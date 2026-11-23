"""T-720 Surfer action sessions: store, tools, worker protocol and the executor, offline (browser double, fake HTTP)."""
import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-surfer-actions-"))

from fastapi import HTTPException  # noqa: E402

import surfer_actions as sa  # noqa: E402
import surfer_fake_browser as fb  # noqa: E402
import surfer_fixture_site as fixture  # noqa: E402
from autopilot import browser_actions, relay_tasks  # noqa: E402
from browser_runner import action_policy as policy  # noqa: E402

ALL = ["read", "navigate", "fill", "submit", "upload"]
LOGIN = "fixture/main"


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class OpenGate:
    """A gate double with a fixed allowlist (the real gate is T-721)."""

    loopback = False

    def __init__(self, allow=None):
        self._allow = allow if allow is not None else [
            {"pattern": "shop.example", "classes": list(ALL), "enabled": True, "login": LOGIN}]
        self.secrets = {f"vault:{LOGIN}#username": fixture.USERNAME, f"vault:{LOGIN}#password": fixture.PASSWORD}
        self.states, self.uploads, self.counts = {}, {}, {"session": 0, "step": 0}

    def status(self):
        return {"enabled": True, "reason": ""}

    def require(self, lane):
        if not lane:
            raise HTTPException(403, "lane required")

    def allow(self):
        return self._allow

    def count(self, kind):
        self.counts[kind] += 1

    def secret(self, value_from):
        return self.secrets.get(value_from, "")

    def storage_state(self, login):
        return self.states.get(login)

    def save_storage_state(self, login, state):
        self.states[login] = state
        return True

    def upload(self, asset_id):
        return self.uploads.get(asset_id)

    def has_login_secret(self, login):
        return f"vault:{login}#password" in self.secrets


class Response:
    def __init__(self, data=None, code=200, content=b""):
        self._data, self.status_code, self.content = data, code, content

    def json(self):
        return self._data


class Wire:
    """The worker's HTTP client wired straight to the store (what the routes do)."""

    def __init__(self, store, gate):
        self.store, self.gate, self.down = store, gate, False
        self.seen = []

    def post(self, url, headers, json, timeout):
        if self.down:
            raise ConnectionError("down")
        assert headers["Authorization"] == "Bearer tok"
        path = url.split("factory.example", 1)[1]
        self.seen.append((path, json))
        try:
            if path.endswith("/actions/claim"):
                return Response(self.store.worker_claim(json.get("live") or "", self.gate))
            step_id = path.split("/")[-2]
            return Response({"ok": True, "status": self.store.worker_result(step_id, json, self.gate)["status"]})
        except HTTPException as exc:
            return Response({"detail": exc.detail}, exc.status_code)

    def get(self, url, headers, timeout):
        step_id = url.split("/")[-2]
        _, step = self.store.find_step(step_id)
        info = self.gate.upload(step["asset_id"])
        return Response(content=pathlib.Path(info["path"]).read_bytes())


class Proxy:
    url = "http://127.0.0.1:1"

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = pathlib.Path(self.tmp.name)
        self.clock = Clock()
        self.store = sa.ActionStore(self.dir, clock=self.clock)
        self.gate = OpenGate()
        self.pw = fb.FakePlaywright()
        self.site = self.pw.site
        self.wire = Wire(self.store, self.gate)
        self.runner = browser_actions.ActionRunner(http=self.wire, start_playwright=self.pw, proxy_factory=Proxy,
                                                   clock=self.clock)
        p = mock.patch.object(relay_tasks, "endpoint", return_value=("https://factory.example", "tok"))
        p.start()
        self.addCleanup(p.stop)
        quiet = mock.patch.object(browser_actions, "log", lambda _message: None)
        quiet.start()
        self.addCleanup(quiet.stop)
        self.addCleanup(self.runner.close)

    # the tool waits for the worker; here every wait tick lets the worker run one pass
    async def _tick(self, _seconds):
        self.runner.pump()
        self.clock.t += 1

    def run_tool(self, fn, args, lane="claude"):
        return asyncio.run(fn(self.store, self.gate, args, lane, sleep=self._tick, clock=self.clock))

    def open(self, path="/", lane="claude", **extra):
        return self.run_tool(sa.web_open, {"url": fb.ORIGIN + path, **extra}, lane)

    def act(self, view, action, name=None, lane="claude", **extra):
        args = {"session_id": view["session_id"], "action": action, **extra}
        if name is not None:
            args["ref"] = self.ref(view, name)
        return self.run_tool(sa.web_act, args, lane)

    @staticmethod
    def ref(view, name):
        return next(e["ref"] for e in view["elements"] if e["name"] == name)

    def everything_stored(self):
        """Every byte the server kept: session files, snapshots, the audit log."""
        return "\n".join(p.read_text(encoding="utf-8", errors="replace")
                         for p in (self.dir / "surfer_actions").rglob("*") if p.is_file() and p.suffix != ".png")


class GateAndIdentityTest(Harness):
    def test_engine_ships_closed(self):
        with self.assertRaises(HTTPException) as err:
            asyncio.run(sa.call_tool("web_open", {"url": fb.ORIGIN + "/"}, store=self.store, gate=sa.ClosedGate(),
                                     lane="claude"))
        self.assertEqual(err.exception.status_code, 503)
        self.assertEqual(self.store.list(), [])

    def test_shared_mcp_token_may_not_act(self):
        for tool in sa.TOOL_NAMES:
            with self.assertRaises(HTTPException) as err:
                asyncio.run(sa.call_tool(tool, {"url": fb.ORIGIN + "/", "session_id": "ws_" + "0" * 16},
                                         store=self.store, gate=self.gate, lane=""))
            self.assertEqual(err.exception.status_code, 403, tool)
        self.assertEqual(self.store.list(), [])

    def test_open_outside_the_allowlist_is_refused_and_logged(self):
        for url in ("https://other.example/", "https://evil-shop.example/", "https://shop.example.evil.io/"):
            with self.assertRaises(HTTPException) as err:
                self.run_tool(sa.web_open, {"url": url})
            self.assertEqual(err.exception.status_code, 403, url)
        with self.assertRaises(HTTPException):                       # not https, private hosts: the read rules apply
            self.run_tool(sa.web_open, {"url": "http://shop.example/"})
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.pw.launches, 0)
        self.assertEqual(self.store.audit_tail()[0]["blocker"], "off_allowlist")

    def test_disabled_entry_and_foreign_login_are_refused(self):
        self.gate._allow[0]["enabled"] = False
        with self.assertRaises(HTTPException):
            self.open()
        self.gate._allow[0]["enabled"] = True
        with self.assertRaises(HTTPException) as err:
            self.open(session="github/main")
        self.assertEqual(err.exception.status_code, 403)


class SessionFlowTest(Harness):
    def test_fill_and_submit_on_an_allowed_site(self):
        view = self.open("/wizard")
        self.assertEqual((view["status"], view["title"]), ("done", "Form step 1"))
        self.assertEqual([e["name"] for e in view["elements"]], ["Full name", "Plan", "Next"])
        self.assertEqual(self.act(view, "fill", "Full name", value="Andrii")["status"], "done")
        self.assertEqual(self.act(view, "select", "Plan", value="Pro")["status"], "done")
        view = self.act(view, "click", "Next")
        self.assertEqual((view["status"], view["title"]), ("done", "Form step 2"))
        self.act(view, "check", "I agree", value=True)
        self.act(view, "fill", "Comment", value="hello")
        view = self.act(view, "click", "Save")
        self.assertEqual(view["title"], "Done")
        self.assertEqual(self.site.events, [{"event": "wizard", "name": "Andrii", "plan": "pro", "agree": "yes",
                                             "comment": "hello"}])
        audit = self.store.audit_tail()
        self.assertEqual([r["action"] for r in reversed(audit)],
                         ["open", "open", "fill", "select", "click", "check", "fill", "click"])
        row = next(r for r in audit if r.get("element") == "Full name")
        self.assertEqual((row["who"], row["lane"], row["value"], row["result"], row["url"]),
                         ("claude", "claude", "Andrii", "done", fb.ORIGIN + "/wizard"))
        self.assertTrue(row["screenshot"].startswith("wa_"))
        self.assertTrue(self.store.screenshot(row["screenshot"]).is_file())
        self.assertEqual(self.gate.counts, {"session": 1, "step": 6})

    def test_sensitive_steps_wait_for_the_owner(self):
        self.site.signed_in = True
        view = self.open("/account")
        waiting = self.act(view, "click", "Delete account")
        self.assertEqual(waiting["status"], "needs_owner_confirmation")
        self.assertEqual(waiting["preview"]["reasons"], ["delete"])
        self.assertEqual(self.site.events, [])                       # nothing reached the site
        with self.assertRaises(HTTPException) as err:                # no second step while one waits
            self.act(view, "click", "Pay now")
        self.assertEqual(err.exception.status_code, 409)
        self.store.decide(waiting["step_id"], confirm=False)
        seen = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "step_id": waiting["step_id"]})
        self.assertEqual((seen["status"], seen["blocker"]), ("rejected", "rejected_by_owner"))
        self.assertEqual(self.site.events, [])
        pay = self.act(view, "click", "Pay now")
        self.assertEqual((pay["status"], pay["preview"]["reasons"]), ("needs_owner_confirmation", ["payment"]))
        self.store.decide(pay["step_id"], confirm=True)
        seen = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "step_id": pay["step_id"],
                                               "refresh": False})
        self.assertEqual(seen["status"], "running")
        self.runner.pump()
        seen = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "step_id": pay["step_id"]})
        self.assertEqual((seen["status"], seen["title"]), ("done", "Done"))
        self.assertEqual(self.site.events, [{"event": "pay"}])
        results = [r["result"] for r in self.store.audit_tail() if r.get("element") in ("Delete account", "Pay now")]
        self.assertEqual(set(results), {"needs_owner_confirmation", "rejected", "confirmed", "done"})
        with self.assertRaises(HTTPException):                       # a decided step cannot be decided again
            self.store.decide(pay["step_id"], confirm=True)

    def test_worker_reviews_a_selector_step_itself(self):
        self.site.signed_in = True
        view = self.open("/account")
        out = self.run_tool(sa.web_act, {"session_id": view["session_id"], "action": "click",
                                         "selector": "button.btn-danger"})
        self.assertEqual((out["status"], out["preview"]["element"], out["preview"]["reasons"]),
                         ("needs_owner_confirmation", "Delete account", ["delete"]))
        self.assertEqual(self.site.events, [])
        self.store.decide(out["step_id"], confirm=True)
        self.runner.pump()
        self.assertEqual(self.site.events, [{"event": "account_delete"}])

    def test_confirmed_step_is_bound_to_the_element_the_owner_saw(self):
        self.site.signed_in = True
        view = self.open("/account")
        waiting = self.act(view, "click", "Delete account")
        self.pw.page.elements[0]["name"] = "Delete everything"       # the page changed under the same ref
        self.store.decide(waiting["step_id"], confirm=True)
        self.runner.pump()
        _, step = self.store.find_step(waiting["step_id"])
        self.assertEqual((step["status"], step["blocker"]), ("failed", "stale_ref"))
        self.assertEqual(self.site.events, [])

    def test_leaving_the_allowlist_needs_the_owner_and_is_stopped_in_the_browser(self):
        view = self.open("/")
        out = self.act(view, "click", "Partner site")
        self.assertEqual((out["status"], out["preview"]["reasons"]), ("needs_owner_confirmation", ["leaves_allowlist"]))
        self.assertEqual(self.pw.page.url, fb.ORIGIN + "/")
        self.store.decide(out["step_id"], confirm=True)
        self.runner.pump()
        self.assertEqual(self.pw.page.url, "https://other.example/landing")
        # even with a confirmed step the network guard decides: a navigation the owner never saw is aborted
        route = fb.FakeRoute(fb.FakeRequest("https://third.example/x", "GET"))
        self.pw.contexts[-1].route_handler(route)
        self.assertTrue(route.aborted)
        with self.assertRaises(HTTPException) as err:
            self.run_tool(sa.web_open, {"url": "ftp://shop.example/", "session_id": view["session_id"]})
        self.assertEqual(err.exception.status_code, 400)
        out = self.run_tool(sa.web_open, {"url": "https://third.example/", "session_id": view["session_id"]})
        self.assertEqual(out["status"], "needs_owner_confirmation")

    def test_stale_ref_and_bad_arguments(self):
        view = self.open("/wizard")
        self.act(view, "fill", "Full name", value="A")
        moved = self.act(view, "click", "Next")
        with self.assertRaises(HTTPException) as err:                # e9 is not on the new page
            self.run_tool(sa.web_act, {"session_id": view["session_id"], "action": "fill", "ref": "e9", "value": "x"})
        self.assertEqual(err.exception.status_code, 409)
        for bad in ({"action": "eval"}, {"action": "goto"}, {"action": "click", "ref": "x1"},
                    {"action": "click", "selector": "a{b}"}, {"action": "press", "key": "F5"},
                    {"action": "fill", "ref": self.ref(moved, "Comment"), "value": "x", "value_from": "vault:a/b#password"},
                    {"action": "fill", "ref": self.ref(moved, "Comment"), "value_from": "env:SECRET"},
                    {"action": "upload", "ref": self.ref(moved, "Comment"), "asset_id": "su_none"},
                    {"action": "fill", "ref": self.ref(moved, "I agree"), "value": "x"}):
            with self.assertRaises(HTTPException, msg=bad):
                self.run_tool(sa.web_act, {"session_id": view["session_id"], **bad})
        self.assertEqual(self.site.events, [])

    def test_captcha_means_waiting_human(self):
        view = self.open("/captcha")
        self.assertEqual((view["status"], view["wait_reason"]), ("waiting_human", "captcha"))
        self.assertIn("never solves", " ".join(view["hints"]))
        with self.assertRaises(HTTPException) as err:
            self.act(view, "click", "Continue")
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(self.site.events, [])

    def test_upload_only_owner_approved_files(self):
        path = self.dir / "approved.txt"
        path.write_text("hello upload")
        self.gate.uploads["su_1"] = {"id": "su_1", "name": "approved.txt", "path": str(path)}
        view = self.open("/upload")
        with self.assertRaises(HTTPException) as err:
            self.act(view, "upload", "File", asset_id="su_other")
        self.assertEqual(err.exception.status_code, 404)
        self.assertEqual(self.act(view, "upload", "File", asset_id="su_1")["status"], "done")
        self.act(view, "click", "Upload")
        self.assertEqual(self.site.events, [{"event": "upload", "name": "approved.txt"}])

    def test_snapshot_paging_filter_and_other_actions(self):
        view = self.open("/")
        snap = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "filter": "form",
                                               "max_chars": 200})
        self.assertEqual([e["name"] for e in snap["elements"]], ["Start the form"])
        self.assertEqual(snap["elements"][0]["href"], "/wizard")     # same-origin links are shortened
        self.assertEqual(self.act(view, "scroll", value="down")["status"], "done")
        self.assertEqual(self.pw.page.scrolled, 700)
        self.assertEqual(self.act(view, "wait_for", value="Fixture site")["status"], "done")
        self.assertEqual(self.act(view, "press", key="Tab")["status"], "done")
        moved = self.act(view, "click", "Start the form")
        self.assertEqual(moved["title"], "Form step 1")
        self.assertEqual(self.act(view, "back")["title"], "Fixture home")


class SecretsTest(Harness):
    def test_login_by_vault_reference_never_shows_the_password(self):
        view = self.open("/login")
        self.assertIn("vault:fixture/main#password", " ".join(view["hints"]))
        password = next(e for e in view["elements"] if e["name"] == "Password")
        self.assertTrue(password["secret"])
        self.assertNotIn("value", password)
        with self.assertRaises(HTTPException) as err:                # a typed secret is refused outright
            self.act(view, "fill", "Password", value="hunter2-typed")
        self.assertIn("secret_field_needs_vault_reference", err.exception.detail)
        with self.assertRaises(HTTPException):                       # the password never goes into a text field
            self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#password")
        with self.assertRaises(HTTPException):                       # nor a login the owner did not bind here
            self.act(view, "fill", "Password", value_from="vault:github/main#password")
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        filled = self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        self.assertEqual(next(e for e in filled["elements"] if e["name"] == "Password").get("filled"), True)
        done = self.act(view, "click", "Sign in")
        self.assertEqual(done["title"], "Account")
        self.assertEqual(self.site.events, [{"event": "login", "ok": True}])
        stored = self.everything_stored()
        self.assertNotIn(fixture.PASSWORD, stored)
        self.assertNotIn("hunter2-typed", stored)
        self.assertNotIn(fixture.PASSWORD, json.dumps([filled, done]))
        self.assertNotIn(fixture.PASSWORD, json.dumps(self.wire.seen[-1]))
        row = next(r for r in self.store.audit_tail() if r.get("element") == "Password" and r["result"] == "done")
        self.assertEqual(row["value"], f"vault:{LOGIN}#password")
        refused = next(r for r in self.store.audit_tail() if r.get("blocker") == "secret_field_needs_vault_reference")
        self.assertEqual(refused.get("value"), "***")

    def test_a_page_that_reveals_the_password_is_scrubbed(self):
        view = self.open("/login")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        self.pw.page.elements[1].update(type="text", secret=False, _shown=True)     # a "show password" toggle
        snap = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "refresh": True})
        self.assertNotIn(fixture.PASSWORD, json.dumps(snap))
        self.assertIn("***", snap["text"])
        self.assertNotIn(fixture.PASSWORD, self.everything_stored())

    def test_saved_login_is_restored_and_never_leaves_the_worker_channel(self):
        self.gate.states[LOGIN] = {"cookies": [{"name": "sid", "value": "cookie-secret-123"}], "origins": []}
        view = self.open("/account")                                 # signed in through the restored state
        self.assertEqual(view["title"], "Account")
        self.assertEqual(self.pw.contexts[-1].kwargs["storage_state"], self.gate.states[LOGIN])
        self.assertNotIn("cookie-secret-123", self.everything_stored())
        self.assertNotIn("cookie-secret-123", json.dumps(view))


class LifecycleTest(Harness):
    def test_one_session_at_a_time_and_lanes_are_isolated(self):
        view = self.open("/")
        with self.assertRaises(HTTPException) as err:
            self.open("/", lane="chatgpt")
        self.assertEqual(err.exception.status_code, 409)
        self.assertNotIn(view["session_id"], err.exception.detail)   # another lane does not learn the id
        with self.assertRaises(HTTPException) as err:
            self.open("/wizard")
        self.assertIn(view["session_id"], err.exception.detail)
        for fn, args in ((sa.web_snapshot, {}), (sa.web_act, {"action": "back"})):
            with self.assertRaises(HTTPException) as err:
                self.run_tool(fn, {"session_id": view["session_id"], **args}, lane="chatgpt")
            self.assertEqual(err.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            sa.web_close(self.store, self.gate, {"session_id": view["session_id"]}, "chatgpt")
        closed = sa.web_close(self.store, self.gate, {"session_id": view["session_id"]}, "claude")
        self.assertEqual(closed["status"], "closed")
        self.runner.pump()                                           # the worker is told to close the page
        self.assertEqual((self.runner.live, self.pw.contexts[-1].closed, self.pw.stops), ("", True, 1))
        self.assertEqual(self.open("/", lane="chatgpt")["status"], "done")

    def test_idle_and_lifetime_timeouts_close_the_page(self):
        view = self.open("/")
        self.clock.t += sa.IDLE_SECONDS + 5
        self.runner.pump()
        self.assertEqual(self.runner.live, "")
        doc = self.store.get(view["session_id"])
        self.assertEqual((doc["session"]["status"], doc["session"]["close_reason"]), ("closed", "idle_timeout"))
        out = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"]})
        self.assertEqual(out["status"], "closed")
        with self.assertRaises(HTTPException):
            self.act(view, "back")

    def test_waiting_for_the_owner_gets_more_time_but_not_forever(self):
        self.site.signed_in = True
        view = self.open("/account")
        waiting = self.act(view, "click", "Delete account")
        self.clock.t += sa.IDLE_SECONDS + 60
        self.assertEqual(self.store.get(view["session_id"])["session"]["status"], "needs_owner_confirmation")
        self.clock.t += sa.OWNER_WAIT_SECONDS
        self.assertEqual(self.store.get(view["session_id"])["session"]["close_reason"], "owner_did_not_answer")
        with self.assertRaises(HTTPException):
            self.store.decide(waiting["step_id"], confirm=True)
        self.assertEqual(self.site.events, [])

    def test_a_restarted_worker_loses_the_page_and_says_so(self):
        view = self.open("/")
        self.runner.close()                                          # the worker process restarted
        self.runner.pump()
        doc = self.store.get(view["session_id"])
        self.assertEqual((doc["session"]["status"], doc["session"]["close_reason"]), ("closed", "worker_lost"))
        out = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"]})
        self.assertIn("Open a new session", " ".join(out["hints"]))

    def test_worker_closes_the_page_when_factoryos_is_unreachable(self):
        self.open("/")
        self.wire.down = True
        self.assertEqual(self.runner.pump(), "error")
        self.assertTrue(self.runner.live)
        self.clock.t += browser_actions.UNREACHABLE_CLOSE_SECONDS + 1
        self.runner.pump()
        self.assertEqual(self.runner.live, "")

    def test_a_stuck_command_is_killed_and_reported_and_the_page_freed(self):
        # Live run 2026-11-23: a click never returned and the worker served nothing else. Here the "browser" blocks
        # until the deadline kill, as Playwright does when its driver dies; then any further call would block forever.
        import threading
        view = self.open("/")
        killed = threading.Event()
        calls = []

        def stuck(_page_call, *args, **kwargs):
            calls.append("evaluate")
            if killed.is_set():
                raise AssertionError("a browser call after the kill would wait forever on a dead driver")
            killed.wait(10)
            raise RuntimeError("Connection closed while reading from the driver")

        self.runner.deadline_seconds = 0.2
        self.runner.kill = killed.set
        page = self.runner.session.page
        with mock.patch.object(type(page), "evaluate", stuck, create=True), \
                mock.patch.object(type(page), "screenshot", lambda *a, **k: (_ for _ in ()).throw(AssertionError("shot")),
                                  create=True):
            out = self.act(view, "click", "Start the form")
        self.assertTrue(killed.is_set())
        self.assertEqual(calls, ["evaluate"])                     # nothing after the kill
        step = self.store.find_step(out["step_id"])[1]
        self.assertEqual((step["status"], step.get("blocker")), ("failed", "worker_timeout"))
        self.assertEqual(self.runner.live, "")                    # the page is gone, the slot is free
        self.assertEqual(self.pw.contexts[-1].closed, False)      # no close call into the dead driver
        self.runner.pump()
        doc = self.store.get(view["session_id"])
        self.assertEqual((doc["session"]["status"], doc["session"]["close_reason"]), ("closed", "worker_lost"))
        self.assertEqual(self.open("/")["status"], "done")        # a new session gets a fresh browser

    def test_read_tasks_borrow_the_live_browser(self):
        self.assertIsNone(self.runner.borrowed_factory())
        self.open("/")
        with self.runner.borrowed_factory()() as playwright:
            browser = playwright.chromium.launch(headless=True, proxy={"server": "x"})
            context = browser.new_context(accept_downloads=False)
            browser.close()
        self.assertEqual((self.pw.launches, self.pw.stops), (1, 0))  # no second Chromium, the live one stays open
        self.assertIsNot(context, self.pw.contexts[0])
        self.assertNotIn("storage_state", context.kwargs)            # a read context is anonymous

    def test_step_limit_and_unreported_command(self):
        view = self.open("/")
        doc = self.store.get(view["session_id"])
        doc["session"]["steps_total"] = sa.MAX_STEPS_PER_SESSION
        self.store._write(doc)
        with self.assertRaises(HTTPException):
            self.act(view, "back")
        self.assertEqual(self.store.get(view["session_id"])["session"]["close_reason"], "step_limit")
        self.runner.pump()
        view = self.open("/")
        step = self.store.add_step(view["session_id"], {"kind": "act", "action": "back"}, by="claude")
        self.assertEqual(self.store.worker_claim(view["session_id"], self.gate)["command"]["id"], step["id"])
        self.assertIsNone(self.store.worker_claim(view["session_id"], self.gate)["command"])   # leased
        self.clock.t += sa.LEASE_SECONDS + 1
        self.store.worker_claim(view["session_id"], self.gate)
        self.assertEqual(self.store.find_step(step["id"])[1]["blocker"], "worker_did_not_report")
        with self.assertRaises(HTTPException):                       # a late report is not accepted
            self.store.worker_result(step["id"], {"status": "done"}, self.gate)


class PolicyUnitTest(unittest.TestCase):
    ALLOW = [{"pattern": "shop.example", "classes": ["read", "navigate", "fill"], "enabled": True, "login": LOGIN},
             {"pattern": "pay.shop.example", "classes": ["read"], "enabled": True}]

    def review(self, action, el=None, url="https://shop.example/x", **kw):
        return policy.review(action, el, url, self.ALLOW, **kw)

    def test_patterns(self):
        self.assertEqual(policy.clean_pattern("https://OLX.ua/account"), "olx.ua")
        self.assertEqual(policy.clean_pattern("*.render.com"), "render.com")
        for bad in ("com", "com.ua", "github.io", "localhost", "10.0.0.1", "a b.com", "", "onrender.com"):
            self.assertEqual(policy.clean_pattern(bad), "", bad)
        self.assertEqual(policy.match(self.ALLOW, "pay.shop.example")["classes"], ["read"])     # most specific wins
        self.assertIsNone(policy.match(self.ALLOW, "notshop.example"))
        self.assertFalse(policy.url_allowed(self.ALLOW, "http://shop.example/"))
        self.assertTrue(policy.url_allowed(self.ALLOW, "https://www.shop.example/a?b=1"))

    def test_classes_the_owner_did_not_switch_on_need_him(self):
        submit = {"kind": "button", "name": "Save", "submit": True, "form": {"action": "https://shop.example/save"}}
        self.assertEqual(self.review("click", submit)["reasons"], ["class_not_allowed"])
        self.assertEqual(self.review("fill", {"kind": "input", "name": "City"}, has_value=True)["decision"], "allow")
        self.assertEqual(self.review("fill", {"kind": "input", "name": "City"}, url="https://pay.shop.example/",
                                     has_value=True)["reasons"], ["class_not_allowed"])
        self.assertEqual(self.review("scroll", url="https://pay.shop.example/")["decision"], "allow")

    def test_sensitive_words_in_three_languages(self):
        cases = {"payment": ["Pay now", "Оплатить", "Купить", "Придбати", "Checkout", "Subscribe"],
                 "delete": ["Delete", "Удалить объявление", "Видалити", "Remove", "Deactivate"],
                 "security": ["Change password", "Сменить пароль", "Змінити пароль", "Log out", "Generate API key"],
                 "messaging": ["Send message", "Отправить", "Надіслати", "Reply", "Написать продавцу"],
                 "publish": ["Publish", "Опубликовать", "Опублікувати", "Manual Deploy", "Post"]}
        for reason, labels in cases.items():
            for label in labels:
                got = self.review("click", {"kind": "button", "name": label})
                self.assertIn(reason, got["reasons"], label)
                self.assertEqual(got["decision"], "confirm", label)
        for label in ("Next", "Search", "Open menu", "Details", "Show more", "Далее", "Messages", "Posts"):
            self.assertEqual(self.review("click", {"kind": "button", "name": label})["reasons"], [] if label not in
                             ("Next", "Далее") else ["class_not_allowed"], label)
        # a link to a section is reading; a button inside it is not
        self.assertEqual(self.review("click", {"kind": "link", "name": "Billing",
                                               "href": "https://shop.example/billing"})["decision"], "allow")
        self.assertIn("payment", self.review("click", {"kind": "button", "name": "Billing"})["reasons"])
        self.assertIn("delete", self.review("click", {"kind": "link", "name": "x",
                                                      "href": "https://shop.example/items/5/delete"})["reasons"])
        self.assertIn("unlabeled_control", self.review("click", {"kind": "button", "name": ""})["reasons"])
        self.assertIn("delete", self.review("click", {"kind": "button", "name": "", "hint": "icon btn-danger"})["reasons"])
        self.assertIn("payment", self.review("fill", {"kind": "input", "name": "Card", "autocomplete": "cc-number",
                                                      "secret": True}, value_from="")["reasons"])
        self.assertIn("security", self.review("fill", {"kind": "input", "type": "password", "secret": True,
                                                       "autocomplete": "new-password"},
                                              value_from=f"vault:{LOGIN}#password")["reasons"])

    def test_scrub_and_fingerprint(self):
        self.assertEqual(policy.scrub({"a": ["x secret-1 y", {"b": "secret-1"}], "n": 5}, ["secret-1", "ab"]),
                         {"a": ["x *** y", {"b": "***"}], "n": 5})
        one = policy.fingerprint({"kind": "button", "name": "Delete  account", "form": {"action": "https://a.b/x?t=1"}})
        self.assertEqual(one, policy.fingerprint({"kind": "button", "name": "Delete account",
                                                  "form": {"action": "https://a.b/x?t=2"}}))
        self.assertNotEqual(one, policy.fingerprint({"kind": "button", "name": "Delete everything"}))


class RoutesTest(Harness):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        self.app = FastAPI()
        sa.install_routes(self.app, store=self.store, gate_fn=lambda: self.gate,
                          identity=lambda r: {"role": r.headers.get("x-role", "")},
                          authorize_worker=lambda r: r.headers.get("authorization") == "Bearer w",
                          lane_identity=lambda r: r.headers.get("x-lane", ""))

    def call(self, method, path, params=None, body=None, **headers):
        from starlette.requests import Request
        route = next(r for r in self.app.routes if getattr(r, "path", "") == path and method in r.methods)
        raw = json.dumps(body or {}).encode()

        async def receive():
            return {"type": "http.request", "body": raw, "more_body": False}
        request = Request({"type": "http", "method": method, "path": path, "query_string": b"",
                           "headers": [(k.replace("_", "-").encode(), v.encode()) for k, v in headers.items()]}, receive)
        result = route.endpoint(**(params or {}), request=request)
        return asyncio.run(result) if asyncio.iscoroutine(result) else result

    def test_auth_boundaries(self):
        view = self.open("/")
        sid, step = view["session_id"], view["step_id"]
        for method, path, params in (
                ("GET", "/api/factory/surfer/owner/sessions", None),
                ("GET", "/api/factory/surfer/owner/audit", None),
                ("GET", "/api/factory/surfer/owner/steps/{step_id}/screenshot", {"step_id": step}),
                ("POST", "/api/factory/surfer/owner/sessions/{session_id}/stop", {"session_id": sid})):
            for role in ("", "viewer", "guest"):
                with self.assertRaises(HTTPException) as err:
                    self.call(method, path, params, x_role=role)
                self.assertEqual(err.exception.status_code, 403, path)
        for path, params in (("/api/factory/browser/worker/actions/claim", None),
                             ("/api/factory/browser/worker/actions/{step_id}/result", {"step_id": step})):
            with self.assertRaises(HTTPException) as err:
                self.call("POST", path, params, x_role="owner")       # an owner session is not a worker
            self.assertEqual(err.exception.status_code, 401)
        with self.assertRaises(HTTPException) as err:
            self.call("GET", "/api/factory/browser/worker/actions/{step_id}/file", {"step_id": step}, x_role="owner")
        self.assertEqual(err.exception.status_code, 401)
        with self.assertRaises(HTTPException) as err:
            self.call("POST", "/api/factory/surfer/agent/{tool}", {"tool": "web_snapshot"}, x_role="owner")
        self.assertEqual(err.exception.status_code, 401)
        with self.assertRaises(HTTPException) as err:
            self.call("POST", "/api/factory/surfer/agent/{tool}", {"tool": "shell"}, x_lane="claude")
        self.assertEqual(err.exception.status_code, 404)

    def test_owner_sees_sessions_without_values_and_can_stop(self):
        view = self.open("/login")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        data = self.call("GET", "/api/factory/surfer/owner/sessions", x_role="owner")
        session = data["sessions"][0]
        self.assertEqual((session["id"], session["lane"], session["status"]), (view["session_id"], "claude", "active"))
        self.assertEqual(session["steps"][-1]["value_from"], f"vault:{LOGIN}#password")
        self.assertNotIn(fixture.PASSWORD, json.dumps(data))
        shot = self.call("GET", "/api/factory/surfer/owner/steps/{step_id}/screenshot",
                         {"step_id": session["steps"][-1]["id"]}, x_role="owner")
        self.assertEqual(shot.media_type, "image/png")
        agent = self.call("POST", "/api/factory/surfer/agent/{tool}", {"tool": "web_snapshot"},
                          body={"session_id": view["session_id"], "refresh": False}, x_lane="claude")
        self.assertEqual(agent["title"], "Sign in")
        self.assertNotIn("screenshot", json.dumps(agent))            # screenshots are for the owner only
        stopped = self.call("POST", "/api/factory/surfer/owner/sessions/{session_id}/stop",
                            {"session_id": view["session_id"]}, x_role="owner")
        self.assertEqual(stopped["session"]["close_reason"], "stopped_by_owner")
        claim = self.call("POST", "/api/factory/browser/worker/actions/claim",
                          body={"live": view["session_id"]}, authorization="Bearer w")
        self.assertEqual(claim, {"command": None, "close": True})

    def test_worker_result_is_validated(self):
        view = self.open("/")
        step = self.store.add_step(view["session_id"], {"kind": "snapshot", "action": "snapshot"}, by="claude")
        self.store.worker_claim(view["session_id"], self.gate)
        for body in ({"status": "published"}, {"status": "done", "screenshot_b64": "!!"},
                     {"status": "done", "screenshot_b64": "aGVsbG8="}):
            with self.assertRaises(HTTPException) as err:
                self.store.worker_result(step["id"], body, self.gate)
            self.assertEqual(err.exception.status_code, 400)
        huge = {"status": "done", "snapshot": {"url": "https://user:pw@shop.example/a#frag", "title": "t" * 900,
                                               "text": "x" * 90_000, "elements": [{"ref": "e1", "name": "n" * 900,
                                                                                    "secret": True, "value": "leak"},
                                                                                   {"ref": "bad ref"}]}}
        self.store.worker_result(step["id"], huge, self.gate)
        snap = self.store.snapshot(view["session_id"])
        self.assertEqual((snap["url"], len(snap["title"]), len(snap["text"])), ("https://shop.example/a", 300, 30_000))
        self.assertEqual(snap["elements"], [{"ref": "e1", "name": "n" * 160, "secret": True}])


class McpEndpointTest(unittest.TestCase):
    def test_tools_are_listed_and_off_by_default_in_the_real_app(self):
        from test_agent_workspace import LANE_TOKENS, SHARED, mcp_call
        import app as factory
        _, listed = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, SHARED)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue(sa.TOOL_NAMES <= names and {"web_read", "web_search", "web_task"} <= names)

        def call(token):
            _, out = mcp_call(factory, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "web_open", "arguments": {"url": "https://example.com/"}}}, token)
            return out["result"].get("isError"), out["result"]["content"][0]["text"]
        error, text = call(SHARED)
        self.assertTrue(error)
        self.assertIn("shared MCP token may not act", text)
        error, text = call(LANE_TOKENS["claude"])
        self.assertTrue(error)
        self.assertIn("FACTORY_SURFER_ACTIONS_ENABLED", text)      # off until the owner sets the flag (T-721)
        self.assertEqual(factory.SURFER_ACTIONS.list(), [])


class CodePromptTest(unittest.TestCase):
    def test_code_wording_needs_a_code_box_not_any_input(self):
        from browser_runner.action_session import code_prompt_on
        readme = "Login walls, captchas and SMS codes go to the owner. Enter the code below to continue."
        # First live session 2026-11-23: GitHub's README mentioned SMS codes and the page has a "Go to file" box.
        self.assertFalse(code_prompt_on(readme, [{"kind": "input", "name": "Go to file", "type": "text"},
                                                 {"kind": "input", "name": "Search", "type": "search"}]))
        self.assertTrue(code_prompt_on("We sent a verification code. Enter the code.",
                                       [{"kind": "input", "name": "Verification code", "type": "text"}]))
        self.assertTrue(code_prompt_on("Введите код из СМС", [{"kind": "input", "name": "Код", "type": "text"}]))
        self.assertTrue(code_prompt_on("", [{"kind": "input", "name": "x", "autocomplete": "one-time-code"}]))
        self.assertFalse(code_prompt_on("enter the code", [{"kind": "input", "name": "Code", "type": "password"}]))


if __name__ == "__main__":
    unittest.main()
