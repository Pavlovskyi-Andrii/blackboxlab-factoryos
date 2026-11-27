"""Password sign-in accepts the FACTORY_USER login or an owner email; the password stays required. Offline."""
import os
import pathlib
import tempfile
import unittest

import password_login as pl

EMAILS = pl.parse_emails(" Owner@Example.com ,other@example.com", "second@example.org,not-an-email")


class PasswordLoginTest(unittest.TestCase):
    def ok(self, user, password="s3cret!", factory_user="blackboxlab", factory_password="s3cret!", emails=EMAILS):
        return pl.password_login_ok(user, password, factory_user, factory_password, emails)

    def test_parse_emails_trims_lowercases_and_merges_lists(self):
        self.assertEqual(EMAILS, {"owner@example.com", "other@example.com", "second@example.org"})
        self.assertEqual(pl.parse_emails("", None), set())

    def test_the_configured_login_still_works(self):
        self.assertTrue(self.ok("blackboxlab"))
        self.assertTrue(self.ok(" blackboxlab "))            # stray spaces from autofill no longer break it
        self.assertFalse(self.ok("BlackBoxLab"))             # the login itself stays case-sensitive

    def test_an_owner_email_works_in_any_case(self):
        for user in ("owner@example.com", "OWNER@example.COM", "  owner@example.com\t", "second@example.org"):
            self.assertTrue(self.ok(user), user)

    def test_an_email_never_replaces_the_password(self):
        self.assertFalse(self.ok("owner@example.com", password="wrong"))
        self.assertFalse(self.ok("owner@example.com", password=""))
        self.assertFalse(self.ok("owner@example.com", password="s3cret! "))

    def test_unknown_identifiers_are_refused(self):
        for user in ("stranger@example.com", "owner@example.co", "example.com", "", "not-an-email"):
            self.assertFalse(self.ok(user), user)
        self.assertFalse(self.ok("owner@example.com", emails=set()))

    def test_no_configured_password_lets_nobody_in(self):
        self.assertFalse(self.ok("blackboxlab", password="", factory_password=""))
        self.assertFalse(self.ok("owner@example.com", password="", factory_password=""))

    def test_the_login_route_uses_it(self):
        env = {"DATA_DIR": tempfile.mkdtemp(prefix="factoryos-pwlogin-"), "FACTORY_USER": "blackboxlab",
               "FACTORY_PASSWORD": "s3cret!", "FACTORY_GOOGLE_OWNER_EMAILS": "Owner@Example.com",
               "FACTORY_OWNER_EMAILS": "second@example.org", "FACTORY_LLM_API_KEY": ""}
        saved = {k: os.environ.get(k) for k in env}
        os.environ.update(env)
        try:
            import app as factory                        # the endpoint is called directly: no HTTP client in CI
            factory.FACTORY_USER, factory.FACTORY_PASSWORD = "blackboxlab", "s3cret!"
            factory.FACTORY_OWNER_LOGIN_EMAILS = pl.parse_emails("Owner@Example.com", "second@example.org")
            for user, password, status in (("owner@example.com", "s3cret!", 303), ("Second@Example.org", "s3cret!", 303),
                                           ("blackboxlab", "s3cret!", 303), ("owner@example.com", "nope", 401),
                                           ("stranger@example.com", "s3cret!", 401)):
                r = factory.login(username=user, password=password, lang="ru")
                self.assertEqual(r.status_code, status, user)
                cookie = r.headers.get("set-cookie", "")
                self.assertEqual(cookie.startswith(factory.COOKIE_NAME + "="), status == 303, user)
            src = (pathlib.Path(__file__).parent / "app.py").read_text(encoding="utf-8")
            self.assertIn('"user":"Логин или email"', src)
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v

    def test_the_app_reads_both_env_lists(self):
        src = (pathlib.Path(__file__).parent / "app.py").read_text(encoding="utf-8")
        self.assertIn('os.environ.get("FACTORY_OWNER_EMAILS","")', src)
        self.assertIn("password_login.password_login_ok(", src)


if __name__ == "__main__":
    unittest.main()
