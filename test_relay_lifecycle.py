"""T-590 deterministic vertical slice: owner intake -> durable ticket -> authenticated
worker claim (run_id) -> idempotent events -> commit/push evidence -> Telegram /task
and Web view from the same backend record. No network, tokens, spend or messages.
"""
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import requests

from relay import RelayStore, relay_handle_telegram_update
from relay_execution import RelayQueue, lifecycle, lifecycle_text, redact
from autopilot import relay_tasks

GITHUB = {"available": True, "repo": "org/repo", "checked_at": "2026-10-29T09:00:00Z",
          "issues": [{"number": 41, "title": "Relay Telegram control room", "state": "open",
                      "url": "https://github.com/org/repo/issues/41"}], "pulls": []}


class SliceBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "relay.json"
        self.store = RelayStore(self.path)
        self.queue = RelayQueue(self.store)
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def tg(self, method, payload=None):
        self.calls.append((method, payload or {}))
        return {"ok": True}

    def update(self, text, update_id, chat="42", github=None):
        return relay_handle_telegram_update(
            {"update_id": update_id, "message": {"chat": {"id": int(chat), "type": "private"}, "text": text, "message_id": update_id}},
            self.store, lambda: {"chat_id": "42"}, self.tg, None, (lambda: github) if github else None, self.queue)

    def last_text(self):
        return [p["text"] for m, p in self.calls if m == "sendMessage"][-1]


class TestOwnerIntake(SliceBase):
    def test_telegram_message_creates_one_queued_ticket_and_dedupes_replay(self):
        first = self.update("/new Fix Worker Center stale heartbeat", 900)
        again = self.update("/new Fix Worker Center stale heartbeat", 900)  # Telegram webhook retry
        self.assertTrue(first["created"])
        self.assertFalse(again["created"])
        self.assertEqual(first["ticket_id"], again["ticket_id"])
        self.assertEqual(self.store.summary()["total"], 1)
        ticket = self.queue.view(self.store.get(first["ticket_id"]))
        self.assertEqual(ticket["execution"]["state"], "queued")
        states = {row["stage"]: row["state"] for row in ticket["lifecycle"]}
        self.assertEqual(states["queued"], "recorded")
        self.assertEqual(states["claimed"], "pending")
        self.assertEqual(states["running"], "pending")

    def test_unpaired_chat_cannot_create(self):
        self.assertIsNone(self.update("/new hijack", 901, chat="7"))
        self.assertEqual(self.store.summary()["total"], 0)

    def test_github_issue_intake_is_idempotent_and_verified(self):
        r1 = self.update("/issue 41", 902, github=GITHUB)
        r2 = self.update("/issue #41", 903, github=GITHUB)
        self.assertTrue(r1["created"])
        self.assertFalse(r2["created"])
        self.assertEqual(r1["ticket_id"], r2["ticket_id"])
        self.assertIn("повторно не ставлю", self.last_text())
        ticket = self.store.get(r1["ticket_id"])
        self.assertEqual(ticket["source"]["source_key"], "github-issue:org/repo#41")
        self.assertEqual(ticket["execution"]["state"], "queued")
        # Unknown/unverifiable issue numbers never become tickets.
        r3 = self.update("/issue 999", 904, github=GITHUB)
        self.assertEqual(r3["action"], "issue_unverified")
        r4 = self.update("/issue 41", 905, github={"available": False})
        self.assertEqual(r4["action"], "issue_unverified")
        self.assertEqual(self.store.summary()["total"], 1)

    def test_api_intake_validation(self):
        with self.assertRaises(ValueError):
            self.queue.intake_github_issue(0, "x")
        with self.assertRaises(ValueError):
            self.queue.intake_github_issue(5, "x", url="https://evil.example/issues/5")
        ticket, created = self.queue.intake_github_issue(5, "Token ghp_abcdefghijklmnopqrstuvwxyz in title",
                                                         url="https://github.com/org/repo/issues/5", repo="org/repo")
        self.assertTrue(created)
        self.assertNotIn("ghp_", ticket["title"])
        _, created = self.queue.intake_github_issue(5, "renamed", repo="org/repo")
        self.assertFalse(created)


class TestWorkerLifecycle(SliceBase):
    def test_claim_run_id_and_idempotent_events(self):
        ticket, _ = self.store.create("Relay slice")
        claimed = self.queue.claim("claude-ec2")
        run_id = claimed["execution"]["run_id"]
        self.assertTrue(run_id.startswith("run-"))
        self.queue.event(ticket["id"], "claude-ec2", "running", "CLI started", run_id=run_id, event_id=run_id + ":1:running")
        replay = self.queue.event(ticket["id"], "claude-ec2", "running", "CLI started", run_id=run_id, event_id=run_id + ":1:running")
        self.assertTrue(replay.get("replayed"))
        self.queue.event(ticket["id"], "claude-ec2", "done", "ok", run_id=run_id, event_id=run_id + ":2:done")
        # A retried final event after completion is still a harmless replay.
        self.assertTrue(self.queue.event(ticket["id"], "claude-ec2", "done", "ok", run_id=run_id, event_id=run_id + ":2:done")["replayed"])
        actions = [h["action"] for h in self.store.get(ticket["id"])["history"]]
        self.assertEqual(actions, ["queued", "claimed", "running", "done"])

    def test_superseded_run_is_fenced(self):
        ticket, _ = self.store.create("Fence")
        old = self.queue.claim("w1")["execution"]["run_id"]
        self.queue.event(ticket["id"], "w1", "blocked", "need owner", run_id=old)
        self.queue.enqueue(ticket["id"])
        new = self.queue.claim("w1")["execution"]["run_id"]
        self.assertNotEqual(old, new)
        with self.assertRaises(ValueError):
            self.queue.event(ticket["id"], "w1", "done", "late event from old run", run_id=old)
        view = self.queue.view(self.store.get(ticket["id"]))
        self.assertEqual(view["execution"]["state"], "claimed")
        # Lifecycle reflects only the current attempt, not the earlier blocked run.
        self.assertNotIn("blocked", [row["stage"] for row in view["lifecycle"]])

    def test_redaction_of_worker_notes(self):
        ticket, _ = self.store.create("Redact")
        self.queue.claim("w1")
        secret = "sk-ant-" + "a" * 30
        bot = "123456789:" + "B" * 35
        self.queue.event(ticket["id"], "w1", "failed", f"crash {secret} {bot} Bearer {'c' * 20}")
        saved = self.path.read_text(encoding="utf-8")
        self.assertNotIn(secret, saved)
        self.assertNotIn(bot, saved)
        self.assertNotIn("c" * 20, saved)
        self.assertEqual(redact("plain text"), "plain text")

    def test_pr_ci_merge_deploy_never_claimed_without_evidence(self):
        ticket, _ = self.store.create("Unverified stages")
        run_id = self.queue.claim("w1")["execution"]["run_id"]
        self.queue.event(ticket["id"], "w1", "running", run_id=run_id)
        self.queue.event(ticket["id"], "w1", "committed", "c", {"commit": "a" * 40, "branch": "autopilot/aws-worker"}, run_id=run_id)
        self.queue.event(ticket["id"], "w1", "pushed", "p", {"pushed": True, "ci_passed": True, "branch": "autopilot/aws-worker"}, run_id=run_id)
        rows = {r["stage"]: r for r in lifecycle(self.store.get(ticket["id"]))}
        self.assertEqual(rows["committed"]["detail"], "a" * 12)
        for stage in ("pr", "ci", "merged", "deployed"):
            self.assertEqual(rows[stage]["state"], "unverified", stage)
        self.assertIn("ci — не проверено", lifecycle_text(self.store.get(ticket["id"])))


class TestEndToEndSlice(SliceBase):
    def test_owner_message_to_telegram_trace_through_real_queue(self):
        """Worker code talks to the real RelayQueue through an in-process bridge."""
        intake = self.update("/new Add lifecycle trace", 1000)
        tid = intake["ticket_id"]
        # /new is deliberately unassigned until the owner chooses a worker.
        assigned = relay_handle_telegram_update(
            {"callback_query": {"id": "assign-lifecycle", "data": "relay:assign:" + tid + ":claude",
                                "message": {"chat": {"id": 42, "type": "private"}}}},
            self.store, lambda: {"chat_id": "42"}, self.tg, queue=self.queue)
        self.assertEqual(assigned["action"], "assigned")
        posted = []

        def bridge(path, data, **kwargs):
            posted.append((path, data))
            if path == "/api/relay/worker/claim":
                return {"ticket": self.queue.claim(data["worker_id"])}
            ticket = self.queue.event(data["ticket_id"], data["worker_id"], data["stage"], data["note"], data["evidence"],
                                      run_id=data["run_id"], event_id=data["event_id"])
            return {"ticket": ticket}

        flaky = {"left": 1}

        def flaky_bridge(path, data, **kwargs):
            # First "committed" POST is lost after the server recorded it.
            result = bridge(path, data)
            if data.get("stage") == "committed" and flaky["left"]:
                flaky["left"] = 0
                raise requests.ConnectionError("response lost")
            return result

        heads = iter(["a" * 40, "b" * 40])

        def fake_git(repo, *args):
            if args == ("branch", "--show-current"):
                return 0, "autopilot/aws-worker"
            if args == ("status", "--porcelain"):
                return 0, ""
            if args == ("rev-parse", "HEAD"):
                return 0, next(heads)
            raise AssertionError(args)

        with patch.dict("os.environ", {"FACTORYOS_URL": "https://factory.invalid", "FACTORY_CLAUDE_WORKER_TOKEN": "t",
                                       "FACTORY_CLAUDE_NODE_ID": "claude-ec2"}):
            with patch.object(relay_tasks, "post", side_effect=flaky_bridge), patch.object(relay_tasks, "git", side_effect=fake_git):
                ticket = relay_tasks.claim()
                self.assertEqual(ticket["id"], tid)
                result = relay_tasks.execute(
                    ticket, Path("/tmp/relay-fake"),
                    run_cli=lambda cmd, **kw: SimpleNamespace(returncode=0, stdout=json.dumps({"result": "Implemented"}), stderr=""),
                    push_fn=lambda: 0)
        self.assertEqual(result["status"], "done")
        run_id = ticket["execution"]["run_id"]
        events = [d for p, d in posted if p == "/api/relay/worker/event" and d["stage"] != "heartbeat"]
        self.assertTrue(all(d["run_id"] == run_id and d["event_id"].startswith(run_id) for d in events))
        history = self.store.get(tid)["history"]
        self.assertEqual([h["action"] for h in history], ["queued", "claimed", "running", "committed", "pushed", "done"])

        # Restart: a fresh store/queue over the same file shows the same durable trace.
        restarted = RelayQueue(RelayStore(self.path))
        web = restarted.view(restarted.store.get(tid))
        self.assertEqual(web["execution"]["state"], "done")
        self.assertEqual(web["execution"]["run_id"], run_id)
        self.assertIsNone(restarted.claim("claude-ec2"))  # no duplicate execution after reconnect

        # Telegram /task renders the same backend record the Web API returns.
        self.update("/task " + tid, 1001)
        text = self.last_text()
        self.assertIn("Этапы (факт из Relay):", text)
        self.assertIn("✅ claimed", text)
        self.assertIn(run_id, text)
        self.assertIn("b" * 12, text)
        self.assertIn("deployed — не проверено", text)
        recorded = [r["stage"] for r in web["lifecycle"] if r["state"] == "recorded"]
        self.assertEqual(recorded, ["queued", "claimed", "running", "committed", "pushed", "done"])

    def test_status_has_no_fabricated_chatgpt_telemetry(self):
        self.update("/status", 1100)
        self.assertIn("ChatGPT: нет автоматической телеметрии", self.last_text())
        self.assertNotIn("ChatGPT: online", self.last_text())


if __name__ == "__main__":
    unittest.main()
