"""Google Sheets for agents through the official Sheets API v4 (owner 2026-11-22, T-725).

Owner: «собери данные с этого сайта, помести их в Google таблицу». Agents collect data with the Surfer read tools
and write it into the owner's spreadsheet through `sheets.googleapis.com`, never by clicking in a browser.

Rules this module keeps:
- Everything is off until the owner sets FACTORY_GOOGLE_SHEETS_ENABLED=1 (the code ships dark).
- Agents reach only spreadsheets the owner registered on /static/sheets/index.html (the allowlist is enforced here, because the
  OAuth scope itself covers every spreadsheet of the account). Appending needs the per-sheet switch «agents may
  append»; reading works for every registered sheet.
- Agent tools need a per-lane MCP token (the shared token is refused), so every call has an author in the history.
- Reads and appends are bounded per call and per day. Appended text that a spreadsheet would treat as a formula
  (starts with = + - @, tab or CR) is stored as text (leading apostrophe).
- `sheet_append` needs an idempotency key. The claim is written to disk before the request: a retry with the same key
  and the same rows returns the first result; after an unknown outcome (timeout / 5xx / crash) it refuses to resend.
- The access token is sent only to `sheets.googleapis.com`; tokens live only in the encrypted token vault. Errors
  carry fixed codes; Google response bodies and tokens are never stored, logged or returned.
- Network goes through one injectable `http` callable, so the tests make zero network calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable
from urllib import error as urlerror
from urllib import request as urlrequest
from urllib.parse import quote, urlencode

from fastapi import HTTPException, Request

from oauth_framework import OAuthAdapter, OAuthError, OAuthProvider, TokenSet

log = logging.getLogger("factoryos.sheets")

PROVIDER = "google_sheets"
SCOPE = "https://www.googleapis.com/auth/spreadsheets"
API = "https://sheets.googleapis.com/v4/spreadsheets"
SHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,100}$")
SHEET_URL_RE = re.compile(r"^https://docs\.google\.com/spreadsheets/d/([A-Za-z0-9_-]{20,100})(?:[/?#].*)?$")
RANGE_RE = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]{0,6}):([A-Za-z]{1,3})([1-9][0-9]{0,6})$")   # Sheets ends at ZZZ
KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,100}$")
NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

MAX_SHEETS = 20
TITLE_MAX = 120
TAB_MAX = 100
TABS_MAX = 50
READ_MAX_ROWS = 500
READ_MAX_CELLS = 5000
READ_CELL_CHARS = 2000
READ_DEFAULT_RANGE = "A1:Z100"
READS_PER_DAY = 500
APPEND_MAX_ROWS = 200                    # per call
APPEND_MAX_COLS = 50
APPEND_MAX_CELLS = 2000                  # per call
APPEND_CELL_CHARS = 2000
APPEND_ROWS_PER_DAY = 2000
APPEND_CELLS_PER_DAY = 20000
APPEND_CALLS_PER_DAY = 300               # also bounds the idempotency records: 300 a day x KEY_TTL_DAYS
STALE_CLAIM_SECONDS = 300                # an append claim older than this died mid-request: outcome unknown
KEY_TTL_DAYS = 7
KEY_TTL_SECONDS = KEY_TTL_DAYS * 86400   # a record is dropped only by age, never to make room for a new one
HISTORY_KEPT = 300
RESPONSE_MAX_BYTES = 4 * 1024 * 1024

# http(method, url, headers, body, timeout) -> (status, headers, body_bytes). Raises only for transport failures.
Http = Callable[[str, str, dict, object, float], tuple]


class SheetsError(ValueError):
    """Fixed, token-free code (a ValueError, so the MCP endpoint returns the code to the agent)."""

    def __init__(self, code: str, uncertain: bool = False):
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


def urllib_http(method, url, headers, body, timeout):
    req = urlrequest.Request(url, data=body, headers=dict(headers or {}), method=method)
    try:
        with urlrequest.urlopen(req, timeout=timeout) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read(RESPONSE_MAX_BYTES + 1)
    except urlerror.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, exc.read(65536) or b""


def _json(body: bytes) -> dict:
    try:
        data = json.loads((body or b"{}").decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def enabled(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("FACTORY_GOOGLE_SHEETS_ENABLED", "")).strip().lower() in ("1", "true", "yes")


def client_credentials(spec: OAuthProvider) -> tuple:
    return os.environ.get(spec.client_id_env, "").strip(), os.environ.get(spec.client_secret_env, "").strip()


class GoogleSheetsOAuthAdapter(OAuthAdapter):
    """Google transport for the `google_sheets` OAuth provider (authorization_code + PKCE, offline refresh token)."""

    def __init__(self, http: Http = urllib_http, timeout: float = 25.0):
        self.http = http
        self.timeout = timeout

    def ready(self, spec: OAuthProvider) -> bool:
        return all(client_credentials(spec))

    def _token(self, spec, form: dict, failure: str) -> dict:
        client_id, client_secret = client_credentials(spec)
        if not (client_id and client_secret):
            raise OAuthError("client_secret_missing")
        body = urlencode({**form, "client_id": client_id, "client_secret": client_secret}).encode()
        try:
            status, _, raw = self.http("POST", spec.token_url, {"Content-Type": "application/x-www-form-urlencoded",
                                                                "Accept": "application/json"}, body, self.timeout)
        except (TimeoutError, OSError, urlerror.URLError):
            raise OAuthError("sheets_token_unreachable") from None
        data = _json(raw)
        if status != 200 or not data.get("access_token"):
            raise OAuthError(failure)
        return data

    def exchange_code(self, spec, code, redirect_uri, code_verifier):
        form = {"code": code, "redirect_uri": redirect_uri, "grant_type": "authorization_code"}
        if code_verifier:
            form["code_verifier"] = code_verifier
        data = self._token(spec, form, "exchange_failed")
        scopes = tuple(str(data.get("scope") or "").split()) or spec.scopes
        if SCOPE not in scopes:
            # Google lets the user untick a permission on the consent screen: a token without it is useless here.
            raise OAuthError("sheets_scope_missing")
        if not data.get("refresh_token"):
            raise OAuthError("sheets_refresh_token_missing")
        # No identity scope is requested (DECISIONS T-725): the label is fixed, the account id is not known.
        return TokenSet(access_token=str(data["access_token"]), refresh_token=str(data["refresh_token"]),
                        expires_in=int(data.get("expires_in") or 0), scopes=scopes,
                        account_id="google-sheets", account_label="Google Sheets")

    def refresh(self, spec, tokens: TokenSet) -> TokenSet:
        if not tokens.refresh_token:
            raise OAuthError("sheets_reconnect_required")
        data = self._token(spec, {"refresh_token": tokens.refresh_token, "grant_type": "refresh_token"},
                           "sheets_reconnect_required")
        return TokenSet(access_token=str(data["access_token"]),
                        refresh_token=str(data.get("refresh_token") or tokens.refresh_token),
                        expires_in=int(data.get("expires_in") or 0),
                        scopes=tuple(str(data.get("scope") or "").split()) or tokens.scopes,
                        account_id=tokens.account_id, account_label=tokens.account_label)

    def revoke(self, spec, tokens):
        token = tokens.refresh_token or tokens.access_token
        status, _, _ = self.http("POST", spec.revoke_url, {"Content-Type": "application/x-www-form-urlencoded"},
                                 urlencode({"token": token}).encode(), self.timeout)
        return status == 200


# --- Validation ----------------------------------------------------------------------------

def parse_sheet_id(value) -> str:
    """Spreadsheet id from a docs.google.com URL or a bare id. Raises SheetsError."""
    text = str(value or "").strip()
    match = SHEET_URL_RE.match(text)
    if match:
        return match.group(1)
    if SHEET_ID_RE.fullmatch(text):
        return text
    raise SheetsError("sheets_url_invalid")


def clean_tab(value) -> str:
    """'' (first tab) or a tab title. Raises SheetsError."""
    tab = str(value or "").strip()
    if len(tab) > TAB_MAX or any(ord(ch) < 32 for ch in tab):
        raise SheetsError("sheets_tab_invalid")
    return tab


def _col(letters: str) -> int:
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def clean_range(value) -> str:
    """A fully bounded A1 range such as A1:F50 (both corners with row numbers). Raises SheetsError."""
    text = str(value or "").strip().replace("$", "") or READ_DEFAULT_RANGE
    match = RANGE_RE.fullmatch(text)
    if not match:
        raise SheetsError("sheets_range_invalid")
    c1, r1, c2, r2 = _col(match.group(1)), int(match.group(2)), _col(match.group(3)), int(match.group(4))
    if c2 < c1 or r2 < r1:
        raise SheetsError("sheets_range_invalid")
    rows, cols = r2 - r1 + 1, c2 - c1 + 1
    if rows > READ_MAX_ROWS or rows * cols > READ_MAX_CELLS:
        raise SheetsError("sheets_range_too_large")
    return text.upper()


def a1(tab: str, cells: str) -> str:
    return ("'" + tab.replace("'", "''") + "'!" + cells) if tab else cells


def safe_cell(value):
    """One cell for valueInputOption=USER_ENTERED. Text a spreadsheet would run as a formula becomes plain text."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if isinstance(value, float) and value != value or value in (float("inf"), float("-inf")):
            raise SheetsError("sheets_cell_invalid")
        return value
    if not isinstance(value, str):
        raise SheetsError("sheets_cell_invalid")
    text = "".join(ch for ch in value.replace("\r\n", "\n") if ch in "\n\t\r" or ord(ch) >= 32)
    if len(text) > APPEND_CELL_CHARS:
        raise SheetsError("sheets_cell_too_long")
    probe = text.lstrip(" \n")
    if text[:1] == "'" or (probe.startswith(FORMULA_START) and not NUMBER_RE.fullmatch(text.strip())):
        return "'" + text
    return text


def clean_rows(rows) -> list:
    if not isinstance(rows, list) or not rows:
        raise SheetsError("sheets_rows_required")
    if len(rows) > APPEND_MAX_ROWS:
        raise SheetsError("sheets_too_many_rows")
    out, cells = [], 0
    for row in rows:
        if not isinstance(row, list) or not row:
            raise SheetsError("sheets_rows_invalid")
        if len(row) > APPEND_MAX_COLS:
            raise SheetsError("sheets_too_many_columns")
        cells += len(row)
        if cells > APPEND_MAX_CELLS:
            raise SheetsError("sheets_too_many_cells")
        out.append([safe_cell(v) for v in row])
    return out


def payload_hash(sheet_id: str, tab: str, rows: list) -> str:
    raw = json.dumps([sheet_id, tab, rows], ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# --- Google API ----------------------------------------------------------------------------

def _is_api_disabled(body: bytes) -> bool:
    err = _json(body).get("error")
    if not isinstance(err, dict):
        return False
    reasons = [str(d.get("reason") or "") for d in (err.get("details") or []) + (err.get("errors") or [])
               if isinstance(d, dict)]
    return any(r in ("SERVICE_DISABLED", "accessNotConfigured") for r in reasons)


def _request(http: Http, method: str, url: str, access_token: str, body: dict | None, *, write: bool,
             timeout: float = 25.0) -> dict:
    """One Sheets API call. A write whose outcome cannot be known raises SheetsError(uncertain=True)."""
    if not url.startswith(API):                        # the token never goes to another host
        raise SheetsError("sheets_internal_url")
    headers = {"Authorization": "Bearer " + access_token, "Accept": "application/json"}
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        status, _, raw = http(method, url, headers, data, timeout)
    except (TimeoutError, OSError, urlerror.URLError):
        raise SheetsError("sheets_append_outcome_unknown" if write else "sheets_unreachable", uncertain=write) from None
    if status == 200:
        if len(raw or b"") > RESPONSE_MAX_BYTES:
            raise SheetsError("sheets_response_too_large")
        return _json(raw)
    if status == 401:
        raise SheetsError("sheets_auth_failed")
    if status == 403:
        raise SheetsError("sheets_api_not_enabled" if _is_api_disabled(raw) else "sheets_forbidden")
    fixed = {400: "sheets_invalid_request", 404: "sheets_not_found", 429: "sheets_rate_limited"}
    if status in fixed:
        raise SheetsError(fixed[status])
    if status >= 500 and write:
        raise SheetsError("sheets_append_outcome_unknown", uncertain=True)
    raise SheetsError("sheets_unreachable" if status >= 500 else "sheets_rejected")


def _meta(data: dict) -> dict:
    title = str((data.get("properties") or {}).get("title") or "")[:TITLE_MAX]
    tabs = []
    for item in (data.get("sheets") or [])[:TABS_MAX]:
        name = str(((item or {}).get("properties") or {}).get("title") or "") if isinstance(item, dict) else ""
        if name:
            tabs.append(name[:TAB_MAX])
    return {"title": title, "tabs": tabs}


def api_metadata(http: Http, access_token: str, sheet_id: str) -> dict:
    url = f"{API}/{sheet_id}?fields=" + quote("spreadsheetId,properties.title,sheets.properties.title", safe="")
    return _meta(_request(http, "GET", url, access_token, None, write=False))


def api_create(http: Http, access_token: str, title: str) -> dict:
    data = _request(http, "POST", API, access_token, {"properties": {"title": title}}, write=False)
    sheet_id = str(data.get("spreadsheetId") or "")
    if not SHEET_ID_RE.fullmatch(sheet_id):
        raise SheetsError("sheets_created_without_id")
    return {"id": sheet_id, **_meta(data)}


def api_read(http: Http, access_token: str, sheet_id: str, tab: str, cells: str) -> list:
    url = (f"{API}/{sheet_id}/values/{quote(a1(tab, cells), safe='')}"
           "?majorDimension=ROWS&valueRenderOption=FORMATTED_VALUE")
    values = _request(http, "GET", url, access_token, None, write=False).get("values")
    rows, cells_left = [], READ_MAX_CELLS
    for row in (values if isinstance(values, list) else [])[:READ_MAX_ROWS]:
        row = (row if isinstance(row, list) else [])[:max(cells_left, 0)]
        cells_left -= len(row)
        rows.append([("" if v is None else str(v))[:READ_CELL_CHARS] for v in row])
    return rows


def api_append(http: Http, access_token: str, sheet_id: str, tab: str, rows: list) -> dict:
    url = (f"{API}/{sheet_id}/values/{quote(a1(tab, 'A1'), safe='')}:append"
           "?valueInputOption=USER_ENTERED&insertDataOption=INSERT_ROWS&includeValuesInResponse=false")
    data = _request(http, "POST", url, access_token, {"majorDimension": "ROWS", "values": rows}, write=True)
    updates = data.get("updates") if isinstance(data.get("updates"), dict) else {}

    def count(name):
        try:
            return max(0, int(updates.get(name) or 0))
        except (TypeError, ValueError):
            return 0
    return {"updated_range": str(updates.get("updatedRange") or "")[:200], "updated_rows": count("updatedRows"),
            "updated_cells": count("updatedCells")}


# --- Tokens --------------------------------------------------------------------------------

def readiness(flow, workspace_id: str, env=None) -> tuple:
    """(blockers, tokens) for calling the Sheets API as the connected account."""
    from oauth_framework import get_provider
    blockers = list(flow.blockers(get_provider(PROVIDER)))
    tokens = None
    if "vault_unavailable" not in blockers:
        try:
            tokens = flow.vault.get(workspace_id, PROVIDER)
        except Exception:
            blockers.append("vault_unreadable")
    if not tokens and not blockers:
        blockers.append("sheets_not_connected")
    if not enabled(env):
        blockers.append("sheets_off")
    return blockers, tokens


def refreshed_tokens(flow, workspace_id: str, tokens: TokenSet) -> TokenSet:
    """Refresh after a 401. The HTTP call runs outside the flow lock; the write-back is a compare-and-set under it,
    so a disconnect or a reconnect during the refresh wins (same fence as olx_publisher.fresh_tokens)."""
    from oauth_framework import get_provider
    adapter = flow.adapters.get(PROVIDER)
    if adapter is None or not hasattr(adapter, "refresh"):
        raise SheetsError("sheets_auth_failed")
    try:
        new = adapter.refresh(get_provider(PROVIDER), tokens)
    except OAuthError as exc:
        raise SheetsError(exc.code if exc.code.startswith("sheets_") else "sheets_reconnect_required") from None
    with flow.lock:
        current = flow.vault.get(workspace_id, PROVIDER)
        if not current:
            raise SheetsError("sheets_not_connected")
        if (current.access_token, current.refresh_token) != (tokens.access_token, tokens.refresh_token):
            raise SheetsError("sheets_connection_changed")
        flow.vault.put(workspace_id, PROVIDER, new)
    return new


# --- Store: allowlist, daily budget, idempotency claims, history ----------------------------

class SheetStore:
    def __init__(self, data_dir, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "google_sheets.json"
        self.clock = clock
        self.lock = threading.RLock()

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        for key, kind in (("sheets", list), ("appends", dict), ("usage", dict), ("history", list)):
            if not isinstance(data.get(key), kind):
                data[key] = kind()
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    def _usage(self, data: dict) -> dict:
        day = self._day()
        data["usage"] = {day: data["usage"].get(day) or {}}          # only today is kept
        usage = data["usage"][day]
        for key in ("reads", "rows", "cells", "appends"):
            usage[key] = int(usage.get(key) or 0)
        return usage

    def _log(self, data: dict, actor: str, action: str, sheet_id: str = "", **extra) -> None:
        entry = {"at": int(self.clock()), "actor": str(actor)[:40], "action": action, "sheet_id": sheet_id, **extra}
        data["history"] = (data["history"] + [entry])[-HISTORY_KEPT:]
        log.info("sheets %s actor=%s sheet=%s status=%s", action, entry["actor"], sheet_id[:12],
                 extra.get("status", "ok"))

    # allowlist ------------------------------------------------------------------------------
    def sheets(self) -> list:
        with self.lock:
            return [dict(s) for s in self._load()["sheets"]]

    def get(self, sheet_id) -> dict:
        sheet_id = str(sheet_id or "").strip()
        if not SHEET_ID_RE.fullmatch(sheet_id):
            sheet_id = parse_sheet_id(sheet_id)
        item = next((s for s in self.sheets() if s["id"] == sheet_id), None)
        if not item:
            raise SheetsError("sheets_not_registered")
        return item

    def add(self, sheet_id: str, meta: dict, actor: str = "owner", created: bool = False) -> dict:
        with self.lock:
            data = self._load()
            item = next((s for s in data["sheets"] if s["id"] == sheet_id), None)
            if item is None:
                if len(data["sheets"]) >= MAX_SHEETS:
                    raise SheetsError("sheets_too_many_targets")
                item = {"id": sheet_id, "agents_append": False, "added": int(self.clock())}
                data["sheets"].append(item)
            item.update(title=meta.get("title") or "", tabs=list(meta.get("tabs") or []),
                        url=f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit")
            self._log(data, actor, "create" if created else "add", sheet_id, title=item["title"])
            self._save(data)
            return dict(item)

    def set_append(self, sheet_id: str, allowed: bool, actor: str = "owner") -> dict:
        with self.lock:
            data = self._load()
            item = next((s for s in data["sheets"] if s["id"] == sheet_id), None)
            if not item:
                raise SheetsError("sheets_not_registered")
            item["agents_append"] = bool(allowed)
            self._log(data, actor, "allow_append" if allowed else "forbid_append", sheet_id)
            self._save(data)
            return dict(item)

    def remove(self, sheet_id: str, actor: str = "owner") -> bool:
        with self.lock:
            data = self._load()
            kept = [s for s in data["sheets"] if s["id"] != sheet_id]
            if len(kept) == len(data["sheets"]):
                raise SheetsError("sheets_not_registered")
            data["sheets"] = kept
            self._log(data, actor, "remove", sheet_id)
            self._save(data)
            return True

    # reads ----------------------------------------------------------------------------------
    def count_read(self, actor: str, sheet_id: str, tab: str, cells: str) -> None:
        with self.lock:
            data = self._load()
            usage = self._usage(data)
            if usage["reads"] >= READS_PER_DAY:
                raise SheetsError("sheets_daily_read_limit")
            usage["reads"] += 1
            self._log(data, actor, "read", sheet_id, tab=tab, range=cells)
            self._save(data)

    # appends --------------------------------------------------------------------------------
    def claim_append(self, actor: str, key: str, digest: str, sheet_id: str, tab: str, rows: int, cells: int):
        """Returns ("replay", result) for a finished identical call, or ("send", None) after writing the claim.
        Raises SheetsError when the key was used for other rows, the earlier outcome is unknown, or the daily
        budget is used up."""
        ident = f"{actor}:{key}"
        with self.lock:
            data = self._load()
            now = int(self.clock())
            record = data["appends"].get(ident)
            if record:
                if record.get("hash") != digest:
                    raise SheetsError("sheets_idempotency_conflict")
                if record.get("status") == "done":
                    self._log(data, actor, "append", sheet_id, tab=tab, rows=rows, cells=cells, status="replayed",
                              key=key)
                    self._save(data)
                    return "replay", dict(record.get("result") or {})
                # "sending" (in flight, or the process died mid-request) and "uncertain": never resent blindly.
                raise SheetsError("sheets_append_in_progress"
                                  if record.get("status") == "sending"
                                  and now - int(record.get("at") or 0) < STALE_CLAIM_SECONDS
                                  else "sheets_append_outcome_unknown")
            usage = self._usage(data)
            if (usage["rows"] + rows > APPEND_ROWS_PER_DAY or usage["cells"] + cells > APPEND_CELLS_PER_DAY
                    or usage["appends"] >= APPEND_CALLS_PER_DAY):
                raise SheetsError("sheets_daily_append_limit")
            usage["rows"] += rows
            usage["cells"] += cells
            usage["appends"] += 1
            data["appends"][ident] = {"hash": digest, "status": "sending", "at": now, "sheet_id": sheet_id,
                                      "rows": rows, "cells": cells}
            # Only age removes a record. The daily call cap keeps the file small (300 x 7 records at most), so a
            # live key is never evicted and a retry inside the window can never write twice.
            data["appends"] = {k: v for k, v in data["appends"].items()
                               if now - int(v.get("at") or 0) < KEY_TTL_SECONDS}
            self._save(data)
            return "send", None

    def finish_append(self, actor: str, key: str, sheet_id: str, tab: str, *, result: dict | None = None,
                      code: str = "", uncertain: bool = False) -> None:
        ident = f"{actor}:{key}"
        with self.lock:
            data = self._load()
            record = data["appends"].get(ident) or {}
            rows, cells = int(record.get("rows") or 0), int(record.get("cells") or 0)
            if result is not None:
                record.update(status="done", result=result)
                data["appends"][ident] = record
                status = "appended"
            elif uncertain:
                record.update(status="uncertain", code=code)
                data["appends"][ident] = record
                status = "unknown"
            else:
                # A certain failure wrote nothing: free the key and give the budget back.
                data["appends"].pop(ident, None)
                usage = self._usage(data)
                usage["rows"] = max(0, usage["rows"] - rows)
                usage["cells"] = max(0, usage["cells"] - cells)
                usage["appends"] = max(0, usage["appends"] - 1)
                status = "failed"
            extra = {"code": code} if code else {}
            if result:
                extra["range"] = result.get("updated_range", "")
            self._log(data, actor, "append", sheet_id, tab=tab, rows=rows, cells=cells, status=status, key=key,
                      **extra)
            self._save(data)

    def overview(self) -> dict:
        with self.lock:
            data = self._load()
            usage = dict(self._usage(data))
            return {"sheets": [dict(s) for s in data["sheets"]], "usage": usage,
                    "history": list(reversed(data["history"]))[:100]}


LIMITS = {"read_max_rows": READ_MAX_ROWS, "read_max_cells": READ_MAX_CELLS, "reads_per_day": READS_PER_DAY,
          "append_max_rows": APPEND_MAX_ROWS, "append_max_columns": APPEND_MAX_COLS,
          "append_max_cells": APPEND_MAX_CELLS, "append_cell_chars": APPEND_CELL_CHARS,
          "append_rows_per_day": APPEND_ROWS_PER_DAY, "append_cells_per_day": APPEND_CELLS_PER_DAY,
          "append_calls_per_day": APPEND_CALLS_PER_DAY, "idempotency_key_days": KEY_TTL_DAYS}


# --- Service: the one path for owner routes and agent tools ----------------------------------

class Sheets:
    def __init__(self, store: SheetStore, flow, workspace: Callable[[], str], http: Http | None = None, env=None):
        self.store, self.flow, self.workspace, self.env = store, flow, workspace, env
        self._http = http

    @property
    def http(self) -> Http:
        return self._http or getattr(self.flow.adapters.get(PROVIDER), "http", urllib_http)

    def _call(self, fn: Callable[[str], object]):
        """Run one API call with the stored token; on 401 refresh once and repeat (a 401 wrote nothing)."""
        blockers, tokens = readiness(self.flow, self.workspace(), self.env)
        if blockers:
            raise SheetsError("sheets_disabled" if "sheets_off" in blockers else
                              "sheets_not_connected" if "sheets_not_connected" in blockers else "sheets_not_ready")
        try:
            return fn(tokens.access_token)
        except SheetsError as exc:
            if exc.code != "sheets_auth_failed":
                raise
        tokens = refreshed_tokens(self.flow, self.workspace(), tokens)
        return fn(tokens.access_token)

    # owner ----------------------------------------------------------------------------------
    def add_target(self, url) -> dict:
        sheet_id = parse_sheet_id(url)
        meta = self._call(lambda token: api_metadata(self.http, token, sheet_id))
        return self.store.add(sheet_id, meta)

    def create_target(self, title) -> dict:
        title = " ".join(str(title or "").split())[:TITLE_MAX]
        if not title:
            raise SheetsError("sheets_title_required")
        made = self._call(lambda token: api_create(self.http, token, title))
        return self.store.add(made["id"], made, created=True)

    # agents ---------------------------------------------------------------------------------
    def list_for_agent(self) -> dict:
        view = self.store.overview()
        usage = view["usage"]
        return {"enabled": enabled(self.env),
                "sheets": [{"sheet_id": s["id"], "title": s.get("title", ""), "tabs": s.get("tabs", []),
                            "agents_may_append": bool(s.get("agents_append"))} for s in view["sheets"]],
                "limits": LIMITS,
                "left_today": {"reads": max(0, READS_PER_DAY - usage["reads"]),
                               "append_rows": max(0, APPEND_ROWS_PER_DAY - usage["rows"]),
                               "append_cells": max(0, APPEND_CELLS_PER_DAY - usage["cells"]),
                               "append_calls": max(0, APPEND_CALLS_PER_DAY - usage["appends"])},
                "note": "Only spreadsheets the owner registered on /static/sheets/index.html are reachable."}

    def read(self, actor: str, sheet_id, tab="", cells="") -> dict:
        if not enabled(self.env):
            raise SheetsError("sheets_disabled")
        sheet, tab, cells = self.store.get(sheet_id), clean_tab(tab), clean_range(cells)
        self.store.count_read(actor, sheet["id"], tab, cells)
        rows = self._call(lambda token: api_read(self.http, token, sheet["id"], tab, cells))
        return {"sheet_id": sheet["id"], "title": sheet.get("title", ""), "tab": tab, "range": cells,
                "rows": rows, "row_count": len(rows)}

    def append(self, actor: str, sheet_id, rows, idempotency_key, tab="") -> dict:
        if not enabled(self.env):
            raise SheetsError("sheets_disabled")
        key = str(idempotency_key or "")
        if not KEY_RE.fullmatch(key):
            raise SheetsError("sheets_idempotency_key_required")
        sheet, tab, rows = self.store.get(sheet_id), clean_tab(tab), clean_rows(rows)
        if not sheet.get("agents_append"):
            raise SheetsError("sheets_append_not_allowed")
        cells = sum(len(r) for r in rows)
        action, earlier = self.store.claim_append(actor, key, payload_hash(sheet["id"], tab, rows), sheet["id"], tab,
                                                  len(rows), cells)
        if action == "replay":
            return {"sheet_id": sheet["id"], "tab": tab, **earlier, "replayed": True}
        try:
            result = self._call(lambda token: api_append(self.http, token, sheet["id"], tab, rows))
        except SheetsError as exc:
            self.store.finish_append(actor, key, sheet["id"], tab, code=exc.code, uncertain=exc.uncertain)
            raise
        except Exception:
            self.store.finish_append(actor, key, sheet["id"], tab, code="sheets_append_outcome_unknown",
                                     uncertain=True)
            raise SheetsError("sheets_append_outcome_unknown", uncertain=True) from None
        result = {**result, "sent_rows": len(rows), "sent_cells": cells}
        self.store.finish_append(actor, key, sheet["id"], tab, result=result)
        return {"sheet_id": sheet["id"], "tab": tab, **result, "replayed": False}


# --- MCP tools -------------------------------------------------------------------------------

MCP_TOOLS = [
    {"name": "sheet_list",
     "description": "List the Google spreadsheets the owner registered for agents (id, title, tabs, whether agents "
                    "may append), the per-call and per-day limits and what is left today. Needs a per-lane token.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"name": "sheet_read",
     "description": "Read a bounded range of a registered Google spreadsheet through the official Sheets API. "
                    "range is A1 notation with both corners, e.g. A1:F50 (default A1:Z100, at most 500 rows and "
                    "5000 cells); tab is the tab title (default: the first tab). Needs a per-lane token.",
     "inputSchema": {"type": "object", "properties": {
         "sheet_id": {"type": "string"}, "tab": {"type": "string"}, "range": {"type": "string"}},
         "required": ["sheet_id"], "additionalProperties": False}},
    {"name": "sheet_append",
     "description": "Append rows after the last row of a registered Google spreadsheet where the owner switched on "
                    "'agents may append'. rows is a list of rows, each a list of cells (text, number or boolean); "
                    "at most 200 rows, 50 columns and 2000 cells per call, 300 calls a day: send rows in batches. Text starting with = + - @ is stored as "
                    "text, never as a formula. idempotency_key (8-100 chars of A-Z a-z 0-9 _ . : -) is required: "
                    "repeat a call with the SAME key and the SAME rows after a network error and nothing is "
                    "written twice. On sheets_append_outcome_unknown do not resend: read the sheet first.",
     "inputSchema": {"type": "object", "properties": {
         "sheet_id": {"type": "string"}, "tab": {"type": "string"},
         "rows": {"type": "array", "items": {"type": "array", "items": {"type": ["string", "number", "boolean", "null"]}}},
         "idempotency_key": {"type": "string"}},
         "required": ["sheet_id", "rows", "idempotency_key"], "additionalProperties": False}},
]
MCP_TOOL_NAMES = frozenset(t["name"] for t in MCP_TOOLS)


def call_tool(service: Sheets, name: str, args: dict, lane: str = "") -> dict:
    """Agent entry point. `lane` is the verified per-lane identity ('' for the shared MCP token: refused)."""
    args = args if isinstance(args, dict) else {}
    if not lane:
        raise SheetsError("sheets_lane_token_required")
    actor = "agent:" + str(lane)[:30]
    if name == "sheet_list":
        return service.list_for_agent()
    if name == "sheet_read":
        return service.read(actor, args.get("sheet_id"), args.get("tab"), args.get("range"))
    if name == "sheet_append":
        return service.append(actor, args.get("sheet_id"), args.get("rows"), args.get("idempotency_key"),
                              args.get("tab"))
    raise SheetsError("sheets_unknown_tool")


# --- Owner routes ------------------------------------------------------------------------------

_HTTP_STATUS = {"sheets_not_registered": 404, "sheets_not_found": 404, "sheets_disabled": 409,
                "sheets_not_connected": 409, "sheets_not_ready": 409, "sheets_too_many_targets": 409,
                "sheets_url_invalid": 400, "sheets_title_required": 400}


def install_routes(app, *, service: Sheets, identity: Callable) -> None:
    store, flow = service.store, service.flow

    def owner(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def guarded(fn):
        try:
            return fn()
        except SheetsError as exc:
            raise HTTPException(_HTTP_STATUS.get(exc.code, 502), exc.code) from None

    @app.get("/api/factory/sheets")
    def sheets_state(request: Request):
        owner(request)
        from oauth_framework import get_provider
        blockers, tokens = readiness(flow, service.workspace(), service.env)
        return {"enabled": enabled(service.env), "ready": not blockers, "blockers": blockers,
                "connected": bool(tokens), "account": (tokens.account_label if tokens else ""),
                "redirect_uri": flow.redirect_uri(get_provider(PROVIDER)), "limits": LIMITS,
                "max_sheets": MAX_SHEETS, **store.overview()}

    @app.post("/api/factory/sheets/targets")
    async def sheets_add(request: Request):
        owner(request)
        url = (await body(request)).get("url")
        return {"sheet": guarded(lambda: service.add_target(url))}

    @app.post("/api/factory/sheets/create")
    async def sheets_create(request: Request):
        owner(request)
        title = (await body(request)).get("title")
        return {"sheet": guarded(lambda: service.create_target(title))}

    @app.post("/api/factory/sheets/targets/{sheet_id}/append")
    async def sheets_toggle(sheet_id: str, request: Request):
        owner(request)
        allowed = (await body(request)).get("allowed") is True
        return {"sheet": guarded(lambda: store.set_append(sheet_id, allowed))}

    @app.post("/api/factory/sheets/targets/{sheet_id}/remove")
    def sheets_remove(sheet_id: str, request: Request):
        owner(request)
        return {"ok": guarded(lambda: store.remove(sheet_id))}
