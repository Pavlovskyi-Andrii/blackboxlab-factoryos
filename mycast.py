"""MyCast delivery: the EC2 worker uploads a rendered episode; the server sends it to the owner's Telegram.

The bot token never leaves the server. Only the worker token may deliver; each episode id is sent once.
"""
from __future__ import annotations

import base64
import json
import os
import re
import secrets
import threading
from pathlib import Path
from typing import Callable, Optional
from urllib import request as urlrequest

from fastapi import File, Form, HTTPException, Request, UploadFile

MAX_AUDIO_BYTES = 20 * 1024 * 1024  # well under Telegram's 50 MB bot upload limit
EPISODE_ID_RE = re.compile(r"^mycast-[a-z0-9-]{4,60}$")


def telegram_send_audio(bot_token: str, chat_id: str, audio: bytes, *, filename: str, title: str, caption: str,
                        opener: Callable = urlrequest.urlopen) -> None:
    """Telegram sendAudio as multipart/form-data, standard library only."""
    boundary = "mycast" + secrets.token_hex(12)
    parts = []
    for name, value in (("chat_id", chat_id), ("title", title[:64]), ("performer", "MyCast"), ("caption", caption[:1000])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8"))
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="audio"; filename="{filename}"\r\n'
                 f"Content-Type: audio/mpeg\r\n\r\n".encode("utf-8") + audio + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode("utf-8"))
    req = urlrequest.Request(f"https://api.telegram.org/bot{bot_token}/sendAudio", data=b"".join(parts),
                             headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
    try:
        with opener(req, timeout=120) as response:
            result = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("Telegram sendAudio failed") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Telegram sendAudio returned not-ok")


class DeliveryLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def delivered(self) -> list:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return value if isinstance(value, list) else []

    def claim(self, episode_id: str) -> bool:
        """True if this id was not delivered before (and records it)."""
        with self._lock:
            done = self.delivered()
            if episode_id in done:
                return False
            done = (done + [episode_id])[-400:]
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(done), encoding="utf-8")
            os.replace(tmp, self.path)
            return True

    def release(self, episode_id: str) -> None:
        with self._lock:
            done = [x for x in self.delivered() if x != episode_id]
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(done), encoding="utf-8")
            os.replace(tmp, self.path)


def install_mycast_routes(app, log: DeliveryLog, *, authorize_worker: Callable[[Request], bool],
                          send_audio: Callable[[bytes, str, str, str], None],
                          paired: Callable[[], bool]) -> None:
    @app.post("/api/factory/mycast/worker/deliver")
    async def mycast_deliver(request: Request, episode_id: str = Form(...), title: str = Form(""),
                             caption: str = Form(""), audio: UploadFile = File(...)):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if not EPISODE_ID_RE.fullmatch(episode_id):
            raise HTTPException(400, "bad episode id")
        if not paired():
            raise HTTPException(409, "Telegram owner chat is not paired")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio missing or too large")
        if not log.claim(episode_id):
            return {"sent": False, "duplicate": True}
        try:
            send_audio(data, f"{episode_id}.mp3", title or episode_id, caption)
        except Exception as exc:
            log.release(episode_id)  # let the worker retry
            raise HTTPException(502, "Telegram delivery failed") from exc
        return {"sent": True, "duplicate": False}


# --- Gemini voices (owner decision 2026-11-02: natural two-host voice via the owner's Gemini API key) ---
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TTS_MODEL = "gemini-2.5-flash-preview-tts"
CHUNK_CHARS = 1400  # several TTS calls per episode keep each request well inside model limits
SPEAKER_LABELS = {"A": "Host1", "B": "Host2"}


class GeminiTTSError(RuntimeError):
    """category is safe to show: no Google response text, no key."""

    def __init__(self, category: str):
        super().__init__(category)
        self.category = category


def _gemini_call(api_key: str, method: str, path: str, payload: Optional[dict], opener) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(f"{GEMINI_API}/{path}", data=data, method=method,
                             headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    try:
        with opener(req, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        code = getattr(exc, "code", None)
        raise GeminiTTSError({400: "bad_request", 401: "invalid_key", 403: "invalid_key", 404: "model_not_found",
                              429: "rate_limited"}.get(code, "unreachable")) from None


def _pick_tts_model(api_key: str, opener) -> str:
    listing = _gemini_call(api_key, "GET", "models?pageSize=200", None, opener)
    names = [str(m.get("name", "")).split("/")[-1] for m in listing.get("models") or []]
    tts = [n for n in names if "tts" in n]
    if not tts:
        raise GeminiTTSError("model_not_found")
    return sorted(tts, key=lambda n: ("flash" not in n, n))[0]


def episode_chunks(lines: list) -> list[list]:
    chunks, current, size = [], [], 0
    for host, text in lines:
        if current and size + len(text) > CHUNK_CHARS:
            chunks.append(current)
            current, size = [], 0
        current.append((host, text))
        size += len(text)
    if current:
        chunks.append(current)
    return chunks


def gemini_tts_pcm(api_key: str, episode: dict, *, model: str = "", voices: tuple[str, str] = ("Charon", "Kore"),
                   opener: Callable = urlrequest.urlopen) -> tuple[bytes, int]:
    """Two-host dialogue → raw PCM (16-bit mono) and its sample rate."""
    model = model or DEFAULT_TTS_MODEL
    language = {"uk": "українською", "ru": "русском", "en": "English"}.get(str(episode.get("language") or "uk"), "українською")
    speaker_cfg = [{"speaker": SPEAKER_LABELS[h], "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}}
                   for h, v in zip(("A", "B"), voices)]
    pcm, rate = b"", 24000
    for chunk in episode_chunks(episode["lines"]):
        script = "\n".join(f"{SPEAKER_LABELS[h]}: {t}" for h, t in chunk)
        payload = {"contents": [{"parts": [{"text": f"Озвуч цей фрагмент подкасту ({language}) природно, жваво, як двоє ведучих, що розмовляють:\n{script}"}]}],
                   "generationConfig": {"responseModalities": ["AUDIO"],
                                        "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": speaker_cfg}}}}
        try:
            result = _gemini_call(api_key, "POST", f"models/{model}:generateContent", payload, opener)
        except GeminiTTSError as exc:
            if exc.category != "model_not_found":
                raise
            model = _pick_tts_model(api_key, opener)  # the default name changed: use what the key can see
            result = _gemini_call(api_key, "POST", f"models/{model}:generateContent", payload, opener)
        parts = ((result.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        inline = next((p.get("inlineData") for p in parts if p.get("inlineData")), None)
        if not inline or not inline.get("data"):
            raise GeminiTTSError("no_audio")
        match = re.search(r"rate=(\d+)", str(inline.get("mimeType") or ""))
        rate = int(match.group(1)) if match else 24000
        pcm += base64.b64decode(inline["data"]) + b"\x00\x00" * int(rate * 0.35)  # short pause between chunks
    return pcm, rate


def pcm_to_mp3(pcm: bytes, rate: int) -> bytes:
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(96)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm) + encoder.flush())


def install_mycast_voice_routes(app, log: DeliveryLog, *, authorize_worker: Callable[[Request], bool],
                                send_audio: Callable[[bytes, str, str, str], None], paired: Callable[[], bool],
                                api_key: Callable[[], str], model: str = "", voices: tuple[str, str] = ("Charon", "Kore"),
                                tts: Callable = gemini_tts_pcm, encode: Callable = pcm_to_mp3) -> None:
    @app.post("/api/factory/mycast/worker/voice-deliver")
    async def mycast_voice_deliver(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "json body required")
        episode = body.get("episode") if isinstance(body, dict) else None
        lines = episode.get("lines") if isinstance(episode, dict) else None
        if not (isinstance(episode, dict) and EPISODE_ID_RE.fullmatch(str(episode.get("id", ""))) and isinstance(lines, list)
                and lines and all(isinstance(l, list) and len(l) == 2 and l[0] in SPEAKER_LABELS and isinstance(l[1], str) for l in lines)
                and sum(len(l[1]) for l in lines) <= 20000):
            raise HTTPException(400, "bad episode")
        key = api_key()
        if not key:
            raise HTTPException(409, "gemini key not configured")
        if not paired():
            raise HTTPException(409, "Telegram owner chat is not paired")
        if not log.claim(episode["id"]):
            return {"sent": False, "duplicate": True, "voice": "gemini"}
        try:
            pcm, rate = tts(key, episode, model=model, voices=voices)
            audio = encode(pcm, rate)
            words = sum(len(t.split()) for _, t in lines)
            send_audio(audio, f"{episode['id']}.mp3", str(episode.get("title") or episode["id"])[:64],
                       f"🎧 {episode.get('title', '')} · ~{max(1, round(words / 140))} хв · голоси Gemini")
        except GeminiTTSError as exc:
            log.release(episode["id"])
            raise HTTPException(502, f"gemini tts: {exc.category}")
        except Exception:
            log.release(episode["id"])
            raise HTTPException(502, "voice delivery failed")
        return {"sent": True, "duplicate": False, "voice": "gemini", "seconds": round(len(pcm) / 2 / rate)}
