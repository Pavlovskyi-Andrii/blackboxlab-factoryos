"""MVP Builder M1D (#275): truthful, read-only status projection of Builder events for Agent Office cards.

Pure and offline: it folds a list of already-fetched Builder events into compact card data. It never fetches,
never writes, never reads the clock (``now`` is a parameter) and never invents activity. Same input -> same card.

Example::

    from mvp_builder_projection import project
    out = project(events, now="2026-11-08T10:00:00Z", snapshot_status="ok")
    out["real"]["stage"]          # e.g. "pr_open", "stale", "unknown"
    out["demo"]                   # None, or a separate card flagged demo=True

Event shape: ``{at: "YYYY-MM-DDTHH:MM:SS[.fff]Z", stage, actor, run_id, source: "real"|"demo",
verified: bool, evidence: str|None, detail?: dict, project?: str, version?: str}``. Extra keys are ignored.

Rules (state machine from #186):
- Events are sorted by ``at`` (ties keep input order), so out-of-order input yields the same card.
- Malformed events (bad timestamp, unknown stage, bad source/actor/run_id/verified/evidence/detail) and events
  dated after ``now`` are ignored and counted in ``ignored`` / ``ignored_reasons``.
- The active run is the run_id of the latest ``claimed`` event; events of any other run are ignored as
  ``stale_run``. Only ``spec_pending``/``ready`` may carry ``run_id: None`` (an unclaimed request).
- Demo events never mix into the real card: ``{"real": card, "demo": card | None}``; a demo card has demo=True.
- An event counts only when ``verified`` is true AND it carries non-empty evidence. The stage shown is the last
  verified stage; later unverified events are listed only in ``pending_unverified``.
- ``claimed``/``running``/``committed``/``pushed`` need a verified ``heartbeat`` within ``heartbeat_ttl``
  seconds; otherwise the card shows ``stale`` (never RUNNING).
- Snapshot ``offline``/``forbidden`` (403)/``missing`` (or events=None) -> stage ``unknown`` with a reason, never
  READY/RUNNING. ``partial`` keeps the projection but marks ``complete: False``.
- ``merge_state``/``deploy_state`` stay ``UNKNOWN`` unless an explicit verified ``merged``/``deployed`` event
  exists; ``pr_open``/``ci_passed`` never imply them.
- There is no percent-complete field. ``cost`` is ``{"known": False}`` unless a verified ``cost`` event has a
  numeric ``detail.usd``.
- ``qa_result`` is pending|passed|rejected|unknown; rejected QA sets a blocker. A verified ``owner_review``
  with no later decision sets ``needs_owner: True``.
- ``labels`` holds uk/ru/en text for the displayed stage and blocker; ``LABELS`` covers every key used.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

LIFECYCLE = ("spec_pending", "ready", "claimed", "running", "committed", "pushed", "pr_open", "ci_running",
             "ci_passed", "qa_review", "preview_ready", "owner_review", "approved", "rejected")
ORTHOGONAL = ("blocked", "failed", "stale", "cancelled")
SIGNALS = ("heartbeat", "qa_passed", "qa_rejected", "cost", "merged", "deployed")
STAGES = LIFECYCLE + ORTHOGONAL
EVENT_KINDS = STAGES + SIGNALS
DISPLAY_ONLY = ("unknown", "demo")
HEARTBEAT_STAGES = ("claimed", "running", "committed", "pushed")
UNCLAIMED_STAGES = ("spec_pending", "ready")
SNAPSHOT_STATUSES = ("ok", "partial", "offline", "forbidden", "missing")
SOURCES = ("real", "demo")

_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,6})?Z$")
_MAX_TEXT = 300

LABELS = {
    "spec_pending": {"uk": "Чекає на специфікацію", "ru": "Ожидает спецификацию", "en": "Spec pending"},
    "ready": {"uk": "Готово до старту", "ru": "Готово к старту", "en": "Ready"},
    "claimed": {"uk": "Взято в роботу", "ru": "Взято в работу", "en": "Claimed"},
    "running": {"uk": "Виконується", "ru": "Выполняется", "en": "Running"},
    "committed": {"uk": "Закомічено", "ru": "Закоммичено", "en": "Committed"},
    "pushed": {"uk": "Відправлено в гілку", "ru": "Отправлено в ветку", "en": "Pushed"},
    "pr_open": {"uk": "PR відкрито", "ru": "PR открыт", "en": "PR open"},
    "ci_running": {"uk": "CI виконується", "ru": "CI выполняется", "en": "CI running"},
    "ci_passed": {"uk": "CI пройдено", "ru": "CI пройден", "en": "CI passed"},
    "qa_review": {"uk": "Перевірка QA", "ru": "Проверка QA", "en": "QA review"},
    "preview_ready": {"uk": "Прев'ю готове", "ru": "Превью готово", "en": "Preview ready"},
    "owner_review": {"uk": "Чекає рішення власника", "ru": "Ожидает решения владельца",
                     "en": "Awaiting owner review"},
    "approved": {"uk": "Схвалено власником", "ru": "Одобрено владельцем", "en": "Approved by owner"},
    "rejected": {"uk": "Відхилено власником", "ru": "Отклонено владельцем", "en": "Rejected by owner"},
    "blocked": {"uk": "Заблоковано", "ru": "Заблокировано", "en": "Blocked"},
    "failed": {"uk": "Помилка", "ru": "Ошибка", "en": "Failed"},
    "stale": {"uk": "Немає сигналу (застаріло)", "ru": "Нет сигнала (устарело)", "en": "Stale (no heartbeat)"},
    "cancelled": {"uk": "Скасовано", "ru": "Отменено", "en": "Cancelled"},
    "unknown": {"uk": "Стан невідомий", "ru": "Состояние неизвестно", "en": "Status unknown"},
    "demo": {"uk": "Демо-дані", "ru": "Демо-данные", "en": "Demo data"},
    # blocker / reason codes
    "qa_rejected": {"uk": "QA відхилив результат", "ru": "QA отклонил результат", "en": "QA rejected"},
    "owner_rejected": {"uk": "Власник відхилив", "ru": "Владелец отклонил", "en": "Owner rejected"},
    "heartbeat_stale": {"uk": "Сигнал застарів", "ru": "Сигнал устарел", "en": "Heartbeat stale"},
    "heartbeat_absent": {"uk": "Сигналу немає", "ru": "Сигнала нет", "en": "No heartbeat"},
    "snapshot_offline": {"uk": "Джерело недоступне", "ru": "Источник недоступен", "en": "Source offline"},
    "snapshot_forbidden": {"uk": "Доступ заборонено (403)", "ru": "Доступ запрещён (403)",
                           "en": "Access forbidden (403)"},
    "snapshot_missing": {"uk": "Даних немає", "ru": "Данных нет", "en": "No snapshot"},
    "snapshot_partial": {"uk": "Дані неповні", "ru": "Данные неполные", "en": "Partial snapshot"},
    "no_verified_events": {"uk": "Немає підтверджених подій", "ru": "Нет подтверждённых событий",
                           "en": "No verified events"},
}


def _parse_at(value: Any) -> Optional[datetime]:
    if not isinstance(value, str) or not _STAMP.match(value):
        return None
    fmt = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in value else "%Y-%m-%dT%H:%M:%SZ"
    try:
        return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _now(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return value.astimezone(timezone.utc)
    parsed = _parse_at(value)
    if parsed is None:
        raise ValueError("now must be an aware datetime or an ISO-8601 UTC 'Z' string")
    return parsed


def _short(value: Any) -> Optional[str]:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:_MAX_TEXT]


def _normalise(raw: Any, index: int) -> Optional[dict]:
    """A validated, copied event or None when malformed."""
    if not isinstance(raw, dict):
        return None
    at = _parse_at(raw.get("at"))
    stage = raw.get("stage")
    actor = _short(raw.get("actor"))
    run_id = raw.get("run_id")
    source = raw.get("source")
    verified = raw.get("verified")
    evidence = raw.get("evidence")
    detail = raw.get("detail")
    if at is None or stage not in EVENT_KINDS or actor is None or source not in SOURCES:
        return None
    if not isinstance(verified, bool) or not (evidence is None or isinstance(evidence, str)):
        return None
    if detail is not None and not isinstance(detail, dict):
        return None
    if run_id is None:
        if stage not in UNCLAIMED_STAGES:
            return None
    elif _short(run_id) is None:
        return None
    evidence = _short(evidence)
    return {"at": at, "at_text": raw["at"], "index": index, "stage": stage, "actor": actor,
            "run_id": run_id.strip() if isinstance(run_id, str) else None, "source": source,
            "verified": verified and evidence is not None, "evidence": evidence,
            "detail": dict(detail) if detail else {},
            "project": _short(raw.get("project")), "version": _short(raw.get("version"))}


def _labels(stage: str, blocker: Optional[dict], demo: bool) -> dict:
    out = {}
    for lang in ("uk", "ru", "en"):
        out[lang] = {"stage": LABELS[stage][lang],
                     "blocker": LABELS[blocker["code"]][lang] if blocker else None,
                     "demo": LABELS["demo"][lang] if demo else None}
    return out


def _evidence_ref(ev: Optional[dict]) -> Optional[dict]:
    if ev is None:
        return None
    return {"stage": ev["stage"], "at": ev["at_text"], "actor": ev["actor"], "evidence": ev["evidence"],
            "source": ev["source"]}


def _card(events: list, *, now: datetime, snapshot: str, ttl: int, demo: bool, ignored: dict) -> dict:
    ignored = dict(ignored)
    claims = [e for e in events if e["stage"] == "claimed"]
    active_run = claims[-1]["run_id"] if claims else None
    kept = []
    for e in events:
        if active_run is not None and e["run_id"] not in (active_run, None):
            ignored["stale_run"] = ignored.get("stale_run", 0) + 1
        else:
            kept.append(e)
    verified = [e for e in kept if e["verified"]]
    stage_events = [e for e in verified if e["stage"] in STAGES]
    last_stage = stage_events[-1] if stage_events else None

    def last_of(*kinds):
        hits = [e for e in verified if e["stage"] in kinds]
        return hits[-1] if hits else None

    heartbeat = last_of("heartbeat")
    hb_age = int((now - heartbeat["at"]).total_seconds()) if heartbeat else None
    hb_fresh = hb_age is not None and hb_age <= ttl

    after = last_stage["at"] if last_stage else None
    pending = [{"stage": e["stage"], "at": e["at_text"], "actor": e["actor"]} for e in kept
               if not e["verified"] and (after is None or (e["at"], e["index"]) > (after, last_stage["index"]))]

    blocker = None
    reason = None
    stage = last_stage["stage"] if last_stage else "unknown"
    if snapshot in ("offline", "forbidden", "missing"):
        stage, reason = "unknown", "snapshot_" + snapshot
    elif last_stage is None:
        reason = "no_verified_events"
    elif stage in HEARTBEAT_STAGES and not hb_fresh:
        reason = "heartbeat_absent" if heartbeat is None else "heartbeat_stale"
        stage = "stale"
    elif snapshot == "partial":
        reason = "snapshot_partial"

    qa_verdict = last_of("qa_passed", "qa_rejected")
    if qa_verdict is not None:
        qa_result = "passed" if qa_verdict["stage"] == "qa_passed" else "rejected"
    elif last_of("qa_review") is not None:
        qa_result = "pending"
    else:
        qa_result = "unknown"

    if stage == "unknown" and reason and reason.startswith("snapshot_"):
        blocker = {"code": reason, "detail": None}
    elif stage == "stale":
        blocker = {"code": reason, "detail": None}
    elif last_stage is not None and last_stage["stage"] in ("blocked", "failed", "cancelled"):
        blocker = {"code": last_stage["stage"], "detail": _short(last_stage["detail"].get("reason"))}
    elif last_stage is not None and last_stage["stage"] == "rejected":
        blocker = {"code": "owner_rejected", "detail": _short(last_stage["detail"].get("reason"))}
    elif qa_result == "rejected":
        blocker = {"code": "qa_rejected", "detail": _short(qa_verdict["detail"].get("reason"))}

    cost_ev = None
    for e in verified:
        usd = e["detail"].get("usd")
        if e["stage"] == "cost" and isinstance(usd, (int, float)) and not isinstance(usd, bool) and usd >= 0:
            cost_ev = e
    cost = ({"known": True, "usd": cost_ev["detail"]["usd"], "evidence": cost_ev["evidence"]}
            if cost_ev else {"known": False})

    preview = last_of("preview_ready")
    merged, deployed = last_of("merged"), last_of("deployed")
    claim = [e for e in verified if e["stage"] == "claimed"]
    meta = [e for e in verified if e["project"] or e["version"]]
    project = next((e["project"] for e in reversed(meta) if e["project"]), None)
    version = next((e["version"] for e in reversed(meta) if e["version"]), None)
    known_snapshot = snapshot not in ("offline", "forbidden", "missing")
    last_ev = [e for e in verified if e["stage"] != "heartbeat"]

    return {
        "demo": demo,
        "project": project,
        "version": version,
        "owner": claim[-1]["actor"] if claim else None,
        "run_id": active_run,
        "stage": stage,
        "stage_reason": reason,
        "verified_stage": last_stage["stage"] if last_stage else None,
        "verified": known_snapshot and last_stage is not None and stage == last_stage["stage"],
        "last_evidence": _evidence_ref(last_ev[-1] if last_ev else None),
        "heartbeat_age_s": hb_age,
        "heartbeat_fresh": hb_fresh,
        "blocker": blocker,
        "qa_result": qa_result if known_snapshot else "unknown",
        "cost": cost,
        "preview_status": ("ready" if preview else "none") if known_snapshot else "unknown",
        "preview_evidence": preview["evidence"] if preview and known_snapshot else None,
        "merge_state": "MERGED" if merged and known_snapshot else "UNKNOWN",
        "deploy_state": "DEPLOYED" if deployed and known_snapshot else "UNKNOWN",
        "needs_owner": known_snapshot and stage == "owner_review",
        "pending_unverified": pending,
        "snapshot": snapshot,
        "complete": snapshot == "ok",
        "ignored": sum(ignored.values()),
        "ignored_reasons": dict(sorted(ignored.items())),
        "labels": _labels(stage, blocker, demo),
    }


def project(events: Any, *, now: Any, snapshot_status: str = "ok", heartbeat_ttl: int = 300) -> dict:
    """Project Builder events into ``{"real": card, "demo": card | None}``. Never mutates ``events``."""
    clock = _now(now)
    if not isinstance(heartbeat_ttl, int) or isinstance(heartbeat_ttl, bool) or heartbeat_ttl < 0:
        raise ValueError("heartbeat_ttl must be a non-negative int")
    snapshot = snapshot_status if snapshot_status in SNAPSHOT_STATUSES else "missing"
    if events is None:
        snapshot, events = "missing", []
    elif not isinstance(events, (list, tuple)):
        snapshot, events = "missing", []

    parts = {"real": [], "demo": []}
    ignored = {"real": {}, "demo": {}}
    for i, raw in enumerate(events):
        ev = _normalise(raw, i)
        if ev is None:
            ignored["real"]["malformed"] = ignored["real"].get("malformed", 0) + 1
        elif ev["at"] > clock:
            ignored[ev["source"]]["future"] = ignored[ev["source"]].get("future", 0) + 1
        else:
            parts[ev["source"]].append(ev)
    for key in parts:
        parts[key].sort(key=lambda e: (e["at"], e["index"]))

    real = _card(parts["real"], now=clock, snapshot=snapshot, ttl=heartbeat_ttl, demo=False,
                 ignored=ignored["real"])
    demo = None
    if parts["demo"] or ignored["demo"]:
        demo = _card(parts["demo"], now=clock, snapshot=snapshot, ttl=heartbeat_ttl, demo=True,
                     ignored=ignored["demo"])
    return {"real": real, "demo": demo}
