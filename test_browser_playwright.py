"""T-560-C guard regression: no APIs, credentials or external browser required.

Optional real Chromium loopback fixture:
  RUN_BROWSER_FIXTURE=1 python test_browser_playwright.py
The default CI suite uses a deterministic browser double and never downloads
Chromium or calls third-party services.
"""
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import tempfile
import threading
import unittest

from browser_runner.core import BrowserActionPlan, canonical_payload_hash
from browser_runner.playwright_executor import (
    BrowserRuntimePolicy, run_playwright, validate_runtime,
)


def plan(*steps, action_class="draft", **extras):
    return BrowserActionPlan(
        plan_id="plan-fixture", workspace_id="workspace-one",
        provider="generic", account_binding_id="account-one",
        session_ref="session://workspace-one/account-one",
        action_class=action_class, steps=steps, **extras,
    )


class FakeRequest:
    def __init__(self, url, method):
        self.url, self.method = url, method


class FakeRoute:
    def __init__(self, request):
        self.request = request
        self.aborted = False

    def abort(self):
        self.aborted = True

    def continue_(self):
        pass


class FakeLocator:
    def __init__(self, page, selector):
        self.page, self.selector = page, selector

    def count(self):
        return int(bool(self.page.challenge and (
            (self.page.challenge == "2fa" and 'one-time-code' in self.selector) or
            (self.page.challenge == "captcha" and 'recaptcha' in self.selector)
        )))

    def evaluate(self, _script):
        return self.selector not in ("#danger",)

    def click(self, timeout):
        if self.selector == "#trigger-write":
            self.page.send_request(self.page.url.replace("/editor", "/save"), "POST")
        elif self.selector == "#trigger-offsite":
            self.page.send_request("https://evil.example/page", "GET")
        self.page.state["clicked"] = True

    def fill(self, value, timeout):
        self.page.state[self.selector] = value

    def select_option(self, *, value, timeout):
        self.page.state[self.selector] = value

    def set_input_files(self, path, timeout):
        self.page.state["uploaded"] = Path(path).name

    def wait_for(self, *, state, timeout):
        assert state == "visible"

    def inner_text(self, timeout):
        return "Synthetic fixture heading"


class FakePage:
    def __init__(self, context):
        self.context, self.url = context, "about:blank"
        self.state, self.challenge = {}, ""

    def set_default_timeout(self, _timeout):
        pass

    def send_request(self, url, method="GET"):
        route = FakeRoute(FakeRequest(url, method))
        self.context.route_handler(route)
        if route.aborted:
            raise RuntimeError("route blocked")

    def goto(self, url, *, wait_until, timeout):
        self.send_request(url)
        self.url = url

    def locator(self, selector):
        return FakeLocator(self, selector)

    def screenshot(self, *, path, full_page, timeout):
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\nfixture")


class FakeContext:
    def __init__(self):
        self.route_handler = None
        self.websocket_guard = False
        self.page = FakePage(self)

    def route(self, _pattern, callback):
        self.route_handler = callback

    def route_web_socket(self, _pattern, _callback):
        self.websocket_guard = True

    def new_page(self):
        assert self.route_handler and self.websocket_guard
        return self.page

    def close(self):
        pass


class FakeBrowser:
    def __init__(self):
        self.context = FakeContext()

    def new_context(self, **kwargs):
        assert kwargs["service_workers"] == "block"
        assert kwargs["accept_downloads"] is False
        return self.context

    def close(self):
        pass


class FakeChromium:
    def __init__(self):
        self.browser = FakeBrowser()

    def launch(self, **_):
        return self.browser


class FakePlaywright:
    def __init__(self):
        self.chromium = FakeChromium()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class SafeBrowserRegression(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = "https://fixture.example"
        self.policy = BrowserRuntimePolicy(
            allowed_origins=(self.origin,), artifact_root=self.root / "artifacts",
            upload_root=self.root / "uploads",
        )
        (self.root / "uploads").mkdir()

    def run_fake(self, p):
        return run_playwright(p, policy=self.policy, playwright_factory=FakePlaywright)

    def test_read_draft_click_upload_extract_and_screenshot(self):
        (self.root / "uploads" / "demo.txt").write_text("safe")
        result = self.run_fake(plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "fill", "selector": "#caption", "value": "draft content"},
            {"type": "select", "selector": "#topic", "value": "research"},
            {"type": "click", "selector": "#tab"},
            {"type": "upload", "selector": "#media", "path": "demo.txt"},
            {"type": "wait_for", "selector": "#preview"},
            {"type": "extract", "selector": "#preview"},
            {"type": "screenshot"},
        ))
        self.assertEqual((result.status, result.completed_steps), ("done", 8))
        self.assertEqual(result.final_url, self.origin)
        self.assertEqual(result.external_receipt, "")
        self.assertEqual(len(result.artifacts), 1)
        self.assertEqual(len(result.action_log), 8)
        self.assertNotIn("draft content", str(result.action_log))
        self.assertIn("text_sha256", result.action_log[6])
        image = self.root / "artifacts" / result.artifacts[0].split("/")[-1]
        self.assertTrue(image.exists())
        self.assertEqual(image.stat().st_mode & 0o777, 0o600)

    def test_publication_rejected_even_with_self_claimed_approval(self):
        candidate = plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "submit", "selector": "#save"},
            action_class="publish",
        )
        signed = replace(candidate, approval_snapshot_id="fake",
                         approved_payload_hash=canonical_payload_hash(candidate))
        result = self.run_fake(signed)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.completed_steps, 0)

    def test_offsite_and_private_targets_block_before_launch(self):
        for url in (
            "https://evil.example/editor", "http://169.254.169.254/latest/meta-data",
            "file:///etc/passwd", "http://127.0.0.1:8000",
            "https://fixture.example:444/editor",
            "https://user:password@fixture.example/editor",
        ):
            result = self.run_fake(plan({"type": "navigate", "url": url}))
            self.assertEqual(result.status, "blocked", url)
            self.assertEqual(result.completed_steps, 0)

    def test_block_write_methods_even_if_click_looks_harmless(self):
        r = self.run_fake(plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "click", "selector": "#trigger-write"},
        ))
        self.assertEqual(r.status, "blocked")
        self.assertEqual(r.completed_steps, 1)
        self.assertEqual(r.blocker_reason, "browser_write_request_blocked")

    def test_block_offsite_request_triggered_by_click(self):
        r = self.run_fake(plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "click", "selector": "#trigger-offsite"},
        ))
        self.assertEqual(r.status, "blocked")
        self.assertEqual(r.blocker_reason, "off_allowlist_network_request")

    def test_unsafe_click_and_unsafe_url_path(self):
        r = self.run_fake(plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "click", "selector": "#danger"},
        ))
        self.assertEqual(r.status, "blocked")
        self.assertEqual(r.blocker_reason, "unsafe_click_target")
        r = self.run_fake(plan({"type": "navigate", "url": self.origin + "/publish"}))
        self.assertEqual(r.status, "blocked")

    def test_upload_requires_trusted_staging_area(self):
        outside = self.root / "outside.txt"
        outside.write_text("private")
        (self.root / "uploads" / "link.txt").symlink_to(outside)
        for filename in ("../outside.txt", "link.txt", "/etc/passwd"):
            result = self.run_fake(plan(
                {"type": "navigate", "url": self.origin + "/editor"},
                {"type": "upload", "selector": "#file", "path": filename},
            ))
            self.assertEqual(result.status, "blocked", filename)

    def test_challenge_stops_and_returns_bound_checkpoint(self):
        def challenge_factory():
            fake = FakePlaywright()
            fake.chromium.browser.context.page.challenge = "2fa"
            return fake
        p = plan(
            {"type": "navigate", "url": self.origin + "/editor"},
            {"type": "fill", "selector": "#title", "value": "no"},
        )
        result = run_playwright(p, policy=self.policy, playwright_factory=challenge_factory)
        self.assertEqual(result.status, "waiting_human")
        self.assertEqual(result.completed_steps, 1)
        self.assertEqual(result.action_log[-1]["payload_hash"], canonical_payload_hash(p))
        self.assertEqual(result.action_log[-1]["reason"], "2fa")

    def test_no_hidden_command_parameters_or_retry(self):
        for p in (
            plan({"type": "navigate", "url": self.origin + "/editor"},
                 {"type": "fill", "selector": "#x", "value": "text", "shell": "cat /etc/passwd"}),
            plan({"type": "navigate", "url": self.origin + "/editor"}, max_retries=1),
            plan({"type": "navigate", "url": self.origin + "/editor"},
                 {"type": "submit", "selector": "#submit"}),
        ):
            self.assertEqual(self.run_fake(p).status, "blocked")

    def test_loopback_only_with_explicit_trusted_fixture_flag(self):
        local = replace(self.policy, allowed_origins=("http://127.0.0.1:9301",),
                        allow_loopback_fixture=True)
        self.assertEqual(
            run_playwright(plan({"type": "navigate", "url": "http://127.0.0.1:9301/editor"}),
                           policy=local, playwright_factory=FakePlaywright).status,
            "done",
        )


class FixtureHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = b"""<!doctype html><html><body>
        <h1 id="heading">Local Chromium fixture</h1>
        <input id="caption" type="text"><select id="topic"><option value="science">Science</option></select>
        <input id="upload" type="file"><button id="tab" onclick="document.querySelector('#result').textContent='Ready'">Preview</button>
        <div id="result">Not ready</div>
        </body></html>"""
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


@unittest.skipUnless(os.environ.get("RUN_BROWSER_FIXTURE") == "1", "opt-in local Chromium fixture only")
class OptionalRealChromiumFixture(unittest.TestCase):
    def test_actual_chromium_page_without_any_external_requests(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), FixtureHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as root:
                origin = f"http://127.0.0.1:{server.server_port}"
                policy = BrowserRuntimePolicy(
                    allowed_origins=(origin,), artifact_root=Path(root) / "artifacts",
                    allow_loopback_fixture=True,
                    browser_executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_PATH") or None,
                )
                result = run_playwright(plan(
                    {"type": "navigate", "url": origin + "/editor"},
                    {"type": "fill", "selector": "#caption", "value": "safe local draft"},
                    {"type": "select", "selector": "#topic", "value": "science"},
                    {"type": "click", "selector": "#tab"},
                    {"type": "extract", "selector": "#result"},
                    {"type": "screenshot"},
                ), policy=policy)
                self.assertEqual(result.status, "done", result.blocker_reason)
                self.assertEqual(result.completed_steps, 6)
                self.assertEqual(len(result.artifacts), 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
