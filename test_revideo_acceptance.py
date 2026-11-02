"""T-540 Revideo zero-spend acceptance.

Drives the full safe content path on deterministic fixtures, in an isolated DATA_DIR with no LLM key:

  Discovery candidate -> Revideo analysis -> original rewrite -> production job -> variants -> Content Package
  -> Media Finisher (worker callback simulated, no network) -> HUMAN APPROVAL (waiting_approval)

and proves at the approval boundary that:
  * provenance is intact: discovery candidate/metrics, source URL, Revideo project, source signal, idea and job all
    stay linked, and the Content Package source list cites the original public source;
  * originality evidence is intact: the mechanical overlap guard result recorded on the project is the same one carried
    by the idea provenance and the job's rewrite artifact, and a copied rewrite is fenced before production;
  * no real provider spend happened: no LLM call, no outbound HTTP, every agent run and the finisher cost $0.00;
  * nothing can auto-publish: no publish item exists before approval, the due-publisher sweep is a no-op, approval
    itself only queues a manual item, and publishing still requires an explicit schedule step.
"""
import asyncio
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-revideo-acceptance-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory

SOURCE_URL = "https://example.com/watch/t540-public-source"
RAW_URL = "https://example.com/t540-raw-render.mp4"
FINAL_URL = "https://example.com/t540-finished.mp4"
TRANSCRIPT = (
    "Most people think batteries fail because they get old. The real reason is heat during fast charging. "
    "Every degree above thirty adds measurable wear to the cells. Keep your phone cool while it charges."
)

outbound = []


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def no_network(*args, **kwargs):
    outbound.append(args[0] if args else kwargs)
    raise AssertionError("T-540 acceptance must not make outbound provider calls")


def no_llm(*args, **kwargs):
    outbound.append(("llm", args[0] if args else ""))
    raise AssertionError("T-540 acceptance must not call a live LLM")


def total_spend():
    con = factory.db()
    runs = float(con.execute("SELECT COALESCE(SUM(cost_usd),0) c FROM agent_runs").fetchone()["c"] or 0)
    edits = float(con.execute("SELECT COALESCE(SUM(measured_cost_usd),0) c FROM edit_jobs").fetchone()["c"] or 0)
    con.close()
    return runs, edits


def publish_rows():
    con = factory.db()
    rows = [dict(x) for x in con.execute("SELECT * FROM publishing_queue").fetchall()]
    con.close()
    return rows


def run_acceptance():
    require(not factory.FACTORY_LLM_API_KEY, "acceptance must run without an LLM key")
    require(factory.get_media_finisher_registry()["configured"] is False, "acceptance must not see a live Media Finisher")

    # 1. Discovery candidate with factual, source-supplied metrics.
    cand = factory.ingest_discovery_candidate(factory.DiscoveryCandidateCreate(
        platform="youtube", source_url=SOURCE_URL, external_id="t540-video", title="Why phone batteries really die",
        creator="Public Creator", topic="battery health", language="en", content_type="short",
        views=250000, vph=812.5, engagement_rate=0.061, breakout_score=4.2, duration_sec=38,
        transcript=TRANSCRIPT,
    ), source="t540_fixture")["candidate"]
    require(cand["status"] == "new", "fixture candidate must start as new")

    # 2. Revideo handoff + zero-spend quote.
    handoff = factory.discovery_candidate_to_revideo(cand["id"], "English")
    project_id = handoff["project"]["id"]
    require(handoff["created"] is True, "Discovery -> Revideo handoff must create a project")
    require(factory.discovery_candidate_to_revideo(cand["id"], "English")["created"] is False,
            "Discovery -> Revideo handoff must be idempotent")
    quote = factory._revideo_quote(factory.get_revideo_project(project_id))
    require(quote["paid_calls_possible"] is False and quote["estimated_max_usd"] == 0.0,
            "Revideo quote must be zero-spend without an LLM key")

    # 3. Analysis + original rewrite + originality guard.
    ready = asyncio.run(factory.run_revideo_analysis(project_id, "English"))
    require(ready["status"] == "ready", "deterministic rewrite must pass the originality guard")
    originality = ready["originality"]
    require(originality["passed"] is True and originality["five_word_shingle_overlap"] < originality["threshold"],
            "originality evidence must record a passing overlap below threshold")
    for key in factory.REVIDEO_REQUIRED_REWRITE_FIELDS:
        require(ready["rewrite"].get(key), f"rewrite is missing required field {key}")
    require(ready["rewrite"]["source_links"][0] == SOURCE_URL, "rewrite must cite the original source first")

    # 4. Production job (signal -> idea -> job lineage).
    prod = factory.create_revideo_production_job(project_id)
    job_id = prod["job"]["id"]
    require(prod["created"] is True and job_id, "Revideo -> production job handoff failed")
    require(factory.create_revideo_production_job(project_id)["created"] is False,
            "production handoff must be idempotent")

    # 5. Variants + Content Package.
    variants = asyncio.run(factory.run_variant_pipeline(job_id, 3))
    require(variants["summary"]["selected"] == 1, "variant pipeline must select exactly one production variant")
    package = asyncio.run(factory.generate_content_package(job_id))
    require(package["status"] == "ready" and package["package"]["final_script"], "Content Package must be ready")

    early = asyncio.run(factory.approve(job_id))
    require(early["ok"] is False and factory.get_job(job_id)["status"] != "approved",
            "approval must be impossible before the job reaches waiting_approval")

    # 6. Media Finisher: queued against a non-routable endpoint; submit thread stubbed; worker result simulated.
    factory.save_artifact("Render Agent", "video", "T-540 raw render", "", job_id=job_id, url=RAW_URL,
                          mime_type="video/mp4", meta={"fixture": True, "source": "T-540"})
    with patch.object(factory, "FACTORY_MEDIA_FINISHER_ENDPOINT", "https://ci.invalid/finish"), \
            patch.object(factory, "_spawn_media_finisher_submit", lambda edit_job_id: None):
        edit = factory.start_media_finisher(job_id, factory.MediaFinisherStartRequest(
            profile_id="revideo_finish", profile_version=1, platform="reels", input_url=RAW_URL,
            edit_full_video=True, split_shortform=False, add_captions=True, add_animation=True,
            smart_graphics=True, max_short_clips=1, confirm_external_cost=True,
        ))["edit_job"]
        require(edit["status"] == "queued" and not edit["provider_job_id"], "finisher must only queue, not submit")
        guardrails = edit["request"]["guardrails"]
        require(guardrails["no_auto_publish"] is True and guardrails["preserve_approved_facts"] is True,
                "finisher request must carry no-auto-publish / preserve-facts guardrails")
        require(edit["request"]["content_package"]["package_id"] == package["package_record"]["id"],
                "finisher must be bound to the exact ready Content Package")
        report = {
            "transcript_words": [{"word": "Battery", "start": 0.0, "end": 0.4}, {"word": "heat", "start": 0.4, "end": 0.8}],
            "cut_list": [], "caption_timeline": [{"start": 0.0, "end": 0.8, "words": ["Battery", "heat"]}],
            "motion_timeline": [], "graphics_timeline": [], "shorts_manifest": {"enabled": False, "clips": []},
            "audio_report": {"voice_lufs": -14.0}, "safe_zone_report": {"violations": []},
            "edit_summary": {"duration_before_sec": 12.0, "duration_after_sec": 11.5, "human_review_required": True},
        }
        finished = factory._finalize_edit_job(edit["id"], "completed", FINAL_URL, "ci-t540-finisher", "",
                                              {"status": "completed"}, report, 0.0, 11.5)
    require(finished["status"] == "ready", "finisher fixture must reach ready")

    # ---- HUMAN APPROVAL boundary ----
    job = factory.get_job(job_id)
    require(job["status"] == "waiting_approval", f"acceptance must stop at waiting_approval, got {job['status']}")
    review = factory._media_review_state(job_id)
    require(review["ready"] is True and review["source_binding_ok"] is True and
            (review["artifact"] or {}).get("url") == FINAL_URL,
            "exact finished media must be bound to the current package and ready for human review")
    queue_item = next((x for x in factory.get_approval_queue()["items"] if x["job"]["id"] == job_id), None)
    require(queue_item and queue_item["review_ready"] is True, "job must be review-ready in Approval Studio")

    # Provenance intact.
    project = factory.get_revideo_project(project_id)
    prov = project["provenance"]
    require(project["status"] == "in_production" and project["job_id"] == job_id, "project/job link lost")
    require(prov.get("discovery_candidate_id") == cand["id"], "discovery candidate provenance lost")
    require(prov.get("discovery_metrics") == {"views": 250000, "vph": 812.5, "engagement_rate": 0.061, "breakout_score": 4.2},
            "discovery metrics provenance changed or lost")
    require(prov.get("source_url") == SOURCE_URL and prov.get("copyright_mode") == "original_rewrite_only",
            "source/copyright provenance lost")
    require(prov.get("voice_identity_imitation") is False and prov.get("auto_publish") is False and
            prov.get("human_approval_required") is True, "safety provenance flags changed")
    candidate_after = factory.get_discovery_candidate(cand["id"])
    require(candidate_after["status"] == "sent_to_revideo" and candidate_after["revideo_project_id"] == project_id,
            "discovery candidate linkage lost")
    con = factory.db()
    signal = con.execute("SELECT url FROM source_signals WHERE id=?", (project["source_signal_id"],)).fetchone()
    idea = con.execute("SELECT provenance_json FROM content_ideas WHERE id=?", (project["idea_id"],)).fetchone()
    con.close()
    require(signal and signal["url"] == SOURCE_URL, "source signal must keep the original URL")
    idea_rev = factory._decode_json(idea["provenance_json"], {}).get("revideo") or {}
    require(idea_rev.get("project_id") == project_id and idea_rev.get("source_url") == SOURCE_URL,
            "idea provenance must link the Revideo project and source")
    package_urls = [x.get("value") for x in factory.get_content_package(job_id)["package"]["source_list"] if x.get("type") == "url"]
    require(SOURCE_URL in package_urls, "Content Package source list must cite the original public source")

    # Originality evidence intact and consistent across the chain.
    require(project["originality"] == originality, "project originality evidence changed after production")
    require(idea_rev.get("originality") == originality, "idea provenance must carry the same originality evidence")
    con = factory.db()
    rewrite_art = con.execute("""SELECT meta_json FROM artifacts WHERE job_id=? AND agent='Editor'
                                 AND title='Revideo original rewrite'""", (job_id,)).fetchone()
    con.close()
    require(rewrite_art and factory._decode_json(rewrite_art["meta_json"], {}).get("originality") == originality,
            "job rewrite artifact must carry the originality evidence to the reviewer")
    require(factory._originality_check(TRANSCRIPT, project["rewrite"]["original_script"]) == originality,
            "recorded originality evidence must be reproducible from the stored rewrite")

    # Zero spend.
    runs_usd, edits_usd = total_spend()
    require(runs_usd == 0.0 and edits_usd == 0.0, f"acceptance recorded spend: runs={runs_usd} finisher={edits_usd}")
    require(factory.get_job_cost(job_id) == 0.0, "job cost must be $0.00")
    con = factory.db()
    live_runs = con.execute("SELECT COUNT(*) c FROM agent_runs WHERE meta_json LIKE '%live_llm%'").fetchone()["c"]
    con.close()
    require(live_runs == 0, "no agent run may be recorded as a live LLM call")

    # Cannot auto-publish.
    require(publish_rows() == [], "no publish item may exist before human approval")
    swept = asyncio.run(factory.run_due_publishing())
    require(swept["processed"] == 0 and factory.get_job(job_id)["status"] == "waiting_approval",
            "the due-publisher sweep must not touch a waiting_approval job")

    # Explicit human approval only queues a manual item; it never posts.
    approved = asyncio.run(factory.approve(job_id))
    require(approved["ok"] is True and approved["publish"]["status"] == "approved", "human approval must queue the job")
    item = approved["publish"]
    require(item["target"] == "manual" and not item.get("scheduled_at") and not item.get("external_post_id")
            and not item.get("published_at"), "approval must not schedule or fabricate a post")
    require(item["media"]["url"] == FINAL_URL, "approved publish item must bind the exact reviewed media")
    require(asyncio.run(factory.run_due_publishing())["processed"] == 0, "approved-but-unscheduled item must not auto-publish")
    blocked = asyncio.run(factory.publish_scheduled_item(item["id"]))
    require(blocked["ok"] is False and "schedul" in blocked["message"].lower(),
            "publishing must still require an explicit schedule step")
    rows = publish_rows()
    require(len(rows) == 1 and rows[0]["status"] == "approved" and rows[0]["external_post_id"] is None,
            "no external post may exist after acceptance")


def run_originality_fence():
    """A rewrite that copies source wording must be stopped before production."""
    project = factory.create_revideo_project(factory.RevideoCreateRequest(
        source_url="https://example.com/watch/t540-copy", source_title="Copy fence", topic="battery health",
        transcript=TRANSCRIPT, language="English",
    ))
    real_demo = factory._demo_revideo

    def copying_demo(proj, transcript):
        analysis, rewrite = real_demo(proj, transcript)
        rewrite["original_script"] = transcript
        return analysis, rewrite

    with patch.object(factory, "_demo_revideo", copying_demo):
        copied = asyncio.run(factory.run_revideo_analysis(project["id"], "English"))
    require(copied["status"] == "needs_revision" and copied["originality"]["passed"] is False,
            "copied rewrite must fail the originality guard")
    try:
        factory.create_revideo_production_job(project["id"])
    except ValueError:
        pass
    else:
        raise AssertionError("copied rewrite must not be allowed into production")
    require(not factory.get_revideo_project(project["id"]).get("job_id"), "copied rewrite must not get a job")


def main():
    with patch.object(factory.urlrequest, "urlopen", no_network), \
            patch.object(factory, "_external_json", no_network), \
            patch.object(factory, "_content_brain_llm", no_llm):
        run_acceptance()
        run_originality_fence()
    require(outbound == [], f"outbound provider calls attempted: {outbound}")
    print("T-540 Revideo zero-spend acceptance passed")


if __name__ == "__main__":
    main()
