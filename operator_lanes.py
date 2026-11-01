"""T-585: multi-operator delegation lanes (Claude, Gemini, ChatGPT) for the delegation board.

One pure function, ``build_operator_lanes``, merges what FactoryOS has actually observed per operator:
the generic operator-worker heartbeat, the richer legacy Claude heartbeat + verified task results,
and Relay-verified runs from the T-599-F lane board. A lane that never reported anything is
``unconfigured`` (explicitly, never "idle"); a reported heartbeat past its TTL is ``stale`` and then
``offline``. Values nobody reported stay ``None``. Only whitelisted fields leave this module, so a
runner cannot smuggle extra keys (tokens, env) into the board; the caller still redacts secret values.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Iterable, Optional

OPERATORS = ("claude", "gemini", "chatgpt")
LABELS = {"claude": "Claude", "gemini": "Gemini", "chatgpt": "ChatGPT"}
# Claude and Gemini report through a runner heartbeat; ChatGPT is the Planner and only appears through Relay runs.
RUNNER_OPERATORS = ("claude", "gemini")
AVAILABILITY = ("online", "stale", "offline", "unconfigured")
ACTIVE_STATUSES = ("running", "working", "in_progress", "claimed", "checkpoint")
FINISHED = ("done", "blocked", "failed")
MAX_TICKETS = 20


def _ts(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _s(value, limit=200) -> str:
    return str(value or "")[:limit]


def _depth(value) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    return max(0, int(value))


def _beat(source: str, last_seen, ttl: int, now: float) -> dict:
    seen = _ts(last_seen)
    age = round(max(0.0, now - seen), 1) if seen else None
    return {"source": source, "last_seen": seen, "age_seconds": age, "fresh": age is not None and age <= ttl}


def build_operator_lanes(*, runners: Optional[dict] = None, runner_ttl: int = 45, claude_worker: Optional[dict] = None,
                         claude_results: Iterable[dict] = (), lane_board: Optional[dict] = None,
                         provider_status: Optional[dict] = None, task_titles: Optional[dict] = None,
                         assigned_roles: Optional[dict] = None, now: Optional[float] = None,
                         offline_after: int = 3600) -> list:
    """Return one lane dict per operator in ``OPERATORS`` order.

    ``runners``: operator -> raw operator-worker heartbeat (``last_seen`` epoch, branch, runtime, status,
    task_id, stage, queue_depth, tickets, last_result). ``claude_worker``: the delegation board ``worker``
    block (legacy Claude heartbeat, already TTL-evaluated). ``claude_results``: verified Claude task results.
    ``lane_board``: ``build_lane_board`` output. ``provider_status``: operator -> T-580 status string.
    """
    now = time.time() if now is None else float(now)
    runners = runners or {}
    claude_worker = claude_worker or {}
    lane_board = lane_board or {}
    relay_lanes = lane_board.get("lanes") or {}
    relay_tasks = [t for t in lane_board.get("tasks") or [] if isinstance(t, dict)]
    provider_status = provider_status or {}
    task_titles = task_titles or {}
    assigned_roles = assigned_roles or {}
    results = [r for r in claude_results or [] if isinstance(r, dict)]

    lanes = []
    for op in OPERATORS:
        runner = runners.get(op) if op in RUNNER_OPERATORS and isinstance(runners.get(op), dict) else {}
        relay = relay_lanes.get(op) if isinstance(relay_lanes.get(op), dict) else {}
        beats = []
        if runner and _ts(runner.get("last_seen")):
            beats.append(_beat("operator_heartbeat", runner.get("last_seen"), runner_ttl, now))
        legacy = op == "claude" and claude_worker.get("heartbeat_age_seconds") is not None
        if legacy:
            age = float(claude_worker.get("heartbeat_age_seconds") or 0)
            beats.append({"source": "claude_heartbeat", "last_seen": _ts(claude_worker.get("last_seen")),
                          "age_seconds": round(age, 1), "fresh": claude_worker.get("online") is True})
        beat = next((b for b in beats if b["fresh"]), None) or min(beats, key=lambda b: b["age_seconds"], default=None)
        relay_state = _s(relay.get("state")) or "offline"
        relay_seen = bool(relay.get("last_task_id") or relay.get("run_id"))

        if beat and beat["fresh"]:
            availability, reason = "online", ""
        elif relay_state == "working":
            availability, reason = "online", ""  # a claimed run is still reporting fresh Relay events
        elif beat:
            availability = "stale" if beat["age_seconds"] <= offline_after else "offline"
            reason = "heartbeat_expired"
        elif relay_seen:
            availability, reason = "offline", "no_heartbeat"
        else:
            availability = "unconfigured"
            reason = "never_reported" if op in RUNNER_OPERATORS else "no_runner"
        live_runner = bool(beat and beat["fresh"] and beat["source"] == "operator_heartbeat")
        live_legacy = bool(beat and beat["fresh"] and beat["source"] == "claude_heartbeat")
        telemetry = claude_worker.get("telemetry") or {} if op == "claude" else {}
        node = claude_worker.get("node") or {} if op == "claude" else {}

        # Open ticket: Relay-verified run first, then what a live heartbeat says it is executing.
        ticket = None
        if relay.get("task_id"):
            ticket = {"id": _s(relay["task_id"], 80), "stage": _s(relay.get("stage"), 40), "source": "relay"}
        elif live_runner and _s(runner.get("task_id")) and _s(runner.get("status")).lower() in ACTIVE_STATUSES:
            ticket = {"id": _s(runner["task_id"], 80), "stage": _s(runner.get("stage") or runner.get("status"), 40),
                      "source": "operator_heartbeat"}
        elif live_legacy and claude_worker.get("active_task_id"):
            ticket = {"id": _s(claude_worker["active_task_id"], 80), "stage": _s(telemetry.get("stage"), 40),
                      "source": "claude_heartbeat"}
        if ticket:
            relay_title = next((t.get("title") for t in relay_tasks if t.get("id") == ticket["id"]), "")
            ticket["title"] = _s(task_titles.get(ticket["id"]) or relay_title, 150)

        # Last result: the most recent factual outcome from verified worker results, Relay or the runner itself.
        candidates = []
        if op == "claude" and results:
            r = results[-1]
            candidates.append({"task_id": _s(r.get("task_id"), 80), "result": _s(r.get("result"), 20),
                               "summary": _s(r.get("summary"), 300), "commit": _s(r.get("commit"), 12),
                               "at": _ts(r.get("received_at")), "source": "worker_result"})
        event = relay.get("last_event") or {}
        if event.get("action") in FINISHED and relay.get("last_task_id"):
            candidates.append({"task_id": _s(relay["last_task_id"], 80), "result": _s(event["action"], 20),
                               "summary": _s(relay.get("reason"), 300), "commit": "", "at": _ts(event.get("at")),
                               "source": "relay"})
        if runner and _s(runner.get("last_result")):
            # A heartbeat repeats its last_result text on every beat, so it carries no outcome time and
            # only wins when no verified worker result or Relay outcome exists.
            candidates.append({"task_id": "", "result": "", "summary": _s(runner["last_result"], 300), "commit": "",
                               "at": None, "source": "operator_heartbeat"})
        last_result = max(candidates, key=lambda c: c["at"] or 0) if candidates else None

        if runner and _ts(runner.get("last_seen")):
            queue_depth, queue_source = _depth(runner.get("queue_depth")), "operator_heartbeat"
        elif op == "claude" and _depth(telemetry.get("queue_depth")) is not None:
            queue_depth, queue_source = _depth(telemetry.get("queue_depth")), "claude_heartbeat"
        else:
            queue_depth, queue_source = None, None

        tickets, seen = [], set()
        for t in relay_tasks:
            if t.get("lane") == op and not t.get("done") and t.get("column") in ("in_progress", "blocked", "review"):
                seen.add(t.get("id"))
                tickets.append({"id": _s(t.get("id"), 80), "title": _s(t.get("title"), 150),
                                "state": _s(t.get("stage") or t.get("column"), 40), "source": "relay"})
        for t in runner.get("tickets") or []:
            tid = _s(t.get("id") or t.get("task_id"), 80) if isinstance(t, dict) else ""
            if tid and tid not in seen:
                seen.add(tid)
                tickets.append({"id": tid, "title": _s(t.get("title"), 150), "state": _s(t.get("state") or t.get("status"), 40),
                                "source": "operator_heartbeat"})

        if op == "claude" and live_legacy:
            branch, runtime = _s(telemetry.get("branch") or node.get("branch"), 120), "claude-code"
        else:
            branch = _s(runner.get("branch") or (telemetry.get("branch") or node.get("branch") if op == "claude" else ""), 120)
            runtime = _s(runner.get("runtime") or ("claude-code" if op == "claude" and legacy else ""), 60)
        lanes.append({
            "operator_id": op, "label": LABELS[op],
            "kind": "runner" if op in RUNNER_OPERATORS else "planner",
            "availability": availability, "configured": availability != "unconfigured", "reason": reason,
            "heartbeat": ({"source": beat["source"], "last_seen": beat["last_seen"], "age_seconds": beat["age_seconds"]}
                          if beat else {"source": None, "last_seen": None, "age_seconds": None}),
            "open_ticket": ticket,
            "stage": ticket["stage"] if ticket else "",
            "branch": branch,
            "head_sha": _s(telemetry.get("head_sha"), 12) if op == "claude" else "",
            "runtime": runtime,
            "node_id": _s(runner.get("node_id") or (node.get("node_id") if op == "claude" else ""), 80),
            "last_result": last_result,
            "queue_depth": queue_depth, "queue_depth_source": queue_source,
            "roadmap_open": int(relay.get("remaining") or 0),
            "assigned_not_claimed": [_s(x, 80) for x in relay.get("assigned_not_claimed") or []][:MAX_TICKETS],
            "open_tickets": tickets[:MAX_TICKETS],
            "relay_state": relay_state,
            "provider_status": _s(provider_status.get(op), 40) or "unknown",
            "assigned_roles": [_s(x, 40) for x in assigned_roles.get(op) or []],
            "last_error": _s(runner.get("last_error") if live_runner else (claude_worker.get("last_error") if live_legacy else ""), 300),
        })
    return lanes
