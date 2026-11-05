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

from relay_execution import lifecycle_text
from lane_board import lane_board_text, telegram_lang
from worker_observability import worker_overview_text

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
                    "action": "queued",
                    "from_status": None,
                    "to_status": "inbox",
                    "note": "",
                }],
                "execution": {
                    "state": "queued",
                    "owner": "claude",
                    "queued_at": now,
                    "attempts": 0,
                    "last_seen_at": None,
                    "note": "Ожидает работающего Claude worker",
                },
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


class RelayWorkerClaimRequest(BaseModel):
    worker_id: str


class RelayRoadmapClaimRequest(BaseModel):
    worker_id: str
    lane: str
    task_id: str
    title: str = ""
    owner: str = ""


class RelayWorkerEventRequest(BaseModel):
    ticket_id: str
    worker_id: str
    stage: str
    note: str = ""
    evidence: dict = {}
    run_id: str = ""
    event_id: str = ""


class RelayIssueIntakeRequest(BaseModel):
    number: int
    title: str = ""
    url: str = ""
    repo: str = ""
    body: str = ""


def _owner_guard(request: Request, request_identity: Callable) -> dict:
    identity = request_identity(request) or {}
    if identity.get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    return identity


def _operator_buttons() -> list:
    return [
        {"text": "🟠 Claude", "callback_data": "relay:operator:claude"},
        {"text": "🔵 Gemini", "callback_data": "relay:operator:gemini"},
    ]


def _operator_keyboard(lane: Optional[dict] = None) -> dict:
    rows = [_operator_buttons()]
    # T-586: one button per open Relay ticket of this operator; it opens the normal ticket card + controls.
    relay_ids = [str(t.get("id") or "") for t in ((lane or {}).get("open_tickets") or []) if isinstance(t, dict)]
    relay_ids = [x for x in relay_ids if re.fullmatch(r"R-\d{4,8}", x)][:OPERATOR_TICKET_BUTTONS]
    for i in range(0, len(relay_ids), 2):
        rows.append([{"text": "📡 " + x, "callback_data": "relay:ticket:" + x} for x in relay_ids[i:i + 2]])
    rows.append([{"text": "📋 Все открытые тикеты", "callback_data": "relay:list:active"}])
    return {"inline_keyboard": rows}


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
    execution = ticket.get("execution") or {}
    if execution:
        stage = str(execution.get("state") or "unknown")
        owner = str(execution.get("owner") or "claude")
        labels = {"queued": "⏳ В очереди", "claimed": "📥 Получено worker", "running": "⚙️ Claude работает", "checkpoint": "⚙️ В процессе", "committed": "📦 Commit", "pushed": "⬆️ Push", "done": "✅ Выполнено", "blocked": "🙋 Нужна помощь", "failed": "❌ Ошибка", "stale": "⚠️ Worker без связи"}
        lines.append(f"Исполнение: {labels.get(stage, stage)} · {owner}")
        if execution.get("note"):
            lines.append(str(execution["note"])[:230])
        if execution.get("commit"):
            lines.append("Commit: " + str(execution["commit"])[:10] + " (worker report)")
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
        for x in rows[:12]:
            ex = x.get("execution") or {}
            stage = str(ex.get("state") or "не назначено")
            owner = str(ex.get("owner") or "owner")
            groups.append(f"{x['id']} · [{stage} · {owner}] {x['title'][:72]}")
            if ex.get("last_seen_at") and stage in ("claimed", "running", "checkpoint", "committed", "pushed"):
                groups.append("  Последняя связь: " + str(ex["last_seen_at"])[:19])
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
    task=str(lane.get("active_task_id") or "").strip()
    if task:
        lines.append(f"Текущая задача: {task}")
    else:
        last=str(lane.get("last_task_id") or "").strip()
        if last:
            lines.append(f"Последняя задача: {last} · {lane.get('task_state') or 'состояние неизвестно'} (не выполняется)")
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


OPERATOR_TICKET_BUTTONS = 6
_OPERATOR_LABELS = {"claude": "🟠 Claude", "gemini": "🔵 Gemini"}
_AVAILABILITY_TEXT = {
    "online": "🟢 online",
    "stale": "🟡 stale (heartbeat просрочен)",
    "offline": "⚪ offline",
    "unconfigured": "⛔ не настроен — runner ни разу не отчитывался",
}


def _t585_lanes(provider: Optional[Callable[[], list]]) -> Optional[dict]:
    """T-586: operator -> T-585 delegation lane; None when the provider is absent or failed."""
    if provider is None:
        return None
    try:
        lanes = provider() or []
    except Exception:
        return None
    return {str(x.get("operator_id") or ""): x for x in lanes if isinstance(x, dict)}


def _t585_status_line(lane: dict) -> str:
    availability = str(lane.get("availability") or "unconfigured")
    text = _AVAILABILITY_TEXT.get(availability, "⚪ " + availability)
    ticket = lane.get("open_ticket") or {}
    if ticket.get("id"):
        text += " · тикет " + str(ticket["id"])[:80] + (" · " + str(ticket.get("stage"))[:40] if ticket.get("stage") else "")
    count = len(lane.get("open_tickets") or [])
    return text + " · открытых: " + str(count)


def _t585_lane_text(name: str, lane: Optional[dict]) -> str:
    """One operator lane from the T-585 delegation board: status, current ticket, open tickets, last result."""
    label = _OPERATOR_LABELS.get(name, name.title())
    if not isinstance(lane, dict):
        return f"{label}\n\nСтатус: {_AVAILABILITY_TEXT['unconfigured']}\nОткрытых тикетов нет."
    lines = [label, "Статус: " + _AVAILABILITY_TEXT.get(str(lane.get("availability") or ""), "⚪ " + str(lane.get("availability") or "unknown"))]
    beat = lane.get("heartbeat") or {}
    if beat.get("age_seconds") is not None:
        lines.append("Heartbeat: " + str(int(float(beat["age_seconds"]))) + " сек назад (" + str(beat.get("source") or "?") + ")")
    else:
        lines.append("Heartbeat: нет данных")
    ticket = lane.get("open_ticket") or {}
    if ticket.get("id"):
        parts = [str(ticket["id"])[:80], str(ticket.get("stage") or "")[:40], str(ticket.get("title") or "")[:100]]
        lines.append("Текущий тикет: " + " · ".join(p for p in parts if p) + " (" + str(ticket.get("source") or "?") + ")")
    else:
        lines.append("Текущий тикет: нет подтверждённой работы")
    branch = str(lane.get("branch") or "").strip()
    runtime = str(lane.get("runtime") or "").strip()
    if branch or runtime:
        lines.append("Ветка: " + (branch or "неизвестно") + (" · runtime: " + runtime if runtime else ""))
    queue = lane.get("queue_depth")
    lines.append("Очередь: " + (str(queue) + " (" + str(lane.get("queue_depth_source") or "?") + ")" if queue is not None else "неизвестно"))
    tickets = [t for t in (lane.get("open_tickets") or []) if isinstance(t, dict)]
    lines.append("")
    if tickets:
        lines.append(f"Открытые тикеты ({len(tickets)}):")
        for t in tickets[:10]:
            parts = [str(t.get("id") or "")[:80], str(t.get("title") or "")[:90], str(t.get("state") or "")[:40]]
            lines.append("• " + " · ".join(p for p in parts if p))
        if len(tickets) > 10:
            lines.append(f"… ещё {len(tickets) - 10}")
    else:
        lines.append("Открытых тикетов нет.")
    waiting = [str(x) for x in (lane.get("assigned_not_claimed") or [])]
    if waiting:
        lines.append("Назначено, не взято: " + ", ".join(waiting[:8]))
    last = lane.get("last_result") or {}
    if last.get("summary") or last.get("result"):
        head = " · ".join(str(x) for x in (last.get("result"), last.get("task_id")) if x)
        lines.extend(["", "Последний результат: " + (head + " — " if head else "") + str(last.get("summary") or "")[:400]])
    if lane.get("last_error"):
        lines.append("Ошибка: " + str(lane["last_error"])[:200])
    return "\n".join(lines)[:3900]


_WORKERS_TEXT = {
    "ru": {"title": "🧠 Исполнители FactoryOS", "online": "🟢 онлайн", "stale": "🟡 сигнал просрочен", "offline": "⚪ офлайн",
           "unknown": "⚪ неизвестно", "working": "работает над", "idle": "простаивает", "beat": "сигнал {age} назад",
           "no_beat": "сигнала нет", "active": "в работе", "queue": "в очереди", "q_unknown": "очередь неизвестна",
           "s": "сек", "m": "мин", "h": "ч", "d": "дн"},
    "uk": {"title": "🧠 Виконавці FactoryOS", "online": "🟢 онлайн", "stale": "🟡 сигнал прострочено", "offline": "⚪ офлайн",
           "unknown": "⚪ невідомо", "working": "працює над", "idle": "простоює", "beat": "сигнал {age} тому",
           "no_beat": "сигналу немає", "active": "в роботі", "queue": "у черзі", "q_unknown": "черга невідома",
           "s": "с", "m": "хв", "h": "год", "d": "дн"},
    "en": {"title": "🧠 FactoryOS workers", "online": "🟢 online", "stale": "🟡 heartbeat overdue", "offline": "⚪ offline",
           "unknown": "⚪ unknown", "working": "working on", "idle": "idle", "beat": "last signal {age} ago",
           "no_beat": "no signal yet", "active": "active", "queue": "queued", "q_unknown": "queue unknown",
           "s": "s", "m": "min", "h": "h", "d": "d"},
}

_HELP_TEXTS = {
    "ru": (
        "🤖 Команды FactoryOS Relay:\n\n"
        "/help — Справка по всем командам бота\n"
        "/start — Запуск бота и просмотр справки\n"
        "/pair — Сопряжение Telegram-чата\n"
        "/status — Статус бота, очереди и воркеров\n"
        "/tasks — Список активных задач\n"
        "/relay — Обзор Relay и активных задач\n"
        "/roadmap — Дорожная карта и задачи\n"
        "/task — Карточка задачи по ID (напр. /task R-0001)\n"
        "/history — История событий и действий\n"
        "/github — Статус репозитория GitHub и CI\n"
        "/issue — Передать GitHub Issue в очередь (напр. /issue 41)\n"
        "/battles — Список и статус Battle Runs\n"
        "/battle — Просмотр конкретного Battle Run\n"
        "/workers — Статус воркеров и операторов\n"
        "/operators — Состояние линий операторов\n"
        "/new — Создать новую задачу (напр. /new Текст)\n"
        "/work — Перевести задачу в работу (напр. /work R-0001)\n"
        "/done — Завершить задачу (напр. /done R-0001)\n"
        "/need — Пометить задачу как требующую внимания (напр. /need R-0001)\n"
        "/inbox — Вернуть задачу в inbox (напр. /inbox R-0001)"
    ),
    "uk": (
        "🤖 Команди FactoryOS Relay:\n\n"
        "/help — Довідка з усіх команд бота\n"
        "/start — Запуск бота та перегляд довідки\n"
        "/pair — Прив'язка Telegram-чату за кодом\n"
        "/status — Статус бота, черги та воркерів\n"
        "/tasks — Список активних завдань\n"
        "/relay — Огляд Relay та активних завдань\n"
        "/roadmap — Дорожня карта та завдання\n"
        "/task — Картка завдання за ID (напр. /task R-0001)\n"
        "/history — Історія подій та дій\n"
        "/github — Статус репозиторію GitHub та CI\n"
        "/issue — Передати GitHub Issue у чергу (напр. /issue 41)\n"
        "/battles — Список та статус Battle Runs\n"
        "/battle — Перегляд конкретного Battle Run\n"
        "/workers — Статус воркерів та операторів\n"
        "/operators — Стан ліній операторів\n"
        "/new — Створити нове завдання (напр. /new Текст)\n"
        "/work — Взяти завдання в роботу (напр. /work R-0001)\n"
        "/done — Завершити завдання (напр. /done R-0001)\n"
        "/need — Позначити завдання як таке, що потребує уваги (напр. /need R-0001)\n"
        "/inbox — Повернути завдання в inbox (напр. /inbox R-0001)"
    ),
    "en": (
        "🤖 FactoryOS Relay Commands:\n\n"
        "/help — Show help and command list\n"
        "/start — Start bot and show command list\n"
        "/pair — Pair Telegram chat using pairing code\n"
        "/status — Bot, queue, and worker status\n"
        "/tasks — List active tasks\n"
        "/relay — Overview of Relay and active tasks\n"
        "/roadmap — View roadmap and task list\n"
        "/task — View task details by ID (e.g. /task R-0001)\n"
        "/history — History of Relay and GitHub events\n"
        "/github — GitHub repository and CI status\n"
        "/issue — Queue open GitHub Issue (e.g. /issue 41)\n"
        "/battles — List and view Battle Runs\n"
        "/battle — View specific Battle Run\n"
        "/workers — Status of workers and operators\n"
        "/operators — Operator lanes status\n"
        "/new — Create a new Relay task (e.g. /new Task text)\n"
        "/work — Set task status to in progress (e.g. /work R-0001)\n"
        "/done — Mark task as done (e.g. /done R-0001)\n"
        "/need — Mark task as needing owner attention (e.g. /need R-0001)\n"
        "/inbox — Move task back to inbox (e.g. /inbox R-0001)"
    ),
}

def _help_text(lang: str = "ru") -> str:
    return _HELP_TEXTS.get(lang) or _HELP_TEXTS["ru"]
_WORKER_ROWS = (("claude", "🟠 Claude"), ("chatgpt", "🟢 ChatGPT"), ("gemini", "🔵 Gemini"))


def _age_text(seconds, t: dict) -> str:
    seconds = int(max(0, float(seconds)))
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size} {t[unit]}"
    return f"{seconds} {t['s']}"


def _worker_row(lane: Optional[dict], t: dict) -> str:
    """#135: status · current task or idle · last heartbeat · active/queued counts; missing data is "unknown"."""
    if not isinstance(lane, dict) or str(lane.get("availability") or "unconfigured") == "unconfigured":
        return t["unknown"] + " · " + t["no_beat"]
    availability = str(lane.get("availability") or "")
    parts = [t.get(availability, t["unknown"])]
    ticket = lane.get("open_ticket") or {}
    if ticket.get("id"):
        parts.append(t["working"] + " " + str(ticket["id"])[:80] + (f" ({str(ticket.get('stage'))[:40]})" if ticket.get("stage") else ""))
    elif availability == "online":
        parts.append(t["idle"])
    age = (lane.get("heartbeat") or {}).get("age_seconds")
    parts.append(t["beat"].format(age=_age_text(age, t)) if age is not None else t["no_beat"])
    parts.append(t["active"] + " " + str(len([x for x in lane.get("open_tickets") or [] if isinstance(x, dict)])))
    queue = lane.get("queue_depth")
    parts.append(t["queue"] + " " + str(queue) if queue is not None else t["q_unknown"])
    return " · ".join(parts)


def _t585_overview_text(lanes: dict, lang: str = "ru") -> str:
    t = _WORKERS_TEXT.get(lang) or _WORKERS_TEXT["ru"]
    return "\n".join([t["title"]] + [label + ": " + _worker_row(lanes.get(key), t) for key, label in _WORKER_ROWS])


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
        rows.append(f"{label}: {'🟢 online' if online else '⚪ '+state}{_lane_task_suffix(lane)}")
    return "\n".join(rows)


def _operators_text(provider: Optional[Callable[[], dict]], lanes_provider: Optional[Callable[[], list]], lang: str = "ru") -> str:
    if lanes_provider is None:
        return _operators_overview_text(provider)
    lanes = _t585_lanes(lanes_provider)
    if lanes is None:
        return "🧠 Operators\n\n⚠️ Статус линий недоступен; состояние неизвестно."
    return _t585_overview_text(lanes, lang)



def relay_github_snapshot(repo: str = "", token: str = "") -> dict:
    """Read GitHub state on demand; a missing token/failed lookup is UNKNOWN, never success."""
    import urllib.error
    import urllib.request
    import json as _json

    repo = (repo or "Pavlovskyi-Andrii/blackboxlab-factoryos").strip()
    token = (token or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return {"available": False, "error": "Invalid repository", "issues": [], "pulls": []}

    def fetch(path: str):
        url = "https://api.github.com/repos/" + repo + path
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "FactoryOS-Relay/1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            return _json.load(response)

    try:
        issues_raw = fetch("/issues?state=open&per_page=12")
        pulls_raw = fetch("/pulls?state=open&per_page=3")
        commits_raw = fetch("/commits?per_page=8")
        if not isinstance(issues_raw, list) or not isinstance(pulls_raw, list) or not isinstance(commits_raw, list):
            raise ValueError("Unexpected GitHub response")
        issues = [{
            "number": int(x["number"]),
            "title": _clean_text(x.get("title"), 100),
            "url": str(x.get("html_url") or ""),
            "state": str(x.get("state") or "unknown"),
            "updated_at": str(x.get("updated_at") or ""),
        } for x in issues_raw if isinstance(x, dict) and "pull_request" not in x]
        pulls = []
        for x in pulls_raw:
            if not isinstance(x, dict):
                continue
            sha = str((x.get("head") or {}).get("sha") or "")
            entry = {
                "number": int(x["number"]),
                "title": _clean_text(x.get("title"), 100),
                "url": str(x.get("html_url") or ""),
                "sha": sha,
                "merged": False,
                "state": str(x.get("state") or "unknown"),
                "ci": "unknown",
            }
            if sha:
                try:
                    runs = fetch("/commits/" + sha + "/check-runs?per_page=50")
                    checks = runs.get("check_runs") if isinstance(runs, dict) else None
                    if isinstance(checks, list) and checks:
                        conclusions = [str(y.get("conclusion") or "") for y in checks]
                        statuses = [str(y.get("status") or "") for y in checks]
                        if any(v != "completed" for v in statuses):
                            entry["ci"] = "running"
                        elif all(v in ("success", "skipped", "neutral") for v in conclusions):
                            entry["ci"] = "passed"
                        else:
                            entry["ci"] = "failed"
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError):
                    pass
            pulls.append(entry)
        commits = [{
            "sha": str(x.get("sha") or "")[:40],
            "message": _clean_text(((x.get("commit") or {}).get("message") or "").splitlines()[0], 100),
            "date": str((((x.get("commit") or {}).get("author") or {}).get("date") or "")),
            "author": _clean_text(((x.get("author") or {}).get("login") or ((x.get("commit") or {}).get("author") or {}).get("name") or ""), 50),
            "url": str(x.get("html_url") or ""),
        } for x in commits_raw if isinstance(x, dict)]
        return {"available": True, "repo": repo, "checked_at": _now(), "issues": issues, "pulls": pulls, "commits": commits}
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        # Do not include request headers, tokens or internal tracebacks in Telegram.
        code = getattr(exc, "code", None)
        return {"available": False, "repo": repo, "error": ("HTTP " + str(code)) if code else "GitHub unavailable", "issues": [], "pulls": []}


def relay_github_owner_issues(repo: str = "", token: str = "", fetch=None) -> dict:
    """T-599-E: list open Issues created by the repo owner (one free GitHub API call).

    Failure is reported as ``available: False`` with a short code only — never
    request headers, tokens or response bodies.
    """
    import urllib.error
    import urllib.request
    import json as _json

    repo = (repo or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        return {"available": False, "repo": repo, "error": "Invalid repository", "issues": []}
    owner = repo.split("/", 1)[0]

    def _fetch(path: str):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "FactoryOS-Relay/1.0",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if (token or "").strip():
            headers["Authorization"] = "Bearer " + token.strip()
        req = urllib.request.Request("https://api.github.com/repos/" + repo + path, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            return _json.load(response)

    try:
        raw = (fetch or _fetch)("/issues?state=open&per_page=50&creator=" + owner)
        if not isinstance(raw, list):
            raise ValueError("Unexpected GitHub response")
        # A malformed entry is passed through as-is so intake counts it as ignored
        # instead of failing the whole pass.
        issues = [{
            "number": x.get("number"),
            "title": str(x.get("title") or "")[:300],
            "body": str(x.get("body") or "")[:20000],
            "url": str(x.get("html_url") or ""),
            "state": str(x.get("state") or "unknown"),
            "author": str((x.get("user") or {}).get("login") or "") if isinstance(x.get("user"), dict) else "",
            "pull_request": bool(x.get("pull_request")),
        } if isinstance(x, dict) else x for x in raw]
        return {"available": True, "repo": repo, "owner": owner, "checked_at": _now(), "issues": issues}
    except Exception as exc:  # network, HTTP, JSON: all mean UNKNOWN, never success
        code = getattr(exc, "code", None)
        return {"available": False, "repo": repo, "owner": owner,
                "error": ("HTTP " + str(code)) if code else "GitHub unavailable", "issues": []}


def relay_auto_intake_issues(queue, repo: str, token: str = "", fetch=None) -> dict:
    """Poll owner Issues once and import/link them; GitHub outage changes nothing."""
    snapshot = relay_github_owner_issues(repo, token, fetch=fetch)
    if not snapshot.get("available"):
        return {"ok": False, "error": snapshot.get("error") or "GitHub unavailable",
                "imported": [], "existing": [], "linked": [], "ignored": 0}
    summary = queue.auto_intake_owner_issues(snapshot["issues"], snapshot["repo"], snapshot["owner"])
    return {"ok": True, **summary}


def _github_text(snapshot: dict) -> str:
    if not snapshot.get("available"):
        return "🔗 GitHub: проверка недоступна (" + str(snapshot.get("error") or "unknown")[:60] + "). Статусы неизвестны."
    lines = ["🔗 GitHub · " + str(snapshot.get("repo") or ""), "Проверено: " + str(snapshot.get("checked_at") or "")[:19]]
    for pr in (snapshot.get("pulls") or [])[:5]:
        sha = str(pr.get("sha") or "")[:7] or "unknown"
        lines.append("PR #" + str(pr.get("number")) + " · " + str(pr.get("state") or "?") + " · CI " + str(pr.get("ci") or "unknown") + " · " + sha)
        lines.append(str(pr.get("url") or ""))
    if not snapshot.get("pulls"):
        lines.append("Открытых PR не найдено")
    for commit in (snapshot.get("commits") or [])[:5]:
        lines.append("Commit " + str(commit.get("sha") or "")[:7] + " · " + str(commit.get("message") or "")[:80])
    return "\n".join(lines)[:3900]


def _lane_task_suffix(lane: dict) -> str:
    """Separate online heartbeat from verified running task."""
    task = str(lane.get("active_task_id") or "").strip()
    if task:
        return " · выполняет " + task
    last = str(lane.get("last_task_id") or "").strip()
    if last:
        state = str(lane.get("task_state") or "неизвестно")[:24]
        return " · последняя " + last + ": " + state + " (не выполняется)"
    return ""


def _lane_section(lane_board: Optional[Callable[[], dict]], lang: str, worker: bool = False) -> list:
    """T-599-F: the same per-lane read model the web lane board renders.

    T-596: with ``worker`` the per-source Claude worker block (the Worker Center signals) follows,
    built from the same board snapshot so task/stage cannot differ from the lane line."""
    if lane_board is None:
        return []
    try:
        board = lane_board() or {}
        out = ["", lane_board_text(board, lang)]
        if worker and isinstance(board.get("worker_overview"), dict):
            out.extend(["", worker_overview_text(board["worker_overview"], lang)])
        return out
    except Exception:
        return ["", "Линии: данные недоступны"]


def _relay_status_text(store: RelayStore, provider: Optional[Callable[[], dict]], queue=None,
                       lane_board: Optional[Callable[[], dict]] = None, lang: str = "ru") -> str:
    summary = store.summary()
    tickets = store.list(limit=500)
    lines = ["📡 FactoryOS Relay", "Связь с Telegram: ✅",
             "Тикетов: " + str(summary["total"]) + " · открытых: " + str(summary["active"])]
    if queue is not None:
        counts = queue.counts(tickets)
        lines.append("Очередь: " + str(counts["claimable"]) + " · работа: " + str(counts["running"]) +
                     " · без связи: " + str(counts["stale"]) + " · нужен владелец: " + str(counts["need_you"]))
        if counts["not_queued"]:
            ids = counts["not_queued"]
            lines.append("Открыты, но не в очереди: " + ", ".join(ids[:8]) +
                         " · /work " + ids[0] + " для повторного запуска (только если нет работы)")
    else:
        stages = [str((t.get("execution") or {}).get("state") or "") for t in tickets]
        lines.append("Очередь: " + str(stages.count("queued")) +
                     " · работа: " + str(sum(x in ("claimed", "running", "checkpoint", "committed", "pushed") for x in stages)))
    if lane_board is not None:
        # T-599-F: lane state, task and stage come only from the verified-event lane board.
        lines.extend(_lane_section(lane_board, lang, worker=True))
        return "\n".join(lines)[:3900]
    lines.append("ChatGPT: нет автоматической телеметрии")
    if provider:
        try:
            lanes = provider() or {}
            for name in ("claude", "gemini"):
                lane = lanes.get(name) or {}
                online = lane.get("online") is True
                age = lane.get("heartbeat_age_seconds")
                desc = "online" if online else str(lane.get("state") or "offline")
                if age is not None:
                    desc += " · heartbeat " + str(age) + " сек назад"
                desc += _lane_task_suffix(lane)
                lines.append(name.capitalize() + ": " + desc)
        except Exception:
            lines.append("Воркеры: данные недоступны")
    else:
        lines.append("Воркеры: телеметрия не подключена")
    return "\n".join(lines)[:3900]


def _legacy_lane_lines(provider: Optional[Callable[[], dict]]) -> list:
    lines = []
    if provider:
        try:
            lanes = provider() or {}
            for name in ("claude", "gemini"):
                lane = lanes.get(name) or {}
                state = "online" if lane.get("online") is True else str(lane.get("state") or "offline")
                lines.append(name.capitalize() + ": " + state + _lane_task_suffix(lane))
        except Exception:
            lines.append("Телеметрия исполнителей недоступна")
    else:
        lines.append("Нет телеметрии воркеров")
    lines.append("ChatGPT: нет автоматической телеметрии")
    return lines


def _relay_tasks_text(store: RelayStore, provider: Optional[Callable[[], dict]], github: Optional[Callable[[], dict]],
                      lane_board: Optional[Callable[[], dict]] = None, lang: str = "ru") -> str:
    lines = [_active_list_text(store)]
    if lane_board is not None:
        lines.extend(_lane_section(lane_board, lang))
    else:
        lines.extend(["", "— Исполнители —"])
        lines.extend(_legacy_lane_lines(provider))
    if github:
        try:
            snapshot = github() or {}
            if snapshot.get("available"):
                lines.append("")
                lines.append("— GitHub issues (открытые) —")
                for issue in (snapshot.get("issues") or [])[:8]:
                    lines.append("#" + str(issue.get("number")) + " · " + str(issue.get("title") or "")[:75])
                if not snapshot.get("issues"):
                    lines.append("Открытых задач GitHub нет")
            else:
                lines.append("GitHub: недоступен; статусы неизвестны")
        except Exception:
            lines.append("GitHub: недоступен; статусы неизвестны")
    return "\n".join(lines)[:3900]


def _relay_history_text(store: RelayStore, github: Optional[Callable[[], dict]] = None) -> str:
    events = []
    for ticket in store.list(limit=500):
        for event in ticket.get("history") or []:
            events.append((str(event.get("at") or ""), str(ticket.get("id") or ""), event))
    events.sort(key=lambda row: row[0], reverse=True)
    lines = ["🕘 Relay · подтверждённая история"]
    for at, ticket_id, event in events[:20]:
        lines.append(at[:19] + " · " + ticket_id + " · " + str(event.get("actor") or "?")[:32] + " · " + str(event.get("action") or "?")[:30])
    if not events:
        lines.append("Событий пока нет")
    if github:
        try:
            snapshot = github() or {}
            if snapshot.get("available"):
                lines.append("")
                lines.append("GitHub: подтверждённые коммиты main")
                for commit in (snapshot.get("commits") or [])[:8]:
                    lines.append(str(commit.get("date") or "")[:19] + " · " + str(commit.get("sha") or "")[:7] + " · " + str(commit.get("author") or "?")[:22] + " · " + str(commit.get("message") or "")[:50])
            else:
                lines.append("GitHub: данные недоступны")
        except Exception:
            lines.append("GitHub: данные недоступны")
    lines.append("Нет автоматической истории действий ChatGPT вне GitHub/Relay.")
    return "\n".join(lines)[:3900]


def _relay_keyboard() -> dict:
    return {"inline_keyboard": [
        [{"text": "📋 Задачи", "callback_data": "relay:overview:tasks"},
         {"text": "🕘 История", "callback_data": "relay:overview:history"}],
        [{"text": "🔗 GitHub / CI", "callback_data": "relay:overview:github"},
         {"text": "🧠 Воркеры", "callback_data": "relay:overview:workers"}],
        _operator_buttons(),
        [{"text": "⚔️ Battles", "callback_data": "battle:list"}],
    ]}

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
    github_provider: Optional[Callable[[], dict]] = None,
    queue=None,
    lane_board_provider: Optional[Callable[[], dict]] = None,
    operator_lanes_provider: Optional[Callable[[], list]] = None,
    battle_controls=None,
) -> Optional[dict]:
    """Handle Relay-specific Telegram traffic.

    Returns {"handled": True, ...} when app.py should stop processing the update.
    For ordinary text messages it creates a Relay ticket but returns handled=False
    so the legacy bridge inbox still receives the text for agent-side processing.

    ``operator_lanes_provider`` (T-586) returns the T-585 delegation ``operator_lanes`` list; when it
    is given, the Claude/Gemini buttons render those lanes (status + open tickets) instead of the
    legacy heartbeat map from ``operator_status_provider``.

    ``battle_controls`` (T-587) is a ``telegram_battles.BattleTelegram``: ``battle:*`` callbacks and
    ``/battles`` / ``/battle <id>`` show Battle Runs and record only the safe owner approve/reject decision.
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
        lang = telegram_lang((callback.get("from") or {}).get("language_code"))
        if data.startswith("battle:"):
            if battle_controls is None:
                telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Battle Runs не подключены"})
                return {"handled": True}
            return battle_controls.callback(data, chat_id, callback_id, telegram_api)
        if data.startswith("relay:overview:"):
            action = data.split(":")[-1]
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            if action == "tasks":
                value = _relay_tasks_text(store, operator_status_provider, github_provider, lane_board_provider, lang)
            elif action == "history":
                value = _relay_history_text(store, github_provider)
            elif action == "github":
                value = _github_text(github_provider() if github_provider else {"available": False})
            elif action == "workers":
                value = _operators_text(operator_status_provider, operator_lanes_provider, lang)
            else:
                return {"handled": True}
            telegram_api("sendMessage", {"chat_id": chat_id, "text": value, "reply_markup": _relay_keyboard()})
            return {"handled": True, "action": action}
        if data == "relay:list:active":
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            telegram_api("sendMessage", {"chat_id": chat_id, "text": _active_list_text(store), "reply_markup": _operator_keyboard()})
            return {"handled": True, "action": "list"}
        match_operator=re.fullmatch(r"relay:operator:(claude|gemini)",data)
        if match_operator:
            name=match_operator.group(1)
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": name.title()})
            lanes=_t585_lanes(operator_lanes_provider)
            if lanes is not None:
                text, keyboard = _t585_lane_text(name, lanes.get(name)), _operator_keyboard(lanes.get(name))
            elif operator_lanes_provider is not None:
                text, keyboard = f"{_OPERATOR_LABELS[name]}\n\n⚠️ Статус линии недоступен; состояние неизвестно.", _operator_keyboard()
            else:
                text, keyboard = _operator_lane_text(name,operator_status_provider), _operator_keyboard()
            telegram_api("sendMessage", {"chat_id": chat_id, "text": text, "reply_markup": keyboard})
            return {"handled": True, "action": "operator", "operator": name}
        match_ticket = re.fullmatch(r"relay:ticket:(R-\d{4,8})", data)
        if match_ticket:
            ticket_id = match_ticket.group(1)
            ticket = store.get(ticket_id)
            if not ticket:
                telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Тикет не найден"})
                return {"handled": True}
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            telegram_api("sendMessage", {"chat_id": chat_id, "text": _ticket_card(queue.view(ticket) if queue else ticket),
                                         "reply_markup": _ticket_keyboard(ticket_id)})
            return {"handled": True, "action": "ticket", "ticket_id": ticket_id}
        match = re.fullmatch(r"relay:status:(R-\d{4,8}):(inbox|in_progress|need_you|done|archived)", data)
        if match:
            ticket_id, status = match.group(1), match.group(2)
            current = store.get(ticket_id)
            ex_state = str(((current or {}).get("execution") or {}).get("state") or "")
            if queue and status in ("done", "archived") and ex_state in ("queued", "claimed", "running", "checkpoint", "committed", "pushed"):
                telegram_api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Сначала дождись результата Claude. Это не завершённая задача."})
                return {"handled": True}
            try:
                ticket = queue.enqueue(ticket_id, actor="telegram") if status == "in_progress" and queue else store.set_status(ticket_id, status, actor="telegram")
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
    lang = telegram_lang((message.get("from") or {}).get("language_code"))
    if command == "/pair" or (command == "/start" and len(text.split()) > 1):
        return None
    if command == "/help" or (command == "/start" and len(text.split()) == 1):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _help_text(lang), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "help"}
    if command == "/status":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_status_text(store, operator_status_provider, queue, lane_board_provider, lang), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "status"}
    if command in ("/relay", "/tasks"):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_tasks_text(store, operator_status_provider, github_provider, lane_board_provider, lang), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "list"}
    if command == "/history":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_history_text(store, github_provider), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "history"}
    if command == "/github":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _github_text(github_provider() if github_provider else {"available": False}), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "github"}
    if command == "/roadmap":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_tasks_text(store, operator_status_provider, github_provider, lane_board_provider, lang), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "roadmap"}
    if command == "/task":
        parts = text.split(maxsplit=1)
        ticket_id = parts[1].strip().upper() if len(parts) > 1 else ""
        if ticket_id.startswith("#") or ticket_id.isdecimal():
            number = ticket_id.lstrip("#")
            try:
                snapshot = github_provider() if github_provider else {}
                match = next((x for x in (snapshot.get("issues") or []) if str(x.get("number") or "") == number), None)
            except Exception:
                match = None
            if match and snapshot.get("available") and str(match.get("state") or "").lower() == "open":
                detail = "🔗 GitHub #" + number + "\n" + str(match.get("title") or "") + "\nСтатус: open (проверено в GitHub)\n" + str(match.get("url") or "")
            else:
                detail = "GitHub #" + number + ": нет в текущей выборке открытых задач. Статус неизвестен; проверь GitHub."
            telegram_api("sendMessage", {"chat_id": chat_id, "text": detail, "reply_markup": _relay_keyboard()})
            return {"handled": True, "action": "github_issue", "number": number}
        ticket = store.get(ticket_id)
        if not ticket:
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "Задача не найдена. Пример: /task R-0001"})
            return {"handled": True}
        if queue:
            ticket = queue.view(ticket)
        history = ticket.get("history") or []
        lines = [_ticket_card(ticket), ("ТЗ: " + str(ticket.get("body") or "")[:450]) if ticket.get("body") else "",
                 lifecycle_text(ticket), "История:"]
        for event in history[-12:]:
            evidence = event.get("evidence") or {}
            commit = " · " + str(evidence.get("commit") or "")[:10] if evidence.get("commit") else ""
            lines.append(f"{str(event.get('at') or '')[:19]} · {event.get('actor') or '?'} · {event.get('action') or '?'}{commit} · {str(event.get('note') or '')[:120]}")
        telegram_api("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines)[:3900], "reply_markup": _ticket_keyboard(ticket_id)})
        return {"handled": True, "action": "detail", "ticket_id": ticket_id}
    if command == "/issue":
        parts = text.split(maxsplit=1)
        number = (parts[1].strip().lstrip("#") if len(parts) > 1 else "")
        if not number.isdecimal() or queue is None:
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "Пример: /issue 41 — поставить открытый GitHub Issue в очередь Claude."})
            return {"handled": True}
        try:
            snapshot = github_provider() if github_provider else {}
        except Exception:
            snapshot = {}
        match = next((x for x in (snapshot.get("issues") or []) if str(x.get("number") or "") == number), None)
        if not snapshot.get("available") or not match:
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "GitHub #" + number + ": не подтверждён как открытый Issue (GitHub недоступен или не в выборке). Тикет НЕ создан."})
            return {"handled": True, "action": "issue_unverified", "number": number}
        ticket, created = queue.intake_github_issue(int(number), str(match.get("title") or ""), url=str(match.get("url") or ""),
                                                    repo=str(snapshot.get("repo") or ""), actor="telegram")
        head = "Issue поставлен в очередь Claude (ещё не запущен).\n\n" if created else "Issue уже связан с тикетом; повторно не ставлю.\n\n"
        telegram_api("sendMessage", {"chat_id": chat_id, "text": head + _ticket_card(ticket), "reply_markup": _ticket_keyboard(ticket["id"])})
        return {"handled": True, "action": "issue_intake", "ticket_id": ticket["id"], "created": created}
    if command in ("/battles", "/battle") and battle_controls is not None:
        return battle_controls.command(command, text, chat_id, telegram_api)
    if command in ("/operators","/workers"):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _operators_text(operator_status_provider, operator_lanes_provider, lang), "reply_markup": _operator_keyboard()})
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
        current = store.get(ticket_id)
        ex_state = str(((current or {}).get("execution") or {}).get("state") or "")
        if queue and command == "/done" and ex_state in ("queued", "claimed", "running", "checkpoint", "committed", "pushed"):
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "⏳ Задание ещё не выполнено. Claude должен подтвердить результат."})
            return {"handled": True}
        try:
            ticket = queue.enqueue(ticket_id, actor="telegram") if command == "/work" and queue else store.set_status(ticket_id, command_status[command], actor="telegram")
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
    if command and not explicit_new:
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _help_text(lang), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "help"}
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


def install_relay_routes(app, store: RelayStore, request_identity: Callable, *, queue=None, authorize_worker=None, notify_owner=None) -> None:
    @app.get("/api/relay")
    def relay_list(request: Request, status: str = "", limit: int = 200):
        _owner_guard(request, request_identity)
        try:
            items = store.list(status=status, limit=limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"summary": store.summary(), "items": [queue.view(x) for x in items] if queue else items, "statuses": list(RELAY_STATUSES)}

    @app.post("/api/relay")
    def relay_create(payload: RelayCreateRequest, request: Request):
        _owner_guard(request, request_identity)
        source = {"channel": "factoryos", "url": (payload.source_url or "").strip()}
        ticket, created = store.create(payload.title, payload.body, source=source, priority=payload.priority)
        if created and notify_owner:
            try:
                notify_owner(f"📥 Relay {ticket['id']}: {ticket['title']}\nВ очереди Claude, выполнение ещё не началось.")
            except Exception:
                pass
        return {"ok": True, "created": created, "ticket": queue.view(ticket) if queue else ticket}

    @app.get("/api/relay/{ticket_id}")
    def relay_detail(ticket_id: str, request: Request):
        _owner_guard(request, request_identity)
        ticket = store.get(ticket_id)
        if not ticket:
            raise HTTPException(404, "Relay ticket not found")
        return queue.view(ticket) if queue else ticket

    @app.post("/api/relay/{ticket_id}/status")
    def relay_status(ticket_id: str, payload: RelayStatusRequest, request: Request):
        identity = _owner_guard(request, request_identity)
        existing = store.get(ticket_id)
        active_state = str(((existing or {}).get("execution") or {}).get("state") or "")
        if queue and payload.status in ("done", "archived") and active_state in ("queued", "claimed", "running", "checkpoint", "committed", "pushed"):
            raise HTTPException(409, "Cannot mark Claude task done before execution is verified")
        try:
            ticket = queue.enqueue(ticket_id, actor=identity.get("email") or "owner") if payload.status == "in_progress" and queue else store.set_status(ticket_id, payload.status, actor=identity.get("email") or "owner", note=payload.note)
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


    @app.post("/api/relay/{ticket_id}/run")
    def relay_enqueue_existing(ticket_id: str, request: Request):
        identity = _owner_guard(request, request_identity)
        if queue is None:
            raise HTTPException(503, "Claude queue unavailable")
        try:
            ticket = queue.enqueue(ticket_id, actor=identity.get("email") or "owner")
        except KeyError:
            raise HTTPException(404, "Relay ticket not found")
        if notify_owner:
            try:
                notify_owner(f"⏳ Relay {ticket_id}: передано Claude; ожидает worker.")
            except Exception:
                pass
        return {"ok": True, "ticket": ticket}

    @app.post("/api/relay/intake/github-issue")
    def relay_intake_github_issue(payload: RelayIssueIntakeRequest, request: Request):
        identity = _owner_guard(request, request_identity)
        if queue is None:
            raise HTTPException(503, "Claude queue unavailable")
        try:
            ticket, created = queue.intake_github_issue(payload.number, payload.title, url=payload.url, repo=payload.repo,
                                                        body=payload.body, actor=identity.get("email") or "owner")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if created and notify_owner:
            try:
                notify_owner(f"📥 Relay {ticket['id']}: {ticket['title']}\nВ очереди Claude, выполнение ещё не началось.")
            except Exception:
                pass
        return {"ok": True, "created": created, "ticket": ticket}

    def _require_worker(request: Request):
        if not authorize_worker or not authorize_worker(request):
            raise HTTPException(401, "Claude worker credential required")
        if queue is None:
            raise HTTPException(503, "Claude queue unavailable")

    @app.post("/api/relay/worker/claim")
    def relay_worker_claim(payload: RelayWorkerClaimRequest, request: Request):
        _require_worker(request)
        try:
            ticket = queue.claim(payload.worker_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "ticket": ticket}

    @app.post("/api/relay/worker/roadmap-claim")
    def relay_worker_roadmap_claim(payload: RelayRoadmapClaimRequest, request: Request):
        _require_worker(request)
        try:
            ticket, reason = queue.claim_roadmap(payload.worker_id, payload.lane, payload.task_id,
                                                 payload.title, payload.owner)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        if ticket and notify_owner:
            try:
                notify_owner(f"📥 {payload.task_id} взята в работу · {payload.lane} · {payload.worker_id}\n"
                             f"run {(ticket.get('execution') or {}).get('run_id') or '?'}")
            except Exception:
                pass
        return {"ok": bool(ticket), "ticket": ticket, "rejected": reason}

    @app.post("/api/relay/worker/event")
    def relay_worker_event(payload: RelayWorkerEventRequest, request: Request):
        _require_worker(request)
        try:
            ticket = queue.event(payload.ticket_id, payload.worker_id, payload.stage, payload.note, payload.evidence,
                                 run_id=payload.run_id, event_id=payload.event_id)
        except KeyError:
            raise HTTPException(404, "Relay ticket not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if payload.stage not in {"heartbeat", "checkpoint"} and notify_owner and not ticket.get("replayed"):
            try:
                execution = ticket.get("execution") or {}
                stage = execution.get("state") or payload.stage
                note = str(execution.get("note") or "")[:200]
                notify_owner(f"📡 Relay {payload.ticket_id} · Claude {stage}\n{note}")
            except Exception:
                pass
        return {"ok": True, "ticket": ticket}

    @app.get("/relay", response_class=HTMLResponse)
    def relay_mobile(request: Request):
        _owner_guard(request, request_identity)
        return HTMLResponse(_relay_html())


def _relay_html() -> str:
    return r"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FactoryOS · Relay</title>
<style>
:root{color-scheme:dark;--bg:#070f19;--card:#102032;--line:#254159;--muted:#95aac0;--accent:#54bdff;--green:#58d9a6}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(850px 500px at 40% -200px,#183453 0,transparent 75%),var(--bg);color:#eef7ff;font:14px Inter,system-ui,Arial}
header{padding:18px clamp(12px,3vw,40px);position:sticky;top:0;z-index:5;background:#081420ee;border-bottom:1px solid #28415c;backdrop-filter:blur(14px)}
h1{font-size:23px;letter-spacing:-.6px;margin:0}h2{font-size:15px;margin:0 0 10px}
.sub{color:var(--muted);font-size:12px;line-height:1.6}.meta{display:flex;gap:14px;flex-wrap:wrap;align-items:center;margin:6px 0 12px}
button{border:1px solid #34506a;background:#17304a;color:#e7f3ff;border-radius:9px;padding:10px 12px;font:inherit;font-weight:650;cursor:pointer}
button:hover{border-color:#65b5ec}.primary{background:#167ad5;border-color:#1684eb;color:white}button:disabled{opacity:.55}
input,textarea{width:100%;background:#101f2e;border:1px solid #35536b;border-radius:10px;color:white;padding:11px;font:inherit}
textarea{resize:vertical;min-height:62px}input:focus,textarea:focus{outline:1px solid #54bdff}
form{display:grid;grid-template-columns:minmax(260px,2fr) minmax(240px,3fr) auto;gap:8px;align-items:start;margin:12px 0 8px}
.toprow{display:flex;gap:9px;flex-wrap:wrap;align-items:center}.hint{font-size:12px;color:#a8bcd0}
main{padding:16px clamp(12px,3vw,40px);display:grid;grid-template-columns:repeat(4,minmax(250px,1fr));gap:12px;align-items:start}
.column{background:#0b1a29;border:1px solid #284157;border-radius:15px;padding:13px;min-height:180px}
.column h2{font-size:13px;color:#b2cce2}.card{background:var(--card);border:1px solid #2c4c65;border-radius:12px;padding:13px;margin:8px 0}
.id{font:11px ui-monospace,monospace;color:var(--accent)}.title{font-size:14px;font-weight:750;margin:7px 0;line-height:1.35;overflow-wrap:anywhere}
.exec{display:inline-block;border-radius:8px;padding:5px 7px;background:#17344b;font-size:12px;font-weight:750}
.exec.queued{color:#ffd58d;background:#4b391a}.exec.running,.exec.claimed,.exec.checkpoint{color:#8bd3ff}.exec.done{color:#80edc6;background:#194338}
.exec.blocked,.exec.failed,.exec.stale{color:#ffb2a5;background:#442525}
.desc{font-size:12px;color:#b6cada;margin-top:8px;overflow-wrap:anywhere}.line{margin:5px 0;color:#8ea7bd;font-size:11px}
.actions{display:flex;gap:6px;flex-wrap:wrap;margin-top:12px}.actions button{font-size:11px;padding:7px 9px}
.empty{color:#718da4;padding:14px 4px}.notice{font-size:12px;color:#b9d6f0;min-height:18px;margin-top:6px}
dialog{background:#0b1926;color:#eaf5ff;border:1px solid #3e6380;border-radius:16px;padding:22px;width:min(650px,94vw);max-height:90vh;overflow:auto}
dialog::backdrop{background:#000a}.event{padding:11px 0;border-bottom:1px solid #254159}.event strong{display:block}.event time{font:11px ui-monospace,monospace;color:#87a2b8}.event p{color:#d0e2ef;margin:5px 0;font-size:12px;overflow-wrap:anywhere}
a{color:#78c7ff}#footer{padding:0 18px 24px;color:#8ca5b9;font-size:12px}
@media(max-width:1250px){main{grid-template-columns:repeat(2,minmax(260px,1fr))}}
@media(max-width:750px){header{position:static;padding:16px}main{grid-template-columns:1fr;padding:12px}form{grid-template-columns:1fr}button{min-height:38px}}
</style></head><body>
<header>
<div class="toprow"><h1>📡 FactoryOS Relay</h1><span class="hint">Работа Claude в реальном времени · без фиктивных процентов</span></div>
<div class="meta"><span id="summary" class="sub">Загрузка…</span><span class="sub" id="worker">Claude: проверка…</span></div>
<form id="newForm">
  <input id="newTitle" maxlength="180" placeholder="Что нужно сделать? Например: исправить вкладку Workers" required>
  <textarea id="newBody" maxlength="10000" placeholder="Подробное задание и критерии готовности (необязательно)"></textarea>
  <button type="submit" id="submit" class="primary">▶ Отправить Claude</button>
</form>
<div class="toprow"><button id="tgBtn" onclick="pairTelegram()">Telegram…</button><span class="sub" id="tgState"></span><button onclick="pairWorker()">🔑 Подключить AWS worker</button><button onclick="load()">↻ Обновить</button></div>
<div id="notice" class="notice"></div>
</header>
<main id="board"></main><div id="footer">Статус «в работе» появляется только после запуска исполнителя. Коммит и push — отдельные подтверждаемые события.</div>
<dialog id="pairDialog"><h2>🔑 Привязка Claude worker на AWS</h2>
<p class="sub">Токен виден только здесь один раз. Не отправляй его в чат и не сохраняй в GitHub.</p>
<textarea id="pairToken" readonly rows="3" style="width:100%;font-family:ui-monospace,monospace"></textarea>
<div class="actions"><button onclick="copyPairToken()">📋 Скопировать токен</button><button onclick="document.getElementById('pairDialog').close()">Закрыть</button></div>
<p class="sub">В существующем EC2 через Session Manager открой <code>/etc/factoryos/claude-worker.env</code> и установи <code>FACTORY_CLAUDE_WORKER_TOKEN=</code> с этим значением. Затем запусти <code>sudo systemctl start factoryos-runner-supervisor.service</code>.</p>
</dialog>
<dialog id="details"><div class="toprow"><h2 id="detailsTitle"></h2><button onclick="document.getElementById('details').close()">Закрыть ×</button></div><div id="detailsBody"></div></dialog>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const states={queued:"⏳ В очереди",claimed:"📥 Получено воркером",running:"⚙️ Claude работает",checkpoint:"⚙️ В процессе",committed:"📦 Commit",pushed:"⬆️ Push",done:"✅ Готово",blocked:"🙋 Нужна помощь",failed:"❌ Ошибка",stale:"⚠️ Нет heartbeat"};
const statuses={inbox:"📥 Очередь",in_progress:"▶️ Выполняется",need_you:"🙋 Проблемы / блокеры",done:"✅ Готово"};
const order=["inbox","in_progress","need_you","done"];
async function api(url,opt){const r=await fetch(url,opt);if(!r.ok)throw new Error("HTTP "+r.status+": "+(await r.text()).slice(0,150));return await r.json()}
const send=(method,body)=>({method,headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
function age(ts){if(!ts)return"";const d=(Date.now()-Date.parse(ts))/1000;if(!Number.isFinite(d))return"";return d<60?Math.round(d)+" сек":Math.round(d/60)+" мин"}
function safeLink(url){try{const x=new URL(String(url));return x.protocol==="https:"||x.protocol==="http:"?x.href:""}catch{return""}}
function executionLine(t){
  const e=t.execution||{},stage=e.state||"not_requested",last=e.last_seen_at||"",note=e.note||"";
  return '<div class="exec '+esc(stage)+'">'+esc(states[stage]||"Не назначено")+'</div>'+
     '<div class="line">Исполнитель: '+esc(e.owner||"не назначен")+' · '+(last?'heartbeat '+esc(age(last))+' назад':'запуск ещё не подтверждён')+'</div>'+
     (note?'<div class="desc">'+esc(note)+'</div>':'')+
     (e.commit?'<div class="line">Commit '+esc(String(e.commit).slice(0,10))+' · отчёт worker</div>':'');
}
async function load(){
 try{
  const [d,w]=await Promise.all([api("/api/relay?limit=200"),api("/api/factory/claude-code/status").catch(()=>null)]);
  $("summary").textContent=d.summary.active+" открытых · "+d.summary.needs_you+" требуют внимания · "+d.summary.done+" завершено";
  $("worker").textContent=w?(w.online?"🟢 Claude worker online":"⚪ Claude worker offline · задания ждут запуска"):"Claude: телеметрия недоступна";
  const board=$("board");board.innerHTML="";
  order.forEach(st=>{
    const col=document.createElement("section");col.className="column";
    const rows=d.items.filter(t=>t.status===st);
    col.innerHTML="<h2>"+statuses[st]+" · "+rows.length+"</h2>";
    if(!rows.length)col.innerHTML+='<div class="empty">Нет задач</div>';
    for(const t of rows){
      const card=document.createElement("article");card.className="card";
      const e=t.execution||{},src=t.source||{},link=safeLink(src.url);
      const startAllowed=!["queued","claimed","running","checkpoint","committed","pushed"].includes(e.state||"");
      card.innerHTML='<span class="id">'+esc(t.id)+'</span><div class="title">'+esc(t.title)+'</div>'+
        executionLine(t)+(link?'<p><a target="_blank" rel="noopener noreferrer" href="'+esc(link)+'">Исходная ссылка</a></p>':'')+
        '<div class="actions"><button data-detail="'+esc(t.id)+'">📜 История</button>'+
        (startAllowed?'<button data-run="'+esc(t.id)+'">↻ Отправить Claude</button>':'')+'</div>';
      col.appendChild(card);
    }
    board.appendChild(col);
  });
 }catch(e){$("notice").textContent="Не удалось обновить данные Relay: "+String(e.message||e)}
}
async function createTicket(ev){
 ev.preventDefault();const el=$("newTitle"),v=el.value.trim(),body=$("newBody").value.trim();if(!v)return;
 $("submit").disabled=true;$("notice").textContent="Добавляю задание в очередь Claude…";
 try{
  const match=v.match(/https?:\/\/\S+/);const d=await api("/api/relay",send("POST",{title:v,body,source_url:match?match[0]:""}));
  $("notice").textContent=d.ticket.id+" · в очереди Claude. Статус сменится только после реального запуска.";
  el.value="";$("newBody").value="";await load();
 }catch(e){$("notice").textContent="Задание не создано: "+String(e.message||e)}
 finally{$("submit").disabled=false}
}
async function startTicket(id){
 try{const d=await api("/api/relay/"+encodeURIComponent(id)+"/run",send("POST",{}));$("notice").textContent=id+" · "+(d.ticket.execution?.state||"queued");await load()}
 catch(e){$("notice").textContent="Не удалось поставить "+id+" в очередь: "+e.message}
}
async function detailTicket(id){
 try{
  const t=await api("/api/relay/"+encodeURIComponent(id));
  $("detailsTitle").textContent=t.id+" · "+t.title;
  const e=t.execution||{},history=[...(t.history||[])].reverse();
  let html='<p class="desc">Исполнитель: '+esc(e.owner||"Claude")+' · '+esc(states[e.state]||e.state||"не назначено")+'</p>';
  if(t.body)html+='<p class="desc">'+esc(t.body)+'</p>';
  const icons={recorded:"✅",linked:"🔗",pending:"⏳",unverified:"❔"};
  html+='<h2>Этапы (факт из Relay)</h2>'+(t.lifecycle||[]).map(r=>'<div class="line">'+esc(icons[r.state]||"•")+' '+esc(r.stage)+
    (r.state==="unverified"?' — не проверено':'')+(r.at?' · '+esc(String(r.at).slice(0,19).replace("T"," "))+' UTC':'')+
    (r.detail?' · '+esc(String(r.detail).slice(0,120)):'')+'</div>').join("");
  html+='<h2>Хронология ('+history.length+')</h2>';
  html+=history.map(ev=>'<div class="event"><time>'+esc(ev.at||"")+'</time><strong>'+esc(ev.action||"")+' · '+esc(ev.actor||"")+'</strong>'+
    '<p>'+esc(ev.note||"")+'</p>'+
    (ev.evidence?.commit?'<p>Commit: '+esc(ev.evidence.commit)+' (отчёт worker)</p>':'')+'</div>').join("");
  $("detailsBody").innerHTML=html;
  $("details").showModal();
 }catch(e){$("notice").textContent="Ошибка истории: "+e.message}
}
$("board").addEventListener("click",ev=>{
 const target=ev.target.closest("button");if(!target)return;
 if(target.dataset.detail)detailTicket(target.dataset.detail);
 if(target.dataset.run)startTicket(target.dataset.run);
});
$("newForm").addEventListener("submit",createTicket);
async function telegramStatus(){
 try{const s=await api("/api/factory/telegram/status");
 $("tgBtn").textContent=s.paired?"✅ Telegram подключён":"Подключить Telegram";
 $("tgState").textContent=s.paired?(s.username?"@"+s.username:"готов"):(s.configured?"ожидает привязки":"бот не настроен");
 }catch(e){$("tgState").textContent="не удалось проверить Telegram"}
}
async function pairWorker(){
 if(!confirm("Создать новый токен AWS worker? Предыдущий токен этого способа привязки станет недействительным."))return;
 try{
  const response=await api("/api/factory/claude-code/pair-token",send("POST",{}));
  $("pairToken").value=response.token;
  $("pairDialog").showModal();
 }catch(e){$("notice").textContent="Не удалось создать токен привязки: "+e.message}
}
function copyPairToken(){
 const token=$("pairToken").value;
 if(navigator.clipboard?.writeText)navigator.clipboard.writeText(token).then(()=>$("notice").textContent="Токен скопирован. Вставь в AWS Session Manager.").catch(()=>$("pairToken").select());
 else $("pairToken").select();
}
$("pairDialog").addEventListener("close",()=>{$("pairToken").value=""});
async function pairTelegram(){
 try{const s=await api("/api/factory/telegram/status");if(s.paired){$("notice").textContent="Telegram уже привязан; открой существующий чат и отправь /tasks";return}
 const d=await api("/api/factory/telegram/pairing/start",send("POST",{}));$("tgState").textContent="Код действует "+Math.round(d.expires_in_seconds/60)+" минут";if(d.deep_link)window.location.href=d.deep_link;else alert("Отправь боту: "+d.command);
 }catch(e){$("notice").textContent="Не удалось привязать Telegram: "+e.message}
}
load();telegramStatus();setInterval(load,5000);setInterval(telegramStatus,30000);
</script></body></html>"""
