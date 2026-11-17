#!/usr/bin/env bash
# Publish one FactoryOS GitHub Release (T-VERSION). Used by .github/workflows/release.yml; tested by test_versioning.py.
#
#   release_publish.sh strict|current TAG SHA TITLE NOTES_FILE
#
# strict  (backfill): the tag must end up on exactly SHA. An existing tag or release on another commit fails.
# current (push run): the version in app.py. An existing release is done whatever commit it is on (a later push that
#                     only edits README must not re-tag); a missing release goes on the existing tag, or on SHA.
# The tag is resolved on the remote (git ls-remote), never from local refs, and re-checked after a failed create
# so a concurrent run that won the race is accepted only if its tag is on the right commit.
set -euo pipefail
mode="$1" tag="$2" sha="$3" title="$4" notes="$5"

remote_tag_commit() {   # peeled commit of the remote tag, or empty when it does not exist
  local out peeled plain
  out="$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")"
  peeled="$(printf '%s\n' "$out" | awk -v r="refs/tags/$tag^{}" '$2==r {print $1}')"
  plain="$(printf '%s\n' "$out" | awk -v r="refs/tags/$tag" '$2==r {print $1}')"
  printf '%s' "${peeled:-$plain}"
}

check_commit() {        # strict mode: the tag must point at SHA
  local got="$1"
  if [ "$mode" = strict ] && [ "$got" != "$sha" ]; then
    echo "tag $tag is on $got, expected $sha"; exit 1
  fi
}

case "$sha" in *[!0-9a-f]*|"") echo "sha must be a full commit SHA"; exit 1;; esac
[ "${#sha}" -eq 40 ] || { echo "sha must be a full 40-char SHA"; exit 1; }
git merge-base --is-ancestor "$sha" origin/main || { echo "$sha ($tag) is not on main"; exit 1; }

latest=()
[ "$mode" = strict ] && latest=(--latest=false)
existing="$(remote_tag_commit)"

if [ -n "$existing" ]; then
  check_commit "$existing"
  if gh release view "$tag" >/dev/null 2>&1; then echo "Release $tag already exists on $existing"; exit 0; fi
  gh release create "$tag" --verify-tag --title "$title" --notes-file "$notes" "${latest[@]}"
  exit 0
fi

if gh release view "$tag" >/dev/null 2>&1; then
  echo "release $tag exists but its tag is missing on the remote"; exit 1
fi
if ! gh release create "$tag" --target "$sha" --title "$title" --notes-file "$notes" "${latest[@]}"; then
  # A parallel run may have created it first: accept only a release whose tag is on the right commit.
  existing="$(remote_tag_commit)"
  [ -n "$existing" ] || { echo "release $tag was not created"; exit 1; }
  check_commit "$existing"
  [ "$existing" = "$sha" ] || [ "$mode" = current ] || exit 1
  gh release view "$tag" >/dev/null 2>&1 || { echo "tag $tag exists but no release"; exit 1; }
fi
created="$(remote_tag_commit)"
[ -n "$created" ] || { echo "tag $tag missing after create"; exit 1; }
[ "$mode" = current ] || check_commit "$created"
echo "Release $tag published on $created"
