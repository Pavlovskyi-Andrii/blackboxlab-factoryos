"""T-541 Media Finisher operator preview regression.

Deterministic fixture (no LLM key, no outbound HTTP, $0.00): Revideo -> production job -> variants -> Content Package ->
Media Finisher (worker result simulated with a deliberately partial report) -> HUMAN APPROVAL. Checks:
  * GET /api/jobs/{id}/media-finisher/preview (and the same block on /api/approval items) exposes the source (before)
    and finished (after) media, the produced short cuts and every cuts/captions/audio/graphics/QA artifact that exists;
  * optional artifacts the worker did not produce are listed as not produced instead of being hidden;
  * every exposed link resolves through the stable /api/artifacts/{id}/media route, and the preview stays behind
    session auth;
  * the approval gate is unchanged: the preview mirrors it, a not-ready finisher run still blocks approve(), and
    approval only queues a manual publish item;
  * the real dashboard renderer (finisherPreviewHtml under node) emits those links, marks absent artifacts and does
    not carry any approve action.
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-finisher-preview-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory

HTML = Path(__file__).resolve().parent / "static" / "index.html"
SOURCE_URL = "https://example.com/watch/t541-public-source"
RAW_URL = "https://example.com/t541-raw-render.mp4"
FINAL_URL = "https://example.com/t541-finished.mp4"
SHORT_URL = "https://example.com/t541-short-01.mp4"
TRANSCRIPT = (
    "Most people think batteries fail because they get old. The real reason is heat during fast charging. "
    "Every degree above thirty adds measurable wear to the cells. Keep your phone cool while it charges."
)
# Produced on purpose; everything else in MEDIA_FINISHER_EVIDENCE is absent and must be marked as not produced.
PRODUCED = {"cut_list", "shorts_manifest", "caption_timeline", "audio_report", "edit_summary"}

outbound = []


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def no_network(*args, **kwargs):
    outbound.append(args[0] if args else kwargs)
    raise AssertionError("T-541 regression must not make outbound provider calls")


def call(path, query="", cookie=None):
    """One GET through the full ASGI app (middleware included). Returns (status, headers dict, body bytes)."""
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode("ascii")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": path, "raw_path": path.encode("utf-8"), "query_string": query.encode("ascii"),
             "headers": headers, "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    return start["status"], {k.decode().lower(): v.decode() for k, v in start["headers"]}, body


def get_json(path):
    path, _, query = path.partition("?")
    status, _, body = call(path, query)
    require(status == 200, f"GET {path} must be 200, got {status}: {body[:200]!r}")
    return json.loads(body)


def build_fixture():
    cand = factory.ingest_discovery_candidate(factory.DiscoveryCandidateCreate(
        platform="youtube", source_url=SOURCE_URL, external_id="t541-video", title="Why phone batteries really die",
        creator="Public Creator", topic="battery health", language="en", content_type="short",
        views=1000, vph=10.0, engagement_rate=0.05, breakout_score=2.0, duration_sec=38, transcript=TRANSCRIPT,
    ), source="t541_fixture")["candidate"]
    project_id = factory.discovery_candidate_to_revideo(cand["id"], "English")["project"]["id"]
    require(asyncio.run(factory.run_revideo_analysis(project_id, "English"))["status"] == "ready", "rewrite fixture")
    job_id = factory.create_revideo_production_job(project_id)["job"]["id"]
    asyncio.run(factory.run_variant_pipeline(job_id, 3))
    require(asyncio.run(factory.generate_content_package(job_id))["status"] == "ready", "Content Package fixture")
    raw_id = factory.save_artifact("Render Agent", "video", "T-541 raw render", "", job_id=job_id, url=RAW_URL,
                                   mime_type="video/mp4", meta={"fixture": True})
    return job_id, raw_id


def check_no_finisher_run(job_id):
    preview = get_json(f"/api/jobs/{job_id}/media-finisher/preview")
    require(preview["available"] is False and preview["edit_job"] is None and preview["groups"] == [],
            "a job without a Media Finisher run must say so, not invent evidence")
    require(preview["approval_gate"]["human_approval_required"] is True and preview["approval_gate"]["auto_publish"] is False,
            "preview must always state the human approval gate")
    status, _, _ = call("/api/jobs/no-such-job/media-finisher/preview")
    require(status == 404, f"unknown job must 404, got {status}")
    print("OK job without a finisher run reports no preview; unknown job 404s")


def run_finisher(job_id):
    with patch.object(factory, "FACTORY_MEDIA_FINISHER_ENDPOINT", "https://ci.invalid/finish"), \
            patch.object(factory, "_spawn_media_finisher_submit", lambda edit_job_id: None):
        edit = factory.start_media_finisher(job_id, factory.MediaFinisherStartRequest(
            profile_id="revideo_finish", profile_version=1, platform="reels", input_url=RAW_URL,
            edit_full_video=True, split_shortform=True, add_captions=True, add_animation=False,
            smart_graphics=False, max_short_clips=1, confirm_external_cost=True,
        ))["edit_job"]
        queued = get_json(f"/api/jobs/{job_id}/media-finisher/preview")
        require(queued["available"] is True and queued["edit_job"]["status"] == "queued", "queued run must be visible")
        require(queued["final"] is None and queued["shorts"] == [], "a queued run has no finished media yet")
        require(all(g["available"] == 0 for g in queued["groups"]), "a queued run must not claim any evidence")
        require(queued["approval_gate"]["ready"] is False and queued["approval_gate"]["reason"],
                "a queued run must show the blocked approval gate with its reason")
        report = {
            "cut_list": [{"start": 1.0, "end": 1.6, "reason": "silence>0.4s"}],
            "caption_timeline": [{"start": 0.0, "end": 0.8, "words": ["Battery", "heat"]}],
            "shorts_manifest": {"enabled": True, "human_review_required": True,
                                "clips": [{"index": 1, "start_sec": 0.0, "end_sec": 9.5, "url": SHORT_URL}]},
            "audio_report": {"voice_lufs": -14.0},
            "edit_summary": {"duration_before_sec": 12.0, "duration_after_sec": 11.0, "human_review_required": True},
        }
        finished = factory._finalize_edit_job(edit["id"], "completed", FINAL_URL, "ci-t541-finisher", "",
                                              {"status": "completed"}, report, 0.0, 11.0)
    require(finished["status"] == "ready", "finisher fixture must reach ready")
    return edit["id"]


def check_preview(job_id, raw_id, edit_id):
    preview = get_json(f"/api/jobs/{job_id}/media-finisher/preview")
    require(preview["available"] is True and preview["edit_job"]["id"] == edit_id, "preview must bind the latest run")
    require(preview["source"] and preview["source"]["id"] == raw_id and preview["source"]["url"] == RAW_URL,
            "before: the exact finisher input artifact must be exposed")
    require(preview["final"] and preview["final"]["url"] == FINAL_URL and preview["final"]["component"] == "final_render",
            "after: the exact finished master must be exposed")
    require([s["url"] for s in preview["shorts"]] == [SHORT_URL], "produced short cut must be listed")
    groups = {g["group"]: g for g in preview["groups"]}
    require(list(groups) == ["cuts", "captions", "audio", "graphics", "qa"], f"evidence groups: {list(groups)}")
    seen = set()
    for group in groups.values():
        require(group["available"] == sum(1 for x in group["items"] if x["available"]), "group count must match items")
        for item in group["items"]:
            seen.add(item["component"])
            if item["component"] in PRODUCED:
                require(item["available"] is True and item["artifact_id"], f"{item['component']} was produced but not linked")
            else:
                require(item["available"] is False and item["artifact_id"] is None,
                        f"{item['component']} was not produced but is not marked absent")
    require(seen == set(factory.MEDIA_FINISHER_EVIDENCE), "every finisher evidence component must be accounted for")
    require(groups["graphics"]["available"] == 0 and groups["audio"]["available"] == 1, "graphics absent / audio present")
    require(preview["qa_gate_artifact_id"], "QA gate report must be linked")
    gate = preview["approval_gate"]
    require(gate["ready"] is True and gate["human_approval_required"] is True and gate["auto_publish"] is False,
            "ready run must open the human gate without auto-publish")

    links = [preview["source"]["id"], preview["final"]["id"], preview["qa_gate_artifact_id"]]
    links += [s["id"] for s in preview["shorts"]]
    links += [i["artifact_id"] for g in preview["groups"] for i in g["items"] if i["available"]]
    for aid in links:
        status, _, _ = call(f"/api/artifacts/{aid}/media")
        require(status in (200, 307), f"artifact link {aid} returned {status}")

    item = next(x for x in get_json(f"/api/approval?job_id={job_id}")["items"] if x["job"]["id"] == job_id)
    require(item["finisher_preview"] == preview, "Approval Studio item must carry the same operator preview")
    require(item["review_ready"] is True and item["job"]["status"] == "waiting_approval", "job must wait for the human")

    with patch.object(factory, "FACTORY_PASSWORD", "t541-owner-pass"):
        status, _, _ = call(f"/api/jobs/{job_id}/media-finisher/preview")
        require(status == 401, f"preview must stay behind session auth, got {status}")
    print(f"OK preview exposes before/after, short cut, {len(links)} resolving links and marks "
          f"{len(factory.MEDIA_FINISHER_EVIDENCE) - len(PRODUCED)} absent artifacts")
    return preview


def check_gate(job_id, edit_id):
    con = factory.db()
    con.execute("UPDATE edit_jobs SET status='processing' WHERE id=?", (edit_id,))
    con.commit(); con.close()
    blocked = get_json(f"/api/jobs/{job_id}/media-finisher/preview")["approval_gate"]
    require(blocked["ready"] is False and blocked["reason"], "preview must mirror a blocked gate")
    refused = asyncio.run(factory.approve(job_id))
    require(refused["ok"] is False and factory.get_job(job_id)["status"] == "waiting_approval",
            "approve() must still refuse while the finisher run is not ready")
    con = factory.db()
    con.execute("UPDATE edit_jobs SET status='ready' WHERE id=?", (edit_id,))
    con.commit(); con.close()
    con = factory.db()
    require(con.execute("SELECT COUNT(*) c FROM publishing_queue").fetchone()["c"] == 0, "nothing queued before approval")
    con.close()
    approved = asyncio.run(factory.approve(job_id))
    require(approved["ok"] is True and approved["publish"]["target"] == "manual"
            and not approved["publish"].get("external_post_id") and approved["publish"]["media"]["url"] == FINAL_URL,
            "approval must only queue the exact reviewed media as a manual item")
    print("OK approval gate unchanged: blocked run refused, approval queues a manual item only")


def ui_script():
    return HTML.read_text(encoding="utf-8").split("<script>", 1)[1].split("</script>", 1)[0]


def check_ui(script, preview):
    def line(name):
        m = re.search(r"^(?:const|function) " + name + r"\b.*$", script, re.M)
        if m.group(0).endswith(("}", ";", "))")):
            return m.group(0)
        return script[m.start():script.index("\n}", m.end()) + 2]
    renderer = line("finisherPreviewHtml")
    require("approvalApprove" not in renderer and "/approve" not in renderer, "preview must not carry an approve action")
    studio = script[script.index("function renderApprovalStudio"):script.index("async function approvalApprove")]
    require("+finisherPreviewHtml(x.finisher_preview)" in studio, "Approval Studio must render the operator preview")
    require("(j.status==='waiting_approval'&&ready)" in studio, "approve button must stay behind review_ready")
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the rendered preview check")
        print("SKIPPED rendered preview check: node is not installed")
        return
    harness = "\n".join([line("textValue"), line("esc"), line("artifactMediaPath"), renderer]) + """
const tr=(k,v)=>k+(v&&v.reason?':'+v.reason:'');
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify({ready:finisherPreviewHtml(input.ready),none:finisherPreviewHtml(input.none),empty:finisherPreviewHtml(null)}));
"""
    none = {"available": False, "edit_job": None, "source": None, "final": None, "shorts": [], "groups": [],
            "approval_gate": {"ready": False, "reason": "no media", "human_approval_required": True}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "finisher-preview.js"
        path.write_text(harness, encoding="utf-8")
        result = subprocess.run([node, str(path)], input=json.dumps({"ready": preview, "none": none}),
                                capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, f"preview renderer failed in node: {result.stderr[:400]}")
    out = json.loads(result.stdout)
    html = out["ready"]
    links = set(re.findall(r'(?:href|src)="([^"]+)"', html))
    expected = {f"/api/artifacts/{preview['source']['id']}/media", f"/api/artifacts/{preview['final']['id']}/media"}
    require(expected <= links, "before/after media must use the stable artifact route")
    require(all(l.startswith("/api/artifacts/") for l in links), f"preview links bypass the stable route: {links}")
    for link in links:
        status, _, _ = call(link)
        require(status in (200, 307), f"rendered link {link} returned {status}")
    require(html.count('data-fp-missing="1"') == len(factory.MEDIA_FINISHER_EVIDENCE) - len(PRODUCED),
            "every absent artifact must be visibly marked")
    require(html.count("<video") == 2 and 'data-fp-gate="ready"' in html and "fp.gateNote" in html,
            "ready preview must show both videos, the open gate and the no-auto-publish note")
    for group in ("cuts", "captions", "audio", "graphics", "qa"):
        require(f'data-fp-group="{group}"' in html, f"{group} group must render")
    blank = out["none"]
    require("fp.noEdit" in blank and "fp.sourceMissing" in blank and "fp.finalMissing" in blank
            and 'data-fp-gate="blocked"' in blank and "fp.gateBlocked:no media" in blank and "<video" not in blank,
            "no-run preview must mark absent media and show the blocked gate reason")
    require(out["empty"] == "", "missing preview payload must render nothing")
    print(f"OK dashboard renderer emits {len(links)} resolving links and marks absent artifacts")


def main():
    factory.init_db()
    with patch.object(factory.urlrequest, "urlopen", no_network), \
            patch.object(factory, "_external_json", no_network), \
            patch.object(factory, "_content_brain_llm", no_network):
        job_id, raw_id = build_fixture()
        check_no_finisher_run(job_id)
        edit_id = run_finisher(job_id)
        preview = check_preview(job_id, raw_id, edit_id)
        check_ui(ui_script(), preview)
        check_gate(job_id, edit_id)
    require(outbound == [], f"outbound provider calls attempted: {outbound}")
    print("T-541 Media Finisher operator preview regression: PASS")


if __name__ == "__main__":
    main()
