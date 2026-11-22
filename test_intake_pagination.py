"""#259: owner issues beyond the first GitHub page reach Relay, once, with bounded and fail-closed pagination. Offline."""
import re
import tempfile
import unittest
import urllib.error
from pathlib import Path

from github_pages import fetch_all
from relay import RelayStore, relay_auto_intake_issues, relay_github_owner_issues
from relay_execution import RelayQueue
from team_tasks import compact_github, read_github, valid_snapshot

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"
OWNER = "Pavlovskyi-Andrii"


def gh_issue(number, body="Owner: Claude\nDo it", login=OWNER):
    return {"number": number, "title": f"Issue {number}", "body": body, "state": "open",
            "html_url": f"https://github.com/{REPO}/issues/{number}", "user": {"login": login},
            "updated_at": "2026-11-01T00:00:00Z"}


class PagedGitHub:
    """Serves a list of open issues 100 per page, like GitHub's /issues; records every page asked for."""

    def __init__(self, issues, fail_page=None, recent=None):
        self.issues, self.fail_page, self.recent, self.calls = issues, fail_page, recent or [], []

    def __call__(self, path):
        self.calls.append(path)
        if "state=all" in path:
            return self.recent
        if path.startswith("/pulls"):
            return []
        m = re.search(r"per_page=(\d+)&page=(\d+)", path)
        per, page = int(m.group(1)), int(m.group(2))
        if page == self.fail_page:
            raise urllib.error.HTTPError("https://api.github.com", 403, "Forbidden", {}, None)
        return self.issues[(page - 1) * per: page * per]


class FetchAllTest(unittest.TestCase):
    def test_stops_on_short_page_and_is_bounded(self):
        gh = PagedGitHub([gh_issue(n) for n in range(1, 151)])
        items, truncated = fetch_all(gh, "/issues?state=open")
        self.assertEqual((len(items), truncated, len(gh.calls)), (150, False, 2))
        endless = PagedGitHub([gh_issue(n) for n in range(1, 10_000)])
        items, truncated = fetch_all(endless, "/issues?state=open", max_pages=5)
        self.assertEqual((len(items), truncated, len(endless.calls)), (500, True, 5))   # never more than 5 calls

    def test_any_failed_page_fails_the_whole_read(self):
        gh = PagedGitHub([gh_issue(n) for n in range(1, 151)], fail_page=2)
        with self.assertRaises(urllib.error.HTTPError):
            fetch_all(gh, "/issues?state=open")
        self.assertRaises(ValueError, fetch_all, lambda p: {"message": "x"}, "/issues")
        self.assertRaises(ValueError, fetch_all, gh, "/issues", per_page=500)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_issue_on_page_two_is_imported_once(self):
        issues = [gh_issue(n, "Owner: Gemini\nfiller") for n in range(300, 240, -1)]          # 60 newer issues
        issues += [gh_issue(n, "Owner: ChatGPT\nfiller") for n in range(240, 190, -1)]       # 50 more
        issues.append(gh_issue(42, "Owner: Claude\nOld approved task"))                      # position 111: page 2
        issues.append(gh_issue(43, "Owner: Claude\nForeign", login="mallory"))               # page 2, wrong author
        gh = PagedGitHub(issues)
        first = relay_auto_intake_issues(self.queue, REPO, "", fetch=gh)
        self.assertTrue(first["ok"])
        imported = {x["issue"] for x in first["imported"]}
        self.assertIn(42, imported)
        self.assertNotIn(43, imported)                                                       # foreign author rejected
        self.assertEqual(len(gh.calls), 2)
        second = relay_auto_intake_issues(self.queue, REPO, "", fetch=PagedGitHub(issues))
        self.assertEqual(second["imported"], [])                                             # repeat sync is idempotent
        self.assertEqual(sum(1 for t in self.store.list() if t["source"].get("issue_number") == 42), 1)

    def test_403_on_any_page_imports_nothing_and_says_why(self):
        issues = [gh_issue(n) for n in range(1, 151)]
        for fail_page in (1, 2):
            out = relay_github_owner_issues(REPO, "", fetch=PagedGitHub(issues, fail_page=fail_page))
            self.assertFalse(out["available"])
            self.assertEqual(out["issues"], [])
            self.assertTrue(out["reason"])
        res = relay_auto_intake_issues(self.queue, REPO, "", fetch=PagedGitHub(issues, fail_page=2))
        self.assertFalse(res["ok"])
        self.assertEqual(self.store.list(), [])

    def test_truncation_is_reported(self):
        out = relay_github_owner_issues(REPO, "", fetch=PagedGitHub([gh_issue(n) for n in range(1, 900)]))
        self.assertTrue(out["available"])
        self.assertEqual((len(out["issues"]), out["truncated"]), (500, True))


class SnapshotTest(unittest.TestCase):
    def test_snapshot_carries_old_open_owner_issues(self):
        recent = [gh_issue(n) for n in range(500, 400, -1)]                                   # 100 recently updated
        old_open = recent[:30] + [gh_issue(42, "Owner: Claude\nOld approved task")]          # overlap + one old
        gh = PagedGitHub(old_open, recent=recent)
        g = read_github(gh, owner=OWNER)
        numbers = [i["number"] for i in g["issues"]]
        self.assertIn(42, numbers)
        self.assertEqual(len(numbers), len(set(numbers)))                                    # no duplicates
        self.assertFalse(g["open_owner_truncated"])
        self.assertTrue(valid_snapshot(compact_github(g)))
        self.assertTrue(any("creator=" + OWNER in c for c in gh.calls))
        self.assertNotIn(42, [i["number"] for i in read_github(PagedGitHub(old_open, recent=recent))["issues"]])  # old call

    def test_snapshot_fails_closed_on_a_403_page(self):
        gh = PagedGitHub([gh_issue(n) for n in range(1, 150)], fail_page=2, recent=[gh_issue(900)])
        g = read_github(gh, owner=OWNER)
        self.assertFalse(g["available"])
        self.assertEqual(g["issues"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
