"""T-702 Social autopilot core: weekly content plan → owner approval → exactly-once scheduled publishing.

Owner 2026-11-18: «FactoryOS ведёт мои соцсети с минимумом действий с моей стороны». Publishing to an external
platform always stays behind an owner approval:

- Mode ``plan`` (A, default): the owner approves the whole plan with one action; each approved item then publishes at
  its planned time by itself. Single items can also be approved one by one.
- Mode ``rules`` (B): explicit owner opt-in (``rules_opt_in``), off by default. At its planned time a draft that passes
  the owner's rules (platforms, topics, banned words, max posts/day, minimum length) is approved *by the owner's rules*
  and published; anything else waits for the owner. Tone is guidance for whoever writes drafts, not a machine check.
- Mode ``each`` (C): every item is approved separately; "approve the plan" is refused.

An approval freezes ``sha256(platform + text)``; any edit drops it (same as ``linkedin_publisher.PostStore``).

Scheduler (``Autopilot.tick``): only when ``FACTORY_SOCIAL_AUTOPILOT_ENABLED=1`` and the owner has not pressed «Стоп».
Each due item is claimed (approved → publishing, persisted) *before* the network call, so a crash or a timeout can
never send it twice: a claim that never finished becomes ``uncertain`` on restart, and uncertain items are never
retried — the owner checks the platform and confirms. Permanent errors become ``failed`` with a fixed code; the owner
re-approves to try again. Provider response bodies and tokens are never stored or returned.

Adapters plug in through ``Adapter`` (``name``, ``max_chars``, ``blockers()``, ``publish(text)``): Telegram channel
(Bot API ``sendMessage`` with the existing FactoryOS bot) and LinkedIn (``linkedin_publisher.send_text``). Instagram,
TikTok and OLX are later tasks.

Plans are filled for free: ``propose_week`` turns existing Content Brain ideas into drafts with a fixed template (no
LLM, no paid call), agents add drafts through the MCP tools ``social_plan_list`` / ``social_plan_propose`` (they can
never approve), and the owner writes or edits drafts on ``/static/social/``.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib import error as urlerror
from urllib import request as urlrequest
from zoneinfo import ZoneInfo

from fastapi import HTTPException, Request

KYIV = ZoneInfo("Europe/Kyiv")
MODES = ("plan", "rules", "each")
PLATFORMS = ("telegram", "linkedin")
ID_RE = re.compile(r"^sp_[0-9a-f]{12}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
LOCAL_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T([01]\d|2[0-3]):[0-5]\d$")
TG_CHANNEL_RE = re.compile(r"^(@[A-Za-z][A-Za-z0-9_]{3,31}|-100\d{5,15})$")
MAX_ITEMS = 600
MAX_LATE_SECONDS = 6 * 3600          # an approved item more than 6 h overdue (e.g. after downtime) is not sent: «missed»
HARD_DAILY_CAP = 10                  # per platform per Kyiv day, in every mode
SUMMARY_HOUR = 21                    # daily owner summary, Europe/Kyiv
MIN_RULES_TEXT = 20
SENT_STATES = ("publishing", "published", "uncertain")
DEFAULT_SETTINGS = {
    "mode": "plan", "rules_opt_in": False, "paused": False, "plan_days": 7,
    "platforms": ["telegram", "linkedin"],
    "slots": {"telegram": ["10:00", "18:00"], "linkedin": ["09:30"]},
    "rules": {"platforms": [], "topics": [], "banned_words": [], "max_per_day": 2, "tone": ""},
}

Http = Callable[[str, str, dict, object, float], tuple]


def env_enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("FACTORY_SOCIAL_AUTOPILOT_ENABLED", "")).strip().lower() in ("1", "true", "yes")


def urllib_http(method, url, headers, body, timeout):
    req = urlrequest.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urlerror.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b""


def _json(body: bytes) -> dict:
    try:
        data = json.loads((body or b"{}").decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def clean_text(text) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def approval_hash(platform: str, text: str) -> str:
    return hashlib.sha256((platform + "\n" + text).encode("utf-8")).hexdigest()


def kyiv_day(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, KYIV).strftime("%Y-%m-%d")


def local_label(ts: float) -> str:
    return dt.datetime.fromtimestamp(ts, KYIV).strftime("%Y-%m-%dT%H:%M")


def parse_local(value) -> int:
    """'YYYY-MM-DDTHH:MM' in Europe/Kyiv → UTC epoch seconds."""
    value = str(value or "").strip()
    if not LOCAL_RE.fullmatch(value):
        raise HTTPException(400, "planned time must look like 2026-11-20T10:00 (Kyiv time)")
    try:
        naive = dt.datetime.strptime(value, "%Y-%m-%dT%H:%M")
    except ValueError:
        raise HTTPException(400, "planned time is not a real date") from None
    return int(naive.replace(tzinfo=KYIV).timestamp())


class PublishError(RuntimeError):
    """Fixed, secret-free code. ``uncertain`` = the post may exist; never retried automatically."""

    def __init__(self, code: str, uncertain: bool = False):
        super().__init__(code)
        self.code, self.uncertain = code, uncertain


class Adapter:
    """One publishing platform. ``publish`` returns {"url": str, "external_id": str} or raises PublishError."""
    name = ""
    max_chars = 4096

    def blockers(self) -> list:
        return []

    def publish(self, text: str) -> dict:
        raise PublishError("adapter_missing")


class TelegramChannelAdapter(Adapter):
    """Plain-text ``sendMessage`` to a channel the existing FactoryOS bot administers (no parse_mode: text is literal)."""
    name, max_chars = "telegram", 4096

    def __init__(self, token: Callable[[], str], channel: Callable[[], str], http: Http = urllib_http,
                 timeout: float = 20.0):
        self.token, self.channel, self.http, self.timeout = token, channel, http, timeout

    def blockers(self) -> list:
        out = []
        if not (self.token() or "").strip():
            out.append("telegram_bot_missing")
        channel = (self.channel() or "").strip()
        if not channel:
            out.append("telegram_channel_missing")
        elif not TG_CHANNEL_RE.fullmatch(channel):
            out.append("telegram_channel_invalid")
        return out

    def _call(self, method: str, payload: dict) -> tuple:
        url = "https://api.telegram.org/bot" + self.token().strip() + "/" + method    # never logged or returned
        return self.http("POST", url, {"Content-Type": "application/json"},
                         json.dumps(payload, ensure_ascii=False).encode("utf-8"), self.timeout)

    @staticmethod
    def link(chat: dict, channel: str, message_id: int) -> str:
        username = str((chat or {}).get("username") or "").lstrip("@") or (channel[1:] if channel.startswith("@") else "")
        if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", username):
            return f"https://t.me/{username}/{message_id}"
        chat_id = str((chat or {}).get("id") or channel)
        if chat_id.startswith("-100") and chat_id[4:].isdigit():
            return f"https://t.me/c/{chat_id[4:]}/{message_id}"
        return ""

    def publish(self, text: str) -> dict:
        if self.blockers():
            raise PublishError("telegram_not_ready")
        channel = self.channel().strip()
        try:
            status, _, raw = self._call("sendMessage", {"chat_id": channel, "text": text,
                                                        "disable_notification": False})
        except (TimeoutError, OSError, urlerror.URLError):
            raise PublishError("telegram_outcome_uncertain", uncertain=True) from None
        data = _json(raw)
        if status == 200 and data.get("ok"):
            msg = data.get("result") or {}
            mid = msg.get("message_id")
            if not isinstance(mid, int):
                raise PublishError("telegram_sent_without_id", uncertain=True)
            return {"url": self.link(msg.get("chat") or {}, channel, mid), "external_id": str(mid)}
        if status == 401:
            raise PublishError("telegram_auth_failed")
        if status == 403:
            raise PublishError("telegram_bot_not_admin")
        if status == 400:
            raise PublishError("telegram_bad_request")
        if status == 429:
            raise PublishError("telegram_rate_limited")      # Telegram refused: nothing was posted
        raise PublishError(f"telegram_rejected_{status}", uncertain=status >= 500 or status == 200)

    def check(self) -> dict:
        """Owner-triggered preflight (no post): is the bot an admin of the channel that may post?"""
        if self.blockers():
            return {"ok": False, "code": self.blockers()[0]}
        try:
            status, _, raw = self._call("getMe", {})
            me = _json(raw).get("result") or {}
            if status != 200 or not isinstance(me.get("id"), int):
                return {"ok": False, "code": "telegram_auth_failed"}
            status, _, raw = self._call("getChatMember", {"chat_id": self.channel().strip(), "user_id": me["id"]})
        except (TimeoutError, OSError, urlerror.URLError):
            return {"ok": False, "code": "telegram_unreachable"}
        member = _json(raw).get("result") or {}
        if status != 200:
            return {"ok": False, "code": "telegram_channel_not_found" if status == 400 else "telegram_bot_not_admin"}
        if member.get("status") == "creator" or (member.get("status") == "administrator"
                                                  and member.get("can_post_messages") is not False):
            return {"ok": True, "code": "telegram_ready"}
        return {"ok": False, "code": "telegram_bot_not_admin"}


class LinkedInAdapter(Adapter):
    """Publishes through ``linkedin_publisher.send_text`` (its OAuth vault, flag and error codes), never a copy of it."""
    name, max_chars = "linkedin", 3000

    def __init__(self, flow, workspace: Callable[[], str], http: Optional[Http] = None, env=None):
        self.flow, self.workspace, self.http, self.env = flow, workspace, http, env

    def blockers(self) -> list:
        import linkedin_publisher
        return linkedin_publisher.readiness(self.flow, self.workspace(), self.env)[0]

    def publish(self, text: str) -> dict:
        import linkedin_publisher
        try:
            out = linkedin_publisher.send_text(self.flow, self.workspace(), text, http=self.http, env=self.env)
        except linkedin_publisher.LinkedInError as exc:
            raise PublishError(exc.code, uncertain=exc.uncertain) from None
        return {"url": out.get("url", ""), "external_id": out.get("post_urn", "")}


def rules_verdict(item: dict, rules: dict, published_today: int) -> list:
    """Reasons a draft does NOT pass the owner's rules; empty list = passes."""
    reasons = []
    text_low = item["text"].lower()
    if rules.get("platforms") and item["platform"] not in rules["platforms"]:
        reasons.append("platform_not_allowed")
    banned = [w for w in rules.get("banned_words") or [] if w and w.lower() in text_low]
    if banned:
        reasons.append("banned_word")
    topics = [t.lower() for t in rules.get("topics") or [] if t]
    if topics and not any(t in text_low or t in str(item.get("topic") or "").lower() for t in topics):
        reasons.append("topic_not_allowed")
    if published_today >= int(rules.get("max_per_day") or 0):
        reasons.append("daily_limit")
    if len(item["text"]) < MIN_RULES_TEXT:
        reasons.append("too_short")
    return reasons


def _clean_list(values, limit=30, size=60) -> list:
    if isinstance(values, str):
        values = values.split(",")
    out = []
    for v in values or []:
        v = " ".join(str(v).split())[:size]
        if v and v not in out:
            out.append(v)
    return out[:limit]


def normalize_settings(raw: dict, base: dict) -> dict:
    s = json.loads(json.dumps(base))
    if "mode" in raw:
        if raw["mode"] not in MODES:
            raise HTTPException(400, "mode must be plan, rules or each")
        s["mode"] = raw["mode"]
    if "rules_opt_in" in raw:
        s["rules_opt_in"] = raw["rules_opt_in"] is True
    if "plan_days" in raw:
        try:
            s["plan_days"] = max(1, min(14, int(raw["plan_days"])))
        except (TypeError, ValueError):
            raise HTTPException(400, "plan_days must be 1–14") from None
    if "platforms" in raw:
        s["platforms"] = [p for p in _clean_list(raw["platforms"]) if p in PLATFORMS]
    if "slots" in raw:
        slots = {}
        for p, times in (raw.get("slots") or {}).items():
            if p not in PLATFORMS:
                continue
            good = sorted({t for t in _clean_list(times, 6) if TIME_RE.fullmatch(t)})
            slots[p] = good
        s["slots"] = {**s["slots"], **slots}
    if "rules" in raw and isinstance(raw["rules"], dict):
        r = raw["rules"]
        rules = s["rules"]
        if "platforms" in r:
            rules["platforms"] = [p for p in _clean_list(r["platforms"]) if p in PLATFORMS]
        for key in ("topics", "banned_words"):
            if key in r:
                rules[key] = _clean_list(r[key])
        if "max_per_day" in r:
            try:
                rules["max_per_day"] = max(0, min(HARD_DAILY_CAP, int(r["max_per_day"])))
            except (TypeError, ValueError):
                raise HTTPException(400, "max_per_day must be a number") from None
        if "tone" in r:
            rules["tone"] = " ".join(str(r["tone"] or "").split())[:300]
    if s["mode"] == "rules" and not s["rules_opt_in"]:
        raise HTTPException(409, "rules mode needs the explicit owner opt-in (rules_opt_in)")
    return s


class Store:
    """Plan, settings and history in DATA_DIR/social_autopilot.json; one lock, atomic writes."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "social_autopilot.json"
        self.clock, self.lock = clock, threading.RLock()

    def _load(self) -> dict:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if not isinstance(value, dict):
            value = {}
        settings = json.loads(json.dumps(DEFAULT_SETTINGS))
        saved = value.get("settings") if isinstance(value.get("settings"), dict) else {}
        for k, v in saved.items():
            if k == "rules" and isinstance(v, dict):
                settings["rules"].update(v)
            elif k == "slots" and isinstance(v, dict):
                settings["slots"].update(v)
            elif k in settings:
                settings[k] = v
        return {"settings": settings, "items": [i for i in value.get("items") or [] if isinstance(i, dict)],
                "meta": value.get("meta") if isinstance(value.get("meta"), dict) else {}}

    def _save(self, data: dict) -> None:
        items = data["items"]
        if len(items) > MAX_ITEMS:          # drop the oldest finished history first, never an open item
            done = [i for i in items if i["status"] in ("published", "failed", "missed")]
            drop = {i["id"] for i in sorted(done, key=lambda i: i["planned_at"])[:len(items) - MAX_ITEMS]}
            data["items"] = [i for i in items if i["id"] not in drop]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def snapshot(self) -> dict:
        with self.lock:
            return self._load()

    @staticmethod
    def _find(data, item_id) -> dict:
        item = next((i for i in data["items"] if i["id"] == item_id), None) if ID_RE.fullmatch(item_id or "") else None
        if not item:
            raise HTTPException(404, "unknown plan item")
        return item

    # ---- settings / stop ----
    def update_settings(self, raw: dict) -> dict:
        with self.lock:
            data = self._load()
            data["settings"] = normalize_settings(raw or {}, data["settings"])
            self._save(data)
            return data["settings"]

    def set_paused(self, paused: bool) -> dict:
        with self.lock:
            data = self._load()
            data["settings"]["paused"] = bool(paused)
            data["meta"]["paused_at" if paused else "resumed_at"] = int(self.clock())
            self._save(data)
            return data["settings"]

    # ---- items ----
    def _validate(self, platform, text, max_chars) -> str:
        if platform not in PLATFORMS:
            raise HTTPException(400, "platform must be telegram or linkedin")
        text = clean_text(text)
        if not text or len(text) > max_chars:
            raise HTTPException(400, f"text must be 1–{max_chars} characters for {platform}")
        return text

    def create(self, platform, text, planned_at: int, *, source="", topic="", created_by="owner",
               max_chars=4096) -> dict:
        text = self._validate(platform, text, max_chars)
        item = {"id": "sp_" + secrets.token_hex(6), "platform": platform, "text": text,
                "planned_at": int(planned_at), "topic": " ".join(str(topic or "").split())[:80],
                "source": str(source or "")[:120], "created_by": str(created_by or "owner")[:40],
                "created": int(self.clock()), "status": "draft", "approved_hash": "", "approved_at": 0,
                "approved_by": "", "result": None, "waiting": []}
        with self.lock:
            data = self._load()
            if sum(1 for i in data["items"] if i["status"] in ("draft", "approved")) >= MAX_ITEMS // 2:
                raise HTTPException(409, "too many open plan items")
            data["items"].append(item)
            self._save(data)
        return item

    def edit(self, item_id, *, text=None, planned_at=None, platform=None, max_chars=4096) -> dict:
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            if item["status"] not in ("draft", "approved", "failed", "missed"):
                raise HTTPException(409, "a sent item can no longer be edited")
            new_platform = platform or item["platform"]
            new_text = self._validate(new_platform, item["text"] if text is None else text, max_chars)
            item.update(platform=new_platform, text=new_text, status="draft", approved_hash="", approved_at=0,
                        approved_by="", result=None, waiting=[])            # an edit drops approval
            if planned_at is not None:
                item["planned_at"] = int(planned_at)
            self._save(data)
            return item

    def delete(self, item_id) -> bool:
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            if item["status"] in SENT_STATES:
                raise HTTPException(409, "a sent item stays in the history")
            data["items"] = [i for i in data["items"] if i["id"] != item_id]
            self._save(data)
            return True

    def _approve(self, item, by) -> None:
        item.update(status="approved", approved_hash=approval_hash(item["platform"], item["text"]),
                    approved_at=int(self.clock()), approved_by=by, waiting=[])

    def approve(self, item_id) -> dict:
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            if item["status"] not in ("draft", "failed"):
                raise HTTPException(409, "only a draft can be approved")
            self._approve(item, "owner_item")
            self._save(data)
            return item

    def approve_plan(self, start: int, end: int) -> list:
        with self.lock:
            data = self._load()
            if data["settings"]["mode"] == "each":
                raise HTTPException(409, "mode «each»: approve every post separately")
            now = self.clock()
            done = []
            for item in data["items"]:
                if item["status"] == "draft" and start <= item["planned_at"] < end and item["planned_at"] > now:
                    self._approve(item, "owner_plan")
                    done.append(item["id"])
            self._save(data)
            return done

    def confirm(self, item_id, outcome) -> dict:
        """Owner checked the platform after an unknown outcome: a post URL, or 'not_published'."""
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            if item["status"] != "uncertain":
                raise HTTPException(409, "only an unknown outcome needs confirmation")
            if outcome == "not_published":
                item.update(status="failed", result={"code": "owner_confirmed_not_published"})
            else:
                url = str(outcome or "")
                if not re.fullmatch(r"https://[^\s]{4,300}", url):
                    raise HTTPException(400, "paste the post URL, or 'not_published'")
                item.update(status="published", result={"url": url, "source": "owner_confirmed"})
            self._save(data)
            return item

    # ---- scheduler side ----
    def recover_interrupted(self) -> int:
        """Startup: a claim that never finished may or may not have been sent → uncertain (never resent)."""
        with self.lock:
            data = self._load()
            n = 0
            for item in data["items"]:
                if item["status"] == "publishing":
                    item.update(status="uncertain", result={"code": "interrupted_by_restart"})
                    n += 1
            if n:
                self._save(data)
            return n

    def claim(self, item_id, *, rules_ok: bool = False) -> Optional[dict]:
        """approved (or a rules-passing draft) → publishing, atomically, unless paused. None = do not send."""
        with self.lock:
            data = self._load()
            if data["settings"]["paused"]:
                return None
            item = self._find(data, item_id)
            if item["status"] == "draft" and rules_ok:
                self._approve(item, "rules")
            if item["status"] != "approved" or item["approved_hash"] != approval_hash(item["platform"], item["text"]):
                return None
            item["status"] = "publishing"
            item["claimed_at"] = int(self.clock())
            self._save(data)
            return dict(item)

    def finish(self, item_id, status, result) -> dict:
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            item.update(status=status, result=result)
            self._save(data)
            return item

    def mark(self, item_id, **fields) -> None:
        with self.lock:
            data = self._load()
            item = self._find(data, item_id)
            if item["status"] in ("draft", "approved"):
                item.update(fields)
                self._save(data)

    def set_meta(self, **fields) -> None:
        with self.lock:
            data = self._load()
            data["meta"].update(fields)
            self._save(data)


def idea_text(idea: dict, platform: str, max_chars: int) -> str:
    """Fixed template from a Content Brain idea (no LLM): title, angle, why now, first source link."""
    parts = [" ".join(str(idea.get("title") or "").split())]
    for key in ("angle", "why_now"):
        v = " ".join(str(idea.get(key) or "").split())
        if v:
            parts.append(v)
    links = [x for x in idea.get("source_links") or [] if str(x).startswith("https://")]
    if links:
        parts.append(str(links[0]))
    text = "\n\n".join(p for p in parts if p)
    return text[:max_chars]


class Autopilot:
    def __init__(self, store: Store, adapters: dict, *, notify: Optional[Callable[[str], object]] = None,
                 ideas: Optional[Callable[[], Iterable[dict]]] = None, env=None,
                 clock: Callable[[], float] = time.time):
        self.store, self.adapters, self.notify, self.ideas, self.env = store, adapters, notify, ideas, env
        self.clock = clock
        self._tick_lock = threading.Lock()

    def enabled(self) -> bool:
        return env_enabled(self.env)

    def max_chars(self, platform) -> int:
        a = self.adapters.get(platform)
        return a.max_chars if a else 4096

    # ---- plan generation (free) ----
    def propose_week(self, start_day: Optional[str] = None, days: Optional[int] = None) -> dict:
        snap = self.store.snapshot()
        s = snap["settings"]
        days = max(1, min(14, int(days or s["plan_days"])))
        now = self.clock()
        if start_day:
            try:
                first = dt.date.fromisoformat(str(start_day))
            except ValueError:
                raise HTTPException(400, "start must be YYYY-MM-DD") from None
        else:
            first = dt.datetime.fromtimestamp(now, KYIV).date() + dt.timedelta(days=1)
        used = {i.get("source") for i in snap["items"] if i.get("source")}
        taken = {(i["platform"], i["planned_at"]) for i in snap["items"]}
        pool = [x for x in (self.ideas() if self.ideas else []) or []
                if x.get("id") and x.get("title") and x.get("status") != "rejected"]
        created, empty = [], 0
        for d in range(days):
            day = first + dt.timedelta(days=d)
            for platform in s["platforms"]:
                for slot in s["slots"].get(platform) or []:
                    at = parse_local(f"{day.isoformat()}T{slot}")
                    if at <= now or (platform, at) in taken:
                        continue
                    idea = next((x for x in pool if f"content_idea:{x['id']}:{platform}" not in used), None)
                    if not idea:
                        empty += 1
                        continue
                    source = f"content_idea:{idea['id']}:{platform}"
                    used.add(source)
                    item = self.store.create(platform, idea_text(idea, platform, self.max_chars(platform)), at,
                                             source=source, topic=idea.get("topic") or "", created_by="factory_plan",
                                             max_chars=self.max_chars(platform))
                    created.append(item["id"])
        return {"created": created, "empty_slots": empty, "days": days, "start": first.isoformat(),
                "generator": "content_brain_template", "paid_calls": 0}

    # ---- scheduler ----
    def tick(self) -> dict:
        """Publish due items exactly once. Safe to call every minute; overlapping calls are skipped."""
        if not self._tick_lock.acquire(blocking=False):
            return {"skipped": "busy"}
        try:
            return self._tick()
        finally:
            self._tick_lock.release()

    def _published_today(self, items, platform, now) -> int:
        today = kyiv_day(now)
        return sum(1 for i in items if i["platform"] == platform and i["status"] in SENT_STATES
                   and kyiv_day(i.get("claimed_at") or i["planned_at"]) == today)

    def _tick(self) -> dict:
        out = {"sent": [], "failed": [], "uncertain": [], "missed": [], "waiting": []}
        if not self.enabled():
            out["off"] = "autopilot_disabled"
            return out
        snap = self.store.snapshot()
        settings = snap["settings"]
        if settings["paused"]:
            out["off"] = "paused"
            return out
        now = self.clock()
        due = sorted((i for i in snap["items"] if i["status"] in ("draft", "approved") and i["planned_at"] <= now),
                     key=lambda i: i["planned_at"])
        rules_on = settings["mode"] == "rules" and settings["rules_opt_in"] is True
        for item in due:
            if item["status"] == "approved" and now - item["planned_at"] > MAX_LATE_SECONDS:
                self.store.finish(item["id"], "missed", {"code": "missed_publish_window"})
                out["missed"].append(item["id"])
                continue
            if item["status"] == "draft" and now - item["planned_at"] > MAX_LATE_SECONDS:
                continue                                    # an old unapproved draft just stays a draft
            current = self.store.snapshot()
            sent_today = self._published_today(current["items"], item["platform"], now)
            if sent_today >= HARD_DAILY_CAP:
                self.store.mark(item["id"], waiting=["hard_daily_cap"])
                out["waiting"].append(item["id"])
                continue
            rules_ok = False
            if item["status"] == "draft":
                if not rules_on:
                    continue                                # waits for the owner
                reasons = rules_verdict(item, current["settings"]["rules"], sent_today)
                if reasons:
                    self.store.mark(item["id"], waiting=reasons)
                    out["waiting"].append(item["id"])
                    continue
                rules_ok = True
            adapter = self.adapters.get(item["platform"])
            blockers = adapter.blockers() if adapter else ["adapter_missing"]
            if blockers:
                self.store.mark(item["id"], waiting=blockers[:3])
                out["waiting"].append(item["id"])
                continue
            claimed = self.store.claim(item["id"], rules_ok=rules_ok)
            if not claimed:
                if self.store.snapshot()["settings"]["paused"]:
                    out["off"] = "paused"
                    break
                continue
            try:
                result = adapter.publish(claimed["text"])
            except PublishError as exc:
                state = "uncertain" if exc.uncertain else "failed"
                self.store.finish(item["id"], state, {"code": exc.code})
                out[state].append(item["id"])
                continue
            except Exception as exc:                        # unknown failure after the request may have left
                self.store.finish(item["id"], "uncertain", {"code": "error_" + type(exc).__name__})
                out["uncertain"].append(item["id"])
                continue
            self.store.finish(item["id"], "published", {"url": str(result.get("url") or "")[:300],
                                                        "external_id": str(result.get("external_id") or "")[:120],
                                                        "published_at": int(self.clock())})
            out["sent"].append(item["id"])
        return out

    # ---- daily summary ----
    def summary_text(self, now: Optional[float] = None) -> str:
        now = self.clock() if now is None else now
        snap = self.store.snapshot()
        today = kyiv_day(now)
        items = snap["items"]
        todays = [i for i in items if kyiv_day(i.get("claimed_at") or i["planned_at"]) == today]
        pub = [i for i in todays if i["status"] == "published"]
        bad = [i for i in todays if i["status"] in ("failed", "missed")]
        unk = [i for i in items if i["status"] in ("uncertain", "publishing")]
        nxt = [i for i in items if i["status"] == "draft" and now < i["planned_at"] <= now + 86400]
        appr = [i for i in items if i["status"] == "approved" and now < i["planned_at"] <= now + 86400]
        lines = [f"📣 Соцсети за {today}"]
        if snap["settings"]["paused"]:
            lines.append("⏸ Автопилот на паузе («Стоп»).")
        elif not self.enabled():
            lines.append("⏸ Автопилот выключен (FACTORY_SOCIAL_AUTOPILOT_ENABLED).")
        lines.append(f"✅ Опубликовано: {len(pub)}")
        lines += [f"  • {i['platform']}: {(i.get('result') or {}).get('url') or 'без ссылки'}" for i in pub[:10]]
        lines.append(f"❌ Не отправлено: {len(bad)}")
        lines += [f"  • {i['platform']}: {(i.get('result') or {}).get('code') or i['status']}" for i in bad[:10]]
        if unk:
            lines.append(f"❓ Исход неизвестен — проверьте вручную: {len(unk)}")
        lines.append(f"🕒 Одобрено на 24 ч: {len(appr)} · ждут вашего одобрения: {len(nxt)}")
        lines.append("Подробно: /static/social/")
        return "\n".join(lines)

    def maybe_send_summary(self) -> bool:
        """Once per Kyiv day after SUMMARY_HOUR, only when the autopilot is on and the plan is not empty."""
        if not (self.notify and self.enabled()):
            return False
        now = self.clock()
        local = dt.datetime.fromtimestamp(now, KYIV)
        today = local.strftime("%Y-%m-%d")
        snap = self.store.snapshot()
        if local.hour < SUMMARY_HOUR or snap["meta"].get("summary_day") == today or not snap["items"]:
            return False
        self.store.set_meta(summary_day=today)              # mark first: a notify failure never spams retries
        try:
            return bool(self.notify(self.summary_text(now)))
        except Exception:
            return False

    # ---- views ----
    def state(self) -> dict:
        snap = self.store.snapshot()
        platforms = {}
        for name in PLATFORMS:
            a = self.adapters.get(name)
            blockers = (a.blockers() if a else ["adapter_missing"])
            platforms[name] = {"ready": not blockers, "blockers": blockers, "max_chars": self.max_chars(name)}
        items = sorted(snap["items"], key=lambda i: i["planned_at"])
        for i in items:
            i["planned_local"] = local_label(i["planned_at"])
        blockers = [] if self.enabled() else ["autopilot_disabled"]
        if snap["settings"]["paused"]:
            blockers.append("paused")
        return {"enabled": self.enabled(), "paused": snap["settings"]["paused"], "blockers": blockers,
                "settings": snap["settings"], "platforms": platforms, "items": items, "timezone": "Europe/Kyiv",
                "now_local": local_label(self.clock()), "summary_day": snap["meta"].get("summary_day", "")}

    def agent_view(self) -> dict:
        """What an agent may read through MCP: plan text and times, no results, links or settings beyond tone."""
        snap = self.store.snapshot()
        return {"timezone": "Europe/Kyiv", "mode": snap["settings"]["mode"], "tone": snap["settings"]["rules"]["tone"],
                "slots": snap["settings"]["slots"],
                "items": [{"id": i["id"], "platform": i["platform"], "planned_local": local_label(i["planned_at"]),
                           "status": i["status"], "text": i["text"][:500]}
                          for i in sorted(snap["items"], key=lambda i: i["planned_at"])
                          if i["status"] in ("draft", "approved")][:100]}

    def agent_propose(self, args: dict, lane: str) -> dict:
        """MCP: an agent adds a draft. It can never approve, edit sent items or publish."""
        platform = str(args.get("platform") or "")
        at = parse_local(args.get("planned_local"))
        if at <= self.clock():
            raise HTTPException(400, "planned time must be in the future")
        item = self.store.create(platform, args.get("text"), at, source=str(args.get("source") or "")[:120],
                                 topic=args.get("topic") or "", created_by="agent:" + (lane or "mcp")[:30],
                                 max_chars=self.max_chars(platform))
        return {"id": item["id"], "status": item["status"], "planned_local": local_label(item["planned_at"]),
                "note": "Draft only. The owner approves it on /static/social/ before anything is published."}


MCP_TOOLS = [
    {"name": "social_plan_list",
     "description": "Read the FactoryOS social media plan (open drafts and approved posts, Europe/Kyiv times, slots, "
                    "the owner's tone). Read-only.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "social_plan_propose",
     "description": "Add one DRAFT post to the FactoryOS social plan. It is never published until the owner approves "
                    "it. platform: telegram or linkedin; planned_local: YYYY-MM-DDTHH:MM in Europe/Kyiv.",
     "inputSchema": {"type": "object", "properties": {
         "platform": {"type": "string", "enum": list(PLATFORMS)}, "text": {"type": "string"},
         "planned_local": {"type": "string"}, "topic": {"type": "string"}, "source": {"type": "string"}},
         "required": ["platform", "text", "planned_local"], "additionalProperties": False}},
]
MCP_TOOL_NAMES = {t["name"] for t in MCP_TOOLS}


def call_tool(pilot: Autopilot, name: str, args: dict, lane: str = "") -> dict:
    if name == "social_plan_list":
        return pilot.agent_view()
    if name == "social_plan_propose":
        return pilot.agent_propose(args or {}, lane)
    raise HTTPException(404, "unknown tool")


def install_routes(app, *, pilot: Autopilot, identity: Callable, telegram: Optional[TelegramChannelAdapter] = None):
    store = pilot.store

    def owner(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def when(data) -> Optional[int]:
        return parse_local(data["planned_local"]) if data.get("planned_local") else None

    @app.get("/api/factory/social")
    def social_state(request: Request):
        owner(request)
        return pilot.state()

    @app.post("/api/factory/social/plan/generate")
    async def social_generate(request: Request):
        owner(request)
        data = await body(request)
        return pilot.propose_week(data.get("start") or None, data.get("days") or None)

    @app.post("/api/factory/social/plan/approve")
    async def social_approve_plan(request: Request):
        owner(request)
        data = await body(request)
        start = parse_local(data["from"]) if data.get("from") else 0
        end = parse_local(data["to"]) if data.get("to") else 2 ** 40
        return {"approved": store.approve_plan(start, end)}

    @app.post("/api/factory/social/items")
    async def social_create(request: Request):
        owner(request)
        data = await body(request)
        platform = str(data.get("platform") or "")
        at = when(data)
        if at is None:
            raise HTTPException(400, "planned_local is required")
        return {"item": store.create(platform, data.get("text"), at, topic=data.get("topic") or "",
                                     source="owner", created_by="owner", max_chars=pilot.max_chars(platform))}

    @app.post("/api/factory/social/items/{item_id}/edit")
    async def social_edit(item_id: str, request: Request):
        owner(request)
        data = await body(request)
        platform = data.get("platform") or None
        if platform is not None and platform not in PLATFORMS:
            raise HTTPException(400, "platform must be telegram or linkedin")
        current = next((i for i in store.snapshot()["items"] if i["id"] == item_id), None)
        limit = pilot.max_chars(platform or (current or {}).get("platform") or "telegram")
        return {"item": store.edit(item_id, text=data.get("text"), planned_at=when(data), platform=platform,
                                   max_chars=limit)}

    @app.post("/api/factory/social/items/{item_id}/approve")
    def social_approve(item_id: str, request: Request):
        owner(request)
        return {"item": store.approve(item_id)}

    @app.post("/api/factory/social/items/{item_id}/delete")
    def social_delete(item_id: str, request: Request):
        owner(request)
        return {"ok": store.delete(item_id)}

    @app.post("/api/factory/social/items/{item_id}/confirm")
    async def social_confirm(item_id: str, request: Request):
        owner(request)
        return {"item": store.confirm(item_id, (await body(request)).get("outcome"))}

    @app.post("/api/factory/social/settings")
    async def social_settings(request: Request):
        owner(request)
        return {"settings": store.update_settings(await body(request))}

    @app.post("/api/factory/social/stop")
    def social_stop(request: Request):
        owner(request)
        return {"settings": store.set_paused(True)}

    @app.post("/api/factory/social/resume")
    def social_resume(request: Request):
        owner(request)
        return {"settings": store.set_paused(False)}

    @app.post("/api/factory/social/telegram/check")
    def social_telegram_check(request: Request):
        owner(request)
        if telegram is None:
            return {"ok": False, "code": "adapter_missing"}
        return telegram.check()
