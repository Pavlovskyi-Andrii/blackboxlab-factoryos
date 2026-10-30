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


if __name__ == "__main__":
    main()
