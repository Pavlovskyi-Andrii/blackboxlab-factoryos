"""FactoryOS Gemini CLI lane worker (Issue #119): the gemini counterpart of autopilot.claude_pro_worker.

Starts the shared autopilot runner with AUTOPILOT_OPERATOR=gemini in its own checkout on a gemini/* branch and
publishes a secret-free operator heartbeat. The runner claims only `Owner: gemini` ROADMAP tasks through the
existing Relay roadmap-claim (run_id fencing, events, heartbeats). Nothing is faked: a missing CLI or login is
reported as `unconfigured` with the exact reason, a spend-guard hit as `refused`, and no task is claimed then.

    python3 -m autopilot.gemini_worker            # run (systemd: deploy/gemini-worker/)
    python3 -m autopilot.gemini_worker --check    # one readiness report for the owner, no model call
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time

from autopilot import gemini_executor

REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO", ".")).resolve()
FACTORY_URL = os.environ.get("FACTORYOS_URL", "https://blackboxlab-factoryos.onrender.com").strip().rstrip("/")
HEARTBEAT_SECONDS = max(10, min(60, int(os.environ.get("FACTORY_GEMINI_HEARTBEAT_SECONDS", "20"))))
PREFLIGHT_CACHE_SECONDS = 300
CODE_UPDATED = 75      # autopilot.EXIT_CODE_UPDATED
EXIT_REFUSED = 3
_stop = threading.Event()
_preflight_cache: dict = {"at": 0.0, "value": None}


def readiness(now: float | None = None, *, check=None) -> dict:
    now = time.time() if now is None else now
    if _preflight_cache["value"] is None or now - _preflight_cache["at"] >= PREFLIGHT_CACHE_SECONDS:
        _preflight_cache["value"] = (check or gemini_executor.preflight)(REPO)
        _preflight_cache["at"] = now
    return _preflight_cache["value"]


def run_snapshot() -> dict:
    try:
        value = json.loads((REPO / ".autopilot" / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def status_snapshot() -> dict:
    try:
        value = json.loads((REPO / ".autopilot" / "status.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def heartbeat_payload(version: str, ready: dict, *, state: str = "") -> dict:
    """Fields of the server's OperatorWorkerHeartbeat model only; reasons are redacted and bounded."""
    run, status = run_snapshot(), status_snapshot()
    running = run.get("state") == "running"
    task_id = str(run.get("task") or "") if running else str(status.get("task") or "")
    lane_state = ready.get("state") or "unconfigured"
    if lane_state != "ready":
        shown, error = lane_state, "; ".join(gemini_executor.redact(r) for r in ready.get("reasons") or [])
    else:
        shown = state or ("running" if running else str(status.get("status") or "idle"))
        error = gemini_executor.redact(status.get("summary") or "") if shown in ("failed", "blocked") else ""
    return {
        "operator_id": "gemini",
        "node_id": os.environ.get("FACTORY_WORKER_NODE_ID") or ("gemini-" + socket.gethostname()),
        "hostname": socket.gethostname(),
        "runtime": "gemini-cli",
        "version": version or ready.get("version") or "",
        "auth_mode": "google_login_personal",
        "branch": str(ready.get("branch") or ""),
        "repo": REPO.name,
        "status": shown[:40],
        "task_id": task_id[:80],
        "stage": ("running" if running else shown)[:40],
        "queue_depth": 0,
        "tickets": [],
        "last_result": str(status.get("status") or "")[:40],
        "last_error": " ".join(error.split())[:500],
    }


def heartbeat(version: str, *, state: str = "", post=None) -> bool:
    """Best-effort POST to /api/operator-worker/heartbeat; needs FACTORY_OPERATOR_WORKER_TOKEN (else no-op)."""
    token = os.environ.get("FACTORY_OPERATOR_WORKER_TOKEN", "").strip()
    if not token or not FACTORY_URL:
        return False
    payload = heartbeat_payload(version, readiness(), state=state)
    if post is None:
        import requests
        post = requests.post
    try:
        response = post(f"{FACTORY_URL}/api/operator-worker/heartbeat",
                        headers={"Authorization": f"Bearer {token}"}, json=payload, timeout=15)
        return 200 <= int(getattr(response, "status_code", 0)) < 300
    except Exception:
        return False


def heartbeat_loop(version: str) -> None:
    while not _stop.wait(HEARTBEAT_SECONDS):
        heartbeat(version)


def startup_problems(env: dict | None = None) -> list[str]:
    """Hard refusals before anything starts (names only, never values)."""
    env = dict(os.environ if env is None else env)
    problems = gemini_executor.spend_guard(env, REPO, gemini_executor.gemini_home(env))
    if not str(env.get("FACTORY_CLAUDE_WORKER_TOKEN") or "").strip():
        problems.append("FACTORY_CLAUDE_WORKER_TOKEN (Relay worker credential for roadmap-claim) is not set")
    return problems


def check() -> int:
    ready = gemini_executor.preflight(REPO)
    hard = startup_problems()
    print(f"gemini lane: {ready['state'] if not hard else 'refused'}"
          + (f" · CLI {ready['version']}" if ready.get("version") else "")
          + (f" · branch {ready['branch']}" if ready.get("branch") else ""))
    for reason in dict.fromkeys(hard + list(ready.get("reasons") or [])):
        print("- " + gemini_executor.redact(reason))
    if not os.environ.get("FACTORY_OPERATOR_WORKER_TOKEN", "").strip():
        print("- note: FACTORY_OPERATOR_WORKER_TOKEN not set; the lane works but sends no operator heartbeat")
    return 0 if ready["state"] == "ready" and not hard else EXIT_REFUSED


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="FactoryOS Gemini CLI lane worker")
    parser.add_argument("--check", action="store_true", help="print lane readiness and exit (no model call)")
    args = parser.parse_args(argv)
    if args.check:
        return check()
    hard = startup_problems()
    if hard:
        print("Refusing to start the Gemini lane:\n- " + "\n- ".join(gemini_executor.redact(r) for r in hard),
              file=sys.stderr)
        return EXIT_REFUSED
    os.environ["AUTOPILOT_OPERATOR"] = "gemini"
    os.environ["AUTOPILOT_RELAY_ONLY"] = "0"
    os.environ["AUTOPILOT_MYCAST"] = "0"
    os.environ.setdefault("AUTOPILOT_REPO", str(REPO))
    os.environ.setdefault("FACTORYOS_URL", FACTORY_URL)
    ready = readiness()
    if not str(ready.get("branch") or "").startswith(gemini_executor.BRANCH_PREFIX):
        print(f"Checkout a dedicated {gemini_executor.BRANCH_PREFIX}* branch in {REPO} first.", file=sys.stderr)
        return EXIT_REFUSED
    version = str(ready.get("version") or "")
    heartbeat(version, state="online" if ready["state"] == "ready" else "")
    thread = threading.Thread(target=heartbeat_loop, args=(version,), daemon=True, name="factoryos-gemini-heartbeat")
    thread.start()
    try:
        result = subprocess.run([sys.executable, "-m", "autopilot.autopilot"], cwd=REPO, check=False)
        if result.returncode == CODE_UPDATED:
            _stop.set()
            thread.join(timeout=2)
            os.execv(sys.executable, [sys.executable, "-m", "autopilot.gemini_worker"])
        heartbeat(version, state="idle" if result.returncode == 0 else "failed")
        return int(result.returncode)
    finally:
        _stop.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
