"""T-712: "Forgot password?" on the FactoryOS login page (owner 2026-11-20: «добавь кнопку восстановить пароль»).

The password is the `FACTORY_PASSWORD` secret on Render: the app cannot show it or change it. So recovery does not
touch the password at all. The owner asks for a one-time sign-in link from the Telegram chat already paired with
FactoryOS:

* the login page button only opens a page of instructions ("send /login to your FactoryOS bot"). Nothing on the public
  site can request, replace or use up a link, so a visitor cannot spam the owner's chat or block recovery;
* the link is made only when `/login` arrives through the authenticated Telegram webhook from the paired chat, and only
  if that chat is private and the sender is the chat's own user (a group can never get a link);
* the secret sits in the URL fragment (`/login/recover#<token>`), which browsers do not send: it is not in any request
  URL, so not in access logs, a link preview or a Referer. The page POSTs it in the form body after the owner presses
  the button; anything that records request bodies would see it there (FactoryOS runs no such tracing);
* one link at a time, valid TTL_SECONDS, usable once; only its SHA-256 is kept, in a file under DATA_DIR that is
  replaced and consumed under a file lock, so every process on that disk sees the same single link;
* `FACTORY_LOGIN_RECOVERY_ENABLED=0` turns it off (the button disappears, the routes answer 404, `/login` is ignored).
"""
from __future__ import annotations

import fcntl
import hashlib
import hmac
import html
import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from fastapi import Form
from fastapi.responses import HTMLResponse

TTL_SECONDS = 600
LANGS = ("en", "uk", "ru")
COMMAND = "/login"

T = {
    "en": {"forgot": "Forgot password?", "title": "Sign in without the password",
           "how": "Open your FactoryOS bot chat in Telegram and send the command /login. The bot answers with a one-time "
                  "sign-in link: it works for 10 minutes and only once. It answers only in the private chat that is "
                  "paired with FactoryOS.",
           "password": "The password itself is stored only in Render (Environment → FACTORY_PASSWORD): it can be read or "
                       "changed there, not here. Google sign-in on the login page also works without the password.",
           "back": "Back to sign-in", "confirm": "Sign in as the owner",
           "confirm_sub": "This link came from your FactoryOS Telegram chat. It works once.",
           "bad": "This link is no longer valid: it was already used or it expired. Send /login to the bot again.",
           "message": "FactoryOS: one-time sign-in link (valid 10 minutes, works once). Do not forward it.\n{url}"},
    "uk": {"forgot": "Забули пароль?", "title": "Вхід без пароля",
           "how": "Відкрийте чат зі своїм ботом FactoryOS у Telegram і надішліть команду /login. Бот відповість "
                  "одноразовим посиланням для входу: воно діє 10 хвилин і лише один раз. Бот відповідає тільки в "
                  "особистому чаті, з’єднаному з FactoryOS.",
           "password": "Сам пароль зберігається лише в Render (Environment → FACTORY_PASSWORD): подивитися або змінити "
                       "його можна там, не тут. Вхід через Google на сторінці входу теж працює без пароля.",
           "back": "Назад до входу", "confirm": "Увійти як власник",
           "confirm_sub": "Це посилання надійшло з вашого чату FactoryOS у Telegram. Воно діє один раз.",
           "bad": "Посилання вже не діє: його використали або минув час. Надішліть боту /login ще раз.",
           "message": "FactoryOS: одноразове посилання для входу (діє 10 хвилин, один раз). Не пересилайте його.\n{url}"},
    "ru": {"forgot": "Забыли пароль?", "title": "Вход без пароля",
           "how": "Откройте чат со своим ботом FactoryOS в Telegram и отправьте команду /login. Бот ответит одноразовой "
                  "ссылкой для входа: она действует 10 минут и только один раз. Бот отвечает только в личном чате, "
                  "связанном с FactoryOS.",
           "password": "Сам пароль хранится только в Render (Environment → FACTORY_PASSWORD): посмотреть или сменить "
                       "его можно там, не здесь. Вход через Google на странице входа тоже работает без пароля.",
           "back": "Назад ко входу", "confirm": "Войти как владелец",
           "confirm_sub": "Эта ссылка пришла из вашего чата FactoryOS в Telegram. Она действует один раз.",
           "bad": "Ссылка больше не действует: её уже использовали или вышло время. Отправьте боту /login ещё раз.",
           "message": "FactoryOS: одноразовая ссылка для входа (действует 10 минут, один раз). Не пересылайте её.\n{url}"},
}


def enabled() -> bool:
    return os.environ.get("FACTORY_LOGIN_RECOVERY_ENABLED", "1").strip() != "0"


def _lang(value: str) -> str:
    return value if value in LANGS else "en"


def link_html(lang: str) -> str:
    """The "Forgot password?" link for the login page; empty when recovery is off. It only opens the instructions."""
    if not enabled():
        return ""
    lang = _lang(lang)
    return f"<p class='forgot'><a href='/login/recover?lang={lang}'>{html.escape(T[lang]['forgot'])}</a></p>"


def owner_private_command(message: dict, owner_chat: str) -> bool:
    """True only for `/login` sent in the private chat paired with FactoryOS, by that chat's own user."""
    if not isinstance(message, dict) or not owner_chat:
        return False
    chat = message.get("chat") if isinstance(message.get("chat"), dict) else {}
    sender = message.get("from") if isinstance(message.get("from"), dict) else {}
    text = str(message.get("text") or "").strip()
    command = text.split(maxsplit=1)[0].split("@", 1)[0].lower() if text.startswith("/") else ""
    chat_id = str(chat.get("id") or "")
    return (command == COMMAND and chat.get("type") == "private" and chat_id == str(owner_chat)
            and not chat_id.startswith("-") and str(sender.get("id") or "") == chat_id and sender.get("is_bot") is not True)


class LoginRecovery:
    """The one pending link. With `state_path` (a file under DATA_DIR) the pending link is shared by every process on
    that disk and replaced / consumed under a file lock; without it the state is in memory (tests)."""

    def __init__(self, *, base_url: Callable[[], str], clock: Callable[[], float] = time.time,
                 log: Callable[[str], None] = lambda line: print(line, flush=True), state_path: Optional[Path] = None):
        self.base_url, self.clock, self.log = base_url, clock, log
        self.state_path = Path(state_path) if state_path else None
        self._lock = threading.Lock()
        self._memory = {"hash": "", "expires": 0.0}

    def _update(self, fn):
        """Run fn(state) -> (result, new_state or None) atomically across threads and processes."""
        with self._lock:
            if not self.state_path:
                result, new = fn(dict(self._memory))
                if new is not None:
                    self._memory = new
                return result
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with open(str(self.state_path) + ".lock", "w") as guard:
                fcntl.flock(guard, fcntl.LOCK_EX)
                try:
                    try:
                        raw = json.loads(self.state_path.read_text(encoding="utf-8"))
                        state = {"hash": str(raw.get("hash") or ""), "expires": float(raw.get("expires") or 0)}
                    except (OSError, ValueError, AttributeError, TypeError):
                        state = {"hash": "", "expires": 0.0}
                    result, new = fn(state)
                    if new is not None:
                        tmp = Path(str(self.state_path) + ".tmp")
                        tmp.write_text(json.dumps(new), encoding="utf-8")
                        os.chmod(tmp, 0o600)
                        os.replace(tmp, self.state_path)
                    return result
                finally:
                    fcntl.flock(guard, fcntl.LOCK_UN)

    @property
    def pending_hash(self) -> str:
        return self._update(lambda state: (state["hash"], None))

    def clear(self) -> None:
        self._update(lambda state: (None, {"hash": "", "expires": 0.0}))

    def issue(self, lang: str = "ru") -> str:
        """A new one-time link (the older one stops working). Call only for a verified owner_private_command."""
        token = secrets.token_urlsafe(32)
        fresh = {"hash": hashlib.sha256(token.encode("utf-8")).hexdigest(), "expires": self.clock() + TTL_SECONDS}
        self._update(lambda state: (None, fresh))
        self.log(json.dumps({"event": "LOGIN_RECOVERY_ISSUED"}))
        return f"{self.base_url()}/login/recover?lang={_lang(lang)}#{token}"

    def message(self, lang: str = "ru") -> str:
        return T[_lang(lang)]["message"].format(url=self.issue(lang))

    def _take(self, token: str):
        def fn(state):
            return (True, {"hash": "", "expires": 0.0}) if self._match(state, token) else (False, None)
        return self._update(fn)

    def revoke(self, url_or_token: str) -> None:
        """Drop the link if it is still the current one (its message could not be delivered)."""
        self._take(str(url_or_token or "").rsplit("#", 1)[-1].strip())

    def consume(self, token: str) -> bool:
        """True once for a live link; the link is gone afterwards."""
        ok = self._take(token)
        if ok:
            self.log(json.dumps({"event": "LOGIN_RECOVERY_USED"}))
        return ok

    def _match(self, state: dict, token: str) -> bool:
        if not state["hash"] or self.clock() > state["expires"] or not isinstance(token, str) or not 20 <= len(token) <= 100:
            return False
        return hmac.compare_digest(hashlib.sha256(token.encode("utf-8")).hexdigest(), state["hash"])


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


# Reads the secret from the URL fragment (never sent to the server), removes it from the address bar and history,
# and shows the confirmation button. Without a fragment the page is just the instructions.
PAGE_JS = ("(function(){var t=(location.hash||'').slice(1);if(!/^[A-Za-z0-9_-]{20,100}$/.test(t))return;"
           "try{history.replaceState(null,'',location.pathname+location.search)}catch(e){}"
           "document.getElementById('tok').value=t;document.getElementById('use').hidden=false;"
           "document.getElementById('how').hidden=true})();")


def install_login_recovery_routes(app, recovery: LoginRecovery, *, sign_in: Callable[[str], object]) -> None:
    """`sign_in(lang)` returns the response that sets the owner session cookie (the same one the password login uses)."""
    def _off():
        return HTMLResponse("Not found", status_code=404)

    def _back(lang: str) -> str:
        return f"<p><a href='/login?lang={lang}'>← {html.escape(T[lang]['back'])}</a></p>"

    @app.get("/login/recover", include_in_schema=False)
    def login_recover_page(lang: str = "en"):
        if not enabled():
            return _off()
        lang = _lang(lang)
        t = T[lang]
        return _page(lang, t["title"],
                     f"<div id='how'><p>{html.escape(t['how'])}</p><p>{html.escape(t['password'])}</p></div>"
                     f"<form id='use' method='post' action='/login/recover' hidden><p>{html.escape(t['confirm_sub'])}</p>"
                     f"<input type='hidden' name='lang' value='{lang}'><input type='hidden' name='token' id='tok' value=''>"
                     f"<button type='submit'>{html.escape(t['confirm'])}</button></form>{_back(lang)}<script>{PAGE_JS}</script>")

    @app.post("/login/recover", include_in_schema=False)
    def login_recover_use(token: str = Form(""), lang: str = Form("en")):
        if not enabled():
            return _off()
        lang = _lang(lang)
        if not recovery.consume(token):
            return _page(lang, T[lang]["title"], f"<p>{html.escape(T[lang]['bad'])}</p>{_back(lang)}", status=410)
        return sign_in(lang)
