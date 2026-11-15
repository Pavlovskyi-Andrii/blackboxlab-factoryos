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

from browser_runner.core import BrowserActionPlan, PolicyError, canonical_payload_hash
from browser_runner.playwright_executor import (
    BrowserRuntimePolicy, run_playwright, validate_runtime,
)
from browser_runner.recipes import generic_form_recipe


def plan(*steps, action_class="draft", **extras):
    return BrowserActionPlan(
        plan_id="plan-fixture", workspace_id="workspace-one",
        provider="generic", account_binding_id="account-one",
        session_ref="session://workspace-one/account-one",
        action_class=action_class, steps=steps, **extras,
    )


# Same class name as playwright.sync_api.TimeoutError, which is not the builtin TimeoutError.
PlaywrightTimeoutError = type("TimeoutError", (Exception,), {})


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

    @property
    def first(self):
        return self

    def wait_for(self, *, state, timeout):
        assert state in ("visible", "attached")
        if self.selector == "#missing":
            raise PlaywrightTimeoutError("Timeout 8000ms exceeded")

    def inner_text(self, timeout):
        return "Synthetic fixture heading"

    def all_inner_texts(self):
        return ["First result", " ", "Second result"] if self.selector == ".many" else ["Synthetic fixture heading"]


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

    def test_read_missing_selector_does_not_fail_the_task(self):
        """Surfer: example.com has no <h1> any more (2026-11-15); that used to fail the whole task with no screenshot."""
        p = plan({"type": "navigate", "url": self.origin + "/page"}, {"type": "extract", "selector": "#missing"},
                 {"type": "extract", "selector": ".many"}, {"type": "screenshot"}, action_class="read")
        policy = replace(self.policy, return_extracted_text=True)
        result = run_playwright(p, policy=policy, playwright_factory=FakePlaywright)
        self.assertEqual(result.status, "done")
        self.assertEqual(result.completed_steps, 4)
        extracts = [row for row in result.action_log if row["type"] == "extract"]
        self.assertEqual(extracts[0], {**extracts[0], "missing": True, "text": "", "text_chars": 0})
        self.assertEqual(extracts[1]["text"], "First result\nSecond result")
        self.assertNotIn("missing", extracts[1])
        self.assertEqual(len(result.artifacts), 1)

    def test_non_read_extract_of_missing_selector_still_fails(self):
        p = plan({"type": "navigate", "url": self.origin + "/page"}, {"type": "wait_for", "selector": "#missing"})
        result = self.run_fake(p)
        self.assertEqual((result.status, result.completed_steps), ("failed", 1))

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


def not_launched():
    raise AssertionError("browser must not launch for a rejected plan")


class GenericFormRecipeRegression(unittest.TestCase):
    """DONE fixture: generic allowlisted form flow on the deterministic browser."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.origin = "https://forms.fixture.example"
        (self.root / "uploads").mkdir()
        (self.root / "uploads" / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        self.policy = BrowserRuntimePolicy(
            allowed_origins=(self.origin,), artifact_root=self.root / "artifacts",
            upload_root=self.root / "uploads",
        )

    def recipe(self, **overrides):
        args = dict(
            plan_id="recipe-1", workspace_id="workspace-one",
            account_binding_id="account-one",
            session_ref="session://workspace-one/account-one",
            start_url=self.origin + "/contact/form?draft_token=abc123",
            fields=[
                {"selector": "#name", "value": "Private Person"},
                {"selector": "#message", "value": "private draft body"},
                {"selector": "#topic", "value": "research", "kind": "select"},
            ],
            uploads=[{"selector": "#attachment", "path": "cover.png"}],
            preview_selector="#preview-tab", ready_selector="#preview",
            extract_selectors=["#preview"],
        )
        args.update(overrides)
        return generic_form_recipe(**args)

    def run_fake(self, p, factory=FakePlaywright, **kwargs):
        return run_playwright(p, policy=self.policy, playwright_factory=factory, **kwargs)

    def test_generic_form_flow_runs_with_redacted_evidence(self):
        fake = FakePlaywright()
        p = self.recipe()
        self.assertEqual(
            [s["type"] for s in p.steps],
            ["navigate", "fill", "fill", "select", "upload", "click",
             "wait_for", "extract", "screenshot"],
        )
        self.assertEqual(p.action_class, "upload")
        result = self.run_fake(p, factory=lambda: fake)
        self.assertEqual((result.status, result.completed_steps), ("done", 9), result.blocker_reason)
        page_state = fake.chromium.browser.context.page.state
        self.assertEqual(page_state["#message"], "private draft body")
        self.assertEqual(page_state["uploaded"], "cover.png")
        evidence = repr(result)
        for private in ("Private Person", "private draft body", "draft_token", "abc123",
                        "/contact/form", "Synthetic fixture heading", str(self.root)):
            self.assertNotIn(private, evidence)
        self.assertEqual(result.final_url, self.origin)
        self.assertEqual(result.external_receipt, "")
        self.assertEqual([r["status"] for r in result.action_log], ["done"] * 9)
        self.assertEqual(result.action_log[7]["text_chars"], len("Synthetic fixture heading"))
        self.assertTrue(result.artifacts[0].startswith("artifact://browser/"))
        self.assertEqual(result.action_log[8]["artifact_ref"], result.artifacts[0])

    def test_off_domain_navigation_rejected_before_launch(self):
        for url in ("https://evil.example/contact", "http://forms.fixture.example/contact",
                    "https://sub.forms.fixture.example/contact", "http://10.0.0.5/contact"):
            result = self.run_fake(self.recipe(start_url=url), factory=not_launched)
            self.assertEqual(result.status, "blocked", url)
            self.assertEqual(result.completed_steps, 0)
        result = self.run_fake(self.recipe(start_url="https://evil.example/x"), factory=not_launched)
        self.assertEqual(result.blocker_reason, "off_allowlist_navigation")

    def test_off_domain_request_during_flow_is_blocked(self):
        result = self.run_fake(self.recipe(preview_selector="#trigger-offsite"))
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.blocker_reason, "off_allowlist_network_request")
        self.assertEqual(result.completed_steps, 5)

    def test_step_limit_enforced_before_launch(self):
        many = [{"selector": f"#f{i}", "value": "x"} for i in range(30)]
        result = self.run_fake(self.recipe(fields=many), factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "plan exceeds max_steps"))
        result = self.run_fake(self.recipe(max_steps=5), factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "plan exceeds max_steps"))
        result = self.run_fake(self.recipe(max_steps=65), factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "max_steps out of bounds"))

    def test_timeout_stops_mid_flow_without_claiming_success(self):
        ticks = iter(range(1000))
        clock = lambda: next(ticks) * 0.5  # each deadline check costs 0.5 s
        result = self.run_fake(self.recipe(timeout_seconds=2), clock=clock)
        self.assertEqual((result.status, result.blocker_reason), ("failed", "browser_execution_timeout"))
        self.assertEqual(result.completed_steps, 2)
        self.assertLess(result.completed_steps, 9)
        self.assertEqual(result.external_receipt, "")
        result = self.run_fake(self.recipe(timeout_seconds=301), factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "timeout_seconds out of bounds"))

    def test_submit_disabled_without_valid_approval(self):
        p = self.recipe(submit_selector="#send-form")
        self.assertEqual((p.action_class, p.steps[-1]["type"]), ("publish", "submit"))
        result = self.run_fake(p, factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason),
                         ("blocked", "submit_requires_matching_human_approval"))
        stale = replace(p, approval_snapshot_id="snap-1", approved_payload_hash="0" * 64)
        result = self.run_fake(stale, factory=not_launched)
        self.assertEqual(result.blocker_reason, "submit_requires_matching_human_approval")
        approved = replace(p, approval_snapshot_id="snap-1",
                           approved_payload_hash=canonical_payload_hash(p))
        tampered = replace(approved, steps=approved.steps[:1] + (
            {"type": "fill", "selector": "#message", "value": "changed after approval"},
        ) + approved.steps[2:])
        result = self.run_fake(tampered, factory=not_launched)
        self.assertEqual(result.blocker_reason, "submit_requires_matching_human_approval")

    def test_submit_stays_disabled_until_trusted_verifier_exists(self):
        p = self.recipe(submit_selector="#send-form")
        approved = replace(p, approval_snapshot_id="snap-1",
                           approved_payload_hash=canonical_payload_hash(p))
        result = self.run_fake(approved, factory=not_launched)
        self.assertEqual((result.status, result.completed_steps), ("blocked", 0))
        self.assertEqual(result.blocker_reason, "trusted_approval_verifier_not_configured")

    def test_recipe_rejects_unknown_field_shapes(self):
        for kwargs in (
            {"fields": [{"selector": "#a", "value": "x", "kind": "submit"}]},
            {"fields": [{"selector": "#a", "value": "x", "password": "p"}]},
            {"uploads": [{"selector": "#a", "path": "cover.png", "url": "https://x"}]},
        ):
            with self.assertRaises(PolicyError):
                self.recipe(**kwargs)
        result = self.run_fake(
            self.recipe(fields=[{"selector": "#a", "value": "Bearer abc.def"}]),
            factory=not_launched,
        )
        self.assertEqual(result.status, "blocked")


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
                result = run_playwright(generic_form_recipe(
                    plan_id="plan-fixture", workspace_id="workspace-one",
                    account_binding_id="account-one",
                    session_ref="session://workspace-one/account-one",
                    start_url=origin + "/editor",
                    fields=[
                        {"selector": "#caption", "value": "safe local draft"},
                        {"selector": "#topic", "value": "science", "kind": "select"},
                    ],
                    preview_selector="#tab", extract_selectors=["#result"],
                ), policy=policy)
                self.assertEqual(result.status, "done", result.blocker_reason)
                self.assertEqual(result.completed_steps, 6)
                self.assertEqual(len(result.artifacts), 1)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    # T-560-D social recipes run in this existing CI step (no `workflow` scope).
    from test_browser_social import (  # noqa: F401
        SocialAccountBindings, SocialChallenges, SocialDraftPreparation,
        SocialNoPlaintextCredentials, SocialPublishGate,
    )
    unittest.main()
