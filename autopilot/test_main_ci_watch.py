"""FO-09 main CI watch: python -m autopilot.test_main_ci_watch"""
import json
import pathlib
import tempfile

try:
    from . import main_ci_watch as w
except ImportError:
    import main_ci_watch as w


def run(name, conclusion, sha, status="completed", event="push", title="PR title (#1)"):
    return {"databaseId": 1, "workflowName": name, "status": status, "conclusion": conclusion, "event": event,
            "headSha": sha, "displayTitle": title, "url": "https://github.com/x/actions/runs/1"}


def test_red_once_then_green_once():
    path = pathlib.Path(tempfile.mkdtemp()) / "watch.json"
    sent, runs, calls = [], [], []

    def gh(*args):
        calls.append(args)
        assert "--branch" in args and args[args.index("--branch") + 1] == "main"
        return 0, json.dumps(runs)

    def send(text):
        sent.append(text)
        return True

    t = 1_000_000.0
    runs[:] = [run("FactoryOS CI", "success", "aaa")]
    assert w.run_once(path, gh_fn=gh, send=send, now=t) == "checked" and sent == []
    assert w.run_once(path, gh_fn=gh, send=send, now=t + 60) == "idle" and len(calls) == 1   # one read per 10 min
    # main goes red: one message; the same red commit is never told twice.
    runs[:] = [run("FactoryOS CI", "in_progress", "ccc", status="in_progress"), run("FactoryOS CI", "failure", "bbb"),
               run("FactoryOS CI", "success", "aaa")]
    w.run_once(path, gh_fn=gh, send=send, now=t + 700)
    assert len(sent) == 1 and sent[0].startswith("🔴 CI на main упал: FactoryOS CI") and "bbb" in sent[0]
    w.run_once(path, gh_fn=gh, send=send, now=t + 1400)
    assert len(sent) == 1
    # a newer red commit is a new message; a PR-event run or a running one does not count.
    runs[:] = [run("FactoryOS CI", "success", "zzz", event="pull_request"), run("FactoryOS CI", "timed_out", "ddd")]
    w.run_once(path, gh_fn=gh, send=send, now=t + 2100)
    assert len(sent) == 2 and "ddd" in sent[1]
    # green again: exactly one message, then quiet.
    runs[:] = [run("FactoryOS CI", "success", "eee")]
    w.run_once(path, gh_fn=gh, send=send, now=t + 2800)
    w.run_once(path, gh_fn=gh, send=send, now=t + 3500)
    assert len(sent) == 3 and sent[2].startswith("🟢 CI на main снова зелёный") and "eee" in sent[2]


def test_failed_send_is_retried_and_github_errors_are_silent():
    path = pathlib.Path(tempfile.mkdtemp()) / "watch.json"
    outbox, ok = [], [False]
    send = lambda text: outbox.append(text) or ok[0]
    gh = lambda *a: (0, json.dumps([run("FactoryOS CI", "failure", "bbb")]))
    w.run_once(path, gh_fn=gh, send=send, now=1_000_000)
    ok[0] = True
    w.run_once(path, gh_fn=gh, send=send, now=1_000_700)                    # Telegram was down: tell it again
    w.run_once(path, gh_fn=gh, send=send, now=1_001_400)
    assert len(outbox) == 2
    quiet = []
    for bad in ((1, ""), (0, "not json"), (0, "{}")):
        p = pathlib.Path(tempfile.mkdtemp()) / "w.json"
        assert w.run_once(p, gh_fn=lambda *a, bad=bad: bad, send=quiet.append, now=1_000_000) == "unavailable"
    assert quiet == []                                                       # no read → no claim either way


if __name__ == "__main__":
    test_red_once_then_green_once()
    test_failed_send_is_retried_and_github_errors_are_silent()
    print("main CI watch tests passed")
