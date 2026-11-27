"""MCP `ops_health` (owner 2026-11-27: «чтобы у тебя был доступ» to the EC2 worker and Telegram).

One read-only snapshot for the Claude lane: is the EC2 Claude worker alive, is the owner's Telegram chat paired, did
the latest MyCast and morning-brief deliveries go out, is the Ops relay switched on and polled, is the Media Finisher
connected. Until now this was visible only in the owner's browser session. No chat ids, usernames, tokens or message
text leave the server; the worker's last error is cut short and known secrets are masked out of it.
"""
from __future__ import annotations

import time
from typing import Callable, Iterable, Optional

LANES = frozenset({"claude"})
TOOL = {
    "name": "ops_health",
    "description": ("Read-only FactoryOS health for the Claude lane: EC2 Claude worker heartbeat and current task, owner "
                    "Telegram pairing, the latest MyCast / morning-brief deliveries (status, length), Ops relay gate "
                    "and EC2 ops-agent polling, Media Finisher connection. No secrets, chat ids or message text."),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
}
TOOL_NAMES = frozenset({TOOL["name"]})


def _age(ts, now: float) -> Optional[int]:
    try:
        ts = float(ts or 0)
    except (TypeError, ValueError):
        return None
    return int(now - ts) if ts > 0 else None


def _masked(text, secrets: Iterable[str], limit: int = 200) -> str:
    text = str(text or "")
    for secret in secrets:
        if secret and len(secret) >= 6:
            text = text.replace(secret, "[redacted]")
    return text[:limit]


def snapshot(lane: str, *, worker: dict, telegram: dict, deliveries: list, ops: dict, finisher: dict,
             known_secrets: Callable[[], Iterable[str]] = lambda: (), now: Optional[float] = None) -> dict:
    if lane not in LANES:
        raise PermissionError("ops_health is for the Claude lane token only (FACTORY_MCP_LANE_TOKEN_CLAUDE)")
    now = time.time() if now is None else now
    secrets = [s for s in known_secrets() if s]
    rows = [r for r in deliveries if isinstance(r, dict)]
    latest = sorted(rows, key=lambda r: r.get("at") or 0, reverse=True)
    executor = ops.get("executor") or {}
    return {
        "checked_at": int(now),
        "claude_worker": {
            "online": bool(worker.get("online")),
            "last_seen_seconds_ago": _age(worker.get("last_seen"), now),
            "active_task_id": str(worker.get("active_task_id") or "")[:40],
            "task_state": str(worker.get("task_state") or "")[:40],
            "last_error": _masked(worker.get("last_error"), secrets),
        },
        "telegram": {"bot_configured": bool(telegram.get("configured")), "owner_paired": bool(telegram.get("paired")),
                     "paired_at": telegram.get("paired_at")},
        "deliveries": [{"kind": r.get("kind"), "id": str(r.get("id") or "")[:80], "status": str(r.get("status") or "")[:60],
                        "seconds": int(r.get("seconds") or 0), "seconds_ago": _age(r.get("at"), now)}
                       for r in latest[:8]],
        "ops_relay": {"enabled": bool(ops.get("enabled")), "classes": list(ops.get("classes") or []),
                      "agent_online": bool(executor.get("online")), "agent_last_poll_at": executor.get("last_poll_at")},
        "media_finisher": {"endpoint_configured": bool(finisher.get("endpoint")),
                           "token_configured": bool(finisher.get("token"))},
    }
