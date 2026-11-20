"""T-704 Business League L1: the Launchpad protocol inside MVP Builder (docs/specs/BUSINESS_LEAGUE_LAUNCHPAD.md).

Discovery checks D1–D7, the 7-day MVP, six channels and Learn, with gates G1–G5, as data on the project record:
`projects[pid]["launchpad"]` of the same `mvp_factory.json`, under the registry's own lock, idempotency table and
event log (the `mvp_experiments.py` pattern). No second registry, scheduler, worker or service.

What this module never does: it never changes a project stage, and it has no network, publishing, messaging, ad or
payment call. It stores plans and evidence. Spend and outreach approvals are false until the owner sets them.

Honesty rules enforced here, not left to the writer:
- a market fact or a signal needs a source URL and an observation date;
- missing data is stored as "unknown", a zero is a valid result and is shown as 0;
- `test` and `synthetic` records are left out of every count, funnel and gate;
- likes, views and clicks are not demand: unknown fields are refused, and only leads and payments count as demand;
- a publication ban or zero reach is a blocker, not "no demand";
- status ladders move forward one rung at a time, with evidence;
- an agent writes at most `linked`; `accepted` comes only from the owner; no agent decides a gate on its own work.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_factory import EVIDENCE_CHECK, MvpError, MvpRegistry, _iso

SCHEMA = "mvp-launchpad/1"
UNKNOWN = "unknown"
MAX_ARTIFACTS = 500
ROLES = ("owner", "member", "agent")
LEVELS = ("claimed", "linked", "checked", "accepted")

# check id → cycle phase, artifact types, learning target (min, max) of real records, gate that follows
CHECKS = (
    ("D1", "battle", ("idea_card",), (5, None), None),
    ("D2", "battle", ("market_fact",), (None, None), "G1"),
    ("D3", "battle", ("signal",), (10, 20), "G2"),
    ("D4", "battle", ("test_card", "channel_entry"), (1, 2), None),
    ("D5", "battle", ("test_card", "channel_entry"), (1, None), None),
    ("D6", "battle", ("test_card", "channel_entry"), (None, None), None),
    ("D7", "battle", ("interview_note",), (None, None), "G3"),
    ("MVP", "build", ("channel_entry",), (1, None), "G4"),
    ("CH", "promote", ("test_card", "channel_entry"), (None, None), None),
    ("LEARN", "learn", (), (None, None), "G5"),
)
CHECK_IDS = tuple(c[0] for c in CHECKS)
DEFAULT_CHECK = {"idea_card": "D1", "market_fact": "D2", "signal": "D3", "interview_note": "D7"}
CHANNELS = ("direct_sales", "communities", "organic_content", "seo_catalogs", "partners", "paid", "organic_social",
            "landing", "product")
FUNNEL = ("reach", "clicks", "leads", "main_scenario_done", "payments")
DEMAND_FIELDS = ("leads", "payments")          # reach and clicks are attention, never demand
NUMBERS = ("reach", "clicks", "leads", "active_users", "main_scenario_done", "payments", "time_spent_h", "money_spent")
BLOCKERS = ("publication_ban", "zero_reach", "account_restricted")

LADDERS = {
    "campaign": ("draft", "moderation", "active", ("finished", "stopped")),
    "listing": ("submitted", "published"),
    "outreach": ("sent", "replied", "negotiating", "test_confirmed", "live"),
    "deal": ("verbal_yes", "invoiced", "paid"),
    "usage": ("demo_viewed", "signed_up", "main_scenario_done"),
}
OWNER_ONLY_RUNGS = {("deal", "paid")}          # a payment is `accepted`: the owner confirms it

GATES = ("G1", "G2", "G3", "G4", "G5")
OWNER_ONLY_GATES = ("G3", "G4", "G5")
GATE_CHECKS = {"G1": ("D1", "D2"), "G2": ("D1", "D2", "D3"), "G3": ("D4", "D5", "D6", "D7"), "G4": ("MVP",),
               "G5": ("CH", "MVP")}
GATE_CHOICES = {"G3": ("build_minimum", "change_assumption", "back_to_idea"), "G4": ("yes", "no"),
                "G5": ("continue", "iterate", "pivot", "kill")}

URL_RE = re.compile(r"^https://(?=[^/\s]{4,253}(/|$))([a-z0-9-]+\.)+[a-z]{2,}(/[^\s<>\"']*)?$", re.I)
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REF_RE = re.compile(r"^a-\d{1,6}$")
PARTICIPANT_RE = re.compile(r"^p-[0-9a-f]{8,32}$")
PII = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}|(?<!\d)\+?\d(?:[\s().-]?\d){8,13}(?!\d)")
COMMON = {"type", "check", "test", "synthetic", "idempotency_key"}


def _text(value: Any, limit: int, *, required: bool = False, redact: bool = False) -> str:
    """Clean text. Missing optional text becomes "unknown": a model never fills a gap (validator 2)."""
    if value is None or value == "":
        if required:
            raise MvpError("text_required")
        return UNKNOWN
    if not isinstance(value, str):
        raise MvpError("bad_text")
    out = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", value).replace("\r", "").strip()
    if redact:
        out = PII.sub("[redacted]", out)
    elif PII.search(out):
        raise MvpError("personal_data")
    if len(out) > limit:
        raise MvpError("text_too_long")
    if required and not out:
        raise MvpError("text_required")
    return out or UNKNOWN


def _url(value: Any, *, required: bool = True) -> str:
    text = str(value or "").strip()
    if not text and not required:
        return UNKNOWN
    if not URL_RE.match(text) or "@" in text.split("/", 3)[2] or len(text) > 500:
        raise MvpError("source_url_required" if required and not text else "bad_url")
    return text


def _date(value: Any, today: str, *, required: bool) -> str:
    text = str(value or "").strip()
    if not text or text == UNKNOWN:
        if required:
            raise MvpError("date_required")
        return UNKNOWN
    try:
        if not DATE_RE.match(text):
            raise ValueError
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        raise MvpError("bad_date")
    if text > today:
        raise MvpError("date_in_future")
    return text


def _number(value: Any) -> Any:
    """None → "unknown"; 0 is a real result and stays 0 (honest zero)."""
    if value is None or value == UNKNOWN:
        return UNKNOWN
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0 or value > 10 ** 9:
        raise MvpError("bad_number")
    return value


def _refs(value: Any, *, required: bool = False) -> list[str]:
    items = value if isinstance(value, list) else ([value] if value else [])
    if len(items) > 20 or any(not isinstance(x, str) or not REF_RE.match(x) for x in items):
        raise MvpError("bad_ref")
    if required and not items:
        raise MvpError("ref_required")
    return list(dict.fromkeys(items))


def _list(value: Any, limit: int, each: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise MvpError("bad_list")
    return [_text(x, each, required=True) for x in value]


def _fields(body: dict, allowed: set) -> None:
    extra = set(body) - allowed - COMMON
    if extra & {"level", "actor", "role", "id", "created_at", "events", "approvals", "status_history"}:
        raise MvpError("server_field_not_settable")
    if extra & {"likes", "views", "impressions", "ctr", "followers", "score", "credibility"}:
        raise MvpError("attention_is_not_demand")     # validator 5 and the "no self-assessed score" rule
    if extra:
        raise MvpError("unknown_fields")


def validate_artifact(body: dict, today: str) -> dict:
    """Return a clean artifact (type, check, fields, flags) or raise MvpError with a stable code."""
    if not isinstance(body, dict):
        raise MvpError("bad_body")
    kind = body.get("type")
    b = body
    if kind == "idea_card":
        _fields(b, {"who", "situation", "problem", "desired_result", "where_noticed", "assumptions"})
        noticed = b.get("where_noticed") or []
        noticed = noticed if isinstance(noticed, list) else [noticed]
        if not noticed or len(noticed) > 5:
            raise MvpError("where_noticed_required")
        fields = {"who": _text(b.get("who"), 300, required=True), "situation": _text(b.get("situation"), 500),
                  "problem": _text(b.get("problem"), 500, required=True), "desired_result": _text(b.get("desired_result"), 500),
                  "where_noticed": [x if x == "own_experience" else _url(x) for x in noticed],
                  "assumptions": _list(b.get("assumptions"), 10, 300)}
        sources = [x for x in fields["where_noticed"] if x != "own_experience"]
    elif kind == "market_fact":
        _fields(b, {"idea_ref", "fact", "source_url", "source_kind", "observed_at", "published_at", "query", "alternative",
                    "price", "complaint", "verdict", "unknowns"})
        if b.get("source_kind") not in ("primary", "secondary"):
            raise MvpError("bad_source_kind")
        if b.get("verdict") not in ("for", "against"):
            raise MvpError("bad_verdict")
        fields = {"idea_ref": _refs(b.get("idea_ref"), required=True), "fact": _text(b.get("fact"), 600, required=True),
                  "source_url": _url(b.get("source_url")), "source_kind": b["source_kind"],
                  "observed_at": _date(b.get("observed_at"), today, required=True),
                  "published_at": _date(b.get("published_at"), today, required=False),
                  "query": _text(b.get("query"), 200), "alternative": _text(b.get("alternative"), 300),
                  "price": _text(b.get("price"), 120), "complaint": _text(b.get("complaint"), 300),
                  "verdict": b["verdict"], "unknowns": _list(b.get("unknowns"), 10, 200)}
        sources = [fields["source_url"]]
    elif kind == "signal":
        _fields(b, {"idea_ref", "url", "posted_at", "observed_at", "situation", "current_solution", "author_words", "independent"})
        if not isinstance(b.get("independent"), bool):
            raise MvpError("independent_yes_or_no")
        fields = {"idea_ref": _refs(b.get("idea_ref"), required=True), "url": _url(b.get("url")),
                  "posted_at": _date(b.get("posted_at"), today, required=False),
                  "observed_at": _date(b.get("observed_at"), today, required=True),
                  "situation": _text(b.get("situation"), 500, required=True),
                  "current_solution": _text(b.get("current_solution"), 300),
                  "author_words": _text(b.get("author_words"), 280, redact=True), "independent": b["independent"]}
        sources = [fields["url"]]
    elif kind == "test_card":
        _fields(b, {"hypothesis", "channel", "audience", "message", "creative_ref", "page_ref", "target_event", "period",
                    "spend_limit", "stop_condition", "success_signal", "exp_id"})
        if b.get("channel") not in CHANNELS:
            raise MvpError("bad_channel")
        limit = 0 if b.get("spend_limit") is None else _number(b.get("spend_limit"))
        fields = {"hypothesis": _text(b.get("hypothesis"), 400, required=True), "channel": b["channel"],
                  "audience": _text(b.get("audience"), 300, required=True), "message": _text(b.get("message"), 600),
                  "creative_ref": _url(b.get("creative_ref"), required=False), "page_ref": _url(b.get("page_ref"), required=False),
                  "target_event": _text(b.get("target_event"), 120), "period": _text(b.get("period"), 80),
                  "spend_limit": limit, "stop_condition": _text(b.get("stop_condition"), 300),
                  "success_signal": _text(b.get("success_signal"), 300),
                  "exp_id": _text(b.get("exp_id"), 41)}
        if limit and (fields["period"] == UNKNOWN or fields["stop_condition"] == UNKNOWN):
            raise MvpError("spend_needs_period_and_stop")   # fixed before launch, never after
        sources = []
    elif kind == "interview_note":
        _fields(b, {"consent_ref", "participant", "last_real_case", "frequency", "current_solution", "cost", "consequences",
                    "roles", "ask_made", "outcome"})
        if not PARTICIPANT_RE.match(str(b.get("participant") or "")):
            raise MvpError("participant_hash_required")     # never a name or a contact
        if b.get("outcome") not in ("agreed", "refused", "conditions", "no_decision"):
            raise MvpError("bad_outcome")
        fields = {"consent_ref": _text(b.get("consent_ref"), 200, required=True), "participant": b["participant"],
                  "last_real_case": _text(b.get("last_real_case"), 600, required=True),
                  "frequency": _text(b.get("frequency"), 200), "current_solution": _text(b.get("current_solution"), 300),
                  "cost": _text(b.get("cost"), 200), "consequences": _text(b.get("consequences"), 300),
                  "roles": _text(b.get("roles"), 200), "ask_made": _text(b.get("ask_made"), 300, required=True),
                  "outcome": b["outcome"]}
        sources = []
    elif kind == "channel_entry":
        _fields(b, {"channel", "action", "period", "test_ref", "ladder", "status", "blocker", "evidence", *NUMBERS})
        if b.get("channel") not in CHANNELS:
            raise MvpError("bad_channel")
        ladder = b.get("ladder")
        if ladder is not None and ladder not in LADDERS:
            raise MvpError("bad_ladder")
        if ladder and b.get("status") not in (None, LADDERS[ladder][0]):
            raise MvpError("ladder_starts_at_first_rung")   # no entry is born "paid" or "live"
        if b.get("blocker") not in (None, *BLOCKERS):
            raise MvpError("bad_blocker")
        evidence = [_url(x) for x in (b.get("evidence") or [])][:5]
        fields = {"channel": b["channel"], "action": _text(b.get("action"), 400, required=True),
                  "period": _text(b.get("period"), 80), "test_ref": (_refs(b.get("test_ref")) or [None])[0],
                  "ladder": ladder, "status": LADDERS[ladder][0] if ladder else None, "blocker": b.get("blocker"),
                  "evidence": evidence, **{n: _number(b.get(n)) for n in NUMBERS}}
        sources = evidence
    else:
        raise MvpError("bad_type")
    check = b.get("check") or DEFAULT_CHECK.get(kind)
    if check not in CHECK_IDS or kind not in dict((c[0], c[2]) for c in CHECKS)[check]:
        raise MvpError("bad_check")
    for flag in ("test", "synthetic"):
        if not isinstance(b.get(flag, False), bool):
            raise MvpError("bad_flag")
    return {"type": kind, "check": check, "fields": fields, "test": bool(b.get("test", False)),
            "synthetic": bool(b.get("synthetic", False)), "sources": sources}


def real(a: dict) -> bool:
    """Counts, funnels and gates only ever see these records (validator 4)."""
    return not a.get("test") and not a.get("synthetic")


def _empty() -> dict:
    return {"schema": SCHEMA, "seq": 0, "artifacts": {}, "gates": {g: {"proposals": [], "decision": None} for g in GATES}}


def _known(n: Any) -> bool:
    return isinstance(n, (int, float)) and not isinstance(n, bool)


def funnel(entries: list[dict]) -> dict:
    """Summed stages of one channel and the largest drop between two known neighbours. Unknown stays unknown."""
    totals = {}
    for stage in FUNNEL:
        known = [e["fields"][stage] for e in entries if _known(e["fields"].get(stage))]
        totals[stage] = sum(known) if known else UNKNOWN
    drop = None
    for a, b in zip(FUNNEL, FUNNEL[1:]):
        if _known(totals[a]) and _known(totals[b]) and totals[a] > 0:
            lost = round(1 - totals[b] / totals[a], 3)
            if drop is None or lost > drop["lost_share"]:
                drop = {"from": a, "to": b, "lost_share": lost}
    blockers = sorted({e["fields"]["blocker"] for e in entries if e["fields"].get("blocker")})
    demand = [totals[k] for k in DEMAND_FIELDS if _known(totals[k])]
    reading = "blocked" if blockers else (UNKNOWN if not demand else ("demand_seen" if sum(demand) > 0 else "honest_zero"))
    return {"stages": totals, "largest_drop": drop, "blockers": blockers, "demand_reading": reading, "entries": len(entries)}


def board(project: dict) -> dict:
    """The Launchpad view of one project. Empty checks are "unknown"; nothing is invented to fill a target."""
    lp = project.get("launchpad") or _empty()
    arts = sorted(lp["artifacts"].values(), key=lambda a: int(a["id"][2:]))
    checks = []
    for cid, phase, types, (lo, hi), gate in CHECKS:
        mine = [a for a in arts if a["check"] == cid]
        counted = [a for a in mine if real(a)]
        levels = {lv: sum(1 for a in counted if a["level"] == lv) for lv in LEVELS}
        actual: Any = len(counted) if mine else UNKNOWN
        checks.append({"id": cid, "phase": phase, "types": list(types), "target": {"min": lo, "max": hi},
                       "actual": actual, "honest_zero": bool(mine) and not counted, "levels": levels,
                       "excluded": {"test": sum(1 for a in mine if a["test"]), "synthetic": sum(1 for a in mine if a["synthetic"])},
                       "target_met": UNKNOWN if actual == UNKNOWN or lo is None else actual >= lo, "gate_after": gate,
                       "loop": [e for a in mine for e in a["events"]][-12:]})
    gates = []
    for g in GATES:
        state = lp["gates"][g]
        gates.append({"gate": g, "who_decides": "owner" if g in OWNER_ONLY_GATES else "judge_or_owner",
                      "state": "decided" if state["decision"] else ("proposed" if state["proposals"] else "pending"),
                      "proposals": state["proposals"][-5:], "decision": state["decision"]})
    entries = [a for a in arts if a["type"] == "channel_entry" and real(a)]
    funnels = {ch: funnel([e for e in entries if e["fields"]["channel"] == ch])
               for ch in CHANNELS if any(e["fields"]["channel"] == ch for e in entries)}
    # One gate at a time: the earliest undecided gate that already has real records to decide on.
    needs = []
    for g in gates:
        if g["state"] == "decided" and not (g["decision"] or {}).get("extra_check"):
            continue
        if any(c["actual"] not in (UNKNOWN, 0) for c in checks if c["id"] in GATE_CHECKS[g["gate"]]):
            needs.append({"kind": "gate", "gate": g["gate"], "state": g["state"]})
            break
    for a in arts:
        if a["type"] == "test_card" and real(a):
            for kind in ("spend", "outreach"):
                wanted = a["fields"]["spend_limit"] > 0 if kind == "spend" else a["fields"]["channel"] in ("direct_sales", "partners")
                if wanted and not a["approvals"][kind]:
                    needs.append({"kind": kind + "_approval", "artifact": a["id"], "channel": a["fields"]["channel"]})
    g5 = lp["gates"]["G5"]["decision"] or {}
    learn = {"verdict": g5.get("chosen", UNKNOWN), "main_channel": g5.get("main_channel", UNKNOWN),
             "main_metric": g5.get("main_metric", UNKNOWN), "price_covers_direct_cost": g5.get("price_covers_direct_cost", UNKNOWN)}
    return {"project": project.get("id"), "schema": SCHEMA, "checks": checks, "gates": gates, "funnels": funnels,
            "needs_you": needs, "learn": learn, "artifacts": arts[-200:], "artifact_count": len(arts),
            "note": "Plans and evidence only. Nothing here posts, messages, advertises or charges. "
                    "Test and synthetic records are shown but never counted."}


def learn_facts(project: dict) -> dict:
    """Short facts for the cycle panel's Learn phase (mvp_cycle.cycle_view)."""
    lp = project.get("launchpad")
    if not lp:
        return {"started": False}
    view = board(project)
    return {"started": True, "gates": {g["gate"]: g["state"] for g in view["gates"]}, **view["learn"]}


class Launchpad:
    """Launchpad writes on top of an MvpRegistry (same lock, same file, same keys table, same event log)."""

    def __init__(self, registry: MvpRegistry):
        self.r = registry

    # -- helpers ----------------------------------------------------------------------------------------------
    def _today(self) -> str:
        return datetime.fromtimestamp(self.r.clock(), timezone.utc).strftime("%Y-%m-%d")

    @staticmethod
    def _scope(op: str, pid: str, actor: str, payload: Any) -> dict:
        fp = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]
        return {"project": pid, "kind": "lp:" + op, "actor": actor, "fingerprint": fp}

    @staticmethod
    def _guard(data: dict, key: Any, scope: dict):
        key = str(key or "")[:80]
        if key and key in data["keys"]:
            held = data["keys"][key]
            if {k: held.get(k) for k in scope} != scope:
                raise MvpError("idempotency_conflict", 409)
            return key, held.get("result")
        return key, None

    def _open(self, data: dict, pid: str) -> tuple[dict, dict]:
        project = data["projects"].get(pid)
        if not project:
            raise MvpError("unknown_project", 404)
        return project, project.setdefault("launchpad", _empty())

    def _event(self, data: dict, project: dict, actor: str, note: str, evidence: list | None = None) -> dict:
        ev = {"id": f"ev-{len(data['events']) + 1}-{int(self.r.clock() * 1000)}", "project": project["id"],
              "at": _iso(self.r.clock()), "actor": actor, "kind": "note", "from_stage": project["stage"],
              "to_stage": project["stage"], "evidence": [], "evidence_check": EVIDENCE_CHECK, "note": note[:500],
              "launchpad": True, "launchpad_evidence": (evidence or [])[:5]}
        data["events"].append(ev)                      # a note: the stage is the same before and after
        return ev

    @staticmethod
    def _artifact(lp: dict, aid: str) -> dict:
        art = lp["artifacts"].get(str(aid))
        if not art:
            raise MvpError("unknown_artifact", 404)
        return art

    def _finish(self, data: dict, key: str, scope: dict, result: dict) -> dict:
        if key:
            data["keys"][key] = dict(scope, result=result)
        self.r._save(data)
        return result

    # -- operations -------------------------------------------------------------------------------------------
    def add_artifact(self, pid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        if actor_role not in ROLES:
            raise MvpError("forbidden", 403)
        spec = validate_artifact(body, self._today())
        who = actor or actor_role
        scope = self._scope("artifact", pid, who, spec)
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "artifact": done}
            project, lp = self._open(data, pid)
            if len(lp["artifacts"]) >= MAX_ARTIFACTS:
                raise MvpError("artifact_limit", 409)
            f = spec["fields"]
            for ref in f.get("idea_ref") or []:
                if self._artifact(lp, ref)["type"] != "idea_card":
                    raise MvpError("idea_ref_must_be_an_idea")
            if f.get("test_ref"):
                card = self._artifact(lp, f["test_ref"])
                if card["type"] != "test_card":
                    raise MvpError("test_ref_must_be_a_test_card")
                if f.get("ladder") == "outreach" and not card["approvals"]["outreach"]:
                    raise MvpError("outreach_not_approved", 409)    # "sent" is recorded only for approved outreach
            elif f.get("ladder") == "outreach":
                raise MvpError("outreach_needs_a_test_card")
            if spec["check"] == "D6" and spec["type"] == "test_card" and not self._d5_ready(lp):
                raise MvpError("paid_test_needs_d5", 409)
            lp["seq"] += 1
            now = _iso(self.r.clock())
            art = {"id": f"a-{lp['seq']}", "type": spec["type"], "check": spec["check"], "fields": f, "test": spec["test"],
                   "synthetic": spec["synthetic"], "level": "linked" if spec["sources"] else "claimed",
                   "actor": who, "role": actor_role, "created_at": now, "updated_at": now,
                   "events": [{"step": "produced", "by": who, "role": actor_role, "at": now, "artifact": f"a-{lp['seq']}"}]}
            if spec["type"] == "test_card":
                art["approvals"] = {"spend": None, "outreach": None}
                art["changes_after_approval"] = 0
            if f.get("ladder"):
                art["status_history"] = [{"status": f["status"], "at": now, "by": who, "level": art["level"], "evidence": f["evidence"]}]
            lp["artifacts"][art["id"]] = art
            self._event(data, project, who, f"Launchpad {spec['check']}: {spec['type']} {art['id']} recorded at level {art['level']}"
                        + (" (test)" if art["test"] else "") + (" (synthetic)" if art["synthetic"] else "") + ".", spec["sources"])
            return {"duplicate": False, "artifact": self._finish(data, key, scope, art)}

    @staticmethod
    def _d5_ready(lp: dict) -> bool:
        """A paid test is eligible only after D5 has a page, a tracked target event and an audience."""
        return any(a["check"] == "D5" and a["type"] == "test_card" and real(a) and a["fields"]["page_ref"] != UNKNOWN
                   and a["fields"]["target_event"] != UNKNOWN and a["fields"]["audience"] != UNKNOWN
                   for a in lp["artifacts"].values())

    def review(self, pid: str, aid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        """The second model completes and checks the same artifact; the producer cannot review its own work."""
        if actor_role not in ROLES:
            raise MvpError("forbidden", 403)
        if not isinstance(body, dict) or set(body) - {"verdict", "note", "idempotency_key"}:
            raise MvpError("unknown_fields")
        if body.get("verdict") not in ("confirmed", "needs_work"):
            raise MvpError("bad_verdict")
        note = _text(body.get("note"), 400, required=True)
        who = actor or actor_role
        scope = self._scope("review", pid, who, [aid, body.get("verdict"), note])
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "artifact": done}
            project, lp = self._open(data, pid)
            art = self._artifact(lp, aid)
            if art["actor"] == who:
                raise MvpError("own_work", 403)
            now = _iso(self.r.clock())
            art["events"].append({"step": "reviewed", "by": who, "role": actor_role, "at": now, "artifact": art["id"],
                                  "verdict": body["verdict"], "note": note})
            art["updated_at"] = now                     # a review never raises the evidence level
            self._event(data, project, who, f"Launchpad {art['check']}: {art['id']} reviewed ({body['verdict']}).")
            return {"duplicate": False, "artifact": self._finish(data, key, scope, art)}

    def step(self, pid: str, aid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        """Move a ladder one rung forward, with evidence."""
        if actor_role not in ROLES:
            raise MvpError("forbidden", 403)
        if not isinstance(body, dict) or set(body) - {"to", "evidence", "note", "idempotency_key"}:
            raise MvpError("unknown_fields")
        evidence = [_url(x) for x in (body.get("evidence") or [])][:5]
        note = _text(body.get("note"), 300)
        who = actor or actor_role
        scope = self._scope("step", pid, who, [aid, body.get("to"), evidence, note])
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "artifact": done}
            project, lp = self._open(data, pid)
            art = self._artifact(lp, aid)
            f = art["fields"]
            ladder = f.get("ladder")
            if art["type"] != "channel_entry" or not ladder:
                raise MvpError("no_ladder")
            rungs = LADDERS[ladder]
            flat = [r for r in rungs if isinstance(r, str)]
            last = rungs[-1] if isinstance(rungs[-1], tuple) else (rungs[-1],)
            if f["status"] in last:
                raise MvpError("ladder_finished", 409)
            nxt = rungs[flat.index(f["status"]) + 1]
            allowed = nxt if isinstance(nxt, tuple) else (nxt,)
            if ladder == "campaign" and f["status"] in ("moderation", "active"):
                allowed = (*allowed, "stopped")         # a campaign can be stopped from any running rung
            if body.get("to") not in allowed:
                raise MvpError("one_rung_at_a_time", 409)
            if (ladder, body["to"]) in OWNER_ONLY_RUNGS and actor_role != "owner":
                raise MvpError("owner_only", 403)
            if actor_role != "owner" and not evidence:
                raise MvpError("evidence_required")
            if ladder == "campaign" and body["to"] in ("moderation", "active"):
                card = lp["artifacts"].get(f.get("test_ref") or "")
                if not card or (card["fields"]["spend_limit"] > 0 and not card["approvals"]["spend"]):
                    raise MvpError("spend_not_approved", 409)
            now = _iso(self.r.clock())
            level = "accepted" if actor_role == "owner" else "linked"
            f["status"] = body["to"]
            art["status_history"].append({"status": body["to"], "at": now, "by": who, "level": level, "evidence": evidence, "note": note})
            art["updated_at"] = now
            self._event(data, project, who, f"Launchpad {art['check']}: {art['id']} {ladder} → {body['to']} ({level}).", evidence)
            return {"duplicate": False, "artifact": self._finish(data, key, scope, art)}

    def approve(self, pid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        """Owner-only spend or outreach approval of a test card. Nothing is launched by this call."""
        if actor_role != "owner":
            raise MvpError("owner_only", 403)
        if not isinstance(body, dict) or set(body) - {"artifact", "kind", "spend_limit", "period", "stop_condition", "idempotency_key"}:
            raise MvpError("unknown_fields")
        if body.get("kind") not in ("spend", "outreach"):
            raise MvpError("bad_kind")
        who = actor or actor_role
        with self.r._lock:
            data = self.r._load()
            project, lp = self._open(data, pid)
            card = self._artifact(lp, body.get("artifact"))
            if card["type"] != "test_card" or not real(card):
                raise MvpError("not_a_real_test_card", 409)   # no approval on test or synthetic records
            f = card["fields"]
            changes = {k: body[k] for k in ("spend_limit", "period", "stop_condition") if k in body}
            if changes:
                if card["approvals"]["spend"] or card["approvals"]["outreach"]:
                    if card["changes_after_approval"] >= 1:
                        raise MvpError("one_change_per_running_test", 409)
                    card["changes_after_approval"] += 1
                if "spend_limit" in changes:
                    f["spend_limit"] = _number(changes["spend_limit"]) if changes["spend_limit"] is not None else 0
                    if f["spend_limit"] == UNKNOWN:
                        raise MvpError("bad_number")
                for k in ("period", "stop_condition"):
                    if k in changes:
                        f[k] = _text(changes[k], 300, required=True)
            if body["kind"] == "spend":
                if f["spend_limit"] <= 0:
                    raise MvpError("nothing_to_approve", 409)
                if f["period"] == UNKNOWN or f["stop_condition"] == UNKNOWN:
                    raise MvpError("spend_needs_period_and_stop", 409)
                if not self._d5_ready(lp):
                    raise MvpError("paid_test_needs_d5", 409)
            if card["approvals"][body["kind"]] and not changes:
                return {"duplicate": True, "artifact": card}
            ev = self._event(data, project, who, f"Owner approved {body['kind']} for test card {card['id']}"
                             + (f" (limit {f['spend_limit']}, {f['period']})" if body["kind"] == "spend" else "")
                             + ". Launchpad itself launches nothing.")
            card["approvals"][body["kind"]] = {"at": ev["at"], "by": who, "event_id": ev["id"],
                                               "spend_limit": f["spend_limit"] if body["kind"] == "spend" else None}
            card["updated_at"] = ev["at"]
            self.r._save(data)
            return {"duplicate": False, "artifact": card}

    def edit_test_card(self, pid: str, aid: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        """Before approval anyone on the team may fix limit, period and stop condition; afterwards they are locked."""
        if actor_role not in ROLES:
            raise MvpError("forbidden", 403)
        if not isinstance(body, dict) or not body or set(body) - {"spend_limit", "period", "stop_condition"}:
            raise MvpError("unknown_fields")
        with self.r._lock:
            data = self.r._load()
            project, lp = self._open(data, pid)
            card = self._artifact(lp, aid)
            if card["type"] != "test_card":
                raise MvpError("not_a_test_card", 409)
            if card["approvals"]["spend"] or card["approvals"]["outreach"]:
                raise MvpError("locked_after_approval", 409)   # the owner changes it through approve(), once
            f = card["fields"]
            if "spend_limit" in body:
                f["spend_limit"] = _number(body["spend_limit"])
                if f["spend_limit"] == UNKNOWN:
                    raise MvpError("bad_number")
            for k in ("period", "stop_condition"):
                if k in body:
                    f[k] = _text(body[k], 300, required=True)
            card["updated_at"] = _iso(self.r.clock())
            self._event(data, project, actor or actor_role, f"Launchpad: test card {card['id']} terms edited before approval.")
            self.r._save(data)
            return {"artifact": card}

    def gate(self, pid: str, gate: str, body: dict, *, actor_role: str, actor: str = "") -> dict:
        """Propose (anyone on the team) or decide (owner; for G1/G2 also a judge who produced none of the work)."""
        if gate not in GATES:
            raise MvpError("unknown_gate", 404)
        if actor_role not in ROLES:
            raise MvpError("forbidden", 403)
        allowed = {"action", "chosen", "deferred", "rationale", "evidence_refs", "extra_check", "main_channel",
                   "main_metric", "price_covers_direct_cost", "idempotency_key"}
        if not isinstance(body, dict) or set(body) - allowed:
            raise MvpError("unknown_fields")
        action = body.get("action")
        if action not in ("propose", "decide"):
            raise MvpError("bad_action")
        rationale = _text(body.get("rationale"), 800, required=True)
        refs = _refs(body.get("evidence_refs"), required=True)
        who = actor or actor_role
        scope = self._scope("gate", pid, who, [gate, {k: body.get(k) for k in sorted(allowed - {"idempotency_key"})}])
        with self.r._lock:
            data = self.r._load()
            key, done = self._guard(data, body.get("idempotency_key"), scope)
            if done is not None:
                return {"duplicate": True, "gate": done}
            project, lp = self._open(data, pid)
            state = lp["gates"][gate]
            if state["decision"] and not state["decision"].get("extra_check"):
                raise MvpError("gate_decided", 409)
            arts = lp["artifacts"]
            for ref in refs:                              # validator 7: no gate on drafts, test or synthetic data
                if not real(self._artifact(lp, ref)):
                    raise MvpError("evidence_not_real", 409)
            record = {"gate": gate, "rationale": rationale, "evidence_refs": refs, "by": who, "role": actor_role,
                      "at": _iso(self.r.clock())}
            extra = body.get("extra_check")
            if extra is not None:                         # thin evidence → a named extra check, never a build
                record["extra_check"] = _text(extra, 200, required=True)
                record["chosen"] = None
            else:
                record.update(self._choice(lp, gate, body))
            if action == "decide":
                if gate in OWNER_ONLY_GATES and actor_role != "owner":
                    raise MvpError("owner_only", 403)
                if actor_role != "owner":
                    produced = {a["actor"] for a in arts.values() if a["check"] in GATE_CHECKS[gate]}
                    produced |= {p["by"] for p in state["proposals"]}
                    if who in produced:
                        raise MvpError("own_work", 403)   # a judge produced none of the compared work
                idx = GATES.index(gate)
                if "extra_check" not in record and idx and not (lp["gates"][GATES[idx - 1]]["decision"] or {}).get("chosen"):
                    raise MvpError("previous_gate_open", 409)
                record["decided_by"] = who
                state["decision"] = record
            else:
                state["proposals"] = (state["proposals"] + [record])[-20:]
            self._event(data, project, who, f"Launchpad gate {gate} {'decided' if action == 'decide' else 'proposed'} by {who}: "
                        + (f"extra check — {record['extra_check']}" if record.get("extra_check") else str(record.get("chosen"))) + ".")
            return {"duplicate": False, "gate": self._finish(data, key, scope, record)}

    @staticmethod
    def _choice(lp: dict, gate: str, body: dict) -> dict:
        arts = lp["artifacts"]
        chosen = body.get("chosen")
        if gate in ("G1", "G2"):
            ideas = _refs(chosen, required=True)
            pool = {a["id"] for a in arts.values() if a["type"] == "idea_card" and real(a)}
            if gate == "G2":
                prior = (lp["gates"]["G1"]["decision"] or {}).get("chosen")
                pool = set(prior) if prior else pool
            if not set(ideas) <= pool or len(ideas) > (3 if gate == "G1" else 2):
                raise MvpError("bad_choice")
            deferred = body.get("deferred") or {}
            if not isinstance(deferred, dict) or set(deferred) != pool - set(ideas):
                raise MvpError("every_deferred_idea_needs_a_reason")
            return {"chosen": ideas, "deferred": {k: _text(v, 300, required=True) for k, v in deferred.items()}}
        if chosen not in GATE_CHOICES[gate]:
            raise MvpError("bad_choice")
        out = {"chosen": chosen}
        if gate == "G4" and chosen == "yes":
            # Demo views, mock-ups and colleague opinions do not count: one real user finished the main scenario,
            # confirmed above the agent's own word (checked by the server or accepted by the owner).
            ok = any(a["type"] == "channel_entry" and real(a) and a["fields"].get("ladder") == "usage"
                     and a["fields"]["status"] == "main_scenario_done"
                     and a["status_history"][-1]["level"] in ("checked", "accepted") for a in arts.values())
            if not ok:
                raise MvpError("no_confirmed_user", 409)
        if gate == "G5":
            if chosen == "continue":
                if body.get("main_channel") not in CHANNELS:
                    raise MvpError("main_channel_required")
                out["main_channel"] = body["main_channel"]
                out["main_metric"] = _text(body.get("main_metric"), 80, required=True)
            cover = body.get("price_covers_direct_cost", UNKNOWN)
            if cover not in ("yes", "no", UNKNOWN):
                raise MvpError("bad_choice")
            out["price_covers_direct_cost"] = cover
        return out


def install_mvp_launchpad_routes(app, registry: MvpRegistry, identity_fn: Callable) -> Launchpad:
    store = Launchpad(registry)

    def _who(request: Request) -> tuple[str, str]:
        ident = identity_fn(request) or {}
        return str(ident.get("role") or ""), str(ident.get("email") or "")

    async def _call(request: Request, fn):
        try:
            body = await request.json()
        except ValueError:
            body = None
        if not isinstance(body, dict):
            return JSONResponse({"detail": "bad_body"}, status_code=400)
        role, email = _who(request)
        try:
            return fn(body, role, email)
        except MvpError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.get("/api/mvp-factory/{project_id}/launchpad")
    def mvp_launchpad_board(project_id: str):
        with registry._lock:
            data = registry._load()
        project = data["projects"].get(project_id)
        if not project:
            return JSONResponse({"detail": "unknown_project"}, status_code=404)
        return board(project)

    @app.post("/api/mvp-factory/{project_id}/launchpad/artifacts")
    async def mvp_launchpad_artifact(project_id: str, request: Request):
        return await _call(request, lambda b, role, who: store.add_artifact(project_id, b, actor_role=role, actor=who))

    @app.post("/api/mvp-factory/{project_id}/launchpad/artifacts/{aid}/status")
    async def mvp_launchpad_status(project_id: str, aid: str, request: Request):
        return await _call(request, lambda b, role, who: store.step(project_id, aid, b, actor_role=role, actor=who))

    @app.post("/api/mvp-factory/{project_id}/launchpad/artifacts/{aid}/review")
    async def mvp_launchpad_review(project_id: str, aid: str, request: Request):
        return await _call(request, lambda b, role, who: store.review(project_id, aid, b, actor_role=role, actor=who))

    @app.post("/api/mvp-factory/{project_id}/launchpad/artifacts/{aid}/terms")
    async def mvp_launchpad_terms(project_id: str, aid: str, request: Request):
        return await _call(request, lambda b, role, who: store.edit_test_card(project_id, aid, b, actor_role=role, actor=who))

    @app.post("/api/mvp-factory/{project_id}/launchpad/gates/{gate}")
    async def mvp_launchpad_gate(project_id: str, gate: str, request: Request):
        return await _call(request, lambda b, role, who: store.gate(project_id, gate, b, actor_role=role, actor=who))

    @app.post("/api/mvp-factory/{project_id}/launchpad/approvals")
    async def mvp_launchpad_approval(project_id: str, request: Request):
        return await _call(request, lambda b, role, who: store.approve(project_id, b, actor_role=role, actor=who))

    return store
