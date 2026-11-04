#!/usr/bin/env bash
# Gemini night/day loop on EC2 (owner decision 2026-11-04): every 5 minutes, up to 15 model attempts.
# Runs the script from origin/main (never the working tree), the Gemini key stays in Render (FactoryOS proxy),
# PRs are opened with the owner's gh login so FactoryOS CI runs on them normally.
set -euo pipefail
REPO="${GEMINI_LOOP_REPO:-Pavlovskyi-Andrii/blackboxlab-factoryos}"
exec 9>/tmp/factoryos-gemini-loop.lock
flock -n 9 || { echo "gemini-loop: previous run still active"; exit 0; }

issue=""
for n in $(gh issue list -R "$REPO" --label gemini --state open --json number,body \
             --jq '[.[]|select(.body|startswith("Owner: Gemini"))]|sort_by(.number)|.[].number'); do
  if ! gh api "repos/$REPO/branches/gemini/issue-$n" >/dev/null 2>&1; then issue="$n"; break; fi
done
[ -n "$issue" ] || { echo "gemini-loop: no Gemini issue waiting"; exit 0; }

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
gh api "repos/$REPO/contents/tools/gemini_issue_pr.cjs?ref=main" -H "Accept: application/vnd.github.raw" > "$work/gemini_issue_pr.cjs"
cd "$work"
export GITHUB_REPOSITORY="$REPO" ISSUE_NUMBER="$issue" GITHUB_TOKEN="$(gh auth token)"
export GEMINI_MAX_ATTEMPTS="${GEMINI_MAX_ATTEMPTS:-15}" GEMINI_BACKOFF_MS="${GEMINI_BACKOFF_MS:-15000}" GEMINI_QUIET_TRANSIENT=1
unset GEMINI_API_KEY
echo "gemini-loop: issue #$issue"
set +e
node gemini_issue_pr.cjs generate; rc=$?
set -e
if [ "$rc" = 3 ]; then echo "gemini-loop: Google busy/limited, next try in 5 min"; exit 0; fi
[ "$rc" = 0 ] || exit "$rc"
node gemini_issue_pr.cjs publish
