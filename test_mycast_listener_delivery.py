"""#317: website listeners' daily MyCast. Gates, schedule, idempotency, routes, worker. Offline: fake TTS/Telegram/CLI."""
import asyncio
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-listeners-"))

import mycast_listener_delivery as mld  # noqa: E402
from mycast_accounts import ListenerStore, public_view  # noqa: E402

# Made by configurator.js encodeShare: boxing (Ukraine) + startup funding, daily 07:30 Kyiv, 5 min, two hosts.
CODE = ("eyJ2IjoxLCJuIjo5MywidCI6W1swLCJ1Il0sWzQwLCJ3Il1dLCJjIjp7fSwiZiI6W10sInMiOlsiRXVyb3BlL0t5aXYiLCIwNzozMCIsImRh"
        "aWx5IixbXSw1XSwibyI6WyJ0d29faG9zdHMiLCJ1ayIsWyJDaGFyb24iLCJLb3JlIl1dLCJkIjoidGVsZWdyYW0iLCJ4IjoiIiwiayI6WzAsMF19")
KYIV = ZoneInfo("Europe/Kyiv")


def at(day, hhmm):
    return datetime.fromisoformat(f"{day}T{hhmm}:00").replace(tzinfo=KYIV).timestamp()


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def ready_listener(store, chat="777"):
    rec = store.login({"provider": "telegram", "pid": chat, "name": "Андрій Тест", "chat_id": chat})
    store.save_code(rec["slug"], CODE, approved=True)
    store.set_delivery(rec["slug"], True, True)
    return rec["slug"]


class ProfileTest(unittest.TestCase):
    def test_topics_json_matches_configurator(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        out = subprocess.run(["node", "-e", "const C=require('./static/mycast-configurator/configurator.js');"
                              "console.log(JSON.stringify(C.TOPIC_IDS))"], capture_output=True, text=True, check=True)
        self.assertEqual([t[0] for t in mld.TOPICS], json.loads(out.stdout))

    def test_decode_real_share_code(self):
        p = mld.decode_profile(CODE)
        self.assertEqual(p["topics"], ["Професійний бокс (Україна)", mld.TOPICS[40][1] + " (world)"])
        self.assertEqual((p["timezone"], p["time"], p["frequency"], p["duration_min"]), ("Europe/Kyiv", "07:30", "daily", 5))
        self.assertEqual((p["language"], p["mode"], p["voices"]), ("uk", "two_hosts", ["Charon", "Kore"]))
        import base64 as b64
        raw = json.loads(b64.urlsafe_b64decode(CODE + "=="))
        raw["s"][4] = 25                                          # any whole minute up to 30 (owner 2026-11-13)
        self.assertEqual(mld.decode_profile(b64.urlsafe_b64encode(json.dumps(raw).encode()).decode().rstrip("="))["duration_min"], 25)
        for bad in ("", "not-base64!!", "eyJ2Ijo5fQ"):
            with self.assertRaises(ValueError):
                mld.decode_profile(bad)


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock(at("2026-11-13", "08:00"))
        self.store = ListenerStore(pathlib.Path(self.tmp.name) / "l.json", clock=self.clock)
        self.d = mld.ListenerDelivery(self.store, clock=self.clock, daily_cap=2)

    def tearDown(self):
        self.tmp.cleanup()

    def state(self, slug):
        return mld.delivery_gate(self.store.get(slug), self.clock())["state"]

    def test_each_gate_blocks_until_the_listener_opts_in(self):
        rec = self.store.login({"provider": "google", "pid": "g1", "name": "A"})
        s = rec["slug"]
        self.assertEqual(self.state(s), "no_podcast")
        self.store.save_code(s, CODE)
        self.assertEqual(self.state(s), "telegram_not_linked")
        self.store.link_telegram(s, "555")
        self.assertEqual(self.state(s), "not_approved")
        self.store.save_code(s, CODE, approved=True)
        self.assertEqual(self.state(s), "delivery_off")
        self.assertEqual(self.d.due(), [])                                 # nothing unsolicited
        self.store.set_delivery(s, True, True)
        self.assertEqual(self.state(s), "due")
        item = self.d.due()[0]
        self.assertNotIn("chat_id", json.dumps(item))
        self.assertEqual((item["slug"], item["local_date"]), (s, "2026-11-13"))

    def test_schedule_time_and_days(self):
        s = ready_listener(self.store)
        self.clock.t = at("2026-11-13", "07:29")
        self.assertEqual(self.state(s), "waiting")
        with patch("mycast_accounts.time.time", self.clock):
            self.assertIn("07:30", public_view(self.store.get(s))["status"]["detail"])
        self.clock.t = at("2026-11-13", "07:30")
        self.assertEqual(self.state(s), "due")
        p = mld.decode_profile(CODE)
        p.update(frequency="weekdays")
        self.assertFalse(mld.scheduled_on(p, datetime(2026, 11, 14, 9, tzinfo=KYIV)))   # Saturday
        p.update(frequency="days", days=["sat"])
        self.assertTrue(mld.scheduled_on(p, datetime(2026, 11, 14, 9, tzinfo=KYIV)))

    def test_referral_credited_only_after_friends_first_real_episode(self):
        """#305 E2E: invite link -> friend signs up -> nothing for the inviter -> failed send still nothing ->
        first sent episode credits +7 once -> later episodes never credit again."""
        inviter = ready_listener(self.store, chat="900")
        friend = self.store.login({"provider": "telegram", "pid": "901", "name": "F", "chat_id": "901"}, ref=inviter)["slug"]
        self.store.save_code(friend, CODE, approved=True)
        self.store.set_delivery(friend, True, True)
        view = lambda: public_view(self.store.get(inviter))
        self.assertEqual((view()["free_days"], view()["referrals_pending"]), (7, 1))
        self.assertEqual(public_view(self.store.get(friend))["free_days"], 14)     # the friend's gift is immediate
        self.d.claim(friend, "2026-11-13")
        self.d.finish(friend, "2026-11-13", False, "TelegramError")
        self.assertEqual(view()["referrals"], 0)                                   # a failed send is not an episode
        self.d.claim(friend, "2026-11-13")
        self.d.finish(friend, "2026-11-13", True, seconds=290)
        self.assertEqual((view()["free_days"], view()["referrals"], view()["referrals_pending"]), (14, 1, 0))
        self.assertIn("friend_first_episode", [e["action"] for e in view()["audit"]])
        self.clock.t = at("2026-11-14", "07:31")
        self.d.claim(friend, "2026-11-14")
        self.d.finish(friend, "2026-11-14", True, seconds=290)
        self.assertEqual(view()["referrals"], 1)                                   # credited once, never again
        self.d.claim(inviter, "2026-11-14")
        self.d.finish(inviter, "2026-11-14", True)                                 # no inviter of its own: no-op
        self.assertEqual(view()["referrals"], 1)

    def test_claim_once_failures_cap_and_stop(self):
        s = ready_listener(self.store)
        c = self.d.claim(s, "2026-11-13")
        self.assertEqual((c["duplicate"], c["chat_id"]), (False, "777"))
        self.assertEqual(self.state(s), "in_progress")
        self.d.finish(s, "2026-11-13", True, seconds=290)
        self.assertEqual(self.state(s), "delivered")
        self.assertTrue(self.d.claim(s, "2026-11-13")["duplicate"])
        self.assertEqual(public_view(self.store.get(s))["status"]["last"]["status"], "sent")
        s2 = ready_listener(self.store, chat="778")
        for _ in range(mld.MAX_FAILED_PER_DAY):
            self.d.claim(s2, "2026-11-13")
            self.d.finish(s2, "2026-11-13", False, "TelegramError")
        self.assertEqual(self.state(s2), "failed_today")
        with self.assertRaises(mld.HTTPException) as e:
            self.d.claim(s2, "2026-11-12")
        self.assertEqual(e.exception.status_code, 409)                      # only today's local date
        s3 = ready_listener(self.store, chat="779")
        self.d.claim(s3, "2026-11-13")
        self.d.finish(s3, "2026-11-13", True)
        s4 = ready_listener(self.store, chat="780")
        with self.assertRaises(mld.HTTPException) as e:                      # daily cap of 2 sent episodes
            self.d.claim(s4, "2026-11-13")
        self.assertEqual(e.exception.status_code, 429)
        self.store.set_delivery(s4, False, False)
        self.assertEqual(self.state(s4), "delivery_off")
        self.store.save_code(s3, CODE.replace("Mi", "Mj"))                   # an edit pauses delivery
        self.assertNotEqual(self.state(s3), "due")

    def test_owner_overview_counts_states_without_private_fields(self):
        s = ready_listener(self.store)
        self.d.claim(s, "2026-11-13")
        self.d.finish(s, "2026-11-13", True, seconds=290, file_id="tg-file-1")
        s2 = ready_listener(self.store, chat="778")
        self.store.login({"provider": "google", "pid": "g9", "name": "Olena K", "email": "olena@example.com"})
        view = self.d.overview()
        self.assertEqual((view["total"], view["sent_today_utc"], view["daily_cap"]), (3, 1, 2))
        self.assertEqual(view["by_state"], {"delivered": 1, "due": 1, "no_podcast": 1})
        row = next(r for r in view["listeners"] if r["slug"] == s)
        self.assertEqual((row["first_name"], row["last_date"], row["last_status"], row["sent_days"]),
                         ("Андрій", "2026-11-13", "sent", 1))
        self.assertEqual(view["listeners"][0]["slug"], s2)                     # due first
        text = json.dumps(view, ensure_ascii=False)
        for private in ("777", "778", "olena@example.com", "tg-file-1", CODE[:20], "Тест"):
            self.assertNotIn(private, text)

        class Req:
            pass
        app2 = __import__("fastapi").FastAPI()
        role = {"role": "member"}
        mld.install_listener_delivery_routes(app2, self.d, authorize_worker=lambda r: False, api_key=lambda: "",
                                             tts=None, encode=None, send_audio=None, identity=lambda r: role)
        handler = next(r.endpoint for r in app2.routes if getattr(r, "path", "") == "/api/factory/mycast/listeners")
        with self.assertRaises(mld.HTTPException) as e:
            handler(Req())
        self.assertEqual(e.exception.status_code, 403)
        role["role"] = "owner"
        self.assertEqual(handler(Req())["total"], 3)
        page = handler(Req(), offset=0, limit=2)                               # Codex review on #336: paging
        self.assertEqual((len(page["listeners"]), page["next_offset"]), (2, 2))
        rest = handler(Req(), offset=2, limit=2)
        self.assertEqual((len(rest["listeners"]), rest["next_offset"]), (1, None))
        self.assertEqual({r["slug"] for r in page["listeners"] + rest["listeners"]}, {r["slug"] for r in view["listeners"]})


import app as factory  # noqa: E402
from test_worker_token_binding import asgi_post  # noqa: E402

WORKER = "worker-token-for-listener-tests"


def asgi_get(path, bearer, app=None, query=b""):
    headers = [(b"host", b"testserver"), (b"authorization", ("Bearer " + bearer).encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": query, "headers": headers,
             "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(m):
        sent.append(m)
    asyncio.run((app or factory.app)(scope, receive, send))
    return next(m for m in sent if m["type"] == "http.response.start")["status"], b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock(at("2026-11-13", "08:00"))
        self.store = ListenerStore(pathlib.Path(self.tmp.name) / "l.json", clock=self.clock)
        self.sent, self.tts_calls = [], []
        self.patches = [patch.object(factory.MYCAST_LISTENER_DELIVERY, "store", self.store),
                        patch.object(factory.MYCAST_LISTENER_DELIVERY, "clock", self.clock),
                        patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", WORKER),
                        patch.object(factory, "FACTORY_GEMINI_API_KEY", "gemini-test-key"),
                        patch.object(factory, "FACTORY_TELEGRAM_BOT_TOKEN", "1:bot"),
                        patch.object(mld.time, "time", self.clock)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def episode(self):
        return {"title": "MyCast · 2026-11-13", "lines": [["A", "Привіт, сьогодні бокс і стартапи."], ["B", "Почнімо."]] * 3}

    def deliver(self, slug, body=None):
        body = body or {"episode": self.episode(), "local_date": "2026-11-13"}
        return asgi_post(f"/api/factory/mycast/worker/listeners/{slug}/deliver", bearer=WORKER, body=json.dumps(body).encode())

    def test_due_then_one_delivery_to_the_listeners_own_chat(self):
        s = ready_listener(self.store)
        other = self.store.login({"provider": "telegram", "pid": "999", "name": "B", "chat_id": "999"})["slug"]
        status, body = asgi_get("/api/factory/mycast/worker/listeners/due", WORKER)
        due = json.loads(body)["listeners"]
        self.assertEqual((status, [d["slug"] for d in due]), (200, [s]))
        self.assertNotIn("777", body.decode())
        self.assertEqual(asgi_get("/api/factory/mycast/worker/listeners/due", "wrong")[0], 401)

        def tts(key, ep, voices, **kw):
            self.tts_calls.append((ep["language"], voices))
            return b"\x01\x00" * 24000 * 3, 24000
        with patch.object(factory, "gemini_tts_pcm", tts), \
             patch("mycast_listener_delivery.asyncio.to_thread", side_effect=lambda f: asyncio.sleep(0, f())), \
             patch.object(factory.MYCAST_LISTENER_DELIVERY, "daily_cap", 10):
            routes = [r for r in factory.app.routes if getattr(r, "path", "") == "/api/factory/mycast/worker/listeners/{slug}/deliver"]
            self.assertEqual(len(routes), 1)
        # Exercise the handler with fakes injected at install time.
        app2 = __import__("fastapi").FastAPI()
        mld.install_listener_delivery_routes(
            app2, factory.MYCAST_LISTENER_DELIVERY, authorize_worker=lambda r: True, api_key=lambda: "k",
            tts=tts, encode=lambda pcm, rate: b"mp3", send_audio=lambda *a: self.sent.append(a))
        handler = next(r.endpoint for r in app2.routes if getattr(r, "path", "").endswith("/deliver"))

        class Req:
            def __init__(self, body):
                self.body = body

            async def json(self):
                return self.body
        payload = {"episode": self.episode(), "local_date": "2026-11-13"}
        out = asyncio.run(handler(s, Req(payload)))
        self.assertEqual((out["sent"], self.sent[0][0], self.tts_calls[0]), (True, "777", ("uk", ("Charon", "Kore"))))
        self.assertTrue(asyncio.run(handler(s, Req(payload)))["duplicate"])
        self.assertEqual(len(self.sent), 1)
        with self.assertRaises(mld.HTTPException) as e:
            asyncio.run(handler(other, Req(payload)))                    # never opted in
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(public_view(self.store.get(s))["status"]["state"], "delivered")

    def test_send_failure_is_recorded_not_claimed_as_sent(self):
        s = ready_listener(self.store)
        app2 = __import__("fastapi").FastAPI()

        def boom(*a):
            raise RuntimeError("Forbidden: bot was blocked by the user")
        mld.install_listener_delivery_routes(
            app2, factory.MYCAST_LISTENER_DELIVERY, authorize_worker=lambda r: True, api_key=lambda: "k",
            tts=lambda key, ep, voices: (b"\x01\x00" * 100, 24000), encode=lambda pcm, rate: b"mp3", send_audio=boom)
        handler = next(r.endpoint for r in app2.routes if getattr(r, "path", "").endswith("/deliver"))

        class Req:
            async def json(self):
                return {"episode": {"lines": [["A", "x"]] * 4}, "local_date": "2026-11-13"}
        with self.assertRaises(mld.HTTPException):
            asyncio.run(handler(s, Req()))
        last = public_view(self.store.get(s))["status"]["last"]
        self.assertEqual((last["status"], last["reason"]), ("failed", "RuntimeError:"))
        self.assertEqual(self.store.get(s)["audit"][-1]["action"], "episode_failed")

    def test_listener_overview_pages_over_http(self):
        # Codex review on #337: > 200 listeners, query parsing, clamping and out-of-range offsets through HTTP.
        d = mld.ListenerDelivery(self.store, clock=self.clock)
        with self.store._lock:
            data = self.store._load()
            for i in range(205):
                data["listeners"][f"l{i:03d}"] = {"slug": f"l{i:03d}", "name": f"N{i}"}
            self.store._save(data)
        app2 = __import__("fastapi").FastAPI()
        mld.install_listener_delivery_routes(app2, d, authorize_worker=lambda r: False, api_key=lambda: "", tts=None,
                                             encode=None, send_audio=None, identity=lambda r: {"role": "owner"})
        get = lambda q: json.loads(asgi_get("/api/factory/mycast/listeners", "x", app=app2, query=q)[1])
        first = get(b"")
        self.assertEqual((first["total"], len(first["listeners"]), first["next_offset"]), (205, 200, 200))
        second = get(b"offset=200")
        self.assertEqual((len(second["listeners"]), second["next_offset"]), (5, None))
        self.assertEqual(len({r["slug"] for r in first["listeners"] + second["listeners"]}), 205)
        self.assertEqual(len(get(b"limit=5000")["listeners"]), 200)              # clamped
        self.assertEqual(get(b"limit=0")["limit"], 1)
        self.assertEqual(get(b"offset=-3")["offset"], 0)
        past = get(b"offset=999")
        self.assertEqual((past["listeners"], past["next_offset"]), ([], None))
        self.assertEqual(asgi_get("/api/factory/mycast/listeners", "x", app=app2, query=b"offset=abc")[0], 422)

    def test_bad_requests(self):
        s = ready_listener(self.store)
        self.assertEqual(self.deliver(s, {"episode": {"lines": []}, "local_date": "2026-11-13"})[0], 400)
        self.assertEqual(self.deliver("../etc")[0], 404)
        self.assertEqual(asgi_post(f"/api/factory/mycast/worker/listeners/{s}/deliver", bearer="nope",
                                   body=b"{}")[0], 401)


class HistoryTest(unittest.TestCase):
    """#317 history: only Telegram's file id is kept; the listener plays back only their own episodes."""

    def test_file_id_kept_and_only_the_owner_can_play_it(self):
        from fastapi import FastAPI
        from mycast_accounts import COOKIE, install_mycast_account_routes, sign
        with tempfile.TemporaryDirectory() as d:
            clock = Clock(at("2026-11-13", "08:00"))
            store = ListenerStore(pathlib.Path(d) / "l.json", clock=clock)
            s = ready_listener(store)
            other = ready_listener(store, chat="778")
            delivery = mld.ListenerDelivery(store, clock=clock)
            app = FastAPI()
            mld.install_listener_delivery_routes(
                app, delivery, authorize_worker=lambda r: True, api_key=lambda: "k",
                tts=lambda key, ep, voices: (b"\x01\x00" * 2400, 24000), encode=lambda pcm, rate: b"ID3mp3",
                send_audio=lambda chat, audio, fn, title, cap: "FILE-ID-" + chat)
            deliver = next(r.endpoint for r in app.routes if getattr(r, "path", "").endswith("/deliver"))

            class Req:
                def __init__(self, body=None, cookie=""):
                    self.body, self.cookies = body, {COOKIE: cookie} if cookie else {}

                async def json(self):
                    return self.body
            asyncio.run(deliver(s, Req({"episode": {"title": "MyCast · 13 листопада", "lines": [["A", "x"]] * 4},
                                        "local_date": "2026-11-13"})))
            entry = store.get(s)["deliveries"]["2026-11-13"]
            self.assertEqual((entry["file_id"], entry["title"]), ("FILE-ID-777", "MyCast · 13 листопада"))
            self.assertEqual(set(entry), {"status", "at", "utc_day", "seconds", "file_id", "title"})   # no audio bytes stored
            fetched = []
            acc = FastAPI()
            install_mycast_account_routes(acc, store, secret="s", bot_token=lambda: "1:x", bot_username=lambda: "b",
                                          google_client_id=lambda: "", google_verify=lambda c: {}, clock=clock,
                                          fetch_audio=lambda fid: fetched.append(fid) or b"ID3-from-telegram")
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in acc.routes if hasattr(r, "methods")}
            mine, theirs = sign("s", s, clock()), sign("s", other, clock())
            eps = h[("GET", "/api/mycast/account/episodes")](Req(cookie=mine))["episodes"]
            self.assertEqual(eps, [{"date": "2026-11-13", "title": "MyCast · 13 листопада", "seconds": 0, "audio": True}])
            audio = h[("GET", "/api/mycast/account/episodes/{day}/audio")]("2026-11-13", Req(cookie=mine))
            self.assertEqual((audio.body, audio.media_type, fetched), (b"ID3-from-telegram", "audio/mpeg", ["FILE-ID-777"]))
            self.assertEqual(h[("GET", "/api/mycast/account/episodes")](Req(cookie=theirs))["episodes"], [])
            self.assertEqual(h[("GET", "/api/mycast/account/episodes/{day}/audio")]("2026-11-13", Req(cookie=theirs)).status_code, 404)
            self.assertEqual(h[("GET", "/api/mycast/account/episodes/{day}/audio")]("../x", Req(cookie=mine)).status_code, 404)
            self.assertEqual(h[("GET", "/api/mycast/account/episodes")](Req()).status_code, 401)


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name) / "s.json"
        self.item = {"slug": "abcd2345", "first_name": "Андрій", "local_date": "2026-11-13", "profile": mld.decode_profile(CODE)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_prompt_and_round(self):
        from autopilot import mycast_listeners as ml
        prompt = ml.build_prompt(self.item)
        self.assertIn("Професійний бокс (Україна)", prompt)
        self.assertIn("українською", prompt)
        self.assertIn("700 words", prompt)
        script = {"title": "t", "sources": [{"title": "s", "url": "https://x", "date": "2026-11-13"}],
                  "lines": [["A", " ".join(["слово"] * 60)], ["B", " ".join(["слово"] * 60)]] * 3}
        cli_out = json.dumps({"result": json.dumps(script, ensure_ascii=False)})
        calls, posts = [], []

        class Resp:
            def __init__(self, code, body):
                self.status_code, self.body = code, body

            def json(self):
                return self.body

        class Http:
            def get(self, url, headers, timeout):
                return Resp(200, {"listeners": [self_item]})

            def post(self, url, headers, json, timeout):
                posts.append((url, json))
                return Resp(200, {"sent": True})
        self_item = self.item
        run_cli = lambda cmd, **kw: calls.append(cmd) or type("R", (), {"stdout": cli_out, "stderr": ""})()
        with patch.object(ml.relay_tasks, "configured", return_value=True), \
             patch.object(ml.relay_tasks, "endpoint", return_value=("https://f", "tok")):
            self.assertEqual(ml.run_listeners(self.state, now=100000, run_cli=run_cli, http=Http()), "delivered")
            self.assertTrue(posts[0][0].endswith("/listeners/abcd2345/deliver"))
            self.assertEqual(posts[0][1]["local_date"], "2026-11-13")
            self.assertEqual(ml.run_listeners(self.state, now=100100, run_cli=run_cli, http=Http()), "idle")  # spacing
            self.assertIn("WebSearch", calls[0])
            self.assertIn("Bash", calls[0][calls[0].index("--disallowedTools"):])


if __name__ == "__main__":
    unittest.main(verbosity=2)
