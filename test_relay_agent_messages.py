"""Issue #94: two-agent same-thread, durable lease and isolation regressions."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from types import SimpleNamespace

import json
import threading


class RelayStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
    def _load_unlocked(self):
        if not self.path.exists():
            return {'agent_messages': []}
        return json.loads(self.path.read_text())
    def _save_unlocked(self, state):
        self.path.write_text(json.dumps(state))
from relay_agent_messages import RelayAgentMessages, agent_identity
from autopilot.codex_relay_worker import run_once, answer_with_codex


class AgentMessageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "relay.json"
        self.store = RelayAgentMessages(RelayStore(self.path), lease_seconds=60)

    def tearDown(self):
        self.tmp.cleanup()

    def test_two_way_round_trip_and_ack_idempotency(self):
        question, created = self.store.send(
            "claude", "codex", "Review the bounds for issue #313",
            task_id="issue-313", idempotency_key="ask-313")
        self.assertTrue(created)
        same, created = self.store.send(
            "claude", "codex", "Review the bounds for issue #313",
            task_id="issue-313", idempotency_key="ask-313")
        self.assertFalse(created)
        self.assertEqual(same["message_id"], question["message_id"])
        self.assertIsNone(self.store.claim("claude"))

        claimed = self.store.claim("codex")
        self.assertEqual(claimed["message_id"], question["message_id"])
        self.assertIsNone(self.store.claim("codex"))
        answer, fresh = self.store.send(
            "codex", "claude", "Prefer the minimum private MVP and secure uploads",
            kind="answer", thread_id=question["thread_id"],
            reply_to=question["message_id"], task_id="issue-313",
            idempotency_key="reply-" + question["message_id"])
        self.assertTrue(fresh)
        self.assertEqual(answer["thread_id"], question["thread_id"])
        self.assertEqual(answer["reply_to"], question["message_id"])
        acknowledged, changed = self.store.ack("codex", claimed["message_id"], claimed["claim_token"])
        self.assertTrue(changed)
        self.assertTrue(acknowledged["ack_at"])
        _, changed = self.store.ack("codex", claimed["message_id"], claimed["claim_token"])
        self.assertFalse(changed)

        received = self.store.claim("claude")
        self.assertEqual(received["message_id"], answer["message_id"])
        self.assertIn("private MVP", received["body"])
        self.store.ack("claude", received["message_id"], received["claim_token"])
        self.assertIsNone(self.store.claim("claude"))

        # Store is durable across process restart.
        reopened = RelayAgentMessages(RelayStore(self.path))
        self.assertEqual(len(reopened.list_for("claude")), 2)
        self.assertIsNone(reopened.claim("codex"))

    def test_lease_expiry_and_stale_ack_rejected(self):
        q, _ = self.store.send("claude", "codex", "Question", idempotency_key="q1")
        first = self.store.claim("codex")
        with self.store.store.lock:
            state = self.store.store._load_unlocked()
            state["agent_messages"][0]["lease_until"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            self.store.store._save_unlocked(state)
        second = RelayAgentMessages(RelayStore(self.path)).claim("codex")
        self.assertEqual(second["message_id"], q["message_id"])
        self.assertNotEqual(first["claim_token"], second["claim_token"])
        self.assertEqual(second["attempts"], 2)
        with self.assertRaisesRegex(ValueError, "lease mismatch"):
            self.store.ack("codex", q["message_id"], first["claim_token"])
        self.store.ack("codex", q["message_id"], second["claim_token"])

    def test_wrong_recipient_reply_and_replay_attack(self):
        q, _ = self.store.send("claude", "codex", "Question", idempotency_key="q1")
        with self.assertRaises(ValueError):
            self.store.send("claude", "claude", "Bad", idempotency_key="x1")
        with self.assertRaisesRegex(ValueError, "reply target"):
            self.store.send("claude", "codex", "Forged answer", reply_to=q["message_id"],
                            idempotency_key="x2")
        with self.assertRaisesRegex(ValueError, "different payload"):
            self.store.send("claude", "codex", "Altered question", idempotency_key="q1")
        with self.assertRaises(ValueError):
            self.store.ack("claude", q["message_id"], "faketoken")
        with self.assertRaises(ValueError):
            self.store.send("codex", "claude", "", idempotency_key="empty")
        with self.assertRaises(ValueError):
            self.store.send("codex", "claude", "x" * 3001, idempotency_key="too-large")

    def test_token_roles_not_claimed_from_body(self):
        def req(token):
            return SimpleNamespace(headers={"authorization": "Bearer " + token})
        with patch.dict(os.environ, {"FACTORY_CODEX_RELAY_TOKEN": "distinct-codex-secret"}):
            auth_claude = lambda r: r.headers.get("authorization") == "Bearer valid-claude-secret"
            self.assertEqual(agent_identity(req("valid-claude-secret"), auth_claude), "claude")
            self.assertEqual(agent_identity(req("distinct-codex-secret"), auth_claude), "codex")
            self.assertEqual(agent_identity(req("invalid"), auth_claude), "")

    def test_codex_once_only_when_pending_and_same_thread(self):
        q, _ = self.store.send("claude", "codex", "Explain architecture", idempotency_key="ask")
        routes = []

        def transport(path, payload):
            routes.append(path)
            if path.endswith("/claim"):
                return {"message": self.store.claim("codex")}
            if path.endswith("/messages"):
                return {"messages": self.store.list_for("codex")}
            if path.endswith("/send"):
                item, created = self.store.send("codex", payload["to_agent"], payload["body"],
                                                kind=payload["kind"], thread_id=payload["thread_id"],
                                                task_id=payload["task_id"], reply_to=payload["reply_to"],
                                                idempotency_key=payload["idempotency_key"])
                return {"message": item, "created": created}
            if path.endswith("/ack"):
                self.store.ack("codex", payload["message_id"], payload["claim_token"])
                return {"ok": True}
            raise AssertionError(path)

        outcome = run_once(transport=transport, reviewer=lambda m: "Review complete")
        self.assertEqual(outcome["state"], "acknowledged")
        self.assertEqual(len(routes), 4)
        answer = self.store.claim("claude")
        self.assertEqual(answer["thread_id"], q["thread_id"])
        self.assertEqual(answer["reply_to"], q["message_id"])
        self.assertEqual(run_once(transport=transport, reviewer=lambda m: "not called")["state"], "idle")

    def test_lost_ack_redelivery_does_not_reinvoke_model(self):
        original, _ = self.store.send("claude", "codex", "A review question", idempotency_key="retry-q")
        invocations = []
        first_ack = [True]

        def transport(path, payload):
            if path.endswith("/claim"):
                return {"message": self.store.claim("codex")}
            if path.endswith("/messages"):
                return {"messages": self.store.list_for("codex")}
            if path.endswith("/send"):
                reply, fresh = self.store.send("codex", payload["to_agent"], payload["body"],
                                               kind=payload["kind"], thread_id=payload["thread_id"],
                                               task_id=payload["task_id"], reply_to=payload["reply_to"],
                                               idempotency_key=payload["idempotency_key"])
                return {"message": reply, "created": fresh}
            if path.endswith("/ack"):
                if first_ack[0]:
                    first_ack[0] = False
                    raise ConnectionError("Simulated lost ACK")
                self.store.ack("codex", payload["message_id"], payload["claim_token"])
                return {"ok": True}
            raise AssertionError(path)

        def reviewer(message):
            invocations.append(message["message_id"])
            return "One stable reply"

        with self.assertRaises(ConnectionError):
            run_once(transport=transport, reviewer=reviewer)
        with self.store.store.lock:
            state = self.store.store._load_unlocked()
            state["agent_messages"][0]["lease_until"] = (
                datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
            self.store.store._save_unlocked(state)
        outcome = run_once(transport=transport, reviewer=reviewer)
        self.assertEqual(outcome["state"], "acknowledged")
        self.assertEqual(invocations, [original["message_id"]])
        reply = self.store.claim("claude")
        self.assertEqual(reply["reply_to"], original["message_id"])
        self.assertEqual(len(self.store.list_for("codex")), 2)

    def test_codex_child_env_is_minimal_and_readonly(self):
        with patch.dict(os.environ, {"FACTORY_CODEX_RELAY_TOKEN": "do-not-expose",
                                      "FACTORY_CLAUDE_WORKER_TOKEN": "do-not-expose-too"}):
            def fake_run(args, **kwargs):
                self.assertEqual(args[args.index("--sandbox") + 1], "read-only")
                self.assertNotIn("FACTORY_CODEX_RELAY_TOKEN", kwargs["env"])
                self.assertNotIn("FACTORY_CLAUDE_WORKER_TOKEN", kwargs["env"])
                Path(args[args.index("--output-last-message") + 1]).write_text("safe reply")
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            self.assertEqual(answer_with_codex({"kind": "question", "body": "Review"}, runner=fake_run),
                             "safe reply")


if __name__ == "__main__":
    unittest.main()
