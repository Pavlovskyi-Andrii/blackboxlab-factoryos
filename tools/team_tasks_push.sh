#!/usr/bin/env bash
# Runs the snapshot pusher from origin/main (never a working tree). EC2 systemd timer, every 3 minutes.
set -euo pipefail
REPO="${GEMINI_LOOP_REPO:-Pavlovskyi-Andrii/blackboxlab-factoryos}"
work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
for f in team_tasks.py tools/team_tasks_push.py; do
  gh api "repos/$REPO/contents/$f?ref=main" -H "Accept: application/vnd.github.raw" > "$work/$(basename "$f")"
done
cd "$work" && python3 team_tasks_push.py
