"""T-603 MyCast daily episode on the worker: schedule, script validation, generation, publish, orchestration.
No real Claude, GitHub or Telegram calls."""
import json
import subprocess
import tempfile
from datetime import datetime, timezone
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
    bad["sources"] = []
    assert md.validate(bad)
    bad = good_episode()
    bad["lines"] = bad["lines"][:3]
    assert md.validate(bad)


def test_sources_gate():
    day = datetime(2026, 11, 5, 5, 10, tzinfo=md.KYIV)

    def gate(*sources):
        ep = {"sources": [dict(s) for s in sources]}
        return md.check_sources(ep, day), ep["sources"]
    ok = {"title": "TechCrunch: Fal raises", "url": "https://techcrunch.com/2026/11/03/fal", "date": "2026-11-03"}
    problems, srcs = gate(ok)
    assert problems == [] and srcs[0]["status"] == "fresh"                                   # valid case
    assert gate({"title": "No link"})[0] == ["source 1: url missing"]                          # missing URL
    for url in ("http://techcrunch.com/x", "https://localhost/x", "https://exa mple.com/x", "https://user@evil.com/x", "ftp://a.com/x"):
        assert gate(dict(ok, url=url))[0] == ["source 1: malformed url"], url                 # malformed URL
    assert gate(dict(ok, date="2026-11-06"))[0] == ["source 1: dated in the future (2026-11-06)"]  # future-dated
    assert gate(dict(ok, date="05.11.2026"))[0] == ["source 1: date must be YYYY-MM-DD"]
    dup = dict(ok, url="https://www.techcrunch.com/2026/11/03/fal/")
    assert gate(ok, dup)[0] == ["source 2: duplicate url"]                                    # duplicated source
    editorial = {"title": "Висновок ведучих про ціни", "kind": "editorial"}
    problems, srcs = gate(ok, editorial)
    assert problems == [] and srcs[1]["status"] == "editorial"                                # editorial: labelled, allowed
    assert gate(editorial)[0] == ["sources: no dated source from the last week"]             # ...but never counts as evidence
    problems, srcs = gate(ok, dict(ok, url="https://example.com/old", date="2026-10-01"), dict(ok, url="https://example.com/nd", date=""))
    assert problems == [] and [s["status"] for s in srcs] == ["fresh", "stale", "undated"] and srcs[1]["age_days"] == 35
    assert gate(dict(ok, date="2026-09-01"))[0] == ["sources: no dated source from the last week"]
    # Transcript labels say what was checked (link + date), never that the fact is confirmed.
    ep = dict(good_episode(), sources=srcs + [dict(editorial, status="editorial")])
    head = md.transcript_messages(ep)[0]
    assert "дата в межах тижня" in head and "старе, 35 дн." in head and "без дати" in head and "думка ведучих" in head
    assert "факти не перевірені незалежно" in head


def test_latin_names():
    """#235 (baseline #226): brand/model names reach TTS in Latin; hosts' names and other Cyrillic text are untouched."""
    import re as _re
    import subprocess as _sp

    import mycast
    lines = [["A", "Привіт, я Клод. Вчора Оупен Ей-Ай випустила оновлення, а Антропік показав Клод Код."],
             ["B", "А я Джі-Пі-Ті. Джеміні в Ей-Пі-Ай від Гугл, ЧатДжіПіТі і FactoryOS у Телеграм."],
             ["A", "Звичайний текст без назв: телеграма не було, кодова база стабільна."],
             ["B", "Already Latin: OpenAI, Claude Code, Gemini 3.8 Flash, API, SDK."]]
    out, n = md.latinize_names([list(l) for l in lines])
    assert n == 8, n  # Оупен Ей-Ай, Антропік, Клод Код, Джеміні, Ей-Пі-Ай, Гугл, ЧатДжіПіТі, Телеграм
    assert out[0][1] == "Привіт, я Клод. Вчора OpenAI випустила оновлення, а Anthropic показав Claude Code."
    assert out[1][1] == "А я Джі-Пі-Ті. Gemini в API від Google, ChatGPT і FactoryOS у Telegram."
    assert out[2] == lines[2] and out[3] == lines[3]               # non-name Cyrillic and Latin stay as they are
    assert [h for h, _ in out] == ["A", "B", "A", "B"]              # two-host order kept
    assert md.latinize_names(out) == (out, 0)                       # idempotent: no double transliteration
    # Nothing is dropped: removing the names leaves the same words on both sides.
    strip = lambda t: _re.findall(r"[А-Яа-яІіЇїЄєҐґ'’]+", t)  # the Cyrillic words, in order
    names = r"Оу?пен\s*Ей[-\s]?Ай|Антропік|Клод Код|Джеміні|Ей-Пі-Ай|Гугл|ЧатДжіПіТі|Телеграм"
    for (_, before), (_, after) in zip(lines, out):
        assert strip(_re.sub(names, "", before)) == strip(after)
    # The TTS script the server builds keeps the Latin names byte for byte.
    script = "\n".join(f"{mycast.SPEAKER_LABELS[h]}: {t}" for chunk in mycast.episode_chunks(out) for h, t in chunk)
    for name in ("OpenAI", "Anthropic", "Claude Code", "Gemini", "API", "Google", "ChatGPT", "FactoryOS", "Telegram"):
        assert name in script, name
    # Regression on the real 2026-11-05 episode, the one the owner rated 7/10 for Cyrillic names.
    raw = _sp.run(["git", "show", "origin/mycast/daily:docs/prototypes/mycast/episodes/2026-11-05.json"],
                  capture_output=True, text=True).stdout
    if raw:
        real = json.loads(raw)["lines"]
        fixed, count = md.latinize_names(real)
        joined = " ".join(t for _, t in fixed)
        assert count >= 5 and "OpenAI" in joined and "Оупен Ей-Ай" not in joined, count
        assert sum(len(t.split()) for _, t in fixed) <= sum(len(t.split()) for _, t in real)  # names only shrink
    else:
        print("SKIPPED real-episode check: origin/mycast/daily not fetched here")
    # generate_episode applies it before the script is published or voiced.
    day = datetime(2026, 11, 3, 7, 5, tzinfo=md.KYIV)
    ep = good_episode()
    ep["lines"][0] = ["A", "Оупен Ей-Ай і Антропік оголосили нові моделі, а Джеміні отримав оновлення. " * 2]
    wrapper = json.dumps({"type": "result", "is_error": False, "result": json.dumps(ep, ensure_ascii=False)})
    status, episode = md.generate_episode(day, run_cli=fake_cli(wrapper)[0])
    assert status == "ok" and episode["lines"][0][1].startswith("OpenAI і Anthropic оголосили нові моделі, а Gemini")


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

    # sync_branch: an existing branch is merged with main before the episode (the render workflow runs the branch's
    # own copy of the renderer). A conflict is reported as False, so run_daily can name it; a missing branch is fine.
    def url(args):
        return next(a for a in args if a.startswith("repos/"))

    for exists, merge_code, want in ((True, 0, True), (True, 1, False), (False, 0, True)):
        calls = []

        def sync_gh(*args, input_text=None):
            calls.append(args)
            if url(args).endswith("/merges"):
                assert "POST" in args and f"base={md.BRANCH}" in args and "head=main" in args
                return merge_code, ""
            return (0 if exists else 1), ""
        assert md.sync_branch(gh_fn=sync_gh) is want
        assert any(url(a).endswith("/merges") for a in calls) is exists
    assert not any(url(a).endswith("/merges") for a in seen)  # publish itself never merges

    states = iter(['[{"databaseId": 7, "status": "in_progress", "conclusion": ""}]',
                   '[{"databaseId": 7, "status": "completed", "conclusion": "success"}]'])
    assert md.wait_render("sha", gh_fn=lambda *a, **k: (0, next(states)), sleep=lambda s: None, wait_seconds=60) == "7"
    failed = lambda *a, **k: (0, '[{"databaseId": 8, "status": "completed", "conclusion": "failure"}]')
    assert md.wait_render("sha", gh_fn=failed, sleep=lambda s: None, wait_seconds=60) == ""


def test_factory_status():
    repo = Path(tempfile.mkdtemp())
    (repo / "ROADMAP.md").write_text("- [x] T-1 a\n- [ ] [HUMAN] T-2 pair the bot\n- [ ] T-3 Telegram live acceptance\n", encoding="utf-8")
    now = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    merged = json.dumps([
        {"title": "Worker sync: never rebase (#211)", "headRefName": "claude/worker-sync",
         "baseRefName": "main", "mergedAt": "2026-11-11T13:00:00Z"},
        {"title": "Gemini · P3 · Battle Runs: invalid input (#197)", "headRefName": "gemini/issue-175",
         "baseRefName": "main", "mergedAt": "2026-11-11T14:00:00Z"},
        {"title": "Wrong-branch PR", "headRefName": "gemini/x",
         "baseRefName": "autopilot/aws-worker", "mergedAt": "2026-11-11T14:00:00Z"},
        {"title": "Old PR", "headRefName": "claude/old",
         "baseRefName": "main", "mergedAt": "2026-11-08T09:00:00Z"},
    ])
    open_prs = json.dumps([{"title": "#216 AI Hangout concept A", "headRefName": "ccr-abc", "isDraft": False},
                          {"title": "Draft thing", "headRefName": "chatgpt/x", "isDraft": True}])

    def run(cmd, **kw):
        # No git log should be consulted: squash PRs have no merge commit.
        assert cmd[0] == "gh"
        assert "-R" in cmd
        if cmd[cmd.index("--state") + 1] == "merged":
            assert cmd[cmd.index("--base") + 1] == "main"
            return subprocess.CompletedProcess(cmd, 0, stdout=merged, stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=open_prs, stderr="")

    text = md.factory_status(repo, runner=run, now=now)
    assert "злили у main (Claude): Worker sync: never rebase" in text
    assert "злили у main (Gemini): Battle Runs: invalid input" in text
    assert "Wrong-branch" not in text and "Old PR" not in text
    assert "зараз на перевірці у Claude: AI Hangout concept A" in text and "Draft thing" not in text
    assert "у плані на сьогодні: Telegram live acceptance" in text and "pair the bot" not in text
    for code in ("#211", "#216", "T-3", "P3", "#197"):
        assert code not in text, code
    assert "немає даних" in md.factory_status(None)

    def bad_api(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="unavailable")
    fallback = md.factory_status(repo, runner=bad_api, now=now)
    assert "результат невідомий" in fallback and "злиттів у main не було" not in fallback
    assert "у плані на сьогодні" in fallback

    def empty_api(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
    verified_empty = md.factory_status(repo, runner=empty_api, now=now)
    assert "GitHub не показує злитих PR у main" in verified_empty

    full_page = json.dumps([{"title": "Old PR", "headRefName": "claude/old",
                             "baseRefName": "main", "mergedAt": "2026-11-01T12:00:00Z"}] * 100)
    def limited_api(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=full_page if "merged" in cmd else "[]", stderr="")
    truncated = md.factory_status(repo, runner=limited_api, now=now)
    assert "відсутність злиттів у main не підтверджена" in truncated


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
    saved = {n: getattr(md, n) for n in ("generate_episode", "publish", "sync_branch", "wait_render", "download_mp3", "deliver", "deliver_gemini")}
    saved_conf = md.relay_tasks.configured
    try:
        md.relay_tasks.configured = lambda: True
        md.generate_episode = lambda day, run_cli=None, status_text="": ("ok", dict(good_episode(), id="mycast-2026-11-03"))
        md.publish = lambda ep: "sha1"
        md.sync_branch = lambda: True
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
        assert "конфлікт" not in notices[0]
        # The branch could not be merged with main (conflict): the failure notice names the stale renderer.
        state_path.unlink()
        md.sync_branch = lambda: False
        msgs = []
        for n in range(md.MAX_ATTEMPTS):
            assert md.run_daily(state_path, now=at + n * md.RETRY_SPACING_SECONDS, send=lambda t: msgs.append(t) or True) == "failed"
        notices = [m for m in msgs if m.startswith("⚠️")]
        assert len(notices) == 1 and "конфлікт злиття" in notices[0] and "рендер застарілий" in notices[0]
        md.sync_branch = lambda: True
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
    test_sources_gate()
    test_latin_names()
    test_factory_status()
    test_transcript_messages()
    test_run_daily_orchestration()
    print("MyCast daily worker tests passed")


if __name__ == "__main__":
    main()
