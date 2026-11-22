"""T-542 Publishing dry-run evidence regression.

Deterministic fixture (no LLM key, no outbound HTTP, $0.00): Revideo -> production job -> variants -> Content Package ->
Media Finisher (simulated worker result) -> HUMAN APPROVAL -> manual publish item. Checks:
  * POST /api/publishing/{id}/dry-run builds the exact YouTube Shorts / TikTok / Instagram Reels publisher payloads
    from the immutable approved snapshot and the exact approved media URL, with AI disclosure metadata;
  * the dry-run is persisted as a traceable Publisher `publish_dry_run` artifact bound to publish_id, idempotency key,
    content snapshot hash and media artifact; re-running the same snapshot is idempotent;
  * the receipt preview never carries an external post ID/URL, no `publish_receipt` is written and the publish item,
    job and cycle state are untouched;
  * a tampered snapshot or swapped media blocks every platform plan; unconfigured YouTube audience blocks only YouTube;
  * real publishing stays fenced behind T-520/T-521 even when a Metricool adapter is configured, no provider call is
    attempted, and the route stays behind session auth.
"""
import asyncio
import json
import os
import tempfile
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-publish-dry-run-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory

SOURCE_URL = "https://example.com/watch/t542-public-source"
RAW_URL = "https://example.com/t542-raw-render.mp4"
FINAL_URL = "https://example.com/t542-finished.mp4"
TRANSCRIPT = (
    "Most people think batteries fail because they get old. The real reason is heat during fast charging. "
    "Every degree above thirty adds measurable wear to the cells. Keep your phone cool while it charges."
)
PLATFORMS = ["youtube_shorts", "tiktok", "instagram_reels"]

outbound = []


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def no_network(*args, **kwargs):
    outbound.append(args[0] if args else kwargs)
    raise AssertionError("T-542 regression must not make outbound provider calls")


def call(method, path):
    """One request through the full ASGI app (middleware included). Returns (status, body bytes)."""
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode("utf-8"), "query_string": b"",
             "headers": [(b"host", b"testserver")], "server": ("testserver", 80), "client": ("127.0.0.1", 50000),
             "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


def dry_run(publish_id):
    status, body = call("POST", f"/api/publishing/{publish_id}/dry-run")
    require(status == 200, f"dry-run must be 200, got {status}: {body[:200]!r}")
    return json.loads(body)


def build_approved_item():
    cand = factory.ingest_discovery_candidate(factory.DiscoveryCandidateCreate(
        platform="youtube", source_url=SOURCE_URL, external_id="t542-video", title="Why phone batteries really die",
        creator="Public Creator", topic="battery health", language="en", content_type="short",
        views=1000, vph=10.0, engagement_rate=0.05, breakout_score=2.0, duration_sec=38, transcript=TRANSCRIPT,
    ), source="t542_fixture")["candidate"]
    project_id = factory.discovery_candidate_to_revideo(cand["id"], "English")["project"]["id"]
    require(asyncio.run(factory.run_revideo_analysis(project_id, "English"))["status"] == "ready", "rewrite fixture")
    job_id = factory.create_revideo_production_job(project_id)["job"]["id"]
    asyncio.run(factory.run_variant_pipeline(job_id, 3))
    require(asyncio.run(factory.generate_content_package(job_id))["status"] == "ready", "Content Package fixture")
    factory.save_artifact("Render Agent", "video", "T-542 raw render", "", job_id=job_id, url=RAW_URL,
                          mime_type="video/mp4", meta={"fixture": True})
    with patch.object(factory, "FACTORY_MEDIA_FINISHER_ENDPOINT", "https://ci.invalid/finish"), \
            patch.object(factory, "_spawn_media_finisher_submit", lambda edit_job_id: None):
        edit = factory.start_media_finisher(job_id, factory.MediaFinisherStartRequest(
            profile_id="revideo_finish", profile_version=1, platform="reels", input_url=RAW_URL,
            edit_full_video=True, split_shortform=False, add_captions=True, add_animation=False,
            smart_graphics=False, max_short_clips=0, confirm_external_cost=True,
        ))["edit_job"]
        finished = factory._finalize_edit_job(edit["id"], "completed", FINAL_URL, "ci-t542-finisher", "",
                                              {"status": "completed"}, {"edit_summary": {"human_review_required": True}},
                                              0.0, 11.0)
    require(finished["status"] == "ready", "finisher fixture must reach ready")
    approved = asyncio.run(factory.approve(job_id))
    require(approved["ok"] is True, f"approval fixture failed: {approved}")
    item = approved["publish"]
    require(item["status"] == "approved" and item["target"] == "manual" and not item.get("external_post_id"),
            "approval must only queue a manual publish item")
    require(item["media"]["url"] == FINAL_URL and item["content_snapshot_hash"], "approved snapshot must be bound")
    return job_id, item


def queue_row(publish_id):
    con = factory.db()
    row = dict(con.execute("SELECT * FROM publishing_queue WHERE id=?", (publish_id,)).fetchone())
    con.close()
    return row


def count_artifacts(job_id, kind):
    con = factory.db()
    n = con.execute("SELECT COUNT(*) c FROM artifacts WHERE job_id=? AND agent='Publisher' AND kind=?",
                    (job_id, kind)).fetchone()["c"]
    con.close()
    return n


def check_dry_run(job_id, item):
    before = queue_row(item["id"])
    job_before = factory.get_job(job_id)
    with patch.object(factory, "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", "false"):
        result = dry_run(item["id"])
    require(result["ok"] is True and result["dry_run"] is True, "dry-run must succeed")
    require(result["spend_usd"] == 0.0 and result["outbound_calls"] == 0, "dry-run must be zero-spend")
    binding = result["binding"]
    require(binding["ok"] is True and binding["media_verified"] is True, f"binding must verify: {binding['problems']}")
    require(binding["content_snapshot_hash"] == item["content_snapshot_hash"] == binding["recomputed_hash"],
            "binding must use the exact approved snapshot hash")
    require(binding["media_artifact_id"] == item["media"]["artifact_id"] and binding["media_url"] == FINAL_URL,
            "binding must use the exact approved media artifact")
    require(result["content_snapshot"] == item["content_snapshot"], "content must be the approved snapshot verbatim")

    plans = {p["platform"]: p for p in result["plans"]}
    require(list(plans) == PLATFORMS, f"plans must cover {PLATFORMS}, got {list(plans)}")
    snapshot = item["content_snapshot"]
    for platform, plan in plans.items():
        require(plan["ready"] is True and plan["blockers"] == [], f"{platform} plan blocked: {plan['blockers']}")
        payload = plan["payload"]
        require(payload["media"] == [FINAL_URL], f"{platform} must bind the exact approved media URL")
        require(payload["text"] == factory._metricool_post_text(snapshot), f"{platform} text must come from the snapshot")
        require(snapshot["description"] and snapshot["description"] in payload["text"], f"{platform} lost the description")
    require(plans["youtube_shorts"]["network"] == "youtube"
            and plans["youtube_shorts"]["payload"]["youtubeData"]["type"] == "short"
            and plans["youtube_shorts"]["payload"]["youtubeData"]["isAiGeneratedContent"] is True
            and plans["youtube_shorts"]["payload"]["youtubeData"]["madeForKids"] is False
            and plans["youtube_shorts"]["payload"]["youtubeData"]["title"] == snapshot["title"],
            "YouTube Shorts mapping/disclosure")
    require(plans["tiktok"]["network"] == "tiktok" and plans["tiktok"]["payload"]["tiktokData"]["isAigc"] is True,
            "TikTok mapping/disclosure")
    require(plans["instagram_reels"]["network"] == "instagram"
            and plans["instagram_reels"]["payload"]["instagramData"]["type"] == "REEL"
            and plans["instagram_reels"]["payload"]["instagramData"]["isAiGenerated"] is True,
            "Instagram Reels mapping/disclosure")

    receipt = result["receipt_preview"]
    require(receipt["dry_run"] is True and receipt["status"] == "not_published", "receipt preview must be a dry-run")
    require(receipt["external_post_id"] is None and receipt["external_url"] is None, "no external post ID may be fabricated")
    require(receipt["publish_id"] == item["id"] and receipt["idempotency_key"] == item["idempotency_key"]
            and receipt["content_snapshot_hash"] == item["content_snapshot_hash"]
            and receipt["media_artifact_id"] == item["media"]["artifact_id"]
            and receipt["plan_hash"] == result["plan_hash"] and receipt["platforms"] == PLATFORMS,
            "receipt preview must be traceable to the approved snapshot")
    real = result["real_publish"]
    require(real["allowed"] is False and any(b.startswith("T-520") for b in real["blockers"])
            and any(b.startswith("T-521") for b in real["blockers"]), "real publish must stay fenced by T-520/T-521")

    con = factory.db()
    row = con.execute("SELECT * FROM artifacts WHERE id=?", (result["artifact_id"],)).fetchone()
    con.close()
    require(row and row["agent"] == "Publisher" and row["kind"] == "publish_dry_run" and row["job_id"] == job_id,
            "dry-run evidence must be persisted as a Publisher artifact")
    meta = json.loads(row["meta_json"])
    require(meta["publish_id"] == item["id"] and meta["plan_hash"] == result["plan_hash"]
            and meta["content_snapshot_hash"] == item["content_snapshot_hash"] and meta["dry_run"] is True,
            "artifact meta must carry the traceable binding")
    stored = json.loads(row["content"])
    require(stored["receipt_preview"]["external_post_id"] is None and stored["plan_hash"] == result["plan_hash"],
            "stored evidence must match the response")

    with patch.object(factory, "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", "false"):
        again = dry_run(item["id"])
    require(again["idempotent"] is True and again["artifact_id"] == result["artifact_id"]
            and again["plan_hash"] == result["plan_hash"], "same snapshot must reuse the same dry-run evidence")
    require(count_artifacts(job_id, "publish_dry_run") == 1, "idempotent dry-run must not duplicate evidence")

    after = queue_row(item["id"])
    require(after == before, "dry-run must not mutate the publish item")
    require(after["external_post_id"] is None and after["attempt_count"] == 0 and after["status"] == "approved",
            "publish item must stay approved with no attempt or post ID")
    require(count_artifacts(job_id, "publish_receipt") == 0, "dry-run must not write a publish receipt")
    job_after = factory.get_job(job_id)
    require(job_after["status"] == job_before["status"] and job_after["status"] != "published",
            "dry-run must not mark the job published")
    print(f"OK dry-run plans {len(plans)} platforms bound to snapshot {item['content_snapshot_hash'][:12]} "
          f"and media {FINAL_URL}; no post ID, receipt or state change")
    return result


def check_blockers(job_id, item, baseline):
    with patch.object(factory, "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", ""):
        partial = dry_run(item["id"])
    plans = {p["platform"]: p for p in partial["plans"]}
    require(plans["youtube_shorts"]["ready"] is False and plans["youtube_shorts"]["payload"] is None
            and "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS" in plans["youtube_shorts"]["blockers"][0],
            "unset YouTube audience must block only the YouTube plan")
    require(plans["tiktok"]["ready"] and plans["instagram_reels"]["ready"], "other platforms stay plannable")
    require(partial["receipt_preview"]["platforms"] == ["tiktok", "instagram_reels"]
            and partial["plan_hash"] != baseline["plan_hash"], "a different plan must get different evidence")

    original = queue_row(item["id"])["meta_json"]
    meta = json.loads(original)
    meta["content_snapshot"] = {**meta["content_snapshot"], "title": "Edited after approval"}
    con = factory.db()
    con.execute("UPDATE publishing_queue SET meta_json=? WHERE id=?", (json.dumps(meta), item["id"]))
    con.commit(); con.close()
    tampered = dry_run(item["id"])
    require(tampered["binding"]["ok"] is False and all(not p["ready"] and p["payload"] is None for p in tampered["plans"]),
            "an edited snapshot must block every platform plan")
    require(any("hash" in p for p in tampered["binding"]["problems"]), "tamper reason must be reported")
    require(tampered["receipt_preview"]["platforms"] == [] and tampered["receipt_preview"]["external_post_id"] is None,
            "blocked dry-run must not claim any platform")

    meta = json.loads(original)
    meta["media_url"] = "https://example.com/t542-swapped.mp4"
    con = factory.db()
    con.execute("UPDATE publishing_queue SET meta_json=? WHERE id=?", (json.dumps(meta), item["id"]))
    con.commit(); con.close()
    swapped = dry_run(item["id"])
    require(swapped["binding"]["ok"] is False and swapped["binding"]["media_verified"] is False
            and all(not p["ready"] for p in swapped["plans"]), "swapped media must block every platform plan")

    con = factory.db()
    con.execute("UPDATE publishing_queue SET meta_json=? WHERE id=?", (original, item["id"]))
    con.commit(); con.close()
    print("OK tampered snapshot / swapped media block all plans; unset YouTube audience blocks only YouTube")


def check_fences(job_id, item):
    with patch.object(factory, "FACTORY_PUBLISHER_ADAPTER", "metricool"), \
            patch.object(factory, "_metricool_configured", lambda: True), \
            patch.object(factory, "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", "false"):
        configured = dry_run(item["id"])
    real = configured["real_publish"]
    require(real["allowed"] is False and real["adapter_configured"] is True
            and not any(b.startswith("T-520") for b in real["blockers"])
            and any(b.startswith("T-521") for b in real["blockers"]),
            "a configured adapter still requires T-521 owner approval for a real post")
    require(all(p["ready"] for p in configured["plans"]), "configured adapter dry-run must still plan all platforms")
    require(queue_row(item["id"])["status"] == "approved", "configured dry-run must not schedule or publish")

    # T-552-YT: a configured YouTube-only adapter flags platforms it cannot publish.
    yt_ready = {"configured": True, "blockers": [], "channel_title": "Fixture", "privacy": "private",
                "audience_configured": True}
    con = factory.db()
    con.execute("UPDATE publishing_queue SET platform='tiktok' WHERE id=?", (item["id"],))
    con.commit(); con.close()
    with patch.object(factory, "FACTORY_PUBLISHER_ADAPTER", "youtube"), \
            patch.object(factory, "_youtube_publisher_state", lambda workspace=None: yt_ready), \
            patch.object(factory, "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", "false"):
        yt_plan = dry_run(item["id"])
    con = factory.db()
    con.execute("UPDATE publishing_queue SET platform='unspecified' WHERE id=?", (item["id"],))
    con.commit(); con.close()
    support = {p["platform"]: p.get("real_publisher_supported") for p in yt_plan["plans"]}
    require(support == {"youtube_shorts": True, "tiktok": False, "instagram_reels": False},
            f"per-platform support must follow the YouTube adapter: {support}")
    require(any("does not support tiktok" in b for b in yt_plan["real_publish"]["blockers"]),
            "a TikTok item must keep a T-520 blocker while only YouTube is configured")

    status, _ = call("POST", "/api/publishing/no-such-item/dry-run")
    require(status == 404, f"unknown publish item must 404, got {status}")
    with patch.object(factory, "FACTORY_PASSWORD", "t542-owner-pass"):
        status, _ = call("POST", f"/api/publishing/{item['id']}/dry-run")
    require(status == 401, f"dry-run must stay behind session auth, got {status}")

    con = factory.db()
    con.execute("UPDATE publishing_queue SET status='published' WHERE id=?", (item["id"],))
    con.commit(); con.close()
    refused = dry_run(item["id"])
    require(refused["ok"] is False and "published" in refused["message"], "a published item must not be re-planned")
    con = factory.db()
    con.execute("UPDATE publishing_queue SET status='approved' WHERE id=?", (item["id"],))
    con.commit(); con.close()
    require(count_artifacts(job_id, "publish_receipt") == 0, "no publish receipt may appear at any point")
    print("OK real publish fenced by T-520/T-521 even with a configured adapter; 404/401/published refusals hold")


def main():
    factory.init_db()
    with patch.object(factory.urlrequest, "urlopen", no_network), \
            patch.object(factory, "_external_json", no_network), \
            patch.object(factory, "_metricool_json", no_network), \
            patch.object(factory, "_metricool_normalize_media_url", no_network), \
            patch.object(factory, "_content_brain_llm", no_network):
        job_id, item = build_approved_item()
        baseline = check_dry_run(job_id, item)
        check_blockers(job_id, item, baseline)
        check_fences(job_id, item)
    require(outbound == [], f"outbound provider calls attempted: {outbound}")
    print("T-542 Publishing dry-run evidence regression: PASS")


if __name__ == "__main__":
    main()
