"""AI Media Finisher as one durable DBOS workflow (T-612).

Per edit job, the workflow ``media-finisher:<edit_job_id>:<generation>`` runs:

    submit → [wait for the worker callback, at most poll_seconds → poll the worker → resubmit if the worker lost the job]*

until the edit job is ready, failed or deleted. Every step is checkpointed by durable_engine, so a deploy or crash in the
middle resumes from the last finished step: an accepted submit is never sent again, and a callback that arrived while
FactoryOS was down is replaced by the next poll. Duplicate-safety on top of the checkpoints:
- the workflow ID is deterministic, so a second start for the same edit job re-attaches to the running workflow;
- the submit routine returns early once ``provider_job_id`` is recorded, and the worker treats ``edit_job_id`` as the
  idempotency key of POST /jobs, so a submit step replayed after a crash cannot create a second worker job.

While a workflow owns an edit job, the legacy watchdog skips it. When the engine is off, or a workflow gives up after
``FACTORY_DBOS_FINISHER_MAX_WAIT_SEC`` without a final status, the legacy watchdog and submit thread work as before.
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

import durable_engine as engine
from durable_engine import DBOS, SetWorkflowID

WORKFLOW_PREFIX = "media-finisher:"
CALLBACK_TOPIC = "media_finisher_callback"
STATE_EVENT = "state"
TERMINAL_STATUSES = ("ready", "failed", "missing")
ACTIVE_WORKFLOW_STATUSES = ("PENDING", "ENQUEUED")

_hooks: Dict[str, Callable[[str], Dict[str, Any]]] = {}
_start_lock = threading.Lock()
_counters = {"workflows_started": 0, "callbacks_delivered": 0}


def poll_seconds() -> float:
    """How long the workflow waits for the worker callback before it polls the worker itself."""
    return engine.env_number("FACTORY_DBOS_FINISHER_POLL_SEC", 30.0, 1.0, 600.0)


def max_wait_seconds() -> float:
    """Without a final status after this long, the workflow hands the edit job back to the legacy watchdog."""
    return engine.env_number("FACTORY_DBOS_FINISHER_MAX_WAIT_SEC", 6 * 3600.0, 1.0, 7 * 24 * 3600.0)


def bind(submit: Callable[[str], Dict[str, Any]], poll: Callable[[str], Dict[str, Any]]) -> None:
    """app.py binds its routines at import time, before durable_engine.launch() can resume a workflow.

    Both return ``{"status": <edit_jobs status or "missing">, "needs_submit": bool}``; needs_submit means the worker has
    no job for this edit job, so the workflow submits again.
    """
    _hooks["submit"] = submit
    _hooks["poll"] = poll


def _call_hook(name: str, edit_job_id: str) -> Dict[str, Any]:
    hook = _hooks.get(name)
    if hook is None:
        return {"status": "unbound", "error": f"media finisher {name} hook is not bound"}
    try:
        result = hook(edit_job_id)
    except Exception as exc:  # A transient error must not end the workflow: it waits and polls again.
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
    return dict(result) if isinstance(result, dict) else {"status": str(result)}


if DBOS is not None:
    @DBOS.step(name="factoryos.media_finisher.submit")
    def _submit_step(edit_job_id: str) -> Dict[str, Any]:
        return _call_hook("submit", edit_job_id)

    @DBOS.step(name="factoryos.media_finisher.poll")
    def _poll_step(edit_job_id: str) -> Dict[str, Any]:
        return _call_hook("poll", edit_job_id)

    @DBOS.workflow(name="factoryos.media_finisher")
    def media_finisher_workflow(edit_job_id: str, wait_seconds: float, rounds: int) -> Dict[str, Any]:
        # wait_seconds and rounds are workflow inputs, so a replay after a restart keeps the same loop bounds.
        state = _submit_step(edit_job_id)
        DBOS.set_event(STATE_EVENT, state)
        for _ in range(int(rounds)):
            if state.get("status") in TERMINAL_STATUSES:
                break
            DBOS.recv(CALLBACK_TOPIC, timeout_seconds=float(wait_seconds))
            state = _poll_step(edit_job_id)
            if state.get("needs_submit"):
                state = _submit_step(edit_job_id)
            DBOS.set_event(STATE_EVENT, state)
        if state.get("status") not in TERMINAL_STATUSES:
            state = dict(state, released=True)
            DBOS.set_event(STATE_EVENT, state)
        return state
else:
    media_finisher_workflow = None


def _workflows(edit_job_id: str) -> List[Any]:
    return list(DBOS.list_workflows(workflow_id_prefix=f"{WORKFLOW_PREFIX}{edit_job_id}:",
                                    load_input=False, load_output=False))


def _generation(workflow_id: str) -> int:
    try:
        return int(str(workflow_id).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return -1


def _active_workflow_id(rows: List[Any]) -> Optional[str]:
    active = [row for row in rows if row.status in ACTIVE_WORKFLOW_STATUSES and row.app_version == engine.APP_VERSION]
    return max(active, key=lambda row: _generation(row.workflow_id)).workflow_id if active else None


def active(edit_job_id: str) -> bool:
    """True while a current-version workflow owns this edit job; the legacy watchdog must then leave it alone."""
    if not engine.launched() or not edit_job_id:
        return False
    try:
        return engine.run_sync(lambda: _active_workflow_id(_workflows(edit_job_id)) is not None)
    except Exception:
        return False


def start(edit_job_id: str) -> Tuple[Optional[str], bool]:
    """Start the workflow for an edit job, or re-attach to the one already running. Returns (workflow_id, created).

    (None, False) means the engine is not launched and the caller must use its legacy path. A new generation starts only
    when no current-version workflow is active, e.g. after an owner repair moved a failed edit job back to queued.
    Safe from any thread, including a FastAPI startup hook or async endpoint (see durable_engine.run_sync).
    """
    if not engine.launched() or not edit_job_id or media_finisher_workflow is None:
        return None, False
    return engine.run_sync(_start, edit_job_id)


def _start(edit_job_id: str) -> Tuple[Optional[str], bool]:
    with _start_lock:
        rows = _workflows(edit_job_id)
        existing = _active_workflow_id(rows)
        if existing:
            return existing, False
        for row in rows:  # An older-version run is never resumed by this process: cancel it so it cannot race later.
            if row.status in ACTIVE_WORKFLOW_STATUSES and row.app_version != engine.APP_VERSION:
                try:
                    DBOS.cancel_workflow(row.workflow_id)
                except Exception as exc:
                    engine.log("DBOS_MEDIA_FINISHER_CANCEL_ERROR", workflow_id=row.workflow_id, error=str(exc)[:200])
        workflow_id = f"{WORKFLOW_PREFIX}{edit_job_id}:{max([_generation(row.workflow_id) for row in rows] + [-1]) + 1}"
        wait = poll_seconds()
        rounds = max(1, int(max_wait_seconds() // wait))
        with SetWorkflowID(workflow_id):
            DBOS.start_workflow(media_finisher_workflow, edit_job_id, wait, rounds)
        _counters["workflows_started"] += 1
    engine.log("DBOS_MEDIA_FINISHER_STARTED", edit_job_id=edit_job_id, workflow_id=workflow_id)
    return workflow_id, True


def notify(edit_job_id: str, payload: Optional[Dict[str, Any]] = None) -> bool:
    """Wake the waiting workflow after a worker callback. An extra wake-up costs one extra poll, nothing more."""
    if not engine.launched() or not edit_job_id:
        return False
    try:
        delivered = engine.run_sync(_send, edit_job_id, dict(payload or {}))
    except Exception as exc:
        engine.log("DBOS_MEDIA_FINISHER_NOTIFY_ERROR", edit_job_id=edit_job_id, error=f"{type(exc).__name__}: {exc}"[:200])
        return False
    if delivered:
        _counters["callbacks_delivered"] += 1
    return delivered


def _send(edit_job_id: str, payload: Dict[str, Any]) -> bool:
    workflow_id = _active_workflow_id(_workflows(edit_job_id))
    if not workflow_id:
        return False
    DBOS.send(workflow_id, payload, topic=CALLBACK_TOPIC)
    return True


def latest_state(edit_job_id: str) -> Optional[Dict[str, Any]]:
    """The state last published by the newest workflow generation of this edit job (tests and diagnostics)."""
    if not engine.launched() or not edit_job_id:
        return None
    return engine.run_sync(_latest_state, edit_job_id)


def _latest_state(edit_job_id: str) -> Optional[Dict[str, Any]]:
    rows = _workflows(edit_job_id)
    if not rows:
        return None
    newest = max(rows, key=lambda row: _generation(row.workflow_id)).workflow_id
    return DBOS.get_event(newest, STATE_EVENT, timeout_seconds=0.1)


def status() -> Dict[str, Any]:
    return {**_counters, "poll_seconds": poll_seconds(), "max_wait_seconds": max_wait_seconds()}


engine.add_status_section("media_finisher", status)
