"""The content pipeline run, from the job's current stage to the human review gate, as a durable DBOS workflow (T-613).

Stage 2 of the DBOS plan. One workflow per run of a job, ``content-run:<job_id>:<generation>``, walks the stages that
``run_until_review`` walks, with one checkpointed step per unit of paid work:

    for each stage: enter stage → one step per agent (the script stage: variant pipeline, content package) → quality gate
    then: review gate (status waiting_approval)

After a crash, restart or Render deploy the run resumes by itself from the first unfinished step: a finished agent, and
the provider call it paid for, never runs again. A step interrupted mid-flight is handled by app.py through
``durable_engine.step_attempt()``: a demo agent simply runs again; a live agent fails the run with an uncertain-spend
incident (Error Center → confirm → manual retry) instead of paying for a second call, the existing provider policy.

The run ends at the review gate exactly like run_until_review: nothing is approved or published by this workflow.
The plan (stages and their agents) is a workflow input, so a deploy that edits AGENT_MAP cannot change a run in flight.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

import durable_engine as engine
from durable_engine import DBOS

WORKFLOW_PREFIX = "content-run:"

_hooks: Dict[str, Callable[..., Dict[str, Any]]] = {}
_counters = {"runs_started": 0}


def bind(**hooks: Callable[..., Dict[str, Any]]) -> None:
    """app.py binds enter_stage, agent, script, gate, review and failed at import time, before the engine launches.

    A hook raises to fail the run; its error is checkpointed, so a replay after a restart takes the same failure path.
    """
    _hooks.update(hooks)


def _hook(name: str, *args: Any) -> Dict[str, Any]:
    hook = _hooks.get(name)
    if hook is None:
        raise RuntimeError(f"content pipeline hook {name} is not bound")
    try:
        result = hook(*args)
    except Exception as exc:  # DBOS pickles a step's error into its checkpoint: keep it a plain, picklable RuntimeError
        raise RuntimeError(str(exc) or type(exc).__name__) from None
    return dict(result) if isinstance(result, dict) else {"result": str(result)}


if DBOS is not None:
    @DBOS.step(name="factoryos.content.enter_stage")
    def _enter_stage_step(job_id: str, index: int) -> Dict[str, Any]:
        return _hook("enter_stage", job_id, index)

    @DBOS.step(name="factoryos.content.agent")
    def _agent_step(job_id: str, stage: str, agent: str, started_at: str) -> Dict[str, Any]:
        return _hook("agent", job_id, stage, agent, started_at)

    @DBOS.step(name="factoryos.content.script")
    def _script_step(job_id: str, part: str, started_at: str) -> Dict[str, Any]:
        return _hook("script", job_id, part, started_at)

    @DBOS.step(name="factoryos.content.gate")
    def _gate_step(job_id: str, stage: str) -> Dict[str, Any]:
        return _hook("gate", job_id, stage)

    @DBOS.step(name="factoryos.content.review")
    def _review_step(job_id: str) -> Dict[str, Any]:
        return _hook("review", job_id)

    @DBOS.step(name="factoryos.content.failed")
    def _failed_step(job_id: str, error: str) -> Dict[str, Any]:
        return _hook("failed", job_id, error)

    @DBOS.workflow(name="factoryos.content_run")
    def content_run_workflow(job_id: str, plan: List[Dict[str, Any]], started_at: str) -> Dict[str, Any]:
        try:
            for entry in plan:
                stage = str(entry["stage"])
                _enter_stage_step(job_id, int(entry["index"]))
                if stage == "script":
                    _script_step(job_id, "variants", started_at)
                    _script_step(job_id, "package", started_at)
                else:
                    for agent in entry.get("agents") or []:
                        _agent_step(job_id, stage, str(agent), started_at)
                _gate_step(job_id, stage)
            _review_step(job_id)
            return {"status": "waiting_approval"}
        except Exception as exc:  # a step's checkpointed error; cancellation is a BaseException and is not caught here
            error = str(exc)[:1000]
            _failed_step(job_id, error)
            return {"status": "failed", "error": error}
else:
    content_run_workflow = None


def job_prefix(job_id: str) -> str:
    return f"{WORKFLOW_PREFIX}{job_id}:"


def start(job_id: str, plan: List[Dict[str, Any]], started_at: str) -> Tuple[Optional[str], bool]:
    """Start a durable run for the job, or re-attach to the one already running. (None, False) → use the legacy path."""
    if not job_id or not plan:
        return None, False
    workflow_id, created = engine.start_generation(job_prefix(job_id), content_run_workflow, job_id, plan, started_at)
    if created:
        _counters["runs_started"] += 1
        engine.log("DBOS_CONTENT_RUN_STARTED", job_id=job_id, workflow_id=workflow_id,
                   stages=[str(x.get("stage")) for x in plan])
    return workflow_id, created


def active(job_id: str) -> bool:
    """True while a current-version durable run owns this job (supervisor auto-heal and new runs must leave it alone)."""
    return bool(job_id) and engine.active_generation(job_prefix(job_id)) is not None


def active_job_ids() -> List[str]:
    """Jobs with a durable run in flight, e.g. resumed at startup before their next step has executed."""
    try:
        ids = engine.active_generations(WORKFLOW_PREFIX)
    except Exception:
        return []
    return sorted({workflow_id[len(WORKFLOW_PREFIX):].rsplit(":", 1)[0] for workflow_id in ids})


def status() -> Dict[str, Any]:
    return dict(_counters)


engine.add_status_section("content_run", status)
