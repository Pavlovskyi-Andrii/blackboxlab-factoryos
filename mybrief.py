"""T-615 MyBrief for a profession (#188): the MVP Factory pilot `mybrief-pro`.

A visitor picks a profession and topics, sees a sample briefing whose every item links to a real source, and may leave
feedback only after ticking an explicit consent box.

Rules:
- No provider call happens on the server. Demo briefings are fixtures (`static/mybrief/demo-briefs.json`) written once
  from pages the FactoryOS Surfer actually read; `validate_catalog` refuses an item without a dated https source, a
  source dated after the fixture, or an unknown topic. Nothing here invents, refreshes or publishes content.
- Feedback is opt-in: `consent` must be literally true or nothing is stored. Stored fields are the profession, chosen
  topics, a 1–5 rating, a yes/no "would read this weekly" and an optional comment (≤ 500 chars) with e-mail addresses
  and phone-like numbers redacted. No IP, user agent, name or e-mail is stored. The client id is used only in memory,
  hashed with a per-day salt, for the per-day cap.
- The submitter gets a one-time withdraw token (only its hash is stored) to delete their own feedback.
- Public routes live under /api/mybrief/public/ and are capped; the owner/member summary is /api/mybrief/feedback.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from mycast_demo import _client_id  # same client identity as the MyCast public demo caps

PROJECT_ID = "mybrief-pro"
ISSUE = 188
PAGE = "/static/mybrief/index.html"
CATALOG_PATH = Path(__file__).resolve().parent / "static" / "mybrief" / "demo-briefs.json"
LANGS = ("en", "uk", "ru")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
URL_RE = re.compile(r"^https://[A-Za-z0-9.-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
COMMENT_MAX = 500
PER_CLIENT_DAILY = 5
GLOBAL_DAILY = 300
MAX_KEPT = 2000
MIN_PROFESSIONS = 3


class MyBriefError(Exception):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def validate_catalog(catalog: Any) -> list[str]:
    """Every problem with the fixture, as readable strings. An empty list means it may be served."""
    errors: list[str] = []
    if not isinstance(catalog, dict):
        return ["catalog is not an object"]
    generated = str(catalog.get("generated_at") or "")
    if not DATE_RE.match(generated):
        errors.append("generated_at must be YYYY-MM-DD")
    if catalog.get("kind") != "demo_fixture":
        errors.append("kind must be demo_fixture (never presented as live)")
    professions = catalog.get("professions")
    if not isinstance(professions, list) or len(professions) < MIN_PROFESSIONS:
        return errors + [f"need at least {MIN_PROFESSIONS} professions"]
    seen_prof, seen_items = set(), set()
    for prof in professions:
        pid = str((prof or {}).get("id") or "")
        if not ID_RE.match(pid) or pid in seen_prof:
            errors.append(f"bad or duplicate profession id {pid!r}")
            continue
        seen_prof.add(pid)
        for field in ("title", "audience"):
            if not all(str((prof.get(field) or {}).get(lang) or "").strip() for lang in LANGS):
                errors.append(f"{pid}: {field} needs en/uk/ru")
        topics = prof.get("topics") or []
        topic_ids = [str((t or {}).get("id") or "") for t in topics]
        if not topic_ids or len(set(topic_ids)) != len(topic_ids) or not all(ID_RE.match(t) for t in topic_ids):
            errors.append(f"{pid}: bad topics")
        for t in topics:
            if not all(str((t.get("title") or {}).get(lang) or "").strip() for lang in LANGS):
                errors.append(f"{pid}/{t.get('id')}: topic title needs en/uk/ru")
        used = set()
        for item in prof.get("items") or []:
            iid = str((item or {}).get("id") or "")
            where = f"{pid}/{iid}"
            if not ID_RE.match(iid) or iid in seen_items:
                errors.append(f"bad or duplicate item id {where}")
            seen_items.add(iid)
            if item.get("topic") not in topic_ids:
                errors.append(f"{where}: unknown topic")
            used.add(item.get("topic"))
            for field in ("headline", "summary", "why"):
                if len(str(item.get(field) or "").strip()) < 20:
                    errors.append(f"{where}: {field} too short")
            src = item.get("source") or {}
            if not URL_RE.match(str(src.get("url") or "")):
                errors.append(f"{where}: source url must be https")
            if not str(src.get("title") or "").strip() or not str(src.get("publisher") or "").strip():
                errors.append(f"{where}: source title and publisher required")
            date = str(src.get("date") or "")
            if not DATE_RE.match(date) or (DATE_RE.match(generated) and date > generated):
                errors.append(f"{where}: source date missing or after generated_at")
            if src.get("verified_via") not in ("surfer_web_read",):
                errors.append(f"{where}: source must be verified by the Surfer")
        for missing in sorted(set(topic_ids) - used):
            errors.append(f"{pid}: topic {missing} has no items")
    return errors


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, Any]:
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    errors = validate_catalog(catalog)
    if errors:
        raise ValueError("MyBrief fixture invalid: " + "; ".join(errors[:5]))
    return catalog


def _profession(catalog: dict[str, Any], profession: str) -> dict[str, Any]:
    for prof in catalog["professions"]:
        if prof["id"] == profession:
            return prof
    raise MyBriefError("unknown_profession", 404)


def catalog_view(catalog: dict[str, Any]) -> dict[str, Any]:
    """What the picker needs: professions and topics with item counts, no item text."""
    return {"kind": catalog["kind"], "generated_at": catalog["generated_at"], "language": catalog.get("language", "en"),
            "method": catalog.get("method", ""),
            "professions": [{"id": p["id"], "title": p["title"], "audience": p["audience"],
                             "topics": [dict(t, items=sum(1 for i in p["items"] if i["topic"] == t["id"]))
                                        for t in p["topics"]]} for p in catalog["professions"]]}


def compose(catalog: dict[str, Any], profession: str, topics: list[str] | None) -> dict[str, Any]:
    """The sample briefing: fixture items for the chosen topics, in fixture order. No topics = all topics."""
    prof = _profession(catalog, profession)
    known = [t["id"] for t in prof["topics"]]
    chosen = [t for t in (topics or []) if t]
    if any(t not in known for t in chosen):
        raise MyBriefError("unknown_topic")
    chosen = chosen or known
    items = [i for i in prof["items"] if i["topic"] in chosen]
    sources, seen = [], set()
    for i in items:
        if i["source"]["url"] not in seen:
            seen.add(i["source"]["url"])
            sources.append(i["source"])
    return {"kind": catalog["kind"], "generated_at": catalog["generated_at"], "profession": prof["id"],
            "title": prof["title"], "topics": chosen, "items": items, "sources": sources,
            "note": "Demo briefing from a fixed sample written once from real, dated sources. Not live news."}


def clean_comment(text: Any) -> str:
    text = re.sub(r"[\u0000-\u0008\u000b-\u001f<>]", "", str(text or "")).strip()[:COMMENT_MAX]
    return PHONE_RE.sub("[number removed]", EMAIL_RE.sub("[email removed]", text))


class FeedbackStore:
    """JSON file of consented feedback. One web process writes it; the lock covers its threads."""

    def __init__(self, path: Path, catalog: dict[str, Any], *, clock: Callable[[], float] = time.time):
        self.path, self.catalog, self.clock = Path(path), catalog, clock
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._salt_day, self._salt = "", b""

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), list):
                data.setdefault("daily", {})
                return data
        except FileNotFoundError:
            return {"version": 1, "entries": [], "daily": {}}
        except (OSError, ValueError):
            pass
        raise MyBriefError("feedback_unreadable", 503)

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["entries"] = data["entries"][-MAX_KEPT:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def _client_key(self, client: str, day: str) -> str:
        if self._salt_day != day:  # a new salt each UTC day: yesterday's keys cannot be linked to today's
            self._salt_day, self._salt, self._counts = day, secrets.token_bytes(16), {}
        return hashlib.sha256(self._salt + client.encode()).hexdigest()[:20]

    def submit(self, body: dict[str, Any], client: str) -> dict[str, Any]:
        if body.get("consent") is not True:
            raise MyBriefError("consent_required")
        prof = _profession(self.catalog, str(body.get("profession") or ""))
        known = {t["id"] for t in prof["topics"]}
        topics = body.get("topics") if isinstance(body.get("topics"), list) else []
        topics = [str(t) for t in topics][:10]
        if any(t not in known for t in topics):
            raise MyBriefError("unknown_topic")
        rating = body.get("rating")
        if not isinstance(rating, int) or isinstance(rating, bool) or not 1 <= rating <= 5:
            raise MyBriefError("bad_rating")
        weekly = body.get("would_read_weekly")
        if weekly is not None and not isinstance(weekly, bool):
            raise MyBriefError("bad_weekly")
        now = self.clock()
        day = _day(now)
        with self._lock:
            key = self._client_key(client or "?", day)
            if self._counts.get(key, 0) >= PER_CLIENT_DAILY:
                raise MyBriefError("daily_limit", 429)
            data = self._load()
            if data["daily"].get(day, 0) >= GLOBAL_DAILY:
                raise MyBriefError("daily_limit", 429)
            token = secrets.token_urlsafe(18)
            entry = {"id": "fb-" + secrets.token_hex(6), "at": _iso(now), "profession": prof["id"],
                     "topics": sorted(set(topics)), "rating": rating, "would_read_weekly": weekly,
                     "comment": clean_comment(body.get("comment")), "consent": True,
                     "withdraw_hash": hashlib.sha256(token.encode()).hexdigest()}
            data["entries"].append(entry)
            data["daily"] = {d: n for d, n in data["daily"].items() if d >= day} | {day: data["daily"].get(day, 0) + 1}
            self._save(data)
            self._counts[key] = self._counts.get(key, 0) + 1
        return {"id": entry["id"], "withdraw_token": token, "stored": ["profession", "topics", "rating",
                                                                       "would_read_weekly", "comment"]}

    def withdraw(self, entry_id: str, token: str) -> dict[str, Any]:
        digest = hashlib.sha256(str(token or "").encode()).hexdigest()
        with self._lock:
            data = self._load()
            keep = [e for e in data["entries"] if not (e["id"] == entry_id and secrets.compare_digest(e["withdraw_hash"], digest))]
            if len(keep) == len(data["entries"]):
                raise MyBriefError("not_found", 404)
            data["entries"] = keep
            self._save(data)
        return {"withdrawn": True}

    def consented_entries(self) -> list[dict[str, Any]]:
        """T-630: stored (consented) entries without withdraw hashes, for the Product Evolution import."""
        with self._lock:
            entries = self._load()["entries"]
        return [{k: v for k, v in e.items() if k != "withdraw_hash"} for e in entries]

    def summary(self) -> dict[str, Any]:
        with self._lock:
            entries = self._load()["entries"]
        per: dict[str, dict[str, Any]] = {}
        for e in entries:
            p = per.setdefault(e["profession"], {"count": 0, "rating_sum": 0, "weekly_yes": 0, "weekly_no": 0, "topics": {}})
            p["count"] += 1
            p["rating_sum"] += e["rating"]
            if e.get("would_read_weekly") is True:
                p["weekly_yes"] += 1
            elif e.get("would_read_weekly") is False:
                p["weekly_no"] += 1
            for t in e["topics"]:
                p["topics"][t] = p["topics"].get(t, 0) + 1
        for p in per.values():
            p["avg_rating"] = round(p.pop("rating_sum") / p["count"], 2)
        public = [{k: v for k, v in e.items() if k != "withdraw_hash"} for e in entries[-50:]]
        return {"project": PROJECT_ID, "issue": ISSUE, "total": len(entries), "by_profession": per,
                "latest": list(reversed(public)),
                "note": "Only consented feedback is stored. Counts are real submissions, not projections."}


def install_mybrief_routes(app, store: FeedbackStore, identity_fn: Callable) -> None:
    """Public (no sign-in): catalog, brief, feedback, withdraw. Signed-in owner/member: the feedback summary."""
    catalog = store.catalog

    def _err(exc: MyBriefError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    async def _body(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    @app.get("/api/mybrief/public/catalog")
    def mybrief_catalog():
        return catalog_view(catalog)

    @app.get("/api/mybrief/public/brief")
    def mybrief_brief(profession: str = "", topics: str = ""):
        try:
            return compose(catalog, profession, [t.strip() for t in topics.split(",") if t.strip()][:10])
        except MyBriefError as exc:
            return _err(exc)

    @app.post("/api/mybrief/public/feedback")
    async def mybrief_feedback(request: Request):
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            return store.submit(body, _client_id(request))
        except MyBriefError as exc:
            return _err(exc)

    @app.post("/api/mybrief/public/feedback/{entry_id}/withdraw")
    async def mybrief_withdraw(entry_id: str, request: Request):
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            return store.withdraw(entry_id, str(body.get("token") or ""))
        except MyBriefError as exc:
            return _err(exc)

    @app.get("/api/mybrief/feedback")
    def mybrief_feedback_summary(request: Request):
        role = str((identity_fn(request) or {}).get("role") or "")
        if role not in ("owner", "member"):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        try:
            return store.summary()
        except MyBriefError as exc:
            return _err(exc)
