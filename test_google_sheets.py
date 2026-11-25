"""T-725 Google Sheets for agents: OAuth adapter, allowlist, bounds, formula safety, idempotent append, lane auth.
Offline: fake HTTP, in-memory vault, handlers called directly (no TestClient: CI has no httpx)."""
import asyncio
import json
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock
from urllib.parse import parse_qs, unquote

LANE = "lane-claude-7Qm2Vx9Lp4Rt8Wz1Ny6Kd3Hs5Jb0Fc"
SHARED = "sheets-test-shared-mcp-token-0123456789abcdef"
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-sheets-"))
os.environ.setdefault("FACTORY_MCP_TOKEN", SHARED)
os.environ.setdefault("FACTORY_MCP_LANE_TOKEN_CLAUDE", LANE)
os.environ.pop("FACTORY_GOOGLE_SHEETS_ENABLED", None)

from fastapi import FastAPI, HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import google_sheets as gs  # noqa: E402
from oauth_framework import MemoryTokenVault, OAuthError, OAuthFlow, TokenSet, get_provider  # noqa: E402

ENV = {"FACTORY_OAUTH_GOOGLE_SHEETS_CLIENT_ID": "cid", "FACTORY_OAUTH_GOOGLE_SHEETS_CLIENT_SECRET": "csecret"}
SID = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789_-abcd"
URL = f"https://docs.google.com/spreadsheets/d/{SID}/edit#gid=0"
META = {"spreadsheetId": SID, "properties": {"title": "Prices"},
        "sheets": [{"properties": {"title": "Sheet1"}}, {"properties": {"title": "Ціни"}}]}
APPENDED = {"spreadsheetId": SID, "updates": {"updatedRange": "Sheet1!A2:B3", "updatedRows": 2, "updatedCells": 4}}
ROWS = [["Lenovo T14", 15000], ["Dell 7490", "12 500"]]


class FakeHttp:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        answer = self.answers.pop(0)
        if callable(answer) and not isinstance(answer, Exception):
            answer = answer()
        if isinstance(answer, Exception):
            raise answer
        status, payload = answer
        return status, {}, json.dumps(payload).encode() if isinstance(payload, (dict, list)) else (payload or b"")


class AdapterTest(unittest.TestCase):
    def test_provider_is_a_separate_google_client_with_one_scope(self):
        spec = get_provider("google_sheets")
        self.assertEqual(spec.scopes, ("https://www.googleapis.com/auth/spreadsheets",))
        self.assertTrue(spec.pkce)
        self.assertEqual((spec.client_id_env, spec.client_secret_env),
                         ("FACTORY_OAUTH_GOOGLE_SHEETS_CLIENT_ID", "FACTORY_OAUTH_GOOGLE_SHEETS_CLIENT_SECRET"))
        self.assertNotEqual(spec.client_id_env, get_provider("youtube").client_id_env)
        self.assertEqual(dict(spec.extra_params), {"access_type": "offline", "prompt": "consent"})

    def test_exchange_needs_the_scope_and_a_refresh_token_and_never_leaks(self):
        spec = get_provider("google_sheets")
        http = FakeHttp((200, {"access_token": "AT", "refresh_token": "RT", "expires_in": 3599, "scope": gs.SCOPE}))
        with mock.patch.dict(os.environ, ENV):
            tokens = gs.GoogleSheetsOAuthAdapter(http).exchange_code(spec, "CODE", "https://x/cb", "V" * 50)
        self.assertEqual((tokens.access_token, tokens.refresh_token, tokens.account_label), ("AT", "RT", "Google Sheets"))
        self.assertEqual(http.calls[0][1], "https://oauth2.googleapis.com/token")
        sent = {k: v[0] for k, v in parse_qs(http.calls[0][3].decode()).items()}
        self.assertEqual(sent, {"grant_type": "authorization_code", "code": "CODE", "redirect_uri": "https://x/cb",
                                "code_verifier": "V" * 50, "client_id": "cid", "client_secret": "csecret"})
        self.assertNotIn("AT", repr(tokens))
        cases = [((400, {"error": "invalid_grant", "error_description": "AT RT CODE"}), "exchange_failed"),
                 ((200, {"access_token": "AT", "refresh_token": "RT", "scope": "openid"}), "sheets_scope_missing"),
                 ((200, {"access_token": "AT", "scope": gs.SCOPE}), "sheets_refresh_token_missing"),
                 (TimeoutError("AT"), "sheets_token_unreachable")]
        for answer, code in cases:
            with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
                gs.GoogleSheetsOAuthAdapter(FakeHttp(answer)).exchange_code(spec, "CODE", "https://x/cb", "")
            self.assertEqual(str(err.exception), code)
        with mock.patch.dict(os.environ, {}, clear=True), self.assertRaises(OAuthError) as err:
            gs.GoogleSheetsOAuthAdapter(FakeHttp()).exchange_code(spec, "CODE", "https://x/cb", "")
        self.assertEqual(err.exception.code, "client_secret_missing")

    def test_refresh_and_revoke(self):
        spec = get_provider("google_sheets")
        old = TokenSet(access_token="AT1", refresh_token="RT1", scopes=(gs.SCOPE,), account_label="Google Sheets")
        http = FakeHttp((200, {"access_token": "AT2", "expires_in": 3599}), (200, {}))
        with mock.patch.dict(os.environ, ENV):
            adapter = gs.GoogleSheetsOAuthAdapter(http)
            new = adapter.refresh(spec, old)
            self.assertTrue(adapter.revoke(spec, new))
        self.assertEqual((new.access_token, new.refresh_token, new.scopes), ("AT2", "RT1", (gs.SCOPE,)))
        self.assertEqual(parse_qs(http.calls[1][3].decode()), {"token": ["RT1"]})
        with mock.patch.dict(os.environ, ENV), self.assertRaises(OAuthError) as err:
            gs.GoogleSheetsOAuthAdapter(FakeHttp((400, {"error": "invalid_grant"}))).refresh(spec, old)
        self.assertEqual(err.exception.code, "sheets_reconnect_required")


class ValidationTest(unittest.TestCase):
    def code(self, fn, *args):
        with self.assertRaises(gs.SheetsError) as err:
            fn(*args)
        return err.exception.code

    def test_sheet_id_from_url_or_bare_id(self):
        self.assertEqual(gs.parse_sheet_id(URL), SID)
        self.assertEqual(gs.parse_sheet_id(" " + SID + " "), SID)
        for bad in ("", "https://evil.example/spreadsheets/d/" + SID, "http://docs.google.com/spreadsheets/d/" + SID,
                    "https://docs.google.com.evil.example/spreadsheets/d/" + SID, SID + "/../x", "short", None):
            self.assertEqual(self.code(gs.parse_sheet_id, bad), "sheets_url_invalid", bad)

    def test_range_must_be_bounded(self):
        self.assertEqual(gs.clean_range(""), "A1:Z100")
        self.assertEqual(gs.clean_range("$a$1:f50"), "A1:F50")
        for bad in ("A:Z", "A1", "Sheet1!A1:B2", "B2:A1", "A1:B2;C3", "A1:AAAA9"):
            self.assertEqual(self.code(gs.clean_range, bad), "sheets_range_invalid", bad)
        self.assertEqual(self.code(gs.clean_range, "A1:A501"), "sheets_range_too_large")
        self.assertEqual(self.code(gs.clean_range, "A1:Z500"), "sheets_range_too_large")
        self.assertEqual(gs.clean_range("zz1:aaa2"), "ZZ1:AAA2")     # three-letter columns: ZZ -> AAA boundary
        self.assertEqual(gs.clean_range("ZZZ1:ZZZ1"), "ZZZ1:ZZZ1")
        self.assertEqual(self.code(gs.clean_range, "AAA1:ZZ1"), "sheets_range_invalid")
        self.assertEqual(gs.a1("It's", "A1:B2"), "'It''s'!A1:B2")
        self.assertEqual(gs.a1("", "A1"), "A1")
        self.assertEqual(self.code(gs.clean_tab, "x" * 101), "sheets_tab_invalid")
        self.assertEqual(self.code(gs.clean_tab, "a\nb"), "sheets_tab_invalid")

    def test_formula_like_text_becomes_text(self):
        for raw in ("=1+1", "+cmd|' /C calc'!A0", "-2+3", "@SUM(A1)", "\t=1", "\r=1", "  =HYPERLINK(\"x\")", "\n=1",
                    "'already", "=IMPORTXML(\"https://evil.example\",\"//a\")", "+380 67 123 45 67"):
            self.assertEqual(gs.safe_cell(raw), "'" + raw, raw)
        for raw in ("hello", "a=b", "12 500", "-5", "+7", "-3,14", "2026-11-22", ""):
            self.assertEqual(gs.safe_cell(raw), raw, raw)
        self.assertEqual([gs.safe_cell(v) for v in (None, 5, 2.5, True)], ["", 5, 2.5, True])
        self.assertEqual(gs.safe_cell("a\x00b\x07"), "ab")
        self.assertEqual(self.code(gs.safe_cell, "x" * 2001), "sheets_cell_too_long")
        self.assertEqual(self.code(gs.safe_cell, {"a": 1}), "sheets_cell_invalid")
        self.assertEqual(self.code(gs.safe_cell, float("nan")), "sheets_cell_invalid")

    def test_rows_are_bounded(self):
        self.assertEqual(gs.clean_rows([["=x", 1]]), [["'=x", 1]])
        self.assertEqual(self.code(gs.clean_rows, []), "sheets_rows_required")
        self.assertEqual(self.code(gs.clean_rows, "rows"), "sheets_rows_required")
        self.assertEqual(self.code(gs.clean_rows, [["a"], "b"]), "sheets_rows_invalid")
        self.assertEqual(self.code(gs.clean_rows, [["a"], []]), "sheets_rows_invalid")
        self.assertEqual(self.code(gs.clean_rows, [["a"]] * 201), "sheets_too_many_rows")
        self.assertEqual(self.code(gs.clean_rows, [["a"] * 51]), "sheets_too_many_columns")
        self.assertEqual(self.code(gs.clean_rows, [["a"] * 50] * 41), "sheets_too_many_cells")


class ApiTest(unittest.TestCase):
    def test_append_request_shape(self):
        http = FakeHttp((200, APPENDED))
        out = gs.api_append(http, "AT", SID, "Ціни", [["a", 1]])
        self.assertEqual(out, {"updated_range": "Sheet1!A2:B3", "updated_rows": 2, "updated_cells": 4})
        method, url, headers, body = http.calls[0]
        self.assertEqual(method, "POST")
        path, query = url.split("?")
        self.assertTrue(path.startswith(f"https://sheets.googleapis.com/v4/spreadsheets/{SID}/values/"))
        self.assertEqual(unquote(path.rsplit("/", 1)[1]), "'Ціни'!A1:append")
        self.assertEqual(parse_qs(query), {"valueInputOption": ["USER_ENTERED"], "insertDataOption": ["INSERT_ROWS"],
                                           "includeValuesInResponse": ["false"]})
        self.assertEqual(headers["Authorization"], "Bearer AT")
        self.assertEqual(json.loads(body), {"majorDimension": "ROWS", "values": [["a", 1]]})

    def test_read_is_truncated_and_metadata_parsed(self):
        http = FakeHttp((200, {"values": [["a", None, 3], "junk", ["x" * 3000]]}), (200, META))
        rows = gs.api_read(http, "AT", SID, "", "A1:C3")
        self.assertEqual(rows[0], ["a", "", "3"])
        self.assertEqual((rows[1], len(rows[2][0])), ([], 2000))
        self.assertIn("/values/A1%3AC3?", http.calls[0][1])
        self.assertEqual(gs.api_metadata(http, "AT", SID), {"title": "Prices", "tabs": ["Sheet1", "Ціни"]})

    def test_errors_are_fixed_codes_and_only_writes_are_uncertain(self):
        disabled = {"error": {"code": 403, "message": "Sheets API has not been used in project 1 AT",
                              "status": "PERMISSION_DENIED", "details": [{"reason": "SERVICE_DISABLED"}]}}
        cases = [((400, {"error": {"message": "Unable to parse range AT"}}), "sheets_invalid_request", False),
                 ((401, {}), "sheets_auth_failed", False), ((403, {"error": {"status": "PERMISSION_DENIED"}}),
                                                            "sheets_forbidden", False),
                 ((403, disabled), "sheets_api_not_enabled", False), ((404, {}), "sheets_not_found", False),
                 ((429, {}), "sheets_rate_limited", False), ((503, b"AT"), "sheets_append_outcome_unknown", True),
                 (TimeoutError("AT"), "sheets_append_outcome_unknown", True)]
        for answer, code, uncertain in cases:
            with self.assertRaises(gs.SheetsError) as err:
                gs.api_append(FakeHttp(answer), "AT", SID, "", [["a"]])
            self.assertEqual((err.exception.code, err.exception.uncertain), (code, uncertain))
            self.assertNotIn("AT", str(err.exception))
        for answer in ((503, b""), OSError("x")):
            with self.assertRaises(gs.SheetsError) as err:
                gs.api_read(FakeHttp(answer), "AT", SID, "", "A1:B2")
            self.assertEqual((err.exception.code, err.exception.uncertain), ("sheets_unreachable", False))
        with self.assertRaises(gs.SheetsError) as err:
            gs._request(FakeHttp(), "GET", "https://evil.example/v4/spreadsheets", "AT", None, write=False)
        self.assertEqual(err.exception.code, "sheets_internal_url")


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.now = [1_800_000_000.0]
        self.vault = MemoryTokenVault()
        self.http = FakeHttp()
        self.flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), self.vault,
                              adapters={"google_sheets": gs.GoogleSheetsOAuthAdapter(self.http)})
        self.env = {"FACTORY_GOOGLE_SHEETS_ENABLED": "1"}
        self.store = gs.SheetStore(pathlib.Path(self.tmp.name), clock=lambda: self.now[0])
        self.svc = gs.Sheets(self.store, self.flow, lambda: "default", env=self.env)
        self.patch = mock.patch.dict(os.environ, ENV)
        self.patch.start()
        self.vault.put("default", "google_sheets", TokenSet(access_token="AT-SECRET-1", refresh_token="RT-SECRET-1",
                                                           scopes=(gs.SCOPE,), account_label="Google Sheets"))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def register(self, append=True):
        self.http.answers.append((200, META))
        sheet = self.svc.add_target(URL)
        if append:
            self.store.set_append(SID, True)
        return sheet

    def tool(self, name, args, lane="claude"):
        return gs.call_tool(self.svc, name, args, lane)

    def code(self, name, args, lane="claude"):
        with self.assertRaises(gs.SheetsError) as err:
            self.tool(name, args, lane)
        return err.exception.code

    def append_args(self, **over):
        return {"sheet_id": SID, "rows": ROWS, "idempotency_key": "run-42:page-1", **over}

    def test_only_registered_sheets_and_only_with_the_append_switch(self):
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_not_registered")
        self.assertEqual(self.code("sheet_append", self.append_args()), "sheets_not_registered")
        sheet = self.register(append=False)
        self.assertEqual((sheet["title"], sheet["tabs"], sheet["agents_append"]), ("Prices", ["Sheet1", "Ціни"], False))
        self.assertEqual(self.code("sheet_append", self.append_args()), "sheets_append_not_allowed")
        listed = self.tool("sheet_list", {})
        self.assertEqual(listed["sheets"], [{"sheet_id": SID, "title": "Prices", "tabs": ["Sheet1", "Ціни"],
                                             "agents_may_append": False}])
        self.http.answers.append((200, {"values": [["a", "b"]]}))
        read = self.tool("sheet_read", {"sheet_id": SID, "tab": "Ціни", "range": "a1:b5"})
        self.assertEqual((read["rows"], read["range"], read["tab"]), ([["a", "b"]], "A1:B5", "Ціни"))
        self.assertEqual(len(self.http.calls), 2)                  # metadata + one read; refused calls sent nothing
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID, "range": "A:Z"}), "sheets_range_invalid")
        self.assertEqual(self.code("sheet_read", {"sheet_id": "https://evil.example/x"}), "sheets_url_invalid")

    def test_shared_token_flag_and_connection_are_required(self):
        self.register()
        for name, args in (("sheet_list", {}), ("sheet_read", {"sheet_id": SID}), ("sheet_append", self.append_args())):
            self.assertEqual(self.code(name, args, lane=""), "sheets_lane_token_required")
        off = gs.Sheets(self.store, self.flow, lambda: "default", env={})
        for name, args in (("sheet_read", {"sheet_id": SID}), ("sheet_append", self.append_args())):
            with self.assertRaises(gs.SheetsError) as err:
                gs.call_tool(off, name, args, "claude")
            self.assertEqual(err.exception.code, "sheets_disabled")
        self.assertFalse(gs.call_tool(off, "sheet_list", {}, "claude")["enabled"])
        with self.assertRaises(gs.SheetsError) as err:
            off.add_target(URL)
        self.assertEqual(err.exception.code, "sheets_disabled")
        self.vault.delete("default", "google_sheets")
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_not_connected")
        self.assertEqual(self.code("sheet_append", self.append_args()), "sheets_not_connected")
        self.assertEqual(len(self.http.calls), 1)                  # only the metadata call from register()
        self.assertEqual(self.store.overview()["usage"]["rows"], 0)  # the refused append gave its budget back

    def test_append_is_idempotent_and_sanitised(self):
        self.register()
        self.http.answers.append((200, APPENDED))
        rows = [["=IMPORTXML(\"https://evil.example\")", "+380 67 111 22 33", -5, "ok"]]
        first = self.tool("sheet_append", self.append_args(rows=rows))
        self.assertEqual((first["updated_rows"], first["sent_rows"], first["replayed"]), (2, 1, False))
        sent = json.loads(self.http.calls[-1][3])["values"]
        self.assertEqual(sent, [["'=IMPORTXML(\"https://evil.example\")", "'+380 67 111 22 33", -5, "ok"]])
        again = self.tool("sheet_append", self.append_args(rows=rows))
        self.assertEqual((again["replayed"], again["updated_range"]), (True, "Sheet1!A2:B3"))
        self.assertEqual(len(self.http.calls), 2)                  # the retry did not reach Google
        self.assertEqual(self.code("sheet_append", self.append_args(rows=[["other"]])), "sheets_idempotency_conflict")
        self.assertEqual(self.code("sheet_append", self.append_args(tab="Ціни", rows=rows)), "sheets_idempotency_conflict")
        for bad in ("", "short", "has space 123", None, "x" * 101):
            self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key=bad)),
                             "sheets_idempotency_key_required")
        usage = self.store.overview()["usage"]
        self.assertEqual((usage["rows"], usage["cells"]), (1, 4))
        # the same key from another lane is another caller's key
        self.http.answers.append((200, APPENDED))
        self.assertFalse(self.tool("sheet_append", self.append_args(rows=rows), lane="chatgpt")["replayed"])

    def test_unknown_outcome_is_never_resent(self):
        self.register()
        self.http.answers.append(TimeoutError("slow"))
        self.assertEqual(self.code("sheet_append", self.append_args()), "sheets_append_outcome_unknown")
        calls = len(self.http.calls)
        self.assertEqual(self.code("sheet_append", self.append_args()), "sheets_append_outcome_unknown")
        self.assertEqual(len(self.http.calls), calls)
        self.assertEqual(self.store.overview()["usage"]["rows"], 2)   # may have been written: budget stays spent
        # a claim whose process died mid-request: "in progress" while fresh, "unknown" once stale; never resent
        self.store.claim_append("agent:claude", "crashed-key-1", "h", SID, "", 1, 1)
        digest = gs.payload_hash(SID, "", gs.clean_rows(ROWS))
        self.store.claim_append("agent:claude", "crashed-key-2", digest, SID, "", 2, 4)
        self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key="crashed-key-2")),
                         "sheets_append_in_progress")
        self.now[0] += gs.STALE_CLAIM_SECONDS + 1
        self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key="crashed-key-2")),
                         "sheets_append_outcome_unknown")
        self.assertEqual(len(self.http.calls), calls)
        # an exception that is not a SheetsError is also an unknown outcome
        self.http.answers.append(RuntimeError("boom AT-SECRET-1"))
        with self.assertRaises(gs.SheetsError) as err:
            self.tool("sheet_append", self.append_args(idempotency_key="other-key-1"))
        self.assertEqual((err.exception.code, str(err.exception)), ("sheets_append_outcome_unknown",) * 2)

    def test_certain_failure_frees_the_key_and_the_budget(self):
        self.register()
        self.http.answers += [(400, {"error": {"message": "Unable to parse range"}}), (200, APPENDED)]
        self.assertEqual(self.code("sheet_append", self.append_args(tab="Nope")), "sheets_invalid_request")
        self.assertEqual(self.store.overview()["usage"]["rows"], 0)
        self.assertFalse(self.tool("sheet_append", self.append_args(tab="Nope"))["replayed"])
        statuses = [h.get("status") for h in self.store.overview()["history"] if h["action"] == "append"]
        self.assertEqual(statuses, ["appended", "failed"])

    def test_daily_budget(self):
        self.register()
        big = [["x"] * 10] * 200
        for i in range(10):
            self.http.answers.append((200, APPENDED))
            self.tool("sheet_append", self.append_args(rows=big, idempotency_key=f"batch-key-{i}"))
        calls = len(self.http.calls)
        self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key="batch-key-10")),
                         "sheets_daily_append_limit")
        self.assertEqual(len(self.http.calls), calls)
        self.assertEqual(self.tool("sheet_list", {})["left_today"]["append_rows"], 0)
        self.now[0] += 86400                                        # next UTC day
        self.http.answers.append((200, APPENDED))
        self.tool("sheet_append", self.append_args(idempotency_key="batch-key-11"))
        with mock.patch.object(gs, "READS_PER_DAY", 1):
            self.http.answers.append((200, {"values": []}))
            self.tool("sheet_read", {"sheet_id": SID})
            self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_daily_read_limit")

    def test_a_full_key_store_never_evicts_a_live_key(self):
        """Fill every daily call slot for a whole key window: the first successful key still replays and the
        uncertain key is still fenced, so neither can be written twice."""
        self.register()
        self.http.answers += [(200, APPENDED), TimeoutError("slow")]
        self.tool("sheet_append", self.append_args(idempotency_key="first-done-key"))
        self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key="first-unknown-key")),
                         "sheets_append_outcome_unknown")
        calls = len(self.http.calls)
        for day in range(gs.KEY_TTL_DAYS - 1):
            start = 2 if day == 0 else 0
            for i in range(start, gs.APPEND_CALLS_PER_DAY):
                self.store.claim_append("agent:claude", f"fill-{day}-{i:04d}", "h", SID, "", 1, 1)
            with self.assertRaises(gs.SheetsError) as err:        # the day is full: refused, nothing evicted
                self.store.claim_append("agent:claude", f"over-{day}-key", "h", SID, "", 1, 1)
            self.assertEqual(err.exception.code, "sheets_daily_append_limit")
            self.now[0] += 86400 - 60
        records = json.loads(self.store.path.read_text(encoding="utf-8"))["appends"]
        self.assertEqual(len(records), gs.APPEND_CALLS_PER_DAY * (gs.KEY_TTL_DAYS - 1))
        self.assertTrue(self.tool("sheet_append", self.append_args(idempotency_key="first-done-key"))["replayed"])
        self.assertEqual(self.code("sheet_append", self.append_args(idempotency_key="first-unknown-key")),
                         "sheets_append_outcome_unknown")
        self.assertEqual(len(self.http.calls), calls)               # neither retry reached Google
        self.assertEqual(self.tool("sheet_list", {})["limits"]["append_calls_per_day"], gs.APPEND_CALLS_PER_DAY)

    def test_expired_token_is_refreshed_once_with_a_fenced_write_back(self):
        self.register()
        self.http.answers += [(401, {}), (200, {"access_token": "AT-SECRET-2", "expires_in": 3599}), (200, APPENDED)]
        self.assertFalse(self.tool("sheet_append", self.append_args())["replayed"])
        self.assertEqual([c[2].get("Authorization") for c in self.http.calls[-3:]],
                         ["Bearer AT-SECRET-1", None, "Bearer AT-SECRET-2"])
        stored = self.vault.get("default", "google_sheets")
        self.assertEqual((stored.access_token, stored.refresh_token), ("AT-SECRET-2", "RT-SECRET-1"))
        # still 401 after the refresh: a certain failure, no loop
        self.http.answers += [(401, {}), (200, {"access_token": "AT-SECRET-3"}), (401, {})]
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_auth_failed")
        # refresh refused by Google: reconnect
        self.http.answers += [(401, {}), (400, {"error": "invalid_grant"})]
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_reconnect_required")
        # a disconnect during the refresh wins: the refreshed token is not stored
        self.http.answers += [(401, {}), lambda: (self.vault.delete("default", "google_sheets"),
                                                   (200, {"access_token": "AT-SECRET-4"}))[1]]
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_not_connected")
        self.assertIsNone(self.vault.get("default", "google_sheets"))

    def test_tokens_never_reach_the_store_history_or_other_hosts(self):
        self.register()
        self.http.answers += [(200, APPENDED), (401, {}), (200, {"access_token": "AT-SECRET-2"}),
                              (200, {"values": [["a"]]}), (403, {"error": {"message": "AT-SECRET-2"}})]
        self.tool("sheet_append", self.append_args())
        self.tool("sheet_read", {"sheet_id": SID})
        self.assertEqual(self.code("sheet_read", {"sheet_id": SID}), "sheets_forbidden")
        disk = self.store.path.read_text(encoding="utf-8")
        for secret in ("AT-SECRET", "RT-SECRET", "csecret", "Lenovo"):   # no tokens and no cell values on disk
            self.assertNotIn(secret, disk)
        self.assertNotIn("SECRET", json.dumps(self.tool("sheet_list", {})))
        for method, url, headers, _ in self.http.calls:
            if "Authorization" in headers:
                self.assertTrue(url.startswith("https://sheets.googleapis.com/v4/spreadsheets"), url)
        history = self.store.overview()["history"]
        self.assertEqual({h["actor"] for h in history}, {"owner", "agent:claude"})
        entry = next(h for h in history if h["action"] == "append")
        self.assertEqual((entry["rows"], entry["cells"], entry["status"], entry["key"], entry["range"]),
                         (2, 4, "appended", "run-42:page-1", "Sheet1!A2:B3"))

    def test_create_and_allowlist_limits(self):
        self.http.answers.append((200, {"spreadsheetId": SID, "properties": {"title": "New"}, "sheets": []}))
        made = self.svc.create_target("  New   sheet ")
        self.assertEqual((made["id"], made["agents_append"]), (SID, False))
        self.assertEqual(json.loads(self.http.calls[0][3]), {"properties": {"title": "New sheet"}})
        self.assertEqual(self.http.calls[0][1], "https://sheets.googleapis.com/v4/spreadsheets")
        with self.assertRaises(gs.SheetsError) as err:
            self.svc.create_target("  ")
        self.assertEqual(err.exception.code, "sheets_title_required")
        with mock.patch.object(gs, "MAX_SHEETS", 1), self.assertRaises(gs.SheetsError) as err:
            self.store.add("B" * 44, {"title": "x"})
        self.assertEqual(err.exception.code, "sheets_too_many_targets")
        self.http.answers.append((403, {"error": {"status": "PERMISSION_DENIED"}}))
        with self.assertRaises(gs.SheetsError) as err:
            self.svc.add_target("C" * 44)
        self.assertEqual(err.exception.code, "sheets_forbidden")
        self.assertEqual(len(self.store.sheets()), 1)               # a sheet Google refused is not registered


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
                              adapters={"google_sheets": gs.GoogleSheetsOAuthAdapter(self.http)})
        self.env = {"FACTORY_GOOGLE_SHEETS_ENABLED": "1"}
        self.svc = gs.Sheets(gs.SheetStore(pathlib.Path(self.tmp.name)), self.flow, lambda: "default", env=self.env)
        app = FastAPI()
        gs.install_routes(app, service=self.svc, identity=lambda r: {"role": r.headers.get("x-role")})
        self.ep = {getattr(r, "path", ""): r.endpoint for r in app.routes}
        self.patch = mock.patch.dict(os.environ, ENV)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def test_every_route_is_owner_only(self):
        paths = [p for p in self.ep if p.startswith("/api/factory/sheets")]
        self.assertEqual(len(paths), 5)
        for path in paths:
            args = (SID,) if "{sheet_id}" in path else ()
            for role in ("viewer", "customer", ""):
                with self.assertRaises(HTTPException) as err:
                    call(self.ep[path], *args, role=role, body={"url": URL})
                self.assertEqual(err.exception.status_code, 403, path)
        self.assertEqual(self.http.calls, [])

    def test_owner_flow_state_add_toggle_remove(self):
        state = call(self.ep["/api/factory/sheets"])
        self.assertEqual((state["ready"], state["connected"], state["blockers"]), (False, False, ["sheets_not_connected"]))
        self.assertEqual(state["redirect_uri"], "https://factory.test/api/oauth/google_sheets/callback")
        with self.assertRaises(HTTPException) as err:
            call(self.ep["/api/factory/sheets/targets"], body={"url": URL})
        self.assertEqual((err.exception.status_code, err.exception.detail), (409, "sheets_not_connected"))
        self.vault.put("default", "google_sheets", TokenSet(access_token="AT-SECRET", refresh_token="RT-SECRET"))
        with self.assertRaises(HTTPException) as err:
            call(self.ep["/api/factory/sheets/targets"], body={"url": "https://example.com/sheet"})
        self.assertEqual((err.exception.status_code, err.exception.detail), (400, "sheets_url_invalid"))
        self.http.answers.append((200, META))
        added = call(self.ep["/api/factory/sheets/targets"], body={"url": URL})["sheet"]
        self.assertEqual((added["id"], added["agents_append"], added["url"]),
                         (SID, False, f"https://docs.google.com/spreadsheets/d/{SID}/edit"))
        toggle = self.ep["/api/factory/sheets/targets/{sheet_id}/append"]
        self.assertFalse(call(toggle, SID, body={"allowed": "yes"})["sheet"]["agents_append"])   # only a real true
        self.assertTrue(call(toggle, SID, body={"allowed": True})["sheet"]["agents_append"])
        state = call(self.ep["/api/factory/sheets"])
        self.assertTrue(state["ready"] and state["sheets"][0]["agents_append"])
        self.assertNotIn("SECRET", json.dumps(state))
        self.assertEqual([h["action"] for h in state["history"]], ["allow_append", "forbid_append", "add"])
        remove = self.ep["/api/factory/sheets/targets/{sheet_id}/remove"]
        self.assertTrue(call(remove, SID)["ok"])
        with self.assertRaises(HTTPException) as err:
            call(remove, SID)
        self.assertEqual(err.exception.status_code, 404)
        with self.assertRaises(gs.SheetsError):
            gs.call_tool(self.svc, "sheet_read", {"sheet_id": SID}, "claude")   # removed = unreachable for agents

    def test_flag_off_blocks_google_calls(self):
        self.env.clear()
        self.vault.put("default", "google_sheets", TokenSet(access_token="AT", refresh_token="RT"))
        self.assertEqual(call(self.ep["/api/factory/sheets"])["blockers"], ["sheets_off"])
        for path, body in (("/api/factory/sheets/targets", {"url": URL}), ("/api/factory/sheets/create", {"title": "x"})):
            with self.assertRaises(HTTPException) as err:
                call(self.ep[path], body=body)
            self.assertEqual((err.exception.status_code, err.exception.detail), (409, "sheets_disabled"))
        self.assertEqual(self.http.calls, [])


class AppWiringTest(unittest.TestCase):
    """The real /mcp endpoint: tools are listed, the shared token is refused, the flag is off by default."""

    def mcp(self, payload, token):
        import app as factory
        body = json.dumps(payload).encode()
        sent = {"done": False}

        async def receive():
            if sent["done"]:
                return {"type": "http.disconnect"}
            sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/mcp", "query_string": b"",
                           "headers": [(b"content-type", b"application/json"),
                                       (b"authorization", ("Bearer " + token).encode())]}, receive)
        response = asyncio.run(factory.factory_mcp(request))
        return response.status_code, json.loads(response.body or b"{}")

    def tool(self, name, args, token):
        status, out = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": name, "arguments": args}}, token)
        self.assertEqual(status, 200, out)
        return out["result"].get("isError", False), out["result"]["content"][0]["text"]

    def test_mcp_tools_listed_and_fenced(self):
        import app as factory
        shared, lane = os.environ["FACTORY_MCP_TOKEN"], os.environ["FACTORY_MCP_LANE_TOKEN_CLAUDE"]
        if factory.FACTORY_MCP_TOKEN != shared:
            self.skipTest("app was imported with another MCP token")
        _, listed = self.mcp({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, shared)
        names = [t["name"] for t in listed["result"]["tools"]]
        self.assertTrue(gs.MCP_TOOL_NAMES <= set(names))
        self.assertEqual(len(names), len(set(names)))
        args = {"sheet_id": SID, "rows": [["a"]], "idempotency_key": "wiring-key-1"}
        for name, a in (("sheet_list", {}), ("sheet_read", {"sheet_id": SID}), ("sheet_append", args)):
            self.assertEqual(self.tool(name, a, shared), (True, "sheets_lane_token_required"))
        self.assertEqual(self.tool("sheet_append", args, lane), (True, "sheets_disabled"))
        err, text = self.tool("sheet_list", {}, lane)
        self.assertFalse(err)
        self.assertEqual((json.loads(text)["enabled"], json.loads(text)["sheets"]), (False, []))
        self.assertIn("Google Sheets", factory.PORTABLE_INTEGRATIONS)
        self.assertIsInstance(factory.OAUTH_FLOW.adapters["google_sheets"], gs.GoogleSheetsOAuthAdapter)


class PageTest(unittest.TestCase):
    def test_page_has_three_languages_with_the_same_keys(self):
        html = (pathlib.Path(__file__).parent / "static" / "sheets" / "index.html").read_text(encoding="utf-8")
        script = html.rsplit("<script>", 1)[1]
        blocks = {lang: script.split(f"\n{lang}:{{", 1)[1].split("}},\n" if lang != "en" else "}}};", 1)[0]
                  for lang in ("ru", "uk", "en")}
        keys = {lang: sorted(re.findall(r"(?:^|[,{\n ])([A-Za-z_]+):[\"{]", text)) for lang, text in blocks.items()}
        self.assertEqual(keys["ru"], keys["en"])
        self.assertEqual(keys["uk"], keys["en"])
        self.assertGreater(len(keys["en"]), 60)
        for needle in ("/api/oauth/google_sheets/authorize", "/api/factory/sheets/targets", "T-725-H",
                       "sheets_api_not_enabled"):
            self.assertIn(needle, html)
        self.assertNotIn("innerHTML=S.", html)                      # server text goes through esc()


if __name__ == "__main__":
    unittest.main(verbosity=1)
