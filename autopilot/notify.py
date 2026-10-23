import json
import os
import pathlib
import secrets
import sys
import time
from typing import Optional

import requests

TOKEN = os.environ.get("TG_TOKEN", "").strip()
ENV_CHAT_ID = os.environ.get("TG_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else ""
REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO", "/work/factoryos")).resolve()
PAIR_FILE = pathlib.Path(
    os.environ.get("TG_PAIRING_FILE", str(REPO / ".autopilot" / "telegram.json"))
).resolve()
PAIR_TIMEOUT_SECONDS = max(
    60, min(3600, int(os.environ.get("TG_PAIR_TIMEOUT_SECONDS", "600")))
)
_offset = 0


def _load_pair() -> dict:
    if not PAIR_FILE.exists():
        return {}
    try:
        value = json.loads(PAIR_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _save_pair(chat_id: str, username: str = "") -> None:
    PAIR_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "chat_id": str(chat_id),
        "username": str(username or ""),
        "paired_at": int(time.time()),
    }
    PAIR_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        PAIR_FILE.chmod(0o600)
    except OSError:
        pass


def chat_id() -> str:
    if ENV_CHAT_ID:
        return ENV_CHAT_ID
    return str(_load_pair().get("chat_id") or "").strip()


def configured() -> bool:
    return bool(TOKEN and chat_id())


def validate_bot() -> dict:
    if not TOKEN:
        raise RuntimeError("TG_TOKEN is not configured")
    response = requests.get(f"{API}/getMe", timeout=20)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("result") or {}
    if not payload.get("ok") or not result.get("id"):
        raise RuntimeError("Telegram getMe did not return a valid bot")
    return result


def _matches_pair_command(text: str, code: str) -> bool:
    cleaned = " ".join(str(text or "").strip().split())
    expected = str(code).strip()
    if not expected:
        return False
    return cleaned in {f"/pair {expected}", f"/start {expected}"}


def pair(timeout_seconds: Optional[int] = None, code: Optional[str] = None) -> dict:
    global _offset
    bot = validate_bot()
    pair_code = (code or secrets.token_hex(4)).strip()
    timeout = int(timeout_seconds or PAIR_TIMEOUT_SECONDS)
    username = str(bot.get("username") or "")
    print(f"Telegram bot: @{username}" if username else "Telegram bot validated")
    print(f"Send this message to the bot within {timeout}s: /pair {pair_code}")
    started = time.monotonic()

    while time.monotonic() - started < timeout:
        remaining = max(1, int(timeout - (time.monotonic() - started)))
        long_poll = min(45, remaining)
        response = requests.get(
            f"{API}/getUpdates",
            params={"offset": _offset, "timeout": long_poll},
            timeout=long_poll + 10,
        )
        response.raise_for_status()
        payload = response.json()
        for update in payload.get("result", []):
            _offset = max(_offset, int(update.get("update_id", 0)) + 1)
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if str(chat.get("type") or "") != "private":
                continue
            text = str(message.get("text") or "")
            if not _matches_pair_command(text, pair_code):
                continue
            owner_chat_id = str(chat.get("id") or "").strip()
            if not owner_chat_id:
                continue
            owner_username = str((message.get("from") or {}).get("username") or "")
            _save_pair(owner_chat_id, owner_username)
            send("✅ FactoryOS Telegram pairing complete. I will use this chat for HUMAN blockers and autopilot stop alerts.")
            return {"chat_id": owner_chat_id, "username": owner_username}

    raise TimeoutError("Telegram pairing timed out before the correct /pair code was received")


def send(text: str) -> bool:
    target = chat_id()
    if not TOKEN or not target:
        return False
    response = requests.post(
        f"{API}/sendMessage",
        json={"chat_id": target, "text": str(text)[:4000]},
        timeout=20,
    )
    response.raise_for_status()
    return True


def wait_answer(timeout_seconds: Optional[int] = None) -> Optional[str]:
    global _offset
    target = chat_id()
    if not TOKEN or not target:
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
            if str(chat.get("id", "")) != target:
                continue
            text = message.get("text")
            if text:
                return str(text)
        time.sleep(1)


def main(argv: Optional[list[str]] = None) -> int:
    args = list(argv or sys.argv[1:])
    command = args[0] if args else "status"

    if command == "status":
        bot = validate_bot() if TOKEN else {}
        print(
            json.dumps(
                {
                    "bot_configured": bool(TOKEN),
                    "bot_username": bot.get("username") if bot else None,
                    "paired": bool(chat_id()),
                    "pair_file": str(PAIR_FILE),
                },
                ensure_ascii=False,
            )
        )
        return 0

    if command == "pair":
        pair()
        return 0

    raise SystemExit("Usage: python -m autopilot.notify [status|pair]")


if __name__ == "__main__":
    raise SystemExit(main())
