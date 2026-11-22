"""T-631 (#270 §2): worker contracts for the 13 logical MVP roles — schema validation, duplicate claim, retry,
failed evidence and approval gates. Offline and pure: no store, no network, no provider."""
import copy
import os
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-mvpcontracts-"))

import mvp_contracts as mk  # noqa: E402
from mvp_cycle import AGENTS  # noqa: E402

PR = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/412"
RUN = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/actions/runs/123456"
ARTIFACT = "/api/mvp-factory/p1/artifacts/spec.md"

BUILD_IN = {"project_id": "p1", "screens": ["home"], "acceptance_criteria": ["home loads"]}
BUILD_OUT = {"pr_url": PR, "tests": ["test_home"]}
V1_DONE = ("ux_designer", "architect")


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class RegistryTest(unittest.TestCase):
    def test_thirteen_roles_valid_and_versioned(self):
        self.assertEqual(len(mk.CONTRACTS), 13)
        self.assertEqual(mk.validate_registry(), [])
        for c in mk.CONTRACTS:
            self.assertEqual(c["schema"], mk.SCHEMA)
            self.assertGreaterEqual(c["version"], 1)
            for key in ("permissions", "trigger", "input_schema", "output_schema", "acceptance", "depends", "retries",
                        "timeout_s", "error_state", "audit_evidence"):
                self.assertIn(key, c, (c["id"], key))
        self.assertEqual(mk.contracts_view()["errors"], [])

    def test_first_and_last_roles_from_the_plan(self):
        self.assertEqual(mk.CONTRACTS[0]["id"], "idea_research")
        self.assertEqual(mk.CONTRACTS[-1]["id"], "product_manager")
        # names used by the T-630 hand-off envelope exist as roles
        labels = {c["label"] for c in mk.CONTRACTS}
        self.assertIn("Product Manager", labels)
        self.assertIn("UI / Builder Worker", labels)

    def test_every_role_runs_on_an_existing_engine_and_every_engine_is_used(self):
        engines = {a["id"]: a["engine"] for a in AGENTS}
        for c in mk.CONTRACTS:
            self.assertEqual(c["engine"], engines[c["cycle_agent"]], c["id"])
        self.assertEqual({c["cycle_agent"] for c in mk.CONTRACTS}, set(engines))

    def test_no_role_holds_an_owner_or_member_action(self):
        for c in mk.CONTRACTS:
            self.assertFalse(set(c["permissions"]) & set(mk.OWNER_ONLY_ACTIONS + mk.MEMBER_ACTIONS), c["id"])

    def test_schema_validation_rejects_broken_contracts(self):
        base = mk.contract("ui_builder")
        cases = {
            "bad_schema": {"schema": "mvp-worker-contract/0"},
            "bad_version": {"version": 0},
            "unknown_cycle_agent": {"cycle_agent": "ghost"},
            "engine_mismatch": {"engine": "openai"},
            "owner_only_action": {"permissions": ["read_project", "approve_proposal"]},
            "member_action": {"permissions": ["handoff"]},
            "unknown_permission": {"permissions": ["deploy_prod"]},
            "bad_trigger": {"trigger": ["cron"]},
            "missing_input_schema": {"input_schema": {}},
            "bad_output_schema_field": {"output_schema": {"pr_url": {"type": "blob", "required": True}}},
            "missing_acceptance": {"acceptance": []},
            "bad_retries": {"retries": 9},
            "bad_timeout": {"timeout_s": 5},
            "bad_error_state": {"error_state": "done"},
            "bad_audit_evidence": {"audit_evidence": ["screenshot"]},
        }
        for code, patch in cases.items():
            c = {**copy.deepcopy(base), **patch}
            self.assertIn(code, mk.validate_contract(c), code)

    def test_registry_rejects_duplicates_unknown_depends_and_cycles(self):
        cs = copy.deepcopy(mk.CONTRACTS)
        self.assertIn("duplicate_id", mk.validate_registry(cs + [copy.deepcopy(cs[0])]))
        cs[1]["depends"] = ["ghost"]
        self.assertIn("market_analyst:unknown_depends:ghost", mk.validate_registry(cs))
        cs = copy.deepcopy(mk.CONTRACTS)
        cs[0]["depends"] = ["product_manager"]  # idea → … → PM → idea
        self.assertIn("depends_cycle", mk.validate_registry(cs))

    def test_payload_validation(self):
        sch = mk.contract("ui_builder")["output_schema"]
        self.assertEqual(mk.validate_payload(sch, BUILD_OUT), [])
        self.assertEqual(mk.validate_payload(sch, {"tests": []}), ["missing:pr_url"])
        self.assertEqual(mk.validate_payload(sch, {"pr_url": "javascript:alert(1)", "tests": []}), ["bad_type:pr_url"])
        self.assertEqual(mk.validate_payload(sch, {**BUILD_OUT, "secret": "x"}), ["unknown_field:secret"])
        self.assertEqual(mk.validate_payload(sch, "nope"), ["not_a_dict"])


class GateTest(unittest.TestCase):
    def test_authorize(self):
        mk.authorize("ui_builder", "open_pr")
        for action, code in (("approve_proposal", "owner_only"), ("publish", "owner_only"), ("spend", "owner_only"),
                             ("handoff", "owner_or_member_only"), ("open_pr", "not_permitted")):
            with self.assertRaises(mk.ContractError) as e:
                mk.authorize("promoter" if action == "open_pr" else "product_manager", action)
            self.assertEqual(e.exception.code, code)
            self.assertEqual(e.exception.status, 403)
        with self.assertRaises(mk.ContractError) as e:
            mk.authorize("ghost", "read_project")
        self.assertEqual(e.exception.code, "unknown_role")

    def test_owner_gate_blocks_downstream_until_approved(self):
        self.assertEqual(mk.ready("ux_designer", ["spec_writer"], []), (False, "owner_approval:spec_writer"))
        self.assertEqual(mk.ready("ux_designer", ["spec_writer"], ["spec_writer"]), (True, ""))
        self.assertEqual(mk.ready("ux_designer", [], ["spec_writer"]), (False, "waiting:spec_writer"))
        self.assertEqual(mk.ready("promoter", ["release_manager"], []), (False, "owner_approval:release_manager"))

    def test_v2_build_needs_an_owner_approved_proposal(self):
        self.assertEqual(mk.ready("ui_builder", ["product_manager"], [], iteration=2),
                         (False, "owner_approval:product_manager"))
        self.assertEqual(mk.ready("ui_builder", ["product_manager"], ["product_manager"], iteration=2), (True, ""))
        self.assertEqual(mk.ready("ui_builder", V1_DONE, [], iteration=1), (True, ""))

    def test_claim_refused_before_approval(self):
        run = mk.ContractRun("ui_builder", "prop-1", clock=Clock())
        with self.assertRaises(mk.ContractError) as e:
            run.claim("claude", "run-0001", done=["product_manager"], iteration=2, payload=BUILD_IN)
        self.assertEqual((e.exception.code, e.exception.status), ("owner_approval:product_manager", 409))
        self.assertEqual(run.state, "queued")
        self.assertEqual(run.attempts, 0)


class RunTest(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.run = mk.ContractRun("ui_builder", "task-1", clock=self.clock)

    def claim(self, worker="claude", run_id="run-0001"):
        return self.run.claim(worker, run_id, done=V1_DONE, payload=BUILD_IN)

    def evidence(self, run_id="run-0001"):
        return {"pr": PR, "relay_run": run_id}

    def test_happy_path_done_with_audit_trail(self):
        self.claim()
        self.run.start("run-0001")
        v = self.run.finish("run-0001", BUILD_OUT, self.evidence())
        self.assertEqual(v["state"], "done")
        self.assertEqual([h["state"] for h in v["history"]], ["claimed", "running", "done"])
        self.assertTrue(all(h["run_id"] == "run-0001" for h in v["history"]))
        self.assertEqual(v["evidence"]["pr"], PR)

    def test_input_validated_before_claim(self):
        with self.assertRaises(mk.ContractError) as e:
            self.run.claim("claude", "run-0001", done=V1_DONE, payload={"project_id": "p1"})
        self.assertTrue(e.exception.code.startswith("bad_input:"))
        self.assertEqual(self.run.state, "queued")

    def test_duplicate_claim_refused_and_same_claim_idempotent(self):
        first = self.claim()
        self.assertEqual(self.claim(), first)  # same worker + run_id → same result, no new attempt
        self.assertEqual(self.run.attempts, 1)
        for worker, run_id in (("chatgpt", "run-0002"), ("claude", "run-0002"), ("chatgpt", "run-0001")):
            with self.assertRaises(mk.ContractError) as e:
                self.claim(worker, run_id)
            self.assertEqual((e.exception.code, e.exception.status), ("duplicate_claim", 409))
        self.run.start("run-0001")
        with self.assertRaises(mk.ContractError) as e:
            self.claim("gemini", "run-0003")
        self.assertEqual(e.exception.code, "duplicate_claim")
        with self.assertRaises(mk.ContractError) as e:
            self.run.finish("run-0003", BUILD_OUT, self.evidence("run-0003"))
        self.assertEqual(e.exception.code, "not_claim_owner")
        self.run.finish("run-0001", BUILD_OUT, self.evidence())
        with self.assertRaises(mk.ContractError) as e:
            self.claim("claude", "run-0004")
        self.assertEqual(e.exception.code, "already_done")

    def test_retry_then_error_state(self):
        retries = self.run.contract["retries"]
        for i in range(retries + 1):
            rid = f"run-{i:04d}"
            self.claim(run_id=rid)
            self.run.start(rid)
            v = self.run.fail(rid, "ci red")
            if i < retries:
                self.assertEqual(v["state"], "queued")
                with self.assertRaises(mk.ContractError) as e:
                    self.claim(run_id=rid)  # a failed run id never comes back
                self.assertEqual(e.exception.code, "stale_run")
        self.assertEqual(v["state"], self.run.contract["error_state"])
        self.assertEqual(v["attempts"], v["max_attempts"])
        with self.assertRaises(mk.ContractError) as e:
            self.claim(run_id="run-9999")
        self.assertEqual(e.exception.code, "terminal")

    def test_zero_retries_goes_straight_to_error_state(self):
        c = mk.contract("qa_tester")
        run = mk.ContractRun("qa_tester", "t", clock=self.clock)
        self.assertGreaterEqual(c["retries"], 0)
        orig = c["retries"]
        try:
            c["retries"] = 0
            run.claim("claude", "run-0001", done=["ui_builder", "backend_builder"],
                      payload={"project_id": "p1", "pr_url": PR})
            run.start("run-0001")
            self.assertEqual(run.fail("run-0001", "x")["state"], "failed")
        finally:
            c["retries"] = orig

    def test_failed_evidence_is_a_failed_attempt_never_done(self):
        bad = [
            {"pr": "https://example.com/pull/1", "relay_run": "run-0001"},  # not a GitHub PR
            {"pr": PR},  # no Relay run id
            {"pr": PR, "relay_run": "run-other"},  # run id of another run
            "done",  # not evidence at all
        ]
        expected = ["evidence:pr", "evidence:relay_run", "evidence:relay_run", "not_a_dict"]
        for i, ev in enumerate(bad):
            self.run = mk.ContractRun("ui_builder", f"task-{i}", clock=self.clock)
            self.claim()
            self.run.start("run-0001")
            v = self.run.finish("run-0001", BUILD_OUT, ev)
            self.assertEqual((v["state"], v["error"]), ("queued", expected[i]), ev)
            self.assertIsNone(v["output"])
            self.assertIsNone(v["evidence"])

    def test_invalid_output_is_a_failed_attempt(self):
        self.claim()
        self.run.start("run-0001")
        v = self.run.finish("run-0001", {"tests": []}, self.evidence())
        self.assertEqual(v["state"], "queued")
        self.assertIn("missing:pr_url", v["error"])

    def test_timeout(self):
        self.claim()
        self.run.start("run-0001")
        self.clock.t += self.run.contract["timeout_s"] - 1
        self.assertEqual(self.run.check_timeout()["state"], "running")
        self.clock.t += 2
        v = self.run.check_timeout()
        self.assertEqual((v["state"], v["error"]), ("queued", "timeout"))
        self.claim(run_id="run-0002")
        self.run.start("run-0002")
        self.clock.t += self.run.contract["timeout_s"] + 1
        self.assertEqual(self.run.finish("run-0002", BUILD_OUT, self.evidence("run-0002"))["error"], "timeout")

    def test_evidence_kinds_per_role(self):
        self.assertEqual(mk.check_evidence("idea_research", {"sources": ["https://example.org/a"],
                                                             "artifact": [ARTIFACT]}), [])
        self.assertEqual(mk.check_evidence("idea_research", {"sources": ["http://x"], "artifact": ["/etc/passwd"]}),
                         ["evidence:sources", "evidence:artifact"])
        self.assertEqual(mk.check_evidence("qa_tester", {"actions_run": RUN}), [])
        self.assertEqual(mk.check_evidence("qa_tester", {"actions_run": PR}), ["evidence:actions_run"])
        self.assertEqual(mk.check_evidence("feedback_synthesis", {"feedback_ids": []}), ["evidence:feedback_ids"])
        self.assertEqual(mk.check_evidence("product_manager", {"feedback_ids": ["fb-1"], "artifact": [ARTIFACT]}), [])

    def test_bad_claims(self):
        for worker, rid in (("", "run-0001"), ("claude", "x"), ("claude", "bad id with spaces")):
            with self.assertRaises(mk.ContractError) as e:
                self.run.claim(worker, rid, done=V1_DONE, payload=BUILD_IN)
            self.assertEqual(e.exception.code, "bad_claim")
        with self.assertRaises(mk.ContractError) as e:
            self.run.start("run-0001")
        self.assertEqual(e.exception.code, "bad_state")


if __name__ == "__main__":
    unittest.main(verbosity=2)
