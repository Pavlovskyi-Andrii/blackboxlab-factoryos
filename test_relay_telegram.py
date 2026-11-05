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

    def test_github_issue_detail(self):
        self.message("/task #41")
        self.assertIn("GitHub #41", self.last_message())
        self.assertIn("open (проверено", self.last_message())

    def test_github_issue_requires_available_open_snapshot(self):
        """Cached or failed GitHub snapshots must not claim a verified open issue."""
        for snapshot in (
            {"available": False, "issues": [{"number": 41, "title": "Old issue", "state": "open"}]},
            {"available": True, "issues": [{"number": 41, "title": "Closed issue", "state": "closed"}]},
        ):
            with self.subTest(snapshot=snapshot):
                self.calls.clear()
                relay_handle_telegram_update(
                    {"update_id": 100, "message": {"chat": {"id": 42, "type": "private"},
                                                   "text": "/task #41"}},
                    self.store, self.pair, self.tg, self.lanes, lambda: snapshot)
                self.assertIn("Статус неизвестен", self.last_message())
                self.assertNotIn("open (проверено", self.last_message())

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

    def test_help_command_ru_uk_en(self):
        for lang, phrase in (("ru", "Справка"), ("uk", "Довідка"), ("en", "Show help")):
            result = relay_handle_telegram_update(
                {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "text": "/help", "from": {"language_code": lang}}},
                self.store, self.pair, self.tg, self.lanes, self.github
            )
            self.assertEqual(result["action"], "help")
            self.assertIn(phrase, self.last_message())

    def test_start_without_code_shows_help(self):
        result = relay_handle_telegram_update(
            {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "text": "/start", "from": {"language_code": "ru"}}},
            self.store, self.pair, self.tg, self.lanes, self.github
        )
        self.assertEqual(result["action"], "help")
        self.assertIn("/help", self.last_message())

    def test_start_with_code_returns_none(self):
        result = relay_handle_telegram_update(
            {"update_id": 1, "message": {"chat": {"id": 42, "type": "private"}, "text": "/start 123456"}},
            self.store, self.pair, self.tg, self.lanes, self.github
        )
        self.assertIsNone(result)

    def test_all_commands_in_help_and_vice_versa(self):
        import re
        from relay import _help_text
        handled_commands = {
            "/help", "/start", "/pair", "/status", "/tasks", "/relay", "/roadmap", "/task",
            "/history", "/github", "/issue", "/battles", "/battle", "/workers", "/operators",
            "/new", "/work", "/done", "/need", "/inbox"
        }
        for lang in ("ru", "uk", "en"):
            text = _help_text(lang)
            help_commands = set(re.findall(r"^/([a-z0-9_]+)", text, re.MULTILINE))
            help_commands = {"/" + cmd for cmd in help_commands}
            self.assertEqual(help_commands, handled_commands, f"Mismatch in lang {lang}")

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
        commits = [{"sha": "abc123", "commit": {"message": "Implement Relay", "author": {"date": "2026-10-28T09:00:00Z", "name": "Claude"}}, "html_url": "https://github.com/org/repo/commit/abc123"}]

        class FakeResponse:
            def __init__(self, value): self.value = value
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(self.value).encode()

        def fake_open(request, timeout=5):
            url = request.full_url
            if "/check-runs" in url: return FakeResponse(check_runs)
            if "/commits?" in url: return FakeResponse(commits)
            if "/pulls?" in url: return FakeResponse(prs)
            if "/issues?" in url: return FakeResponse(issues)
            raise AssertionError(url)

        with patch("urllib.request.urlopen", side_effect=fake_open):
            result = relay_github_snapshot("org/repo", "token")
        self.assertTrue(result["available"])
        self.assertEqual(result["pulls"][0]["ci"], "passed")
        self.assertEqual(result["issues"][0]["number"], 41)
        self.assertEqual(result["commits"][0]["message"], "Implement Relay")


class TestTelegramOperatorLanes(unittest.TestCase):
    """T-586: rides this existing CI step (worker token lacks `workflow` scope)."""

    def test_operator_lane_callbacks(self):
        import test_telegram_operator_lanes as t586
        t586.pure_checks()

    def test_webhook_operator_lanes(self):
        import test_telegram_operator_lanes as t586
        t586.app_checks()


class TestTelegramBattles(unittest.TestCase):
    """T-587: rides this existing CI step (worker token lacks `workflow` scope)."""

    def test_battle_callbacks(self):
        import test_telegram_battles as t587
        t587.pure_checks()

    def test_webhook_battles(self):
        import test_telegram_battles as t587
        t587.app_checks()


if __name__ == "__main__":
    unittest.main()
