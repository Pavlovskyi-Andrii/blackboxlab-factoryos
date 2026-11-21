"""Zero-API-billing local recovery supervisor for the subscription Claude worker.

Runs from a systemd timer with root privileges. No passwords, cookies, OAuth
tokens or account codes are read or logged; only Claude CLI's auth *status* is
queried as the unprivileged worker user. Never attempts OAuth on its own.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from typing import NamedTuple

try:
    from . import worker_heartbeat
except ImportError:  # pragma: no cover - run as a plain script
    import worker_heartbeat

ENV_FILE = Path("/etc/factoryos/claude-worker.env")
STATUS_FILE = Path("/var/lib/factoryos/supervisor-status.json")
RESTART_FILE = Path("/var/lib/factoryos/supervisor-restarts.json")
WORKER_SERVICE = "factoryos-claude-worker.service"
WORKER_USER = "ec2-user"
# T-714: loop-heartbeat watchdog. The supervisor timer (every minute, root) restarts a worker whose own loop stopped
# beating .autopilot/<file> past the deadline it promised (15 min, longer before a Claude CLI run).
SURFER_SERVICE = "factoryos-surfer-worker.service"
WATCHDOG_RESTART_FILE = Path("/var/lib/factoryos/watchdog-restarts.json")
WATCHDOG_UNITS = (
    ("claude_worker", WORKER_SERVICE, worker_heartbeat.CLAUDE_LOOP_FILE),
    ("surfer_worker", SURFER_SERVICE, worker_heartbeat.SURFER_FILE),
)
STARTUP_GRACE_SECONDS = 300
MAX_RESTARTS_PER_HOUR = 3
MIN_RESTART_INTERVAL_SECONDS = 120
PAID_KEYS = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_USE_FOUNDRY",
)


class Plan(NamedTuple):
    action: str
    status: str
    reason: str


def parse_env(path: Path) -> dict[str, str]:
    """Read only necessary config; callers must never display values."""
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def preflight_reasons(
    *,
    has_repo: bool,
    branch: str,
    token_set: bool,
    subscription_logged_in: bool,
    paid_credentials_found: bool,
    claude_installed: bool,
) -> list[str]:
    """Refuse to execute if any required safety or readiness gate fails."""
    reasons = []
    if paid_credentials_found:
        reasons.append("paid_api_credentials")
    if not has_repo:
        reasons.append("repo_missing")
    if not branch or branch in ("main", "master"):
        reasons.append("unsafe_branch")
    if not token_set:
        reasons.append("factoryos_worker_token_missing")
    if not claude_installed:
        reasons.append("claude_cli_missing")
    elif not subscription_logged_in:
        reasons.append("subscription_auth_required")
    return reasons


def choose_action(
    reasons: list[str],
    service_active: str,
    recent_attempts: list[float],
    now: float,
) -> Plan:
    """Pure policy: bounded restarts, fail closed on auth and spending."""
    if reasons:
        # Stop even an active worker if the paid API guard/auth guard is broken.
        return Plan(
            "stop" if service_active in ("active", "activating") else "none",
            "blocked",
            ",".join(reasons),
        )
    if service_active in ("active", "activating"):
        return Plan("none", "running", "service_active")
    recent = sorted(float(t) for t in recent_attempts if now - 3600 <= t <= now)
    if len(recent) >= MAX_RESTARTS_PER_HOUR:
        return Plan("none", "needs_owner", "restart_budget_exhausted")
    if recent and now - recent[-1] < MIN_RESTART_INTERVAL_SECONDS:
        return Plan("none", "cooldown", "waiting_before_restart")
    return Plan("start", "recovering", "approved_safe_restart")


def watchdog_decision(
    *,
    supposed_to_run: bool,
    service_state: str,
    active_since: float | None,
    beat: dict,
    recent_attempts: list[float],
    now: float,
) -> Plan:
    """T-714 pure policy: restart a running unit whose loop heartbeat broke its deadline (bounded, like choose_action).

    Never acts on a unit that is not supposed to run, on a freshly started one, or on one that never beat since it
    started (old code without the heartbeat, or a different checkout): only a broken promise counts as "hung"."""
    if not supposed_to_run:
        return Plan("none", "not_expected", "unit_not_expected")
    recent = sorted(float(t) for t in recent_attempts if now - 3600 <= t <= now)
    budget_left = len(recent) < MAX_RESTARTS_PER_HOUR
    if service_state == "failed":
        # systemd gave up after its own StartLimitBurst; a bounded retry here, then the owner.
        return Plan("restart", "recovering", "unit_failed") if budget_left else Plan(
            "none", "needs_owner", "restart_budget_exhausted")
    if service_state != "active":
        return Plan("none", "not_running", "service_" + (service_state or "unknown"))
    if active_since is None or now - active_since < STARTUP_GRACE_SECONDS:
        return Plan("none", "starting", "startup_grace")
    if not beat:
        return Plan("none", "unknown", "no_loop_heartbeat")
    if beat["at"] + 5 < active_since:
        return Plan("none", "unknown", "no_loop_heartbeat_since_start")
    if now <= beat["deadline"]:
        return Plan("none", "ok", "loop_heartbeat_fresh")
    if not budget_left:
        return Plan("none", "needs_owner", "restart_budget_exhausted")
    if recent and now - recent[-1] < MIN_RESTART_INTERVAL_SECONDS:
        return Plan("none", "cooldown", "waiting_before_restart")
    return Plan("restart", "recovering", "loop_heartbeat_stale")


def command(argv: list[str], *, timeout: int = 15) -> tuple[int, str]:
    try:
        p = subprocess.run(
            argv, text=True, capture_output=True, timeout=timeout, check=False
        )
        return p.returncode, (p.stdout or "").strip()
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""


def subscription_status() -> tuple[bool, bool]:
    """Boolean only; never print or persist auth details or token material."""
    rc, output = command(
        ["runuser", "-u", WORKER_USER, "--", "claude", "auth", "status"],
        timeout=20,
    )
    if not output:
        # "auth status" may return a non-zero exit code for logged-out users.
        # Probe --version separately so we don't misdiagnose missing CLI.
        version_rc, _ = command(["runuser", "-u", WORKER_USER, "--", "claude", "--version"])
        return version_rc == 0, False
    try:
        obj = json.loads(output)
    except (ValueError, TypeError):
        version_rc, _ = command(["runuser", "-u", WORKER_USER, "--", "claude", "--version"])
        return version_rc == 0, False
    # The CLI may use different names for subscription OAuth. Do not accept
    # api_key/console login as a substitute for a paid Claude subscription.
    method = str(obj.get("authMethod") or "").lower().strip()
    provider = str(obj.get("apiProvider") or "").strip()
    valid = (
        obj.get("loggedIn") is True
        and provider == "firstParty"
        and method not in ("", "none", "api_key", "api-key", "console")
    )
    return True, valid and rc == 0


def read_attempts(path: Path, now: float) -> list[float]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [float(t) for t in raw if isinstance(t, (int, float))
                and now - 3600 <= float(t) <= now]
    except (OSError, ValueError, TypeError):
        return []


def save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)
    path.chmod(0o600)


def publish_report(path: Path, report: dict) -> None:
    """T-596: world-readable copy for the unprivileged worker's heartbeat.

    The report holds booleans and short state codes only (no tokens or command output), so 0644
    is safe; STATUS_FILE itself stays 0600 under the root-only /var/lib/factoryos."""
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.chmod(0o644)
        os.replace(tmp, path)
    except OSError:
        pass


def unit_active_since(unit: str) -> float | None:
    """Wall-clock time the unit last became active (from systemd's monotonic stamp and /proc/uptime)."""
    rc, raw = command(["systemctl", "show", unit, "-p", "ActiveEnterTimestampMonotonic", "--value"], timeout=10)
    try:
        entered = int(raw) / 1_000_000
        uptime = float(Path("/proc/uptime").read_text(encoding="utf-8").split()[0])
    except (ValueError, OSError, IndexError):
        return None
    if rc or entered <= 0:
        return None
    return time.time() - max(0.0, uptime - entered)


def read_watchdog_attempts(path: Path, now: float) -> dict[str, list[float]]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    return {str(k): [float(t) for t in v if isinstance(t, (int, float)) and now - 3600 <= float(t) <= now]
            for k, v in raw.items() if isinstance(v, list)}


def run_watchdog(repo: Path, claude_expected: bool, now: float, *, cmd=None, active_since=None,
                 attempts_file: Path | None = None) -> dict[str, str]:
    """Check both worker loops; restart a hung one. Returns {"watchdog_<name>": "<status>:<reason>"}."""
    cmd = cmd or command
    active_since = active_since or unit_active_since
    attempts_file = attempts_file or WATCHDOG_RESTART_FILE
    attempts = read_watchdog_attempts(attempts_file, now)
    out: dict[str, str] = {}
    for name, unit, beat_file in WATCHDOG_UNITS:
        rc, raw_state = cmd(["systemctl", "is-active", unit], timeout=10)
        state = raw_state if raw_state in ("active", "activating", "inactive", "failed", "deactivating") else "unknown"
        if name == "claude_worker":
            expected = claude_expected
        else:
            # The Surfer unit is optional: it is supposed to run once the owner enabled it (T-714-H).
            expected = cmd(["systemctl", "is-enabled", unit], timeout=10)[1] == "enabled"
        plan = watchdog_decision(
            supposed_to_run=expected, service_state=state,
            active_since=active_since(unit) if state == "active" else None,
            beat=worker_heartbeat.read(worker_heartbeat.path_for(repo, beat_file)),
            recent_attempts=attempts.get(name, []), now=now,
        )
        status, reason = plan.status, plan.reason
        if plan.action == "restart":
            attempts.setdefault(name, []).append(now)
            save_json(attempts_file, attempts)
            cmd(["systemctl", "reset-failed", unit], timeout=10)
            rc, _ = cmd(["systemctl", "restart", "--no-block", unit], timeout=25)
            status, reason = ("failed", "systemd_restart_failed") if rc else ("restart", reason)
        out["watchdog_" + name] = f"{status}:{reason}"
    return out


def run_once(now: float | None = None) -> dict[str, object]:
    now = time.time() if now is None else now
    env = parse_env(ENV_FILE)
    repo = Path(env.get("AUTOPILOT_REPO") or "/opt/factoryos")
    has_repo = (repo / ".git").exists() and (repo / "ROADMAP.md").is_file()
    rc, branch = command(["git", "-C", str(repo), "branch", "--show-current"]) if has_repo else (1, "")
    if rc:
        branch = ""
    paid_env = any(env.get(k) for k in PAID_KEYS) or any(os.environ.get(k) for k in PAID_KEYS)
    token = bool(env.get("FACTORY_CLAUDE_WORKER_TOKEN"))
    available, logged_in = subscription_status()
    rc, raw_state = command(["systemctl", "is-active", WORKER_SERVICE], timeout=10)
    state = raw_state if raw_state in ("active", "activating", "inactive", "failed", "deactivating") else "unknown"
    reasons = preflight_reasons(
        has_repo=has_repo, branch=branch, token_set=token,
        subscription_logged_in=logged_in, paid_credentials_found=paid_env,
        claude_installed=available,
    )
    attempts = read_attempts(RESTART_FILE, now)
    decision = choose_action(reasons, state, attempts, now)
    result_status = decision.status
    result_reason = decision.reason
    if decision.action == "stop":
        rc, _ = command(["systemctl", "stop", WORKER_SERVICE], timeout=30)
        if rc:
            result_status, result_reason = "failed", "cannot_stop_unready_worker"
    elif decision.action == "start":
        # A failed systemd unit may have exhausted its own StartLimitBurst.
        # Do not reset the start limit repeatedly: local rate cap is separate.
        attempts.append(now)
        save_json(RESTART_FILE, attempts)
        rc, _ = command(["systemctl", "start", "--no-block", WORKER_SERVICE], timeout=25)
        if rc:
            result_status, result_reason = "failed", "systemd_start_failed"
    # No secrets, access tokens or detailed command outputs in status/logs.
    report: dict[str, object] = {
        "checked_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
        "component": "claude_subscription_worker",
        "status": result_status,
        "reason": result_reason,
        "service_state": state,
        "branch": branch[:120],
        "subscription_authenticated": bool(logged_in),
        "factoryos_token_configured": token,
        "paid_api_credentials_present": bool(paid_env),
        "restart_attempts_last_hour": len(attempts),
        "recovery_action": decision.action,
    }
    try:
        report.update(run_watchdog(repo, decision.action == "none" and result_status == "running", now))
    except Exception as exc:  # the watchdog must never break the subscription supervisor
        report["watchdog_claude_worker"] = report["watchdog_surfer_worker"] = "failed:" + type(exc).__name__
    save_json(STATUS_FILE, report)
    if has_repo:
        publish_report(repo / ".autopilot" / "supervisor.json", report)
    print(json.dumps(report, ensure_ascii=False))
    return report


if __name__ == "__main__":
    try:
        run_once()
    except Exception as exc:  # no sensitive exception payload in service logs
        print(json.dumps({"component": "claude_subscription_worker", "status": "failed",
                          "reason": "supervisor_internal_error",
                          "exception_type": type(exc).__name__}))
        sys.exit(1)
