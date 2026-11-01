"""T-583 Outcome attribution + leaderboard regression.

Analytics fixtures: three completed Battle Run chains, four human-approved published items and real
performance snapshots with deliberately missing metrics. Proves the leaderboard attributes metrics to the
exact role/operator chain, ranks only on factual data, keeps missing platform metrics unavailable (null,
never zero) and that attribution neither publishes nor calls out.
"""
import asyncio
import json
import os
import tempfile
import uuid

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-battle-outcomes-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

import app  # noqa: E402
import battle_runs  # noqa: E402
import workspace_tenancy  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

OWNER = {"role": "owner", "email": "owner@example.com"}
VIEWER = {"role": "viewer"}


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def request(body=None):
    raw = json.dumps(body if body is not None else {}).encode("utf-8")

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "headers": [(b"content-type", b"application/json")], "method": "POST", "path": "/"}, receive)


def run(coro_or_value):
    return asyncio.run(coro_or_value) if asyncio.iscoroutine(coro_or_value) else coro_or_value


def refused(fn, code):
    try:
        run(fn())
    except HTTPException as exc:
        require(exc.status_code == code, f"expected {code}, got {exc.status_code}: {exc.detail}")
        return
    raise AssertionError(f"expected HTTP {code}")


def no_network(*_a, **_k):
    raise AssertionError("outcome attribution must not make outbound calls")


app.urlrequest.urlopen = no_network
app.FACTORY_LLM_API_KEY = "sk-secret-llm"
app.FACTORY_GEMINI_API_KEY = "gem-secret"
app.request_identity = lambda _r: OWNER

# --- a completed three-chain battle
battle = run(app.battle_create(request({
    "kind": "content", "brief": "60s explainer: why on-device models protect privacy", "idempotency_key": "t583",
    "chains": [
        {"label": "ChatGPT writes", "steps": [{"role": "scriptwriter", "operator": "chatgpt"}, {"role": "reviewer", "operator": "claude"}]},
        {"label": "Claude writes", "steps": [{"role": "scriptwriter", "operator": "claude"}, {"role": "reviewer", "operator": "gemini"}]},
        {"label": "Gemini writes", "steps": [{"role": "scriptwriter", "operator": "gemini"}, {"role": "reviewer", "operator": "chatgpt"}]},
    ]})))["battle"]
bid = battle["battle_id"]
c1, c2, c3 = (c["chain_id"] for c in battle["chains"])


def finish(chain_id, ops):
    for i, (op, runtime) in enumerate(ops):
        run(app.battle_record_result(bid, request({"chain_id": chain_id, "step": i, "operator": op, "model": f"{op}-model",
                                                   "runtime": runtime, "output": f"{chain_id} step {i}"})))


# --- human-approved published items (fixture rows, as the publishing gate would leave them)
job = run(app.create_job(app.JobCreate(title="T-583 fixture", brief="outcomes")))["id"]


def published(status="published"):
    pid = str(uuid.uuid4())
    now = app.ts()
    con = app.db()
    con.execute("""INSERT INTO publishing_queue(id,job_id,package_id,status,target,platform,scheduled_at,idempotency_key,
                   attempt_count,external_post_id,created_at,updated_at,published_at,meta_json) VALUES(?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
                (pid, job, "pkg-" + pid[:8], status, "manual", "youtube_shorts", now, "idem-" + pid,
                 "ext-" + pid[:8] if status == "published" else None, now, now, now if status == "published" else None, "{}"))
    con.commit()
    con.close()
    return pid


def snapshot(pid, captured_at, **metrics):
    run(app.add_performance_snapshot(app.PerformanceSnapshotCreate(publish_id=pid, captured_at=captured_at, source="fixture", **metrics)))


p1, p2, p3, p4 = (published() for _ in range(4))
scheduled = published("scheduled")


def link(chain_id, pid):
    return run(app.battle_link_outcome(bid, request({"chain_id": chain_id, "publish_id": pid})))


# a chain without recorded results cannot be credited
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c1, "publish_id": p1})), 409)
finish(c1, [("chatgpt", "api"), ("claude", "runner")])
finish(c2, [("claude", "runner"), ("gemini", "api")])
finish(c3, [("gemini", "api"), ("chatgpt", "api")])

con = app.db()
publish_before = con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0]
con.close()

first = link(c1, p1)
require(first["created"] is True and first["link"]["chain_id"] == c1 and first["link"]["job_id"] == job, "p1 credited to chain A")
link(c1, p2)
link(c2, p3)
link(c3, p4)
require(link(c1, p1)["created"] is False, "relinking the same item to the same chain is idempotent")
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c2, "publish_id": p1})), 409)        # one item, one chain
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c2, "publish_id": scheduled})), 409)  # not published
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c2, "publish_id": "missing"})), 404)
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c2, "publish_id": ""})), 422)
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": f"{bid}.c9", "publish_id": p1})), 404)
refused(lambda: app.battle_link_outcome("battle_missing", request({"chain_id": c1, "publish_id": p1})), 404)

# --- analytics fixtures: p1 has an older and a newer snapshot; p2 lacks comments/shares; p4 has no snapshot at all
snapshot(p1, "2026-10-01T00:00:00+00:00", views=200, likes=4)
snapshot(p1, "2026-10-03T00:00:00+00:00", views=1000, likes=50, comments=5, shares=3)
snapshot(p2, "2026-10-03T00:00:00+00:00", views=3000, likes=150, ctr_pct=4.0)
snapshot(p3, "2026-10-03T00:00:00+00:00", views=1500, likes=120, comments=30, shares=10, saves=7, ctr_pct=6.5, conversions=4)


def board(metric="views"):
    return run(app.battle_leaderboard(bid, request(), metric))


views = board()
require(views["battle_id"] == bid and views["metric"] == "views" and views["aggregation"] == "sum", "views leaderboard")
rows = {r["chain_id"]: r for r in views["chains"]}
require([r["chain_id"] for r in views["chains"]] == [c1, c2, c3], "ranked chains first, unranked last")
a, b, c = rows[c1], rows[c2], rows[c3]
require(a["rank"] == 1 and a["score"] == 2000 and a["metrics"]["views"]["total"] == 4000, "chain A: latest snapshots only, per-item mean")
require(a["metrics"]["views"]["items_reporting"] == 2 and a["metrics"]["views"]["status"] == "available", "chain A coverage")
require(b["rank"] == 2 and b["score"] == 1500, "chain B second")
require(c["rank"] is None and c["score"] is None and c["published_items"] == 1 and c["measured_items"] == 0, "unmeasured chain unranked")
require(c["items"][0]["snapshot"] is None and c["items"][0]["metrics"] == {}, "no snapshot -> no metrics")
require(all(m["value"] is None and m["status"] == "unavailable" for m in c["metrics"].values()), "chain C metrics unavailable, not zero")
require(views["unranked_reason"], "unranked chains are explained")

# missing platform metrics stay unavailable / partial, never zero
require(a["metrics"]["saves"] == {"value": None, "total": None, "items_reporting": 0, "status": "unavailable"}, "saves not fabricated")
require(a["metrics"]["conversions"]["value"] is None and a["metrics"]["conversions"]["status"] == "unavailable", "conversions not fabricated")
require(a["metrics"]["comments"] == {"value": 5, "total": 5, "items_reporting": 1, "status": "partial"}, "comments partial for A")
require(a["metrics"]["ctr_pct"]["value"] == 4.0 and a["metrics"]["ctr_pct"]["status"] == "partial", "CTR only where reported")
require("comments" not in next(i for i in a["items"] if i["publish_id"] == p2)["metrics"], "absent item metric not filled in")
require(b["metrics"]["conversions"] == {"value": 4, "total": 4, "items_reporting": 1, "status": "available"}, "conversions when available")
p1_item = next(i for i in a["items"] if i["publish_id"] == p1)
require(p1_item["snapshot"]["captured_at"].startswith("2026-10-03") and p1_item["snapshot"]["source"] == "fixture"
        and p1_item["metrics"]["views"] == 1000, "latest real snapshot is the evidence")

# exact role/operator chain provenance including the actual producers
require([(s["role"], s["operator"], s["produced_by"], s["runtime"]) for s in a["provenance"]]
        == [("scriptwriter", "chatgpt", "chatgpt", "api"), ("reviewer", "claude", "claude", "runner")], "chain A provenance")
require(a["provenance"][1]["model"] == "claude-model" and a["chain_hash"] == battle["chains"][0]["chain_hash"], "producer model + chain hash")

# other metrics re-rank; chains without the metric stay unranked
comments = board("comments")
require([(r["chain_id"], r["rank"]) for r in comments["chains"]] == [(c2, 1), (c1, 2), (c3, None)], "comments leaderboard")
conv = board("conversions")
require([(r["chain_id"], r["rank"]) for r in conv["chains"]] == [(c2, 1), (c1, None), (c3, None)], "conversions leaderboard")
saves = board("saves")
require(saves["chains"][0]["chain_id"] == c2 and saves["chains"][0]["score"] == 7, "saves leaderboard")
require(all(r["score"] is None for r in saves["chains"][1:]), "saves missing elsewhere stays null")
ctr = board("ctr_pct")
require(ctr["aggregation"] == "mean" and [r["score"] for r in ctr["chains"]] == [6.5, 4.0, None], "CTR leaderboard")
refused(lambda: app.battle_leaderboard(bid, request(), "revenue"), 422)
refused(lambda: app.battle_leaderboard("battle_missing", request(), "views"), 404)

# ties share a rank
tie = battle_runs.build_leaderboard(
    {"battle_id": "battle_tie", "chains": [dict(battle["chains"][0], chain_id="x.c1"), dict(battle["chains"][1], chain_id="x.c2")]},
    [{"publish_id": "a", "chain_id": "x.c1", "job_id": "", "platform": "", "linked_at": "t"},
     {"publish_id": "b", "chain_id": "x.c2", "job_id": "", "platform": "", "linked_at": "t"}],
    lambda pid: {"id": pid, "captured_at": "t", "source": "fixture", "metrics": {"views": 10, "likes": True}}, "views")
require([r["rank"] for r in tie["chains"]] == [1, 1], "ties share a rank")
require(tie["chains"][0]["metrics"]["likes"]["status"] == "unavailable", "non-numeric metric is not counted")

# attribution never publishes, never changes the battle publish policy, never leaks secrets
con = app.db()
require(con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0] == publish_before, "no publishing item created")
require(con.execute("SELECT status FROM publishing_queue WHERE id=?", (scheduled,)).fetchone()[0] == "scheduled", "scheduled item untouched")
require(con.execute("SELECT COUNT(*) FROM battle_outcome_links").fetchone()[0] == 4, "four attribution links")
con.close()
require(run(app.battle_get(bid, request()))["battle"]["publish"]["automatic"] is False, "battle never auto-publishes")
blob = json.dumps(views) + json.dumps(comments)
require("sk-secret-llm" not in blob and "gem-secret" not in blob, "secret leaked")
require(battle_runs.BattleStore(app.db).leaderboard(bid, app._battle_latest_snapshot)["chains"][0]["chain_id"] == c1, "fresh store")

# owner-only operator surface
app.request_identity = lambda _r: VIEWER
refused(lambda: app.battle_leaderboard(bid, request(), "views"), 403)
refused(lambda: app.battle_link_outcome(bid, request({"chain_id": c2, "publish_id": p3})), 403)
require(not workspace_tenancy.member_route_allowed("GET", f"/api/battles/{bid}/leaderboard"), "members cannot read leaderboard")
require(not workspace_tenancy.member_route_allowed("POST", f"/api/battles/{bid}/outcomes"), "members cannot attribute")
print("T-583 outcome attribution + leaderboard regression passed")
