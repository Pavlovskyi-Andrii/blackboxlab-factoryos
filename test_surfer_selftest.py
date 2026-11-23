"""T-724 Surfer self-test: one scenario on the fixture site that proves the safety properties end to end.

    python test_surfer_selftest.py                         # CI: the browser double (surfer_fake_browser)
    RUN_BROWSER_FIXTURE=1 python test_surfer_selftest.py   # the same scenario in real Chromium on a loopback site

The scenario goes through the real store, gate, tools, worker runner and executor. What it proves:
1. a site outside the allowlist is refused before any browser starts;
2. an allowlisted fill + submit runs (two-step form, file upload);
3. sensitive steps (delete, payment) wait for the owner; rejected ones never reach the site;
4. secrets (vault password, SMS code, text typed in a takeover, session cookie) are in no snapshot, view or log;
5. login by vault reference, then the owner types the SMS code; a takeover continues the session;
6. a captcha-like wall is ``waiting_human``; nothing is solved;
7. a saved recipe replays without AI with a new parameter.
"""
import asyncio
import json
import os
import pathlib
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-surfer-selftest-"))

from fastapi import HTTPException  # noqa: E402

import surfer_actions as sa  # noqa: E402
import surfer_fake_browser as fb  # noqa: E402
import surfer_fixture_site as fixture  # noqa: E402
import surfer_policy as sp  # noqa: E402
import surfer_recipes as sr  # noqa: E402
import test_surfer_actions as base  # noqa: E402
from autopilot import browser_actions, relay_tasks  # noqa: E402
from test_surfer_policy import LOGIN, Vault  # noqa: E402

REAL = os.environ.get("RUN_BROWSER_FIXTURE") == "1"
CLASSES = ["read", "navigate", "fill", "submit", "upload"]
OWNER_TEXT = "typed-by-the-owner-771"


class World:
    """Store + gate + worker around one site. Subclasses choose the browser."""

    def __init__(self, tmp: pathlib.Path):
        self.dir = tmp
        self.store = sa.ActionStore(tmp)
        self.vault = Vault()
        self.gate = sp.PolicyGate(tmp, env={sp.FLAG_ENV: "1"}, vault=self.vault, loopback=self.loopback)
        self.recipes = sr.RecipeStore(tmp)
        self.wire = base.Wire(self.store, self.gate)
        self.views = []

    def allow_site(self, host: str) -> None:
        data = self.gate._load()             # the loopback host is not a pattern an owner could type; test only
        data["allow"] = [{"id": "al_selftest0001", "pattern": host, "classes": list(CLASSES), "enabled": True,
                          "login": LOGIN, "note": "self-test"}]
        self.gate._save(data)

    def tool(self, fn, args, lane="claude"):
        view = self._run(fn(self.store, self.gate, args, lane, **self.wait_kw()))
        self.views.append(view)
        return view

    def act(self, view, action, name=None, **extra):
        args = {"session_id": view["session_id"], "action": action, **extra}
        if name is not None:
            args["ref"] = next(e["ref"] for e in view["elements"] if e["name"] == name)
        return self.tool(sa.web_act, args)

    def goto(self, view, path):
        return self.tool(sa.web_open, {"url": self.origin + path, "session_id": view["session_id"]})

    def step(self, step_id):
        """Wait until the worker reported this step."""
        for _ in range(600):
            self.pump()
            found = self.store.find_step(step_id)[1]
            if found["status"] in sa.STEP_FINAL:
                return found
            time.sleep(self.tick)
        raise AssertionError("the worker did not report " + step_id)

    def owner(self, session_id, kind, **payload):
        return self.step(self.store.owner_command(session_id, kind, payload)["id"])

    def stored(self) -> bytes:
        """Every byte the server kept under its data directory: state, snapshots, logs, recipes, screenshots, uploads."""
        return b"\n".join(p.read_bytes() for p in sorted(self.dir.rglob("*")) if p.is_file())


class FakeWorld(World):
    loopback, tick, origin = False, 0, fb.ORIGIN

    def __init__(self, tmp):
        super().__init__(tmp)
        self.pw = fb.FakePlaywright()
        self.site = self.pw.site
        self.runner = browser_actions.ActionRunner(http=self.wire, start_playwright=self.pw, proxy_factory=base.Proxy)
        self.allow_site("shop.example")

    def wait_kw(self):
        async def tick(_seconds):
            self.runner.pump()
        return {"sleep": tick}

    def _run(self, coro):
        return asyncio.run(coro)

    def pump(self):
        self.runner.pump()

    def launches(self):
        return self.pw.launches

    def point(self, name):
        index = next(i for i, e in enumerate(self.pw.page.elements) if e["name"] == name)
        return 200.0, 100.0 * (index + 1) + 10

    def close(self):
        self.runner.close()


class RealWorld(World):
    """Real Chromium on the loopback fixture site; the worker runs on its own thread, as on EC2."""

    loopback, tick = True, 0.1

    def __init__(self, tmp):
        super().__init__(tmp)
        self.site = fixture.FixtureSite().__enter__()
        self.origin = self.site.url
        self.runner = browser_actions.ActionRunner(http=self.wire, loopback=True)
        self.allow_site("127.0.0.1")
        self.jobs, self.stop, self.started = queue.Queue(), threading.Event(), 0
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def _loop(self):
        while not self.stop.is_set():
            try:
                self.jobs.get_nowait()()
            except queue.Empty:
                pass
            if self.runner.pump() != "ran":
                time.sleep(0.1)
        self.runner.close()

    def on_worker(self, fn):
        done, box = threading.Event(), {}

        def job():
            try:
                box["value"] = fn()
            except BaseException as exc:          # report the real error instead of a 60 s timeout
                box["error"] = exc
            finally:
                done.set()
        self.jobs.put(job)
        assert done.wait(60), "worker thread is stuck"
        if "error" in box:
            raise box["error"]
        return box["value"]

    def wait_kw(self):
        return {}

    def _run(self, coro):
        return asyncio.run(coro)

    def pump(self):
        pass

    def launches(self):
        return 1 if self.runner.live else 0

    def point(self, name):
        def find():
            page = self.runner.session.page
            ref = next(e["ref"] for e in self.runner.session.snapshot()["elements"] if e["name"] == name)
            box = page.locator('[data-fos-ref="%s"]' % ref).bounding_box()
            return box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        return self.on_worker(find)

    def close(self):
        self.stop.set()
        self.thread.join(30)
        self.site.__exit__(None, None, None)


class SelfTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worker_log = []                       # what the worker would print to its journal on EC2
        for target, value in ((relay_tasks, ("endpoint", mock.Mock(return_value=("https://factory.example", "tok")))),
                              (browser_actions, ("log", self.worker_log.append))):
            patch = mock.patch.object(target, *value)
            patch.start()
            self.addCleanup(patch.stop)
        self.w = (RealWorld if REAL else FakeWorld)(pathlib.Path(self.tmp.name))
        self.addCleanup(self.w.close)

    def events(self, name):
        return [e for e in self.w.site.events if e["event"] == name]

    def test_scenario(self):
        w = self.w
        w.site.sms_step = True

        # 1. outside the allowlist: refused at the door, no browser
        for url in ("https://not-allowed.example/", "https://shop.example.evil.example/"):
            with self.assertRaises(HTTPException) as err:
                w.tool(sa.web_open, {"url": url})
            self.assertEqual(err.exception.status_code, 403)
        self.assertEqual((w.launches(), w.store.list()), (0, []))
        with self.assertRaises(HTTPException) as err:                 # and the shared MCP token may not act at all
            asyncio.run(sa.call_tool("web_open", {"url": w.origin + "/"}, store=w.store, gate=w.gate, lane=""))
        self.assertEqual(err.exception.status_code, 403)

        # 5a. login by vault reference; the password is never typed, shown or stored
        view = w.tool(sa.web_open, {"url": w.origin + "/login"})
        self.assertEqual((view["status"], view["title"]), ("done", "Sign in"))
        sid = view["session_id"]
        with self.assertRaises(HTTPException) as err:
            w.act(view, "fill", "Password", value="guess-123456")
        self.assertIn("secret_field_needs_vault_reference", err.exception.detail)
        w.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        filled = w.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        password = next(e for e in filled["elements"] if e["name"] == "Password")
        self.assertEqual((password.get("secret"), password.get("filled"), "value" in password), (True, True, False))
        code = w.act(view, "click", "Sign in")
        self.assertEqual((code["status"], code["wait_reason"]), ("waiting_human", "2fa"))
        with self.assertRaises(HTTPException):                        # the agent cannot touch the code step
            w.act(code, "fill", "Code", value="000000")
        # 5b. the owner types the code he received
        self.assertEqual(w.owner(sid, "human_input", text=fixture.SMS_CODE, submit=True)["status"], "done")
        account = w.tool(sa.web_snapshot, {"session_id": sid, "refresh": True})
        self.assertEqual((account["status"], account["title"]), ("done", "Account"))
        self.assertEqual(self.events("login") + self.events("code"),
                         [{"event": "login", "ok": True}, {"event": "code", "ok": True}])

        # 3. sensitive steps wait for the owner
        delete = w.act(account, "click", "Delete account")
        self.assertEqual((delete["status"], delete["preview"]["reasons"]), ("needs_owner_confirmation", ["delete"]))
        w.store.decide(delete["step_id"], confirm=False)
        pay = w.act(account, "click", "Pay now")
        self.assertEqual((pay["status"], pay["preview"]["reasons"]), ("needs_owner_confirmation", ["payment"]))
        self.assertEqual(self.events("account_delete") + self.events("pay"), [])
        w.store.decide(pay["step_id"], confirm=True)
        self.assertEqual(w.step(pay["step_id"])["status"], "done")
        self.assertEqual((self.events("account_delete"), len(self.events("pay"))), ([], 1))

        # 2. an allowlisted fill + submit runs: the two-step form
        form = w.goto(account, "/wizard")
        w.act(form, "fill", "Full name", value="Andrii")
        w.act(form, "select", "Plan", value="Pro")
        second = w.act(form, "click", "Next")
        self.assertEqual((second["status"], second["title"]), ("done", "Form step 2"))
        w.act(second, "check", "I agree", value=True)
        w.act(second, "fill", "Comment", value="from the self-test")
        self.assertEqual(w.act(second, "click", "Save")["status"], "done")
        self.assertEqual(self.events("wizard"), [{"event": "wizard", "name": "Andrii", "plan": "pro", "agree": "yes",
                                                  "comment": "from the self-test"}])
        #    ... and a file upload, only of a file the owner approved
        upload = w.goto(account, "/upload")
        with self.assertRaises(HTTPException):
            w.act(upload, "upload", "File", asset_id="su_000000000000")
        asset = w.gate.add_upload("price-list.txt", b"approved by the owner")
        self.assertEqual(w.act(upload, "upload", "File", asset_id=asset["id"])["status"], "done")
        w.act(upload, "click", "Upload")
        self.assertEqual(self.events("upload")[0]["name"], "price-list.txt")

        # 5c. takeover: the owner drives the page, then the agent continues in the same session
        back = w.goto(account, "/account")
        self.assertEqual(back["title"], "Account")                    # still signed in
        w.store.set_takeover(sid, True)
        with self.assertRaises(HTTPException):
            w.act(back, "fill", "Note", value="agent while the owner drives")
        x, y = w.point("Note")
        w.owner(sid, "takeover_click", x=x, y=y)
        w.owner(sid, "takeover_type", text=OWNER_TEXT)
        w.owner(sid, "takeover_key", key="Enter")
        self.assertEqual(self.events("account_note"), [{"event": "account_note", "note": OWNER_TEXT}])
        saved = w.owner(sid, "save_login")
        self.assertEqual(saved.get("saved"), True)
        self.assertTrue(w.vault.states[("fixture", "main")]["cookies"])
        w.store.set_takeover(sid, False)
        again = w.tool(sa.web_snapshot, {"session_id": sid, "refresh": True})
        self.assertEqual((again["status"], again["title"]), ("done", "Done"))

        # 6. a captcha-like wall: waiting_human, nothing is solved
        wall = w.goto(account, "/captcha")
        self.assertEqual((wall["status"], wall["wait_reason"]), ("waiting_human", "captcha"))
        with self.assertRaises(HTTPException):
            w.act(wall, "click", "Continue")
        self.assertEqual(self.events("captcha"), [])
        self.close_session(sid)

        # 7. a recipe: record, the owner saves it with a parameter, replay without AI
        w.site.sms_step = False
        rec = w.tool(sa.web_open, {"url": w.origin + "/wizard"})
        w.act(rec, "fill", "Full name", value="Recorded")
        mid = w.act(rec, "click", "Next")
        w.act(mid, "click", "Save")
        recipe = w.recipes.save(w.store.get(rec["session_id"]), "Wizard", {"2": "full_name"})
        self.close_session(rec["session_id"])
        run = w.recipes.start_run(recipe, "claude", "owner")
        run = w._run(sr.replay(w.store, w.gate, w.recipes, run, recipe, {"full_name": "Replayed"}, **w.wait_kw()))
        self.assertEqual((run["status"], run["reason"], run["at_step"]), ("done", "", len(recipe["steps"])))
        self.assertEqual(self.events("wizard")[-1]["name"], "Replayed")
        self.assertEqual(len(self.events("wizard")), 3)

        # 4. secrets are nowhere: not in what the server stored, not in what agents saw, not in the log
        stored = w.stored()
        seen = json.dumps(w.views) + json.dumps(w.store.audit_tail(1000)) + json.dumps(recipe)
        cookie = fixture.COOKIE.split("=", 1)[1]
        journal = "\n".join(self.worker_log)
        self.assertGreater(len(self.worker_log), 30)                  # the worker did log every command
        self.assertGreater(len(list((w.dir / "surfer_actions" / "shots").glob("wa_*"))), 20)   # screenshots are scanned too
        for secret in (fixture.PASSWORD, fixture.SMS_CODE, OWNER_TEXT, cookie, "guess-123456"):
            self.assertNotIn(secret.encode(), stored, secret)
            self.assertNotIn(secret, seen, secret)
            self.assertNotIn(secret, journal, secret)
        self.assertNotIn(b"storage_state", stored)
        self.assertNotIn(fixture.USERNAME, journal)
        audit = w.store.audit_tail(1000)
        self.assertEqual({r["value"] for r in audit if r.get("action") in ("human_input", "takeover_type")}, {"***"})
        self.assertTrue(all(r.get("who") for r in audit))
        self.assertGreater(len([r for r in audit if r.get("screenshot")]), 20)

    def close_session(self, session_id):
        closed = sa.web_close(self.w.store, self.w.gate, {"session_id": session_id}, "claude")
        self.assertEqual(closed["status"], "closed")
        for _ in range(300):
            self.w.pump()
            if not self.w.runner.live:
                return
            time.sleep(self.w.tick or 0.001)
        self.fail("the worker did not close the page")


@unittest.skipUnless(REAL, "real Chromium only (RUN_BROWSER_FIXTURE=1)")
class HungPageTest(unittest.TestCase):
    """Live run 2026-11-23: a click left the worker stuck; nothing else was served until the 15-min watchdog."""

    def test_a_stuck_command_is_killed_and_the_slot_is_free_again(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        log = []
        for target, value in ((relay_tasks, ("endpoint", mock.Mock(return_value=("https://factory.example", "tok")))),
                              (browser_actions, ("log", log.append))):
            patch = mock.patch.object(target, *value)
            patch.start()
            self.addCleanup(patch.stop)
        w = RealWorld(pathlib.Path(tmp.name))
        self.addCleanup(w.close)
        w.runner.deadline_seconds = 8
        view = w.tool(sa.web_open, {"url": w.origin + "/busy"})
        self.assertEqual(view["status"], "done")
        started = time.monotonic()
        stuck = w.tool(sa.web_act, {"session_id": view["session_id"], "action": "click",
                                    "ref": next(e["ref"] for e in view["elements"] if e["name"] == "Freeze")})
        step = w.store.find_step(stuck["step_id"])[1]
        for _ in range(300):
            if step["status"] in sa.STEP_FINAL:
                break
            time.sleep(0.1)
            step = w.store.find_step(stuck["step_id"])[1]
        self.assertEqual((step["status"], step.get("blocker")), ("failed", "worker_timeout"), log)
        self.assertLess(time.monotonic() - started, 40)
        self.assertTrue(any("killing the browser" in line for line in log), log)
        for _ in range(100):                                   # the next claim closes the dead session
            if w.store.get(view["session_id"])["session"]["status"] == "closed":
                break
            time.sleep(0.1)
        self.assertEqual(w.store.get(view["session_id"])["session"]["status"], "closed")
        again = w.tool(sa.web_open, {"url": w.origin + "/soft"})   # a fresh browser serves the next session
        self.assertEqual((again["status"], again["title"]), ("done", "Soft navigation"))


@unittest.skipUnless(REAL, "real Chromium only (RUN_BROWSER_FIXTURE=1)")
class SoftNavigationTest(unittest.TestCase):
    def test_link_click_waits_for_in_page_navigation(self):
        # Live session 2026-11-23: a click on GitHub's Issues tab returned the old page; the URL changed a moment later.
        from playwright.sync_api import sync_playwright
        from browser_runner.action_session import ActionSession
        with fixture.FixtureSite() as site, sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                context = browser.new_context()
                session = ActionSession(context.new_page(), context, loopback=True)
                policy = {"allow": [{"pattern": "127.0.0.1", "classes": ["read", "navigate"], "enabled": True}]}
                opened = session.execute({"kind": "open", "url": site.url + "/soft", "policy": policy})
                page = opened.get("snapshot") or opened
                ref = next(e["ref"] for e in page["elements"] if e.get("name") == "Next section")
                done = session.execute({"kind": "act", "action": "click", "ref": ref, "policy": policy})
                page = done.get("snapshot") or done
                self.assertEqual(done["status"], "done")
                self.assertTrue(page["url"].endswith("/soft/next"), page["url"])
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
