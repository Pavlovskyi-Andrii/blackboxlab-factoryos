import tempfile
from pathlib import Path

from autopilot import autopilot as ap


def write_roadmap(text: str) -> Path:
    root = Path(tempfile.mkdtemp(prefix="factoryos-autopilot-test-"))
    path = root / "ROADMAP.md"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    path = write_roadmap(
        """# Roadmap

## v5
- [x] T-001 Finished
- [ ] [HUMAN] T-002 Owner credential
- [ ] T-003 Safe next task
- [ ] T-004 Later safe task
"""
    )
    tasks = ap.parse_roadmap(path)
    assert [x["id"] for x in tasks] == ["T-001", "T-002", "T-003", "T-004"]
    assert ap.next_safe_task(path)["id"] == "T-003"
    assert ap.first_human_blocker(path).startswith("T-002")
    assert ap.roadmap_has_safe_work(path) is True

    expected = ap.next_safe_task(path)
    assert ap.done_status_is_consistent({"task": "T-003", "status": "done"}, expected, path) is False

    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ] T-003", "- [x] T-003"),
        encoding="utf-8",
    )
    assert ap.done_status_is_consistent({"task": "T-003", "status": "done"}, expected, path) is True
    assert ap.next_safe_task(path)["id"] == "T-004"

    path.write_text(
        path.read_text(encoding="utf-8").replace("- [ ] T-004", "- [x] T-004"),
        encoding="utf-8",
    )
    assert ap.next_safe_task(path) is None
    assert ap.roadmap_has_safe_work(path) is False
    assert ap.first_human_blocker(path).startswith("T-002")
    assert "T-002" in ap.idle_notice(path)

    no_human = write_roadmap("# Roadmap\n\n## v5\n- [x] T-001 Finished\n")
    assert ap.idle_notice(no_human).startswith("🏁")
    dependency_and_owner_regression()
    print("Autopilot roadmap advancement tests passed")


def dependency_and_owner_regression():
    # T-537: unmet Depends are skipped, unrelated safe work advances, completion unlocks, HUMAN never runs.
    path = write_roadmap(
        """# Roadmap

## v5
- [ ] T-010 Foundation
  Owner: ChatGPT
- [ ] T-011 Needs foundation
  Depends: T-010
- [ ] [HUMAN] T-012 Owner credential
- [ ] T-013 Needs human task
  Depends: T-012
- [ ] T-014 Needs unknown task
  Depends: T-999, not-a-task
- [ ] T-015 Unrelated safe task
  Owner: any
- [ ] T-016 Claude lane task
  Owner: claude
"""
    )
    tasks = ap.parse_roadmap(path)
    by_id = {x["id"]: x for x in tasks}
    assert by_id["T-011"]["depends"] == ["T-010"]
    assert by_id["T-014"]["depends"] == ["T-999"]
    assert by_id["T-010"]["owner"] == "chatgpt"
    # ChatGPT-owned work is never taken by the Claude runner; dependents wait for it.
    assert ap.next_safe_task(path, "claude")["id"] == "T-015"
    assert ap.next_safe_task(path, "chatgpt")["id"] == "T-010"
    assert ap.unmet_dependencies(by_id["T-014"], tasks) == ["T-999"]

    text = path.read_text(encoding="utf-8").replace("- [ ] T-015", "- [x] T-015")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-016"

    text = text.replace("- [ ] T-016", "- [x] T-016")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None
    assert "T-011" in ap.idle_notice(path)

    # Completed dependency unlocks the dependent task.
    text = text.replace("- [ ] T-010", "- [x] T-010")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-011"

    # A HUMAN task is never selectable, even when it is the only open dependency path.
    text = text.replace("- [ ] T-011", "- [x] T-011")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None
    for operator in ("claude", "chatgpt", "gemini"):
        selected = ap.next_safe_task(path, operator)
        assert selected is None or not selected["human"]
    text = text.replace("- [ ] [HUMAN] T-012", "- [x] [HUMAN] T-012")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude")["id"] == "T-013"

    # Inline metadata as written in the live ROADMAP: other fields on the same line, trailing punctuation.
    inline = write_roadmap(
        """# Roadmap

## P0
- [ ] T-020 Takeover
  Planner: owner; Executor: Claude Code Pro. P0.
- [ ] T-021 Live acceptance
  Planner: owner; Executor: Claude Code Pro. P0. Depends: T-020.
- [ ] T-022 Hotfix
  Owner: ChatGPT. Depends: T-020 (implementation merged in #63; acceptance remains T-021).
"""
    )
    by_id = {x["id"]: x for x in ap.parse_roadmap(inline)}
    assert by_id["T-020"]["owner"] == "" and by_id["T-020"]["depends"] == []
    assert by_id["T-021"]["depends"] == ["T-020"]
    assert by_id["T-022"]["owner"] == "chatgpt"
    assert by_id["T-022"]["depends"] == ["T-020"]
    assert ap.next_safe_task(inline, "claude")["id"] == "T-020"
    text = text.replace("- [ ] T-013", "- [x] T-013")
    path.write_text(text, encoding="utf-8")
    assert ap.next_safe_task(path, "claude") is None  # T-014 waits forever on unknown T-999
    assert "T-014" in ap.idle_notice(path)
    print("Autopilot dependency/owner scheduler tests passed")
    parking_regression()
    roadmap_owner_lint()
    claim_gate_regression()
    follow_main_regression()
    restart_survival_regression()
    git_timeout_regression()
    subscription_limit_regression()
    milestone_report_regression()


def claim_gate_regression():
    # T-599-C/D: no verified server claim -> the agent never runs; a claimed run emits factual events.
    path = write_roadmap("# Roadmap\n\n## v5\n- [ ] T-040 Busy elsewhere\n  Owner: claude\n- [ ] T-041 Free\n  Owner: claude\n")
    calls, events, sleeps = [], [], {"n": 0}
    heads = iter(["a" * 40, "b" * 40])

    def fake_claim(task, lane):
        if task["id"] == "T-040":
            return None, "T-040 is already running by claude-other"
        return {"id": "R-0007", "execution": {"run_id": "run-x"}}, ""

    class Reporter:
        def __init__(self, ticket):
            self.ticket = ticket

        def __call__(self, stage, note="", evidence=None):
            events.append((stage, dict(evidence or {})))

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

    def fake_agent(target):
        calls.append(target["id"])
        path.write_text(path.read_text(encoding="utf-8").replace("- [ ] T-041", "- [x] T-041"), encoding="utf-8")
        return {"task": "T-041", "status": "done", "summary": "ok", "checks": ["python -m autopilot.test_autopilot"]}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] > 2:
            raise _StopLoop

    patches = {
        "ROADMAP": path, "ANSWERS": path.parent / "answers.md", "DAEMON_MODE": True, "OPERATOR": "claude",
        "RELAY_ONLY": False, "ALLOW_UNCLAIMED": False,
        "assert_safe_branch": lambda: "autopilot/test", "current_branch": lambda: "autopilot/test",
        "sync_branch": lambda _b: None, "commits_ahead": lambda _b: 0, "push_branch": lambda _b: True,
        "poll_control": lambda *a, **k: {"paused": False, "retry": "", "acks": []},
        "run_agent": fake_agent, "send": lambda _m: None, "write_runtime_status": lambda *a, **k: None,
        "git_head": lambda: next(heads),
    }
    saved = {name: getattr(ap, name) for name in patches}
    saved_rt = (ap.relay_tasks.run_one, ap.relay_tasks.claim_roadmap, ap.relay_tasks.RunReporter, ap.time.sleep)
    try:
        for name, value in patches.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one = lambda *a, **k: False
        ap.relay_tasks.claim_roadmap = fake_claim
        ap.relay_tasks.RunReporter = Reporter
        ap.time.sleep = fake_sleep
        try:
            ap.main()
        except _StopLoop:
            pass
    finally:
        for name, value in saved.items():
            setattr(ap, name, value)
        (ap.relay_tasks.run_one, ap.relay_tasks.claim_roadmap, ap.relay_tasks.RunReporter, ap.time.sleep) = saved_rt

    assert calls == ["T-041"], calls  # T-040 was refused by the server and never ran
    assert [s for s, _ in events] == ["running", "committed", "pushed", "done"], events
    assert events[1][1]["commit"] == "b" * 40
    print("Autopilot claim gate tests passed")


def follow_main_regression():
    # The worker branch follows main between tasks; runner code changes ask for a restart;
    # a conflicting merge is aborted and leaves a clean checkout.
    import subprocess

    def git(cwd, *args):
        subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)

    root = Path(tempfile.mkdtemp(prefix="factoryos-follow-main-"))
    origin, seed, worker = root / "origin.git", root / "seed", root / "worker"
    git(root, "init", "--bare", "-b", "main", str(origin))
    git(root, "clone", str(origin), str(seed))
    for cwd in (seed,):
        git(cwd, "config", "user.email", "t@example.com")
        git(cwd, "config", "user.name", "t")
    (seed / "ROADMAP.md").write_text("v1\n", encoding="utf-8")
    git(seed, "add", "."); git(seed, "commit", "-m", "init"); git(seed, "push", "origin", "main")
    git(seed, "push", "origin", "main:autopilot/w")
    git(root, "clone", "-b", "autopilot/w", str(origin), str(worker))
    git(worker, "config", "user.email", "w@example.com"); git(worker, "config", "user.name", "w")

    saved = (ap.REPO, ap.BASE_BRANCH)
    ap.REPO, ap.BASE_BRANCH = worker, "main"
    try:
        assert ap.sync_branch("autopilot/w") == ""
        (seed / "ROADMAP.md").write_text("v2\n", encoding="utf-8")
        git(seed, "commit", "-am", "roadmap only"); git(seed, "push", "origin", "main")
        assert ap.sync_branch("autopilot/w") == ""
        assert (worker / "ROADMAP.md").read_text(encoding="utf-8") == "v2\n"
        (seed / "autopilot").mkdir()
        (seed / "autopilot" / "x.py").write_text("X = 1\n", encoding="utf-8")
        git(seed, "add", "."); git(seed, "commit", "-m", "runner code"); git(seed, "push", "origin", "main")
        assert ap.sync_branch("autopilot/w") == "code_updated"
        # Conflict: both sides edit the same line; merge is aborted and the tree stays clean.
        (worker / "ROADMAP.md").write_text("worker\n", encoding="utf-8")
        git(worker, "commit", "-am", "worker edit")
        (seed / "ROADMAP.md").write_text("main\n", encoding="utf-8")
        git(seed, "commit", "-am", "main edit"); git(seed, "push", "origin", "main")
        assert ap.sync_branch("autopilot/w") == "conflict"
        status = subprocess.run(["git", "status", "--porcelain"], cwd=worker, capture_output=True, text=True).stdout
        assert status.strip() == "", status
    finally:
        ap.REPO, ap.BASE_BRANCH = saved
    print("Autopilot follow-main sync tests passed")


def roadmap_owner_lint():
    # T-599-B: every open, non-HUMAN task in the real ROADMAP names its lane explicitly.
    unowned = [t["id"] for t in ap.parse_roadmap(ap.ROADMAP) if not t["done"] and not t["human"] and not t["owner"]]
    assert not unowned, f"ROADMAP tasks without Owner: {unowned}"
    print("ROADMAP owner lint passed")


class _StopLoop(Exception):
    pass


def parking_regression():
    # T-599-A: a blocked or failed task is parked; the daemon moves on instead of stalling.
    path = write_roadmap(
        """# Roadmap

## v5
- [ ] T-030 Needs owner
  Owner: claude
- [ ] T-031 Keeps failing
  Owner: claude
- [ ] T-032 Healthy work
  Owner: claude
"""
    )
    assert ap.next_safe_task(path, "claude", skip={"T-030"})["id"] == "T-031"
    assert ap.next_safe_task(path, "claude", skip={"T-030", "T-031", "T-032"}) is None
    assert "T-030" in ap.idle_notice(path, parked={"T-030"})

    answers = path.parent / "answers.md"
    calls: list[str] = []
    sleeps = {"n": 0}

    def fake_agent(target):
        calls.append(target["id"])
        if target["id"] == "T-030":
            return {"task": "T-030", "status": "blocked", "need": "owner decision"}
        if target["id"] == "T-031":
            return {"task": "T-031", "status": "failed", "summary": "tests red"}
        text = path.read_text(encoding="utf-8").replace("- [ ] T-032", "- [x] T-032")
        path.write_text(text, encoding="utf-8")
        return {"task": "T-032", "status": "done", "summary": "ok"}

    def fake_sleep(_seconds):
        sleeps["n"] += 1
        if sleeps["n"] == 8:
            # New owner input wakes the blocked task exactly once more.
            answers.write_text("## T-030\nuse option A\n", encoding="utf-8")
        if sleeps["n"] > 12:
            raise _StopLoop

    patches = {
        "ROADMAP": path, "ANSWERS": answers, "DAEMON_MODE": True, "ALLOW_UNCLAIMED": True, "OPERATOR": "claude", "RELAY_ONLY": False,
        "assert_safe_branch": lambda: "autopilot/test", "current_branch": lambda: "autopilot/test",
        "sync_branch": lambda _b: None, "commits_ahead": lambda _b: 0, "push_branch": lambda _b: True,
        "poll_control": lambda *a, **k: {"paused": False, "retry": "", "acks": []},
        "run_agent": fake_agent, "send": lambda _m: None, "write_runtime_status": lambda *a, **k: None,
        "done_status_is_consistent": lambda status, target, path=None: True,
    }
    saved = {name: getattr(ap, name) for name in patches}
    saved_relay, saved_sleep = ap.relay_tasks.run_one, ap.time.sleep
    try:
        for name, value in patches.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one = lambda *a, **k: False
        ap.time.sleep = fake_sleep
        try:
            ap.main()
        except _StopLoop:
            pass
    finally:
        for name, value in saved.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one, ap.time.sleep = saved_relay, saved_sleep

    # Blocked T-030 did not stall the queue; T-031 got exactly MAX_FAILS attempts, then parked;
    # healthy T-032 still ran; owner input re-opened T-030 once.
    assert calls[0] == "T-030" and calls[1] == "T-031", calls
    assert calls.count("T-031") == ap.MAX_FAILS, calls
    assert "T-032" in calls, calls
    assert calls.count("T-030") == 2, calls
    print("Autopilot blocked/failed parking tests passed")


def _run_once(path, fake_agent, sent):
    """One daemon iteration, then a simulated crash/restart at the next sleep."""
    patches = {
        "ROADMAP": path, "ANSWERS": path.parent / "answers.md", "DAEMON_MODE": True, "ALLOW_UNCLAIMED": True,
        "OPERATOR": "claude", "RELAY_ONLY": False,
        "assert_safe_branch": lambda: "autopilot/test", "current_branch": lambda: "autopilot/test",
        "sync_branch": lambda _b: "", "commits_ahead": lambda _b: 0, "push_branch": lambda _b: True,
        "poll_control": lambda *a, **k: {"paused": False, "retry": "", "acks": []},
        "run_agent": fake_agent, "send": sent.append, "write_runtime_status": lambda *a, **k: None,
        "done_status_is_consistent": lambda status, target, path=None: True,
        "git_head": lambda: "c" * 40, "commit_files": lambda _sha: [],
    }
    saved = {name: getattr(ap, name) for name in patches}
    saved_relay, saved_sleep = ap.relay_tasks.run_one, ap.time.sleep

    def crash(_seconds):
        raise _StopLoop

    try:
        for name, value in patches.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one = lambda *a, **k: False
        ap.time.sleep = crash
        try:
            ap.main()
        except _StopLoop:
            pass
    finally:
        for name, value in saved.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one, ap.time.sleep = saved_relay, saved_sleep


def restart_survival_regression():
    # T-598: bounded retries and parking survive a worker restart (crash or code-update re-exec).
    path = write_roadmap(
        "# Roadmap\n\n## v5\n- [ ] T-050 Always red\n  Owner: claude\n- [ ] T-051 Needs owner\n  Owner: claude\n"
        "- [ ] T-052 Healthy\n  Owner: claude\n"
    )
    calls, sent = [], []

    def fake_agent(target):
        calls.append(target["id"])
        if target["id"] == "T-050":
            return {"task": "T-050", "status": "failed", "summary": "tests red"}
        if target["id"] == "T-051":
            return {"task": "T-051", "status": "blocked", "need": "owner decision"}
        path.write_text(path.read_text(encoding="utf-8").replace("- [ ] T-052", "- [x] T-052"), encoding="utf-8")
        return {"task": "T-052", "status": "done", "summary": "ok", "checks": ["python -m autopilot.test_autopilot"]}

    for _ in range(ap.MAX_FAILS + 6):
        _run_once(path, fake_agent, sent)
    # Without persistence every restart would reset the counter and T-050 would run forever.
    assert calls == ["T-050"] * ap.MAX_FAILS + ["T-051", "T-052"], calls
    parking = ap.json.loads((path.parent / "parking.json").read_text(encoding="utf-8"))
    assert parking["failed"] == ["T-050"] and "T-051" in parking["blocked"], parking
    assert any(m.startswith("✅ 🧭 T-052 · done") for m in sent), sent
    assert any("blocker: owner decision" in m for m in sent), sent

    # Corrupt state is ignored instead of crashing the worker.
    (path.parent / "parking.json").write_text("{not json", encoding="utf-8")
    saved_answers = ap.ANSWERS
    try:
        ap.ANSWERS = path.parent / "answers.md"
        assert ap.load_parking() == {"blocked": {}, "failed": set(), "failures_task": "", "failures": 0, "limit_until": 0.0}
    finally:
        ap.ANSWERS = saved_answers
    print("Autopilot restart survival tests passed")


def git_timeout_regression():
    # T-598: an unreachable/hung remote is a bounded failed sync, never an endless "busy" pull.
    seen = []

    def hung(cmd, **kwargs):
        seen.append((cmd[:2], kwargs.get("timeout"), kwargs.get("env", {}).get("GIT_TERMINAL_PROMPT")))
        if cmd[1] in {"pull", "fetch", "push"}:
            raise ap.subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return ap.subprocess.CompletedProcess(cmd, 0, "a" * 40 + "\n", "")

    saved = ap.subprocess.run
    try:
        ap.subprocess.run = hung
        assert ap.sync_branch("autopilot/w") == "offline"
        assert ap.push_branch("autopilot/w") is False
    finally:
        ap.subprocess.run = saved
    network = [s for s in seen if s[0][1] in {"pull", "fetch", "push"}]
    assert network and all(t == ap.GIT_NET_TIMEOUT and prompt == "0" for _, t, prompt in network), seen
    print("Autopilot git timeout tests passed")


def subscription_limit_regression():
    # T-600: an account-wide limit pauses the whole queue until the reset instead of burning and
    # parking one task after another (2026-10-31: 13 tasks parked in 20 minutes).
    path = write_roadmap(
        "# Roadmap\n\n## v5\n- [ ] T-060 First\n  Owner: claude\n- [ ] T-061 Second\n  Owner: claude\n"
    )
    clock = {"now": 1793466900.0}  # 2026-10-31 17:15 UTC
    calls, sent = [], []
    limited = {"status": "blocked", "error_category": "subscription_limit", "limit_resets": "6pm (UTC)",
               "summary": "Claude subscription usage limit reached; resets 6pm (UTC)."}

    def fake_agent(target):
        calls.append((target["id"], clock["now"]))
        if len(calls) == 1:
            return dict(limited, task=target["id"])
        text = path.read_text(encoding="utf-8").replace(f"- [ ] {target['id']}", f"- [x] {target['id']}")
        path.write_text(text, encoding="utf-8")
        return {"task": target["id"], "status": "done", "summary": "ok"}

    def fake_sleep(seconds):
        clock["now"] += seconds
        if clock["now"] > 1793466900.0 + 3 * 3600:
            raise _StopLoop

    patches = {
        "ROADMAP": path, "ANSWERS": path.parent / "answers.md", "DAEMON_MODE": True, "ALLOW_UNCLAIMED": True,
        "OPERATOR": "claude", "RELAY_ONLY": False,
        "assert_safe_branch": lambda: "autopilot/test", "current_branch": lambda: "autopilot/test",
        "sync_branch": lambda _b: "", "commits_ahead": lambda _b: 0, "push_branch": lambda _b: True,
        "poll_control": lambda *a, **k: {"paused": False, "retry": "", "acks": []},
        "run_agent": fake_agent, "send": sent.append, "write_runtime_status": lambda *a, **k: None,
        "done_status_is_consistent": lambda status, target, path=None: True,
        "git_head": lambda: "c" * 40, "commit_files": lambda _sha: [],
    }
    saved = {name: getattr(ap, name) for name in patches}
    saved_relay, saved_sleep, saved_time = ap.relay_tasks.run_one, ap.time.sleep, ap.time.time
    try:
        for name, value in patches.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one = lambda *a, **k: False
        ap.time.sleep = fake_sleep
        ap.time.time = lambda: clock["now"]
        try:
            ap.main()
        except _StopLoop:
            pass
    finally:
        for name, value in saved.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one, ap.time.sleep, ap.time.time = saved_relay, saved_sleep, saved_time

    reset = 1793466900.0 + 45 * 60 + ap.LIMIT_GRACE_SECONDS  # 18:00 UTC + grace
    # Exactly one call hit the limit; nothing else started before the reset; then both tasks ran.
    assert [c[0] for c in calls] == ["T-060", "T-060", "T-061"], calls
    assert all(t >= reset for _, t in calls[1:]), (calls, reset)
    assert any(m.startswith("⏳") and "18:02 UTC" in m and "no task is parked" in m for m in sent), sent
    assert any("limit window has passed" in m for m in sent), sent
    assert not any("failed" in m and "T-060" in m for m in sent), sent

    # The pause survives a worker restart: a fresh daemon start must not run Claude before the reset.
    path2 = write_roadmap("# Roadmap\n\n## v5\n- [ ] T-070 Waits\n  Owner: claude\n")
    answers2 = path2.parent / "answers.md"
    saved_answers = ap.ANSWERS
    try:
        ap.ANSWERS = answers2
        ap.save_parking({}, set(), "", 0, 1793466900.0 + 600)
        state = ap.load_parking()
    finally:
        ap.ANSWERS = saved_answers
    assert state["limit_until"] == 1793466900.0 + 600 and state["failures"] == 0, state
    started = []
    clock["now"] = 1793466900.0
    patches.update({"ROADMAP": path2, "ANSWERS": answers2, "run_agent": lambda t: started.append(clock["now"]) or
                    {"task": t["id"], "status": "failed", "summary": "stop"}})
    saved = {name: getattr(ap, name) for name in patches}
    try:
        for name, value in patches.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one = lambda *a, **k: False
        ap.time.sleep = fake_sleep
        ap.time.time = lambda: clock["now"]
        try:
            ap.main()
        except _StopLoop:
            pass
    finally:
        for name, value in saved.items():
            setattr(ap, name, value)
        ap.relay_tasks.run_one, ap.time.sleep, ap.time.time = saved_relay, saved_sleep, saved_time
    assert started and started[0] >= 1793466900.0 + 600, started
    print("Autopilot subscription limit pause tests passed")


def milestone_report_regression():
    # T-598/M6: concise checkpoint with UTC + Kyiv, stage, lanes, files, checks, SHA; no claimed PR/CI/deploy.
    text = ap.milestone_report(
        "T-598", "done · pushed", summary="ok", owner="claude", branch="autopilot/aws-worker", commit="0123456789abcdef",
        files=[f"f{i}.py" for i in range(7)], checks=["python -m autopilot.test_autopilot"], next_task="T-600",
        now=1793464200,  # 2026-10-31 16:30 UTC
    )
    assert "2026-10-31 16:30 UTC" in text, text
    assert "18:30 Kyiv" in text or "Kyiv time unavailable" in text, text
    assert "autopilot/aws-worker @ 0123456789" in text and "(+2)" in text, text
    assert "PR / CI / Render: not verified by the worker" in text and "next: T-600" in text, text
    assert len(text.splitlines()) <= 10
    print("Autopilot milestone report tests passed")


if __name__ == "__main__":
    main()
