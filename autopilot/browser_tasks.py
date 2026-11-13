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


def build_plan(task: dict) -> BrowserActionPlan:
    steps = [{"type": "navigate", "url": task["url"]}]
    steps += [{"type": "extract", "selector": s} for s in task.get("selectors") or ["body"]]
    steps.append({"type": "screenshot"})
    return BrowserActionPlan(plan_id=task["id"], workspace_id="owner", provider="web", account_binding_id="anonymous", session_ref="session://owner/anonymous",  # no store: never restored
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
    with (proxy_factory or (lambda: PublicOnlyProxy(resolve=resolve)))() as proxy:
        policy = BrowserRuntimePolicy(allowed_origins=(f"{parts.scheme}://{parts.netloc}",), artifact_root=artifact_root,
                                      allow_offsite_subresource_reads=True, return_extracted_text=True,
                                      proxy_server=proxy.url)
        result = runner(build_plan(task), policy=policy)
    selectors = task.get("selectors") or ["body"]
    extracts = [row for row in result.action_log if row.get("type") == "extract"]
    texts = [{"selector": selectors[i], "text": row.get("text", "")} for i, row in enumerate(extracts[:len(selectors)])]
    shot = ""
    for ref in result.artifacts[:1]:
        path = artifact_root / ref.rsplit("/", 1)[-1]
        if path.is_file():
            shot = base64.b64encode(path.read_bytes()).decode()
    return {"status": result.status, "final_url": result.final_url, "blocker": result.blocker_reason,
            "steps": result.completed_steps, "texts": texts, "screenshot_png_b64": shot}


def run_one(*, http=None, runner=run_playwright, available=playwright_available, resolve=socket.getaddrinfo) -> str:
    """idle | done | failed. Never raises."""
    if not relay_tasks.configured() or not available():
        return "idle"
    import requests
    http = http or requests
    url, token = relay_tasks.endpoint()
    headers = {"Authorization": "Bearer " + token}
    try:
        r = http.post(url + "/api/factory/browser/worker/claim", headers=headers, json={}, timeout=30)
        task = r.json().get("task") if r.status_code == 200 else None
    except Exception as exc:
        log(f"queue unavailable: {type(exc).__name__}")
        return "idle"
    if not task:
        return "idle"
    log(f"running {task['id']} on {urlsplit(task['url']).netloc}")
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
