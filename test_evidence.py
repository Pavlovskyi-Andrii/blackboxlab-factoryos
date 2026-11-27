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
from relay_execution import RelayQueue, lifecycle_text  # noqa: E402

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
        self.assertEqual(set(evidence.RULES), {"code", "mycast", "telegram", "publish", "other",
                                               "market", "lead", "usage", "payment", "outreach", "spend",   # T-704 Launchpad types
                                               "answer"})                                                   # T-736 agent requests
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
        self.assertIn("⏳ только слова агента (нужно: проверено сервером)", evidence.summary_line(self.t()))


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
        self.assertIn("❌ CI красный", evidence.summary_line(self.t()))

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
        # Fine-grained tokens have no Checks permission: Actions runs are enough for CI.
        self.assertEqual(out["reads"], {"issues": "ok", "pulls": "ok", "checks": "http_403", "actions": "ok"})
        self.assertEqual((out["ci_via"], out["all_ok"]), ("actions", True))

        def no_ci(path):
            if "check-runs" in path or "actions" in path:
                raise E()
            return []
        self.assertEqual(factory.github_read_check(no_ci)["all_ok"], False)
        with patch.object(factory, "GITHUB_READ_TOKEN", ""):
            self.assertEqual(factory.github_read_check(), {"configured": False, "reads": {}})

    def test_server_reads_prefer_the_read_only_token(self):
        """Production log 2026-11-10: intake got 403 with the Builder token while the read token can read issues."""
        import app as factory
        seen = []
        with patch.object(factory, "GITHUB_READ_TOKEN", "read-tok"), patch.object(factory, "GITHUB_TOKEN", "write-tok"), \
             patch.object(factory, "relay_github_owner_issues",
                          side_effect=lambda repo, token, fetch=None: seen.append(token) or {"available": False, "error": "x"}), \
             patch.object(factory, "_intake_issues_from_ec2_snapshot", return_value=(None, "stale")):
            factory.github_issue_intake_once()
            self.assertEqual(factory._github_read_token(), "read-tok")
        self.assertEqual(seen, ["read-tok"])
        with patch.object(factory, "GITHUB_READ_TOKEN", ""), patch.object(factory, "GITHUB_TOKEN", "write-tok"):
            self.assertEqual(factory._github_read_token(), "write-tok")                 # unchanged without it

    def test_read_check_route_is_owner_only(self):
        import app as factory
        from test_route_auth_fixes import AUTH_ON, call
        with patch.object(factory, "FACTORY_PASSWORD", AUTH_ON), patch.object(factory, "GITHUB_READ_TOKEN", ""):
            self.assertEqual(call("GET", "/api/factory/evidence/github-read-check")[0], 401)
            viewer = factory._role_session_token("viewer", "guest")
            self.assertEqual(call("GET", "/api/factory/evidence/github-read-check", cookie=viewer)[0], 403)
            status, body = call("GET", "/api/factory/evidence/github-read-check", cookie=factory.session_token(factory.FACTORY_USER))
            self.assertEqual((status, json.loads(body)), (200, {"configured": False, "reads": {}}))


class ActionsFallbackTest(unittest.TestCase):
    """Fine-grained token: check-runs answers 403, CI is read from Actions workflow runs instead."""

    def read(self, runs_by_sha, total=None):
        from team_tasks import read_github

        class E(Exception):
            code = 403
        calls = []

        def fetch(path):
            calls.append(path)
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [{"number": n, "state": "open", "head": {"sha": sha}} for n, sha in enumerate(runs_by_sha, 1)]
            if "check-runs" in path:
                raise E()
            sha = path.split("head_sha=")[1].split("&")[0]
            runs = runs_by_sha[sha]
            return {"total_count": total if total is not None else len(runs), "workflow_runs": runs}
        return read_github(fetch)["ci"], calls

    def test_actions_runs_give_the_same_labels(self):
        ok = {"status": "completed", "conclusion": "success", "name": "CI"}
        ci, calls = self.read({"a": [ok], "b": [ok, {"status": "completed", "conclusion": "failure", "name": "CI"}],
                               "c": [{"status": "in_progress", "conclusion": None}], "d": []})
        self.assertEqual({k: v["state"] for k, v in ci.items()}, {"a": "passed", "b": "failed", "c": "running", "d": "none"})
        self.assertEqual(sum("check-runs" in c for c in calls), 1)                 # asked once, then Actions only

    def test_truncated_or_odd_runs_are_unknown(self):
        ok = {"status": "completed", "conclusion": "success"}
        self.assertEqual(self.read({"a": [ok]}, total=5)[0]["a"]["state"], "unknown")
        self.assertEqual(self.read({"a": [{"status": "completed", "conclusion": "stale"}]})[0]["a"]["state"], "unknown")


class TrustedSourceTest(Base):
    """Tier 2.1: with the read-only token, only Render's own GitHub read can make a ticket "checked"."""

    def setUp(self):
        super().setUp()
        evidence.set_trusted_sources({"github:render"})

    def tearDown(self):
        evidence.set_trusted_sources(())
        super().tearDown()

    def test_worker_snapshot_is_only_linked(self):
        self.finish()
        self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}})      # default: EC2 snapshot
        t = self.t()
        self.assertEqual((t["status"], evidence.level(t)), ("in_progress", "linked"))
        self.assertIn("только по данным воркера", ", ".join(evidence.missing(t)))
        self.assertIn("☑️ CI зелёный", evidence.summary_line(t))

    def test_render_read_closes_it(self):
        self.finish()
        self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}}, source="github:render")
        self.assertEqual((self.t()["status"], evidence.level(self.t())), ("done", "checked"))

    def test_app_reconcile_uses_its_own_read(self):
        import app as factory
        sent = []

        def fetch(path):
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [merged()]
            if "check-runs" in path:
                return {"total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success", "name": "ci"}]}
            raise AssertionError(path)
        self.finish()
        with patch.object(factory, "RELAY_QUEUE", self.queue), patch.object(factory, "_telegram_send", side_effect=sent.append), \
             patch.object(factory, "_intake_issues_from_ec2_snapshot", side_effect=AssertionError("snapshot not needed")):
            out = factory.relay_pr_reconcile_once(fetch=fetch)
        self.assertEqual((out["source"], out["notices"]), ("github:render", 1))
        self.assertEqual(self.t()["status"], "done")
        self.assertEqual(self.t()["verification"]["checks"]["ci_passed"]["source"], "github:render")
        self.assertIn("тикет закрыт", sent[0])

    def test_own_read_failure_falls_back_to_the_snapshot_without_closing(self):
        import app as factory

        class E(Exception):
            code = 502

        def fetch(path):
            raise E()
        snap = {"github": {"pulls": [merged()], "ci": {"abc123": {"state": "passed"}}}}
        self.finish()
        with patch.object(factory, "RELAY_QUEUE", self.queue), patch.object(factory, "_telegram_send"), \
             patch.object(factory, "_intake_issues_from_ec2_snapshot", return_value=(snap, "fresh")):
            out = factory.relay_pr_reconcile_once(fetch=fetch)
        self.assertEqual(out["source"], "github:ec2-snapshot")
        self.assertEqual(self.t()["status"], "in_progress")


class Tier2Test(Base):
    def close(self):
        self.finish()
        return self.queue.reconcile_pull_requests([{**merged(), "merge_commit_sha": "f" * 40}], {"abc123": {"state": "passed"}})

    def test_t22_deploy_is_told_once_and_shown(self):
        self.close()
        asked = []
        contains = lambda sha: asked.append(sha) or True
        self.assertEqual(self.queue.reconcile_deploys("local", contains), [])                  # no real build sha
        n = self.queue.reconcile_deploys("a" * 40, contains)
        self.assertEqual([x["action"] for x in n], ["deployed"])
        self.assertIn("работают на Render (сборка aaaaaaa)", n[0]["text"])
        self.assertEqual(asked, ["f" * 40])
        self.assertEqual(self.queue.reconcile_deploys("a" * 40, contains), [])                 # once
        self.assertIn("🚀 на Render", evidence.summary_line(self.t()))
        self.assertIn("✅ deployed", lifecycle_text(self.t()))

    def test_t22_not_in_build_or_unknown_is_not_claimed(self):
        self.close()
        self.assertEqual(self.queue.reconcile_deploys("a" * 40, lambda sha: False), [])
        self.assertEqual(self.queue.reconcile_deploys("a" * 40, lambda sha: None), [])
        self.assertIn("deployed — не проверено", lifecycle_text(self.t()))
        self.assertEqual([x["action"] for x in self.queue.reconcile_deploys("f" * 40, lambda sha: None)], ["deployed"])

    def test_t23_closing_notice_offers_the_owner_buttons(self):
        n = self.close()
        self.assertEqual(n[0]["markup"]["inline_keyboard"][0][0]["callback_data"], f"relay:accept:{self.tid}:yes")

    def tap(self, answer):
        sent = []
        api = lambda method, payload=None: sent.append((method, payload or {})) or {"ok": True}
        upd = {"update_id": 77, "callback_query": {"id": "c", "data": f"relay:accept:{self.tid}:{answer}",
                                                   "from": {"id": 42}, "message": {"chat": {"id": 42}}}}
        return relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, api, queue=self.queue), sent

    def test_t23_accept_and_send_back(self):
        self.close()
        out, _ = self.tap("yes")
        self.assertEqual(out["action"], "owner_accepted")
        self.assertEqual(evidence.level(self.t()), "accepted")
        self.assertIn("👍 принято владельцем", evidence.summary_line(self.t()))
        self.tap("yes")
        self.assertEqual(sum(h["action"] == "owner_accepted" for h in self.t()["history"]), 1)   # replay: no change
        out, sent = self.tap("no")
        self.assertEqual((out["action"], self.t()["status"]), ("owner_rejected", "need_you"))
        self.assertNotEqual(evidence.level(self.t()), "accepted")
        self.assertIn("Retry", sent[-1][1]["text"])

    def test_t23_foreign_chat_cannot_tap(self):
        self.close()
        api = lambda method, payload=None: {"ok": True}
        upd = {"update_id": 78, "callback_query": {"id": "c", "data": f"relay:accept:{self.tid}:no",
                                                   "from": {"id": 9}, "message": {"chat": {"id": 9}}}}
        relay_handle_telegram_update(upd, self.store, lambda: {"chat_id": "42"}, api, queue=self.queue)
        self.assertEqual(self.t()["status"], "done")

    def test_t22_app_compares_the_merge_commit_with_the_running_build(self):
        import app as factory
        calls, sent = [], []

        def fetch(path):
            calls.append(path)
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [{**merged(), "merge_commit_sha": "f" * 40}]
            if path.startswith("/compare/"):
                return {"status": "ahead"}
            return {"total_count": 1, "check_runs": [{"status": "completed", "conclusion": "success", "name": "ci"}]}
        self.finish()
        with patch.object(factory, "RELAY_QUEUE", self.queue), patch.object(factory, "BUILD_SHA", "a" * 40), \
             patch.object(factory, "_telegram_send", side_effect=sent.append), \
             patch.object(factory, "_telegram_load_state", return_value={}):
            out = factory.relay_pr_reconcile_once(fetch=fetch)
        self.assertEqual(out["notices"], 2)
        self.assertIn("/compare/" + "f" * 40 + "..." + "a" * 40, calls)
        self.assertTrue(any("работают на Render" in t for t in sent))

    def test_t25_metrics(self):
        import time
        self.close()
        other, _ = self.store.create("second")
        run = self.queue.claim("w2")["execution"]["run_id"]
        self.queue.event(other["id"], "w2", "running", "", {}, run_id=run, event_id=run + ":1")
        self.queue.event(other["id"], "w2", "done", "", {}, run_id=run, event_id=run + ":2")
        third, _ = self.store.create("third")
        self.store.set_status(third["id"], "done", actor="owner", note="closed by hand")
        m = evidence.metrics(self.store.list(), time.time())
        self.assertEqual(m, {"verified": 1, "overridden": 1, "rejected": 0, "waiting": 1})
        self.assertEqual(evidence.metrics(self.store.list(), time.time() + 30 * 86400)["verified"], 0)

    def test_t25_brief_line(self):
        from morning_brief import compose_brief
        text = compose_brief("2026-11-11", 0, github=None, tickets=[], questions_open=0,
                             evidence_metrics={"verified": 3, "overridden": 1, "rejected": 0, "waiting": 2})
        self.assertIn("Докази за тиждень: підтверджено 3, закрито вручну 1", text)
        self.assertIn("«готово» без доказів: 2", text)
        self.assertNotIn("Докази", compose_brief("2026-11-11", 0, github=None, tickets=[], questions_open=0))


class AgentOfficePanelTest(Base):
    """T2.4: owner-only overview route + the Agent Office drawer (button, handlers, EN/UK/RU, hidden for viewers)."""

    def test_overview_facts(self):
        self.finish()
        self.queue.reconcile_pull_requests([merged()], {"abc123": {"state": "passed"}})
        other, _ = self.store.create("closed by hand")
        self.store.set_status(other["id"], "done", actor="owner", note="answered in chat")
        out = evidence.overview(self.store.list(), 2_000_000_000)
        rows = {r["id"]: r for r in out["tickets"]}
        self.assertEqual((rows[self.tid]["level"], rows[self.tid]["satisfied"]), ("checked", True))
        self.assertEqual([c["name"] for c in rows[self.tid]["checks"]], ["pr_merged", "ci_passed"])
        self.assertEqual(rows[other["id"]]["override"]["reason"], "answered in chat")
        self.assertEqual(set(out["metrics"]), {"verified", "overridden", "rejected", "waiting"})

    def test_route_is_owner_only(self):
        import app as factory
        from test_route_auth_fixes import AUTH_ON, call
        with patch.object(factory, "FACTORY_PASSWORD", AUTH_ON), patch.object(factory, "RELAY_STORE", self.store):
            self.assertEqual(call("GET", "/api/factory/evidence/overview")[0], 401)
            viewer = factory._role_session_token("viewer", "guest")
            self.assertEqual(call("GET", "/api/factory/evidence/overview", cookie=viewer)[0], 403)
            status, body = call("GET", "/api/factory/evidence/overview", cookie=factory.session_token(factory.FACTORY_USER))
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["tickets"][0]["id"], self.tid)
        self.assertIn(data["source"], ("render", "ec2_snapshot"))

    def test_dashboard_drawer(self):
        import re
        html = (Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertIn('id="evidenceOpenBtn" onclick="openEvidence()"', html)
        for fn in ("openEvidence", "evidenceRefresh", "evidenceHtml"):
            self.assertRegex(script, r"(async )?function " + fn + r"\(")
        self.assertIn("const eb=$('#evidenceOpenBtn');if(eb)eb.style.display=readOnly?'none':'';", script)
        keys = {k for k in re.findall(r"tr\('(evidence\.[A-Za-z0-9_.]+)'", script) if not k.endswith(".")} | {"evidence.open"}
        keys |= {"evidence.level." + x for x in ("claimed", "linked", "checked", "accepted", "override")}
        keys |= {"evidence.check." + x for x in evidence.RULES["code"]["checks"] + ["deployed", "peer_review"]}
        for lang in ("en", "uk", "ru"):
            line = next(l for l in script.split("\n") if l.startswith(f"Object.assign(I18N.{lang},") and '"evidence.open"' in l)
            table = json.loads(line[len(f"Object.assign(I18N.{lang},"):-2])
            self.assertFalse(keys - set(table), f"{lang} missing {sorted(keys - set(table))}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
