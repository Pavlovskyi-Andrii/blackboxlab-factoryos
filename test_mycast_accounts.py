"""MyCast listener accounts: Telegram widget signature, Google claims, signed cookie, minimal data, delete. Offline."""
import asyncio
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from mycast_accounts import (COOKIE, AccountError, ListenerStore, install_mycast_account_routes, sign, unsign,
                             verify_telegram)

BOT = "123456:TEST-token"
NOW = 1_800_000_000


def tg_login(**over):
    data = {"id": 777, "first_name": "Андрій", "username": "andrii", "auth_date": NOW - 60}
    data.update(over)
    check = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    data["hash"] = hmac.new(hashlib.sha256(BOT.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    return data


class TelegramTest(unittest.TestCase):
    def code(self, fn):
        with self.assertRaises(AccountError) as ctx:
            fn()
        return ctx.exception.code

    def test_valid_widget_login(self):
        who = verify_telegram(tg_login(), BOT, NOW)
        self.assertEqual(who, {"provider": "telegram", "pid": "777", "name": "Андрій", "chat_id": "777"})

    def test_forged_stale_or_unconfigured_login_is_refused(self):
        forged = tg_login(); forged["first_name"] = "Mallory"
        self.assertEqual(self.code(lambda: verify_telegram(forged, BOT, NOW)), "bad_telegram_login")
        self.assertEqual(self.code(lambda: verify_telegram(tg_login(), "other:token", NOW)), "bad_telegram_login")
        self.assertEqual(self.code(lambda: verify_telegram(tg_login(auth_date=NOW - 2 * 86400), BOT, NOW)), "stale_telegram_login")
        self.assertEqual(self.code(lambda: verify_telegram(tg_login(), "", NOW)), "telegram_not_configured")
        self.assertEqual(self.code(lambda: verify_telegram({"id": 1}, BOT, NOW)), "bad_telegram_login")


class StoreAndCookieTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "listeners.json"
        self.store = ListenerStore(self.path, clock=lambda: NOW)

    def tearDown(self):
        self.dir.cleanup()

    def test_same_person_same_account_minimal_data(self):
        a = self.store.login({"provider": "telegram", "pid": "777", "name": "A", "chat_id": "777"})
        b = self.store.login({"provider": "telegram", "pid": "777", "name": "A2", "chat_id": "777"})
        g = self.store.login({"provider": "google", "pid": "777", "name": "G"})
        self.assertEqual(a["slug"], b["slug"])
        self.assertNotEqual(a["slug"], g["slug"])                       # provider is part of the identity
        raw = self.path.read_text()
        self.assertNotIn('"pid"', raw)
        self.assertNotIn("email", raw)
        self.assertNotIn("google:777", raw)                             # provider ids are stored hashed
        self.assertNotIn("chat_id", json.dumps(json.loads(raw)["listeners"][g["slug"]]))

    def test_podcast_code_validation_and_delete(self):
        rec = self.store.login({"provider": "google", "pid": "1", "name": "G"})
        self.assertRaises(AccountError, self.store.save_code, rec["slug"], "<script>")
        self.store.save_code(rec["slug"], "eyJ2IjoxfQ")
        self.assertEqual(self.store.get(rec["slug"])["code"], "eyJ2IjoxfQ")
        self.assertTrue(self.store.delete(rec["slug"]))
        self.assertIsNone(self.store.get(rec["slug"]))
        again = self.store.login({"provider": "google", "pid": "1", "name": "G"})
        self.assertNotEqual(again["slug"], rec["slug"])                 # deleted means gone, a new login starts fresh

    def test_damaged_store_is_refused(self):
        self.path.write_text("{oops")
        self.assertRaises(AccountError, self.store.get, "abcdefgh")
        self.assertEqual(self.path.read_text(), "{oops")

    def test_cookie_signature_and_expiry(self):
        tok = sign("s3cret", "abcd2345", NOW)
        self.assertEqual(unsign("s3cret", tok, NOW), "abcd2345")
        self.assertIsNone(unsign("other", tok, NOW))
        self.assertIsNone(unsign("s3cret", tok.replace("abcd2345", "zzzz2345"), NOW))
        self.assertIsNone(unsign("s3cret", tok, NOW + 31 * 86400))
        self.assertIsNone(unsign("s3cret", "v2|owner||sig", NOW))       # a staff token is never a listener


class RoutesTest(unittest.TestCase):
    def test_flow(self):
        from fastapi import FastAPI
        with tempfile.TemporaryDirectory() as d:
            app = FastAPI()
            store = ListenerStore(Path(d) / "l.json", clock=lambda: NOW)
            install_mycast_account_routes(app, store, secret="s", bot_token=lambda: BOT, bot_username=lambda: "FactoryOSBot",
                                          google_client_id=lambda: "cid", clock=lambda: NOW,
                                          google_verify=lambda c: {"sub": "g-1", "given_name": "Olena"} if c == "good" else (_ for _ in ()).throw(ValueError()))
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

            class Req:
                def __init__(self, body=None, cookie=""):
                    self.body, self.cookies = body, {COOKIE: cookie} if cookie else {}
                async def json(self):
                    if self.body is None: raise ValueError
                    return self.body

            run = asyncio.run
            self.assertEqual(h[("GET", "/api/mycast/account/config")](), {"telegram_bot": "FactoryOSBot", "google_client_id": "cid"})
            r = run(h[("POST", "/api/mycast/account/telegram")](Req(tg_login())))
            listener = json.loads(r.body)["listener"]
            cookie = r.headers["set-cookie"].split(";")[0].split("=", 1)[1]
            self.assertIn("HttpOnly", r.headers["set-cookie"])
            self.assertTrue(listener["telegram_linked"])
            me = h[("GET", "/api/mycast/account/me")](Req(cookie=cookie))
            self.assertEqual(me["listener"]["slug"], listener["slug"])
            self.assertEqual(h[("GET", "/api/mycast/account/me")](Req()).status_code, 401)
            saved = run(h[("POST", "/api/mycast/account/podcast")](Req({"code": "eyJ2IjoxfQ"}, cookie)))
            self.assertTrue(saved["listener"]["has_podcast"])
            page = h[("GET", "/mycast/u/{slug}")](listener["slug"])
            self.assertEqual(page.headers["location"], f"/static/mycast-configurator/index.html#p=eyJ2IjoxfQ&from={listener['slug']}")
            self.assertTrue(h[("GET", "/mycast/u/{slug}")]("../etc").headers["location"].endswith("#missing"))
            g = run(h[("POST", "/api/mycast/account/google")](Req({"credential": "good"})))
            self.assertEqual(json.loads(g.body)["listener"]["name"], "Olena")
            self.assertEqual(run(h[("POST", "/api/mycast/account/google")](Req({"credential": "bad"}))).status_code, 401)
            gone = h[("DELETE", "/api/mycast/account")](Req(cookie=cookie))
            self.assertEqual(json.loads(gone.body), {"deleted": True})
            self.assertEqual(h[("GET", "/api/mycast/account/me")](Req(cookie=cookie)).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
