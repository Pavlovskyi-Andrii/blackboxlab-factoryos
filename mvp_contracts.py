"""T-631 Product Evolution S2 (#270 §2, epic #186): versioned worker contracts for the 13 logical MVP roles.

A contract says what one logical role may do and what it must hand over: permissions, trigger, input/output schema,
acceptance, Depends, retries, timeout, error state and the audit evidence a finished run must carry.

Rules
- Roles are logical, not processes: every role runs on one of the five existing `mvp_cycle.AGENTS` engines (Gemini for
  research/spec, Claude through the EC2 worker for build/QA, Content Factory for promotion). No new runtime, no paid
  service per role.
- No contract may hold an owner-only action (approve, decline, release, verdict, publish, spend, delete feedback) or an
  owner/member action (hand-off, ship, queue a build, open a preview). Those stay in `mvp_factory` / `mvp_evolution`.
- A role whose output needs the owner's yes (`owner_gate`) blocks every downstream role until that approval is recorded.
- `ContractRun` is a pure state machine for one task (no I/O, no persistence): one active claim, idempotent re-claim
  with the same run_id, a second claim refused, retries up to `retries`, then the contract's error state. A run reaches
  `done` only with valid output and valid audit evidence; failed evidence is a failed attempt, never a success.
- Changing a contract's fields means bumping its `version`; `SCHEMA` changes only when the contract shape changes.
"""
from __future__ import annotations

import re
import time
from typing import Any, Callable, Iterable, Optional

from mvp_cycle import AGENTS
from mvp_factory import EVIDENCE_RE

SCHEMA = "mvp-worker-contract/1"
OWNER_ONLY_ACTIONS = ("approve_proposal", "decline_proposal", "release_version", "set_verdict", "publish", "spend",
                      "delete_feedback")
MEMBER_ACTIONS = ("handoff", "mark_shipped", "queue_build", "open_preview")
AGENT_ACTIONS = ("read_project", "read_feedback", "web_research", "write_artifact", "record_note", "advance_research_spec",
                 "record_feedback", "propose", "open_branch", "open_pr", "run_tests", "review_pr", "draft_content")
TRIGGERS = ("owner_request", "stage_entered", "upstream_done", "approved_proposal", "relay_ticket", "feedback_recorded")
TYPES = ("str", "int", "bool", "list", "dict", "url")
EVIDENCE_KINDS = ("sources", "artifact", "pr", "actions_run", "relay_run", "feedback_ids")
ERROR_STATES = ("blocked", "failed", "needs_owner")
RUN_STATES = ("queued", "claimed", "running", "done") + ERROR_STATES
ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,30}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{4,80}$")
HTTPS_RE = re.compile(r"^https://[^\s<>\"']{4,500}$")
PR_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(pull|commit)/[A-Za-z0-9]+$")
RUN_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/actions/runs/\d+$")
MAX_RETRIES = 5
TIMEOUT_RANGE = (60, 86400)
CYCLE_AGENTS = {a["id"]: a for a in AGENTS}


class ContractError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _f(type_: str, required: bool = True) -> dict[str, Any]:
    return {"type": type_, "required": required}


def _c(rid: str, label: str, agent: str, *, permissions: tuple, trigger: tuple, inputs: dict, outputs: dict,
       acceptance: tuple, depends: tuple = (), evidence: tuple, retries: int = 2, timeout_s: int = 3600,
       error_state: str = "blocked", owner_gate: bool = False, loop_from: tuple = (), module: str = "mvp_cycle",
       version: int = 1) -> dict[str, Any]:
    return {"schema": SCHEMA, "id": rid, "label": label, "version": version, "cycle_agent": agent,
            "engine": CYCLE_AGENTS[agent]["engine"] if agent in CYCLE_AGENTS else "", "module": module,
            "permissions": list(permissions), "trigger": list(trigger), "input_schema": inputs, "output_schema": outputs,
            "acceptance": list(acceptance), "depends": list(depends), "loop_from": list(loop_from), "retries": retries,
            "timeout_s": timeout_s, "error_state": error_state, "owner_gate": owner_gate,
            "audit_evidence": list(evidence)}


# The 13 logical roles, in pipeline order (V1: idea → validated; V2: feedback → proposal → owner → build again).
CONTRACTS: list[dict[str, Any]] = [
    _c("idea_research", "Idea / Research", "researcher",
       permissions=("read_project", "web_research", "write_artifact", "record_note", "advance_research_spec"),
       trigger=("owner_request", "stage_entered"),
       inputs={"project_id": _f("str"), "brief": _f("str")},
       outputs={"problem": _f("str"), "audience": _f("str"), "sources": _f("list")},
       acceptance=("names one problem and one audience", "every claim cites a dated public source"),
       evidence=("sources", "artifact"), timeout_s=1800),
    _c("market_analyst", "Market / Competitor Analyst", "researcher",
       permissions=("read_project", "web_research", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "problem": _f("str"), "audience": _f("str")},
       outputs={"competitors": _f("list"), "gap": _f("str"), "sources": _f("list")},
       acceptance=("lists real competitors with links", "states the gap without invented numbers"),
       depends=("idea_research",), evidence=("sources", "artifact"), timeout_s=1800),
    _c("spec_writer", "Spec Writer", "spec",
       permissions=("read_project", "write_artifact", "record_note", "advance_research_spec"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "problem": _f("str"), "gap": _f("str")},
       outputs={"spec": _f("str"), "done_when": _f("list")},
       acceptance=("every feature has a «done when» check", "no build starts before the owner accepts the spec"),
       depends=("idea_research", "market_analyst"), evidence=("artifact",), owner_gate=True),
    _c("ux_designer", "UX / Design", "spec",
       permissions=("read_project", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "spec": _f("str")},
       outputs={"screens": _f("list"), "flows": _f("list")},
       acceptance=("covers each spec feature with a screen or flow", "EN/UK/RU copy keys listed"),
       depends=("spec_writer",), evidence=("artifact",)),
    _c("architect", "Architect", "builder",
       permissions=("read_project", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "spec": _f("str")},
       outputs={"file_map": _f("list"), "risks": _f("list")},
       acceptance=("reuses existing modules before adding new ones", "names every new secret or paid service (none by default)"),
       depends=("spec_writer",), evidence=("artifact",)),
    _c("ui_builder", "UI / Builder Worker", "builder",
       permissions=("read_project", "open_branch", "open_pr", "run_tests", "write_artifact", "record_note"),
       trigger=("upstream_done", "approved_proposal", "relay_ticket"),
       inputs={"project_id": _f("str"), "screens": _f("list"), "acceptance_criteria": _f("list")},
       outputs={"pr_url": _f("url"), "tests": _f("list")},
       acceptance=("PR from a branch, never main", "CI green on the PR head", "acceptance criteria covered by tests"),
       depends=("ux_designer", "architect"), loop_from=("product_manager",), evidence=("pr", "relay_run"),
       timeout_s=14400, module="mvp_evolution.handoff_status"),
    _c("backend_builder", "Backend / Builder Worker", "builder",
       permissions=("read_project", "open_branch", "open_pr", "run_tests", "write_artifact", "record_note"),
       trigger=("upstream_done", "approved_proposal", "relay_ticket"),
       inputs={"project_id": _f("str"), "file_map": _f("list"), "acceptance_criteria": _f("list")},
       outputs={"pr_url": _f("url"), "tests": _f("list")},
       acceptance=("PR from a branch, never main", "CI green on the PR head", "no paid call enabled by default"),
       depends=("architect",), loop_from=("product_manager",), evidence=("pr", "relay_run"), timeout_s=14400,
       module="mvp_evolution.handoff_status"),
    _c("qa_tester", "QA / Test", "qa",
       permissions=("read_project", "run_tests", "review_pr", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "pr_url": _f("url")},
       outputs={"verdict": _f("str"), "failures": _f("list")},
       acceptance=("runs the spec's «done when» checks", "reports failures with their output"),
       depends=("ui_builder", "backend_builder"), evidence=("actions_run",), error_state="failed"),
    _c("security_reviewer", "Security / Privacy Reviewer", "qa",
       permissions=("read_project", "review_pr", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "pr_url": _f("url")},
       outputs={"verdict": _f("str"), "findings": _f("list")},
       acceptance=("no secret in code or logs", "auth on every owner route", "personal data only with consent"),
       depends=("ui_builder", "backend_builder"), evidence=("pr", "artifact"), error_state="failed"),
    _c("release_manager", "Release / Preview", "qa",
       permissions=("read_project", "review_pr", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "pr_url": _f("url"), "qa_verdict": _f("str")},
       outputs={"preview_url": _f("url"), "notes": _f("str")},
       acceptance=("preview reachable through the CI-gated flow only", "owner decides validated/rejected"),
       depends=("qa_tester", "security_reviewer"), evidence=("actions_run", "artifact"), owner_gate=True,
       error_state="needs_owner"),
    _c("promoter", "Promoter", "promoter",
       permissions=("read_project", "draft_content", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "preview_url": _f("url")},
       outputs={"drafts": _f("list"), "channels": _f("list")},
       acceptance=("drafts only; publishing needs the owner's explicit yes", "no outreach sent by an agent"),
       depends=("release_manager",), evidence=("artifact",), owner_gate=True, error_state="needs_owner",
       module="content_factory"),
    _c("feedback_synthesis", "Feedback / Discovery Synthesis", "researcher",
       permissions=("read_project", "read_feedback", "record_feedback", "write_artifact", "record_note"),
       trigger=("feedback_recorded",),
       inputs={"project_id": _f("str"), "version": _f("str")},
       outputs={"themes": _f("list"), "feedback_ids": _f("list")},
       acceptance=("consented records only", "synthetic data never counted", "contrary evidence shown with confidence"),
       depends=("release_manager",), evidence=("feedback_ids",), timeout_s=600, module="mvp_evolution.synthesize"),
    _c("product_manager", "Product Manager", "spec",
       permissions=("read_project", "read_feedback", "propose", "write_artifact", "record_note"),
       trigger=("upstream_done",),
       inputs={"project_id": _f("str"), "themes": _f("list"), "feedback_ids": _f("list")},
       outputs={"proposal_id": _f("str"), "target_version": _f("str"), "acceptance_test": _f("str"),
                "feedback_ids": _f("list")},
       acceptance=("cites feedback ids", "carries an acceptance test", "only the owner approves or declines"),
       depends=("feedback_synthesis",), evidence=("feedback_ids", "artifact"), owner_gate=True,
       error_state="needs_owner", module="mvp_evolution.EvolutionStore.propose"),
]
BY_ID = {c["id"]: c for c in CONTRACTS}


def validate_contract(c: dict[str, Any]) -> list[str]:
    """Shape errors of one contract (empty list = valid)."""
    errs: list[str] = []
    if not isinstance(c, dict):
        return ["not_a_dict"]
    if c.get("schema") != SCHEMA:
        errs.append("bad_schema")
    if not ID_RE.match(str(c.get("id") or "")):
        errs.append("bad_id")
    if not str(c.get("label") or "").strip():
        errs.append("missing_label")
    if not isinstance(c.get("version"), int) or isinstance(c.get("version"), bool) or c["version"] < 1:
        errs.append("bad_version")
    agent = CYCLE_AGENTS.get(c.get("cycle_agent"))
    if not agent:
        errs.append("unknown_cycle_agent")
    elif c.get("engine") != agent["engine"]:
        errs.append("engine_mismatch")
    perms = c.get("permissions")
    if not isinstance(perms, list) or not perms:
        errs.append("missing_permissions")
    else:
        if any(p in OWNER_ONLY_ACTIONS for p in perms):
            errs.append("owner_only_action")
        if any(p in MEMBER_ACTIONS for p in perms):
            errs.append("member_action")
        if any(p not in AGENT_ACTIONS + OWNER_ONLY_ACTIONS + MEMBER_ACTIONS for p in perms):
            errs.append("unknown_permission")
    trig = c.get("trigger")
    if not isinstance(trig, list) or not trig or any(t not in TRIGGERS for t in trig):
        errs.append("bad_trigger")
    for key in ("input_schema", "output_schema"):
        sch = c.get(key)
        if not isinstance(sch, dict) or not sch:
            errs.append(f"missing_{key}")
            continue
        for name, spec in sch.items():
            if not ID_RE.match(str(name)) or not isinstance(spec, dict) or spec.get("type") not in TYPES \
                    or not isinstance(spec.get("required"), bool):
                errs.append(f"bad_{key}_field")
                break
    acc = c.get("acceptance")
    if not isinstance(acc, list) or not acc or not all(isinstance(a, str) and a.strip() for a in acc):
        errs.append("missing_acceptance")
    for key in ("depends", "loop_from"):
        if not isinstance(c.get(key), list) or not all(isinstance(d, str) for d in c[key]):
            errs.append(f"bad_{key}")
    r = c.get("retries")
    if not isinstance(r, int) or isinstance(r, bool) or not 0 <= r <= MAX_RETRIES:
        errs.append("bad_retries")
    t = c.get("timeout_s")
    if not isinstance(t, int) or isinstance(t, bool) or not TIMEOUT_RANGE[0] <= t <= TIMEOUT_RANGE[1]:
        errs.append("bad_timeout")
    if c.get("error_state") not in ERROR_STATES:
        errs.append("bad_error_state")
    if not isinstance(c.get("owner_gate"), bool):
        errs.append("bad_owner_gate")
    ev = c.get("audit_evidence")
    if not isinstance(ev, list) or not ev or any(e not in EVIDENCE_KINDS for e in ev):
        errs.append("bad_audit_evidence")
    return errs


def validate_registry(contracts: Iterable[dict[str, Any]] = CONTRACTS) -> list[str]:
    """Errors across the set: each contract valid, unique ids, Depends known and acyclic, every engine used is real."""
    contracts = list(contracts)
    errs = [f"{c.get('id') if isinstance(c, dict) else '?'}:{e}" for c in contracts for e in validate_contract(c)]
    ids = [c.get("id") for c in contracts if isinstance(c, dict)]
    if len(ids) != len(set(ids)):
        errs.append("duplicate_id")
    known = set(ids)
    graph = {c["id"]: c.get("depends") or [] for c in contracts if isinstance(c, dict) and "id" in c}
    for c in contracts:
        for d in (c.get("depends") or []) + (c.get("loop_from") or []):
            if d not in known:
                errs.append(f"{c['id']}:unknown_depends:{d}")
            if d == c.get("id"):
                errs.append(f"{c['id']}:self_depends")
    state: dict[str, int] = {}

    def visit(n: str) -> bool:
        if state.get(n) == 1:
            return False
        if state.get(n) == 2:
            return True
        state[n] = 1
        ok = all(visit(d) for d in graph.get(n, []) if d in graph)
        state[n] = 2
        return ok

    if not all(visit(n) for n in graph):
        errs.append("depends_cycle")
    return errs


def contract(role_id: str) -> dict[str, Any]:
    c = BY_ID.get(role_id)
    if c is None:
        raise ContractError("unknown_role", 404)
    return c


def authorize(role_id: str, action: str) -> None:
    """Raise unless the role's contract grants the action. Owner/member actions are never granted to a role."""
    c = contract(role_id)
    if action in OWNER_ONLY_ACTIONS:
        raise ContractError("owner_only", 403)
    if action in MEMBER_ACTIONS:
        raise ContractError("owner_or_member_only", 403)
    if action not in c["permissions"]:
        raise ContractError("not_permitted", 403)


def _type_ok(type_: str, value: Any) -> bool:
    if type_ == "str":
        return isinstance(value, str) and bool(value.strip())
    if type_ == "int":
        return isinstance(value, int) and not isinstance(value, bool)
    if type_ == "bool":
        return isinstance(value, bool)
    if type_ == "list":
        return isinstance(value, list)
    if type_ == "dict":
        return isinstance(value, dict)
    if type_ == "url":
        return isinstance(value, str) and bool(EVIDENCE_RE.match(value) or HTTPS_RE.match(value))
    return False


def validate_payload(schema: dict[str, Any], payload: Any) -> list[str]:
    """Errors of an input/output payload against a contract schema. Unknown fields are refused, not dropped."""
    if not isinstance(payload, dict):
        return ["not_a_dict"]
    errs = [f"unknown_field:{k}" for k in payload if k not in schema]
    for name, spec in schema.items():
        if name not in payload or payload[name] is None:
            if spec["required"]:
                errs.append(f"missing:{name}")
        elif not _type_ok(spec["type"], payload[name]):
            errs.append(f"bad_type:{name}")
    return errs


def check_evidence(role_id: str, evidence: Any, run_id: str = "") -> list[str]:
    """Errors of the audit evidence a finished run hands over. Only the link shape is checked, as in mvp_factory."""
    c = contract(role_id)
    if not isinstance(evidence, dict):
        return ["not_a_dict"]
    errs = []
    for kind in c["audit_evidence"]:
        v = evidence.get(kind)
        if kind == "sources":
            ok = isinstance(v, list) and bool(v) and all(isinstance(u, str) and HTTPS_RE.match(u) for u in v)
        elif kind == "artifact":
            ok = isinstance(v, list) and bool(v) and all(isinstance(u, str) and EVIDENCE_RE.match(u) for u in v)
        elif kind == "pr":
            ok = isinstance(v, str) and bool(PR_RE.match(v))
        elif kind == "actions_run":
            ok = isinstance(v, str) and bool(RUN_RE.match(v))
        elif kind == "relay_run":  # the Relay ticket's run_id must be this run's id (same run that claimed it)
            ok = isinstance(v, str) and bool(RUN_ID_RE.match(v)) and v == run_id
        else:  # feedback_ids
            ok = isinstance(v, list) and bool(v) and all(isinstance(i, str) and i.strip() for i in v)
        if not ok:
            errs.append(f"evidence:{kind}")
    return errs


def ready(role_id: str, done: Iterable[str], approved: Iterable[str], *, iteration: int = 1) -> tuple[bool, str]:
    """Can a run of this role start? Every dependency done and, where the upstream has an owner gate, owner-approved.
    From iteration 2 (V2+) builder roles start from an approved Product Manager proposal (`loop_from`) instead."""
    c = contract(role_id)
    done, approved = set(done), set(approved)
    deps = c["loop_from"] if iteration > 1 and c["loop_from"] else c["depends"]
    for d in deps:
        if d not in done:
            return False, f"waiting:{d}"
        if BY_ID[d]["owner_gate"] and d not in approved:
            return False, f"owner_approval:{d}"
    return True, ""


class ContractRun:
    """One task of one role. Pure and in-memory: the caller (Relay / MVP Builder) owns persistence."""

    def __init__(self, role_id: str, task_id: str, *, clock: Callable[[], float] = time.time):
        self.contract = contract(role_id)
        self.task_id, self.clock = task_id, clock
        self.state, self.worker, self.run_id = "queued", "", ""
        self.attempts, self.started_at = 0, 0.0
        self.used_runs: set[str] = set()
        self.output: Optional[dict[str, Any]] = None
        self.evidence: Optional[dict[str, Any]] = None
        self.error = ""
        self.history: list[dict[str, Any]] = []

    def _log(self, state: str, note: str = "") -> None:
        self.state = state
        self.history.append({"at": self.clock(), "state": state, "worker": self.worker, "run_id": self.run_id,
                             "attempt": self.attempts, "note": note})

    def claim(self, worker: str, run_id: str, *, done: Iterable[str] = (), approved: Iterable[str] = (),
              iteration: int = 1, payload: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Claim the task. Same worker + run_id while active → idempotent; anyone else → duplicate_claim (409)."""
        if not str(worker or "").strip() or not RUN_ID_RE.match(str(run_id or "")):
            raise ContractError("bad_claim")
        if self.state in ("claimed", "running"):
            if worker == self.worker and run_id == self.run_id:
                return self.view()
            raise ContractError("duplicate_claim", 409)
        if self.state == "done":
            raise ContractError("already_done", 409)
        if self.state in ERROR_STATES:
            raise ContractError("terminal", 409)
        if run_id in self.used_runs:
            raise ContractError("stale_run", 409)
        ok, reason = ready(self.contract["id"], done, approved, iteration=iteration)
        if not ok:
            raise ContractError(reason, 409)
        errs = validate_payload(self.contract["input_schema"], payload if payload is not None else {})
        if errs:
            raise ContractError("bad_input:" + ",".join(errs))
        self.worker, self.run_id = worker, run_id
        self.used_runs.add(run_id)
        self.attempts += 1
        self._log("claimed")
        return self.view()

    def start(self, run_id: str) -> dict[str, Any]:
        self._own(run_id, ("claimed",))
        self.started_at = self.clock()
        self._log("running")
        return self.view()

    def finish(self, run_id: str, output: Any, evidence: Any) -> dict[str, Any]:
        """Done only with a valid output and valid audit evidence; anything else is a failed attempt."""
        self._own(run_id, ("running",))
        if self._timed_out():
            return self._fail("timeout")
        errs = validate_payload(self.contract["output_schema"], output) + \
            check_evidence(self.contract["id"], evidence, run_id)
        if errs:
            return self._fail(",".join(errs))
        self.output, self.evidence = output, evidence
        self._log("done")
        return self.view()

    def fail(self, run_id: str, reason: str) -> dict[str, Any]:
        self._own(run_id, ("claimed", "running"))
        return self._fail(str(reason or "worker_failed")[:200])

    def check_timeout(self) -> dict[str, Any]:
        """Called by whoever watches the run (e.g. on a Relay stale check)."""
        if self.state == "running" and self._timed_out():
            return self._fail("timeout")
        return self.view()

    def _own(self, run_id: str, states: tuple) -> None:
        if self.state not in states:
            raise ContractError("bad_state", 409)
        if run_id != self.run_id:
            raise ContractError("not_claim_owner", 409)

    def _timed_out(self) -> bool:
        return self.clock() - self.started_at > self.contract["timeout_s"]

    def _fail(self, reason: str) -> dict[str, Any]:
        self.error = reason
        if self.attempts <= self.contract["retries"]:
            self._log("queued", f"retry after: {reason}")
        else:
            self._log(self.contract["error_state"], reason)
        self.worker, self.run_id = "", ""
        return self.view()

    def view(self) -> dict[str, Any]:
        c = self.contract
        return {"schema": SCHEMA, "role": c["id"], "contract_version": c["version"], "task_id": self.task_id,
                "state": self.state, "worker": self.worker, "run_id": self.run_id, "attempts": self.attempts,
                "max_attempts": c["retries"] + 1, "error": self.error, "output": self.output,
                "evidence": self.evidence, "history": list(self.history)}


def contracts_view() -> dict[str, Any]:
    """JSON-ready summary of all contracts, with the registry check result."""
    return {"schema": SCHEMA, "roles": [dict(c) for c in CONTRACTS], "errors": validate_registry(),
            "note": "Logical roles on the existing mvp_cycle engines; no process or paid service per role."}
