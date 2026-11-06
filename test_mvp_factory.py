"""#186 MVP Factory registry: evidence-gated, one-step, owner-gated, idempotent, never dispatches. Offline only."""
import json
import tempfile
import unittest
from pathlib import Path

from mvp_factory import REPO, MvpError, MvpRegistry, recommend

ISSUE = f"{REPO}/issues/187"


class MvpRegistryTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "mvp_factory.json"
        self.t = [1_800_000_000.0]
        self.reg = MvpRegistry(self.path, clock=lambda: self.t[0])

    def tearDown(self):
        self.dir.cleanup()

    def code(self, fn):
        with self.assertRaises(MvpError) as ctx:
            fn()
        return ctx.exception.code

    def test_seed_is_evidence_backed_and_written_once(self):
        snap = self.reg.snapshot()
        ids = {p["id"]: p for p in snap["projects"]}
        self.assertEqual(set(ids), {"mycast", "decision-memory", "mybrief-pro", "release-guardian"})
        self.assertEqual(ids["mycast"]["stage"], "preview_ready")
        self.assertEqual(ids["decision-memory"]["stage"], "idea")
        for e in snap["events"]:
            self.assertTrue(e["evidence"], e)
        self.assertEqual(ids["mycast"]["recommendation"]["decision"], "owner")
        self.assertTrue(all(p["approval"] == {"deploy": False, "outreach": False, "publish": False} for p in snap["projects"]))
        self.path.write_text(json.dumps({"version": 1, "projects": {}, "events": []}))
        self.assertEqual(self.reg.snapshot()["projects"], [])          # existing file is never re-seeded

    def test_damaged_registry_is_refused_not_replaced(self):
        self.path.write_text("{not json")
        self.assertEqual(self.code(self.reg.snapshot), "registry_unreadable")
        self.assertEqual(self.path.read_text(), "{not json")

    def test_advance_needs_evidence_and_moves_one_step(self):
        self.assertEqual(self.code(lambda: self.reg.record("decision-memory", "advance", actor_role="member")), "evidence_required")
        self.assertEqual(self.code(lambda: self.reg.record("decision-memory", "advance", actor_role="member",
                                                           evidence=["https://evil.example/x"])), "bad_evidence")
        out = self.reg.record("decision-memory", "advance", actor_role="member", evidence=[ISSUE], note="research started")
        self.assertEqual((out["event"]["from_stage"], out["event"]["to_stage"]), ("idea", "researching"))
        self.assertEqual(out["project"]["recommendation"]["role"], "Spec Writer")
        self.assertIn("no worker", out["project"]["recommendation"]["reason"])

    def test_owner_gates(self):
        self.reg.record("mycast", "advance", actor_role="member", evidence=["/static/mycast-configurator/index.html"])
        self.assertEqual(self.code(lambda: self.reg.record("mycast", "advance", actor_role="member", evidence=[ISSUE])), "owner_only")
        self.assertEqual(self.code(lambda: self.reg.record("mycast", "reject", actor_role="member")), "owner_only")
        out = self.reg.record("mycast", "advance", actor_role="owner", evidence=[f"{REPO}/issues/261"])
        self.assertEqual(out["project"]["stage"], "validated")
        self.assertEqual(self.code(lambda: self.reg.record("mycast", "advance", actor_role="owner", evidence=[ISSUE])), "project_closed")
        self.reg.record("mycast", "note", actor_role="owner", note="handed to Content Factory")   # notes stay allowed

    def test_block_and_unblock(self):
        self.assertEqual(self.code(lambda: self.reg.record("release-guardian", "block", actor_role="member")), "reason_required")
        self.reg.record("release-guardian", "block", actor_role="member", reason="waiting for D-240")
        snap = {p["id"]: p for p in self.reg.snapshot()["projects"]}
        self.assertEqual(snap["release-guardian"]["recommendation"], {"decision": "blocked", "reason": "waiting for D-240"})
        self.assertEqual(self.code(lambda: self.reg.record("release-guardian", "advance", actor_role="owner", evidence=[ISSUE])), "project_blocked")
        self.reg.record("release-guardian", "unblock", actor_role="member")
        self.assertEqual(self.code(lambda: self.reg.record("release-guardian", "unblock", actor_role="member")), "not_blocked")

    def test_idempotent_writes(self):
        a = self.reg.record("mybrief-pro", "advance", actor_role="member", evidence=[ISSUE], idempotency_key="k1")
        b = self.reg.record("mybrief-pro", "advance", actor_role="member", evidence=[ISSUE], idempotency_key="k1")
        self.assertTrue(b["duplicate"])
        self.assertEqual(a["event"]["id"], b["event"]["id"])
        stage = {p["id"]: p["stage"] for p in self.reg.snapshot()["projects"]}["mybrief-pro"]
        self.assertEqual(stage, "researching")

    def test_add_project_and_bad_input(self):
        self.assertEqual(self.code(lambda: self.reg.add_project("x", "t", 1, actor_role="viewer")), "forbidden")
        self.assertEqual(self.code(lambda: self.reg.add_project("Bad Id", "t", 1, actor_role="owner")), "bad_id")
        self.reg.add_project("ai-hangout", "AI Hangout <b>", 216, actor_role="owner")
        self.assertEqual(self.code(lambda: self.reg.add_project("ai-hangout", "again", 216, actor_role="owner")), "project_exists")
        p = {p["id"]: p for p in self.reg.snapshot()["projects"]}["ai-hangout"]
        self.assertEqual((p["title"], p["stage"]), ("AI Hangout b", "idea"))
        self.assertEqual(self.code(lambda: self.reg.record("nope", "advance", actor_role="owner", evidence=[ISSUE])), "unknown_project")
        self.assertEqual(self.code(lambda: self.reg.record("ai-hangout", "launch", actor_role="owner")), "bad_kind")

    def test_recommend_never_dispatches(self):
        self.assertEqual(recommend({"stage": "build_queued"})["role"], "Claude Builder")
        self.assertEqual(recommend({"stage": "rejected"})["decision"], "hold")


class MvpRoutesTest(unittest.TestCase):
    def test_routes_roles(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from mvp_factory import install_mvp_factory_routes
        with tempfile.TemporaryDirectory() as d:
            role = {"r": "member"}
            app = FastAPI()
            install_mvp_factory_routes(app, MvpRegistry(Path(d) / "m.json"), lambda req: {"role": role["r"], "email": "a@b"})
            c = TestClient(app)
            self.assertEqual(len(c.get("/api/mvp-factory").json()["projects"]), 4)
            r = c.post("/api/mvp-factory/mycast/events", json={"kind": "advance", "evidence": ["/static/mycast-configurator/index.html"]})
            self.assertEqual(r.json()["event"]["to_stage"], "owner_review")
            r = c.post("/api/mvp-factory/mycast/events", json={"kind": "advance", "evidence": [ISSUE]})
            self.assertEqual((r.status_code, r.json()["detail"]), (403, "owner_only"))
            self.assertEqual(c.post("/api/mvp-factory/mycast/events", content="x").status_code, 400)
            role["r"] = "viewer"
            self.assertEqual(c.post("/api/mvp-factory/mycast/events", json={"kind": "note"}).status_code, 403)


if __name__ == "__main__":
    unittest.main(verbosity=2)
