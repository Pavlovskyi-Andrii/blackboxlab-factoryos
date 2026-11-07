"""Owner-only MyCast voice preference persistence (Issue #140).

Pure storage component: API auth, TTS and delivery are deliberately not implemented here.
Never expose this file through a public static route.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

VOICES = frozenset("""Achernar Achird Algenib Algieba Alnilam Aoede Autonoe Callirrhoe Charon
Despina Enceladus Erinome Fenrir Gacrux Iapetus Kore Laomedeia Leda
Orus Puck Pulcherrima Rasalgethi Sadachbia Sadaltager Schedar Sulafat
Umbriel Vindemiatrix Zephyr Zubenelgenubi""".split())
DEFAULT_MODEL = "gemini-2.5-flash-preview-tts"
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
