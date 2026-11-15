"""T-560 wiring (owner 2026-11-13: "погнали"): a queue of browser tasks for the EC2 runner.

First slice is READ ONLY: the owner gives an https URL and up to five CSS selectors to read; the runner opens the page
in an anonymous Chromium (browser_runner.playwright_executor), returns the text it read and one screenshot. Forms,
logins, registration and purchases are not part of this slice: submit stays disabled in the executor, and the
approval-gated flow comes next. Nothing here runs a browser on the Render web service.
"""
from __future__ import annotations

import base64
import ipaddress
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

MAX_TASKS = 50                       # finished tasks kept
MAX_ACTIVE = 20                      # queued + running; new tasks are refused beyond this (Codex review on #334)
LEASE_SECONDS = 600
MAX_SELECTORS = 5
MAX_SHOT_BYTES = 2 * 1024 * 1024
MAX_TEXT = 6000
AGENT_DAILY_CAP = 200                # read tasks Claude may queue per 24 h with the browser-agent token (owner 2026-11-13)
ID_RE = re.compile(r"^bt_[0-9a-f]{16}$")
SELECTOR_RE = re.compile(r"^[^\x00-\x1f<>{};]{1,200}$")
SESSION_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
SESSION_ACCOUNT_RE = re.compile(r"^[\w.@+ -]{1,80}$")
MAX_WAIT_SELECTOR = 200
STATUSES = ("queued", "running", "done", "blocked", "failed", "waiting_human")


def check_url(url: str) -> str:
    """Public https URL only: no credentials in it, no IP literals in private ranges, no localhost."""
    url = str(url or "").strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or len(url) > 2000:
        raise HTTPException(400, "Потрібна адреса https://… без логіна в ній")
    host = parts.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal", ".localhost")):
        raise HTTPException(400, "Внутрішні адреси заборонені")
    try:
        if not ipaddress.ip_address(host).is_global:
            raise HTTPException(400, "Внутрішні адреси заборонені")
    except ValueError:
        pass
    return url


class BrowserTaskStore:
    def __init__(self, data_dir: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "browser_tasks.json"
        self.shots = Path(data_dir) / "browser_shots"
        self.clock, self.lock = clock, threading.Lock()

    def _load(self) -> list:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            return value if isinstance(value, list) else []
        except (OSError, ValueError):
            return []

    def _save(self, items: list) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        finished = [t for t in items if t["status"] not in ("queued", "running")]
        drop = {t["id"] for t in finished[:-MAX_TASKS]} if len(finished) > MAX_TASKS else set()
        keep = [t for t in items if t["id"] not in drop]       # queued/running tasks are never evicted
        for task_id in drop:                                   # old screenshots go with their task
            (self.shots / f"{task_id}.png").unlink(missing_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def create(self, url: str, selectors: list, note: str = "", source: str = "owner", session: Optional[dict] = None,
               wait_for: str = "") -> dict:
        url = check_url(url)
        if session is not None:
            provider, account = str(session.get("provider") or ""), str(session.get("account") or "")
            if not SESSION_SLUG_RE.fullmatch(provider) or not SESSION_ACCOUNT_RE.fullmatch(account):
                raise HTTPException(400, "bad session binding")
            session = {"provider": provider, "account": account}
        wait_for = str(wait_for or "").strip()
        if wait_for and not SELECTOR_RE.fullmatch(wait_for):
            raise HTTPException(400, "Некоректний CSS-селектор")
        sel = [str(s).strip() for s in (selectors or []) if str(s).strip()][:MAX_SELECTORS] or ["body"]
        if not all(SELECTOR_RE.fullmatch(s) for s in sel):
            raise HTTPException(400, "Некоректний CSS-селектор")
        task = {"id": "bt_" + secrets.token_hex(8), "url": url, "selectors": sel, "note": str(note or "")[:300],
                "action": "read", "status": "queued", "created": int(self.clock()), "lease_until": 0,
                "result": None, "source": source}
        if session:
            task["session"] = session          # provider/account only; the cookies stay in the vault
        if wait_for:
            task["wait_for"] = wait_for
        with self.lock:
            items = self._load()
            if sum(t["status"] in ("queued", "running") for t in items) >= MAX_ACTIVE:
                raise HTTPException(429, "Забагато завдань у черзі — дочекайтеся виконання")
            if source != "owner" and sum(t.get("source") == source and t.get("created", 0) > self.clock() - 86400
                                         for t in items) >= AGENT_DAILY_CAP:
                raise HTTPException(429, "daily cap for agent tasks reached")
            items.append(task)
            self._save(items)
        return task

    def list(self) -> list:
        with self.lock:
            return list(reversed(self._load()))

    def claim(self) -> Optional[dict]:
        now = self.clock()
        with self.lock:
            items = self._load()
            for t in items:
                if t["status"] == "queued" or (t["status"] == "running" and t.get("lease_until", 0) < now):
                    t.update(status="running", lease_until=int(now + LEASE_SECONDS), claimed=int(now))
                    self._save(items)
                    return {k: t[k] for k in ("id", "url", "selectors", "action", "session", "wait_for") if k in t}
        return None

    def finish(self, task_id: str, body: dict) -> dict:
        status = str(body.get("status") or "")
        if status not in STATUSES[2:]:
            raise HTTPException(400, "bad status")
        texts = []
        for row in (body.get("texts") or [])[:MAX_SELECTORS]:
            if isinstance(row, dict):
                texts.append(dict({"selector": str(row.get("selector") or "")[:200], "text": str(row.get("text") or "")[:MAX_TEXT]},
                                  **({"missing": True} if row.get("missing") else {})))
        shot = body.get("screenshot_png_b64") or ""
        with self.lock:
            items = self._load()
            task = next((t for t in items if t["id"] == task_id), None)
            if not task or task["status"] != "running":
                raise HTTPException(409, "task is not running")
            if shot:
                try:
                    raw = base64.b64decode(shot, validate=True)
                except ValueError:
                    raise HTTPException(400, "bad screenshot")
                if len(raw) > MAX_SHOT_BYTES or not raw.startswith(b"\x89PNG"):
                    raise HTTPException(400, "bad screenshot")
                self.shots.mkdir(parents=True, exist_ok=True)
                (self.shots / f"{task_id}.png").write_bytes(raw)
            task.update(status=status, lease_until=0, finished=int(self.clock()), result={
                "final_url": str(body.get("final_url") or "")[:500], "texts": texts,
                "blocker": str(body.get("blocker") or "")[:120], "steps": int(body.get("steps") or 0),
                "screenshot": bool(shot)})
            self._save(items)
            return task

    def get(self, task_id: str) -> Optional[dict]:
        with self.lock:
            return next((t for t in self._load() if t["id"] == task_id), None)

    def screenshot(self, task_id: str) -> Path:
        path = self.shots / f"{task_id}.png"
        if not ID_RE.fullmatch(task_id) or not path.is_file():
            raise HTTPException(404, "no screenshot")
        return path


def install_browser_task_routes(app, store: BrowserTaskStore, *, identity: Callable, authorize_worker: Callable,
                                authorize_agent: Optional[Callable] = None,
                                session_domains: Optional[Callable[[str, str], list]] = None,
                                session_state: Optional[Callable[[str, str], Optional[dict]]] = None) -> None:
    """session_domains(provider, account) -> cookie domains of a saved vault session ([] when none);
    session_state(provider, account) -> the decrypted Playwright storage_state, handed only to the worker."""

    def checked_session(body: dict, url: str) -> Optional[dict]:
        raw = body.get("session")
        if not raw:
            return None
        if not isinstance(raw, dict) or session_domains is None:
            raise HTTPException(400, "sessions are not available")
        domains = session_domains(str(raw.get("provider") or ""), str(raw.get("account") or ""))
        if not domains:
            raise HTTPException(404, "no saved browser session for this site/account")
        host = (urlsplit(check_url(url)).hostname or "").lower()
        if not any(host == d or host.endswith("." + d) for d in domains):
            raise HTTPException(400, "the page is not on a domain of this session")   # cookies never go elsewhere
        return raw
    def owner(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    @app.get("/api/factory/browser/tasks")
    def browser_tasks(request: Request):
        owner(request)
        return {"tasks": store.list()}

    @app.post("/api/factory/browser/tasks")
    async def browser_task_create(request: Request):
        owner(request)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        if not isinstance(body, dict):
            raise HTTPException(400, "json object required")
        return {"task": store.create(body.get("url", ""), body.get("selectors") or [], body.get("note", ""),
                                     session=checked_session(body, body.get("url", "")), wait_for=body.get("wait_for", ""))}

    @app.get("/api/factory/browser/tasks/{task_id}/screenshot")
    def browser_task_screenshot(task_id: str, request: Request):
        owner(request)
        return FileResponse(store.screenshot(task_id), media_type="image/png", headers={"Cache-Control": "private"})

    # Owner 2026-11-13: Claude queues read tasks itself and reads the results ("моего подтверждения не нужно").
    # The token (FACTORY_BROWSER_AGENT_TOKEN) opens only these three routes; tasks stay read-only and public-https-only.
    def agent(request: Request):
        if authorize_agent is None or not authorize_agent(request):
            raise HTTPException(401, "Browser agent token required")

    @app.post("/api/factory/browser/agent/tasks")
    async def browser_agent_create(request: Request):
        agent(request)
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        if not isinstance(body, dict):
            raise HTTPException(400, "json object required")
        task = store.create(body.get("url", ""), body.get("selectors") or [], body.get("note", ""), source="claude",
                            session=checked_session(body, body.get("url", "")), wait_for=body.get("wait_for", ""))
        return {"task": task}

    @app.get("/api/factory/browser/agent/tasks/{task_id}")
    def browser_agent_task(task_id: str, request: Request):
        agent(request)
        task = store.get(task_id) if ID_RE.fullmatch(task_id) else None
        if not task or task.get("source") != "claude":
            raise HTTPException(404, "unknown task")
        return {"task": task}

    @app.get("/api/factory/browser/agent/tasks/{task_id}/screenshot")
    def browser_agent_screenshot(task_id: str, request: Request):
        agent(request)
        task = store.get(task_id) if ID_RE.fullmatch(task_id) else None
        if not task or task.get("source") != "claude":
            raise HTTPException(404, "unknown task")
        return FileResponse(store.screenshot(task_id), media_type="image/png", headers={"Cache-Control": "private"})

    @app.post("/api/factory/browser/worker/claim")
    def browser_worker_claim(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        task = store.claim()
        if task and task.get("session"):
            try:
                state = session_state(task["session"]["provider"], task["session"]["account"]) if session_state else None
            except Exception:
                state = None
            task["storage_state"] = state      # None → the worker reports session_unavailable; never logged or stored
        return {"task": task}

    @app.post("/api/factory/browser/worker/{task_id}/result")
    async def browser_worker_result(task_id: str, request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if not ID_RE.fullmatch(task_id):
            raise HTTPException(404, "unknown task")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return {"task": store.finish(task_id, body if isinstance(body, dict) else {})}
