"""Owner 2026-11-14: brand strategy passport (7 steps) -> Master Brief. Offline: fake LLM."""
import asyncio
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-strategy-"))

import fastapi  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import brand_strategy as bs  # noqa: E402
from brand_strategy_seeds import SEEDS  # noqa: E402


class Req:
    def __init__(self, body=None, role="owner"):
        self.body, self.role = body, role

    async def json(self):
        return self.body


def run(x):
    return asyncio.run(x) if asyncio.iscoroutine(x) else x


class StrategyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = bs.StrategyStore(pathlib.Path(self.tmp.name) / "s.json", seeds=SEEDS)
        self.calls = []

        async def draft(agent, system, user):
            self.calls.append((agent, system, user))
            return {"content": "LLM draft text", "cost_usd": 0.01}
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, self.store, identity=lambda r: {"role": r.role}, draft=draft)
        self.h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_mycast_starts_from_claudes_draft_and_nothing_is_approved(self):
        p = run(self.h[("GET", "/api/factory/strategy/{brand}")]("mycast", Req()))["passport"]
        self.assertEqual([p["steps"][str(n)]["state"] for n in range(1, 8)], ["draft"] * 7)
        self.assertTrue(all(p["steps"][str(n)]["text"] for n in range(1, 8)))
        self.assertEqual(len(p["step_meta"]), 7)
        brief = bs.master_brief(p)
        self.assertIn("Ещё не утверждено", brief)                     # drafts are never passed off as approved
        self.assertIn("Распаковка", bs.master_brief(p, approved_only=False))

    def test_chain_context_carries_earlier_steps_and_answers(self):
        p = self.store.get("mycast")
        _, user5 = bs.prompt_for(p, 5)
        self.assertIn("Шаг 4. Tone of Voice", user5)
        self.assertNotIn("Шаг 5.", user5)
        self.assertIn("(черновик, не утверждён)", user5)
        _, user2 = bs.prompt_for(p, 2)
        self.assertIn("Ответы автора на 7 вопросов", user2)
        self.assertIn(bs.UNPACK_QUESTIONS[0], user2)

    def test_owner_only_save_approve_draft_and_brief(self):
        get = self.h[("GET", "/api/factory/strategy/{brand}")]
        with self.assertRaises(HTTPException) as e:
            get("mycast", Req(role="viewer"))
        self.assertEqual(e.exception.status_code, 403)
        with self.assertRaises(HTTPException):
            get("../etc", Req())
        save = self.h[("POST", "/api/factory/strategy/{brand}/steps/{n}")]
        p = run(save("mycast", 1, Req({"text": "Цель: 100 слушателей", "approve": True})))["passport"]
        self.assertEqual((p["steps"]["1"]["state"], p["version"]), ("approved", 1))
        with self.assertRaises(HTTPException):
            run(save("mycast", 9, Req({"text": "x"})))
        p = run(self.h[("POST", "/api/factory/strategy/{brand}/steps/{n}/draft")]("mycast", 3, Req({})))["passport"]
        self.assertEqual((p["steps"]["3"]["state"], p["steps"]["3"]["by"], p["steps"]["3"]["text"]), ("draft", "llm", "LLM draft text"))
        self.assertEqual(self.calls[0][0], "Angle Strategist")
        self.assertIn("Цель: 100 слушателей", self.calls[0][2])         # the approved step 1 feeds step 3
        brief = self.h[("GET", "/api/factory/strategy/{brand}/brief.md")]("mycast", Req()).body.decode()
        self.assertIn("## 1. Цель и KPI\nЦель: 100 слушателей", brief)
        self.assertNotIn("LLM draft text", brief)                      # draft step 3 stays out until approved
        p = run(self.h[("POST", "/api/factory/strategy/{brand}/inputs")]("blackboxlab", Req({"niche": "AI-студия", "name": "Blackbox Lab"})))["passport"]
        self.assertEqual((p["name"], p["inputs"]["niche"], p["steps"]["1"]["state"]), ("Blackbox Lab", "AI-студия", "empty"))
        brands = {b["brand"] for b in self.h[("GET", "/api/factory/strategy")](Req())["brands"]}
        self.assertEqual(brands, {"mycast", "blackboxlab"})

    def test_llm_failure_is_a_readable_409_and_changes_nothing(self):
        async def broken(*a):
            raise RuntimeError("Daily provider budget would be exceeded")
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, self.store, identity=lambda r: {"role": "owner"}, draft=broken)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        before = self.store.get("mycast")["steps"]["4"]["text"]
        with self.assertRaises(HTTPException) as e:
            run(h[("POST", "/api/factory/strategy/{brand}/steps/{n}/draft")]("mycast", 4, Req({})))
        self.assertEqual(e.exception.status_code, 409)
        self.assertIn("budget", e.exception.detail)
        self.assertEqual(self.store.get("mycast")["steps"]["4"]["text"], before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
