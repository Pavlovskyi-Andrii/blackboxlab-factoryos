"""Evidence Protocol Tier 1: No Evidence — No Done. Offline: temp Relay store, fake GitHub reads, fake Telegram."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-evidence-"))

import evidence  # noqa: E402
from relay import RelayStatusRequest, RelayStore, install_relay_routes, relay_handle_telegram_update  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402

URL = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/950"


def pr(head="abc123", **over):
    return {"number": 950, "html_url": URL, "state": "open", "merged_at": None, "head": {"sha": head}, **over}


def merged(head="abc123"):
    return pr(head, state="closed", merged_at="2026-11-10T09:00:00Z")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)
        t, _ = self.store.create("Fix the Workers page")
        self.tid = t["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def finish(self, ev=None):
        run = self.queue.claim("w1")["execution"]["run_id"]
        self.queue.event(self.tid, "w1", "running", "", {}, run_id=run, event_id=run + ":1")
        return self.queue.event(self.tid, "w1", "done", "PR opened", ev if ev is not None else {"pr_url": URL},
                                run_id=run, event_id=run + ":2")

    def t(self):
        return self.store.get(self.tid)


class RulesTest(Base):
    def test_t16_rules_are_fixed_from_code_at_creation(self):
        ver = self.t()["verification"]
        self.assertEqual((ver["type"], ver["required_level"], ver["required_checks"]), ("code", "checked", ["pr_merged", "ci_passed"]))
        other, _ = self.store.create("Write a memo", owner="chatgpt")
        self.assertEqual(other["verification"]["required_level"], "linked")
        self.assertEqual(set(evidence.RULES), {"code", "mycast", "telegram", "publish", "other"})
        self.assertEqual(evidence.RULES["publish"]["required_level"], "accepted")

    def test_t11_worker_cannot_write_its_own_verdict(self):
        out = self.finish({"pr_url": URL, "verification": {"override": {"reason": "trust me"}}, "level": "checked",
                           "ci_passed": True})
        self.assertEqual((out["status"], out["execution"]["state"]), ("in_progress", "done"))
        ver = self.t()["verification"]
        self.assertEqual((ver["checks"], ver["override"]), ({}, None))
        self.assertEqual(evidence.level(self.t()), "linked")                    # a link, not proof
        self.assertTrue(self.t()["execution"].get("ci_passed_reported"))         # kept only as the worker's report

    def test_levels(self):
        self.assertEqual(evidence.level(self.t()), "claimed")
        self.finish({})
        self.assertEqual(evidence.level(self.t()), "claimed")
        self.assertIn("⏳ claimed (нужно checked)", evidence.summary_line(self.t()))


class RoundTripTest(Base):
    def test_t13_merged_with_ci_on_that_commit_closes_once(self):
        self.finish()
        n = self.queue.reconcile_pull_requests([pr()], {"abc123": {"state": "passed"}})
        self.assertEqual([x["action"] for x in n], ["ci"])
        self.assertEqual(self.t()["status"], "in_progress")
        n = self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}})
        self.assertIn("Доказательства собраны — тикет закрыт", n[0]["text"])
        t = self.t()
        self.assertEqual((t["status"], evidence.level(t)), ("done", "checked"))
        self.assertEqual(t["history"][-2]["action"], "verified")
        self.assertEqual(t["verification"]["checks"]["ci_passed"]["source"], "github:ec2-snapshot")
        self.assertEqual(self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}}), [])

    def test_merged_without_ci_waits_then_closes_when_ci_is_read(self):
        self.finish()
        n = self.queue.reconcile_pull_requests([merged()], {})
        self.assertIn("CI на смерженном коммите не подтверждён", n[0]["text"])
        self.assertIn(f"/done {self.tid} причина", n[0]["text"])
        self.assertEqual(self.t()["status"], "in_progress")
        self.assertEqual(self.queue.reconcile_pull_requests([merged()], {}), [])            # still waiting: silent
        n = self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}})
        self.assertEqual([x["action"] for x in n], ["verified"])
        self.assertEqual(self.t()["status"], "done")
        self.assertEqual(self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}}), [])

    def test_t15_a_new_push_makes_old_ci_stale(self):
        self.finish()
        self.queue.reconcile_pull_requests([pr("abc123")], {"abc123": {"state": "passed"}})
        self.queue.reconcile_pull_requests([pr("def456")], {})                              # new push, CI not read yet
        self.assertIn("ci_passed (старый коммит)", evidence.missing(self.t()))
        self.queue.reconcile_pull_requests([merged("def456")], {})
        self.assertEqual(self.t()["status"], "in_progress")
        self.assertNotEqual(evidence.level(self.t()), "checked")

    def test_red_ci_on_the_merged_commit_does_not_close(self):
        self.finish()
        self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "failed", "failed": "smoke"}})
        self.assertEqual(self.t()["status"], "in_progress")
        self.assertIn("❌ CI зелёный", evidence.summary_line(self.t()))

    def test_closed_without_merge_never_closes(self):
        self.finish()
        self.queue.reconcile_pull_requests([pr(state="closed")], {"abc123": {"state": "passed"}})
        self.assertEqual(self.t()["status"], "in_progress")


class OwnerOverrideTest(Base):
    def test_t14_owner_closes_only_with_a_reason_and_it_is_kept(self):
        self.finish()
        with self.assertRaises(ValueError):
            self.store.set_status(self.tid, "done", actor="owner")
        with self.assertRaises(ValueError):
            self.store.set_status(self.tid, "done", actor="owner", note="ok")              # too short
        t = self.store.set_status(self.tid, "done", actor="owner", note="answer was in chat")
        self.assertEqual((t["status"], t["verification"]["override"]["reason"]), ("done", "answer was in chat"))
        self.assertEqual(t["history"][-1]["note"], "answer was in chat")
        self.assertIn("Закрыто владельцем без доказательств", evidence.summary_line(t))
        self.assertEqual(self.store.set_status(self.tid, "archived", actor="owner")["status"], "archived")

    def test_archive_needs_no_evidence(self):
        self.assertEqual(self.store.set_status(self.tid, "archived", actor="owner")["status"], "archived")

    def test_legacy_ticket_keeps_old_behaviour(self):
        with self.store.lock:
            state = self.store._load_unlocked()
            state["tickets"][0].pop("verification")
            self.store._save_unlocked(state)
        self.assertEqual(self.finish()["status"], "done")

    def telegram(self, text, uid):
        sent = []
        api = lambda method, payload=None: sent.append((method, (payload or {}).get("text", ""))) or {"ok": True}
        upd = {"update_id": uid, "message": {"message_id": uid, "chat": {"id": 42, "type": "private"}, "from": {"id": 42}, "text": text}}
        out = relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, api, queue=self.queue)
        return out, sent

    def test_telegram_done_needs_a_reason(self):
        self.finish()
        out, sent = self.telegram(f"/done {self.tid}", 1)
        self.assertEqual(out["action"], "evidence_required")
        self.assertIn("нет доказательств (pr_merged, ci_passed)", sent[-1][1])
        self.assertEqual(self.t()["status"], "in_progress")
        self.telegram(f"/done {self.tid} проверил сам на проде", 2)
        self.assertEqual((self.t()["status"], self.t()["verification"]["override"]["reason"]), ("done", "проверил сам на проде"))

    def test_telegram_button_refuses_without_evidence(self):
        self.finish()
        sent = []
        api = lambda method, payload=None: sent.append((method, payload or {})) or {"ok": True}
        upd = {"update_id": 9, "callback_query": {"id": "c", "data": f"relay:status:{self.tid}:done",
                                                  "from": {"id": 42}, "message": {"chat": {"id": 42}}}}
        out = relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, api, queue=self.queue)
        self.assertEqual(out["action"], "evidence_required")
        self.assertIn(f"/done {self.tid} причина", sent[-1][1]["text"])
        self.assertEqual(self.t()["status"], "in_progress")

    def test_api_status_refuses_with_409(self):
        from fastapi import FastAPI
        app = FastAPI()
        install_relay_routes(app, self.store, lambda r: {"role": "owner", "email": "o"}, queue=self.queue)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        route = h[("POST", "/api/relay/{ticket_id}/status")]
        self.finish()
        with self.assertRaises(Exception) as ctx:
            route(self.tid, RelayStatusRequest(status="done"), None)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(route(self.tid, RelayStatusRequest(status="done", note="verified by hand"), None)["ticket"]["status"], "done")


class CheckersTest(unittest.TestCase):
    def test_mycast_and_telegram_checkers_only_read(self):
        rows = [{"id": "ep-1", "status": "failed:rate_limited"}, {"id": "ep-1", "status": "sent"}]
        self.assertEqual(evidence.check_mycast(rows, "ep-1")["result"], "pass")
        self.assertEqual(evidence.check_mycast(rows[:1], "ep-1")["detail"], "failed:rate_limited")
        self.assertEqual(evidence.check_mycast([], "ep-2")["detail"], "not_in_log")
        self.assertEqual(evidence.check_telegram({"ok": True, "result": {"message_id": 5}})["result"], "pass")
        self.assertEqual(evidence.check_telegram({"ok": True})["result"], "fail")
        self.assertEqual(evidence.check_telegram(None)["result"], "fail")

    def test_record_check_reports_change_once(self):
        ver = evidence.new_verification("code")
        self.assertTrue(evidence.record_check(ver, "ci_passed", "pass", source="x", sha="a"))
        self.assertFalse(evidence.record_check(ver, "ci_passed", "pass", source="x", sha="a"))
        self.assertTrue(evidence.record_check(ver, "ci_passed", "fail", source="x", sha="a"))


class GithubReadTest(unittest.TestCase):
    def test_merged_prs_get_their_ci_read(self):
        from team_tasks import read_github
        calls = []

        def fetch(path):
            calls.append(path)
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [{"number": 1, "state": "closed", "merged_at": "x", "head": {"sha": "m1"}},
                        {"number": 2, "state": "closed", "merged_at": None, "head": {"sha": "c1"}},
                        {"number": 3, "state": "open", "head": {"sha": "o1"}}]
            return {"total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success", "name": "ci"}]}
        out = read_github(fetch)
        self.assertEqual(set(out["ci"]), {"o1", "m1"})                         # not the unmerged closed one
        self.assertEqual(out["ci"]["m1"]["state"], "passed")

    def test_read_token_check_reports_codes_never_the_token(self):
        import app as factory

        class E(Exception):
            code = 403

        def fetch(path):
            if "check-runs" in path:
                raise E()
            return [] if "issues" in path or "pulls" in path else {}
        out = factory.github_read_check(fetch)
        self.assertEqual(out["reads"], {"issues": "ok", "pulls": "ok", "checks": "http_403", "statuses": "ok"})
        self.assertFalse(out["all_ok"])
        with patch.object(factory, "GITHUB_READ_TOKEN", ""):
            self.assertEqual(factory.github_read_check(), {"configured": False, "reads": {}})

    def test_read_check_route_is_owner_only(self):
        import app as factory
        from test_route_auth_fixes import AUTH_ON, call
        with patch.object(factory, "FACTORY_PASSWORD", AUTH_ON), patch.object(factory, "GITHUB_READ_TOKEN", ""):
            self.assertEqual(call("GET", "/api/factory/evidence/github-read-check")[0], 401)
            viewer = factory._role_session_token("viewer", "guest")
            self.assertEqual(call("GET", "/api/factory/evidence/github-read-check", cookie=viewer)[0], 403)
            status, body = call("GET", "/api/factory/evidence/github-read-check", cookie=factory.session_token(factory.FACTORY_USER))
            self.assertEqual((status, json.loads(body)), (200, {"configured": False, "reads": {}}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
