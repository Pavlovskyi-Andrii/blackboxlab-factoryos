"""Owner 2026-11-14 (Actions budget): a restart re-dispatches only a builder preflight that GitHub never saw."""
import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-builder-"))
os.environ.setdefault("FACTORY_PASSWORD", "")

import app as factory  # noqa: E402


class BuilderRecoveryTest(unittest.TestCase):
    def test_restart_does_not_redispatch_a_preflight_that_already_ran(self):
        con = factory.db()
        now = factory.ts()
        rows = [("lost", None, None), ("failed", "failure", "111"), ("finished", "completed", "222"), ("running", "in_progress", "333")]
        for tid, wf_status, run_id in rows:
            con.execute("DELETE FROM factory_tasks WHERE id=?", (tid,))
            con.execute("INSERT INTO factory_tasks(id,title,status,created_at,updated_at) VALUES(?,?,?,?,?)",
                        (tid, tid, "in_progress", now, now))
            con.execute("UPDATE factory_tasks SET requested_at=?,workflow_status=?,workflow_run_id=? WHERE id=?",
                        (now, wf_status, run_id, tid))
        con.commit()
        con.close()
        sent = []

        async def dispatch(task):
            sent.append(task["id"])
            return True

        async def track(*a):
            return None
        with patch.object(factory, "GITHUB_TOKEN", "t"), patch.object(factory, "dispatch_builder_workflow", dispatch), \
                patch.object(factory, "track_builder_dispatch", track):
            asyncio.run(factory.resume_stale_started_tasks())
        self.assertEqual(sorted(x for x in sent if x in {r[0] for r in rows}), ["lost"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
