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

    def test_bounded_and_old_screenshots_removed(self):
        first = self.s.create("https://shop.example/0", [])
        self.s.claim()
        self.s.finish(first["id"], {"status": "done", "screenshot_png_b64": base64.b64encode(PNG).decode()})
        for i in range(bt.MAX_TASKS):
            self.s.create(f"https://shop.example/{i + 1}", [])
        self.assertEqual(len(self.s.list()), bt.MAX_TASKS)
        self.assertFalse((self.s.shots / f"{first['id']}.png").exists())


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


class WorkerTest(unittest.TestCase):
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
