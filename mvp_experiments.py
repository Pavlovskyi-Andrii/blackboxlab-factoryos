"""A/B Tester S1 (T-608, issue #348): experiments with two branches inside the existing MVP registry.

Design follows the S0 review (docs/reviews/MVP_AB_TESTER_S0_REVIEW.md §2.8, corrections 1–13):
- An experiment lives in the project record (`projects[pid]["experiments"][exp_id]`) of the same
  `mvp_factory.json`, written under the registry's own lock, idempotency table and event log. No new file,
  database, scheduler, worker or service. The project stage is never touched.
- Exactly two branches, `a` then `b`. "A above B" is a rendering rule derived from this order.
- `mode` is SEGMENT_COMPARISON (audience/positioning exploration, never a winner) or CONTROLLED_AB (declared future
  mode: accepted only as a draft, because no randomized assignment exists).
- No metrics, publishing, spend or outreach can be written here: measurement stays null, those approvals stay false,
  and channels stay placeholders. Preview approval is owner-only, per branch and per revision; editing a draft makes
  the new revision unapproved. An MVP preview approval never satisfies the job publish gate.
- Draft copy is checked against a deny-list of health/outcome claims and personal data (emails, phone numbers).
"""
from __future__ import annotations

import hashlib
import json
import re
import secrets
import time
from typing import Any, Awaitable, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_factory import EVIDENCE_CHECK, ID_RE, MvpError, MvpRegistry, _iso

SCHEMA = "mvp-experiment/1"
MODES = ("SEGMENT_COMPARISON", "CONTROLLED_AB")
BRANCH_IDS = ("a", "b")
CHANNELS = ("facebook", "tiktok")
CHOICES = ("continue_a", "continue_b", "both", "iterate", "pivot", "stop")
MAX_EXPERIMENTS = 20
PERSONA_RE = re.compile(r"^[a-z0-9_]{2,40}$")
METRIC_RE = re.compile(r"^[a-z0-9_]{2,60}$")
CREATE_FIELDS = {"id", "mode", "concept_id", "hypothesis", "primary_metric", "branches", "idempotency_key"}
BRANCH_FIELDS = {"id", "label", "persona"}
COPY_LIMITS = {"headline": 120, "subhead": 300, "cta": 40}
# Health/outcome promises and guarantees are refused in any language the owner writes in (correction 8).
DENY = re.compile(r"lose weight|weight loss|\bcure[sd]?\b|guarantee|\bheal(s|ed|ing)?\b|diagnos|"
                  r"похуд|схудн|вылеч|виліку|гаранти|излеч|диагноз|діагноз", re.I)
PII = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?<!\d)\+?\d(?:[\s().-]?\d){8,13}(?!\d)")


def _text(value: Any, limit: int, *, required: bool = False) -> str:
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise MvpError("bad_text")
    out = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", value).replace("\r", "").strip()
    if len(out) > limit:
        raise MvpError("text_too_long")
    if required and not out:
        raise MvpError("text_required")
    return out


def _check_copy_text(text: str) -> None:
    if DENY.search(text):
        raise MvpError("copy_health_claim")
    if PII.search(text):
        raise MvpError("copy_personal_data")


def _branch(spec: dict) -> dict:
    return {"id": spec["id"], "label": spec["label"], "persona": spec["persona"], "revision": 0, "copy": None,
            "content_job_id": None, "relay_ticket": None, "blocked": None,
            "approval": {"preview": None, "publish": False, "spend": False, "outreach": False},
            "channels": [{"id": c, "status": "placeholder"} for c in CHANNELS],
            "measurement": {"eligible_views": None, "signups": None, "activated": None, "cost_usd": None}}


def validate_create(body: dict) -> dict:
    """Return a clean experiment spec or raise MvpError with a stable code."""
    if not isinstance(body, dict):
        raise MvpError("bad_body")
    if set(body) - CREATE_FIELDS:
        raise MvpError("unknown_fields")
    exp_id = str(body.get("id") or "")
    if not ID_RE.match(exp_id):
        raise MvpError("bad_id")
    mode = body.get("mode")
    if mode not in MODES:
        raise MvpError("bad_mode")
    concept = str(body.get("concept_id") or "")
    if concept and not ID_RE.match(concept):
        raise MvpError("bad_concept")
    hypothesis = _text(body.get("hypothesis"), 500, required=True)
    _check_copy_text(hypothesis)
    metric = str(body.get("primary_metric") or "verified_signup_rate")
    if not METRIC_RE.match(metric):
        raise MvpError("bad_metric")
    branches = body.get("branches")
    if not isinstance(branches, list) or len(branches) != 2:
        raise MvpError("two_branches_required")
    clean = []
    for want, b in zip(BRANCH_IDS, branches):
        if not isinstance(b, dict):
            raise MvpError("bad_branch")
        extra = set(b) - BRANCH_FIELDS
        if extra & {"measurement", "metrics"}:
            raise MvpError("metrics_not_supported")
        if extra & {"approval", "publish", "spend", "outreach"}:
            raise MvpError("approval_not_settable")
        if extra & {"channels"}:
            raise MvpError("channels_are_placeholders")
        if extra:
            raise MvpError("unknown_fields")
        if b.get("id") != want:
            raise MvpError("branch_ids_a_b")   # exactly a then b; A is always rendered above B
        label = _text(b.get("label"), 80, required=True)
        _check_copy_text(label)
        persona = str(b.get("persona") or "")
        if not PERSONA_RE.match(persona):
            raise MvpError("bad_persona")      # a coarse owner-written marketing persona, never user attributes
        clean.append({"id": want, "label": label, "persona": persona})
    if clean[0]["persona"] == clean[1]["persona"] and mode == "SEGMENT_COMPARISON":
        raise MvpError("same_segment")         # a segment comparison needs two segments
    return {"id": exp_id, "mode": mode, "concept_id": concept, "hypothesis": hypothesis, "primary_metric": metric,
            "branches": clean}


def validate_copy(body: dict) -> dict:
    if not isinstance(body, dict):
        raise MvpError("bad_body")
    allowed = set(COPY_LIMITS) | {"bullets", "posts", "idempotency_key"}
    if set(body) - allowed:
        raise MvpError("unknown_fields")
    copy = {k: _text(body.get(k), n, required=(k == "headline")) for k, n in COPY_LIMITS.items()}
    bullets = body.get("bullets") or []
    if not isinstance(bullets, list) or len(bullets) > 5:
        raise MvpError("bad_bullets")
    copy["bullets"] = [_text(x, 140, required=True) for x in bullets]
    posts = body.get("posts") or {}
    if not isinstance(posts, dict) or set(posts) - {"short", "medium"}:
        raise MvpError("bad_posts")
    copy["posts"] = {}
    for kind, limit in (("short", 280), ("medium", 1000)):
        items = posts.get(kind) or []
        if not isinstance(items, list) or len(items) > 2:
            raise MvpError("bad_posts")
        copy["posts"][kind] = [_text(x, limit, required=True) for x in items]
    flat = [copy["headline"], copy["subhead"], copy["cta"], *copy["bullets"], *copy["posts"]["short"], *copy["posts"]["medium"]]
    for t in flat:
        _check_copy_text(t)
    return copy


def comparison(exp: dict) -> dict:
    """The only comparison S1 can state: none. A segment comparison never names a winner (correction 2)."""
    reason = "segment_comparison" if exp["mode"] == "SEGMENT_COMPARISON" else "not_instrumented"
    return {"winner": None, "lift": None, "significance": None, "reason": reason}


def view(exp: dict) -> dict:
    out = json.loads(json.dumps(exp))
    for b in out["branches"]:
        b.pop("content_job_claim", None)   # internal reservation token, never shown
        p = b["approval"]["preview"]
        b["preview_approved"] = bool(p) and p.get("rev") == b["revision"] and b["revision"] > 0
    out["comparison"] = comparison(exp)
    out["metric_status"] = "not_instrumented"
    return out


class Experiments:
    """Experiment writes on top of an MvpRegistry (same lock, same file, same keys table, same event log)."""

    def __init__(self, registry: MvpRegistry):
        self.r = registry

    # -- helpers ----------------------------------------------------------------------------------------------
    def _guard(self, data: dict, key: str, scope: dict):
        key = str(key or "")[:80]
        if key and key in data["keys"]:
            held = data["keys"][key]
            if {k: held.get(k) for k in scope} != scope:
                raise MvpError("idempotency_conflict", 409)
            return key, held.get("result")
        return key, None

    def _remember(self, data: dict, key: str, scope: dict, result: dict) -> None:
        if key:
            data["keys"][key] = dict(scope, result=result)

    def _event(self, data: dict, project: dict, actor: str, note: str, exp_id: str, branch: str = "",
               evidence: list | None = None) -> dict:
        now = _iso(self.r.clock())
        ev = {"id": f"ev-{len(data['events']) + 1}-{int(self.r.clock() * 1000)}", "project": project["id"], "at": now,
              "actor": actor, "kind": "note", "from_stage": project["stage"], "to_stage": project["stage"],
              "evidence": evidence or [], "evidence_check": EVIDENCE_CHECK, "note": note[:500],
              "experiment": exp_id, "branch": branch}
        data["events"].append(ev)
        return ev

    @staticmethod
    def _scope(op: str, pid: str, actor: str, payload: Any) -> dict:
        fp = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        return {"project": pid, "kind": "exp:" + op, "actor": actor, "fingerprint": fp}

    def _project(self, data: dict, pid: str) -> dict:
        project = data["projects"].get(pid)
        if not project:
            raise MvpError("unknown_project", 404)
        return project

    def _experiment(self, project: dict, exp_id: str, *, open_only: bool = True) -> dict:
        exp = (project.get("experiments") or {}).get(exp_id)
        if not exp:
            raise MvpError("unknown_experiment", 404)
        if open_only and exp["state"] == "closed":
            raise MvpError("experiment_closed", 409)
        return exp

    # -- operations -------------------------------------------------------------------------------------------
    def create(self, pid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        if actor_role not in ("owner", "member"):
            raise MvpError("forbidden", 403)
        spec = validate_create(body)
        who = actor or actor_role
        scope = self._scope("create", pid, who, spec)
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "experiment": done}
            project = self._project(data, pid)
            if project["stage"] == "rejected":
                raise MvpError("project_closed", 409)
            exps = project.setdefault("experiments", {})
            if spec["id"] in exps:
                raise MvpError("experiment_exists", 409)
            if len(exps) >= MAX_EXPERIMENTS:
                raise MvpError("experiment_limit", 409)
            now = _iso(self.r.clock())
            exp = {"id": spec["id"], "schema": SCHEMA, "mode": spec["mode"], "concept_id": spec["concept_id"],
                   "hypothesis": spec["hypothesis"], "primary_metric": spec["primary_metric"], "state": "draft",
                   "created_at": now, "updated_at": now, "created_by": who,
                   "branches": [_branch(b) for b in spec["branches"]], "decision": None}
            exps[spec["id"]] = exp
            self._event(data, project, who, f"Experiment {spec['id']} created ({spec['mode']}); drafts only, no worker started.",
                        spec["id"])
            result = view(exp)
            self._remember(data, key, scope, result)
            self.r._save(data)
            return {"duplicate": False, "experiment": result}

    def save_draft(self, pid: str, exp_id: str, branch_id: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        if actor_role not in ("owner", "member"):
            raise MvpError("forbidden", 403)
        if branch_id not in BRANCH_IDS:
            raise MvpError("unknown_branch", 404)
        copy = validate_copy(body)
        who = actor or actor_role
        scope = self._scope("draft", pid, who, [exp_id, branch_id, copy])
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "branch": done}
            project = self._project(data, pid)
            exp = self._experiment(project, exp_id)
            branch = next(b for b in exp["branches"] if b["id"] == branch_id)
            if branch["copy"] == copy:
                return {"duplicate": True, "branch": view(exp)["branches"][BRANCH_IDS.index(branch_id)]}
            branch["copy"], branch["revision"] = copy, branch["revision"] + 1   # new revision: preview not approved
            exp["updated_at"] = _iso(self.r.clock())
            self._event(data, project, who, f"Branch {branch_id.upper()} draft saved as revision {branch['revision']}.",
                        exp_id, branch_id)
            result = view(exp)["branches"][BRANCH_IDS.index(branch_id)]
            self._remember(data, key, scope, result)
            self.r._save(data)
            return {"duplicate": False, "branch": result}

    def approve_preview(self, pid: str, exp_id: str, branch_id: str, rev: Any, *, actor_role: str, actor: str = "") -> dict:
        if actor_role != "owner":
            raise MvpError("owner_only", 403)
        if branch_id not in BRANCH_IDS:
            raise MvpError("unknown_branch", 404)
        if type(rev) is not int or rev < 1:
            raise MvpError("bad_revision")
        who = actor or actor_role
        with self.r._lock:
            data = self.r._load()
            project = self._project(data, pid)
            exp = self._experiment(project, exp_id)
            branch = next(b for b in exp["branches"] if b["id"] == branch_id)
            if branch["revision"] != rev:
                raise MvpError("stale_revision", 409)        # approving revision n never approves n+1
            if (branch["approval"]["preview"] or {}).get("rev") == rev:
                return {"duplicate": True, "branch": view(exp)["branches"][BRANCH_IDS.index(branch_id)]}
            ev = self._event(data, project, who, f"Owner approved branch {branch_id.upper()} preview, revision {rev}. "
                             "This is not a publish approval.", exp_id, branch_id)
            branch["approval"]["preview"] = {"rev": rev, "event_id": ev["id"], "at": ev["at"]}
            exp["updated_at"] = ev["at"]
            self.r._save(data)
            return {"duplicate": False, "branch": view(exp)["branches"][BRANCH_IDS.index(branch_id)]}

    def decide(self, pid: str, exp_id: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        if actor_role != "owner":
            raise MvpError("owner_only", 403)
        if not isinstance(body, dict) or set(body) - {"choice", "note"}:
            raise MvpError("unknown_fields")             # no winner/lift fields can be stored
        choice = body.get("choice")
        if choice not in CHOICES:
            raise MvpError("bad_choice")
        note = _text(body.get("note"), 500)
        who = actor or actor_role
        with self.r._lock:
            data = self.r._load()
            project = self._project(data, pid)
            exp = self._experiment(project, exp_id)
            ev = self._event(data, project, who, f"Owner decision on {exp_id}: {choice}. {note}".strip(), exp_id)
            exp["decision"] = {"choice": choice, "note": note, "event_id": ev["id"], "at": ev["at"], "by": who}
            exp["state"], exp["updated_at"] = "closed", ev["at"]
            self.r._save(data)
            return {"experiment": view(exp)}


    # -- S3 (T-610): one Content Factory draft job per branch ------------------------------------------------
    CLAIM_SECONDS = 120

    def claim_content_job(self, pid: str, exp_id: str, branch_id: str, *, actor_role: str, actor: str = "") -> dict:
        """Reserve the branch under the registry lock before any job exists, so two clicks make one job.
        Returns {"existing": job_id} or {"token": ..., "brief": ..., "title": ...}."""
        if actor_role != "owner":
            raise MvpError("owner_only", 403)
        if branch_id not in BRANCH_IDS:
            raise MvpError("unknown_branch", 404)
        with self.r._lock:
            data = self.r._load()
            project = self._project(data, pid)
            exp = self._experiment(project, exp_id)
            branch = next(b for b in exp["branches"] if b["id"] == branch_id)
            if branch.get("content_job_id"):
                return {"existing": branch["content_job_id"]}
            prev = (branch["approval"]["preview"] or {}).get("rev")
            if not branch["revision"] or prev != branch["revision"]:
                raise MvpError("preview_not_approved", 409)   # the owner approves the draft before it is handed off
            claim = branch.get("content_job_claim") or {}
            if claim and time.time() - float(claim.get("at", 0)) < self.CLAIM_SECONDS:
                raise MvpError("content_job_pending", 409)
            token = secrets.token_hex(8)
            branch["content_job_claim"] = {"token": token, "at": time.time()}
            self.r._save(data)
            return {"token": token, "title": f"[A/B {exp_id} · {branch_id.upper()}] {branch['label']}"[:200],
                    "brief": content_brief(project, exp, branch)}

    def release_content_job(self, pid: str, exp_id: str, branch_id: str, token: str) -> None:
        with self.r._lock:
            data = self.r._load()
            b = self._branch_or_none(data, pid, exp_id, branch_id)
            if b and (b.get("content_job_claim") or {}).get("token") == token:
                b.pop("content_job_claim", None)
                self.r._save(data)

    def attach_content_job(self, pid: str, exp_id: str, branch_id: str, token: str, job_id: str, *, actor: str) -> dict:
        with self.r._lock:
            data = self.r._load()
            project = self._project(data, pid)
            exp = self._experiment(project, exp_id, open_only=False)
            branch = next(b for b in exp["branches"] if b["id"] == branch_id)
            if (branch.get("content_job_claim") or {}).get("token") == token:
                branch.pop("content_job_claim", None)
                branch["content_job_id"] = job_id
                self._event(data, project, actor, f"Branch {branch_id.upper()} handed to Content Factory as a draft job "
                            f"{job_id} (inbox). Nothing is published; publishing needs the job's own approval.", exp_id, branch_id)
                exp["updated_at"] = _iso(self.r.clock())
                self.r._save(data)
            return view(exp)["branches"][BRANCH_IDS.index(branch_id)]

    def _branch_or_none(self, data: dict, pid: str, exp_id: str, branch_id: str):
        exp = ((data["projects"].get(pid) or {}).get("experiments") or {}).get(exp_id)
        return next((b for b in exp["branches"] if b["id"] == branch_id), None) if exp else None


def content_brief(project: dict, exp: dict, branch: dict) -> str:
    """The job brief: everything Content Factory needs, and the limits it must keep (correction 10)."""
    c = branch.get("copy") or {}
    lines = [f"A/B experiment {exp['id']} · branch {branch['id'].upper()} · revision {branch['revision']}",
             f"Project: {project.get('title') or project['id']} ({project['id']})",
             f"Mode: {exp['mode']} — " + ("segment comparison, NOT a randomized A/B test; never claim a winner."
                                          if exp["mode"] == "SEGMENT_COMPARISON" else "controlled A/B is not instrumented yet."),
             f"Audience (persona): {branch['persona']} — {branch['label']}",
             f"Hypothesis: {exp.get('hypothesis', '')}", "",
             "Owner-approved landing copy for this branch:",
             f"- Headline: {c.get('headline', '')}", f"- Subheadline: {c.get('subhead', '')}", f"- CTA: {c.get('cta', '')}"]
    lines += [f"- Bullet: {x}" for x in c.get("bullets") or []]
    posts = c.get("posts") or {}
    lines += [f"- Short post draft: {x}" for x in posts.get("short") or []]
    lines += [f"- Medium post draft: {x}" for x in posts.get("medium") or []]
    lines += ["", "Rules: DRAFTS ONLY. Do not publish, schedule, buy ads or contact anyone. Facebook and TikTok are placeholders.",
              "No health or guaranteed-result claims; no personal data. Keep this branch's audience and CTA; do not mix in the other branch.",
              "Publishing later needs the owner's approval of this job in Review."]
    return "\n".join(lines)[:8000]


def experiments_view(project: dict) -> list[dict]:
    return [view(e) for e in sorted((project.get("experiments") or {}).values(), key=lambda e: e["created_at"])]


def install_mvp_experiment_routes(app, registry: MvpRegistry, identity_fn: Callable,
                                  create_job: Optional[Callable[[str, str], Awaitable[str]]] = None) -> Experiments:
    store = Experiments(registry)

    def _who(request: Request) -> tuple[str, str]:
        ident = identity_fn(request) or {}
        return str(ident.get("role") or ""), str(ident.get("email") or "")

    async def _body(request: Request):
        try:
            body = await request.json()
        except ValueError:
            return None
        return body if isinstance(body, dict) else None

    def _run(fn):
        try:
            return fn()
        except MvpError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mvp-factory/{project_id}/experiments")
    def mvp_experiments_list(project_id: str):
        def go():
            with registry._lock:
                data = registry._load()
            project = data["projects"].get(project_id)
            if not project:
                raise MvpError("unknown_project", 404)
            return {"project": project_id, "experiments": experiments_view(project),
                    "note": "Drafts only. No metrics, publishing, spend or outreach exist for experiments."}
        return _run(go)

    @app.post("/api/mvp-factory/{project_id}/experiments")
    async def mvp_experiment_create(project_id: str, request: Request):
        role, email = _who(request)
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        return _run(lambda: store.create(project_id, body, actor_role=role, actor=email))

    @app.post("/api/mvp-factory/{project_id}/experiments/{exp_id}/branches/{branch_id}/draft")
    async def mvp_experiment_draft(project_id: str, exp_id: str, branch_id: str, request: Request):
        role, email = _who(request)
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        return _run(lambda: store.save_draft(project_id, exp_id, branch_id, body, actor_role=role, actor=email))

    @app.post("/api/mvp-factory/{project_id}/experiments/{exp_id}/branches/{branch_id}/approve-preview")
    async def mvp_experiment_approve(project_id: str, exp_id: str, branch_id: str, request: Request):
        role, email = _who(request)
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        return _run(lambda: store.approve_preview(project_id, exp_id, branch_id, body.get("revision"),
                                                  actor_role=role, actor=email))

    @app.post("/api/mvp-factory/{project_id}/experiments/{exp_id}/branches/{branch_id}/content-job")
    async def mvp_experiment_content_job(project_id: str, exp_id: str, branch_id: str, request: Request):
        """T-610: one inbox job per branch, draft only. Never runs the job, never queues publishing, calls no provider."""
        role, email = _who(request)
        if create_job is None:
            return JSONResponse({"detail": "job_creation_unavailable"}, status_code=503)
        try:
            claim = store.claim_content_job(project_id, exp_id, branch_id, actor_role=role, actor=email)
        except MvpError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)
        if "existing" in claim:
            return {"job_id": claim["existing"], "existing": True}
        try:
            job_id = await create_job(claim["title"], claim["brief"])
        except Exception:
            store.release_content_job(project_id, exp_id, branch_id, claim["token"])
            raise
        branch = store.attach_content_job(project_id, exp_id, branch_id, claim["token"], job_id, actor=email or role)
        return {"job_id": job_id, "existing": False, "branch": branch}

    @app.post("/api/mvp-factory/{project_id}/experiments/{exp_id}/decision")
    async def mvp_experiment_decision(project_id: str, exp_id: str, request: Request):
        role, email = _who(request)
        body = await _body(request)
        if body is None:
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        return _run(lambda: store.decide(project_id, exp_id, body, actor_role=role, actor=email))

    return store
