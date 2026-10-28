"""Durable Relay -> Claude subscription-worker task queue.

All state transitions are persisted to the existing Relay JSON file on the
FactoryOS disk. Tickets are *queued*, not reported as running, until a worker
actually claims them. No API billing, background cloud workers or external
publishing are started here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

ACTIVE_STATES = {"claimed", "running", "checkpoint", "committed", "pushed"}
FINAL_STATES = {"done", "blocked", "failed"}
ALLOWED_EVENTS = ACTIVE_STATES | FINAL_STATES | {"heartbeat"}
WORKER_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def age_seconds(value: str) -> float | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - stamp).total_seconds())
    except (ValueError, AttributeError, TypeError):
        return None


def safe_evidence(source: Any) -> dict:
    """Persist only explicitly allowed factual fields; no raw environment/logs."""
    if not isinstance(source, dict):
        return {}
    result = {}
    sha = str(source.get("commit") or "").strip()
    if SHA_RE.fullmatch(sha):
        result["commit"] = sha.lower()
    branch = str(source.get("branch") or "").strip()
    if re.fullmatch(r"[a-zA-Z0-9_./-]{1,120}", branch):
        result["branch"] = branch
    for key in ("pushed", "ci_passed"):
        if type(source.get(key)) is bool:
            # Worker self-report only; UI must not treat this as GitHub verification.
            result[key + "_reported"] = source[key]
    for key in ("pr_url", "artifact_url"):
        url = str(source.get(key) or "")
        if re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(?:pull|commit|actions/runs)/[A-Za-z0-9]+", url):
            result[key] = url
    return result


class RelayQueue:
    def __init__(self, store, stale_seconds: int = 180):
        self.store = store
        self.stale_seconds = max(60, min(900, int(stale_seconds)))

    def view(self, ticket: dict) -> dict:
        item = dict(ticket)
        execution = dict(item.get("execution") or {})
        if execution.get("state") in ACTIVE_STATES:
            age = age_seconds(execution.get("last_seen_at") or execution.get("claimed_at") or "")
            if age is not None and age > self.stale_seconds:
                execution["state"] = "stale"
                execution["stale_seconds"] = round(age)
        item["execution"] = execution
        return item

    def enqueue(self, ticket_id: str, actor: str = "owner") -> dict:
        tid = str(ticket_id).strip().upper()
        with self.store.lock:
            state = self.store._load_unlocked()
            for item in state["tickets"]:
                if item.get("id") != tid:
                    continue
                execution = item.get("execution") or {}
                if execution.get("state") in {"queued", *ACTIVE_STATES}:
                    view = self.view(dict(item))
                    # Explicit owner Retry may recover a truly stale task. Normal active
                    # work is never requeued merely because the page was refreshed.
                    if view["execution"].get("state") != "stale":
                        return view
                now = utc_now()
                attempts = int(execution.get("attempts") or 0)
                item["execution"] = {
                    "state": "queued", "owner": "claude", "queued_at": now,
                    "attempts": attempts, "last_seen_at": None,
                    "note": "Ожидает работающего Claude worker",
                }
                item["status"] = "inbox"
                item["updated_at"] = now
                item.setdefault("history", []).append({
                    "at": now, "actor": actor[:80], "action": "queued",
                    "note": "Передано в очередь Claude (не запущено)",
                    "from_status": None, "to_status": "inbox",
                })
                self.store._save_unlocked(state)
                return self.view(dict(item))
        raise KeyError(tid)

    def claim(self, worker_id: str) -> dict | None:
        worker_id = str(worker_id or "").strip()
        if not WORKER_ID_RE.fullmatch(worker_id):
            raise ValueError("Invalid worker ID")
        with self.store.lock:
            state = self.store._load_unlocked()
            # Only one active job per worker. Do not reclaim stale work silently.
            for item in state["tickets"]:
                ex = item.get("execution") or {}
                if ex.get("worker_id") == worker_id and ex.get("state") in ACTIVE_STATES:
                    return None
            pending = [item for item in state["tickets"] if item.get("status") == "inbox" and (item.get("execution") or {}).get("state") == "queued"]
            pending.sort(key=lambda item: (item.get("execution") or {}).get("queued_at") or "")
            if not pending:
                return None
            item = pending[0]
            now = utc_now()
            ex = dict(item["execution"])
            ex.update({
                "state": "claimed", "worker_id": worker_id,
                "claimed_at": now, "last_seen_at": now,
                "attempts": int(ex.get("attempts") or 0) + 1,
                "note": "Задание получено исполнителем; запуск Claude ещё проверяется",
            })
            item["execution"] = ex
            item["updated_at"] = now
            item.setdefault("history", []).append({
                "at": now, "actor": worker_id, "action": "claimed",
                "note": "Claude worker забрал задание", "from_status": "inbox", "to_status": "inbox",
            })
            self.store._save_unlocked(state)
            return self.view(dict(item))

    def event(self, ticket_id: str, worker_id: str, stage: str, note: str = "", evidence: dict | None = None) -> dict:
        stage = str(stage or "").strip().lower()
        worker_id = str(worker_id or "").strip()
        if stage not in ALLOWED_EVENTS:
            raise ValueError("Unknown worker stage")
        if not WORKER_ID_RE.fullmatch(worker_id):
            raise ValueError("Invalid worker ID")
        tid = str(ticket_id or "").strip().upper()
        with self.store.lock:
            state = self.store._load_unlocked()
            for item in state["tickets"]:
                if item.get("id") != tid:
                    continue
                ex = dict(item.get("execution") or {})
                if ex.get("worker_id") != worker_id or ex.get("state") not in ACTIVE_STATES:
                    raise ValueError("No active claim for this worker")
                now = utc_now()
                ex["last_seen_at"] = now
                if stage == "heartbeat":
                    item["execution"] = ex
                    self.store._save_unlocked(state)
                    return self.view(dict(item))
                before = ex["state"]
                ex["state"] = stage
                ex["note"] = " ".join(str(note or "").split())[:650]
                evidence_clean = safe_evidence(evidence)
                ex.update(evidence_clean)
                if stage == "running" and not ex.get("started_at"):
                    ex["started_at"] = now
                if stage in FINAL_STATES:
                    ex["finished_at"] = now
                if stage in {"done"}:
                    item["status"] = "done"
                elif stage in {"blocked", "failed"}:
                    item["status"] = "need_you"
                elif stage in {"running", "checkpoint", "committed", "pushed"}:
                    item["status"] = "in_progress"
                item["execution"] = ex
                item["updated_at"] = now
                item.setdefault("history", []).append({
                    "at": now, "actor": worker_id, "action": stage,
                    "note": ex["note"], "evidence": evidence_clean,
                    "from_status": before, "to_status": stage,
                })
                self.store._save_unlocked(state)
                return self.view(dict(item))
        raise KeyError(tid)
