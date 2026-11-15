"""T-613 checks: the content pipeline run to the review gate as a durable DBOS workflow. Run: python test_durable_content.py

Gate 2 of the DBOS plan: after a restart no finished LLM step is called again. Part 1 drives durable_content with fake
hooks across a real SIGKILL (live and demo agents, gate failure, re-attach). Part 2 runs the FactoryOS pipeline itself on
a background event loop (as under uvicorn) with demo agents, then with a fake paid LLM killed mid-call. No network, no
paid calls; each scenario runs in a fresh interpreter.
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
PLAN = [{"index": 1, "stage": "research", "agents": ["A", "B", "C"]}]
STARTED_AT = "2026-01-01T00:00:00+00:00"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def wait_for(predicate, message, timeout=60.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError(message)


def bump(path: Path) -> int:
    value = int(path.read_text() or 0) + 1 if path.exists() else 1
    path.write_text(str(value))
    return value


def count(path: Path) -> int:
    return int(path.read_text() or 0) if path.exists() else 0


# ---------------------------------------------------------------- part 1: the workflow with fake hooks

def _bind_fake_hooks(data_dir: Path):
    """Agents of a job whose ID ends in "live" stand for paid calls; the others for demo agents. An agent with a
    block-<job>-<agent> file hangs on its first start, so the parent can kill the process mid-call."""
    import durable_engine as engine
    import durable_content as content

    def enter_stage(job_id, index, stage):
        bump(data_dir / f"{job_id}.enter-{index}")
        (data_dir / f"{job_id}.enter-stage-{index}").write_text(stage)
        return {"index": index}

    def agent(job_id, stage, name, started_at):
        require(started_at == STARTED_AT, "started_at must reach the step unchanged")
        while (data_dir / "hold").exists():  # lets a test look at a resumed run before it moves on
            time.sleep(0.05)
        attempt = engine.step_attempt()
        bump(data_dir / f"{job_id}.{name}.starts")
        if attempt > 1:
            if job_id.endswith("live"):
                raise RuntimeError(f"{name}: Interrupted by a FactoryOS restart: the provider request failed or may have "
                                   "completed; outcome uncertain")
            bump(data_dir / f"{job_id}.{name}.restarted")
        elif (data_dir / f"block-{job_id}-{name}").exists():
            (data_dir / f"{job_id}.{name}.blocked").write_text("1")
            time.sleep(300)  # the parent SIGKILLs the process during this "provider call"
        bump(data_dir / f"{job_id}.{name}.done")
        return {"agent": name}

    def script(job_id, part, started_at):
        bump(data_dir / f"{job_id}.script-{part}")
        return {"part": part}

    def gate(job_id, stage):
        if (data_dir / f"fail-gate-{job_id}").exists():
            raise ValueError(f"Quality gate failed for {stage}: missing artifacts from C")
        bump(data_dir / f"{job_id}.gate-{stage}")
        return {"stage": stage}

    def review(job_id):
        (data_dir / f"{job_id}.review").write_text("1")
        return {"status": "waiting_approval"}

    def failed(job_id, error):
        (data_dir / f"{job_id}.failed").write_text(error)
        return {"status": "failed"}

    content.bind(enter_stage=enter_stage, agent=agent, script=script, gate=gate, review=review, failed=failed)
    return engine, content


def child_first(data_dir: Path):
    engine, content = _bind_fake_hooks(data_dir)
    require(engine.launch(data_dir), f"launch failed: {engine.status()}")
    for job_id in ("j-live", "j-demo"):
        (data_dir / f"block-{job_id}-B").write_text("1")
        workflow_id, created = content.start(job_id, PLAN, STARTED_AT)
        require(created and workflow_id == f"content-run:{job_id}:0", f"start {job_id}: {workflow_id} {created}")
        require(content.start(job_id, PLAN, STARTED_AT) == (workflow_id, False), "a second start must re-attach")
    wait_for(lambda: all((data_dir / f"{j}.B.blocked").exists() for j in ("j-live", "j-demo")), "B never started")
    require(sorted(content.active_job_ids()) == ["j-demo", "j-live"], f"active jobs: {content.active_job_ids()}")
    (data_dir / "first.flag").write_text("1")
    time.sleep(300)


def child_second(data_dir: Path):
    for job_id in ("j-live", "j-demo"):
        (data_dir / f"block-{job_id}-B").unlink()
    (data_dir / "hold").write_text("1")
    engine, content = _bind_fake_hooks(data_dir)
    require(engine.launch(data_dir), f"relaunch failed: {engine.status()}")
    require(engine.status()["pending_at_launch"] == 2 and sorted(content.active_job_ids()) == ["j-demo", "j-live"],
            f"both killed runs must resume and own their jobs: {engine.status()} {content.active_job_ids()}")
    (data_dir / "hold").unlink()
    DBOS = engine.DBOS

    live = DBOS.retrieve_workflow("content-run:j-live:0").get_result()
    require(live["status"] == "failed" and "outcome uncertain" in live["error"], f"live run: {live}")
    require(count(data_dir / "j-live.A.done") == 1, "a finished paid agent must not run again after the restart")
    require(count(data_dir / "j-live.B.done") == 0 and count(data_dir / "j-live.C.starts") == 0,
            "an interrupted paid call must stop the run, not be paid for again")
    require("outcome uncertain" in (data_dir / "j-live.failed").read_text(), "the failed hook must get the error")
    require(not (data_dir / "j-live.review").exists(), "a failed run never reaches the review gate")

    demo = DBOS.retrieve_workflow("content-run:j-demo:0").get_result()
    require(demo == {"status": "waiting_approval"}, f"demo run: {demo}")
    require(count(data_dir / "j-demo.A.done") == 1 and count(data_dir / "j-demo.C.done") == 1, "A and C exactly once")
    require(count(data_dir / "j-demo.B.done") == 1 and count(data_dir / "j-demo.B.restarted") == 1,
            "an interrupted demo agent runs again by itself")
    require(count(data_dir / "j-demo.enter-1") == 1 and count(data_dir / "j-demo.gate-research") == 1, "steps run once")
    require(content.active_job_ids() == [] and not content.active("j-demo"), "finished runs own nothing")

    # A failed quality gate fails the run (its error is checkpointed like any step error); the review gate is not reached.
    # The plan's saved stage name reaches the enter step as is, never re-derived from its index (Codex review #380).
    (data_dir / "fail-gate-j-gate").write_text("1")
    workflow_id, created = content.start("j-gate", [{"index": 5, "stage": "research", "agents": ["A"]}], STARTED_AT)
    result = DBOS.retrieve_workflow(workflow_id).get_result()
    require(created and result["status"] == "failed" and "Quality gate failed" in result["error"], f"gate: {result}")
    require(not (data_dir / "j-gate.review").exists(), "gate failure must not reach review")
    require((data_dir / "j-gate.enter-stage-5").read_text() == "research", "enter step must get the saved stage name")
    # A new run of the same job is a new generation.
    (data_dir / "fail-gate-j-gate").unlink()
    workflow_id, created = content.start("j-gate", [{"index": 1, "stage": "research", "agents": ["A"]}], STARTED_AT)
    require(created and workflow_id == "content-run:j-gate:1", f"second run: {workflow_id}")
    require(DBOS.retrieve_workflow(workflow_id).get_result() == {"status": "waiting_approval"}, "second run result")
    engine.shutdown()


# ---------------------------------------------------------------- part 2: the FactoryOS pipeline itself

def _app(data_dir: Path, fake_llm: bool = False, live_key: bool = False, hold: bool = False):
    os.environ.update({"DATA_DIR": str(data_dir), "FACTORY_PASSWORD": "", "FACTORY_LLM_API_KEY": ""})
    import asyncio
    import threading
    import app

    if hold:  # a resumed step waits at its spend fence until the test has looked at the restarted process
        (data_dir / "hold").write_text("1")
        fence = app._durable_content_fence

        def held_fence(*args):
            while (data_dir / "hold").exists():
                time.sleep(0.05)
            return fence(*args)

        app._durable_content_fence = held_fence

    loop = asyncio.new_event_loop()  # stands in for uvicorn's loop: FactoryOS coroutines must keep running on it
    threading.Thread(target=loop.run_forever, daemon=True, name="main-loop").start()

    def on_loop(coro, timeout=120):
        return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=timeout)

    if live_key:  # paid mode from the first step on (a placeholder, never sent anywhere: the provider is faked)
        app.FACTORY_LLM_API_KEY = "ci-placeholder-not-a-key"
    if fake_llm:  # a fake paid provider: counts calls per agent; QA Agent hangs while block-qa exists

        def fake_provider(agent, job, input_pack):
            bump(data_dir / f"llm-{agent.replace(' ', '_')}.calls")
            if agent == "QA Agent" and (data_dir / "block-qa").exists():
                (data_dir / "qa.inflight").write_text("1")
                time.sleep(300)
            return {"kind": "analysis", "title": f"{agent} output", "content": f"{agent}: CI output", "model": "ci-fake",
                    "input_tokens": 10, "output_tokens": 10, "cost_usd": 0.0}

        app._call_live_llm = fake_provider

    async def startup():  # Starlette runs sync startup hooks on the loop's thread
        app._durable_engine_startup()

    on_loop(startup())
    return app, on_loop


def _audit_without_running_jobs(app):
    """One supervisor pass as right after a restart, when the in-memory running_jobs no longer knows the job."""
    saved, app.running_jobs = app.running_jobs, set()
    try:
        app.supervisor_audit(auto_heal=True, persist=False)
    finally:
        saved.update(app.running_jobs)
        app.running_jobs = saved


def _completed_runs(app, job_id, since=""):
    con = app.db()
    rows = con.execute("""SELECT agent, stage, COUNT(*) c FROM agent_runs WHERE job_id=? AND status='completed'
                          AND started_at>=? GROUP BY agent, stage""", (job_id, since)).fetchall()
    con.close()
    return {(r["agent"], r["stage"]): r["c"] for r in rows}


def _new_job(app, on_loop, title):
    return on_loop(app.create_job(app.JobCreate(title=title, brief="T-613 fixture", presenter="Faceless",
                                                format="Short only", language="English", outputs=1)))["id"]


def child_app_demo(data_dir: Path):
    app, on_loop = _app(data_dir)
    import durable_engine as engine
    import durable_content as content
    require(engine.launched() and engine.main_loop() is not None, f"engine: {engine.status()}")
    legacy_runs = []

    async def legacy_runner(job_id):
        legacy_runs.append(job_id)

    app.run_until_review = legacy_runner  # any legacy fallback below would show up here
    real_start, real_owner = content.start, content.active_workflow

    def start_then_fail(*args):  # Codex review #380: the start persisted the workflow, then raised
        real_start(*args)
        raise RuntimeError("synthetic failure after the workflow was persisted")

    content.start = start_then_fail
    job_id = _new_job(app, on_loop, "CI durable content run")
    response = on_loop(app.run_job(job_id))
    content.start = real_start
    require(response["ok"] and content.active(job_id) and not legacy_runs,
            f"a durable start that persisted, then failed, must not add a legacy runner: {response} {legacy_runs}")
    require(on_loop(app.run_job(job_id))["message"] == "Already running", "a second click must not start another run")

    # The supervisor must not reset a job a durable run owns, even if running_jobs forgot it (as after a restart).
    wait_for(lambda: (app.get_job(job_id) or {}).get("status") == "running", "the run never entered a stage")
    _audit_without_running_jobs(app)
    require(app.get_job(job_id)["status"] == "running", "supervisor auto-heal reset a durable run")

    wait_for(lambda: (app.get_job(job_id) or {}).get("status") == "waiting_approval", "run never reached review", 120)
    runs = _completed_runs(app, job_id)
    require(set(runs.values()) == {1}, f"each agent exactly once, as run_until_review: {runs}")
    for stage in ("research", "visual", "voice", "render", "qa"):
        for agent in app.AGENT_MAP[stage]:
            require(runs.get((agent, stage)) == 1, f"{agent} ({stage}) missing: {runs}")
    require(runs.get(("Content Packager", "package")) == 1, f"script stage: {runs}")
    require(not content.active(job_id) and job_id not in app.running_jobs, "a finished run owns nothing")
    require(app.health_details()["durable_engine"]["workflows"]["content_run"]["runs_started"] == 1, "health counter")

    # A failed start whose outcome DBOS cannot confirm starts nothing; a confirmed non-start falls back to the legacy task.
    def start_fails(*args):
        raise RuntimeError("synthetic start failure")

    def owner_unknown(job_id, strict=False):  # like the real lookup during an outage: None, or raise when strict
        if strict:
            raise RuntimeError("synthetic DBOS outage")
        return None

    other = _new_job(app, on_loop, "CI start failure")
    content.start, content.active_workflow = start_fails, owner_unknown
    blocked = on_loop(app.run_job(other))
    require(not blocked["ok"] and "could not confirm" in blocked["message"] and other not in app.running_jobs
            and not legacy_runs, f"unknown start outcome must start nothing: {blocked} {legacy_runs}")
    content.active_workflow = real_owner
    fallback = on_loop(app.run_job(other))
    wait_for(lambda: legacy_runs == [other], "a confirmed non-start must fall back to the legacy task")
    require(fallback["ok"] and not content.active(other), f"legacy fallback: {fallback}")
    content.start = real_start
    app.running_jobs.discard(other)

    # The enter step stores the plan's stage name even if a deploy reordered STAGES (Codex review #380).
    saved = list(app.STAGES)
    app.STAGES[3], app.STAGES[4] = app.STAGES[4], app.STAGES[3]
    try:
        app._durable_content_enter_stage(other, 3, "visual")
        require(app.get_job(other)["stage"] == "visual", "enter step must use the saved stage name")
    finally:
        app.STAGES[:] = saved

    # Which steps count as paid mirrors each operation's own demo/live switch.
    require(not any(app._content_step_is_paid(agent=a) for a in ("QA Agent", "Voice Agent"))
            and not app._content_step_is_paid(part="variants"), "no key → nothing is paid")
    app.FACTORY_LLM_API_KEY = "ci-placeholder-not-a-key"
    try:
        require(app._content_step_is_paid(agent="QA Agent") and not app._content_step_is_paid(agent="Voice Agent")
                and app._content_step_is_paid(part="variants") and app._content_step_is_paid(part="package"),
                "with a key: LLM agents and both script operations are paid, Voice/Render are not")
    finally:
        app.FACTORY_LLM_API_KEY = ""


def child_app_live_first(data_dir: Path):
    (data_dir / "block-qa").write_text("1")
    app, on_loop = _app(data_dir, fake_llm=True)
    job_id = _new_job(app, on_loop, "CI durable paid run")
    (data_dir / "job_id").write_text(job_id)
    # A demo run first builds the upstream artifacts (Visual Director needs the Content Package) ...
    require(on_loop(app.run_job(job_id))["ok"], "demo run_job failed")
    wait_for(lambda: (app.get_job(job_id) or {}).get("status") == "waiting_approval", "demo run never reached review", 120)
    # ... then a paid rerun from Visual: Visual Director (paid) → Voice → Render → QA Agent (paid, hangs → SIGKILL).
    app.FACTORY_LLM_API_KEY = "ci-placeholder-not-a-key"
    (data_dir / "paid_run_started_at").write_text(app.ts())
    con = app.db()
    con.execute("UPDATE jobs SET stage='visual', status='idle' WHERE id=?", (job_id,))
    con.commit()
    con.close()
    require(on_loop(app.run_job(job_id))["ok"], "paid run_job failed")
    wait_for(lambda: (data_dir / "qa.inflight").exists(), "QA Agent never started its paid call", 120)
    (data_dir / "first.flag").write_text("1")
    time.sleep(300)


def child_app_live_second(data_dir: Path):
    (data_dir / "block-qa").unlink()
    job_id = (data_dir / "job_id").read_text()
    app, _on_loop = _app(data_dir, fake_llm=True, live_key=True, hold=True)
    import durable_content as content
    require(job_id in app.running_jobs and content.active(job_id), "the resumed run must own its job at startup")
    _audit_without_running_jobs(app)
    require(app.get_job(job_id)["status"] == "running", "supervisor auto-heal reset a resumed durable run")
    (data_dir / "hold").unlink()
    wait_for(lambda: (app.get_job(job_id) or {}).get("status") == "failed", "the interrupted paid call must fail the run")
    require(count(data_dir / "llm-Visual_Director.calls") == 1, "a finished paid agent was called again after restart")
    require(count(data_dir / "llm-QA_Agent.calls") == 1, "the interrupted paid call was repeated without confirmation")
    runs = _completed_runs(app, job_id, since=(data_dir / "paid_run_started_at").read_text())
    require(runs == {("Visual Director", "visual"): 1, ("Voice Agent", "voice"): 1, ("Render Agent", "render"): 1},
            f"the paid run's finished agents exactly once, QA never completed: {runs}")
    center = app.get_job_error_center(job_id)
    qa = [x for x in center["incidents"] if x["agent"] == "QA Agent" and not x["resolved"]]
    require(qa and qa[0]["policy"]["spend_uncertain"] and qa[0]["policy"]["requires_confirmation"],
            f"Error Center must hold an uncertain-spend incident for QA Agent: {center['incidents']}")
    require(job_id not in app.running_jobs and not content.active(job_id), "a failed run owns nothing")


CHILDREN = {"first": child_first, "second": child_second, "app-demo": child_app_demo,
            "app-live-first": child_app_live_first, "app-live-second": child_app_live_second}


def _command(mode: str, data_dir: Path):
    return [sys.executable, str(Path(__file__).resolve()), "--child", mode, str(data_dir)]


def run_child(mode: str, data_dir: Path, **env_extra: str):
    done = subprocess.run(_command(mode, data_dir), cwd=HERE, env={**os.environ, **env_extra}, capture_output=True,
                          text=True, timeout=300)
    if done.returncode != 0:
        raise AssertionError(f"child {mode} failed ({done.returncode}):\n{done.stdout[-4000:]}\n{done.stderr[-4000:]}")


def run_until_flag_then_kill(mode: str, data_dir: Path, flag: str, **env_extra: str):
    log_path = data_dir / f"{mode}.log"
    with open(log_path, "w") as log:
        proc = subprocess.Popen(_command(mode, data_dir), cwd=HERE, env={**os.environ, **env_extra}, stdout=log,
                                stderr=subprocess.STDOUT)
    deadline = time.time() + 180
    while not (data_dir / flag).exists():
        if proc.poll() is not None or time.time() > deadline:
            proc.kill()
            raise AssertionError(f"child {mode} did not reach {flag}:\n{log_path.read_text()[-4000:]}")
        time.sleep(0.2)
    os.kill(proc.pid, signal.SIGKILL)
    proc.wait(timeout=30)


def main():
    root = Path(tempfile.mkdtemp(prefix="factoryos-durable-content-"))
    workflow = root / "workflow"
    workflow.mkdir()
    run_until_flag_then_kill("first", workflow, "first.flag")
    run_child("second", workflow)
    print("workflow: SIGKILL mid-call → finished agents not re-run; paid call stops the run, demo call reruns; gate")
    run_child("app-demo", root / "app-demo")
    print("app: run_job → durable run to the review gate, each agent once, no second run, supervisor leaves it alone")
    live = root / "app-live"
    live.mkdir()
    run_until_flag_then_kill("app-live-first", live, "first.flag")
    run_child("app-live-second", live)
    print("app: SIGKILL during a paid call → no finished paid agent called again; uncertain-spend incident instead")
    print("Durable content run tests passed")


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
