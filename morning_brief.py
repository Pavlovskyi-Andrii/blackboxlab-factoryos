"""#106 Morning brief at 08:00 Europe/Kyiv, voiced in the owner's host-A voice, to the owner's own paired chat.

Owner opt-in (authorised 2026-11-01 in #106): off until the owner sends `/brief on` in the paired private chat.
`/brief test` sends the composed text only (no voice, no Gemini call) so the owner can check it first.

Content is built from data FactoryOS already holds, never invented: PRs merged in the last 24 h and open PRs with
red CI (fresh EC2 GitHub snapshot), active Relay tickets, open owner questions. World news stays in the MyCast
episode (06:00), so nothing here repeats web content. No snapshot → the brief says GitHub status is unknown.

Schedule: one brief per Kyiv date, first try at 08:00, up to 3 tries 20 min apart, none after 11:00 (a restart at
noon does not send a stale morning brief). The voice path shares the worker route's once-per-date delivery log,
so a brief is never sent twice. After the last failed try the owner gets the text plus one explicit failure note.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
START_HOUR, LAST_HOUR = 8, 11
MAX_TRIES, RETRY_GAP = 3, 20 * 60
_NOISE = re.compile(r"\(?#\d+\)?|\bT-\d+[A-Z0-9-]*\b|\bP[0-3]\b|^\s*(?:feat|fix|chore|docs|test|refactor|ci|perf)(?:\([^)]*\))?!?:\s*", re.I)


def _clean_title(title: str) -> str:
    """The owner asked for no task/PR numbers or priority codes in spoken text (MyCast feedback, 2026-11-05)."""
    t = _NOISE.sub(" ", str(title or "")).strip(" -·:+,")
    return re.sub(r"\s+", " ", t)[:90]


def _ts(value) -> Optional[float]:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def compose_brief(date: str, now: float, *, github: Optional[dict], tickets: list, questions_open: int,
                  evidence_metrics: Optional[dict] = None) -> str:
    lines = [f"Доброго ранку. Ранковий брифінг FactoryOS на {date}."]
    if github is None:
        lines.append("Дані GitHub зараз недоступні, тому статус PR невідомий.")
    else:
        pulls = [p for p in github.get("pulls") or [] if isinstance(p, dict)]
        merged = [p for p in pulls if (_ts(p.get("merged_at")) or 0) >= now - 86400]
        if merged:
            titles = [t for t in (_clean_title(p.get("title")) for p in merged[:4]) if t]
            lines.append(f"За добу влито змін: {len(merged)}." + (" Серед них: " + "; ".join(titles) + "." if titles else ""))
        else:
            lines.append("За добу нових злиттів не було.")
        ci = github.get("ci") if isinstance(github.get("ci"), dict) else {}
        open_prs = [p for p in pulls if p.get("state") == "open" and not p.get("draft")]
        red = [p for p in open_prs if (ci.get(str((p.get("head") or {}).get("sha") or "")) or {}).get("state") == "failed"]
        if open_prs:
            lines.append(f"Відкритих PR: {len(open_prs)}" + (f", з червоним CI: {len(red)}." if red else ", червоного CI немає."))
    active = [t for t in tickets if isinstance(t, dict) and t.get("status") in ("inbox", "in_progress", "need_you")]
    need_you = sum(1 for t in active if t.get("status") == "need_you")
    if active:
        lines.append(f"У Relay активних задач: {len(active)}" + (f", чекають на тебе: {need_you}." if need_you else "."))
    else:
        lines.append("У Relay активних задач немає.")
    if questions_open:
        lines.append(f"Відкритих питань до команди: {questions_open}.")
    m = evidence_metrics or {}
    if any(m.get(k) for k in ("verified", "overridden", "rejected", "waiting")):
        # Evidence T2.5: what was proven, what the owner closed by hand, and "done" still waiting for proof.
        lines.append(f"Докази за тиждень: підтверджено {m.get('verified', 0)}, закрито вручну {m.get('overridden', 0)}, "
                     f"повернуто тобою {m.get('rejected', 0)}. Агент сказав «готово», але доказів ще немає: {m.get('waiting', 0)}.")
    lines.append("Новини світу AI — у випуску MyCast. Гарного дня.")
    return "\n".join(lines)[:1400]


class MorningBrief:
    def __init__(self, data_dir: Path, *, deliver: Callable[[str, str], dict], send_text: Callable[[str], object],
                 compose: Callable[[str, float], str], clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "morning_brief.json"
        self.deliver, self.send_text, self.compose, self.clock = deliver, send_text, compose, clock
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

    def _local(self) -> datetime:
        return datetime.fromtimestamp(self.clock(), KYIV)

    def status(self) -> dict:
        s = self._load()
        return {"enabled": bool(s.get("enabled")), "last": s.get("last") or {}}

    def handle_private(self, text: str) -> Optional[str]:
        """Owner's paired private chat only (the caller checks the chat). None = not a /brief command."""
        parts = str(text or "").strip().split()
        if not parts or parts[0].split("@")[0].lower() != "/brief":
            return None
        arg = parts[1].lower() if len(parts) > 1 else ""
        with self._lock:
            s = self._load()
            if arg in ("on", "off"):
                s["enabled"] = arg == "on"
                self._save(s)
                if arg == "off":
                    return "Ранковий брифінг вимкнено."
                return ("Ранковий брифінг увімкнено: щодня о 08:00 за Києвом, голосом ведучого A, у цей чат. "
                        "Спершу перевір текст: /brief test. Вимкнути: /brief off.")
        if arg == "test":
            local = self._local()
            return "Тест (тільки текст, без голосу):\n\n" + self.compose(local.strftime("%Y-%m-%d"), self.clock())
        last = s.get("last") or {}
        state = "увімкнено, 08:00 Київ" if s.get("enabled") else "вимкнено"
        tail = f"\nОстанній: {last.get('date')} · {last.get('status')}" if last else ""
        return f"Ранковий брифінг: {state}.{tail}\nКоманди: /brief on · /brief off · /brief test"

    def tick(self) -> Optional[dict]:
        """Called about once a minute. Blocking (voice synthesis); run it off the event loop."""
        local = self._local()
        if not START_HOUR <= local.hour < LAST_HOUR:
            return None
        date, now = local.strftime("%Y-%m-%d"), self.clock()
        with self._lock:
            s = self._load()
            run = (s.get("runs") or {}).get(date) or {}
            if not s.get("enabled") or run.get("done") or int(run.get("tries") or 0) >= MAX_TRIES \
                    or now - float(run.get("last_try") or 0) < RETRY_GAP:
                return None
            run = {**run, "tries": int(run.get("tries") or 0) + 1, "last_try": now}
            s["runs"] = {date: run, **{k: v for k, v in (s.get("runs") or {}).items() if k != date and k > _days_ago(local, 7)}}
            self._save(s)
        text = self.compose(date, now)
        try:
            out = self.deliver(date, text)
            status, detail = ("sent" if out.get("sent") else "duplicate"), ""
        except Exception as exc:  # BriefError or anything else: category/status only, never provider text
            status, detail = "failed", str(getattr(exc, "detail", "") or type(exc).__name__)[:60]
        done = status != "failed" or run["tries"] >= MAX_TRIES
        if status == "sent":
            self._safe_send("📝 Текст брифінгу:\n" + text)
        elif status == "failed" and done:
            self._safe_send(text + f"\n\n⚠️ Голосовий брифінг не доставлено ({detail}) після {MAX_TRIES} спроб. Це текстова версія.")
        with self._lock:
            s = self._load()
            runs = s.get("runs") or {}
            runs[date] = {**(runs.get(date) or {}), "done": done, "status": status, "detail": detail}
            s["runs"], s["last"] = runs, {"date": date, "status": status if done else f"retry ({detail})"}
            self._save(s)
        print(json.dumps({"event": "MORNING_BRIEF", "date": date, "status": status, "try": run["tries"], "detail": detail}), flush=True)
        return {"date": date, "status": status, "done": done}

    def _safe_send(self, text: str) -> None:
        try:
            self.send_text(text)
        except Exception:
            pass


def _days_ago(local: datetime, days: int) -> str:
    return (local - timedelta(days=days)).strftime("%Y-%m-%d")
