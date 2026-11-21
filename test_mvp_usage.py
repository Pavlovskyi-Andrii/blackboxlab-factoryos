"""T-633 consent-aware in-product usage events (#270, M5): no consent → no event, minimal record, returned derived from
dates, per-participant export and delete, funnel counted from events and never typed by hand, caps, kill switch, login
rule per product, page wiring. Offline; handlers are called directly (CI has no httpx)."""
import asyncio
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI

import mvp_evolution as ev
import mvp_usage as mu

ROOT = Path(__file__).resolve().parent
PID = "mybrief-pro"
DAY = 86400
A, B, C = "a" * 32, "b" * 32, "c" * 32


def event(token=A, kind="activated", **kw):
    b = {"action": "event", "event": kind, "consent": True, "consent_version": mu.CONSENT_VERSION, "participant": token}
    b.update(kw)
    return b


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = os.environ.pop("FACTORY_USAGE_EVENTS", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "evo.json"
        self.t = [1_800_000_000.0]
        self.evo = ev.EvolutionStore(self.path, clock=lambda: self.t[0], project_exists=lambda pid: pid in mu.USAGE)
        self.svc = mu.UsageService(self.evo, clock=lambda: self.t[0])

    def tearDown(self):
        self.tmp.cleanup()
        os.environ.pop("FACTORY_USAGE_EVENTS", None)
        if self.saved is not None:
            os.environ["FACTORY_USAGE_EVENTS"] = self.saved

    def code(self, fn):
        with self.assertRaises(ev.EvolutionError) as ctx:
            fn()
        return ctx.exception.code

    def send(self, body, pid=PID, client="10.0.0.1"):
        return self.svc.handle(pid, body, client=client)

    def funnel(self, pid=PID, version="v1"):
        return self.evo.view(pid)["funnel"][version]

    def raw(self):
        return self.path.read_text(encoding="utf-8") if self.path.exists() else ""


class ConsentTest(Base):
    def test_no_consent_no_event(self):
        for bad in ({"consent": False}, {"consent": "true"}, {"consent": 1}, {"consent": None}):
            self.assertEqual(self.code(lambda: self.send(event(**bad))), "consent_required")
        self.assertEqual(self.code(lambda: self.send(event(consent_version="usage-consent-v0"))), "consent_changed")
        self.assertEqual(self.code(lambda: self.send(event(consent_version=None))), "consent_changed")
        self.assertEqual(self.code(lambda: self.evo.record_usage(PID, {"consent": True, "event": "used", "participant": A})),
                         "consent_ref_required")
        self.assertEqual(self.raw(), "")  # nothing was written at all
        self.assertEqual({s: self.funnel()[s] for s in ev.USAGE_STEPS}, {"activated": None, "used": None, "returned": None})

    def test_validation(self):
        self.assertEqual(self.code(lambda: self.send(event(kind="invited"))), "bad_event")
        self.assertEqual(self.code(lambda: self.send(event(kind="page_view"))), "bad_event")
        for token in ("", "short", "x" * 65, "has space " * 3, None, "me@example.com-0123456789"):
            self.assertEqual(self.code(lambda: self.send(event(token=token))), "bad_participant")
        self.assertEqual(self.code(lambda: self.send({"action": "track"})), "bad_action")
        self.assertEqual(self.code(lambda: self.send(event(), pid="unknown-pilot")), "unknown_usage_project")
        self.assertEqual(self.raw(), "")

    def test_record_is_minimal_and_holds_no_identifier(self):
        out = self.send(event(extra="alice@example.com", user_agent="Mozilla", page="/secret"), client="203.0.113.77")
        self.assertEqual(out["recorded"], ["activated"])
        usage = json.loads(self.raw())["projects"][PID]["usage"]["v1"]
        (key, rec), = usage.items()
        self.assertEqual(set(rec), {"consent_ref", "activated", "used", "returned"})
        self.assertEqual(rec, {"consent_ref": f"{PID}-usage:{mu.CONSENT_VERSION}", "activated": "2027-01-15", "used": None, "returned": None})
        self.assertRegex(key, r"^[0-9a-f]{16}$")
        raw = self.raw()
        for leak in (A, "203.0.113.77", "alice@example.com", "Mozilla", "/secret"):
            self.assertNotIn(leak, raw)  # the code, the address and anything extra never reach the file


class FunnelTest(Base):
    def test_funnel_counts_come_from_events(self):
        self.send(event(A))
        self.send(event(B))
        self.send(event(B, "used"))
        self.send(event(C, "used"))  # used implies opened
        f = self.funnel()
        self.assertEqual([f[s]["count"] for s in ev.USAGE_STEPS], [3, 2, 0])
        self.assertEqual({f[s]["source"] for s in ev.USAGE_STEPS}, {ev.USAGE_SOURCE})
        self.assertEqual({f[s]["by"] for s in ev.USAGE_STEPS}, {"events"})
        self.assertIsNone(f["invited"])  # an invitation is never inferred from an event

    def test_repeats_do_not_inflate(self):
        for _ in range(5):
            self.send(event(A))
            self.send(event(A, "used"))
        self.assertEqual(self.send(event(A, "used"))["recorded"], [])
        f = self.funnel()
        self.assertEqual([f[s]["count"] for s in ev.USAGE_STEPS], [1, 1, 0])

    def test_returned_needs_a_later_day(self):
        self.send(event(A))
        self.assertEqual(self.send(event(A, "returned"))["recorded"], [])  # same day: a page cannot claim a return
        self.assertEqual(self.funnel()["returned"]["count"], 0)
        self.t[0] += DAY
        out = self.send(event(A, "returned"))
        self.assertEqual(out["recorded"], ["returned"])
        self.assertEqual(out["events"], {"activated": "2027-01-15", "used": None, "returned": "2027-01-16"})
        self.send(event(B, "returned"))  # a first visit that calls itself a return is just a first visit
        f = self.funnel()
        self.assertEqual([f[s]["count"] for s in ev.USAGE_STEPS], [2, 0, 1])
        self.assertEqual(f["returned"]["at"], "2027-01-16")

    def test_manual_entry_is_refused_for_event_steps(self):
        for step in ev.USAGE_STEPS:
            self.assertEqual(self.code(lambda: self.evo.set_funnel(PID, {"step": step, "count": 99, "source": "my guess"}, actor_role="owner")),
                             "step_from_events")
        self.assertIsNone(self.funnel()["activated"])
        self.evo.set_funnel(PID, {"step": "invited", "count": 7, "source": "owner's sent list"}, actor_role="owner")
        self.assertEqual(self.funnel()["invited"]["count"], 7)  # steps without events stay manual with a source

    def test_a_manual_number_left_in_an_old_file_is_not_shown(self):
        self.evo.set_funnel(PID, {"step": "invited", "count": 7, "source": "s"}, actor_role="owner")
        data = json.loads(self.raw())
        data["projects"][PID]["funnel"]["v1"]["used"] = {"count": 500, "source": "typed before T-633", "at": "x", "by": "owner"}
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertIsNone(self.funnel()["used"])
        self.send(event(A, "used"))
        self.assertEqual(self.funnel()["used"]["count"], 1)

    def test_events_belong_to_the_current_version_and_product(self):
        self.send(event(A, "used"))
        self.send(event(A, "used"), pid="mycast")
        fid = self.evo.add_feedback(PID, {"consent": True, "consent_ref": "note", "participant": "p1", "tried": "yes",
                                          "job": "read my weekly brief", "failed": "no pdf export for my manager"},
                                    actor_role="owner")["feedback"]["id"]
        prop = self.evo.propose(PID, {"title": "PDF", "problem": "p", "change": "c", "acceptance_test": "t", "feedback_ids": [fid]},
                                actor_role="owner")["proposal"]
        self.evo.decide(PID, prop["id"], {"action": "approve"}, actor_role="owner")
        self.evo.decide(PID, prop["id"], {"action": "handoff"}, actor_role="owner",
                        create_ticket=lambda **kw: {"id": "R-0001"})
        self.evo.decide(PID, prop["id"], {"action": "ship", "evidence": [f"{ev.REPO}/pull/1"]}, actor_role="owner")
        self.evo.release(PID, {"evidence": [f"{ev.REPO}/pull/1"]}, actor_role="owner")
        self.assertIsNone(self.funnel(version="v2")["activated"])  # unknown until someone uses v2
        self.send(event(B))
        self.assertEqual(self.funnel(version="v2")["activated"]["count"], 1)
        self.assertEqual(self.funnel(version="v1")["used"]["count"], 1)
        self.assertEqual(self.funnel("mycast")["used"]["count"], 1)
        keys = {pid: set(json.loads(self.raw())["projects"][pid]["usage"]["v1"]) for pid in (PID, "mycast")}
        self.assertFalse(keys[PID] & keys["mycast"])  # the same code is a different participant in another product


class ExportDeleteTest(Base):
    def test_export_returns_only_the_holders_records(self):
        self.send(event(A, "used"))
        self.send(event(B))
        out = self.send({"action": "export", "participant": A})
        self.assertEqual(out["records"], [{"consent_ref": f"{PID}-usage:{mu.CONSENT_VERSION}", "activated": "2027-01-15",
                                           "used": "2027-01-15", "returned": None, "version": "v1"}])
        self.assertEqual(out["fields"], ["version", "consent_ref", "activated", "used", "returned"])
        self.assertEqual(self.send({"action": "export", "participant": C})["records"], [])
        self.assertEqual(self.code(lambda: self.send({"action": "export", "participant": "nope"})), "bad_participant")
        self.assertEqual(self.code(lambda: self.send({"action": "export"})), "bad_participant")

    def test_delete_removes_the_record_and_the_counts(self):
        self.send(event(A, "used"))
        self.send(event(B, "used"))
        self.assertEqual(self.funnel()["used"]["count"], 2)
        self.assertEqual(self.send({"action": "delete", "participant": A}), {"deleted": 1})
        f = self.funnel()
        self.assertEqual([f[s]["count"] for s in ev.USAGE_STEPS], [1, 1, 0])
        self.assertEqual(self.send({"action": "export", "participant": A})["records"], [])
        self.assertEqual(self.send({"action": "delete", "participant": A}), {"deleted": 0})  # repeat is harmless
        self.assertEqual(self.send({"action": "export", "participant": B})["records"][0]["used"], "2027-01-15")
        self.send({"action": "delete", "participant": B})
        self.assertIsNone(self.funnel()["activated"])  # nobody left: unknown again, not a claimed zero
        log = [row for row in self.evo.view(PID)["log"] if row["action"] == "usage_deleted"]
        self.assertEqual([(row["actor"], row["ref"]) for row in log], [("participant", "1"), ("participant", "1")])

    def test_export_and_delete_survive_the_kill_switch(self):
        self.send(event(A, "used"))
        os.environ["FACTORY_USAGE_EVENTS"] = "0"
        self.assertFalse(self.svc.config(PID)["enabled"])
        self.assertEqual(self.code(lambda: self.send(event(B))), "usage_off")
        self.assertEqual(self.funnel()["activated"]["count"], 1)
        self.assertEqual(len(self.send({"action": "export", "participant": A})["records"]), 1)
        self.assertEqual(self.send({"action": "delete", "participant": A}), {"deleted": 1})

    def test_feedback_is_untouched_by_a_usage_delete(self):
        self.evo.add_feedback(PID, {"consent": True, "consent_ref": "note", "participant": A, "tried": "yes"}, actor_role="owner")
        self.send(event(A))
        self.send({"action": "delete", "participant": A})
        self.assertEqual(self.evo.view(PID)["cohort"]["feedback_real"], 1)


class CapsTest(Base):
    def test_one_client_cannot_invent_a_crowd(self):
        tokens = [f"{i:032d}" for i in range(mu.PER_CLIENT_NEW_DAILY + 1)]
        for tok in tokens[:-1]:
            self.send(event(tok))
        self.assertEqual(self.code(lambda: self.send(event(tokens[-1]))), "daily_limit")
        self.assertEqual(self.send(event(tokens[0], "used"))["recorded"], ["used"])  # known participants still count
        self.assertEqual(self.funnel()["activated"]["count"], mu.PER_CLIENT_NEW_DAILY)
        self.send(event(tokens[-1]), client="10.0.0.2")  # another client is not affected
        self.t[0] += DAY
        self.send(event("z" * 32))  # the cap is per day

    def test_call_cap_and_no_address_kept(self):
        self.svc._budget("10.9.9.9")[1] = mu.PER_CLIENT_CALLS_DAILY
        self.assertEqual(self.code(lambda: self.send(event(), client="10.9.9.9")), "daily_limit")
        self.assertEqual(self.code(lambda: self.send({"action": "export", "participant": A}, client="10.9.9.9")), "daily_limit")
        self.assertNotIn("10.9.9.9", repr(self.svc._clients))

    def test_participant_limit_per_version(self):
        old, ev.MAX_USAGE = ev.MAX_USAGE, 2
        try:
            self.evo.record_usage(PID, {"consent": True, "consent_ref": "r", "event": "activated", "participant": A})
            self.evo.record_usage(PID, {"consent": True, "consent_ref": "r", "event": "activated", "participant": B})
            self.assertEqual(self.code(lambda: self.evo.record_usage(
                PID, {"consent": True, "consent_ref": "r", "event": "activated", "participant": C})), "usage_full")
        finally:
            ev.MAX_USAGE = old


class Req:
    def __init__(self, body=None):
        self.body = body

    async def json(self):
        if self.body is ...:
            raise ValueError("not json")
        return self.body


class RouteTest(Base):
    def setUp(self):
        super().setUp()
        self.who = {}
        app = FastAPI()
        mu.install_mvp_usage_routes(app, self.svc, lambda r: dict(self.who), client_fn=lambda r: "1.2.3.4")
        self.routes = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if r.path.endswith("/usage")}

    def call(self, method, path, body=None):
        fn = self.routes[(method, path)]
        out = asyncio.run(fn(request=Req(body))) if asyncio.iscoroutinefunction(fn) else fn(request=Req(body))
        if hasattr(out, "status_code"):
            return out.status_code, json.loads(out.body)
        return 200, out

    def test_one_pair_of_routes_per_pilot(self):
        self.assertEqual({p for _, p in self.routes}, {"/api/mycast/usage", "/api/mybrief/public/usage", "/api/decision-memory/usage"})
        self.assertEqual(len(self.routes), 6)

    def test_public_pilot_needs_no_login_but_needs_consent(self):
        for path in ("/api/mycast/usage", "/api/mybrief/public/usage"):
            st, cfg = self.call("GET", path)
            self.assertEqual((st, cfg["enabled"], cfg["consent_version"], cfg["third_party"]), (200, True, mu.CONSENT_VERSION, False))
            self.assertEqual(self.call("POST", path, event(consent=False)), (400, {"detail": "consent_required"}))
            self.assertEqual(self.call("POST", path, [1])[0], 400)
            self.assertEqual(self.call("POST", path, ...)[0], 400)
            self.assertEqual(self.call("POST", path, event(kind="used"))[1]["recorded"], ["activated", "used"])
            self.assertEqual(len(self.call("POST", path, {"action": "export", "participant": A})[1]["records"]), 1)
            self.assertEqual(self.call("POST", path, {"action": "delete", "participant": A}), (200, {"deleted": 1}))

    def test_decision_memory_stays_behind_the_owner_login(self):
        path = "/api/decision-memory/usage"
        for who, status in (({}, 401), ({"role": "viewer"}, 403), ({"role": "member"}, 403)):
            self.who = who
            self.assertEqual(self.call("GET", path)[0], status)
            self.assertEqual(self.call("POST", path, event())[0], status)
            self.assertEqual(self.call("POST", path, {"action": "export", "participant": A})[0], status)
        self.assertEqual(self.raw(), "")
        self.who = {"role": "owner", "email": "owner@example.com"}
        self.assertEqual(self.call("POST", path, event())[0], 200)
        self.assertNotIn("owner@example.com", self.raw())  # the login is a gate, not an identity in the record

    def test_owner_funnel_route_refuses_manual_event_steps(self):
        app = FastAPI()
        ev.install_mvp_evolution_routes(app, self.evo, lambda r: {"role": "owner"})
        fn = next(r.endpoint for r in app.routes if r.path == "/api/mvp-evolution/{project_id}/funnel")
        out = asyncio.run(fn(PID, Req({"step": "used", "count": 3, "source": "typed"})))
        self.assertEqual((out.status_code, json.loads(out.body)), (409, {"detail": "step_from_events"}))


class PageAndWiringTest(unittest.TestCase):
    js = (ROOT / "static/mycast-configurator/usage.js").read_text(encoding="utf-8")

    def test_widget_asks_first_and_stays_first_party(self):
        js = self.js
        keys = {lang: set(re.findall(r"(\w+): '", re.search(lang + r": \{(.*?)\}", js, re.S).group(1))) for lang in ("uk", "ru", "en")}
        self.assertEqual(keys["uk"], keys["ru"])
        self.assertEqual(keys["uk"], keys["en"])
        self.assertEqual(set(re.findall(r"fetch\(([^,)]+)", js)), {"API"})  # one same-site address, nothing else
        self.assertNotRegex(js, r"https?://")  # no third-party host anywhere in the widget
        for banned in ("google", "gtag", "sendBeacon", "document.cookie", "navigator.userAgent", "mailto:"):
            self.assertNotIn(banned, js)
        # the code is created only inside the Allow handler, and every event goes through the consent check
        self.assertEqual(js.count("newToken()"), 2)
        self.assertIn("mem({token: k.token || newToken(), v: cfg.consent_version}); note = ''; send('activated');", js)
        self.assertIn("function send(event) {\n    if (!consented()) return;", js)
        self.assertIn("action: 'export'", js)
        self.assertIn("action: 'delete'", js)
        self.assertNotRegex(js.split("var UI = {", 1)[1], r"MyCast|MyBrief")  # every text names the product through %P%

    def test_every_pilot_page_carries_the_widget_once(self):
        pages = {"mycast": ("static/mycast-configurator/index.html", '<script src="usage.js" defer></script>'),
                 "mybrief-pro": ("static/mybrief/index.html", '<script src="/static/mycast-configurator/usage.js" defer></script>'),
                 "decision-memory": ("static/decision-memory/index.html", "s.src='/static/mycast-configurator/usage.js'")}
        self.assertEqual(set(pages), set(mu.USAGE))
        keys = []
        for pid, (page, script) in pages.items():
            html = (ROOT / page).read_text(encoding="utf-8")
            self.assertEqual(html.count('id="usage"'), 1)
            tag = re.search(r'<section id="usage"[^>]*>', html).group(0)
            self.assertIn(" hidden", tag)  # shown only after the server says counting is on
            self.assertRegex(tag, r'data-used="[^"]+"')
            if pid == "mycast":
                self.assertNotIn("data-api", tag)  # the widget's default address
                self.assertIn("'/api/mycast/usage'", self.js)
            else:
                self.assertIn(f'data-api="{mu.USAGE[pid]["api"]}"', tag)
                keys.append(re.search(r'data-key="([a-z-]+)"', tag).group(1))
            self.assertEqual(html.count(script), 1)
            self.assertEqual(html.count("usage.js'") + html.count('usage.js"'), 1)
            self.assertLess(html.index('id="usage"'), html.index(script))
            self.assertFalse((ROOT / page).with_name("usage.js").exists() and pid != "mycast")  # reused, not copied
        self.assertEqual(len(set(keys + ["mycast"])), 3)  # consent is remembered per product

    def test_app_wiring_and_login_rules(self):
        app = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mvp_usage_routes(app, UsageService(MVP_EVOLUTION), request_identity, client_fn=_mycast_client_id)", app)
        paths = re.search(r"public_paths = \{(.*?)\}", app, re.S).group(1)
        prefixes = re.search(r"public_prefixes = \((.*?)\)", app).group(1)
        self.assertIn('"/api/mycast/usage"', paths)  # one exact path, not a prefix
        self.assertNotIn("/api/mycast/usage", prefixes)
        self.assertIn('"/api/mybrief/public/"', prefixes)
        self.assertNotIn("decision-memory", paths + prefixes)
        self.assertNotIn("mvp-usage", paths + prefixes)

    def test_owner_page_no_longer_offers_manual_event_steps(self):
        html = (ROOT / "static/mvp-factory/evolution.html").read_text(encoding="utf-8")
        self.assertIn("const EVENT_STEPS=['activated','used','returned'];", html)
        self.assertIn("opts(FUNNEL.filter(s=>!EVENT_STEPS.includes(s)),x)", html)
        self.assertEqual(tuple(re.search(r"const EVENT_STEPS=\[(.*?)\]", html).group(1).replace("'", "").split(",")), ev.USAGE_STEPS)

    def test_module_has_no_outbound_calls(self):
        for name in ("mvp_usage.py",):
            src = (ROOT / name).read_text(encoding="utf-8")
            for banned in ("import requests", "import httpx", "urllib", "smtplib", "http://", "https://"):
                self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main(verbosity=1)
