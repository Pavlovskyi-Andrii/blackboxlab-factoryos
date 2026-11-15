"""Issue #119: Gemini CLI lane regression tests. No network, no real Gemini CLI, no model call.

Run: python -m autopilot.test_gemini_worker
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest

from autopilot import autopilot as ap
from autopilot import delegation, gemini_executor as gx, gemini_worker, relay_tasks
from relay import RelayStore
from relay_execution import RelayQueue

FAKE_KEY = "AIza" + "x" * 35          # shape of a Google API key; not a real key


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True).stdout.strip()


def make_repo(branch="gemini/aws-worker", roadmap="- [ ] T-777 Gemini task\n  Owner: gemini\n"):
    root = pathlib.Path(tempfile.mkdtemp(prefix="factoryos-gemini-test-"))
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "test")
    (root / "ROADMAP.md").write_text("# Roadmap\n\n## v9\n" + roadmap, encoding="utf-8")
    (root / ".gitignore").write_text(".autopilot/\n.venv/\n", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "checkout", "-q", "-b", branch)
    return root


def make_home(auth="oauth-personal", creds=True):
    home = pathlib.Path(tempfile.mkdtemp(prefix="factoryos-gemini-home-"))
    gem = home / ".gemini"
    gem.mkdir()
    if auth is not None:
        (gem / "settings.json").write_text(json.dumps({"security": {"auth": {"selectedType": auth}}}), encoding="utf-8")
    if creds:
        (gem / "oauth_creds.json").write_text("{}", encoding="utf-8")
    return home


class FakeRun:
    def __init__(self, rc=0, stdout="0.68.0\n", exc=None):
        self.rc, self.stdout, self.exc, self.calls = rc, stdout, exc, []

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(cmd, self.rc, self.stdout, "")


class PreflightTest(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo()

    def env(self, home, **extra):
        return {"HOME": str(home), "PATH": os.environ.get("PATH", ""), **extra}

    def test_ready(self):
        out = gx.preflight(self.repo, env=self.env(make_home()), runner=FakeRun(), forbidden_checkouts=())
        self.assertEqual(out["state"], "ready", out)
        self.assertEqual(out["branch"], "gemini/aws-worker")

    def test_no_runtime(self):
        out = gx.preflight(self.repo, env=self.env(make_home()), runner=FakeRun(exc=FileNotFoundError()),
                           forbidden_checkouts=())
        self.assertEqual(out["state"], "unconfigured")
        self.assertTrue(any("not installed" in r for r in out["reasons"]), out)
        out = gx.preflight(self.repo, env=self.env(make_home()), runner=FakeRun(rc=1), forbidden_checkouts=())
        self.assertEqual(out["state"], "unconfigured")

    def test_unauthenticated(self):
        for home in (make_home(auth=None, creds=False), make_home(auth="gemini-api-key"), make_home(creds=False)):
            out = gx.preflight(self.repo, env=self.env(home), runner=FakeRun(), forbidden_checkouts=())
            self.assertEqual(out["state"], "unconfigured", out)
            self.assertTrue(any("login" in r or "auth" in r for r in out["reasons"]), out)

    def test_zero_spend_guard_env(self):
        for name in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS",
                     "GOOGLE_CLOUD_PROJECT"):
            value = FAKE_KEY if "KEY" in name else "true"
            out = gx.preflight(self.repo, env=self.env(make_home(), **{name: value}), runner=FakeRun(),
                               forbidden_checkouts=())
            self.assertEqual(out["state"], "refused", (name, out))
            text = json.dumps(out)
            self.assertIn(name, text)
            self.assertNotIn(FAKE_KEY, text)          # names only, never values

    def test_zero_spend_guard_dotenv_presence_only(self):
        home = make_home()
        (self.repo / ".env").write_text("SOMETHING=" + FAKE_KEY + "\n", encoding="utf-8")
        out = gx.preflight(self.repo, env=self.env(home), runner=FakeRun(), forbidden_checkouts=())
        self.assertEqual(out["state"], "refused")
        self.assertNotIn(FAKE_KEY, json.dumps(out))
        (self.repo / ".env").unlink()
        (home / ".gemini" / ".env").write_text("X=1\n", encoding="utf-8")
        self.assertEqual(gx.preflight(self.repo, env=self.env(home), runner=FakeRun(), forbidden_checkouts=())["state"],
                         "refused")

    def test_shared_checkout_and_wrong_branch(self):
        out = gx.preflight(self.repo, env=self.env(make_home()), runner=FakeRun(), forbidden_checkouts=(str(self.repo),))
        self.assertEqual(out["state"], "refused")
        claude = make_repo(branch="autopilot/aws-worker")
        out = gx.preflight(claude, env=self.env(make_home()), runner=FakeRun(), forbidden_checkouts=())
        self.assertEqual(out["state"], "unconfigured")
        self.assertTrue(any("gemini/" in r for r in out["reasons"]), out)

    def test_worker_refuses_to_start_with_paid_key(self):
        env = {"HOME": str(make_home()), "FACTORY_CLAUDE_WORKER_TOKEN": "t" * 40, "GEMINI_API_KEY": FAKE_KEY}
        problems = gemini_worker.startup_problems(env)
        self.assertTrue(any("GEMINI_API_KEY" in p for p in problems))
        self.assertNotIn(FAKE_KEY, " ".join(problems))
        env.pop("GEMINI_API_KEY")
        env.pop("FACTORY_CLAUDE_WORKER_TOKEN")
        self.assertTrue(any("FACTORY_CLAUDE_WORKER_TOKEN" in p for p in gemini_worker.startup_problems(env)))


class ChildEnvAndCommandTest(unittest.TestCase):
    def test_child_env_scrubs_and_blocks_push(self):
        base = {"PATH": "/usr/bin", "GEMINI_API_KEY": FAKE_KEY, "FACTORY_CLAUDE_WORKER_TOKEN": "w" * 40,
                "FACTORY_OPERATOR_WORKER_TOKEN": "o" * 40, "GH_TOKEN": "g" * 40, "ANTHROPIC_API_KEY": "a" * 40}
        env = gx.child_env(base)
        for key in ("GEMINI_API_KEY", "FACTORY_CLAUDE_WORKER_TOKEN", "FACTORY_OPERATOR_WORKER_TOKEN", "GH_TOKEN",
                    "ANTHROPIC_API_KEY"):
            self.assertNotIn(key, env)
        self.assertEqual(env["NO_BROWSER"], "true")
        self.assertEqual(env["GIT_CONFIG_KEY_0"], "remote.origin.pushurl")

    def test_command_and_scope(self):
        repo = make_repo()
        spec = gx.build_gemini_delegation({"id": "T-777", "title": "x", "owner": "gemini"}, repo)
        cmd = spec["cmd"]
        self.assertEqual(cmd[cmd.index("--output-format") + 1], "json")
        self.assertEqual(cmd[cmd.index("--approval-mode") + 1], "yolo")
        self.assertIn("--admin-policy", cmd)
        self.assertTrue(pathlib.Path(cmd[cmd.index("--admin-policy") + 1]).exists())
        self.assertEqual(spec["auth_mode"], "google_login_personal")
        for bad in ({"id": "T-777", "title": "x", "owner": ""}, {"id": "T-777", "title": "x", "owner": "claude"},
                    {"id": "T-777", "title": "x", "owner": "gemini", "human": True}):
            with self.assertRaises(ValueError):
                gx.build_gemini_delegation(bad, repo)
        with self.assertRaises(ValueError):
            gx.build_gemini_delegation({"id": "T-777", "title": "x", "owner": "gemini"},
                                       make_repo(branch="autopilot/aws-worker"))

    def test_owner_lane_strict_for_gemini(self):
        self.assertTrue(ap.owned_by_operator({"owner": "gemini"}, "gemini"))
        for owner in ("", "any", "auto", "claude", "chatgpt"):
            self.assertFalse(ap.owned_by_operator({"owner": owner}, "gemini"), owner)
        self.assertTrue(ap.owned_by_operator({"owner": ""}, "claude"))      # Claude lane unchanged
        self.assertFalse(ap.owned_by_operator({"owner": "gemini"}, "claude"))

    def test_worker_id_per_lane(self):
        saved = {k: os.environ.get(k) for k in ("AUTOPILOT_OPERATOR", "FACTORY_WORKER_NODE_ID", "FACTORY_CLAUDE_NODE_ID")}
        try:
            os.environ.pop("FACTORY_WORKER_NODE_ID", None)
            os.environ["FACTORY_CLAUDE_NODE_ID"] = "claude-ec2"
            os.environ["AUTOPILOT_OPERATOR"] = "gemini"
            self.assertTrue(relay_tasks.worker_id().startswith("gemini-"))
            os.environ["AUTOPILOT_OPERATOR"] = "claude"
            self.assertEqual(relay_tasks.worker_id(), "claude-ec2")
        finally:
            for k, v in saved.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


class DiagnoseTest(unittest.TestCase):
    def d(self, code, out, timed_out=False):
        return gx.diagnose_gemini_failure(exit_code=code, timed_out=timed_out, output=out)

    def test_quota_exhausted_parks_not_fails(self):
        daily = self.d(1, '{"error": {"type": "TerminalQuotaError", "message": "You have exhausted your daily quota on this model."}}')
        self.assertEqual((daily["status"], daily["error_category"]), ("blocked", "subscription_limit"))
        self.assertEqual(daily["hold_seconds"], gx.QUOTA_DAILY_SECONDS)
        burst = self.d(1, "[API Error: got status: 429 Too Many Requests] RESOURCE_EXHAUSTED")
        self.assertEqual(burst["error_category"], "subscription_limit")
        self.assertEqual(burst["hold_seconds"], gx.QUOTA_RETRY_SECONDS)

    def test_auth_ineligible_missing_cli(self):
        self.assertEqual(self.d(41, "")["error_category"], "lane_unavailable")
        self.assertIn("login", self.d(1, "FatalAuthenticationError: Manual authorization is required")["summary"])
        ineligible = self.d(1, "IneligibleTierError: UNSUPPORTED_LOCATION")
        self.assertEqual(ineligible["error_category"], "lane_unavailable")
        self.assertIn("not eligible", ineligible["summary"])
        self.assertEqual(self.d(None, "Gemini CLI could not start: FileNotFoundError")["error_category"], "lane_unavailable")

    def test_timeout_turns_and_unknown(self):
        self.assertEqual(self.d(None, "", timed_out=True)["error_category"], "timeout")
        self.assertEqual(self.d(53, "")["error_category"], "turn_limit")
        unknown = self.d(1, '{"error": {"message": "boom ' + FAKE_KEY + '"}}')
        self.assertEqual(unknown["status"], "failed")
        self.assertNotIn(FAKE_KEY, unknown["summary"])


class RedactionTest(unittest.TestCase):
    def test_google_and_github_secrets(self):
        secrets = [FAKE_KEY, "ya29." + "a" * 40, "1//" + "b" * 40, "GOCSPX-" + "c" * 24, "ghp_" + "d" * 36,
                   "sk-ant-" + "e" * 30]
        text = "out: " + " | ".join(secrets) + ' "refresh_token": "zzzzzzzzzzzzzz"'
        clean = gx.redact(text)
        for s in secrets + ["zzzzzzzzzzzzzz"]:
            self.assertNotIn(s, clean)
        status = gx.sanitize_status({"summary": "done with " + FAKE_KEY, "need": "ya29." + "q" * 30,
                                     "checks": ["python x " + FAKE_KEY]})
        self.assertNotIn(FAKE_KEY, json.dumps(status))
        self.assertNotIn("ya29.qqq", json.dumps(status))

    def test_heartbeat_payload_redacts_and_reports_unconfigured(self):
        ready = {"state": "unconfigured", "reasons": ["CLI broke near " + FAKE_KEY], "version": "", "branch": "gemini/x"}
        payload = gemini_worker.heartbeat_payload("", ready)
        self.assertEqual(payload["operator_id"], "gemini")
        self.assertEqual(payload["status"], "unconfigured")
        self.assertNotIn(FAKE_KEY, json.dumps(payload))
        allowed = {"operator_id", "node_id", "hostname", "runtime", "version", "auth_mode", "branch", "repo", "status",
                   "task_id", "stage", "queue_depth", "tickets", "last_result", "last_error"}
        self.assertEqual(set(payload), allowed)       # server model OperatorWorkerHeartbeat fields only


class TimeoutTest(unittest.TestCase):
    def test_bounded_run_kills_process_group(self):
        marker = pathlib.Path(tempfile.mkdtemp()) / "survivor"
        script = f"(sleep 3; touch {marker}) & sleep 30"
        started = time.time()
        with self.assertRaises(subprocess.TimeoutExpired):
            gx.bounded_run(["bash", "-c", script], timeout=1)
        self.assertLess(time.time() - started, 15)
        time.sleep(3.5)
        self.assertFalse(marker.exists(), "a grandchild survived the timeout kill")


class DuplicateClaimTest(unittest.TestCase):
    def test_duplicate_and_foreign_claims_refused(self):
        tmp = tempfile.TemporaryDirectory()
        try:
            queue = RelayQueue(RelayStore(pathlib.Path(tmp.name) / "relay.json"))
            first, reason = queue.claim_roadmap("gemini-ec2", "gemini", "T-777", "x", "gemini")
            self.assertIsNotNone(first, reason)
            second, reason = queue.claim_roadmap("gemini-ec2b", "gemini", "T-777", "x", "gemini")
            self.assertIsNone(second)
            self.assertIn("already", reason)
            foreign, reason = queue.claim_roadmap("claude-ec2", "claude", "T-778", "x", "gemini")
            self.assertIsNone(foreign)
            self.assertIn("lane gemini", reason)
        finally:
            tmp.cleanup()

    def test_client_reports_rejection_without_ticket(self):
        ticket, reason = relay_tasks.claim_roadmap(
            {"id": "T-777", "title": "x", "owner": "gemini"}, "gemini",
            post_fn=lambda path, data: {"ok": False, "ticket": None, "rejected": "T-777 is already running by x"})
        self.assertIsNone(ticket)
        self.assertIn("already", reason)


class _Stop(Exception):
    pass


def _forbidden(*_a, **_k):
    raise AssertionError("Claude-only side job ran in the gemini lane")


class MainLoopTest(unittest.TestCase):
    """The shared runner with OPERATOR=gemini: strict owner, preflight before claim, quota parks the lane."""

    def run_loop(self, roadmap, agent, *, ready=None, claim=None, max_sleeps=3):
        path = make_repo(roadmap=roadmap) / "ROADMAP.md"
        answers = path.parent / ".autopilot" / "answers.md"
        calls, claims, sent, statuses, sleeps = [], [], [], [], {"n": 0}

        def fake_sleep(_s):
            sleeps["n"] += 1
            if sleeps["n"] >= max_sleeps:
                raise _Stop

        def fake_claim(task, lane, **_k):
            claims.append((task["id"], lane))
            return claim(task) if claim else ({"id": "R-1", "execution": {"run_id": "run-1"}}, "")

        patches = {
            "ROADMAP": path, "ANSWERS": answers, "DAEMON_MODE": True, "ALLOW_UNCLAIMED": False, "OPERATOR": "gemini",
            "RELAY_ONLY": False, "assert_safe_branch": lambda: "gemini/test", "current_branch": lambda: "gemini/test",
            "sync_branch": lambda _b: "", "commits_ahead": lambda _b: 0, "push_branch": lambda _b: True,
            "poll_control": lambda *a, **k: {"paused": False, "retry": "", "acks": []},
            "run_agent": lambda t: (calls.append(t["id"]), agent(t))[1], "send": sent.append,
            "write_runtime_status": lambda *a, **k: statuses.append((a, k)),
            "done_status_is_consistent": lambda status, target, path=None: True,
            "git_head": lambda: "c" * 40, "commit_files": lambda _sha: [],
            "lane_preflight": lambda: ready or {"state": "ready", "reasons": []},
        }
        saved = {n: getattr(ap, n) for n in patches}
        side = [(ap.relay_tasks, "run_one"), (ap.relay_tasks, "claim_roadmap"), (ap.relay_tasks, "RunReporter"),
                (ap.owner_questions, "answer_one"), (ap.owner_questions, "maybe_selftest"),
                (ap.codex_review, "run_once"), (ap.browser_tasks, "run_one"), (ap.mycast_daily, "run_daily"),
                (ap.time, "sleep")]
        saved_side = [(m, n, getattr(m, n)) for m, n in side]
        try:
            for n, v in patches.items():
                setattr(ap, n, v)
            for m, n in side:
                setattr(m, n, _forbidden)
            ap.relay_tasks.claim_roadmap = fake_claim
            ap.relay_tasks.RunReporter = lambda ticket: _Reporter()
            ap.time.sleep = fake_sleep
            try:
                ap.main()
            except _Stop:
                pass
        finally:
            for n, v in saved.items():
                setattr(ap, n, v)
            for m, n, v in saved_side:
                setattr(m, n, v)
        return calls, claims, sent, statuses, path

    def test_only_owner_gemini_tasks_and_no_side_jobs(self):
        roadmap = ("- [ ] T-700 Shared\n- [ ] T-701 Claude\n  Owner: claude\n- [ ] T-702 Gemini\n  Owner: gemini\n")

        def agent(t):
            p = ap.ROADMAP
            p.write_text(p.read_text(encoding="utf-8").replace("- [ ] " + t["id"], "- [x] " + t["id"]), encoding="utf-8")
            return {"task": t["id"], "status": "done", "summary": "ok"}

        calls, claims, _sent, _st, _p = self.run_loop(roadmap, agent)
        self.assertEqual(calls, ["T-702"])
        self.assertEqual(claims, [("T-702", "gemini")])

    def test_unconfigured_lane_never_claims(self):
        ready = {"state": "unconfigured", "reasons": ["Gemini CLI 'gemini' is not installed"]}
        calls, claims, sent, statuses, _p = self.run_loop("- [ ] T-702 Gemini\n  Owner: gemini\n", _forbidden, ready=ready)
        self.assertEqual((calls, claims), ([], []))
        self.assertTrue(any("not installed" in m for m in sent), sent)
        self.assertTrue(any(a and a[0] == "blocked" for a, _k in statuses), statuses)

    def test_duplicate_claim_refused_does_not_run(self):
        calls, claims, _sent, _st, _p = self.run_loop(
            "- [ ] T-702 Gemini\n  Owner: gemini\n", _forbidden,
            claim=lambda task: (None, task["id"] + " is already running by gemini-other"))
        self.assertEqual(calls, [])
        self.assertTrue(claims)

    def test_quota_exhausted_parks_lane_without_failure(self):
        def agent(t):
            return {"task": t["id"], **gx.diagnose_gemini_failure(
                exit_code=1, timed_out=False, output="TerminalQuotaError: You have exhausted your daily quota")}

        calls, _claims, sent, _st, path = self.run_loop("- [ ] T-702 Gemini\n  Owner: gemini\n", agent, max_sleeps=4)
        self.assertEqual(calls, ["T-702"])                    # one attempt, then the lane is on hold
        parking = json.loads((path.parent / ".autopilot" / "parking.json").read_text(encoding="utf-8"))
        self.assertEqual(parking["failures"], 0)
        self.assertEqual(parking["failed"], [])
        self.assertGreater(parking["limit_until"], time.time() + gx.QUOTA_DAILY_SECONDS - 60)
        self.assertTrue(any("gemini lane parked" in m for m in sent), sent)


class _Reporter:
    def __call__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class DelegationEndToEndTest(unittest.TestCase):
    """run_delegation with the gemini spec and a fake CLI: done needs one commit + checkbox; push is caught."""

    def spec(self, repo):
        return gx.build_gemini_delegation({"id": "T-777", "title": "x", "owner": "gemini"}, repo, timeout_seconds=600)

    def test_done_with_one_commit(self):
        repo = make_repo()

        def fake_cli(cmd, cwd=None, env=None, **_k):
            self.assertNotIn("GEMINI_API_KEY", env)
            roadmap = pathlib.Path(cwd) / "ROADMAP.md"
            roadmap.write_text(roadmap.read_text().replace("- [ ] T-777", "- [x] T-777"))
            _git(cwd, "commit", "-qam", "T-777 do it")
            sha = _git(cwd, "rev-parse", "HEAD")
            (pathlib.Path(cwd) / ".autopilot" / "status.json").write_text(json.dumps(
                {"task": "T-777", "status": "done", "summary": "ok", "checks": ["python x"], "commit": sha}))
            return subprocess.CompletedProcess(cmd, 0, '{"response": "ok"}', "")

        evidence = delegation.run_delegation(self.spec(repo), runner=fake_cli, venv_fn=lambda r: (None, "skipped"),
                                             env_fn=lambda: gx.child_env({"PATH": "/usr/bin", "GEMINI_API_KEY": FAKE_KEY}),
                                             diagnose_fn=gx.diagnose_gemini_failure)
        self.assertEqual(evidence["result"], "done", evidence["violations"])
        self.assertEqual(evidence["auth_mode"], "google_login_personal")

    def test_quota_without_status_is_blocked(self):
        repo = make_repo()
        evidence = delegation.run_delegation(
            self.spec(repo), venv_fn=lambda r: (None, "skipped"), env_fn=lambda: {"PATH": "/usr/bin"},
            diagnose_fn=gx.diagnose_gemini_failure,
            runner=lambda cmd, **k: subprocess.CompletedProcess(cmd, 1, "", "RESOURCE_EXHAUSTED 429 " + FAKE_KEY))
        self.assertEqual(evidence["result"], "blocked")
        self.assertEqual(evidence["status"]["error_category"], "subscription_limit")
        self.assertNotIn(FAKE_KEY, json.dumps(evidence))

    def test_missing_cli_is_blocked_not_running(self):
        repo = make_repo()

        def missing(cmd, **_k):
            raise FileNotFoundError(cmd[0])

        evidence = delegation.run_delegation(self.spec(repo), runner=missing, venv_fn=lambda r: (None, "skipped"),
                                             env_fn=lambda: {}, diagnose_fn=gx.diagnose_gemini_failure)
        self.assertEqual(evidence["status"]["error_category"], "lane_unavailable")
        run = json.loads((repo / ".autopilot" / "run.json").read_text())
        self.assertNotEqual(run["state"], "running")


if __name__ == "__main__":
    result = unittest.main(argv=[sys.argv[0], "-v"], exit=False).result
    if not result.wasSuccessful():
        raise SystemExit(1)
    print("Gemini CLI lane tests passed")
