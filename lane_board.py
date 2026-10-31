"""T-599-F: per-lane Workers / Build Progress / Telegram read model from verified events only.

One pure function, ``build_lane_board``, turns ROADMAP tasks, durable Relay tickets (claims,
run_id-fenced worker events) and lane heartbeats into a lane summary and a five-column board.
Web (``GET /api/factory/lane-board``) and Telegram (``/status``, ``/tasks``) render this same
dict, so both always show the same task and stage. Nothing here infers activity: a task with an
``Owner:`` but no claim is "assigned, not claimed", and a lane is "working" only while it has a
claimed run with a fresh event.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Iterable, Optional

LANES = ("claude", "chatgpt", "gemini")
LANE_STATES = ("working", "blocked", "stale", "idle", "offline")
COLUMNS = ("planned", "in_progress", "blocked", "review", "done")
ACTIVE = ("claimed", "running", "checkpoint", "committed", "pushed")
SHARED = ("", "any", "auto")


def _ts(value) -> Optional[float]:
    if isinstance(value, (int, float)):
        return float(value) if value > 0 else None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (ValueError, TypeError):
        return None


def _last_event(ticket: dict) -> dict:
    """Latest worker-recorded event of the current run (heartbeats are not stored in history)."""
    for event in reversed(ticket.get("history") or []):
        if str(event.get("action") or "") in ACTIVE + ("done", "blocked", "failed", "stale_released"):
            return {"action": str(event.get("action")), "at": str(event.get("at") or ""),
                    "actor": str(event.get("actor") or "")[:80]}
    return {}


def _ticket_task_key(ticket: dict) -> str:
    source = ticket.get("source") or {}
    if source.get("channel") == "roadmap":
        return str(source.get("task_id") or "")
    return ""


def _issue_lane(ticket: dict) -> str:
    source = ticket.get("source") or {}
    if source.get("channel") != "github":
        return ""
    lane = str(source.get("owner") or "").lower()
    return lane if lane in LANES else ""


def _run(ticket: Optional[dict], now: float, stale_seconds: int) -> dict:
    """Factual run state of one ticket: stage, freshness and evidence."""
    if not ticket:
        return {}
    ex = ticket.get("execution") or {}
    stage = str(ex.get("state") or "")
    seen = _ts(ex.get("last_seen_at") or ex.get("claimed_at"))
    stale = stage in ACTIVE and (seen is None or now - seen > stale_seconds)
    return {
        "ticket_id": str(ticket.get("id") or ""),
        "stage": "stale" if stale else stage,
        "worker_stage": stage,
        "lane": str(ex.get("owner") or "").lower(),
        "worker_id": str(ex.get("worker_id") or "")[:80],
        "run_id": str(ex.get("run_id") or "")[:40],
        "started_at": str(ex.get("started_at") or ex.get("claimed_at") or ""),
        "last_seen_at": str(ex.get("last_seen_at") or ""),
        "pr_url": str(ex.get("pr_url") or ""),
        "commit": str(ex.get("commit") or "")[:12],
        "last_event": _last_event(ticket),
        "note": str(ex.get("note") or "")[:200],
    }


def _column(done: bool, run: dict) -> str:
    if done:
        return "done"
    stage = run.get("stage") or ""
    if stage in ACTIVE:
        return "in_progress"
    if stage in ("blocked", "failed", "stale"):
        return "blocked"
    if stage == "done":
        # Worker reported done with evidence; the ROADMAP checkbox reaches main only after PR/merge.
        return "review"
    return "planned"


def _claimed(run: dict) -> bool:
    return (run.get("stage") or "") not in ("", "queued")


def _claim(owner: str, run: dict) -> str:
    """Queued is still pre-claim: an owned task without a claimed event is "assigned, not claimed"."""
    if _claimed(run):
        return "claimed"
    if owner in SHARED:
        return "queued" if run.get("stage") == "queued" else "unassigned"
    return "assigned_not_claimed"


def build_lane_board(roadmap_tasks: Iterable[dict], tickets: Iterable[dict], heartbeats: Optional[dict] = None, *,
                     now: Optional[float] = None, stale_seconds: int = 180, heartbeat_ttl: int = 180,
                     offline_after: int = 3600) -> dict:
    """Return ``{"lanes": {...}, "columns": {...}, "tasks": [...], "counts": {...}}``.

    ``heartbeats`` maps lane -> last heartbeat epoch seconds, or ``{"last_seen", "online"}`` when the
    server already applied its own TTL (absent = never seen). A heartbeat younger than
    ``heartbeat_ttl`` is online, one younger than ``offline_after`` is stale, older or
    missing is offline. Run freshness uses the run's own events (``stale_seconds``), so a lane with
    no heartbeat reporter (ChatGPT) is "working" only while its own claimed run keeps reporting.
    """
    now = time.time() if now is None else float(now)
    heartbeats = heartbeats or {}
    tickets = [t for t in tickets or [] if isinstance(t, dict)]
    by_task = {}
    for ticket in tickets:
        key = _ticket_task_key(ticket)
        if key:
            by_task[key] = ticket

    tasks = []
    for task in roadmap_tasks or []:
        owner = str(task.get("owner") or "").lower()
        run = _run(by_task.get(task["id"]), now, stale_seconds)
        lane = run["lane"] if _claimed(run) and run.get("lane") not in SHARED else owner
        tasks.append({
            "id": task["id"], "title": str(task.get("title") or "")[:150], "kind": "roadmap",
            "owner": owner or "any", "lane": lane if lane not in SHARED else "unassigned",
            "human": bool(task.get("human")), "done": bool(task.get("done")),
            "column": _column(bool(task.get("done")), run), "claim": _claim(owner, run),
            "stage": run.get("stage") or "", "run": run,
        })
    for ticket in tickets:
        lane = _issue_lane(ticket)
        if not lane or str(ticket.get("status") or "") == "archived":
            continue
        run = _run(ticket, now, stale_seconds)
        done = str(ticket.get("status") or "") == "done"
        tasks.append({
            "id": str(ticket.get("id") or ""), "title": str(ticket.get("title") or "")[:150], "kind": "issue",
            "owner": lane, "lane": lane, "human": False, "done": done,
            "column": "done" if done else _column(False, run), "claim": _claim(lane, run),
            "stage": "done" if done else (run.get("stage") or ""), "run": run,
        })

    lanes = {}
    for lane in LANES:
        mine = [t for t in tasks if t["lane"] == lane]
        runs = [t for t in tickets if str((t.get("execution") or {}).get("owner") or "").lower() == lane]
        views = [(_run(t, now, stale_seconds), t) for t in runs]
        active = [v for v, _ in views if v["stage"] in ACTIVE]
        lost = [v for v, _ in views if v["stage"] == "stale"]
        finished = sorted((v for v, _ in views if v["worker_stage"] in ("done", "blocked", "failed")),
                          key=lambda v: v["last_event"].get("at") or "")
        reported = heartbeats.get(lane)
        if isinstance(reported, dict):
            beat, online = _ts(reported.get("last_seen")), reported.get("online")
        else:
            beat, online = _ts(reported), None
        age = round(max(0.0, now - beat), 1) if beat else None
        if online is None:
            online = age is not None and age <= heartbeat_ttl
        if active:
            state, run = "working", max(active, key=lambda v: v["last_seen_at"])
        elif lost:
            state, run = "stale", max(lost, key=lambda v: v["last_seen_at"])
        elif online and age is not None:
            run = finished[-1] if finished else {}
            state = "blocked" if run.get("worker_stage") in ("blocked", "failed") else "idle"
        else:
            run = finished[-1] if finished else {}
            state = "stale" if age is not None and age <= offline_after else "offline"
        task_id = ""
        if run:
            task_id = next((t["id"] for t in tasks if t["run"].get("ticket_id") == run["ticket_id"]), run["ticket_id"])
        col_counts = {c: sum(1 for t in mine if t["column"] == c) for c in COLUMNS}
        lanes[lane] = {
            "lane": lane, "state": state,
            "heartbeat_age_seconds": age,
            "task_id": task_id if state in ("working", "stale", "blocked") else "",
            "last_task_id": task_id,
            "stage": run.get("stage", "") if state in ("working", "stale", "blocked") else "",
            "started_at": run.get("started_at", ""),
            "last_event": run.get("last_event") or {},
            "pr_url": run.get("pr_url", ""),
            "run_id": run.get("run_id", ""),
            "columns": col_counts,
            "done": col_counts["done"],
            "remaining": len(mine) - col_counts["done"],
            "assigned_not_claimed": [t["id"] for t in mine if t["claim"] == "assigned_not_claimed" and not t["done"]],
        }
    columns = {c: [t["id"] for t in tasks if t["column"] == c] for c in COLUMNS}
    return {
        "lanes": lanes, "columns": columns, "tasks": tasks,
        "counts": {c: len(columns[c]) for c in COLUMNS},
        "assigned_not_claimed": [t["id"] for t in tasks if t["claim"] == "assigned_not_claimed" and not t["done"]],
        "source": "relay-events+heartbeat",
    }


# Telegram copy. The web dashboard uses the same keys under ``lb.*`` in static/index.html.
TEXT = {
    "en": {"title": "Lanes (verified events)", "working": "Working", "blocked": "Blocked", "stale": "Stale",
           "idle": "Idle", "offline": "Offline", "task": "task", "stage": "stage", "since": "since",
           "last": "last event", "pr": "PR", "done": "done", "remaining": "remaining",
           "unclaimed": "assigned, not claimed", "planned": "Planned", "in_progress": "In progress",
           "review": "Review", "none": "—"},
    "uk": {"title": "Лінії (підтверджені події)", "working": "Працює", "blocked": "Заблоковано", "stale": "Немає зв'язку",
           "idle": "Вільний", "offline": "Офлайн", "task": "задача", "stage": "етап", "since": "з",
           "last": "остання подія", "pr": "PR", "done": "готово", "remaining": "залишилось",
           "unclaimed": "призначено, не взято", "planned": "Заплановано", "in_progress": "У роботі",
           "review": "Перевірка", "none": "—"},
    "ru": {"title": "Линии (подтверждённые события)", "working": "Работает", "blocked": "Заблокирован", "stale": "Нет связи",
           "idle": "Свободен", "offline": "Офлайн", "task": "задача", "stage": "этап", "since": "с",
           "last": "последнее событие", "pr": "PR", "done": "готово", "remaining": "осталось",
           "unclaimed": "назначено, не взято", "planned": "Запланировано", "in_progress": "В работе",
           "review": "Проверка", "none": "—"},
}
ICONS = {"working": "🟢", "blocked": "🙋", "stale": "🟡", "idle": "⚪", "offline": "⚫"}
LABELS = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini"}


def telegram_lang(code: str) -> str:
    code = str(code or "").lower()[:2]
    return code if code in TEXT else "ru"


def lane_board_text(board: dict, lang: str = "ru") -> str:
    """Per-lane summary for Telegram /status and /tasks; same fields the web lane cards show."""
    t = TEXT.get(lang) or TEXT["ru"]
    lines = ["— " + t["title"] + " —"]
    for lane in LANES:
        row = (board.get("lanes") or {}).get(lane) or {}
        state = str(row.get("state") or "offline")
        head = ICONS.get(state, "•") + " " + LABELS[lane] + ": " + t.get(state, state)
        if row.get("task_id"):
            head += " · " + t["task"] + " " + row["task_id"] + " · " + t["stage"] + " " + str(row.get("stage") or t["none"])
        lines.append(head)
        detail = []
        if row.get("task_id") and row.get("started_at"):
            detail.append(t["since"] + " " + str(row["started_at"])[:16].replace("T", " ") + " UTC")
        event = row.get("last_event") or {}
        if event.get("action"):
            detail.append(t["last"] + ": " + event["action"] + " " + str(event.get("at") or "")[:16].replace("T", " "))
        if row.get("pr_url"):
            detail.append(t["pr"] + " " + row["pr_url"])
        detail.append(t["done"] + " " + str(row.get("done", 0)) + " · " + t["remaining"] + " " + str(row.get("remaining", 0)))
        lines.append("   " + " · ".join(detail))
        unclaimed = row.get("assigned_not_claimed") or []
        if unclaimed:
            lines.append("   " + t["unclaimed"] + ": " + ", ".join(unclaimed[:6]) + (" …" if len(unclaimed) > 6 else ""))
    counts = board.get("counts") or {}
    column_label = {"planned": t["planned"], "in_progress": t["in_progress"], "blocked": t["blocked"],
                    "review": t["review"], "done": t["done"]}
    lines.append(" · ".join(column_label[c] + " " + str(counts.get(c, 0)) for c in COLUMNS))
    return "\n".join(lines)
