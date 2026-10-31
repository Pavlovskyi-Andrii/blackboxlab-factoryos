"""T-596: Worker Center / Agent Office factual observability.

Deterministic, no network, no Claude. Fixtures cover offline / stale / idle / running / blocked workers,
fresh / stale / missing supervisor reports, a heartbeat that names a task without a claim, the
Kyiv-day heatmap (zero vs unknown) and separate progress populations. The same lane board snapshot
feeds the overview, Telegram ``/status`` and the web renderer (run under Node) in EN/UK/RU.
"""
import json
import os
import re
import shutil
import subprocess
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path

from test_lane_board import CHAT, LaneBoardCase, ROADMAP
from relay import relay_handle_telegram_update
from worker_observability import (TEXT, build_worker_overview, sanitize_supervisor, worker_overview_text, _heatmap)

HTML = Path(__file__).resolve().parent / "static" / "index.html"
REPO = "owner/repo"
ROADMAP_X = ROADMAP + [{"id": "T-906", "title": "Pair bot", "owner": "", "done": False, "human": True,
                        "need": "Pair the owner Telegram chat", "roadmap_line": 157}]


def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def status(seen=None, online=None, task="", task_state="idle", supervisor=None, error=""):
    node = {"node_id": "ec2", "hostname": "ip-10-0-0-1", "auth_mode": "subscription", "branch": "autopilot/aws-worker"}
    if supervisor is not None:
        node["supervisor"] = supervisor
    return {"online": bool(online), "ttl_seconds": 180, "last_seen": seen or 0, "node": node,
            "active_task_id": task, "task_state": task_state, "last_error": error}


def supervisor(age=10, service="active", logged_in=True):
    return {"checked_at": iso(time.time() - age), "service_state": service, "subscription_authenticated": logged_in,
            "status": "running", "reason": "healthy", "restart_attempts_last_hour": 0}


class OverviewCase(LaneBoardCase):
    def overview(self, board, st, results=(), answers=""):
        self.last_board = board
        return build_worker_overview(st, board, results=list(results), tickets=self.store.list(limit=500),
                                     roadmap_tasks=ROADMAP_X, factory_tasks={"total": 45, "done": 39},
                                     answers_text=answers, repo=REPO)

    def live(self, **kw):
        return status(seen=time.time() - 5, online=True, supervisor=supervisor(), **kw)

    # one fixture per worker state ----------------------------------------------------------------
    def fixture_offline(self):
        return self.overview(self.board({}), status())

    def fixture_stale(self):
        seen = time.time() - 900
        return self.overview(self.board({"claude": seen}), status(seen=seen, online=False))

    def fixture_idle(self):
        return self.overview(self.board(self.fresh()), self.live())

    def fixture_running(self):
        ticket = self.claim()
        self.emit(ticket, "running")
        return self.overview(self.board(self.fresh()), self.live(task="T-901", task_state="running"))

    def fixture_blocked(self):
        ticket = self.claim()
        self.emit(ticket, "running")
        self.emit(ticket, "blocked")
        return self.overview(self.board(self.fresh()), self.live())


def sig(overview, sid):
    return next(s for s in overview["signals"] if s["id"] == sid)


class TestSignals(OverviewCase):
    def test_offline_never_seen(self):
        o = self.fixture_offline()
        self.assertEqual(o["lane_state"], "offline")
        self.assertEqual(sig(o, "host")["state"], "unknown")
        self.assertEqual(sig(o, "heartbeat")["state"], "fail")
        self.assertEqual(sig(o, "systemd")["value"], "supervisor_not_reported")
        self.assertEqual(sig(o, "oauth")["state"], "unknown")
        self.assertEqual(o["task_id"], "")
        self.assertEqual(o["last_verified_at"], "")

    def test_ec2_api_is_missing_visibility_not_offline(self):
        for name in ("offline", "stale", "idle", "running", "blocked"):
            self.tearDown(); self.setUp()
            s = sig(getattr(self, "fixture_" + name)(), "ec2_api")
            self.assertEqual((s["state"], s["value"], s["human"]), ("unknown", "describe_instances_not_granted", "optional"))

    def test_stale_heartbeat(self):
        o = self.fixture_stale()
        self.assertEqual(o["lane_state"], "stale")
        self.assertEqual(sig(o, "heartbeat")["state"], "warn")
        self.assertEqual(sig(o, "host")["state"], "warn")
        # No supervisor report: OAuth is only the runner's own claim, never "ok".
        self.assertEqual(sig(o, "oauth")["state"], "unknown")
        self.assertTrue(sig(o, "oauth")["value"].startswith("self_reported:"))

    def test_idle_verified_sources_without_task(self):
        o = self.fixture_idle()
        self.assertEqual(o["lane_state"], "idle")
        for sid in ("host", "systemd", "oauth", "heartbeat"):
            self.assertEqual(sig(o, sid)["state"], "ok", sid)
            self.assertTrue(sig(o, sid)["checked_at"], sid)
        self.assertEqual(sig(o, "relay_claim")["state"], "idle")
        self.assertEqual(sig(o, "current_task")["state"], "idle")
        self.assertEqual(o["task_id"], "")
        self.assertTrue(o["last_verified_at"])

    def test_running_needs_claim_and_matches_lane(self):
        o = self.fixture_running()
        cur = sig(o, "current_task")
        self.assertEqual((o["lane_state"], o["task_id"], o["stage"]), ("working", "T-901", "running"))
        self.assertEqual((cur["state"], cur["value"], cur["stage"], cur["mismatch"]), ("ok", "T-901", "running", False))
        self.assertTrue(sig(o, "relay_claim")["value"].startswith("run-"))

    def test_heartbeat_task_without_claim_is_mismatch_not_work(self):
        o = self.overview(self.board(self.fresh()), self.live(task="T-902", task_state="running"))
        cur = sig(o, "current_task")
        self.assertEqual((cur["state"], cur["source"], cur["mismatch"]), ("warn", "heartbeat", True))
        self.assertEqual(o["task_id"], "")

    def test_heartbeat_task_differs_from_claim(self):
        ticket = self.claim()
        self.emit(ticket, "running")
        o = self.overview(self.board(self.fresh()), self.live(task="T-902", task_state="running"))
        cur = sig(o, "current_task")
        self.assertEqual((cur["state"], cur["value"], cur["heartbeat_task"]), ("warn", "T-901", "T-902"))
        self.assertEqual(o["task_id"], "T-901")

    def test_blocked_reason_in_errors(self):
        o = self.fixture_blocked()
        self.assertEqual(o["lane_state"], "blocked")
        self.assertEqual(sig(o, "relay_claim")["state"], "fail")
        self.assertIn("relay", [e["source"] for e in o["errors"]])
        self.assertEqual(o["task_id"], "")

    def test_supervisor_stale_failed_logged_out(self):
        board = self.board(self.fresh())
        o = self.overview(board, status(seen=time.time() - 5, online=True, supervisor=supervisor(age=3600)))
        self.assertEqual((sig(o, "systemd")["state"], sig(o, "systemd")["value"]), ("unknown", "supervisor_report_stale"))
        self.assertEqual(sig(o, "oauth")["state"], "unknown")
        o = self.overview(board, status(seen=time.time() - 5, online=True, supervisor=supervisor(service="failed", logged_in=False)))
        self.assertEqual(sig(o, "systemd")["state"], "fail")
        self.assertEqual((sig(o, "oauth")["state"], sig(o, "oauth")["human"]), ("fail", "required"))

    def test_sanitize_supervisor_whitelist(self):
        raw = {**supervisor(), "token": "abc", "service_state": "active; rm -rf <x>", "subscription_authenticated": "yes",
               "restart_attempts_last_hour": True}
        clean = sanitize_supervisor(raw)
        self.assertNotIn("token", clean)
        self.assertNotIn("subscription_authenticated", clean)  # only a real bool counts
        self.assertNotIn("restart_attempts_last_hour", clean)
        self.assertNotIn("<", clean["service_state"])
        self.assertEqual(sanitize_supervisor("nope"), {})


class TestEvidence(OverviewCase):
    def test_links_progress_and_human(self):
        sha = "0123456789abcdef0123456789abcdef01234567"
        results = [{"task_id": "T-901", "result": "done", "commit": sha, "files": ["app.py"], "checks": ["python smoke_tests.py"],
                    "received_at": time.time() - 60}]
        o = self.overview(self.board(self.fresh()), self.live(), results, answers="## T-905\nanswer\n")
        ev = o["evidence"]
        self.assertEqual(ev["last_commit_url"], f"https://github.com/{REPO}/commit/{sha}")
        self.assertEqual(ev["branch_url"], f"https://github.com/{REPO}/tree/autopilot/aws-worker")
        self.assertEqual((ev["ci"], ev["pr_url"], ev["changed_files"]), ("unverified", "", ["app.py"]))
        progress = {p["id"]: p for p in o["progress"]}
        self.assertEqual((progress["factory_builder"]["done"], progress["factory_builder"]["total"]), (39, 45))
        self.assertEqual((progress["roadmap"]["done"], progress["roadmap"]["total"]), (1, 6))
        self.assertEqual(progress["factory_builder"]["percent"], 86.7)
        self.assertNotEqual(progress["factory_builder"]["source"], progress["roadmap"]["source"])
        human = {b["id"]: b for b in o["human_blockers"]}
        self.assertEqual(set(human), {"T-905", "T-906"})
        self.assertTrue(human["T-905"]["answered"])
        self.assertEqual(human["T-906"]["action"], "answers_md")
        self.assertEqual(human["T-906"]["roadmap_url"], f"https://github.com/{REPO}/blob/main/ROADMAP.md#L157")
        self.assertEqual(o["timeline"][0]["source"], "worker_result")

    def test_bad_repo_or_sha_gives_no_link(self):
        o = build_worker_overview(self.live(), self.board(self.fresh()), results=[{"task_id": "T-1", "commit": "zz", "received_at": 1}],
                                  repo="evil/../x")
        self.assertEqual((o["evidence"]["last_commit_url"], o["evidence"]["branch_url"]), ("", ""))

    def test_heatmap_zero_vs_unknown_kyiv(self):
        # 2026-10-30 22:30 UTC is already 2026-10-31 in Kyiv (UTC+2 after the DST switch).
        now = datetime(2026, 10, 31, 12, 0, tzinfo=timezone.utc).timestamp()
        late = datetime(2026, 10, 30, 22, 30, tzinfo=timezone.utc).timestamp()
        first = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc).timestamp()
        results = [{"task_id": "T-0", "result": "blocked", "received_at": first},
                   {"task_id": "T-1", "result": "done", "commit": "abcdef1", "received_at": late},
                   {"task_id": "T-2", "result": "done", "commit": "", "received_at": late}]
        h = _heatmap([], results, now)
        cells = {c["date"]: c for c in h["cells"]}
        self.assertEqual(len(h["cells"]), 28)
        self.assertEqual(h["cells"][-1]["date"], "2026-10-31")
        if h["timezone"] == "Europe/Kyiv":
            self.assertEqual((cells["2026-10-31"]["state"], cells["2026-10-31"]["tasks"]), ("active", ["T-1"]))
        self.assertEqual(cells["2026-10-26"]["state"], "zero")
        self.assertEqual(cells["2026-10-24"]["state"], "unknown")
        self.assertIsNone(cells["2026-10-24"]["count"])
        self.assertTrue(all(c["state"] == "unknown" for c in _heatmap([], [], now)["cells"]))


class TestTelegramMatchesWeb(OverviewCase):
    def send(self, board, lang):
        sent = []
        update = {"message": {"chat": {"id": int(CHAT), "type": "private"}, "text": "/status", "from": {"language_code": lang}}}
        relay_handle_telegram_update(update, self.store, lambda: {"chat_id": CHAT},
                                     lambda method, payload=None: sent.append((method, payload)) or {"ok": True},
                                     queue=self.queue, lane_board_provider=lambda: board)
        return next(p["text"] for m, p in sent if m == "sendMessage")

    def test_status_shows_same_task_stage_and_sources(self):
        for name in ("offline", "stale", "idle", "running", "blocked"):
            self.tearDown(); self.setUp()
            o = getattr(self, "fixture_" + name)()
            board = {**self.last_board, "worker_overview": o}
            for lang in ("en", "uk", "ru"):
                text = self.send(board, lang)
                t = TEXT[lang]
                self.assertIn(t["title"], text, (name, lang))
                self.assertIn(t["ec2_note"], text)
                line = next(l for l in text.splitlines() if l.split(" ", 1)[-1].startswith(t["current_task"] + ":"))
                if o["task_id"]:
                    self.assertIn(o["task_id"] + " · " + o["stage"], line)
                    self.assertIn(o["task_id"], text.split(t["title"])[0])  # the lane line names the same task
                else:
                    self.assertNotIn("T-90", line)
                self.assertIn("T-906", text)  # open HUMAN blocker listed
        self.assertEqual(worker_overview_text({}, "de").splitlines()[0], "— " + TEXT["ru"]["title"] + " —")


def ui_program():
    html = HTML.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    lane = script.split("// --- lane-board:begin", 1)[1].split("\n", 1)[1].split("// --- lane-board:end", 1)[0]
    block = script.split("// --- worker-overview:begin", 1)[1].split("\n", 1)[1].split("// --- worker-overview:end", 1)[0]
    dc = script.split("// --- delegation-center:begin", 1)[1].split("\n", 1)[1].split("// --- delegation-center:end", 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    assigns = "\n".join(l for l in script.splitlines() if l.startswith("Object.assign(I18N.") and ('"wo.' in l or '"lb.' in l or '"dc.' in l))
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return html, block, "let LANG='en';\n" + helpers + "\n" + i18n + "\n" + assigns + "\n" + tr + "\n" + dc + "\n" + lane + "\n" + block


class TestWebRenderer(OverviewCase):
    def test_static_wiring_and_locale_parity(self):
        html, block, _ = ui_program()
        self.assertIn("/api/factory/worker-overview", html)
        self.assertIn("renderWorkerOverview(woLast)", html)
        self.assertIn('id="officeWorkers"', html)  # Agent Office worker chips
        self.assertNotIn("innerHTML", block)
        self.assertNotIn("fetch(", block)
        self.assertIsNone(re.search(r"token|api_key|password|secret", block, re.I))
        keys = set(re.findall(r"tr\('(wo\.[a-zA-Z_.]*[a-zA-Z_])'", block))
        keys |= {f"wo.s.{s}" for s in ("host", "ec2_api", "systemd", "oauth", "heartbeat", "relay_claim", "current_task")}
        keys |= {f"wo.state.{s}" for s in ("ok", "warn", "fail", "idle", "unknown")}
        keys |= {f"wo.p.{s}" for s in ("factory_builder", "roadmap", "claude_lane")}
        keys |= {f"wo.ci.{s}" for s in ("unverified", "passed", "failed")}
        keys |= {f"wo.h.{s}" for s in ("answered", "open", "verify", "action")}
        keys |= {"wo.v." + v for v in ("never_reported", "no_recent_heartbeat", "describe_instances_not_granted",
                                       "supervisor_not_reported", "supervisor_report_stale", "subscription_logged_in",
                                       "subscription_logged_out", "self_reported", "not_reported", "online", "stale",
                                       "never_seen", "claim_without_fresh_event", "lane_stale", "last_run_blocked",
                                       "no_active_claim", "heartbeat_only", "none")}
        for key in keys:
            self.assertEqual(html.count(f'"{key}":'), 3, f"{key} must exist in EN/UK/RU")

    def test_fixture_rendering(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required for the worker overview rendering check")
            self.skipTest("node is not installed")
        fixtures, boards = {}, {}
        for name in ("offline", "stale", "idle", "running", "blocked"):
            self.tearDown(); self.setUp()
            fixtures[name] = getattr(self, "fixture_" + name)()
            boards[name] = self.last_board
        fixtures["running"]["human_blockers"][0]["title"] = "<script>alert(1)</script>"
        _, _, code = ui_program()
        program = code + "\nconst fx=" + json.dumps(fixtures) + ",bx=" + json.dumps(boards) + ",out={};" \
            "for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fx)){out[lang+':'+k]=renderWorkerOverview(fx[k]);out[lang+':office:'+k]=renderOfficeWorkers(bx[k])}}" \
            "process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        out = json.loads(result.stdout)
        titles = {"en": "Claude worker", "uk": "Claude-виконавець", "ru": "Claude-исполнитель"}
        for key, html in out.items():
            parts = key.split(":")
            lang, name = parts[0], parts[-1]
            if parts[1] == "office":
                self.assertIn('data-lane="claude"', html)
                self.assertIn('onclick="openDelegationCenter()"', html)
                continue
            o = fixtures[name]
            self.assertIn(titles[lang], html, key)
            self.assertIn(f'data-task="{o["task_id"]}" data-stage="{o["stage"]}" data-lane-state="{o["lane_state"]}"', html, key)
            for s in o["signals"]:
                self.assertIn(f'data-signal="{s["id"]}" data-state="{s["state"]}"', html, key)
            self.assertIn('data-signal="ec2_api" data-state="unknown"', html)
            self.assertIn('data-ci="unverified"', html)
            self.assertEqual(html.count('class="woCell '), 28 + 3, key)  # 28 days + legend
            self.assertIn('data-human="T-906" data-answered="0"', html)
            self.assertIsNone(re.search(r">(wo|lb|dc)\.[a-z]", html), key)  # no raw i18n keys
            self.assertNotIn("<script>alert", html)
        self.assertIn("ec2:DescribeInstances", out["en:offline"])
        self.assertIn("не офлайн", out["uk:offline"])
        self.assertIn("не офлайн", out["ru:offline"])
        self.assertIn('data-state="working"', out["en:office:running"])


if __name__ == "__main__":
    unittest.main()
