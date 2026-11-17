"""T-592: the server compares what Telegram last showed for a Relay ticket with what the website shows now.

Every time the bot delivers a ticket view to the owner (🔄 Refresh, `/task R-…`, a worker notice) the server
logs the facts that view carried: stage, run_id and last worker contact, plus whether each value literally
appears in the delivered text. The log keeps no chat id, no message text and no secrets: only the ticket id,
a UTC time, the kind of view and those three facts.

`compare()` puts the newest delivered detail view next to the same ticket as the web read model shows it now
(`RelayQueue.view`, the source of /relay and the Worker Center) and returns one verdict:

    match      Telegram and the website show the same stage, run_id and last contact
    outdated   the ticket changed after Telegram showed it; press 🔄 in Telegram and compare again
    mismatch   Telegram showed different facts than the website for the same ticket state (a bug)
    no_view    Telegram has not shown this ticket since the log exists; open it there (🔄) first

The owner then presses «Совпадает / Не совпадает» once; that answer is stored next to the server verdict.
Nothing here calls Telegram.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

FIELDS = ("stage", "run_id", "last_contact")
ACTIVE = {"claimed", "running", "checkpoint", "committed", "pushed"}
VIEW_KINDS = ("detail", "notice")
VERDICTS = ("match", "outdated", "mismatch", "no_view")
OWNER_VERDICTS = ("match", "mismatch")
MAX_VIEWS = 300
MAX_CONFIRMATIONS = 50
# Stage labels the bot prints (relay._ticket_card / worker notices); a stage counts as shown if its label or code is in the text.
STAGE_WORDS = {
    "queued": ("В очереди",), "claimed": ("Получено worker",), "running": ("Claude работает", "работает"),
    "checkpoint": ("В процессе",), "committed": ("Commit",), "pushed": ("Push",), "done": ("Выполнено", "закончил"),
    "blocked": ("Нужна помощь", "помощь"), "failed": ("Ошибка", "ошибка"), "stale": ("без связи",),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ts(value: Any) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def contact_text(value: Any) -> str:
    """Last contact the way both the bot and this comparison print it: `YYYY-MM-DD HH:MM:SS` (UTC)."""
    return str(value or "")[:19].replace("T", " ")


def ticket_facts(view: dict) -> dict:
    """Stage, run_id and last worker contact of one ticket from the web read model (`RelayQueue.view`)."""
    view = view if isinstance(view, dict) else {}
    ex = view.get("execution") or {}
    return {"ticket_id": str(view.get("id") or "").upper(), "stage": str(ex.get("state") or ""),
            "run_id": str(ex.get("run_id") or "")[:120], "last_contact": contact_text(ex.get("last_seen_at"))}


def shown_in_text(facts: dict, text: str) -> dict:
    """Which facts the delivered Telegram text really contains. Last contact is printed only for active/stale work."""
    text = str(text or "")
    stage = facts.get("stage") or ""
    words = (stage,) + STAGE_WORDS.get(stage, ())
    needs_contact = stage in ACTIVE or stage == "stale"
    return {"stage": bool(stage) and any(w and w in text for w in words),
            "run_id": bool(facts.get("run_id")) and facts["run_id"] in text,
            "last_contact": (bool(facts.get("last_contact")) and facts["last_contact"] in text) if needs_contact else None}


def ticket_changed_at(view: dict) -> Optional[float]:
    """Newest server-side change of the ticket: its last history event or the worker's last contact."""
    view = view if isinstance(view, dict) else {}
    stamps = [_ts(e.get("at")) for e in view.get("history") or [] if isinstance(e, dict)
              and e.get("action") != "owner_notified"]
    stamps.append(_ts((view.get("execution") or {}).get("last_seen_at")))
    stamps = [x for x in stamps if x is not None]
    return max(stamps) if stamps else None


def compare(snapshot: Optional[dict], view: Optional[dict]) -> dict:
    """One verdict for the owner card; see the module docstring."""
    site = ticket_facts(view or {})
    if not snapshot:
        return {"verdict": "no_view", "ticket_id": site["ticket_id"], "site": site, "telegram": None, "rows": [], "problems": []}
    tg = {k: str((snapshot.get("facts") or {}).get(k) or "") for k in FIELDS}
    shown = snapshot.get("shown") or {}
    rows, problems = [], []
    for field in FIELDS:
        same = tg[field] == site[field]
        hidden = shown.get(field) is False and bool(tg[field])
        rows.append({"field": field, "telegram": tg[field], "site": site[field], "match": same and not hidden,
                     "shown_in_telegram": shown.get(field)})
        if hidden:
            problems.append("not_shown:" + field)
    if site["stage"] == "stale":
        problems.append("worker_stale")
    changed = ticket_changed_at(view or {})
    seen_at = _ts(snapshot.get("at"))
    differs = any(not r["match"] for r in rows)
    if not differs and not problems:
        verdict = "match"
    elif differs and not any(p.startswith("not_shown") for p in problems) and changed and seen_at and changed > seen_at:
        verdict = "outdated"
    else:
        verdict = "mismatch"
    return {"verdict": verdict, "ticket_id": site["ticket_id"], "site": site, "telegram": {**tg, "at": snapshot.get("at"),
            "kind": snapshot.get("kind")}, "rows": rows, "problems": problems}


class TelegramViewLog:
    """Small JSON file: what the bot delivered (facts only) and the owner's «Совпадает / Не совпадает» answers."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        return {"views": [x for x in data.get("views") or [] if isinstance(x, dict)],
                "confirmations": [x for x in data.get("confirmations") or [] if isinstance(x, dict)]}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def record(self, view: dict, kind: str, text: str) -> Optional[dict]:
        """Log one delivered view. Call only after the Bot API accepted the message. Never stores the text itself."""
        facts = ticket_facts(view)
        if not facts["ticket_id"] or kind not in VIEW_KINDS:
            return None
        entry = {"ticket_id": facts["ticket_id"], "at": _now(), "kind": kind,
                 "facts": {k: facts[k] for k in FIELDS}, "shown": shown_in_text(facts, text)}
        with self.lock:
            data = self._load()
            data["views"] = (data["views"] + [entry])[-MAX_VIEWS:]
            self._save(data)
        return entry

    def latest(self, ticket_id: str = "", kind: str = "detail") -> Optional[dict]:
        tid = str(ticket_id or "").upper()
        with self.lock:
            views = self._load()["views"]
        return next((v for v in reversed(views) if v.get("kind") == kind and (not tid or v.get("ticket_id") == tid)), None)

    def confirm(self, ticket_id: str, owner_verdict: str, server: dict) -> dict:
        if owner_verdict not in OWNER_VERDICTS:
            raise ValueError("verdict must be match or mismatch")
        entry = {"ticket_id": str(ticket_id or "").upper()[:20], "at": _now(), "owner": owner_verdict,
                 "server": str(server.get("verdict") or ""), "telegram_at": str((server.get("telegram") or {}).get("at") or "")}
        with self.lock:
            data = self._load()
            data["confirmations"] = (data["confirmations"] + [entry])[-MAX_CONFIRMATIONS:]
            self._save(data)
        return entry

    def latest_confirmation(self) -> Optional[dict]:
        with self.lock:
            items = self._load()["confirmations"]
        return items[-1] if items else None


def owner_status(confirmation: Optional[dict], prerequisite_done: bool) -> dict:
    """Owner-desk status for T-592-H (detail keys localized in owner_desk_i18n.STATUS_DETAILS)."""
    if not prerequisite_done:
        return {"state": "blocked", "detail_key": "waits", "args": {"task": "T-591-H"}}
    if confirmation and confirmation.get("owner") == "match" and confirmation.get("server") == "match":
        return {"state": "done", "detail_key": "compare_confirmed", "args": {"ticket": confirmation.get("ticket_id") or "—"}}
    if confirmation and confirmation.get("owner") == "mismatch":
        return {"state": "todo", "detail_key": "compare_owner_mismatch", "args": {"ticket": confirmation.get("ticket_id") or "—"}}
    return {"state": "todo", "detail_key": "compare_ready"}
