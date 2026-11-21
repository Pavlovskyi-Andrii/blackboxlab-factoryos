"""Deterministic zero-cloud/no-auth tests of the worker supervisor policy."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from autopilot import supervisor as s


class PreflightTests(unittest.TestCase):
    def ready(self, **overrides):
        baseline = dict(
            has_repo=True,
            branch="autopilot/aws-worker",
            token_set=True,
            subscription_logged_in=True,
            paid_credentials_found=False,
            claude_installed=True,
        )
        baseline.update(overrides)
        return s.preflight_reasons(**baseline)

    def test_ready(self):
        self.assertEqual(self.ready(), [])

    def test_no_paid_api_fallback_even_if_subscription_signed_in(self):
        self.assertIn("paid_api_credentials", self.ready(paid_credentials_found=True))
        result = s.choose_action(self.ready(paid_credentials_found=True), "active", [], 1000)
        self.assertEqual((result.action, result.status), ("stop", "blocked"))

    def test_auth_and_internal_token_both_required(self):
        reasons = self.ready(subscription_logged_in=False, token_set=False)
        self.assertIn("subscription_auth_required", reasons)
        self.assertIn("factoryos_worker_token_missing", reasons)
        self.assertEqual(s.choose_action(reasons, "inactive", [], 1000).action, "none")

    def test_never_run_on_main_or_without_repo(self):
        self.assertIn("unsafe_branch", self.ready(branch="main"))
        self.assertIn("repo_missing", self.ready(has_repo=False))
        self.assertIn("claude_cli_missing", self.ready(claude_installed=False))


class RestartTests(unittest.TestCase):
    def test_healthy_does_not_restart(self):
        self.assertEqual(s.choose_action([], "active", [], 1000).status, "running")

    def test_restart_of_inactive_worker_when_all_gates_pass(self):
        self.assertEqual(s.choose_action([], "inactive", [], 1000).action, "start")

    def test_cooldown_prevents_restart_loop(self):
        self.assertEqual(s.choose_action([], "failed", [950], 1000).status, "cooldown")
        self.assertEqual(s.choose_action([], "failed", [850], 1000).action, "start")

    def test_hourly_budget_requires_owner_instead_of_infinite_retries(self):
        decision = s.choose_action([], "failed", [100, 400, 700], 1000)
        self.assertEqual((decision.action, decision.status), ("none", "needs_owner"))

    def test_old_attempts_expire(self):
        self.assertEqual(s.choose_action([], "failed", [10, 20, 30], 4000).action, "start")


class LocalStateTests(unittest.TestCase):
    def test_atomic_status_permissions_and_no_token_leak(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            state = {"status": "blocked", "reason": "subscription_auth_required"}
            s.save_json(path, state)
            self.assertEqual(json.loads(path.read_text()), state)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_parse_env_ignores_comments(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "worker.env"
            path.write_text('# SECRET=ignore\nAUTOPILOT_REPO="/opt/factoryos"\nFACTORY_CLAUDE_WORKER_TOKEN=\n')
            parsed = s.parse_env(path)
            self.assertEqual(parsed["AUTOPILOT_REPO"], "/opt/factoryos")
            self.assertEqual(parsed["FACTORY_CLAUDE_WORKER_TOKEN"], "")
            self.assertNotIn("SECRET", parsed)

    def test_logged_out_status_is_not_missing_cli(self):
        with mock.patch.object(s, "command", return_value=(
            1, json.dumps({"loggedIn": False, "apiProvider": "firstParty", "authMethod": "none"})
        )):
            self.assertEqual(s.subscription_status(), (True, False))

    def test_subscription_requires_first_party_non_api_key_auth(self):
        with mock.patch.object(s, "command", return_value=(
            0, json.dumps({"loggedIn": True, "apiProvider": "firstParty", "authMethod": "api_key"})
        )):
            self.assertEqual(s.subscription_status(), (True, False))
        with mock.patch.object(s, "command", return_value=(
            0, json.dumps({"loggedIn": True, "apiProvider": "firstParty", "authMethod": "claude.ai"})
        )):
            self.assertEqual(s.subscription_status(), (True, True))


class RunOnceTests(unittest.TestCase):
    """End-to-end tick with fake systemctl/git/claude: the persisted status is truthful."""

    def tick(self, env_text: str, auth: dict, service: str = "active"):
        calls: list[list[str]] = []

        def fake(argv, *, timeout=15):
            calls.append(argv)
            if argv[:2] == ["git", "-C"]:
                return 0, "autopilot/aws-worker"
            if "auth" in argv:
                return 0, json.dumps(auth)
            if argv[:2] == ["systemctl", "is-active"]:
                return 0, service
            return 0, ""

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            repo = root / "repo"
            (repo / ".git").mkdir(parents=True)
            (repo / ".autopilot").mkdir()
            (repo / "ROADMAP.md").write_text("# roadmap\n")
            env_file = root / "worker.env"
            env_file.write_text(f'AUTOPILOT_REPO="{repo}"\n' + env_text)
            with mock.patch.multiple(
                s, ENV_FILE=env_file, STATUS_FILE=root / "status.json",
                RESTART_FILE=root / "restarts.json", WATCHDOG_RESTART_FILE=root / "watchdog.json", command=fake,
            ), mock.patch.dict(s.os.environ, {k: "" for k in s.PAID_KEYS}), \
                    mock.patch("builtins.print"):
                report = s.run_once(now=1000.0)
                persisted = (root / "status.json").read_text()
                published = (repo / ".autopilot" / "supervisor.json").read_text()
        return report, persisted, published, calls

    SUBSCRIPTION = {"loggedIn": True, "apiProvider": "firstParty", "authMethod": "claude.ai"}

    def test_paid_key_stops_active_worker_and_never_leaks_values(self):
        report, persisted, published, calls = self.tick(
            "FACTORY_CLAUDE_WORKER_TOKEN=tok-secret-123\nANTHROPIC_API_KEY=sk-ant-secret-456\n",
            self.SUBSCRIPTION,
        )
        self.assertEqual((report["status"], report["recovery_action"]), ("blocked", "stop"))
        self.assertEqual(report["reason"], "paid_api_credentials")
        self.assertIn(["systemctl", "stop", s.WORKER_SERVICE], calls)
        for text in (persisted, published):
            self.assertNotIn("tok-secret-123", text)
            self.assertNotIn("sk-ant-secret-456", text)

    def test_logged_out_is_reported_blocked_not_running(self):
        report, _, _, calls = self.tick(
            "FACTORY_CLAUDE_WORKER_TOKEN=tok\n",
            {"loggedIn": False, "apiProvider": "firstParty", "authMethod": "none"},
            service="inactive",
        )
        self.assertEqual((report["status"], report["reason"]), ("blocked", "subscription_auth_required"))
        self.assertFalse(report["subscription_authenticated"])
        self.assertFalse(any(c[:2] == ["systemctl", "start"] for c in calls))

    def test_all_gates_pass_restarts_stopped_worker(self):
        report, _, _, calls = self.tick(
            "FACTORY_CLAUDE_WORKER_TOKEN=tok\n", self.SUBSCRIPTION, service="failed",
        )
        self.assertEqual((report["status"], report["recovery_action"]), ("recovering", "start"))
        self.assertIn(["systemctl", "start", "--no-block", s.WORKER_SERVICE], calls)



class WatchdogTests(unittest.TestCase):
    """T-714: a running worker whose own loop stopped beating past its deadline is restarted (bounded)."""

    NOW = 100_000.0

    def decide(self, *, beat=None, state="active", since=NOW - 3600, attempts=(), expected=True, now=NOW):
        return s.watchdog_decision(supposed_to_run=expected, service_state=state, active_since=since,
                                   beat=beat if beat is not None else {"at": now - 60, "deadline": now + 600},
                                   recent_attempts=list(attempts), now=now)

    def test_fresh_heartbeat_is_left_alone(self):
        self.assertEqual(self.decide().action, "none")
        self.assertEqual(self.decide().status, "ok")

    def test_stale_heartbeat_restarts_a_running_unit(self):
        stale = {"at": self.NOW - 2000, "deadline": self.NOW - 1}
        plan = self.decide(beat=stale)
        self.assertEqual((plan.action, plan.reason), ("restart", "loop_heartbeat_stale"))

    def test_no_action_when_not_expected_starting_or_never_beat(self):
        stale = {"at": self.NOW - 2000, "deadline": self.NOW - 1}
        self.assertEqual(self.decide(beat=stale, expected=False).reason, "unit_not_expected")
        self.assertEqual(self.decide(beat=stale, since=self.NOW - 60).reason, "startup_grace")
        self.assertEqual(self.decide(beat={}).reason, "no_loop_heartbeat")               # old code: no file at all
        self.assertEqual(self.decide(beat=stale, since=self.NOW - 1000).reason, "no_loop_heartbeat_since_start")
        self.assertEqual(self.decide(beat=stale, state="inactive").action, "none")       # owner stopped it on purpose

    def test_restart_budget_and_cooldown(self):
        stale = {"at": self.NOW - 2000, "deadline": self.NOW - 1}
        three = [self.NOW - 3000, self.NOW - 2000, self.NOW - 1000]
        self.assertEqual(self.decide(beat=stale, attempts=three).status, "needs_owner")
        self.assertEqual(self.decide(beat=stale, attempts=[self.NOW - 30]).status, "cooldown")
        self.assertEqual(self.decide(beat=stale, attempts=[self.NOW - 4000]).action, "restart")   # older than 1 h
        self.assertEqual(self.decide(state="failed").action, "restart")                          # systemd gave up
        self.assertEqual(self.decide(state="failed", attempts=three).status, "needs_owner")

    def test_run_watchdog_restarts_only_the_hung_unit(self):
        from autopilot import worker_heartbeat as hb
        calls = []

        def fake(argv, *, timeout=15):
            calls.append(argv)
            if argv[:2] == ["systemctl", "is-active"]:
                return 0, "active"
            if argv[:2] == ["systemctl", "is-enabled"]:
                return 0, "enabled"
            return 0, ""
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            hb.beat(hb.path_for(repo, hb.CLAUDE_LOOP_FILE), budget_seconds=900, now=self.NOW - 100)   # fresh
            hb.beat(hb.path_for(repo, hb.SURFER_FILE), budget_seconds=900, now=self.NOW - 1000)       # 100 s overdue
            out = s.run_watchdog(repo, True, self.NOW, cmd=fake, active_since=lambda unit: self.NOW - 7200,
                                 attempts_file=repo / "watchdog.json")
            self.assertEqual(out, {"watchdog_claude_worker": "ok:loop_heartbeat_fresh",
                                   "watchdog_surfer_worker": "restart:loop_heartbeat_stale"})
            self.assertIn(["systemctl", "restart", "--no-block", s.SURFER_SERVICE], calls)
            self.assertNotIn(["systemctl", "restart", "--no-block", s.WORKER_SERVICE], calls)
            self.assertEqual(len(json.loads((repo / "watchdog.json").read_text())["surfer_worker"]), 1)
            # The Claude worker is not checked while the T-562 gates do not want it running.
            hb.beat(hb.path_for(repo, hb.CLAUDE_LOOP_FILE), budget_seconds=1, now=self.NOW - 5000)
            out = s.run_watchdog(repo, False, self.NOW, cmd=fake, active_since=lambda unit: self.NOW - 7200,
                                 attempts_file=repo / "watchdog.json")
            self.assertEqual(out["watchdog_claude_worker"], "not_expected:unit_not_expected")


if __name__ == "__main__":
    unittest.main()
