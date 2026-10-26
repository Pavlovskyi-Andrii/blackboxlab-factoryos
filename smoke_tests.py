"""FactoryOS zero-spend smoke/regression checks."""
import asyncio
import inspect
import json
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-smoke-")
elif Path(os.environ["DATA_DIR"]).is_dir() and any(Path(os.environ["DATA_DIR"]).iterdir()):
    # The suite asserts fresh-fixture state; isolate reruns without deleting prior data.
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="smoke-run-", dir=os.environ["DATA_DIR"])
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
import app  # noqa: E402

def require(condition, message):
    if not condition:
        raise AssertionError(message)

def route_exists(path, method):
    method=method.upper()
    return any(getattr(route,"path",None)==path and method in set(getattr(route,"methods",set()) or set()) for route in app.app.routes)

health=app.health()
require(health["ok"] is True,"health must be ok")
require(health["version"]==app.APP_VERSION=="v5.5.1","version mismatch")
require("paid_verification" in health,"paid verification health summary missing")
require(health["paid_verification"]["status"] in ("pending","started","passed","failed","disabled"),"unexpected paid verification status")
require("llm_configured" in health and "llm_model" in health,"provider readiness fields missing")
require("real_pilot" in health and health["real_pilot"]["status"]=="disabled","CI must never auto-run the real paid pilot")
state=app.status()
for key in ("factory","version","jobs","agentStates","agentProgress","usage","selectedJobWorkerResults","selectedJobHandoffs","selectedJobAgentErrors","selectedJobErrorCenter","selectedJobVariants","selectedJobContentPackage","mediaAdapters","contentBrain","approvalSummary","publishingSummary","performanceSummary","selfImprovementSummary","autonomousCycleSummary","discoverySummary","discoveryAdapter","revideoSummary","revideoAdapters","mediaFinisher","activeWorkflow","publisherAdapters","analyticsAdapters","runtimePolicy"):
    require(key in state,f"status missing {key}")
require(state["factory"]=="online","factory must report online")
autopilot_state=app.get_repository_autopilot_state()
require(autopilot_state["enabled"] is True,"repository autopilot contract must be enabled")
require(autopilot_state["runner_present"] is True,"autopilot runner missing")
require(autopilot_state["total"]>=8,"roadmap task parsing regression")
roadmap_tasks=app._parse_roadmap_tasks()
safe_roadmap=[x for x in roadmap_tasks if not x["done"] and not x["human"]]
human_roadmap=[x for x in roadmap_tasks if not x["done"] and x["human"]]
expected_next=safe_roadmap[0] if safe_roadmap else None
require(autopilot_state["safe_pending"]==len(safe_roadmap),"safe roadmap count mismatch")
require(autopilot_state["next_task"]==expected_next,"next safe roadmap task must match the first pending non-HUMAN task")
require(autopilot_state["human_pending"]==len(human_roadmap) and autopilot_state["human_pending"]>=2,"real publisher and first real post must remain HUMAN blockers")
require(len(autopilot_state["recent_decisions"])>=1,"autonomous decision log must be exposed")
require(autopilot_state["safety"]["main_push_forbidden"] is True,"autopilot main-branch safety regression")
connections=app.get_connection_registry()
require("Telegram" in connections and "Claude Code Pro" in connections,"owner/automation connections missing")
require("HubSpot" in connections and connections["HubSpot"]["portable"] is True,"CRM portability connection missing")
for provider in ("Metricool","YouTube","Instagram","TikTok","HubSpot"):
    require(provider in connections and connections[provider].get("secrets_exposed") is False,f"{provider} portability metadata missing")
require("@blackboxlab" not in json.dumps(connections,ensure_ascii=False),"connection registry must not hard-code the owner's social identity")
require(connections["Claude Code Pro"]["state"]=="not_configured","CI must not fake a live Claude Pro runner")
require(app.get_claude_code_status()["online"] is False,"CI must not report Claude worker online")

# v5.3.1 account portability — a workspace can detach provider identities without deleting content.
orig_metricool=(app.FACTORY_METRICOOL_TOKEN,app.FACTORY_METRICOOL_USER_ID,app.FACTORY_METRICOOL_BLOG_ID)
con=app.db();con.execute("DELETE FROM integration_accounts WHERE workspace_key=?",(app.INTEGRATION_WORKSPACE_KEY,));con.commit();con.close()
try:
    app.FACTORY_METRICOOL_TOKEN="ci-token";app.FACTORY_METRICOOL_USER_ID="ci-user";app.FACTORY_METRICOOL_BLOG_ID="ci-blog"
    require(app._portable_connection("YouTube")["state"]=="connected","legacy Metricool credentials should expose a replaceable YouTube binding")
    app._integration_set("YouTube","disconnected",auth_mode="via_metricool",connected_via="metricool")
    require(app._portable_connection("YouTube")["state"]=="disconnected","YouTube disconnect override must be durable")
    require(app._metricool_configured() is True,"one social disconnect must not disable Metricool transport")
    app._integration_set("Metricool","disconnected",auth_mode="server_credentials",connected_via="metricool")
    require(app._metricool_configured() is False,"Metricool disconnect must disable the publishing transport")
finally:
    app.FACTORY_METRICOOL_TOKEN,app.FACTORY_METRICOOL_USER_ID,app.FACTORY_METRICOOL_BLOG_ID=orig_metricool
    con=app.db();con.execute("DELETE FROM integration_accounts WHERE workspace_key=?",(app.INTEGRATION_WORKSPACE_KEY,));con.commit();con.close()
def claude_result(**overrides):
    base=dict(task_id="T-508",pinned_task_id="T-508",result="done",branch="autopilot-ci",summary="ci",commit="a"*40,commit_count=1,files=["ROADMAP.md"],exit_code=0,max_turns=80,timeout_seconds=3600)
    return app.ClaudeWorkerTaskResult(**{**base,**overrides})
accepted=app.ingest_claude_worker_result(claude_result())
require(accepted["result"]=="done" and accepted["violations"]==[],"verified delegated result must be ingested as done")
require(app.get_claude_code_status()["recent_results"][-1]["task_id"]=="T-508","ingested Claude result must be visible in worker status")
for overrides,code in ((dict(pinned_task_id="T-510"),409),(dict(branch="main"),409),(dict(branch="master"),409),(dict(task_id="T-507",pinned_task_id="T-507"),409),(dict(task_id="T-999",pinned_task_id="T-999"),404),(dict(result="shipped"),422)):
    try:
        app.ingest_claude_worker_result(claude_result(**overrides))
    except app.HTTPException as exc:
        require(exc.status_code==code,f"Claude result rejection regression for {overrides}: {exc.status_code}")
    else:
        raise AssertionError(f"Claude result must be rejected: {overrides}")
for overrides in (dict(commit_count=2),dict(commit=""),dict(pushed=True),dict(deploy_credentials_scrubbed=False),dict(violations=["protected branch main was modified"])):
    require(app.ingest_claude_worker_result(claude_result(**overrides))["result"]=="failed",f"unverified Claude done must fail closed: {overrides}")
require(app.get_claude_code_status()["online"] is False,"result ingestion must not fake a live Claude worker heartbeat")
live_t536a=next((x for x in roadmap_tasks if x["id"]=="T-536-A"),None)
require(live_t536a and live_t536a["parent"]=="T-536" and live_t536a["planner"]=="ChatGPT","live ROADMAP planner/parent metadata regression")
require(next(x for x in roadmap_tasks if x["id"]=="T-536-D")["depends"]==["T-536-A","T-536-B","T-536-C"],"live ROADMAP dependency metadata regression")
require(next(x for x in roadmap_tasks if x["id"]=="T-500")["depends"]==[] and route_exists("/api/factory/delegation-board","GET"),"legacy ROADMAP entries/board route regression")
board_fixture=app._parse_roadmap_tasks("""## Fixture
- [x] T-900 Done task
- [ ] [HUMAN] T-901 Owner credential
  Need: owner secret
- [ ] T-902 Parent work
  Planner: ChatGPT
- [ ] T-902-A Running child
  Planner: ChatGPT
  Parent: T-902
  Goal: build the child
    across two lines
  DONE: `python -m child_check` passes
- [ ] T-902-B Blocked child
  Parent: T-902
  Depends: T-902-A, not-a-task
- [ ] T-903 Queued legacy task
  Goal: still parses
""")
require([x["id"] for x in board_fixture]==["T-900","T-901","T-902","T-902-A","T-902-B","T-903"],"fixture ROADMAP parse regression")
require(board_fixture[4]["depends"]==["T-902-A"] and board_fixture[3]["parent"]=="T-902" and board_fixture[5]["planner"]=="","fixture ROADMAP metadata regression")
require(board_fixture[3]["goal"]=="build the child across two lines" and board_fixture[3]["done_criteria"]=="`python -m child_check` passes"
        and board_fixture[3]["source"]=="ChatGPT" and board_fixture[3]["provenance"]=="planner" and board_fixture[3]["roadmap_line"]==7,
        f"fixture ROADMAP goal/DONE/provenance regression: {board_fixture[3]}")
require(board_fixture[1]["need"]=="owner secret" and board_fixture[5]["goal"]=="still parses" and board_fixture[5]["done_criteria"]==""
        and board_fixture[5]["source"]=="roadmap" and board_fixture[5]["provenance"]=="legacy" and board_fixture[0]["done"] is True,"legacy ROADMAP entry compatibility regression")
live_t536c=next(x for x in roadmap_tasks if x["id"]=="T-536-C")
require(live_t536c["parent"]=="T-536" and live_t536c["source"]=="ChatGPT" and live_t536c["depends"]==["T-536-A"]
        and live_t536c["goal"].startswith("make ROADMAP tasks readable") and live_t536c["done_criteria"].startswith("parser/API expose"),"live ROADMAP T-536-C metadata regression")
live_t500=next(x for x in roadmap_tasks if x["id"]=="T-500")
require(live_t500["provenance"]=="legacy" and live_t500["goal"] and live_t500["done_criteria"].startswith("`test -f ROADMAP.md"),"live legacy ROADMAP Goal/DONE regression")
odd_tree=app._roadmap_task_tree([{**x,"state":"queued","queue_position":None} for x in app._parse_roadmap_tasks("""## Odd
- [ ] T-1 Self parent
  Parent: T-1
- [ ] T-2 Cycle A
  Parent: T-3
- [ ] T-3 Cycle B
  Parent: T-2
- [ ] T-4 Orphan
  Parent: T-404
""")])
require(sorted(n["id"] for n in odd_tree)==["T-1","T-2","T-4"] and next(n for n in odd_tree if n["id"]=="T-2")["children"][0]["id"]=="T-3","roadmap tree must survive self-parent, cycles and unknown parents")
real_parse_roadmap,real_results_file,real_worker_runtime=app._parse_roadmap_tasks,app.CLAUDE_WORKER_RESULTS_FILE,dict(app.claude_worker_runtime)
app._parse_roadmap_tasks=lambda text=None:[dict(x) for x in board_fixture]
app.CLAUDE_WORKER_RESULTS_FILE=Path(os.environ["DATA_DIR"])/"delegation_board_fixture_results.json"
try:
    offline=app.get_delegation_board()
    require(offline["worker"]["connection"]=="offline" and offline["worker"]["heartbeat_age_seconds"] is None,"board must not fake a worker heartbeat")
    require(offline["counts"]=={"done":1,"running":0,"queued":4,"blocked":0,"human":1,"total":6,"safe_remaining":4},f"offline board counts regression: {offline['counts']}")
    require(offline["next_task"]["id"]=="T-902" and offline["planner_queue"][2]["queue_position"]==1,"board queue order regression")
    app.ingest_claude_worker_result(claude_result(task_id="T-902-B",pinned_task_id="T-902-B",result="blocked",commit="",commit_count=0,need="owner input"))
    app.claude_worker_heartbeat(app.ClaudeWorkerHeartbeat(task_id="T-902-A",status="running",branch="autopilot-ci",
        repo=f"https://ci:{app.FACTORY_CLAUDE_WORKER_TOKEN}@github.com/example/factoryos.git",last_error=f"leak {app.FACTORY_CLAUDE_WORKER_TOKEN}"))
    live=app.get_delegation_board()
    states={x["id"]:x["state"] for x in live["planner_queue"]}
    require(states=={"T-900":"done","T-901":"human","T-902":"queued","T-902-A":"running","T-902-B":"blocked","T-903":"queued"},f"board task state regression: {states}")
    require(live["counts"]=={"done":1,"running":1,"queued":2,"blocked":1,"human":1,"total":6,"safe_remaining":4},f"live board counts regression: {live['counts']}")
    require(live["worker"]["connection"]=="online" and live["active_task"]["id"]=="T-902-A" and live["worker"]["node"]["branch"]=="autopilot-ci","board worker state regression")
    require(live["hierarchy"]==[{"parent":"T-902","parent_is_task":True,"children":["T-902-A","T-902-B"],"done":0,"total":2}],"board hierarchy regression")
    require(next(x for x in live["planner_queue"] if x["id"]=="T-902-B")["dependencies_met"] is False,"board dependency regression")
    require(next(x for x in live["planner_queue"] if x["id"]=="T-902-B")["unmet_dependencies"]==["T-902-A"],"board unmet dependency regression")
    require([n["id"] for n in live["tree"]]==["T-900","T-901","T-902","T-903"],f"board tree roots regression: {[n['id'] for n in live['tree']]}")
    tree_parent=live["tree"][2]
    require([c["id"] for c in tree_parent["children"]]==["T-902-A","T-902-B"] and tree_parent["children_total"]==2 and tree_parent["children"][0]["depth"]==1
            and tree_parent["children"][0]["state"]=="running" and tree_parent["children"][0]["goal"]=="build the child across two lines"
            and tree_parent["children"][0]["done_criteria"]=="`python -m child_check` passes" and tree_parent["children"][0]["source"]=="ChatGPT"
            and tree_parent["children"][1]["depends"]==["T-902-A"] and tree_parent["children"][1]["source"]=="roadmap","board tree provenance regression")
    require(live["provenance"]=={"roadmap":4,"ChatGPT":2},f"board provenance count regression: {live['provenance']}")
    require(live["recent_results"][-1]["task_id"]=="T-902-B" and "pinned_task_id" not in live["recent_results"][-1],"board recent result regression")
    board_json=json.dumps(live)
    require(app.FACTORY_CLAUDE_WORKER_TOKEN not in board_json and app.FACTORY_SECRET not in board_json and "ci:" not in board_json and "token" not in board_json.lower(),"delegation board must never return worker tokens or secrets")
    app.claude_worker_runtime["last_seen"]=app.time.time()-app.FACTORY_CLAUDE_WORKER_TTL_SECONDS-5
    stale=app.get_delegation_board()
    require(stale["worker"]["connection"]=="stale" and stale["counts"]["running"]==0 and stale["counts"]["queued"]==3,"stale worker must not count as running")
finally:
    app._parse_roadmap_tasks,app.CLAUDE_WORKER_RESULTS_FILE=real_parse_roadmap,real_results_file
    app.claude_worker_runtime.clear();app.claude_worker_runtime.update(real_worker_runtime)
require(app.get_claude_code_status()["online"] is False,"delegation board fixture must not leave a live worker behind")
pair_hash=app._telegram_pair_code_hash("PAIR1234")
require(app._telegram_pair_code_matches("PAIR1234",pair_hash) is True,"Telegram pair-code verification regression")
require(app._telegram_pair_code_matches("WRONG",pair_hash) is False,"Telegram pair-code rejection regression")
require(app._telegram_public_status()["configured"] is False,"CI must not have a Telegram bot token")

brain=app.get_content_brain()
require(brain["summary"]["signals"]==0 and brain["summary"]["ideas"]==0,"fresh Content Brain fixture must be empty")
signal_payload=app.SignalCreate(title="Open-source firmware RE update",content="New reverse-engineering workflow details",url="https://example.com/re",source_type="url",topic="reverse engineering")
signal_result=app.ingest_source_signal(signal_payload)
require(signal_result["created"] is True and signal_result["duplicate"] is False,"first signal ingestion must create")
duplicate=app.ingest_source_signal(signal_payload)
require(duplicate["created"] is False and duplicate["duplicate"] is True,"signal deduplication regression")
signal_id=signal_result["signal"]["id"]
idea=app.create_content_idea(app.IdeaCreate(title="What changed in firmware reverse engineering?",topic="reverse engineering",angle="show the workflow delta",audience="embedded/security",why_now="new source signal",source_signal_ids=[signal_id],source_links=["https://example.com/re"],score=0.8))
require(idea["status"]=="generated" and signal_id in idea["source_signal_ids"],"Idea Queue provenance regression")
brain=app.get_content_brain()
require(brain["summary"]["signals"]==1 and brain["summary"]["ideas"]==1,"Content Brain counts regression")
parsed=app._parse_idea_candidates('[{"title":"A","score":0.8}]')
require(parsed and parsed[0]["title"]=="A","idea candidate parser regression")
obj=app._parse_json_object('```json\n{"decision":"shortlist","score":0.9}\n```')
require(obj["decision"]=="shortlist","Content Brain JSON object parser regression")
brain=app.get_content_brain()
require("adapters" in brain and "rss" in brain["adapters"],"source adapter registry missing")
require("verified" in brain["summary"] and "feeds_configured" in brain["summary"],"Content Brain summary fields missing")
for path,method in (("/guest","GET"),("/api/viewer-invite","GET"),("/health","GET"),("/api/version","GET"),("/api/status","GET"),("/api/release-readiness","GET"),("/api/intelligence","GET"),("/api/content-brain","GET"),("/api/content-brain/collect","POST"),("/api/content-brain/signals","POST"),("/api/content-brain/generate","POST"),("/api/content-brain/process","POST"),("/api/content-brain/ideas","POST"),("/api/content-brain/ideas/{idea_id}/status","POST"),("/api/media-adapters","GET"),("/api/jobs/{job_id}/content-package","GET"),("/api/jobs/{job_id}/content-package/generate","POST"),("/api/jobs/{job_id}/content-package/export.json","GET"),("/api/jobs/{job_id}/content-package/export.zip","GET"),("/api/jobs/{job_id}/variants","GET"),("/api/jobs/{job_id}/variants/generate","POST"),("/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}","POST"),("/api/jobs/{job_id}/variants/{variant_id}/select","POST"),("/api/handoffs/{run_id}/{artifact_id}","GET"),("/api/jobs/{job_id}/approve","POST"),("/api/jobs/{job_id}/reject","POST"),("/api/approval","GET"),("/api/jobs/{job_id}/approval/history","GET"),("/api/jobs/{job_id}/approval/quote/{component}","GET"),("/api/jobs/{job_id}/approval/regenerate","POST"),("/api/jobs/{job_id}/idea-link/{idea_id}","POST"),("/api/publisher-adapters","GET"),("/api/publishing","GET"),("/api/publishing/{publish_id}/schedule","POST"),("/api/publishing/{publish_id}/publish","POST"),("/api/publishing/{publish_id}/confirm","POST"),("/api/publishing/{publish_id}/refresh","POST"),("/api/publishing/run-due","POST"),("/api/analytics-adapters","GET"),("/api/performance","GET"),("/api/performance/{publish_id}","GET"),("/api/performance/snapshots","POST"),("/api/performance/{publish_id}/sync","POST"),("/api/self-improvement","GET"),("/api/workflow/active","GET"),("/api/experiments","GET"),("/api/improvements","POST"),("/api/improvements/{proposal_id}/experiment","POST"),("/api/experiments/{experiment_id}/assign","POST"),("/api/experiments/{experiment_id}/evaluate","POST"),("/api/experiments/{experiment_id}/rollout","POST"),("/api/experiments/{experiment_id}/rollback","POST"),("/api/experiments/{experiment_id}/reject","POST"),("/api/factory/autopilot","GET"),("/api/factory-cycles","GET"),("/api/factory-cycles","POST"),("/api/factory-cycles/{cycle_id}","GET"),("/api/factory-cycles/{cycle_id}/quote","GET"),("/api/factory-cycles/{cycle_id}/run","POST"),("/api/factory-cycles/{cycle_id}/sync","POST"),("/api/factory-cycles/{cycle_id}/learn","POST"),("/api/factory-cycles/{cycle_id}/next","POST"),("/api/discovery","GET"),("/api/discovery/candidates","POST"),("/api/discovery/collect","POST"),("/api/discovery/{candidate_id}/revideo","POST"),("/api/revideo","GET"),("/api/revideo","POST"),("/api/revideo/adapters","GET"),("/api/revideo/{project_id}","GET"),("/api/revideo/{project_id}/quote","GET"),("/api/revideo/{project_id}/analyze","POST"),("/api/revideo/{project_id}/create-job","POST"),("/api/revideo/{project_id}/render","POST"),("/api/media-jobs","GET"),("/api/media-jobs/{media_job_id}","GET"),("/api/media-jobs/{media_job_id}/refresh","POST"),("/api/media-jobs/{media_job_id}/callback","POST"),("/api/media-finisher/profiles","GET"),("/api/media-finisher","GET"),("/api/media-finisher/{edit_job_id}","GET"),("/api/jobs/{job_id}/media-finisher","POST"),("/api/media-finisher/{edit_job_id}/refresh","POST"),("/api/media-finisher/{edit_job_id}/archive","POST"),("/api/media-finisher/{edit_job_id}/callback","POST"),("/api/media-finisher/{edit_job_id}/rerun/{stage}","POST"),("/api/jobs/{job_id}/media-finisher/upload","POST"),("/media-source/{upload_id}","GET"),("/media-archive/{archive_id}","GET"),("/api/jobs/{job_id}/agents/{agent_name}/rerun","POST")):
    require(route_exists(path,method),f"route missing: {method} {path}")

for path,method in (
    ("/api/integrations","GET"),
    ("/api/integrations/disconnect-all","POST"),
    ("/api/integrations/{provider}/disconnect","POST"),
    ("/api/integrations/{provider}/connect","POST"),
    ("/api/integrations/{provider}/switch","POST"),
):
    require(route_exists(path,method),f"Integration portability route missing: {method} {path}")

for path,method in (
    ("/api/factory/telegram/status","GET"),
    ("/api/factory/telegram/pairing/start","POST"),
    ("/api/factory/telegram/test","POST"),
    ("/api/integrations/telegram/webhook","POST"),
    ("/api/factory/telegram/bridge/notify","POST"),
    ("/api/factory/telegram/bridge/inbox","GET"),
    ("/api/factory/claude-code/status","GET"),
    ("/api/factory/claude-code/worker-token","GET"),
    ("/api/claude-worker/heartbeat","POST"),
    ("/api/claude-worker/task-result","POST"),
):
    require(route_exists(path,method),f"Telegram route missing: {method} {path}")

created=asyncio.run(app.create_job(app.JobCreate(title="CI smoke job",brief="Zero-spend regression fixture",presenter="Faceless",format="Short only",language="English",outputs=1)))
job_id=created["id"]
require(app.get_job(job_id) is not None,"smoke job was not persisted")
require(app.get_job_worker_results(job_id)=={},"new job should not invent worker outputs")
require(app.get_job_handoffs(job_id)==[],"new job should not invent handoffs")
worker_run=app.start_agent_run("Scout",job_id,"research",model="simulation-v4.2")
worker_artifact=app.save_artifact("Scout","analysis","CI worker evidence",{"summary":"structured object output","items":[1,2,3]},job_id=job_id,run_id=worker_run,meta={"mode":"demo","model":"simulation-v4.2"})
app.finish_agent_run(worker_run,status="completed",input_tokens=12,output_tokens=8,cost_usd=0.0,meta={"mode":"demo"})
worker_results=app.get_job_worker_results(job_id)
require("Scout" in worker_results,"selected-job worker result missing")
require("structured object output" in worker_results["Scout"]["content"],"worker result must expose full normalized content")
require(worker_results["Scout"]["artifact_count"]>=1 and worker_results["Scout"]["run"]["output_tokens"]==8,"worker accounting/evidence regression")
# T-531 Worker Results contract: input/action/status/output/artifacts/duration/tokens/cost, unknown → None.
rep=worker_results["Scout"]["report"]
require(set(rep)>={"input","action","status","output","artifacts","duration_ms","tokens","cost_usd","unavailable"},"worker report contract shape changed")
require(rep["status"]=="completed" and rep["input"]=={"count":0,"sources":[]} and rep["action"]["stage"]=="research" and rep["action"]["mode"]=="demo","worker report input/action/status regression")
require(rep["output"]["title"]=="CI worker evidence" and rep["artifacts"]["count"]==1 and rep["artifacts"]["items"][0]["id"]==worker_artifact,"worker report output/artifacts regression")
require(isinstance(rep["duration_ms"],int) and rep["tokens"]=={"input":12,"output":8,"total":20} and rep["cost_usd"]==0.0 and rep["unavailable"]==[],"measured demo run must expose duration, tokens and cost")
agent_detail=app.agent_detail("Scout")
require(agent_detail["selected_job_id"]==job_id and agent_detail["selected_job_result"]["id"]==worker_artifact,"agent drawer must expose selected-job result first")
center=app.get_job_error_center(job_id)
require(set(center)=={"summary","incidents"},"error center shape changed")
require(center["summary"]["open"]==0,"new job should not have incidents")
approval=asyncio.run(app.approve(job_id))
require(approval["ok"] is False,"approval must be gated until waiting_approval")
legacy=asyncio.run(app.create_job(app.JobCreate(title="Legacy incomplete review",brief="No package fixture",presenter="Faceless",format="Short only",language="English",outputs=1)))
legacy_id=legacy["id"]
con=app.db();con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(app.ts(),legacy_id));con.commit();con.close()
legacy_item=next(x for x in app.get_approval_queue()["items"] if x["job"]["id"]==legacy_id)
require(legacy_item["legacy_incomplete"] is True and legacy_item["review_ready"] is False,"legacy approval item must be explicitly marked incomplete")
contract_job=asyncio.run(app.create_job(app.JobCreate(title="CI worker contract",brief="Unknown-value fixture",presenter="Faceless",format="Short only",language="English",outputs=1)))["id"]
contract_seed=app.save_artifact("Scout","analysis","CI contract seed","seed",job_id=contract_job)
running_run=app.start_agent_run("Researcher",contract_job,"research",model="simulation-v4.2")
app.attach_run_inputs(running_run,[{"id":contract_seed,"agent":"Scout"}])
app.save_artifact("Researcher","analysis","CI partial research","partial",job_id=contract_job,run_id=running_run,meta={"mode":"live_llm"})
app.save_artifact("Tech Verifier","analysis","CI orphan artifact","no run record",job_id=contract_job)
failed_run=app.start_agent_run("Angle Strategist",contract_job,"angle",model="gpt-ci")
app.save_artifact("Angle Strategist","analysis","CI failed attempt","partial",job_id=contract_job,run_id=failed_run,meta={"mode":"live_llm"})
app.finish_agent_run(failed_run,status="failed",error="Timed out",meta={"mode":"live_llm"})
reports={k:v["report"] for k,v in app.get_job_worker_results(contract_job).items()}
running=reports["Researcher"]
require(running["status"]=="running" and running["input"]["count"]==1 and running["input"]["sources"][0]["agent"]=="Scout","running worker must expose its consumed input")
require(running["duration_ms"] is None and running["tokens"] is None and running["cost_usd"] is None and running["unavailable"]==["duration_ms","tokens","cost_usd"],"unfinished run must not fabricate duration/tokens/cost")
orphan=reports["Tech Verifier"]
require(orphan["status"]=="artifact_only" and orphan["input"] is None and orphan["action"] is None and orphan["unavailable"]==["input","action","duration_ms","tokens","cost_usd"],"artifact without run must render run fields as unavailable")
failed=reports["Angle Strategist"]
require(failed["status"]=="failed" and failed["error"]=="Timed out" and isinstance(failed["duration_ms"],int) and failed["tokens"] is None and failed["cost_usd"] is None,"failed live call with no recorded usage must report spend as unavailable, not 0")
# T-532 live pipeline handoff trace: ordered source artifact -> run -> output -> downstream runs from persisted evidence only.
require(app.get_job_flow(legacy_id)["hops"]==[] and app.get_job_flow(legacy_id)["live"] is False,"job without runs must not invent a flow")
flow_job=asyncio.run(app.create_job(app.JobCreate(title="CI flow trace",brief="Handoff fixture",presenter="Faceless",format="Short only",language="English",outputs=1)))["id"]
flow_seed=app.save_artifact("Scout","analysis","CI flow brief","FLOW-SEED-CONTENT-NOT-IN-TRACE",job_id=flow_job)
def flow_run(agent,stage,inputs,output=None,status=None,error=None):
    rid=app.start_agent_run(agent,flow_job,stage,model="simulation-v4.2")
    app.attach_run_inputs(rid,[{"id":a,"agent":src} for a,src in inputs])
    art=app.save_artifact(agent,"text",output,"FLOW-OUTPUT-CONTENT",job_id=flow_job,run_id=rid) if output else None
    if status:app.finish_agent_run(rid,status=status,error=error,meta={"mode":"demo"})
    return rid,art
r_research,a_research=flow_run("Researcher","research",[(flow_seed,"Scout")],"CI flow research","completed")
r_script,a_script=flow_run("Scriptwriter","script",[(a_research,"Researcher")],"CI flow script","completed")
r_visual,_=flow_run("Visual Director","visual",[(a_script,"Scriptwriter")])
r_voice,_=flow_run("Voice Agent","voice",[(a_script,"Scriptwriter")],status="failed",error="Timed out")
r_render,_=flow_run("Render Agent","render",[(a_script,"Scriptwriter")],status="failed",error="Missing required upstream artifacts: Voice Agent")
flow=app.get_job_flow(flow_job)
require([h["agent"] for h in flow["hops"]]==["Researcher","Scriptwriter","Visual Director","Voice Agent","Render Agent"] and [h["order"] for h in flow["hops"]]==[1,2,3,4,5],"flow hops must follow run start order")
require([h["state"] for h in flow["hops"]]==["done","done","running","failed","blocked"],f"flow run states regression: {[h['state'] for h in flow['hops']]}")
require(flow["counts"]=={"running":1,"done":2,"blocked":1,"failed":1,"queued":0,"unknown":0} and flow["live"] is True and flow["truncated"] is False,"flow counts/live regression")
first=flow["hops"][0]
require(first["inputs"]==[{"artifact_id":flow_seed,"title":"CI flow brief","kind":"analysis","source_agent":"Scout","source_run_id":None,"origin":"source"}],"seed artifact must be the trace source")
require(flow["sources"]==[{"artifact_id":flow_seed,"title":"CI flow brief","kind":"analysis","agent":"Scout","origin":"source"}],"flow sources regression")
require([o["artifact_id"] for o in first["outputs"]]==[a_research] and [(d["agent"],d["state"]) for d in first["downstream"]]==[("Scriptwriter","done")],"run output -> downstream edge regression")
require([(d["agent"],d["state"]) for d in flow["hops"][1]["downstream"]]==[("Visual Director","running"),("Voice Agent","failed"),("Render Agent","blocked")],"fan-out downstream edges regression")
require(flow["hops"][2]["outputs"]==[] and flow["hops"][2]["finished_at"] is None and flow["hops"][2]["error"]=="","running hop must not invent output or completion")
require(flow["hops"][3]["error"]=="Timed out" and flow["hops"][4]["error"].startswith("Missing required upstream"),"failed/blocked hops must carry their recorded error")
require([(e["from_agent"],e["to_agent"],e["origin"]) for e in flow["edges"]]==[("Scout","Researcher","source"),("Researcher","Scriptwriter","run"),("Scriptwriter","Visual Director","run"),("Scriptwriter","Voice Agent","run"),("Scriptwriter","Render Agent","run")],"flow edge order regression")
require(all(e["from_run"] in (None,r_research,r_script) for e in flow["edges"]) and flow["edges"][1]["from_run"]==r_research and flow["edges"][1]["to_run"]==r_script,"flow edges must link exact runs")
require("CONTENT" not in json.dumps(flow),"flow trace must not carry artifact content")
window=app.get_job_flow(flow_job,limit=2)
require([h["agent"] for h in window["hops"]]==["Voice Agent","Render Agent"] and window["truncated"] is True and window["hops"][0]["inputs"][0]["origin"]=="earlier","flow window must keep latest runs and mark out-of-window producers as earlier")
require('"selectedJobFlow": get_job_flow(sid)' in inspect.getsource(app.status),"status payload must expose the selected job flow")

# v4.4 Viral Discovery — factual metric persistence, dedup and Revideo handoff.
dc_payload=app.DiscoveryCandidateCreate(
    platform="youtube",source_url="https://www.youtube.com/shorts/ciOutlier01",external_id="ciOutlier01",
    title="CI breakout AI tools Short",creator="CI Creator",thumbnail_url="https://example.com/thumb.jpg",
    topic="AI automation tools",language="en",content_type="short",published_at="2026-10-20T10:00:00Z",
    duration_sec=42,views=108273,vph=123.4,engagement_rate=0.029,breakout_score=53.09,
    transcript="A source transcript with hook, examples, mechanism and CTA. It is only source material and must not be copied.",
    metrics={"likeCount":3100},provenance={"source":"ci_fixture"}
)
dc=app.ingest_discovery_candidate(dc_payload,"ci_fixture")
require(dc["created"] is True and dc["candidate"]["views"]==108273 and dc["candidate"]["breakout_score"]==53.09,
        "discovery factual metric persistence regression")
require(dc["candidate"]["platform"]=="youtube" and dc["candidate"]["source_url"]==dc_payload.source_url,
        "discovery source identity regression")
require(bool(dc["candidate"]["discovered_at"]) and bool(dc["candidate"]["updated_at"]),
        "discovery capture timestamps missing")
require(dc["candidate"]["metrics"].get("vph")==123.4 and dc["candidate"]["metrics"].get("engagement_rate")==0.029,
        "discovery factual metric evidence missing")
require(dc["candidate"]["provenance"].get("source")=="ci_fixture" and bool(dc["candidate"]["provenance"].get("ingested_at")),
        "discovery provenance/capture evidence regression")
dc_dup=app.ingest_discovery_candidate(dc_payload,"ci_fixture")
require(dc_dup["created"] is False and dc_dup["candidate"]["id"]==dc["candidate"]["id"],"discovery dedup regression")

rank_tie_ids=[]
for suffix in ("A","B"):
    ranked=app.ingest_discovery_candidate(app.DiscoveryCandidateCreate(
        platform="tiktok",source_url=f"https://www.tiktok.com/@ci/video/rank{suffix}",external_id=f"rank{suffix}",
        title=f"Ranking tie {suffix}",topic="AI automation tools",content_type="short",
        views=5000,vph=80.0,engagement_rate=0.02,breakout_score=10.0,
        provenance={"source":"ranking_fixture"}
    ),"ranking_fixture")
    rank_tie_ids.append(ranked["candidate"]["id"])
missing_rank=app.ingest_discovery_candidate(app.DiscoveryCandidateCreate(
    platform="instagram",source_url="https://www.instagram.com/reel/ciMissingMetrics",external_id="ciMissingMetrics",
    title="Missing metric candidate",topic="AI automation tools",content_type="short",
    provenance={"source":"ranking_fixture"}
),"ranking_fixture")
con=app.db();con.execute("UPDATE discovery_candidates SET discovered_at=? WHERE id IN (?,?)",
                         ("2026-10-20T12:00:00+00:00",rank_tie_ids[0],rank_tie_ids[1]));con.commit();con.close()
discovery=app.get_discovery_candidates()
ranked_ids=[x["id"] for x in discovery["candidates"]]
require(ranked_ids.index(dc["candidate"]["id"]) < ranked_ids.index(rank_tie_ids[0]),"higher factual breakout evidence must rank first")
require([x for x in ranked_ids if x in rank_tie_ids]==sorted(rank_tie_ids,reverse=True),
        "Discovery factual tie-break must be deterministic")
missing_item=next(x for x in discovery["candidates"] if x["id"]==missing_rank["candidate"]["id"])
require(missing_item["ranking_evidence"]["metrics"]=={} and set(missing_item["ranking_evidence"]["missing_metrics"])==set(app.DISCOVERY_RANK_FIELDS),
        "missing Discovery metrics must stay missing instead of being imputed")
require(ranked_ids.index(rank_tie_ids[0]) < ranked_ids.index(missing_rank["candidate"]["id"]),
        "measured factual evidence must rank ahead of a metric-empty candidate")
require(discovery["ranking"]["method"]=="factual_lexicographic","Discovery ranking method must be explicit")
require(discovery["summary"]["candidates"]>=1 and discovery["adapter"]["configured"] is False,"discovery dashboard/adapter regression")
require(discovery["measurement_note"].startswith("views"),"discovery measurement honesty note missing")
dc_rev=app.discovery_candidate_to_revideo(dc["candidate"]["id"],"English")
require(dc_rev["created"] is True and dc_rev["project"]["source_url"]==dc["candidate"]["source_url"],"discovery → Revideo handoff regression")
require(dc_rev["project"]["transcript"].startswith("A source transcript"),"discovery transcript was not preserved")
dc_after=app.get_discovery_candidate(dc["candidate"]["id"])
require(dc_after["status"]=="sent_to_revideo" and dc_after["revideo_project_id"]==dc_rev["project"]["id"],"discovery linkage regression")
dc_ready=asyncio.run(app.run_revideo_analysis(dc_rev["project"]["id"],"English"))
require(dc_ready["status"]=="ready","Discovery-sourced Revideo must reach a deterministic ready rewrite")
dc_prod=app.create_revideo_production_job(dc_rev["project"]["id"])
require(dc_prod["created"] is True and dc_prod["job"]["id"],"Discovery → Revideo → production handoff failed")
dc_project=app.get_revideo_project(dc_rev["project"]["id"])
require(dc_project["status"]=="in_production" and dc_project["job_id"]==dc_prod["job"]["id"],
        "Discovery-sourced Revideo production linkage regression")
require(dc_project["provenance"].get("discovery_candidate_id")==dc["candidate"]["id"],
        "Discovery candidate provenance was lost before production")
require(dc_project["provenance"].get("discovery_metrics",{}).get("vph")==123.4,
        "Discovery performance evidence was lost before production")
require(bool(dc_project.get("source_signal_id")) and bool(dc_project.get("idea_id")),
        "Discovery → Revideo production must preserve source/idea lineage")

# v5.1 T-513 — deterministic zero-spend Discovery → Revideo → Package → Finisher → HUMAN APPROVAL.
dc_job_id=dc_prod["job"]["id"]
dc_variants=asyncio.run(app.run_variant_pipeline(dc_job_id,3))
require(dc_variants["summary"]["selected"]==1 and dc_variants["summary"]["variants"]==3,
        "semi-autonomous Discovery flow must build three deterministic production variants")
dc_package=asyncio.run(app.generate_content_package(dc_job_id))
require(dc_package["status"]=="ready" and dc_package["package"]["final_script"],
        "semi-autonomous Discovery flow must build a ready Content Package")
dc_raw_url="https://example.com/discovery-source-render.mp4"
app.save_artifact("Render Agent","video","Discovery CI raw render","",job_id=dc_job_id,url=dc_raw_url,
                  mime_type="video/mp4",meta={"fixture":True,"source":"T-513"})
dc_publish_before=app._publishing_summary()
dc_orig_endpoint,dc_orig_spawn=app.FACTORY_MEDIA_FINISHER_ENDPOINT,app._spawn_media_finisher_submit
app.FACTORY_MEDIA_FINISHER_ENDPOINT="https://ci.invalid/finish"
app._spawn_media_finisher_submit=lambda edit_job_id: None
try:
    dc_edit=app.start_media_finisher(dc_job_id,app.MediaFinisherStartRequest(
        profile_id="revideo_finish",profile_version=1,platform="reels",input_url=dc_raw_url,
        edit_full_video=True,split_shortform=False,add_captions=True,add_animation=True,
        smart_graphics=True,max_short_clips=1,confirm_external_cost=True
    ))
    dc_edit_id=dc_edit["edit_job"]["id"]
    dc_report={
      "transcript_words":[{"word":"Discovery","start":0.0,"end":0.4},{"word":"rewrite","start":0.4,"end":0.8}],
      "cut_list":[],"caption_timeline":[{"start":0.0,"end":0.8,"words":["Discovery","rewrite"]}],
      "motion_timeline":[],"graphics_timeline":[],"shorts_manifest":{"enabled":False,"clips":[]},
      "audio_report":{"voice_lufs":-14.0},"safe_zone_report":{"violations":[]},
      "edit_summary":{"duration_before_sec":12.0,"duration_after_sec":11.5,
                      "options":{"edit_full_video":True,"split_shortform":False},"human_review_required":True}
    }
    dc_finished=app._finalize_edit_job(dc_edit_id,"completed","https://example.com/discovery-finished.mp4",
                                       "ci-t513-finisher","",{"status":"completed"},dc_report,0.0,11.5)
finally:
    app.FACTORY_MEDIA_FINISHER_ENDPOINT,app._spawn_media_finisher_submit=dc_orig_endpoint,dc_orig_spawn
require(dc_finished["status"]=="ready","semi-autonomous Discovery Media Finisher fixture must reach ready")
require(app.get_job(dc_job_id)["status"]=="waiting_approval",
        "semi-autonomous Discovery flow must stop at HUMAN APPROVAL")
dc_review=app._media_review_state(dc_job_id)
require(dc_review["required"] is True and dc_review["ready"] is True and
        (dc_review["artifact"] or {}).get("url")=="https://example.com/discovery-finished.mp4",
        "semi-autonomous Discovery flow must expose the exact finished media for human review")
require(app._publishing_summary()==dc_publish_before,
        "semi-autonomous Discovery flow must never publish or create a publish item before human approval")
require(any(x["job"]["id"]==dc_job_id for x in app.get_approval_queue()["items"]),
        "semi-autonomous Discovery flow must enter the Approval Studio queue")
dc_project_after=app.get_revideo_project(dc_rev["project"]["id"])
require(dc_project_after["provenance"].get("discovery_candidate_id")==dc["candidate"]["id"],
        "Discovery provenance must survive through the Media Finisher approval boundary")
manual_collect=app.collect_discovery_candidates("AI automation",5,"short","en")
require(manual_collect["created_count"]==0 and manual_collect["adapter"]=="manual_intake","unconfigured discovery provider must not invent candidates")

# v4.3 Revideo MVP — zero-spend original rewrite + provenance + production handoff.
rv=app.create_revideo_project(app.RevideoCreateRequest(
    source_url="https://example.com/public-video",
    source_title="Public explainer source",
    topic="AI interface adoption",
    transcript="This source explains a product launch with a strong opening, then context, mechanism, evidence and a final takeaway. The exact wording belongs to the source and must not be copied.",
    source_notes="CI fixture contains no claim of external verification.",
    language="English",
))
require(rv["status"]=="draft" and rv["source_url"].startswith("https://"),"Revideo project persistence regression")
rv_quote=app._revideo_quote(rv)
require(rv_quote["paid_calls_possible"] is False and rv_quote["estimated_max_usd"]==0.0,"CI Revideo must remain zero-spend")
rv_ready=asyncio.run(app.run_revideo_analysis(rv["id"],"English"))
require(rv_ready["status"]=="ready","demo Revideo rewrite must pass originality guard")
require(rv_ready["analysis"].get("source_hook_pattern") and rv_ready["rewrite"].get("original_script"),"Revideo analysis/rewrite artifacts missing")
require(rv_ready["originality"]["passed"] is True and rv_ready["originality"]["five_word_shingle_overlap"]<0.20,"Revideo originality guard regression")
rv_job=app.create_revideo_production_job(rv["id"])
require(rv_job["created"] is True and rv_job["job"]["id"],"Revideo production handoff failed")
rv_project=app.get_revideo_project(rv["id"])
require(rv_project["status"]=="in_production" and rv_project["job_id"]==rv_job["job"]["id"],"Revideo job linkage regression")
rv_worker=app.get_job_worker_results(rv_job["job"]["id"])
require("Researcher" in rv_worker and "Editor" in rv_worker,"Revideo worker evidence must be visible on production job")
require(rv_project["source_signal_id"] and rv_project["idea_id"],"Revideo provenance links missing")
rv_registry=app.get_revideo_adapter_registry()
require(rv_registry["transcript"]["manual_supported"] is True,"manual transcript baseline missing")
require(rv_registry["video"]["configured"] is False,"CI must not claim a configured video provider")

# v4.4 async media-job lifecycle — zero-spend provider contract regression.
media_job_id=str(uuid.uuid4())
media_now=app.ts()
con=app.db();con.execute("""INSERT INTO media_jobs(
    id,revideo_project_id,job_id,provider,provider_job_id,status,media_url,error,
    request_json,response_json,created_at,updated_at,completed_at
) VALUES(?,?,?,?,?,'queued','','',?,'{}',?,?,NULL)""",(
    media_job_id,rv["id"],rv_job["job"]["id"],"ci-video-provider","",
    json.dumps({"fixture":True}),media_now,media_now
));con.commit();con.close()
media_processing=app._finalize_media_job(media_job_id,"processing",provider_job_id="ci-provider-task-1",response={"status":"processing"})
require(media_processing["status"]=="processing" and media_processing["provider_job_id"]=="ci-provider-task-1",
        "async media job processing transition regression")
media_ready=app._finalize_media_job(media_job_id,"completed",media_url="https://example.com/generated-ci-video.mp4",
                                    response={"status":"completed","video_url":"https://example.com/generated-ci-video.mp4"})
require(media_ready["status"]=="ready" and media_ready["media_url"].endswith("generated-ci-video.mp4"),
        "async media job ready transition regression")
rv_with_media=app.get_revideo_project(rv["id"])
require(rv_with_media["media"]["url"].endswith("generated-ci-video.mp4"),"ready media must persist on Revideo project")
require(rv_with_media["media_job"]["id"]==media_job_id and rv_with_media["media_job"]["status"]=="ready",
        "Revideo project must expose latest media job")
rv_media_worker=app.get_job_worker_results(rv_job["job"]["id"])
require("Render Agent" in rv_media_worker and "generated-ci-video.mp4" in rv_media_worker["Render Agent"]["url"],
        "ready media must be visible as Render Agent worker evidence")

# v3.40 zero-spend variant pipeline: CI clears provider key, so this exercises demo contracts only.
variant_result=asyncio.run(app.run_variant_pipeline(job_id,3))
require(variant_result["summary"]["variants"]==3,"variant pipeline must create three candidates")
require(variant_result["summary"]["selected"]==1,"variant pipeline must select exactly one candidate")
require(variant_result["summary"]["rejected"]==2,"non-selected demo variants must remain comparable")
require(app.validate_stage_outputs(job_id,"script")["ok"] is True,"script-stage variant workers must persist artifacts")
selected=[x for x in variant_result["variants"] if x["status"]=="selected"][0]
require(selected["edited_script"],"selected variant must keep an edited script")
require("fact_check" in selected and "qa" in selected and "provenance" in selected,"variant trace fields missing")
normalized=app._normalize_qa_findings([
    {"type":"weak_hook","severity":"warning","message":"Too generic","evidence":"opening"},
    {"type":"invented_type","severity":"critical","message":"ignore me"}
])
require(len(normalized)==1 and normalized[0]["type"]=="weak_hook","structured QA finding normalization regression")
manual=app.select_production_variant(job_id,variant_result["variants"][1]["id"])
require(manual["summary"]["selected"]==1,"manual variant selection must preserve one winner")

# v3.50 zero-spend Content Package: selected variant becomes a complete traceable short-form bundle.
package_result=asyncio.run(app.generate_content_package(job_id))
require(package_result["status"]=="ready","Content Package must be ready after demo build")
package=package_result["package"]
for field in app.CONTENT_PACKAGE_REQUIRED_FIELDS:
    require(field in package,f"Content Package missing {field}")
require(package["final_script"] and package["hook"],"Content Package must preserve selected script and hook")
require(len(package["scenes"])>=3,"Content Package must include a scene breakdown")
require("-->" in package["subtitles_srt"],"Content Package must include valid-looking SRT timings")
require(package["voice_over"],"Content Package must include voice-over text")
require(isinstance(package["source_list"],list),"Content Package source list must be traceable")
require("package_generation_usd" in package["production_cost"] and "job_total_measured_usd" in package["production_cost"],"Content Package cost aggregation missing")
visual_inputs=app.collect_agent_inputs(job_id,"Visual Director")
require(not visual_inputs["missing"] and visual_inputs["artifacts"][0]["agent"]=="Content Packager","downstream visual stage must consume the Content Package manifest")
adapters=app.get_media_adapter_registry()
require({x["kind"] for x in adapters["adapters"]}=={"tts","image","video","stock","manual"},"media adapter contract regression")

# v4.5 AI Media Finisher — zero-spend async contract, guide-derived profile and approval boundary.
profiles=app.get_edit_profiles()
profile_ids={x["id"] for x in profiles}
require({"talking_head_fast","generated_visual","revideo_finish"}.issubset(profile_ids),"Media Finisher default profiles missing")
talking=app.get_edit_profile("talking_head_fast",1)
require(talking["config"]["speech_cleanup"]["pause_threshold_sec"]==0.4,"guide pause threshold profile regression")
require(app.MediaFinisherStartRequest().compute_target=="auto","Media Finisher compute target default regression")
require(talking["config"]["captions"]["min_words"]==1 and talking["config"]["captions"]["max_words"]==3,"guide caption grouping regression")
require(talking["config"]["safe_zones"]["top"]==0.12 and talking["config"]["safe_zones"]["bottom"]==0.20 and talking["config"]["safe_zones"]["right"]==0.12,"guide safe-zone profile regression")
fin_registry=app.get_media_finisher_registry()
require(fin_registry["configured"] is False and fin_registry["async_jobs"] is True,"CI must not claim a live Media Finisher provider")
require("local_booster" in fin_registry and fin_registry["local_booster"]["online"] is False,"Local Booster registry contract regression")
require(app.MediaFinisherStartRequest().compute_target=="auto","Media Finisher compute target default regression")
require(fin_registry["uploads_enabled"] is True and fin_registry["upload_max_bytes"]>=10*1024*1024,"Media Finisher upload contract regression")
orig_finisher_base,orig_finisher_status=app.FACTORY_MEDIA_FINISHER_ENDPOINT,app.FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT
app.FACTORY_MEDIA_FINISHER_ENDPOINT="finisher.internal:10000"
app.FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT=""
require(app._media_finisher_submit_endpoint()=="http://finisher.internal:10000/jobs","Render private host submit endpoint normalization regression")
require(app._media_finisher_status_base()=="http://finisher.internal:10000/jobs","Render private host status fallback regression")
app.FACTORY_MEDIA_FINISHER_ENDPOINT,app.FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT=orig_finisher_base,orig_finisher_status
require(len(app._media_upload_signature("ci-upload"))==64,"Media source signature regression")
require(app.get_media_finisher_pilot()["status"]=="disabled","CI must never auto-run the real v4.5 Media Finisher pilot")
require(callable(app.time.monotonic),"v4.5 pilot clock dependency regression")

raw_video=app.save_artifact("Render Agent","video","CI raw media","",job_id=job_id,url="https://example.com/raw-ci.mp4",mime_type="video/mp4",meta={"fixture":True})
signed_ci_url="https://factory.example/media-source/ci-upload?token="+app._media_upload_signature("ci-upload")
signed_artifact=app.save_artifact("AI Media Finisher","video","CI signed upload","",job_id=job_id,url=signed_ci_url,mime_type="video/mp4",meta={"fixture":True})
resolved_url,resolved_artifact,_=app._resolve_finisher_input(job_id,signed_ci_url,"")
require(resolved_url==signed_ci_url and resolved_artifact==signed_artifact,"uploaded raw artifact provenance regression")
publish_before=app._publishing_summary()
orig_finish_endpoint=app.FACTORY_MEDIA_FINISHER_ENDPOINT
orig_external_json=app._external_json
orig_finisher_spawn=app._spawn_media_finisher_submit
app.FACTORY_MEDIA_FINISHER_ENDPOINT="https://ci.invalid/finish"
app._spawn_media_finisher_submit=lambda edit_job_id: None
finisher_payloads=[]
finisher_attempts=[0]
def fake_finisher_provider(url,method="GET",payload=None,token=""):
    require(method=="POST","Media Finisher CI provider must receive POST")
    finisher_attempts[0]+=1
    if finisher_attempts[0]==1:
        raise TimeoutError("synthetic cold start")
    require(payload["guardrails"]["no_auto_publish"] is True,"Media Finisher guardrail missing")
    require(payload["profile"]["config"]["captions"]["max_words"]==3,"profile config not sent to finisher")
    finisher_payloads.append(payload)
    return {"id":"ci-finisher-task-1","status":"processing","stage":"queued","percent":1}
app._external_json=fake_finisher_provider
try:
    started=app.start_media_finisher(job_id,app.MediaFinisherStartRequest(
        profile_id="talking_head_fast",profile_version=1,platform="reels",input_url="https://example.com/raw-ci.mp4",
        edit_full_video=True,split_shortform=True,add_captions=True,add_animation=True,smart_graphics=True,max_short_clips=3,
        confirm_external_cost=True
    ))
    edit_id=started["edit_job"]["id"]
    require(started["edit_job"]["status"]=="queued" and not started["edit_job"]["provider_job_id"],"Media Finisher must return immediately while worker wakes")
    require((started["edit_job"]["response"] or {}).get("stage")=="waking_worker" and int((started["edit_job"]["response"] or {}).get("percent") or 0)>=1,
            "Media Finisher queued response must expose visible startup progress")
    orig_sleep=app.time.sleep
    app.time.sleep=lambda _seconds: None
    try:app._submit_media_finisher_background(edit_id)
    finally:app.time.sleep=orig_sleep
    submitted=app.get_edit_job(edit_id)
    require(submitted["status"]=="processing" and submitted["provider_job_id"]=="ci-finisher-task-1","Media Finisher background submit lifecycle regression")
    require(finisher_attempts[0]>=2,"Media Finisher cold-start timeout must retry automatically")
    submitted_opts=finisher_payloads[-1]["options"]
    require(submitted_opts["edit_full_video"] is True and submitted_opts["split_shortform"] is True,"Media Finisher full/short output options regression")
    require(submitted_opts["add_captions"] is True and submitted_opts["add_animation"] is True and submitted_opts["smart_graphics"] is True,"Media Finisher editing option regression")
    require(submitted_opts["shortform_targets"]==["youtube_shorts","instagram_reels"],"Media Finisher Shorts/Reels targets regression")
    report={
      "transcript_words":[{"word":"Hello","start":0.0,"end":0.3,"confidence":0.99}],
      "transcript_corrections":[],
      "cut_list":[{"start":1.0,"end":1.7,"reason":"silence>0.4s","pre_handle":0.1,"post_handle":0.15}],
      "caption_timeline":[{"start":0.0,"end":0.7,"words":["Hello","world"]}],
      "motion_timeline":[{"start":0.0,"type":"push_in","zoom":1.08}],
      "graphics_timeline":[{"start":1.2,"end":2.2,"text":"KEY POINT"}],
      "shorts_manifest":{"enabled":True,"selector":"transcript_density_v1","human_review_required":True,
                         "clips":[{"index":1,"start_sec":0.0,"end_sec":9.8,"duration_sec":9.8,
                                   "url":"https://example.com/short-01.mp4","targets":["youtube_shorts","instagram_reels"]}]},
      "audio_report":{"voice_lufs":-14.0,"music_relative_db":-20.0},
      "safe_zone_report":{"violations":[],"top":0.12,"bottom":0.20,"right":0.12},
      "edit_summary":{"duration_before_sec":12.0,"duration_after_sec":9.8,"human_review_required":True}
    }
    ready=app._finalize_edit_job(edit_id,"completed","https://example.com/final-ci.mp4","ci-finisher-task-1","",{"status":"completed"},report,0.0,9.8)
    require(ready["status"]=="ready" and ready["output_url"].endswith("final-ci.mp4"),"Media Finisher ready lifecycle regression")
    require({x["kind"] for x in ready["artifacts"]}>={"cut_list","caption_timeline","shorts_manifest","audio_report","safe_zone_report"},"Media Finisher evidence persistence regression")
    con=app.db()
    persisted_video_rows=[dict(x) for x in con.execute("SELECT * FROM artifacts WHERE job_id=? AND kind='video' ORDER BY created_at DESC",(job_id,)).fetchall()]
    qa_row=con.execute("SELECT * FROM artifacts WHERE job_id=? AND agent='QA Agent' AND title='Media Finisher QA gate' ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone()
    con.close()
    require(any(x.get("url")=="https://example.com/short-01.mp4" for x in persisted_video_rows),"Shorts/Reels clip artifact persistence regression")
    require(qa_row is not None,"Media Finisher must hand finished media to QA Agent")
    safe_latest=app._latest_job_video_artifact(job_id)
    require(safe_latest and safe_latest.get("url") not in {"https://example.com/final-ci.mp4","https://example.com/short-01.mp4"},"finished outputs must never become the next automatic input buffer")
    finished_worker=app.get_job_worker_results(job_id).get("AI Media Finisher")
    require(finished_worker and finished_worker["kind"]=="video" and finished_worker["url"].endswith("final-ci.mp4"),"finished media must be visible in Worker Evidence")
    review_job=app.get_job(job_id)
    require(review_job["status"]=="waiting_approval","finished media must return to human approval gate")
    media_review=app._media_review_state(job_id)
    require(media_review["required"] is True and media_review["ready"] is True,"finished media must be approval-ready")
    require((media_review["artifact"] or {}).get("url")=="https://example.com/final-ci.mp4","Approval must resolve the exact Media Finisher master")
    require(app._publishing_summary()==publish_before,"Media Finisher must not create a publish item")

    # v4.8 durable media: Render worker /files URLs are ephemeral and must be copied onto FactoryOS persistent storage.
    ephemeral_url="https://blackboxlab-media-finisher.onrender.com/files/ci-archive/final.mp4"
    con=app.db()
    con.execute("UPDATE artifacts SET url=? WHERE id=?",(ephemeral_url,ready["output_artifact_id"]))
    con.execute("UPDATE edit_jobs SET output_url=?,response_json=? WHERE id=?",(ephemeral_url,json.dumps({"durable_media_status":"queued"}),edit_id))
    con.commit();con.close()
    archive_blocked=app._media_review_state(job_id)
    require(archive_blocked["durability_required"] is True and archive_blocked["ready"] is False,
            "ephemeral Media Finisher output must be blocked until it is durably archived")
    orig_archive_download=app._download_media_to_path
    def fake_archive_download(source_url,dest):
        require(source_url==ephemeral_url,"durable archive must fetch the exact finished-media source URL")
        payload=b"factoryos-durable-media"*100
        dest.write_bytes(payload)
        return {"bytes":len(payload),"sha256":app.hashlib.sha256(payload).hexdigest(),"content_type":"video/mp4"}
    app._download_media_to_path=fake_archive_download
    try:
        archived=app._archive_edit_media(edit_id)
    finally:
        app._download_media_to_path=orig_archive_download
    require(archived["status"]=="ready" and archived["items"],"durable media archive lifecycle regression")
    durable_review=app._media_review_state(job_id)
    durable_url=(durable_review["artifact"] or {}).get("url") or ""
    require(durable_review["ready"] is True and durable_review["durability_ready"] is True,
            "approval must unlock only after durable media is ready")
    require("/media-archive/" in durable_url and "token=" in durable_url,
            "approval/publishing must use the signed FactoryOS durable media URL")
    con=app.db();archive_art=con.execute("SELECT meta_json FROM artifacts WHERE id=?",(ready["output_artifact_id"],)).fetchone();con.close()
    archive_meta=json.loads(archive_art["meta_json"])
    require(archive_meta["durable_media"] is True and archive_meta["source_url"]==ephemeral_url and len(archive_meta["archive_sha256"])==64,
            "durable archive provenance/hash regression")
    require(app._edit_media_archive_targets(edit_id)==[],"durable archive target discovery must clear archived master")
    short_ephemeral="https://blackboxlab-media-finisher.onrender.com/files/ci-archive/short-01.mp4"
    con=app.db()
    short_row=con.execute("SELECT id FROM artifacts WHERE job_id=? AND agent='AI Media Finisher' AND meta_json LIKE '%short_render%' ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone()
    con.execute("UPDATE artifacts SET url=? WHERE id=?",(short_ephemeral,short_row["id"]));con.commit();con.close()
    require(short_row["id"] in app._edit_media_archive_targets(edit_id),
            "short clips must still be discovered for durable archival after the master is already durable")
    # Lost temporary output repair is allowed only when the original raw upload still exists on FactoryOS persistent storage.
    upload_id="ci-repair-upload";stored_name=upload_id+".mp4"
    repair_payload=b"factoryos-persistent-raw"*100
    (app.MEDIA_UPLOAD_DIR/stored_name).write_bytes(repair_payload)
    (app.MEDIA_UPLOAD_DIR/f"{upload_id}.json").write_text(json.dumps({
        "upload_id":upload_id,"job_id":job_id,"filename":"repair.mp4","stored_name":stored_name,
        "content_type":"video/mp4","bytes":len(repair_payload),"created_at":app.ts()
    }),encoding="utf-8")
    repair_input=f"{app.FACTORY_PUBLIC_BASE_URL}/media-source/{upload_id}?token="+app._media_upload_signature(upload_id)
    con=app.db();con.execute("UPDATE edit_jobs SET input_url=? WHERE id=?",(repair_input,edit_id));con.commit();con.close()
    repair_edit=app.get_edit_job(edit_id)
    require(app._recoverable_persistent_finisher_input(repair_edit) is True,
            "lost-output repair must recognize a persistent signed raw upload")
    require(app._latest_ready_edit_for_job(job_id)==edit_id,
            "lost-output repair must identify the latest ready edit for a production job")

    rerun=app.rerun_media_finisher_stage(edit_id,"captions")
    require(rerun["edit_job"]["parent_edit_job_id"]==edit_id and rerun["edit_job"]["rerun_stage"]=="captions","targeted Media Finisher rerun lineage regression")
    rerun_id=rerun["edit_job"]["id"]
    rerun_ready=app._finalize_edit_job(rerun_id,"completed","https://example.com/final-ci-rerun.mp4","ci-finisher-task-2","",
                                       {"status":"completed"},report,0.0,9.8)
    require(rerun_ready["status"]=="ready","targeted rerun must complete before the newer render can be approved")

    # Direct user upload must be finishable without first building a Content Package.
    manual_job_id=str(uuid.uuid4())
    con=app.db()
    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(
        manual_job_id,"Manual raw v4.5 test","Direct uploaded talking-head video","render",
        "Human","Short only","English",1,"idle",65,app.ts(),app.ts()
    ))
    con.commit();con.close()
    manual_url="https://factory.example/media-source/manual-ci?token="+app._media_upload_signature("manual-ci")
    app.save_artifact("AI Media Finisher","video","Raw video upload","",job_id=manual_job_id,url=manual_url,
                      mime_type="video/mp4",meta={"component":"raw_upload","upload_id":"manual-ci","fixture":True})
    direct=app.start_media_finisher(manual_job_id,app.MediaFinisherStartRequest(
        profile_id="talking_head_fast",profile_version=1,platform="reels",input_url="",confirm_external_cost=True
    ))
    require(direct["edit_job"]["status"]=="queued","direct raw upload must queue immediately while submit runs asynchronously")
    direct_id=direct["edit_job"]["id"]
    app._submit_media_finisher_background(direct_id)
    direct= {"edit_job":app.get_edit_job(direct_id)}
    require(direct["edit_job"]["status"]=="processing","direct raw upload Media Finisher background submit regression")
    direct_payload=finisher_payloads[-1]
    require(direct_payload["package_mode"]=="manual_raw_upload","direct upload must use manual raw package mode")
    require(direct_payload["content_package"]["_factoryos_manual_raw"] is True,"direct upload marker missing")
    require(direct_payload["guardrails"]["manual_raw_upload_transcript_exact_graphics"] is True,
            "direct upload graphics must be constrained to exact transcript words")

    split_only_report={
      "transcript_words":[
        {"word":"This","start":0.0,"end":0.2},{"word":"is","start":0.2,"end":0.3},
        {"word":"the","start":0.3,"end":0.4},{"word":"owner","start":0.4,"end":0.7},
        {"word":"uploaded","start":0.7,"end":1.0},{"word":"video","start":1.0,"end":1.3}
      ],
      "caption_timeline":[],"graphics_timeline":[],"safe_zone_report":{"violations":[]},
      "shorts_manifest":{"enabled":True,"clips":[{"index":1,"start_sec":0.0,"end_sec":8.0,"url":"https://example.com/manual-short-01.mp4"}]},
      "edit_summary":{"duration_before_sec":30.0,"duration_after_sec":28.0,
                      "options":{"edit_full_video":False,"split_shortform":True}}
    }
    app._finalize_edit_job(direct_id,"completed","https://example.com/internal-master.mp4","ci-finisher-task-1","",
                           {"status":"completed"},split_only_report,0.0,28.0)
    con=app.db()
    internal_master_artifact=con.execute("SELECT id FROM artifacts WHERE job_id=? AND url='https://example.com/internal-master.mp4'",(manual_job_id,)).fetchone()
    split_clip_artifact=con.execute("SELECT id FROM artifacts WHERE job_id=? AND url='https://example.com/manual-short-01.mp4'",(manual_job_id,)).fetchone()
    split_qa=con.execute("SELECT id FROM artifacts WHERE job_id=? AND agent='QA Agent' AND title='Media Finisher QA gate'",(manual_job_id,)).fetchone()
    con.close()
    require(internal_master_artifact is None,"split-only mode must not expose the internal master as a deliverable")
    require(split_clip_artifact is not None and split_qa is not None,"split-only Shorts/Reels must persist clips and hand them to QA")
    manual_package=app.get_content_package(manual_job_id)
    require(manual_package["status"]=="ready" and manual_package["package"]["_factoryos_manual_raw"] is True,
            "direct raw upload must auto-create a zero-spend publish/approval package")
    require(manual_package["package"]["final_script"].startswith("This is the owner uploaded video"),
            "manual raw publish pack must derive script text from persisted transcript evidence")
    manual_variants=app.get_job_variants(manual_job_id)
    require(manual_variants["summary"]["selected"]==1 and manual_variants["summary"]["variants"]==1,
            "direct raw upload must create one traceable selected source variant")
    manual_review=app._media_review_state(manual_job_id)
    require(manual_review["ready"] is True and (manual_review["artifact"] or {}).get("url")=="https://example.com/manual-short-01.mp4",
            "split-only raw upload must surface the exact short clip at approval")
    manual_approval=asyncio.run(app.approve(manual_job_id))
    require(manual_approval["ok"] is True,"direct raw upload must be approvable without running the normal idea/variant/package LLM pipeline")
    require((manual_approval["publish"].get("media") or {}).get("url")=="https://example.com/manual-short-01.mp4",
            "direct raw upload approval must bind the exact Shorts/Reels artifact")
    require((manual_approval["publish"].get("content_snapshot") or {}).get("title")=="Manual raw v4.5 test",
            "direct raw upload approval must freeze deterministic owner/job publishing metadata")

    unused_upload=app.save_artifact("AI Media Finisher","video","Unused raw upload","",job_id=manual_job_id,
                                    url="https://factory.example/media-source/unused-ci?token=fake",mime_type="video/mp4",
                                    meta={"component":"raw_upload","upload_id":"unused-ci","filename":"unused.mp4"})
    deleted=asyncio.run(app.delete_video_artifact(unused_upload))
    require(deleted["ok"] is True,"unused raw video delete endpoint regression")
    con=app.db();deleted_row=con.execute("SELECT id FROM artifacts WHERE id=?",(unused_upload,)).fetchone();con.close()
    require(deleted_row is None,"deleted raw video artifact must leave the active buffer")
finally:
    app._external_json=orig_external_json
    app._spawn_media_finisher_submit=orig_finisher_spawn
    app.FACTORY_MEDIA_FINISHER_ENDPOINT=orig_finish_endpoint

exports=app._package_export_files(package_result["package_record"])
for name in ("content-package.json","final-script.txt","voice-over.txt","subtitles.srt","scenes.json","publishing-metadata.json","sources.json","fact-check.json","media-brief.md"):
    require(name in exports,f"package export missing {name}")
app.select_production_variant(job_id,variant_result["variants"][0]["id"])
require(app.get_content_package(job_id)["status"]=="stale","changing selected variant must invalidate existing Content Package")
require(app.get_job(job_id)["stage"]=="script" and app.get_job(job_id)["status"]=="idle","changing selected variant must fence downstream stages back to script")

# v3.60 Approval Studio — deterministic/zero-spend regression.
asyncio.run(app.generate_content_package(job_id))
app.link_job_idea(job_id,idea["id"])
con=app.db();con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(app.ts(),job_id));con.commit();con.close()
queue=app.get_approval_queue()
require(any(x["job"]["id"]==job_id for x in queue["items"]),"approval queue must include waiting job")
require("estimated_model_cost_usd" in app._estimated_regeneration_cost("hook"),"cost-before-rerun quote missing")
stale_media=app._media_review_state(job_id)
require(stale_media["required"] is True and stale_media["ready"] is False and stale_media["source_binding_ok"] is False,
        "changing selected variant/package must invalidate previously finished media for approval")
blocked_stale=asyncio.run(app.approve(job_id))
require(blocked_stale["ok"] is False and "older Content Package" in blocked_stale["message"],
        "approval must block stale final media after package/variant change")
orig_rebind_endpoint,orig_rebind_spawn=app.FACTORY_MEDIA_FINISHER_ENDPOINT,app._spawn_media_finisher_submit
app.FACTORY_MEDIA_FINISHER_ENDPOINT="https://ci.invalid/finish"
app._spawn_media_finisher_submit=lambda edit_job_id: None
try:
    rebound=app.rerun_media_finisher_stage(rerun_id,"render")
    rebound_id=rebound["edit_job"]["id"]
    rebound_ready=app._finalize_edit_job(rebound_id,"completed","https://example.com/final-ci-current.mp4","ci-finisher-task-3","",
                                         {"status":"completed"},report,0.0,9.8)
    require(rebound_ready["status"]=="ready","current package/variant rerun must finish before approval")
finally:
    app.FACTORY_MEDIA_FINISHER_ENDPOINT,app._spawn_media_finisher_submit=orig_rebind_endpoint,orig_rebind_spawn
current_media=app._media_review_state(job_id)
require(current_media["ready"] is True and current_media["source_binding_ok"] is True,
        "latest ready Media Finisher render must bind to the current package/variant")
require((current_media["artifact"] or {}).get("url")=="https://example.com/final-ci-current.mp4",
        "approval must resolve the exact latest bound Media Finisher artifact")
approval=asyncio.run(app.approve(job_id))
require(approval["ok"] is True and approval["status"]=="approved","approval decision regression")
require(app.get_approval_history(job_id)[0]["decision"]=="approved","approval history must persist")
pub=approval["publish"]
require(pub["status"]=="approved" and pub["idempotency_key"],"approval must create idempotent queue item")
require((pub.get("media") or {}).get("url")=="https://example.com/final-ci-current.mp4","approved publish item must bind the exact final Media Finisher video")
require((pub.get("meta") or {}).get("media_artifact_id"),"publish provenance must persist the final media artifact id")
require(pub.get("approval_decision_id"),"publish item must link to the exact approval decision")
require(isinstance(pub.get("content_snapshot"),dict) and pub["content_snapshot"].get("title"),"approved publishing metadata snapshot missing")
require(len(pub.get("content_snapshot_hash") or "")==64,"approved publishing metadata snapshot hash missing")
approved_title=pub["content_snapshot"]["title"]
con=app.db();pkg_row=con.execute("SELECT package_json FROM content_packages WHERE id=?",(pub["package_id"],)).fetchone()
mutated_pkg=json.loads(pkg_row["package_json"]);mutated_pkg["title"]="MUTATED AFTER APPROVAL — MUST NOT PUBLISH"
con.execute("UPDATE content_packages SET package_json=?,updated_at=? WHERE id=?",(json.dumps(mutated_pkg,ensure_ascii=False),app.ts(),pub["package_id"]));con.commit();con.close()

orig_pub_adapter,orig_pub_endpoint,orig_pub_external=app.FACTORY_PUBLISHER_ADAPTER,app.FACTORY_PUBLISHER_ENDPOINT,app._external_json
captured_publish={}
def fake_publish_webhook(url,method="GET",payload=None,token=""):
    captured_publish.update({"url":url,"method":method,"payload":payload,"token":token})
    return {"status":"publishing","id":"provider-publish-1"}
app.FACTORY_PUBLISHER_ADAPTER="webhook";app.FACTORY_PUBLISHER_ENDPOINT="https://publisher.invalid/publish";app._external_json=fake_publish_webhook
try:
    adapter_result=app._publish_via_adapter(pub)
    require(adapter_result["manual"] is False,"configured publisher adapter must use webhook path")
    require((captured_publish.get("payload") or {}).get("media_url")=="https://example.com/final-ci-current.mp4","publisher payload must carry the approved final video URL")
    require(((captured_publish.get("payload") or {}).get("content") or {}).get("title")==approved_title,
            "publisher must use the metadata frozen at approval, not a later package mutation")
    require(((captured_publish.get("payload") or {}).get("content") or {}).get("title")!="MUTATED AFTER APPROVAL — MUST NOT PUBLISH",
            "post-approval package edits must not drift into the publisher payload")
    require((captured_publish.get("payload") or {}).get("content_snapshot_hash")==pub["content_snapshot_hash"],
            "publisher payload must carry the approved content snapshot hash")
finally:
    app.FACTORY_PUBLISHER_ADAPTER,app.FACTORY_PUBLISHER_ENDPOINT,app._external_json=orig_pub_adapter,orig_pub_endpoint,orig_pub_external

# v5.3 T-519 — Metricool publisher adapter uses only the frozen approval snapshot and exact media.
metricool_globals=(
    app.FACTORY_PUBLISHER_ADAPTER,app.FACTORY_METRICOOL_TOKEN,app.FACTORY_METRICOOL_USER_ID,
    app.FACTORY_METRICOOL_BLOG_ID,app.FACTORY_METRICOOL_TIMEZONE,
    app.FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS,app._metricool_json,app._metricool_normalize_media_url
)
captured_metricool={}
def fake_metricool(url,method="GET",payload=None):
    captured_metricool.update({"url":url,"method":method,"payload":payload})
    return {"data":{"id":"metricool-schedule-ci","plannerUrl":"https://example.com/metricool/planner/ci"}}
def fake_metricool_normalize(url):
    captured_metricool["normalized_source"]=url
    return "https://metricool.invalid/media/final-ci-current.mp4"
try:
    app.FACTORY_PUBLISHER_ADAPTER="metricool"
    app.FACTORY_METRICOOL_TOKEN="ci-secret-never-render"
    app.FACTORY_METRICOOL_USER_ID="ci-user"
    app.FACTORY_METRICOOL_BLOG_ID="ci-blog"
    app.FACTORY_METRICOOL_TIMEZONE="Europe/Kyiv"
    app.FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS="false"
    app._metricool_json=fake_metricool
    app._metricool_normalize_media_url=fake_metricool_normalize
    metricool_item={**pub,"platform":"youtube_shorts",
                    "scheduled_at":(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat()}
    metricool_result=app._publish_via_adapter(metricool_item)
    require(metricool_result["manual"] is False and metricool_result["status"]=="publishing",
            "Metricool must create an external schedule without inventing a published receipt")
    require(metricool_result.get("external_post_id") is None,
            "Metricool scheduler id must never be misreported as a real platform post id")
    mc_payload=captured_metricool.get("payload") or {}
    require(captured_metricool.get("method")=="POST" and "/api/v2/scheduler/posts?" in captured_metricool.get("url",""),
            "Metricool scheduler endpoint regression")
    require(mc_payload.get("providers")==[{"network":"youtube"}] and mc_payload.get("autoPublish") is True,
            "Metricool YouTube provider payload regression")
    require(captured_metricool.get("normalized_source")=="https://example.com/final-ci-current.mp4",
            "Metricool normalization must start from the exact approved durable media URL")
    require(mc_payload.get("media")==["https://metricool.invalid/media/final-ci-current.mp4"] and mc_payload.get("saveExternalMediaFiles") is True,
            "Metricool scheduler must receive the normalized provider-hosted media URL")
    require((mc_payload.get("youtubeData") or {}).get("title")==approved_title and
            (mc_payload.get("youtubeData") or {}).get("madeForKids") is False and
            (mc_payload.get("youtubeData") or {}).get("isAiGeneratedContent") is True,
            "Metricool YouTube compliance metadata regression")
    require("MUTATED AFTER APPROVAL" not in json.dumps(mc_payload,ensure_ascii=False),
            "Metricool must never receive mutable post-approval package state")
    require(app.get_publisher_adapter_registry()["adapters"][-1]["configured"] is True,
            "Metricool adapter registry must reflect complete server-side configuration")
    ig_payload,_,ig_network=app._metricool_scheduler_payload(
        {**metricool_item,"platform":"instagram_reels"},pub["content_snapshot"],pub["media"])
    require(ig_network=="instagram" and (ig_payload.get("instagramData") or {}).get("type")=="REEL" and
            (ig_payload.get("instagramData") or {}).get("isAiGenerated") is True,
            "Metricool Instagram Reel mapping regression")
    tt_payload,_,tt_network=app._metricool_scheduler_payload(
        {**metricool_item,"platform":"tiktok"},pub["content_snapshot"],pub["media"])
    require(tt_network=="tiktok" and (tt_payload.get("tiktokData") or {}).get("isAigc") is True,
            "Metricool TikTok mapping regression")
    published_snap=app._metricool_provider_snapshot({
        "id":"metricool-schedule-ci",
        "providers":[{"network":"youtube","status":"PUBLISHED","detailedStatus":"OK",
                      "publicUrl":"https://youtube.com/shorts/ci-real",
                      "externalPostId":"yt-ci-real"}]
    },"youtube")
    require(published_snap["status"]=="PUBLISHED" and published_snap["external_id"]=="yt-ci-real" and
            published_snap["public_url"].endswith("/ci-real"),
            "Metricool provider reconciliation must preserve factual platform ID and public URL")
    error_snap=app._metricool_provider_snapshot({
        "providers":[{"network":"youtube","status":"ERROR","detailedStatus":"upload rejected"}]
    },"youtube")
    require(error_snap["status"]=="ERROR" and error_snap["detail"]=="upload rejected" and not error_snap["public_url"],
            "Metricool provider error reconciliation regression")
finally:
    (app.FACTORY_PUBLISHER_ADAPTER,app.FACTORY_METRICOOL_TOKEN,app.FACTORY_METRICOOL_USER_ID,
     app.FACTORY_METRICOOL_BLOG_ID,app.FACTORY_METRICOOL_TIMEZONE,
     app.FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS,app._metricool_json,
     app._metricool_normalize_media_url)=metricool_globals

# v3.70 Publishing Engine — no duplicate publish and no invented external receipt.
unscheduled=asyncio.run(app.publish_scheduled_item(pub["id"]))
require(unscheduled["ok"] is False and "scheduling" in unscheduled["message"].lower(),
        "approved item must not publish before an explicit scheduling action")
scheduled=asyncio.run(app.schedule_publishing(pub["id"],app.PublishScheduleRequest(target="manual",platform="youtube_shorts",scheduled_at=app.ts())))
require(scheduled["item"]["status"]=="scheduled","publishing schedule regression")
started=asyncio.run(app.publish_scheduled_item(pub["id"]))
require(started["requiresManualConfirmation"] is True,"manual path must require factual platform confirmation")
confirmed=asyncio.run(app.confirm_manual_publish(pub["id"],app.PublishConfirmRequest(external_post_id="ci-post-1",external_url="https://example.com/post/ci-post-1")))
require(confirmed["status"]=="published","manual publish confirmation regression")
require(app.get_job(job_id)["status"]=="published","publish receipt must close the production job as published")
con=app.db();receipt=con.execute("SELECT * FROM artifacts WHERE job_id=? AND agent='Publisher' AND kind='publish_receipt' ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone();con.close()
require(receipt is not None and "media_artifact_id" in (receipt["meta_json"] or ""),"publish receipt must preserve final media provenance")
require("content_snapshot_hash" in (receipt["meta_json"] or "") and "approval_decision_id" in (receipt["meta_json"] or ""),
        "publish receipt must preserve approved content/decision provenance")
again=asyncio.run(app.publish_scheduled_item(pub["id"]))
require(again.get("idempotent") is True,"published item must be duplicate-safe")

# v3.80 Feedback Loop — store only metrics actually supplied and preserve attribution.
snap=app.record_performance_snapshot(app.PerformanceSnapshotCreate(publish_id=pub["id"],views=1200,retention_pct=61.5,likes=48,source="ci_fixture"))
require(snap["metrics"]=={"views":1200,"retention_pct":61.5,"likes":48},"missing metrics must not be invented")
require(snap["meta"]["external_post_id"]=="ci-post-1" and snap["meta"]["external_url"].endswith("/ci-post-1"),
        "analytics snapshot must preserve the factual external platform receipt")
require(snap["meta"]["media_artifact_id"]==(pub.get("meta") or {}).get("media_artifact_id"),
        "analytics snapshot must preserve exact published media provenance")
require(snap["meta"]["content_snapshot_hash"]==pub["content_snapshot_hash"] and
        snap["meta"]["approval_decision_id"]==pub["approval_decision_id"],
        "analytics snapshot must bind to exact approved content/decision provenance")
perf=app.get_performance_dashboard()
pitem=next(x for x in perf["items"] if x["publish"]["id"]==pub["id"])
require(pitem["publish"]["external_post_id"]=="ci-post-1","performance item must remain traceable to the external post ID")
require((pitem["latest"].get("meta") or {}).get("external_post_id")=="ci-post-1",
        "persisted latest analytics snapshot must retain platform receipt provenance")
require(pitem["latest"]["metrics"]=={"views":1200,"retention_pct":61.5,"likes":48},
        "performance dashboard must not fabricate absent platform metrics")
require(pitem["attribution"]["idea_id"]==idea["id"],"performance must link to originating idea")
require(pitem["attribution"]["package_id"] and pitem["attribution"]["variant_id"],"performance package/variant attribution missing")
require(pitem["cost_per_1k_views_usd"] is not None,"cost/outcome comparison missing when views exist")
require(perf["angle_cohorts"],"angle cohort comparison missing")

# v3.90 Self-Improving Factory — zero-spend controlled experiment and rollback.
baseline=app._active_workflow_version()
require(baseline["status"]=="active" and baseline["config"]["candidate_count"]==3,"baseline workflow version regression")
try:
    app._sanitize_workflow_patch({"approval_required":False})
    raise AssertionError("workflow patch must reject safety invariant keys")
except ValueError:
    pass
proposal=app.create_improvement_proposal(app.ImprovementProposalCreate(
    title="Test a fourth production candidate",
    rationale="Measure whether one additional candidate improves observed retention before changing production.",
    hypothesis="Four candidates should improve observed retention by at least 5% without bypassing approval.",
    change={"candidate_count":4,"prompt_addenda":{"Hook Generator":"Prefer a concrete mechanism-first opening and keep claims inside supplied evidence."}},
    evidence=[{"type":"ci_fixture","detail":"Controlled deterministic v3.90 verification"}],
))
require(proposal["requires_experiment"] is True and proposal["change"]["candidate_count"]==4,"proposal schema regression")
exp=app.create_experiment_from_proposal(proposal["id"],app.ExperimentCreateRequest(
    primary_metric="retention_pct",min_samples_per_arm=1,min_effect_pct=5.0,platform="youtube_shorts"
))
require(exp["status"]=="draft","new experiment must start as draft")
require(exp["control_version"]["config"]["candidate_count"]==3 and exp["treatment_version"]["config"]["candidate_count"]==4,"control/treatment version regression")

control_created=asyncio.run(app.create_job(app.JobCreate(title="CI experiment control",brief="v3.90 control arm",presenter="Faceless",format="Short only",language="English",outputs=1)))
treatment_created=asyncio.run(app.create_job(app.JobCreate(title="CI experiment treatment",brief="v3.90 treatment arm",presenter="Faceless",format="Short only",language="English",outputs=1)))
control_id=control_created["id"];treatment_id=treatment_created["id"]
control_assignment=app.assign_job_to_experiment(exp["id"],control_id,"control")
treatment_assignment=app.assign_job_to_experiment(exp["id"],treatment_id,"treatment")
require(control_assignment["arm"]=="control" and treatment_assignment["arm"]=="treatment","experiment arm assignment regression")

control_variants=asyncio.run(app.run_variant_pipeline(control_id,None))
treatment_variants=asyncio.run(app.run_variant_pipeline(treatment_id,None))
require(control_variants["summary"]["variants"]==3,"control arm must keep baseline candidate count")
require(treatment_variants["summary"]["variants"]==4,"treatment arm must use isolated workflow candidate count")

def publish_experiment_fixture(job_id,external_post_id,retention,views):
    asyncio.run(app.generate_content_package(job_id))
    con=app.db();con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(app.ts(),job_id));con.commit();con.close()
    approved=asyncio.run(app.approve(job_id))
    require(approved["ok"] is True,"experiment fixture approval regression")
    pub=approved["publish"]
    asyncio.run(app.schedule_publishing(pub["id"],app.PublishScheduleRequest(target="manual",platform="youtube_shorts",scheduled_at=app.ts())))
    started=asyncio.run(app.publish_scheduled_item(pub["id"]))
    require(started["requiresManualConfirmation"] is True,"experiment fixture must not invent publish receipt")
    asyncio.run(app.confirm_manual_publish(pub["id"],app.PublishConfirmRequest(external_post_id=external_post_id,external_url="https://example.com/post/"+external_post_id)))
    snap=app.record_performance_snapshot(app.PerformanceSnapshotCreate(publish_id=pub["id"],views=views,retention_pct=retention,source="ci_experiment_fixture"))
    return pub,snap

control_pub,_=publish_experiment_fixture(control_id,"ci-exp-control",50.0,1000)
treatment_pub,_=publish_experiment_fixture(treatment_id,"ci-exp-treatment",60.0,1100)
control_perf=next(x for x in app.get_performance_dashboard()["items"] if x["publish"]["id"]==control_pub["id"])
treatment_perf=next(x for x in app.get_performance_dashboard()["items"] if x["publish"]["id"]==treatment_pub["id"])
require(control_perf["attribution"]["experiment_arm"]=="control" and treatment_perf["attribution"]["experiment_arm"]=="treatment","performance attribution must preserve experiment arm")
evaluation=app.evaluate_experiment(exp["id"])
require(evaluation["enough_samples"] is True and evaluation["recommendation"]=="treatment","measured treatment recommendation regression")
require(round(evaluation["observed_improvement_pct"],1)==20.0,"retention effect calculation regression")
require(evaluation["control"]["avg_production_cost_usd"] is not None and evaluation["treatment"]["avg_production_cost_usd"] is not None,"experiment cost comparison missing")
blocked_rollout=app.rollout_experiment(exp["id"],False,"CI should require owner confirmation")
require(blocked_rollout["requires_confirmation"] is True,"rollout must require explicit owner confirmation")
rolled=app.rollout_experiment(exp["id"],True,"CI owner-approved measured rollout")
require(rolled["active"]["config"]["candidate_count"]==4,"approved treatment did not become active")
rolled_back=app.rollback_experiment(exp["id"],True,"CI rollback verification")
require(rolled_back["active"]["config"]["candidate_count"]==3,"rollback did not restore baseline workflow")
dash=app.get_self_improvement_dashboard()
require(dash["active_workflow"]["config"]["candidate_count"]==3 and dash["experiments"],"Experiment Lab dashboard regression")
require("never auto-promote" in dash["safety_note"],"self-improvement safety note regression")

# v4.1 production SQLite regression: exercise the LIVE variant persistence path with a deterministic fake worker.
lock_job=asyncio.run(app.create_job(app.JobCreate(
    title="CI live-variant transaction regression",brief="No network; fake live worker exercises SQLite persistence.",
    presenter="Faceless",format="Short only",language="English",outputs=1
)))["id"]
orig_key=app.FACTORY_LLM_API_KEY
orig_variant_call=app._variant_agent_call
app.FACTORY_LLM_API_KEY="ci-fake-no-network"
async def fake_variant_call(agent,job_id,label,system,user,max_output_tokens=1100):
    run_id=app.start_agent_run(agent,job_id,"script",model="ci-fake")
    ids=list(dict.fromkeys(app.re.findall(r'"id"\s*:\s*"([^"]+)"',user)))
    if agent=="Angle Strategist":
        obj={"angles":[
            {"angle":"CI angle one","reason":"transaction test","audience":"builders"},
            {"angle":"CI angle two","reason":"transaction test","audience":"builders"},
            {"angle":"CI angle three","reason":"transaction test","audience":"builders"},
        ]}
    elif agent=="Hook Generator":
        obj={"variants":[{"variant_id":x,"hook":f"Hook {i+1}","rationale":"CI"} for i,x in enumerate(ids)]}
    elif agent=="Scriptwriter":
        obj={"variants":[{"variant_id":x,"script":f"Hook {i+1}. Evidence-bounded CI script. CTA."} for i,x in enumerate(ids)]}
    elif agent=="Fact Checker":
        obj={"variants":[{"variant_id":x,"findings":[],"fact_summary":"CI only"} for x in ids]}
    elif agent=="Hook Optimizer":
        obj={"variants":[{"variant_id":x,"optimized_hook":f"Optimized {i+1}","change_reason":"CI"} for i,x in enumerate(ids)]}
    elif agent=="Editor":
        obj={"variants":[{"variant_id":x,"edited_script":f"Optimized {i+1}. Edited evidence-bounded CI script. CTA.","edit_notes":"CI"} for i,x in enumerate(ids)]}
    elif agent=="QA Agent":
        obj={"variants":[{"variant_id":x,"decision":"keep" if i==0 else "reject","reason":"CI deterministic choice","findings":[]} for i,x in enumerate(ids)],
             "recommended_variant_id":ids[0] if ids else ""}
    else:
        raise AssertionError("unexpected fake variant agent "+agent)
    app.finish_agent_run(run_id,status="completed",meta={"mode":"ci_fake_live"})
    return obj,run_id,{"input_tokens":0,"output_tokens":0,"cost_usd":0.0,"model":"ci-fake"}
app._variant_agent_call=fake_variant_call
try:
    live_variant_result=asyncio.run(app.run_variant_pipeline(lock_job,None))
    require(live_variant_result["summary"]["variants"]==3 and live_variant_result["summary"]["selected"]==1,
            "live variant persistence/SQLite transaction regression")
    con=app.db();busy=int(con.execute("PRAGMA busy_timeout").fetchone()[0]);con.close()
    require(busy>=30000,"SQLite busy_timeout hardening regression")
finally:
    app._variant_agent_call=orig_variant_call
    app.FACTORY_LLM_API_KEY=orig_key

# v4.1 real-world pilot controls — zero-spend validation only.
pilot_signals=app._parse_real_pilot_signals('[{"title":"Real signal","url":"https://example.com/real","content":"A factual source summary for pilot parsing.","topic":"AI"}]')
require(len(pilot_signals)==1 and pilot_signals[0]["url"]=="https://example.com/real","real pilot signal parsing regression")
pilot_tag="ci-v4.1-pilot-fence"
con=app.db();con.execute("""INSERT OR REPLACE INTO system_verifications(tag,status,started_at,finished_at,live_runs,input_tokens,output_tokens,cost_usd,detail)
                           VALUES(?,?,?,?,?,?,?,?,?)""",(pilot_tag,"passed",app.ts(),app.ts(),4,100,40,0.01,
                           '{"cycle_id":"ci-cycle","job_id":"ci-job","approval_gate_reached":true,"idea_title":"CI pilot"}'));con.commit();con.close()
pilot=app.get_real_pilot(pilot_tag)
require(pilot["status"]=="passed" and pilot["approval_gate_reached"] is True and pilot["cycle_id"]=="ci-cycle","real pilot evidence readback regression")

# v4.0 Autonomous Content Factory — zero-spend closed-loop acceptance.
cycle_signal=app.ingest_source_signal(app.SignalCreate(
    title="CI v4 autonomous signal",
    content="A persisted source signal for the closed-loop acceptance fixture.",
    url="https://example.com/v4-source",
    source_type="ci",
    topic="autonomous factory",
))
cycle_idea=app.create_content_idea(app.IdeaCreate(
    title="How an autonomous content factory closes the loop",
    topic="autonomous factory",
    angle="show the exact handoffs and approval boundary",
    audience="AI builders",
    why_now="v4 integration acceptance",
    source_signal_ids=[cycle_signal["signal"]["id"]],
    source_links=["https://example.com/v4-source"],
    score=0.92,
))
con=app.db();now=app.ts()
con.execute("""UPDATE content_ideas SET status='selected',research_json=?,strategy_json=?,verification_json=?,
               novelty_evidence=?,verified_at=?,updated_at=? WHERE id=?""",(
    '{"research_summary":"Persisted CI source only","claims":["Factory Cycle keeps one traceable chain from signal to learning."],"source_signal_ids":[],"source_links":["https://example.com/v4-source"],"missing_evidence":[]}',
    '{"title":"How an autonomous content factory closes the loop","angle":"show the exact handoffs and approval boundary","audience":"AI builders","why_now":"v4 integration acceptance","novelty_evidence":"closed-loop integration","complexity":"medium","score":0.92,"strategy_notes":"CI fixture"}',
    '{"decision":"shortlist","score":0.92,"risk_flags":[],"verification_notes":"CI fixture is bounded to persisted source evidence.","rejection_reason":""}',
    "closed-loop integration",now,now,cycle_idea["id"]
));con.commit();con.close()

cycle=app.create_factory_cycle(app.FactoryCycleCreate(
    signal_ids=[cycle_signal["signal"]["id"]],idea_id=cycle_idea["id"],language="English"
),source="ci_fixture")
require(cycle["status"]=="ready" and cycle["idea_id"]==cycle_idea["id"],"Factory Cycle creation/provenance regression")
quote=app.estimate_factory_cycle_cost(cycle["id"],3)
require(quote["paid_calls_possible"] is False and quote["estimated_max_usd"]==0.0,"CI cycle must remain zero-spend")
asyncio.run(app._run_factory_cycle_to_review(cycle["id"],3,"English"))
cycle=app.get_factory_cycle(cycle["id"],True)
require(cycle["status"]=="waiting_approval" and cycle["phase"]=="approval","Autopilot must stop at human approval")
require(cycle["job_id"] and cycle["job"]["status"]=="waiting_approval","cycle idea→job→review handoff regression")
require(cycle["workflow_version_id"]==app.get_job_workflow_assignment(cycle["job_id"])["workflow_version_id"],"cycle workflow pinning regression")
require(app.get_content_package(cycle["job_id"])["status"]=="ready","Autopilot cycle must build a fresh Content Package")
con=app.db();link=con.execute("SELECT idea_id FROM job_idea_links WHERE job_id=?",(cycle["job_id"],)).fetchone();con.close()
require(link and link["idea_id"]==cycle_idea["id"],"cycle must preserve idea→job attribution")
require(cycle.get("publish_id") is None,"Autopilot must not publish or queue before human approval")

cycle_approved=asyncio.run(app.approve(cycle["job_id"]))
require(cycle_approved["ok"] is True,"cycle approval regression")
cycle=app.get_factory_cycle(cycle["id"],True)
require(cycle["status"]=="approved" and cycle["publish_id"]==cycle_approved["publish"]["id"],"approval→cycle publishing handoff regression")
asyncio.run(app.schedule_publishing(cycle["publish_id"],app.PublishScheduleRequest(target="manual",platform="youtube_shorts",scheduled_at=app.ts())))
manual_start=asyncio.run(app.publish_scheduled_item(cycle["publish_id"]))
require(manual_start["requiresManualConfirmation"] is True,"cycle publisher must still require factual external confirmation")
asyncio.run(app.confirm_manual_publish(cycle["publish_id"],app.PublishConfirmRequest(
    external_post_id="ci-v4-post",external_url="https://example.com/post/ci-v4-post"
)))
cycle=app.get_factory_cycle(cycle["id"],True)
require(cycle["status"]=="published","published receipt must synchronize into Factory Cycle")
cycle_snap=app.record_performance_snapshot(app.PerformanceSnapshotCreate(
    publish_id=cycle["publish_id"],views=1800,retention_pct=70.0,completion_rate_pct=52.0,likes=90,source="ci_v4_fixture"
))
require(cycle_snap["metrics"]["retention_pct"]==70.0,"cycle factual performance persistence regression")
cycle=app.get_factory_cycle(cycle["id"],True)
require(cycle["status"]=="learning_ready" and cycle["phase"]=="learning","analytics→learning handoff regression")
require(cycle["learning"].get("primary_observed_metric")=="retention_pct","cycle learning must use real persisted metric")
require("causal proof" in cycle["learning"].get("statement",""),"learning must preserve evidence/causality boundary")
cycle_perf=next(x for x in app.get_performance_dashboard()["items"] if x["publish"]["id"]==cycle["publish_id"])
require(cycle_perf["attribution"]["factory_cycle_id"]==cycle["id"],"performance must trace back to Factory Cycle")
require(cycle_perf["attribution"]["workflow_version_id"]==cycle["workflow_version_id"],"performance must trace exact workflow version")
child=app.create_factory_cycle(app.FactoryCycleCreate(language="English",parent_cycle_id=cycle["id"]),source="ci_next_cycle")
require(child["parent_cycle_id"]==cycle["id"],"learning→next-cycle lineage regression")
require(child["workflow_version_id"]==app._active_workflow_version()["id"],"next cycle must use current owner-approved workflow")
cycle_dash=app.get_factory_cycles()
require(cycle_dash["summary"]["cycles"]>=2 and any(x["id"]==cycle["id"] for x in cycle_dash["cycles"]),"Cycle Control dashboard regression")
require("human approval" in cycle_dash["safety_note"],"Autopilot safety fence regression")

transport=app.classify_agent_error("LLM provider request failed: timed out")
require(transport["requires_confirmation"] is True,"uncertain transport failure must require confirmation")
require(transport["auto_retry"] is False,"uncertain transport failure must not auto-retry")
rate=app.classify_agent_error("OpenAI API rate limit reached")
require(rate["auto_retry"] is True,"rate-limit policy should allow one safe retry")
billing=app.classify_agent_error("OpenAI API balance exhausted")
require(billing["auto_retry"] is False and billing["spend_uncertain"] is False,"billing policy regression")

readiness=app.get_release_readiness()
for key in ("state","summary","checks","blockers","remaining_paid_verification","next_priorities","note"):
    require(key in readiness,f"readiness missing {key}")
require(any(x["id"]=="approval_gate" and x["ok"] for x in readiness["checks"]),"approval gate readiness check missing")
require(any(x["id"]=="uncertain_retry" and x["ok"] for x in readiness["checks"]),"safe retry readiness check missing")

intel=app.get_factory_intelligence()
for key in ("summary","leaders","workers","jobs","insights","measurement_note"):
    require(key in intel,f"intelligence missing {key}")
for key in ("runs","completed_runs","failed_runs","success_rate","duration_ms","tokens","cost_usd","recent_avg_artifact_coverage"):
    require(key in intel["summary"],f"intelligence summary missing {key}")

html=Path("static/index.html").read_text(encoding="utf-8")
require('data-i18n="error.title"' in html,"Error Center title is not localized")
require('data-i18n="worker.title"' in html,"Worker Results title is not localized")
require("function workerContract(" in html and "workerContract(r&&r.report)" in html,"Worker Results must render the input/action/output/cost contract")
for key in ("input","action","status","output","artifacts","duration","tokens","cost","unavailable","noInputs","artifactOnly"):
    require(html.count('"worker.contract.'+key+'":')==3,f"worker.contract.{key} must exist in EN/UK/RU")
require('data-i18n="intel.title"' in html,"Factory Intelligence title is not localized")
require('onclick="openDelegationCenter()"' in html and 'data-i18n="dc.title"' in html and "function renderDelegationCenter(" in html,"Worker / Delegation Control Center page missing")
require("api('/api/factory/delegation-board')" in html,"Control Center must read the owner-safe delegation board API")
for key in ("dc.nav","dc.title","dc.unavailable","dc.planner","dc.worker","dc.connection.online","dc.connection.stale","dc.connection.offline","dc.safeRemaining","dc.humanRemaining"):
    require(html.count(f'"{key}":')==3,f"i18n key {key} must exist in EN/UK/RU")
require("FactoryOS v3.14" not in html,"stale document title version returned")
require('data-i18n="brain.title"' in html,"Content Brain workspace missing")
require('data-i18n="variant.title"' in html,"Variant Studio workspace missing")
require('data-i18n="package.title"' in html,"Content Package workspace missing")
require('data-i18n="approval.title"' in html,"Approval Studio workspace missing")
require('data-i18n="publishing.title"' in html,"Publishing Engine workspace missing")
require('data-i18n="performance.title"' in html,"Performance Feedback workspace missing")
require('data-i18n="experiment.title"' in html,"Experiment Lab workspace missing")
require('data-i18n="cycle.title"' in html,"Autonomous Cycle Control workspace missing")
require('data-i18n="revideo.title"' in html,"Revideo workspace missing")
require('data-i18n="discovery.title"' in html,"Discovery workspace missing")
require("openApprovalStudio" in html and "approvalRegenerate" in html,"Approval Studio controls missing")
require("openPublishingStudio" in html and "publishQueueItem" in html,"Publishing controls missing")
require("openPerformanceStudio" in html and "addPerformanceSnapshot" in html,"Performance controls missing")
require("openExperimentLab" in html and "evaluateExperiment" in html and "rolloutExperiment" in html and "rollbackExperiment" in html,"Experiment Lab controls missing")
require("openAutonomousFactory" in html and "runFactoryCycle" in html and "nextFactoryCycle" in html,"Autonomous Cycle controls missing")
require("openRevideoStudio" in html and "analyzeRevideo" in html and "createRevideoJob" in html and "renderRevideoVideo" in html,"Revideo controls missing")
require("openMediaFinisher" in html and "startMediaFinisher" in html and "refreshMediaFinisher" in html and "rerunMediaFinisher" in html,"Media Finisher controls missing")
require("serviceIcon(k)" in html and "worker.downloadMedia" in html and "copyArtifactLink" in html,"v4.6 branded connections/artifact actions missing")
require("finisherCompute" in html and "copyLocalBoosterToken" in html and "/api/local-booster/status" in html,"v4.9 Local Render Booster UI missing")
require("/api/local-booster/package.zip" in html,"Local Booster package UI missing")
require("/api/artifacts/" in html and "/media" in html,"artifact UI must route media through stable FactoryOS endpoints")
require('data-i18n="finisher.nav"' in html,"Media Finisher navigation missing")
require("openDiscoveryStudio" in html and "saveDiscoveryCandidate" in html and "candidateToRevideo" in html,"Discovery controls missing")
require('onclick="openPackageStudio()"' in html,"Content Package action missing")
require("buildContentPackage" in html and "renderPackageStudio" in html,"Content Package controls missing")
require('onclick="openVariantStudio()"' in html,"Variant Studio action missing")
require("rerunVariant" in html and "buildVariants" in html,"Variant Studio controls missing")
require('onclick="openContentBrain()"' in html,"Content Brain navigation missing")
require("runBrainFull()" in html and "processBrainIdea" in html,"Content Brain mobile actions missing")
require("function textValue(v)" in html and "const esc=v=>textValue(v).replace" in html,"type-safe frontend escaping regression")
require("const esc=s=>(s||'').replace" not in html,"unsafe frontend escape function returned")
require("workerSelectedResult" in html and "selected_job_result" in Path("app.py").read_text(encoding="utf-8"),"selected-job worker evidence UI/API missing")
require('"/media-archive/"' in Path("app.py").read_text(encoding="utf-8").split("public_prefixes =",1)[1].split("\n",1)[0],"signed durable media route must bypass session auth before token validation")
require('data-help="help.approval"' in html and 'data-help="help.brain"' in html and 'data-help="help.worker"' in html and 'data-help="help.finisher"' in html,"help tooltip coverage missing")
require("legacyBanner" in html and "approval.legacyHelp" in html,"legacy approval clarity missing")
require('<span class="version">v5.3</span>' in html,"visible UI version mismatch")
require('autopilotDecisions' in html and 'recent_decisions' in html,"autopilot decision review UI missing")
require("v3.24 mobile parity" in html,"mobile parity CSS marker missing")
require(".agent{display:none}" not in html,"mobile CSS must not hide clickable worker cards")
require("#agentBadges{position:relative;display:grid" in html,"mobile worker grid missing")
for key in ("approval.nav","approval.title","approval.statWaiting","approval.approveQueue","approval.legacyHelp","help.approval","help.brain","help.worker","help.revideo","help.finisher","revideo.nav","revideo.title","revideo.analyze","revideo.originalRewrite","finisher.nav","finisher.title","finisher.start","finisher.unconfigured","finisher.rerunCaptions","finisher.humanGate","help.discovery","discovery.nav","discovery.title","discovery.toRevideo","publishing.nav","publishing.title","publishing.statQueue","performance.nav","performance.title","performance.statPublished","experiment.nav","experiment.title","experiment.sub","cycle.nav","cycle.title","cycle.sub","cycle.run","cycle.review","cycle.next","cycle.statCycles","cycle.status.waiting_approval","brain.nav","brain.title","brain.run","brain.verifyOne","brain.createJob","variant.nav","variant.title","variant.build","variant.select","variant.rerun","package.nav","package.title","package.build","package.scenes","package.adapters","nav.errors","error.title","error.confirmUncertain","worker.title","worker.noHandoffs","worker.selectedResult","worker.purpose.renderagent","trace.title","trace.loadFailed","intel.title","intel.workerComparison","intel.note","nav.qa","qa.title","qa.loading"):
    require(html.count(f'"{key}":')==3,f"i18n key {key} must exist in EN/UK/RU")
print("FactoryOS v4.8.1 smoke/regression suite passed without paid provider calls; signed durable media access verified")

require(hasattr(app,"FACTORY_GOOGLE_CLIENT_ID") and hasattr(app,"FACTORY_GOOGLE_ALLOWED_EMAILS"),"Google auth config missing")

owner_token=app._role_session_token("owner","owner@example.com")
viewer_token=app._role_session_token("viewer","viewer@example.com")
require(app._identity_from_session_token(owner_token)["role"]=="owner","owner role session regression")
require(app._identity_from_session_token(viewer_token)["role"]=="viewer","viewer role session regression")
require(app._identity_from_session_token(viewer_token)["email"]=="viewer@example.com","viewer email session regression")

require(hasattr(app,"FACTORY_VIEWER_INVITE_TOKEN"),"viewer invite config missing")


# Native Gemini Omni video provider stays zero-spend in CI: only pure parsing/config helpers are exercised.
require(hasattr(app,"FACTORY_GEMINI_API_KEY") and hasattr(app,"FACTORY_GEMINI_VIDEO_MODEL"),"Gemini video config missing")
require(app._is_gemini_video_provider("gemini-omni"),"Gemini adapter alias regression")
uri_payload={"steps":[{"type":"model_output","content":[{"type":"video","mime_type":"video/mp4","uri":"https://generativelanguage.googleapis.com/v1beta/files/abc-123:download?alt=media"}]}]}
require(app._gemini_video_uri(uri_payload).endswith("files/abc-123:download?alt=media"),"Gemini REST URI extraction regression")
require(app._gemini_video_file_id(app._gemini_video_uri(uri_payload))=="abc-123","Gemini file-id extraction regression")
prompt=app._gemini_video_prompt({"title":"Test","hook":"Open fast","scenes":[{"visual":"Original abstract motion","narration":"A concise fact"}]})
require("Do not copy or reuse source footage" in prompt and "No spoken dialogue" in prompt,"Gemini prompt guardrails missing")
old_video_adapter=app.FACTORY_MEDIA_ADAPTERS.get("video")
old_gemini_key=app.FACTORY_GEMINI_API_KEY
try:
    app.FACTORY_MEDIA_ADAPTERS["video"]="gemini-omni"
    app.FACTORY_GEMINI_API_KEY="ci-placeholder-not-a-real-key"
    require(app._video_provider_configured(),"Gemini video should report configured when runtime secret exists")
    adapter=app.get_revideo_adapter_registry()["video"]
    require(adapter["configured"] and adapter["execution"]=="gemini_interactions_uri","Gemini Revideo registry regression")
    require("ci-placeholder-not-a-real-key" not in json.dumps(app.get_revideo_adapter_registry()),"Gemini secret leaked through adapter registry")
    video_conn=app.get_connection_registry()["Video"]
    require(video_conn["state"]=="connected" and video_conn["provider"]=="gemini-omni","Gemini connection registry regression")
finally:
    app.FACTORY_MEDIA_ADAPTERS["video"]=old_video_adapter
    app.FACTORY_GEMINI_API_KEY=old_gemini_key
