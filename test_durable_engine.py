"""T-611 checks for durable_engine (DBOS Transact embedded in FactoryOS). Run: python test_durable_engine.py

Each scenario runs in a fresh interpreter: DBOS keeps process-global state, and the crash check needs a real SIGKILL.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
CRASH_WORKFLOW_ID = "factoryos-test:crash:0"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def bump(path: Path) -> int:
    count = int(path.read_text() or 0) + 1 if path.exists() else 1
    path.write_text(str(count))
    return count


def child_disabled(data_dir: Path):
    import durable_engine as engine
    require(engine.DBOS is None and "dbos" not in sys.modules, "kill switch must keep dbos unimported")
    require(engine.launch(data_dir) is False and not engine.launched(), "kill switch must keep the engine off")
    status = engine.status()
    require(status["enabled"] is False and status["launched"] is False and "disabled" in status["error"],
            f"kill switch status: {status}")
    require(not (data_dir / engine.SYSTEM_DB_FILENAME).exists(), "kill switch must not create the DBOS database")
    engine.shutdown()


def child_lifecycle(data_dir: Path):
    import asyncio
    import durable_engine as engine

    async def startup_hook():  # FastAPI runs startup hooks on the thread of its running event loop
        return engine.launch(data_dir)

    require(asyncio.run(startup_hook()) is True and engine.launched(), f"launch failed: {engine.status()}")

    async def list_from_loop():  # DBOS's sync API refuses this thread; run_sync must route around it
        return engine.run_sync(engine.DBOS.list_workflows, load_input=False, load_output=False)

    require(asyncio.run(list_from_loop()) == [], "run_sync must work on an event-loop thread")
    require((data_dir / engine.SYSTEM_DB_FILENAME).is_file(), "system database must live on DATA_DIR")
    require(engine.launch(data_dir) is True, "a second launch must be a no-op")
    status = engine.status()
    require(status["app_version"] == engine.APP_VERSION and status["system_database"] == "sqlite"
            and status["error"] == "" and status["pending_at_launch"] == 0, f"status: {status}")
    require(str(data_dir) not in json.dumps(status), "status must not expose the database location")
    engine.shutdown()
    require(not engine.launched(), "shutdown must stop the engine")
    require(engine.launch(data_dir) is True, "the engine must relaunch after shutdown")
    engine.shutdown()


def _crash_workflow(data_dir: Path):
    from durable_engine import DBOS

    @DBOS.step(name="factoryos.test.side_effect")
    def side_effect(tag: str) -> int:
        return bump(data_dir / f"{tag}.count")

    @DBOS.workflow(name="factoryos.test.crash_workflow")
    def crash_workflow() -> dict:
        before = side_effect("before")
        DBOS.set_event("phase", "waiting")
        message = DBOS.recv("go", timeout_seconds=120)
        after = side_effect("after")
        return {"before": before, "message": message, "after": after}

    return crash_workflow


def child_crash_first(data_dir: Path):
    import durable_engine as engine
    workflow = _crash_workflow(data_dir)
    require(engine.launch(data_dir), f"launch failed: {engine.status()}")
    with engine.SetWorkflowID(CRASH_WORKFLOW_ID):
        engine.DBOS.start_workflow(workflow)
    deadline = time.time() + 30
    while engine.DBOS.get_event(CRASH_WORKFLOW_ID, "phase", timeout_seconds=1) != "waiting":
        require(time.time() < deadline, "workflow never reached its wait")
    (data_dir / "ready.flag").write_text("1")
    time.sleep(300)  # The parent SIGKILLs this process here: no shutdown, no flush.


def child_crash_second(data_dir: Path):
    import durable_engine as engine
    _crash_workflow(data_dir)
    require(engine.launch(data_dir), f"relaunch failed: {engine.status()}")
    require(engine.status()["pending_at_launch"] == 1, f"the killed workflow must resume: {engine.status()}")
    engine.DBOS.send(CRASH_WORKFLOW_ID, {"go": True}, topic="go")
    result = engine.DBOS.retrieve_workflow(CRASH_WORKFLOW_ID).get_result()
    require(result == {"before": 1, "message": {"go": True}, "after": 1}, f"resumed result: {result}")
    require((data_dir / "before.count").read_text() == "1", "a checkpointed step must not run again after a crash")
    require((data_dir / "after.count").read_text() == "1", "the step after the wait must run exactly once")
    engine.shutdown()


CHILDREN = {"disabled": child_disabled, "lifecycle": child_lifecycle,
            "crash-first": child_crash_first, "crash-second": child_crash_second}


def _command(mode: str, data_dir: Path):
    return [sys.executable, str(Path(__file__).resolve()), "--child", mode, str(data_dir)]


def run_child(mode: str, data_dir: Path, **env_extra: str):
    env = {**os.environ, **env_extra}
    done = subprocess.run(_command(mode, data_dir), cwd=HERE, env=env, capture_output=True, text=True, timeout=180)
    if done.returncode != 0:
        raise AssertionError(f"child {mode} failed ({done.returncode}):\n{done.stdout[-3000:]}\n{done.stderr[-3000:]}")


def run_until_flag_then_kill(mode: str, data_dir: Path, flag: str, **env_extra: str):
    env = {**os.environ, **env_extra}
    log_path = data_dir / f"{mode}.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(_command(mode, data_dir), cwd=HERE, env=env, stdout=log, stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while not (data_dir / flag).exists():
        if proc.poll() is not None or time.time() > deadline:
            proc.kill()
            raise AssertionError(f"child {mode} did not reach {flag}:\n{log_path.read_text()[-3000:]}")
        time.sleep(0.2)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def main():
    root = Path(tempfile.mkdtemp(prefix="factoryos-durable-engine-"))
    run_child("disabled", root / "disabled", FACTORY_DBOS_ENABLED="0")
    print("kill switch: dbos stays unimported and nothing launches")
    run_child("lifecycle", root / "lifecycle")
    print("lifecycle: SQLite system DB on DATA_DIR, idempotent launch, clean shutdown and relaunch")
    crash_dir = root / "crash"
    crash_dir.mkdir()
    run_until_flag_then_kill("crash-first", crash_dir, "ready.flag")
    run_child("crash-second", crash_dir)
    print("crash: SIGKILL mid-workflow → relaunch resumes it; the finished step did not run again")
    print("Durable engine tests passed")


def run_as_child(mode: str, target: Path):
    """DBOS executor threads are not daemons: always stop the engine and hard-exit, so a failure cannot hang CI."""
    sys.path.insert(0, str(HERE))
    target.mkdir(parents=True, exist_ok=True)
    code = 1
    try:
        CHILDREN[mode](target)
        print(f"child {mode} ok", flush=True)
        code = 0
    except BaseException:
        traceback.print_exc()
    finally:
        engine = sys.modules.get("durable_engine")
        if engine is not None:
            engine.shutdown()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(code)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--child":
        run_as_child(sys.argv[2], Path(sys.argv[3]))
    else:
        main()
