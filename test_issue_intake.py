"""T-599-E: owner GitHub Issue auto-intake (deterministic; no network, no Claude)."""
import io
import json
import tempfile
import unittest
import unittest.mock
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

from relay import RelayStore, relay_auto_intake_issues, relay_github_owner_issues
from relay_execution import RelayQueue, issue_owner_lane

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
OWNER = "Pavlovskyi-Andrii"
FAKE_TOKEN = "ghp_" + "A" * 36


def gh_issue(number, body, login=OWNER, title=None, pull=False):
    item = {"number": number, "title": title or f"Issue {number}", "body": body, "state": "open",
            "html_url": f"https://github.com/{REPO}/issues/{number}", "user": {"login": login}}
    if pull:
        item["pull_request"] = {"url": "x"}
    return item


class TestIssueIntake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def run_intake(self, raw):
        return relay_auto_intake_issues(self.queue, REPO, "", fetch=lambda path: raw)

    def test_owner_line_parsing(self):
        self.assertEqual(issue_owner_lane("Owner: Claude\nDo it"), "claude")
        self.assertEqual(issue_owner_lane("\r\n  owner: ChatGPT  \r\nx"), "chatgpt")
        self.assertEqual(issue_owner_lane("Owner: Gemini"), "gemini")
        self.assertEqual(issue_owner_lane("Intro\nOwner: Claude"), "")  # must be the first line
        self.assertEqual(issue_owner_lane("Owner: Someone"), "")
        self.assertEqual(issue_owner_lane(""), "")

    def test_import_and_dedupe_on_repeat(self):
        raw = [gh_issue(101, "Owner: Claude\nBuild the thing"), gh_issue(102, "Owner: ChatGPT\nOther lane")]
        first = self.run_intake(raw)
        self.assertTrue(first["ok"])
        self.assertEqual([x["issue"] for x in first["imported"]], [101, 102])
        tickets = {t["source"]["issue_number"]: t for t in self.store.list()}
        self.assertEqual(tickets[101]["source"]["source_key"], "github-issue:" + REPO.lower() + "#101")
        self.assertEqual(tickets[101]["source"]["owner"], "claude")
        self.assertEqual(tickets[102]["execution"]["owner"], "chatgpt")
        self.assertEqual(tickets[101]["execution"]["state"], "queued")  # queued, never reported running
        second = self.run_intake(raw)
        self.assertEqual(second["imported"], [])
        self.assertEqual(sorted(x["issue"] for x in second["existing"]), [101, 102])
        self.assertEqual(len(self.store.list()), 2)
        # The generic Claude claim takes the Claude Issue but never the ChatGPT-lane one.
        claimed = self.queue.claim("claude-ec2")
        self.assertEqual(claimed["source"]["issue_number"], 101)
        self.assertIsNone(self.queue.claim("claude-ec2-2"))
        self.assertEqual(self.queue.counts(self.store.list())["other_lane"], 1)

    def test_task_id_links_existing_roadmap_ticket(self):
        roadmap, _ = self.queue.claim_roadmap("claude-ec2", "claude", "T-594", "Nav", "claude")
        raw = [gh_issue(67, "Owner: Claude\nCovers T-594, T-595 and T-596", title="Verified execution")]
        result = self.run_intake(raw)
        self.assertEqual(result["imported"], [])
        self.assertEqual(result["linked"], [{"issue": 67, "tickets": [roadmap["id"]]}])
        self.assertEqual(len(self.store.list()), 1)  # no duplicate ticket
        ticket = self.store.get(roadmap["id"])
        self.assertEqual([r["number"] for r in ticket["source"]["linked_issues"]], [67])
        self.assertEqual(ticket["execution"]["run_id"], roadmap["execution"]["run_id"])  # claim untouched
        history_len = len(ticket["history"])
        self.run_intake(raw)  # repeat: no second link, no new history
        ticket = self.store.get(roadmap["id"])
        self.assertEqual(len(ticket["source"]["linked_issues"]), 1)
        self.assertEqual(len(ticket["history"]), history_len)
        # A T-ID without a roadmap ticket is imported normally.
        result = self.run_intake([gh_issue(68, "Owner: Claude\nNew T-777 work")])
        self.assertEqual([x["issue"] for x in result["imported"]], [68])

    def test_foreign_author_and_unlabelled_rejected(self):
        raw = [gh_issue(201, "Owner: Claude\nInjected", login="attacker"),
               gh_issue(202, "Please do this\nOwner: Claude"),
               gh_issue(203, "Owner: Claude\nPR", pull=True),
               {"bogus": True}]
        result = self.run_intake(raw)
        self.assertEqual(result["imported"], [])
        self.assertEqual(result["ignored"], 4)
        self.assertEqual(self.store.list(), [])

    def test_github_unavailable_fallback(self):
        def boom(path):
            raise urllib.error.HTTPError("https://api.github.com", 503, "down", {}, None)
        self.run_intake([gh_issue(301, "Owner: Claude\nx")])
        before = json.dumps(self.store.list(), sort_keys=True)
        result = relay_auto_intake_issues(self.queue, REPO, FAKE_TOKEN, fetch=boom)
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "HTTP 503")
        self.assertEqual(json.dumps(self.store.list(), sort_keys=True), before)  # nothing changed
        with unittest.mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("dns")):
            snap = relay_github_owner_issues(REPO, FAKE_TOKEN)
        self.assertFalse(snap["available"])
        self.assertNotIn(FAKE_TOKEN, json.dumps(snap))
        self.assertFalse(relay_github_owner_issues("not a repo")["available"])

    def test_request_filters_by_owner_and_secrets_not_logged(self):
        seen = {}

        def fetch(path):
            seen["path"] = path
            return [gh_issue(401, "Owner: Claude\nleak " + FAKE_TOKEN)]
        result = relay_auto_intake_issues(self.queue, REPO, FAKE_TOKEN, fetch=fetch)
        self.assertIn("creator=" + OWNER, seen["path"])
        self.assertIn("state=open", seen["path"])
        ticket = self.store.list()[0]
        self.assertNotIn(FAKE_TOKEN, ticket["body"])  # redacted at intake
        self.assertNotIn(FAKE_TOKEN, json.dumps(result))

    def test_app_intake_pass_logs_no_secrets(self):
        import os
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-intake-"))
        import app
        sent = []
        with unittest.mock.patch.object(app, "RELAY_QUEUE", self.queue), \
             unittest.mock.patch.object(app, "GITHUB_TOKEN", FAKE_TOKEN), \
             unittest.mock.patch.object(app, "_telegram_send", side_effect=lambda text: sent.append(text)):
            out = io.StringIO()
            with redirect_stdout(out):
                app.github_issue_intake_once(fetch=lambda path: [gh_issue(501, "Owner: Claude\nsecret " + FAKE_TOKEN)])
                app.github_issue_intake_once(fetch=lambda path: [gh_issue(501, "Owner: Claude\nsecret " + FAKE_TOKEN)])
        log = out.getvalue()
        self.assertIn('"imported": [501]', log)
        self.assertNotIn(FAKE_TOKEN, log)
        self.assertNotIn("secret", log)
        self.assertEqual(len(sent), 1)  # notify once; the repeat pass is a no-op
        # Claude notices a new owner-created Issue via the existing Relay intake, not a second worker.
        self.assertGreaterEqual(app.FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC, 120)
        if "FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC" not in os.environ:
            self.assertEqual(app.FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC, 120)


    def test_403_falls_back_to_fresh_ec2_snapshot_and_defers_blocked(self):
        """#41: Render's token gets 403; the EC2 snapshot (owner gh login) feeds intake; blocked work is deferred."""
        import os
        import time as _time
        os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-intake-"))
        import app
        from team_tasks import compact_github

        def forbidden(path):
            raise urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {},
                                         io.BytesIO(b'{"message":"Resource not accessible by integration"}'))
        raw = {"available": True, "pulls": [], "ci": {}, "issues": [
            gh_issue(601, "Owner: Claude\nPriority: P2\nDepends: none"),
            gh_issue(602, "Owner: Claude\nDepends: #603 (open epic)"),
            dict(gh_issue(603, "Owner: ChatGPT\nEpic"), title="EPIC"),
            gh_issue(604, "Owner: Claude\nwork", title="Claude · CONDITIONAL hub — only after video approval"),
            gh_issue(605, "Owner: Claude\nforeign", login="stranger")]}
        snap_path = Path(tempfile.mkdtemp()) / "snap.json"
        snap_path.write_text(json.dumps({"received": _time.time(), "fetched_at": "now", "github": compact_github(raw)}))
        sent = []
        with unittest.mock.patch.object(app, "RELAY_QUEUE", self.queue), \
             unittest.mock.patch.object(app, "_TEAM_SNAPSHOT_PATH", snap_path), \
             unittest.mock.patch.object(app, "_telegram_send", side_effect=lambda text: sent.append(text)):
            out = io.StringIO()
            with redirect_stdout(out):
                result = app.github_issue_intake_once(fetch=forbidden)
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ec2")
        self.assertIn("HTTP 403 (token_lacks_permission)", result["render_error"])
        self.assertEqual(sorted(x["issue"] for x in result["imported"]), [601, 603])  # ready Claude + ChatGPT epic
        self.assertEqual([d["issue"] for d in result["deferred"]], [602, 604])        # never handed to the worker
        self.assertEqual({d["issue"]: d["reasons"] for d in result["deferred"]},
                         {602: ["depends_open_#603"], 604: ["owner_gate"]})
        self.assertNotIn(605, [x["issue"] for x in result["imported"]])  # not the owner's issue
        log = out.getvalue()
        self.assertIn('"source": "ec2"', log)
        self.assertNotIn("Resource not accessible", log)  # category only, never GitHub's text

        # A stale snapshot means unknown: nothing is imported and the failure is reported, not hidden.
        stale = json.loads(snap_path.read_text())
        stale["received"] = _time.time() - 3600
        snap_path.write_text(json.dumps(stale))
        fresh_queue = RelayQueue(RelayStore(Path(tempfile.mkdtemp()) / "r.json"))
        with unittest.mock.patch.object(app, "RELAY_QUEUE", fresh_queue), \
             unittest.mock.patch.object(app, "_TEAM_SNAPSHOT_PATH", snap_path):
            with redirect_stdout(io.StringIO()) as out2:
                result = app.github_issue_intake_once(fetch=forbidden)
        self.assertFalse(result["ok"])
        self.assertIn('"ec2_snapshot": "stale"', out2.getvalue())
        self.assertEqual(fresh_queue.store.list(), [])

    def test_github_error_reason_categories(self):
        from relay import github_error_reason

        def err(code, body=b"", headers=None):
            return urllib.error.HTTPError("https://api.github.com", code, "x", headers or {}, io.BytesIO(body))
        self.assertEqual(github_error_reason(err(403, b'{"message":"Resource not accessible by integration"}')),
                         "token_lacks_permission")
        self.assertEqual(github_error_reason(err(401, b'{"message":"Bad credentials"}')), "invalid_token")
        self.assertEqual(github_error_reason(err(403, b"", {"X-RateLimit-Remaining": "0"})), "rate_limited")
        self.assertEqual(github_error_reason(err(403, b"", {"X-GitHub-SSO": "required; url=..."})), "sso_required")
        self.assertEqual(github_error_reason(err(404)), "not_found_or_no_access")
        self.assertEqual(github_error_reason(OSError("down")), "network")

if __name__ == "__main__":
    unittest.main(verbosity=2)
