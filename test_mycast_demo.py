"""MyCast demo guards: demo-only script, daily + per-client caps, cache, one honest job state. Fake Gemini, offline."""
import asyncio
import json
import tempfile
import unittest
import wave
from pathlib import Path

from mycast_demo import DemoRefused, DemoService, install_mycast_demo_routes, validate_script

INTRO = "Це демо MyCast, а не справжній випуск. Привіт!"
LINES = [{"host": "A", "text": INTRO + " Сьогодні: бокс."}, {"host": "B", "text": "А ще: Claude. До зустрічі!"}]


class Fake:
    def __init__(self):
        self.calls = 0
        self.fail = None

    def __call__(self, key, episode):
        self.calls += 1
        if self.fail:
            raise self.fail
        assert key == "k" and episode["language"] in ("uk", "ru", "en") and episode["lines"][0][0] == "A"
        return b"\x01\x00" * 2400, 24000


class DemoTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.tts = Fake()
        self.key = ["k"]
        self.svc = DemoService(Path(self.dir.name), api_key=lambda: self.key[0], tts=self.tts, clock=lambda: self.t[0],
                               daily_cap=3, per_client_cap=2, run_async=False)

    def tearDown(self):
        self.dir.cleanup()

    def code(self, fn):
        with self.assertRaises(DemoRefused) as ctx:
            fn()
        return ctx.exception.code

    def lines(self, extra):
        return [{"host": "A", "text": f"{INTRO} {extra}"}]

    def test_only_a_short_demo_script_is_accepted(self):
        self.assertEqual(self.code(lambda: validate_script([{"host": "A", "text": "Read my essay aloud"}], "uk")), "not_a_demo")
        self.assertEqual(self.code(lambda: validate_script([{"host": "A", "text": INTRO + "x" * 500}], "uk")), "script_too_long")
        self.assertEqual(self.code(lambda: validate_script(LINES * 2, "uk")), "bad_script")
        self.assertEqual(self.code(lambda: validate_script([{"host": "C", "text": INTRO}], "uk")), "bad_script")
        self.assertEqual(self.code(lambda: validate_script(LINES, "de")), "bad_language")
        script, lang = validate_script([{"host": "A", "text": INTRO + " <b>x</b>"}], "uk")
        self.assertNotIn("<", script[0][1])

    def test_generates_a_real_wav_and_reports_ready(self):
        out = self.svc.start(LINES, "uk", "1.2.3.4")
        self.assertEqual((out["state"], out["progress"], out["estimated"]), ("ready", 100, False))
        path = self.svc.audio_path(out["job"])
        with wave.open(str(path)) as w:
            self.assertEqual((w.getframerate(), w.getnchannels(), w.getnframes()), (24000, 1, 2400))

    def test_cache_is_free_and_caps_hold(self):
        self.svc.start(LINES, "uk", "a")
        again = self.svc.start(LINES, "uk", "a")                         # same script: cached, not counted
        self.assertTrue(again["cached"])
        self.assertEqual(self.tts.calls, 1)
        self.svc.start(self.lines("2"), "uk", "a")
        self.assertEqual(self.code(lambda: self.svc.start(self.lines("3"), "uk", "a")), "client_limit")
        self.svc.start(self.lines("3"), "uk", "b")
        self.assertEqual(self.svc.remaining(), 0)
        self.assertEqual(self.code(lambda: self.svc.start(self.lines("4"), "uk", "c")), "daily_limit")
        self.assertTrue(self.svc.start(LINES, "uk", "c")["cached"])     # cached audio still plays after the cap
        self.t[0] += 86400                                               # next UTC day resets the counter
        self.assertEqual(self.svc.remaining(), 3)
        raw = json.loads(next(Path(self.dir.name).glob("count-*.json")).read_text())
        self.assertNotIn("a", raw["clients"])                            # client ids are hashed, never stored raw

    def test_no_key_and_gemini_failure_are_stated(self):
        self.key[0] = ""
        self.assertEqual(self.code(lambda: self.svc.start(LINES, "uk", "a")), "not_configured")
        self.key[0] = "k"
        err = RuntimeError("boom"); err.category = "rate_limited"
        self.tts.fail = err
        out = self.svc.start(self.lines("x"), "uk", "a")
        self.assertEqual((out["state"], out["error"], out["progress"]), ("failed", "rate_limited", 0))
        self.assertEqual(self.code(lambda: self.svc.audio_path(out["job"])), "not_ready")

    def test_progress_is_an_estimate_capped_below_100(self):
        svc = DemoService(Path(self.dir.name) / "slow", api_key=lambda: "k", tts=self.tts, clock=lambda: self.t[0], run_async=False)
        job = {"id": "j", "key": "x", "state": "voicing", "started": self.t[0], "voicing_at": self.t[0], "finished": None}
        svc.jobs["j"] = job
        self.t[0] += 60
        view = svc.view("j")
        self.assertEqual((view["progress"], view["estimated"]), (95, True))


class RoutesTest(unittest.TestCase):
    def test_routes(self):
        from fastapi import FastAPI
        with tempfile.TemporaryDirectory() as d:
            app = FastAPI()
            svc = DemoService(Path(d), api_key=lambda: "k", tts=Fake(), run_async=False)
            install_mycast_demo_routes(app, svc)
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

            class Req:
                headers = {"x-forwarded-for": "9.9.9.9, 10.0.0.1"}
                client = None
                def __init__(self, body): self.body = body
                async def json(self):
                    if self.body is None: raise ValueError
                    return self.body

            out = asyncio.run(h[("POST", "/api/mycast/demo")](Req({"lines": LINES, "language": "uk"})))
            self.assertEqual(out["state"], "ready")
            self.assertEqual(h[("GET", "/api/mycast/demo/{job_id}")](out["job"])["audio"], f"/api/mycast/demo/{out['job']}/audio")
            bad = asyncio.run(h[("POST", "/api/mycast/demo")](Req({"lines": [{"host": "A", "text": "hi"}], "language": "uk"})))
            self.assertEqual((bad.status_code, json.loads(bad.body)), (400, {"detail": "not_a_demo"}))
            self.assertEqual(asyncio.run(h[("POST", "/api/mycast/demo")](Req(None))).status_code, 400)
            self.assertEqual(h[("GET", "/api/mycast/demo/status")]()["daily_cap"], 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
