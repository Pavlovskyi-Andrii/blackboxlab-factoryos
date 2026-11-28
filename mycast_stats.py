"""T-746 (#452, owner 2026-11-27): who of the registered MyCast listeners actually listens, and who drops off.

The owner wants to see this before any payment (Telegram Stars) is switched on: «если они на бесплатной версии
спрыгивают через три дня и отписываются — это одно; если они долго слушают бесплатно — тогда можно подключать звёзды».

What the numbers can and cannot say:
- An episode «delivered» means the Telegram Bot API accepted the audio for the listener's own chat. Telegram does not
  tell a bot whether the audio was played, so a delivered episode is not proof of listening.
- «Site plays» are real play starts: the listener opened an own episode in «My podcasts», or someone opened a shared
  episode or profile player. Each counts once per fetch; the browser caches the file for an hour.
- «Stopped» separates the listener switching delivery off (`listener_stopped`) from other pauses (a changed podcast,
  a changed Telegram account) and from deliveries that keep failing.
- A deleted account leaves no row. Only anonymous counters remain (how many, after how many days, with or without an
  episode), kept in the account store under `stats` without any id.

Everything here is a pure function of the account store, so it can be tested without a server.
"""
from __future__ import annotations

import calendar
import re
import time
from typing import Callable, Iterable, Optional

from fastapi import HTTPException, Request

SCHEMA = "mycast-listening/1"
SEGMENTS = ("never_started", "dropped_early", "stopped_later", "listening_new", "listening_long")
EARLY_DAYS = 3        # «спрыгивают через три дня»
LONG_DAYS = 7         # a week of daily episodes = listening long enough to ask for money
DELETE_BUCKETS = ("0-2", "3-6", "7-13", "14+")
# Telegram answers 403 Forbidden when the listener blocked the bot: that is leaving, not our failure.
BLOCKED_RE = re.compile(r"forbidden|blocked|403", re.I)


def _day_ts(day: str) -> Optional[int]:
    try:
        return calendar.timegm(time.strptime(day, "%Y-%m-%d"))
    except (TypeError, ValueError):
        return None


def delete_bucket(days: float) -> str:
    return "0-2" if days < 3 else "3-6" if days < 7 else "7-13" if days < 14 else "14+"


def listener_row(rec: dict, now: float) -> dict:
    """One listener as the owner sees it: first name and slug, no chat id, email or podcast code."""
    from mycast_library import episodes
    eps = episodes(rec)
    days = sorted(d for d, e in eps.items() if e.get("file_id") or int(e.get("seconds") or 0) > 0)
    seconds = sum(int(eps[d].get("seconds") or 0) for d in days)
    first, last = (days[0], days[-1]) if days else ("", "")
    delivery = rec.get("delivery") or {}
    log = rec.get("deliveries") or {}
    recent_failures = [d for d in sorted(log)[-3:] if (log[d] or {}).get("status") == "failed"]
    plays = rec.get("plays") or {}
    if not rec.get("code"):
        setup = "no_podcast"
    elif not rec.get("chat_id"):
        setup = "telegram_not_linked"
    elif rec.get("approved_code") != rec.get("code"):
        setup = "not_approved"
    elif delivery.get("active"):
        last_reason = str((log.get(recent_failures[-1]) or {}).get("reason") or "") if recent_failures else ""
        setup = ("receiving" if len(recent_failures) < 2 else
                 "blocked_bot" if BLOCKED_RE.search(last_reason) else "delivery_failing")
    elif delivery.get("paused_reason") == "listener_stopped":
        setup = "stopped_by_listener"
    elif delivery.get("paused_reason"):
        setup = "paused"
    else:
        setup = "delivery_off"
    created = int(rec.get("created") or 0)
    first_ts, last_ts = _day_ts(first), _day_ts(last)
    span_days = (last_ts - first_ts) // 86400 + 1 if first_ts is not None and last_ts is not None else 0
    since_first = int((now - first_ts) // 86400) if first_ts is not None else None
    # A delivery that fails for our own reasons is not the listener leaving, so it does not count as stopped.
    stopped = setup in ("stopped_by_listener", "blocked_bot", "paused", "delivery_off")
    if not days:
        segment = "never_started"
    elif stopped and span_days <= EARLY_DAYS:
        segment = "dropped_early"
    elif stopped:
        segment = "stopped_later"
    elif since_first is not None and since_first >= LONG_DAYS:
        segment = "listening_long"
    else:
        segment = "listening_new"
    acq = rec.get("acq") if isinstance(rec.get("acq"), dict) else {}
    return {"slug": str(rec.get("slug") or ""), "first_name": str(rec.get("name") or "").split(" ")[0][:40],
            "provider": str(rec.get("provider") or ""), "signed_up": time.strftime("%Y-%m-%d", time.gmtime(created)) if created else "",
            "days_since_signup": int((now - created) // 86400) if created else None,
            "channel": str(acq.get("channel") or ""), "variant": str(acq.get("variant") or ""),
            "setup": setup, "segment": segment,
            "episodes": len(days), "minutes": round(seconds / 60, 1),
            "first_episode": first, "last_episode": last, "listening_span_days": span_days,
            "episodes_last_7_days": sum(1 for d in days if (_day_ts(d) or 0) >= now - 7 * 86400),
            "site_plays": int(plays.get("own") or 0), "shared_plays": int(plays.get("shared") or 0),
            "last_site_play": time.strftime("%Y-%m-%d", time.gmtime(int(plays["last_own_at"]))) if plays.get("last_own_at") else "",
            "invited": int(rec.get("invited", rec.get("referrals", 0)) or 0),
            "last_failure": str((log.get(recent_failures[-1]) or {}).get("reason") or "")[:80] if recent_failures else ""}


def _retention(rows: list, day: int, now: float) -> dict:
    """Of the listeners whose first episode is at least `day` days old: how many still got an episode on or after
    that day. Denominator and numerator are both shown; there is no percentage for small groups."""
    eligible = [r for r in rows if r["first_episode"] and now - _day_ts(r["first_episode"]) >= day * 86400]
    kept = [r for r in eligible if r["listening_span_days"] > day]
    return {"day": day, "eligible": len(eligible), "still_receiving": len(kept)}


def build(listeners: Iterable[dict], stats: Optional[dict], now: float) -> dict:
    rows = [listener_row(rec, now) for rec in listeners]
    rows.sort(key=lambda r: (SEGMENTS.index(r["segment"]), -(r["episodes"]), r["slug"]))
    seg = {s: 0 for s in SEGMENTS}
    for r in rows:
        seg[r["segment"]] += 1
    funnel = [
        ("registered", len(rows)),
        ("podcast_set_up", sum(1 for r in rows if r["setup"] != "no_podcast")),
        ("telegram_linked", sum(1 for r in rows if r["setup"] not in ("no_podcast", "telegram_not_linked"))),
        ("first_episode", sum(1 for r in rows if r["episodes"] > 0)),
        ("three_days", sum(1 for r in rows if r["listening_span_days"] > EARLY_DAYS)),
        ("seven_days", sum(1 for r in rows if r["listening_span_days"] > LONG_DAYS)),
        ("played_on_site", sum(1 for r in rows if r["site_plays"] > 0)),
    ]
    deleted = (stats or {}).get("deleted") or {}
    return {"schema": SCHEMA, "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
            "total": len(rows), "segments": seg,
            "funnel": [{"step": k, "count": v} for k, v in funnel],
            "retention": [_retention(rows, d, now) for d in (EARLY_DAYS, LONG_DAYS, 14)],
            "minutes_delivered": round(sum(r["minutes"] for r in rows), 1),
            "deleted_accounts": {"total": int(deleted.get("total", 0)),
                                 "by_days_after_signup": {b: int((deleted.get("by_days") or {}).get(b, 0)) for b in DELETE_BUCKETS},
                                 "had_episode": int(deleted.get("had_episode", 0))},
            "limits": ["Telegram does not tell a bot whether an episode was played: «delivered» is not «listened».",
                       "Site plays count play starts on the MyCast site only.",
                       "Deleted accounts leave only anonymous counters."],
            "listeners": rows}


def install_mycast_stats_routes(app, *, load: Callable[[], dict], identity: Callable[[Request], dict],
                                clock: Callable[[], float] = time.time) -> None:
    @app.get("/api/factory/mycast/stats")
    def mycast_listening_stats(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")
        data = load()
        return build(data.get("listeners", {}).values(), data.get("stats"), clock())
