"""T-733 (#452): the owner-home prototype stays self-contained, honest and complete in EN/UK/RU.

The prototype is served by /learn/view/owner-home in a CSP sandbox, so it must not load anything from the network.
It shows demo data, so every language must carry the DEMO marker. The owner asked (2026-11-24) for a visible switch
to the current full dashboard («Pro version») and back, remembered per browser.
"""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT / "docs" / "prototypes" / "owner-home-growth" / "index.html"


def script() -> str:
    return re.findall(r"<script>(.*?)</script>", PAGE.read_text(encoding="utf-8"), re.S)[0]


def strings() -> dict:
    """Evaluate only the `const L = {...};` block in Node and return {lang: {key: value}}."""
    src = script()
    block = src[src.index("const L = "):src.index("/* ================= prototype state")]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "strings.js"
        path.write_text(block + "\nprocess.stdout.write(JSON.stringify(L));\n", encoding="utf-8")
        out = subprocess.run(["node", str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class OwnerHomePrototypeTest(unittest.TestCase):
    def test_registered_on_the_learning_shelf(self):
        import learn_center
        item = next(i for i in learn_center.CATALOG if i["id"] == "owner-home")
        self.assertEqual(item["kind"], "html")
        self.assertEqual(ROOT / item["path"], PAGE)
        self.assertEqual(set(item["title"]), {"ru", "uk", "en"})

    def test_one_plain_script_block(self):
        # CI runs `node --check` on the text between the last bare <script> and </script>: that must be all the code.
        html = PAGE.read_text(encoding="utf-8")
        self.assertEqual(len(re.findall(r"<script\b", html)), 1, "keep all code in one script block")
        self.assertEqual(html.count("<script>"), 1, "the script tag has no attributes, so the CI extraction finds it")
        self.assertNotRegex(html, r"\son[a-z]+=", "no inline event-handler attributes outside the checked script")

    def test_no_network_resources(self):
        html = PAGE.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"https?://", html), "the sandbox blocks every external load; keep the page inline")
        self.assertNotIn("fetch(", html)
        self.assertNotIn("XMLHttpRequest", html)

    def test_storage_is_optional(self):
        # The sandbox has an opaque origin: localStorage throws there, the page must keep working in memory.
        src = script()
        for call in re.finditer(r"localStorage\.\w+\(", src):
            before = src[max(0, call.start() - 40):call.start()]
            self.assertIn("try{", before, "every localStorage call sits inside try/catch")

    @unittest.skipUnless(shutil.which("node"), "node is needed to read the string table")
    def test_three_languages_have_the_same_keys_and_placeholders(self):
        table = strings()
        self.assertEqual(set(table), {"en", "uk", "ru"})
        en = table["en"]
        for lang in ("uk", "ru"):
            self.assertEqual(set(table[lang]), set(en), f"{lang}: missing or extra keys")
            for key, value in en.items():
                self.assertTrue(table[lang][key].strip(), f"{lang}.{key} is empty")
                self.assertEqual(sorted(re.findall(r"\{\w+\}", value)), sorted(re.findall(r"\{\w+\}", table[lang][key])),
                                 f"{lang}.{key}: placeholders differ")
        self.assertRegex(table["uk"]["promise"], "[іїєґ]")
        self.assertRegex(table["ru"]["promise"], "[ыэё]")

    @unittest.skipUnless(shutil.which("node"), "node is needed to read the string table")
    def test_demo_marker_and_pro_switch_in_every_language(self):
        table = strings()
        for lang, values in table.items():
            self.assertTrue(values["demo"] and values["pLabel"], lang)
            for key in ("pro", "proHint", "simple", "proBack", "proRemember"):
                self.assertTrue(values[key], f"{lang}.{key}")
        src = script()
        self.assertIn('store("factoryos_home_view"', src, "the Pro/simple choice is remembered per browser")
        self.assertIn('load("factoryos_home_view")', src)

    def test_eight_states_and_every_view(self):
        src = script()
        states = re.search(r"const STATES = \[(.*?)\]", src).group(1)
        self.assertEqual([s.strip().strip('"') for s in states.split(",")],
                         ["new", "empty", "working", "approval", "completed", "failed", "offline", "budget"])
        views = re.search(r"const VIEWS = \[(.*?)\]", src).group(1)
        for view in ("home", "needs", "results", "team", "tools", "goal-mycast", "compare", "wizard", "pro"):
            self.assertIn(f'"{view}"', views)

    def test_decision_does_not_publish(self):
        # Choosing a variant and publishing are two acts (issue #452 §6.6–6.7, benchmark P-07).
        table_src = script()
        self.assertIn("Nothing is published", table_src)
        self.assertNotRegex(table_src, r"data-act=\"publish")


if __name__ == "__main__":
    unittest.main()
