"""T-714: the dedicated Surfer worker — Surfer browser tasks in their own long-running process on the EC2 host.

Before T-714 the Claude worker loop ran one browser task *between* coding jobs, so a long Claude CLI job (or a hung
loop) froze the Surfer queue for tens of minutes (2026-11-21, 15:18→16:55 UTC). This process does only browser
tasks: claim → run Playwright (one anonymous Chromium, closed after each task) → report → short sleep, with
exponential backoff while FactoryOS is unreachable.

- Exactly-once stays on the server: ``/api/factory/browser/worker/claim`` hands a task out under a lock with a lease
  (``browser_tasks.BrowserTaskStore.claim``). Locally a file lock keeps a second copy of this worker from starting a
  second Chromium.
- It beats a local heartbeat (``.autopilot/surfer.json``, read by the root supervisor's watchdog and by the Claude
  worker, which skips its in-loop fallback while this worker is alive) and a server heartbeat
  (``/api/factory/browser/worker/heartbeat`` → the "Surfer" lane in Worker Center).
- SIGTERM/SIGINT finish the current task, report "stopped" and exit. When the runner code changes on disk (the Claude
  worker merges main into the checkout) it exits between tasks and systemd starts it again on the new code.

Run: ``python -m autopilot.browser_worker`` (systemd unit ``deploy/systemd/factoryos-surfer-worker.service``).
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import pathlib
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

try:
    from . import browser_actions, browser_tasks, relay_tasks, worker_heartbeat
except ImportError:  # pragma: no cover - run as a plain script
    import browser_actions
    import browser_tasks
    import relay_tasks
    import worker_heartbeat

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO") or ROOT).resolve()
POLL_SECONDS = max(2, min(60, int(os.environ.get("FACTORY_SURFER_POLL_SECONDS", "5"))))
MAX_BACKOFF_SECONDS = 120
UNAVAILABLE_SECONDS = 60                 # no token / no Chromium: check again every minute, quietly
UNAVAILABLE_EXIT_SECONDS = 10 * 60       # T-728: Chromium "unavailable" this long (token configured) → exit 75, restart
HEARTBEAT_SECONDS = 30
# A read task is bounded (~90 s); an action command by browser_actions (60 s staging + 90 s deadline + 20 s grace).
# The beat before a pass promises 6 min: past it the loop is hung (live run 2026-11-23: a stuck browser call kept the
# worker silent for 30+ min while the root supervisor's watchdog did not restart it).
TASK_BUDGET_SECONDS = 6 * 60
EXIT_CODE_UPDATED = 0                    # Restart=always brings it back on the new code
EXIT_CODE_STUCK = 75                     # the self-watchdog: systemd (Restart=always) starts a fresh worker
SELF_WATCHDOG_EVERY_SECONDS = 15
# T-728: a code change ends the process only when it is real and settled: the content hash differs from the one taken
# at start, the same new hash is seen on two checks CODE_CHECK_SECONDS apart, and the worker has run MIN_UPTIME_SECONDS.
CODE_CHECK_SECONDS = 60
MIN_UPTIME_SECONDS = 5 * 60
CODE_FILES = ("autopilot/browser_worker.py", "autopilot/browser_tasks.py", "autopilot/worker_heartbeat.py",
              "autopilot/relay_tasks.py", "autopilot/browser_actions.py")


def _try_write_stderr(text: str) -> None:
    try:
        os.write(2, text.encode("utf-8", "replace"))
    except OSError:
        pass


def log(message: str) -> None:
    print(f"surfer-worker: {message}", file=sys.stderr, flush=True)


def code_fingerprint(root: pathlib.Path = ROOT) -> str:
    """sha256 over the *contents* of the runner's tracked .py files (never __pycache__/.pyc, never mtimes).

    T-728 (EC2 journal 2026-11-25): the former (mtime, size) tuple changed 6-17 s after every start although the code
    had not, so the worker exited "runner code changed" in a loop until systemd's start limit stopped the unit. A
    checkout that rewrites files with the same bytes (the Claude worker's git operations) no longer counts."""
    files = [root / f for f in CODE_FILES] + sorted((root / "browser_runner").glob("*.py"))
    digest = hashlib.sha256()
    for path in files:
        digest.update(str(path.relative_to(root)).encode("utf-8") + b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return digest.hexdigest()


def code_version(root: pathlib.Path = ROOT) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, text=True, capture_output=True,
                                timeout=10, check=False)
        return result.stdout.strip()[:20]
    except (OSError, subprocess.SubprocessError):
        return ""


class SingleInstance:
    """Non-blocking exclusive lock: a second copy on the same checkout refuses to start (no second Chromium)."""

    def __init__(self, path: pathlib.Path):
        self.path = pathlib.Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fh = open(self.path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fh.close()
            return False
        self._fh = fh
        return True

    def release(self) -> None:
        if self._fh:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


class SurferWorker:
    def __init__(self, *, repo: pathlib.Path = REPO, run_one: Callable = browser_tasks.run_one,
                 available: Callable[[], bool] = lambda: browser_tasks.playwright_available(),
                 configured: Callable[[], bool] = relay_tasks.configured, post: Optional[Callable] = None,
                 clock: Callable[[], float] = time.time, stop: Optional[threading.Event] = None,
                 fingerprint: Callable[[], object] = code_fingerprint, version: str = "",
                 actions: Optional["browser_actions.ActionRunner"] = None):
        self.repo = pathlib.Path(repo)
        self.beat_path = worker_heartbeat.path_for(self.repo, worker_heartbeat.SURFER_FILE)
        self.run_one, self.available, self.configured = run_one, available, configured
        self.actions = actions               # T-720: live action sessions (None: read tasks only)
        self.post, self.clock = post, clock
        self.stop = stop or threading.Event()
        self.fingerprint = fingerprint
        self._code = fingerprint()
        self.version = version
        self.started = clock()
        self.backoff = 0.0
        self.done = self.failed = 0
        self.last_result = ""
        self.task_id = ""
        self._last_server_beat = 0.0
        self._loop_deadline = 0.0            # monotonic time by which the loop promised its next beat
        self._watch = threading.Lock()       # deadline renewal / shutdown vs the self-watchdog's exit decision
        self.exit = os._exit
        self.monotonic = time.monotonic
        self._unavailable_since = 0.0        # T-728: monotonic start of the current "Chromium unavailable" stretch
        self._started_mono = self.monotonic()
        self._next_code_check = self._started_mono + MIN_UPTIME_SECONDS
        self._pending_code = None            # a new hash seen once; it must be seen again to count

    # --- self-watchdog ----------------------------------------------------------------------------------------
    def check_self(self) -> bool:
        """True (and the process exits) when the main loop broke the deadline its last beat promised. It does not
        rely on the root supervisor timer: a hung loop is restarted by systemd within the budget plus one check.
        The decision and the exit happen under the same lock as deadline renewal and shutdown, so a beat or a stop
        that lands meanwhile always wins; the exit does not wait for the log line."""
        with self._watch:
            deadline = self._loop_deadline
            if not deadline or self.stop.is_set() or self.monotonic() <= deadline:
                return False
            note = f"surfer-worker: main loop silent past its deadline (task {self.task_id or '-'}); exiting so systemd restarts the worker\n"
            threading.Thread(target=_try_write_stderr, args=(note,), daemon=True).start()
            time.sleep(0.5)                              # give the log line a moment, never more
            self.exit(EXIT_CODE_STUCK)
            return True

    def _self_watchdog(self) -> None:
        while not self.stop.is_set():
            time.sleep(SELF_WATCHDOG_EVERY_SECONDS)
            if self.check_self():
                return

    # --- heartbeats -------------------------------------------------------------------------------------------
    def local_beat(self, state: str, budget: float) -> None:
        with self._watch:
            self._loop_deadline = self.monotonic() + max(0.0, float(budget)) if state != "stopped" else 0.0
        worker_heartbeat.beat(self.beat_path, budget_seconds=budget, state=state, task=self.task_id,
                              now=self.clock(), done=self.done, failed=self.failed)

    def server_beat(self, state: str, *, force: bool = False) -> bool:
        now = self.clock()
        if not force and now - self._last_server_beat < HEARTBEAT_SECONDS:
            return False
        url, token = relay_tasks.endpoint()
        if not (url and token):
            return False
        self._last_server_beat = now
        payload = {"state": state, "task_id": self.task_id, "node_id": socket.gethostname()[:80], "pid": os.getpid(),
                   "version": self.version, "started_at": int(self.started), "tasks_done": self.done,
                   "tasks_failed": self.failed, "last_result": self.last_result[:80],
                   "last_error": str(getattr(browser_tasks, "LAST_ERROR", {}).get("claim") or "")[:80]}
        try:
            if self.post is None:
                import requests
                self.post = requests.post
            response = self.post(url + "/api/factory/browser/worker/heartbeat",
                                 headers={"Authorization": "Bearer " + token}, json=payload, timeout=15)
            return 200 <= int(getattr(response, "status_code", 0)) < 300
        except Exception:
            return False

    def _claimed(self, task_id: str) -> None:
        self.task_id = task_id
        self.local_beat("running", TASK_BUDGET_SECONDS)
        self.server_beat("running", force=True)

    # --- loop -------------------------------------------------------------------------------------------------
    def pass_once(self) -> tuple[str, float]:
        """One claim/run/report pass. Returns (result, seconds to wait before the next pass)."""
        # T-720: while an action session holds Chromium, a read task opens its own anonymous context in that browser.
        # T-728: that live browser already proves Chromium works, so no second launch probe then: under the unit's
        # memory cap the probe could fail and park the worker in "unavailable" (no claims, no action pumping).
        # Incident 2026-11-25 (reproduced with real Playwright): while the action runner held its Playwright, the probe
        # raised "Sync API inside the asyncio loop", the worker returned "unavailable" before pump(), so the action
        # session was never closed either: reads waited for ever while the loop kept beating (no watchdog fired).
        borrowed = self.actions.borrowed_factory() if self.actions else None
        holds = bool(self.actions and getattr(self.actions, "holds_playwright", lambda: False)())
        configured = self.configured()
        if not configured or not (borrowed or holds or self.available()):
            if self.actions and configured:
                self.actions.pump()                      # sessions still close on their lifetime / FactoryOS close
            now = self.monotonic()
            self._unavailable_since = self._unavailable_since or now
            if configured and now - self._unavailable_since > UNAVAILABLE_EXIT_SECONDS:
                # A fresh process (systemd kills the unit's leftover Chromium) is the recovery that worked by hand.
                log(f"Chromium unavailable for {UNAVAILABLE_EXIT_SECONDS // 60} min; exiting so systemd restarts the worker")
                self.server_beat("unavailable", force=True)
                self.exit(EXIT_CODE_STUCK)
                return "unavailable", UNAVAILABLE_SECONDS
            self.local_beat("unavailable", UNAVAILABLE_SECONDS + worker_heartbeat.STALE_AFTER_SECONDS)
            self.server_beat("unavailable")
            return "unavailable", UNAVAILABLE_SECONDS
        self._unavailable_since = 0.0
        self.local_beat("polling", TASK_BUDGET_SECONDS)
        self.task_id = ""
        if borrowed:
            import functools
            result = self.run_one(on_claim=self._claimed, available=lambda: True, runner=functools.partial(
                browser_tasks.run_playwright, playwright_factory=borrowed))
        else:
            result = self.run_one(on_claim=self._claimed)
        if result == "error":
            self.backoff = min(MAX_BACKOFF_SECONDS, max(POLL_SECONDS * 2.0, self.backoff * 2))
            wait = self.backoff
        else:
            self.backoff = 0.0
            wait = 0.0 if result in ("done", "failed") else float(POLL_SECONDS)
        if result in ("done", "failed"):
            self.done += result == "done"
            self.failed += result == "failed"
            self.last_result = f"{self.task_id} {result}".strip()
            self.task_id = ""
            self.server_beat("idle", force=True)
        else:
            self.server_beat("idle" if result == "idle" else "queue_unreachable")
        if self.actions:
            acted = self.actions.pump()
            if acted == "ran":
                wait = 0.0
            elif self.actions.live and result != "error":
                wait = min(wait, browser_actions.LIVE_POLL_SECONDS) if wait else 0.0
            if self.actions.live:
                self.local_beat("running", TASK_BUDGET_SECONDS)
                self.server_beat("running")
                return result, max(wait, 0.2) if acted != "ran" else 0.0
        self.local_beat("idle", wait + worker_heartbeat.STALE_AFTER_SECONDS)
        return result, wait

    def code_changed(self) -> bool:
        """True once a settled change of the runner code was seen (see CODE_CHECK_SECONDS / MIN_UPTIME_SECONDS)."""
        now = self.monotonic()
        if now < self._next_code_check or (self.actions and self.actions.live):
            return False
        self._next_code_check = now + CODE_CHECK_SECONDS
        current = self.fingerprint()
        if current == self._code:
            self._pending_code = None
            return False
        if current != self._pending_code:
            self._pending_code = current             # first sighting: wait one more check (a branch flip settles)
            return False
        return True

    def run(self, max_passes: Optional[int] = None) -> int:
        with self._watch:                    # armed before any startup I/O (a stuck log or beat write counts too)
            self._loop_deadline = self.monotonic() + worker_heartbeat.STALE_AFTER_SECONDS
        threading.Thread(target=self._self_watchdog, name="surfer-self-watchdog", daemon=True).start()
        log(f"started (pid {os.getpid()}, poll {POLL_SECONDS}s)")
        self.local_beat("starting", worker_heartbeat.STALE_AFTER_SECONDS)
        self.server_beat("idle", force=True)
        passes = 0
        code = 0
        while not self.stop.is_set():
            _, wait = self.pass_once()
            passes += 1
            if max_passes is not None and passes >= max_passes:
                break
            if self.code_changed():
                log("runner code changed on disk; exiting between tasks so systemd restarts on the new code")
                code = EXIT_CODE_UPDATED
                break
            if wait:
                self.stop.wait(wait)
        if self.actions:
            self.actions.close()
        # Deadline = now: the Claude worker's fallback may take browser tasks again at once.
        self.local_beat("stopped", 0)
        self.server_beat("stopped", force=True)
        log("stopped")
        return code


def main() -> int:
    lock = SingleInstance(worker_heartbeat.path_for(REPO, "surfer.lock"))
    if not lock.acquire():
        log("another Surfer worker already runs on this checkout; refusing to start a second Chromium")
        return 0
    stop = threading.Event()

    def _graceful(signum, _frame):
        log(f"signal {signum}: finishing the current task, then stopping")
        stop.set()

    signal.signal(signal.SIGTERM, _graceful)
    signal.signal(signal.SIGINT, _graceful)
    try:
        return SurferWorker(stop=stop, version=code_version(), actions=browser_actions.ActionRunner()).run()
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
