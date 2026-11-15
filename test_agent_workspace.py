"""T-604 / T-625: shared agent workspace on /mcp — lane auth, single claim, replay, secret scrubbing, Relay fencing.

The /mcp handler is called directly (CI has no httpx for fastapi's TestClient), as in test_web_surfer.py.
"""
import asyncio
import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

LANE_TOKENS = {
    "claude": "lane-claude-7Qm2Vx9Lp4Rt8Wz1Ny6Kd3Hs5Jb0Fc",
    "chatgpt": "lane-chatgpt-3Hd8Ks2Lq9Wx5Vn1Mz7Rt4Pb6Yc0Jf",
    "gemini": "lane-gemini-9Pt4Wx2Kd7Ls1Vm8Qz3Hn6Rb5Yc0Jf",
}
SHARED = "workspace-test-shared-mcp-token-0123456789abcdef"
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-workspace-"))
os.environ.setdefault("FACTORY_MCP_TOKEN", SHARED)
for _lane, _value in LANE_TOKENS.items():
    os.environ["FACTORY_MCP_LANE_TOKEN_" + _lane.upper()] = _value
os.environ["FACTORY_MCP_LANE_URL_KEY"] = "chatgpt"

import agent_workspace as aw  # noqa: E402
from relay import RelayStore  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402

PR = "https://github.com/pavlovskyi-andrii/blackboxlab-factoryos/pull/999"


class FakeRequest:
    def __init__(self, bearer="", key=""):
        self.headers = {"authorization": "Bearer " + bearer} if bearer else {}
        self.query_params = {"key": key} if key else {}


def make_workspace(**kw):
    tmp = tempfile.TemporaryDirectory()
    store = RelayStore(Path(tmp.name) / "relay.json")
    queue = RelayQueue(store)
    ws = aw.AgentWorkspace(store, queue, policy=lambda: "policy-1", **kw)
    return tmp, store, queue, ws


def handoff_args(**over):
    args = {"to": "chatgpt", "task_id": "T-900", "objective": "Write docs/example.md",
            "done": ["file exists"], "files_scope": ["docs/example.md"], "idempotency_key": "h-1"}
    args.update(over)
    return args


class LaneAuthTest(unittest.TestCase):
    env = {"FACTORY_MCP_LANE_TOKEN_" + k.upper(): v for k, v in LANE_TOKENS.items()}

    def test_each_lane_token_maps_to_exactly_its_lane(self):
        for lane, token in LANE_TOKENS.items():
            self.assertEqual(aw.lane_identity(FakeRequest(bearer=token), self.env), lane)
        self.assertEqual(aw.lane_identity(FakeRequest(bearer=SHARED), self.env), "")
        self.assertEqual(aw.lane_identity(FakeRequest(bearer=LANE_TOKENS["claude"] + "x"), self.env), "")
        self.assertEqual(aw.lane_identity(FakeRequest(), self.env), "")

    def test_url_key_only_for_lanes_the_owner_opted_in(self):
        env = dict(self.env)
        self.assertEqual(aw.lane_identity(FakeRequest(key=LANE_TOKENS["chatgpt"]), env), "")
        env[aw.URL_KEY_ENV] = "chatgpt"
        self.assertEqual(aw.lane_identity(FakeRequest(key=LANE_TOKENS["chatgpt"]), env), "chatgpt")
        self.assertEqual(aw.lane_identity(FakeRequest(key=LANE_TOKENS["claude"]), env), "")

    def test_misconfigured_tokens_fail_closed(self):
        env = dict(self.env)
        env["FACTORY_MCP_LANE_TOKEN_GEMINI"] = "short"
        self.assertTrue(aw.lane_status(env)["gemini"])
        self.assertEqual(aw.lane_identity(FakeRequest(bearer="short"), env), "")
        env["FACTORY_MCP_LANE_TOKEN_GEMINI"] = LANE_TOKENS["claude"]            # duplicate disables both
        self.assertEqual(aw.lane_identity(FakeRequest(bearer=LANE_TOKENS["claude"]), env), "")
        status = aw.lane_status(self.env, forbidden=(LANE_TOKENS["chatgpt"],))   # reuse of another credential
        self.assertIn("reuse", status["chatgpt"])
        self.assertEqual(aw.lane_identity(FakeRequest(bearer=LANE_TOKENS["chatgpt"]), self.env,
                                          forbidden=(LANE_TOKENS["chatgpt"],)), "")
        self.assertEqual(aw.lane_status({}), {lane: f"{aw.TOKEN_ENV[lane]} is not set" for lane in aw.LANES})

    def test_access_log_never_prints_query_keys(self):
        f = aw._QueryKeyRedactor()
        record = logging.LogRecord("uvicorn.access", logging.INFO, "", 0, '%s - "%s %s"', (
            "1.2.3.4", "POST", "/mcp?key=" + LANE_TOKENS["chatgpt"] + "&x=1"), None)
        f.filter(record)
        self.assertNotIn(LANE_TOKENS["chatgpt"], record.getMessage())
        self.assertIn("key=[REDACTED]&x=1", record.getMessage())


class ThreadTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.store, self.queue, self.ws = make_workspace(known_secrets=lambda: (LANE_TOKENS["claude"],))
        self.addCleanup(self.tmp.cleanup)

    def test_post_read_and_sender_comes_from_the_lane(self):
        first = aw.call_tool(self.ws, "post_message", {"topic": "Naming", "body": "Use T-ids", "idempotency_key": "k1",
                                                       }, "claude")
        self.assertFalse(first["idempotent_replay"])
        tid = first["thread_id"]
        aw.call_tool(self.ws, "post_message", {"thread_id": tid, "body": "Agree", "kind": "answer",
                                               "reply_to": first["message_id"], "idempotency_key": "k1"}, "chatgpt")
        read = aw.call_tool(self.ws, "read_thread", {"thread_id": tid}, "")
        self.assertEqual([m["from"] for m in read["messages"]], ["claude", "chatgpt"])
        page = aw.call_tool(self.ws, "read_thread", {"thread_id": tid, "limit": 1}, "")
        self.assertEqual(page["next_cursor"], first["message_id"])
        rest = aw.call_tool(self.ws, "read_thread", {"thread_id": tid, "after_message_id": page["next_cursor"]}, "")
        self.assertEqual(len(rest["messages"]), 1)
        self.assertEqual(aw.call_tool(self.ws, "list_threads", {}, "")["total"], 1)

    def test_no_spoofed_sender_and_no_decision_kind(self):
        bad = aw.call_tool(self.ws, "post_message", {"topic": "t", "body": "b", "from": "owner",
                                                     "idempotency_key": "k"}, "chatgpt")
        self.assertNotIn("error", bad)                       # extra fields are ignored by the server…
        msg = aw.call_tool(self.ws, "read_thread", {"thread_id": bad["thread_id"]}, "")["messages"][0]
        self.assertEqual(msg["from"], "chatgpt")             # …the sender is always the authenticated lane
        refused = aw.call_tool(self.ws, "post_message", {"topic": "t", "body": "approved", "kind": "decision",
                                                         "idempotency_key": "k2"}, "claude")
        self.assertEqual(refused["error"]["code"], "INVALID_ARGUMENT")

    def test_shared_token_reads_but_cannot_write(self):
        out = aw.call_tool(self.ws, "post_message", {"topic": "t", "body": "b", "idempotency_key": "k"}, "")
        self.assertEqual(out["error"]["code"], "LANE_AUTH_REQUIRED")
        self.assertEqual(aw.call_tool(self.ws, "list_handoffs", {}, "")["error"]["code"], "LANE_AUTH_REQUIRED")
        self.assertIn("threads", aw.call_tool(self.ws, "list_threads", {}, ""))

    def test_replay_returns_same_answer_and_conflict_is_refused(self):
        args = {"topic": "t", "body": "same", "idempotency_key": "k"}
        a = aw.call_tool(self.ws, "post_message", args, "claude")
        b = aw.call_tool(self.ws, "post_message", args, "claude")
        self.assertTrue(b["idempotent_replay"])
        self.assertEqual((a["message_id"], a["event_id"]), (b["message_id"], b["event_id"]))
        self.assertEqual(aw.call_tool(self.ws, "list_threads", {}, "")["total"], 1)
        c = aw.call_tool(self.ws, "post_message", {**args, "body": "different"}, "claude")
        self.assertEqual(c["error"]["code"], "DUPLICATE_CONFLICT")
        other_lane = aw.call_tool(self.ws, "post_message", args, "chatgpt")     # keys are per lane
        self.assertFalse(other_lane["idempotent_replay"])

    def test_secrets_are_refused_not_stored(self):
        for body in ("token ghp_abcdefghijklmnopqrstuvwxyz123456", "my key " + LANE_TOKENS["claude"],
                     "Bearer abcdefghijklmnopqrstuvwxyz"):
            out = aw.call_tool(self.ws, "post_message", {"topic": "t", "body": body, "idempotency_key": "s"}, "claude")
            self.assertEqual(out["error"]["code"], "SECRET_DETECTED")
        self.assertNotIn("ghp_", self.store.path.read_text() if self.store.path.exists() else "")

    def test_rate_limit_and_unknown_thread(self):
        tmp, _, _, ws = make_workspace(max_writes_per_hour=2)
        self.addCleanup(tmp.cleanup)
        for i in range(2):
            aw.call_tool(ws, "post_message", {"topic": "t", "body": str(i), "idempotency_key": f"r{i}"}, "gemini")
        out = aw.call_tool(ws, "post_message", {"topic": "t", "body": "3", "idempotency_key": "r3"}, "gemini")
        self.assertEqual(out["error"]["code"], "RATE_LIMITED")
        self.assertTrue(out["error"]["retryable"])
        out = aw.call_tool(self.ws, "post_message", {"thread_id": "th_nope", "body": "x", "idempotency_key": "u"}, "claude")
        self.assertEqual(out["error"]["code"], "THREAD_NOT_FOUND")


class HandoffTest(unittest.TestCase):
    def setUp(self):
        self.tmp, self.store, self.queue, self.ws = make_workspace()
        self.addCleanup(self.tmp.cleanup)

    def create(self, **over):
        out = aw.call_tool(self.ws, "create_handoff", handoff_args(**over), "claude")
        self.assertNotIn("error", out, out)
        return out["handoff_id"]

    def claim(self, hid, lane="chatgpt", key="c-1", sha="policy-1"):
        return aw.call_tool(self.ws, "claim_handoff", {"handoff_id": hid, "policy_sha": sha, "idempotency_key": key}, lane)

    def test_full_round_trip_with_relay_ticket(self):
        hid = self.create()
        listed = aw.call_tool(self.ws, "list_handoffs", {"state": "queued"}, "chatgpt")
        self.assertEqual([h["handoff_id"] for h in listed["items"]], [hid])
        self.assertEqual(listed["policy_sha"], "policy-1")
        claimed = self.claim(hid)
        self.assertTrue(claimed["run_id"].startswith("run-"))
        ticket = self.store.get(claimed["relay_ticket_id"])
        self.assertEqual(ticket["execution"]["state"], "claimed")
        self.assertEqual(ticket["execution"]["worker_id"], "mcp-chatgpt")
        self.assertEqual(ticket["execution"]["run_id"], claimed["run_id"])
        # the EC2 worker cannot claim the same ROADMAP task while the MCP lane holds it
        stolen, reason = self.queue.claim_roadmap("ec2-claude", "claude", "T-900", owner="claude")
        self.assertIsNone(stolen)
        self.assertTrue(reason)
        result = aw.call_tool(self.ws, "submit_handoff_result", {
            "handoff_id": hid, "run_id": claimed["run_id"], "summary": "Done, see PR", "artifact_urls": [PR],
            "checks": [{"name": "smoke", "status": "pass"}], "idempotency_key": "s-1"}, "chatgpt")
        self.assertEqual(result["state"], "review")
        ticket = self.store.get(claimed["relay_ticket_id"])
        self.assertEqual(ticket["execution"]["state"], "pushed")
        self.assertEqual(ticket["execution"]["pr_url"], PR)
        self.assertEqual(aw.call_tool(self.ws, "review_handoff", {"handoff_id": hid, "verdict": "accept",
                                                                  "idempotency_key": "v"}, "chatgpt")["error"]["code"],
                         "NOT_PERMITTED")                    # the executor cannot approve its own work
        done = aw.call_tool(self.ws, "review_handoff", {"handoff_id": hid, "verdict": "accept",
                                                        "idempotency_key": "v"}, "claude")
        self.assertEqual(done["state"], "done")
        self.assertEqual(self.store.get(claimed["relay_ticket_id"])["execution"]["state"], "done")
        overview = self.ws.overview()
        self.assertEqual(overview["handoff_states"], {"done": 1})

    def test_single_claim_and_replay(self):
        hid = self.create()
        first = self.claim(hid)
        replay = self.claim(hid)
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(first["run_id"], replay["run_id"])
        again = self.claim(hid, key="c-2")
        self.assertEqual(again["error"]["code"], "CLAIM_CONFLICT")
        tickets = [t for t in self.store.list() if (t.get("source") or {}).get("task_id") == "T-900"]
        self.assertEqual(len(tickets), 1)
        claims = [h for h in tickets[0]["history"] if h.get("action") == "claimed"]
        self.assertEqual(len(claims), 1)

    def test_claim_guards(self):
        hid = self.create()
        self.assertEqual(self.claim(hid, lane="gemini")["error"]["code"], "NOT_ASSIGNED")
        self.assertEqual(self.claim(hid, sha="old")["error"]["code"], "POLICY_STALE")
        self.assertEqual(aw.call_tool(self.ws, "create_handoff", handoff_args(idempotency_key="x"), "chatgpt")
                         ["error"]["code"], "NOT_PERMITTED")
        self.assertEqual(aw.call_tool(self.ws, "create_handoff", handoff_args(idempotency_key="y"), "claude")
                         ["error"]["code"], "CLAIM_CONFLICT")            # one open handoff per task
        dep = self.create(task_id="T-901", depends=[hid], files_scope=["docs/other.md"], idempotency_key="h-2")
        self.assertEqual(self.claim(dep, key="d")["error"]["code"], "DEPENDENCY_PENDING")
        self.claim(hid)
        overlap = self.create(task_id="T-902", files_scope=["docs/*"], idempotency_key="h-3")
        self.assertEqual(self.claim(overlap, key="o")["error"]["code"], "CLAIM_CONFLICT")

    def test_relay_already_running_task_blocks_the_claim(self):
        ticket, _ = self.queue.claim_roadmap("ec2-claude", "chatgpt", "T-900", owner="chatgpt")
        self.assertIsNotNone(ticket)
        hid = self.create()
        self.assertEqual(self.claim(hid)["error"]["code"], "CLAIM_CONFLICT")
        self.assertEqual(aw.call_tool(self.ws, "list_handoffs", {"state": "queued"}, "chatgpt")["items"][0]["state"],
                         "queued")

    def test_submit_guards_and_artifact_validation(self):
        hid = self.create()
        run = self.claim(hid)["run_id"]
        base = {"handoff_id": hid, "run_id": run, "summary": "s", "artifact_urls": [PR], "idempotency_key": "s"}
        self.assertEqual(aw.call_tool(self.ws, "submit_handoff_result", {**base, "run_id": "run-bad"}, "chatgpt")
                         ["error"]["code"], "RUN_ID_MISMATCH")
        for url in ("https://github.com/someone/else/pull/1", "https://evil.example/pull/1", "javascript:alert(1)"):
            self.assertEqual(aw.call_tool(self.ws, "submit_handoff_result", {**base, "artifact_urls": [url]}, "chatgpt")
                             ["error"]["code"], "ARTIFACT_INVALID")
        self.assertEqual(aw.call_tool(self.ws, "submit_handoff_result", base, "gemini")["error"]["code"],
                         "NOT_ASSIGNED")

    def test_lease_expiry_and_release(self):
        clock = {"now": datetime(2026, 11, 15, tzinfo=timezone.utc)}
        tmp, store, queue, ws = make_workspace(clock=lambda: clock["now"], lease=timedelta(hours=1))
        self.addCleanup(tmp.cleanup)
        hid = aw.call_tool(ws, "create_handoff", handoff_args(), "claude")["handoff_id"]
        run = aw.call_tool(ws, "claim_handoff", {"handoff_id": hid, "policy_sha": "policy-1",
                                                 "idempotency_key": "c"}, "chatgpt")["run_id"]
        clock["now"] += timedelta(hours=2)
        late = aw.call_tool(ws, "submit_handoff_result", {"handoff_id": hid, "run_id": run, "summary": "s",
                                                          "artifact_urls": [PR], "idempotency_key": "s"}, "chatgpt")
        self.assertEqual(late["error"]["code"], "LEASE_EXPIRED")
        hid2 = aw.call_tool(ws, "create_handoff", handoff_args(task_id="T-903", idempotency_key="h9",
                                                               files_scope=["x.md"]), "claude")["handoff_id"]
        run2 = aw.call_tool(ws, "claim_handoff", {"handoff_id": hid2, "policy_sha": "policy-1",
                                                  "idempotency_key": "c2"}, "chatgpt")["run_id"]
        out = aw.call_tool(ws, "release_handoff", {"handoff_id": hid2, "run_id": run2, "reason": "blocked",
                                                   "notes": "needs owner", "idempotency_key": "r"}, "chatgpt")
        self.assertEqual(out["state"], "blocked")
        ticket = next(t for t in store.list() if (t.get("source") or {}).get("task_id") == "T-903")
        self.assertEqual(ticket["execution"]["state"], "blocked")
        self.assertEqual(aw.call_tool(ws, "release_handoff", {"handoff_id": hid2, "run_id": run2,
                                                              "reason": "owner_reassign", "idempotency_key": "r2"},
                                      "chatgpt")["error"]["code"], "NOT_PERMITTED")


def mcp_call(factory, payload, token=None, query=b""):
    from starlette.requests import Request
    body = json.dumps(payload).encode()
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", ("Bearer " + token).encode()))
    sent = {"done": False}

    async def receive():
        if sent["done"]:
            return {"type": "http.disconnect"}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "query_string": query, "headers": headers},
                      receive)
    response = asyncio.run(factory.factory_mcp(request))
    return response.status_code, json.loads(response.body or b"{}")


class McpEndpointTest(unittest.TestCase):
    def call(self, name, args, token=None, query=b""):
        import app as factory
        status, out = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                         "params": {"name": name, "arguments": args}}, token, query)
        self.assertEqual(status, 200, out)
        result = out["result"]
        return result.get("isError", False), json.loads(result["content"][0]["text"])

    def test_tools_listed_and_lane_auth_through_mcp(self):
        import app as factory
        _, listed = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, SHARED)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue(aw.TOOL_NAMES <= names and "web_search" in names)
        self.assertEqual(mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, "nope" * 10)[0], 401)
        err, out = self.call("post_message", {"topic": "t", "body": "b", "idempotency_key": "k"}, SHARED)
        self.assertTrue(err)
        self.assertEqual(out["code"], "LANE_AUTH_REQUIRED")
        err, out = self.call("post_message", {"topic": "MCP round trip", "body": "hello", "idempotency_key": "mcp-1"},
                             LANE_TOKENS["claude"])
        self.assertFalse(err, out)
        # ChatGPT's connector cannot send headers: its lane key works in the URL because the owner opted it in
        err, read = self.call("read_thread", {"thread_id": out["thread_id"]},
                              query=("key=" + LANE_TOKENS["chatgpt"]).encode())
        self.assertFalse(err)
        self.assertEqual(read["messages"][0]["from"], "claude")
        status, _ = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                             query=("key=" + LANE_TOKENS["gemini"]).encode())
        self.assertEqual(status, 401)                          # gemini did not opt in to URL keys
        # the owner view
        view = factory.AGENT_WORKSPACE.overview()
        self.assertGreaterEqual(len(view["threads"]), 1)


if __name__ == "__main__":
    unittest.main()
