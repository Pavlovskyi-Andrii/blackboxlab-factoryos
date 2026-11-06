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

    def test_retry_same_key_moves_stage_once(self):
        first = self.reg.record("decision-memory", "advance", actor_role="member", actor="a@b", evidence=[ISSUE], idempotency_key="op-1")
        for _ in range(3):  # a network retry of the same operation
            again = self.reg.record("decision-memory", "advance", actor_role="member", actor="a@b", evidence=[ISSUE], idempotency_key="op-1")
            self.assertTrue(again["duplicate"])
            self.assertEqual(again["event"]["id"], first["event"]["id"])
        snap = {p["id"]: p for p in self.reg.snapshot()["projects"]}["decision-memory"]
        self.assertEqual(snap["stage"], "researching")
        self.assertEqual(sum(1 for e in snap["history"] if e["kind"] == "advance"), 1)

    def test_new_key_same_payload_is_a_distinct_event(self):
        a = self.reg.record("mybrief-pro", "note", actor_role="member", actor="a@b", note="call with a lawyer", idempotency_key="op-a")
        b = self.reg.record("mybrief-pro", "note", actor_role="member", actor="a@b", note="call with a lawyer", idempotency_key="op-b")
        self.assertFalse(b["duplicate"])
        self.assertNotEqual(a["event"]["id"], b["event"]["id"])
        c = self.reg.record("mybrief-pro", "advance", actor_role="member", actor="a@b", evidence=[ISSUE], idempotency_key="op-c")
        d = self.reg.record("mybrief-pro", "advance", actor_role="member", actor="a@b", evidence=[ISSUE], idempotency_key="op-d")
        self.assertEqual((c["event"]["to_stage"], d["event"]["to_stage"]), ("researching", "spec_draft"))

    def test_key_reused_for_another_operation_is_refused(self):
        self.reg.record("mybrief-pro", "note", actor_role="member", actor="a@b", note="x", idempotency_key="op-1")
        for other in (dict(project_id="release-guardian", kind="note", actor="a@b", note="x"),      # other project
                      dict(project_id="mybrief-pro", kind="note", actor="c@d", note="x"),           # other actor
                      dict(project_id="mybrief-pro", kind="note", actor="a@b", note="changed"),     # other payload
                      dict(project_id="mybrief-pro", kind="block", actor="a@b", reason="x")):       # other kind
            pid = other.pop("project_id")
            kind = other.pop("kind")
            self.assertEqual(self.code(lambda: self.reg.record(pid, kind, actor_role="member", idempotency_key="op-1", **other)),
                             "idempotency_conflict")
        hist = {p["id"]: p["history"] for p in self.reg.snapshot()["projects"]}
        self.assertEqual(len(hist["mybrief-pro"]), 2)        # seed note + the one real note; no refused write landed
        self.assertEqual(len(hist["release-guardian"]), 1)   # seed note only
        self.assertIsNone({p["id"]: p for p in self.reg.snapshot()["projects"]}["mybrief-pro"]["blocked"])

    def test_malicious_evidence_is_refused(self):
        for bad in ("javascript:alert(1)", "http://github.com/a/b/issues/1", "https://github.com.evil.com/a/b/issues/1",
                    "https://github.com/a/b/wiki/x", "/static/../app.py", "/static//etc", "https://evil.example/x",
                    'https://github.com/a/b/issues/1"><script>'):
            self.assertEqual(self.code(lambda: self.reg.record("decision-memory", "advance", actor_role="owner", evidence=[bad])),
                             "bad_evidence", bad)
        self.assertEqual({p["id"]: p for p in self.reg.snapshot()["projects"]}["decision-memory"]["stage"], "idea")

    def test_every_event_says_evidence_is_shape_checked_only(self):
        self.reg.record("decision-memory", "advance", actor_role="member", evidence=[ISSUE])
        snap = self.reg.snapshot()
        self.assertEqual(snap["evidence_check"], "link_shape_only")
        self.assertTrue(all(e["evidence_check"] == "link_shape_only" for e in snap["events"]))
        self.assertNotIn("VERIFIED", json.dumps(snap))

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


class _Req:
    """Minimal stand-in for a Starlette request: the handlers only read the identity and the JSON body."""

    def __init__(self, body=None, raw=False):
        self.body, self.raw = body, raw

    async def json(self):
        if self.raw:
            raise ValueError("not json")
        return self.body


class MvpRoutesTest(unittest.TestCase):
    """Calls the installed handlers directly (CI has no HTTP test client)."""

    def test_routes_roles(self):
        import asyncio
        from fastapi import FastAPI
        from mvp_factory import install_mvp_factory_routes
        with tempfile.TemporaryDirectory() as d:
            role = {"r": "member"}
            app = FastAPI()
            install_mvp_factory_routes(app, MvpRegistry(Path(d) / "m.json"), lambda req: {"role": role["r"], "email": "a@b"})
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
            get, post = h[("GET", "/api/mvp-factory")], h[("POST", "/api/mvp-factory/{project_id}/events")]

            def call(body=None, raw=False):
                out = asyncio.run(post("mycast", _Req(body, raw)))
                return (out.status_code, json.loads(out.body)) if hasattr(out, "status_code") else (200, out)

            self.assertEqual(len(get(_Req())["projects"]), 4)
            status, out = call({"kind": "advance", "evidence": ["/static/mycast-configurator/index.html"]})
            self.assertEqual((status, out["event"]["to_stage"]), (200, "owner_review"))
            self.assertEqual(call({"kind": "advance", "evidence": [ISSUE]}), (403, {"detail": "owner_only"}))
            self.assertEqual(call(raw=True)[0], 400)
            role["r"] = "viewer"
            self.assertEqual(call({"kind": "note"}), (403, {"detail": "forbidden"}))
            (Path(d) / "m.json").write_text("{broken")
            out = get(_Req())
            self.assertEqual((out.status_code, json.loads(out.body)), (503, {"detail": "registry_unreadable"}))
            self.assertEqual((Path(d) / "m.json").read_text(), "{broken")


if __name__ == "__main__":
    unittest.main(verbosity=2)
