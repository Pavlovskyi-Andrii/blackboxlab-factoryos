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
require(health["version"]==app.APP_VERSION=="v4.0","version mismatch")
require("paid_verification" in health,"paid verification health summary missing")
require(health["paid_verification"]["status"] in ("pending","started","passed","failed","disabled"),"unexpected paid verification status")
require("llm_configured" in health and "llm_model" in health,"provider readiness fields missing")
state=app.status()
for key in ("factory","version","jobs","agentStates","agentProgress","usage","selectedJobWorkerResults","selectedJobHandoffs","selectedJobAgentErrors","selectedJobErrorCenter","selectedJobVariants","selectedJobContentPackage","mediaAdapters","contentBrain","approvalSummary","publishingSummary","performanceSummary","selfImprovementSummary","autonomousCycleSummary","activeWorkflow","publisherAdapters,"analyticsAdapters","runtimePolicy"):
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
for path,method in (("/health","GET"),("/api/version","GET"),("/api/status","GET"),("/api/release-readiness","GET"),("/api/intelligence","GET"),("/api/content-brain","GET"),("/api/content-brain/collect","POST"),("/api/content-brain/signals","POST"),("/api/content-brain/generate","POST"),("/api/content-brain/process","POST"),("/api/content-brain/ideas","POST"),("/api/content-brain/ideas/{idea_id}/status","POST"),("/api/media-adapters","GET"),("/api/jobs/{job_id}/content-package","GET"),("/api/jobs/{job_id}/content-package/generate","POST"),("/api/jobs/{job_id}/content-package/export.json","GET"),("/api/jobs/{job_id}/content-package/export.zip","GET"),("/api/jobs/{job_id}/variants","GET"),("/api/jobs/{job_id}/variants/generate","POST"),("/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}","POST"),("/api/jobs/{job_id}/variants/{variant_id}/select","POST"),("/api/handoffs/{run_id}/{artifact_id}","GET"),("/api/jobs/{job_id}/approve","POST"),("/api/jobs/{job_id}/reject","POST"),("/api/approval","GET"),("/api/jobs/{job_id}/approval/history","GET"),("/api/jobs/{job_id}/approval/quote/{component}","GET"),("/api/jobs/{job_id}/approval/regenerate","POST"),("/api/jobs/{job_id}/idea-link/{idea_id}","POST"),("/api/publisher-adapters","GET"),("/api/publishing","GET"),("/api/publishing/{publish_id}/schedule","POST"),("/api/publishing/{publish_id}/publish","POST"),("/api/publishing/{publish_id}/confirm","POST"),("/api/publishing/run-due","POST"),("/api/analytics-adapters","GET"),("/api/performance","GET"),("/api/performance/{publish_id}","GET"),("/api/performance/snapshots","POST"),("/api/performance/{publish_id}/sync","POST"),("/api/self-improvement","GET"),("/api/workflow/active","GET"),("/api/experiments","GET"),("/api/improvements","POST"),("/api/improvements/{proposal_id}/experiment","POST"),("/api/experiments/{experiment_id}/assign","POST"),("/api/experiments/{experiment_id}/evaluate","POST"),("/api/experiments/{experiment_id}/rollout","POST"),("/api/experiments/{experiment_id}/rollback","POST"),("/api/experiments/{experiment_id}/reject","POST"),("/api/factory-cycles","GET"),("/api/factory-cycles","POST"),("/api/factory-cycles/{cycle_id}","GET"),("/api/factory-cycles/{cycle_id}/quote","GET"),("/api/factory-cycles/{cycle_id}/run","POST"),("/api/factory-cycles/{cycle_id}/sync","POST"),("/api/factory-cycles/{cycle_id}/learn","POST"),("/api/factory-cycles/{cycle_id}/next","POST"),("/api/jobs/{job_id}/agents/{agent_name}/rerun","POST")):
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

# v3.60 Approval Studio — deterministic/zero-spend regression.
asyncio.run(app.generate_content_package(job_id))
app.link_job_idea(job_id,idea["id"])
con=app.db();con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(app.ts(),job_id));con.commit();con.close()
queue=app.get_approval_queue()
require(any(x["job"]["id"]==job_id for x in queue["items"]),"approval queue must include waiting job")
require("estimated_model_cost_usd" in app._estimated_regeneration_cost("hook"),"cost-before-rerun quote missing")
approval=asyncio.run(app.approve(job_id))
require(approval["ok"] is True and approval["status"]=="approved","approval decision regression")
require(app.get_approval_history(job_id)[0]["decision"]=="approved","approval history must persist")
pub=approval["publish"]
require(pub["status"]=="approved" and pub["idempotency_key"],"approval must create idempotent queue item")

# v3.70 Publishing Engine — no duplicate publish and no invented external receipt.
scheduled=asyncio.run(app.schedule_publishing(pub["id"],app.PublishScheduleRequest(target="manual",platform="youtube_shorts",scheduled_at=app.ts())))
require(scheduled["item"]["status"]=="scheduled","publishing schedule regression")
started=asyncio.run(app.publish_scheduled_item(pub["id"]))
require(started["requiresManualConfirmation"] is True,"manual path must require factual platform confirmation")
confirmed=asyncio.run(app.confirm_manual_publish(pub["id"],app.PublishConfirmRequest(external_post_id="ci-post-1",external_url="https://example.com/post/ci-post-1")))
require(confirmed["status"]=="published","manual publish confirmation regression")
again=asyncio.run(app.publish_scheduled_item(pub["id"]))
require(again.get("idempotent") is True,"published item must be duplicate-safe")

# v3.80 Feedback Loop — store only metrics actually supplied and preserve attribution.
snap=app.record_performance_snapshot(app.PerformanceSnapshotCreate(publish_id=pub["id"],views=1200,retention_pct=61.5,likes=48,source="ci_fixture"))
require(snap["metrics"]=={"views":1200,"retention_pct":61.5,"likes":48},"missing metrics must not be invented")
perf=app.get_performance_dashboard()
pitem=next(x for x in perf["items"] if x["publish"]["id"]==pub["id"])
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
require('data-i18n="intel.title"' in html,"Factory Intelligence title is not localized")
require("FactoryOS v3.14" not in html,"stale document title version returned")
require('data-i18n="brain.title"' in html,"Content Brain workspace missing")
require('data-i18n="variant.title"' in html,"Variant Studio workspace missing")
require('data-i18n="package.title"' in html,"Content Package workspace missing")
require('data-i18n="approval.title"' in html,"Approval Studio workspace missing")
require('data-i18n="publishing.title"' in html,"Publishing Engine workspace missing")
require('data-i18n="performance.title"' in html,"Performance Feedback workspace missing")
require('data-i18n="experiment.title"' in html,"Experiment Lab workspace missing")
require('data-i18n="cycle.title"' in html,"Autonomous Cycle Control workspace missing")
require("openApprovalStudio" in html and "approvalRegenerate" in html,"Approval Studio controls missing")
require("openPublishingStudio" in html and "publishQueueItem" in html,"Publishing controls missing")
require("openPerformanceStudio" in html and "addPerformanceSnapshot" in html,"Performance controls missing")
require("openExperimentLab" in html and "evaluateExperiment" in html and "rolloutExperiment" in html and "rollbackExperiment" in html,"Experiment Lab controls missing")
require("openAutonomousFactory" in html and "runFactoryCycle" in html and "nextFactoryCycle" in html,"Autonomous Cycle controls missing")
require('onclick="openPackageStudio()"' in html,"Content Package action missing")
require("buildContentPackage" in html and "renderPackageStudio" in html,"Content Package controls missing")
require('onclick="openVariantStudio()"' in html,"Variant Studio action missing")
require("rerunVariant" in html and "buildVariants" in html,"Variant Studio controls missing")
require('onclick="openContentBrain()"' in html,"Content Brain navigation missing")
require("runBrainFull()" in html and "processBrainIdea" in html,"Content Brain mobile actions missing")
require('<span class="version">v4.0</span>' in html,"visible UI version mismatch")
require("v3.24 mobile parity" in html,"mobile parity CSS marker missing")
require(".agent{display:none}" not in html,"mobile CSS must not hide clickable worker cards")
require("#agentBadges{position:relative;display:grid" in html,"mobile worker grid missing")
for key in ("approval.nav","approval.title","publishing.nav","publishing.title","performance.nav","performance.title","experiment.nav","experiment.title","experiment.sub","cycle.nav","cycle.title","cycle.sub","cycle.run","cycle.review","cycle.next","brain.nav","brain.title","brain.run","brain.verifyOne","brain.createJob","variant.nav","variant.title","variant.build","variant.select","variant.rerun","package.nav","package.title","package.build","package.scenes","package.adapters","nav.errors","error.title","error.confirmUncertain","worker.title","worker.noHandoffs","trace.title","trace.loadFailed","intel.title","intel.workerComparison","intel.note","nav.qa","qa.title","qa.loading"):
    require(html.count(f'"{key}":')==3,f"i18n key {key} must exist in EN/UK/RU")
print("FactoryOS v4.0 smoke/regression suite passed without paid provider calls")
