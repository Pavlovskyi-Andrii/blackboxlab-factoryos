"""T-714: local loop heartbeats of the EC2 workers, read by the root supervisor's watchdog.

Each long-running worker loop writes a tiny JSON file in the checkout's ignored ``.autopilot/`` directory on every
pass: when it beat (``at``) and by when the next beat is due at the latest (``deadline``). A loop that is about to start
a long job (a Claude CLI run, a browser task) beats with a longer budget first. The heartbeat is written by the loop
itself, never by a side thread, so a hung loop stops beating even while its process (and its server heartbeat thread)
is still alive: that is the 2026-11-21 failure, "Idle · last activity 1 h ago" with nothing running.

No secrets, tokens or command output go into the file: timestamps, a state word, a task id and a pid.
"""
from __future__ import annotations

import json
import os
import pathlib
import time
from typing import Optional

CLAUDE_LOOP_FILE = "claude-loop.json"      # autopilot.autopilot main loop (the Claude worker)
SURFER_FILE = "surfer.json"                # autopilot.browser_worker (the dedicated Surfer worker)
STALE_AFTER_SECONDS = 15 * 60              # N = 15 min: no beat for this long past a pass means "hung"


def path_for(repo: pathlib.Path, name: str) -> pathlib.Path:
    return pathlib.Path(repo) / ".autopilot" / name


def beat(path: pathlib.Path, *, budget_seconds: float = STALE_AFTER_SECONDS, state: str = "idle", task: str = "",
         now: Optional[float] = None, **extra) -> bool:
    """Record a beat; the next one is due within ``budget_seconds``. Best effort: never raises."""
    now = time.time() if now is None else float(now)
    record = {"at": round(now, 1), "deadline": round(now + max(0.0, float(budget_seconds)), 1),
              "state": str(state)[:40], "task": str(task)[:80], "pid": os.getpid()}
    record.update({k: v for k, v in extra.items() if isinstance(v, (int, float, str, bool))})
    try:
        path = pathlib.Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.chmod(0o644)                       # the root supervisor reads it; nothing secret inside
        os.replace(tmp, path)
        return True
    except OSError:
        return False


def read(path: pathlib.Path) -> dict:
    try:
        raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(raw, dict):
        return {}
    try:
        raw["at"], raw["deadline"] = float(raw.get("at") or 0), float(raw.get("deadline") or 0)
    except (TypeError, ValueError):
        return {}
    return raw


def alive(path: pathlib.Path, now: Optional[float] = None) -> bool:
    """True while the last beat's deadline has not passed (the loop is alive and keeping its promise).
    A loop that stopped on purpose writes state "stopped" and is not alive from that moment."""
    record = read(path)
    now = time.time() if now is None else float(now)
    return (bool(record) and record.get("state") != "stopped" and record["at"] <= now + 60
            and now < record["deadline"])
