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
TASK_ID_RE = re.compile(r"^T-[A-Za-z0-9-]{1,40}$")
LANE_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
SHARED_LANES = {"", "any", "auto"}
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
            elif stage in ("ci", "merged"):
                row["source"] = "github"
                row["detail"] = str(event.get("note") or "")[:120]
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
        if row["stage"] == "ci" and row["detail"].startswith("CI failed"):
            icon = "❌"
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


def _is_roadmap(ticket: dict) -> bool:
    return (ticket.get("source") or {}).get("channel") == "roadmap"


def _claude_claimable(ticket: dict) -> bool:
    """Only Claude-owned generic tickets may be claimed by the Claude worker.

    Telegram assignment lives in execution.owner, while imported GitHub Issues
    declare source.owner. An explicit execution lane (including unassigned)
    must take precedence; legacy tickets without either field remain claimable.
    """
    if _is_roadmap(ticket):
        return False
    execution_owner = str((ticket.get("execution") or {}).get("owner") or "").strip().lower()
    source_owner = str((ticket.get("source") or {}).get("owner") or "").strip().lower()
    owner = execution_owner or source_owner
    if source_owner not in SHARED_LANES and source_owner != "claude":
        return False
    return owner in SHARED_LANES or owner == "claude"


# T-599-E: an owner Issue is imported only when its first non-blank body line names a lane.
ISSUE_OWNER_LINE_RE = re.compile(r"^\s*Owner:\s*(Claude|ChatGPT|Gemini)\s*$", re.IGNORECASE)
ISSUE_TASK_ID_RE = re.compile(r"\bT-\d{3,4}(?:-[A-Z])?\b")


def issue_owner_lane(body: str) -> str:
    for line in str(body or "").splitlines():
        if line.strip():
            match = ISSUE_OWNER_LINE_RE.fullmatch(line.strip())
            return match.group(1).lower() if match else ""
    return ""


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

    def auto_intake_owner_issues(self, issues: list, repo: str, owner_login: str) -> dict:
        """T-599-E: import open owner Issues carrying an ``Owner:`` first line.

        Only Issues authored by ``owner_login`` are considered (foreign task
        injection is ignored). An Issue that names a T-ID with an existing
        ``roadmap:T-xxx`` ticket is linked to it instead of creating a duplicate;
        everything else goes through the idempotent ``intake_github_issue``.
        """
        owner_login = str(owner_login or "").strip().lower()
        summary = {"imported": [], "existing": [], "linked": [], "ignored": 0}
        if not owner_login or not GITHUB_REPO_RE.fullmatch(str(repo or "")):
            raise ValueError("Repository owner is required")
        for issue in issues or []:
            if not isinstance(issue, dict) or issue.get("pull_request") or str(issue.get("state") or "open") != "open":
                summary["ignored"] += 1
                continue
            author = str(issue.get("author") or "").strip().lower()
            lane = issue_owner_lane(str(issue.get("body") or ""))
            try:
                number = int(issue.get("number"))
            except (TypeError, ValueError):
                number = 0
            if author != owner_login or not lane or number <= 0:
                summary["ignored"] += 1
                continue
            title, body, url = str(issue.get("title") or ""), str(issue.get("body") or ""), str(issue.get("url") or "")
            task_ids = sorted(set(ISSUE_TASK_ID_RE.findall(title + "\n" + body)))
            linked = self._link_issue_to_roadmap(task_ids, number, url, repo)
            if linked:
                summary["linked"].append({"issue": number, "tickets": linked})
                continue
            ticket, created = self.intake_github_issue(number, title, url=url, repo=repo, body=body,
                                                       actor="github-auto-intake")
            if created:
                ticket = self._set_issue_lane(ticket["id"], lane)
            summary["imported" if created else "existing"].append({"issue": number, "ticket": ticket["id"], "lane": lane})
        return summary

    def _set_issue_lane(self, ticket_id: str, lane: str) -> dict:
        with self.store.lock:
            state = self.store._load_unlocked()
            item = next(x for x in state["tickets"] if x.get("id") == ticket_id)
            item.setdefault("source", {})["owner"] = lane
            item.setdefault("execution", {})["owner"] = lane
            self.store._save_unlocked(state)
            return self.view(dict(item))

    def _link_issue_to_roadmap(self, task_ids: list, number: int, url: str, repo: str) -> list:
        """Attach an Issue reference to existing ROADMAP tickets; repeat calls change nothing."""
        if not task_ids:
            return []
        keys = {"roadmap:" + tid for tid in task_ids}
        ref = {"number": number, "repo": repo, "url": url}
        linked = []
        with self.store.lock:
            state = self.store._load_unlocked()
            changed = False
            for item in state["tickets"]:
                source = item.get("source") or {}
                if source.get("source_key") not in keys:
                    continue
                linked.append(str(item.get("id") or ""))
                refs = source.setdefault("linked_issues", [])
                if any(int(r.get("number") or 0) == number for r in refs):
                    continue
                refs.append(ref)
                item["source"] = source
                now = utc_now()
                item.setdefault("history", []).append({
                    "at": now, "actor": "github-auto-intake", "action": "linked",
                    "note": "GitHub #" + str(number) + " привязан к " + str(source.get("task_id") or ""),
                    "from_status": item.get("status"), "to_status": item.get("status"),
                })
                changed = True
            if changed:
                self.store._save_unlocked(state)
        return sorted(linked)

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
                        if execution.get("state") == "queued" and item.get("status") != "inbox":
                            # Legacy status actions can leave an unclaimable queued item.
                            # Reconcile the existing ticket; never create a second ticket/run.
                            now = utc_now()
                            previous = item.get("status")
                            item["status"] = "inbox"
                            item["updated_at"] = now
                            item.setdefault("history", []).append({
                                "at": now, "actor": actor[:80],
                                "action": "queued", "from_status": previous,
                                "to_status": "inbox",
                                "note": "Повторный запуск существующего тикета; без дублирования",
                            })
                            self.store._save_unlocked(state)
                            return self.view(dict(item))
                        return view
                now = utc_now()
                attempts = int(execution.get("attempts") or 0)
                item["execution"] = {
                    "state": "queued", "owner": execution.get("owner") or "claude", "queued_at": now,
                    "attempts": attempts, "last_seen_at": None,
                    "note": "Ожидает исполнителя " + str(execution.get("owner") or "claude") + " (повторная очередь)",
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
            # The *same worker*, polling after a crash/restart, can explicitly
            # release its stale claim, but never silently rerun that ticket.
            released = False
            for item in state["tickets"]:
                ex = item.get("execution") or {}
                if ex.get("worker_id") == worker_id and ex.get("state") in ACTIVE_STATES:
                    if self.view(dict(item))["execution"].get("state") != "stale":
                        return None
                    self._release_stale_unlocked(item, worker_id)
                    released = True
            if released:
                self.store._save_unlocked(state)
            pending = [item for item in state["tickets"] if item.get("status") == "inbox"
                       and (item.get("execution") or {}).get("state") == "queued" and _claude_claimable(item)]
            pending.sort(key=lambda item: (item.get("execution") or {}).get("queued_at") or "")
            if not pending:
                return None
            item = pending[0]
            self._claim_unlocked(item, worker_id, "Claude worker забрал задание")
            self.store._save_unlocked(state)
            return self.view(dict(item))

    def _claim_unlocked(self, item: dict, worker_id: str, history_note: str, lane: str = "") -> None:
        now = utc_now()
        ex = dict(item.get("execution") or {})
        before = str(item.get("status") or "inbox")
        # A fresh run_id per claim fences late events from an older attempt.
        run_id = "run-" + secrets.token_hex(6)
        for key in ("started_at", "finished_at", "commit", "pushed_reported", "ci_passed_reported", "pr_url", "artifact_url",
                    "stale_seconds"):
            ex.pop(key, None)
        ex.update({
            "state": "claimed", "worker_id": worker_id, "run_id": run_id,
            "claimed_at": now, "last_seen_at": now,
            "attempts": int(ex.get("attempts") or 0) + 1,
            "note": "Задание получено исполнителем; запуск Claude ещё проверяется",
        })
        if lane:
            ex["owner"] = lane
        item["execution"] = ex
        item["status"] = "inbox"
        item["updated_at"] = now
        item.setdefault("history", []).append({
            "at": now, "actor": worker_id, "action": "claimed", "run_id": run_id,
            "note": history_note, "from_status": before, "to_status": "inbox",
        })

    def claim_roadmap(self, worker_id: str, lane: str, task_id: str, title: str = "",
                      owner: str = "") -> tuple[dict | None, str]:
        """T-599-C: atomic server-side claim of one ROADMAP task by one runner lane.

        One ticket per task (source_key ``roadmap:T-xxx``). Returns ``(ticket, "")`` with a
        fresh run_id, or ``(None, reason)`` when another lane owns the task, a run is still
        active, or a stale run awaits an owner Retry. Never re-runs active work.
        """
        worker_id = str(worker_id or "").strip()
        lane = str(lane or "").strip().lower()
        task_id = str(task_id or "").strip()
        owner = str(owner or "").strip().lower()
        if not WORKER_ID_RE.fullmatch(worker_id):
            raise ValueError("Invalid worker ID")
        if not LANE_RE.fullmatch(lane) or (owner and not LANE_RE.fullmatch(owner)):
            raise ValueError("Invalid lane")
        if not TASK_ID_RE.fullmatch(task_id):
            raise ValueError("Invalid ROADMAP task ID")
        if owner not in SHARED_LANES and owner != lane:
            return None, f"{task_id} belongs to lane {owner}"
        source = {"channel": "roadmap", "source_key": "roadmap:" + task_id, "task_id": task_id, "owner": owner or "any"}
        clean_title = " ".join(redact(title).split())[:150]
        with self.store.lock:
            ticket, _created = self.store.create(task_id + (" · " + clean_title if clean_title else ""),
                                                 source=source, created_by=worker_id)
            state = self.store._load_unlocked()
            item = next(x for x in state["tickets"] if x.get("id") == ticket["id"])
            current = self.view(dict(item))["execution"]
            stage = str(current.get("state") or "")
            reason = ""
            if stage == "stale":
                reason = f"{task_id}: previous run lost contact; owner Retry required"
            elif stage in ACTIVE_STATES:
                reason = f"{task_id} is already {stage} by {current.get('worker_id') or '?'}"
            if reason:
                self._claim_rejected_unlocked(item, worker_id, lane, current, reason)
                self.store._save_unlocked(state)
                return None, reason
            item.setdefault("source", {}).update({"owner": owner or "any"})
            self._claim_unlocked(item, worker_id, f"ROADMAP {task_id} взята исполнителем {worker_id} (lane {lane})", lane)
            self.store._save_unlocked(state)
            return self.view(dict(item)), ""

    def _claim_rejected_unlocked(self, item: dict, worker_id: str, lane: str, current: dict, reason: str) -> None:
        """Journal a refused claim once per (run, worker), so periodic retries don't flood history."""
        run_id = str(current.get("run_id") or "")
        if any(h.get("action") == "claim_rejected" and h.get("actor") == worker_id and h.get("run_id") == run_id
               for h in item.get("history") or []):
            return
        item.setdefault("history", []).append({
            "at": utc_now(), "actor": worker_id, "action": "claim_rejected", "run_id": run_id,
            "note": f"{reason} (lane {lane})"[:300],
        })

    def _release_stale_unlocked(self, item: dict, worker_id: str) -> None:
        now = utc_now()
        execution = dict(item.get("execution") or {})
        before = execution.get("state") or ""
        note = "Исполнитель потерял связь; ручной повтор: /work " + str(item.get("id") or "")
        execution.update({"state": "blocked", "note": note, "finished_at": now})
        item["execution"] = execution
        item["status"] = "need_you"
        item["updated_at"] = now
        item.setdefault("history", []).append({
            "at": now, "actor": worker_id, "action": "stale_released",
            "note": note, "from_status": before, "to_status": "blocked"
        })

    def reconcile_pull_requests(self, pulls: list, ci: dict) -> list[dict]:
        """#289 round trip, server side: follow each ticket's PR (the worker's pr_url evidence) on GitHub.

        Facts come only from the GitHub read passed in (the EC2 snapshot); a PR that is not in it stays unknown.
        Each transition is recorded once in the ticket history (actor "github") and returned as an owner notice:
        CI passed / CI failed / merged / closed without merge. Nothing is merged or retried here.
        """
        by_url = {str(p.get("html_url") or ""): p for p in pulls or [] if isinstance(p, dict) and p.get("html_url")}
        notices = []
        with self.store.lock:
            state = self.store._load_unlocked()
            changed = False
            for item in state["tickets"]:
                ex = item.get("execution") or {}
                url = str(ex.get("pr_url") or "")
                if not url or ex.get("pr_final"):
                    continue
                pr = by_url.get(url)
                if pr is None:
                    continue
                now = utc_now()

                def record(action, note, text):
                    item.setdefault("history", []).append({"at": now, "actor": "github", "action": action, "note": note,
                                                           "evidence": {"pr_url": url}})
                    notices.append({"ticket": item["id"], "action": action, "text": text})

                if pr.get("merged_at"):
                    ex.update(pr_final="merged", merged_at=str(pr.get("merged_at"))[:40])
                    record("merged", "PR merged into main (GitHub)", f"🔀 Relay {item['id']}: PR смержен в main\n{url}\n"
                           "Деплой на Render — после зелёных проверок main.")
                elif str(pr.get("state") or "") == "closed":
                    ex.update(pr_final="closed")
                    record("pr_closed", "PR closed without merge (GitHub)", f"🚫 Relay {item['id']}: PR закрыт без мержа\n{url}")
                else:
                    summary = (ci or {}).get(str((pr.get("head") or {}).get("sha") or "")) or {}
                    ci_state = summary.get("state") if isinstance(summary, dict) else None
                    if ci_state in ("passed", "failed") and ci_state != ex.get("ci_state"):
                        ex["ci_state"] = ci_state
                        if ci_state == "passed":
                            record("ci", "CI passed (GitHub)", f"✅ Relay {item['id']}: CI зелёный — PR готов к ревью и мержу\n{url}")
                        else:
                            failed = str(summary.get("failed") or "")[:80]
                            record("ci", "CI failed: " + failed, f"❌ Relay {item['id']}: CI упал ({failed or 'check'})\n{url}")
                    else:
                        continue
                item["execution"] = ex
                item["updated_at"] = now
                changed = True
            if changed:
                self.store._save_unlocked(state)
        return notices

    def counts(self, tickets: list[dict]) -> dict:
        """Effective queue depth must reflect the same predicates as claim()."""
        counts = {"claimable": 0, "other_lane": 0, "running": 0, "stale": 0, "need_you": 0, "not_queued": []}
        for ticket in tickets:
            status = str(ticket.get("status") or "")
            if status not in ("inbox", "in_progress", "need_you"):
                continue
            stage = str(self.view(ticket)["execution"].get("state") or "")
            if status == "inbox" and stage == "queued" and _claude_claimable(ticket):
                counts["claimable"] += 1
            elif status == "inbox" and stage == "queued" and not _is_roadmap(ticket):
                counts["other_lane"] += 1
            elif stage == "stale":
                counts["stale"] += 1
            elif stage in ACTIVE_STATES:
                counts["running"] += 1
            elif status == "need_you":
                counts["need_you"] += 1
            else:
                counts["not_queued"].append(str(ticket.get("id") or ""))
        return counts

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
