#!/usr/bin/env bash
# Prints the MyCast episode files a push changed, one per line; the newest episode when it changed none.
# Usage: tools/mycast_changed_episodes.sh [BEFORE_SHA]   (BEFORE_SHA = github.event.before; empty or zeros = unknown)
# The whole pushed range counts, not only the last commit: a push can carry several commits.
set -euo pipefail
dir=docs/prototypes/mycast/episodes
before="${1:-}"
changed=""
if [ -n "$before" ] && [ -z "${before//0/}" ]; then before=""; fi
if [ -n "$before" ]; then
  git cat-file -e "$before^{commit}" 2>/dev/null || git fetch --quiet --depth=1 origin "$before" 2>/dev/null || before=""
fi
[ -n "$before" ] || before=$(git rev-parse --quiet --verify HEAD~1 || true)
if [ -n "$before" ]; then
  changed=$(git diff --name-only --diff-filter=AM "$before" HEAD -- "$dir/*.json" 2>/dev/null || true)
fi
[ -n "$changed" ] || changed=$(ls "$dir"/*.json | sort | tail -n 1)
echo "$changed"
