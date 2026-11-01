import calendar
import json
import os
import pathlib
import re
import socket
import subprocess
import sys
import threading
import time

import requests

REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO", ".")).resolve()
FACTORY_URL = os.environ.get("FACTORYOS_URL", "https://blackboxlab-factoryos.onrender.com").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", "").strip()
SUBSCRIPTION = os.environ.get("CLAUDE_SUBSCRIPTION_LABEL", "Pro").strip() or "Pro"
HEARTBEAT_SECONDS = max(10, min(60, int(os.environ.get("FACTORY_CLAUDE_HEARTBEAT_SECONDS", "20"))))
_stop = threading.Event()


def current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    return result.stdout.strip()


def claude_version() -> str:
    result = subprocess.run(
        ["claude", "--version"],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError("Claude Code CLI is not installed or not on PATH")
    return (result.stdout or result.stderr).strip().splitlines()[0][:120]


def _pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError, TypeError):
        return False
    return True


def run_snapshot() -> dict:
    """Parent-owned live run record written by autopilot.delegation."""
    try:
        value = json.loads((REPO / ".autopilot" / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    if value.get("state") == "running" and not _pid_alive(value.get("pid")):
        # The parent died mid-run: report it, never a ghost "running".
        value = {**value, "state": "stale"}
    return value


def task_snapshot() -> tuple[str, str, str]:
    run = run_snapshot()
    if run.get("state") in ("running", "stale"):
        detail = f"Claude CLI run {run.get('run_id') or '?'} started {run.get('started_at') or '?'}"
        if run["state"] == "stale":
            detail = "Autopilot parent process is gone; " + detail
        return str(run.get("task") or ""), str(run["state"]), detail[:500]
    path = REPO / ".autopilot" / "status.json"
    if not path.exists():
        return "", "idle", ""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "", "idle", ""
    if not isinstance(value, dict):
        return "", "idle", ""
    return (
        str(value.get("task") or ""),
        str(value.get("status") or "idle"),
        str(value.get("summary") or value.get("need") or "")[:500],
    )


def supervisor_snapshot() -> dict:
    """Secret-free systemd/OAuth report published by autopilot.supervisor (absent = unknown)."""
    try:
        value = json.loads((REPO / ".autopilot" / "supervisor.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(value, dict):
        return {}
    keep = ("checked_at", "status", "reason", "service_state", "subscription_authenticated",
            "restart_attempts_last_hour", "recovery_action")
    return {k: value[k] for k in keep if k in value}


_STARTED = time.time()
_cpu_prev = None  # last (idle, total) jiffies from /proc/stat; the delta between heartbeats is the CPU percent
_ROADMAP_OPEN_RE = re.compile(r"^- \[ \]\s+T-[A-Za-z0-9-]+\s")


def _git(*args) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=REPO, text=True, capture_output=True, check=False, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def _iso_epoch(value):
    try:
        return float(calendar.timegm(time.strptime(str(value), "%Y-%m-%dT%H:%M:%SZ")))
    except (ValueError, OverflowError):
        return None


def cpu_sample(proc="/proc"):
    """(percent, source). /proc/stat delta when readable (Linux, older Termux); else loadavg/cores; else unsupported."""
    global _cpu_prev
    try:
        with open(os.path.join(proc, "stat"), encoding="ascii") as handle:
            fields = [int(x) for x in handle.readline().split()[1:]]
        idle, total = fields[3] + (fields[4] if len(fields) > 4 else 0), sum(fields[:8])
    except (OSError, ValueError, IndexError):
        idle = total = None
    if total is not None:
        prev, _cpu_prev = _cpu_prev, (idle, total)
        if prev and total > prev[1]:
            return round(max(0.0, min(100.0, 100.0 * (1 - (idle - prev[0]) / (total - prev[1])))), 1), "proc_stat"
        # First sample has no delta yet; fall through to loadavg instead of inventing a number.
    try:
        load = os.getloadavg()[0]
        cores = os.cpu_count() or 1
        return round(max(0.0, min(100.0, 100.0 * load / cores)), 1), "loadavg"
    except (OSError, AttributeError):
        return None, "unsupported"


def memory_sample(proc="/proc"):
    """(used_mb, total_mb, source) from /proc/meminfo; unsupported elsewhere."""
    try:
        values = {}
        with open(os.path.join(proc, "meminfo"), encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                values[key] = int(rest.split()[0])
        total = values["MemTotal"]
        available = values.get("MemAvailable", values.get("MemFree", 0) + values.get("Cached", 0))
    except (OSError, ValueError, KeyError, IndexError):
        return None, None, "unsupported"
    return round((total - available) / 1024.0, 1), round(total / 1024.0, 1), "proc_meminfo"


def queue_depth():
    """Unchecked, non-HUMAN ROADMAP tasks (the worker's remaining queue); None when ROADMAP is unreadable."""
    try:
        lines = (REPO / "ROADMAP.md").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    return sum(1 for line in lines if _ROADMAP_OPEN_RE.match(line.strip()))


def collect_telemetry(task_state: str, run: dict, *, proc="/proc", now=None) -> dict:
    """T-536-B: secret-free runtime telemetry. Unknown values are None with an explicit source, never guessed."""
    now = time.time() if now is None else now
    started = _iso_epoch(run.get("started_at")) if run.get("state") == "running" else None
    cpu, cpu_source = cpu_sample(proc)
    memory, memory_total, memory_source = memory_sample(proc)
    return {
        "available": True,
        "stage": task_state or "idle",
        "task_started_at": started,
        "elapsed_seconds": round(max(0.0, now - started), 1) if started is not None else None,
        "branch": current_branch() or None,
        "head_sha": _git("rev-parse", "HEAD") or None,
        "queue_depth": queue_depth(),
        "cpu_percent": cpu, "cpu_source": cpu_source,
        "memory_mb": memory, "memory_total_mb": memory_total, "memory_source": memory_source,
        "worker_uptime_seconds": round(max(0.0, now - _STARTED), 1),
    }


def heartbeat(version: str, *, state: str = "") -> None:
    if not WORKER_TOKEN:
        return
    task_id, task_state, detail = task_snapshot()
    run = run_snapshot()
    payload = {
        "run_id": str(run.get("run_id") or "") if run.get("task") == task_id else "",
        "run_started_at": str(run.get("started_at") or "") if run.get("task") == task_id else "",
        "node_id": os.environ.get("FACTORY_CLAUDE_NODE_ID", socket.gethostname() or "claude-pro-runner"),
        "hostname": socket.gethostname(),
        "platform": sys.platform,
        "claude_version": version,
        "auth_mode": "subscription",
        "subscription": SUBSCRIPTION,
        "branch": current_branch(),
        "repo": REPO.name,
        "status": state or task_state or "idle",
        "task_id": task_id,
        "last_error": detail if (state == "failed" or task_state == "failed") else "",
        "supervisor": supervisor_snapshot(),
        "telemetry": collect_telemetry(state or task_state or "idle", run if run.get("task") == task_id else {}),
    }
    response = requests.post(
        f"{FACTORY_URL}/api/claude-worker/heartbeat",
        headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


CODE_UPDATED = 75  # autopilot.EXIT_CODE_UPDATED


def heartbeat_loop(version: str) -> None:
    while not _stop.wait(HEARTBEAT_SECONDS):
        try:
            heartbeat(version)
        except Exception:
            pass


def main() -> int:
    if os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise SystemExit(
            "Refusing to start: ANTHROPIC_API_KEY is set. "
            "Remove it to keep Claude Code on the Pro/Max subscription instead of PAYG API billing."
        )
    if not WORKER_TOKEN:
        raise SystemExit("FACTORY_CLAUDE_WORKER_TOKEN is required. Copy it from FactoryOS Connections.")
    os.environ.setdefault("AUTOPILOT_REPO", str(REPO))
    # The autopilot child reports delegation evidence to the same FactoryOS instance.
    os.environ.setdefault("FACTORYOS_URL", FACTORY_URL)
    version = claude_version()
    branch = current_branch()
    if not branch or branch in {"main", "master"}:
        raise SystemExit("Checkout a dedicated non-main autopilot branch before starting the Claude Pro Worker.")

    heartbeat(version, state="online")
    thread = threading.Thread(target=heartbeat_loop, args=(version,), daemon=True, name="factoryos-claude-heartbeat")
    thread.start()
    try:
        result = subprocess.run([sys.executable, "-m", "autopilot.autopilot"], cwd=REPO, check=False)
        if result.returncode == CODE_UPDATED:
            # The runner merged new code from main between tasks: re-exec so this parent runs it too.
            heartbeat(version, state="online")
            _stop.set()
            thread.join(timeout=2)
            os.execv(sys.executable, [sys.executable, "-m", "autopilot.claude_pro_worker"])
        heartbeat(version, state="idle" if result.returncode == 0 else "failed")
        return int(result.returncode)
    finally:
        _stop.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
