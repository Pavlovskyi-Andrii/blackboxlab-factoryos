"""T-552-YT direct YouTube publisher regression. Run: python test_youtube_publisher.py

Zero network, zero secrets, $0.00. A fake Google endpoint stands in for oauth2.googleapis.com and the
YouTube Data API. Checks: code exchange + channel lookup, refusal without a channel, refresh, revoke,
resumable upload of the exact archived approved file with AI disclosure and explicit audience, private by
default, quota/auth errors as fixed codes, an interrupted upload surfacing as an uncertain outcome (no blind
retry), registry/owner-desk readiness from facts, and that no token or client secret reaches results or logs.
"""
import io
import json
import logging
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-youtube-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory
import oauth_framework as oauth
import youtube_publisher as yt

CLIENT_ID = "t552yt-client.apps.googleusercontent.com"
CLIENT_SECRET = "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ear"
ENV = {"FACTORY_OAUTH_GOOGLE_CLIENT_ID": CLIENT_ID, "FACTORY_OAUTH_GOOGLE_CLIENT_SECRET": CLIENT_SECRET,
       "FACTORY_YOUTUBE_MADE_FOR_KIDS": "false"}
SPEC = oauth.PROVIDERS["youtube"]
seen_text = []


class Capture(logging.Handler):
    def emit(self, record):
        seen_text.append(record.getMessage())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


class FakeGoogle:
    """Minimal stand-in for Google token/revoke endpoints and the YouTube Data API."""

    def __init__(self, channel=True, upload_init_status=200, upload_init_body=b"", put_mode="ok"):
        self.channel = channel
        self.upload_init_status = upload_init_status
        self.upload_init_body = upload_init_body
        self.put_mode = put_mode
        self.calls = []
        self.uploaded = b""
        self.metadata = None
        self.issued = 0

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url.split("?")[0]))
        if url == SPEC.token_url:
            form = {k: v[0] for k, v in parse_qs(body.decode()).items()}
            require(form["client_id"] == CLIENT_ID and form["client_secret"] == CLIENT_SECRET, "client credentials sent")
            self.issued += 1
            if form["grant_type"] == "authorization_code":
                require(form["redirect_uri"].endswith("/api/oauth/youtube/callback") and form.get("code_verifier"),
                        "redirect + PKCE verifier sent to Google")
                return 200, {}, json.dumps({"access_token": f"ya29.at-{self.issued}", "refresh_token": "1//rt-secret",
                                            "expires_in": 3599, "scope": " ".join(SPEC.scopes)}).encode()
            require(form["grant_type"] == "refresh_token" and form["refresh_token"] == "1//rt-secret", "refresh grant")
            return 200, {}, json.dumps({"access_token": f"ya29.at-{self.issued}", "expires_in": 3599}).encode()
        if url == SPEC.revoke_url:
            require(parse_qs(body.decode())["token"] == ["1//rt-secret"], "revoke uses the refresh token")
            return 200, {}, b""
        if url.startswith("https://www.googleapis.com/youtube/v3/channels"):
            items = [{"id": "UC-t552", "snippet": {"title": "Blackbox Lab"}}] if self.channel else []
            return 200, {}, json.dumps({"items": items}).encode()
        if url.startswith("https://www.googleapis.com/upload/youtube/v3/videos"):
            require(headers["Authorization"].startswith("Bearer ya29."), "upload uses a fresh access token")
            self.metadata = json.loads(body.decode())
            if self.upload_init_status != 200:
                return self.upload_init_status, {}, self.upload_init_body
            return 200, {"location": "https://upload.example/session-1"}, b""
        if url == "https://upload.example/session-1":
            require(method == "PUT" and int(headers["Content-Length"]) > 0, "single streamed PUT")
            if self.put_mode == "timeout":
                raise TimeoutError("socket timeout")
            self.uploaded = body.read()
            if self.put_mode == "500":
                return 500, {}, b"{}"
            return 200, {}, json.dumps({"id": "vid-t552", "status": {"privacyStatus": self.metadata["status"]["privacyStatus"],
                                                                     "uploadStatus": "uploaded"}}).encode()
        raise AssertionError("unexpected outbound call " + url)


def check_adapter_unit():
    with patch.dict(os.environ, ENV):
        fake = FakeGoogle()
        adapter = yt.GoogleOAuthAdapter(http=fake)
        require(adapter.ready(SPEC), "ready with id + secret")
        tokens = adapter.exchange_code(SPEC, "code-1", "https://x/api/oauth/youtube/callback", "v" * 50)
        require(tokens.account_id == "UC-t552" and tokens.account_label == "Blackbox Lab" and tokens.refresh_token,
                "exchange stores channel identity")
        refreshed = adapter.refresh(SPEC, tokens)
        require(refreshed.access_token != tokens.access_token and refreshed.refresh_token == tokens.refresh_token
                and refreshed.account_id == "UC-t552", "refresh keeps the refresh token and channel")
        require(adapter.revoke(SPEC, tokens) is True, "revoke")
        try:
            yt.GoogleOAuthAdapter(http=FakeGoogle(channel=False)).exchange_code(SPEC, "c", "https://x/api/oauth/youtube/callback", "v" * 50)
            raise AssertionError("account without channel must be refused")
        except oauth.OAuthError as e:
            require(e.code == "youtube_channel_missing", "no-channel code")
    with patch.dict(os.environ, {"FACTORY_OAUTH_GOOGLE_CLIENT_ID": CLIENT_ID, "FACTORY_OAUTH_GOOGLE_CLIENT_SECRET": ""}):
        require(not yt.GoogleOAuthAdapter(http=FakeGoogle()).ready(SPEC), "secret missing -> not ready")
        flow = oauth.OAuthFlow("https://x", lambda s: os.environ.get(s.client_id_env, ""), oauth.MemoryTokenVault(),
                               adapters={"youtube": yt.GoogleOAuthAdapter(http=FakeGoogle())})
        require(flow.blockers(SPEC) == ["client_secret_missing"], "registry names the missing secret")
    print("OK Google adapter: exchange + channel, no-channel refusal, refresh, revoke, missing secret")


def check_settings_and_metadata():
    require(yt.upload_settings({})["blockers"] == ["youtube_audience_unset"], "audience must be explicit")
    s = yt.upload_settings({"FACTORY_YOUTUBE_MADE_FOR_KIDS": "false"})
    require(s == {"privacy": "private", "made_for_kids": False, "blockers": []}, "private by default")
    require("youtube_privacy_invalid" in yt.upload_settings({"FACTORY_YOUTUBE_PRIVACY": "everyone",
                                                             "FACTORY_YOUTUBE_MADE_FOR_KIDS": "no"})["blockers"], "privacy")
    meta = yt.video_metadata({"title": "<b>" + "x" * 150, "description": "Heat <kills> batteries", "cta": "Follow",
                              "hashtags": ["#Shorts", "battery tips", ""]}, s)
    sn = meta["snippet"]
    require(len(sn["title"]) <= yt.TITLE_MAX and "<" not in sn["title"] and ">" not in sn["description"], "sanitized")
    require(sn["tags"] == ["Shorts", "battery tips"] and "#batterytips" in sn["description"], "tags + hashtags")
    require(meta["status"] == {"privacyStatus": "private", "selfDeclaredMadeForKids": False,
                               "containsSyntheticMedia": True}, "AI disclosure + audience + privacy")
    print("OK upload settings fail closed; metadata sanitized with AI disclosure")


def archived_media(job_id, payload=b"\x00\x00\x00\x18ftypmp42-t552-video-bytes"):
    import hashlib
    archive_id = str(uuid.uuid4())
    digest = hashlib.sha256(payload).hexdigest()
    factory.MEDIA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    (factory.MEDIA_ARCHIVE_DIR / f"{archive_id}.mp4").write_bytes(payload)
    (factory.MEDIA_ARCHIVE_DIR / f"{archive_id}.json").write_text(json.dumps(
        {"archive_id": archive_id, "stored_name": f"{archive_id}.mp4", "content_type": "video/mp4",
         "sha256": digest}), encoding="utf-8")
    url = f"{factory.FACTORY_PUBLIC_BASE_URL}/media-archive/{archive_id}?token=t"
    artifact_id = factory.save_artifact("Media Finisher", "video", "final", job_id=job_id, url=url,
                                        mime_type="video/mp4", meta={"archive_id": archive_id, "durable_media": True,
                                                                     "archive_sha256": digest})
    return {"artifact_id": artifact_id, "url": url, "mime_type": "video/mp4", "sha256": digest}, payload


def check_publish_path():
    import asyncio
    job_id = asyncio.run(factory.create_job(factory.JobCreate(title="T-552-YT", brief="fixture", presenter="Faceless",
                                                              format="Short only", language="English", outputs=1)))["id"]
    media, payload = archived_media(job_id)
    content = {"title": "Why batteries die", "description": "Heat matters.", "cta": "", "hashtags": ["#Shorts"]}
    item = {"id": "pub-1", "job_id": job_id, "platform": "youtube_shorts", "content_snapshot": content,
            "media": media, "workspace_key": factory.tenancy.DEFAULT_WORKSPACE}
    vault = oauth.MemoryTokenVault()
    fake = FakeGoogle()
    adapter = yt.GoogleOAuthAdapter(http=fake)
    with patch.dict(os.environ, ENV), patch.object(factory.OAUTH_FLOW, "vault", vault), \
            patch.object(factory.OAUTH_FLOW, "adapters", {"youtube": adapter}), \
            patch.object(factory, "FACTORY_PUBLISHER_ADAPTER", "youtube"):
        state = factory._youtube_publisher_state()
        require(state["blockers"] == ["youtube_not_connected"], f"not connected yet: {state}")
        status = factory._owner_desk_status()["T-520"]
        require(status["state"] == "todo" and status["detail_key"] == "youtube_blocked", "owner desk shows blocker")
        try:
            factory._publish_via_adapter(item)
            raise AssertionError("publishing without a connected channel must fail")
        except RuntimeError as e:
            require("youtube_not_connected" in str(e), "fixed blocker message")
        vault.put(factory.tenancy.DEFAULT_WORKSPACE, "youtube",
                  adapter.exchange_code(SPEC, "code", "https://x/api/oauth/youtube/callback", "v" * 50))
        reg = factory.get_publisher_adapter_registry()
        ytreg = next(a for a in reg["adapters"] if a["kind"] == "youtube")
        require(ytreg["configured"] and ytreg["channel_title"] == "Blackbox Lab" and ytreg["privacy"] == "private",
                "registry ready from facts")
        require(factory._owner_desk_status()["T-520"]["state"] == "done", "owner desk T-520 done")
        result = factory._publish_via_adapter(item)
        require(result["status"] == "published" and result["external_post_id"] == "vid-t552"
                and result["external_url"] == "https://www.youtube.com/shorts/vid-t552", "real video receipt")
        require(fake.uploaded == payload, "the exact archived approved file is uploaded")
        require(fake.metadata["snippet"]["title"] == "Why batteries die"
                and fake.metadata["status"]["containsSyntheticMedia"] is True, "approved snapshot metadata")
        dumped = json.dumps(result)
        for secret in ("ya29.", "1//rt-secret", CLIENT_SECRET):
            require(secret not in dumped, "no token or secret in the publish result")
        require(vault.get(factory.tenancy.DEFAULT_WORKSPACE, "youtube").access_token != "ya29.at-1",
                "refreshed token persisted")

        # Wrong platform, swapped media, quota, interrupted upload.
        for bad, needle in (({**item, "platform": "tiktok"}, "only handles youtube_shorts"),
                            ({**item, "media": {**media, "url": media["url"] + "x"}}, "does not match")):
            try:
                factory._publish_via_adapter(bad)
                raise AssertionError("must refuse: " + needle)
            except RuntimeError as e:
                require(needle in str(e), needle)
        quota = yt.GoogleOAuthAdapter(http=FakeGoogle(upload_init_status=403, upload_init_body=json.dumps(
            {"error": {"errors": [{"reason": "quotaExceeded", "message": "token ya29.leak"}]}}).encode()))
        with patch.object(factory.OAUTH_FLOW, "adapters", {"youtube": quota}):
            try:
                factory._publish_via_adapter(item)
                raise AssertionError("quota must fail")
            except RuntimeError as e:
                require(str(e) == "youtube_quotaExceeded", f"fixed quota code, no provider text: {e}")
        # Replaced bytes under the same artifact/URL, or no recorded digest, are refused before any upload.
        path = factory.MEDIA_ARCHIVE_DIR / (media["url"].split("/media-archive/")[1].split("?")[0] + ".mp4")
        original = path.read_bytes()
        path.write_bytes(original + b"tampered")
        calls_before = len(fake.calls)
        try:
            factory._publish_via_adapter(item)
            raise AssertionError("replaced archive file must be refused")
        except RuntimeError as e:
            require("do not match the approved media digest" in str(e), f"digest refusal: {e}")
        require(not any(u.startswith("https://www.googleapis.com/upload") for _, u in fake.calls[calls_before:]),
                "no upload attempted for tampered media")
        path.write_bytes(original)
        undigested, _ = archived_media(job_id)
        con = factory.db()
        con.execute("UPDATE artifacts SET meta_json=? WHERE id=?",
                    (json.dumps({"archive_id": undigested["url"].split("/media-archive/")[1].split("?")[0]}),
                     undigested["artifact_id"]))
        con.commit()
        con.close()
        try:
            factory._publish_via_adapter({**item, "media": {**undigested, "sha256": ""}})
            raise AssertionError("media without a recorded digest must be refused")
        except RuntimeError as e:
            require("no recorded digest" in str(e), f"no-digest refusal: {e}")

        # Workspace isolation: another workspace neither sees the default channel nor publishes through it.
        with factory.tenancy.workspace_scope("customer-b"):
            other = factory._youtube_publisher_state()
            require(other["channel_title"] == "" and "youtube_not_connected" in other["blockers"],
                    f"other workspace must not see the default channel: {other}")
            ytreg = next(a for a in factory.get_publisher_adapter_registry()["adapters"] if a["kind"] == "youtube")
            require(ytreg["channel_title"] == "" and not ytreg["configured"], "registry scoped to the caller")
        try:
            factory._publish_via_adapter({**item, "workspace_key": "customer-b"})
            raise AssertionError("another workspace must not publish through the default channel")
        except RuntimeError as e:
            require("customer-b" in str(e), f"workspace refusal: {e}")

        for mode in ("timeout", "500"):
            flaky = yt.GoogleOAuthAdapter(http=FakeGoogle(put_mode=mode))
            with patch.object(factory.OAUTH_FLOW, "adapters", {"youtube": flaky}):
                try:
                    factory._publish_via_adapter(item)
                    raise AssertionError("interrupted upload must fail")
                except TimeoutError as e:
                    # publish_scheduled_item marks TimeoutError as outcome_uncertain -> no blind retry.
                    require(str(e).startswith("youtube_upload"), "uncertain outcome code")
    for line in seen_text:
        for secret in ("ya29.", "1//rt-secret", CLIENT_SECRET):
            require(secret not in line, "no token or secret in logs")
    print("OK publish path: exact archived file, receipt, refresh persisted, refusals, quota, uncertain outcome")


def main():
    handler = Capture()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    with patch.object(factory.urlrequest, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network"))):
        check_adapter_unit()
        check_settings_and_metadata()
        check_publish_path()
    logging.getLogger().removeHandler(handler)
    print("T-552-YT direct YouTube publisher: PASS (zero secrets, zero network)")


if __name__ == "__main__":
    main()
