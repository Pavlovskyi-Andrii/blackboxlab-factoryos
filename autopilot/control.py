"""T-536-F runner side of the FactoryOS safe operator controls.

The owner can only pause (after the current task), resume, or retry a blocked/failed
task. This module never touches git, deploys or publishing: it reads the pause level and
pending commands from FactoryOS and tells the autopilot loop which in-memory hold to
clear. Everything else (branch checks, push rules, HUMAN gates) stays in the loop.
"""
from __future__ import annotations

import os
from typing import Any, Callable

ACTIONS = ("pause", "resume", "retry")


def _endpoint() -> tuple[str, str]:
    token = os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", "").strip()
    url = os.environ.get("FACTORYOS_URL", "").strip().rstrip("/")
    return url, token


def configured() -> bool:
    url, token = _endpoint()
    return bool(url and token)


def fetch(*, get: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Pending control state, or None when not configured / unreachable / malformed."""
    url, token = _endpoint()
    if not url or not token:
        return None
    if get is None:
        import requests

        get = requests.get
    try:
        response = get(f"{url}/api/claude-worker/control", headers={"Authorization": f"Bearer {token}"}, timeout=15)
        if not 200 <= int(getattr(response, "status_code", 0)) < 300:
            return None
        value = response.json()
    except Exception:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("paused"), bool) or not isinstance(value.get("commands"), list):
        return None
    return value


def ack(command_id: str, outcome: str, detail: str = "", *, post: Callable[..., Any] | None = None) -> bool:
    url, token = _endpoint()
    if not url or not token:
        return False
    if post is None:
        import requests

        post = requests.post
    try:
        response = post(
            f"{url}/api/claude-worker/control/ack",
            headers={"Authorization": f"Bearer {token}"},
            json={"command_id": command_id, "outcome": outcome, "detail": detail[:300]},
            timeout=15,
        )
        return 200 <= int(getattr(response, "status_code", 0)) < 300
    except Exception:
        return False


def decide(
    control: dict[str, Any] | None, *, paused: bool, held_task: str | set[str] | frozenset[str], decided: dict[str, tuple[str, str]] | None = None
) -> dict[str, Any]:
    """Pure decision step for one loop iteration.

    `paused` is the last known level (kept when FactoryOS is unreachable). `held_task` is the
    task (or set of tasks) this runner is holding because it blocked or exhausted its failure budget. Returns
    the new pause level, the task whose hold is released (if any) and the acks to send.
    Unknown actions and retries for a task the runner does not hold are rejected. Commands in
    `decided` were already acted on (their ack was lost) and are re-acknowledged with the
    same outcome instead of being applied twice.
    """
    if control is None:
        return {"paused": paused, "retry": "", "acks": []}
    retry = ""
    held = {held_task} if isinstance(held_task, str) else set(held_task)
    held.discard("")
    acks: list[tuple[str, str, str]] = []
    for command in control.get("commands") or []:
        if not isinstance(command, dict) or not isinstance(command.get("id"), str):
            continue
        action, task = command.get("action"), str(command.get("task_id") or "")
        if decided and command["id"] in decided:
            acks.append((command["id"], *decided[command["id"]]))
        elif action in ("pause", "resume"):
            acks.append((command["id"], "applied", "paused before the next task" if action == "pause" else "resumed"))
        elif action == "retry" and task in held:
            retry = task
            acks.append((command["id"], "applied", f"released hold on {task}"))
        elif action == "retry":
            acks.append((command["id"], "rejected", f"runner is not holding {task or 'that task'} as blocked/failed"))
        else:
            acks.append((command["id"], "rejected", "unsupported action"))
    return {"paused": bool(control["paused"]), "retry": retry, "acks": acks}
