"""MyCast: a listener connects their Google Calendar (read-only) and today's events and birthdays end the episode.

Flow (owner 2026-11-13, Google Cloud project "MyCastpro"):
- /api/mycast/calendar/connect: the signed-in listener is sent to Google with scope calendar.readonly and a signed,
  short-lived state that names their own slug.
- /api/mycast/calendar/callback: the state must match the listener cookie (no login CSRF); the code is exchanged with
  FACTORY_GOOGLE_CLIENT_SECRET; only the refresh token is kept, AES-256-GCM encrypted with FACTORY_VAULT_KEY and bound
  to the listener's slug. No calendar contents are stored.
- When the listener's episode is due, the server reads only today's events and birthdays (title and start time, at
  most 10 each) and hands them to the worker for that one script. Any failure means "no calendar today", never a
  missed episode. Disconnect (or deleting the account) revokes the token at Google and removes it here.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from typing import Callable, Optional
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse

SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"
STATE_SECONDS = 600
CACHE_SECONDS = 3600
MAX_ITEMS = 10
MAX_TITLE = 80
PAGE = "/static/mycast-configurator/index.html"
SLUG_RE = re.compile(r"^[a-z0-9]{8}$")


class CalendarError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _aad(slug: str) -> bytes:
    return f"mycast-gcal|{slug}".encode()


class ListenerCalendar:
    def __init__(self, store, *, keyring: Callable, client_id: Callable[[], str], client_secret: Callable[[], str],
                 secret: str, redirect_uri: str, http=None, clock: Callable[[], float] = time.time):
        self.store, self.keyring, self.client_id, self.client_secret = store, keyring, client_id, client_secret
        self.secret, self.redirect_uri, self.clock = secret, redirect_uri, clock
        self._http = http
        self._cache: dict = {}

    @property
    def http(self):
        if self._http is None:
            import requests
            self._http = requests
        return self._http

    def available(self) -> bool:
        try:
            return bool(self.client_id() and self.client_secret() and self.keyring())
        except Exception:
            return False

    # --- state: names the listener, expires, cannot be forged without the server secret
    def _state(self, slug: str) -> str:
        payload = f"gc1|{slug}|{int(self.clock() + STATE_SECONDS)}|{secrets.token_hex(8)}"
        return payload + "|" + hmac.new(self.secret.encode(), payload.encode(), hashlib.sha256).hexdigest()

    def _state_slug(self, state: str) -> Optional[str]:
        parts = str(state or "").split("|")
        if len(parts) != 5 or parts[0] != "gc1" or not SLUG_RE.match(parts[1]):
            return None
        good = hmac.new(self.secret.encode(), "|".join(parts[:4]).encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(good, parts[4]):
            return None
        try:
            return parts[1] if int(parts[2]) > self.clock() else None
        except ValueError:
            return None

    def auth_url(self, slug: str) -> str:
        return AUTH_URL + "?" + urlencode({
            "client_id": self.client_id(), "redirect_uri": self.redirect_uri, "response_type": "code", "scope": SCOPE,
            "access_type": "offline", "prompt": "consent", "include_granted_scopes": "false",
            "state": self._state(slug)})

    def finish(self, cookie_slug: Optional[str], code: str, state: str) -> None:
        slug = self._state_slug(state)
        if not slug or slug != cookie_slug:
            raise CalendarError("bad_state")
        if not code or len(code) > 512:
            raise CalendarError("no_code")
        r = self.http.post(TOKEN_URL, data={"code": code, "client_id": self.client_id(),
                                            "client_secret": self.client_secret(), "redirect_uri": self.redirect_uri,
                                            "grant_type": "authorization_code"}, timeout=20)
        body = r.json() if r.status_code == 200 else {}
        refresh = str(body.get("refresh_token") or "")
        if not refresh:
            raise CalendarError("token_exchange_failed")
        if SCOPE not in str(body.get("scope") or "").split():
            self._revoke(refresh)
            raise CalendarError("scope_not_granted")          # the listener unticked calendar on Google's screen
        envelope = self.keyring().encrypt(refresh.encode(), _aad(slug))
        with self.store._lock:
            data = self.store._load()
            rec = data["listeners"].get(slug)
            if not rec:
                self._revoke(refresh)
                raise CalendarError("signed_out")
            rec["gcal"] = {"env": envelope, "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock()))}
            rec["audit"] = (rec.get("audit") or [])[-49:] + [{"at": int(self.clock()), "action": "calendar_connected", "detail": ""}]
            self.store._save(data)

    def _refresh_token(self, rec: dict) -> str:
        env = (rec.get("gcal") or {}).get("env")
        if not env:
            raise CalendarError("not_connected")
        return self.keyring().decrypt(env, _aad(rec["slug"])).decode()

    def _revoke(self, token: str) -> None:
        try:
            self.http.post(REVOKE_URL, data={"token": token}, timeout=10)
        except Exception:
            pass

    def disconnect(self, slug: str) -> bool:
        rec = self.store.get(slug)
        if not rec or not rec.get("gcal"):
            return False
        try:
            self._revoke(self._refresh_token(rec))
        except Exception:
            pass                                               # unreadable token: still forget it here
        self._forget(slug, "calendar_disconnected")
        return True

    def _forget(self, slug: str, action: str) -> None:
        with self.store._lock:
            data = self.store._load()
            rec = data["listeners"].get(slug)
            if rec and rec.pop("gcal", None) is not None:
                rec["audit"] = (rec.get("audit") or [])[-49:] + [{"at": int(self.clock()), "action": action, "detail": ""}]
                self.store._save(data)
        for key in [k for k in self._cache if k[0] == slug]:
            self._cache.pop(key, None)

    def _access_token(self, rec: dict) -> str:
        r = self.http.post(TOKEN_URL, data={"refresh_token": self._refresh_token(rec), "client_id": self.client_id(),
                                            "client_secret": self.client_secret(), "grant_type": "refresh_token"},
                           timeout=20)
        if r.status_code == 400 and (r.json() if r.content else {}).get("error") == "invalid_grant":
            self._forget(rec["slug"], "calendar_revoked_at_google")     # the listener revoked us in their Google Account
            raise CalendarError("revoked")
        token = (r.json() if r.status_code == 200 else {}).get("access_token")
        if not token:
            raise CalendarError("refresh_failed")
        return token

    def _list(self, token: str, start: datetime, end: datetime, event_type: str) -> list:
        r = self.http.get(EVENTS_URL, headers={"Authorization": "Bearer " + token}, params={
            "timeMin": start.isoformat(), "timeMax": end.isoformat(), "singleEvents": "true", "orderBy": "startTime",
            "maxResults": str(MAX_ITEMS), "eventTypes": event_type,
            "fields": "items(summary,start,status)"}, timeout=20)
        if r.status_code != 200:
            raise CalendarError(f"events_{r.status_code}")
        items = []
        for ev in (r.json().get("items") or [])[:MAX_ITEMS]:
            if ev.get("status") == "cancelled":
                continue
            title = " ".join(str(ev.get("summary") or "").split())[:MAX_TITLE]
            when = (ev.get("start") or {}).get("dateTime") or ""
            items.append({"title": title or "—", "time": when[11:16] if len(when) >= 16 else ""})
        return items

    def today(self, rec: dict, profile: dict, local_date: str) -> dict:
        """{"events": [...], "birthdays": [...]} for what the listener chose; {} when not connected or on any error."""
        want = profile.get("calendar") or {}
        if not rec.get("gcal") or not (want.get("events") or want.get("birthdays")) or not self.available():
            return {}
        key = (rec["slug"], local_date, bool(want.get("events")), bool(want.get("birthdays")))
        hit = self._cache.get(key)
        if hit and self.clock() - hit[0] < CACHE_SECONDS:
            return hit[1]
        try:
            tz = ZoneInfo(profile.get("timezone") or "Europe/Kyiv")
            start = datetime.fromisoformat(local_date).replace(tzinfo=tz)
            token = self._access_token(rec)
            out = {}
            if want.get("events"):
                out["events"] = self._list(token, start, start + timedelta(days=1), "default")
            if want.get("birthdays"):
                out["birthdays"] = [{"title": b["title"], "time": ""} for b in
                                    self._list(token, start, start + timedelta(days=1), "birthday")]
        except Exception:
            return {}
        self._cache[key] = (self.clock(), out)
        return out


def install_calendar_routes(app, cal: ListenerCalendar, *, current_slug: Callable[[Request], Optional[str]]) -> None:
    def back(state: str) -> RedirectResponse:
        return RedirectResponse(f"{PAGE}?calendar={state}#calBox", status_code=302)

    @app.get("/api/mycast/calendar/connect")
    def mycast_calendar_connect(request: Request):
        slug = current_slug(request)
        if not slug:
            return back("signin")
        if not cal.available():
            return back("unavailable")
        return RedirectResponse(cal.auth_url(slug), status_code=302)

    @app.get("/api/mycast/calendar/callback")
    def mycast_calendar_callback(request: Request, code: str = "", state: str = "", error: str = ""):
        if error:
            return back("denied")
        try:
            cal.finish(current_slug(request), code, state)
        except CalendarError as exc:
            return back("scope" if exc.code == "scope_not_granted" else "failed")
        except Exception:
            return back("failed")
        return back("connected")

    @app.post("/api/mycast/calendar/disconnect")
    def mycast_calendar_disconnect(request: Request):
        slug = current_slug(request)
        if not slug:
            return JSONResponse({"detail": "signed_out"}, status_code=401)
        return {"disconnected": cal.disconnect(slug)}

