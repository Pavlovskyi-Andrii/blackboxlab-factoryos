"""#260: offline acceptance check for a redacted Relay smoke trace (the #256 round-trip).

It only judges evidence it is given; it never calls GitHub, Relay or Telegram and never creates proof.
A trace is VERIFIED only when every stage is present and consistent:

    GitHub issue -> Relay ticket (sourced from that issue) -> one run_id -> claimed -> running -> done
    -> owner-visible Telegram delivery receipt after done

Heartbeats, a bare HTTP 200, or a claim POST without recorded events are not evidence of execution.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

STAGES = ("issue", "ticket", "claimed", "running", "done", "telegram")
MAX_DELIVERY_DELAY_SECONDS = 3600  # a receipt much later than "done" is not the delivery of this run


def _ts(value: Any) -> float | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def verify_smoke_trace(trace: Any, *, expected_issue: int = 256) -> dict:
    """Return {"status": "VERIFIED"|"UNVERIFIED", "missing": [stage...], "problems": [text...], "run_id": str}."""
    missing: list[str] = []
    problems: list[str] = []
    if not isinstance(trace, dict):
        return {"status": "UNVERIFIED", "missing": list(STAGES), "problems": ["trace is not an object"], "run_id": ""}

    try:
        issue = int(trace.get("issue"))
    except (TypeError, ValueError):
        issue = 0
    if issue != expected_issue:
        missing.append("issue")
        if issue:
            problems.append(f"trace is for issue #{issue}, expected #{expected_issue}")

    ticket = trace.get("ticket") if isinstance(trace.get("ticket"), dict) else {}
    ticket_id = str(ticket.get("id") or "")
    if not ticket_id:
        missing.append("ticket")
    else:
        try:
            source_issue = int(ticket.get("source_issue"))
        except (TypeError, ValueError):
            source_issue = 0
        if source_issue != expected_issue:
            problems.append("Relay ticket is not sourced from the expected GitHub issue")

    events = [e for e in trace.get("events") or [] if isinstance(e, dict)]
    by_stage: dict[str, dict] = {}
    for event in events:
        stage = str(event.get("stage") or "")
        if stage == "heartbeat":
            continue  # liveness only, never execution evidence
        if stage in ("claimed", "running", "done") and stage not in by_stage:
            by_stage[stage] = event
    for stage in ("claimed", "running", "done"):
        if stage not in by_stage:
            missing.append(stage)

    run_ids = {str(e.get("run_id") or "") for e in by_stage.values()}
    run_id = next(iter(run_ids)) if len(run_ids) == 1 else ""
    if "" in run_ids:
        problems.append("an execution event has no run_id")
    if len(run_ids - {""}) > 1:
        problems.append("events carry different run_ids")
    if ticket.get("run_id") and run_id and str(ticket.get("run_id")) != run_id:
        problems.append("ticket run_id does not match the events")

    times = {stage: _ts(event.get("at")) for stage, event in by_stage.items()}
    for stage, at in times.items():
        if at is None:
            problems.append(f"{stage} has no valid timestamp")
    ordered = [times.get(s) for s in ("claimed", "running", "done") if times.get(s) is not None]
    if ordered != sorted(ordered):
        problems.append("stages are out of order (claimed -> running -> done)")
    if "done" in by_stage and not str(by_stage["done"].get("result") or "").strip():
        problems.append("done has no result")

    if trace.get("http_status") == 200 and not by_stage:
        problems.append("an HTTP 200 alone is not evidence of execution")

    telegram = trace.get("telegram") if isinstance(trace.get("telegram"), dict) else {}
    delivered_at = _ts(telegram.get("delivered_at"))
    if not (telegram.get("delivered") is True and telegram.get("message_id") and delivered_at is not None):
        missing.append("telegram")
    elif times.get("done") is not None:
        delay = delivered_at - times["done"]
        if delay < 0:
            problems.append("Telegram delivery is older than the done event")
        elif delay > MAX_DELIVERY_DELAY_SECONDS:
            problems.append("Telegram delivery is stale for this run")

    verified = not missing and not problems
    return {"status": "VERIFIED" if verified else "UNVERIFIED", "missing": missing, "problems": problems,
            "run_id": run_id if verified else ""}
