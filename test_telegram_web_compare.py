"""T-592: the server compares the Telegram ticket view it delivered with the website read model."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from relay import RelayStore, relay_handle_telegram_update
from relay_execution import RelayQueue
import telegram_web_compare as twc


class TestTelegramWebCompare(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)
        self.log = twc.TelegramViewLog(Path(self.tmp.name) / "telegram_views.json")
        self.sent = []
        self.fail_send = False

    def tearDown(self):
        self.tmp.cleanup()

    def tg(self, method, payload=None):
        if self.fail_send and method == "sendMessage":
            raise RuntimeError("Telegram API sendMessage returned not-ok")
        self.sent.append((method, payload or {}))
        return {"ok": True}

    def click(self, data):
        upd = {"callback_query": {"id": "c", "data": data, "message": {"chat": {"id": 42}}}}
        return relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, self.tg, queue=self.queue,
                                            view_log=self.log)

    def command(self, text):
        upd = {"update_id": 7, "message": {"chat": {"id": 42, "type": "private"}, "message_id": 7, "text": text}}
        return relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, self.tg, queue=self.queue,
                                            view_log=self.log)

    def finished_ticket(self):
        ticket, _ = self.store.create("T-592 compare", "check")
        tid = ticket["id"]
        claimed = self.queue.claim("claude-ec2")
        run = claimed["execution"]["run_id"]
        self.queue.event(tid, "claude-ec2", "running", "started", run_id=run)
        self.queue.event(tid, "claude-ec2", "done", "answered", run_id=run)
        return tid, run

    def site(self, tid):
        return self.queue.view(self.store.get(tid))

    def test_refresh_logs_facts_and_server_says_match(self):
        tid, run = self.finished_ticket()
        self.assertEqual(twc.compare(self.log.latest(tid), self.site(tid))["verdict"], "no_view")
        self.click("relay:ticket:" + tid)
        snap = self.log.latest(tid)
        self.assertEqual(snap["kind"], "detail")
        self.assertEqual(snap["facts"]["stage"], "done")
        self.assertEqual(snap["facts"]["run_id"], run)
        self.assertTrue(snap["shown"]["stage"] and snap["shown"]["run_id"], snap)
        self.assertIsNone(snap["shown"]["last_contact"])  # finished work: last contact is not printed anywhere
        report = twc.compare(snap, self.site(tid))
        self.assertEqual(report["verdict"], "match", report)
        self.assertEqual([r["field"] for r in report["rows"]], list(twc.FIELDS))
        # The log never stores the chat id or the message text.
        raw = (Path(self.tmp.name) / "telegram_views.json").read_text(encoding="utf-8")
        self.assertNotIn('"42"', raw.replace(" ", ""))
        self.assertNotIn("chat", raw)
        self.assertNotIn("answered", raw)

    def test_task_command_also_logs(self):
        tid, _ = self.finished_ticket()
        self.command("/task " + tid)
        self.assertEqual(self.log.latest(tid)["ticket_id"], tid)

    def test_failed_delivery_is_not_logged(self):
        tid, _ = self.finished_ticket()
        self.fail_send = True
        with self.assertRaises(RuntimeError):
            self.click("relay:ticket:" + tid)
        self.assertIsNone(self.log.latest(tid))

    def test_change_after_the_message_is_outdated_not_a_bug(self):
        ticket, _ = self.store.create("running task", "x")
        tid = ticket["id"]
        run = self.queue.claim("claude-ec2")["execution"]["run_id"]
        self.queue.event(tid, "claude-ec2", "running", "started", run_id=run)
        self.click("relay:ticket:" + tid)
        snap = self.log.latest(tid)
        self.assertTrue(snap["shown"]["last_contact"], snap)  # active work prints the last contact
        self.assertEqual(twc.compare(snap, self.site(tid))["verdict"], "match")
        time.sleep(1.1)
        self.queue.event(tid, "claude-ec2", "done", "finished", run_id=run)
        report = twc.compare(snap, self.site(tid))
        self.assertEqual(report["verdict"], "outdated", report)
        self.assertFalse(next(r for r in report["rows"] if r["field"] == "stage")["match"])

    def test_render_bug_is_a_mismatch(self):
        tid, run = self.finished_ticket()
        view = self.site(tid)
        later = "2999-01-01T00:00:00+00:00"  # Telegram view newer than every ticket change
        snap = {"ticket_id": tid, "at": later, "kind": "detail",
                "facts": {"stage": "running", "run_id": run, "last_contact": ""}, "shown": {"stage": True, "run_id": True}}
        self.assertEqual(twc.compare(snap, view)["verdict"], "mismatch")
        hidden = {**snap, "facts": {"stage": "done", "run_id": run, "last_contact": twc.ticket_facts(view)["last_contact"]},
                  "shown": {"stage": True, "run_id": False}}
        report = twc.compare(hidden, view)
        self.assertEqual(report["verdict"], "mismatch")
        self.assertIn("not_shown:run_id", report["problems"])

    def test_worker_notice_logged_by_route_hook(self):
        tid, _ = self.finished_ticket()
        entry = self.log.record(self.site(tid), "notice", "🏁 " + tid + " · Claude закончил работу")
        self.assertEqual(entry["kind"], "notice")
        self.assertIsNone(self.log.latest(tid))  # the comparison uses only full detail views
        self.assertEqual(self.log.latest(tid, kind="notice")["ticket_id"], tid)
        self.assertIsNone(self.log.record({"id": ""}, "detail", "x"))
        self.assertIsNone(self.log.record(self.site(tid), "other", "x"))

    def test_owner_confirmation_drives_t592_status(self):
        self.assertEqual(twc.owner_status(None, False)["state"], "blocked")
        self.assertEqual(twc.owner_status(None, True)["detail_key"], "compare_ready")
        tid, _ = self.finished_ticket()
        self.click("relay:ticket:" + tid)
        report = twc.compare(self.log.latest(tid), self.site(tid))
        with self.assertRaises(ValueError):
            self.log.confirm(tid, "maybe", report, report["key"])
        self.log.confirm(tid, "mismatch", report, report["key"])
        self.assertEqual(twc.owner_status(self.log.latest_confirmation(), True, report)["detail_key"], "compare_owner_mismatch")
        outdated = {**report, "verdict": "outdated"}
        outdated["key"] = twc.report_key(outdated)
        self.log.confirm(tid, "match", outdated, outdated["key"])
        self.assertEqual(twc.owner_status(self.log.latest_confirmation(), True, outdated)["state"], "todo")  # server must agree
        self.log.confirm(tid, "match", report, report["key"])
        status = twc.owner_status(self.log.latest_confirmation(), True, report)
        self.assertEqual((status["state"], status["args"]["ticket"]), ("done", tid))

    def test_stale_card_answer_is_refused(self):
        """Codex review #416: the answer is bound to the card the owner saw."""
        ticket, _ = self.store.create("running task", "x")
        tid = ticket["id"]
        run = self.queue.claim("claude-ec2")["execution"]["run_id"]
        self.queue.event(tid, "claude-ec2", "running", "started", run_id=run)
        self.click("relay:ticket:" + tid)
        shown = twc.compare(self.log.latest(tid), self.site(tid))
        self.assertEqual(shown["verdict"], "match")
        time.sleep(1.1)
        self.queue.event(tid, "claude-ec2", "done", "finished", run_id=run)  # ticket changes before the owner clicks
        current = twc.compare(self.log.latest(tid), self.site(tid))
        self.assertNotEqual(shown["key"], current["key"])
        with self.assertRaises(twc.StaleComparison):
            self.log.confirm(tid, "match", current, shown["key"])
        with self.assertRaises(twc.StaleComparison):
            self.log.confirm(tid, "match", current, "")
        self.assertIsNone(self.log.latest_confirmation())
        self.click("relay:ticket:" + tid)  # Telegram refreshed too: also a new card
        self.assertNotEqual(twc.compare(self.log.latest(tid), self.site(tid))["key"], current["key"])

    def test_confirmed_match_reopens_after_ticket_change(self):
        """Codex review #416: a confirmed match no longer counts once the comparison changes."""
        ticket, _ = self.store.create("running task", "x")
        tid = ticket["id"]
        run = self.queue.claim("claude-ec2")["execution"]["run_id"]
        self.queue.event(tid, "claude-ec2", "running", "started", run_id=run)
        self.click("relay:ticket:" + tid)
        shown = twc.compare(self.log.latest(tid), self.site(tid))
        self.log.confirm(tid, "match", shown, shown["key"])
        self.assertEqual(twc.owner_status(self.log.latest_confirmation(), True, shown)["state"], "done")
        time.sleep(1.1)
        self.queue.event(tid, "claude-ec2", "done", "finished", run_id=run)
        now = twc.compare(self.log.latest(tid), self.site(tid))
        self.assertEqual(now["verdict"], "outdated")
        self.assertEqual(twc.owner_status(self.log.latest_confirmation(), True, now)["state"], "todo")
        self.assertEqual(twc.owner_status(self.log.latest_confirmation(), True, None)["state"], "todo")

    def test_confirmation_is_scoped_to_its_ticket(self):
        """Codex review #416: a report for ticket B never carries ticket A's confirmation."""
        a, _ = self.finished_ticket()
        b, _ = self.finished_ticket()
        self.click("relay:ticket:" + a)
        self.click("relay:ticket:" + b)
        ra = twc.compare(self.log.latest(a), self.site(a))
        rb = twc.compare(self.log.latest(b), self.site(b))
        conf = self.log.confirm(a, "match", ra, ra["key"])
        self.assertEqual(twc.confirmation_for(conf, ra), conf)
        self.assertIsNone(twc.confirmation_for(conf, rb))
        self.assertEqual(twc.owner_status(conf, True, rb)["state"], "todo")

    def test_log_is_bounded_and_survives_garbage(self):
        path = Path(self.tmp.name) / "telegram_views.json"
        path.write_text("not json", encoding="utf-8")
        self.assertIsNone(self.log.latest())
        tid, _ = self.finished_ticket()
        for _ in range(twc.MAX_VIEWS + 5):
            self.log.record(self.site(tid), "detail", "done")
        self.assertEqual(len(json.loads(path.read_text(encoding="utf-8"))["views"]), twc.MAX_VIEWS)


if __name__ == "__main__":
    unittest.main(verbosity=1)
