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

    def test_command_words_without_slash_never_create_tickets(self):
        # 2026-11-07: "task R-0034" and a bare "R-…" became junk tickets R-0050 and R-0052.
        before = len(self.store.list())
        for text in ("R-…", "task R-0034", "need R-0052", "R-0052", "done R-0046", "issue 41"):
            result = self.message(text)
            self.assertEqual(result.get("action"), "command_hint", text)
            self.assertIn("/", self.last_message())
        self.assertEqual(len(self.store.list()), before)
        self.message("Build a landing page for R-0034 users")             # a real request still becomes a ticket
        self.assertEqual(len(self.store.list()), before + 1)

    def test_gemini_lane_card_shows_github_facts(self):
        from relay import _t585_lane_text
        text = _t585_lane_text("gemini", {"availability": "unconfigured", "github": {"open_prs": 9, "done_7d": 6, "last_activity_at": "2026-11-06T12:30:00+00:00"}})
        self.assertIn("работает через GitHub", text)
        self.assertIn("открытых PR 9 · закрыто за 7 дней 6", text)
        self.assertIn("не настроен", _t585_lane_text("gemini", {"availability": "unconfigured"}))   # no facts: unchanged

    def test_status_only_shows_verified_telemetry(self):
        r = self.message("/status")
        self.assertEqual(r["action"], "status")
        self.assertIn("Claude: online", self.last_message())
        self.assertIn("ChatGPT: нет автоматической телеметрии", self.last_message())
        self.assertIn("heartbeat", self.last_message())

    def test_tasks_done_24h_requires_recent_completion_event(self):
        from datetime import datetime, timedelta, timezone
        from relay import _team_ticket_counts
        recent = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        with self.store.lock:
            data = self.store._load_unlocked()
            for index, timestamp in enumerate((recent, old), start=2):
                data["tickets"].append({
                    "id": f"R-{index:04d}", "title": "Finished",
                    "status": "done", "created_at": timestamp,
                    "updated_at": timestamp,
                    "execution": {"owner": "claude", "state": "done"},
                    "history": [{"at": timestamp, "action": "status_changed",
                                 "from_status": "in_progress", "to_status": "done"}],
                })
            data["tickets"].append({
                "id": "R-0004", "title": "Unverified done",
                "status": "done", "updated_at": recent,
                "execution": {"owner": "claude", "state": "done"}, "history": [],
            })
            self.store._save_unlocked(data)
        text = _team_ticket_counts(self.store)
        self.assertIn("готово за 24 ч 1", text)
        self.assertNotIn("готово за 24 ч 3", text)

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
        # T-591: /roadmap is the ROADMAP.md view (it used to repeat /tasks); GitHub issues stay under /tasks and /github.
        text = self.last_message()
        self.assertIn("ROADMAP", text)
        # The reply lists real ROADMAP.md tasks; no pinned id, because tasks get closed (T-590 closed 2026-11-23).
        from relay import roadmap_summary
        summary = roadmap_summary(Path(__file__).with_name("ROADMAP.md").read_text(encoding="utf-8"))
        self.assertIn((summary["p0"] or summary["human"] or summary["next"])[0]["id"], text)
        self.assertIn("HUMAN", text)
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
            "/help", "/start", "/pair", "/status", "/tasks", "/relay", "/roadmap", "/task", "/proof",
            "/history", "/github", "/issue", "/battles", "/battle", "/workers", "/operators",
            "/new", "/work", "/done", "/need", "/inbox",
            "/ask",  # #133: handled by the app webhook (owner question queue) before the Relay handler
            "/group",  # #129: handled by the app webhook (group pairing) before the Relay handler
            "/brief",  # #106: handled by the app webhook (morning brief opt-in) before the Relay handler
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


class TestTelegramAssignmentLoop(unittest.TestCase):
    def setUp(self):
        from relay_execution import RelayQueue
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)
        self.sent = []
        self.seq = 0

    def tearDown(self):
        self.tmp.cleanup()

    def tg(self, method, payload=None):
        self.sent.append((method, payload or {}))
        return {"ok": True}

    def send(self, command, chat_id=42, update_id=None):
        self.seq += 1
        uid = update_id if update_id is not None else self.seq
        upd = {"update_id": uid, "message": {"chat": {"id": chat_id, "type": "private"},
               "message_id": uid, "text": command}}
        return relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, self.tg, queue=self.queue)

    def click(self, data, chat_id=42):
        upd = {"callback_query": {"id": "c", "data": data, "message": {"chat": {"id": chat_id}}}}
        return relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, self.tg, queue=self.queue)

    def test_no_claim_until_assignment_and_idempotent_update(self):
        task = self.send("/new Fix Telegram", update_id=901)
        tid = task["ticket_id"]
        self.assertEqual(self.store.get(tid)["execution"]["owner"], "unassigned")
        self.assertIsNone(self.queue.claim("worker-test"))
        self.assertEqual(self.send("/new Fix Telegram", update_id=901)["ticket_id"], tid)
        self.assertEqual(self.store.summary()["total"], 1)
        self.assertEqual(self.click("relay:assign:" + tid + ":claude")["action"], "assigned")
        self.assertEqual(self.click("relay:assign:" + tid + ":claude")["action"], "assigned")
        self.assertEqual(self.click("relay:assign:" + tid + ":gemini")["action"], "assign_refused")
        self.assertEqual(self.queue.claim("worker-test")["id"], tid)
        self.assertEqual(self.click("relay:cancel:" + tid)["action"], "cancel_refused")

    def test_other_executor_and_cancel_stay_truthful(self):
        t = self.send("/new Assign Gemini")
        tid = t["ticket_id"]
        self.click("relay:assign:" + tid + ":gemini")
        self.assertEqual(self.store.get(tid)["execution"]["state"], "queued")
        self.assertIsNone(self.queue.claim("worker-test"))
        self.send("/tasks")
        self.assertIn("gemini: очередь 1", [p["text"] for m,p in self.sent if m=="sendMessage"][-1])

    def test_assignment_buttons_offer_claude_and_honest_gemini_only(self):
        tid = self.send("/new Something")["ticket_id"]
        kb = [p for m, p in self.sent if m == "sendMessage"][-1]["reply_markup"]["inline_keyboard"][0]
        self.assertEqual([b["callback_data"].rsplit(":", 1)[1] for b in kb], ["claude", "gemini"])  # ChatGPT lane taken over (#94)
        self.click("relay:assign:" + tid + ":gemini")
        self.assertIn("не имеет Relay-runner", [p["text"] for m, p in self.sent if m == "sendMessage"][-1])
        self.assertEqual(self.click("relay:retry:" + tid)["action"], "retry_refused")
        self.assertEqual(self.click("relay:cancel:" + tid)["action"], "cancel")
        self.assertEqual(self.store.get(tid)["execution"]["state"], "cancelled")
        self.assertEqual(self.store.get(tid)["status"], "archived")

    def test_foreign_chat_cannot_assign(self):
        tid = self.send("/new Secure task")["ticket_id"]
        count = len(self.sent)
        self.click("relay:assign:" + tid + ":claude", chat_id=93)
        self.assertEqual(len(self.sent), count)
        self.assertEqual(self.store.get(tid)["execution"]["owner"], "unassigned")


if __name__ == "__main__":
    unittest.main()
