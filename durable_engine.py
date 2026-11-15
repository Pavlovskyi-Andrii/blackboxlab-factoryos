"""FactoryOS durable execution engine (T-611): DBOS Transact embedded in the FastAPI process.

Each completed workflow step is checkpointed into its own SQLite file on DATA_DIR (``dbos_system.sqlite``; the FactoryOS
``factory.db`` is never touched). After a crash, restart or Render deploy, ``launch()`` resumes every PENDING workflow from
its last completed step, so a finished step does not run again. No DBOS Conductor and no DBOS Cloud: the engine makes no
outbound network calls.

Rules for workflow code (also in CLAUDE.md and AGENTS.md):
- A workflow body is deterministic: no network, database, clock or random calls in it. Put those in ``@DBOS.step``.
- A step can run again after a crash (at-least-once). Every external side effect it makes needs an idempotency key.
- Never start a workflow or call ``DBOS.recv`` from inside a step.
- Give workflows and steps an explicit ``name=``, and register them at import time, before ``launch()``.
- Bump ``APP_VERSION`` only when a workflow's sequence of steps changes. Workflows of an older version are not resumed;
  the module that owns them must cancel them and start a fresh run.
- A SQLite system database serves exactly one process. Set ``DBOS_SYSTEM_DATABASE_URL`` (Postgres) before running more
  than one FactoryOS process.
- Call DBOS from FactoryOS code through ``run_sync``: DBOS's sync API refuses to run on a thread with a running asyncio
  loop, which is where FastAPI runs startup hooks and async endpoints.

Kill switch: ``FACTORY_DBOS_ENABLED=0`` keeps dbos unimported, nothing launches, and every caller uses its legacy path.
"""
from __future__ import annotations

import asyncio
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict

APP_VERSION = "factoryos-durable-v1"
SYSTEM_DB_FILENAME = "dbos_system.sqlite"


def wanted() -> bool:
    return str(os.environ.get("FACTORY_DBOS_ENABLED", "1")).strip().lower() not in ("0", "false", "no", "off")


DBOS: Any = None
SetWorkflowID: Any = None
IMPORT_ERROR = ""
if wanted():
    try:
        from dbos import DBOS, SetWorkflowID
    except Exception as exc:  # e.g. the Python 3.9 EC2 venv or a missing dependency: the legacy path stays active.
        DBOS = None
        SetWorkflowID = None
        IMPORT_ERROR = f"{type(exc).__name__}: {exc}"[:300]

_lock = threading.Lock()
_caller = ThreadPoolExecutor(max_workers=4, thread_name_prefix="dbos-call")
_state: Dict[str, Any] = {"configured": False, "launched": False, "error": "", "system_database": "", "launched_at": 0.0,
                          "pending_at_launch": None}
_status_sections: Dict[str, Callable[[], Dict[str, Any]]] = {}


def log(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False, default=str), flush=True)


def env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except ValueError:
        value = default
    return max(low, min(high, value))


def run_sync(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Run a synchronous DBOS call from any thread.

    DBOS raises RuntimeError for its sync API on a thread whose asyncio loop is running (a FastAPI startup hook, an async
    endpoint). There the call runs on a helper thread and this one waits: a short blocking SQLite call, like the legacy
    edit_jobs writes made from the same places.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return fn(*args, **kwargs)
    return _caller.submit(fn, *args, **kwargs).result()


def launched() -> bool:
    return bool(_state["launched"])


def add_status_section(name: str, section: Callable[[], Dict[str, Any]]) -> None:
    """A durable-workflow module reports its own counters under status()["workflows"][name]."""
    _status_sections[name] = section


def status() -> Dict[str, Any]:
    """Operator summary for /health details. Shows only the database scheme, never the URL."""
    workflows: Dict[str, Any] = {}
    for name, section in sorted(_status_sections.items()):
        try:
            workflows[name] = section()
        except Exception as exc:
            workflows[name] = {"error": f"{type(exc).__name__}: {exc}"[:200]}
    return {
        "engine": "dbos", "enabled": wanted(), "available": DBOS is not None, "launched": launched(),
        "app_version": APP_VERSION, "system_database": _state["system_database"], "error": _state["error"] or IMPORT_ERROR,
        "pending_at_launch": _state["pending_at_launch"], "workflows": workflows,
    }


def launch(data_dir: Any) -> bool:
    """Configure and launch DBOS once per process; PENDING workflows resume in the background. Never raises."""
    with _lock:
        if _state["launched"]:
            return True
        if not wanted():
            _state["error"] = "disabled by FACTORY_DBOS_ENABLED"
            return False
        if DBOS is None:
            _state["error"] = IMPORT_ERROR or "dbos is not installed"
            return False
        try:
            url = os.environ.get("DBOS_SYSTEM_DATABASE_URL", "").strip()
            if not url:
                folder = Path(data_dir)
                folder.mkdir(parents=True, exist_ok=True)  # SQLite cannot create a missing parent directory.
                url = f"sqlite:///{folder / SYSTEM_DB_FILENAME}"
            if not _state["configured"]:
                DBOS(config={
                    "name": "factoryos", "system_database_url": url, "application_version": APP_VERSION,
                    "executor_id": "local", "log_level": os.environ.get("FACTORY_DBOS_LOG_LEVEL", "WARNING"),
                })
                _state["configured"] = True
            run_sync(DBOS.launch)
            _state.update(launched=True, error="", system_database=url.split(":", 1)[0], launched_at=time.time())
        except Exception as exc:
            _state["error"] = f"{type(exc).__name__}: {exc}"[:500]
            log("DBOS_LAUNCH_FAILED", error=_state["error"])
            return False
    try:  # Recovery re-enqueues each interrupted workflow (ENQUEUED) before running it again (PENDING): count both.
        pending = run_sync(DBOS.list_workflows, status=["PENDING", "ENQUEUED"], app_version=APP_VERSION,
                           load_input=False, load_output=False)
        _state["pending_at_launch"] = len(pending)
    except Exception:
        pending = []
    log("DBOS_LAUNCHED", app_version=APP_VERSION, system_database=_state["system_database"],
        resuming_workflows=len(pending))
    return True


def shutdown() -> None:
    """Stop without waiting: a workflow parked in recv() or mid-step resumes from its checkpoint on the next launch."""
    with _lock:
        if not _state["launched"] or DBOS is None:
            return
        _state.update(launched=False, configured=False)  # destroy() drops the instance; a relaunch reconfigures.
        try:
            run_sync(DBOS.destroy, workflow_completion_timeout_sec=0)
        except Exception as exc:
            log("DBOS_SHUTDOWN_ERROR", error=f"{type(exc).__name__}: {exc}"[:300])
