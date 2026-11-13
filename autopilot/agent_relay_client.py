"""HTTPS client for the FactoryOS agent relay (/api/relay/agent/*), shared by Claude and the Codex worker.

Claude side (dedicated FACTORY_CLAUDE_RELAY_TOKEN, never the broad worker token):

    python -m autopilot.agent_relay_client ask --to codex --kind review --task PR-314 --body-file q.txt --wait 600
    python -m autopilot.agent_relay_client inbox

`ask` prints a JSON audit record (message ids, thread, server timestamps, ACK) so an exchange can be cited as
evidence. No paid API is called here: the only model behind the relay is Codex CLI on the owner's subscription.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import sys
import time


class RelayHTTPError(RuntimeError):
    def __init__(self, status: int, code: str, detail: str):
        super().__init__(f"{status} {code}: {detail}")
        self.status, self.code = status, code


def read_token(env_name: str) -> str:
    """Token from the environment or from a systemd credential file; never printed."""
    value = os.environ.get(env_name, "").strip()
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
    cred = Path(cred_dir) / env_name.lower() if cred_dir else None
    if not value and cred and cred.is_file():
        value = cred.read_text(encoding="utf-8").strip()
    return value


class AgentRelayClient:
    def __init__(self, base_url: str, token: str, session=None, timeout: float = 15):
        base_url = (base_url or "").rstrip("/")
        if not base_url.startswith("https://") or not token:
            raise RuntimeError("Authenticated HTTPS agent relay is not configured")
        if session is None:
            import requests
            session = requests.Session()
        self.base, self.token, self.http, self.timeout = base_url, token, session, timeout

    def _call(self, method: str, path: str, payload=None) -> dict:
        headers = {"Authorization": "Bearer " + self.token}
        if method == "GET":
            r = self.http.get(self.base + path, headers=headers, timeout=self.timeout)
        else:
            r = self.http.post(self.base + path, headers=headers, json=payload or {}, timeout=self.timeout)
        if r.status_code >= 400:
            try:
                detail = r.json().get("detail")
            except ValueError:
                detail = None
            if isinstance(detail, dict):
                raise RelayHTTPError(r.status_code, str(detail.get("code") or ""), str(detail.get("detail") or ""))
            raise RelayHTTPError(r.status_code, "", str(detail or r.reason)[:200])
        return r.json()

    def send(self, to_agent, body, *, kind="question", thread_id="", task_id="", reply_to="", idempotency_key=""):
        return self._call("POST", "/api/relay/agent/send", {
            "to_agent": to_agent, "body": body, "kind": kind, "thread_id": thread_id, "task_id": task_id,
            "reply_to": reply_to, "idempotency_key": idempotency_key or "k_" + secrets.token_hex(10)})["message"]

    def claim(self):
        return self._call("POST", "/api/relay/agent/claim", {}).get("message")

    def ack(self, message_id, claim_token):
        return self._call("POST", "/api/relay/agent/ack", {"message_id": message_id, "claim_token": claim_token})

    def get(self, message_id):
        return self._call("GET", "/api/relay/agent/messages/" + message_id)["message"]

    def thread(self, thread_id, limit=50):
        return self._call("GET", f"/api/relay/agent/messages?thread_id={thread_id}&limit={limit}")["messages"]


def ask(client: AgentRelayClient, to_agent, body, *, kind, task_id="", thread_id="", wait=600, poll=10,
        sleep=time.sleep, clock=time.monotonic):
    """Send, wait for the server-recorded reply, take it from our inbox and ACK it. Returns an audit record."""
    sent = client.send(to_agent, body, kind=kind, task_id=task_id, thread_id=thread_id)
    record = {"question": {k: sent.get(k) for k in ("message_id", "thread_id", "task_id", "created_at")}}
    deadline = clock() + wait
    while True:
        current = client.get(sent["message_id"])
        if current.get("reply_id") or current.get("status") == "dead" or clock() >= deadline:
            break
        sleep(poll)
    record["question"].update({k: current.get(k) for k in ("status", "attempts", "claimed_at", "ack_at", "reply_id")})
    if not current.get("reply_id"):
        record["state"] = "dead_letter" if current.get("status") == "dead" else "timeout"
        return record
    for _ in range(20):                          # our inbox may hold older items first; ACK them in order
        item = client.claim()
        if not item:
            break
        client.ack(item["message_id"], item["claim_token"])
        if item["message_id"] == current["reply_id"]:
            final = client.get(item["message_id"])
            record["reply"] = {k: final.get(k) for k in ("message_id", "thread_id", "reply_to", "from_agent", "kind",
                                                        "created_at", "claimed_at", "ack_at", "status", "body")}
            record["state"] = "answered"
            return record
    record["state"] = "reply_not_in_inbox"
    return record


def main(argv=None):
    ap = argparse.ArgumentParser(description="FactoryOS agent relay client (Claude side)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("--to", default="codex", choices=["codex", "claude"])
    a.add_argument("--kind", default="question", choices=["question", "review"])
    a.add_argument("--task", default="")
    a.add_argument("--thread", default="")
    a.add_argument("--body-file", required=True)
    a.add_argument("--wait", type=int, default=600)
    sub.add_parser("inbox")
    args = ap.parse_args(argv)
    client = AgentRelayClient(os.environ.get("FACTORYOS_URL", ""), read_token("FACTORY_CLAUDE_RELAY_TOKEN"))
    if args.cmd == "ask":
        out = ask(client, args.to, Path(args.body_file).read_text(encoding="utf-8"), kind=args.kind,
                  task_id=args.task, thread_id=args.thread, wait=args.wait)
    else:
        item = client.claim()
        out = {"state": "idle"} if not item else {"message": {k: v for k, v in item.items() if k != "claim_token"},
                                                  "ack": client.ack(item["message_id"], item["claim_token"])["message"]["ack_at"]}
    json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0 if out.get("state") in (None, "answered", "idle") else 2


if __name__ == "__main__":
    sys.exit(main())
