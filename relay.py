"""FactoryOS Relay — persistent mobile inbox/task layer for Telegram and web.

Zero external dependencies beyond FastAPI/Pydantic already used by FactoryOS.
The store is intentionally file-backed on DATA_DIR so it survives Render restarts
on the existing persistent disk and stays independent from the production DB schema.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

RELAY_STATUSES = ("inbox", "in_progress", "need_you", "done", "archived")
ACTIVE_STATUSES = ("inbox", "in_progress", "need_you")
STATUS_LABELS = {
    "inbox": "📥 Inbox",
    "in_progress": "▶️ В работе",
    "need_you": "🙋 Нужно от тебя",
    "done": "✅ Готово",
    "archived": "🗄 Архив",
}
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: object, limit: int = 12000) -> str:
    return " ".join(str(value or "").replace("\x00", "").split())[:limit]


def _first_url(text: str) -> str:
    match = URL_RE.search(text or "")
    return match.group(0).rstrip(".,;:!?)]}") if match else ""


class RelayStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _empty(self) -> dict:
        return {"version": 1, "seq": 0, "tickets": []}

    def _load_unlocked(self) -> dict:
        if not self.path.exists():
            return self._empty()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return self._empty()
        if not isinstance(value, dict):
            return self._empty()
        value.setdefault("version", 1)
        value.setdefault("seq", 0)
        value.setdefault("tickets", [])
        if not isinstance(value["tickets"], list):
            value["tickets"] = []
        return value

    def _save_unlocked(self, state: dict) -> None:
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def summary(self) -> dict:
        with self.lock:
            items = list(self._load_unlocked()["tickets"])
        counts = {status: sum(1 for x in items if x.get("status") == status) for status in RELAY_STATUSES}
        return {
            "total": len(items),
            "active": sum(counts[x] for x in ACTIVE_STATUSES),
            "needs_you": counts["need_you"],
            **counts,
        }

    def list(self, status: str = "", limit: int = 200, active_only: bool = False) -> list[dict]:
        status = (status or "").strip().lower()
        if status and status not in RELAY_STATUSES:
            raise ValueError("Unknown Relay status")
        with self.lock:
            items = [dict(x) for x in self._load_unlocked()["tickets"] if isinstance(x, dict)]
        if status:
            items = [x for x in items if x.get("status") == status]
        if active_only:
            items = [x for x in items if x.get("status") in ACTIVE_STATUSES]
        items.sort(key=lambda x: (x.get("updated_at") or "", x.get("created_at") or ""), reverse=True)
        return items[: max(1, min(500, int(limit or 200)))]

    def get(self, ticket_id: str) -> Optional[dict]:
        ticket_id = str(ticket_id or "").strip().upper()
        with self.lock:
            for item in self._load_unlocked()["tickets"]:
                if str(item.get("id") or "").upper() == ticket_id:
                    return dict(item)
        return None

    def create(
        self,
        title: str,
        body: str = "",
        source: Optional[dict] = None,
        created_by: str = "owner",
        priority: str = "normal",
    ) -> tuple[dict, bool]:
        source = dict(source or {})
        source_key = str(source.get("source_key") or "").strip()
        with self.lock:
            state = self._load_unlocked()
            if source_key:
                for existing in state["tickets"]:
                    if str((existing.get("source") or {}).get("source_key") or "") == source_key:
                        return dict(existing), False
            state["seq"] = int(state.get("seq") or 0) + 1
            ticket_id = f"R-{state['seq']:04d}"
            now = _now()
            clean_body = str(body or "").strip()[:20000]
            clean_title = _clean_text(title, 180) or _clean_text(clean_body, 180) or "Новая задача"
            item = {
                "id": ticket_id,
                "title": clean_title,
                "body": clean_body,
                "status": "inbox",
                "priority": (priority or "normal").strip().lower()[:24],
                "created_by": (created_by or "owner").strip()[:80],
                "created_at": now,
                "updated_at": now,
                "source": source,
                "notes": [],
                "history": [{
                    "at": now,
                    "actor": (created_by or "owner").strip()[:80],
                    "action": "created",
                    "from_status": None,
                    "to_status": "inbox",
                    "note": "",
                }],
                "operator": {
                    "state": "not_requested",
                    "requires_confirmation": False,
                    "confirmation_reason": "",
                },
            }
            state["tickets"].append(item)
            self._save_unlocked(state)
            return dict(item), True

    def set_status(self, ticket_id: str, status: str, actor: str = "owner", note: str = "") -> dict:
        status = (status or "").strip().lower()
        if status not in RELAY_STATUSES:
            raise ValueError("Unknown Relay status")
        ticket_id = str(ticket_id or "").strip().upper()
        with self.lock:
            state = self._load_unlocked()
            for item in state["tickets"]:
                if str(item.get("id") or "").upper() != ticket_id:
                    continue
                before = item.get("status") or "inbox"
                now = _now()
                item["status"] = status
                item["updated_at"] = now
                item.setdefault("history", []).append({
                    "at": now,
                    "actor": (actor or "owner").strip()[:80],
                    "action": "status_changed",
                    "from_status": before,
                    "to_status": status,
                    "note": str(note or "")[:1000],
                })
                self._save_unlocked(state)
                return dict(item)
        raise KeyError(ticket_id)

    def add_note(self, ticket_id: str, text: str, actor: str = "owner", kind: str = "note") -> dict:
        ticket_id = str(ticket_id or "").strip().upper()
        note_text = str(text or "").strip()
        if not note_text:
            raise ValueError("Note text is required")
        with self.lock:
            state = self._load_unlocked()
            for item in state["tickets"]:
                if str(item.get("id") or "").upper() != ticket_id:
                    continue
                now = _now()
                note = {"at": now, "actor": (actor or "owner")[:80], "kind": (kind or "note")[:40], "text": note_text[:12000]}
                item.setdefault("notes", []).append(note)
                item.setdefault("history", []).append({
                    "at": now,
                    "actor": note["actor"],
                    "action": "note_added",
                    "from_status": item.get("status"),
                    "to_status": item.get("status"),
                    "note": note_text[:1000],
                })
                item["updated_at"] = now
                self._save_unlocked(state)
                return dict(item)
        raise KeyError(ticket_id)


class RelayCreateRequest(BaseModel):
    title: str
    body: str = ""
    source_url: str = ""
    priority: str = "normal"


class RelayStatusRequest(BaseModel):
    status: str
    note: str = ""


class RelayNoteRequest(BaseModel):
    text: str
    kind: str = "note"


def _owner_guard(request: Request, request_identity: Callable) -> dict:
    identity = request_identity(request) or {}
    if identity.get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    return identity


def _operator_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "🟠 Claude", "callback_data": "relay:operator:claude"},
                {"text": "🔵 Gemini", "callback_data": "relay:operator:gemini"},
            ],
            [{"text": "📋 Все открытые тикеты", "callback_data": "relay:list:active"}],
        ]
    }


def _ticket_keyboard(ticket_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "▶️ В работу", "callback_data": f"relay:status:{ticket_id}:in_progress"},
                {"text": "🙋 Нужно от меня", "callback_data": f"relay:status:{ticket_id}:need_you"},
            ],
            [
                {"text": "✅ Готово", "callback_data": f"relay:status:{ticket_id}:done"},
                {"text": "↩️ Inbox", "callback_data": f"relay:status:{ticket_id}:inbox"},
            ],
            [
                {"text": "🟠 Claude", "callback_data": "relay:operator:claude"},
                {"text": "🔵 Gemini", "callback_data": "relay:operator:gemini"},
            ],
            [{"text": "📋 Мои задачи", "callback_data": "relay:list:active"}],
        ]
    }


def _ticket_card(ticket: dict) -> str:
    source = ticket.get("source") or {}
    link = str(source.get("url") or "").strip()
    attachment = source.get("attachment") or {}
    lines = [
        f"📡 {ticket.get('id')}",
        STATUS_LABELS.get(ticket.get("status"), ticket.get("status") or ""),
        str(ticket.get("title") or ""),
    ]
    if link:
        lines.append(link)
    if attachment:
        lines.append(f"📎 {attachment.get('kind') or 'attachment'} сохранён в тикете")
    notes = ticket.get("notes") or []
    if notes:
        lines.append(f"📝 Заметок: {len(notes)}")
    return "\n".join(x for x in lines if x)


def _active_list_text(store: RelayStore) -> str:
    items = store.list(active_only=True, limit=30)
    if not items:
        return "📡 FactoryOS Relay\n\nАктивных задач нет."
    groups = []
    for status in ACTIVE_STATUSES:
        rows = [x for x in items if x.get("status") == status]
        if not rows:
            continue
        groups.append(STATUS_LABELS[status])
        groups.extend(f"{x['id']} · {x['title'][:90]}" for x in rows[:12])
        groups.append("")
    return "📡 FactoryOS Relay\n\n" + "\n".join(groups).strip()


def _operator_lane_text(name: str, provider: Optional[Callable[[], dict]]) -> str:
    key=(name or "").strip().lower()
    label={"claude":"🟠 Claude","gemini":"🔵 Gemini"}.get(key,key.title() or "Operator")
    if provider is None:
        return f"{label}\n\nСтатус пока не подключён к FactoryOS."
    try:
        lanes=provider() or {}
    except Exception as exc:
        return f"{label}\n\n⚠️ Статус недоступен: {str(exc)[:160]}"
    lane=lanes.get(key) if isinstance(lanes,dict) else None
    lane=lane if isinstance(lane,dict) else {}
    online=lane.get("online") is True
    state=str(lane.get("state") or ("online" if online else "offline"))
    lines=[label, f"Статус: {'🟢 online' if online else '⚪ '+state}"]
    task=str(lane.get("active_task_id") or lane.get("task_id") or "").strip()
    if task:
        lines.append(f"Текущая задача: {task}")
    branch=str(lane.get("branch") or "").strip()
    if branch:
        lines.append(f"Ветка: {branch}")
    stage=str(lane.get("stage") or "").strip()
    if stage:
        lines.append(f"Этап: {stage}")
    queue=lane.get("queue_depth")
    if queue is not None:
        lines.append(f"Очередь: {queue}")
    tickets=lane.get("tickets") or []
    if isinstance(tickets,list) and tickets:
        lines.append("")
        lines.append("Открытые тикеты:")
        for item in tickets[:10]:
            if isinstance(item,dict):
                tid=str(item.get("id") or item.get("task_id") or "").strip()
                title=str(item.get("title") or "").strip()
                lines.append(f"• {tid}{' · ' if tid and title else ''}{title}"[:180])
            else:
                lines.append(f"• {str(item)[:160]}")
    last=str(lane.get("last_result") or lane.get("summary") or "").strip()
    if last:
        lines.extend(["",f"Последний результат: {last[:500]}"])
    return "\n".join(lines)


def _operators_overview_text(provider: Optional[Callable[[], dict]]) -> str:
    if provider is None:
        return "🧠 Operators\n\nClaude: статус не подключён\nGemini: статус не подключён"
    try:
        lanes=provider() or {}
    except Exception as exc:
        return f"🧠 Operators\n\n⚠️ Статус недоступен: {str(exc)[:160]}"
    rows=["🧠 FactoryOS Operators"]
    for key,label in (("claude","🟠 Claude"),("gemini","🔵 Gemini")):
        lane=(lanes.get(key) or {}) if isinstance(lanes,dict) else {}
        online=lane.get("online") is True
        state=str(lane.get("state") or ("online" if online else "offline"))
        task=str(lane.get("active_task_id") or lane.get("task_id") or "").strip()
        rows.append(f"{label}: {'🟢 online' if online else '⚪ '+state}{' · '+task if task else ''}")
    return "\n".join(rows)


def _telegram_attachment(message: dict) -> dict:
    for kind in ("voice", "audio", "video", "video_note", "document", "animation"):
        raw = message.get(kind)
        if isinstance(raw, dict):
            return {
                "kind": kind,
                "file_id": raw.get("file_id"),
                "file_unique_id": raw.get("file_unique_id"),
                "duration": raw.get("duration"),
                "mime_type": raw.get("mime_type"),
                "file_name": raw.get("file_name"),
                "file_size": raw.get("file_size"),
            }
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        raw = photos[-1] if isinstance(photos[-1], dict) else {}
        return {
            "kind": "photo",
            "file_id": raw.get("file_id"),
            "file_unique_id": raw.get("file_unique_id"),
            "width": raw.get("width"),
            "height": raw.get("height"),
            "file_size": raw.get("file_size"),
        }
    return {}


def _telegram_title(text: str, attachment: dict) -> str:
    clean = _clean_text(text, 180)
    if clean:
        url = _first_url(clean)
        if url and clean == url:
            host = urlparse(url).netloc or "link"
            return f"Проверить ссылку · {host}"
        return clean
    kind = attachment.get("kind")
    return {
        "voice": "Голосовое сообщение",
        "audio": "Аудио",
        "video": "Видео",
        "video_note": "Видеосообщение",
        "document": f"Файл · {attachment.get('file_name') or 'document'}",
        "photo": "Фото",
        "animation": "Анимация",
    }.get(kind, "Новая задача")


def relay_handle_telegram_update(
    update: dict,
    store: RelayStore,
    load_pair_state: Callable[[], dict],
    telegram_api: Callable[[str, Optional[dict]], dict],
    operator_status_provider: Optional[Callable[[], dict]] = None,
) -> Optional[dict]:
    """Handle Relay-specific Telegram traffic.

    Returns {"handled": True, ...} when app.py should stop processing the update.
    For ordinary text messages it creates a Relay ticket but returns handled=False
    so the legacy bridge inbox still receives the text for agent-side processing.
    """
    if not isinstance(update, dict):
        return None
    state = load_pair_state() or {}
    paired_chat = str(state.get("chat_id") or "").strip()

    callback = update.get("callback_query")
    if isinstance(callback, dict):
        message = callback.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id") or "").strip()
        if not paired_chat or chat_id != paired_chat:
            return {"handled": True}
        data = str(callback.get("data") or "")
        callback_id = str(callback.get("id") or "")
        if data == "relay:list:active":
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            telegram_api("sendMessage", {"chat_id": chat_id, "text": _active_list_text(store), "reply_markup": _operator_keyboard()})
            return {"handled": True, "action": "list"}
        match_operator=re.fullmatch(r"relay:operator:(claude|gemini)",data)
        if match_operator:
            name=match_operator.group(1)
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": name.title()})
            telegram_api("sendMessage", {
                "chat_id": chat_id,
                "text": _operator_lane_text(name,operator_status_provider),
                "reply_markup": _operator_keyboard(),
            })
            return {"handled": True, "action": "operator", "operator": name}
        match = re.fullmatch(r"relay:status:(R-\d{4,8}):(inbox|in_progress|need_you|done|archived)", data)
        if match:
            ticket_id, status = match.group(1), match.group(2)
            try:
                ticket = store.set_status(ticket_id, status, actor="telegram")
            except KeyError:
                telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Тикет не найден"})
                return {"handled": True}
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": STATUS_LABELS[status]})
            telegram_api("sendMessage", {
                "chat_id": chat_id,
                "text": _ticket_card(ticket),
                "reply_markup": _ticket_keyboard(ticket_id),
            })
            return {"handled": True, "ticket_id": ticket_id, "status": status}
        return {"handled": True}

    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat") or {}
    if str(chat.get("type") or "") != "private":
        return None
    chat_id = str(chat.get("id") or "").strip()
    if not paired_chat or chat_id != paired_chat:
        return None

    text = str(message.get("text") or message.get("caption") or "").strip()
    command = text.split(maxsplit=1)[0].lower() if text.startswith("/") else ""
    if command in ("/pair", "/start", "/status"):
        return None
    if command in ("/relay", "/tasks"):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _active_list_text(store), "reply_markup": _operator_keyboard()})
        return {"handled": True, "action": "list"}
    if command in ("/operators","/workers"):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _operators_overview_text(operator_status_provider), "reply_markup": _operator_keyboard()})
        return {"handled": True, "action": "operators"}

    command_status = {
        "/done": "done",
        "/work": "in_progress",
        "/need": "need_you",
        "/inbox": "inbox",
    }
    if command in command_status:
        parts = text.split(maxsplit=1)
        ticket_id = parts[1].strip().upper() if len(parts) > 1 else ""
        try:
            ticket = store.set_status(ticket_id, command_status[command], actor="telegram")
        except (KeyError, ValueError):
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "Не нашёл тикет. Пример: /done R-0001"})
            return {"handled": True}
        telegram_api("sendMessage", {
            "chat_id": chat_id,
            "text": _ticket_card(ticket),
            "reply_markup": _ticket_keyboard(ticket_id),
        })
        return {"handled": True, "ticket_id": ticket_id}

    explicit_new = command == "/new"
    if explicit_new:
        parts = text.split(maxsplit=1)
        text = parts[1].strip() if len(parts) > 1 else ""

    attachment = _telegram_attachment(message)
    if not text and not attachment:
        return None

    source_url = _first_url(text)
    update_id = int(update.get("update_id") or 0)
    message_id = int(message.get("message_id") or 0)
    source_key = f"telegram:{update_id}" if update_id else f"telegram-message:{chat_id}:{message_id}"
    source = {
        "channel": "telegram",
        "source_key": source_key,
        "chat_id": chat_id,
        "message_id": message_id,
        "update_id": update_id,
        "url": source_url,
        "attachment": attachment or None,
    }
    ticket, created = store.create(
        _telegram_title(text, attachment),
        body=text,
        source=source,
        created_by="telegram",
    )
    telegram_api("sendMessage", {
        "chat_id": chat_id,
        "text": ("Создал тикет.\n\n" if created else "Тикет уже существует.\n\n") + _ticket_card(ticket),
        "reply_markup": _ticket_keyboard(ticket["id"]),
    })
    # Preserve the existing plain-text agent inbox: Relay is the durable task layer,
    # the bridge remains the processing channel.
    return {"handled": bool(explicit_new or not message.get("text")), "ticket_id": ticket["id"], "created": created}


def install_relay_routes(app, store: RelayStore, request_identity: Callable) -> None:
    @app.get("/api/relay")
    def relay_list(request: Request, status: str = "", limit: int = 200):
        _owner_guard(request, request_identity)
        try:
            items = store.list(status=status, limit=limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"summary": store.summary(), "items": items, "statuses": list(RELAY_STATUSES)}

    @app.post("/api/relay")
    def relay_create(payload: RelayCreateRequest, request: Request):
        _owner_guard(request, request_identity)
        source = {"channel": "factoryos", "url": (payload.source_url or "").strip()}
        ticket, created = store.create(payload.title, payload.body, source=source, priority=payload.priority)
        return {"ok": True, "created": created, "ticket": ticket}

    @app.get("/api/relay/{ticket_id}")
    def relay_detail(ticket_id: str, request: Request):
        _owner_guard(request, request_identity)
        ticket = store.get(ticket_id)
        if not ticket:
            raise HTTPException(404, "Relay ticket not found")
        return ticket

    @app.post("/api/relay/{ticket_id}/status")
    def relay_status(ticket_id: str, payload: RelayStatusRequest, request: Request):
        identity = _owner_guard(request, request_identity)
        try:
            ticket = store.set_status(ticket_id, payload.status, actor=identity.get("email") or "owner", note=payload.note)
        except KeyError:
            raise HTTPException(404, "Relay ticket not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "ticket": ticket}

    @app.post("/api/relay/{ticket_id}/notes")
    def relay_note(ticket_id: str, payload: RelayNoteRequest, request: Request):
        identity = _owner_guard(request, request_identity)
        try:
            ticket = store.add_note(ticket_id, payload.text, actor=identity.get("email") or "owner", kind=payload.kind)
        except KeyError:
            raise HTTPException(404, "Relay ticket not found")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "ticket": ticket}

    @app.get("/relay", response_class=HTMLResponse)
    def relay_mobile(request: Request):
        _owner_guard(request, request_identity)
        return HTMLResponse(_relay_html())


def _relay_html() -> str:
    return r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FactoryOS Relay</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#07101b;color:#eaf3ff;font:14px Inter,system-ui,Arial}
header{position:sticky;top:0;z-index:5;padding:16px;background:#08131fee;border-bottom:1px solid #20364a;backdrop-filter:blur(12px)}
h1{font-size:20px;margin:0}.sub{color:#8299ad;font-size:12px;margin-top:4px}.new{display:flex;gap:8px;margin-top:12px}
input{flex:1;min-width:0;background:#0d1b29;border:1px solid #29465e;border-radius:10px;color:#fff;padding:11px}
button{border:0;border-radius:9px;padding:9px 11px;background:#17304a;color:#dff4ff;font-weight:700}.primary{background:#137be6}
main{padding:12px;display:grid;grid-template-columns:repeat(4,minmax(240px,1fr));gap:10px;overflow-x:auto}.col{background:#0a1622;border:1px solid #1d3346;border-radius:14px;padding:10px;min-height:150px}
.col h2{font-size:13px;color:#9fb5c8;margin:2px 2px 10px}.card{background:#0d1d2b;border:1px solid #29445b;border-radius:12px;padding:11px;margin-bottom:8px}
.id{font:11px ui-monospace,monospace;color:#53c7ff}.title{font-weight:750;margin:5px 0;line-height:1.3}.url{display:block;color:#57b8ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;margin:5px 0}
.actions{display:flex;flex-wrap:wrap;gap:5px;margin-top:9px}.actions button{font-size:11px;padding:7px 8px}.empty{color:#60778b;padding:8px}
@media(max-width:800px){main{display:block;overflow:visible}.col{margin-bottom:10px;min-height:auto}header{padding-top:max(14px,env(safe-area-inset-top))}}
</style></head><body>
<header><h1>📡 FactoryOS Relay</h1><div class="sub" id="summary">Загрузка…</div>
<div class="new"><input id="newTitle" placeholder="Новая задача или ссылка"><button class="primary" onclick="createTicket()">Добавить</button></div><div class="new"><button id="tgBtn" onclick="pairTelegram()">Telegram…</button><span class="sub" id="tgState"></span></div></header>
<main id="board"></main>
<script>
const labels={inbox:"📥 Inbox",in_progress:"▶️ В работе",need_you:"🙋 Нужно от тебя",done:"✅ Готово"};
const order=["inbox","in_progress","need_you","done"];
function esc(s){return String(s||"").replace(/[&<>"']/g,function(c){return({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"})[c]})}
async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw new Error(await r.text());return r.json()}
async function load(){
  const d=await api("/api/relay?limit=200");
  document.getElementById("summary").textContent=d.summary.active+" активных · "+d.summary.needs_you+" ждут тебя · "+d.summary.done+" готово";
  const board=document.getElementById("board");board.innerHTML="";
  order.forEach(function(st){
    const col=document.createElement("section");col.className="col";const rows=d.items.filter(function(x){return x.status===st});
    col.innerHTML="<h2>"+labels[st]+" · "+rows.length+"</h2>";
    if(!rows.length)col.innerHTML+="<div class='empty'>Пусто</div>";
    rows.forEach(function(t){
      const src=t.source||{};const card=document.createElement("article");card.className="card";
      card.innerHTML="<div class='id'>"+esc(t.id)+"</div><div class='title'>"+esc(t.title)+"</div>"+
        (src.url?"<a class='url' target='_blank' href='"+esc(src.url)+"'>"+esc(src.url)+"</a>":"")+
        "<div class='actions'>"+
        "<button onclick=\"setStatus('"+esc(t.id)+"','inbox')\">Inbox</button>"+
        "<button onclick=\"setStatus('"+esc(t.id)+"','in_progress')\">В работу</button>"+
        "<button onclick=\"setStatus('"+esc(t.id)+"','need_you')\">Нужен я</button>"+
        "<button onclick=\"setStatus('"+esc(t.id)+"','done')\">✓</button></div>";
      col.appendChild(card);
    });board.appendChild(col);
  })
}
async function setStatus(id,status){await api("/api/relay/"+id+"/status",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({status:status})});load()}
async function createTicket(){const el=document.getElementById("newTitle"),v=el.value.trim();if(!v)return;const u=(v.match(/https?:\/\/\S+/)||[""])[0];await api("/api/relay",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({title:v,source_url:u})});el.value="";load()}
async function telegramStatus(){try{const s=await api("/api/factory/telegram/status");document.getElementById("tgBtn").textContent=s.paired?"✅ Telegram подключён":"Подключить Telegram";document.getElementById("tgState").textContent=s.paired?(s.username?"@"+s.username:"готов"):(s.configured?"не привязан":"бот не настроен")}catch(e){document.getElementById("tgState").textContent="статус недоступен"}}
async function pairTelegram(){try{const d=await api("/api/factory/telegram/pairing/start",{method:"POST"});document.getElementById("tgState").textContent="Код "+d.pair_code+" · действует "+Math.round(d.expires_in_seconds/60)+" мин";if(d.deep_link){window.location.href=d.deep_link}else{alert("Отправь боту: "+d.command)}}catch(e){alert("Не удалось начать привязку Telegram")}}
document.getElementById("newTitle").addEventListener("keydown",function(e){if(e.key==="Enter")createTicket()});load();telegramStatus();setInterval(load,10000);setInterval(telegramStatus,30000);
</script></body></html>"""
