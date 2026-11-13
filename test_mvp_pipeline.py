"""MVP Builder step 2: autonomous hand-off with evidence, owner gates. Offline: fake Gemini, temp stores."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-mvppipe-"))

import mvp_pipeline as mp  # noqa: E402
from mvp_cycle import AgentChat  # noqa: E402
from mvp_factory import MvpError, MvpRegistry  # noqa: E402

RESEARCH = {"summary": "s", "audience": "інді-хакери", "problem": "вразливості", "competitors": ["X — сканер"],
            "variants": [{"id": "A", "name": "Скан репо", "pitch": "p", "features": ["f1"], "differentiator": "d", "risks": ["r"]},
                         {"id": "B", "name": "Чекліст", "pitch": "p", "features": ["f2"], "differentiator": "d", "risks": []},
                         {"id": "C", "name": "Бот", "pitch": "p", "features": ["f3"], "differentiator": "d", "risks": []}],
            "recommended": "A", "why": "w", "assumptions": ["a"]}
SPEC = "## Мета\nx\n## Готово, коли\n- [ ] тест проходить\n"


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.t = [1_800_000_000.0]
        self.reg = MvpRegistry(d / "mvp.json", clock=lambda: self.t[0])
        self.chat = AgentChat(d)
        self.arts = mp.ArtifactStore(d)
        self.answers, self.prompts, self.tickets = [], [], {}

        def gemini(prompt):
            self.prompts.append(prompt)
            return self.answers.pop(0) if self.answers else (None, "no answer")

        def create(title, body, key, pid):
            t = {"id": "R-%04d" % (len(self.tickets) + 1), "title": title, "body": body, "key": key, "execution": {}}
            self.tickets[t["id"]] = t
            return t
        self.p = mp.Pipeline(d, registry=self.reg, chat=self.chat, artifacts=self.arts, gemini=gemini,
                             create_ticket=create, get_ticket=lambda tid: self.tickets.get(tid),
                             ticket_done=lambda t: t.get("done", False), clock=lambda: self.t[0])
        self.pid = self.reg.add_project("", "Security Check", actor_role="owner", brief="Перевірка коду стартапів")["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def stage(self):
        return next(p for p in self.reg.snapshot()["projects"] if p["id"] == self.pid)["stage"]


class HandOffTest(Base):
    def test_autopilot_off_does_nothing(self):
        self.assertEqual(self.p.tick(), [])
        self.assertEqual(self.stage(), "idea")

    def test_battle_phase_runs_on_its_own_and_stops_at_the_owner(self):
        self.p.set_autopilot(self.pid, True)
        self.answers = [(json.dumps(RESEARCH, ensure_ascii=False), ""), (SPEC, "")]
        self.p.tick()
        self.assertEqual(self.stage(), "researching")
        self.assertIn("Перевірка коду стартапів", self.arts.read(self.pid, "brief.md"))
        self.p.tick()
        self.assertEqual(self.stage(), "spec_draft")
        self.assertIn("⭐ рекомендовано", self.arts.read(self.pid, "research.md"))
        self.assertIn("рекомендую A", self.chat.thread(self.pid)["researcher"][-1]["text"])
        self.p.tick()
        self.assertEqual(self.stage(), "spec_review")
        self.assertIn("Скан репо", self.prompts[-1])                       # the recommended variant went into the spec
        self.assertEqual(self.arts.read(self.pid, "spec-v1.md"), SPEC)
        self.p.tick()
        self.assertEqual(self.stage(), "spec_review")                       # never past the owner's gate
        events = [e for e in self.reg.snapshot()["events"] if e["project"] == self.pid and e["kind"] == "advance"]
        self.assertTrue(all(e["evidence"][0].startswith(f"/api/mvp-factory/{self.pid}/artifacts/") for e in events))
        with self.assertRaises(MvpError) as ctx:
            self.reg.record(self.pid, "advance", actor_role="agent", evidence=[events[-1]["evidence"][0]])
        self.assertEqual(ctx.exception.code, "owner_gate")

    def test_bad_agent_output_waits_instead_of_looping(self):
        self.p.set_autopilot(self.pid, True)
        self.p.tick()
        self.answers = [("not json at all", "")]
        self.p.tick()
        self.assertEqual(self.stage(), "researching")
        self.assertIn("не вдалося", self.chat.thread(self.pid)["researcher"][-1]["text"])
        self.answers = [(json.dumps(RESEARCH), "")]
        self.p.tick()
        self.assertEqual(self.stage(), "researching")                       # cooling down
        self.t[0] += mp.RETRY_AFTER + 1
        self.p.tick()
        self.assertEqual(self.stage(), "spec_draft")

    def test_spec_without_done_criteria_is_refused(self):
        self.p.set_autopilot(self.pid, True)
        self.answers = [(json.dumps(RESEARCH), ""), ("## Мета\nбез критеріїв", "")]
        for _ in range(3):
            self.p.tick()
        self.assertEqual(self.stage(), "spec_draft")

    def test_build_hand_off_after_owner_approval(self):
        self.p.set_autopilot(self.pid, True)
        self.answers = [(json.dumps(RESEARCH), ""), (SPEC, "")]
        for _ in range(3):
            self.p.tick()
        self.reg.record(self.pid, "advance", actor_role="owner", evidence=[f"/api/mvp-factory/{self.pid}/artifacts/spec-v1.md"])
        self.p.tick()
        self.assertEqual(list(self.tickets), ["R-0001"])
        t = self.tickets["R-0001"]
        self.assertIn(f"mvps/{self.pid}/", t["body"])
        self.assertIn("Готово, коли", t["body"])
        self.p.tick()
        self.assertEqual((self.stage(), len(self.tickets)), ("build_queued", 1))   # one ticket, waiting for a PR
        t["execution"]["pr_url"] = "https://github.com/o/r/pull/12"
        self.p.tick()
        self.assertEqual(self.stage(), "building")
        self.p.tick()
        self.assertEqual(self.stage(), "building")                          # not merged / not verified yet
        t["done"] = True
        self.p.tick()
        self.assertEqual(self.stage(), "qa_review")
        self.assertIn("pull/12", self.chat.thread(self.pid)["qa"][-1]["text"])

    def test_redo_spec_on_another_variant(self):
        self.p.set_autopilot(self.pid, True)
        self.answers = [(json.dumps(RESEARCH), ""), (SPEC, ""), (SPEC + "\nv2", "")]
        for _ in range(3):
            self.p.tick()
        self.p._update(self.pid, variant="B")
        project = next(p for p in self.reg.snapshot()["projects"] if p["id"] == self.pid)
        self.assertTrue(self.p.run_spec(project, "менше функцій"))
        self.assertIn("Чекліст", self.prompts[-1])
        self.assertIn("менше функцій", self.prompts[-1])
        self.assertEqual(self.p.state(self.pid)["spec_version"], 2)
        self.assertEqual(self.stage(), "spec_review")


class AppRoutesTest(Base):
    def setUp(self):
        super().setUp()
        import app as factory
        self.f = factory
        self.patches = [patch.object(factory, "MVP_REGISTRY", self.reg), patch.object(factory, "MVP_CHAT", self.chat),
                        patch.object(factory, "MVP_ARTIFACTS", self.arts), patch.object(factory, "MVP_PIPELINE", self.p)]
        for x in self.patches:
            x.start()

    def tearDown(self):
        for x in self.patches:
            x.stop()
        super().tearDown()

    def test_owner_flow_through_the_app(self):
        from test_route_auth_fixes import AUTH_ON, call
        from test_worker_token_binding import asgi_post
        self.assertEqual(asgi_post(f"/api/mvp-factory/{self.pid}/autopilot", body=b'{"on": true}')[0], 200)
        self.answers = [(json.dumps(RESEARCH), ""), (SPEC, "")]
        for _ in range(3):
            self.p.tick()
        status, body = call("GET", f"/api/mvp-factory/{self.pid}/artifacts/spec-v1.md")
        self.assertEqual((status, body.decode()), (200, SPEC))
        status, body = call("GET", f"/api/mvp-factory/{self.pid}/cycle")
        self.assertEqual(json.loads(body)["pipeline"]["spec_version"], 1)
        self.assertEqual(asgi_post(f"/api/mvp-factory/{self.pid}/spec/approve", body=b"{}")[0], 200)
        self.assertEqual(self.stage(), "build_queued")
        self.assertEqual(asgi_post(f"/api/mvp-factory/{self.pid}/spec/approve", body=b"{}")[0], 409)
        with patch.object(self.f, "FACTORY_PASSWORD", AUTH_ON):
            viewer = self.f._role_session_token("viewer", "guest")
            self.assertIn(call("POST", f"/api/mvp-factory/{self.pid}/autopilot", cookie=viewer, body=b'{"on":false}')[0], (401, 403))
            self.assertEqual(call("GET", f"/api/mvp-factory/{self.pid}/artifacts/spec-v1.md")[0], 401)
        self.assertEqual(call("GET", f"/api/mvp-factory/{self.pid}/artifacts/..%2Fmvp.json")[0], 404)

    def test_override_closed_ticket_is_not_build_evidence(self):
        self.assertFalse(self.f._mvp_ticket_done({"status": "done", "verification": {"override": {"reason": "x"}}}))
        self.assertFalse(self.f._mvp_ticket_done({"status": "in_progress"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
