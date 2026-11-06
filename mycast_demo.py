"""MyCast public demo: a ~15 s two-host sample voiced by Gemini (owner decision 2026-11-06: up to 30 per day).

Guards, all server-side:
- Only a short demo script is accepted. At most 2 lines and 420 characters, and the first line must open with the
  fixed "this is a MyCast demo" sentence, so the endpoint is not a general free TTS service.
- One global daily cap (default 30 new generations per UTC day) and a per-client cap (default 5). Cached results are
  free: the same script and language are voiced once and then served from disk.
- One generation at a time. A job reports its real stage (queued, voicing, ready, failed). The percentage is an
  estimate from elapsed time against a typical duration, capped at 95 % until the audio really exists.
- No key, cap reached or a Gemini error give a stated reason and no audio; the page falls back to the browser voice.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

DAILY_CAP = int(os.environ.get("MYCAST_DEMO_DAILY_CAP", "30") or 30)
PER_CLIENT_CAP = int(os.environ.get("MYCAST_DEMO_PER_CLIENT_CAP", "5") or 5)
MAX_LINES = 2
MAX_CHARS = 420
TYPICAL_SECONDS = 14.0
MAX_CACHE_FILES = 300
INTROS = ("Це демо MyCast, а не справжній випуск.", "Это демо MyCast, а не настоящий выпуск.",
          "This is a MyCast demo, not a real episode.")
LANGUAGES = ("uk", "ru", "en")


class DemoRefused(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _clean(text: Any) -> str:
    return re.sub(r"[\u0000-\u001f<>]", " ", str(text or "")).strip()


def validate_script(lines: Any, language: Any) -> tuple[list[tuple[str, str]], str]:
    if language not in LANGUAGES:
        raise DemoRefused("bad_language")
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise DemoRefused("bad_script")
    out: list[tuple[str, str]] = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict) or line.get("host") not in ("A", "B"):
            raise DemoRefused("bad_script")
        text = _clean(line.get("text"))
        if not text:
            raise DemoRefused("bad_script")
        out.append((line["host"], text))
    if sum(len(t) for _, t in out) > MAX_CHARS:
        raise DemoRefused("script_too_long")
    if not out[0][1].startswith(INTROS):
        raise DemoRefused("not_a_demo")  # keeps the endpoint from being a free general-purpose voice service
    return out, language


def pcm_to_wav(pcm: bytes, rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class DemoService:
    def __init__(self, root: Path, *, api_key: Callable[[], str], tts: Callable, clock: Callable[[], float] = time.time,
                 daily_cap: int = DAILY_CAP, per_client_cap: int = PER_CLIENT_CAP, run_async: bool = True):
        self.root = Path(root)
        self.api_key, self.tts, self.clock = api_key, tts, clock
        self.daily_cap, self.per_client_cap, self.run_async = daily_cap, per_client_cap, run_async
        self._lock = threading.Lock()        # guards jobs and the counter file
        self._voice = threading.Lock()       # one Gemini generation at a time
        self.jobs: dict[str, dict] = {}

    # --- counters (persisted, one file per UTC day) ---
    def _day(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def _counts_path(self) -> Path:
        return self.root / f"count-{self._day()}.json"

    def _load_counts(self) -> dict:
        try:
            data = json.loads(self._counts_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"total": 0, "clients": {}}
        except (OSError, ValueError):
            return {"total": 0, "clients": {}}

    def _save_counts(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._counts_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        os.replace(tmp, self._counts_path())

    def remaining(self) -> int:
        with self._lock:
            return max(0, self.daily_cap - int(self._load_counts().get("total", 0)))

    # --- jobs ---
    def _cache_path(self, key: str) -> Path:
        return self.root / f"{key}.wav"

    def start(self, lines: Any, language: Any, client: str) -> dict:
        script, lang = validate_script(lines, language)
        key = hashlib.sha256(json.dumps([script, lang], ensure_ascii=False).encode()).hexdigest()[:32]
        now = self.clock()
        if self._cache_path(key).exists():
            job = {"id": uuid.uuid4().hex, "key": key, "state": "ready", "started": now, "finished": now, "cached": True}
            with self._lock:
                self.jobs[job["id"]] = job
            return self.view(job["id"])
        if not self.api_key():
            raise DemoRefused("not_configured", 503)
        client = hashlib.sha256(str(client or "?").encode()).hexdigest()[:16]  # never store raw addresses
        with self._lock:
            counts = self._load_counts()
            if int(counts.get("total", 0)) >= self.daily_cap:
                raise DemoRefused("daily_limit", 429)
            clients = counts.setdefault("clients", {})
            if int(clients.get(client, 0)) >= self.per_client_cap:
                raise DemoRefused("client_limit", 429)
            counts["total"] = int(counts.get("total", 0)) + 1
            clients[client] = int(clients.get(client, 0)) + 1
            self._save_counts(counts)
            job = {"id": uuid.uuid4().hex, "key": key, "state": "queued", "started": now, "finished": None, "cached": False}
            self.jobs[job["id"]] = job
            for old in [j for j, v in self.jobs.items() if now - v["started"] > 3600]:
                self.jobs.pop(old, None)
        args = (job["id"], script, lang)
        if self.run_async:
            threading.Thread(target=self._run, args=args, daemon=True).start()
        else:
            self._run(*args)
        return self.view(job["id"])

    def _run(self, job_id: str, script: list, lang: str) -> None:
        with self._voice:
            job = self.jobs[job_id]
            job["state"], job["voicing_at"] = "voicing", self.clock()
            try:
                pcm, rate = self.tts(self.api_key(), {"lines": script, "language": lang})
                if not pcm:
                    raise RuntimeError("no_audio")
                self.root.mkdir(parents=True, exist_ok=True)
                tmp = self._cache_path(job["key"]).with_suffix(".part")
                tmp.write_bytes(pcm_to_wav(pcm, rate))
                os.replace(tmp, self._cache_path(job["key"]))
                job["state"] = "ready"
                self._prune()
            except Exception as exc:  # the reason category only; never Google's response text
                job["state"], job["error"] = "failed", str(getattr(exc, "category", "") or "voice_failed")[:40]
            job["finished"] = self.clock()

    def _prune(self) -> None:
        files = sorted(self.root.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for old in files[:-MAX_CACHE_FILES]:
            old.unlink(missing_ok=True)

    def view(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise DemoRefused("unknown_job", 404)
        state = job["state"]
        if state == "ready":
            pct = 100
        elif state == "failed":
            pct = 0
        else:
            since = self.clock() - job.get("voicing_at", job["started"])
            pct = 5 if state == "queued" else min(95, 10 + int(85 * since / TYPICAL_SECONDS))
        out = {"job": job_id, "state": state, "progress": pct, "estimated": state not in ("ready", "failed"),
               "cached": job.get("cached", False)}
        if state == "ready":
            out["audio"] = f"/api/mycast/demo/{job_id}/audio"
        if state == "failed":
            out["error"] = job.get("error", "voice_failed")
        return out

    def audio_path(self, job_id: str) -> Path:
        job = self.jobs.get(job_id)
        if not job or job["state"] != "ready" or not self._cache_path(job["key"]).exists():
            raise DemoRefused("not_ready", 404)
        return self._cache_path(job["key"])


def _client_id(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else "") or (request.client.host if request.client else "?")


def install_mycast_demo_routes(app, service: DemoService) -> None:
    """Public routes (no sign-in in the open beta); the caps above are the protection."""

    def _err(exc: DemoRefused):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mycast/demo/status")
    def mycast_demo_status():
        return {"remaining_today": service.remaining(), "daily_cap": service.daily_cap, "configured": bool(service.api_key())}

    @app.post("/api/mycast/demo")
    async def mycast_demo_start(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            return service.start(body.get("lines"), body.get("language"), _client_id(request))
        except DemoRefused as exc:
            return _err(exc)

    @app.get("/api/mycast/demo/{job_id}")
    def mycast_demo_job(job_id: str):
        try:
            return service.view(job_id)
        except DemoRefused as exc:
            return _err(exc)

    @app.get("/api/mycast/demo/{job_id}/audio")
    def mycast_demo_audio(job_id: str):
        try:
            return FileResponse(service.audio_path(job_id), media_type="audio/wav", filename="mycast-demo.wav",
                                headers={"Cache-Control": "private, max-age=3600"})
        except DemoRefused as exc:
            return _err(exc)
