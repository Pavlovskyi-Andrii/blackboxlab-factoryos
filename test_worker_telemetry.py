"""T-536-B Live worker telemetry regression.

Deterministic, no network, no Claude. Proves:
- the runner collects numeric CPU/memory from Linux/Termux-style /proc fixtures, falls back to
  loadavg, and degrades to null + ``unsupported`` where neither exists;
- the runner heartbeat carries stage, task start/elapsed, branch/head and queue depth;
- the server whitelists/type-checks telemetry (invalid -> null, extra keys dropped), persists the
  last heartbeat across a restart, and the owner board + shipped Control Center renderer show it
  without secrets.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SECRET = "fixture-worker-token-SECRET-536b"
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-telemetry-")
os.environ["FACTORY_CLAUDE_WORKER_TOKEN"] = SECRET
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app  # noqa: E402
import test_delegation_ui as ui  # noqa: E402
from autopilot import claude_pro_worker as worker  # noqa: E402
from worker_observability import sanitize_telemetry  # noqa: E402

ROADMAP = """## Fixture
- [x] T-970 Done task
- [ ] [HUMAN] T-971 Real publish approval
- [ ] T-972 Running safe task
- [ ] T-973 Queued safe task
"""
MEMINFO = "MemTotal:        4000000 kB\nMemFree:          500000 kB\nMemAvailable:    1500000 kB\nCached:           800000 kB\n"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def proc_dir(stat=None, meminfo=None):
    path = Path(tempfile.mkdtemp(prefix="factoryos-proc-"))
    if stat is not None:
        (path / "stat").write_text(stat, encoding="ascii")
    if meminfo is not None:
        (path / "meminfo").write_text(meminfo, encoding="ascii")
    return str(path)


def check_runner_metrics():
    worker._cpu_prev = None
    first = proc_dir("cpu  100 0 100 800 0 0 0 0 0 0\n", MEMINFO)
    second = proc_dir("cpu  150 0 150 900 0 0 0 0 0 0\n", MEMINFO)
    _, source = worker.cpu_sample(first)
    require(source in ("loadavg", "unsupported"), "first /proc/stat sample has no delta and must not invent a percent")
    cpu, source = worker.cpu_sample(second)
    require((cpu, source) == (50.0, "proc_stat"), f"/proc/stat delta CPU wrong: {cpu} {source}")
    require(worker.memory_sample(first) == (2441.4, 3906.2, "proc_meminfo"), f"meminfo wrong: {worker.memory_sample(first)}")
    old_kernel = proc_dir(meminfo="MemTotal: 2048000 kB\nMemFree: 1024000 kB\nCached: 512000 kB\n")
    require(worker.memory_sample(old_kernel) == (500.0, 2000.0, "proc_meminfo"), "MemAvailable fallback wrong")

    # Termux on newer Android: /proc/stat is unreadable; loadavg is used and labelled as an estimate.
    worker._cpu_prev = None
    termux = proc_dir(meminfo=MEMINFO)
    real_loadavg, real_count = os.getloadavg, os.cpu_count
    try:
        os.getloadavg, os.cpu_count = (lambda: (2.0, 1.0, 1.0)), (lambda: 8)
        require(worker.cpu_sample(termux) == (25.0, "loadavg"), "loadavg fallback wrong")

        def no_loadavg():
            raise OSError("unsupported")
        os.getloadavg = no_loadavg
        empty = proc_dir()
        require(worker.cpu_sample(empty) == (None, "unsupported"), "unsupported CPU must be null")
        require(worker.memory_sample(empty) == (None, None, "unsupported"), "unsupported memory must be null")
    finally:
        os.getloadavg, os.cpu_count = real_loadavg, real_count


def check_runner_heartbeat():
    repo = Path(tempfile.mkdtemp(prefix="factoryos-repo-"))
    (repo / ".autopilot").mkdir()
    (repo / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    started = time.time() - 125
    (repo / ".autopilot" / "run.json").write_text(json.dumps({
        "task": "T-972", "state": "running", "run_id": "run-1", "pid": os.getpid(),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))}), encoding="utf-8")
    git = shutil.which("git")
    if git:
        env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
        for args in (["init", "-q", "-b", "autopilot/fixture"], ["add", "ROADMAP.md"], ["commit", "-q", "-m", "fixture"]):
            subprocess.run([git, *args], cwd=repo, env=env, check=True, capture_output=True)
    sent = {}

    class Response:
        def raise_for_status(self):
            return None

    real = (worker.REPO, worker.WORKER_TOKEN, worker.requests.post)
    try:
        worker.REPO, worker.WORKER_TOKEN = repo, SECRET
        worker.requests.post = lambda url, headers, json, timeout: sent.update(url=url, payload=json) or Response()
        worker.heartbeat("2.0.0-fixture")
    finally:
        worker.REPO, worker.WORKER_TOKEN, worker.requests.post = real
    payload = sent["payload"]
    telemetry = payload["telemetry"]
    require(payload["task_id"] == "T-972" and telemetry["stage"] == "running", f"stage/task missing: {telemetry}")
    require(abs(telemetry["task_started_at"] - int(started)) < 1, "task start not taken from run.json")
    require(120 <= telemetry["elapsed_seconds"] <= 140, f"elapsed wrong: {telemetry['elapsed_seconds']}")
    require(telemetry["queue_depth"] == 2, f"queue depth must count unchecked non-HUMAN tasks: {telemetry['queue_depth']}")
    if git:
        require(telemetry["branch"] == "autopilot/fixture" and len(telemetry["head_sha"] or "") == 40, "branch/head missing")
    if os.path.exists("/proc/meminfo"):
        require(isinstance(telemetry["memory_mb"], float) and telemetry["memory_source"] == "proc_meminfo",
                "Linux memory must be numeric when available")
    require(SECRET not in json.dumps(payload), "worker token leaked into the heartbeat body")
    # The real model accepts it, so the endpoint will not 422 on a new runner.
    app.ClaudeWorkerHeartbeat(**payload)
    return payload


def check_sanitize():
    now = 2_000_000_000.0
    require(sanitize_telemetry(None) == {} and sanitize_telemetry("x") == {} and sanitize_telemetry({}) == {},
            "missing telemetry must stay empty (renders as unavailable)")
    bad = sanitize_telemetry({"stage": "<script>", "task_started_at": now + 3600, "elapsed_seconds": 50,
                              "cpu_percent": "90", "cpu_source": "proc_stat", "memory_mb": float("nan"),
                              "memory_source": "proc_meminfo", "queue_depth": 2.5, "branch": "a b;rm -rf",
                              "head_sha": "not-a-sha", "token": SECRET, "worker_uptime_seconds": -1}, now)
    require(bad["task_started_at"] is None and bad["elapsed_seconds"] is None, "future start must drop start + elapsed")
    require(bad["cpu_percent"] is None and bad["cpu_source"] == "unsupported", "string CPU must degrade to null")
    require(bad["memory_mb"] is None and bad["memory_source"] == "unsupported", "NaN memory must degrade to null")
    require(bad["queue_depth"] is None and bad["branch"] is None and bad["head_sha"] is None, "invalid fields must be null")
    require(bad["stage"] == "script" and bad["worker_uptime_seconds"] is None, "stage/uptime not sanitized")
    require("token" not in bad and SECRET not in json.dumps(bad), "unknown keys must be dropped")
    over = sanitize_telemetry({"cpu_percent": 250, "cpu_source": "proc_stat", "memory_mb": 10, "memory_source": "bogus"}, now)
    require(over["cpu_percent"] is None and over["memory_mb"] is None and over["memory_source"] == "unsupported",
            "out-of-range / unknown-source metrics must degrade")


def check_server(payload):
    (Path(os.environ["DATA_DIR"])).mkdir(parents=True, exist_ok=True)
    raw = dict(payload)
    raw["telemetry"] = {**payload["telemetry"], "token": SECRET, "cpu_percent": 33.3, "cpu_source": "proc_stat",
                        "memory_mb": 1234.5, "memory_total_mb": 3906.2, "memory_source": "proc_meminfo",
                        "branch": payload["telemetry"]["branch"] or "autopilot/fixture",
                        "head_sha": payload["telemetry"]["head_sha"] or "a" * 40}
    app._parse_roadmap_tasks = (lambda real: (lambda text=None: real(ROADMAP if text is None else text)))(app._parse_roadmap_tasks)
    response = app.claude_worker_heartbeat(app.ClaudeWorkerHeartbeat(**raw))
    require(response["telemetry"]["cpu_percent"] == 33.3 and "token" not in response["telemetry"], "heartbeat telemetry not sanitized")
    require("telemetry" not in app.claude_worker_runtime["node"], "telemetry must not also sit unsanitized in node")
    stored = app.CLAUDE_WORKER_HEARTBEAT_FILE.read_text(encoding="utf-8")
    require(SECRET not in stored and '"cpu_percent": 33.3' in stored, "heartbeat must persist sanitized telemetry without secrets")

    # Restart: runtime is lost, the persisted heartbeat comes back; elapsed keeps advancing live.
    app.claude_worker_runtime.update({"last_seen": 0.0, "node": {}, "active_task_id": "", "last_error": "", "telemetry": {}})
    app._restore_claude_worker_heartbeat()
    restored = app.claude_worker_runtime["telemetry"]
    require(restored["memory_mb"] == 1234.5 and restored["stage"] == "running", "telemetry not restored after restart")
    live = app._live_claude_worker_telemetry(now=restored["task_started_at"] + 600)
    require(live["elapsed_seconds"] == 600.0, f"elapsed must advance from task start: {live['elapsed_seconds']}")

    board = app.get_delegation_board()
    t = board["worker"]["telemetry"]
    require(board["worker"]["connection"] == "online" and board["worker"]["active_task_id"] == "T-972", "board worker state wrong")
    require(t["cpu_percent"] == 33.3 and t["memory_total_mb"] == 3906.2 and t["queue_depth"] == 2, f"board telemetry missing: {t}")
    require(SECRET not in json.dumps(board), "board leaked the worker token")
    running = board["timelines"]["T-972"]["events"]
    require(any(e["kind"] == "running" and e["status"] == "observed" and e.get("stage") == "running" for e in running),
            "timeline running event must use heartbeat telemetry")

    # Unsupported platform heartbeat: metrics null, board still renders.
    app.claude_worker_heartbeat(app.ClaudeWorkerHeartbeat(**{**payload, "telemetry": {
        "stage": "idle", "cpu_percent": None, "cpu_source": "unsupported", "memory_mb": None, "memory_source": "unsupported"}}))
    degraded = app.get_delegation_board()
    dt = degraded["worker"]["telemetry"]
    require(dt["cpu_percent"] is None and dt["memory_mb"] is None and dt["elapsed_seconds"] is None, "unsupported must stay null")
    return board, degraded


def check_render(board, degraded):
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the telemetry rendering check")
        print("SKIPPED telemetry rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    _, block, i18n, helpers, tr = ui.extract(ui.HTML.read_text(encoding="utf-8"))
    program = (f"let LANG='en';\n{helpers}\n{i18n}\n{tr}\n{block}\n"
               f"const boards={json.dumps({'live': board, 'degraded': degraded})};\n"
               "process.stdout.write(JSON.stringify({live:renderDelegationCenter(boards.live,{}),"
               "degraded:renderDelegationCenter(boards.degraded,{})}));\n")
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"renderer harness failed:\n{result.stderr[-2000:]}")
    out = json.loads(result.stdout)
    live, degraded_html = out["live"], out["degraded"]
    head = board["worker"]["telemetry"]["head_sha"][:7]
    require("33.3%" in live and "1235 / 3906 MB" in live, "rendered CPU/memory missing")
    require(f"{board['worker']['telemetry']['branch']}@{head}" in live, "rendered branch@head missing")
    require(">running<" in live and "T-972" in live, "rendered stage/task missing")
    require("33.3%" not in degraded_html and degraded_html.count('class="dcNa"') >= 2, "unsupported metrics must render unavailable")
    require(SECRET not in live and SECRET not in degraded_html, "secret rendered")


def main():
    check_runner_metrics()
    print("runner metrics: /proc delta, meminfo, loadavg fallback, unsupported -> null: OK")
    payload = check_runner_heartbeat()
    print("runner heartbeat: stage, start/elapsed, branch/head, queue depth, no token in body: OK")
    check_sanitize()
    print("server sanitize: invalid -> null, extra keys dropped: OK")
    board, degraded = check_server(payload)
    print("server persist/restore + delegation board telemetry, secret-free: OK")
    check_render(board, degraded)
    print("T-536-B live worker telemetry regression passed")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
