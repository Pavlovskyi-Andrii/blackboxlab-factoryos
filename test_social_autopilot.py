"""T-702 Social autopilot: plan, approval modes, exactly-once scheduler, Telegram/LinkedIn adapters, summary, routes.
Offline: fake HTTP and clock, handlers called directly (no TestClient: CI has no httpx)."""
import asyncio
import datetime as dt
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-social-"))

from fastapi import FastAPI, HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

import linkedin_publisher as lp  # noqa: E402
import social_autopilot as sa  # noqa: E402
from oauth_framework import MemoryTokenVault, OAuthFlow, TokenSet  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent
TOKEN = "123456:SECRET_BOT_TOKEN_abcdefghijklmnopqrstuvw"
ON = {"FACTORY_SOCIAL_AUTOPILOT_ENABLED": "1"}


def kyiv(stamp: str) -> int:
    return int(dt.datetime.strptime(stamp, "%Y-%m-%dT%H:%M").replace(tzinfo=sa.KYIV).timestamp())


class Clock:
    def __init__(self, stamp="2026-11-18T12:00"):
        self.now = kyiv(stamp)

    def __call__(self):
        return self.now


class FakeHttp:
    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append((method, url, dict(headers), body))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        status, hdrs, payload = answer
        return status, hdrs, json.dumps(payload).encode() if isinstance(payload, dict) else (payload or b"")


def tg_ok(mid=42, username="blackboxlab"):
    return (200, {}, {"ok": True, "result": {"message_id": mid, "chat": {"id": -1001234567890, "username": username}}})


class FakeAdapter(sa.Adapter):
    def __init__(self, name, *answers, blockers=()):
        self.name, self.answers, self.sent, self._blockers = name, list(answers), [], list(blockers)
        self.max_chars = 3000 if name == "linkedin" else 4096
        self.on_publish = None
        self.images = []

    def blockers(self):
        return list(self._blockers)

    def publish(self, text, image=None, alt=""):
        self.sent.append(text)
        self.images.append((image, alt))
        if self.on_publish:
            self.on_publish()
        answer = self.answers.pop(0) if self.answers else {"url": f"https://t.me/x/{len(self.sent)}", "external_id": "1"}
        if isinstance(answer, Exception):
            raise answer
        return answer


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.env = dict(ON)
        self.store = sa.Store(pathlib.Path(self.tmp.name), clock=self.clock)
        self.tg = FakeAdapter("telegram")
        self.li = FakeAdapter("linkedin")
        self.notes = []
        self.ideas = []
        self.pilot = sa.Autopilot(self.store, {"telegram": self.tg, "linkedin": self.li},
                                  notify=lambda text: self.notes.append(text) or True,
                                  ideas=lambda: self.ideas, env=self.env, clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def item(self, platform="telegram", text="A post about our factory and its first week", at="2026-11-18T13:00"):
        return self.store.create(platform, text, kyiv(at))


class TelegramAdapterTest(unittest.TestCase):
    def adapter(self, http, channel="@blackboxlab", token=TOKEN):
        return sa.TelegramChannelAdapter(lambda: token, lambda: channel, http)

    def test_send_message_shape_and_link(self):
        http = FakeHttp(tg_ok(77))
        out = self.adapter(http).publish("Hello <b>literal</b>")
        self.assertEqual(out, {"url": "https://t.me/blackboxlab/77", "external_id": "77"})
        method, url, _, body = http.calls[0]
        self.assertEqual((method, url), ("POST", f"https://api.telegram.org/bot{TOKEN}/sendMessage"))
        sent = json.loads(body)
        self.assertEqual((sent["chat_id"], sent["text"]), ("@blackboxlab", "Hello <b>literal</b>"))
        self.assertNotIn("parse_mode", sent)
        private = self.adapter(FakeHttp(tg_ok(5, username="")), channel="-1001234567890").publish("x")
        self.assertEqual(private["url"], "https://t.me/c/1234567890/5")

    def test_errors_are_fixed_codes_and_uncertainty(self):
        cases = [((401, {}, {"ok": False, "description": TOKEN}), "telegram_auth_failed", False),
                 ((403, {}, {"ok": False}), "telegram_bot_not_admin", False),
                 ((400, {}, {"ok": False, "description": "chat not found"}), "telegram_bad_request", False),
                 ((429, {}, {"ok": False}), "telegram_rate_limited", False),
                 ((502, {}, b"gateway"), "telegram_rejected_502", True),
                 ((200, {}, {"ok": True, "result": {}}), "telegram_sent_without_id", True),
                 (TimeoutError(), "telegram_outcome_uncertain", True), (OSError(), "telegram_outcome_uncertain", True)]
        for answer, code, uncertain in cases:
            with self.assertRaises(sa.PublishError, msg=code) as err:
                self.adapter(FakeHttp(answer)).publish("hi")
            self.assertEqual((err.exception.code, err.exception.uncertain), (code, uncertain))
            self.assertNotIn("SECRET", str(err.exception))

    def test_blockers_and_no_network_when_not_ready(self):
        http = FakeHttp()
        self.assertEqual(self.adapter(http, channel="").blockers(), ["telegram_channel_missing"])
        self.assertEqual(self.adapter(http, channel="my channel").blockers(), ["telegram_channel_invalid"])
        self.assertEqual(self.adapter(http, token="").blockers(), ["telegram_bot_missing"])
        with self.assertRaises(sa.PublishError):
            self.adapter(http, token="").publish("x")
        self.assertEqual(self.adapter(http, channel="").check(), {"ok": False, "code": "telegram_channel_missing"})
        self.assertEqual(http.calls, [])

    def test_check_admin_preflight_posts_nothing(self):
        me = (200, {}, {"ok": True, "result": {"id": 999}})
        admin = (200, {}, {"ok": True, "result": {"status": "administrator", "can_post_messages": True}})
        http = FakeHttp(me, admin)
        self.assertEqual(self.adapter(http).check(), {"ok": True, "code": "telegram_ready"})
        self.assertEqual([c[1].rsplit("/", 1)[1] for c in http.calls], ["getMe", "getChatMember"])
        member = (200, {}, {"ok": True, "result": {"status": "member"}})
        self.assertEqual(self.adapter(FakeHttp(me, member)).check()["code"], "telegram_bot_not_admin")
        self.assertEqual(self.adapter(FakeHttp(me, (400, {}, {"ok": False}))).check()["code"], "telegram_channel_not_found")
        self.assertEqual(self.adapter(FakeHttp(TimeoutError())).check()["code"], "telegram_unreachable")


class LinkedInAdapterTest(unittest.TestCase):
    def test_reuses_linkedin_publisher_path_and_codes(self):
        vault, http = MemoryTokenVault(), FakeHttp()
        flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), vault,
                         adapters={"linkedin": lp.LinkedInOAuthAdapter(http)})
        env = {"FACTORY_LINKEDIN_ENABLED": "1"}
        creds = {"FACTORY_OAUTH_LINKEDIN_CLIENT_ID": "cid", "FACTORY_OAUTH_LINKEDIN_CLIENT_SECRET": "cs"}
        adapter = sa.LinkedInAdapter(flow, lambda: "default", env=env)
        with mock.patch.dict(os.environ, creds):
            self.assertEqual(adapter.blockers(), ["linkedin_not_connected"])
            with self.assertRaises(sa.PublishError) as err:
                adapter.publish("x")
            self.assertEqual(err.exception.code, "linkedin_not_ready")
            vault.put("default", "linkedin", TokenSet(access_token="AT", account_id="urn:li:person:abc"))
            self.assertEqual(adapter.blockers(), [])
            http.answers.append((201, {"x-restli-id": "urn:li:share:5"}, b""))
            self.assertEqual(adapter.publish("hello #ai"),
                             {"url": "https://www.linkedin.com/feed/update/urn:li:share:5", "external_id": "urn:li:share:5"})
            self.assertEqual(json.loads(http.calls[0][3])["commentary"], r"hello \#ai")
            http.answers.append((503, {}, b""))
            with self.assertRaises(sa.PublishError) as err:
                adapter.publish("again")
            self.assertEqual((err.exception.code, err.exception.uncertain), ("linkedin_rejected_503", True))
            env["FACTORY_LINKEDIN_ENABLED"] = "0"
            self.assertEqual(adapter.blockers(), ["linkedin_publishing_off"])


class StoreTest(Base):
    def test_edit_drops_approval_and_sent_items_are_frozen(self):
        i = self.item()
        self.store.approve(i["id"])
        edited = self.store.edit(i["id"], text="Changed text for the channel post")
        self.assertEqual((edited["status"], edited["approved_hash"]), ("draft", ""))
        self.assertIsNone(self.store.claim(i["id"]))
        self.store.approve(i["id"])
        self.assertEqual(self.store.claim(i["id"])["status"], "publishing")
        self.assertIsNone(self.store.claim(i["id"]))                       # never twice
        for call in (lambda: self.store.edit(i["id"], text="x"), lambda: self.store.delete(i["id"]),
                     lambda: self.store.approve(i["id"])):
            with self.assertRaises(HTTPException):
                call()
        with self.assertRaises(HTTPException):
            self.store.approve("../x")

    def test_validation(self):
        for platform, text in (("telegram", ""), ("x", "hi"), ("linkedin", "y" * 3001)):
            with self.assertRaises(HTTPException):
                self.store.create(platform, text, kyiv("2026-11-19T10:00"), max_chars=3000 if platform == "linkedin" else 4096)
        for bad in ("2026-11-19 10:00", "2026-02-30T10:00", "", "2026-11-19T25:00"):
            with self.assertRaises(HTTPException):
                sa.parse_local(bad)
        self.assertEqual(sa.local_label(sa.parse_local("2026-07-01T09:30")), "2026-07-01T09:30")   # summer time

    def test_modes(self):
        a, b = self.item(at="2026-11-19T10:00"), self.item(at="2026-11-20T10:00")
        past = self.item(at="2026-11-18T09:00")
        self.assertEqual(sorted(self.store.approve_plan(0, 2 ** 40)), sorted([a["id"], b["id"]]))   # past stays draft
        self.assertEqual(next(i for i in self.store.snapshot()["items"] if i["id"] == past["id"])["status"], "draft")
        self.store.update_settings({"mode": "each"})
        with self.assertRaises(HTTPException):
            self.store.approve_plan(0, 2 ** 40)
        with self.assertRaises(HTTPException) as err:
            self.store.update_settings({"mode": "rules"})                 # opt-in required
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(sa.DEFAULT_SETTINGS["mode"], "plan")
        self.assertFalse(sa.DEFAULT_SETTINGS["rules_opt_in"])
        s = self.store.update_settings({"mode": "rules", "rules_opt_in": True,
                                        "rules": {"banned_words": "казино, crypto", "max_per_day": 99}})
        self.assertEqual((s["mode"], s["rules"]["banned_words"], s["rules"]["max_per_day"]),
                         ("rules", ["казино", "crypto"], sa.HARD_DAILY_CAP))
        with self.assertRaises(HTTPException):
            self.store.update_settings({"mode": "auto"})


class TickTest(Base):
    def test_kill_switch_and_stop_send_nothing(self):
        i = self.item(at="2026-11-18T11:59")
        self.store.approve(i["id"])
        self.env.clear()
        self.assertEqual(self.pilot.tick()["off"], "autopilot_disabled")
        self.env.update(ON)
        self.store.set_paused(True)
        self.assertEqual(self.pilot.tick()["off"], "paused")
        self.assertEqual(self.tg.sent, [])
        self.store.set_paused(False)
        self.assertEqual(self.pilot.tick()["sent"], [i["id"]])

    def test_publishes_due_approved_once_and_not_future_or_drafts(self):
        due = self.item(at="2026-11-18T11:00")
        later = self.item(at="2026-11-18T15:00")
        draft = self.item(at="2026-11-18T11:30")
        self.store.approve(due["id"])
        self.store.approve(later["id"])
        out = self.pilot.tick()
        self.assertEqual(out["sent"], [due["id"]])
        self.assertEqual(self.pilot.tick()["sent"], [])
        self.assertEqual(len(self.tg.sent), 1)
        items = {i["id"]: i for i in self.store.snapshot()["items"]}
        self.assertEqual(items[due["id"]]["status"], "published")
        self.assertEqual(items[due["id"]]["result"]["url"], "https://t.me/x/1")
        self.assertEqual(items[draft["id"]]["status"], "draft")              # mode A: drafts wait for the owner
        self.clock.now = kyiv("2026-11-18T15:01")
        self.assertEqual(self.pilot.tick()["sent"], [later["id"]])

    def test_uncertain_and_failed_are_never_retried(self):
        a, b = self.item(at="2026-11-18T11:00"), self.item(platform="linkedin", at="2026-11-18T11:01")
        self.store.approve(a["id"])
        self.store.approve(b["id"])
        self.tg.answers.append(sa.PublishError("telegram_outcome_uncertain", uncertain=True))
        self.li.answers.append(sa.PublishError("linkedin_permission_denied"))
        out = self.pilot.tick()
        self.assertEqual((out["uncertain"], out["failed"]), ([a["id"]], [b["id"]]))
        self.pilot.tick()
        self.assertEqual((len(self.tg.sent), len(self.li.sent)), (1, 1))
        with self.assertRaises(HTTPException):
            self.store.confirm(a["id"], "javascript:alert(1)")
        self.assertEqual(self.store.confirm(a["id"], "https://t.me/blackboxlab/9")["status"], "published")
        self.store.approve(b["id"])                                          # owner re-approves a failed item
        self.assertEqual(self.pilot.tick()["sent"], [b["id"]])

    def test_unexpected_exception_is_uncertain(self):
        i = self.item(at="2026-11-18T11:00")
        self.store.approve(i["id"])
        self.tg.answers.append(ValueError("boom"))
        self.assertEqual(self.pilot.tick()["uncertain"], [i["id"]])

    def test_restart_mid_send_becomes_uncertain(self):
        i = self.item(at="2026-11-18T11:00")
        self.store.approve(i["id"])
        self.store.claim(i["id"])                                            # crash after the claim
        fresh = sa.Store(pathlib.Path(self.tmp.name), clock=self.clock)
        self.assertEqual(fresh.recover_interrupted(), 1)
        self.pilot.tick()
        self.assertEqual(self.tg.sent, [])
        self.assertEqual(fresh.snapshot()["items"][0]["result"], {"code": "interrupted_by_restart"})

    def test_missed_window_and_blocked_platform_waits(self):
        old = self.item(at="2026-11-18T05:00")
        self.store.approve(old["id"])
        blocked = self.item(platform="linkedin", at="2026-11-18T11:00")
        self.store.approve(blocked["id"])
        self.li._blockers = ["linkedin_not_connected"]
        out = self.pilot.tick()
        self.assertEqual((out["missed"], out["waiting"]), ([old["id"]], [blocked["id"]]))
        items = {i["id"]: i for i in self.store.snapshot()["items"]}
        self.assertEqual(items[blocked["id"]]["waiting"], ["linkedin_not_connected"])
        self.assertEqual(items[blocked["id"]]["status"], "approved")
        self.assertEqual(self.li.sent, [])

    def test_stop_pressed_during_a_run_stops_the_next_item(self):
        a, b = self.item(at="2026-11-18T11:00"), self.item(at="2026-11-18T11:01")
        self.store.approve(a["id"])
        self.store.approve(b["id"])
        self.tg.on_publish = lambda: self.store.set_paused(True)
        out = self.pilot.tick()
        self.assertEqual((out["sent"], out.get("off")), ([a["id"]], "paused"))
        self.assertEqual(len(self.tg.sent), 1)

    def test_rules_mode(self):
        self.store.update_settings({"mode": "rules", "rules_opt_in": True,
                                    "rules": {"banned_words": ["casino"], "topics": ["factory"], "max_per_day": 1}})
        good = self.item(at="2026-11-18T11:00")
        banned = self.item(text="Our factory now has a casino corner", at="2026-11-18T11:01")
        off_topic = self.item(text="Some unrelated words about cats and dogs", at="2026-11-18T11:02")
        second = self.item(text="Another factory update for the channel", at="2026-11-18T11:03")
        out = self.pilot.tick()
        self.assertEqual(out["sent"], [good["id"]])
        items = {i["id"]: i for i in self.store.snapshot()["items"]}
        self.assertEqual(items[good["id"]]["approved_by"], "rules")
        self.assertIn("banned_word", items[banned["id"]]["waiting"])
        self.assertIn("topic_not_allowed", items[off_topic["id"]]["waiting"])
        self.assertEqual(items[second["id"]]["waiting"], ["daily_limit"])
        for x in (banned, off_topic, second):
            self.assertEqual(items[x["id"]]["status"], "draft")
        # Without the opt-in (owner switched back to plan mode) drafts never auto-publish.
        self.store.update_settings({"mode": "plan"})
        self.clock.now = kyiv("2026-11-19T11:00")
        late = self.item(text="A factory draft in plan mode", at="2026-11-19T10:59")
        self.assertEqual(self.pilot.tick()["sent"], [])
        self.assertEqual(next(i for i in self.store.snapshot()["items"] if i["id"] == late["id"])["status"], "draft")

    def test_hard_daily_cap(self):
        ids = [self.item(text=f"Approved post number {n} for today", at=f"2026-11-18T11:{n:02d}")["id"]
               for n in range(sa.HARD_DAILY_CAP + 1)]
        self.clock.now = kyiv("2026-11-18T11:59")
        for i in ids:
            self.store.approve(i)
        out = self.pilot.tick()
        self.assertEqual(len(out["sent"]), sa.HARD_DAILY_CAP)
        self.assertEqual(len(out["waiting"]), 1)


class PlanAndSummaryTest(Base):
    def test_propose_week_uses_content_brain_ideas_without_llm(self):
        self.ideas = [{"id": "i1", "title": "Idea one", "angle": "Why it matters", "status": "selected",
                       "source_links": ["https://example.com/a", "javascript:x"], "topic": "factory"},
                      {"id": "i2", "title": "Idea two", "status": "generated"},
                      {"id": "i3", "title": "Rejected", "status": "rejected"}]
        self.store.update_settings({"plan_days": 2, "slots": {"telegram": ["10:00"], "linkedin": ["09:30"]}})
        out = self.pilot.propose_week()
        self.assertEqual((out["paid_calls"], out["start"], out["days"]), (0, "2026-11-19", 2))
        items = self.store.snapshot()["items"]
        self.assertEqual(len(items), 4)                                   # 2 ideas × 2 platforms
        self.assertEqual(out["empty_slots"], 0)
        first = next(i for i in items if i["source"] == "content_idea:i1:telegram")
        self.assertEqual(first["text"], "Idea one\n\nWhy it matters\n\nhttps://example.com/a")
        self.assertEqual((first["created_by"], first["status"], sa.local_label(first["planned_at"])),
                         ("factory_plan", "draft", "2026-11-19T10:00"))
        self.assertFalse(any("Rejected" in i["text"] for i in items))
        again = self.pilot.propose_week()
        self.assertEqual((again["created"], again["empty_slots"]), ([], 0))   # slots taken, ideas not reused
        self.store.update_settings({"plan_days": 3})
        self.assertEqual(self.pilot.propose_week()["empty_slots"], 2)

    def test_daily_summary_once_after_21_kyiv(self):
        i = self.item(at="2026-11-18T11:00")
        self.store.approve(i["id"])
        self.pilot.tick()
        self.item(at="2026-11-19T10:00")
        self.assertFalse(self.pilot.maybe_send_summary())                 # 12:00 Kyiv
        self.clock.now = kyiv("2026-11-18T21:05")
        self.assertTrue(self.pilot.maybe_send_summary())
        self.assertFalse(self.pilot.maybe_send_summary())                 # once per day
        text = self.notes[0]
        self.assertIn("Опубликовано: 1", text)
        self.assertIn("https://t.me/x/1", text)
        self.assertIn("ждут вашего одобрения: 1", text)
        self.env.clear()
        self.clock.now = kyiv("2026-11-19T21:05")
        self.assertFalse(self.pilot.maybe_send_summary())                 # kill switch: no notification either


def call(endpoint, *args, role="owner", body=None):
    raw = json.dumps(body or {}).encode()

    async def receive():
        return {"type": "http.request", "body": raw, "more_body": False}
    request = Request({"type": "http", "method": "POST", "headers": [(b"x-role", role.encode())], "path": "/",
                       "query_string": b""}, receive)
    result = endpoint(*args, request)
    return asyncio.run(result) if asyncio.iscoroutine(result) else result


class RoutesAndMcpTest(Base):
    def setUp(self):
        super().setUp()
        app = FastAPI()
        self.check_http = FakeHttp()
        tg = sa.TelegramChannelAdapter(lambda: TOKEN, lambda: "", self.check_http)
        sa.install_routes(app, pilot=self.pilot, identity=lambda r: {"role": r.headers.get("x-role")}, telegram=tg)
        self.ep = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", ()) or ()))): r.endpoint
                   for r in app.routes}
        self.paths = {p for p, _ in self.ep}

    def route(self, path, *args, **kw):
        ep = next(e for (p, _), e in self.ep.items() if p == path)
        return call(ep, *args, **kw)

    def test_every_route_is_owner_only(self):
        for path in self.paths:
            if not path.startswith("/api/factory/social"):
                continue
            args = ("sp_000000000000",) if "{item_id}" in path else ()
            with self.assertRaises(HTTPException, msg=path) as err:
                self.route(path, *args, role="member")
            self.assertEqual(err.exception.status_code, 403, path)

    def test_owner_flow(self):
        item = self.route("/api/factory/social/items", body={"platform": "telegram", "planned_local": "2026-11-19T10:00",
                                                             "text": "Hello channel"})["item"]
        self.route("/api/factory/social/items/{item_id}/edit", item["id"], body={"planned_local": "2026-11-19T11:00"})
        approved = self.route("/api/factory/social/plan/approve")["approved"]
        self.assertEqual(approved, [item["id"]])
        state = self.route("/api/factory/social")
        self.assertEqual(state["items"][0]["planned_local"], "2026-11-19T11:00")
        self.assertEqual(state["items"][0]["approved_by"], "owner_plan")
        self.assertEqual(state["platforms"]["telegram"]["blockers"], [])     # fake adapters
        self.assertEqual(self.route("/api/factory/social/stop")["settings"]["paused"], True)
        self.assertIn("paused", self.route("/api/factory/social")["blockers"])
        self.assertEqual(self.route("/api/factory/social/resume")["settings"]["paused"], False)
        self.assertEqual(self.route("/api/factory/social/telegram/check"),
                         {"ok": False, "code": "telegram_channel_missing"})
        self.assertEqual(self.check_http.calls, [])
        with self.assertRaises(HTTPException):
            self.route("/api/factory/social/items", body={"platform": "linkedin", "planned_local": "2026-11-19T10:00",
                                                          "text": "x" * 3001})

    def test_mcp_agents_can_only_add_drafts(self):
        self.store.update_settings({"rules": {"tone": "дружелюбно, без кликбейта"}})
        out = sa.call_tool(self.pilot, "social_plan_propose",
                           {"platform": "telegram", "text": "Agent draft", "planned_local": "2026-11-20T10:00"}, "gemini")
        self.assertEqual(out["status"], "draft")
        view = sa.call_tool(self.pilot, "social_plan_list", {})
        self.assertEqual((view["tone"], view["items"][0]["id"]), ("дружелюбно, без кликбейта", out["id"]))
        self.assertEqual(self.store.snapshot()["items"][0]["created_by"], "agent:gemini")
        with self.assertRaises(HTTPException):
            sa.call_tool(self.pilot, "social_plan_propose",
                         {"platform": "telegram", "text": "late", "planned_local": "2026-11-18T10:00"})
        with self.assertRaises(HTTPException):
            sa.call_tool(self.pilot, "social_plan_approve", {"id": out["id"]})
        self.assertEqual({t["name"] for t in sa.MCP_TOOLS}, {"social_plan_list", "social_plan_propose"})


class WiringAndPageTest(unittest.TestCase):
    def test_app_wiring(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("social_autopilot.install_routes(app", src)
        self.assertIn("+social_autopilot.MCP_TOOLS", src)
        self.assertIn("SOCIAL_AUTOPILOT.store.recover_interrupted()", src)
        self.assertIn('os.environ.get("FACTORY_TELEGRAM_CHANNEL_ID"', src)
        self.assertLess(src.index("def _durable_engine_startup"), src.index("async def start_social_autopilot"))

    def test_page_languages_and_script(self):
        html = (ROOT / "static/social/index.html").read_text(encoding="utf-8")
        for lang in ("ru", "uk", "en"):
            self.assertIn(f'<option value="{lang}">', html)
        script = re.search(r"<script>(.*?)</script>", html, re.S).group(1)
        blocks = {lang: re.search(rf"\n{lang}:\{{(.*?)\}}\}}(,|;)", script, re.S).group(1) for lang in ("ru", "uk", "en")}
        keys = {lang: set(re.findall(r"(?:^|[,{])\s*([A-Za-z_]+):", b)) for lang, b in blocks.items()}
        self.assertEqual(keys["ru"], keys["uk"])
        self.assertEqual(keys["ru"], keys["en"])
        self.assertIn("проверьте вручную", html)
        node = shutil.which("node")
        if node:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
                fh.write(script)
            try:
                subprocess.run([node, "--check", fh.name], check=True)
            finally:
                os.unlink(fh.name)


if __name__ == "__main__":
    unittest.main()
