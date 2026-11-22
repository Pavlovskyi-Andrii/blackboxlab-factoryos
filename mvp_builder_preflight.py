"""MVP Builder M1B (#273): offline preflight guard before a Builder task may be claimed.

Side-effect free. It takes a build_request (see ``mvp_builder_request``) and a dict of *facts* that the caller has
already gathered (from GitHub, Relay, the runtime). It never calls GitHub or Relay, never claims and never runs a
worker. It answers one of four verdicts, with every reason and the fact source it came from:

- ``READY``       every check passed on facts that were actually read;
- ``BLOCKED``     a hard stop: wrong owner, open dependency, file overlap with an active PR, task already claimed,
                  no subscription/runtime, any spend above zero, or an invalid request;
- ``NEEDS_OWNER`` the owner must act: spec not approved, owner approval gate pending or denied;
- ``UNKNOWN``     a fact is missing, forbidden (HTTP 403), errored or stale. Unknown never becomes READY.

Precedence: BLOCKED > NEEDS_OWNER > UNKNOWN > READY. All reasons are reported, not just the first.

Facts shape (each block has ``status``: ``ok`` | ``forbidden`` | ``missing`` | ``error``; an absent block is
``missing``)::

    {"issue":   {"status": "ok", "owner": "Claude", "state": "open"},
     "spec":    {"status": "ok", "approved": True},
     "depends": {"status": "ok", "items": {"41": "closed", "186": "open"}},
     "gates":   {"status": "ok", "owner_approval": "not_required" | "granted" | "pending" | "denied"},
     "active_prs": {"status": "ok", "prs": [{"number": 194, "files": ["mvp_manager.py"]}]},
     "claim":   {"status": "ok", "run_id": None | "run-…", "lease_expires_at": "2026-11-08T12:00:00Z"},
     "runtime": {"status": "ok", "subscription_available": True, "worker_online": True},
     "cost":    {"status": "ok", "estimated_usd": 0}}
"""
from __future__ import annotations

from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Any, Optional

from mvp_builder_request import validate as validate_request

READY, BLOCKED, NEEDS_OWNER, UNKNOWN = "READY", "BLOCKED", "NEEDS_OWNER", "UNKNOWN"
_RANK = {BLOCKED: 3, NEEDS_OWNER: 2, UNKNOWN: 1, READY: 0}
SOURCES = ("request", "issue", "spec", "depends", "gates", "active_prs", "claim", "runtime", "cost")


def _stamp(text: Any) -> Optional[datetime]:
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _overlaps(scope: list, files: list) -> list:
    """Paths of an active PR that fall inside this request's files_scope (exact, glob or directory prefix)."""
    hits = []
    for f in files:
        if not isinstance(f, str):
            continue
        for s in scope:
            if f == s or fnmatchcase(f, s) or f.startswith(s.rstrip("/") + "/") or s.startswith(f.rstrip("/") + "/"):
                hits.append(f)
                break
    return sorted(set(hits))


def evaluate(request: Any, facts: Any, *, now: str) -> dict:
    """Return ``{"verdict", "reasons": [{"verdict","code","source","detail"}], "checked": [...]}``."""
    reasons: list = []
    checked: list = []

    def add(verdict: str, code: str, source: str, detail: str = "") -> None:
        reasons.append({"verdict": verdict, "code": code, "source": source, "detail": detail})

    clock = _stamp(now)
    if clock is None:
        raise ValueError("now must be YYYY-MM-DDTHH:MM:SSZ")
    facts = facts if isinstance(facts, dict) else {}

    req = validate_request(request)
    if not req.ok:
        add(BLOCKED, "invalid_request", "request", ",".join(req.codes))
        return _result(reasons, checked)
    r = req.request
    checked.append("request")

    def block(name: str) -> Optional[dict]:
        """The fact block if it was actually read; otherwise record UNKNOWN and return None."""
        b = facts.get(name)
        status = b.get("status") if isinstance(b, dict) else "missing"
        if status != "ok":
            add(UNKNOWN, "fact_" + (status if status in ("forbidden", "missing", "error") else "error"), name)
            return None
        checked.append(name)
        return b

    issue = block("issue")
    if issue is not None:
        owner = str(issue.get("owner") or "").strip().lower()
        if not owner:
            add(UNKNOWN, "owner_unknown", "issue")
        elif owner != r["owner_lane"]:
            add(BLOCKED, "owner_mismatch", "issue", owner)
        if issue.get("state") == "closed":
            add(BLOCKED, "issue_closed", "issue")

    spec = block("spec")
    if spec is not None and spec.get("approved") is not True:
        add(NEEDS_OWNER, "spec_not_approved", "spec")

    if r["depends"]:
        deps = block("depends")
        if deps is not None:
            items = deps.get("items") if isinstance(deps.get("items"), dict) else {}
            for d in r["depends"]:
                state = items.get(str(d))
                if state == "closed":
                    continue
                if state == "open":
                    add(BLOCKED, "dependency_open", "depends", "#%d" % d)
                else:
                    add(UNKNOWN, "dependency_unknown", "depends", "#%d" % d)

    gates = block("gates")
    if gates is not None:
        approval = gates.get("owner_approval")
        if approval in ("pending", "denied"):
            add(NEEDS_OWNER, "owner_approval_" + approval, "gates")
        elif approval not in ("granted", "not_required"):
            add(UNKNOWN, "owner_approval_unknown", "gates")

    prs = block("active_prs")
    if prs is not None:
        for pr in prs.get("prs") or []:
            hits = _overlaps(r["files_scope"], (pr or {}).get("files") or [])
            if hits:
                add(BLOCKED, "file_conflict", "active_prs", "#%s: %s" % ((pr or {}).get("number"), ", ".join(hits)))

    claim = block("claim")
    if claim is not None:
        holder = claim.get("run_id")
        if holder:
            expires = _stamp(claim.get("lease_expires_at"))
            if expires is None:
                add(UNKNOWN, "claim_lease_unknown", "claim", str(holder))
            elif expires <= clock:
                add(UNKNOWN, "stale_claim", "claim", str(holder))       # maybe still running: never assume free
            elif holder != r["run_id"]:
                add(BLOCKED, "already_claimed", "claim", str(holder))
        elif r["run_id"]:
            add(BLOCKED, "run_id_not_claimed", "claim", r["run_id"])      # a run id with no live lease is not ours

    runtime = block("runtime")
    if runtime is not None:
        if runtime.get("subscription_available") is False:
            add(BLOCKED, "no_subscription", "runtime")
        elif runtime.get("subscription_available") is not True:
            add(UNKNOWN, "subscription_unknown", "runtime")
        if runtime.get("worker_online") is False:
            add(BLOCKED, "worker_offline", "runtime")
        elif runtime.get("worker_online") is not True:
            add(UNKNOWN, "worker_unknown", "runtime")

    cost = block("cost")
    if cost is not None:
        est = cost.get("estimated_usd")
        if isinstance(est, bool) or not isinstance(est, (int, float)):
            add(UNKNOWN, "cost_unknown", "cost")
        elif est > r["budget_cap_usd"]:
            add(BLOCKED, "unauthorized_spend", "cost", str(est))

    return _result(reasons, checked)


def _result(reasons: list, checked: list) -> dict:
    verdict = max((x["verdict"] for x in reasons), key=_RANK.__getitem__, default=READY)
    return {"verdict": verdict, "reasons": reasons, "checked": checked}
