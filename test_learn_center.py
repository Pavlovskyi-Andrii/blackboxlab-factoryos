"""Owner 2026-11-14: the Learning section (/learn) — catalog complete, docs escaped, prototypes sandboxed, login kept."""
import html as html_mod
import re
import shutil
import tempfile
import unittest
from pathlib import Path

import fastapi
from fastapi import HTTPException

import brand_strategy
import learn_center as lc

BASE = Path(__file__).parent


class LearnCenterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        app = fastapi.FastAPI()
        lc.install_learn_routes(app, base=BASE, steps_source=lambda: brand_strategy.STEPS)
        cls.h = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}   # no httpx needed on CI

    def view(self, item_id, lang="ru"):
        r = self.h["/learn/view/{item_id}"](item_id, lang)
        text = Path(r.path).read_text(encoding="utf-8") if hasattr(r, "path") else r.body.decode()
        return r, text

    def missing(self, item_id):
        with self.assertRaises(HTTPException) as e:
            self.h["/learn/view/{item_id}"](item_id)
        return e.exception.status_code

    def test_catalog_has_three_shelves_and_every_item_exists(self):
        d = self.h["/api/learn"]()
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
            r, text = self.view(item["id"])
            self.assertEqual(r.status_code, 200, item["id"])
            csp = r.headers["content-security-policy"]
            if item["kind"] == "html":
                self.assertTrue(csp.startswith("sandbox allow-scripts;"), item["id"])   # opaque origin: no cookies/API
                self.assertNotIn("allow-same-origin", csp)
                self.assertIn("default-src 'none'", csp)
            else:
                self.assertNotIn("script-src", csp)                        # rendered docs run no script at all
                self.assertNotIn("<script", text)
        self.assertEqual(self.missing("../../app.py"), 404)
        self.assertEqual(self.missing("nope"), 404)
        self.assertIn("Распаковка", self.view("brand-method")[1])

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
        page = self.h["/learn"]()
        html = Path(page.path).read_text(encoding="utf-8")
        self.assertEqual(page.status_code, 200)
        self.assertIn("/api/learn", html)
        self.assertIn('sandbox="allow-scripts', html)
        self.assertNotIn("allow-same-origin", html)
        nav = (BASE / "static/index.html").read_text(encoding="utf-8")
        self.assertIn('data-nav-id="learn"', nav)
        self.assertIn("function openLearning(){location.href='/learn'}", nav)


    # --- T-667: guides in RU / UK / EN ------------------------------------------------------------------------------
    def test_every_markdown_guide_exists_in_all_three_languages(self):
        for item in lc.CATALOG:
            if item["kind"] != "md":
                continue
            self.assertIn(item["lang"], lc.LANGS, item["id"])
            self.assertEqual(lc.available_langs(BASE, item), list(lc.LANGS), item["id"])
            original = (BASE / item["path"]).read_text(encoding="utf-8")
            for lang in lc.LANGS:
                path = lc.doc_path(item, lang)
                if lang != item["lang"]:
                    self.assertEqual(path, item["path"][:-3] + f".{lang}.md")
                    self.assertNotEqual((BASE / path).read_text(encoding="utf-8").strip(), original.strip(), path)
                r, text = self.view(item["id"], lang)
                self.assertEqual(r.headers["content-language"], lang, (item["id"], lang))
                self.assertIn(f'<html lang="{lang}">', text)
                self.assertIn(f"<title>{html_mod.escape(item['title'][lang])}</title>", text)
                self.assertNotIn("class=\"langnote\"", text)                      # translated: no "only in X" banner
                self.assertNotIn("<script", text)

    def test_translations_are_in_the_right_language(self):
        def prose(path):
            t = (BASE / path).read_text(encoding="utf-8")
            t = re.sub(r"```.*?```", " ", t, flags=re.S)
            t = re.sub(r"`[^`]*`", " ", t)
            t = re.sub(r"«[^»]*»|\"[^\"\n]*\"|\([^()\n]*\)", " ", t)   # quoted UI labels / glosses may stay literal
            return t
        cyr = re.compile(r"[А-Яа-яЁёІіЇїЄєҐґ]")
        for item in lc.CATALOG:
            if item["kind"] != "md":
                continue
            for lang in lc.LANGS:
                path = lc.doc_path(item, lang)
                text = prose(path)
                if lang == "uk":
                    self.assertFalse(re.search(r"[ыэъёЫЭЪЁ]", text), (path, re.findall(r"\w*[ыэъё]\w*", text)[:5]))
                    self.assertTrue(re.search(r"[іїєІЇЄ]", text), path)
                elif lang == "ru":
                    self.assertFalse(re.search(r"[іїєґІЇЄҐ]", text), (path, re.findall(r"\w*[іїєґ]\w*", text)[:5]))
                    self.assertTrue(cyr.search(text), path)
                else:
                    letters = len(re.findall(r"[A-Za-z]", text))
                    self.assertLess(len(cyr.findall(text)), max(40, letters // 50), path)   # English prose

    def test_missing_translation_falls_back_to_the_original_and_says_so(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            for item_id in ("mycast", "browser-agent"):
                src = BASE / lc.BY_ID[item_id]["path"]
                (tmp / src.relative_to(BASE)).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(src, tmp / src.relative_to(BASE))                 # originals only, no translations
            app = fastapi.FastAPI()
            lc.install_learn_routes(app, base=tmp, steps_source=lambda: brand_strategy.STEPS)
            h = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
            r = h["/learn/view/{item_id}"]("mycast", "en")
            body = r.body.decode()
            self.assertEqual(r.headers["content-language"], "ru")
            self.assertIn('<html lang="ru">', body)
            self.assertIn("only available in Russian", body)
            r = h["/learn/view/{item_id}"]("browser-agent", "uk")
            self.assertIn("лише англійською", r.body.decode())
            self.assertEqual(r.headers["content-language"], "en")
            items = {i["id"]: i for i in h["/api/learn"]()["items"]}
            self.assertEqual(items["mycast"]["langs"], ["ru"])
            self.assertEqual(items["browser-agent"]["langs"], ["en"])
            self.assertFalse(items["oauth"]["available"])
        finally:
            shutil.rmtree(tmp)

    def test_lang_parameter_cannot_reach_other_files(self):
        allowed = {lc.doc_path(i, lang) for i in lc.CATALOG for lang in lc.LANGS}
        for item in lc.CATALOG:
            for bad in ("../../app", "en/../../app.py", "../.env", "EN", "", None, "de", "ru.md", "uk%2f..%2f"):
                path, served = lc.resolve_doc(BASE, item, bad)
                self.assertIn(path, allowed)
                self.assertIn(served, lc.LANGS)
            for lang in lc.LANGS:
                p = lc.doc_path(item, lang)
                self.assertNotIn("..", p)
                self.assertEqual(Path(p).parent, Path(item["path"]).parent)   # always next to the catalog original
        with self.assertRaises(ValueError):
            lc.doc_path(lc.BY_ID["mycast"], "../x")
        self.assertEqual(lc.normalize_lang("../../etc/passwd"), "ru")
        self.assertEqual(lc.normalize_lang("EN"), "en")
        r, text = self.view("mycast", "../../app.py")                       # unknown lang → default language, same file
        self.assertEqual(r.headers["content-language"], "ru")
        self.assertNotIn("FastAPI(", text)

    def test_steps_and_api_follow_the_language(self):
        self.assertIn("Brand strategy method", self.view("brand-method", "en")[1])
        self.assertIn("Метод бренд-стратегії", self.view("brand-method", "uk")[1])
        items = {i["id"]: i for i in self.h["/api/learn"]()["items"]}
        self.assertEqual(items["brand-method"]["langs"], list(lc.LANGS))
        self.assertEqual(items["motion-explainer"]["langs"], ["ru"])
        page = (BASE / "static/learn/index.html").read_text(encoding="utf-8")
        self.assertIn("'?lang=' + encodeURIComponent(lang)", page)          # the viewer asks for the chosen language

    def test_how_it_works_shelf_has_the_new_product_guides(self):
        guide = [i["id"] for i in lc.CATALOG if i["section"] == "guide"]
        for item_id in ("surfer", "agent-workspace", "mvp-pilots", "mycast-library", "autopilot-cycle",
                        "telegram-relay-proof", "owner-desk"):
            self.assertIn(item_id, guide)


if __name__ == "__main__":
    unittest.main(verbosity=2)
