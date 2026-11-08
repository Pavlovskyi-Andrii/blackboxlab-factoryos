"""#274 MVP Builder M1C: output manifest for QA handoff. Offline, deterministic, no network."""
import copy
import unittest

import mvp_builder_request
from mvp_builder_manifest import REPO, UNKNOWN, from_json, redacted_example, to_json, validate

NOW = "2026-11-08T12:00:00Z"
PR = "https://github.com/" + REPO + "/pull/1"


def request(**over):
    raw = {
        "schema_version": mvp_builder_request.SCHEMA_VERSION, "project_id": "mycast", "product_version": "v1",
        "spec_revision": "r1", "spec_url": "https://github.com/" + REPO + "/issues/186", "spec_approved": True,
        "issue_id": 274, "task_id": "T-0001", "run_id": "run-0123abcd", "owner_lane": "claude", "priority": "P1",
        "files_scope": ["test_example.py"], "acceptance_criteria": ["Example criterion holds"],
        "test_commands": ["python test_example.py"],
        "permission_flags": {k: False for k in mvp_builder_request.PERMISSION_FLAGS}, "budget_cap_usd": 0,
        "requested_at": "2026-11-08T09:00:00Z"}
    raw.update(over)
    res = mvp_builder_request.validate(raw)
    assert res.ok, res.reasons
    return res.request


def good(**over):
    m = redacted_example()
    m.update(over)
    return m


class ManifestTest(unittest.TestCase):
    def codes(self, raw, **kw):
        kw.setdefault("now", NOW)
        res = validate(raw, **kw)
        self.assertFalse(res.ok)
        self.assertIsNone(res.manifest)
        return res.codes

    def test_redacted_example_is_valid_and_ready(self):
        res = validate(good(), request=request(), now=NOW)
        self.assertTrue(res.ok, res.reasons)
        m = res.manifest
        self.assertTrue(m["ready_for_qa"])
        self.assertEqual(m["state"], "qa_review")
        self.assertEqual((m["merge_state"], m["deploy_state"]), (UNKNOWN, UNKNOWN))   # never proof of merge/deploy
        self.assertTrue(all(e["state"] == UNKNOWN for e in m["evidence_refs"]))

    def test_stable_json_round_trip(self):
        a = to_json(validate(good(), now=NOW).manifest)
        shuffled = dict(reversed(list(good().items())))
        self.assertEqual(a, to_json(validate(shuffled, now=NOW).manifest))
        back = from_json(a, request=request(), now=NOW)
        self.assertTrue(back.ok, back.reasons)
        self.assertEqual(to_json(back.manifest), a)
        self.assertEqual(from_json("{oops").codes, ["bad_json"])

    def test_mismatch_against_request(self):
        self.assertEqual(self.codes(good(run_id="run-ffffffff"), request=request()), ["run_id_mismatch"])
        self.assertEqual(self.codes(good(product_version="v2"), request=request()), ["version_mismatch"])
        self.assertEqual(self.codes(good(task_id="T-9"), request=request()), ["task_mismatch"])
        self.assertEqual(self.codes(good(project_id="other"), request=request()), ["project_mismatch"])
        self.assertIn("run_id_mismatch", self.codes(good(), request=request(run_id=None)))   # unclaimed request
        self.assertEqual(self.codes(good(run_id="run-XYZ")), ["bad_run_id"])

    def test_malformed_commit_sha(self):
        for sha in ("abc123", "A" * 40, "g" * 40, "0" * 40, None, "0" * 41, 12345):
            self.assertEqual(self.codes(good(commit_sha=sha)), ["bad_commit_sha"], sha)

    def test_branch_rules(self):
        for b in ("main", "master"):
            self.assertEqual(self.codes(good(branch=b)), ["branch_is_default"])
        for b in ("claude/../main", "claude/x y", "claude/x.lock", "-x", "", "claude//x", "a@{1}"):
            self.assertEqual(self.codes(good(branch=b)), ["bad_branch"], b)
        self.assertTrue(validate(good(branch="feature/t-1"), now=NOW).ok)

    def test_counterfeit_pr_and_evidence_links(self):
        for url in ("https://github.com.evil.com/" + REPO + "/pull/1", "https://github.com/other/repo/pull/1",
                    "http://github.com/" + REPO + "/pull/1", PR + "/files", PR + "#x",
                    "https://gitHub.com/" + REPO + "/pull/1", "https://user@github.com/" + REPO + "/pull/1"):
            self.assertEqual(self.codes(good(pr_url=url)), ["counterfeit_link"], url)
        self.assertEqual(self.codes(good(pr_url=None)), ["missing_pr_url"])
        for ev in ({"kind": "ci_run", "ref": "https://github.com/other/repo/actions/runs/5"},
                   {"kind": "url", "ref": "https://github.com.evil.com/x"},
                   {"kind": "url", "ref": "https://githubb.com/x"},
                   {"kind": "url", "ref": "https://github.com@evil.com/x"},
                   {"kind": "url", "ref": "https://github.com/other/repo"},
                   {"kind": "url", "ref": "http://example.com/x"}):
            self.assertEqual(self.codes(good(evidence_refs=[ev])), ["counterfeit_link"], ev)
        self.assertEqual(self.codes(good(evidence_refs=[{"kind": "file", "ref": ".env"}])), ["secret_path"])
        self.assertEqual(self.codes(good(evidence_refs=[{"kind": "blob", "ref": "x"}])), ["bad_evidence_ref"])
        ok = [{"kind": "url", "ref": "https://example.com/report"}, {"kind": "commit", "ref": "1" * 40},
              {"kind": "pr", "ref": PR}]
        self.assertTrue(validate(good(evidence_refs=ok), now=NOW).ok)

    def test_fabricated_and_future_tests(self):
        t = {"command": "python test_example.py", "result": "passed"}
        self.assertEqual(self.codes(good(tests=[t])), ["fabricated_test"])
        self.assertEqual(self.codes(good(tests=[dict(t, result="failed")])), ["fabricated_test"])
        self.assertEqual(self.codes(good(tests=[dict(t, ran_at="2026-11-09T00:00:00Z")])), ["future_ran_at"])
        self.assertEqual(self.codes(good(tests=[dict(t, ran_at="2026-11-08 10:00")])), ["bad_ran_at"])
        self.assertEqual(self.codes(good(tests=[dict(t, result="not_run", ran_at=NOW)])), ["bad_test"])
        self.assertEqual(self.codes(good(tests=[])), ["missing_tests"])
        self.assertEqual(self.codes(good(tests=[dict(t, ran_at=NOW, result="ok")])), ["bad_test_result"])
        # without `now` the manifest's own created_at is the reference
        self.assertEqual(self.codes(good(tests=[dict(t, ran_at="2026-11-08T11:00:00Z")]), now=None),
                         ["future_ran_at"])
        self.assertEqual(self.codes(good(created_at="2026-11-09T00:00:00Z")), ["future_created_at"])

    def test_duplicate_and_missing_required_tests(self):
        t = {"command": "python test_example.py", "result": "passed", "ran_at": "2026-11-08T10:00:00Z"}
        self.assertEqual(self.codes(good(tests=[t, dict(t)])), ["duplicate_test"])
        other = dict(t, command="python other.py")
        self.assertEqual(self.codes(good(tests=[other]), request=request()), ["missing_required_test"])

    def test_missing_qa_criteria(self):
        self.assertEqual(self.codes(good(qa_criteria=[])), ["missing_qa_criteria"])
        raw = good(); del raw["qa_criteria"]
        self.assertEqual(self.codes(raw), ["missing_qa_criteria"])
        other = [{"criterion": "Something else", "status": "met"}]
        self.assertEqual(self.codes(good(qa_criteria=other), request=request()), ["missing_qa_criteria"])
        self.assertEqual(self.codes(good(qa_criteria=[{"criterion": "x", "status": "done"}])), ["bad_qa_criterion"])

    def test_preview_kinds(self):
        self.assertTrue(validate(good(preview={"kind": "local"}), now=NOW).ok)
        self.assertTrue(validate(good(preview={"kind": "local", "url": "http://localhost:8000/"}), now=NOW).ok)
        self.assertTrue(validate(good(preview={"kind": "verified", "url": "https://preview.example.com/"}),
                                 now=NOW).ok)
        self.assertEqual(self.codes(good(preview={"kind": "local", "url": "https://example.com/"})), ["bad_preview"])
        self.assertEqual(self.codes(good(preview={"kind": "verified"})), ["bad_preview"])
        self.assertEqual(self.codes(good(preview={"kind": "verified", "url": "http://example.com/"})),
                         ["counterfeit_link"])
        self.assertEqual(self.codes(good(preview={"kind": "none", "url": "https://x.example/"})), ["bad_preview"])
        self.assertEqual(self.codes(good(preview={"kind": "prod"})), ["bad_preview"])

    def test_merge_and_deploy_claims_are_refused(self):
        self.assertEqual(self.codes(good(merged=True)), ["unverifiable_claim"])
        self.assertEqual(self.codes(good(deployed=True)), ["unverifiable_claim"])
        self.assertEqual(self.codes(good(merge_state="MERGED")), ["unverifiable_claim"])
        self.assertEqual(self.codes(good(deploy_state="DEPLOYED")), ["unverifiable_claim"])
        self.assertEqual(self.codes(good(state="merged")), ["unverifiable_claim"])
        ev = [{"kind": "ci_run", "ref": "https://github.com/" + REPO + "/actions/runs/1", "state": "success"}]
        self.assertEqual(self.codes(good(evidence_refs=ev)), ["unverifiable_claim"])
        failing = [{"command": "python test_example.py", "result": "failed", "ran_at": "2026-11-08T10:00:00Z"}]
        self.assertEqual(self.codes(good(tests=failing, ready_for_qa=True)), ["unverifiable_claim"])

    def test_unknown_fields_and_every_reason_listed(self):
        self.assertEqual(self.codes(good(extra=1)), ["unknown_field"])
        self.assertEqual(self.codes(good(schema_version="mvp-build-manifest/2")), ["unknown_schema_version"])
        self.assertEqual(self.codes("nope"), ["not_an_object"])
        many = self.codes(good(commit_sha="x", pr_url="https://evil.com/pull/1", human_review="lgtm",
                               producer_role="chatgpt"))
        self.assertEqual(sorted(many), ["bad_commit_sha", "bad_human_review", "bad_producer", "counterfeit_link"])

    def test_failed_test_is_valid_but_not_ready(self):
        failing = [{"command": "python test_example.py", "result": "failed", "ran_at": "2026-11-08T10:00:00Z"}]
        res = validate(good(tests=failing), request=request(), now=NOW)
        self.assertTrue(res.ok, res.reasons)
        self.assertFalse(res.manifest["ready_for_qa"])
        self.assertEqual(res.manifest["state"], "pr_open")
        not_run = [{"command": "python test_example.py", "result": "not_run"}]
        self.assertFalse(validate(good(tests=not_run), now=NOW).manifest["ready_for_qa"])
        blocked = validate(good(blocked_reason="Needs owner decision"), now=NOW).manifest
        self.assertEqual((blocked["ready_for_qa"], blocked["state"]), (False, "blocked"))
        unmet = validate(good(qa_criteria=[{"criterion": "Example criterion holds", "status": "not_met"}]), now=NOW)
        self.assertFalse(unmet.manifest["ready_for_qa"])

    def test_secrets_in_text_refused(self):
        t = [{"command": "python x.py --token=ghp_abc", "result": "passed", "ran_at": "2026-11-08T10:00:00Z"}]
        self.assertEqual(self.codes(good(tests=t)), ["secret_in_text"])
        self.assertEqual(self.codes(good(blocked_reason="password: hunter2")), ["secret_in_text"])

    def test_input_not_mutated(self):
        raw = good(product_version="V1", tests=[{"command": " python test_example.py ", "result": "passed",
                                                 "ran_at": "2026-11-08T10:00:00Z"}])
        before = copy.deepcopy(raw)
        req = request()
        req_before = copy.deepcopy(req)
        res = validate(raw, request=req, now=NOW)
        self.assertTrue(res.ok, res.reasons)
        self.assertEqual(raw, before)
        self.assertEqual(req, req_before)
        self.assertEqual(res.manifest["product_version"], "v1")
        res.manifest["tests"].append("x")
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
