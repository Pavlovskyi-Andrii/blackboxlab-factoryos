"""MCP `ops_health` (owner 2026-11-27: «чтобы у тебя был доступ» to the EC2 worker and Telegram).

One read-only snapshot for the Claude lane: is the EC2 Claude worker alive, is the owner's Telegram chat paired, did
the latest MyCast and morning-brief deliveries go out, is the Ops relay switched on and polled, is the Media Finisher
connected. Until now this was visible only in the owner's browser session. No chat ids, usernames, tokens or message
text leave the server; the worker's last error is cut short and known secrets are masked out of it.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Iterable, Optional

LANES = frozenset({"claude"})
TOOL = {
    "name": "ops_health",
    "description": ("Read-only FactoryOS health for the Claude lane: EC2 Claude worker heartbeat and current task, owner "
                    "Telegram pairing, the latest MyCast / morning-brief deliveries (status, length), Ops relay gate "
                    "and EC2 ops-agent polling, Media Finisher connection and its latest edit jobs (status, stage, QA "
                    "verdicts, Shorts count, timings). No secrets, chat ids, media links or transcript text."),
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


_URL = re.compile(r"https?://\S+")


def _num(value):
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return None


def endpoint_host(value) -> str:
    """host[:port] of the worker address the server submits to; never a path, query or credential."""
    from urllib.parse import urlsplit
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw if "://" in raw else "http://" + raw)
        host = parts.hostname or ""
        return (host + (f":{parts.port}" if parts.port else ""))[:120]
    except ValueError:
        return "unparseable"


def edit_job_summary(job: dict, secrets: Iterable[str] = ()) -> dict:
    """One Media Finisher edit job without its media links or the speaker's words: what the reviewer checks first."""
    request = job.get("request") if isinstance(job.get("request"), dict) else {}
    response = job.get("response") if isinstance(job.get("response"), dict) else {}
    report = job.get("report") if isinstance(job.get("report"), dict) else {}
    options = request.get("options") if isinstance(request.get("options"), dict) else {}
    summary = report.get("edit_summary") if isinstance(report.get("edit_summary"), dict) else {}
    qa = report.get("qa_report") if isinstance(report.get("qa_report"), dict) else {}
    metrics = report.get("render_metrics") if isinstance(report.get("render_metrics"), dict) else {}
    shorts = report.get("shorts_manifest") if isinstance(report.get("shorts_manifest"), dict) else {}
    clips = [c for c in shorts.get("clips") or [] if isinstance(c, dict)]
    flagged = []
    for check in qa.get("checks") or []:
        if isinstance(check, dict) and check.get("status") not in ("pass", None):
            row = {"id": str(check.get("id") or "")[:40], "status": str(check.get("status") or "")[:12]}
            for key in ("lost_words", "clipped_words", "slivers", "pauses", "issues"):  # counts only: never the words
                if isinstance(check.get(key), list):
                    row[key] = len(check[key])
            for key in ("measured_lufs", "target_lufs", "violations", "expected_sec", "actual_sec"):
                if key in check and not isinstance(check[key], (list, dict)):
                    row[key] = check[key]
            flagged.append(row)
    return {
        "id": str(job.get("id") or "")[:12], "status": str(job.get("status") or "")[:20],
        "stage": str(response.get("stage") or "")[:24], "percent": _num(response.get("percent")),
        "provider": str(job.get("provider") or "")[:30], "platform": str(job.get("platform") or "")[:20],
        "shorts_requested": bool(options.get("split_shortform")), "edit_full_video": options.get("edit_full_video"),
        "created_at": job.get("created_at"), "updated_at": job.get("updated_at"), "completed_at": job.get("completed_at"),
        "error": _URL.sub("[link]", _masked(job.get("error"), secrets, 400))[:200],  # signed links carry tokens
        "duration_before_sec": _num(summary.get("duration_before_sec")), "duration_after_sec": _num(summary.get("duration_after_sec")),
        "removed_segments": summary.get("removed_segments"), "filler_segments_removed": summary.get("filler_segments_removed"),
        "graphics_engine": summary.get("graphics_engine"),
        "qa_overall": qa.get("overall"), "qa_flagged": flagged[:12],
        "shorts": {"enabled": bool(shorts.get("enabled")), "clips": len(clips),
                   "clip_seconds": [_num(c.get("duration_sec")) for c in clips[:8]]},
        "render_wall_sec": _num(metrics.get("wall_sec")), "realtime_factor": _num(metrics.get("realtime_factor")),
    }


def snapshot(lane: str, *, worker: dict, telegram: dict, deliveries: list, ops: dict, finisher: dict,
             known_secrets: Callable[[], Iterable[str]] = lambda: (), now: Optional[float] = None,
             edit_jobs: Iterable[dict] = ()) -> dict:
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
                           "endpoint_host": endpoint_host(finisher.get("endpoint")),
                           "token_configured": bool(finisher.get("token")),
                           "recent_jobs": [edit_job_summary(j, secrets) for j in list(edit_jobs)[:5] if isinstance(j, dict)]},
    }
