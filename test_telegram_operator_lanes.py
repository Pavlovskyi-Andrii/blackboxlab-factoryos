"""T-586 Telegram operator lanes regression (no live token, network, spend or messages).

The paired Telegram owner bridge renders Claude and Gemini operator buttons, each button lists that operator's
open tickets and current status from the T-585 delegation lanes, an unconfigured Gemini stays explicit, and the
existing Relay ticket controls (status buttons, done-guard, ticket card) keep working.
"""
import asyncio
import json
import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-telegram-lanes-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

from lane_board import build_lane_board  # noqa: E402
from operator_lanes import build_operator_lanes  # noqa: E402
from relay import RelayStore, relay_handle_telegram_update  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402

CHAT = "4242"


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def iso(ts):
    return datetime.fromtimestamp(ts, timezone.utc).isoformat().replace("+00:00", "Z")


def seed(store):
    """Two Claude-owned GitHub tickets (running + blocked) and one plain inbox ticket."""
    now = time.time()
    store.create("Fix CI flake", source={"channel": "github", "owner": "claude", "source_key": "github:51"}, created_by="ChatGPT")
    store.create("Relay retry blocked", source={"channel": "github", "owner": "claude", "source_key": "github:52"}, created_by="ChatGPT")
    store.create("Owner note", source={"source_key": "telegram:9"}, created_by="telegram")
    with store.lock:
        state = store._load_unlocked()
        for t in state["tickets"]:
            if t["id"] == "R-0001":
                t["status"] = "in_progress"
                t["execution"] = {"state": "running", "owner": "claude", "worker_id": "ec2-claude", "run_id": "run-1",
                                  "claimed_at": iso(now - 30), "last_seen_at": iso(now - 5)}
            if t["id"] == "R-0002":
                t["status"] = "need_you"
                t["execution"] = {"state": "blocked", "owner": "claude", "worker_id": "ec2-claude", "run_id": "run-0",
                                  "claimed_at": iso(now - 900), "last_seen_at": iso(now - 600), "note": "needs owner"}
        store._save_unlocked(state)


def keyboard_data(payload):
    return [b["callback_data"] for row in (payload.get("reply_markup") or {}).get("inline_keyboard") or [] for b in row]


class Bot:
    def __init__(self):
        self.calls = []

    def __call__(self, method, payload=None):
        self.calls.append((method, payload or {}))
        return {"ok": True}

    def sent(self):
        return [p for m, p in self.calls if m == "sendMessage"]


def callback(data, chat=CHAT):
    return {"update_id": 1, "callback_query": {"id": "cb", "data": data, "from": {"language_code": "ru"},
                                               "message": {"chat": {"id": int(chat), "type": "private"}}}}


def workers_overview_checks():
    """#135: /workers row per executor — working / idle / stale / no data, RU/UK/EN, nothing invented."""
    from relay import _t585_overview_text
    lanes = {
        "claude": {"availability": "online", "heartbeat": {"age_seconds": 75}, "open_ticket": {"id": "T-610", "stage": "running"},
                   "open_tickets": [{"id": "T-610"}], "queue_depth": 3},
        "chatgpt": {"availability": "online", "heartbeat": {"age_seconds": 5}, "open_tickets": [], "queue_depth": 0},
        "gemini": {"availability": "stale", "heartbeat": {"age_seconds": 7200}, "open_tickets": []},
    }
    ru = _t585_overview_text(lanes, "ru").splitlines()
    require(ru[1] == "🟠 Claude: 🟢 онлайн · работает над T-610 (running) · сигнал 1 мин назад · в работе 1 · в очереди 3", f"working: {ru}")
    require(ru[2] == "🟢 ChatGPT: 🟢 онлайн · простаивает · сигнал 5 сек назад · в работе 0 · в очереди 0", f"idle: {ru}")
    require(ru[3] == "🔵 Gemini: 🟡 сигнал просрочен · сигнал 2 ч назад · в работе 0 · очередь неизвестна", f"stale: {ru}")
    empty = _t585_overview_text({}, "en").splitlines()
    require(empty[0] == "🧠 FactoryOS workers" and all(row.endswith("⚪ unknown · no signal yet") for row in empty[1:]), f"no data: {empty}")
    uk = _t585_overview_text(lanes, "uk")
    require("працює над T-610" in uk and "простоює" in uk and "2 год тому" in uk, f"uk: {uk}")


def pure_checks():
    workers_overview_checks()
    tmp = tempfile.TemporaryDirectory()
    store = RelayStore(Path(tmp.name) / "relay.json")
    queue = RelayQueue(store)
    seed(store)
    board = build_lane_board([], store.list(limit=500), {}, stale_seconds=180)
    lanes = build_operator_lanes(lane_board=board, runners={"claude": {"last_seen": time.time() - 3, "branch": "autopilot/aws-worker",
                                                                      "runtime": "claude-code", "queue_depth": 2}})
    bot = Bot()
    pair = lambda: {"chat_id": CHAT}  # noqa: E731

    def run(update, provider=lambda: lanes):
        return relay_handle_telegram_update(update, store, pair, bot, None, None, queue, operator_lanes_provider=provider)

    # /status (main relay keyboard) now carries the two operator buttons.
    r = run({"update_id": 2, "message": {"chat": {"id": int(CHAT), "type": "private"}, "text": "/status", "message_id": 2}})
    require(r["action"] == "status", f"/status: {r}")
    data = keyboard_data(bot.sent()[-1])
    require("relay:operator:claude" in data and "relay:operator:gemini" in data, f"/status keyboard lacks operator buttons: {data}")
    require("relay:overview:tasks" in data, "existing overview buttons kept")

    # Claude button: status + its open tickets, each Relay ticket gets a button.
    r = run(callback("relay:operator:claude"))
    require(r == {"handled": True, "action": "operator", "operator": "claude"}, f"claude callback: {r}")
    msg = bot.sent()[-1]
    text = msg["text"]
    require(text.startswith("🟠 Claude") and "🟢 online" in text, f"claude status: {text}")
    require("Текущий тикет: R-0001 · running" in text, f"claude current ticket: {text}")
    require("Открытые тикеты (2):" in text and "R-0001 · Fix CI flake · running" in text
            and "R-0002 · Relay retry blocked · blocked" in text, f"claude open tickets: {text}")
    require("Ветка: autopilot/aws-worker · runtime: claude-code" in text and "Очередь: 2 (operator_heartbeat)" in text,
            f"claude branch/queue: {text}")
    data = keyboard_data(msg)
    require(data[:2] == ["relay:operator:claude", "relay:operator:gemini"], f"operator buttons first: {data}")
    require("relay:ticket:R-0001" in data and "relay:ticket:R-0002" in data and "relay:ticket:R-0003" not in data,
            f"only Claude's tickets get buttons: {data}")
    require(data[-1] == "relay:list:active", "all-tickets button kept")
    require(all(len(x.encode()) <= 64 for x in data), "Telegram callback_data limit")

    # Gemini button: explicitly unconfigured, no tickets, never online.
    run(callback("relay:operator:gemini"))
    msg = bot.sent()[-1]
    text = msg["text"]
    require(text.startswith("🔵 Gemini") and "не настроен" in text and "online" not in text, f"gemini unconfigured: {text}")
    require("Открытых тикетов нет." in text and "Heartbeat: нет данных" in text and "Очередь: неизвестно" in text,
            f"gemini must not invent data: {text}")
    require(not any(x.startswith("relay:ticket:") for x in keyboard_data(msg)), "gemini has no ticket buttons")

    # Workers overview lists both lanes with status and open-ticket counts.
    r = run(callback("relay:overview:workers"))
    text = bot.sent()[-1]["text"]
    require(r["action"] == "workers" and "🟠 Claude: 🟢 онлайн · работает над R-0001 (running) · сигнал" in text
            and "в работе 2 · в очереди 2" in text and "🔵 Gemini: ⚪ неизвестно · сигнала нет" in text
            and "🟢 ChatGPT:" in text, f"workers overview: {text}")
    run({"update_id": 3, "message": {"chat": {"id": int(CHAT), "type": "private"}, "text": "/operators", "message_id": 3}})
    require("🔵 Gemini: ⚪ неизвестно" in bot.sent()[-1]["text"], "/operators uses the same lanes")

    # Ticket button opens the normal ticket card with the existing Relay controls.
    r = run(callback("relay:ticket:R-0001"))
    require(r == {"handled": True, "action": "ticket", "ticket_id": "R-0001"}, f"ticket callback: {r}")
    msg = bot.sent()[-1]
    require("📡 R-0001" in msg["text"] and "Fix CI flake" in msg["text"], f"ticket card: {msg['text']}")
    data = keyboard_data(msg)
    require("relay:status:R-0001:done" in data and "relay:status:R-0001:in_progress" in data, f"ticket controls: {data}")
    n = len(bot.sent())
    require(run(callback("relay:ticket:R-9999")) == {"handled": True} and len(bot.sent()) == n, "unknown ticket sends nothing")

    # Existing Relay controls: running ticket cannot be marked done; inbox ticket status change still works.
    before = store.get("R-0001")["status"]
    run(callback("relay:status:R-0001:done"))
    require(store.get("R-0001")["status"] == before, "done-guard must still block a running ticket")
    r = run(callback("relay:status:R-0003:need_you"))
    require(r == {"handled": True, "ticket_id": "R-0003", "status": "need_you"} and store.get("R-0003")["status"] == "need_you",
            f"status control: {r}")
    require("relay:status:R-0003:inbox" in keyboard_data(bot.sent()[-1]), "status reply keeps ticket controls")
    run(callback("relay:list:active"))
    require("R-0003" in bot.sent()[-1]["text"], "active list still works")

    # Lane provider failure is explicit unknown, never online.
    def broken():
        raise RuntimeError("boom")
    run(callback("relay:operator:claude"), provider=broken)
    text = bot.sent()[-1]["text"]
    require("недоступен" in text and "online" not in text, f"failed provider must be unknown: {text}")

    # Unpaired chat cannot read lanes.
    n = len(bot.sent())
    require(run(callback("relay:operator:claude", chat="777")) == {"handled": True} and len(bot.sent()) == n, "unpaired chat")

    # Without the T-585 provider the legacy heartbeat rendering is unchanged.
    relay_handle_telegram_update(callback("relay:operator:gemini"), store, pair, bot,
                                 lambda: {"gemini": {"online": False, "state": "offline"}}, None, queue)
    require(bot.sent()[-1]["text"] == "🔵 Gemini\nСтатус: ⚪ offline", f"legacy path: {bot.sent()[-1]['text']}")
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
    try:
        app._telegram_load_state = lambda: {"chat_id": CHAT}
        app._telegram_api = bot
        app._telegram_webhook_authorized = lambda _r: True
        app.claude_worker_runtime.update({"last_seen": 0.0, "node": {}, "active_task_id": "", "last_error": "", "telemetry": {}})
        app.operator_worker_runtime.clear()
        app.operator_worker_runtime.update({"claude": {"last_seen": 0.0}, "gemini": {"last_seen": 0.0}})
        seed(app.RELAY_STORE)

        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("relay:operator:gemini"))))
        require(r.get("action") == "operator" and r.get("operator") == "gemini", f"webhook gemini: {r}")
        require("не настроен" in bot.sent()[-1]["text"], f"app gemini must be unconfigured: {bot.sent()[-1]['text']}")

        app.operator_worker_heartbeat(app.OperatorWorkerHeartbeat(
            operator_id="claude", node_id="ec2", runtime="claude-code", branch="autopilot/aws-worker", status="idle",
            queue_depth=1, last_result="token " + app.FACTORY_OPERATOR_WORKER_TOKEN))
        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("relay:operator:claude"))))
        msg = bot.sent()[-1]
        require(r.get("operator") == "claude" and "🟢 online" in msg["text"] and "R-0001" in msg["text"]
                and "R-0002" in msg["text"], f"app claude lane: {msg['text']}")
        require("relay:ticket:R-0001" in keyboard_data(msg), "app ticket buttons")
        dumped = json.dumps(bot.calls)
        require(app.FACTORY_OPERATOR_WORKER_TOKEN not in dumped and "[redacted]" in msg["text"], "secrets must be redacted")

        r = asyncio.run(app.telegram_webhook(FakeRequest(callback("relay:status:R-0003:need_you"))))
        require(r.get("status") == "need_you" and app.RELAY_STORE.get("R-0003")["status"] == "need_you", f"app status control: {r}")
    finally:
        app._telegram_load_state, app._telegram_api, app._telegram_webhook_authorized = saved
        app.operator_worker_runtime.clear()
        app.operator_worker_runtime.update({"claude": {"last_seen": 0.0}, "gemini": {"last_seen": 0.0}})


if __name__ == "__main__":
    pure_checks()
    print("Telegram operator lane checks passed (Claude/Gemini buttons, open tickets/status, unconfigured Gemini, Relay controls)")
    app_checks()
    print("Telegram webhook operator lane checks passed (T-585 lanes, secrets redacted, Relay controls)")
