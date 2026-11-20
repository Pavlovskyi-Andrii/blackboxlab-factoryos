"""T-712: "Forgot password?" — a one-time sign-in link to the owner's paired Telegram chat. Offline."""
import json
import os
import pathlib
import re
import unittest

from fastapi import FastAPI

import login_recovery as lr

ROOT = pathlib.Path(__file__).parent


class Clock:
    def __init__(self, t=1795132800.0):          # 2026-11-19T00:00:00Z
        self.t = t

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)
        self.clock, self.sent, self.logs, self.paired = Clock(), [], [], True
        self.rec = lr.LoginRecovery(send=self._send, base_url=lambda: "https://f.example", clock=self.clock, log=self.logs.append)
        app = FastAPI()
        lr.install_login_recovery_routes(app, self.rec, sign_in=lambda lang: ("SIGNED_IN", lang))
        self.h = {(sorted(r.methods)[0], r.path): r.endpoint for r in app.routes if hasattr(r, "endpoint")}

    def tearDown(self):
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)

    def _send(self, text):
        if not self.paired:
            return False
        self.sent.append(text)
        return True

    def token(self):
        return re.search(r"/login/recover/([A-Za-z0-9_-]+)\?lang=", self.sent[-1]).group(1)


class RecoveryTest(Base):
    def test_link_goes_to_telegram_only_and_works_once(self):
        r = self.h[("POST", "/login/recover")](lang="ru")
        page = r.body.decode()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(self.sent), 1)
        token = self.token()
        self.assertIn(f"https://f.example/login/recover/{token}?lang=ru", self.sent[0])
        self.assertNotIn(token, page)                                   # never on the page
        self.assertNotIn(token, "".join(self.logs))                     # never in the log
        self.assertIn("FACTORY_PASSWORD", page)                         # says where the password itself lives
        self.assertEqual(r.headers["cache-control"], "no-store")
        opened = self.h[("GET", "/login/recover/{token}")](token, lang="ru")
        self.assertEqual(opened.status_code, 200)
        self.assertIn("method='post'", opened.body.decode())            # a preview that only GETs cannot sign in…
        self.assertTrue(self.rec.valid(token))                          # …and does not use the link up
        self.assertEqual(self.h[("POST", "/login/recover/{token}")](token, lang="ru"), ("SIGNED_IN", "ru"))
        again = self.h[("POST", "/login/recover/{token}")](token, lang="ru")
        self.assertEqual(again.status_code, 410)                        # once only
        self.assertEqual(self.h[("GET", "/login/recover/{token}")](token).status_code, 410)
        self.assertIn("LOGIN_RECOVERY_USED", "".join(self.logs))

    def test_wrong_expired_and_replaced_links_do_not_sign_in(self):
        self.h[("POST", "/login/recover")](lang="en")
        first = self.token()
        use = self.h[("POST", "/login/recover/{token}")]
        self.assertEqual(use("x" * 43).status_code, 410)
        self.assertEqual(use("").status_code, 410)
        self.assertEqual(use("y" * 5000).status_code, 410)
        self.assertTrue(self.rec.valid(first))                           # wrong guesses do not burn the real link
        self.clock.t += lr.MIN_INTERVAL_SECONDS + 1
        self.h[("POST", "/login/recover")](lang="en")
        self.assertEqual(use(first).status_code, 410)                    # a newer link replaces the older one
        second = self.token()
        self.clock.t += lr.TTL_SECONDS + 1
        self.assertEqual(use(second).status_code, 410)                   # expired

    def test_rate_limit_and_daily_cap(self):
        ask = self.h[("POST", "/login/recover")]
        self.assertEqual(ask(lang="uk").status_code, 200)
        self.assertEqual(ask(lang="uk").status_code, 429)                # too soon: nothing sent
        self.assertEqual(len(self.sent), 1)
        self.assertTrue(self.rec.valid(self.token()))                    # the first link still works
        for _ in range(lr.DAILY_CAP - 1):
            self.clock.t += lr.MIN_INTERVAL_SECONDS + 1
            self.assertEqual(ask(lang="uk").status_code, 200)
        self.clock.t += lr.MIN_INTERVAL_SECONDS + 1
        self.assertEqual(ask(lang="uk").status_code, 429)                # daily cap
        self.assertEqual(len(self.sent), lr.DAILY_CAP)
        self.clock.t += 86400
        self.assertEqual(ask(lang="uk").status_code, 200)                # next UTC day

    def test_same_answer_without_a_paired_chat_and_no_usable_link(self):
        paired_page = self.h[("POST", "/login/recover")](lang="en").body.decode()
        other = Base()
        other.setUp()
        other.paired = False
        r = other.h[("POST", "/login/recover")](lang="en")
        self.assertEqual((r.status_code, r.body.decode()), (200, paired_page))   # does not reveal whether a chat is paired
        self.assertEqual(other.sent, [])
        self.assertFalse(other.rec._token_hash)
        self.assertIn('"delivered": false', "".join(other.logs))
        boom = lr.LoginRecovery(send=lambda text: 1 / 0, base_url=lambda: "https://f.example", clock=Clock(), log=lambda line: None)
        self.assertEqual(boom.request("en"), "sent")                     # a Telegram failure is not shown either
        self.assertFalse(boom._token_hash)

    def test_kill_switch_hides_the_button_and_the_routes(self):
        self.assertIn("action='/login/recover'", lr.link_html("ru"))
        self.assertIn("Забыли пароль?", lr.link_html("ru"))
        self.assertIn("Forgot password?", lr.link_html("zz"))
        self.h[("POST", "/login/recover")](lang="en")
        token = self.token()
        os.environ["FACTORY_LOGIN_RECOVERY_ENABLED"] = "0"
        self.assertEqual(lr.link_html("ru"), "")
        self.assertEqual(self.h[("POST", "/login/recover")](lang="en").status_code, 404)
        self.assertEqual(self.h[("GET", "/login/recover/{token}")](token).status_code, 404)
        self.assertEqual(self.h[("POST", "/login/recover/{token}")](token).status_code, 404)

    def test_three_languages_have_the_same_keys(self):
        self.assertEqual(set(lr.T["en"]), set(lr.T["uk"]))
        self.assertEqual(set(lr.T["en"]), set(lr.T["ru"]))
        for lang in lr.LANGS:
            self.assertIn("{url}", lr.T[lang]["message"])

    def test_app_wiring(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"/login/recover", "/auth/google"', src)           # reachable without a session
        self.assertIn('"/login/recover/"', src)
        self.assertIn("{login_recovery.link_html(lang)}", src)
        self.assertRegex(src, r'def _login_recovery_send[\s\S]{0,400}_telegram_load_state\(\)\.get\("chat_id"\)[\s\S]{0,300}"disable_web_page_preview":True')
        self.assertIn('sign_in=lambda lang: _auth_cookie_response(f"/{lang}","owner","")', src)


if __name__ == "__main__":
    unittest.main(verbosity=2)
