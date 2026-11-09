"""#129 FactoryOS Team: one private Telegram group where the owner discusses with the agents (owner, 2026-11-09:
group "FactoryOS Team" created, the existing bot added; the bot runs in privacy mode, so it only sees commands
and replies to its own messages — that is all this bridge needs).

- Pairing: the owner sends /group in the bot's private chat and gets a one-time code (10 min); posting
  `/pair_group CODE` in the group binds that group's chat id. Only the paired owner (Telegram user id = the owner's
  private chat id) can pair, discuss, stop or record decisions; other members and other groups are ignored.
  `/group off` in the private chat unbinds it.
- `/discuss <topic>` opens a discussion thread and asks Claude through the existing owner-question queue (the same
  worker as /ask, existing subscription, no paid API). The owner's replies to the bot continue the open thread.
  Claude's real answer is posted back into the group labelled [Claude]. ChatGPT and Gemini have no Relay runner,
  so they are shown as unavailable — never imitated.
- `/stop` closes the thread: answers that arrive later are not posted to the group.
- `/decision <text>` shows a preview with ✅/✖ buttons; only after the owner confirms is it recorded (versioned,
  in this bridge's own store — no prod or rules files are edited).
- Telegram update ids are deduplicated, so a webhook retry never creates a second question.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

CODE_TTL = 600
MAX_TEXT = 1500
GROUP_TYPES = ("group", "supergroup")
UNAVAILABLE = "ChatGPT и Gemini: нет Relay-runner — в этой группе отвечает только Claude (не имитируем)."


def _cmd(text: str) -> tuple[str, str]:
    """('/discuss', 'rest') with any @BotName suffix removed."""
    text = str(text or "").strip()
    if not text.startswith("/"):
        return "", text
    head, _, rest = text.partition(" ")
    return head.split("@", 1)[0].lower(), rest.strip()


class GroupBridge:
    def __init__(self, data_dir: Path, *, ask: Callable[..., dict], clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "telegram-group.json"
        self.ask = ask          # ask(question_text, source_key=..., meta=...) -> question item
        self.clock = clock
        self._lock = threading.Lock()

    # --- storage ---
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            pass
        return {"group_id": "", "codes": {}, "threads": [], "decisions": [], "pending": {}, "seen": []}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def status(self) -> dict:
        with self._lock:
            d = self._load()
        open_t = [t for t in d.get("threads", []) if t.get("status") == "open"]
        return {"paired": bool(d.get("group_id")), "open_threads": len(open_t), "decisions": len(d.get("decisions", []))}

    # --- private chat: pairing ---
    def handle_private(self, text: str) -> Optional[str]:
        cmd, rest = _cmd(text)
        if cmd != "/group":
            return None
        with self._lock:
            d = self._load()
            if rest.lower() in ("off", "unpair", "выкл"):
                had = bool(d.get("group_id"))
                d.update(group_id="", codes={})
                self._save(d)
                return "Группа отвязана." if had else "Группа и так не привязана."
            now = self.clock()
            d["codes"] = {c: exp for c, exp in (d.get("codes") or {}).items() if exp > now}
            code = secrets.token_hex(3).upper()
            d["codes"][code] = now + CODE_TTL
            self._save(d)
        return (f"Код привязки группы: {code} (10 минут).\nОтправь в группе «FactoryOS Team»: /pair_group {code}\n"
                "Сейчас привязана: " + ("да" if d.get("group_id") else "нет") + ". Отвязать: /group off")

    # --- group ---
    def handle_group(self, update: dict, owner_id: str, send: Callable[[str, str, Optional[dict]], Any]) -> dict:
        """Returns {"handled": bool, "action": ...}. `send(chat_id, text, reply_markup)`."""
        if "callback_query" in update:
            return self._callback(update["callback_query"], owner_id, send)
        msg = update.get("message") if isinstance(update.get("message"), dict) else {}
        chat = msg.get("chat") if isinstance(msg.get("chat"), dict) else {}
        if chat.get("type") not in GROUP_TYPES:
            return {"handled": False}
        chat_id = str(chat.get("id") or "")
        sender = str((msg.get("from") or {}).get("id") or "")
        text = str(msg.get("text") or "")
        cmd, rest = _cmd(text)
        update_id = str(update.get("update_id") or "")
        with self._lock:
            d = self._load()
            if update_id and update_id in d.get("seen", []):
                return {"handled": True, "action": "duplicate"}
            d["seen"] = (d.get("seen", []) + ([update_id] if update_id else []))[-300:]
            self._save(d)
        if not owner_id or sender != str(owner_id):
            return {"handled": True, "action": "ignored_member"}     # silently: members and other bots get nothing
        if cmd == "/pair_group":
            return self._pair(chat_id, rest.upper(), send)
        with self._lock:
            d = self._load()
        if not d.get("group_id") or d["group_id"] != chat_id:
            if cmd:
                send(chat_id, "Эта группа не привязана. В личке с ботом: /group, затем здесь /pair_group КОД.", None)
            return {"handled": True, "action": "unbound_group"}
        replied_to_bot = bool(((msg.get("reply_to_message") or {}).get("from") or {}).get("is_bot"))
        if cmd == "/discuss":
            return self._discuss(chat_id, rest, update_id, send)
        if cmd == "/stop":
            return self._stop(chat_id, send)
        if cmd == "/decision":
            return self._decision_preview(chat_id, rest, send)
        if cmd == "/decisions":
            items = d.get("decisions", [])[-5:]
            send(chat_id, "Решения (последние 5):\n" + ("\n".join(f"v{x['version']} · {x['text'][:200]}" for x in items) or "пока нет"), None)
            return {"handled": True, "action": "decisions"}
        if replied_to_bot and text.strip() and not cmd:
            return self._follow_up(chat_id, text, update_id, send)
        if cmd in ("/help", "/start"):
            send(chat_id, "В группе: /discuss тема · ответь боту, чтобы продолжить · /stop · /decision текст · /decisions", None)
            return {"handled": True, "action": "help"}
        return {"handled": True, "action": "ignored"}

    def _pair(self, chat_id: str, code: str, send) -> dict:
        with self._lock:
            d = self._load()
            exp = (d.get("codes") or {}).pop(code, None) if code else None
            if not exp or exp < self.clock():
                self._save(d)
                send(chat_id, "Код неверный или просрочен. В личке с ботом: /group — получить новый.", None)
                return {"handled": True, "action": "pair_refused"}
            d["group_id"] = chat_id
            d["paired_at"] = int(self.clock())
            self._save(d)
        send(chat_id, "✅ Группа привязана. /discuss тема — начать обсуждение с Claude.\n" + UNAVAILABLE, None)
        return {"handled": True, "action": "paired"}

    def _open_thread(self, d: dict) -> Optional[dict]:
        return next((t for t in reversed(d.get("threads", [])) if t.get("status") == "open"), None)

    def _discuss(self, chat_id: str, topic: str, update_id: str, send) -> dict:
        topic = " ".join(topic.split())[:MAX_TEXT]
        if not topic:
            send(chat_id, "Пример: /discuss как сделать релиз MyCast на следующей неделе", None)
            return {"handled": True, "action": "discuss_help"}
        with self._lock:
            d = self._load()
            for t in d.get("threads", []):
                if t.get("status") == "open":
                    t["status"] = "superseded"
            tid = "D-%04d" % (len(d.get("threads", [])) + 1)
            d.setdefault("threads", []).append({"id": tid, "topic": topic, "status": "open", "created": int(self.clock()),
                                                "questions": [], "last_answer": ""})
            self._save(d)
        item = self.ask("Обсуждение в группе FactoryOS Team (" + tid + "). Тема: " + topic,
                        source_key="tg-group:" + (update_id or tid), meta={"group_thread": tid})
        self._link(tid, item)
        send(chat_id, f"🧵 {tid}: {topic}\n[Claude] вопрос принят ({item.get('id')}) — ответ появится здесь, когда воркер его заберёт.\n" + UNAVAILABLE, None)
        return {"handled": True, "action": "discuss", "thread": tid, "question": item.get("id")}

    def _follow_up(self, chat_id: str, text: str, update_id: str, send) -> dict:
        with self._lock:
            d = self._load()
            t = self._open_thread(d)
        if not t:
            send(chat_id, "Нет открытого обсуждения. Начни: /discuss тема", None)
            return {"handled": True, "action": "no_thread"}
        context = ("Тема: " + t["topic"] + ("\nПредыдущий ответ Claude (кратко): " + t["last_answer"][:800] if t.get("last_answer") else ""))
        item = self.ask("Продолжение обсуждения " + t["id"] + ".\n" + context + "\nВладелец: " + text.strip()[:MAX_TEXT],
                        source_key="tg-group:" + (update_id or t["id"] + str(self.clock())), meta={"group_thread": t["id"]})
        self._link(t["id"], item)
        send(chat_id, f"[Claude] принял продолжение {t['id']} ({item.get('id')}).", None)
        return {"handled": True, "action": "follow_up", "thread": t["id"]}

    def _link(self, tid: str, item: dict) -> None:
        with self._lock:
            d = self._load()
            for t in d.get("threads", []):
                if t["id"] == tid and item.get("id") not in t["questions"]:
                    t["questions"].append(item.get("id"))
            self._save(d)

    def _stop(self, chat_id: str, send) -> dict:
        with self._lock:
            d = self._load()
            t = self._open_thread(d)
            if t:
                t["status"] = "stopped"
                t["stopped"] = int(self.clock())
            self._save(d)
        send(chat_id, (f"⏹ {t['id']} остановлено: поздние ответы сюда не придут." if t else "Нет открытого обсуждения."), None)
        return {"handled": True, "action": "stopped" if t else "nothing_to_stop"}

    def _decision_preview(self, chat_id: str, text: str, send) -> dict:
        text = " ".join(text.split())[:MAX_TEXT]
        if not text:
            send(chat_id, "Пример: /decision Публичный запуск MyCast — после теста голосовой доставки", None)
            return {"handled": True, "action": "decision_help"}
        pid = secrets.token_hex(3)
        with self._lock:
            d = self._load()
            d.setdefault("pending", {})[pid] = text
            self._save(d)
        send(chat_id, "Записать решение?\n«" + text + "»",
             {"inline_keyboard": [[{"text": "✅ Записать", "callback_data": f"grp:dec:{pid}:yes"},
                                   {"text": "✖ Отмена", "callback_data": f"grp:dec:{pid}:no"}]]})
        return {"handled": True, "action": "decision_preview", "pending": pid}

    def _callback(self, cb: dict, owner_id: str, send) -> dict:
        data = str(cb.get("data") or "")
        m = re.fullmatch(r"grp:dec:([0-9a-f]{6}):(yes|no)", data)
        if not m:
            return {"handled": False}
        chat_id = str(((cb.get("message") or {}).get("chat") or {}).get("id") or "")
        if str((cb.get("from") or {}).get("id") or "") != str(owner_id):
            return {"handled": True, "action": "ignored_member"}
        pid, answer = m.groups()
        with self._lock:
            d = self._load()
            if d.get("group_id") != chat_id:
                return {"handled": True, "action": "unbound_group"}
            text = (d.get("pending") or {}).pop(pid, None)
            if text and answer == "yes":
                version = len(d.get("decisions", [])) + 1
                d.setdefault("decisions", []).append({"version": version, "text": text, "at": int(self.clock()),
                                                      "thread": (self._open_thread(d) or {}).get("id", "")})
            self._save(d)
        if not text:
            send(chat_id, "Это решение уже обработано.", None)
            return {"handled": True, "action": "decision_stale"}
        send(chat_id, (f"📌 Решение v{version} записано." if answer == "yes" else "Решение не записано."), None)
        return {"handled": True, "action": "decision_" + answer}

    # --- answers from the existing Claude question worker ---
    def deliver_answer(self, item: dict, send: Callable[[str, str, Optional[dict]], Any]) -> bool:
        """True when the answer belongs to a group thread (posted, or deliberately dropped after /stop)."""
        tid = ((item.get("meta") or {}).get("group_thread")) if isinstance(item.get("meta"), dict) else None
        if not tid:
            return False
        with self._lock:
            d = self._load()
            t = next((x for x in d.get("threads", []) if x["id"] == tid), None)
            group = d.get("group_id")
            if t is not None:
                t["last_answer"] = str(item.get("answer") or "")[:2000]
            self._save(d)
        if not t or t.get("status") != "open" or not group:
            return True                                                   # stopped: never posted later
        answer = str(item.get("answer") or "") or "Claude вернул пустой ответ."
        parts = [answer[i:i + 3800] for i in range(0, len(answer), 3800)]
        for n, part in enumerate(parts, 1):
            send(group, f"[Claude] {tid} · {item.get('id')} ({n}/{len(parts)})\n{part}", None)
        return True
