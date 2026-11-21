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
        self.evo = EvolutionStore(d / "evo.json", clock=lambda: self.t[0], project_exists=lambda pid: pid in mq.QUIZZES)
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

    def test_anonymous_repeats_across_days_never_reach_the_threshold(self):
        # Codex review #412: an anonymous id rotates daily, so one person on 12 days must not become 12 supporters.
        for day in range(12):
            out = self.svc.submit("mycast", body(), client="same-person", listener="")
            self.assertEqual((out["counted"], out["reason"]), (False, "sign_in_to_count"))
            self.t[0] += 86400
        view = self.evo.view("mycast")
        self.assertEqual(len(view["feedback"]), 12)
        self.assertEqual(view["themes"]["v1"], [])
        self.assertEqual(self.relay.tickets, {})
        self.assertEqual(self.svc.analyze("mycast"), [])

    def test_malformed_relay_answer_is_not_saved_as_a_handoff(self):
        for i in range(9):
            self.answer(i)
        good = self.svc.create_ticket
        self.svc.create_ticket = lambda **kw: {"status": "inbox"}  # no id
        out = self.answer(9)
        self.assertEqual(out["analyst"][0]["error"], "relay_failed")
        prop = self.evo.view("mycast")["proposals"][0]
        self.assertEqual((prop["state"], prop["ticket_id"]), ("proposed", None))
        self.svc.create_ticket = good  # Relay is back: the next analyst pass retries the same proposal once
        retry = self.answer(10)["analyst"]
        self.assertEqual((retry[0]["retry"], retry[0]["handoff"], retry[0]["ticket"]), (True, "handed_off", "R-0001"))
        self.assertEqual(self.answer(11)["analyst"], [])
        self.assertEqual(len(self.relay.tickets), 1)
        with self.assertRaises(EvolutionError):
            self.evo.decide("mycast", "pr-404", {"action": "handoff"}, actor_role="owner", create_ticket=lambda **kw: {})

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
        # T-636: the widget is shared, so the address comes from data-api; without it, it is still the MyCast quiz
        self.assertIn("var API = root.getAttribute('data-api') || '/api/mycast/quiz';", js)
        self.assertEqual(set(re.findall(r"fetch\(([^,)]+)", js)), {"API"})
        self.assertNotIn("data-api", html)
        self.assertIn("quiz.rewards_enabled", js)  # the gift line is shown only when the server says it is on
        self.assertIn("prefers-reduced-motion", js)

    def test_app_wiring(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mvp_quiz_routes(", app)
        # Codex review #412: exactly one public path, not a prefix that would also open /api/mycast/quiz-admin
        prefixes = re.search(r"public_prefixes = \((.*?)\)", app).group(1)
        self.assertNotIn("/api/mycast/quiz", prefixes)
        self.assertIn('public_paths = {"/api/mycast/quiz", ', app)
        self.assertIn("grant_days=MYCAST_LISTENERS.grant_bonus", app)
        self.assertIn("create_ticket=_mvp_evolution_ticket", app)


# --- T-636: the same quiz on the other MVPs -------------------------------------------------------------------------
OTHERS = {  # product -> (answers that ask for one theme, that theme, a second product-specific theme option)
    "mybrief-pro": ({"q_use": "several", "q_length": "same", "q_add": ["why"], "q_fix": "none", "q_channel": "web"}, "job-relevance-note"),
    "decision-memory": ({"q_use": "weekly", "q_capture": "manual", "q_add": ["ask"], "q_fix": "none", "q_channel": "page"}, "ask-the-memory"),
}


class OtherProductsTest(Base):
    def send(self, pid, i, **kw):
        b = {"version": mq.QUIZZES[pid]["version"], "consent": True, "answers": dict(OTHERS[pid][0])}
        b.update(kw)
        return self.svc.submit(pid, b, client=f"10.1.0.{i}", listener=kw.pop("listener", f"ws-{i:016d}"))

    def test_every_quiz_definition_is_complete_and_product_specific(self):
        self.assertEqual(set(mq.QUIZZES), {"mycast", "mybrief-pro", "decision-memory"})
        seen_themes, seen_versions, seen_apis = {}, set(), set()
        for pid, quiz in mq.QUIZZES.items():
            self.assertNotIn(quiz["version"], seen_versions)
            self.assertNotIn(quiz["api"], seen_apis)
            seen_versions.add(quiz["version"])
            seen_apis.add(quiz["api"])
            self.assertIn(quiz["access"], ("public", "owner"))
            self.assertIn(quiz["identity"], ("listener", "workspace"))
            for field in ("title", "free_text", "peers"):
                self.assertEqual(set(quiz[field]), {"uk", "ru", "en"}, (pid, field))
            ids = [q["id"] for q in quiz["questions"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertGreaterEqual(len(ids), mq.MIN_ANSWERS + 1)
            use = next(q for q in quiz["questions"] if q["id"] == "q_use")
            self.assertIn("not_yet", [o["id"] for o in use["options"]])
            refs = [q for _, q in quiz["summary"]["job"] + quiz["summary"]["helped"]] + [quiz["summary"]["failed"]]
            self.assertTrue(set(refs) <= set(ids), pid)
            for q in quiz["questions"]:
                self.assertEqual(set(q["text"]), {"uk", "ru", "en"})
                self.assertEqual(len({o["id"] for o in q["options"]}), len(q["options"]))
                for o in q["options"]:
                    self.assertEqual(set(o["text"]), {"uk", "ru", "en"})
                    self.assertTrue(all(o["text"].values()))
            themes = mq.quiz_themes(pid)
            self.assertGreaterEqual(len(themes), 8, pid)
            for th in themes:
                self.assertIn(th, mq.THEMES)
                self.assertRegex(th, r"^[a-z0-9][a-z0-9-]{1,30}$")
                self.assertNotIn(th, seen_themes, f"{th} is shared by {pid} and {seen_themes.get(th)}")
                seen_themes[th] = pid
                self.assertEqual(set(mq.THEMES[th]["title"]), {"uk", "ru", "en"})
                self.assertTrue(mq.THEMES[th]["change"] and mq.THEMES[th]["test"])
            out = self.svc.quiz(pid)
            self.assertEqual((out["project"], out["version"], out["name"]), (pid, quiz["version"], quiz["name"]))
        self.assertEqual(set(seen_themes), set(mq.THEMES))  # no orphan theme
        # gifts only where the product has accounts
        self.assertEqual({pid for pid, q in mq.QUIZZES.items() if q["rewards"]}, {"mycast"})
        self.assertEqual({pid for pid, q in mq.QUIZZES.items() if q["identity"] == "listener"}, {"mycast"})

    def test_answer_goes_to_the_products_own_ledger(self):
        for pid, (answers, theme) in OTHERS.items():
            out = self.send(pid, 1, free_text="mail me at someone@example.com")
            self.assertTrue(out["counted"], pid)
            view = self.evo.view(pid)
            self.assertEqual(len(view["feedback"]), 1)
            rec = view["feedback"][0]
            self.assertEqual(rec["source"], "in_product")
            self.assertTrue(rec["consent"]["ref"].startswith(f"{pid}-quiz:{mq.QUIZZES[pid]['version']}:qz-"))
            self.assertEqual(rec["themes"], [theme])
            self.assertTrue(set(rec["contra"]) <= mq.quiz_themes(pid))
            self.assertTrue(rec["contra"])
            self.assertTrue(rec["substantive"])
            self.assertTrue(rec["answers"]["job"].startswith(f"{mq.QUIZZES[pid]['name']} quiz {mq.QUIZZES[pid]['version']}: "))
            self.assertNotIn("?", rec["answers"]["job"])
            self.assertNotIn("someone@example.com", json.dumps(rec))
        self.assertEqual(self.evo.view("mycast")["feedback"], [])
        self.assertEqual(self.svc.stats("mybrief-pro")["submissions"], 1)
        self.assertEqual(self.svc.stats("decision-memory")["version"], "decision-memory-q1")
        self.assertEqual(self.svc.stats("mycast")["submissions"], 0)

    def test_the_same_person_answers_each_product_once(self):
        for pid in OTHERS:
            self.send(pid, 1)
            self.assertEqual(self.code(lambda: self.send(pid, 1)), "already_answered")
        self.answer(1)  # and the MyCast quiz is still open to them

    def test_validation_uses_the_products_own_questions(self):
        for pid in OTHERS:
            self.assertEqual(self.code(lambda: self.send(pid, 1, version=V)), "quiz_changed")
            self.assertEqual(self.code(lambda: self.send(pid, 1, answers=body()["answers"])), "bad_answer")
            self.assertEqual(self.code(lambda: self.send(pid, 1, consent=False)), "consent_required")
            self.assertEqual(self.code(lambda: self.send(pid, 1, answers={"q_use": "not_yet"})), "too_few_answers")
        self.assertEqual(self.code(lambda: self.answer(1, answers=OTHERS["mybrief-pro"][0])), "bad_answer")

    def test_threshold_makes_one_ticket_per_product_with_its_own_acceptance_test(self):
        for n, (pid, (answers, theme)) in enumerate(OTHERS.items(), 1):
            for i in range(9):
                self.assertEqual(self.send(pid, i)["analyst"], [])
            act = self.send(pid, 9)["analyst"]
            self.assertEqual([(a["theme"], a["handoff"], a["people"]) for a in act], [(theme, "handed_off", 10)])
            self.assertEqual(len(self.relay.tickets), n)
            ticket = self.relay.tickets[act[0]["ticket"]]
            self.assertIn("Acceptance test: " + mq.THEMES[theme]["test"], ticket["body"])
            prop = self.evo.view(pid)["proposals"]
            self.assertEqual([(p["theme"], p["state"], p["decided_by"]) for p in prop], [(theme, "handed_off", "policy:quiz-threshold")])
            self.assertEqual(self.send(pid, 10)["analyst"], [])
        self.assertEqual(self.evo.view("mycast")["proposals"], [])

    def test_anonymous_and_never_used_answers_do_not_count(self):
        for pid, (answers, theme) in OTHERS.items():
            for day in range(12):  # one anonymous visitor on 12 days is not 12 supporters
                out = self.send(pid, 1, listener="")
                self.assertEqual((out["counted"], out["reason"]), (False, "anonymous_not_counted"))
                self.t[0] += 86400
            out = self.send(pid, 2, answers=dict(answers, q_use="not_yet"))
            self.assertEqual((out["counted"], out["reason"]), (False, "not_used_yet"))
            view = self.evo.view(pid)
            self.assertEqual((len(view["feedback"]), view["themes"]["v1"], view["proposals"]), (13, [], []))
        self.assertEqual(self.relay.tickets, {})

    def test_another_products_theme_never_becomes_a_proposal(self):
        # a foreign tag in the ledger (hand-recorded feedback, or a validate answer naming a MyCast theme) is not the quiz's
        for i in range(12):
            self.evo.add_feedback("mybrief-pro", {"consent": True, "consent_ref": f"manual-{i}", "participant": f"p{i}", "source": "interview",
                                                  "tried": "yes", "job": "reads the briefing every week at work", "helped": "sources",
                                                  "failed": "wants audio", "themes": ["text-transcript"]}, actor_role="owner")
        self.assertEqual(self.svc.analyze("mybrief-pro"), [])
        self.assertIsNone(self.svc.quiz("mybrief-pro")["validate"])
        self.send("mybrief-pro", 1, validate={"theme": "offline-download", "answer": "yes"})
        self.assertNotIn("offline-download", self.evo.view("mybrief-pro")["feedback"][-1]["themes"])
        self.assertEqual((self.relay.tickets, self.evo.view("mybrief-pro")["proposals"]), ({}, []))

    def test_adaptive_question_speaks_about_the_product(self):
        for pid, (answers, theme) in OTHERS.items():
            for i in range(3):
                self.send(pid, i)
            v = self.svc.quiz(pid)["validate"]
            self.assertEqual(v["theme"], theme)
            for lang in ("uk", "ru", "en"):
                self.assertTrue(v["text"][lang].startswith(mq.QUIZZES[pid]["peers"][lang]))
                self.assertIn(mq.THEMES[theme]["title"][lang], v["text"][lang])
            self.send(pid, 3, validate={"theme": theme, "answer": "no"}, answers=dict(answers, q_add=["nothing"]))
            th = {t["theme"]: t for t in self.evo.view(pid)["themes"]["v1"]}[theme]
            self.assertEqual((th["unique_support"], th["unique_contra"]), (3, 1))

    def test_no_gift_where_the_product_has_no_accounts(self):
        os.environ["FACTORY_QUIZ_REWARDS"] = "1"
        for pid in OTHERS:
            q = self.svc.quiz(pid)
            self.assertEqual((q["rewards_enabled"], q["reward_days"]), (False, 0))
            self.assertEqual(self.send(pid, 1)["reward"], {"status": "none", "reason": "no_accounts"})
            self.assertEqual(self.svc.stats(pid)["rewards"], {"held_flag_off": 0, "granted": 0, "not_granted": 0})
        self.assertEqual(self.grants, [])
        self.assertNotIn("reward:", (Path(self.tmp.name) / "quiz.json").read_text())
        self.assertEqual(self.svc.quiz("mycast")["reward_days"], 7)  # MyCast has accounts: unchanged
        self.assertEqual(self.answer(5)["reward"], {"status": "granted", "days": 7})

    def test_email_is_held_and_privacy_delete_works(self):
        for pid in OTHERS:
            out = self.send(pid, 1, email="a@b.co", contact_consent=True)
            self.assertEqual(self.svc.stats(pid)["outbox"]["held_flag_off"], 1)
            self.assertEqual(self.code(lambda: self.svc.delete("mycast", out["id"])), "not_found")
            self.svc.delete(pid, out["id"])
            self.assertEqual(self.evo.view(pid)["feedback"], [])
        self.assertNotIn("a@b.co", (Path(self.tmp.name) / "quiz.json").read_text())

    def test_workspace_person(self):
        a, b = mq.workspace_person({"role": "member", "email": "Ann@Example.com "}), mq.workspace_person({"role": "viewer", "email": "ann@example.com"})
        self.assertEqual(a, b)
        self.assertRegex(a, r"^ws-[0-9a-f]{16}$")
        self.assertNotIn("ann", a)
        self.assertNotEqual(a, mq.workspace_person({"role": "member", "email": "bob@example.com"}))
        self.assertEqual(mq.workspace_person({"role": "owner", "email": ""}), "ws-owner")
        for nobody in ({}, None, {"role": "viewer"}, {"role": "guest", "email": ""}):
            self.assertEqual(mq.workspace_person(nobody), "")


class OtherProductsRouteTest(RouteTest):
    def post(self, pid, **kw):
        b = {"version": mq.QUIZZES[pid]["version"], "consent": True, "answers": dict(OTHERS[pid][0])}
        b.update(kw)
        return self.call("POST", mq.QUIZZES[pid]["api"], body=b)

    def test_routes_exist_once_per_product(self):
        self.assertEqual({p for m, p in self.routes if m == "GET" and p.endswith("/quiz")},
                         {"/api/mycast/quiz", "/api/mybrief/public/quiz", "/api/decision-memory/quiz"})
        self.assertEqual(len(self.routes), 3 * 2 + 2)

    def test_mybrief_quiz_is_public_and_counts_only_workspace_people(self):
        self.assertEqual(self.routes[("GET", "/api/mybrief/public/quiz")]()["version"], "mybrief-q1")
        self.listener = "lst00042"  # a MyCast listener cookie is not a MyBrief identity
        st, out = self.post("mybrief-pro")
        self.assertEqual((st, out["counted"], out["reason"], out["reward"]["status"]), (200, False, "anonymous_not_counted", "none"))
        self.who = {"role": "member", "email": "ann@example.com"}
        st, out = self.post("mybrief-pro")
        self.assertEqual((st, out["counted"]), (200, True))
        self.assertEqual(self.post("mybrief-pro")[0], 409)
        self.assertEqual(self.call("POST", "/api/mybrief/public/quiz", body="x")[0], 400)
        self.assertNotIn("ann@example.com", (Path(self.tmp.name) / "quiz.json").read_text() + (Path(self.tmp.name) / "evo.json").read_text())
        self.assertEqual(self.call("GET", "/api/mvp-quiz/{project_id}/stats", "mybrief-pro")[1]["counted"], 1)

    def test_decision_memory_quiz_is_owner_only(self):
        for who, status in (({}, 401), ({"role": "viewer", "email": "v@example.com"}, 403), ({"role": "member", "email": "m@example.com"}, 403)):
            self.who = who
            self.assertEqual(self.call("GET", "/api/decision-memory/quiz")[0], status)
            self.assertEqual(self.post("decision-memory")[0], status)
        self.assertEqual(self.evo.view("decision-memory")["feedback"], [])
        self.who = {"role": "owner", "email": ""}
        self.assertEqual(self.call("GET", "/api/decision-memory/quiz")[1]["name"], "Decision Memory")
        st, out = self.post("decision-memory")
        self.assertEqual((st, out["counted"], out["reward"]["status"]), (200, True, "none"))
        self.assertEqual(self.post("decision-memory")[0], 409)


class OtherPagesTest(unittest.TestCase):
    def test_pages_reuse_the_widget_with_their_own_quiz(self):
        js = (ROOT / "static/mycast-configurator/improve.js").read_text(encoding="utf-8")
        for attr in ("data-api", "data-product", "data-key"):
            self.assertIn(f"root.getAttribute('{attr}')", js)
        self.assertIn("anonymous_not_counted", js)
        self.assertNotRegex(js.split("var UI = {", 1)[1], r"MyCast")  # every text names the product through %P%
        keys = []
        for pid, page in (("mybrief-pro", "static/mybrief/index.html"), ("decision-memory", "static/decision-memory/index.html")):
            html = (ROOT / page).read_text(encoding="utf-8")
            tag = re.search(r'<section id="improve"[^>]*>', html).group(0)
            self.assertEqual(html.count('id="improve"'), 1)
            self.assertIn(f'data-api="{mq.QUIZZES[pid]["api"]}"', tag)
            self.assertIn(f'data-product="{mq.QUIZZES[pid]["name"]}"', tag)
            self.assertIn("data-plain", tag)
            self.assertIn(" hidden", tag)  # shown only after the quiz loaded
            keys.append(re.search(r'data-key="([a-z-]+)"', tag).group(1))
            self.assertEqual(html.count("/static/mycast-configurator/improve.js"), 1)
            self.assertLess(html.index('id="improve"'), html.index("/static/mycast-configurator/improve.js"))
            self.assertFalse((ROOT / page).with_name("improve.js").exists())  # reused, not copied
        self.assertEqual(len(set(keys + ["mycast"])), 3)  # "done"/"closed" are remembered per product

    def test_new_quiz_paths_follow_each_products_login_rule(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        paths = re.search(r"public_paths = \{(.*?)\}", app, re.S).group(1)
        prefixes = re.search(r"public_prefixes = \((.*?)\)", app).group(1)
        self.assertIn('"/api/mybrief/public/"', prefixes)  # MyBrief is a public page
        self.assertNotIn("decision-memory", paths + prefixes)  # Decision Memory stays behind the dashboard login


if __name__ == "__main__":
    unittest.main(verbosity=1)
