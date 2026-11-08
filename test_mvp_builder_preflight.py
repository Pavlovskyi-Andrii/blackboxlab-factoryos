"""#273 MVP Builder M1B: offline preflight guard. Mocked facts only: no GitHub, no Relay, no worker."""
import copy
import unittest

from mvp_builder_preflight import BLOCKED, NEEDS_OWNER, READY, UNKNOWN, evaluate
from test_mvp_builder_request import good

NOW = "2026-11-08T12:00:00Z"


def facts(**over):
    f = {"issue": {"status": "ok", "owner": "Claude", "state": "open"},
         "spec": {"status": "ok", "approved": True},
         "depends": {"status": "ok", "items": {"41": "closed", "186": "closed"}},
         "gates": {"status": "ok", "owner_approval": "granted"},
         "active_prs": {"status": "ok", "prs": [{"number": 194, "files": ["mvp_manager.py", "docs/mvp.md"]}]},
         "claim": {"status": "ok", "run_id": None},
         "runtime": {"status": "ok", "subscription_available": True, "worker_online": True},
         "cost": {"status": "ok", "estimated_usd": 0}}
    f.update(over)
    return f


class PreflightTest(unittest.TestCase):
    def run_(self, req=None, **over):
        return evaluate(good() if req is None else req, facts(**over), now=NOW)

    def codes(self, out):
        return [r["code"] for r in out["reasons"]]

    def test_valid_scenario_is_ready(self):
        out = self.run_()
        self.assertEqual((out["verdict"], out["reasons"]), (READY, []))
        self.assertEqual(out["checked"], ["request", "issue", "spec", "depends", "gates", "active_prs", "claim",
                                          "runtime", "cost"])

    def test_owner_mismatch_blocks(self):
        out = self.run_(issue={"status": "ok", "owner": "Gemini", "state": "open"})
        self.assertEqual((out["verdict"], self.codes(out)), (BLOCKED, ["owner_mismatch"]))
        self.assertEqual(out["reasons"][0]["source"], "issue")

    def test_unapproved_spec_needs_owner(self):
        out = self.run_(spec={"status": "ok", "approved": False})
        self.assertEqual((out["verdict"], self.codes(out)), (NEEDS_OWNER, ["spec_not_approved"]))
        out = self.run_(gates={"status": "ok", "owner_approval": "pending"})
        self.assertEqual((out["verdict"], self.codes(out)), (NEEDS_OWNER, ["owner_approval_pending"]))

    def test_blocked_or_unknown_dependency(self):
        out = self.run_(depends={"status": "ok", "items": {"41": "open", "186": "closed"}})
        self.assertEqual((out["verdict"], self.codes(out)), (BLOCKED, ["dependency_open"]))
        out = self.run_(depends={"status": "ok", "items": {"41": "closed"}})               # #186 never read
        self.assertEqual((out["verdict"], self.codes(out)), (UNKNOWN, ["dependency_unknown"]))

    def test_file_overlap_with_active_pr_blocks(self):
        prs = {"status": "ok", "prs": [{"number": 266, "files": ["static/mycast-configurator/index.html"]}]}
        out = self.run_(active_prs=prs)
        self.assertEqual((out["verdict"], self.codes(out)), (BLOCKED, ["file_conflict"]))
        self.assertIn("#266", out["reasons"][0]["detail"])
        glob = good(files_scope=["static/mycast-configurator/*.js"])
        prs = {"status": "ok", "prs": [{"number": 1, "files": ["static/mycast-configurator/configurator.js"]}]}
        self.assertEqual(self.run_(glob, active_prs=prs)["verdict"], BLOCKED)
        prs = {"status": "ok", "prs": [{"number": 2, "files": ["static"]}]}                   # a whole directory
        self.assertEqual(self.run_(active_prs=prs)["verdict"], BLOCKED)

    def test_claims_live_stale_and_unknown(self):
        live = {"status": "ok", "run_id": "run-aaaaaaaa", "lease_expires_at": "2026-11-08T12:05:00Z"}
        self.assertEqual(self.codes(self.run_(claim=live)), ["already_claimed"])
        self.assertEqual(self.run_(good(run_id="run-aaaaaaaa"), claim=live)["verdict"], READY)    # our own lease
        stale = {**live, "lease_expires_at": "2026-11-08T11:00:00Z"}
        out = self.run_(claim=stale)
        self.assertEqual((out["verdict"], self.codes(out)), (UNKNOWN, ["stale_claim"]))         # never assumed free
        self.assertEqual(self.codes(self.run_(claim={"status": "ok", "run_id": "run-aaaaaaaa"})), ["claim_lease_unknown"])
        self.assertEqual(self.codes(self.run_(good(run_id="run-bbbbbbbb"))), ["run_id_not_claimed"])

    def test_no_subscription_or_worker(self):
        out = self.run_(runtime={"status": "ok", "subscription_available": False, "worker_online": True})
        self.assertEqual((out["verdict"], self.codes(out)), (BLOCKED, ["no_subscription"]))
        out = self.run_(runtime={"status": "ok", "worker_online": False})
        self.assertEqual(self.codes(out), ["subscription_unknown", "worker_offline"])

    def test_unauthorized_spend(self):
        self.assertEqual(self.codes(self.run_(cost={"status": "ok", "estimated_usd": 0.5})), ["unauthorized_spend"])
        out = self.run_(cost={"status": "ok", "estimated_usd": None})
        self.assertEqual((out["verdict"], self.codes(out)), (UNKNOWN, ["cost_unknown"]))
        self.assertEqual(evaluate(good(budget_cap_usd=10), facts(), now=NOW)["reasons"][0]["code"], "invalid_request")

    def test_403_or_missing_facts_are_unknown_never_ready(self):
        out = self.run_(issue={"status": "forbidden"})
        self.assertEqual((out["verdict"], self.codes(out)), (UNKNOWN, ["fact_forbidden"]))
        f = facts(); del f["runtime"]
        out = evaluate(good(), f, now=NOW)
        self.assertEqual((out["verdict"], self.codes(out)), (UNKNOWN, ["fact_missing"]))
        out = evaluate(good(), None, now=NOW)
        self.assertEqual(out["verdict"], UNKNOWN)
        self.assertEqual(len(out["reasons"]), 8)
        self.assertEqual(self.codes(self.run_(issue={"status": "ok", "state": "open"})), ["owner_unknown"])

    def test_precedence_and_all_reasons(self):
        out = self.run_(issue={"status": "forbidden"}, spec={"status": "ok", "approved": False},
                        cost={"status": "ok", "estimated_usd": 3})
        self.assertEqual(out["verdict"], BLOCKED)
        self.assertEqual(sorted(self.codes(out)), ["fact_forbidden", "spec_not_approved", "unauthorized_spend"])
        out = self.run_(issue={"status": "forbidden"}, spec={"status": "ok", "approved": False})
        self.assertEqual(out["verdict"], NEEDS_OWNER)

    def test_invalid_request_and_closed_issue(self):
        out = evaluate({"schema_version": "x"}, facts(), now=NOW)
        self.assertEqual((out["verdict"], self.codes(out)), (BLOCKED, ["invalid_request"]))
        self.assertIn("unknown_schema_version", out["reasons"][0]["detail"])
        self.assertEqual(self.codes(self.run_(issue={"status": "ok", "owner": "claude", "state": "closed"})), ["issue_closed"])

    def test_no_side_effects_and_bad_clock(self):
        req, f = good(), facts()
        before = (copy.deepcopy(req), copy.deepcopy(f))
        evaluate(req, f, now=NOW)
        self.assertEqual((req, f), before)
        self.assertRaises(ValueError, evaluate, req, f, now="today")


if __name__ == "__main__":
    unittest.main(verbosity=2)
