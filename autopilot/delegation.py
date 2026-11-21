"""Agent delegation adapter (Claude Code CLI, or Gemini CLI for the T-607 Gemini lane).

Delegates exactly one pinned roadmap task to an agent CLI invocation that
runs on the owner's subscription / Google-account auth, with bounded turns/time, and captures
verifiable evidence (git state before/after, commits, status.json, output tail).

The adapter never pushes, never touches main/master and never deploys. Any
evidence of such an action turns the result into ``failed``.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import secrets
import subprocess
import time
from typing import Any, Callable

PROTECTED_BRANCHES = {"main", "master"}
MAX_TURNS_RANGE = (10, 160)
TIMEOUT_RANGE = (600, 7200)
OUTPUT_TAIL_CHARS = 4000
# Environment variables that would switch Claude Code to PAYG API billing or
# hand the delegated agent production/deploy credentials.
SCRUBBED_ENV = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "RENDER_API_KEY",
    "RENDER_DEPLOY_HOOK_URL",
    "FACTORY_CLAUDE_WORKER_TOKEN",
    "FACTORY_TELEGRAM_BOT_TOKEN",
    "TELEGRAM_BOT_TOKEN",
    # T-607: Gemini CLI must run on the owner's free Google-account login, never on an API key
    # (a key on a project with billing turns quota overflow into paid calls).
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_GENAI_USE_VERTEXAI",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "FACTORY_GEMINI_API_KEY",
    "FACTORY_GEMINI_WORKER_TOKEN",
)
AGENTS = ("claude", "gemini")
AGENT_LABELS = {"claude": "Claude", "gemini": "Gemini"}
# T-607: Gemini CLI tool exclusions (shell-command prefixes), the same boundary as DISALLOWED_TOOLS.
GEMINI_EXCLUDED_SHELL = (
    "git push", "git checkout main", "git checkout master", "git switch main", "git switch master",
    "git branch -D", "git reset --hard", "git rebase", "git merge", "render", "gh", "curl", "wget",
    "npm publish", "sudo",
)
GEMINI_AUTH_TYPE = "oauth-personal"   # "Login with Google": free personal tier, no API key, no billing
# Owner 2026-11-15: the Google login kept falling back to a key, so the owner may opt in to an AI Studio key from a
# project WITHOUT billing ("Free tier" in AI Studio): Google cannot bill it, quota overflow is a 429, never a charge.
# Opt-in only (FACTORY_GEMINI_AUTH=api-key-free-tier); the key comes from the worker's own env file.
GEMINI_KEY_AUTH = "api-key-free-tier"


def gemini_auth_mode(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    return GEMINI_KEY_AUTH if env.get("FACTORY_GEMINI_AUTH", "").strip().lower() == GEMINI_KEY_AUTH else "google"
# Claude Code permission rules: the delegated agent may commit locally but
# must never push, switch to a protected branch or deploy.
DISALLOWED_TOOLS = (
    "Bash(git push:*)",
    "Bash(git checkout main:*)",
    "Bash(git checkout master:*)",
    "Bash(git switch main:*)",
    "Bash(git switch master:*)",
    "Bash(git branch -D:*)",
    "Bash(git reset --hard:*)",
    "Bash(render:*)",
    "Bash(gh workflow run:*)",
    "Bash(gh pr merge:*)",
    # T-MODS: product-film's upstream upload path (display.dev) is removed; block it here too.
    "Bash(dsp:*)",
    "Bash(npx -y @displaydev/cli:*)",
)
# Headless `claude -p` cannot ask for approval, so anything not pre-allowed is denied.
# The verification loop from CLAUDE.md (edit, run python tests, node --check, local commit)
# must work without a human; push/deploy stay blocked by DISALLOWED_TOOLS above.
# No `env …` rule: `Bash(env DATA_DIR=:*)` never matched on the worker, and a rule that did
# would let any command hide behind `env`. Checks that need variables go through
# `python -m autopilot.envrun` (covered by `Bash(python:*)`).
ALLOWED_TOOLS = (
    "Read",
    "Edit",
    "Write",
    "Glob",
    "Grep",
    "Bash(python:*)",
    "Bash(python3:*)",
    "Bash(node --check:*)",
    "Bash(git status:*)",
    "Bash(git diff:*)",
    "Bash(git log:*)",
    "Bash(git show:*)",
    "Bash(git add:*)",
    "Bash(git commit:*)",
    "Bash(ls:*)",
    "Bash(mkdir:*)",
    "Bash(rm -rf /tmp/factoryos-:*)",
)
VENV_DIR = ".venv"
VENV_TIMEOUT_SECONDS = 900
TASK_ID_RE = re.compile(r"^T-[A-Za-z0-9-]+$")

try:
    from . import mods_runtime
except ImportError:
    import mods_runtime

Runner = Callable[..., subprocess.CompletedProcess]


def _clamp(value: int, bounds: tuple[int, int]) -> int:
    return max(bounds[0], min(bounds[1], int(value)))


def _git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else ""


def git_snapshot(repo: pathlib.Path) -> dict[str, Any]:
    refs = {}
    for name in sorted(PROTECTED_BRANCHES):
        refs[name] = _git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}")
    # A push updates local remote-tracking refs, so any change here is evidence
    # that the delegated agent pushed despite the disallowed-tool rules.
    remote_refs = {}
    for line in _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/remotes").splitlines():
        name, _, sha = line.partition(" ")
        remote_refs[name] = sha
    return {
        "branch": _git(repo, "branch", "--show-current"),
        "head": _git(repo, "rev-parse", "HEAD"),
        "protected_refs": refs,
        "remote_refs": remote_refs,
    }


def task_prompt(task: dict[str, Any]) -> str:
    return (
        f"Работай строго по CLAUDE.md. Выполни только задачу {task['id']} — {task['title']}. "
        "Не переходи к другой задаче в этом запуске. Доведи её до проверяемого DONE, "
        "отметь checkbox в ROADMAP.md, запиши решения, тесты и .autopilot/status.json, "
        "сделай один commit с ID задачи. Не трогай main и production. "
        "Python: `python`/`python3` уже указывают на подготовленное .venv с requirements.txt; "
        "не создавай свой venv и не используй /tmp для окружения. "
        "Команды вида `env VAR=… python …` и `VAR=… python …` в этом режиме запрещены. "
        "Переменные окружения для проверок задавай через `python -m autopilot.envrun`, например "
        "`python -m autopilot.envrun DATA_DIR=/tmp/factoryos-autopilot FACTORY_PASSWORD= FACTORY_LLM_API_KEY= smoke_tests.py`."
    )


def gemini_task_prompt(task: dict[str, Any]) -> str:
    """Gemini reads AGENTS.md/GEMINI.md, not CLAUDE.md, so the run contract is spelled out here."""
    return (
        f"You are the FactoryOS Gemini worker. Read AGENTS.md and GEMINI.md first and follow them. "
        f"Do exactly one ROADMAP task: {task['id']} — {task['title']}. Do not start any other task. "
        "Read the task's Goal/DONE lines in ROADMAP.md, inspect the existing code, make the smallest safe change "
        "that meets DONE, add or update tests, and run them with `python`/`python3` (already the prepared .venv; "
        "set variables with `env`, e.g. `env DATA_DIR=/tmp/factoryos-autopilot FACTORY_PASSWORD= FACTORY_LLM_API_KEY= "
        "python smoke_tests.py`). When DONE is met: mark only this task `[x]` in ROADMAP.md and make exactly ONE "
        f"local git commit whose subject starts with {task['id']}. Never push, merge, rebase, deploy, publish, "
        "touch main/master, read .env or print secrets, enable paid APIs, or weaken tests. "
        "Finally ALWAYS write .autopilot/status.json (also when blocked or failed): "
        f'{{"task": "{task["id"]}", "status": "done|blocked|failed", "summary": "...", '
        '"need": "only when blocked", "checks": ["commands you actually ran"], "commit": "sha when done"}. '
        "Block only for a missing secret, payment, external account access, publishing approval or an "
        "irreversible business decision."
    )


def gemini_settings(max_turns: int, auth: str = "google") -> dict[str, Any]:
    """System-level Gemini CLI settings for one run: Google-account auth enforced, dangerous shell excluded.

    Both the current (`tools.exclude`, `security.auth.*`) and the legacy (`excludeTools`, `selectedAuthType`)
    keys are written, so the same file works across CLI versions.
    """
    excluded = [f"run_shell_command({cmd})" for cmd in GEMINI_EXCLUDED_SHELL]
    auth_type = "gemini-api-key" if auth == GEMINI_KEY_AUTH else GEMINI_AUTH_TYPE
    return {
        "security": {"auth": {"selectedType": auth_type, "enforcedType": auth_type}},
        "selectedAuthType": auth_type,
        "tools": {"exclude": excluded},
        "excludeTools": excluded,
        "model": {"maxSessionTurns": max_turns},
        "maxSessionTurns": max_turns,
        "privacy": {"usageStatisticsEnabled": False},
        "usageStatisticsEnabled": False,
    }


def gemini_settings_path(repo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(repo) / ".autopilot" / "gemini-settings.json"   # gitignored runtime file


def gemini_home(env: dict[str, str] | None = None) -> pathlib.Path:
    env = os.environ if env is None else env
    return pathlib.Path(env.get("GEMINI_CLI_HOME") or env.get("HOME") or str(pathlib.Path.home())) / ".gemini"


def agent_preflight(spec: dict[str, Any], *, env: dict[str, str] | None = None,
                    which: Callable[[str], str | None] | None = None) -> dict[str, Any] | None:
    """Fail closed before starting a CLI that cannot run for free. None means the run may start."""
    if spec.get("agent") != "gemini":
        return None
    import shutil

    if not (which or shutil.which)("gemini"):
        return {"status": "blocked", "error_category": "gemini_cli_unavailable",
                "summary": "Gemini CLI is not installed on this worker.",
                "need": "On EC2 install Node.js 20+ and `npm install -g @google/gemini-cli`, then run `gemini` once and log in with Google."}
    env = os.environ if env is None else env
    if gemini_auth_mode(env) == GEMINI_KEY_AUTH:
        if not env.get("GEMINI_API_KEY", "").strip():
            return {"status": "blocked", "error_category": "subscription_auth_required",
                    "summary": "Gemini worker is in free-tier key mode but GEMINI_API_KEY is missing.",
                    "need": "Put a key from an AI Studio project WITHOUT billing into ~/.config/factoryos/gemini-worker.env as GEMINI_API_KEY."}
        return None
    home = gemini_home(env)
    # Gemini CLI has stored the Google login as oauth_creds.json and, in newer versions, gemini-credentials.json.
    if not any((home / name).exists() for name in ("oauth_creds.json", "gemini-credentials.json")):
        return {"status": "blocked", "error_category": "subscription_auth_required",
                "summary": "Gemini CLI has no Google-account login on this worker.",
                "need": "On EC2 run `NO_BROWSER=true gemini`, choose Login with Google, open the link on your phone and paste the code. Do not enter an API key."}
    return None


def build_delegation(
    task: dict[str, Any],
    repo: pathlib.Path,
    *,
    max_turns: int = 80,
    timeout_seconds: int = 3600,
    skip_permissions: bool = False,
    agent: str = "claude",
    mods: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a pinned, bounded delegation spec for exactly one roadmap task.

    ``mods`` (from ``mods_runtime.prepare``) adds the owner's switched-on Claude Code plugins for this run only;
    they are Claude plugins, so a Gemini run never carries them."""
    agent = str(agent or "claude").strip().lower()
    if agent not in AGENTS:
        raise ValueError(f"unsupported agent: {agent!r}")
    task_id = str(task.get("id") or "")
    if not TASK_ID_RE.match(task_id):
        raise ValueError(f"invalid task id: {task_id!r}")
    if task.get("human"):
        raise ValueError(f"{task_id} is a HUMAN task and cannot be delegated")
    if task.get("done"):
        raise ValueError(f"{task_id} is already done")
    repo = pathlib.Path(repo).resolve()
    branch = _git(repo, "branch", "--show-current")
    if not branch or branch in PROTECTED_BRANCHES:
        raise ValueError("delegation refuses to run on main/master or a detached HEAD")
    turns = _clamp(max_turns, MAX_TURNS_RANGE)
    timeout = _clamp(timeout_seconds, TIMEOUT_RANGE)
    if agent != "claude" or not mods:
        mods = {"mods": [], "plugins": [], "applied": False,
                "note": "mods not requested" if agent == "claude" else "mods are Claude plugins"}
    cmd = [
        "claude",
        "-p",
        mods_runtime.prompt_prefix(mods) + task_prompt(task),
        "--output-format",
        "json",
        "--max-turns",
        str(turns),
        *mods_runtime.cli_args(mods, repo),
        "--allowedTools",
        *ALLOWED_TOOLS,
        *mods_runtime.extra_tools(mods),
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    env_extra: dict[str, str] = {}
    if agent == "gemini":
        # Headless Gemini cannot ask for approval: --yolo auto-approves, and the system settings file
        # (written by run_delegation) excludes push/merge/deploy shell commands and enforces Google login.
        cmd = ["gemini", "-p", gemini_task_prompt(task), "--output-format", "json", "--yolo"]
        model = os.environ.get("FACTORY_GEMINI_MODEL", "").strip()
        if re.fullmatch(r"[A-Za-z0-9._-]{1,80}", model):
            cmd += ["--model", model]
        env_extra = {"GEMINI_CLI_SYSTEM_SETTINGS_PATH": str(gemini_settings_path(repo))}
    return {
        "agent": agent,
        "env_extra": env_extra,
        "task_id": task_id,
        "task_title": str(task.get("title") or ""),
        "repo": str(repo),
        "branch": branch,
        "max_turns": turns,
        "timeout_seconds": timeout,
        "cmd": cmd,
        "gemini_auth": gemini_auth_mode() if agent == "gemini" else "",
        "auth_mode": ({"google": "google_account", GEMINI_KEY_AUTH: GEMINI_KEY_AUTH}[gemini_auth_mode()]
                      if agent == "gemini" else "subscription"),
        "mods": mods,
    }


def delegated_env(base: dict[str, str] | None = None, keep: tuple[str, ...] = ()) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in SCRUBBED_ENV:
        if key not in keep:
            env.pop(key, None)
    return env


def ensure_venv(repo: pathlib.Path, *, runner: Runner = subprocess.run) -> tuple[pathlib.Path | None, str]:
    """Keep a persistent `<repo>/.venv` matching requirements.txt for the delegated agent.

    Lives in the (gitignored) checkout, not /tmp, so it survives reboots. Rebuilt only when
    requirements.txt changes. Uses the free PyPI index; no paid resource is involved.
    """
    requirements = repo / "requirements.txt"
    if not requirements.exists():
        return None, "no requirements.txt"
    venv = repo / VENV_DIR
    python = venv / "bin" / "python"
    marker = venv / ".requirements.sha256"
    digest = __import__("hashlib").sha256(requirements.read_bytes()).hexdigest()
    if python.exists() and marker.exists() and marker.read_text(encoding="utf-8").strip() == digest:
        return venv, "ready"
    try:
        if not python.exists():
            created = runner(["python3", "-m", "venv", str(venv)], cwd=repo, check=False,
                             text=True, capture_output=True, timeout=VENV_TIMEOUT_SECONDS)
            if created.returncode != 0:
                return None, "venv creation failed: " + _tail(created.stderr)[-300:]
        installed = runner([str(python), "-m", "pip", "install", "-q", "-r", str(requirements)], cwd=repo,
                           check=False, text=True, capture_output=True, timeout=VENV_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return None, "venv setup failed: " + type(exc).__name__
    if installed.returncode != 0:
        return None, "pip install failed: " + _tail(installed.stderr)[-300:]
    marker.write_text(digest + "\n", encoding="utf-8")
    return venv, "installed"


def venv_env(env: dict[str, str], venv: pathlib.Path | None) -> dict[str, str]:
    if venv is None:
        return env
    env = dict(env)
    env["VIRTUAL_ENV"] = str(venv)
    env["PATH"] = str(venv / "bin") + os.pathsep + env.get("PATH", "")
    return env


def _safe_cli_output(value: Any) -> str:
    """Bound and redact local CLI evidence. Never send raw agent output to Relay."""
    tail = _tail(value)
    tail = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", tail)
    tail = re.sub(r"(?i)(authorization:\s*bearer\s+)[^\s\"']+", r"\1[REDACTED]", tail)
    tail = re.sub(r"(?i)\b(?:sk-ant-[A-Za-z0-9_-]{8,}|github_pat_[A-Za-z0-9_]{12,}|gh[pousr]_[A-Za-z0-9_]{12,}|AIza[0-9A-Za-z_-]{20,}|ya29\.[0-9A-Za-z_.-]{10,})\b", "[REDACTED]", tail)
    tail = re.sub(
        r"(?i)([\"']?(?:access_token|refresh_token|api_key|client_secret|authorization_code)[\"']?\s*[:=]\s*[\"']?)[^\"'\s,}]+",
        r"\1[REDACTED]", tail,
    )
    tail = re.sub(r"(?i)([?&](?:code|token|access_token|refresh_token|state)=)[^&\s\"']+", r"\1[REDACTED]", tail)
    return tail[-OUTPUT_TAIL_CHARS:]


# Structured `api_error` values the Claude CLI reports when the account is out of allowance.
LIMIT_API_ERRORS = {"usage_limit_reached", "rate_limit_error", "rate_limit_exceeded", "rate_limit"}


def cli_error_fields(output: str) -> dict[str, Any]:
    """Error fields from the CLI's JSON result line.

    Regex instead of json.loads: the evidence is a tail (the line may be cut at the
    start) and stdout+stderr are concatenated, so the line need not parse on its own.
    """
    fields: dict[str, Any] = {}
    api_error = re.findall(r'"api_error"\s*:\s*"([A-Za-z_]{1,64})"', output)
    if api_error:
        fields["api_error"] = api_error[-1].lower()
    status = re.findall(r'"api_error_status"\s*:\s*(\d{3})\b', output)
    if status:
        fields["api_error_status"] = int(status[-1])
    result = re.findall(r'"result"\s*:\s*"((?:[^"\\]|\\.){0,400})"', output)
    if result:
        try:
            fields["result"] = json.loads('"' + result[-1] + '"')
        except ValueError:
            fields["result"] = result[-1]
    return fields


def limit_reset_hint(text: str) -> str:
    """'resets 6pm (UTC)' -> '6pm (UTC)'. Charset-restricted so CLI text never reaches the owner verbatim."""
    found = re.search(r"(?i)\bresets?\s+(?:at\s+)?([0-9][0-9A-Za-z:/_+ ().,-]{0,40})", text or "")
    if not found:
        return ""
    return re.sub(r"[^0-9A-Za-z:/_+ ().,-]", "", found.group(1)).strip(" .,")[:40]


def limit_reset_epoch(hint: str, now: float) -> float | None:
    """Next moment matching a clock-time hint such as '6pm (UTC)', '6:30pm', '18:00 (Europe/Kyiv)'.

    Returns None for anything we cannot read with certainty (dated weekly resets,
    unknown zones); the caller then falls back to a fixed back-off.
    """
    import datetime as dt

    hint = (hint or "").strip()
    if not hint or re.search(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|mon|tue|wed|thu|fri|sat|sun)", hint):
        return None
    clock = re.match(r"(?i)^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:\(([^)]{1,40})\))?$", hint)
    if not clock or (clock.group(3) is None and clock.group(2) is None):
        return None
    hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
    meridiem = (clock.group(3) or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    if hour > 23 or minute > 59:
        return None
    zone_name = (clock.group(4) or "UTC").strip()
    if zone_name.upper() in {"UTC", "GMT"}:
        zone: dt.tzinfo = dt.timezone.utc
    else:
        try:
            from zoneinfo import ZoneInfo

            zone = ZoneInfo(zone_name)
        except Exception:
            return None
    local_now = dt.datetime.fromtimestamp(now, zone)
    moment = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if moment.timestamp() <= now:
        moment += dt.timedelta(days=1)
    return moment.timestamp()


def diagnose_missing_status(*, exit_code: int | None, timed_out: bool, output: str, agent: str = "claude") -> dict[str, Any]:
    """Fail closed while telling the owner what kind of early CLI failure happened.

    We cannot treat a Claude process as successful without its fresh status file.
    Classifications are fixed strings: raw CLI output stays in redacted local evidence.
    """
    lower = output.lower()
    fields = cli_error_fields(output)
    code = "unknown" if exit_code is None else str(exit_code)
    label = AGENT_LABELS.get(agent, "Claude")
    prefix = f"{label} CLI exit={code}; .autopilot/status.json absent."
    if timed_out:
        return {"status": "failed", "error_category": "timeout",
                "summary": prefix + " Execution timed out; inspect local evidence."}
    # T-600: the structured result is authoritative. Checked before the auth keywords because a
    # limit response is also an error response and must not be mistaken for a logged-out session.
    if fields.get("api_error") in LIMIT_API_ERRORS or fields.get("api_error_status") == 429 or any(word in lower for word in (
        "usage limit", "usage_limit", "rate limit", "rate_limit", "limit reached",
        "session limit", "weekly limit", "hit your limit",
        "out of extra usage", "usage exhausted", "quota exceeded", "resource_exhausted", "exceeded your current quota",
    )):
        hint = limit_reset_hint(str(fields.get("result") or output))
        return {"status": "blocked", "error_category": "subscription_limit",
                "summary": prefix + f" {label} subscription usage limit reached" + (f"; resets {hint}." if hint else "."),
                "limit_resets": hint,
                "need": "Wait for the subscription limit to reset; the worker resumes automatically. Do not enable pay-as-you-go API billing."}
    if any(word in lower for word in (
        "not logged in", "not logged into", "please log in", "please login",
        "login required", "authentication required", "not authenticated",
        "oauth token expired", "oauth expired", "session expired",
        "authentication_error", "unauthorized", "invalid oauth",
        "please set an auth method", "api key not found", "gemini_api_key", "login with google",
    )):
        need = ("On EC2 run `NO_BROWSER=true gemini` in the Gemini worker checkout, choose Login with Google and sign in again; never enter an API key."
                if agent == "gemini" else
                "On the existing EC2, ec2-user must check 'claude auth status' and complete official subscription login if needed; do not use API billing.")
        return {"status": "blocked", "error_category": "subscription_auth_required",
                "summary": prefix + " Subscription authentication unavailable.",
                "need": need}
    if any(word in lower for word in (
        "permission denied", "permissions denied", "tool use denied",
        "tool permission", "not allowed to use", "disallowed tool",
    )):
        return {"status": "blocked", "error_category": "permission_policy",
                "summary": prefix + " Headless tool permissions blocked execution.",
                "need": "Review the permitted CLI tools and local evidence without bypassing safety restrictions."}
    if "could not start" in lower or "command not found" in lower:
        cli = "gemini" if agent == "gemini" else "claude"
        return {"status": "blocked", "error_category": f"{cli}_cli_unavailable",
                "summary": prefix + f" {label} CLI is unavailable.",
                "need": f"Check 'command -v {cli}' and '{cli} --version' on the existing worker host."}
    return {"status": "failed", "error_category": "missing_status",
            "summary": prefix + (f" {label} returned nonzero; inspect redacted local evidence."
                                  if exit_code not in (0, None) else
                                  f" {label} returned without a verified completion record.")}


def _load_status(path: pathlib.Path, *, exit_code: int | None = None,
                 timed_out: bool = False, output: str = "", agent: str = "claude") -> dict[str, Any]:
    if not path.exists():
        return diagnose_missing_status(exit_code=exit_code, timed_out=timed_out, output=output, agent=agent)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"status": "failed", "summary": f"invalid status.json: {type(exc).__name__}"}
    if not isinstance(value, dict):
        return {"status": "failed", "summary": "status.json is not an object"}
    return value


def _tail(value: Any) -> str:
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value or "")
    return text[-OUTPUT_TAIL_CHARS:]


def _roadmap_task_done(repo: pathlib.Path, task_id: str) -> bool:
    path = repo / "ROADMAP.md"
    if not path.exists():
        return False
    pattern = re.compile(rf"^- \[[xX]\]\s+{re.escape(task_id)}\s")
    return any(pattern.match(line.strip()) for line in path.read_text(encoding="utf-8").splitlines())


def verify_evidence(spec: dict[str, Any], evidence: dict[str, Any]) -> list[str]:
    """Return a list of violations; empty means the result can be trusted as reported."""
    violations: list[str] = []
    before, after = evidence["before"], evidence["after"]
    task_id = spec["task_id"]
    status = evidence["status"]
    if after["branch"] != spec["branch"]:
        violations.append(f"branch changed from {spec['branch']} to {after['branch'] or 'detached'}")
    if after["branch"] in PROTECTED_BRANCHES:
        violations.append("agent ended on a protected branch")
    for name, sha in before["protected_refs"].items():
        if after["protected_refs"].get(name) != sha:
            violations.append(f"protected branch {name} was modified")
    if after.get("remote_refs") != before.get("remote_refs"):
        violations.append("remote-tracking refs changed during delegation (push detected)")
    reported = str(status.get("task") or "")
    if reported and reported != task_id:
        violations.append(f"agent reported task {reported}; pinned task is {task_id}")
    if evidence.get("timed_out"):
        violations.append(f"agent exceeded {spec['timeout_seconds']}s bound")
    if evidence.get("exit_code") not in (0, None) and str(status.get("status") or "").lower() == "done":
        violations.append("CLI exited nonzero; cannot accept a done status")
    if str(status.get("status") or "").lower() == "done":
        commits = evidence["commits"]
        if len(commits) != 1:
            violations.append(f"done requires exactly one task commit, found {len(commits)}")
        elif task_id not in commits[0]["subject"]:
            violations.append(f"commit subject does not reference {task_id}")
        elif status.get("commit") and not commits[0]["sha"].startswith(str(status["commit"])):
            violations.append("status.json commit does not match the captured commit")
        if not evidence["roadmap_done"]:
            violations.append(f"{task_id} reported done but ROADMAP checkbox was not closed")
    return violations


def run_state_path(repo: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(repo) / ".autopilot" / "run.json"


def write_run_state(repo: pathlib.Path, payload: dict[str, Any]) -> None:
    """Parent-owned, atomically replaced run record (never model-authored)."""
    path = run_state_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def read_run_state(repo: pathlib.Path) -> dict[str, Any]:
    try:
        value = json.loads(run_state_path(repo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _iso(stamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(stamp))


def run_delegation(spec: dict[str, Any], *, runner: Runner = subprocess.run,
                   venv_fn: Callable[[pathlib.Path], tuple[pathlib.Path | None, str]] = ensure_venv) -> dict[str, Any]:
    """Execute a delegation spec and return captured, verified evidence."""
    repo = pathlib.Path(spec["repo"])
    venv, venv_note = venv_fn(repo)
    status_path = repo / ".autopilot" / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.unlink(missing_ok=True)
    before = git_snapshot(repo)
    started = time.time()
    run_id = "run-" + time.strftime("%Y%m%d%H%M%S", time.gmtime(started)) + "-" + secrets.token_hex(3)
    run_state = {
        "run_id": run_id,
        "task": spec["task_id"],
        "state": "running",
        "branch": spec["branch"],
        "head_before": before["head"],
        "started_at": _iso(started),
        "pid": os.getpid(),
        "source": "parent",
    }
    # status.json is removed so the agent must write a fresh one; run.json keeps
    # the live task/run visible to the heartbeat while the CLI is working.
    write_run_state(repo, run_state)
    agent = str(spec.get("agent") or "claude")
    keep: tuple[str, ...] = ()
    if agent == "gemini":
        gemini_settings_path(repo).write_text(
            json.dumps(gemini_settings(int(spec["max_turns"]), str(spec.get("gemini_auth") or "google")), indent=2) + "\n",
            encoding="utf-8")
    # Only the owner's opt-in free-tier key survives; every other key/credential variable is still stripped.
    keep = ("GEMINI_API_KEY",) if spec.get("gemini_auth") == GEMINI_KEY_AUTH else ()
    exit_code: int | None = None
    output = ""
    timed_out = False
    try:
        result = runner(
            spec["cmd"],
            cwd=repo,
            env={**venv_env(delegated_env(keep=keep), venv), **(spec.get("env_extra") or {})},
            timeout=spec["timeout_seconds"],
            check=False,
            text=True,
            capture_output=True,
        )
        exit_code = int(result.returncode)
        output = _tail(result.stdout) + _tail(result.stderr)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = _tail(exc.stdout) + _tail(exc.stderr)
    except OSError as exc:
        # e.g. claude CLI missing: a failed run, never a ghost "running" record.
        output = f"{AGENT_LABELS.get(agent, 'Claude')} CLI could not start: {type(exc).__name__}"
    after = git_snapshot(repo)
    commits = []
    if before["head"] and after["head"] and before["head"] != after["head"]:
        log = _git(repo, "log", "--format=%H%x09%s", f"{before['head']}..{after['head']}")
        for line in filter(None, log.splitlines()):
            sha, _, subject = line.partition("\t")
            files = _git(repo, "show", "--name-only", "--format=", sha).splitlines()
            commits.append({"sha": sha, "subject": subject, "files": [f for f in files if f]})
    evidence = {
        "task_id": spec["task_id"],
        "branch": spec["branch"],
        "max_turns": spec["max_turns"],
        "timeout_seconds": spec["timeout_seconds"],
        "auth_mode": spec["auth_mode"],
        "started_at": started,
        "duration_seconds": round(time.time() - started, 3),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "python_env": venv_note,
        "before": before,
        "after": after,
        "commits": commits,
        "roadmap_done": _roadmap_task_done(repo, spec["task_id"]),
        "agent": agent,
        "status": _load_status(status_path, exit_code=exit_code, timed_out=timed_out, output=output, agent=agent),
        "output_tail": _safe_cli_output(output),
        "pushed": after.get("remote_refs") != before.get("remote_refs"),
        "deploy_credentials_scrubbed": True,
    }
    violations = verify_evidence(spec, evidence)
    reported = str(evidence["status"].get("status") or "failed").strip().lower()
    if reported not in {"done", "blocked", "failed"}:
        reported = "failed"
    evidence["violations"] = violations
    evidence["result"] = "failed" if violations else reported
    evidence["run_id"] = run_id
    write_run_state(repo, {
        **run_state,
        "state": evidence["result"],
        "finished_at": _iso(time.time()),
        "exit_code": exit_code,
        "timed_out": timed_out,
        "commit": commits[0]["sha"] if len(commits) == 1 else "",
        "violations": len(violations),
    })
    return evidence


def write_evidence(repo: pathlib.Path, evidence: dict[str, Any]) -> pathlib.Path:
    path = pathlib.Path(repo) / ".autopilot" / "evidence" / f"{evidence['task_id']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def result_payload(evidence: dict[str, Any]) -> dict[str, Any]:
    """Compact, secret-free payload for FactoryOS task-result ingestion."""
    status = evidence.get("status") or {}
    commits = evidence.get("commits") or []
    return {
        "task_id": evidence["task_id"],
        "pinned_task_id": evidence["task_id"],
        "result": evidence["result"],
        "branch": evidence["branch"],
        "summary": str(status.get("summary") or "")[:500],
        "need": str(status.get("need") or "")[:500],
        "checks": [str(x)[:300] for x in (status.get("checks") or [])][:20],
        "commit": commits[0]["sha"] if len(commits) == 1 else "",
        "commit_count": len(commits),
        "files": (commits[0]["files"] if len(commits) == 1 else [])[:100],
        "exit_code": evidence.get("exit_code"),
        "timed_out": bool(evidence.get("timed_out")),
        "duration_seconds": evidence.get("duration_seconds") or 0,
        "started_at": evidence.get("started_at"),
        "max_turns": evidence["max_turns"],
        "timeout_seconds": evidence["timeout_seconds"],
        "violations": list(evidence.get("violations") or [])[:20],
        "pushed": bool(evidence.get("pushed")),
        "deploy_credentials_scrubbed": True,
    }


def report_result(evidence: dict[str, Any], *, post: Callable[..., Any] | None = None) -> bool:
    """Best-effort POST of the result to FactoryOS; no-op without a worker token."""
    token = os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", "").strip()
    url = os.environ.get("FACTORYOS_URL", "").strip().rstrip("/")
    if not token or not url:
        return False
    if post is None:
        import requests

        post = requests.post
    try:
        response = post(
            f"{url}/api/claude-worker/task-result",
            headers={"Authorization": f"Bearer {token}"},
            json=result_payload(evidence),
            timeout=15,
        )
        return 200 <= int(getattr(response, "status_code", 0)) < 300
    except Exception:
        return False
