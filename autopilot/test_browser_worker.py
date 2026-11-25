"""T-714: the dedicated Surfer worker loop and the loop heartbeats. Offline: fake run_one, fake HTTP, fake clock."""
from __future__ import annotations

import pathlib
import sys
import time
import tempfile
import threading
import unittest
from unittest import mock

from autopilot import browser_tasks, browser_worker as bw, worker_heartbeat as hb


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


class Resp:
    def __init__(self, code=200):
        self.status_code = code


class WorkerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = pathlib.Path(self.tmp.name)
        self.clock = Clock()
        self.posts = []
        self.results = []
        self.calls = 0
        p = mock.patch.object(bw.relay_tasks, "endpoint", return_value=("https://factory.example", "tok"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def post(self, url, headers, json, timeout):
        self.posts.append((url, dict(json), headers))
        return Resp()

    def fake_run_one(self, *, on_claim=None):
        self.calls += 1
        result = self.results.pop(0) if self.results else "idle"
        if isinstance(result, tuple):                # ("done", "bt_…"): a task was claimed
            result, task_id = result
            on_claim(task_id)
            # while the task runs, the local heartbeat says "running" with the task and its budget
            beat = hb.read(hb.path_for(self.repo, hb.SURFER_FILE))
            assert beat["state"] == "running" and beat["task"] == task_id, beat
            assert beat["deadline"] - beat["at"] == bw.TASK_BUDGET_SECONDS
        return result

    def worker(self, **kw):
        kw.setdefault("configured", lambda: True)
        kw.setdefault("available", lambda: True)
        return bw.SurferWorker(repo=self.repo, run_one=self.fake_run_one, post=self.post, clock=self.clock,
                               fingerprint=kw.pop("fingerprint", lambda: ("same",)), **kw)

    def test_claim_run_report_and_heartbeats(self):
        w = self.worker()
        self.results = [("done", "bt_0123456789abcdef"), "idle"]
        self.assertEqual(w.pass_once(), ("done", 0.0))          # the next task at once after a finished one
        running = [p for u, p, _ in self.posts if p["state"] == "running"]
        self.assertEqual(running[0]["task_id"], "bt_0123456789abcdef")
        self.assertTrue(all(u == "https://factory.example/api/factory/browser/worker/heartbeat" for u, _, _ in self.posts))
        self.assertEqual(self.posts[-1][2]["Authorization"], "Bearer tok")
        self.assertEqual((self.posts[-1][1]["state"], self.posts[-1][1]["tasks_done"]), ("idle", 1))
        self.assertEqual(w.pass_once(), ("idle", float(bw.POLL_SECONDS)))
        beat = hb.read(hb.path_for(self.repo, hb.SURFER_FILE))
        self.assertEqual(beat["state"], "idle")
        self.assertTrue(hb.alive(hb.path_for(self.repo, hb.SURFER_FILE), now=self.clock.t))
        # The server heartbeat is throttled to one per 30 s while idle.
        n = len(self.posts)
        w.pass_once()
        self.assertEqual(len(self.posts), n)
        self.clock.t += bw.HEARTBEAT_SECONDS
        w.pass_once()
        self.assertEqual(len(self.posts), n + 1)

    def test_self_watchdog_exits_when_the_loop_breaks_its_promise(self):
        # Live run 2026-11-23: the loop hung inside a browser call for 30+ min and the root watchdog did not act.
        w = self.worker()
        now = {"t": 1000.0}
        exits = []
        w.monotonic, w.exit = (lambda: now["t"]), exits.append
        self.assertFalse(w.check_self())                         # no beat yet: nothing promised
        w.local_beat("polling", bw.TASK_BUDGET_SECONDS)
        now["t"] += bw.TASK_BUDGET_SECONDS - 1
        self.assertFalse(w.check_self())
        self.assertEqual(exits, [])
        now["t"] += 2                                            # the pass is stuck past its promise
        self.assertTrue(w.check_self())
        self.assertEqual(exits, [bw.EXIT_CODE_STUCK])
        w.local_beat("idle", 5 + hb.STALE_AFTER_SECONDS)          # a beat renews the promise
        self.assertFalse(w.check_self())
        w.local_beat("stopped", 0)                                # a deliberate stop is never "stuck"
        now["t"] += 10 * 3600
        self.assertFalse(w.check_self())
        self.assertEqual(exits, [bw.EXIT_CODE_STUCK])

    def test_a_beat_that_lands_during_the_check_wins(self):
        # Codex on #460: the exit decision is serialized with deadline renewal.
        import threading as th
        w = self.worker()
        now = {"t": 1000.0}
        exits = []
        w.monotonic, w.exit = (lambda: now["t"]), exits.append
        w.local_beat("polling", 10)
        now["t"] += 11                                           # expired ...
        result = {}
        with w._watch:                                           # ... but the loop is renewing right now
            checker = th.Thread(target=lambda: result.setdefault("fired", w.check_self()))
            checker.start()
            checker.join(0.2)
            self.assertTrue(checker.is_alive())                  # the check waits for the renewal
            w._loop_deadline = now["t"] + 60
        checker.join(5)
        self.assertEqual((result["fired"], exits), (False, []))
        with w._watch:                                           # a stop that lands meanwhile wins too
            checker = th.Thread(target=lambda: result.update(fired=w.check_self()))
            now["t"] += 120
            checker.start()
            w.stop.set()
        checker.join(5)
        self.assertEqual((result["fired"], exits), (False, []))

    def test_a_stalled_loop_exits_the_real_process_with_75(self):
        import subprocess
        import textwrap
        script = textwrap.dedent(f"""
            import pathlib, sys, time
            sys.path.insert(0, {str(bw.ROOT)!r})
            from autopilot import browser_worker as bw
            bw.SELF_WATCHDOG_EVERY_SECONDS = 0.2
            bw.TASK_BUDGET_SECONDS = 1
            def stuck(*, on_claim=None):
                time.sleep(120)                                  # a pass that never returns
            w = bw.SurferWorker(repo=pathlib.Path({str(self.repo)!r}), run_one=stuck, configured=lambda: True,
                                available=lambda: True, post=lambda *a, **k: None, fingerprint=lambda: ())
            w.run()
        """)
        started = time.monotonic()
        proc = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, bw.EXIT_CODE_STUCK, proc.stderr[-500:])
        self.assertLess(time.monotonic() - started, 30)
        self.assertIn("silent past its deadline", proc.stderr)

    def test_a_pass_promises_less_than_the_old_15_minutes(self):
        self.assertLessEqual(bw.TASK_BUDGET_SECONDS, 6 * 60)
        from autopilot import browser_actions as ba
        worst = ba.STAGE_SECONDS + ba.COMMAND_DEADLINE_SECONDS + ba.EXIT_GRACE_SECONDS + 60   # + result post
        self.assertLess(worst, bw.TASK_BUDGET_SECONDS)

    def test_backoff_on_unreachable_queue_and_reset(self):
        w = self.worker()
        self.results = ["error", "error", "error", "error", "error", "error", "error", "idle", "error"]
        waits = [w.pass_once()[1] for _ in range(9)]
        self.assertEqual(waits[:7], [10.0, 20.0, 40.0, 80.0, 120.0, 120.0, 120.0])
        self.assertEqual(waits[7], float(bw.POLL_SECONDS))
        self.assertEqual(waits[8], 10.0)                         # backoff restarts after a good pass

    def test_unavailable_does_not_claim(self):
        w = self.worker(available=lambda: False)
        self.assertEqual(w.pass_once(), ("unavailable", bw.UNAVAILABLE_SECONDS))
        w2 = self.worker(configured=lambda: False)
        self.assertEqual(w2.pass_once()[0], "unavailable")
        self.assertEqual(self.calls, 0)
        self.assertEqual(hb.read(hb.path_for(self.repo, hb.SURFER_FILE))["state"], "unavailable")

    def test_graceful_stop_finishes_the_task_and_releases_the_queue(self):
        stop = threading.Event()
        w = self.worker(stop=stop)

        def run_one(*, on_claim=None):
            self.calls += 1
            on_claim("bt_0123456789abcdef")
            stop.set()                                           # SIGTERM arrives while the task runs
            return "done"
        w.run_one = run_one
        self.assertEqual(w.run(), 0)
        self.assertEqual(self.calls, 1)                          # finished, no further pass
        self.assertEqual(self.posts[-1][1]["state"], "stopped")
        path = hb.path_for(self.repo, hb.SURFER_FILE)
        self.assertEqual(hb.read(path)["state"], "stopped")
        self.assertFalse(hb.alive(path, now=self.clock.t + 1))   # the Claude worker's fallback may take over

    def test_runner_code_change_exits_between_tasks(self):
        versions = iter([("v1",), ("v2",)])
        w = self.worker(fingerprint=lambda: next(versions))
        self.results = ["idle"]
        self.assertEqual(w.run(), bw.EXIT_CODE_UPDATED)
        self.assertEqual(self.calls, 1)

    def test_tasks_run_one_at_a_time(self):
        active, peak = [0], [0]

        def run_one(*, on_claim=None):
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            active[0] -= 1
            return "idle"
        w = self.worker()
        w.run_one = run_one
        w.stop.wait = lambda *_: False
        w.run(max_passes=5)
        self.assertEqual(peak[0], 1)

    def test_single_instance_lock(self):
        path = self.repo / ".autopilot" / "surfer.lock"
        a, b = bw.SingleInstance(path), bw.SingleInstance(path)
        self.assertTrue(a.acquire())
        self.assertFalse(b.acquire())                            # no second Chromium on this checkout
        a.release()
        self.assertTrue(b.acquire())
        b.release()


class RunOneTest(unittest.TestCase):
    """browser_tasks.run_one: on_claim before the browser starts, "error" when the queue is unreachable."""

    def test_on_claim_and_error(self):
        class Http:
            def __init__(self, fail=False):
                self.fail = fail

            def post(self, url, headers, json, timeout):
                if self.fail:
                    raise OSError("down")
                body = {"task": {"id": "bt_0123456789abcdef", "url": "https://shop.example/", "selectors": []}} \
                    if url.endswith("/claim") else {}

                class R:
                    status_code = 200

                    def json(self):
                        return body
                return R()
        seen = []
        with mock.patch.object(browser_tasks.relay_tasks, "configured", return_value=True), \
                mock.patch.object(browser_tasks.relay_tasks, "endpoint", return_value=("https://f", "tok")), \
                mock.patch.object(browser_tasks, "execute", side_effect=lambda task, **k: seen.append(("run", task["id"]))
                                  or {"status": "done", "texts": []}):
            result = browser_tasks.run_one(http=Http(), available=lambda: True,
                                           on_claim=lambda tid: seen.append(("claim", tid)))
            self.assertEqual(result, "done")
            self.assertEqual(seen, [("claim", "bt_0123456789abcdef"), ("run", "bt_0123456789abcdef")])
            self.assertEqual(browser_tasks.run_one(http=Http(fail=True), available=lambda: True), "error")


class QueueNeverSilentTest(unittest.TestCase):
    """T-728: a worker that cannot claim says so; a live action session never parks read tasks."""

    def test_refused_claim_is_an_error_not_idle(self):
        class Http:
            def post(self, url, headers, json, timeout):
                class R:
                    status_code = 401

                    def json(self):
                        return {"detail": "Worker token required"}
                return R()
        with mock.patch.object(browser_tasks.relay_tasks, "configured", return_value=True), \
                mock.patch.object(browser_tasks.relay_tasks, "endpoint", return_value=("https://f", "tok")):
            self.assertEqual(browser_tasks.run_one(http=Http(), available=lambda: True), "error")
            self.assertEqual(browser_tasks.LAST_ERROR["claim"], "claim_http_401")
        posts = []
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bw.relay_tasks, "endpoint", return_value=("https://factory.example", "tok")):
            w = bw.SurferWorker(repo=pathlib.Path(d), run_one=lambda **k: "error", configured=lambda: True,
                                available=lambda: True, clock=Clock(), fingerprint=lambda: ("same",),
                                post=lambda url, headers, json, timeout: posts.append(json) or Resp())
            w.pass_once()
        self.assertEqual((posts[-1]["state"], posts[-1]["last_error"]), ("queue_unreachable", "claim_http_401"))
        browser_tasks.LAST_ERROR["claim"] = ""

    def test_live_action_browser_skips_the_launch_probe_and_reads_still_claim(self):
        class Actions:
            live = "as_1"

            def borrowed_factory(self):
                return lambda: "borrowed"

            def pump(self):
                return "idle"

            def close(self):
                pass
        seen = []

        def run_one(*, on_claim=None, available=None, runner=None):
            seen.append(available())
            return "idle"
        probe = mock.Mock(return_value=False)                  # a second Chromium would not start under the cap
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bw.relay_tasks, "endpoint", return_value=("https://factory.example", "tok")):
            w = bw.SurferWorker(repo=pathlib.Path(d), run_one=run_one, configured=lambda: True, available=probe,
                                clock=Clock(), fingerprint=lambda: ("same",), actions=Actions(),
                                post=lambda *a, **k: Resp())
            result, _ = w.pass_once()
        self.assertEqual((result, seen), ("idle", [True]))      # it asked the server for a read task
        probe.assert_not_called()

    def test_runner_holding_playwright_without_a_page_skips_the_probe(self):
        class Actions:
            live = ""

            def borrowed_factory(self):
                return None

            def holds_playwright(self):
                return True                              # a session is being opened / its Playwright still runs

            def pump(self):
                return "idle"
        calls = []
        probe = mock.Mock(return_value=False)
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bw.relay_tasks, "endpoint", return_value=("https://factory.example", "tok")):
            w = bw.SurferWorker(repo=pathlib.Path(d), run_one=lambda **k: calls.append(1) or "idle",
                                configured=lambda: True, available=probe, clock=Clock(),
                                fingerprint=lambda: ("same",), actions=Actions(), post=lambda *a, **k: Resp())
            self.assertEqual(w.pass_once()[0], "idle")
        self.assertEqual(calls, [1])
        probe.assert_not_called()

    def test_unavailable_still_pumps_actions_and_exits_after_ten_minutes(self):
        class Actions:
            live = ""
            pumps = 0

            def borrowed_factory(self):
                return None

            def holds_playwright(self):
                return False

            def pump(self):
                Actions.pumps += 1
                return "idle"
        exits, mono = [], [1000.0]
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(bw.relay_tasks, "endpoint", return_value=("https://factory.example", "tok")):
            w = bw.SurferWorker(repo=pathlib.Path(d), run_one=lambda **k: "idle", configured=lambda: True,
                                available=lambda: False, clock=Clock(), fingerprint=lambda: ("same",),
                                actions=Actions(), post=lambda *a, **k: Resp())
            w.exit, w.monotonic = exits.append, lambda: mono[0]
            self.assertEqual(w.pass_once()[0], "unavailable")
            self.assertEqual((Actions.pumps, exits), (1, []))   # a live session can still close on its lifetime
            mono[0] += bw.UNAVAILABLE_EXIT_SECONDS - 1
            w.pass_once()
            self.assertEqual(exits, [])
            mono[0] += 2
            w.pass_once()
            self.assertEqual(exits, [bw.EXIT_CODE_STUCK])        # systemd starts a fresh worker
            w.available = lambda: True                           # a working pass resets the stretch
            w.pass_once()
            self.assertEqual(w._unavailable_since, 0.0)


class HeartbeatFileTest(unittest.TestCase):
    def test_alive_and_deadline(self):
        with tempfile.TemporaryDirectory() as d:
            path = hb.path_for(pathlib.Path(d), hb.CLAUDE_LOOP_FILE)
            self.assertFalse(hb.alive(path, now=100))
            self.assertTrue(hb.beat(path, budget_seconds=60, state="idle", now=100))
            self.assertTrue(hb.alive(path, now=150))
            self.assertFalse(hb.alive(path, now=161))
            path.write_text("not json", encoding="utf-8")
            self.assertEqual(hb.read(path), {})


class FallbackTest(unittest.TestCase):
    """The Claude worker loop runs a browser task only while the dedicated Surfer worker is not alive."""

    def test_main_worker_skips_browser_tasks_while_surfer_alive(self):
        from autopilot import autopilot as ap
        with tempfile.TemporaryDirectory() as d:
            beat = hb.path_for(pathlib.Path(d), hb.SURFER_FILE)
            calls = []
            with mock.patch.object(ap, "SURFER_BEAT", beat), \
                    mock.patch.object(ap.browser_tasks, "run_one", side_effect=lambda: calls.append(1) or "done"):
                self.assertTrue(ap.run_browser_fallback())           # no Surfer worker: the loop serves the queue
                hb.beat(beat, budget_seconds=600, state="idle")
                self.assertFalse(ap.run_browser_fallback())          # Surfer alive: no second Chromium
                hb.beat(beat, budget_seconds=0, state="stopped")
                self.assertTrue(ap.run_browser_fallback())           # stopped: the fallback takes over at once
            self.assertEqual(len(calls), 2)

    def test_claude_loop_beats_with_a_long_budget_before_claude_runs(self):
        from autopilot import autopilot as ap
        with tempfile.TemporaryDirectory() as d:
            path = hb.path_for(pathlib.Path(d), hb.CLAUDE_LOOP_FILE)
            with mock.patch.object(ap, "LOOP_BEAT", path):
                ap.loop_beat()
                short = hb.read(path)
                ap.loop_beat("running", long_job=True, task="T-1")
                long = hb.read(path)
            self.assertEqual(short["deadline"] - short["at"],
                             max(ap.IDLE_SECONDS, ap.PAUSE_SECONDS) + hb.STALE_AFTER_SECONDS)
            self.assertEqual(long["deadline"] - long["at"], max(ap.TASK_TIMEOUT_SECONDS, 3600) + hb.STALE_AFTER_SECONDS)
            self.assertEqual((long["state"], long["task"]), ("running", "T-1"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
