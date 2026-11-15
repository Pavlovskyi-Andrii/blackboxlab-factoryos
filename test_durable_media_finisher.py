"""T-612 checks: the AI Media Finisher runs as a durable DBOS workflow. Run: python test_durable_media_finisher.py

Part 1 drives durable_media_finisher with fake submit/poll routines across a real SIGKILL. Part 2 imports the FactoryOS app
with a fake worker (no network, no paid calls) and checks the wiring: submit, re-attach, watchdog skip, lost-worker resubmit,
callback wake-up, health counters, and the FACTORY_DBOS_ENABLED=0 legacy path. Each scenario runs in a fresh interpreter.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait_for(predicate, message, timeout=30.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(message)


def bump(path: Path) -> int:
    count = int(path.read_text() or 0) + 1 if path.exists() else 1
    path.write_text(str(count))
    return count


def count(data_dir: Path, edit_job_id: str, kind: str) -> int:
    path = data_dir / f"{edit_job_id}.{kind}"
    return int(path.read_text() or 0) if path.exists() else 0


# ---------------------------------------------------------------- part 1: the workflow with fake hooks

def _bind_fake_hooks(data_dir: Path):
    """The fake worker: submit records a provider job; poll reports ready once <edit_job_id>.done exists and asks for a
    resubmit once when <edit_job_id>.lost exists (a worker that restarted and forgot the job)."""
    import durable_media_finisher as finisher

    def submit(edit_job_id):
        bump(data_dir / f"{edit_job_id}.submit")
        return {"status": "processing", "provider_job_id": f"provider-{edit_job_id}", "needs_submit": False}

    def poll(edit_job_id):
        bump(data_dir / f"{edit_job_id}.poll")
        lost = data_dir / f"{edit_job_id}.lost"
        if lost.exists():
            lost.unlink()
            return {"status": "queued", "provider_job_id": "", "needs_submit": True}
        status = "ready" if (data_dir / f"{edit_job_id}.done").exists() else "processing"
        return {"status": status, "provider_job_id": f"provider-{edit_job_id}", "needs_submit": False}

    finisher.bind(submit=submit, poll=poll)
    return finisher


def _launch(data_dir: Path):
    import durable_engine as engine
    require(engine.launch(data_dir), f"launch failed: {engine.status()}")
    return engine


def _hold_until_killed(data_dir: Path, flag: str):
    (data_dir / flag).write_text("1")
    time.sleep(300)  # The parent SIGKILLs this process here.


def child_first(data_dir: Path):
    """Start the workflow, let the submit finish, then get killed while it waits for the worker callback."""
    finisher = _bind_fake_hooks(data_dir)
    _launch(data_dir)
    workflow_id, created = finisher.start("ej-1")
    require((workflow_id, created) == ("media-finisher:ej-1:0", True), f"first start: {workflow_id} {created}")
    require(finisher.start("ej-1") == (workflow_id, False), "a second start must re-attach, not start another workflow")
    wait_for(lambda: (finisher.latest_state("ej-1") or {}).get("status") == "processing", "submit never finished")
    _hold_until_killed(data_dir, "first.flag")


def child_old_version(data_dir: Path):
    """A workflow written by an older APP_VERSION, interrupted by a kill (what a version bump leaves behind)."""
    import durable_engine as engine
    engine.APP_VERSION = "factoryos-durable-v0"
    finisher = _bind_fake_hooks(data_dir)
    _launch(data_dir)
    require(finisher.start("ej-3") == ("media-finisher:ej-3:0", True), "old-version start failed")
    wait_for(lambda: (finisher.latest_state("ej-3") or {}).get("status") == "processing", "old-version submit never finished")
    _hold_until_killed(data_dir, "old.flag")


def child_second(data_dir: Path):
    os.environ["FACTORY_DBOS_FINISHER_POLL_SEC"] = "30"  # Completion within seconds must then come from notify().
    finisher = _bind_fake_hooks(data_dir)
    engine = _launch(data_dir)
    DBOS = engine.DBOS
    require(engine.status()["pending_at_launch"] == 1, f"only the current-version workflow resumes: {engine.status()}")
    require(finisher.active("ej-1"), "the killed workflow must still own its edit job after the restart")
    require(finisher.start("ej-1") == ("media-finisher:ej-1:0", False), "a start after the restart must re-attach")

    (data_dir / "ej-1.done").write_text("1")
    started = time.time()
    require(finisher.notify("ej-1", {"status": "ready"}), "notify must reach the waiting workflow")
    result = DBOS.retrieve_workflow("media-finisher:ej-1:0").get_result()
    require(result.get("status") == "ready", f"resumed workflow result: {result}")
    require(time.time() - started < 15, "the callback must wake the workflow long before its 30 s poll")
    require(count(data_dir, "ej-1", "submit") == 1, "the worker must receive exactly one submit across the crash")
    require(not finisher.active("ej-1") and not finisher.notify("ej-1"), "a finished workflow owns nothing")

    # A repaired edit job gets a new generation; a worker that lost the job is resubmitted by the workflow itself.
    os.environ["FACTORY_DBOS_FINISHER_POLL_SEC"] = "1"
    (data_dir / "ej-1.done").unlink()
    (data_dir / "ej-1.lost").write_text("1")
    require(finisher.start("ej-1") == ("media-finisher:ej-1:1", True), "a repaired edit job must start generation 1")
    wait_for(lambda: count(data_dir, "ej-1", "submit") == 3, "lost worker job was not resubmitted")
    (data_dir / "ej-1.done").write_text("1")
    result = DBOS.retrieve_workflow("media-finisher:ej-1:1").get_result()
    require(result.get("status") == "ready" and count(data_dir, "ej-1", "submit") == 3, f"generation 1: {result}")

    # Without a final status inside the max wait, the workflow releases the edit job to the legacy watchdog.
    os.environ["FACTORY_DBOS_FINISHER_MAX_WAIT_SEC"] = "2"
    workflow_id, created = finisher.start("ej-2")
    result = DBOS.retrieve_workflow(workflow_id).get_result()
    require(created and result.get("released") is True and result.get("status") == "processing", f"release: {result}")
    require(not finisher.active("ej-2"), "a released edit job belongs to the legacy watchdog again")

    # A workflow from an older APP_VERSION is never resumed here: start() cancels it and runs a new generation.
    require(not finisher.active("ej-3"), "an older-version workflow must not count as the owner")
    require(finisher.start("ej-3") == ("media-finisher:ej-3:1", True), "old-version edit job must get a fresh workflow")
    require(DBOS.get_workflow_status("media-finisher:ej-3:0").status == "CANCELLED", "old-version workflow must be cancelled")
    (data_dir / "ej-3.done").write_text("1")
    require(DBOS.retrieve_workflow("media-finisher:ej-3:1").get_result().get("status") == "ready", "ej-3 generation 1")
    stats = engine.status()["workflows"]["media_finisher"]
    require(stats["workflows_started"] == 3 and stats["callbacks_delivered"] == 1, f"counters: {stats}")
    engine.shutdown()


# ---------------------------------------------------------------- part 2: FactoryOS app wiring

def _app_fixture(data_dir: Path):
    os.environ.update({"DATA_DIR": str(data_dir), "FACTORY_PASSWORD": "", "FACTORY_LLM_API_KEY": "",
                       "FACTORY_DBOS_FINISHER_POLL_SEC": "30"})
    import uuid
    from urllib import error as urlerror
    import app

    calls = {"POST": 0, "GET": 0}
    worker = {"lost": False}

    def fake_worker(url, method="GET", payload=None, token=""):
        calls[method] += 1
        if method == "POST":
            require(payload["guardrails"]["no_auto_publish"] is True, "guardrails must reach the worker")
            return {"id": "ci-provider-1", "status": "processing", "stage": "queued", "percent": 1}
        if worker["lost"]:
            raise urlerror.HTTPError(url, 404, "not found", None, None)
        return {"id": "ci-provider-1", "status": "processing", "stage": "render", "percent": 50}

    app.FACTORY_MEDIA_FINISHER_ENDPOINT = "https://ci.invalid/finish"
    app.FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT = "https://ci.invalid/finish/jobs"
    app._external_json = fake_worker
    # A direct raw upload (the smoke-test fixture shape): finishable without building a Content Package first.
    job_id = str(uuid.uuid4())
    con = app.db()
    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (job_id, "CI durable finisher", "T-612 fixture", "render",
                                                                      "Human", "Short only", "English", 1, "idle", 65,
                                                                      app.ts(), app.ts()))
    con.commit()
    con.close()
    upload_url = "https://factory.example/media-source/durable-ci?token=" + app._media_upload_signature("durable-ci")
    app.save_artifact("AI Media Finisher", "video", "Raw video upload", "", job_id=job_id, url=upload_url, mime_type="video/mp4",
                      meta={"component": "raw_upload", "upload_id": "durable-ci", "fixture": True})

    def start_edit_job():
        return app.start_media_finisher(job_id, app.MediaFinisherStartRequest(
            profile_id="talking_head_fast", profile_version=1, platform="reels", input_url="",
            confirm_external_cost=True))["edit_job"]["id"]

    return app, calls, worker, start_edit_job


def on_event_loop(fn, *args):
    """Call fn on a thread with a running asyncio loop: where FastAPI runs startup hooks and async endpoints, and where
    DBOS refuses its sync API (durable_engine.run_sync must route around that)."""
    import asyncio

    async def call():
        return fn(*args)

    return asyncio.run(call())


def child_app(data_dir: Path):
    app, calls, worker, start_edit_job = _app_fixture(data_dir)
    import durable_engine as engine
    import durable_media_finisher as finisher
    require(app.app.router.on_startup[0].__name__ == "_durable_engine_startup",
            "the engine must launch before the Media Finisher recovery hooks run")
    on_event_loop(app._durable_engine_startup)
    require(engine.launched() and engine.status()["pending_at_launch"] == 0, f"app startup: {engine.status()}")

    edit_id = on_event_loop(start_edit_job)  # e.g. the startup recovery hook queueing a submit
    workflow_id = f"media-finisher:{edit_id}:0"
    wait_for(lambda: app.get_edit_job(edit_id)["provider_job_id"] == "ci-provider-1", "durable submit never reached the worker")
    require(calls["POST"] == 1 and finisher.active(edit_id), f"one durable submit expected: {calls}")
    require(engine.DBOS.get_workflow_status(workflow_id) is not None, "the workflow ID must be deterministic")

    on_event_loop(app._spawn_media_finisher_submit, edit_id)  # the startup recovery hook seeing this edit job again
    require(len(engine.DBOS.list_workflows(workflow_id_prefix=f"media-finisher:{edit_id}:")) == 1, "no second workflow")
    app._recover_active_media_finisher_jobs()  # one legacy watchdog pass
    require(calls == {"POST": 1, "GET": 0}, f"the watchdog must not poll or resubmit a DBOS-owned edit job: {calls}")

    worker["lost"] = True  # The worker restarted and forgot the job: the poll step resets it, the workflow resubmits.
    state = app._durable_finisher_poll(edit_id)
    require(state["needs_submit"] is True and state["status"] == "queued" and calls["POST"] == 1,
            f"a 404 poll must ask the workflow to resubmit, without spawning a legacy thread: {state} {calls}")
    worker["lost"] = False
    state = app._durable_finisher_submit(edit_id)
    require(state == {"status": "processing", "provider_job_id": "ci-provider-1", "needs_submit": False}, f"{state}")

    # The worker callback, through the endpoint handler (CI has no HTTP client for TestClient; see test_web_surfer.py).
    import asyncio
    from starlette.requests import Request
    started = time.time()
    payload = app.MediaFinisherCallbackRequest(status="failed", error="CI synthetic worker failure",
                                               provider_job_id="ci-provider-1")
    response = asyncio.run(app.media_finisher_callback(edit_id, payload, Request({"type": "http", "headers": []})))
    require(response["ok"] is True and response["edit_job"]["status"] == "failed", f"callback: {response}")
    result = engine.DBOS.retrieve_workflow(workflow_id).get_result()
    require(result.get("status") == "failed" and time.time() - started < 15,
            f"the callback must finish the workflow without waiting for the 30 s poll: {result}")
    require(not finisher.active(edit_id), "a finished edit job is not DBOS-owned any more")
    durable = app.health_details()["durable_engine"]
    require(durable["launched"] and durable["workflows"]["media_finisher"]["workflows_started"] == 1
            and durable["workflows"]["media_finisher"]["callbacks_delivered"] == 1, f"health: {durable}")
    app._durable_engine_shutdown()


def child_app_disabled(data_dir: Path):
    app, calls, _worker, start_edit_job = _app_fixture(data_dir)
    import durable_engine as engine
    require("dbos" not in sys.modules, "FACTORY_DBOS_ENABLED=0 must not import dbos")
    app._durable_engine_startup()
    require(not engine.launched() and app.health_details()["durable_engine"]["enabled"] is False, "kill switch")
    edit_id = start_edit_job()
    wait_for(lambda: app.get_edit_job(edit_id)["provider_job_id"] == "ci-provider-1", "legacy submit thread never ran")
    require(calls["POST"] == 1, f"legacy path must submit exactly once: {calls}")
    app._recover_active_media_finisher_jobs()
    require(calls == {"POST": 1, "GET": 1}, f"without the engine the legacy watchdog polls the edit job as before: {calls}")
    require(not (data_dir / engine.SYSTEM_DB_FILENAME).exists(), "kill switch must not create the DBOS database")

    # Codex review on #379: a failing wake-up must never fail the worker's callback once the result is saved.
    import asyncio
    from starlette.requests import Request

    def broken_notify(*_args, **_kwargs):
        raise RuntimeError("synthetic notify failure")

    broadcasts = []

    async def record_broadcast(payload=None):
        broadcasts.append(payload)

    app.durable_finisher.notify, app.broadcast = broken_notify, record_broadcast
    payload = app.MediaFinisherCallbackRequest(status="failed", error="CI synthetic worker failure", provider_job_id="ci-provider-1")
    response = asyncio.run(app.media_finisher_callback(edit_id, payload, Request({"type": "http", "headers": []})))
    require(response["ok"] is True and app.get_edit_job(edit_id)["status"] == "failed", f"callback after notify error: {response}")
    require(broadcasts and broadcasts[-1]["action"] == "callback", "the UI broadcast must still go out")


CHILDREN = {"first": child_first, "old-version": child_old_version, "second": child_second,
            "app": child_app, "app-disabled": child_app_disabled}


def _command(mode: str, data_dir: Path):
    return [sys.executable, str(Path(__file__).resolve()), "--child", mode, str(data_dir)]


def run_child(mode: str, data_dir: Path, **env_extra: str):
    done = subprocess.run(_command(mode, data_dir), cwd=HERE, env={**os.environ, **env_extra}, capture_output=True,
                          text=True, timeout=240)
    if done.returncode != 0:
        raise AssertionError(f"child {mode} failed ({done.returncode}):\n{done.stdout[-4000:]}\n{done.stderr[-4000:]}")


def run_until_flag_then_kill(mode: str, data_dir: Path, flag: str, **env_extra: str):
    log_path = data_dir / f"{mode}.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(_command(mode, data_dir), cwd=HERE, env={**os.environ, **env_extra}, stdout=log,
                                stderr=subprocess.STDOUT)
    deadline = time.time() + 120
    while not (data_dir / flag).exists():
        if proc.poll() is not None or time.time() > deadline:
            proc.kill()
            raise AssertionError(f"child {mode} did not reach {flag}:\n{log_path.read_text()[-4000:]}")
        time.sleep(0.2)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def main():
    root = Path(tempfile.mkdtemp(prefix="factoryos-durable-finisher-"))
    crash = root / "workflow"
    crash.mkdir()
    run_until_flag_then_kill("first", crash, "first.flag")
    run_until_flag_then_kill("old-version", crash, "old.flag")
    run_child("second", crash)
    print("workflow: survives SIGKILL with one submit, callback wake-up, lost-worker resubmit, release, version bump")
    run_child("app", root / "app")
    print("app: durable submit, re-attach, watchdog skip, 404 resubmit hook, callback finishes the workflow, health")
    run_child("app-disabled", root / "app-disabled", FACTORY_DBOS_ENABLED="0")
    print("app: FACTORY_DBOS_ENABLED=0 keeps the legacy submit thread")
    print("Durable Media Finisher tests passed")


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
