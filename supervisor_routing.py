"""T-588: Supervisor routing policy.

Supervisor is a routing role, not a fixed model. ``route_task`` picks the operator for one task from, in order:

1. ``[HUMAN]`` tasks: never routed (``blocked``), whatever is assigned.
2. Explicit owner assignment: the task's ``Owner:`` lane, then the owner's T-580 role assignment. Explicit wins
   over Auto. If the assigned operator is not online the task ``waits`` for it. It is never silently handed to
   someone else, so two agents never build the same task.
3. Bounded Auto policy: the role's fixed preference order, limited to operators that are both eligible for the
   role and positively online. Offline, stale, unconfigured and unverified operators are skipped. No candidate
   means ``waiting``, never a guess.

A route is a decision only. It executes nothing, calls no provider, and grants every operator the same
non-privileges: no publishing, no production deploy, no main merge, no paid calls. Selection never widens
privileges, and human publish approval stays mandatory.
"""
from __future__ import annotations

from typing import Iterable, Optional

OPERATORS = ("claude", "gemini", "chatgpt")
EXPLICIT_NONE = ("", "any", "auto")
# Bounded Auto preference per role: at most these operators, in this order. Engineering follows the 2026-10-30
# lane policy (Claude coordinates; ChatGPT has no coding runner). Content roles keep today's pipeline provider first.
AUTO_POLICY = {
    "engineer": ("claude", "gemini"),
    "supervisor": ("claude", "gemini"),
    "scout": ("chatgpt", "claude", "gemini"),
    "researcher": ("chatgpt", "claude", "gemini"),
    "scriptwriter": ("chatgpt", "claude", "gemini"),
    "reviewer": ("chatgpt", "claude", "gemini"),
    "qa": ("chatgpt", "claude", "gemini"),
}
AUTO_MAX_CANDIDATES = 3
# Identical for every operator; routing can never grant more.
PRIVILEGES = {"publish": False, "production_deploy": False, "merge_main": False, "paid_provider_calls": False,
              "requires_human_publish_approval": True}
STATES = ("routed", "waiting", "blocked", "done")


def operator_availability(lanes: Iterable[dict] = (), operators: Iterable[dict] = ()) -> dict:
    """operator -> True only when positively online: a fresh T-585 lane or a T-580 status with ``online is True``.

    Stale, offline, unconfigured and unverified (``online: None``) all count as not available.
    """
    available = {op: False for op in OPERATORS}
    for lane in lanes or []:
        if isinstance(lane, dict) and lane.get("operator_id") in available and lane.get("availability") == "online":
            available[lane["operator_id"]] = True
    for item in operators or []:
        if isinstance(item, dict) and item.get("id") in available and item.get("online") is True:
            available[item["id"]] = True
    return available


def _route(task_id: str, role: str, state: str, operator: Optional[str], source: str, reason: str,
           considered: list) -> dict:
    return {"task_id": task_id, "role": role, "state": state, "operator": operator, "source": source,
            "reason": reason, "considered": considered, "privileges": dict(PRIVILEGES), "executes": False}


def route_task(task: dict, *, role: str = "engineer", role_assignments: Optional[dict] = None,
               availability: Optional[dict] = None, eligible: Optional[Iterable[str]] = None) -> dict:
    """Route one task. ``task`` uses the roadmap parser shape (``id``, ``human``, ``done``, ``owner``)."""
    task_id = str(task.get("id") or "")[:80]
    availability = availability or {}
    role_assignments = role_assignments or {}
    eligible = set(eligible) if eligible is not None else set(AUTO_POLICY.get(role, ()))
    if task.get("done"):
        return _route(task_id, role, "done", None, "roadmap", "task_done", [])
    if task.get("human"):
        return _route(task_id, role, "blocked", None, "roadmap", "human_task", [])

    owner = str(task.get("owner") or "").strip().lower()
    explicit, source = None, ""
    if owner not in EXPLICIT_NONE:
        explicit, source = owner, "task_owner"
    elif str(role_assignments.get(role) or "") not in EXPLICIT_NONE:
        explicit, source = str(role_assignments[role]).lower(), "role_assignment"
    if explicit:
        if explicit not in OPERATORS:
            return _route(task_id, role, "blocked", None, source, "unknown_operator", [explicit])
        if availability.get(explicit) is True:
            return _route(task_id, role, "routed", explicit, source, "explicit_assignment", [explicit])
        return _route(task_id, role, "waiting", explicit, source, "assigned_operator_offline", [explicit])

    candidates = [op for op in AUTO_POLICY.get(role, ()) if op in eligible][:AUTO_MAX_CANDIDATES]
    for op in candidates:
        if availability.get(op) is True:
            return _route(task_id, role, "routed", op, "auto", "auto_policy", candidates)
    return _route(task_id, role, "waiting", None, "auto", "no_online_operator" if candidates else "no_eligible_operator",
                  candidates)


def route_tasks(tasks: Iterable[dict], **kwargs) -> list:
    return [route_task(t, **kwargs) for t in tasks if isinstance(t, dict)]
