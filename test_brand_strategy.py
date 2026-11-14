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


    def test_an_edit_or_approval_during_a_pending_draft_always_wins(self):
        # Codex review on #357: the LLM answer must never overwrite work done while it was being written.
        store = self.store

        async def slow_draft(agent, system, user):
            store.update("mycast", lambda p: p["steps"]["6"].update(text="owner wrote this", state="approved", updated=999))
            return {"content": "late LLM text"}
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, store, identity=lambda r: {"role": "owner"}, draft=slow_draft)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        with self.assertRaises(HTTPException) as e:
            run(h[("POST", "/api/factory/strategy/{brand}/steps/{n}/draft")]("mycast", 6, Req({})))
        self.assertEqual(e.exception.status_code, 409)
        step = store.get("mycast")["steps"]["6"]
        self.assertEqual((step["text"], step["state"]), ("owner wrote this", "approved"))

    def test_unreadable_file_is_never_overwritten(self):
        path = pathlib.Path(self.tmp.name) / "s.json"
        self.store.get("mycast")
        path.write_text("{ not json", encoding="utf-8")
        for call in (lambda: self.store.get("mycast"), lambda: self.store.update("mycast", lambda p: None),
                     lambda: self.store.brands()):
            with self.assertRaises(bs.StoreUnreadable):
                call()
        self.assertEqual(path.read_text(encoding="utf-8"), "{ not json")         # untouched, nothing wiped

    def test_two_store_instances_in_parallel_lose_no_update(self):
        import threading
        path = pathlib.Path(self.tmp.name) / "s.json"
        a, b = bs.StrategyStore(path, seeds=SEEDS), bs.StrategyStore(path, seeds=SEEDS)

        def write(store, n):
            for i in range(15):
                store.update("mycast", lambda p, i=i: p["inputs"].__setitem__(f"x{n}_{i}", str(i)))
        threads = [threading.Thread(target=write, args=(st, n)) for n, st in enumerate((a, b, a, b))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        keys = [k for k in a.get("mycast")["inputs"] if k.startswith("x")]
        self.assertEqual(len(keys), 60)
        self.assertEqual([x for x in path.parent.iterdir() if x.name.endswith(".tmp")], [])

    def test_brief_with_drafts_labels_them_and_keeps_the_missing_list(self):
        self.store.update("mycast", lambda p: p["steps"]["1"].update(state="approved"))
        brief = bs.master_brief(self.store.get("mycast"), approved_only=False)
        self.assertIn("## 1. Цель и KPI\n", brief)
        self.assertIn("## 2. Распаковка и позиционирование — ЧЕРНОВИК, не утверждён", brief)
        self.assertIn("Ещё не утверждено: Распаковка", brief)
        self.assertNotIn("Цель и KPI,", brief.split("Ещё не утверждено:")[1])


    # --- stage 2: plan, matrix, jobs
    def test_seed_plan_matrix_dates_and_late_seeding(self):
        p = self.h[("GET", "/api/factory/strategy/{brand}")]("mycast", Req())["passport"]
        plan = p["plan"]
        self.assertEqual(len(plan["items"]), 20)
        self.assertEqual(plan["funnel_share"], {"TOFU": 50, "MOFU": 30, "BOFU": 20})
        self.assertEqual(plan["items"][0]["date"], "2026-11-16")
        self.assertEqual(sum(sum(v.values()) for v in plan["matrix"].values()), 20)
        path = pathlib.Path(self.tmp.name) / "late.json"
        store = bs.StrategyStore(path, seeds=SEEDS)
        store.update("mycast", lambda q: q.pop("plan"))                    # a passport saved before stage 2
        self.assertEqual(len(bs.StrategyStore(path, seeds=SEEDS).get("mycast")["plan"]["items"]), 20)

    def test_parse_plan_is_defensive(self):
        st = bs.plan_settings({"start": "2026-12-01", "per_week": 3, "weeks": 2})
        text = 'Вот план:\n[{"day": 3, "title": "A", "funnel": "mofu", "cta": "x"}, {"day": 99, "title": "B", "funnel": "zzz"},' \
               ' {"title": ""}, "junk", {"day": "x", "title": "C"}] спасибо'
        rows = bs.parse_plan(text, st)
        self.assertEqual([(r["title"], r["day"], r["funnel"]) for r in rows], [("C", 1, "TOFU"), ("A", 3, "MOFU"), ("B", 14, "TOFU")])
        self.assertEqual(bs.parse_plan("no json here", st), [])
        bad = bs.plan_settings({"start": "nope", "per_week": 99, "weeks": 0})
        self.assertEqual((bad["per_week"], bad["weeks"]), (14, 4))                 # 0 weeks -> the default 4
        self.assertRegex(bad["start"], r"^\d{4}-\d{2}-\d{2}$")

    def test_generate_plan_then_one_job_per_row(self):
        made = []

        async def draft(agent, system, user):
            self.assertIn("Master Brief", user)
            self.assertIn("ровно 6 публикаций", user)
            return {"content": '[{"day": 1, "title": "Пост 1", "pillar": "P", "funnel": "TOFU", "hook": "h", "cta": "c"},'
                               ' {"day": 2, "title": "Пост 2", "pillar": "P", "funnel": "BOFU"}]'}

        async def create_job(title, brief, fmt):
            made.append((title, brief))
            return f"job-{len(made)}"
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, self.store, identity=lambda r: {"role": "owner"}, draft=draft, create_job=create_job)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        p = run(h[("POST", "/api/factory/strategy/{brand}/plan/generate")]("mycast", Req({"start": "2026-12-01", "per_week": 3, "weeks": 2})))["passport"]
        self.assertEqual([i["title"] for i in p["plan"]["items"]], ["Пост 1", "Пост 2"])
        job = h[("POST", "/api/factory/strategy/{brand}/plan/items/{item_id}/job")]
        ids = [i["id"] for i in p["plan"]["items"]]
        first = run(job("mycast", ids[0], Req({})))
        again = run(job("mycast", ids[0], Req({})))
        self.assertEqual((first["job_id"], again["job_id"], again["existing"], len(made)), ("job-1", "job-1", True, 1))
        self.assertIn("CTA: c", made[0][1])
        self.assertIn("Tone of Voice", made[0][1])
        with self.assertRaises(HTTPException):
            run(job("mycast", "pi_0000000000", Req({})))
        p = h[("POST", "/api/factory/strategy/{brand}/plan/items/{item_id}/delete")]("mycast", ids[1], Req())["passport"]
        self.assertEqual(len(p["plan"]["items"]), 1)

        async def junk(*a):
            return {"content": "sorry, no plan"}
        app2 = fastapi.FastAPI()
        bs.install_strategy_routes(app2, self.store, identity=lambda r: {"role": "owner"}, draft=junk)
        h2 = {(next(iter(r.methods)), r.path): r.endpoint for r in app2.routes if hasattr(r, "methods")}
        with self.assertRaises(HTTPException) as e:
            run(h2[("POST", "/api/factory/strategy/{brand}/plan/generate")]("mycast", Req({})))
        self.assertEqual(e.exception.status_code, 502)
        self.assertEqual(len(self.store.get("mycast")["plan"]["items"]), 1)      # unusable answer changes nothing


    def test_job_claim_is_atomic_and_follows_the_row_not_its_position(self):
        # Codex review on #358: two clicks -> one job; deleting other rows meanwhile never misattaches it.
        store, made = self.store, []
        ids = [i["id"] for i in store.get("mycast")["plan"]["items"]]
        self.assertEqual(len(set(ids)), 20)
        h_holder = {}

        async def create_job(title, brief, fmt):
            made.append(title)
            if len(made) == 1:                        # while the first job is being created...
                with self.assertRaises(HTTPException) as e:          # ...a second click is refused
                    await h_holder["job"]("mycast", ids[3], Req({}))
                self.assertEqual(e.exception.status_code, 409)
                h_holder["del"]("mycast", ids[0], Req())              # ...and an earlier row is deleted
            return "job-A"

        async def draft(*a):
            return {"content": "[]"}
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, store, identity=lambda r: {"role": "owner"}, draft=draft, create_job=create_job)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        h_holder["job"] = h[("POST", "/api/factory/strategy/{brand}/plan/items/{item_id}/job")]
        h_holder["del"] = h[("POST", "/api/factory/strategy/{brand}/plan/items/{item_id}/delete")]
        out = run(h_holder["job"]("mycast", ids[3], Req({})))
        self.assertEqual((out["job_id"], made), ("job-A", [made[0]]))
        rows = {i["id"]: i for i in store.get("mycast")["plan"]["items"]}
        self.assertNotIn(ids[0], rows)
        self.assertEqual(rows[ids[3]]["job_id"], "job-A")
        self.assertFalse(any(r.get("job_id") for k, r in rows.items() if k != ids[3]))
        self.assertFalse(any(r.get("job_claim") for r in rows.values()))

    def test_a_pending_generation_never_replaces_changes_made_meanwhile(self):
        store = self.store
        gone = store.get("mycast")["plan"]["items"][0]["id"]
        holder = {}

        async def draft(*a):
            holder["del"]("mycast", gone, Req())            # the owner deletes a row while the plan is written
            return {"content": '[{"day": 1, "title": "new"}]'}
        app = fastapi.FastAPI()
        bs.install_strategy_routes(app, store, identity=lambda r: {"role": "owner"}, draft=draft)
        h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
        holder["del"] = h[("POST", "/api/factory/strategy/{brand}/plan/items/{item_id}/delete")]
        with self.assertRaises(HTTPException) as e:
            run(h[("POST", "/api/factory/strategy/{brand}/plan/generate")]("mycast", Req({})))
        self.assertEqual(e.exception.status_code, 409)
        self.assertEqual(len(store.get("mycast")["plan"]["items"]), 19)       # the deletion survived

    def test_settings_never_ask_for_more_rows_than_are_kept(self):
        st = bs.plan_settings({"per_week": 14, "weeks": 6})
        self.assertLessEqual(st["per_week"] * st["weeks"], bs.MAX_PLAN_ITEMS)
        self.assertEqual((st["per_week"], st["weeks"]), (14, 4))


    # --- stage 3: agents work from the Master Brief
    def test_each_agent_gets_its_part_and_drafts_are_labelled(self):
        p = self.store.get("mycast")
        self.store.update("mycast", lambda q: q["steps"]["4"].update(state="approved"))
        p = self.store.get("mycast")
        script = bs.agent_context(p, "Scriptwriter")
        self.assertIn("### Tone of Voice и правила\n", script)                 # approved: no draft label
        self.assertIn("### Оффер и CTA (черновик, ещё не утверждён — ориентир)", script)
        self.assertNotIn("### Цель и KPI", script)                               # not this agent's business
        self.assertIn("### Цель и KPI", bs.agent_context(p, "Analyst"))
        self.assertIn("CTA соответствует этапу воронки", bs.agent_context(p, "QA Agent"))
        self.assertEqual(bs.agent_context(p, "Render Agent"), "")               # no brief for pure rendering
        item = {"pillar": "P", "funnel": "BOFU", "format": "Reels", "platform": "Instagram", "cta": "Войди через Telegram"}
        self.assertIn("этап воронки BOFU", bs.agent_context(p, "Publisher", item))
        self.assertLessEqual(len(bs.agent_context(p, "Scriptwriter")), bs.AGENT_BRIEF_LIMIT)

    def test_job_to_brand_via_plan_or_link_and_into_the_real_agent_prompt(self):
        import app as factory
        from unittest.mock import patch
        it = self.store.get("mycast")["plan"]["items"][2]
        self.store.update("mycast", lambda q: next(r for r in q["plan"]["items"] if r["id"] == it["id"]).update(job_id="job-1"))
        p, row = bs.brand_for_job(self.store, "job-1")
        self.assertEqual((p["brand"], row["id"]), ("mycast", it["id"]))
        self.assertEqual(bs.brand_for_job(self.store, "nope"), (None, None))
        self.assertEqual(bs.brand_for_job(self.store, ""), (None, None))
        link = self.h[("POST", "/api/factory/strategy/{brand}/jobs/{job_id}/link")]
        link("mycast", "0123abcd-0000-4000-8000-000000000000", Req())
        self.assertEqual(bs.brand_for_job(self.store, "0123abcd-0000-4000-8000-000000000000")[0]["brand"], "mycast")
        with self.assertRaises(HTTPException):
            link("mycast", "../x", Req())
        with patch.object(factory, "STRATEGY", self.store):
            prompt = factory._apply_workflow_prompt("Scriptwriter", "BASE", "job-1")
            self.assertTrue(prompt.startswith("BASE\n"))
            self.assertIn("Master Brief бренда MyCast", prompt)
            self.assertIn(f"этап воронки {it['funnel']}", prompt)
            self.assertEqual(factory._apply_workflow_prompt("Scriptwriter", "BASE", "other-job"), "BASE")
            self.assertEqual(factory._apply_workflow_prompt("Scriptwriter", "BASE", None), "BASE")


if __name__ == "__main__":
    unittest.main(verbosity=2)
