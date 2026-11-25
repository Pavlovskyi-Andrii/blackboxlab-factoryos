"""T-738: tell the owner in Telegram when the Claude worker stops sending heartbeats, and once more when it is back.

The server already records the worker's last heartbeat (``claude_worker_runtime["last_seen"]``, persisted in
``DATA_DIR/claude_worker_heartbeat.json``), but nothing pushed a silence to the owner: on 2026-11-24 the EC2 worker
was silent from 22:05 UTC for about 17 hours and the owner found out because the morning MyCast episode did not
arrive. This module is the policy only (pure, testable); ``app.py`` owns the loop, the Telegram call and the clock.

Rules:
- one alert per silence, after ``FACTORY_WORKER_OFFLINE_ALERT_SECONDS`` (default 15 min) without a heartbeat;
- one "back" message when a heartbeat newer than the silent one arrives;
- nothing for a worker the server has never seen, and nothing during the first two minutes after a server start
  (the restored heartbeat file is old until the worker's next beat reaches the new process);
- the state lives in a small JSON file, so a server restart neither repeats nor loses an alert; a failed send keeps
  the state unchanged and is retried on the next tick;
- 23:00-08:00 Kyiv the message is sent without sound (Telegram ``disable_notification``);
- ``FACTORY_WORKER_OFFLINE_ALERT_ENABLED=0`` turns it off.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Mapping, Optional
from zoneinfo import ZoneInfo

KYIV = ZoneInfo("Europe/Kyiv")
ENABLED_ENV = "FACTORY_WORKER_OFFLINE_ALERT_ENABLED"
AFTER_ENV = "FACTORY_WORKER_OFFLINE_ALERT_SECONDS"
DEFAULT_AFTER_SECONDS = 15 * 60
MIN_AFTER_SECONDS = 5 * 60
MAX_AFTER_SECONDS = 6 * 3600
STARTUP_GRACE_SECONDS = 120  # the worker beats every ~20 s; let it reach a freshly started server first
QUIET_HOURS = (23, 8)  # Kyiv; alerts still go out, only without sound
FIRST_CHECK = "sudo cat /var/lib/factoryos/supervisor-status.json"


def enabled(environ: Mapping[str, str] = os.environ) -> bool:
    return str(environ.get(ENABLED_ENV, "1")).strip().lower() not in ("0", "false", "no", "off")


def offline_after(environ: Mapping[str, str] = os.environ) -> int:
    try:
        value = int(str(environ.get(AFTER_ENV, DEFAULT_AFTER_SECONDS)).strip())
    except (TypeError, ValueError):
        value = DEFAULT_AFTER_SECONDS
    return max(MIN_AFTER_SECONDS, min(value, MAX_AFTER_SECONDS))


@dataclass(frozen=True)
class Decision:
    action: str  # "none" | "offline" | "back"
    state: dict = field(default_factory=dict)
    offline_since: float = 0.0  # last heartbeat before the silence
    silent_for: float = 0.0  # seconds without a heartbeat (so far, or in total for "back")


def decide(last_seen: float, now: float, state: Optional[dict], *, after: int, started_at: float) -> Decision:
    state = dict(state or {})
    try:
        since = float(state.get("offline_since") or 0)
    except (TypeError, ValueError):
        since = 0.0
    if since:
        if last_seen > since:  # a heartbeat arrived after the alerted silence
            return Decision("back", {}, since, max(0.0, last_seen - since))
        return Decision("none", state)  # this silence was already reported
    if last_seen <= 0 or now - started_at < STARTUP_GRACE_SECONDS:
        return Decision("none", state)
    silent = now - last_seen
    if silent >= after:
        return Decision("offline", {"offline_since": last_seen, "alerted_at": now}, last_seen, silent)
    return Decision("none", state)


def quiet(now: float) -> bool:
    hour = datetime.fromtimestamp(now, KYIV).hour
    start, end = QUIET_HOURS
    return hour >= start or hour < end


def kyiv_time(ts: float) -> str:
    return datetime.fromtimestamp(ts, KYIV).strftime("%d.%m %H:%M")


def duration(seconds: float) -> str:
    minutes = max(0, int(seconds // 60))
    hours, minutes = divmod(minutes, 60)
    return f"{hours} ч {minutes} мин" if hours else f"{minutes} мин"


def offline_text(decision: Decision, supervisor: Optional[dict] = None) -> str:
    lines = [f"⚠️ Claude worker молчит {duration(decision.silent_for)}: последний сигнал "
             f"{kyiv_time(decision.offline_since)} по Киеву."]
    report = supervisor if isinstance(supervisor, dict) else {}
    status, reason = str(report.get("status") or ""), str(report.get("reason") or "")
    if status and status != "running":  # only a report that already explains the silence
        lines.append(f"Последний отчёт супервизора: {status}" + (f" ({reason})" if reason else "") + ".")
    lines.append("Пока он молчит, не выходит утренний MyCast и не берутся задачи Relay.")
    lines.append(f"Первая проверка на EC2: {FIRST_CHECK}")
    return "\n".join(lines)


def back_text(decision: Decision) -> str:
    return (f"✅ Claude worker снова на связи. Молчал {duration(decision.silent_for)}, "
            f"с {kyiv_time(decision.offline_since)} по Киеву.")


def load_state(path: Path) -> dict:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def tick(*, last_seen: float, now: float, started_at: float, state_path: Path,
         send: Callable[[str, bool], bool], supervisor: Optional[dict] = None,
         environ: Mapping[str, str] = os.environ) -> str:
    """One check. ``send(text, silent)`` returns True only when Telegram accepted the message."""
    if not enabled(environ):
        return "disabled"
    decision = decide(float(last_seen or 0), now, load_state(state_path), after=offline_after(environ),
                      started_at=started_at)
    if decision.action == "none":
        return "none"
    text = offline_text(decision, supervisor) if decision.action == "offline" else back_text(decision)
    try:
        sent = bool(send(text, quiet(now)))
    except Exception:  # Telegram down or not paired: keep the state, retry on the next tick
        sent = False
    if not sent:
        return "send_failed"
    save_state(state_path, decision.state)
    return decision.action
