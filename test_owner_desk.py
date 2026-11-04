"""Owner desk regression: runbook coverage/shape, question queue, secret scrubbing, route auth.

Zero spend, no network: routes are called directly through a capturing fake app.
"""
import re
import tempfile
from pathlib import Path

from fastapi import HTTPException

import owner_desk as od

ROOT = Path(__file__).resolve().parent


def test_every_open_human_task_has_a_runbook():
    roadmap = (ROOT / "ROADMAP.md").read_text(encoding="utf-8")
    open_human = set(re.findall(r"^- \[ \] \[HUMAN\] (T-[A-Za-z0-9-]+)", roadmap, re.M))
    assert open_human, "no open HUMAN tasks parsed"
    missing = open_human - set(od.RUNBOOK_BY_ID)
    assert not missing, f"HUMAN tasks without an owner runbook: {sorted(missing)}"


def test_runbook_shape():
    ids = set()
    for book in od.RUNBOOKS:
        assert book["id"] not in ids
        ids.add(book["id"])
        for key in ("title", "why", "time", "done"):
            assert str(book.get(key) or "").strip(), (book["id"], key)
        assert book["steps"], book["id"]
        step_ids = set()
        for step in book["steps"]:
            assert step["id"] not in step_ids and re.fullmatch(r"[a-z0-9-]+", step["id"]), (book["id"], step["id"])
            step_ids.add(step["id"])
            assert step["title"].strip() and step["do"] and all(d.strip() for d in step["do"]), (book["id"], step["id"])
            assert str(step.get("check") or "").strip(), (book["id"], step["id"])
            for branch in step.get("if") or []:
                assert branch["when"].strip() and branch["then"].strip(), (book["id"], step["id"])
        text = od.runbook_text(book)
        assert book["id"] in text and "Проверка:" in text
    # Secrets are never requested on the site: every step that mentions a token says where it goes.
    for book in od.RUNBOOKS:
        for step in book["steps"]:
            joined = " ".join(step["do"])
            if "токен" in joined.lower() and "секрет" in joined.lower():
                assert "никогда не отправляйте" in joined.lower(), (book["id"], step["id"])


_CYRILLIC = re.compile(r"[\u0400-\u04ff]")
_RU_ONLY = re.compile(r"[ыэъёЫЭЪЁ]")
_KEEP = re.compile(r"FACTORY_[A-Z_]+|@BotFather|/mybots|/newbot|/pair|gh auth [a-z]+|blackboxlab-factoryos|blackboxlab7")
_NEVER_SEND = {"ru": "никогда не отправляйте", "en": "never send", "uk": "ніколи не надсилайте"}
_SECRET_WORDS = {"ru": ("токен", "секрет"), "en": ("token", "secret"), "uk": ("токен", "секрет")}


def _texts(book):
    yield from (book["title"], book["why"], book["time"], book["done"])
    for step in book["steps"]:
        yield from (step["title"], step["check"], *step["do"])
        for branch in step.get("if") or []:
            yield from (branch["when"], branch["then"])


def test_runbooks_localized_en_uk_ru():
    for lang in od.RUNBOOK_LANGS:
        for src in od.RUNBOOKS:
            book = od.localize_runbook(src, lang)
            assert book["lang"] == lang, (lang, src["id"])
            assert [s["id"] for s in book["steps"]] == [s["id"] for s in src["steps"]], (lang, src["id"])
            for step, orig in zip(book["steps"], src["steps"]):
                assert len(step["do"]) == len(orig["do"]) and len(step.get("if") or []) == len(orig.get("if") or []), (lang, src["id"], step["id"])
            texts = list(_texts(book))
            assert all(str(t).strip() for t in texts), (lang, src["id"])
            if lang != "ru":
                assert list(_texts(book)) != list(_texts(src)), (lang, src["id"])
            if lang == "en":
                bad = [t for t in texts if _CYRILLIC.search(t)]
                assert not bad, (src["id"], bad[:2])
            if lang == "uk":
                bad = [t for t in texts if _RU_ONLY.search(t)]
                assert not bad, (src["id"], bad[:2])
            # Variable names, commands and product handles are never translated.
            assert sorted(_KEEP.findall(" ".join(texts))) == sorted(_KEEP.findall(" ".join(_texts(src)))), (lang, src["id"])
            for step in book["steps"]:
                joined = " ".join(step["do"]).lower()
                if all(w in joined for w in _SECRET_WORDS[lang]):
                    assert _NEVER_SEND[lang] in joined, (lang, src["id"], step["id"])
    # Every status line exists in every language with the same placeholders.
    for lang in od.RUNBOOK_LANGS:
        assert set(od.STATUS_DETAILS[lang]) == set(od.STATUS_DETAILS["ru"]), lang
        for key, text in od.STATUS_DETAILS[lang].items():
            assert re.findall(r"{\w+}", text) == re.findall(r"{\w+}", od.STATUS_DETAILS["ru"][key]), (lang, key)
    got = od.status_detail({"state": "info", "detail_key": "prod_sha", "args": {"sha": "abc1234"}}, "en")
    assert got == {"state": "info", "detail": "Now in production: abc1234"}, got
    assert od.status_detail({"state": "todo", "detail_key": "waits", "args": {"task": "T-520"}}, "uk")["detail"] == "Чекає на T-520"
    assert od.status_detail({"state": "done", "detail": "plain"}, "en") == {"state": "done", "detail": "plain"}


def test_secret_scrubbing():
    bot = "123456789:" + "A" * 35
    ghp = "ghp_" + "b" * 36
    gh_pat = "github_pat_11ABCDEFG0123456789_" + "c" * 50
    google_key = "AIzaSyA" + "d" * 32
    bearer_hdr = "Bearer " + "e" * 30
    text = od.scrub_secrets(
        f"мой токен {bot} и {ghp} и {gh_pat} и {google_key} и {bearer_hdr} и AKIA{'C' * 16} password=hunter2hunter2"
    )
    for secret in (bot, ghp, gh_pat, google_key, "eeeeeeee", "AKIA", "hunter2"):
        assert secret not in text, f"{secret} leaked in {text}"
    assert text.count("[скрыто]") == 7, text

    # Normal text and runbook variable names survive without corruption
    normal_text = "Обычный текст: используйте FACTORY_TELEGRAM_BOT_TOKEN, FACTORY_GEMINI_API_KEY, ghp_ и Bearer в заголовках."
    assert od.scrub_secrets(normal_text) == normal_text


def test_question_queue():
    clock = {"t": 1000.0}
    store = od.QuestionStore(Path(tempfile.mkdtemp()) / "q.json", clock=lambda: clock["t"])
    try:
        store.create("T-999", "", "", "что?")
        raise AssertionError("unknown task accepted")
    except ValueError:
        pass
    try:
        store.create("T-506", "render", "", "   ")
        raise AssertionError("empty question accepted")
    except ValueError:
        pass
    q = store.create("T-506", "nope", "x" * 2000, "Где взять токен? 123456789:" + "Z" * 35)
    assert q["step_id"] == "" and len(q["quote"]) == od.QUOTE_MAX and "[скрыто]" in q["question"]
    claimed = store.claim("w1")
    assert claimed["id"] == q["id"] and claimed["status"] == "answering"
    assert store.claim("w2") is None
    # Lease expiry returns a stuck question to the queue.
    clock["t"] += od.CLAIM_LEASE_SECONDS + 1
    again = store.claim("w2")
    assert again and again["id"] == q["id"]
    assert store.finish(q["id"], "requeue", "")["status"] == "pending"
    store.claim("w1")
    done = store.finish(q["id"], "answered", "1. Откройте Render…")
    assert done["status"] == "answered" and done["answer"].startswith("1.")
    try:
        store.finish(q["id"], "answered", "again")
        raise AssertionError("finished twice")
    except LookupError:
        pass
    for _ in range(od.MAX_OPEN_QUESTIONS):
        store.create("T-520", "", "", "?")
    try:
        store.create("T-520", "", "", "?")
        raise AssertionError("open question limit not enforced")
    except OverflowError:
        pass
    assert all("claimed_ts" not in item for item in store.list())


class _FakeApp:
    def __init__(self):
        self.routes = {}

    def _register(self, method, path):
        def deco(fn):
            self.routes[(method, path)] = fn
            return fn
        return deco

    def get(self, path):
        return self._register("GET", path)

    def post(self, path):
        return self._register("POST", path)


class _Req:
    def __init__(self, role="", worker=False):
        self.role, self.worker = role, worker


def test_routes_and_auth():
    app, sent = _FakeApp(), []
    store = od.QuestionStore(Path(tempfile.mkdtemp()) / "q.json")
    od.install_owner_desk_routes(app, store, lambda r: {"role": r.role} if r.role else None,
                                 authorize_worker=lambda r: r.worker,
                                 status_fn=lambda: {"T-506": {"state": "done", "detail": "ok"},
                                                    "T-521": {"state": "blocked", "detail_key": "waits", "args": {"task": "T-520"}}},
                                 redact_fn=lambda s: s.replace("SERVERSECRET", "[redacted]"),
                                 notify_owner=sent.append)
    desk, ask = app.routes[("GET", "/api/factory/owner-desk")], app.routes[("POST", "/api/factory/owner-desk/questions")]
    claim, answer = app.routes[("POST", "/api/factory/owner-desk/worker/claim")], app.routes[("POST", "/api/factory/owner-desk/worker/answer")]
    owner, viewer, worker = _Req("owner"), _Req("viewer"), _Req(worker=True)
    for fn, args in ((desk, (viewer,)), (ask, (od.OwnerQuestionRequest(task_id="T-506", question="?"), viewer))):
        try:
            fn(*args)
            raise AssertionError("non-owner allowed")
        except HTTPException as exc:
            assert exc.status_code == 403
    try:
        claim(od.WorkerClaimRequest(worker_id="w"), owner)
        raise AssertionError("owner cookie must not act as worker")
    except HTTPException as exc:
        assert exc.status_code == 401
    data = desk(owner)
    by_id = {b["id"]: b for b in data["runbooks"]}
    assert by_id["T-506"]["status"]["state"] == "done" and by_id["T-520"]["status"]["state"] == "unknown"
    assert data["lang"] == "ru" and by_id["T-506"]["title"] == od.RUNBOOK_BY_ID["T-506"]["title"]
    assert by_id["T-521"]["status"] == {"state": "blocked", "detail": "Ждёт T-520"}
    for lang, title in (("en", "Connect the owner's Telegram bot"), ("uk", "Підключити Telegram-бота власника"), ("xx", od.RUNBOOK_BY_ID["T-506"]["title"])):
        loc = {b["id"]: b for b in desk(owner, lang)["runbooks"]}
        assert loc["T-506"]["title"] == title, (lang, loc["T-506"]["title"])
    assert {b["id"]: b for b in desk(owner, "en")["runbooks"]}["T-521"]["status"]["detail"] == "Waiting for T-520"
    made = ask(od.OwnerQuestionRequest(task_id="T-506", step_id="render", quote="Add Environment Variable",
                                       question="Где кнопка? SERVERSECRET"), owner)["question"]
    assert "[redacted]" in made["question"]
    got = claim(od.WorkerClaimRequest(worker_id="claude-ec2"), worker)
    assert got["question"]["id"] == made["id"] and "T-506" in got["runbook_text"]
    assert answer(od.WorkerAnswerRequest(id=made["id"], outcome="answered", answer="Вот так."), worker)["status"] == "answered"
    assert sent and "T-506" in sent[0]
    assert claim(od.WorkerClaimRequest(worker_id="claude-ec2"), worker) == {"question": None}
    try:
        answer(od.WorkerAnswerRequest(id=made["id"], outcome="bogus"), worker)
        raise AssertionError("bad outcome accepted")
    except HTTPException as exc:
        assert exc.status_code == 400
    # A failing status source never breaks the desk.
    app2 = _FakeApp()
    od.install_owner_desk_routes(app2, store, lambda r: {"role": "owner"}, authorize_worker=lambda r: False,
                                 status_fn=lambda: 1 / 0)
    assert app2.routes[("GET", "/api/factory/owner-desk")](owner)["runbooks"][0]["status"]["state"] == "unknown"


def test_selftest_round_trip():
    clock = {"t": 1_800_000_000.0}
    store = od.QuestionStore(Path(tempfile.mkdtemp()) / "q.json", clock=lambda: clock["t"])
    app, sent = _FakeApp(), []
    od.install_owner_desk_routes(app, store, lambda r: {"role": r.role} if r.role else None,
                                 authorize_worker=lambda r: r.worker, status_fn=lambda: {}, notify_owner=sent.append)
    selftest = app.routes[("POST", "/api/factory/owner-desk/worker/selftest")]
    claim = app.routes[("POST", "/api/factory/owner-desk/worker/claim")]
    answer = app.routes[("POST", "/api/factory/owner-desk/worker/answer")]
    worker = _Req(worker=True)
    try:
        selftest(_Req("owner"))
        raise AssertionError("owner session must not trigger the worker self-test")
    except HTTPException as exc:
        assert exc.status_code == 401
    first = selftest(worker)
    assert first["queued"] is True
    assert selftest(worker)["queued"] is False  # only one probe in flight
    assert store.list() == []  # never shown to the owner
    got = claim(od.WorkerClaimRequest(worker_id="w"), worker)
    assert got["question"]["task_id"] == od.SELFTEST_TASK
    answer(od.WorkerAnswerRequest(id=first["id"], outcome="answered", answer="self-test ok"), worker)
    assert sent and sent[-1].startswith("✅ Круговая проверка") and "нет" in sent[-1], sent
    # An owner question waiting over an hour is called out in the next round-trip message.
    real = store.create("T-520", "", "", "Где blogId?")
    # created_at uses the wall clock; move the store clock past the stale threshold
    clock["t"] = od.datetime.fromisoformat(real["created_at"]).timestamp() + od.STALE_QUESTION_SECONDS + 60
    second = selftest(worker)
    claimed = claim(od.WorkerClaimRequest(worker_id="w"), worker)["question"]
    assert claimed["task_id"] == "T-520"  # owner questions keep their place ahead of the probe
    nxt = claim(od.WorkerClaimRequest(worker_id="w"), worker)["question"]  # T-520 stays open (answering)
    assert nxt["id"] == second["id"], nxt
    answer(od.WorkerAnswerRequest(id=second["id"], outcome="answered", answer="ok"), worker)
    assert "1" in sent[-1] and "⚠️" in sent[-1] and "T-520" in sent[-1], sent[-1]


def main():
    test_every_open_human_task_has_a_runbook()
    test_runbook_shape()
    test_runbooks_localized_en_uk_ru()
    test_secret_scrubbing()
    test_question_queue()
    test_routes_and_auth()
    test_selftest_round_trip()
    print("Owner desk tests passed: runbooks cover every open HUMAN task, EN/UK/RU runbooks, queue, scrubbing, auth")


if __name__ == "__main__":
    main()
