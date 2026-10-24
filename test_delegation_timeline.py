"""T-536-E Delegation execution timeline regression (server side).

Verified task-result fixtures must produce factual timeline events
(queued -> picked -> running -> checks -> commit -> push -> outcome) carrying the
exact commit SHA/link, changed files and reported checks. Anything that was not
reported stays `unavailable` / `pending` / `skipped`; nothing is invented.
"""
import json
import os
import sys
import tempfile
import time

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-timeline-")
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app  # noqa: E402

SHA = "5fb2d3cc8823d2330bdb113eec415c5a8670c94f"
ROADMAP = """## Fixture
- [x] T-950 Legacy done without a worker result
- [ ] [HUMAN] T-951 Owner approval
- [ ] T-952 Delegated and verified
- [ ] T-953 Delegated but blocked
- [ ] T-954 Currently running
- [ ] T-955 Still queued
- [ ] T-956 Agent pushed by itself
"""


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def by_kind(timeline):
    return {e["kind"]: e for e in timeline["events"]}


def kinds(timeline):
    return [e["kind"] for e in timeline["events"]]


ORDER = ["queued", "picked", "running", "checks", "commit", "push", "outcome"]


def pure_builder_checks():
    now = 1_800_000_000.0
    done = app.build_delegation_timeline(
        {"id": "T-1", "state": "done", "done": False, "roadmap_line": 7},
        [{"task_id": "T-1", "result": "failed", "received_at": now - 900},
         {"task_id": "T-1", "result": "done", "started_at": now - 600, "received_at": now - 60, "duration_seconds": 540.0,
          "exit_code": 0, "timed_out": False, "checks": ["python smoke_tests.py"], "commit": SHA, "commit_count": 1,
          "files": ["app.py", "ROADMAP.md"], "summary": "implemented", "need": "", "violations": []}], now=now)
    ev = by_kind(done)
    require(kinds(done) == ORDER and done["phase"] == "result" and done["attempts"] == 2, f"done timeline shape: {done}")
    require(ev["queued"]["status"] == "observed" and ev["queued"]["at"] is None and ev["queued"]["roadmap_line"] == 7,
            "queued is observed from ROADMAP without an invented timestamp")
    require(ev["picked"]["at"] == ev["running"]["at"] == now - 600 and ev["running"]["duration_seconds"] == 540.0, "observed start/duration")
    require(ev["checks"]["status"] == "observed" and ev["checks"]["items"] == [{"command": "python smoke_tests.py", "passed": None}],
            "checks are the reported commands; per-check pass/fail is not invented")
    require(ev["commit"]["sha"] == SHA and ev["commit"]["files"] == ["app.py", "ROADMAP.md"] and ev["commit"]["file_count"] == 2
            and ev["commit"]["url"] == f"https://github.com/{app.GITHUB_REPO}/commit/{SHA}", f"commit evidence: {ev['commit']}")
    require(ev["push"]["status"] == "unavailable" and ev["push"]["at"] is None, "the runner's push is never observed, so it is not claimed")
    require(ev["outcome"]["result"] == "done" and ev["outcome"]["at"] == now - 60 and ev["outcome"]["summary"] == "implemented", "outcome event")

    legacy = app.build_delegation_timeline({"id": "T-2", "state": "done", "done": True}, [], now=now)
    require(kinds(legacy) == ORDER and legacy["phase"] == "roadmap"
            and [e["status"] for e in legacy["events"]] == ["observed"] + ["unavailable"] * 5 + ["observed"]
            and legacy["events"][-1]["source"] == "roadmap" and legacy["events"][-1]["at"] is None,
            f"done-without-evidence must show the middle as unavailable: {legacy}")

    queued = app.build_delegation_timeline({"id": "T-3", "state": "queued", "done": False}, [], now=now)
    require([e["status"] for e in queued["events"]] == ["observed"] + ["pending"] * 6 and queued["attempts"] == 0, "queued timeline")

    telemetry = {"stage": "running", "task_started_at": now - 120, "elapsed_seconds": 120.0}
    running = app.build_delegation_timeline({"id": "T-4", "state": "running", "done": False}, [], telemetry, now=now)
    ev = by_kind(running)
    require(ev["picked"]["at"] == now - 120 and ev["picked"]["source"] == "heartbeat" and ev["running"]["elapsed_seconds"] == 120.0
            and [ev[k]["status"] for k in ORDER[3:]] == ["pending"] * 4, f"running timeline: {running}")
    bare = app.build_delegation_timeline({"id": "T-4", "state": "running", "done": False}, [], {}, now=now)
    require(by_kind(bare)["picked"]["at"] is None and by_kind(bare)["running"]["elapsed_seconds"] is None,
            "a heartbeat without telemetry must not invent a start time")
    future = app.build_delegation_timeline({"id": "T-4", "state": "running", "done": False}, [],
                                           {"stage": "running", "task_started_at": now + 3600}, now=now)
    require(by_kind(future)["picked"]["at"] is None, "future start timestamps are rejected")

    blocked = app.build_delegation_timeline(
        {"id": "T-5", "state": "blocked", "done": False},
        [{"task_id": "T-5", "result": "blocked", "received_at": now, "need": "owner decision", "checks": [], "commit": ""}], now=now)
    ev = by_kind(blocked)
    require(ev["picked"]["at"] is None and ev["checks"]["status"] == ev["commit"]["status"] == ev["push"]["status"] == "skipped"
            and ev["outcome"]["result"] == "blocked" and ev["outcome"]["need"] == "owner decision", f"blocked timeline: {blocked}")


def board_checks():
    tasks = app._parse_roadmap_tasks(ROADMAP)
    real_parse = app._parse_roadmap_tasks
    app._parse_roadmap_tasks = lambda text=None: [dict(x) for x in tasks]
    try:
        def ingest(task_id, **overrides):
            base = dict(task_id=task_id, pinned_task_id=task_id, result="done", branch="autopilot-ci", summary="ci", commit=SHA,
                        commit_count=1, files=["app.py"], exit_code=0, max_turns=80, timeout_seconds=3600)
            return app.ingest_claude_worker_result(app.ClaudeWorkerTaskResult(**{**base, **overrides}))

        before = time.time()
        rec = ingest("T-952", started_at=before - 300, duration_seconds=290.5, checks=["python smoke_tests.py", "python test_delegation_ui.py"],
                     files=["app.py", "static/index.html"], summary=f"done with {app.FACTORY_CLAUDE_WORKER_TOKEN or 'no-token'}")
        require(rec["started_at"] == before - 300, "observed start must be stored")
        require(ingest("T-953", result="blocked", commit="", commit_count=0, files=[], need="needs owner",
                       started_at=time.time() + 10**6)["started_at"] is None, "implausible future start must be dropped at ingest")
        require(ingest("T-956", pushed=True)["result"] == "failed", "self-push must fail the result")
        app.claude_worker_heartbeat(app.ClaudeWorkerHeartbeat(task_id="T-954", status="running", branch="autopilot-ci"))
        board = app.get_delegation_board()
        timelines = board["timelines"]
        require(sorted(timelines) == ["T-950", "T-952", "T-953", "T-954", "T-955", "T-956"], f"HUMAN tasks are never delegated: {sorted(timelines)}")
        ev = by_kind(timelines["T-952"])
        require(ev["picked"]["at"] == before - 300 and ev["running"]["duration_seconds"] == 290.5
                and [c["command"] for c in ev["checks"]["items"]] == ["python smoke_tests.py", "python test_delegation_ui.py"]
                and ev["commit"]["sha"] == SHA and ev["commit"]["url"].endswith("/commit/" + SHA)
                and ev["commit"]["files"] == ["app.py", "static/index.html"] and ev["outcome"]["result"] == "done"
                and ev["outcome"]["at"] >= before, f"verified result timeline: {timelines['T-952']}")
        ev = by_kind(timelines["T-953"])
        require(ev["picked"]["at"] is None and ev["commit"]["status"] == "skipped" and ev["outcome"]["need"] == "needs owner", "blocked board timeline")
        ev = by_kind(timelines["T-956"])
        require(ev["push"]["status"] == "observed" and ev["push"]["violation"] is True and ev["outcome"]["result"] == "failed"
                and "delegated agent pushed during execution" in ev["outcome"]["violations"], "self-push is shown as an observed violation")
        require(timelines["T-954"]["phase"] == "running" and by_kind(timelines["T-954"])["picked"]["source"] == "heartbeat", "running board timeline")
        require(timelines["T-950"]["phase"] == "roadmap" and timelines["T-955"]["phase"] == "queued", "legacy/queued board timelines")
        text = json.dumps(board)
        if app.FACTORY_CLAUDE_WORKER_TOKEN:
            require(app.FACTORY_CLAUDE_WORKER_TOKEN not in text, "worker token must never be returned")
        require("token" not in text.lower().replace("no-token", ""), "timeline board must stay secret-free")
    finally:
        app._parse_roadmap_tasks = real_parse


def main():
    pure_builder_checks()
    board_checks()
    print("Delegation execution timeline regression passed (done/blocked/failed/running/queued/legacy)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
