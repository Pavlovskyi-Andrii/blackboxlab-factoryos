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
    (repo / ".gitignore").write_text(".autopilot/status.json\n.autopilot/evidence/\n.autopilot/run.json\n", encoding="utf-8")
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


def test_parent_owned_run_state_visible_during_cli():
    from autopilot import claude_pro_worker as worker

    repo = make_repo()
    seen = {}

    def during(r):
        # While Claude works, status.json is absent but the parent record is live.
        assert not (r / ".autopilot" / "status.json").exists()
        seen.update(dg.read_run_state(r))
        old_repo = worker.REPO
        worker.REPO = r
        try:
            seen["snapshot"] = worker.task_snapshot()
        finally:
            worker.REPO = old_repo
        complete_task(r)

    evidence = dg.run_delegation(dg.build_delegation(TASK, repo), runner=fake_runner(during))
    assert seen["state"] == "running" and seen["task"] == "T-003" and seen["source"] == "parent"
    assert seen["run_id"] == evidence["run_id"]
    task_id, state, detail = seen["snapshot"]
    assert (task_id, state) == ("T-003", "running") and evidence["run_id"] in detail
    final = dg.read_run_state(repo)
    assert final["state"] == "done" and final["commit"] == evidence["commits"][0]["sha"]
    assert final["run_id"] == evidence["run_id"] and final["finished_at"]
    assert git(repo, "status", "--porcelain") == "", "run state must stay out of git"

    # A dead parent never shows as a ghost running task.
    dg.write_run_state(repo, {**final, "state": "running", "pid": 2 ** 22 + 12345})
    old_repo = worker.REPO
    worker.REPO = repo
    try:
        assert worker.task_snapshot()[1] == "stale"
    finally:
        worker.REPO = old_repo

    # CLI that cannot start is a recorded failure, not a crash with a stuck record.
    def missing_cli(cmd, **kwargs):
        raise FileNotFoundError("claude")

    evidence = dg.run_delegation(dg.build_delegation(TASK, make_repo()), runner=missing_cli)
    assert evidence["result"] == "failed" and "could not start" in evidence["output_tail"]


def test_persistent_venv_and_allowed_tools():
    # The agent can run the CLAUDE.md checks headlessly, from a venv that survives reboot.
    spec = dg.build_delegation(TASK, make_repo())
    allowed = spec["cmd"][spec["cmd"].index("--allowedTools") + 1:spec["cmd"].index("--disallowedTools")]
    assert "Bash(python:*)" in allowed and "Edit" in allowed and "Bash(git commit:*)" in allowed
    assert not any("push" in rule or "render" in rule for rule in allowed)

    repo = make_repo()
    assert dg.ensure_venv(repo) == (None, "no requirements.txt")
    (repo / "requirements.txt").write_text("requests\n", encoding="utf-8")
    calls = []

    def fake(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:3] == ["-m", "venv"]:
            (Path(cmd[3]) / "bin").mkdir(parents=True)
            (Path(cmd[3]) / "bin" / "python").write_text("", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    venv, note = dg.ensure_venv(repo, runner=fake)
    assert venv == repo / ".venv" and note == "installed" and len(calls) == 2
    assert dg.ensure_venv(repo, runner=fake) == (venv, "ready") and len(calls) == 2  # cached by hash
    (repo / "requirements.txt").write_text("requests\nfastapi\n", encoding="utf-8")
    assert dg.ensure_venv(repo, runner=fake)[1] == "installed" and len(calls) == 3  # reinstall only
    env = dg.venv_env({"PATH": "/usr/bin"}, venv)
    assert env["PATH"].startswith(str(venv / "bin")) and env["VIRTUAL_ENV"] == str(venv)
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr="no network")
    (repo / ".venv" / ".requirements.sha256").unlink()
    assert dg.ensure_venv(repo, runner=failing) == (None, "pip install failed: no network")


def test_early_cli_failures_are_actionable_and_fail_closed():
    """No real Claude calls: exercise the exact missing-status failure seen on EC2."""
    def run_case(code: int, stdout: str = "", stderr: str = ""):
        repo = make_repo()
        spec = dg.build_delegation(TASK, repo)
        def runner(cmd, **_kw):
            return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr=stderr)
        return dg.run_delegation(spec, runner=runner)

    missing = run_case(0, stdout='{"type":"result","is_error":false,"result":"done"}')
    assert missing["result"] == "failed", missing
    assert missing["status"]["error_category"] == "missing_status"
    assert "exit=0" in missing["status"]["summary"]

    logged_out = run_case(1, stdout='{"is_error":true,"result":"Not logged in; please login"}')
    assert logged_out["result"] == "blocked", logged_out
    assert logged_out["status"]["error_category"] == "subscription_auth_required"
    assert "claude auth status" in logged_out["status"]["need"]

    rate_limited = run_case(1, stderr="Rate limit exceeded")
    assert rate_limited["result"] == "blocked"
    assert rate_limited["status"]["error_category"] == "subscription_limit"

    permission = run_case(1, stderr="Tool permission denied")
    assert permission["result"] == "blocked"
    assert permission["status"]["error_category"] == "permission_policy"

    generic = run_case(2, stderr="Unexpected CLI error")
    assert generic["result"] == "failed"
    assert generic["status"]["error_category"] == "missing_status"
    assert "exit=2" in generic["status"]["summary"]

    secret = "sk-ant-" + "A" * 24
    token = "github_pat_" + "B" * 24
    redacted = run_case(1, stderr=f"Unknown failure; Authorization: Bearer verysecrettoken {secret} {token} access_token=privatesession")
    tail = redacted["output_tail"]
    assert "verysecrettoken" not in tail and secret not in tail
    assert token not in tail and "privatesession" not in tail
    assert "[REDACTED]" in tail
    # Never leak untrusted CLI text into Relay/Telegram owner summary.
    payload = dg.result_payload(redacted)
    assert "verysecrettoken" not in payload["summary"]
    assert "privatesession" not in payload["summary"]

    # If CLI writes DONE and exits nonzero, the evidence remains failed.
    repo = make_repo()
    spec = dg.build_delegation(TASK, repo)
    def invalid_success(cmd, *, cwd, **_kw):
        complete_task(Path(cwd))
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="process failed")
    mismatch = dg.run_delegation(spec, runner=invalid_success)
    assert mismatch["result"] == "failed"
    assert any("CLI exited nonzero" in violation for violation in mismatch["violations"])

    # Normal verified happy path is unchanged.
    success_repo = make_repo()
    success = dg.run_delegation(dg.build_delegation(TASK, success_repo), runner=fake_runner(complete_task))
    assert success["result"] == "done" and success["violations"] == []


def main():
    test_early_cli_failures_are_actionable_and_fail_closed()
    test_persistent_venv_and_allowed_tools()
    test_spec_pins_and_bounds()
    test_env_scrubs_payg_and_deploy_credentials()
    test_done_with_evidence()
    test_violations_fail_closed()
    test_timeout_is_bounded()
    test_parent_owned_run_state_visible_during_cli()
    print("Claude delegation adapter tests passed")


if __name__ == "__main__":
    main()
