"""T-670: re-run the Surfer benchmark against production through the agent REST.

  FACTORY_BROWSER_AGENT_TOKEN=… python tools/surfer_benchmark.py [--only key1,key2] > result.md

Queues real read-only tasks (public https pages, no logins), polls them, and prints a Markdown table with status, queue
wait, run time, blocker, amount of text and the first hint. At most 15 tasks are queued at once so the 20-task queue
cap is not hit. The token is read from the environment (or injected by a proxy) and never printed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("FACTORYOS_URL", "https://blackboxlab-factoryos.onrender.com").rstrip("/")
API = BASE + "/api/factory/browser/agent/tasks"
BATCH = 15

TASKS = [
    ("py-docs", "Python docs page, main text", {"url": "https://docs.python.org/3/library/pathlib.html"}),
    ("py-docs-id", "Python docs section, id with dots", {"url": "https://docs.python.org/3/library/pathlib.html",
                                                          "selectors": ['[id="pathlib.Path.glob"]']}),
    ("mdn", "MDN guide", {"url": "https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch"}),
    ("playwright", "playwright.dev (Docusaurus)", {"url": "https://playwright.dev/python/docs/locators"}),
    ("fastapi", "FastAPI docs (invisible reCAPTCHA)", {"url": "https://fastapi.tiangolo.com/tutorial/first-steps/"}),
    ("gh-docs", "docs.github.com article", {"url": "https://docs.github.com/en/rest/pulls/pulls"}),
    ("gh-readme", "GitHub README", {"url": "https://github.com/microsoft/playwright-python"}),
    ("gh-releases", "GitHub releases", {"url": "https://github.com/fastapi/fastapi/releases"}),
    ("changelog", "pip changelog", {"url": "https://pip.pypa.io/en/stable/news/"}),
    ("pypi", "PyPI package", {"url": "https://pypi.org/project/requests/"}),
    ("wiki", "Wikipedia article", {"url": "https://en.wikipedia.org/wiki/Playwright_(software)"}),
    ("spa", "react.dev (SPA)", {"url": "https://react.dev/learn"}),
    ("redirect", "redirect python.org → www", {"url": "https://python.org/"}),
    ("redirect-x", "redirect pypi.python.org → pypi.org", {"url": "https://pypi.python.org/pypi/requests"}),
    ("long", "very long page (os module)", {"url": "https://docs.python.org/3/library/os.html"}),
    ("antibot-so", "StackOverflow (anti-bot page)", {"url": "https://stackoverflow.com/questions/231767/"}),
    ("antibot-npm", "npm package (anti-bot page)", {"url": "https://www.npmjs.com/package/playwright"}),
    ("missing-sel", "missing selector", {"url": "https://example.com/", "selectors": ["#does-not-exist", "p"]}),
    ("404", "404 page", {"url": "https://docs.python.org/3/this-page-does-not-exist.html"}),
    ("slow", "slow page (8 s)", {"url": "https://httpbin.org/delay/8"}),
    ("table", "table (HTTP status codes)", {"url": "https://en.wikipedia.org/wiki/List_of_HTTP_status_codes",
                                            "selectors": ["table"]}),
    ("nodns", "domain that does not exist", {"url": "https://no-such-host-factoryos-bench.example/"}),
    ("raw", "raw.githubusercontent README", {"url": "https://raw.githubusercontent.com/microsoft/playwright-python/main/README.md"}),
]


def call(url: str, body: dict | None = None) -> dict:
    headers = {"content-type": "application/json"}
    token = os.environ.get("FACTORY_BROWSER_AGENT_TOKEN", "")
    if token:
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers,
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        return {"error": exc.code}


def run(tasks: list) -> list:
    rows = []
    for start in range(0, len(tasks), BATCH):
        pending = {}
        for key, what, body in tasks[start:start + BATCH]:
            answer = call(API, dict(body, note="surfer benchmark " + key))
            task = answer.get("task") or {}
            rows.append({"key": key, "what": what, "url": body["url"], "error": answer.get("error")})
            if task.get("id"):
                pending[task["id"]] = rows[-1]
            time.sleep(0.3)
        deadline = time.time() + 900
        while pending and time.time() < deadline:
            time.sleep(10)
            for task_id in list(pending):
                got = call(f"{API}/{task_id}")
                task = got.get("task") or {}
                if task.get("status") not in ("queued", "running", None):
                    pending.pop(task_id).update(task=task, view=got.get("view") or {})
    return rows


def table(rows: list) -> str:
    out = ["| Task | Status | Wait s | Run s | Text chars | Blocker | First hint |", "|---|---|---|---|---|---|---|"]
    for row in rows:
        task, view = row.get("task") or {}, row.get("view") or {}
        result = task.get("result") or {}
        wait = task.get("claimed", 0) - task.get("created", 0) if task.get("claimed") else ""
        took = task.get("finished", 0) - task.get("claimed", 0) if task.get("finished") else ""
        chars = view.get("total_chars", result.get("total_chars", sum(len(t.get("text", "")) for t in result.get("texts", []))))
        hint = (view.get("hints") or [""])[0][:90].replace("|", "/")
        status = task.get("status") or (f"HTTP {row['error']}" if row.get("error") else "timeout")
        out.append(f"| {row['key']} — {row['what']} | {status} | {wait} | {took} | {chars} | "
                   f"{result.get('blocker', '')} | {hint} |")
    return "\n".join(out)


if __name__ == "__main__":
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    print(table(run([t for t in TASKS if only is None or t[0] in only])))
