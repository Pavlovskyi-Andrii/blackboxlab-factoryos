"""Deterministic Telegram Relay tests; no live tokens, network, API spend or messages."""
import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from relay import RelayStore, relay_github_snapshot, relay_handle_telegram_update


class TestRelayTelegram(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.store.create("Check FactoryOS runner", source={"source_key": "github:40", "url": "https://github.com/org/repo/issues/40"}, created_by="ChatGPT")
        self.store.set_status("R-0001", "in_progress", actor="Claude", note="Investigating CI")
        self.calls = []
        self.pair = lambda: {"chat_id": "42"}
        self.lanes = lambda: {"claude": {"online": True, "state": "running", "active_task_id": "T-41", "heartbeat_age_seconds": 2}, "gemini": {"online": False, "state": "offline"}}
        self.github = lambda: {"available": True, "repo": "org/repo", "checked_at": "2026-10-28T09:00:00Z", "issues": [{"number": 41, "title": "Relay Telegram", "state": "open"}], "pulls": [{"number": 42, "sha": "abc123456", "state": "open", "ci": "passed", "url": "https://github.com/org/repo/pull/42"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def tg(self, method, payload=None):
        self.calls.append((method, payload or {}))
        return {"ok": True}

    def message(self, command, chat="42"):
        result = relay_handle_telegram_update(
            {"update_id": len(self.calls) + 1, "message": {"chat": {"id": int(chat), "type": "private"}, "text": command, "message_id": len(self.calls) + 1}},
            self.store, self.pair, self.tg, self.lanes, self.github)
        return result

    def last_message(self):
        return [payload["text"] for method, payload in self.calls if method == "sendMessage"][-1]

    def test_status_only_shows_verified_telemetry(self):
        r = self.message("/status")
        self.assertEqual(r["action"], "status")
        self.assertIn("Claude: online", self.last_message())
        self.assertIn("ChatGPT: нет автоматической телеметрии", self.last_message())
        self.assertIn("heartbeat", self.last_message())

    def test_tasks_include_github_and_executor(self):
        self.message("/tasks")
        message = self.last_message()
        self.assertIn("R-0001", message)
        self.assertIn("#41", message)
        self.assertIn("Claude: online", message)

    def test_history_and_detail_are_real_multiline(self):
        self.message("/history")
        self.assertIn("status_changed", self.last_message())
        self.message("/task R-0001")
        self.assertIn("\nИстория:\n", self.last_message())
        self.assertIn("Claude", self.last_message())

    def test_github_verified_ci_and_buttons(self):
        self.message("/github")
        self.assertIn("CI passed", self.last_message())
        self.assertIn("abc1234", self.last_message())
        callback = {"callback_query": {"id": "q1", "data": "relay:overview:github", "message": {"chat": {"id": 42}}}}
        r = relay_handle_telegram_update(callback, self.store, self.pair, self.tg, self.lanes, self.github)
        self.assertEqual(r["action"], "github")
        self.assertEqual(self.calls[-2][0], "answerCallbackQuery")

    def test_roadmap_is_displayed_and_not_converted_to_ticket(self):
        count = self.store.summary()["total"]
        self.message("/roadmap")
        self.assertIn("#41", self.last_message())
        self.assertEqual(count, self.store.summary()["total"])

    def test_unknown_or_unpaired_chat_cannot_read(self):
        self.message("/github", chat="93")
        self.assertEqual(self.calls, [])
        self.message("/task R-9999")
        self.assertIn("не найдена", self.last_message())

    def test_git_failure_remains_unknown_without_token_leak(self):
        self.assertFalse(relay_github_snapshot("not-a-repo!")["available"])
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("url", 403, "denied", {}, None)):
            result = relay_github_snapshot("org/repo", "secret-value")
        self.assertFalse(result["available"])
        self.assertNotIn("secret-value", str(result))

    def test_github_snapshot_checks_commit_ci(self):
        issues = [{"number": 41, "title": "Relay", "state": "open", "html_url": "https://github.com/org/repo/issues/41"}]
        prs = [{"number": 42, "title": "Relay PR", "state": "open", "html_url": "https://github.com/org/repo/pull/42", "head": {"sha": "abc123"}}]
        check_runs = {"check_runs": [{"status": "completed", "conclusion": "success"}]}

        class FakeResponse:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.value).encode()

        def fake_open(request, timeout=5):
            url = request.full_url
            if "/check-runs" in url: return FakeResponse(check_runs)
            if "/pulls?" in url: return FakeResponse(prs)
            if "/issues?" in url: return FakeResponse(issues)
            raise AssertionError(url)

        with patch("urllib.request.urlopen", side_effect=fake_open):
            result = relay_github_snapshot("org/repo", "token")
        self.assertTrue(result["available"])
        self.assertEqual(result["pulls"][0]["ci"], "passed")
        self.assertEqual(result["issues"][0]["number"], 41)


if __name__ == "__main__":
    unittest.main()
