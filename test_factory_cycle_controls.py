"""T-646 Autopilot Cycle Control for beginners: cycle target, stop/resume, readiness. Offline, zero-spend.

Calls the app functions and route handlers directly (no TestClient: CI has no httpx). Demo mode only:
FACTORY_LLM_API_KEY is empty, so nothing here can reach a paid provider.
"""
import asyncio
import os
import tempfile
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-cycle-controls-")
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ.setdefault("FACTORY_PASSWORD", "")

import app  # noqa: E402
from fastapi import HTTPException  # noqa: E402


def run(x):
    return asyncio.run(x) if asyncio.iscoroutine(x) else x


def signal(title, topic=""):
    return app.ingest_source_signal(app.SignalCreate(title=title, content="fixture", url="https://example.com/" + title.replace(" ", "-"),
                                                     source_type="ci", topic=topic))["signal"]


def idea(title="Cycle controls idea"):
    return app.create_content_idea(app.IdeaCreate(title=title, topic="factory", angle="explain the loop", audience="beginners",
                                                  why_now="T-646", score=0.8))


class CycleControls(unittest.TestCase):
    def test_target_is_validated_and_stored(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"], target={
            "brand": "mycast", "topic": "  ai   news ", "platform": "tiktok", "audience": "students"}))
        self.assertEqual(c["meta"]["target"], {"brand": "mycast", "topic": "ai news", "platform": "tiktok", "audience": "students"})
        with self.assertRaises(ValueError):
            app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"], target={"platform": "myspace"}))
        with self.assertRaises(ValueError):
            app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"], target={"brand": "no-such-brand"}))
        empty = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        self.assertEqual(empty["meta"]["target"], {"brand": "", "topic": "", "platform": "", "audience": ""})

    def test_topic_narrows_new_signals_and_says_so_when_nothing_matches(self):
        a = signal("Robots in warehouses", "robotics")
        b = signal("Quiet cooking tips", "food")
        c = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "robot"}))
        self.assertIn(a["id"], c["source_signal_ids"])
        self.assertNotIn(b["id"], c["source_signal_ids"])
        self.assertTrue(c["meta"]["target_topic_matched"])
        none = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "zzz-unmatched"}))
        self.assertFalse(none["meta"]["target_topic_matched"])
        self.assertIn(b["id"], none["source_signal_ids"])
        self.assertTrue(any("zzz-unmatched" in e["message"] for e in none["events"]))

    def test_stop_and_resume_without_a_running_task(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        r = app.stop_factory_cycle(c["id"])
        self.assertFalse(r["pending"])
        self.assertEqual(r["cycle"]["status"], "stopped")
        # a stopped cycle is not run and not overwritten by sync / the reconcile loop
        with self.assertRaises(HTTPException) as ctx:
            run(app.run_factory_cycle_api(c["id"], app.FactoryCycleRunRequest()))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(app.sync_factory_cycle(c["id"])["status"], "stopped")
        resumed = app.resume_factory_cycle(c["id"])
        self.assertEqual(resumed["status"], "ready")
        self.assertNotIn("stop_requested", resumed["meta"])
        with self.assertRaises(PermissionError):
            app.resume_factory_cycle(c["id"])

    def test_stop_is_refused_after_the_approval_gate(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        app._cycle_update(c["id"], status="waiting_approval", phase="approval")
        with self.assertRaises(PermissionError):
            app.stop_factory_cycle(c["id"])

    def test_pending_stop_halts_the_run_before_production(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        app.active_factory_cycles.add(c["id"])
        r = app.stop_factory_cycle(c["id"])
        app.active_factory_cycles.discard(c["id"])
        self.assertTrue(r["pending"])
        self.assertEqual(r["cycle"]["status"], "ready")
        run(app._run_factory_cycle_to_review(c["id"], 1, "English"))
        after = app.get_factory_cycle(c["id"], True)
        self.assertEqual(after["status"], "stopped")
        self.assertIsNone(after["job_id"], "a stopped cycle must not create a production job")
        self.assertIsNone(after["publish_id"])

    def test_run_applies_target_to_job_and_stops_at_approval(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea("Targeted idea")["id"], target={
            "brand": "mycast", "topic": "ai", "platform": "youtube_shorts", "audience": "new founders"}))
        run(app._run_factory_cycle_to_review(c["id"], 1, "English"))
        after = app.get_factory_cycle(c["id"], True)
        self.assertEqual(after["status"], "waiting_approval")
        self.assertIsNone(after["publish_id"], "Autopilot must never queue publishing before approval")
        self.assertIn("CYCLE TARGET (owner): BRAND: mycast", after["job"]["brief"])
        self.assertIn("TARGET PLATFORM: youtube_shorts", after["job"]["brief"])
        passport, _ = __import__("brand_strategy").brand_for_job(app.STRATEGY, after["job_id"])
        self.assertEqual((passport or {}).get("brand"), "mycast")
        # once a job exists, the target is fixed
        with self.assertRaises(PermissionError):
            app.set_factory_cycle_target(c["id"], {"topic": "other"})

    def test_target_edit_before_production(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        out = run(app.factory_cycle_target_api(c["id"], app.FactoryCycleTarget(topic="space", platform="instagram_reels")))
        self.assertEqual(out["cycle"]["meta"]["target"]["topic"], "space")
        with self.assertRaises(HTTPException) as ctx:
            run(app.factory_cycle_target_api(c["id"], app.FactoryCycleTarget(platform="fax")))
        self.assertEqual(ctx.exception.status_code, 400)
        with self.assertRaises(HTTPException) as ctx:
            run(app.factory_cycle_target_api("missing", app.FactoryCycleTarget()))
        self.assertEqual(ctx.exception.status_code, 404)

    def test_topic_change_reselects_auto_signals(self):
        a = signal("Mars rover finds ice", "space")
        b = signal("Sourdough starter guide", "baking")
        c = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "mars"}))
        self.assertIn(a["id"], c["source_signal_ids"])
        self.assertNotIn(b["id"], c["source_signal_ids"])
        out = app.set_factory_cycle_target(c["id"], {"topic": "sourdough"})
        self.assertIn(b["id"], out["source_signal_ids"], "signals picked by the cycle must follow the new topic")
        self.assertNotIn(a["id"], out["source_signal_ids"])
        self.assertTrue(out["meta"]["target_topic_matched"])
        # signals chosen explicitly by the owner stay as chosen
        manual = app.create_factory_cycle(app.FactoryCycleCreate(signal_ids=[a["id"]], target={"topic": "mars"}))
        kept = app.set_factory_cycle_target(manual["id"], {"topic": "sourdough"})
        self.assertEqual(kept["source_signal_ids"], [a["id"]])

    def test_run_time_topic_fallback_is_explained(self):
        con = app.db()
        con.execute("UPDATE source_signals SET status='used'")
        con.commit()
        con.close()
        c = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "nothing-matches-this"}))
        self.assertEqual(c["source_signal_ids"], [])
        late = signal("Late arriving signal", "misc")
        run(app._run_factory_cycle_to_review(c["id"], 1, "English"))   # demo: fails at idea generation, after attaching
        after = app.get_factory_cycle(c["id"], True)
        self.assertIn(late["id"], after["source_signal_ids"])
        self.assertFalse(after["meta"]["target_topic_matched"])
        self.assertTrue(any("nothing-matches-this" in e["message"] for e in after["events"]))

    def test_brand_link_failure_is_surfaced(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea("Brand link failure")["id"], target={"brand": "mycast"}))
        original = app.STRATEGY.link_job

        def refuse(brand, job_id):
            raise HTTPException(409, "this job belongs to another brand's content plan")
        app.STRATEGY.link_job = refuse
        try:
            run(app._run_factory_cycle_to_review(c["id"], 1, "English"))
        finally:
            app.STRATEGY.link_job = original
        after = app.get_factory_cycle(c["id"], True)
        self.assertEqual(after["status"], "waiting_approval")
        self.assertIn("another brand", after["meta"]["brand_link_error"])
        self.assertTrue(any(e["message"].startswith("WARNING: brand mycast was NOT linked") for e in after["events"]))

    def test_same_idea_with_a_different_target_is_refused(self):
        shared = idea("Shared idea")
        first = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=shared["id"], target={"topic": "alpha", "audience": "kids"}))
        run(app._run_factory_cycle_to_review(first["id"], 1, "English"))
        self.assertEqual(app.get_factory_cycle(first["id"])["status"], "waiting_approval")
        other = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=shared["id"], target={"topic": "beta"}))
        run(app._run_factory_cycle_to_review(other["id"], 1, "English"))
        after = app.get_factory_cycle(other["id"], True)
        self.assertEqual(after["status"], "failed")
        self.assertIn("different target", after["last_error"])
        self.assertIsNone(after["job_id"], "a job made for another target must not be reused")
        same = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=shared["id"], target={"topic": "alpha", "audience": "kids"}))
        run(app._run_factory_cycle_to_review(same["id"], 1, "English"))
        self.assertEqual(app.get_factory_cycle(same["id"])["job_id"], app.get_factory_cycle(first["id"])["job_id"])

    def test_topic_change_finds_matches_beyond_the_newest_batch(self):
        old_match = signal("Volcano eruption footage", "geology")
        for n in range(app.FACTORY_CYCLE_MAX_SIGNALS + 2):
            signal(f"Unrelated newer signal {n}", "misc")
        c = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "unrelated"}))
        out = app.set_factory_cycle_target(c["id"], {"topic": "volcano"})
        self.assertEqual(out["source_signal_ids"], [old_match["id"]])
        self.assertTrue(out["meta"]["target_topic_matched"])
        cyr = signal("Новости вулканов", "Вулканы")
        out = app.set_factory_cycle_target(c["id"], {"topic": "вулкан"})
        self.assertEqual(out["source_signal_ids"], [cyr["id"]], "Cyrillic topics must match case-insensitively")

    def test_stop_during_a_production_step_that_then_fails_stays_stopped(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea("Stop then fail")["id"]))
        original = app.run_until_review

        async def stop_then_fail(job_id):
            app.stop_factory_cycle(c["id"])
            raise RuntimeError("provider exploded")
        app.run_until_review = stop_then_fail
        try:
            run(app._run_factory_cycle_to_review(c["id"], 1, "English"))
        finally:
            app.run_until_review = original
        after = app.get_factory_cycle(c["id"], True)
        self.assertEqual(after["status"], "stopped")
        self.assertIn("provider exploded", after["last_error"])
        self.assertEqual(app.sync_factory_cycle(c["id"])["status"], "stopped", "stays stopped until resumed")

    # T-647: server messages carry a code so the dashboard can show them in EN/UK/RU.
    def test_every_server_message_code_is_translated(self):
        import json
        import re
        html = (__import__("pathlib").Path(__file__).resolve().parent / "static" / "index.html").read_text(encoding="utf-8")
        codes = {code for _, code in app.CYCLE_MESSAGE_CODES} | {"unknown", "stopped_then_failed", "brand_not_linked"}
        for lang in ("en", "uk", "ru"):
            line = next(l for l in html.split("\n") if l.startswith("Object.assign(I18N." + lang + ",{") and '"cycle.srv.not_found"' in l)
            keys = set(json.loads(line[len("Object.assign(I18N." + lang + ","):-2]))
            missing = {c for c in codes if "cycle.srv." + c not in keys}
            self.assertFalse(missing, f"{lang} lacks translations for {missing}")
        self.assertIn("cycleApi('/api/factory-cycles", html)
        self.assertNotRegex(html, r"[^e]api\('/api/factory-cycles", "cycle calls must go through cycleApi")

    def test_real_messages_map_to_codes(self):
        cases = {
            "Live LLM provider is not configured": "llm_not_configured",
            "Daily provider budget would be exceeded by the next Content Brain call": "daily_budget",
            "No source signals are available. Add a signal or configure RSS feeds.": "no_signals",
            "No source signals available": "no_signals",
            "Rejected idea cannot enter production": "idea_rejected",
            "Live-mode idea must pass Content Brain verification before production": "idea_not_verified",
            "Production did not reach the human approval gate": "production_not_at_gate",
            "This cycle is stopped. Resume it first.": "stopped_resume_first",
            "Factory cycle not found": "not_found",
            "Unknown target platform: fax": "bad_platform",
            "No real performance snapshot exists for this cycle yet.": "no_metrics",
        }
        for msg, code in cases.items():
            self.assertEqual(app.cycle_message_info(msg)[0], code, msg)
        self.assertEqual(app.cycle_message_info("Unknown target platform: fax")[1], {"value": "fax"})
        code, params = app.cycle_message_info("This idea already has production job abcd1234 made for a different target "
                                               "(TOPIC: alpha). Start the cycle from another idea, or set the same target.")
        self.assertEqual((code, params), ("job_other_target", {"job": "abcd1234", "have": "TOPIC: alpha"}))
        self.assertEqual(app.cycle_message_info("boom"), ("unknown", {"text": "boom"}))

    def test_failure_stores_code_and_http_errors_carry_it(self):
        signal("Error codes fixture signal", "codes")
        c = app.create_factory_cycle(app.FactoryCycleCreate(target={"topic": "codes"}))
        run(app._run_factory_cycle_to_review(c["id"], 1, "English"))   # demo: no LLM -> idea generation fails
        after = app.get_factory_cycle(c["id"], True)
        self.assertEqual(after["status"], "failed")
        self.assertEqual(after["meta"]["last_error_code"], "llm_not_configured")
        self.assertTrue(any((e["meta"] or {}).get("code") == "llm_not_configured" for e in after["events"]))
        app.stop_factory_cycle(c["id"])
        with self.assertRaises(HTTPException) as ctx:
            run(app.run_factory_cycle_api(c["id"], app.FactoryCycleRunRequest()))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "stopped_resume_first")
        self.assertIn("Resume", ctx.exception.detail["message"])
        app.resume_factory_cycle(c["id"])
        out = run(app.run_factory_cycle_api(c["id"], app.FactoryCycleRunRequest()))
        self.assertEqual(out["message_code"], "started")

    def test_next_cycle_inherits_target(self):
        parent = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"], target={"topic": "kept", "audience": "parents"}))
        child = run(app.next_factory_cycle(parent["id"]))["cycle"]
        self.assertEqual(child["meta"]["target"]["topic"], "kept")
        self.assertEqual(child["parent_cycle_id"], parent["id"])

    def test_listing_has_readiness_and_safety(self):
        idea()
        data = app.factory_cycles()
        rd = data["readiness"]
        self.assertFalse(rd["paid_calls_possible"], "demo mode must report no paid calls")
        self.assertIn("tiktok", rd["platforms"])
        self.assertTrue(any(b["brand"] == "mycast" for b in rd["brands"]))
        self.assertTrue(rd["ideas"])
        self.assertIsInstance(rd["new_signals"], int)
        self.assertIn("human approval", data["safety_note"])
        self.assertNotIn("stopped", ("ready", "running", "waiting_approval"))
        # the dashboard summary helper keeps its old shape (readiness is only on the route)
        self.assertNotIn("readiness", app.get_factory_cycles(5))

    def test_paid_run_still_needs_cost_confirmation(self):
        c = app.create_factory_cycle(app.FactoryCycleCreate(idea_id=idea()["id"]))
        old = app.FACTORY_LLM_API_KEY
        app.FACTORY_LLM_API_KEY = "test-not-used"
        try:
            out = run(app.run_factory_cycle_api(c["id"], app.FactoryCycleRunRequest(confirm_cost=False)))
        finally:
            app.FACTORY_LLM_API_KEY = old
        self.assertFalse(out["ok"])
        self.assertTrue(out["requiresCostConfirmation"])
        self.assertEqual(app.get_factory_cycle(c["id"])["status"], "ready")


if __name__ == "__main__":
    unittest.main(verbosity=2)
