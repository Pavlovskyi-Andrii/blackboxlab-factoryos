"""Owner 2026-11-14: the Learning section (/learn) — catalog complete, docs escaped, prototypes sandboxed, login kept."""
import re
import unittest
from pathlib import Path

import fastapi
from fastapi.testclient import TestClient

import brand_strategy
import learn_center as lc

BASE = Path(__file__).parent


class LearnCenterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = fastapi.FastAPI()
        lc.install_learn_routes(app, base=BASE, steps_source=lambda: brand_strategy.STEPS)
        cls.c = TestClient(app)

    def test_catalog_has_three_shelves_and_every_item_exists(self):
        d = self.c.get("/api/learn").json()
        self.assertEqual(d["sections"], ["mine", "explainers", "guide"])
        for s in d["sections"]:
            self.assertTrue([i for i in d["items"] if i["section"] == s], s)
        for i in d["items"]:
            self.assertTrue(i["available"], i["id"])                      # nothing on the shelf points at a missing file
            for lang in ("ru", "uk", "en"):
                self.assertTrue(i["title"][lang] and i["desc"][lang], (i["id"], lang))
        self.assertEqual(len({i["id"] for i in d["items"]}), len(d["items"]))

    def test_every_item_opens(self):
        for item in lc.CATALOG:
            r = self.c.get(f"/learn/view/{item['id']}")
            self.assertEqual(r.status_code, 200, item["id"])
            csp = r.headers["content-security-policy"]
            if item["kind"] == "html":
                self.assertTrue(csp.startswith("sandbox allow-scripts;"), item["id"])   # opaque origin: no cookies/API
                self.assertNotIn("allow-same-origin", csp)
                self.assertIn("default-src 'none'", csp)
            else:
                self.assertNotIn("script-src", csp)                        # rendered docs run no script at all
                self.assertNotIn("<script", r.text)
        self.assertEqual(self.c.get("/learn/view/../../app.py").status_code, 404)
        self.assertEqual(self.c.get("/learn/view/nope").status_code, 404)
        self.assertIn("Распаковка", self.c.get("/learn/view/brand-method").text)

    def test_markdown_is_escaped_first(self):
        out = lc.render_markdown("# T <b>\n\n<script>alert(1)</script> **x** `y` [ok](https://a.b/c) [bad](javascript:alert(1))\n\n- a\n- b\n\n| h | i |\n|---|---|\n| 1 | <img> |")
        self.assertNotIn("<script", out)
        self.assertNotIn("<img", out)
        self.assertIn("&lt;script&gt;", out)
        self.assertIn('<a href="https://a.b/c" target="_blank" rel="noopener noreferrer">ok</a>', out)
        self.assertNotIn('href="javascript', out)
        self.assertIn("<ul><li>a</li><li>b</li></ul>", out)
        self.assertIn("<th>h</th>", out)

    def test_page_and_wiring_stay_behind_login(self):
        app_src = (BASE / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_learn_routes(app, base=BASE", app_src)
        prefixes = re.search(r"public_prefixes = \(([^)]*)\)", app_src).group(1)
        self.assertNotIn("/learn", prefixes)
        page = self.c.get("/learn")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/api/learn", page.text)
        self.assertIn('sandbox="allow-scripts', page.text)
        self.assertNotIn("allow-same-origin", page.text)
        nav = (BASE / "static/index.html").read_text(encoding="utf-8")
        self.assertIn('data-nav-id="learn"', nav)
        self.assertIn("function openLearning(){location.href='/learn'}", nav)


if __name__ == "__main__":
    unittest.main(verbosity=2)
