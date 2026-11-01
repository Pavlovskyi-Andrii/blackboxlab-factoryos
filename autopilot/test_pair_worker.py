"""Zero-network tests of interactive FactoryOS worker pairing."""
from __future__ import annotations

from contextlib import redirect_stdout, redirect_stderr
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from autopilot import pair_worker


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "claude-worker.env"
        self.file.write_text(
            "FACTORYOS_URL=https://blackboxlab-factoryos.onrender.com\n"
            "AUTOPILOT_DAEMON=1\n"
            "ANTHROPIC_API_KEY=\n", encoding="utf-8",
        )
        self.file.chmod(0o600)
        self.token = "x" * 50
        # The fixture file is owned by the test user; on the host it is root.
        root = mock.patch.object(pair_worker, "ROOT_UID", os.geteuid())
        root.start()
        self.addCleanup(root.stop)

    def test_pair_preserves_unrelated_variables_without_printing_secret(self):
        capture = io.StringIO()
        with redirect_stdout(capture):
            pair_worker.pair_token(self.file, self.token)
        body = self.file.read_text()
        self.assertIn("FACTORYOS_URL=", body)
        self.assertIn("AUTOPILOT_DAEMON=1", body)
        self.assertIn(pair_worker.KEY + "=" + self.token, body)
        self.assertNotIn(self.token, capture.getvalue())
        self.assertEqual(self.file.stat().st_mode & 0o777, 0o600)

    def test_repair_replaces_only_old_worker_token(self):
        self.file.write_text("FACTORY_CLAUDE_WORKER_TOKEN=" + "a" * 50 + "\nKEEP=ok\n")
        self.file.chmod(0o600)
        pair_worker.pair_token(self.file, self.token)
        content = self.file.read_text()
        self.assertEqual(content.count("FACTORY_CLAUDE_WORKER_TOKEN="), 1)
        self.assertIn("KEEP=ok", content)
        self.assertNotIn("a" * 50, content)

    def test_secret_never_saved_on_validation_failure(self):
        before = self.file.read_bytes()
        for bad in ("", "short", "Bearer invalid", " a" * 40, "x" * 300):
            with self.assertRaises(pair_worker.PairingError):
                pair_worker.pair_token(self.file, bad)
        self.assertEqual(self.file.read_bytes(), before)

    def test_detects_pay_as_you_go_override(self):
        self.file.write_text("ANTHROPIC_API_KEY=sk-sensitive\n")
        self.file.chmod(0o600)
        with self.assertRaisesRegex(pair_worker.PairingError, "paid_api"):
            pair_worker.pair_token(self.file, self.token)
        self.assertNotIn(self.token, self.file.read_text())

    def test_reject_symlink_and_overly_permissive_config(self):
        link = Path(self.tmp.name) / "symlink"
        link.symlink_to(self.file)
        with self.assertRaises(pair_worker.PairingError):
            pair_worker.pair_token(link, self.token)
        self.file.chmod(0o644)
        with self.assertRaisesRegex(pair_worker.PairingError, "permissions"):
            pair_worker.pair_token(self.file, self.token)
        self.assertNotIn(self.token, self.file.read_text())

    def test_noninteractive_fails_without_reading_or_printing_token(self):
        with mock.patch.object(pair_worker.sys, "stdin", io.StringIO()), \
             mock.patch.object(pair_worker.getpass, "getpass") as spy:
            with redirect_stderr(io.StringIO()):
                status = pair_worker.main()
            self.assertEqual(status, 2)
            spy.assert_not_called()

    def test_success_requests_only_supervisor_check(self):
        fake = mock.Mock(returncode=0)
        stdout = io.StringIO()
        with mock.patch.object(pair_worker.sys, "stdin", mock.Mock(isatty=lambda: True)), \
             mock.patch.object(pair_worker, "DEFAULT_ENV", self.file), \
             mock.patch.object(pair_worker.getpass, "getpass", return_value=self.token), \
             mock.patch.object(pair_worker.subprocess, "run", return_value=fake) as shell, \
             redirect_stdout(stdout):
            self.assertEqual(pair_worker.main(), 0)
        shell.assert_called_once()
        argv = shell.call_args.args[0]
        self.assertEqual(argv, ["systemctl", "start", "factoryos-runner-supervisor.service"])
        self.assertNotIn(self.token, stdout.getvalue())
        self.assertNotIn(self.token, repr(shell.call_args))

    def test_refuses_anthropic_api_key_pasted_as_worker_token(self):
        before = self.file.read_bytes()
        with self.assertRaisesRegex(pair_worker.PairingError, "anthropic_api_key"):
            pair_worker.pair_token(self.file, "sk-ant-api03-" + "k" * 40)
        self.assertEqual(self.file.read_bytes(), before)

    def test_forbidden_keys_match_supervisor_preflight(self):
        from autopilot import supervisor
        self.assertEqual(set(pair_worker._FORBIDDEN), set(supervisor.PAID_KEYS))
        for key in supervisor.PAID_KEYS:
            self.file.write_text("KEEP=ok\n" + key + " = 1\n")
            self.file.chmod(0o600)
            with self.assertRaisesRegex(pair_worker.PairingError, "paid_api"):
                pair_worker.pair_token(self.file, self.token)
            self.assertNotIn(self.token, self.file.read_text())

    def test_spaced_old_token_line_is_replaced(self):
        self.file.write_text("FACTORY_CLAUDE_WORKER_TOKEN = " + "a" * 50 + "\n")
        self.file.chmod(0o600)
        pair_worker.pair_token(self.file, self.token)
        content = self.file.read_text()
        self.assertNotIn("a" * 50, content)
        self.assertEqual(content.count("FACTORY_CLAUDE_WORKER_TOKEN"), 1)

    def test_refuses_file_not_owned_by_runner_or_open_directory(self):
        before = self.file.read_bytes()
        with mock.patch.object(pair_worker, "ROOT_UID", os.geteuid() + 1):
            with self.assertRaisesRegex(pair_worker.PairingError, "not_owned"):
                pair_worker.pair_token(self.file, self.token)
        os.chmod(self.tmp.name, 0o777)
        self.addCleanup(os.chmod, self.tmp.name, 0o700)
        with self.assertRaisesRegex(pair_worker.PairingError, "directory_not_protected"):
            pair_worker.pair_token(self.file, self.token)
        self.assertEqual(self.file.read_bytes(), before)
        leftovers = [p.name for p in Path(self.tmp.name).iterdir() if p.name != "claude-worker.env"]
        self.assertEqual(leftovers, [])

    def _interactive(self, **getpass_kw):
        return (
            mock.patch.object(pair_worker.sys, "stdin", mock.Mock(isatty=lambda: True)),
            mock.patch.object(pair_worker, "DEFAULT_ENV", self.file),
            mock.patch.object(pair_worker.getpass, "getpass", **getpass_kw),
        )

    def test_cancel_saves_nothing_and_never_starts_services(self):
        before = self.file.read_bytes()
        stdin, env, ask = self._interactive(side_effect=KeyboardInterrupt)
        err = io.StringIO()
        with stdin, env, ask, \
             mock.patch.object(pair_worker.subprocess, "run") as shell, \
             redirect_stderr(err), redirect_stdout(io.StringIO()):
            self.assertEqual(pair_worker.main(), 2)
        shell.assert_not_called()
        self.assertIn("nothing saved", err.getvalue())
        self.assertEqual(self.file.read_bytes(), before)

    def test_blocked_pairing_never_echoes_token_or_starts_services(self):
        bad = "sk-ant-api03-" + "s" * 40
        stdin, env, ask = self._interactive(return_value=bad)
        out, err = io.StringIO(), io.StringIO()
        with stdin, env, ask, \
             mock.patch.object(pair_worker.subprocess, "run") as shell, \
             redirect_stderr(err), redirect_stdout(out):
            self.assertEqual(pair_worker.main(), 2)
        shell.assert_not_called()
        self.assertNotIn(bad, out.getvalue() + err.getvalue())
        self.assertIn("anthropic_api_key_not_accepted", err.getvalue())

    def test_supervisor_start_failure_is_reported_without_secret(self):
        stdin, env, ask = self._interactive(return_value=self.token)
        out = io.StringIO()
        with stdin, env, ask, \
             mock.patch.object(pair_worker.subprocess, "run",
                               return_value=mock.Mock(returncode=5)), \
             redirect_stdout(out):
            self.assertEqual(pair_worker.main(), 1)
        self.assertIn("could not start", out.getvalue())
        self.assertNotIn(self.token, out.getvalue())

    def test_cli_has_no_token_argument_and_never_starts_claude_directly(self):
        source = Path(pair_worker.__file__).read_text(encoding="utf-8")
        self.assertNotIn("argparse", source)
        self.assertNotIn("sys.argv", source)
        self.assertNotIn("factoryos-claude-worker.service", source)
        self.assertNotIn("print(token", source)


if __name__ == "__main__":
    unittest.main()
