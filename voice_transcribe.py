"""Owner voice messages in Telegram → text, via the owner's existing Gemini key (owner: «1 вариант», 2026-11-08).

- Only the paired owner's private chat is transcribed (the caller checks that).
- Free-tier Gemini Flash text model with inline audio; at most DAILY_CAP new transcriptions per UTC day
  (FACTORY_VOICE_TRANSCRIBE_DAILY_CAP, default 30). A repeat of the same Telegram file is served from a small cache
  and costs nothing. Files above MAX_BYTES (about 2–3 minutes of voice) are refused instead of uploaded.
- No key, cap reached or a Gemini/Telegram error give a short reason; the caller keeps the old behaviour
  (a ticket with the attachment only). Provider response text and the key never reach logs or the chat.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib import request as urlrequest

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
MODEL = os.environ.get("FACTORY_VOICE_TRANSCRIBE_MODEL", "gemini-2.5-flash").strip() or "gemini-2.5-flash"
DAILY_CAP = int(os.environ.get("FACTORY_VOICE_TRANSCRIBE_DAILY_CAP", "30") or 30)
MAX_BYTES = 4 * 1024 * 1024
MAX_TEXT = 3500
PROMPT = ("Transcribe this voice message verbatim, in the language it is spoken (usually Ukrainian or Russian, "
          "sometimes mixed with English terms). Output only the transcript text: no translation, no summary, "
          "no comments, no quotes. If nothing intelligible is said, output exactly: [неразборчиво]")


class TranscribeError(RuntimeError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def telegram_file_bytes(bot_token: str, file_id: str, *, opener=urlrequest.urlopen) -> bytes:
    req = urlrequest.Request(f"https://api.telegram.org/bot{bot_token}/getFile",
                             data=json.dumps({"file_id": file_id}).encode(), method="POST",
                             headers={"Content-Type": "application/json"})
    try:
        with opener(req, timeout=20) as r:
            meta = json.loads(r.read().decode("utf-8"))
        path = str(((meta or {}).get("result") or {}).get("file_path") or "")
        size = int(((meta or {}).get("result") or {}).get("file_size") or 0)
    except Exception:
        raise TranscribeError("telegram_file_unavailable") from None
    if not path:
        raise TranscribeError("telegram_file_unavailable")
    if size > MAX_BYTES:
        raise TranscribeError("too_long")
    try:
        with opener(urlrequest.Request(f"https://api.telegram.org/file/bot{bot_token}/{path}"), timeout=30) as r:
            data = r.read(MAX_BYTES + 1)
    except Exception:
        raise TranscribeError("telegram_file_unavailable") from None
    if len(data) > MAX_BYTES:
        raise TranscribeError("too_long")
    return data


def gemini_transcribe(api_key: str, audio: bytes, mime: str, *, opener=urlrequest.urlopen) -> str:
    payload = {"contents": [{"parts": [{"text": PROMPT},
                                       {"inline_data": {"mime_type": mime or "audio/ogg",
                                                        "data": base64.b64encode(audio).decode("ascii")}}]}],
               "generationConfig": {"temperature": 0}}
    model = MODEL
    if opener is urlrequest.urlopen:
        from gemini_proxy import resolve_flash_model
        model = resolve_flash_model(api_key, MODEL)            # 2026-11-11: 2.5-flash returned 404 for this key
    req = urlrequest.Request(f"{GEMINI_API}/models/{model}:generateContent", data=json.dumps(payload).encode("utf-8"),
                             method="POST", headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    try:
        with opener(req, timeout=60) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", None)
        raise TranscribeError({400: "bad_request", 401: "invalid_key", 403: "invalid_key", 404: "model_not_found",
                               429: "rate_limited"}.get(code, "unreachable")) from None
    parts = (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []) if isinstance(data, dict) else []
    text = " ".join(str(p.get("text") or "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise TranscribeError("empty_transcript")
    return text[:MAX_TEXT]


class VoiceTranscriber:
    """Daily cap + cache around telegram_file_bytes → gemini_transcribe. Thread-safe; state is one small JSON file."""

    def __init__(self, data_dir: Path, *, api_key: Callable[[], str], bot_token: Callable[[], str],
                 fetch: Callable = telegram_file_bytes, transcribe: Callable = gemini_transcribe,
                 clock: Callable[[], float] = time.time, daily_cap: int = DAILY_CAP):
        self.path = Path(data_dir) / "voice-transcribe.json"
        self.api_key, self.bot_token, self.fetch, self.transcribe = api_key, bot_token, fetch, transcribe
        self.clock, self.daily_cap = clock, daily_cap
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def __call__(self, attachment: dict) -> tuple[Optional[str], str]:
        """(transcript, "") or (None, reason). Never raises."""
        if not isinstance(attachment, dict) or attachment.get("kind") not in ("voice", "audio"):
            return None, "not_voice"
        file_id = str(attachment.get("file_id") or "")
        unique = str(attachment.get("file_unique_id") or file_id)
        if not file_id:
            return None, "no_file"
        key, token = self.api_key(), self.bot_token()
        if not key:
            return None, "not_configured"
        if not token:
            return None, "telegram_not_configured"
        cache_key = hashlib.sha256(unique.encode()).hexdigest()[:24]
        day = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")
        with self._lock:
            data = self._load()
            cache = data.get("cache") if isinstance(data.get("cache"), dict) else {}
            if cache_key in cache:
                return str(cache[cache_key]), ""
            count = int(data.get("count", 0)) if data.get("day") == day else 0
            if count >= self.daily_cap:
                return None, "daily_limit"
            data.update(day=day, count=count + 1)   # counted before the call: a failed call still used the quota
            self._save(data)
        try:
            text = self.transcribe(key, self.fetch(token, file_id), str(attachment.get("mime_type") or "audio/ogg"))
        except TranscribeError as exc:
            return None, exc.reason
        except Exception:
            return None, "voice_failed"
        with self._lock:
            data = self._load()
            cache = data.get("cache") if isinstance(data.get("cache"), dict) else {}
            cache[cache_key] = text
            data["cache"] = dict(list(cache.items())[-50:])
            self._save(data)
        return text, ""
