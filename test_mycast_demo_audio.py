"""T-665: owner-made Gemini voicing of the MyCast demo cities. Offline: a fake TTS, no Gemini, no network.

Covers the repo scripts, idempotency (no second voicing without "regenerate"), the per-run and daily limits, a 429
stopping the run, owner-only routes, approval (and its withdrawal on regenerate), the public route serving approved
tracks only, and the shared-episode page playing approved tracks only, with escaping intact."""
import asyncio
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

from fastapi import FastAPI

import mycast
import mycast_demo_audio as mda
import mycast_share_page as sp

ROOT = pathlib.Path(__file__).parent
CITIES = ["athens", "rome", "delphi", "olympia", "pompeii"]


class Clock:
    def __init__(self, t=1794873600.0):          # 2026-11-16T00:00:00Z
        self.t = t

    def __call__(self):
        return self.t


class FakeTTS:
    def __init__(self):
        self.calls, self.fail = [], {}

    def __call__(self, key, episode):
        assert key == "k"
        self.calls.append(episode)
        n = len(self.calls)
        if n in self.fail:
            raise self.fail[n]
        return b"\x01\x00" * 2400, 24000


class Req:
    def __init__(self, body=None, owner=True, ctype="application/json"):
        self._body, self.owner = body, owner
        self.headers = {"content-type": ctype} if ctype else {}

    async def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "data"
        self.tts, self.clock, self.sleeps = FakeTTS(), Clock(), []
        self.key = "k"
        self.store = self.make()

    def make(self, **kw):
        args = dict(api_key=lambda: self.key, tts=self.tts, encode=lambda pcm, rate: b"ID3" + pcm[:10],
                    clock=self.clock, sleep=self.sleeps.append, background=False)
        args.update(kw)
        return mda.DemoAudioStore(self.root, **args)

    def tearDown(self):
        self.tmp.cleanup()

    def track(self, city, lang="uk"):
        return next(c for c in self.store.status()["cities"] if c["id"] == city)["tracks"][lang]


class ScriptsTest(unittest.TestCase):
    def test_every_city_has_a_valid_sourced_script_in_every_language(self):
        ids = [c["id"] for c in mda.manifest_cities()]
        self.assertEqual(ids, CITIES)
        for city in ids:
            for lang in mda.LANGS:
                s = mda.load_script(city, lang)
                words = sum(len(t.split()) for _, t in s["lines"])
                self.assertTrue(170 <= words <= 300, (city, lang, words))      # 1-2 minutes of speech
                self.assertEqual({h for h, _ in s["lines"]}, {"A", "B"}, (city, lang))
                self.assertTrue(s["sources"] and all(u.startswith("https://") for u in s["sources"]), (city, lang))
                # one TTS request per city: the script fits a single mycast chunk
                self.assertEqual(len(mycast.episode_chunks(s["lines"])), 1, (city, lang))

    def test_bad_names_and_scripts_are_refused(self):
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            for name in ("../app", "Athens", "a/b"):
                with self.assertRaises(mda.DemoAudioRefused):
                    mda.load_script(name, "uk", d)
            with self.assertRaises(mda.DemoAudioRefused):
                mda.load_script("athens", "de", d)
            (d / "x.uk.json").write_text(json.dumps({"id": "x", "language": "uk", "lines": [{"host": "C", "text": "a"}] * 2}))
            with self.assertRaisesRegex(mda.DemoAudioRefused, "bad_script"):
                mda.load_script("x", "uk", d)
            (d / "x.uk.json").write_text(json.dumps({"id": "x", "language": "uk", "lines": [{"host": "A", "text": "a" * 2000}] * 2}))
            with self.assertRaisesRegex(mda.DemoAudioRefused, "script_too_long"):
                mda.load_script("x", "uk", d)


class StoreTest(Base):
    def test_generate_is_idempotent_and_regenerate_withdraws_approval(self):
        job = self.store.start(["athens"], "uk")
        self.assertEqual((job["state"], job["results"][0]["result"]), ("done", "generated"))
        self.assertEqual(len(self.tts.calls), 1)
        self.assertEqual(self.tts.calls[0]["language"], "uk")
        self.assertTrue((self.root / "athens.uk.mp3").read_bytes().startswith(b"ID3"))
        self.assertEqual(self.track("athens")["state"], "generated")
        again = self.store.start(["athens"], "uk")                           # no second voicing
        self.assertEqual(again["results"], [{"id": "athens", "language": "uk", "result": "cached"}])
        self.assertEqual(len(self.tts.calls), 1)
        self.store.set_approved("athens", "uk", True)
        self.assertEqual(self.track("athens")["state"], "approved")
        self.store.start(["athens"], "uk", regenerate=True)                   # explicit regenerate only
        self.assertEqual(len(self.tts.calls), 2)
        self.assertEqual(self.track("athens")["state"], "generated")          # new audio is not approved
        self.assertFalse(self.store.is_approved("athens", "uk"))

    def test_run_cap_and_daily_cap(self):
        with self.assertRaisesRegex(mda.DemoAudioRefused, "run_limit"):
            self.make(run_cap=2).start(["athens", "rome", "delphi"], "uk")
        store = self.make(daily_cap=3)
        job = store.start("all", "uk")                                       # 5 cities, 3 left today
        self.assertEqual(job["state"], "stopped")
        self.assertEqual(job["message"], "daily_limit")
        self.assertEqual([r["result"] for r in job["results"]], ["generated"] * 3 + ["skipped_daily_limit"] * 2)
        self.assertEqual(len(self.tts.calls), 3)
        self.assertEqual(self.sleeps, [mda.PAUSE_SECONDS] * 2)                # paced between calls
        with self.assertRaisesRegex(mda.DemoAudioRefused, "daily_limit"):
            store.start(["olympia"], "uk")
        self.clock.t += 86400                                               # a new UTC day
        self.assertEqual(store.start(["olympia"], "uk")["results"][0]["result"], "generated")

    def test_failed_attempts_count_and_other_errors_do_not_stop_the_run(self):
        self.tts.fail[1] = mycast.GeminiTTSError("no_audio")
        job = self.store.start(["athens", "rome"], "ru")
        self.assertEqual([r["result"] for r in job["results"]], ["failed", "generated"])
        self.assertEqual(self.store.used_today(), 2)
        self.assertEqual(self.track("athens", "ru")["last_error"], "no_audio")

    def test_qc_failure_keeps_no_file(self):
        def qc(pcm, rate, lines):
            raise mycast.AudioQCError("silence")
        job = self.make(qc=qc).start(["rome"], "uk")
        self.assertEqual(job["results"][0], {"id": "rome", "language": "uk", "result": "failed", "reason": "qc_failed"})
        self.assertFalse((self.root / "rome.uk.mp3").exists())

    def test_429_stops_the_run_with_a_plain_message(self):
        self.tts.fail[2] = mycast.GeminiTTSError("rate_limited")
        job = self.store.start(["athens", "rome", "delphi"], "uk")
        self.assertEqual(job["state"], "stopped")
        self.assertEqual(job["message"], "quota_exhausted")
        self.assertEqual([r["result"] for r in job["results"]], ["generated", "quota_exhausted", "not_started"])
        self.assertEqual(len(self.tts.calls), 2)                              # no retry, nothing after the 429
        self.assertTrue(self.store.status()["last_quota_error"])
        self.assertIn("429", mda.QUOTA_MESSAGE["ru"])
        self.assertIn("завтра", mda.QUOTA_MESSAGE["ru"])

    def test_app_tts_adapter_does_not_wait_on_429(self):
        import urllib.error
        calls = []

        def opener(req, timeout=0):
            calls.append(req)
            raise urllib.error.HTTPError(req.full_url, 429, "quota", {}, None)

        def stop(_s):
            raise mycast.GeminiTTSError("rate_limited")
        with self.assertRaisesRegex(mycast.GeminiTTSError, "rate_limited"):
            mycast.gemini_tts_pcm("k", {"language": "uk", "lines": [("A", "a"), ("B", "b")]}, opener=opener, sleep=stop)
        self.assertEqual(len(calls), 1)
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertRegex(src, r"def _mycast_demo_tts_no_retry[\s\S]{0,400}sleep=_stop")

    def test_no_key_and_bad_input(self):
        self.key = ""
        with self.assertRaisesRegex(mda.DemoAudioRefused, "not_configured"):
            self.store.start(["athens"], "uk")
        self.key = "k"
        for cities, lang in ((["athens"], "de"), (["nowhere"], "uk"), ([], "uk"), ("athens", "uk")):
            with self.assertRaises(mda.DemoAudioRefused):
                self.store.start(cities, lang)
        with self.assertRaisesRegex(mda.DemoAudioRefused, "not_generated"):
            self.store.set_approved("athens", "uk", True)
        with self.assertRaises(mda.DemoAudioRefused):
            self.store.set_approved("../x", "uk", True)

    def test_approved_url_prefers_page_language(self):
        self.store.start(["rome"], "uk")
        self.store.start(["rome"], "en")
        self.assertIsNone(self.store.approved_url("rome", "en"))
        self.store.set_approved("rome", "uk", True)
        self.assertEqual(self.store.approved_url("rome", "en"), "/mycast/demo/rome.uk.mp3")
        self.store.set_approved("rome", "en", True)
        self.assertEqual(self.store.approved_url("rome", "en"), "/mycast/demo/rome.en.mp3")
        self.store.set_approved("rome", "en", False)
        self.assertEqual(self.store.approved_url("rome", "en"), "/mycast/demo/rome.uk.mp3")

    def test_background_run_finishes(self):
        store = self.make(background=True)
        job = store.start(["pompeii"], "uk")
        self.assertIn(job["state"], ("running", "done"))
        store._thread.join(5)
        self.assertEqual(store.status()["job"]["state"], "done")
        self.assertEqual(self.track("pompeii")["state"], "generated")


class RouteTest(Base):
    def setUp(self):
        super().setUp()
        self.app = FastAPI()
        mda.install_mycast_demo_audio_routes(self.app, self.store, is_owner=lambda r: getattr(r, "owner", False))
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in self.app.routes if hasattr(r, "methods")}

    def call(self, method, path, *args, **kw):
        r = self.h[(method, path)](*args, **kw)
        return asyncio.run(r) if asyncio.iscoroutine(r) else r

    def body(self, r):
        return r if isinstance(r, dict) else json.loads(r.body)

    def test_everything_is_owner_only_except_approved_public_audio(self):
        guest = Req({"cities": ["athens"], "language": "uk"}, owner=False)
        self.assertEqual(self.call("GET", "/factory/mycast-demos", guest).status_code, 403)
        self.assertEqual(self.call("GET", "/api/factory/mycast/demo-audio", guest).status_code, 403)
        self.assertEqual(self.call("POST", "/api/factory/mycast/demo-audio/generate", guest).status_code, 403)
        self.assertEqual(self.call("POST", "/api/factory/mycast/demo-audio/{city}/{lang}/approve", "athens", "uk",
                                   Req({"approved": True}, owner=False)).status_code, 403)
        self.assertEqual(self.call("GET", "/api/factory/mycast/demo-audio/{city}/{lang}.mp3", "athens", "uk", guest).status_code, 403)
        self.assertEqual(self.tts.calls, [])

    def test_owner_flow_generate_listen_approve_public(self):
        owner = Req({"cities": ["athens"], "language": "uk"})
        page = self.call("GET", "/factory/mycast-demos", owner)
        self.assertEqual(page.status_code, 200)
        self.assertIn("Сгенерировать демо", page.body.decode())
        self.assertEqual(self.call("GET", "/mycast/demo/{name}", "athens.uk.mp3").status_code, 404)
        job = self.body(self.call("POST", "/api/factory/mycast/demo-audio/generate", owner))
        self.assertEqual(job["results"][0]["result"], "generated")
        self.assertEqual(self.call("GET", "/mycast/demo/{name}", "athens.uk.mp3").status_code, 404)  # not approved yet
        prev = self.call("GET", "/api/factory/mycast/demo-audio/{city}/{lang}.mp3", "athens", "uk", owner)
        self.assertEqual((prev.status_code, prev.media_type), (200, "audio/mpeg"))
        r = self.call("POST", "/api/factory/mycast/demo-audio/{city}/{lang}/approve", "athens", "uk", Req({"approved": True}))
        self.assertEqual(self.body(r)["approved"], True)
        pub = self.call("GET", "/mycast/demo/{name}", "athens.uk.mp3")
        self.assertEqual((pub.status_code, pub.media_type), (200, "audio/mpeg"))
        for bad in ("athens.ru.mp3", "../state.json", "athens.uk.mp3/../../x", "state.json", "ATHENS.uk.mp3"):
            self.assertEqual(self.call("GET", "/mycast/demo/{name}", bad).status_code, 404, bad)
        status = self.body(self.call("GET", "/api/factory/mycast/demo-audio", owner))
        athens = next(c for c in status["cities"] if c["id"] == "athens")["tracks"]["uk"]
        self.assertEqual((athens["state"], athens["public_url"]), ("approved", "/mycast/demo/athens.uk.mp3"))
        self.assertEqual(status["used_today"], 1)

    def test_post_needs_json_and_reports_errors(self):
        r = self.call("POST", "/api/factory/mycast/demo-audio/generate", Req({"cities": ["athens"], "language": "uk"}, ctype="text/plain"))
        self.assertEqual(r.status_code, 415)
        r = self.call("POST", "/api/factory/mycast/demo-audio/generate", Req({"cities": "all", "language": "xx"}))
        self.assertEqual((r.status_code, self.body(r)["detail"]), (400, "bad_language"))
        r = self.call("POST", "/api/factory/mycast/demo-audio/{city}/{lang}/approve", "rome", "uk", Req({"approved": True}))
        self.assertEqual((r.status_code, self.body(r)["detail"]), (409, "not_generated"))
        self.tts.fail[1] = mycast.GeminiTTSError("rate_limited")
        job = self.body(self.call("POST", "/api/factory/mycast/demo-audio/generate", Req({"cities": ["rome"], "language": "uk"})))
        self.assertEqual((job["state"], job["message"]), ("stopped", "quota_exhausted"))

    def test_console_js_parses_and_escapes(self):
        page = mda.console_html()
        self.assertIn("noindex", page)
        self.assertIn(mda.QUOTA_MESSAGE["ru"], page)
        self.assertIn("function esc(", page)
        if not shutil.which("node"):
            self.skipTest("node not installed")
        js = re.search(r"<script>([\s\S]*)</script>", page).group(1)
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(js)
        out = subprocess.run(["node", "--check", f.name], capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)


class SharePageTest(Base):
    def test_page_plays_only_approved_tracks_and_escapes(self):
        rec = {"name": "Андрій", "code": ""}
        self.store.start(["athens", "rome"], "uk")
        body = sp.render(rec, "2026-11-13", {"title": "T", "seconds": 60}, token="tok", page="/mycast", lang="uk",
                         demos=sp.demo_cards("uk", server_audio=self.store.approved_url))
        self.assertEqual(body.count('class="play"'), 1)                     # generated is not enough
        self.store.set_approved("athens", "uk", True)
        cards = sp.demo_cards("uk", server_audio=self.store.approved_url)
        self.assertEqual([c["id"] for c in cards if c["audio"]], ["athens"])
        body = sp.render(rec, "2026-11-13", {"title": "T", "seconds": 60}, token="tok", page="/mycast", lang="uk", demos=cards)
        self.assertEqual(body.count('class="play"'), 2)
        self.assertIn('data-src="/mycast/demo/athens.uk.mp3"', body)
        en = sp.demo_cards("en", server_audio=self.store.approved_url)
        self.assertTrue(next(c for c in en if c["id"] == "athens")["meta"].endswith("· UK"))   # language is said

    def test_bad_server_urls_are_ignored(self):
        for url in ("https://evil.example/a.mp3", "/mycast/demo/../app.py", "javascript:alert(1)", '/mycast/demo/a".uk.mp3', 7):
            cards = sp.demo_cards("uk", server_audio=lambda c, l, u=url: u)
            self.assertTrue(all(c["audio"] is None for c in cards), url)
        cards = sp.demo_cards("uk", server_audio=lambda c, l: 1 / 0)           # a broken store never breaks the page
        self.assertTrue(all(c["audio"] is None for c in cards))

    def test_app_wires_the_store_into_the_page(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("set_demo_audio_source(MYCAST_DEMO_AUDIO.approved_url)", src)
        self.assertIn('"/mycast/demo/"', src)


if __name__ == "__main__":
    unittest.main()
