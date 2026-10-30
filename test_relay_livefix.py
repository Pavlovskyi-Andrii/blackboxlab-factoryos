"""P0 regression: honest Telegram worker status and queue recovery."""
import tempfile
import unittest
from pathlib import Path

from relay import RelayStore, _relay_status_text, _relay_tasks_text
from relay_execution import RelayQueue


class TestTelegramLiveFix(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.temp.name) / "tickets.json")
        self.queue = RelayQueue(self.store, stale_seconds=60)

    def tearDown(self):
        self.temp.cleanup()

    def test_status_exposes_unclaimable_open_ticket(self):
        t, _ = self.store.create("Already investigated")
        self.store.set_status(t["id"], "in_progress")
        # Ticket counts as open but worker cannot claim unless it is inbox.
        text = _relay_status_text(self.store, lambda: {}, self.queue)
        self.assertIn("Очередь: 0", text)
        self.assertIn("работа: 0", text)
        self.assertIn("Открыты, но не в очереди", text)
        self.assertIn("/work " + t["id"], text)
        self.assertIsNone(self.queue.claim("ec2"))

    def test_blocked_heartbeat_is_not_running_task(self):
        text = _relay_status_text(self.store, lambda: {"claude": {
            "online": True, "active_task_id": "", "last_task_id": "T-590",
            "task_state": "blocked", "heartbeat_age_seconds": 3}}, self.queue)
        self.assertIn("Claude: online", text)
        self.assertIn("последняя T-590: blocked (не выполняется)", text)
        self.assertNotIn("выполняет T-590", text)
        tasks = _relay_tasks_text(self.store, lambda: {"claude": {
            "online": True, "active_task_id": "", "last_task_id": "T-590", "task_state": "blocked"}}, None)
        self.assertIn("не выполняется", tasks)

    def test_stale_claim_no_automatic_retry(self):
        first, _ = self.store.create("Old stuck task")
        self.assertEqual(self.queue.claim("ec2")["id"], first["id"])
        with self.store.lock:
            d = self.store._load_unlocked()
            d["tickets"][0]["execution"]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
            self.store._save_unlocked(d)
        other, _ = self.store.create("New task")
        claimed = self.queue.claim("ec2")
        self.assertEqual(claimed["id"], other["id"])
        self.assertEqual(self.store.get(first["id"])["execution"]["state"], "blocked")
        self.assertEqual(self.store.get(first["id"])["status"], "need_you")
        self.assertEqual(self.store.get(first["id"])["history"][-1]["action"], "stale_released")
        self.assertIsNone(self.queue.claim("ec2"))
        self.assertEqual(self.queue.claim("another-worker"), None)


if __name__ == "__main__":
    unittest.main()
