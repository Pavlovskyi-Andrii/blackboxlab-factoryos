"""#260: offline fixtures for the #256 smoke evidence check. Synthetic, redacted traces; nothing is sent or fetched."""
import copy
import unittest

from relay_smoke_evidence import verify_smoke_trace

GOOD = {
    "issue": 256,
    "ticket": {"id": "R-0042", "source_issue": 256, "run_id": "run-20261105-abc123"},
    "events": [
        {"stage": "heartbeat", "at": "2026-11-05T20:30:00+00:00"},
        {"stage": "claimed", "run_id": "run-20261105-abc123", "at": "2026-11-05T20:31:00+00:00"},
        {"stage": "running", "run_id": "run-20261105-abc123", "at": "2026-11-05T20:31:05+00:00"},
        {"stage": "done", "run_id": "run-20261105-abc123", "at": "2026-11-05T20:33:40+00:00",
         "result": "smoke ok · main=4a27cfc · open ROADMAP tasks=22"},
    ],
    "telegram": {"delivered": True, "message_id": 9001, "delivered_at": "2026-11-05T20:33:45+00:00"},
}


def mutate(fn):
    trace = copy.deepcopy(GOOD)
    fn(trace)
    return verify_smoke_trace(trace)


class SmokeEvidenceTest(unittest.TestCase):
    def test_positive_trace_is_verified(self):
        out = verify_smoke_trace(GOOD)
        self.assertEqual(out, {"status": "VERIFIED", "missing": [], "problems": [], "run_id": "run-20261105-abc123"})

    def test_mismatched_run_id(self):
        out = mutate(lambda t: t["events"][3].update(run_id="run-other"))
        self.assertEqual(out["status"], "UNVERIFIED")
        self.assertIn("events carry different run_ids", out["problems"])
        out = mutate(lambda t: t["ticket"].update(run_id="run-other"))
        self.assertIn("ticket run_id does not match the events", out["problems"])

    def test_missing_claim(self):
        out = mutate(lambda t: t["events"].pop(1))
        self.assertEqual((out["status"], out["missing"]), ("UNVERIFIED", ["claimed"]))

    def test_heartbeat_only(self):
        out = mutate(lambda t: t.update(events=[{"stage": "heartbeat", "at": "2026-11-05T20:30:00+00:00"}] * 5))
        self.assertEqual(out["status"], "UNVERIFIED")
        self.assertEqual(out["missing"], ["claimed", "running", "done"])

    def test_generic_http_200_is_not_evidence(self):
        out = mutate(lambda t: t.update(events=[], http_status=200))
        self.assertEqual(out["status"], "UNVERIFIED")
        self.assertIn("an HTTP 200 alone is not evidence of execution", out["problems"])

    def test_stale_or_premature_telegram_delivery(self):
        stale = mutate(lambda t: t["telegram"].update(delivered_at="2026-11-05T23:00:00+00:00"))
        self.assertIn("Telegram delivery is stale for this run", stale["problems"])
        early = mutate(lambda t: t["telegram"].update(delivered_at="2026-11-05T20:20:00+00:00"))
        self.assertIn("Telegram delivery is older than the done event", early["problems"])
        absent = mutate(lambda t: t.update(telegram={"delivered": False}))
        self.assertEqual(absent["missing"], ["telegram"])

    def test_reordered_finish(self):
        out = mutate(lambda t: t["events"][3].update(at="2026-11-05T20:30:30+00:00"))
        self.assertIn("stages are out of order (claimed -> running -> done)", out["problems"])

    def test_wrong_issue_or_foreign_ticket(self):
        wrong = mutate(lambda t: t.update(issue=255))
        self.assertIn("issue", wrong["missing"])
        foreign = mutate(lambda t: t["ticket"].update(source_issue=999))
        self.assertIn("Relay ticket is not sourced from the expected GitHub issue", foreign["problems"])

    def test_done_without_result_and_garbage_input(self):
        out = mutate(lambda t: t["events"][3].pop("result"))
        self.assertIn("done has no result", out["problems"])
        self.assertEqual(verify_smoke_trace(None)["missing"], ["issue", "ticket", "claimed", "running", "done", "telegram"])
        self.assertEqual(verify_smoke_trace({})["status"], "UNVERIFIED")


if __name__ == "__main__":
    unittest.main(verbosity=2)
