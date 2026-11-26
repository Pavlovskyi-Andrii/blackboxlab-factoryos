"""T-741: both Relay Claude launch paths allow ToolSearch + FactoryOS Surfer MCP tools and keep every safety block."""
import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from autopilot import relay_tasks
from autopilot.delegation import DISALLOWED_TOOLS

READ = ["ToolSearch"] + [p + n for p in ("mcp__claude_ai_FactoryOS__", "mcp__FactoryOS__")
                         for n in ("web_search", "web_read", "web_task", "surfer_pending")]
ACTIONS = [p + n for p in ("mcp__claude_ai_FactoryOS__", "mcp__FactoryOS__")
           for n in ("web_open", "web_act", "web_snapshot", "web_close", "web_recipe")]


def flag_values(cmd, flag):
    """Values of a variadic CLI flag: everything up to the next `--flag`."""
    i = cmd.index(flag) + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


class RelayMcpToolGrants(unittest.TestCase):
    ticket = {"id": "R-0999", "title": "Read example.com", "execution": {"run_id": "run-0123456789ab"}}

    def run_execute(self, env):
        seen = []
        heads = iter(["a" * 40, "a" * 40])

        def fake_git(repo, *args):
            if args == ("branch", "--show-current"): return 0, "autopilot/aws-worker"
            if args == ("status", "--porcelain"): return 0, ""
            if args == ("rev-parse", "HEAD"): return 0, next(heads)
            raise AssertionError(args)

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")
        with patch.dict(os.environ, env, clear=False), patch.object(relay_tasks, "git", side_effect=fake_git):
            relay_tasks.execute(self.ticket, Path("/tmp/relay-fake"), run_cli=fake_run,
                                emit_fn=lambda *a, **k: None, push_fn=lambda: 0)
        return seen[0]

    def run_isolated(self, env):
        seen = []
        branch = relay_tasks.relay_branch(self.ticket["id"], self.ticket["execution"]["run_id"])

        def fake_git(repo, *args):
            return 0, (branch if args == ("branch", "--show-current") else "" if args == ("status", "--porcelain")
                       else "a" * 40)

        def fake_run(cmd, **kw):
            seen.append(cmd)
            return SimpleNamespace(returncode=0, stdout=json.dumps({"result": "ok"}), stderr="")
        with patch.dict(os.environ, env, clear=False):
            relay_tasks.execute_isolated(self.ticket, Path("/tmp/relay-fake"), run_cli=fake_run, git_fn=fake_git,
                                         emit_fn=lambda *a, **k: None, pr_fn=lambda *a: self.fail("no PR"))
        return seen[0]

    def both(self, env):
        return [("execute", self.run_execute(env)), ("isolated", self.run_isolated(env))]

    def test_read_tools_granted_exactly_on_both_paths(self):
        for path, cmd in self.both({"RELAY_SURFER_ACTIONS": "0"}):
            with self.subTest(path=path):
                self.assertEqual(cmd[:2], ["claude", "-p"])
                self.assertEqual(flag_values(cmd, "--allowedTools"), READ)
                self.assertNotIn("Bash", flag_values(cmd, "--allowedTools"))

    def test_action_tools_only_on_owner_opt_in(self):
        for path, cmd in self.both({"RELAY_SURFER_ACTIONS": ""}):
            with self.subTest(path=path, actions="off"):
                self.assertFalse(set(ACTIONS) & set(flag_values(cmd, "--allowedTools")))
        for path, cmd in self.both({"RELAY_SURFER_ACTIONS": "1"}):
            with self.subTest(path=path, actions="on"):
                self.assertEqual(flag_values(cmd, "--allowedTools"), READ[:1] + [
                    p + n for p in ("mcp__claude_ai_FactoryOS__", "mcp__FactoryOS__")
                    for n in ("web_search", "web_read", "web_task", "surfer_pending",
                              "web_open", "web_act", "web_snapshot", "web_close", "web_recipe")])

    def test_safety_invariants_preserved(self):
        for path, cmd in self.both({"RELAY_SURFER_ACTIONS": "1"}):
            with self.subTest(path=path):
                self.assertEqual(flag_values(cmd, "--disallowedTools"), list(DISALLOWED_TOOLS))
                self.assertEqual(cmd[-len(DISALLOWED_TOOLS) - 1:], ["--disallowedTools", *DISALLOWED_TOOLS])
                for blocked in ("Bash(git push:*)", "Bash(render:*)", "Bash(gh pr merge:*)", "Bash(gh workflow run:*)"):
                    self.assertIn(blocked, flag_values(cmd, "--disallowedTools"))
                joined = " ".join(cmd[3:])
                self.assertNotIn("bypassPermissions", joined)
                self.assertNotIn("--dangerously-skip-permissions", cmd)
                self.assertNotIn("--permission-mode", cmd)
                allowed = flag_values(cmd, "--allowedTools")
                # only the FactoryOS connector: no other MCP server, no wildcard, no owner-confirm tool
                self.assertTrue(all(t == "ToolSearch" or t.startswith(relay_tasks.FACTORYOS_MCP_PREFIXES)
                                    for t in allowed))
                self.assertFalse([t for t in allowed if "*" in t or "confirm" in t or "decide" in t])

    def test_relay_env_scrubs_paid_api_keys(self):
        seen = {}

        def fake_run(cmd, **kw):
            seen.update(kw["env"])
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        fake_git = lambda repo, *a: (0, relay_tasks.relay_branch("R-0999", "run-0123456789ab")
                                     if a == ("branch", "--show-current") else "")
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-test-not-real"}):
            relay_tasks.execute_isolated(self.ticket, Path("/tmp/relay-fake"), run_cli=fake_run, git_fn=fake_git,
                                         emit_fn=lambda *a, **k: None, pr_fn=lambda *a: ("", "x"))
        self.assertNotIn("ANTHROPIC_API_KEY", seen)


if __name__ == "__main__":
    unittest.main()
