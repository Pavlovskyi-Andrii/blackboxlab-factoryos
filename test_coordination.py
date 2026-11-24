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


class DependencyTest(unittest.TestCase):
    def test_suffixed_dependency_must_exist_exactly(self):
        text = ROADMAP.replace(", T-999", ", T-729-BOG")
        bad = [f for f in co.build_report(text, [], [], [])["findings"] if f["code"] == "unknown_dependency"]
        self.assertEqual(bad[0]["depends"], ["T-729-BOG"])

    def test_group_number_resolves_to_its_suffixed_tasks(self):
        text = ROADMAP.replace(", T-999", ", T-725")   # only T-725-H exists: T-725 names the group
        self.assertNotIn("unknown_dependency", {f["code"] for f in co.build_report(text, [], [], [])["findings"]})

    def test_done_rows_are_checked_too(self):
        text = ROADMAP.replace(", T-999", "").replace("  Depends: T-726\n", "  Depends: T-555\n")
        bad = [f for f in co.build_report(text, [], [], [])["findings"] if f["code"] == "unknown_dependency"]
        self.assertEqual((bad[0]["task_ids"], bad[0]["depends"]), (["T-727"], ["T-555"]))


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

    def test_truncated_pr_list_is_unknown(self):
        report = co.build_report(ROADMAP.replace(", T-999", ""), [], [], [], prs_truncated=True)
        self.assertEqual(report["verdict"], "unknown")
        self.assertIn("github_truncated", {f["code"] for f in report["findings"]})
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
        """GitHub double with real paging (per_page / page), so limits are exercised the way GitHub applies them."""
        from urllib.parse import parse_qs, urlparse

        def fetch(path):
            q = parse_qs(urlparse(path).query)
            per, page = int(q.get("per_page", ["30"])[0]), int(q.get("page", ["1"])[0])
            if path.startswith("/pulls?"):
                rows = pulls
            else:
                number = int(path.split("/")[2])
                if files.get(number) == "boom":
                    raise OSError("github down")
                rows = [{"filename": f} for f in files.get(number, [])]
            return rows[(page - 1) * per: page * per]
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

    def test_conflict_in_pr_26_and_on_file_101_is_found(self):
        pulls = [{"number": n, "title": "p%d" % n, "head": {"ref": "gemini/p%d" % n}} for n in range(1, 32)]
        files = {n: ["docs/p%d.md" % n] for n in range(1, 32)}
        files[26] = ["docs/f%03d.md" % i for i in range(100)] + ["app.py"]   # app.py is file 101 of PR 26
        files[3] = ["app.py"]
        report = self.factory.get_coordination_report(fetch=self.fake_github(pulls, files))
        f = [x for x in report["findings"] if x["code"] == "pr_file_overlap"]
        self.assertEqual((sorted(f[0]["prs"]), f[0]["files"]), (["#26", "#3"], ["app.py"]))
        self.assertTrue(report["sources"]["github_complete"])

    def test_more_prs_than_the_page_limit_are_unknown(self):
        pulls = [{"number": n, "title": "p", "head": {"ref": "claude/p"}} for n in range(1, 302)]
        with mock.patch.object(self.factory, "COORDINATION_MAX_PR_PAGES", 3):
            report = self.factory.get_coordination_report(fetch=self.fake_github(pulls, {}))
        self.assertEqual(report["verdict"], "unknown")
        self.assertIn("github_truncated", {f["code"] for f in report["findings"]})

    def test_too_many_files_in_one_pr_are_unknown(self):
        pulls = [{"number": 9, "title": "big", "head": {"ref": "claude/big"}}]
        with mock.patch.object(self.factory, "COORDINATION_MAX_FILE_PAGES", 2):
            report = self.factory.get_coordination_report(fetch=self.fake_github(pulls, {9: ["f%d" % i for i in range(250)]}))
        self.assertIn("pr_files_unreadable", {f["code"] for f in report["findings"]})

    def test_active_claim_beyond_the_newest_500_tickets_is_seen(self):
        store = self.factory.RELAY_STORE
        with store.lock:
            state = store._load_unlocked()
            saved = list(state["tickets"])
            old = {"id": "R-OLD1", "title": "T-777 old claim", "status": "working", "created_at": "2020-01-01T00:00:00+00:00",
                   "updated_at": "2020-01-01T00:00:00+00:00", "source": {"channel": "roadmap", "task_id": "T-777", "owner": "gemini"},
                   "execution": {"state": "running", "owner": "gemini", "claimed_at": "2099-01-01T00:00:00+00:00",
                                 "last_seen_at": "2099-01-01T00:00:00+00:00"}}
            filler = [{"id": "R-F%04d" % i, "title": "f", "status": "done", "created_at": "2026-11-23T00:00:00+00:00",
                       "updated_at": "2026-11-23T00:00:%02d+00:00" % (i % 60), "source": {"channel": "telegram"}} for i in range(600)]
            state["tickets"] = filler + [old]
            store._save_unlocked(state)
        try:
            claims = self.factory._coordination_claims()
            self.assertEqual([c["task_id"] for c in claims], ["T-777"])
        finally:
            with store.lock:
                state = store._load_unlocked()
                state["tickets"] = saved
                store._save_unlocked(state)

    def test_mcp_lane_comes_from_the_token(self):
        call = {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "coordination_check", "arguments": {"task_id": "T-800", "lane": "claude"}}}
        with mock.patch.object(self.factory, "_coordination_open_prs", return_value=([], False)):
            _, out = self.mcp_call(self.factory, call, self.lane_tokens["chatgpt"])
            self.assertTrue(out["result"].get("isError"))
            self.assertIn("lane", out["result"]["content"][0]["text"])
            _, out = self.mcp_call(self.factory, call, self.lane_tokens["claude"])
            self.assertFalse(out["result"].get("isError"), out)
            self.assertEqual(json.loads(out["result"]["content"][0]["text"])["lane"], "claude")
            _, out = self.mcp_call(self.factory, call, self.shared)        # shared token: no lane proven
            body = json.loads(out["result"]["content"][0]["text"])
            self.assertIsNone(body["lane"])
            self.assertIn("lane_note", body)

    def test_mcp_check_reads_github_fresh_inside_the_page_cache_window(self):
        reads = iter([([], False), ([{"number": 50, "title": "new", "branch": "gemini/x", "url": "", "files": ["film_studio/a.py"]}], False)])
        with mock.patch.object(self.factory, "_coordination_open_prs", side_effect=lambda fetch=None: next(reads)):
            self.factory.get_coordination_report(refresh=True)          # owner page snapshot: no PRs
            call = {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "coordination_check", "arguments": {"files": ["film_studio/a.py"]}}}
            _, out = self.mcp_call(self.factory, call, self.lane_tokens["claude"])
        body = json.loads(out["result"]["content"][0]["text"])
        self.assertEqual(body["safe_to_start"], "no", body)

    def test_no_read_token_means_github_unknown(self):
        with mock.patch.object(self.factory, "_github_read_token", return_value=""):
            self.assertEqual(self.factory._coordination_open_prs(), (None, False))

    def test_api_is_owner_only(self):
        from fastapi import HTTPException
        from starlette.requests import Request
        req = Request({"type": "http", "method": "GET", "path": "/api/factory/coordination", "query_string": b"", "headers": []})
        with mock.patch.object(self.factory, "request_identity", return_value={"role": "viewer"}):
            with self.assertRaises(HTTPException) as ctx:
                self.factory.factory_coordination(req)
            self.assertEqual(ctx.exception.status_code, 403)
        with mock.patch.object(self.factory, "request_identity", return_value={"role": "owner"}), \
                mock.patch.object(self.factory, "_coordination_open_prs", return_value=([], False)):
            body = self.factory.factory_coordination(req, refresh=1)
        self.assertIn(body["verdict"], ("clear", "attention"))
        self.assertFalse([k for k in body if k.startswith("_")])

    def test_mcp_tool_is_listed_and_answers(self):
        _, listed = self.mcp_call(self.factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, self.shared)
        self.assertIn("coordination_check", {t["name"] for t in listed["result"]["tools"]})
        call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "coordination_check", "arguments": {"task_id": "T-726", "files": ["coordination.py"]}}}
        with mock.patch.object(self.factory, "_coordination_open_prs", return_value=([], False)):
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
