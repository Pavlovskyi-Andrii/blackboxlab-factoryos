"""Deterministic regression for the Claude delegation adapter (T-508).

Uses a throwaway git repository and a fake Claude runner; never invokes the
real Claude CLI, never touches the network and never pushes.
"""
import json
import os
import subprocess
import tempfile
from pathlib import Path

from autopilot import delegation as dg

ROADMAP = """# Roadmap

## v5
- [x] T-001 Finished
- [ ] [HUMAN] T-002 Owner credential
- [ ] T-003 Delegated task
- [ ] T-004 Later task
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


def make_repo() -> Path:
    repo = Path(tempfile.mkdtemp(prefix="factoryos-delegation-test-"))
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "delegation-test")
    (repo / "ROADMAP.md").write_text(ROADMAP, encoding="utf-8")
    (repo / ".gitignore").write_text(".autopilot/status.json\n.autopilot/evidence/\n", encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "init")
    # Simulate a remote-tracking ref so a push would be observable.
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    git(repo, "checkout", "-q", "-b", "autopilot-test")
    return repo


TASK = {"id": "T-003", "title": "Delegated task", "done": False, "human": False}


def fake_runner(behaviour):
    calls = []

    def runner(cmd, *, cwd, env, timeout, **kwargs):
        calls.append({"cmd": cmd, "env": env, "timeout": timeout, "cwd": cwd})
        repo = Path(cwd)
        behaviour(repo)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result":"ok"}', stderr="")

    runner.calls = calls
    return runner


def complete_task(repo: Path, *, task="T-003", subject="T-003: implement delegated task", commits=1):
    roadmap = repo / "ROADMAP.md"
    roadmap.write_text(roadmap.read_text(encoding="utf-8").replace("- [ ] T-003", "- [x] T-003"), encoding="utf-8")
    for index in range(commits):
        (repo / f"work{index}.txt").write_text("done\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", subject if index == 0 else f"{subject} part {index}")
    status = {"task": task, "status": "done", "summary": "implemented", "checks": ["python -m x"], "commit": git(repo, "rev-parse", "HEAD")}
    (repo / ".autopilot").mkdir(exist_ok=True)
    (repo / ".autopilot" / "status.json").write_text(json.dumps(status), encoding="utf-8")


def test_spec_pins_and_bounds():
    repo = make_repo()
    spec = dg.build_delegation(TASK, repo, max_turns=9999, timeout_seconds=1)
    assert spec["task_id"] == "T-003" and spec["branch"] == "autopilot-test"
    assert spec["max_turns"] == dg.MAX_TURNS_RANGE[1]
    assert spec["timeout_seconds"] == dg.TIMEOUT_RANGE[0]
    prompt = spec["cmd"][spec["cmd"].index("-p") + 1]
    assert "T-003" in prompt and "T-004" not in prompt and "T-002" not in prompt
    assert spec["cmd"][spec["cmd"].index("--max-turns") + 1] == str(dg.MAX_TURNS_RANGE[1])
    assert "Bash(git push:*)" in spec["cmd"] and "Bash(render:*)" in spec["cmd"]
    assert "--dangerously-skip-permissions" not in spec["cmd"]

    for bad in ({**TASK, "human": True}, {**TASK, "done": True}, {**TASK, "id": "T-003; rm -rf /"}):
        try:
            dg.build_delegation(bad, repo)
        except ValueError:
            pass
        else:
            raise AssertionError(f"delegation must refuse {bad}")

    git(repo, "checkout", "-q", "main")
    try:
        dg.build_delegation(TASK, repo)
    except ValueError:
        pass
    else:
        raise AssertionError("delegation must refuse to run on main")


def test_env_scrubs_payg_and_deploy_credentials():
    env = dg.delegated_env({"PATH": "/bin", "ANTHROPIC_API_KEY": "x", "RENDER_API_KEY": "y", "FACTORY_CLAUDE_WORKER_TOKEN": "z"})
    assert env == {"PATH": "/bin"}


def test_done_with_evidence():
    repo = make_repo()
    spec = dg.build_delegation(TASK, repo, max_turns=40, timeout_seconds=900)
    old_key = os.environ.get("ANTHROPIC_API_KEY")
    os.environ["ANTHROPIC_API_KEY"] = "must-not-leak"
    try:
        runner = fake_runner(complete_task)
        evidence = dg.run_delegation(spec, runner=runner)
    finally:
        if old_key is None:
            os.environ.pop("ANTHROPIC_API_KEY", None)
        else:
            os.environ["ANTHROPIC_API_KEY"] = old_key
    call = runner.calls[0]
    assert call["timeout"] == 900 and "ANTHROPIC_API_KEY" not in call["env"]
    assert evidence["result"] == "done", evidence["violations"]
    assert evidence["violations"] == []
    assert len(evidence["commits"]) == 1 and "T-003" in evidence["commits"][0]["subject"]
    assert "ROADMAP.md" in evidence["commits"][0]["files"]
    assert evidence["roadmap_done"] is True and evidence["pushed"] is False
    assert evidence["before"]["protected_refs"] == evidence["after"]["protected_refs"]
    assert evidence["output_tail"].startswith('{"result":"ok"}')

    path = dg.write_evidence(repo, evidence)
    assert json.loads(path.read_text(encoding="utf-8"))["task_id"] == "T-003"
    assert git(repo, "status", "--porcelain") == "", "evidence must stay out of git"

    payload = dg.result_payload(evidence)
    assert payload["task_id"] == payload["pinned_task_id"] == "T-003"
    assert payload["commit"] == evidence["commits"][0]["sha"] and payload["commit_count"] == 1
    assert payload["started_at"] == evidence["started_at"] and payload["started_at"] > 0, "timeline needs the observed start"

    posted = []

    class Response:
        status_code = 200

    os.environ["FACTORY_CLAUDE_WORKER_TOKEN"] = "test-token"
    os.environ["FACTORYOS_URL"] = "https://factory.invalid/"
    try:
        assert dg.report_result(evidence, post=lambda url, **kw: posted.append((url, kw)) or Response()) is True
    finally:
        os.environ.pop("FACTORY_CLAUDE_WORKER_TOKEN", None)
        os.environ.pop("FACTORYOS_URL", None)
    assert posted[0][0] == "https://factory.invalid/api/claude-worker/task-result"
    assert posted[0][1]["headers"]["Authorization"] == "Bearer test-token"
    assert dg.report_result(evidence, post=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no token, no post"))) is False


def assert_failed(behaviour, expected_fragment):
    repo = make_repo()
    spec = dg.build_delegation(TASK, repo)
    evidence = dg.run_delegation(spec, runner=fake_runner(lambda r: behaviour(r)))
    assert evidence["result"] == "failed", evidence
    joined = " | ".join(evidence["violations"])
    assert expected_fragment in joined, joined
    return evidence


def test_violations_fail_closed():
    # Task pinning: agent works on another task.
    assert_failed(lambda r: complete_task(r, task="T-004", subject="T-004: wrong task"), "pinned task is T-003")
    # One task = one commit.
    assert_failed(lambda r: complete_task(r, commits=2), "exactly one task commit")
    # Commit subject must carry the task id.
    assert_failed(lambda r: complete_task(r, subject="misc cleanup"), "does not reference T-003")

    # Done without closing the ROADMAP checkbox.
    def done_without_checkbox(repo):
        complete_task(repo)
        roadmap = repo / "ROADMAP.md"
        roadmap.write_text(roadmap.read_text(encoding="utf-8").replace("- [x] T-003", "- [ ] T-003"), encoding="utf-8")
        git(repo, "commit", "-q", "-am", "T-003: reopen")

    assert_failed(done_without_checkbox, "ROADMAP checkbox")

    # Direct main action: committing onto main.
    def commit_to_main(repo):
        git(repo, "checkout", "-q", "main")
        (repo / "hot.txt").write_text("x\n", encoding="utf-8")
        git(repo, "add", ".")
        git(repo, "commit", "-q", "-m", "T-003: direct main hotfix")
        git(repo, "checkout", "-q", "autopilot-test")
        complete_task(repo)

    assert_failed(commit_to_main, "protected branch main was modified")

    # Ending on main.
    def end_on_main(repo):
        complete_task(repo)
        git(repo, "checkout", "-q", "main")

    assert_failed(end_on_main, "protected branch")

    # Push detected through remote-tracking refs.
    def push(repo):
        complete_task(repo)
        git(repo, "update-ref", "refs/remotes/origin/autopilot-test", "HEAD")

    evidence = assert_failed(push, "push detected")
    assert evidence["pushed"] is True

    # Missing status.json is never treated as success.
    repo = make_repo()
    evidence = dg.run_delegation(dg.build_delegation(TASK, repo), runner=fake_runner(lambda r: None))
    assert evidence["result"] == "failed" and evidence["commits"] == []


def test_timeout_is_bounded():
    repo = make_repo()
    spec = dg.build_delegation(TASK, repo, timeout_seconds=600)

    def runner(cmd, *, timeout, **kwargs):
        assert timeout == 600
        raise subprocess.TimeoutExpired(cmd, timeout, output=b"partial")

    evidence = dg.run_delegation(spec, runner=runner)
    assert evidence["timed_out"] is True and evidence["result"] == "failed"
    assert evidence["exit_code"] is None and "partial" in evidence["output_tail"]
    assert any("600s bound" in v for v in evidence["violations"])


def main():
    test_spec_pins_and_bounds()
    test_env_scrubs_payg_and_deploy_credentials()
    test_done_with_evidence()
    test_violations_fail_closed()
    test_timeout_is_bounded()
    print("Claude delegation adapter tests passed")


if __name__ == "__main__":
    main()
