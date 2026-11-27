"""T-742: one read model for both MVP Builder pages (dashboard card and /static/mvp-factory/index.html).

Owner 2026-11-27: «приведи к единому стандарту чтоб была синхронизация проектов на обеих страницах».
The server computes stage, status, progress, next step and links once (`mvp_factory.view_model`) and ships the
RU/UK/EN wording (`LABELS`); both pages render only from it. Run: python test_mvp_view.py
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import mvp_factory
from mvp_factory import LABELS, NEXT, PATH, STAGES, MvpRegistry, view_model

ROOT = Path(__file__).resolve().parent
DASH = (ROOT / "static/index.html").read_text(encoding="utf-8")
FULL = (ROOT / "static/mvp-factory/index.html").read_text(encoding="utf-8")


def _mvp_block(html: str) -> str:
    """The dashboard's MVP Builder card code (between its begin marker and the cycle panel)."""
    start = html.index("// --- mvp-builder:begin")
    return html[start:html.index("function openMvpNew(", start)]


class ViewModelTest(unittest.TestCase):
    def test_every_open_stage_has_one_next_step(self):
        expected = {  # stage -> (progress %, step, next stage, who acts, owner decision)
            "idea": (0, 0, "researching", "Product Analyst", False),
            "researching": (11, 1, "spec_draft", "Spec Writer", False),
            "spec_draft": (22, 2, "spec_review", "MVP Manager", False),
            "spec_review": (33, 3, "build_queued", "Owner", True),
            "build_queued": (44, 4, "building", "Claude Builder", False),
            "building": (56, 5, "qa_review", "QA / Security", False),
            "qa_review": (67, 6, "preview_ready", "Deploy Agent", False),
            "preview_ready": (78, 7, "owner_review", "Owner", True),
            "owner_review": (89, 8, "validated", "Owner", True),
        }
        self.assertEqual(set(expected), set(NEXT))
        for stage, (pct, step, nxt, role, owner) in expected.items():
            v = view_model({"id": "p1", "stage": stage})
            self.assertEqual((v["stage"], v["progress"], v["step"], v["steps"]), (stage, pct, step, 9), stage)
            self.assertEqual(v["next"], {"key": stage, "stage": nxt, "role": role, "owner": owner}, stage)
            self.assertEqual(v["status"], "owner" if owner else "active", stage)
            self.assertEqual(v["progress"], mvp_factory.progress({"stage": stage}))   # one progress formula
            # the legacy recommendation agrees with the read model on who decides
            self.assertEqual(mvp_factory.recommend({"stage": stage})["decision"] == "owner", owner, stage)

    def test_closed_blocked_and_rejected(self):
        v = view_model({"id": "p", "stage": "validated"})
        self.assertEqual((v["status"], v["progress"], v["step"], v["next"]["key"], v["next"]["owner"]), ("validated", 100, 9, "validated", False))
        events = [{"kind": "reject", "from_stage": "qa_review", "to_stage": "rejected"}]
        v = view_model({"id": "p", "stage": "rejected"}, events)
        self.assertEqual((v["status"], v["progress"], v["next"]["key"]), ("rejected", 67, "rejected"))   # stays where it stopped
        self.assertEqual(view_model({"id": "p", "stage": "rejected"})["progress"], 0)
        v = view_model({"id": "p", "stage": "building", "blocked": {"reason": "CI red"}})
        self.assertEqual((v["status"], v["stage"], v["progress"], v["blocked_reason"]), ("blocked", "building", 56, "CI red"))
        self.assertEqual(v["next"], {"key": "blocked", "stage": None, "role": "Owner", "owner": True})

    def test_links_are_computed_once(self):
        keys = lambda p: [l["key"] for l in view_model(p)["links"]]
        self.assertEqual(keys({"id": "mycast", "stage": "preview_ready", "issue": 261, "prototype": "/static/mycast-configurator/index.html"}),
                         ["issue", "prototype", "launchpad", "evolution"])
        self.assertEqual(keys({"id": "faceless-creator", "stage": "idea", "issue": 313}), ["issue", "crm", "launchpad", "evolution"])
        self.assertEqual(keys({"id": "faceless-crm", "stage": "idea", "issue": 359}), ["issue", "crm", "launchpad", "evolution"])
        self.assertEqual(keys({"id": "release-guardian", "stage": "idea", "issue": 189}), ["issue", "guardian", "launchpad", "evolution"])
        self.assertEqual(keys({"id": "x", "stage": "idea", "issue": 0, "prototype": "https://evil.example/"}), ["launchpad", "evolution"])
        issue = view_model({"id": "x", "stage": "idea", "issue": 187})["links"][0]
        self.assertEqual((issue["text"], issue["href"]), ("#187", mvp_factory.REPO + "/issues/187"))
        self.assertEqual(view_model({"id": "mycast", "stage": "idea"})["anchor"], "/static/mvp-factory/index.html#p-mycast")

    def test_snapshot_ships_view_summary_and_labels_for_every_project(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            reg = MvpRegistry(tmp / "mvp.json")
            reg.add_project("", "Request-only project", 0, actor_role="owner", brief="A brief, no issue")
            reg.record("decision-memory", "block", actor_role="owner", reason="waiting for data")
            snap = reg.snapshot()
        finally:
            shutil.rmtree(tmp)
        self.assertEqual(snap["view_version"], 1)
        self.assertIs(snap["labels"], LABELS)
        ids = [p["id"] for p in snap["projects"]]
        self.assertIn("request-only-project", ids)            # a project with a brief and no issue is listed like the rest
        for p in snap["projects"]:
            self.assertEqual(p["view"], view_model(p, [e for e in snap["events"] if e["project"] == p["id"]]))
        sm = snap["summary"]
        self.assertEqual(sm["total"], len(ids))
        self.assertEqual(sm["total"], sm["active"] + sm["owner"] + sm["blocked"] + sm["closed"])
        self.assertEqual(sm["blocked"], 1)
        self.assertEqual(sum(sm["by_stage"].values()), len(ids))


class LabelsTest(unittest.TestCase):
    def test_three_languages_cover_every_stage_and_next_step(self):
        self.assertEqual(set(LABELS), {"uk", "ru", "en"})
        for lang, table in LABELS.items():
            self.assertEqual(set(table["stage"]), set(STAGES), lang)
            self.assertEqual(set(table["next"]), set(NEXT) | {"validated", "rejected", "blocked"}, lang)
            for group in ("ui", "links"):
                self.assertEqual(set(table[group]), set(LABELS["en"][group]), (lang, group))
            self.assertTrue(all(str(v).strip() for g in table.values() for v in g.values()), lang)
        same_ok = {("links", k) for k in ("crm", "guardian", "launchpad", "evolution", "issue")}
        for lang in ("uk", "ru"):
            for group, values in LABELS[lang].items():
                for key, value in values.items():
                    if (group, key) not in same_ok:
                        self.assertNotEqual(value, LABELS["en"][group][key], (lang, group, key))
        # The owner's example (MyCast #261 at preview_ready): one wording, on both pages.
        self.assertEqual(LABELS["ru"]["next"]["preview_ready"], "Ваша проверка превью")
        self.assertEqual(LABELS["ru"]["stage"]["owner_review"], "Ваше решение")
        for table in LABELS.values():
            self.assertIn("{step}", table["ui"]["step"])
            self.assertIn("{steps}", table["ui"]["step"])


class PageParityTest(unittest.TestCase):
    def test_both_pages_read_the_same_endpoint_and_shared_fields(self):
        dash = _mvp_block(DASH)
        for html in (dash, FULL):
            self.assertIn("fetch('/api/mvp-factory'", html)
            for field in ("p.view", "v.next", "v.progress", "v.step", "v.steps", "v.links", "labels", ".summary"):
                self.assertIn(field, html, field)

    def test_no_page_side_state_logic(self):
        dash = _mvp_block(DASH)
        for name, html in (("dashboard", dash), ("full page", FULL)):
            for bad in ("recommendation", "next_stage", "p.progress", "[313,359]", "Number(p.issue)===189",
                        "'mvpb.stage.", "decision==='owner'", "PIPE.indexOf", "/ 100"):
                self.assertNotIn(bad, html, f"{name} re-derives state: {bad}")
        self.assertNotIn("stages:{", FULL)                         # stage names come from the server labels
        self.assertNotIn('"mvpb.stage.', DASH)
        self.assertNotIn('"mvpb.ownerRole"', DASH)

    def test_full_page_refreshes_like_the_dashboard(self):
        self.assertIn("setInterval(refresh,30000)", FULL)
        self.assertIn("visibilitychange", FULL)
        self.assertIn("addEventListener('focus',refresh)", FULL)
        self.assertIn("closest('form.ev')", FULL)                  # never re-render under a half-typed event form
        self.assertRegex(DASH, r"function render\(\)\{[^\n]*mvpProjects\(\);loadMvpProjects\(\)")

    def test_dashboard_never_hides_a_project_silently(self):
        dash = _mvp_block(DASH)
        self.assertIn("a.map(p=>", dash)                          # every project in the response is a row
        self.assertNotRegex(dash, r"projects\|\|\[\]\)\.(slice|filter)\(")
        self.assertIn("L.ui.shown", dash)                          # «показано N из M» if rows are ever fewer than the total

    def test_inline_scripts_parse(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        tmp = Path(tempfile.mkdtemp())
        try:
            for name, html in (("dash", DASH), ("full", FULL)):
                js = tmp / f"{name}.js"
                js.write_text("\n".join(re.findall(r"<script>(.*?)</script>", html, re.S)), encoding="utf-8")
                out = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True)
                self.assertEqual(out.returncode, 0, out.stderr)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
