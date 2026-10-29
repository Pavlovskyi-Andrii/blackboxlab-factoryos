"""GitHub Issue -> Relay intake, with explicit allowlist and idempotency.

Call from an authenticated owner-controlled workflow. This module does not
poll, start a worker, deploy, or publish by itself.
"""
from __future__ import annotations

import json
import re
from urllib import request as urlrequest

ISSUE_URL = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)/?$")
DEFAULT_REPOSITORY = "Pavlovskyi-Andrii/blackboxlab-factoryos"


def import_issue(store, issue: dict, repository: str = DEFAULT_REPOSITORY) -> tuple[dict, bool]:
    """Import a verified GitHub issue payload into Relay once.

    The caller must fetch the issue from GitHub using trusted credentials and
    authorize the import. A newly created Relay ticket is queued by RelayStore;
    this function never claims it or reports it running.
    """
    if not isinstance(issue, dict):
        raise ValueError("Issue must be an object")
    url = str(issue.get("html_url") or issue.get("url") or "").strip()
    match = ISSUE_URL.fullmatch(url)
    if not match or f"{match.group(1)}/{match.group(2)}".lower() != repository.lower():
        raise ValueError("Issue URL does not belong to configured repository")
    number = int(match.group(3))
    if str(issue.get("number", number)) != str(number):
        raise ValueError("Issue number mismatch")
    if issue.get("pull_request") or issue.get("state") != "open":
        raise ValueError("Only open GitHub Issues can be imported")
    title = str(issue.get("title") or "").strip()
    if not title:
        raise ValueError("Issue title is required")
    body = str(issue.get("body") or "")
    source = {
        "channel": "github_issue",
        "url": url,
        "source_key": f"github:{repository.lower()}#{number}",
        "issue_number": number,
    }
    return store.create(title=title, body=body, source=source, created_by="github_issue")


def fetch_github_issue(number: int, repository: str = DEFAULT_REPOSITORY, token: str = "") -> dict:
    """Fetch exactly one issue from GitHub, never a user-provided URL.

    Any network error must be reported by the owner route. No API billing,
    worker claim, state mutation or automatic retry occurs here.
    """
    if not isinstance(number, int) or isinstance(number, bool) or number < 1 or number > 1000000000:
        raise ValueError("Invalid issue number")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Invalid GitHub repository")
    endpoint = f"https://api.github.com/repos/{repository}/issues/{number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "FactoryOS-Relay/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = "Bearer " + token.strip()
    req = urlrequest.Request(endpoint, headers=headers)
    with urlrequest.urlopen(req, timeout=6) as response:
        data = response.read(256 * 1024 + 1)
    if len(data) > 256 * 1024:
        raise ValueError("GitHub response too large")
    issue = json.loads(data)
    if not isinstance(issue, dict):
        raise ValueError("Invalid GitHub response")
    return issue
