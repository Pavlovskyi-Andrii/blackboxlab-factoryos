"""T-633 Product Evolution S4 (#270, M5): consent-aware in-product usage events for the pilot pages.

A pilot page asks once whether it may count the visitor anonymously. Only after "Allow" does the browser make a random
code, keep it in its own storage and send three kinds of first-party events: activated (opened with consent), used (did
the product's main action) and returned (came back on a later day). The T-630 ledger keeps one record per participant
and version - a hash of the code, the consent reference and three dates - and the Product Evolution funnel counts
those records instead of numbers typed by hand.

Rules
- Without `consent: true` and the current consent wording version nothing is stored. A changed wording asks again.
- Minimal data: no name, e-mail, account id, address, user agent, page content or timestamp finer than a UTC day.
  The client address is used only for an in-memory daily cap (hashed with a per-process salt, never written to disk).
- The holder of the code can export everything stored under it and delete it; both keep working when events are
  switched off (`FACTORY_USAGE_EVENTS=0`, the kill switch).
- First-party only: no third-party analytics, no cookies, no outbound message or invitation of any kind.
- A product behind the owner login (Decision Memory) keeps its usage route behind the same login.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_evolution import USAGE_STEPS, EvolutionError, EvolutionStore

CONSENT_VERSION = "usage-consent-v1"  # bump when the consent text in usage.js changes: every browser is asked again
PER_CLIENT_NEW_DAILY = 5      # new participants one client address may create per day
PER_CLIENT_CALLS_DAILY = 300  # all usage calls of one client address per day
GLOBAL_NEW_DAILY = 2000
ACTIONS = ("event", "export", "delete")

# One exact path per pilot page, next to its quiz path (mvp_quiz.QUIZZES), with the same login rule.
USAGE: dict[str, dict[str, str]] = {
    "mycast": {"api": "/api/mycast/usage", "access": "public"},
    "mybrief-pro": {"api": "/api/mybrief/public/usage", "access": "public"},
    "decision-memory": {"api": "/api/decision-memory/usage", "access": "owner"},
}


def enabled() -> bool:
    return os.environ.get("FACTORY_USAGE_EVENTS", "1").strip() != "0"


class UsageService:
    """Consent check, caps and the kill switch in front of `EvolutionStore.record_usage`."""

    def __init__(self, evolution: EvolutionStore, *, clock: Callable[[], float] = time.time):
        self.evo, self.clock = evolution, clock
        self._lock = threading.Lock()
        self._salt = secrets.token_hex(16)
        self._day, self._new, self._clients = "", 0, {}

    def config(self, pid: str) -> dict[str, Any]:
        self._known(pid)
        return {"project": pid, "enabled": enabled(), "consent_version": CONSENT_VERSION, "events": list(USAGE_STEPS),
                "stored": ["consent_ref", *USAGE_STEPS], "third_party": False}

    @staticmethod
    def _known(pid: str) -> None:
        if pid not in USAGE:
            raise EvolutionError("unknown_usage_project", 404)

    def _budget(self, client: str) -> list[int]:
        """[new participants, calls] of this client today; counts live in memory only."""
        day = datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")
        if day != self._day:
            self._day, self._new, self._clients = day, 0, {}
        key = hashlib.sha256(f"{self._salt}|{client}".encode()).hexdigest()[:20]
        return self._clients.setdefault(key, [0, 0])

    def handle(self, pid: str, body: dict[str, Any], *, client: str) -> dict[str, Any]:
        self._known(pid)
        action = str(body.get("action") or "")
        if action not in ACTIONS:
            raise EvolutionError("bad_action")
        with self._lock:
            mine = self._budget(client)
            if mine[1] >= PER_CLIENT_CALLS_DAILY:
                raise EvolutionError("daily_limit", 429)
            mine[1] += 1
            if action == "export":
                return self.evo.export_usage(pid, body.get("participant"))
            if action == "delete":
                return self.evo.delete_usage(pid, body.get("participant"))
            if not enabled():
                raise EvolutionError("usage_off", 503)
            if body.get("consent") is not True:
                raise EvolutionError("consent_required")
            if body.get("consent_version") != CONSENT_VERSION:
                raise EvolutionError("consent_changed", 409)
            out = self.evo.record_usage(pid, {
                "consent": True, "consent_ref": f"{pid}-usage:{CONSENT_VERSION}", "participant": body.get("participant"),
                "event": body.get("event")}, allow_new=mine[0] < PER_CLIENT_NEW_DAILY and self._new < GLOBAL_NEW_DAILY)
            if "activated" in out["recorded"]:
                mine[0] += 1
                self._new += 1
            return out


def install_mvp_usage_routes(app, service: UsageService, identity_fn: Callable, *,
                             client_fn: Callable[[Request], str] = lambda request: "?") -> None:
    """Per pilot page: GET (is counting on, which consent wording) and POST {action: event | export | delete}."""

    def _mount(pid: str, spec: dict[str, str]) -> None:
        owner_only = spec["access"] == "owner"

        def _denied(request: Request):
            if not owner_only:
                return None
            role = str((identity_fn(request) or {}).get("role") or "")
            if role == "owner":
                return None
            return JSONResponse({"detail": "owner_only" if role else "login_required"}, status_code=403 if role else 401)

        def usage_get(request: Request):
            return _denied(request) or service.config(pid)

        async def usage_post(request: Request):
            denial = _denied(request)
            if denial is not None:
                return denial
            try:
                body = await request.json()
            except (ValueError, TypeError):
                body = None
            if not isinstance(body, dict):
                return JSONResponse({"detail": "bad_body"}, status_code=400)
            try:
                return service.handle(pid, body, client=client_fn(request))
            except EvolutionError as exc:
                return JSONResponse({"detail": exc.code}, status_code=exc.status)

        slug = pid.replace("-", "_")
        app.get(spec["api"], name=f"{slug}_usage")(usage_get)
        app.post(spec["api"], name=f"{slug}_usage_post")(usage_post)

    for pid, spec in USAGE.items():
        _mount(pid, spec)
