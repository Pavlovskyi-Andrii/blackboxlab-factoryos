"""Gemini CLI executor for the FactoryOS autopilot lane (Issue #119, owner approval 2026-11-15).

Runs exactly one pinned ROADMAP task (``Owner: gemini``) through the open-source Gemini CLI in headless
mode, on the owner's own cached "Sign in with Google" login. It reuses the Claude lane's evidence and
verification path (``delegation.run_delegation``): fresh status.json, exactly one task commit, closed
ROADMAP checkbox, no push from the agent, no change to main/master.

Zero-spend guard: the lane refuses to run when anything in its environment would switch the CLI from the
personal Google login to a key-billed or Cloud-project path (Gemini API key, Vertex AI, ADC, a gateway,
a Code Assist project), and it never reads ``.env`` files, it only refuses to start when one exists where
the CLI would load it. Nothing here pretends the CLI works: a missing binary, a missing login, an
ineligible account or an exhausted quota is a named, blocked state.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import signal
import subprocess
from typing import Any, Callable

try:
    from .delegation import (PROTECTED_BRANCHES, SCRUBBED_ENV, TASK_ID_RE, TIMEOUT_RANGE, _clamp, _git,
                             _safe_cli_output)
except ImportError:  # pragma: no cover - script-style import used by the runner
    from delegation import (PROTECTED_BRANCHES, SCRUBBED_ENV, TASK_ID_RE, TIMEOUT_RANGE, _clamp, _git,
                            _safe_cli_output)

GEMINI_BIN = os.environ.get("FACTORY_GEMINI_BIN", "gemini").strip() or "gemini"
BRANCH_PREFIX = "gemini/"
POLICY_FILE = pathlib.Path(__file__).resolve().with_name("gemini_policy.toml")
# Any of these makes the CLI pick a key-billed / Cloud-project auth path instead of the free personal login
# (verified in gemini-cli packages/core/src/core/contentGenerator.ts getAuthTypeFromEnv and docs/get-started/
# authentication.mdx). GOOGLE_CLOUD_PROJECT routes "Sign in with Google" to a Code Assist licence project.
SPEND_ENV = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "GOOGLE_GEMINI_BASE_URL",
    "GOOGLE_CLOUD_PROJECT",
    "GOOGLE_CLOUD_PROJECT_ID",
    "GEMINI_CLI_USE_COMPUTE_ADC",
    "CLOUD_SHELL",
)
# Never handed to the model process: FactoryOS/worker credentials and anything that could bill.
CHILD_SCRUB = tuple(dict.fromkeys(SCRUBBED_ENV + SPEND_ENV + (
    "FACTORY_OPERATOR_WORKER_TOKEN", "FACTORY_CLAUDE_WORKER_TOKEN_EC2", "FACTORY_CODEX_RELAY_TOKEN",
    "FACTORY_BROWSER_AGENT_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
)))
PERSONAL_AUTH = "oauth-personal"   # AuthType.LOGIN_WITH_GOOGLE in gemini-cli
DEFAULT_TIMEOUT = 3600
QUOTA_RETRY_SECONDS = max(300, min(21600, int(os.environ.get("GEMINI_QUOTA_BACKOFF_SECONDS", "1800"))))
QUOTA_DAILY_SECONDS = max(1800, min(43200, int(os.environ.get("GEMINI_DAILY_QUOTA_BACKOFF_SECONDS", "21600"))))
UNAVAILABLE_SECONDS = max(300, min(43200, int(os.environ.get("GEMINI_UNAVAILABLE_BACKOFF_SECONDS", "3600"))))
# Exit codes documented in gemini-cli docs/cli/headless.md and packages/core/src/utils/exitCodes.ts.
EXIT_AUTH, EXIT_INPUT, EXIT_CONFIG, EXIT_TURNS = 41, 42, 52, 53


def gemini_home(env: dict[str, str] | None = None) -> pathlib.Path:
    env = os.environ if env is None else env
    return pathlib.Path(env.get("HOME") or os.path.expanduser("~")) / ".gemini"


def redact(text: Any) -> str:
    """Bounded, secret-free tail of CLI output (shared patterns + Google keys/tokens)."""
    return _safe_cli_output(text)


# ---------------------------------------------------------------- preflight (no network, no model call)

def spend_guard(env: dict[str, str], repo: pathlib.Path, home: pathlib.Path) -> list[str]:
    """Reasons the lane would not be on the free personal login. Names only, never values."""
    problems = [f"{name} is set in the worker environment" for name in SPEND_ENV if str(env.get(name) or "").strip()]
    # The CLI loads the first .env it finds walking up from the workspace, then ~/.gemini/.env. We do not read
    # them (they may hold secrets); their mere presence where the CLI looks is a refusal.
    for candidate in (repo / ".gemini" / ".env", repo / ".env", home / ".env"):
        if candidate.exists():
            problems.append(f"{candidate} exists; Gemini CLI would load it (may switch auth to a key)")
    return problems


def _settings_auth(home: pathlib.Path) -> str:
    try:
        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    security = data.get("security") if isinstance(data.get("security"), dict) else {}
    auth = security.get("auth") if isinstance(security.get("auth"), dict) else {}
    return str(auth.get("selectedType") or data.get("selectedAuthType") or "")


def cli_version(runner: Callable[..., Any] = subprocess.run, env: dict[str, str] | None = None) -> str:
    """'' when the CLI is missing or broken."""
    try:
        result = runner([GEMINI_BIN, "--version"], capture_output=True, text=True, timeout=30, check=False,
                        env=child_env(env))
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    line = (str(result.stdout or "").strip().splitlines() or [""])[0]
    return re.sub(r"[^0-9A-Za-z.+_ -]", "", line)[:40]


def preflight(repo: pathlib.Path, *, env: dict[str, str] | None = None, runner: Callable[..., Any] = subprocess.run,
              forbidden_checkouts: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Lane readiness without any model call. ``state`` is ready | unconfigured | refused."""
    env = dict(os.environ if env is None else env)
    repo = pathlib.Path(repo).resolve()
    home = gemini_home(env)
    refused = spend_guard(env, repo, home)
    problems: list[str] = []
    branch = _git(repo, "branch", "--show-current")
    if not branch.startswith(BRANCH_PREFIX):
        problems.append(f"checkout {repo} is on '{branch or 'detached'}', expected a {BRANCH_PREFIX}* branch")
    others = forbidden_checkouts if forbidden_checkouts is not None else tuple(
        p for p in env.get("GEMINI_FORBIDDEN_CHECKOUTS", "/opt/factoryos").split(":") if p)
    for other in others:
        try:
            if pathlib.Path(other).resolve() == repo:
                refused.append(f"{repo} is the Claude worker checkout; the Gemini lane needs its own clone")
        except OSError:
            pass
    version = cli_version(runner, env)
    if not version:
        problems.append(f"Gemini CLI '{GEMINI_BIN}' is not installed or does not start (gemini --version failed)")
    auth = _settings_auth(home)
    if auth != PERSONAL_AUTH:
        problems.append(f"Gemini CLI auth is '{auth or 'not set'}' in {home / 'settings.json'}; "
                        "run the one-time interactive 'Sign in with Google' as this user")
    elif not (home / "oauth_creds.json").exists():
        problems.append(f"no cached Google login ({home / 'oauth_creds.json'} missing); "
                        "run the one-time interactive login as this user")
    state = "refused" if refused else ("unconfigured" if problems else "ready")
    return {"state": state, "reasons": refused + problems, "version": version, "branch": branch}


# ---------------------------------------------------------------- one bounded run

def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    """Environment of the model process: no worker/billing credentials, no browser, no push."""
    env = dict(os.environ if base is None else base)
    for key in CHILD_SCRUB:
        env.pop(key, None)
    env["NO_BROWSER"] = "true"            # never try to open a browser for OAuth on a headless host
    env["GIT_TERMINAL_PROMPT"] = "0"
    # Defense in depth next to the policy file: the agent's own `git push` points at a dead URL. The runner
    # pushes later with its own environment. verify_evidence still treats any remote-ref change as a push.
    env["GIT_CONFIG_COUNT"] = "1"
    env["GIT_CONFIG_KEY_0"] = "remote.origin.pushurl"
    env["GIT_CONFIG_VALUE_0"] = "/nonexistent/factoryos-gemini-push-disabled"
    return env


def task_prompt(task: dict[str, Any], branch: str) -> str:
    return (
        f"You are the FactoryOS Gemini lane. Do exactly one ROADMAP task: {task['id']} - {task['title']}.\n"
        "Rules: read AGENTS.md and GEMINI.md first and obey them; the repository's CLAUDE.md safety invariants "
        "apply to you too. Work only in this checkout, on the current branch " + branch + ". Do not switch "
        "branches, do not touch main/master, never run git push, merge, deploy or publish (the runner pushes). "
        "No paid APIs, no new cloud resources, never print or write secrets, never read .env files.\n"
        "Inspect the code and tests first, make the smallest change that meets the task's DONE criterion, run "
        "the task's checks plus `python -m py_compile` on changed files and "
        "`env DATA_DIR=/tmp/factoryos-gemini FACTORY_PASSWORD= FACTORY_LLM_API_KEY= python smoke_tests.py`.\n"
        f"When green: mark only `- [x] {task['id']}` in ROADMAP.md, make exactly ONE git commit whose subject "
        f"contains {task['id']}, then write .autopilot/status.json (it is gitignored, do not commit it) as JSON "
        '{"task": "' + task["id"] + '", "status": "done", "summary": "...", "checks": ["commands you ran"], '
        '"commit": "<sha>"}.\n'
        'If you cannot finish safely, do not commit; write status "blocked" with a "need" field (what the owner '
        'must provide) or "failed" with the reason. Never claim a check you did not run.'
    )


def build_gemini_delegation(task: dict[str, Any], repo: pathlib.Path, *,
                            timeout_seconds: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    task_id = str(task.get("id") or "")
    if not TASK_ID_RE.match(task_id):
        raise ValueError(f"invalid task id: {task_id!r}")
    if task.get("human"):
        raise ValueError(f"{task_id} is a HUMAN task and cannot be delegated")
    if task.get("done"):
        raise ValueError(f"{task_id} is already done")
    if str(task.get("owner") or "").lower() != "gemini":
        raise ValueError(f"{task_id} is not explicitly owned by the gemini lane")
    repo = pathlib.Path(repo).resolve()
    branch = _git(repo, "branch", "--show-current")
    if not branch or branch in PROTECTED_BRANCHES or not branch.startswith(BRANCH_PREFIX):
        raise ValueError(f"the gemini lane runs only on a {BRANCH_PREFIX}* branch, not '{branch or 'detached'}'")
    cmd = [GEMINI_BIN, "--prompt", task_prompt(task, branch), "--output-format", "json",
           "--approval-mode", "yolo", "--skip-trust"]
    if POLICY_FILE.exists():
        cmd += ["--admin-policy", str(POLICY_FILE)]
    return {
        "task_id": task_id,
        "task_title": str(task.get("title") or ""),
        "repo": str(repo),
        "branch": branch,
        "max_turns": 0,  # bounded by time; the CLI has no turn flag (model.maxSessionTurns is a settings key)
        "timeout_seconds": _clamp(timeout_seconds, TIMEOUT_RANGE),
        "cmd": cmd,
        "auth_mode": "google_login_personal",
        "cli_label": "Gemini CLI",
    }


def bounded_run(cmd: list[str], *, cwd=None, env=None, timeout: float | None = None, check: bool = False,
                text: bool = True, capture_output: bool = True, input: str | None = None,
                popen: Callable[..., Any] = subprocess.Popen, killpg: Callable[[int, int], None] = os.killpg):
    """subprocess.run with a hard bound: on timeout the whole process group (node + its shells) is killed,
    so a child holding the pipes cannot keep the runner waiting past the deadline."""
    proc = popen(cmd, cwd=cwd, env=env, text=text, stdin=subprocess.PIPE if input is not None else subprocess.DEVNULL,
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        out, err = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                killpg(proc.pid, sig)
            except (OSError, ProcessLookupError):
                pass
            try:
                out, err = proc.communicate(timeout=10)
                break
            except subprocess.TimeoutExpired:
                out, err = "", ""
        raise subprocess.TimeoutExpired(cmd, timeout, output=out, stderr=err)
    return subprocess.CompletedProcess(cmd, proc.returncode, out, err)


# ---------------------------------------------------------------- reading a failed run

_QUOTA_DAILY = ("exhausted your daily quota", "terminalquotaerror", "quota_exhausted")
_QUOTA_ANY = _QUOTA_DAILY + ("usage limit reached", "resource_exhausted", "rate_limit_exceeded", "rate limit",
                             "quota exceeded", "retryablequotaerror", "status: 429", "\"code\": 429", "code 429",
                             "too many requests")
_INELIGIBLE = ("ineligibletiererror", "ineligible_account", "unsupported_location", "unknown_location",
               "restricted_network", "restricted_age", "validation_required", "not eligible", "antigravity")
_AUTH = ("fatalauthenticationerror", "manual authorization is required", "please set an auth method",
         "failed to authenticate", "invalid_grant", "token has been expired or revoked", "login required",
         "not authenticated", "unauthenticated", "authentication required", "reauthenticate")


def _error_message(output: str) -> str:
    found = re.findall(r'"message"\s*:\s*"((?:[^"\\]|\\.){0,300})"', output or "")
    return found[-1] if found else ""


def diagnose_gemini_failure(*, exit_code: int | None, timed_out: bool, output: str) -> dict[str, Any]:
    """Fail closed when the agent wrote no status.json. Fixed categories; raw output stays local and redacted."""
    lower = (output or "").lower()
    code = "unknown" if exit_code is None else str(exit_code)
    prefix = f"Gemini CLI exit={code}; .autopilot/status.json absent."
    if timed_out:
        return {"status": "failed", "error_category": "timeout",
                "summary": prefix + " Execution exceeded the bounded time; the process group was killed."}
    if "could not start" in lower or "command not found" in lower or "enoent" in lower:
        return {"status": "blocked", "error_category": "lane_unavailable", "hold_seconds": UNAVAILABLE_SECONDS,
                "summary": prefix + " Gemini CLI is not installed or does not start.",
                "need": "On the EC2 host as ec2-user: install the CLI and check 'gemini --version' (runbook step 3)."}
    if any(word in lower for word in _INELIGIBLE):
        return {"status": "blocked", "error_category": "lane_unavailable", "hold_seconds": UNAVAILABLE_SECONDS * 6,
                "summary": prefix + " Google reports this account is not eligible for Gemini CLI access "
                                    "(tier/region/validation).",
                "need": "Owner: see GEMINI_CLI_WORKER.md 'account not eligible'. Do NOT add an API key or Vertex "
                        "project to work around it; that would bill."}
    if exit_code == EXIT_AUTH or any(word in lower for word in _AUTH):
        return {"status": "blocked", "error_category": "lane_unavailable", "hold_seconds": UNAVAILABLE_SECONDS,
                "summary": prefix + " The cached Google login is missing or expired.",
                "need": "Owner: repeat the one-time interactive 'Sign in with Google' as ec2-user (runbook step 4)."}
    if any(word in lower for word in _QUOTA_ANY):
        daily = any(word in lower for word in _QUOTA_DAILY)
        return {"status": "blocked", "error_category": "subscription_limit",
                "hold_seconds": QUOTA_DAILY_SECONDS if daily else QUOTA_RETRY_SECONDS,
                "summary": prefix + (" Free-tier daily quota exhausted." if daily else " Gemini rate limit/quota hit."),
                "limit_resets": "",
                "need": "Wait; the lane parks and resumes automatically. Do not add a paid key."}
    if exit_code == EXIT_TURNS:
        return {"status": "failed", "error_category": "turn_limit",
                "summary": prefix + " The CLI hit its session turn limit before finishing; split the task or Retry."}
    if exit_code in (EXIT_INPUT, EXIT_CONFIG):
        return {"status": "failed", "error_category": "cli_config",
                "summary": prefix + " The CLI rejected its arguments or configuration; check the runner/CLI version."}
    message = _error_message(output)
    detail = (" CLI error: " + " ".join(redact(message).split())[:200]) if message else ""
    return {"status": "failed", "error_category": "missing_status",
            "summary": prefix + (" Gemini returned nonzero." if exit_code not in (0, None)
                                 else " Gemini returned without a verified completion record.") + detail}


def sanitize_status(status: dict[str, Any]) -> dict[str, Any]:
    """Model-authored text goes to Relay/Telegram only after redaction and bounding."""
    out = dict(status)
    for key in ("summary", "need"):
        if key in out:
            out[key] = " ".join(redact(out.get(key)).split())[:600]
    if isinstance(out.get("checks"), list):
        out["checks"] = [" ".join(redact(c).split())[:200] for c in out["checks"][:20]]
    return out
