"""Durable authenticated Claude <-> Codex inbox, on the existing Relay JSON store.

No second queue for task execution. Messages are bounded collaboration requests;
they never claim, run, or complete a Relay ticket. No API billing is used here.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
import re
import secrets

from relay_execution import redact

AGENTS = {"claude", "codex"}
KINDS = {"question", "review", "answer", "blocker"}
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


def now():
    return datetime.now(timezone.utc)


def agent_identity(request, authorize_claude):
    """Bearer token determines source; clients cannot self-assert their sender."""
    header = (request.headers.get("authorization") or "").strip()
    if not header.lower().startswith("bearer "):
        return ""
    supplied = header.split(" ", 1)[1].strip()
    codex_token = os.environ.get("FACTORY_CODEX_RELAY_TOKEN", "").strip()
    if supplied and codex_token and hmac.compare_digest(supplied, codex_token):
        return "codex"
    if supplied and authorize_claude and authorize_claude(request):
        return "claude"
    return ""


def _public(item):
    return {k: v for k, v in item.items()
            if k not in {"claim_token", "payload_fingerprint", "idempotency_key"}}


class RelayAgentMessages:
    """Persistent atomic inbox, leases, ACK and same-thread idempotent replies."""

    def __init__(self, relay_store, lease_seconds=180, max_messages=1000):
        self.store = relay_store
        self.lease_seconds = max(60, min(600, int(lease_seconds)))
        self.max_messages = max(10, int(max_messages))

    def send(self, sender, recipient, body, *, kind="question", thread_id="",
             task_id="", reply_to="", idempotency_key=""):
        if sender not in AGENTS or recipient not in AGENTS or sender == recipient:
            raise ValueError("Invalid sender/recipient")
        if kind not in KINDS:
            raise ValueError("Invalid message kind")
        body = str(body or "").strip()
        if not body or len(body) > 3000:
            raise ValueError("Message must be 1..3000 characters")
        for value in (thread_id, task_id, reply_to, idempotency_key):
            if value and not ID_RE.fullmatch(value):
                raise ValueError("Invalid message identifier")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        payload = [recipient, kind, body, thread_id, task_id, reply_to]
        fingerprint = hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()
        with self.store.lock:
            state = self.store._load_unlocked()
            items = state.setdefault("agent_messages", [])
            for existing in items:
                if existing["from_agent"] == sender and existing["idempotency_key"] == idempotency_key:
                    if existing["payload_fingerprint"] != fingerprint:
                        raise ValueError("idempotency_key reused with different payload")
                    return _public(existing), False
            if len(items) >= self.max_messages:
                raise ValueError("Agent inbox at capacity")
            if reply_to:
                previous = next((m for m in items if m["message_id"] == reply_to), None)
                if (not previous or previous["to_agent"] != sender
                        or previous["from_agent"] != recipient):
                    raise ValueError("Invalid reply target")
                if thread_id and thread_id != previous["thread_id"]:
                    raise ValueError("Reply thread mismatch")
                if task_id and task_id != previous["task_id"]:
                    raise ValueError("Reply task mismatch")
                thread_id = previous["thread_id"]
                task_id = previous["task_id"]
            elif thread_id and not any(m["thread_id"] == thread_id and sender in
                                       (m["from_agent"], m["to_agent"]) for m in items):
                raise ValueError("Unknown thread")
            thread_id = thread_id or ("th_" + secrets.token_hex(12))
            item = {
                "message_id": "msg_" + secrets.token_hex(12),
                "thread_id": thread_id, "task_id": task_id, "reply_to": reply_to,
                "from_agent": sender, "to_agent": recipient, "kind": kind,
                "body": redact(body), "created_at": now().isoformat(),
                "status": "pending", "attempts": 0, "lease_until": "",
                "claim_token": "", "ack_at": "", "idempotency_key": idempotency_key,
                "payload_fingerprint": fingerprint,
            }
            items.append(item)
            self.store._save_unlocked(state)
            return _public(item), True

    def claim(self, recipient):
        if recipient not in AGENTS:
            raise ValueError("Unknown recipient")
        with self.store.lock:
            state = self.store._load_unlocked()
            for item in state.setdefault("agent_messages", []):
                if item["to_agent"] != recipient:
                    continue
                expired = False
                if item["status"] == "leased":
                    try:
                        expired = datetime.fromisoformat(item["lease_until"]) <= now()
                    except (ValueError, TypeError):
                        expired = True
                if item["status"] != "pending" and not expired:
                    continue
                item["status"] = "leased"
                item["attempts"] += 1
                item["claim_token"] = secrets.token_hex(16)
                item["lease_until"] = (now() + timedelta(seconds=self.lease_seconds)).isoformat()
                self.store._save_unlocked(state)
                return {**_public(item), "claim_token": item["claim_token"]}
        return None

    def ack(self, recipient, message_id, claim_token):
        if recipient not in AGENTS or not message_id or not claim_token:
            raise ValueError("Invalid ACK")
        with self.store.lock:
            state = self.store._load_unlocked()
            for item in state.setdefault("agent_messages", []):
                if item["message_id"] != message_id:
                    continue
                if item["to_agent"] != recipient or not hmac.compare_digest(item["claim_token"], claim_token):
                    raise ValueError("ACK lease mismatch")
                if item["status"] == "acked":
                    return _public(item), False
                if item["status"] != "leased":
                    raise ValueError("Message not leased")
                if datetime.fromisoformat(item["lease_until"]) <= now():
                    raise ValueError("ACK lease expired")
                item["status"] = "acked"
                item["ack_at"] = now().isoformat()
                self.store._save_unlocked(state)
                return _public(item), True
        raise ValueError("Unknown message")

    def list_for(self, agent, limit=50):
        if agent not in AGENTS:
            raise ValueError("Unknown agent")
        with self.store.lock:
            items = self.store._load_unlocked().get("agent_messages", [])
            return [_public(m) for m in items if agent in (m["to_agent"], m["from_agent"])][-max(1, min(50, int(limit))):]


def install_agent_message_routes(app, relay_store, authorize_claude):
    from fastapi import HTTPException, Request
    from pydantic import BaseModel

    class SendPayload(BaseModel):
        to_agent: str
        body: str
        kind: str = "question"
        thread_id: str = ""
        task_id: str = ""
        reply_to: str = ""
        idempotency_key: str


    class AckPayload(BaseModel):
        message_id: str
        claim_token: str

    messages = RelayAgentMessages(relay_store)

    def guard(request):
        agent = agent_identity(request, authorize_claude)
        if not agent:
            raise HTTPException(401, "Agent bearer token required")
        return agent

    @app.post("/api/relay/agent/send")
    def send(payload: SendPayload, request: Request):
        sender = guard(request)
        try:
            item, created = messages.send(sender, payload.to_agent, payload.body, kind=payload.kind,
                                          thread_id=payload.thread_id, task_id=payload.task_id,
                                          reply_to=payload.reply_to, idempotency_key=payload.idempotency_key)
            return {"ok": True, "created": created, "message": item}
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.post("/api/relay/agent/claim")
    def claim(request: Request):
        return {"ok": True, "message": messages.claim(guard(request))}

    @app.post("/api/relay/agent/ack")
    def ack(payload: AckPayload, request: Request):
        recipient = guard(request)
        try:
            item, updated = messages.ack(recipient, payload.message_id, payload.claim_token)
            return {"ok": True, "updated": updated, "message": item}
        except ValueError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/relay/agent/messages")
    def list_messages(request: Request, limit: int = 50):
        return {"ok": True, "messages": messages.list_for(guard(request), limit)}
