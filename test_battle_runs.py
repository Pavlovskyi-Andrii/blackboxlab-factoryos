"""T-582 Battle Run experiment model regression.

Deterministically creates competing role -> operator chains for one brief, proves every step keeps
role/operator/model/runtime provenance, that the battle ID is recorded and persisted, that results keep
the actual producer and cannot be rewritten, and that nothing is executed or published automatically.
"""
import asyncio
import json
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-battles-")
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


def as_identity(identity):
    app.request_identity = lambda _r: identity


def run(coro_or_value):
    return asyncio.run(coro_or_value) if asyncio.iscoroutine(coro_or_value) else coro_or_value


def refused(fn, code):
    try:
        run(fn())
    except HTTPException as exc:
        require(exc.status_code == code, f"expected {code}, got {exc.status_code}: {exc.detail}")
        return
    raise AssertionError(f"expected HTTP {code}")


def create(body):
    return run(app.battle_create(request(body)))


def record(battle_id, body):
    return run(app.battle_record_result(battle_id, request(body)))["battle"]


# Any outbound HTTP during a battle would mean a provider call or a publish: fail loudly.
def no_network(*_a, **_k):
    raise AssertionError("battle must not make outbound calls")


app.urlrequest.urlopen = no_network

# Real operator readiness mix: ChatGPT key configured, Gemini key unverified, Claude runner live.
app.FACTORY_LLM_API_KEY = "sk-secret-llm"
app.FACTORY_GEMINI_API_KEY = "gem-secret"
app.claude_worker_runtime.update({"last_seen": app.time.time(), "node": {"auth_mode": "subscription"}})
as_identity(OWNER)

con = app.db()
publish_before = con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0]
jobs_before = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
con.close()
assignments_before = app.factory_roles(request())["assignments"]

BRIEF = "Explain why small on-device models matter for privacy in 60 seconds."
content_body = {
    "kind": "content",
    "brief": BRIEF,
    "ref": "job-demo",
    "chains": [
        {"label": "ChatGPT writes", "steps": [{"role": "scout", "operator": "chatgpt"},
                                               {"role": "scriptwriter", "operator": "claude"},
                                               {"role": "reviewer", "operator": "gemini"}]},
        {"label": "Gemini writes", "steps": [{"role": "scout", "operator": "auto"},
                                              {"role": "scriptwriter", "operator": "gemini"},
                                              {"role": "reviewer", "operator": "claude"}]},
    ],
}
out = create(content_body)
battle = out["battle"]
require(out["created"] is True, "battle created")
bid = battle["battle_id"]
require(bid.startswith("battle_") and len(bid) == len("battle_") + 16, "battle ID recorded")
require(battle["status"] == "planned" and len(battle["chains"]) == 2, "two competing chains planned")
a, b = battle["chains"]
require(a["chain_id"] == f"{bid}.c1" and b["chain_id"] == f"{bid}.c2", "chain IDs scoped to battle")
require(a["brief_hash"] == b["brief_hash"] == battle["brief_hash"], "same brief for every chain")
require(a["chain_hash"] != b["chain_hash"], "chains are distinct")

# per-step provenance: role, requested operator, resolved operator, model, runtime, status snapshot
s = a["steps"]
require([x["role"] for x in s] == ["scout", "scriptwriter", "reviewer"], "chain A roles")
require([x["operator"] for x in s] == ["chatgpt", "claude", "gemini"], "chain A operators")
require(s[0]["model"] == app.FACTORY_LLM_MODEL and s[0]["runtime"] == "api" and s[0]["operator_status"] == "configured", "chatgpt provenance")
require(s[1]["resolved_operator"] == "claude" and s[1]["runtime"] == "runner" and s[1]["model"] is None
        and s[1]["operator_status"] == "online", "claude provenance (model unknown stays null)")
require(s[2]["model"] == app.FACTORY_GEMINI_VIDEO_MODEL and s[2]["operator_status"] == "configured_unverified", "gemini provenance")
require("Scriptwriter" in s[1]["workers"] and s[1]["role_label"] == "Scriptwriter", "canonical workers kept")
auto = b["steps"][0]
require(auto["operator"] == "auto" and auto["resolved_operator"] == "chatgpt" and auto["model"] == app.FACTORY_LLM_MODEL,
        "auto resolves to the real pipeline runtime")
for chain in battle["chains"]:
    for step in chain["steps"]:
        require(step["enforced"] is False and step["status"] == "planned" and step["result"] is None, "planned, not executed")

# no automatic publishing, no new jobs, role assignments untouched
require(battle["publish"] == {"automatic": False, "status": "not_published", "requires_human_approval": True}, "publish policy")
con = app.db()
require(con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0] == publish_before, "no publishing item")
require(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before, "no job created")
con.close()
require(app.factory_roles(request())["assignments"] == assignments_before, "battle does not change role assignments")
blob = json.dumps(battle)
require("sk-secret-llm" not in blob and "gem-secret" not in blob, "secret leaked")

# persisted and readable through the API and a fresh store
require(run(app.battle_get(bid, request()))["battle"] == battle, "battle persisted")
require(battle_runs.BattleStore(app.db).get(bid) == battle, "fresh store reads same battle")
listed = run(app.battle_list(request()))["battles"]
require(listed[0]["battle_id"] == bid and listed[0]["chains"][1]["steps"][0] == "scout→auto", "battle listed")

# engineering battle: Auto has no pipeline runtime and stays unresolved instead of guessing
eng = create({"kind": "engineering", "brief": "Implement T-999 fixture", "ref": "T-999", "idempotency_key": "eng-1",
              "chains": [{"steps": [{"role": "engineer", "operator": "claude"}, {"role": "reviewer", "operator": "chatgpt"}]},
                         {"steps": [{"role": "engineer", "operator": "gemini"}, {"role": "reviewer", "operator": "claude"}]},
                         {"steps": [{"role": "engineer", "operator": "auto"}]}]})
require(eng["created"] and len(eng["battle"]["chains"]) == 3, "three-chain engineering battle")
eng_auto = eng["battle"]["chains"][2]["steps"][0]
require(eng_auto["resolved_operator"] is None and eng_auto["model"] is None and eng_auto["operator_status"] == "unresolved", "auto unresolved")
require(eng["battle"]["chains"][0]["label"] == "Chain A", "default labels")

# idempotency fence: same key + same request returns the same battle; a different request is refused
again = create({**{k: v for k, v in eng["battle"].items() if k in ("kind", "brief", "ref")}, "idempotency_key": "eng-1",
                "chains": [{"steps": [{"role": "engineer", "operator": "claude"}, {"role": "reviewer", "operator": "chatgpt"}]},
                           {"steps": [{"role": "engineer", "operator": "gemini"}, {"role": "reviewer", "operator": "claude"}]},
                           {"steps": [{"role": "engineer", "operator": "auto"}]}]})
require(again["created"] is False and again["battle"]["battle_id"] == eng["battle"]["battle_id"], "idempotent replay")
require(eng["battle"]["battle_id"] == "battle_" + battle_runs._sha("battle|eng-1")[:16], "deterministic keyed ID")
refused(lambda: app.battle_create(request({**content_body, "idempotency_key": "eng-1"})), 409)

# validation
con = app.db()
count_before = con.execute("SELECT COUNT(*) FROM battle_runs").fetchone()[0]
con.close()

refused(lambda: app.battle_create(request({**content_body, "chains": content_body["chains"][:1]})), 422)
refused(lambda: app.battle_create(request({**content_body, "chains": [content_body["chains"][0]] * 2})), 409)
refused(lambda: app.battle_create(request({**content_body, "brief": ""})), 422)
refused(lambda: app.battle_create(request({**content_body, "brief": " "})), 422)
refused(lambda: app.battle_create(request({**content_body, "brief": "x" * (battle_runs.MAX_BRIEF + 1)})), 422)
refused(lambda: app.battle_create(request({**content_body, "kind": "ads"})), 422)
bad = lambda step: {**content_body, "chains": [content_body["chains"][0], {"steps": [step]}]}  # noqa: E731
refused(lambda: app.battle_create(request(bad({"role": "engineer", "operator": "chatgpt"}))), 409)
refused(lambda: app.battle_create(request(bad({"role": "nope", "operator": "claude"}))), 404)
refused(lambda: app.battle_create(request(bad({"role": "scout", "operator": "gpt"}))), 422)
refused(lambda: app.battle_create(request(bad({"role": "scout", "operator": "unknown_operator"}))), 422)
refused(lambda: app.battle_create(request(bad({"role": "scout", "operator": ""}))), 422)

con = app.db()
count_after = con.execute("SELECT COUNT(*) FROM battle_runs").fetchone()[0]
require(count_after == count_before, "invalid requests save nothing to database")
con.close()

# results keep the actual producer, run in order, match the plan and are immutable
c1, c2 = a["chain_id"], b["chain_id"]
result = lambda chain, step, op, **kw: {"chain_id": chain, "step": step, "operator": op, "model": kw.get("model", "m-1"),  # noqa: E731
                                         "runtime": kw.get("runtime", "api"), "output": kw.get("output", f"out {chain} {step}")}
refused(lambda: app.battle_record_result(bid, request(result(c1, 1, "claude"))), 409)  # step 0 first
refused(lambda: app.battle_record_result(bid, request(result(c1, 0, "gemini"))), 409)  # planned for chatgpt
refused(lambda: app.battle_record_result(bid, request(result(c2, 0, "auto"))), 422)    # must be concrete
refused(lambda: app.battle_record_result(bid, request({**result(c1, 0, "chatgpt"), "model": ""})), 422)
refused(lambda: app.battle_record_result(bid, request(result(f"{bid}.c9", 0, "chatgpt"))), 404)
refused(lambda: app.battle_record_result("battle_missing", request(result(c1, 0, "chatgpt"))), 404)
after = record(bid, result(c1, 0, "chatgpt", model=app.FACTORY_LLM_MODEL, output="trend list"))
step0 = after["chains"][0]["steps"][0]
require(step0["status"] == "completed" and step0["result"]["operator"] == "chatgpt"
        and step0["result"]["model"] == app.FACTORY_LLM_MODEL and step0["result"]["runtime"] == "api", "actual producer kept")
require(step0["result"]["output_hash"] == battle_runs._sha("trend list") and step0["result"]["recorded_by"] == "owner@example.com", "output fingerprint")
require(step0["role"] == "scout" and step0["operator"] == "chatgpt", "planned provenance untouched by result")
require(after["chains"][0]["status"] == "running" and after["status"] == "running", "battle running")
refused(lambda: app.battle_record_result(bid, request(result(c1, 0, "chatgpt", output="rewritten"))), 409)
record(bid, result(c1, 1, "claude", model="claude-opus-5-5", runtime="runner"))
record(bid, result(c1, 2, "gemini", model="gemini-x"))
record(bid, result(c2, 0, "chatgpt"))
record(bid, result(c2, 1, "gemini"))
done = record(bid, result(c2, 2, "claude", runtime="runner"))
require(done["status"] == "completed" and all(c["status"] == "completed" for c in done["chains"]), "battle completed")
require(done["publish"]["automatic"] is False and done["publish"]["status"] == "not_published", "completion does not publish")
con = app.db()
require(con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0] == publish_before, "still no publishing item")
con.close()
ebid = eng["battle"]["battle_id"]
ec3 = eng["battle"]["chains"][2]["chain_id"]
refused(lambda: app.battle_record_result(ebid, request(result(ec3, 0, "chatgpt"))), 409)  # not eligible for engineer
require(record(ebid, result(ec3, 0, "claude", runtime="runner"))["chains"][2]["status"] == "completed", "unresolved auto records real operator")

# owner-only operator surface: viewers refused, workspace members are not routed here
as_identity(VIEWER)
refused(lambda: app.battle_list(request()), 403)
refused(lambda: app.battle_create(request(content_body)), 403)
refused(lambda: app.battle_get(bid, request()), 403)
refused(lambda: app.battle_record_result(bid, request(result(c1, 0, "chatgpt"))), 403)
require(not workspace_tenancy.member_route_allowed("GET", "/api/battles"), "members cannot list battles")
require(not workspace_tenancy.member_route_allowed("POST", "/api/battles"), "members cannot create battles")
print("T-582 battle run regression passed")
