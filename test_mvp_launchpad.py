"""T-704 Business League L1: Launchpad protocol — schemas, honesty validators, ladders, gates, authority, approvals."""
import json
import re
import socket
import tempfile
import unittest
from pathlib import Path

import fastapi
from fastapi.testclient import TestClient

import evidence
import mvp_cycle
from mvp_factory import MvpError, MvpRegistry
from mvp_launchpad import (CHANNELS, CHECK_IDS, GATES, LADDERS, UNKNOWN, Launchpad, board, funnel,
                           install_mvp_launchpad_routes, learn_facts, validate_artifact)

PID = "mycast"
ROOT = Path(__file__).parent
TODAY = "2027-01-15"


class Clock:
    def __init__(self):
        self.t = 1_800_000_000.0   # 2027-01-15 UTC

    def __call__(self):
        self.t += 1
        return self.t


def idea(n=1, **over):
    return {"type": "idea_card", "who": f"Listeners {n}", "problem": "No time to read channels",
            "where_noticed": ["https://example.org/study"], **over}


def fact(ref="a-1", **over):
    return {"type": "market_fact", "idea_ref": [ref], "fact": "62% read news in Telegram", "source_url": "https://example.org/ipsos",
            "source_kind": "secondary", "observed_at": "2027-01-10", "verdict": "for", **over}


def signal(ref="a-1", **over):
    return {"type": "signal", "idea_ref": [ref], "url": "https://forum.example.org/t/1", "observed_at": "2027-01-11",
            "situation": "Spends hours tracking topics", "independent": True, **over}


def card(check="D4", **over):
    return {"type": "test_card", "check": check, "hypothesis": "Fans want a daily club digest", "channel": "organic_social",
            "audience": "club fans", **over}


def entry(check="D4", **over):
    return {"type": "channel_entry", "check": check, "channel": "organic_social", "action": "One post in the club group", **over}


class LaunchpadCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = MvpRegistry(Path(self.tmp.name) / "mvp_factory.json", clock=Clock())
        self.lp = Launchpad(self.reg)
        self.stage = self.project()["stage"]

    def tearDown(self):
        self.assertEqual(self.project()["stage"], self.stage)   # Launchpad never changes a project stage
        self.tmp.cleanup()

    def project(self):
        return self.reg._load()["projects"][PID]

    def add(self, body, role="agent", actor="claude"):
        return self.lp.add_artifact(PID, body, actor_role=role, actor=actor)["artifact"]

    def code(self, fn, *a, **k):
        with self.assertRaises(MvpError) as ctx:
            fn(*a, **k)
        return ctx.exception.code

    def view(self):
        return board(self.project())

    def check(self, cid):
        return next(c for c in self.view()["checks"] if c["id"] == cid)


class SchemaTest(LaunchpadCase):
    def test_empty_board_is_unknown_not_zero(self):
        view = self.view()
        self.assertEqual([c["id"] for c in view["checks"]], list(CHECK_IDS))
        self.assertTrue(all(c["actual"] == UNKNOWN and c["target_met"] in (UNKNOWN,) or c["target"]["min"] is None for c in view["checks"]))
        self.assertTrue(all(c["actual"] == UNKNOWN for c in view["checks"]))
        self.assertEqual([g["state"] for g in view["gates"]], ["pending"] * 5)
        self.assertEqual(view["learn"], {"verdict": UNKNOWN, "main_channel": UNKNOWN, "main_metric": UNKNOWN,
                                         "price_covers_direct_cost": UNKNOWN})
        self.assertEqual(view["needs_you"], [])
        self.assertNotIn("launchpad", self.project())           # reading the board writes nothing

    def test_fact_and_signal_need_a_source_url_and_a_date(self):
        self.add(idea())
        for body, want in ((fact(source_url=""), "source_url_required"), (fact(source_url="http://example.org/x"), "bad_url"),
                           (fact(source_url="https://user@example.org/x"), "bad_url"), (fact(observed_at=""), "date_required"),
                           (fact(observed_at="2027-13-40"), "bad_date"), (fact(observed_at="2027-02-01"), "date_in_future"),
                           (signal(url="notes.txt"), "bad_url"), (signal(observed_at=None), "date_required"),
                           (fact(idea_ref=[]), "ref_required"), (fact(source_kind="blog"), "bad_source_kind"),
                           (fact(verdict="maybe"), "bad_verdict"), (signal(independent="yes"), "independent_yes_or_no")):
            self.assertEqual(self.code(self.add, body), want, body)
        self.assertEqual(self.check("D2")["actual"], UNKNOWN)   # nothing was stored

    def test_missing_data_is_unknown_and_never_filled(self):
        self.add(idea())
        f = self.add(fact())["fields"]
        self.assertEqual([f[k] for k in ("published_at", "query", "alternative", "price", "complaint")], [UNKNOWN] * 5)
        s = self.add(signal(posted_at="unknown"))["fields"]
        self.assertEqual((s["posted_at"], s["current_solution"], s["author_words"]), (UNKNOWN, UNKNOWN, UNKNOWN))
        e = self.add(entry(reach=0, leads=None))["fields"]
        self.assertEqual((e["reach"], e["leads"], e["payments"]), (0, UNKNOWN, UNKNOWN))   # zero is a result

    def test_levels_agents_write_at_most_linked(self):
        a = self.add(idea())
        self.assertEqual(a["level"], "linked")
        self.assertEqual(self.add(idea(2, where_noticed=["own_experience"]))["level"], "claimed")
        self.assertEqual(self.add(card())["level"], "claimed")   # a plan has no source
        for field in ("level", "actor", "role", "events"):
            self.assertEqual(self.code(self.add, idea(3, **{field: "accepted"})), "server_field_not_settable")
        self.assertEqual(self.code(self.add, idea(3, credibility=0.9)), "attention_is_not_demand")   # no self-assessed score

    def test_likes_views_and_ctr_are_refused(self):
        for field in ("likes", "views", "impressions", "ctr", "followers"):
            self.assertEqual(self.code(self.add, entry(**{field: 100})), "attention_is_not_demand")
        self.assertEqual(self.code(self.add, entry(leads=-1)), "bad_number")
        self.assertEqual(self.code(self.add, entry(leads="many")), "bad_number")
        self.assertEqual(self.code(self.add, entry(channel="billboard")), "bad_channel")

    def test_privacy_signal_words_redacted_interview_needs_consent_and_a_hash(self):
        self.add(idea())
        s = self.add(signal(author_words="write me at fan@example.org or +380 67 123 45 67"))
        self.assertNotIn("example.org", s["fields"]["author_words"])
        self.assertEqual(s["fields"]["author_words"].count("[redacted]"), 2)
        self.assertEqual(self.code(self.add, signal(author_words="x" * 281)), "text_too_long")
        self.assertEqual(self.code(self.add, signal(situation="call +380 67 123 45 67")), "personal_data")
        note = {"type": "interview_note", "consent_ref": "recorded verbal consent, 2027-01-12", "participant": "p-0123abcd",
                "last_real_case": "Missed the match result", "ask_made": "Try the digest for a week", "outcome": "agreed"}
        self.assertEqual(self.add(note)["check"], "D7")
        self.assertEqual(self.code(self.add, dict(note, participant="Ivan Petrenko")), "participant_hash_required")
        self.assertEqual(self.code(self.add, dict(note, consent_ref="")), "text_required")
        self.assertEqual(self.code(self.add, dict(note, outcome="loved it")), "bad_outcome")

    def test_types_checks_and_refs(self):
        self.assertEqual(self.code(self.add, {"type": "viral_score"}), "bad_type")
        self.assertEqual(self.code(self.add, idea(check="D3")), "bad_check")
        self.assertEqual(self.code(self.add, card(check="D7")), "bad_check")
        self.assertEqual(self.code(self.add, fact("a-9")), "unknown_artifact")
        self.add(idea())
        f = self.add(fact())
        self.assertEqual(self.code(self.add, signal(f["id"])), "idea_ref_must_be_an_idea")
        self.assertEqual(self.code(self.add, entry(test_ref="a-1")), "test_ref_must_be_a_test_card")
        self.assertEqual(self.code(validate_artifact, [], TODAY), "bad_body")
        self.assertEqual(self.code(self.add, idea(test="yes")), "bad_flag")
        self.assertEqual(self.code(self.lp.add_artifact, PID, idea(), actor_role="viewer"), "forbidden")
        self.assertEqual(self.code(self.lp.add_artifact, "nope", idea(), actor_role="owner"), "unknown_project")


class CountingTest(LaunchpadCase):
    def test_test_and_synthetic_records_are_shown_but_never_counted(self):
        real_idea = self.add(idea(1))
        self.add(idea(2, test=True))
        self.add(idea(3, synthetic=True))
        d1 = self.check("D1")
        self.assertEqual((d1["actual"], d1["excluded"], d1["target_met"]), (1, {"test": 1, "synthetic": 1}, False))
        self.assertEqual(d1["levels"]["linked"], 1)
        self.assertEqual(self.view()["artifact_count"], 3)       # still visible
        self.add(entry("CH", channel="paid", leads=50, payments=9, synthetic=True))
        self.assertEqual(self.view()["funnels"], {})             # a synthetic entry feeds no funnel
        self.assertEqual(self.code(self.lp.gate, PID, "G1", {"action": "propose", "chosen": ["a-1"], "deferred": {},
                                                             "rationale": "r", "evidence_refs": ["a-2"]},
                                   actor_role="agent", actor="gpt"), "evidence_not_real")   # validator 7
        self.assertEqual(real_idea["id"], "a-1")

    def test_only_synthetic_records_is_an_honest_zero_not_a_met_target(self):
        for n in range(6):
            self.add(idea(n, synthetic=True))
        d1 = self.check("D1")
        self.assertEqual((d1["actual"], d1["honest_zero"], d1["target_met"]), (0, True, False))

    def test_funnel_honest_zero_blocker_and_largest_drop(self):
        self.add(entry("CH", channel="paid", reach=1000, clicks=40, leads=4, main_scenario_done=2, payments=0))
        self.add(entry("CH", channel="paid", reach=1000, clicks=60, leads=6))
        self.add(entry("CH", channel="communities", reach=0, leads=0, payments=0))
        self.add(entry("CH", channel="seo_catalogs", reach=300, clicks=12))
        self.add(entry("CH", channel="organic_content", reach=0, blocker="publication_ban"))
        f = self.view()["funnels"]
        self.assertEqual(f["paid"]["stages"], {"reach": 2000, "clicks": 100, "leads": 10, "main_scenario_done": 2, "payments": 0})
        self.assertEqual(f["paid"]["largest_drop"], {"from": "main_scenario_done", "to": "payments", "lost_share": 1.0})
        self.assertEqual(f["paid"]["demand_reading"], "demand_seen")          # leads, not clicks
        self.assertEqual(f["communities"]["demand_reading"], "honest_zero")   # a real zero, shown as zero
        self.assertEqual(f["communities"]["stages"]["leads"], 0)
        self.assertIsNone(f["communities"]["largest_drop"])
        self.assertEqual(f["seo_catalogs"]["demand_reading"], UNKNOWN)        # clicks alone say nothing about demand
        self.assertEqual(f["seo_catalogs"]["stages"]["payments"], UNKNOWN)
        self.assertEqual((f["organic_content"]["demand_reading"], f["organic_content"]["blockers"]), ("blocked", ["publication_ban"]))
        self.assertEqual(funnel([])["demand_reading"], UNKNOWN)
        self.assertEqual(self.code(self.add, entry(blocker="lazy")), "bad_blocker")


class LadderTest(LaunchpadCase):
    def usage(self):
        return self.add(entry("MVP", channel="product", action="First user tries the digest", ladder="usage"))

    def step(self, aid, to, role="agent", actor="claude", **body):
        body.setdefault("evidence", ["https://example.org/proof"])
        return self.lp.step(PID, aid, {"to": to, **body}, actor_role=role, actor=actor)["artifact"]

    def test_forward_one_rung_with_evidence(self):
        a = self.usage()
        self.assertEqual(a["fields"]["status"], "demo_viewed")
        self.assertEqual(self.code(self.step, a["id"], "main_scenario_done"), "one_rung_at_a_time")   # no skipping
        self.assertEqual(self.code(self.step, a["id"], "signed_up", evidence=[]), "evidence_required")
        self.assertEqual(self.step(a["id"], "signed_up")["fields"]["status"], "signed_up")
        self.assertEqual(self.code(self.step, a["id"], "demo_viewed"), "one_rung_at_a_time")          # never backwards
        done = self.step(a["id"], "main_scenario_done")
        self.assertEqual([h["status"] for h in done["status_history"]], ["demo_viewed", "signed_up", "main_scenario_done"])
        self.assertEqual(done["status_history"][-1]["level"], "linked")                               # the agent's word
        self.assertEqual(self.code(self.step, a["id"], "signed_up"), "ladder_finished")
        self.assertEqual(self.code(self.add, entry(ladder="deal", status="paid")), "ladder_starts_at_first_rung")
        self.assertEqual(self.code(self.add, entry(ladder="rocket")), "bad_ladder")
        self.assertEqual(self.code(self.step, self.add(entry())["id"], "active"), "no_ladder")

    def test_every_ladder_from_the_spec(self):
        self.assertEqual(LADDERS["deal"], ("verbal_yes", "invoiced", "paid"))
        self.assertEqual(LADDERS["outreach"], ("sent", "replied", "negotiating", "test_confirmed", "live"))
        self.assertEqual(LADDERS["usage"], ("demo_viewed", "signed_up", "main_scenario_done"))
        self.assertEqual(LADDERS["listing"], ("submitted", "published"))
        self.assertEqual(LADDERS["campaign"], ("draft", "moderation", "active", ("finished", "stopped")))

    def test_payment_is_owner_confirmed(self):
        d = self.add(entry("CH", channel="direct_sales", action="Club media manager", ladder="deal"))
        self.assertEqual(self.code(self.step, d["id"], "paid"), "one_rung_at_a_time")     # verbal_yes → paid is rejected
        self.step(d["id"], "invoiced")
        self.assertEqual(self.code(self.step, d["id"], "paid"), "owner_only")
        paid = self.step(d["id"], "paid", role="owner", actor="owner", evidence=[])
        self.assertEqual(paid["status_history"][-1]["level"], "accepted")

    def test_campaign_needs_a_test_card_and_spend_approval(self):
        self.assertEqual(self.code(self.add, card("D6", channel="paid", spend_limit=20, period="7 days", stop_condition="20 USD")),
                         "paid_test_needs_d5")                                            # D6 only after D5
        self.add(card("D5", channel="landing", page_ref="https://mycast.pro/club", target_event="waitlist_signup"))
        self.assertEqual(self.code(self.add, card("D6", channel="paid", spend_limit=20)), "spend_needs_period_and_stop")
        paid = self.add(card("D6", channel="paid", spend_limit=20, period="7 days", stop_condition="20 USD or 300 clicks"))
        orphan = self.add(entry("D6", channel="paid", action="No plan", ladder="campaign"))
        self.assertEqual(self.code(self.step, orphan["id"], "moderation"), "spend_not_approved")   # a campaign without a card
        camp = self.add(entry("D6", channel="paid", action="Search ads", ladder="campaign", test_ref=paid["id"]))
        self.assertEqual(self.code(self.step, camp["id"], "moderation"), "spend_not_approved")
        self.assertIn({"kind": "spend_approval", "artifact": paid["id"], "channel": "paid"}, self.view()["needs_you"])
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": paid["id"], "kind": "spend"}, actor_role="member"), "owner_only")
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": paid["id"], "kind": "spend"}, actor_role="agent"), "owner_only")
        ok = self.lp.approve(PID, {"artifact": paid["id"], "kind": "spend"}, actor_role="owner", actor="owner")["artifact"]
        self.assertEqual(ok["approvals"]["spend"]["spend_limit"], 20)
        self.assertTrue(self.lp.approve(PID, {"artifact": paid["id"], "kind": "spend"}, actor_role="owner", actor="owner")["duplicate"])
        self.assertNotIn("spend_approval", [n["kind"] for n in self.view()["needs_you"]])
        self.step(camp["id"], "moderation")
        self.step(camp["id"], "active")
        self.assertEqual(self.step(camp["id"], "stopped")["fields"]["status"], "stopped")
        # Terms are locked for agents after approval; the owner may change them once.
        self.assertEqual(self.code(self.lp.edit_test_card, PID, paid["id"], {"spend_limit": 500}, actor_role="agent"), "locked_after_approval")
        self.lp.approve(PID, {"artifact": paid["id"], "kind": "spend", "spend_limit": 30}, actor_role="owner", actor="owner")
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": paid["id"], "kind": "spend", "spend_limit": 90},
                                   actor_role="owner", actor="owner"), "one_change_per_running_test")

    def test_spend_defaults_to_zero_and_approvals_start_false(self):
        c = self.add(card())
        self.assertEqual((c["fields"]["spend_limit"], c["approvals"]), (0, {"spend": None, "outreach": None}))
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": c["id"], "kind": "spend"}, actor_role="owner"), "nothing_to_approve")
        self.lp.edit_test_card(PID, c["id"], {"period": "3 days"}, actor_role="agent", actor="claude")   # before approval: fine
        synthetic = self.add(card(synthetic=True))
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": synthetic["id"], "kind": "outreach"}, actor_role="owner"),
                         "not_a_real_test_card")
        self.assertEqual(self.code(self.lp.approve, PID, {"artifact": c["id"], "kind": "publish"}, actor_role="owner"), "bad_kind")

    def test_outreach_is_recorded_only_after_owner_approval(self):
        c = self.add(card("CH", channel="direct_sales", audience="club media managers"))
        self.assertIn({"kind": "outreach_approval", "artifact": c["id"], "channel": "direct_sales"}, self.view()["needs_you"])
        out = entry("CH", channel="direct_sales", action="Message to 5 clubs", ladder="outreach", test_ref=c["id"])
        self.assertEqual(self.code(self.add, out), "outreach_not_approved")
        self.assertEqual(self.code(self.add, dict(out, test_ref=None)), "outreach_needs_a_test_card")
        self.lp.approve(PID, {"artifact": c["id"], "kind": "outreach"}, actor_role="owner", actor="owner")
        sent = self.add(out)
        self.assertEqual(self.code(LadderTest.step, self, sent["id"], "live"), "one_rung_at_a_time")   # sent → live is rejected


class GateTest(LaunchpadCase):
    def seed(self, ideas=5):
        ids = [self.add(idea(n))["id"] for n in range(ideas)]
        facts = [self.add(fact(i))["id"] for i in ids]
        return ids, facts

    def gate(self, gate, role, actor, **body):
        body.setdefault("rationale", "Evidence is in the refs")
        return self.lp.gate(PID, gate, body, actor_role=role, actor=actor)

    def g1(self, ids, facts, role="owner", actor="owner", action="decide"):
        return self.gate("G1", role, actor, action=action, chosen=ids[:3], deferred={i: "weaker facts" for i in ids[3:]},
                         evidence_refs=facts[:3])

    def test_no_agent_decides_a_gate_on_its_own_work(self):
        ids, facts = self.seed()
        self.assertEqual(self.code(self.g1, ids, facts, "agent", "claude"), "own_work")        # claude produced D1–D2
        proposal = self.g1(ids, facts, "agent", "claude", "propose")["gate"]
        self.assertEqual(proposal["by"], "claude")
        self.assertEqual(self.view()["gates"][0]["state"], "proposed")
        self.gate("G1", "agent", "gemini", action="propose", chosen=ids[:1], deferred={i: "later" for i in ids[1:]}, evidence_refs=facts[:1])
        self.assertEqual(self.code(self.g1, ids, facts, "agent", "gemini"), "own_work")        # a proposer is not a judge either
        decided = self.g1(ids, facts, "agent", "gpt")["gate"]                                   # gpt produced nothing: a judge
        self.assertEqual((decided["decided_by"], decided["chosen"]), ("gpt", ids[:3]))
        self.assertEqual(self.code(self.g1, ids, facts), "gate_decided")

    def test_g1_g2_choices_and_reasons_for_every_deferred_idea(self):
        ids, facts = self.seed()
        self.assertEqual(self.code(self.gate, "G1", "owner", "owner", action="decide", chosen=ids[:4], deferred={ids[4]: "x"},
                                   evidence_refs=facts), "bad_choice")                          # at most three go on
        self.assertEqual(self.code(self.gate, "G1", "owner", "owner", action="decide", chosen=ids[:3], deferred={ids[3]: "x"},
                                   evidence_refs=facts), "every_deferred_idea_needs_a_reason")
        self.assertEqual(self.code(self.gate, "G1", "owner", "owner", action="decide", chosen=ids[:3],
                                   deferred={ids[3]: "x", ids[4]: "y"}, evidence_refs=[]), "ref_required")
        self.assertEqual(self.code(self.gate, "G1", "owner", "owner", action="decide", chosen=ids[:3],
                                   deferred={ids[3]: "x", ids[4]: "y"}, evidence_refs=facts, rationale=""), "text_required")
        self.assertEqual(self.code(self.gate, "G2", "owner", "owner", action="decide", chosen=ids[:1], deferred={i: "x" for i in ids[1:]},
                                   evidence_refs=facts), "previous_gate_open")
        self.g1(ids, facts)
        self.assertEqual(self.code(self.gate, "G2", "owner", "owner", action="decide", chosen=[ids[4]], deferred={},
                                   evidence_refs=facts), "bad_choice")                          # only from the G1 shortlist
        g2 = self.gate("G2", "owner", "owner", action="decide", chosen=ids[:2], deferred={ids[2]: "no signals"}, evidence_refs=facts)["gate"]
        self.assertEqual(g2["chosen"], ids[:2])
        self.assertEqual(self.code(self.gate, "G9", "owner", "owner", action="decide"), "unknown_gate")
        self.assertEqual(self.code(self.gate, "G1", "owner", "owner", action="merge", evidence_refs=facts), "bad_action")

    def test_thin_evidence_gives_a_named_extra_check_never_a_build(self):
        ids, facts = self.seed()
        self.g1(ids, facts)
        self.gate("G2", "owner", "owner", action="decide", chosen=ids[:1], deferred={i: "x" for i in ids[1:3]}, evidence_refs=facts)
        thin = self.gate("G3", "owner", "owner", action="decide", extra_check="Five more interviews with club fans", evidence_refs=facts)["gate"]
        self.assertEqual((thin["chosen"], thin["extra_check"]), (None, "Five more interviews with club fans"))
        self.assertEqual(self.code(self.gate, "G4", "owner", "owner", action="decide", chosen="no", evidence_refs=facts), "previous_gate_open")
        self.gate("G3", "owner", "owner", action="decide", chosen="build_minimum", evidence_refs=facts)   # after the extra check
        self.assertEqual(self.view()["gates"][2]["decision"]["chosen"], "build_minimum")

    def test_g3_g4_g5_are_owner_only_and_g4_needs_a_confirmed_user(self):
        ids, facts = self.seed()
        self.g1(ids, facts)
        self.gate("G2", "owner", "owner", action="decide", chosen=ids[:1], deferred={i: "x" for i in ids[1:3]}, evidence_refs=facts)
        for role, actor in (("agent", "gpt"), ("member", "teammate")):
            self.assertEqual(self.code(self.gate, "G3", role, actor, action="decide", chosen="build_minimum", evidence_refs=facts), "owner_only")
        self.gate("G3", "agent", "gpt", action="propose", chosen="build_minimum", evidence_refs=facts)   # proposing is allowed
        self.assertEqual([n["gate"] for n in self.view()["needs_you"] if n["kind"] == "gate"], [])   # G3 has no records yet
        self.gate("G3", "owner", "owner", action="decide", chosen="build_minimum", evidence_refs=facts)
        use = self.add(entry("MVP", channel="product", action="First user", ladder="usage"))
        self.assertEqual(self.code(self.gate, "G4", "owner", "owner", action="decide", chosen="yes", evidence_refs=[use["id"]]),
                         "no_confirmed_user")                                                   # a demo view is not usage
        for to in ("signed_up", "main_scenario_done"):
            self.lp.step(PID, use["id"], {"to": to, "evidence": ["https://example.org/log"]}, actor_role="agent", actor="claude")
        self.assertEqual(self.code(self.gate, "G4", "owner", "owner", action="decide", chosen="yes", evidence_refs=[use["id"]]),
                         "no_confirmed_user")                                                   # the agent's word is not enough
        seen = self.add(entry("MVP", channel="product", action="Second user", ladder="usage"), role="owner", actor="owner")
        for to in ("signed_up", "main_scenario_done"):
            self.lp.step(PID, seen["id"], {"to": to}, actor_role="owner", actor="owner")
        self.gate("G4", "owner", "owner", action="decide", chosen="yes", evidence_refs=[seen["id"]])
        self.assertEqual(self.code(self.gate, "G5", "owner", "owner", action="decide", chosen="scale", evidence_refs=facts), "bad_choice")
        self.assertEqual(self.code(self.gate, "G5", "owner", "owner", action="decide", chosen="continue", evidence_refs=facts),
                         "main_channel_required")
        self.gate("G5", "owner", "owner", action="decide", chosen="continue", main_channel="communities",
                  main_metric="weekly_active_listeners", evidence_refs=facts)
        self.assertEqual(self.view()["learn"], {"verdict": "continue", "main_channel": "communities",
                                                "main_metric": "weekly_active_listeners", "price_covers_direct_cost": UNKNOWN})
        self.assertEqual(learn_facts(self.project())["gates"], {g: "decided" for g in GATES})

    def test_owner_gates_appear_in_needs_you_only_when_there_is_something_to_decide(self):
        self.assertEqual(self.view()["needs_you"], [])
        self.add({"type": "interview_note", "consent_ref": "consent on record", "participant": "p-0123abcd",
                  "last_real_case": "c", "ask_made": "a", "outcome": "refused"})
        self.assertIn({"kind": "gate", "gate": "G3", "state": "pending"}, self.view()["needs_you"])
        self.add(fact(self.add(idea())["id"]))
        gates = [n for n in self.view()["needs_you"] if n["kind"] == "gate"]
        self.assertEqual(gates, [{"kind": "gate", "gate": "G1", "state": "pending"}])   # one gate at a time, the earliest


class StorageTest(LaunchpadCase):
    def test_idempotency_and_agent_loop_events(self):
        body = dict(idea(), idempotency_key="k-1")
        first = self.lp.add_artifact(PID, body, actor_role="agent", actor="claude")
        again = self.lp.add_artifact(PID, body, actor_role="agent", actor="claude")
        self.assertEqual((first["duplicate"], again["duplicate"], again["artifact"]["id"]), (False, True, first["artifact"]["id"]))
        self.assertEqual(self.view()["artifact_count"], 1)
        self.assertEqual(self.code(self.lp.add_artifact, PID, dict(idea(2), idempotency_key="k-1"), actor_role="agent", actor="claude"),
                         "idempotency_conflict")
        aid = first["artifact"]["id"]
        self.assertEqual(self.code(self.lp.review, PID, aid, {"verdict": "confirmed", "note": "ok"}, actor_role="agent", actor="claude"),
                         "own_work")                                           # the same artifact, a different model
        reviewed = self.lp.review(PID, aid, {"verdict": "confirmed", "note": "Source opened, quote matches", "idempotency_key": "k-2"},
                                  actor_role="agent", actor="gpt")["artifact"]
        self.assertTrue(self.lp.review(PID, aid, {"verdict": "confirmed", "note": "Source opened, quote matches", "idempotency_key": "k-2"},
                                       actor_role="agent", actor="gpt")["duplicate"])
        self.assertEqual([(e["step"], e["by"]) for e in reviewed["events"]], [("produced", "claude"), ("reviewed", "gpt")])
        self.assertEqual(reviewed["level"], "linked")                           # a review never raises the level
        self.assertEqual([e["step"] for e in self.check("D1")["loop"]], ["produced", "reviewed"])

    def test_events_are_notes_and_the_stage_never_moves(self):
        before = len(self.reg._load()["events"])
        self.add(idea())
        events = self.reg._load()["events"][before:]
        self.assertTrue(events and all(e["kind"] == "note" and e["from_stage"] == e["to_stage"] and e["launchpad"] for e in events))

    def test_no_network_is_touched(self):
        real_socket = socket.socket

        def blocked(*a, **k):
            raise AssertionError("Launchpad must not open a socket")
        socket.socket = blocked
        try:
            ids = [self.add(idea(n))["id"] for n in range(2)]
            f = self.add(fact(ids[0]))
            self.add(card("D5", channel="landing", page_ref="https://mycast.pro/x", target_event="signup"))
            c = self.add(card("D6", channel="paid", spend_limit=5, period="3 days", stop_condition="5 USD"))
            self.lp.approve(PID, {"artifact": c["id"], "kind": "spend"}, actor_role="owner", actor="owner")
            self.lp.gate(PID, "G1", {"action": "decide", "chosen": ids[:1], "deferred": {ids[1]: "x"}, "rationale": "r",
                                     "evidence_refs": [f["id"]]}, actor_role="owner", actor="owner")
            self.view()
        finally:
            socket.socket = real_socket
        source = (ROOT / "mvp_launchpad.py").read_text(encoding="utf-8")
        self.assertNotRegex(source, r"\b(import|from)\s+(requests|urllib|httpx|aiohttp|socket|subprocess|smtplib)\b")

    def test_evidence_rule_types_and_cycle_facts(self):
        want = {"market": "linked", "lead": "checked", "usage": "checked", "payment": "accepted", "outreach": "accepted", "spend": "accepted"}
        self.assertEqual({k: evidence.RULES[k]["required_level"] for k in want}, want)
        self.assertEqual(evidence.new_verification("payment")["required_level"], "accepted")
        self.assertEqual(mvp_cycle.cycle_view(self.project(), {}, {})["launchpad"], {"started": False})
        self.add(idea())
        self.assertTrue(mvp_cycle.cycle_view(self.project(), {}, {})["launchpad"]["started"])


class RouteTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.reg = MvpRegistry(Path(self.tmp.name) / "mvp_factory.json", clock=Clock())
        self.role = "owner"
        app = fastapi.FastAPI()
        install_mvp_launchpad_routes(app, self.reg, lambda request: {"role": self.role, "email": self.role + "@example.org"})
        self.http = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_routes(self):
        base = f"/api/mvp-factory/{PID}/launchpad"
        self.assertEqual(self.http.get(base).json()["checks"][0]["actual"], UNKNOWN)
        self.assertEqual(self.http.get("/api/mvp-factory/nope/launchpad").status_code, 404)
        made = self.http.post(base + "/artifacts", json=idea()).json()["artifact"]
        self.assertEqual((made["id"], made["actor"]), ("a-1", "owner@example.org"))
        self.assertEqual(self.http.post(base + "/artifacts", json=fact(source_url="")).json(), {"detail": "source_url_required"})
        self.assertEqual(self.http.post(base + "/artifacts", content=b"{").status_code, 400)
        use = self.http.post(base + "/artifacts", json=entry("MVP", channel="product", ladder="usage")).json()["artifact"]
        self.assertEqual(self.http.post(f"{base}/artifacts/{use['id']}/status", json={"to": "signed_up"}).json()["artifact"]["fields"]["status"], "signed_up")
        self.role = "viewer"
        self.assertEqual(self.http.post(base + "/artifacts", json=idea(2)).status_code, 403)
        self.role = "member"
        c = self.http.post(base + "/artifacts", json=card(spend_limit=0)).json()["artifact"]
        self.assertEqual(self.http.post(base + "/approvals", json={"artifact": c["id"], "kind": "outreach"}).status_code, 403)
        self.assertEqual(self.http.post(base + "/gates/G3", json={"action": "decide", "chosen": "build_minimum", "rationale": "r",
                                                                  "evidence_refs": ["a-1"]}).status_code, 403)
        self.assertEqual(self.http.post(f"{base}/artifacts/a-1/review", json={"verdict": "confirmed", "note": "checked"}).status_code, 200)
        self.assertEqual(self.http.post(f"{base}/artifacts/{c['id']}/terms", json={"period": "2 days"}).status_code, 200)
        self.role = "owner"
        self.assertEqual(self.http.post(base + "/approvals", json={"artifact": c["id"], "kind": "outreach"}).status_code, 200)


class UiTest(unittest.TestCase):
    HTML = (ROOT / "static/mvp-factory/launchpad.html").read_text(encoding="utf-8")

    def tables(self):
        out = {}
        for lang in ("en", "uk", "ru"):
            m = re.search(r"^ %s:(\{.*\}),?$" % lang, self.HTML, re.M)
            out[lang] = json.loads(m.group(1))
        return out

    def test_three_languages_have_the_same_keys(self):
        t = self.tables()
        self.assertEqual(set(t["en"]), set(t["uk"]))
        self.assertEqual(set(t["en"]), set(t["ru"]))
        self.assertTrue(all(v.strip() for table in t.values() for v in table.values()))
        for cid in CHECK_IDS:
            self.assertIn("c_" + cid, t["en"])
        for g in GATES:
            self.assertIn("g_" + g, t["en"])
        for ch in CHANNELS:
            self.assertIn("ch_" + ch, t["en"])

    def test_page_only_reads_the_board_and_escapes_text(self):
        self.assertEqual(re.findall(r"fetch\('([^']+)'", self.HTML), ["/api/mvp-factory/"])
        self.assertNotRegex(self.HTML, r"method:\s*'POST'")            # L1 page is read-only: no action can be triggered
        self.assertIn("const esc=", self.HTML)
        self.assertNotRegex(self.HTML, r"innerHTML=[^;]*\+\s*(a|d|g)\.[a-z_.]+\s*[;+](?<!esc)")
        self.assertIn("project=mycast", (ROOT / "static/mvp-factory/index.html").read_text(encoding="utf-8"))
        self.assertIn("@media", self.HTML)


if __name__ == "__main__":
    unittest.main()
