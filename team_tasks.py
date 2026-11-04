"""Team tasks page (owner 2026-11-04): every task of Claude, ChatGPT, Gemini and the owner in one read model.

Sources, all read-only: GitHub Issues (executor = first line ``Owner: X``), pull requests (executor = branch
prefix ``claude/`` ``chatgpt/`` ``gemini/``), check runs of open PR heads (CI), ROADMAP ``[HUMAN]`` tasks
(waiting for the owner) and the existing lane facts (heartbeat). Nothing is inferred as "working" without a PR
or a heartbeat; a failed GitHub read is reported as unavailable, never as an empty success.
"""
from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Optional

AGENTS = ("claude", "chatgpt", "gemini")
LABELS = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini", "owner": "Owner"}
STATUSES = ("in_progress", "review", "ci_failed", "queued", "blocked", "waiting_owner", "done")
PROGRESS = {"queued": 0, "blocked": 0, "waiting_owner": 0, "in_progress": 40, "ci_failed": 60, "review": 85, "done": 100}
_OWNER_LINE = re.compile(r"^\s*Owner:\s*(Claude|ChatGPT|Gemini)\b", re.I)
_ISSUE_REF = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?|refs?)\s+#(\d+)", re.I)
_BRANCH_ISSUE = re.compile(r"issue-(\d+)")


def _ts(value) -> float:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _agent_of_issue(body) -> str:
    m = _OWNER_LINE.match(str(body or "").split("\n", 1)[0])
    return m.group(1).lower() if m else ""


def _agent_of_pr(pr: dict) -> str:
    head = str(((pr.get("head") or {}).get("ref")) or "")
    for agent in AGENTS:
        if head.startswith(agent + "/"):
            return agent
    return ""


def _ci_summary(runs: list) -> dict:
    """passed | failed | running | none, plus the first failing check name."""
    runs = [r for r in runs or [] if isinstance(r, dict)]
    if not runs:
        return {"state": "none", "failed": ""}
    failed = [r for r in runs if r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required")]
    if failed:
        return {"state": "failed", "failed": str(failed[0].get("name") or "")[:80]}
    if any(r.get("status") != "completed" for r in runs):
        return {"state": "running", "failed": ""}
    return {"state": "passed", "failed": ""}


def github_fetcher(repo: str, token: str) -> Callable[[str], object]:
    import urllib.request

    def fetch(path: str):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "FactoryOS-TeamTasks/1.0",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request("https://api.github.com/repos/" + repo + path, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            return json.load(response)
    return fetch


def read_github(fetch: Callable[[str], object], max_ci: int = 20) -> dict:
    try:
        issues = fetch("/issues?state=all&per_page=100&sort=updated&direction=desc")
        pulls = fetch("/pulls?state=all&per_page=60&sort=updated&direction=desc")
        if not isinstance(issues, list) or not isinstance(pulls, list):
            raise ValueError("unexpected GitHub response")
        ci = {}
        for pr in [p for p in pulls if isinstance(p, dict) and p.get("state") == "open"][:max_ci]:
            sha = str((pr.get("head") or {}).get("sha") or "")
            if sha:
                try:
                    data = fetch("/commits/" + sha + "/check-runs?per_page=50")
                    ci[sha] = _ci_summary((data or {}).get("check_runs") if isinstance(data, dict) else [])
                except Exception:
                    ci[sha] = {"state": "unknown", "failed": ""}
        return {"available": True, "issues": issues, "pulls": pulls, "ci": ci}
    except Exception as exc:
        code = getattr(exc, "code", None)
        return {"available": False, "error": ("HTTP " + str(code)) if code else "GitHub unavailable",
                "issues": [], "pulls": [], "ci": {}}


def _pr_view(pr: dict, ci: dict) -> dict:
    sha = str((pr.get("head") or {}).get("sha") or "")
    merged = bool(pr.get("merged_at"))
    state = "merged" if merged else str(pr.get("state") or "")
    summary = ci.get(sha) or {"state": "unknown" if state == "open" else "none", "failed": ""}
    return {"number": pr.get("number"), "url": str(pr.get("html_url") or ""), "state": state,
            "draft": bool(pr.get("draft")), "ci": summary["state"], "ci_failed_check": summary["failed"],
            "updated_at": str(pr.get("updated_at") or "")}


def _status_from_pr(pr: dict) -> str:
    if pr["state"] == "merged":
        return "done"
    if pr["ci"] == "failed":
        return "ci_failed"
    return "in_progress" if pr["draft"] else "review"


def _reason(task: dict, agent: str) -> str:
    """Short machine code; the page translates it."""
    s, pr = task["status"], task.get("pr") or {}
    if s == "ci_failed":
        return "ci_failed"
    if s == "review":
        return "ci_running" if pr.get("ci") in ("running", "unknown") else "awaiting_review"
    if s == "in_progress":
        return "draft_pr"
    if s == "queued":
        return "gemini_loop" if agent == "gemini" and "gemini" in task.get("labels", []) else "not_started"
    if s == "waiting_owner":
        return "owner_action"
    if s == "blocked":
        return "blocked_label"
    return "done"


def build_team_tasks(github: dict, *, roadmap: list, lanes: Optional[dict] = None, repo: str = "",
                     now: Optional[float] = None, done_limit: int = 25) -> dict:
    now = time.time() if now is None else float(now)
    lanes = lanes or {}
    ci = github.get("ci") or {}
    prs = [p for p in github.get("pulls") or [] if isinstance(p, dict)]
    by_issue: dict = {}
    for pr in prs:
        refs = {int(n) for n in _ISSUE_REF.findall(str(pr.get("body") or ""))}
        refs |= {int(n) for n in _BRANCH_ISSUE.findall(str((pr.get("head") or {}).get("ref") or ""))}
        for n in refs:
            current = by_issue.get(n)
            if current is None or _ts(pr.get("updated_at")) > _ts(current.get("updated_at")):
                by_issue[n] = pr
    known = {int(i.get("number") or 0) for i in github.get("issues") or []
             if isinstance(i, dict) and not i.get("pull_request") and _agent_of_issue(i.get("body"))}
    linked_prs = {id(p) for n, p in by_issue.items() if n in known}
    tasks = {a: [] for a in AGENTS + ("owner",)}

    for issue in github.get("issues") or []:
        if not isinstance(issue, dict) or issue.get("pull_request"):
            continue
        agent = _agent_of_issue(issue.get("body"))
        if not agent:
            continue
        number = int(issue.get("number") or 0)
        labels = [str(l.get("name") or "") for l in issue.get("labels") or [] if isinstance(l, dict)]
        pr = _pr_view(by_issue[number], ci) if number in by_issue else None
        if issue.get("state") == "closed":
            status = "done"
        elif pr and pr["state"] in ("open", "merged"):
            status = _status_from_pr(pr)  # merged PR = work done, even if the issue was left open
        elif "blocked" in labels:
            status = "blocked"
        else:
            status = "queued"
        task = {"id": "#" + str(number), "number": number, "title": str(issue.get("title") or "")[:200],
                "url": str(issue.get("html_url") or ""), "status": status, "progress": PROGRESS[status],
                "labels": labels, "pr": pr, "created_at": str(issue.get("created_at") or ""),
                "updated_at": str(issue.get("updated_at") or ""), "closed_at": str(issue.get("closed_at") or ""),
                "source": "issue"}
        task["reason"] = _reason(task, agent)
        tasks[agent].append(task)

    for pr in prs:  # agent PRs without a linked issue are tasks of their own
        agent = _agent_of_pr(pr)
        if not agent or id(pr) in linked_prs or (pr.get("state") == "closed" and not pr.get("merged_at")):
            continue
        view = _pr_view(pr, ci)
        status = _status_from_pr(view)
        task = {"id": "PR #" + str(pr.get("number")), "number": pr.get("number"), "title": str(pr.get("title") or "")[:200],
                "url": view["url"], "status": status, "progress": PROGRESS[status], "labels": [], "pr": view,
                "created_at": str(pr.get("created_at") or ""), "updated_at": view["updated_at"],
                "closed_at": str(pr.get("merged_at") or ""), "source": "pr"}
        task["reason"] = _reason(task, agent)
        tasks[agent].append(task)

    for item in roadmap or []:
        if item.get("human") and not item.get("done"):
            url = f"https://github.com/{repo}/blob/main/ROADMAP.md" + (f"#L{item['roadmap_line']}" if item.get("roadmap_line") else "")
            task = {"id": str(item.get("id") or ""), "number": None, "title": str(item.get("title") or "")[:200], "url": url,
                    "status": "waiting_owner", "progress": 0, "labels": [], "pr": None, "need": str(item.get("need") or "")[:300],
                    "created_at": "", "updated_at": "", "closed_at": "", "source": "roadmap"}
            task["reason"] = "owner_action"
            tasks["owner"].append(task)

    agents = {}
    week = now - 7 * 86400
    for agent, items in tasks.items():
        active = sorted([t for t in items if t["status"] != "done"], key=lambda t: (STATUSES.index(t["status"]), -_ts(t["updated_at"])))
        done = sorted([t for t in items if t["status"] == "done"], key=lambda t: -_ts(t["closed_at"] or t["updated_at"]))
        working = [t for t in active if t["status"] in ("in_progress", "review", "ci_failed")]
        queued = sorted([t for t in active if t["status"] == "queued"], key=lambda t: (t["number"] or 0))
        activity = max([_ts(t["updated_at"]) for t in items] + [0.0])
        facts = lanes.get(agent) or {}
        beat = facts.get("heartbeat_age_seconds")
        agents[agent] = {
            "label": LABELS[agent],
            "online": None if agent == "owner" else (facts.get("state") in ("idle", "working") if beat is not None else None),
            "heartbeat_age_seconds": beat,
            "last_activity_at": datetime.fromtimestamp(activity, timezone.utc).isoformat() if activity else None,
            "counts": {s: sum(t["status"] == s for t in items) for s in STATUSES},
            "done_7d": sum(_ts(t["closed_at"] or t["updated_at"]) >= week for t in done),
            "current": working[0] if working else None,
            "next": queued[0] if queued else None,
            "last_done": done[0] if done else None,
            "tasks": active + done[:done_limit],
        }
    totals = {s: sum(a["counts"][s] for a in agents.values()) for s in STATUSES}
    return {"synced_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), "github_available": bool(github.get("available")),
            "github_error": github.get("error") or "", "repo": repo, "agents": agents, "totals": totals,
            "done_7d": sum(a["done_7d"] for a in agents.values()),
            "progress_note": "progress = stage (queued 0, draft PR 40, CI failed 60, review 85, merged/closed 100), not measured code completion"}


class TeamTasksCache:
    """GitHub is read at most every ``ttl`` seconds; a manual refresh at most every ``min_refresh`` seconds."""

    def __init__(self, ttl: int = 180, min_refresh: int = 20):
        self.ttl, self.min_refresh = ttl, min_refresh
        self._lock = threading.Lock()
        self._at, self._data = 0.0, None

    def get(self, read: Callable[[], dict], refresh: bool = False) -> dict:
        with self._lock:
            age = time.time() - self._at
            if self._data is None or age > self.ttl or (refresh and age > self.min_refresh):
                self._data, self._at = read(), time.time()
            return self._data
