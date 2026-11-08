"""T-599-F: Workers / Build Progress / Telegram derive lane state only from verified Relay events + heartbeat.

Deterministic, no network, no Claude. Fixtures cover idle / working / blocked / stale / offline lanes and
"assigned, not claimed" tasks. The same ``build_lane_board`` dict feeds Telegram ``/status`` + ``/tasks``
and the web renderer (run under Node), and both must show the identical task and stage in EN/UK/RU.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from lane_board import TEXT, build_lane_board, lane_board_text, telegram_lang
from relay import RelayStore, relay_handle_telegram_update
from relay_execution import RelayQueue

HTML = Path(__file__).resolve().parent / "static" / "index.html"
ROADMAP = [
    {"id": "T-901", "title": "Claude task", "owner": "claude", "done": False, "human": False},
    {"id": "T-902", "title": "Second Claude task", "owner": "claude", "done": False, "human": False},
    {"id": "T-903", "title": "ChatGPT task", "owner": "chatgpt", "done": False, "human": False},
    {"id": "T-904", "title": "Finished", "owner": "claude", "done": True, "human": False},
    {"id": "T-905", "title": "Owner pairing", "owner": "", "done": False, "human": True},
]
CHAT = "4242"


class LaneBoardCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def board(self, beats=None, roadmap=None):
        return build_lane_board(roadmap or ROADMAP, self.store.list(limit=500), beats or {}, stale_seconds=self.queue.stale_seconds)

    def fresh(self):
        return {"claude": time.time() - 5}

    def claim(self, task="T-901", lane="claude", worker="claude-ec2"):
        ticket, reason = self.queue.claim_roadmap(worker, lane, task, "title", lane)
        self.assertEqual(reason, "")
        return ticket

    def emit(self, ticket, stage, worker="claude-ec2", evidence=None):
        run = ticket["execution"]["run_id"]
        return self.queue.event(ticket["id"], worker, stage, stage, evidence or {}, run_id=run, event_id=f"{run}:{stage}")

    def expire(self, ticket_id):
        with self.store.lock:
            data = self.store._load_unlocked()
            for item in data["tickets"]:
                if item["id"] == ticket_id:
                    item["execution"]["last_seen_at"] = "2020-01-01T00:00:00+00:00"
            self.store._save_unlocked(data)

    # --- fixtures: one per lane state -------------------------------------------------------------
    def fixture_idle(self):
        return self.board(self.fresh())

    def fixture_working(self):
        ticket = self.claim()
        self.emit(ticket, "running", evidence={"branch": "autopilot/aws-worker"})
        return self.board(self.fresh())

    def fixture_blocked(self):
        ticket = self.claim()
        self.emit(ticket, "running")
        self.emit(ticket, "blocked")
        return self.board(self.fresh())

    def fixture_stale(self):
        ticket = self.claim()
        self.emit(ticket, "running")
        self.expire(ticket["id"])
        return self.board(self.fresh())

    def fixture_offline(self):
        return self.board({})


class TestLaneStates(LaneBoardCase):
    def task(self, board, tid):
        return next(t for t in board["tasks"] if t["id"] == tid)

    def test_idle_assigned_not_claimed(self):
        board = self.fixture_idle()
        lane = board["lanes"]["claude"]
        self.assertEqual(lane["state"], "idle")
        self.assertEqual(lane["task_id"], "")
        self.assertEqual(lane["assigned_not_claimed"], ["T-901", "T-902"])
        for tid in ("T-901", "T-902"):
            self.assertEqual(self.task(board, tid)["column"], "planned")
            self.assertEqual(self.task(board, tid)["claim"], "assigned_not_claimed")
        self.assertEqual(self.task(board, "T-905")["claim"], "unassigned")
        self.assertEqual(board["counts"], {"planned": 4, "in_progress": 0, "blocked": 0, "review": 0, "done": 1})
        self.assertEqual((lane["done"], lane["remaining"]), (1, 2))

    def test_working_only_with_claim_and_fresh_event(self):
        board = self.fixture_working()
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["stage"]), ("working", "T-901", "running"))
        self.assertEqual(lane["last_event"]["action"], "running")
        self.assertTrue(lane["started_at"] and lane["run_id"].startswith("run-"))
        self.assertEqual(self.task(board, "T-901")["column"], "in_progress")
        self.assertEqual(lane["assigned_not_claimed"], ["T-902"])
        self.assertEqual(lane["columns"]["in_progress"], 1)

    def test_blocked_last_event(self):
        board = self.fixture_blocked()
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["stage"]), ("blocked", "T-901", "blocked"))
        self.assertEqual(self.task(board, "T-901")["column"], "blocked")

    def test_old_block_is_history_not_current_state(self):
        # 2026-11-05 mobile screenshot: a run blocked three days earlier still showed the lane as "Blocked".
        self.fixture_blocked()
        later = time.time() + 2 * 86400
        board = build_lane_board(ROADMAP, self.store.list(limit=500), {"claude": later - 5},
                                 now=later, stale_seconds=self.queue.stale_seconds)
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["reason"]), ("idle", "", ""))
        self.assertEqual(lane["last_task_id"], "T-901")                       # still visible as the last task
        self.assertEqual(self.task(board, "T-901")["column"], "blocked")       # the task itself stays blocked

    def test_github_activity_is_shown_not_trusted_as_state(self):
        activity = {"gemini": {"done_7d": 6, "last_activity_at": "2026-11-05T08:42:38+00:00"}, "chatgpt": {"done_7d": 0},
                    "claude": "garbage"}
        board = build_lane_board(ROADMAP, self.store.list(limit=500), {}, stale_seconds=self.queue.stale_seconds,
                                 github_activity=activity)
        gem = board["lanes"]["gemini"]
        self.assertEqual(gem["github"], {"done_7d": 6, "last_activity_at": "2026-11-05T08:42:38+00:00"})
        self.assertEqual(gem["state"], "offline")             # no heartbeat: GitHub activity never fakes "online"
        self.assertIsNone(board["lanes"]["chatgpt"]["github"])  # nothing to show
        self.assertIsNone(board["lanes"]["claude"]["github"])   # malformed input ignored

    def test_stale_run_lost_contact(self):
        board = self.fixture_stale()
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["stage"]), ("stale", "T-901", "stale"))
        self.assertEqual(self.task(board, "T-901")["column"], "blocked")

    def test_offline_and_stale_heartbeat(self):
        self.assertEqual(self.fixture_offline()["lanes"]["claude"]["state"], "offline")
        self.assertEqual(self.board({"claude": time.time() - 600})["lanes"]["claude"]["state"], "stale")
        self.assertEqual(self.board({"claude": time.time() - 7200})["lanes"]["claude"]["state"], "offline")
        # A server-side TTL verdict wins over the local default.
        self.assertEqual(self.board({"claude": {"last_seen": time.time() - 5, "online": False}})["lanes"]["claude"]["state"], "stale")

    def test_review_until_roadmap_checkbox(self):
        ticket = self.claim()
        for stage in ("running", "committed", "pushed", "done"):
            self.emit(ticket, stage, evidence={"commit": "ab" * 20} if stage == "committed" else None)
        board = self.board(self.fresh())
        self.assertEqual(self.task(board, "T-901")["column"], "review")
        self.assertEqual(board["lanes"]["claude"]["state"], "idle")
        merged = [dict(t, done=True) if t["id"] == "T-901" else t for t in ROADMAP]
        self.assertEqual(self.task(self.board(self.fresh(), merged), "T-901")["column"], "done")

    def test_chatgpt_never_fabricated(self):
        board = self.fixture_working()
        gpt = board["lanes"]["chatgpt"]
        self.assertEqual(gpt["state"], "offline")
        self.assertEqual(gpt["assigned_not_claimed"], ["T-903"])
        self.assertNotIn("T-903", board["columns"]["in_progress"])
        # Its own claimed run with fresh events is the only way ChatGPT shows as working.
        ticket = self.claim("T-903", "chatgpt", "gpt-runner")
        self.emit(ticket, "running", worker="gpt-runner")
        gpt = self.board(self.fresh())["lanes"]["chatgpt"]
        self.assertEqual((gpt["state"], gpt["task_id"], gpt["stage"]), ("working", "T-903", "running"))

    def test_owner_issue_shows_assigned_not_claimed(self):
        self.queue.auto_intake_owner_issues([{"number": 77, "title": "Gemini work", "body": "Owner: Gemini\nDo it",
                                              "author": "owner", "state": "open", "url": ""}], "owner/repo", "owner")
        board = self.board(self.fresh())
        issue = next(t for t in board["tasks"] if t["kind"] == "issue")
        self.assertEqual((issue["lane"], issue["claim"], issue["column"]), ("gemini", "assigned_not_claimed", "planned"))
        self.assertEqual(board["lanes"]["gemini"]["assigned_not_claimed"], [issue["id"]])


class TestTelegramMatchesWeb(LaneBoardCase):
    def send(self, command, lang, board):
        sent = []
        update = {"message": {"chat": {"id": int(CHAT), "type": "private"}, "text": command,
                              "from": {"language_code": lang}}}
        relay_handle_telegram_update(update, self.store, lambda: {"chat_id": CHAT},
                                     lambda method, payload=None: sent.append((method, payload)) or {"ok": True},
                                     queue=self.queue, lane_board_provider=lambda: board)
        return next(p["text"] for m, p in sent if m == "sendMessage")

    def test_status_and_tasks_show_web_task_and_stage(self):
        fixtures = {}
        for name in ("idle", "working", "blocked", "stale", "offline"):
            self.tearDown(); self.setUp()
            fixtures[name] = getattr(self, "fixture_" + name)()
        for name, board in fixtures.items():
            lane = board["lanes"]["claude"]
            self.assertEqual(lane["state"], name)
            for lang in ("en", "uk", "ru"):
                t = TEXT[lang]
                for command in ("/status", "/tasks"):
                    text = self.send(command, lang, board)
                    self.assertIn("Claude: " + t[name], text, (name, lang, command))
                    if lane["task_id"]:
                        self.assertIn(f"{t['task']} {lane['task_id']} · {t['stage']} {lane['stage']}", text)
                    else:
                        self.assertNotIn(t["stage"] + " ", text.split("ChatGPT")[0].split("Claude:")[-1])
                    self.assertIn("ChatGPT: " + t["offline"], text)
                    self.assertIn(t["unclaimed"] + ": T-903", text)
                    # Heartbeat-only legacy lines are replaced, not mixed in.
                    self.assertNotIn("выполняет", text)

    def test_language_fallback_and_columns(self):
        board = self.fixture_working()
        text = lane_board_text(board, "de")
        self.assertIn(TEXT["ru"]["title"], text)
        self.assertIn("В работе 1", text)

    def test_lane_board_text(self):
        board = self.fixture_working()
        texts = {lang: lane_board_text(board, lang) for lang in ("ru", "uk", "en")}
        for lang in ("ru", "uk", "en"):
            self.assertIn(TEXT[lang]["title"], texts[lang])
        nums = {lang: re.findall(r"\d+", texts[lang]) for lang in ("ru", "uk", "en")}
        self.assertEqual(nums["ru"], nums["uk"])
        self.assertEqual(nums["ru"], nums["en"])

    def test_telegram_lang(self):
        self.assertEqual(telegram_lang('uk-UA'), 'uk')
        self.assertEqual(telegram_lang('EN'), 'en')
        self.assertEqual(telegram_lang(None), 'ru')
        self.assertEqual(telegram_lang('de'), 'ru')
        self.assertEqual(telegram_lang(''), 'ru')


def ui_program():
    html = HTML.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split("// --- lane-board:begin", 1)[1].split("\n", 1)[1].split("// --- lane-board:end", 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    assigns = "\n".join(l for l in script.splitlines() if l.startswith("Object.assign(I18N.") and '"lb.' in l)
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    # T-597: the lane heading carries the shared Relay help tip, so load the real explain helper.
    explain = script.split("// --- explain:begin", 1)[1].split("\n", 1)[1].split("// --- explain:end", 1)[0]
    stub = "const document={addEventListener(){},querySelectorAll(){return []}};\n"
    return html, block, "let LANG='en';\n" + stub + helpers + "\n" + i18n + "\n" + assigns + "\n" + tr + "\n" + explain + "\n" + block


class TestWebRenderer(LaneBoardCase):
    def test_static_wiring(self):
        html, block, _ = ui_program()
        self.assertIn("/api/factory/lane-board", html)
        self.assertIn('id="laneBoardBuild"', html)
        self.assertIn("renderLaneBoard(lbWorkersBoard)", html)  # Workers center
        self.assertNotIn("innerHTML", block)
        self.assertNotIn("fetch(", block)
        self.assertIsNone(re.search(r"token|api_key|password|secret", block, re.I))
        keys = set(re.findall(r"tr\('(lb\.[a-zA-Z_.]*[a-zA-Z_])'", block))
        keys |= {f"lb.state.{s}" for s in ("working", "blocked", "stale", "idle", "offline")}
        keys |= {f"lb.col.{c}" for c in ("planned", "in_progress", "blocked", "review", "done")}
        keys |= {f"lb.claim.{c}" for c in ("unassigned", "queued", "claimed")}
        for key in keys:
            self.assertEqual(html.count(f'"{key}":'), 3, f"{key} must exist in EN/UK/RU")

    def test_fixture_rendering_matches_api(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required for the lane board rendering check")
            self.skipTest("node is not installed")
        fixtures = {}
        for name in ("idle", "working", "blocked", "stale", "offline"):
            self.tearDown(); self.setUp()
            fixtures[name] = getattr(self, "fixture_" + name)()
        fixtures["working"]["tasks"][1]["title"] = "<script>alert(1)</script>"
        _, _, code = ui_program()
        program = code + "\nconst fx=" + json.dumps(fixtures) + ",out={};" \
            "for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fx))out[lang+':'+k]=renderLaneBoard(fx[k])}" \
            "process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        out = json.loads(result.stdout)
        labels = {"en": ("Working", "assigned, not claimed"), "uk": ("Працює", "призначено, не взято"),
                  "ru": ("Работает", "назначено, не взято")}
        for key, html in out.items():
            lang, name = key.split(":")
            lane = fixtures[name]["lanes"]["claude"]
            self.assertIn(f'data-lane="claude" data-state="{name}"', html, key)
            self.assertIn('data-lane="chatgpt" data-state="offline"', html, key)
            if lane["task_id"]:
                self.assertIn(f'data-task="{lane["task_id"]}" data-stage="{lane["stage"]}"', html, key)
            self.assertIn('data-unclaimed="T-903"', html)
            self.assertIn(labels[lang][1], html, key)
            self.assertIsNone(re.search(r">lb\.[a-z]", html), key)  # no raw i18n keys
            for col in ("planned", "in_progress", "blocked", "review", "done"):
                self.assertIn(f'data-column="{col}"', html)
            self.assertNotIn("<script>alert", html)
        self.assertIn(labels["uk"][0], out["uk:working"])
        self.assertIn(labels["ru"][0], out["ru:working"])
        self.assertIn('data-task="T-901" data-claim="claimed"', out["en:working"])
        self.assertIn('data-task="T-901" data-claim="assigned_not_claimed"', out["en:idle"])
        self.assertNotIn('data-state="working"', out["en:idle"])
        # T-599: the blocked run's worker note is shown as the reason, only on a blocked lane.
        self.assertIn('data-reason="1">Reason: blocked<', out["en:blocked"])
        self.assertIn('data-reason="1">Причина: blocked<', out["ru:blocked"])
        self.assertNotIn("data-reason", out["en:working"])


class TestApi(unittest.TestCase):
    def test_endpoint_uses_relay_events_and_heartbeat(self):
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-lanes-"))
        import app
        paths = {getattr(r, "path", "") for r in app.app.routes}
        self.assertIn("/api/factory/lane-board", paths)
        with tempfile.TemporaryDirectory() as tmp:
            store = RelayStore(Path(tmp) / "relay.json")
            queue = RelayQueue(store)
            task = next(t for t in app._parse_roadmap_tasks() if not t["done"] and t["owner"] == "claude")
            ticket, _ = queue.claim_roadmap("claude-ec2", "claude", task["id"], owner="claude")
            queue.event(ticket["id"], "claude-ec2", "running", "go", run_id=ticket["execution"]["run_id"])
            with unittest.mock.patch.object(app, "RELAY_STORE", store), unittest.mock.patch.object(app, "RELAY_QUEUE", queue):
                board = app.get_lane_board()
        lane = board["lanes"]["claude"]
        self.assertEqual((lane["state"], lane["task_id"], lane["stage"]), ("working", task["id"], "running"))
        self.assertEqual(board["source"], "relay-events+heartbeat")


if __name__ == "__main__":
    unittest.main(verbosity=2)
