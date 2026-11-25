"""T-740 EC2 ops agent: pulls fixed operations from FactoryOS and runs them, nothing else.

Runs as root from ``factoryos-ops-agent.timer`` (every 30 s), like the T-562 runner supervisor. Each run claims up to
``MAX_PER_RUN`` requests from ``/api/ops/worker/claim`` with the worker credential already in
``/etc/factoryos/claude-worker.env``, validates every request again against ``ops_catalog`` (an unknown op is
reported as refused and never run), runs the catalog's argv lists without a shell under one 60 s deadline, redacts
the output (every value from the env file literally, then credential-shaped text), caps it at 32 KB and posts it to
``/api/ops/worker/result/{id}``.

Never: a shell, an argument that is not from the catalog, sudo beyond these ops, a push, a force, printing a secret.
Standard library only (the host's root Python 3.9 may not have ``requests``).
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

try:
    from . import supervisor
except ImportError:  # pragma: no cover - run as a plain script
    import supervisor  # type: ignore

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ops_catalog as cat  # noqa: E402

ENV_FILE = Path("/etc/factoryos/claude-worker.env")
MAX_PER_RUN = 3
HTTP_TIMEOUT = 20
SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def log(message: str) -> None:
    print(json.dumps({"component": "ops_agent", "msg": message}, ensure_ascii=False), flush=True)


def child_env(as_worker: bool) -> Dict[str, str]:
    """A minimal environment: no worker tokens, no inherited secrets."""
    env = {"PATH": SAFE_PATH, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "SYSTEMD_PAGER": "", "PAGER": "cat",
           "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "/bin/false", "SYSTEMD_COLORS": "0"}
    env["HOME"] = "/home/" + cat.WORKER_USER if as_worker else "/root"
    return env


def run_argv(argv: List[str], *, as_worker: bool, timeout: float) -> Tuple[int, str]:
    """One catalog step. ``shell`` is never used; a worker-user step goes through runuser."""
    full = (["runuser", "-u", cat.WORKER_USER, "--"] + argv) if as_worker else list(argv)
    try:
        p = subprocess.run(full, shell=False, text=True, capture_output=True, timeout=max(1.0, timeout),
                           check=False, env=child_env(as_worker), stdin=subprocess.DEVNULL)
        return p.returncode, (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or b""
        out = out.decode("utf-8", "replace") if isinstance(out, bytes) else str(out)
        return 124, out + "\n[timeout]"
    except OSError as exc:
        return 127, f"[cannot run {argv[0]}: {type(exc).__name__}]"


def execute(task: dict, *, repo: str, known: List[str], runner: Callable = run_argv,
            clock: Callable[[], float] = time.monotonic, deadline_seconds: float = cat.OP_TIMEOUT_SECONDS) -> dict:
    """Run one claimed request → the result body. Never raises."""
    started = clock()
    try:
        steps = cat.plan({k: task.get(k) for k in ("op", "unit", "minutes", "lines")}, repo)
    except ValueError as exc:
        return {"status": "failed", "exit_code": None, "error": "refused: " + str(exc)[:200], "output": "",
                "duration_ms": 0}
    chunks: List[str] = []
    final_rc = 0
    error = ""
    for label, argv, as_worker in steps:
        left = deadline_seconds - (clock() - started)
        if left <= 0:
            error = f"timeout: op deadline {deadline_seconds:.0f} s reached before step {label}"
            final_rc = 124
            break
        rc, out = runner(argv, as_worker=as_worker, timeout=left)
        chunks.append(f"$ {label} (exit {rc})\n{out.rstrip()}")
        if rc == 124:
            error, final_rc = f"timeout in step {label}", 124
            break
        # Read ops report every step; a mutating step that fails stops the op.
        if rc and task.get("op") in ("restart", "sync_checkout", "install_surfer_unit") and label not in (
                "reset-failed", "upstream"):
            error, final_rc = f"step {label} failed (exit {rc})", rc
            break
        if task.get("op") == "sync_checkout" and label == "upstream" and rc:
            error, final_rc = "the checkout has no upstream branch; nothing was changed", rc
            break
    output = cat.cap(cat.redact("\n\n".join(chunks), known))
    return {"status": "failed" if error else "done", "exit_code": final_rc, "error": cat.redact(error, known),
            "output": output, "duration_ms": int((clock() - started) * 1000)}


def http_post(url: str, token: str, body: dict) -> Tuple[int, dict]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=data, method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json",
                                          "User-Agent": "factoryos-ops-agent"})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as exc:
        return exc.code, {}
    except (urllib.error.URLError, OSError, ValueError):
        return 0, {}


def run_once(*, env: Optional[Dict[str, str]] = None, post: Callable = http_post, runner: Callable = run_argv) -> dict:
    env = supervisor.parse_env(ENV_FILE) if env is None else env
    base = str(env.get("FACTORYOS_URL") or "").rstrip("/")
    token = str(env.get("FACTORY_CLAUDE_WORKER_TOKEN") or "")
    if not base.startswith("https://") and not base.startswith("http://127.0.0.1"):
        return {"status": "not_configured", "reason": "FACTORYOS_URL missing or not https"}
    if not token:
        return {"status": "not_configured", "reason": "worker token missing"}
    repo = str(env.get("AUTOPILOT_REPO") or cat.DEFAULT_REPO)
    if not repo.startswith("/") or ".." in repo:
        repo = cat.DEFAULT_REPO
    known = [v for v in env.values() if v and len(v) >= cat.MIN_KNOWN_SECRET]
    node = "ops-" + socket.gethostname()[:60]
    done = []
    for _ in range(MAX_PER_RUN):
        code, data = post(base + "/api/ops/worker/claim", token, {"node": node})
        if code != 200:
            return {"status": "claim_failed", "http": code, "ran": done}
        task = data.get("task") if isinstance(data, dict) else None
        if not isinstance(task, dict) or not str(task.get("id") or "").startswith("ops_"):
            break
        body = execute(task, repo=repo, known=known, runner=runner)
        code, _ = post(base + "/api/ops/worker/result/" + str(task["id"]), token, body)
        done.append({"id": task["id"], "op": task.get("op"), "status": body["status"], "posted": code})
        log(f"{task['id']} {task.get('op')} {task.get('unit') or ''} -> {body['status']} (post {code})")
    return {"status": "ok", "ran": done}


if __name__ == "__main__":
    try:
        result = run_once()
        if result.get("ran") or result.get("status") != "ok":
            print(json.dumps(result, ensure_ascii=False), flush=True)
    except Exception as exc:  # no exception payload in the journal (it could carry a URL with a token)
        print(json.dumps({"component": "ops_agent", "status": "failed", "exception_type": type(exc).__name__}))
        sys.exit(1)
