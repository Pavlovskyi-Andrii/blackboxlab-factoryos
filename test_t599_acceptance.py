"""T-599 acceptance: assignment is not execution (spec docs/handoff/T-599_VERIFIED_EXECUTION.md §3, scenarios A–E).

One deterministic suite that joins the slices end to end: ROADMAP text -> server claim (run_id) -> worker
events -> lane board (web/API) -> Telegram /status. No network, no Claude, no paid calls.
The slice suites (test_roadmap_claims, test_lane_board, test_issue_intake, autopilot parking_regression)
cover each part in depth; this file checks that the parts agree with each other.
"""
import json
import tempfile
import time
import unittest
from pathlib import Path

from autopilot import autopilot as ap
from lane_board import TEXT, build_lane_board
from relay import RelayStore, relay_auto_intake_issues, relay_handle_telegram_update
from relay_execution import RelayQueue

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
OWNER = "Pavlovskyi-Andrii"
CHAT = "4242"
ROADMAP_TEXT = """# Roadmap

## P0
- [ ] T-951 First Claude task
  Owner: claude
- [ ] T-952 Second Claude task
  Owner: claude
- [ ] T-953 Shared task
  Owner: any
- [ ] T-954 ChatGPT task
  Owner: chatgpt
- [ ] [HUMAN] T-955 Owner pairing
"""


class AcceptanceCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.roadmap = self.dir / "ROADMAP.md"
        self.roadmap.write_text(ROADMAP_TEXT, encoding="utf-8")
        self.relay = self.dir / "relay.json"
        self.store = RelayStore(self.relay)
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def tasks(self):
        return ap.parse_roadmap(self.roadmap)

    def board(self, online=True):
        beats = {"claude": time.time() - 5} if online else {}
        return build_lane_board(self.tasks(), self.store.list(limit=500), beats, stale_seconds=self.queue.stale_seconds)

    def claim(self, task, worker="claude-ec2", lane="claude"):
        target = next(t for t in self.tasks() if t["id"] == task)
        return self.queue.claim_roadmap(worker, lane, task, target["title"], target["owner"])

    def emit(self, ticket, stage, note="", evidence=None, worker="claude-ec2", run_id=None):
        run = run_id or ticket["execution"]["run_id"]
        return self.queue.event(ticket["id"], worker, stage, note or stage, evidence or {},
                                run_id=run, event_id=f"{run}:{stage}:{len(note)}")

    def telegram(self, board, command="/status", lang="en"):
        sent = []
        update = {"message": {"chat": {"id": int(CHAT), "type": "private"}, "text": command,
                              "from": {"language_code": lang}}}
        relay_handle_telegram_update(update, self.store, lambda: {"chat_id": CHAT},
                                     lambda method, payload=None: sent.append((method, payload)) or {"ok": True},
                                     queue=self.queue, lane_board_provider=lambda: board)
        return next(p["text"] for m, p in sent if m == "sendMessage")

    def row(self, board, task):
        return next(t for t in board["tasks"] if t["id"] == task)

    def assert_same_task_and_stage(self, board, task, stage, state="working"):
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["stage"]), (state, task, stage))
        for lang in ("en", "uk", "ru"):
            t = TEXT[lang]
            text = self.telegram(board, "/status", lang)
            self.assertIn(f"Claude: {t[state]} · {t['task']} {task} · {t['stage']} {stage}", text, (lang, stage))


class TestA_NormalTask(AcceptanceCase):
    def test_claim_to_done_web_and_telegram_agree_at_every_stage(self):
        target = ap.next_safe_task(self.roadmap, "claude")
        self.assertEqual(target["id"], "T-951")
        self.assertEqual(self.row(self.board(), "T-951")["claim"], "assigned_not_claimed")
        ticket, reason = self.claim("T-951")
        self.assertEqual(reason, "")
        self.assertTrue(ticket["execution"]["run_id"].startswith("run-"))
        self.assert_same_task_and_stage(self.board(), "T-951", "claimed")
        for stage, evidence in (("running", {"branch": "autopilot/aws-worker"}),
                                ("checkpoint", {"checks": "started"}),
                                ("checkpoint", {"checks": "passed"}),
                                ("committed", {"commit": "ab" * 20}),
                                ("pushed", {"pushed": True})):
            self.emit(ticket, stage, f"{stage} {json.dumps(evidence)}", evidence)
            board = self.board()
            self.assert_same_task_and_stage(board, "T-951", stage)
            self.assertEqual(self.row(board, "T-951")["column"], "in_progress")
        self.emit(ticket, "done", "done · checks: smoke_tests.py")
        board = self.board()
        # Worker "done" is Review until the ROADMAP checkbox actually closes; never "done" on its word alone.
        self.assertEqual(self.row(board, "T-951")["column"], "review")
        self.assertEqual(board["lanes"]["claude"]["state"], "idle")
        self.roadmap.write_text(ROADMAP_TEXT.replace("- [ ] T-951", "- [x] T-951"), encoding="utf-8")
        self.assertEqual(self.row(self.board(), "T-951")["column"], "done")
        actions = [h["action"] for h in self.store.get(ticket["id"])["history"]]
        self.assertEqual(actions, ["queued", "claimed", "running", "checkpoint", "checkpoint", "committed", "pushed", "done"])


class TestB_Conflict(AcceptanceCase):
    def test_exactly_one_lane_wins_and_foreign_lane_never_claims(self):
        first, _ = self.claim("T-953", "claude-ec2", "claude")
        second, reason = self.claim("T-953", "gpt-runner", "chatgpt")
        self.assertIsNotNone(first)
        self.assertIsNone(second)
        self.assertIn("already claimed", reason)
        # The refusal is journalled on the ticket once per (run, worker), even if the loser keeps retrying.
        self.claim("T-953", "gpt-runner", "chatgpt")
        rejected = [h for h in self.store.get(first["id"])["history"] if h["action"] == "claim_rejected"]
        self.assertEqual([(h["actor"], h["run_id"]) for h in rejected], [("gpt-runner", first["execution"]["run_id"])])
        self.assertEqual(self.store.get(first["id"])["execution"]["worker_id"], "claude-ec2")
        foreign, reason = self.claim("T-954", "claude-ec2", "claude")
        self.assertIsNone(foreign)
        self.assertIn("lane chatgpt", reason)
        board = self.board()
        self.assertEqual(self.row(board, "T-953")["lane"], "claude")
        self.assertEqual(self.row(board, "T-954")["claim"], "assigned_not_claimed")
        self.assertEqual(board["lanes"]["chatgpt"]["state"], "offline")
        # The worker's own selection never offers another lane's task either.
        self.assertNotIn("T-954", [t["id"] for t in self.tasks() if ap.selectable(t, self.tasks(), "claude")])


class TestC_Restart(AcceptanceCase):
    def test_state_survives_restart_and_stale_run_waits_for_retry(self):
        ticket, _ = self.claim("T-951")
        self.emit(ticket, "running")
        self.queue = RelayQueue(RelayStore(self.relay))
        self.store = self.queue.store
        self.assert_same_task_and_stage(self.board(), "T-951", "running")
        again, reason = self.claim("T-951")
        self.assertIsNone(again)
        self.assertIn("already running", reason)
        with self.store.lock:
            data = self.store._load_unlocked()
            data["tickets"][0]["execution"]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
            self.store._save_unlocked(data)
        board = self.board()
        self.assertEqual(board["lanes"]["claude"]["state"], "stale")
        self.assertEqual(self.row(board, "T-951")["column"], "blocked")
        stale, reason = self.claim("T-951")
        self.assertIsNone(stale)
        self.assertIn("owner Retry", reason)


class TestD_Blocked(AcceptanceCase):
    def test_blocked_reason_visible_and_queue_moves_on(self):
        ticket, _ = self.claim("T-951")
        self.emit(ticket, "running")
        self.emit(ticket, "blocked", "T-951: committed locally, push failed; worker retries the push only")
        board = self.board()
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"]), ("blocked", "T-951"))
        self.assertIn("push failed", lane["reason"])
        self.assertEqual(self.row(board, "T-951")["column"], "blocked")
        for lang in ("en", "uk", "ru"):
            text = self.telegram(board, "/status", lang)
            self.assertIn(TEXT[lang]["reason"] + ": T-951: committed locally, push failed", text)
        # The parked task does not stall the queue: the next safe task is selected and claimed.
        nxt = ap.next_safe_task(self.roadmap, "claude", skip={"T-951"})
        self.assertEqual(nxt["id"], "T-952")
        ticket2, reason = self.claim(nxt["id"])
        self.assertEqual(reason, "")
        self.emit(ticket2, "running")
        self.assert_same_task_and_stage(self.board(), "T-952", "running")
        # A reason is only shown for a blocked lane, never for a working one.
        self.assertEqual(self.board()["lanes"]["claude"]["reason"], "")


class TestE_Freshness(AcceptanceCase):
    def test_new_roadmap_task_and_owner_issue_appear_assigned_not_claimed(self):
        self.roadmap.write_text(ROADMAP_TEXT + "- [ ] T-956 Added later\n  Owner: claude\n", encoding="utf-8")
        board = self.board()
        self.assertEqual(self.row(board, "T-956")["owner"], "claude")
        self.assertIn("T-956", board["lanes"]["claude"]["assigned_not_claimed"])
        issue = {"number": 777, "title": "Owner request", "body": "Owner: Claude\nDo the thing", "state": "open",
                 "html_url": f"https://github.com/{REPO}/issues/777", "user": {"login": OWNER}}
        foreign = dict(issue, number=778, user={"login": "someone-else"})
        result = relay_auto_intake_issues(self.queue, REPO, "", fetch=lambda path: [issue, foreign])
        self.assertEqual([x["issue"] for x in result["imported"]], [777])
        board = self.board()
        issue_rows = [t for t in board["tasks"] if t["kind"] == "issue"]
        self.assertEqual(len(issue_rows), 1)
        self.assertEqual((issue_rows[0]["lane"], issue_rows[0]["claim"]), ("claude", "assigned_not_claimed"))
        self.assertIn(issue_rows[0]["id"], board["lanes"]["claude"]["assigned_not_claimed"])
        text = self.telegram(board, "/tasks", "en")
        self.assertIn("T-956", text)


class TestF_NoFabricatedActivity(AcceptanceCase):
    def test_assigned_tasks_without_events_never_running_and_wrong_run_id_rejected(self):
        board = self.board()
        self.assertEqual(board["counts"]["in_progress"], 0)
        self.assertTrue(all(t["claim"] != "claimed" for t in board["tasks"]))
        self.assertEqual(board["lanes"]["claude"]["state"], "idle")
        for lang in ("en", "uk", "ru"):
            self.assertNotIn(TEXT[lang]["working"], self.telegram(board, "/status", lang).split("ChatGPT")[0])
        ticket, _ = self.claim("T-951")
        with self.assertRaises(ValueError):
            self.emit(ticket, "running", run_id="run-forged")
        with self.assertRaises(ValueError):
            self.emit(ticket, "running", worker="intruder")
        self.assertEqual(self.store.get(ticket["id"])["execution"]["state"], "claimed")
        self.assertNotIn("running", [h["action"] for h in self.store.get(ticket["id"])["history"]])


class TestRealRoadmap(unittest.TestCase):
    def test_no_open_task_lacks_owner(self):
        unowned = [t["id"] for t in ap.parse_roadmap(ap.ROADMAP) if not t["done"] and not t["human"] and not t["owner"]]
        self.assertEqual(unowned, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
