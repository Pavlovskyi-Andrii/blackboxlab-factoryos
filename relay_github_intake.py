"""GitHub Issue -> Relay intake, with explicit allowlist and idempotency.

Call from an authenticated owner-controlled workflow. This module does not
poll, start a worker, deploy, or publish by itself.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

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
