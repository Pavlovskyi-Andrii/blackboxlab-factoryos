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

READ_CHUNK_DEFAULT = 8000
READ_CHUNK_MAX = 20000
LINKS_DEFAULT = 40
LINKS_MAX = 150

TOOLS = [
    {
        "name": "web_search",
        "description": "Search the web through FactoryOS (official search APIs, never scraping a search engine). "
                       "Returns {provider, results:[{title,url,snippet}], answer?, note?}. provider 'auto' uses Google "
                       "Search via Gemini when the owner enabled it, otherwise Wikipedia (a 'note' says which and why). "
                       "Then open a result with web_read. Example: {\"query\": \"playwright python locator docs\", "
                       "\"limit\": 5}. Tip: for library docs you often know the URL already (docs.python.org, "
                       "developer.mozilla.org, pypi.org/project/<name>/, github.com/<owner>/<repo>) - call web_read "
                       "directly.",
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
        "description": "Read a public https page with the FactoryOS browser agent (real Chromium on a server; "
                       "read-only: no logins, forms or purchases). WITHOUT selectors it returns the page's main text "
                       "(menus, sidebars and cookie banners removed), its title and its links - start here. The text "
                       "comes in chunks: if next_offset is set, call web_task {task_id, offset: next_offset} for the "
                       "next chunk. WITH selectors (max 5 CSS selectors) it returns every match of each selector in "
                       "'texts'; a selector that matched nothing is marked missing. Every answer has 'status' "
                       "(done/queued/running/blocked/failed/waiting_human) and, when something needs your action, "
                       "'hints' saying what to do next. Pages run in a queue (usually 5-30 s); if the page is not done "
                       "within wait_seconds you get status queued/running and a task_id for web_task. Examples: "
                       "{\"url\": \"https://docs.python.org/3/library/pathlib.html\"}; "
                       "{\"url\": \"https://pypi.org/project/requests/\", \"selectors\": [\"h1\", \".package-description__summary\"]}; "
                       "{\"url\": \"https://react.dev/learn\", \"wait_for\": \"article h1\"} for pages that render "
                       "with JavaScript. An id with dots is written [id=\"pathlib.Path.glob\"], not #pathlib.Path.glob.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https:// address of a public page."},
                "selectors": {"type": "array", "items": {"type": "string"}, "maxItems": 5,
                              "description": "Optional CSS selectors to read (every match is read; missing ones are "
                                             "marked). Omit to get the main text, title and links."},
                "wait_for": {"type": "string", "description": "Optional CSS selector to wait for before reading "
                                                              "(JavaScript-rendered pages)."},
                "wait_seconds": {"type": "integer", "minimum": 0, "maximum": READ_WAIT_MAX,
                                 "description": f"How long to wait for the result (default {READ_WAIT_DEFAULT})."},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": READ_CHUNK_MAX,
                              "description": f"Size of the text chunk returned (default {READ_CHUNK_DEFAULT})."},
                "agent": {"type": "string", "description": "Who is asking (chatgpt, claude, gemini…); a label only."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_task",
        "description": "Status and result of a task started with web_read, and the next chunks of its text. "
                       "Example: {\"task_id\": \"bt_0123456789abcdef\", \"offset\": 8000} returns the text from "
                       "character 8000 on; keep calling with the returned next_offset until it is null. 'links' "
                       "sets how many of the page's links to return (default 40, max 150; 0 for none).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string"},
                "offset": {"type": "integer", "minimum": 0, "description": "Start of the text chunk (default 0)."},
                "max_chars": {"type": "integer", "minimum": 1000, "maximum": READ_CHUNK_MAX},
                "links": {"type": "integer", "minimum": 0, "maximum": LINKS_MAX},
            },
            "required": ["task_id"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)

# What an agent should do about each blocker (T-670, Surfer benchmark 2026-11-16). Prefix match on the blocker code.
BLOCKER_HINTS = (
    ("host_not_public", "The address does not resolve to a public server (typo, a domain that does not exist, or an "
                        "internal host). Check the URL; web_search can find the right one."),
    ("net_err_name_not_resolved", "The domain does not exist (DNS). Check the URL; web_search can find the right one."),
    ("net_err_connection", "The site refused or dropped the connection. Retry later or use another source."),
    ("net_err_tunnel_connection_failed", "The connection was refused by the browser agent's safety proxy (a private "
                                         "address) or by the site. Check the URL."),
    ("net_err_cert", "The site's TLS certificate is invalid; the browser agent does not open such pages."),
    ("net_err_too_many_redirects", "The page redirects in a loop. Try the site's canonical URL."),
    ("net_err", "The browser could not load the page (network error). Retry once; if it fails again use another source."),
    ("off_allowlist_navigation", "The URL is not allowed for this task."),
    ("off_allowlist_network_request", "The page tried to move the browser to another site. If redirect_to is set, "
                                      "call web_read with that URL; otherwise use the site's canonical address "
                                      "(e.g. with or without www.)."),
    ("browser_write_request_blocked", "The page tried to send data (POST); read tasks never do that. Read a "
                                      "different page or narrower selectors."),
    ("irreversible", "The URL or selector looks like an action (post, delete, subscribe...); read tasks refuse it."),
    ("browser_execution_timeout", "The page did not finish in time. Retry once, or read specific selectors; a page "
                                  "that keeps loading forever cannot be read whole."),
    ("browser_runtime_TimeoutError", "Loading timed out. Retry once, or add wait_for with a selector that appears "
                                     "early."),
    ("browser_runtime", "The browser failed on this page. Retry once; if it fails again use another source."),
    ("session_unavailable", "The saved login for this site is not available; the owner has to save it again."),
    ("worker_", "The browser agent crashed on this page. Retry once; report the task_id if it repeats."),
)


def _blocker_hint(blocker: str) -> str:
    for prefix, text in BLOCKER_HINTS:
        if blocker.startswith(prefix):
            return text
    return ""


def _hints(task: dict, result: dict, document_chars: int) -> list:
    hints, status, blocker = [], task["status"], str(result.get("blocker") or "")
    if status == "waiting_human":
        if blocker == "bot_challenge":
            hints.append("The site shows an anti-bot check (e.g. Cloudflare 'Just a moment...') to automated "
                         "browsers; FactoryOS never bypasses it. Use another source: the site's official API, "
                         "a docs mirror, raw.githubusercontent.com, or web_search.")
        else:
            hints.append("The page asked for a CAPTCHA/2FA/security check; FactoryOS never solves it. The owner can "
                         "look at the screenshot; meanwhile use another source.")
    elif blocker:
        hint = _blocker_hint(blocker)
        if hint:
            hints.append(hint)
    if result.get("redirect_to"):
        hints.append(f"The page redirected to {result['redirect_to']} - call web_read with that url.")
    try:
        http_status = int(result.get("http_status") or 0)
    except (TypeError, ValueError):
        http_status = 0
    if http_status >= 400:
        hints.append(f"The site answered HTTP {http_status}; the text is its error page. Check the URL, or open a "
                     "parent page and follow one of its links.")
    missing = [row.get("selector", "") for row in result.get("texts") or [] if row.get("missing")]
    if missing:
        hint = (f"Selector(s) {', '.join(missing)} matched nothing. Call web_read without selectors to get the "
                "page's main text and links, then pick selectors that exist.")
        if any(sel.startswith("#") and any(c in sel[1:] for c in ".:") for sel in missing):
            hint += " An id that contains dots or colons is written [id=\"a.b\"], not #a.b."
        hints.append(hint)
    if status == "done" and not task.get("selectors") and document_chars < 200:
        hints.append("Very little text came back: the page may build its content with JavaScript. Retry with "
                     "wait_for set to a selector of the content (e.g. 'main h1' or 'article').")
    return hints


def _int_arg(args: dict, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(args.get(name, default) if args.get(name) is not None else default)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number")
    return max(low, min(value, high))


def _agent_label(args: dict) -> str:
    agent = str(args.get("agent") or "").strip()
    return agent if AGENT_RE.fullmatch(agent) else "unknown"


def task_view(task: dict, store=None, *, offset: int = 0, max_chars: int = READ_CHUNK_DEFAULT,
              links: int = LINKS_DEFAULT, chunk_requested: bool = False) -> dict:
    """What an agent sees of a task: no lease bookkeeping, no session binding. The text is a chunk of the full text
    the worker returned (store.page); `next_offset` points to the next chunk."""
    result = task.get("result") or {}
    view = {"task_id": task["id"], "status": task["status"], "url": task["url"]}
    if task["status"] in ("queued", "running"):
        if store is not None and task["status"] == "queued":
            ahead = sum(1 for t in store.list() if t["status"] in ("queued", "running")
                        and t.get("created", 0) <= task.get("created", 0) and t["id"] != task["id"])
            view["queue_ahead"] = ahead
        view["next"] = "call web_task with this task_id in 5-10 seconds"
        return view
    page = store.page(task["id"]) if store is not None and hasattr(store, "page") else {}
    document = str(page.get("text") or "")
    if not document and result.get("texts"):              # tasks finished before T-670 (or by an older worker)
        rows = result["texts"]
        document = rows[0].get("text", "") if len(rows) == 1 else "\n\n".join(
            f"### {r.get('selector', '')}\n{r.get('text', '')}" for r in rows)
    view.update(final_url=result.get("final_url", ""), blocker=result.get("blocker", ""),
                screenshot=bool(result.get("screenshot")))
    for key in ("http_status", "title", "description", "redirect_to"):
        if result.get(key):
            view[key] = result[key]
    if task.get("selectors"):
        view["texts"] = [dict(row, truncated=True) if int(row.get("chars") or 0) > len(row.get("text") or "") else row
                         for row in result.get("texts", [])]
    if not task.get("selectors") or chunk_requested:
        offset = max(0, min(offset, len(document)))
        chunk = document[offset:offset + max_chars]
        end = offset + len(chunk)
        view.update(text=chunk, offset=offset, total_chars=len(document), next_offset=end if end < len(document) else None)
        if end < len(document):
            view["next"] = f"more text: call web_task with task_id and offset={end}"
    page_links = page.get("links") if isinstance(page.get("links"), list) else []
    if links and page_links:
        view["links"] = page_links[:links]
        view["links_total"] = len(page_links)
    hints = _hints(task, result, len(document))
    if hints:
        view["hints"] = hints
    return view


async def web_read(store, args: dict, *, sleep=asyncio.sleep, clock: Callable[[], float] = time.monotonic,
                   source: str = MCP_SOURCE) -> dict:
    selectors = args.get("selectors") or []
    if not isinstance(selectors, list):
        raise HTTPException(400, "selectors must be a list of CSS selectors")
    wait = _int_arg(args, "wait_seconds", READ_WAIT_DEFAULT, 0, READ_WAIT_MAX)
    max_chars = _int_arg(args, "max_chars", READ_CHUNK_DEFAULT, 1000, READ_CHUNK_MAX)
    note = f"via {'MCP' if source == MCP_SOURCE else 'worker'}, agent: {_agent_label(args)} (self-declared)"
    task = store.create(args.get("url", ""), selectors, note, source=source, wait_for=args.get("wait_for", ""))
    deadline = clock() + wait
    redirected_from = ""
    while clock() < deadline:
        if task["status"] not in ("queued", "running"):
            target = ((task.get("result") or {}).get("redirect_to") or "") if task["status"] == "blocked" else ""
            if not target or redirected_from:
                break
            # T-670: the page moved the browser to another site (a JavaScript redirect); the task's origin is fixed,
            # so the agent's read follows once with a new task for the target (same URL rules apply).
            try:
                follow = store.create(target, selectors, note + ", redirect", source=source,
                                      wait_for=args.get("wait_for", ""))
            except HTTPException:
                break
            redirected_from, task = task["id"], follow
            continue
        await sleep(POLL_SECONDS)
        task = store.get(task["id"]) or task
    view = task_view(task, store, max_chars=max_chars)
    if redirected_from:
        view["redirected_from_task"] = redirected_from
    return view


def web_task(store, args: dict, *, source: str = MCP_SOURCE) -> dict:
    task_id = str(args.get("task_id") or "")
    task = store.get(task_id) if re.fullmatch(r"bt_[0-9a-f]{16}", task_id) else None
    if not task or task.get("source") != source:           # each caller sees only its own kind of task
        raise HTTPException(404, "unknown task")
    return task_view(task, store, offset=_int_arg(args, "offset", 0, 0, 10_000_000),
                     max_chars=_int_arg(args, "max_chars", READ_CHUNK_DEFAULT, 1000, READ_CHUNK_MAX),
                     links=_int_arg(args, "links", LINKS_DEFAULT, 0, LINKS_MAX),
                     chunk_requested=args.get("offset") is not None)


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
