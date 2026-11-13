"""Automatic Codex PR review (owner 2026-11-13). Offline: fake gh and an in-memory relay client."""
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from autopilot import codex_review as cr
from autopilot.agent_relay_client import RelayHTTPError

PR = {"number": 42, "title": "fix: thing", "headRefOid": "a" * 40, "headRefName": "ccr-x", "isDraft": False,
      "additions": 3, "deletions": 1, "body": "Fixes a bug."}


class FakeGh:
    def __init__(self, prs, diff="diff --git a/x b/x\n+print('hi')\n"):
        self.prs, self.diff, self.comments = prs, diff, []

    def __call__(self, *args, input_text=None):
        if args[:2] == ("pr", "list"):
            return 0, json.dumps(self.prs)
        if args[:2] == ("pr", "diff"):
            return 0, self.diff
        if args[:2] == ("pr", "comment"):
            self.comments.append((args[2], input_text))
            return 0, ""
        return 1, ""


class FakeClient:
    def __init__(self):
        self.sent, self.inbox, self.acked, self.n = [], [], [], 0

    def send(self, to, body, **kw):
        self.n += 1
        self.sent.append({"to": to, "body": body, **kw})
        return {"message_id": f"msg_{self.n}"}

    def claim(self):
        return self.inbox.pop(0) if self.inbox else None

    def ack(self, mid, token):
        self.acked.append(mid)


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = pathlib.Path(self.tmp.name) / "s.json"
        self.c = FakeClient()

    def tearDown(self):
        self.tmp.cleanup()

    def run_once(self, gh, now):
        return cr.run_once(self.state, client=self.c, gh_fn=gh, now=now)

    def test_request_then_post_review_once_per_head(self):
        gh = FakeGh([PR, {**PR, "number": 43, "isDraft": True}])
        self.assertEqual(self.run_once(gh, 1_000_000), "requested")
        req = self.c.sent[0]
        self.assertEqual((req["to"], req["kind"], req["task_id"]), ("codex", "review", "pr-42"))
        self.assertIn("Pull request #42", req["body"])
        self.assertIn("+print('hi')", req["body"])
        self.assertEqual(self.run_once(gh, 1_000_010), "idle")              # same head: never asked twice
        self.assertEqual(len(self.c.sent), 1)                               # the draft PR is skipped
        self.c.inbox.append({"message_id": "r1", "claim_token": "t", "from_agent": "codex", "kind": "answer",
                             "reply_to": "msg_1", "body": "BLOCKING: app.py misses an owner check."})
        self.assertEqual(self.run_once(gh, 1_000_020), "posted")
        pr, text = gh.comments[0]
        self.assertEqual(pr, "42")
        self.assertIn("Codex review", text)
        self.assertIn("advisory only", text)
        self.assertIn("BLOCKING: app.py", text)
        self.assertIn("a" * 12, text)
        self.assertEqual(self.c.acked, ["r1"])

    def test_new_push_is_reviewed_after_the_gap_and_daily_cap_holds(self):
        gh = FakeGh([PR])
        self.run_once(gh, 1_000_000)
        gh.prs = [{**PR, "headRefOid": "b" * 40}]
        self.run_once(gh, 1_000_000 + 60)
        self.assertEqual(len(self.c.sent), 1)                               # quick re-push waits
        self.run_once(gh, 1_000_000 + cr.MIN_GAP_SECONDS + 1)
        self.assertEqual(len(self.c.sent), 2)
        with patch.object(cr, "MAX_PER_DAY", 2):
            gh.prs = [{**PR, "number": 50}]
            self.run_once(gh, 1_000_000 + 2 * cr.MIN_GAP_SECONDS)
        self.assertEqual(len(self.c.sent), 2)

    def test_secrets_redacted_and_diff_truncated(self):
        gh = FakeGh([PR], diff="+token = 'ghp_abcdefghijklmnopqrstuvwx'\n" + "x" * (cr.MAX_DIFF + 500))
        self.run_once(gh, 1_000_000)
        body = self.c.sent[0]["body"]
        self.assertNotIn("ghp_abcdefghijklmnop", body)
        self.assertIn("[REDACTED]", body)
        self.assertIn("diff truncated", body)
        self.assertLessEqual(len(body), 24000)

    def test_unrelated_inbox_items_are_acked_and_failures_never_raise(self):
        gh = FakeGh([])
        self.c.inbox.append({"message_id": "x", "claim_token": "t", "from_agent": "codex", "reply_to": "other"})
        self.assertEqual(self.run_once(gh, 1), "idle")
        self.assertEqual(self.c.acked, ["x"])

        def refuse(*a, **kw):
            raise RelayHTTPError(422, "secret_detected", "no")
        self.c.send = refuse
        gh.prs = [PR]
        self.assertEqual(self.run_once(gh, 2), "idle")
        self.assertIn("42:" + "a" * 40, json.loads(self.state.read_text())["reviewed"])   # not retried forever

        def boom():
            raise ConnectionError("down")
        self.c.claim = boom
        self.assertEqual(self.run_once(gh, 3), "idle")

    def test_token_from_the_worker_home_and_off_reason_logged(self):
        token_file = pathlib.Path(self.tmp.name) / "claude-relay.token"
        token_file.write_text("tok-" + "x" * 40 + "\n")
        with patch.object(cr, "TOKEN_FILES", ["/root/unreadable", str(token_file)]), patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("FACTORY_CLAUDE_RELAY_TOKEN", None)
            self.assertEqual(cr.claude_token(), "tok-" + "x" * 40)
        logged = []
        with patch.object(cr, "TOKEN_FILES", ["/nope"]), patch.object(cr, "log", logged.append), \
                patch.dict("os.environ", {"FACTORYOS_URL": "https://f"}):
            import os
            os.environ.pop("FACTORY_CLAUDE_RELAY_TOKEN", None)
            cr._OFF_LOGGED["reason"] = ""
            self.assertIsNone(cr.default_client())
            self.assertIsNone(cr.default_client())
        self.assertEqual(len(logged), 1)
        self.assertIn("no Claude relay token readable", logged[0])

    def test_off_without_token(self):
        with patch.object(cr, "default_client", return_value=None):
            self.assertEqual(cr.run_once(self.state, gh_fn=FakeGh([PR])), "off")


if __name__ == "__main__":
    unittest.main(verbosity=2)
