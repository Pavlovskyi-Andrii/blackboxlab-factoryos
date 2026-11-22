"""T-722 Surfer owner page: pending requests, code input, takeover, approved files, routes, the page itself. Offline."""
import asyncio
import base64
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

TMP = tempfile.mkdtemp(prefix="factoryos-surfer-owner-")
os.environ["DATA_DIR"] = TMP
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")
os.environ.pop("FACTORY_SURFER_ACTIONS_ENABLED", None)

from fastapi import HTTPException  # noqa: E402

import surfer_actions as sa  # noqa: E402
import surfer_fake_browser as fb  # noqa: E402
import surfer_fixture_site as fixture  # noqa: E402
import surfer_owner as so  # noqa: E402
import surfer_policy as sp  # noqa: E402
import test_surfer_actions as base  # noqa: E402
from test_surfer_policy import LOGIN, Vault  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
PAGE = ROOT / "static" / "surfer" / "index.html"


class OwnerHarness(base.Harness):
    def setUp(self):
        super().setUp()
        self.env = {sp.FLAG_ENV: "1"}
        self.vault = Vault()
        self.gate = sp.PolicyGate(self.dir, env=self.env, vault=self.vault, clock=self.clock)
        self.wire.gate = self.gate
        self.entry = self.gate.save_entry({"pattern": "shop.example", "enabled": True, "login": LOGIN,
                                           "classes": ["read", "navigate", "fill", "submit"]})

    def owner(self, session_id, kind, **payload):
        step = self.store.owner_command(session_id, kind, payload)
        self.runner.pump()
        return self.store.find_step(step["id"])[1]

    def status(self, view):
        return self.store.get(view["session_id"])["session"]["status"]


class PendingTest(OwnerHarness):
    def test_confirmation_request_says_what_and_why_in_three_languages(self):
        self.site.signed_in = True
        view = self.open("/account")
        self.assertEqual(so.pending_requests(self.store), [])
        waiting = self.act(view, "click", "Delete account")
        (item,) = so.pending_requests(self.store)
        self.assertEqual((item["kind"], item["id"], item["step_id"], item["lane"], item["site"], item["action"],
                          item["element"], item["reasons"]),
                         ("confirm", waiting["step_id"], waiting["step_id"], "claude", "shop.example", "click",
                          "Delete account", ["delete"]))
        self.assertEqual(item["page"], "/static/surfer/index.html")
        self.assertRegex(item["screenshot"], r"^/api/factory/surfer/owner/steps/wa_[0-9a-f]{16}/screenshot$")
        self.assertIn("Delete account", item["text"]["ru"])
        self.assertIn("удаление", item["text"]["ru"])
        self.assertIn("видалення", item["text"]["uk"])
        self.assertIn("deleting", item["text"]["en"])
        self.assertGreater(item["expires_in_seconds"], sa.OWNER_WAIT_SECONDS - 30)
        self.store.decide(waiting["step_id"], confirm=False)
        self.assertEqual(so.pending_requests(self.store), [])

    def test_a_fill_that_needs_the_owner_shows_its_value_but_never_a_secret(self):
        self.gate.save_entry({**self.entry, "classes": ["read", "navigate"]})
        view = self.open("/login")
        self.act(view, "fill", "Email", value="someone@example.test")
        (item,) = so.pending_requests(self.store)
        self.assertEqual((item["value"], item["reasons"]), ("someone@example.test", ["class_not_allowed"]))
        self.store.decide(item["step_id"], confirm=False)
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        (item,) = so.pending_requests(self.store)
        self.assertNotIn("value", item)
        self.assertNotIn(fixture.PASSWORD, json.dumps(item))

    def test_every_reason_and_wait_has_a_line_in_every_language(self):
        from browser_runner import action_policy
        self.assertEqual(set(so.REASONS), set(action_policy.REASONS))
        for table in (so.REASONS, so.WAITS, so.ACTIONS, so.TEMPLATES):
            for key, row in table.items():
                self.assertEqual(set(row), {"ru", "uk", "en"}, key)
                self.assertFalse(re.search(r"[іїєґ]", row["ru"]), key)
                self.assertFalse(re.search(r"[ыэъё]", row["uk"]), key)


class CodeAndTakeoverTest(OwnerHarness):
    def login_until_code(self):
        self.site.sms_step = True
        view = self.open("/login")
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        out = self.act(view, "click", "Sign in")
        self.assertEqual((out["status"], out["wait_reason"]), ("waiting_human", "2fa"))
        return view

    def test_owner_types_the_sms_code_and_the_agent_continues(self):
        view = self.login_until_code()
        (item,) = so.pending_requests(self.store)
        self.assertEqual((item["kind"], item["wait_reason"]), ("human", "2fa"))
        self.assertIn("код", item["text"]["ru"])
        wrong = self.owner(view["session_id"], "human_input", text="111111", submit=True)
        self.assertEqual((wrong["status"], self.status(view)), ("done", "waiting_human"))     # still asking
        done = self.owner(view["session_id"], "human_input", text=fixture.SMS_CODE, submit=True)
        self.assertEqual((done["status"], self.status(view)), ("done", "active"))
        self.assertEqual(self.site.events[-1], {"event": "code", "ok": True})
        self.assertEqual(so.pending_requests(self.store), [])
        after = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "refresh": True})
        self.assertEqual((after["status"], after["title"]), ("done", "Account"))
        self.assertEqual(self.act(after, "fill", "Note", value="hello")["status"], "done")       # the agent goes on
        stored = self.everything_stored()
        for secret in (fixture.SMS_CODE, "111111", fixture.PASSWORD):
            self.assertNotIn(secret, stored)
        rows = [r for r in self.store.audit_tail() if r["action"] == "human_input"]
        self.assertEqual([(r["who"], r["value"]) for r in rows], [("owner", "***"), ("owner", "***")])
        self.assertEqual(self.store._volatile, {})

    def test_owner_input_is_validated_and_lost_text_fails_closed(self):
        view = self.login_until_code()
        for bad in ("", "   ", "x" * 201):
            with self.assertRaises(HTTPException):
                self.store.owner_command(view["session_id"], "human_input", {"text": bad})
        with self.assertRaises(HTTPException) as err:                 # clicking needs Take over first
            self.store.owner_command(view["session_id"], "takeover_click", {"x": 5, "y": 5})
        self.assertEqual(err.exception.status_code, 409)
        with self.assertRaises(HTTPException):
            self.store.owner_command(view["session_id"], "shell", {})
        step = self.store.owner_command(view["session_id"], "human_input", {"text": fixture.SMS_CODE})
        self.store._volatile.clear()                                  # the web service restarted in between
        self.runner.pump()
        self.assertEqual(self.store.find_step(step["id"])[1]["blocker"], "empty_input")
        self.assertEqual(self.status(view), "waiting_human")

    def test_takeover_finishes_a_login_and_hands_the_page_back(self):
        self.gate.save_entry({**self.entry, "login": ""})             # no saved login for this site
        view = self.open("/account")
        self.assertEqual((view["status"], view["wait_reason"]), ("waiting_human", "login_required"))
        sid = view["session_id"]
        self.store.set_takeover(sid, True)
        self.assertEqual(so.pending_requests(self.store)[0]["kind"], "takeover")
        with self.assertRaises(HTTPException) as err:                 # the agent waits while the owner drives
            self.act(view, "back")
        self.assertEqual(err.exception.status_code, 409)
        snap = self.run_tool(sa.web_snapshot, {"session_id": sid})
        self.assertIn("owner is driving", " ".join(snap["hints"]))
        self.owner(sid, "takeover_click", x=200, y=110)               # the Email field
        self.owner(sid, "takeover_type", text=fixture.USERNAME)
        self.owner(sid, "takeover_click", x=200, y=210)               # the Password field
        typed = self.owner(sid, "takeover_type", text=fixture.PASSWORD)
        self.assertEqual(typed["status"], "done")
        self.owner(sid, "takeover_key", key="Enter")
        self.assertEqual(self.site.events, [{"event": "login", "ok": True}])
        self.assertEqual(self.status(view), "takeover")               # stays his until he gives it back
        with self.assertRaises(HTTPException):
            self.store.owner_command(sid, "takeover_key", {"key": "F12"})
        with self.assertRaises(HTTPException):
            self.store.owner_command(sid, "takeover_click", {"x": 5000, "y": 5})
        self.assertEqual(self.owner(sid, "takeover_scroll", dy=600)["status"], "done")
        self.assertEqual(self.owner(sid, "snapshot")["status"], "done")
        self.store.set_takeover(sid, False)
        self.assertEqual(self.status(view), "active")
        after = self.run_tool(sa.web_snapshot, {"session_id": sid, "refresh": True})
        self.assertEqual((after["status"], after["title"]), ("done", "Account"))
        self.assertEqual(self.act(after, "fill", "Note", value="after takeover")["status"], "done")
        stored = self.everything_stored()
        self.assertNotIn(fixture.PASSWORD, stored)
        self.assertNotIn(fixture.USERNAME, stored)                    # everything the owner types is a secret
        self.assertNotIn(fixture.PASSWORD, json.dumps(after))
        kinds = [(r["action"], r.get("value")) for r in self.store.audit_tail() if r["who"] == "owner"]
        self.assertIn(("takeover_type", "***"), kinds)
        self.assertIn(("takeover", None), kinds)
        self.assertIn(("resume", None), kinds)

    def test_takeover_may_pass_through_another_site_but_the_agent_may_not(self):
        view = self.open("/")
        sid = view["session_id"]
        self.store.set_takeover(sid, True)
        self.owner(sid, "takeover_click", x=200, y=610)               # the "Partner site" link, off the allowlist
        self.assertEqual(self.pw.page.url, "https://other.example/landing")
        self.store.set_takeover(sid, False)
        out = self.run_tool(sa.web_snapshot, {"session_id": sid, "refresh": True})
        self.assertEqual(out["url"], "https://other.example/landing")
        route = fb.FakeRoute(fb.FakeRequest("https://third.example/", "GET"))
        self.pw.contexts[-1].route_handler(route)                     # back with the agent: the guard is strict again
        self.assertTrue(route.aborted)

    def test_save_login_goes_to_the_vault_only(self):
        self.site.signed_in = True
        view = self.open("/account")
        sid = view["session_id"]
        self.store.set_takeover(sid, True)
        step = self.owner(sid, "save_login")
        self.assertEqual((step["status"], step["saved"]), ("done", True))
        self.assertEqual(self.vault.states[("fixture", "main")]["cookies"][0]["name"], "fos_fixture")
        self.assertNotIn("signed-in-7f3a", self.everything_stored())
        self.gate.save_entry({**self.entry, "login": ""})
        self.store.set_takeover(sid, False)
        doc = self.store.get(sid)
        doc["session"]["login"] = ""
        self.store._write(doc)
        with self.assertRaises(HTTPException) as err:
            self.store.owner_command(sid, "save_login", {})
        self.assertEqual(err.exception.status_code, 409)

    def test_resume_tells_the_agent_to_go_on_from_a_page_that_still_shows_a_widget(self):
        view = self.open("/captcha")
        self.assertEqual(self.status(view), "waiting_human")
        with self.assertRaises(HTTPException):                        # nothing to give back from an active session
            self.store.set_takeover("ws_" + "0" * 16, False)
        self.store.set_takeover(view["session_id"], False)            # "all good, continue"
        out = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "refresh": True})
        self.assertEqual(out["status"], "done")
        waiting = self.act(out, "click", "Continue")                  # same page: no bounce back to the owner
        self.assertEqual(waiting["status"], "done")

    def test_takeover_waits_for_a_pending_decision(self):
        self.site.signed_in = True
        view = self.open("/account")
        self.act(view, "click", "Delete account")
        with self.assertRaises(HTTPException) as err:
            self.store.set_takeover(view["session_id"], True)
        self.assertIn("confirm or reject", err.exception.detail)


class RoutesTest(OwnerHarness):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        self.role = "owner"
        self.app = FastAPI()
        so.install_routes(self.app, store=self.store, gate=self.gate, identity=lambda r: {"role": self.role})

    def call(self, method, path, params=None, body=None):
        from starlette.requests import Request
        route = next(r for r in self.app.routes if getattr(r, "path", "") == path and method in r.methods)
        raw = json.dumps(body or {}).encode()

        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}
        request = Request({"type": "http", "method": method, "path": path, "query_string": b"", "headers": []}, receive)
        result = route.endpoint(**(params or {}), request=request)
        return asyncio.run(result) if asyncio.iscoroutine(result) else result

    def test_every_route_is_owner_only(self):
        self.role = "viewer"
        seen = 0
        for route in self.app.routes:
            path = getattr(route, "path", "")
            if not path.startswith("/api/factory/surfer/owner/"):
                continue
            seen += 1
            params = {n: "x" for n in ("session_id", "step_id", "asset_id") if "{" + n + "}" in path}
            with self.assertRaises(HTTPException) as err:
                self.call(next(iter(route.methods)), path, params)
            self.assertEqual(err.exception.status_code, 403, path)
        self.assertEqual(seen, 9)

    def test_owner_flow_through_the_routes(self):
        self.site.sms_step = True
        view = self.open("/login")
        sid = view["session_id"]
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        self.act(view, "click", "Sign in")
        data = self.call("GET", "/api/factory/surfer/owner/pending")
        self.assertEqual((data["pending"][0]["kind"], data["gate"]["enabled"], data["page"]),
                         ("human", True, "/static/surfer/index.html"))
        sent = self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/input", {"session_id": sid},
                         {"text": fixture.SMS_CODE, "submit": True})
        self.runner.pump()
        step = self.call("GET", "/api/factory/surfer/owner/steps/{step_id}", {"step_id": sent["step"]["id"]})
        self.assertEqual((step["step"]["status"], step["session_status"]), ("done", "active"))
        session = self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/takeover", {"session_id": sid},
                            {"on": True})["session"]
        self.assertEqual((session["status"], session["screen"]), ("takeover", sent["step"]["id"]))
        for kind, extra in (("click", {"x": 10, "y": 10}), ("type", {"text": "abc"}), ("key", {"key": "Tab"}),
                            ("scroll", {"dy": 300}), ("refresh", {}), ("save_login", {})):
            out = self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/control", {"session_id": sid},
                            {"kind": kind, **extra})
            self.runner.pump()
            self.assertEqual(self.store.find_step(out["step"]["id"])[1]["status"], "done", kind)
        with self.assertRaises(HTTPException) as err:
            self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/control", {"session_id": sid},
                      {"kind": "eval"})
        self.assertEqual(err.exception.status_code, 404)
        session = self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/takeover", {"session_id": sid},
                            {"on": False})["session"]
        self.assertEqual(session["status"], "active")
        text = json.dumps(self.call("GET", "/api/factory/surfer/owner/sessions/{session_id}", {"session_id": sid}))
        for secret in (fixture.PASSWORD, fixture.SMS_CODE, "signed-in-7f3a"):
            self.assertNotIn(secret, text)

    def test_approved_files_through_the_routes(self):
        body = {"name": "price.csv", "data_b64": base64.b64encode(b"a,b\n1,2\n").decode()}
        made = self.call("POST", "/api/factory/surfer/owner/uploads", None, body)
        asset = made["upload"]["id"]
        self.assertEqual([u["id"] for u in self.call("GET", "/api/factory/surfer/owner/uploads")["uploads"]], [asset])
        for bad in ({"name": "x.csv", "data_b64": "%%%"}, {"name": "x.sh", "data_b64": body["data_b64"]}):
            with self.assertRaises(HTTPException) as err:
                self.call("POST", "/api/factory/surfer/owner/uploads", None, bad)
            self.assertEqual(err.exception.status_code, 400)
        view = self.gate.save_entry({**self.entry, "classes": ["read", "navigate", "fill", "submit", "upload"]})
        view = self.open("/upload")
        self.assertEqual(self.act(view, "upload", "File", asset_id=asset)["status"], "done")
        self.act(view, "click", "Upload")
        self.assertEqual(self.site.events, [{"event": "upload", "name": "price.csv"}])
        self.call("POST", "/api/factory/surfer/owner/uploads/{asset_id}/delete", {"asset_id": asset})
        with self.assertRaises(HTTPException) as err:
            self.call("POST", "/api/factory/surfer/owner/uploads/{asset_id}/delete", {"asset_id": asset})
        self.assertEqual(err.exception.status_code, 404)


class PageTest(unittest.TestCase):
    html = PAGE.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]

    def tables(self):
        block = self.script.split("const T={", 1)[1].split("\n};", 1)[0]
        out = {}
        for lang in ("ru", "uk", "en"):
            body = re.search(r"^%s:\{(.*?)\}(?:,\n|$)" % lang, block, re.S | re.M).group(1)
            out[lang] = dict(re.findall(r'(\w+):"((?:[^"\\]|\\.)*)"', body))
        return out

    def test_three_languages_have_the_same_keys_and_placeholders(self):
        tables = self.tables()
        self.assertGreater(len(tables["en"]), 90)
        for lang in ("ru", "uk"):
            self.assertEqual(set(tables[lang]), set(tables["en"]), lang)
            for key, value in tables["en"].items():
                self.assertEqual(sorted(re.findall(r"\{(\w+)\}", value)),
                                 sorted(re.findall(r"\{(\w+)\}", tables[lang][key])), key)
        self.assertFalse([k for k, v in tables["ru"].items() if re.search(r"[іїєґІЇЄҐ]", v)])
        self.assertFalse([k for k, v in tables["uk"].items() if re.search(r"[ыэъёЫЭЪЁ]", v)])
        for lang in ("ru", "uk"):
            same = [k for k, v in tables[lang].items() if v == tables["en"][k] and re.search(r"[a-z]{4}", v)]
            self.assertEqual(same, [], lang)

    def test_every_key_the_page_uses_exists(self):
        keys = set(self.tables()["en"])
        used = set(re.findall(r'tr\("(\w+)"[,)]', self.script)) | set(re.findall(r'data-t="(\w+)"', self.html))
        self.assertEqual(used - keys, set())
        from browser_runner import action_policy
        for name in list(action_policy.REASONS):
            self.assertIn("r_" + name, keys)
        for name in so.WAITS:
            self.assertIn("w_" + name, keys)
        for name in action_policy.ACTION_CLASSES:
            self.assertIn("c_" + name, keys)
        for name in so.ACTIONS:
            self.assertIn("a_" + name, keys)
        for status in sa.OPEN_STATUSES + ("closed",):
            self.assertIn("st_" + status, keys)

    def test_page_text_from_sites_is_never_markup(self):
        # Labels, titles and URLs come from arbitrary sites: the page builds DOM nodes, it never parses HTML.
        for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval("):
            self.assertNotIn(banned, self.script, banned)
        self.assertIn("createTextNode", self.script)
        self.assertIn('rel:"noopener"', self.script)
        self.assertEqual(self.html.count("<script>"), 1)
        self.assertIn('name="robots" content="noindex"', self.html)

    def test_inline_script_parses(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required")
            self.skipTest("node is not installed")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as handle:
            handle.write(self.script)
        self.addCleanup(os.unlink, handle.name)
        done = subprocess.run([node, "--check", handle.name], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def test_page_calls_only_routes_that_exist(self):
        import app
        paths = {getattr(r, "path", "") for r in app.app.routes}
        for suffix in ("/policy", "/policy/allow", "/policy/allow/{entry_id}/delete", "/policy/pause", "/sessions",
                       "/sessions/{session_id}", "/sessions/{session_id}/stop", "/sessions/{session_id}/takeover",
                       "/sessions/{session_id}/input", "/sessions/{session_id}/control", "/steps/{step_id}/screenshot",
                       "/steps/{step_id}/{decision}", "/uploads", "/uploads/{asset_id}/delete", "/audit", "/pending"):
            self.assertIn("/api/factory/surfer/owner" + suffix, paths, suffix)
        called = set(re.findall(r'api\("(/[a-z/]+)', self.script))
        self.assertTrue(called <= {"/policy", "/policy/pause", "/policy/allow", "/policy/allow/", "/sessions",
                                   "/sessions/", "/steps/", "/uploads", "/uploads/", "/audit"}, called)


if __name__ == "__main__":
    unittest.main()
