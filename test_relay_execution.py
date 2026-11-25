"""Zero-network regressions for Relay auto-queue and Claude execution wiring."""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from relay import RelayStore
from relay_execution import RelayQueue, lifecycle_text, safe_evidence
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
from test_relay_acceptance import AcceptanceTest, ControlRoomTest  # noqa: F401  (T-591 live acceptance verdict)



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
        # Evidence Protocol: the worker's "done" is a claim; without a merged PR + CI the ticket stays open.
        self.assertEqual(finished["status"], "in_progress")
        self.assertEqual(finished["execution"]["state"], "done")
        self.assertEqual([e["action"] for e in finished["history"]], ["queued", "claimed", "running", "committed", "pushed", "done"])
        with self.assertRaises(ValueError):
            self.store.set_status(tid, "done", actor="owner")                 # no evidence, no reason
        self.assertEqual(self.store.set_status(tid, "done", actor="owner", note="checked by hand")["status"], "done")
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



class TestRelayIsolatedRoundTrip(unittest.TestCase):
    """#289: each ticket runs in its own worktree branch from fresh origin/main, pushes it and opens a PR.
    Real git (temporary bare origin + runner clone); the Claude CLI and `gh` are fakes."""

    def setUp(self):
        import subprocess, tempfile
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.origin, self.runner = root / "origin.git", root / "runner"
        run = lambda *a, cwd=root: subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True)
        self.run = run
        run("git", "init", "--bare", "-b", "main", str(self.origin))
        run("git", "clone", str(self.origin), str(self.runner))
        for k, v in (("user.email", "w@example.invalid"), ("user.name", "worker")):
            run("git", "config", k, v, cwd=self.runner)
        (self.runner / "README.md").write_text("hi\n")
        run("git", "add", "README.md", cwd=self.runner); run("git", "commit", "-m", "init", cwd=self.runner)
        run("git", "push", "origin", "HEAD:main", cwd=self.runner)
        run("git", "checkout", "-b", "autopilot/aws-worker", cwd=self.runner)
        (self.runner / "local-notes.txt").write_text("the runner's own dirty file\n")    # must survive untouched
        self.ticket = {"id": "R-0123", "title": "Add verification doc", "execution": {"run_id": "run-1a2b3c4d5e6f"}}

    def tearDown(self):
        self.tmp.cleanup()

    def cli(self, change=True):
        import subprocess
        def fake(cmd, cwd=None, **kw):
            self.assertEqual(cmd[0], "claude")
            self.cwd = Path(cwd)
            if change:
                (Path(cwd) / "docs").mkdir(exist_ok=True)
                (Path(cwd) / "docs" / "verification.md").write_text("ok\n")
                subprocess.run(["git", "add", "-A"], cwd=cwd, check=True)
                subprocess.run(["git", "-c", "user.email=w@example.invalid", "-c", "user.name=w", "commit", "-m", "R-0123 doc"],
                               cwd=cwd, check=True, capture_output=True)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "Added the doc"}), stderr="")
        return fake

    def test_commit_push_pr_without_touching_the_runner(self):
        stages, prs = [], []
        out = relay_tasks.execute_isolated(self.ticket, self.runner, run_cli=self.cli(),
                                           emit_fn=lambda *a, **k: stages.append(a),
                                           pr_fn=lambda wd, br, t, run: (prs.append(br) or ("https://github.com/o/r/pull/77", "")))
        self.assertEqual(out["status"], "done")
        self.assertEqual([s[1] for s in stages], ["running", "committed", "pushed", "done"])
        self.assertEqual(out["branch"], "relay/r-0123-3c4d5e6f")
        self.assertEqual(stages[-1][3]["pr_url"], "https://github.com/o/r/pull/77")
        self.assertEqual(prs, [out["branch"]])
        self.assertNotEqual(self.cwd, self.runner)                                   # ran in its own worktree
        self.assertFalse(self.cwd.exists())                                          # and it was cleaned up
        self.assertEqual(relay_tasks.git(self.runner, "branch", "--show-current")[1], "autopilot/aws-worker")
        self.assertTrue((self.runner / "local-notes.txt").exists())                  # dirty runner file untouched
        remote = self.run("git", "ls-remote", "--heads", str(self.origin)).stdout
        self.assertIn("refs/heads/" + out["branch"], remote)                         # really pushed
        self.assertIn("refs/heads/main", remote)

    def test_no_change_means_done_without_pr(self):
        stages = []
        out = relay_tasks.execute_isolated(self.ticket, self.runner, run_cli=self.cli(change=False),
                                           emit_fn=lambda *a, **k: stages.append(a),
                                           pr_fn=lambda *a: self.fail("no PR without a commit"))
        self.assertEqual(([s[1] for s in stages], out["status"]), (["running", "done"], "done"))

    def test_pushed_but_no_pr_is_blocked_not_done(self):
        stages = []
        out = relay_tasks.execute_isolated(self.ticket, self.runner, run_cli=self.cli(),
                                           emit_fn=lambda *a, **k: stages.append(a),
                                           pr_fn=lambda *a: ("", "gh unavailable: FileNotFoundError"))
        self.assertEqual(out["status"], "blocked")
        self.assertEqual([s[1] for s in stages], ["running", "committed", "pushed", "blocked"])
        self.assertIn("PR не создан", stages[-1][2])

    def test_branch_name_is_safe(self):
        self.assertEqual(relay_tasks.relay_branch("R-0123", "run-1a2b3c4d5e6f"), "relay/r-0123-3c4d5e6f")
        self.assertEqual(relay_tasks.relay_branch("../x", ""), "relay/x-run")

    def agent_ticket(self, mode):
        return {**self.ticket, "source": {"channel": "agent_workspace", "requested_by": "chatgpt", "mode": mode,
                                          "thread_id": "th_1", "message_id": "msg_1"}}

    def test_t736_agent_request_prompt_is_framed_as_data(self):
        owner = relay_tasks.build_prompt(self.ticket, "relay/x")
        self.assertIn("явно поставленную пользователем", owner)
        agent = relay_tasks.build_prompt(self.agent_ticket("read_only"), "relay/x")
        self.assertNotIn("явно поставленную пользователем", agent)
        self.assertIn("ИИ-агент chatgpt", agent)
        self.assertIn("не распоряжение владельца", agent)
        self.assertIn("Режим read_only", agent)
        self.assertNotIn("Режим read_only", relay_tasks.build_prompt(self.agent_ticket("code"), "relay/x"))

    def test_t736_read_only_request_never_pushes_a_commit(self):
        stages = []
        out = relay_tasks.execute_isolated(self.agent_ticket("read_only"), self.runner, run_cli=self.cli(),
                                           emit_fn=lambda *a, **k: stages.append(a),
                                           pr_fn=lambda *a: self.fail("no PR for a read-only request"),
                                           push_fn=lambda: self.fail("no push for a read-only request"))
        self.assertEqual((out["status"], [s[1] for s in stages]), ("blocked", ["running", "blocked"]))
        self.assertIn("read_only", stages[-1][2])
        remote = self.run("git", "ls-remote", "--heads", str(self.origin)).stdout
        self.assertNotIn("relay/", remote)
        stages.clear()
        again = {**self.agent_ticket("read_only"), "execution": {"run_id": "run-0f0e0d0c0b0a"}}   # a new claim, new run
        out = relay_tasks.execute_isolated(again, self.runner, run_cli=self.cli(change=False),
                                           emit_fn=lambda *a, **k: stages.append(a))
        self.assertEqual((out["status"], [s[1] for s in stages]), ("done", ["running", "done"]))

    def test_t736_read_only_request_refused_in_shared_branch_mode(self):
        stages = []
        out = relay_tasks.execute(self.agent_ticket("read_only"), self.runner,
                                  run_cli=lambda *a, **k: self.fail("Claude must not start"),
                                  emit_fn=lambda *a, **k: stages.append(a))
        self.assertEqual((out["status"], [s[1] for s in stages]), ("blocked", ["blocked"]))



class TestRelayPrReconcile(unittest.TestCase):
    """#289 server side: the ticket's PR is followed from the GitHub snapshot; each transition is told once."""

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)
        t, _ = self.store.create("Round trip")
        self.tid = t["id"]
        claimed = self.queue.claim("w1")
        run = claimed["execution"]["run_id"]
        self.url = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/901"
        self.queue.event(self.tid, "w1", "running", "", {}, run_id=run, event_id=run + ":1:running")
        self.queue.event(self.tid, "w1", "done", "PR opened", {"pr_url": self.url, "branch": "relay/r-0001-x"},
                         run_id=run, event_id=run + ":2:done")

    def tearDown(self):
        self.tmp.cleanup()

    def pr(self, **over):
        return {"number": 901, "html_url": self.url, "state": "open", "merged_at": None, "head": {"sha": "abc123"}, **over}

    def test_ci_then_merge_each_told_once(self):
        q = self.queue
        self.assertEqual(q.reconcile_pull_requests([self.pr()], {}), [])                              # CI unknown: silent
        self.assertEqual(q.reconcile_pull_requests([self.pr()], {"abc123": {"state": "running"}}), [])
        n = q.reconcile_pull_requests([self.pr()], {"abc123": {"state": "failed", "failed": "syntax-and-smoke"}})
        self.assertEqual([(x["action"], "CI упал (syntax-and-smoke)" in x["text"]) for x in n], [("ci", True)])
        self.assertEqual(q.reconcile_pull_requests([self.pr()], {"abc123": {"state": "failed", "failed": "x"}}), [])  # no repeat
        n = q.reconcile_pull_requests([self.pr(head={"sha": "def456"})], {"def456": {"state": "passed"}})
        self.assertIn("готов к ревью и мержу", n[0]["text"])
        n = q.reconcile_pull_requests([self.pr(state="closed", merged_at="2026-11-08T20:00:00Z")], {})
        self.assertEqual(n[0]["action"], "merged")
        self.assertEqual(q.reconcile_pull_requests([self.pr(state="closed", merged_at="2026-11-08T20:00:00Z")], {}), [])
        text = lifecycle_text(self.store.get(self.tid))
        self.assertIn("✅ ci", text)
        self.assertIn("merged", text)
        self.assertNotIn("merged — не проверено", text)
        self.assertIn("deployed — не проверено", text)                                # deploy is still not claimed

    def test_closed_without_merge_and_missing_pr(self):
        self.assertEqual(self.queue.reconcile_pull_requests([], {}), [])                              # not in the read
        n = self.queue.reconcile_pull_requests([self.pr(state="closed")], {})
        self.assertEqual(n[0]["action"], "pr_closed")
        self.assertEqual(self.queue.reconcile_pull_requests([self.pr(state="closed")], {}), [])

    def test_failed_ci_shows_red_in_the_trace(self):
        self.queue.reconcile_pull_requests([self.pr()], {"abc123": {"state": "failed", "failed": "ui"}})
        self.assertIn("❌ ci", lifecycle_text(self.store.get(self.tid)))


if __name__ == "__main__":
    unittest.main()
