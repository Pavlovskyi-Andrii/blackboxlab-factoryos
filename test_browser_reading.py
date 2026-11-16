"""T-670 Surfer reading quality: main text + links (read_page), HTTP status, network-error codes, JS redirects,
anti-bot pages and invisible captchas. Offline by default (browser double from test_browser_playwright).

Real Chromium against local pages (no internet):
  RUN_BROWSER_FIXTURE=1 PLAYWRIGHT_CHROMIUM_PATH=/opt/pw-browsers/chromium-*/chrome-linux64/chrome \
      python test_browser_reading.py
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import pathlib
import tempfile
import threading
import time
import unittest

import test_browser_playwright as fx
from autopilot import browser_tasks as worker
from browser_runner.core import BrowserActionPlan
from browser_runner.playwright_executor import (
    PAGE_LINKS_LIMIT, BrowserRuntimePolicy, run_playwright,
)

ORIGIN = "https://docs.example"
LONG = "Readable paragraph about the API. " * 120


class Response:
    def __init__(self, status):
        self.status = status


class ReadPage(fx.FakePage):
    def __init__(self, context, *, status=200, data=None, title="Docs", goto_error="", redirect="", body_chars=0):
        super().__init__(context)
        self.status, self.data, self._title = status, data, title
        self.goto_error, self.redirect, self.body_chars = goto_error, redirect, body_chars
        self.waited = []

    def goto(self, url, *, wait_until, timeout):
        if self.goto_error:
            raise RuntimeError(self.goto_error)
        super().goto(url, wait_until=wait_until, timeout=timeout)
        if self.redirect:
            self.send_request(self.redirect)          # a script moves the main frame to another site
        return Response(self.status)

    def wait_for_load_state(self, state, *, timeout):
        self.waited.append((state, timeout))
        raise fx.PlaywrightTimeoutError("networkidle not reached")   # a chatty page: read it anyway

    def evaluate(self, script, *args):
        if "document.body" in script and "innerText" in script and "MAIN" not in script:
            return self.body_chars
        return self.data

    def title(self):
        return self._title


def browser(**page):
    def factory():
        pw = fx.FakePlaywright()
        context = pw.chromium.browser.context
        context.page = ReadPage(context, **page)
        factory.page = context.page
        return pw
    return factory


def read_plan(*middle):
    return worker.build_plan({"id": "bt_0123456789abcdef", "url": ORIGIN + "/guide", "selectors": list(middle)})


class ReadPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.policy = BrowserRuntimePolicy(allowed_origins=(ORIGIN,), artifact_root=Path(self.tmp.name) / "shots",
                                           allow_offsite_subresource_reads=True, return_extracted_text=True)

    def test_no_selectors_reads_main_text_title_and_links(self):
        self.assertEqual([dict(s)["type"] for s in read_plan().steps], ["navigate", "read_page", "screenshot"])
        self.assertEqual([dict(s)["type"] for s in read_plan("h1").steps], ["navigate", "extract", "screenshot"])
        links = [{"text": "Next", "url": ORIGIN + "/next"}, {"text": "bad", "url": "javascript:alert(1)"},
                 {"text": "http", "url": "http://docs.example/x"}, "junk"]
        links += [{"text": f"l{i}", "url": f"{ORIGIN}/p{i}"} for i in range(300)]
        factory = browser(data={"title": "Guide", "text": LONG, "links": links, "main": "article",
                                "description": "About"})
        result = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory)
        self.assertEqual(result.status, "done", result.blocker_reason)
        row = next(r for r in result.action_log if r["type"] == "read_page")
        self.assertEqual((row["title"], row["main"], row["description"]), ("Guide", "article", "About"))
        self.assertEqual(row["text"], LONG)                     # well past the 6000-char selector cap
        self.assertEqual(row["links"][0], {"text": "Next", "url": ORIGIN + "/next"})
        self.assertTrue(all(link["url"].startswith("https://") for link in row["links"]))
        self.assertEqual(len(row["links"]), PAGE_LINKS_LIMIT)
        self.assertEqual(factory.page.waited[0][0], "networkidle")
        nav = next(r for r in result.action_log if r["type"] == "navigate")
        self.assertEqual(nav["http_status"], 200)

    def test_read_page_is_only_for_read_tasks(self):
        plan = BrowserActionPlan(plan_id="p", workspace_id="w", provider="web", account_binding_id="a",
                                 session_ref="session://w/a", action_class="draft",
                                 steps=({"type": "navigate", "url": ORIGIN + "/"}, {"type": "read_page"}))
        result = run_playwright(plan, policy=self.policy, playwright_factory=browser(data={}))
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "read_page_is_read_only"))
        no_text = BrowserRuntimePolicy(allowed_origins=(ORIGIN,), artifact_root=Path(self.tmp.name) / "s2")
        result = run_playwright(read_plan(), policy=no_text,
                                playwright_factory=browser(data={"text": "secret page", "title": "t"}))
        row = next(r for r in result.action_log if r["type"] == "read_page")
        self.assertNotIn("text", row)                           # only length + hash unless the host asks for text
        self.assertEqual(row["text_chars"], len("secret page"))

    def test_worker_sends_page_status_and_main_text(self):
        public = lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", port))]
        task = {"id": "bt_0123456789abcdef", "url": ORIGIN + "/missing", "selectors": []}

        class NoProxy:
            url = "http://127.0.0.1:1"

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False
        factory = browser(status=404, data={"title": "Not found", "text": "Page not found", "links": [], "main": "body"})
        out = worker.execute(task, runner=lambda plan, *, policy: run_playwright(plan, policy=policy,
                                                                               playwright_factory=factory),
                             artifact_root=Path(self.tmp.name) / "w", resolve=public, proxy_factory=NoProxy)
        self.assertEqual((out["status"], out["http_status"]), ("done", 404))
        self.assertEqual(out["page"]["title"], "Not found")
        self.assertEqual(out["texts"], [{"selector": "(main content)", "text": "Page not found"}])

    def test_network_error_code_without_url_or_message(self):
        factory = browser(goto_error="Page.goto: net::ERR_NAME_NOT_RESOLVED at https://docs.example/guide?token=s3cret")
        result = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory)
        self.assertEqual((result.status, result.blocker_reason), ("failed", "net_err_name_not_resolved"))
        self.assertNotIn("s3cret", repr(result))

    def test_javascript_redirect_to_another_site_is_reported_without_query(self):
        factory = browser(data={}, redirect="https://moved.example/new/place?session=zq9secret#x")
        result = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "off_allowlist_network_request"))
        row = next(r for r in result.action_log if r["type"] == "redirect")
        self.assertEqual(row["url"], "https://moved.example/new/place")
        self.assertNotIn("zq9secret", repr(result))
        private = browser(data={}, redirect="https://10.0.0.5/admin")
        result = run_playwright(read_plan(), policy=self.policy, playwright_factory=private)
        self.assertFalse(any(r["type"] == "redirect" for r in result.action_log))

    def test_anti_bot_interstitial_waits_for_a_human(self):
        factory = browser(title="Just a moment...", data={"text": "Verifying", "title": "Just a moment..."})
        result = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory)
        self.assertEqual((result.status, result.blocker_reason), ("waiting_human", "bot_challenge"))

    def test_captcha_widget_on_a_readable_page_does_not_stop_a_read(self):
        class CaptchaPage(ReadPage):
            def locator(self, selector):
                loc = super().locator(selector)
                loc.count = lambda: int("recaptcha" in selector)
                return loc

        def factory_for(body_chars, action_class="read"):
            def factory():
                pw = fx.FakePlaywright()
                ctx = pw.chromium.browser.context
                ctx.page = CaptchaPage(ctx, data={"text": "x", "title": "t"}, body_chars=body_chars)
                return pw
            return factory
        readable = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory_for(5000))
        self.assertEqual(readable.status, "done", readable.blocker_reason)
        gate = run_playwright(read_plan(), policy=self.policy, playwright_factory=factory_for(40))
        self.assertEqual((gate.status, gate.blocker_reason), ("waiting_human", "captcha"))
        draft = BrowserActionPlan(plan_id="p", workspace_id="w", provider="web", account_binding_id="a",
                                  session_ref="session://w/a", action_class="draft",
                                  steps=({"type": "navigate", "url": ORIGIN + "/"}, {"type": "extract", "selector": "h1"}))
        result = run_playwright(draft, policy=self.policy, playwright_factory=factory_for(5000))
        self.assertEqual(result.status, "waiting_human")       # only read tasks get the text-length allowance


PAGES = {
    "/docs": """<!doctype html><html><head><title>Guide - Docs</title><meta name="description" content="How to use it">
<script>window.__x = 1</script></head><body>
<header><nav><a href="/home">Home</a> Language: English | Deutsch | Français</nav></header>
<div id="cookie-banner">We use cookies. Accept all cookies?</div>
<aside class="sidebar"><a href="/v1">Version 1</a><a href="/v2">Version 2</a></aside>
<main><article><h1>Using the API</h1><p>%s</p><p>See <a href="/next#part">the next chapter</a>.</p>
<table><tr><th>Code</th><th>Meaning</th></tr><tr><td>404</td><td>Not Found</td></tr></table></article></main>
<footer>Copyright footer text</footer></body></html>""" % ("The API reads pages. " * 200),
    "/spa": """<!doctype html><html><head><title>SPA</title></head><body><div id="root"></div><script>
fetch('/data').then(r => r.text()).then(t => { document.getElementById('root').innerHTML =
  '<main><h1>Rendered later</h1><p>' + t + '</p></main>'; });</script></body></html>""",
    "/invisible-captcha": """<!doctype html><html><head><title>Docs with a widget</title></head><body><main>
<h1>Real content</h1><p>%s</p></main><iframe src="/recaptcha/api2/anchor?size=invisible" width="0" height="0">
</iframe></body></html>""" % ("Text worth reading. " * 150),
    "/moment": """<!doctype html><html><head><title>Just a moment...</title></head><body>
<div id="challenge-running">Checking your browser</div></body></html>""",
}


class Fixture(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/data":
            time.sleep(0.6)
            body = ("Data from a slow API call. " * 30).encode()
        elif path in PAGES:
            body = PAGES[path].encode()
        elif path.startswith("/recaptcha/"):
            body = b"<html><body></body></html>"
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<html><head><title>404</title></head><body><h1>Not found</h1></body></html>")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@unittest.skipUnless(os.environ.get("RUN_BROWSER_FIXTURE") == "1", "opt-in local Chromium fixture only")
class RealChromiumReading(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.origin = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def read(self, path, selectors=()):
        with tempfile.TemporaryDirectory() as root:
            policy = BrowserRuntimePolicy(allowed_origins=(self.origin,), artifact_root=pathlib.Path(root),
                                          allow_loopback_fixture=True, return_extracted_text=True,
                                          browser_executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") or None)
            plan = worker.build_plan({"id": "bt_0123456789abcdef", "url": self.origin + path,
                                      "selectors": list(selectors)})
            return run_playwright(plan, policy=policy)

    def page_row(self, result):
        return next(r for r in result.action_log if r["type"] == "read_page")

    def test_main_text_without_menus_cookies_or_footer(self):
        result = self.read("/docs")
        self.assertEqual(result.status, "done", result.blocker_reason)
        row = self.page_row(result)
        self.assertTrue(row["text"].startswith("Using the API"), row["text"][:200])
        for junk in ("Deutsch", "Accept all cookies", "Version 2", "Copyright footer"):
            self.assertNotIn(junk, row["text"])
        self.assertIn("404\tNot Found", row["text"])             # tables keep their cells
        self.assertGreater(len(row["text"]), 4000)
        self.assertEqual((row["title"], row["description"], row["main"]), ("Guide - Docs", "How to use it", "article"))
        urls = [link["url"] for link in row["links"]]
        self.assertEqual(urls, [])                                # loopback http links are not https: never listed
        nav = next(r for r in result.action_log if r["type"] == "navigate")
        self.assertEqual(nav["http_status"], 200)

    def test_page_is_restored_after_reading(self):
        # The banner is hidden only while reading; the screenshot afterwards sees the page as the site made it.
        result = self.read("/docs", selectors=())
        self.assertEqual(result.status, "done")
        self.assertEqual(len(result.artifacts), 1)

    def test_javascript_rendered_content_is_waited_for(self):
        row = self.page_row(self.read("/spa"))
        self.assertIn("Rendered later", row["text"])
        self.assertIn("Data from a slow API call", row["text"])

    def test_http_404_is_reported(self):
        result = self.read("/nope")
        self.assertEqual(result.status, "done")
        self.assertEqual(next(r for r in result.action_log if r["type"] == "navigate")["http_status"], 404)

    def test_invisible_captcha_does_not_block_and_bot_page_does(self):
        self.assertEqual(self.read("/invisible-captcha").status, "done")
        moment = self.read("/moment")
        self.assertEqual((moment.status, moment.blocker_reason), ("waiting_human", "bot_challenge"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
