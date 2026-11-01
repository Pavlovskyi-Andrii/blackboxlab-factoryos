"""Dashboard screenshots for UI pull requests (evidence for T-594..T-597 DONE criteria).

Runs against a local FactoryOS started without a password or provider keys (zero spend).
Writes PNGs, report.json, an index.html contact sheet and a Markdown summary into UI_SHOTS_DIR.

Findings (horizontal overflow, uncaught page errors) are reported, not enforced: the job
fails only if the dashboard cannot be loaded or a scene cannot be captured at all.
"""
from __future__ import annotations

import html
import json
import os
import pathlib
import sys

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("UI_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUT = pathlib.Path(os.environ.get("UI_SHOTS_DIR", "ui-screenshots"))
SETTLE_MS = int(os.environ.get("UI_SETTLE_MS", "1500"))
LANGS = ("en", "uk", "ru")
VIEWPORTS = {
    "desktop-1440x900": {"width": 1440, "height": 900, "mobile": False},
    "tablet-1024x768": {"width": 1024, "height": 768, "mobile": False},
    "mobile-390x844": {"width": 390, "height": 844, "mobile": True},
}
# (scene, roadmap task it documents, JS run after load; None = page as loaded)
SCENES = (
    ("home", "T-594", None),
    ("menu-open", "T-594", "toggleMobileNav()"),
    ("build-progress", "T-595", "openBuildProgress()"),
    ("worker-center", "T-596", "openDelegationCenter()"),
    ("help-tip", "T-597", "(document.querySelector('.helpTip')||{click(){throw new Error('no .helpTip on page')}}).click()"),
)


def capture(page, lang: str, viewport: str, scene: str, action: str | None) -> dict:
    errors: list[str] = []
    page.on("pageerror", lambda exc: errors.append(str(exc)[:300]))
    page.goto(f"{BASE_URL}/{lang}", wait_until="load")
    page.wait_for_timeout(SETTLE_MS)
    action_error = ""
    if action:
        try:
            page.evaluate(f"async () => {{ await {action}; }}")
        except PlaywrightError as exc:
            action_error = str(exc).splitlines()[0][:300]
        page.wait_for_timeout(SETTLE_MS)
    overflow = page.evaluate("() => document.documentElement.scrollWidth - window.innerWidth")
    name = f"{lang}/{viewport}/{scene}.png"
    (OUT / lang / viewport).mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(OUT / name))
    return {"lang": lang, "viewport": viewport, "scene": scene, "file": name,
            "overflow_px": int(overflow), "page_errors": errors, "action_error": action_error}


def write_reports(results: list[dict]) -> int:
    findings = [r for r in results if r["overflow_px"] > 1 or r["page_errors"] or r["action_error"]]
    (OUT / "report.json").write_text(json.dumps({"base_url": BASE_URL, "results": results}, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
    rows = []
    for scene, task, _ in SCENES:
        rows.append(f"<h2>{html.escape(scene)} <small>({task})</small></h2><div class=row>")
        for r in (x for x in results if x["scene"] == scene):
            note = []
            if r["overflow_px"] > 1:
                note.append(f"horizontal overflow {r['overflow_px']}px")
            if r["action_error"]:
                note.append("action failed: " + r["action_error"])
            note.extend("page error: " + e for e in r["page_errors"])
            rows.append(
                f"<figure><a href='{r['file']}'><img src='{r['file']}' loading=lazy></a>"
                f"<figcaption>{r['lang']} · {r['viewport']}<br><b>{html.escape('; '.join(note))}</b></figcaption></figure>"
            )
        rows.append("</div>")
    (OUT / "index.html").write_text(
        "<!doctype html><meta charset=utf-8><title>FactoryOS UI screenshots</title>"
        "<style>body{font:14px sans-serif;margin:16px}.row{display:flex;flex-wrap:wrap;gap:12px}"
        "figure{margin:0;width:300px}img{width:100%;border:1px solid #ccc}b{color:#b3261e}</style>"
        + "".join(rows), encoding="utf-8")
    lines = [f"### UI screenshots: {len(results)} captured ({len(LANGS)} languages × {len(VIEWPORTS)} viewports × {len(SCENES)} scenes)",
             "Download the `ui-screenshots` artifact and open `index.html`.", ""]
    if findings:
        lines += [f"**{len(findings)} finding(s)** (reported, not enforced):", "", "| scene | lang | viewport | finding |", "|---|---|---|---|"]
        for r in findings:
            what = []
            if r["overflow_px"] > 1:
                what.append(f"overflow {r['overflow_px']}px")
            if r["action_error"]:
                what.append("action failed")
            if r["page_errors"]:
                what.append(f"{len(r['page_errors'])} page error(s)")
            lines.append(f"| {r['scene']} | {r['lang']} | {r['viewport']} | {', '.join(what)} |")
    else:
        lines.append("No horizontal overflow, page errors or failed actions.")
    summary = "\n".join(lines) + "\n"
    (OUT / "summary.md").write_text(summary, encoding="utf-8")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(summary)
    print(summary)
    return len(findings)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for viewport, spec in VIEWPORTS.items():
                context = browser.new_context(
                    viewport={"width": spec["width"], "height": spec["height"]},
                    is_mobile=spec["mobile"], has_touch=spec["mobile"],
                )
                try:
                    for lang in LANGS:
                        for scene, _task, action in SCENES:
                            page = context.new_page()
                            try:
                                results.append(capture(page, lang, viewport, scene, action))
                            finally:
                                page.close()
                finally:
                    context.close()
        finally:
            browser.close()
    write_reports(results)
    expected = len(LANGS) * len(VIEWPORTS) * len(SCENES)
    if len(results) != expected:
        print(f"captured {len(results)} of {expected} scenes", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
