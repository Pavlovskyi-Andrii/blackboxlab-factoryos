"""T-536-F runner-side safe operator controls regression.

The runner only turns owner commands into "pause before the next task", "resume" or "release
the hold on the task I am holding". Retries for other tasks and unknown actions are rejected,
lost acks never apply a command twice, and an unreachable FactoryOS keeps the last pause level.
"""
import os
import pathlib
import tempfile
from unittest import mock

from autopilot import autopilot as ap
from autopilot import control


class Response:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def feed(*commands, paused=False):
    return {"paused": paused, "commands": [{"id": cid, "action": action, "task_id": task} for cid, action, task in commands]}


def decide_checks():
    unreachable = control.decide(None, paused=True, held_task="T-1")
    assert unreachable == {"paused": True, "retry": "", "acks": []}, "unreachable FactoryOS must keep the last pause level"

    paused = control.decide(feed(("c1", "pause", ""), paused=True), paused=False, held_task="")
    assert paused["paused"] is True and paused["retry"] == "" and paused["acks"] == [("c1", "applied", "paused before the next task")]

    retry = control.decide(feed(("c2", "retry", "T-3")), paused=False, held_task="T-3")
    assert retry["retry"] == "T-3" and retry["acks"][0][:2] == ("c2", "applied")

    other = control.decide(feed(("c3", "retry", "T-4")), paused=False, held_task="T-3")
    assert other["retry"] == "" and other["acks"][0][:2] == ("c3", "rejected"), "retry of a task the runner does not hold must be rejected"
    idle = control.decide(feed(("c4", "retry", "T-3")), paused=False, held_task="")
    assert idle["retry"] == "" and idle["acks"][0][:2] == ("c4", "rejected"), "retry without a held task must be rejected"

    for action in ("force_push", "push", "checkout_main", "deploy", "publish", "approve_publish", "", None):
        bad = control.decide({"paused": False, "commands": [{"id": "c5", "action": action, "task_id": "T-3"}]}, paused=False, held_task="T-3")
        assert bad["retry"] == "" and bad["acks"] == [("c5", "rejected", "unsupported action")], f"{action!r} must be rejected"

    decided = {"c2": ("applied", "released hold on T-3")}
    again = control.decide(feed(("c2", "retry", "T-3")), paused=False, held_task="T-3", decided=decided)
    assert again["retry"] == "" and again["acks"] == [("c2", "applied", "released hold on T-3")], "a lost ack must not retry twice"

    junk = control.decide({"paused": False, "commands": ["x", {"action": "retry"}]}, paused=True, held_task="T-3")
    assert junk == {"paused": False, "retry": "", "acks": []}


def transport_checks():
    with mock.patch.dict(os.environ, {"FACTORY_CLAUDE_WORKER_TOKEN": "", "FACTORYOS_URL": ""}):
        assert control.configured() is False and control.fetch(get=lambda *a, **k: 1 / 0) is None
        assert control.ack("c1", "applied", post=lambda *a, **k: 1 / 0) is False
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return Response(200, feed(("c1", "pause", ""), paused=True))

    with mock.patch.dict(os.environ, {"FACTORY_CLAUDE_WORKER_TOKEN": "worker-fixture", "FACTORYOS_URL": "https://factory.example/"}):
        assert control.fetch(get=get)["paused"] is True
        assert calls[0][0] == "https://factory.example/api/claude-worker/control"
        assert calls[0][1]["headers"] == {"Authorization": "Bearer worker-fixture"}
        assert control.fetch(get=lambda *a, **k: Response(401, {"detail": "no"})) is None
        assert control.fetch(get=lambda *a, **k: Response(200, {"paused": "yes", "commands": []})) is None
        assert control.fetch(get=lambda *a, **k: (_ for _ in ()).throw(OSError("offline"))) is None
        posted = []
        assert control.ack("c1", "applied", "x" * 999, post=lambda url, **kw: posted.append((url, kw)) or Response(200)) is True
        assert posted[0][0].endswith("/api/claude-worker/control/ack") and len(posted[0][1]["json"]["detail"]) == 300
        assert set(posted[0][1]["json"]) == {"command_id", "outcome", "detail"}


def loop_checks():
    acks = []
    decided = {}
    decision = ap.poll_control(False, "T-3", decided, fetch=lambda: feed(("c1", "retry", "T-3"), ("c2", "pause", ""), paused=True),
                               ack=lambda *a: acks.append(a))
    assert decision["retry"] == "T-3" and decision["paused"] is True and [a[:2] for a in acks] == [("c1", "applied"), ("c2", "applied")]
    assert set(decided) == {"c1", "c2"}
    acks.clear()
    replay = ap.poll_control(True, "T-3", decided, fetch=lambda: feed(("c1", "retry", "T-3"), paused=True), ack=lambda *a: acks.append(a))
    assert replay["retry"] == "" and acks == [("c1", "applied", "released hold on T-3")], "re-delivered retry must only be re-acked"


def run_loop(*, branch_sequence, control_feed, daemon=False):
    """Drive autopilot.main with git, Claude and network replaced by fakes."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="factoryos-control-loop-"))
    roadmap = root / "ROADMAP.md"
    roadmap.write_text("## v\n- [ ] [HUMAN] T-1 Publish for real\n- [ ] T-2 Safe task\n", encoding="utf-8")
    branches = iter(branch_sequence)
    agent_calls, messages = [], []
    patches = [
        mock.patch.object(ap, "ROADMAP", roadmap),
        mock.patch.object(ap, "next_safe_task", lambda path=roadmap, operator="", skip=frozenset(), _real=ap.next_safe_task: _real(path, operator, skip)),
        mock.patch.object(ap, "STATUS", root / ".autopilot" / "status.json"),
        mock.patch.object(ap, "ANSWERS", root / ".autopilot" / "answers.md"),
        mock.patch.object(ap, "REPO", root),
        mock.patch.object(ap, "DAEMON_MODE", daemon),
        mock.patch.object(ap, "current_branch", lambda: next(branches)),
        mock.patch.object(ap, "sync_branch", lambda branch: None),
        mock.patch.object(ap, "commits_ahead", lambda branch: 0),
        mock.patch.object(ap, "push_branch", lambda branch: (_ for _ in ()).throw(AssertionError("must not push"))),
        mock.patch.object(ap, "run_agent", lambda target: agent_calls.append(target["id"]) or {"task": target["id"], "status": "blocked"}),
        mock.patch.object(ap, "send", messages.append),
        mock.patch.object(ap.control, "fetch", lambda: control_feed),
        mock.patch.object(ap.control, "ack", lambda *a, **k: True),
    ]
    for p in patches:
        p.start()
    try:
        try:
            code = ap.main()
        except RuntimeError as exc:
            code = str(exc)
    finally:
        for p in patches:
            p.stop()
    status = (root / ".autopilot" / "status.json")
    return code, agent_calls, messages, status.read_text(encoding="utf-8") if status.exists() else ""


def main_loop_checks():
    # Paused before any task: nothing runs, status says paused.
    code, calls, messages, status = run_loop(branch_sequence=["autopilot-ci"], control_feed=feed(("p1", "pause", ""), paused=True))
    assert code == 5 and calls == [] and '"paused"' in status and any("paused" in m for m in messages), (code, calls, status)

    # Retry for the HUMAN publish task is rejected; the safe task runs on the dedicated branch only.
    code, calls, _, _ = run_loop(branch_sequence=["autopilot-ci", "autopilot-ci"], control_feed=feed(("r1", "retry", "T-1")))
    assert code == 2 and calls == ["T-2"], (code, calls)

    # Controls can never start a task on main: refused at startup and if the branch changes later.
    code, calls, _, _ = run_loop(branch_sequence=["main"], control_feed=feed(("r2", "resume", "")))
    assert "main/master" in str(code) and calls == [], (code, calls)
    code, calls, _, _ = run_loop(branch_sequence=["autopilot-ci", "main"], control_feed=feed(("r3", "retry", "T-2")))
    assert "Branch changed" in str(code) and calls == [], (code, calls)


def main():
    decide_checks()
    transport_checks()
    loop_checks()
    main_loop_checks()
    print("Autopilot safe operator control tests passed")


if __name__ == "__main__":
    main()
