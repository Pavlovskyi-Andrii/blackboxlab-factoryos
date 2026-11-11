"""MVP Builder project cycle (owner 2026-11-11): Battle → Build → Promote → Learn, five agents, a chat per agent.

Step 1 only shows facts and routes messages; it never advances a stage or starts a build on its own.
- Phases and agent statuses are derived from the project's recorded stage (mvp_factory: stages move only through
  recorded events with evidence). Learn has no stage yet: it shows "not started" until real metrics exist.
- Agents are roles with different instructions, run by the engines we actually have: Gemini (owner's free key) for
  research and spec, Claude (subscription, through the EC2 worker) for build and QA, Content Factory for promotion.
- A message to an agent is stored in the project chat. Gemini agents answer right away; Claude agents get the
  message through the existing owner-question queue and the worker's answer is written back into the chat.
- "Stop" / "Resume" use the registry's block/unblock events (owner-visible, recorded), nothing new.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Optional

PHASES = [
    {"id": "battle", "icon": "⚔️", "stages": ["idea", "researching", "spec_draft", "spec_review"]},
    {"id": "build", "icon": "🔨", "stages": ["build_queued", "building", "qa_review", "preview_ready", "owner_review"]},
    {"id": "promote", "icon": "📣", "stages": ["validated"]},
    {"id": "learn", "icon": "📊", "stages": []},
]
AGENTS = [
    {"id": "researcher", "label": "Researcher", "engine": "gemini", "stages": ["idea", "researching"],
     "does": "Аудиторія, конкуренти, проблема, ідеї для Battle", "needs": ["gemini"]},
    {"id": "spec", "label": "Spec Writer", "engine": "gemini", "stages": ["spec_draft", "spec_review"],
     "does": "Технічне завдання з критеріями «готово, коли»", "needs": ["gemini"]},
    {"id": "builder", "label": "Builder", "engine": "claude", "stages": ["build_queued", "building"],
     "does": "Код в окремій гілці, PR, CI", "needs": ["github", "claude_worker"]},
    {"id": "qa", "label": "QA / Security", "engine": "claude", "stages": ["qa_review", "preview_ready", "owner_review"],
     "does": "Тести, секрети, доступи, прев'ю на Render", "needs": ["github", "render"]},
    {"id": "promoter", "label": "Promoter", "engine": "content_factory", "stages": ["validated"],
     "does": "Сайт, розсилка, соцмережі — тільки з твоїм «так» на публікацію", "needs": ["channels"]},
]
AGENT_IDS = {a["id"] for a in AGENTS}
NEED_LABELS = {"gemini": "Gemini (безкоштовний ключ)", "github": "GitHub (читання)", "claude_worker": "Claude-воркер на EC2",
               "render": "Render (прев'ю)", "channels": "Канали проєкту: сайт, пошта, YouTube, Telegram, TikTok…"}
MAX_MESSAGE = 1500
MAX_THREAD = 60


def _stage_order() -> list:
    return [s for p in PHASES for s in p["stages"]]


def cycle_view(project: dict, connections: dict, chat: dict) -> dict:
    """Facts for the panel: the current phase, each agent's status, what it produced, what to connect, its chat."""
    stage = str(project.get("stage") or "idea")
    order = _stage_order()
    pos = order.index(stage) if stage in order else -1
    blocked = project.get("blocked")
    phase = next((p["id"] for p in PHASES if stage in p["stages"]), "battle" if stage != "rejected" else "")
    history = project.get("history") or []
    agents = []
    for a in AGENTS:
        idx = [order.index(s) for s in a["stages"] if s in order]
        if stage == "rejected":
            status = "stopped"
        elif stage in a["stages"]:
            status = "blocked" if blocked else "working"
        elif idx and pos > max(idx):
            status = "done"
        else:
            status = "waiting"
        events = [e for e in history if e.get("to_stage") in a["stages"] or e.get("from_stage") in a["stages"]][-8:]
        links = []
        for e in events:
            for link in e.get("evidence") or []:
                if link not in links:
                    links.append(link)
        agents.append({**{k: a[k] for k in ("id", "label", "engine", "does")}, "status": status,
                       "events": [{"at": e.get("at"), "kind": e.get("kind"), "to_stage": e.get("to_stage"),
                                   "note": e.get("note") or ""} for e in events],
                       "links": links[:8],
                       "needs": [{"id": n, "label": NEED_LABELS.get(n, n), "ok": bool(connections.get(n))} for n in a["needs"]],
                       "chat": (chat.get(a["id"]) or [])[-20:]})
    return {"project": project.get("id"), "stage": stage, "phase": phase, "blocked": blocked,
            "phases": [{"id": p["id"], "icon": p["icon"], "current": p["id"] == phase,
                        "done": bool(p["stages"]) and pos > max(order.index(s) for s in p["stages"])} for p in PHASES],
            "agents": agents,
            "note": "Етапи рухаються тільки через записані події з доказами; панель нічого не запускає сама."}


class AgentChat:
    """Per project, per agent message thread (owner ↔ agent). One small JSON file; bounded."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time):
        self.path, self.clock = Path(data_dir) / "mvp_agent_chat.json", clock
        self._lock = threading.Lock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def thread(self, project_id: str) -> dict:
        with self._lock:
            return dict(self._load().get(project_id) or {})

    def add(self, project_id: str, agent: str, author: str, text: str, ref: str = "") -> dict:
        if agent not in AGENT_IDS:
            raise ValueError("unknown_agent")
        text = re.sub(r"[\u0000-\u0008\u000b-\u001f]", "", str(text or "")).strip()[:MAX_MESSAGE]
        if not text:
            raise ValueError("empty_message")
        msg = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.clock())), "author": author[:20],
               "text": text, "ref": ref[:40]}
        with self._lock:
            data = self._load()
            thread = data.setdefault(project_id, {}).setdefault(agent, [])
            thread.append(msg)
            del thread[:-MAX_THREAD]
            self._save(data)
        return msg


def agent_prompt(project: dict, agent: dict, text: str, chat: list) -> str:
    recent = "\n".join(f"{m['author']}: {m['text'][:400]}" for m in (chat or [])[-6:])
    return (f"Ти — агент «{agent['label']}» у MVP Builder (FactoryOS). Твоя роль: {agent['does']}.\n"
            f"Проєкт: {project.get('title')}. Поточний етап: {project.get('stage')}.\n"
            f"Технічне завдання власника:\n{str(project.get('brief') or '—')[:3000]}\n\n"
            f"Останні повідомлення:\n{recent or '—'}\n\n"
            f"Власник пише тобі: {text}\n\n"
            "Відповідай українською або тією мовою, якою пише власник, по суті, до 1200 символів. "
            "Не вигадуй результатів, цифр, клієнтів чи статусів, яких немає. Не стверджуй, що щось запущено чи "
            "опубліковано. Якщо потрібне рішення власника — скажи прямо, яке.")
