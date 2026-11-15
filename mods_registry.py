"""Mods & skills (T-611, owner 2026-11-15): one place that lists every switchable skill or feature of FactoryOS.

"Подключенные фичи и скиллы": the owner switches a mod on or off with one button and sees whether it works
(usage counter, last use) and whether it helps (worker runs with the mod against runs without it).

- The catalog is code. Toggleable mods: poteto-mode, grilling (Claude worker skills, loaded per run with
  ``--plugin-dir mods/<plugin>``), product-film (video tool, arm B of the video duel) and brand-strategy (the
  7-step passport → Master Brief that enters content agents' prompts). Built-in tools are listed as always on.
- State lives in one JSON file under DATA_DIR (flock + atomic replace, the brand-strategy store pattern).
  Unreadable state never blocks content work: ``enabled()`` falls back to each mod's default.
- Only the owner can switch. The worker reads the enabled set and reports runs with its worker token.
- Numbers are only what was recorded: a comparison needs runs on both sides, otherwise the API says so.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException, Request

CATALOG = (
    {"id": "poteto-mode", "kind": "dev", "toggle": True, "default": False, "plugin": "pstack",
     "invoke": "/pstack:poteto-mode", "source": "github.com/cursor/plugins (pstack 0.15.42)", "license": "MIT"},
    {"id": "grilling", "kind": "dev", "toggle": True, "default": False, "plugin": "grilling",
     "source": "github.com/mattpocock/skills", "license": "MIT"},
    {"id": "brand-strategy", "kind": "content", "toggle": True, "default": True,
     "source": "FactoryOS (brand_strategy.py)", "license": ""},
    {"id": "product-film", "kind": "video", "toggle": True, "default": False, "plugin": "product-film",
     "source": "github.com/display-dev/product-film 0.2.0", "license": "MIT"},
    {"id": "revideo", "kind": "video", "toggle": False, "default": True, "source": "FactoryOS", "license": ""},
    {"id": "media-finisher", "kind": "video", "toggle": False, "default": True, "source": "FactoryOS", "license": ""},
    {"id": "explainer-motion", "kind": "video", "toggle": False, "default": True, "source": "FactoryOS", "license": ""},
    {"id": "peer-review", "kind": "review", "toggle": False, "default": True,
     "source": "FactoryOS (peer_review.py, Gemini free tier)", "license": ""},
)
BY_ID = {m["id"]: m for m in CATALOG}
RUN_RESULTS = ("done", "blocked", "failed")
RUN_KINDS = ("roadmap", "relay")
MAX_HISTORY = 500
MAX_RUNS = 1000
RUN_ID_RE = re.compile(r"^[A-Za-z0-9:._-]{1,120}$")


def _now() -> int:
    return int(time.time())


class ModsStore:
    def __init__(self, path: Path):
        self.path, self._thread_lock = Path(path), threading.Lock()

    @contextlib.contextmanager
    def lock(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, open(str(self.path) + ".lock", "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("mods state is not an object")
        return data

    def _save(self, data: dict) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def read(self) -> dict:
        with self.lock():
            return self._load()

    def change(self, fn):
        with self.lock():
            data = self._load()
            out = fn(data)
            self._save(data)
            return out

    # --- queries -------------------------------------------------------------------------------------------
    @staticmethod
    def _enabled_in(data: dict, mod_id: str) -> bool:
        mod = BY_ID[mod_id]
        if not mod["toggle"]:
            return True
        row = (data.get("state") or {}).get(mod_id)
        return bool(row["enabled"]) if isinstance(row, dict) and "enabled" in row else bool(mod["default"])

    def enabled(self, mod_id: str) -> bool:
        """Never raises: unreadable state means the mod's default (content work must not stop on a bad file)."""
        try:
            return self._enabled_in(self.read(), mod_id)
        except Exception:
            return bool(BY_ID[mod_id]["default"])

    def enabled_ids(self) -> list:
        data = self.read()
        return [m["id"] for m in CATALOG if m["toggle"] and self._enabled_in(data, m["id"])]

    # --- writes --------------------------------------------------------------------------------------------
    def set_enabled(self, mod_id: str, enabled: bool, by: str) -> dict:
        def fn(data):
            was = self._enabled_in(data, mod_id)
            if was == enabled:
                return {"changed": False}
            now = _now()
            data.setdefault("state", {})[mod_id] = {"enabled": enabled, "at": now, "by": by}
            hist = data.setdefault("history", [])
            hist.append({"id": mod_id, "enabled": enabled, "at": now, "by": by})
            del hist[:-MAX_HISTORY]
            return {"changed": True}
        return self.change(fn)

    def use(self, mod_id: str, n: int = 1) -> None:
        """Count one real use (a prompt carried the Master Brief, a run loaded the plugin). Never raises."""
        try:
            def fn(data):
                row = data.setdefault("uses", {}).setdefault(mod_id, {"count": 0, "last": 0})
                row["count"] = int(row.get("count") or 0) + n
                row["last"] = _now()
            self.change(fn)
        except Exception:
            pass

    def record_run(self, run: dict) -> dict:
        def fn(data):
            runs = data.setdefault("runs", [])
            if any(r.get("run_id") == run["run_id"] for r in runs):
                return {"recorded": False}
            runs.append(run)
            del runs[:-MAX_RUNS]
            if run["applied"]:
                for mod_id in run["mods"]:
                    row = data.setdefault("uses", {}).setdefault(mod_id, {"count": 0, "last": 0})
                    row["count"] = int(row.get("count") or 0) + 1
                    row["last"] = run["at"]
            return {"recorded": True}
        return self.change(fn)


def _side(runs: list) -> dict:
    n = len(runs)
    out = {"runs": n, **{r: sum(1 for x in runs if x["result"] == r) for r in RUN_RESULTS}}
    out["done_rate"] = round(out["done"] / n, 3) if n else None
    durations = [float(x["duration_seconds"]) for x in runs if x.get("duration_seconds")]
    out["avg_minutes"] = round(sum(durations) / len(durations) / 60, 1) if durations else None
    return out


def compare(runs: list, mod_id: str) -> dict:
    """Worker runs that really loaded the mod against runs without it. A run whose mods could not be applied
    (server unreachable, CLI too old) counts as "without"."""
    with_mod = [r for r in runs if r.get("applied") and mod_id in (r.get("mods") or [])]
    without = [r for r in runs if not (r.get("applied") and mod_id in (r.get("mods") or []))]
    a, b = _side(with_mod), _side(without)
    ready = a["runs"] >= 3 and b["runs"] >= 3
    delta = round(a["done"] / a["runs"] - b["done"] / b["runs"], 3) if ready else None
    return {"with": a, "without": b, "ready": ready, "done_rate_delta": delta}


def view(data: dict) -> dict:
    runs = [r for r in data.get("runs") or [] if isinstance(r, dict)]
    hist = [h for h in data.get("history") or [] if isinstance(h, dict)]
    mods = []
    for m in CATALOG:
        row = (data.get("state") or {}).get(m["id"]) or {}
        uses = (data.get("uses") or {}).get(m["id"]) or {}
        item = {"id": m["id"], "kind": m["kind"], "toggle": m["toggle"], "default": m["default"],
                "enabled": ModsStore._enabled_in(data, m["id"]), "since": row.get("at") or 0, "by": row.get("by") or "",
                "uses": int(uses.get("count") or 0), "last_used": int(uses.get("last") or 0),
                "plugin": m.get("plugin", ""), "source": m["source"], "license": m["license"],
                "history": [h for h in hist if h.get("id") == m["id"]][-5:][::-1]}
        if m["kind"] == "dev":
            item["compare"] = compare(runs, m["id"])
        mods.append(item)
    last = sorted(runs, key=lambda r: r.get("at") or 0)[-8:][::-1]
    return {"mods": mods, "runs_total": len(runs), "recent_runs": last}


def clean_run(body: dict) -> dict:
    if not isinstance(body, dict):
        raise HTTPException(400, "json object required")
    run_id = str(body.get("run_id") or "")
    if not RUN_ID_RE.fullmatch(run_id):
        raise HTTPException(422, "run_id required")
    result = str(body.get("result") or "").lower()
    if result not in RUN_RESULTS:
        raise HTTPException(422, "result must be done, blocked or failed")
    kind = str(body.get("kind") or "roadmap")
    if kind not in RUN_KINDS:
        raise HTTPException(422, "unknown run kind")
    mods = body.get("mods") or []
    if not isinstance(mods, list) or any(m not in BY_ID or not BY_ID[m].get("plugin") for m in mods):
        raise HTTPException(422, "unknown mod in run")
    try:
        duration = max(0.0, min(86400.0, float(body.get("duration_seconds") or 0)))
    except (TypeError, ValueError):
        raise HTTPException(422, "duration_seconds must be a number")
    return {"run_id": run_id, "kind": kind, "task": str(body.get("task") or "")[:40], "result": result,
            "duration_seconds": duration, "mods": sorted(set(mods)), "applied": bool(body.get("applied")),
            "note": re.sub(r"[\x00-\x1f]", " ", str(body.get("note") or ""))[:200], "at": _now()}


def worker_plan(store: ModsStore) -> dict:
    """What the worker loads for its next run: plugin folders of the switched-on worker mods."""
    on = set(store.enabled_ids())
    plugins = [{"id": m["id"], "plugin": m["plugin"], "invoke": m.get("invoke", "")}
               for m in CATALOG if m["id"] in on and m.get("plugin") and m["kind"] in ("dev", "video")]
    return {"enabled": sorted(on), "plugins": plugins}


def install_mods_routes(app, store: ModsStore, *, identity: Callable, worker_auth: Callable[[Request], bool],
                        extra: Optional[Callable[[dict], dict]] = None) -> None:
    def owner(request: Request) -> str:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")
        return "owner"

    def worker(request: Request) -> None:
        if not worker_auth(request):
            raise HTTPException(401, "worker token required")

    async def body(request: Request) -> dict:
        try:
            b = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        if not isinstance(b, dict):
            raise HTTPException(400, "json object required")
        return b

    def full_view() -> dict:
        try:
            data = store.read()
        except Exception as exc:
            raise HTTPException(503, f"mods state unreadable: {type(exc).__name__}")
        out = view(data)
        if extra:
            out.update(extra(data))
        return out

    @app.get("/api/factory/mods")
    def mods_list(request: Request):
        owner(request)
        return full_view()

    @app.post("/api/factory/mods/{mod_id}")
    async def mods_toggle(mod_id: str, request: Request):
        by = owner(request)
        mod = BY_ID.get(mod_id)
        if not mod:
            raise HTTPException(404, "unknown mod")
        if not mod["toggle"]:
            raise HTTPException(409, "built-in tool: always on")
        b = await body(request)
        if not isinstance(b.get("enabled"), bool):
            raise HTTPException(422, "enabled must be true or false")
        store.set_enabled(mod_id, b["enabled"], by)
        return full_view()

    @app.get("/api/mods/worker/plan")
    def mods_worker_plan(request: Request):
        worker(request)
        try:
            return worker_plan(store)
        except Exception as exc:
            raise HTTPException(503, f"mods state unreadable: {type(exc).__name__}")

    @app.post("/api/mods/worker/run")
    async def mods_worker_run(request: Request):
        worker(request)
        return store.record_run(clean_run(await body(request)))
