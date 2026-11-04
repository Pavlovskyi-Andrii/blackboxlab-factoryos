import unittest
from mvp_manager import plan_mvp


class MvpManagerTests(unittest.TestCase):
    def test_idea_recommendation_does_not_dispatch(self):
        p = plan_mvp(187, "idea", [])
        self.assertEqual(p["decision"], "recommend")
        self.assertEqual(p["next_stage"], "researching")

    def test_build_requires_spec_approval(self):
        self.assertEqual(plan_mvp(187, "build_queued", [])["decision"], "blocked")
        self.assertEqual(plan_mvp(187, "build_queued", [], spec_approved=True)["decision"], "recommend")

    def test_reuses_active_relay_ticket(self):
        t = {"id": "relay-7", "title": "GitHub issue #187", "execution": {"state": "running"}}
        p = plan_mvp(187, "idea", [t])
        self.assertEqual(p["decision"], "observe")
        self.assertEqual(p["ticket_ids"], ["relay-7"])

    def test_duplicate_active_execution_is_blocked(self):
        ts = [{"id": str(i), "source": {"url": "https://github.com/a/b/issues/189"},
               "execution": {"state": "queued"}} for i in range(2)]
        self.assertEqual(plan_mvp(189, "idea", ts)["decision"], "blocked")

    def test_review_and_deploy_gates(self):
        self.assertEqual(plan_mvp(187, "qa_review", [])["decision"], "blocked")
        self.assertEqual(plan_mvp(187, "qa_review", [], ci_green=True, review_approved=True)["decision"], "recommend")
        self.assertEqual(plan_mvp(187, "preview_ready", [])["decision"], "blocked")

    def test_unrelated_issue_not_claimed(self):
        t = {"title": "Issue #188", "execution": {"state": "running"}}
        self.assertEqual(plan_mvp(187, "idea", [t])["decision"], "recommend")


if __name__ == "__main__":
    unittest.main()
