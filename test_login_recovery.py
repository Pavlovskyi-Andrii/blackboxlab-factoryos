"""T-712: "Forgot password?" — `/login` in the owner's private Telegram chat gives a one-time sign-in link. Offline."""
import inspect
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

from fastapi import FastAPI

import login_recovery as lr

ROOT = pathlib.Path(__file__).parent
OWNER = "777"


def msg(text="/login", chat_id=777, chat_type="private", sender=777, bot=False):
    return {"text": text, "chat": {"id": chat_id, "type": chat_type}, "from": {"id": sender, "is_bot": bot}}


class Clock:
    def __init__(self, t=1795132800.0):          # 2026-11-19T00:00:00Z
        self.t = t

    def __call__(self):
        return self.t


class RecoveryTest(unittest.TestCase):
    def setUp(self):
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)
        self.clock, self.logs = Clock(), []
        self.rec = lr.LoginRecovery(base_url=lambda: "https://f.example", clock=self.clock, log=self.logs.append)
        app = FastAPI()
        lr.install_login_recovery_routes(app, self.rec, sign_in=lambda lang: ("SIGNED_IN", lang))
        self.routes = [(sorted(r.methods)[0], r.path) for r in app.routes if getattr(r, "path", "").startswith("/login")]
        self.h = {(sorted(r.methods)[0], r.path): r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        self.page, self.use = self.h[("GET", "/login/recover")], self.h[("POST", "/login/recover")]

    def tearDown(self):
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)

    def token(self, text):
        return re.search(r"/login/recover\?lang=\w+#([A-Za-z0-9_-]+)$", text).group(1)

    def test_only_the_owners_private_chat_can_ask_for_a_link(self):
        self.assertTrue(lr.owner_private_command(msg(), OWNER))
        self.assertTrue(lr.owner_private_command(msg("/login@FactoryBot now"), OWNER))
        for bad in (msg(chat_id=-100777, chat_type="supergroup"), msg(chat_type="group"),     # a group, even a paired one
                    msg(chat_id=-777, sender=-777), msg(chat_id=888, sender=888),             # another private chat
                    msg(sender=999), msg(bot=True), msg("/loginx"), msg("login"), msg("/ask /login"),
                    {"text": "/login"}, None):
            self.assertFalse(lr.owner_private_command(bad, OWNER), bad)
        self.assertFalse(lr.owner_private_command(msg(), ""))                                 # nothing paired
        self.assertFalse(lr.owner_private_command(msg(chat_id=-100777, chat_type="private", sender=-100777), "-100777"))

    def test_link_keeps_the_secret_in_the_fragment_and_works_once(self):
        text = self.rec.message("ru")
        token = self.token(text)
        self.assertIn(f"https://f.example/login/recover?lang=ru#{token}", text)     # after "#": browsers never send it
        self.assertNotIn(token, "".join(self.logs))
        page = self.page(lang="ru")
        body = page.body.decode()
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(token, body)
        self.assertIn("/login", body)                                               # the instructions name the command
        self.assertIn("FACTORY_PASSWORD", body)                                     # and where the password itself lives
        self.assertIn("method='post' action='/login/recover' hidden", body)
        self.assertEqual(page.headers["cache-control"], "no-store")
        self.assertIn("no-referrer", body)
        self.assertEqual(self.use(token=token, lang="ru"), ("SIGNED_IN", "ru"))
        self.assertEqual(self.use(token=token, lang="ru").status_code, 410)         # once only
        self.assertIn("LOGIN_RECOVERY_USED", "".join(self.logs))

    def test_the_public_site_cannot_request_replace_or_use_up_a_link(self):
        """Codex #430: no anonymous request may spam the owner's chat, spend a budget or revoke a usable link."""
        self.assertEqual(sorted(self.routes), [("GET", "/login/recover"), ("POST", "/login/recover")])
        self.assertEqual(list(inspect.signature(self.page).parameters), ["lang"])   # the page takes no secret
        token = self.token(self.rec.message("en"))
        for _ in range(50):                                                         # any amount of anonymous traffic
            self.assertEqual(self.page(lang="en").status_code, 200)
            self.assertEqual(self.use(token="x" * 43, lang="en").status_code, 410)
        self.assertEqual(self.use(token="", lang="en").status_code, 410)
        self.assertEqual(self.use(token="y" * 5000, lang="en").status_code, 410)
        self.assertEqual(self.use(token=token, lang="en"), ("SIGNED_IN", "en"))     # the owner's link still works

    def test_expired_and_replaced_links_do_not_sign_in(self):
        first = self.token(self.rec.message("uk"))
        second = self.token(self.rec.message("uk"))
        self.assertEqual(self.use(token=first, lang="uk").status_code, 410)         # a newer link replaces the older one
        self.clock.t += lr.TTL_SECONDS + 1
        self.assertEqual(self.use(token=second, lang="uk").status_code, 410)        # expired

    def test_an_undelivered_link_is_revoked_but_never_a_newer_one(self):
        old = self.rec.message("ru")
        self.rec.revoke(old)
        self.assertEqual(self.use(token=self.token(old), lang="ru").status_code, 410)
        stale = self.rec.message("ru")
        fresh = self.rec.message("ru")
        self.rec.revoke(stale)                                                      # a late failure of the older send
        self.assertEqual(self.use(token=self.token(fresh), lang="ru"), ("SIGNED_IN", "ru"))

    def test_kill_switch_hides_the_link_and_the_routes(self):
        self.assertIn("href='/login/recover?lang=ru'", lr.link_html("ru"))
        self.assertIn("Забыли пароль?", lr.link_html("ru"))
        self.assertIn("Forgot password?", lr.link_html("zz"))
        token = self.token(self.rec.message("en"))
        os.environ["FACTORY_LOGIN_RECOVERY_ENABLED"] = "0"
        self.assertEqual(lr.link_html("ru"), "")
        self.assertEqual(self.page(lang="en").status_code, 404)
        self.assertEqual(self.use(token=token, lang="en").status_code, 404)

    def test_three_languages_have_the_same_keys(self):
        for lang in ("uk", "ru"):
            self.assertEqual(set(lr.T["en"]), set(lr.T[lang]))
        for lang in lr.LANGS:
            self.assertIn("{url}", lr.T[lang]["message"])
            self.assertIn("/login", lr.T[lang]["how"])

    def test_page_script_parses_and_only_reads_the_fragment(self):
        self.assertIn("location.hash", lr.PAGE_JS)
        self.assertIn("history.replaceState", lr.PAGE_JS)                           # the secret leaves the address bar
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(lr.PAGE_JS)
        try:
            self.assertEqual(subprocess.run(["node", "--check", f.name], capture_output=True).returncode, 0)
        finally:
            os.unlink(f.name)

    def test_app_wiring(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn('"/login/recover", "/auth/google"', src)                      # reachable without a session
        self.assertNotIn('"/login/recover/"', src)                                  # no path that carries a secret
        self.assertIn("{login_recovery.link_html(lang)}", src)
        self.assertRegex(src, r"def _login_recovery_reply[\s\S]{0,300}login_recovery\.enabled\(\) or not login_recovery\.owner_private_command\(message,owner_chat\)")
        self.assertRegex(src, r'def _login_recovery_reply[\s\S]{0,600}"disable_web_page_preview":True[\s\S]{0,120}LOGIN_RECOVERY\.revoke\(text\)')
        hook = src.index("if _login_recovery_reply(g_msg,owner_chat):")
        self.assertLess(src.index("if not _telegram_webhook_authorized(request):"), hook)   # behind the webhook secret
        self.assertIn('sign_in=lambda lang: _auth_cookie_response(f"/{lang}","owner","")', src)


class WebhookGuardTest(unittest.TestCase):
    """Codex #430: the chat and sender ids in a webhook body count only behind Telegram's secret header. With the secret
    unset, missing or wrong, nothing is issued, replaced or sent. Runs against the real app."""

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-recovery-"))
        import app as factory
        from fastapi.testclient import TestClient
        cls.f, cls.client = factory, TestClient(factory.app, follow_redirects=False)

    def setUp(self):
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)
        f = self.f
        self.saved = (f.FACTORY_TELEGRAM_BOT_TOKEN, f._telegram_api, f._telegram_load_state, f.LOGIN_RECOVERY._token_hash,
                      f.LOGIN_RECOVERY._expires)
        self.sent = []
        f._telegram_api = lambda method, payload=None: self.sent.append((method, payload)) or {"ok": True}
        f._telegram_load_state = lambda: {"chat_id": OWNER}
        f.LOGIN_RECOVERY._token_hash, f.LOGIN_RECOVERY._expires = "", 0.0

    def tearDown(self):
        f = self.f
        (f.FACTORY_TELEGRAM_BOT_TOKEN, f._telegram_api, f._telegram_load_state, f.LOGIN_RECOVERY._token_hash,
         f.LOGIN_RECOVERY._expires) = self.saved
        os.environ.pop("FACTORY_LOGIN_RECOVERY_ENABLED", None)

    def hook(self, headers, message=None):
        return self.client.post("/api/integrations/telegram/webhook", json={"update_id": 1, "message": message or msg()}, headers=headers)

    def links(self):
        return [p for m, p in self.sent if "login/recover" in str(p)]

    def test_unset_missing_and_wrong_secrets_issue_nothing(self):
        f = self.f
        f.FACTORY_TELEGRAM_BOT_TOKEN = ""                                           # no bot token: there is no secret at all
        self.assertEqual(f._telegram_webhook_secret(), "")
        for headers in ({}, {"X-Telegram-Bot-Api-Secret-Token": ""}, {"X-Telegram-Bot-Api-Secret-Token": "anything"}):
            self.assertEqual(self.hook(headers).status_code, 403, headers)
        f.FACTORY_TELEGRAM_BOT_TOKEN = "1:test-token"
        good = f._telegram_webhook_secret()
        for headers in ({}, {"X-Telegram-Bot-Api-Secret-Token": ""}, {"X-Telegram-Bot-Api-Secret-Token": good[:-1] + "0"},
                        {"X-Telegram-Bot-Api-Secret-Token": "x" * 64}):
            self.assertEqual(self.hook(headers).status_code, 403, headers)
        self.assertEqual(self.sent, [])
        self.assertEqual(f.LOGIN_RECOVERY._token_hash, "")                          # nothing issued

    def test_a_bad_secret_cannot_replace_the_owners_link_and_only_the_owner_chat_gets_one(self):
        f = self.f
        f.FACTORY_TELEGRAM_BOT_TOKEN = "1:test-token"
        good = {"X-Telegram-Bot-Api-Secret-Token": f._telegram_webhook_secret()}
        self.assertEqual(self.hook(good, msg(chat_id=-100777, chat_type="supergroup")).status_code, 200)
        self.assertEqual(self.hook(good, msg(chat_id=888, sender=888)).status_code, 200)
        self.assertEqual(self.links(), [])                                          # a group and a foreign chat: nothing
        self.assertEqual(self.hook(good).json().get("action"), "login_link")
        link = self.links()[-1]
        self.assertEqual((link["chat_id"], link["disable_web_page_preview"]), (OWNER, True))
        token = link["text"].rsplit("#", 1)[1]
        current = f.LOGIN_RECOVERY._token_hash
        self.assertEqual(self.hook({"X-Telegram-Bot-Api-Secret-Token": "wrong"}).status_code, 403)
        self.assertEqual(self.hook({}).status_code, 403)
        self.assertEqual(f.LOGIN_RECOVERY._token_hash, current)                     # the owner's link was not replaced
        self.assertEqual(len(self.links()), 1)
        self.assertEqual(self.client.get("/api/factory/telegram/status").status_code, 401 if f.FACTORY_PASSWORD else 200)
        used = self.client.post("/login/recover", data={"token": token, "lang": "ru"})
        self.assertEqual((used.status_code, used.headers.get("location")), (303, "/ru"))
        self.assertEqual(self.client.post("/login/recover", data={"token": token, "lang": "ru"}).status_code, 410)

    def test_kill_switch_ignores_the_command(self):
        f = self.f
        f.FACTORY_TELEGRAM_BOT_TOKEN = "1:test-token"
        os.environ["FACTORY_LOGIN_RECOVERY_ENABLED"] = "0"
        self.hook({"X-Telegram-Bot-Api-Secret-Token": f._telegram_webhook_secret()})
        self.assertEqual(self.links(), [])
        self.assertEqual(f.LOGIN_RECOVERY._token_hash, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
