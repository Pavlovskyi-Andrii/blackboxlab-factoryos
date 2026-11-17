"""T-634 MyCast improve-quiz + analyst (#270): consent, one answer per person, caps, adaptive question, threshold,
one Relay ticket by the standing rule, kill switch, gifts/mail held behind flags, privacy delete. Offline; handlers are
called directly (CI has no httpx)."""
import asyncio
import json
import os
import re
import tempfile
import threading
import unittest
from pathlib import Path

from fastapi import FastAPI

import mvp_quiz as mq
from mvp_evolution import EvolutionError, EvolutionStore

ROOT = Path(__file__).resolve().parent
V = mq.QUIZZES["mycast"]["version"]
FLAGS = ("FACTORY_QUIZ_REWARDS", "FACTORY_QUIZ_MAIL", "FACTORY_QUIZ_AUTO_V2", "FACTORY_QUIZ_MIN_PEOPLE", "FACTORY_QUIZ_MIN_SHARE")


def body(**kw):
    b = {"version": V, "consent": True, "answers": {"q_use": "daily", "q_length": "same", "q_add": ["transcript"],
                                                    "q_fix": "none", "q_channel": "web"}}
    b.update(kw)
    return b


class Relay:
    def __init__(self):
        self.tickets, self.lock = {}, threading.Lock()

    def create(self, title, body, key, lane):
        with self.lock:
            for t in self.tickets.values():
                if t["source_key"] == key:
                    return t
            tid = f"R-{len(self.tickets) + 1:04d}"
            self.tickets[tid] = {"id": tid, "title": title, "body": body, "source_key": key, "lane": lane}
            return self.tickets[tid]


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {k: os.environ.pop(k, None) for k in FLAGS}
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        self.t = [1_800_000_000.0]
        self.evo = EvolutionStore(d / "evo.json", clock=lambda: self.t[0], project_exists=lambda pid: pid == "mycast")
        self.relay = Relay()
        self.grants = []
        self.svc = mq.QuizService(d / "quiz.json", self.evo, clock=lambda: self.t[0], create_ticket=self.relay.create,
                                  grant_days=lambda slug, days, key: self.grants.append((slug, days, key)) or True)

    def tearDown(self):
        self.tmp.cleanup()
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def code(self, fn):
        with self.assertRaises(mq.QuizError) as ctx:
            fn()
        return ctx.exception.code

    def answer(self, i, client=None, **kw):
        return self.svc.submit("mycast", body(**kw), client=client or f"10.0.0.{i}", listener=f"lst{i:05d}")


class QuizTest(Base):
    def test_quiz_definition_and_flags_off_by_default(self):
        q = self.svc.quiz("mycast")
        self.assertEqual((q["version"], q["rewards_enabled"], q["reward_days"], q["validate"]), (V, False, 0, None))
        for qq in q["questions"]:
            self.assertEqual(set(qq["text"]), {"uk", "ru", "en"})
            for o in qq["options"]:
                self.assertEqual(set(o["text"]), {"uk", "ru", "en"})
                self.assertTrue(not o["theme"] or o["theme"] in mq.THEMES)
                self.assertTrue(all(c in mq.THEMES for c in o["contra"]))
        self.assertEqual(self.code(lambda: self.svc.quiz("nope")), "unknown_quiz")

    def test_validation(self):
        sub = lambda **kw: self.svc.submit("mycast", body(**kw), client="c", listener="")
        self.assertEqual(self.code(lambda: sub(consent="yes")), "consent_required")
        self.assertEqual(self.code(lambda: sub(version="old")), "quiz_changed")
        self.assertEqual(self.code(lambda: sub(answers={"q_use": "daily", "q_fix": "none"})), "too_few_answers")
        self.assertEqual(self.code(lambda: sub(answers={"q_use": "x", "q_fix": "none", "q_channel": "web"})), "bad_answer")
        self.assertEqual(self.code(lambda: sub(answers={"q_use": "daily", "q_fix": "none", "q_add": ["voices", "ask", "offline"]})), "bad_answer")
        self.assertEqual(self.code(lambda: sub(answers={"q_use": ["daily", "weekly"], "q_fix": "none", "q_channel": "web"})), "bad_answer")
        self.assertEqual(self.code(lambda: sub(email="a@b.co")), "contact_consent_required")
        self.assertEqual(self.code(lambda: sub(email="nope", contact_consent=True)), "bad_email")

    def test_answer_becomes_consented_feedback(self):
        out = self.answer(1, free_text="call +44 20 7946 0958 please", answers={"q_use": "daily", "q_length": "short",
                                                                                 "q_add": ["transcript", "voices"], "q_fix": "voice", "q_channel": "telegram"})
        self.assertTrue(out["counted"])
        rec = self.evo.view("mycast")["feedback"][0]
        self.assertEqual(rec["source"], "in_product")
        self.assertTrue(rec["consent"]["ref"].startswith(f"mycast-quiz:{V}:qz-"))
        self.assertEqual(rec["themes"], ["shorter-episodes", "text-transcript", "voice-choice", "better-voices"])
        self.assertEqual(rec["contra"], ["email-delivery", "podcast-app-feed"])
        self.assertTrue(rec["substantive"])
        self.assertNotIn("7946", json.dumps(rec))
        raw = (Path(self.tmp.name) / "quiz.json").read_text() + (Path(self.tmp.name) / "evo.json").read_text()
        self.assertNotIn("10.0.0.1", raw)
        self.assertNotIn("lst00001", (Path(self.tmp.name) / "evo.json").read_text())

    def test_people_who_never_used_it_do_not_shape_themes(self):
        out = self.answer(1, answers={"q_use": "not_yet", "q_length": "short", "q_add": ["transcript"]})
        self.assertFalse(out["counted"])
        rec = self.evo.view("mycast")["feedback"][0]
        self.assertEqual((rec["themes"], rec["contra"], rec["answers"]["tried"]), ([], [], "no"))

    def test_one_answer_per_person_and_caps(self):
        self.answer(1)
        self.assertEqual(self.code(lambda: self.answer(1, client="other")), "already_answered")
        self.svc.submit("mycast", body(), client="anon-1", listener="")
        self.assertEqual(self.code(lambda: self.svc.submit("mycast", body(), client="anon-1", listener="")), "already_answered")
        for i in range(2, 2 + mq.PER_CLIENT_DAILY):
            self.answer(i, client="shared")
        self.assertEqual(self.code(lambda: self.answer(9, client="shared")), "daily_limit")
        self.t[0] += 86400
        self.answer(9, client="shared")

    # --- analyst ---------------------------------------------------------------------------------------------------
    def test_threshold_creates_one_proposal_and_one_ticket(self):
        for i in range(9):
            self.assertEqual(self.answer(i)["analyst"], [])
        out = self.answer(9)
        self.assertEqual(len(out["analyst"]), 1)
        act = out["analyst"][0]
        self.assertEqual((act["theme"], act["handoff"], act["people"], act["min_people"]), ("text-transcript", "handed_off", 10, 10))
        self.assertEqual(len(self.relay.tickets), 1)
        ticket = next(iter(self.relay.tickets.values()))
        self.assertIn("quiz-threshold", ticket["body"])
        self.assertIn("Acceptance test: Every ready episode", ticket["body"])
        prop = self.evo.view("mycast")["proposals"][0]
        self.assertEqual((prop["state"], prop["decided_by"], prop["proposed_by"]), ("handed_off", "policy:quiz-threshold", "agent"))
        for i in range(10, 14):
            self.assertEqual(self.answer(i)["analyst"], [])
        self.assertEqual(len(self.relay.tickets), 1)
        self.assertEqual(len(self.evo.view("mycast")["proposals"]), 1)

    def test_share_and_contrary_evidence_hold_the_threshold(self):
        for i in range(10):
            self.answer(i)
        self.assertEqual(len(self.relay.tickets), 1)  # transcript crossed
        os.environ["FACTORY_QUIZ_MIN_SHARE"] = "0.9"
        for i in range(10, 22):
            self.answer(i, answers={"q_use": "daily", "q_length": "short", "q_fix": "none", "q_channel": "web"})
        # 12 people ask for shorter episodes, but they are only 12/22 of the sample < 90 %
        self.assertEqual(len(self.relay.tickets), 1)
        os.environ["FACTORY_QUIZ_MIN_SHARE"] = "0.1"
        for i in range(22, 34):
            self.answer(i, answers={"q_use": "daily", "q_length": "same", "q_fix": "none", "q_channel": "web"})
        # 12 for shorter vs 12 "as it is now" (contrary): contrary >= half of support -> still held
        self.assertEqual(self.svc.analyze("mycast"), [])
        self.assertEqual(len(self.relay.tickets), 1)

    def test_kill_switch_leaves_the_proposal_to_the_owner(self):
        os.environ["FACTORY_QUIZ_AUTO_V2"] = "0"
        for i in range(10):
            out = self.answer(i)
        self.assertEqual(out["analyst"][0]["handoff"], "waiting_owner")
        self.assertEqual(self.relay.tickets, {})
        prop = self.evo.view("mycast")["proposals"][0]
        self.assertEqual(prop["state"], "proposed")
        self.evo.decide("mycast", prop["id"], {"action": "approve"}, actor_role="owner")
        self.evo.decide("mycast", prop["id"], {"action": "handoff"}, actor_role="owner", create_ticket=self.relay.create)
        self.assertEqual(len(self.relay.tickets), 1)

    def test_policy_handoff_only_for_agent_proposals_on_real_data(self):
        fid = self.evo.add_feedback("mycast", {"consent": True, "consent_ref": "x", "participant": "p", "source": "synthetic",
                                               "synthetic": True, "themes": ["a-b"]}, actor_role="agent")["feedback"]["id"]
        fake = self.evo.propose("mycast", {"title": "t", "problem": "p", "change": "c", "acceptance_test": "a",
                                           "feedback_ids": [fid]}, actor_role="agent")["proposal"]
        with self.assertRaises(EvolutionError) as ctx:
            self.evo.policy_handoff("mycast", fake["id"], policy="p", evidence={}, create_ticket=self.relay.create)
        self.assertEqual(ctx.exception.code, "synthetic_not_handed_off")
        self.answer(1)
        real = self.evo.view("mycast")["feedback"][0]["id"]
        mine = self.evo.propose("mycast", {"title": "t", "problem": "p", "change": "c", "acceptance_test": "a",
                                           "feedback_ids": [real]}, actor_role="member")["proposal"]
        with self.assertRaises(EvolutionError) as ctx:
            self.evo.policy_handoff("mycast", mine["id"], policy="p", evidence={}, create_ticket=self.relay.create)
        self.assertEqual(ctx.exception.code, "bad_transition")
        self.assertEqual(self.relay.tickets, {})

    def test_adaptive_validation_question(self):
        for i in range(3):
            self.answer(i, answers={"q_use": "daily", "q_add": ["offline"], "q_fix": "none", "q_channel": "web"})
        q = self.svc.quiz("mycast")
        self.assertEqual(q["validate"]["theme"], "offline-download")
        self.assertEqual(set(q["validate"]["text"]), {"uk", "ru", "en"})
        self.answer(3, validate={"theme": "offline-download", "answer": "no"})
        self.answer(4, validate={"theme": "offline-download", "answer": "yes"})
        th = {t["theme"]: t for t in self.evo.view("mycast")["themes"]["v1"]}
        self.assertEqual((th["offline-download"]["unique_support"], th["offline-download"]["unique_contra"]), (4, 1))

    # --- gifts, mail, privacy --------------------------------------------------------------------------------------
    def test_rewards_and_mail_are_held_while_flags_are_off(self):
        out = self.answer(1, email="a@b.co", contact_consent=True)
        self.assertEqual(out["reward"], {"status": "held_flag_off", "days": 0})
        self.assertEqual(self.grants, [])
        anon = self.svc.submit("mycast", body(), client="z", listener="")
        self.assertEqual(anon["reward"]["status"], "none")
        st = self.svc.stats("mycast")
        self.assertEqual((st["rewards"]["held_flag_off"], st["outbox"]["held_flag_off"], st["with_email"]), (1, 1, 1))
        self.assertNotIn("a@b.co", json.dumps(st))
        os.environ["FACTORY_QUIZ_REWARDS"] = "1"
        os.environ["FACTORY_QUIZ_MAIL"] = "1"
        self.assertEqual(self.svc.quiz("mycast")["reward_days"], 7)
        out = self.answer(2, email="c@d.co", contact_consent=True)
        self.assertEqual(out["reward"], {"status": "granted", "days": 7})
        self.assertEqual(self.grants[0][:2], ("lst00002", 7))
        self.assertEqual(self.svc.stats("mycast")["outbox"]["held_no_provider"], 1)  # no sender exists yet

    def test_privacy_delete_removes_email_and_feedback(self):
        out = self.answer(1, email="a@b.co", contact_consent=True)
        self.svc.delete("mycast", out["id"])
        self.assertEqual(self.evo.view("mycast")["feedback"], [])
        raw = (Path(self.tmp.name) / "quiz.json").read_text()
        self.assertNotIn("a@b.co", raw)
        self.assertEqual(self.code(lambda: self.svc.delete("mycast", out["id"])), "not_found")


class GrantBonusTest(unittest.TestCase):
    def test_grant_is_idempotent_and_adds_free_days(self):
        import mycast_accounts as ma
        with tempfile.TemporaryDirectory() as d:
            store = ma.ListenerStore(Path(d) / "l.json")
            rec = store.login({"provider": "telegram", "pid": "1", "name": "A"})
            before = ma.free_days(store.get(rec["slug"]))
            self.assertTrue(store.grant_bonus(rec["slug"], 7, "reward:qz-1"))
            self.assertFalse(store.grant_bonus(rec["slug"], 7, "reward:qz-1"))
            self.assertFalse(store.grant_bonus(rec["slug"], 99, "reward:qz-2"))
            self.assertFalse(store.grant_bonus("nobody", 7, "reward:qz-3"))
            self.assertEqual(ma.free_days(store.get(rec["slug"])), before + 7)


class Req:
    def __init__(self, body=None):
        self.body = body

    async def json(self):
        return self.body


class RouteTest(Base):
    def setUp(self):
        super().setUp()
        self.who, self.listener = {}, ""
        app = FastAPI()
        mq.install_mvp_quiz_routes(app, self.svc, lambda r: dict(self.who), listener_fn=lambda r: self.listener,
                                   client_fn=lambda r: "1.2.3.4")
        self.routes = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if "quiz" in r.path}

    def call(self, method, path, *args, body=None):
        fn = self.routes[(method, path)]
        out = fn(*args, request=Req(body)) if not asyncio.iscoroutinefunction(fn) else asyncio.run(fn(*args, request=Req(body)))
        if hasattr(out, "status_code"):
            return out.status_code, json.loads(out.body)
        return 200, out

    def test_public_quiz_and_owner_routes(self):
        self.assertEqual(self.routes[("GET", "/api/mycast/quiz")]()["version"], V)
        self.listener = "lst00042"
        st, out = self.call("POST", "/api/mycast/quiz", body=body())
        self.assertEqual(st, 200)
        self.assertEqual(self.call("POST", "/api/mycast/quiz", body=body())[0], 409)
        self.assertEqual(self.call("POST", "/api/mycast/quiz", body=[1])[0], 400)
        for who, status in (({}, 401), ({"role": "viewer"}, 403)):
            self.who = who
            self.assertEqual(self.call("GET", "/api/mvp-quiz/{project_id}/stats", "mycast")[0], status)
        self.who = {"role": "member"}
        self.assertEqual(self.call("GET", "/api/mvp-quiz/{project_id}/stats", "mycast")[1]["submissions"], 1)
        self.assertEqual(self.call("POST", "/api/mvp-quiz/{project_id}/submissions/{submission_id}/delete", "mycast", out["id"])[0], 403)
        self.who = {"role": "owner"}
        self.assertEqual(self.call("POST", "/api/mvp-quiz/{project_id}/submissions/{submission_id}/delete", "mycast", out["id"])[0], 200)


class PageAndWiringTest(unittest.TestCase):
    def test_widget_is_on_the_mycast_page_in_three_languages(self):
        html = (ROOT / "static/mycast-configurator/index.html").read_text(encoding="utf-8")
        self.assertIn('<section id="improve"', html)
        self.assertLess(html.index('<section id="improve"'), html.index('<footer data-t="foot">'))
        self.assertIn('<script src="improve.js" defer></script>', html)
        js = (ROOT / "static/mycast-configurator/improve.js").read_text(encoding="utf-8")
        keys = {lang: set(re.findall(r"(\w+): '", re.search(lang + r": \{(.*?)\}", js, re.S).group(1))) for lang in ("uk", "ru", "en")}
        self.assertEqual(keys["uk"], keys["ru"])
        self.assertEqual(keys["uk"], keys["en"])
        self.assertEqual(set(re.findall(r"fetch\('([^']+)'", js)), {"/api/mycast/quiz"})
        self.assertIn("quiz.rewards_enabled", js)  # the gift line is shown only when the server says it is on
        self.assertIn("prefers-reduced-motion", js)

    def test_app_wiring(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mvp_quiz_routes(", app)
        self.assertIn('"/api/mycast/quiz")', app)
        self.assertIn("grant_days=MYCAST_LISTENERS.grant_bonus", app)
        self.assertIn("create_ticket=_mvp_evolution_ticket", app)


if __name__ == "__main__":
    unittest.main(verbosity=1)
