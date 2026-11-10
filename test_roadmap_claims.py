"""T-599-C/D: ROADMAP tasks run only under a verified server claim (no network, no Claude)."""
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from relay import RelayStore
from relay_execution import RelayQueue
from autopilot import relay_tasks

TASK = {"id": "T-901", "title": "Example roadmap task", "owner": "claude"}


class TestRoadmapClaims(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "relay.json"
        self.store = RelayStore(self.path)
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def _expire(self, tid):
        with self.store.lock:
            data = self.store._load_unlocked()
            for item in data["tickets"]:
                if item["id"] == tid:
                    item["execution"]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
            self.store._save_unlocked(data)

    def test_a_claim_then_worker_events(self):
        ticket, reason = self.queue.claim_roadmap("claude-ec2", "claude", "T-901", "Example", "claude")
        self.assertEqual(reason, "")
        ex = ticket["execution"]
        self.assertEqual(ex["state"], "claimed")
        self.assertTrue(ex["run_id"].startswith("run-"))
        self.assertEqual(ticket["source"]["source_key"], "roadmap:T-901")
        run_id = ex["run_id"]
        for stage, evidence in (("running", {"branch": "autopilot/aws-worker"}), ("committed", {"commit": "ab" * 20}),
                                ("pushed", {"pushed": True}), ("done", {})):
            self.queue.event(ticket["id"], "claude-ec2", stage, stage, evidence, run_id=run_id, event_id=f"{run_id}:{stage}")
        final = self.store.get(ticket["id"])
        # Evidence Protocol: a commit is a link, not proof; the ticket waits for a merged PR + CI or the owner.
        self.assertEqual((final["status"], final["execution"]["state"]), ("in_progress", "done"))
        self.assertEqual([h["action"] for h in final["history"]],
                         ["queued", "claimed", "running", "committed", "pushed", "done"])

    def test_b_conflict_only_one_claim_wins(self):
        first, _ = self.queue.claim_roadmap("claude-ec2", "claude", "T-902", owner="any")
        second, reason = self.queue.claim_roadmap("gpt-runner", "chatgpt", "T-902", owner="any")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("already claimed", reason)
        # A lane never takes another lane's task, and generic Relay claims never pick ROADMAP tickets.
        foreign, reason = self.queue.claim_roadmap("claude-ec2", "claude", "T-903", owner="chatgpt")
        self.assertIsNone(foreign)
        self.assertIn("lane chatgpt", reason)
        self.assertIsNone(self.queue.claim("claude-other"))
        self.assertEqual(len(self.store.list()), 1)  # one ticket per task, none for the refused lane

    def test_c_restart_keeps_state_and_never_reruns_silently(self):
        ticket, _ = self.queue.claim_roadmap("claude-ec2", "claude", "T-904", owner="claude")
        self.queue.event(ticket["id"], "claude-ec2", "running", "started", run_id=ticket["execution"]["run_id"])
        restarted = RelayQueue(RelayStore(self.path))
        again, reason = restarted.claim_roadmap("claude-ec2", "claude", "T-904", owner="claude")
        self.assertIsNone(again)
        self.assertIn("already running", reason)
        self._expire(ticket["id"])
        stale, reason = restarted.claim_roadmap("claude-ec2", "claude", "T-904", owner="claude")
        self.assertIsNone(stale)
        self.assertIn("owner Retry", reason)
        # Owner Retry re-queues; only the ROADMAP claim (not the generic Relay claim) picks it up.
        restarted.enqueue(ticket["id"])
        self.assertIsNone(restarted.claim("claude-ec2"))
        retried, reason = restarted.claim_roadmap("claude-ec2", "claude", "T-904", owner="claude")
        self.assertEqual(reason, "")
        self.assertNotEqual(retried["execution"]["run_id"], ticket["execution"]["run_id"])

    def test_d_blocked_then_reclaim_after_owner_input(self):
        ticket, _ = self.queue.claim_roadmap("claude-ec2", "claude", "T-905", owner="claude")
        run_id = ticket["execution"]["run_id"]
        blocked = self.queue.event(ticket["id"], "claude-ec2", "blocked", "needs owner decision", run_id=run_id)
        self.assertEqual(blocked["status"], "need_you")
        # Late event from the superseded run is rejected after a new claim.
        again, _ = self.queue.claim_roadmap("claude-ec2", "claude", "T-905", owner="claude")
        with self.assertRaises(ValueError):
            self.queue.event(ticket["id"], "claude-ec2", "running", "late", run_id=run_id)
        self.assertEqual(self.store.get(ticket["id"])["execution"]["run_id"], again["execution"]["run_id"])

    def test_invalid_input_rejected(self):
        for args in (("bad id!", "claude", "T-1"), ("w", "Claude!", "T-1"), ("w", "claude", "not-a-task")):
            with self.assertRaises(ValueError):
                self.queue.claim_roadmap(*args)


class TestWorkerSide(unittest.TestCase):
    def test_claim_roadmap_client(self):
        calls = []

        def post(path, data):
            calls.append((path, data))
            return {"ticket": {"id": "R-0001", "execution": {"run_id": "run-1"}}, "rejected": ""}

        ticket, reason = relay_tasks.claim_roadmap(TASK, "claude", post_fn=post)
        self.assertEqual((ticket["id"], reason), ("R-0001", ""))
        self.assertEqual(calls[0][0], "/api/relay/worker/roadmap-claim")
        self.assertEqual(calls[0][1]["task_id"], "T-901")
        refused, reason = relay_tasks.claim_roadmap(TASK, "claude", post_fn=lambda p, d: {"ticket": None, "rejected": "busy"})
        self.assertIsNone(refused)
        self.assertEqual(reason, "busy")

    def test_unconfigured_worker_never_claims(self):
        with unittest.mock.patch.dict("os.environ", {"FACTORYOS_URL": "", "FACTORY_CLAUDE_WORKER_TOKEN": ""}):
            ticket, reason = relay_tasks.claim_roadmap(TASK, "claude")
        self.assertIsNone(ticket)
        self.assertIn("not configured", reason)

    def test_reporter_event_ids_and_failures_swallowed(self):
        sent = []

        def emit(tid, stage, note, evidence, *, run_id, event_id):
            sent.append((stage, event_id))
            if stage == "committed":
                raise RuntimeError("network down")

        report = relay_tasks.RunReporter({"id": "R-0001", "execution": {"run_id": "run-9"}}, emit_fn=emit, interval=0.01)
        with report:
            report("running", "started")
            report("committed", "c")
        report("done", "ok")
        stages = [s for s, _ in sent if s != "heartbeat"]
        self.assertEqual(stages, ["running", "committed", "done"])
        self.assertEqual(sent[0][1], "run-9:1:running")
        self.assertTrue(all(e == "" for s, e in sent if s == "heartbeat"))


if __name__ == "__main__":
    unittest.main()
