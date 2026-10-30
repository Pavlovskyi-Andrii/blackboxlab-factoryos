"""T-594 left navigation regression: semantic groups, RU/UK/EN labels and route preservation.

Static checks. Every destination that existed before the regrouping (the before-map below, taken
from the pre-T-594 sidebar) must still be reachable from exactly one sidebar button with the same
handler. Each button belongs to a declared, collapsible section, carries a descriptive localized
hint, and every section heading / hint / menu control has a real EN, UK and RU translation. The
slide-out menu, remembered accordion state, breadcrumbs and keyboard handling are checked against
the markup, CSS and script. The inline script is syntax-checked with `node --check` when node is
available (required with FACTORYOS_REQUIRE_NODE=1).
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_locale_parity import FOREIGN_LETTERS, extract, parse_tables, require

HTML = Path(__file__).resolve().parent / "static" / "index.html"

# Before-map: label key -> click handler of the pre-T-594 flat sidebar (None = no handler).
BEFORE = {
    "nav.control": None,
    "approval.nav": "openApprovalStudio()",
    "publishing.nav": "openPublishingStudio()",
    "cycle.nav": "openAutonomousFactory()",
    "performance.nav": "openPerformanceStudio()",
    "experiment.nav": "openExperimentLab()",
    "brain.nav": "openContentBrain()",
    "discovery.nav": "openDiscoveryStudio()",
    "revideo.nav": "openRevideoStudio()",
    "finisher.nav": "openMediaFinisher()",
    "variant.nav": "S&&S.selectedJobId?openVariantStudio():toast(tr('toast.selectJob'))",
    "package.nav": "S&&S.selectedJobId?openPackageStudio():toast(tr('toast.selectJob'))",
    "nav.newJob": "openNew()",
    "nav.jobs": "document.querySelector('.jobs').scrollIntoView()",
    "nav.agents": "openAgentDirectory()",
    "nav.supervisor": "document.querySelector('.supervisor').scrollIntoView()",
    "nav.errors": "document.querySelector('.errorCenterCard').scrollIntoView()",
    "nav.pipeline": "document.querySelector('.pipelineCard').scrollIntoView()",
    "nav.build": "openBuildProgress()",
    "dc.nav": "openDelegationCenter()",
    "nav.outputs": "S&&S.selectedJobId?openJobOutputs(S.selectedJobId):toast(tr('toast.selectJob'))",
    "nav.analytics": "openFactoryIntelligence()",
    "nav.qa": "openReleaseReadiness()",
    "nav.settings": None,
}
GROUPS = ("overview", "create", "publish", "grow", "automation", "system")
# Live counters updated by other renderers must keep their ids inside the sidebar.
COUNTERS = ("brainNavCount", "discoveryNavCount", "revideoNavCount", "variantNavCount", "packageNavState", "buildNavPct")


def nav_markup(html):
    m = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', html, re.S)
    require(m is not None, "sidebar <nav class=\"nav\"> missing")
    return m.group(0), m.group(1)


def parse_items(inner):
    """Return the sidebar as an ordered list of ('section', group) and ('button', attrs, body)."""
    items = []
    for m in re.finditer(r'<div class="navSection"([^>]*)>.*?</div>|<button([^>]*)>(.*?)</button>', inner, re.S):
        if m.group(1) is not None:
            group = re.search(r'data-nav-group="([^"]+)"', m.group(1))
            require(group is not None, "nav section without data-nav-group")
            require('role="heading"' in m.group(1), f"nav section {group.group(1)} is not exposed as a heading")
            items.append(("section", group.group(1)))
        else:
            items.append(("button", m.group(2), m.group(3)))
    return items


def attr(attrs, name):
    m = re.search(name + r'="([^"]*)"', attrs)
    return m.group(1) if m else None


def check_routes_and_groups(items):
    buttons = [i for i in items if i[0] == "button"]
    sections = [i[1] for i in items if i[0] == "section"]
    require(tuple(sections) == GROUPS, f"nav sections out of order or missing: {sections}")
    require(items[0] == ("section", "overview"), "sidebar must open with the Overview section")
    seen = {}
    current = None
    for item in items:
        if item[0] == "section":
            current = item[1]
            continue
        _, attrs, body = item
        key = re.search(r'data-i18n="([^"]+)"', body)
        require(key is not None, "nav button without a localized label")
        key = key.group(1)
        require(key not in seen, f"duplicate nav destination {key}")
        handler = attr(attrs, "onclick")
        handler = handler.replace("&amp;", "&") if handler else None
        require(key in BEFORE, f"unexpected nav destination {key}; update the before/after map")
        require(handler == BEFORE[key], f"{key} handler changed: {handler!r} != {BEFORE[key]!r}")
        require(attr(attrs, "data-nav-group") == current, f"{key} is tagged {attr(attrs, 'data-nav-group')} but sits under {current}")
        nav_id = attr(attrs, "data-nav-id")
        require(nav_id, f"{key} has no data-nav-id")
        require(attr(attrs, "data-i18n-title") == f"navHint.{nav_id}", f"{key} has no descriptive hint navHint.{nav_id}")
        require('class="navIcon" aria-hidden="true"' in body, f"{key} lost its icon")
        seen[key] = current
    require(set(seen) == set(BEFORE), f"destinations lost from the sidebar: {sorted(set(BEFORE) - set(seen))}")
    require(len(buttons) == len(BEFORE), "sidebar button count changed")
    require(seen["nav.control"] == "overview" and 'class="active"' in buttons[0][1], "Control Room must stay first and active")
    for group in GROUPS:
        require(group in seen.values(), f"section {group} is empty")
    return [attr(b[1], "data-nav-id") for b in buttons]


def check_locales(tables, nav_ids):
    keys = [f"navGroup.{g}" for g in GROUPS] + ["navGroup.aria"] + [f"navHint.{n}" for n in nav_ids]
    keys += ["navMenu.open", "navMenu.close", "navCrumb.aria", "navCrumb.home"]
    for key in keys:
        en = tables["en"].get(key)
        require(en, f"en missing {key}")
        for lang in ("uk", "ru"):
            value = tables[lang].get(key)
            require(value, f"{lang} missing {key}")
            require(value != en, f"{lang} {key} is untranslated EN copy")
            require(not FOREIGN_LETTERS[lang].search(value), f"{lang} {key} uses letters from the other language: {value}")
    require(tables["uk"]["navGroup.create"] != tables["ru"]["navGroup.create"], "UK and RU section labels must be distinct copy")


def check_collapsible_groups(inner):
    """Each section is a navGroup: a heading with a real toggle button that controls its item list."""
    groups = re.findall(r'<div class="navGroup" data-nav-group="([^"]+)">', inner)
    require(tuple(groups) == GROUPS, f"navGroup wrappers out of order or missing: {groups}")
    for group in GROUPS:
        toggle = re.search(r'<button type="button" class="navSectionToggle" id="navHead-' + group + r'"([^>]*)>(.*?)</button>', inner, re.S)
        require(toggle is not None, f"section {group} has no toggle button")
        require('aria-expanded="true"' in toggle.group(1), f"section {group} toggle has no aria-expanded")
        require(f'aria-controls="navItems-{group}"' in toggle.group(1), f"section {group} toggle does not control its list")
        require(f"onclick=\"toggleNavGroup('{group}')\"" in toggle.group(1), f"section {group} toggle is not wired")
        require(f'data-i18n="navGroup.{group}"' in toggle.group(2), f"section {group} toggle lost its localized label")
        items = re.search(r'<div class="navItems" id="navItems-' + group + r'" role="group" aria-labelledby="navHead-' + group + r'">(.*?)</div></div>', inner, re.S)
        require(items is not None, f"section {group} has no labelled item group")
        tags = re.findall(r'data-nav-group="([^"]+)" data-nav-id', items.group(1))
        require(tags and set(tags) == {group}, f"section {group} list holds foreign items: {tags}")


def check_behaviour(html, script, css):
    # Slide-out: ~1/3 on capable viewports, usable adaptive width on phones, outside tap closes.
    require("width:clamp(320px,33.333vw,520px)" in css, "desktop slide-out menu is not ~1/3 of the viewport")
    require(".side.navOpen{width:min(86vw,360px)" in css, "phone drawer must use a usable adaptive width")
    require('id="navBackdrop" onclick="closeMobileNav()"' in html, "outside tap no longer closes the menu")
    require(".navBackdrop.open{opacity:1;pointer-events:auto}" in css.split("@media(min-width:701px){", 1)[-1], "backdrop not active on desktop")
    require('id="navExpandToggle" aria-controls="appSideNav" aria-expanded="false"' in html, "desktop expand toggle missing")
    require('id="mobileNavToggle" aria-label="Open navigation" aria-controls="appSideNav"' in html, "phone toggle lost aria-controls")
    require("content:attr(title)" in css, "expanded menu does not show one-line descriptions")
    require(".navGroup.collapsed .navItems{display:none}" in css, "collapsed groups are not hidden")
    require(".side:not(.navOpen) .navGroup.collapsed .navItems{display:grid}" in css, "icon rails must keep every destination visible")
    # The rail hide rule must out-rank the toggle's display:flex!important (.nav .navSection .navSectionToggle:not(.active)).
    require(".side:not(.navOpen) .nav .navSection .navSectionToggle{display:none!important}" in css, "section toggles leak into the icon rail")
    # Remembered accordion state, current section, breadcrumbs, keyboard.
    require("const NAV_COLLAPSED_KEY='factoryos_nav_collapsed'" in script, "accordion state is not remembered")
    require("localStorage.setItem(NAV_COLLAPSED_KEY" in script, "accordion state is not persisted")
    require("set.has(g)&&!box.querySelector('.navItems>button.active')" in script, "current group can be restored collapsed")
    require("b.setAttribute('aria-current','page')" in script, "current destination is not exposed via aria-current")
    require('id="navCrumbs" data-i18n-aria-label="navCrumb.aria"' in html, "breadcrumb landmark missing")
    require("function renderNavCrumbs(" in script and "tr('navGroup.'+group)" in script, "breadcrumbs do not show the section")
    require("syncNavToggles();restoreNavGroups();renderNavCrumbs();" in script, "applyLanguage does not refresh nav state")
    require("new MutationObserver(" in script and "setNavCurrent('control')" in script, "closing a studio does not return to Control Room")
    for key in ("'ArrowDown','ArrowUp','Home','End'", "e.key==='ArrowRight'||e.key==='ArrowLeft'", "e.key==='Escape'&&navMenuOpen()"):
        require(key in script, f"keyboard handling missing: {key}")
    require("e.target.closest('.navItems>button')" in script, "only destinations, not section toggles, may close the menu")
    require("window.addEventListener('resize',()=>{if(!mobileNavEnabled())closeMobileNav()})" not in script, "desktop resize must not force-close the menu")


def check_script_syntax(script):
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the script syntax check")
        print("SKIPPED inline script syntax check: node is not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "factoryos-ui.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, f"inline dashboard script has a syntax error: {result.stderr.strip()[:400]}")


def main():
    html = HTML.read_text(encoding="utf-8")
    nav, inner = nav_markup(html)
    check_collapsible_groups(inner)
    require('data-i18n-aria-label="navGroup.aria"' in nav, "sidebar has no localized accessible name")
    for counter in COUNTERS:
        require(f'id="{counter}"' in inner, f"live nav counter #{counter} missing from sidebar")
    nav_ids = check_routes_and_groups(parse_items(inner))
    script, i18n, _task_copy, _task_fn, assigns, _tr = extract(html)
    check_locales(parse_tables(i18n, assigns), nav_ids)
    require("[data-i18n-title]" in script and "el.title=tr(el.dataset.i18nTitle)" in script, "applyLanguage does not localize nav hints")
    require("[data-i18n-aria-label]" in script, "applyLanguage does not localize the nav aria-label")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(".navSection{" in css, "nav section styling missing")
    require(".side.navOpen .navSection{" in css, "open mobile drawer must show section labels")
    require(".nav button:focus-visible{" in css, "keyboard focus ring for nav buttons missing")
    check_behaviour(html, script, css)
    check_script_syntax(script)
    print(f"Navigation passed: {len(BEFORE)} destinations preserved across {len(GROUPS)} collapsible sections, "
          "slide-out menu, breadcrumbs, keyboard handling, EN/UK/RU labels and hints present")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
