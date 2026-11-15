"""T-614 / #187 AI Decision Memory: real dataset import, persistence, owner-only API, registry link, page script."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import decision_memory as dm
from agent_secret_scan import contains_secret
from mvp_factory import MvpRegistry

ROOT = Path(__file__).resolve().parent
DAY = 86400
T0 = 1_794_700_800  # 2026-11-15T00:00:00Z


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class ImportTests(unittest.TestCase):
    def test_real_decisions_md_imports_without_secrets(self):
        text = (ROOT / "DECISIONS.md").read_text(encoding="utf-8")
        lines = text.splitlines()
        recs = dm.parse_decisions(text)
        self.assertGreater(len(recs), 100)
        self.assertEqual(len({r["id"] for r in recs}), len(recs))
        explicit = text.count("**Decision:**")
        self.assertGreaterEqual(len(recs), explicit)
        for rec in recs:
            self.assertTrue(rec["decision"] and rec["date"], rec)
            self.assertFalse(contains_secret(json.dumps(rec)), rec["id"])
            # Fields DECISIONS.md does not record are not invented.
            self.assertEqual((rec["owner"], rec["expected_outcome"], rec["review_at"]), ("", "", ""))
            line = int(rec["sources"][0]["label"].split(":")[1])
            self.assertTrue(rec["sources"][0]["url"].endswith(f"DECISIONS.md#L{line}"))
            src = lines[line - 1]
            self.assertTrue(src.startswith("- **Decision:**") or src.startswith("## "), (line, src))
            for s in rec["sources"]:
                self.assertTrue(s["url"].startswith(dm.REPO + "/"), s)

    def test_explicit_decision_and_reason_split(self):
        text = ("## 2026-10-23 — Sample\n\n- **Decision:** use `X` for #187.\n  **Reason:** it is cheap (T-614).\n"
                "- **Decision:** second.\n  **Reason:** why.\n## Plain heading (2026-10-31)\n- one\n- two #12\n")
        a, b, c = dm.parse_decisions(text)
        self.assertEqual((a["decision"], a["rationale"], a["date"]), ("use X for #187.", "it is cheap (T-614).", "2026-10-23"))
        self.assertEqual(a["tasks"], ["T-614"])
        self.assertIn(f"{dm.REPO}/issues/187", [s["url"] for s in a["sources"]])
        self.assertEqual(b["decision"], "second.")
        self.assertEqual((c["decision"], c["rationale"], c["date"]), ("Plain heading (2026-10-31)", "one two #12", "2026-10-31"))

    def test_credential_shaped_text_is_redacted(self):
        text = "## 2026-11-01 — Leak\n- **Decision:** rotate ghp_abcdefghijklmnopqrstuv now.\n  **Reason:** ok.\n"
        rec = dm.parse_decisions(text)[0]
        self.assertEqual(rec["decision"], dm.REDACTED)
        self.assertTrue(rec["redacted"])
        self.assertNotIn("ghp_", json.dumps(rec))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self.source = base / "DECISIONS.md"
        self.source.write_text("## 2026-10-23 — Arch\n- **Decision:** reuse the repo.\n  **Reason:** less to run.\n", encoding="utf-8")
        self.clock = Clock()
        self.store = dm.DecisionStore(base / "dm.json", self.source, clock=self.clock)
        self.imported = self.store.snapshot()["decisions"][0]["id"]

    def tearDown(self):
        self.tmp.cleanup()

    def body(self, **kw):
        out = {"decision": "Pilot Decision Memory first", "rationale": "Real dataset already exists",
               "owner": "owner", "expected_outcome": "3 of 5 interviewees keep using it", "review_at": "2026-12-01",
               "sources": ["https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/187"], "idempotency_key": "k1"}
        out.update(kw)
        return out

    def test_create_is_idempotent_and_persists(self):
        first = self.store.create(self.body())
        again = self.store.create(self.body())
        self.assertFalse(first["duplicate"])
        self.assertTrue(again["duplicate"])
        self.assertEqual(first["decision"]["id"], again["decision"]["id"])
        with self.assertRaises(dm.DecisionError) as ctx:
            self.store.create(self.body(decision="Something else"))
        self.assertEqual((ctx.exception.code, ctx.exception.status), ("idempotency_conflict", 409))
        fresh = dm.DecisionStore(self.store.path, self.source, clock=self.clock).snapshot()
        self.assertEqual(fresh["stats"]["created"], 1)
        self.assertEqual(fresh["stats"]["total"], 2)
        self.assertEqual(fresh["stats"]["missing_owner"], 1)
        self.store.create(self.body(idempotency_key=""))
        self.store.create(self.body(idempotency_key=""))
        self.assertEqual(self.store.snapshot()["stats"]["created"], 3)  # no key: two real submissions stay two

    def test_validation(self):
        for kw, code in (({"decision": ""}, "decision_required"), ({"rationale": " "}, "rationale_required"),
                         ({"review_at": "2026-02-30"}, "bad_date"), ({"review_at": "tomorrow"}, "bad_date"),
                         ({"sources": ["javascript:alert(1)"]}, "bad_sources"), ({"sources": ["http://x.y"]}, "bad_sources"),
                         ({"sources": ["/static/../app.py"]}, "bad_sources"), ({"sources": "https://x.y"}, "bad_sources"),
                         ({"owner": "x" * 81}, "too_long"), ({"owner": 5}, "bad_field"),
                         ({"rationale": "FACTORY_PASSWORD=abcdef1234567890abcdef12"}, "secret_like_text")):
            with self.assertRaises(dm.DecisionError, msg=kw) as ctx:
                self.store.create(self.body(idempotency_key="", **kw))
            self.assertEqual(ctx.exception.code, code, kw)
        self.assertEqual(self.store.snapshot()["stats"]["created"], 0)

    def test_fill_imported_record_and_review_cycle(self):
        rec = self.store.update(self.imported, {"owner": "Andrii", "expected_outcome": "one deploy path", "review_at": "2026-11-20"})
        self.assertEqual((rec["owner"], rec["follow_up"]), ("Andrii", "scheduled"))
        self.clock.now = T0 + 6 * DAY
        snap = self.store.snapshot()
        self.assertEqual(snap["stats"]["due"], 1)
        with self.assertRaises(dm.DecisionError):
            self.store.update(self.imported, {"decision": "rewrite history"})  # imported text is not editable
        r1 = self.store.review(self.imported, {"verdict": "as_expected", "note": "held", "idempotency_key": "r1"})
        r2 = self.store.review(self.imported, {"verdict": "as_expected", "note": "held", "idempotency_key": "r1"})
        self.assertTrue(r2["duplicate"])
        self.assertEqual(r1["review"]["id"], r2["review"]["id"])
        rec = next(r for r in self.store.snapshot()["decisions"] if r["id"] == self.imported)
        self.assertEqual((rec["follow_up"], len(rec["reviews"]), rec["review_at"]), ("reviewed", 1, ""))
        self.store.review(self.imported, {"verdict": "partly", "next_review_at": "2027-01-10"})
        rec = next(r for r in self.store.snapshot()["decisions"] if r["id"] == self.imported)
        self.assertEqual((rec["follow_up"], len(rec["reviews"])), ("scheduled", 2))
        for bad, code in (({"verdict": "great"}, "bad_verdict"), ({"verdict": "partly", "next_review_at": "x"}, "bad_date")):
            with self.assertRaises(dm.DecisionError) as ctx:
                self.store.review(self.imported, bad)
            self.assertEqual(ctx.exception.code, code)
        with self.assertRaises(dm.DecisionError) as ctx:
            self.store.review("dmd-missing", {"verdict": "partly"})
        self.assertEqual(ctx.exception.status, 404)

    def test_damaged_store_is_not_replaced(self):
        self.store.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(dm.DecisionError) as ctx:
            self.store.snapshot()
        self.assertEqual(ctx.exception.status, 503)
        with self.assertRaises(dm.DecisionError):
            self.store.create(self.body())
        self.assertEqual(self.store.path.read_text(encoding="utf-8"), "{not json")

    def test_concurrent_creates_with_one_key_make_one_decision(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            ids = set(pool.map(lambda _: self.store.create(self.body())["decision"]["id"], range(8)))
        self.assertEqual(len(ids), 1)
        self.assertEqual(self.store.snapshot()["stats"]["created"], 1)


class RouteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.who = {}
        app = FastAPI()
        store = dm.DecisionStore(Path(self.tmp.name) / "dm.json", ROOT / "DECISIONS.md")
        dm.install_decision_memory_routes(app, store, lambda request: dict(self.who))
        self.client = TestClient(app)

    def tearDown(self):
        self.tmp.cleanup()

    def test_owner_only(self):
        body = {"decision": "d", "rationale": "r"}
        for who, status in (({}, 401), ({"role": "viewer"}, 403), ({"role": "member", "email": "m@x"}, 403)):
            self.who = who
            self.assertEqual(self.client.get("/api/decision-memory").status_code, status, who)
            self.assertEqual(self.client.post("/api/decision-memory/decisions", json=body).status_code, status, who)
        self.who = {"role": "owner", "email": "owner@example.com"}
        snap = self.client.get("/api/decision-memory").json()
        self.assertGreater(snap["stats"]["imported"], 100)
        made = self.client.post("/api/decision-memory/decisions", json=dict(body, idempotency_key="a")).json()
        self.assertEqual(made["decision"]["actor"], "owner@example.com")
        did = made["decision"]["id"]
        self.assertEqual(self.client.post(f"/api/decision-memory/decisions/{did}", json={"owner": "me"}).json()["owner"], "me")
        self.assertEqual(self.client.post(f"/api/decision-memory/decisions/{did}/reviews", json={"verdict": "missed"}).status_code, 200)
        self.assertEqual(self.client.post("/api/decision-memory/decisions", content=b"[1]",
                                          headers={"content-type": "application/json"}).json(), {"detail": "bad_body"})
        self.assertEqual(self.client.post("/api/decision-memory/decisions/nope", json={"owner": "x"}).status_code, 404)


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.registry = MvpRegistry(self.base / "mvp.json")
        self.marker = self.base / "dm.marker"

    def tearDown(self):
        self.tmp.cleanup()

    def pilot(self):
        return next(p for p in self.registry.snapshot()["projects"] if p["issue"] == 187)

    def test_links_existing_pilot_and_stops_at_agent_gate(self):
        before = len(self.registry.snapshot()["projects"])
        with patch.object(dm, "PILOT_PR", 0):
            self.assertEqual(dm.sync_mvp_registry_once(self.registry, self.marker), ["prototype", "idea", "researching"])
            self.assertEqual(dm.sync_mvp_registry_once(self.registry, self.marker), [])
        p = self.pilot()
        self.assertEqual((p["id"], p["stage"], p["prototype"]), ("decision-memory", "spec_draft", dm.PAGE))
        with patch.object(dm, "PILOT_PR", 999):  # PR number known later: one more agent-allowed step, then stop
            self.assertEqual(dm.sync_mvp_registry_once(self.registry, self.marker), ["spec_draft"])
            self.assertEqual(dm.sync_mvp_registry_once(self.registry, self.marker), [])
        p = self.pilot()
        self.assertEqual(p["stage"], "spec_review")
        self.assertEqual(len(self.registry.snapshot()["projects"]), before)  # no second registry entry
        events = [e for e in self.registry.snapshot()["events"] if e["project"] == "decision-memory" and e["actor"] == dm.AGENT]
        self.assertTrue(all(e["evidence"] for e in events))
        self.assertIn(f"{dm.REPO}/pull/999", events[-1]["evidence"])
        # build_queued and later stay with the owner: the agent role is refused by the registry itself.
        with self.assertRaises(Exception):
            self.registry.record("decision-memory", "advance", actor_role="agent", evidence=[dm.PAGE])

    def test_owner_moves_and_removals_are_respected(self):
        self.registry.record("decision-memory", "block", actor_role="owner", reason="paused by owner")
        with patch.object(dm, "PILOT_PR", 5):
            self.assertEqual(dm.sync_mvp_registry_once(self.registry, self.marker), ["prototype"])
        self.assertEqual(self.pilot()["stage"], "idea")
        data = json.loads((self.base / "mvp.json").read_text())
        del data["projects"]["decision-memory"]
        (self.base / "mvp.json").write_text(json.dumps(data))
        marker2 = self.base / "other.marker"
        self.assertEqual(dm.sync_mvp_registry_once(self.registry, marker2), [])
        self.assertFalse(any(p["issue"] == 187 for p in self.registry.snapshot()["projects"]))

    def test_set_prototype_guards(self):
        for url in ("https://evil.example/x", "/static/../app.py", "javascript:1", "/static//x"):
            with self.assertRaises(Exception):
                self.registry.set_prototype("decision-memory", url, actor_role="owner")
        with self.assertRaises(Exception):
            self.registry.set_prototype("decision-memory", dm.PAGE, actor_role="viewer")


class PageTests(unittest.TestCase):
    html = (ROOT / "static/decision-memory/index.html").read_text(encoding="utf-8")

    def test_script_parses_and_locales_match(self):
        script = self.html.rsplit("<script>", 1)[1].split("</script>", 1)[0]
        self.assertEqual(self.html.count("<script"), 1)
        node = shutil.which("node")
        if node:
            with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
                f.write(script)
            subprocess.run([node, "--check", f.name], check=True)
        blocks = {lang: set(re.findall(r"(\w+):'", re.search(lang + r":\{(.*?)\}(?:,\n (?:uk|en):|\};)", script, re.S).group(1)))
                  for lang in ("ru", "uk", "en")}
        self.assertEqual(blocks["ru"], blocks["uk"])
        self.assertEqual(blocks["ru"], blocks["en"])
        for k in re.findall(r"data-t=\"(\w+)\"", self.html):
            self.assertIn(k, blocks["en"])

    def test_page_holds_no_data_and_calls_only_own_api(self):
        self.assertNotIn("**Decision:**", self.html)
        self.assertEqual(set(re.findall(r"fetch\('([^']+)'", self.html)), {"/api/decision-memory"})
        self.assertNotRegex(self.html, r"(?:src|href)=[\"']?(?:https?:)?//")  # no third-party scripts, fonts or beacons


if __name__ == "__main__":
    unittest.main()
