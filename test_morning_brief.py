"""#106 morning brief at 08:00 Kyiv: owner opt-in, one per date, retries, failure note, honest content. Offline."""
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-brief-"))

from morning_brief import KYIV, MorningBrief, compose_brief  # noqa: E402
from voice_settings import BriefError  # noqa: E402


def kyiv(h, m=0, day=10):
    return datetime(2026, 11, day, h, m, tzinfo=KYIV).timestamp()


class ComposeTest(unittest.TestCase):
    def test_facts_only_and_no_numbers(self):
        now = kyiv(8)
        github = {"pulls": [
            {"title": "fix: Relay round trip (#289) P1", "merged_at": "2026-11-09T20:00:00Z", "state": "closed"},
            {"title": "T-602 old", "merged_at": "2026-11-01T10:00:00Z", "state": "closed"},
            {"title": "Open one", "state": "open", "head": {"sha": "a"}},
            {"title": "Open red", "state": "open", "head": {"sha": "b"}},
            {"title": "Draft", "state": "open", "draft": True, "head": {"sha": "c"}}],
            "ci": {"a": {"state": "passed"}, "b": {"state": "failed"}}}
        tickets = [{"id": "R-1", "title": "Waits", "status": "need_you"},
                   {"id": "R-2", "title": "Running", "status": "in_progress", "execution": {"owner": "claude"}},
                   {"id": "R-3", "title": "Closed yesterday", "status": "done",
                    "history": [{"to_status": "done", "at": "2026-11-09T18:00:00+00:00"}]}]
        text = compose_brief("2026-11-10", now, github=github, tickets=tickets, questions_open=2)
        self.assertIn("🔀 За добу влито PR: 1.\n  • Relay round trip", text)
        self.assertNotIn("#289", text)
        self.assertNotIn("P1", text)
        self.assertIn("🔴 Червоний CI у відкритих PR: 1.", text)
        self.assertIn("📊 Вчора закрито задач: 1.\n  ✅ R-3 Closed yesterday", text)
        self.assertIn("📋 Сьогодні в плані агентів: 1.", text)
        self.assertIn("🤖 Claude: у роботі 1, у черзі 0", text)
        self.assertIn("🙋 Чекають на тебе: 1.", text)
        self.assertIn("Відкритих питань до команди: 2.", text)

    def test_plan_vs_fact(self):
        tickets = [{"id": "R-1", "title": "A", "status": "done"}, {"id": "R-2", "title": "B", "status": "in_progress"},
                   {"id": "R-3", "title": "C", "status": "done"}, {"id": "R-4", "title": "D", "status": "inbox"}]
        text = compose_brief("2026-11-11", kyiv(8, day=11), github=None, tickets=tickets, questions_open=0,
                             yesterday_plan={"date": "2026-11-10", "ids": ["R-1", "R-2", "R-3", "R-4"]})
        self.assertIn("у плані було 4, виконано 2 — ККД 50%", text)
        self.assertIn("⏳ не встигли: R-2 B", text)
        first = compose_brief("2026-11-11", kyiv(8, day=11), github=None, tickets=tickets, questions_open=0)
        self.assertIn("План/факт з'явиться завтра", first)

    def test_unknown_github_is_said_not_guessed(self):
        text = compose_brief("2026-11-10", kyiv(8), github=None, tickets=[], questions_open=0)
        self.assertIn("GitHub зараз недоступний", text)
        self.assertNotIn("влито", text)

    def test_voice_reads_headlines_only(self):
        from morning_brief import voice_text
        full = compose_brief("2026-11-10", kyiv(8), github=None, questions_open=0,
                             tickets=[{"id": f"R-{i}", "title": "Task %d" % i, "status": "need_you"} for i in range(30)])
        spoken = voice_text(full)
        self.assertNotIn("R-1 Task", spoken)
        self.assertIn("Чекають на тебе: 30.", spoken)
        self.assertLessEqual(len(spoken), 1400)
        self.assertFalse(spoken.startswith("☀"))


class ScheduleTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [kyiv(7, 59)]
        self.delivered, self.texts, self.fail = [], [], [None]

        def deliver(date, text):
            if self.fail[0]:
                raise self.fail[0]
            dup = date in [d for d, _ in self.delivered]
            self.delivered.append((date, text))
            return {"sent": not dup, "duplicate": dup}
        self.b = MorningBrief(Path(self.dir.name), deliver=deliver, send_text=self.texts.append,
                              compose=lambda date, now: f"brief {date}", clock=lambda: self.t[0])

    def tearDown(self):
        self.dir.cleanup()

    def test_off_until_owner_opts_in(self):
        self.t[0] = kyiv(8, 5)
        self.assertIsNone(self.b.tick())
        self.assertIsNone(self.b.handle_private("/ask hi"))
        self.assertIn("увімкнено", self.b.handle_private("/brief on"))
        self.assertEqual(self.b.tick()["status"], "sent")
        self.assertEqual(self.b.handle_private("/brief off"), "Ранковий брифінг вимкнено.")
        self.assertIn("вимкнено", self.b.handle_private("/brief@FactoryOSBot"))

    def test_once_per_date_from_0800_kyiv_and_not_late(self):
        self.b.handle_private("/brief on")
        self.assertIsNone(self.b.tick())                          # 07:59
        self.t[0] = kyiv(8)
        self.assertEqual(self.b.tick(), {"date": "2026-11-10", "status": "sent", "done": True})
        self.assertEqual(self.texts, ["📝 Текст брифінгу:\nbrief 2026-11-10"])
        self.t[0] = kyiv(9, 30)
        self.assertIsNone(self.b.tick())                          # done for the day
        self.t[0] = kyiv(11, 0, day=11)
        self.assertIsNone(self.b.tick())                          # a restart at 11:00 does not send a stale brief
        self.assertEqual(len(self.delivered), 1)

    def test_retries_then_text_with_failure_note(self):
        self.b.handle_private("/brief on")
        self.fail[0] = BriefError(502, "brief failed: rate_limited")
        self.t[0] = kyiv(8)
        self.assertFalse(self.b.tick()["done"])
        self.t[0] += 60
        self.assertIsNone(self.b.tick())                          # 20 minutes between tries
        self.t[0] = kyiv(8, 21)
        self.assertFalse(self.b.tick()["done"])
        self.assertEqual(self.texts, [])
        self.t[0] = kyiv(8, 42)
        self.assertEqual(self.b.tick(), {"date": "2026-11-10", "status": "failed", "done": True})
        self.assertEqual(len(self.texts), 1)
        self.assertIn("brief 2026-11-10", self.texts[0])
        self.assertIn("не доставлено (brief failed: rate_limited) після 3 спроб", self.texts[0])
        self.t[0] = kyiv(9, 30)
        self.assertIsNone(self.b.tick())
        self.assertIn("failed", self.b.handle_private("/brief"))

    def test_test_command_is_text_only(self):
        self.t[0] = kyiv(7)
        reply = self.b.handle_private("/brief test")
        self.assertIn("без голосу", reply)
        self.assertIn("brief 2026-11-10", reply)
        self.assertEqual(self.delivered, [])


class WebhookTest(unittest.TestCase):
    """The real ASGI app: the owner's /brief reaches the opt-in, another chat cannot switch it on."""

    def test_owner_command_through_the_webhook(self):
        from test_worker_token_binding import asgi_post, factory
        with tempfile.TemporaryDirectory() as tmp:
            brief = MorningBrief(Path(tmp), deliver=lambda d, t: {"sent": True}, send_text=lambda t: None,
                                 compose=lambda d, n: "x")
            sent = []
            with patch.object(factory, "MORNING_BRIEF", brief), \
                 patch.object(factory, "_telegram_webhook_authorized", return_value=True), \
                 patch.object(factory, "_telegram_load_state", return_value={"chat_id": "42"}), \
                 patch.object(factory, "_telegram_send_to", side_effect=lambda c, t: sent.append((str(c), t))), \
                 patch.object(factory, "_telegram_api", return_value={"ok": True}):
                def post(chat, uid):
                    body = {"update_id": uid, "message": {"message_id": uid, "chat": {"id": chat, "type": "private"},
                                                          "from": {"id": chat}, "text": "/brief on"}}
                    return asgi_post("/api/integrations/telegram/webhook", body=json.dumps(body).encode())
                self.assertEqual(post(93, 8801)[0], 200)
                self.assertFalse(brief.status()["enabled"])
                self.assertEqual(post(42, 8802)[0], 200)
                self.assertTrue(brief.status()["enabled"])
                self.assertTrue(any(c == "42" and "увімкнено" in t for c, t in sent))

    def test_server_compose_uses_real_stores(self):
        from test_worker_token_binding import factory
        with patch.object(factory, "_intake_issues_from_ec2_snapshot", return_value=(None, "missing")), \
             patch.object(factory, "GITHUB_READ_TOKEN", ""):
            text = factory._morning_brief_compose("2026-11-10", kyiv(8))
        self.assertIn("GitHub зараз недоступний", text)

    def test_plan_is_stored_and_used_next_day(self):
        with tempfile.TemporaryDirectory() as tmp:
            t, seen, plan = [kyiv(8)], [], [["R-1", "R-2"]]
            b = MorningBrief(Path(tmp), deliver=lambda d, x: {"sent": True}, send_text=lambda x: None,
                             compose=lambda date, now, prev: seen.append(prev) or "x", clock=lambda: t[0],
                             plan_source=lambda: plan[0])
            b.handle_private("/brief on")
            b.tick()
            self.assertEqual(seen, [None])
            plan[0] = ["R-9"]
            t[0] = kyiv(8, day=11)
            b.tick()
            self.assertEqual(seen[-1], {"date": "2026-11-10", "ids": ["R-1", "R-2"]})
            b.handle_private("/brief test")                                     # a test does not record a plan
            self.assertEqual(seen[-1], {"date": "2026-11-10", "ids": ["R-1", "R-2"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)
