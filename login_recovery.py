"""T-712: "Forgot password?" on the FactoryOS login page (owner 2026-11-20: «добавь кнопку восстановить пароль»).

The password is the `FACTORY_PASSWORD` secret on Render: the app cannot show it or change it. So recovery does not
touch the password at all. It sends a one-time sign-in link to the Telegram chat the owner already paired with FactoryOS:

* the link is sent only to that paired chat, never shown on the page, in logs or in an API answer;
* the page says the same thing whether or not a link was sent (it never confirms that a chat is paired);
* one link at a time, valid TTL_SECONDS, usable once; only its SHA-256 is kept, in memory (a restart drops it);
* opening the link shows a confirmation page; only the POST from that page signs in, so a link preview cannot use it up
  or be signed in;
* at most one request per MIN_INTERVAL_SECONDS and DAILY_CAP per UTC day, so the button cannot spam the owner's chat;
* `FACTORY_LOGIN_RECOVERY_ENABLED=0` turns it off (the button disappears, the routes answer 404).
"""
from __future__ import annotations

import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from typing import Callable

from fastapi import Form
from fastapi.responses import HTMLResponse

TTL_SECONDS = 600
MIN_INTERVAL_SECONDS = 120
DAILY_CAP = 5
LANGS = ("en", "uk", "ru")

T = {
    "en": {"forgot": "Forgot password?", "title": "Sign in without the password",
           "sent": "If a Telegram chat is paired with FactoryOS, a one-time sign-in link was just sent there. "
                   "It works for 10 minutes and only once.",
           "wait": "A link was requested a moment ago. Check Telegram, or try again in a couple of minutes.",
           "password": "The password itself is stored only in Render (Environment → FACTORY_PASSWORD): it can be read or "
                       "changed there, not here. Google sign-in on the login page also works without the password.",
           "back": "Back to sign-in", "confirm_title": "Sign in to FactoryOS", "confirm": "Sign in as the owner",
           "confirm_sub": "This link came from your FactoryOS Telegram chat. It works once.",
           "bad": "This link is no longer valid: it was already used or it expired. Request a new one.",
           "message": "FactoryOS: one-time sign-in link (valid 10 minutes, works once). "
                      "If you did not ask for it, ignore this message — nothing changes.\n{url}"},
    "uk": {"forgot": "Забули пароль?", "title": "Вхід без пароля",
           "sent": "Якщо з FactoryOS з’єднано чат у Telegram, туди щойно надіслано одноразове посилання для входу. "
                   "Воно діє 10 хвилин і лише один раз.",
           "wait": "Посилання вже запитували щойно. Перевірте Telegram або спробуйте ще раз за кілька хвилин.",
           "password": "Сам пароль зберігається лише в Render (Environment → FACTORY_PASSWORD): подивитися або змінити "
                       "його можна там, не тут. Вхід через Google на сторінці входу теж працює без пароля.",
           "back": "Назад до входу", "confirm_title": "Вхід до FactoryOS", "confirm": "Увійти як власник",
           "confirm_sub": "Це посилання надійшло з вашого чату FactoryOS у Telegram. Воно діє один раз.",
           "bad": "Посилання вже не діє: його використали або минув час. Запросіть нове.",
           "message": "FactoryOS: одноразове посилання для входу (діє 10 хвилин, один раз). "
                      "Якщо ви його не просили, просто не відкривайте — нічого не зміниться.\n{url}"},
    "ru": {"forgot": "Забыли пароль?", "title": "Вход без пароля",
           "sent": "Если с FactoryOS связан чат в Telegram, туда только что отправлена одноразовая ссылка для входа. "
                   "Она действует 10 минут и только один раз.",
           "wait": "Ссылку уже запрашивали только что. Проверьте Telegram или попробуйте ещё раз через пару минут.",
           "password": "Сам пароль хранится только в Render (Environment → FACTORY_PASSWORD): посмотреть или сменить "
                       "его можно там, не здесь. Вход через Google на странице входа тоже работает без пароля.",
           "back": "Назад ко входу", "confirm_title": "Вход в FactoryOS", "confirm": "Войти как владелец",
           "confirm_sub": "Эта ссылка пришла из вашего чата FactoryOS в Telegram. Она действует один раз.",
           "bad": "Ссылка больше не действует: её уже использовали или вышло время. Запросите новую.",
           "message": "FactoryOS: одноразовая ссылка для входа (действует 10 минут, один раз). "
                      "Если вы её не запрашивали, просто не открывайте — ничего не изменится.\n{url}"},
}


def enabled() -> bool:
    return os.environ.get("FACTORY_LOGIN_RECOVERY_ENABLED", "1").strip() != "0"


def _lang(value: str) -> str:
    return value if value in LANGS else "en"


def link_html(lang: str) -> str:
    """The "Forgot password?" button for the login page; empty when recovery is off."""
    if not enabled():
        return ""
    lang = _lang(lang)
    return (f"<form method='post' action='/login/recover' class='forgot'><input type='hidden' name='lang' value='{lang}'>"
            f"<button type='submit' class='linkBtn'>{html.escape(T[lang]['forgot'])}</button></form>")


class LoginRecovery:
    def __init__(self, *, send: Callable[[str], bool], base_url: Callable[[], str], clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] = lambda line: print(line, flush=True)):
        self.send, self.base_url, self.clock, self.log = send, base_url, clock, log
        self._lock = threading.Lock()
        self._token_hash = ""
        self._expires = 0.0
        self._last = 0.0
        self._day, self._count = "", 0

    def request(self, lang: str) -> str:
        """Ask for a link. Returns "sent" (the same whether or not a chat is paired) or "wait" (rate limited)."""
        now = self.clock()
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self._lock:
            if day != self._day:
                self._day, self._count = day, 0
            if now - self._last < MIN_INTERVAL_SECONDS or self._count >= DAILY_CAP:
                return "wait"
            self._last, self._count = now, self._count + 1
            token = secrets.token_urlsafe(32)
            self._token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
            self._expires = now + TTL_SECONDS
        url = f"{self.base_url()}/login/recover/{token}?lang={_lang(lang)}"
        try:
            delivered = bool(self.send(T[_lang(lang)]["message"].format(url=url)))
        except Exception:
            delivered = False
        if not delivered:                                   # no paired chat or Telegram failed: no usable link stays
            with self._lock:
                self._token_hash, self._expires = "", 0.0
        self.log(json.dumps({"event": "LOGIN_RECOVERY_REQUESTED", "delivered": delivered}))
        return "sent"

    def valid(self, token: str) -> bool:
        with self._lock:
            return self._match(token)

    def consume(self, token: str) -> bool:
        """True once for a live link; the link is gone afterwards."""
        with self._lock:
            ok = self._match(token)
            if ok:
                self._token_hash, self._expires = "", 0.0
        if ok:
            self.log(json.dumps({"event": "LOGIN_RECOVERY_USED"}))
        return ok

    def _match(self, token: str) -> bool:
        if not self._token_hash or self.clock() > self._expires or not isinstance(token, str) or not 20 <= len(token) <= 100:
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode("utf-8")).hexdigest(), self._token_hash)


CSS = ("body{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(700px 420px at 50% 0,#163f6255,"
       "transparent 65%),#07101b;color:#fff;font:15px/1.5 Inter,system-ui,Arial}.box{width:min(430px,90vw);background:linear-gradient("
       "180deg,#0e1d2d,#0a1522);border:1px solid #284963;border-radius:20px;padding:28px;box-shadow:0 24px 80px #000a}"
       "h1{margin:0 0 12px;font-size:22px}p{color:#b6c5d4;margin:0 0 12px}a{color:#5cc8ff}"
       "button{width:100%;margin:6px 0 14px;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#1677ff,#0db7f5);"
       "color:#fff;font-weight:800;font-size:15px;cursor:pointer}")


def _page(lang: str, title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(
        f"<!doctype html><html lang='{lang}'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<meta name='robots' content='noindex,nofollow'><meta name='referrer' content='no-referrer'><title>{html.escape(title)}</title>"
        f"<style>{CSS}</style></head><body><div class='box'><h1>{html.escape(title)}</h1>{body}</div></body></html>",
        status_code=status, headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})


def install_login_recovery_routes(app, recovery: LoginRecovery, *, sign_in: Callable[[str], object]) -> None:
    """`sign_in(lang)` returns the response that sets the owner session cookie (the same one the password login uses)."""
    def _off():
        return HTMLResponse("Not found", status_code=404)

    def _back(lang: str) -> str:
        return f"<p><a href='/login?lang={lang}'>← {html.escape(T[lang]['back'])}</a></p>"

    @app.post("/login/recover", include_in_schema=False)
    def login_recover_request(lang: str = Form("en")):
        if not enabled():
            return _off()
        lang = _lang(lang)
        t = T[lang]
        result = recovery.request(lang)
        return _page(lang, t["title"], f"<p>{html.escape(t[result])}</p><p>{html.escape(t['password'])}</p>{_back(lang)}",
                     status=429 if result == "wait" else 200)

    @app.get("/login/recover/{token}", include_in_schema=False)
    def login_recover_open(token: str, lang: str = "en"):
        if not enabled():
            return _off()
        lang = _lang(lang)
        t = T[lang]
        if not recovery.valid(token):
            return _page(lang, t["confirm_title"], f"<p>{html.escape(t['bad'])}</p>{_back(lang)}", status=410)
        return _page(lang, t["confirm_title"],
                     f"<p>{html.escape(t['confirm_sub'])}</p><form method='post' action='/login/recover/{html.escape(token)}'>"
                     f"<input type='hidden' name='lang' value='{lang}'><button type='submit'>{html.escape(t['confirm'])}</button></form>{_back(lang)}")

    @app.post("/login/recover/{token}", include_in_schema=False)
    def login_recover_use(token: str, lang: str = Form("en")):
        if not enabled():
            return _off()
        lang = _lang(lang)
        if not recovery.consume(token):
            return _page(lang, T[lang]["confirm_title"], f"<p>{html.escape(T[lang]['bad'])}</p>{_back(lang)}", status=410)
        return sign_in(lang)
