"""MVP Factory manager: deterministic, side-effect-free dispatch recommendations.

Never claim or enqueue a worker here. Existing RelayQueue is the sole executor.
"""
import re

ISSUE_RE = re.compile(r"(?:github\.com/[^/]+/[^/]+/issues/|(?:issue|#)\s*#?)(\d+)", re.I)
STAGES = ("idea", "researching", "spec_draft", "spec_review", "build_queued",
          "building", "qa_review", "preview_ready", "owner_review", "validated", "rejected")
NEXT = {"idea": "researching", "researching": "spec_draft",
        "spec_draft": "spec_review", "spec_review": "build_queued",
        "build_queued": "building", "building": "qa_review",
        "qa_review": "preview_ready", "preview_ready": "owner_review"}
ROLE = {"researching": "Product Analyst", "spec_draft": "Spec Writer",
        "spec_review": "MVP Manager", "build_queued": "Claude Builder",
        "building": "Claude Builder", "qa_review": "QA / Security",
        "preview_ready": "Deploy Agent", "owner_review": "Owner"}


def _linked(ticket, issue):
    source = ticket.get("source") or {}
    text = " ".join(str(v) for v in
                    (ticket.get("title", ""), ticket.get("body", ""),
                     ticket.get("source_url", ""), source.get("url", "")))
    return issue in {int(m) for m in ISSUE_RE.findall(text)}


def plan_mvp(issue, stage, tickets, *, spec_approved=False, ci_green=False,
             review_approved=False, owner_deploy_approved=False):
    """Return recommendation with evidence; no network or state mutation."""
    if type(issue) is not int or issue <= 0:
        raise ValueError("invalid issue")
    if stage not in STAGES:
        raise ValueError("invalid stage")
    matches = [t for t in tickets if isinstance(t, dict) and _linked(t, issue)]
    active = [t for t in matches if
              (t.get("execution") or {}).get("state") in
              ("queued", "claimed", "running", "checkpoint", "committed", "pushed")]
    if len(active) > 1:
        return {"issue": issue, "decision": "blocked", "reason": "multiple active Relay executions",
                "ticket_ids": [t.get("id") for t in active]}
    if active:
        return {"issue": issue, "decision": "observe", "reason": "existing Relay execution owns task",
                "ticket_ids": [active[0].get("id")],
                "execution": (active[0].get("execution") or {}).get("state")}
    if stage in ("validated", "rejected", "owner_review"):
        return {"issue": issue, "decision": "hold", "reason": "terminal or owner review stage"}
    next_stage = NEXT[stage]
    gates = {
        "building": (spec_approved, "approved specification required"),
        "preview_ready": (ci_green and review_approved, "green CI and independent review required"),
        "owner_review": (owner_deploy_approved, "owner preview/deploy approval required"),
    }
    if next_stage in gates and not gates[next_stage][0]:
        return {"issue": issue, "decision": "blocked", "reason": gates[next_stage][1]}
    return {"issue": issue, "decision": "recommend", "next_stage": next_stage,
            "role": ROLE.get(next_stage, "MVP Manager"),
            "reason": "manual assignment only; no worker claimed or started"}
