"""#281 MyCast voice audition: the prebuilt Gemini TTS voices, each with a real sample voiced by Gemini.

- The catalogue is the 30 prebuilt voice names Gemini TTS publishes, with their one-word style. Google publishes no
  gender for them; the male/female split here is by sound, marked unofficial (`gender_source: "by_ear"`) on the page.
- A voice is offered as playable only after its sample really exists. A voice whose generation fails is marked
  unavailable with the reason and is not retried for an hour. There is never a browser-voice stand-in.
- Samples are voiced once per voice and language, kept as WAV under DATA_DIR, and served from cache afterwards.
  New generations are capped (owner, 2026-11-07: about 30 samples; the default here is 40 a UTC day, to cover retries).
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse

from mycast_demo import pcm_to_wav

CATALOGUE_VERSION = "gemini-tts-prebuilt-2026-11"
# (name, style, gender by ear: m/f)
VOICES = [
    ("Zephyr", "Bright", "f"), ("Puck", "Upbeat", "m"), ("Charon", "Informative", "m"), ("Kore", "Firm", "f"),
    ("Fenrir", "Excitable", "m"), ("Leda", "Youthful", "f"), ("Orus", "Firm", "m"), ("Aoede", "Breezy", "f"),
    ("Callirrhoe", "Easy-going", "f"), ("Autonoe", "Bright", "f"), ("Enceladus", "Breathy", "m"), ("Iapetus", "Clear", "m"),
    ("Umbriel", "Easy-going", "m"), ("Algieba", "Smooth", "m"), ("Despina", "Smooth", "f"), ("Erinome", "Clear", "f"),
    ("Algenib", "Gravelly", "m"), ("Rasalgethi", "Informative", "m"), ("Laomedeia", "Upbeat", "f"), ("Achernar", "Soft", "f"),
    ("Alnilam", "Firm", "m"), ("Schedar", "Even", "m"), ("Gacrux", "Mature", "f"), ("Pulcherrima", "Forward", "f"),
    ("Achird", "Friendly", "m"), ("Zubenelgenubi", "Casual", "m"), ("Vindemiatrix", "Gentle", "f"), ("Sadachbia", "Lively", "m"),
    ("Sadaltager", "Knowledgeable", "m"), ("Sulafat", "Warm", "f"),
]
NAMES = {v[0] for v in VOICES}
DEFAULTS = {"narrator": ("Charon",), "two_hosts": ("Charon", "Kore")}   # the pair MyCast already used for episodes
SAMPLE_TEXT = {
    "uk": "Привіт! Я — голос {name}. Ось так звучатиме ваш MyCast.",
    "ru": "Привет! Я — голос {name}. Вот так будет звучать ваш MyCast.",
    "en": "Hi! I am the {name} voice. This is how your MyCast will sound.",
}
DAILY_CAP = int(os.environ.get("MYCAST_VOICE_SAMPLE_DAILY_CAP", "40") or 40)
FAIL_RETRY_SECONDS = 3600


def valid_voices(mode: str, voices) -> bool:
    """narrator: one male-by-ear voice; two_hosts: two different voices, the first male-by-ear, the second female-by-ear."""
    if not isinstance(voices, (list, tuple)) or any(v not in NAMES for v in voices):
        return False
    gender = {n: g for n, _, g in VOICES}
    if mode == "narrator":
        return len(voices) == 1 and gender[voices[0]] == "m"
    if mode == "two_hosts":
        return len(voices) == 2 and voices[0] != voices[1] and gender[voices[0]] == "m" and gender[voices[1]] == "f"
    return False


def gemini_single_voice_pcm(api_key: str, text: str, voice: str, *, opener=None) -> tuple[bytes, int]:
    """One speaker, one prebuilt voice: the single-voice form of the same Gemini TTS call MyCast uses for episodes."""
    import mycast
    from urllib import request as urlrequest
    payload = {"contents": [{"parts": [{"text": text}]}],
               "generationConfig": {"responseModalities": ["AUDIO"],
                                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    result = mycast._gemini_call(api_key, "POST", f"models/{mycast.DEFAULT_TTS_MODEL}:generateContent", payload,
                                 opener or urlrequest.urlopen)
    parts = ((result.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
    inline = next((p.get("inlineData") for p in parts if p.get("inlineData")), None)
    if not inline or not inline.get("data"):
        raise mycast.GeminiTTSError("no_audio")
    m = re.search(r"rate=(\d+)", str(inline.get("mimeType") or ""))
    return base64.b64decode(inline["data"]), int(m.group(1)) if m else 24000


class VoiceRefused(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


class VoiceSamples:
    def __init__(self, root: Path, *, api_key: Callable[[], str], tts: Callable, clock: Callable[[], float] = time.time,
                 daily_cap: int = DAILY_CAP):
        self.root, self.api_key, self.tts, self.clock, self.daily_cap = Path(root), api_key, tts, clock, daily_cap
        self._lock = threading.Lock()
        self._failed: dict[str, tuple[float, str]] = {}

    def _path(self, voice: str, lang: str) -> Path:
        return self.root / f"sample-{voice}-{lang}.wav"

    def _counter(self) -> Path:
        return self.root / ("count-" + datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d") + ".json")

    def _used(self) -> int:
        try:
            return int(json.loads(self._counter().read_text()).get("total", 0))
        except (OSError, ValueError):
            return 0

    def catalogue(self, lang: str) -> dict:
        now = self.clock()
        voices = []
        for name, style, gender in VOICES:
            failed = self._failed.get(f"{name}:{lang}")
            state = "ready" if self._path(name, lang).exists() else (
                "unavailable" if failed and now - failed[0] < FAIL_RETRY_SECONDS else "not_generated")
            item = {"name": name, "style": style, "gender": gender, "gender_source": "by_ear", "sample": state}
            if state == "ready":
                item["url"] = f"/api/mycast/voices/{name}/{lang}.wav"
            if state == "unavailable":
                item["reason"] = failed[1]
            voices.append(item)
        return {"version": CATALOGUE_VERSION, "language": lang, "voices": voices, "defaults": DEFAULTS,
                "remaining_today": max(0, self.daily_cap - self._used()), "configured": bool(self.api_key())}

    def sample(self, voice: str, lang: str) -> dict:
        if voice not in NAMES:
            raise VoiceRefused("unknown_voice", 404)
        if lang not in SAMPLE_TEXT:
            raise VoiceRefused("bad_language")
        url = f"/api/mycast/voices/{voice}/{lang}.wav"
        if self._path(voice, lang).exists():
            return {"voice": voice, "state": "ready", "url": url, "cached": True}
        failed = self._failed.get(f"{voice}:{lang}")
        if failed and self.clock() - failed[0] < FAIL_RETRY_SECONDS:
            return {"voice": voice, "state": "unavailable", "reason": failed[1]}
        if not self.api_key():
            raise VoiceRefused("not_configured", 503)
        with self._lock:                                   # one generation at a time; re-check after waiting
            if self._path(voice, lang).exists():
                return {"voice": voice, "state": "ready", "url": url, "cached": True}
            used = self._used()
            if used >= self.daily_cap:
                raise VoiceRefused("daily_limit", 429)
            self.root.mkdir(parents=True, exist_ok=True)
            self._counter().write_text(json.dumps({"total": used + 1}))
            try:
                pcm, rate = self.tts(self.api_key(), SAMPLE_TEXT[lang].format(name=voice), voice)
                if not pcm:
                    raise RuntimeError("no_audio")
            except Exception as exc:
                reason = str(getattr(exc, "category", "") or "voice_failed")[:40]
                self._failed[f"{voice}:{lang}"] = (self.clock(), reason)
                return {"voice": voice, "state": "unavailable", "reason": reason}
            tmp = self._path(voice, lang).with_suffix(".part")
            tmp.write_bytes(pcm_to_wav(pcm, rate))
            os.replace(tmp, self._path(voice, lang))
        return {"voice": voice, "state": "ready", "url": url, "cached": False}

    def file(self, voice: str, lang: str) -> Path:
        path = self._path(voice, lang) if voice in NAMES and lang in SAMPLE_TEXT else None
        if not path or not path.exists():
            raise VoiceRefused("not_ready", 404)
        return path


def install_mycast_voice_audition_routes(app, samples: VoiceSamples) -> None:
    def _err(exc: VoiceRefused):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mycast/voices")
    def mycast_voices(lang: str = "uk"):
        return samples.catalogue(lang if lang in SAMPLE_TEXT else "uk")

    @app.post("/api/mycast/voices/{voice}/sample")
    async def mycast_voice_sample(voice: str, request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        try:
            return samples.sample(voice, str((body or {}).get("language") or "uk"))
        except VoiceRefused as exc:
            return _err(exc)

    @app.get("/api/mycast/voices/{voice}/{lang}.wav")
    def mycast_voice_file(voice: str, lang: str):
        try:
            return FileResponse(samples.file(voice, lang), media_type="audio/wav", headers={"Cache-Control": "public, max-age=86400"})
        except VoiceRefused as exc:
            return _err(exc)
