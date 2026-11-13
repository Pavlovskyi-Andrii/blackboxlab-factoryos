"""Durable authenticated Claude <-> Codex inbox on the existing Relay JSON store (issue #94, PR #314 hardened).

Messages are bounded collaboration requests: they never claim, run or complete a Relay ticket and never call a
paid API. Security review of PR #314 (blockers 2-6) is answered here:

* identity comes only from two dedicated, strong, distinct bearer tokens (FACTORY_CLAUDE_RELAY_TOKEN,
  FACTORY_CODEX_RELAY_TOKEN); the broad Claude worker token is never accepted; misconfiguration fails closed;
* storage is bounded: acked/dead messages are pruned after RETENTION, each sender has a pending backlog cap and an
  hourly send budget, and the total inbox has a hard cap;
* delivery attempts are bounded: a message whose lease expired MAX_ATTEMPTS times becomes a dead letter instead of
  re-running a model forever; the original records its reply id server-side, so a lost ACK is recovered by lookup,
  not by scanning a short history window;
* every write happens under RelayStore.lock and is saved atomically (tmp + os.replace) by RelayStore; the app runs as
  one uvicorn process (render.yaml), which test_relay_agent_messages pins;
* request bodies are read with a hard byte cap; Authorization must be short printable ASCII;
* bodies carrying anything that looks like a credential are refused, not stored.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets

from fastapi import HTTPException, Request

from agent_secret_scan import contains_secret
from relay_execution import redact

AGENTS = ("claude", "codex")
TOKEN_ENV = {"claude": "FACTORY_CLAUDE_RELAY_TOKEN", "codex": "FACTORY_CODEX_RELAY_TOKEN"}
KINDS = {"question", "review", "answer", "blocker"}
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")
MIN_TOKEN = 32
MAX_HEADER = 512
MAX_BODY_CHARS = 3000
MAX_REVIEW_CHARS = 24000          # a review request carries a (truncated) PR diff
MAX_REQUEST_BYTES = 64 * 1024
LEASE_SECONDS = 180
MAX_ATTEMPTS = 3
RETENTION = timedelta(days=7)
MAX_MESSAGES = 1000
MAX_PENDING_PER_SENDER = 50
MAX_SENDS_PER_HOUR = 60
class AgentRelayError(ValueError):
    def __init__(self, code: str, detail: str = "", status: int = 409):
        super().__init__(detail or code)
        self.code, self.status = code, status


def now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def token_problem(environ=None, forbidden=()) -> str:
    """Empty when both agent tokens are present, strong, distinct and not reused from another credential."""
    env = os.environ if environ is None else environ
    values = {agent: str(env.get(name, "")).strip() for agent, name in TOKEN_ENV.items()}
    for agent, value in values.items():
        if not value:
            return f"{TOKEN_ENV[agent]} is not set"
        if len(value) < MIN_TOKEN or not value.isascii() or not value.isprintable() or " " in value:
            return f"{TOKEN_ENV[agent]} must be at least {MIN_TOKEN} printable ASCII characters"
        if len(set(value)) < 10:
            return f"{TOKEN_ENV[agent]} is too repetitive"
    if values["claude"] == values["codex"]:
        return "Claude and Codex relay tokens must differ"
    reused = {str(x or "").strip() for x in forbidden} - {""}
    if reused & set(values.values()):
        return "Agent relay tokens must not reuse another FactoryOS credential"
    return ""


def agent_identity(request, environ=None, forbidden=()) -> str:
    """'claude' / 'codex' from a dedicated bearer token; '' otherwise. Clients cannot assert their sender."""
    if token_problem(environ, forbidden):
        return ""
    header = request.headers.get("authorization") or ""
    if len(header) > MAX_HEADER or not header.isascii():
        return ""
    scheme, _, supplied = header.strip().partition(" ")
    supplied = supplied.strip()
    if scheme.lower() != "bearer" or not supplied:
        return ""
    env = os.environ if environ is None else environ
    match = ""
    for agent, name in TOKEN_ENV.items():          # compare against both, always, in constant time per token
        if hmac.compare_digest(supplied.encode(), str(env.get(name, "")).strip().encode()):
            match = agent
    return match


def _public(item: dict) -> dict:
    return {k: v for k, v in item.items() if k not in {"claim_token", "acked_token", "payload_fingerprint", "idempotency_key"}}


class RelayAgentMessages:
    """Inbox with leases, ACK, bounded retries, dead letters, retention and same-thread idempotent replies."""

    def __init__(self, relay_store, *, lease_seconds=LEASE_SECONDS, max_messages=MAX_MESSAGES,
                 max_attempts=MAX_ATTEMPTS, retention=RETENTION, max_pending=MAX_PENDING_PER_SENDER,
                 max_per_hour=MAX_SENDS_PER_HOUR, clock=now, known_secrets=lambda: ()):
        self.store = relay_store
        self.known_secrets = known_secrets          # literal credential values that must never appear in a body
        self.lease = timedelta(seconds=max(30, min(600, int(lease_seconds))))
        self.max_messages = max(10, int(max_messages))
        self.max_attempts = max(1, int(max_attempts))
        self.retention = retention
        self.max_pending = max(1, int(max_pending))
        self.max_per_hour = max(1, int(max_per_hour))
        self.clock = clock

    # -- internals (caller holds store.lock) -------------------------------------------------------------------
    def _items(self, state: dict) -> list:
        items = state.get("agent_messages")
        if not isinstance(items, list):
            items = state["agent_messages"] = []
        return items

    def _expire(self, items: list, at: datetime) -> bool:
        """Leases that ran out go back to pending, or to the dead-letter state once attempts are used up."""
        changed = False
        for item in items:
            if item.get("status") != "leased":
                continue
            until = _when(item.get("lease_until"))
            if until and until > at:
                continue
            item["claim_token"], item["lease_until"] = "", ""
            if int(item.get("attempts") or 0) >= self.max_attempts:
                item.update(status="dead", dead_at=at.isoformat(), dead_reason="lease expired %d times" % item["attempts"])
            else:
                item["status"] = "pending"
            changed = True
        return changed

    def _prune(self, items: list, at: datetime) -> bool:
        """Finished messages (acked / dead) leave the store after the retention window; open ones never do."""
        keep = [m for m in items if m.get("status") not in ("acked", "dead")
                or (_when(m.get("ack_at") or m.get("dead_at")) or at) > at - self.retention]
        if len(keep) == len(items):
            return False
        items[:] = keep
        return True

    # -- API ----------------------------------------------------------------------------------------------------
    def send(self, sender, recipient, body, *, kind="question", thread_id="", task_id="", reply_to="",
             idempotency_key=""):
        if sender not in AGENTS or recipient not in AGENTS or sender == recipient:
            raise AgentRelayError("bad_agent", "Invalid sender/recipient", 400)
        if kind not in KINDS:
            raise AgentRelayError("bad_kind", "Invalid message kind", 400)
        body = str(body or "").replace("\x00", "").strip()
        limit = MAX_REVIEW_CHARS if kind == "review" else MAX_BODY_CHARS
        if not body or len(body) > limit:
            raise AgentRelayError("bad_body", f"Message must be 1..{limit} characters", 400)
        for value in (thread_id, task_id, reply_to, idempotency_key):
            if value and not ID_RE.fullmatch(value):
                raise AgentRelayError("bad_id", "Invalid message identifier", 400)
        if not idempotency_key:
            raise AgentRelayError("bad_id", "idempotency_key is required", 400)
        if contains_secret(body) or any(len(v) >= 8 and v in body for v in map(str, self.known_secrets() or ())):
            raise AgentRelayError("secret_detected", "Message looks like it carries a credential; not stored", 422)
        fingerprint = hashlib.sha256(json.dumps([recipient, kind, body, thread_id, task_id, reply_to],
                                                ensure_ascii=False).encode()).hexdigest()
        with self.store.lock:
            state = self.store._load_unlocked()
            items = self._items(state)
            at = self.clock()
            dirty = self._expire(items, at) | self._prune(items, at)
            for existing in items:
                if existing.get("from_agent") == sender and existing.get("idempotency_key") == idempotency_key:
                    if dirty:
                        self.store._save_unlocked(state)
                    if existing.get("payload_fingerprint") != fingerprint:
                        raise AgentRelayError("idempotency_conflict", "idempotency_key reused with different payload")
                    return _public(existing), False
            mine = [m for m in items if m.get("from_agent") == sender]
            refusal = None
            if len(items) >= self.max_messages:
                refusal = AgentRelayError("inbox_full", "Agent inbox at capacity", 429)
            elif sum(m.get("status") in ("pending", "leased") for m in mine) >= self.max_pending:
                refusal = AgentRelayError("backlog_full", "Too many undelivered messages from this agent", 429)
            elif sum((_when(m.get("created_at")) or at) > at - timedelta(hours=1) for m in mine) >= self.max_per_hour:
                refusal = AgentRelayError("rate_limited", "Hourly send budget used", 429)
            previous = None
            if not refusal and reply_to:
                previous = next((m for m in items if m.get("message_id") == reply_to), None)
                if not previous or previous.get("to_agent") != sender or previous.get("from_agent") != recipient:
                    refusal = AgentRelayError("bad_reply", "Invalid reply target")
                elif (thread_id and thread_id != previous["thread_id"]) or (task_id and task_id != previous["task_id"]):
                    refusal = AgentRelayError("bad_reply", "Reply thread/task mismatch")
                elif previous.get("reply_id"):
                    refusal = AgentRelayError("already_replied", "This message already has a reply: " + previous["reply_id"])
                else:
                    thread_id, task_id = previous["thread_id"], previous["task_id"]
            elif not refusal and thread_id and not any(m.get("thread_id") == thread_id and sender in
                                                       (m.get("from_agent"), m.get("to_agent")) for m in items):
                refusal = AgentRelayError("bad_thread", "Unknown thread")
            if refusal:
                if dirty:
                    self.store._save_unlocked(state)
                raise refusal
            item = {
                "message_id": "msg_" + secrets.token_hex(12),
                "thread_id": thread_id or ("th_" + secrets.token_hex(12)), "task_id": task_id, "reply_to": reply_to,
                "from_agent": sender, "to_agent": recipient, "kind": kind,
                "body": redact(body), "created_at": at.isoformat(),
                "status": "pending", "attempts": 0, "lease_until": "", "claimed_at": "",
                "claim_token": "", "ack_at": "", "reply_id": "",
                "idempotency_key": idempotency_key, "payload_fingerprint": fingerprint,
            }
            items.append(item)
            if previous is not None:
                previous["reply_id"] = item["message_id"]          # authoritative: survives any history window
            self.store._save_unlocked(state)
            return _public(item), True

    def claim(self, recipient):
        if recipient not in AGENTS:
            raise AgentRelayError("bad_agent", "Unknown recipient", 400)
        with self.store.lock:
            state = self.store._load_unlocked()
            items = self._items(state)
            at = self.clock()
            dirty = self._expire(items, at) | self._prune(items, at)
            for item in items:
                if item.get("to_agent") != recipient or item.get("status") != "pending":
                    continue
                item.update(status="leased", attempts=int(item.get("attempts") or 0) + 1,
                            claim_token=secrets.token_hex(16), claimed_at=at.isoformat(),
                            lease_until=(at + self.lease).isoformat())
                self.store._save_unlocked(state)
                return {**_public(item), "claim_token": item["claim_token"]}
            if dirty:
                self.store._save_unlocked(state)
        return None

    def ack(self, recipient, message_id, claim_token):
        if recipient not in AGENTS or not message_id or not claim_token:
            raise AgentRelayError("bad_ack", "Invalid ACK", 400)
        with self.store.lock:
            state = self.store._load_unlocked()
            items = self._items(state)
            at = self.clock()
            for item in items:
                if item.get("message_id") != message_id:
                    continue
                if item.get("to_agent") != recipient:
                    raise AgentRelayError("ack_mismatch", "ACK lease mismatch")
                if item.get("status") == "acked":
                    if hmac.compare_digest(str(item.get("acked_token") or ""), str(claim_token)):
                        return _public(item), False
                    raise AgentRelayError("ack_mismatch", "ACK lease mismatch")
                if item.get("status") != "leased" or not hmac.compare_digest(str(item.get("claim_token") or ""), str(claim_token)):
                    raise AgentRelayError("ack_mismatch", "ACK lease mismatch")
                if (_when(item.get("lease_until")) or at) <= at:
                    raise AgentRelayError("lease_expired", "ACK lease expired")
                item.update(status="acked", ack_at=at.isoformat(), acked_token=item["claim_token"],
                            claim_token="", lease_until="")
                self.store._save_unlocked(state)
                return _public(item), True
        raise AgentRelayError("unknown_message", "Unknown message", 404)

    def get(self, agent, message_id):
        with self.store.lock:
            for item in self._items(self.store._load_unlocked()):
                if item.get("message_id") == message_id and agent in (item.get("from_agent"), item.get("to_agent")):
                    return _public(item)
        return None

    def list_for(self, agent, limit=50, thread_id=""):
        if agent not in AGENTS:
            raise AgentRelayError("bad_agent", "Unknown agent", 400)
        with self.store.lock:
            items = self._items(self.store._load_unlocked())
            mine = [_public(m) for m in items if agent in (m.get("to_agent"), m.get("from_agent"))
                    and (not thread_id or m.get("thread_id") == thread_id)]
        return mine[-max(1, min(50, int(limit))):]

    def stats(self):
        """Owner view: counts and dead letters, never bodies."""
        with self.store.lock:
            items = list(self._items(self.store._load_unlocked()))
        counts = {}
        for m in items:
            counts[m.get("status") or "?"] = counts.get(m.get("status") or "?", 0) + 1
        dead = [{k: m.get(k) for k in ("message_id", "thread_id", "from_agent", "to_agent", "kind", "attempts",
                                       "dead_at", "dead_reason")} for m in items if m.get("status") == "dead"]
        last = max((m.get("created_at") or "" for m in items), default="")
        return {"total": len(items), "by_status": counts, "dead_letters": dead[-20:], "last_message_at": last}


async def read_json_capped(request, limit=MAX_REQUEST_BYTES) -> dict:
    """Read at most `limit` bytes, whatever Content-Length claims; 413 above it, 400 for anything not a JSON object."""
    declared = request.headers.get("content-length") or "0"
    if not declared.isdigit() or int(declared) > limit:
        raise HTTPException(413, "Request body too large")
    raw = b""
    async for chunk in request.stream():
        raw += chunk
        if len(raw) > limit:
            raise HTTPException(413, "Request body too large")
    if not raw:
        return {}
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(400, "Body must be UTF-8 JSON")
    if not isinstance(value, dict):
        raise HTTPException(400, "Body must be a JSON object")
    return value


def install_agent_message_routes(app, relay_store, forbidden_tokens=lambda: ()):
    """Agent routes authenticate only with the dedicated relay tokens; /api/relay-agents/status is owner-session."""

    messages = RelayAgentMessages(relay_store, known_secrets=lambda: (
        *forbidden_tokens(), *(os.environ.get(name, "").strip() for name in TOKEN_ENV.values())))

    def guard(request):
        problem = token_problem(forbidden=forbidden_tokens())
        if problem:
            raise HTTPException(503, "Agent relay disabled: " + problem)
        agent = agent_identity(request, forbidden=forbidden_tokens())
        if not agent:
            raise HTTPException(401, "Agent bearer token required")
        return agent

    def fail(exc: AgentRelayError):
        raise HTTPException(exc.status, {"code": exc.code, "detail": str(exc)})

    def text(payload, key, limit=200):
        value = payload.get(key, "")
        if not isinstance(value, str) or len(value) > limit:
            raise HTTPException(400, f"{key} must be a string up to {limit} characters")
        return value

    @app.post("/api/relay/agent/send")
    async def agent_send(request: Request):
        sender = guard(request)
        p = await read_json_capped(request)
        try:
            item, created = messages.send(sender, text(p, "to_agent", 20), text(p, "body", MAX_REVIEW_CHARS * 2),
                                          kind=text(p, "kind", 20) or "question", thread_id=text(p, "thread_id"),
                                          task_id=text(p, "task_id"), reply_to=text(p, "reply_to"),
                                          idempotency_key=text(p, "idempotency_key"))
        except AgentRelayError as exc:
            fail(exc)
        return {"ok": True, "created": created, "message": item}

    @app.post("/api/relay/agent/claim")
    async def agent_claim(request: Request):
        agent = guard(request)
        await read_json_capped(request)
        try:
            return {"ok": True, "message": messages.claim(agent)}
        except AgentRelayError as exc:
            fail(exc)

    @app.post("/api/relay/agent/ack")
    async def agent_ack(request: Request):
        agent = guard(request)
        p = await read_json_capped(request)
        try:
            item, updated = messages.ack(agent, text(p, "message_id"), text(p, "claim_token", 64))
        except AgentRelayError as exc:
            fail(exc)
        return {"ok": True, "updated": updated, "message": item}

    @app.get("/api/relay/agent/messages")
    def agent_messages(request: Request, limit: int = 50, thread_id: str = ""):
        agent = guard(request)
        if thread_id and not ID_RE.fullmatch(thread_id):
            raise HTTPException(400, "Invalid thread id")
        return {"ok": True, "messages": messages.list_for(agent, limit, thread_id)}

    @app.get("/api/relay/agent/messages/{message_id}")
    def agent_message(message_id: str, request: Request):
        agent = guard(request)
        item = messages.get(agent, message_id) if ID_RE.fullmatch(message_id) else None
        if not item:
            raise HTTPException(404, "Unknown message")
        return {"ok": True, "message": item}

    @app.get("/api/relay-agents/status")
    def agent_status():
        problem = token_problem(forbidden=forbidden_tokens())
        return {"ok": True, "enabled": not problem, "problem": problem, **messages.stats()}

    return messages
