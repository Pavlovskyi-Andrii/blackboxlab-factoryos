"""T-VERSION (owner 2026-11-16): one FactoryOS version everywhere.

`APP_VERSION` in app.py is the only version. The README changelog's first entry, the dashboard sidebar fallback and
the release workflow must agree with it; the header and the sidebar read it from /api/status at runtime.

Run: python test_versioning.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SEMVER = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
HEADING = re.compile(r"^### (v\d+\.\d+(?:\.\d+)?) — ", re.M)


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def app_version() -> str:
    m = re.search(r'^APP_VERSION = "([^"]+)"', (ROOT / "app.py").read_text(encoding="utf-8"), re.M)
    require(m, "APP_VERSION not found in app.py")
    return m.group(1)


def key(v: str) -> tuple:
    parts = [int(x) for x in v.lstrip("v").split(".")]
    return tuple(parts + [0] * (3 - len(parts)))


def test_version_is_semver():
    require(SEMVER.fullmatch(app_version()), f"APP_VERSION must be vMAJOR.MINOR.PATCH, got {app_version()!r}")


def test_readme_changelog_leads_with_app_version():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    log = readme.split("## Product changelog", 1)
    require(len(log) == 2, "README has no '## Product changelog' section")
    versions = HEADING.findall(log[1])
    require(versions and versions[0] == app_version(),
            f"README changelog starts with {versions[:1]}, APP_VERSION is {app_version()}: add the release entry")
    require(len(versions) == len(set(versions)), "a version appears twice in the changelog")
    require(versions == sorted(versions, key=key, reverse=True), f"changelog is not newest-first: {versions[:8]}")


def test_dashboard_shows_app_version():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    badge = re.findall(r'<span class="version" id="appVersion">([^<]*)</span>', html)
    require(badge == [app_version()], f"sidebar badge fallback {badge} != {app_version()}")
    require("const av=$('#appVersion');if(av&&S.version)av.textContent=S.version;" in html,
            "sidebar badge must follow /api/status version at runtime")
    require("(S.version||'FactoryOS')" in html, "header build stamp must show /api/status version")
    require(not re.search(r'class="version"[^>]*>v(?!' + re.escape(app_version()[1:]) + r')', html),
            "another hard-coded version badge is on the dashboard")


def test_smoke_and_release_workflow_follow_app_version():
    smoke = (ROOT / "smoke_tests.py").read_text(encoding="utf-8")
    require(f'app.APP_VERSION=="{app_version()}"' in smoke, "smoke_tests.py pins a different version")
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for needle in ("branches: [main]", "contents: write", "APP_VERSION", "tools/release_publish.sh", "Product changelog"):
        require(needle in wf, f"release workflow lost: {needle}")
    script = (ROOT / "tools" / "release_publish.sh").read_text(encoding="utf-8")
    require("gh release create" in script and "git ls-remote --tags origin" in script, "publish script lost its core")
    # Codex review on #396: a manual backfill must never tag a past version on today's main, and no run may be
    # dropped by a concurrency group (GitHub keeps one pending run per group).
    require('[ -n "$TARGET" ] ||' in wf and "release_publish.sh strict" in wf, "manual backfill without target must fail")
    require("\nconcurrency:" not in wf, "a concurrency group can drop a pending release run")


def test_backfill_list_matches_changelog():
    """Every version in .github/release-backfill.txt has a changelog entry and a full SHA (the workflow releases it)."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8").split("## Product changelog", 1)[1]
    versions = set(HEADING.findall(readme))
    path = ROOT / ".github" / "release-backfill.txt"
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tag, sha = line.split()
        require(tag in versions, f"backfill {tag} has no README changelog entry")
        require(re.fullmatch(r"[0-9a-f]{40}", sha), f"backfill {tag} needs a full commit SHA")
        require(tag != app_version(), "the current version is released by the push run, not the backfill list")
    wf = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    require(".github/release-backfill.txt" in wf and 'release_publish.sh strict "$tag" "$sha"' in wf,
            "release workflow lost the backfill step")


SHA_A, SHA_B = "a" * 40, "b" * 40
GIT_STUB = r"""#!/bin/bash
S="$STUB_STATE"
case "$1" in
  ls-remote) shift 2; for ref in "$@"; do awk -v r="$ref" '$2==r' "$S/tags"; done ;;
  merge-base) [ -f "$S/notmain" ] && exit 1; exit 0 ;;
  *) exit 0 ;;
esac
"""
GH_STUB = r"""#!/bin/bash
S="$STUB_STATE"
if [ "$1 $2" = "release view" ]; then grep -qx "$3" "$S/releases"; exit $?; fi
if [ "$1 $2" = "release create" ]; then
  tag="$3"; shift 3; target=""
  while [ $# -gt 0 ]; do [ "$1" = "--target" ] && target="$2"; shift; done
  echo "create $tag target=${target:-existing}" >> "$S/log"
  if [ -f "$S/race" ]; then
    echo "$(cat "$S/race") refs/tags/$tag" >> "$S/tags"; echo "$tag" >> "$S/releases"; exit 1
  fi
  [ -n "$target" ] && echo "$target refs/tags/$tag" >> "$S/tags"
  echo "$tag" >> "$S/releases"; exit 0
fi
exit 0
"""


def run_publish(mode, sha, *, tags=(), releases=(), race=None, notmain=False):
    """Run tools/release_publish.sh against stubbed git/gh holding a fake remote: (exit code, create log)."""
    import os
    import subprocess
    import tempfile
    state = Path(tempfile.mkdtemp(prefix="factoryos-release-"))
    stub = state / "bin"
    stub.mkdir()
    for name, body in (("git", GIT_STUB), ("gh", GH_STUB)):
        (stub / name).write_text(body)
        (stub / name).chmod(0o755)
    (state / "tags").write_text("".join(f"{c} refs/tags/v5.9.0\n" for c in tags))
    (state / "releases").write_text("".join(f"{r}\n" for r in releases))
    (state / "log").write_text("")
    if race:
        (state / "race").write_text(race)
    if notmain:
        (state / "notmain").write_text("")
    env = {**os.environ, "PATH": f"{stub}:{os.environ['PATH']}", "STUB_STATE": str(state)}
    r = subprocess.run(["bash", str(ROOT / "tools" / "release_publish.sh"), mode, "v5.9.0", sha, "T", "/dev/null"],
                       env=env, capture_output=True, text=True, timeout=30)
    return r.returncode, (state / "log").read_text().strip()


def test_release_publish_guards():
    """Codex review on #397: every conflict case is checked against the remote tag, with behaviour, not substrings."""
    code, log = run_publish("strict", SHA_A)
    require(code == 0 and log == f"create v5.9.0 target={SHA_A}", f"fresh backfill: {code} {log}")
    code, log = run_publish("strict", SHA_A, tags=[SHA_A], releases=["v5.9.0"])
    require(code == 0 and log == "", f"matching existing release must be skipped: {code} {log}")
    code, _ = run_publish("strict", SHA_A, tags=[SHA_B], releases=["v5.9.0"])
    require(code == 1, "existing release on the wrong commit must fail")
    code, log = run_publish("strict", SHA_A, tags=[SHA_B])
    require(code == 1 and log == "", "a remote-only tag on another commit must fail before any create")
    code, log = run_publish("strict", SHA_A, tags=[SHA_A])
    require(code == 0 and log == "create v5.9.0 target=existing", f"remote tag without release: {code} {log}")
    code, _ = run_publish("strict", SHA_A, race=SHA_A)
    require(code == 0, "a concurrent run that released the same commit counts as done")
    code, _ = run_publish("strict", SHA_A, race=SHA_B)
    require(code == 1, "a concurrent create on another commit must fail")
    code, _ = run_publish("strict", SHA_A, releases=["v5.9.0"])
    require(code == 1, "a release whose tag is missing must fail")
    code, log = run_publish("strict", SHA_A, notmain=True)
    require(code == 1 and log == "", "a commit that is not on main must fail")
    code, _ = run_publish("strict", "abc")
    require(code == 1, "a short SHA must fail")
    code, log = run_publish("current", SHA_A, tags=[SHA_B], releases=["v5.9.0"])
    require(code == 0 and log == "", "current version already released on an older commit is done (README-only push)")


TESTS = [test_release_publish_guards, test_backfill_list_matches_changelog, test_version_is_semver, test_readme_changelog_leads_with_app_version, test_dashboard_shows_app_version,
         test_smoke_and_release_workflow_follow_app_version]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok", t.__name__)
    print(f"Versioning tests passed: {len(TESTS)} (APP_VERSION {app_version()})")
