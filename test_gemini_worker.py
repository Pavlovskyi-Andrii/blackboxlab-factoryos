"""T-607 Gemini worker: free Google-login runtime, narrow token, own lane only.

Deterministic: fake runners, a throwaway git repo and the real ASGI app (auth middleware included).
Never runs the Gemini CLI, never touches the network.
"""
import asyncio
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-t607-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
GEMINI_TOKEN = "gemini-worker-token-for-tests-0123456789abcdef"
os.environ["FACTORY_GEMINI_WORKER_TOKEN"] = GEMINI_TOKEN

import app as factory  # noqa: E402
from autopilot import autopilot as ap  # noqa: E402
from autopilot import delegation as dg  # noqa: E402
from autopilot import gemini_worker as gw  # noqa: E402
from autopilot import relay_tasks  # noqa: E402

TASK = {"id": "T-903", "title": "Gemini task", "done": False, "human": False}


def asgi(method, path, bearer=None, payload=None):
    body = json.dumps(payload or {}).encode()
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if bearer is not None:
        headers.append((b"authorization", ("Bearer " + bearer).encode("ascii")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
             "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent, delivered = [], []

    async def receive():
        if not delivered:
            delivered.append(True)
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return start["status"], json.loads(raw or b"{}")
    except ValueError:
        return start["status"], {}


def claim(lane, task_id, bearer=GEMINI_TOKEN, owner="gemini"):
    return asgi("POST", "/api/relay/worker/roadmap-claim", bearer,
                {"worker_id": f"{lane}-test-node", "lane": lane, "task_id": task_id, "title": "t", "owner": owner})


class ServerScopeTest(unittest.TestCase):
    def test_gemini_token_claims_and_reports_only_its_own_lane(self):
        status, body = claim("gemini", "T-901")
        self.assertEqual(status, 200, body)
        ticket = body["ticket"]
        self.assertEqual(ticket["execution"]["owner"], "gemini")
        run_id = ticket["execution"]["run_id"]
        event = {"ticket_id": ticket["id"], "worker_id": "gemini-test-node", "stage": "running", "note": "started",
                 "run_id": run_id, "event_id": run_id + ":1:running"}
        status, _ = asgi("POST", "/api/relay/worker/event", GEMINI_TOKEN, event)
        self.assertEqual(status, 200)

    def test_gemini_token_cannot_claim_claude_work_or_owner_tickets(self):
        status, _ = claim("claude", "T-902", owner="claude")
        self.assertEqual(status, 403)
        status, _ = asgi("POST", "/api/relay/worker/claim", GEMINI_TOKEN, {"worker_id": "gemini-test-node"})
        self.assertEqual(status, 401)

    def test_gemini_token_cannot_report_on_a_claude_ticket(self):
        status, body = claim("claude", "T-904", bearer=factory.FACTORY_CLAUDE_WORKER_TOKEN, owner="claude")
        self.assertEqual(status, 200, body)
        ticket = body["ticket"]
        event = {"ticket_id": ticket["id"], "worker_id": "gemini-test-node", "stage": "done", "note": "fake",
                 "run_id": ticket["execution"]["run_id"], "event_id": "x:1:done"}
        status, _ = asgi("POST", "/api/relay/worker/event", GEMINI_TOKEN, event)
        self.assertEqual(status, 403)

    def test_gemini_token_opens_nothing_else(self):
        for path in ("/api/claude-worker/heartbeat", "/api/claude-worker/task-result",
                     "/api/factory/owner-desk/worker/claim", "/api/factory/gemini/worker/generate"):
            status, _ = asgi("POST", path, GEMINI_TOKEN, {})
            self.assertEqual(status, 401, path)

    def test_heartbeat_only_for_gemini_lane(self):
        status, body = asgi("POST", "/api/operator-worker/heartbeat", GEMINI_TOKEN,
                            {"operator_id": "gemini", "status": "online", "auth_mode": "google_account"})
        self.assertEqual(status, 200, body)
        self.assertTrue(body["lane"]["online"])
        status, _ = asgi("POST", "/api/operator-worker/heartbeat", GEMINI_TOKEN, {"operator_id": "claude"})
        self.assertEqual(status, 403)

    def test_short_or_missing_token_fails_closed(self):
        with patch.object(factory, "FACTORY_GEMINI_WORKER_TOKEN", "short"):
            status, _ = claim("gemini", "T-905", bearer="short")
            self.assertEqual(status, 401)
        with patch.object(factory, "FACTORY_GEMINI_WORKER_TOKEN", ""):
            status, _ = claim("gemini", "T-905", bearer="")
            self.assertEqual(status, 401)
        status, _ = claim("gemini", "T-905", bearer=GEMINI_TOKEN + "x")
        self.assertEqual(status, 401)


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="factoryos-t607-repo-"))

    def git(*args):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init", "-q", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "t607")
    (repo / "ROADMAP.md").write_text("- [ ] T-903 Gemini task\n  Owner: gemini\n", encoding="utf-8")
    (repo / ".gitignore").write_text(".autopilot/\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-q", "-m", "init")
    git("checkout", "-q", "-b", "autopilot/gemini-worker")
    return repo


class RunnerTest(unittest.TestCase):
    def test_gemini_command_and_settings_enforce_google_login_and_block_push(self):
        repo = make_repo()
        spec = dg.build_delegation(TASK, repo, max_turns=40, timeout_seconds=900, agent="gemini")
        self.assertEqual(spec["cmd"][:2], ["gemini", "-p"])
        self.assertIn("--yolo", spec["cmd"])
        self.assertIn(".autopilot/status.json", spec["cmd"][2])
        self.assertEqual(spec["auth_mode"], "google_account")
        settings = dg.gemini_settings(40)
        self.assertEqual(settings["security"]["auth"]["enforcedType"], "oauth-personal")
        self.assertIn("run_shell_command(git push)", settings["tools"]["exclude"])
        self.assertIn("run_shell_command(git push)", settings["excludeTools"])
        with self.assertRaises(ValueError):
            dg.build_delegation(TASK, repo, agent="other")

    def test_run_scrubs_keys_and_writes_settings(self):
        repo = make_repo()
        spec = dg.build_delegation(TASK, repo, max_turns=40, timeout_seconds=900, agent="gemini")
        calls = []

        def runner(cmd, *, cwd, env, timeout, **kwargs):
            calls.append(env)
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr='{"error": "RESOURCE_EXHAUSTED quota"}')

        with patch.dict(os.environ, {"GEMINI_API_KEY": "must-not-leak", "GOOGLE_API_KEY": "nor-this"}):
            evidence = dg.run_delegation(spec, runner=runner, venv_fn=lambda _r: (None, "none"))
        env = calls[0]
        self.assertNotIn("GEMINI_API_KEY", env)
        self.assertNotIn("GOOGLE_API_KEY", env)
        settings_path = Path(env["GEMINI_CLI_SYSTEM_SETTINGS_PATH"])
        self.assertEqual(json.loads(settings_path.read_text())["security"]["auth"]["selectedType"], "oauth-personal")
        self.assertEqual(evidence["status"]["error_category"], "subscription_limit")
        self.assertIn("Gemini CLI", evidence["status"]["summary"])

    def test_auth_failure_is_blocked_with_google_login_instructions(self):
        out = dg.diagnose_missing_status(exit_code=1, timed_out=False, output="Please set an Auth method", agent="gemini")
        self.assertEqual(out["error_category"], "subscription_auth_required")
        self.assertIn("Login with Google".lower(), out["need"].lower())
        self.assertIn("never enter an API key", out["need"])

    def test_preflight_fails_closed_without_cli_or_google_login(self):
        spec = {"agent": "gemini"}
        home = Path(tempfile.mkdtemp(prefix="factoryos-t607-home-"))
        env = {"HOME": str(home)}
        self.assertEqual(dg.agent_preflight(spec, env=env, which=lambda _n: None)["error_category"], "gemini_cli_unavailable")
        self.assertEqual(dg.agent_preflight(spec, env=env, which=lambda _n: "/usr/bin/gemini")["error_category"],
                         "subscription_auth_required")
        (home / ".gemini").mkdir()
        (home / ".gemini" / "oauth_creds.json").write_text("{}", encoding="utf-8")
        self.assertIsNone(dg.agent_preflight(spec, env=env, which=lambda _n: "/usr/bin/gemini"))
        self.assertIsNone(dg.agent_preflight({"agent": "claude"}, env=env, which=lambda _n: None))

    def test_gemini_lane_takes_only_explicit_gemini_tasks(self):
        with patch.object(ap, "OPERATOR", "gemini"), patch.object(ap, "EXPLICIT_OWNER_ONLY", True):
            self.assertTrue(ap.owned_by_operator({"owner": "gemini"}))
            for owner in ("", "any", "auto", "claude", "chatgpt"):
                self.assertFalse(ap.owned_by_operator({"owner": owner}), owner)
        with patch.object(ap, "OPERATOR", "claude"), patch.object(ap, "EXPLICIT_OWNER_ONLY", False):
            self.assertTrue(ap.owned_by_operator({"owner": ""}))
            self.assertFalse(ap.owned_by_operator({"owner": "gemini"}))

    def test_relay_client_uses_the_gemini_token_and_node_id(self):
        with patch.dict(os.environ, {"AUTOPILOT_OPERATOR": "gemini", "FACTORYOS_URL": "https://f.example",
                                     "FACTORY_GEMINI_WORKER_TOKEN": "g-token", "FACTORY_CLAUDE_WORKER_TOKEN": "c-token"}):
            self.assertEqual(relay_tasks.endpoint(), ("https://f.example", "g-token"))
            self.assertTrue(relay_tasks.worker_id().startswith("gemini-"))
        with patch.dict(os.environ, {"AUTOPILOT_OPERATOR": "claude", "FACTORY_CLAUDE_WORKER_TOKEN": "c-token"}):
            self.assertEqual(relay_tasks.endpoint()[1], "c-token")

    def test_worker_entry_refuses_api_keys_and_strips_claude_credentials(self):
        with patch.dict(os.environ, {"GEMINI_API_KEY": "paid-risk"}):
            with self.assertRaises(SystemExit) as stop:
                gw.main()
            self.assertIn("GEMINI_API_KEY", str(stop.exception))
        env = gw.child_env({"PATH": "/bin", "FACTORY_CLAUDE_WORKER_TOKEN": "c", "TG_TOKEN": "t", "GOOGLE_API_KEY": "k",
                            "FACTORY_GEMINI_WORKER_TOKEN": "g"})
        self.assertEqual(env["AUTOPILOT_OPERATOR"], "gemini")
        self.assertEqual(env["AUTOPILOT_AGENT"], "gemini")
        for key in ("FACTORY_CLAUDE_WORKER_TOKEN", "TG_TOKEN", "GOOGLE_API_KEY"):
            self.assertNotIn(key, env)
        self.assertEqual(env["FACTORY_GEMINI_WORKER_TOKEN"], "g")

    def test_heartbeat_payload_is_secret_free(self):
        sent = {}

        class Response:
            status_code = 200

        def post(url, headers, json, timeout):
            sent.update(url=url, json=json)
            return Response()

        with patch.object(gw, "WORKER_TOKEN", "g-token-secret"):
            self.assertTrue(gw.heartbeat("0.1.0", status="online", post=post))
        self.assertTrue(sent["url"].endswith("/api/operator-worker/heartbeat"))
        self.assertEqual(sent["json"]["operator_id"], "gemini")
        self.assertEqual(sent["json"]["auth_mode"], "google_account")
        self.assertNotIn("g-token-secret", json.dumps(sent["json"]))


if __name__ == "__main__":
    unittest.main()
