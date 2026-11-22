"""#281 voice audition: 30 prebuilt voices, real cached samples, honest unavailable states, cap. Fake Gemini, offline."""
import asyncio
import tempfile
import unittest
import wave
from pathlib import Path

from mycast_voices import DEFAULTS, NAMES, VOICES, VoiceRefused, VoiceSamples, install_mycast_voice_audition_routes, valid_voices


class Fake:
    def __init__(self):
        self.calls, self.fail_for = [], set()

    def __call__(self, key, text, voice):
        self.calls.append(voice)
        if voice in self.fail_for:
            err = RuntimeError("x"); err.category = "rate_limited"
            raise err
        assert voice in text
        return b"\x02\x00" * 1200, 24000


class VoicesTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.fake = Fake()
        self.key = ["k"]
        self.s = VoiceSamples(Path(self.dir.name), api_key=lambda: self.key[0], tts=self.fake, clock=lambda: self.t[0], daily_cap=3)

    def tearDown(self):
        self.dir.cleanup()

    def test_catalogue_is_thirty_named_voices_with_unofficial_gender(self):
        self.assertEqual(len(VOICES), 30)
        self.assertEqual(len(NAMES), 30)
        cat = self.s.catalogue("uk")
        self.assertEqual({v["gender_source"] for v in cat["voices"]}, {"by_ear"})
        self.assertEqual({v["sample"] for v in cat["voices"]}, {"not_generated"})       # nothing claimed playable yet
        self.assertTrue(all("url" not in v for v in cat["voices"]))
        self.assertTrue(valid_voices("narrator", list(DEFAULTS["narrator"])) and valid_voices("two_hosts", list(DEFAULTS["two_hosts"])))

    def test_page_catalogue_matches_the_server(self):
        import re
        js = Path(__file__).resolve().parent.joinpath("static/mycast-configurator/configurator.js").read_text(encoding="utf-8")
        block = js.split("const GEMINI_VOICES = [", 1)[1].split("];", 1)[0]
        page = [tuple(m) for m in re.findall(r"\['(\w+)', '([\w-]+)', '([mf])'\]", block)]
        self.assertEqual(page, [tuple(v) for v in VOICES])

    def test_voice_rules(self):
        self.assertTrue(valid_voices("narrator", ["Puck"]))
        self.assertFalse(valid_voices("narrator", ["Kore"]))              # single host: a male-by-ear voice
        self.assertTrue(valid_voices("two_hosts", ["Puck", "Kore"]))
        self.assertFalse(valid_voices("two_hosts", ["Kore", "Puck"]))     # host A male, host B female
        self.assertFalse(valid_voices("two_hosts", ["Puck", "Puck"]))
        self.assertFalse(valid_voices("two_hosts", ["Puck", "Nobody"]))

    def test_real_sample_then_cache(self):
        out = self.s.sample("Puck", "uk")
        self.assertEqual((out["state"], out["cached"]), ("ready", False))
        with wave.open(str(self.s.file("Puck", "uk"))) as w:
            self.assertEqual((w.getframerate(), w.getnframes()), (24000, 1200))
        self.assertTrue(self.s.sample("Puck", "uk")["cached"])
        self.assertEqual(self.fake.calls, ["Puck"])
        ready = {v["name"]: v for v in self.s.catalogue("uk")["voices"]}["Puck"]
        self.assertEqual((ready["sample"], ready["url"]), ("ready", "/api/mycast/voices/Puck/uk.wav"))

    def test_failure_is_unavailable_with_reason_and_not_retried_for_an_hour(self):
        self.fake.fail_for.add("Kore")
        self.assertEqual(self.s.sample("Kore", "uk"), {"voice": "Kore", "state": "unavailable", "reason": "rate_limited"})
        self.s.sample("Kore", "uk")
        self.assertEqual(self.fake.calls.count("Kore"), 1)
        self.assertEqual({v["name"]: v for v in self.s.catalogue("uk")["voices"]}["Kore"]["sample"], "unavailable")
        self.t[0] += 3601
        self.fake.fail_for.clear()
        self.assertEqual(self.s.sample("Kore", "uk")["state"], "ready")

    def test_cap_unknown_voice_and_no_key(self):
        for v in ("Puck", "Charon", "Orus"):
            self.s.sample(v, "uk")
        with self.assertRaises(VoiceRefused) as ctx:
            self.s.sample("Fenrir", "uk")
        self.assertEqual(ctx.exception.code, "daily_limit")
        self.assertTrue(self.s.sample("Puck", "uk")["cached"])                        # cached plays stay free
        self.assertRaises(VoiceRefused, self.s.sample, "Nobody", "uk")
        self.assertRaises(VoiceRefused, self.s.sample, "Puck", "de")
        self.key[0] = ""
        with self.assertRaises(VoiceRefused) as ctx:
            self.s.sample("Leda", "uk")
        self.assertEqual(ctx.exception.code, "not_configured")
        self.assertRaises(VoiceRefused, self.s.file, "../x", "uk")

    def test_routes(self):
        from fastapi import FastAPI
        app = FastAPI()
        install_mycast_voice_audition_routes(app, self.s)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

        class Req:
            async def json(self):
                return {"language": "en"}

        self.assertEqual(len(h[("GET", "/api/mycast/voices")]("en")["voices"]), 30)
        self.assertEqual(asyncio.run(h[("POST", "/api/mycast/voices/{voice}/sample")]("Iapetus", Req()))["state"], "ready")
        self.assertEqual(h[("GET", "/api/mycast/voices/{voice}/{lang}.wav")]("Iapetus", "en").media_type, "audio/wav")
        self.assertEqual(h[("GET", "/api/mycast/voices/{voice}/{lang}.wav")]("Iapetus", "uk").status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
