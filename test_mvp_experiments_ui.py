"""T-609 A/B Tester S2: source contract of the experiment lanes in the dashboard MVP panel (#348 §6.3)."""
import json
import re
import unittest
from pathlib import Path

HTML = (Path(__file__).parent / "static/index.html").read_text(encoding="utf-8")


def block():
    start = HTML.index("// T-609 A/B Tester S2: experiment lanes")
    return HTML[start:HTML.index("async function mvpSend(){", start)]


def table(lang):
    m = re.search(r"Object\.assign\(I18N\.%s,(\{\"mvpx\.title\".*?\})\);" % lang, HTML)
    return json.loads(m.group(1))


class ExperimentLanesUiTest(unittest.TestCase):
    def test_wired_into_the_mvp_panel(self):
        self.assertIn("loadMvpCycle(id);loadMvpExperiments(id)", HTML)
        self.assertIn("mvpPipelineHtml(c)+mvpExperimentsHtml(mvpOpen)", HTML)

    def test_lane_a_renders_before_lane_b_and_compare_has_no_winner(self):
        js = block()
        self.assertIn("for(const b of (x.branches||[]))", js)           # API order a then b, no re-sorting
        self.assertNotIn(".reverse()", js)
        self.assertNotIn("sort(", js)
        self.assertIn("'mvpx.compare.'+(cmp.reason||'not_instrumented')", js)
        self.assertNotRegex(js, r"cmp\.winner|\.lift\b|significance")      # the UI never shows a winner/lift

    def test_owner_gates_and_only_mvp_api_calls(self):
        js = block()
        self.assertIn("if(own&&b.revision&&!b.preview_approved)", js)       # approve button only for the owner
        self.assertIn("else if(!ro&&own)", js)                              # decision form only for the owner
        self.assertIn("if(!pid||mvpReadOnly()||!mvpIsOwner())return", js)
        urls = re.findall(r"fetch\(([^,]+),", js)
        self.assertTrue(urls and all("url" == u.strip() or "/api/mvp-factory/" in u for u in urls), urls)
        self.assertNotIn("innerHTML", js)                                   # strings are built with esc() only

    def test_every_button_has_a_handler_and_every_field_a_label(self):
        js = block()
        for btn in re.findall(r"<button[^>]*>", js):
            self.assertIn("onclick=", btn)
        self.assertGreaterEqual(js.count("<label class=\"mvpExpLbl\""), 2)

    def test_locales_complete(self):
        en, uk, ru = table("en"), table("uk"), table("ru")
        self.assertEqual(set(en), set(uk))
        self.assertEqual(set(en), set(ru))
        used = set(re.findall(r"tr\('(mvpx\.[a-zA-Z_.]+)'", block()))
        dyn = {"mvpx.mode.", "mvpx.modeNote.", "mvpx.state.", "mvpx.load.", "mvpx.compare.", "mvpx.choice."}
        for k in used - {u for u in used if any(u == d for d in dyn)}:
            self.assertIn(k, en, k)
        for prefix, values in (("mvpx.mode.", ("SEGMENT_COMPARISON", "CONTROLLED_AB")), ("mvpx.state.", ("draft", "closed")),
                               ("mvpx.compare.", ("segment_comparison", "not_instrumented")),
                               ("mvpx.choice.", ("continue_a", "continue_b", "both", "iterate", "pivot", "stop"))):
            for v in values:
                self.assertIn(prefix + v, en)
        self.assertIn("не рандомизированный", ru["mvpx.modeNote.SEGMENT_COMPARISON"])
        self.assertIn("не разрешение на публикацию", ru["mvpx.approved"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
