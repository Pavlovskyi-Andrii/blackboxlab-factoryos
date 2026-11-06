"""#186 MVP Factory, phase 1: a durable registry of MVP projects and their evidence-backed events.

The state machine and role map come from ChatGPT's draft (PR #194, docs/MVP_FACTORY_SPEC.md and mvp_manager.py).
Claude adopted them when the owner reassigned #186 on 2026-11-06.

Rules:
- A stage changes only through a recorded event, and only one step forward. Every advance needs at least one evidence
  link (a GitHub issue/PR/commit/actions URL or a /static/ page). An LLM saying "done" is not evidence.
- owner_review -> validated and any rejection are owner-only. Blocking is allowed from any open stage and needs a reason.
- Nothing here dispatches a worker, calls a provider, spends money, deploys or publishes. `recommend()` only names the
  next role; the existing Relay queue stays the only executor.
- Writes are idempotent by `idempotency_key`; a repeat returns the first result and adds nothing.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

STAGES = ("idea", "researching", "spec_draft", "spec_review", "build_queued", "building", "qa_review",
          "preview_ready", "owner_review", "validated", "rejected")
TERMINAL = ("validated", "rejected")
NEXT = {"idea": "researching", "researching": "spec_draft", "spec_draft": "spec_review", "spec_review": "build_queued",
        "build_queued": "building", "building": "qa_review", "qa_review": "preview_ready",
        "preview_ready": "owner_review", "owner_review": "validated"}
ROLE = {"idea": "MVP Manager", "researching": "Product Analyst", "spec_draft": "Spec Writer", "spec_review": "MVP Manager",
        "build_queued": "Claude Builder", "building": "Claude Builder", "qa_review": "QA / Security",
        "preview_ready": "Deploy Agent", "owner_review": "Owner", "validated": "Content Factory", "rejected": "—"}
OWNER_ONLY_TARGETS = ("validated", "rejected")
KINDS = ("advance", "block", "unblock", "reject", "note")
MAX_EVENTS = 2000
MAX_NOTE = 500
REPO = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos"
EVIDENCE_RE = re.compile(r"^(https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(issues|pull|commit|actions/runs)/[A-Za-z0-9]+[^\s<>\"']*"
                         r"|/static/[A-Za-z0-9_./-]+)$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,40}$")


class MvpError(ValueError):
    """A refused event; `code` is a stable key the UI can translate."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _clean(text: Any, limit: int) -> str:
    return re.sub(r"[\u0000-\u001f<>]", "", str(text or "")).strip()[:limit]


def _seed(now: str) -> dict[str, Any]:
    """The starting registry, written once when no file exists. Every step cites what already happened on GitHub."""
    def ev(pid, i, kind, frm, to, evidence, note):
        return {"id": f"seed-{pid}-{i}", "project": pid, "at": now, "actor": "seed", "kind": kind,
                "from_stage": frm, "to_stage": to, "evidence": evidence, "note": note}

    mycast_steps = [
        ("idea", "researching", [f"{REPO}/issues/261"], "Owner requested the MyCast configurator pilot (#261)."),
        ("researching", "spec_draft", [f"{REPO}/issues/261"], "Issue #261 holds the audience, flow and taxonomy requirements."),
        ("spec_draft", "spec_review", ["/static/mycast-configurator/spec.json"], "Product Strategist output: spec.json."),
        ("spec_review", "build_queued", [f"{REPO}/issues/261"], "Owner expanded and approved the scope in #261 (2026-11-05)."),
        ("build_queued", "building", [f"{REPO}/pull/263"], "Web Builder: first prototype merged in PR #263."),
        ("building", "qa_review", [f"{REPO}/pull/271"], "Full acceptance build in PR #271."),
        ("qa_review", "preview_ready", ["/static/mycast-configurator/index.html", f"{REPO}/pull/267"],
         "QA: node tests in CI, Playwright at 390/1440; preview served on the site (PR #267)."),
    ]
    events = [ev("mycast", i, "advance", f, t, e, n) for i, (f, t, e, n) in enumerate(mycast_steps)]
    pilots = [("mycast", "MyCast · personal podcast configurator", 261, "preview_ready", "/static/mycast-configurator/index.html")]
    for issue, pid, title in ((187, "decision-memory", "AI Decision Memory"), (188, "mybrief-pro", "MyBrief for a profession"),
                              (189, "release-guardian", "AI Release Guardian")):
        pilots.append((pid, title, issue, "idea", ""))
        events.append(ev(pid, 0, "note", "idea", "idea", [f"{REPO}/issues/{issue}"], f"Pilot recorded from GitHub issue #{issue}."))
    projects = {pid: {"id": pid, "title": title, "issue": issue, "stage": stage, "blocked": None, "prototype": proto,
                      "cost_usd": 0, "approval": {"deploy": False, "outreach": False, "publish": False},
                      "created_at": now, "updated_at": now} for pid, title, issue, stage, proto in pilots}
    return {"version": 1, "projects": projects, "events": events, "keys": {}}


class MvpRegistry:
    """JSON-file registry. One web process writes it; the lock covers its threads."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("projects"), dict) and isinstance(data.get("events"), list):
                data.setdefault("keys", {})
                return data
        except FileNotFoundError:
            data = _seed(_iso(self.clock()))
            self._save(data)
            return data
        except (OSError, ValueError):
            pass
        raise MvpError("registry_unreadable", 503)  # never silently replace a damaged registry with the seed

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["events"] = data["events"][-MAX_EVENTS:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def snapshot(self, limit_events: int = 60) -> dict[str, Any]:
        with self._lock:
            data = self._load()
        projects = [dict(p, recommendation=recommend(p), history=[e for e in data["events"] if e["project"] == p["id"]][-20:])
                    for p in sorted(data["projects"].values(), key=lambda p: (STAGES.index(p["stage"]) * -1, p["id"]))]
        return {"stages": list(STAGES), "roles": ROLE, "projects": projects, "events": data["events"][-limit_events:],
                "note": "Stages change only through recorded events with evidence. No worker is started from here."}

    def record(self, project_id: str, kind: str, *, actor_role: str, actor: str = "", evidence: list[str] | None = None,
               note: str = "", reason: str = "", idempotency_key: str = "") -> dict[str, Any]:
        if kind not in KINDS:
            raise MvpError("bad_kind")
        key = _clean(idempotency_key, 80)
        evidence = [str(e).strip() for e in (evidence or []) if str(e).strip()][:5]
        bad = [e for e in evidence if not EVIDENCE_RE.match(e)]
        if bad:
            raise MvpError("bad_evidence")
        note, reason = _clean(note, MAX_NOTE), _clean(reason, 200)
        with self._lock:
            data = self._load()
            if key and key in data["keys"]:
                return {"duplicate": True, "event": data["keys"][key]}
            project = data["projects"].get(project_id)
            if not project:
                raise MvpError("unknown_project", 404)
            stage, to = project["stage"], project["stage"]
            if stage in TERMINAL and kind != "note":
                raise MvpError("project_closed", 409)
            if kind == "advance":
                if project.get("blocked"):
                    raise MvpError("project_blocked", 409)
                to = NEXT[stage]
                if not evidence:
                    raise MvpError("evidence_required")
                if to in OWNER_ONLY_TARGETS and actor_role != "owner":
                    raise MvpError("owner_only", 403)
            elif kind == "reject":
                if actor_role != "owner":
                    raise MvpError("owner_only", 403)
                to = "rejected"
            elif kind == "block":
                if not reason:
                    raise MvpError("reason_required")
                project["blocked"] = {"reason": reason, "at": _iso(self.clock())}
            elif kind == "unblock":
                if not project.get("blocked"):
                    raise MvpError("not_blocked", 409)
                project["blocked"] = None
            now = _iso(self.clock())
            event = {"id": f"ev-{len(data['events']) + 1}-{int(self.clock() * 1000)}", "project": project_id, "at": now,
                     "actor": _clean(actor, 80) or actor_role, "kind": kind, "from_stage": stage, "to_stage": to,
                     "evidence": evidence, "note": reason if kind == "block" else note}
            project["stage"], project["updated_at"] = to, now
            data["events"].append(event)
            if key:
                data["keys"][key] = event
                if len(data["keys"]) > MAX_EVENTS:
                    for old in list(data["keys"])[: len(data["keys"]) - MAX_EVENTS]:
                        del data["keys"][old]
            self._save(data)
            return {"duplicate": False, "event": event, "project": dict(project, recommendation=recommend(project))}

    def add_project(self, project_id: str, title: str, issue: int, *, actor_role: str) -> dict[str, Any]:
        if actor_role not in ("owner", "member"):
            raise MvpError("forbidden", 403)
        if not ID_RE.match(project_id or ""):
            raise MvpError("bad_id")
        title = _clean(title, 120)
        if not title or not isinstance(issue, int) or issue <= 0:
            raise MvpError("bad_project")
        with self._lock:
            data = self._load()
            if project_id in data["projects"]:
                raise MvpError("project_exists", 409)
            now = _iso(self.clock())
            data["projects"][project_id] = {"id": project_id, "title": title, "issue": issue, "stage": "idea", "blocked": None,
                                            "prototype": "", "cost_usd": 0, "approval": {"deploy": False, "outreach": False, "publish": False},
                                            "created_at": now, "updated_at": now}
            data["events"].append({"id": f"ev-{len(data['events']) + 1}-{int(self.clock() * 1000)}", "project": project_id, "at": now,
                                   "actor": actor_role, "kind": "note", "from_stage": "idea", "to_stage": "idea",
                                   "evidence": [f"{REPO}/issues/{issue}"], "note": "Project added."})
            self._save(data)
            return data["projects"][project_id]


def recommend(project: dict[str, Any]) -> dict[str, Any]:
    """Next step as a recommendation only (after #194's plan_mvp). It never claims or starts a worker."""
    stage = project.get("stage")
    if project.get("blocked"):
        return {"decision": "blocked", "reason": project["blocked"].get("reason", "")}
    if stage in TERMINAL:
        return {"decision": "hold", "reason": "closed"}
    if stage == "owner_review" or stage == "preview_ready":
        nxt = NEXT[stage]
        return {"decision": "owner", "next_stage": nxt, "role": "Owner", "reason": "owner review of the preview is required"}
    nxt = NEXT[stage]
    return {"decision": "recommend", "next_stage": nxt, "role": ROLE[nxt], "reason": "manual assignment only; no worker started"}


def install_mvp_factory_routes(app, registry: MvpRegistry, identity_fn: Callable) -> None:
    """GET /api/mvp-factory (any signed-in role) and POST event/project routes (viewers are refused by the app middleware)."""
    def _role(request: Request) -> tuple[str, str]:
        ident = identity_fn(request) or {}
        return str(ident.get("role") or ""), str(ident.get("email") or "")

    def _err(exc: MvpError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mvp-factory")
    def mvp_factory_snapshot(request: Request):
        try:
            return registry.snapshot()
        except MvpError as exc:
            return _err(exc)

    @app.post("/api/mvp-factory/{project_id}/events")
    async def mvp_factory_event(project_id: str, request: Request):
        role, email = _role(request)
        if role not in ("owner", "member"):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            return registry.record(project_id, str(body.get("kind") or ""), actor_role=role, actor=email,
                                   evidence=body.get("evidence") if isinstance(body.get("evidence"), list) else [],
                                   note=body.get("note") or "", reason=body.get("reason") or "",
                                   idempotency_key=body.get("idempotency_key") or "")
        except MvpError as exc:
            return _err(exc)

    @app.post("/api/mvp-factory/projects")
    async def mvp_factory_add(request: Request):
        role, _ = _role(request)
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        try:
            issue = body.get("issue")
            return registry.add_project(str(body.get("id") or ""), body.get("title") or "",
                                        issue if isinstance(issue, int) else 0, actor_role=role)
        except MvpError as exc:
            return _err(exc)
