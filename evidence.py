"""Evidence Protocol, Tier 1 (docs/specs/EVIDENCE_PROTOCOL.md): No Evidence — No Done.

Levels: claimed (the agent said so) < linked (the agent gave links) < checked (the server read the source itself and
every required check passed on the current head) < accepted (the owner confirmed).

- The rules per task type live here, in code, and are copied into the ticket when it is created, so the agent cannot
  change what "done" means for its own task. Only the server's checkers write checks; only the owner overrides.
- Checkers are pure: they only read results that already exist (a GitHub read, the delivery log, a Bot API reply).
  They never start CI, synthesise audio or call a paid provider.
- A check belongs to one commit. When the PR head moves, older checks stop counting (T1.5).
- Tickets created before this module have no ``verification`` block and keep the old behaviour.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

LEVELS = ("claimed", "linked", "checked", "accepted")
RANK = {name: i for i, name in enumerate(LEVELS)}

RULES: dict[str, dict] = {
    # code: the PR is merged and CI passed on the very commit that was merged.
    "code": {"required_level": "checked", "checks": ["pr_merged", "ci_passed"]},
    # mycast: the server delivered it (delivery only happens after the audio QC passed).
    "mycast": {"required_level": "checked", "checks": ["delivered_qc"]},
    # telegram: the Bot API returned a message id (sent, not read: reading needs the owner).
    "telegram": {"required_level": "checked", "checks": ["message_sent"]},
    # publish: only the owner, through the existing approval gate.
    "publish": {"required_level": "accepted", "checks": []},
    # anything else: at least one link to evidence.
    "other": {"required_level": "linked", "checks": []},
}
CODE_LANES = ("claude", "gemini", "unassigned")
OVERRIDE_MIN_CHARS = 3


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def task_type_for(owner: str) -> str:
    """Engineering lanes produce PRs; everything else needs at least a link until a finer type is set."""
    return "code" if owner in CODE_LANES else "other"


def new_verification(task_type: str) -> dict:
    rule = RULES.get(task_type) or RULES["other"]
    return {"type": task_type if task_type in RULES else "other", "required_level": rule["required_level"],
            "required_checks": list(rule["checks"]), "checks": {}, "head_sha": "", "override": None}


def _links(execution: dict) -> bool:
    return any(execution.get(k) for k in ("pr_url", "commit", "artifact_url"))


def level(ticket: dict) -> str:
    """The level this ticket has reached now. A check on a commit other than the current head does not count."""
    ver = ticket.get("verification") or {}
    if ver.get("override") or ver.get("accepted"):
        return "accepted"
    execution = ticket.get("execution") or {}
    head = str(ver.get("head_sha") or "")
    required = ver.get("required_checks") or []
    checks = ver.get("checks") or {}
    current = [checks.get(name) for name in required]
    if required and all(c and c.get("result") == "pass" and (not head or c.get("sha") == head) for c in current):
        return "checked"
    if _links(execution):
        return "linked"
    return "claimed"


def satisfied(ticket: dict) -> bool:
    ver = ticket.get("verification")
    if not ver:
        return True                                   # legacy ticket: old behaviour
    return RANK[level(ticket)] >= RANK.get(str(ver.get("required_level") or "checked"), RANK["checked"])


def record_check(ver: dict, name: str, result: str, *, source: str, sha: str = "", detail: str = "") -> bool:
    """Server-side only. Returns True when the stored check changed (so callers notify once)."""
    entry = {"result": "pass" if result == "pass" else "fail", "source": source[:40], "sha": str(sha or "")[:40],
             "detail": str(detail or "")[:120]}
    old = (ver.get("checks") or {}).get(name) or {}
    if {k: old.get(k) for k in entry} == entry:
        return False
    ver.setdefault("checks", {})[name] = {**entry, "observed_at": _now()}
    return True


def set_head(ver: dict, sha: str) -> bool:
    sha = str(sha or "")[:40]
    if not sha or ver.get("head_sha") == sha:
        return False
    ver["head_sha"] = sha
    return True


def override(ver: dict, actor: str, reason: str) -> None:
    reason = " ".join(str(reason or "").split())
    if len(reason) < OVERRIDE_MIN_CHARS:
        raise ValueError("evidence_required")
    ver["override"] = {"actor": str(actor or "owner")[:80], "reason": reason[:300], "at": _now()}


def missing(ticket: dict) -> list[str]:
    ver = ticket.get("verification") or {}
    head = str(ver.get("head_sha") or "")
    checks = ver.get("checks") or {}
    out = []
    for name in ver.get("required_checks") or []:
        c = checks.get(name) or {}
        if c.get("result") != "pass":
            out.append(name)
        elif head and c.get("sha") != head:
            out.append(name + " (старый коммит)")
    return out


LABELS = {"pr_merged": "PR смержен", "ci_passed": "CI зелёный", "delivered_qc": "доставлено после QC",
          "message_sent": "сообщение отправлено"}


def summary_line(ticket: dict) -> str:
    """One line for the Telegram card; empty for legacy tickets."""
    ver = ticket.get("verification")
    if not ver:
        return ""
    lvl, need = level(ticket), str(ver.get("required_level") or "")
    if ver.get("override"):
        return f"🔎 Закрыто владельцем без доказательств: {ver['override']['reason']}"
    head = "✅" if RANK[lvl] >= RANK.get(need, 2) else "⏳"
    parts = []
    for name in ver.get("required_checks") or []:
        c = (ver.get("checks") or {}).get(name) or {}
        stale = c and ver.get("head_sha") and c.get("sha") != ver.get("head_sha")
        mark = "✅" if c.get("result") == "pass" and not stale else ("❌" if c.get("result") == "fail" and not stale else "·")
        parts.append(f"{mark} {LABELS.get(name, name)}")
    return f"🔎 Доказательства: {head} {lvl} (нужно {need})" + (" · " + " · ".join(parts) if parts else "")


# ---- pure checkers: they read results that already exist and never start anything ----

def check_mycast(history_entries: list, item_id: str) -> dict:
    """The delivery history records "sent" only after the audio passed QC and Telegram accepted it."""
    rows = [r for r in history_entries or [] if isinstance(r, dict) and r.get("id") == item_id]
    ok = any(r.get("status") == "sent" for r in rows)
    return {"name": "delivered_qc", "result": "pass" if ok else "fail", "source": "delivery_log",
            "detail": "" if ok else (str(rows[-1].get("status") or "")[:60] if rows else "not_in_log")}


def check_telegram(api_reply: Any) -> dict:
    """Sent = the Bot API answered ok with a message id. It does not prove the owner read it."""
    result = api_reply.get("result") if isinstance(api_reply, dict) else None
    ok = bool(isinstance(api_reply, dict) and api_reply.get("ok") and isinstance(result, dict) and result.get("message_id"))
    return {"name": "message_sent", "result": "pass" if ok else "fail", "source": "telegram_api",
            "detail": "" if ok else "no_message_id"}
