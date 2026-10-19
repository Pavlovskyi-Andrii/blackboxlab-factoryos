"""FactoryOS zero-spend smoke/regression checks."""
import asyncio
import os
import tempfile
from pathlib import Path
if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-smoke-")
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
require(health["version"]==app.APP_VERSION=="v3.25","version mismatch")
require("paid_verification" in health,"paid verification health summary missing")
require(health["paid_verification"]["status"] in ("pending","started","passed","failed","disabled"),"unexpected paid verification status")
require("llm_configured" in health and "llm_model" in health,"provider readiness fields missing")
state=app.status()
for key in ("factory","version","jobs","agentStates","agentProgress","usage","selectedJobWorkerResults","selectedJobHandoffs","selectedJobAgentErrors","selectedJobErrorCenter","contentBrain","runtimePolicy"):
    require(key in state,f"status missing {key}")
require(state["factory"]=="online","factory must report online")

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
for path,method in (("/health","GET"),("/api/version","GET"),("/api/status","GET"),("/api/release-readiness","GET"),("/api/intelligence","GET"),("/api/content-brain","GET"),("/api/content-brain/signals","POST"),("/api/content-brain/ideas","POST"),("/api/content-brain/ideas/{idea_id}/status","POST"),("/api/handoffs/{run_id}/{artifact_id}","GET"),("/api/jobs/{job_id}/approve","POST"),("/api/jobs/{job_id}/agents/{agent_name}/rerun","POST")):
    require(route_exists(path,method),f"route missing: {method} {path}")

created=asyncio.run(app.create_job(app.JobCreate(title="CI smoke job",brief="Zero-spend regression fixture",presenter="Faceless",format="Short only",language="English",outputs=1)))
job_id=created["id"]
require(app.get_job(job_id) is not None,"smoke job was not persisted")
require(app.get_job_worker_results(job_id)=={},"new job should not invent worker outputs")
require(app.get_job_handoffs(job_id)==[],"new job should not invent handoffs")
center=app.get_job_error_center(job_id)
require(set(center)=={"summary","incidents"},"error center shape changed")
require(center["summary"]["open"]==0,"new job should not have incidents")
approval=asyncio.run(app.approve(job_id))
require(approval["ok"] is False,"approval must be gated until waiting_approval")

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
require('data-i18n="intel.title"' in html,"Factory Intelligence title is not localized")
require("FactoryOS v3.14" not in html,"stale document title version returned")
require("v3.24 mobile parity" in html,"mobile parity CSS marker missing")
require(".agent{display:none}" not in html,"mobile CSS must not hide clickable worker cards")
require("#agentBadges{position:relative;display:grid" in html,"mobile worker grid missing")
for key in ("nav.errors","error.title","error.confirmUncertain","worker.title","worker.noHandoffs","trace.title","trace.loadFailed","intel.title","intel.workerComparison","intel.note","nav.qa","qa.title","qa.loading"):
    require(html.count(f'"{key}":')==3,f"i18n key {key} must exist in EN/UK/RU")
print("FactoryOS v3.25 smoke/regression suite passed without paid provider calls")
