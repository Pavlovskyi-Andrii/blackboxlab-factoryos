"""#129 FactoryOS Team group bridge: pairing, owner-only commands, real Claude answers via the existing question
worker, /stop, decisions, dedupe. Offline: fake Telegram send, the real ASGI app for the end-to-end path."""
import asyncio
import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-group-"))

from telegram_group import GroupBridge  # noqa: E402

OWNER, GROUP, OTHER = "42", "-1001234", "777"


def group_msg(text, update_id, sender=OWNER, chat=GROUP, reply_to_bot=False):
    m = {"message_id": update_id, "chat": {"id": int(chat), "type": "supergroup"}, "from": {"id": int(sender)}, "text": text}
    if reply_to_bot:
        m["reply_to_message"] = {"from": {"id": 1, "is_bot": True}}
    return {"update_id": update_id, "message": m}


class BridgeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.asked, self.sent = [], []

        def ask(text, source_key="", meta=None):
            item = {"id": "Q-%d" % (len(self.asked) + 1), "text": text, "source_key": source_key, "meta": meta}
            if not any(a["source_key"] == source_key for a in self.asked):
                self.asked.append(item)
            return next(a for a in self.asked if a["source_key"] == source_key)
        self.b = GroupBridge(Path(self.dir.name), ask=ask, clock=lambda: self.t[0])
        self.send = lambda chat, text, markup=None: self.sent.append((chat, text, markup))

    def tearDown(self):
        self.dir.cleanup()

    def pair(self):
        code = self.b.handle_private("/group").split("Код привязки группы: ")[1].split()[0]
        return self.b.handle_group(group_msg("/pair_group@FactoryOSBot " + code, 1), OWNER, self.send)

    def test_pairing_needs_a_fresh_owner_code(self):
        self.assertEqual(self.b.handle_group(group_msg("/discuss x", 5), OWNER, self.send)["action"], "unbound_group")
        self.assertEqual(self.b.handle_group(group_msg("/pair_group ABCDEF", 6), OWNER, self.send)["action"], "pair_refused")
        code = self.b.handle_private("/group").split("Код привязки группы: ")[1].split()[0]
        self.assertEqual(self.b.handle_group(group_msg("/pair_group " + code, 7, sender=OTHER), OWNER, self.send)["action"], "ignored_member")
        self.t[0] += 601
        self.assertEqual(self.b.handle_group(group_msg("/pair_group " + code, 8), OWNER, self.send)["action"], "pair_refused")
        self.assertEqual(self.pair()["action"], "paired")
        self.assertTrue(self.b.status()["paired"])
        self.assertEqual(self.b.handle_private("/group off"), "Группа отвязана.")
        self.assertFalse(self.b.status()["paired"])

    def test_discuss_follow_up_answer_stop(self):
        self.pair()
        r = self.b.handle_group(group_msg("/discuss релиз MyCast", 10), OWNER, self.send)
        self.assertEqual((r["action"], r["thread"]), ("discuss", "D-0001"))
        self.assertEqual(self.asked[0]["meta"], {"group_thread": "D-0001"})
        self.assertIn("ChatGPT и Gemini", self.sent[-1][1])                       # shown unavailable, not imitated
        self.assertEqual(self.b.handle_group(group_msg("/discuss релиз MyCast", 10), OWNER, self.send)["action"], "duplicate")
        self.assertEqual(len(self.asked), 1)
        # Claude's real answer is posted into the group, labelled.
        self.assertTrue(self.b.deliver_answer({"id": "Q-1", "answer": "План: …", "meta": {"group_thread": "D-0001"}}, self.send))
        self.assertEqual(self.sent[-1][0], GROUP)
        self.assertTrue(self.sent[-1][1].startswith("[Claude] D-0001"))
        self.b.handle_group(group_msg("а сроки?", 11, reply_to_bot=True), OWNER, self.send)
        self.assertIn("Предыдущий ответ Claude", self.asked[1]["text"])
        self.assertEqual(self.b.handle_group(group_msg("/stop", 12), OWNER, self.send)["action"], "stopped")
        n = len(self.sent)
        self.assertTrue(self.b.deliver_answer({"id": "Q-2", "answer": "late", "meta": {"group_thread": "D-0001"}}, self.send))
        self.assertEqual(len(self.sent), n)                                       # after /stop: nothing posted
        self.assertFalse(self.b.deliver_answer({"id": "Q-9", "answer": "dm"}, self.send))   # a DM /ask stays a DM

    def test_members_and_other_groups_are_ignored(self):
        self.pair()
        self.assertEqual(self.b.handle_group(group_msg("/discuss hi", 20, sender=OTHER), OWNER, self.send)["action"], "ignored_member")
        self.assertEqual(self.b.handle_group(group_msg("/discuss hi", 21, chat="-100999"), OWNER, self.send)["action"], "unbound_group")
        self.assertEqual(self.asked, [])

    def test_decision_needs_confirmation(self):
        self.pair()
        r = self.b.handle_group(group_msg("/decision Запуск после теста", 30), OWNER, self.send)
        pid = r["pending"]
        cb = lambda who, ans: {"callback_query": {"id": "c", "data": f"grp:dec:{pid}:{ans}", "from": {"id": int(who)},
                                                  "message": {"chat": {"id": int(GROUP)}}}}
        self.assertEqual(self.b.handle_group(cb(OTHER, "yes"), OWNER, self.send)["action"], "ignored_member")
        self.assertEqual(self.b.status()["decisions"], 0)
        self.assertEqual(self.b.handle_group(cb(OWNER, "yes"), OWNER, self.send)["action"], "decision_yes")
        self.assertEqual(self.b.handle_group(cb(OWNER, "yes"), OWNER, self.send)["action"], "decision_stale")
        self.assertEqual(self.b.status()["decisions"], 1)


class GeminiInGroupTest(unittest.TestCase):
    """Owner 2026-11-11: Gemini answers in /discuss threads too; ChatGPT stays honestly not connected."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.sent, self.prompts, self.pending = [], [], []
        self.reply = [("Предлагаю начать с теста круга.", "")]

        def gem(prompt):
            self.prompts.append(prompt)
            return self.reply[0]
        ask = lambda text, source_key="", meta=None: {"id": "Q-%d" % len(self.prompts)}
        self.b = GroupBridge(Path(self.dir.name), ask=ask, clock=lambda: self.t[0], gemini=gem,
                             run_async=self.pending.append)          # run later, like a background thread
        self.send = lambda chat, text, markup=None: self.sent.append((chat, text))
        code = self.b.handle_private("/group").split("Код привязки группы: ")[1].split()[0]
        self.b.handle_group(group_msg("/pair_group " + code, 1), OWNER, self.send)

    def tearDown(self):
        self.dir.cleanup()

    def flush(self):
        while self.pending:
            self.pending.pop(0)()

    def test_gemini_answers_in_the_thread(self):
        self.assertIn("ChatGPT не подключён", self.sent[-1][1])
        self.b.handle_group(group_msg("/discuss релиз MyCast", 2), OWNER, self.send)
        self.assertIn("Gemini", self.sent[-1][1])
        self.flush()
        self.assertEqual(self.sent[-1], (GROUP, "[Gemini] D-0001\nПредлагаю начать с теста круга."))
        self.assertIn("релиз MyCast", self.prompts[0])
        self.b.handle_group(group_msg("а сроки?", 3, reply_to_bot=True), OWNER, self.send)
        self.flush()
        self.assertIn("Твой предыдущий ответ: Предлагаю", self.prompts[1])

    def test_stop_drops_a_late_answer_and_failures_are_said(self):
        self.b.handle_group(group_msg("/discuss тема", 2), OWNER, self.send)
        self.b.handle_group(group_msg("/stop", 3), OWNER, self.send)
        n = len(self.sent)
        self.flush()
        self.assertEqual(len(self.sent), n)                                      # stopped: nothing posted
        self.reply[0] = (None, "перегружен, попробуй позже")
        self.b.handle_group(group_msg("/discuss ещё", 4), OWNER, self.send)
        self.flush()
        self.assertIn("[Gemini] D-0002: не ответил (перегружен, попробуй позже)", self.sent[-1][1])

    def test_daily_cap(self):
        import telegram_group
        with unittest.mock.patch.object(telegram_group, "GEMINI_DAILY_CAP", 1):
            self.b.handle_group(group_msg("/discuss one", 2), OWNER, self.send)
            self.b.handle_group(group_msg("/discuss two", 3), OWNER, self.send)
        self.assertIn("дневной лимит 1", self.sent[-1][1])
        self.flush()
        self.assertEqual(len(self.prompts), 1)


class EndToEndTest(unittest.TestCase):
    """Real webhook → existing owner-question queue → worker answer route → message in the paired group."""

    def test_group_question_round_trip(self):
        import app as factory
        from test_worker_token_binding import asgi_post
        with tempfile.TemporaryDirectory() as tmp:
            queue = factory.OWNER_QUESTIONS           # the answer route was installed with this very store
            bridge = GroupBridge(Path(tmp), ask=lambda text, source_key="", meta=None: queue.create(
                factory.TELEGRAM_TASK, "", "", text, source_key=source_key, meta=meta))
            sent = []
            with patch.object(factory, "GROUP_BRIDGE", bridge), \
                 patch.object(factory, "_telegram_webhook_authorized", return_value=True), \
                 patch.object(factory, "_telegram_load_state", return_value={"chat_id": OWNER}), \
                 patch.object(factory, "_telegram_send_to", side_effect=lambda c, t: sent.append((str(c), t))), \
                 patch.object(factory, "_telegram_send_markup", side_effect=lambda c, t, m=None: sent.append((str(c), t)) or True), \
                 patch.object(factory, "_telegram_api", return_value={"ok": True}), \
                 patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", "w"):
                post = lambda body: asgi_post("/api/integrations/telegram/webhook", body=json.dumps(body).encode())
                post({"update_id": 1, "message": {"message_id": 1, "chat": {"id": int(OWNER), "type": "private"},
                                                  "from": {"id": int(OWNER)}, "text": "/group"}})
                code = next(t for _, t in sent if "Код привязки" in t).split("Код привязки группы: ")[1].split()[0]
                post(group_msg("/pair_group " + code, 2))
                post(group_msg("/discuss что дальше с Relay?", 3))
                self.assertTrue(bridge.status()["paired"])
                q = queue.claim("claude-ec2")
                while q and (q.get("meta") or {}).get("group_thread") != "D-0001":   # skip anything else queued
                    queue.finish(q["id"], "failed", "")
                    q = queue.claim("claude-ec2")
                self.assertEqual(q["meta"], {"group_thread": "D-0001"})
                status, _ = asgi_post("/api/factory/owner-desk/worker/answer", bearer="w",
                                      body=json.dumps({"id": q["id"], "outcome": "answered", "answer": "Сначала тест круга."}).encode())
                self.assertEqual(status, 200)
                group_posts = [t for c, t in sent if c == GROUP]
                self.assertTrue(any(t.startswith("[Claude] D-0001") and "Сначала тест круга" in t for t in group_posts))
                self.assertFalse(any("ответ на" in t for c, t in sent if c == OWNER))   # not duplicated into the DM


if __name__ == "__main__":
    unittest.main(verbosity=2)
