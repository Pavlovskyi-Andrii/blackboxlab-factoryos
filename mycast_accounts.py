"""MyCast listener accounts, open beta (owner decision 2026-11-06): sign in with Telegram or Google, keep one podcast,
share it at /mycast/u/<slug>.

Separate from FactoryOS staff sign-in: a listener cookie (`mycast_listener`) never grants dashboard access, and the
dashboard session never acts as a listener.

What is stored (also stated on the page):
- a random public slug;
- a display name (first name, or the Google name);
- the provider and a SHA-256 of the provider id, used to find the account again;
- for Telegram only, the chat id, needed to send the podcast later (the widget asks for "write" access);
- the podcast settings as a share code, and timestamps.
No email, no photo, no access token. DELETE /api/mycast/account removes the record at once.

#281 delivery is a separate, explicit opt-in. Approving a profile, signing in, pairing Telegram, importing a share
link or auditioning a voice never turns delivery on. "Enable delivery" needs: a signed-in listener, a Telegram chat,
an approved podcast version equal to the saved one, and an explicit consent flag. Any later edit to the podcast cancels
the approval and pauses delivery. Every change is written to the listener's audit trail. Test messages and samples go
only to the listener's own chat, a few per day.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "mycast_listener"
SESSION_SECONDS = 30 * 24 * 3600
TELEGRAM_MAX_AGE = 24 * 3600
CONSENT_VERSION = "mycast-delivery-consent-2026-11-07"
SENDS_PER_DAY = 3
MAX_AUDIT = 50
import mycast_library
from mycast_library import FREE_DAYS, FRIEND_DAYS, MAX_REFERRALS   # owner offer 2026-11-07; #305 rule in mycast_library
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{8,4000}$")
SLUG_RE = re.compile(r"^[a-z0-9]{8}$")
PAGE = "/static/mycast-configurator/index.html"


class AccountError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _name(text: Any) -> str:
    return re.sub(r"[\u0000-\u001f<>]", "", str(text or "")).strip()[:40] or "MyCast"


def verify_telegram(data: dict, bot_token: str, now: float) -> dict:
    """Telegram Login Widget check: HMAC-SHA256 over the sorted fields, keyed with SHA-256(bot token)."""
    if not bot_token:
        raise AccountError("telegram_not_configured", 503)
    if not isinstance(data, dict) or not data.get("hash") or not data.get("id"):
        raise AccountError("bad_telegram_login")
    fields = {k: str(v) for k, v in data.items() if k != "hash" and v is not None}
    check = "\n".join(f"{k}={fields[k]}" for k in sorted(fields))
    expected = hmac.new(hashlib.sha256(bot_token.encode()).digest(), check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, str(data["hash"])):
        raise AccountError("bad_telegram_login", 401)
    try:
        auth_date = int(fields.get("auth_date", "0"))
    except ValueError:
        auth_date = 0
    if now - auth_date > TELEGRAM_MAX_AGE or auth_date - now > 300:
        raise AccountError("stale_telegram_login", 401)
    return {"provider": "telegram", "pid": str(data["id"]), "name": _name(data.get("first_name") or data.get("username")),
            "chat_id": str(data["id"])}


class ListenerStore:
    """One JSON file; the web process is the only writer (one uvicorn worker, see render.yaml)."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(path), clock
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("listeners"), dict):
                return data
        except FileNotFoundError:
            return {"listeners": {}, "index": {}}
        except (OSError, ValueError):
            pass
        raise AccountError("store_unreadable", 503)  # never replace a damaged file with an empty one

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def _key(provider: str, pid: str) -> str:
        return hashlib.sha256(f"{provider}:{pid}".encode()).hexdigest()

    def login(self, who: dict, ref: str = "") -> dict:
        """ref: the inviting listener's slug from a share link. It counts once, only for a brand-new account."""
        key = self._key(who["provider"], who["pid"])
        now = int(self.clock())
        with self._lock:
            data = self._load()
            slug = data["index"].get(key)
            rec = data["listeners"].get(slug) if slug else None
            if not rec:
                slug = "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(8))
                while slug in data["listeners"]:
                    slug = "".join(secrets.choice("abcdefghijkmnpqrstuvwxyz23456789") for _ in range(8))
                rec = {"slug": slug, "provider": who["provider"], "key": key, "created": now, "code": ""}
                data["index"][key] = slug
                inviter = data["listeners"].get(ref) if isinstance(ref, str) and SLUG_RE.fullmatch(ref or "") else None
                if inviter and mycast_library.is_self_referral(inviter, key, who.get("chat_id")):
                    inviter = None                                               # #305: no self-referral
                if inviter and int(inviter.get("invited", inviter.get("referrals", 0))) < MAX_REFERRALS:
                    rec["referred_by"] = ref
                    # #305: both sides get +7 only at the friend's first real episode (credit_referral), so
                    # throwaway sign-ups cannot farm free days. "invited" caps pending + credited friends.
                    inviter["invited"] = int(inviter.get("invited", inviter.get("referrals", 0))) + 1
                    self._audit(inviter, now, "friend_joined")
            rec.update({"name": who["name"], "seen": now})
            if who.get("chat_id"):
                rec["chat_id"] = who["chat_id"]
            data["listeners"][slug] = rec
            self._save(data)
            return dict(rec)

    def link_telegram(self, slug: str, chat_id: str) -> dict:
        """#281: a signed-in listener (e.g. via Google) links their own Telegram chat; nothing is sent here."""
        now = int(self.clock())
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            if rec.get("chat_id") != chat_id:
                rec["chat_id"] = chat_id
                rec.pop("telegram_verified_at", None)          # a new chat must be verified again
                d = rec.get("delivery") or {}
                if d.get("active"):
                    rec["delivery"] = {**d, "active": False, "paused_reason": "telegram_changed"}
                self._audit(rec, now, "telegram_linked")
            rec["seen"] = now
            self._save(data)
            return dict(rec)

    @classmethod
    def credit_referral(cls, data: dict, rec: dict, now: int) -> bool:
        """#305: called under the store lock when an episode really reached the listener. Decides once, via the ledger."""
        return mycast_library.credit(data, rec, now)

    def grant_bonus(self, slug: str, days: int, key: str) -> bool:
        """T-634: add gift days once per key (a quiz reward id). False when the listener is gone or the key was used."""
        if not isinstance(days, int) or not 0 < days <= 31 or not key:
            return False
        now = int(self.clock())
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                return False
            grants = rec.setdefault("bonus_grants", [])
            if key in grants:
                return False
            grants.append(key)
            del grants[:-50]
            rec["bonus_days"] = int(rec.get("bonus_days", 0)) + days
            self._audit(rec, now, "bonus_days", f"+{days} {key}"[:80])
            self._save(data)
            return True

    def set_episode_public(self, slug: str, day: str, public: bool) -> dict:
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            try:
                row = mycast_library.set_public(data, rec, day, public, int(self.clock()))
            except KeyError:
                raise AccountError("episode_not_found", 404)
            except LookupError:
                raise AccountError("episode_not_ready", 409)
            self._save(data)
            return row

    def public_episode(self, token: str) -> Optional[tuple]:
        with self._lock:
            found = mycast_library.find_public(self._load(), token)
        return (dict(found[0]), found[1], dict(found[2])) if found else None

    def get(self, slug: str) -> Optional[dict]:
        with self._lock:
            rec = self._load()["listeners"].get(slug)
        return dict(rec) if rec else None

    @staticmethod
    def _audit(rec: dict, now: int, action: str, detail: str = "") -> None:
        rec["audit"] = (rec.get("audit") or [])[-(MAX_AUDIT - 1):] + [{"at": now, "action": action, "detail": detail[:120]}]

    def save_code(self, slug: str, code: str, approved: bool = False) -> dict:
        if not CODE_RE.match(code or ""):
            raise AccountError("bad_profile")
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            now = int(self.clock())
            rec["code"], rec["saved"] = code, now
            if approved:
                if rec.get("approved_code") != code:
                    self._audit(rec, now, "approved")
                rec["approved_code"], rec["approved_at"] = code, now
            elif rec.get("approved_code") and rec.get("approved_code") != code:
                rec["approved_code"], rec["approved_at"] = "", None          # an edit cancels the approval...
                self._audit(rec, now, "approval_cleared", "profile changed")
                if (rec.get("delivery") or {}).get("active"):                # ...and pauses delivery
                    rec["delivery"] = {**rec["delivery"], "active": False, "paused_reason": "profile_changed"}
                    self._audit(rec, now, "delivery_paused", "profile changed after approval")
            self._save(data)
            return dict(rec)

    def set_delivery(self, slug: str, enable: bool, consent: bool) -> dict:
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            now = int(self.clock())
            if enable:
                if consent is not True:
                    raise AccountError("consent_required")
                if not rec.get("chat_id"):
                    raise AccountError("telegram_not_linked", 409)
                if not rec.get("code") or rec.get("approved_code") != rec.get("code"):
                    raise AccountError("profile_not_approved", 409)
                if not (rec.get("delivery") or {}).get("active"):
                    rec["delivery"] = {"active": True, "since": now, "consent": CONSENT_VERSION, "code": rec["code"]}
                    self._audit(rec, now, "delivery_enabled", CONSENT_VERSION)
            elif (rec.get("delivery") or {}).get("active"):
                rec["delivery"] = {**rec["delivery"], "active": False, "stopped_at": now, "paused_reason": "listener_stopped"}
                self._audit(rec, now, "delivery_stopped")
            self._save(data)
            return dict(rec)

    def take_send(self, slug: str, kind: str) -> dict:
        """Count one message to the listener's own chat; refuse past SENDS_PER_DAY per UTC day."""
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
            sends = rec.get("sends") if (rec.get("sends") or {}).get("day") == day else {"day": day, "n": 0}
            if sends["n"] >= SENDS_PER_DAY:
                raise AccountError("send_limit", 429)
            rec["sends"] = {"day": day, "n": sends["n"] + 1}
            self._audit(rec, int(self.clock()), "sent_" + kind)
            self._save(data)
            return dict(rec)

    def mark(self, slug: str, **fields) -> None:
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if rec:
                rec.update(fields)
                self._save(data)

    def delete(self, slug: str) -> bool:
        with self._lock:
            data = self._load()
            rec = data["listeners"].pop(slug, None)
            if rec:
                data["index"].pop(rec.get("key", ""), None)
                mycast_library.drop_listener_links(data, slug)   # public episode links die with the account
                self._save(data)
            return bool(rec)


def sign(secret: str, slug: str, now: float) -> str:
    payload = f"ml1|{slug}|{int(now + SESSION_SECONDS)}"
    return payload + "|" + hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def unsign(secret: str, token: str, now: float) -> Optional[str]:
    parts = str(token or "").split("|")
    if len(parts) != 4 or parts[0] != "ml1" or not SLUG_RE.match(parts[1]):
        return None
    expected = hmac.new(secret.encode(), "|".join(parts[:3]).encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[3]):
        return None
    try:
        return parts[1] if int(parts[2]) > now else None
    except ValueError:
        return None


def public_view(rec: dict) -> dict:
    d = rec.get("delivery") or {}
    return {"slug": rec["slug"], "name": rec.get("name", ""), "provider": rec.get("provider", ""),
            "has_podcast": bool(rec.get("code")), "page": f"/mycast/u/{rec['slug']}",
            "telegram_linked": bool(rec.get("chat_id")), "telegram_verified": bool(rec.get("telegram_verified_at")),
            "calendar_linked": bool(rec.get("gcal")), "public_audio": bool(rec.get("public_audio")),
            "approved": bool(rec.get("code")) and rec.get("approved_code") == rec.get("code"),
            "delivery": {"active": bool(d.get("active")), "since": d.get("since"), "paused_reason": d.get("paused_reason", "")},
            "status": _delivery_status(rec),
            "audit": (rec.get("audit") or [])[-10:], "referrals": int(rec.get("referrals", 0)),
            "referrals_pending": max(0, int(rec.get("invited", 0)) - int(rec.get("referrals", 0))),
            "gifted": bool(rec.get("referred_by")), "free_days": free_days(rec),
            "access": mycast_library.access(rec),
            "referral": {"enabled": mycast_library.referrals_enabled(), "bonus_at": mycast_library.friend_bonus_at(),
                         "events": (rec.get("referral_events") or [])[-10:]}}


def _delivery_status(rec: dict) -> dict:
    """#317: the one honest state of the listener's daily episode for the cabinet (no profile, no chat id)."""
    from mycast_listener_delivery import delivery_gate
    try:
        gate = delivery_gate(rec, time.time())
    except Exception:
        return {"state": "unknown", "detail": "", "last": None}
    last = sorted((rec.get("deliveries") or {}).items())[-1:] or None
    return {"state": gate["state"], "detail": gate.get("detail", ""), "local_date": gate.get("local_date", ""),
            "last": {"date": last[0][0], "status": last[0][1].get("status"), "reason": last[0][1].get("reason", "")} if last else None}


def free_days(rec: dict) -> int:
    """7 days to start, +7 for each side of a referral once the friend's first real episode arrives (#305)."""
    return mycast_library.free_days(rec)


def install_mycast_account_routes(app, store: ListenerStore, *, secret: str, bot_token: Callable[[], str],
                                  bot_username: Callable[[], str], google_client_id: Callable[[], str],
                                  google_verify: Callable[[str], dict], secure_cookie: bool = True,
                                  clock: Callable[[], float] = time.time,
                                  send_message: Optional[Callable[[str, str], None]] = None,
                                  send_sample: Optional[Callable[[str, str], None]] = None,
                                  fetch_audio: Optional[Callable[[str], bytes]] = None,
                                  calendar_available: Optional[Callable[[], bool]] = None,
                                  on_delete: Optional[Callable[[str], None]] = None) -> None:
    def _err(exc: AccountError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    def _current(request: Request) -> Optional[dict]:
        slug = unsign(secret, request.cookies.get(COOKIE, ""), clock())
        return store.get(slug) if slug else None

    def _signed_in(rec: dict) -> JSONResponse:
        resp = JSONResponse({"listener": public_view(rec)})
        resp.set_cookie(COOKIE, sign(secret, rec["slug"], clock()), max_age=SESSION_SECONDS, httponly=True,
                        samesite="lax", secure=secure_cookie, path="/")
        return resp

    async def _body(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            raise AccountError("bad_body")
        return body

    @app.get("/api/mycast/account/config")
    def mycast_account_config():
        name = ""
        try:
            name = bot_username() if bot_token() else ""
        except Exception:
            name = ""
        token = bot_token() or ""
        bot_id = token.split(":", 1)[0] if re.fullmatch(r"\d{5,}:.+", token) else ""   # the public numeric part only
        return {"telegram_bot": name or None, "telegram_bot_id": bot_id or None, "google_client_id": google_client_id() or None,
                "consent_version": CONSENT_VERSION, "referrals_enabled": mycast_library.referrals_enabled(),
                "calendar_available": bool(calendar_available and calendar_available())}

    @app.get("/api/mycast/account/me")
    def mycast_account_me(request: Request):
        try:
            rec = _current(request)
        except AccountError as exc:
            return _err(exc)
        return {"listener": public_view(rec)} if rec else JSONResponse({"detail": "signed_out"}, status_code=401)

    @app.post("/api/mycast/account/telegram")
    async def mycast_account_telegram(request: Request):
        try:
            body = await _body(request)
            ref = str(body.pop("ref", "") or "")          # not part of Telegram's signed fields
            who = verify_telegram(body, bot_token(), clock())
            current = _current(request)
            if current and current.get("provider") != "telegram":   # #281: link to the account already signed in
                return _signed_in(store.link_telegram(current["slug"], who["chat_id"]))
            return _signed_in(store.login(who, ref))
        except AccountError as exc:
            return _err(exc)

    @app.post("/api/mycast/account/google")
    async def mycast_account_google(request: Request):
        try:
            body = await _body(request)
            if not google_client_id():
                raise AccountError("google_not_configured", 503)
            try:
                claims = google_verify(str(body.get("credential") or ""))
            except Exception:
                raise AccountError("bad_google_login", 401)
            if not claims or not claims.get("sub") or claims.get("email_verified") is False:
                raise AccountError("bad_google_login", 401)
            ref = str(body.get("ref") or "")
            current = _current(request)
            if current and current["slug"] == ref:
                ref = ""                                        # #305: a signed-in listener cannot invite a new self
            return _signed_in(store.login({"provider": "google", "pid": str(claims["sub"]),
                                           "name": _name(claims.get("given_name") or claims.get("name"))}, ref))
        except AccountError as exc:
            return _err(exc)

    @app.get("/api/mycast/account/podcast")
    def mycast_account_podcast_get(request: Request):
        """The signed-in listener's own saved podcast, so signing in on another browser restores it."""
        try:
            rec = _current(request)
        except AccountError as exc:
            return _err(exc)
        if not rec:
            return JSONResponse({"detail": "signed_out"}, status_code=401)
        code = rec.get("code") or ""
        return {"code": code or None, "approved": bool(code) and rec.get("approved_code") == code}

    @app.post("/api/mycast/account/podcast")
    async def mycast_account_podcast(request: Request):
        try:
            rec = _current(request)
            if not rec:
                raise AccountError("signed_out", 401)
            body = await _body(request)
            return {"listener": public_view(store.save_code(rec["slug"], str(body.get("code") or ""), body.get("approved") is True))}
        except AccountError as exc:
            return _err(exc)

    def _signed(request: Request) -> dict:
        rec = _current(request)
        if not rec:
            raise AccountError("signed_out", 401)
        return rec

    @app.post("/api/mycast/account/delivery")
    async def mycast_account_delivery(request: Request):
        try:
            rec, body = _signed(request), await _body(request)
            return {"listener": public_view(store.set_delivery(rec["slug"], body.get("enable") is True, body.get("consent") is True))}
        except AccountError as exc:
            return _err(exc)

    @app.post("/api/mycast/account/telegram/test")
    def mycast_account_telegram_test(request: Request):
        """Proves the pairing: the bot writes one short message to the listener's own chat. Only that marks it verified."""
        try:
            rec = _signed(request)
            if not rec.get("chat_id"):
                raise AccountError("telegram_not_linked", 409)
            if not send_message or not bot_token():
                raise AccountError("telegram_not_configured", 503)
            store.take_send(rec["slug"], "test")
            try:
                send_message(rec["chat_id"], "✅ MyCast: цей чат підключено. Розсилка не ввімкнена — її вмикаєте лише ви на сторінці MyCast.")
            except Exception:
                raise AccountError("telegram_send_failed", 502)
            store.mark(rec["slug"], telegram_verified_at=int(clock()))
            return {"listener": public_view(store.get(rec["slug"]))}
        except AccountError as exc:
            return _err(exc)

    @app.post("/api/mycast/account/delivery/sample")
    async def mycast_account_delivery_sample(request: Request):
        """One already generated demo, to the listener's own chat, only while delivery is on."""
        try:
            rec, body = _signed(request), await _body(request)
            if not (rec.get("delivery") or {}).get("active"):
                raise AccountError("delivery_off", 409)
            if not send_sample:
                raise AccountError("telegram_not_configured", 503)
            job = str(body.get("job") or "")
            if not re.fullmatch(r"[0-9a-f]{32}", job):
                raise AccountError("bad_job")
            store.take_send(rec["slug"], "sample")
            try:
                send_sample(rec["chat_id"], job)
            except AccountError:
                raise
            except Exception:
                raise AccountError("telegram_send_failed", 502)
            return {"listener": public_view(store.get(rec["slug"])), "sent": True}
        except AccountError as exc:
            return _err(exc)

    @app.get("/api/mycast/account/episodes")
    def mycast_account_episodes(request: Request):
        """#305 "My podcasts": the signed-in listener's own library (honest states). Audio stays on Telegram."""
        try:
            rec = _signed(request)
            return {"episodes": mycast_library.episode_rows(rec)}
        except AccountError as exc:
            return _err(exc)

    @app.get("/api/mycast/account/episodes/{day}/audio")
    def mycast_account_episode_audio(day: str, request: Request):
        """Streams one of the listener's own episodes back from Telegram (bot token stays on the server)."""
        try:
            rec = _signed(request)
            entry = mycast_library.episodes(rec).get(day) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day or "") else None
            if not entry or not entry.get("file_id"):
                raise AccountError("episode_not_found", 404)
            if not fetch_audio:
                raise AccountError("telegram_not_configured", 503)
            try:
                audio = fetch_audio(entry["file_id"])
            except Exception:
                raise AccountError("episode_unavailable", 502)
            return Response(audio, media_type="audio/mpeg",
                            headers={"Cache-Control": "private, max-age=3600",
                                     "Content-Disposition": f'inline; filename="mycast-{day}.mp3"'})
        except AccountError as exc:
            return _err(exc)

    @app.post("/api/mycast/account/logout")
    def mycast_account_logout():
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.delete("/api/mycast/account")
    def mycast_account_delete(request: Request):
        try:
            rec = _current(request)
            if not rec:
                raise AccountError("signed_out", 401)
            if on_delete is not None:
                try:
                    on_delete(rec["slug"])          # e.g. revoke the Google Calendar token at Google first
                except Exception:
                    pass
            store.delete(rec["slug"])
        except AccountError as exc:
            return _err(exc)
        resp = JSONResponse({"deleted": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/mycast/u/{slug}", include_in_schema=False)
    def mycast_public_page(slug: str, lang: str = ""):
        """Owner 2026-11-13: a shareable podcast page (DNA, optional player, "make one like this"), not the editor."""
        rec, profile = _public(slug)
        if not rec:
            return RedirectResponse(PAGE + "#missing", status_code=307)
        if profile is None:                                   # an old or damaged code: the editor still opens it
            return RedirectResponse(f"{PAGE}#p={rec['code']}&from={slug}", status_code=307)
        import mycast_public
        return HTMLResponse(mycast_public.render_page(rec, profile, page=PAGE, lang=str(lang or "")[:5]), headers={"Cache-Control": "public, max-age=300"})

    def _public(slug: str):
        rec = store.get(slug) if SLUG_RE.match(slug or "") else None
        if not rec or not rec.get("code"):
            return None, None
        from mycast_listener_delivery import decode_profile
        try:
            return rec, decode_profile(rec["code"])
        except ValueError:
            return rec, None

    @app.get("/mycast/u/{slug}/card.png", include_in_schema=False)
    def mycast_public_card(slug: str):
        rec, profile = _public(slug)
        if not rec or profile is None:
            return Response(status_code=404)
        import mycast_public
        return Response(mycast_public.card_png(rec, profile), media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    @app.get("/mycast/u/{slug}/latest.mp3", include_in_schema=False)
    def mycast_public_audio(slug: str):
        """Only when the listener turned on listening by link; streamed from Telegram, never stored here."""
        import mycast_public
        rec, _profile = _public(slug)
        found = mycast_public.latest_audio(rec) if rec else None
        if not found or not fetch_audio:
            return Response(status_code=404)
        if not mycast_public.allow_play(slug, clock()):
            return Response(status_code=429)
        try:
            audio = fetch_audio(found[1])
        except Exception:
            return Response(status_code=502)
        return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=3600",
                                                                 "Content-Disposition": f'inline; filename="mycast-{found[0]}.mp3"'})

    @app.post("/api/mycast/account/sharing")
    async def mycast_account_sharing(request: Request):
        try:
            rec = _signed(request)
            body = await _body(request)
        except AccountError as exc:
            return _err(exc)
        store.mark(rec["slug"], public_audio=body.get("public_audio") is True)
        return {"listener": public_view(store.get(rec["slug"]))}

    # ---- #305 / T-620: one episode at a time can be made public; private is the default ----
    @app.post("/api/mycast/account/episodes/{day}/visibility")
    async def mycast_account_episode_visibility(day: str, request: Request):
        try:
            rec, body = _signed(request), await _body(request)
            row = store.set_episode_public(rec["slug"], day, body.get("public") is True)
            return {"episode": row}
        except AccountError as exc:
            return _err(exc)

    _NOINDEX = {"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow", "Referrer-Policy": "no-referrer"}

    @app.get("/mycast/e/{token}", include_in_schema=False)
    def mycast_public_episode(token: str, request: Request = None, lang: str = ""):
        """A revocable public episode page (T-645 share card: coverflow with demo cards, player, public DNA). no-store,
        so unpublishing takes effect at once (no CDN copy keeps serving it)."""
        import mycast_public
        import mycast_share_page
        found = store.public_episode(token)
        if not found:
            return HTMLResponse(mycast_public.render_episode_missing(), status_code=404, headers=_NOINDEX)
        rec, day, entry = found
        accept = request.headers.get("accept-language", "") if request is not None else ""
        body = mycast_share_page.render(rec, day, entry, token=token, page=PAGE, lang=str(lang or "")[:5], accept=accept)
        return HTMLResponse(body, headers={**_NOINDEX, "Vary": "Accept-Language"})

    @app.get("/mycast/e/{token}/audio.mp3", include_in_schema=False)
    def mycast_public_episode_audio(token: str):
        import mycast_public
        found = store.public_episode(token)
        if not found or not found[2].get("file_id") or not fetch_audio:
            return Response(status_code=404, headers=_NOINDEX)
        if not mycast_public.allow_play("e:" + token, clock()):
            return Response(status_code=429, headers=_NOINDEX)
        try:
            audio = fetch_audio(found[2]["file_id"])
        except Exception:
            return Response(status_code=502, headers=_NOINDEX)
        return Response(audio, media_type="audio/mpeg",
                        headers={**_NOINDEX, "Content-Disposition": f'inline; filename="mycast-{found[1]}.mp3"'})
