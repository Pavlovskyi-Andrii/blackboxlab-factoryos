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

import os
import pathlib
import shutil
import signal
import socket
import sys
import tempfile
import threading
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
# Live run 2026-11-23: one click left the worker stuck inside a browser call, so it served nothing else (actions and
# reads) until the 15-min loop watchdog. Playwright's sync calls cannot be cancelled from another thread, and some
# (page.evaluate) have no timeout at all: past this deadline the browser processes are killed, which makes the stuck
# call fail at once; the step reports worker_timeout and the page is closed, freeing the single slot.
COMMAND_DEADLINE_SECONDS = 90


def _children_map() -> dict:
    children: dict = {}
    try:
        names = os.listdir("/proc")
    except OSError:
        return children
    for name in names:
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat", "rb") as handle:
                stat = handle.read().decode("ascii", "replace")
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        children.setdefault(ppid, []).append(int(name))
    return children


def _children(pid: int) -> list:
    return list(_children_map().get(pid, []))


def _descendants(root: int) -> list:
    """Every process under ``root`` (Chromium and its helpers under the driver), from /proc; [] without /proc."""
    children = _children_map()
    found, todo = [], [root]
    while todo:
        for child in children.get(todo.pop(), []):
            found.append(child)
            todo.append(child)
    return found


EXIT_GRACE_SECONDS = 20       # the stuck call still has not returned this long after the kill: restart the worker
EXIT_CODE_STUCK = 75          # systemd (Restart=always) starts a fresh worker
STAGE_SECONDS = 60            # an approved upload must be downloaded within this, end to end


def log(message: str) -> None:
    print(f"surfer-actions: {message}", file=sys.stderr, flush=True)


def kill_process_tree(root: int) -> int:
    """SIGKILL ``root`` (this command's Playwright driver) and everything under it, children first, twice so that a
    process forked in between is caught as well. Returns how many processes were signalled."""
    killed = 0
    for _ in range(2):
        for pid in list(reversed(_descendants(root))) + [root]:
            try:
                os.kill(pid, signal.SIGKILL)
                killed += 1
            except OSError:
                pass
        time.sleep(0.2)
    return killed


def _driver_pid(playwright: Any) -> Optional[int]:
    """The Playwright driver's pid (private attribute; None when the shape differs or in tests)."""
    try:
        pid = int(playwright._impl_obj._connection._transport._proc.pid)
        return pid if pid > 1 else None
    except Exception:
        return None


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
        self.deadline_seconds = COMMAND_DEADLINE_SECONDS
        self.exit_grace_seconds = EXIT_GRACE_SECONDS
        self.kill = kill_process_tree
        self.exit = os._exit
        self.timed_out = False
        self._browser_root: Optional[int] = None   # pid of the Playwright driver this runner started
        self._watch = threading.Lock()             # command completion vs the deadline callback
        self._active = ""                          # id of the command being executed ("" when none)

    # --- browser lifetime -------------------------------------------------------------------------------------
    def _launch(self, storage_state: Optional[dict]) -> None:
        self.close()
        self._tmp = tempfile.mkdtemp(prefix="factoryos-surfer-actions-")
        args = {}
        if not self.loopback:
            self._proxy = self.proxy_factory()
            self._proxy.__enter__()
            args["proxy"] = {"server": self._proxy.url, "bypass": "<-loopback>"}
        before = set(_children(os.getpid()))
        self._pw = self.start_playwright()
        new = [pid for pid in _children(os.getpid()) if pid not in before]
        self._browser_root = _driver_pid(self._pw) or (new[0] if len(new) == 1 else None)
        self._browser = self._pw.chromium.launch(headless=True, **args)
        extra = {"storage_state": storage_state} if isinstance(storage_state, dict) else {}
        self._context = self._browser.new_context(accept_downloads=False, service_workers="block", permissions=[],
                                                  ignore_https_errors=False, viewport=dict(VIEWPORT), **extra)
        page = self._context.new_page()
        self.session = ActionSession(page, self._context, loopback=self.loopback,
                                     upload_dir=pathlib.Path(self._tmp))
        self._opened = self.clock()

    def close(self) -> None:
        # After a deadline kill the context and the browser are already gone: closing them would wait on the dead
        # driver, so only the Playwright handle is stopped.
        dead = self.timed_out
        for closer in (None if dead else getattr(self._context, "close", None),
                       None if dead else getattr(self._browser, "close", None), getattr(self._pw, "stop", None)):
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
        self.session, self.live, self._browser_root = None, "", None

    def holds_playwright(self) -> bool:
        """T-728: this runner has a started Playwright (a live page, or one being opened). While it does, a second
        ``sync_playwright()`` in the same thread raises ("Sync API inside the asyncio loop"), so the launch probe
        must not run: it would always fail and park the worker in "unavailable"."""
        return self._pw is not None

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
        """Download the approved file within STAGE_SECONDS end to end; on failure the step reports the file missing."""
        started = time.monotonic()
        response = self._http().get(base + f"/api/factory/browser/worker/actions/{command['id']}/file",
                                    headers=headers, timeout=(10, 20), stream=True)
        if response.status_code != 200 or not self._tmp:
            return
        chunks = getattr(response, "iter_content", None)
        data = bytearray()
        for chunk in (chunks(65536) if chunks else [response.content]):
            data += chunk
            if len(data) > MAX_UPLOAD_BYTES or time.monotonic() - started > STAGE_SECONDS:
                log(f"{command['id']} upload file not staged: too large or too slow")
                getattr(response, "close", lambda: None)()
                return
        path = pathlib.Path(self._tmp) / staging_name(command.get("file_name") or "upload.bin")
        path.write_bytes(bytes(data))
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
        self.timed_out = False
        if command.get("action") == "upload" and self.session is not None:
            try:                                                   # bounded by STAGE_SECONDS on its own
                self._stage_upload(base, headers, command)
            except Exception as exc:
                log(f"{command['id']} upload file not staged: {type(exc).__name__}")

        token = command["id"] + ":" + str(time.monotonic())

        def _deadline() -> None:
            with self._watch:                                      # the command may have finished just now
                if self._active != token:
                    return
                self.timed_out = True
                if self.session is not None:
                    self.session.aborted = True                    # no more calls into the dead driver
                root = self._browser_root
            log(f"{command['id']} {kind}: no answer in {self.deadline_seconds:.0f}s; killing the browser")
            killed = self.kill(root) if root else 0
            if not killed:
                log(f"{command['id']}: no browser process to kill")
            escalate = threading.Timer(self.exit_grace_seconds, _escalate)
            escalate.daemon = True
            escalate.start()

        def _escalate() -> None:
            with self._watch:
                if self._active != token:
                    return
            log(f"{command['id']}: still stuck {self.exit_grace_seconds:.0f}s after the kill; restarting the worker")
            self.exit(EXIT_CODE_STUCK)

        with self._watch:
            self._active = token
        timer = threading.Timer(self.deadline_seconds, _deadline)
        timer.daemon = True
        timer.start()
        try:
            if kind == "open":
                self._launch(state if isinstance(state, dict) else None)
                self.live = str(command.get("session_id") or "")
            state = None                                           # cookies leave memory with the command
            if self.session is None:
                body = {"status": "failed", "blocker": "worker_lost"}
            else:
                body = self.session.execute(command)
        except Exception as exc:
            body = {"status": "failed", "blocker": f"worker_{type(exc).__name__}"}
            if kind == "open":
                self.close()
        finally:
            timer.cancel()
            with self._watch:
                self._active = ""
        if self.timed_out:
            body = {"status": "failed", "blocker": "worker_timeout"}
            self.close()                                           # the page is gone; FactoryOS closes the session
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
