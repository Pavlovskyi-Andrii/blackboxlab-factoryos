"""T-729 Coordination guard: duplicates and overlaps between ROADMAP, open PRs, Relay claims and handoffs."""
import json
import os
import tempfile
import unittest
from unittest import mock

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-coordination-")
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import coordination as co  # noqa: E402

ROADMAP = """# ROADMAP
## Surfer
- [x] T-726 Surfer pending list
  Owner: claude-session
- [x] T-727 Surfer DOM settle
  Owner: claude-session
  Depends: T-726
- [ ] T-729 Coordination guard
  Owner: claude
  Depends: T-726, T-999
- [ ] [HUMAN] T-725-H Connect Google
  Owner: human
"""


def pr(number, branch, title, files):
    return {"number": number, "branch": branch, "title": title, "url": "https://github.com/x/y/pull/%d" % number, "files": files}


class ReportTest(unittest.TestCase):
    def test_clean_inputs_are_clear(self):
        r = co.build_report(ROADMAP.replace(", T-999", ""), [pr(1, "claude/t-729-coord", "T-729 guard", ["coordination.py", "ROADMAP.md"])],
                            [], [], now="2026-11-23T20:00:00Z")
        self.assertEqual(r["verdict"], "clear", r["findings"])
        self.assertEqual(r["roadmap"], {"tasks": 4, "unique_ids": 4, "open": 2, "open_human": 1, "max_id": 729})
        self.assertEqual(co.next_free_id(r), "T-730")
        self.assertNotIn("_pr_files", co.public_view(r))

    def test_unknown_dependency_is_a_warning(self):
        r = co.build_report(ROADMAP, [], [], [])
        self.assertEqual(r["verdict"], "attention")
        self.assertEqual([(f["code"], f["depends"]) for f in r["findings"]], [("unknown_dependency", ["T-999"])])

    def test_duplicate_task_id_is_a_conflict(self):
        r = co.build_report(ROADMAP + "- [ ] T-727 #452 UX audit\n  Owner: claude\n", [], [], [])
        self.assertEqual(r["verdict"], "conflict")
        dup = [f for f in r["findings"] if f["code"] == "duplicate_task_id"]
        self.assertEqual(dup[0]["task_ids"], ["T-727"])
        self.assertEqual(len(dup[0]["lines"]), 2)

    def test_reused_number_in_a_pr_is_flagged(self):
        # the 2026-11-23 case: a UX branch named its new work T-727, which is a merged Surfer task on main
        r = co.build_report(ROADMAP, [pr(470, "ccr-d27f8b6b-foz7f7", "T-727 UX audit for #452", ["docs/ux/a.md"])], [], [])
        codes = {f["code"] for f in r["findings"]}
        self.assertIn("pr_names_done_task", codes)

    def test_same_task_in_two_lanes_is_a_conflict(self):
        claims = [{"ticket": "R-1", "task_id": "T-729", "lane": "chatgpt", "state": "running"}]
        r = co.build_report(ROADMAP, [pr(2, "claude/t-729", "T-729 guard", ["coordination.py"])], claims, [])
        f = [x for x in r["findings"] if x["code"] == "task_in_two_places"]
        self.assertEqual(f[0]["lanes"], ["chatgpt", "claude"])
        self.assertEqual(r["verdict"], "conflict")
        # a finished claim is history, not active work
        claims[0]["state"] = "done"
        r = co.build_report(ROADMAP, [pr(2, "claude/t-729", "T-729 guard", ["coordination.py"])], claims, [])
        self.assertNotIn("task_in_two_places", {x["code"] for x in r["findings"]})

    def test_two_prs_on_the_same_code_file_conflict_but_ledger_files_do_not(self):
        a = pr(3, "claude/a", "a", ["app.py", "ROADMAP.md", "DECISIONS.md"])
        b = pr(4, "chatgpt/b", "b", ["static/x.html", "ROADMAP.md", "DECISIONS.md"])
        r = co.build_report(ROADMAP, [a, b], [], [])
        self.assertNotIn("pr_file_overlap", {f["code"] for f in r["findings"]})
        self.assertEqual(r["shared_ledger"], {"DECISIONS.md": ["#3", "#4"], "ROADMAP.md": ["#3", "#4"]})
        b["files"].append("app.py")
        r = co.build_report(ROADMAP, [a, b], [], [])
        f = [x for x in r["findings"] if x["code"] == "pr_file_overlap"][0]
        self.assertEqual((f["prs"], f["files"]), (["#3", "#4"], ["app.py"]))

    def test_pr_inside_another_lanes_handoff_scope(self):
        h = {"handoff_id": "ho_1", "to": "chatgpt", "state": "claimed", "task_id": "T-800", "files_scope": ["film_studio/**"]}
        r = co.build_report(ROADMAP, [pr(5, "claude/x", "x", ["film_studio/render.py"])], [], [h])
        self.assertIn("pr_in_handoff_scope", {f["code"] for f in r["findings"]})
        h["state"] = "done"
        r = co.build_report(ROADMAP, [pr(5, "claude/x", "x", ["film_studio/render.py"])], [], [h])
        self.assertNotIn("pr_in_handoff_scope", {f["code"] for f in r["findings"]})

    def test_unknown_sources_never_read_as_clear(self):
        r = co.build_report(ROADMAP.replace(", T-999", ""), None, [], [])
        self.assertEqual(r["verdict"], "unknown")
        r = co.build_report(ROADMAP.replace(", T-999", ""), [pr(6, "claude/y", "y", None)], [], [])
        self.assertEqual(r["verdict"], "unknown")
        self.assertIn("pr_files_unreadable", {f["code"] for f in r["findings"]})


class AgentCheckTest(unittest.TestCase):
    def setUp(self):
        self.report = co.build_report(ROADMAP.replace(", T-999", ""),
                                      [pr(7, "chatgpt/sandbox", "Sandbox #437", ["sandbox/app.py", "ROADMAP.md"]),
                                       pr(8, "claude/t-729", "T-729 guard", ["coordination.py"])],
                                      [{"ticket": "R-2", "task_id": "T-725-H", "lane": "claude", "state": "running"}], [])

    def test_free_task_and_free_files_are_safe(self):
        out = co.agent_check(self.report, "T-800", ["film_studio/a.py", "ROADMAP.md"], "claude")
        self.assertEqual(out["safe_to_start"], "yes", out)
        self.assertEqual(out["next_free_id"], "T-730")

    def test_task_with_an_open_pr_is_not_safe(self):
        out = co.agent_check(self.report, "t-729", [], "chatgpt")
        self.assertEqual(out["safe_to_start"], "no")
        self.assertEqual(out["reasons"][0]["code"], "task_already_active")
        self.assertEqual(out["roadmap"]["owner"], "claude")

    def test_files_in_an_open_pr_are_not_safe(self):
        out = co.agent_check(self.report, "", ["sandbox/app.py"], "claude")
        self.assertEqual([r["code"] for r in out["reasons"]], ["files_in_open_pr"])
        out = co.agent_check(self.report, "", ["sandbox"], "claude")      # a directory covers the PR's files
        self.assertEqual(out["safe_to_start"], "no")

    def test_unknown_github_is_unknown_not_yes(self):
        report = co.build_report(ROADMAP, None, [], [])
        self.assertEqual(co.agent_check(report, "T-800", ["x.py"])["safe_to_start"], "unknown")

    def test_bad_task_id_is_refused(self):
        with self.assertRaises(ValueError):
            co.agent_check(self.report, "rm -rf", [])


class AppTest(unittest.TestCase):
    """The real app: owner-only API, the MCP tool, and GitHub failures shown as unknown."""

    @classmethod
    def setUpClass(cls):
        from test_agent_workspace import LANE_TOKENS, SHARED, mcp_call  # sets the MCP env before app import
        import app as factory
        cls.factory, cls.lane_tokens, cls.shared, cls.mcp_call = factory, LANE_TOKENS, SHARED, staticmethod(mcp_call)

    def fake_github(self, pulls, files):
        def fetch(path):
            if path.startswith("/pulls?"):
                return pulls
            number = int(path.split("/")[2])
            if files.get(number) == "boom":
                raise OSError("github down")
            return [{"filename": f} for f in files.get(number, [])]
        return fetch

    def test_report_reads_open_prs_and_their_files(self):
        fetch = self.fake_github([{"number": 11, "title": "T-999 x", "head": {"ref": "claude/x"}, "html_url": "u"},
                                  {"number": 12, "title": "y", "head": {"ref": "gemini/y"}, "html_url": "u"}],
                                 {11: ["app.py"], 12: ["app.py", "ROADMAP.md"]})
        report = self.factory.get_coordination_report(fetch=fetch)
        self.assertIn("pr_file_overlap", {f["code"] for f in report["findings"]})
        self.assertTrue(report["next_free_id"].startswith("T-"))
        # the real ROADMAP has no duplicate IDs
        self.assertNotIn("duplicate_task_id", {f["code"] for f in report["findings"]})

    def test_unreadable_pr_files_are_unknown(self):
        fetch = self.fake_github([{"number": 13, "title": "z", "head": {"ref": "claude/z"}}], {13: "boom"})
        report = self.factory.get_coordination_report(fetch=fetch)
        self.assertIn("pr_files_unreadable", {f["code"] for f in report["findings"]})
        self.assertNotEqual(report["verdict"], "clear")

    def test_no_read_token_means_github_unknown(self):
        with mock.patch.object(self.factory, "_github_read_token", return_value=""):
            self.assertIsNone(self.factory._coordination_open_prs())

    def test_api_is_owner_only(self):
        from fastapi import HTTPException
        from starlette.requests import Request
        req = Request({"type": "http", "method": "GET", "path": "/api/factory/coordination", "query_string": b"", "headers": []})
        with mock.patch.object(self.factory, "request_identity", return_value={"role": "viewer"}):
            with self.assertRaises(HTTPException) as ctx:
                self.factory.factory_coordination(req)
            self.assertEqual(ctx.exception.status_code, 403)
        with mock.patch.object(self.factory, "request_identity", return_value={"role": "owner"}), \
                mock.patch.object(self.factory, "_coordination_open_prs", return_value=[]):
            body = self.factory.factory_coordination(req, refresh=1)
        self.assertIn(body["verdict"], ("clear", "attention"))
        self.assertFalse([k for k in body if k.startswith("_")])

    def test_mcp_tool_is_listed_and_answers(self):
        _, listed = self.mcp_call(self.factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.shared)
        self.assertIn("coordination_check", {t["name"] for t in listed["result"]["tools"]})
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "coordination_check", "arguments": {"task_id": "T-726", "files": ["coordination.py"]}}}
        with mock.patch.object(self.factory, "_coordination_open_prs", return_value=[]):
            self.factory._COORDINATION_CACHE["at"] = 0
            _, out = self.mcp_call(self.factory, call, self.lane_tokens["chatgpt"])
        self.assertFalse(out["result"].get("isError"), out)
        body = json.loads(out["result"]["content"][0]["text"])
        self.assertEqual(body["roadmap"]["done"], True)
        self.assertIn(body["safe_to_start"], ("yes", "no"))
        bad = {**call, "params": {"name": "coordination_check", "arguments": {"task_id": "nope"}}}
        _, out = self.mcp_call(self.factory, bad, self.lane_tokens["chatgpt"])
        self.assertTrue(out["result"].get("isError"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
