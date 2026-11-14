"""#317: daily MyCast for website listeners (owner report: configured 2026-11-11, nothing arrived 11-13 Nov).

Root cause: "delivery on" was only stored. Nothing ever read it, so no episode was made or sent. This module adds:

* `decode_profile(code)`: the listener's saved share code (configurator.js encodeShare) to plain settings;
* `delivery_gate(rec, now)`: the ordered gates, with one honest state for the cabinet
  (telegram_not_linked < not_approved < delivery_off < bad_profile < not_today < waiting < delivered < due);
* worker routes for the EC2 runner: list the listeners whose episode is due now, then hand in one script per
  listener and date. The server re-checks every gate, claims (listener, local date) once, voices it with the
  listener's own Gemini voices and sends it to the listener's own chat. Daily global cap; nothing else is sent.

No audio goes to anyone who did not approve the podcast and turn delivery on themselves.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException, Request

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None

_SPEC = json.loads((Path(__file__).parent / "static/mycast-configurator/topics.json").read_text(encoding="utf-8"))
TOPICS = _SPEC["topics"]                     # [id, uk, ru, en] in configurator.js TOPIC_IDS order
GROUPS = _SPEC["groups"]
VOICE_NAMES = {v[0] for v in _SPEC["gemini_voices"]}
LANG_COL = {"uk": 1, "ru": 2, "en": 3}
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
DURATIONS = tuple(range(1, 31))                 # configurator.js: any whole minute 1..30
DAILY_CAP = 10                               # listener episodes per UTC day across all listeners (Gemini budget)
MAX_FAILED_PER_DAY = 3
MAX_SCRIPT_CHARS = 40000                     # ~30 min at 140 words/min
SLUG_RE = re.compile(r"^[a-z0-9]{8}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def decode_profile(code: str) -> dict:
    """Mirror of configurator.js decodeShare for what the episode needs; ValueError when unusable."""
    raw = str(code or "")[:8000]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    except Exception:
        raise ValueError("bad share code")
    if not isinstance(data, dict) or data.get("v") != _SPEC["share_version"] or data.get("n") != len(TOPICS):
        raise ValueError("bad share code")
    o = data.get("o") if isinstance(data.get("o"), list) else []
    lang = o[1] if len(o) > 1 and o[1] in LANG_COL else "uk"
    mode = o[0] if o and o[0] in ("narrator", "two_hosts") else "two_hosts"
    voices = [v for v in (o[2] if len(o) > 2 and isinstance(o[2], list) else []) if v in VOICE_NAMES]
    voices = (voices or _SPEC["default_voices"][mode])[: 1 if mode == "narrator" else 2]
    if mode == "two_hosts" and len(voices) < 2:
        voices = list(_SPEC["default_voices"]["two_hosts"])
    topics = []
    for row in data.get("t") if isinstance(data.get("t"), list) else []:
        if isinstance(row, list) and row and isinstance(row[0], int) and 0 <= row[0] < len(TOPICS):
            label = TOPICS[row[0]][LANG_COL[lang]]
            scope = {"u": "Україна" if lang == "uk" else "Ukraine", "w": "world"}.get(row[1] if len(row) > 1 else "", "")
            if len(row) > 2 and row[1] == "c":
                scope = str(row[2])[:60]
            topics.append(label + (f" ({scope})" if scope else ""))
    custom = []
    for group, items in (data.get("c") or {}).items() if isinstance(data.get("c"), dict) else []:
        if group in GROUPS and isinstance(items, list):
            custom += [f"{GROUPS[group][LANG_COL[lang] - 1]}: {str(i)[:40]}" for i in items[:5] if str(i).strip()]
    follows = [f"{f[0]} {str(f[1])[:120]}" for f in (data.get("f") or [])[:20] if isinstance(f, list) and len(f) == 2]
    s = data.get("s") if isinstance(data.get("s"), list) else []
    tz = s[0] if s and isinstance(s[0], str) else "Europe/Kyiv"
    try:
        ZoneInfo(tz)
    except Exception:
        tz = "Europe/Kyiv"
    at = s[1] if len(s) > 1 and isinstance(s[1], str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s[1]) else "07:30"
    freq = s[2] if len(s) > 2 and s[2] in ("daily", "weekdays", "days") else "daily"
    days = [d for d in (s[3] if len(s) > 3 and isinstance(s[3], list) else []) if d in WEEKDAYS]
    duration = s[4] if len(s) > 4 and s[4] in DURATIONS else 10
    if not topics and not custom and not follows:
        raise ValueError("no topics")
    k = data.get("k") if isinstance(data.get("k"), list) else []
    calendar = {"birthdays": bool(k[0]) if k else False, "events": bool(k[1]) if len(k) > 1 else False}
    return {"topics": topics, "custom": custom, "follows": follows, "free_text": str(data.get("x") or "")[:120],
            "timezone": tz, "time": at, "frequency": freq, "days": days, "duration_min": duration,
            "language": lang, "mode": mode, "voices": voices, "calendar": calendar}


def _local(profile: dict, now: float) -> datetime:
    return datetime.fromtimestamp(now, ZoneInfo(profile["timezone"]))


def scheduled_on(profile: dict, local: datetime) -> bool:
    day = WEEKDAYS[local.weekday()]
    if profile["frequency"] == "weekdays":
        return day not in ("sat", "sun")
    if profile["frequency"] == "days":
        return day in profile["days"]
    return True


def delivery_gate(rec: dict, now: float) -> dict:
    """{state, detail, local_date}; state 'due' is the only one that may produce audio."""
    d = rec.get("delivery") or {}
    if not rec.get("code"):
        return {"state": "no_podcast", "detail": "", "local_date": ""}
    if not rec.get("chat_id"):
        return {"state": "telegram_not_linked", "detail": "", "local_date": ""}
    if rec.get("approved_code") != rec.get("code"):
        return {"state": "not_approved", "detail": "", "local_date": ""}
    if not d.get("active"):
        return {"state": "delivery_off", "detail": d.get("paused_reason", ""), "local_date": ""}
    try:
        profile = decode_profile(rec["code"])
    except ValueError as exc:
        return {"state": "bad_profile", "detail": str(exc), "local_date": ""}
    local = _local(profile, now)
    day = local.date().isoformat()
    log = (rec.get("deliveries") or {}).get(day) or {}
    if log.get("status") == "sent":
        return {"state": "delivered", "detail": log.get("at", ""), "local_date": day}
    if not scheduled_on(profile, local):
        return {"state": "not_today", "detail": profile["frequency"], "local_date": day}
    if local.strftime("%H:%M") < profile["time"]:
        return {"state": "waiting", "detail": profile["time"] + " " + profile["timezone"], "local_date": day}
    if int(log.get("failures", 0)) >= MAX_FAILED_PER_DAY:
        return {"state": "failed_today", "detail": log.get("reason", ""), "local_date": day}
    if log.get("status") == "claimed" and now - float(log.get("claimed_ts", 0)) < 1800:
        return {"state": "in_progress", "detail": "", "local_date": day}
    return {"state": "due", "detail": "", "local_date": day, "profile": profile}


class ListenerDelivery:
    """Delivery bookkeeping inside the listener record (same file and lock as ListenerStore)."""

    def __init__(self, store, *, clock: Callable[[], float] = time.time, daily_cap: int = DAILY_CAP,
                 calendar: Optional[Callable[[dict, dict, str], dict]] = None):
        self.store, self.clock, self.daily_cap = store, clock, daily_cap
        self.calendar = calendar           # mycast_calendar.ListenerCalendar.today; {} = nothing to add

    def due(self) -> list[dict]:
        now = self.clock()
        with self.store._lock:
            listeners = list(self.store._load()["listeners"].values())
        out = []
        for rec in listeners:
            gate = delivery_gate(rec, now)
            if gate["state"] == "due":
                item = {"slug": rec["slug"], "first_name": str(rec.get("name") or "").split(" ")[0][:40],
                        "local_date": gate["local_date"], "profile": gate["profile"]}
                if self.calendar is not None and rec.get("gcal"):
                    try:
                        cal = self.calendar(rec, gate["profile"], gate["local_date"])
                    except Exception:
                        cal = {}            # a calendar problem never costs the listener their episode
                    if cal:
                        item["calendar"] = cal
                out.append(item)
        return out

    def overview(self, offset: int = 0, limit: int = 200) -> dict:
        """Owner dashboard view: delivery state per listener. First name and slug only — no email, chat id or code."""
        now = self.clock()
        with self.store._lock:
            data = self.store._load()
            listeners = list(data["listeners"].values())
            sent_today = self._sent_today_utc(data)
        rows = []
        for rec in listeners:
            gate = delivery_gate(rec, now)
            log = rec.get("deliveries") or {}
            last_day = max(log, default="")
            last = log.get(last_day) or {}
            rows.append({"slug": rec.get("slug", ""), "first_name": str(rec.get("name") or "").split(" ")[0][:40],
                         "state": gate["state"], "detail": str(gate.get("detail") or "")[:80],
                         "last_date": last_day, "last_status": str(last.get("status") or ""),
                         "last_reason": str(last.get("reason") or "")[:80],
                         "sent_days": sum(1 for e in log.values() if e.get("status") == "sent")})
        rows.sort(key=lambda r: (r["state"] != "failed_today", r["state"] != "due", r["slug"]))
        counts = {}
        for r in rows:
            counts[r["state"]] = counts.get(r["state"], 0) + 1
        offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        page = rows[offset:offset + limit]
        return {"total": len(rows), "by_state": counts, "sent_today_utc": sent_today, "daily_cap": self.daily_cap,
                "offset": offset, "limit": limit, "next_offset": offset + len(page) if offset + len(page) < len(rows) else None,
                "listeners": page}

    def _sent_today_utc(self, data: dict) -> int:
        day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        return sum(1 for r in data["listeners"].values() for e in (r.get("deliveries") or {}).values()
                   if e.get("status") == "sent" and str(e.get("utc_day")) == day)

    def claim(self, slug: str, local_date: str) -> dict:
        """Re-check the gates under the lock and mark (slug, local_date) claimed. Raises HTTPException."""
        now = self.clock()
        with self.store._lock:
            data = self.store._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise HTTPException(404, "unknown listener")
            gate = delivery_gate(rec, now)
            if gate["state"] == "delivered":
                return {"duplicate": True}
            if gate["state"] != "due" or gate["local_date"] != local_date:
                raise HTTPException(409, "not due: " + gate["state"])
            if self._sent_today_utc(data) >= self.daily_cap:
                raise HTTPException(429, "listener daily cap reached")
            log = rec.setdefault("deliveries", {})
            entry = log.get(local_date) or {}
            log[local_date] = {**entry, "status": "claimed", "claimed_ts": now}
            rec["deliveries"] = dict(sorted(log.items())[-14:])
            self.store._save(data)
            return {"duplicate": False, "chat_id": rec["chat_id"], "profile": gate["profile"]}

    def finish(self, slug: str, local_date: str, ok: bool, reason: str = "", seconds: int = 0, file_id: str = "",
               title: str = "") -> None:
        now = self.clock()
        with self.store._lock:
            data = self.store._load()
            rec = data["listeners"].get(slug)
            if not rec:
                return
            entry = (rec.get("deliveries") or {}).get(local_date) or {}
            if ok:
                entry = {"status": "sent", "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
                         "utc_day": time.strftime("%Y-%m-%d", time.gmtime(now)), "seconds": seconds,
                         # Only Telegram's file id is kept: the audio itself stays on Telegram, never on our disk.
                         "file_id": str(file_id or "")[:200], "title": str(title or "")[:64]}
                action = "episode_sent"
                from mycast_accounts import ListenerStore
                ListenerStore.credit_referral(data, rec, int(now))
            else:
                entry = {**entry, "status": "failed", "failures": int(entry.get("failures", 0)) + 1, "reason": reason[:80]}
                action = "episode_failed"
            rec.setdefault("deliveries", {})[local_date] = entry
            rec["audit"] = (rec.get("audit") or [])[-49:] + [{"at": int(now), "action": action, "detail": (reason or local_date)[:120]}]
            self.store._save(data)


def install_listener_delivery_routes(app, delivery: ListenerDelivery, *, authorize_worker: Callable[[Request], bool],
                                     api_key: Callable[[], str], tts: Callable, encode: Callable,
                                     send_audio: Callable[[str, bytes, str, str, str], None],
                                     check_pcm: Optional[Callable] = None,
                                     identity: Optional[Callable] = None) -> None:
    if identity is not None:
        @app.get("/api/factory/mycast/listeners")
        def mycast_listeners_overview(request: Request, offset: int = 0, limit: int = 200):
            if (identity(request) or {}).get("role") != "owner":
                raise HTTPException(403, "Owner access required")
            return delivery.overview(offset, limit)

    @app.get("/api/factory/mycast/worker/listeners/due")
    def mycast_listeners_due(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        return {"listeners": delivery.due()}

    @app.post("/api/factory/mycast/worker/listeners/{slug}/deliver")
    async def mycast_listener_deliver(slug: str, request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if not SLUG_RE.fullmatch(slug):
            raise HTTPException(404, "unknown listener")
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "json body required")
        episode = body.get("episode") if isinstance(body, dict) else None
        local_date = str((body or {}).get("local_date") or "")
        lines = episode.get("lines") if isinstance(episode, dict) else None
        if not (DATE_RE.fullmatch(local_date) and isinstance(lines, list) and 4 <= len(lines) <= 300
                and all(isinstance(l, list) and len(l) == 2 and l[0] in ("A", "B") and isinstance(l[1], str) and l[1].strip()
                        for l in lines) and sum(len(l[1]) for l in lines) <= MAX_SCRIPT_CHARS):
            raise HTTPException(400, "bad episode")
        key = api_key()
        if not key:
            raise HTTPException(409, "gemini key not configured")
        claim = delivery.claim(slug, local_date)
        if claim["duplicate"]:
            return {"sent": False, "duplicate": True}
        profile = claim["profile"]
        if profile["mode"] == "narrator":
            lines = [["A", t] for _, t in lines]
        voices = tuple(profile["voices"]) if len(profile["voices"]) == 2 else (profile["voices"][0],) * 2
        title = str(episode.get("title") or f"MyCast · {local_date}")[:64]
        ep = {"id": f"listener-{slug}-{local_date}", "lines": lines, "language": profile["language"], "title": title}

        def produce():
            pcm, rate = tts(key, ep, voices=voices)
            if check_pcm:
                check_pcm(pcm, rate, lines)
            audio = encode(pcm, rate)
            minutes = max(1, round(len(pcm) / 2 / rate / 60))
            file_id = send_audio(claim["chat_id"], audio, f"mycast-{local_date}.mp3", title,
                                 f"🎧 {title} · ~{minutes} хв\nВаш MyCast. Зупинити розсилку можна на сторінці MyCast.")
            return round(len(pcm) / 2 / rate), len(audio), file_id

        try:
            seconds, size, file_id = await asyncio.to_thread(produce)
        except Exception as exc:
            reason = type(exc).__name__ + (":" + str(getattr(exc, "category", "") or getattr(exc, "reason", "")))
            delivery.finish(slug, local_date, False, reason)
            raise HTTPException(502, "listener delivery failed: " + reason[:60])
        delivery.finish(slug, local_date, True, seconds=seconds, file_id=file_id if isinstance(file_id, str) else "",
                        title=title)
        return {"sent": True, "duplicate": False, "seconds": seconds, "bytes": size}
