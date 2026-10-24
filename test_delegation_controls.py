"""T-536-F Safe operator controls regression (server side).

Proves the owner -> FactoryOS -> Claude runner command channel is authenticated (owner session
to issue, worker token to read/ack), idempotent (request_id replay, repeated intents), auditable
(every accepted/rejected/no-op/ack lands in the audit log) and limited to pause / resume /
retry of a blocked or failed safe task: force-push, main checkout, deploy, publish, secrets,
HUMAN tasks and extra payload fields are all refused.
"""
import asyncio
import json
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-controls-")
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app  # noqa: E402
from pydantic import ValidationError  # noqa: E402
from starlette.requests import Request  # noqa: E402

ROADMAP = """## Fixture
- [x] T-960 Done task
- [ ] [HUMAN] T-961 Real publish approval
- [ ] T-962 Blocked safe task
- [ ] T-963 Failed safe task
- [ ] T-964 Queued safe task
- [ ] T-965 Running safe task
"""
OWNER = {"role": "owner", "email": "owner@example.com", "provider": "google"}
VIEWER = {"role": "viewer", "email": "viewer@example.com", "provider": "google"}
_ids = iter(range(10**6))


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def rid():
    return f"req-{next(_ids):08d}"


def request(path, *, method="GET", token=None):
    headers = [(b"authorization", f"Bearer {token}".encode())] if token is not None else []
    return Request({"type": "http", "method": method, "path": path, "headers": headers, "query_string": b""})


def expect_http(code, fn, *args, **kwargs):
    try:
        fn(*args, **kwargs)
    except app.HTTPException as exc:
        require(exc.status_code == code, f"expected HTTP {code}, got {exc.status_code}: {exc.detail}")
        return exc.detail
    raise AssertionError(f"expected HTTP {code}")


def owner_send(action, task_id="", request_id=None, identity=OWNER):
    real = app.request_identity
    app.request_identity = lambda _request: identity
    try:
        item = app.DelegationControlRequest(action=action, task_id=task_id, request_id=request_id or rid())
        return app.factory_delegation_control(item, request("/api/factory/delegation-control", method="POST"))
    finally:
        app.request_identity = real


def audit():
    return app._load_delegation_control()["audit"]


def worker_view():
    return app.claude_worker_control(request("/api/claude-worker/control", token=app.FACTORY_CLAUDE_WORKER_TOKEN))


def worker_ack(command_id, outcome, detail="", token=None):
    item = app.DelegationControlAck(command_id=command_id, outcome=outcome, detail=detail)
    return app.claude_worker_control_ack(item, request("/api/claude-worker/control/ack", method="POST",
                                                       token=app.FACTORY_CLAUDE_WORKER_TOKEN if token is None else token))


def middleware_status(path, *, method="GET", token=None):
    """Run the real auth middleware with a closed (password-protected) identity."""
    real = app.request_identity
    app.request_identity = lambda _request: None
    reached = []

    async def call_next(_request):
        reached.append(True)
        return app.JSONResponse({"ok": True})

    try:
        response = asyncio.run(app.auth_middleware(request(path, method=method, token=token), call_next))
    finally:
        app.request_identity = real
    return response.status_code, bool(reached)


def setup_fixture():
    tasks = app._parse_roadmap_tasks(ROADMAP)
    app._parse_roadmap_tasks = lambda text=None: [dict(x) for x in tasks]
    for task_id, result in (("T-962", "blocked"), ("T-963", "failed")):
        app.ingest_claude_worker_result(app.ClaudeWorkerTaskResult(
            task_id=task_id, pinned_task_id=task_id, result=result, branch="autopilot-ci", summary=result, commit="",
            commit_count=0, need="owner input" if result == "blocked" else "", exit_code=1, max_turns=80, timeout_seconds=3600))
    app.claude_worker_heartbeat(app.ClaudeWorkerHeartbeat(task_id="T-965", status="running", branch="autopilot-ci"))


def auth_checks():
    token = app.FACTORY_CLAUDE_WORKER_TOKEN
    expect_http(403, owner_send, "pause", identity=VIEWER)
    expect_http(403, owner_send, "pause", identity={})
    require(middleware_status("/api/factory/delegation-control", method="POST", token=token) == (401, False),
            "worker token must not authorize owner commands")
    require(middleware_status("/api/factory/delegation-control", method="POST") == (401, False), "anonymous command must be refused")
    require(middleware_status("/api/claude-worker/control", token=token) == (200, True), "worker token must reach the control feed")
    require(middleware_status("/api/claude-worker/control", token="wrong-token") == (401, False), "bad worker token must be refused")
    # Defence in depth: even an owner session (e.g. open mode) cannot read or ack as the runner.
    expect_http(401, app.claude_worker_control, request("/api/claude-worker/control"))
    expect_http(401, app.claude_worker_control, request("/api/claude-worker/control", token="wrong-token"))
    expect_http(401, worker_ack, "x", "applied", token="wrong-token")
    require(app._load_delegation_control()["commands"] == [], "refused requests must not queue commands")


def safety_checks():
    before = len(audit())
    for action in ("force_push", "push", "checkout_main", "switch_branch", "deploy", "deploy_production", "publish",
                   "approve_publish", "skip_approval", "set_env", "read_secret", "merge"):
        detail = expect_http(400, owner_send, action)
        require("unsupported action" in detail, f"{action} must be refused as unsupported")
    for field, value in (("branch", "main"), ("force", True), ("deploy", True), ("publish", True), ("skip_approval", True),
                         ("command", "git push --force origin main"), ("env", {"FACTORY_PASSWORD": ""})):
        try:
            app.DelegationControlRequest(action="retry", task_id="T-962", request_id=rid(), **{field: value})
        except ValidationError:
            continue
        raise AssertionError(f"extra command field {field} must be rejected")
    log = audit()[before:]
    require(len(log) == 12 and all(x["outcome"] == "rejected" for x in log), "every refused action must be audited")
    expect_http(409, owner_send, "retry", "T-961")   # HUMAN publish approval cannot be retried by the runner
    expect_http(409, owner_send, "retry", "T-960")   # done
    expect_http(409, owner_send, "retry", "T-964")   # queued, nothing to retry
    expect_http(409, owner_send, "retry", "T-965")   # running now
    expect_http(409, owner_send, "retry", "T-999")   # unknown
    expect_http(409, owner_send, "retry", "main")    # not a task id
    expect_http(409, owner_send, "pause", "T-962")   # pause/resume take no task
    expect_http(422, owner_send, "pause", request_id="x;rm -rf /")
    require(any(x["task_id"] == "T-961" and "HUMAN" in x["detail"] for x in audit()), "HUMAN retry refusal must be audited")
    require(app._load_delegation_control()["commands"] == [], "refused commands must never reach the runner")


def lifecycle_checks():
    board = app.get_delegation_board()
    ctl = board["controls"]
    require(ctl["mode"] == "running" and ctl["available"] == ["pause"] and ctl["retryable"] == ["T-962", "T-963"],
            f"initial control view: {ctl}")
    require(ctl["allowed_actions"] == ["pause", "resume", "retry"], "only the three safe actions may be advertised")

    # Pause is idempotent per request_id and per intent.
    first = owner_send("pause", request_id="pause-request-1")
    require(first["changed"] and first["paused"] and first["command"]["action"] == "pause", f"pause: {first}")
    replay = owner_send("pause", request_id="pause-request-1")
    require(replay["duplicate"] and replay["command"]["id"] == first["command"]["id"], "request_id replay must return the same command")
    again = owner_send("pause")
    require(not again["changed"] and not again["duplicate"], "second pause intent must be a no-op")
    expect_http(409, owner_send, "resume", request_id="pause-request-1")
    feed = worker_view()
    require(feed == {"paused": True, "commands": [{"id": first["command"]["id"], "action": "pause", "task_id": ""}]},
            f"worker feed must expose only id/action/task_id: {feed}")
    require(app.get_delegation_board()["controls"]["mode"] == "pause_requested", "pending pause shows as requested")

    acked = worker_ack(first["command"]["id"], "applied", "paused before the next task")
    require(acked["command"]["status"] == "applied" and not acked["duplicate"], "pause ack")
    require(worker_ack(first["command"]["id"], "rejected")["duplicate"], "acks must be idempotent and terminal")
    require(app._load_delegation_control()["commands"][0]["status"] == "applied", "a late ack must not rewrite the outcome")
    expect_http(404, worker_ack, "missing", "applied")
    expect_http(422, worker_ack, first["command"]["id"], "deployed")
    ctl = app.get_delegation_board()["controls"]
    require(ctl["mode"] == "paused" and ctl["available"] == ["resume"] and worker_view()["commands"] == [], f"paused view: {ctl}")

    # Retry: one pending command per task, idempotent.
    retry = owner_send("retry", "T-962")
    require(retry["changed"] and retry["command"]["task_id"] == "T-962", "retry accepted for a blocked safe task")
    require(not owner_send("retry", "T-962")["changed"], "duplicate retry intent must not queue twice")
    require(app.get_delegation_board()["controls"]["retryable"] == ["T-963"], "pending retry is no longer offered")
    retry_failed = owner_send("retry", "T-963")
    worker_ack(retry_failed["command"]["id"], "rejected", "runner is not holding T-963 as blocked/failed")

    # Resume supersedes a pause the runner has not seen yet.
    resumed = owner_send("resume")
    pause2 = owner_send("pause")
    resume2 = owner_send("resume")
    state = app._load_delegation_control()
    by_id = {x["id"]: x for x in state["commands"]}
    require(not state["paused"] and by_id[pause2["command"]["id"]]["status"] == "superseded", "resume must supersede a pending pause")
    require(by_id[resumed["command"]["id"]]["status"] == "superseded", "pause must supersede a pending resume")
    require(resumed["changed"] and resume2["changed"], "resume after pause must change state")
    feed = worker_view()
    require([c["action"] for c in feed["commands"]] == ["retry", "resume"] and feed["paused"] is False, f"feed order: {feed}")

    outcomes = [x["outcome"] for x in audit()]
    for outcome in ("accepted", "noop", "applied", "rejected", "superseded"):
        require(outcome in outcomes, f"audit log must record {outcome}")
    require(all({"at", "actor", "action", "outcome"} <= set(x) for x in audit()), "audit entries must be complete")
    require(any(x["actor"] == "owner:owner@example.com" for x in audit()) and any(x["actor"] == "worker" for x in audit()),
            "audit must attribute owner and runner actions")

    stored = app.DELEGATION_CONTROL_FILE.read_text(encoding="utf-8")
    board_json = json.dumps(app.get_delegation_board())
    for text in (stored, board_json, json.dumps(worker_view())):
        require(app.FACTORY_CLAUDE_WORKER_TOKEN not in text and app.FACTORY_SECRET not in text, "control channel must be secret-free")
    safety = app.get_delegation_board()["safety"]
    require(safety["main_push_forbidden"] and safety["production_direct_deploy_forbidden"] and safety["human_publish_approval_required"],
            "board safety invariants must stay asserted")


def route_checks():
    routes = {(getattr(r, "path", ""), m) for r in app.app.routes for m in (getattr(r, "methods", None) or ())}
    for path, method in (("/api/factory/delegation-control", "POST"), ("/api/claude-worker/control", "GET"),
                         ("/api/claude-worker/control/ack", "POST")):
        require((path, method) in routes, f"route missing: {method} {path}")
    require(not any("deploy" in p or "force" in p for p, _ in routes if p.startswith(("/api/claude-worker/", "/api/factory/delegation"))),
            "no deploy/force route may exist on the delegation channel")


def main():
    setup_fixture()
    route_checks()
    auth_checks()
    safety_checks()
    lifecycle_checks()
    print("Delegation safe operator controls regression passed (auth, idempotency, audit, safety invariants)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
