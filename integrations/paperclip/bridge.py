"""Paperclip -> Relay observe-only bridge (GitHub #368, S0b proof of concept).

Relay stays the only source of task claims and execution. A Paperclip wake/issue
event becomes, at most, a *proposed read-only mapping* between a Paperclip issue
and an existing, Claude-owned Relay ticket. The bridge never creates, claims,
runs or cancels a Relay ticket, never touches GitHub and never wakes a worker:
it only reads a ticket through an injected lookup and writes its own mapping file.

Secure defaults:
- disabled unless PAPERCLIP_BRIDGE_ENABLED=1, and fails closed when any setting is missing;
- no network at import time; the only outbound call is an optional GET to a
  loopback (127.0.0.1) Paperclip, with capped timeout/retries and no redirects/proxies;
- events must carry an HMAC-SHA256 signature over "<timestamp>.<raw body>" and a
  timestamp within MAX_SKEW_S; replays of the same event id return the stored result;
- secrets never appear in repr, results or the mapping file.

Not wired into app.py: mounting an HTTP route is an S1 step behind owner approval.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Callable, Optional
from urllib.parse import quote, urlsplit

import evidence as proof

EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,120}$")
PAPERCLIP_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
RELAY_ID_RE = re.compile(r"^R-\d{4,8}$")
# Normalised event names this bridge accepts; everything else is rejected, not ignored.
EVENT_KINDS = {"issue.wake": "propose", "issue.updated": "propose", "issue.cancelled": "cancel"}
RELAY_ACTIVE = {"claimed", "running", "checkpoint", "committed", "pushed"}
RELAY_FINAL = {"done", "blocked", "failed"}
SHARED_LANES = {"", "any", "auto"}
MAX_BODY_BYTES = 16 * 1024
MAX_SKEW_S = 300
MIN_SECRET_LEN = 32
LOOPBACK_HOST = "127.0.0.1"
MAX_EVENTS_KEPT = 5000


class PaperclipUnavailable(Exception):
    """Paperclip did not answer within the capped retries; the bridge fails closed."""


def sign_event(secret: str, timestamp: str, raw_body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256).hexdigest()


def _clamp(value: Any, low: float, high: float, default: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def loopback_url_problem(url: str) -> str:
    """Only plain http://127.0.0.1:<port> is allowed: no hostnames (DNS rebinding), no public IPs, no paths with creds."""
    parts = urlsplit(url or "")
    if not url:
        return "base_url_missing"
    if parts.scheme != "http" or parts.hostname != LOOPBACK_HOST or parts.username or parts.password:
        return "base_url_not_loopback"
    try:
        if not parts.port:
            return "base_url_not_loopback"
    except ValueError:
        return "base_url_not_loopback"
    if parts.path not in ("", "/") or parts.query or parts.fragment:
        return "base_url_not_loopback"
    return ""


@dataclass(frozen=True)
class BridgeSettings:
    enabled: bool = False
    base_url: str = ""
    state_path: str = ""
    secret: str = field(default="", repr=False)
    paperclip_token: str = field(default="", repr=False)
    expected_owner: str = "claude"
    timeout_s: float = 3.0
    max_retries: int = 1
    rate_per_minute: int = 30

    @classmethod
    def from_env(cls, env: Optional[dict] = None) -> "BridgeSettings":
        env = os.environ if env is None else env
        return cls(
            enabled=str(env.get("PAPERCLIP_BRIDGE_ENABLED") or "") == "1",
            base_url=str(env.get("PAPERCLIP_BRIDGE_BASE_URL") or "").rstrip("/"),
            state_path=str(env.get("PAPERCLIP_BRIDGE_STATE_PATH") or ""),
            secret=str(env.get("PAPERCLIP_BRIDGE_SECRET") or ""),
            paperclip_token=str(env.get("PAPERCLIP_BRIDGE_TOKEN") or ""),
            timeout_s=_clamp(env.get("PAPERCLIP_BRIDGE_TIMEOUT_S"), 0.5, 10.0, 3.0),
            max_retries=int(_clamp(env.get("PAPERCLIP_BRIDGE_MAX_RETRIES"), 0, 2, 1)),
            rate_per_minute=int(_clamp(env.get("PAPERCLIP_BRIDGE_RATE_PER_MIN"), 1, 60, 30)),
        )

    def problems(self) -> list[str]:
        """Every reason the bridge must stay closed. Empty list means it may process events."""
        found = []
        if not self.enabled:
            found.append("disabled")
        if len(self.secret) < MIN_SECRET_LEN:
            found.append("secret_missing")
        if not self.state_path:
            found.append("state_path_missing")
        url_problem = loopback_url_problem(self.base_url)
        if url_problem:
            found.append(url_problem)
        if not (0.5 <= self.timeout_s <= 10.0 and 0 <= self.max_retries <= 2 and 1 <= self.rate_per_minute <= 60):
            found.append("caps_out_of_range")
        return found


class _NoRedirect:
    """urllib handler factory kept lazy so importing this module opens nothing."""

    @staticmethod
    def opener():
        import urllib.request

        class Refuse(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):  # SSRF: never follow a redirect off loopback
                return None

        return urllib.request.build_opener(urllib.request.ProxyHandler({}), Refuse)


def urllib_transport(method: str, url: str, headers: dict, timeout: float) -> tuple[int, bytes]:
    import urllib.error
    import urllib.request

    if loopback_url_problem(url.split("/api/", 1)[0]):
        raise PaperclipUnavailable("refused_non_loopback")
    request = urllib.request.Request(url, method=method, headers=headers)
    try:
        with _NoRedirect.opener().open(request, timeout=timeout) as response:
            return response.status, response.read(64 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, b""


class PaperclipClient:
    """Read-only Paperclip API client: one GET to confirm an issue exists. Never writes to Paperclip."""

    def __init__(self, settings: BridgeSettings, transport: Optional[Callable] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.settings = settings
        self.transport = transport or urllib_transport
        self.sleep = sleep

    def issue_exists(self, issue_id: str) -> bool:
        if not PAPERCLIP_ID_RE.fullmatch(issue_id or ""):
            return False
        url = self.settings.base_url + "/api/issues/" + quote(issue_id, safe="")
        headers = {"Accept": "application/json"}
        if self.settings.paperclip_token:
            headers["Authorization"] = "Bearer " + self.settings.paperclip_token
        last = "unavailable"
        for attempt in range(1 + self.settings.max_retries):
            if attempt:
                self.sleep(min(2.0, 0.25 * (2 ** attempt)))
            try:
                status, _ = self.transport("GET", url, headers, self.settings.timeout_s)
            except TimeoutError:
                last = "timeout"
                continue
            except PaperclipUnavailable:
                raise
            except OSError:
                last = "unavailable"
                continue
            if status == 200:
                return True
            if status == 404:
                return False
            if status >= 500:
                last = "http_" + str(status)
                continue
            raise PaperclipUnavailable("http_" + str(status))   # 401/403 etc.: misconfigured, do not retry
        raise PaperclipUnavailable(last)


class MappingStore:
    """Bridge-owned JSON file (never relay.json). Atomic replace so a restart keeps every mapping and seen event."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def load(self) -> dict:
        try:
            data = json.loads(self.path.read_text("utf-8"))
        except FileNotFoundError:
            data = {}
        if not isinstance(data, dict):
            raise ValueError("mapping_state_corrupt")
        data.setdefault("version", 1)
        data.setdefault("events", {})
        data.setdefault("mappings", {})
        return data

    def save(self, data: dict) -> None:
        events = data["events"]
        if len(events) > MAX_EVENTS_KEPT:
            for key in sorted(events, key=lambda k: events[k].get("at", 0))[: len(events) - MAX_EVENTS_KEPT]:
                events.pop(key, None)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=1), "utf-8")
        os.replace(tmp, self.path)


def _ticket_owner(ticket: dict) -> str:
    execution_owner = str((ticket.get("execution") or {}).get("owner") or "").strip().lower()
    source_owner = str((ticket.get("source") or {}).get("owner") or "").strip().lower()
    return execution_owner or source_owner


def correlation(ticket: dict, paperclip: dict) -> dict:
    """project -> issue/task -> relay ticket -> relay run -> paperclip issue/run -> branch/PR -> evidence level."""
    source = ticket.get("source") or {}
    ex = ticket.get("execution") or {}
    state = str(ex.get("state") or "queued")
    if state in RELAY_FINAL:
        stage = state
    elif state in RELAY_ACTIVE:
        stage = "claimed"                      # a worker holds the claim; Paperclip did not
    else:
        stage = "queued"                       # nobody has claimed it; queued != claimed
    level = proof.level(ticket)
    return {
        "project_id": str(source.get("repo") or source.get("channel") or ""),
        "issue_or_task_id": str(source.get("issue_number") or source.get("task_id") or ""),
        "relay_ticket_id": str(ticket.get("id") or ""),
        "relay_run_id": str(ex.get("run_id") or ""),
        "paperclip_company_id": paperclip.get("company_id", ""),
        "paperclip_issue_id": paperclip["issue_id"],
        "paperclip_run_id": paperclip.get("run_id", ""),
        "branch": str(ex.get("branch") or ""),
        "pr_url": str(ex.get("pr_url") or ""),
        "relay_stage": stage,
        # done != verified: "done" is a worker report; only evidence level checked/accepted is server/owner proof.
        "evidence_level": level,
        "verified": level in ("checked", "accepted"),
        "owner_accepted": level == "accepted",
    }


class PaperclipBridge:
    def __init__(self, settings: BridgeSettings, relay_lookup: Callable[[str], Optional[dict]],
                 client: Optional[PaperclipClient] = None, store: Optional[MappingStore] = None,
                 clock: Callable[[], float] = time.time):
        self.settings = settings
        self.relay_lookup = relay_lookup     # read-only: RelayStore.get returns a copy
        self.client = client
        self.store = store or (MappingStore(settings.state_path) if settings.state_path else None)
        self.clock = clock
        self._window: list[float] = []
        self._rate_lock = threading.Lock()

    # Result helpers keep a stable, secret-free shape for logs and tests.
    @staticmethod
    def _out(status: int, code: str, **extra) -> tuple[int, dict]:
        # The bridge writes only its own mapping file; Relay, GitHub, workers and Paperclip are never mutated.
        body = {"ok": 200 <= status < 300, "code": code, "relay_side_effects": "none"}
        body.update(extra)
        return status, body

    def _rate_ok(self, now: float) -> bool:
        with self._rate_lock:
            self._window = [t for t in self._window if now - t < 60]
            if len(self._window) >= self.settings.rate_per_minute:
                return False
            self._window.append(now)
            return True

    def _authentic(self, headers: dict, raw: bytes, now: float) -> str:
        lower = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
        signature = lower.get("x-paperclip-signature", "")
        stamp = lower.get("x-paperclip-timestamp", "")
        if not signature or not stamp:
            return "unauthenticated"
        if not re.fullmatch(r"\d{9,11}", stamp):
            return "unauthenticated"
        if abs(now - int(stamp)) > MAX_SKEW_S:
            return "stale_signature"
        expected = sign_event(self.settings.secret, stamp, raw)
        return "" if hmac.compare_digest(expected, signature) else "unauthenticated"

    @staticmethod
    def _parse(raw: bytes) -> tuple[Optional[dict], str]:
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return None, "malformed_json"
        if not isinstance(event, dict):
            return None, "malformed_payload"
        event_id = event.get("event_id")
        kind = event.get("type")
        issue = event.get("issue") if isinstance(event.get("issue"), dict) else {}
        relay_id = str(issue.get("relay_ticket_id") or "").strip().upper()
        if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
            return None, "invalid_event_id"
        if kind not in EVENT_KINDS:
            return None, "unsupported_event_type"
        if not isinstance(issue.get("id"), str) or not PAPERCLIP_ID_RE.fullmatch(issue["id"]):
            return None, "invalid_paperclip_issue_id"
        for key in ("company_id", "run_id"):
            value = issue.get(key, "")
            if not isinstance(value, str) or (value and not PAPERCLIP_ID_RE.fullmatch(value)):
                return None, "invalid_" + key
        if not RELAY_ID_RE.fullmatch(relay_id):
            return None, "invalid_relay_ticket_id"
        occurred = event.get("occurred_at")
        if type(occurred) is not int or occurred <= 0:
            return None, "invalid_occurred_at"
        return {
            "event_id": event_id,
            "action": EVENT_KINDS[kind],
            "type": kind,
            "occurred_at": occurred,
            "relay_ticket_id": relay_id,
            "paperclip": {"issue_id": issue["id"], "company_id": issue.get("company_id", ""),
                          "run_id": issue.get("run_id", "")},
        }, ""

    def handle_event(self, headers: dict, raw_body: bytes) -> tuple[int, dict]:
        problems = self.settings.problems()
        if problems or self.store is None:
            return self._out(503, "bridge_closed", reasons=problems or ["store_missing"])
        now = self.clock()
        if not isinstance(raw_body, (bytes, bytearray)) or len(raw_body) > MAX_BODY_BYTES:
            return self._out(413, "payload_too_large")
        auth = self._authentic(headers, bytes(raw_body), now)
        if auth:
            return self._out(401, auth)
        if not self._rate_ok(now):
            return self._out(429, "rate_limited")
        event, error = self._parse(bytes(raw_body))
        if error:
            return self._out(400, error)
        with self.store.lock:
            state = self.store.load()
            seen = state["events"].get(event["event_id"])
            if seen:
                # Replay (retry, restart, duplicated webhook): same answer, no new work item.
                mapping = state["mappings"].get(seen.get("issue_id"), {})
                return self._out(200, "duplicate_event", mapping=mapping, replay=True)
            return self._apply(state, event, now)

    def _apply(self, state: dict, event: dict, now: float) -> tuple[int, dict]:
        paperclip = event["paperclip"]
        issue_id = paperclip["issue_id"]
        relay_id = event["relay_ticket_id"]
        current = state["mappings"].get(issue_id)
        if current and current["relay"]["relay_ticket_id"] != relay_id:
            return self._out(409, "paperclip_issue_already_mapped")
        for other_issue, other in state["mappings"].items():
            if other_issue != issue_id and other["relay"]["relay_ticket_id"] == relay_id and other["state"] != "cancelled":
                return self._out(409, "double_claim_rejected")   # one Relay ticket <-> one Paperclip issue
        if current and event["occurred_at"] < int(current.get("last_occurred_at") or 0):
            return self._out(409, "stale_event")
        if event["action"] == "cancel":
            if not current:
                return self._out(404, "nothing_to_cancel")
            current.update(state="cancelled", last_occurred_at=event["occurred_at"], updated_at=int(now))
            current["events"] = (current.get("events") or [])[-19:] + [event["event_id"]]
            state["events"][event["event_id"]] = {"issue_id": issue_id, "at": int(now)}
            self.store.save(state)
            # Only the proposal is withdrawn. Relay cancellation stays an owner action in Relay itself.
            return self._out(200, "proposal_cancelled", mapping=current)
        ticket = self.relay_lookup(relay_id)
        if not isinstance(ticket, dict) or str(ticket.get("id") or "").upper() != relay_id:
            return self._out(404, "unknown_relay_ticket")
        owner = _ticket_owner(ticket)
        if owner not in SHARED_LANES and owner != self.settings.expected_owner:
            return self._out(409, "unexpected_task_owner")
        if self.client is not None:
            try:
                if not self.client.issue_exists(issue_id):
                    return self._out(404, "unknown_paperclip_issue")
            except PaperclipUnavailable as exc:
                return self._out(503, "paperclip_unavailable", reason=str(exc))
        mapping = {
            "mapping_id": "pcm-" + hashlib.sha256(issue_id.encode()).hexdigest()[:16],
            "mode": "observe_only",
            "state": "proposed",
            "relay": correlation(ticket, paperclip),
            "last_occurred_at": event["occurred_at"],
            "created_at": int((current or {}).get("created_at") or now),
            "updated_at": int(now),
            "events": ((current or {}).get("events") or [])[-19:] + [event["event_id"]],
        }
        state["mappings"][issue_id] = mapping
        state["events"][event["event_id"]] = {"issue_id": issue_id, "at": int(now)}
        self.store.save(state)
        return self._out(200, "mapping_proposed" if not current else "mapping_refreshed", mapping=mapping)
