"""T-560 wiring: owner's read-only browser tasks → EC2 runner. Offline: fake Playwright, fake HTTP."""
import asyncio
import base64
import json
import os
import pathlib
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-browsertasks-"))

from fastapi import HTTPException  # noqa: E402

import browser_tasks as bt  # noqa: E402
from autopilot import browser_tasks as worker  # noqa: E402
from browser_runner.playwright_executor import BrowserRuntimePolicy, run_playwright  # noqa: E402
import test_browser_playwright as fx  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 50


class Clock:
    def __init__(self):
        self.t = 1_800_000_000

    def __call__(self):
        return self.t


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.s = bt.BrowserTaskStore(pathlib.Path(self.tmp.name), clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def test_url_rules(self):
        for bad in ("http://example.com", "https://user:pw@example.com", "https://localhost/x", "https://10.0.0.5/",
                    "https://169.254.169.254/latest/meta-data", "https://printer.local/", "ftp://x.com"):
            with self.assertRaises(HTTPException, msg=bad):
                self.s.create(bad, [])
        with self.assertRaises(HTTPException):
            self.s.create("https://shop.example/", ["<script>"])
        task = self.s.create("https://shop.example/item", [".price", " ", "h1", "a", "b", "c", "d"])
        self.assertEqual((task["status"], task["action"], len(task["selectors"])), ("queued", "read", 5))
        self.assertEqual(self.s.create("https://shop.example/", [])["selectors"], ["body"])

    def test_claim_lease_finish_and_screenshot(self):
        task = self.s.create("https://shop.example/item", [".price"])
        claimed = self.s.claim()
        self.assertEqual(claimed, {"id": task["id"], "url": task["url"], "selectors": [".price"], "action": "read"})
        self.assertIsNone(self.s.claim())                                   # leased
        self.clock.t += bt.LEASE_SECONDS + 1
        self.assertEqual(self.s.claim()["id"], task["id"])                  # a lost worker's task comes back
        done = self.s.finish(task["id"], {"status": "done", "final_url": "https://shop.example",
                                          "texts": [{"selector": ".price", "text": "1 299 UAH"}],
                                          "screenshot_png_b64": base64.b64encode(PNG).decode(), "steps": 3})
        self.assertEqual((done["status"], done["result"]["texts"][0]["text"], done["result"]["screenshot"]),
                         ("done", "1 299 UAH", True))
        self.assertEqual(self.s.screenshot(task["id"]).read_bytes(), PNG)
        with self.assertRaises(HTTPException):
            self.s.finish(task["id"], {"status": "done"})                   # only a running task takes a result
        with self.assertRaises(HTTPException):
            self.s.screenshot("../browser_tasks.json")
        t2 = self.s.create("https://shop.example/2", [])
        self.s.claim()
        for bad in ({"status": "queued"}, {"status": "done", "screenshot_png_b64": base64.b64encode(b"GIF89a").decode()}):
            with self.assertRaises(HTTPException):
                self.s.finish(t2["id"], bad)

    def finish(self, url, shot=False):
        task = self.s.create(url, [])
        self.s.claim()
        body = {"status": "done"}
        if shot:
            body["screenshot_png_b64"] = base64.b64encode(PNG).decode()
        self.s.finish(task["id"], body)
        return task

    def test_only_finished_tasks_are_evicted_with_their_screenshots(self):
        first = self.finish("https://shop.example/0", shot=True)
        running = self.s.create("https://shop.example/running", [])
        self.assertEqual(self.s.claim()["id"], running["id"])               # leased: the loop below cannot take it
        for i in range(bt.MAX_TASKS):
            self.finish(f"https://shop.example/{i + 1}")
        ids = {t["id"] for t in self.s.list()}
        self.assertNotIn(first["id"], ids)
        self.assertFalse((self.s.shots / f"{first['id']}.png").exists())
        self.assertIn(running["id"], ids)                                   # its result can still arrive
        self.assertEqual(self.s.finish(running["id"], {"status": "done"})["status"], "done")
        # a queued task older than every finished one is kept as well
        items = self.s._load()
        items.insert(0, {**items[0], "id": "bt_" + "f" * 16, "status": "queued", "result": None})
        items += [{**items[-1], "id": "bt_%016x" % n} for n in range(5)]
        self.s._save(items)
        self.assertIn("bt_" + "f" * 16, {t["id"] for t in self.s.list()})

    def test_full_active_queue_refuses_new_tasks(self):
        for i in range(bt.MAX_ACTIVE):
            self.s.create(f"https://shop.example/{i}", [])
        with self.assertRaises(HTTPException) as e:
            self.s.create("https://shop.example/one-more", [])
        self.assertEqual(e.exception.status_code, 429)
        self.s.claim()
        self.s.finish(self.s.list()[-1]["id"], {"status": "failed"})
        self.s.create("https://shop.example/now-fits", [])


class RoutesTest(unittest.TestCase):
    def test_owner_and_worker_auth(self):
        from fastapi import FastAPI
        with tempfile.TemporaryDirectory() as d:
            store = bt.BrowserTaskStore(pathlib.Path(d))
            app = FastAPI()
            role = {"v": "viewer"}
            bt.install_browser_task_routes(app, store, identity=lambda r: {"role": role["v"]},
                                           authorize_worker=lambda r: getattr(r, "worker", False))
            h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

            class Req:
                def __init__(self, body=None, worker=False):
                    self.body, self.worker = body, worker

                async def json(self):
                    return self.body
            with self.assertRaises(HTTPException) as e:
                h[("GET", "/api/factory/browser/tasks")](Req())
            self.assertEqual(e.exception.status_code, 403)
            role["v"] = "owner"
            task = asyncio.run(h[("POST", "/api/factory/browser/tasks")](Req({"url": "https://shop.example/", "selectors": ["h1"]})))["task"]
            with self.assertRaises(HTTPException) as e:
                h[("POST", "/api/factory/browser/worker/claim")](Req())
            self.assertEqual(e.exception.status_code, 401)
            self.assertEqual(h[("POST", "/api/factory/browser/worker/claim")](Req(worker=True))["task"]["id"], task["id"])
            res = asyncio.run(h[("POST", "/api/factory/browser/worker/{task_id}/result")](task["id"], Req({"status": "blocked", "blocker": "x"}, worker=True)))
            self.assertEqual(res["task"]["status"], "blocked")


class NavRequest(fx.FakeRequest):
    def __init__(self, url, method, navigation):
        super().__init__(url, method)
        self.navigation = navigation

    def is_navigation_request(self):
        return self.navigation


class ExecutorFlagsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, extra_requests, action_class="read", **flags):
        original = fx.FakePage.goto

        def goto(page, url, *, wait_until, timeout):
            original(page, url, wait_until=wait_until, timeout=timeout)
            for url2, method, nav in extra_requests:
                route = fx.FakeRoute(NavRequest(url2, method, nav))
                page.context.route_handler(route)
        policy = BrowserRuntimePolicy(allowed_origins=("https://shop.example",), artifact_root=self.root, **flags)
        plan = worker.build_plan({"id": "bt_0123456789abcdef", "url": "https://shop.example/item", "selectors": ["h1"]})
        if action_class != "read":
            plan = fx.plan(*plan.steps, action_class=action_class)
        with patch.object(fx.FakePage, "goto", goto):
            return run_playwright(plan, policy=policy, playwright_factory=fx.FakePlaywright)

    def test_offsite_subresources_only_for_read_and_only_get(self):
        cdn = [("https://cdn.example/app.js", "GET", False)]
        self.assertEqual(self.run_with(cdn).blocker_reason, "off_allowlist_network_request")          # default unchanged
        ok = self.run_with(cdn, allow_offsite_subresource_reads=True, return_extracted_text=True)
        self.assertEqual(ok.status, "done")
        self.assertEqual([r.get("text") for r in ok.action_log if r.get("type") == "extract"], ["Synthetic fixture heading"])
        for bad in ([("https://evil.example/", "GET", True)], [("https://cdn.example/collect", "POST", False)]):
            self.assertEqual(self.run_with(bad, allow_offsite_subresource_reads=True).status, "blocked", bad)
        self.assertEqual(self.run_with(cdn, action_class="draft", allow_offsite_subresource_reads=True).status, "blocked")
        plain = self.run_with([], allow_offsite_subresource_reads=True)
        self.assertNotIn("text", [k for r in plain.action_log for k in r])                           # text only when asked


class EgressProxyTest(unittest.TestCase):
    """Codex review on #334: the address is checked when the browser connects, for every host."""

    def connect(self, proxy, target):
        import socket
        with socket.create_connection(("127.0.0.1", int(proxy.url.rsplit(":", 1)[1])), timeout=5) as s:
            s.sendall(f"CONNECT {target} HTTP/1.1\r\nHost: {target}\r\n\r\n".encode())
            head = s.recv(1024).split(b"\r\n", 1)[0]
            if head.endswith(b"200 Connection Established"):
                s.sendall(b"ping")
                return head, s.recv(16)
            return head, b""

    def test_rebinding_and_private_subresources_are_refused_at_connect_time(self):
        from browser_runner.egress_proxy import PublicOnlyProxy
        answers = iter(["93.184.216.34", "169.254.169.254"])     # check sees public, the connection would see private
        rebinding = lambda host, port, proto=0: [(2, 1, 6, "", (next(answers), port))]
        self.assertTrue(worker.public_host("rebind.example", rebinding))   # the pre-launch check alone is fooled...
        with PublicOnlyProxy(resolve=rebinding) as proxy:
            head, _ = self.connect(proxy, "rebind.example:443")
        self.assertIn(b"403", head)                                          # ...the proxy is not
        mixed = lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", port)), (2, 1, 6, "", ("10.0.0.7", port))]
        with PublicOnlyProxy(resolve=mixed) as proxy:
            self.assertIn(b"403", self.connect(proxy, "cdn.internal-ish.example:443")[0])
            self.assertIn(b"403", self.connect(proxy, "93.184.216.34:22")[0])   # only https port
            self.assertEqual([r[0] for r in proxy.refused], ["address", "port"])

    def test_plain_http_refused_and_public_connect_tunnels(self):
        import socket
        import threading
        from browser_runner.egress_proxy import PublicOnlyProxy
        echo = socket.socket()
        echo.bind(("127.0.0.1", 0))
        echo.listen(1)

        def serve():
            conn, _ = echo.accept()
            with conn:
                conn.sendall(conn.recv(16).upper())
        threading.Thread(target=serve, daemon=True).start()
        port = echo.getsockname()[1]
        local = lambda host, p, proto=0: [(2, 1, 6, "", ("127.0.0.1", p))]
        with PublicOnlyProxy(resolve=local, allow=lambda a: a == "127.0.0.1", allowed_ports=(port,)) as proxy:
            head, reply = self.connect(proxy, f"shop.example:{port}")
            self.assertEqual((head, reply), (b"HTTP/1.1 200 Connection Established", b"PING"))
            with socket.create_connection(("127.0.0.1", int(proxy.url.rsplit(":", 1)[1])), timeout=5) as s:
                s.sendall(b"GET http://shop.example/ HTTP/1.1\r\nHost: shop.example\r\n\r\n")
                self.assertIn(b"403", s.recv(1024))
        echo.close()
        self.assertEqual(proxy.connected, ["shop.example"])

    def test_next_checked_address_is_tried_when_the_first_fails(self):
        import socket
        import threading
        from browser_runner import egress_proxy
        echo = socket.socket()
        echo.bind(("127.0.0.1", 0))
        echo.listen(1)
        port = echo.getsockname()[1]

        def serve():
            conn, _ = echo.accept()
            with conn:
                conn.sendall(conn.recv(16).upper())
        threading.Thread(target=serve, daemon=True).start()
        tried, real = [], socket.create_connection

        def connect(addr, timeout=None):
            tried.append(addr[0])
            if addr[0] == "2001:db8::1":                     # e.g. IPv6 first on an IPv4-only worker
                raise OSError("network unreachable")
            return real(addr, timeout=timeout)
        two = lambda host, p, proto=0: [(10, 1, 6, "", ("2001:db8::1", p, 0, 0)), (2, 1, 6, "", ("127.0.0.1", p))]
        with patch.object(egress_proxy, "_connect", connect), \
                egress_proxy.PublicOnlyProxy(resolve=two, allow=lambda a: a in ("2001:db8::1", "127.0.0.1"),
                                             allowed_ports=(port,)) as proxy:
            head, reply = self.connect(proxy, f"dual.example:{port}")
        echo.close()
        self.assertEqual(tried, ["2001:db8::1", "127.0.0.1"])
        self.assertEqual((head, reply), (b"HTTP/1.1 200 Connection Established", b"PING"))

    def test_worker_routes_the_browser_through_the_proxy(self):
        seen = []

        def runner(plan, *, policy):
            seen.append(policy.proxy_server)
            return run_playwright(plan, policy=policy, playwright_factory=fx.FakePlaywright)
        public = lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", port))]
        worker.execute({"id": "bt_0123456789abcdef", "url": "https://shop.example/", "selectors": []},
                       runner=runner, artifact_root=pathlib.Path(tempfile.mkdtemp()), resolve=public)
        self.assertTrue(seen[0].startswith("http://127.0.0.1:"))
        launched = {}
        original = fx.FakeChromium.launch

        def launch(chromium, **kwargs):
            launched.update(kwargs)
            return original(chromium, **kwargs)
        policy = BrowserRuntimePolicy(allowed_origins=("https://shop.example",), artifact_root=pathlib.Path(tempfile.mkdtemp()),
                                      proxy_server="http://127.0.0.1:1")
        with patch.object(fx.FakeChromium, "launch", launch):
            run_playwright(worker.build_plan({"id": "bt_0123456789abcdef", "url": "https://shop.example/", "selectors": []}),
                           policy=policy, playwright_factory=fx.FakePlaywright)
        self.assertEqual(launched["proxy"], {"server": "http://127.0.0.1:1", "bypass": "<-loopback>"})


class WorkerTest(unittest.TestCase):
    def test_ready_only_when_chromium_really_starts(self):
        ok = lambda: None

        def missing_package():
            raise ImportError("no playwright")

        def launch_fails():
            raise RuntimeError("error while loading shared libraries: libnss3.so")
        self.assertTrue(worker.playwright_available(ok, importer=ok))
        self.assertFalse(worker.playwright_available(ok, importer=missing_package))
        self.assertFalse(worker.playwright_available(launch_fails, importer=ok))       # binary present, cannot launch

    def test_failed_probe_is_retried_after_a_minute_success_is_cached(self):
        # Codex review on #336: installing Chromium must not leave tasks queued for the 10-minute cache.
        state = {"fail": True, "probes": 0}

        def probe():
            state["probes"] += 1
            if state["fail"]:
                raise RuntimeError("no chromium")
        t = [1000.0]
        with patch.object(worker, "_launch_probe", probe), patch.dict(worker._READY, {"at": 0.0, "ok": False}):
            check = lambda: worker.playwright_available(importer=lambda: None, clock=lambda: t[0])
            self.assertFalse(check())
            state["fail"] = False                     # owner installs Chromium
            t[0] = 1000.0 + worker.RETRY_SECONDS - 1
            self.assertFalse(check())                 # just inside the retry window: no new launch
            self.assertEqual(state["probes"], 1)
            t[0] = 1000.0 + worker.RETRY_SECONDS
            self.assertTrue(check())                  # exactly at RETRY_SECONDS the probe runs again
            self.assertEqual(state["probes"], 2)
            ok_at = t[0]
            t[0] = ok_at + worker.READY_CACHE_SECONDS - 1
            self.assertTrue(check())                  # success stays cached ...
            self.assertEqual(state["probes"], 2)
            t[0] = ok_at + worker.READY_CACHE_SECONDS
            self.assertTrue(check())                  # ... until READY_CACHE_SECONDS
            self.assertEqual(state["probes"], 3)

    def test_private_resolution_is_refused_before_any_browser(self):
        calls = []
        for addr in ("169.254.169.254", "10.1.2.3", "127.0.0.1"):
            out = worker.execute({"id": "bt_0123456789abcdef", "url": "https://rebind.example/", "selectors": []},
                                 runner=lambda *a, **k: calls.append(1), artifact_root=pathlib.Path("/tmp/x"),
                                 resolve=lambda host, port, proto=0, a=addr: [(2, 1, 6, "", (a, port))])
            self.assertEqual(out["blocker"], "host_not_public")
        self.assertEqual(calls, [])

    def test_claim_run_and_report(self):
        posts = []

        class Resp:
            def __init__(self, code, body):
                self.status_code, self.body = code, body

            def json(self):
                return self.body

        class Http:
            def post(self, url, headers, json, timeout):
                posts.append((url, json))
                if url.endswith("/claim"):
                    return Resp(200, {"task": {"id": "bt_0123456789abcdef", "url": "https://shop.example/item",
                                               "selectors": ["h1"], "action": "read"}})
                return Resp(200, {"task": {}})

        def runner(plan, *, policy):
            self.assertEqual((policy.allowed_origins, policy.allow_offsite_subresource_reads, policy.return_extracted_text),
                             (("https://shop.example",), True, True))
            self.assertEqual(plan.action_class, "read")
            return run_playwright(plan, policy=policy, playwright_factory=fx.FakePlaywright)
        with patch.object(worker.relay_tasks, "configured", return_value=True), \
                patch.object(worker.relay_tasks, "endpoint", return_value=("https://f", "tok")):
            public = lambda host, port, proto=0: [(2, 1, 6, "", ("93.184.216.34", port))]
            self.assertEqual(worker.run_one(http=Http(), runner=runner, available=lambda: True, resolve=public), "done")
            self.assertEqual(worker.run_one(http=Http(), runner=runner, available=lambda: False), "idle")
        url, body = posts[-1]
        self.assertTrue(url.endswith("/browser/worker/bt_0123456789abcdef/result"))
        self.assertEqual((body["status"], body["texts"]), ("done", [{"selector": "h1", "text": "Synthetic fixture heading"}]))
        self.assertTrue(base64.b64decode(body["screenshot_png_b64"]).startswith(b"\x89PNG"))
        self.assertEqual(json.loads(json.dumps(body))["final_url"], "https://shop.example")


if __name__ == "__main__":
    unittest.main(verbosity=2)
