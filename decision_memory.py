"""#187 MVP Factory pilot 1 — AI Decision Memory (T-614).

A small owner-only web MVP: every decision has a rationale, a responsible person, source links, an expected outcome and
a follow-up review. The demo dataset is not invented: it is parsed at runtime from FactoryOS's own DECISIONS.md, so it
never drifts from the repository. DECISIONS.md records decisions and reasons, but not who is responsible, what result
was expected or when to look back — those fields stay empty in the import, and showing that gap is the point of the
pilot. The owner fills them in on the page; edits, new decisions and reviews persist in DATA_DIR/decision_memory.json.

Rules:
- No LLM, provider, network, payment or publishing call happens here. "AI" in the name is the product hypothesis; this
  pilot validates the memory/review loop first.
- Owner only, read and write (issue #187 does not authorize public access). The static page is only a shell; all data
  comes from /api/decision-memory behind the dashboard login.
- Imported text that looks like a credential is replaced by a redaction marker; submitted text that looks like a
  credential is refused.
- Writes that create something (a decision, a review) are idempotent by a client-made `idempotency_key`, bound to one
  operation: retrying returns the first result, reusing the key for different content is refused (409).
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from agent_secret_scan import contains_secret

REPO = "https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos"
ISSUE = 187
PAGE = "/static/decision-memory/index.html"
INTERVIEW_SCRIPT = f"{REPO}/blob/main/docs/mvp/decision-memory/INTERVIEW_SCRIPT.md"
REDACTED = "[redacted: credential-shaped text]"
VERDICTS = ("as_expected", "partly", "missed", "reversed")
MAX_CREATED = 500
MAX_REVIEWS = 50
MAX_KEYS = 2000
LIMITS = {"decision": 500, "rationale": 2000, "owner": 80, "expected_outcome": 500, "note": 1000, "title": 160}
URL_RE = re.compile(r"^(https://[A-Za-z0-9.-]+(?:/[^\s<>\"'`]*)?|/static/[A-Za-z0-9_./-]+)$")
HEAD_RE = re.compile(r"^## (.+?)\s*$")
DATE_RE = re.compile(r"(20\d\d-\d\d-\d\d)")
TASK_RE = re.compile(r"\bT-\d{3}(?:-[A-Z0-9]+)?\b")
REF_RE = re.compile(r"(?<![\w/&])#(\d{2,4})\b")


class DecisionError(ValueError):
    """A refused request; `code` is a stable key the page translates."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _plain(text: str) -> str:
    """Markdown bullet text to one plain line (the page escapes it again)."""
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _redact(text: str) -> tuple[str, bool]:
    return (REDACTED, True) if contains_secret(text) else (text, False)


def _record(*, heading: str, line: int, decision: str, rationale: str, index: int) -> dict[str, Any]:
    found = DATE_RE.search(heading)
    title = _plain(re.sub(r"^\s*20\d\d-\d\d-\d\d\s*[—–-]\s*", "", heading))
    decision, red1 = _redact(_plain(decision)[: LIMITS["decision"]])
    rationale, red2 = _redact(_plain(rationale)[: LIMITS["rationale"]])
    blob = " ".join((heading, decision, rationale))
    sources = [{"label": f"DECISIONS.md:{line}", "url": f"{REPO}/blob/main/DECISIONS.md#L{line}"}]
    for num in list(dict.fromkeys(REF_RE.findall(blob)))[:6]:
        sources.append({"label": f"#{num}", "url": f"{REPO}/issues/{num}"})
    digest = hashlib.sha256(f"{heading}|{index}|{decision[:160]}".encode()).hexdigest()[:12]
    return {"id": f"dmd-{digest}", "origin": "decisions_md", "date": found.group(1) if found else "",
            "title": title[: LIMITS["title"]], "decision": decision, "rationale": rationale,
            "tasks": sorted(set(TASK_RE.findall(blob))), "sources": sources, "owner": "", "expected_outcome": "",
            "review_at": "", "redacted": red1 or red2}


def parse_decisions(text: str) -> list[dict[str, Any]]:
    """DECISIONS.md -> records. A section with `**Decision:** … **Reason:** …` bullets gives one record per bullet;
    any other section gives one record: the heading is the decision, its body the rationale."""
    sections: list[tuple[str, int, list[tuple[int, str]]]] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        head = HEAD_RE.match(raw)
        if head:
            sections.append((head.group(1), number, []))
        elif sections:
            sections[-1][2].append((number, raw))
    out: list[dict[str, Any]] = []
    for heading, head_line, body in sections:
        bullets: list[tuple[int, list[str]]] = []
        for number, raw in body:
            if raw.startswith("- "):
                bullets.append((number, [raw[2:]]))
            elif bullets and raw.strip():
                bullets[-1][1].append(raw)
        explicit = [(n, " ".join(lines)) for n, lines in bullets if "**Decision:**" in lines[0]]
        if explicit:
            for i, (number, joined) in enumerate(explicit):
                decision, _, reason = joined.split("**Decision:**", 1)[1].partition("**Reason:**")
                out.append(_record(heading=heading, line=number, decision=decision, rationale=reason, index=i))
        else:
            rest = " ".join(re.sub(r"^\s*[-*]\s+", "", raw) for _, raw in body if raw.strip())
            out.append(_record(heading=heading, line=head_line, decision=re.sub(r"^\s*20\d\d-\d\d-\d\d\s*[—–-]\s*", "", heading),
                               rationale=rest, index=0))
    seen: dict[str, int] = {}
    for rec in out:  # identical headings + text would collide; keep ids unique and stable in file order
        n = seen.get(rec["id"], 0)
        seen[rec["id"]] = n + 1
        if n:
            rec["id"] = f"{rec['id']}-{n + 1}"
    return out


def _text(body: dict, field: str, *, required: bool = False) -> str:
    value = body.get(field, "")
    if value is None:
        value = ""
    if not isinstance(value, str):
        raise DecisionError("bad_field")
    value = re.sub(r"[\x00-\x08\x0b-\x1f<>]", " ", value).strip()
    if len(value) > LIMITS[field]:
        raise DecisionError("too_long")
    if required and not value:
        raise DecisionError(f"{field}_required")
    if contains_secret(value):
        raise DecisionError("secret_like_text")
    return value


def _day(body: dict, field: str) -> str:
    value = body.get(field, "")
    if value in (None, ""):
        return ""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise DecisionError("bad_date")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise DecisionError("bad_date") from exc
    return value


def _sources(body: dict) -> list[dict[str, str]]:
    raw = body.get("sources") or []
    if not isinstance(raw, list) or len(raw) > 6:
        raise DecisionError("bad_sources")
    out = []
    for item in raw:
        url = str(item or "").strip()
        if not url:
            continue
        if len(url) > 300 or not URL_RE.match(url) or ".." in url or contains_secret(url):
            raise DecisionError("bad_sources")
        out.append({"label": url.split("://", 1)[-1][:60], "url": url})
    return out


class DecisionStore:
    """Imported records (read from `source` on demand) plus the owner's overlay in one JSON file."""

    def __init__(self, path: Path, source: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.source = Path(source)
        self.clock = clock
        self._lock = threading.Lock()
        self._cache: tuple[float, list[dict[str, Any]]] | None = None

    # --- storage -------------------------------------------------------------------------------------------------
    def _imported(self) -> list[dict[str, Any]]:
        try:
            mtime = self.source.stat().st_mtime
            if not self._cache or self._cache[0] != mtime:
                self._cache = (mtime, parse_decisions(self.source.read_text(encoding="utf-8")))
            return [dict(r) for r in self._cache[1]]
        except OSError:
            return []

    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "created": {}, "edits": {}, "reviews": {}, "keys": {}}
        except (OSError, ValueError) as exc:
            raise DecisionError("store_unreadable", 503) from exc
        if not (isinstance(data, dict) and data.get("version") == 1
                and all(isinstance(data.get(k), dict) for k in ("created", "edits", "reviews", "keys"))):
            raise DecisionError("store_unreadable", 503)  # never silently replace a damaged store
        return data

    def _save(self, data: dict[str, Any]) -> None:
        name = ""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, prefix=".decision-memory-",
                                             suffix=".tmp", delete=False) as file:
                name = file.name
                json.dump(data, file, ensure_ascii=False, indent=1)
                file.flush()
                os.fsync(file.fileno())
            os.replace(name, self.path)
        except OSError as exc:
            raise DecisionError("store_write_failed", 503) from exc
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    def _now(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).date().isoformat()

    def _claim(self, data: dict, key: str, scope: dict) -> Any:
        """Return the stored result for a retried key, refuse a key reused for something else, else None."""
        key = str(key or "").strip()[:80]
        if not key:
            return None
        held = data["keys"].get(key)
        if held is None:
            return None
        if held.get("scope") != scope:
            raise DecisionError("idempotency_conflict", 409)
        return held.get("result")

    @staticmethod
    def _remember(data: dict, key: str, scope: dict, result: Any) -> None:
        key = str(key or "").strip()[:80]
        if key:
            data["keys"][key] = {"scope": scope, "result": result}
            for old in list(data["keys"])[: max(0, len(data["keys"]) - MAX_KEYS)]:
                del data["keys"][old]

    # --- reads ---------------------------------------------------------------------------------------------------
    def _merged(self, data: dict) -> list[dict[str, Any]]:
        today = self._today()
        records = self._imported() + [dict(r) for r in data["created"].values()]
        for rec in records:
            rec.update(data["edits"].get(rec["id"], {}))
            reviews = data["reviews"].get(rec["id"], [])
            rec["reviews"] = reviews
            if rec.get("review_at") and rec["review_at"] <= today:
                rec["follow_up"] = "due"
            elif rec.get("review_at"):
                rec["follow_up"] = "scheduled"
            elif reviews:
                rec["follow_up"] = "reviewed"
            else:
                rec["follow_up"] = "none"
        records.sort(key=lambda r: (r.get("date") or "", r.get("created_at") or ""), reverse=True)
        return records

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = self._merged(self._load())
        stats = {"total": len(records),
                 "imported": sum(r["origin"] == "decisions_md" for r in records),
                 "created": sum(r["origin"] == "owner" for r in records),
                 "missing_owner": sum(not r.get("owner") for r in records),
                 "missing_outcome": sum(not r.get("expected_outcome") for r in records),
                 "due": sum(r["follow_up"] == "due" for r in records),
                 "reviewed": sum(bool(r["reviews"]) for r in records),
                 "redacted": sum(bool(r.get("redacted")) for r in records)}
        return {"decisions": records, "stats": stats, "today": self._today(), "verdicts": list(VERDICTS),
                "issue": f"{REPO}/issues/{ISSUE}", "interview_script": INTERVIEW_SCRIPT,
                "source": {"file": "DECISIONS.md", "url": f"{REPO}/blob/main/DECISIONS.md"},
                "note": "Demo data is parsed from FactoryOS DECISIONS.md; responsible person, expected outcome and "
                        "follow-up are not recorded there and start empty. No AI or external call is made."}

    def _exists(self, data: dict, decision_id: str) -> bool:
        return decision_id in data["created"] or any(r["id"] == decision_id for r in self._imported())

    # --- writes --------------------------------------------------------------------------------------------------
    def create(self, body: dict, *, actor: str = "owner") -> dict[str, Any]:
        fields = {"decision": _text(body, "decision", required=True), "rationale": _text(body, "rationale", required=True),
                  "owner": _text(body, "owner"), "expected_outcome": _text(body, "expected_outcome"),
                  "review_at": _day(body, "review_at"), "date": _day(body, "date"), "sources": _sources(body)}
        scope = {"op": "create", "fp": hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()[:24]}
        with self._lock:
            data = self._load()
            held = self._claim(data, body.get("idempotency_key", ""), scope)
            if held is not None:
                return {"duplicate": True, "decision": data["created"].get(held) or {"id": held}}
            if len(data["created"]) >= MAX_CREATED:
                raise DecisionError("store_full", 409)
            now = self._now()
            rec = {"id": f"dmo-{uuid.uuid4().hex[:12]}", "origin": "owner", "title": "", "tasks": [], "redacted": False,
                   "created_at": now, "updated_at": now, "actor": str(actor)[:80], **fields}
            rec["date"] = rec["date"] or self._today()
            data["created"][rec["id"]] = rec
            self._remember(data, body.get("idempotency_key", ""), scope, rec["id"])
            self._save(data)
            return {"duplicate": False, "decision": rec}

    def update(self, decision_id: str, body: dict) -> dict[str, Any]:
        allowed = {"owner", "expected_outcome", "review_at"}
        if not body or set(body) - allowed:
            raise DecisionError("bad_fields")
        patch = {f: (_day(body, f) if f == "review_at" else _text(body, f)) for f in body}
        with self._lock:
            data = self._load()
            if not self._exists(data, decision_id):
                raise DecisionError("unknown_decision", 404)
            patch["updated_at"] = self._now()
            if decision_id in data["created"]:
                data["created"][decision_id].update(patch)
            else:
                data["edits"].setdefault(decision_id, {}).update(patch)
            self._save(data)
            return next(r for r in self._merged(data) if r["id"] == decision_id)

    def review(self, decision_id: str, body: dict, *, actor: str = "owner") -> dict[str, Any]:
        verdict = body.get("verdict")
        if verdict not in VERDICTS:
            raise DecisionError("bad_verdict")
        note = _text(body, "note")
        next_at = _day(body, "next_review_at")
        scope = {"op": "review", "id": decision_id,
                 "fp": hashlib.sha256(json.dumps([verdict, note, next_at]).encode()).hexdigest()[:24]}
        with self._lock:
            data = self._load()
            if not self._exists(data, decision_id):
                raise DecisionError("unknown_decision", 404)
            held = self._claim(data, body.get("idempotency_key", ""), scope)
            if held is not None:
                return {"duplicate": True, "review": held}
            reviews = data["reviews"].setdefault(decision_id, [])
            if len(reviews) >= MAX_REVIEWS:
                raise DecisionError("too_many_reviews", 409)
            item = {"id": uuid.uuid4().hex[:12], "at": self._now(), "verdict": verdict, "note": note,
                    "actor": str(actor)[:80]}
            reviews.append(item)
            target = data["created"][decision_id] if decision_id in data["created"] else data["edits"].setdefault(decision_id, {})
            target.update(review_at=next_at, updated_at=item["at"])  # a review closes the due date; next one optional
            self._remember(data, body.get("idempotency_key", ""), scope, item)
            self._save(data)
            return {"duplicate": False, "review": item}


def install_decision_memory_routes(app, store: DecisionStore, identity_fn: Callable) -> None:
    """Owner-only JSON API for the page. Viewers and members are refused even for reads."""

    def _deny(request: Request):
        ident = identity_fn(request) or {}
        if not ident:
            return JSONResponse({"detail": "login_required"}, status_code=401)
        if ident.get("role") != "owner":
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        return None

    def _actor(request: Request) -> str:
        return str((identity_fn(request) or {}).get("email") or "owner")

    async def _body(request: Request) -> dict:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise DecisionError("bad_body")
        if not isinstance(body, dict):
            raise DecisionError("bad_body")
        return body

    async def _run(request: Request, fn):
        denial = _deny(request)
        if denial is not None:
            return denial
        try:
            return await fn()
        except DecisionError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/decision-memory")
    async def decision_memory_snapshot(request: Request):
        async def go():
            return store.snapshot()
        return await _run(request, go)

    @app.post("/api/decision-memory/decisions")
    async def decision_memory_create(request: Request):
        async def go():
            return store.create(await _body(request), actor=_actor(request))
        return await _run(request, go)

    @app.post("/api/decision-memory/decisions/{decision_id}")
    async def decision_memory_update(decision_id: str, request: Request):
        async def go():
            return store.update(decision_id, await _body(request))
        return await _run(request, go)

    @app.post("/api/decision-memory/decisions/{decision_id}/reviews")
    async def decision_memory_review(decision_id: str, request: Request):
        async def go():
            return store.review(decision_id, await _body(request), actor=_actor(request))
        return await _run(request, go)


# --- MVP Factory registry link (the "decision-memory" pilot seeded in mvp_factory.py) -------------------------------
AGENT = "claude-session-decision-memory"
PILOT_PR = 384  # T-614 PR; the spec_draft -> spec_review step cites it
INTAKE_VERSION = "v1"


def _registry_steps() -> list[tuple[str, list[str], str]]:
    issue = f"{REPO}/issues/{ISSUE}"
    pr = [f"{REPO}/pull/{PILOT_PR}"] if PILOT_PR else []
    steps = [("idea", [issue], "Issue #187 holds the scope: decision, rationale, owner, sources, expected outcome, follow-up."),
             ("researching", [issue, PAGE], "T-614 spec: owner-only web MVP over a real DECISIONS.md dataset; see DECISIONS.md.")]
    if pr:
        steps.append(("spec_draft", pr + [PAGE], f"Spec and clickable preview are in PR #{PILOT_PR}, awaiting owner review."))
    return steps


def sync_mvp_registry_once(registry, marker_path: Path) -> list[str]:
    """Link the existing #187 pilot to its preview and move it through the agent-allowed stages (research, spec) with
    evidence. Never creates a second project, never moves past spec_review (build/preview/verdict stay with the owner),
    never moves a project the owner has already moved elsewhere. Returns the events recorded."""
    marker = Path(marker_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    done: list[str] = []
    with marker.with_name(marker.name + ".lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            stamp = f"{INTAKE_VERSION}:{PILOT_PR}"
            if marker.exists() and marker.read_text(encoding="utf-8").strip() == stamp:
                return done
            project = next((p for p in registry.snapshot()["projects"] if p.get("issue") == ISSUE), None)
            if project is None:
                return done  # the owner removed the pilot; do not recreate it
            pid = project["id"]
            if not project.get("prototype"):
                registry.set_prototype(pid, PAGE, actor_role="agent", actor=AGENT)
                done.append("prototype")
            for from_stage, evidence, note in _registry_steps():
                current = next(p for p in registry.snapshot()["projects"] if p["id"] == pid)
                if current["stage"] != from_stage or current.get("blocked"):
                    continue
                registry.record(pid, "advance", actor_role="agent", actor=AGENT, evidence=evidence, note=note,
                                idempotency_key=f"t614-{INTAKE_VERSION}-{from_stage}")
                done.append(from_stage)
            marker.write_text(stamp + "\n", encoding="utf-8")
            return done
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
