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


class HistoryAndBriefTests(unittest.TestCase):
    """#140 follow-up: shared delivery history and a once-per-date morning brief to the owner's own chat."""

    def setUp(self):
        import asyncio
        from fastapi import FastAPI
        from mycast import DeliveryLog
        from voice_settings import VoiceHistory, install_brief_route, install_voice_history_routes
        self.run = asyncio.run
        self.dir = tempfile.TemporaryDirectory()
        d = Path(self.dir.name)
        self.store, self.history = VoiceSettingsStore(d), VoiceHistory(d, clock=lambda: 1_800_000_000)
        self.store.write({"voice_a": "Orus", "voice_b": "Leda", "model": DEFAULT_MODEL})
        self.sent, self.err, self.key, self.paired, self.owner = [], [None], ["k"], [True], [True]

        def tts(key, text, voice):
            if self.err[0]:
                raise self.err[0]
            return b"\x01\x00" * 24000, 24000
        app = FastAPI()
        install_voice_history_routes(app, self.history, is_owner=lambda r: self.owner[0])
        install_brief_route(app, self.history, DeliveryLog(d / "log.json"), self.store,
                            authorize_worker=lambda r: getattr(r, "worker", True), api_key=lambda: self.key[0],
                            paired=lambda: self.paired[0], tts_single=tts, encode=lambda pcm, rate: b"MP3",
                            send_audio=lambda audio, name, title, caption: self.sent.append((name, caption)))
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

    def tearDown(self):
        self.dir.cleanup()

    def brief(self, body, worker=True):
        class Req:
            async def json(self_):
                if body is None: raise ValueError
                return body
        r = Req(); r.worker = worker
        try:
            return self.run(self.h[("POST", "/api/factory/voice/worker/brief-deliver")](r))
        except Exception as exc:
            return getattr(exc, "status_code", exc)

    def test_brief_once_per_date_in_host_a_voice(self):
        out = self.brief({"date": "2026-11-08", "text": "Доброго ранку. Три новини."})
        self.assertEqual((out["sent"], out["voice"], out["seconds"]), (True, "Orus", 1))
        self.assertEqual(self.brief({"date": "2026-11-08", "text": "again"}), {"sent": False, "duplicate": True})
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Ранковий брифінг", self.sent[0][1])
        rows = self.h[("GET", "/api/factory/voice/history")](None)["deliveries"]
        self.assertEqual([(r["kind"], r["id"], r["status"], r["voice"]) for r in rows], [("brief", "brief-2026-11-08", "sent", "Orus")])

    def test_brief_refusals(self):
        self.assertEqual(self.brief({"date": "8 Nov", "text": "x"}), 400)
        self.assertEqual(self.brief({"date": "2026-11-08", "text": "x" * 1401}), 400)
        self.assertEqual(self.brief(None), 400)
        self.assertEqual(self.brief({"date": "2026-11-08", "text": "x"}, worker=False), 401)
        self.key[0] = ""
        self.assertEqual(self.brief({"date": "2026-11-08", "text": "x"}), 409)
        self.key[0], self.paired[0] = "k", False
        self.assertEqual(self.brief({"date": "2026-11-08", "text": "x"}), 409)
        self.assertEqual(self.sent, [])

    def test_failure_is_recorded_and_retry_allowed(self):
        err = RuntimeError("provider text"); err.category = "rate_limited"
        self.err[0] = err
        self.assertEqual(self.brief({"date": "2026-11-09", "text": "x"}), 502)
        self.err[0] = None
        self.assertTrue(self.brief({"date": "2026-11-09", "text": "x"})["sent"])      # the claim was released
        statuses = [r["status"] for r in self.history.entries()]
        self.assertEqual(statuses, ["failed:rate_limited", "sent"])
        self.assertNotIn("provider text", json.dumps(self.history.entries()))

    def test_history_is_owner_only_and_bounded(self):
        self.owner[0] = False
        self.assertEqual(self.h[("GET", "/api/factory/voice/history")](None).status_code, 403)
        for i in range(205):
            self.history.record(kind="mycast", item_id=f"mycast-{i}", voice="Charon+Kore", status="sent")
        self.assertEqual(len(self.history.entries()), 200)
        with self.assertRaises(ValueError):
            self.history.record(kind="other", item_id="x", voice="v", status="sent")

    def test_daily_delivery_reports_to_history(self):
        import mycast
        from fastapi import FastAPI
        rows, app = [], FastAPI()
        mycast.install_mycast_voice_routes(app, mycast.DeliveryLog(Path(self.dir.name) / "d.json"), authorize_worker=lambda r: True,
                                           send_audio=lambda *a: None, paired=lambda: True, api_key=lambda: "k",
                                           voices=lambda: ("Orus", "Leda"),
                                           tts=lambda key, ep, model="", voices=(): (_ for _ in ()).throw(mycast.GeminiTTSError("rate_limited")),
                                           on_result=rows.append)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

        class Req:
            async def json(self_):
                return {"episode": {"id": "mycast-2026-11-08", "lines": [["A", "Привіт"]]}}
        with self.assertRaises(Exception):
            self.run(h[("POST", "/api/factory/mycast/worker/voice-deliver")](Req()))
        self.assertEqual(rows, [{"id": "mycast-2026-11-08", "status": "failed:rate_limited"}])



class FullAppRoutesTest(unittest.TestCase):
    """Route audit #114 found every /api/factory/voice/* route answering 422: `Request` was imported inside the
    install functions, so with postponed annotations FastAPI read `request` as a required query parameter.
    Calling the real ASGI app (middleware included) catches that; direct endpoint calls did not."""

    def test_voice_routes_resolve_through_the_real_app(self):
        from test_worker_token_binding import asgi_get, asgi_post, factory
        from unittest.mock import patch
        with patch.object(factory, "FACTORY_PASSWORD", ""):      # open mode: the caller is the owner
            status, body = asgi_get("/api/factory/voice/settings")
            self.assertEqual(status, 200, body)
            self.assertIn(b"available_voices", body)
            self.assertEqual(asgi_get("/api/factory/voice/history")[0], 200)
        status, body = asgi_post("/api/factory/voice/worker/brief-deliver", body=b'{"date":"2026-11-08","text":"x"}')
        self.assertEqual(status, 401, body)                    # no worker token: refused, not 422


if __name__ == "__main__":
    unittest.main()
