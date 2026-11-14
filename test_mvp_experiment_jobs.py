"""T-610 A/B Tester S3 against the real app: one Content Factory draft job per branch.

Proves with the real `create_job`, jobs table and publish gate (S0 review §S3 DONE, §6.2): concurrent owner clicks
make exactly one inbox job per branch, a second click returns the same job, A's job never appears under B, no
publishing_queue or approval row is written, no provider/LLM/network function or job run is called, and an MVP
preview approval cannot satisfy the job publish gate.
"""
import asyncio
import os
import tempfile
import threading
import unittest

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-t610-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
import app  # noqa: E402
from mvp_experiments import Experiments  # noqa: E402

PID, EXP = "mycast", "mc-exp-t610"
PATH = "/api/mvp-factory/{project_id}/experiments/{exp_id}/branches/{branch_id}/content-job"


class Req:
    cookies, headers = {}, {}

    async def json(self):
        return {}


class ContentJobAppTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.calls = []
        cls.saved = {}
        for name in ("_content_brain_llm", "_gemini_text", "run_job"):
            cls.saved[name] = getattr(app, name)
            setattr(app, name, cls._forbid(name))
        cls.saved["urlopen"] = app.urlrequest.urlopen
        app.urlrequest.urlopen = cls._forbid("urlopen")
        ex = Experiments(app.MVP_REGISTRY)
        ex.create(PID, {"id": EXP, "mode": "SEGMENT_COMPARISON", "hypothesis": "Two audiences, two positionings.",
                        "branches": [{"id": "a", "label": "Business focus", "persona": "entrepreneurs"},
                                     {"id": "b", "label": "Personal goals", "persona": "personal_goals"}]},
                  actor_role="owner")
        for b in "ab":
            ex.save_draft(PID, EXP, b, {"headline": f"Branch {b.upper()} headline", "cta": "Listen to a sample"},
                          actor_role="owner")
        cls.ex = ex
        cls.fn = staticmethod(next(r.endpoint for r in app.app.routes if getattr(r, "path", "") == PATH))

    @classmethod
    def tearDownClass(cls):
        for name in ("_content_brain_llm", "_gemini_text", "run_job"):
            setattr(app, name, cls.saved[name])
        app.urlrequest.urlopen = cls.saved["urlopen"]

    @classmethod
    def _forbid(cls, name):
        def fn(*a, **kw):
            cls.calls.append(name)
            raise AssertionError(f"S3 must not call {name}")
        return fn

    @staticmethod
    def count(table, where="", args=()):
        con = app.db()
        try:
            return con.execute(f"SELECT COUNT(*) FROM {table} {where}", args).fetchone()[0]
        finally:
            con.close()

    @staticmethod
    def branches():
        with app.MVP_REGISTRY._lock:
            return app.MVP_REGISTRY._load()["projects"][PID]["experiments"][EXP]["branches"]

    def click(self, branch):
        out = asyncio.run(self.fn(project_id=PID, exp_id=EXP, branch_id=branch, request=Req()))
        return (out.status_code, out.body) if hasattr(out, "status_code") else (200, out)

    def test_one_inbox_job_per_branch_no_publish_no_provider(self):
        jobs0, pub0, appr0 = self.count("jobs"), self.count("publishing_queue"), self.count("approval_decisions")
        results = []
        threads = [threading.Thread(target=lambda b=b: results.append((b, self.click(b)))) for b in "abababab"]
        [t.start() for t in threads]
        [t.join() for t in threads]
        branches = self.branches()
        ids = {b["id"]: b["content_job_id"] for b in branches}
        self.assertTrue(ids["a"] and ids["b"] and ids["a"] != ids["b"])
        for b, (status, out) in results:
            if status == 200:
                self.assertEqual(out["job_id"], ids[b])     # a job for A never appears under B
        self.assertEqual(self.count("jobs"), jobs0 + 2)
        self.assertEqual(self.click("a")[1], {"job_id": ids["a"], "existing": True, "branch": "a"})
        self.assertEqual(self.click("b")[1]["job_id"], ids["b"])
        self.assertEqual(self.count("jobs"), jobs0 + 2)
        for b in "ab":
            con = app.db()
            row = con.execute("SELECT * FROM jobs WHERE id=?", (ids[b],)).fetchone()
            con.close()
            self.assertEqual((row["stage"], row["status"]), ("inbox", "idle"))
            self.assertIn(f"Branch {b.upper()} headline", row["brief"])
            self.assertNotIn(f"Branch {'ba'['ab'.index(b)].upper()} headline", row["brief"])
            self.assertIn("DRAFT ONLY", row["brief"])
        self.assertEqual(self.count("publishing_queue"), pub0)
        self.assertEqual(self.count("approval_decisions"), appr0)
        self.assertEqual(self.calls, [])
        # An MVP preview approval is a registry event, never a job approval: the publish gate stays closed.
        self.ex.approve_preview(PID, EXP, "a", 1, actor_role="owner")
        preview = self.branches()[0]["approval"]["preview"]
        reason = app._publish_approval_gate({"job_id": ids["a"], "approval_decision_id": preview["event_id"]})
        self.assertTrue(reason)
        self.assertTrue(app._publish_approval_gate({"job_id": ids["a"]}))
        self.assertEqual(self.count("approval_decisions"), appr0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
