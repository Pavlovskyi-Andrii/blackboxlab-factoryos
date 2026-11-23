"""T-721 Surfer policy gate: flag, pause, allowlist, caps, vault access, login wall, owner routes. Offline."""
import asyncio
import json
import os
import pathlib
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="factoryos-surfer-policy-")
os.environ["DATA_DIR"] = TMP
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")
os.environ.pop("FACTORY_SURFER_ACTIONS_ENABLED", None)
from browser_runner.vault import generate_key  # noqa: E402

os.environ["FACTORY_VAULT_KEY"] = generate_key()

from fastapi import HTTPException  # noqa: E402

import surfer_actions as sa  # noqa: E402
import surfer_fake_browser as fb  # noqa: E402
import surfer_fixture_site as fixture  # noqa: E402
import surfer_policy as sp  # noqa: E402
import test_surfer_actions as base  # noqa: E402

LOGIN = "fixture/main"


class Vault:
    def __init__(self):
        self.creds = {("fixture", "main"): {"username": fixture.USERNAME, "password": fixture.PASSWORD}}
        self.states = {}

    def logins(self):
        return ["%s/%s" % key for key in list(self.creds) + list(self.states)]

    def secret(self, provider, account, kind):
        return self.creds.get((provider, account), {}).get(kind, "")

    def has_secret(self, provider, account):
        return "password" in self.creds.get((provider, account), {})

    def storage_state(self, provider, account):
        return self.states.get((provider, account))

    def save_storage_state(self, provider, account, state):
        self.states[(provider, account)] = state
        return True


class GateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.env = {}
        self.clock = base.Clock()
        self.vault = Vault()
        self.gate = sp.PolicyGate(pathlib.Path(self.tmp.name), env=self.env, vault=self.vault, clock=self.clock)

    def on(self):
        self.env[sp.FLAG_ENV] = "1"

    def site(self, **extra):
        return self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate", "fill", "submit"],
                                     "enabled": True, **extra})

    def test_off_by_default_and_nothing_on_the_list(self):
        status = self.gate.status()
        self.assertEqual((status["enabled"], status["flag"], status["paused"]), (False, False, False))
        self.assertIn(sp.FLAG_ENV, status["reason"])
        self.assertEqual(self.gate.entries(), [])
        self.site()                                         # an entry alone does not switch anything on
        self.assertEqual(self.gate.allow(), [])
        for lane in ("claude", "chatgpt", "gemini", ""):
            with self.assertRaises(HTTPException) as err:
                self.gate.require(lane)
            self.assertEqual(err.exception.status_code, 503)
        self.assertEqual(self.gate.secret(f"vault:{LOGIN}#password"), "")
        for value in ("0", "false", "no", "off", "", "enabled?"):
            self.env[sp.FLAG_ENV] = value
            self.assertFalse(self.gate.status()["enabled"], value)

    def test_flag_lane_and_pause(self):
        self.on()
        self.gate.require("claude")
        for lane in ("", "owner", "shared", "Claude"):
            with self.assertRaises(HTTPException) as err:
                self.gate.require(lane)
            self.assertEqual(err.exception.status_code, 403)
        self.site()
        self.assertEqual([e["pattern"] for e in self.gate.allow()], ["shop.example"])
        self.assertTrue(self.gate.set_paused(True))
        self.assertEqual(self.gate.allow(), [])
        with self.assertRaises(HTTPException) as err:
            self.gate.require("claude")
        self.assertIn("paused", err.exception.detail)
        self.gate.set_paused(False)
        self.gate.require("claude")

    def test_allowlist_entries_are_validated(self):
        self.on()
        for bad in ("com.ua", "onrender.com", "localhost", "10.1.2.3", "", "shop example", "*"):
            with self.assertRaises(HTTPException, msg=bad):
                self.gate.save_entry({"pattern": bad, "classes": ["read"], "enabled": True})
        entry = self.gate.save_entry({"pattern": "https://WWW.Shop.example/cabinet", "classes": ["submit", "shell"]})
        self.assertEqual((entry["pattern"], entry["classes"], entry["enabled"]),
                         ("www.shop.example", ["read", "submit"], False))        # off unless the owner says on
        self.assertEqual(self.gate.allow(), [])
        with self.assertRaises(HTTPException) as err:
            self.gate.save_entry({"pattern": "www.shop.example", "classes": ["read"]})
        self.assertEqual(err.exception.status_code, 409)
        with self.assertRaises(HTTPException):                                   # a login that is not in the vault
            self.gate.save_entry({"id": entry["id"], "pattern": "www.shop.example", "login": "github/main"})
        with self.assertRaises(HTTPException):
            self.gate.save_entry({"id": "al_000000000000", "pattern": "x.example"})
        updated = self.gate.save_entry({"id": entry["id"], "pattern": "www.shop.example", "classes": ["fill"],
                                        "enabled": True, "login": LOGIN, "note": "my  shop"})
        self.assertEqual((updated["id"], updated["classes"], updated["login"], updated["note"]),
                         (entry["id"], ["read", "fill"], LOGIN, "my shop"))
        self.assertEqual(self.gate.allow(), [{"pattern": "www.shop.example", "classes": ["read", "fill"],
                                              "enabled": True, "login": LOGIN}])
        self.assertTrue(self.gate.remove_entry(entry["id"]))
        self.assertFalse(self.gate.remove_entry(entry["id"]))
        self.assertEqual(self.gate.entries(), [])
        self.assertEqual([p["pattern"] for p in sp.PRESETS][:3],
                         ["blackboxlab-factoryos.onrender.com", "docs.google.com", "olx.ua"])
        for preset in sp.PRESETS:                                                # every suggestion is a valid entry
            self.assertEqual(self.gate.save_entry(dict(preset))["enabled"], False)

    def test_daily_caps(self):
        self.on()
        self.env[sp.SESSIONS_CAP_ENV], self.env[sp.STEPS_CAP_ENV] = "2", "3"
        self.gate.count("session")
        self.gate.count("session")
        with self.assertRaises(HTTPException) as err:
            self.gate.count("session")
        self.assertEqual(err.exception.status_code, 429)
        for _ in range(3):
            self.gate.count("step")
        with self.assertRaises(HTTPException):
            self.gate.count("step")
        self.assertEqual(self.gate.usage()["steps"], 3)
        self.clock.t += 86400
        self.assertEqual(self.gate.usage()["steps"], 0)
        self.gate.count("step")
        self.env[sp.STEPS_CAP_ENV] = "999999"                                    # a typo cannot remove the cap
        self.assertEqual(self.gate.caps()["steps"], sp.STEPS_CAP_MAX)
        self.env[sp.STEPS_CAP_ENV] = "many"
        self.assertEqual(self.gate.caps()["steps"], sp.STEPS_CAP_DEFAULT)

    def test_vault_values_only_for_a_login_bound_to_an_enabled_site(self):
        self.on()
        ref = f"vault:{LOGIN}#password"
        self.assertEqual(self.gate.secret(ref), "")                              # no site names this login
        entry = self.site(login=LOGIN)
        self.assertEqual(self.gate.secret(ref), fixture.PASSWORD)
        self.assertEqual(self.gate.secret(f"vault:{LOGIN}#username"), fixture.USERNAME)
        self.assertTrue(self.gate.has_login_secret(LOGIN))
        self.assertEqual(self.gate.secret("vault:github/main#password"), "")
        self.assertEqual(self.gate.secret(f"vault:{LOGIN}#cookie"), "")
        self.assertIsNone(self.gate.storage_state(LOGIN))
        self.assertTrue(self.gate.save_storage_state(LOGIN, {"cookies": [], "origins": []}))
        self.assertEqual(self.gate.storage_state(LOGIN), {"cookies": [], "origins": []})
        self.assertFalse(self.gate.save_storage_state("github/main", {"cookies": []}))
        self.gate.save_entry({**entry, "enabled": False})
        self.assertEqual(self.gate.secret(ref), "")
        self.assertIsNone(self.gate.storage_state(LOGIN))

    def test_approved_upload_files(self):
        for name, raw in (("run.sh", b"x"), ("a.exe", b"x"), ("empty.txt", b""),
                          ("big.pdf", b"x" * (sp.MAX_UPLOAD_BYTES + 1))):
            with self.assertRaises(HTTPException, msg=name):
                self.gate.add_upload(name, raw)
        row = self.gate.add_upload("../../etc/Price list.PDF", b"%PDF-1.4 fixture")
        self.assertRegex(row["id"], sp.UPLOAD_ID_RE)
        self.assertEqual((row["name"], row["bytes"]), ("Price list.PDF", 16))
        info = self.gate.upload(row["id"])
        self.assertEqual(pathlib.Path(info["path"]).parent, self.gate.upload_dir)
        self.assertIsNone(self.gate.upload("su_000000000000"))
        self.assertIsNone(self.gate.upload("../policy"))
        self.assertTrue(self.gate.remove_upload(row["id"]))
        self.assertIsNone(self.gate.upload(row["id"]))


class GatedSessionsTest(base.Harness):
    """The tools of T-720 behind the real gate."""

    def setUp(self):
        super().setUp()
        self.env = {}
        self.vault = Vault()
        self.gate = sp.PolicyGate(self.dir, env=self.env, vault=self.vault, clock=self.clock)
        self.wire.gate = self.gate

    def test_nothing_runs_until_the_owner_switches_it_on(self):
        with self.assertRaises(HTTPException) as err:
            self.open("/")
        self.assertEqual(err.exception.status_code, 503)
        self.env[sp.FLAG_ENV] = "1"
        with self.assertRaises(HTTPException) as err:                 # the flag alone allows no site
            self.open("/")
        self.assertEqual(err.exception.status_code, 403)
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate"], "enabled": False})
        with self.assertRaises(HTTPException) as err:                 # a listed but not enabled site neither
            self.open("/")
        self.assertEqual(err.exception.status_code, 403)
        self.assertEqual((self.store.list(), self.pw.launches), ([], 0))

    def test_classes_of_the_allowlist_bound_the_agent(self):
        self.env[sp.FLAG_ENV] = "1"
        entry = self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate"], "enabled": True})
        view = self.open("/wizard")
        fill = self.act(view, "fill", "Full name", value="A")
        self.assertEqual((fill["status"], fill["preview"]["reasons"]), ("needs_owner_confirmation", ["class_not_allowed"]))
        self.store.decide(fill["step_id"], confirm=False)
        self.gate.save_entry({**entry, "classes": ["read", "navigate", "fill"]})      # the owner adds "fill"
        self.assertEqual(self.act(view, "fill", "Full name", value="A")["status"], "done")
        submit = self.act(view, "click", "Next")
        self.assertEqual(submit["preview"]["reasons"], ["class_not_allowed"])
        self.assertEqual(self.pw.page.dom["title"], "Form step 1")

    def test_pause_closes_the_live_session_and_refuses_new_ones(self):
        self.env[sp.FLAG_ENV] = "1"
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate"], "enabled": True})
        view = self.open("/")
        self.gate.set_paused(True)
        self.assertEqual(self.store.stop_all(by="owner", reason="paused_by_owner"), 1)
        self.runner.pump()
        self.assertEqual(self.runner.live, "")
        with self.assertRaises(HTTPException) as err:
            self.run_tool(sa.web_snapshot, {"session_id": view["session_id"]})
        self.assertEqual(err.exception.status_code, 503)
        with self.assertRaises(HTTPException):
            self.open("/")

    def test_caps_stop_a_runaway_agent(self):
        self.env.update({sp.FLAG_ENV: "1", sp.STEPS_CAP_ENV: "2", sp.SESSIONS_CAP_ENV: "1"})
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate"], "enabled": True})
        view = self.open("/")
        self.act(view, "scroll", value="down")
        self.act(view, "scroll", value="down")
        with self.assertRaises(HTTPException) as err:
            self.act(view, "scroll", value="down")
        self.assertEqual(err.exception.status_code, 429)
        sa.web_close(self.store, self.gate, {"session_id": view["session_id"]}, "claude")
        self.runner.pump()
        with self.assertRaises(HTTPException) as err:
            self.open("/")
        self.assertEqual(err.exception.status_code, 429)

    def test_login_wall_without_a_saved_login_waits_for_the_owner(self):
        self.env[sp.FLAG_ENV] = "1"
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate", "fill", "submit"],
                              "enabled": True})
        view = self.open("/account")                                  # redirects to the login form
        self.assertEqual((view["status"], view["wait_reason"], view["title"]),
                         ("waiting_human", "login_required", "Sign in"))
        with self.assertRaises(HTTPException) as err:
            self.act(view, "fill", "Email", value="guess@example.test")
        self.assertEqual(err.exception.status_code, 409)

    def test_saved_login_gets_one_try_then_the_owner_takes_over(self):
        self.env[sp.FLAG_ENV] = "1"
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate", "fill", "submit"],
                              "enabled": True, "login": LOGIN})
        self.vault.creds[("fixture", "main")]["password"] = "an-old-password-1"
        view = self.open("/login")
        self.assertEqual(view["status"], "done")
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        out = self.act(view, "click", "Sign in")
        self.assertEqual((out["status"], out["wait_reason"]), ("waiting_human", "login_failed"))
        self.assertEqual(self.site.events, [{"event": "login", "ok": False}])
        with self.assertRaises(HTTPException):                        # no second automatic try
            self.act(view, "click", "Sign in")
        self.assertNotIn("an-old-password-1", self.everything_stored())

    def test_sms_code_step_waits_for_the_owner(self):
        self.env[sp.FLAG_ENV] = "1"
        self.site.sms_step = True
        self.gate.save_entry({"pattern": "shop.example", "classes": ["read", "navigate", "fill", "submit"],
                              "enabled": True, "login": LOGIN})
        view = self.open("/login")
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        out = self.act(view, "click", "Sign in")
        self.assertEqual((out["status"], out["wait_reason"], out["title"]),
                         ("waiting_human", "2fa", "Verification code"))
        with self.assertRaises(HTTPException):
            self.act(out, "fill", "Code", value="000000")
        self.assertEqual(self.site.events, [{"event": "login", "ok": True}])


class RealAppTest(unittest.TestCase):
    """The routes in the real app: owner-only, the gate off by default, the vault adapter on the encrypted vault."""

    @classmethod
    def setUpClass(cls):
        import app
        from test_vault_ui import Client
        cls.app, cls.c = app, Client()

    def test_1_default_state_and_presets(self):
        self.assertIsInstance(self.app.SURFER_GATE, sp.PolicyGate)
        self.assertFalse(self.app.SURFER_GATE.loopback)
        data = self.c.get("/api/factory/surfer/owner/policy").json()
        self.assertEqual((data["gate"]["enabled"], data["gate"]["flag"], data["allow"]), (False, False, []))
        self.assertEqual(len(data["presets"]), len(sp.PRESETS))
        self.assertEqual(data["classes"], ["read", "navigate", "fill", "submit", "upload"])

    def test_2_allowlist_pause_and_vault_adapter(self):
        c = self.c
        self.assertEqual(c.post("/api/factory/vault/credentials", json={
            "provider": "fixture", "account": "main", "username": fixture.USERNAME,
            "password": fixture.PASSWORD}).status_code, 200)
        self.assertEqual(c.post("/api/factory/surfer/owner/policy/allow", json={"pattern": "onrender.com"}).status_code, 400)
        saved = c.post("/api/factory/surfer/owner/policy/allow", json={
            "pattern": "shop.example", "classes": ["fill"], "enabled": True, "login": LOGIN})
        self.assertEqual(saved.status_code, 200, saved.text)
        body = saved.json()
        self.assertEqual(body["logins"], [LOGIN])
        self.assertNotIn(fixture.PASSWORD, saved.text)
        self.assertNotIn("shop.example", [p["pattern"] for p in body["presets"]])
        gate = self.app.SURFER_GATE
        self.assertEqual(gate.secret(f"vault:{LOGIN}#password"), "")              # the flag is still off
        os.environ[sp.FLAG_ENV] = "1"
        try:
            self.assertEqual(gate.secret(f"vault:{LOGIN}#password"), fixture.PASSWORD)
            self.assertEqual(gate.secret(f"vault:{LOGIN}#username"), fixture.USERNAME)
            self.assertTrue(gate.has_login_secret(LOGIN))
            self.assertIsNone(gate.storage_state(LOGIN))
            state = {"cookies": [{"name": "sid", "value": "v" * 20, "domain": ".shop.example", "path": "/",
                                  "expires": 1893456000}], "origins": []}
            self.assertTrue(gate.save_storage_state(LOGIN, state))
            self.assertEqual(gate.storage_state(LOGIN)["cookies"][0]["name"], "sid")
            paused = c.post("/api/factory/surfer/owner/policy/pause", json={"paused": True}).json()
            self.assertEqual((paused["paused"], paused["gate"]["enabled"]), (True, False))
            self.assertEqual(c.post("/api/factory/surfer/owner/steps/wa_0000000000000000/confirm").status_code, 409)
            c.post("/api/factory/surfer/owner/policy/pause", json={"paused": False})
        finally:
            os.environ.pop(sp.FLAG_ENV, None)
        entry_id = body["entry"]["id"]
        self.assertEqual(c.post(f"/api/factory/surfer/owner/policy/allow/{entry_id}/delete").status_code, 200)
        self.assertEqual(c.post(f"/api/factory/surfer/owner/policy/allow/{entry_id}/delete").status_code, 404)
        self.assertEqual(c.post("/api/factory/surfer/owner/steps/wa_0000000000000000/approve").status_code, 404)
        actions = [row["action"] for row in self.app.SURFER_ACTIONS.audit_tail()]
        self.assertTrue({"allowlist_save", "allowlist_delete", "pause", "resume"} <= set(actions))
        stored = "".join(p.read_text(errors="replace") for p in pathlib.Path(TMP).rglob("*")
                         if p.is_file() and p.suffix in (".json", ".jsonl"))
        self.assertNotIn(fixture.PASSWORD, stored)

    def test_3_routes_are_owner_only(self):
        from fastapi import FastAPI
        probe = FastAPI()
        sp.install_routes(probe, gate=self.app.SURFER_GATE, store=self.app.SURFER_ACTIONS,
                          identity=lambda request: {"role": "viewer"})
        for route in probe.routes:
            if not getattr(route, "path", "").startswith("/api/factory/surfer/owner/"):
                continue
            kwargs = {name: "x" for name in ("entry_id", "step_id", "decision") if "{" + name + "}" in route.path}
            with self.assertRaises(HTTPException) as err:
                result = route.endpoint(request=None, **kwargs)
                if asyncio.iscoroutine(result):
                    asyncio.run(result)
            self.assertEqual(err.exception.status_code, 403, route.path)


if __name__ == "__main__":
    unittest.main()
