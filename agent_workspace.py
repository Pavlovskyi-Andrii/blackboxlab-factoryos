"""T-604 (slice T-625): shared Claude <-> ChatGPT <-> Gemini workspace exposed as tools on the FactoryOS MCP server.

Spec: docs/handoff/T-604_MCP_TOOLS_SPEC.md. What this slice does and does not do:

* FactoryOS Relay stays the single source of truth. Threads, messages and handoffs live in the same Relay JSON store
  (``DATA_DIR/relay.json``, key ``agent_workspace``) under ``RelayStore.lock`` with its atomic save. A handoff claim
  goes through ``RelayQueue.claim_roadmap`` (one ticket per ROADMAP task, fresh run_id), so the EC2 worker and an MCP
  lane can never run the same task at once; result/release/review are journaled on that ticket with
  ``RelayQueue.event``. Handoffs are not plain Relay tickets on purpose: the EC2 worker polls queued tickets.
* Identity comes only from a per-lane credential: ``FACTORY_MCP_LANE_TOKEN_CLAUDE`` / ``_CHATGPT`` / ``_GEMINI``
  (owner-set, T-624). The shared ``FACTORY_MCP_TOKEN`` proves nothing about who calls, so with it the workspace is
  read-only (list_threads / read_thread) and every write or lane-bound tool answers ``LANE_AUTH_REQUIRED``. The server
  derives ``from``; no tool accepts a sender field. A lane token is accepted in ``Authorization: Bearer`` and, only for
  lanes the owner lists in ``FACTORY_MCP_LANE_URL_KEY`` (connector UIs that cannot send headers, e.g. ChatGPT), as the
  ``?key=`` connector URL. Misconfigured tokens (short, repeated, reused) disable that lane, fail closed.
* Every write takes a client ``idempotency_key``; a replay returns the stored answer, a reused key with another payload
  is ``DUPLICATE_CONFLICT``. Bodies that look like credentials are refused, not stored.
* An agent can never write an owner decision (no ``decision`` kind) and cannot approve its own handoff: only the lane
  that created a handoff reviews it. Creating handoffs is limited to ``HANDOFF_CREATORS`` (Claude prepares the
  ChatGPT queue, docs/handoff/CLAUDE_CHATGPT_COORDINATION.md section 1).
* No paid provider call, no model is run: reading a thread is not proof that a model executed anything.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from pathlib import Path

from agent_secret_scan import contains_secret
from relay_execution import TASK_ID_RE, redact

LANES = ("claude", "chatgpt", "gemini")
TOKEN_ENV = {lane: "FACTORY_MCP_LANE_TOKEN_" + lane.upper() for lane in LANES}
URL_KEY_ENV = "FACTORY_MCP_LANE_URL_KEY"
HANDOFF_CREATORS = ("claude",)
REPO = "pavlovskyi-andrii/blackboxlab-factoryos"
POLICY_FILE = Path(__file__).resolve().parent / "docs" / "handoff" / "CLAUDE_CHATGPT_COORDINATION.md"

MIN_TOKEN = 32
MAX_HEADER = 512
MAX_BODY = 4000
MAX_TOPIC = 200
MAX_THREADS = 300
MAX_MESSAGES = 3000
MAX_HANDOFFS = 500
MAX_WRITES_PER_HOUR = 120
LEDGER_RETENTION = timedelta(days=14)
LEASE = timedelta(hours=6)
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
SCOPE_RE = re.compile(r"^[A-Za-z0-9_./*-]{1,200}$")
MESSAGE_KINDS = ("comment", "proposal", "answer", "status", "question")
GITHUB_URL_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/(?:pull|commit|actions/runs)/[A-Za-z0-9]+$")
ACTIVE_HANDOFF = ("claimed", "review")


class WorkspaceError(ValueError):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code, self.message, self.retryable = code, message, retryable

    def payload(self) -> dict:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value):
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


# -- lane authentication ---------------------------------------------------------------------------------------
def lane_status(environ=None, forbidden=()) -> dict:
    """{lane: "" (enabled) | why it is disabled}. Never includes token values."""
    env = os.environ if environ is None else environ
    values = {lane: str(env.get(name, "") or "").strip() for lane, name in TOKEN_ENV.items()}
    reused = {str(x or "").strip() for x in forbidden} - {""}
    result = {}
    for lane, value in values.items():
        name = TOKEN_ENV[lane]
        if not value:
            result[lane] = f"{name} is not set"
        elif len(value) < MIN_TOKEN or not value.isascii() or not value.isprintable() or " " in value:
            result[lane] = f"{name} must be at least {MIN_TOKEN} printable ASCII characters without spaces"
        elif len(set(value)) < 10:
            result[lane] = f"{name} is too repetitive"
        elif any(value == other for o, other in values.items() if o != lane):
            result[lane] = f"{name} must differ from the other lane tokens"
        elif value in reused:
            result[lane] = f"{name} must not reuse another FactoryOS credential"
        else:
            result[lane] = ""
    return result


def url_key_lanes(environ=None) -> set:
    env = os.environ if environ is None else environ
    return {x.strip().lower() for x in str(env.get(URL_KEY_ENV, "") or "").split(",") if x.strip().lower() in LANES}


def lane_identity(request, environ=None, forbidden=()) -> str:
    """'claude' / 'chatgpt' / 'gemini' from a dedicated lane credential, '' otherwise. Constant-time per token."""
    env = os.environ if environ is None else environ
    enabled = [lane for lane, problem in lane_status(env, forbidden).items() if not problem]
    if not enabled:
        return ""
    supplied, via_url = "", False
    header = request.headers.get("authorization") or ""
    if header and len(header) <= MAX_HEADER and header.isascii():
        scheme, _, value = header.strip().partition(" ")
        if scheme.lower() == "bearer":
            supplied = value.strip()
    if not supplied:
        value = (request.query_params.get("key") or "").strip()
        if value and len(value) <= MAX_HEADER and value.isascii():
            supplied, via_url = value, True
    if not supplied:
        return ""
    allowed_by_url = url_key_lanes(env)
    match = ""
    for lane in LANES:                      # compare against every lane token, always
        token = str(env.get(TOKEN_ENV[lane], "") or "").strip()
        if token and hmac.compare_digest(supplied.encode(), token.encode()) and lane in enabled:
            if not via_url or lane in allowed_by_url:
                match = lane
    return match


class _QueryKeyRedactor(logging.Filter):
    """uvicorn's access log prints the request path with its query string; never let a ?key= value reach the log."""
    PATTERN = re.compile(r"((?:^|[?&])(?:key|token)=)[^&\s\"]+", re.IGNORECASE)

    def filter(self, record):
        if isinstance(record.args, tuple):
            record.args = tuple(self.PATTERN.sub(r"\1[REDACTED]", a) if isinstance(a, str) else a for a in record.args)
        return True


def install_access_log_redaction() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _QueryKeyRedactor) for f in logger.filters):
        logger.addFilter(_QueryKeyRedactor())


def policy_sha() -> str:
    try:
        data = POLICY_FILE.read_bytes()
    except OSError:
        data = b""
    return hashlib.sha256(data).hexdigest()[:16]


def _scope_overlaps(a: list, b: list) -> bool:
    def base(p):
        return p.split("*", 1)[0].rstrip("/")
    for x in a:
        for y in b:
            bx, by = base(x), base(y)
            if not bx or not by or bx == by or bx.startswith(by + "/") or by.startswith(bx + "/"):
                return True
    return False


# -- the workspace -----------------------------------------------------------------------------------------------
class AgentWorkspace:
    def __init__(self, relay_store, relay_queue, *, known_secrets=lambda: (), clock=_now, lease=LEASE,
                 max_writes_per_hour=MAX_WRITES_PER_HOUR, policy=policy_sha):
        self.store, self.queue = relay_store, relay_queue
        self.known_secrets, self.clock, self.lease = known_secrets, clock, lease
        self.max_writes_per_hour, self.policy = max(1, int(max_writes_per_hour)), policy

    # internals; the caller holds store.lock
    def _ws(self, state: dict) -> dict:
        ws = state.get("agent_workspace")
        if not isinstance(ws, dict):
            ws = state["agent_workspace"] = {}
        for key in ("threads", "messages", "handoffs", "writes"):
            if not isinstance(ws.get(key), list):
                ws[key] = []
        return ws

    def _clean_text(self, value, limit: int, field: str, required: bool = True) -> str:
        text = str(value or "").replace("\x00", "").strip()
        if required and not text:
            raise WorkspaceError("INVALID_ARGUMENT", f"{field} is required")
        if len(text) > limit:
            raise WorkspaceError("LENGTH_EXCEEDED", f"{field} must be at most {limit} characters")
        if contains_secret(text) or any(len(s) >= 8 and s in text for s in map(str, self.known_secrets() or ())):
            raise WorkspaceError("SECRET_DETECTED", f"{field} looks like it carries a credential; not stored")
        return redact(text)

    @staticmethod
    def _id(value, field: str, required: bool = True) -> str:
        value = str(value or "").strip()
        if not value:
            if required:
                raise WorkspaceError("INVALID_ARGUMENT", f"{field} is required")
            return ""
        if not ID_RE.fullmatch(value):
            raise WorkspaceError("INVALID_ARGUMENT", f"{field} has an invalid format")
        return value

    def _write(self, lane: str, tool: str, key: str, payload: dict, apply):
        """Idempotent, rate-limited, atomic write. ``apply(ws, at)`` returns the response or raises WorkspaceError."""
        if lane not in LANES:
            raise WorkspaceError("LANE_AUTH_REQUIRED", "This tool needs a per-lane FactoryOS credential")
        key = self._id(key, "idempotency_key")
        fingerprint = hashlib.sha256(json.dumps([tool, payload], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        with self.store.lock:
            state = self.store._load_unlocked()
            ws = self._ws(state)
            at = self.clock()
            ws["writes"] = [w for w in ws["writes"] if (_when(w.get("at")) or at) > at - LEDGER_RETENTION]
            for w in ws["writes"]:
                if w.get("lane") == lane and w.get("key") == key:
                    if w.get("fingerprint") != fingerprint:
                        raise WorkspaceError("DUPLICATE_CONFLICT", "idempotency_key was already used with another payload")
                    return {**w["response"], "idempotent_replay": True}
            recent = sum(1 for w in ws["writes"] if w.get("lane") == lane
                         and (_when(w.get("at")) or at) > at - timedelta(hours=1))
            if recent >= self.max_writes_per_hour:
                raise WorkspaceError("RATE_LIMITED", "Hourly write budget for this lane is used", retryable=True)
            response = apply(state, ws, at)
            response = {**response, "event_id": "ev_" + secrets.token_hex(8), "at": at.isoformat()}
            ws["writes"].append({"lane": lane, "key": key, "tool": tool, "fingerprint": fingerprint,
                                 "at": at.isoformat(), "response": response})
            self.store._save_unlocked(state)
            return {**response, "idempotent_replay": False}

    # threads ----------------------------------------------------------------------------------------------------
    def post_message(self, lane: str, args: dict) -> dict:
        thread_id = self._id(args.get("thread_id"), "thread_id", required=False)
        kind = str(args.get("kind") or "comment").strip().lower()
        if kind not in MESSAGE_KINDS:
            raise WorkspaceError("INVALID_ARGUMENT", "kind must be one of " + ", ".join(MESSAGE_KINDS) +
                                 " (owner decisions cannot be written by an agent)")
        body = self._clean_text(args.get("body"), MAX_BODY, "body")
        topic = "" if thread_id else self._clean_text(args.get("topic"), MAX_TOPIC, "topic (for a new thread)")
        reply_to = self._id(args.get("reply_to"), "reply_to", required=False)
        payload = {"thread_id": thread_id, "kind": kind, "body": body, "topic": topic, "reply_to": reply_to}

        def apply(state, ws, at):
            nonlocal thread_id
            if thread_id:
                thread = next((t for t in ws["threads"] if t.get("thread_id") == thread_id), None)
                if not thread:
                    raise WorkspaceError("THREAD_NOT_FOUND", "Unknown thread_id")
                if thread.get("status") != "open":
                    raise WorkspaceError("THREAD_CLOSED", "The thread is " + str(thread.get("status")))
            else:
                if len(ws["threads"]) >= MAX_THREADS:
                    raise WorkspaceError("RATE_LIMITED", "Thread store is full; the owner must archive threads")
                thread_id = "th_" + secrets.token_hex(8)
                thread = {"thread_id": thread_id, "topic": topic, "status": "open", "origin": "mcp",
                          "created_by": lane, "created_at": at.isoformat(), "last_message_id": "", "message_count": 0}
                ws["threads"].append(thread)
            if reply_to and not any(m.get("message_id") == reply_to and m.get("thread_id") == thread_id
                                    for m in ws["messages"]):
                raise WorkspaceError("INVALID_ARGUMENT", "reply_to is not a message of this thread")
            if len(ws["messages"]) >= MAX_MESSAGES:
                raise WorkspaceError("RATE_LIMITED", "Message store is full; the owner must archive threads")
            message = {"message_id": "msg_" + secrets.token_hex(8), "thread_id": thread_id, "from": lane,
                       "kind": kind, "body": body, "reply_to": reply_to, "at": at.isoformat(),
                       "actor_auth_subject": "mcp-lane:" + lane, "visibility": "owner_team"}
            ws["messages"].append(message)
            thread["last_message_id"] = message["message_id"]
            thread["message_count"] = int(thread.get("message_count") or 0) + 1
            thread["updated_at"] = at.isoformat()
            return {"message_id": message["message_id"], "thread_id": thread_id}

        return self._write(lane, "post_message", args.get("idempotency_key"), payload, apply)

    def list_threads(self, args: dict) -> dict:
        limit = max(1, min(100, int(args.get("limit") or 20)))
        with self.store.lock:
            ws = self._ws(self.store._load_unlocked())
            threads = [dict(t) for t in ws["threads"]]
        threads.sort(key=lambda t: t.get("updated_at") or t.get("created_at") or "", reverse=True)
        return {"threads": threads[:limit], "total": len(threads)}

    def read_thread(self, args: dict) -> dict:
        thread_id = self._id(args.get("thread_id"), "thread_id")
        after = self._id(args.get("after_message_id"), "after_message_id", required=False)
        limit = max(1, min(100, int(args.get("limit") or 50)))
        with self.store.lock:
            ws = self._ws(self.store._load_unlocked())
            thread = next((dict(t) for t in ws["threads"] if t.get("thread_id") == thread_id), None)
            messages = [dict(m) for m in ws["messages"] if m.get("thread_id") == thread_id]
        if not thread:
            raise WorkspaceError("THREAD_NOT_FOUND", "Unknown thread_id")
        if after:
            index = next((i for i, m in enumerate(messages) if m["message_id"] == after), None)
            if index is None:
                raise WorkspaceError("CURSOR_INVALID", "after_message_id is not in this thread")
            messages = messages[index + 1:]
        page = messages[:limit]
        result = {"thread": thread, "messages": page, "policy_sha": self.policy(),
                  "note": "Messages are what each lane posted; reading them is not proof that a model ran."}
        if len(messages) > limit:
            result["next_cursor"] = page[-1]["message_id"]
        return result

    # handoffs ---------------------------------------------------------------------------------------------------
    @staticmethod
    def _public_handoff(h: dict) -> dict:
        return {k: v for k, v in h.items() if k != "history"} | {"history": list(h.get("history") or [])[-10:]}

    def _expire(self, ws: dict, at: datetime) -> None:
        for h in ws["handoffs"]:
            if h.get("state") == "claimed" and (_when(h.get("lease_expires_at")) or at) <= at:
                h["state"] = "blocked"
                h.setdefault("history", []).append({"at": at.isoformat(), "by": "server", "action": "lease_expired",
                                                    "run_id": h.get("run_id")})

    def create_handoff(self, lane: str, args: dict) -> dict:
        if lane in LANES and lane not in HANDOFF_CREATORS:
            raise WorkspaceError("NOT_PERMITTED", "Only " + ", ".join(HANDOFF_CREATORS) + " can create handoffs")
        to = str(args.get("to") or "").strip().lower()
        if to not in LANES or to == lane:
            raise WorkspaceError("INVALID_ARGUMENT", "to must be another lane: " + ", ".join(LANES))
        task_id = str(args.get("task_id") or "").strip()
        if not TASK_ID_RE.fullmatch(task_id):
            raise WorkspaceError("INVALID_ARGUMENT", "task_id must be a ROADMAP id like T-123")
        objective = self._clean_text(args.get("objective"), MAX_BODY, "objective")
        done = [self._clean_text(x, 500, "done item") for x in (args.get("done") or [])][:20]
        if not done:
            raise WorkspaceError("INVALID_ARGUMENT", "done needs at least one acceptance criterion")
        scope = [str(x).strip() for x in (args.get("files_scope") or [])][:50]
        if not scope or any(not SCOPE_RE.fullmatch(x) or ".." in x for x in scope):
            raise WorkspaceError("INVALID_ARGUMENT", "files_scope needs 1..50 repository paths")
        depends = [self._id(x, "depends item") for x in (args.get("depends") or [])][:20]
        thread_id = self._id(args.get("thread_id"), "thread_id", required=False)
        priority = str(args.get("priority") or "P2").strip().upper()
        if priority not in ("P0", "P1", "P2", "P3"):
            raise WorkspaceError("INVALID_ARGUMENT", "priority must be P0..P3")
        payload = {"to": to, "task_id": task_id, "objective": objective, "done": done, "files_scope": scope,
                   "depends": depends, "thread_id": thread_id, "priority": priority}

        def apply(state, ws, at):
            if len(ws["handoffs"]) >= MAX_HANDOFFS:
                raise WorkspaceError("RATE_LIMITED", "Handoff store is full")
            if thread_id and not any(t.get("thread_id") == thread_id for t in ws["threads"]):
                raise WorkspaceError("THREAD_NOT_FOUND", "Unknown thread_id")
            if any(h.get("task_id") == task_id and h.get("state") in ("queued",) + ACTIVE_HANDOFF for h in ws["handoffs"]):
                raise WorkspaceError("CLAIM_CONFLICT", f"{task_id} already has an open handoff")
            handoff = {"handoff_id": "ho_" + secrets.token_hex(8), "task_id": task_id, "thread_id": thread_id,
                       "from": lane, "to": to, "priority": priority, "depends": depends, "files_scope": scope,
                       "objective": objective, "done": done, "state": "queued", "run_id": "", "relay_ticket_id": "",
                       "lease_expires_at": "", "artifacts": [], "checks": [], "summary": "",
                       "created_at": at.isoformat(), "updated_at": at.isoformat(),
                       "history": [{"at": at.isoformat(), "by": lane, "action": "created"}]}
            ws["handoffs"].append(handoff)
            return {"handoff_id": handoff["handoff_id"], "state": "queued"}

        return self._write(lane, "create_handoff", args.get("idempotency_key"), payload, apply)

    def list_handoffs(self, lane: str, args: dict) -> dict:
        if lane not in LANES:
            raise WorkspaceError("LANE_AUTH_REQUIRED", "list_handoffs is bound to a per-lane credential")
        wanted = str(args.get("state") or "all").strip().lower()
        if wanted not in ("all", "queued", "claimed", "review", "blocked", "done", "released"):
            raise WorkspaceError("INVALID_ARGUMENT", "Unknown state filter")
        limit = max(1, min(100, int(args.get("limit") or 50)))
        with self.store.lock:
            state = self.store._load_unlocked()
            ws = self._ws(state)
            self._expire(ws, self.clock())
            items = [self._public_handoff(h) for h in ws["handoffs"] if lane in (h.get("to"), h.get("from"))]
        if wanted != "all":
            items = [h for h in items if h.get("state") == wanted]
        items.sort(key=lambda h: (h.get("priority") or "P9", h.get("created_at") or ""))
        return {"lane": lane, "items": items[:limit], "policy_sha": self.policy()}

    def _find(self, ws: dict, handoff_id: str) -> dict:
        handoff = next((h for h in ws["handoffs"] if h.get("handoff_id") == handoff_id), None)
        if not handoff:
            raise WorkspaceError("HANDOFF_NOT_FOUND", "Unknown handoff_id")
        return handoff

    def claim_handoff(self, lane: str, args: dict) -> dict:
        handoff_id = self._id(args.get("handoff_id"), "handoff_id")
        sha = str(args.get("policy_sha") or "").strip()
        payload = {"handoff_id": handoff_id, "policy_sha": sha}

        def apply(state, ws, at):
            self._expire(ws, at)
            handoff = self._find(ws, handoff_id)
            if handoff.get("to") != lane:
                raise WorkspaceError("NOT_ASSIGNED", "This handoff is assigned to another lane")
            if not sha or not hmac.compare_digest(sha, self.policy()):
                raise WorkspaceError("POLICY_STALE", "Re-read the coordination rules; policy_sha is " + self.policy())
            if handoff.get("state") != "queued":
                raise WorkspaceError("CLAIM_CONFLICT", "Handoff is " + str(handoff.get("state")))
            for dep in handoff.get("depends") or []:
                other = next((h for h in ws["handoffs"] if dep in (h.get("handoff_id"), h.get("task_id"))), None)
                if not other or other.get("state") != "done":
                    raise WorkspaceError("DEPENDENCY_PENDING", f"Dependency {dep} is not done", retryable=True)
            for other in ws["handoffs"]:
                if other is not handoff and other.get("state") in ACTIVE_HANDOFF and \
                        _scope_overlaps(other.get("files_scope") or [], handoff.get("files_scope") or []):
                    raise WorkspaceError("CLAIM_CONFLICT", "files_scope overlaps active handoff " + other["handoff_id"])
            # The atomic single claim of record is the Relay ROADMAP ticket; the store lock is re-entrant.
            ticket, reason = self.queue.claim_roadmap("mcp-" + lane, lane, handoff["task_id"],
                                                      title=handoff["objective"][:120], owner=lane)
            if not ticket:
                raise WorkspaceError("CLAIM_CONFLICT", reason or "Relay refused the claim")
            self._reload_into(state, ws)
            handoff = self._find(ws, handoff_id)
            run_id = str((ticket.get("execution") or {}).get("run_id") or "")
            handoff.update(state="claimed", run_id=run_id, relay_ticket_id=ticket["id"],
                           lease_expires_at=(at + self.lease).isoformat(), updated_at=at.isoformat())
            handoff.setdefault("history", []).append({"at": at.isoformat(), "by": lane, "action": "claimed",
                                                      "run_id": run_id})
            return {"handoff_id": handoff_id, "run_id": run_id, "relay_ticket_id": ticket["id"],
                    "lease_expires_at": handoff["lease_expires_at"], "files_scope": handoff["files_scope"]}

        return self._write(lane, "claim_handoff", args.get("idempotency_key"), payload, apply)

    def _active_run(self, ws, lane, handoff_id, run_id, at, states=("claimed",)) -> dict:
        self._expire(ws, at)
        handoff = self._find(ws, handoff_id)
        if handoff.get("to") != lane:
            raise WorkspaceError("NOT_ASSIGNED", "This handoff is assigned to another lane")
        if not run_id or not hmac.compare_digest(str(run_id), str(handoff.get("run_id") or "")):
            raise WorkspaceError("RUN_ID_MISMATCH", "run_id does not match the active claim")
        if handoff.get("state") == "blocked" and any(x.get("action") == "lease_expired" for x in handoff.get("history") or []):
            raise WorkspaceError("LEASE_EXPIRED", "The claim lease expired; the owner must re-queue the handoff")
        if handoff.get("state") not in states:
            raise WorkspaceError("CONFLICT", "Handoff is " + str(handoff.get("state")))
        return handoff

    def _relay_event(self, handoff: dict, lane: str, stage: str, note: str, evidence: dict, event_id: str) -> None:
        try:
            self.queue.event(handoff["relay_ticket_id"], "mcp-" + lane, stage, note, evidence,
                             run_id=handoff.get("run_id") or "", event_id=event_id)
        except (KeyError, ValueError) as exc:
            raise WorkspaceError("CONFLICT", "Relay ticket refused the event: " + str(exc)[:160]) from exc

    def submit_handoff_result(self, lane: str, args: dict) -> dict:
        handoff_id = self._id(args.get("handoff_id"), "handoff_id")
        run_id = self._id(args.get("run_id"), "run_id")
        summary = self._clean_text(args.get("summary"), MAX_BODY, "summary")
        urls = [str(u).strip() for u in (args.get("artifact_urls") or [])][:10]
        if not urls:
            raise WorkspaceError("ARTIFACT_INVALID", "artifact_urls needs at least one GitHub PR/commit/run URL")
        for url in urls:
            match = GITHUB_URL_RE.fullmatch(url)
            if not match or match.group(1).lower() != REPO:
                raise WorkspaceError("ARTIFACT_INVALID", "Only " + REPO + " pull/commit/actions URLs are accepted")
        checks = []
        for check in (args.get("checks") or [])[:30]:
            if not isinstance(check, dict) or check.get("status") not in ("pass", "fail", "not_run"):
                raise WorkspaceError("INVALID_ARGUMENT", "checks items need name and status pass/fail/not_run")
            checks.append({"name": self._clean_text(check.get("name"), 200, "check name"), "status": check["status"],
                           "evidence": self._clean_text(check.get("evidence"), 500, "check evidence", required=False)})
        payload = {"handoff_id": handoff_id, "run_id": run_id, "summary": summary, "urls": urls, "checks": checks}

        def apply(state, ws, at):
            handoff = self._active_run(ws, lane, handoff_id, run_id, at)
            pr = next((u for u in urls if "/pull/" in u), "")
            evidence = {"pr_url": pr} if pr else {"artifact_url": urls[0]}
            self._relay_event(handoff, lane, "pushed", "MCP handoff result: " + summary[:300], evidence,
                              "ho-result-" + handoff_id + "-" + run_id)
            self._reload_into(state, ws)
            handoff = self._find(ws, handoff_id)
            handoff.update(state="review", summary=summary, artifacts=urls, checks=checks, updated_at=at.isoformat())
            handoff.setdefault("history", []).append({"at": at.isoformat(), "by": lane, "action": "submitted",
                                                      "run_id": run_id})
            return {"handoff_id": handoff_id, "state": "review",
                    "note": "Submitted for review by " + handoff["from"] + "; not merged, not done."}

        return self._write(lane, "submit_handoff_result", args.get("idempotency_key"), payload, apply)

    def release_handoff(self, lane: str, args: dict) -> dict:
        handoff_id = self._id(args.get("handoff_id"), "handoff_id")
        run_id = self._id(args.get("run_id"), "run_id")
        reason = str(args.get("reason") or "").strip()
        if reason not in ("blocked", "cancelled"):
            raise WorkspaceError("NOT_PERMITTED", "reason must be blocked or cancelled (reassignment is owner-only)")
        notes = self._clean_text(args.get("notes"), 1000, "notes", required=False)
        payload = {"handoff_id": handoff_id, "run_id": run_id, "reason": reason, "notes": notes}

        def apply(state, ws, at):
            handoff = self._active_run(ws, lane, handoff_id, run_id, at, states=("claimed", "review"))
            self._relay_event(handoff, lane, "blocked", f"MCP handoff {reason}: {notes}"[:400], {},
                              "ho-release-" + handoff_id + "-" + run_id)
            self._reload_into(state, ws)
            handoff = self._find(ws, handoff_id)
            new_state = "blocked" if reason == "blocked" else "released"
            handoff.update(state=new_state, updated_at=at.isoformat())
            handoff.setdefault("history", []).append({"at": at.isoformat(), "by": lane, "action": reason,
                                                      "run_id": run_id, "notes": notes})
            return {"handoff_id": handoff_id, "state": new_state}

        return self._write(lane, "release_handoff", args.get("idempotency_key"), payload, apply)

    def review_handoff(self, lane: str, args: dict) -> dict:
        handoff_id = self._id(args.get("handoff_id"), "handoff_id")
        verdict = str(args.get("verdict") or "").strip()
        if verdict not in ("accept", "changes_requested"):
            raise WorkspaceError("INVALID_ARGUMENT", "verdict must be accept or changes_requested")
        notes = self._clean_text(args.get("notes"), 2000, "notes", required=False)
        payload = {"handoff_id": handoff_id, "verdict": verdict, "notes": notes}

        def apply(state, ws, at):
            handoff = self._find(ws, handoff_id)
            if handoff.get("from") != lane:
                raise WorkspaceError("NOT_PERMITTED", "Only the lane that created the handoff reviews it")
            if handoff.get("state") != "review":
                raise WorkspaceError("CONFLICT", "Handoff is " + str(handoff.get("state")))
            if verdict == "accept":
                # The executing lane's claim ends; the Relay ticket closes only once its evidence is proven.
                worker = "mcp-" + str(handoff.get("to"))
                try:
                    self.queue.event(handoff["relay_ticket_id"], worker, "done", "Reviewed and accepted by " + lane,
                                     {}, run_id=handoff.get("run_id") or "", event_id="ho-accept-" + handoff_id)
                except (KeyError, ValueError) as exc:
                    raise WorkspaceError("CONFLICT", "Relay ticket refused the event: " + str(exc)[:160]) from exc
                self._reload_into(state, ws)
                handoff = self._find(ws, handoff_id)
                handoff["state"] = "done"
            else:
                handoff.update(state="claimed", lease_expires_at=(at + self.lease).isoformat())
            handoff["updated_at"] = at.isoformat()
            handoff.setdefault("history", []).append({"at": at.isoformat(), "by": lane, "action": verdict,
                                                      "notes": notes})
            return {"handoff_id": handoff_id, "state": handoff["state"]}

        return self._write(lane, "review_handoff", args.get("idempotency_key"), payload, apply)

    def _reload_into(self, state: dict, ws: dict) -> None:
        """A RelayQueue call saved its own snapshot under the same (re-entrant) lock; continue from that snapshot."""
        fresh = self.store._load_unlocked()
        state.clear()
        state.update(fresh)
        ws2 = self._ws(state)
        ws.clear()
        ws.update(ws2)
        state["agent_workspace"] = ws

    def overview(self) -> dict:
        """Owner read view (Worker Center): counts plus the latest threads and handoffs."""
        with self.store.lock:
            ws = self._ws(self.store._load_unlocked())
            threads = [dict(t) for t in ws["threads"]]
            handoffs = [self._public_handoff(h) for h in ws["handoffs"]]
        threads.sort(key=lambda t: t.get("updated_at") or t.get("created_at") or "", reverse=True)
        handoffs.sort(key=lambda h: h.get("updated_at") or "", reverse=True)
        states = {}
        for h in handoffs:
            states[h.get("state")] = states.get(h.get("state"), 0) + 1
        return {"threads": threads[:20], "handoffs": handoffs[:30], "handoff_states": states}


# -- MCP surface -------------------------------------------------------------------------------------------------
_IDEM = {"type": "string", "description": "Client-generated unique key for this write; a retry with the same key "
                                          "and payload returns the stored answer."}
TOOLS = [
    {"name": "post_message",
     "description": "Post to a shared FactoryOS Relay thread (Claude / ChatGPT / Gemini brainstorm, visible to the "
                    "owner). The sender is taken from your lane credential. Omit thread_id and give a topic to open a "
                    "new thread. Agents cannot write owner decisions. Needs a per-lane token.",
     "inputSchema": {"type": "object", "properties": {
         "thread_id": {"type": "string"}, "topic": {"type": "string", "maxLength": MAX_TOPIC},
         "body": {"type": "string", "maxLength": MAX_BODY}, "kind": {"type": "string", "enum": list(MESSAGE_KINDS)},
         "reply_to": {"type": "string"}, "idempotency_key": _IDEM},
         "required": ["body", "idempotency_key"], "additionalProperties": False}},
    {"name": "list_threads",
     "description": "List shared FactoryOS Relay threads, newest first.",
     "inputSchema": {"type": "object", "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 100}},
                     "additionalProperties": False}},
    {"name": "read_thread",
     "description": "Read messages of a shared thread in order (paginate with after_message_id). Reading is not "
                    "proof that any model executed anything.",
     "inputSchema": {"type": "object", "properties": {
         "thread_id": {"type": "string"}, "after_message_id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}},
         "required": ["thread_id"], "additionalProperties": False}},
    {"name": "create_handoff",
     "description": "Hand a bounded ROADMAP task to another lane (Claude only). Needs task_id, objective, done "
                    "criteria and files_scope. Needs a per-lane token.",
     "inputSchema": {"type": "object", "properties": {
         "to": {"type": "string", "enum": list(LANES)}, "task_id": {"type": "string"},
         "objective": {"type": "string", "maxLength": MAX_BODY}, "done": {"type": "array", "items": {"type": "string"}},
         "files_scope": {"type": "array", "items": {"type": "string"}},
         "depends": {"type": "array", "items": {"type": "string"}}, "thread_id": {"type": "string"},
         "priority": {"type": "string", "enum": ["P0", "P1", "P2", "P3"]}, "idempotency_key": _IDEM},
         "required": ["to", "task_id", "objective", "done", "files_scope", "idempotency_key"],
         "additionalProperties": False}},
    {"name": "list_handoffs",
     "description": "Handoffs for your lane (assigned to you or created by you) plus the current policy_sha needed "
                    "to claim. Needs a per-lane token.",
     "inputSchema": {"type": "object", "properties": {
         "state": {"type": "string", "enum": ["all", "queued", "claimed", "review", "blocked", "done", "released"]},
         "limit": {"type": "integer", "minimum": 1, "maximum": 100}}, "additionalProperties": False}},
    {"name": "claim_handoff",
     "description": "Atomically claim a queued handoff assigned to your lane. Returns run_id and lease. Fails on "
                    "stale policy_sha, pending dependencies, overlapping files_scope or an active Relay claim.",
     "inputSchema": {"type": "object", "properties": {
         "handoff_id": {"type": "string"}, "policy_sha": {"type": "string"}, "idempotency_key": _IDEM},
         "required": ["handoff_id", "policy_sha", "idempotency_key"], "additionalProperties": False}},
    {"name": "submit_handoff_result",
     "description": "Submit the result of your claimed handoff for review: summary, GitHub PR/commit URLs of this "
                    "repository and checks. Moves it to review, never to merged/done.",
     "inputSchema": {"type": "object", "properties": {
         "handoff_id": {"type": "string"}, "run_id": {"type": "string"}, "summary": {"type": "string"},
         "artifact_urls": {"type": "array", "items": {"type": "string"}},
         "checks": {"type": "array", "items": {"type": "object", "properties": {
             "name": {"type": "string"}, "status": {"type": "string", "enum": ["pass", "fail", "not_run"]},
             "evidence": {"type": "string"}}, "required": ["name", "status"]}},
         "idempotency_key": _IDEM},
         "required": ["handoff_id", "run_id", "summary", "artifact_urls", "idempotency_key"],
         "additionalProperties": False}},
    {"name": "release_handoff",
     "description": "Give back your claimed handoff as blocked or cancelled (with notes), so it is not run twice.",
     "inputSchema": {"type": "object", "properties": {
         "handoff_id": {"type": "string"}, "run_id": {"type": "string"},
         "reason": {"type": "string", "enum": ["blocked", "cancelled"]}, "notes": {"type": "string"},
         "idempotency_key": _IDEM},
         "required": ["handoff_id", "run_id", "reason", "idempotency_key"], "additionalProperties": False}},
    {"name": "review_handoff",
     "description": "Accept a submitted handoff or request changes (only the lane that created it).",
     "inputSchema": {"type": "object", "properties": {
         "handoff_id": {"type": "string"}, "verdict": {"type": "string", "enum": ["accept", "changes_requested"]},
         "notes": {"type": "string"}, "idempotency_key": _IDEM},
         "required": ["handoff_id", "verdict", "idempotency_key"], "additionalProperties": False}},
]
TOOL_NAMES = {t["name"] for t in TOOLS}
READ_ONLY = {"list_threads", "read_thread"}


def call_tool(workspace: AgentWorkspace, name: str, args: dict, lane: str) -> dict:
    """Runs one tool. Domain problems come back as {"error": {...}} so the MCP layer can set isError."""
    if not isinstance(args, dict):
        args = {}
    try:
        if name not in READ_ONLY and lane not in LANES:
            raise WorkspaceError("LANE_AUTH_REQUIRED",
                                 "This tool needs a per-lane FactoryOS credential (the shared MCP token only reads "
                                 "threads). The owner sets " + ", ".join(TOKEN_ENV.values()) + ".")
        if name == "post_message":
            return workspace.post_message(lane, args)
        if name == "list_threads":
            return workspace.list_threads(args)
        if name == "read_thread":
            return workspace.read_thread(args)
        if name == "create_handoff":
            return workspace.create_handoff(lane, args)
        if name == "list_handoffs":
            return workspace.list_handoffs(lane, args)
        if name == "claim_handoff":
            return workspace.claim_handoff(lane, args)
        if name == "submit_handoff_result":
            return workspace.submit_handoff_result(lane, args)
        if name == "release_handoff":
            return workspace.release_handoff(lane, args)
        if name == "review_handoff":
            return workspace.review_handoff(lane, args)
        raise WorkspaceError("UNKNOWN_TOOL", "Unknown workspace tool")
    except WorkspaceError as exc:
        return {"error": exc.payload()}
    except (TypeError, ValueError) as exc:
        return {"error": {"code": "INVALID_ARGUMENT", "message": str(exc)[:200], "retryable": False}}


def install_routes(app, workspace: AgentWorkspace, lanes_status) -> None:
    """Owner read view for Worker Center; the session middleware already requires a signed-in owner for /api/."""

    @app.get("/api/factory/agent-workspace")
    def agent_workspace_overview():
        status = lanes_status()
        return {**workspace.overview(),
                "lanes": {lane: {"enabled": not problem, "problem": problem} for lane, problem in status.items()},
                "url_key_lanes": sorted(url_key_lanes()), "policy_sha": workspace.policy()}
