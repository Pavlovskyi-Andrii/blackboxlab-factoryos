"""MVP Builder cycle (Battle → Build → Promote → Learn), five agents, agent chat. Offline: fake Gemini, temp stores."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-mvpcycle-"))

import mvp_cycle as mc  # noqa: E402


def project(stage, blocked=None, history=None):
    return {"id": "p1", "title": "Security Check", "stage": stage, "blocked": blocked, "brief": "Мета: перевірка коду",
            "history": history or []}


class CycleViewTest(unittest.TestCase):
    def statuses(self, view):
        return {a["id"]: a["status"] for a in view["agents"]}

    def test_phases_and_agent_status_follow_the_recorded_stage(self):
        v = mc.cycle_view(project("researching"), {}, {})
        self.assertEqual(v["phase"], "battle")
        self.assertEqual(self.statuses(v), {"researcher": "working", "spec": "waiting", "builder": "waiting",
                                            "qa": "waiting", "promoter": "waiting"})
        v = mc.cycle_view(project("building"), {}, {})
        self.assertEqual(v["phase"], "build")
        self.assertEqual(self.statuses(v)["researcher"], "done")
        self.assertEqual(self.statuses(v)["builder"], "working")
        self.assertTrue(next(p for p in v["phases"] if p["id"] == "battle")["done"])
        v = mc.cycle_view(project("validated"), {}, {})
        self.assertEqual((v["phase"], self.statuses(v)["promoter"], self.statuses(v)["qa"]), ("promote", "working", "done"))
        self.assertFalse(next(p for p in v["phases"] if p["id"] == "learn")["current"])

    def test_blocked_and_rejected(self):
        v = mc.cycle_view(project("spec_draft", blocked={"reason": "stop"}), {}, {})
        self.assertEqual(self.statuses(v)["spec"], "blocked")
        v = mc.cycle_view(project("rejected"), {}, {})
        self.assertTrue(all(s == "stopped" for s in self.statuses(v).values()))

    def test_events_links_needs_and_chat(self):
        hist = [{"at": "t", "kind": "advance", "from_stage": "idea", "to_stage": "researching", "note": "audience",
                 "evidence": ["https://github.com/o/r/issues/1"]},
                {"at": "t2", "kind": "advance", "from_stage": "researching", "to_stage": "spec_draft", "note": "spec",
                 "evidence": ["https://github.com/o/r/pull/2"]}]
        v = mc.cycle_view(project("spec_draft", history=hist), {"gemini": True, "github": False},
                          {"builder": [{"author": "owner", "text": "hi"}]})
        r = next(a for a in v["agents"] if a["id"] == "researcher")
        self.assertEqual(r["links"], ["https://github.com/o/r/issues/1", "https://github.com/o/r/pull/2"])
        self.assertEqual(r["needs"], [{"id": "gemini", "label": mc.NEED_LABELS["gemini"], "ok": True}])
        b = next(a for a in v["agents"] if a["id"] == "builder")
        self.assertEqual([n["ok"] for n in b["needs"]], [False, False])
        self.assertEqual(b["chat"][0]["text"], "hi")
        self.assertIn("нічого не запускає", v["note"])


class ChatTest(unittest.TestCase):
    def test_bounded_clean_thread(self):
        with tempfile.TemporaryDirectory() as d:
            c = mc.AgentChat(Path(d))
            c.add("p1", "spec", "owner", "  Додай\x00 критерії  ")
            self.assertEqual(c.thread("p1")["spec"][0]["text"], "Додай критерії")
            for bad in (("nobody", "x"), ("spec", "   ")):
                with self.assertRaises(ValueError):
                    c.add("p1", bad[0], "owner", bad[1])
            for i in range(mc.MAX_THREAD + 5):
                c.add("p1", "qa", "owner", f"m{i}")
            self.assertEqual(len(c.thread("p1")["qa"]), mc.MAX_THREAD)

    def test_prompt_forbids_invented_results(self):
        p = mc.agent_prompt(project("idea"), mc.AGENTS[0], "Хто наша аудиторія?", [{"author": "owner", "text": "раніше"}])
        self.assertIn("Researcher", p)
        self.assertIn("Мета: перевірка коду", p)
        self.assertIn("Не вигадуй результатів", p)


class RouteTest(unittest.TestCase):
    """Through the real app: cycle view, Gemini agent answers, Claude agent goes to the worker queue and back."""

    def setUp(self):
        import app as factory
        from mvp_factory import MvpRegistry
        self.f = factory
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = MvpRegistry(Path(self.tmp.name) / "mvp.json")
        self.reg.add_project("", "Security Check", actor_role="owner", brief="Перевірка коду стартапів")
        self.pid = next(p["id"] for p in self.reg.snapshot()["projects"] if p["title"] == "Security Check")
        self.chat = mc.AgentChat(Path(self.tmp.name))
        self.p = [patch.object(factory, "MVP_REGISTRY", self.reg), patch.object(factory, "MVP_CHAT", self.chat)]
        for x in self.p:
            x.start()

    def tearDown(self):
        for x in self.p:
            x.stop()
        self.tmp.cleanup()

    def post(self, agent, text):
        from test_worker_token_binding import asgi_post
        return asgi_post(f"/api/mvp-factory/{self.pid}/agents/{agent}/message", body=json.dumps({"text": text}).encode())

    def test_cycle_and_gemini_agent(self):
        from test_route_auth_fixes import call
        status, body = call("GET", f"/api/mvp-factory/{self.pid}/cycle")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["phase"], "battle")
        started = []
        with patch.object(self.f, "_gemini_text", return_value=("Аудиторія: інді-хакери.", "")), \
             patch.object(self.f.threading, "Thread", side_effect=lambda target, daemon: started.append(target) or
                          type("T", (), {"start": lambda s: None})()):
            status, _ = self.post("researcher", "Хто наша аудиторія?")
            started[0]()                                     # the background answer, still with the fake Gemini
        self.assertEqual(status, 200)
        thread = self.chat.thread(self.pid)["researcher"]
        self.assertEqual([m["author"] for m in thread], ["owner", "agent"])
        self.assertEqual(thread[1]["text"], "Аудиторія: інді-хакери.")

    def test_claude_agent_goes_to_the_worker_and_back(self):
        created = []

        class Q:
            def create(self_, *a, **kw):
                created.append(kw)
                return {"id": "Q-9"}
        with patch.object(self.f, "OWNER_QUESTIONS", Q()):
            status, _ = self.post("builder", "Почни з форми входу")
        self.assertEqual(status, 200)
        self.assertEqual(created[0]["meta"], {"mvp_project": self.pid, "mvp_agent": "builder"})
        self.assertIn("Передано Claude-воркеру (Q-9)", self.chat.thread(self.pid)["builder"][-1]["text"])
        self.assertTrue(self.f._mvp_route_answer({"id": "Q-9", "answer": "Зробив гілку.", "meta": created[0]["meta"]}))
        self.assertEqual(self.chat.thread(self.pid)["builder"][-1]["text"], "Зробив гілку.")
        self.assertFalse(self.f._mvp_route_answer({"id": "Q-1", "answer": "dm", "meta": {}}))

    def test_bad_requests(self):
        self.assertEqual(self.post("nobody", "x")[0], 404)
        self.assertEqual(self.post("spec", "   ")[0], 400)
        from test_route_auth_fixes import AUTH_ON, call
        with patch.object(self.f, "FACTORY_PASSWORD", AUTH_ON):
            viewer = self.f._role_session_token("viewer", "guest")
            self.assertIn(call("POST", f"/api/mvp-factory/{self.pid}/agents/spec/message", cookie=viewer,
                               body=b'{"text":"x"}')[0], (401, 403))


if __name__ == "__main__":
    unittest.main(verbosity=2)
