"""#240 MVP Factory: executable state-machine contract tests. Offline, deterministic, DEMO only.

These tests exercise the REAL code, not a parallel model:
- ``mvp_factory.MvpRegistry`` owns the stage machine (STAGES / NEXT / TERMINAL / owner-only targets, evidence,
  block/unblock, idempotency keys). It runs against a temporary JSON file with a fixed clock.
- ``mvp_builder_request.validate`` is the "scoped spec" gate (scope, owner lane, zero spend, no publish flags).
- ``mvp_builder_preflight.evaluate`` is the "assignment" gate (claim conflict, operator unavailable, spend).
- ``mvp_builder_manifest.validate`` is the "artifact / PR" gate (ready_for_qa, no merge/deploy claims).
- ``mvp_builder_projection.project`` keeps demo events apart from the real card.

Issue phase -> registry stages (docs/MVP_FACTORY_SPEC.md "State machine"):
  idea -> idea; scoped spec -> researching, spec_draft, spec_review; assignment -> build_queued;
  artifact/PR -> building, qa_review; review -> preview_ready, owner_review; owner approve -> validated;
  publish/closed -> validated|rejected are terminal. Publishing is NOT a registry transition at all: there is no
  ``publish`` kind and ``approval.publish`` stays False. Owner rejection is terminal (the spec has no
  "back to spec" edge), so these tests assert that and do not invent one.

Known gap, recorded rather than patched: the registry does not call the Builder gates itself (wiring Relay claims
into the Builder is M2, #186). ``DemoPipeline`` below composes them the way MVP Manager must: the gate runs first
and the registry is only asked to advance when the gate passes.

Every project, actor and note written here is marked DEMO. Pilots #187-#189 are never touched.
"""
import re
import tempfile
import unittest
from pathlib import Path

import mvp_factory
from mvp_builder_manifest import redacted_example, validate as validate_manifest
from mvp_builder_preflight import BLOCKED, NEEDS_OWNER, READY, UNKNOWN, evaluate as preflight
from mvp_builder_projection import project as project_events
from mvp_builder_request import PERMISSION_FLAGS, SCHEMA_VERSION, validate as validate_request
from mvp_factory import REPO, MvpError, MvpRegistry

NOW = "2026-11-08T12:00:00Z"
DEMO_ID = "demo-contract"
DEMO_ACTOR = "DEMO contract test"
EVIDENCE = f"{REPO}/issues/240"
PILOTS = {"decision-memory": 187, "mybrief-pro": 188, "release-guardian": 189}

# The contract: stage -> the only allowed forward stage. Must equal the registry's table exactly.
EXPECTED_NEXT = {
    "idea": "researching", "researching": "spec_draft", "spec_draft": "spec_review", "spec_review": "build_queued",
    "build_queued": "building", "building": "qa_review", "qa_review": "preview_ready",
    "preview_ready": "owner_review", "owner_review": "validated",
}
PHASES = {
    "idea": ("idea",), "scoped_spec": ("researching", "spec_draft", "spec_review"), "assignment": ("build_queued",),
    "artifact_pr": ("building", "qa_review"), "review": ("preview_ready", "owner_review"),
    "owner_approve": ("validated",), "closed": ("validated", "rejected"),
}
# Gate guarding the step INTO each stage (None = evidence link only).
GUARDS = {"build_queued": "request+preflight", "qa_review": "manifest", "validated": "owner"}
HAPPY_TRACE = [("idea", "idea")] + list(EXPECTED_NEXT.items())


def demo_request(**over):
    req = {
        "schema_version": SCHEMA_VERSION, "project_id": DEMO_ID, "product_version": "v1", "spec_revision": "r1",
        "spec_url": EVIDENCE, "spec_approved": True, "issue_id": 240, "task_id": "T-0240", "owner_lane": "claude",
        "priority": "P2", "depends": [], "files_scope": ["test_mvp_state_machine.py"], "input_artifact_refs": [],
        "acceptance_criteria": ["DEMO transition table holds"], "test_commands": ["python test_mvp_state_machine.py"],
        "permission_flags": {k: False for k in PERMISSION_FLAGS}, "budget_cap_usd": 0,
        "requested_at": "2026-11-08T09:00:00Z"}
    req.update(over)
    return req


def demo_facts(**over):
    f = {"issue": {"status": "ok", "owner": "Claude", "state": "open"},
         "spec": {"status": "ok", "approved": True},
         "gates": {"status": "ok", "owner_approval": "granted"},
         "active_prs": {"status": "ok", "prs": []},
         "claim": {"status": "ok", "run_id": None},
         "runtime": {"status": "ok", "subscription_available": True, "worker_online": True},
         "cost": {"status": "ok", "estimated_usd": 0}}
    f.update(over)
    return f


class DemoPipeline:
    """MVP Manager composition for tests: a gate must pass before the real registry is asked to advance."""

    def __init__(self, reg: MvpRegistry):
        self.reg = reg

    def stage(self):
        return next(p for p in self.reg.snapshot()["projects"] if p["id"] == DEMO_ID)["stage"]

    def advance(self, *, role="member", request=None, facts=None, manifest=None, key=""):
        """Returns ("ok", registry_result) or ("refused", [codes]). Refusal never touches the registry."""
        target = EXPECTED_NEXT.get(self.stage())
        guard = GUARDS.get(target)
        if guard == "request+preflight":
            req = validate_request(request if request is not None else demo_request())
            if not req.ok:
                return "refused", req.codes
            out = preflight(req.request, facts if facts is not None else demo_facts(), now=NOW)
            if out["verdict"] != READY:
                return "refused", [r["code"] for r in out["reasons"]]
        elif guard == "manifest":
            res = validate_manifest(manifest if manifest is not None else redacted_example(), now=NOW)
            if not res.ok:
                return "refused", res.codes
            if not res.manifest["ready_for_qa"]:
                return "refused", ["not_ready_for_qa"]
        try:
            return "ok", self.reg.record(DEMO_ID, "advance", actor_role=role, actor=DEMO_ACTOR, evidence=[EVIDENCE],
                                         note=f"DEMO: -> {target}", idempotency_key=key)
        except MvpError as exc:
            return "refused", [exc.code]


class MvpStateMachineContractTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.reg = MvpRegistry(Path(self.dir.name) / "mvp_factory.json", clock=lambda: self.t[0])
        self.pilots_before = self._pilots()
        self.reg.add_project(DEMO_ID, "DEMO · #240 state-machine contract", 240, actor_role="owner")
        self.p = DemoPipeline(self.reg)

    def tearDown(self):
        # Every test, whatever it did to the demo project, must leave pilots #187-#189 exactly as seeded.
        self.assertEqual(self._pilots(), self.pilots_before)
        self.dir.cleanup()

    def _pilots(self):
        snap = self.reg.snapshot(limit_events=10_000)
        return {p["id"]: (p["stage"], p["blocked"], p["approval"], [e["id"] for e in snap["events"] if e["project"] == p["id"]])
                for p in snap["projects"] if p["id"] in PILOTS}

    def _events(self):
        return [e for e in self.reg.snapshot(limit_events=10_000)["events"] if e["project"] == DEMO_ID]

    def code(self, fn):
        with self.assertRaises(MvpError) as ctx:
            fn()
        return ctx.exception.code

    def walk_to(self, stage):
        while self.p.stage() != stage:
            role = "owner" if EXPECTED_NEXT[self.p.stage()] in mvp_factory.OWNER_ONLY_TARGETS else "member"
            status, out = self.p.advance(role=role)
            self.assertEqual(status, "ok", out)

    # --- the table itself -------------------------------------------------------------------------------------
    def test_transition_table_matches_registry(self):
        self.assertEqual(mvp_factory.NEXT, EXPECTED_NEXT)
        self.assertEqual(mvp_factory.STAGES, tuple(EXPECTED_NEXT) + ("validated", "rejected"))
        self.assertEqual(mvp_factory.TERMINAL, ("validated", "rejected"))
        self.assertEqual(mvp_factory.OWNER_ONLY_TARGETS, ("validated", "rejected"))
        self.assertNotIn("publish", mvp_factory.KINDS)
        covered = {s for stages in PHASES.values() for s in stages}
        self.assertEqual(covered, set(mvp_factory.STAGES))
        for stage in mvp_factory.TERMINAL:
            self.assertNotIn(stage, mvp_factory.NEXT)

    # --- happy path -------------------------------------------------------------------------------------------
    def test_happy_path_trace(self):
        for _ in range(len(EXPECTED_NEXT)):
            role = "owner" if EXPECTED_NEXT[self.p.stage()] == "validated" else "member"
            status, out = self.p.advance(role=role)
            self.assertEqual(status, "ok", out)
            self.t[0] += 60
        trace = [(e["from_stage"], e["to_stage"]) for e in self._events()]
        self.assertEqual(trace, HAPPY_TRACE)
        project = next(p for p in self.reg.snapshot()["projects"] if p["id"] == DEMO_ID)
        self.assertEqual(project["stage"], "validated")
        self.assertEqual(project["approval"], {"deploy": False, "outreach": False, "publish": False})  # no auto-publish
        self.assertEqual(mvp_factory.recommend(project), {"decision": "hold", "reason": "closed"})
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "advance", actor_role="owner", actor=DEMO_ACTOR,
                                                           evidence=[EVIDENCE])), "project_closed")

    def test_trace_is_deterministic(self):
        def run_once():
            with tempfile.TemporaryDirectory() as d:
                t = [1_800_000_000.0]
                reg = MvpRegistry(Path(d) / "mvp_factory.json", clock=lambda: t[0])
                reg.add_project(DEMO_ID, "DEMO · #240 state-machine contract", 240, actor_role="owner")
                pipe = DemoPipeline(reg)
                while pipe.stage() in EXPECTED_NEXT:
                    role = "owner" if EXPECTED_NEXT[pipe.stage()] == "validated" else "member"
                    self.assertEqual(pipe.advance(role=role)[0], "ok")
                    t[0] += 60
                return [(e["from_stage"], e["to_stage"], e["kind"], e["at"], e["note"])
                        for e in reg.snapshot(limit_events=10_000)["events"] if e["project"] == DEMO_ID]
        first = run_once()
        self.assertEqual(first, run_once())
        self.assertEqual([(a, b) for a, b, *_ in first], HAPPY_TRACE)

    # --- publish is never automatic --------------------------------------------------------------------------
    def test_publish_requires_explicit_owner_approval(self):
        self.walk_to("owner_review")
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "publish", actor_role="owner")), "bad_kind")
        self.assertEqual(self.p.advance(role="member"), ("refused", ["owner_only"]))
        self.assertEqual(self.p.stage(), "owner_review")
        self.assertEqual(mvp_factory.recommend({"stage": "owner_review"})["decision"], "owner")
        self.assertEqual(self.p.advance(role="owner")[0], "ok")
        self.assertEqual(self.p.stage(), "validated")

    def test_llm_assertion_without_evidence_does_not_advance(self):
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "advance", actor_role="member", actor=DEMO_ACTOR,
                                                           note="DEMO: the model says it is done")), "evidence_required")
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "advance", actor_role="member", actor=DEMO_ACTOR,
                                                           evidence=["https://example.com/done"])), "bad_evidence")
        self.assertEqual(self.p.stage(), "idea")

    # --- negative: missing scope / owner -----------------------------------------------------------------------
    def test_missing_scope_refuses_assignment(self):
        self.walk_to("spec_review")
        for over, code in ((dict(files_scope=[]), "missing_files_scope"), (dict(files_scope=["*"]), "wildcard_root_scope"),
                           (dict(acceptance_criteria=[]), "missing_acceptance"), (dict(spec_url=""), "missing_owner_spec"),
                           (dict(spec_approved=False), "spec_not_owner_approved")):
            status, codes = self.p.advance(request=demo_request(**over))
            self.assertEqual(status, "refused")
            self.assertIn(code, codes)
        self.assertEqual(self.p.stage(), "spec_review")

    def test_missing_owner_refuses_assignment(self):
        self.walk_to("spec_review")
        status, codes = self.p.advance(request=demo_request(owner_lane=""))
        self.assertEqual((status, codes), ("refused", ["unknown_owner_lane"]))
        status, codes = self.p.advance(facts=demo_facts(issue={"status": "ok", "owner": "", "state": "open"}))
        self.assertEqual((status, codes), ("refused", ["owner_unknown"]))
        status, codes = self.p.advance(request=demo_request(owner_lane="gemini"))
        self.assertEqual((status, codes), ("refused", ["wrong_owner_lane"]))
        self.assertEqual(self.p.stage(), "spec_review")

    # --- negative: operator (Claude / Gemini) unavailable ---------------------------------------------------
    def test_operator_unavailable_refuses_assignment(self):
        self.walk_to("spec_review")
        cases = (
            ({"status": "ok", "subscription_available": False, "worker_online": True}, BLOCKED, "no_subscription"),
            ({"status": "ok", "subscription_available": True, "worker_online": False}, BLOCKED, "worker_offline"),
            ({"status": "forbidden"}, UNKNOWN, "fact_forbidden"),
            ({"status": "ok", "subscription_available": None, "worker_online": True}, UNKNOWN, "subscription_unknown"),
        )
        req = validate_request(demo_request()).request
        for runtime, verdict, code in cases:
            self.assertEqual(preflight(req, demo_facts(runtime=runtime), now=NOW)["verdict"], verdict)
            self.assertEqual(self.p.advance(facts=demo_facts(runtime=runtime)), ("refused", [code]))
        # Gemini holding the issue while the Builder lane is Claude is a hard stop, not a fallback.
        gem = demo_facts(issue={"status": "ok", "owner": "Gemini", "state": "open"})
        self.assertEqual(self.p.advance(facts=gem), ("refused", ["owner_mismatch"]))
        self.assertEqual(self.p.stage(), "spec_review")

    # --- negative: owner rejects -------------------------------------------------------------------------------
    def test_owner_rejects_preview_is_terminal(self):
        self.walk_to("owner_review")
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "reject", actor_role="member", actor=DEMO_ACTOR)),
                         "owner_only")
        out = self.reg.record(DEMO_ID, "reject", actor_role="owner", actor=DEMO_ACTOR, note="DEMO: owner rejects")
        self.assertEqual((out["event"]["from_stage"], out["event"]["to_stage"]), ("owner_review", "rejected"))
        self.assertEqual(self.p.advance(role="owner"), ("refused", ["project_closed"]))
        for kind in ("block", "unblock", "reject"):
            self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, kind, actor_role="owner", actor=DEMO_ACTOR,
                                                               reason="DEMO")), "project_closed")
        self.reg.record(DEMO_ID, "note", actor_role="owner", actor=DEMO_ACTOR, note="DEMO: notes stay allowed")
        self.assertEqual(self.p.stage(), "rejected")

    def test_owner_rejects_spec_is_terminal_too(self):
        self.walk_to("spec_review")
        self.reg.record(DEMO_ID, "reject", actor_role="owner", actor=DEMO_ACTOR, note="DEMO: spec rejected")
        self.assertEqual(self.p.stage(), "rejected")
        self.assertEqual(self.p.advance(), ("refused", ["project_closed"]))

    def test_owner_pending_approval_gate_refuses_assignment(self):
        self.walk_to("spec_review")
        for approval in ("pending", "denied"):
            facts = demo_facts(gates={"status": "ok", "owner_approval": approval})
            self.assertEqual(preflight(validate_request(demo_request()).request, facts, now=NOW)["verdict"], NEEDS_OWNER)
            self.assertEqual(self.p.advance(facts=facts), ("refused", ["owner_approval_" + approval]))
        self.assertEqual(self.p.stage(), "spec_review")

    # --- negative: duplicate event -----------------------------------------------------------------------------
    def test_duplicate_event_is_a_noop(self):
        def deliver():   # one event, delivered twice with identical bytes (a Relay/HTTP retry)
            return self.reg.record(DEMO_ID, "advance", actor_role="member", actor=DEMO_ACTOR, evidence=[EVIDENCE],
                                   note="DEMO: -> researching", idempotency_key="demo-key-1")
        first = deliver()
        self.assertEqual((first["duplicate"], self.p.stage()), (False, "researching"))
        before = self._events()
        self.t[0] += 3600
        again = deliver()
        self.assertTrue(again["duplicate"])
        self.assertEqual(again["event"], first["event"])
        self.assertEqual(self._events(), before)
        self.assertEqual(self.p.stage(), "researching")            # not researching -> spec_draft

    def test_reused_key_for_another_operation_is_refused(self):
        self.reg.record(DEMO_ID, "note", actor_role="member", actor=DEMO_ACTOR, note="DEMO: a", idempotency_key="demo-k")
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "note", actor_role="member", actor=DEMO_ACTOR,
                                                           note="DEMO: b", idempotency_key="demo-k")), "idempotency_conflict")

    def test_duplicate_owner_approval_after_close_does_not_reopen(self):
        self.walk_to("owner_review")
        self.assertEqual(self.p.advance(role="owner", key="demo-approve")[0], "ok")
        n = len(self._events())
        # A retried delivery of the very same approval: the registry replays the first result, adds nothing.
        out = self.reg.record(DEMO_ID, "advance", actor_role="owner", actor=DEMO_ACTOR, evidence=[EVIDENCE],
                              note="DEMO: -> validated", idempotency_key="demo-approve")
        self.assertEqual((out["duplicate"], len(self._events()), self.p.stage()), (True, n, "validated"))
        # Without the key it is a new operation on a closed project and is refused.
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "advance", actor_role="owner", actor=DEMO_ACTOR,
                                                           evidence=[EVIDENCE])), "project_closed")

    # --- negative: claim conflict ------------------------------------------------------------------------------
    def test_claim_conflict_refuses_assignment(self):
        self.walk_to("spec_review")
        held = demo_facts(claim={"status": "ok", "run_id": "run-aaaaaaaa", "lease_expires_at": "2026-11-08T13:00:00Z"})
        self.assertEqual(self.p.advance(facts=held), ("refused", ["already_claimed"]))
        stale = demo_facts(claim={"status": "ok", "run_id": "run-aaaaaaaa", "lease_expires_at": "2026-11-08T11:00:00Z"})
        self.assertEqual(self.p.advance(facts=stale), ("refused", ["stale_claim"]))          # never assumed free
        overlap = demo_facts(active_prs={"status": "ok", "prs": [{"number": 1, "files": ["test_mvp_state_machine.py"]}]})
        self.assertEqual(self.p.advance(facts=overlap), ("refused", ["file_conflict"]))
        self.assertEqual(self.p.stage(), "spec_review")

    # --- negative: paid feature without permission -------------------------------------------------------------
    def test_paid_feature_without_permission_refuses_assignment(self):
        self.walk_to("spec_review")
        paid = demo_request(permission_flags=dict({k: False for k in PERMISSION_FLAGS}, paid_api=True))
        self.assertEqual(self.p.advance(request=paid), ("refused", ["permission_not_allowed"]))
        publish = demo_request(permission_flags=dict({k: False for k in PERMISSION_FLAGS}, publish=True))
        self.assertEqual(self.p.advance(request=publish), ("refused", ["permission_not_allowed"]))
        self.assertEqual(self.p.advance(request=demo_request(budget_cap_usd=5)), ("refused", ["budget_not_zero"]))
        spend = demo_facts(cost={"status": "ok", "estimated_usd": 0.5})
        self.assertEqual(self.p.advance(facts=spend), ("refused", ["unauthorized_spend"]))
        self.assertEqual(self.p.stage(), "spec_review")

    # --- negative: artifact / PR gate --------------------------------------------------------------------------
    def test_artifact_gate_refuses_unready_or_overclaiming_manifest(self):
        self.walk_to("building")
        failed = redacted_example()
        failed["tests"][0]["result"] = "failed"
        self.assertEqual(self.p.advance(manifest=failed), ("refused", ["not_ready_for_qa"]))
        merged = dict(redacted_example(), merged=True)
        status, codes = self.p.advance(manifest=merged)
        self.assertEqual(status, "refused")
        self.assertIn("unverifiable_claim", codes)
        self.assertEqual(self.p.stage(), "building")
        self.assertEqual(self.p.advance()[0], "ok")
        self.assertEqual(self.p.stage(), "qa_review")

    # --- blocked from any open stage ---------------------------------------------------------------------------
    def test_blocked_needs_reason_and_freezes_the_stage(self):
        self.walk_to("building")
        self.assertEqual(self.code(lambda: self.reg.record(DEMO_ID, "block", actor_role="member", actor=DEMO_ACTOR)),
                         "reason_required")
        self.reg.record(DEMO_ID, "block", actor_role="member", actor=DEMO_ACTOR, reason="DEMO: CI missing")
        self.assertEqual(self.p.advance(), ("refused", ["project_blocked"]))
        self.reg.record(DEMO_ID, "unblock", actor_role="member", actor=DEMO_ACTOR, note="DEMO: CI back")
        self.assertEqual(self.p.advance()[0], "ok")

    # --- DEMO marking and isolation from live pilots -----------------------------------------------------------
    def test_every_demo_record_is_marked_demo(self):
        self.walk_to("owner_review")
        self.reg.record(DEMO_ID, "reject", actor_role="owner", actor=DEMO_ACTOR, note="DEMO: closing")
        project = next(p for p in self.reg.snapshot()["projects"] if p["id"] == DEMO_ID)
        self.assertTrue(project["title"].startswith("DEMO"))
        events = self._events()
        added, recorded = events[0], events[1:]
        self.assertEqual((added["kind"], added["note"]), ("note", "Project added."))   # the registry's own text
        self.assertTrue(recorded)
        for e in recorded:
            self.assertEqual(e["actor"], DEMO_ACTOR, e)
            self.assertTrue(e["note"].startswith("DEMO"), e)
            self.assertEqual(e["evidence_check"], "link_shape_only")         # never "verified"

    def test_demo_builder_events_never_reach_the_real_card(self):
        def ev(at, stage):
            return {"at": at, "stage": stage, "actor": "claude", "run_id": "run-dddddddd", "source": "demo",
                    "verified": True, "evidence": EVIDENCE, "project": DEMO_ID}
        demo = [ev("2026-11-08T09:00:00Z", "claimed"), ev("2026-11-08T09:01:00Z", "heartbeat"),
                ev("2026-11-08T09:30:00Z", "owner_review"), ev("2026-11-08T09:31:00Z", "approved")]
        out = project_events(demo, now=NOW)
        self.assertFalse(out["real"]["demo"])
        self.assertIsNone(out["real"]["run_id"])
        self.assertIsNone(out["real"]["last_evidence"])
        self.assertFalse(out["real"]["verified"])
        self.assertIsNone(out["real"]["labels"]["en"]["demo"])
        self.assertTrue(out["demo"]["demo"])
        self.assertEqual(out["demo"]["stage"], "approved")
        self.assertIsNotNone(out["demo"]["labels"]["en"]["demo"])
        self.assertEqual((out["demo"]["merge_state"], out["demo"]["deploy_state"]), ("UNKNOWN", "UNKNOWN"))

    def test_pilots_are_separate_and_not_referenced(self):
        # Full flow plus refusals; tearDown asserts the pilots are byte-for-byte as seeded.
        self.walk_to("validated")
        pilot_link = re.compile(r"/issues/(187|188|189)\b")
        for e in self._events():
            self.assertFalse(any(pilot_link.search(x) for x in e["evidence"]), e)
            self.assertFalse(pilot_link.search(e["note"]), e)
        self.assertNotIn(DEMO_ID, PILOTS)
        for pid, (stage, blocked, approval, _) in self.pilots_before.items():
            self.assertEqual((stage, blocked), ("idea", None), pid)                 # seed says idea, nothing live
            self.assertFalse(any(approval.values()), pid)
        self.assertEqual(self.pilots_before, self._pilots())


if __name__ == "__main__":
    unittest.main(verbosity=2)
