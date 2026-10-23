import tempfile
from pathlib import Path

from autopilot import notify


def main():
    original_pair_file = notify.PAIR_FILE
    try:
        root = Path(tempfile.mkdtemp(prefix="factoryos-telegram-test-"))
        notify.PAIR_FILE = root / ".autopilot" / "telegram.json"

        assert notify._load_pair() == {}
        assert notify._matches_pair_command("/pair ABCD1234", "ABCD1234") is True
        assert notify._matches_pair_command("/start ABCD1234", "ABCD1234") is True
        assert notify._matches_pair_command("/pair WRONG", "ABCD1234") is False
        assert notify._matches_pair_command("", "ABCD1234") is False

        notify._save_pair("123456789", "owner")
        paired = notify._load_pair()
        assert paired["chat_id"] == "123456789"
        assert paired["username"] == "owner"
        assert notify.chat_id() in {"123456789", notify.ENV_CHAT_ID}
        print("Telegram pairing state tests passed")
    finally:
        notify.PAIR_FILE = original_pair_file


if __name__ == "__main__":
    main()
