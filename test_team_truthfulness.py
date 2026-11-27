"""#242 Team Tasks truthfulness matrix: source facts (GitHub / EC2 snapshot / lane heartbeat) → API label.

Offline and deterministic: no network, GitHub reads are fake fetchers, the snapshot file lives in a temp dir.
Each case asserts that missing, stale or partial facts surface as unknown/unavailable, never as a confident
"fresh", "passed", "working" or "0 tasks". Complements test_team_tasks.py (which covers the happy paths).
"""
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-team-truth-"))

import app as factory  # noqa: E402
from team_tasks import PROGRESS, _ci_summary, build_team_tasks, compact_github, read_github  # noqa: E402

NOW = 1_800_000_000.0  # fixed clock for build_team_tasks


def issue(n, owner, state="open", labels=(), updated="2026-11-04T08:00:00Z", body=""):
    return {"number": n, "title": f"Task {n}", "body": f"Owner: {owner}\n{body}", "state": state,
            "html_url": f"https://g/i/{n}", "labels": [{"name": x} for x in labels], "updated_at": updated,
            "created_at": "2026-11-01T00:00:00Z", "closed_at": None}


def pr(n, branch, body="", draft=False, state="open", merged=None, sha=None, updated="2026-11-04T09:00:00Z"):
    return {"number": n, "title": f"PR {n}", "body": body, "draft": draft, "state": state, "merged_at": merged,
            "head": {"ref": branch, "sha": sha or f"sha{n}"}, "html_url": f"https://g/p/{n}", "updated_at": updated,
            "created_at": "2026-11-03T00:00:00Z"}


def http_error(code):
    def fetch(path):
        err = Exception("GitHub said no")
        err.code = code
        raise err
    return fetch


def all_tasks(board):
    return [t for a in board["agents"].values() for t in a["tasks"]]


class AppSnapshotHarness(unittest.TestCase):
    """Runs the real get_team_tasks / _intake_issues_from_ec2_snapshot with a temp snapshot file and Render's read
    forced to HTTP 403 (the production failure of 2026-11-04). Lane board, roadmap and owner desk are pinned."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="team-truth-snap-"))
        self.path = self.dir / "team_tasks_github.json"
        forbidden = {"available": False, "error": "HTTP 403", "issues": [], "pulls": [], "ci": {}}
        self.patches = [patch.object(factory, "_TEAM_SNAPSHOT_PATH", self.path),
                        patch.object(factory, "read_github", lambda fetch, **kw: dict(forbidden)),
                        patch.object(factory, "get_lane_board", lambda: {"lanes": {}}),
                        patch.object(factory, "_parse_roadmap_tasks", lambda: []),
                        patch.object(factory, "_owner_decision_cards", lambda roadmap: [])]
        for p in self.patches:
            p.start()
        factory._TEAM_TASKS_CACHE.invalidate()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        factory._TEAM_TASKS_CACHE.invalidate()

    def write_snapshot(self, age_seconds, github=None):
        received = time.time() - age_seconds
        github = github or compact_github({"available": True, "issues": [issue(5, "Gemini"), issue(6, "Claude")],
                                           "pulls": [], "ci": {}})
        fetched_at = "2020-01-01T00:00:00+00:00"  # a recognisable, clearly-old provenance stamp
        self.path.write_text(json.dumps({"received": received, "fetched_at": fetched_at, "github": github}))
        return fetched_at


class StaleSnapshotTest(AppSnapshotHarness):
    """Case 1: an old EC2 snapshot past its TTL is stale/unknown, never served as fresh facts."""

    def test_intake_rejects_snapshot_past_ttl(self):
        self.write_snapshot(factory.INTAKE_SNAPSHOT_MAX_AGE + 60)
        data, state = factory._intake_issues_from_ec2_snapshot()
        self.assertIsNone(data)
        self.assertEqual(state, "stale")
        self.write_snapshot(30)
        data, state = factory._intake_issues_from_ec2_snapshot()
        self.assertEqual(state, "fresh")
        self.assertEqual([i["number"] for i in data["issues"]], [5, 6])

    def test_intake_rejects_snapshot_from_the_future(self):
        self.write_snapshot(-(factory.INTAKE_SNAPSHOT_CLOCK_SKEW + 120))
        self.assertEqual(factory._intake_issues_from_ec2_snapshot(), (None, "stale"))

    def test_intake_missing_and_malformed_are_not_fresh(self):
        self.assertEqual(factory._intake_issues_from_ec2_snapshot(), (None, "missing"))
        self.path.write_text(json.dumps({"received": "yesterday", "github": {}}))
        self.assertEqual(factory._intake_issues_from_ec2_snapshot(), (None, "malformed"))
        self.path.write_text(json.dumps({"received": time.time(), "github": {"issues": "nope"}}))
        self.assertEqual(factory._intake_issues_from_ec2_snapshot(), (None, "malformed"))

    def test_board_drops_snapshot_older_than_an_hour(self):
        self.write_snapshot(2 * 3600)
        board = factory.get_team_tasks(refresh=True)
        self.assertFalse(board["github_available"])          # unknown, not the old snapshot dressed as fresh
        self.assertEqual(board["github_source"], "render")
        self.assertEqual(board["github_error"], "HTTP 403")
        self.assertEqual(all_tasks(board), [])
        self.assertFalse(board["queue_keeper"]["available"])
        self.assertIsNone(board["queue_keeper"]["counts"])

    def test_board_from_recent_snapshot_keeps_its_own_timestamp(self):
        fetched_at = self.write_snapshot(20 * 60)            # usable for the board, already stale for intake
        board = factory.get_team_tasks(refresh=True)
        self.assertTrue(board["github_available"])
        self.assertEqual(board["github_source"], "ec2")      # provenance: the EC2 snapshot, not Render's read
        self.assertEqual(board["synced_at"], fetched_at)     # the snapshot's age, not "synced just now"
        self.assertEqual(factory._intake_issues_from_ec2_snapshot(), (None, "stale"))


class UnavailableIsNotEmptyTest(AppSnapshotHarness):
    """Cases 2 and 5: GitHub 403 / unavailable read is "unknown"; zero work is a different, explicit label."""

    def test_403_without_snapshot_is_unknown_not_zero_tasks(self):
        board = factory.get_team_tasks(refresh=True)
        self.assertFalse(board["github_available"])
        self.assertEqual(board["github_error"], "HTTP 403")
        self.assertFalse(board["queue_keeper"]["available"])
        self.assertIsNone(board["queue_keeper"]["counts"])   # not {"ready": 0, ...}
        self.assertIsNone(board["queue_keeper"]["shortfall"])
        self.assertEqual(board["queue_keeper"]["escalation"], "")  # no "0 of 10 ready" claim from a failed read

    def test_route_reports_unavailable_through_the_api(self):
        from test_worker_token_binding import asgi_get
        with patch.object(factory, "FACTORY_PASSWORD", ""):  # open mode = owner identity
            status, body = asgi_get("/api/factory/team-tasks")  # cache invalidated in setUp
        self.assertEqual(status, 200, body)
        out = json.loads(body)
        self.assertFalse(out["github_available"])
        self.assertEqual(out["github_error"], "HTTP 403")
        self.assertIsNone(out["queue_keeper"]["counts"])

    def test_read_github_errors_are_unavailable(self):
        for code, label in ((403, "HTTP 403"), (404, "HTTP 404"), (502, "HTTP 502"), (None, "GitHub unavailable")):
            g = read_github(http_error(code))
            self.assertEqual((g["available"], g["error"]), (False, label))
        self.assertFalse(read_github(lambda path: {"message": "Bad credentials"})["available"])  # non-list body

    def test_zero_work_and_unknown_are_distinguishable(self):
        empty = build_team_tasks({"available": True, "issues": [], "pulls": [], "ci": {}}, roadmap=[], now=NOW)
        unknown = build_team_tasks(read_github(http_error(403)), roadmap=[], now=NOW)
        self.assertTrue(empty["github_available"])
        self.assertEqual(empty["github_error"], "")
        self.assertEqual(empty["queue_keeper"]["counts"], {"open": 0, "ready": 0, "blocked": 0, "in_review": 0})
        self.assertFalse(unknown["github_available"])
        self.assertEqual(unknown["github_error"], "HTTP 403")
        self.assertIsNone(unknown["queue_keeper"]["counts"])
        # Comparing the two payloads alone must tell them apart (the page keys its "bad" banner off these fields).
        keys = ("github_available", "github_error")
        self.assertNotEqual([empty[k] for k in keys], [unknown[k] for k in keys])
        self.assertNotEqual(empty["queue_keeper"], unknown["queue_keeper"])


class PartialCiTest(unittest.TestCase):
    """Case 3: CI facts that are missing or partial for a PR head are unknown, never passed."""

    def test_open_pr_without_ci_entry_is_unknown(self):
        github = {"available": True, "issues": [issue(1, "Claude")], "pulls": [pr(10, "claude/issue-1-x")], "ci": {}}
        task = build_team_tasks(github, roadmap=[], now=NOW)["agents"]["claude"]["tasks"][0]
        self.assertEqual(task["pr"]["ci"], "unknown")
        self.assertEqual(task["reason"], "ci_running")       # not "awaiting_review" (which implies CI is green)
        self.assertNotEqual(task["status"], "done")

    def test_check_runs_read_failure_is_unknown(self):
        def fetch(path):
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [pr(1, "claude/a", sha="s1")]
            raise http_error(403)(path)
        self.assertEqual(read_github(fetch)["ci"], {"s1": {"state": "unknown", "failed": ""}})

    def check_runs_fetch(self, payload):
        def fetch(path):
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [pr(1, "claude/a", sha="s1")]
            return payload
        return fetch

    def test_truncated_check_runs_are_not_passed(self):
        # 50 green runs on page 1, but GitHub says 51 exist: the unseen one may be red.
        runs = [{"name": f"c{i}", "status": "completed", "conclusion": "success"} for i in range(50)]
        ci = read_github(self.check_runs_fetch({"total_count": 51, "check_runs": runs}))["ci"]
        self.assertEqual(ci["s1"]["state"], "unknown")
        # A failure already seen on page 1 stays a failure; a complete page stays passed.
        red = runs[:49] + [{"name": "smoke", "status": "completed", "conclusion": "failure"}]
        self.assertEqual(read_github(self.check_runs_fetch({"total_count": 51, "check_runs": red}))["ci"]["s1"],
                         {"state": "failed", "failed": "smoke"})
        self.assertEqual(read_github(self.check_runs_fetch({"total_count": 50, "check_runs": runs}))["ci"]["s1"]["state"], "passed")

    def test_unexpected_check_runs_body_is_unknown(self):
        for payload in ({"message": "Resource not accessible by integration"}, ["not", "a", "dict"], None,
                        {"check_runs": "x"}):
            ci = read_github(self.check_runs_fetch(payload))["ci"]
            self.assertEqual(ci["s1"]["state"], "unknown", payload)

    def test_stale_check_run_is_not_passed(self):
        stale = [{"name": "ok", "status": "completed", "conclusion": "success"},
                 {"name": "old", "status": "completed", "conclusion": "stale"}]
        self.assertNotEqual(_ci_summary(stale)["state"], "passed")

    def test_no_check_runs_is_none_not_passed(self):
        self.assertEqual(_ci_summary([])["state"], "none")
        github = {"available": True, "issues": [], "pulls": [pr(10, "claude/x")], "ci": {"sha10": {"state": "none", "failed": ""}}}
        task = build_team_tasks(github, roadmap=[], now=NOW)["agents"]["claude"]["tasks"][0]
        self.assertEqual(task["pr"]["ci"], "none")
        self.assertNotEqual(task["pr"]["ci"], "passed")


class HeartbeatIsNotWorkTest(unittest.TestCase):
    """Case 4: an online heartbeat without a claimed task (PR) is not shown as working."""

    def test_online_without_task_has_no_current_work(self):
        github = {"available": True, "issues": [issue(1, "Claude")], "pulls": [], "ci": {}}
        lanes = {"claude": {"state": "working", "heartbeat_age_seconds": 5},
                 "chatgpt": {"state": "idle", "heartbeat_age_seconds": 30}}
        board = build_team_tasks(github, roadmap=[], lanes=lanes, now=NOW)
        claude = board["agents"]["claude"]
        self.assertTrue(claude["online"])
        self.assertIsNone(claude["current"])                 # a heartbeat alone is not a task in progress
        self.assertEqual(claude["counts"]["in_progress"], 0)
        self.assertEqual(claude["next"]["id"], "#1")         # the open issue is next, still queued
        self.assertEqual(claude["next"]["status"], "queued")
        chatgpt = board["agents"]["chatgpt"]
        self.assertTrue(chatgpt["online"])
        self.assertIsNone(chatgpt["current"])
        self.assertEqual(sum(chatgpt["counts"].values()), 0)
        self.assertEqual(board["totals"]["in_progress"], 0)

    def test_online_is_unknown_without_heartbeat(self):
        lanes = {"claude": {"state": "working"}, "gemini": {"state": "offline", "heartbeat_age_seconds": 9000}}
        board = build_team_tasks({"available": True, "issues": [], "pulls": [], "ci": {}}, roadmap=[], lanes=lanes, now=NOW)
        self.assertIsNone(board["agents"]["claude"]["online"])      # "working" claim without a heartbeat = unknown
        self.assertIsNone(board["agents"]["claude"]["heartbeat_age_seconds"])
        self.assertIs(board["agents"]["gemini"]["online"], False)
        self.assertEqual(board["agents"]["gemini"]["heartbeat_age_seconds"], 9000)  # provenance kept as given
        self.assertIsNone(board["agents"]["owner"]["online"])


class RenderDeploySkew(unittest.TestCase):
    """Case 6 / FO-05: Render deployed SHA vs main, and honest stages of a finished task.

    The deployed commit (RENDER_GIT_COMMIT) is placed on main as the merged PR whose merge commit it is. A task is
    "deployed" only when its PR merged before that point; a local run or an unknown commit makes no deploy claim."""

    def board(self, deployed_sha="", verified=frozenset(), ci=None):
        pulls = [dict(pr(1, "claude/a", state="closed", merged="2026-11-04T10:00:00Z", sha="h1"), merge_commit_sha="m1aaaaaaaa"),
                 dict(pr(2, "claude/b", state="closed", merged="2026-11-04T12:00:00Z", sha="h2"), merge_commit_sha="m2bbbbbbbb"),
                 dict(pr(3, "claude/c", state="closed", merged="2026-11-04T14:00:00Z", sha="h3"), merge_commit_sha="m3cccccccc")]
        github = {"available": True, "issues": [issue(9, "Claude", state="closed")], "pulls": pulls,
                  "ci": ci if ci is not None else {"h1": {"state": "passed", "failed": ""}, "h2": {"state": "failed", "failed": "smoke"}}}
        b = build_team_tasks(github, roadmap=[], now=NOW, deployed_sha=deployed_sha, verified_prs=verified)
        return b, {t["number"]: t.get("delivery") for t in b["agents"]["claude"]["tasks"]}

    def test_board_makes_no_deploy_claim_without_a_known_commit(self):
        for sha in ("", "local", "ffffffffffff"):                        # local run / commit not among the PRs read
            b, d = self.board(sha)
            self.assertFalse(b["deploy"]["known"])
            self.assertTrue(all(x is None or x["deployed"] is None for x in d.values()), d)
            self.assertNotIn("deployed", {x["label"] for x in d.values() if x})

    def test_deployed_sha_mismatch_is_reported(self):
        b, d = self.board("m2bbbbbbbb1234")                              # Render runs PR #2's merge commit
        self.assertEqual((b["deploy"]["known"], b["deploy"]["pr"]), (True, 2))
        self.assertEqual(d[1]["label"], "deployed")                      # merged before it: on production
        self.assertTrue(d[2]["deployed"] and d[2]["tested"] == "fail")   # on production although its CI failed…
        self.assertEqual(d[2]["label"], "failed")                        # …so the label says so, not "deployed"
        self.assertEqual((d[3]["label"], d[3]["deployed"]), ("merged", False))   # merged after: not deployed yet
        self.assertEqual(d[3]["tested"], "unknown")                      # no CI result read: never "passed"

    def test_labels_never_round_up(self):
        b, d = self.board("", verified=frozenset({3}))
        self.assertEqual((d[1]["label"], d[2]["label"], d[3]["label"]), ("tested", "failed", "verified"))
        self.assertEqual(d[9]["label"], "closed_no_pr")                  # closed issue without a merged PR
        self.assertFalse(d[9]["merged"])
        open_task = build_team_tasks({"available": True, "issues": [issue(5, "Claude")], "pulls": [], "ci": {}},
                                     roadmap=[], now=NOW)["agents"]["claude"]["tasks"][0]
        self.assertNotIn("delivery", open_task)                          # only finished tasks get stages

    def test_compact_snapshot_keeps_the_merge_commit(self):
        from team_tasks import compact_github
        snap = compact_github({"available": True, "issues": [], "pulls": [dict(pr(1, "claude/a"), merge_commit_sha="abc123def")]})
        self.assertEqual(snap["pulls"][0]["merge_commit_sha"], "abc123def")


class StaleQueuedTest(unittest.TestCase):
    """Case 7: a queued task stays queued (not_started, 0%) however old it is; nothing promotes it."""

    def test_old_queued_issue_stays_queued(self):
        github = {"available": True,
                  "issues": [issue(1, "ChatGPT", updated="2025-01-01T00:00:00Z"),
                             issue(2, "ChatGPT", updated="2025-01-01T00:00:00Z")],
                  "pulls": [pr(9, "chatgpt/issue-2-x", state="closed", updated="2025-01-02T00:00:00Z")],  # abandoned PR
                  "ci": {}}
        board = build_team_tasks(github, roadmap=[], lanes={"chatgpt": {"state": "working", "heartbeat_age_seconds": 1}}, now=NOW)
        tasks = {t["id"]: t for t in board["agents"]["chatgpt"]["tasks"]}
        for tid in ("#1", "#2"):
            self.assertEqual((tasks[tid]["status"], tasks[tid]["reason"], tasks[tid]["progress"]), ("queued", "not_started", 0))
            self.assertEqual(tasks[tid]["updated_at"], "2025-01-01T00:00:00Z")  # its real age is exposed, not refreshed
        self.assertEqual(tasks["#2"]["pr"]["state"], "closed")  # the abandoned PR is shown as closed, not as active work
        self.assertIsNone(board["agents"]["chatgpt"]["current"])
        self.assertEqual(board["agents"]["chatgpt"]["done_7d"], 0)
        self.assertEqual(board["agents"]["chatgpt"]["last_activity_at"], "2025-01-01T00:00:00+00:00")


class ProvenanceAndProgressTest(unittest.TestCase):
    """Source timestamps/provenance present; progress is a fixed stage value, never a measured percentage."""

    def board(self):
        github = {"available": True, "fetched_at": "2026-11-04T10:00:00+00:00", "source": "ec2",
                  "issues": [issue(1, "Claude"), issue(2, "ChatGPT"), issue(3, "Gemini", state="closed")],
                  "pulls": [pr(10, "claude/issue-1-a", draft=True), pr(11, "chatgpt/b", body="Closes #2", sha="s11"),
                            pr(12, "gemini/c", state="closed", merged="2026-11-04T05:00:00Z")],
                  "ci": {"s11": {"state": "failed", "failed": "smoke"}}}
        roadmap = [{"id": "T-9", "title": "Pay provider", "human": True, "done": False}]
        return build_team_tasks(github, roadmap=roadmap, lanes={"claude": {"state": "idle", "heartbeat_age_seconds": 7}},
                                repo="o/r", now=NOW)

    def test_provenance_fields(self):
        b = self.board()
        self.assertEqual(b["synced_at"], "2026-11-04T10:00:00+00:00")
        self.assertEqual(b["github_source"], "ec2")
        self.assertIn("progress_note", b)
        self.assertEqual(b["agents"]["claude"]["heartbeat_age_seconds"], 7)
        for task in all_tasks(b):
            for key in ("source", "updated_at", "created_at", "closed_at", "url"):
                self.assertIn(key, task, task["id"])
            self.assertIn(task["source"], ("issue", "pr", "roadmap", "owner_desk"))
            if task["pr"]:
                self.assertTrue(task["pr"]["updated_at"])
                self.assertIn(task["pr"]["ci"], ("passed", "failed", "running", "none", "unknown"))

    def test_progress_is_stage_not_measurement(self):
        b = self.board()
        tasks = all_tasks(b)
        self.assertTrue(tasks)
        for task in tasks:
            self.assertIsInstance(task["progress"], int)
            self.assertEqual(task["progress"], PROGRESS[task["status"]], task["id"])
        self.assertEqual(set(PROGRESS.values()), {0, 40, 60, 85, 100})
        by_id = {t["id"]: t for t in tasks}
        self.assertEqual(by_id["T-9"]["progress"], 0)            # owner task: nothing measured
        self.assertEqual(by_id["#2"]["status"], "ci_failed")
        self.assertEqual(by_id["#2"]["pr"]["ci_failed_check"], "smoke")


if __name__ == "__main__":
    unittest.main(verbosity=2)
