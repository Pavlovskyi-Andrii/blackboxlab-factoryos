"""T-740 Ops relay (server side): a small, audited queue of fixed EC2 operations for the Claude lane.

Pull-based: nothing on EC2 listens. A Claude session asks through MCP (``ops_request`` / ``ops_result``, Claude lane
token only); the root ops agent on the EC2 host (``autopilot/ops_agent.py``, a 30 s timer) claims a request with the
worker credential it already has, runs the fixed argv lists from ``ops_catalog.plan`` and posts redacted output back.

Gates, all server side and fail closed: ``FACTORY_OPS_RELAY_ENABLED`` (off by default), op classes
(``FACTORY_OPS_RELAY_CLASSES``, default read + restart), lane = claude, rolling-24 h limits, at most a few requests
waiting. Every request is kept (audit) and shown to the owner; restarts and installs also notify the owner in Telegram.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from fastapi import HTTPException, Request

import ops_catalog as cat

ENABLED_ENV = "FACTORY_OPS_RELAY_ENABLED"
CLASSES_ENV = "FACTORY_OPS_RELAY_CLASSES"
LANES = frozenset({"claude"})
MAX_PER_DAY = 30
MAX_RESTARTS_PER_UNIT_PER_DAY = 6
MAX_OPEN = 5
QUEUE_EXPIRES_SECONDS = 10 * 60
CLAIM_LEASE_SECONDS = 3 * 60
KEEP = 500
DAY = 24 * 3600
NOTIFY_CLASSES = frozenset({"restart", "install"})
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
_ID = re.compile(r"^ops_[0-9a-f]{12}$")


def enabled(environ: Mapping[str, str] = os.environ) -> bool:
    return str(environ.get(ENABLED_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def allowed_classes(environ: Mapping[str, str] = os.environ) -> tuple:
    return cat.classes_from(environ.get(CLASSES_ENV))


def _iso(ts: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds") if ts else None


def _clean_text(value, limit: int) -> str:
    text = " ".join(re.sub(r"[\x00-\x1f\x7f]", " ", str(value or "")).split())
    return text[:limit]


class OpsStore:
    """JSON file in DATA_DIR; one lock; the last ``KEEP`` requests are the audit log."""

    def __init__(self, data_dir: Path, *, clock: Callable[[], float] = time.time,
                 environ: Mapping[str, str] = os.environ, known_secrets: Callable[[], Iterable[str]] = lambda: ()):
        self.path = Path(data_dir) / "ops_relay.json"
        self.clock = clock
        self.environ = environ
        self.known_secrets = known_secrets
        self.lock = threading.Lock()

    # -------------------------------------------------------------------------------------------- storage
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        data.setdefault("requests", [])
        data.setdefault("executor", {})
        data.setdefault("outbox", [])
        return data

    def _save(self, data: dict) -> None:
        data["requests"] = data["requests"][-KEEP:]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _sweep(self, data: dict, now: float) -> list:
        """Expire requests nobody claimed and claims nobody finished. Returns the requests that just ended."""
        ended = []
        for r in data["requests"]:
            if r["status"] == "queued" and now - r["created_at"] > QUEUE_EXPIRES_SECONDS:
                r.update(status="expired", finished_at=now,
                         error="not claimed within 10 min: the EC2 ops agent is not installed or offline (T-740-H)")
                ended.append(r)
            elif r["status"] == "claimed" and now - (r.get("claimed_at") or now) > CLAIM_LEASE_SECONDS:
                r.update(status="failed", finished_at=now, error="executor_lost: claimed but no result within 3 min")
                ended.append(r)
        data["outbox"].extend(self._ended_note(r) for r in ended if r.get("class") in NOTIFY_CLASSES)
        return ended

    def drain_notes(self) -> list:
        """Owner notifications waiting to be sent (restart / install queued or ended). Taken once."""
        with self.lock:
            data = self._load()
            self._sweep(data, self.clock())
            notes, data["outbox"] = data["outbox"][-20:], []
            if notes:
                self._save(data)
        return notes

    def _redact(self, text: str) -> str:
        return cat.cap(cat.redact(text, self.known_secrets()))

    # -------------------------------------------------------------------------------------------- agent side
    def gate(self) -> dict:
        return {"enabled": enabled(self.environ), "classes": list(allowed_classes(self.environ))}

    def request(self, lane: str, args: dict) -> dict:
        """→ public view (a restart / install also queues an owner notification). Raises PermissionError / ValueError with a caller message."""
        if lane not in LANES:
            raise PermissionError("ops_request is for the Claude lane token only (FACTORY_MCP_LANE_TOKEN_CLAUDE)")
        if not enabled(self.environ):
            raise PermissionError("Ops relay is off: the owner sets FACTORY_OPS_RELAY_ENABLED=1 in Render (T-740-H)")
        args = dict(args or {})
        key = str(args.pop("idempotency_key", "") or "").strip()
        reason = _clean_text(args.pop("reason", ""), 300)
        if not _KEY.match(key):
            raise ValueError("idempotency_key is required: 1-80 chars of letters, digits, _ . : -")
        if len(reason) < 3:
            raise ValueError("reason is required (why this op is needed, shown to the owner)")
        unknown = set(args) - {"op", "unit", "minutes", "lines"}
        if unknown:
            raise ValueError("unknown arguments: " + ", ".join(sorted(unknown)))
        req = cat.validate(args)
        klass = cat.OPS_CLASS[req["op"]]
        if klass not in allowed_classes(self.environ):
            raise PermissionError(f"op class '{klass}' is switched off by the owner ({CLASSES_ENV})")
        now = self.clock()
        with self.lock:
            data = self._load()
            ended = self._sweep(data, now)
            same = next((r for r in data["requests"] if r["lane"] == lane and r["idempotency_key"] == key), None)
            if same:
                if any(same.get(k) != req[k] for k in ("op", "unit", "minutes", "lines")):
                    raise ValueError("idempotency_key was already used for a different op")
                if ended:
                    self._save(data)
                return self.view(same, agent=True, data=data)
            recent = [r for r in data["requests"] if now - r["created_at"] < DAY]
            if len(recent) >= MAX_PER_DAY:
                raise PermissionError(f"daily limit reached: {MAX_PER_DAY} ops in 24 h")
            if req["op"] == "restart" and sum(1 for r in recent if r["op"] == "restart"
                                              and r["unit"] == req["unit"]) >= MAX_RESTARTS_PER_UNIT_PER_DAY:
                raise PermissionError(f"restart limit reached: {MAX_RESTARTS_PER_UNIT_PER_DAY} restarts of "
                                      f"{req['unit']} in 24 h; ask the owner")
            if sum(1 for r in data["requests"] if r["status"] in ("queued", "claimed")) >= MAX_OPEN:
                raise PermissionError(f"{MAX_OPEN} ops are already waiting for the EC2 ops agent")
            row = {"id": "ops_" + secrets.token_hex(6), "lane": lane, "idempotency_key": key, "reason": reason,
                   "class": klass, **req, "status": "queued", "created_at": now, "claimed_at": None,
                   "finished_at": None, "exit_code": None, "output": "", "error": "", "duration_ms": None}
            data["requests"].append(row)
            if klass in NOTIFY_CLASSES:
                target = f" {row['unit']}" if row["unit"] else ""
                data["outbox"].append(f"FactoryOS Ops relay: Claude запросил {row['op']}{target} на EC2.\n"
                                      f"Причина: {reason}\nЗапрос {row['id']}; результат придёт отдельным сообщением.")
            self._save(data)
            return self.view(row, agent=True, data=data)

    def result_for_agent(self, lane: str, request_id: str) -> dict:
        if lane not in LANES:
            raise PermissionError("ops_result is for the Claude lane token only (FACTORY_MCP_LANE_TOKEN_CLAUDE)")
        request_id = str(request_id or "").strip()
        if not _ID.match(request_id):
            raise ValueError("id must look like ops_0123456789ab")
        with self.lock:
            data = self._load()
            if self._sweep(data, self.clock()):
                self._save(data)
            row = next((r for r in data["requests"] if r["id"] == request_id), None)
            if not row:
                raise ValueError("unknown ops request id")
            return self.view(row, agent=True, data=data)

    # -------------------------------------------------------------------------------------------- executor side
    def claim(self, node: str = "") -> Optional[dict]:
        """Oldest queued request → claimed (or None). Also records that the executor polled."""
        now = self.clock()
        with self.lock:
            data = self._load()
            self._sweep(data, now)
            data["executor"] = {"last_poll_at": now, "node": _clean_text(node, 80)}
            row = None
            if enabled(self.environ):
                for r in data["requests"]:
                    if r["status"] == "queued" and cat.OPS_CLASS.get(r["op"]) in allowed_classes(self.environ):
                        r.update(status="claimed", claimed_at=now)
                        row = r
                        break
            self._save(data)
        task = None
        if row:
            task = {"id": row["id"], "op": row["op"], "unit": row["unit"], "minutes": row["minutes"],
                    "lines": row["lines"]}
        return task

    def finish(self, request_id: str, body: dict) -> dict:
        """Executor result → stored (redacted again, capped); a restart / install queues an owner notification."""
        request_id = str(request_id or "").strip()
        if not _ID.match(request_id):
            raise ValueError("bad id")
        body = body if isinstance(body, dict) else {}
        status = "done" if body.get("status") == "done" else "failed"
        try:
            exit_code = int(body.get("exit_code")) if body.get("exit_code") is not None else None
        except (TypeError, ValueError):
            exit_code = None
        try:
            duration = max(0, min(int(body.get("duration_ms") or 0), 10 * 60 * 1000))
        except (TypeError, ValueError):
            duration = None
        now = self.clock()
        with self.lock:
            data = self._load()
            row = next((r for r in data["requests"] if r["id"] == request_id), None)
            if not row:
                raise LookupError("unknown ops request id")
            if row["status"] != "claimed":
                raise ValueError(f"request is {row['status']}, not claimed")
            row.update(status=status, finished_at=now, exit_code=exit_code, duration_ms=duration,
                       output=self._redact(body.get("output") or ""),
                       error=_clean_text(self._redact(body.get("error") or ""), 300))
            if row.get("class") in NOTIFY_CLASSES:
                data["outbox"].append(self._ended_note(row))
            self._save(data)
            return self.view(row, data=data)

    @staticmethod
    def _ended_note(row: dict) -> str:
        target = f" {row['unit']}" if row.get("unit") else ""
        word = {"done": "выполнено", "failed": "ошибка", "expired": "не выполнено (агент на EC2 не ответил)"}
        text = (f"FactoryOS Ops relay: {row['op']}{target} — {word.get(row['status'], row['status'])}"
                f" ({row['id']}).")
        if row.get("error"):
            text += "\n" + row["error"][:200]
        tail = [ln for ln in str(row.get("output") or "").splitlines() if ln.strip()][-6:]
        if tail:
            text += "\n" + "\n".join(ln[:160] for ln in tail)
        return text

    # -------------------------------------------------------------------------------------------- views
    def view(self, row: dict, *, agent: bool = False, data: Optional[dict] = None, preview: int = 0) -> dict:
        out = {k: row.get(k) for k in ("id", "op", "unit", "minutes", "lines", "class", "status", "reason",
                                         "exit_code", "error", "duration_ms")}
        out.update(created_at=_iso(row.get("created_at")), claimed_at=_iso(row.get("claimed_at")),
                   finished_at=_iso(row.get("finished_at")))
        output = str(row.get("output") or "")
        out["output"] = output[:preview] + ("…" if len(output) > preview else "") if preview else output
        if not agent:
            out["lane"] = row.get("lane")
            out["idempotency_key"] = row.get("idempotency_key")
        if row["status"] in ("queued", "claimed"):
            out["next"] = "call ops_result again in about 30-60 s"
        if data is not None:
            out["executor_last_poll_at"] = _iso((data.get("executor") or {}).get("last_poll_at"))
        return {k: v for k, v in out.items() if v is not None}

    def owner_board(self, limit: int = 50) -> dict:
        now = self.clock()
        with self.lock:
            data = self._load()
            if self._sweep(data, now):
                self._save(data)
        rows = data["requests"]
        recent = [r for r in rows if now - r["created_at"] < DAY]
        last_poll = (data.get("executor") or {}).get("last_poll_at")
        restarts = {}
        for r in recent:
            if r["op"] == "restart":
                restarts[r["unit"]] = restarts.get(r["unit"], 0) + 1
        return {
            **self.gate(),
            "limits": {"per_day": MAX_PER_DAY, "restarts_per_unit_per_day": MAX_RESTARTS_PER_UNIT_PER_DAY,
                       "max_open": MAX_OPEN},
            "usage": {"last_24h": len(recent), "restarts_last_24h": restarts},
            "executor": {"last_poll_at": _iso(last_poll),
                         "online": bool(last_poll) and now - float(last_poll) < 180,
                         "node": (data.get("executor") or {}).get("node") or ""},
            "requests": [self.view(r, preview=4000) for r in reversed(rows[-limit:])],
            "catalog": {"ops": cat.OPS_CLASS, "read_units": list(cat.READ_UNITS),
                        "restart_units": list(cat.RESTART_UNITS)},
        }

    def owner_request(self, request_id: str) -> dict:
        with self.lock:
            data = self._load()
        row = next((r for r in data["requests"] if r["id"] == str(request_id)), None)
        if not row:
            raise LookupError("unknown ops request id")
        return self.view(row, data=data)


# ------------------------------------------------------------------------------------------------ MCP
MCP_TOOLS = [
    {
        "name": "ops_request",
        "description": "Queue one fixed operation on the FactoryOS EC2 worker host (no shell, no free commands). "
                       "ops: status / journal (unit, minutes<=180, lines<=300) / host (memory, disk, uptime, Chrome "
                       "processes, checkout vs origin/main) / restart (reset-failed + restart of the Surfer or Claude "
                       "worker) / sync_checkout (fast-forward the worker checkout) / install_surfer_unit. The EC2 ops "
                       "agent picks it up within ~30 s; read the result with ops_result. Output is redacted. Limits: "
                       "30 ops and 6 restarts per unit per 24 h; restarts notify the owner. Claude lane only; off "
                       "until the owner sets FACTORY_OPS_RELAY_ENABLED=1.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "op": {"type": "string", "enum": list(cat.OPS_CLASS)},
                "unit": {"type": "string", "enum": list(cat.READ_UNITS)},
                "minutes": {"type": "integer", "minimum": 1, "maximum": cat.MAX_MINUTES},
                "lines": {"type": "integer", "minimum": 1, "maximum": cat.MAX_LINES},
                "reason": {"type": "string", "maxLength": 300},
                "idempotency_key": {"type": "string", "maxLength": 80},
            },
            "required": ["op", "reason", "idempotency_key"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ops_result",
        "description": "Status and redacted output of an ops_request: queued / claimed / done / failed / expired "
                       "(expired = the EC2 ops agent did not pick it up within 10 min). Claude lane only.",
        "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}, "required": ["id"],
                        "additionalProperties": False},
    },
]
MCP_TOOL_NAMES = frozenset(t["name"] for t in MCP_TOOLS)


def call_tool(store: OpsStore, name: str, args: dict, lane: str, notify: Callable[[str], object] = lambda t: None) -> dict:
    """MCP entry point. Errors come back as ValueError (the /mcp handler turns them into isError text)."""
    try:
        if name == "ops_request":
            return store.request(lane, args or {})
        if name == "ops_result":
            return store.result_for_agent(lane, (args or {}).get("id"))
    except PermissionError as exc:
        raise ValueError(str(exc))
    finally:
        for note in store.drain_notes():
            try:
                notify(note)
            except Exception:
                pass
    raise ValueError("unknown ops tool")


# ------------------------------------------------------------------------------------------------ routes
def install_routes(app, *, store: OpsStore, authorize_worker: Callable[[Request], bool], identity: Callable,
                   notify: Callable[[str], object]) -> None:
    import asyncio

    def owner(request: Request) -> None:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    def worker(request: Request) -> None:
        if not authorize_worker(request):
            raise HTTPException(401, "worker token required")

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            data = {}
        return data if isinstance(data, dict) else {}

    async def send() -> None:
        for note in store.drain_notes():
            try:
                await asyncio.to_thread(notify, note)
            except Exception:
                pass

    @app.post("/api/ops/worker/claim")
    async def ops_worker_claim(request: Request):
        worker(request)
        body = await body_of(request)
        task = store.claim(str(body.get("node") or ""))
        await send()
        return {"task": task}

    @app.post("/api/ops/worker/result/{request_id}")
    async def ops_worker_result(request_id: str, request: Request):
        worker(request)
        body = await body_of(request)
        try:
            view = store.finish(request_id, body)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        await send()
        return {"ok": True, "status": view["status"]}

    @app.get("/api/ops/owner")
    async def ops_owner_board(request: Request):
        owner(request)
        board = store.owner_board()
        await send()
        return board

    @app.get("/api/ops/owner/{request_id}")
    def ops_owner_request(request_id: str, request: Request):
        owner(request)
        try:
            return store.owner_request(request_id)
        except LookupError as exc:
            raise HTTPException(404, str(exc))
