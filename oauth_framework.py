"""Provider-neutral OAuth scaffold for direct customer accounts (T-551-A).

Credential-free by design: this module never reads a client secret, never makes an HTTP
request and never logs or returns a token. Real provider adapters and the encrypted
token vault arrive in T-552; production OAuth applications are owner work (T-551).
Until both exist, every provider reports blockers and the authorize route refuses.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urlencode

log = logging.getLogger("factoryos.oauth")

STATE_TTL_SECONDS = 600
MAX_PENDING_STATES = 200


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    label: str
    integration: str  # key in app.PORTABLE_INTEGRATIONS
    authorize_url: str
    token_url: str
    revoke_url: str
    scopes: tuple
    pkce: bool
    client_id_env: str
    client_secret_env: str  # name only; the scaffold never reads the value
    client_id_param: str = "client_id"
    scope_separator: str = " "
    extra_params: tuple = ()


# Endpoint/scope values are the documented defaults and are re-verified when the real
# adapters are built in T-552. PKCE is enabled only where the provider supports it for
# server-side web apps.
PROVIDERS = {
    "youtube": OAuthProvider(
        id="youtube", label="Google / YouTube", integration="YouTube",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        revoke_url="https://oauth2.googleapis.com/revoke",
        scopes=("https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly"),
        pkce=True,
        client_id_env="FACTORY_OAUTH_GOOGLE_CLIENT_ID", client_secret_env="FACTORY_OAUTH_GOOGLE_CLIENT_SECRET",
        extra_params=(("access_type", "offline"), ("prompt", "consent"), ("include_granted_scopes", "true")),
    ),
    "tiktok": OAuthProvider(
        id="tiktok", label="TikTok", integration="TikTok",
        authorize_url="https://www.tiktok.com/v2/auth/authorize/",
        token_url="https://open.tiktokapis.com/v2/oauth/token/",
        revoke_url="https://open.tiktokapis.com/v2/oauth/revoke/",
        scopes=("user.info.basic", "video.upload", "video.publish"),
        pkce=False,
        client_id_env="FACTORY_OAUTH_TIKTOK_CLIENT_KEY", client_secret_env="FACTORY_OAUTH_TIKTOK_CLIENT_SECRET",
        client_id_param="client_key", scope_separator=",",
    ),
    "instagram": OAuthProvider(
        id="instagram", label="Meta / Instagram", integration="Instagram",
        authorize_url="https://www.facebook.com/v21.0/dialog/oauth",
        token_url="https://graph.facebook.com/v21.0/oauth/access_token",
        revoke_url="https://graph.facebook.com/v21.0/me/permissions",
        scopes=("instagram_basic", "instagram_content_publish", "pages_show_list", "business_management"),
        pkce=False,
        client_id_env="FACTORY_OAUTH_META_APP_ID", client_secret_env="FACTORY_OAUTH_META_APP_SECRET",
        scope_separator=",",
    ),
    # T-700 (owner 2026-11-17): member text posts through Share on LinkedIn + Sign In with LinkedIn (OpenID).
    "linkedin": OAuthProvider(
        id="linkedin", label="LinkedIn", integration="LinkedIn",
        authorize_url="https://www.linkedin.com/oauth/v2/authorization",
        token_url="https://www.linkedin.com/oauth/v2/accessToken",
        revoke_url="https://www.linkedin.com/oauth/v2/revoke",
        scopes=("openid", "profile", "w_member_social"),
        pkce=False,
        client_id_env="FACTORY_OAUTH_LINKEDIN_CLIENT_ID", client_secret_env="FACTORY_OAUTH_LINKEDIN_CLIENT_SECRET",
    ),
    # T-701 (owner 2026-11-17): OLX adverts through the OLX Partner API (developer.olx.ua). No revoke endpoint is
    # documented, so revoke_url is empty and disconnect only forgets the tokens. Scopes per the OLX docs.
    "olx": OAuthProvider(
        id="olx", label="OLX", integration="OLX",
        authorize_url="https://www.olx.ua/oauth/authorize/",
        token_url="https://www.olx.ua/api/open/oauth/token",
        revoke_url="",
        scopes=("read", "write", "v2"),
        pkce=False,
        client_id_env="FACTORY_OAUTH_OLX_CLIENT_ID", client_secret_env="FACTORY_OAUTH_OLX_CLIENT_SECRET",
    ),
    "hubspot": OAuthProvider(
        id="hubspot", label="HubSpot", integration="HubSpot",
        authorize_url="https://app.hubspot.com/oauth/authorize",
        token_url="https://api.hubapi.com/oauth/v1/token",
        revoke_url="https://api.hubapi.com/oauth/v1/refresh-tokens/",
        scopes=("oauth", "crm.objects.contacts.read", "crm.objects.contacts.write"),
        pkce=False,
        client_id_env="FACTORY_OAUTH_HUBSPOT_CLIENT_ID", client_secret_env="FACTORY_OAUTH_HUBSPOT_CLIENT_SECRET",
    ),
}


class OAuthError(Exception):
    """Carries only a fixed machine code; never provider text or token material."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def get_provider(provider_id: str) -> OAuthProvider:
    spec = PROVIDERS.get(str(provider_id or "").strip().lower())
    if not spec:
        raise OAuthError("unknown_provider")
    return spec


# --- PKCE (RFC 7636) ---------------------------------------------------------------

def pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]  # 43..128 unreserved chars


def pkce_challenge(verifier: str) -> str:
    if not 43 <= len(verifier) <= 128:
        raise OAuthError("pkce_verifier_invalid")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


# --- Tokens -------------------------------------------------------------------------

@dataclass
class TokenSet:
    access_token: str = field(repr=False)
    refresh_token: str = field(default="", repr=False)
    expires_in: int = 0
    scopes: tuple = ()
    account_id: str = ""
    account_label: str = ""

    def secret_values(self) -> list:
        return [v for v in (self.access_token, self.refresh_token) if v]


def redact(text: str, secret_values) -> str:
    out = str(text)
    for value in secret_values or ():
        if value:
            out = out.replace(value, "[redacted]")
    return out


class TokenVault:
    """Interface. Implementations store tokens server-side only; `status` is the only
    projection that may leave the server and it never includes token material."""

    kind = "abstract"
    durable = False
    encrypted = False

    def put(self, workspace: str, provider: str, tokens: TokenSet) -> None:
        raise NotImplementedError

    def get(self, workspace: str, provider: str):
        raise NotImplementedError

    def delete(self, workspace: str, provider: str) -> bool:
        raise NotImplementedError

    def status(self, workspace: str, provider: str) -> dict:
        tokens = self.get(workspace, provider)
        return {
            "stored": bool(tokens), "vault": self.kind, "durable": self.durable, "encrypted": self.encrypted,
            "has_refresh_token": bool(tokens and tokens.refresh_token),
            "scopes": list(tokens.scopes) if tokens else [],
        }


class UnavailableTokenVault(TokenVault):
    """Production default until the encrypted vault (T-552) exists: refuses to store."""

    kind = "unavailable"

    def put(self, workspace, provider, tokens):
        raise OAuthError("vault_unavailable")

    def get(self, workspace, provider):
        return None

    def delete(self, workspace, provider):
        return False


class MemoryTokenVault(TokenVault):
    """Test/dev only: process memory, not durable, not encrypted."""

    kind = "memory"

    def __init__(self):
        self._items = {}

    def put(self, workspace, provider, tokens):
        self._items[(workspace, provider)] = tokens

    def get(self, workspace, provider):
        return self._items.get((workspace, provider))

    def delete(self, workspace, provider):
        return self._items.pop((workspace, provider), None) is not None


# --- Adapters -----------------------------------------------------------------------

class OAuthAdapter:
    """Provider transport. Real adapters (T-552) do the HTTP calls and read the client secret."""

    def exchange_code(self, spec: OAuthProvider, code: str, redirect_uri: str, code_verifier: str) -> TokenSet:
        raise NotImplementedError

    def revoke(self, spec: OAuthProvider, tokens: TokenSet) -> bool:
        raise NotImplementedError


class MockOAuthAdapter(OAuthAdapter):
    """Deterministic, offline adapter for tests. Tokens derive from the code."""

    def __init__(self, fail_exchange: bool = False, fail_revoke: bool = False):
        self.fail_exchange = fail_exchange
        self.fail_revoke = fail_revoke
        self.calls = []

    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        self.calls.append(("exchange", spec.id, redirect_uri, bool(code_verifier)))
        if self.fail_exchange:
            raise RuntimeError(f"mock exchange failure for code {code}")
        seed = hashlib.sha256(f"{spec.id}:{code}".encode()).hexdigest()
        return TokenSet(access_token="mock-at-" + seed[:32], refresh_token="mock-rt-" + seed[32:],
                        expires_in=3600, scopes=spec.scopes, account_id="mock-" + seed[:10],
                        account_label=f"Mock {spec.label} account")

    def revoke(self, spec, tokens):
        self.calls.append(("revoke", spec.id))
        if self.fail_revoke:
            raise RuntimeError("mock revoke failure " + tokens.access_token)
        return True


# --- State + flow -------------------------------------------------------------------

class StateStore:
    """Server-side, single-use pending authorizations (in-process; lost on restart)."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self._clock = clock
        self._items = {}

    def issue(self, record: dict) -> str:
        now = self._clock()
        self._items = {k: v for k, v in self._items.items() if v["expires_at"] > now}
        while len(self._items) >= MAX_PENDING_STATES:
            self._items.pop(min(self._items, key=lambda k: self._items[k]["expires_at"]))
        state = secrets.token_urlsafe(32)
        self._items[state] = {**record, "expires_at": now + STATE_TTL_SECONDS}
        return state

    def consume(self, state: str) -> dict:
        record = self._items.pop(str(state or ""), None)
        if record is None:
            raise OAuthError("state_invalid")
        if record["expires_at"] <= self._clock():
            raise OAuthError("state_expired")
        return record

    def pending(self) -> int:
        return len(self._items)


class OAuthFlow:
    def __init__(self, redirect_base: str, client_id_lookup: Callable[[OAuthProvider], str],
                 vault: TokenVault, adapters: dict | None = None, state_store: StateStore | None = None):
        self.redirect_base = redirect_base.rstrip("/")
        self.client_id_lookup = client_id_lookup
        self.vault = vault
        self.adapters = dict(adapters or {})
        self.states = state_store or StateStore()

    def redirect_uri(self, spec: OAuthProvider) -> str:
        return f"{self.redirect_base}/api/oauth/{spec.id}/callback"

    def blockers(self, spec: OAuthProvider) -> list:
        out = []
        if not (self.client_id_lookup(spec) or "").strip():
            out.append("client_not_configured")
        adapter = self.adapters.get(spec.id)
        if adapter is None:
            out.append("adapter_missing")
        elif hasattr(adapter, "ready") and not out and not adapter.ready(spec):
            # Real adapters (T-552) also need the client secret; report it instead of failing at exchange.
            out.append("client_secret_missing")
        if isinstance(self.vault, UnavailableTokenVault):
            out.append("vault_unavailable")
        return out

    def public_registry(self) -> list:
        return [{
            "id": spec.id, "label": spec.label, "integration": spec.integration,
            "pkce": spec.pkce, "scopes": list(spec.scopes), "redirect_uri": self.redirect_uri(spec),
            "client_id_env": spec.client_id_env, "client_secret_env": spec.client_secret_env,
            "client_configured": not ("client_not_configured" in self.blockers(spec)),
            "ready": not self.blockers(spec), "blockers": self.blockers(spec),
            "vault": self.vault.kind, "secrets_exposed": False,
        } for spec in PROVIDERS.values()]

    def start(self, provider_id: str, workspace: str, subject: str) -> dict:
        spec = get_provider(provider_id)
        blockers = self.blockers(spec)
        if blockers:
            raise OAuthError(blockers[0])
        verifier = pkce_verifier() if spec.pkce else ""
        state = self.states.issue({"provider": spec.id, "workspace": workspace, "subject": subject,
                                   "verifier": verifier, "redirect_uri": self.redirect_uri(spec)})
        params = [(spec.client_id_param, self.client_id_lookup(spec).strip()),
                  ("redirect_uri", self.redirect_uri(spec)), ("response_type", "code"),
                  ("scope", spec.scope_separator.join(spec.scopes)), ("state", state)]
        if spec.pkce:
            params += [("code_challenge", pkce_challenge(verifier)), ("code_challenge_method", "S256")]
        params += list(spec.extra_params)
        log.info("oauth authorize started provider=%s workspace=%s", spec.id, workspace)
        return {"provider": spec.id, "authorize_url": spec.authorize_url + "?" + urlencode(params),
                "pkce": spec.pkce, "expires_in": STATE_TTL_SECONDS}

    def complete(self, provider_id: str, params: dict, subject: str) -> dict:
        """Validate the callback, exchange the code and store tokens. Returns a public
        result (no tokens). Raises OAuthError with a fixed code on any failure."""
        spec = get_provider(provider_id)
        state = str(params.get("state") or "")
        if not state:
            raise OAuthError("state_missing")
        record = self.states.consume(state)  # single use, even when the callback fails below
        if record["provider"] != spec.id:
            raise OAuthError("state_provider_mismatch")
        if record["subject"] != subject:
            raise OAuthError("state_subject_mismatch")
        if params.get("error"):
            raise OAuthError("provider_denied" if params.get("error") == "access_denied" else "provider_error")
        code = str(params.get("code") or "")
        if not code:
            raise OAuthError("code_missing")
        adapter = self.adapters.get(spec.id)
        if adapter is None:
            raise OAuthError("adapter_missing")
        try:
            tokens = adapter.exchange_code(spec, code, record["redirect_uri"], record["verifier"])
        except OAuthError:
            raise
        except Exception:
            log.warning("oauth code exchange failed provider=%s", spec.id)
            raise OAuthError("exchange_failed")
        if not isinstance(tokens, TokenSet) or not tokens.access_token:
            raise OAuthError("exchange_failed")
        self.vault.put(record["workspace"], spec.id, tokens)
        log.info("oauth connected provider=%s workspace=%s", spec.id, record["workspace"])
        return {"ok": True, "provider": spec.id, "integration": spec.integration,
                "workspace": record["workspace"], "account_id": tokens.account_id[:180],
                "account_label": tokens.account_label[:180], "scopes": list(tokens.scopes),
                "token_storage": self.vault.status(record["workspace"], spec.id)}

    def disconnect(self, provider_id: str, workspace: str) -> dict:
        """Best-effort provider revoke, then always forget local tokens. Never touches
        FactoryOS content history."""
        spec = get_provider(provider_id)
        tokens = self.vault.get(workspace, spec.id)
        revoke = "no_tokens"
        if tokens:
            adapter = self.adapters.get(spec.id)
            if adapter is None:
                revoke = "adapter_missing"
            else:
                try:
                    revoke = "revoked" if adapter.revoke(spec, tokens) else "revoke_failed"
                except Exception:
                    log.warning("oauth revoke failed provider=%s", spec.id)
                    revoke = "revoke_failed"
        deleted = self.vault.delete(workspace, spec.id)
        log.info("oauth disconnected provider=%s workspace=%s revoke=%s", spec.id, workspace, revoke)
        return {"ok": True, "provider": spec.id, "integration": spec.integration, "revoke": revoke,
                "tokens_deleted": deleted, "history_preserved": True}
