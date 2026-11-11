"""#241 One Relay event → at most one owner notice, across restarts, retries, out-of-order and redelivered webhooks.

Offline: a fake notifier, a persistent tempfile store, and a fresh RelayStore/RelayQueue/app per "process" so a
restart is real (only the JSON file survives). No Telegram calls.
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI

from relay import (RelayStore, RelayWorkerClaimRequest, RelayWorkerEventRequest, install_relay_routes,
                   relay_handle_telegram_update)
from relay_execution import RelayQueue

OWNER = {"role": "owner", "email": "owner@example.test"}


class Process:
    """One server process over the shared file: routes, queue and a notifier trace."""

    def __init__(self, path: Path, trace: list):
        self.store = RelayStore(path)
        self.queue = RelayQueue(self.store)
        app = FastAPI()
        install_relay_routes(app, self.store, lambda r: OWNER, queue=self.queue, authorize_worker=lambda r: True,
                             notify_owner=trace.append)
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

    def run(self, tid):
        return self.h[("POST", "/api/relay/{ticket_id}/run")](tid, None)

    def claim(self, worker="claude-ec2"):
        return self.h[("POST", "/api/relay/worker/claim")](RelayWorkerClaimRequest(worker_id=worker), None)["ticket"]

    def event(self, tid, stage, event_id, run_id="", worker="claude-ec2"):
        try:
            return self.h[("POST", "/api/relay/worker/event")](RelayWorkerEventRequest(
                ticket_id=tid, worker_id=worker, stage=stage, note=stage, run_id=run_id, event_id=event_id), None)
        except Exception as exc:
            return getattr(exc, "status_code", exc)


class NotifyDedupeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "relay.json"
        self.trace = []
        self.p = Process(self.path, self.trace)
        ticket, _ = self.p.store.create("Fix the Workers page", source={"channel": "factoryos", "source_key": "k1"})
        self.tid = ticket["id"]

    def tearDown(self):
        self.dir.cleanup()

    def start(self):
        self.p.run(self.tid)
        t = self.p.claim()
        return t["execution"]["run_id"]

    def test_1_retried_event_after_restart_notifies_once(self):
        run = self.start()
        self.assertEqual(self.p.event(self.tid, "running", "e-1", run)["ok"], True)
        restarted = Process(self.path, self.trace)                       # new process, same file
        again = restarted.event(self.tid, "running", "e-1", run)
        self.assertTrue(again["ticket"].get("replayed"))
        running = [t for t in self.trace if t.startswith(f"⚙️ {self.tid} · Claude работает над задачей")]
        self.assertEqual(len(running), 1)                                         # exactly one notice

    def test_2_repeated_run_is_silent_only_a_real_retry_notifies(self):
        self.p.run(self.tid)
        self.p.run(self.tid)                                             # refresh / double tap while queued
        run = self.p.claim()["execution"]["run_id"]
        self.p.event(self.tid, "running", "e-1", run)
        Process(self.path, self.trace).run(self.tid)                     # after a restart, while running
        self.assertEqual(sum("передано Claude" in t for t in self.trace), 0)
        lost = Process(self.path, self.trace)
        lost.queue.stale_seconds = -1                                    # the worker lost contact
        lost.run(self.tid)                                               # owner Retry: a real requeue
        lost.run(self.tid)                                               # tapped twice
        self.assertEqual(sum("передано Claude" in t for t in self.trace), 1)

    def test_3_out_of_order_late_event_after_done_is_refused_silently(self):
        run = self.start()
        self.p.event(self.tid, "running", "e-1", run)
        self.p.event(self.tid, "done", "e-3", run)
        n = len(self.trace)
        self.assertEqual(self.p.event(self.tid, "pushed", "e-2", run), 409)   # arrives after done
        self.assertEqual(len(self.trace), n)

    def test_4_superseded_run_cannot_notify(self):
        run = self.start()
        n = len(self.trace)
        self.assertEqual(self.p.event(self.tid, "running", "e-9", "old-run"), 409)
        self.assertEqual(len(self.trace), n)
        self.p.event(self.tid, "running", "e-1", run)
        self.assertEqual(len(self.trace), n + 1)

    def test_5_redelivered_telegram_update_answers_once(self):
        sent = []
        api = lambda method, payload=None: sent.append((method, (payload or {}).get("text", ""))) or {"ok": True}
        update = {"update_id": 5501, "message": {"message_id": 9, "chat": {"id": 42, "type": "private"},
                                                 "from": {"id": 42}, "text": "/new Проверить дедуп"}}
        first = relay_handle_telegram_update(update, self.p.store, lambda: {"chat_id": "42"}, api, queue=self.p.queue)
        restarted = Process(self.path, self.trace)
        second = relay_handle_telegram_update(update, restarted.store, lambda: {"chat_id": "42"}, api, queue=restarted.queue)
        self.assertTrue(first["created"])
        self.assertEqual((second["created"], second.get("replayed")), (False, True))
        self.assertEqual(second["ticket_id"], first["ticket_id"])
        self.assertEqual(sum(1 for m, _ in sent if m == "sendMessage"), 1)

    def test_6_pr_transitions_once_across_restart(self):
        run = self.start()
        self.p.event(self.tid, "pushed", "e-1", run)
        store = self.p.store
        with store.lock:
            state = store._load_unlocked()
            item = next(x for x in state["tickets"] if x["id"] == self.tid)
            item["execution"]["pr_url"] = "https://github.com/o/r/pull/7"
            store._save_unlocked(state)
        pulls = [{"html_url": "https://github.com/o/r/pull/7", "state": "open", "head": {"sha": "s"}}]
        self.assertEqual(len(self.p.queue.reconcile_pull_requests(pulls, {"s": {"state": "passed"}})), 1)
        restarted = Process(self.path, self.trace)
        self.assertEqual(restarted.queue.reconcile_pull_requests(pulls, {"s": {"state": "passed"}}), [])
        merged = [{**pulls[0], "state": "closed", "merged_at": "2026-11-09T10:00:00Z"}]
        self.assertEqual([n["action"] for n in restarted.queue.reconcile_pull_requests(merged, {})], ["merged"])
        self.assertEqual(Process(self.path, self.trace).queue.reconcile_pull_requests(merged, {}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
