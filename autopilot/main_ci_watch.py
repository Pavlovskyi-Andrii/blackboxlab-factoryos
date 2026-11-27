"""FO-09 (owner brief 19.11, monitoring): tell the owner when CI on main goes red, and once when it is green again.

Runs on the EC2 worker between tasks (it has the owner's `gh` login; Render's token cannot read Actions). At most one
GitHub call per CHECK_SECONDS. For each workflow that runs on pushes to main, only its latest completed run counts:
red → one Telegram message per failing commit; the first green run after a red one → one "green again" message.
Nothing is retried, re-run or changed on GitHub. A GitHub read that fails is silent (no guess), and is retried later.
"""
from __future__ import annotations

import json
import pathlib
import time
from typing import Callable

REPO_SLUG = "Pavlovskyi-Andrii/blackboxlab-factoryos"
CHECK_SECONDS = 600
RED = ("failure", "timed_out", "startup_failure")
GREEN = ("success",)


def _load(path: pathlib.Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    return value if isinstance(value, dict) else {}


def _save(path: pathlib.Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def latest_completed(runs: list) -> dict:
    """{workflow name: its newest completed push run on main}. gh lists newest first."""
    out: dict = {}
    for run in runs:
        if not isinstance(run, dict) or run.get("status") != "completed" or run.get("event") != "push":
            continue
        name = str(run.get("workflowName") or "")
        if name and name not in out:
            out[name] = run
    return out


def run_once(state_path: pathlib.Path, *, gh_fn: Callable, send: Callable[[str], object],
             now: float | None = None) -> str:
    """Returns idle | checked | unavailable."""
    now = time.time() if now is None else now
    state = _load(state_path)
    if now - float(state.get("checked_at") or 0) < CHECK_SECONDS:
        return "idle"
    state["checked_at"] = now
    code, out = gh_fn("run", "list", "-R", REPO_SLUG, "--branch", "main", "--limit", "30",
                      "--json", "databaseId,workflowName,status,conclusion,event,headSha,displayTitle,url")
    try:
        runs = json.loads(out) if code == 0 else None
    except ValueError:
        runs = None
    if not isinstance(runs, list):
        _save(state_path, state)
        return "unavailable"
    red = state.setdefault("red", {})            # workflow → sha already reported as red
    for name, run in latest_completed(runs).items():
        sha, conclusion = str(run.get("headSha") or "")[:12], run.get("conclusion")
        if conclusion in RED and red.get(name) != sha:
            if send(f"🔴 CI на main упал: {name}\n{str(run.get('displayTitle') or '')[:120]}\n"
                    f"коммит {sha} · {run.get('url') or ''}\nАвтоматически ничего не перезапускается."):
                red[name] = sha
        elif conclusion in GREEN and name in red:
            if send(f"🟢 CI на main снова зелёный: {name} · коммит {sha}"):
                red.pop(name, None)
    _save(state_path, state)
    return "checked"
