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
- Steps run on DBOS executor threads. FactoryOS coroutines (agents, broadcast) go through ``run_on_main_loop`` so they
  run on the app's own event loop, as before.
- A step whose side effect cannot be repeated blindly (a paid provider call) asks ``step_attempt()`` first: more than 1
  means an earlier start of this very step was interrupted before its result was checkpointed.

Kill switch: ``FACTORY_DBOS_ENABLED=0`` keeps dbos unimported, nothing launches, and every caller uses its legacy path.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

APP_VERSION = "factoryos-durable-v1"
SYSTEM_DB_FILENAME = "dbos_system.sqlite"
STEP_ATTEMPTS_FILENAME = "durable_step_attempts.sqlite"
ACTIVE_WORKFLOW_STATUSES = ("PENDING", "ENQUEUED")


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
_start_lock = threading.Lock()
_state: Dict[str, Any] = {"configured": False, "launched": False, "error": "", "system_database": "", "launched_at": 0.0,
                          "pending_at_launch": None, "loop": None, "data_dir": None}
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


def main_loop() -> Optional[asyncio.AbstractEventLoop]:
    """The app's event loop, captured by launch() when it runs inside a FastAPI startup hook."""
    return _state["loop"]


def run_on_main_loop(coro: Any) -> Any:
    """Run a FactoryOS coroutine on the app's event loop from a DBOS step thread, and wait for its result.

    Without a captured loop (a script or test that launched the engine directly) the coroutine runs on a fresh loop in
    this thread. Calling this on the loop's own thread would deadlock, so that is refused.
    """
    loop = _state["loop"]
    if loop is None or loop.is_closed() or not loop.is_running():
        return asyncio.run(coro)
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is loop:
        coro.close()
        raise RuntimeError("run_on_main_loop() called on the event loop's own thread")
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


def step_attempt() -> int:
    """Call first inside a DBOS step: how many times this step of this workflow has started, across crashes.

    1 is the first start. More means an earlier start was interrupted (a crash, a deploy) before DBOS checkpointed its
    result, so its side effects may or may not have happened. Kept in its own small SQLite file next to the system DB.
    """
    workflow_id, step_id = DBOS.workflow_id, DBOS.step_id
    if not workflow_id or step_id is None:
        raise RuntimeError("step_attempt() must be called inside a DBOS step")
    folder = _state["data_dir"] or Path(".")
    con = sqlite3.connect(str(Path(folder) / STEP_ATTEMPTS_FILENAME), timeout=30)
    try:
        with con:
            con.execute("""CREATE TABLE IF NOT EXISTS step_attempts(workflow_id TEXT NOT NULL, step_id INTEGER NOT NULL,
                           attempts INTEGER NOT NULL, first_started_at REAL, last_started_at REAL,
                           PRIMARY KEY(workflow_id, step_id))""")
            now = time.time()
            con.execute("""INSERT INTO step_attempts VALUES(?,?,1,?,?) ON CONFLICT(workflow_id, step_id)
                           DO UPDATE SET attempts=attempts+1, last_started_at=excluded.last_started_at""",
                        (workflow_id, step_id, now, now))
            return int(con.execute("SELECT attempts FROM step_attempts WHERE workflow_id=? AND step_id=?",
                                   (workflow_id, step_id)).fetchone()[0])
    finally:
        con.close()


def generation_of(workflow_id: str) -> int:
    try:
        return int(str(workflow_id).rsplit(":", 1)[1])
    except (IndexError, ValueError):
        return -1


def _generations(prefix: str) -> List[Any]:
    return list(DBOS.list_workflows(workflow_id_prefix=prefix, load_input=False, load_output=False))


def _active_generation(rows: List[Any]) -> Optional[str]:
    active = [row for row in rows if row.status in ACTIVE_WORKFLOW_STATUSES and row.app_version == APP_VERSION]
    return max(active, key=lambda row: generation_of(row.workflow_id)).workflow_id if active else None


def active_generation(prefix: str, strict: bool = False) -> Optional[str]:
    """The running current-version workflow `<prefix><n>`, if any. Safe from any thread; None when not launched.

    strict=True raises when DBOS cannot answer, so a caller can tell "no run" from "unknown".
    """
    if not launched():
        return None
    try:
        return run_sync(lambda: _active_generation(_generations(prefix)))
    except Exception:
        if strict:
            raise
        return None


def active_generations(prefix: str) -> List[str]:
    """IDs of all running current-version workflows whose ID starts with prefix (e.g. "content-run:")."""
    if not launched():
        return []
    rows = run_sync(_generations, prefix)
    return [row.workflow_id for row in rows
            if row.status in ACTIVE_WORKFLOW_STATUSES and row.app_version == APP_VERSION]


def start_generation(prefix: str, workflow: Callable[..., Any], *args: Any) -> Tuple[Optional[str], bool]:
    """Start workflow as `<prefix><n>` with the next generation n, or re-attach to the one running. Returns (id, created).

    The deterministic ID is the idempotency key: a second start while one runs is a no-op. An older-APP_VERSION run is
    never resumed by this process, so it is cancelled before the new generation starts (one owner per prefix).
    """
    if not launched() or workflow is None:
        return None, False
    return run_sync(_start_generation, prefix, workflow, args)


def _start_generation(prefix: str, workflow: Callable[..., Any], args: Tuple[Any, ...]) -> Tuple[Optional[str], bool]:
    with _start_lock:
        rows = _generations(prefix)
        existing = _active_generation(rows)
        if existing:
            return existing, False
        for row in rows:
            if row.status in ACTIVE_WORKFLOW_STATUSES and row.app_version != APP_VERSION:
                try:
                    DBOS.cancel_workflow(row.workflow_id)
                except Exception as exc:
                    log("DBOS_CANCEL_ERROR", workflow_id=row.workflow_id, error=str(exc)[:200])
        workflow_id = f"{prefix}{max([generation_of(row.workflow_id) for row in rows] + [-1]) + 1}"
        with SetWorkflowID(workflow_id):
            DBOS.start_workflow(workflow, *args)
    return workflow_id, True


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
            _state["loop"] = asyncio.get_running_loop()  # set when launched from a FastAPI startup hook
        except RuntimeError:
            _state["loop"] = None
        try:
            folder = Path(data_dir)
            folder.mkdir(parents=True, exist_ok=True)  # SQLite cannot create a missing parent directory.
            _state["data_dir"] = folder
            url = os.environ.get("DBOS_SYSTEM_DATABASE_URL", "").strip()
            if not url:
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
