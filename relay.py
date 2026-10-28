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


class RelayWorkerEventRequest(BaseModel):
    ticket_id: str
    worker_id: str
    stage: str
    note: str = ""
    evidence: dict = {}


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


def _relay_status_text(store: RelayStore, provider: Optional[Callable[[], dict]]) -> str:
    summary = store.summary()
    tickets = store.list(limit=500)
    stages = [str((t.get("execution") or {}).get("state") or "") for t in tickets]
    lines = ["📡 FactoryOS Relay", "Связь с Telegram: ✅",
             "Тикетов: " + str(summary["total"]) + " · активных: " + str(summary["active"]),
             "Очередь: " + str(stages.count("queued")) + " · работа: " + str(sum(x in ("claimed", "running", "checkpoint", "committed", "pushed") for x in stages)),
             "ChatGPT: нет автоматической телеметрии"]
    if provider:
        try:
            lanes = provider() or {}
            for name in ("claude", "gemini"):
                lane = lanes.get(name) or {}
                online = lane.get("online") is True
                age = lane.get("heartbeat_age_seconds")
                task = str(lane.get("active_task_id") or "")
                desc = "online" if online else str(lane.get("state") or "offline")
                if age is not None:
                    desc += " · heartbeat " + str(age) + " сек назад"
                if task:
                    desc += " · " + task
                lines.append(name.capitalize() + ": " + desc)
        except Exception:
            lines.append("Воркеры: данные недоступны")
    else:
        lines.append("Воркеры: телеметрия не подключена")
    return "\n".join(lines)[:3900]


def _relay_tasks_text(store: RelayStore, provider: Optional[Callable[[], dict]], github: Optional[Callable[[], dict]]) -> str:
    lines = [_active_list_text(store), "", "— Исполнители —"]
    if provider:
        try:
            lanes = provider() or {}
            for name in ("claude", "gemini"):
                lane = lanes.get(name) or {}
                state = "online" if lane.get("online") is True else str(lane.get("state") or "offline")
                lines.append(name.capitalize() + ": " + state + (" · " + str(lane.get("active_task_id")) if lane.get("active_task_id") else ""))
        except Exception:
            lines.append("Телеметрия исполнителей недоступна")
    else:
        lines.append("Нет телеметрии воркеров")
    lines.append("ChatGPT: нет автоматической телеметрии")
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
        if data.startswith("relay:overview:"):
            action = data.split(":")[-1]
            telegram_api("answerCallbackQuery", {"callback_query_id": callback_id})
            if action == "tasks":
                value = _relay_tasks_text(store, operator_status_provider, github_provider)
            elif action == "history":
                value = _relay_history_text(store, github_provider)
            elif action == "github":
                value = _github_text(github_provider() if github_provider else {"available": False})
            elif action == "workers":
                value = _operators_overview_text(operator_status_provider)
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
    if command in ("/pair", "/start"):
        return None
    if command == "/status":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_status_text(store, operator_status_provider), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "status"}
    if command in ("/relay", "/tasks"):
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_tasks_text(store, operator_status_provider, github_provider), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "list"}
    if command == "/history":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_history_text(store, github_provider), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "history"}
    if command == "/github":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _github_text(github_provider() if github_provider else {"available": False}), "reply_markup": _relay_keyboard()})
        return {"handled": True, "action": "github"}
    if command == "/roadmap":
        telegram_api("sendMessage", {"chat_id": chat_id, "text": _relay_tasks_text(store, operator_status_provider, github_provider), "reply_markup": _relay_keyboard()})
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
            if match:
                detail = "🔗 GitHub #" + number + "\n" + str(match.get("title") or "") + "\nСтатус: open (проверено в GitHub)\n" + str(match.get("url") or "")
            else:
                detail = "GitHub #" + number + ": нет в текущей выборке открытых задач. Статус неизвестен; проверь GitHub."
            telegram_api("sendMessage", {"chat_id": chat_id, "text": detail, "reply_markup": _relay_keyboard()})
            return {"handled": True, "action": "github_issue", "number": number}
        ticket = store.get(ticket_id)
        if not ticket:
            telegram_api("sendMessage", {"chat_id": chat_id, "text": "Задача не найдена. Пример: /task R-0001"})
            return {"handled": True}
        history = ticket.get("history") or []
        lines = [_ticket_card(ticket), ("ТЗ: " + str(ticket.get("body") or "")[:450]) if ticket.get("body") else "", "История:"]
        for event in history[-12:]:
            evidence = event.get("evidence") or {}
            commit = " · " + str(evidence.get("commit") or "")[:10] if evidence.get("commit") else ""
            lines.append(f"{str(event.get('at') or '')[:19]} · {event.get('actor') or '?'} · {event.get('action') or '?'}{commit} · {str(event.get('note') or '')[:120]}")
        telegram_api("sendMessage", {"chat_id": chat_id, "text": "\n".join(lines)[:3900], "reply_markup": _ticket_keyboard(ticket_id)})
        return {"handled": True, "action": "detail", "ticket_id": ticket_id}
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

    @app.post("/api/relay/worker/event")
    def relay_worker_event(payload: RelayWorkerEventRequest, request: Request):
        _require_worker(request)
        try:
            ticket = queue.event(payload.ticket_id, payload.worker_id, payload.stage, payload.note, payload.evidence)
        except KeyError:
            raise HTTPException(404, "Relay ticket not found")
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        if payload.stage not in {"heartbeat", "checkpoint"} and notify_owner:
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
<div class="toprow"><button id="tgBtn" onclick="pairTelegram()">Telegram…</button><span class="sub" id="tgState"></span><button onclick="load()">↻ Обновить</button></div>
<div id="notice" class="notice"></div>
</header>
<main id="board"></main><div id="footer">Статус «в работе» появляется только после запуска исполнителя. Коммит и push — отдельные подтверждаемые события.</div>
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
async function pairTelegram(){
 try{const s=await api("/api/factory/telegram/status");if(s.paired){$("notice").textContent="Telegram уже привязан; открой существующий чат и отправь /tasks";return}
 const d=await api("/api/factory/telegram/pairing/start",send("POST",{}));$("tgState").textContent="Код действует "+Math.round(d.expires_in_seconds/60)+" минут";if(d.deep_link)window.location.href=d.deep_link;else alert("Отправь боту: "+d.command);
 }catch(e){$("notice").textContent="Не удалось привязать Telegram: "+e.message}
}
load();telegramStatus();setInterval(load,5000);setInterval(telegramStatus,30000);
</script></body></html>"""
