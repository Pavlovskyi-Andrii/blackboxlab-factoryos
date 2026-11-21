"""T-630 Product Evolution for the existing MVP Factory (#270, epic #186): consented feedback → themes → V2 proposal →
owner approval → Builder hand-off through the existing Relay → shipped → V2 → retest by the original participants.

This is not a second registry: a project must already exist in `mvp_factory.MvpRegistry`, and this module never changes
its stage (agents may not move a pilot past the allowed stages, and validated/rejected stay the owner's call).

Rules
- Feedback is stored only with explicit consent (`consent` literally true) and a consent reference (where and how it was
  given). The participant label is never stored: only a per-project hash, so the same person counts once. Free text is
  capped, with e-mail addresses and phone-like numbers redacted (same rule as the MyBrief pilot).
- Synthetic records are allowed only as clearly marked demo data: `synthetic: true` everywhere, never counted in the real
  cohort, never mixed into a real proposal. The real view shows the 10 → 100 cohort targets against real counts only.
- "Substantive" feedback has a job-to-be-done and what helped or failed; stars alone are not substantive.
- Themes are synthesised deterministically from tags: support, contrary evidence, unique participants and a confidence
  that stays `insufficient` below three people. A majority is a signal, not an automatic change.
- A proposal must cite feedback ids and carry an acceptance test. Only the owner approves or declines it. Approval is not
  a build: the owner or a member hands it off, which creates exactly one Relay ticket (existing `RelayStore.create`,
  idempotent by source key). Nothing here claims, runs or merges anything.
- A hand-off reads VERIFIED only when the Relay ticket is done with a run_id and the app's evidence check accepted it;
  otherwise it shows the ticket's real state (queued / claimed / running / needs_owner / blocked / unknown).
- "Shipped" needs a merged-PR / commit link; releasing V2 is owner-only and needs a shipped proposal.
- Every write is idempotent by `idempotency_key` (same operation → same result; key reused for another operation → 409).
- T-633: the funnel steps activated / used / returned are counted from consented in-product usage events only (one
  record of three dates per participant and version, keyed by a hash of a random code the participant's browser holds);
  they cannot be typed in by hand. The participant can export or delete the record with that code.
- No provider call, no outreach, no publishing, no spending.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_factory import EVIDENCE_RE, ID_RE, REPO

SCHEMA = "mvp-evolution/1"
COHORT_TARGETS = (10, 100)  # first cohort: 10 unique substantive feedback records; next: 100 invited/opted-in users
FUNNEL = ("invited", "activated", "used", "returned", "abandoned")
USAGE_STEPS = ("activated", "used", "returned")  # T-633: counted from consented events, never entered by hand
USAGE_SOURCE = "consented in-product events"
USAGE_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
MAX_USAGE = 5000  # participants per version
SOURCES = ("interview", "survey", "in_product", "mybrief_import", "synthetic")
TRI = ("yes", "no", "unknown")
SOLVED = ("yes", "partly", "no", "unknown")
PROPOSAL_STATES = ("proposed", "approved", "handed_off", "shipped", "declined")
VERSION_RE = re.compile(r"^v\d{1,3}$")
THEME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")  # an ISO date is not a phone number
SHIP_RE = re.compile(r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/(pull|commit)/[A-Za-z0-9]+$")
TEXT_MAX = 600
SUBSTANTIVE_MIN = 40
MAX_FEEDBACK = 3000
MAX_PROPOSALS = 300
MAX_KEYS = 4000
LANES = ("claude", "chatgpt", "gemini", "unassigned")


class EvolutionError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def clean_text(value: Any, limit: int = TEXT_MAX) -> str:
    text = re.sub(r"[\u0000-\u0008\u000b-\u001f<>]", "", str(value or "")).strip()
    text = PHONE_RE.sub(lambda m: m.group(0) if DATE_RE.fullmatch(m.group(0)) else "[phone]", EMAIL_RE.sub("[email]", text))
    return text[:limit]


def _choice(value: Any, allowed: tuple, default: str = "unknown") -> str:
    value = str(value if value is not None else default).strip().lower()
    if value not in allowed:
        raise EvolutionError("bad_choice")
    return value


def _themes(value: Any) -> list[str]:
    items = value if isinstance(value, list) else []
    out = []
    for t in items[:5]:
        t = str(t or "").strip().lower()
        if not THEME_RE.match(t):
            raise EvolutionError("bad_theme")
        if t not in out:
            out.append(t)
    return out


def is_substantive(rec: dict[str, Any]) -> bool:
    a = rec.get("answers") or {}
    detail = (a.get("helped") or "") + (a.get("failed") or "")
    return bool(a.get("job")) and bool(detail) and len((a.get("job") or "") + detail) >= SUBSTANTIVE_MIN


def confidence(unique_support: int, unique_contra: int) -> str:
    if unique_support < 3:
        return "insufficient"
    if unique_support < 5 or unique_contra * 2 >= unique_support:
        return "low"
    if unique_support < 10 or unique_contra * 3 >= unique_support:
        return "medium"
    return "high"


def synthesize(feedback: list[dict[str, Any]], version: str) -> list[dict[str, Any]]:
    """Themes for one version. Deterministic; never decides anything."""
    rows = [r for r in feedback if r.get("version") == version and not r.get("retest_of")]
    themes: dict[str, dict[str, Any]] = {}
    for r in rows:
        for kind in ("themes", "contra"):
            for t in r.get(kind) or []:
                th = themes.setdefault(t, {"theme": t, "support": [], "contra": [], "p_support": set(), "p_contra": set(),
                                           "importance": []})
                if kind == "themes":
                    th["support"].append(r["id"])
                    th["p_support"].add(r["participant"])
                    if isinstance((r.get("answers") or {}).get("importance"), int):
                        th["importance"].append(r["answers"]["importance"])
                else:
                    th["contra"].append(r["id"])
                    th["p_contra"].add(r["participant"])
    sample = len({r["participant"] for r in rows})
    out = []
    for th in themes.values():
        ns, nc = len(th["p_support"]), len(th["p_contra"])
        imp = th["importance"]
        out.append({"theme": th["theme"], "support_ids": th["support"], "contra_ids": th["contra"],
                    "unique_support": ns, "unique_contra": nc, "sample_size": sample,
                    "share": round(ns / sample, 2) if sample else 0.0,
                    "avg_importance": round(sum(imp) / len(imp), 2) if imp else None,
                    "confidence": confidence(ns, nc)})
    out.sort(key=lambda t: (-t["unique_support"], t["unique_contra"], t["theme"]))
    return out


def _ticket_id(ticket: Any) -> str:
    """A hand-off is recorded only with a real Relay id; otherwise nothing is saved and the call can be retried."""
    tid = str((ticket or {}).get("id") or "") if isinstance(ticket, dict) else ""
    if not re.fullmatch(r"R-\d{1,8}", tid):
        raise EvolutionError("relay_failed", 502)
    return tid


def handoff_status(proposal: dict[str, Any], ticket: Optional[dict[str, Any]], verified: bool) -> dict[str, Any]:
    """The #270 task envelope for a handed-off proposal, from Relay facts only."""
    ex = (ticket or {}).get("execution") or {}
    run_id = str(ex.get("run_id") or "")
    if ticket is None:
        state, label = "unknown", "UNKNOWN"
    elif ticket.get("status") == "done":
        ok = verified and bool(run_id)
        state, label = ("validated", "VERIFIED") if ok else ("produced", "UNVERIFIED")
    elif ticket.get("status") == "need_you":
        state, label = "needs_owner", "BLOCKED"
    elif ticket.get("status") == "archived" or ex.get("state") in ("stale", "failed", "blocked"):
        state, label = "blocked", "BLOCKED"
    elif ex.get("state") in ("claimed", "running"):
        state, label = ex["state"], "UNKNOWN"
    else:
        state, label = "queued", "UNKNOWN"
    return {"schema": SCHEMA, "project_id": proposal["project"], "version": proposal["target_version"],
            "task_id": proposal["id"], "ticket_id": proposal.get("ticket_id") or "", "run_id": run_id,
            "producer_role": "Product Manager", "consumer_role": "UI/Builder Worker",
            "input_artifact_refs": [f"feedback:{f}" for f in proposal["feedback_ids"]],
            "acceptance_criteria": [proposal["acceptance_test"]], "lane": ex.get("owner") or "",
            "state": state, "verification": label, "attempts": int(ex.get("attempts") or 0),
            "note": "Read from the Relay ticket; VERIFIED needs done + run_id + accepted evidence."}


class EvolutionStore:
    """One JSON file (or memory, for the synthetic demo). One web process writes it; the lock covers its threads."""

    def __init__(self, path: Optional[Path], *, clock: Callable[[], float] = time.time,
                 project_exists: Callable[[str], bool] = lambda pid: True, salt: str = ""):
        self.path = Path(path) if path else None
        self.clock, self.project_exists = clock, project_exists
        self._lock = threading.Lock()
        self._mem: Optional[dict[str, Any]] = None
        self._salt = salt

    # --- storage ------------------------------------------------------------------------------------------------
    def _empty(self) -> dict[str, Any]:
        return {"schema": SCHEMA, "salt": self._salt or os.urandom(16).hex(), "projects": {}, "keys": {}}

    def _load(self) -> dict[str, Any]:
        if self.path is None:
            if self._mem is None:
                self._mem = self._empty()
            return self._mem
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("projects"), dict) and data.get("salt"):
                data.setdefault("keys", {})
                return data
        except FileNotFoundError:
            return self._empty()
        except (OSError, ValueError):
            pass
        raise EvolutionError("store_unreadable", 503)  # never silently replace a damaged ledger

    def _save(self, data: dict[str, Any]) -> None:
        if len(data["keys"]) > MAX_KEYS:
            for old in list(data["keys"])[: len(data["keys"]) - MAX_KEYS]:
                del data["keys"][old]
        if self.path is None:
            self._mem = data
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    def _project(self, data: dict[str, Any], pid: str) -> dict[str, Any]:
        if not ID_RE.match(pid or ""):
            raise EvolutionError("bad_project")
        if pid not in data["projects"]:
            if not self.project_exists(pid):
                raise EvolutionError("unknown_project", 404)
            data["projects"][pid] = {"current_version": "v1", "versions": [{"version": "v1", "at": None, "evidence": []}],
                                     "feedback": [], "proposals": [], "funnel": {}, "log": []}
        return data["projects"][pid]

    def _now(self) -> str:
        return _iso(self.clock())

    def _idem(self, data: dict, key: str, scope: dict, fn: Callable[[], Any]) -> Any:
        key = clean_text(key, 80)
        fp = hashlib.sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()[:24]
        if key and key in data["keys"]:
            held = data["keys"][key]
            if held.get("fp") != fp:
                raise EvolutionError("idempotency_conflict", 409)
            return dict(held["result"], duplicate=True)
        result = fn()
        if key:
            data["keys"][key] = {"fp": fp, "result": result}
        self._save(data)
        return dict(result, duplicate=False)

    def _log(self, proj: dict, actor: str, action: str, ref: str, note: str = "") -> None:
        proj["log"].append({"at": self._now(), "actor": actor[:80], "action": action, "ref": ref, "note": note[:200]})
        del proj["log"][:-300]

    @staticmethod
    def _next_id(proj: dict) -> str:
        proj["seq"] = int(proj.get("seq") or 0) + 1  # never reused, even after a privacy delete
        return f"fb-{proj['seq']:04d}"

    def _participant(self, data: dict, pid: str, label: str) -> str:
        return hashlib.sha256(f"{data['salt']}|{pid}|{label.strip().lower()}".encode()).hexdigest()[:16]

    # --- feedback -----------------------------------------------------------------------------------------------
    def add_feedback(self, pid: str, body: dict[str, Any], *, actor_role: str, actor: str = "") -> dict[str, Any]:
        if actor_role not in ("owner", "member", "agent"):
            raise EvolutionError("forbidden", 403)
        if body.get("consent") is not True:
            raise EvolutionError("consent_required")
        consent_ref = clean_text(body.get("consent_ref"), 160)
        if not consent_ref:
            raise EvolutionError("consent_ref_required")
        label = str(body.get("participant") or "").strip()[:120]
        if not label:
            raise EvolutionError("participant_required")
        source = _choice(body.get("source") or "interview", SOURCES)
        synthetic = body.get("synthetic") is True
        if (source == "synthetic") != synthetic:
            raise EvolutionError("synthetic_must_be_marked")
        imp = body.get("importance")
        if imp is not None and (not isinstance(imp, int) or isinstance(imp, bool) or not 1 <= imp <= 5):
            raise EvolutionError("bad_importance")
        answers = {"tried": _choice(body.get("tried"), TRI), "job": clean_text(body.get("job")),
                   "helped": clean_text(body.get("helped")), "failed": clean_text(body.get("failed")),
                   "change": clean_text(body.get("change")), "importance": imp,
                   "would_pay": _choice(body.get("would_pay"), TRI), "pay_period": clean_text(body.get("pay_period"), 40),
                   "paid_pilot": _choice(body.get("paid_pilot"), TRI)}
        themes, contra = _themes(body.get("themes")), _themes(body.get("contra"))
        if set(themes) & set(contra):
            raise EvolutionError("theme_and_contra")
        retest_of = str(body.get("retest_of") or "").strip()
        solved = _choice(body.get("solved"), SOLVED) if retest_of else None
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            version = str(body.get("version") or proj["current_version"])
            if version not in [v["version"] for v in proj["versions"]]:
                raise EvolutionError("unknown_version")
            if retest_of:
                prop = next((p for p in proj["proposals"] if p["id"] == retest_of), None)
                if not prop or prop["state"] != "shipped" or version != prop["target_version"]:
                    raise EvolutionError("retest_needs_shipped_version", 409)
                if bool(prop.get("synthetic")) != synthetic:
                    raise EvolutionError("synthetic_mix", 409)
            participant = self._participant(data, pid, label)
            scope = {"op": "feedback", "pid": pid, "participant": participant, "answers": answers, "themes": themes,
                     "contra": contra, "version": version, "retest_of": retest_of, "source": source}

            def go():
                if len(proj["feedback"]) >= MAX_FEEDBACK:
                    raise EvolutionError("feedback_full", 409)
                rec = {"id": self._next_id(proj),
                       "project": pid, "version": version, "at": self._now(), "source": source, "synthetic": synthetic,
                       "consent": {"given": True, "ref": consent_ref}, "participant": participant, "answers": answers,
                       "themes": themes, "contra": contra, "retest_of": retest_of or None, "solved": solved,
                       "recorded_by": actor_role}
                rec["substantive"] = is_substantive(rec)
                proj["feedback"].append(rec)
                self._log(proj, actor or actor_role, "feedback", rec["id"], "synthetic" if synthetic else source)
                return {"feedback": rec}
            return self._idem(data, str(body.get("idempotency_key") or ""), scope, go)

    def delete_feedback(self, pid: str, fid: str, *, actor_role: str, actor: str = "") -> dict[str, Any]:
        """Privacy delete (a participant withdraws consent). Owner only. Proposals keep the id with a 'deleted' mark."""
        if actor_role != "owner":
            raise EvolutionError("owner_only", 403)
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            keep = [r for r in proj["feedback"] if r["id"] != fid]
            if len(keep) == len(proj["feedback"]):
                raise EvolutionError("not_found", 404)
            proj["feedback"] = keep
            for key in [k for k, v in data["keys"].items() if (v.get("result") or {}).get("feedback", {}).get("id") == fid]:
                del data["keys"][key]
            self._log(proj, actor or actor_role, "feedback_deleted", fid)
            self._save(data)
            return {"deleted": fid}

    def import_mybrief(self, pid: str, entries: list[dict[str, Any]], *, actor_role: str, actor: str = "") -> dict[str, Any]:
        """Bring consented MyBrief feedback in as records (pilot mybrief-pro only). Idempotent by the MyBrief id."""
        if actor_role not in ("owner", "member"):
            raise EvolutionError("forbidden", 403)
        if pid != "mybrief-pro":
            raise EvolutionError("import_not_for_project")
        added = 0
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            seen = {r["consent"]["ref"] for r in proj["feedback"]}
            for e in entries:
                if e.get("consent") is not True or not e.get("id"):
                    continue
                ref = f"mybrief:{e['id']}"
                if ref in seen or len(proj["feedback"]) >= MAX_FEEDBACK:
                    continue
                rating = e.get("rating") if isinstance(e.get("rating"), int) else None
                weekly = e.get("would_read_weekly")
                rec = {"id": self._next_id(proj), "project": pid, "version": proj["current_version"],
                       "at": str(e.get("at") or self._now()), "source": "mybrief_import", "synthetic": False,
                       "consent": {"given": True, "ref": ref}, "participant": self._participant(data, pid, ref),
                       "answers": {"tried": "yes", "job": "", "helped": "", "failed": "",
                                   "change": clean_text(e.get("comment")), "importance": rating,
                                   "would_pay": "unknown", "pay_period": "", "paid_pilot": "unknown",
                                   "would_read_weekly": weekly if isinstance(weekly, bool) else None},
                       "themes": [], "contra": [], "retest_of": None, "solved": None, "recorded_by": actor_role}
                rec["substantive"] = False  # a rating and a comment are a signal, not a discovery interview
                proj["feedback"].append(rec)
                seen.add(ref)
                added += 1
            if added:
                self._log(proj, actor or actor_role, "import_mybrief", str(added))
            self._save(data)
        return {"imported": added}

    def set_funnel(self, pid: str, body: dict[str, Any], *, actor_role: str, actor: str = "") -> dict[str, Any]:
        """Usage counts for the current version, each with its source. A step nobody recorded stays unknown (null)."""
        if actor_role not in ("owner", "member"):
            raise EvolutionError("forbidden", 403)
        step = str(body.get("step") or "")
        count = body.get("count")
        source = clean_text(body.get("source"), 200)
        if step not in FUNNEL:
            raise EvolutionError("bad_step")
        if step in USAGE_STEPS:
            raise EvolutionError("step_from_events", 409)  # T-633: these counts come from consented events only
        if count is not None and (not isinstance(count, int) or isinstance(count, bool) or count < 0):
            raise EvolutionError("bad_count")
        if count is not None and not source:
            raise EvolutionError("source_required")
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            fn = proj["funnel"].setdefault(proj["current_version"], {})
            fn[step] = None if count is None else {"count": count, "source": source, "at": self._now(), "by": actor_role}
            self._log(proj, actor or actor_role, "funnel", step, str(count))
            self._save(data)
            return {"funnel": fn}

    # --- usage events (T-633) -----------------------------------------------------------------------------------
    def _usage_key(self, data: dict, pid: str, token: Any) -> str:
        token = str(token or "")
        if not USAGE_TOKEN_RE.match(token):
            raise EvolutionError("bad_participant")
        return self._participant(data, pid, "usage:" + token)

    def record_usage(self, pid: str, body: dict[str, Any], *, allow_new: bool = True) -> dict[str, Any]:
        """One consented in-product event for the current version. Stored per participant: the consent reference and
        three dates (first open, first use, first return on a later day) - no timestamps, addresses or content.
        `returned` is derived here from the dates, so a page cannot claim a return on the day of the first visit."""
        if body.get("consent") is not True:
            raise EvolutionError("consent_required")
        consent_ref = clean_text(body.get("consent_ref"), 160)
        if not consent_ref:
            raise EvolutionError("consent_ref_required")
        kind = str(body.get("event") or "")
        if kind not in USAGE_STEPS:
            raise EvolutionError("bad_event")
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            who = self._usage_key(data, pid, body.get("participant"))
            version, day = proj["current_version"], self._now()[:10]
            bucket = proj.setdefault("usage", {}).setdefault(version, {})
            rec, new = bucket.get(who), []
            if rec is None:
                if not allow_new:
                    raise EvolutionError("daily_limit", 429)
                if len(bucket) >= MAX_USAGE:
                    raise EvolutionError("usage_full", 409)
                rec = bucket[who] = {"consent_ref": consent_ref, "activated": day, "used": None, "returned": None}
                new.append("activated")
            if kind == "used" and not rec["used"]:
                rec["used"] = day
                new.append("used")
            if not rec["returned"] and day > rec["activated"]:
                rec["returned"] = day
                new.append("returned")
            if new:
                self._save(data)
            return {"project": pid, "version": version, "recorded": new, "events": {s: rec[s] for s in USAGE_STEPS}}

    def export_usage(self, pid: str, token: Any) -> dict[str, Any]:
        """Everything stored about one participant's usage, for the holder of the code."""
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            who = self._usage_key(data, pid, token)
            records = [dict(bucket[who], version=v) for v, bucket in (proj.get("usage") or {}).items() if who in bucket]
        return {"project": pid, "records": records, "fields": ["version", "consent_ref", *USAGE_STEPS],
                "note": "Dates only (UTC days). No name, e-mail, address or page content is stored with usage events."}

    def delete_usage(self, pid: str, token: Any) -> dict[str, Any]:
        """Privacy delete by the holder of the code: the records leave every version and the funnel counts drop."""
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            who = self._usage_key(data, pid, token)
            removed = sum(1 for bucket in (proj.get("usage") or {}).values() if bucket.pop(who, None) is not None)
            if removed:
                self._log(proj, "participant", "usage_deleted", str(removed))
                self._save(data)
            return {"deleted": removed}

    # --- proposals ----------------------------------------------------------------------------------------------
    def propose(self, pid: str, body: dict[str, Any], *, actor_role: str, actor: str = "") -> dict[str, Any]:
        if actor_role not in ("owner", "member", "agent"):
            raise EvolutionError("forbidden", 403)
        title, problem = clean_text(body.get("title"), 140), clean_text(body.get("problem"))
        change, test = clean_text(body.get("change")), clean_text(body.get("acceptance_test"))
        if not (title and problem and change and test):
            raise EvolutionError("proposal_incomplete")
        theme = str(body.get("theme") or "").strip().lower()
        if theme and not THEME_RE.match(theme):
            raise EvolutionError("bad_theme")
        fids = [str(f) for f in (body.get("feedback_ids") if isinstance(body.get("feedback_ids"), list) else [])][:50]
        if not fids:
            raise EvolutionError("feedback_required")
        issue = body.get("issue")
        if issue is not None and (not isinstance(issue, int) or isinstance(issue, bool) or issue <= 0):
            raise EvolutionError("bad_issue")
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            by_id = {r["id"]: r for r in proj["feedback"]}
            if any(f not in by_id for f in fids):
                raise EvolutionError("unknown_feedback")
            kinds = {bool(by_id[f]["synthetic"]) for f in fids}
            if len(kinds) > 1:
                raise EvolutionError("synthetic_mix", 409)
            synthetic = kinds.pop()
            cur = proj["current_version"]
            target = f"v{int(cur[1:]) + 1}"
            scope = {"op": "propose", "pid": pid, "title": title, "problem": problem, "change": change, "test": test,
                     "fids": sorted(fids), "theme": theme, "issue": issue}

            def go():
                if len(proj["proposals"]) >= MAX_PROPOSALS:
                    raise EvolutionError("proposals_full", 409)
                prop = {"id": f"pr-{len(proj['proposals']) + 1:03d}", "project": pid, "from_version": cur,
                        "target_version": target, "title": title, "problem": problem, "change": change,
                        "acceptance_test": test, "theme": theme, "feedback_ids": sorted(fids), "issue": issue,
                        "synthetic": synthetic, "state": "proposed", "proposed_by": actor_role, "created_at": self._now(),
                        "decided_by": None, "ticket_id": None, "lane": None, "shipped_evidence": [], "history": []}
                prop["history"].append({"at": self._now(), "state": "proposed", "by": actor_role})
                proj["proposals"].append(prop)
                self._log(proj, actor or actor_role, "propose", prop["id"])
                return {"proposal": copy.deepcopy(prop)}
            return self._idem(data, str(body.get("idempotency_key") or ""), scope, go)

    def decide(self, pid: str, prop_id: str, body: dict[str, Any], *, actor_role: str, actor: str = "",
               create_ticket: Optional[Callable[..., dict]] = None) -> dict[str, Any]:
        action = str(body.get("action") or "")
        if action in ("approve", "decline") and actor_role != "owner":
            raise EvolutionError("owner_only", 403)
        if action in ("handoff", "ship") and actor_role not in ("owner", "member"):
            raise EvolutionError("forbidden", 403)
        if action not in ("approve", "decline", "handoff", "ship"):
            raise EvolutionError("bad_action")
        note = clean_text(body.get("note"), 300)
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            prop = next((p for p in proj["proposals"] if p["id"] == prop_id), None)
            if not prop:
                raise EvolutionError("unknown_proposal", 404)
            evidence = [str(e).strip() for e in (body.get("evidence") if isinstance(body.get("evidence"), list) else [])][:5]
            lane = str(body.get("lane") or "claude")
            scope = {"op": "decide", "pid": pid, "prop": prop_id, "action": action, "evidence": evidence, "lane": lane}

            def go():
                state = prop["state"]
                need = {"approve": "proposed", "decline": None, "handoff": "approved", "ship": "handed_off"}[action]
                if action == "decline":
                    if state not in ("proposed", "approved"):
                        raise EvolutionError("bad_transition", 409)
                    prop["state"] = "declined"
                elif state != need:
                    raise EvolutionError("bad_transition", 409)
                elif action == "approve":
                    prop["state"], prop["decided_by"] = "approved", actor or actor_role
                elif action == "handoff":
                    if prop.get("synthetic"):
                        raise EvolutionError("synthetic_not_handed_off", 409)  # demo data never reaches a real worker
                    if lane not in LANES:
                        raise EvolutionError("bad_lane")
                    if create_ticket is None:
                        raise EvolutionError("relay_unavailable", 503)
                    ticket = create_ticket(title=f"MVP {pid} {prop['target_version']}: {prop['title']}"[:180],
                                           body=ticket_body(prop), key=f"mvp-evolution:{pid}:{prop['id']}", lane=lane)
                    prop["state"], prop["ticket_id"], prop["lane"] = "handed_off", _ticket_id(ticket), lane
                elif action == "ship":
                    if not evidence or any(not SHIP_RE.match(e) for e in evidence):
                        raise EvolutionError("ship_evidence_required")
                    prop["state"], prop["shipped_evidence"] = "shipped", evidence
                prop["history"].append({"at": self._now(), "state": prop["state"], "by": actor_role, "note": note})
                self._log(proj, actor or actor_role, action, prop_id, note)
                return {"proposal": copy.deepcopy(prop)}
            return self._idem(data, str(body.get("idempotency_key") or ""), scope, go)

    def policy_handoff(self, pid: str, prop_id: str, *, policy: str, evidence: dict[str, Any],
                       create_ticket: Callable[..., dict], lane: str = "claude") -> dict[str, Any]:
        """T-634: the owner's standing rule ("hand a theme to Builder once enough people ask for it") approves and hands
        off one proposal. Only an agent-made proposal on real data, still `proposed`, qualifies; the threshold numbers
        are kept in the proposal history. Owners and members keep the manual path; nothing here merges or releases."""
        if lane not in LANES:
            raise EvolutionError("bad_lane")
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            prop = next((p for p in proj["proposals"] if p["id"] == prop_id), None)
            if not prop:
                raise EvolutionError("unknown_proposal", 404)
            if prop.get("synthetic"):
                raise EvolutionError("synthetic_not_handed_off", 409)
            if prop["state"] != "proposed" or prop.get("proposed_by") != "agent":
                raise EvolutionError("bad_transition", 409)
            ticket = create_ticket(title=f"MVP {pid} {prop['target_version']}: {prop['title']}"[:180],
                                   body=ticket_body(prop) + f"\nApproved by the owner's standing rule `{policy}`: "
                                   + json.dumps(evidence, sort_keys=True), key=f"mvp-evolution:{pid}:{prop['id']}", lane=lane)
            now = self._now()
            prop["decided_by"] = f"policy:{policy}"
            prop["history"].append({"at": now, "state": "approved", "by": f"policy:{policy}", "note": json.dumps(evidence, sort_keys=True)[:300]})
            prop["state"], prop["ticket_id"], prop["lane"] = "handed_off", _ticket_id(ticket), lane
            prop["history"].append({"at": now, "state": "handed_off", "by": f"policy:{policy}", "note": ""})
            self._log(proj, f"policy:{policy}", "policy_handoff", prop_id)
            self._save(data)
            return {"proposal": copy.deepcopy(prop)}

    def release(self, pid: str, body: dict[str, Any], *, actor_role: str, actor: str = "") -> dict[str, Any]:
        """Owner only: the next version exists once at least one proposal for it shipped. Not a public release."""
        if actor_role != "owner":
            raise EvolutionError("owner_only", 403)
        evidence = [str(e).strip() for e in (body.get("evidence") if isinstance(body.get("evidence"), list) else [])][:5]
        if not evidence or any(not EVIDENCE_RE.match(e) for e in evidence):
            raise EvolutionError("evidence_required")
        with self._lock:
            data = self._load()
            proj = self._project(data, pid)
            cur = proj["current_version"]
            target = f"v{int(cur[1:]) + 1}"
            scope = {"op": "release", "pid": pid, "evidence": evidence}

            def go():
                if not any(p["state"] == "shipped" and p["target_version"] == target for p in proj["proposals"]):
                    raise EvolutionError("nothing_shipped", 409)
                proj["versions"].append({"version": target, "at": self._now(), "evidence": evidence})
                proj["current_version"] = target
                self._log(proj, actor or actor_role, "release", target)
                return {"version": target}
            # a retry with the same key replays the first result instead of bumping the version twice
            return self._idem(data, str(body.get("idempotency_key") or ""), scope, go)

    # --- read ---------------------------------------------------------------------------------------------------
    def view(self, pid: str, *, ticket_lookup: Callable[[str], Optional[dict]] = lambda tid: None,
             ticket_verified: Callable[[dict], bool] = lambda t: False) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            proj = copy.deepcopy(self._project(data, pid)) if (pid in data["projects"] or self.project_exists(pid)) else None
        if proj is None:
            raise EvolutionError("unknown_project", 404)
        return build_view(pid, proj, ticket_lookup, ticket_verified)


def ticket_body(prop: dict[str, Any]) -> str:
    return "\n".join([
        f"Product Evolution hand-off ({SCHEMA}) — project `{prop['project']}` {prop['from_version']} → {prop['target_version']}.",
        f"Proposal {prop['id']}: {prop['title']}", "", f"Problem (from feedback): {prop['problem']}",
        f"Change: {prop['change']}", f"Acceptance test: {prop['acceptance_test']}",
        f"Feedback evidence (anonymised ids, FactoryOS /api/mvp-evolution/{prop['project']}): {', '.join(prop['feedback_ids'])}",
        f"Issue: {REPO}/issues/{prop['issue']}" if prop.get("issue") else "Issue: none yet",
        "", "Rules: isolated branch → PR → CI; no publishing, outreach, paid calls or merge without the owner.",
        "Do not move the MVP registry stage; the owner records the release and the verdict.",
    ])


def usage_funnel(proj: dict[str, Any], version: str) -> dict[str, Any]:
    """T-633: activated / used / returned for one version, counted from its usage records. Unknown (null) until the
    version has at least one consented participant; a manual number is never used for these steps."""
    bucket = (proj.get("usage") or {}).get(version) or {}
    out: dict[str, Any] = {}
    for step in USAGE_STEPS:
        days = [r[step] for r in bucket.values() if r.get(step)]
        out[step] = {"count": len(days), "source": USAGE_SOURCE, "at": max(days) if days else None, "by": "events"} if bucket else None
    return out


def build_view(pid: str, proj: dict[str, Any], ticket_lookup: Callable, ticket_verified: Callable) -> dict[str, Any]:
    feedback = proj["feedback"]
    real = [r for r in feedback if not r["synthetic"]]
    cur = proj["current_version"]
    unique_sub = len({r["participant"] for r in real if r["substantive"] and not r.get("retest_of")})
    proposals = []
    for p in proj["proposals"]:
        p = dict(p)
        if p["state"] in ("handed_off", "shipped") and p.get("ticket_id"):
            t = ticket_lookup(p["ticket_id"])
            p["handoff"] = handoff_status(p, t, bool(t) and ticket_verified(t))
        retests = [r for r in feedback if r.get("retest_of") == p["id"]]
        p["retest"] = {"responses": len(retests), "original_participants": len(
            {r["participant"] for r in retests} & {r["participant"] for r in feedback if r["id"] in p["feedback_ids"]}),
            "solved": {k: sum(1 for r in retests if r.get("solved") == k) for k in SOLVED}}
        p["missing_feedback"] = [f for f in p["feedback_ids"] if f not in {r["id"] for r in feedback}]
        proposals.append(p)
    versions = [v["version"] for v in proj["versions"]]
    synthetic_any = any(r["synthetic"] for r in feedback)
    return {
        "schema": SCHEMA, "project": pid, "current_version": cur, "versions": proj["versions"],
        "cohort": {"targets": list(COHORT_TARGETS), "unique_substantive_real": unique_sub,
                   "first_target_met": unique_sub >= COHORT_TARGETS[0],
                   "feedback_real": len(real), "feedback_synthetic": len(feedback) - len(real)},
        "funnel": {v: {s: (proj["funnel"].get(v) or {}).get(s) for s in FUNNEL} | usage_funnel(proj, v) | {
            "feedback_received": sum(1 for r in real if r["version"] == v)} for v in versions},
        "themes": {v: synthesize(real, v) for v in versions},
        "synthetic_themes": {v: synthesize([r for r in feedback if r["synthetic"]], v) for v in versions} if synthetic_any else {},
        "feedback": list(reversed(feedback[-200:])), "proposals": proposals, "log": proj["log"][-40:],
        "note": "Real counts only; synthetic records are labelled and excluded. Themes are signals, not decisions. "
                "Hand-offs are VERIFIED only from Relay facts. Nothing here changes the MVP registry stage.",
    }


# --- deterministic synthetic V1 → V2 loop (clearly marked demo) -------------------------------------------------------
DEMO_PROJECT = "demo-evolution"


def synthetic_demo() -> dict[str, Any]:
    """The whole loop on an in-memory store with a fixed clock. Every record is synthetic; no ticket is created —
    the hand-off step is shown as what a real one would carry, marked SIMULATED."""
    t = [1_800_000_000.0]

    def clock():
        t[0] += 60
        return t[0]
    store = EvolutionStore(None, clock=clock, project_exists=lambda pid: pid == DEMO_PROJECT, salt="demo")
    jobs = [("prepare a weekly client report", "the summary saved time", "", ["faster-summary"], []),
            ("brief the team on Monday", "", "export to PDF was missing", ["pdf-export"], []),
            ("send a digest to my manager", "", "no PDF export, had to copy by hand", ["pdf-export"], []),
            ("archive decisions for audits", "", "cannot export to PDF for the auditor", ["pdf-export"], []),
            ("share with a client offline", "", "needs a PDF I can attach", ["pdf-export"], []),
            ("read on the train", "mobile view works well", "", ["mobile"], ["pdf-export"]),
            ("prepare a board update", "", "PDF export would close the loop", ["pdf-export"], []),
            ("track weekly changes", "the change list is clear", "", ["faster-summary"], []),
            ("print for a meeting", "", "printing breaks the layout; a PDF would fix it", ["pdf-export"], []),
            ("forward to a colleague", "links are useful", "", ["faster-summary"], [])]
    for i, (job, helped, failed, themes, contra) in enumerate(jobs, 1):
        store.add_feedback(DEMO_PROJECT, {"consent": True, "consent_ref": "synthetic fixture", "participant": f"S{i}",
                                          "source": "synthetic", "synthetic": True, "tried": "yes", "job": job,
                                          "helped": helped, "failed": failed, "importance": 4 if failed else 3,
                                          "would_pay": "unknown", "themes": themes, "contra": contra},
                           actor_role="agent", actor="synthetic-demo")
    view = store.view(DEMO_PROJECT)
    top = view["synthetic_themes"]["v1"][0]
    prop = store.propose(DEMO_PROJECT, {"title": "Export the briefing to PDF", "problem": "Participants cannot hand the "
                                        "result to someone else", "change": "Add a PDF export button",
                                        "acceptance_test": "A briefing exports to a PDF that opens and keeps all links",
                                        "theme": top["theme"], "feedback_ids": top["support_ids"]},
                         actor_role="agent", actor="synthetic-demo")["proposal"]
    store.decide(DEMO_PROJECT, prop["id"], {"action": "approve"}, actor_role="owner", actor="synthetic-owner")
    # A synthetic proposal never reaches Relay; the demo marks the hand-off as simulated and ships it directly.
    with store._lock:
        data = store._load()
        p = next(x for x in data["projects"][DEMO_PROJECT]["proposals"] if x["id"] == prop["id"])
        p["state"], p["ticket_id"], p["lane"] = "handed_off", "SIMULATED", "claude"
        p["history"].append({"at": store._now(), "state": "handed_off", "by": "synthetic-demo", "note": "SIMULATED"})
        store._save(data)
    store.decide(DEMO_PROJECT, prop["id"], {"action": "ship", "evidence": [f"{REPO}/pull/1"]},
                 actor_role="owner", actor="synthetic-owner")
    store.release(DEMO_PROJECT, {"evidence": [f"{REPO}/pull/1"]}, actor_role="owner", actor="synthetic-owner")
    for i, solved in ((2, "yes"), (3, "yes"), (4, "partly")):
        store.add_feedback(DEMO_PROJECT, {"consent": True, "consent_ref": "synthetic fixture", "participant": f"S{i}",
                                          "source": "synthetic", "synthetic": True, "tried": "yes", "job": jobs[i - 1][0],
                                          "helped": "PDF export works", "retest_of": prop["id"], "solved": solved},
                           actor_role="agent", actor="synthetic-demo")
    out = store.view(DEMO_PROJECT)
    for p in out["proposals"]:
        p["handoff"] = dict(handoff_status(p, None, False), state="simulated", verification="SIMULATED")
        p["shipped_evidence"] = ["SIMULATED — no real PR"]
    for v in out["versions"]:
        v["evidence"] = ["SIMULATED — no real release"] if v["evidence"] else []
    out["synthetic"] = True
    out["note"] = "SYNTHETIC DEMO — no real participants, tickets, PRs or releases. " + out["note"]
    return out


# --- routes ----------------------------------------------------------------------------------------------------------
def install_mvp_evolution_routes(app, store: EvolutionStore, identity_fn: Callable, *,
                                 create_ticket: Optional[Callable[..., dict]] = None,
                                 ticket_lookup: Callable[[str], Optional[dict]] = lambda tid: None,
                                 ticket_verified: Callable[[dict], bool] = lambda t: False,
                                 mybrief_entries: Optional[Callable[[], list]] = None) -> None:
    """Owner/member JSON API. Feedback is private research data: viewers and anonymous callers get nothing."""

    def _who(request: Request) -> tuple[str, str]:
        ident = identity_fn(request) or {}
        return str(ident.get("role") or ""), str(ident.get("email") or "")

    def _deny(role: str):
        if not role:
            return JSONResponse({"detail": "login_required"}, status_code=401)
        if role not in ("owner", "member"):
            return JSONResponse({"detail": "forbidden"}, status_code=403)
        return None

    async def _body(request: Request) -> dict:
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise EvolutionError("bad_body")
        if not isinstance(body, dict):
            raise EvolutionError("bad_body")
        return body

    async def _run(request: Request, fn):
        role, email = _who(request)
        denial = _deny(role)
        if denial is not None:
            return denial
        try:
            return await fn(role, email)
        except EvolutionError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mvp-evolution-demo")
    async def mvp_evolution_demo(request: Request):
        async def go(role, email):
            return synthetic_demo()
        return await _run(request, go)

    @app.get("/api/mvp-evolution/{project_id}")
    async def mvp_evolution_view(project_id: str, request: Request):
        async def go(role, email):
            return store.view(project_id, ticket_lookup=ticket_lookup, ticket_verified=ticket_verified)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/feedback")
    async def mvp_evolution_feedback(project_id: str, request: Request):
        async def go(role, email):
            return store.add_feedback(project_id, await _body(request), actor_role=role, actor=email)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/feedback/{feedback_id}/delete")
    async def mvp_evolution_feedback_delete(project_id: str, feedback_id: str, request: Request):
        async def go(role, email):
            return store.delete_feedback(project_id, feedback_id, actor_role=role, actor=email)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/funnel")
    async def mvp_evolution_funnel(project_id: str, request: Request):
        async def go(role, email):
            return store.set_funnel(project_id, await _body(request), actor_role=role, actor=email)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/import-mybrief")
    async def mvp_evolution_import(project_id: str, request: Request):
        async def go(role, email):
            if mybrief_entries is None:
                raise EvolutionError("import_unavailable", 503)
            return store.import_mybrief(project_id, mybrief_entries(), actor_role=role, actor=email)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/proposals")
    async def mvp_evolution_propose(project_id: str, request: Request):
        async def go(role, email):
            return store.propose(project_id, await _body(request), actor_role=role, actor=email)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/proposals/{proposal_id}/decision")
    async def mvp_evolution_decide(project_id: str, proposal_id: str, request: Request):
        async def go(role, email):
            return store.decide(project_id, proposal_id, await _body(request), actor_role=role, actor=email,
                                create_ticket=create_ticket)
        return await _run(request, go)

    @app.post("/api/mvp-evolution/{project_id}/release")
    async def mvp_evolution_release(project_id: str, request: Request):
        async def go(role, email):
            return store.release(project_id, await _body(request), actor_role=role, actor=email)
        return await _run(request, go)
