"""T-560-H Surfer: the browser agent and web search for every agent connected to FactoryOS through /mcp.

Owner 2026-11-15: "им должны пользоваться все, кто подключен к Factory OS" (ChatGPT, Claude, Gemini). /mcp is the
one surface all three clients speak, so the Surfer is exposed there as three tools:

- web_read   — queue a read-only browser task (the EC2 runner opens the page in an anonymous Chromium) and wait up to
               ~40 s for the text it read; a slower task is returned as queued/running with its id.
- web_task   — the status/result of a task queued through MCP.
- web_search — web search through an official API. Search engines refuse the EC2 runner's datacenter address as
               automated traffic (checked 2026-11-15: DuckDuckGo, Mojeek, Startpage, Brave, Bing), and bypassing that
               is a T-560 non-goal, so search never goes through the browser.

Search providers: "wikipedia" (official MediaWiki API, free, no key, always available) and "gemini" (Gemini API with
Google Search grounding, using the key already configured for FactoryOS). Grounding can be billed beyond the free tier,
so Gemini search is off until the owner sets FACTORY_WEB_SEARCH_PROVIDER=gemini, and is capped per day.

The MCP token is shared by every client, so the `agent` argument is only a self-declared label for the history; it is
never treated as an authenticated identity.
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib import parse as urlparse
from urllib import request as urlrequest

from fastapi import HTTPException

MCP_SOURCE = "mcp"
WORKER_SOURCE = "worker"      # FactoryOS's own agents on EC2 (the Gemini coder loop), worker token
READ_WAIT_DEFAULT = 40
READ_WAIT_MAX = 50
POLL_SECONDS = 1.0
SEARCH_MAX_RESULTS = 10
GEMINI_DAILY_CAP = 100
USER_AGENT = "FactoryOS-Surfer/1.0 (read-only research tool)"
AGENT_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")
LANG_RE = re.compile(r"^[a-z]{2,3}$")
_TAG_RE = re.compile(r"<[^>]+>")

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web through FactoryOS (official search API, never scraping). Returns title, url and "
                       "snippet per result. Provider 'auto' uses Google Search via Gemini when the owner enabled it, "
                       "otherwise Wikipedia. Use web_read to open a result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for (max 300 chars)."},
                "limit": {"type": "integer", "minimum": 1, "maximum": SEARCH_MAX_RESULTS},
                "provider": {"type": "string", "enum": ["auto", "gemini", "wikipedia"]},
                "lang": {"type": "string", "description": "Wikipedia language code, e.g. en, uk, ru (default en)."},
                "agent": {"type": "string", "description": "Who is asking (chatgpt, claude, gemini…); a label only."},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_read",
        "description": "Open a public https page in the FactoryOS browser agent (real Chromium, read-only: no logins, "
                       "forms or purchases) and return the text of up to 5 CSS selectors (default: whole page) plus "
                       "whether a screenshot was taken. Waits up to wait_seconds; if the page is not done yet, call "
                       "web_task with the returned task id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https:// address of a public page."},
                "selectors": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                              "description": "CSS selectors to read; every match is read; missing ones are marked."},
                "wait_for": {"type": "string", "description": "Optional CSS selector to wait for before reading."},
                "wait_seconds": {"type": "integer", "minimum": 0, "maximum": READ_WAIT_MAX},
                "agent": {"type": "string", "description": "Who is asking (chatgpt, claude, gemini…); a label only."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_task",
        "description": "Status and result of a browser task started with web_read.",
        "inputSchema": {
            "type": "object",
            "properties": {"task_id": {"type": "string"}},
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)


def _agent_label(args: dict) -> str:
    agent = str(args.get("agent") or "").strip()
    return agent if AGENT_RE.fullmatch(agent) else "unknown"


def task_view(task: dict) -> dict:
    """What an agent sees of a task: no lease bookkeeping, no session binding."""
    result = task.get("result") or {}
    view = {"task_id": task["id"], "status": task["status"], "url": task["url"]}
    if task["status"] in ("queued", "running"):
        view["next"] = "call web_task with this task_id in a few seconds"
        return view
    view.update(final_url=result.get("final_url", ""), texts=result.get("texts", []),
                blocker=result.get("blocker", ""), screenshot=bool(result.get("screenshot")))
    if task["status"] == "waiting_human":
        view["next"] = "the page asked for a CAPTCHA/2FA/security check; the owner has to look at it"
    return view


async def web_read(store, args: dict, *, sleep=asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                   source: str = MCP_SOURCE) -> dict:
    selectors = args.get("selectors") or []
    if not isinstance(selectors, list):
        raise HTTPException(400, "selectors must be a list of CSS selectors")
    try:
        wait = int(args.get("wait_seconds", READ_WAIT_DEFAULT))
    except (TypeError, ValueError):
        raise HTTPException(400, "wait_seconds must be a number")
    wait = max(0, min(wait, READ_WAIT_MAX))
    note = f"via {'MCP' if source == MCP_SOURCE else 'worker'}, agent: {_agent_label(args)} (self-declared)"
    task = store.create(args.get("url", ""), selectors, note, source=source, wait_for=args.get("wait_for", ""))
    deadline = clock() + wait
    while task["status"] in ("queued", "running") and clock() < deadline:
        await sleep(POLL_SECONDS)
        task = store.get(task["id"]) or task
    return task_view(task)


def web_task(store, args: dict, *, source: str = MCP_SOURCE) -> dict:
    task_id = str(args.get("task_id") or "")
    task = store.get(task_id) if re.fullmatch(r"bt_[0-9a-f]{16}", task_id) else None
    if not task or task.get("source") != source:           # each caller sees only its own kind of task
        raise HTTPException(404, "unknown task")
    return task_view(task)


def _http_json(url: str, *, data: Optional[dict] = None, headers: Optional[dict] = None, opener=None,
               timeout: int = 20) -> dict:
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urlrequest.Request(url, data=body, method="POST" if body else "GET",
                             headers={"User-Agent": USER_AGENT, "Accept": "application/json",
                                      **({"Content-Type": "application/json"} if body else {}), **(headers or {})})
    with (opener or urlrequest.urlopen)(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_wikipedia(query: str, limit: int, lang: str = "en", *, opener=None) -> list:
    lang = lang if LANG_RE.fullmatch(lang or "") else "en"
    qs = urlparse.urlencode({"action": "query", "list": "search", "srsearch": query, "srlimit": limit,
                             "format": "json", "utf8": 1, "formatversion": 2})
    data = _http_json(f"https://{lang}.wikipedia.org/w/api.php?{qs}", opener=opener)
    out = []
    for row in ((data or {}).get("query") or {}).get("search") or []:
        title = str(row.get("title") or "")
        if not title:
            continue
        out.append({"title": title,
                    "url": f"https://{lang}.wikipedia.org/wiki/" + urlparse.quote(title.replace(" ", "_")),
                    "snippet": html.unescape(_TAG_RE.sub("", str(row.get("snippet") or "")))})
    return out[:limit]


class DailyCap:
    """Counts paid-capable searches per UTC day in a small file; the cap is checked before the provider is called."""

    def __init__(self, path: Path, cap: int, *, clock: Callable[[], float] = time.time):
        self.path, self.cap, self.clock, self.lock = Path(path), cap, clock, threading.Lock()

    def take(self) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        with self.lock:
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = {}
            used = int(state.get("used", 0)) if state.get("day") == day else 0
            if used >= self.cap:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"day": day, "used": used + 1}), encoding="utf-8")
            tmp.replace(self.path)
            return True


def search_gemini(query: str, limit: int, *, api_key: str, model: str, opener=None) -> dict:
    """Gemini with the google_search tool: a short answer plus the web sources Google returned for it."""
    payload = {"contents": [{"role": "user", "parts": [{"text": "Search the web and answer briefly, with sources: "
                                                                + query}]}],
               "tools": [{"google_search": {}}],
               "generationConfig": {"maxOutputTokens": 800, "temperature": 0.2}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    data = _http_json(url, data=payload, headers={"x-goog-api-key": api_key}, opener=opener, timeout=45)
    candidate = ((data or {}).get("candidates") or [{}])[0]
    answer = "".join(str(p.get("text") or "") for p in (candidate.get("content") or {}).get("parts") or [])
    results, seen = [], set()
    for chunk in (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []:
        web = chunk.get("web") or {}
        uri = str(web.get("uri") or "")
        if uri.startswith("https://") and uri not in seen:
            seen.add(uri)
            results.append({"title": str(web.get("title") or ""), "url": uri, "snippet": ""})
    return {"answer": answer.strip()[:4000], "results": results[:limit]}


GEMINI_FALLBACK_MODELS = ("gemini-flash-latest", "gemini-2.5-flash")
_GOOGLE_STATUS_RE = re.compile(r"^[A-Z_]{1,40}$")


def gemini_error(exc: Exception) -> str:
    """HTTP code plus Google's error enum (e.g. 'HTTP 400 INVALID_ARGUMENT'); never the free-text message."""
    code = getattr(exc, "code", None)
    if not code:
        return type(exc).__name__
    status = ""
    try:
        status = str((json.loads(exc.read().decode("utf-8")).get("error") or {}).get("status") or "")
    except Exception:
        pass
    return f"HTTP {int(code)}" + (f" {status}" if _GOOGLE_STATUS_RE.fullmatch(status) else "")


class WebSearch:
    def __init__(self, data_dir: Path, *, provider: Callable[[], str], gemini_key: Callable[[], str],
                 gemini_model: Callable[[str], str], opener=None, cap: int = GEMINI_DAILY_CAP):
        self.provider, self.gemini_key, self.gemini_model = provider, gemini_key, gemini_model
        self.opener = opener
        self.cap = DailyCap(Path(data_dir) / "web_search_usage.json", cap)

    def gemini_enabled(self) -> bool:
        return (self.provider() or "").strip().lower() == "gemini" and bool(self.gemini_key())

    def search(self, args: dict) -> dict:
        query = " ".join(str(args.get("query") or "").split())
        if not query or len(query) > 300:
            raise HTTPException(400, "query must be 1–300 characters")
        try:
            limit = max(1, min(int(args.get("limit") or 5), SEARCH_MAX_RESULTS))
        except (TypeError, ValueError):
            raise HTTPException(400, "limit must be a number")
        wanted = str(args.get("provider") or "auto").lower()
        if wanted not in ("auto", "gemini", "wikipedia"):
            raise HTTPException(400, "provider must be auto, gemini or wikipedia")
        notes = []
        if wanted in ("auto", "gemini"):
            if not self.gemini_enabled():
                if wanted == "gemini":
                    raise HTTPException(400, "Google search via Gemini is off: the owner has to set "
                                             "FACTORY_WEB_SEARCH_PROVIDER=gemini in Render")
                notes.append("Google search via Gemini is off (owner setting); Wikipedia used instead")
            elif not self.cap.take():
                if wanted == "gemini":
                    raise HTTPException(429, f"daily Gemini search cap ({self.cap.cap}) reached")
                notes.append(f"daily Gemini search cap ({self.cap.cap}) reached; Wikipedia used instead")
            else:
                key = self.gemini_key()
                models = list(dict.fromkeys([self.gemini_model(key), *GEMINI_FALLBACK_MODELS]))
                errors = []
                for model in models:          # a model without Search grounding answers 400/404: try the next Flash
                    try:
                        found = search_gemini(query, limit, api_key=key, model=model, opener=self.opener)
                        return {"provider": "gemini_google_search", "model": model, "query": query, **found}
                    except Exception as exc:
                        errors.append(f"{model}: {gemini_error(exc)}")
                        if getattr(exc, "code", None) not in (400, 404):
                            break
                reason = "; ".join(errors)
                if wanted == "gemini":
                    raise HTTPException(502, f"Gemini search failed ({reason})") from None
                notes.append(f"Gemini search failed ({reason}); Wikipedia used instead")
        try:
            results = search_wikipedia(query, limit, str(args.get("lang") or "en"), opener=self.opener)
        except Exception as exc:
            raise HTTPException(502, f"Wikipedia search failed ({type(exc).__name__})") from None
        out = {"provider": "wikipedia", "query": query, "results": results}
        if notes:
            out["note"] = "; ".join(notes)
        return out


async def call_tool(name: str, args: dict, *, store, search: WebSearch, source: str = MCP_SOURCE) -> dict:
    if not isinstance(args, dict):
        raise HTTPException(400, "arguments must be an object")
    if name == "web_read":
        return await web_read(store, args, source=source)
    if name == "web_task":
        return web_task(store, args, source=source)
    if name == "web_search":
        return await asyncio.to_thread(search.search, args)
    raise HTTPException(404, "unknown tool")


def install_worker_routes(app, *, store, search: WebSearch, authorize_worker: Callable) -> None:
    """The same three tools for FactoryOS's own EC2 agents (Gemini coder loop) with the worker token they already
    have, so no new secret is needed on EC2. POST /api/factory/surfer/worker/{web_search|web_read|web_task}."""
    from fastapi import Request

    @app.post("/api/factory/surfer/worker/{tool}")
    async def surfer_worker_tool(tool: str, request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if tool not in TOOL_NAMES:
            raise HTTPException(404, "unknown tool")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return await call_tool(tool, body if isinstance(body, dict) else {}, store=store, search=search,
                               source=WORKER_SOURCE)
