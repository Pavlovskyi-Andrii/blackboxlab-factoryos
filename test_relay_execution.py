"""Zero-network regressions for Relay auto-queue and Claude execution wiring."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relay import RelayStore
from relay_execution import RelayQueue, safe_evidence
from autopilot import relay_tasks
# T-590 vertical-slice suite; imported here so the existing CI step runs it.
from test_relay_lifecycle import TestEndToEndSlice, TestOwnerIntake, TestWorkerLifecycle  # noqa: F401
from test_relay_livefix import TestTelegramLiveFix  # noqa: F401
from test_roadmap_claims import TestRoadmapClaims, TestWorkerSide  # noqa: F401  (T-599-C/D)
from test_lane_board import TestApi, TestLaneStates, TestTelegramMatchesWeb, TestWebRenderer  # noqa: F401  (T-599-F)
from test_issue_intake import TestIssueIntake  # noqa: F401  (T-599-E; no workflow edit possible)
from test_intake_fallback_contract import IntakeFallbackContract  # noqa: F401  (#258)
from test_relay_smoke_evidence import SmokeEvidenceTest
from test_intake_pagination import FetchAllTest, IntakeTest as PaginationIntakeTest, SnapshotTest  # #259  # noqa: F401  (#260)
from test_worker_observability import TestEvidence, TestSignals  # noqa: F401  (T-596)
from test_worker_observability import TestTelegramMatchesWeb as TestWorkerTelegramMatchesWeb  # noqa: F401
from test_worker_observability import TestWebRenderer as TestWorkerWebRenderer  # noqa: F401
from test_t599_acceptance import (TestA_NormalTask, TestB_Conflict, TestC_Restart, TestD_Blocked,  # noqa: F401  (T-599)
                                  TestE_Freshness, TestF_NoFabricatedActivity, TestRealRoadmap)



class TestRelayQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_new_ticket_queued_not_running(self):
        ticket, created = self.store.create("Fix Worker UI", "Confirm real execution")
        self.assertTrue(created)
        self.assertEqual(ticket["status"], "inbox")
        self.assertEqual(ticket["execution"]["state"], "queued")
        self.assertEqual(ticket["execution"]["owner"], "claude")
        self.assertNotIn("started_at", ticket["execution"])
        self.assertEqual(ticket["history"][-1]["action"], "queued")

    def test_single_claim_and_status_lifecycle(self):
        ticket, _ = self.store.create("Relay automatic test")
        tid = ticket["id"]
        claimed = self.queue.claim("claude-ec2-1")
        self.assertEqual(claimed["id"], tid)
        self.assertEqual(claimed["execution"]["state"], "claimed")
        self.assertEqual(self.store.get(tid)["status"], "inbox")  # no fake running
        self.assertIsNone(self.queue.claim("claude-ec2-1"))
        self.assertIsNone(self.queue.claim("claude-ec2-2"))
        self.queue.event(tid, "claude-ec2-1", "running", "CLI subprocess started", {"branch": "autopilot/aws-worker"})
        self.assertEqual(self.store.get(tid)["status"], "in_progress")
        self.assertEqual(self.queue.event(tid, "claude-ec2-1", "heartbeat")["execution"]["state"], "running")
        self.queue.event(tid, "claude-ec2-1", "committed", "Local commit", {"commit": "deadbeef"*5})
        self.queue.event(tid, "claude-ec2-1", "pushed", "git push returned 0", {"pushed": True})
        finished = self.queue.event(tid, "claude-ec2-1", "done", "CLI succeeded")
        self.assertEqual(finished["status"], "done")
        self.assertEqual(finished["execution"]["state"], "done")
        self.assertEqual([e["action"] for e in finished["history"]], ["queued", "claimed", "running", "committed", "pushed", "done"])
        self.assertEqual(self.queue.claim("claude-ec2-1"), None)

    def test_durable_restart_retry_and_no_duplicate(self):
        t, _ = self.store.create("Test persistence")
        tid = t["id"]
        first = self.queue.enqueue(tid)
        self.assertEqual(first["execution"]["attempts"], 0)
        self.queue.claim("worker")
        self.queue.event(tid, "worker", "blocked", "Needs owner input")
        after_restart = RelayQueue(RelayStore(Path(self.tmp.name) / "relay.json"))
        self.assertEqual(after_restart.view(after_restart.store.get(tid))["execution"]["state"], "blocked")
        after_restart.enqueue(tid)
        claimed = after_restart.claim("worker")
        self.assertEqual(claimed["execution"]["attempts"], 2)

    def test_invalid_worker_and_fake_events_rejected(self):
        t, _ = self.store.create("Avoid fake activity")
        with self.assertRaises(ValueError): self.queue.claim("bad worker ID")
        self.queue.claim("good-worker")
        with self.assertRaises(ValueError): self.queue.event(t["id"], "wrong", "done", "fake")
        with self.assertRaises(ValueError): self.queue.event(t["id"], "good-worker", "invalid", "fake")
        self.assertEqual(self.store.get(t["id"])["execution"]["state"], "claimed")

    def test_stale_shown_without_fake_recovery(self):
        t, _ = self.store.create("Stale task")
        self.queue.claim("worker")
        with self.store.lock:
            d = self.store._load_unlocked()
            d["tickets"][0]["execution"]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
            self.store._save_unlocked(d)
        self.assertEqual(self.queue.view(self.store.get(t["id"]))["execution"]["state"], "stale")
        self.assertIsNone(self.queue.claim("other-worker"))
        self.assertEqual(self.store.get(t["id"])["execution"]["state"], "claimed")
        retried = self.queue.enqueue(t["id"])
        self.assertEqual(retried["execution"]["state"], "queued")
        self.assertEqual(self.queue.claim("other-worker")["id"], t["id"])

    def test_evidence_allowlist_excludes_secrets(self):
        val = safe_evidence({"commit": "a"*40, "branch": "autopilot/aws-worker", "pushed": True,
                             "password": "dont-save", "token": "dont-save", "paid_api_key": "dont-save"})
        self.assertNotIn("password", str(val))
        self.assertNotIn("dont-save", str(val))
        self.assertTrue(val["pushed_reported"])

    def test_nonexistent_and_empty_ticket_id_operations(self):
        t, _ = self.store.create("Existing task")
        with self.assertRaises(KeyError):
            self.queue.enqueue("R-9999")
        with self.assertRaises(KeyError):
            self.queue.event("R-9999", "good-worker", "running")
        with self.assertRaises(KeyError):
            self.queue.enqueue("")
        with self.assertRaises(KeyError):
            self.queue.event("", "good-worker", "running")

        with self.store.lock:
            tickets = self.store._load_unlocked()["tickets"]
            self.assertEqual(len(tickets), 1)
            self.assertEqual(tickets[0]["id"], t["id"])


class TestRelayCli(unittest.TestCase):
    def test_no_execution_on_main(self):
        stages = []
        with patch.object(relay_tasks, "git", return_value=(0, "main")):
            result = relay_tasks.execute({"id": "R-0001", "title": "Test"},
                                         Path("/tmp/relay-fake"),
                                         emit_fn=lambda *args, **kwargs: stages.append(args),
                                         run_cli=lambda *args, **kwargs: self.fail("CLI must not run"))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(stages[-1][1], "blocked")

    def test_dirty_checkout_names_the_paths(self):
        stages = []
        porcelain = "M ROADMAP.md\n?? .autopilot/mycast.json\n?? weird name;rm -rf.txt\n?? a\n?? b\n?? c\n?? d"
        def fake_git(repo, *args):
            if args == ("branch", "--show-current"): return 0, "autopilot/aws-worker"
            if args == ("status", "--porcelain"): return 0, porcelain
            raise AssertionError(args)
        with patch.object(relay_tasks, "git", side_effect=fake_git):
            result = relay_tasks.execute({"id": "R-0001", "title": "T"}, Path("/tmp/relay-fake"),
                                         emit_fn=lambda *args, **kwargs: stages.append(args),
                                         run_cli=lambda *args, **kwargs: self.fail("CLI must not run on a dirty tree"))
        self.assertEqual(result["status"], "blocked")
        note = stages[-1][2]
        self.assertTrue(note.startswith("Runner checkout has uncommitted changes (M ROADMAP.md, ?? .autopilot/mycast.json"))
        self.assertIn("weird_name_rm_-rf.txt", note)
        self.assertIn("+2 more", note)
        self.assertTrue(note.endswith("do not risk overwriting them"))

    def test_real_cli_result_and_commit_push_stages(self):
        stages = []
        heads = iter(["a"*40, "b"*40])
        def fake_git(repo, *args):
            if args == ("branch", "--show-current"): return 0, "autopilot/aws-worker"
            if args == ("status", "--porcelain"): return 0, ""
            if args == ("rev-parse", "HEAD"): return 0, next(heads)
            raise AssertionError(args)
        def fake_run(cmd, **kwargs):
            self.assertEqual(cmd[0], "claude")
            self.assertIn("--disallowedTools", cmd)
            self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "Completed the task"}), stderr="")
        with patch.object(relay_tasks, "git", side_effect=fake_git):
            result = relay_tasks.execute({"id": "R-0001", "title": "Fix UI"},
                                         Path("/tmp/relay-fake"),
                                         run_cli=fake_run,
                                         emit_fn=lambda *args, **kwargs: stages.append(args),
                                         push_fn=lambda: 0)
        self.assertEqual(result["status"], "done")
        self.assertEqual([x[1] for x in stages], ["running", "committed", "pushed", "done"])
        self.assertEqual(stages[-1][3]["commit"], "b"*40)

    def test_failed_cli_must_not_be_done(self):
        stages=[]
        def fake_git(repo, *args):
            return 0, ("autopilot/aws-worker" if args == ("branch", "--show-current")
                       else "a"*40 if args == ("rev-parse", "HEAD") else "")
        with patch.object(relay_tasks, "git", side_effect=fake_git):
            result = relay_tasks.execute({"id": "R-0002", "title": "Failed"},
                                         Path("/tmp/relay-fake"),
                                         run_cli=lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr=""),
                                         emit_fn=lambda *args, **kwargs: stages.append(args))
        self.assertNotEqual(result["status"], "done")
        self.assertEqual(stages[-1][1], "blocked")


if __name__ == "__main__":
    unittest.main()
