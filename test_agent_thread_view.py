"""T-739: the owner reads one whole ChatGPT <-> Claude Relay conversation with the worker's progress.

GET /api/factory/agent-workspace/threads/<id> (``AgentWorkspace.thread_detail``) and the dashboard's pure
``renderAgentThread``. Covers owner-only access through the real ASGI app, event order, sender provenance,
ticket/run_id linkage, honest states (a worker result is "review", never "done"), duplicate rows, redaction and the
pending-reply count that does not pretend ChatGPT is awake.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-threadview-"))

import agent_workspace as aw  # noqa: E402
from relay import RelayStore  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402
from test_agent_workspace_ui import ui_program  # noqa: E402

SECRET = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"
PR = "https://github.com/pavlovskyi-andrii/blackboxlab-factoryos/pull/4739"


def conversation(tmp):
    """ChatGPT opens a thread, asks the Claude worker, the worker claims/runs/answers; Claude then posts once more."""
    store = RelayStore(Path(tmp) / "relay.json")
    queue = RelayQueue(store)
    ws = aw.AgentWorkspace(store, queue, policy=lambda: "policy-1", environ={},
                           worker_status=lambda: {"online": True, "task_state": "idle"})
    thread = ws.post_message("chatgpt", {"topic": "T-739 <b>view</b>", "body": "Hi Claude <script>x</script>",
                                         "idempotency_key": "k-1"})["thread_id"]
    req = ws.request_task("chatgpt", {"thread_id": thread, "title": "Count tasks", "body": "How many open?",
                                      "idempotency_key": "k-2"})
    ticket = queue.claim("claude-ec2-a")
    run = ticket["execution"]["run_id"]
    for _ in range(2):                                   # a retried event is mirrored once
        queue.event(ticket["id"], "claude-ec2-a", "running", "CLI started", {}, run_id=run, event_id=run + ":1:running")
    queue.event(ticket["id"], "claude-ec2-a", "done", "1) 42 open 2) counted 3) none", {"pr_url": PR},
                run_id=run, event_id=run + ":2:done")
    note = ws.post_message("claude", {"thread_id": thread, "body": "Over to you, ChatGPT", "kind": "question",
                                      "idempotency_key": "k-3"})
    return store, queue, ws, thread, req, ticket["id"], run, note["message_id"]


class ThreadDetailTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store, self.queue, self.ws, self.thread, self.req, self.ticket, self.run, self.last = conversation(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def detail(self):
        return self.ws.thread_detail(self.thread)

    def test_order_provenance_and_linkage(self):
        d = self.detail()
        msgs = d["messages"]
        self.assertEqual([m["seq"] for m in msgs], list(range(1, len(msgs) + 1)))
        self.assertEqual([m["at"] for m in msgs], sorted(m["at"] for m in msgs))
        self.assertEqual([(m["from"], m["kind"], m["via"]) for m in msgs],
                         [("chatgpt", "comment", "mcp-lane"), ("chatgpt", "task_request", "mcp-lane"),
                          ("claude", "status", "relay-worker"), ("claude", "status", "relay-worker"),
                          ("claude", "answer", "relay-worker"), ("claude", "question", "mcp-lane")])
        self.assertEqual(msgs[2]["actor_auth_subject"], "relay-worker:claude-ec2-a")
        self.assertEqual(msgs[1]["message_id"], self.req["message_id"])
        for m in msgs[2:5]:                               # every worker event answers the request, same ticket + run
            self.assertEqual((m["reply_to"], m["reply_to_known"]), (self.req["message_id"], True))
            self.assertEqual((m["task"]["ticket_id"], m["task"]["run_id"]), (self.ticket, self.run))
        self.assertEqual([m["task"]["state"] for m in msgs[2:5]], ["claimed", "running", "review"])
        self.assertIsNone(msgs[0]["task"])
        self.assertEqual((d["total_messages"], d["shown_from_seq"], d["duplicates_hidden"]), (6, 1, 0))

    def test_request_state_is_honest(self):
        (r,) = self.detail()["requests"]
        self.assertEqual((r["ticket_id"], r["run_id"], r["requested_by"], r["mode"]),
                         (self.ticket, self.run, "chatgpt", "read_only"))
        self.assertEqual(r["state"], "review")             # the worker's result is not acceptance
        self.assertEqual(r["worker_events"], 3)
        self.assertEqual(r["result_message_id"], self.detail()["messages"][4]["message_id"])
        queued = self.ws.request_task("chatgpt", {"thread_id": self.thread, "title": "Second", "body": "b",
                                                  "idempotency_key": "k-4"})
        second = next(x for x in self.detail()["requests"] if x["ticket_id"] == queued["ticket_id"])
        self.assertEqual((second["state"], second["run_id"], second["worker_events"]), ("queued", "", 0))
        with self.store.lock:                              # a ticket that vanished is reported, not guessed
            state = self.store._load_unlocked()
            state["tickets"] = [t for t in state["tickets"] if t["id"] != queued["ticket_id"]]
            self.store._save_unlocked(state)
        gone = next(x for x in self.detail()["requests"] if x["ticket_id"] == queued["ticket_id"])
        self.assertEqual(gone["state"], "missing")

    def test_pending_reply_counts_posts_not_presence(self):
        d = self.detail()
        self.assertEqual(d["pending_replies"]["chatgpt"]["newer_from_others"], 4)   # ACK, running, result, question
        self.assertEqual(d["pending_replies"]["claude"]["newer_from_others"], 0)
        self.assertIn("cannot wake up", d["wake"]["chatgpt"])
        self.ws.post_message("chatgpt", {"thread_id": self.thread, "body": "Thanks", "idempotency_key": "k-5"})
        self.assertEqual(self.detail()["pending_replies"]["chatgpt"]["newer_from_others"], 0)

    def test_duplicate_rows_and_redaction(self):
        with self.store.lock:                              # legacy / hand-edited rows: a copy and a raw credential
            state = self.store._load_unlocked()
            msgs = state["agent_workspace"]["messages"]
            msgs.append(dict(msgs[2]))                      # same message_id
            msgs.append({**msgs[3], "message_id": "msg_copy"})  # same relay_event under another id
            msgs.append({"message_id": "msg_leak", "thread_id": self.thread, "from": "gemini", "kind": "comment",
                         "body": "key " + SECRET, "reply_to": "msg_gone", "at": "2099-01-01T00:00:00+00:00"})
            self.store._save_unlocked(state)
        d = self.detail()
        self.assertEqual(d["duplicates_hidden"], 2)
        self.assertEqual(len({m["message_id"] for m in d["messages"]}), len(d["messages"]))
        leak = d["messages"][-1]
        self.assertEqual((leak["via"], leak["reply_to"], leak["reply_to_known"]), ("unknown", "msg_gone", False))
        self.assertNotIn(SECRET, json.dumps(d))
        self.assertNotIn(SECRET[:20], leak["body"])

    def test_unknown_and_invalid_ids(self):
        for bad, code in (("th_missing", "THREAD_NOT_FOUND"), ("../etc", "INVALID_ARGUMENT"), ("", "INVALID_ARGUMENT")):
            with self.assertRaises(aw.WorkspaceError) as err:
                self.ws.thread_detail(bad)
            self.assertEqual(err.exception.code, code)

    def test_rendering(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required for the thread view rendering check")
            self.skipTest("node is not installed")
        d = self.detail()
        html, block, code = ui_program()
        self.assertIn("/api/factory/agent-workspace/threads/", html)
        self.assertNotIn("fetch(", block)
        self.assertNotIn("innerHTML", block)
        self.assertNotIn("method:", block)
        keys = set(re.findall(r"tr\('(aw\.[a-zA-Z_.]*[a-zA-Z_])'", block))
        keys |= {f"aw.state.{s}" for s in ("queued", "claimed", "running", "review", "blocked", "failed", "cancelled",
                                            "missing", "unknown")}
        keys |= {f"aw.via.{v}" for v in ("mcp-lane", "relay-worker", "unknown")} | {f"aw.wake.{l}" for l in aw.LANES}
        for key in keys:
            self.assertEqual(html.count(f'"{key}":'), 3, f"{key} must exist in EN/UK/RU")
        overview = aw.owner_view(self.ws, aw.lane_status({}), {})
        program = code + "\nconst d=" + json.dumps(d) + ",ov=" + json.dumps(overview) + ",out={};" \
            "for(const lang of ['en','uk','ru']){LANG=lang;out[lang]=renderAgentThread(d)}" \
            "out.closed=renderAgentWorkspace(ov);AW_DETAIL[d.thread.thread_id]=d;out.open=renderAgentWorkspace(ov);" \
            "out.none=renderAgentThread(null);process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        out = json.loads(result.stdout)
        self.assertEqual(out["none"], "")
        words = {"en": ("In review", "ChatGPT cannot wake up", "Done"),
                 "uk": ("На перевірці", "ChatGPT не прокидається сам", "Готово"),
                 "ru": ("На проверке", "ChatGPT не просыпается сам", "Готово")}
        for lang, (review, wake, done) in words.items():
            page = out[lang]
            self.assertIsNone(re.search(r">aw\.[a-z]", page), lang)
            self.assertEqual([int(x) for x in re.findall(r'data-seq="(\d+)"', page)], list(range(1, 7)))
            self.assertIn(f'data-ticket="{self.ticket}" data-state="review" data-run="{self.run}"', page)
            self.assertIn(review, page)
            self.assertNotIn(done, page)                   # nothing here is presented as finished/accepted
            self.assertIn(wake, page)
            self.assertIn('data-lane="chatgpt" data-pending="4"', page)
            self.assertIn('data-via="relay-worker"', page)
            self.assertIn(f'data-reply="{self.req["message_id"]}"', page)
            self.assertIn("#2", page)                     # reply_to resolved to the request's position
            self.assertNotIn("<script>x", page)
            self.assertIn("&lt;script&gt;", page)
        self.assertIn('class="ghost awOpen"', out["closed"])
        self.assertNotIn('data-seq="', out["closed"])
        self.assertIn(f'data-thread="{self.thread}" data-status="open" open', out["open"])
        self.assertIn('data-seq="6"', out["open"])         # a periodic refresh keeps the opened conversation


class ThreadRouteAuthTest(unittest.TestCase):
    """Through the real ASGI app: only the signed-in owner reads a conversation."""

    @classmethod
    def setUpClass(cls):
        try:
            import fastapi  # noqa: F401
        except ImportError:
            if os.environ.get("FACTORYOS_REQUIRE_APP") == "1":
                raise
            raise unittest.SkipTest("fastapi is not installed here; CI runs this through test_agent_workspace.py")
        import app as factory
        from test_route_auth_fixes import call
        cls.factory, cls.call = factory, staticmethod(call)

    def setUp(self):
        self.patch = patch.object(self.factory, "FACTORY_PASSWORD", "auth-enabled-for-thread-tests")
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.thread = self.factory.AGENT_WORKSPACE.post_message(
            "chatgpt", {"topic": "auth", "body": "hello", "idempotency_key": "auth-" + os.urandom(4).hex()})["thread_id"]

    def test_owner_only(self):
        path = "/api/factory/agent-workspace/threads/" + self.thread
        self.assertEqual(self.call("GET", path)[0], 401)
        lane = os.environ.get("FACTORY_MCP_LANE_TOKEN_CHATGPT") or "lane-chatgpt-3Hd8Ks2Lq9Wx5Vn1Mz7Rt4Pb6Yc0Jf"
        self.assertEqual(self.call("GET", path, bearer=lane)[0], 401)           # an agent credential is not the owner
        viewer = self.factory._role_session_token("viewer", "guest")
        self.assertEqual(self.call("GET", path, cookie=viewer)[0], 403)
        owner = self.factory.session_token(self.factory.FACTORY_USER)
        status, body = self.call("GET", path, cookie=owner)
        self.assertEqual(status, 200, body[:300])
        data = json.loads(body)
        self.assertEqual((data["thread"]["thread_id"], data["messages"][0]["body"]), (self.thread, "hello"))
        self.assertEqual(self.call("GET", "/api/factory/agent-workspace/threads/th_missing", cookie=owner)[0], 404)


if __name__ == "__main__":
    unittest.main()
