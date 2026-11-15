"""T-591: the owner's live-acceptance verdict (`/proof`, GET /api/relay/{id}/acceptance) from durable server facts.

Offline: a fake Telegram API and notifier, a tempfile Relay store and the real Relay routes called directly
(no TestClient). Nothing calls Telegram, GitHub or Render; nothing here may turn a missing fact into evidence.
"""
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI, HTTPException

from relay import (RelayStore, RelayWorkerClaimRequest, RelayWorkerEventRequest, _roadmap_text, install_relay_routes,
                   relay_handle_telegram_update, roadmap_summary)
from relay_acceptance import acceptance_report, acceptance_text
from relay_execution import RelayQueue

OWNER = {"role": "owner", "email": "owner@example.test"}
CHAT = "4242"


class Server:
    """One server process over the shared relay.json: routes + a Telegram notifier that reports delivery."""

    def __init__(self, path: Path, delivered=True, identity=OWNER):
        self.store = RelayStore(path)
        self.queue = RelayQueue(self.store)
        self.notices = []
        self.delivered = delivered
        app = FastAPI()
        install_relay_routes(app, self.store, lambda r: identity, queue=self.queue, authorize_worker=lambda r: True,
                             notify_owner=self.notify)
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        self.sent = []

    def notify(self, text):
        self.notices.append(text)
        return self.delivered

    def tg(self, method, payload=None):
        self.sent.append((method, payload or {}))
        return {"ok": True}

    def telegram(self, text, update_id, chat=CHAT, lang="ru"):
        update = {"update_id": update_id, "message": {"chat": {"id": int(chat), "type": "private"}, "message_id": update_id,
                                                      "from": {"language_code": lang}, "text": text}}
        return relay_handle_telegram_update(update, self.store, lambda: {"chat_id": CHAT}, self.tg, queue=self.queue)

    def claim(self, worker="claude-ec2"):
        return self.h[("POST", "/api/relay/worker/claim")](RelayWorkerClaimRequest(worker_id=worker), None)["ticket"]

    def event(self, tid, stage, run_id, note="", evidence=None, event_id="", worker="claude-ec2"):
        return self.h[("POST", "/api/relay/worker/event")](RelayWorkerEventRequest(
            ticket_id=tid, worker_id=worker, stage=stage, note=note or stage, evidence=evidence or {}, run_id=run_id,
            event_id=event_id or f"{run_id}-{stage}"), None)

    def acceptance(self, tid, lang="ru"):
        return self.h[("GET", "/api/relay/{ticket_id}/acceptance")](tid, None, lang)

    def last_text(self):
        return [p["text"] for m, p in self.sent if m == "sendMessage"][-1]


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "relay.json"
        self.s = Server(self.path)

    def tearDown(self):
        self.dir.cleanup()

    def intake(self, update_id=101):
        result = self.s.telegram("T-591 приёмка: ответь текущим UTC-временем, код не меняй", update_id)
        return result["ticket_id"]

    def full_run(self, note="Ответ: 2026-11-15T10:00Z; код не менялся"):
        tid = self.intake()
        run_id = self.s.claim()["execution"]["run_id"]
        self.s.event(tid, "running", run_id)
        self.s.event(tid, "done", run_id, note=note)
        return tid, run_id

    def test_full_live_chain_is_verified_with_ids_and_utc_timestamps(self):
        tid, run_id = self.full_run()
        report = self.s.acceptance(tid)
        self.assertEqual(report["status"], "VERIFIED", report)
        self.assertEqual((report["ticket_id"], report["run_id"], report["worker_id"]), (tid, run_id, "claude-ec2"))
        self.assertTrue(all(row["ok"] and row["at"] for row in report["stages"] if row["stage"] != "single_ticket"))
        self.assertIn(run_id, report["text"])
        self.assertIn("UTC", report["text"])
        self.assertIn("ПОДТВЕРЖДЕНО", report["text"])
        # the receipt is a history fact, not a status change
        receipt = [e for e in self.s.store.get(tid)["history"] if e["action"] == "owner_notified"]
        self.assertEqual([(e["stage"], e["run_id"]) for e in receipt], [("running", run_id), ("done", run_id)])

    def test_proof_command_answers_in_the_paired_chat_only(self):
        tid, _ = self.full_run()
        result = self.s.telegram(f"/proof {tid}", 900, lang="en")
        self.assertEqual((result["action"], result["status"]), ("proof", "VERIFIED"))
        self.assertIn("VERIFIED by the server", self.s.last_text())
        before = len(self.s.sent)
        self.assertIsNone(self.s.telegram(f"/proof {tid}", 901, chat="999"))
        self.assertEqual(len(self.s.sent), before)
        self.assertEqual(self.s.telegram("/proof", 902)["action"], "proof_help")
        self.assertEqual(len(self.s.store.list()), 1)           # commands never become tickets

    def test_undelivered_notice_is_not_evidence(self):
        self.s = Server(self.path, delivered=False)
        tid, _ = self.full_run()
        report = self.s.acceptance(tid)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertEqual(report["missing"], ["owner_notified"])
        self.assertFalse([e for e in self.s.store.get(tid)["history"] if e["action"] == "owner_notified"])

    def test_non_telegram_ticket_is_not_live_telegram_acceptance(self):
        ticket, _ = self.s.store.create("Web task", source={"channel": "factoryos", "source_key": "web:1"})
        run_id = self.s.claim()["execution"]["run_id"]
        self.s.event(ticket["id"], "running", run_id)
        self.s.event(ticket["id"], "done", run_id, note="ok")
        report = self.s.acceptance(ticket["id"])
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertIn("telegram_intake", report["missing"])

    def test_queued_only_and_blocked_runs_are_not_done(self):
        tid = self.intake()
        report = self.s.acceptance(tid)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertEqual(set(report["missing"]), {"claimed", "running", "final", "result", "owner_notified"})
        run_id = self.s.claim()["execution"]["run_id"]
        self.s.event(tid, "running", run_id)
        self.s.event(tid, "blocked", run_id, note="needs owner login")
        report = self.s.acceptance(tid)
        self.assertEqual(report["status"], "UNVERIFIED")
        self.assertTrue(any("blocked" in p for p in report["problems"]))

    def test_a_retry_counts_only_the_current_run(self):
        tid = self.intake()
        first = self.s.claim()["execution"]["run_id"]
        self.s.event(tid, "running", first)
        self.s.event(tid, "failed", first, note="tests failed")
        self.s.queue.enqueue(tid, actor="telegram")
        second = self.s.claim()["execution"]["run_id"]
        self.assertNotEqual(first, second)
        report = self.s.acceptance(tid)
        self.assertEqual(report["run_id"], second)
        self.assertIn("running", report["missing"])              # the old run's running/final never count
        self.s.event(tid, "running", second)
        self.s.event(tid, "done", second, note="fixed")
        self.assertEqual(self.s.acceptance(tid)["status"], "VERIFIED")

    def test_telegram_redelivery_keeps_one_ticket_and_a_forged_duplicate_is_flagged(self):
        tid = self.intake(update_id=555)
        self.assertEqual(self.intake(update_id=555), tid)         # Telegram retried the same update
        self.assertEqual(len(self.s.store.list()), 1)
        report = acceptance_report(self.s.store.get(tid), self.s.store.list() * 2)
        self.assertTrue(any("2 tickets share" in p for p in report["problems"]))

    def test_code_task_needs_branch_or_pr_and_keeps_github_stages_unverified(self):
        tid = self.intake()
        run_id = self.s.claim()["execution"]["run_id"]
        self.s.event(tid, "running", run_id)
        self.s.event(tid, "done", run_id, note="changed relay.py", evidence={"commit": "abcdef1234567"})
        report = self.s.acceptance(tid)
        self.assertTrue(any("without a branch or PR" in p for p in report["problems"]))
        self.assertEqual(report["status"], "UNVERIFIED")
        tid2, _ = self.s.telegram("второй тест", 202)["ticket_id"], None
        run2 = self.s.claim()["execution"]["run_id"]
        self.s.event(tid2, "running", run2)
        self.s.event(tid2, "done", run2, note="pushed", evidence={"commit": "1234567abcdef", "branch": "claude/t-591"})
        report = self.s.acceptance(tid2)
        self.assertEqual(report["status"], "VERIFIED", report)
        states = {row["stage"]: row["state"] for row in report["code"]}
        self.assertEqual(states["ci"], "unverified")              # never claimed by the worker's word
        self.assertEqual(states["merged"], "unverified")
        text = acceptance_text(report)
        self.assertIn("ci: не проверено", text)
        self.assertIn("commit 1234567abcde · branch claude/t-591 (worker report)", text)

    def test_restart_keeps_the_verdict(self):
        tid, run_id = self.full_run()
        restarted = Server(self.path)
        self.assertEqual(restarted.acceptance(tid)["status"], "VERIFIED")
        self.assertEqual(restarted.acceptance(tid)["run_id"], run_id)

    def test_owner_only_and_secrets_redacted(self):
        tid, _ = self.full_run(note="done; token=ghp_abcdefghijklmnopqrstuvwxyz0123")
        self.assertNotIn("ghp_abcdefghijklmnop", self.s.acceptance(tid)["text"])
        viewer = Server(self.path, identity={"role": "viewer"})
        with self.assertRaises(HTTPException) as ctx:
            viewer.acceptance(tid)
        self.assertEqual(ctx.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            self.s.acceptance("R-9999")

    def test_out_of_order_timestamps_are_a_problem(self):
        tid, run_id = self.full_run()
        ticket = self.s.store.get(tid)
        for event in ticket["history"]:
            if event["action"] == "running":
                event["at"] = "2000-01-01T00:00:00+00:00"
        self.assertTrue(any("out of order" in p for p in acceptance_report(ticket, [ticket])["problems"]))

    def test_owner_desk_picks_the_newest_verified_telegram_ticket(self):
        from relay_acceptance import latest_telegram_acceptance
        self.assertIsNone(latest_telegram_acceptance([]))
        tid, run_id = self.full_run()
        self.s.telegram("ещё одна задача, не выполнена", 303)
        best = latest_telegram_acceptance(self.s.store.list())
        self.assertEqual((best["status"], best["ticket_id"], best["run_id"]), ("VERIFIED", tid, run_id))
        self.s.store.create("web only", source={"channel": "factoryos", "source_key": "w"})
        fresh = Server(Path(self.dir.name) / "other.json")
        fresh.telegram("не выполнена", 1)
        self.assertEqual(latest_telegram_acceptance(fresh.store.list())["status"], "UNVERIFIED")


class ControlRoomTest(unittest.TestCase):
    """T-591 goal: /roadmap is a real ROADMAP view, /history is RU/UK/EN, the ticket card has 🔄 refresh → detail."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.s = Server(Path(self.dir.name) / "relay.json")

    def tearDown(self):
        self.dir.cleanup()

    def test_roadmap_summary_and_text(self):
        text = ("- [ ] T-1 Fix Telegram\n  Planner: owner. P0.\n- [x] T-2 Old\n- [ ] [HUMAN] T-3 Pair bot\n"
                "- [ ] T-4 P1 polish\n")
        summary = roadmap_summary(text)
        self.assertEqual((summary["total"], summary["done"], summary["open"]), (4, 1, 3))
        self.assertEqual([x["id"] for x in summary["p0"]], ["T-1"])
        self.assertEqual([x["id"] for x in summary["human"]], ["T-3"])
        self.assertEqual([x["id"] for x in summary["next"]], ["T-4"])
        uk = _roadmap_text(lambda: text, "uk")
        self.assertIn("Потрібно від власника", uk)
        self.assertIn("T-3 Pair bot", uk)
        self.assertIn("unknown", _roadmap_text(lambda: (_ for _ in ()).throw(OSError("gone")), "en").lower())

    def test_roadmap_command_reads_the_deployed_file_and_creates_no_ticket(self):
        self.assertEqual(self.s.telegram("/roadmap", 1, lang="en")["action"], "roadmap")
        self.assertIn("T-591", self.s.last_text())
        self.assertEqual(self.s.store.list(), [])

    def test_history_is_localized(self):
        self.s.telegram("A real task", 2)
        for lang, phrase in (("ru", "подтверждённая история"), ("uk", "підтверджена історія"), ("en", "verified history")):
            self.assertEqual(self.s.telegram("/history", 10 + len(lang), lang=lang)["action"], "history")
            self.assertIn(phrase, self.s.last_text())

    def test_refresh_button_shows_the_factual_detail(self):
        tid = self.s.telegram("A real task", 3)["ticket_id"]
        keyboard = [p["reply_markup"] for m, p in self.s.sent if m == "sendMessage"][-1]["inline_keyboard"]
        buttons = {b["callback_data"] for row in keyboard for b in row}
        self.assertIn(f"relay:ticket:{tid}", buttons)
        callback = {"callback_query": {"id": "c1", "data": f"relay:ticket:{tid}", "message": {"chat": {"id": int(CHAT)}}}}
        result = relay_handle_telegram_update(callback, self.s.store, lambda: {"chat_id": CHAT}, self.s.tg, queue=self.s.queue)
        self.assertEqual(result["action"], "ticket")
        self.assertIn("Этапы (факт из Relay)", self.s.last_text())
        self.assertIn("История:", self.s.last_text())


if __name__ == "__main__":
    unittest.main(verbosity=1)
