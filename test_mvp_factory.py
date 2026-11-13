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
        self.assertEqual(set(ids), {"mycast", "decision-memory", "mybrief-pro", "release-guardian", "faceless-creator"})
        self.assertEqual((ids["faceless-creator"]["issue"], ids["faceless-creator"]["stage"]), (313, "idea"))
        self.assertIn("ЧЕРНЕТКА", ids["faceless-creator"]["brief"])
        self.assertFalse(any(ids["faceless-creator"]["approval"].values()))
        self.assertEqual(ids["mycast"]["stage"], "preview_ready")
        self.assertEqual(ids["decision-memory"]["stage"], "idea")
        for e in snap["events"]:
            self.assertTrue(e["evidence"], e)
        self.assertEqual(ids["mycast"]["recommendation"]["decision"], "owner")
        self.assertTrue(all(p["approval"] == {"deploy": False, "outreach": False, "publish": False} for p in snap["projects"]))
        self.path.write_text(json.dumps({"version": 1, "projects": {}, "events": []}))
        self.assertEqual([p["id"] for p in self.reg.snapshot()["projects"]], ["faceless-creator"])  # only the one-time owner-requested concept migration; do not reseed old pilots

    def test_migrate_existing_registry_once_without_overwriting_owner_data(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        original["projects"].pop("faceless-creator")
        original["events"] = [e for e in original["events"] if e["project"] != "faceless-creator"]
        original["projects"]["mycast"]["brief"] = "Owner's existing project brief"
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertEqual(by_id["mycast"]["brief"], "Owner's existing project brief")
        self.assertEqual(by_id["faceless-creator"]["issue"], 313)
        self.assertEqual(by_id["faceless-creator"]["stage"], "idea")
        self.assertEqual(len([e for e in snap["events"] if e["project"] == "faceless-creator"]), 1)
        self.assertEqual(json.loads(self.path.read_text())["version"], 2)
        self.reg.snapshot()
        self.assertEqual(len([e for e in self.reg.snapshot()["events"] if e["project"] == "faceless-creator"]), 1)

    def test_migration_does_not_duplicate_existing_issue_313(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        concept = original["projects"].pop("faceless-creator")
        concept["id"] = "faceless-existing"
        concept["title"] = "Owner's existing concept title"
        original["projects"]["faceless-existing"] = concept
        original["events"] = [e for e in original["events"] if e["project"] != "faceless-creator"]
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        ids = {p["id"] for p in snap["projects"]}
        self.assertIn("faceless-existing", ids)
        self.assertNotIn("faceless-creator", ids)
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)

    def test_migration_preserves_colliding_project_dictionary_key(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        custom = dict(original["projects"]["faceless-creator"],
                      id="owner-custom", issue=777, title="Owner's custom keyed project",
                      brief="Owner's original brief")
        original["projects"]["faceless-creator"] = custom
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        saved = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(saved["projects"]["faceless-creator"], custom)
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertIn("owner-custom", by_id)
        self.assertIn("faceless-creator-313", by_id)
        self.assertEqual(by_id["faceless-creator-313"]["issue"], 313)
        self.assertIn("ЧЕРНЕТКА", by_id["faceless-creator-313"]["brief"])
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)
        self.reg.snapshot()
        self.assertEqual(self.path.read_text(encoding="utf-8"), json.dumps(saved, ensure_ascii=False, indent=1))

    def test_existing_issue_313_custom_brief_survives_v1_and_v2_reads(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        original["projects"]["faceless-creator"]["brief"] = "Owner's signed-off text — keep verbatim"
        self.path.write_text(json.dumps(original), encoding="utf-8")
        for _ in range(3):
            snap = self.reg.snapshot()
            concept = next(p for p in snap["projects"] if p["issue"] == 313)
            self.assertEqual(concept["brief"], "Owner's signed-off text — keep verbatim")
        self.assertEqual(json.loads(self.path.read_text())["version"], 2)
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)

    def test_v2_registry_key_collision_backfills_missing_concept(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        custom = dict(original["projects"]["faceless-creator"],
                      id="owner-custom", issue=777, title="Existing custom",
                      brief="Keep exactly")
        original["projects"]["faceless-creator"] = custom
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertEqual(original["projects"]["faceless-creator"], custom)
        self.assertIn("faceless-creator-313", by_id)
        self.assertEqual(by_id["owner-custom"]["brief"], "Keep exactly")
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)
        saved = self.path.read_text(encoding="utf-8")
        self.reg.snapshot()
        self.assertEqual(self.path.read_text(encoding="utf-8"), saved)

    def test_fallback_id_collision_uses_next_available_id(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        original["projects"]["faceless-creator"]["id"] = "first-existing"
        original["projects"]["faceless-creator"]["issue"] = 777
        original["projects"]["faceless-creator-313"] = {
            **original["projects"]["faceless-creator"], "id": "second-existing", "issue": 778
        }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertIn("faceless-creator-313-2", by_id)
        self.assertEqual(by_id["faceless-creator-313-2"]["issue"], 313)
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)

    def test_intentional_removal_does_not_recreate_issue_313(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(original["faceless_creator_intake_complete"])
        original["projects"].pop("faceless-creator")
        self.path.write_text(json.dumps(original), encoding="utf-8")
        for _ in range(3):
            snap = self.reg.snapshot()
            self.assertFalse(any(p["issue"] == 313 for p in snap["projects"]))
        self.assertEqual(json.loads(self.path.read_text())["projects"].get("faceless-creator"), None)

    def test_legacy_v2_intake_runs_once_then_respects_removal(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original.pop("faceless_creator_intake_complete")
        original["projects"].pop("faceless-creator")
        self.path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(len([p for p in self.reg.snapshot()["projects"] if p["issue"] == 313]), 1)
        updated = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(updated["faceless_creator_intake_complete"])
        updated["projects"].pop("faceless-creator")
        self.path.write_text(json.dumps(updated), encoding="utf-8")
        self.assertEqual(len([p for p in self.reg.snapshot()["projects"] if p["issue"] == 313]), 0)

    def test_many_fallback_id_collisions_do_not_break_registry(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        original["projects"]["faceless-creator"]["issue"] = 777
        original["projects"]["faceless-creator"]["id"] = "owner-original"
        for n in range(1, 31):
            key = "faceless-creator-313" + (f"-{n}" if n > 1 else "")
            original["projects"][key] = {
                **original["projects"]["faceless-creator"],
                "id": f"owner-{n}", "issue": 800 + n,
            }
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertIn("faceless-creator-313-31", by_id)
        self.assertEqual(by_id["faceless-creator-313-31"]["issue"], 313)
        self.assertEqual(len([p for p in snap["projects"] if p["issue"] == 313]), 1)

    def test_mvp_builder_drawer_renders_escaped_draft_for_fallback_id(self):
        # Source-level UI contract: drawer resolves by project.id, not canonical ID.
        html = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("find(x=>x.id===id)", html)
        self.assertIn("p.brief?'<div class=\\"mvpBrief\\">'+esc(p.brief)", html)
        self.assertIn("encodeURIComponent(p.id)", html)

    def test_existing_issue_313_without_brief_gets_draft_once(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["version"] = 1
        concept = original["projects"].pop("faceless-creator")
        concept["id"] = "faceless-existing"
        concept["title"] = "Owner's concept title"
        concept.pop("brief")
        original["projects"]["faceless-existing"] = concept
        original["events"] = [e for e in original["events"] if e["project"] != "faceless-creator"]
        self.path.write_text(json.dumps(original), encoding="utf-8")
        first = self.reg.snapshot()
        by_id = {p["id"]: p for p in first["projects"]}
        self.assertNotIn("faceless-creator", by_id)
        self.assertIn("ЧЕРНЕТКА", by_id["faceless-existing"]["brief"])
        self.assertEqual(by_id["faceless-existing"]["title"], "Owner's concept title")
        self.assertEqual(len([p for p in first["projects"] if p["issue"] == 313]), 1)
        saved = self.path.read_text(encoding="utf-8")
        self.reg.snapshot()
        self.assertEqual(self.path.read_text(encoding="utf-8"), saved)

    def test_existing_v2_issue_313_missing_brief_is_repaired(self):
        self.reg.snapshot()
        original = json.loads(self.path.read_text(encoding="utf-8"))
        original["projects"]["faceless-creator"].pop("brief")
        self.path.write_text(json.dumps(original), encoding="utf-8")
        snap = self.reg.snapshot()
        by_id = {p["id"]: p for p in snap["projects"]}
        self.assertIn("ЧЕРНЕТКА", by_id["faceless-creator"]["brief"])
        self.assertEqual(json.loads(self.path.read_text())["version"], 2)
        self.assertEqual(len([e for e in snap["events"] if e["project"] == "faceless-creator"]), 1)

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

    def test_new_project_from_a_brief_without_issue(self):
        """Owner 2026-11-11: "New Project" in the dashboard carries the technical brief; a GitHub issue is optional."""
        p = self.reg.add_project("", "Telegram CRM для салону", actor_role="owner",
                                 brief="Мета: запис клієнтів через бота.\nГотово, коли: бот приймає запис і нагадує.")
        self.assertTrue(p["id"].startswith("telegram-crm"))
        self.assertEqual((p["issue"], p["stage"]), (0, "idea"))
        self.assertIn("нагадує", p["brief"])
        again = self.reg.add_project("", "Telegram CRM для салону", actor_role="owner", brief="x")
        self.assertNotEqual(again["id"], p["id"])                                  # unique id, no overwrite
        self.assertEqual(self.code(lambda: self.reg.add_project("", "No brief, no issue", actor_role="owner")), "bad_project")
        snap = {x["id"]: x for x in self.reg.snapshot()["projects"]}
        self.assertEqual(snap[p["id"]]["progress"], 0)

    def test_progress_follows_the_recorded_stage(self):
        from mvp_factory import progress
        self.assertEqual([progress({"stage": s}) for s in ("idea", "building", "owner_review", "validated", "rejected")],
                         [0, 56, 89, 100, 0])

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

            self.assertEqual(len(get(_Req())["projects"]), 5)  # #313 Faceless Creator is registered
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



class OpenQuestionsProjectionTest(unittest.TestCase):
    """#321: read-only projection includes all structured open items and nothing answered."""

    def test_all_unresolved_sources_and_gates(self):
        from open_questions import collect_open_questions
        class StubQuestions:
            def list(self, limit):
                self.limit = limit
                return [
                    {"id": "Q-1", "status": "pending", "task_id": "T-506", "question": "Waiting for Claude?", "created_at": "2026-11-13T08:00:00+00:00"},
                    {"id": "Q-2", "status": "answering", "task_id": "T-502", "question": "In progress", "created_at": "2026-11-13T08:01:00+00:00"},
                    {"id": "Q-3", "status": "answered", "task_id": "T-500", "question": "Already answered", "created_at": "2026-11-13T08:02:00+00:00"},
                    {"id": "Q-4", "status": "failed", "task_id": "T-500", "question": "Needs follow-up", "created_at": "2026-11-13T08:03:00+00:00"},
                ]
        with tempfile.TemporaryDirectory() as d:
            reg = MvpRegistry(Path(d) / "mvp_factory.json")
            reg.record("release-guardian", "block", actor_role="owner", reason="Waiting for owner input")
            reg.record("decision-memory", "advance", actor_role="owner", evidence=[ISSUE])
            stub = StubQuestions()
            result = collect_open_questions(reg, stub)
            items = result["items"]
            ids = {item["id"] for item in items}
            self.assertEqual(ids, {"Q-1", "Q-2", "Q-4", "mvp-block:release-guardian", "mvp-review:mycast"})
            self.assertEqual(result["total"], 5)
            self.assertFalse(result["sources"]["notion"])
            self.assertTrue(result["read_only"])
            self.assertIn("Notion", result["coverage"])
            self.assertEqual(stub.limit, 200)
            self.assertEqual({item["status"] for item in items}, {"pending", "answering", "failed", "blocked", "needs_review"})
            self.assertEqual(next(x for x in items if x["id"] == "mvp-block:release-guardian")["title"], "Waiting for owner input")
            self.assertFalse(any("Already answered" in x["title"] for x in items))
            # Closing a review gate removes it, without requiring a separate questions table.
            reg.record("mycast", "advance", actor_role="owner", evidence=[ISSUE])
            reg.record("mycast", "advance", actor_role="owner", evidence=[ISSUE])
            self.assertNotIn("mvp-review:mycast", {x["id"] for x in collect_open_questions(reg, stub)["items"]})
            # A blocked project that the owner rejects is closed: it must not stay "blocked" on the dashboard forever.
            reg.record("release-guardian", "reject", actor_role="owner", reason="Not pursuing")
            self.assertNotIn("mvp-block:release-guardian", {x["id"] for x in collect_open_questions(reg, stub)["items"]})

    def test_route_owner_only_and_unreadable_store(self):
        from fastapi import FastAPI, HTTPException
        from open_questions import install_open_questions_routes
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mvp_factory.json"
            reg = MvpRegistry(path)
            class StubQuestions:
                def list(self, limit):
                    return []
            role = {"value": "viewer"}
            app = FastAPI()
            install_open_questions_routes(app, reg, StubQuestions(), lambda req: {"role": role["value"]})
            handler = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/factory/open-questions")
            with self.assertRaises(HTTPException) as denied:
                handler(object())
            self.assertEqual(denied.exception.status_code, 403)
            role["value"] = "owner"
            self.assertTrue(handler(object())["read_only"])
            path.write_text("{broken")
            res = handler(object())
            self.assertEqual(res.status_code, 503)
            self.assertEqual(path.read_text(), "{broken")


if __name__ == "__main__":
    unittest.main(verbosity=2)
