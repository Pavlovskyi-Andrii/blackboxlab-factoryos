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
require(health["version"]==app.APP_VERSION=="v3.50","version mismatch")
require("paid_verification" in health,"paid verification health summary missing")
require(health["paid_verification"]["status"] in ("pending","started","passed","failed","disabled"),"unexpected paid verification status")
require("llm_configured" in health and "llm_model" in health,"provider readiness fields missing")
state=app.status()
for key in ("factory","version","jobs","agentStates","agentProgress","usage","selectedJobWorkerResults","selectedJobHandoffs","selectedJobAgentErrors","selectedJobErrorCenter","selectedJobVariants","selectedJobContentPackage","mediaAdapters","contentBrain","runtimePolicy"):
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
parsed=app._parse_idea_candidates('[{"title":"A","score":0.8}]')
require(parsed and parsed[0]["title"]=="A","idea candidate parser regression")
obj=app._parse_json_object('```json\n{"decision":"shortlist","score":0.9}\n```')
require(obj["decision"]=="shortlist","Content Brain JSON object parser regression")
brain=app.get_content_brain()
require("adapters" in brain and "rss" in brain["adapters"],"source adapter registry missing")
require("verified" in brain["summary"] and "feeds_configured" in brain["summary"],"Content Brain summary fields missing")
for path,method in (("/health","GET"),("/api/version","GET"),("/api/status","GET"),("/api/release-readiness","GET"),("/api/intelligence","GET"),("/api/content-brain","GET"),("/api/content-brain/collect","POST"),("/api/content-brain/signals","POST"),("/api/content-brain/generate","POST"),("/api/content-brain/process","POST"),("/api/content-brain/ideas","POST"),("/api/content-brain/ideas/{idea_id}/status","POST"),("/api/media-adapters","GET"),("/api/jobs/{job_id}/content-package","GET"),("/api/jobs/{job_id}/content-package/generate","POST"),("/api/jobs/{job_id}/content-package/export.json","GET"),("/api/jobs/{job_id}/content-package/export.zip","GET"),("/api/jobs/{job_id}/variants","GET"),("/api/jobs/{job_id}/variants/generate","POST"),("/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}","POST"),("/api/jobs/{job_id}/variants/{variant_id}/select","POST"),("/api/handoffs/{run_id}/{artifact_id}","GET"),("/api/jobs/{job_id}/approve","POST"),("/api/jobs/{job_id}/agents/{agent_name}/rerun","POST")):
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
exports=app._package_export_files(package_result["package_record"])
for name in ("content-package.json","final-script.txt","voice-over.txt","subtitles.srt","scenes.json","publishing-metadata.json","sources.json","fact-check.json","media-brief.md"):
    require(name in exports,f"package export missing {name}")
app.select_production_variant(job_id,variant_result["variants"][0]["id"])
require(app.get_content_package(job_id)["status"]=="stale","changing selected variant must invalidate existing Content Package")
require(app.get_job(job_id)["stage"]=="script" and app.get_job(job_id)["status"]=="idle","changing selected variant must fence downstream stages back to script")


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
require('data-i18n="brain.title"' in html,"Content Brain workspace missing")
require('data-i18n="variant.title"' in html,"Variant Studio workspace missing")
require('data-i18n="package.title"' in html,"Content Package workspace missing")
require('onclick="openPackageStudio()"' in html,"Content Package action missing")
require("buildContentPackage" in html and "renderPackageStudio" in html,"Content Package controls missing")
require('onclick="openVariantStudio()"' in html,"Variant Studio action missing")
require("rerunVariant" in html and "buildVariants" in html,"Variant Studio controls missing")
require('onclick="openContentBrain()"' in html,"Content Brain navigation missing")
require("runBrainFull()" in html and "processBrainIdea" in html,"Content Brain mobile actions missing")
require('<span class="version">v3.50</span>' in html,"visible UI version mismatch")
require("v3.24 mobile parity" in html,"mobile parity CSS marker missing")
require(".agent{display:none}" not in html,"mobile CSS must not hide clickable worker cards")
require("#agentBadges{position:relative;display:grid" in html,"mobile worker grid missing")
for key in ("brain.nav","brain.title","brain.run","brain.verifyOne","brain.createJob","variant.nav","variant.title","variant.build","variant.select","variant.rerun","package.nav","package.title","package.build","package.scenes","package.adapters","nav.errors","error.title","error.confirmUncertain","worker.title","worker.noHandoffs","trace.title","trace.loadFailed","intel.title","intel.workerComparison","intel.note","nav.qa","qa.title","qa.loading"):
    require(html.count(f'"{key}":')==3,f"i18n key {key} must exist in EN/UK/RU")
print("FactoryOS v3.50 smoke/regression suite passed without paid provider calls")
