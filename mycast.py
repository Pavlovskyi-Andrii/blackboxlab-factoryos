"""MyCast delivery: the EC2 worker uploads a rendered episode; the server sends it to the owner's Telegram.

The bot token never leaves the server. Only the worker token may deliver; each episode id is sent once.
"""
from __future__ import annotations

import asyncio
import base64
import inspect
import json
import os
import re
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib import error as urlerror
from urllib import request as urlrequest

from fastapi import File, Form, HTTPException, Request, UploadFile

import mycast_timecodes

MAX_AUDIO_BYTES = 20 * 1024 * 1024  # well under Telegram's 50 MB bot upload limit
EPISODE_ID_RE = re.compile(r"^mycast-[a-z0-9-]{4,60}$")


class TelegramUncertain(RuntimeError):
    """The upload may have reached the chat (timeout, reset, unreadable answer). Retrying could send the MP3 twice,
    so the episode stays claimed and the owner is told instead (#468)."""


def telegram_send_audio(bot_token: str, chat_id: str, audio: bytes, *, filename: str, title: str, caption: str,
                        opener: Callable = urlrequest.urlopen) -> str:
    """Telegram sendAudio as multipart/form-data, standard library only. Returns Telegram's file_id ("" if absent):
    the audio then lives on Telegram's servers and can be fetched again later without storing it here (#317 history).
    RuntimeError: Telegram certainly did not take it (HTTP error, no connection, not-ok), so a retry is safe.
    TelegramUncertain: it may have been delivered; never retried automatically."""
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
            raw = response.read()
    except urlerror.HTTPError as exc:  # Telegram answered with an error: nothing was posted
        raise RuntimeError("Telegram sendAudio failed") from exc
    except urlerror.URLError as exc:
        if isinstance(exc.reason, (ConnectionRefusedError, socket.gaierror)):  # never connected: nothing was sent
            raise RuntimeError("Telegram sendAudio failed") from exc
        raise TelegramUncertain("Telegram sendAudio unconfirmed") from exc
    except Exception as exc:  # timeout or reset while the upload was in flight
        raise TelegramUncertain("Telegram sendAudio unconfirmed") from exc
    try:
        result = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise TelegramUncertain("Telegram sendAudio unconfirmed") from exc
    if not isinstance(result, dict) or not result.get("ok"):
        raise RuntimeError("Telegram sendAudio returned not-ok")
    message = result.get("result") if isinstance(result.get("result"), dict) else {}
    return str((message.get("audio") or message.get("document") or {}).get("file_id") or "")


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

    # #468: every attempt and its Telegram outcome per episode, next to the claim list. Ids and statuses only.
    @property
    def attempts_path(self) -> Path:
        return self.path.with_name(self.path.stem + "_attempts.json")

    def attempts(self, episode_id: str) -> list:
        try:
            value = json.loads(self.attempts_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        rows = value.get(episode_id) if isinstance(value, dict) else None
        return rows if isinstance(rows, list) else []

    def record(self, episode_id: str, status: str, **extra) -> None:
        """Never raises: the ledger is evidence, not a gate."""
        try:
            with self._lock:
                try:
                    data = json.loads(self.attempts_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                data = data if isinstance(data, dict) else {}
                rows = data.pop(episode_id, [])
                data[episode_id] = ((rows if isinstance(rows, list) else []) +
                                    [{"at": round(time.time()), "status": status, **extra}])[-20:]
                data = dict(list(data.items())[-100:])
                self.attempts_path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self.attempts_path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp, self.attempts_path)
        except Exception:
            pass


# --- Audio preflight QC (#233): nothing is logged as delivered unless the audio passes these checks ---
# Pure Python on purpose: Render has no ffmpeg/ffprobe, and a missing tool must never turn into a silent "OK".
QC_WORDS_PER_MINUTE = 140           # spoken Ukrainian/Russian pace used for the expected length
QC_DURATION_RATIO = (0.45, 2.2)     # actual / expected seconds
QC_MAX_SILENCE_SECONDS = 6.0        # one run of near-silence longer than this fails the episode
QC_SILENCE_RMS = 160                # ~ -46 dBFS on 16-bit PCM
QC_CHUNK_CHARS_PER_SECOND = 14.0    # a TTS chunk far shorter than its text was truncated
QC_CHUNK_MIN_RATIO = 0.35
QC_MIN_MP3_FRAMES = 20

_MP3_BITRATES = {1: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
                 2: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160]}
_MP3_RATES = {3: (44100, 48000, 32000), 2: (22050, 24000, 16000), 0: (11025, 12000, 8000)}


class AudioQCError(RuntimeError):
    """reason is short and safe to show to the worker and the owner."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def expected_seconds(lines: list) -> float:
    words = sum(len(str(t).split()) for _, t in lines)
    return words / QC_WORDS_PER_MINUTE * 60


def pcm_report(pcm: bytes, rate: int, *, stride: int = 4) -> dict:
    """Duration and the longest run of near-silence (100 ms windows) of 16-bit mono PCM."""
    import array

    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    window = max(1, rate // 10)
    longest = run = 0
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window:stride]
        rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5 if chunk else 0.0
        run = run + 1 if rms < QC_SILENCE_RMS else 0
        longest = max(longest, run)
    return {"seconds": round(len(samples) / rate, 2) if rate else 0.0, "max_silence_seconds": round(longest * window / rate, 2)}


def mp3_report(data: bytes) -> dict:
    """Walk MPEG audio Layer III frame headers: frame count, duration and how much of the file is valid frames."""
    pos, frames, seconds, valid_bytes = 0, 0, 0.0, 0
    if data[:3] == b"ID3" and len(data) >= 10:
        size = (data[6] & 0x7F) << 21 | (data[7] & 0x7F) << 14 | (data[8] & 0x7F) << 7 | (data[9] & 0x7F)
        pos = valid_bytes = 10 + size
    while pos + 4 <= len(data):
        b1, b2, b3 = data[pos + 1], data[pos + 2], data[pos + 3]
        version, layer = (b1 >> 3) & 3, (b1 >> 1) & 3
        bitrate_idx, rate_idx, padding = b2 >> 4, (b2 >> 2) & 3, (b2 >> 1) & 1
        if data[pos] != 0xFF or (b1 & 0xE0) != 0xE0 or version == 1 or layer != 1 or bitrate_idx in (0, 15) or rate_idx == 3:
            if frames:  # garbage after the stream started: stop, the share of valid bytes tells the rest
                break
            pos += 1
            continue
        mpeg1 = version == 3
        bitrate = _MP3_BITRATES[1 if mpeg1 else 2][bitrate_idx] * 1000
        sample_rate = _MP3_RATES[version][rate_idx]
        length = (144 if mpeg1 else 72) * bitrate // sample_rate + padding
        if length < 4 or pos + length > len(data):
            break
        frames += 1
        seconds += (1152 if mpeg1 else 576) / sample_rate
        valid_bytes += length
        pos += length
    return {"frames": frames, "seconds": round(seconds, 2), "valid_share": round(valid_bytes / len(data), 3) if data else 0.0}


def check_mp3(data: bytes, *, expected: float | None = None) -> dict:
    if not data:
        raise AudioQCError("empty audio")
    report = mp3_report(data)
    if report["frames"] < QC_MIN_MP3_FRAMES or report["valid_share"] < 0.9:
        raise AudioQCError("not a decodable mp3")
    if expected:
        lo, hi = QC_DURATION_RATIO
        if not lo * expected <= report["seconds"] <= hi * expected:
            raise AudioQCError(f"duration {report['seconds']:.0f}s outside expected {lo * expected:.0f}-{hi * expected:.0f}s")
    return report


def check_pcm(pcm: bytes, rate: int, lines: list, chunk_stats: list | None = None) -> dict:
    """Gemini path: the raw PCM is known, so silence and truncated chunks can be measured before encoding."""
    if not pcm or not rate:
        raise AudioQCError("empty audio")
    report = pcm_report(pcm, rate)
    expected = expected_seconds(lines)
    lo, hi = QC_DURATION_RATIO
    if not lo * expected <= report["seconds"] <= hi * expected:
        raise AudioQCError(f"duration {report['seconds']:.0f}s outside expected {lo * expected:.0f}-{hi * expected:.0f}s")
    if report["max_silence_seconds"] > QC_MAX_SILENCE_SECONDS:
        raise AudioQCError(f"silence of {report['max_silence_seconds']:.0f}s")
    for n, (chars, seconds) in enumerate(chunk_stats or [], 1):
        if seconds < QC_CHUNK_MIN_RATIO * chars / QC_CHUNK_CHARS_PER_SECOND:
            raise AudioQCError(f"chunk {n} truncated ({seconds:.0f}s for {chars} chars)")
    return report


def measured_index(raw: str, mp3_seconds: float) -> dict | None:
    """Piper path: the worker forwards what tools/mycast_render.py measured from the WAV it wrote
    ({"sections", "n_lines", "line_starts", "pcm_seconds"}). None when the episode has no sections."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        n_lines = int(data.get("n_lines") or 0)
        pcm_seconds = float(data.get("pcm_seconds") or 0)
    except (ValueError, TypeError, AttributeError):
        return {"status": "unavailable", "reason": "not_measured", "chapters": [], "pcm_seconds": 0.0, "mp3_seconds": mp3_seconds}
    sections = mycast_timecodes.normalize_sections(data.get("sections"), n_lines)
    if not sections:
        return None
    starts = data.get("line_starts") if isinstance(data.get("line_starts"), dict) else {}
    return mycast_timecodes.build_index(sections, starts, pcm_seconds=pcm_seconds, mp3_seconds=mp3_seconds)


def install_mycast_routes(app, log: DeliveryLog, *, authorize_worker: Callable[[Request], bool],
                          send_audio: Callable[[bytes, str, str, str], None],
                          paired: Callable[[], bool]) -> None:
    @app.post("/api/factory/mycast/worker/deliver")
    async def mycast_deliver(request: Request, episode_id: str = Form(...), title: str = Form(""),
                             caption: str = Form(""), audio: UploadFile = File(...), chapters: str = Form("")):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if not EPISODE_ID_RE.fullmatch(episode_id):
            raise HTTPException(400, "bad episode id")
        if not paired():
            raise HTTPException(409, "Telegram owner chat is not paired")
        data = await audio.read(MAX_AUDIO_BYTES + 1)
        if not data or len(data) > MAX_AUDIO_BYTES:
            raise HTTPException(413, "audio missing or too large")
        try:
            report = check_mp3(data)  # length is checked against the script on the worker side
        except AudioQCError as exc:
            raise HTTPException(422, f"audio qc: {exc.reason}")
        index = measured_index(chapters[:20000] if isinstance(chapters, str) else "", report["seconds"])
        if not log.claim(episode_id):
            log.record(episode_id, "duplicate_refused", voice="piper")
            return {"sent": False, "duplicate": True}
        try:
            send_audio(data, f"{episode_id}.mp3", title or episode_id, mycast_timecodes.compose_caption(caption, index))
        except TelegramUncertain:
            log.record(episode_id, "uncertain", voice="piper")  # the claim stays: a retry could post the MP3 twice
            raise HTTPException(504, "Telegram delivery unconfirmed; not retried to avoid a duplicate")
        except Exception as exc:
            log.release(episode_id)  # let the worker retry
            log.record(episode_id, "failed:telegram", voice="piper")
            raise HTTPException(502, "Telegram delivery failed") from exc
        log.record(episode_id, "sent", voice="piper", chapters=(index or {}).get("status", "none"))
        result = {"sent": True, "duplicate": False, "seconds": report["seconds"]}
        if index:
            result["chapters"] = index
        return result


# --- Gemini voices (owner decision 2026-11-02: natural two-host voice via the owner's Gemini API key) ---
GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_TTS_MODEL = "gemini-2.5-flash-preview-tts"
CHUNK_CHARS = 2800  # ~2 min of speech per call: a 5-8 min episode needs 3-4 calls, inside the free-tier per-minute quota
RATE_LIMIT_RETRIES = 2  # per chunk, only on HTTP 429 (free-tier RPM); never a paid fallback
RATE_LIMIT_WAIT_SECONDS = 30
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


def episode_chunks(lines: list, breaks=()) -> list[list]:
    """breaks: line indexes that must open a new TTS call (section starts), so their offset is measurable."""
    chunks, current, size = [], [], 0
    for n, (host, text) in enumerate(lines):
        if current and (size + len(text) > CHUNK_CHARS or n in breaks):
            chunks.append(current)
            current, size = [], 0
        current.append((host, text))
        size += len(text)
    if current:
        chunks.append(current)
    return chunks


def gemini_tts_pcm(api_key: str, episode: dict, *, model: str = "", voices: tuple[str, str] = ("Charon", "Kore"),
                   opener: Callable = urlrequest.urlopen, sleep: Callable[[float], None] = time.sleep,
                   stats: list | None = None, marks: dict | None = None) -> tuple[bytes, int]:
    """Two-host dialogue → raw PCM (16-bit mono) and its sample rate.
    stats, when given, receives (chars, seconds) per chunk for the truncation check.
    marks, when given, receives {first line index of each call: measured start second in the returned PCM}; each
    tagged section opens its own call, so section starts are measured, pauses included (#468)."""
    model = model or DEFAULT_TTS_MODEL
    breaks = mycast_timecodes.section_breaks(mycast_timecodes.normalize_sections(episode.get("sections"), len(episode["lines"])))
    offsets, first_line, rates = {}, 0, set()
    language = {"uk": "українською", "ru": "русском", "en": "English"}.get(str(episode.get("language") or "uk"), "українською")
    speaker_cfg = [{"speaker": SPEAKER_LABELS[h], "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}}
                   for h, v in zip(("A", "B"), voices)]
    pcm, rate = b"", 24000
    for chunk in episode_chunks(episode["lines"], breaks):
        offsets[first_line] = len(pcm)
        first_line += len(chunk)
        script ="\n".join(f"{SPEAKER_LABELS[h]}: {t}" for h, t in chunk)
        payload = {"contents": [{"parts": [{"text": f"Озвуч цей фрагмент подкасту ({language}) природно, жваво, як двоє ведучих, що розмовляють:\n{script}"}]}],
                   "generationConfig": {"responseModalities": ["AUDIO"],
                                        "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": speaker_cfg}}}}
        result, waits = None, 0
        while result is None:
            try:
                result = _gemini_call(api_key, "POST", f"models/{model}:generateContent", payload, opener)
            except GeminiTTSError as exc:
                if exc.category == "rate_limited" and waits < RATE_LIMIT_RETRIES:
                    waits += 1
                    sleep(RATE_LIMIT_WAIT_SECONDS * waits)  # free-tier requests-per-minute window
                    continue
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
        rates.add(rate)
        audio = base64.b64decode(inline["data"])
        if stats is not None:
            stats.append((sum(len(t) for _, t in chunk), len(audio) / 2 / rate))
        pcm += audio + b"\x00\x00" * int(rate * 0.35)  # short pause between chunks
    if marks is not None and len(rates) == 1:  # mixed sample rates: byte offsets are not seconds, report none
        marks.update({line: round(at / 2 / rate, 6) for line, at in offsets.items()})  # sample-exact
    return pcm, rate


def pcm_to_mp3(pcm: bytes, rate: int, bitrate: int = 96) -> bytes:
    import lameenc

    encoder = lameenc.Encoder()
    encoder.set_bit_rate(bitrate)
    encoder.set_in_sample_rate(rate)
    encoder.set_channels(1)
    encoder.set_quality(2)
    return bytes(encoder.encode(pcm) + encoder.flush())


def install_mycast_voice_routes(app, log: DeliveryLog, *, authorize_worker: Callable[[Request], bool],
                                send_audio: Callable[[bytes, str, str, str], None], paired: Callable[[], bool],
                                api_key: Callable[[], str], model: str = "", voices=("Charon", "Kore"),
                                tts: Callable = gemini_tts_pcm, encode: Callable = pcm_to_mp3,
                                on_result: Optional[Callable[[dict], None]] = None) -> None:
    def _note(**row):  # #140 shared history; a history failure never breaks delivery
        if on_result:
            try:
                on_result(row)
            except Exception:
                pass

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
        sections = mycast_timecodes.normalize_sections(episode.get("sections"), len(lines))
        if not log.claim(episode["id"]):
            log.record(episode["id"], "duplicate_refused", voice="gemini")
            return {"sent": False, "duplicate": True, "voice": "gemini"}
        try:
            def produce():
                stats: list = []
                marks: dict = {}
                params = inspect.signature(tts).parameters
                extra = {name: value for name, value in (("stats", stats), ("marks", marks)) if name in params}
                pcm, rate = tts(key, dict(episode, sections=sections), model=model,
                                voices=tuple(voices() if callable(voices) else voices), **extra)  # #140: owner's stored pair
                check_pcm(pcm, rate, lines, stats)  # silence / length / truncated chunk → not delivered
                audio = encode(pcm, rate)
                mp3 = check_mp3(audio)
                # #468: offsets from the PCM that was encoded; the MP3 length bounds the encoder delay/padding.
                index = (mycast_timecodes.build_index(sections, marks, pcm_seconds=len(pcm) / 2 / rate,
                                                      mp3_seconds=mp3["seconds"]) if sections else None)
                words = sum(len(t.split()) for _, t in lines)
                base = f"🎧 {episode.get('title', '')} · ~{max(1, round(words / 140))} хв · голоси Gemini"
                send_audio(audio, f"{episode['id']}.mp3", str(episode.get("title") or episode["id"])[:64],
                           mycast_timecodes.compose_caption(base, index))
                return pcm, rate, audio, index

            # Several TTS calls (and free-tier waits) take minutes: keep them off the server's event loop.
            pcm, rate, audio, index = await asyncio.to_thread(produce)
        except GeminiTTSError as exc:
            log.release(episode["id"])
            log.record(episode["id"], "failed:" + exc.category, voice="gemini")
            _note(id=episode["id"], status="failed:" + exc.category)
            raise HTTPException(502, f"gemini tts: {exc.category}")
        except AudioQCError as exc:
            log.release(episode["id"])
            log.record(episode["id"], "failed:qc", voice="gemini")
            _note(id=episode["id"], status="failed:qc")
            raise HTTPException(502, f"audio qc: {exc.reason}")
        except TelegramUncertain:
            log.record(episode["id"], "uncertain", voice="gemini")  # claim kept: neither Gemini nor Piper resends it
            _note(id=episode["id"], status="failed:unconfirmed")
            raise HTTPException(504, "Telegram delivery unconfirmed; not retried to avoid a duplicate")
        except Exception:
            log.release(episode["id"])
            log.record(episode["id"], "failed:voice_failed", voice="gemini")
            _note(id=episode["id"], status="failed:voice_failed")
            raise HTTPException(502, "voice delivery failed")
        log.record(episode["id"], "sent", voice="gemini", chapters=(index or {}).get("status", "none"))
        _note(id=episode["id"], status="sent", seconds=round(len(pcm) / 2 / rate))
        result = {"sent": True, "duplicate": False, "voice": "gemini", "seconds": round(len(pcm) / 2 / rate), "bytes": len(audio)}
        if index:
            result["chapters"] = index
        return result
