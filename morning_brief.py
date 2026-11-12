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


ACTIVE = ("inbox", "in_progress", "need_you")
AGENTS = {"claude": "Claude", "gemini": "Gemini", "chatgpt": "ChatGPT"}


def _closed_at(t: dict) -> Optional[float]:
    for h in reversed(t.get("history") or []):
        if h.get("to_status") == "done":
            return _ts(h.get("at"))
    return None


def plan_ids(tickets: list) -> list:
    """Today's plan: agent work that is queued or running (not waiting for the owner)."""
    return [t["id"] for t in tickets or [] if isinstance(t, dict) and t.get("status") in ("inbox", "in_progress")
            and str((t.get("execution") or {}).get("owner") or "") in AGENTS]


def _row(t: dict) -> str:
    return f"{t.get('id')} {_clean_title(t.get('title')) or '—'}"


def compose_brief(date: str, now: float, *, github: Optional[dict], tickets: list, questions_open: int,
                  evidence_metrics: Optional[dict] = None, yesterday_plan: Optional[dict] = None) -> str:
    """Owner feedback 2026-11-11: what was done, what was not, plan vs fact with a completion rate, today's plan,
    what waits for the owner. Lines starting with two spaces are details: text only, not read out by the voice."""
    tickets = [t for t in tickets or [] if isinstance(t, dict)]
    by_id = {t.get("id"): t for t in tickets}
    lines = [f"☀️ Доброго ранку! Брифінг FactoryOS · {date}"]

    closed = [t for t in tickets if t.get("status") == "done" and (_closed_at(t) or 0) >= now - 86400]
    manual = sum(1 for t in closed if (t.get("verification") or {}).get("override"))
    lines.append(f"📊 Вчора закрито задач: {len(closed)}" + (f" (з них вручну: {manual})" if manual else "") + ".")
    lines += ["  ✅ " + _row(t) for t in closed[:6]]
    if github is None:
        lines.append("🔗 GitHub зараз недоступний, тому про PR сьогодні без цифр.")
    else:
        pulls = [p for p in github.get("pulls") or [] if isinstance(p, dict)]
        # Count only known main-target PRs; older snapshots without base metadata
        # remain unscoped. Never equate a filtered PR list with all work in main.
        merged = [p for p in pulls
                  if now - 86400 <= (_ts(p.get("merged_at")) or 0) <= now
                  and ((p.get("base") or {}).get("ref") in (None, "", "main"))]
        main_commits = github.get("main_commits")
        complete = github.get("main_commits_complete") is True
        if merged:
            lines.append(f"🔀 За добу влито PR: {len(merged)}.")
            lines += ["  • " + t for t in (_clean_title(p.get("title")) for p in merged[:5]) if t]
        elif complete and isinstance(main_commits, list) and not main_commits:
            lines.append("🔀 За добу комітів у main не було (перевірено через GitHub).")
        else:
            lines.append("🔀 Список PR не підтвердив злиттів у main; це НЕ означає, що змін не було.")
        if isinstance(main_commits, list) and main_commits:
            label = "щонайменше " if not complete else ""
            lines.append(f"🧾 За добу в main: {label}{len(main_commits)} комітів (GitHub).")
        ci = github.get("ci") if isinstance(github.get("ci"), dict) else {}
        open_prs = [p for p in pulls if p.get("state") == "open" and not p.get("draft")]
        red = [p for p in open_prs if (ci.get(str((p.get("head") or {}).get("sha") or "")) or {}).get("state") == "failed"]
        if red:
            lines.append(f"🔴 Червоний CI у відкритих PR: {len(red)}.")
            lines += ["  • " + _clean_title(p.get("title")) for p in red[:3]]
        elif open_prs:
            lines.append(f"🟢 Відкритих PR: {len(open_prs)}, червоного CI немає.")

    if yesterday_plan and yesterday_plan.get("ids"):
        ids = list(yesterday_plan["ids"])
        done = [i for i in ids if (by_id.get(i) or {}).get("status") == "done"]
        rate = round(100 * len(done) / len(ids))
        lines.append(f"🎯 План/факт: у плані було {len(ids)}, виконано {len(done)} — ККД {rate}%.")
        rest = [by_id[i] for i in ids if i in by_id and i not in done][:4]
        lines += ["  ⏳ не встигли: " + _row(t) for t in rest]
    else:
        lines.append("🎯 План/факт з'явиться завтра: сьогодні план записано вперше.")

    today = [by_id[i] for i in plan_ids(tickets)]
    lines.append(f"📋 Сьогодні в плані агентів: {len(today)}.")
    for name, label in AGENTS.items():
        mine = [t for t in today if str((t.get("execution") or {}).get("owner") or "") == name]
        if mine:
            running = sum(1 for t in mine if t.get("status") == "in_progress")
            lines.append(f"  🤖 {label}: у роботі {running}, у черзі {len(mine) - running}")
    lines += ["  ▫️ " + _row(t) for t in today[:5]]

    waiting = [t for t in tickets if t.get("status") == "need_you"]
    if waiting:
        lines.append(f"🙋 Чекають на тебе: {len(waiting)}." + (" Багато старих — варто розібрати або архівувати." if len(waiting) > 10 else ""))
        lines += ["  • " + _row(t) for t in waiting[:4]]
    if questions_open:
        lines.append(f"❓ Відкритих питань до команди: {questions_open}.")
    m = evidence_metrics or {}
    if any(m.get(k) for k in ("verified", "overridden", "rejected", "waiting")):
        lines.append(f"🔎 Докази за тиждень: підтверджено {m.get('verified', 0)}, закрито вручну {m.get('overridden', 0)}, "
                     f"повернуто тобою {m.get('rejected', 0)}; «готово» без доказів: {m.get('waiting', 0)}.")
    lines.append("🗞 Новини світу AI — у випуску MyCast. Гарного дня!")
    return "\n".join(lines)[:3800]


def voice_text(full: str, limit: int = 1400) -> str:
    """The spoken version: headline lines only (details start with two spaces), cut at a line boundary."""
    out, used = [], 0
    for line in full.split("\n"):
        if line.startswith("  "):
            continue
        clean = line.lstrip("☀️📊🔗🔀🧾🔴🟢🎯📋🙋❓🔎🗞 ").strip()
        if used + len(clean) + 1 > limit:
            break
        out.append(clean)
        used += len(clean) + 1
    return "\n".join(out)


class MorningBrief:
    def __init__(self, data_dir: Path, *, deliver: Callable[[str, str], dict], send_text: Callable[[str], object],
                 compose: Callable[..., str], clock: Callable[[], float] = time.time,
                 plan_source: Optional[Callable[[], list]] = None):
        """``plan_source`` (owner 2026-11-11): today's planned ticket ids, stored per date so tomorrow's brief can
        report plan vs fact. When given, ``compose(date, now, yesterday_plan)`` receives the latest earlier plan."""
        self.path = Path(data_dir) / "morning_brief.json"
        self.deliver, self.send_text, self.compose, self.clock = deliver, send_text, compose, clock
        self.plan_source = plan_source
        self._lock = threading.Lock()

    def _compose(self, date: str, now: float, record: bool) -> str:
        if self.plan_source is None:
            return self.compose(date, now)
        with self._lock:
            s = self._load()
            plans = s.get("plans") or {}
            earlier = sorted(d for d in plans if d < date)
            prev = {"date": earlier[-1], "ids": plans[earlier[-1]]} if earlier else None
        text = self.compose(date, now, prev)
        if record:
            try:
                ids = list(self.plan_source())
            except Exception:
                ids = None
            if ids is not None:
                with self._lock:
                    s = self._load()
                    plans = {d: v for d, v in (s.get("plans") or {}).items() if d >= _days_ago(self._local(), 8)}
                    plans.setdefault(date, ids[:200])
                    s["plans"] = plans
                    self._save(s)
        return text

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
            return "Тест (тільки текст, без голосу):\n\n" + self._compose(local.strftime("%Y-%m-%d"), self.clock(), False)
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
        text = self._compose(date, now, True)
        try:
            out = self.deliver(date, voice_text(text))
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
