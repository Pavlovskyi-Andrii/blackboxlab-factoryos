"""T-596: Worker Center / Agent Office factual observability for the Claude worker.

One pure function, ``build_worker_overview``, separates the facts the owner asked to see apart:
EC2 host reachability vs EC2 cloud API visibility, systemd service state, subscription OAuth,
heartbeat freshness, Relay claim and the real current task. Every signal names its source and
when it was last checked; a source that did not report stays ``unknown``, never ``ok``.

The current task and stage come from the T-599-F lane board row, so the web Worker Center and
Telegram ``/status`` (``worker_overview_text``) always show the same task/stage. The activity
heatmap counts only verified worker evidence (worker results with a commit, Relay
``committed``/``done`` events of the Claude lane), not all repository commits. Days before the first
recorded worker event are ``unknown`` instead of zero.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

try:
    from zoneinfo import ZoneInfo
    KYIV = ZoneInfo("Europe/Kyiv")
    TZ_NAME = "Europe/Kyiv"
except Exception:  # tzdata missing: label the fallback honestly instead of pretending Kyiv
    KYIV = timezone.utc
    TZ_NAME = "UTC"

SIGNALS = ("host", "ec2_api", "systemd", "oauth", "heartbeat", "relay_claim", "current_task")
SIGNAL_STATES = ("ok", "warn", "fail", "idle", "unknown")
SUPERVISOR_FIELDS = ("checked_at", "status", "reason", "service_state", "subscription_authenticated",
                     "restart_attempts_last_hour", "recovery_action")
SUPERVISOR_STALE_SECONDS = 600  # the supervisor timer runs every minute
HEATMAP_DAYS = 28
ACTIVE = ("claimed", "running", "checkpoint", "committed", "pushed")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def _ts(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _iso(epoch: Optional[float]) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds") if epoch else ""


def _signal(sid: str, state: str, value: str, source: str, checked: Optional[float], **extra) -> dict:
    return {"id": sid, "state": state if state in SIGNAL_STATES else "unknown", "value": str(value)[:200],
            "source": source, "checked_at": _iso(checked), **extra}


def sanitize_supervisor(raw) -> dict:
    """Whitelist of the secret-free supervisor report fields; anything else is dropped."""
    if not isinstance(raw, dict):
        return {}
    out = {}
    for key in SUPERVISOR_FIELDS:
        value = raw.get(key)
        if key == "subscription_authenticated":
            if isinstance(value, bool):
                out[key] = value
        elif key == "restart_attempts_last_hour":
            if isinstance(value, int) and not isinstance(value, bool):
                out[key] = max(0, min(value, 1000))
        elif value is not None:
            out[key] = re.sub(r"[^A-Za-z0-9_:+.\- ]", "", str(value))[:64]
    return out


TELEMETRY_SOURCES = {"cpu_source": ("proc_stat", "loadavg", "unsupported"),
                     "memory_source": ("proc_meminfo", "unsupported")}
TELEMETRY_LIMITS = {"elapsed_seconds": 7 * 86400, "worker_uptime_seconds": 365 * 86400, "queue_depth": 10000,
                    "cpu_percent": 100, "memory_mb": 1 << 22, "memory_total_mb": 1 << 22}


def _bounded(value, limit):
    """Finite, non-negative number within limit; anything else (bool, str, NaN, negative, too large) is None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return None
    if value < 0 or value > limit:
        return None
    return round(float(value), 1) if isinstance(value, float) else value


def sanitize_telemetry(raw, now: Optional[float] = None) -> dict:
    """T-536-B: whitelist + type check of runner telemetry. Invalid values degrade to None, never to a guess."""
    if not isinstance(raw, dict) or not raw:
        return {"available": False, "state": "unknown"}
    now = time.time() if now is None else now
    out = {"available": True}
    stage = re.sub(r"[^a-z_]", "", str(raw.get("stage") or "").lower())[:32]
    out["stage"] = stage or None
    # Epoch seconds (the timeline contract); a start in the future (+60 s skew) is not plausible.
    started = _bounded(raw.get("task_started_at"), now + 60)
    out["task_started_at"] = float(started) if started else None
    for key, limit in TELEMETRY_LIMITS.items():
        out[key] = _bounded(raw.get(key), limit)
    if out["queue_depth"] is not None and not isinstance(out["queue_depth"], int):
        out["queue_depth"] = None
    if out["task_started_at"] is None:
        out["elapsed_seconds"] = None
    branch = str(raw.get("branch") or "")
    out["branch"] = branch[:120] if branch and re.match(r"^[A-Za-z0-9_./-]+$", branch) else None
    head = str(raw.get("head_sha") or "").lower()
    out["head_sha"] = head if SHA_RE.match(head) else None
    for key, allowed in TELEMETRY_SOURCES.items():
        source = raw.get(key)
        out[key] = source if source in allowed else "unsupported"
    if out["cpu_source"] == "unsupported" or out["cpu_percent"] is None:
        out["cpu_percent"], out["cpu_source"] = None, "unsupported"
    if out["memory_source"] == "unsupported" or out["memory_mb"] is None:
        out["memory_mb"], out["memory_total_mb"], out["memory_source"] = None, None, "unsupported"
    has_valid_data = any(out.get(k) is not None for k in ("cpu_percent", "memory_mb", "stage", "head_sha", "branch", "queue_depth", "worker_uptime_seconds"))
    out["state"] = "ok" if has_valid_data else "unknown"
    if not has_valid_data:
        out["available"] = False
    return out


def _github(repo: str, kind: str, ref: str) -> str:
    if not repo or not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
        return ""
    if kind == "commit" and SHA_RE.match(ref or ""):
        return f"https://github.com/{repo}/commit/{ref}"
    if kind == "tree" and ref and re.match(r"^[A-Za-z0-9_./-]+$", ref):
        return f"https://github.com/{repo}/tree/{ref}"
    if kind == "roadmap" and str(ref).isdigit():
        return f"https://github.com/{repo}/blob/main/ROADMAP.md#L{ref}"
    return ""


def _claude_tickets(tickets: Iterable[dict]) -> list:
    return [t for t in tickets or [] if isinstance(t, dict)
            and str((t.get("execution") or {}).get("owner") or "").lower() == "claude"]


def _task_of(ticket: dict) -> str:
    source = ticket.get("source") or {}
    return str(source.get("task_id") or "") if source.get("channel") == "roadmap" else str(ticket.get("id") or "")


def _signals(status: dict, lane: dict, now: float, ttl: int) -> list:
    node = status.get("node") or {}
    sup = sanitize_supervisor(node.get("supervisor"))
    beat = _ts(status.get("last_seen"))
    age = (now - beat) if beat else None
    online = bool(status.get("online"))
    out = []
    # Host: the only evidence the EC2 instance runs is that its worker process reports in.
    if online:
        out.append(_signal("host", "ok", str(node.get("hostname") or node.get("node_id") or ""), "heartbeat", beat))
    elif beat:
        out.append(_signal("host", "warn", "no_recent_heartbeat", "heartbeat", beat))
    else:
        out.append(_signal("host", "unknown", "never_reported", "heartbeat", None))
    # The instance role lacks ec2:DescribeInstances; that is missing visibility, not an offline EC2.
    out.append(_signal("ec2_api", "unknown", "describe_instances_not_granted", "aws-iam", None,
                       human="optional", action="ec2_describe_iam"))
    sup_at = _ts(sup.get("checked_at"))
    sup_fresh = bool(sup_at) and now - sup_at <= SUPERVISOR_STALE_SECONDS
    service = str(sup.get("service_state") or "")
    if not sup:
        out.append(_signal("systemd", "unknown", "supervisor_not_reported", "supervisor", None))
    elif not sup_fresh:
        out.append(_signal("systemd", "unknown", "supervisor_report_stale", "supervisor", sup_at, last_value=service))
    else:
        state = {"active": "ok", "activating": "warn", "deactivating": "warn", "inactive": "fail", "failed": "fail"}.get(service, "unknown")
        out.append(_signal("systemd", state, service or "unknown", "supervisor", sup_at,
                           reason=str(sup.get("reason") or ""),
                           restarts_last_hour=sup.get("restart_attempts_last_hour")))
    if sup_fresh and "subscription_authenticated" in sup:
        ok = sup["subscription_authenticated"] is True
        out.append(_signal("oauth", "ok" if ok else "fail", "subscription_logged_in" if ok else "subscription_logged_out",
                           "supervisor", sup_at, human="" if ok else "required", action="" if ok else "claude_login"))
    elif beat:
        # The heartbeat's auth_mode is the runner's own claim; it does not prove `claude auth status`.
        out.append(_signal("oauth", "unknown", "self_reported:" + str(node.get("auth_mode") or "none")[:40], "heartbeat", beat))
    else:
        out.append(_signal("oauth", "unknown", "not_reported", "supervisor", None))
    if online:
        out.append(_signal("heartbeat", "ok", "online", "heartbeat", beat, age_seconds=round(age, 1), ttl_seconds=ttl))
    elif beat:
        out.append(_signal("heartbeat", "warn", "stale", "heartbeat", beat, age_seconds=round(age, 1), ttl_seconds=ttl))
    else:
        out.append(_signal("heartbeat", "fail", "never_seen", "heartbeat", None, ttl_seconds=ttl))
    lane_state = str(lane.get("state") or "offline")
    seen = _ts((lane.get("last_event") or {}).get("at"))
    if lane_state == "working":
        out.append(_signal("relay_claim", "ok", lane.get("run_id") or "claimed", "relay", seen, task_id=lane.get("task_id") or ""))
    elif lane_state == "stale":
        out.append(_signal("relay_claim", "warn", "claim_without_fresh_event" if lane.get("task_id") else "lane_stale",
                           "relay", seen, task_id=lane.get("task_id") or ""))
    elif lane_state == "blocked":
        out.append(_signal("relay_claim", "fail", "last_run_blocked", "relay", seen, task_id=lane.get("task_id") or ""))
    else:
        out.append(_signal("relay_claim", "idle", "no_active_claim", "relay", seen))
    # Current task: only a claimed run with a fresh event counts. A heartbeat that names a task
    # without a claim is shown as a mismatch, never as work in progress.
    hb_task = str(status.get("active_task_id") or "")
    hb_state = str(status.get("task_state") or "")
    lane_task = str(lane.get("task_id") or "") if lane_state == "working" else ""
    if lane_task:
        mismatch = bool(hb_task) and hb_task != lane_task
        out.append(_signal("current_task", "warn" if mismatch else "ok", lane_task, "relay", seen,
                           stage=lane.get("stage") or "", heartbeat_task=hb_task, mismatch=mismatch))
    elif online and hb_task and hb_state in ("running", "working", "in_progress", "claimed", "checkpoint"):
        out.append(_signal("current_task", "warn", "heartbeat_only:" + hb_task, "heartbeat", beat,
                           stage="", heartbeat_task=hb_task, mismatch=True))
    else:
        out.append(_signal("current_task", "idle", "none", "relay", seen, stage="", heartbeat_task=hb_task, mismatch=False))
    return out


def _timeline(tickets: list, results: list, limit: int = 20) -> list:
    rows = []
    for ticket in tickets:
        task = _task_of(ticket)
        for event in ticket.get("history") or []:
            action = str(event.get("action") or "")
            at = _ts(event.get("at"))
            if not at or action not in ACTIVE + ("done", "blocked", "failed", "stale_released", "claim_rejected"):
                continue
            evidence = event.get("evidence") or {}
            rows.append({"at": _iso(at), "epoch": at, "task_id": task, "action": action, "source": "relay",
                         "run_id": str(event.get("run_id") or "")[:40],
                         "commit": str(evidence.get("commit") or "")[:12],
                         "note": str(event.get("note") or "")[:160]})
    for result in results:
        at = _ts(result.get("received_at"))
        if not at:
            continue
        rows.append({"at": _iso(at), "epoch": at, "task_id": str(result.get("task_id") or ""),
                     "action": "result:" + str(result.get("result") or "?"), "source": "worker_result",
                     "run_id": "", "commit": str(result.get("commit") or "")[:12],
                     "note": str(result.get("summary") or result.get("need") or "")[:160]})
    rows.sort(key=lambda r: r["epoch"], reverse=True)
    for row in rows:
        row.pop("epoch")
    return rows[:limit]


def _heatmap(tickets: list, results: list, now: float, days: int = HEATMAP_DAYS) -> dict:
    verified = {}  # Kyiv date -> set of task ids with verified evidence
    horizon = None
    for ticket in tickets:
        task = _task_of(ticket)
        for event in ticket.get("history") or []:
            at = _ts(event.get("at"))
            if not at:
                continue
            horizon = at if horizon is None else min(horizon, at)
            action = str(event.get("action") or "")
            if action == "done" or (action == "committed" and (event.get("evidence") or {}).get("commit")):
                day = datetime.fromtimestamp(at, KYIV).date().isoformat()
                verified.setdefault(day, set()).add(task)
    for result in results:
        at = _ts(result.get("received_at"))
        if not at:
            continue
        horizon = at if horizon is None else min(horizon, at)
        if str(result.get("result") or "") == "done" and SHA_RE.match(str(result.get("commit") or "")):
            day = datetime.fromtimestamp(at, KYIV).date().isoformat()
            verified.setdefault(day, set()).add(str(result.get("task_id") or ""))
    today = datetime.fromtimestamp(now, KYIV).date()
    first = datetime.fromtimestamp(horizon, KYIV).date() if horizon else None
    cells = []
    for offset in range(days - 1, -1, -1):
        day = today - timedelta(days=offset)
        key = day.isoformat()
        if first is None or day < first:
            cells.append({"date": key, "state": "unknown", "count": None, "tasks": []})
        else:
            tasks = sorted(verified.get(key, set()))
            cells.append({"date": key, "state": "active" if tasks else "zero", "count": len(tasks), "tasks": tasks[:10]})
    return {"timezone": TZ_NAME, "days": days, "cells": cells,
            "scope": "claude_worker_verified", "first_evidence_date": first.isoformat() if first else ""}


def _progress(roadmap_tasks: list, factory: Optional[dict], lane: dict) -> list:
    """Each percentage keeps its own population; they are never merged into one number."""
    out = []
    if factory and int(factory.get("total") or 0):
        total, done = int(factory["total"]), int(factory.get("done") or 0)
        out.append({"id": "factory_builder", "done": done, "total": total, "percent": round(done / total * 100, 1),
                    "source": "factory_build_manifest.json → /api/factory/tasks", "population": "product_build_tasks_all_versions"})
    if roadmap_tasks:
        total = len(roadmap_tasks)
        done = sum(1 for t in roadmap_tasks if t.get("done"))
        out.append({"id": "roadmap", "done": done, "total": total, "percent": round(done / total * 100, 1),
                    "source": "ROADMAP.md checkboxes", "population": "roadmap_tasks_all_versions"})
    if lane:
        done = int(lane.get("done") or 0)
        total = done + int(lane.get("remaining") or 0)
        if total:
            out.append({"id": "claude_lane", "done": done, "total": total, "percent": round(done / total * 100, 1),
                        "source": "lane board (Owner: claude + claimed runs)", "population": "claude_lane_tasks"})
    return out


def _human_blockers(roadmap_tasks: list, answers_text: str, repo: str) -> list:
    out = []
    for task in roadmap_tasks:
        if not task.get("human") or task.get("done"):
            continue
        answered = bool(re.search(r"^##\s+" + re.escape(task["id"]) + r"\b", answers_text or "", re.M))
        out.append({"id": task["id"], "title": str(task.get("title") or "")[:150],
                    "need": str(task.get("need") or task.get("done_criteria") or task.get("goal") or "")[:300],
                    "answered": answered,
                    "action": "answers_md" if not answered else "verify_answer",
                    "answer_path": ".autopilot/answers.md#" + task["id"],
                    "roadmap_url": _github(repo, "roadmap", str(task.get("roadmap_line") or ""))})
    return out


def build_worker_overview(status: dict, lane_board: dict, *, results: Iterable[dict] = (), tickets: Iterable[dict] = (),
                          roadmap_tasks: Iterable[dict] = (), factory_tasks: Optional[dict] = None,
                          answers_text: str = "", repo: str = "", now: Optional[float] = None) -> dict:
    """Return the Claude worker overview. ``status`` is ``get_claude_code_status()``; the lane row is
    ``lane_board["lanes"]["claude"]`` so web and Telegram cannot disagree on task/stage."""
    now = time.time() if now is None else float(now)
    status = status or {}
    lane = ((lane_board or {}).get("lanes") or {}).get("claude") or {}
    node = status.get("node") or {}
    mine = _claude_tickets(tickets)
    results = [r for r in results or [] if isinstance(r, dict)]
    roadmap_tasks = [t for t in roadmap_tasks or [] if isinstance(t, dict)]
    ttl = int(status.get("ttl_seconds") or 0)
    signals = _signals(status, lane, now, ttl)
    checked = [_ts(s["checked_at"]) for s in signals if s["checked_at"] and s["state"] != "unknown"]
    last = results[-1] if results else {}
    commit = str(last.get("commit") or "")
    head = str(node.get("head_sha") or "")
    branch = str(node.get("branch") or "")
    errors = []
    if status.get("last_error"):
        errors.append({"source": "heartbeat", "task_id": str(status.get("active_task_id") or ""),
                       "detail": str(status["last_error"])[:300], "at": _iso(_ts(status.get("last_seen")))})
    for result in results[-10:]:
        if str(result.get("result") or "") in ("blocked", "failed"):
            errors.append({"source": "worker_result", "task_id": str(result.get("task_id") or ""),
                           "detail": str(result.get("need") or result.get("summary") or "")[:300],
                           "at": _iso(_ts(result.get("received_at")))})
    if lane.get("reason"):
        errors.append({"source": "relay", "task_id": str(lane.get("task_id") or ""), "detail": str(lane["reason"])[:300],
                       "at": str((lane.get("last_event") or {}).get("at") or "")})
    pr_url = str(lane.get("pr_url") or "")
    working = lane.get("state") == "working"
    return {
        "worker": "claude",
        "lane_state": str(lane.get("state") or "offline"),
        # Same fields as the lane board row Telegram renders.
        "task_id": str(lane.get("task_id") or "") if working else "",
        "stage": str(lane.get("stage") or "") if working else "",
        "signals": signals,
        "last_verified_at": _iso(max(checked)) if checked else "",
        "evidence": {
            "branch": branch, "branch_url": _github(repo, "tree", branch),
            "last_commit": commit[:12], "last_commit_url": _github(repo, "commit", commit),
            "last_result_task": str(last.get("task_id") or ""), "last_result": str(last.get("result") or ""),
            "changed_files": [str(f)[:160] for f in (last.get("files") or [])][:20],
            "checks": [str(c)[:200] for c in (last.get("checks") or [])][:10],
            "pr_url": pr_url if pr_url.startswith("https://github.com/") else "",
            # No backend CI verifier exists for worker branches: say so instead of guessing.
            "ci": "unverified",
            "head": head[:12],
        },
        "timeline": _timeline(mine, results),
        "heatmap": _heatmap(mine, results, now),
        "errors": errors[-8:],
        "progress": _progress(roadmap_tasks, factory_tasks, lane),
        "human_blockers": _human_blockers(roadmap_tasks, answers_text, repo),
        "source": "heartbeat+supervisor+relay-events+worker-results",
    }


# Telegram copy. The web dashboard uses the same keys under ``wo.*`` in static/index.html.
TEXT = {
    "en": {"title": "Claude worker (sources)", "host": "host", "ec2_api": "EC2 API", "systemd": "systemd",
           "oauth": "OAuth", "heartbeat": "heartbeat", "relay_claim": "claim", "current_task": "task",
           "unknown": "unknown", "checked": "verified", "human": "HUMAN", "ec2_note": "no DescribeInstances permission (not offline)"},
    "uk": {"title": "Claude-виконавець (джерела)", "host": "хост", "ec2_api": "EC2 API", "systemd": "systemd",
           "oauth": "OAuth", "heartbeat": "heartbeat", "relay_claim": "claim", "current_task": "задача",
           "unknown": "невідомо", "checked": "перевірено", "human": "HUMAN", "ec2_note": "немає дозволу DescribeInstances (не офлайн)"},
    "ru": {"title": "Claude-исполнитель (источники)", "host": "хост", "ec2_api": "EC2 API", "systemd": "systemd",
           "oauth": "OAuth", "heartbeat": "heartbeat", "relay_claim": "claim", "current_task": "задача",
           "unknown": "неизвестно", "checked": "проверено", "human": "HUMAN", "ec2_note": "нет права DescribeInstances (не офлайн)"},
}
ICONS = {"ok": "✅", "warn": "🟡", "fail": "❌", "idle": "⚪", "unknown": "❔"}


def worker_overview_text(overview: dict, lang: str = "ru") -> str:
    """Compact per-source line block for Telegram /status; same signals the Worker Center shows."""
    t = TEXT.get(lang) or TEXT["ru"]
    lines = ["— " + t["title"] + " —"]
    for sig in overview.get("signals") or []:
        sid = str(sig.get("id") or "")
        value = t["ec2_note"] if sid == "ec2_api" else str(sig.get("value") or "")
        if sid == "current_task" and sig.get("stage"):
            value += " · " + str(sig["stage"])
        if sig.get("state") == "unknown" and sid != "ec2_api":
            value = t["unknown"] + (" · " + value if value else "")
        lines.append(ICONS.get(str(sig.get("state")), "•") + " " + t.get(sid, sid) + ": " + value[:120])
    if overview.get("last_verified_at"):
        lines.append(t["checked"] + ": " + str(overview["last_verified_at"])[:16].replace("T", " ") + " UTC")
    blockers = [b["id"] for b in overview.get("human_blockers") or [] if not b.get("answered")]
    if blockers:
        lines.append(t["human"] + ": " + ", ".join(blockers[:6]))
    return "\n".join(lines)
