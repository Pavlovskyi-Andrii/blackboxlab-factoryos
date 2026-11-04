"""T-585 Multi-operator delegation board regression.

The delegation board API returns Claude / Gemini / ChatGPT operator lanes (open ticket, stage, branch/runtime,
heartbeat, last result, queue depth) built only from observed heartbeats, verified results and Relay runs.
An operator that never reported is explicitly `unconfigured`, never idle/online; secrets are never returned.
"""
import json
import os
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-operator-lanes-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

import app  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from operator_lanes import build_operator_lanes  # noqa: E402

NOW = 1793000000.0
SECRET = "sk-lane-fixture-SECRET-value"


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def by_id(lanes):
    require([x["operator_id"] for x in lanes] == ["claude", "gemini", "chatgpt"], f"lane order: {[x['operator_id'] for x in lanes]}")
    return {x["operator_id"]: x for x in lanes}


def pure_checks():
    # Nothing ever reported: every lane is explicitly unconfigured and nothing is invented.
    empty = by_id(build_operator_lanes(now=NOW, provider_status={"gemini": "auth_pending"}))
    for op, lane in empty.items():
        require(lane["availability"] == "unconfigured" and lane["configured"] is False, f"{op} must be unconfigured")
        require(lane["open_ticket"] is None and lane["last_result"] is None and lane["queue_depth"] is None,
                f"{op} must not invent ticket/result/queue depth")
        require(lane["heartbeat"]["age_seconds"] is None and lane["branch"] == "" and lane["runtime"] == "", f"{op} invented heartbeat/branch")
    require(empty["gemini"]["reason"] == "never_reported" and empty["chatgpt"]["reason"] == "no_runner", "unconfigured reasons")
    require(empty["gemini"]["provider_status"] == "auth_pending" and empty["claude"]["provider_status"] == "unknown", "provider status")

    claude_worker = {"online": True, "connection": "online", "heartbeat_age_seconds": 6.0, "last_seen": NOW - 6,
                     "active_task_id": "T-585", "last_error": "",
                     "node": {"branch": "autopilot/aws-worker", "node_id": "ec2", "worker_token": SECRET},
                     "telemetry": {"stage": "running", "head_sha": "03a88cd2d214", "queue_depth": 3, "branch": "autopilot/aws-worker"}}
    results = [{"task_id": "T-583", "result": "done", "commit": "9da8c43abcdef", "summary": "older", "received_at": NOW - 7200},
               {"task_id": "T-584", "result": "done", "commit": "03a88cd2d214f5", "summary": "judge mode", "received_at": NOW - 600}]
    runners = {"claude": {"last_seen": 0.0},
               "gemini": {"last_seen": NOW - 200, "branch": "gemini/t-589", "runtime": "antigravity", "status": "working",
                          "task_id": "T-589", "stage": "coding", "queue_depth": 0, "node_id": "gem-1", "last_result": "tests green",
                          "tickets": [{"id": "T-589", "title": "Engineering battle", "token": SECRET, "env": {"K": SECRET}}]}}
    lane_board = {"lanes": {
        "claude": {"state": "idle", "remaining": 4, "assigned_not_claimed": ["T-586"]},
        "gemini": {"state": "blocked", "task_id": "T-589", "last_task_id": "T-589", "stage": "blocked", "run_id": "r1",
                   "last_event": {"action": "blocked", "at": "2026-10-26T09:00:00Z"}, "reason": "needs review", "remaining": 1},
        "chatgpt": {"state": "working", "task_id": "T-600", "last_task_id": "T-600", "stage": "running", "run_id": "r2",
                    "last_event": {"action": "running", "at": "2026-10-26T09:10:00Z"}, "remaining": 0}},
        "tasks": [{"id": "T-589", "title": "Engineering battle pilot", "lane": "gemini", "done": False, "column": "blocked", "stage": "blocked"},
                  {"id": "T-600", "title": "Planner relay", "lane": "chatgpt", "done": False, "column": "in_progress", "stage": "running"},
                  {"id": "T-100", "title": "Old", "lane": "gemini", "done": True, "column": "done", "stage": "done"}]}
    lanes = by_id(build_operator_lanes(runners=runners, runner_ttl=45, claude_worker=claude_worker, claude_results=results,
                                       lane_board=lane_board, task_titles={"T-585": "Multi-operator delegation board"},
                                       provider_status={"claude": "online", "gemini": "auth_pending", "chatgpt": "auth_pending"},
                                       assigned_roles={"gemini": ["engineer"]}, now=NOW))
    claude, gemini, chatgpt = lanes["claude"], lanes["gemini"], lanes["chatgpt"]
    require(claude["availability"] == "online" and claude["heartbeat"]["source"] == "claude_heartbeat", "legacy Claude heartbeat online")
    require(claude["open_ticket"] == {"id": "T-585", "stage": "running", "source": "claude_heartbeat", "title": "Multi-operator delegation board"},
            f"claude open ticket: {claude['open_ticket']}")
    require(claude["branch"] == "autopilot/aws-worker" and claude["runtime"] == "claude-code" and claude["head_sha"] == "03a88cd2d214",
            "claude branch/runtime/head")
    require(claude["queue_depth"] == 3 and claude["queue_depth_source"] == "claude_heartbeat", "claude queue depth from telemetry")
    require(claude["last_result"]["task_id"] == "T-584" and claude["last_result"]["commit"] == "03a88cd2d214"
            and claude["last_result"]["source"] == "worker_result", f"claude last result: {claude['last_result']}")
    require(claude["roadmap_open"] == 4 and claude["assigned_not_claimed"] == ["T-586"], "claude roadmap queue")

    require(gemini["availability"] == "stale" and gemini["configured"] and gemini["reason"] == "heartbeat_expired",
            f"expired Gemini heartbeat must be stale: {gemini['availability']}")
    require(gemini["heartbeat"]["age_seconds"] == 200.0 and gemini["branch"] == "gemini/t-589" and gemini["runtime"] == "antigravity",
            "gemini last-known heartbeat/branch/runtime")
    require(gemini["open_ticket"]["source"] == "relay" and gemini["open_ticket"]["title"] == "Engineering battle pilot",
            "gemini open ticket comes from the Relay run, not the expired heartbeat")
    require(gemini["last_result"]["source"] == "relay" and gemini["last_result"]["result"] == "blocked"
            and gemini["last_result"]["summary"] == "needs review", f"gemini last result: {gemini['last_result']}")
    require(gemini["queue_depth"] == 0 and gemini["queue_depth_source"] == "operator_heartbeat", "reported zero stays a reported zero")
    require(gemini["last_error"] == "" and gemini["assigned_roles"] == ["engineer"], "gemini error/roles")
    require([t["id"] for t in gemini["open_tickets"]] == ["T-589"], f"gemini open tickets: {gemini['open_tickets']}")

    require(chatgpt["availability"] == "online" and chatgpt["kind"] == "planner" and chatgpt["heartbeat"]["source"] is None,
            "ChatGPT is online only through a fresh Relay run")
    require(chatgpt["open_ticket"]["id"] == "T-600" and chatgpt["stage"] == "running" and chatgpt["queue_depth"] is None, "chatgpt lane")

    dumped = json.dumps(lanes)
    require(SECRET not in dumped and "worker_token" not in dumped and '"env"' not in dumped and '"token"' not in dumped,
            "runner-supplied extra fields must not leave the lane builder")

    # Long-expired heartbeat becomes offline; a fresh runner heartbeat drives the ticket itself.
    old = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - 7200, "status": "working", "task_id": "T-589"}}, now=NOW))
    require(old["gemini"]["availability"] == "offline" and old["gemini"]["open_ticket"] is None, "old heartbeat offline, no ticket")
    live = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - 5, "status": "working", "task_id": "T-589", "stage": "coding",
                                                          "queue_depth": 2, "last_result": "tests green"}}, now=NOW))["gemini"]
    require(live["availability"] == "online" and live["open_ticket"]["source"] == "operator_heartbeat" and live["stage"] == "coding",
            "live Gemini runner")
    require(live["queue_depth"] == 2 and live["last_result"]["summary"] == "tests green", "live Gemini queue/result")
    idle = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - 5, "status": "idle", "task_id": "T-589"}}, now=NOW))["gemini"]
    require(idle["open_ticket"] is None, "an idle heartbeat does not claim an open ticket")

    # Heartbeat time boundary checks: TTL, TTL+1, offline_after, offline_after+1
    ttl, off = 45, 3600
    at_ttl = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - ttl}}, runner_ttl=ttl, offline_after=off, now=NOW))["gemini"]
    require(at_ttl["availability"] == "online", f"age == TTL ({ttl}) must be online, got {at_ttl['availability']}")

    ttl_plus_1 = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - (ttl + 1)}}, runner_ttl=ttl, offline_after=off, now=NOW))["gemini"]
    require(ttl_plus_1["availability"] == "stale", f"age == TTL + 1 ({ttl + 1}) must be stale, got {ttl_plus_1['availability']}")

    at_off = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - off}}, runner_ttl=ttl, offline_after=off, now=NOW))["gemini"]
    require(at_off["availability"] == "stale", f"age == offline_after ({off}) must be stale, got {at_off['availability']}")

    off_plus_1 = by_id(build_operator_lanes(runners={"gemini": {"last_seen": NOW - (off + 1)}}, runner_ttl=ttl, offline_after=off, now=NOW))["gemini"]
    require(off_plus_1["availability"] == "offline", f"age == offline_after + 1 ({off + 1}) must be offline, got {off_plus_1['availability']}")


def api_checks():
    real_identity = app.request_identity
    try:
        app.request_identity = lambda _r: {"role": "viewer"}
        try:
            app.factory_delegation_board(None)
            raise AssertionError("viewer must not read the delegation board")
        except HTTPException as exc:
            require(exc.status_code == 403, f"viewer got {exc.status_code}")
        app.request_identity = lambda _r: {"role": "owner"}
        app.claude_worker_runtime.update({"last_seen": 0.0, "node": {}, "active_task_id": "", "last_error": "", "telemetry": {}})
        app.operator_worker_runtime.clear()
        app.operator_worker_runtime.update({"claude": {"last_seen": 0.0}, "gemini": {"last_seen": 0.0}})
        lanes = by_id(app.factory_delegation_board(None)["operator_lanes"])
        require(lanes["gemini"]["availability"] == "unconfigured" and lanes["gemini"]["reason"] == "never_reported",
                "unconfigured Gemini must be explicit in the API")
        require(lanes["gemini"]["provider_status"] == "auth_pending", "Gemini without a key is auth_pending, not ready")
        require(lanes["claude"]["availability"] == "unconfigured", "never-seen Claude must not look online")

        app.operator_worker_heartbeat(app.OperatorWorkerHeartbeat(
            operator_id="gemini", node_id="gem-ci", runtime="antigravity", branch="gemini/ci", status="working", task_id="T-589",
            stage="coding", queue_depth=2, last_result="secret was " + app.FACTORY_OPERATOR_WORKER_TOKEN,
            tickets=[{"id": "T-589", "title": "pilot", "token": SECRET}]))
        board = app.factory_delegation_board(None)
        lanes = by_id(board["operator_lanes"])
        gemini = lanes["gemini"]
        require(gemini["availability"] == "online" and gemini["open_ticket"]["id"] == "T-589" and gemini["stage"] == "coding",
                f"live Gemini lane: {gemini}")
        require(gemini["branch"] == "gemini/ci" and gemini["runtime"] == "antigravity" and gemini["queue_depth"] == 2, "gemini provenance")
        require(gemini["open_ticket"]["title"].startswith("Engineering battle pilot"), "ticket title from ROADMAP")
        dumped = json.dumps(board)
        require(app.FACTORY_OPERATOR_WORKER_TOKEN not in dumped and "[redacted]" in gemini["last_result"]["summary"],
                "worker token must be redacted from the board")
        require(SECRET not in dumped, "runner ticket extra fields must not be returned")
        require(board["safety"]["secrets_returned"] is False, "safety flag")
    finally:
        app.request_identity = real_identity
        app.operator_worker_runtime.clear()
        app.operator_worker_runtime.update({"claude": {"last_seen": 0.0}, "gemini": {"last_seen": 0.0}})


if __name__ == "__main__":
    pure_checks()
    print("operator lane builder checks passed (unconfigured/stale/offline/online, ticket/result/queue provenance, field whitelist)")
    api_checks()
    print("delegation board operator lanes API checks passed (owner-only, explicit unconfigured Gemini, secrets redacted)")
    # T-588 routes on these lanes; run it here (own process, own DATA_DIR) since the CI workflow cannot be edited
    # until T-598-H1 grants the workflow scope.
    import subprocess
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    subprocess.run([sys.executable, os.path.join(here, "test_supervisor_routing.py")], check=True)
