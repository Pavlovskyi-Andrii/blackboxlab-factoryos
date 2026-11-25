"""T-560 wiring: run the owner's read-only browser tasks on the EC2 worker (one per pass).

Claims a task from FactoryOS, builds a read plan (navigate → read each selector → one screenshot), runs it with the
bounded Playwright executor in an anonymous Chromium, and posts back the text it read plus the screenshot. Without
Playwright installed the worker says so once in the log and does nothing else.
"""
from __future__ import annotations

import base64
import ipaddress
import pathlib
import socket
import sys
import tempfile
from urllib.parse import urlsplit

try:
    from . import relay_tasks
except ImportError:
    import relay_tasks

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from browser_runner.core import BrowserActionPlan  # noqa: E402
from browser_runner.egress_proxy import PublicOnlyProxy  # noqa: E402
from browser_runner.playwright_executor import BrowserRuntimePolicy, run_playwright  # noqa: E402

_LOGGED = {"missing": False}


def log(message: str) -> None:
    print(f"browser-tasks: {message}", file=sys.stderr, flush=True)


def _launch_probe() -> None:
    """Start and close headless Chromium: proves the binary, its libraries and permissions, not just a path."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        p.chromium.launch(headless=True).close()


LAST_ERROR = {"claim": ""}   # T-728: the last claim failure, reported in the Surfer heartbeat ("" once a claim works)
READY_CACHE_SECONDS = 600
RETRY_SECONDS = 60          # a failed probe is retried after a minute, so a fresh install is picked up (Codex on #336)
_READY = {"at": 0.0, "ok": False}


def playwright_available(probe=None, *, importer=None, clock=None) -> bool:
    """Ready only when Chromium really starts (Codex reviews on #334/#335). Tasks stay queued otherwise; the reason is
    logged once. A probe result is reused for 10 minutes so an idle worker does not launch a browser every pass."""
    import time as _time
    now = (clock or _time.monotonic)()
    ttl = READY_CACHE_SECONDS if _READY["ok"] else RETRY_SECONDS
    if probe is None and _READY["at"] and now - _READY["at"] < ttl:
        return _READY["ok"]
    try:
        (importer or (lambda: __import__("playwright.sync_api")))()
        (probe or _launch_probe)()
        ready, reason = True, ""
    except ImportError:
        ready, reason = False, "Playwright is not installed"
    except Exception as exc:
        ready, reason = False, f"Chromium cannot start ({type(exc).__name__}); run: playwright install chromium"
    if probe is None:
        _READY.update(at=now, ok=ready)
    if not ready and _LOGGED.get("reason") != reason:
        _LOGGED["reason"] = reason
        log(reason + " on this worker; browser tasks wait (see docs/guides/browser-agent.md)")
    if ready:
        _LOGGED["reason"] = ""
    return ready


class _OneSession:
    """Hands the executor the storage_state the server sent with this task; nothing is written to disk."""

    def __init__(self, state: dict):
        self._state = state

    def load(self, *_a, **_k):
        state = self._state

        class _Revealed:
            def reveal(self):
                return state
        return _Revealed()


def build_plan(task: dict) -> BrowserActionPlan:
    steps = [{"type": "navigate", "url": task["url"]}]
    if task.get("wait_for"):
        steps.append({"type": "wait_for", "selector": task["wait_for"]})
    selectors = task.get("selectors") or []
    if selectors:
        steps += [{"type": "extract", "selector": s} for s in selectors]
    else:
        # T-670: no selectors → the main text of the page, its title and links (an explicit "body" still reads it all).
        steps.append({"type": "read_page"})
    steps.append({"type": "screenshot"})
    session = task.get("session") or {}
    return BrowserActionPlan(plan_id=task["id"], workspace_id="owner", provider=session.get("provider") or "web",
                             account_binding_id=session.get("account") or "anonymous",
                             session_ref=f"session://owner/{task['id']}" if session else "session://owner/anonymous",
                             action_class="read", steps=tuple(steps), timeout_seconds=90, max_steps=10)


def public_host(host: str, resolve=socket.getaddrinfo) -> bool:
    """The task host must resolve only to public addresses (no EC2 metadata, no private network)."""
    try:
        addresses = {info[4][0] for info in resolve(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return False
    return bool(addresses) and all(ipaddress.ip_address(a.split("%")[0]).is_global for a in addresses)


def execute(task: dict, *, runner=run_playwright, artifact_root: pathlib.Path, resolve=socket.getaddrinfo,
            proxy_factory=None) -> dict:
    parts = urlsplit(task["url"])
    if parts.scheme != "https" or not public_host(parts.hostname or "", resolve):   # fast fail; the proxy is the guard
        return {"status": "blocked", "blocker": "host_not_public", "texts": [], "steps": 0}
    # Codex review on #334: Chromium resolves names again, and sub-resources can name any host, so every connection
    # goes through a proxy that checks the address it actually connects to.
    session_store = None
    if task.get("session"):
        if not isinstance(task.get("storage_state"), dict):
            return {"status": "blocked", "blocker": "session_unavailable", "texts": [], "steps": 0}
        session_store = _OneSession(task["storage_state"])
    with (proxy_factory or (lambda: PublicOnlyProxy(resolve=resolve)))() as proxy:
        policy = BrowserRuntimePolicy(allowed_origins=(f"{parts.scheme}://{parts.netloc}",), artifact_root=artifact_root,
                                      allow_offsite_subresource_reads=True, return_extracted_text=True,
                                      proxy_server=proxy.url, allow_same_origin_xhr=bool(session_store))
        result = runner(build_plan(task), policy=policy, **({"session_store": session_store} if session_store else {}))
    task.pop("storage_state", None)                       # cookies leave memory with the task
    plan_steps = [dict(s) for s in build_plan(task).steps]
    selectors = [s["selector"] for s in plan_steps if s["type"] == "extract"]
    extracts = [row for row in result.action_log if row.get("type") == "extract"]
    texts = [dict({"selector": selectors[i], "text": row.get("text", "")}, **({"missing": True} if row.get("missing") else {}))
             for i, row in enumerate(extracts[:len(selectors)])]
    extra = {}
    for row in result.action_log:
        if row.get("type") == "navigate" and row.get("http_status"):
            extra["http_status"] = int(row["http_status"])
        elif row.get("type") == "read_page":
            extra["page"] = {k: row[k] for k in ("title", "description", "text", "links", "main") if k in row}
            texts = [{"selector": "(main content)", "text": row.get("text", "")}]
        elif row.get("type") == "redirect" and row.get("url"):
            extra["redirect_to"] = row["url"]
    shot = ""
    for ref in result.artifacts[:1]:
        path = artifact_root / ref.rsplit("/", 1)[-1]
        if path.is_file():
            shot = base64.b64encode(path.read_bytes()).decode()
    return {"status": result.status, "final_url": result.final_url, "blocker": result.blocker_reason,
            "steps": result.completed_steps, "texts": texts, "screenshot_png_b64": shot, **extra}


def run_one(*, http=None, runner=run_playwright, available=playwright_available, resolve=socket.getaddrinfo,
            on_claim=None) -> str:
    """idle | done | failed | error (queue unreachable). Never raises.

    ``on_claim(task_id)`` (T-714) runs right after a task is claimed, before Chromium starts: the dedicated Surfer
    worker reports "running" there."""
    if not relay_tasks.configured() or not available():
        return "idle"
    import requests
    http = http or requests
    url, token = relay_tasks.endpoint()
    headers = {"Authorization": "Bearer " + token}
    try:
        r = http.post(url + "/api/factory/browser/worker/claim", headers=headers, json={}, timeout=30)
        if r.status_code != 200:
            # T-728: a refused claim (401 token, 5xx) used to read as "idle": the worker beat "idle" for ever and the
            # queue never moved. Now it is an error the heartbeat reports (last_error) and the worker backs off.
            LAST_ERROR["claim"] = f"claim_http_{r.status_code}"
            log(f"claim refused: HTTP {r.status_code}")
            return "error"
        task = r.json().get("task")
    except Exception as exc:
        LAST_ERROR["claim"] = f"claim_{type(exc).__name__}"
        log(f"queue unavailable: {type(exc).__name__}")
        return "error"
    LAST_ERROR["claim"] = ""
    if not task:
        return "idle"
    if on_claim:
        try:
            on_claim(str(task.get("id") or ""))
        except Exception:
            pass
    log(f"running {task['id']} on {urlsplit(task['url']).netloc}" + (" (saved session)" if task.get("session") else ""))
    with tempfile.TemporaryDirectory(prefix="factoryos-browser-") as tmp:
        try:
            body = execute(task, runner=runner, artifact_root=pathlib.Path(tmp) / "shots", resolve=resolve)
        except Exception as exc:
            body = {"status": "failed", "blocker": f"worker_{type(exc).__name__}", "texts": []}
    try:
        resp = http.post(url + f"/api/factory/browser/worker/{task['id']}/result", headers=headers, json=body,
                         timeout=60)
    except Exception as exc:
        log(f"result not delivered: {type(exc).__name__}")
        return "failed"
    log(f"{task['id']} → {body['status']} {body.get('blocker', '')}".rstrip())
    return "done" if resp.status_code == 200 else "failed"
