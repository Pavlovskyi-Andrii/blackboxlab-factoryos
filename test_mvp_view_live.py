"""T-742 regression (Codex review on #492): the full MVP Builder page keeps refreshing while an event form holds a
draft, shows a project added meanwhile, and keeps the draft (text, retry key, focus) across the refresh.

Real Chromium through Playwright; the page and /api/mvp-factory are served by request interception, no server.
Skipped when Playwright or its browser is not installed. Run: python test_mvp_view_live.py
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from mvp_factory import MvpRegistry

ROOT = Path(__file__).resolve().parent
HTML = (ROOT / "static/mvp-factory/index.html").read_text(encoding="utf-8")
BASE = "http://mvp.test"

try:
    from playwright.sync_api import sync_playwright
except ImportError:   # pragma: no cover
    sync_playwright = None


class LiveRefreshKeepsDraftTest(unittest.TestCase):
    def setUp(self):
        if sync_playwright is None:
            self.skipTest("playwright not installed")
        self.tmp = Path(tempfile.mkdtemp())
        self.reg = MvpRegistry(self.tmp / "mvp.json")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_refresh_with_a_draft_shows_new_projects_and_keeps_the_draft(self):
        try:
            pw = sync_playwright().start()
            exe = os.environ.get("PW_CHROMIUM")   # optional: a preinstalled Chromium binary
            browser = pw.chromium.launch(**({"executable_path": exe} if exe else {}))
        except Exception as exc:   # pragma: no cover - browser binary missing
            self.skipTest(f"chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.route(BASE + "/static/mvp-factory/index.html",
                       lambda r: r.fulfill(status=200, content_type="text/html; charset=utf-8", body=HTML))
            page.route(BASE + "/api/mvp-factory",
                       lambda r: r.fulfill(status=200, content_type="application/json", body=json.dumps(self.reg.snapshot())))
            page.goto(BASE + "/static/mvp-factory/index.html")
            page.wait_for_selector("#p-mycast")
            self.assertEqual(page.locator("#p-added-elsewhere").count(), 0)

            page.locator("#p-mycast details.act summary").click()
            note = page.locator('#p-mycast form.ev input[name="note"]')
            note.fill("half-typed reason")
            page.locator('#p-mycast form.ev input[name="evidence"]').fill("https://github.com/o/r/pull/1")
            page.evaluate("document.querySelector('#p-mycast form.ev').dataset.key='retry-key-1'")
            note.click()
            page.keyboard.press("End")

            # A project added on the dashboard (or anywhere) while the draft sits in the form.
            self.reg.add_project("added-elsewhere", "Added elsewhere", 0, actor_role="owner", brief="b")
            page.evaluate("window.dispatchEvent(new Event('focus'))")
            page.wait_for_selector("#p-added-elsewhere", timeout=5000)

            self.assertEqual(note.input_value(), "half-typed reason")
            self.assertEqual(page.locator('#p-mycast form.ev input[name="evidence"]').input_value(), "https://github.com/o/r/pull/1")
            self.assertEqual(page.evaluate("document.querySelector('#p-mycast form.ev').dataset.key"), "retry-key-1")
            self.assertTrue(page.evaluate("document.querySelector('#p-mycast details.act').open"))
            self.assertEqual(page.evaluate("document.activeElement.name"), "note")
            page.keyboard.type("!")
            self.assertEqual(note.input_value(), "half-typed reason!")   # the cursor stayed where it was
        finally:
            browser.close()
            pw.stop()


if __name__ == "__main__":
    unittest.main()
