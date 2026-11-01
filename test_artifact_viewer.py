"""T-535 artifact + media viewer hardening regression.

Representative text, JSON, subtitle (SRT/VTT) and finished-video artifacts are opened through the real FastAPI
stack (auth middleware + routes, driven as ASGI without a network or browser). Checks:
  * /api/artifacts/{id}/media serves stored text/JSON/subtitle content with a safe, correct content type, and the
    durable video archive with byte-exact inline/attachment responses;
  * stored active types (text/html) are never served as active content; redirects only to http(s)/same-origin;
  * the session-auth boundary on /api/artifacts and the HMAC boundary on /media-archive are unchanged;
  * the dashboard's Worker Results, Trace Viewer, Approval and Publishing links point at the stable route, and every
    link the real artifact renderer emits for the known artifacts resolves (no 404/410/422).
"""
import asyncio
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-artifact-viewer-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory

HTML = Path(__file__).resolve().parent / "static" / "index.html"
JOB_ID = "t535-job-" + uuid.uuid4().hex[:8]
VIDEO_BYTES = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 8


def require(condition, message):
    if not condition:
        raise AssertionError(message)


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


def media(artifact_id, download=False):
    return call(f"/api/artifacts/{artifact_id}/media", "download=1" if download else "")


def seed():
    ids = {}
    ids["text"] = factory.save_artifact("Hook Writer", "text", "Hook candidates", "1. Look inside the black box.\n2. Ünïcode ✓",
                                        job_id=JOB_ID)
    package = {"hook": "h", "scenes": [{"n": 1, "voice": "v"}]}
    ids["json"] = factory.save_artifact("Content Packager", "json", "Content Package", package, job_id=JOB_ID,
                                        mime_type="application/json", meta={"component": "package"})
    ids["srt"] = factory.save_artifact("Content Packager", "text", "Subtitles / SRT",
                                       "1\n00:00:00,000 --> 00:00:01,500\nLook inside\n", job_id=JOB_ID,
                                       mime_type="application/x-subrip", meta={"component": "srt"})
    ids["vtt"] = factory.save_artifact("AI Media Finisher", "text", "Captions VTT",
                                       "WEBVTT\n\n00:00.000 --> 00:01.500\nLook inside\n", job_id=JOB_ID)
    ids["caption_json"] = factory.save_artifact("AI Media Finisher", "json", "Caption timeline",
                                                {"items": [{"start": 0, "end": 1.5, "text": "Look"}]}, job_id=JOB_ID,
                                                mime_type="application/json", meta={"component": "caption_timeline"})
    ids["html"] = factory.save_artifact("Editor", "text", "Injected <b>", "<script>alert(1)</script>", job_id=JOB_ID,
                                        mime_type="text/html")
    ids["bad_json"] = factory.save_artifact("Analyst", "json", "Broken JSON", "{not json", job_id=JOB_ID)
    # Finished video in the durable archive, exactly as _archive_media_artifact leaves it.
    archive_id = str(uuid.uuid4())
    factory.MEDIA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (factory.MEDIA_ARCHIVE_DIR / f"{archive_id}.mp4").write_bytes(VIDEO_BYTES)
    (factory.MEDIA_ARCHIVE_DIR / f"{archive_id}.json").write_text(json.dumps({
        "archive_id": archive_id, "stored_name": f"{archive_id}.mp4", "filename": "final.mp4",
        "content_type": "video/mp4", "bytes": len(VIDEO_BYTES)}), encoding="utf-8")
    token = factory._media_archive_signature(archive_id)
    ids["video"] = factory.save_artifact("AI Media Finisher", "video", "Finished video", job_id=JOB_ID,
                                         url=f"{factory.FACTORY_PUBLIC_BASE_URL}/media-archive/{archive_id}?token={token}",
                                         mime_type="video/mp4",
                                         meta={"component": "final_render", "durable_media": True, "archive_id": archive_id,
                                               "human_approval_required": True})
    ids["remote_video"] = factory.save_artifact("Render Agent", "video", "Remote render", job_id=JOB_ID,
                                                url="https://cdn.example.invalid/render.mp4", mime_type="video/mp4")
    ids["js_url"] = factory.save_artifact("Render Agent", "video", "Bad scheme", job_id=JOB_ID,
                                          url="javascript:alert(1)", mime_type="video/mp4")
    ids["scheme_relative"] = factory.save_artifact("Render Agent", "video", "Scheme relative", job_id=JOB_ID,
                                                   url="//evil.example/x.mp4", mime_type="video/mp4")
    ids["video_no_url"] = factory.save_artifact("Render Agent", "video", "Render plan", "demo render plan", job_id=JOB_ID)
    return ids, archive_id, token


def check_text_routes(ids):
    expect = {  # artifact -> (inline type, download type, extension, body check)
        "text": ("text/plain", "text/plain", ".txt", lambda b: "Ünïcode ✓" in b),
        "json": ("application/json", "application/json", ".json", lambda b: json.loads(b)["scenes"][0]["voice"] == "v"),
        "srt": ("text/plain", "application/x-subrip", ".srt", lambda b: "00:00:00,000 --> 00:00:01,500" in b),
        "vtt": ("text/plain", "text/vtt", ".vtt", lambda b: b.startswith("WEBVTT")),
        "caption_json": ("application/json", "application/json", ".json", lambda b: json.loads(b)["items"][0]["text"] == "Look"),
        "html": ("text/plain", "text/plain", ".txt", lambda b: b == "<script>alert(1)</script>"),
        "bad_json": ("text/plain", "text/plain", ".txt", lambda b: b == "{not json"),
    }
    for name, (inline_type, download_type, ext, body_ok) in expect.items():
        status, headers, body = media(ids[name])
        require(status == 200, f"{name}: inline open must be 200, got {status} {body[:120]!r}")
        require(headers["content-type"] == f"{inline_type}; charset=utf-8", f"{name}: inline type {headers['content-type']}")
        require(headers["content-disposition"].startswith("inline;") and ext + '"' in headers["content-disposition"],
                f"{name}: inline disposition {headers['content-disposition']}")
        require(headers.get("x-content-type-options") == "nosniff", f"{name}: nosniff header missing")
        require("sandbox" in headers.get("content-security-policy", ""), f"{name}: stored content must be sandboxed")
        require(headers.get("cache-control") == "private, no-store", f"{name}: authenticated content must not be cached")
        require(body_ok(body.decode("utf-8")), f"{name}: body does not round-trip: {body[:120]!r}")
        status, headers, _ = media(ids[name], download=True)
        require(status == 200 and headers["content-type"] == f"{download_type}; charset=utf-8",
                f"{name}: download type {status} {headers.get('content-type')}")
        require(headers["content-disposition"].startswith("attachment;"), f"{name}: download must be an attachment")
    print("OK text/JSON/SRT/VTT artifacts open inline and download with correct, non-active content types")


def check_video_routes(ids, archive_id, token):
    status, headers, body = media(ids["video"])
    require(status == 200 and body == VIDEO_BYTES, f"finished video must stream byte-exact from the archive, got {status}")
    require(headers["content-type"] == "video/mp4" and headers["content-disposition"].startswith("inline"),
            f"finished video inline headers: {headers}")
    require(headers.get("x-content-type-options") == "nosniff", "archived media must be served with nosniff")
    status, headers, body = media(ids["video"], download=True)
    require(status == 200 and headers["content-disposition"].startswith("attachment") and body == VIDEO_BYTES,
            "finished video download must be a byte-exact attachment")
    status, headers, _ = media(ids["remote_video"])
    require(status == 307 and headers["location"] == "https://cdn.example.invalid/render.mp4",
            f"remote http(s) media must redirect, got {status}")
    for name in ("js_url", "scheme_relative"):
        status, headers, _ = media(ids[name])
        require(status == 422 and "location" not in headers, f"{name}: non-http(s) media URL must not redirect, got {status}")
    status, _, _ = media(ids["video_no_url"])
    require(status == 404, "a video artifact without media must 404, never serve its text as video")
    status, _, _ = media(str(uuid.uuid4()))
    require(status == 404, "unknown artifact must 404")
    status, _, body = call(f"/media-archive/{archive_id}", f"token={token}")
    require(status == 200 and body == VIDEO_BYTES, "signed durable media link must play")
    print("OK finished video streams inline/attachment from the durable archive; redirects limited to http(s)")


def check_auth_boundaries(ids, archive_id, token):
    with patch.object(factory, "FACTORY_PASSWORD", "t535-owner-pass"):
        for name in ("text", "json", "srt", "video"):
            status, _, _ = media(ids[name])
            require(status == 401, f"{name}: /api/artifacts must stay behind session auth, got {status}")
        for role, cookie in (("owner", factory.session_token(factory.FACTORY_USER)),
                             ("viewer", factory._role_session_token("viewer", "guest"))):
            status, _, _ = call(f"/api/artifacts/{ids['srt']}/media", cookie=f"{factory.COOKIE_NAME}={cookie}")
            require(status == 200, f"{role} session must open artifacts read-only, got {status}")
        status, _, _ = call(f"/api/artifacts/{ids['srt']}/media", cookie=f"{factory.COOKIE_NAME}=v2|owner||forged")
        require(status == 401, f"forged session must not open artifacts, got {status}")
        status, _, body = call(f"/media-archive/{archive_id}", f"token={token}")
        require(status == 200 and body == VIDEO_BYTES, "signed media link must keep working without a session")
        for bad in ("", "token=" + "0" * 64, "token=" + token[:-1]):
            status, _, _ = call(f"/media-archive/{archive_id}", bad)
            require(status == 403, f"media archive must reject bad token {bad[:12]!r}, got {status}")
    print("OK session auth on /api/artifacts and HMAC token on /media-archive are unchanged")


def ui_script():
    script = HTML.read_text(encoding="utf-8").split("<script>", 1)[1].split("</script>", 1)[0]
    def line(name):  # one-line definition, or a multi-line function closed by a column-0 "}"
        m = re.search(r"^(?:const|function) " + name + r"\b.*$", script, re.M)
        if m.group(0).endswith(("}", ";", "))")):
            return m.group(0)
        return script[m.start():script.index("\n}", m.end()) + 2]
    block = script[script.index("// T-535: binary media"):script.index("async function deleteVideoArtifact")]
    return script, "\n".join([line("textValue"), line("esc"), line("safeDate"), line("artifactMediaPath"), block])


def check_ui_wiring(script):
    trace = script[script.index("async function openHandoffTrace"):script.index("async function openBrowserRunTrace")]
    require("artifactMediaActions({id:d.artifact_id" in trace, "Trace Viewer must offer open/download for the passed artifact")
    detail = script[script.index("function renderAgentDetail"):script.index("function artifactMediaPath")]
    require("artifactMediaActions(selected)" in detail and "arts.map(a=>artifactHtml(a))" in detail,
            "Worker Results drawer must render artifacts through the shared viewer actions")
    require(script.count("esc(artifactMediaPath(x.preview,false))") == 2, "Approval preview must use the stable artifact route")
    require("artifactMediaPath({id:m.artifact_id,url:m.url},false)" in script,
            "Publishing approved-media preview must use the stable artifact route")
    require(not re.search(r"src=\"'\+esc\((x\.preview|m)\.url\)", script), "no raw provider URL may be used as a <video> src")
    print("OK Worker Results, Trace Viewer, Approval and Publishing link through /api/artifacts/{id}/media")


def check_rendered_links(snippet, ids):
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the rendered-link check")
        print("SKIPPED rendered-link check: node is not installed")
        return
    con = factory.db()
    rows = [dict(r) for r in con.execute("SELECT id,kind,title,content,url,meta_json FROM artifacts WHERE job_id=?", (JOB_ID,))]
    con.close()
    artifacts = [{**r, "meta": json.loads(r.pop("meta_json") or "{}")} for r in rows]
    worker = factory.get_job_worker_results(JOB_ID)
    selected = [{k: v[k] for k in ("id", "kind", "title", "content", "url")} for v in worker.values()]
    harness = snippet + """
const tr=k=>k,workerPurpose=n=>n,S={selectedJobId:''};
const input=JSON.parse(require('fs').readFileSync(0,'utf8'));
const out={};
for(const a of input.artifacts)out[a.id]=artifactHtml(a);
for(const a of input.selected)out['sel:'+a.id]=artifactMediaActions(a);
process.stdout.write(JSON.stringify(out));
"""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "artifact-viewer.js"
        path.write_text(harness, encoding="utf-8")
        result = subprocess.run([node, str(path)], input=json.dumps({"artifacts": artifacts, "selected": selected}),
                                capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, f"artifact renderer failed in node: {result.stderr[:400]}")
    rendered = json.loads(result.stdout)
    by_id = {v: k for k, v in ids.items()}
    broken_by_design = {ids["js_url"], ids["scheme_relative"]}
    checked = 0
    for key, html in rendered.items():
        aid = key.split(":", 1)[-1]
        links = set(re.findall(r'(?:href|src)="([^"]+)"', html))
        name = by_id.get(aid, aid)
        if name == "video_no_url":
            require(not links, "a video without media must render a placeholder, not a link")
            continue
        require(links, f"{name}: known artifact renders no open/download link")
        for link in links:
            require(link.startswith(f"/api/artifacts/{aid}/media"), f"{name}: link bypasses the stable route: {link}")
            path, _, query = link.replace("&amp;", "&").partition("?")
            status, _, _ = call(path, query)
            ok = status == 422 if aid in broken_by_design else status in (200, 307)
            require(ok, f"{name}: rendered link {link} returned {status}")
            checked += 1
    require(checked >= 20, f"too few rendered links verified: {checked}")
    print(f"OK {checked} links rendered by the real artifact viewer resolve (Worker Results drawer + selected result)")


def main():
    factory.init_db()
    ids, archive_id, token = seed()
    check_text_routes(ids)
    check_video_routes(ids, archive_id, token)
    check_auth_boundaries(ids, archive_id, token)
    script, snippet = ui_script()
    check_ui_wiring(script)
    check_rendered_links(snippet, ids)
    print("T-535 artifact viewer regression: PASS")


if __name__ == "__main__":
    main()
