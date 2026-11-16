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
    for needle in ("branches: [main]", "contents: write", "APP_VERSION", "gh release create", "Product changelog"):
        require(needle in wf, f"release workflow lost: {needle}")


TESTS = [test_version_is_semver, test_readme_changelog_leads_with_app_version, test_dashboard_shows_app_version,
         test_smoke_and_release_workflow_follow_app_version]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok", t.__name__)
    print(f"Versioning tests passed: {len(TESTS)} (APP_VERSION {app_version()})")
