"""T-701 OLX adverts: OAuth adapter, validation, approval fence, uncertain outcomes, reconcile, owner-only routes.
Offline: fake HTTP, in-memory vault, handlers called directly (no TestClient: CI has no httpx)."""
import asyncio
import json
import os
import pathlib
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-olx-"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import olx_publisher as op  # noqa: E402
from oauth_framework import MemoryTokenVault, OAuthError, OAuthFlow, TokenSet, get_provider  # noqa: E402

ENV = {"FACTORY_OAUTH_OLX_CLIENT_ID": "cid", "FACTORY_OAUTH_OLX_CLIENT_SECRET": "csecret"}
ADVERT = {"title": "Ноутбук Lenovo ThinkPad T14 у гарному стані",
          "description": "Продаю ноутбук Lenovo ThinkPad T14, 16 ГБ пам'яті, SSD 512 ГБ. Батарея тримає шість годин, "
                         "подряпин немає, повний комплект із зарядним пристроєм.",
          "category_id": "1234", "advertiser_type": "private",
          "contact": {"name": "Андрій", "phone": "+380 67 123 45 67"},
          "location": {"city_id": 268, "district_id": ""},
          "images": ["https://cdn.example.com/a.jpg", {"url": "https://cdn.example.com/b.jpg"}],
          "price": {"value": "15000", "negotiable": True},
          "attributes": [{"code": "state", "value": "used"}]}


class FakeHttp:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        answer = self.answers.pop(0)
        if callable(answer) and not isinstance(answer, Exception):
            answer = answer()                                     # side effect while the request is in flight
        if isinstance(answer, Exception):
            raise answer
        status, payload = answer
        return status, {}, json.dumps(payload).encode() if isinstance(payload, (dict, list)) else (payload or b"")


class AdapterTest(unittest.TestCase):
    def test_provider_matches_olx_docs(self):
        spec = get_provider("olx")
        self.assertEqual(spec.authorize_url, "https://www.olx.ua/oauth/authorize/")
        self.assertEqual(spec.token_url, "https://www.olx.ua/api/open/oauth/token")
        self.assertEqual(" ".join(spec.scopes), "read write v2")
        self.assertEqual((spec.client_id_env, spec.client_secret_env),
                         ("FACTORY_OAUTH_OLX_CLIENT_ID", "FACTORY_OAUTH_OLX_CLIENT_SECRET"))

    def test_exchange_reads_user_and_never_leaks_tokens(self):
        spec = get_provider("olx")
        http = FakeHttp((200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 86400,
                               "token_type": "bearer", "scope": "v2 read write"}),
                        (200, {"data": {"id": 777, "name": "Andrii", "email": "a@example.com"}}))
        with mock.patch.dict(os.environ, ENV):
            tokens = op.OlxOAuthAdapter(http).exchange_code(spec, "CODE", "https://x/api/oauth/olx/callback", "")
        self.assertEqual((tokens.account_id, tokens.account_label, tokens.refresh_token),
                         ("olx:user:777", "Andrii", "RT"))
        self.assertEqual(http.calls[0][2]["Content-Type"], "application/x-www-form-urlencoded")
        sent = {k: v[0] for k, v in parse_qs(http.calls[0][3].decode()).items()}
        self.assertEqual(sent, {"grant_type": "authorization_code", "code": "CODE", "scope": "v2 read write",
                                "client_id": "cid", "client_secret": "csecret",
                                "redirect_uri": "https://x/api/oauth/olx/callback"})
        user = http.calls[1]
        self.assertEqual((user[0], user[1]), ("GET", "https://www.olx.ua/api/partner/users/me"))
        self.assertEqual((user[2]["Authorization"], user[2]["Version"]), ("Bearer AT", "2.0"))
        self.assertNotIn("Content-Type", user[2])                 # OLX FAQ: no Content-Type on GET
        bad = FakeHttp((400, {"error": "invalid_grant", "error_description": "code CODE AT"}))
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            op.OlxOAuthAdapter(bad).exchange_code(spec, "CODE", "https://x/cb", "")
        self.assertEqual(err.exception.code, "exchange_failed")
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(OAuthError):
            op.OlxOAuthAdapter(FakeHttp()).exchange_code(spec, "CODE", "https://x/cb", "")
        no_user = FakeHttp((200, {"access_token": "AT"}), (401, {}))
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            op.OlxOAuthAdapter(no_user).exchange_code(spec, "C", "https://x/cb", "")
        self.assertEqual(err.exception.code, "olx_user_missing")

    def test_refresh_keeps_account_and_rotates(self):
        spec = get_provider("olx")
        old = TokenSet(access_token="AT1", refresh_token="RT1", account_id="olx:user:1", account_label="A")
        http = FakeHttp((200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 86400}))
        with mock.patch.dict(os.environ, ENV):
            new = op.OlxOAuthAdapter(http).refresh(spec, old)
        self.assertEqual((new.access_token, new.refresh_token, new.account_id), ("AT2", "RT2", "olx:user:1"))
        self.assertEqual(http.calls[0][2]["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual({k: v[0] for k, v in parse_qs(http.calls[0][3].decode()).items()},
                         {"grant_type": "refresh_token", "refresh_token": "RT1", "client_id": "cid",
                          "client_secret": "csecret"})
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            op.OlxOAuthAdapter(FakeHttp((400, {"error": "invalid_grant"}))).refresh(spec, old)
        self.assertEqual(err.exception.code, "olx_reconnect_required")
        self.assertFalse(op.OlxOAuthAdapter(FakeHttp()).revoke(spec, old))    # no documented revoke endpoint


class ValidationTest(unittest.TestCase):
    def test_clean_advert_shape(self):
        adv = op.clean_advert(ADVERT)
        self.assertEqual(adv["category_id"], 1234)
        self.assertEqual(adv["location"], {"city_id": 268})
        self.assertEqual(adv["images"], [{"url": "https://cdn.example.com/a.jpg"}, {"url": "https://cdn.example.com/b.jpg"}])
        self.assertEqual(adv["price"], {"value": 15000, "currency": "UAH", "negotiable": True, "trade": False})
        self.assertEqual(adv["attributes"], [{"code": "state", "value": "used"}])

    def test_documented_rules_are_enforced_locally(self):
        cases = {"title": ["short", "x" * 71, "НОУТБУК LENOVO THINKPAD T14 СУПЕР", "Ноутбук Lenovo!!! дуже гарний",
                           "Пишіть на mail@example.com швидко", "Дзвоніть 0671234567 ноутбук"],
                 "description": ["коротко", "y" * 9001, ADVERT["description"] + " www.shop.ua"],
                 "category_id": [None, "abc", -1], "advertiser_type": ["company"],
                 "contact": [{}, {"name": "A", "phone": "call me"}], "location": [{}, {"city_id": 0}],
                 "images": [["http://insecure.example/a.jpg"], ["https://x/" + str(i) + ".jpg" for i in range(21)]],
                 "attributes": [[{"code": "bad code", "value": "x"}], [{"code": "state", "value": ""}]]}
        for field, values in cases.items():
            for value in values:
                with self.assertRaises(HTTPException, msg=f"{field}={value!r}"):
                    op.clean_advert({**ADVERT, field: value})
        with self.assertRaises(HTTPException):
            op.clean_advert("not a dict")


class ApiTest(unittest.TestCase):
    def test_create_advert_body_headers_and_receipt(self):
        http = FakeHttp((200, {"data": {"id": 9001, "status": "new", "url": "https://www.olx.ua/d/uk/obyavlenie/x.html",
                                        "valid_to": "2026-12-18 10:00:00", "contact": {"phone": "secret"}}}))
        adv = op.clean_advert(ADVERT)
        out = op.create_advert(http, "AT", adv, "olx_0123456789ab")
        self.assertEqual(out, {"advert_id": "9001", "olx_status": "new", "url": "https://www.olx.ua/d/uk/obyavlenie/x.html",
                               "valid_to": "2026-12-18 10:00:00"})
        method, url, headers, body = http.calls[0]
        self.assertEqual((method, url), ("POST", "https://www.olx.ua/api/partner/adverts"))
        self.assertEqual((headers["Version"], headers["Content-Type"], headers["Accept-Language"]),
                         ("2.0", "application/json", "uk"))
        self.assertEqual(json.loads(body), {**adv, "external_id": "olx_0123456789ab"})
        limited = op.create_advert(FakeHttp((200, {"id": 5, "status": "limited", "url": "https://evil.example/x"})),
                                   "AT", adv, "olx_0123456789ab")
        self.assertEqual((limited["note"], limited["url"]), ("olx_limited_needs_packet", ""))

    def test_errors_map_to_fixed_codes_and_uncertainty(self):
        invalid = {"error": {"status": 400, "title": "Invalid request", "detail": "Data validation error occurred",
                             "validation": [{"field": "title", "title": "Too many capital letters AT"},
                                            {"field": "bad field!", "title": "x"}]}}
        cases = [((400, invalid), "olx_invalid_request", False, ("title",)), ((401, {}), "olx_auth_failed", False, ()),
                 ((403, b""), "olx_forbidden", False, ()), ((429, b""), "olx_rate_limited", False, ()),
                 ((503, b""), "olx_rejected_503", True, ()), ((200, {"data": {}}), "olx_created_without_id", True, ()),
                 (TimeoutError(), "olx_outcome_uncertain", True, ())]
        for answer, code, uncertain, fields in cases:
            with self.assertRaises(op.OlxError, msg=code) as err:
                op.create_advert(FakeHttp(answer), "AT", op.clean_advert(ADVERT), "olx_0123456789ab")
            self.assertEqual((err.exception.code, err.exception.uncertain, err.exception.fields),
                             (code, uncertain, fields))

    def test_reads_and_deactivate(self):
        http = FakeHttp((200, {"data": [{"id": 1, "status": "active", "url": "https://www.olx.ua/d/1.html",
                                         "external_id": "olx_0123456789ab"},
                                        {"id": 2, "status": "active", "external_id": "olx_ffffffffffff"},
                                        {"id": 3, "status": "active"}]}))
        found = op.find_by_external_id(http, "AT", "olx_0123456789ab")
        self.assertEqual([f["advert_id"] for f in found], ["1"])          # mismatched / missing external_id ignored
        self.assertIn("external_id=olx_0123456789ab", http.calls[0][1])
        http = FakeHttp((204, b""))
        op.deactivate_advert(http, "AT", "1", sold=True)
        self.assertEqual((http.calls[0][1], json.loads(http.calls[0][3])),
                         ("https://www.olx.ua/api/partner/adverts/1/commands", {"command": "deactivate", "is_success": True}))
        cats = op.reference(FakeHttp((200, {"data": [{"id": 3, "name": "Ноутбуки", "is_leaf": True, "secret": "x"}]})),
                            "AT", "categories", {"parent_id": "2"})
        self.assertEqual(cats, [{"id": 3, "name": "Ноутбуки", "is_leaf": True}])
        with self.assertRaises(HTTPException):
            op.reference(FakeHttp(), "AT", "packets", {})            # paid endpoints are not reachable
        with self.assertRaises(HTTPException):
            op.reference(FakeHttp(), "AT", "suggest", {"q": "ab"})

    def test_flag_and_language(self):
        self.assertFalse(op.enabled({}))
        self.assertTrue(op.enabled({"FACTORY_OLX_ENABLED": "1"}))
        self.assertEqual(op.language({"FACTORY_OLX_LANGUAGE": "ru"}), "ru")
        self.assertEqual(op.language({"FACTORY_OLX_LANGUAGE": "../x"}), "uk")


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = op.AdvertStore(pathlib.Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_approval_fence_edit_and_states(self):
        d = self.store.create(ADVERT)
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # not approved
        self.store.approve(d["id"])
        self.store.edit(d["id"], {**ADVERT, "price": {"value": 14000}})   # an edit drops the approval
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])
        self.store.approve(d["id"])
        self.assertEqual(self.store.claim_for_publish(d["id"])["status"], "publishing")
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # second click while publishing
        self.store.finish(d["id"], "uncertain", {"code": "olx_outcome_uncertain"})
        for call_ in (lambda: self.store.claim_for_publish(d["id"]), lambda: self.store.delete(d["id"]),
                      lambda: self.store.edit(d["id"], ADVERT)):
            with self.assertRaises(HTTPException):
                call_()
        with self.assertRaises(HTTPException):
            self.store.confirm(d["id"], "https://evil.example/x")
        self.assertEqual(self.store.confirm(d["id"], "https://www.olx.ua/d/uk/obyavlenie/x.html")["status"], "published")
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # never twice

    def test_stale_publishing_claim_can_be_resolved_without_resend(self):
        now = [1000.0]
        store = op.AdvertStore(pathlib.Path(self.tmp.name) / "s2", clock=lambda: now[0])
        d = store.create(ADVERT)
        store.approve(d["id"], "olx:user:7")
        store.claim_for_publish(d["id"])                          # process dies here, after the POST
        self.assertFalse(store.unresolved(store.get(d["id"])))   # a live request is not touched
        with self.assertRaises(HTTPException):
            store.confirm(d["id"], "not_published")
        now[0] += op.STALE_CLAIM_SECONDS + 1
        self.assertTrue(store.unresolved(store.get(d["id"])))
        with self.assertRaises(HTTPException):
            store.claim_for_publish(d["id"])                      # still never a second POST
        self.assertEqual(store.confirm(d["id"], "https://www.olx.ua/d/9.html")["status"], "published")

    def test_tampered_file_is_refused(self):
        d = self.store.create(ADVERT)
        self.store.approve(d["id"])
        items = json.loads(self.store.path.read_text())
        items[0]["advert"]["title"] = "Інший заголовок оголошення тут"
        self.store.path.write_text(json.dumps(items))
        with self.assertRaises(HTTPException):
            self.store.claim_for_publish(d["id"])                 # approval hash no longer matches
        with self.assertRaises(HTTPException):
            self.store.approve("../etc")


def call(endpoint, *args, role="owner", body=None, query=b""):
    raw = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    request = Request({"type": "http", "method": "POST", "headers": [(b"x-role", role.encode())], "path": "/",
                       "query_string": query}, receive)
    result = endpoint(*args, request)
    return asyncio.run(result) if asyncio.iscoroutine(result) else result


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = MemoryTokenVault()
        self.http = FakeHttp()
        self.flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), self.vault,
                              adapters={"olx": op.OlxOAuthAdapter(self.http)})
        self.env = {"FACTORY_OLX_ENABLED": "1"}
        self.store = op.AdvertStore(pathlib.Path(self.tmp.name))
        app = FastAPI()
        op.install_routes(app, store=self.store, flow=self.flow,
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

    def connect(self):
        self.vault.put("default", "olx", TokenSet(access_token="AT", refresh_token="RT", account_id="olx:user:7",
                                                  account_label="Andrii"))

    def approved(self):
        d = self.route("/api/factory/olx/drafts", body={"advert": ADVERT})["draft"]
        return self.route("/api/factory/olx/drafts/{draft_id}/approve", d["id"])["draft"]

    def test_owner_only_and_not_ready_without_connection_or_flag(self):
        for path, args in (("/api/factory/olx", ()), ("/api/factory/olx/drafts", ()),
                           ("/api/factory/olx/drafts/{draft_id}/publish", ("olx_000000000000",)),
                           ("/api/factory/olx/reference/{kind}", ("categories",))):
            with self.assertRaises(HTTPException) as err:
                self.route(path, *args, role="member", body={"advert": ADVERT})
            self.assertEqual(err.exception.status_code, 403)
        state = self.route("/api/factory/olx")
        self.assertIn("olx_not_connected", state["blockers"])
        self.assertEqual(state["redirect_uri"], "https://factory.test/api/oauth/olx/callback")
        self.connect()
        self.env["FACTORY_OLX_ENABLED"] = "0"
        self.assertEqual(self.route("/api/factory/olx")["blockers"], ["olx_publishing_off"])
        d = self.approved()
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertIn("olx_publishing_off", err.exception.detail)
        with self.assertRaises(HTTPException) as err:
            op.publish_approved(store=self.store, flow=self.flow, workspace="default", draft_id=d["id"], env=self.env)
        self.assertEqual(err.exception.detail, "olx_publishing_off")
        self.assertEqual(self.http.calls, [])                      # nothing left FactoryOS

    def test_publish_once_refreshes_token_and_uncertain_is_not_retried(self):
        self.connect()
        d = self.approved()
        self.http.answers += [(200, {"access_token": "AT2", "refresh_token": "RT2", "expires_in": 86400}),
                              (200, {"data": {"id": 42, "status": "new", "url": "https://www.olx.ua/d/42.html"}})]
        out = self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])["draft"]
        self.assertEqual((out["status"], out["result"]["advert_id"], out["result"]["olx_status"]), ("published", "42", "new"))
        self.assertEqual(self.http.calls[1][2]["Authorization"], "Bearer AT2")
        self.assertEqual(self.vault.get("default", "olx").refresh_token, "RT2")   # rotated token stored in the vault
        self.assertEqual(json.loads(self.http.calls[1][3])["external_id"], d["id"])
        with self.assertRaises(HTTPException):
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(len(self.http.calls), 2)                 # refused before any network call
        d2 = self.approved()
        self.http.answers += [(200, {"access_token": "AT3", "refresh_token": "RT3"}), TimeoutError()]
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d2["id"])
        self.assertEqual(err.exception.detail, "olx_outcome_uncertain")
        with self.assertRaises(HTTPException):
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d2["id"])
        self.assertEqual(len(self.http.calls), 4)                 # no blind retry
        # Reconcile: read-only lookup by external_id; nothing found keeps it unknown, a match marks it published.
        self.http.answers += [(200, {"access_token": "AT3"}), (200, {"data": []})]
        self.assertFalse(self.route("/api/factory/olx/drafts/{draft_id}/reconcile", d2["id"])["found"])
        self.assertEqual(self.store.get(d2["id"])["status"], "uncertain")
        self.http.answers += [(200, {"access_token": "AT3"}),
                              (200, {"data": [{"id": 43, "status": "active", "url": "https://www.olx.ua/d/43.html",
                                               "external_id": d2["id"]}]})]
        rec = self.route("/api/factory/olx/drafts/{draft_id}/reconcile", d2["id"])
        self.assertEqual((rec["found"], rec["draft"]["status"], rec["draft"]["result"]["advert_id"]),
                         (True, "published", "43"))
        self.assertTrue(all(c[0] == "GET" or c[1].endswith("/oauth/token") for c in self.http.calls[4:]))
        state = json.dumps(self.route("/api/factory/olx"))
        for secret in ("AT", "RT2", "csecret"):
            self.assertNotIn('"' + secret, state)

    def test_approval_is_bound_to_the_connected_account(self):
        d = self.route("/api/factory/olx/drafts", body={"advert": ADVERT})["draft"]
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/approve", d["id"])   # not connected
        self.assertEqual(err.exception.status_code, 409)
        self.connect()
        self.route("/api/factory/olx/drafts/{draft_id}/approve", d["id"])
        self.vault.put("default", "olx", TokenSet(access_token="AT9", refresh_token="RT9", account_id="olx:user:8"))
        self.http.answers.append((200, {"access_token": "AT9", "refresh_token": "RT9"}))
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(err.exception.detail, "olx_account_changed_approve_again")
        self.assertFalse(any(c[1].endswith("/api/partner/adverts") for c in self.http.calls))
        self.assertEqual(self.store.get(d["id"])["status"], "approved")
        with self.assertRaises(HTTPException) as err:
            op.publish_approved(store=self.store, flow=self.flow, workspace="other", draft_id=d["id"], env=self.env)
        self.assertEqual(err.exception.detail, "olx_not_connected")      # another workspace has no tokens

    def test_refresh_in_flight_never_restores_tokens_after_disconnect_or_reconnect(self):
        self.connect()
        d = self.approved()

        def disconnect_then_answer():
            self.flow.disconnect("olx", "default")                # owner disconnects while the refresh is in flight
            return (200, {"access_token": "AT-late", "refresh_token": "RT-late"})
        self.http.answers.append(disconnect_then_answer)
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(err.exception.detail, "olx_not_connected")
        self.assertIsNone(self.vault.get("default", "olx"))       # vault stays empty
        self.assertEqual(self.store.get(d["id"])["status"], "approved")
        self.connect()

        def reconnect_then_answer():
            self.vault.put("default", "olx", TokenSet(access_token="NEW", refresh_token="NEWRT", account_id="olx:user:8"))
            return (200, {"access_token": "AT-late", "refresh_token": "RT-late"})
        self.http.answers.append(reconnect_then_answer)
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(err.exception.detail, "olx_connection_changed")
        self.assertEqual(self.vault.get("default", "olx").access_token, "NEW")   # the new account's tokens are kept
        self.assertFalse(any(c[1].endswith("/api/partner/adverts") for c in self.http.calls))

    def test_validation_error_fields_and_reconnect(self):
        self.connect()
        d = self.approved()
        self.http.answers += [(200, {"access_token": "AT"}),
                              (400, {"error": {"validation": [{"field": "category_id", "title": "Fix the category"}]}})]
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual((err.exception.status_code, err.exception.detail), (502, "olx_invalid_request"))
        failed = self.store.get(d["id"])
        self.assertEqual((failed["status"], failed["result"]), ("failed", {"code": "olx_invalid_request",
                                                                           "fields": ["category_id"]}))
        self.route("/api/factory/olx/drafts/{draft_id}/approve", d["id"])         # owner fixes, re-approves
        self.http.answers.append((400, {"error": "invalid_grant"}))               # refresh token expired (30 days)
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.assertEqual(err.exception.detail, "olx_reconnect_required")
        self.assertEqual(self.store.get(d["id"])["status"], "approved")           # not claimed, still publishable

    def test_refresh_status_deactivate_and_reference(self):
        self.connect()
        d = self.approved()
        self.http.answers += [(200, {"access_token": "AT"}), (200, {"id": 50, "status": "new"})]
        self.route("/api/factory/olx/drafts/{draft_id}/publish", d["id"])
        self.http.answers += [(200, {"access_token": "AT"}),
                              (200, {"data": {"id": 50, "status": "active", "url": "https://www.olx.ua/d/50.html"}})]
        out = self.route("/api/factory/olx/drafts/{draft_id}/refresh", d["id"])["draft"]
        self.assertEqual(out["result"]["olx_status"], "active")
        with self.assertRaises(HTTPException):
            self.route("/api/factory/olx/drafts/{draft_id}/deactivate", d["id"], body={})       # needs confirm
        self.http.answers += [(200, {"access_token": "AT"}), (204, b"")]
        out = self.route("/api/factory/olx/drafts/{draft_id}/deactivate", d["id"], body={"confirm": True, "sold": False})
        self.assertEqual((out["draft"]["status"], out["draft"]["result"]["olx_status"]), ("deactivated", "removed_by_user"))
        self.assertEqual(json.loads(self.http.calls[-1][3]), {"command": "deactivate", "is_success": False})
        with self.assertRaises(HTTPException):
            self.route("/api/factory/olx/drafts/{draft_id}/delete", d["id"])          # history stays
        self.http.answers += [(200, {"access_token": "AT"}), (200, [{"code": "state", "label": "Стан", "values": []}])]
        ref = self.route("/api/factory/olx/reference/{kind}", "attributes", query=b"id=1234")
        self.assertEqual(ref["items"], [{"code": "state", "label": "Стан", "values": []}])
        self.assertTrue(self.http.calls[-1][1].endswith("/api/partner/categories/1234/attributes"))
        self.assertFalse(any("/packets" in c[1] or "/paid-features" in c[1] for c in self.http.calls))


if __name__ == "__main__":
    unittest.main()
