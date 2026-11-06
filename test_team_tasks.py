"""Team tasks page: statuses from Issues / PRs / CI / ROADMAP, owner-only route. No network."""
import os
import tempfile
import unittest

from team_tasks import TeamTasksCache, build_team_tasks, compact_github, queue_readiness, read_github

NOW = 1_800_000_000.0  # fixed clock


def issue(n, owner, state="open", labels=(), updated="2026-11-04T08:00:00Z", closed=None):
    return {"number": n, "title": f"Task {n}", "body": f"Owner: {owner}\n\ntext", "state": state, "html_url": f"https://g/i/{n}",
            "labels": [{"name": x} for x in labels], "updated_at": updated, "created_at": "2026-11-01T00:00:00Z", "closed_at": closed}


def pr(n, branch, body="", draft=False, state="open", merged=None, sha=None, updated="2026-11-04T09:00:00Z"):
    return {"number": n, "title": f"PR {n}", "body": body, "draft": draft, "state": state, "merged_at": merged,
            "head": {"ref": branch, "sha": sha or f"sha{n}"}, "html_url": f"https://g/p/{n}", "updated_at": updated,
            "created_at": "2026-11-03T00:00:00Z"}


class TeamTasksTest(unittest.TestCase):
    def board(self):
        github = {"available": True,
                  "issues": [issue(1, "ChatGPT"), issue(2, "ChatGPT"), issue(3, "Gemini", labels=["gemini"]),
                             issue(4, "Claude", state="closed", closed="2026-11-03T10:00:00Z"),
                             issue(5, "Claude (взял днём)"), issue(6, "Gemini", labels=["blocked"]),
                             issue(7, "ChatGPT"), {"number": 99, "pull_request": {}, "body": "Owner: Claude"},
                             {"number": 8, "title": "no owner", "body": "hello", "state": "open"}],
                  "pulls": [pr(10, "chatgpt/issue-1-x", draft=True), pr(11, "chatgpt/y", body="Closes #2"),
                            pr(12, "claude/z", body="Refs #5", sha="bad"), pr(13, "gemini/issue-134", state="closed", merged="2026-11-04T05:00:00Z"),
                            pr(14, "chatgpt/q", body="Refs #7", state="closed"), pr(15, "someone/else")],
                  "ci": {"sha11": {"state": "passed", "failed": ""}, "bad": {"state": "failed", "failed": "syntax-and-smoke"}}}
        roadmap = [{"id": "T-520", "title": "Configure publisher", "human": True, "done": False, "roadmap_line": 285, "need": "account"},
                   {"id": "T-1", "title": "done human", "human": True, "done": True}, {"id": "T-2", "title": "auto", "human": False, "done": False}]
        lanes = {"claude": {"state": "working", "heartbeat_age_seconds": 12}, "gemini": {"state": "offline"}}
        return build_team_tasks(github, roadmap=roadmap, lanes=lanes, repo="o/r", now=NOW)

    def test_statuses(self):
        b = self.board()
        chat = {t["id"]: t for t in b["agents"]["chatgpt"]["tasks"]}
        self.assertEqual(chat["#1"]["status"], "in_progress")           # draft PR via branch issue-1
        self.assertEqual(chat["#2"]["status"], "review")                # ready PR, CI passed
        self.assertEqual(chat["#2"]["reason"], "awaiting_review")
        self.assertEqual(chat["#7"]["status"], "queued")                # PR closed without merge does not count
        claude = {t["id"]: t for t in b["agents"]["claude"]["tasks"]}
        self.assertEqual(claude["#5"]["status"], "ci_failed")
        self.assertEqual(claude["#5"]["pr"]["ci_failed_check"], "syntax-and-smoke")
        self.assertEqual(claude["#4"]["status"], "done")
        gem = {t["id"]: t for t in b["agents"]["gemini"]["tasks"]}
        self.assertEqual(gem["#3"]["reason"], "gemini_loop")
        self.assertEqual(gem["#6"]["status"], "blocked")
        self.assertEqual(gem["PR #13"]["status"], "done")               # merged agent PR without its issue in the list
        self.assertNotIn("PR #15", str(b))                               # unknown branch prefix is not an executor
        self.assertNotIn("#8", {t["id"] for a in b["agents"].values() for t in a["tasks"]})

    def test_owner_lane_and_summary(self):
        b = self.board()
        owner = b["agents"]["owner"]
        self.assertEqual([t["id"] for t in owner["tasks"]], ["T-520"])
        self.assertTrue(owner["tasks"][0]["url"].endswith("ROADMAP.md#L285"))
        self.assertEqual(b["totals"]["waiting_owner"], 1)
        chat = b["agents"]["chatgpt"]
        self.assertEqual(chat["current"]["id"], "#1")                   # draft PR = being done now
        self.assertEqual(chat["next"]["id"], "#7")
        self.assertEqual(b["agents"]["claude"]["last_done"]["id"], "#4")
        self.assertTrue(b["agents"]["claude"]["online"])
        self.assertIsNone(b["agents"]["chatgpt"]["online"])              # no heartbeat = unknown, not offline
        self.assertFalse(b["agents"]["gemini"]["online"] is True)

    def test_github_failure_is_unavailable(self):
        def boom(path):
            err = Exception("x")
            err.code = 403
            raise err
        g = read_github(boom)
        self.assertEqual((g["available"], g["error"]), (False, "HTTP 403"))
        b = build_team_tasks(g, roadmap=[], now=NOW)
        self.assertFalse(b["github_available"])
        self.assertEqual(b["totals"]["queued"], 0)

    def test_read_github_ci(self):
        calls = []

        def fetch(path):
            calls.append(path)
            if path.startswith("/issues"):
                return []
            if path.startswith("/pulls"):
                return [pr(1, "claude/a", sha="s1"), pr(2, "claude/b", state="closed")]
            return {"check_runs": [{"name": "a", "status": "completed", "conclusion": "success"},
                                   {"name": "b", "status": "in_progress", "conclusion": None}]}
        g = read_github(fetch)
        self.assertEqual(g["ci"], {"s1": {"state": "running", "failed": ""}})
        self.assertEqual(sum(p.startswith("/commits/") for p in calls), 1)  # only open PR heads

    def test_cache(self):
        n = []
        c = TeamTasksCache(ttl=999, min_refresh=0)
        c.get(lambda: n.append(1) or {"v": len(n)})
        c.get(lambda: n.append(1) or {"v": len(n)})
        self.assertEqual(len(n), 1)
        c.get(lambda: n.append(1) or {"v": len(n)}, refresh=True)
        self.assertEqual(len(n), 2)

    def test_compact_snapshot(self):
        from team_tasks import compact_github, valid_snapshot
        g = {"available": True, "issues": [dict(issue(1, "ChatGPT"), body="Owner: ChatGPT\nsecret long text")],
             "pulls": [pr(2, "chatgpt/x", body="Long description. Closes #1 and more")], "ci": {"sha2": {"state": "passed", "failed": ""}}}
        c = compact_github(g)
        self.assertEqual(c["issues"][0]["body"], "Owner: ChatGPT")
        self.assertEqual(c["pulls"][0]["body"], "Refs #1")
        self.assertTrue(valid_snapshot(c))
        self.assertFalse(valid_snapshot({"available": True, "issues": "x", "pulls": [], "ci": {}}))
        b = build_team_tasks(c, roadmap=[], now=NOW)
        self.assertEqual(b["agents"]["chatgpt"]["tasks"][0]["status"], "review")

    def test_ec2_snapshot_fallback_through_app(self):
        import json
        from unittest.mock import patch
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-team-tasks-"))
        import app
        from test_worker_token_binding import asgi_post
        body = json.dumps({"available": True, "issues": [issue(5, "Gemini")], "pulls": [], "ci": {}}).encode()
        with patch.object(app, "FACTORY_PASSWORD", "set-so-auth-is-enforced"), \
             patch.object(app, "FACTORY_CLAUDE_WORKER_TOKEN", "worker-token"), \
             patch.object(app, "read_github", lambda fetch, **kw: {"available": False, "error": "HTTP 403", "issues": [], "pulls": [], "ci": {}}):
            self.assertEqual(asgi_post("/api/factory/team-tasks/worker/snapshot", None, body)[0], 401)
            self.assertEqual(asgi_post("/api/factory/team-tasks/worker/snapshot", "worker-token", b'{"issues": 1}')[0], 400)
            status, out = asgi_post("/api/factory/team-tasks/worker/snapshot", "worker-token", body)
            self.assertEqual(status, 200, out)
            board = app.get_team_tasks(refresh=True)
            self.assertEqual(board["github_source"], "ec2")
            self.assertTrue(board["github_available"])
            self.assertEqual(board["agents"]["gemini"]["tasks"][0]["id"], "#5")
            # The lane board peeks at this cache while the board is being built: it must not deadlock.
            self.assertIn("gemini", app.get_lane_board()["lanes"])

    def test_owner_only_route(self):
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-team-tasks-"))
        import app
        self.assertIn("/api/factory/team-tasks", {getattr(r, "path", "") for r in app.app.routes})


class QueueKeeperTest(unittest.TestCase):
    """#231: READY / BLOCKED / IN_REVIEW for Claude Issues, no invented tasks, same answer on every run."""

    def github(self):
        def iss(n, title="Task", body="", state="open", labels=()):
            return dict(issue(n, "Claude", state=state, labels=labels), title=f"{title} {n}",
                        body=f"Owner: Claude\nPriority: P1\n{body}")
        return {"available": True,
                "issues": [iss(1), iss(2, body="Depends: #9 (open), #8 (closed)"), iss(3, body="Depends: #8, T-593"),
                           iss(4, labels=["blocked"]), iss(5, title="Claude · CONDITIONAL hub — only after video approval"),
                           iss(6, body="Depends: none"), iss(7), issue(9, "ChatGPT"), issue(8, "ChatGPT", state="closed"),
                           iss(10, body="Priority: P0 · Depends: #555 (older than this read), #22 (a closed PR)"), iss(11, state="closed"),
                           iss(13, body="Depends: #20 (an open PR)"),
                           issue(12, "Gemini")],
                "pulls": [pr(20, "claude/x", body="Closes #7"), pr(21, "gemini/issue-6"),
                          pr(22, "claude/y", body="Refs #1", state="closed")],  # closed unmerged PR does not count
                "ci": {}}

    def test_classification(self):
        roadmap = [{"id": "T-593", "done": False}, {"id": "T-1", "done": True}]
        q = queue_readiness(self.github(), roadmap=roadmap)
        ready = [t["number"] for t in q["ready"]]
        blocked = {t["number"]: t["reasons"] for t in q["blocked"]}
        self.assertEqual(ready, [1, 10])
        self.assertEqual(blocked, {2: ["depends_open_#9"], 3: ["depends_roadmap_T-593"], 4: ["blocked_label"],
                                   5: ["owner_gate"], 6: ["claimed_by_gemini"], 13: ["depends_open_#20"]})
        self.assertEqual([t["number"] for t in q["in_review"]], [7])
        self.assertEqual(q["counts"], {"open": 9, "ready": 2, "blocked": 6, "in_review": 1})
        self.assertEqual(q["ready"][1]["unverified_depends"], ["#555"])  # not guessed as done or open
        self.assertEqual(q["shortfall"], 8)  # PR dependencies resolve from PR state: #22 closed → not unverified
        self.assertIn("No task is invented", q["escalation"])
        # A finished roadmap dependency no longer blocks.
        done = queue_readiness(self.github(), roadmap=[{"id": "T-593", "done": True}])
        self.assertIn(3, [t["number"] for t in done["ready"]])

    def test_deterministic_and_target(self):
        g = self.github()
        runs = [queue_readiness(g, roadmap=[]) for _ in range(3)]
        self.assertTrue(all(r == runs[0] for r in runs))  # multiple runs: same report, nothing created
        self.assertEqual(queue_readiness(g, roadmap=[], target=2)["shortfall"], 0)
        self.assertEqual(queue_readiness(g, roadmap=[], target=2)["escalation"], "")

    def test_unavailable_is_not_empty_success(self):
        q = queue_readiness({"available": False, "error": "HTTP 403"}, roadmap=[])
        self.assertFalse(q["available"])
        self.assertIsNone(q["counts"])
        self.assertIsNone(q["shortfall"])

    def test_board_shows_blocked_and_decision_cards(self):
        cards = [{"id": "D-240", "title": "Decide on #2 and #3", "covers": [2, 3]}]
        board = build_team_tasks(self.github(), roadmap=[{"id": "T-593", "done": False}], repo="o/r", now=NOW, owner_cards=cards)
        claude = {t["number"]: t for t in board["agents"]["claude"]["tasks"]}
        self.assertEqual((claude[2]["status"], claude[2]["reason"], claude[2]["blocked_by"]), ("blocked", "depends", ["#9"]))
        self.assertEqual(claude[2]["decision_card"], "D-240")
        self.assertEqual((claude[5]["status"], claude[5]["reason"]), ("blocked", "owner_gate"))
        self.assertEqual((claude[1]["status"], claude[1]["reason"]), ("queued", "not_started"))  # ready stays queued
        owner = [t for t in board["agents"]["owner"]["tasks"] if t["source"] == "owner_desk"]
        self.assertEqual([(t["id"], t["status"], t["decision_card"]) for t in owner], [("D-240", "waiting_owner", "D-240")])
        self.assertEqual(board["queue_keeper"]["counts"]["ready"], 2)

    def test_snapshot_keeps_depends_and_board_exposes_queue(self):
        snap = compact_github(self.github())
        two = next(i for i in snap["issues"] if i["number"] == 2)
        self.assertEqual(two["body"], "Owner: Claude\nDepends: #9 (open), #8 (closed)")
        self.assertNotIn("Priority", two["body"])  # the rest of the body is still dropped
        board = build_team_tasks(snap, roadmap=[{"id": "T-593", "done": False}], repo="o/r", now=NOW)
        self.assertEqual(board["queue_keeper"]["counts"]["ready"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
