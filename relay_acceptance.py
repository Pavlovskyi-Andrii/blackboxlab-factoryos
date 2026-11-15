"""T-591: live owner-acceptance report for one Relay ticket, judged only from durable server facts.

The owner sends one real test task in the paired Telegram chat; this module then answers "did the whole
chain really happen?" from the ticket's own append-only history, never from model-written status:

    Telegram message (paired chat) -> exactly one ticket for that update -> authenticated worker claim with a
    run_id -> running -> done (same run_id, in order, with a result) -> Telegram delivery receipt for that
    final notice (recorded by the server when the Bot API accepted it)

Code tasks additionally need the branch / PR link the worker reported; PR / CI / merge / deploy stay "not
verified" until the GitHub/Render reconcilers record them. Nothing here calls Telegram, GitHub or Render, and
nothing creates evidence: a missing fact is reported as missing.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable, Optional

from relay_execution import lifecycle, redact

REQUIRED = ("telegram_intake", "single_ticket", "claimed", "running", "final", "result", "owner_notified")
MAX_NOTICE_DELAY_SECONDS = 3600  # a receipt much later than the final event is not the notice of this run
OWNER_NOTIFIED = "owner_notified"


def _ts(value: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _current_run(history: list) -> tuple[int, Optional[dict]]:
    """Index and event of the last `claimed`; older attempts never count for this run."""
    for index in range(len(history) - 1, -1, -1):
        if str(history[index].get("action") or "") == "claimed":
            return index, history[index]
    return -1, None


def acceptance_report(ticket: dict, all_tickets: Iterable[dict] = ()) -> dict:
    """{"status": VERIFIED|UNVERIFIED, "ticket_id", "run_id", "stages": [...], "problems": [...], "code": [...]}"""
    ticket = ticket if isinstance(ticket, dict) else {}
    history = [e for e in ticket.get("history") or [] if isinstance(e, dict)]
    source = ticket.get("source") or {}
    ex = ticket.get("execution") or {}
    stages: dict[str, dict] = {name: {"stage": name, "ok": False, "at": "", "detail": ""} for name in REQUIRED}
    problems: list[str] = []

    def mark(name: str, at: Any = "", detail: Any = "") -> None:
        stages[name].update(ok=True, at=str(at or ""), detail=redact(detail)[:240])

    # 1. Intake: only the paired private chat can create a Telegram-sourced ticket (relay_handle_telegram_update).
    source_key = str(source.get("source_key") or "")
    if source.get("channel") == "telegram" and source.get("chat_id") and (source.get("update_id") or source.get("message_id")):
        mark("telegram_intake", ticket.get("created_at"), source_key)
    else:
        problems.append("ticket was not created from the paired Telegram chat")

    # 2. Dedupe: one durable ticket for this Telegram update.
    same = [t for t in all_tickets if isinstance(t, dict) and source_key
            and str((t.get("source") or {}).get("source_key") or "") == source_key]
    if source_key and len(same) == 1:
        mark("single_ticket", "", f"1 ticket for {source_key}")
    elif source_key and len(same) > 1:
        problems.append(f"{len(same)} tickets share {source_key}")

    # 3–5. One run: claimed -> running -> final, same run_id, in time order.
    start, claimed = _current_run(history)
    run_id = str((claimed or {}).get("run_id") or "")
    worker = str((claimed or {}).get("actor") or "")
    if claimed and run_id and worker:
        mark("claimed", claimed.get("at"), f"{worker} · {run_id}")
    elif claimed:
        problems.append("claim has no worker id or run_id")
    later = history[start + 1:] if start >= 0 else []
    same_run = [e for e in later if str(e.get("run_id") or "") == run_id] if run_id else []
    running = next((e for e in same_run if e.get("action") == "running"), None)
    if running:
        mark("running", running.get("at"), str(running.get("actor") or ""))
    final = next((e for e in same_run if e.get("action") in ("done", "blocked", "failed")), None)
    if final:
        if final.get("action") == "done":
            mark("final", final.get("at"), "done")
        else:
            problems.append(f"the run ended {final.get('action')}: {redact(final.get('note'))[:160]}")
    if any(str(e.get("run_id") or "") not in ("", run_id) and e.get("action") in ("running", "done", "blocked", "failed")
           for e in later):
        problems.append("events from another run_id after this claim")
    order = [_ts(e.get("at")) for e in (claimed, running, final) if e]
    if None in order:
        problems.append("an execution event has no valid timestamp")
    elif order != sorted(order):
        problems.append("stages are out of order (claimed -> running -> final)")

    # 6. Result: the worker's own summary of what it did, plus links for code work.
    evidence = dict((final or {}).get("evidence") or {})
    if final and final.get("action") == "done" and str(final.get("note") or "").strip():
        mark("result", final.get("at"), final.get("note"))
    elif final and final.get("action") == "done":
        problems.append("done has no result summary")
    commit = str(evidence.get("commit") or ex.get("commit") or "")
    links = [x for x in (ex.get("pr_url"), evidence.get("pr_url")) if x]
    branch = str(evidence.get("branch") or ex.get("branch") or "")
    if commit and not (links or branch):
        problems.append("a commit was reported without a branch or PR link")

    # 7. Owner notice: the server recorded that Telegram accepted the final notice of this run.
    receipt = next((e for e in history[start + 1:] if e.get("action") == OWNER_NOTIFIED and final
                    and str(e.get("stage") or "") == str(final.get("action") or "")
                    and str(e.get("run_id") or "") == run_id), None) if start >= 0 else None
    if receipt:
        delay = (_ts(receipt.get("at")) or 0) - (_ts(final.get("at")) or 0)
        if 0 <= delay <= MAX_NOTICE_DELAY_SECONDS:
            mark(OWNER_NOTIFIED, receipt.get("at"), "Telegram Bot API accepted the notice")
        else:
            problems.append("the Telegram receipt does not belong to this final event")

    code = [{"stage": row["stage"], "state": row["state"], "at": row["at"], "detail": row["detail"]}
            for row in lifecycle(ticket) if row["stage"] in ("committed", "pushed", "pr", "ci", "merged", "deployed")]
    missing = [name for name in REQUIRED if not stages[name]["ok"]]
    verified = not missing and not problems
    return {"status": "VERIFIED" if verified else "UNVERIFIED", "ticket_id": str(ticket.get("id") or ""),
            "run_id": run_id, "worker_id": worker, "stages": [stages[n] for n in REQUIRED], "missing": missing,
            "problems": problems, "code": code, "links": [str(x)[:300] for x in links],
            "commit": commit[:40], "branch": branch[:120]}


_TEXT = {
    "ru": {"title": "🧾 Приёмка {id}", "verified": "✅ ПОДТВЕРЖДЕНО сервером", "unverified": "❔ НЕ подтверждено",
           "telegram_intake": "сообщение из привязанного чата", "single_ticket": "ровно один тикет",
           "claimed": "claim воркера (run_id)", "running": "running", "final": "done", "result": "итог воркера",
           "owner_notified": "уведомление доставлено в Telegram", "code": "Код (только записанные факты):",
           "unverified_row": "не проверено", "problems": "Проблемы:"},
    "uk": {"title": "🧾 Приймання {id}", "verified": "✅ ПІДТВЕРДЖЕНО сервером", "unverified": "❔ НЕ підтверджено",
           "telegram_intake": "повідомлення з прив'язаного чату", "single_ticket": "рівно один тікет",
           "claimed": "claim воркера (run_id)", "running": "running", "final": "done", "result": "підсумок воркера",
           "owner_notified": "сповіщення доставлено в Telegram", "code": "Код (лише записані факти):",
           "unverified_row": "не перевірено", "problems": "Проблеми:"},
    "en": {"title": "🧾 Acceptance {id}", "verified": "✅ VERIFIED by the server", "unverified": "❔ NOT verified",
           "telegram_intake": "message from the paired chat", "single_ticket": "exactly one ticket",
           "claimed": "worker claim (run_id)", "running": "running", "final": "done", "result": "worker result",
           "owner_notified": "notice delivered to Telegram", "code": "Code (recorded facts only):",
           "unverified_row": "not verified", "problems": "Problems:"},
}


def acceptance_text(report: dict, lang: str = "ru") -> str:
    """Compact, copyable transcript for Telegram and Issue #41 (UTC timestamps, IDs, links; no secrets)."""
    t = _TEXT.get(lang) or _TEXT["ru"]
    lines = [t["title"].format(id=report.get("ticket_id") or "?"),
             t["verified"] if report.get("status") == "VERIFIED" else t["unverified"]]
    if report.get("run_id"):
        lines.append(f"run_id {report['run_id']} · {report.get('worker_id') or '?'}")
    for row in report.get("stages") or []:
        at = (row.get("at") or "")[:19].replace("T", " ")
        parts = [("✅ " if row.get("ok") else "⏳ ") + t.get(row["stage"], row["stage"])]
        if at:
            parts.append(at + " UTC")
        if row.get("detail") and row["stage"] != "final":
            parts.append(str(row["detail"])[:120])
        lines.append(" · ".join(parts))
    recorded = [r for r in report.get("code") or [] if r.get("state") in ("recorded", "linked")]
    if recorded or report.get("links") or report.get("commit") or report.get("branch"):
        lines.append(t["code"])
        facts = [x for x in (("commit " + report["commit"][:12]) if report.get("commit") else "",
                             ("branch " + report["branch"]) if report.get("branch") else "") if x]
        if facts:
            lines.append("• " + " · ".join(facts) + " (worker report)")
        lines.extend("• " + link for link in report.get("links") or [])
        for row in report.get("code") or []:
            state = row.get("detail") or row.get("state") if row.get("state") in ("recorded", "linked") else t["unverified_row"]
            lines.append(f"• {row['stage']}: {str(state)[:120]}")
    if report.get("problems"):
        lines.append(t["problems"])
        lines.extend("• " + str(p)[:200] for p in report["problems"])
    return redact("\n".join(lines))[:3900]


def latest_telegram_acceptance(tickets: Iterable[dict]) -> Optional[dict]:
    """Owner desk status for T-591-H: the newest VERIFIED Telegram ticket, else the newest Telegram ticket's report."""
    tickets = [t for t in tickets if isinstance(t, dict)]
    telegram = sorted((t for t in tickets if (t.get("source") or {}).get("channel") == "telegram"),
                      key=lambda t: str(t.get("created_at") or ""), reverse=True)
    reports = [acceptance_report(t, tickets) for t in telegram[:50]]
    return next((r for r in reports if r["status"] == "VERIFIED"), reports[0] if reports else None)
