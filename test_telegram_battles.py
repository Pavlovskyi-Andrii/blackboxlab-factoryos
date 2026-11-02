"""T-587 Telegram Battle controls regression (no live token, network, spend or messages).

Deterministic fixture: one Battle Run with two completed candidate chains and one unfinished chain, a judge review,
and real-shaped outcome snapshots. The paired Telegram chat sees the battle summary, the candidate chains and the
factual metrics, and can only approve/reject. Nothing publishes, unsafe callbacks are refused and the human publish
approval stays in place.
"""
import asyncio
import json
import os
import sqlite3
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-telegram-battles-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

from battle_runs import BattleError, BattleStore, _sha  # noqa: E402
from relay import RelayStore, relay_handle_telegram_update  # noqa: E402
from telegram_battles import PUBLISH_GATE, BattleTelegram  # noqa: E402

CHAT = "4242"
ROLE_BOARD = {
    "operators": [{"id": "auto"}, {"id": "claude", "model": "claude-x", "kind": "runner", "status": "online"},
                  {"id": "gemini", "model": "gemini-x", "kind": "api", "status": "online"},
                  {"id": "chatgpt", "model": "gpt-x", "kind": "api", "status": "online"}],
    "roles": [{"id": r, "label": r.title(), "operators": ["auto", "claude", "gemini", "chatgpt"], "runtime_operator": "claude"}
              for r in ("scout", "scriptwriter", "reviewer")],
}
SCRIPT_A = "Hook: your phone already knows you. On-device models never upload your words."
SCRIPT_B = "Hook: what if AI ran without the cloud? Local models keep data on the device."
SNAPSHOTS = {
    "pub-a": {"id": "snap-a", "captured_at": "2026-11-01T10:00:00+00:00", "source": "metricool",
              "metrics": {"views": 1200, "likes": 90, "ctr_pct": 4.5}},
    "pub-b": {"id": "snap-b", "captured_at": "2026-11-01T10:00:00+00:00", "source": "metricool", "metrics": {"views": 800}},
}


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


class Bot:
    def __init__(self):
        self.calls = []

    def __call__(self, method, payload=None):
        self.calls.append((method, payload or {}))
        return {"ok": True}

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]

    def answers(self):
        return [p.get("text", "") for m, p in self.calls if m == "answerCallbackQuery"]


def keyboard_data(payload):
    return [b["callback_data"] for row in (payload.get("reply_markup") or {}).get("inline_keyboard") or [] for b in row]


def callback(data, chat=CHAT):
    return {"update_id": 1, "callback_query": {"id": "cb", "data": data, "from": {"language_code": "ru"},
                                               "message": {"chat": {"id": int(chat), "type": "private"}}}}


def message(text):
    return {"update_id": 2, "message": {"chat": {"id": int(CHAT), "type": "private"}, "text": text, "message_id": 2}}


def seed(store, role_board, judge="chatgpt"):
    battle, _ = store.create({
        "kind": "content", "brief": "60-second explainer: why on-device models protect privacy.", "idempotency_key": "tg-battle-1",
        "chains": [
            {"label": "Claude script", "steps": [{"role": "scout", "operator": "claude"}, {"role": "scriptwriter", "operator": "claude"}]},
            {"label": "Gemini script", "steps": [{"role": "scout", "operator": "gemini"}, {"role": "scriptwriter", "operator": "gemini"}]},
            {"label": "Unfinished", "steps": [{"role": "scout", "operator": "gemini"}, {"role": "scriptwriter", "operator": "claude"}]},
        ]}, role_board, "owner")
    bid = battle["battle_id"]
    c1, c2, c3 = (c["chain_id"] for c in battle["chains"])
    for chain, op, rt, out in ((c1, "claude", "runner", SCRIPT_A), (c2, "gemini", "api", SCRIPT_B)):
        store.record_step_result(bid, {"chain_id": chain, "step": 0, "operator": op, "model": op + "-model", "runtime": rt, "output": "trends"})
        store.record_step_result(bid, {"chain_id": chain, "step": 1, "operator": op, "model": op + "-model", "runtime": rt, "output": out})
    store.record_step_result(bid, {"chain_id": c3, "step": 0, "operator": "gemini", "model": "gemini-model", "runtime": "api", "output": "t"})
    cands = {c["chain_id"]: c for c in store.candidates(bid)}
    crit = [{"id": "hook", "weight": 2}, {"id": "accuracy", "weight": 3}]
    scores = [{"chain_id": c, "criterion": k, "score": s} for c, k, s in
              ((c1, "hook", 8), (c1, "accuracy", 9), (c2, "hook", 7), (c2, "accuracy", 6))]
    store.record_review(bid, {"judge": {"operator": judge, "model": "judge-model", "runtime": "api"},
                              "candidates": [{"chain_id": c, "evidence_hash": cands[c]["evidence_hash"]} for c in (c1, c2)],
                              "criteria": crit, "scores": scores, "selected_chain_id": c1,
                              "rationale": "A is more accurate."}, role_board, "owner")
    return bid, c1, c2, c3


def pure_checks():
    tmp = tempfile.TemporaryDirectory()
    dbfile = Path(tmp.name) / "battles.db"

    def connect():
        con = sqlite3.connect(dbfile)
        con.row_factory = sqlite3.Row
        return con

    store = BattleStore(connect)
    store.ensure_schema()
    bid, c1, c2, c3 = seed(store, ROLE_BOARD)
    published = {"pub-a": {"status": "published", "job_id": "job-a", "platform": "tiktok"},
                 "pub-b": {"status": "published", "job_id": "job-b", "platform": "tiktok"}}
    store.link_outcome(bid, {"chain_id": c1, "publish_id": "pub-a"}, published.get, "owner")
    store.link_outcome(bid, {"chain_id": c2, "publish_id": "pub-b"}, published.get, "owner")
    before = store.get(bid)

    relay = RelayStore(Path(tmp.name) / "relay.json")
    controls = BattleTelegram(store, SNAPSHOTS.get)
    bot = Bot()
    pair = lambda: {"chat_id": CHAT}  # noqa: E731

    def run(update, battles=controls, chat_pair=pair):
        return relay_handle_telegram_update(update, relay, chat_pair, bot, None, None, None, battle_controls=battles)

    # Main Relay keyboard carries a Battles entry; /battles lists the battle with a view button.
    run(message("/status"))
    require("battle:list" in keyboard_data(bot.sent()[-1]), "relay keyboard has Battles button")
    r = run(message("/battles"))
    msg = bot.sent()[-1]
    require(r == {"handled": True, "action": "battles"} and bid in msg["text"], f"/battles: {r} {msg['text']}")
    require(keyboard_data(msg) == ["battle:view:" + bid], f"list keyboard: {keyboard_data(msg)}")
    r = run(callback("battle:list"))
    require(r["action"] == "battles" and bid in bot.sent()[-1]["text"], "Battles button lists battles")

    # Battle summary: brief, chains + status, judge pick, owner decision and the publish gate.
    r = run(callback("battle:view:" + bid))
    msg = bot.sent()[-1]
    text = msg["text"]
    require(r == {"handled": True, "action": "battle_view", "battle_id": bid}, f"view: {r}")
    require("on-device models protect privacy" in text and "статус: ⏳ идёт" in text, f"summary head: {text}")
    require("c1 · Claude script · ✅ завершён (2/2 шагов)\n  scout→claude ▸ scriptwriter→claude" in text
            and "c3 · Unfinished · ⏳ идёт (1/2 шагов)" in text, f"summary chains: {text}")
    require("Судья chatgpt: выбрал c1 (c1 8.6 · c2 6.4)" in text and "Решение владельца: нет" in text, f"judge/decision: {text}")
    require(PUBLISH_GATE in text, "publish gate stated")
    data = keyboard_data(msg)
    require(data == ["battle:chains:" + bid, "battle:metrics:" + bid, f"battle:approve:{bid}:c1", f"battle:approve:{bid}:c2",
                     "battle:reject:" + bid, "battle:list"], f"battle keyboard (no approve for unfinished c3, no publish): {data}")
    require(all(len(x.encode()) <= 64 for x in data), "Telegram callback_data limit")
    require(not any("publish" in x for x in data), "no publish button")
    run(message("/battle " + bid))
    require(bot.sent()[-1]["text"] == text, "/battle <id> renders the same summary")
    run(message("/battle battle_nope"))
    require("не найден" in bot.sent()[-1]["text"], "unknown battle")

    # Candidate chains: per-step provenance, final output excerpt and hash; unfinished step is explicit.
    r = run(callback("battle:chains:" + bid))
    text = bot.sent()[-1]["text"]
    require(r["action"] == "battle_chains", f"chains: {r}")
    require("1. scout → claude (сделал claude · claude-model · runner)" in text and "Итог: " + SCRIPT_A in text
            and "sha256: " + _sha(SCRIPT_A)[:16] in text, f"chain A: {text}")
    require("Итог: " + SCRIPT_B in text and "2. scriptwriter → claude (результата нет)" in text, f"chain B/C: {text}")

    # Factual metrics: real snapshot values, ranks, explicit "no data" for chains without measurements; never zero.
    r = run(callback("battle:metrics:" + bid))
    text = bot.sent()[-1]["text"]
    require(r["action"] == "battle_metrics", f"metrics: {r}")
    require("#1 · c1 · Claude script · публикаций: 1, измерено: 1\n  просмотры: 1200 · лайки: 90 · CTR %: 4.50" in text, f"metrics c1: {text}")
    require("#2 · c2 · Gemini script · публикаций: 1, измерено: 1\n  просмотры: 800" in text, f"metrics c2: {text}")
    require("без ранга · c3 · Unfinished · публикаций: 0, измерено: 0\n  нет данных" in text, f"metrics c3: {text}")
    require("лайки: 0" not in text, "missing metric must not be zero")
    no_source = BattleTelegram(store, None)
    run(callback("battle:metrics:" + bid), battles=no_source)
    require("Источник метрик не подключён" in bot.sent()[-1]["text"], "no metric source is explicit")

    # Safe actions: approve a completed chain (idempotent on replay), refuse unfinished, reject; nothing publishes.
    r = run(callback(f"battle:approve:{bid}:c3"))
    require(r["action"] == "battle_error" and r["status_code"] == 409 and store.owner_decisions(bid) == [], f"unfinished approve: {r}")
    r = run(callback(f"battle:approve:{bid}:c1"))
    require(r == {"handled": True, "action": "battle_approve", "battle_id": bid, "chain_id": c1, "created": True}, f"approve: {r}")
    text = bot.sent()[-1]["text"]
    require(text.startswith("✅ Одобрено: c1. Ничего не опубликовано.") and "Решение владельца: ✅ одобрена c1 · Claude script" in text
            and PUBLISH_GATE in text, f"approve reply: {text}")
    r = run(callback(f"battle:approve:{bid}:c1"))
    require(r["created"] is False and len(store.owner_decisions(bid)) == 1, "replayed callback is idempotent")
    r = run(callback("battle:reject:" + bid))
    require(r["action"] == "battle_reject" and r["created"] is True, f"reject: {r}")
    require("Решение владельца: ❌ кандидаты отклонены" in bot.sent()[-1]["text"], "reject reply")
    decisions = store.owner_decisions(bid)
    require([d["action"] for d in decisions] == ["approve", "reject"] and all(d["channel"] == "telegram" for d in decisions),
            f"append-only decisions: {decisions}")

    # Unsafe / unknown actions are refused without any state change.
    n = len(store.owner_decisions(bid))
    for data in ("battle:publish:" + bid, f"battle:publish:{bid}:c1", "battle:run:" + bid, "battle:approve:" + bid,
                 "battle:view:battle_nope", f"battle:approve:{bid}:c9"):
        r = run(callback(data))
        require(r["handled"] and r["action"] in ("battle_refused", "battle_error"), f"{data}: {r}")
    require("публикация — через ручное одобрение" in bot.answers()[-6].lower(), f"refusal text: {bot.answers()[-6]}")
    require(len(store.owner_decisions(bid)) == n, "refused callbacks change nothing")
    try:
        store.record_owner_decision(bid, "publish", c1)
        raise AssertionError("publish is not an owner action")
    except BattleError as exc:
        require(exc.status_code == 422, "publish action refused")

    # Battle record and candidates are untouched; automatic publishing stays off.
    after = store.get(bid)
    require(after == before and after["publish"] == {"automatic": False, "status": "not_published", "requires_human_approval": True},
            "decisions never change the battle or its publish policy")

    # Unpaired chat sees nothing and cannot decide; legacy bridge without battle controls stays inert.
    n_msgs, n_dec = len(bot.sent()), len(store.owner_decisions(bid))
    require(run(callback(f"battle:approve:{bid}:c2", chat="777")) == {"handled": True}, "unpaired chat")
    require(run(message("/battles"), chat_pair=lambda: {"chat_id": "999"}) is None, "unpaired /battles")
    require(len(bot.sent()) == n_msgs and len(store.owner_decisions(bid)) == n_dec, "unpaired chat changes nothing")
    require(run(callback("battle:list"), battles=None) == {"handled": True} and len(bot.sent()) == n_msgs, "no controls: inert")
    tmp.cleanup()


class FakeRequest:
    def __init__(self, body):
        self.body = body

    async def json(self):
        return self.body


def app_checks():
    import app
    bot = Bot()
    saved = (app._telegram_load_state, app._telegram_api, app._telegram_webhook_authorized)
    con = app.db()
    publish_before = con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0]
    jobs_before = con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    con.close()
    try:
        app._telegram_load_state = lambda: {"chat_id": CHAT}
        app._telegram_api = bot
        app._telegram_webhook_authorized = lambda _r: True
        board = app.get_role_operator_board()
        judge = next(o for o in next(r for r in board["roles"] if r["id"] == "reviewer")["operators"] if o not in ("auto", "claude", "gemini"))
        bid, c1, _c2, _c3 = seed(app.BATTLE_STORE, board, judge)

        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("battle:view:" + bid))))
        require(r.get("action") == "battle_view" and bid in bot.sent()[-1]["text"] and PUBLISH_GATE in bot.sent()[-1]["text"],
                f"webhook view: {r}")
        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("battle:metrics:" + bid))))
        require(r.get("action") == "battle_metrics" and "нет данных" in bot.sent()[-1]["text"], "webhook metrics without snapshots")
        r = asyncio.run(app.telegram_webhook(FakeRequest(callback(f"battle:approve:{bid}:c1"))))
        require(r.get("action") == "battle_approve" and r.get("chain_id") == c1, f"webhook approve: {r}")
        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("battle:publish:" + bid))))
        require(r.get("action") == "battle_refused", f"webhook publish refused: {r}")
        r = asyncio.run(app.telegram_webhook(FakeRequest(message("/battles"))))
        require(r.get("action") == "battles", f"webhook /battles: {r}")

        con = app.db()
        require(con.execute("SELECT COUNT(*) FROM publishing_queue").fetchone()[0] == publish_before
                and con.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == jobs_before, "Telegram battle controls never publish or create jobs")
        con.close()
        require(app.BATTLE_STORE.get(bid)["publish"]["automatic"] is False, "publish.automatic stays false")
        require(app.FACTORY_OPERATOR_WORKER_TOKEN not in json.dumps(bot.calls), "no worker token in Telegram replies")
    finally:
        app._telegram_load_state, app._telegram_api, app._telegram_webhook_authorized = saved


if __name__ == "__main__":
    pure_checks()
    print("Telegram Battle checks passed (summary, candidate chains, factual metrics, approve/reject only, publish gate kept)")
    app_checks()
    print("Telegram webhook Battle checks passed (no publish, no jobs, unsafe callbacks refused)")
