"""T-743 (#452 B-01): first-party visit and variant counter for MyCast pages.

Why: the growth funnel (exposure → visit → registration → first episode → payment) could not show visits or which
landing variant and channel a person came from (docs/architecture/internal-growth-manager-rfc.md §8). Without that,
the funnel cannot be honest.

What is stored, per page view, one JSON line in DATA_DIR/mycast_visits.jsonl:
  {ts, day, page, variant, channel, visitor, synthetic}
- `visitor` is HMAC-SHA256(salt of the UTC day, ip | user agent), cut to 16 hex. Each day gets a new random salt and the
  old one is deleted, so a visitor cannot be linked across days, even by us. The IP and user agent are never written.
- `channel` comes from `?ch=` on the link a post carries. Without it, only the referring site's category is kept
  (Telegram, LinkedIn, search, …). The referring host itself is dropped.
- No cookie, no browser storage, no third-party script. The page script skips the count under Do Not Track or Global
  Privacy Control, and drops bots by user agent. `?synthetic=1` (QA runs) is stored with synthetic=true and never counted.
- Rows older than RETENTION_DAYS are folded into per-day totals; their visitor hashes are dropped.

Off by default: FACTORY_MYCAST_VISITS_ENABLED=1 turns the public endpoint on (owner decision, after the privacy text).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import Response

SCHEMA = "mycast-visits/1"
PAGES = ("landing", "profile", "episode")
TOKEN_RE = re.compile(r"^[a-z0-9_-]{1,16}$")
HOST_RE = re.compile(r"^[a-z0-9.-]{1,253}$")
RETENTION_DAYS = 120
MAX_REPORT_DAYS = 90
MAX_PER_VISITOR_HOUR = 30
MAX_BODY = 512
BOT_RE = re.compile(r"bot|crawl|spider|slurp|preview|facebookexternalhit|embedly|whatsapp|discord|slack|skype|curl|"
                    r"wget|python|httpclient|okhttp|go-http|java/|headless|lighthouse|pingdom|uptime|monitor|scan", re.I)
# Referring site → channel category. The host is matched, then dropped; only the category is stored.
CHANNEL_HOSTS = (("t.me", "tg"), ("telegram", "tg"), ("linkedin", "li"), ("lnkd.in", "li"), ("google.", "search"),
                 ("bing.", "search"), ("duckduckgo", "search"), ("yandex", "search"), ("ecosia", "search"),
                 ("facebook", "fb"), ("fb.", "fb"), ("instagram", "ig"), ("tiktok", "tt"), ("youtube", "yt"),
                 ("youtu.be", "yt"), ("x.com", "x"), ("twitter", "x"), ("t.co", "x"), ("reddit", "reddit"),
                 ("chatgpt", "ai"), ("perplexity", "ai"), ("claude.ai", "ai"), ("gemini", "ai"))


def enabled() -> bool:
    return os.environ.get("FACTORY_MYCAST_VISITS_ENABLED", "").strip() == "1"


def _token(value) -> str:
    value = str(value or "").strip().lower()
    return value if TOKEN_RE.fullmatch(value) else ""


def channel_for(explicit, referrer_host) -> str:
    """`?ch=` wins; else the category of the referring site; else direct (no referrer) or other."""
    ch = _token(explicit)
    if ch:
        return ch
    host = str(referrer_host or "").strip().lower()
    if not host or not HOST_RE.fullmatch(host):
        return "direct"
    for needle, category in CHANNEL_HOSTS:
        if host == needle or needle in host:
            return category
    return "other"


def clean_acq(value) -> Optional[dict]:
    """The {variant, channel} a sign-up arrived with, validated; None when there is nothing usable."""
    if not isinstance(value, dict):
        return None
    out = {"variant": _token(value.get("variant")), "channel": _token(value.get("channel"))}
    return out if (out["variant"] or out["channel"]) else None


class VisitLog:
    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.salt_path = self.path.with_name(self.path.stem + ".salt.json")
        self.daily_path = self.path.with_name(self.path.stem + ".daily.json")
        self.clock = clock
        self._lock = threading.Lock()
        self._hits: dict = {}
        self._compacted = ""
        self._salt_cache: tuple = ("", b"")

    @staticmethod
    def day_of(ts: float) -> str:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()

    # --- salt: one random value per UTC day; yesterday's is deleted, so hashes cannot be re-linked ---------------------
    def _salt(self, day: str) -> bytes:
        if self._salt_cache[0] == day:
            return self._salt_cache[1]
        try:
            data = json.loads(self.salt_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict) or not isinstance(data.get(day), str):
            data = {day: secrets.token_hex(32)}
            self._write(self.salt_path, json.dumps(data))
        elif len(data) > 1:
            data = {day: data[day]}
            self._write(self.salt_path, json.dumps(data))
        self._salt_cache = (day, bytes.fromhex(data[day]))
        return self._salt_cache[1]

    def visitor(self, ip: str, ua: str, day: str) -> str:
        return hmac.new(self._salt(day), f"{ip}|{ua}".encode("utf-8", "replace"), hashlib.sha256).hexdigest()[:16]

    @staticmethod
    def _write(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)

    # --- write -------------------------------------------------------------------------------------------------------
    def record(self, *, page, variant="", channel="", referrer_host="", ip="", ua="", synthetic=False,
               now: Optional[float] = None) -> str:
        """Returns recorded | invalid | bot | limited. Nothing about the person is kept beyond the daily hash."""
        now = self.clock() if now is None else now
        page = str(page or "").strip().lower()
        if page not in PAGES:
            return "invalid"
        if not ua or BOT_RE.search(ua):
            return "bot"
        day = self.day_of(now)
        with self._lock:
            who = self.visitor(str(ip), str(ua), day)
            hits = [t for t in self._hits.get(who, []) if now - t < 3600]
            if len(hits) >= MAX_PER_VISITOR_HOUR:
                self._hits[who] = hits
                return "limited"
            self._hits[who] = hits + [now]
            if len(self._hits) > 50_000:              # bound memory: forget visitors with no hit in the last hour
                self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < 3600}
            row = {"ts": int(now), "day": day, "page": page, "variant": _token(variant),
                   "channel": channel_for(channel, referrer_host), "visitor": who, "synthetic": bool(synthetic)}
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
            if self._compacted != day:
                self._compact(now)
                self._compacted = day
        return "recorded"

    def _rows(self) -> list:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict) and isinstance(row.get("day"), str):
                rows.append(row)
        return rows

    def _compact(self, now: float) -> None:
        """Fold rows older than RETENTION_DAYS into per-day totals and drop their visitor hashes. Caller holds the lock."""
        cutoff = self.day_of(now - RETENTION_DAYS * 86400)
        rows = self._rows()
        old = [r for r in rows if r["day"] < cutoff]
        if not old:
            return
        try:
            daily = json.loads(self.daily_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            daily = {}
        for r in old:
            if r.get("synthetic"):
                continue
            key = "|".join((r.get("page", ""), r.get("variant", ""), r.get("channel", "")))
            daily.setdefault(r["day"], {})[key] = daily.get(r["day"], {}).get(key, 0) + 1
        self._write(self.daily_path, json.dumps(daily, sort_keys=True))
        keep = [r for r in rows if r["day"] >= cutoff]
        self._write(self.path, "".join(json.dumps(r, separators=(",", ":")) + "\n" for r in keep))

    # --- read --------------------------------------------------------------------------------------------------------
    def report(self, days: int = 30, *, registrations: Iterable[dict] = (), now: Optional[float] = None) -> dict:
        """Counts for the last `days` UTC days (1..90). `daily_visitors` sums distinct visitors per day: one person on
        three days counts three times, and two people on one phone count once. It is not «unique people»."""
        now = self.clock() if now is None else now
        days = max(1, min(int(days), MAX_REPORT_DAYS))
        since = self.day_of(now - (days - 1) * 86400)
        visits = 0
        excluded = 0
        seen = set()
        by = {"page": {}, "variant": {}, "channel": {}}
        by_day: dict = {}
        with self._lock:
            rows = self._rows()
        for r in rows:
            if r["day"] < since:
                continue
            if r.get("synthetic"):
                excluded += 1
                continue
            visits += 1
            first = (r["day"], r.get("visitor")) not in seen
            seen.add((r["day"], r.get("visitor")))
            d = by_day.setdefault(r["day"], {"visits": 0, "daily_visitors": 0})
            d["visits"] += 1
            d["daily_visitors"] += int(first)
            for field in by:
                key = r.get(field) or "none"
                by[field][key] = by[field].get(key, 0) + 1
        regs = {"total": 0, "by_variant": {}, "by_channel": {}}
        since_ts = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc).timestamp()
        for rec in registrations:
            created = rec.get("created") if isinstance(rec, dict) else None
            if not isinstance(created, (int, float)) or created < since_ts or created > now:
                continue
            acq = clean_acq(rec.get("acq")) or {"variant": "", "channel": ""}
            regs["total"] += 1
            for field, key in (("by_variant", acq["variant"] or "unknown"), ("by_channel", acq["channel"] or "unknown")):
                regs[field][key] = regs[field].get(key, 0) + 1
        return {"schema": SCHEMA, "since": since, "until": self.day_of(now), "days": days,
                "visits": {"total": visits, "daily_visitors": len(seen), "by_page": by["page"],
                           "by_variant": by["variant"], "by_channel": by["channel"],
                           "by_day": dict(sorted(by_day.items()))},
                "synthetic_excluded": excluded,
                "registrations": regs,
                "not_counted": ["Do Not Track / Global Privacy Control", "bots", "synthetic test visits",
                                "more than %d views per visitor per hour" % MAX_PER_VISITOR_HOUR]}


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()[:64]
    return (request.client.host if request.client else "")[:64]


def install_mycast_visit_routes(app, log: VisitLog, *, identity: Callable[[Request], dict],
                                registrations: Callable[[], list], is_enabled: Callable[[], bool] = enabled) -> None:
    @app.post("/api/mycast/v", include_in_schema=False)
    async def mycast_visit(request: Request):
        """Public page-view beacon (navigator.sendBeacon sends text/plain). 404 while the owner flag is off."""
        if not is_enabled():
            return Response(status_code=404)
        raw = await request.body()
        if len(raw) > MAX_BODY:
            return Response(status_code=413)
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return Response(status_code=400)
        if not isinstance(body, dict):
            return Response(status_code=400)
        status = log.record(page=body.get("p"), variant=body.get("v"), channel=body.get("ch"),
                            referrer_host=body.get("r"), ip=_client_ip(request),
                            ua=request.headers.get("user-agent", "")[:400], synthetic=bool(body.get("s")))
        if status == "invalid":
            return Response(status_code=400)
        return Response(status_code=204, headers={"Cache-Control": "no-store"})   # bot/limited look the same as counted

    @app.get("/api/factory/mycast/visits")
    def mycast_visits_report(request: Request, days: int = 30):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")
        return {"enabled": is_enabled(), **log.report(days, registrations=registrations())}
