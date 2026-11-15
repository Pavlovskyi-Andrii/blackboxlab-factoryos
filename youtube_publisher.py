"""Direct YouTube publisher (T-552-YT): Google OAuth transport + resumable Shorts upload.

Owner decision 2026-11-15: publish to YouTube through the official, free YouTube Data API v3 instead of a
paid scheduler. This module is the provider half; app.py keeps the approval gate, the immutable snapshot,
the idempotency/uncertain-outcome fence and the receipt.

Rules this module keeps:
- The client secret is read from the environment only at call time and never returned or logged.
- Tokens never leave the module except into the encrypted TokenVault; errors carry fixed codes, never
  provider bodies (they can echo tokens) and never token values.
- Network goes through one injectable `http` callable so tests run with zero network and zero spend.
- Upload privacy defaults to `private`; `selfDeclaredMadeForKids` must be declared explicitly (fail closed).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import urlencode

from oauth_framework import OAuthAdapter, OAuthError, OAuthProvider, TokenSet

CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status"
PRIVACY_VALUES = ("private", "unlisted", "public")
TITLE_MAX = 100
DESCRIPTION_MAX_BYTES = 4900  # API limit is 5000 bytes; keep headroom for multi-byte characters
TAGS_MAX_CHARS = 450  # API limit is 500 characters for all tags together

# http(method, url, headers, body, timeout) -> (status, headers, body_bytes). `body` is bytes, a binary
# file object (streamed upload) or None. Raises urllib errors only for transport failures.
Http = Callable[[str, str, dict, object, float], tuple]


class YouTubeError(RuntimeError):
    """Fixed, token-free message. `uncertain` marks failures after the video bytes may have been accepted."""

    def __init__(self, code: str, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


def urllib_http(method, url, headers, body, timeout):
    req = urlrequest.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urlerror.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b""


def _json(body: bytes) -> dict:
    try:
        data = json.loads((body or b"{}").decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _api_reason(body: bytes) -> str:
    """First machine reason from a Google error body (e.g. quotaExceeded), never the message text."""
    err = _json(body).get("error")
    if isinstance(err, dict):
        for item in err.get("errors") or []:
            if isinstance(item, dict) and item.get("reason"):
                return str(item["reason"])[:60]
        return str(err.get("status") or "")[:60]
    return str(err or "")[:60]


def client_credentials(spec: OAuthProvider) -> tuple:
    return os.environ.get(spec.client_id_env, "").strip(), os.environ.get(spec.client_secret_env, "").strip()


class GoogleOAuthAdapter(OAuthAdapter):
    """Real Google transport for the `youtube` OAuth provider."""

    def __init__(self, http: Http = urllib_http, timeout: float = 25.0):
        self.http = http
        self.timeout = timeout

    def ready(self, spec: OAuthProvider) -> bool:
        return all(client_credentials(spec))

    def _token_request(self, spec, form: dict) -> dict:
        client_id, client_secret = client_credentials(spec)
        if not (client_id and client_secret):
            raise OAuthError("client_secret_missing")
        body = urlencode({**form, "client_id": client_id, "client_secret": client_secret}).encode()
        status, _, raw = self.http("POST", spec.token_url,
                                   {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                   body, self.timeout)
        data = _json(raw)
        if status != 200 or not data.get("access_token"):
            raise OAuthError("exchange_failed" if form.get("grant_type") == "authorization_code" else "refresh_failed")
        return data

    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        form = {"code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"}
        if code_verifier:
            form["code_verifier"] = code_verifier
        data = self._token_request(spec, form)
        scopes = tuple(str(data.get("scope") or "").split()) or spec.scopes
        tokens = TokenSet(access_token=data["access_token"], refresh_token=str(data.get("refresh_token") or ""),
                          expires_in=int(data.get("expires_in") or 0), scopes=scopes)
        tokens.account_id, tokens.account_label = self.channel(tokens)
        return tokens

    def refresh(self, spec, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise OAuthError("refresh_token_missing")
        data = self._token_request(spec, {"refresh_token": tokens.refresh_token, "grant_type": "refresh_token"})
        return TokenSet(access_token=data["access_token"], refresh_token=tokens.refresh_token,
                        expires_in=int(data.get("expires_in") or 0),
                        scopes=tuple(str(data.get("scope") or "").split()) or tokens.scopes,
                        account_id=tokens.account_id, account_label=tokens.account_label)

    def channel(self, tokens: TokenSet) -> tuple:
        status, _, raw = self.http("GET", CHANNELS_URL, {"Authorization": "Bearer " + tokens.access_token,
                                                        "Accept": "application/json"}, None, self.timeout)
        items = _json(raw).get("items") or [] if status == 200 else []
        if not items:
            # A Google account without a YouTube channel cannot upload; refuse instead of storing a useless token.
            raise OAuthError("youtube_channel_missing")
        first = items[0] if isinstance(items[0], dict) else {}
        return str(first.get("id") or "")[:180], str((first.get("snippet") or {}).get("title") or "")[:180]

    def revoke(self, spec, tokens):
        token = tokens.refresh_token or tokens.access_token
        status, _, _ = self.http("POST", spec.revoke_url, {"Content-Type": "application/x-www-form-urlencoded"},
                                 urlencode({"token": token}).encode(), self.timeout)
        return status == 200


def upload_settings(env=None) -> dict:
    """Owner-controlled upload settings. Returns blockers instead of guessing a legal declaration."""
    env = os.environ if env is None else env
    blockers = []
    privacy = str(env.get("FACTORY_YOUTUBE_PRIVACY", "private")).strip().lower() or "private"
    if privacy not in PRIVACY_VALUES:
        blockers.append("youtube_privacy_invalid")
    kids_raw = str(env.get("FACTORY_YOUTUBE_MADE_FOR_KIDS", "")).strip().lower()
    made_for_kids = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}.get(kids_raw)
    if made_for_kids is None:
        blockers.append("youtube_audience_unset")
    return {"privacy": privacy, "made_for_kids": made_for_kids, "blockers": blockers}


def _clean_text(text: str) -> str:
    # YouTube rejects '<' and '>' in titles and descriptions.
    return str(text or "").replace("<", "").replace(">", "").strip()


def video_metadata(content: dict, settings: dict) -> dict:
    content = content or {}
    title = _clean_text(content.get("title")) or "FactoryOS video"
    if len(title) > TITLE_MAX:
        title = title[:TITLE_MAX - 1].rstrip() + "…"
    tags, used = [], 0
    for raw in content.get("hashtags") or []:
        tag = _clean_text(raw).lstrip("#").strip()
        if tag and used + len(tag) + 1 <= TAGS_MAX_CHARS:
            tags.append(tag)
            used += len(tag) + 1
    parts = [_clean_text(content.get("description")), _clean_text(content.get("cta")),
             " ".join("#" + t.replace(" ", "") for t in tags)]
    description = "\n\n".join(p for p in parts if p)
    encoded = description.encode("utf-8")
    if len(encoded) > DESCRIPTION_MAX_BYTES:
        description = encoded[:DESCRIPTION_MAX_BYTES].decode("utf-8", "ignore").rstrip() + "…"
    return {
        "snippet": {"title": title, "description": description, "tags": tags, "categoryId": "22"},
        # AI disclosure travels with every upload, like the Metricool path (isAiGeneratedContent).
        "status": {"privacyStatus": settings["privacy"], "selfDeclaredMadeForKids": bool(settings["made_for_kids"]),
                   "containsSyntheticMedia": True},
    }


def upload_video(http: Http, access_token: str, path: Path, mime_type: str, metadata: dict,
                 timeout: float = 600.0) -> dict:
    """Resumable upload in one PUT. Returns {video_id, url}. Raises YouTubeError (never with tokens)."""
    path = Path(path)
    if not path.is_file():
        raise YouTubeError("youtube_media_missing")
    size = path.stat().st_size
    if size <= 0:
        raise YouTubeError("youtube_media_empty")
    mime_type = mime_type if str(mime_type or "").startswith("video/") else "video/mp4"
    status, headers, raw = http("POST", UPLOAD_URL, {
        "Authorization": "Bearer " + access_token, "Content-Type": "application/json; charset=UTF-8",
        "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": mime_type,
    }, json.dumps(metadata, ensure_ascii=False).encode("utf-8"), 30.0)
    if status != 200 or not headers.get("location"):
        reason = _api_reason(raw)
        if status == 403 and reason in ("quotaExceeded", "uploadLimitExceeded", "rateLimitExceeded"):
            raise YouTubeError("youtube_" + reason)
        if status == 401:
            raise YouTubeError("youtube_auth_failed")
        raise YouTubeError(f"youtube_upload_rejected_{status}" + (f"_{reason}" if reason else ""))
    try:
        with path.open("rb") as handle:
            status, _, raw = http("PUT", headers["location"], {"Content-Type": mime_type,
                                                               "Content-Length": str(size)}, handle, timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        # The bytes may have landed: the caller must not retry blindly (duplicate video).
        raise YouTubeError("youtube_upload_outcome_uncertain", uncertain=True)
    data = _json(raw)
    if status not in (200, 201) or not data.get("id"):
        raise YouTubeError(f"youtube_upload_failed_{status}", uncertain=status >= 500)
    video_id = str(data["id"])
    return {"video_id": video_id, "url": f"https://www.youtube.com/shorts/{video_id}",
            "privacy": ((data.get("status") or {}).get("privacyStatus") or metadata["status"]["privacyStatus"]),
            "upload_status": (data.get("status") or {}).get("uploadStatus") or ""}
