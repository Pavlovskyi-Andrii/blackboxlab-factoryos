"""T-607 Gemini worker: the third engineering operator, on the owner's free Google-account login.

Same loop as the Claude Pro worker (autopilot.autopilot), with AUTOPILOT_OPERATOR=gemini and AUTOPILOT_AGENT=gemini:
it takes only ROADMAP tasks marked `Owner: gemini`, claims each one on the FactoryOS server (run_id fencing),
runs Gemini CLI headless in its own checkout and pushes only to its own worker branch. It never claims Relay owner
tickets, never answers owner questions and never runs Claude.

Run it from a separate checkout on a dedicated branch (e.g. ~/factoryos-gemini on autopilot/gemini-worker), with
FACTORY_GEMINI_WORKER_TOKEN set. Auth: the Google login (`NO_BROWSER=true gemini`), or, by owner opt-in,
FACTORY_GEMINI_AUTH=api-key-free-tier + GEMINI_API_KEY from an AI Studio project without billing.
"""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import threading

import requests

REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO", ".")).resolve()
FACTORY_URL = os.environ.get("FACTORYOS_URL", "https://blackboxlab-factoryos.onrender.com").strip().rstrip("/")
WORKER_TOKEN = os.environ.get("FACTORY_GEMINI_WORKER_TOKEN", "").strip()
HEARTBEAT_SECONDS = max(10, min(120, int(os.environ.get("FACTORY_GEMINI_HEARTBEAT_SECONDS", "30"))))
CODE_UPDATED = 75  # autopilot.EXIT_CODE_UPDATED
# Variables that would let Gemini CLI fall back to an API key (possibly billed) instead of the Google login.
KEY_VARIABLES = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_APPLICATION_CREDENTIALS")
# Owner opt-in (2026-11-15): an AI Studio key from a project WITHOUT billing. Only GEMINI_API_KEY is then allowed.
KEY_MODE = "api-key-free-tier"


def key_mode(env: dict[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    return env.get("FACTORY_GEMINI_AUTH", "").strip().lower() == KEY_MODE


def forbidden_variables(env: dict[str, str] | None = None) -> list[str]:
    env = os.environ if env is None else env
    allowed = {"GEMINI_API_KEY"} if key_mode(env) else set()
    return [k for k in KEY_VARIABLES if k not in allowed and env.get(k, "").strip()]
_stop = threading.Event()


def _run(*cmd: str) -> str:
    try:
        result = subprocess.run(list(cmd), cwd=REPO, text=True, capture_output=True, check=False, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return (result.stdout or result.stderr).strip() if result.returncode == 0 else ""


def current_branch() -> str:
    return _run("git", "branch", "--show-current")


def gemini_version() -> str:
    version = _run("gemini", "--version")
    if not version:
        raise RuntimeError("Gemini CLI is not installed or not on PATH (npm install -g @google/gemini-cli)")
    return version.splitlines()[0][:120]


def heartbeat(version: str, *, status: str = "idle", task_id: str = "", last_result: str = "",
              post=None) -> bool:
    """Secret-free lane heartbeat (/api/operator-worker/heartbeat, operator gemini). Best effort."""
    if not WORKER_TOKEN:
        return False
    payload = {
        "operator_id": "gemini",
        "node_id": os.environ.get("FACTORY_GEMINI_NODE_ID", "gemini-" + socket.gethostname())[:80],
        "hostname": socket.gethostname()[:120],
        "runtime": "gemini-cli",
        "version": version[:120],
        "auth_mode": KEY_MODE if key_mode() else "google_account",
        "branch": current_branch()[:120],
        "repo": REPO.name[:120],
        "status": status,
        "task_id": task_id,
        "last_result": last_result[:300],
    }
    try:
        response = (post or requests.post)(f"{FACTORY_URL}/api/operator-worker/heartbeat",
                                           headers={"Authorization": f"Bearer {WORKER_TOKEN}"}, json=payload, timeout=15)
        return 200 <= int(getattr(response, "status_code", 0)) < 300
    except Exception:
        return False


def _heartbeat_loop(version: str) -> None:
    while not _stop.wait(HEARTBEAT_SECONDS):
        heartbeat(version, status="running")


def child_env(base: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    for key in KEY_VARIABLES:
        if not (key == "GEMINI_API_KEY" and key_mode(env)):
            env.pop(key, None)
    env.update({"AUTOPILOT_REPO": str(REPO), "FACTORYOS_URL": FACTORY_URL,
                "AUTOPILOT_OPERATOR": "gemini", "AUTOPILOT_AGENT": "gemini"})
    # The Gemini runner never holds the Claude credentials: it cannot claim Claude work or ack owner controls.
    for key in ("FACTORY_CLAUDE_WORKER_TOKEN", "TG_TOKEN"):
        env.pop(key, None)
    return env


def main() -> int:
    for key in forbidden_variables():
        raise SystemExit(f"Refusing to start: {key} is set. The Gemini worker runs on the Google-account login, or on "
                         "GEMINI_API_KEY only with FACTORY_GEMINI_AUTH=api-key-free-tier (a project without billing).")
    if key_mode() and not os.environ.get("GEMINI_API_KEY", "").strip():
        raise SystemExit("FACTORY_GEMINI_AUTH=api-key-free-tier needs GEMINI_API_KEY in the worker env file.")
    if not WORKER_TOKEN:
        raise SystemExit("FACTORY_GEMINI_WORKER_TOKEN is required (owner sets the same value in Render).")
    version = gemini_version()
    branch = current_branch()
    if not branch or branch in {"main", "master"} or branch == "autopilot/aws-worker":
        raise SystemExit("Check out a dedicated Gemini branch (e.g. autopilot/gemini-worker) in a separate checkout; "
                         "never main or the Claude worker branch.")
    heartbeat(version, status="online")
    thread = threading.Thread(target=_heartbeat_loop, args=(version,), daemon=True, name="factoryos-gemini-heartbeat")
    thread.start()
    try:
        result = subprocess.run([sys.executable, "-m", "autopilot.autopilot"], cwd=REPO, env=child_env(), check=False)
        if result.returncode == CODE_UPDATED:
            _stop.set()
            thread.join(timeout=2)
            os.execv(sys.executable, [sys.executable, "-m", "autopilot.gemini_worker"])
        heartbeat(version, status="idle" if result.returncode == 0 else "failed")
        return int(result.returncode)
    finally:
        _stop.set()
        thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
