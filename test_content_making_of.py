"""T-690/T-691 content "making of" regression (backend + static UI contract).

T-690: content-job runs live inside the FastAPI process. A deploy/restart used to leave their agent_runs row
'running' forever (a phantom live worker in the trace) while the Supervisor silently reset the job to "ready".
Now the orphaned run is closed as failed with a classified, confirmation-gated reason, and the job list carries
a per-job count of open incidents.

T-691: the flow read model carries per-run duration, cost, model, the Error Center policy and a resolved flag,
and the dashboard renders the pipeline + agent chain inside the expanded content row ("making of").

Runs without fastapi's TestClient (CI has no httpx): the app module is imported with a temp DATA_DIR and its
functions are called directly.
"""
import asyncio
import json
import os
import re
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-making-of-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
import app  # noqa: E402

HTML = Path(__file__).resolve().parent / "static" / "index.html"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def new_job(title):
    return asyncio.run(app.create_job(app.JobCreate(title=title, brief="making-of fixture", presenter="Faceless",
                                                    format="Short only", language="English", outputs=1)))["id"]


def run(job, agent, stage, status=None, error=None, inputs=(), output=None, cost=0.0):
    rid = app.start_agent_run(agent, job, stage, model="simulation-v3")
    app.attach_run_inputs(rid, [{"id": a, "agent": src} for a, src in inputs])
    art = app.save_artifact(agent, "text", output, "MO-OUTPUT", job_id=job, run_id=rid) if output else None
    if status:
        app.finish_agent_run(rid, status=status, error=error, cost_usd=cost)
    return rid, art


def run_status(rid):
    con = app.db()
    row = dict(con.execute("SELECT status,error,finished_at FROM agent_runs WHERE id=?", (rid,)).fetchone())
    con.close()
    return row


def test_interrupted_runs_are_closed():
    job = new_job("Interrupted by deploy")
    r_scout, a_scout = run(job, "Scout", "research", "completed", output="Scout brief", cost=0.01)
    r_res, _ = run(job, "Researcher", "research", inputs=[(a_scout, "Scout")])  # left 'running' by a dead task
    busy = new_job("Still executing here")
    r_busy, _ = run(busy, "Scout", "research")
    app.running_jobs.add(busy)
    try:
        closed = app.close_interrupted_agent_runs()
    finally:
        app.running_jobs.discard(busy)
    require(closed >= 1, "orphaned running run must be closed")
    row = run_status(r_res)
    require(row["status"] == "failed" and row["error"] == app.RUN_INTERRUPTED_ERROR and row["finished_at"],
            f"interrupted run must become failed with the explicit reason: {row}")
    require(run_status(r_busy)["status"] == "running", "a run of a job this process still executes must not be touched")
    require(run_status(r_scout)["status"] == "completed", "finished runs must not be touched")
    p = app.classify_agent_error(app.RUN_INTERRUPTED_ERROR)
    require(p["code"] == "run_interrupted" and p["retryable"] and not p["auto_retry"], "interrupted runs are manual-retryable")
    require(p["requires_confirmation"] and p["spend_uncertain"], "a possibly billed call keeps the paid-retry confirmation")
    flow = app.get_job_flow(job)
    require(flow["live"] is False and flow["counts"]["running"] == 0, "no phantom live worker after the restart")
    hop = flow["hops"][-1]
    require(hop["state"] == "failed" and hop["policy"]["code"] == "run_interrupted" and hop["resolved"] is False,
            f"failed hop must carry the classified policy: {hop}")
    events = [e["message"] for e in _events(job)]
    require(any(m.startswith("Run interrupted: Researcher") for m in events), "the interruption must be logged on the job")
    # Supervisor orphan heal also closes the job's runs.
    r_again, _ = run(job, "Researcher", "research")
    con = app.db(); con.execute("UPDATE jobs SET status='running' WHERE id=?", (job,)); con.commit(); con.close()
    app.supervisor_audit(auto_heal=True, persist=False)
    require(app.get_job(job)["status"] == "idle", "orphaned job is reset to ready")
    require(run_status(r_again)["status"] == "failed", "orphan heal must close the job's running runs")
    return job


def _events(job):
    con = app.db()
    rows = [dict(x) for x in con.execute("SELECT * FROM events WHERE job_id=? ORDER BY id", (job,)).fetchall()]
    con.close()
    return rows


def test_flow_enrichment_and_attention():
    job = new_job("Making-of chain")
    r1, a1 = run(job, "Scout", "research", "completed", output="Scout brief", cost=0.02)
    r2, _ = run(job, "Researcher", "research", "failed", "LLM provider request failed: timed out", inputs=[(a1, "Scout")])
    r3, _ = run(job, "Tech Verifier", "research", "failed", "Missing required upstream artifacts: Researcher")
    flow = app.get_job_flow(job)
    hops = {h["agent"]: h for h in flow["hops"]}
    require(hops["Scout"]["cost_usd"] == 0.02 and isinstance(hops["Scout"]["duration_ms"], int) and hops["Scout"]["model"] == "simulation-v3",
            "hops must carry recorded duration/cost/model")
    require("policy" not in hops["Scout"], "done hops carry no failure policy")
    pol = hops["Researcher"]["policy"]
    require(pol["code"] == "transport_uncertain" and pol["requires_confirmation"] is True, "failed hop must use the Error Center classification")
    require(hops["Tech Verifier"]["state"] == "blocked" and hops["Tech Verifier"]["policy"]["retryable"] is False, "gate stops stay blocked/non-retryable")
    require("MO-OUTPUT" not in json.dumps(flow), "flow must not carry artifact content")
    att = app.get_jobs_attention([job])[job]
    require(att["open"] == 2 and att["agent"] in ("Researcher", "Tech Verifier"), f"two open incidents expected: {att}")
    # A later successful run of the same agent resolves its incident everywhere.
    run(job, "Researcher", "research", "completed", output="Research v2", inputs=[(a1, "Scout")])
    flow = app.get_job_flow(job)
    failed = [h for h in flow["hops"] if h["agent"] == "Researcher" and h["state"] == "failed"][0]
    require(failed["resolved"] is True, "a later completion resolves the failed hop")
    att = app.get_jobs_attention([job])[job]
    require(att["open"] == 1 and att["agent"] == "Tech Verifier", f"only the unresolved incident stays open: {att}")
    center = app.get_job_error_center(job)
    require(center["summary"]["open"] == att["open"], "job-list attention must agree with the Error Center")
    require(app.get_jobs_attention([]) == {}, "empty input")
    st = app.status()
    row = next(j for j in st["jobs"] if j["id"] == job)
    require(row["attention"]["open"] == 1, "status jobs must carry attention")


def test_static_ui_contract():
    html = HTML.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    workmain = html[html.index('<div class="workMain">'):html.index('<aside class="card selected">')]
    require('id="pipeline"' not in workmain, "the global pipeline card must not hang separately above the content list")
    require("function moPanel(" in script and "function toggleMakingOf(" in script, "making-of panel renderer and toggle missing")
    require("onclick=\"toggleMakingOf(" in script, "clicking a content row must expand its making-of")
    require("renderPipelineFlow(S.selectedJobFlow" in script, "the agent chain renders the selected job's flow")
    require("aria-expanded" in script[script.index("function jobs("):script.index("function detail(")], "row must expose its expanded state")
    for key in ("mo.title", "mo.stop.failed", "mo.stop.interrupted", "mo.stop.running", "mo.stop.approval", "mo.stop.paused",
                "mo.stop.done", "mo.attention", "mo.retry", "mo.openLog", "mo.cost", "mo.duration", "mo.whatToDo",
                "error.policy.run_interrupted.title", "error.policy.run_interrupted.action", "error.category.interrupted"):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist in EN/UK/RU")
    require(re.search(r'"status\.ready":"ready to run"', html), "idle must not read as finished ('ready'/'готово')")
    require('"status.ready":"готово"' not in html, "RU/UK idle label must not say 'готово'")


if __name__ == "__main__":
    test_interrupted_runs_are_closed()
    test_flow_enrichment_and_attention()
    test_static_ui_contract()
    print("test_content_making_of: OK")
