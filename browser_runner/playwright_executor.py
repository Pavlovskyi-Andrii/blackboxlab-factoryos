"""T-560-C: bounded Playwright executor for anonymous, approval-free browser drafts.

Security boundary: this module executes ONLY read/draft/upload preparation steps
within origins supplied by trusted application configuration. No credentials,
arbitrary shell commands, external submissions, or automatic social publishing.

T-560-F: a logged-in browser session may be restored ONLY when the trusted host
passes an ``EncryptedSessionStore`` and the plan's ``session_ref`` is bound to the
plan's exact workspace/provider/account binding. The decrypted storage_state goes
straight into the Chromium context and never into results, logs or artifacts.
The network guard (GET/HEAD/OPTIONS only, allowlisted origins) still applies, so a
restored session can read and prepare drafts but cannot write to the site.

Playwright is an optional dependency of the separate runner host, NOT the
FactoryOS Render web service. The default runner never uses an API service.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import time
from typing import Any, Callable, Collection
from urllib.parse import urlsplit

from .core import (
    IRREVERSIBLE_ACTIONS, BrowserActionPlan, BrowserActionResult, PolicyError,
    approval_matches, canonical_payload_hash, validate_plan,
)
from .core import redact
from .sessions import challenge_checkpoint

EXTRACT_TEXT_LIMIT = 6000


_SAFE_CLASSES = frozenset({"read", "draft", "upload"})
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_SAFE_UPLOAD_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".pdf", ".mp4", ".mov"})
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_UNSAFE_WORDS = re.compile(
    r"(?:^|[^a-z])(?:publish|post|delete|remove|send|submit|pay|purchase|"
    r"checkout|transfer|subscribe|unsubscribe|invite|confirm|follow|like)(?:[^a-z]|$)",
    re.I,
)
_CHALLENGE_MARKERS = (
    ("captcha", 'iframe[src*="recaptcha"],iframe[src*="hcaptcha"],.h-captcha,.g-recaptcha'),
    ("2fa", 'input[autocomplete="one-time-code"],input[name="otp"],input[name="totp"]'),
    ("security_challenge", 'form[id="challenge-form"],[data-security-challenge]'),
)
_SCHEMA = {
    "navigate": frozenset({"type", "url"}),
    "click": frozenset({"type", "selector"}),
    "fill": frozenset({"type", "selector", "value"}),
    "select": frozenset({"type", "selector", "value"}),
    "upload": frozenset({"type", "selector", "path"}),
    "wait_for": frozenset({"type", "selector"}),
    "extract": frozenset({"type", "selector"}),
    "screenshot": frozenset({"type"}),
}


@dataclass(frozen=True)
class BrowserRuntimePolicy:
    """Trusted host-supplied limits, never deserialized from user plan JSON."""

    allowed_origins: tuple[str, ...]
    artifact_root: Path
    upload_root: Path | None = None
    browser_executable_path: str | None = None
    allow_loopback_fixture: bool = False
    # Read tasks on real sites (2026-11-13): pages pull CSS/JS/images from CDNs. When set, an off-allowlist GET that is
    # not a navigation is loaded instead of failing the run. Navigations off the allowlist and every non-GET request
    # stay blocked, and only the "read" action class may use it.
    allow_offsite_subresource_reads: bool = False
    # Return the extracted text (redacted, capped) for read tasks; otherwise only its length and hash are recorded.
    return_extracted_text: bool = False
    # Owner 2026-11-13: logged-in read tasks (a saved session) — the page's own same-origin XHR/fetch may use POST
    # (apps like Search Console load data that way). Navigations, forms and every other origin stay GET-only.
    allow_same_origin_xhr: bool = False
    # Every browser connection goes through this proxy (browser_runner.egress_proxy.PublicOnlyProxy), which checks the
    # address at connection time; "<-loopback>" removes Chromium's implicit loopback bypass.
    proxy_server: str | None = None


def _main_frame_navigation(request: Any) -> bool:
    """True unless the request is clearly a sub-resource or a sub-frame navigation (unknown counts as main frame)."""
    try:
        if not bool(getattr(request, "is_navigation_request", lambda: True)()):
            return False
        frame = getattr(request, "frame", None)
        return frame is None or getattr(frame, "parent_frame", None) is None
    except Exception:
        return True


def _origin(url: str, *, allow_loopback_fixture: bool) -> str:
    if not isinstance(url, str) or "\\" in url or any(ord(c) < 32 for c in url):
        raise PolicyError("invalid_browser_url")
    try:
        p = urlsplit(url)
        host = p.hostname
        port = p.port
    except (ValueError, AttributeError):
        raise PolicyError("invalid_browser_url") from None
    if p.scheme not in {"http", "https"} or not host or p.username or p.password:
        raise PolicyError("only_absolute_credential_free_http_origins")
    host = host.lower().rstrip(".")
    if not host or host in {"localhost", "localhost.localdomain"} or host.endswith(".localhost"):
        raise PolicyError("localhost_disallowed_use_explicit_loopback_fixture")
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_loopback:
            if not allow_loopback_fixture:
                raise PolicyError("local_network_disallowed")
        elif not ip.is_global:
            raise PolicyError("local_network_disallowed")
    except ValueError:
        # Hostnames are allowed only if trusted application configuration
        # explicitly lists their precise origin.
        if not re.fullmatch(r"[a-z0-9.-]+", host) or ".." in host:
            raise PolicyError("invalid_browser_host")
    suffix = f":{port}" if port is not None and port != (443 if p.scheme == "https" else 80) else ""
    return f"{p.scheme}://{host}{suffix}"


def _safe_report_url(url: str) -> str:
    """Return only the origin, never secret-bearing path/query/fragment."""
    try:
        return _origin(url, allow_loopback_fixture=True)
    except PolicyError:
        return ""


def _selector(step: dict[str, Any]) -> str:
    selector = step.get("selector")
    if not isinstance(selector, str) or not selector.strip() or len(selector) > 300:
        raise PolicyError("selector_required_and_bounded")
    if _UNSAFE_WORDS.search(selector):
        raise PolicyError("irreversible_selector_disallowed")
    return selector


def _validated_file(step: dict[str, Any], upload_root: Path | None) -> Path:
    if upload_root is None:
        raise PolicyError("upload_root_not_configured")
    name = step.get("path")
    if not isinstance(name, str) or not name or len(name) > 240:
        raise PolicyError("upload_path_invalid")
    if Path(name).is_absolute() or ".." in Path(name).parts:
        raise PolicyError("upload_must_be_relative_to_staging_root")
    try:
        root = upload_root.resolve(strict=True)
        resolved = (root / name).resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError):
        raise PolicyError("upload_outside_staging_root") from None
    if not resolved.is_file() or resolved.suffix.lower() not in _SAFE_UPLOAD_TYPES:
        raise PolicyError("upload_file_type_disallowed")
    if resolved.stat().st_size > _MAX_UPLOAD_BYTES:
        raise PolicyError("upload_file_too_large")
    return resolved


def validate_runtime(plan: BrowserActionPlan, policy: BrowserRuntimePolicy) -> frozenset[str]:
    validate_plan(plan)
    if plan.action_class in IRREVERSIBLE_ACTIONS or any(
        dict(step).get("type") == "submit" for step in plan.steps
    ):
        if not approval_matches(plan):
            raise PolicyError("submit_requires_matching_human_approval")
        # A self-asserted snapshot id + hash is necessary but not sufficient:
        # no trusted server-side approval verifier exists yet, so submit stays
        # disabled for the real browser even with a matching payload hash.
        raise PolicyError("trusted_approval_verifier_not_configured")
    if plan.action_class not in _SAFE_CLASSES:
        raise PolicyError("real_publish_send_delete_disabled")
    if plan.max_retries:
        raise PolicyError("real_browser_retries_disabled")
    if not plan.steps or plan.steps[0].get("type") != "navigate":
        raise PolicyError("first_step_must_navigate")
    if not policy.allowed_origins:
        raise PolicyError("trusted_origin_allowlist_required")
    origins: set[str] = set()
    for allowed in policy.allowed_origins:
        normalized = _origin(allowed, allow_loopback_fixture=policy.allow_loopback_fixture)
        if allowed.rstrip("/") != normalized:
            raise PolicyError("allowlist_must_contain_exact_origins")
        origins.add(normalized)
    if len(origins) > 12:
        raise PolicyError("too_many_allowed_origins")
    for item in plan.steps:
        step = dict(item)
        kind = str(step.get("type") or "")
        if kind not in _SCHEMA:
            # submit is unconditionally disabled, regardless of self-declared
            # approval_snapshot_id and hash.
            raise PolicyError("submit_or_unknown_step_disabled")
        if set(step) - _SCHEMA[kind]:
            raise PolicyError("unexpected_step_parameter")
        if kind == "navigate":
            url = step["url"]
            origin = _origin(url, allow_loopback_fixture=policy.allow_loopback_fixture)
            if origin not in origins:
                raise PolicyError("off_allowlist_navigation")
            if _UNSAFE_WORDS.search(urlsplit(url).path):
                raise PolicyError("irreversible_navigation_path_disallowed")
        elif kind not in {"screenshot"}:
            _selector(step)
        if kind in {"fill", "select"} and (
            not isinstance(step.get("value"), str) or len(step["value"]) > 10000
        ):
            raise PolicyError("form_value_invalid_or_too_long")
        if kind == "upload":
            _validated_file(step, policy.upload_root)
    return frozenset(origins)


def _challenge(page: Any) -> str:
    for reason, selector in _CHALLENGE_MARKERS:
        if page.locator(selector).count():
            return reason
    return ""


def _safe_click(locator: Any) -> bool:
    """Extra DOM-level guard in addition to rejecting all write HTTP requests."""
    return bool(locator.evaluate("""el => {
        const form = el.closest('form');
        const words = [
            el.innerText || '', el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '', el.getAttribute('type') || '',
            el.getAttribute('href') || ''
        ].join(' ').toLowerCase();
        return !form && !/(publish|post|delete|remove|send|submit|pay|purchase|checkout|transfer|subscribe|unsubscribe|invite|confirm|follow|like)/i.test(words);
    }"""))


def run_playwright(
    plan: BrowserActionPlan,
    *,
    policy: BrowserRuntimePolicy,
    playwright_factory: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.monotonic,
    session_store: Any | None = None,
) -> BrowserActionResult:
    """Execute a bounded, fresh anonymous Chromium context; no external writes.

    A trusted owner-approval verifier is NOT wired yet: real submit/publish is
    always blocked even when plan approval metadata appears to match.
    """
    try:
        origins = validate_runtime(plan, policy)
    except (PolicyError, TypeError, KeyError, ValueError) as exc:
        return BrowserActionResult(
            plan_id=plan.plan_id, status="blocked",
            blocker_reason=str(exc) if isinstance(exc, PolicyError) else "invalid_browser_plan",
            executor="playwright",
        )

    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return BrowserActionResult(
                plan_id=plan.plan_id, status="blocked",
                blocker_reason="playwright_optional_dependency_not_installed",
                executor="playwright",
            )
        playwright_factory = sync_playwright

    context_state: dict[str, Any] = {}
    if session_store is not None:
        try:
            if not plan.session_ref:
                raise PermissionError("session_ref_required_for_session_restore")
            context_state = {"storage_state": session_store.load(
                plan.session_ref, workspace_id=plan.workspace_id, provider=plan.provider,
                account_binding_id=plan.account_binding_id,
            ).reveal()}
        except PermissionError:
            return BrowserActionResult(
                plan_id=plan.plan_id, status="blocked",
                blocker_reason="session_unavailable_for_binding", executor="playwright",
            )

    deadline = clock() + plan.timeout_seconds
    log: list[dict[str, Any]] = []
    artifacts: list[str] = []
    blocked_requests: list[str] = []
    quietly_aborted: list[str] = []
    completed = 0
    final_url = ""
    status = "done"
    blocker = ""

    def time_left() -> int:
        milliseconds = int((deadline - clock()) * 1000)
        if milliseconds < 100:
            raise TimeoutError("browser_execution_timeout")
        return milliseconds

    def guard_route(route: Any) -> None:
        request = route.request
        try:
            actual_origin = _origin(
                request.url, allow_loopback_fixture=policy.allow_loopback_fixture
            )
            if actual_origin not in origins:
                is_navigation = bool(getattr(request, "is_navigation_request", lambda: True)())
                if not (policy.allow_offsite_subresource_reads and plan.action_class == "read" and not is_navigation
                        and request.method.upper() in ("GET", "HEAD")):
                    raise PolicyError("off_allowlist_network_request")
            if request.method.upper() not in _SAFE_METHODS and not (
                    policy.allow_same_origin_xhr and plan.action_class == "read" and actual_origin in origins
                    and not bool(getattr(request, "is_navigation_request", lambda: True)())):
                raise PolicyError("browser_write_request_blocked")
            if _UNSAFE_WORDS.search(urlsplit(request.url).path):
                raise PolicyError("irreversible_network_path_disallowed")
        except PolicyError as exc:
            route.abort()                      # the request never leaves the browser, in every mode
            # Read tasks on real sites (owner 2026-11-13, prom.ua): analytics POSTs and third-party iframes are
            # aborted as before, but only a main-frame navigation away from the allowed origin fails the read.
            if policy.allow_offsite_subresource_reads and plan.action_class == "read" and not _main_frame_navigation(request):
                quietly_aborted.append(str(exc))
                return
            blocked_requests.append(str(exc))
            return
        route.continue_()

    try:
        with playwright_factory() as playwright:
            args = {} if policy.browser_executable_path is None else {
                "executable_path": policy.browser_executable_path
            }
            if policy.proxy_server:
                args["proxy"] = {"server": policy.proxy_server, "bypass": "<-loopback>"}
            browser = playwright.chromium.launch(headless=True, **args)
            try:
                context = browser.new_context(
                    accept_downloads=False, service_workers="block",
                    permissions=[], ignore_https_errors=False, **context_state,
                )
                context_state = {}
                try:
                    context.route("**/*", guard_route)
                    if not hasattr(context, "route_web_socket"):
                        raise PolicyError("websocket_guard_unavailable")
                    context.route_web_socket("**/*", lambda websocket: websocket.close())
                    page = context.new_page()
                    page.set_default_timeout(min(time_left(), 10000))
                    for index, input_step in enumerate(plan.steps, 1):
                        if blocked_requests:
                            status, blocker = "blocked", blocked_requests[0]
                            break
                        if completed:
                            challenge = _challenge(page)
                            if challenge:
                                status, blocker = "waiting_human", challenge
                                break
                        step = dict(input_step)
                        kind = step["type"]
                        ms = min(time_left(), 20000)
                        if kind == "navigate":
                            page.goto(step["url"], wait_until="domcontentloaded", timeout=ms)
                        elif kind == "screenshot":
                            root = policy.artifact_root.resolve()
                            root.mkdir(parents=True, exist_ok=True, mode=0o700)
                            root.chmod(0o700)
                            digest = hashlib.sha256(
                                f"{plan.plan_id}:{index}:{secrets.token_hex(8)}".encode()
                            ).hexdigest()[:24]
                            dest = root / f"browser-{digest}.png"
                            fd = os.open(str(dest), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                            os.close(fd)
                            try:
                                page.screenshot(path=str(dest), full_page=False, timeout=ms)
                            except Exception:
                                dest.unlink(missing_ok=True)
                                raise
                            ref = f"artifact://browser/{dest.name}"
                            artifacts.append(ref)
                        else:
                            selector = _selector(step)
                            locator = page.locator(selector)
                            if kind == "click":
                                if not _safe_click(locator):
                                    raise PolicyError("unsafe_click_target")
                                locator.click(timeout=ms)
                            elif kind == "fill":
                                locator.fill(step["value"], timeout=ms)
                            elif kind == "select":
                                locator.select_option(value=step["value"], timeout=ms)
                            elif kind == "upload":
                                path = _validated_file(step, policy.upload_root)
                                locator.set_input_files(str(path), timeout=ms)
                            elif kind == "wait_for":
                                locator.wait_for(state="visible", timeout=ms)
                            elif kind == "extract":
                                text = locator.inner_text(timeout=ms)
                        if blocked_requests:
                            status, blocker = "blocked", blocked_requests[0]
                            break
                        completed = index
                        record: dict[str, Any] = {
                            "index": index, "type": kind, "status": "done"
                        }
                        if kind == "extract":
                            record["text_chars"] = len(text)
                            record["text_sha256"] = hashlib.sha256(text.encode()).hexdigest()
                            if policy.return_extracted_text and plan.action_class == "read":
                                record["text"] = str(redact(text))[:EXTRACT_TEXT_LIMIT]
                        if kind == "screenshot":
                            record["artifact_ref"] = artifacts[-1]
                        log.append(record)
                        final_url = _safe_report_url(page.url)
                    if status == "done":
                        challenge = _challenge(page)
                        if challenge:
                            status, blocker = "waiting_human", challenge
                    if blocked_requests:
                        status, blocker = "blocked", blocked_requests[0]
                finally:
                    context.close()
            finally:
                browser.close()
    except PolicyError as exc:
        status, blocker = "blocked", str(exc)
    except TimeoutError:
        status, blocker = "failed", "browser_execution_timeout"
    except Exception as exc:
        # No raw Playwright errors (may contain secret-bearing URLs/DOM).
        status, blocker = "failed", f"browser_runtime_{type(exc).__name__}"
        if blocked_requests:
            status, blocker = "blocked", blocked_requests[0]

    if status == "waiting_human":
        cp = challenge_checkpoint(
            plan.plan_id, plan.workspace_id, plan.account_binding_id,
            completed, canonical_payload_hash(plan), blocker,
        )
        log.append({
            "type": "checkpoint", "status": "waiting_human",
            "completed_steps": cp.completed_steps, "payload_hash": cp.payload_hash,
            "reason": cp.reason,
        })
    return BrowserActionResult(
        plan_id=plan.plan_id, status=status,
        completed_steps=completed, action_log=tuple(log),
        final_url=final_url, external_receipt="", blocker_reason=blocker,
        executor="playwright",
        artifacts=tuple(artifacts),
    )
