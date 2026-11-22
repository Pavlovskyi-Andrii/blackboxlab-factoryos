"""T-720: Surfer action sessions on the EC2 worker: one live Chromium page kept between commands.

The dedicated Surfer worker (``autopilot.browser_worker``) calls ``ActionRunner.pump()`` on every pass. It asks
FactoryOS for one command (``/api/factory/browser/worker/actions/claim``), runs it on the live page with
``browser_runner.action_session.ActionSession`` and posts the outcome. ``open`` starts Chromium; the page then stays
until FactoryOS says close (the agent closed it, the owner stopped it, a timeout), FactoryOS is unreachable for two
minutes, or the hard lifetime passes.

Read tasks keep running while a page is live: ``borrowed_factory()`` lets the read executor open a fresh anonymous
context in the same Chromium instead of starting a second browser.

Nothing here is logged except command ids, kinds and statuses: no values, no URLs with queries, no cookies.
"""
from __future__ import annotations

import pathlib
import shutil
import socket
import sys
import tempfile
import time
from typing import Any, Callable, Optional

try:
    from . import relay_tasks
except ImportError:  # pragma: no cover - run as a plain script
    import relay_tasks

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from browser_runner.action_session import VIEWPORT, ActionSession, staging_name  # noqa: E402
from browser_runner.egress_proxy import PublicOnlyProxy  # noqa: E402

LIVE_POLL_SECONDS = 1.0                  # how often the worker asks for the next command while a page is live
UNREACHABLE_CLOSE_SECONDS = 120          # FactoryOS unreachable this long: close the page (fail safe)
HARD_LIFETIME_SECONDS = 35 * 60          # the server closes at 30 min; this is the local backstop
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def log(message: str) -> None:
    print(f"surfer-actions: {message}", file=sys.stderr, flush=True)


class _BorrowedBrowser:
    """The live session's Chromium, lent to a read task: it may open contexts, it may not close the browser."""

    def __init__(self, browser: Any):
        self._browser = browser

    def new_context(self, **kwargs: Any) -> Any:
        return self._browser.new_context(**kwargs)

    def close(self) -> None:
        pass


class _BorrowedPlaywright:
    def __init__(self, browser: Any):
        self.chromium = self
        self._browser = browser

    def launch(self, **_kwargs: Any) -> Any:            # proxy and headless are already set on the live browser
        return _BorrowedBrowser(self._browser)

    def __enter__(self) -> "_BorrowedPlaywright":
        return self

    def __exit__(self, *_exc: Any) -> None:
        pass


def _start_playwright() -> Any:
    from playwright.sync_api import sync_playwright
    return sync_playwright().start()


class ActionRunner:
    def __init__(self, *, http: Any = None, start_playwright: Callable[[], Any] = _start_playwright,
                 proxy_factory: Optional[Callable[[], Any]] = None, clock: Callable[[], float] = time.monotonic,
                 resolve: Callable = socket.getaddrinfo, loopback: bool = False):
        self.http = http
        self.start_playwright, self.clock, self.loopback = start_playwright, clock, loopback
        self.proxy_factory = proxy_factory or (lambda: PublicOnlyProxy(resolve=resolve))
        self.live = ""                       # session id whose page this worker holds
        self.session: Optional[ActionSession] = None
        self._pw = self._browser = self._context = self._proxy = None
        self._tmp: Optional[str] = None
        self._opened = self._last_ok = 0.0
        self.done = self.failed = 0

    # --- browser lifetime -------------------------------------------------------------------------------------
    def _launch(self, storage_state: Optional[dict]) -> None:
        self.close()
        self._tmp = tempfile.mkdtemp(prefix="factoryos-surfer-actions-")
        args = {}
        if not self.loopback:
            self._proxy = self.proxy_factory()
            self._proxy.__enter__()
            args["proxy"] = {"server": self._proxy.url, "bypass": "<-loopback>"}
        self._pw = self.start_playwright()
        self._browser = self._pw.chromium.launch(headless=True, **args)
        extra = {"storage_state": storage_state} if isinstance(storage_state, dict) else {}
        self._context = self._browser.new_context(accept_downloads=False, service_workers="block", permissions=[],
                                                  ignore_https_errors=False, viewport=dict(VIEWPORT), **extra)
        page = self._context.new_page()
        self.session = ActionSession(page, self._context, loopback=self.loopback,
                                     upload_dir=pathlib.Path(self._tmp))
        self._opened = self.clock()

    def close(self) -> None:
        for closer in (getattr(self._context, "close", None), getattr(self._browser, "close", None),
                       getattr(self._pw, "stop", None)):
            try:
                if closer:
                    closer()
            except Exception:
                pass
        if self._proxy is not None:
            try:
                self._proxy.__exit__(None, None, None)
            except Exception:
                pass
        if self._tmp:
            shutil.rmtree(self._tmp, ignore_errors=True)
        self._pw = self._browser = self._context = self._proxy = self._tmp = None
        self.session, self.live = None, ""

    def borrowed_factory(self) -> Optional[Callable[[], Any]]:
        """A playwright_factory for read tasks while a page is live (None otherwise: they start their own)."""
        if self._browser is None:
            return None
        browser = self._browser
        return lambda: _BorrowedPlaywright(browser)

    # --- one pass ---------------------------------------------------------------------------------------------
    def _http(self) -> Any:
        if self.http is None:
            import requests
            self.http = requests
        return self.http

    def _stage_upload(self, base: str, headers: dict, command: dict) -> None:
        response = self._http().get(base + f"/api/factory/browser/worker/actions/{command['id']}/file",
                                    headers=headers, timeout=120)
        if response.status_code != 200 or len(response.content) > MAX_UPLOAD_BYTES or not self._tmp:
            return
        path = pathlib.Path(self._tmp) / staging_name(command.get("file_name") or "upload.bin")
        path.write_bytes(response.content)
        command["file_path"] = str(path)

    def pump(self) -> str:
        """idle | ran | error. Never raises."""
        if not relay_tasks.configured():
            return "idle"
        now = self.clock()
        if self.live and (now - self._opened > HARD_LIFETIME_SECONDS or (
                self._last_ok and now - self._last_ok > UNREACHABLE_CLOSE_SECONDS)):
            log(f"closing {self.live}: lifetime or FactoryOS unreachable")
            self.close()
        base, token = relay_tasks.endpoint()
        headers = {"Authorization": "Bearer " + token}
        try:
            response = self._http().post(base + "/api/factory/browser/worker/actions/claim", headers=headers,
                                         json={"live": self.live}, timeout=30)
            if response.status_code != 200:
                return "error" if response.status_code >= 500 else "idle"
            data = response.json()
        except Exception as exc:
            log(f"queue unavailable: {type(exc).__name__}")
            return "error"
        self._last_ok = now
        if data.get("close") and self.live:
            log(f"closing {self.live}: FactoryOS closed the session")
            self.close()
            return "ran"
        command = data.get("command")
        if not isinstance(command, dict) or not command.get("id"):
            return "idle"
        kind = str(command.get("kind") or "")
        state = command.pop("storage_state", None)
        try:
            if kind == "open":
                self._launch(state if isinstance(state, dict) else None)
                self.live = str(command.get("session_id") or "")
            state = None                                           # cookies leave memory with the command
            if self.session is None:
                body = {"status": "failed", "blocker": "worker_lost"}
            else:
                if command.get("action") == "upload":
                    self._stage_upload(base, headers, command)
                body = self.session.execute(command)
        except Exception as exc:
            body = {"status": "failed", "blocker": f"worker_{type(exc).__name__}"}
            if kind == "open":
                self.close()
        command.pop("secret_value", None)
        log(f"{command['id']} {kind} {command.get('action') or ''} -> {body.get('status')} {body.get('blocker') or ''}".rstrip())
        try:
            posted = self._http().post(base + f"/api/factory/browser/worker/actions/{command['id']}/result",
                                       headers=headers, json=body, timeout=60)
            ok = posted.status_code == 200
        except Exception as exc:
            log(f"result not delivered: {type(exc).__name__}")
            ok = False
        self.done += ok
        self.failed += not ok
        return "ran"
