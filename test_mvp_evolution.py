"""T-630 Product Evolution (#270): consent, synthetic labelling, themes, owner gates, one Relay ticket per hand-off,
truthful hand-off status, V2 release and retest. Offline; handlers are called directly (CI has no httpx)."""
import asyncio
import json
import re
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI

import mvp_evolution as ev
from mvp_factory import MvpRegistry, REPO

ROOT = Path(__file__).resolve().parent
PID = "mybrief-pro"
PR = f"{REPO}/pull/999"


def fb(i, **kw):
    body = {"consent": True, "consent_ref": "interview notes 2026-11-16, verbal consent", "participant": f"person-{i}",
            "source": "interview", "tried": "yes", "job": f"prepare my weekly brief number {i}",
            "failed": "could not export it to PDF for my manager", "themes": ["pdf-export"], "importance": 4}
    body.update(kw)
    return body


class Relay:
    """Stand-in for RelayStore.create/get: idempotent by source key, like the real one."""

    def __init__(self):
        self.tickets, self.calls, self.lock = {}, 0, threading.Lock()

    def create(self, title, body, key, lane):
        with self.lock:
            self.calls += 1
            for t in self.tickets.values():
                if t["source_key"] == key:
                    return t
            tid = f"R-{len(self.tickets) + 1:04d}"
            self.tickets[tid] = {"id": tid, "title": title, "body": body, "source_key": key, "status": "inbox",
                                 "execution": {"state": "queued", "owner": lane, "attempts": 0}}
            return self.tickets[tid]


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "evo.json"
        self.t = [1_800_000_000.0]
        self.store = ev.EvolutionStore(self.path, clock=lambda: self.t[0],
                                       project_exists=lambda pid: pid in (PID, "decision-memory"))
        self.relay = Relay()

    def tearDown(self):
        self.tmp.cleanup()

    def code(self, fn):
        with self.assertRaises(ev.EvolutionError) as ctx:
            fn()
        return ctx.exception.code

    def add(self, i, role="owner", **kw):
        return self.store.add_feedback(PID, fb(i, **kw), actor_role=role)["feedback"]

    def proposal(self, ids, role="agent", **kw):
        body = {"title": "PDF export", "problem": "people cannot hand the brief on", "change": "add a PDF button",
                "acceptance_test": "a brief exports to a PDF with all links", "theme": "pdf-export", "feedback_ids": ids}
        body.update(kw)
        return self.store.propose(PID, body, actor_role=role)["proposal"]

    def decide(self, prop, action, role="owner", **kw):
        return self.store.decide(PID, prop, dict(action=action, **kw), actor_role=role, create_ticket=self.relay.create)

    # --- consent and privacy ----------------------------------------------------------------------------------------
    def test_consent_and_participant_rules(self):
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(1, consent="yes"), actor_role="owner")), "consent_required")
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(1, consent_ref=""), actor_role="owner")), "consent_ref_required")
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(1, participant=""), actor_role="owner")), "participant_required")
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(1), actor_role="viewer")), "forbidden")
        rec = self.add(1, participant="Jane Roe jane@example.com", job="call me at +44 20 7946 0958 or jane@example.com please")
        self.assertNotIn("@", rec["answers"]["job"])
        self.assertIn("[phone]", rec["answers"]["job"])
        raw = self.path.read_text()
        self.assertNotIn("Jane", raw)
        self.assertNotIn("jane@example.com", raw)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(rec["consent"], {"given": True, "ref": "interview notes 2026-11-16, verbal consent"})

    def test_unknown_project_and_damaged_store(self):
        self.assertEqual(self.code(lambda: self.store.add_feedback("nope-x", fb(1), actor_role="owner")), "unknown_project")
        self.assertEqual(self.code(lambda: self.store.view("nope-x")), "unknown_project")
        self.path.write_text("{broken")
        self.assertEqual(self.code(lambda: self.store.view(PID)), "store_unreadable")

    # --- cohort, substantive, synthetic ------------------------------------------------------------------------------
    def test_cohort_counts_unique_real_substantive_only(self):
        for i in range(9):
            self.add(i)
        self.add(0)  # same person again: one participant
        self.add(20, job="", failed="", helped="", themes=[])  # stars only: not substantive
        self.store.add_feedback(PID, fb(30, source="synthetic", synthetic=True), actor_role="agent")
        view = self.store.view(PID)
        self.assertEqual(view["cohort"]["unique_substantive_real"], 9)
        self.assertFalse(view["cohort"]["first_target_met"])
        self.assertEqual((view["cohort"]["feedback_real"], view["cohort"]["feedback_synthetic"]), (11, 1))
        self.add(9)
        self.assertTrue(self.store.view(PID)["cohort"]["first_target_met"])
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(40, synthetic=True), actor_role="owner")),
                         "synthetic_must_be_marked")
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(40, source="synthetic"), actor_role="owner")),
                         "synthetic_must_be_marked")

    def test_funnel_unknown_until_recorded_with_source(self):
        view = self.store.view(PID)
        self.assertEqual(view["funnel"]["v1"], {"invited": None, "activated": None, "used": None, "returned": None,
                                                "abandoned": None, "feedback_received": 0})
        self.assertEqual(self.code(lambda: self.store.set_funnel(PID, {"step": "invited", "count": 5}, actor_role="owner")), "source_required")
        self.assertEqual(self.code(lambda: self.store.set_funnel(PID, {"step": "x", "count": 5, "source": "s"}, actor_role="owner")), "bad_step")
        self.assertEqual(self.code(lambda: self.store.set_funnel(PID, {"step": "invited", "count": 5, "source": "s"}, actor_role="agent")), "forbidden")
        self.store.set_funnel(PID, {"step": "invited", "count": 5, "source": "owner's sent list"}, actor_role="owner")
        self.assertEqual(self.store.view(PID)["funnel"]["v1"]["invited"]["count"], 5)
        self.assertIsNone(self.store.view(PID)["funnel"]["v1"]["used"])

    # --- synthesis -----------------------------------------------------------------------------------------------------
    def test_themes_have_confidence_and_contrary_evidence(self):
        self.add(1)
        self.add(2)
        self.assertEqual(self.store.view(PID)["themes"]["v1"][0]["confidence"], "insufficient")
        self.add(3)
        self.add(4, themes=["mobile"], contra=["pdf-export"])
        th = {t["theme"]: t for t in self.store.view(PID)["themes"]["v1"]}
        self.assertEqual((th["pdf-export"]["unique_support"], th["pdf-export"]["unique_contra"]), (3, 1))
        self.assertEqual(th["pdf-export"]["confidence"], "low")
        self.assertEqual(th["pdf-export"]["sample_size"], 4)
        self.assertEqual(self.code(lambda: self.add(5, themes=["a-b"], contra=["a-b"])), "theme_and_contra")
        self.assertEqual(self.code(lambda: self.add(5, themes=["Bad Tag!"])), "bad_theme")
        self.assertEqual(ev.confidence(10, 0), "high")
        self.assertEqual(ev.confidence(10, 4), "medium")

    # --- proposals and owner gates ---------------------------------------------------------------------------------
    def test_owner_gates_and_one_ticket_per_handoff(self):
        ids = [self.add(i)["id"] for i in range(3)]
        self.assertEqual(self.code(lambda: self.proposal([])), "feedback_required")
        self.assertEqual(self.code(lambda: self.proposal(["fb-9999"])), "unknown_feedback")
        self.assertEqual(self.code(lambda: self.proposal(ids, acceptance_test="")), "proposal_incomplete")
        p = self.proposal(ids)  # an agent may propose
        self.assertEqual((p["state"], p["from_version"], p["target_version"]), ("proposed", "v1", "v2"))
        self.assertEqual(self.code(lambda: self.decide(p["id"], "approve", role="agent")), "owner_only")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "approve", role="member")), "owner_only")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "handoff")), "bad_transition")  # not approved yet
        self.decide(p["id"], "approve")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "handoff", role="agent")), "forbidden")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "handoff", lane="root")), "bad_lane")
        results = []
        threads = [threading.Thread(target=lambda: results.append(self._try_handoff(p["id"]))) for _ in range(6)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(self.relay.tickets), 1)
        self.assertEqual(self.relay.calls, 1)
        self.assertEqual(sum(1 for r in results if r == "ok"), 1)
        ticket = next(iter(self.relay.tickets.values()))
        self.assertEqual(ticket["source_key"], f"mvp-evolution:{PID}:{p['id']}")
        self.assertIn("Acceptance test: a brief exports to a PDF with all links", ticket["body"])
        self.assertIn("no publishing", ticket["body"])
        self.assertNotIn("person-", ticket["body"])

    def _try_handoff(self, pid):
        try:
            self.decide(pid, "handoff", lane="claude")
            return "ok"
        except ev.EvolutionError as exc:
            return exc.code

    def test_idempotency_replay_and_conflict(self):
        body = fb(1, idempotency_key="k-1")
        a = self.store.add_feedback(PID, dict(body), actor_role="owner")
        b = self.store.add_feedback(PID, dict(body), actor_role="owner")
        self.assertEqual(a["feedback"]["id"], b["feedback"]["id"])
        self.assertTrue(b["duplicate"])
        self.assertEqual(len(self.store.view(PID)["feedback"]), 1)
        self.assertEqual(self.code(lambda: self.store.add_feedback(PID, fb(2, idempotency_key="k-1"), actor_role="owner")),
                         "idempotency_conflict")

    def test_synthetic_never_mixes_or_reaches_relay(self):
        real = self.add(1)["id"]
        fake = self.store.add_feedback(PID, fb(2, source="synthetic", synthetic=True), actor_role="agent")["feedback"]["id"]
        self.assertEqual(self.code(lambda: self.proposal([real, fake])), "synthetic_mix")
        p = self.proposal([fake])
        self.assertTrue(p["synthetic"])
        self.decide(p["id"], "approve")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "handoff")), "synthetic_not_handed_off")
        self.assertEqual(self.relay.calls, 0)

    # --- hand-off truth, ship, release, retest --------------------------------------------------------------------
    def test_handoff_status_is_read_from_relay_facts(self):
        prop = {"id": "pr-001", "project": PID, "target_version": "v2", "feedback_ids": ["fb-0001"], "acceptance_test": "t"}
        self.assertEqual(ev.handoff_status(prop, None, False)["verification"], "UNKNOWN")
        q = {"status": "inbox", "execution": {"state": "queued", "owner": "claude"}}
        self.assertEqual(ev.handoff_status(prop, q, False)["state"], "queued")
        c = {"status": "in_progress", "execution": {"state": "claimed", "run_id": "run-1"}}
        self.assertEqual((ev.handoff_status(prop, c, False)["state"], ev.handoff_status(prop, c, False)["verification"]), ("claimed", "UNKNOWN"))
        done = {"status": "done", "execution": {"state": "done", "run_id": "run-1"}}
        self.assertEqual(ev.handoff_status(prop, done, False)["verification"], "UNVERIFIED")
        self.assertEqual(ev.handoff_status(prop, done, True)["verification"], "VERIFIED")
        no_run = {"status": "done", "execution": {"state": "done"}}
        self.assertEqual(ev.handoff_status(prop, no_run, True)["verification"], "UNVERIFIED")
        self.assertEqual(ev.handoff_status(prop, {"status": "need_you", "execution": {}}, False)["state"], "needs_owner")
        self.assertEqual(ev.handoff_status(prop, {"status": "inbox", "execution": {"state": "stale"}}, False)["verification"], "BLOCKED")
        env = ev.handoff_status(prop, c, False)
        for field in ("project_id", "version", "task_id", "run_id", "producer_role", "consumer_role", "input_artifact_refs",
                      "acceptance_criteria", "state", "attempts"):
            self.assertIn(field, env)

    def test_full_real_loop_v1_to_v2_with_retest(self):
        reg = MvpRegistry(Path(self.tmp.name) / "mvp.json", clock=lambda: self.t[0])
        stage_before = {p["id"]: p["stage"] for p in reg.snapshot()["projects"]}
        ids = [self.add(i)["id"] for i in range(3)]
        p = self.proposal(ids, issue=270)
        self.decide(p["id"], "approve")
        self.assertEqual(self.code(lambda: self.store.release(PID, {"evidence": [PR]}, actor_role="owner")), "nothing_shipped")
        self.decide(p["id"], "handoff", lane="chatgpt")
        tid = next(iter(self.relay.tickets))
        view = self.store.view(PID, ticket_lookup=self.relay.tickets.get, ticket_verified=lambda t: True)
        self.assertEqual(view["proposals"][0]["handoff"]["verification"], "UNKNOWN")  # queued, not verified
        self.assertEqual(view["proposals"][0]["handoff"]["lane"], "chatgpt")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "ship", evidence=["https://example.com/pr/1"])), "ship_evidence_required")
        self.assertEqual(self.code(lambda: self.decide(p["id"], "ship", role="agent", evidence=[PR])), "forbidden")
        self.assertEqual(self.code(lambda: self.add(1, retest_of=p["id"], solved="yes")), "retest_needs_shipped_version")
        self.decide(p["id"], "ship", role="member", evidence=[PR])
        self.relay.tickets[tid].update(status="done", execution={"state": "done", "run_id": "run-abc", "owner": "chatgpt"})
        self.assertEqual(self.code(lambda: self.store.release(PID, {"evidence": [PR]}, actor_role="member")), "owner_only")
        self.assertEqual(self.code(lambda: self.store.release(PID, {"evidence": []}, actor_role="owner")), "evidence_required")
        r1 = self.store.release(PID, {"evidence": [PR], "idempotency_key": "rel-1"}, actor_role="owner")
        r2 = self.store.release(PID, {"evidence": [PR], "idempotency_key": "rel-1"}, actor_role="owner")
        self.assertEqual((r1["version"], r2["version"], r2["duplicate"]), ("v2", "v2", True))
        self.assertEqual(self.code(lambda: self.store.release(PID, {"evidence": [PR]}, actor_role="owner")), "nothing_shipped")
        self.add(1, retest_of=p["id"], solved="yes")
        self.add(2, retest_of=p["id"], solved="partly")
        self.add(77, retest_of=p["id"], solved="no")
        view = self.store.view(PID, ticket_lookup=self.relay.tickets.get, ticket_verified=lambda t: True)
        prop = view["proposals"][0]
        self.assertEqual(view["current_version"], "v2")
        self.assertEqual(prop["handoff"]["verification"], "VERIFIED")
        self.assertEqual(prop["handoff"]["run_id"], "run-abc")
        self.assertEqual(prop["retest"], {"responses": 3, "original_participants": 2,
                                          "solved": {"yes": 1, "partly": 1, "no": 1, "unknown": 0}})
        self.assertEqual(view["themes"]["v2"], [])  # retests are not new discovery themes
        self.assertEqual({p["id"]: p["stage"] for p in reg.snapshot()["projects"]}, stage_before)  # registry untouched

    def test_privacy_delete_is_owner_only_and_ids_never_reused(self):
        a = self.add(1)["id"]
        self.assertEqual(self.code(lambda: self.store.delete_feedback(PID, a, actor_role="member")), "owner_only")
        self.store.delete_feedback(PID, a, actor_role="owner")
        self.assertEqual(self.code(lambda: self.store.delete_feedback(PID, a, actor_role="owner")), "not_found")
        b = self.add(2)["id"]
        self.assertNotEqual(a, b)
        self.assertNotIn("person-1", self.path.read_text())

    def test_import_mybrief_consented_only_idempotent(self):
        entries = [{"id": "fb-aa", "at": "2026-11-15T10:00:00+00:00", "rating": 4, "would_read_weekly": True,
                    "comment": "mail me at a@b.co", "consent": True},
                   {"id": "fb-bb", "rating": 2, "consent": False}]
        self.assertEqual(self.code(lambda: self.store.import_mybrief("decision-memory", entries, actor_role="owner")), "import_not_for_project")
        self.assertEqual(self.code(lambda: self.store.import_mybrief(PID, entries, actor_role="agent")), "forbidden")
        self.assertEqual(self.store.import_mybrief(PID, entries, actor_role="owner")["imported"], 1)
        self.assertEqual(self.store.import_mybrief(PID, entries, actor_role="owner")["imported"], 0)
        rec = self.store.view(PID)["feedback"][0]
        self.assertEqual((rec["source"], rec["substantive"], rec["consent"]["ref"]), ("mybrief_import", False, "mybrief:fb-aa"))
        self.assertNotIn("a@b.co", json.dumps(rec))


class DemoTest(unittest.TestCase):
    def test_synthetic_loop_is_deterministic_and_labelled(self):
        a, b = ev.synthetic_demo(), ev.synthetic_demo()
        self.assertEqual(a, b)
        self.assertTrue(a["synthetic"])
        self.assertIn("SYNTHETIC", a["note"])
        self.assertEqual(a["current_version"], "v2")
        self.assertEqual((a["cohort"]["unique_substantive_real"], a["cohort"]["feedback_real"]), (0, 0))
        self.assertTrue(all(r["synthetic"] for r in a["feedback"]))
        self.assertEqual(a["themes"]["v1"], [])  # no real themes are invented
        self.assertEqual(a["synthetic_themes"]["v1"][0]["theme"], "pdf-export")
        prop = a["proposals"][0]
        self.assertEqual((prop["state"], prop["handoff"]["verification"]), ("shipped", "SIMULATED"))
        self.assertEqual(prop["shipped_evidence"], ["SIMULATED — no real PR"])
        self.assertNotIn("github.com", json.dumps(a["versions"]))
        self.assertEqual(prop["retest"]["solved"]["yes"], 2)


class Req:
    def __init__(self, body=None):
        self.body = body

    async def json(self):
        return self.body


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.who = {}
        self.relay = Relay()
        app = FastAPI()
        store = ev.EvolutionStore(Path(self.tmp.name) / "evo.json", project_exists=lambda pid: pid == PID)
        ev.install_mvp_evolution_routes(app, store, lambda request: dict(self.who), create_ticket=self.relay.create,
                                        ticket_lookup=self.relay.tickets.get, mybrief_entries=lambda: [])
        self.routes = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if r.path.startswith("/api/mvp-evolution")}

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, method, path, *args, body=None):
        out = asyncio.run(self.routes[(method, path)](*args, request=Req(body)))
        if hasattr(out, "status_code"):
            return out.status_code, json.loads(out.body)
        return 200, out

    def test_auth_and_owner_gates_through_handlers(self):
        self.assertEqual(len(self.routes), 9)
        for who, status in (({}, 401), ({"role": "viewer"}, 403)):
            self.who = who
            self.assertEqual(self.call("GET", "/api/mvp-evolution/{project_id}", PID)[0], status)
            self.assertEqual(self.call("GET", "/api/mvp-evolution-demo")[0], status)
            self.assertEqual(self.call("POST", "/api/mvp-evolution/{project_id}/feedback", PID, body=fb(1))[0], status)
        self.who = {"role": "member", "email": "m@x"}
        self.assertEqual(self.call("POST", "/api/mvp-evolution/{project_id}/feedback", PID, body=fb(1))[0], 200)
        self.assertEqual(self.call("POST", "/api/mvp-evolution/{project_id}/feedback", PID, body=[1])[0], 400)
        fid = self.call("GET", "/api/mvp-evolution/{project_id}", PID)[1]["feedback"][0]["id"]
        st, prop = self.call("POST", "/api/mvp-evolution/{project_id}/proposals", PID,
                             body={"title": "t", "problem": "p", "change": "c", "acceptance_test": "a", "feedback_ids": [fid]})
        self.assertEqual(st, 200)
        pid = prop["proposal"]["id"]
        path = "/api/mvp-evolution/{project_id}/proposals/{proposal_id}/decision"
        self.assertEqual(self.call("POST", path, PID, pid, body={"action": "approve"}), (403, {"detail": "owner_only"}))
        self.assertEqual(self.call("POST", "/api/mvp-evolution/{project_id}/feedback/{feedback_id}/delete", PID, fid)[0], 403)
        self.who = {"role": "owner", "email": "o@x"}
        self.assertEqual(self.call("POST", path, PID, pid, body={"action": "approve"})[0], 200)
        self.assertEqual(self.call("POST", path, PID, pid, body={"action": "handoff", "lane": "claude"})[0], 200)
        self.assertEqual(len(self.relay.tickets), 1)
        self.assertEqual(self.call("GET", "/api/mvp-evolution/{project_id}", "other-x")[0], 404)
        self.assertTrue(self.call("GET", "/api/mvp-evolution-demo")[1]["synthetic"])
        self.assertEqual(self.call("POST", "/api/mvp-evolution/{project_id}/import-mybrief", PID)[1]["imported"], 0)


class PageAndWiringTest(unittest.TestCase):
    def test_page_calls_only_own_api_and_has_three_languages(self):
        html = (ROOT / "static/mvp-factory/evolution.html").read_text(encoding="utf-8")
        script = html.rsplit("<script>", 1)[1].split("</script>", 1)[0]
        self.assertEqual(set(re.findall(r"fetch\(", script)), {"fetch("})
        self.assertEqual(set(re.findall(r"'(/api/[a-z-]+)", script)), {"/api/mvp-factory", "/api/mvp-evolution-demo", "/api/mvp-evolution"})
        self.assertIn('name="robots" content="noindex"', html)
        self.assertIn("prefers-reduced-motion", html)
        blocks = {lang: set(re.findall(r"(\w+):'", re.search(lang + r":\{(.*?)\}(,\n uk:|,\n ru:|\n\};)", script, re.S).group(1)))
                  for lang in ("en", "uk", "ru")}
        self.assertEqual(blocks["en"], blocks["uk"])
        self.assertEqual(blocks["en"], blocks["ru"])
        index = (ROOT / "static/mvp-factory/index.html").read_text(encoding="utf-8")
        self.assertIn("/static/mvp-factory/evolution.html?project=", index)

    def test_app_wiring_uses_existing_relay_and_registry(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mvp_evolution_routes(", app)
        self.assertIn('"channel": "mvp-evolution"', app)
        self.assertIn("ticket_verified=_mvp_ticket_done", app)
        self.assertIn("project_exists=lambda pid: _mvp_project(pid) is not None", app)


if __name__ == "__main__":
    unittest.main(verbosity=1)
