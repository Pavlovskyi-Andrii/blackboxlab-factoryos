"""MyCast listener accounts: Telegram widget signature, Google claims, signed cookie, minimal data, delete. Offline."""
import asyncio
import hashlib
import hmac
import json
import tempfile
import unittest
from pathlib import Path

from mycast_accounts import (COOKIE, AccountError, ListenerStore, install_mycast_account_routes, public_view, sign, unsign,
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

    def test_invite_gives_seven_days_each_side_once(self):
        a = self.store.login({"provider": "google", "pid": "1", "name": "A"})
        self.assertEqual(public_view(a)["free_days"], 7)
        f = self.store.login({"provider": "google", "pid": "2", "name": "F"}, ref=a["slug"])
        self.assertEqual((public_view(f)["free_days"], public_view(f)["gifted"]), (14, True))   # 7 + 7 gift
        self.store.login({"provider": "google", "pid": "2", "name": "F"}, ref=a["slug"])         # same friend again: no double count
        self.store.login({"provider": "google", "pid": "1", "name": "A"}, ref=a["slug"])         # cannot invite yourself
        self.store.login({"provider": "telegram", "pid": "3", "name": "G", "chat_id": "3"}, ref="../etc")
        self.assertEqual(public_view(self.store.get(a["slug"]))["free_days"], 14)                 # 7 + 7 for one friend
        self.assertEqual(public_view(self.store.get(a["slug"]))["referrals"], 1)

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


class DeliveryTest(unittest.TestCase):
    """#281: approval, pairing and delivery are separate steps; nothing is sent on approval, sign-in or import."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = ListenerStore(Path(self.dir.name) / "l.json", clock=lambda: NOW)
        self.tg = self.store.login({"provider": "telegram", "pid": "777", "name": "A", "chat_id": "777"})
        self.gg = self.store.login({"provider": "google", "pid": "9", "name": "G"})

    def tearDown(self):
        self.dir.cleanup()

    def code(self, fn):
        with self.assertRaises(AccountError) as ctx:
            fn()
        return ctx.exception.code

    def test_each_step_is_separate(self):
        slug = self.tg["slug"]
        self.store.save_code(slug, "eyJ2IjoxfQ")                                        # saved, not approved
        self.assertEqual(self.code(lambda: self.store.set_delivery(slug, True, True)), "profile_not_approved")
        self.store.save_code(slug, "eyJ2IjoxfQ", approved=True)
        self.assertFalse((self.store.get(slug).get("delivery") or {}).get("active"))  # approval alone: still off
        self.assertEqual(self.code(lambda: self.store.set_delivery(slug, True, False)), "consent_required")
        on = self.store.set_delivery(slug, True, True)
        self.assertTrue(on["delivery"]["active"])
        self.assertEqual(on["delivery"]["consent"], "mycast-delivery-consent-2026-11-07")
        self.store.set_delivery(slug, False, False)                                     # stop really revokes
        self.assertFalse(self.store.get(slug)["delivery"]["active"])
        actions = [a["action"] for a in self.store.get(slug)["audit"]]
        self.assertEqual(actions, ["approved", "delivery_enabled", "delivery_stopped"])

    def test_google_listener_without_telegram_cannot_enable(self):
        slug = self.gg["slug"]
        self.store.save_code(slug, "eyJ2IjoxfQ", approved=True)
        self.assertEqual(self.code(lambda: self.store.set_delivery(slug, True, True)), "telegram_not_linked")

    def test_edit_after_approval_pauses_delivery(self):
        slug = self.tg["slug"]
        self.store.save_code(slug, "eyJ2IjoxfQ", approved=True)
        self.store.set_delivery(slug, True, True)
        rec = self.store.save_code(slug, "eyJ2IjoyfQ")                                  # a different podcast
        self.assertEqual((rec["delivery"]["active"], rec["delivery"]["paused_reason"], rec["approved_code"]), (False, "profile_changed", ""))
        self.assertEqual(self.code(lambda: self.store.set_delivery(slug, True, True)), "profile_not_approved")

    def test_send_limit(self):
        slug = self.tg["slug"]
        for _ in range(3):
            self.store.take_send(slug, "test")
        self.assertEqual(self.code(lambda: self.store.take_send(slug, "test")), "send_limit")


class RoutesTest(unittest.TestCase):
    def test_flow(self):
        from fastapi import FastAPI
        with tempfile.TemporaryDirectory() as d:
            app = FastAPI()
            store = ListenerStore(Path(d) / "l.json", clock=lambda: NOW)
            sent = []
            install_mycast_account_routes(app, store, secret="s", bot_token=lambda: BOT, bot_username=lambda: "FactoryOSBot",
                                          google_client_id=lambda: "cid", clock=lambda: NOW,
                                          send_message=lambda chat, text: sent.append(("msg", chat)),
                                          send_sample=lambda chat, job: sent.append(("sample", chat, job)),
                                          google_verify=lambda c: {"sub": "g-1", "given_name": "Olena"} if c == "good" else (_ for _ in ()).throw(ValueError()))
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

            class Req:
                def __init__(self, body=None, cookie=""):
                    self.body, self.cookies = body, {COOKIE: cookie} if cookie else {}
                async def json(self):
                    if self.body is None: raise ValueError
                    return self.body

            run = asyncio.run
            cfg = h[("GET", "/api/mycast/account/config")]()
            self.assertEqual((cfg["telegram_bot"], cfg["telegram_bot_id"], cfg["google_client_id"]), ("FactoryOSBot", "123456", "cid"))
            self.assertNotIn("TEST-token", json.dumps(cfg))                                           # never the secret part
            r = run(h[("POST", "/api/mycast/account/telegram")](Req({**tg_login(), "ref": "zzzzzzzz"})))   # ref is not signed by Telegram
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
            # #281: a Google listener links Telegram to the same account; nothing is sent by linking
            gcookie = g.headers["set-cookie"].split(";")[0].split("=", 1)[1]
            linked = json.loads(run(h[("POST", "/api/mycast/account/telegram")](Req(tg_login(id=555), gcookie))).body)["listener"]
            self.assertEqual((linked["slug"], linked["provider"], linked["telegram_linked"], linked["telegram_verified"]),
                             (json.loads(g.body)["listener"]["slug"], "google", True, False))
            self.assertEqual(sent, [])
            # #281 delivery routes: off until approved + consented; messages only to the listener's own chat
            self.assertEqual(json.loads(run(h[("POST", "/api/mycast/account/delivery")](Req({"enable": True, "consent": True}, cookie))).body)["detail"], "profile_not_approved")
            run(h[("POST", "/api/mycast/account/podcast")](Req({"code": "eyJ2IjoxfQ", "approved": True}, cookie)))
            self.assertEqual(json.loads(run(h[("POST", "/api/mycast/account/delivery/sample")](Req({"job": "a" * 32}, cookie))).body)["detail"], "delivery_off")
            on = run(h[("POST", "/api/mycast/account/delivery")](Req({"enable": True, "consent": True}, cookie)))
            self.assertTrue(on["listener"]["delivery"]["active"])
            t = h[("POST", "/api/mycast/account/telegram/test")](Req(cookie=cookie))
            self.assertTrue(t["listener"]["telegram_verified"])
            run(h[("POST", "/api/mycast/account/delivery/sample")](Req({"job": "b" * 32}, cookie)))
            self.assertEqual(sent, [("msg", "777"), ("sample", "777", "b" * 32)])                     # only chat 777
            self.assertEqual(json.loads(run(h[("POST", "/api/mycast/account/delivery/sample")](Req({"job": "../x"}, cookie))).body)["detail"], "bad_job")
            gone = h[("DELETE", "/api/mycast/account")](Req(cookie=cookie))
            self.assertEqual(json.loads(gone.body), {"deleted": True})
            self.assertEqual(h[("GET", "/api/mycast/account/me")](Req(cookie=cookie)).status_code, 401)


if __name__ == "__main__":
    unittest.main(verbosity=2)
