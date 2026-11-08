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

from mycast_voices import NAMES, VOICES as CATALOGUE, valid_voices

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
    if not valid_voices("two_hosts", [a, b]):
        raise ValueError("invalid voice pair")       # same rule the demo and the page use
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
    from fastapi import Request
    from fastapi.responses import JSONResponse

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
