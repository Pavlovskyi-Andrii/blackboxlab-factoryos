"""MyCast delivery: the EC2 worker uploads a rendered episode; the server sends it to the owner's Telegram.

The bot token never leaves the server. Only the worker token may deliver; each episode id is sent once.
"""
from __future__ import annotations

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
