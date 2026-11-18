"""OLX adverts through the official OLX Partner API (owner 2026-11-17, T-701).

Path: the owner's own OLX Partner API application (developer.olx.ua, T-701-H), OAuth 2.0 `authorization_code`
with scopes `v2 read write`, then `https://www.olx.ua/api/partner/...` with `Version: 2.0`. FactoryOS never logs in to
olx.ua through a browser and never automates its pages. Sources and open points: docs/guides/olx-partner-api.md.

Flow, all owner-only: draft → approve (freezes the exact advert: SHA-256 of its canonical JSON) → publish.
- Publishing is off until the owner sets FACTORY_OLX_ENABLED=1 (the code ships dark).
- Publish refuses a draft whose advert changed after approval, one already published, and one whose earlier attempt
  ended with an unknown outcome (timeout / 5xx / reply without an id). Each advert carries `external_id` = draft id,
  so the owner can reconcile an unknown outcome with a read-only lookup instead of a blind resend.
- FactoryOS never buys packets or paid features: an advert OLX puts in `limited` stays there for the owner to decide.
- Errors carry fixed codes; OLX response bodies and tokens are never stored, logged or returned (only the names of the
  fields OLX rejected).
- Network goes through one injectable `http` callable, so the tests make zero network calls.

For the social autopilot (T-702): `publish_approved(...)` is the one entry point that keeps every fence above;
`publish_draft(...)` is the bare API call on an already-claimed draft.
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

SITE = "https://www.olx.ua"                      # client credentials work for one OLX country only (OLX FAQ #8)
API = SITE + "/api/partner"
TOKEN_URL = SITE + "/api/open/oauth/token"
AUTHORIZE_URL = SITE + "/oauth/authorize/"
SCOPE = "v2 read write"
API_VERSION = "2.0"                              # required `Version` header
TITLE_MIN, TITLE_MAX = 16, 70                    # OLX "Create advert" validation rules
DESC_MIN, DESC_MAX = 80, 9000
IMAGES_MAX = 20                                  # local cap only; OLX enforces the category's `photos_limit`
ATTRIBUTES_MAX = 60
MAX_DRAFTS = 200
STALE_CLAIM_SECONDS = 300                        # a publish claim older than this died mid-request: reconcile it
ID_RE = re.compile(r"^olx_[0-9a-f]{12}$")
CODE_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,60}$")
FIELD_RE = re.compile(r"^[A-Za-z0-9_.\-/\[\]]{1,60}$")
ADVERT_URL_RE = re.compile(r"^https://(www\.|m\.)?olx\.ua/[^\s]{1,400}$")
STATUSES = {"new", "active", "limited", "removed_by_user", "outdated", "unconfirmed", "unpaid", "moderated",
            "blocked", "disabled", "removed_by_moderator"}
_PUNCT = re.escape("!?.,-=+#%&@*_><:()|")
_REPEATED_PUNCT = re.compile(r"([" + _PUNCT + r"])\1\1")
_EMAIL_OR_WWW = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+|\bwww\.|https?://", re.I)
_PHONE = re.compile(r"(?:\+?\d[\s\-()]{0,2}){9,}")

Http = Callable[[str, str, dict, object, float], tuple]


class OlxError(RuntimeError):
    """Fixed, token-free code. `uncertain` = the advert may have been created (do not retry blindly)."""

    def __init__(self, code: str, uncertain: bool = False, fields: tuple = ()):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain
        self.fields = tuple(fields)


def urllib_http(method, url, headers, body, timeout):
    req = urlrequest.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urlerror.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read() or b""


def _json(body: bytes):
    try:
        return json.loads((body or b"null").decode("utf-8", "replace"))
    except ValueError:
        return None


def _data(body: bytes):
    """OLX wraps some replies in {"data": ...} and returns others bare."""
    value = _json(body)
    if isinstance(value, dict) and "data" in value and len(value) <= 2:
        return value["data"]
    return value


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("FACTORY_OLX_ENABLED", "")).strip().lower() in ("1", "true", "yes")


def language(env=None) -> str:
    env = os.environ if env is None else env
    value = str(env.get("FACTORY_OLX_LANGUAGE", "")).strip().lower()
    return value if value in ("uk", "ru") else "uk"


def client_credentials(spec: OAuthProvider) -> tuple:
    return os.environ.get(spec.client_id_env, "").strip(), os.environ.get(spec.client_secret_env, "").strip()


def api_headers(access_token: str, lang: str = "uk", body: bool = False) -> dict:
    headers = {"Authorization": "Bearer " + access_token, "Version": API_VERSION, "Accept": "application/json",
               "Accept-Language": lang}
    if body:                                     # OLX FAQ #2: no Content-Type on GET requests
        headers["Content-Type"] = "application/json"
    return headers


class OlxOAuthAdapter(OAuthAdapter):
    """Real OLX transport for the `olx` OAuth provider (authorization_code + refresh_token, confidential client)."""

    def __init__(self, http: Http = urllib_http, timeout: float = 25.0):
        self.http = http
        self.timeout = timeout

    def ready(self, spec: OAuthProvider) -> bool:
        return all(client_credentials(spec))

    def _token(self, spec, fields: dict) -> dict:
        client_id, client_secret = client_credentials(spec)
        if not (client_id and client_secret):
            raise OAuthError("client_secret_missing")
        body = json.dumps({**fields, "client_id": client_id, "client_secret": client_secret}).encode()
        try:
            status, _, raw = self.http("POST", spec.token_url, {"Content-Type": "application/json",
                                                                "Accept": "application/json"}, body, self.timeout)
        except (TimeoutError, OSError, urlerror.URLError):
            raise OAuthError("olx_token_unreachable")
        data = _json(raw)
        if status != 200 or not isinstance(data, dict) or not data.get("access_token"):
            raise OAuthError("exchange_failed" if fields.get("grant_type") == "authorization_code"
                             else "olx_reconnect_required")
        return data

    @staticmethod
    def _tokens(data: dict, spec, previous: TokenSet | None = None) -> TokenSet:
        return TokenSet(access_token=str(data["access_token"]),
                        refresh_token=str(data.get("refresh_token") or (previous.refresh_token if previous else "")),
                        expires_in=int(data.get("expires_in") or 0),
                        scopes=tuple(str(data.get("scope") or "").split()) or spec.scopes,
                        account_id=previous.account_id if previous else "",
                        account_label=previous.account_label if previous else "")

    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        # redirect_uri is sent in the authorize step, so OLX requires it here too.
        data = self._token(spec, {"grant_type": "authorization_code", "code": code, "scope": SCOPE,
                                  "redirect_uri": redirect_uri})
        tokens = self._tokens(data, spec)
        tokens.account_id, tokens.account_label = self.user(tokens)
        return tokens

    def refresh(self, spec, tokens: TokenSet) -> TokenSet:
        """Access tokens live 24 h; the refresh token 30 days and may rotate (OLX docs, Authentication)."""
        if not tokens.refresh_token:
            raise OAuthError("olx_reconnect_required")
        data = self._token(spec, {"grant_type": "refresh_token", "refresh_token": tokens.refresh_token})
        return self._tokens(data, spec, previous=tokens)

    def user(self, tokens: TokenSet) -> tuple:
        try:
            status, _, raw = self.http("GET", API + "/users/me", api_headers(tokens.access_token), None, self.timeout)
        except (TimeoutError, OSError, urlerror.URLError):
            raise OAuthError("olx_user_unreachable")
        data = _data(raw) if status == 200 else None
        user_id = str((data or {}).get("id") or "") if isinstance(data, dict) else ""
        if not re.fullmatch(r"\d{1,20}", user_id):
            raise OAuthError("olx_user_missing")
        return "olx:user:" + user_id, str(data.get("name") or "")[:180]

    def revoke(self, spec, tokens):
        # The public OLX docs list no revoke endpoint: disconnect forgets the tokens locally; the owner removes the
        # app's access in the OLX account if wanted (docs/guides/olx-partner-api.md, open question 3).
        return False


# --- Advert validation ------------------------------------------------------------------

def clean_text(text) -> str:
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return "".join(ch for ch in text if ch in "\n\t" or ord(ch) >= 32)


def text_problems(text: str) -> list:
    """Local copy of the documented OLX title/description rules; OLX moderation stays the final judge."""
    out = []
    letters = [ch for ch in text if ch.isalpha()]
    if letters and sum(ch.isupper() for ch in letters) * 2 > len(letters):
        out.append("too_many_capitals")
    if _REPEATED_PUNCT.search(text):
        out.append("repeated_punctuation")
    if _EMAIL_OR_WWW.search(text):
        out.append("contains_email_or_www")
    if _PHONE.search(text):
        out.append("contains_phone")
    return out


def _bad(code: str):
    raise HTTPException(400, code)


def _int(value, code, required=True):
    if value in (None, "") and not required:
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        _bad(code)
    if number <= 0 or number > 10 ** 12:
        _bad(code)
    return number


def clean_advert(data) -> dict:
    """Validate the owner's advert form into the exact OLX `POST /adverts` body (without external_id)."""
    if not isinstance(data, dict):
        _bad("olx_advert_required")
    title, description = clean_text(data.get("title")), clean_text(data.get("description"))
    if not TITLE_MIN <= len(title) <= TITLE_MAX:
        _bad(f"olx_title_length_{TITLE_MIN}_{TITLE_MAX}")
    if not DESC_MIN <= len(description) <= DESC_MAX:
        _bad(f"olx_description_length_{DESC_MIN}_{DESC_MAX}")
    for name, text in (("title", title), ("description", description)):
        problems = text_problems(text)
        if problems:
            _bad(f"olx_{name}_{problems[0]}")
    advertiser = str(data.get("advertiser_type") or "private").strip()
    if advertiser not in ("private", "business"):
        _bad("olx_advertiser_type")
    contact_in = data.get("contact") if isinstance(data.get("contact"), dict) else {}
    contact = {"name": clean_text(contact_in.get("name"))[:100]}
    if not contact["name"]:
        _bad("olx_contact_name_required")
    phone = str(contact_in.get("phone") or "").strip()
    if phone:
        if not re.fullmatch(r"\+?[0-9 ()\-]{9,20}", phone):
            _bad("olx_contact_phone")
        contact["phone"] = phone
    loc_in = data.get("location") if isinstance(data.get("location"), dict) else {}
    location = {"city_id": _int(loc_in.get("city_id"), "olx_city_id")}
    district = _int(loc_in.get("district_id"), "olx_district_id", required=False)
    if district:
        location["district_id"] = district
    images = data.get("images") or []
    if not isinstance(images, list) or len(images) > IMAGES_MAX:
        _bad("olx_images")
    clean_images = []
    for item in images:
        url = str(item.get("url") if isinstance(item, dict) else item or "").strip()
        if not re.fullmatch(r"https://[^\s\"'<>]{4,1000}", url):
            _bad("olx_image_url_https")
        clean_images.append({"url": url})
    advert = {"title": title, "description": description,
              "category_id": _int(data.get("category_id"), "olx_category_id"),
              "advertiser_type": advertiser, "contact": contact, "location": location, "images": clean_images}
    price_in = data.get("price")
    if isinstance(price_in, dict) and price_in.get("value") not in (None, ""):
        try:
            value = round(float(price_in.get("value")), 2)
        except (TypeError, ValueError):
            _bad("olx_price_value")
        currency = str(price_in.get("currency") or "UAH").strip().upper()
        if not (0 <= value < 10 ** 12) or not re.fullmatch(r"[A-Z]{3}", currency):
            _bad("olx_price_value")
        advert["price"] = {"value": int(value) if value == int(value) else value, "currency": currency,
                           "negotiable": bool(price_in.get("negotiable")), "trade": bool(price_in.get("trade"))}
    attributes = data.get("attributes") or []
    if not isinstance(attributes, list) or len(attributes) > ATTRIBUTES_MAX:
        _bad("olx_attributes")
    clean_attrs = []
    for item in attributes:                      # OLX: each item holds `code` and `value` only
        if not isinstance(item, dict) or not CODE_RE.fullmatch(str(item.get("code") or "")):
            _bad("olx_attribute_code")
        value = clean_text(item.get("value"))[:300]
        if not value:
            _bad("olx_attribute_value")
        clean_attrs.append({"code": str(item["code"]), "value": value})
    advert["attributes"] = clean_attrs
    return advert


def advert_hash(advert: dict) -> str:
    return hashlib.sha256(json.dumps(advert, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# --- OLX API calls ------------------------------------------------------------------------

def _fields(raw: bytes) -> tuple:
    data = _json(raw)
    err = data.get("error") if isinstance(data, dict) else None
    items = err.get("validation") if isinstance(err, dict) else None
    out = []
    for item in items if isinstance(items, list) else []:
        field = str(item.get("field") or "") if isinstance(item, dict) else ""
        if FIELD_RE.fullmatch(field) and field not in out:
            out.append(field)
    return tuple(out[:10])


def _raise_for(status: int, raw: bytes, write: bool):
    if status == 400:
        raise OlxError("olx_invalid_request", fields=_fields(raw))
    if status == 401:
        raise OlxError("olx_auth_failed")
    if status == 403:
        raise OlxError("olx_forbidden")
    if status == 404:
        raise OlxError("olx_not_found")
    if status == 429:
        raise OlxError("olx_rate_limited")
    raise OlxError(f"olx_rejected_{status}", uncertain=write and status >= 500)


def _call(http: Http, method: str, path: str, access_token: str, lang: str, body=None, timeout: float = 30.0,
          write: bool = False):
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    try:
        return http(method, API + path, api_headers(access_token, lang, body=payload is not None), payload, timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        raise OlxError("olx_outcome_uncertain" if write else "olx_unreachable", uncertain=write)


def _receipt(advert) -> dict:
    advert = advert if isinstance(advert, dict) else {}
    advert_id = str(advert.get("id") or "")
    if not re.fullmatch(r"\d{1,20}", advert_id):
        return {}
    url = str(advert.get("url") or "")
    status = str(advert.get("status") or "")
    out = {"advert_id": advert_id, "olx_status": status if status in STATUSES else "unknown",
           "url": url if ADVERT_URL_RE.fullmatch(url) else "",
           "valid_to": str(advert.get("valid_to") or "")[:40]}
    if out["olx_status"] == "limited":
        out["note"] = "olx_limited_needs_packet"  # paid packet needed; FactoryOS never buys one
    return out


def create_advert(http: Http, access_token: str, advert: dict, external_id: str, lang: str = "uk") -> dict:
    """`POST /api/partner/adverts` once. Returns the receipt. Raises OlxError (never with tokens or OLX text)."""
    status, _, raw = _call(http, "POST", "/adverts", access_token, lang, {**advert, "external_id": external_id},
                           write=True)
    if status in (200, 201):
        receipt = _receipt(_data(raw))
        if not receipt:
            raise OlxError("olx_created_without_id", uncertain=True)
        return receipt
    _raise_for(status, raw, write=True)


def find_by_external_id(http: Http, access_token: str, external_id: str, lang: str = "uk") -> list:
    status, _, raw = _call(http, "GET", "/adverts?" + urlencode({"external_id": external_id}), access_token, lang)
    if status != 200:
        _raise_for(status, raw, write=False)
    items = _data(raw)
    # Keep only adverts that echo this exact external_id (a missing or different value is not a match).
    mine = [a for a in (items if isinstance(items, list) else [])
            if isinstance(a, dict) and str(a.get("external_id") or "") == external_id]
    return [r for r in (_receipt(a) for a in mine) if r]


def get_advert(http: Http, access_token: str, advert_id: str, lang: str = "uk") -> dict:
    status, _, raw = _call(http, "GET", "/adverts/" + quote(advert_id, safe=""), access_token, lang)
    if status != 200:
        _raise_for(status, raw, write=False)
    receipt = _receipt(_data(raw))
    if not receipt:
        raise OlxError("olx_advert_unreadable")
    return receipt


def deactivate_advert(http: Http, access_token: str, advert_id: str, sold: bool, lang: str = "uk") -> None:
    status, _, raw = _call(http, "POST", "/adverts/" + quote(advert_id, safe="") + "/commands", access_token, lang,
                           {"command": "deactivate", "is_success": bool(sold)})
    if status not in (200, 204):
        _raise_for(status, raw, write=False)


def publish_draft(http: Http, access_token: str, draft: dict, lang: str = "uk") -> dict:
    """The bare API call for a draft already claimed by `AdvertStore.claim_for_publish`."""
    return create_advert(http, access_token, draft["advert"], draft["id"], lang)


# --- Draft store ---------------------------------------------------------------------------

class AdvertStore:
    """Drafts in DATA_DIR/olx_adverts.json, one lock, atomic writes."""

    def __init__(self, data_dir: Path, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "olx_adverts.json"
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

    def get(self, draft_id) -> dict:
        with self.lock:
            return dict(self._find(self._load(), draft_id))

    def create(self, advert) -> dict:
        draft = {"id": "olx_" + secrets.token_hex(6), "advert": clean_advert(advert), "status": "draft",
                 "created": int(self.clock()), "approved_hash": "", "approved_at": 0, "result": None}
        with self.lock:
            items = self._load()
            items.append(draft)
            self._save(items)
        return draft

    def edit(self, draft_id, advert) -> dict:
        advert = clean_advert(advert)
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] not in ("draft", "approved", "failed"):
                raise HTTPException(409, "this draft can no longer be edited")
            draft.update(advert=advert, status="draft", approved_hash="", approved_at=0,  # an edit drops approval
                         approved_account="")
            self._save(items)
            return draft

    def approve(self, draft_id, account_id: str = "") -> dict:
        """Freeze the exact advert and the OLX account it was approved for (publish refuses another account)."""
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] not in ("draft", "failed"):
                raise HTTPException(409, "only a draft can be approved")
            draft.update(status="approved", approved_hash=advert_hash(draft["advert"]),
                         approved_at=int(self.clock()), approved_account=str(account_id or ""))
            self._save(items)
            return draft

    def delete(self, draft_id) -> bool:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if draft["status"] in ("publishing", "published", "uncertain", "deactivated"):
                raise HTTPException(409, "a sent advert stays in the history")
            self._save([d for d in items if d["id"] != draft_id])
            return True

    def check_publishable(self, draft_id) -> None:
        """Read-only pre-check so no OLX call (token refresh) happens for a draft that cannot be published."""
        with self.lock:
            self._check(self._find(self._load(), draft_id))

    @staticmethod
    def _check(draft):
        if draft["status"] in ("published", "deactivated"):
            raise HTTPException(409, "already published")
        if draft["status"] in ("publishing", "uncertain"):
            raise HTTPException(409, "an earlier attempt has an unknown outcome; check OLX and confirm")
        if draft["status"] != "approved" or draft["approved_hash"] != advert_hash(draft["advert"]):
            raise HTTPException(409, "approve this exact advert before publishing")

    def claim_for_publish(self, draft_id) -> dict:
        """approved → publishing, atomically; the approval must still match the exact advert."""
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            self._check(draft)
            draft.update(status="publishing", claimed_at=int(self.clock()))
            self._save(items)
            return dict(draft)

    def finish(self, draft_id, status, result) -> dict:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            draft.update(status=status, result=result)
            self._save(items)
            return draft

    def update_result(self, draft_id, receipt: dict, status: str | None = None) -> dict:
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            draft["result"] = {**(draft.get("result") or {}), **receipt, "checked_at": int(self.clock())}
            if status:
                draft["status"] = status
            self._save(items)
            return draft

    def unresolved(self, draft) -> bool:
        """Unknown outcome, or a publish claim older than STALE_CLAIM_SECONDS (process died after the POST)."""
        return draft["status"] == "uncertain" or (
            draft["status"] == "publishing" and self.clock() - int(draft.get("claimed_at") or 0) > STALE_CLAIM_SECONDS)

    def confirm(self, draft_id, outcome) -> dict:
        """Owner checked OLX after an unknown outcome: 'not_published', or the advert URL."""
        with self.lock:
            items = self._load()
            draft = self._find(items, draft_id)
            if not self.unresolved(draft):
                raise HTTPException(409, "only an unknown outcome needs confirmation")
            if outcome == "not_published":
                draft.update(status="failed", result={"code": "owner_confirmed_not_published"})
            else:
                url = str(outcome or "")
                if not ADVERT_URL_RE.fullmatch(url):
                    raise HTTPException(400, "paste the OLX advert URL, or 'not_published'")
                draft.update(status="published", result={"url": url, "source": "owner_confirmed"})
            self._save(items)
            return draft


# --- Publishing with every fence (routes and T-702 use this) -------------------------------

def fresh_tokens(flow, workspace: str) -> TokenSet:
    """Refresh before each write (OLX returns the same token while it is still valid) and store the result."""
    from oauth_framework import get_provider
    spec = get_provider("olx")
    tokens = flow.vault.get(workspace, "olx")
    if not tokens:
        raise OlxError("olx_not_connected")
    adapter = flow.adapters.get("olx")
    if adapter is None or not hasattr(adapter, "refresh") or not tokens.refresh_token:
        return tokens
    try:
        new = adapter.refresh(spec, tokens)
    except OAuthError as exc:
        raise OlxError(exc.code if exc.code.startswith("olx_") else "olx_reconnect_required") from None
    flow.vault.put(workspace, "olx", new)
    return new


def publish_approved(*, store: AdvertStore, flow, workspace: str, draft_id: str, http: Http | None = None,
                     env=None) -> dict:
    """Publish one owner-approved draft exactly once. Raises HTTPException with a fixed code."""
    if not enabled(env):
        raise HTTPException(409, "olx_publishing_off")
    store.check_publishable(draft_id)
    try:
        tokens = fresh_tokens(flow, workspace)
    except OlxError as exc:
        raise HTTPException(409, exc.code) from None
    approved_for = str(store.get(draft_id).get("approved_account") or "")
    if not approved_for or approved_for != tokens.account_id:
        raise HTTPException(409, "olx_account_changed_approve_again")
    draft = store.claim_for_publish(draft_id)
    transport = http or getattr(flow.adapters.get("olx"), "http", urllib_http)
    try:
        receipt = publish_draft(transport, tokens.access_token, draft, language(env))
    except OlxError as exc:
        result = {"code": exc.code, **({"fields": list(exc.fields)} if exc.fields else {})}
        store.finish(draft_id, "uncertain" if exc.uncertain else "failed", result)
        raise HTTPException(409 if exc.uncertain else 502, exc.code) from None
    return store.finish(draft_id, "published", {**receipt, "published_at": int(time.time())})


# --- Reference data (read-only) --------------------------------------------------------------

_REFERENCE = {
    "categories": ("/categories", ("id", "name", "parent_id", "photos_limit", "is_leaf")),
    "category": ("/categories/{id}", ("id", "name", "parent_id", "photos_limit", "is_leaf")),
    "attributes": ("/categories/{id}/attributes", ("code", "label", "unit", "validation", "values")),
    "suggest": ("/categories/suggestion", ("id", "name", "path")),
    "regions": ("/regions", ("id", "name")),
    "cities": ("/cities", ("id", "region_id", "name", "county", "municipality")),
    "districts": ("/cities/{id}/districts", ("id", "city_id", "name")),
}


def reference(http: Http, access_token: str, kind: str, params: dict, lang: str = "uk"):
    if kind not in _REFERENCE:
        raise HTTPException(400, "unknown reference kind")
    path, keep = _REFERENCE[kind]
    query = {}
    if "{id}" in path:
        path = path.replace("{id}", str(_int(params.get("id"), "olx_reference_id")))
    if kind == "categories" and params.get("parent_id"):
        query["parent_id"] = _int(params.get("parent_id"), "olx_reference_id")
    if kind == "suggest":
        q = clean_text(params.get("q"))[:120]
        if len(q) < 3:
            raise HTTPException(400, "olx_suggest_query_min_3")
        query["q"] = q
    if kind == "cities":
        try:
            query["offset"] = max(0, min(int(str(params.get("offset") or 0)), 10 ** 6))
        except ValueError:
            _bad("olx_offset")
        query["limit"] = 200
    status, _, raw = _call(http, "GET", path + ("?" + urlencode(query) if query else ""), access_token, lang)
    if status != 200:
        _raise_for(status, raw, write=False)
    data = _data(raw)
    rows = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
    return [{k: row.get(k) for k in keep if k in row} for row in rows[:1000] if isinstance(row, dict)]


# --- Routes ----------------------------------------------------------------------------------

def install_routes(app, *, store: AdvertStore, flow, identity: Callable, workspace: Callable[[], str],
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

    def transport():
        return http or getattr(flow.adapters.get("olx"), "http", urllib_http)

    def state() -> dict:
        from oauth_framework import get_provider
        spec = get_provider("olx")
        blockers = list(flow.blockers(spec))
        tokens = None
        if "vault_unavailable" not in blockers:
            try:
                tokens = flow.vault.get(workspace(), "olx")
            except Exception:
                blockers.append("vault_unreadable")
        if not tokens and not blockers:
            blockers.append("olx_not_connected")
        if not enabled(env):
            blockers.append("olx_publishing_off")
        return {"enabled": enabled(env), "ready": not blockers, "blockers": blockers,
                "account": (tokens.account_label if tokens else ""), "connected": bool(tokens),
                "redirect_uri": flow.redirect_uri(spec), "language": language(env),
                "limits": {"title": [TITLE_MIN, TITLE_MAX], "description": [DESC_MIN, DESC_MAX],
                           "images": IMAGES_MAX}}

    def read_tokens() -> TokenSet:
        try:
            return fresh_tokens(flow, workspace())
        except OlxError as exc:
            raise HTTPException(409, exc.code) from None

    def published(draft_id) -> dict:
        draft = store.get(draft_id)
        advert_id = str((draft.get("result") or {}).get("advert_id") or "")
        if draft["status"] != "published" or not advert_id:
            raise HTTPException(409, "only a published advert with an OLX id")
        return draft

    @app.get("/api/factory/olx")
    def olx_state(request: Request):
        owner(request)
        return {**state(), "drafts": store.list()}

    @app.get("/api/factory/olx/reference/{kind}")
    def olx_reference(kind: str, request: Request):
        owner(request)
        tokens = read_tokens()
        try:
            return {"kind": kind, "items": reference(transport(), tokens.access_token, kind,
                                                     dict(request.query_params), language(env))}
        except OlxError as exc:
            raise HTTPException(502, exc.code) from None

    @app.post("/api/factory/olx/drafts")
    async def olx_create(request: Request):
        owner(request)
        return {"draft": store.create((await body(request)).get("advert"))}

    @app.post("/api/factory/olx/drafts/{draft_id}/edit")
    async def olx_edit(draft_id: str, request: Request):
        owner(request)
        return {"draft": store.edit(draft_id, (await body(request)).get("advert"))}

    @app.post("/api/factory/olx/drafts/{draft_id}/approve")
    def olx_approve(draft_id: str, request: Request):
        owner(request)
        try:
            tokens = flow.vault.get(workspace(), "olx")
        except Exception:
            tokens = None
        if not tokens or not tokens.account_id:
            raise HTTPException(409, "connect the OLX account before approving")
        return {"draft": store.approve(draft_id, tokens.account_id)}

    @app.post("/api/factory/olx/drafts/{draft_id}/delete")
    def olx_delete(draft_id: str, request: Request):
        owner(request)
        return {"ok": store.delete(draft_id)}

    @app.post("/api/factory/olx/drafts/{draft_id}/confirm")
    async def olx_confirm(draft_id: str, request: Request):
        owner(request)
        return {"draft": store.confirm(draft_id, (await body(request)).get("outcome"))}

    @app.post("/api/factory/olx/drafts/{draft_id}/publish")
    def olx_publish(draft_id: str, request: Request):
        owner(request)
        current = state()
        if not current["ready"]:
            raise HTTPException(409, "OLX is not ready: " + ", ".join(current["blockers"]))
        return {"draft": publish_approved(store=store, flow=flow, workspace=workspace(), draft_id=draft_id,
                                          http=http, env=env)}

    @app.post("/api/factory/olx/drafts/{draft_id}/reconcile")
    def olx_reconcile(draft_id: str, request: Request):
        """Unknown outcome → read-only lookup by external_id (= draft id). Found → published; else stays unknown."""
        owner(request)
        draft = store.get(draft_id)
        if not store.unresolved(draft):
            raise HTTPException(409, "only an unknown outcome needs reconciling")
        tokens = read_tokens()
        try:
            found = find_by_external_id(transport(), tokens.access_token, draft_id, language(env))
        except OlxError as exc:
            raise HTTPException(502, exc.code) from None
        if len(found) == 1:
            return {"found": True, "draft": store.finish(draft_id, "published",
                                                         {**found[0], "source": "reconciled_by_external_id"})}
        return {"found": False, "matches": len(found), "draft": draft}

    @app.post("/api/factory/olx/drafts/{draft_id}/refresh")
    def olx_refresh(draft_id: str, request: Request):
        owner(request)
        draft = published(draft_id)
        tokens = read_tokens()
        try:
            receipt = get_advert(transport(), tokens.access_token, draft["result"]["advert_id"], language(env))
        except OlxError as exc:
            raise HTTPException(502, exc.code) from None
        return {"draft": store.update_result(draft_id, receipt)}

    @app.post("/api/factory/olx/drafts/{draft_id}/deactivate")
    async def olx_deactivate(draft_id: str, request: Request):
        owner(request)
        data = await body(request)
        if data.get("confirm") is not True:
            raise HTTPException(400, "confirm: true required")
        if not enabled(env):
            raise HTTPException(409, "olx_publishing_off")
        draft = published(draft_id)
        tokens = read_tokens()
        try:
            deactivate_advert(transport(), tokens.access_token, draft["result"]["advert_id"],
                              bool(data.get("sold")), language(env))
        except OlxError as exc:
            raise HTTPException(502, exc.code) from None
        return {"draft": store.update_result(draft_id, {"olx_status": "removed_by_user"}, status="deactivated")}
