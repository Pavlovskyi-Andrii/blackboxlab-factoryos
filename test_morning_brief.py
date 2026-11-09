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
        tickets = [{"status": "need_you"}, {"status": "in_progress"}, {"status": "done"}]
        text = compose_brief("2026-11-10", now, github=github, tickets=tickets, questions_open=2)
        self.assertIn("За добу влито змін: 1. Серед них: Relay round trip.", text)
        self.assertNotIn("#289", text)
        self.assertNotIn("P1", text)
        self.assertIn("Відкритих PR: 2, з червоним CI: 1.", text)
        self.assertIn("активних задач: 2, чекають на тебе: 1.", text)
        self.assertIn("Відкритих питань до команди: 2.", text)
        self.assertLessEqual(len(text), 1400)

    def test_unknown_github_is_said_not_guessed(self):
        text = compose_brief("2026-11-10", kyiv(8), github=None, tickets=[], questions_open=0)
        self.assertIn("Дані GitHub зараз недоступні", text)
        self.assertNotIn("влито", text)


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
        with patch.object(factory, "_intake_issues_from_ec2_snapshot", return_value=(None, "missing")):
            text = factory._morning_brief_compose("2026-11-10", kyiv(8))
        self.assertIn("Дані GitHub зараз недоступні", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
