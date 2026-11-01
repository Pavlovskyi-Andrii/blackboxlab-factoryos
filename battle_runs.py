"""T-582 Battle Run experiment model.

A Battle Run sends one brief through two or more competing role -> operator chains and keeps the exact
provenance of every step: role, requested operator, the operator it resolved to, model, runtime and the
operator status at planning time. Recorded step results add the operator/model/runtime that actually
produced the output. A battle never executes a provider, never creates a publishing item and never
publishes: `publish.automatic` is always false and any publication still goes through the normal human
approval gate. Judging (T-584) and routing (T-588) build on this record.

T-583 outcome attribution: after a human-approved publish, the owner links the published item to the completed
chain that produced it; the leaderboard compares chains using only real performance snapshots.
"""
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone

MIN_CHAINS = 2
MAX_CHAINS = 6
MAX_STEPS = 12
MAX_BRIEF = 4000
KINDS = ("content", "engineering")
PUBLISH_POLICY = {"automatic": False, "status": "not_published", "requires_human_approval": True}

SCHEMA = """
CREATE TABLE IF NOT EXISTS battle_runs(
  id TEXT PRIMARY KEY,
  idempotency_key TEXT UNIQUE,
  request_hash TEXT NOT NULL,
  status TEXT NOT NULL,
  created_by TEXT DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_battle_runs_created ON battle_runs(created_at);
CREATE TABLE IF NOT EXISTS battle_outcome_links(
  publish_id TEXT PRIMARY KEY,
  battle_id TEXT NOT NULL,
  chain_id TEXT NOT NULL,
  job_id TEXT DEFAULT '',
  platform TEXT DEFAULT '',
  linked_by TEXT DEFAULT '',
  linked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_battle_outcome_battle ON battle_outcome_links(battle_id, chain_id);
"""

# T-583 outcome metrics: (name, aggregation). Counts are summed and compared per measured item; rates are averaged
# over the items that report them. A metric no linked item reports stays unavailable (None), never zero.
OUTCOME_METRICS = (
    ("views", "sum"), ("reach", "sum"), ("likes", "sum"), ("comments", "sum"), ("shares", "sum"),
    ("saves", "sum"), ("conversions", "sum"), ("ctr_pct", "mean"), ("retention_pct", "mean"),
    ("completion_rate_pct", "mean"),
)
OUTCOME_AGGREGATION = dict(OUTCOME_METRICS)


class BattleError(ValueError):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha(value):
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _clean(value, limit):
    return " ".join(str(value or "").split()).strip()[:limit]


def _plan_step(index, spec, roles, operators):
    if not isinstance(spec, dict):
        raise BattleError(422, f"step {index} must be an object")
    role_id = str(spec.get("role") or "").strip().lower()
    op_id = str(spec.get("operator") or "").strip().lower()
    role = roles.get(role_id)
    if not role:
        raise BattleError(404, f"unknown role: {role_id or '-'}")
    if op_id not in operators:
        raise BattleError(422, f"unknown operator: {op_id or '-'}")
    if op_id not in role["operators"]:
        raise BattleError(409, f"operator {op_id} is not eligible for role {role_id}")
    # Auto resolves to what the unchanged pipeline really runs for this role today; no runtime stays unresolved.
    resolved = (role.get("runtime_operator") or None) if op_id == "auto" else op_id
    op = operators.get(resolved) if resolved else None
    return {
        "index": index,
        "role": role_id,
        "role_label": role.get("label", role_id),
        "workers": list(role.get("workers") or []),
        "operator": op_id,
        "eligible_operators": [o for o in role["operators"] if o != "auto"],
        "resolved_operator": resolved,
        "model": (op or {}).get("model") or None,
        "runtime": (op or {}).get("kind") or None,
        "operator_status": (op or {}).get("status") or "unresolved",
        "enforced": False,
        "status": "planned",
        "result": None,
    }


def plan_battle(body, role_board, battle_id):
    """Validate a battle request against the role/operator board and return the planned record."""
    if not isinstance(body, dict):
        raise BattleError(422, "battle body must be an object")
    brief = str(body.get("brief") or "").strip()
    if not brief:
        raise BattleError(422, "brief is required")
    if len(brief) > MAX_BRIEF:
        raise BattleError(422, f"brief exceeds {MAX_BRIEF} characters")
    kind = str(body.get("kind") or "content").strip().lower()
    if kind not in KINDS:
        raise BattleError(422, f"kind must be one of {', '.join(KINDS)}")
    chains_in = body.get("chains")
    if not isinstance(chains_in, list) or len(chains_in) < MIN_CHAINS:
        raise BattleError(422, f"a battle needs at least {MIN_CHAINS} competing chains")
    if len(chains_in) > MAX_CHAINS:
        raise BattleError(422, f"a battle allows at most {MAX_CHAINS} chains")
    roles = {r["id"]: r for r in role_board.get("roles") or []}
    operators = {o["id"]: o for o in role_board.get("operators") or []}
    brief_hash = _sha(brief)
    chains, signatures = [], set()
    for n, chain in enumerate(chains_in):
        steps_in = chain.get("steps") if isinstance(chain, dict) else None
        if not isinstance(steps_in, list) or not steps_in:
            raise BattleError(422, f"chain {n + 1} needs at least one step")
        if len(steps_in) > MAX_STEPS:
            raise BattleError(422, f"chain {n + 1} exceeds {MAX_STEPS} steps")
        steps = [_plan_step(i, s, roles, operators) for i, s in enumerate(steps_in)]
        signature = tuple((s["role"], s["operator"]) for s in steps)
        if signature in signatures:
            raise BattleError(409, f"chain {n + 1} duplicates another chain; competing chains must differ")
        signatures.add(signature)
        label = _clean(chain.get("label"), 80) or f"Chain {chr(65 + n)}"
        provenance = [{k: s[k] for k in ("role", "operator", "resolved_operator", "model", "runtime")} for s in steps]
        chains.append({
            "chain_id": f"{battle_id}.c{n + 1}",
            "label": label,
            "brief_hash": brief_hash,
            "chain_hash": _sha({"brief_hash": brief_hash, "steps": provenance}),
            "status": "planned",
            "steps": steps,
        })
    return {
        "battle_id": battle_id,
        "kind": kind,
        "brief": brief,
        "brief_hash": brief_hash,
        "ref": _clean(body.get("ref"), 120),
        "status": "planned",
        "chains": chains,
        "publish": dict(PUBLISH_POLICY),
        "routing_note": "Chains record intended operators; FactoryOS does not execute or reroute providers for a battle.",
    }


def _request_hash(body):
    return _sha({"kind": str(body.get("kind") or "content").strip().lower(),
                 "brief": str(body.get("brief") or "").strip(),
                 "ref": _clean(body.get("ref"), 120),
                 "chains": [[(str(s.get("role") or "").strip().lower(), str(s.get("operator") or "").strip().lower())
                             for s in (c.get("steps") or []) if isinstance(s, dict)]
                            for c in (body.get("chains") or []) if isinstance(c, dict)]})


def _refresh_status(battle):
    for chain in battle["chains"]:
        done = [s["status"] == "completed" for s in chain["steps"]]
        chain["status"] = "completed" if all(done) else ("running" if any(done) else "planned")
    states = {c["status"] for c in battle["chains"]}
    battle["status"] = "completed" if states == {"completed"} else ("planned" if states == {"planned"} else "running")
    # The publish policy is re-asserted on every write so no stored edit can turn on automatic publishing.
    battle["publish"] = dict(PUBLISH_POLICY)


class BattleStore:
    def __init__(self, connect):
        self._connect = connect

    def ensure_schema(self):
        con = self._connect()
        try:
            con.executescript(SCHEMA)
            con.commit()
        finally:
            con.close()

    def create(self, body, role_board, created_by=""):
        if not isinstance(body, dict):
            raise BattleError(422, "battle body must be an object")
        key = _clean(body.get("idempotency_key"), 120) or None
        request_hash = _request_hash(body)
        battle_id = "battle_" + (_sha("battle|" + key)[:16] if key else uuid.uuid4().hex[:16])
        con = self._connect()
        try:
            if key:
                row = con.execute("SELECT request_hash,payload_json FROM battle_runs WHERE idempotency_key=?", (key,)).fetchone()
                if row:
                    if row["request_hash"] != request_hash:
                        raise BattleError(409, "idempotency_key already used for a different battle")
                    return json.loads(row["payload_json"]), False
            battle = plan_battle(body, role_board, battle_id)
            now = _now()
            battle.update({"idempotency_key": key, "created_by": created_by, "created_at": now, "updated_at": now})
            try:
                con.execute("INSERT INTO battle_runs(id,idempotency_key,request_hash,status,created_by,created_at,updated_at,payload_json)"
                            " VALUES(?,?,?,?,?,?,?,?)",
                            (battle_id, key, request_hash, battle["status"], created_by, now, now, json.dumps(battle, ensure_ascii=False)))
                con.commit()
            except sqlite3.IntegrityError:
                row = con.execute("SELECT request_hash,payload_json FROM battle_runs WHERE idempotency_key=?", (key,)).fetchone()
                if row and row["request_hash"] == request_hash:
                    return json.loads(row["payload_json"]), False
                raise BattleError(409, "idempotency_key already used for a different battle")
            return battle, True
        finally:
            con.close()

    def get(self, battle_id):
        con = self._connect()
        try:
            row = con.execute("SELECT payload_json FROM battle_runs WHERE id=?", (str(battle_id or ""),)).fetchone()
        finally:
            con.close()
        if not row:
            raise BattleError(404, "battle not found")
        return json.loads(row["payload_json"])

    def list(self, limit=50):
        con = self._connect()
        try:
            rows = con.execute("SELECT payload_json FROM battle_runs ORDER BY created_at DESC, id DESC LIMIT ?",
                               (max(1, min(200, int(limit))),)).fetchall()
        finally:
            con.close()
        out = []
        for row in rows:
            b = json.loads(row["payload_json"])
            out.append({k: b.get(k) for k in ("battle_id", "kind", "ref", "brief_hash", "status", "created_at", "updated_at", "publish")}
                       | {"brief": b.get("brief", "")[:200],
                          "chains": [{"chain_id": c["chain_id"], "label": c["label"], "status": c["status"],
                                      "steps": [f"{s['role']}→{s['operator']}" for s in c["steps"]]} for c in b["chains"]]})
        return out

    def record_step_result(self, battle_id, body, recorded_by=""):
        """Attach the actual producer of one step's output. Completed steps are immutable; steps run in order."""
        if not isinstance(body, dict):
            raise BattleError(422, "result body must be an object")
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT payload_json FROM battle_runs WHERE id=?", (str(battle_id or ""),)).fetchone()
            if not row:
                raise BattleError(404, "battle not found")
            battle = json.loads(row["payload_json"])
            chain = next((c for c in battle["chains"] if c["chain_id"] == body.get("chain_id")), None)
            if not chain:
                raise BattleError(404, "chain not found")
            try:
                index = int(body.get("step"))
            except (TypeError, ValueError):
                raise BattleError(422, "step must be an integer index")
            if not 0 <= index < len(chain["steps"]):
                raise BattleError(404, "step not found")
            step = chain["steps"][index]
            if step["status"] == "completed":
                raise BattleError(409, "step already has a recorded result")
            if any(s["status"] != "completed" for s in chain["steps"][:index]):
                raise BattleError(409, "earlier steps of this chain have no result yet")
            operator = str(body.get("operator") or "").strip().lower()
            model = _clean(body.get("model"), 120)
            runtime = _clean(body.get("runtime"), 60)
            if not operator or not model or not runtime:
                raise BattleError(422, "operator, model and runtime of the actual producer are required")
            expected = step["resolved_operator"] or (step["operator"] if step["operator"] != "auto" else None)
            if operator == "auto":
                raise BattleError(422, "a result must name the concrete operator that produced it")
            if expected and operator != expected:
                raise BattleError(409, f"step was planned for {expected}, not {operator}")
            if operator not in step["eligible_operators"]:
                raise BattleError(409, f"operator {operator} is not eligible for role {step['role']}")
            output = str(body.get("output") or "")
            output_ref = _clean(body.get("output_ref"), 500)
            if not output.strip() and not output_ref:
                raise BattleError(422, "output or output_ref is required")
            step["result"] = {
                "operator": operator, "model": model, "runtime": runtime,
                "output_excerpt": output[:2000], "output_ref": output_ref,
                "output_hash": _sha(output) if output.strip() else None,
                "recorded_by": recorded_by, "recorded_at": _now(),
            }
            step["status"] = "completed"
            _refresh_status(battle)
            battle["updated_at"] = step["result"]["recorded_at"]
            con.execute("UPDATE battle_runs SET status=?,updated_at=?,payload_json=? WHERE id=?",
                        (battle["status"], battle["updated_at"], json.dumps(battle, ensure_ascii=False), battle["battle_id"]))
            con.commit()
            return battle
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def link_outcome(self, battle_id, body, publish_lookup, linked_by=""):
        """Attribute one already-published item to the completed chain that produced it.

        `publish_lookup(publish_id)` returns the visible publishing row (dict) or None. A publish item belongs to
        exactly one chain across all battles; links are immutable. Linking never publishes anything.
        """
        if not isinstance(body, dict):
            raise BattleError(422, "outcome body must be an object")
        battle = self.get(battle_id)
        chain = next((c for c in battle["chains"] if c["chain_id"] == body.get("chain_id")), None)
        if not chain:
            raise BattleError(404, "chain not found")
        if chain["status"] != "completed":
            raise BattleError(409, "only a completed chain can be credited with an outcome")
        publish_id = _clean(body.get("publish_id"), 120)
        if not publish_id:
            raise BattleError(422, "publish_id is required")
        pub = publish_lookup(publish_id)
        if not pub:
            raise BattleError(404, "published item not found")
        if pub.get("status") != "published":
            raise BattleError(409, "only a published item can be attributed; publishing stays behind human approval")
        con = self._connect()
        try:
            row = con.execute("SELECT * FROM battle_outcome_links WHERE publish_id=?", (publish_id,)).fetchone()
            if row:
                if row["battle_id"] == battle["battle_id"] and row["chain_id"] == chain["chain_id"]:
                    return dict(row), False
                raise BattleError(409, f"published item is already attributed to {row['chain_id']}")
            link = {"publish_id": publish_id, "battle_id": battle["battle_id"], "chain_id": chain["chain_id"],
                    "job_id": str(pub.get("job_id") or ""), "platform": str(pub.get("platform") or ""),
                    "linked_by": linked_by, "linked_at": _now()}
            try:
                con.execute("INSERT INTO battle_outcome_links(publish_id,battle_id,chain_id,job_id,platform,linked_by,linked_at)"
                            " VALUES(:publish_id,:battle_id,:chain_id,:job_id,:platform,:linked_by,:linked_at)", link)
                con.commit()
            except sqlite3.IntegrityError:
                raise BattleError(409, "published item is already attributed to a chain")
            return link, True
        finally:
            con.close()

    def outcome_links(self, battle_id):
        con = self._connect()
        try:
            rows = con.execute("SELECT * FROM battle_outcome_links WHERE battle_id=? ORDER BY linked_at, publish_id",
                               (str(battle_id or ""),)).fetchall()
        finally:
            con.close()
        return [dict(r) for r in rows]

    def leaderboard(self, battle_id, latest_snapshot, metric="views"):
        battle = self.get(battle_id)
        return build_leaderboard(battle, self.outcome_links(battle_id), latest_snapshot, metric)


def _number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _aggregate(metric, values, published):
    """values: numbers reported by the chain's measured items. Missing data stays None with an explicit status."""
    n = len(values)
    status = "unavailable" if n == 0 else ("available" if n == published else "partial")
    if not n:
        return {"value": None, "total": None, "items_reporting": 0, "status": status}
    if OUTCOME_AGGREGATION[metric] == "sum":
        total = sum(values)
        return {"value": round(total / n, 4), "total": total, "items_reporting": n, "status": status}
    return {"value": round(sum(values) / n, 4), "total": None, "items_reporting": n, "status": status}


def build_leaderboard(battle, links, latest_snapshot, metric="views"):
    """Rank a battle's chains by one factual metric using the latest real snapshot of each attributed publish.

    `latest_snapshot(publish_id)` returns {id, captured_at, source, platform, metrics} or None. Chains whose
    attributed items never reported the metric are listed unranked; nothing is imputed.
    """
    metric = str(metric or "views").strip().lower()
    if metric not in OUTCOME_AGGREGATION:
        raise BattleError(422, f"metric must be one of {', '.join(OUTCOME_AGGREGATION)}")
    by_chain = {}
    for link in links:
        by_chain.setdefault(link["chain_id"], []).append(link)
    rows = []
    for chain in battle["chains"]:
        items = []
        for link in by_chain.get(chain["chain_id"], []):
            snap = latest_snapshot(link["publish_id"])
            reported = {k: _number((snap or {}).get("metrics", {}).get(k)) for k in OUTCOME_AGGREGATION}
            items.append({
                "publish_id": link["publish_id"], "job_id": link["job_id"], "platform": link["platform"],
                "linked_at": link["linked_at"],
                "snapshot": {k: snap.get(k) for k in ("id", "captured_at", "source")} if snap else None,
                "metrics": {k: v for k, v in reported.items() if v is not None},
            })
        measured = [i for i in items if i["snapshot"]]
        metrics = {m: _aggregate(m, [i["metrics"][m] for i in measured if m in i["metrics"]], len(measured))
                   for m in OUTCOME_AGGREGATION}
        rows.append({
            "chain_id": chain["chain_id"], "label": chain["label"], "chain_hash": chain["chain_hash"],
            "status": chain["status"],
            "provenance": [{"role": s["role"], "operator": s["operator"], "resolved_operator": s["resolved_operator"],
                            "produced_by": (s.get("result") or {}).get("operator"),
                            "model": (s.get("result") or {}).get("model") or s.get("model"),
                            "runtime": (s.get("result") or {}).get("runtime") or s.get("runtime")}
                           for s in chain["steps"]],
            "published_items": len(items), "measured_items": len(measured),
            "score": metrics[metric]["value"], "metrics": metrics, "items": items, "rank": None,
        })
    ranked = sorted((r for r in rows if r["score"] is not None), key=lambda r: (-r["score"], r["chain_id"]))
    previous, rank = None, 0
    for position, row in enumerate(ranked, start=1):
        if row["score"] != previous:
            rank, previous = position, row["score"]
        row["rank"] = rank
    unranked = [r for r in rows if r["score"] is None]
    return {
        "battle_id": battle["battle_id"], "metric": metric, "aggregation": OUTCOME_AGGREGATION[metric],
        "score_basis": "mean per measured item reporting the metric",
        "chains": ranked + unranked,
        "unranked_reason": "no attributed published item has reported this metric yet" if unranked else None,
        "measurement_note": "Only real platform snapshots count. Missing metrics stay unavailable (null), never zero or estimated.",
    }
