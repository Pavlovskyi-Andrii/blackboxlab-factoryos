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
    morning = kyiv_ts(2026, 11, 3, 5, 9)
    assert md.due({}, morning) is False  # before 05:10 Kyiv
    assert md.due({}, kyiv_ts(2026, 11, 3, 4, 30)) is False
    at7 = kyiv_ts(2026, 11, 3, 5, 10)  # first attempt early enough for the 06:00 target (#219)
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
    status, episode = md.generate_episode(day, run_cli=run, status_text="- дорожня карта: 3 задачі виконано")
    assert status == "ok" and episode["id"] == "mycast-2026-11-03" and episode["hosts"] == md.HOSTS
    cmd = calls[0][0]
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
    assert allowed == ["WebSearch", "WebFetch"] and "Bash" in cmd and "Write" in cmd
    prompt = cmd[cmd.index("-p") + 1]
    assert "2026-11-03" in prompt and "3 листопада 2026" in prompt
    assert "- дорожня карта: 3 задачі виконано" in prompt and "750–1100" in prompt and "промпт" in prompt
    assert "ЛАТИНИЦЕЮ" in prompt and "Без номерів задач" in prompt and "3–4" in prompt and "у FactoryOS" in prompt
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


def test_factory_status():
    repo = Path(tempfile.mkdtemp())
    (repo / "ROADMAP.md").write_text("- [x] T-1 a\n- [ ] [HUMAN] T-2 pair the bot\n- [ ] T-3 Telegram live acceptance\n", encoding="utf-8")
    log = ("Merge pull request #211 from owner/claude/worker-sync\x1fWorker sync: never rebase (#211)\x1e"
           "Merge pull request #197 from owner/gemini/issue-175\x1fGemini: Gemini · P3 · Battle Runs: invalid input\x1e")
    prs = json.dumps([{"title": "#216 AI Hangout concept A", "headRefName": "ccr-abc", "isDraft": False},
                      {"title": "Draft thing", "headRefName": "chatgpt/x", "isDraft": True}])

    def run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=log if cmd[0] == "git" else prs, stderr="")
    text = md.factory_status(repo, runner=run)
    assert "вчора зробив(ла) Claude: Worker sync: never rebase" in text
    assert "вчора зробив(ла) Gemini: Battle Runs: invalid input" in text
    assert "зараз на перевірці у Claude: AI Hangout concept A" in text and "Draft thing" not in text
    assert "у плані на сьогодні: Telegram live acceptance" in text and "pair the bot" not in text  # HUMAN skipped
    for code in ("#211", "#216", "T-3", "P3", "#197"):
        assert code not in text, code  # hosts never read out task/PR numbers
    assert "немає даних" in md.factory_status(None)
    broken = lambda cmd, **kw: (_ for _ in ()).throw(OSError("no git"))
    fallback = md.factory_status(repo, runner=broken)  # fail-soft: roadmap plan still there
    assert "нових злиттів" in fallback and "у плані на сьогодні" in fallback


def test_transcript_messages():
    ep = dict(good_episode(), id="mycast-2026-11-03")
    ep["lines"] = ep["lines"] * 8  # long episode: several Telegram messages
    parts = md.transcript_messages(ep)
    assert len(parts) > 1 and all(len(p) <= md.TELEGRAM_TEXT_LIMIT for p in parts)
    assert "https://tech.eu/x" in parts[0] and "2026-11-02" in parts[0] and parts[0].startswith("📝")
    joined = "\n\n".join(parts)
    assert joined.count("Клод:") == joined.count("Джі-Пі-Ті:") == len(ep["lines"]) // 2


def test_run_daily_orchestration():
    state_path = Path(tempfile.mkdtemp()) / "mycast.json"
    at = kyiv_ts(2026, 11, 3, 7, 30)
    saved = {n: getattr(md, n) for n in ("generate_episode", "publish", "wait_render", "download_mp3", "deliver", "deliver_gemini")}
    saved_conf = md.relay_tasks.configured
    try:
        md.relay_tasks.configured = lambda: True
        md.generate_episode = lambda day, run_cli=None, status_text="": ("ok", dict(good_episode(), id="mycast-2026-11-03"))
        md.publish = lambda ep: "sha1"
        md.deliver_gemini = lambda ep: "unavailable"  # no Gemini key yet → Piper path
        md.wait_render = lambda sha: "42"
        md.download_mp3 = lambda run_id, eid: b"ID3audio"
        delivered = []
        md.deliver = lambda ep, audio: delivered.append((ep["id"], audio)) or True
        msgs = []
        assert md.run_daily(state_path, now=at, send=msgs.append) == "delivered"
        assert msgs and msgs[0].startswith("📝")  # transcript + sources follow the audio
        assert md.run_daily(state_path, now=at + 3600, send=msgs.append) == "idle" and len(msgs) == len(md.transcript_messages(good_episode()))
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
        md.generate_episode = lambda day, run_cli=None, status_text="": ("limit", None)
        assert md.run_daily(state_path, now=at) == "limit"
        assert json.loads(state_path.read_text())["attempts"]["2026-11-03"] == 0
        # Without a FactoryOS connection nothing runs.
        # Audio fails on every attempt: text fallback once, one honest failure notice after the last attempt.
        state_path.unlink()
        md.generate_episode = lambda day, run_cli=None, status_text="": ("ok", dict(good_episode(), id="mycast-2026-11-03"))
        md.download_mp3 = lambda run_id, eid: b""
        msgs = []
        for n in range(md.MAX_ATTEMPTS):
            assert md.run_daily(state_path, now=at + n * md.RETRY_SPACING_SECONDS, send=lambda t: msgs.append(t) or True) == "failed"
        notices = [m for m in msgs if m.startswith("⚠️")]
        assert len(notices) == 1 and "не доставлено" in notices[0] and "Текст випуску надіслано" in notices[0]
        assert sum(m.startswith("📝") for m in msgs) == 1  # transcript sent once, not per attempt
        assert md.run_daily(state_path, now=at + 9 * md.RETRY_SPACING_SECONDS, send=msgs.append) == "idle"
        # A broken Telegram notice never breaks the worker loop.
        assert md.notify_owner("x", send=lambda t: (_ for _ in ()).throw(RuntimeError("down"))) is False
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
    test_factory_status()
    test_transcript_messages()
    test_run_daily_orchestration()
    print("MyCast daily worker tests passed")


if __name__ == "__main__":
    main()
