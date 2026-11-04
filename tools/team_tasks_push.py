"""EC2 → FactoryOS: push a compact GitHub snapshot (Issues, PRs, CI) for the team tasks page.

Render's GitHub token could not read the repo (HTTP 403, 2026-11-04); the EC2 worker is logged in with
the owner's gh account, so it reads GitHub and sends only the fields the page needs. Worker token auth.
"""
import json
import os
import subprocess
import sys
import urllib.request

from team_tasks import compact_github, read_github

REPO = os.environ.get("GEMINI_LOOP_REPO", "Pavlovskyi-Andrii/blackboxlab-factoryos")


def fetch(path):
    out = subprocess.run(["gh", "api", "repos/" + REPO + path], capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        err = RuntimeError("gh api failed")
        err.code = "gh"
        raise err
    return json.loads(out.stdout)


def main():
    url, token = os.environ.get("FACTORYOS_URL", "").rstrip("/"), os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", "")
    if not url or not token:
        sys.exit("team-tasks-push: FACTORYOS_URL / worker token not configured")
    github = read_github(fetch)
    if not github.get("available"):
        sys.exit("team-tasks-push: GitHub read failed: " + str(github.get("error")))
    body = json.dumps(compact_github(github)).encode()
    req = urllib.request.Request(url + "/api/factory/team-tasks/worker/snapshot", data=body, method="POST",
                                 headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as response:
        print("team-tasks-push:", response.read().decode()[:200])


if __name__ == "__main__":
    main()
