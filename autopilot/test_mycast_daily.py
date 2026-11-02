"""T-603 MyCast daily episode on the worker: schedule, script validation, generation, publish, orchestration.
No real Claude, GitHub or Telegram calls."""
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from autopilot import mycast_daily as md


def kyiv_ts(y, m, d, hh, mm=0):
    return datetime(y, m, d, hh, mm, tzinfo=md.KYIV).timestamp()


def good_episode():
    line = "Сьогодні говоримо про нові функції моделей і про стартапи, які залучили інвестиції цього тижня. " * 2
    return {"title": "MyCast · 3 листопада 2026",
            "sources": [{"title": "Tech.eu", "url": "https://tech.eu/x", "date": "2026-11-02"}],
            "lines": [["A" if n % 2 == 0 else "B", line] for n in range(14)]}


def fake_cli(stdout, code=0):
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, code, stdout=stdout, stderr="")
    return run, calls


def test_schedule():
    morning = kyiv_ts(2026, 11, 3, 6, 59)
    assert md.due({}, morning) is False  # before 07:00 Kyiv
    at7 = kyiv_ts(2026, 11, 3, 7, 0)
    assert md.due({}, at7) is True
    assert md.due({"delivered_date": "2026-11-03"}, at7) is False
    assert md.due({"attempts": {"2026-11-03": md.MAX_ATTEMPTS}}, at7) is False
    assert md.due({"last_attempt_ts": at7 - 60}, at7) is False  # spacing between attempts
    assert md.due({"last_attempt_ts": at7 - md.RETRY_SPACING_SECONDS}, at7) is True


def test_validate():
    assert md.validate(good_episode()) == []
    bad = good_episode()
    bad["lines"][0] = ["C", "x"]
    assert md.validate(bad)
    bad = good_episode()
    bad["sources"] = [{"title": "x", "url": "http://insecure"}]
    assert md.validate(bad)
    bad = good_episode()
    bad["lines"] = bad["lines"][:3]
    assert md.validate(bad)


def test_generate():
    day = datetime(2026, 11, 3, 7, 5, tzinfo=md.KYIV)
    wrapper = json.dumps({"type": "result", "is_error": False,
                          "result": "Ось сценарій:\n" + json.dumps(good_episode(), ensure_ascii=False)})
    run, calls = fake_cli(wrapper)
    status, episode = md.generate_episode(day, run_cli=run)
    assert status == "ok" and episode["id"] == "mycast-2026-11-03" and episode["hosts"] == md.HOSTS
    cmd = calls[0][0]
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
    assert allowed == ["WebSearch", "WebFetch"] and "Bash" in cmd and "Write" in cmd
    assert "2026-11-03" in cmd[cmd.index("-p") + 1] and "3 листопада 2026" in cmd[cmd.index("-p") + 1]
    limit = '{"type":"result","is_error":true,"api_error_status":429,"api_error":"usage_limit_reached","result":"limit"}'
    assert md.generate_episode(day, run_cli=fake_cli(limit, 1)[0]) == ("limit", None)
    assert md.generate_episode(day, run_cli=fake_cli('{"type":"result","is_error":false,"result":"no json here"}')[0]) == ("failed", None)
    short = good_episode()
    short["lines"] = short["lines"][:2]
    wrapped = json.dumps({"type": "result", "is_error": False, "result": json.dumps(short)})
    assert md.generate_episode(day, run_cli=fake_cli(wrapped)[0])[0] == "failed"


def test_publish_and_wait():
    ep = dict(good_episode(), id="mycast-2026-11-03")
    seen = []

    def gh_fn(*args, input_text=None):
        seen.append(args)
        if args[:2] == ("api", f"repos/{md.REPO_SLUG}/git/ref/heads/main"):
            return 0, "mainsha"
        if args[:2] == ("api", f"repos/{md.REPO_SLUG}/git/ref/heads/{md.BRANCH}"):
            return 1, ""  # branch missing → created
        if "POST" in args:
            return 0, ""
        if args[1].startswith(f"repos/{md.REPO_SLUG}/contents/") and "PUT" not in args:
            return 1, ""  # file not there yet
        if "PUT" in args:
            body = json.loads(input_text)
            assert body["branch"] == md.BRANCH and "sha" not in body
            assert json.loads(__import__("base64").b64decode(body["content"]))["id"] == "mycast-2026-11-03"
            return 0, "newcommitsha"
        return 1, ""
    assert md.publish(ep, gh_fn=gh_fn) == "newcommitsha"
    assert any("POST" in a for a in seen)
    assert any(a[-1].endswith("episodes/2026-11-03.json") or "episodes/2026-11-03.json" in " ".join(a) for a in seen)

    states = iter(['[{"databaseId": 7, "status": "in_progress", "conclusion": ""}]',
                   '[{"databaseId": 7, "status": "completed", "conclusion": "success"}]'])
    assert md.wait_render("sha", gh_fn=lambda *a, **k: (0, next(states)), sleep=lambda s: None, wait_seconds=60) == "7"
    failed = lambda *a, **k: (0, '[{"databaseId": 8, "status": "completed", "conclusion": "failure"}]')
    assert md.wait_render("sha", gh_fn=failed, sleep=lambda s: None, wait_seconds=60) == ""


def test_run_daily_orchestration():
    state_path = Path(tempfile.mkdtemp()) / "mycast.json"
    at = kyiv_ts(2026, 11, 3, 7, 30)
    saved = {n: getattr(md, n) for n in ("generate_episode", "publish", "wait_render", "download_mp3", "deliver", "deliver_gemini")}
    saved_conf = md.relay_tasks.configured
    try:
        md.relay_tasks.configured = lambda: True
        md.generate_episode = lambda day, run_cli=None: ("ok", dict(good_episode(), id="mycast-2026-11-03"))
        md.publish = lambda ep: "sha1"
        md.deliver_gemini = lambda ep: "unavailable"  # no Gemini key yet → Piper path
        md.wait_render = lambda sha: "42"
        md.download_mp3 = lambda run_id, eid: b"ID3audio"
        delivered = []
        md.deliver = lambda ep, audio: delivered.append((ep["id"], audio)) or True
        assert md.run_daily(state_path, now=at) == "delivered"
        assert delivered == [("mycast-2026-11-03", b"ID3audio")]
        assert md.run_daily(state_path, now=at + 3600) == "idle"  # once per day
        # Gemini voices delivered by the server: no render wait, no Piper upload.
        state_path.unlink()
        delivered.clear()
        md.deliver_gemini = lambda ep: "sent"
        md.wait_render = lambda sha: (_ for _ in ()).throw(AssertionError("Piper render must not be awaited"))
        assert md.run_daily(state_path, now=at) == "delivered" and delivered == []
        md.wait_render = lambda sha: "42"
        md.deliver_gemini = lambda ep: "unavailable"
        # A subscription limit does not use up one of the day's attempts.
        state_path.unlink()
        md.generate_episode = lambda day, run_cli=None: ("limit", None)
        assert md.run_daily(state_path, now=at) == "limit"
        assert json.loads(state_path.read_text())["attempts"]["2026-11-03"] == 0
        # Without a FactoryOS connection nothing runs.
        md.relay_tasks.configured = lambda: False
        assert md.run_daily(Path(tempfile.mkdtemp()) / "s.json", now=at) == "idle"
    finally:
        for n, v in saved.items():
            setattr(md, n, v)
        md.relay_tasks.configured = saved_conf


def main():
    test_schedule()
    test_validate()
    test_generate()
    test_publish_and_wait()
    test_run_daily_orchestration()
    print("MyCast daily worker tests passed")


if __name__ == "__main__":
    main()
