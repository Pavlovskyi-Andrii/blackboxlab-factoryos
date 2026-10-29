"""Claude delegation adapter.

Delegates exactly one pinned roadmap task to a Claude Code CLI invocation that
runs on the owner's subscription auth, with bounded turns/time, and captures
verifiable evidence (git state before/after, commits, status.json, output tail).

The adapter never pushes, never touches main/master and never deploys. Any
evidence of such an action turns the result into ``failed``.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
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
)
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
)
TASK_ID_RE = re.compile(r"^T-[A-Za-z0-9-]+$")

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
        "сделай один commit с ID задачи. Не трогай main и production."
    )


def build_delegation(
    task: dict[str, Any],
    repo: pathlib.Path,
    *,
    max_turns: int = 80,
    timeout_seconds: int = 3600,
    skip_permissions: bool = False,
) -> dict[str, Any]:
    """Return a pinned, bounded delegation spec for exactly one roadmap task."""
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
    cmd = [
        "claude",
        "-p",
        task_prompt(task),
        "--output-format",
        "json",
        "--max-turns",
        str(turns),
        "--disallowedTools",
        *DISALLOWED_TOOLS,
    ]
    if skip_permissions:
        cmd.append("--dangerously-skip-permissions")
    return {
        "task_id": task_id,
        "task_title": str(task.get("title") or ""),
        "repo": str(repo),
        "branch": branch,
        "max_turns": turns,
        "timeout_seconds": timeout,
        "cmd": cmd,
        "auth_mode": "subscription",
    }


def delegated_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in SCRUBBED_ENV:
        env.pop(key, None)
    return env


def _load_status(path: pathlib.Path) -> dict[str, Any]:
    if not path.exists():
        return {"status": "failed", "summary": "agent did not write .autopilot/status.json"}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "failed", "summary": f"invalid status.json: {exc}"}
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


def run_delegation(spec: dict[str, Any], *, runner: Runner = subprocess.run) -> dict[str, Any]:
    """Execute a delegation spec and return captured, verified evidence."""
    repo = pathlib.Path(spec["repo"])
    status_path = repo / ".autopilot" / "status.json"
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.unlink(missing_ok=True)
    before = git_snapshot(repo)
    started = time.time()
    exit_code: int | None = None
    output = ""
    timed_out = False
    try:
        result = runner(
            spec["cmd"],
            cwd=repo,
            env=delegated_env(),
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
        "before": before,
        "after": after,
        "commits": commits,
        "roadmap_done": _roadmap_task_done(repo, spec["task_id"]),
        "status": _load_status(status_path),
        "output_tail": output[-OUTPUT_TAIL_CHARS:],
        "pushed": after.get("remote_refs") != before.get("remote_refs"),
        "deploy_credentials_scrubbed": True,
    }
    violations = verify_evidence(spec, evidence)
    reported = str(evidence["status"].get("status") or "failed").strip().lower()
    if reported not in {"done", "blocked", "failed"}:
        reported = "failed"
    evidence["violations"] = violations
    evidence["result"] = "failed" if violations else reported
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
