"""#305 / T-620 MyCast MVP V1: library, private-by-default episodes with revocable public links, the referral ledger
(+7 each side exactly once) and the free-access period. Offline: no Telegram, no Gemini, no network."""
import asyncio
import json
import os
import pathlib
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI

import mycast_library as lib
import mycast_listener_delivery as mld
from mycast_accounts import COOKIE, ListenerStore, install_mycast_account_routes, public_view, sign
from test_mycast_listener_delivery import CODE, Clock, at, ready_listener


class Req:
    def __init__(self, body=None, cookie=""):
        self.body, self.cookies = body, {COOKIE: cookie} if cookie else {}

    async def json(self):
        if self.body is None:
            raise ValueError
        return self.body


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock(at("2026-11-13", "07:31"))
        self.store = ListenerStore(pathlib.Path(self.tmp.name) / "l.json", clock=self.clock)
        self.d = mld.ListenerDelivery(self.store, clock=self.clock)
        self.fetched = []
        self.app = FastAPI()
        install_mycast_account_routes(self.app, self.store, secret="s", bot_token=lambda: "1:x", bot_username=lambda: "b",
                                      google_client_id=lambda: "", google_verify=lambda c: {}, clock=self.clock,
                                      fetch_audio=lambda fid: self.fetched.append(fid) or b"ID3" + fid.encode())
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in self.app.routes if hasattr(r, "methods")}

    def tearDown(self):
        self.tmp.cleanup()

    def deliver(self, slug, day, ok=True, file_id="FID"):
        self.clock.t = at(day, "07:31")
        self.d.claim(slug, day)
        self.d.finish(slug, day, ok, "" if ok else "TelegramError", seconds=300, file_id=file_id if ok else "",
                      title=f"MyCast · {day}")

    def cookie(self, slug):
        return sign("s", slug, self.clock())

    def visibility(self, slug, day, public):
        r = asyncio.run(self.h[("POST", "/api/mycast/account/episodes/{day}/visibility")](day, Req({"public": public}, self.cookie(slug))))
        return r if isinstance(r, dict) else (r.status_code, json.loads(r.body)["detail"])


class LibraryTest(Base):
    def test_history_persists_beyond_the_delivery_log_and_shows_honest_states(self):
        s = ready_listener(self.store)
        days = [f"2026-11-{d:02d}" for d in range(1, 21)]
        for day in days:
            self.deliver(s, day, file_id="F" + day)
        rec = self.store.get(s)
        self.assertEqual(len(rec["deliveries"]), 14)                        # the delivery log stays short...
        self.assertEqual(len(rec["library"]), 20)                           # ...the library keeps everything
        self.clock.t = at("2026-11-21", "07:31")
        self.d.claim(s, "2026-11-21")                                       # being prepared right now
        rows = self.h[("GET", "/api/mycast/account/episodes")](Req(cookie=self.cookie(s)))["episodes"]
        self.assertEqual(rows[0], {"date": "2026-11-21", "title": "MyCast · 2026-11-21", "seconds": 0, "status": "preparing",
                                   "audio": False, "public": False, "public_url": None})
        self.assertEqual([r["date"] for r in rows[1:]], sorted(days, reverse=True))
        self.assertTrue(all(r["status"] == "ready" and r["audio"] and not r["public"] for r in rows[1:]))
        self.d.finish(s, "2026-11-21", False, "TelegramError")
        rows = self.h[("GET", "/api/mycast/account/episodes")](Req(cookie=self.cookie(s)))["episodes"]
        self.assertEqual(rows[0]["status"], "failed")
        # an episode older than the 14-day log still plays for its owner, and the store survives a reload
        reloaded = ListenerStore(self.store.path, clock=self.clock)
        self.assertIn("2026-11-01", reloaded.get(s)["library"])
        audio = self.h[("GET", "/api/mycast/account/episodes/{day}/audio")]("2026-11-01", Req(cookie=self.cookie(s)))
        self.assertEqual(audio.body, b"ID3F2026-11-01")

    def test_other_users_never_see_private_records(self):
        a, b = ready_listener(self.store, "700"), ready_listener(self.store, "701")
        self.deliver(a, "2026-11-13")
        self.assertEqual(self.h[("GET", "/api/mycast/account/episodes")](Req(cookie=self.cookie(b)))["episodes"], [])
        self.assertEqual(self.h[("GET", "/api/mycast/account/episodes/{day}/audio")]("2026-11-13", Req(cookie=self.cookie(b))).status_code, 404)
        self.assertEqual(self.visibility(b, "2026-11-13", True), (404, "episode_not_found"))   # cannot publish A's episode
        self.assertEqual(self.h[("GET", "/api/mycast/account/episodes")](Req()).status_code, 401)
        self.assertNotIn("public_token", json.dumps(self.store.get(a)["library"]["2026-11-13"]).replace('"public_token": ""', ""))


class PublicLinkTest(Base):
    def test_publish_unpublish_and_republish(self):
        s = ready_listener(self.store)
        self.deliver(s, "2026-11-13", file_id="SECRETFILE")
        row = self.visibility(s, "2026-11-13", True)["episode"]
        self.assertTrue(row["public"])
        token = row["public_url"].rsplit("/", 1)[1]
        self.assertRegex(token, lib.TOKEN_RE)
        page = self.h[("GET", "/mycast/e/{token}")](token)                   # a logged-out visitor
        body = page.body.decode()
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'/mycast/e/{token}/audio.mp3', body)
        self.assertIn("noindex", body)
        self.assertEqual((page.headers["x-robots-tag"], page.headers["cache-control"]), ("noindex, nofollow", "no-store"))
        for private in ("777", "SECRETFILE", CODE[:20], s):                  # no chat id, file id, settings or slug
            self.assertNotIn(private, body)
        self.assertIn("Андрій", body)                                       # first name only
        self.assertNotIn("Тест", body)
        audio = self.h[("GET", "/mycast/e/{token}/audio.mp3")](token)
        self.assertEqual((audio.status_code, audio.body), (200, b"ID3SECRETFILE"))
        self.assertEqual(self.visibility(s, "2026-11-13", True)["episode"]["public_url"], row["public_url"])  # idempotent
        self.assertFalse(self.visibility(s, "2026-11-13", False)["episode"]["public"])
        self.assertEqual(self.h[("GET", "/mycast/e/{token}")](token).status_code, 404)           # revoked at once
        self.assertEqual(self.h[("GET", "/mycast/e/{token}/audio.mp3")](token).status_code, 404)
        again = self.visibility(s, "2026-11-13", True)["episode"]["public_url"]
        self.assertNotEqual(again, row["public_url"])                       # a new link; the old one stays dead
        self.assertEqual(self.h[("GET", "/mycast/e/{token}")](token).status_code, 404)
        actions = [a["action"] for a in self.store.get(s)["audit"]]
        self.assertEqual(actions[-3:], ["episode_published", "episode_unpublished", "episode_published"])

    def test_hostile_title_cannot_break_out_of_the_page(self):
        s = ready_listener(self.store)
        evil = '</script><script>alert(1)</script>"\'<b>'
        self.clock.t = at("2026-11-13", "07:31")
        self.d.claim(s, "2026-11-13")
        self.d.finish(s, "2026-11-13", True, seconds=60, file_id="F", title=evil)
        token = self.visibility(s, "2026-11-13", True)["episode"]["public_url"].rsplit("/", 1)[1]
        body = self.h[("GET", "/mycast/e/{token}")](token).body.decode()
        self.assertNotIn("<script>alert", body)
        self.assertNotIn("</script><script>", body)
        self.assertEqual(body.count("<script>"), 1)

    def test_not_ready_unknown_and_deleted(self):
        s = ready_listener(self.store)
        self.deliver(s, "2026-11-13", file_id="")                           # sent, but Telegram gave no file id
        self.assertEqual(self.visibility(s, "2026-11-13", True), (409, "episode_not_ready"))
        self.assertEqual(self.visibility(s, "2026-11-14", True), (404, "episode_not_found"))
        self.assertEqual(self.visibility(s, "../../x", True), (404, "episode_not_found"))
        for bad in ("short", "../../etc/passwd", "A" * 16):
            self.assertEqual(self.h[("GET", "/mycast/e/{token}")](bad).status_code, 404)
        self.deliver(s, "2026-11-14")
        token = self.visibility(s, "2026-11-14", True)["episode"]["public_url"].rsplit("/", 1)[1]
        self.assertEqual(self.h[("GET", "/mycast/e/{token}")](token).status_code, 200)
        self.h[("DELETE", "/api/mycast/account")](Req(cookie=self.cookie(s)))
        self.assertEqual(self.h[("GET", "/mycast/e/{token}")](token).status_code, 404)           # links die with the account
        self.assertEqual(json.loads(self.store.path.read_text()).get("episode_links"), {})


class ReferralTest(Base):
    def invite(self, inviter, pid, chat=None):
        chat = chat or pid
        f = self.store.login({"provider": "telegram", "pid": pid, "name": "F", "chat_id": chat}, ref=inviter)["slug"]
        self.store.save_code(f, CODE, approved=True)
        self.store.set_delivery(f, True, True)
        return f

    def days(self, slug):
        return public_view(self.store.get(slug))["free_days"]

    def test_valid_referral_credits_both_exactly_once(self):
        a = ready_listener(self.store, "800")
        f = self.invite(a, "801")
        self.assertEqual((self.days(a), self.days(f)), (7, 7))              # incomplete: signed up, no episode yet
        self.deliver(f, "2026-11-13")
        self.assertEqual((self.days(a), self.days(f)), (14, 14))
        self.deliver(f, "2026-11-14")                                       # more episodes, retries: nothing more
        self.assertTrue(not lib.credit(json.loads(self.store.path.read_text()), self.store.get(f), 0))
        self.assertEqual((self.days(a), self.days(f)), (14, 14))
        ledger = json.loads(self.store.path.read_text())["referral_ledger"]
        self.assertEqual([(e["status"], e["inviter"], e["friend"], e["days_each"]) for e in ledger], [("credited", a, f, 7)])
        self.assertNotIn("801", json.dumps(ledger))                         # only one-way hashes identify the friend
        events = public_view(self.store.get(a))["referral"]["events"]
        self.assertEqual([(e["role"], e["status"], e["days"]) for e in events], [("inviter", "credited", 7)])

    def test_self_duplicate_and_incomplete_referrals_grant_nothing(self):
        a = ready_listener(self.store, "900")
        same_chat = self.store.login({"provider": "google", "pid": "g-900", "name": "Me"}, ref=a)["slug"]
        self.store.link_telegram(same_chat, "900")                          # my own Telegram chat, via Google
        self.store.save_code(same_chat, CODE, approved=True)
        self.store.set_delivery(same_chat, True, True)
        self.deliver(same_chat, "2026-11-13")
        self.assertEqual((self.days(a), self.days(same_chat)), (7, 7))
        self.assertEqual(self.store.get(same_chat)["referral_rejected"], "self_referral")
        tg_self = self.store.login({"provider": "telegram", "pid": "900", "name": "Me", "chat_id": "900"}, ref=a)
        self.assertEqual(tg_self["slug"], a)                                # same identity is the same account
        # a friend is credited once, even after deleting and re-creating the account with the same Telegram
        f = self.invite(a, "901")
        self.deliver(f, "2026-11-14")
        self.assertEqual(self.days(a), 14)
        self.store.delete(f)
        f2 = self.invite(a, "901")
        self.deliver(f2, "2026-11-15")
        self.assertEqual((self.days(a), self.days(f2)), (14, 7))
        self.assertEqual(self.store.get(f2)["referral_rejected"], "duplicate_friend")
        # signed up through the link but never got an episode: nothing
        self.invite(a, "902")
        self.assertEqual(self.days(a), 14)
        statuses = [(e["status"], e["reason"]) for e in json.loads(self.store.path.read_text())["referral_ledger"]]
        self.assertEqual(statuses, [("rejected", "self_referral"), ("credited", ""), ("rejected", "duplicate_friend")])

    def test_concurrent_retries_cannot_double_credit(self):
        a = ready_listener(self.store, "950")
        f = self.invite(a, "951")
        self.d.claim(f, "2026-11-13")
        threads = [threading.Thread(target=self.d.finish, args=(f, "2026-11-13", True),
                                    kwargs={"seconds": 1, "file_id": "X"}) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(self.store.get(a)["referrals"], 1)
        self.assertEqual(len(json.loads(self.store.path.read_text())["referral_ledger"]), 1)

    def test_promotion_is_off_until_the_owner_signs_off(self):
        cfg = self.h[("GET", "/api/mycast/account/config")]()
        self.assertFalse(cfg["referrals_enabled"])
        a = ready_listener(self.store, "960")
        self.assertFalse(public_view(self.store.get(a))["referral"]["enabled"])
        with patch.dict(os.environ, {"FACTORY_MYCAST_REFERRALS": "1"}):
            self.assertTrue(self.h[("GET", "/api/mycast/account/config")]()["referrals_enabled"])
        f = self.invite(a, "961")                                           # invites are still recorded meanwhile
        self.assertEqual(self.store.get(f)["referred_by"], a)


class AccessTest(Base):
    def test_access_period_starts_at_first_episode_and_is_enforced_only_by_switch(self):
        s = ready_listener(self.store)
        self.assertEqual(public_view(self.store.get(s))["access"],
                         {"free_days": 7, "started_at": None, "until": None, "enforced": False})
        self.deliver(s, "2026-11-13")
        acc = public_view(self.store.get(s))["access"]
        self.assertEqual(acc["until"] - acc["started_at"], 7 * 86400)
        self.clock.t = acc["until"] + 3600
        rec = self.store.get(s)
        self.assertNotEqual(mld.delivery_gate(rec, self.clock())["state"], "trial_ended")   # open beta: not enforced
        with patch.dict(os.environ, {"FACTORY_MYCAST_ENFORCE_TRIAL": "1"}):
            self.assertEqual(mld.delivery_gate(rec, self.clock())["state"], "trial_ended")
            self.assertEqual(mld.delivery_gate(rec, acc["until"] - 60)["state"] != "trial_ended", True)

    def test_legacy_deliveries_without_library_still_count(self):
        rec = {"slug": "abcd2345", "deliveries": {"2026-11-10": {"status": "sent", "file_id": "F", "at": "x"}}}
        self.assertEqual(lib.access(rec)["started_at"], 1794268800)         # 2026-11-10T00:00:00Z
        self.assertEqual([r["date"] for r in lib.episode_rows(rec)], ["2026-11-10"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
