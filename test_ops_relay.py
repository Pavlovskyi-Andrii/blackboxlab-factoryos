"""T-740 Ops relay: catalog, gates, limits, idempotency, redaction, caps, executor. Offline, no systemd, no network.

Routes are called directly through a capturing fake app (CI has no httpx); the executor gets a fake runner instead
of systemctl / journalctl / git.
"""
import asyncio
import json
import pathlib
import tempfile
import unittest

from fastapi import HTTPException

import ops_catalog as cat
import ops_relay as orl
from autopilot import ops_agent

ON = {"FACTORY_OPS_RELAY_ENABLED": "1"}
TOKEN = "wrk_" + "Z" * 40


def req(op="status", key="k1", **extra):
    args = {"op": op, "reason": "surfer looks stuck", "idempotency_key": key}
    if op in ("status", "journal") and "unit" not in extra:
        extra["unit"] = cat.SURFER_UNIT
    if op == "restart" and "unit" not in extra:
        extra["unit"] = cat.SURFER_UNIT
    args.update(extra)
    return args


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def store(env=None, clock=None, known=()):
    d = pathlib.Path(tempfile.mkdtemp())
    return orl.OpsStore(d, clock=clock or Clock(), environ=ON if env is None else env, known_secrets=lambda: known)


class CatalogTest(unittest.TestCase):
    def test_only_catalog_shapes_validate(self):
        self.assertEqual(cat.validate({"op": "host"}), {"op": "host", "unit": None, "minutes": None, "lines": None})
        j = cat.validate({"op": "journal", "unit": cat.CLAUDE_UNIT, "minutes": 180, "lines": "300"})
        self.assertEqual((j["minutes"], j["lines"]), (180, 300))
        bad = [{"op": "shell"}, {"op": "status"}, {"op": "status", "unit": "sshd.service"},
               {"op": "restart", "unit": "factoryos-runner-supervisor.timer"},
               {"op": "journal", "unit": cat.SURFER_UNIT, "minutes": 181},
               {"op": "journal", "unit": cat.SURFER_UNIT, "lines": 301},
               {"op": "journal", "unit": cat.SURFER_UNIT, "lines": True},
               {"op": "journal", "unit": cat.SURFER_UNIT, "minutes": "5; rm -rf /"},
               {"op": "host", "unit": cat.SURFER_UNIT}, {"op": "status", "unit": cat.SURFER_UNIT, "lines": 5},
               {"op": "status", "unit": cat.SURFER_UNIT + " ; reboot"}, "status"]
        for args in bad:
            with self.assertRaises(ValueError, msg=args):
                cat.validate(args)

    def test_plans_are_argv_lists_with_no_shell_metacharacters_beyond_catalog(self):
        cases = [{"op": "status", "unit": cat.SURFER_UNIT}, {"op": "journal", "unit": cat.SURFER_UNIT},
                 {"op": "host"}, {"op": "restart", "unit": cat.CLAUDE_UNIT}, {"op": "sync_checkout"},
                 {"op": "install_surfer_unit"}]
        for c in cases:
            steps = cat.plan(c)
            self.assertTrue(steps)
            for label, argv, as_worker in steps:
                self.assertIsInstance(argv, list)
                self.assertTrue(all(isinstance(a, str) for a in argv))
                self.assertNotIn(argv[0], ("sh", "/bin/sh", "sudo", "ssh", "curl", "python3"))
                self.assertFalse(any(x in " ".join(argv) for x in ("push", "--force", "reset --hard", "&&", "|")))
        restart = cat.plan({"op": "restart", "unit": cat.SURFER_UNIT})
        self.assertEqual([s[1][:2] for s in restart[:2]], [["systemctl", "reset-failed"], ["systemctl", "restart"]])
        sync = [s[1] for s in cat.plan({"op": "sync_checkout"})]
        self.assertIn(["git", "-C", cat.DEFAULT_REPO, "merge", "--ff-only", "@{u}"], sync)
        self.assertTrue(all(s[2] for s in cat.plan({"op": "sync_checkout"})), "git runs as the worker user")

    def test_classes(self):
        self.assertEqual(cat.classes_from(None), ("read", "restart"))
        self.assertEqual(cat.classes_from("read"), ("read",))
        self.assertEqual(cat.classes_from("read,restart,install,root"), ("read", "restart", "install"))
        self.assertEqual(cat.classes_from("none"), ())


class RedactionTest(unittest.TestCase):
    def test_redacts_known_values_and_credential_shapes(self):
        secrets = {
            "known": "my-own-worker-token-value-123",
            "gh": "ghp_" + "a" * 36,
            "tg": "123456789:" + "B" * 35,
            "ant": "sk-ant-api03-" + "c" * 30,
            "aws": "AKIA" + "D" * 16,
            "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijk",
        }
        text = (f"token {secrets['known']}\nAuthorization: Bearer abcdefghijklmnopqrstuvwxyz\n"
                f"FACTORY_CLAUDE_WORKER_TOKEN={secrets['known']}x\nDB_PASSWORD='hunter2hunter2'\n"
                f"{secrets['gh']} {secrets['tg']} {secrets['ant']} {secrets['aws']} {secrets['jwt']}\n"
                "https://user:pa55word@example.com/x?key=abcdef123456&ok=1\n"
                "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----\n"
                "ActiveState=active\nNRestarts=4\n")
        out = cat.redact(text, [secrets["known"]])
        for value in list(secrets.values()) + ["hunter2", "abcdefghijklmnop", "pa55word", "abcdef123456", "AAAA"]:
            self.assertNotIn(value, out, out)
        self.assertIn("ActiveState=active", out)
        self.assertIn("NRestarts=4", out)
        self.assertIn("@example.com", out)
        self.assertEqual(cat.redact(out, [secrets["known"]]), out, "idempotent")

    def test_cap_keeps_tail(self):
        text = "\n".join(f"line {i}" for i in range(20000))
        capped = cat.cap(text)
        self.assertLessEqual(len(capped.encode()), cat.MAX_OUTPUT_BYTES)
        self.assertTrue(capped.endswith("line 19999"))
        self.assertIn("bytes cut", capped)
        self.assertEqual(cat.cap("short"), "short")


class StoreTest(unittest.TestCase):
    def test_flag_off_refuses(self):
        s = store(env={})
        with self.assertRaisesRegex(PermissionError, "FACTORY_OPS_RELAY_ENABLED"):
            s.request("claude", req())
        self.assertIsNone(store(env={}).claim())

    def test_only_the_claude_lane(self):
        s = store()
        for lane in ("", "chatgpt", "gemini", "shared"):
            with self.assertRaises(PermissionError):
                s.request(lane, req())
            with self.assertRaises(PermissionError):
                s.result_for_agent(lane, "ops_0123456789ab")

    def test_reason_key_and_unknown_args(self):
        s = store()
        with self.assertRaisesRegex(ValueError, "idempotency_key"):
            s.request("claude", req(key=""))
        with self.assertRaisesRegex(ValueError, "idempotency_key"):
            s.request("claude", req(key="a b"))
        with self.assertRaisesRegex(ValueError, "reason"):
            s.request("claude", {**req(), "reason": ""})
        with self.assertRaisesRegex(ValueError, "unknown arguments"):
            s.request("claude", req(command="rm -rf /"))
        with self.assertRaises(ValueError):
            s.request("claude", req(op="shell"))

    def test_classes_switch(self):
        s = store(env={**ON, "FACTORY_OPS_RELAY_CLASSES": "read"})
        with self.assertRaisesRegex(PermissionError, "restart"):
            s.request("claude", req("restart"))
        s = store()
        with self.assertRaisesRegex(PermissionError, "install"):
            s.request("claude", req("sync_checkout"))
        s = store(env={**ON, "FACTORY_OPS_RELAY_CLASSES": "read,restart,install"})
        self.assertEqual(s.request("claude", req("install_surfer_unit"))["status"], "queued")

    def test_idempotency(self):
        s = store()
        a = s.request("claude", req())
        b = s.request("claude", req())
        self.assertEqual(a["id"], b["id"])
        with self.assertRaisesRegex(ValueError, "different op"):
            s.request("claude", req("host"))
        self.assertEqual(s.owner_board()["usage"]["last_24h"], 1)

    def test_daily_and_restart_limits_and_open_cap(self):
        clock = Clock()
        s = store(clock=clock)
        for i in range(orl.MAX_RESTARTS_PER_UNIT_PER_DAY):
            s.request("claude", req("restart", key=f"r{i}"))
            task = s.claim()
            s.finish(task["id"], {"status": "done", "output": "ok"})
        with self.assertRaisesRegex(PermissionError, "restart limit"):
            s.request("claude", req("restart", key="r-more"))
        s.request("claude", req("restart", key="claude-1", unit=cat.CLAUDE_UNIT))  # another unit still allowed
        for i in range(orl.MAX_OPEN - 1):
            s.request("claude", req("host", key=f"h{i}"))
        with self.assertRaisesRegex(PermissionError, "already waiting"):
            s.request("claude", req("host", key="h-over"))
        clock.t += orl.QUEUE_EXPIRES_SECONDS + 1  # the queued ones expire
        n = orl.MAX_RESTARTS_PER_UNIT_PER_DAY + orl.MAX_OPEN
        i = 0
        while n < orl.MAX_PER_DAY:
            s.request("claude", req("host", key=f"d{i}"))
            s.finish(s.claim()["id"], {"status": "done"})
            n += 1
            i += 1
        with self.assertRaisesRegex(PermissionError, "daily limit"):
            s.request("claude", req("host", key="over"))
        clock.t += orl.DAY + 1
        self.assertEqual(s.request("claude", req("host", key="next-day"))["status"], "queued")

    def test_lifecycle_expiry_lease_and_notifications(self):
        clock = Clock()
        s = store(clock=clock, known=[TOKEN])
        r = s.request("claude", req("restart"))
        notes = s.drain_notes()
        self.assertEqual(len(notes), 1)
        self.assertIn("restart", notes[0])
        self.assertEqual(s.drain_notes(), [])
        self.assertEqual(s.request("claude", req("host", key="h"))["status"], "queued")
        self.assertEqual(s.drain_notes(), [], "read ops do not notify")
        task = s.claim("ops-ip-1")
        self.assertEqual(task, {"id": r["id"], "op": "restart", "unit": cat.SURFER_UNIT, "minutes": None,
                                "lines": None})
        self.assertEqual(s.result_for_agent("claude", r["id"])["status"], "claimed")
        s.finish(r["id"], {"status": "done", "exit_code": 0, "output": f"x {TOKEN} y\nActiveState=active",
                           "duration_ms": 9000})
        got = s.result_for_agent("claude", r["id"])
        self.assertEqual(got["status"], "done")
        self.assertNotIn(TOKEN, got["output"])
        self.assertIn("ActiveState=active", got["output"])
        self.assertNotIn("lane", got)
        notes = s.drain_notes()
        self.assertEqual(len(notes), 1)
        self.assertIn("выполнено", notes[0])
        self.assertNotIn(TOKEN, notes[0])
        with self.assertRaises(ValueError):
            s.finish(r["id"], {"status": "done"})  # not claimed any more
        with self.assertRaises(LookupError):
            s.finish("ops_ffffffffffff", {"status": "done"})
        # A claim nobody finishes fails after the lease; a request nobody claims expires.
        h = s.claim()
        clock.t += orl.CLAIM_LEASE_SECONDS + 1
        self.assertEqual(s.result_for_agent("claude", h["id"])["status"], "failed")
        r2 = s.request("claude", req("restart", key="r2"))
        s.drain_notes()
        clock.t += orl.QUEUE_EXPIRES_SECONDS + 1
        out = s.result_for_agent("claude", r2["id"])
        self.assertEqual(out["status"], "expired")
        self.assertIn("T-740-H", out["error"])
        self.assertTrue(any("не выполнено" in n for n in s.drain_notes()))

    def test_server_caps_output(self):
        s = store()
        r = s.request("claude", req())
        s.claim()
        s.finish(r["id"], {"status": "done", "output": "x" * 200_000})
        self.assertLessEqual(len(s.result_for_agent("claude", r["id"])["output"].encode()), cat.MAX_OUTPUT_BYTES)

    def test_owner_board(self):
        s = store()
        s.request("claude", req())
        s.claim("ops-node")
        b = s.owner_board()
        self.assertTrue(b["enabled"])
        self.assertEqual(b["classes"], ["read", "restart"])
        self.assertTrue(b["executor"]["online"])
        self.assertEqual(b["requests"][0]["lane"], "claude")
        self.assertEqual(b["requests"][0]["status"], "claimed")


class FakeApp:
    def __init__(self):
        self.routes = {}

    def _reg(self, method, path):
        def deco(fn):
            self.routes[(method, path)] = fn
            return fn
        return deco

    def get(self, path):
        return self._reg("GET", path)

    def post(self, path):
        return self._reg("POST", path)


class FakeRequest:
    def __init__(self, auth="", body=None, role="owner"):
        self.headers = {"authorization": auth}
        self._body = body or {}
        self.role = role

    async def json(self):
        return self._body


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.app = FakeApp()
        self.sent = []
        self.store = store()
        orl.install_routes(self.app, store=self.store,
                           authorize_worker=lambda r: r.headers.get("authorization") == "Bearer " + TOKEN,
                           identity=lambda r: {"role": r.role}, notify=self.sent.append)

    def run_route(self, method, path, *args):
        res = self.app.routes[(method, path)](*args)
        return asyncio.run(res) if asyncio.iscoroutine(res) else res

    def test_worker_and_owner_auth(self):
        with self.assertRaises(HTTPException) as e:
            self.run_route("POST", "/api/ops/worker/claim", FakeRequest("Bearer nope"))
        self.assertEqual(e.exception.status_code, 401)
        with self.assertRaises(HTTPException) as e:
            self.run_route("GET", "/api/ops/owner", FakeRequest(role="viewer"))
        self.assertEqual(e.exception.status_code, 403)

    def test_claim_result_round_trip_notifies(self):
        view = orl.call_tool(self.store, "ops_request", req("restart"), "claude", notify=self.sent.append)
        self.assertEqual(len(self.sent), 1)
        got = self.run_route("POST", "/api/ops/worker/claim", FakeRequest("Bearer " + TOKEN, {"node": "n"}))
        self.assertEqual(got["task"]["id"], view["id"])
        ok = self.run_route("POST", "/api/ops/worker/result/{request_id}", view["id"],
                            FakeRequest("Bearer " + TOKEN, {"status": "done", "output": "fine"}))
        self.assertEqual(ok["status"], "done")
        self.assertEqual(len(self.sent), 2)
        board = self.run_route("GET", "/api/ops/owner", FakeRequest())
        self.assertEqual(board["requests"][0]["status"], "done")
        with self.assertRaises(HTTPException) as e:
            self.run_route("POST", "/api/ops/worker/result/{request_id}", view["id"],
                           FakeRequest("Bearer " + TOKEN, {"status": "done"}))
        self.assertEqual(e.exception.status_code, 409)

    def test_mcp_errors_are_value_errors(self):
        with self.assertRaisesRegex(ValueError, "Claude lane"):
            orl.call_tool(self.store, "ops_request", req(), "chatgpt")
        with self.assertRaisesRegex(ValueError, "unknown ops request"):
            orl.call_tool(self.store, "ops_result", {"id": "ops_0123456789ab"}, "claude")


class FakeRunner:
    def __init__(self, results=None, delay=0.0, clock=None):
        self.calls = []
        self.results = results or {}
        self.delay = delay
        self.clock = clock

    def __call__(self, argv, *, as_worker, timeout):
        self.calls.append((argv, as_worker, timeout))
        if self.clock:
            self.clock.t += self.delay
        key = " ".join(argv[:2])
        return self.results.get(key, (0, "ok " + " ".join(argv[:2])))


class ExecutorTest(unittest.TestCase):
    def test_unknown_op_never_runs(self):
        runner = FakeRunner()
        for task in ({"id": "ops_x", "op": "shell"}, {"id": "ops_x", "op": "status", "unit": "sshd.service"},
                     {"id": "ops_x", "op": "restart", "unit": "factoryos-ops-agent.service"},
                     {"id": "ops_x", "op": "journal", "unit": cat.SURFER_UNIT, "lines": 10_000}):
            body = ops_agent.execute(task, repo="/opt/factoryos", known=[], runner=runner)
            self.assertEqual(body["status"], "failed")
            self.assertTrue(body["error"].startswith("refused"))
        self.assertEqual(runner.calls, [])

    def test_runs_plan_redacts_and_reports(self):
        runner = FakeRunner({"journalctl -u": (0, f"Nov 25 worker: header Authorization: Bearer {TOKEN}\nfine")})
        body = ops_agent.execute({"id": "ops_x", "op": "status", "unit": cat.SURFER_UNIT}, repo="/opt/factoryos",
                                 known=[TOKEN], runner=runner)
        self.assertEqual(body["status"], "done")
        self.assertNotIn(TOKEN, body["output"])
        self.assertIn("fine", body["output"])
        self.assertEqual([c[0] for c in runner.calls], [s[1] for s in cat.plan({"op": "status",
                                                                                   "unit": cat.SURFER_UNIT})])

    def test_deadline_stops_the_op(self):
        clock = Clock(0.0)
        runner = FakeRunner(delay=25.0, clock=clock)
        body = ops_agent.execute({"id": "ops_x", "op": "host"}, repo="/opt/factoryos", known=[], runner=runner,
                                 clock=clock)
        self.assertEqual(body["status"], "failed")
        self.assertIn("timeout", body["error"])
        self.assertEqual(len(runner.calls), 3)  # 25 + 25 + 25 s > 60 s: the 4th step never starts
        self.assertTrue(all(c[2] <= cat.OP_TIMEOUT_SECONDS for c in runner.calls))

    def test_failed_mutation_stops(self):
        runner = FakeRunner({"git -C": (1, "fatal: Not possible to fast-forward")})
        body = ops_agent.execute({"id": "ops_x", "op": "sync_checkout"}, repo="/opt/factoryos", known=[],
                                 runner=runner)
        self.assertEqual(body["status"], "failed")
        self.assertEqual(len(runner.calls), 1)

    def test_real_runner_never_uses_a_shell_and_times_out(self):
        rc, out = ops_agent.run_argv(["sleep", "5"], as_worker=False, timeout=1)
        self.assertEqual(rc, 124)
        rc, out = ops_agent.run_argv(["echo", "a; echo b"], as_worker=False, timeout=5)
        self.assertEqual((rc, out.strip()), (0, "a; echo b"))
        self.assertNotIn("FACTORY_CLAUDE_WORKER_TOKEN", ops_agent.child_env(False))

    def test_run_once_against_a_store(self):
        s = store(known=[TOKEN])
        s.request("claude", req("journal", minutes=5, lines=10))
        s.request("claude", req("host", key="h2"))

        def post(url, token, body):
            self.assertEqual(token, TOKEN)
            if url.endswith("/api/ops/worker/claim"):
                return 200, {"task": s.claim(body.get("node", ""))}
            rid = url.rsplit("/", 1)[1]
            s.finish(rid, json.loads(json.dumps(body)))
            return 200, {"ok": True}

        out = ops_agent.run_once(env={"FACTORYOS_URL": "https://factory.example", "FACTORY_CLAUDE_WORKER_TOKEN": TOKEN},
                                 post=post, runner=FakeRunner({"journalctl -u": (0, "token " + TOKEN)}))
        self.assertEqual([r["status"] for r in out["ran"]], ["done", "done"])
        board = s.owner_board()
        self.assertTrue(all(r["status"] == "done" for r in board["requests"]))
        self.assertFalse(any(TOKEN in r["output"] for r in board["requests"]))
        self.assertEqual(ops_agent.run_once(env={"FACTORYOS_URL": "", "FACTORY_CLAUDE_WORKER_TOKEN": TOKEN})["status"],
                         "not_configured")


class DeployFilesTest(unittest.TestCase):
    ROOT = pathlib.Path(__file__).resolve().parent

    def test_units_and_install_script(self):
        svc = (self.ROOT / "deploy/systemd/factoryos-ops-agent.service").read_text()
        self.assertIn("ExecStart=/usr/bin/python3 -m autopilot.ops_agent", svc)
        timer = (self.ROOT / "deploy/systemd/factoryos-ops-agent.timer").read_text()
        self.assertIn("OnUnitInactiveSec=30s", timer)
        script = (self.ROOT / "deploy/install_ops_agent.sh").read_text()
        self.assertIn("set -euo pipefail", script)
        self.assertIn("WorkingDirectory=/usr/local/lib/factoryos-ops", svc)  # root-owned copy, not the git checkout
        for module in ("ops_catalog.py", "ops_agent", "supervisor", "worker_heartbeat"):
            self.assertIn(module, script)
        self.assertIn('bash "$REPO/deploy/install_surfer_worker.sh"', script)  # one owner command applies T-728 too
        for forbidden in ("ssh-keygen", "authorized_keys", "aws configure", "curl ", "AWS_SECRET"):
            self.assertNotIn(forbidden, script)

    def test_no_shell_true_in_executor(self):
        src = (self.ROOT / "autopilot/ops_agent.py").read_text()
        self.assertNotIn("shell=True", src)
        self.assertNotIn("os.system", src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
