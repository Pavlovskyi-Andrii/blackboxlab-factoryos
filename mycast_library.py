"""MyCast MVP V1 (#305, T-620): the listener's podcast library, per-episode public links, the referral ledger and the
free-access period.

Everything lives inside the listener store (one JSON file, one writer, one lock — see mycast_accounts.ListenerStore);
the helpers here are called with that lock held and never save on their own.

Library. Every episode that really reached the listener (Telegram returned a file id) is kept in rec["library"], newest
LIBRARY_MAX, so history survives the 14-day delivery log. Only Telegram's file id is stored, never the audio.

Public links. Each episode is private. The author can publish one episode: that creates a random, unguessable token and
the page /mycast/e/<token> (player + safe metadata only: title, date, length, first name). Unpublishing deletes the
token at once, so the old link stops working; publishing again makes a new link. Nothing is posted anywhere and nobody
is notified: sharing is the author's own copy/share action. The pages are noindex and not in the sitemap.

Referrals (#305 rule, owner decision 2026-11-10): the inviter AND the invited friend get +FRIEND_DAYS each, once, when
the friend's first real episode is delivered (verified sign-up + Telegram chat + a sent episode). Self-referrals (same
identity or same Telegram chat as the inviter), a friend credited before (also after deleting and re-creating the
account), and inviters over the cap get nothing. Every decision is an entry of an append-only ledger with an
idempotency id; only one-way hashes identify the friend there. FACTORY_MYCAST_FRIEND_BONUS=signup restores the
2026-11-07 rule (the friend's +7 at sign-up) without a code change.

Promotion switch. FACTORY_MYCAST_REFERRALS=1 shows the invite offer on the page. It is OFF by default: #305 requires
the promotion to stay hidden until the owner signs off the terms (ROADMAP T-620-H). Invites are still recorded, so the
ledger is complete when it is switched on.

Access period. Free days start counting at the listener's first delivered episode ("days start counting when regular
episodes launch"). FACTORY_MYCAST_ENFORCE_TRIAL=1 stops deliveries after the period ends; OFF by default during the
open beta (owner decision).
"""
from __future__ import annotations

import calendar
import hashlib
import os
import re
import secrets
import time
from typing import Optional

FREE_DAYS, FRIEND_DAYS, MAX_REFERRALS = 7, 7, 50
LIBRARY_MAX = 200
LEDGER_MAX = 5000
MAX_EVENTS = 20
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16}$")
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def referrals_enabled() -> bool:
    return os.environ.get("FACTORY_MYCAST_REFERRALS", "0").strip() == "1"


def friend_bonus_at() -> str:
    value = os.environ.get("FACTORY_MYCAST_FRIEND_BONUS", "activation").strip()
    return value if value in ("activation", "signup") else "activation"


def trial_enforced() -> bool:
    return os.environ.get("FACTORY_MYCAST_ENFORCE_TRIAL", "0").strip() == "1"


# ---------------------------------------------------------------- library

def episodes(rec: dict) -> dict:
    """day -> episode for every delivered episode: the library, plus older sent entries of the delivery log."""
    out = {}
    for day, e in (rec.get("deliveries") or {}).items():
        if e.get("status") == "sent":
            out[day] = {"title": e.get("title") or "", "seconds": int(e.get("seconds") or 0),
                        "file_id": e.get("file_id") or "", "created": e.get("at") or ""}
    for day, e in (rec.get("library") or {}).items():
        out[day] = {**out.get(day, {}), **e}
    return out


def library_add(data: dict, rec: dict, day: str, *, title: str, seconds: int, file_id: str, now: int) -> None:
    """Called (lock held) when an episode reached the listener. Also starts the free-access period once."""
    lib = rec.setdefault("library", {})
    old = lib.get(day) or {}
    lib[day] = {"title": str(title or "")[:64], "seconds": int(seconds or 0), "file_id": str(file_id or "")[:200],
                "created": old.get("created") or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                "public_token": old.get("public_token", "")}
    for gone in sorted(lib)[:-LIBRARY_MAX]:
        _drop_token(data, lib.pop(gone).get("public_token", ""))
    rec.setdefault("activated_at", int(now))


def episode_rows(rec: dict) -> list:
    """The cabinet's "My podcasts": honest states only — ready (playable), no_audio, preparing, failed."""
    rows = {}
    for day, e in episodes(rec).items():
        tok = e.get("public_token") or ""
        rows[day] = {"date": day, "title": e.get("title") or f"MyCast · {day}", "seconds": int(e.get("seconds") or 0),
                     "status": "ready" if e.get("file_id") else "no_audio", "audio": bool(e.get("file_id")),
                     "public": bool(tok), "public_url": f"/mycast/e/{tok}" if tok else None}
    for day, e in (rec.get("deliveries") or {}).items():
        if day in rows or e.get("status") not in ("claimed", "failed"):
            continue
        rows[day] = {"date": day, "title": f"MyCast · {day}", "seconds": 0,
                     "status": "preparing" if e.get("status") == "claimed" else "failed", "audio": False,
                     "public": False, "public_url": None}
    return [rows[d] for d in sorted(rows, reverse=True)]


def _drop_token(data: dict, token: str) -> None:
    if token:
        (data.get("episode_links") or {}).pop(token, None)


def set_public(data: dict, rec: dict, day: str, public: bool, now: int) -> dict:
    """Publish or unpublish one episode (lock held). Returns the episode row. Raises KeyError / LookupError."""
    ep = episodes(rec).get(day) if DAY_RE.fullmatch(day or "") else None
    if not ep:
        raise KeyError("episode_not_found")
    if public and not ep.get("file_id"):
        raise LookupError("episode_not_ready")              # no real audio: nothing to share
    lib = rec.setdefault("library", {})
    entry = lib.setdefault(day, {k: ep.get(k, "") for k in ("title", "seconds", "file_id", "created")})
    links = data.setdefault("episode_links", {})
    token = entry.get("public_token") or ""
    if public and not token:
        token = secrets.token_urlsafe(12)
        while token in links:
            token = secrets.token_urlsafe(12)
        links[token] = {"slug": rec["slug"], "day": day}
        entry["public_token"] = token
        _audit(rec, now, "episode_published", day)
    elif not public and token:
        _drop_token(data, token)
        entry["public_token"] = ""
        _audit(rec, now, "episode_unpublished", day)
    return next(r for r in episode_rows(rec) if r["date"] == day)


def find_public(data: dict, token: str) -> Optional[tuple]:
    """(rec, day, episode) for a live public token, else None. Both sides must still agree (revocation is instant)."""
    if not TOKEN_RE.fullmatch(token or ""):
        return None
    link = (data.get("episode_links") or {}).get(token)
    rec = data["listeners"].get(link.get("slug")) if isinstance(link, dict) else None
    entry = ((rec or {}).get("library") or {}).get(link.get("day")) if rec else None
    if not entry or entry.get("public_token") != token:
        return None
    return rec, link["day"], entry


def drop_listener_links(data: dict, slug: str) -> None:
    links = data.get("episode_links") or {}
    for token in [t for t, link in links.items() if isinstance(link, dict) and link.get("slug") == slug]:
        links.pop(token, None)


# ---------------------------------------------------------------- referrals

def _h(kind: str, value) -> str:
    return hashlib.sha256(f"mycast-ref|{kind}|{value}".encode()).hexdigest()[:32] if value else ""


def _audit(rec: dict, now: int, action: str, detail: str = "") -> None:
    rec["audit"] = (rec.get("audit") or [])[-49:] + [{"at": int(now), "action": action, "detail": detail[:120]}]


def _event(rec: dict, now: int, role: str, status: str, reason: str = "") -> None:
    rec["referral_events"] = (rec.get("referral_events") or [])[-(MAX_EVENTS - 1):] + [
        {"at": int(now), "role": role, "status": status, "reason": reason, "days": FRIEND_DAYS if status == "credited" else 0}]


def is_self_referral(inviter: dict, who_key: str, chat_id) -> bool:
    return bool(inviter.get("key") == who_key or (chat_id and str(inviter.get("chat_id") or "") == str(chat_id)))


def credit(data: dict, rec: dict, now: int) -> bool:
    """The friend's first delivered episode (lock held). Decides the referral exactly once and writes the ledger."""
    ref = rec.get("referred_by")
    if not ref or rec.get("referral_credited"):
        return False
    rec["referral_credited"] = int(now)               # one activation event per friend, whatever the outcome
    inviter = data["listeners"].get(ref)
    ledger = data.setdefault("referral_ledger", [])
    keys = [k for k in (_h("id", rec.get("key")), _h("chat", rec.get("chat_id"))) if k]
    seen = {k for e in ledger if e.get("status") == "credited" for k in e.get("keys", [])}
    if not inviter:
        reason = "inviter_gone"
    elif is_self_referral(inviter, rec.get("key", ""), rec.get("chat_id")):
        reason = "self_referral"
    elif seen.intersection(keys):
        reason = "duplicate_friend"
    elif int(inviter.get("referrals", 0)) >= MAX_REFERRALS:
        reason = "inviter_cap"
    else:
        reason = ""
    entry_id = f"ref:{ref}:{rec['slug']}"
    if any(e.get("id") == entry_id for e in ledger):  # idempotency fence (a retried call never credits twice)
        return False
    status = "rejected" if reason else "credited"
    ledger.append({"id": entry_id, "at": int(now), "inviter": ref, "friend": rec["slug"], "status": status,
                   "reason": reason, "days_each": FRIEND_DAYS if not reason else 0, "keys": keys})
    del ledger[:-LEDGER_MAX]
    _event(rec, now, "friend", status, reason)
    if reason:
        rec["referral_rejected"] = reason
        if inviter:
            _event(inviter, now, "inviter", status, reason)
        return False
    rec["referral_granted"] = int(now)
    inviter["referrals"] = int(inviter.get("referrals", 0)) + 1
    _event(inviter, now, "inviter", status)
    _audit(inviter, now, "friend_first_episode")
    _audit(rec, now, "referral_bonus")
    return True


# ---------------------------------------------------------------- access period

def free_days(rec: dict) -> int:
    friend_bonus = bool(rec.get("referred_by")) and not rec.get("referral_rejected") and (
        friend_bonus_at() == "signup" or bool(rec.get("referral_granted")))
    return FREE_DAYS + (FRIEND_DAYS if friend_bonus else 0) + FRIEND_DAYS * int(rec.get("referrals", 0))


def _started(rec: dict) -> Optional[int]:
    if rec.get("activated_at"):
        return int(rec["activated_at"])
    days = sorted(episodes(rec))
    if not days:
        return None
    return calendar.timegm(time.strptime(days[0], "%Y-%m-%d"))


def access(rec: dict) -> dict:
    days, start = free_days(rec), _started(rec)
    return {"free_days": days, "started_at": start, "until": start + days * 86400 if start else None,
            "enforced": trial_enforced()}


def access_ended(rec: dict, now: float) -> bool:
    if not trial_enforced():
        return False
    until = access(rec)["until"]
    return bool(until) and now >= until
