"""T-700 LinkedIn text posts: OAuth adapter, escaping, approval fence, uncertain outcomes, owner-only routes.
Offline: fake HTTP, in-memory vault, handlers called directly (no TestClient: CI has no httpx)."""
import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-linkedin-"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import linkedin_publisher as lp  # noqa: E402
from oauth_framework import MemoryTokenVault, OAuthError, OAuthFlow, TokenSet, get_provider  # noqa: E402

ENV = {"FACTORY_OAUTH_LINKEDIN_CLIENT_ID": "cid", "FACTORY_OAUTH_LINKEDIN_CLIENT_SECRET": "csecret"}


class FakeHttp:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, hdrs, payload = answer
        return status, hdrs, json.dumps(payload).encode() if isinstance(payload, dict) else (payload or b"")


class AdapterTest(unittest.TestCase):
    def test_exchange_stores_member_urn_and_never_returns_tokens_in_errors(self):
        spec = get_provider("linkedin")
        http = FakeHttp((200, {}, {"access_token": "AT", "expires_in": 5184000, "scope": "openid,profile,w_member_social"}),
                        (200, {}, {"sub": "abc_123", "name": "Andrii P"}))
        with mock.patch.dict(os.environ, ENV):
            tokens = lp.LinkedInOAuthAdapter(http).exchange_code(spec, "CODE", "https://x/cb", "")
        self.assertEqual((tokens.account_id, tokens.account_label), ("urn:li:person:abc_123", "Andrii P"))
        self.assertEqual(tokens.scopes, ("openid", "profile", "w_member_social"))
        form = http.calls[0][3].decode()
        self.assertIn("grant_type=authorization_code", form)
        self.assertIn("client_secret=csecret", form)
        self.assertEqual(http.calls[1][2]["Authorization"], "Bearer AT")
        bad = FakeHttp((400, {}, {"error": "invalid_grant", "error_description": "code AT leaked"}))
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            lp.LinkedInOAuthAdapter(bad).exchange_code(spec, "CODE", "https://x/cb", "")
        self.assertEqual(str(err.exception.code), "exchange_failed")
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(OAuthError):
            lp.LinkedInOAuthAdapter(FakeHttp()).exchange_code(spec, "CODE", "https://x/cb", "")

    def test_member_without_sub_is_refused(self):
        http = FakeHttp((200, {}, {"access_token": "AT"}), (200, {}, {"name": "x"}))
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            lp.LinkedInOAuthAdapter(http).exchange_code(get_provider("linkedin"), "C", "https://x/cb", "")
        self.assertEqual(err.exception.code, "linkedin_member_missing")


class PostTest(unittest.TestCase):
    def test_create_post_shape_escaping_and_receipt(self):
        http = FakeHttp((201, {"x-restli-id": "urn:li:share:7123"}, b""))
        out = lp.create_post(http, "AT", "urn:li:person:abc", "Hi (team) #ai @x_y", "202510")
        self.assertEqual(out["post_urn"], "urn:li:share:7123")
        self.assertEqual(out["url"], "https://www.linkedin.com/feed/update/urn:li:share:7123")
        method, url, headers, body = http.calls[0]
        self.assertEqual((method, url), ("POST", lp.POSTS_URL))
        self.assertEqual(headers["LinkedIn-Version"], "202510")
        self.assertEqual(headers["X-Restli-Protocol-Version"], "2.0.0")
        sent = json.loads(body)
        self.assertEqual(sent["commentary"], r"Hi \(team\) \#ai \@x\_y")
        self.assertEqual((sent["author"], sent["visibility"], sent["lifecycleState"]),
                         ("urn:li:person:abc", "PUBLIC", "PUBLISHED"))

    def test_errors_map_to_fixed_codes_and_uncertainty(self):
        cases = [((401, {}, b"AT"), "linkedin_auth_failed", False), ((403, {}, b""), "linkedin_permission_denied", False),
                 ((426, {}, b""), "linkedin_version_unsupported", False), ((429, {}, b""), "linkedin_rate_limited", False),
                 ((503, {}, b""), "linkedin_rejected_503", True), ((201, {}, b""), "linkedin_created_without_id", True),
                 (TimeoutError(), "linkedin_outcome_uncertain", True)]
        for answer, code, uncertain in cases:
            with self.assertRaises(lp.LinkedInError, msg=code) as err:
                lp.create_post(FakeHttp(answer), "AT", "urn:li:person:abc", "hi", "202510")
            self.assertEqual((err.exception.code, err.exception.uncertain), (code, uncertain))
            self.assertNotIn("AT", err.exception.code)
        with self.assertRaises(lp.LinkedInError):
            lp.create_post(FakeHttp(), "AT", "not-a-urn", "hi", "202510")

    def test_flag_and_version_settings(self):
        self.assertFalse(lp.enabled({}))
        self.assertTrue(lp.enabled({"FACTORY_LINKEDIN_ENABLED": "1"}))
        self.assertEqual(lp.api_version({"FACTORY_LINKEDIN_API_VERSION": "202601"}), "202601")
        self.assertEqual(lp.api_version({"FACTORY_LINKEDIN_API_VERSION": "../x"}), lp.DEFAULT_API_VERSION)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = lp.PostStore(pathlib.Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_approval_fence_edit_and_states(self):
        d = self.store.create("  Hello\r\nworld\x00 ")
        self.assertEqual(d["text"], "Hello\nworld")
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # not approved
        self.store.approve(d["id"])
        self.store.edit(d["id"], "Changed")                        # an edit drops the approval
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])
        self.store.approve(d["id"])
        self.assertEqual(self.store.claim_for_publish(d["id"])["status"], "publishing")
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # second click while publishing
        self.store.finish(d["id"], "uncertain", {"code": "linkedin_outcome_uncertain"})
        for call in (lambda: self.store.claim_for_publish(d["id"]), lambda: self.store.delete(d["id"]),
                     lambda: self.store.edit(d["id"], "x")):
            with self.assertRaises(HTTPException):
                call()
        with self.assertRaises(HTTPException):
            self.store.confirm(d["id"], "https://evil.example/x")
        self.assertEqual(self.store.confirm(d["id"], "https://www.linkedin.com/feed/update/urn:li:share:1")["status"],
                         "published")
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # never twice

    def test_text_limits_and_unknown_ids(self):
        for bad in ("", "  ", "x" * 3001):
            with self.assertRaises(HTTPException):
                self.store.create(bad)
        with self.assertRaises(HTTPException):
            self.store.approve("../etc")


def call(endpoint, *args, role="owner", body=None):
    raw = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    request = Request({"type": "http", "method": "POST", "headers": [(b"x-role", role.encode())], "path": "/",
                       "query_string": b""}, receive)
    result = endpoint(*args, request)
    return asyncio.run(result) if asyncio.iscoroutine(result) else result


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = MemoryTokenVault()
        self.http = FakeHttp()
        self.flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), self.vault,
                              adapters={"linkedin": lp.LinkedInOAuthAdapter(self.http)})
        self.env = {"FACTORY_LINKEDIN_ENABLED": "1"}
        app = FastAPI()
        lp.install_routes(app, store=lp.PostStore(pathlib.Path(self.tmp.name)), flow=self.flow,
                          identity=lambda r: {"role": r.headers.get("x-role")}, workspace=lambda: "default",
                          env=self.env)
        self.ep = {getattr(r, "path", ""): r.endpoint for r in app.routes}
        self.patch = mock.patch.dict(os.environ, ENV)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def route(self, path, *args, **kw):
        return call(self.ep[path], *args, **kw)

    def test_owner_only_and_not_ready_without_connection_or_flag(self):
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/linkedin", role="member")
        self.assertEqual(err.exception.status_code, 403)
        state = self.route("/api/factory/linkedin")
        self.assertIn("linkedin_not_connected", state["blockers"])
        self.vault.put("default", "linkedin", TokenSet(access_token="AT", account_id="urn:li:person:abc"))
        self.env["FACTORY_LINKEDIN_ENABLED"] = "0"
        self.assertEqual(self.route("/api/factory/linkedin")["blockers"], ["linkedin_publishing_off"])
        d = self.route("/api/factory/linkedin/drafts", body={"text": "hello"})["draft"]
        self.route("/api/factory/linkedin/drafts/{draft_id}/approve", d["id"])
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/linkedin/drafts/{draft_id}/publish", d["id"])
        self.assertIn("linkedin_publishing_off", err.exception.detail)
        self.assertEqual(self.http.calls, [])                      # nothing left FactoryOS

    def test_publish_once_and_uncertain_is_not_retried(self):
        self.vault.put("default", "linkedin", TokenSet(access_token="AT", account_id="urn:li:person:abc"))
        d = self.route("/api/factory/linkedin/drafts", body={"text": "post one"})["draft"]
        self.route("/api/factory/linkedin/drafts/{draft_id}/approve", d["id"])
        self.http.answers.append((201, {"x-restli-id": "urn:li:share:99"}, b""))
        out = self.route("/api/factory/linkedin/drafts/{draft_id}/publish", d["id"])["draft"]
        self.assertEqual((out["status"], out["result"]["post_urn"]), ("published", "urn:li:share:99"))
        with self.assertRaises(HTTPException):
            self.route("/api/factory/linkedin/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(len(self.http.calls), 1)
        d2 = self.route("/api/factory/linkedin/drafts", body={"text": "post two"})["draft"]
        self.route("/api/factory/linkedin/drafts/{draft_id}/approve", d2["id"])
        self.http.answers.append(TimeoutError())
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/linkedin/drafts/{draft_id}/publish", d2["id"])
        self.assertEqual(err.exception.detail, "linkedin_outcome_uncertain")
        with self.assertRaises(HTTPException):
            self.route("/api/factory/linkedin/drafts/{draft_id}/publish", d2["id"])
        self.assertEqual(len(self.http.calls), 2)                 # no blind retry
        state = self.route("/api/factory/linkedin")
        self.assertNotIn("AT", json.dumps(state))


if __name__ == "__main__":
    unittest.main()
