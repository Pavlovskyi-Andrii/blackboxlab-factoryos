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
        from mycast_voices import NAMES
        self.assertEqual(VOICES, frozenset(NAMES))                      # one catalogue for the whole app

    def test_pair_rule_matches_the_demo(self):
        with tempfile.TemporaryDirectory() as d:
            store = VoiceSettingsStore(Path(d))
            for a, b in (("Kore", "Puck"), ("Puck", "Puck"), ("Puck", "Charon")):   # female A, same voice, two male
                with self.assertRaises(ValueError):
                    store.write({"voice_a": a, "voice_b": b, "model": DEFAULT_MODEL})
            self.assertEqual(store.current_pair(), ("Charon", "Kore"))          # nothing stored: env default
            store.write({"voice_a": "Puck", "voice_b": "Leda", "model": DEFAULT_MODEL})
            self.assertEqual(store.current_pair(), ("Puck", "Leda"))
            store.path.write_text("{oops")
            self.assertEqual(store.current_pair(), ("Charon", "Kore"))           # damaged file never breaks delivery

    def test_owner_only_routes(self):
        import asyncio
        from fastapi import FastAPI
        from voice_settings import install_voice_settings_routes
        with tempfile.TemporaryDirectory() as d:
            app, owner = FastAPI(), [True]
            install_voice_settings_routes(app, VoiceSettingsStore(Path(d)), is_owner=lambda r: owner[0])
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

            class Req:
                def __init__(self, body=None): self.body = body
                async def json(self):
                    if self.body is None: raise ValueError
                    return self.body

            got = h[("GET", "/api/factory/voice/settings")](Req())
            self.assertEqual((got["settings"]["voice_a"], got["state"], len(got["available_voices"])), ("Charon", "ok", 30))
            ok = asyncio.run(h[("POST", "/api/factory/voice/settings")](Req({"voice_a": "Orus", "voice_b": "Leda", "model": DEFAULT_MODEL})))
            self.assertEqual(ok["settings"]["voice_a"], "Orus")
            bad = asyncio.run(h[("POST", "/api/factory/voice/settings")](Req({"voice_a": "Leda", "voice_b": "Orus", "model": DEFAULT_MODEL})))
            self.assertEqual((bad.status_code, json.loads(bad.body)["detail"]), (400, "invalid_voice_pair"))
            self.assertEqual(asyncio.run(h[("POST", "/api/factory/voice/settings")](Req(None))).status_code, 400)
            owner[0] = False
            self.assertEqual(h[("GET", "/api/factory/voice/settings")](Req()).status_code, 403)
            self.assertEqual(asyncio.run(h[("POST", "/api/factory/voice/settings")](Req({}))).status_code, 403)


if __name__ == "__main__":
    unittest.main()
