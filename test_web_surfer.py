"""T-560-H Surfer over MCP: read tasks, private task lookup, search providers. Offline: fake HTTP, no browser."""
import asyncio
import io
import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-surfer-"))
os.environ.setdefault("FACTORY_MCP_TOKEN", "surfer-test-mcp-token-0123456789abcdef")

from fastapi import HTTPException  # noqa: E402

import browser_tasks as bt  # noqa: E402
import web_surfer as ws  # noqa: E402


class Opener:
    """Fake urlopen: records requests, answers from a list of JSON bodies (or raises an exception instance)."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, req, timeout):
        self.requests.append(req)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return io.BytesIO(json.dumps(answer).encode())


WIKI = {"query": {"search": [{"title": "Web browser", "snippet": "A <span class=\"searchmatch\">web</span> &amp; more"},
                             {"title": "Browser game", "snippet": "game"}]}}
GEMINI = {"candidates": [{"content": {"parts": [{"text": "Playwright is a browser automation library."}]},
                          "groundingMetadata": {"groundingChunks": [
                              {"web": {"uri": "https://vertexaisearch.cloud.google.com/a", "title": "playwright.dev"}},
                              {"web": {"uri": "https://vertexaisearch.cloud.google.com/a", "title": "dup"}},
                              {"web": {"uri": "javascript:alert(1)", "title": "bad"}}]}}]}


def search(tmp, provider="", key="", opener=None, cap=2):
    return ws.WebSearch(pathlib.Path(tmp), provider=lambda: provider, gemini_key=lambda: key,
                        gemini_model=lambda _k: "gemini-2.5-flash", opener=opener, cap=cap)


class ReadTaskTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = bt.BrowserTaskStore(pathlib.Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_web_read_waits_for_the_runner_and_returns_its_text(self):
        store = self.store

        async def runner_sleep(_seconds):            # the EC2 runner picks the task up while the tool waits
            task = store.claim()
            if task:
                store.finish(task["id"], {"status": "done", "final_url": "https://example.com", "steps": 3,
                                          "texts": [{"selector": "h1", "text": "", "missing": True},
                                                    {"selector": "p", "text": "Example"}]})
        view = asyncio.run(ws.web_read(store, {"url": "https://example.com", "selectors": ["h1", "p"],
                                               "agent": "chatgpt"}, sleep=runner_sleep))
        self.assertEqual(view["status"], "done")
        self.assertEqual(view["texts"][0], {"selector": "h1", "text": "", "chars": 0, "missing": True})
        self.assertEqual(view["texts"][1]["text"], "Example")
        saved = store.get(view["task_id"])
        self.assertEqual(saved["source"], "mcp")
        self.assertIn("chatgpt (self-declared)", saved["note"])

    def test_web_read_returns_the_task_id_when_the_runner_is_slow(self):
        ticks = iter(range(0, 1000, 10))
        view = asyncio.run(ws.web_read(self.store, {"url": "https://example.com", "wait_seconds": 30},
                                       sleep=lambda _s: asyncio.sleep(0), clock=lambda: next(ticks)))
        self.assertEqual(view["status"], "queued")
        self.assertIn("web_task", view["next"])
        self.assertEqual(ws.web_task(self.store, {"task_id": view["task_id"]})["status"], "queued")

    def test_web_read_keeps_the_queue_rules(self):
        for bad in ({"url": "http://example.com"}, {"url": "https://127.0.0.1/"}, {"url": "https://a.local/"},
                    {"url": "https://example.com", "selectors": "h1"},
                    {"url": "https://example.com", "selectors": ["<script>"]}):
            with self.assertRaises(HTTPException, msg=bad):
                asyncio.run(ws.web_read(self.store, dict(bad, wait_seconds=0)))
        view = asyncio.run(ws.web_read(self.store, {"url": "https://example.com", "agent": "<b>x</b>",
                                                    "wait_seconds": 0}))
        self.assertIn("agent: unknown", self.store.get(view["task_id"])["note"])

    def test_web_task_shows_only_mcp_tasks(self):
        owner = self.store.create("https://example.com", [], "owner task")
        claude = self.store.create("https://example.com", [], "", source="claude")
        for task in (owner, claude):
            with self.assertRaises(HTTPException) as err:
                ws.web_task(self.store, {"task_id": task["id"]})
            self.assertEqual(err.exception.status_code, 404)
        with self.assertRaises(HTTPException):
            ws.web_task(self.store, {"task_id": "../browser_tasks.json"})


class ReadingQualityTest(unittest.TestCase):
    """T-670: chunks of long text, page links, hints for every blocker, one JS-redirect follow."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = bt.BrowserTaskStore(pathlib.Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def finish(self, task, body):
        claimed = self.store.claim()
        self.assertEqual(claimed["id"], task["id"])
        return self.store.finish(task["id"], body)

    def test_main_text_comes_in_chunks_with_links(self):
        text = "".join(f"line {i:05d}\n" for i in range(3000))          # 33 000 chars
        task = self.store.create("https://docs.example/guide", [], "", source=ws.MCP_SOURCE)
        self.assertEqual(task["selectors"], [])
        links = [{"text": f"p{i}", "url": f"https://docs.example/p{i}"} for i in range(200)] + [{"url": "javascript:x"}]
        self.finish(task, {"status": "done", "final_url": "https://docs.example", "http_status": 200,
                           "texts": [{"selector": "(main content)", "text": text}],
                           "page": {"title": "Guide", "description": "d", "text": text, "links": links, "main": "main"}})
        saved = self.store.get(task["id"])["result"]
        self.assertEqual((saved["total_chars"], saved["links_total"], saved["texts"][0]["chars"]), (len(text), 150, len(text)))
        self.assertEqual(len(saved["texts"][0]["text"]), bt.MAX_TEXT)  # the task record (dashboard) stays small
        first = ws.web_task(self.store, {"task_id": task["id"]})
        self.assertEqual((first["title"], first["http_status"], first["offset"]), ("Guide", 200, 0))
        self.assertEqual(first["text"], text[:ws.READ_CHUNK_DEFAULT])
        self.assertEqual(first["next_offset"], ws.READ_CHUNK_DEFAULT)
        self.assertIn("offset=8000", first["next"])
        self.assertEqual((len(first["links"]), first["links_total"]), (ws.LINKS_DEFAULT, 150))
        self.assertNotIn("texts", first)                              # main-content task: one text, no duplicate
        joined, offset = "", 0
        while offset is not None:
            part = ws.web_task(self.store, {"task_id": task["id"], "offset": offset, "max_chars": 20000, "links": 0})
            self.assertNotIn("links", part)
            joined += part["text"]
            offset = part["next_offset"]
        self.assertEqual(joined, text)
        self.assertNotIn("hints", first)

    def test_selector_tasks_keep_texts_and_can_page_a_long_selector(self):
        table = "row\t" * 5000
        task = self.store.create("https://wiki.example/list", ["table", "#gone"], "", source=ws.MCP_SOURCE)
        self.finish(task, {"status": "done", "texts": [{"selector": "table", "text": table},
                                                        {"selector": "#gone", "text": "", "missing": True}]})
        view = ws.web_task(self.store, {"task_id": task["id"]})
        self.assertNotIn("text", view)
        self.assertEqual(view["texts"][0]["truncated"], True)
        self.assertEqual(view["texts"][0]["chars"], len(table))
        self.assertIn("#gone", view["hints"][0])
        rest = ws.web_task(self.store, {"task_id": task["id"], "offset": 6000})
        self.assertTrue(rest["text"].startswith(("### table\n" + table)[6000:6100]))

    def test_hints_name_the_next_step(self):
        cases = [
            ({"status": "blocked", "blocker": "host_not_public"}, "does not resolve"),
            ({"status": "failed", "blocker": "net_err_name_not_resolved"}, "does not exist"),
            ({"status": "failed", "blocker": "browser_execution_timeout"}, "did not finish"),
            ({"status": "waiting_human", "blocker": "bot_challenge"}, "anti-bot"),
            ({"status": "waiting_human", "blocker": "captcha"}, "CAPTCHA"),
            ({"status": "done", "http_status": 404, "texts": [{"selector": "(main content)", "text": "Not found " * 40}]},
             "HTTP 404"),
            ({"status": "done", "texts": [{"selector": "(main content)", "text": "Loading..."}]}, "JavaScript"),
        ]
        for body, words in cases:
            task = self.store.create("https://site.example/", [], "", source=ws.MCP_SOURCE)
            self.finish(task, body)
            view = ws.web_task(self.store, {"task_id": task["id"]})
            self.assertTrue(any(words in h for h in view.get("hints", [])), (body, view.get("hints")))
        task = self.store.create("https://docs.example/", ["#pathlib.Path.glob"], "", source=ws.MCP_SOURCE)
        self.finish(task, {"status": "done", "texts": [{"selector": "#pathlib.Path.glob", "text": "", "missing": True}]})
        hint = ws.web_task(self.store, {"task_id": task["id"]})["hints"][0]
        # T-674: the worker already tried the literal id, so the hint says so instead of a tip that would not help.
        self.assertIn("No element has the id pathlib.Path.glob (tried both as a literal id", hint)
        task = self.store.create("https://docs.example/", ["#a.b p"], "", source=ws.MCP_SOURCE)
        self.finish(task, {"status": "done", "texts": [{"selector": "#a.b p", "text": "", "missing": True}]})
        self.assertIn('[id="a.b"]', ws.web_task(self.store, {"task_id": task["id"]})["hints"][0])

    def test_queued_task_reports_its_place_in_the_queue(self):
        self.store.create("https://a.example/", [], "", source="claude")
        view = asyncio.run(ws.web_read(self.store, {"url": "https://b.example/", "wait_seconds": 0}))
        self.assertEqual((view["status"], view["queue_ahead"]), ("queued", 1))

    def test_web_read_follows_one_javascript_redirect(self):
        store, seen = self.store, []

        async def runner_sleep(_seconds):
            task = store.claim()
            if not task:
                return
            seen.append(task["url"])
            if task["url"] == "https://old.example/doc":
                store.finish(task["id"], {"status": "blocked", "blocker": "off_allowlist_network_request",
                                          "redirect_to": "https://new.example/doc"})
            else:
                store.finish(task["id"], {"status": "done", "texts": [{"selector": "(main content)", "text": "New home"}],
                                          "page": {"text": "New home " * 50, "title": "Moved"}})
        view = asyncio.run(ws.web_read(store, {"url": "https://old.example/doc"}, sleep=runner_sleep))
        self.assertEqual(seen, ["https://old.example/doc", "https://new.example/doc"])
        self.assertEqual((view["status"], view["title"], view["url"]), ("done", "Moved", "https://new.example/doc"))
        self.assertTrue(view["redirected_from_task"].startswith("bt_"))

    def test_redirect_to_a_private_address_is_not_followed(self):
        store = self.store

        async def runner_sleep(_seconds):
            task = store.claim()
            if task:
                store.finish(task["id"], {"status": "blocked", "blocker": "off_allowlist_network_request",
                                          "redirect_to": "https://10.0.0.1/admin"})
        view = asyncio.run(ws.web_read(store, {"url": "https://old.example/doc", "wait_seconds": 5}, sleep=runner_sleep))
        self.assertEqual(view["status"], "blocked")
        self.assertNotIn("redirected_from_task", view)
        self.assertEqual(len(store.list()), 1)

    def test_tool_descriptions_teach_usage(self):
        tools = {t["name"]: t for t in ws.TOOLS}
        for word in ("Example", "next_offset", "hints", "wait_for", "selectors"):
            self.assertIn(word, tools["web_read"]["description"])
        self.assertIn("offset", tools["web_task"]["inputSchema"]["properties"])
        self.assertIn("Example", tools["web_search"]["description"])


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tmp.cleanup()

    def test_wikipedia_is_the_default_and_gemini_is_never_called_without_opt_in(self):
        opener = Opener(WIKI)
        out = search(self.tmp.name, provider="", key="real-key", opener=opener).search(
            {"query": "web  browser", "limit": 2, "lang": "uk"})
        self.assertEqual(out["provider"], "wikipedia")
        self.assertEqual(out["results"][0], {"title": "Web browser", "url": "https://uk.wikipedia.org/wiki/Web_browser",
                                             "snippet": "A web & more"})
        self.assertIn("off", out["note"])
        self.assertEqual(len(opener.requests), 1)
        self.assertTrue(opener.requests[0].full_url.startswith("https://uk.wikipedia.org/w/api.php?"))
        self.assertIn("srsearch=web+browser", opener.requests[0].full_url)
        self.assertEqual(opener.requests[0].get_header("User-agent"), ws.USER_AGENT)
        with self.assertRaises(HTTPException) as err:
            search(self.tmp.name, key="real-key", opener=Opener()).search({"query": "x", "provider": "gemini"})
        self.assertEqual(err.exception.status_code, 400)

    def test_gemini_search_when_enabled_with_sources_and_daily_cap(self):
        opener = Opener(GEMINI, GEMINI, WIKI)
        s = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=2)
        out = s.search({"query": "what is playwright"})
        self.assertEqual(out["provider"], "gemini_google_search")
        self.assertEqual(out["answer"], "Playwright is a browser automation library.")
        self.assertEqual(out["results"], [{"title": "playwright.dev", "url": "https://vertexaisearch.cloud.google.com/a",
                                           "snippet": ""}])
        body = json.loads(opener.requests[0].data)
        self.assertEqual(body["tools"], [{"google_search": {}}])
        self.assertEqual(opener.requests[0].get_header("X-goog-api-key"), "k")
        s.search({"query": "second"})
        out = s.search({"query": "third"})                     # cap 2 reached → Wikipedia, Gemini not called
        self.assertEqual(out["provider"], "wikipedia")
        self.assertIn("cap", out["note"])
        self.assertEqual(len(opener.requests), 3)
        with self.assertRaises(HTTPException) as err:
            s.search({"query": "fourth", "provider": "gemini"})
        self.assertEqual(err.exception.status_code, 429)

    def test_gemini_failure_falls_back_without_leaking_the_error(self):
        out = search(self.tmp.name, provider="gemini", key="k",
                     opener=Opener(OSError("secret upstream text"), WIKI)).search({"query": "x"})
        self.assertEqual(out["provider"], "wikipedia")
        self.assertNotIn("secret", json.dumps(out))

    def test_gemini_error_reports_code_and_status_and_tries_fallback_models(self):
        import urllib.error

        def http_error(code, status, message):
            body = json.dumps({"error": {"code": code, "status": status, "message": message}}).encode()
            return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))
        opener = Opener(http_error(400, "INVALID_ARGUMENT", "secret detail AIzaXYZ"), GEMINI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "x"})
        self.assertEqual((out["provider"], out["model"]), ("gemini_google_search", "gemini-flash-latest"))
        self.assertIn("/models/gemini-2.5-flash:", opener.requests[0].full_url)   # resolved model first
        opener = Opener(http_error(429, "RESOURCE_EXHAUSTED", "quota secret"), GEMINI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "y"})
        self.assertEqual((out["provider"], out["model"]), ("gemini_google_search", "gemini-flash-latest"))  # 429 → next model
        opener = Opener(*[http_error(429, "RESOURCE_EXHAUSTED", "quota secret") for _ in range(3)], WIKI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "y2"})
        self.assertEqual(out["provider"], "wikipedia")
        self.assertIn("gemini-flash-lite-latest: HTTP 429 RESOURCE_EXHAUSTED", out["note"])
        self.assertNotIn("secret", json.dumps(out))
        self.assertEqual(len(opener.requests), 4)                  # 3 distinct models + Wikipedia
        opener = Opener(OSError("down"), WIKI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "y3"})
        self.assertEqual(len(opener.requests), 2)                  # a network error is not retried on another model
        opener = Opener(*[http_error(400, "bad status!", "m") for _ in range(3)], WIKI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "z"})
        self.assertIn("gemini-2.5-flash: HTTP 400;", out["note"])  # non-enum status text is dropped
        self.assertNotIn("bad status", out["note"])

    def test_production_sequence_404_429_then_flash_lite_and_three_attempt_cap(self):
        import urllib.error

        def http_error(code, status):
            body = json.dumps({"error": {"code": code, "status": status}}).encode()
            return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(body))
        opener = Opener(http_error(404, "NOT_FOUND"), http_error(429, "RESOURCE_EXHAUSTED"), GEMINI)
        out = search(self.tmp.name, provider="gemini", key="k", opener=opener, cap=10).search({"query": "q"})
        self.assertEqual((out["provider"], out["model"]), ("gemini_google_search", "gemini-flash-lite-latest"))
        self.assertIn("/models/gemini-flash-lite-latest:", opener.requests[2].full_url)
        s = ws.WebSearch(pathlib.Path(self.tmp.name), provider=lambda: "gemini", gemini_key=lambda: "k",
                         gemini_model=lambda _k: "gemini-9.9-flash",
                         opener=Opener(*[http_error(404, "NOT_FOUND") for _ in range(3)], WIKI), cap=10)
        out = s.search({"query": "q2"})                            # resolved model outside the fallback list
        self.assertEqual(len(s.opener.requests), 4)                # still 3 Gemini calls + Wikipedia
        self.assertIn("gemini-9.9-flash: HTTP 404", out["note"])
        self.assertNotIn("gemini-2.5-flash", out["note"])

    def test_query_validation(self):
        s = search(self.tmp.name, opener=Opener())
        for bad in ({"query": ""}, {"query": "x" * 301}, {"query": "x", "provider": "bing"}, {"query": "x", "limit": "a"}):
            with self.assertRaises(HTTPException, msg=bad):
                s.search(bad)


def mcp_call(factory, payload, token=None):
    """Calls the /mcp handler directly (CI has no HTTP client for TestClient)."""
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
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "query_string": b"", "headers": headers},
                      receive)
    response = asyncio.run(factory.factory_mcp(request))
    return response.status_code, json.loads(response.body or b"{}")


class WorkerRoutesTest(unittest.TestCase):
    def test_worker_routes_need_the_worker_token_and_keep_tasks_apart(self):
        from fastapi import FastAPI
        from starlette.requests import Request
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        store = bt.BrowserTaskStore(pathlib.Path(tmp.name))
        app = FastAPI()
        ws.install_worker_routes(app, store=store, search=search(tmp.name, opener=Opener(WIKI)),
                                 authorize_worker=lambda r: r.headers.get("authorization") == "Bearer w")
        endpoint = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/factory/surfer/worker/{tool}")

        def call(tool, body, token="w"):
            raw = json.dumps(body).encode()

            async def receive():
                return {"type": "http.request", "body": raw, "more_body": False}
            headers = [(b"authorization", ("Bearer " + token).encode())] if token else []
            return asyncio.run(endpoint(tool, Request({"type": "http", "method": "POST", "headers": headers,
                                                       "path": "/x", "query_string": b""}, receive)))
        with self.assertRaises(HTTPException) as err:
            call("web_search", {"query": "x"}, token="")
        self.assertEqual(err.exception.status_code, 401)
        with self.assertRaises(HTTPException) as err:
            call("shell", {})
        self.assertEqual(err.exception.status_code, 404)
        self.assertEqual(call("web_search", {"query": "web", "agent": "gemini"})["provider"], "wikipedia")
        view = call("web_read", {"url": "https://example.com", "wait_seconds": 0, "agent": "gemini"})
        self.assertEqual(store.get(view["task_id"])["source"], "worker")
        self.assertIn("via worker, agent: gemini", store.get(view["task_id"])["note"])
        self.assertEqual(call("web_task", {"task_id": view["task_id"]})["status"], "queued")
        with self.assertRaises(HTTPException):                   # an MCP caller cannot read worker tasks
            ws.web_task(store, {"task_id": view["task_id"]})
        mcp_task = store.create("https://example.com", [], "", source="mcp")
        with self.assertRaises(HTTPException):                   # and the worker cannot read MCP tasks
            call("web_task", {"task_id": mcp_task["id"]})


class McpEndpointTest(unittest.TestCase):
    def test_tools_listed_and_callable_through_mcp(self):
        import app as factory
        factory.WEB_SEARCH.opener = Opener(WIKI)
        token = factory.FACTORY_MCP_TOKEN
        _, listed = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token)
        names = {t["name"] for t in listed["result"]["tools"]}
        self.assertTrue({"web_search", "web_read", "web_task", "get_design_context"} <= names)
        self.assertEqual(mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})[0], 401)
        _, found = mcp_call(factory, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
            "name": "web_search", "arguments": {"query": "web browser", "agent": "gemini"}}}, token)
        self.assertEqual(json.loads(found["result"]["content"][0]["text"])["provider"], "wikipedia")
        _, queued = mcp_call(factory, {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
            "name": "web_read", "arguments": {"url": "https://example.com", "wait_seconds": 0}}}, token)
        self.assertEqual(json.loads(queued["result"]["content"][0]["text"])["status"], "queued")
        _, bad = mcp_call(factory, {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
            "name": "web_read", "arguments": {"url": "http://example.com"}}}, token)
        self.assertTrue(bad["result"]["isError"])


if __name__ == "__main__":
    unittest.main()
