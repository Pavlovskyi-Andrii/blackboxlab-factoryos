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


if __name__ == "__main__":
    unittest.main()
