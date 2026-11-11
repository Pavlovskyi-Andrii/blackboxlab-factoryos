"""Evidence Tier 2.6: Gemini reviews Claude's risky or large PRs. Offline: fake GitHub reads, fake Gemini."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-review-"))

import evidence  # noqa: E402
import peer_review as pr  # noqa: E402
from relay import RelayStore  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402

URL = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/960"
RISKY = [{"filename": "app.py", "additions": 5, "deletions": 1, "patch": "+x"},
         {"filename": "auth_tokens.py", "additions": 10, "deletions": 0,
          "patch": "+TOKEN = 'ghp_abcdefghijklmnopqrstuv'\n+check()"}]
SAFE = [{"filename": "docs/guide.md", "additions": 12, "deletions": 3, "patch": "+text"}]


def gem(verdict, blockers=0):
    findings = [{"severity": "blocker", "file": "auth_tokens.py", "text": "owner check missing"}] * blockers
    return {"candidates": [{"content": {"parts": [{"text": json.dumps({"verdict": verdict, "findings": findings})}]}}]}


class PureTest(unittest.TestCase):
    def test_which_prs_need_review(self):
        self.assertEqual(pr.needs_review(RISKY)[0], True)
        self.assertIn("auth_tokens.py", pr.needs_review(RISKY)[1])
        self.assertEqual(pr.needs_review(SAFE), (False, ""))
        big = [{"filename": "relay.py", "additions": 250, "deletions": 60}]
        self.assertEqual(pr.needs_review(big), (True, "large: 310 lines"))
        self.assertTrue(pr.needs_review([{"filename": ".github/workflows/ci.yml"}])[0])

    def test_prompt_redacts_and_caps(self):
        files = RISKY + [{"filename": "package-lock.json", "patch": "+lock"},
                         {"filename": "big.py", "patch": "+" + "x" * (pr.MAX_PATCH_CHARS + 10)},
                         {"filename": "after.py", "patch": "+y"}]
        p = pr.build_prompt("Fix auth", "Done when: owner only. key AIzaSyA1234567890abcdefghijk", files)
        self.assertNotIn("ghp_abcdefghijklmnopqrstuv", p)
        self.assertNotIn("AIzaSyA1234567890abcdefghijk", p)
        self.assertIn("[REDACTED]", p)
        self.assertNotIn("package-lock.json", p)
        self.assertIn("[truncated]", p)
        self.assertIn("after.py: (omitted, size cap)", p)

    def test_parse_verdict(self):
        self.assertEqual(pr.parse_verdict('```json\n{"verdict":"approve","findings":[]}\n```')["verdict"], "approve")
        v = pr.parse_verdict(json.dumps({"verdict": "changes", "findings": [
            {"severity": "blocker", "file": "a.py", "text": "bypass"}, {"severity": "nit", "text": "rename"}, {"text": ""}]}))
        self.assertEqual((v["blockers"], [f["severity"] for f in v["findings"]]), (1, ["blocker", "minor"]))
        for bad in ("", "not json", '{"verdict":"maybe"}', "[]"):
            self.assertIsNone(pr.parse_verdict(bad))

    def test_gemini_call_errors_are_never_a_pass(self):
        def boom(*a):
            raise RuntimeError("429")
        self.assertIsNone(pr.gemini_review("k", "p", boom))
        seen = {}

        def call(key, method, path, payload, opener, timeout):
            seen.update(key=key, path=path)
            return gem("approve")
        self.assertEqual(pr.gemini_review("k", "p", call)["verdict"], "approve")
        self.assertEqual(seen["path"], "models/gemini-2.5-flash:generateContent")

    def test_daily_cap(self):
        with tempfile.TemporaryDirectory() as d:
            t = [1_800_000_000.0]
            b = pr.ReviewBudget(Path(d), cap=2, clock=lambda: t[0])
            self.assertEqual([b.take(), b.take(), b.take()], [True, True, False])
            t[0] += 86400
            self.assertTrue(b.take())

    def test_notice(self):
        text = pr.notice_text("R-0001", URL, {"verdict": "changes", "blockers": 1,
                                              "findings": [{"severity": "blocker", "file": "a.py", "text": "bypass"}]})
        self.assertIn("блокирующих замечаний 1", text)
        self.assertIn("/done R-0001 причина", text)
        self.assertIn("не доказательство", text)


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)
        t, _ = self.store.create("Harden auth check")
        self.tid = t["id"]
        run = self.queue.claim("w1")["execution"]["run_id"]
        self.queue.event(self.tid, "w1", "running", "", {}, run_id=run, event_id=run + ":1")
        self.queue.event(self.tid, "w1", "done", "", {"pr_url": URL}, run_id=run, event_id=run + ":2")
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def pulls(self, merged=False, head="abc123"):
        p = {"html_url": URL, "state": "closed" if merged else "open", "head": {"sha": head}}
        if merged:
            p["merged_at"] = "2026-11-11T10:00:00Z"
        return [p]

    def run_app(self, pulls, ci, files, gemini=None, key="k"):
        import app as factory

        def reader(path):
            self.calls.append(path)
            return files
        with patch.object(factory, "RELAY_QUEUE", self.queue), patch.object(factory, "FACTORY_GEMINI_API_KEY", key), \
             patch.object(factory, "PEER_REVIEW_BUDGET", pr.ReviewBudget(Path(self.tmp.name))):
            return factory.relay_peer_review_once(pulls, ci, reader, gemini_call=gemini)

    def t(self):
        return self.store.get(self.tid)

    def test_safe_small_pr_needs_no_review(self):
        n = self.run_app(self.pulls(), {"abc123": {"state": "passed"}}, SAFE, gemini=lambda *a: self.fail("no call"))
        self.assertEqual(n, [])
        self.assertNotIn("peer_review", self.t()["verification"]["required_checks"])
        self.queue.reconcile_pull_requests(self.pulls(True), {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "done")
        self.assertEqual(self.run_app(self.pulls(True), {"abc123": {"state": "passed"}}, SAFE), [])

    def test_no_review_before_green_ci(self):
        self.assertEqual(self.run_app(self.pulls(), {"abc123": {"state": "running"}}, RISKY), [])
        self.assertEqual(self.calls, [])

    def test_risky_pr_waits_for_review_then_closes(self):
        n = self.run_app(self.pulls(), {"abc123": {"state": "passed"}}, RISKY, gemini=lambda *a: gem("approve"))
        self.assertIn("замечаний нет", n[0]["text"])
        ver = self.t()["verification"]
        self.assertIn("peer_review", ver["required_checks"])
        self.assertEqual(ver["checks"]["peer_review"]["result"], "pass")
        self.queue.reconcile_pull_requests(self.pulls(True), {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "done")

    def test_merged_before_review_does_not_close(self):
        self.run_app(self.pulls(True), {"abc123": {"state": "passed"}}, RISKY, key="")      # no key: unavailable
        self.queue.reconcile_pull_requests(self.pulls(True), {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "in_progress")
        self.assertIn("peer_review", evidence.missing(self.t()))

    def test_blockers_keep_it_open_and_a_new_push_is_reviewed_again(self):
        n = self.run_app(self.pulls(), {"abc123": {"state": "passed"}}, RISKY, gemini=lambda *a: gem("changes", 1))
        self.assertIn("блокирующих замечаний 1", n[0]["text"])
        self.queue.reconcile_pull_requests(self.pulls(True), {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "in_progress")
        self.assertEqual(self.t()["verification"]["review"]["findings"][0]["text"], "owner check missing")
        # a fix pushed before merge: new head, new review
        t2 = self.run_app(self.pulls(head="def456"), {"def456": {"state": "passed"}}, RISKY, gemini=lambda *a: gem("approve"))
        self.assertEqual(len(t2), 1)
        self.assertEqual(self.t()["verification"]["checks"]["peer_review"]["sha"], "def456")

    def test_unavailable_is_retried_later_not_passed(self):
        def down(*a):
            raise RuntimeError("503")
        self.assertEqual(self.run_app(self.pulls(), {"abc123": {"state": "passed"}}, RISKY, gemini=down), [])
        self.assertNotIn("peer_review", self.t()["verification"]["checks"])
        self.assertEqual(self.queue.review_candidates(self.pulls(), {"abc123": {"state": "passed"}}, 0 + 1e12)[0]["ticket"], self.tid)
        import time
        self.assertEqual(self.queue.review_candidates(self.pulls(), {"abc123": {"state": "passed"}}, time.time()), [])

    def test_unreadable_diff_means_review_required(self):
        self.assertEqual(self.run_app(self.pulls(True), {"abc123": {"state": "passed"}}, None), [])
        self.assertEqual(self.t()["verification"]["review_scope"]["reason"], "diff unreadable")
        self.queue.reconcile_pull_requests(self.pulls(True), {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "in_progress")                      # not closed unreviewed

    def test_gemini_authored_pr_is_not_reviewed_by_gemini(self):
        with self.store.lock:
            state = self.store._load_unlocked()
            state["tickets"][0]["execution"]["owner"] = "gemini"
            self.store._save_unlocked(state)
        self.assertEqual(self.queue.review_candidates(self.pulls(), {"abc123": {"state": "passed"}}, 0), [])

    def test_owner_override_still_works(self):
        self.run_app(self.pulls(), {"abc123": {"state": "passed"}}, RISKY, gemini=lambda *a: gem("changes", 1))
        self.assertEqual(self.store.set_status(self.tid, "done", actor="owner", note="false positive, checked")["status"], "done")


if __name__ == "__main__":
    unittest.main(verbosity=2)
