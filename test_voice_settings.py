"""Offline regression tests for #140 voice settings storage."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from voice_settings import DEFAULT_MODEL, VOICES, VoiceSettingsStore


class VoiceSettingsTests(unittest.TestCase):
    def test_default_and_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            store = VoiceSettingsStore(Path(d))
            with patch.dict("os.environ", {"FACTORY_MYCAST_VOICE_A": "Charon", "FACTORY_MYCAST_VOICE_B": "Kore"}):
                self.assertEqual(store.read()["voice_a"], "Charon")
            chosen = {"voice_a": "Puck", "voice_b": "Aoede", "model": DEFAULT_MODEL}
            self.assertEqual(store.write(chosen), chosen)
            self.assertEqual(VoiceSettingsStore(Path(d)).read(), chosen)
            self.assertEqual(json.loads(store.path.read_text()), chosen)
            self.assertEqual(store.path.stat().st_mode & 0o777, 0o600)

    def test_rejects_invalid_and_preserves_previous(self):
        with tempfile.TemporaryDirectory() as d:
            store = VoiceSettingsStore(Path(d))
            good = {"voice_a": "Charon", "voice_b": "Kore", "model": DEFAULT_MODEL}
            store.write(good)
            for invalid in (
                {**good, "voice_a": "../../etc/passwd"},
                {**good, "model": "unapproved-paid-model"},
                {**good, "api_key": "secret"},
                {**good, "voice_b": 7},
                [],
            ):
                with self.subTest(invalid=invalid):
                    with self.assertRaises(ValueError):
                        store.write(invalid)
                    self.assertEqual(store.read(), good)

    def test_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            store = VoiceSettingsStore(Path(d))
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.path.write_text('{"voice_a": "oops"}')
            with self.assertRaises(ValueError):
                store.read()

    def test_failed_atomic_replace_preserves_saved_choice_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as d:
            store = VoiceSettingsStore(Path(d))
            original = {"voice_a": "Charon", "voice_b": "Kore", "model": DEFAULT_MODEL}
            replacement = {"voice_a": "Puck", "voice_b": "Aoede", "model": DEFAULT_MODEL}
            store.write(original)
            with patch("voice_settings.os.replace", side_effect=OSError("simulated replace failure")):
                with self.assertRaises(OSError):
                    store.write(replacement)
            self.assertEqual(store.read(), original)
            self.assertEqual(list(Path(d).glob(".mycast-voice-*.tmp")), [])

    def test_catalog(self):
        self.assertEqual(len(VOICES), 30)


if __name__ == "__main__":
    unittest.main()
