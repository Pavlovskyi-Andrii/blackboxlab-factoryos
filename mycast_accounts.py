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
from fastapi.responses import JSONResponse, RedirectResponse

COOKIE = "mycast_listener"
SESSION_SECONDS = 30 * 24 * 3600
TELEGRAM_MAX_AGE = 24 * 3600
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

    def login(self, who: dict) -> dict:
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
            rec.update({"name": who["name"], "seen": now})
            if who.get("chat_id"):
                rec["chat_id"] = who["chat_id"]
            data["listeners"][slug] = rec
            self._save(data)
            return dict(rec)

    def get(self, slug: str) -> Optional[dict]:
        with self._lock:
            rec = self._load()["listeners"].get(slug)
        return dict(rec) if rec else None

    def save_code(self, slug: str, code: str) -> dict:
        if not CODE_RE.match(code or ""):
            raise AccountError("bad_profile")
        with self._lock:
            data = self._load()
            rec = data["listeners"].get(slug)
            if not rec:
                raise AccountError("signed_out", 401)
            rec["code"], rec["saved"] = code, int(self.clock())
            self._save(data)
            return dict(rec)

    def delete(self, slug: str) -> bool:
        with self._lock:
            data = self._load()
            rec = data["listeners"].pop(slug, None)
            if rec:
                data["index"].pop(rec.get("key", ""), None)
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
    return {"slug": rec["slug"], "name": rec.get("name", ""), "provider": rec.get("provider", ""),
            "has_podcast": bool(rec.get("code")), "page": f"/mycast/u/{rec['slug']}",
            "telegram_linked": bool(rec.get("chat_id"))}


def install_mycast_account_routes(app, store: ListenerStore, *, secret: str, bot_token: Callable[[], str],
                                  bot_username: Callable[[], str], google_client_id: Callable[[], str],
                                  google_verify: Callable[[str], dict], secure_cookie: bool = True,
                                  clock: Callable[[], float] = time.time) -> None:
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
        return {"telegram_bot": name or None, "google_client_id": google_client_id() or None}

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
            who = verify_telegram(await _body(request), bot_token(), clock())
            return _signed_in(store.login(who))
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
            return _signed_in(store.login({"provider": "google", "pid": str(claims["sub"]),
                                           "name": _name(claims.get("given_name") or claims.get("name"))}))
        except AccountError as exc:
            return _err(exc)

    @app.post("/api/mycast/account/podcast")
    async def mycast_account_podcast(request: Request):
        try:
            rec = _current(request)
            if not rec:
                raise AccountError("signed_out", 401)
            body = await _body(request)
            return {"listener": public_view(store.save_code(rec["slug"], str(body.get("code") or "")))}
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
            store.delete(rec["slug"])
        except AccountError as exc:
            return _err(exc)
        resp = JSONResponse({"deleted": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    @app.get("/mycast/u/{slug}", include_in_schema=False)
    def mycast_public_page(slug: str):
        rec = store.get(slug) if SLUG_RE.match(slug or "") else None
        if not rec or not rec.get("code"):
            return RedirectResponse(PAGE + "#missing", status_code=307)
        return RedirectResponse(f"{PAGE}#p={rec['code']}&from={slug}", status_code=307)
