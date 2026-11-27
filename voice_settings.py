"""Owner-only MyCast voice preference persistence and API (Issue #140).

Storage by ChatGPT (PR #282), adopted as the base on the owner's decision of 2026-11-08. Claude added:
- the voice list and the pair rule come from ``mycast_voices`` (one catalogue for the whole app): host A is a
  male-by-ear voice, host B a female-by-ear voice, and the two differ;
- owner-only routes ``GET/POST /api/factory/voice/settings`` (the caller passes ``is_owner``);
- ``current_pair()`` for the daily MyCast voice delivery, which falls back to the env defaults when nothing valid
  is stored.
Never expose the settings file through a public static route.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable

from fastapi import HTTPException, Request  # module level: with postponed annotations FastAPI resolves
from fastapi.responses import JSONResponse   # `request: Request` here, or it becomes a required query param

from mycast_voices import NAMES, VOICES as CATALOGUE, classic_pair

VOICES = frozenset(NAMES)
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"   # = mycast.DEFAULT_TTS_MODEL; no other (paid) model is selectable
_LOCK = threading.RLock()


def validate_settings(value: dict) -> dict:
    """Reject unknown fields/voices; never accept API keys or caller-supplied paths."""
    if not isinstance(value, dict) or set(value) != {"voice_a", "voice_b", "model"}:
        raise ValueError("invalid voice settings fields")
    a, b, model = value["voice_a"], value["voice_b"], value["model"]
    if not isinstance(a, str) or a not in VOICES:
        raise ValueError("invalid voice_a")
    if not isinstance(b, str) or b not in VOICES:
        raise ValueError("invalid voice_b")
    if not isinstance(model, str) or model != DEFAULT_MODEL:
        raise ValueError("unsupported TTS model")
    if not classic_pair([a, b]):
        raise ValueError("invalid voice pair")       # the daily script writes host A male, host B female
    return {"voice_a": a, "voice_b": b, "model": model}


class VoiceSettingsStore:
    """Atomic, owner-scoped local JSON store. Caller MUST enforce owner auth."""

    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "mycast-voice-settings.json"

    def read(self) -> dict:
        with _LOCK:
            defaults = {"voice_a": os.getenv("FACTORY_MYCAST_VOICE_A", "Charon"),
                        "voice_b": os.getenv("FACTORY_MYCAST_VOICE_B", "Kore"),
                        "model": DEFAULT_MODEL}
            try:
                raw = self.path.read_text(encoding="utf-8")
            except FileNotFoundError:
                return validate_settings(defaults)
            # Corruption must not silently replace owner choices.
            return validate_settings(json.loads(raw))

    def write(self, value: dict) -> dict:
        safe = validate_settings(value)
        with _LOCK:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_name = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", dir=self.path.parent,
                    prefix=".mycast-voice-", suffix=".tmp", delete=False
                ) as f:
                    tmp_name = f.name
                    os.chmod(tmp_name, 0o600)
                    json.dump(safe, f, ensure_ascii=False, sort_keys=True)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, self.path)
                tmp_name = None
            finally:
                if tmp_name is not None:
                    os.unlink(tmp_name)
            return safe

    def current_pair(self) -> tuple:
        """The pair the daily delivery should use; a missing or damaged file means the env defaults."""
        try:
            s = self.read()
            return (s["voice_a"], s["voice_b"])
        except (OSError, ValueError):                   # as before #140: the env pair, else Charon + Kore
            return (os.getenv("FACTORY_MYCAST_VOICE_A", "").strip() or "Charon",
                    os.getenv("FACTORY_MYCAST_VOICE_B", "").strip() or "Kore")


def install_voice_settings_routes(app, store: VoiceSettingsStore, *, is_owner: Callable) -> None:

    catalogue = [{"name": n, "style": st, "gender": g, "gender_source": "by_ear"} for n, st, g in CATALOGUE]

    @app.get("/api/factory/voice/settings")
    def voice_settings_get(request: Request):
        if not is_owner(request):
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        try:
            settings, state = store.read(), "ok"
        except (OSError, ValueError):
            settings, state = None, "damaged"          # shown honestly, never silently reset
        return {"settings": settings, "state": state, "available_voices": catalogue, "model": DEFAULT_MODEL,
                "rule": "voice_a male, voice_b female, different"}

    @app.post("/api/factory/voice/settings")
    async def voice_settings_post(request: Request):
        if not is_owner(request):
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        try:
            return {"settings": store.write(body), "state": "ok"}
        except ValueError as exc:
            return JSONResponse({"detail": str(exc).replace(" ", "_")}, status_code=400)


class VoiceHistory:
    """Shared delivery history for the owner (#140): MyCast episodes and morning briefs, newest last, 200 kept."""

    KINDS = ("mycast", "brief")
    MAX = 200

    def __init__(self, data_dir: Path, *, clock: Callable = None):
        import time
        self.path = Path(data_dir) / "voice-history.json"
        self.clock = clock or time.time

    def entries(self) -> list:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return value if isinstance(value, list) else []

    def record(self, *, kind: str, item_id: str, voice: str, status: str, seconds: int = 0) -> dict:
        if kind not in self.KINDS:
            raise ValueError("unknown kind")
        entry = {"id": str(item_id)[:80], "kind": kind, "voice": str(voice)[:40], "status": str(status)[:60],
                 "seconds": int(seconds or 0), "at": int(self.clock())}
        with _LOCK:
            rows = (self.entries() + [entry])[-self.MAX:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        return entry


BRIEF_MAX_CHARS = 1400
_DATE = __import__("re").compile(r"^\d{4}-\d{2}-\d{2}$")


def install_voice_history_routes(app, history: VoiceHistory, *, is_owner: Callable) -> None:

    @app.get("/api/factory/voice/history")
    def voice_history(request: Request):
        if not is_owner(request):
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        return {"deliveries": list(reversed(history.entries()))[:50]}


class BriefError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


def make_brief_sender(history: VoiceHistory, log, store: VoiceSettingsStore, *, api_key: Callable, paired: Callable,
                      tts_single: Callable, encode: Callable, send_audio: Callable,
                      check_audio: Callable = lambda audio: None) -> Callable[[str, str], dict]:
    """deliver(date, text): the brief in the owner's host-A voice to the owner's own paired chat, at most once per
    date (the claim is released on failure so a retry can run). Blocking; raises BriefError(status, detail).
    Shared by the worker route and the 08:00 schedule (#106), so both use one delivery log."""

    def deliver(date: str, text) -> dict:
        if not _DATE.fullmatch(str(date or "")) or not isinstance(text, str) or not 1 <= len(text.strip()) <= BRIEF_MAX_CHARS:
            raise BriefError(400, "bad brief")
        key = api_key()
        if not key:
            raise BriefError(409, "gemini key not configured")
        if not paired():
            raise BriefError(409, "Telegram owner chat is not paired")
        brief_id = f"brief-{date}"
        if not log.claim(brief_id):
            return {"sent": False, "duplicate": True}
        voice = store.current_pair()[0]
        try:
            pcm, rate = tts_single(key, text.strip(), voice)
            audio = encode(pcm, rate)
            check_audio(audio)
            send_audio(audio, f"{brief_id}.mp3", f"Ранковий брифінг {date}", f"🎙 Ранковий брифінг · {date} · голос {voice}")
            seconds = round(len(pcm) / 2 / rate)
        except Exception as exc:  # the category only, never the provider's text
            log.release(brief_id)
            category = str(getattr(exc, "category", "") or getattr(exc, "reason", "") or "voice_failed")[:40]
            history.record(kind="brief", item_id=brief_id, voice=voice, status="failed:" + category)
            raise BriefError(502, f"brief failed: {category}")
        history.record(kind="brief", item_id=brief_id, voice=voice, status="sent", seconds=seconds)
        return {"sent": True, "duplicate": False, "voice": voice, "seconds": seconds}
    return deliver


def install_brief_route(app, history: VoiceHistory, log, store: VoiceSettingsStore, *, authorize_worker: Callable,
                        api_key: Callable, paired: Callable, tts_single: Callable, encode: Callable, send_audio: Callable,
                        check_audio: Callable = lambda audio: None) -> Callable[[str, str], dict]:
    """POST /api/factory/voice/worker/brief-deliver {date, text}: see make_brief_sender. Returns the sender so the
    server's own 08:00 schedule (morning_brief.py) shares the same once-per-date log."""
    import asyncio
    deliver = make_brief_sender(history, log, store, api_key=api_key, paired=paired, tts_single=tts_single,
                                encode=encode, send_audio=send_audio, check_audio=check_audio)

    @app.post("/api/factory/voice/worker/brief-deliver")
    async def voice_brief_deliver(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        try:
            body = await request.json()
        except ValueError:
            body = None
        body = body if isinstance(body, dict) else {}
        try:
            return await asyncio.to_thread(deliver, str(body.get("date") or ""), body.get("text"))
        except BriefError as exc:
            raise HTTPException(exc.status, exc.detail)
    return deliver
