"""T-616 / Issue #189 — AI Release Guardian, the MVP Factory pilot `release-guardian`.

A read-only GitHub pull-request board: author, the real state of check runs, reviews and blockers.

The rule this pilot exists for: **skipped, neutral or missing checks are never success**.
- A check run counts as passed only with conclusion `success`.
- `skipped`, `neutral` and `stale` runs are "not verified": they are listed, never counted as passes.
- A GitHub Actions workflow that finished without running a single job (a check suite with zero check runs and a
  failing conclusion, e.g. a workflow that could not start) is a failure, even when other workflows are green.
- No checks at all, or only unverified ones, gives readiness `unknown`, never `green`.
- A required check (from the branch rulesets) that has not reported is `unknown`; if the rules cannot be read, that
  is said explicitly.
- If GitHub cannot be read, everything stays `unknown`. Nothing here infers a status.

Read-only: the client only issues GET requests. It never comments, sets a status, approves or merges.
Responses are cached (TTL) and the client stops calling GitHub when the rate limit is almost spent.
The token is read through a callable at call time and never returned, logged or stored in a response.
"""
from __future__ import annotations

import json
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

from fastapi import Request
from fastapi.responses import JSONResponse

READINESS = ("green", "red", "pending", "unknown")
PASS_CONCLUSIONS = frozenset({"success"})
# `cancelled` is not success: GitHub blocks a required check on it, and a cancelled run proved nothing.
FAIL_CONCLUSIONS = frozenset({"failure", "timed_out", "action_required", "startup_failure", "cancelled", "error"})
UNVERIFIED_CONCLUSIONS = frozenset({"skipped", "neutral", "stale"})
PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending", "expected"})
ACTIONS_APP = "github-actions"
PILOT_PRS = (162, 163, 144)  # Issue #189: "Start on FactoryOS PR #162/#163/#144"
MAX_PRS = 10
MAX_PRS_ANONYMOUS = 5
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")


# --------------------------------------------------------------------------------------------------------------------
# Pure classification. No I/O; every input is a parsed GitHub API object (or a fixture of one).
# --------------------------------------------------------------------------------------------------------------------

def classify_run(status: Any, conclusion: Any) -> str:
    """One check run or commit status -> passed | failed | pending | not_verified.

    Anything unexpected (an unknown conclusion, a completed run without one) is `not_verified`, never `passed`."""
    status = str(status or "").lower()
    conclusion = str(conclusion or "").lower()
    if status and status != "completed":
        return "pending" if status in PENDING_STATUSES else "not_verified"
    if conclusion in PASS_CONCLUSIONS:
        return "passed"
    if conclusion in FAIL_CONCLUSIONS:
        return "failed"
    return "not_verified"


def _latest_by(items: Iterable[dict], key: Callable[[dict], Any]) -> list[dict]:
    """Keep the newest item per key (highest id) — a re-run replaces the earlier attempt."""
    best: dict[Any, dict] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        k = key(item)
        held = best.get(k)
        if held is None or int(item.get("id") or 0) >= int(held.get("id") or 0):
            best[k] = item
    return list(best.values())


def _app_slug(obj: dict) -> str:
    app = obj.get("app")
    return str(app.get("slug") or "") if isinstance(app, dict) else ""


def collect_checks(check_runs: Iterable[dict] = (), *, suites: Iterable[dict] = (), workflow_runs: Iterable[dict] = (),
                   statuses: Iterable[dict] = ()) -> tuple[list[dict], list[dict]]:
    """Normalise check runs, commit statuses and job-less Actions workflows into one list of checks.

    Returns (checks, notes). Each check: {name, source, state, status, conclusion, url}."""
    checks: list[dict] = []
    notes: list[dict] = []
    for run in _latest_by(check_runs, lambda r: (_app_slug(r), str(r.get("name") or ""))):
        checks.append({"name": str(run.get("name") or "?"), "source": "check_run", "app": _app_slug(run),
                       "state": classify_run(run.get("status"), run.get("conclusion")),
                       "status": str(run.get("status") or ""), "conclusion": str(run.get("conclusion") or ""),
                       "url": str(run.get("html_url") or "")})
    for st in _latest_by(statuses, lambda s: str(s.get("context") or "")):
        state = str(st.get("state") or "").lower()
        mapped = {"success": "passed", "failure": "failed", "error": "failed", "pending": "pending"}.get(state, "not_verified")
        checks.append({"name": str(st.get("context") or "?"), "source": "status", "app": "",
                       "state": mapped, "status": state, "conclusion": state, "url": str(st.get("target_url") or "")})
    by_suite = {}
    for wr in workflow_runs:
        if isinstance(wr, dict) and wr.get("check_suite_id") is not None:
            by_suite[wr["check_suite_id"]] = wr
    for suite in suites:
        if not isinstance(suite, dict) or int(suite.get("latest_check_runs_count") or 0) > 0:
            continue
        slug = _app_slug(suite)
        if slug != ACTIONS_APP:
            # Other apps (e.g. Render) open suites that may never run; they are listed but cannot pass or fail a PR.
            notes.append({"code": "app_suite_without_runs", "name": slug or "?",
                          "detail": str(suite.get("status") or "")})
            continue
        wr = by_suite.get(suite.get("id")) or {}
        name = str(wr.get("name") or "workflow")
        event = str(wr.get("event") or "")
        label = f"{name} ({event})" if event else name
        state = classify_run(suite.get("status"), suite.get("conclusion"))
        if state == "passed" or state == "not_verified":
            # A workflow that "succeeded" or was skipped without one job verified nothing.
            notes.append({"code": "workflow_without_jobs", "name": label, "detail": str(suite.get("conclusion") or "")})
            continue
        checks.append({"name": label, "source": "workflow_no_jobs", "app": slug, "state": state,
                       "status": str(suite.get("status") or ""), "conclusion": str(suite.get("conclusion") or ""),
                       "url": str(wr.get("html_url") or "")})
    checks.sort(key=lambda c: ({"failed": 0, "pending": 1, "not_verified": 2, "passed": 3}[c["state"]], c["name"]))
    return checks, notes


def classify_readiness(checks: list[dict], *, required: list[str] | None = None, truncated: bool = False,
                       available: bool = True) -> dict[str, Any]:
    """Readiness of a head commit from normalised checks.

    red      — any check failed (including a workflow that ran no job)
    pending  — nothing failed and something is still running or queued
    unknown  — nothing failed or runs, but there is nothing that proves success: no checks, only skipped/neutral,
               a required check missing or not verified, an incomplete list, or GitHub unreadable
    green    — at least one check passed, none failed or pending, every required check passed, list complete
    """
    reasons: list[dict] = []
    if not available:
        return {"readiness": "unknown", "reasons": [{"code": "github_unavailable"}], "counts": _counts(checks)}
    counts = _counts(checks)
    failed = [c for c in checks if c["state"] == "failed"]
    pending = [c for c in checks if c["state"] == "pending"]
    passed_names = {c["name"] for c in checks if c["state"] == "passed"}
    present_names = {c["name"] for c in checks}
    for c in failed:
        reasons.append({"code": "workflow_no_jobs" if c["source"] == "workflow_no_jobs" else "check_failed",
                        "name": c["name"], "detail": c["conclusion"]})
    for c in pending:
        reasons.append({"code": "check_pending", "name": c["name"], "detail": c["status"]})
    unknown = False
    if required is None:
        reasons.append({"code": "required_unknown"})
    else:
        for name in required:
            if name not in present_names:
                reasons.append({"code": "required_missing", "name": name})
                unknown = True
            elif name not in passed_names and not any(c["name"] == name and c["state"] in ("failed", "pending")
                                                      for c in checks):
                reasons.append({"code": "required_not_verified", "name": name})
                unknown = True
    for c in checks:
        if c["state"] == "not_verified" and c["name"] not in (required or ()):
            reasons.append({"code": "not_counted", "name": c["name"], "detail": c["conclusion"] or c["status"]})
    if not checks:
        reasons.append({"code": "no_checks"})
        unknown = True
    elif not passed_names:
        reasons.append({"code": "nothing_passed"})
        unknown = True
    if truncated:
        reasons.append({"code": "list_truncated"})
        unknown = True
    if failed:
        readiness = "red"
    elif pending:
        readiness = "pending"
    elif unknown:
        readiness = "unknown"
    else:
        readiness = "green"
    return {"readiness": readiness, "reasons": reasons, "counts": counts}


def _counts(checks: list[dict]) -> dict[str, int]:
    out = {"passed": 0, "failed": 0, "pending": 0, "not_verified": 0}
    for c in checks:
        out[c["state"]] = out.get(c["state"], 0) + 1
    return out


def summarize_reviews(reviews: Iterable[dict], requested: Iterable[dict] = ()) -> dict[str, Any]:
    """The latest decisive review per reviewer (a COMMENTED review does not cancel an approval)."""
    latest: dict[str, dict] = {}
    for r in reviews:
        if not isinstance(r, dict):
            continue
        state = str(r.get("state") or "").upper()
        if state not in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            continue
        login = str((r.get("user") or {}).get("login") or "?") if isinstance(r.get("user"), dict) else "?"
        held = latest.get(login)
        if held is None or int(r.get("id") or 0) >= int(held.get("id") or 0):
            latest[login] = r
    approved = sorted(k for k, v in latest.items() if str(v.get("state")).upper() == "APPROVED")
    changes = sorted(k for k, v in latest.items() if str(v.get("state")).upper() == "CHANGES_REQUESTED")
    pending = sorted(str(u.get("login") or "?") for u in requested if isinstance(u, dict))
    return {"approved": approved, "changes_requested": changes, "requested": pending}


def parse_rules(rules: Any) -> dict[str, Any]:
    """Branch rulesets (GET /rules/branches/{branch}) -> required check names and approvals.

    `None` input means the rules could not be read: both stay unknown (None)."""
    if not isinstance(rules, list):
        return {"required_checks": None, "required_approvals": None, "visible": False}
    required: list[str] = []
    approvals = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        params = rule.get("parameters") if isinstance(rule.get("parameters"), dict) else {}
        if rule.get("type") == "required_status_checks":
            for item in params.get("required_status_checks") or []:
                if isinstance(item, dict) and item.get("context") and item["context"] not in required:
                    required.append(str(item["context"]))
        elif rule.get("type") == "pull_request":
            approvals = max(approvals, int(params.get("required_approving_review_count") or 0))
    return {"required_checks": required, "required_approvals": approvals, "visible": True}


def assess_pull(pull: dict, *, readiness: dict, reviews: dict, rules: dict) -> dict[str, Any]:
    """PR-level blockers on top of check readiness, and a single verdict."""
    blockers: list[dict] = []
    notes: list[dict] = []
    merged = bool(pull.get("merged") or pull.get("merged_at"))
    state = "merged" if merged else str(pull.get("state") or "unknown")
    if pull.get("draft"):
        blockers.append({"code": "draft"})
    mergeable = pull.get("mergeable")
    mstate = str(pull.get("mergeable_state") or "")
    if state == "open":
        if mergeable is False or mstate == "dirty":
            blockers.append({"code": "merge_conflict"})
        elif mergeable is None:
            notes.append({"code": "mergeability_unknown"})
        if mstate == "behind":
            notes.append({"code": "behind_base"})
    if reviews["changes_requested"]:
        blockers.append({"code": "changes_requested", "name": ", ".join(reviews["changes_requested"])})
    need = rules.get("required_approvals")
    if need is None:
        notes.append({"code": "review_rules_unknown"})
    elif need and len(reviews["approved"]) < need:
        blockers.append({"code": "approvals_missing", "detail": f"{len(reviews['approved'])}/{need}"})
    if readiness["readiness"] != "green":
        blockers.append({"code": "checks_" + readiness["readiness"]})
    if state != "open":
        verdict = state  # merged / closed: shown for the record, nothing to release
    elif not blockers:
        verdict = "ready"
    else:
        verdict = "not_ready"
    return {"state": state, "verdict": verdict, "blockers": blockers, "notes": notes}


# --------------------------------------------------------------------------------------------------------------------
# Read-only GitHub client with a TTL cache and a rate-limit guard.
# --------------------------------------------------------------------------------------------------------------------

class GitHubUnavailable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _error_reason(exc: Exception) -> str:
    try:
        from relay import github_error_reason  # the shared, redacting categoriser (#41)
        return github_error_reason(exc)
    except Exception:
        return "network" if getattr(exc, "code", None) is None else f"http_{getattr(exc, 'code', '')}"


class GitHubReader:
    """GET-only, cached. `fetch(path, token) -> (data, headers)` can be replaced in tests."""

    def __init__(self, repo: str, token_fn: Callable[[], str] = lambda: "", *, fetch: Callable | None = None,
                 clock: Callable[[], float] = time.time, ttl: float = 120.0, ttl_anonymous: float = 600.0,
                 min_remaining: int = 5):
        if not REPO_RE.match(repo or ""):
            raise ValueError("bad repo")
        self.repo = repo
        self.token_fn = token_fn
        self.fetch = fetch or self._http_get
        self.clock = clock
        self.ttl, self.ttl_anonymous = ttl, ttl_anonymous
        self.min_remaining = min_remaining
        self._cache: dict[tuple[str, bool], tuple[float, Any]] = {}
        self._lock = threading.Lock()
        self.rate: dict[str, Any] = {"remaining": None, "reset": None}
        self.calls = 0

    def authenticated(self) -> bool:
        try:
            return bool((self.token_fn() or "").strip())
        except Exception:
            return False

    def _http_get(self, path: str, token: str):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "FactoryOS-ReleaseGuardian/1.0",
                   "X-GitHub-Api-Version": "2022-11-28"}
        if token:
            headers["Authorization"] = "Bearer " + token
        req = urllib.request.Request("https://api.github.com/repos/" + self.repo + path, headers=headers, method="GET")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.load(resp), dict(resp.headers.items())

    def get(self, path: str) -> tuple[Any, bool]:
        """(data, from_cache). Serves a fresh cache entry, else calls GitHub; on failure serves a stale entry if one
        exists, otherwise raises GitHubUnavailable with a fixed reason (never the token or response text)."""
        token = ""
        try:
            token = (self.token_fn() or "").strip()
        except Exception:
            token = ""
        key = (path, bool(token))
        ttl = self.ttl if token else self.ttl_anonymous
        now = self.clock()
        with self._lock:
            held = self._cache.get(key)
            if held and now - held[0] < ttl:
                return held[1], True
            reset = self.rate.get("reset")
            guard = (self.rate.get("remaining") is not None and self.rate["remaining"] <= self.min_remaining
                     and reset is not None and now < reset)
        if guard:
            if held:
                return held[1], True
            raise GitHubUnavailable("rate_limit_guard")
        try:
            self.calls += 1
            data, headers = self.fetch(path, token)
        except Exception as exc:
            reason = _error_reason(exc)
            if reason == "rate_limited":
                with self._lock:
                    self.rate = {"remaining": 0, "reset": now + 600}
            if held:
                return held[1], True
            raise GitHubUnavailable(reason) from None
        self._note_rate(headers or {}, now)
        with self._lock:
            self._cache[key] = (now, data)
            if len(self._cache) > 500:
                for old in sorted(self._cache, key=lambda k: self._cache[k][0])[:100]:
                    del self._cache[old]
        return data, False

    def _note_rate(self, headers: dict, now: float) -> None:
        low = {str(k).lower(): v for k, v in headers.items()}
        try:
            remaining = int(low["x-ratelimit-remaining"])
            reset = float(low.get("x-ratelimit-reset") or now + 3600)
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            self.rate = {"remaining": remaining, "reset": reset}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


class ReleaseGuardian:
    def __init__(self, reader: GitHubReader):
        self.reader = reader

    def _rules(self, branch: str) -> dict:
        try:
            data, _ = self.reader.get("/rules/branches/" + urllib.parse.quote(branch, safe=""))
        except GitHubUnavailable:
            data = None
        return parse_rules(data)

    def pull_report(self, number: int, rules_cache: dict) -> dict[str, Any]:
        base = {"number": number, "url": f"https://github.com/{self.reader.repo}/pull/{number}"}
        try:
            pull, _ = self.reader.get(f"/pulls/{number}")
        except GitHubUnavailable as exc:
            return dict(base, available=False, reason=exc.reason, readiness={"readiness": "unknown",
                        "reasons": [{"code": "github_unavailable", "detail": exc.reason}], "counts": _counts([])},
                        verdict="unknown", blockers=[{"code": "checks_unknown"}], notes=[], checks=[])
        if not isinstance(pull, dict):
            return dict(base, available=False, reason="bad_response", verdict="unknown", checks=[], notes=[],
                        blockers=[{"code": "checks_unknown"}],
                        readiness={"readiness": "unknown", "reasons": [{"code": "github_unavailable"}], "counts": _counts([])})
        sha = str((pull.get("head") or {}).get("sha") or "")
        branch = str((pull.get("base") or {}).get("ref") or "main")
        if branch not in rules_cache:
            rules_cache[branch] = self._rules(branch)
        rules = rules_cache[branch]
        available = bool(re.fullmatch(r"[0-9a-f]{40}", sha))
        checks: list[dict] = []
        notes: list[dict] = []
        truncated = False
        failure = ""
        try:
            if not available:
                raise GitHubUnavailable("no_head_sha")
            runs, _ = self.reader.get(f"/commits/{sha}/check-runs?filter=latest&per_page=100")
            suites, _ = self.reader.get(f"/commits/{sha}/check-suites?per_page=100")
            wruns, _ = self.reader.get(f"/actions/runs?head_sha={sha}&per_page=100")
            status, _ = self.reader.get(f"/commits/{sha}/status?per_page=100")
            run_list = (runs.get("check_runs") or []) if isinstance(runs, dict) else []
            truncated = isinstance(runs, dict) and int(runs.get("total_count") or 0) > len(run_list)
            checks, notes = collect_checks(
                run_list,
                suites=(suites.get("check_suites") or []) if isinstance(suites, dict) else [],
                workflow_runs=(wruns.get("workflow_runs") or []) if isinstance(wruns, dict) else [],
                statuses=(status.get("statuses") or []) if isinstance(status, dict) else [])
        except GitHubUnavailable as exc:
            available, failure = False, exc.reason
        readiness = classify_readiness(checks, required=rules["required_checks"], truncated=truncated, available=available)
        if failure:
            readiness["reasons"][0]["detail"] = failure
        try:
            raw_reviews, _ = self.reader.get(f"/pulls/{number}/reviews?per_page=100")
            reviews = summarize_reviews(raw_reviews if isinstance(raw_reviews, list) else [],
                                        pull.get("requested_reviewers") or [])
            reviews_ok = True
        except GitHubUnavailable:
            reviews = summarize_reviews([], pull.get("requested_reviewers") or [])
            reviews_ok = False
        verdict = assess_pull(pull, readiness=readiness, reviews=reviews, rules=rules)
        if not reviews_ok:
            verdict["notes"].append({"code": "reviews_unavailable"})
            if verdict["verdict"] == "ready":
                verdict["verdict"] = "not_ready"
                verdict["blockers"].append({"code": "reviews_unknown"})
        user = pull.get("user") if isinstance(pull.get("user"), dict) else {}
        return dict(base, available=available, title=str(pull.get("title") or "")[:200],
                    author={"login": str(user.get("login") or "?"), "type": str(user.get("type") or "")},
                    head_sha=sha, base=branch, updated_at=str(pull.get("updated_at") or ""),
                    readiness=readiness, checks=checks, check_notes=notes, reviews=reviews,
                    required_checks=rules["required_checks"], required_approvals=rules["required_approvals"],
                    state=verdict["state"], verdict=verdict["verdict"], blockers=verdict["blockers"], notes=verdict["notes"])

    def dashboard(self, numbers: list[int] | None = None) -> dict[str, Any]:
        authed = self.reader.authenticated()
        cap = MAX_PRS if authed else MAX_PRS_ANONYMOUS
        source = "requested"
        list_error = ""
        if not numbers:
            source = "open"
            try:
                pulls, _ = self.reader.get(f"/pulls?state=open&sort=updated&direction=desc&per_page={cap}")
                numbers = [int(p["number"]) for p in pulls if isinstance(p, dict) and p.get("number")] if isinstance(pulls, list) else []
            except GitHubUnavailable as exc:
                numbers, list_error = [], exc.reason
        numbers = list(dict.fromkeys(numbers))[:cap]
        rules_cache: dict[str, dict] = {}
        pulls = [self.pull_report(n, rules_cache) for n in numbers]
        return {"repo": self.reader.repo, "checked_at": _iso(self.reader.clock()), "source": source,
                "list_error": list_error, "auth": "token" if authed else "anonymous", "limit": cap,
                "pilot_prs": list(PILOT_PRS), "pulls": pulls, "read_only": True,
                "rate": {"remaining": self.reader.rate.get("remaining")},
                "rule": "Only conclusion=success passes. Skipped, neutral, missing checks and workflows without jobs are "
                        "never success; no checks means readiness unknown."}


def parse_pr_numbers(raw: str) -> list[int]:
    out: list[int] = []
    for part in re.split(r"[\s,;]+", str(raw or "")):
        part = part.strip().lstrip("#")
        if part.isdigit() and 0 < int(part) < 10_000_000:
            out.append(int(part))
    return out[:MAX_PRS]


def install_release_guardian_routes(app, guardian: ReleaseGuardian, identity_fn: Callable) -> None:
    """GET /api/release-guardian?prs=162,163 — owner only, read-only."""

    @app.get("/api/release-guardian")
    def release_guardian_dashboard(request: Request, prs: str = ""):
        if (identity_fn(request) or {}).get("role") != "owner":
            return JSONResponse({"detail": "Owner access required"}, status_code=403)
        return guardian.dashboard(parse_pr_numbers(prs) or None)
