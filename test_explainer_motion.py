"""#353: the Claude motion explainer stays self-contained, offline and complete in RU/UK/EN."""
import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HTML = Path(__file__).parent / "docs/prototypes/factoryos-explainer/claude-motion/index.html"


class ExplainerTest(unittest.TestCase):
    def setUp(self):
        self.html = HTML.read_text(encoding="utf-8")
        self.js = self.html.rsplit("<script>", 1)[1].split("</script>", 1)[0]

    def test_no_external_resources(self):
        urls = set(re.findall(r"https?://[^\s'\"`)<>]+", self.html))
        self.assertEqual(urls, {"http://www.w3.org/2000/svg"})
        self.assertNotRegex(self.html, r"<(script|link|img|iframe|audio|video)[^>]+(src|href)=")
        self.assertNotIn("fetch(", self.js)

    def test_script_parses(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
            f.write(self.js)
        subprocess.run(["node", "--check", f.name], check=True)

    def test_languages_and_scenes_complete(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        block = self.js[self.js.index("const L = {"):self.js.index("let lang")]
        out = subprocess.run(["node", "-e", block + "\nconsole.log(JSON.stringify(L))"], capture_output=True, text=True, check=True)
        lang = json.loads(out.stdout)
        ru = lang["ru"]
        for code in ("uk", "en"):
            self.assertEqual(set(lang[code]), set(ru), code)
            self.assertEqual(set(lang[code]["k"]), set(ru["k"]), code)
            for key in ("scenes", "msg", "vo"):
                self.assertEqual(len(lang[code][key]), 9, (code, key))
        self.assertEqual(len(ru["msg"]), 9)
        self.assertIn("DEMO", ru["footnote"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
