"""T-584 Reviewer / Judge mode regression.

Deterministically produces two candidate outputs from two competing chains, then records one review decision by a
separately assigned judge with explicit criteria, a selected candidate, rationale and provenance. Proves the judge
cannot silently rewrite candidates, cannot judge its own output, and that a decision never publishes anything.
"""
import asyncio
import json
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-battle-review-")
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
    raise AssertionError("a review must not make outbound calls")


app.urlrequest.urlopen = no_network
app.FACTORY_LLM_API_KEY = "sk-secret-llm"
app.FACTORY_GEMINI_API_KEY = "gem-secret"
app.claude_worker_runtime.update({"last_seen": app.time.time(), "node": {"auth_mode": "subscription"}})
app.request_identity = lambda _r: OWNER

# owner separately assigns ChatGPT to the Reviewer role
run(app.factory_role_assignment(app.RoleAssignmentRequest(role="reviewer", operator="chatgpt"), request()))

con = app.db()
publish_before = con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0]
jobs_before = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
con.close()

battle = run(app.battle_create(request({
    "kind": "content", "brief": "60-second explainer: why on-device models protect privacy.", "idempotency_key": "judge-1",
    "chains": [
        {"label": "Claude script", "steps": [{"role": "scout", "operator": "claude"}, {"role": "scriptwriter", "operator": "claude"}]},
        {"label": "Gemini script", "steps": [{"role": "scout", "operator": "gemini"}, {"role": "scriptwriter", "operator": "gemini"}]},
        {"label": "Unfinished", "steps": [{"role": "scout", "operator": "gemini"}, {"role": "scriptwriter", "operator": "claude"}]},
    ]})))["battle"]
bid = battle["battle_id"]
c1, c2, c3 = (c["chain_id"] for c in battle["chains"])


def result(chain, step, op, output, runtime):
    body = {"chain_id": chain, "step": step, "operator": op, "model": f"{op}-model", "runtime": runtime, "output": output}
    return run(app.battle_record_result(bid, request(body)))["battle"]


SCRIPT_A = "Hook: your phone already knows you. Keep it that way: on-device models never upload your words."
SCRIPT_B = "Hook: what if AI ran without the cloud? Local models answer offline and keep data on the device."
result(c1, 0, "claude", "trends A", "runner")
result(c1, 1, "claude", SCRIPT_A, "runner")
result(c2, 0, "gemini", "trends B", "api")
result(c2, 1, "gemini", SCRIPT_B, "api")
battle = result(c3, 0, "gemini", "trends C", "api")  # chain 3 stays incomplete

# two candidate outputs, each pinned by an evidence hash
listing = run(app.battle_reviews(bid, request()))
cands = {c["chain_id"]: c for c in listing["candidates"]}
require(set(cands) == {c1, c2} and listing["reviews"] == [], "two completed candidates, no review yet")
require(cands[c1]["output_hash"] == battle_runs._sha(SCRIPT_A) and cands[c1]["output_excerpt"] == SCRIPT_A, "candidate A output")
require(cands[c2]["output_hash"] == battle_runs._sha(SCRIPT_B) and cands[c2]["produced_by"] == "gemini", "candidate B output")
require([p["produced_by"] for p in cands[c1]["provenance"]] == ["claude", "claude"], "candidate provenance")
pins = [{"chain_id": c1, "evidence_hash": cands[c1]["evidence_hash"]}, {"chain_id": c2, "evidence_hash": cands[c2]["evidence_hash"]}]

CRITERIA = [{"id": "hook", "label": "Hook strength", "weight": 2},
            {"id": "accuracy", "label": "Factual accuracy", "weight": 3},
            {"id": "clarity", "label": "Clarity"}]
SCORES = [
    {"chain_id": c1, "criterion": "hook", "score": 8, "evidence": "Personal, direct second-person opener."},
    {"chain_id": c1, "criterion": "accuracy", "score": 9, "evidence": "Claim limited to not uploading input."},
    {"chain_id": c1, "criterion": "clarity", "score": 7, "evidence": "One idea per sentence."},
    {"chain_id": c2, "criterion": "hook", "score": 7, "evidence": "Question hook, less specific."},
    {"chain_id": c2, "criterion": "accuracy", "score": 6, "evidence": "'Answer offline' overstated for hybrid models."},
    {"chain_id": c2, "criterion": "clarity", "score": 8, "evidence": "Plain wording."},
]
JUDGE = {"operator": "chatgpt", "model": app.FACTORY_LLM_MODEL, "runtime": "api"}
review_body = {"judge": JUDGE, "candidates": pins, "criteria": CRITERIA, "scores": SCORES, "selected_chain_id": c1,
               "rationale": "Chain A is more accurate and has the stronger hook; B overstates offline capability."}


def review(body):
    return run(app.battle_record_review(bid, request(body)))


before = run(app.battle_get(bid, request()))["battle"]

# the judge cannot rewrite candidates, judge its own work, or judge stale/unfinished evidence
for key in ("output", "revised_output", "edits", "output_ref"):
    refused(lambda key=key: app.battle_record_review(bid, request({**review_body, key: "better script"})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "judge": {**JUDGE, "operator": "claude"}})), 409)
refused(lambda: app.battle_record_review(bid, request({**review_body, "judge": {**JUDGE, "operator": "gemini"}})), 409)
refused(lambda: app.battle_record_review(bid, request({**review_body, "judge": {**JUDGE, "operator": "auto"}})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "judge": {"operator": "chatgpt"}})), 422)
tampered = [{"chain_id": c1, "evidence_hash": battle_runs._sha("rewritten")}, pins[1]]
refused(lambda: app.battle_record_review(bid, request({**review_body, "candidates": tampered})), 409)
refused(lambda: app.battle_record_review(bid, request({**review_body, "candidates": [pins[0], {"chain_id": c3, "evidence_hash": "x"}]})), 409)
refused(lambda: app.battle_record_review(bid, request({**review_body, "candidates": pins[:1]})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "candidates": [pins[0], pins[0]]})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "candidates": [pins[0], {"chain_id": "nope", "evidence_hash": "x"}]})), 404)
# explicit criteria, complete scores, a selected candidate and a rationale are mandatory
refused(lambda: app.battle_record_review(bid, request({**review_body, "criteria": []})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "scores": SCORES[:-1]})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "scores": SCORES[:-1] + [{**SCORES[-1], "score": 11}]})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "scores": SCORES + [{**SCORES[0], "criterion": "vibes"}]})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "selected_chain_id": c3})), 422)
refused(lambda: app.battle_record_review(bid, request({**review_body, "rationale": "  "})), 422)
refused(lambda: app.battle_record_review("battle_missing", request(review_body)), 404)

out = review(review_body)
r = out["review"]
require(out["created"] is True and r["review_id"] == f"{bid}.r.chatgpt", "review decision recorded")
require(r["judge"] == {"role": "reviewer", "operator": "chatgpt", "model": app.FACTORY_LLM_MODEL, "runtime": "api",
                       "independent": True, "assigned_reviewer_operator": "chatgpt"}, "judge provenance")
require([c["id"] for c in r["criteria"]] == ["hook", "accuracy", "clarity"] and r["criteria"][2]["weight"] == 1, "explicit criteria")
require(len(r["scores"]) == 6 and r["scores"][1]["evidence"].startswith("Claim limited"), "per-criterion evidence kept")
require(r["totals"] == {c1: round((8 * 2 + 9 * 3 + 7) / 6, 4), c2: round((7 * 2 + 6 * 3 + 8) / 6, 4)}, "weighted totals")
require(r["selected_chain_id"] == c1 and r["selection_matches_scores"] is True and r["rationale"].startswith("Chain A"), "selection")
require([c["evidence_hash"] for c in r["candidates"]] == [p["evidence_hash"] for p in pins], "candidate evidence preserved")
require(r["candidates"][0]["output_excerpt"] == SCRIPT_A and r["candidates"][1]["output_excerpt"] == SCRIPT_B, "outputs preserved verbatim")
require(r["candidates_modified"] is False and r["reviewed_by"] == "owner@example.com", "review metadata")
require(r["publish"] == {"automatic": False, "status": "not_published", "requires_human_approval": True}, "review never publishes")

# the battle and its candidates are untouched by the review
after = run(app.battle_get(bid, request()))["battle"]
require(after == before, "review did not change the battle record")
require(battle_runs.review_candidates(after) == listing["candidates"], "candidates unchanged after review")

# immutable and idempotent: identical replay returns the same review, a changed decision is refused
again = review(review_body)
require(again["created"] is False and again["review"] == r, "idempotent replay")
refused(lambda: app.battle_record_review(bid, request({**review_body, "selected_chain_id": c2})), 409)
listed = run(app.battle_reviews(bid, request()))["reviews"]
require(listed == [r] and battle_runs.BattleStore(app.db).reviews(bid) == [r], "review persisted")

# a decision against the scores is allowed but flagged, never hidden
app.factory_role_assignment(app.RoleAssignmentRequest(role="reviewer", operator="auto"), request())
other = battle_runs.plan_review(after, {**review_body, "selected_chain_id": c2}, app.get_role_operator_board())
require(other["selection_matches_scores"] is False and other["judge"]["assigned_reviewer_operator"] == "auto", "mismatch flagged")

# no publishing items, no jobs, no secrets
con = app.db()
require(con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0] == publish_before, "no publishing item")
require(con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before, "no job created")
con.close()
blob = json.dumps(listed)
require("sk-secret-llm" not in blob and "gem-secret" not in blob, "secret leaked")

# owner-only operator surface
app.request_identity = lambda _r: VIEWER
refused(lambda: app.battle_reviews(bid, request()), 403)
refused(lambda: app.battle_record_review(bid, request(review_body)), 403)
require(not workspace_tenancy.member_route_allowed("POST", f"/api/battles/{bid}/reviews"), "members cannot review battles")
print("T-584 reviewer / judge regression passed")
