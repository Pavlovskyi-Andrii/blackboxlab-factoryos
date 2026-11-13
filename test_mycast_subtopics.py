"""MyCast AI subtopics: cache, caps, cleaning, public route. Offline: fake Gemini."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-subtopics-"))

import mycast_subtopics as ms  # noqa: E402


class ServiceTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.calls = []
        self.answer = ['{"topics": ["Growth loops", "Referral programs", "<b>SEO</b>", "growth hacking", "A/B tests", "Pricing", "Onboarding", "Extra"]}']

        def gen(key, prompt):
            self.calls.append(prompt)
            return self.answer[0]
        self.s = ms.SubtopicService(Path(self.dir.name), api_key=lambda: "k", generate=gen, clock=lambda: self.t[0],
                                    daily_cap=3, per_client_cap=2)

    def tearDown(self):
        self.dir.cleanup()

    def test_clean_cached_and_capped(self):
        out = self.s.suggest("growth hacking", "uk", "1.2.3.4")
        self.assertEqual(out["source"], "gemini")
        self.assertEqual(out["topics"], ["Growth loops", "Referral programs", "SEO", "A/B tests", "Pricing", "Onboarding"])
        self.assertIn("українською", self.calls[0])
        self.assertEqual(self.s.suggest("Growth  Hacking", "uk", "1.2.3.4")["source"], "cache")      # free repeat
        self.assertEqual(len(self.calls), 1)
        self.s.suggest("crypto", "uk", "1.2.3.4")
        self.assertEqual(self.s.suggest("ai agents", "uk", "1.2.3.4")["source"], "limit")          # per client
        self.s.suggest("ai agents", "uk", "5.6.7.8")
        self.assertEqual(self.s.suggest("startups", "uk", "9.9.9.9")["source"], "limit")           # daily cap
        self.t[0] += 86400
        self.assertEqual(self.s.suggest("startups", "uk", "9.9.9.9")["source"], "gemini")
        raw = (Path(self.dir.name) / "subtopics.json").read_text()
        self.assertNotIn("1.2.3.4", raw)                                                           # hashed only

    def test_failures_are_empty_not_errors(self):
        self.answer[0] = None
        self.assertEqual(self.s.suggest("growth", "ru", "c"), {"topics": [], "source": "unavailable"})
        self.answer[0] = "not json"
        self.assertEqual(self.s.suggest("growth2", "ru", "c")["topics"], [])
        self.assertEqual(self.s.suggest("x", "ru", "c"), {"topics": [], "source": "empty"})
        nokey = ms.SubtopicService(Path(self.dir.name) / "n", api_key=lambda: "", generate=lambda k, p: self.fail("no call"))
        self.assertEqual(nokey.suggest("growth", "en", "c")["source"], "unavailable")
        self.assertEqual(len(ms.normalize("a" * 500)), ms.MAX_QUERY)


class RouteTest(unittest.TestCase):
    def test_public_route(self):
        import app as factory
        from test_route_auth_fixes import AUTH_ON, call
        fake = ms.SubtopicService(Path(tempfile.mkdtemp()), api_key=lambda: "k",
                                  generate=lambda k, p: '{"topics": ["Referral programs"]}')
        with patch.object(factory, "FACTORY_PASSWORD", AUTH_ON), patch.object(factory, "MYCAST_SUBTOPICS", fake):
            status, body = call("GET", "/api/mycast/subtopics")
            self.assertEqual(status, 200)                                   # public beta page, no session
        self.assertEqual(json.loads(body)["source"], "empty")


if __name__ == "__main__":
    unittest.main(verbosity=2)
