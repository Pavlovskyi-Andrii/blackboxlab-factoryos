import os
import time
from typing import Optional

import requests

TOKEN = os.environ.get("TG_TOKEN", "").strip()
CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
_offset = 0


def configured() -> bool:
    return bool(TOKEN and CHAT_ID)


def send(text: str) -> bool:
    if not configured():
        return False
    response = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": CHAT_ID, "text": str(text)[:4000]},
        timeout=20,
    )
    response.raise_for_status()
    return True


def wait_answer(timeout_seconds: Optional[int] = None) -> Optional[str]:
    global _offset
    if not configured():
        return None

    started = time.monotonic()
    while True:
        if timeout_seconds and time.monotonic() - started >= timeout_seconds:
            return None
        response = requests.get(
            f"{API}/getUpdates",
            params={"offset": _offset, "timeout": 45},
            timeout=55,
        )
        response.raise_for_status()
        payload = response.json()
        for update in payload.get("result", []):
            _offset = max(_offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if str(chat.get("id", "")) != CHAT_ID:
                continue
            text = message.get("text")
            if text:
                return str(text)
        time.sleep(1)
