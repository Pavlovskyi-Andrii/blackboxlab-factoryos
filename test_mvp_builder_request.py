"""#272 MVP Builder M1A: build_request contract. Offline, deterministic, no network."""
import copy
import json
import unittest

from mvp_builder_request import PERMISSION_FLAGS, SCHEMA_VERSION, from_json, to_json, validate

SPEC = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/186#issuecomment-6684703331"


def good(**over):
    req = {
        "schema_version": SCHEMA_VERSION, "project_id": "mycast", "product_version": "V1", "spec_revision": "r1",
        "spec_url": SPEC, "spec_approved": True, "issue_id": 261, "task_id": "T-0001", "owner_lane": "Claude",
        "priority": "p1", "depends": ["#186", 41, "#186"],
        "files_scope": ["static/mycast-configurator/index.html", "mycast_voices.py"],
        "input_artifact_refs": [{"kind": "pr", "ref": 284},
                                {"kind": "commit", "ref": "ad30654ee6ddd2507b25cd16385cb63102324fc4"}],
        "acceptance_criteria": ["Pairing Telegram sends nothing", "Delivery needs explicit consent"],
        "test_commands": ["python test_mycast_accounts.py", "node static/mycast-configurator/test_configurator.js"],
        "permission_flags": {k: False for k in PERMISSION_FLAGS}, "budget_cap_usd": 0,
        "requested_at": "2026-11-08T09:00:00Z"}
    req.update(over)
    return req


class BuildRequestTest(unittest.TestCase):
    def codes(self, raw, **kw):
        res = validate(raw, **kw)
        self.assertFalse(res.ok)
        self.assertIsNone(res.request)
        return res.codes

    def test_good_request_is_normalised(self):
        res = validate(good())
        self.assertTrue(res.ok, res.reasons)
        r = res.request
        self.assertEqual((r["owner_lane"], r["priority"], r["product_version"]), ("claude", "P1", "v1"))
        self.assertEqual(r["depends"], [41, 186])                                   # deduplicated, sorted
        self.assertEqual(r["files_scope"], ["mycast_voices.py", "static/mycast-configurator/index.html"])
        self.assertIsNone(r["run_id"])                                              # unclaimed: never invented

    def test_stable_json_round_trip(self):
        a = to_json(validate(good()).request)
        shuffled = dict(reversed(list(good().items())))
        self.assertEqual(a, to_json(validate(shuffled).request))                    # key order does not matter
        back = from_json(a)
        self.assertTrue(back.ok)
        self.assertEqual(to_json(back.request), a)
        self.assertEqual(from_json("{oops").codes, ["bad_json"])

    def test_missing_or_unapproved_spec_needs_owner(self):
        raw = good(); del raw["spec_url"]
        self.assertIn("missing_owner_spec", self.codes(raw))
        self.assertIn("bad_spec_link", self.codes(good(spec_url="https://example.com/spec")))
        self.assertIn("bad_spec_link", self.codes(good(spec_url="https://github.com/other/repo/issues/1")))
        self.assertEqual(self.codes(good(spec_approved="yes")), ["spec_not_owner_approved"])

    def test_unknown_schema_version(self):
        self.assertEqual(self.codes(good(schema_version="mvp-build-request/2")), ["unknown_schema_version"])
        raw = good(); del raw["schema_version"]
        self.assertEqual(self.codes(raw), ["unknown_schema_version"])

    def test_malformed_paths_are_refused(self):
        for path in ("/etc/passwd", "../secrets.py", "app\\x.py", "static//x.js", "C:/x.py", ".git/config", "static/"):
            self.assertIn("bad_path", self.codes(good(files_scope=[path])), path)
        self.assertEqual(self.codes(good(files_scope=[".env"])), ["secret_path"])
        self.assertEqual(self.codes(good(files_scope=["config/.env.production"])), ["secret_path"])

    def test_wildcard_root_scope_is_refused(self):
        for path in ("*", "**", ".", "*.py", "**/x.py"):
            self.assertEqual(self.codes(good(files_scope=[path])), ["wildcard_root_scope"], path)
        self.assertTrue(validate(good(files_scope=["static/mycast-configurator/*.js"])).ok)   # scoped glob is fine
        self.assertEqual(self.codes(good(files_scope=[])), ["missing_files_scope"])

    def test_missing_acceptance_and_tests(self):
        self.assertEqual(self.codes(good(acceptance_criteria=[])), ["missing_acceptance"])
        self.assertEqual(self.codes(good(acceptance_criteria=["  "])), ["bad_acceptance_criteria"])
        self.assertEqual(self.codes(good(test_commands=None)), ["missing_test_commands"])
        self.assertEqual(self.codes(good(test_commands=["python x.py $(cat .env)"])), ["bad_test_commands"])

    def test_wrong_or_unknown_owner_lane(self):
        self.assertEqual(self.codes(good(owner_lane="gemini")), ["wrong_owner_lane"])
        self.assertEqual(self.codes(good(owner_lane="human")), ["unknown_owner_lane"])
        self.assertTrue(validate(good(owner_lane="gemini"), expected_lane="gemini").ok)

    def test_zero_spend_and_permissions(self):
        self.assertEqual(self.codes(good(budget_cap_usd=5)), ["budget_not_zero"])
        self.assertEqual(self.codes(good(budget_cap_usd=True)), ["budget_not_zero"])
        flags = {k: False for k in PERMISSION_FLAGS}
        for key in PERMISSION_FLAGS:
            self.assertEqual(self.codes(good(permission_flags={**flags, key: True})), ["permission_not_allowed"], key)
        self.assertEqual(self.codes(good(permission_flags={**flags, "deploy": False})), ["unknown_permission_flag"])
        partial = dict(flags); del partial["publish"]
        self.assertEqual(self.codes(good(permission_flags=partial)), ["missing_permission_flag"])

    def test_identifiers(self):
        self.assertEqual(self.codes(good(run_id="run-42cc4719ff45x")), ["bad_run_id"])
        self.assertTrue(validate(good(run_id="run-42cc4719ff45")).ok)
        self.assertEqual(self.codes(good(task_id="do it")), ["bad_task_id"])
        self.assertEqual(self.codes(good(issue_id="261")), ["bad_issue_id"])
        self.assertEqual(self.codes(good(issue_id=True)), ["bad_issue_id"])
        self.assertEqual(self.codes(good(project_id="My Cast")), ["bad_project_id"])
        self.assertEqual(self.codes(good(product_version="latest")), ["bad_product_version"])
        self.assertEqual(self.codes(good(priority="urgent")), ["bad_priority"])
        self.assertEqual(self.codes(good(requested_at="2026-11-08 09:00")), ["bad_requested_at"])
        self.assertEqual(self.codes(good(requested_at="2026-13-40T09:00:00Z")), ["bad_requested_at"])

    def test_depends_and_artifacts(self):
        self.assertEqual(self.codes(good(depends=["soon"])), ["bad_depends"])
        self.assertEqual(self.codes(good(depends=[261])), ["self_dependency"])
        for art in ({"kind": "commit", "ref": "abc"}, {"kind": "pr", "ref": "284"}, {"kind": "url", "ref": "http://x"},
                    {"kind": "file", "ref": "../x"}, {"kind": "zip", "ref": 1}, {"kind": "pr", "ref": 1, "x": 1}):
            self.assertEqual(self.codes(good(input_artifact_refs=[art])), ["bad_artifact_ref"], art)

    def test_every_reason_is_reported_and_unknown_fields_refused(self):
        raw = good(owner_lane="gemini", budget_cap_usd=1, acceptance_criteria=[], extra="x")
        del raw["spec_url"]
        self.assertEqual(self.codes(raw), ["unknown_field", "missing_owner_spec", "wrong_owner_lane",
                                           "missing_acceptance", "budget_not_zero"])
        self.assertEqual(validate([]).codes, ["not_an_object"])

    def test_input_is_not_mutated(self):
        raw = good(); before = copy.deepcopy(raw)
        validate(raw)
        self.assertEqual(raw, before)
        self.assertEqual(json.loads(to_json(validate(raw).request))["schema_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
