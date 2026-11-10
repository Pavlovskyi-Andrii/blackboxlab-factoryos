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
_DEPENDS_LINE = re.compile(r"Depends:\s*([^\n]*)", re.I)
_DEP_ISSUE = re.compile(r"#(\d+)")
_DEP_TASK = re.compile(r"\bT-\d+(?:-[A-Z0-9]+)?\b")
_OWNER_GATE = re.compile(r"\bCONDITIONAL\b|only after|не начинать до|только после", re.I)
QUEUE_TARGET = 10


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
    """passed | failed | running | none | unknown (a stale run), plus the first failing check name."""
    runs = [r for r in runs or [] if isinstance(r, dict)]
    if not runs:
        return {"state": "none", "failed": ""}
    failed = [r for r in runs if r.get("conclusion") in ("failure", "timed_out", "cancelled", "action_required")]
    if failed:
        return {"state": "failed", "failed": str(failed[0].get("name") or "")[:80]}
    if any(r.get("status") != "completed" for r in runs):
        return {"state": "running", "failed": ""}
    if any(r.get("conclusion") == "stale" for r in runs):  # #242: GitHub gave up on it; no result is not a pass
        return {"state": "unknown", "failed": ""}
    return {"state": "passed", "failed": ""}


def _actions_summary(runs: list) -> dict:
    """Same labels as _ci_summary, from GitHub Actions workflow runs (fine-grained tokens cannot read check runs)."""
    runs = [r for r in runs or [] if isinstance(r, dict)]
    if not runs:
        return {"state": "none", "failed": ""}
    bad = [r for r in runs if r.get("status") == "completed"
           and r.get("conclusion") in ("failure", "cancelled", "timed_out", "action_required", "startup_failure")]
    if bad:
        return {"state": "failed", "failed": str(bad[0].get("name") or "")[:80]}
    if any(r.get("status") != "completed" for r in runs):
        return {"state": "running", "failed": ""}
    if any(r.get("conclusion") not in ("success", "skipped", "neutral") for r in runs):
        return {"state": "unknown", "failed": ""}
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


def read_github(fetch: Callable[[str], object], max_ci: int = 20, owner: str = "") -> dict:
    """Recent activity for the board, plus (#259) every open issue the owner created, so intake from this snapshot
    does not miss an old open task that is no longer among the 100 most recently updated."""
    try:
        issues = fetch("/issues?state=all&per_page=100&sort=updated&direction=desc")
        open_truncated = False
        if owner and isinstance(issues, list):
            from github_pages import fetch_all
            open_owner, open_truncated = fetch_all(fetch, "/issues?state=open&creator=" + owner, max_pages=3)
            seen = {i.get("number") for i in issues if isinstance(i, dict)}
            issues = issues + [i for i in open_owner if isinstance(i, dict) and i.get("number") not in seen]
        pulls = fetch("/pulls?state=all&per_page=60&sort=updated&direction=desc")
        if not isinstance(issues, list) or not isinstance(pulls, list):
            raise ValueError("unexpected GitHub response")
        ci = {}
        # Open PRs, then recently merged ones: Evidence T1.3 needs CI on the commit that was merged.
        wanted = [p for p in pulls if isinstance(p, dict) and p.get("state") == "open"] + \
                 [p for p in pulls if isinstance(p, dict) and p.get("state") == "closed" and p.get("merged_at")]
        via_actions = False
        for pr in wanted[:max_ci]:
            sha = str((pr.get("head") or {}).get("sha") or "")
            if sha:
                try:
                    if not via_actions:
                        try:
                            data = fetch("/commits/" + sha + "/check-runs?per_page=50")
                        except Exception as exc:
                            if getattr(exc, "code", None) not in (403, 404):
                                raise
                            via_actions = True      # fine-grained token: no Checks permission exists
                    if via_actions:
                        data = fetch("/actions/runs?head_sha=" + sha + "&per_page=50")
                        runs = data.get("workflow_runs") if isinstance(data, dict) else None
                        if not isinstance(runs, list):
                            ci[sha] = {"state": "unknown", "failed": ""}
                            continue
                        summary = _actions_summary(runs)
                        total = data.get("total_count")
                        if summary["state"] in ("passed", "none") and isinstance(total, int) and total > len(runs):
                            summary = {"state": "unknown", "failed": ""}
                        ci[sha] = summary
                        continue
                    runs = data.get("check_runs") if isinstance(data, dict) else None
                    if not isinstance(runs, list):  # #242: an unexpected body is unknown, not "no checks"
                        ci[sha] = {"state": "unknown", "failed": ""}
                        continue
                    summary = _ci_summary(runs)
                    total = data.get("total_count")
                    if summary["state"] in ("passed", "none") and isinstance(total, int) and total > len(runs):
                        summary = {"state": "unknown", "failed": ""}  # #242: unseen runs (next page) may be red
                    ci[sha] = summary
                except Exception:
                    ci[sha] = {"state": "unknown", "failed": ""}
        return {"available": True, "issues": issues, "pulls": pulls, "ci": ci, "open_owner_truncated": open_truncated}
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


_NO_DEPENDS = re.compile(r"^(none|no|n/a|нет|немає|ні)\b|^[-—–]\s", re.I)


def _depends(body) -> str:
    """The Depends: value. "Depends: none …" means no dependencies, even if references follow as context
    (#289 said "Depends: none for diagnosis … Reuse #41, #61" and was deferred forever behind the open epic #41)."""
    m = _DEPENDS_LINE.search(str(body or ""))
    value = m.group(1).strip()[:300] if m else ""
    return "" if _NO_DEPENDS.match(value) else value


def _prs_by_issue(prs: list) -> dict:
    by_issue: dict = {}
    for pr in prs:
        refs = {int(n) for n in _ISSUE_REF.findall(str(pr.get("body") or ""))}
        refs |= {int(n) for n in _BRANCH_ISSUE.findall(str((pr.get("head") or {}).get("ref") or ""))}
        for n in refs:
            current = by_issue.get(n)
            if current is None or _ts(pr.get("updated_at")) > _ts(current.get("updated_at")):
                by_issue[n] = pr
    return by_issue


def queue_readiness(github: dict, *, roadmap: list, agent: str = "claude", target: int = QUEUE_TARGET) -> dict:
    """#231 Queue Keeper: which open Issues of one agent can really be taken now. Read-only; it never creates,
    claims or starts anything (claims stay with Relay). Deterministic for the same input, so repeated runs agree.

    in_review: a linked PR exists (open or merged) · blocked: ``blocked`` label, owner gate in the title, an open
    ``Depends:`` issue, an unfinished ``Depends:`` ROADMAP task, or an open PR of another agent on it · ready: the rest.
    A ``Depends:`` issue not present in the GitHub read is listed as unverified rather than guessed."""
    if not github.get("available"):
        return {"agent": agent, "available": False, "error": str(github.get("error") or "GitHub unavailable"),
                "target": target, "counts": None, "ready": [], "blocked": [], "in_review": [], "shortfall": None, "escalation": ""}
    items = [i for i in github.get("issues") or [] if isinstance(i, dict)]
    issues = [i for i in items if not i.get("pull_request")]
    # A dependency may be an issue or a PR (GitHub lists PRs among issues too); a merged/closed PR is resolved.
    state = {int(i.get("number") or 0): str(i.get("state") or "") for i in items}
    state.update({int(p.get("number") or 0): str(p.get("state") or "") for p in github.get("pulls") or [] if isinstance(p, dict)})
    roadmap_done = {str(t.get("id")): bool(t.get("done")) for t in roadmap or [] if t.get("id")}
    by_issue = _prs_by_issue([p for p in github.get("pulls") or [] if isinstance(p, dict)])
    ready, blocked, in_review = [], [], []
    for issue in sorted(issues, key=lambda i: int(i.get("number") or 0)):
        if issue.get("state") != "open" or _agent_of_issue(issue.get("body")) != agent:
            continue
        number, title = int(issue.get("number") or 0), str(issue.get("title") or "")[:200]
        labels = {str(l.get("name") or "") for l in issue.get("labels") or [] if isinstance(l, dict)}
        item = {"number": number, "title": title, "url": str(issue.get("html_url") or "")}
        pr = by_issue.get(number)
        pr_agent = _agent_of_pr(pr) if pr else ""
        if pr and (pr.get("merged_at") or pr.get("state") == "open") and pr_agent in ("", agent):
            in_review.append(dict(item, pr=pr.get("number")))
            continue
        depends = _depends(issue.get("body"))
        reasons, unverified = [], []
        if "blocked" in labels:
            reasons.append("blocked_label")
        if _OWNER_GATE.search(title):
            reasons.append("owner_gate")
        if pr and pr.get("state") == "open" and pr_agent not in ("", agent):
            reasons.append(f"claimed_by_{pr_agent}")
        for n in sorted({int(x) for x in _DEP_ISSUE.findall(depends)}):
            if n == number:
                continue
            if n not in state:
                unverified.append(f"#{n}")
            elif state[n] == "open":
                reasons.append(f"depends_open_#{n}")
        for task in sorted(set(_DEP_TASK.findall(depends))):
            if task in roadmap_done and not roadmap_done[task]:
                reasons.append(f"depends_roadmap_{task}")
        if unverified:
            item["unverified_depends"] = unverified
        if reasons:
            blocked.append(dict(item, reasons=reasons))
        else:
            ready.append(item)
    shortfall = max(0, target - len(ready))
    escalation = ""
    if shortfall:
        escalation = (f"{len(ready)} of {target} Claude tasks are ready; {len(blocked)} blocked. "
                      "No task is invented to fill the queue: the owner (or ChatGPT, under the owner's rules) adds approved "
                      "work, or unblocks the listed dependencies.")
    return {"agent": agent, "available": True, "target": target,
            "counts": {"open": len(ready) + len(blocked) + len(in_review), "ready": len(ready),
                       "blocked": len(blocked), "in_review": len(in_review)},
            "ready": ready, "blocked": blocked, "in_review": in_review, "shortfall": shortfall, "escalation": escalation}


def build_team_tasks(github: dict, *, roadmap: list, lanes: Optional[dict] = None, repo: str = "",
                     now: Optional[float] = None, done_limit: int = 25, owner_cards: Optional[list] = None) -> dict:
    """owner_cards: open owner-desk decision cards [{id, title, covers: [issue numbers]}]. They are listed as the
    owner's tasks, and a blocked Claude issue they cover links to the card that explains how to unblock it."""
    now = time.time() if now is None else float(now)
    queue = queue_readiness(github, roadmap=roadmap, agent="claude")
    blocked_by = {t["number"]: t["reasons"] for t in queue.get("blocked") or []}
    card_for = {int(n): str(c.get("id")) for c in owner_cards or [] for n in c.get("covers") or []}
    lanes = lanes or {}
    ci = github.get("ci") or {}
    prs = [p for p in github.get("pulls") or [] if isinstance(p, dict)]
    by_issue = _prs_by_issue(prs)
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
        elif "blocked" in labels or (agent == "claude" and number in blocked_by):
            status = "blocked"  # #231 Queue Keeper: an open Depends issue/task or an owner gate is a real block
        else:
            status = "queued"
        task = {"id": "#" + str(number), "number": number, "title": str(issue.get("title") or "")[:200],
                "url": str(issue.get("html_url") or ""), "status": status, "progress": PROGRESS[status],
                "labels": labels, "pr": pr, "created_at": str(issue.get("created_at") or ""),
                "updated_at": str(issue.get("updated_at") or ""), "closed_at": str(issue.get("closed_at") or ""),
                "source": "issue"}
        task["reason"] = _reason(task, agent)
        if status == "blocked" and number in blocked_by and "blocked" not in labels:
            reasons = blocked_by[number]
            deps = [r.split("_", 2)[-1] for r in reasons if r.startswith("depends_")]
            task["reason"] = "depends" if deps else ("owner_gate" if "owner_gate" in reasons else "blocked_by_other")
            task["blocked_by"] = deps
        if number in card_for:
            task["decision_card"] = card_for[number]
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
    for card in owner_cards or []:  # decisions the site explains step by step (owner desk)
        task = {"id": str(card.get("id") or ""), "number": None, "title": str(card.get("title") or "")[:200], "url": "",
                "status": "waiting_owner", "progress": 0, "labels": [], "pr": None, "created_at": "", "updated_at": "",
                "closed_at": "", "source": "owner_desk", "decision_card": str(card.get("id") or ""), "reason": "owner_decision"}
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
    return {"synced_at": str(github.get("fetched_at") or "") or datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "github_source": str(github.get("source") or "render"), "github_available": bool(github.get("available")),
            "github_error": github.get("error") or "", "repo": repo, "agents": agents, "totals": totals,
            "done_7d": sum(a["done_7d"] for a in agents.values()),
            "queue_keeper": queue,
            "progress_note": "progress = stage (queued 0, draft PR 40, CI failed 60, review 85, merged/closed 100), not measured code completion"}


def compact_github(github: dict) -> dict:
    """Only the fields the page needs: Owner line, issue refs, states, times, PR heads, CI. Bodies are not kept."""
    def owner_line(body):  # plus the Depends line, which the Queue Keeper needs; the rest of the body is dropped
        first = str(body or "").split("\n", 1)[0][:200]
        dep = _depends(body)
        return first + ("\nDepends: " + dep if dep else "")

    def refs(body):
        return " ".join("Refs #" + n for n in _ISSUE_REF.findall(str(body or "")))[:500]
    issues = [{"number": i.get("number"), "title": str(i.get("title") or "")[:200], "body": owner_line(i.get("body")),
               "author": str((i.get("user") or {}).get("login") or i.get("author") or "")[:60],
               "state": i.get("state"), "html_url": i.get("html_url"), "pull_request": bool(i.get("pull_request")),
               "labels": [{"name": str(l.get("name") or "")[:50]} for l in i.get("labels") or [] if isinstance(l, dict)],
               "updated_at": i.get("updated_at"), "created_at": i.get("created_at"), "closed_at": i.get("closed_at")}
              for i in github.get("issues") or [] if isinstance(i, dict)]
    pulls = [{"number": p.get("number"), "title": str(p.get("title") or "")[:200], "body": refs(p.get("body")),
              "draft": bool(p.get("draft")), "state": p.get("state"), "merged_at": p.get("merged_at"),
              "head": {"ref": str((p.get("head") or {}).get("ref") or "")[:120], "sha": str((p.get("head") or {}).get("sha") or "")[:64]},
              "html_url": p.get("html_url"), "updated_at": p.get("updated_at"), "created_at": p.get("created_at")}
             for p in github.get("pulls") or [] if isinstance(p, dict)]
    return {"available": bool(github.get("available")), "error": str(github.get("error") or "")[:80],
            "issues": issues, "pulls": pulls, "ci": {str(k)[:64]: v for k, v in (github.get("ci") or {}).items()}}


def valid_snapshot(data) -> bool:
    return (isinstance(data, dict) and data.get("available") is True and isinstance(data.get("issues"), list)
            and isinstance(data.get("pulls"), list) and isinstance(data.get("ci"), dict)
            and len(data["issues"]) <= 400 and len(data["pulls"]) <= 200)  # 100 recent + up to 300 open owner issues


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

    def peek(self) -> Optional[dict]:
        """The cached board without reading GitHub (None until the first read). Lock-free on purpose: the
        board builder itself runs inside get() and asks the lane board, which peeks here."""
        return self._data

    def invalidate(self) -> None:
        with self._lock:
            self._at = 0.0
