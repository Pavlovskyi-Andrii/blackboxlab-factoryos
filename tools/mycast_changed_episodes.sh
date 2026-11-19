#!/usr/bin/env bash
# Prints the MyCast episode files a push changed, NUL-separated; the newest episode when it changed none.
# Usage: tools/mycast_changed_episodes.sh [BEFORE_SHA]   (BEFORE_SHA = github.event.before; empty or zeros = unknown)
# The whole pushed range counts, not only the last commit: a push can carry several commits.
# NUL-separated so that a file name with spaces or glob characters reaches the renderer unchanged.
set -euo pipefail
dir=docs/prototypes/mycast/episodes
before="${1:-}"
if [ -n "$before" ] && [ -z "${before//0/}" ]; then before=""; fi
if [ -n "$before" ]; then
  git cat-file -e "$before^{commit}" 2>/dev/null || git fetch --quiet --depth=1 origin "$before" 2>/dev/null || before=""
fi
[ -n "$before" ] || before=$(git rev-parse --quiet --verify HEAD~1 || true)
list=$(mktemp)
trap 'rm -f "$list"' EXIT
if [ -n "$before" ]; then
  git diff -z --name-only --diff-filter=AM "$before" HEAD -- "$dir/*.json" > "$list" 2>/dev/null || : > "$list"
fi
[ -s "$list" ] || find "$dir" -maxdepth 1 -name '*.json' -print0 | sort -z | tail -z -n 1 > "$list"
cat "$list"
