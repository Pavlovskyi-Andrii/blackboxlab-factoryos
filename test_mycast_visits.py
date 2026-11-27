"""T-743 (#452 B-01): first-party MyCast visit counter. Offline: no network, temp files only."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

import mycast_visits
from mycast_visits import RETENTION_DAYS, VisitLog, channel_for, clean_acq, install_mycast_visit_routes

ROOT = Path(__file__).resolve().parent
NOW = 1_800_000_000          # 2027-01-15 UTC
DAY = 86400
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148"
IP = "203.0.113.7"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class LogTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.clock = Clock(NOW)
        self.log = VisitLog(Path(self.dir.name) / "mycast_visits.jsonl", clock=self.clock)

    def tearDown(self):
        self.dir.cleanup()

    def rec(self, **kw):
        args = {"page": "landing", "ip": IP, "ua": UA}
        args.update(kw)
        return self.log.record(**args)

    def test_counts_variant_channel_and_daily_visitors(self):
        self.assertEqual(self.rec(variant="b", channel="tg"), "recorded")
        self.assertEqual(self.rec(variant="b", channel="tg"), "recorded")          # same person, same day
        self.assertEqual(self.rec(variant="a", ip="198.51.100.2"), "recorded")      # no ?ch and no referrer → direct
        self.assertEqual(self.rec(page="profile", referrer_host="www.linkedin.com", ip="198.51.100.3"), "recorded")
        rep = self.log.report(7)
        self.assertEqual(rep["visits"]["total"], 4)
        self.assertEqual(rep["visits"]["daily_visitors"], 3)
        self.assertEqual(rep["visits"]["by_variant"], {"b": 2, "a": 1, "none": 1})
        self.assertEqual(rep["visits"]["by_channel"], {"tg": 2, "direct": 1, "li": 1})
        self.assertEqual(rep["visits"]["by_page"], {"landing": 3, "profile": 1})

    def test_nothing_personal_is_written(self):
        self.rec(referrer_host="t.me")
        text = "".join(p.read_text() for p in Path(self.dir.name).iterdir())
        for secret in (IP, "iPhone", "t.me"):
            self.assertNotIn(secret, text)
        row = json.loads(self.log.path.read_text().splitlines()[0])
        self.assertEqual(set(row), {"ts", "day", "page", "variant", "channel", "visitor", "synthetic"})
        self.assertRegex(row["visitor"], r"^[0-9a-f]{16}$")

    def test_daily_salt_rotates_and_yesterday_is_deleted(self):
        today = self.log.visitor(IP, UA, "2027-01-15")
        self.assertEqual(today, self.log.visitor(IP, UA, "2027-01-15"))
        tomorrow = self.log.visitor(IP, UA, "2027-01-16")
        self.assertNotEqual(today, tomorrow)
        salts = json.loads(self.log.salt_path.read_text())
        self.assertEqual(list(salts), ["2027-01-16"])                               # cannot re-link yesterday

    def test_bots_synthetic_invalid_and_rate_limit(self):
        self.assertEqual(self.rec(ua="TelegramBot (like TwitterBot)"), "bot")
        self.assertEqual(self.rec(ua=""), "bot")
        self.assertEqual(self.rec(page="admin"), "invalid")
        self.assertEqual(self.rec(synthetic=True, ip="192.0.2.9"), "recorded")
        for _ in range(mycast_visits.MAX_PER_VISITOR_HOUR):
            self.rec()
        self.assertEqual(self.rec(), "limited")
        rep = self.log.report(1)
        self.assertEqual(rep["visits"]["total"], mycast_visits.MAX_PER_VISITOR_HOUR)
        self.assertEqual(rep["synthetic_excluded"], 1)

    def test_bad_tokens_are_dropped_not_stored(self):
        self.rec(variant="<script>", channel="DROP TABLE")
        row = json.loads(self.log.path.read_text().splitlines()[0])
        self.assertEqual((row["variant"], row["channel"]), ("", "direct"))

    def test_old_rows_fold_into_daily_totals(self):
        self.clock.t = NOW - (RETENTION_DAYS + 5) * DAY
        self.rec(variant="a", channel="tg")
        self.clock.t = NOW
        self.log._compacted = ""
        self.rec(variant="b")
        rows = self.log.path.read_text().splitlines()
        self.assertEqual(len(rows), 1)                                              # the old row and its hash are gone
        daily = json.loads(self.log.daily_path.read_text())
        self.assertEqual(sum(sum(v.values()) for v in daily.values()), 1)
        self.assertNotIn("visitor", self.log.daily_path.read_text())

    def test_registrations_by_variant_and_channel(self):
        regs = [{"created": NOW - 100, "acq": {"variant": "b", "channel": "tg"}},
                {"created": NOW - 200, "acq": None},
                {"created": NOW - 40 * DAY, "acq": {"variant": "a", "channel": "tg"}}]   # outside a 30-day window
        rep = self.log.report(30, registrations=regs)
        self.assertEqual(rep["registrations"], {"total": 2, "by_variant": {"b": 1, "unknown": 1},
                                                "by_channel": {"tg": 1, "unknown": 1}})

    def test_helpers(self):
        self.assertEqual(channel_for("TG", "www.google.com"), "tg")
        self.assertEqual(channel_for("", "www.google.com"), "search")
        self.assertEqual(channel_for("", "example.org"), "other")
        self.assertEqual(channel_for("", "bad host!"), "direct")
        self.assertIsNone(clean_acq({"variant": "<x>", "channel": ""}))
        self.assertEqual(clean_acq({"variant": "B", "channel": "tg", "extra": 1}), {"variant": "b", "channel": "tg"})


class RoutesTest(unittest.TestCase):
    def setUp(self):
        from fastapi import FastAPI
        self.dir = tempfile.TemporaryDirectory()
        self.app = FastAPI()
        self.on = False
        self.log = VisitLog(Path(self.dir.name) / "v.jsonl", clock=lambda: NOW)
        self.role = "viewer"
        install_mycast_visit_routes(self.app, self.log, identity=lambda r: {"role": self.role},
                                    registrations=lambda: [{"created": NOW - 5, "acq": {"variant": "b", "channel": "tg"}}],
                                    is_enabled=lambda: self.on)
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in self.app.routes if hasattr(r, "methods")}

    def tearDown(self):
        self.dir.cleanup()

    def post(self, raw, ua=UA):
        class Req:
            headers = {"user-agent": ua, "x-forwarded-for": IP + ", 10.0.0.1"}
            client = None
            async def body(self):
                return raw
        return asyncio.run(self.h[("POST", "/api/mycast/v")](Req()))

    def test_flag_off_is_404_and_records_nothing(self):
        self.assertEqual(self.post(b'{"p":"landing"}').status_code, 404)
        self.assertFalse(self.log.path.exists())

    def test_beacon_and_owner_report(self):
        self.on = True
        self.assertEqual(self.post(b'{"p":"landing","v":"b","ch":"tg","r":"t.me"}').status_code, 204)
        self.assertEqual(self.post(b'{"p":"landing"}', ua="curl/8").status_code, 204)       # a bot looks the same
        self.assertEqual(self.post(b"not json").status_code, 400)
        self.assertEqual(self.post(b'{"p":"nope"}').status_code, 400)
        self.assertEqual(self.post(b"{" + b" " * 600 + b"}").status_code, 413)
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            self.h[("GET", "/api/factory/mycast/visits")](None)
        self.assertEqual(ctx.exception.status_code, 403)
        self.role = "owner"
        rep = self.h[("GET", "/api/factory/mycast/visits")](None, days=30)
        self.assertTrue(rep["enabled"])
        self.assertEqual(rep["visits"]["total"], 1)
        self.assertEqual(rep["registrations"]["by_variant"], {"b": 1})


class WiringTest(unittest.TestCase):
    def test_signup_keeps_arrival_only_for_new_accounts(self):
        from mycast_accounts import ListenerStore
        with tempfile.TemporaryDirectory() as d:
            store = ListenerStore(Path(d) / "l.json", clock=lambda: NOW)
            who = {"provider": "telegram", "pid": "1", "name": "A", "chat_id": "1"}
            rec = store.login(who, "", {"variant": "b", "channel": "tg"})
            self.assertEqual(rec["acq"], {"variant": "b", "channel": "tg"})
            again = store.login(who, "", {"variant": "a", "channel": "li"})            # a returning listener
            self.assertEqual(again["acq"], {"variant": "b", "channel": "tg"})
            plain = store.login({"provider": "google", "pid": "2", "name": "B"}, "", {"variant": "<x>"})
            self.assertNotIn("acq", plain)
            self.assertEqual(sorted(r["acq"]["variant"] if r["acq"] else "" for r in store.acquisition()), ["", "b"])

    def test_telegram_route_does_not_sign_the_arrival_fields(self):
        src = (ROOT / "mycast_accounts.py").read_text(encoding="utf-8")
        tg = src[src.index('@app.post("/api/mycast/account/telegram")'):src.index('@app.post("/api/mycast/account/google")')]
        self.assertLess(tg.index('body.pop("acq"'), tg.index("verify_telegram(body"))

    def test_pages_carry_the_beacon_and_it_stays_private(self):
        js = (ROOT / "static/mycast-configurator/v.js").read_text(encoding="utf-8")
        for banned in ("document.cookie", "localStorage", "sessionStorage", "indexedDB", "http://", "https://"):
            self.assertNotIn(banned, js)
        self.assertIn("globalPrivacyControl", js)
        self.assertIn("doNotTrack", js)
        page = (ROOT / "static/mycast-configurator/index.html").read_text(encoding="utf-8")
        self.assertIn('<script src="v.js" data-page="landing" defer></script>', page)
        self.assertIn("return acq ? { ...b, acq } : b;", page)
        self.assertIn('data-page="profile"', (ROOT / "mycast_public.py").read_text(encoding="utf-8"))
        self.assertIn('data-page="episode"', (ROOT / "mycast_share_page.py").read_text(encoding="utf-8"))

    def test_app_wiring_flag_off_by_default(self):
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mycast_visit_routes(app, VisitLog(DATA_DIR / \"mycast_visits.jsonl\")", app_src)
        self.assertIn('"/api/mycast/v"}', app_src)                                    # exact public path, not a prefix
        import os
        old = os.environ.pop("FACTORY_MYCAST_VISITS_ENABLED", None)
        try:
            self.assertFalse(mycast_visits.enabled())
        finally:
            if old is not None:
                os.environ["FACTORY_MYCAST_VISITS_ENABLED"] = old


if __name__ == "__main__":
    unittest.main()
