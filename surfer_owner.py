"""T-722 Surfer owner page: what waits for the owner, his controls on a live session, approved upload files.

Routes here are owner-only. The page is ``static/surfer/index.html``. ``GET /api/factory/surfer/owner/pending`` is the
list another agent session mirrors onto the owner's task page: each item says in RU/UK/EN what the agent wants to
do and why it waits, with a link to the page and to the screenshot (owner session required to open either).
"""
from __future__ import annotations

import base64
import time
from typing import Any, Callable, Dict, List

from fastapi import HTTPException, Request

from browser_runner import action_policy as policy
import surfer_actions as sa

PAGE = "/static/surfer/index.html"

REASONS = {
    "payment": {"ru": "оплата или покупка", "uk": "оплата або покупка", "en": "payment or purchase"},
    "delete": {"ru": "удаление", "uk": "видалення", "en": "deleting something"},
    "security": {"ru": "настройки безопасности или доступа", "uk": "налаштування безпеки чи доступу",
                 "en": "security or access settings"},
    "messaging": {"ru": "сообщение другим людям", "uk": "повідомлення іншим людям", "en": "a message to other people"},
    "publish": {"ru": "публикация", "uk": "публікація", "en": "publishing"},
    "leaves_allowlist": {"ru": "переход на сайт вне вашего списка", "uk": "перехід на сайт поза вашим списком",
                         "en": "leaving your list of allowed sites"},
    "off_allowlist": {"ru": "действие на сайте вне вашего списка", "uk": "дія на сайті поза вашим списком",
                      "en": "an action on a site outside your list"},
    "class_not_allowed": {"ru": "этот тип действий вы для сайта не включали",
                          "uk": "цей тип дій ви для сайту не вмикали",
                          "en": "you did not switch this kind of action on for the site"},
    "unlabeled_control": {"ru": "кнопка без понятной подписи", "uk": "кнопка без зрозумілого підпису",
                          "en": "a button without a readable label"},
}
WAITS = {
    "captcha": {"ru": "сайт показывает капчу", "uk": "сайт показує капчу", "en": "the site shows a captcha"},
    "bot_challenge": {"ru": "сайт показывает проверку «вы не робот»", "uk": "сайт показує перевірку «ви не робот»",
                      "en": "the site shows an anti-bot check"},
    "2fa": {"ru": "сайт просит код (СМС или приложение)", "uk": "сайт просить код (СМС або застосунок)",
            "en": "the site asks for a code (SMS or app)"},
    "security_challenge": {"ru": "сайт просит проверку безопасности", "uk": "сайт просить перевірку безпеки",
                           "en": "the site asks for a security check"},
    "login_required": {"ru": "нужно войти в аккаунт, сохранённого входа нет",
                       "uk": "потрібно увійти в акаунт, збереженого входу немає",
                       "en": "you need to sign in; there is no saved login"},
    "login_failed": {"ru": "сохранённый вход не сработал", "uk": "збережений вхід не спрацював",
                     "en": "the saved login did not work"},
}
ACTIONS = {
    "click": {"ru": "нажать", "uk": "натиснути", "en": "click"},
    "fill": {"ru": "заполнить поле", "uk": "заповнити поле", "en": "fill the field"},
    "select": {"ru": "выбрать в списке", "uk": "вибрати у списку", "en": "choose in the list"},
    "check": {"ru": "переключить", "uk": "перемкнути", "en": "toggle"},
    "press": {"ru": "нажать клавишу в поле", "uk": "натиснути клавішу в полі", "en": "press a key in"},
    "upload": {"ru": "загрузить файл в", "uk": "завантажити файл у", "en": "upload a file to"},
    "goto": {"ru": "открыть адрес", "uk": "відкрити адресу", "en": "open the address"},
}
TEMPLATES = {
    "confirm": {"ru": "Surfer ({lane}) хочет {action} «{element}» на {site}. Причина остановки: {why}. "
                      "Подтвердите или отклоните на странице Surfer.",
                "uk": "Surfer ({lane}) хоче {action} «{element}» на {site}. Причина зупинки: {why}. "
                      "Підтвердіть або відхиліть на сторінці Surfer.",
                "en": "Surfer ({lane}) wants to {action} “{element}” on {site}. It stopped because of: {why}. "
                      "Confirm or reject it on the Surfer page."},
    "human": {"ru": "Surfer ({lane}) остановился на {site}: {why}. Введите код или нажмите «Взять управление» "
                    "на странице Surfer.",
              "uk": "Surfer ({lane}) зупинився на {site}: {why}. Введіть код або натисніть «Взяти керування» "
                    "на сторінці Surfer.",
              "en": "Surfer ({lane}) stopped on {site}: {why}. Type the code or press “Take over” on the Surfer page."},
    "takeover": {"ru": "Вы управляете страницей {site} сами. Когда закончите, нажмите «Вернуть агенту» на странице "
                       "Surfer.",
                 "uk": "Ви керуєте сторінкою {site} самі. Коли закінчите, натисніть «Повернути агенту» на сторінці "
                       "Surfer.",
                 "en": "You are driving {site} yourself. When you are done, press “Give back to the agent” on the "
                       "Surfer page."},
}


def _iso(ts: Any) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(ts or 0))) if ts else ""


def pending_requests(store: sa.ActionStore) -> List[dict]:
    """Everything that waits for the owner right now, newest first. No values, no secrets."""
    out: List[dict] = []
    now = store.clock()
    for doc in store.list():
        session = doc["session"]
        if session["status"] not in sa.OWNER_WAIT_STATUSES:
            continue
        site = policy.host_of(session.get("url") or session.get("start_url") or "") or "?"
        shot = store.last_shot(doc)
        item: Dict[str, Any] = {
            "session_id": session["id"], "lane": session.get("lane") or "", "agent": session.get("agent") or "",
            "site": site, "url": policy.log_url(session.get("url") or ""), "title": session.get("title") or "",
            "since": _iso(session.get("last_activity")),
            "expires_in_seconds": max(0, int(sa.OWNER_WAIT_SECONDS - (now - float(session.get("last_activity") or now)))),
            "page": PAGE, "screenshot": f"/api/factory/surfer/owner/steps/{shot}/screenshot" if shot else ""}
        fields = {"lane": item["lane"] or "agent", "site": site}
        if session["status"] == "needs_owner_confirmation":
            step = store.pending(doc) or {}
            element = step.get("element") or {}
            reasons = list((step.get("review") or {}).get("reasons") or [])
            action = str(step.get("action") or step.get("kind") or "")
            label = str(element.get("name") or step.get("url") or step.get("selector") or "")[:120]
            item.update(kind="confirm", id=step.get("id") or session["id"], step_id=step.get("id") or "",
                        action=action, element=label, reasons=reasons)
            if step.get("value") not in (None, "") and not element.get("secret") and not step.get("value_from"):
                item["value"] = str(step["value"])[:200]
            item["text"] = {lang: TEMPLATES["confirm"][lang].format(
                action=ACTIONS.get(action, {}).get(lang, action), element=label,
                why=", ".join(REASONS.get(r, {}).get(lang, r) for r in reasons) or "?", **fields)
                for lang in ("ru", "uk", "en")}
        elif session["status"] == "waiting_human":
            reason = str(session.get("wait_reason") or "security_challenge")
            item.update(kind="human", id=session["id"], wait_reason=reason)
            item["text"] = {lang: TEMPLATES["human"][lang].format(
                why=WAITS.get(reason, WAITS["security_challenge"])[lang], **fields) for lang in ("ru", "uk", "en")}
        else:
            item.update(kind="takeover", id=session["id"])
            item["text"] = {lang: TEMPLATES["takeover"][lang].format(**fields) for lang in ("ru", "uk", "en")}
        out.append(item)
    return out


def install_routes(app, *, store: sa.ActionStore, gate: Any, identity: Callable) -> None:
    def owner(request: Request) -> None:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def session_view(session_id: str) -> dict:
        doc = store.get(session_id)
        if not doc:
            raise HTTPException(404, "unknown session")
        view = sa.owner_session_view(store, doc)
        view["screen"] = store.last_shot(doc)
        return view

    @app.get("/api/factory/surfer/owner/pending")
    def surfer_owner_pending(request: Request):
        owner(request)
        return {"pending": pending_requests(store), "gate": gate.status(), "page": PAGE}

    @app.get("/api/factory/surfer/owner/sessions/{session_id}")
    def surfer_owner_session(session_id: str, request: Request):
        owner(request)
        return {"session": session_view(session_id)}

    @app.post("/api/factory/surfer/owner/sessions/{session_id}/takeover")
    async def surfer_owner_takeover(session_id: str, request: Request):
        owner(request)
        store.set_takeover(session_id, (await body_of(request)).get("on") is not False)
        return {"session": session_view(session_id)}

    @app.post("/api/factory/surfer/owner/sessions/{session_id}/input")
    async def surfer_owner_input(session_id: str, request: Request):
        """A code or a short text the page asks the owner for. Kept in memory until the worker takes it; never stored."""
        owner(request)
        body = await body_of(request)
        step = store.owner_command(session_id, "human_input", body)
        return {"step": {"id": step["id"], "status": step["status"]}}

    @app.post("/api/factory/surfer/owner/sessions/{session_id}/control")
    async def surfer_owner_control(session_id: str, request: Request):
        owner(request)
        body = await body_of(request)
        kind = {"click": "takeover_click", "type": "takeover_type", "key": "takeover_key", "scroll": "takeover_scroll",
                "refresh": "snapshot", "save_login": "save_login"}.get(str(body.get("kind") or ""))
        if not kind:
            raise HTTPException(404, "unknown control")
        step = store.owner_command(session_id, kind, body)
        return {"step": {"id": step["id"], "status": step["status"]}}

    @app.get("/api/factory/surfer/owner/steps/{step_id}")
    def surfer_owner_step(step_id: str, request: Request):
        owner(request)
        doc, step = store.find_step(step_id)
        if not doc:
            raise HTTPException(404, "unknown step")
        return {"step": {k: step[k] for k in ("id", "kind", "status", "blocker", "screenshot", "saved") if k in step},
                "session_status": doc["session"]["status"]}

    @app.get("/api/factory/surfer/owner/uploads")
    def surfer_owner_uploads(request: Request):
        owner(request)
        return {"uploads": gate.uploads()}

    @app.post("/api/factory/surfer/owner/uploads")
    async def surfer_owner_upload(request: Request):
        owner(request)
        body = await body_of(request)
        try:
            raw = base64.b64decode(str(body.get("data_b64") or ""), validate=True)
        except ValueError:
            raise HTTPException(400, "data_b64 is not base64")
        row = gate.add_upload(str(body.get("name") or ""), raw)
        store.audit(who="owner", action="upload_approve", element=row["name"], value=row["id"])
        return {"upload": row, "uploads": gate.uploads()}

    @app.post("/api/factory/surfer/owner/uploads/{asset_id}/delete")
    def surfer_owner_upload_delete(asset_id: str, request: Request):
        owner(request)
        if not gate.remove_upload(asset_id):
            raise HTTPException(404, "unknown file")
        store.audit(who="owner", action="upload_remove", value=asset_id)
        return {"uploads": gate.uploads()}
