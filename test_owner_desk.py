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


def test_secret_scrubbing():
    bot = "123456789:" + "A" * 35
    text = od.scrub_secrets(f"мой токен {bot} и ghp_{'b' * 20} и AKIA{'C' * 16} password=hunter2hunter2")
    assert bot not in text and "ghp_" not in text and "AKIA" not in text and "hunter2" not in text, text
    assert text.count("[скрыто]") == 4, text
    # Variable names in the runbooks are not secrets and must survive.
    assert od.scrub_secrets("FACTORY_TELEGRAM_BOT_TOKEN = значение") == "FACTORY_TELEGRAM_BOT_TOKEN = значение"


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
                                 status_fn=lambda: {"T-506": {"state": "done", "detail": "ok"}},
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


def main():
    test_every_open_human_task_has_a_runbook()
    test_runbook_shape()
    test_secret_scrubbing()
    test_question_queue()
    test_routes_and_auth()
    print("Owner desk tests passed: runbooks cover every open HUMAN task, queue, scrubbing, auth")


if __name__ == "__main__":
    main()
