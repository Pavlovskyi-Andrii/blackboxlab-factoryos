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
  if ! git cat-file -e "$before^{commit}" 2>/dev/null && ! git fetch --quiet --depth=1 origin "$before" 2>/dev/null; then
    # Not an error on purpose: the morning episode must still be rendered (it is the last commit of a daily push).
    echo "::warning::push base $before is not available; using the last commit only, earlier commits of this push are not rendered" >&2
    before=""
  fi
fi
[ -n "$before" ] || before=$(git rev-parse --quiet --verify HEAD~1 || true)
list=$(mktemp)
trap 'rm -f "$list"' EXIT
if [ -n "$before" ]; then
  # AMR: a renamed episode is listed under its new name.
  if ! git diff -z --name-only --diff-filter=AMR "$before" HEAD -- "$dir/*.json" > "$list" 2>/dev/null; then
    echo "::warning::could not compare $before with HEAD; rendering the newest episode only" >&2
    : > "$list"
  fi
fi
[ -s "$list" ] || find "$dir" -maxdepth 1 -name '*.json' -print0 | sort -z | tail -z -n 1 > "$list"
cat "$list"
