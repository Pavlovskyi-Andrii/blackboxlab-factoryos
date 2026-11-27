# T-594 left navigation: before / after map

Source of truth for the regression: `test_navigation.py` (`BEFORE` dict + group checks).
None of the 24 destinations was removed, renamed or re-wired. Every handler is byte-identical to the pre-T-594 sidebar.

## Before (pre-T-594, flat list of 24 buttons, no grouping)

Control Room · Review · Publish · Autopilot · Performance · Experiments · Content Brain · Discovery ·
Revideo · Media Finisher · Variants · Package · New Job · Jobs · Agents · Supervisor · Error Center ·
Pipeline · Build Progress · Workers · Outputs · Analytics · Release QA · Settings

## After (six collapsible semantic groups)

| Group (EN / UK / RU) | Destination | Handler (unchanged) |
|---|---|---|
| Overview / Огляд / Обзор | Control Room | none → scroll to top (listener, not handler) |
| | Pipeline | scroll `.pipelineCard` |
| | Supervisor | scroll `.supervisor` |
| | Error Center | scroll `.errorCenterCard` |
| Create content / Створення контенту / Создание контента | New Job | `openNew()` |
| | Jobs | scroll `.jobs` |
| | Discovery | `openDiscoveryStudio()` |
| | Revideo | `openRevideoStudio()` |
| | Content Brain | `openContentBrain()` |
| | Media Finisher | `openMediaFinisher()` |
| | Variants | `openVariantStudio()` if a job is selected, else toast |
| | Package | `openPackageStudio()` if a job is selected, else toast |
| | Outputs | `openJobOutputs(selectedJobId)` if a job is selected, else toast |
| Review & publish / Перевірка та публікація / Проверка и публикация | Review | `openApprovalStudio()` |
| | Publish | `openPublishingStudio()` |
| Growth & learning / Зростання та навчання / Рост и обучение | Performance | `openPerformanceStudio()` |
| | Analytics | `openFactoryIntelligence()` |
| | Experiments | `openExperimentLab()` |
| Automation & team / Автоматизація та команда / Автоматизация и команда | Autopilot | `openAutonomousFactory()` |
| | Agents | `openAgentDirectory()` |
| | Workers | `openDelegationCenter()` |
| System / Система / Система | Build Progress | `openBuildProgress()` |
| | Release QA | `openReleaseReadiness()` |
| | Settings | none (unchanged; no settings page exists yet) |

Live counters stay inside their buttons: `discoveryNavCount`, `revideoNavCount`, `brainNavCount`,
`variantNavCount`, `packageNavState`, `buildNavPct`.

## Behaviour by viewport

| Viewport | Closed state | Open state (`»` / `☰`) |
|---|---|---|
| ≥ 901px (e.g. 1440×900) | 228px sidebar with labels; group headings collapse/expand (remembered) | slide-out `clamp(320px, 33.333vw, 520px)` with labels + one-line descriptions, backdrop |
| 701–900px (e.g. 768×1024) | 72px icon rail, all icons visible, groups as dividers, native localized tooltips | same slide-out as desktop |
| ≤ 700px (e.g. 390×844) | 46px icon rail + floating ☰ | drawer `min(86vw, 360px)`, 13px labels + descriptions |

Closing the menu: backdrop tap/click, Escape (focus returns to the toggle), or choosing a destination.
Section toggles do not close it.

Keyboard: ↑/↓/Home/End move focus across the sidebar buttons. ←/→ collapse or expand the focused section.
Enter/Space activate. Visible focus ring on every nav button.

Current location: `.active` + `aria-current="page"` on the destination, a highlighted group heading, and
header breadcrumbs `⌂ › Section › Destination`. A studio is current only while its overlay is open. Once it
closes, the location returns to Control Room.

## Evidence status

- Static + script-syntax regression: `python test_navigation.py`. In CI it runs inside the existing
  "EN/UK/RU locale parity regression" step: `test_locale_parity.py` calls it, because the worker token cannot edit the workflow.
- Behaviour run (increment 3): the real sidebar markup and the real nav script run in Node against a minimal DOM.
  It covers 48 taps (24 destinations, with and without a selected job), the slide-out at 1440/1024/800/390px,
  outside tap, Escape and destination close, the keyboard order, remembered sections, breadcrumbs, and EN/UK/RU rendering.
  A tap is simulated as a click event. This is not a real touch device and does not render CSS. Visibility follows the pinned CSS rules.
- Desktop/mobile screenshots: **partly captured**. The #452 session (T-732, a cloud runner with a browser, v5.19.1)
  committed real captures of the current menu: `docs/screenshots/t-732/home-1440-en.png` (desktop sidebar closed:
  labels, collapsible groups, breadcrumbs), `menu-open-390-en.png` (phone drawer open with descriptions) and
  `home-390-{en,uk,ru}.png` (phone, closed). Still missing: the desktop slide-out open at 1440×900, and one open-menu
  scene in UK or RU. `first-screen-metrics.json` shows that the T-732 run also captured EN 1440×900 `menu-open`
  (0 px overflow, 0 page errors), but that PNG was not committed. The EC2 worker still has no Chromium/Playwright (re-checked 2026-11-27).
- CI-gated PR: as of 2026-11-01, increments 1–3 and the re-check (`aac3b8c`) are on `origin/main` (`c2879b9`),
  merged through the normal PR flow. The agent run had no network/`gh`, so it did not see the CI result of those merges.
- Re-check 2026-11-01: there is still no browser on the worker (no Chromium/Chrome/Firefox, and no
  Playwright/Selenium/pyppeteer in the venv). Steps 1–2 below are still open. Step 3 is done if CI on the merge was green.

### Remaining steps (owner or a runner with a browser + GitHub access)

1. Serve the dashboard (`uvicorn app:app`, `FACTORY_PASSWORD=""`) and capture the two missing scenes: 1440×900 with
   the `»` slide-out open (EN), and 390×844 with the menu open in UK or RU. Save them under `docs/roadmap/T-594_screens/`.
   The CI `ui-screenshots` artifact (`{lang}/desktop-1440x900/menu-open.png`) also covers this if a run is green.
2. On a touch device or in device emulation, check that tapping the backdrop closes the menu and that ☰ opens it.
3. Open the PR `autopilot/aws-worker` → `main`, wait for green CI on the head and merge it. CI runs `test_navigation.py`
   inside the locale parity step.
