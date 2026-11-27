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
LEASE_SECONDS = 300                  # T-728: a read task is bounded (~90 s + report); was 600
MAX_ATTEMPTS = 2                     # T-728: a task whose lease expired this many times fails as lease_expired
QUEUED_MAX_SECONDS = 1800            # T-728: a task nobody claimed for 30 min fails as queue_timeout (frees MAX_ACTIVE)
FALLBACK_POLL_SECONDS = 120         # T-728: claim requests this recent with no Surfer heartbeat = the fallback serves
STUCK_SECONDS = 120                  # T-728: queue health — the oldest queued task waits longer than this
MAX_SELECTORS = 5
MAX_SHOT_BYTES = 2 * 1024 * 1024
MAX_TEXT = 6000                      # per selector in the task record (dashboard); the full text is in browser_pages/
MAX_PAGE_TEXT = 100_000              # T-670: full text kept per task, read in chunks (web_task offset)
MAX_LINKS = 150
AGENT_DAILY_CAP = 200                # read tasks Claude may queue per 24 h with the browser-agent token (owner 2026-11-13)
ID_RE = re.compile(r"^bt_[0-9a-f]{16}$")
SELECTOR_RE = re.compile(r"^[^\x00-\x1f<>{};]{1,200}$")
SESSION_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
SESSION_ACCOUNT_RE = re.compile(r"^[\w.@+ -]{1,80}$")
MAX_WAIT_SELECTOR = 200
STATUSES = ("queued", "running", "done", "blocked", "failed", "waiting_human")
# T-714: the dedicated Surfer worker's heartbeat → the "surfer" lane in Worker Center.
SURFER_STATES = ("idle", "running", "unavailable", "queue_unreachable", "stopped")
SURFER_ONLINE_SECONDS = 180          # it beats every 30 s while idle
SURFER_OFFLINE_SECONDS = 3600
SAFE_TEXT_RE = re.compile(r"[^A-Za-z0-9_:+.\- ]")


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
        self.pages = Path(data_dir) / "browser_pages"
        self.beat_path = Path(data_dir) / "surfer_heartbeat.json"
        self.poll_path = Path(data_dir) / "surfer_claims.json"     # T-728: when the worker last asked for a task
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
        for task_id in drop:                                   # old screenshots and page texts go with their task
            (self.shots / f"{task_id}.png").unlink(missing_ok=True)
            (self.pages / f"{task_id}.json").unlink(missing_ok=True)
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
        # T-670: no selectors = "the main text of the page" (the worker picks the content, drops menus); an older worker
        # reads the whole body for an empty list, as it did for the former default ["body"].
        sel = [str(s).strip() for s in (selectors or []) if str(s).strip()][:MAX_SELECTORS]
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
                raise HTTPException(429, f"Забагато завдань у черзі — дочекайтеся виконання / queue full: {MAX_ACTIVE} "
                                         "tasks are queued or running; retry in about a minute")
            if source != "owner" and sum(t.get("source") == source and t.get("created", 0) > self.clock() - 86400
                                         for t in items) >= AGENT_DAILY_CAP:
                raise HTTPException(429, "daily cap for agent tasks reached")
            items.append(task)
            self._save(items)
        return task

    def list(self) -> list:
        with self.lock:
            return list(reversed(self._swept()))

    def _sweep(self, items: list, now: float) -> bool:
        """T-728: no task can sit at the head forever. A running task whose lease expired goes back to the queue
        (it keeps its place) until it has been handed out MAX_ATTEMPTS times, then fails as lease_expired; a task
        nobody claimed for QUEUED_MAX_SECONDS fails as queue_timeout. Returns True when something changed."""
        changed = False
        for t in items:
            if t["status"] == "running" and t.get("lease_until", 0) < now:
                if int(t.get("attempts") or 1) >= MAX_ATTEMPTS:
                    t.update(status="failed", lease_until=0, finished=int(now),
                             result={"blocker": "lease_expired", "final_url": "", "texts": [], "steps": 0,
                                     "screenshot": False, "attempts": int(t.get("attempts") or 1)})
                else:
                    t.update(status="queued", lease_until=0, requeued=int(now))
                changed = True
            elif t["status"] == "queued" and now - t.get("created", now) > QUEUED_MAX_SECONDS:
                t.update(status="failed", lease_until=0, finished=int(now),
                         result={"blocker": "queue_timeout", "final_url": "", "texts": [], "steps": 0,
                                 "screenshot": False, "worker": self._verdict(items, now)["verdict"]})
                changed = True
        return changed

    def _swept(self) -> list:
        """Load under the lock and apply the sweep (saved only when it changed something)."""
        items = self._load()
        if self._sweep(items, self.clock()):
            self._save(items)
        return items

    def claim(self) -> Optional[dict]:
        now = self.clock()
        with self.lock:
            items = self._load()
            changed = self._sweep(items, now)
            handed = None
            for t in items:
                if t["status"] == "queued":
                    t.update(status="running", lease_until=int(now + LEASE_SECONDS), claimed=int(now),
                             attempts=int(t.get("attempts") or 0) + 1)
                    handed = {k: t[k] for k in ("id", "url", "selectors", "action", "session", "wait_for") if k in t}
                    break
            if changed or handed:
                self._save(items)
            self._write_poll(now, handed["id"] if handed else "")
        return handed

    def _write_poll(self, now: float, task_id: str) -> None:
        try:
            poll = json.loads(self.poll_path.read_text(encoding="utf-8"))
            poll = poll if isinstance(poll, dict) else {}
        except (OSError, ValueError):
            poll = {}
        poll["last_poll"] = now
        if task_id:
            poll.update(last_claim=now, last_task=task_id)
        try:
            self.poll_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.poll_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(poll), encoding="utf-8")
            tmp.replace(self.poll_path)
        except OSError:
            pass

    def _read_json(self, path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def _verdict(self, items: list, now: float) -> dict:
        """T-728 queue health, agent-readable: tells "worker down" from "worker alive but not claiming" from
        "queue blocked". Only facts from the heartbeat, the claim log and the task list; no secrets."""
        beat, poll = self._read_json(self.beat_path), self._read_json(self.poll_path)
        active = [t for t in items if t.get("status") in ("queued", "running")]
        queued = [t for t in active if t["status"] == "queued"]
        oldest = min((t.get("created", now) for t in queued), default=None)
        oldest_age = round(now - oldest, 1) if oldest is not None else None
        head = active[0] if active else None

        def age(ts):
            return round(max(0.0, now - float(ts)), 1) if ts else None
        beat_age, poll_age = age(beat.get("last_seen")), age(poll.get("last_poll"))
        state = str(beat.get("state") or "")
        if beat_age is None or beat_age > SURFER_ONLINE_SECONDS or state == "stopped":
            # The Claude worker's in-loop fallback claims read tasks while the Surfer worker is down (it sends no
            # Surfer heartbeat): recent claim requests mean reads are served, only actions wait for the Surfer worker.
            verdict = "fallback_serving" if poll_age is not None and poll_age <= FALLBACK_POLL_SECONDS else "worker_offline"
        elif state == "unavailable":
            verdict = "worker_unavailable"
        elif state == "queue_unreachable" or beat.get("last_error"):
            verdict = "worker_cannot_claim"
        elif oldest_age is not None and oldest_age > STUCK_SECONDS and (poll_age is None or poll_age > STUCK_SECONDS):
            verdict = "worker_not_claiming"
        elif oldest_age is not None and oldest_age > STUCK_SECONDS:
            verdict = "queue_blocked"
        else:
            verdict = "ok"
        out = {"verdict": verdict, "queued": len(queued), "running": len(active) - len(queued),
               "oldest_queued_age_seconds": oldest_age,
               "worker": {"state": state or "never_seen", "heartbeat_age_seconds": beat_age,
                          "last_poll_age_seconds": poll_age, "last_claim_age_seconds": age(poll.get("last_claim")),
                          "last_claimed_task": str(poll.get("last_task") or ""),
                          "last_result": str(beat.get("last_result") or ""),
                          "last_error": str(beat.get("last_error") or ""), "version": str(beat.get("version") or "")}}
        if head:
            out["head"] = {"task_id": head["id"], "status": head["status"], "age_seconds": age(head.get("created")),
                           "attempts": int(head.get("attempts") or 0),
                           "lease_left_seconds": round(head.get("lease_until", 0) - now, 1)
                           if head["status"] == "running" else None}
        return out

    def queue_health(self) -> dict:
        now = self.clock()
        with self.lock:
            items = self._swept()
            return self._verdict(items, now)

    def finish(self, task_id: str, body: dict) -> dict:
        status = str(body.get("status") or "")
        if status not in STATUSES[2:]:
            raise HTTPException(400, "bad status")
        texts, full = [], []
        for row in (body.get("texts") or [])[:MAX_SELECTORS]:
            if isinstance(row, dict):
                text = str(row.get("text") or "")[:MAX_PAGE_TEXT]
                full.append({"selector": str(row.get("selector") or "")[:200], "text": text})
                texts.append(dict({"selector": full[-1]["selector"], "text": text[:MAX_TEXT], "chars": len(text)},
                                  **({"missing": True} if row.get("missing") else {})))
        page = body.get("page") if isinstance(body.get("page"), dict) else {}
        links = []
        for link in (page.get("links") or [])[:MAX_LINKS] if isinstance(page.get("links"), list) else []:
            url = str((link or {}).get("url") or "") if isinstance(link, dict) else ""
            if url.startswith("https://") and len(url) <= 500:
                links.append({"text": str(link.get("text") or "")[:120], "url": url})
        try:
            http_status = int(body.get("http_status") or 0)
        except (TypeError, ValueError):
            http_status = 0
        redirect_to = str(body.get("redirect_to") or "")
        redirect_to = redirect_to[:500] if redirect_to.startswith("https://") else ""
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
            if page:
                document = str(page.get("text") or "")[:MAX_PAGE_TEXT]
            elif len(full) == 1:
                document = full[0]["text"]
            else:
                document = "\n\n".join(f"### {row['selector']}\n{row['text']}" for row in full)
            self.pages.mkdir(parents=True, exist_ok=True)
            tmp = self.pages / f"{task_id}.tmp"
            tmp.write_text(json.dumps({"text": document[:MAX_PAGE_TEXT], "links": links}, ensure_ascii=False),
                           encoding="utf-8")
            tmp.replace(self.pages / f"{task_id}.json")
            result = {"final_url": str(body.get("final_url") or "")[:500], "texts": texts,
                      "blocker": str(body.get("blocker") or "")[:120], "steps": int(body.get("steps") or 0),
                      "screenshot": bool(shot), "total_chars": len(document[:MAX_PAGE_TEXT]), "links_total": len(links)}
            if page:
                result.update(mode="main_content", title=str(page.get("title") or "")[:300],
                              description=str(page.get("description") or "")[:500], main=str(page.get("main") or "")[:80])
            if http_status:
                result["http_status"] = http_status
            if redirect_to:
                result["redirect_to"] = redirect_to
            task.update(status=status, lease_until=0, finished=int(self.clock()), result=result)
            self._save(items)
            return task

    def record_heartbeat(self, body: dict) -> dict:
        """T-714: keep only secret-free, bounded fields of the Surfer worker heartbeat."""
        def num(key, limit):
            try:
                return max(0, min(int(body.get(key) or 0), limit))
            except (TypeError, ValueError):
                return 0
        state = str(body.get("state") or "")
        task_id = str(body.get("task_id") or "")
        beat = {"last_seen": self.clock(), "state": state if state in SURFER_STATES else "idle",
                "task_id": task_id if ID_RE.fullmatch(task_id) else "",
                "node_id": SAFE_TEXT_RE.sub("", str(body.get("node_id") or ""))[:80],
                "version": SAFE_TEXT_RE.sub("", str(body.get("version") or ""))[:20],
                "last_result": SAFE_TEXT_RE.sub("", str(body.get("last_result") or ""))[:80],
                "last_error": SAFE_TEXT_RE.sub("", str(body.get("last_error") or ""))[:80],
                "started_at": num("started_at", 1 << 40), "pid": num("pid", 1 << 30),
                "tasks_done": num("tasks_done", 1 << 30), "tasks_failed": num("tasks_failed", 1 << 30)}
        with self.lock:
            self.beat_path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.beat_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(beat), encoding="utf-8")
            tmp.replace(self.beat_path)
        return beat

    def surfer_lane(self) -> dict:
        """Worker Center lane of the Surfer worker, in the lane-board shape (state, task_id, last_event, …)."""
        try:
            beat = json.loads(self.beat_path.read_text(encoding="utf-8"))
            beat = beat if isinstance(beat, dict) else {}
        except (OSError, ValueError):
            beat = {}
        now = self.clock()
        with self.lock:
            items = self._load()
        queued = sum(1 for t in items if t.get("status") == "queued")
        seen = float(beat.get("last_seen") or 0)
        age = round(max(0.0, now - seen), 1) if seen else None
        state, task_id, reason = "offline", "", ""
        if age is not None and beat.get("state") != "stopped":
            if beat.get("state") == "running" and age <= LEASE_SECONDS:
                state, task_id = "working", str(beat.get("task_id") or "")
            elif age <= SURFER_ONLINE_SECONDS:
                state = "blocked" if beat.get("state") == "unavailable" else "idle"
                reason = "chromium_unavailable" if state == "blocked" else ""
            elif age <= SURFER_OFFLINE_SECONDS:
                state = "stale"
        at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seen)) if seen else ""
        return {"lane": "surfer", "state": state, "heartbeat_age_seconds": age, "task_id": task_id,
                "stage": "running" if task_id else "", "started_at": "", "reason": reason,
                "last_event": {"action": "heartbeat", "at": at} if at else {}, "queue_depth": queued,
                "tasks_done": int(beat.get("tasks_done") or 0), "tasks_failed": int(beat.get("tasks_failed") or 0),
                "version": str(beat.get("version") or ""), "node_id": str(beat.get("node_id") or ""),
                "queue_health": self._verdict(items, now), "source": "surfer-heartbeat"}

    def get(self, task_id: str) -> Optional[dict]:
        with self.lock:
            return next((t for t in self._swept() if t["id"] == task_id), None)

    def page(self, task_id: str) -> dict:
        """The full text and links the worker returned ({} for tasks finished before T-670)."""
        if not ID_RE.fullmatch(task_id):
            return {}
        try:
            value = json.loads((self.pages / f"{task_id}.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

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

    @app.get("/api/factory/browser/agent/queue")
    def browser_agent_queue(request: Request):
        """T-728: queue health for agents — worker down vs not claiming vs queue blocked."""
        agent(request)
        return store.queue_health()

    @app.get("/api/factory/browser/agent/tasks/{task_id}")
    def browser_agent_task(task_id: str, request: Request, offset: Optional[int] = None, max_chars: int = 8000,
                           links: int = 40):
        agent(request)
        task = store.get(task_id) if ID_RE.fullmatch(task_id) else None
        if not task or task.get("source") != "claude":
            raise HTTPException(404, "unknown task")
        # T-670: "view" is what MCP agents see (text chunk + next_offset, links, hints); "task" stays as before.
        import web_surfer
        args = {"task_id": task_id, "max_chars": max_chars, "links": links}
        if offset is not None:
            args["offset"] = offset
        return {"task": task, "view": web_surfer.web_task(store, args, source="claude")}

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

    @app.post("/api/factory/browser/worker/heartbeat")
    async def browser_worker_heartbeat(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        store.record_heartbeat(body if isinstance(body, dict) else {})
        return {"ok": True, "lane": store.surfer_lane()}

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
