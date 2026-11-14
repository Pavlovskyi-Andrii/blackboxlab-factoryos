"""T-608 A/B Tester S1: experiments with branches A/B inside the MVP registry (acceptance plan from #348 §6.1/6.2)."""
import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path

import fastapi

from mvp_factory import MvpError, MvpRegistry
from mvp_experiments import Experiments, install_mvp_experiment_routes, validate_copy

PID = "mycast"


def spec(**over):
    body = {"id": "mc-exp-focus-001", "mode": "SEGMENT_COMPARISON", "concept_id": "mc-focus-001",
            "hypothesis": "Founders and personal-goal listeners respond to different positioning.",
            "branches": [{"id": "a", "label": "Business focus", "persona": "entrepreneurs"},
                         {"id": "b", "label": "Personal goals", "persona": "personal_goals"}]}
    body.update(over)
    return body


COPY = {"headline": "Start the day focused on your business", "subhead": "One short daily audio briefing.",
        "cta": "Listen to a sample", "bullets": ["Your sources", "Your schedule"],
        "posts": {"short": ["Morning focus in 7 minutes.", "Your briefing, your sources."], "medium": ["A longer draft."]}}


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0

    def __call__(self):
        self.t += 1
        return self.t


class ExperimentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "mvp_factory.json"
        self.reg = MvpRegistry(self.path, clock=Clock())
        self.ex = Experiments(self.reg)

    def tearDown(self):
        self.tmp.cleanup()

    def project(self):
        return json.loads(self.path.read_text())["projects"][PID]

    def code(self, fn, *a, **kw):
        with self.assertRaises(MvpError) as cm:
            fn(*a, **kw)
        return cm.exception.code

    def test_valid_segment_comparison_lives_in_the_project_and_leaves_its_stage_alone(self):
        self.reg.snapshot()
        before = self.project()["stage"]
        out = self.ex.create(PID, spec(), actor_role="member", actor="m@x")["experiment"]
        self.assertEqual([b["id"] for b in out["branches"]], ["a", "b"])           # A always first (rendered on top)
        self.assertEqual(out["comparison"], {"winner": None, "lift": None, "significance": None, "reason": "segment_comparison"})
        self.assertTrue(all(v is None for b in out["branches"] for v in b["measurement"].values()))
        self.assertTrue(all(c["status"] == "placeholder" for b in out["branches"] for c in b["channels"]))
        self.assertTrue(all(not b["approval"][k] for b in out["branches"] for k in ("publish", "spend", "outreach")))
        p = self.project()
        self.assertEqual(p["stage"], before)
        self.assertIn("mc-exp-focus-001", p["experiments"])
        ev = json.loads(self.path.read_text())["events"][-1]
        self.assertEqual((ev["experiment"], ev["kind"], ev["evidence_check"]), ("mc-exp-focus-001", "note", "link_shape_only"))

    def test_refused_shapes(self):
        c = lambda body: self.code(self.ex.create, PID, body, actor_role="owner")
        one = spec(); one["branches"] = one["branches"][:1]
        self.assertEqual(c(one), "two_branches_required")
        swapped = spec(); swapped["branches"] = swapped["branches"][::-1]
        self.assertEqual(c(swapped), "branch_ids_a_b")
        self.assertEqual(c(spec(id="Bad_ID")), "bad_id")
        self.assertEqual(c(spec(mode="CREATIVE_COMPARE")), "bad_mode")
        self.assertEqual(c(spec(winner="a")), "unknown_fields")
        m = spec(); m["branches"][0]["measurement"] = {"signups": 10}
        self.assertEqual(c(m), "metrics_not_supported")
        ap = spec(); ap["branches"][1]["approval"] = {"publish": True}
        self.assertEqual(c(ap), "approval_not_settable")
        ch = spec(); ch["branches"][0]["channels"] = [{"id": "facebook", "status": "live"}]
        self.assertEqual(c(ch), "channels_are_placeholders")
        same = spec(); same["branches"][1]["persona"] = "entrepreneurs"
        self.assertEqual(c(same), "same_segment")
        self.assertEqual(c(spec(hypothesis="Guaranteed results for everyone")), "copy_health_claim")
        self.assertEqual(self.code(self.ex.create, PID, spec(), actor_role="viewer"), "forbidden")
        self.assertEqual(self.code(self.ex.create, "nope", spec(), actor_role="owner"), "unknown_project")
        # CONTROLLED_AB is accepted only as a declared draft (no randomized assignment exists)
        ab = self.ex.create(PID, spec(id="mc-exp-ab-001", mode="CONTROLLED_AB"), actor_role="owner")["experiment"]
        self.assertEqual((ab["state"], ab["comparison"]["reason"]), ("draft", "not_instrumented"))

    def test_copy_deny_list_and_personal_data(self):
        self.assertEqual(self.code(validate_copy, dict(COPY, headline="Lose weight in 7 days")), "copy_health_claim")
        self.assertEqual(self.code(validate_copy, dict(COPY, subhead="Схудни за тиждень")), "copy_health_claim")
        self.assertEqual(self.code(validate_copy, dict(COPY, cta="Write me: me@site.com")), "copy_personal_data")
        self.assertEqual(self.code(validate_copy, dict(COPY, subhead="Call +380 67 123 45 67")), "copy_personal_data")
        self.assertEqual(validate_copy(dict(COPY, subhead="Secure, healthy habits since 2026-11-14"))["subhead"],
                         "Secure, healthy habits since 2026-11-14")              # no false positives on words/dates
        self.assertEqual(self.code(validate_copy, dict(COPY, posts={"short": ["1", "2", "3"]})), "bad_posts")

    def test_idempotency(self):
        body = spec(idempotency_key="k-1")
        first = self.ex.create(PID, dict(body), actor_role="owner")
        again = self.ex.create(PID, dict(body), actor_role="owner")
        self.assertEqual((first["duplicate"], again["duplicate"]), (False, True))
        self.assertEqual(again["experiment"]["id"], first["experiment"]["id"])
        self.assertEqual(self.code(self.ex.create, PID, spec(id="other-exp", idempotency_key="k-1"), actor_role="owner"),
                         "idempotency_conflict")
        self.assertEqual(self.code(self.ex.create, PID, spec(), actor_role="owner"), "experiment_exists")

    def test_preview_approval_is_owner_only_per_branch_and_per_revision(self):
        self.ex.create(PID, spec(), actor_role="owner")
        r1 = self.ex.save_draft(PID, "mc-exp-focus-001", "a", dict(COPY), actor_role="member")["branch"]
        self.assertEqual((r1["revision"], r1["preview_approved"]), (1, False))
        self.assertEqual(self.code(self.ex.approve_preview, PID, "mc-exp-focus-001", "a", 1, actor_role="member"), "owner_only")
        ok = self.ex.approve_preview(PID, "mc-exp-focus-001", "a", 1, actor_role="owner")["branch"]
        self.assertTrue(ok["preview_approved"])
        b = next(x for x in self.project()["experiments"]["mc-exp-focus-001"]["branches"] if x["id"] == "b")
        self.assertIsNone(b["approval"]["preview"])                                # approving A leaves B untouched
        r2 = self.ex.save_draft(PID, "mc-exp-focus-001", "a", dict(COPY, cta="Try a sample"), actor_role="owner")["branch"]
        self.assertEqual((r2["revision"], r2["preview_approved"]), (2, False))    # new revision is not approved
        self.assertEqual(self.code(self.ex.approve_preview, PID, "mc-exp-focus-001", "a", 1, actor_role="owner"), "stale_revision")
        self.assertEqual(self.code(self.ex.approve_preview, PID, "mc-exp-focus-001", "b", 1, actor_role="owner"), "stale_revision")
        a = next(x for x in self.project()["experiments"]["mc-exp-focus-001"]["branches"] if x["id"] == "a")
        self.assertFalse(a["approval"]["publish"])                                  # preview approval ≠ publish approval

    def test_decision_closes_without_winner_and_rejected_projects_refuse(self):
        self.ex.create(PID, spec(), actor_role="owner")
        self.assertEqual(self.code(self.ex.decide, PID, "mc-exp-focus-001", {"choice": "both"}, actor_role="member"), "owner_only")
        self.assertEqual(self.code(self.ex.decide, PID, "mc-exp-focus-001", {"choice": "both", "winner": "a"}, actor_role="owner"),
                         "unknown_fields")
        out = self.ex.decide(PID, "mc-exp-focus-001", {"choice": "iterate", "note": "Re-test copy"}, actor_role="owner")["experiment"]
        self.assertEqual((out["state"], out["decision"]["choice"]), ("closed", "iterate"))
        self.assertNotIn("winner", out["decision"])
        self.assertEqual(self.code(self.ex.save_draft, PID, "mc-exp-focus-001", "a", dict(COPY), actor_role="owner"),
                         "experiment_closed")
        self.reg.record(PID, "reject", actor_role="owner", reason="test")
        self.assertEqual(self.code(self.ex.create, PID, spec(id="after-reject"), actor_role="owner"), "project_closed")

    def test_old_registries_load_unchanged_and_damage_is_refused(self):
        self.reg.snapshot()
        raw = self.path.read_text()
        MvpRegistry(self.path).snapshot()
        self.assertEqual(self.path.read_text(), raw)                               # no experiments key until first write
        self.assertNotIn("experiments", raw)
        self.path.write_text("{oops")
        self.assertEqual(self.code(self.ex.create, PID, spec(), actor_role="owner"), "registry_unreadable")
        self.assertEqual(self.path.read_text(), "{oops")

    def test_concurrent_creates_with_one_key_store_one_experiment(self):
        self.reg.snapshot()
        results = []
        def go():
            results.append(self.ex.create(PID, spec(idempotency_key="race"), actor_role="owner")["duplicate"])
        threads = [threading.Thread(target=go) for _ in range(6)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(sorted(results), [False] + [True] * 5)
        self.assertEqual(len(self.project()["experiments"]), 1)


class Req:
    def __init__(self, role, body):
        self.role, self._body = role, body

    async def json(self):
        return self._body


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = MvpRegistry(Path(self.tmp.name) / "mvp_factory.json", clock=Clock())
        app = fastapi.FastAPI()
        install_mvp_experiment_routes(app, self.reg, lambda r: {"role": r.role, "email": r.role + "@x"})
        self.h = {(r.path, tuple(sorted(r.methods))): r.endpoint for r in app.routes if hasattr(r, "endpoint")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, path, role, body=None, **kw):
        fn = self.h[(path, ("POST",))]
        out = asyncio.run(fn(request=Req(role, body), **kw))
        return (out.status_code, json.loads(out.body)) if hasattr(out, "status_code") else (200, out)

    def test_api_roles_and_read(self):
        base = "/api/mvp-factory/{project_id}/experiments"
        self.assertEqual(self.call(base, "viewer", spec(), project_id=PID)[0], 403)
        self.assertEqual(self.call(base, "member", "nope", project_id=PID), (400, {"detail": "bad_body"}))
        self.assertEqual(self.call(base, "member", spec(), project_id=PID)[0], 200)
        draft = base + "/{exp_id}/branches/{branch_id}/draft"
        self.assertEqual(self.call(draft, "member", dict(COPY), project_id=PID, exp_id="mc-exp-focus-001", branch_id="b")[0], 200)
        approve = base + "/{exp_id}/branches/{branch_id}/approve-preview"
        self.assertEqual(self.call(approve, "member", {"revision": 1}, project_id=PID, exp_id="mc-exp-focus-001", branch_id="b")[0], 403)
        self.assertEqual(self.call(approve, "owner", {"revision": 1}, project_id=PID, exp_id="mc-exp-focus-001", branch_id="b")[0], 200)
        self.assertEqual(self.call(approve, "owner", {"revision": 1}, project_id=PID, exp_id="mc-exp-focus-001", branch_id="c")[0], 404)
        listing = self.h[(base, ("GET",))](project_id=PID)
        exp = listing["experiments"][0]
        self.assertEqual([b["preview_approved"] for b in exp["branches"]], [False, True])
        self.assertEqual(exp["metric_status"], "not_instrumented")
        self.assertIsNone(exp["comparison"]["winner"])
        status, _ = self.call(base + "/{exp_id}/decision", "owner", {"choice": "stop"}, project_id=PID, exp_id="mc-exp-focus-001")
        self.assertEqual(status, 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
