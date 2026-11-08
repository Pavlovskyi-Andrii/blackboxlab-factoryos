"""#275 MVP Builder M1D: truthful status projection for Agent Office. Offline, deterministic, no network."""
import copy
import json
import unittest

from mvp_builder_projection import DISPLAY_ONLY, LABELS, STAGES, project

NOW = "2026-11-08T10:00:00Z"
RUN = "run-0123abcd"


def ev(at, stage, *, verified=True, evidence="auto", run_id=RUN, source="real", actor="claude", **extra):
    if evidence == "auto":
        evidence = f"https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/{stage}/{at}"
    e = {"at": at, "stage": stage, "actor": actor, "run_id": run_id, "source": source,
         "verified": verified, "evidence": evidence}
    e.update(extra)
    return e


def flow():
    return [
        ev("2026-11-08T09:00:00Z", "ready", run_id=None, project="mycast", version="v1"),
        ev("2026-11-08T09:01:00Z", "claimed"),
        ev("2026-11-08T09:02:00Z", "running"),
        ev("2026-11-08T09:20:00Z", "committed"),
        ev("2026-11-08T09:21:00Z", "pushed"),
        ev("2026-11-08T09:22:00Z", "pr_open"),
        ev("2026-11-08T09:30:00Z", "ci_passed"),
    ]


def real(events, **kw):
    kw.setdefault("now", NOW)
    return project(events, **kw)["real"]


class ProjectionTest(unittest.TestCase):
    def assertNotLive(self, card):
        self.assertNotIn(card["stage"], ("running", "ready"))
        self.assertEqual((card["merge_state"], card["deploy_state"]), ("UNKNOWN", "UNKNOWN"))

    def test_empty_and_missing_events(self):
        for events in ([], None):
            card = real(events)
            self.assertEqual(card["stage"], "unknown")
            self.assertFalse(card["verified"])
            self.assertIsNone(card["run_id"])
            self.assertEqual(card["cost"], {"known": False})
        self.assertEqual(real(None)["stage_reason"], "snapshot_missing")
        self.assertEqual(real([])["stage_reason"], "no_verified_events")
        self.assertIsNone(project([], now=NOW)["demo"])

    def test_offline_and_forbidden_snapshots_are_unknown(self):
        events = flow() + [ev("2026-11-08T09:59:00Z", "heartbeat")]
        for status in ("offline", "forbidden", "missing", "nonsense"):
            card = real(events, snapshot_status=status)
            self.assertEqual(card["stage"], "unknown", status)
            self.assertTrue(card["stage_reason"].startswith("snapshot_"))
            self.assertEqual(card["blocker"]["code"], card["stage_reason"])
            self.assertFalse(card["verified"])
            self.assertFalse(card["needs_owner"])
            self.assertNotLive(card)
        self.assertEqual(real(events, snapshot_status="forbidden")["stage_reason"], "snapshot_forbidden")
        self.assertEqual(real(events, snapshot_status="forbidden")["labels"]["en"]["blocker"],
                         "Access forbidden (403)")

    def test_partial_snapshot_is_marked_incomplete(self):
        card = real(flow(), snapshot_status="partial")
        self.assertEqual(card["stage"], "ci_passed")
        self.assertEqual(card["stage_reason"], "snapshot_partial")
        self.assertFalse(card["complete"])
        self.assertTrue(real(flow())["complete"])

    def test_out_of_order_input_gives_same_card(self):
        events = flow() + [ev("2026-11-08T09:58:00Z", "heartbeat")]
        shuffled = list(reversed(events))
        shuffled.insert(2, shuffled.pop(5))
        a, b = project(events, now=NOW), project(shuffled, now=NOW)
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual(a["real"]["stage"], "ci_passed")

    def test_stale_or_absent_heartbeat_is_never_running(self):
        base = flow()[:3]
        card = real(base)
        self.assertEqual((card["stage"], card["stage_reason"]), ("stale", "heartbeat_absent"))
        self.assertEqual(card["verified_stage"], "running")
        old = real(base + [ev("2026-11-08T09:50:00Z", "heartbeat")])
        self.assertEqual((old["stage"], old["stage_reason"], old["heartbeat_age_s"]),
                         ("stale", "heartbeat_stale", 600))
        self.assertEqual(old["blocker"]["code"], "heartbeat_stale")
        unverified = real(base + [ev("2026-11-08T09:59:00Z", "heartbeat", verified=False)])
        self.assertEqual(unverified["stage"], "stale")

    def test_fresh_heartbeat_shows_running(self):
        card = real(flow()[:3] + [ev("2026-11-08T09:58:00Z", "heartbeat")])
        self.assertEqual(card["stage"], "running")
        self.assertTrue(card["heartbeat_fresh"])
        self.assertEqual(card["heartbeat_age_s"], 120)
        self.assertEqual((card["owner"], card["run_id"], card["project"], card["version"]),
                         ("claude", RUN, "mycast", "v1"))
        self.assertEqual(real(flow()[:3] + [ev("2026-11-08T09:58:00Z", "heartbeat")],
                              heartbeat_ttl=60)["stage"], "stale")

    def test_pr_open_never_implies_merged_or_deployed(self):
        card = real(flow())
        self.assertEqual(card["stage"], "ci_passed")
        self.assertEqual((card["merge_state"], card["deploy_state"]), ("UNKNOWN", "UNKNOWN"))
        self.assertNotIn("percent", json.dumps(card))
        card = real(flow() + [ev("2026-11-08T09:40:00Z", "merged", verified=False)])
        self.assertEqual(card["merge_state"], "UNKNOWN")
        card = real(flow() + [ev("2026-11-08T09:40:00Z", "merged")])
        self.assertEqual((card["merge_state"], card["deploy_state"]), ("MERGED", "UNKNOWN"))

    def test_demo_is_separated_from_real(self):
        demo_events = [ev("2026-11-08T09:00:00Z", "claimed", source="demo", run_id="run-dddddddd"),
                       ev("2026-11-08T09:05:00Z", "preview_ready", source="demo", run_id="run-dddddddd")]
        out = project(flow() + demo_events, now=NOW)
        self.assertFalse(out["real"]["demo"])
        self.assertEqual(out["real"]["run_id"], RUN)
        self.assertEqual(out["real"]["preview_status"], "none")
        self.assertTrue(out["demo"]["demo"])
        self.assertEqual((out["demo"]["stage"], out["demo"]["preview_status"]), ("preview_ready", "ready"))
        self.assertEqual(out["demo"]["labels"]["uk"]["demo"], LABELS["demo"]["uk"])
        self.assertIsNone(out["real"]["labels"]["en"]["demo"])

    def test_unverified_events_are_only_pending(self):
        card = real(flow() + [ev("2026-11-08T09:40:00Z", "qa_review", verified=False),
                              ev("2026-11-08T09:41:00Z", "preview_ready", evidence=None)])
        self.assertEqual(card["stage"], "ci_passed")
        self.assertEqual([p["stage"] for p in card["pending_unverified"]], ["qa_review", "preview_ready"])
        self.assertEqual(card["preview_status"], "none")
        self.assertEqual(card["last_evidence"]["stage"], "ci_passed")
        self.assertTrue(card["last_evidence"]["evidence"].startswith("https://github.com/"))
        self.assertEqual(card["last_evidence"]["source"], "real")

    def test_rejected_qa_sets_blocker(self):
        card = real(flow() + [ev("2026-11-08T09:40:00Z", "qa_review"),
                              ev("2026-11-08T09:45:00Z", "qa_rejected", detail={"reason": "login broken"})])
        self.assertEqual(card["qa_result"], "rejected")
        self.assertEqual(card["blocker"], {"code": "qa_rejected", "detail": "login broken"})
        self.assertEqual(card["labels"]["ru"]["blocker"], LABELS["qa_rejected"]["ru"])
        pending = real(flow() + [ev("2026-11-08T09:40:00Z", "qa_review")])
        self.assertEqual((pending["qa_result"], pending["blocker"]), ("pending", None))
        self.assertEqual(real(flow())["qa_result"], "unknown")

    def test_pending_owner_approval(self):
        steps = [ev("2026-11-08T09:40:00Z", "qa_review"), ev("2026-11-08T09:45:00Z", "qa_passed"),
                 ev("2026-11-08T09:50:00Z", "preview_ready"), ev("2026-11-08T09:51:00Z", "owner_review")]
        card = real(flow() + steps)
        self.assertEqual((card["stage"], card["needs_owner"], card["qa_result"]), ("owner_review", True, "passed"))
        self.assertEqual(card["preview_status"], "ready")
        done = real(flow() + steps + [ev("2026-11-08T09:55:00Z", "approved", actor="owner")])
        self.assertEqual((done["stage"], done["needs_owner"]), ("approved", False))
        self.assertEqual(done["merge_state"], "UNKNOWN")

    def test_cost_unknown_vs_known(self):
        self.assertEqual(real(flow())["cost"], {"known": False})
        for bad in ({"usd": "0.4"}, {"usd": True}, {}, {"usd": -1}):
            self.assertEqual(real(flow() + [ev("2026-11-08T09:40:00Z", "cost", detail=bad)])["cost"],
                             {"known": False})
        self.assertEqual(real(flow() + [ev("2026-11-08T09:40:00Z", "cost", verified=False,
                                           detail={"usd": 1})])["cost"], {"known": False})
        cost = real(flow() + [ev("2026-11-08T09:40:00Z", "cost", detail={"usd": 0})])["cost"]
        self.assertEqual((cost["known"], cost["usd"]), (True, 0))

    def test_stale_run_and_malformed_events_are_ignored(self):
        events = flow() + [ev("2026-11-08T08:00:00Z", "claimed", run_id="run-oldoldold"),
                           ev("2026-11-08T09:35:00Z", "merged", run_id="run-oldoldold"),
                           {"stage": "running"}, "junk", ev("bad-time", "running"),
                           ev("2026-11-08T09:40:00Z", "percent_complete"),
                           ev("2026-11-08T09:40:00Z", "running", source="mock"),
                           ev("2026-11-08T11:00:00Z", "approved")]
        card = real(events)
        self.assertEqual(card["run_id"], RUN)
        self.assertEqual(card["merge_state"], "UNKNOWN")
        self.assertEqual(card["stage"], "ci_passed")
        self.assertEqual(card["ignored_reasons"], {"future": 1, "malformed": 5, "stale_run": 2})
        self.assertEqual(card["ignored"], 8)

    def test_blocked_and_failed_show_blocker(self):
        card = real(flow() + [ev("2026-11-08T09:40:00Z", "blocked", detail={"reason": "needs secret"})])
        self.assertEqual((card["stage"], card["blocker"]), ("blocked", {"code": "blocked", "detail": "needs secret"}))
        self.assertEqual(real(flow() + [ev("2026-11-08T09:40:00Z", "failed")])["blocker"]["code"], "failed")

    def test_labels_cover_every_stage_in_three_languages(self):
        for key in STAGES + DISPLAY_ONLY:
            self.assertEqual(set(LABELS[key]), {"uk", "ru", "en"}, key)
            self.assertTrue(all(LABELS[key].values()), key)
        for key, text in LABELS.items():
            self.assertEqual(set(text), {"uk", "ru", "en"}, key)
        card = real(flow())
        self.assertEqual(set(card["labels"]), {"uk", "ru", "en"})
        self.assertEqual(card["labels"]["en"]["stage"], "CI passed")

    def test_input_is_not_mutated_and_now_is_required(self):
        events = flow() + [ev("2026-11-08T09:40:00Z", "cost", detail={"usd": 1.5})]
        before = copy.deepcopy(events)
        project(events, now=NOW)
        self.assertEqual(events, before)
        with self.assertRaises(TypeError):
            project(events)                                                         # pylint: disable=E1125
        with self.assertRaises(ValueError):
            project(events, now="yesterday")


if __name__ == "__main__":
    unittest.main(verbosity=2)
