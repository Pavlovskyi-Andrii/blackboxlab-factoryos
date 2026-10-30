"""Durable Relay -> Claude subscription-worker task queue.

All state transitions are persisted to the existing Relay JSON file on the
FactoryOS disk. Tickets are *queued*, not reported as running, until a worker
actually claims them. No API billing, background cloud workers or external
publishing are started here.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
import secrets
from typing import Any

ACTIVE_STATES = {"claimed", "running", "checkpoint", "committed", "pushed"}
FINAL_STATES = {"done", "blocked", "failed"}
ALLOWED_EVENTS = ACTIVE_STATES | FINAL_STATES | {"heartbeat"}
WORKER_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,80}$")
EVENT_ID_RE = re.compile(r"^[a-zA-Z0-9_.:-]{1,120}$")
SHA_RE = re.compile(r"^[0-9a-fA-F]{7,40}$")
GITHUB_REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
SECRET_RE = re.compile(
    r"(?:sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}"
    r"|\b\d{6,12}:[A-Za-z0-9_-]{30,}\b|Bearer\s+[A-Za-z0-9._~+/=-]{12,})"
)
# Ordered owner-facing lifecycle. Backend-recorded worker events are the only
# evidence for the first stages; PR/CI/merge/deploy have no backend verifier
# yet and therefore stay UNVERIFIED unless a GitHub URL is attached.
LIFECYCLE = ("queued", "claimed", "running", "committed", "pushed", "pr", "ci", "merged", "deployed")


def redact(value: Any) -> str:
    return SECRET_RE.sub("[REDACTED]", str(value or ""))


def lifecycle(ticket: dict) -> list[dict]:
    """Per-stage factual trace derived only from durable Relay history."""
    ex = ticket.get("execution") or {}
    history = ticket.get("history") or []
    run_id = str(ex.get("run_id") or "")
    # Only the current run counts; older attempts must not make a stage look reached.
    start = 0
    for index, event in enumerate(history):
        if event.get("action") == "queued":
            start = index
    seen: dict[str, dict] = {}
    for event in history[start:]:
        action = str(event.get("action") or "")
        if action in LIFECYCLE or action in FINAL_STATES:
            seen[action] = event
    rows = []
    for stage in LIFECYCLE:
        event = seen.get(stage)
        row = {"stage": stage, "state": "pending", "source": "", "at": "", "detail": ""}
        if event:
            row.update(state="recorded", at=str(event.get("at") or ""),
                       source="relay" if stage == "queued" else "worker:" + str(event.get("actor") or "?"))
            evidence = event.get("evidence") or {}
            if stage == "claimed":
                row["detail"] = " ".join(x for x in (str(event.get("actor") or ""), str(event.get("run_id") or run_id)) if x)
            elif stage == "committed" and evidence.get("commit"):
                row["detail"] = str(evidence["commit"])[:12]
            elif stage == "pushed":
                row["detail"] = "branch " + str(evidence.get("branch") or ex.get("branch") or "?")
        elif stage == "pr" and ex.get("pr_url"):
            row.update(state="linked", source="worker", detail=str(ex["pr_url"]))
        elif stage in ("pr", "ci", "merged", "deployed"):
            row.update(state="unverified")
        rows.append(row)
    final = next((seen[s] for s in ("done", "blocked", "failed") if s in seen), None)
    if final:
        rows.append({"stage": str(final.get("action")), "state": "recorded", "source": "worker:" + str(final.get("actor") or "?"),
                     "at": str(final.get("at") or ""), "detail": str(final.get("note") or "")[:200]})
    return rows


def lifecycle_text(ticket: dict) -> str:
    icons = {"recorded": "✅", "linked": "🔗", "pending": "⏳", "unverified": "❔"}
    lines = ["Этапы (факт из Relay):"]
    for row in lifecycle(ticket):
        icon = {"blocked": "🙋", "failed": "❌"}.get(row["stage"], icons.get(row["state"], "•"))
        label = row["stage"] + (" — не проверено" if row["state"] == "unverified" else "")
        parts = [icon + " " + label]
        if row["at"]:
            parts.append(row["at"][:19].replace("T", " ") + " UTC")
        if row["detail"]:
            parts.append(row["detail"][:120])
        lines.append(" · ".join(parts))
    ex = ticket.get("execution") or {}
    if ex.get("last_seen_at") and ex.get("state") in ACTIVE_STATES | {"stale"}:
        lines.append("Последняя связь worker: " + str(ex["last_seen_at"])[:19].replace("T", " ") + " UTC")
    return "\n".join(lines)


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
        item["lifecycle"] = lifecycle(item)
        return item

    def intake_github_issue(self, number: int, title: str, url: str = "", repo: str = "",
                            body: str = "", actor: str = "owner") -> tuple[dict, bool]:
        """Owner-authorized, idempotent GitHub Issue -> queued Relay ticket.

        One issue maps to exactly one ticket (source_key); a repeated import
        returns the existing ticket and never re-queues or duplicates work.
        """
        try:
            number = int(number)
        except (TypeError, ValueError):
            raise ValueError("Issue number must be a positive integer")
        if number <= 0:
            raise ValueError("Issue number must be a positive integer")
        repo = str(repo or "").strip()
        if repo and not GITHUB_REPO_RE.fullmatch(repo):
            raise ValueError("Invalid GitHub repository")
        url = str(url or "").strip()
        if url and not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/" + str(number), url):
            raise ValueError("URL must be the GitHub issue URL")
        title = " ".join(redact(title).split())[:160]
        source = {
            "channel": "github",
            "source_key": "github-issue:" + (repo.lower() + "#" if repo else "#") + str(number),
            "issue_number": number,
            "repo": repo,
            "url": url,
        }
        ticket, created = self.store.create(
            "GitHub #" + str(number) + (" · " + title if title else ""),
            body=redact(body)[:20000],
            source=source,
            created_by=str(actor or "owner")[:80],
        )
        return self.view(ticket), created

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
            # A fresh run_id per claim fences late events from an older attempt.
            run_id = "run-" + secrets.token_hex(6)
            for key in ("started_at", "finished_at", "commit", "pushed_reported", "ci_passed_reported", "pr_url", "artifact_url"):
                ex.pop(key, None)
            ex.update({
                "state": "claimed", "worker_id": worker_id, "run_id": run_id,
                "claimed_at": now, "last_seen_at": now,
                "attempts": int(ex.get("attempts") or 0) + 1,
                "note": "Задание получено исполнителем; запуск Claude ещё проверяется",
            })
            item["execution"] = ex
            item["updated_at"] = now
            item.setdefault("history", []).append({
                "at": now, "actor": worker_id, "action": "claimed", "run_id": run_id,
                "note": "Claude worker забрал задание", "from_status": "inbox", "to_status": "inbox",
            })
            self.store._save_unlocked(state)
            return self.view(dict(item))

    def event(self, ticket_id: str, worker_id: str, stage: str, note: str = "", evidence: dict | None = None,
              *, run_id: str = "", event_id: str = "") -> dict:
        stage = str(stage or "").strip().lower()
        worker_id = str(worker_id or "").strip()
        run_id = str(run_id or "").strip()
        event_id = str(event_id or "").strip()
        if stage not in ALLOWED_EVENTS:
            raise ValueError("Unknown worker stage")
        if not WORKER_ID_RE.fullmatch(worker_id):
            raise ValueError("Invalid worker ID")
        if run_id and not EVENT_ID_RE.fullmatch(run_id):
            raise ValueError("Invalid run ID")
        if event_id and not EVENT_ID_RE.fullmatch(event_id):
            raise ValueError("Invalid event ID")
        tid = str(ticket_id or "").strip().upper()
        with self.store.lock:
            state = self.store._load_unlocked()
            for item in state["tickets"]:
                if item.get("id") != tid:
                    continue
                ex = dict(item.get("execution") or {})
                if event_id and any(h.get("event_id") == event_id and h.get("actor") == worker_id
                                    for h in item.get("history") or []):
                    # Network retry of an already-recorded event: no duplicate history.
                    return {**self.view(dict(item)), "replayed": True}
                if ex.get("worker_id") != worker_id or ex.get("state") not in ACTIVE_STATES:
                    raise ValueError("No active claim for this worker")
                if run_id and ex.get("run_id") and run_id != ex["run_id"]:
                    raise ValueError("Event belongs to a superseded run")
                now = utc_now()
                ex["last_seen_at"] = now
                if stage == "heartbeat":
                    item["execution"] = ex
                    self.store._save_unlocked(state)
                    return self.view(dict(item))
                before = ex["state"]
                ex["state"] = stage
                ex["note"] = " ".join(redact(note).split())[:650]
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
                entry = {
                    "at": now, "actor": worker_id, "action": stage,
                    "note": ex["note"], "evidence": evidence_clean,
                    "from_status": before, "to_status": stage,
                }
                if ex.get("run_id"):
                    entry["run_id"] = ex["run_id"]
                if event_id:
                    entry["event_id"] = event_id
                item.setdefault("history", []).append(entry)
                self.store._save_unlocked(state)
                return self.view(dict(item))
        raise KeyError(tid)
