"""LinkedIn text posts through the official LinkedIn API (owner 2026-11-17, T-700).

Path: "Sign In with LinkedIn using OpenID Connect" + "Share on LinkedIn" (`w_member_social`) on the owner's own
LinkedIn developer app (T-700-H). FactoryOS never logs in through a browser and never automates linkedin.com pages.

Flow, all owner-only: draft → approve (freezes the exact text: its SHA-256 is the approval snapshot) → publish.
- Publishing is off until the owner sets FACTORY_LINKEDIN_ENABLED=1 (the code ships dark).
- Publish refuses a draft whose text changed after approval, one already published, and one whose earlier attempt
  ended with an unknown outcome (timeout / 5xx): that one needs the owner to check LinkedIn and confirm, so a post
  is never sent twice.
- Errors carry fixed codes; LinkedIn response bodies and tokens are never stored, logged or returned.
- Network goes through one injectable `http` callable, so the tests make zero network calls.

T-713: a post can carry one image through the Images API (initializeUpload → PUT the bytes to the returned upload URL
→ post with ``content.media.id``). Any failure before the post call is a plain failure (no post exists yet); the
access token is only ever sent to a LinkedIn host.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request

from oauth_framework import OAuthAdapter, OAuthError, OAuthProvider, TokenSet

USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
POSTS_URL = "https://api.linkedin.com/rest/posts"
IMAGES_INIT_URL = "https://api.linkedin.com/rest/images?action=initializeUpload"
IMAGE_URN_RE = re.compile(r"^urn:li:image:[A-Za-z0-9_-]{1,200}$")
UPLOAD_HOST_RE = re.compile(r"^https://([a-z0-9-]+\.)*(linkedin\.com|licdn\.com)(:443)?/")
IMAGE_MAX_BYTES = 8 * 1024 * 1024
DEFAULT_API_VERSION = "202510"           # LinkedIn-Version header (YYYYMM); owner can override, see DECISIONS T-700
TEXT_MAX = 3000                          # LinkedIn post commentary limit
MAX_DRAFTS = 200
ID_RE = re.compile(r"^li_[0-9a-f]{12}$")
VERSION_RE = re.compile(r"^20\d{4}$")
# LinkedIn "little text" format: these characters are syntax and must be backslash-escaped to appear literally.
_RESERVED = re.compile(r"([\\|{}@\[\]()<>#*_~])")

Http = Callable[[str, str, dict, object, float], tuple]


class LinkedInError(RuntimeError):
    """Fixed, token-free code. `uncertain` = the post may have been created (do not retry blindly)."""

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


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("FACTORY_LINKEDIN_ENABLED", "")).strip().lower() in ("1", "true", "yes")


def api_version(env=None) -> str:
    env = os.environ if env is None else env
    value = str(env.get("FACTORY_LINKEDIN_API_VERSION", "")).strip()
    return value if VERSION_RE.fullmatch(value) else DEFAULT_API_VERSION


def client_credentials(spec: OAuthProvider) -> tuple:
    return os.environ.get(spec.client_id_env, "").strip(), os.environ.get(spec.client_secret_env, "").strip()


class LinkedInOAuthAdapter(OAuthAdapter):
    """Real LinkedIn transport for the `linkedin` OAuth provider (3-legged, confidential client)."""

    def __init__(self, http: Http = urllib_http, timeout: float = 25.0):
        self.http = http
        self.timeout = timeout

    def ready(self, spec: OAuthProvider) -> bool:
        return all(client_credentials(spec))

    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        client_id, client_secret = client_credentials(spec)
        if not (client_id and client_secret):
            raise OAuthError("client_secret_missing")
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": client_id, "client_secret": client_secret}
        status, _, raw = self.http("POST", spec.token_url, {"Content-Type": "application/x-www-form-urlencoded",
                                                            "Accept": "application/json"},
                                   urlencode(form).encode(), self.timeout)
        data = _json(raw)
        if status != 200 or not data.get("access_token"):
            raise OAuthError("exchange_failed")
        tokens = TokenSet(access_token=data["access_token"], refresh_token=str(data.get("refresh_token") or ""),
                          expires_in=int(data.get("expires_in") or 0),
                          scopes=tuple(str(data.get("scope") or "").replace(",", " ").split()) or spec.scopes)
        tokens.account_id, tokens.account_label = self.member(tokens)
        return tokens

    def member(self, tokens: TokenSet) -> tuple:
        status, _, raw = self.http("GET", USERINFO_URL, {"Authorization": "Bearer " + tokens.access_token,
                                                         "Accept": "application/json"}, None, self.timeout)
        data = _json(raw) if status == 200 else {}
        sub = str(data.get("sub") or "")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", sub):
            raise OAuthError("linkedin_member_missing")
        return "urn:li:person:" + sub, str(data.get("name") or "")[:180]

    def revoke(self, spec, tokens):
        client_id, client_secret = client_credentials(spec)
        status, _, _ = self.http("POST", spec.revoke_url, {"Content-Type": "application/x-www-form-urlencoded"},
                                 urlencode({"client_id": client_id, "client_secret": client_secret,
                                            "token": tokens.access_token}).encode(), self.timeout)
        return status == 200


def escape_commentary(text: str) -> str:
    return _RESERVED.sub(r"\\\1", text)


def clean_text(text) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def upload_image(http: Http, access_token: str, author_urn: str, png: bytes, version: str,
                 timeout: float = 60.0) -> str:
    """Images API: initializeUpload, then PUT the bytes. Returns the image URN. Nothing is posted here, so every
    failure is a plain (certain) one; an orphan uploaded image is harmless."""
    if not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]{1,100}", author_urn or ""):
        raise LinkedInError("linkedin_author_missing")
    if not isinstance(png, (bytes, bytearray)) or not png or len(png) > IMAGE_MAX_BYTES:
        raise LinkedInError("linkedin_image_invalid")
    try:
        status, _, raw = http("POST", IMAGES_INIT_URL, {
            "Authorization": "Bearer " + access_token, "Content-Type": "application/json",
            "LinkedIn-Version": version, "X-Restli-Protocol-Version": "2.0.0"},
            json.dumps({"initializeUploadRequest": {"owner": author_urn}}).encode("utf-8"), timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        raise LinkedInError("linkedin_image_init_failed") from None
    fixed = {401: "linkedin_auth_failed", 403: "linkedin_permission_denied", 426: "linkedin_version_unsupported",
             429: "linkedin_rate_limited"}
    if status in fixed:
        raise LinkedInError(fixed[status])
    value = _json(raw).get("value") if status == 200 else None
    value = value if isinstance(value, dict) else {}
    upload_url, urn = str(value.get("uploadUrl") or ""), str(value.get("image") or "")
    if status != 200 or not IMAGE_URN_RE.fullmatch(urn) or not UPLOAD_HOST_RE.match(upload_url):
        raise LinkedInError("linkedin_image_init_failed")
    try:
        status, _, _ = http("PUT", upload_url, {"Authorization": "Bearer " + access_token,
                                                "Content-Type": "application/octet-stream"}, bytes(png), timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        raise LinkedInError("linkedin_image_upload_failed") from None
    if status not in (200, 201):
        raise LinkedInError("linkedin_image_upload_failed")
    return urn


def create_post(http: Http, access_token: str, author_urn: str, text: str, version: str,
                timeout: float = 30.0, image_urn: str = "", alt_text: str = "") -> dict:
    """Create one public post (text, or text + one uploaded image). Returns {post_urn, url}. Raises LinkedInError."""
    if not re.fullmatch(r"urn:li:person:[A-Za-z0-9_-]{1,100}", author_urn or ""):
        raise LinkedInError("linkedin_author_missing")
    body = {"author": author_urn, "commentary": escape_commentary(text), "visibility": "PUBLIC",
            "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                             "thirdPartyDistributionChannels": []},
            "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    if image_urn:
        if not IMAGE_URN_RE.fullmatch(image_urn):
            raise LinkedInError("linkedin_image_invalid")
        media = {"id": image_urn}
        alt = clean_text(alt_text).replace("\n", " ")[:300]
        if alt:
            media["altText"] = alt
        body["content"] = {"media": media}
    try:
        status, headers, _ = http("POST", POSTS_URL, {
            "Authorization": "Bearer " + access_token, "Content-Type": "application/json",
            "LinkedIn-Version": version, "X-Restli-Protocol-Version": "2.0.0"},
            json.dumps(body, ensure_ascii=False).encode("utf-8"), timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        raise LinkedInError("linkedin_outcome_uncertain", uncertain=True)
    if status == 201:
        urn = str(headers.get("x-restli-id") or headers.get("x-linkedin-id") or "")
        if not re.fullmatch(r"urn:li:(share|ugcPost):\d{1,30}", urn):
            raise LinkedInError("linkedin_created_without_id", uncertain=True)
        return {"post_urn": urn, "url": "https://www.linkedin.com/feed/update/" + quote(urn, safe=":")}
    if status == 401:
        raise LinkedInError("linkedin_auth_failed")
    if status == 403:
        raise LinkedInError("linkedin_permission_denied")
    if status == 422:
        raise LinkedInError("linkedin_duplicate_or_invalid")
    if status == 426:
        raise LinkedInError("linkedin_version_unsupported")
    if status == 429:
        raise LinkedInError("linkedin_rate_limited")
    raise LinkedInError(f"linkedin_rejected_{status}", uncertain=status >= 500)


class PostStore:
    """Drafts in DATA_DIR/linkedin_posts.json, one lock, atomic writes."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "linkedin_posts.json"
        self.clock, self.lock = clock, threading.RLock()

    def _load(self) -> list:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-MAX_DRAFTS:], ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def _find(self, items, draft_id):
        item = next((d for d in items if d["id"] == draft_id), None) if ID_RE.fullmatch(draft_id or "") else None
        if not item:
            raise HTTPException(404, "unknown draft")
        return item

    def list(self) -> list:
        with self.lock:
            return list(reversed(self._load()))

    def create(self, text) -> dict:
        text = clean_text(text)
        if not text or len(text) > TEXT_MAX:
            raise HTTPException(400, f"text must be 1–{TEXT_MAX} characters")
        draft = {"id": "li_" + secrets.token_hex(6), "text": text, "status": "draft",
                 "created": int(self.clock()), "approved_hash": "", "approved_at": 0, "result": None}
        with self.lock:
            items = self._load()
            items.append(draft)
            self._save(items)
        return draft

    def edit(self, draft_id, text) -> dict:
        text = clean_text(text)
        if not text or len(text) > TEXT_MAX:
            raise HTTPException(400, f"text must be 1–{TEXT_MAX} characters")
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] not in ("draft", "approved", "failed"):
                raise HTTPException(409, "this draft can no longer be edited")
            draft.update(text=text, status="draft", approved_hash="", approved_at=0)   # an edit drops approval
            self._save(items)
            return draft

    def approve(self, draft_id) -> dict:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] not in ("draft", "failed"):
                raise HTTPException(409, "only a draft can be approved")
            draft.update(status="approved", approved_hash=text_hash(draft["text"]), approved_at=int(self.clock()))
            self._save(items)
            return draft

    def delete(self, draft_id) -> bool:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] in ("publishing", "published", "uncertain"):
                raise HTTPException(409, "a sent post stays in the history")
            self._save([d for d in items if d["id"] != draft_id])
            return True

    def claim_for_publish(self, draft_id) -> dict:
        """approved → publishing, atomically; the approval must still match the exact text."""
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] == "published":
                raise HTTPException(409, "already published")
            if draft["status"] in ("publishing", "uncertain"):
                raise HTTPException(409, "an earlier attempt has an unknown outcome; check LinkedIn and confirm")
            if draft["status"] != "approved" or draft["approved_hash"] != text_hash(draft["text"]):
                raise HTTPException(409, "approve this exact text before publishing")
            draft["status"] = "publishing"
            self._save(items)
            return dict(draft)

    def finish(self, draft_id, status, result) -> dict:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            draft.update(status=status, result=result)
            self._save(items)
            return draft

    def confirm(self, draft_id, outcome) -> dict:
        """Owner checked LinkedIn after an unknown outcome: 'published' (with URL) or 'not_published'."""
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] != "uncertain":
                raise HTTPException(409, "only an unknown outcome needs confirmation")
            if outcome == "not_published":
                draft.update(status="failed", result={"code": "owner_confirmed_not_published"})
            else:
                url = str(outcome or "")
                if not re.fullmatch(r"https://(www\.)?linkedin\.com/[^\s]{1,300}", url):
                    raise HTTPException(400, "paste the LinkedIn post URL, or 'not_published'")
                draft.update(status="published", result={"url": url, "source": "owner_confirmed"})
            self._save(items)
            return draft


def readiness(flow, workspace_id: str, env=None) -> tuple:
    """(blockers, tokens) for publishing as the connected member. Shared by the draft routes and the T-702 adapter."""
    from oauth_framework import get_provider
    spec = get_provider("linkedin")
    blockers = list(flow.blockers(spec))
    tokens = None
    if "vault_unavailable" not in blockers:
        try:
            tokens = flow.vault.get(workspace_id, "linkedin")
        except Exception:
            blockers.append("vault_unreadable")
    if not tokens and not blockers:
        blockers.append("linkedin_not_connected")
    if not enabled(env):
        blockers.append("linkedin_publishing_off")
    return blockers, tokens


def send_text(flow, workspace_id: str, text: str, *, http: Http | None = None, env=None,
              image: bytes | None = None, alt: str = "") -> dict:
    """The one LinkedIn publish path: re-checks readiness, uploads the image (if any), then creates the post.
    Raises LinkedInError. Callers own the approval fence and the claim-before-send (PostStore here,
    social_autopilot for T-702/T-713)."""
    blockers, tokens = readiness(flow, workspace_id, env)
    if blockers:
        raise LinkedInError("linkedin_not_ready")
    transport = http or getattr(flow.adapters.get("linkedin"), "http", urllib_http)
    version = api_version(env)
    image_urn = upload_image(transport, tokens.access_token, tokens.account_id, image, version) if image else ""
    return create_post(transport, tokens.access_token, tokens.account_id, text, version,
                       image_urn=image_urn, alt_text=alt)


def install_routes(app, *, store: PostStore, flow, identity: Callable, workspace: Callable[[], str],
                   http: Http | None = None, env=None) -> None:
    def owner(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def state() -> dict:
        from oauth_framework import get_provider
        spec = get_provider("linkedin")
        blockers, tokens = readiness(flow, workspace(), env)
        return {"enabled": enabled(env), "ready": not blockers, "blockers": blockers,
                "account": (tokens.account_label if tokens else ""), "connected": bool(tokens),
                "api_version": api_version(env), "redirect_uri": flow.redirect_uri(spec), "text_max": TEXT_MAX}

    @app.get("/api/factory/linkedin")
    def linkedin_state(request: Request):
        owner(request)
        return {**state(), "drafts": store.list()}

    @app.post("/api/factory/linkedin/drafts")
    async def linkedin_create(request: Request):
        owner(request)
        return {"draft": store.create((await body(request)).get("text"))}

    @app.post("/api/factory/linkedin/drafts/{draft_id}/edit")
    async def linkedin_edit(draft_id: str, request: Request):
        owner(request)
        return {"draft": store.edit(draft_id, (await body(request)).get("text"))}

    @app.post("/api/factory/linkedin/drafts/{draft_id}/approve")
    def linkedin_approve(draft_id: str, request: Request):
        owner(request)
        return {"draft": store.approve(draft_id)}

    @app.post("/api/factory/linkedin/drafts/{draft_id}/delete")
    def linkedin_delete(draft_id: str, request: Request):
        owner(request)
        return {"ok": store.delete(draft_id)}

    @app.post("/api/factory/linkedin/drafts/{draft_id}/confirm")
    async def linkedin_confirm(draft_id: str, request: Request):
        owner(request)
        return {"draft": store.confirm(draft_id, (await body(request)).get("outcome"))}

    @app.post("/api/factory/linkedin/drafts/{draft_id}/publish")
    def linkedin_publish(draft_id: str, request: Request):
        owner(request)
        current = state()
        if not current["ready"]:
            raise HTTPException(409, "LinkedIn is not ready: " + ", ".join(current["blockers"]))
        draft = store.claim_for_publish(draft_id)
        try:
            result = send_text(flow, workspace(), draft["text"], http=http, env=env)
        except LinkedInError as exc:
            store.finish(draft_id, "uncertain" if exc.uncertain else "failed", {"code": exc.code})
            raise HTTPException(409 if exc.uncertain else 502, exc.code) from None
        return {"draft": store.finish(draft_id, "published", {**result, "published_at": int(time.time())})}
