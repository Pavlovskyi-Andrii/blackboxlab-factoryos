"""#258 contract: GitHub owner-issue intake when Render's own read fails (HTTP 403) and the EC2 snapshot is used.

Offline and deterministic: fake GitHub reads, temporary snapshot files, a temporary Relay store. No network, no token.
Stale, missing or malformed snapshot data is UNKNOWN: nothing is imported and the reason is reported.
"""
import io
import json
import os
import tempfile
import time
import unittest
import unittest.mock
import urllib.error
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-intake-contract-"))

import app  # noqa: E402
from relay import RelayStore  # noqa: E402
from relay_execution import RelayQueue  # noqa: E402
from team_tasks import compact_github  # noqa: E402

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
OWNER = "Pavlovskyi-Andrii"
FAKE_TOKEN = "ghp_" + "Z" * 36


def gh_issue(number, body, login=OWNER, title=None):
    return {"number": number, "title": title or f"Issue {number}", "body": body, "state": "open",
            "html_url": f"https://github.com/{REPO}/issues/{number}", "user": {"login": login}}


def forbidden(path):
    raise urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {},
                                 io.BytesIO(b'{"message":"Resource not accessible by integration"}'))


class IntakeFallbackContract(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.queue = RelayQueue(RelayStore(self.tmp / "relay.json"))
        self.snap = self.tmp / "team_tasks_github.json"

    def write_snapshot(self, issues, *, age=0.0, raw=None):
        if raw is not None:
            self.snap.write_text(raw if isinstance(raw, str) else json.dumps(raw))
            return
        github = compact_github({"available": True, "issues": issues, "pulls": [], "ci": {}})
        self.snap.write_text(json.dumps({"received": time.time() - age, "fetched_at": "t", "github": github}))

    def intake(self, fetch=forbidden):
        out = io.StringIO()
        with unittest.mock.patch.object(app, "RELAY_QUEUE", self.queue), \
             unittest.mock.patch.object(app, "_TEAM_SNAPSHOT_PATH", self.snap), \
             unittest.mock.patch.object(app, "GITHUB_TOKEN", FAKE_TOKEN), \
             unittest.mock.patch.object(app, "_telegram_send", lambda text: None), \
             redirect_stdout(out):
            result = app.github_issue_intake_once(fetch=fetch)
        log = out.getvalue()
        self.assertNotIn(FAKE_TOKEN, log + json.dumps(result, default=str))  # never leak the credential
        return result, log

    def tickets(self):
        return self.queue.store.list(limit=500)

    # 1 ---------------------------------------------------------------------------------------------------------
    def test_1_primary_403_with_fresh_snapshot_imports_with_provenance(self):
        self.write_snapshot([gh_issue(701, "Owner: Claude\nDepends: none")])
        result, log = self.intake()
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ec2")                      # provenance: where the issues came from
        self.assertIn("HTTP 403 (token_lacks_permission)", result["render_error"])
        self.assertEqual([x["issue"] for x in result["imported"]], [701])
        self.assertIn('"source": "ec2"', log)

    # 2 ---------------------------------------------------------------------------------------------------------
    def test_2_expired_snapshot_is_unknown_not_imported(self):
        self.write_snapshot([gh_issue(702, "Owner: Claude")], age=app.INTAKE_SNAPSHOT_MAX_AGE + 5)
        result, log = self.intake()
        self.assertFalse(result["ok"])
        self.assertEqual(result["ec2_snapshot"], "stale")
        self.assertEqual(self.tickets(), [])
        self.assertIn('"ec2_snapshot": "stale"', log)

    # 3 ---------------------------------------------------------------------------------------------------------
    def test_3_missing_snapshot_is_unknown_not_imported(self):
        result, log = self.intake()
        self.assertFalse(result["ok"])
        self.assertEqual(result["ec2_snapshot"], "missing")
        self.assertEqual(self.tickets(), [])

    # 4 ---------------------------------------------------------------------------------------------------------
    def test_4_malformed_snapshot_is_unknown_and_never_crashes(self):
        future = {"received": time.time() + 3600, "github": {"issues": [gh_issue(704, "Owner: Claude")]}}
        cases = {"not json": "{", "a list": [1, 2], "received not a number": {"received": "soon", "github": {"issues": []}},
                 "no github": {"received": time.time()}, "issues not a list": {"received": time.time(), "github": {"issues": "x"}},
                 "from the future": future}
        for name, raw in cases.items():
            with self.subTest(name):
                self.write_snapshot(None, raw=raw)
                result, _ = self.intake()
                self.assertFalse(result["ok"], name)
                expected = "stale" if name == "from the future" else ("missing" if name == "not json" else "malformed")
                self.assertEqual(result["ec2_snapshot"], expected, name)
                self.assertEqual(self.tickets(), [], name)

    # 5 ---------------------------------------------------------------------------------------------------------
    def test_5_same_issue_from_primary_then_snapshot_is_one_ticket(self):
        issue = gh_issue(705, "Owner: Claude\nDepends: none")
        first, _ = self.intake(fetch=lambda path: [issue])               # Render's own read works once
        self.assertEqual((first["source"], [x["issue"] for x in first["imported"]]), ("render", [705]))
        self.write_snapshot([issue])
        second, _ = self.intake()                                        # then 403 and the snapshot carries it
        self.assertEqual(second["source"], "ec2")
        self.assertEqual(second["imported"], [])
        self.assertEqual([x["issue"] for x in second["existing"]], [705])
        self.assertEqual(len(self.tickets()), 1)

    # 6 ---------------------------------------------------------------------------------------------------------
    def test_6_repeated_snapshot_imports_are_idempotent(self):
        self.write_snapshot([gh_issue(706, "Owner: Claude"), gh_issue(707, "Owner: Gemini")])
        runs = [self.intake()[0] for _ in range(3)]
        self.assertEqual(sorted(x["issue"] for x in runs[0]["imported"]), [706, 707])
        for later in runs[1:]:
            self.assertEqual(later["imported"], [])
            self.assertEqual(sorted(x["issue"] for x in later["existing"]), [706, 707])
        self.assertEqual(len(self.tickets()), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
