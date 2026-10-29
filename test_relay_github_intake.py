"""Offline checks for owner-approved GitHub Issue -> Relay intake."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

from fastapi import FastAPI, HTTPException
from relay import RelayStore, install_relay_routes
from relay_execution import RelayQueue
from relay_github_intake import fetch_github_issue, import_issue

REPO = "Pavlovskyi-Andrii/blackboxlab-factoryos"


def issue(number=54):
    return {
        "number": number,
        "title": "T-575: Resizable panels",
        "body": "Fix panel layout and validate on mobile",
        "state": "open",
        "html_url": f"https://github.com/{REPO}/issues/{number}",
    }


class TestGitHubIssueIntake(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = RelayStore(Path(self.tmp.name) / "relay.json")
        self.queue = RelayQueue(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def endpoint(self, identity):
        app = FastAPI()
        install_relay_routes(app, self.store, lambda request: identity, queue=self.queue)
        return next(
            route.endpoint for route in app.routes
            if route.path == "/api/relay/github/issues/{issue_number}/import"
            and "POST" in route.methods
        )

    def test_only_open_issues_from_configured_repo(self):
        for changed in (
            {**issue(), "state": "closed"},
            {**issue(), "pull_request": {}},
            {**issue(), "number": 99},
            {**issue(), "html_url": "https://github.com/elsewhere/repo/issues/54"},
            {**issue(), "title": ""},
        ):
            with self.assertRaises(ValueError):
                import_issue(self.store, changed)
        self.assertEqual(self.store.list(), [])

    def test_idempotent_across_restarts(self):
        first, created = import_issue(self.store, issue())
        self.assertTrue(created)
        self.assertEqual(first["execution"]["state"], "queued")
        self.assertEqual(first["source"]["source_key"], "github:" + REPO.lower() + "#54")
        second_store = RelayStore(Path(self.tmp.name) / "relay.json")
        again, created_again = import_issue(second_store, issue())
        self.assertFalse(created_again)
        self.assertEqual(again["id"], first["id"])
        self.assertEqual(len(second_store.list()), 1)
        self.assertNotIn("claimed_at", first["execution"])

    def test_request_owner_auth_before_github_lookup(self):
        route = self.endpoint({"role": "viewer"})
        with patch("relay.fetch_github_issue") as fetched:
            with self.assertRaises(HTTPException) as caught:
                route(54, SimpleNamespace())
            self.assertEqual(caught.exception.status_code, 403)
            fetched.assert_not_called()
        self.assertEqual(self.store.list(), [])

    def test_owner_import_queued_then_worker_claim(self):
        route = self.endpoint({"role": "owner", "email": "owner@example.test"})
        with patch("relay.fetch_github_issue", return_value=issue()) as fetched:
            result = route(54, SimpleNamespace())
            repeat = route(54, SimpleNamespace())
        self.assertTrue(result["created"])
        self.assertFalse(repeat["created"])
        self.assertEqual(result["ticket"]["execution"]["state"], "queued")
        self.assertEqual(repeat["ticket"]["id"], result["ticket"]["id"])
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.queue.claim("worker-test")["execution"]["state"], "claimed")
        self.assertEqual(fetched.call_count, 2)

    def test_github_http_errors_do_not_create_tickets(self):
        route = self.endpoint({"role": "owner"})
        error = HTTPError("https://api.github.com/", 404, "Not found", {}, None)
        with patch("relay.fetch_github_issue", side_effect=error):
            with self.assertRaises(HTTPException) as caught:
                route(54, SimpleNamespace())
        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(self.store.list(), [])

    def test_fetch_uses_fixed_github_api_origin(self):
        body = json.dumps(issue()).encode("utf-8")
        with patch("relay_github_intake.urlrequest.urlopen", return_value=io.BytesIO(body)) as fetch:
            actual = fetch_github_issue(54, repository=REPO)
        self.assertEqual(actual["number"], 54)
        request = fetch.call_args.args[0]
        self.assertEqual(request.full_url, "https://api.github.com/repos/" + REPO + "/issues/54")
        with self.assertRaises(ValueError):
            fetch_github_issue(0, repository=REPO)
        with self.assertRaises(ValueError):
            fetch_github_issue(54, repository="../../private")
        self.assertEqual(fetch.call_count, 1)


if __name__ == "__main__":
    unittest.main()
