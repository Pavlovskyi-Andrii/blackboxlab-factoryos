import json
import os
import pathlib
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
    }
    response = requests.post(
        f"{FACTORY_URL}/api/claude-worker/heartbeat",
        headers={"Authorization": f"Bearer {WORKER_TOKEN}"},
        json=payload,
        timeout=15,
    )
    response.raise_for_status()


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
        heartbeat(version, state="idle" if result.returncode == 0 else "failed")
        return int(result.returncode)
    finally:
        _stop.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
