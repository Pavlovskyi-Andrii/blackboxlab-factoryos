"""T-551-A OAuth framework scaffold regression. Run: python test_oauth_framework.py

Zero secrets, zero network, $0.00. Checks provider selection, state validation (single use,
expiry, provider/subject binding), PKCE (S256 recomputed independently, sent in the authorize URL only
where supported), callback error handling, the token-vault interface, the revoke/disconnect contract,
auth boundaries, and that no token or client secret reaches responses, redirects, events or logs.
"""
import asyncio
import base64
import hashlib
import json
import logging
import os
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-oauth-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory
import oauth_framework as oauth

SECRET_SENTINEL = "t551a-client-secret-must-never-appear"
FAKE_CLIENT_IDS = {spec.client_id_env: f"t551a-client-{spec.id}" for spec in oauth.PROVIDERS.values()}
FAKE_SECRETS = {spec.client_secret_env: SECRET_SENTINEL for spec in oauth.PROVIDERS.values()}

outbound = []
issued_tokens = []
seen_text = []


class Capture(logging.Handler):
    def emit(self, record):
        seen_text.append(record.getMessage())


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def no_network(*args, **kwargs):
    outbound.append(args[0] if args else kwargs)
    raise AssertionError("T-551-A must not make outbound calls")


def call(method, path, query="", cookie=""):
    headers = [(b"host", b"testserver")]
    if cookie:
        headers.append((b"cookie", cookie.encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": query.encode(), "headers": headers,
             "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    hdrs = {k.decode().lower(): v.decode() for k, v in start.get("headers", [])}
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    seen_text.extend([body, hdrs.get("location", "")])
    return start["status"], hdrs, body


class TrackingMock(oauth.MockOAuthAdapter):
    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        self.last_verifier = code_verifier
        tokens = super().exchange_code(spec, code, redirect_uri, code_verifier)
        issued_tokens.extend(tokens.secret_values())
        return tokens


def authorize(provider, cookie=""):
    status, _, body = call("POST", f"/api/oauth/{provider}/authorize", cookie=cookie)
    require(status == 200, f"{provider} authorize must succeed with mocks, got {status}: {body[:200]}")
    data = json.loads(body)
    url = urlsplit(data["authorize_url"])
    return data, url, {k: v[0] for k, v in parse_qs(url.query).items()}


def callback(provider, query, cookie=""):
    status, hdrs, _ = call("GET", f"/api/oauth/{provider}/callback", query, cookie=cookie)
    require(status == 303, f"{provider} callback must redirect, got {status}")
    loc = hdrs["location"]
    return {k: v[0] for k, v in parse_qs(urlsplit(loc).query).items()}, loc


def check_registry_and_pkce():
    require(list(oauth.PROVIDERS) == ["youtube", "tiktok", "instagram", "google_sheets", "linkedin", "olx", "hubspot"], "provider set")
    for spec in oauth.PROVIDERS.values():
        require(spec.integration in factory.PORTABLE_INTEGRATIONS, f"{spec.id} maps to a portable integration slot")
        require(oauth.get_provider(spec.id.upper()) is spec, "provider selection is case-insensitive")
    require({s.id for s in oauth.PROVIDERS.values() if s.pkce} == {"youtube", "google_sheets"}, "PKCE only where supported")
    for bad in ("", "facebook", "../youtube", None):
        try:
            oauth.get_provider(bad)
            raise AssertionError(f"unknown provider {bad!r} accepted")
        except oauth.OAuthError as e:
            require(e.code == "unknown_provider", "unknown provider code")
    # S256 = BASE64URL-without-padding(SHA256(ASCII(verifier))), computed independently here.
    fixed = "t551a-" + "v" * 40
    expected = base64.urlsafe_b64encode(hashlib.sha256(fixed.encode("ascii")).digest()).rstrip(b"=").decode()
    challenge = oauth.pkce_challenge(fixed)
    require(challenge == expected and len(challenge) == 43 and "=" not in challenge, "PKCE S256 per RFC 7636")
    v = oauth.pkce_verifier()
    require(43 <= len(v) <= 128 and v != oauth.pkce_verifier(), "verifier length and randomness")
    for bad in ("short", "x" * 129):
        try:
            oauth.pkce_challenge(bad)
            raise AssertionError("invalid verifier accepted")
        except oauth.OAuthError as e:
            require(e.code == "pkce_verifier_invalid", "verifier length enforced")
    print("OK provider registry, selection and PKCE S256")


def check_production_default_is_fenced():
    with patch.dict(os.environ, FAKE_SECRETS):
        status, _, body = call("GET", "/api/oauth/providers")
        require(status == 200 and SECRET_SENTINEL not in body, "registry must not expose secrets")
        providers = json.loads(body)["providers"]
        for p in providers:
            # T-552-YT / T-700 / T-701 / T-725: YouTube, LinkedIn, OLX and Google Sheets ship real adapters; the rest have none.
            expected = {"client_not_configured", "vault_unavailable"} | (set() if p["id"] in ("youtube", "linkedin", "olx", "google_sheets") else {"adapter_missing"})
            require(not p["ready"] and set(p["blockers"]) == expected, f"{p['id']} blockers")
            require(p["redirect_uri"] == f"{factory.FACTORY_PUBLIC_BASE_URL}/api/oauth/{p['id']}/callback", "redirect")
            status, _, body = call("POST", f"/api/oauth/{p['id']}/authorize")
            require(status == 409 and json.loads(body)["reason"] == "client_not_configured", "authorize refused")
    status, _, _ = call("POST", "/api/oauth/myspace/authorize")
    require(status == 404, "unknown provider authorize must 404")
    status, _, _ = call("GET", "/api/oauth/myspace/callback", "state=x&code=y")
    require(status == 404, "unknown provider callback must 404")
    vault = oauth.UnavailableTokenVault()
    try:
        vault.put("default", "youtube", oauth.TokenSet(access_token="x"))
        raise AssertionError("unavailable vault stored a token")
    except oauth.OAuthError as e:
        require(e.code == "vault_unavailable", "vault refusal code")
    require(vault.status("default", "youtube")["stored"] is False, "unavailable vault status")
    with patch.dict(os.environ, FAKE_CLIENT_IDS):
        status, _, body = call("POST", "/api/oauth/hubspot/authorize")
        require(status == 409 and json.loads(body)["reason"] == "adapter_missing",
                "a client id alone must not enable OAuth without adapter + vault (T-552)")
    print("OK production default: every provider blocked, nothing stored, unknown providers 404")


def check_mock_flows(mocks):
    for pid in ("youtube", "tiktok", "instagram", "hubspot"):
        spec = oauth.PROVIDERS[pid]
        data, url, q = authorize(pid)
        require(f"{url.scheme}://{url.netloc}{url.path}" == spec.authorize_url, f"{pid} authorize endpoint")
        require(q[spec.client_id_param] == FAKE_CLIENT_IDS[spec.client_id_env], f"{pid} client id param")
        require(q["redirect_uri"] == factory.OAUTH_FLOW.redirect_uri(spec) and q["response_type"] == "code", pid)
        require(q["scope"] == spec.scope_separator.join(spec.scopes), f"{pid} scopes")
        require(SECRET_SENTINEL not in data["authorize_url"], "client secret never in the authorize URL")
        if spec.pkce:
            verifier = factory.OAUTH_FLOW.states._items[q["state"]]["verifier"]
            require(q["code_challenge_method"] == "S256" and q["code_challenge"] == oauth.pkce_challenge(verifier),
                    f"{pid} PKCE challenge")
            require(verifier not in data["authorize_url"], "verifier stays server-side")
        else:
            require("code_challenge" not in q, f"{pid} must not send PKCE")
        result, loc = callback(pid, f"state={q['state']}&code=auth-code-{pid}")
        require(result == {"oauth": pid, "result": "connected"}, f"{pid} connected redirect: {loc}")
        require(mocks[pid].last_verifier == (verifier if spec.pkce else ""), f"{pid} verifier passed to exchange")
        stored = factory.OAUTH_FLOW.vault.get("default", pid)
        require(stored and stored.access_token.startswith("mock-at-"), f"{pid} tokens in vault")
        require("mock-at-" not in repr(stored) and "mock-rt-" not in repr(stored), "TokenSet repr is redacted")
        row = factory._integration_row(spec.integration)
        require(row["state"] == "connected" and row["auth_mode"] == "oauth", f"{pid} binding recorded")
        require(not any(t in json.dumps(row) for t in stored.secret_values()), "binding row has no tokens")
        result, _ = callback(pid, f"state={q['state']}&code=again")
        require(result.get("reason") == "state_invalid", f"{pid} state must be single use")
    status, _, body = call("GET", "/api/oauth/providers")
    require(all(p["ready"] for p in json.loads(body)["providers"]), "all mocked providers ready")
    for path in ("/api/integrations", "/api/status"):
        status, _, _ = call("GET", path)
        require(status == 200, path)
    print("OK authorize/callback contract for YouTube, TikTok, Instagram, HubSpot with mocked adapters")


def check_state_and_callback_errors(mocks):
    _, _, q1 = authorize("youtube")
    _, _, q2 = authorize("youtube")
    require(q1["state"] != q2["state"], "two authorize calls yield different state values")

    cases = [
        ("tiktok", f"state={q1['state']}&code=c", "state_provider_mismatch"),
        ("youtube", f"state={q1['state']}&code=c", "state_invalid"),  # burned by the mismatch above (repeated state)
        ("youtube", "code=c", "state_missing"),
        ("youtube", "state=&code=c", "state_missing"),
        ("youtube", "state=forged-state&code=c", "state_invalid"),
    ]
    _, _, q2 = authorize("youtube")
    cases.append(("youtube", f"state={q2['state']}&error=access_denied", "provider_denied"))
    _, _, q3 = authorize("instagram")
    cases.append(("instagram", f"state={q3['state']}&error=server_error&error_description=%3Cscript%3Eboom%3C%2Fscript%3E",
                  "provider_error"))
    _, _, q4 = authorize("hubspot")
    cases.append(("hubspot", f"state={q4['state']}", "code_missing"))
    for pid, query, reason in cases:
        result, loc = callback(pid, query)
        require(result == {"oauth": pid, "result": "error", "reason": reason}, f"{pid} {query[:30]}: {loc}")
        require("script" not in loc and "boom" not in loc, "provider error text is never reflected")
    mocks["tiktok"].fail_exchange = True
    _, _, q5 = authorize("tiktok")
    result, _ = callback("tiktok", f"state={q5['state']}&code=leaky-code-t551a")
    require(result["reason"] == "exchange_failed", "exchange failure maps to a fixed code")
    mocks["tiktok"].fail_exchange = False
    require(not any("leaky-code-t551a" in t for t in seen_text), "auth code never logged or returned")

    clock = [1000.0]
    flow = oauth.OAuthFlow("https://factory.example", lambda s: "cid", oauth.MemoryTokenVault(),
                           {"youtube": oauth.MockOAuthAdapter()}, oauth.StateStore(clock=lambda: clock[0]))
    st = parse_qs(urlsplit(flow.start("youtube", "default", "owner|a")["authorize_url"]).query)["state"][0]
    clock[0] += oauth.STATE_TTL_SECONDS + 1
    expect_code(lambda: flow.complete("youtube", {"state": st, "code": "c"}, "owner|a"), "state_expired")
    st = parse_qs(urlsplit(flow.start("youtube", "default", "owner|a")["authorize_url"]).query)["state"][0]
    expect_code(lambda: flow.complete("youtube", {"state": st, "code": "c"}, "owner|b"), "state_subject_mismatch")
    expect_code(lambda: flow.complete("youtube", {"state": st, "code": "c"}, "owner|a"), "state_invalid")
    expect_code(lambda: flow.complete("youtube", {"state": "", "code": "c"}, "owner|a"), "state_missing")
    expect_code(lambda: flow.complete("youtube", {"state": "foreign-state", "code": "c"}, "owner|a"), "state_invalid")
    for _ in range(oauth.MAX_PENDING_STATES + 25):
        flow.start("youtube", "default", "owner|a")
    require(flow.states.pending() <= oauth.MAX_PENDING_STATES, "pending state store is bounded")
    print("OK state validation (single use, expiry, provider/subject binding) and callback error handling")


def expect_code(fn, code):
    try:
        fn()
        raise AssertionError(f"expected {code}")
    except oauth.OAuthError as e:
        require(e.code == code, f"expected {code}, got {e.code}")


def check_disconnect(mocks):
    con = factory.db()
    before = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    status, _, body = call("POST", "/api/oauth/youtube/disconnect")
    data = json.loads(body)
    require(status == 200 and data["revoke"] == "revoked" and data["tokens_deleted"], f"revoke: {body[:200]}")
    require(("revoke", "youtube") in mocks["youtube"].calls, "adapter revoke called")
    require(factory.OAUTH_FLOW.vault.get("default", "youtube") is None, "tokens removed")
    require(factory._integration_row("YouTube")["state"] == "disconnected" and data["history_preserved"], "binding")
    mocks["hubspot"].fail_revoke = True
    status, _, body = call("POST", "/api/oauth/hubspot/disconnect")
    data = json.loads(body)
    require(data["revoke"] == "revoke_failed" and data["tokens_deleted"], "failed revoke still forgets tokens")
    status, _, body = call("POST", "/api/oauth/youtube/disconnect")
    require(json.loads(body)["revoke"] == "no_tokens", "disconnect without tokens is safe")
    status, _, _ = call("POST", "/api/oauth/myspace/disconnect")
    require(status == 404, "unknown provider disconnect 404")
    con = factory.db()
    after = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    con.close()
    require(after > before, "disconnect never deletes history")
    print("OK revoke/disconnect contract: best-effort revoke, tokens always forgotten, history kept")


def check_auth_boundaries():
    with patch.object(factory, "FACTORY_PASSWORD", "t551a-owner-pass"):
        for method, path in (("GET", "/api/oauth/providers"), ("POST", "/api/oauth/youtube/authorize"),
                             ("GET", "/api/oauth/youtube/callback"), ("POST", "/api/oauth/youtube/disconnect")):
            require(call(method, path)[0] == 401, f"{method} {path} must require a session")
        viewer = f"{factory.COOKIE_NAME}={factory._role_session_token('viewer', 'guest')}"
        owner = f"{factory.COOKIE_NAME}={factory.session_token(factory.FACTORY_USER)}"
        google_owner = f"{factory.COOKIE_NAME}={factory._role_session_token('owner', 'other@example.com')}"
        require(call("GET", "/api/oauth/providers", cookie=viewer)[0] == 200, "viewer may read the registry")
        for path in ("/api/oauth/youtube/authorize", "/api/oauth/youtube/disconnect"):
            require(call("POST", path, cookie=viewer)[0] == 403, f"viewer cannot write {path}")
        _, _, q = authorize("youtube", cookie=owner)
        status, _, _ = call("GET", "/api/oauth/youtube/callback", f"state={q['state']}&code=c", cookie=viewer)
        require(status == 403, "viewer cannot complete a callback")
        result, _ = callback("youtube", f"state={q['state']}&code=c", cookie=google_owner)
        require(result["reason"] == "state_subject_mismatch", "state is bound to the initiating session")
        _, _, q = authorize("youtube", cookie=owner)
        result, _ = callback("youtube", f"state={q['state']}&code=c", cookie=owner)
        require(result["result"] == "connected", "owner session completes its own flow")
    print("OK session auth: 401 without session, viewer read-only, callback bound to initiating owner")


def check_no_leakage():
    con = factory.db()
    seen_text.extend(r[0] for r in con.execute("SELECT message FROM events").fetchall())
    seen_text.extend(r[0] or "" for r in con.execute("SELECT meta_json FROM integration_accounts").fetchall())
    con.close()
    require(issued_tokens, "fixture issued tokens")
    blob = "\n".join(seen_text)
    for token in issued_tokens + [SECRET_SENTINEL]:
        require(token not in blob, "token/secret leaked to UI, redirect, events or logs")
    require(oauth.redact(f"x {issued_tokens[0]} y", issued_tokens) == "x [redacted] y", "redact helper")
    require(not outbound, f"outbound calls attempted: {outbound}")
    print("OK no token, auth code or client secret in responses, redirects, events, bindings or logs")


def main():
    handler = Capture()
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.DEBUG)
    with patch.object(factory.urlrequest, "urlopen", no_network):
        check_registry_and_pkce()
        check_production_default_is_fenced()
        mocks = {pid: TrackingMock() for pid in oauth.PROVIDERS}
        with patch.dict(os.environ, {**FAKE_CLIENT_IDS, **FAKE_SECRETS}), \
                patch.object(factory.OAUTH_FLOW, "adapters", mocks), \
                patch.object(factory.OAUTH_FLOW, "vault", oauth.MemoryTokenVault()):
            check_mock_flows(mocks)
            check_state_and_callback_errors(mocks)
            check_disconnect(mocks)
            check_auth_boundaries()
        require(isinstance(factory.OAUTH_FLOW.vault, oauth.UnavailableTokenVault)
                and set(factory.OAUTH_FLOW.adapters) == {"youtube", "linkedin", "olx", "google_sheets"},
                "production defaults restored (only the real YouTube, LinkedIn, OLX and Google Sheets adapters are registered)")
        check_no_leakage()
    logging.getLogger().removeHandler(handler)
    print("T-551-A OAuth framework scaffold: PASS (zero secrets, zero network)")


if __name__ == "__main__":
    main()
