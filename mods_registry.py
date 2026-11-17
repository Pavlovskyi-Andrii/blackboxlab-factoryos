"""Mods & skills (T-MODS, owner 2026-11-15): one place that lists every switchable skill or feature of FactoryOS.

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

# Video duel (T-MODS-D): two takes by a built-in FactoryOS tool (A1, A2) against two takes by product-film (B1, B2).
FACTORY_TOOLS = ("revideo", "media-finisher", "explainer-motion")
ARMS = ("a1", "a2", "b1", "b2")
DUEL_ID_RE = re.compile(r"^D-\d{4}$")
MAX_DUELS = 30
START_HOLD = 120
MAX_VIDEO = 80 * 1024 * 1024   # one take; product-film's 1080p web cut is a few MB
FILM_ROOT = "/tmp/factoryos-films"   # where the worker's product-film run leaves its film (never committed)
URL_RE = re.compile(r"^(https?://[^\s<>\"']{3,500}|/[A-Za-z0-9/_.?=&%-]{1,300})$")


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


def _clean_text(value, limit: int) -> str:
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(value or "")).replace("\r", "").strip()[:limit]


def arm_tool(duel: dict, arm: str) -> str:
    return duel["factory_tool"] if arm.startswith("a") else "product-film"


def verdict(duel: dict) -> dict:
    """A against B only when all four takes are scored; never a winner from partial data."""
    scores = {a: (duel["arms"][a].get("score")) for a in ARMS}
    missing = [a for a, v in scores.items() if v is None]
    if missing:
        return {"ready": False, "missing": missing}
    avg_a, avg_b = (scores["a1"] + scores["a2"]) / 2, (scores["b1"] + scores["b2"]) / 2
    winner = "tie" if avg_a == avg_b else ("a" if avg_a > avg_b else "b")
    return {"ready": True, "avg_a": avg_a, "avg_b": avg_b, "winner": winner,
            "winner_tool": "" if winner == "tie" else arm_tool(duel, winner + "1")}


def job_brief(duel: dict, arm: str) -> str:
    tool = arm_tool(duel, arm)
    return (f"ВИДЕО-ДУЭЛЬ {duel['id']}, дубль {arm.upper()} (инструмент: {tool}). ТОЛЬКО ЧЕРНОВИК: не публиковать, "
            "не запускать платные провайдеры, публикация только через обычное одобрение владельца.\n"
            f"Сделай вариант {arm[-1]} из 2 — он должен отличаться от второго дубля хуком или подачей.\n\n"
            f"Бриф: {duel['brief']}")


def ticket_body(duel: dict, arm: str) -> str:
    return (f"Видео-дуэль {duel['id']}, дубль {arm.upper()}: сделай короткий продуктовый ролик скиллом "
            "/product-film:product-film (он загружен в этот запуск).\n"
            f"Это вариант {arm[-1]} из 2: второй дубль B должен отличаться маршрутом или подачей "
            "(например, B1 — walkthrough в kinetic-стиле, B2 — reel или paper collage).\n"
            f"Папка фильма: {FILM_ROOT}/{duel['id']}-{arm}/. Готовый ролик сохрани ровно как "
            f"{FILM_ROOT}/{duel['id']}-{arm}/final.mp4 (H.264 MP4, 9:16, до 80 МБ): воркер сам загрузит его в "
            "FactoryOS, где владелец смотрит и оценивает дубль. Видео в git не коммитить.\n"
            "Ролик должен быть настоящим рендером: не подставляй заглушки, пустые кадры или чужие видео.\n"
            "Ничего не публиковать и не загружать во внешние сервисы, платные API и покупки запрещены.\n"
            "Если нет Node 18+, ffmpeg или Playwright — верни BLOCKED и назови, чего не хватает.\n"
            "В итоговом ответе: пути к MP4, постеру и review-странице.\n\n"
            f"Бриф: {duel['brief']}")


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


def is_mp4(head: bytes) -> bool:
    """ISO base media (MP4/MOV) files start with a box whose type at bytes 4..8 is 'ftyp'."""
    return len(head) >= 12 and head[4:8] == b"ftyp"


def duel_view(duel: dict, live: Callable[[str, str], Optional[dict]]) -> dict:
    arms = []
    for a in ARMS:
        row = dict(duel["arms"][a])
        ref = row.get("job_id") or row.get("ticket_id") or ""
        row.update(id=a, tool=arm_tool(duel, a), live=live(a, ref) if ref else None)
        row.pop("starting", None)
        video = row.get("video")
        if isinstance(video, dict):
            row["video"] = {k: video.get(k) for k in ("size", "sha256", "at", "by")}
            row["video_url"] = f"/api/factory/mods/duels/{duel['id']}/arms/{a}/video?v={str(video.get('sha256'))[:12]}"
        arms.append(row)
    return {"id": duel["id"], "title": duel["title"], "brief": duel["brief"], "factory_tool": duel["factory_tool"],
            "created_at": duel["created_at"], "arms": arms, "verdict": verdict(duel)}


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
                        create_job: Optional[Callable] = None, create_ticket: Optional[Callable] = None,
                        job_state: Optional[Callable[[str], Optional[dict]]] = None,
                        ticket_state: Optional[Callable[[str], Optional[dict]]] = None,
                        media_dir: Optional[Path] = None) -> None:
    """create_job(title, brief, fmt) -> awaitable job id; create_ticket(title, body, source_key) -> ticket id.
    job_state / ticket_state(id) -> small dict or None, shown live on each duel arm."""
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

        def live(arm: str, ref: str):
            try:
                fn = job_state if arm.startswith("a") else ticket_state
                return fn(ref) if fn else None
            except Exception:
                return None
        duels = sorted((data.get("duels") or {}).values(), key=lambda d: d.get("created_at") or 0, reverse=True)
        out["duels"] = [duel_view(d, live) for d in duels]
        return out

    def duel_or_404(data: dict, duel_id: str) -> dict:
        duel = (data.get("duels") or {}).get(duel_id) if DUEL_ID_RE.fullmatch(duel_id or "") else None
        if not duel:
            raise HTTPException(404, "unknown duel")
        return duel

    def arm_ok(arm: str) -> str:
        if arm not in ARMS:
            raise HTTPException(404, "unknown arm")
        return arm

    @app.get("/api/factory/mods")
    def mods_list(request: Request):
        owner(request)
        return full_view()

    @app.post("/api/factory/mods/duels")
    async def duel_create(request: Request):
        owner(request)
        b = await body(request)
        title, brief = _clean_text(b.get("title"), 120), _clean_text(b.get("brief"), 3000)
        tool = str(b.get("factory_tool") or "revideo")
        if not title or not brief:
            raise HTTPException(422, "title and brief are required")
        if tool not in FACTORY_TOOLS:
            raise HTTPException(422, "factory_tool must be revideo, media-finisher or explainer-motion")

        def fn(data):
            duels = data.setdefault("duels", {})
            if len(duels) >= MAX_DUELS:
                raise HTTPException(409, "too many duels")
            data["duel_seq"] = int(data.get("duel_seq") or 0) + 1
            duel_id = f"D-{data['duel_seq']:04d}"
            duels[duel_id] = {"id": duel_id, "title": title, "brief": brief, "factory_tool": tool, "created_at": _now(),
                              "arms": {a: {"job_id": "", "ticket_id": "", "result_url": "", "score": None} for a in ARMS}}
        store.change(fn)
        return full_view()

    @app.post("/api/factory/mods/duels/{duel_id}/arms/{arm}/start")
    async def duel_start(duel_id: str, arm: str, request: Request):
        """A arm → an ordinary draft job; B arm → a Claude Relay ticket that loads product-film. Idempotent."""
        owner(request)
        arm_ok(arm)
        if arm.startswith("b") and not store.enabled("product-film"):
            raise HTTPException(409, "switch product-film on first")
        if (arm.startswith("a") and not create_job) or (arm.startswith("b") and not create_ticket):
            raise HTTPException(503, "this server cannot start that arm")
        now = _now()

        def reserve(data):
            duel = duel_or_404(data, duel_id)
            row = duel["arms"][arm]
            if row.get("job_id") or row.get("ticket_id"):
                return None
            if now - int(row.get("starting") or 0) < START_HOLD:
                raise HTTPException(409, "already starting")
            row["starting"] = now
            return dict(duel)
        duel = store.change(reserve)
        if duel is None:
            return full_view()
        title = f"{duel['id']} {arm.upper()} · {duel['title']}"[:180]
        try:
            if arm.startswith("a"):
                ref = await create_job(title, job_brief(duel, arm), "Shorts")
            else:
                ref = create_ticket(title, ticket_body(duel, arm), f"mods-duel:{duel['id']}:{arm}")
        except HTTPException:
            store.change(lambda data: duel_or_404(data, duel_id)["arms"][arm].pop("starting", None))
            raise
        except Exception as exc:
            store.change(lambda data: duel_or_404(data, duel_id)["arms"][arm].pop("starting", None))
            raise HTTPException(502, f"could not start {arm}: {type(exc).__name__}")

        def attach(data):
            row = duel_or_404(data, duel_id)["arms"][arm]
            row["job_id" if arm.startswith("a") else "ticket_id"] = str(ref)
            row.pop("starting", None)
        store.change(attach)
        if arm.startswith("b"):
            store.use("product-film")
        return full_view()

    @app.post("/api/factory/mods/duels/{duel_id}/arms/{arm}")
    async def duel_arm_update(duel_id: str, arm: str, request: Request):
        owner(request)
        arm_ok(arm)
        b = await body(request)
        patch = {}
        if "result_url" in b:
            url = _clean_text(b.get("result_url"), 500)
            if url and not URL_RE.fullmatch(url):
                raise HTTPException(422, "result_url must be an http(s) link or a FactoryOS path")
            patch["result_url"] = url
        if "score" in b:
            score = b.get("score")
            if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 1 <= score <= 5):
                raise HTTPException(422, "score must be 1-5 or null")
            patch["score"] = score
        if not patch:
            raise HTTPException(422, "nothing to update")
        def fn(data):
            row = duel_or_404(data, duel_id)["arms"][arm]
            after = {**row, **patch}
            if after.get("score") is not None and not (after.get("job_id") or after.get("ticket_id") or after.get("result_url")
                                                       or after.get("video")):
                raise HTTPException(409, "start the take or add its link before scoring it")
            row.update(patch)
        store.change(fn)
        return full_view()

    def video_path(duel_id: str, arm: str) -> Path:
        if media_dir is None:
            raise HTTPException(503, "this server stores no duel videos")
        return Path(media_dir) / f"{duel_id}-{arm}.mp4"

    async def read_capped(stream) -> bytes:
        chunks, size = [], 0
        async for chunk in stream:
            size += len(chunk)
            if size > MAX_VIDEO:
                raise HTTPException(413, "video larger than 80 MB")
            chunks.append(chunk)
        return b"".join(chunks)

    def store_video(duel_id: str, arm: str, data: bytes, by: str, ticket: str = "") -> None:
        """Only a real MP4 is kept; the arm records size, sha256 and who uploaded it, so a take is never fake."""
        import hashlib
        if not is_mp4(data[:16]):
            raise HTTPException(422, "not an MP4 video")
        path = video_path(duel_id, arm)

        def check(data_):
            row = duel_or_404(data_, duel_id)["arms"][arm_ok(arm)]
            if ticket and row.get("ticket_id") != ticket:
                raise HTTPException(409, "ticket does not belong to this take")
            return row
        store.change(check)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
        meta = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "at": _now(), "by": by}
        store.change(lambda data_: check(data_).update(video=meta))

    @app.post("/api/factory/mods/duels/{duel_id}/arms/{arm}/video")
    async def duel_video_owner_upload(duel_id: str, arm: str, request: Request):
        """Owner uploads a take made anywhere (e.g. an A take from Media Finisher) as one MP4 file."""
        owner(request)
        arm_ok(arm)
        form = await request.form()
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise HTTPException(422, "file required")
        data = b""
        while True:
            chunk = await upload.read(1024 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) > MAX_VIDEO:
                raise HTTPException(413, "video larger than 80 MB")
        store_video(duel_id, arm, data, "owner")
        return full_view()

    @app.get("/api/factory/mods/duels/{duel_id}/arms/{arm}/video")
    def duel_video(duel_id: str, arm: str, request: Request):
        owner(request)
        arm_ok(arm)
        duel_or_404(store.read(), duel_id)
        path = video_path(duel_id, arm)
        if not path.is_file():
            raise HTTPException(404, "no video for this take")
        from fastapi.responses import FileResponse
        return FileResponse(path, media_type="video/mp4", headers={"Cache-Control": "private, max-age=3600"})

    @app.post("/api/mods/worker/duels/{duel_id}/arms/{arm}/video")
    async def duel_video_worker_upload(duel_id: str, arm: str, request: Request, ticket: str = ""):
        """The worker's runner (not the agent) uploads the product-film render of a B take it ran."""
        worker(request)
        if arm_ok(arm)[0] != "b" or not re.fullmatch(r"R-\d{4,}", ticket or ""):
            raise HTTPException(422, "a B take and its Relay ticket are required")
        store_video(duel_id, arm, await read_capped(request.stream()), "worker", ticket)
        return {"ok": True}

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

    # Registered last: its {mod_id} would otherwise capture /api/factory/mods/duels.
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
