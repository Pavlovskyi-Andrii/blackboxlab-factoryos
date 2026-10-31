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
- Desktop/mobile screenshots: **not captured yet**. No runner session so far has had a browser
  (no Chromium/Playwright on the EC2 worker).
- CI-gated PR: **not opened yet**. As of 2026-10-31 only increment 1 (#66) is on `origin/main`.
  Increments 2–3 are only on `autopilot/aws-worker`.

### Remaining steps (owner or a runner with a browser + GitHub access)

1. Serve the dashboard (`uvicorn app:app`, `FACTORY_PASSWORD=""`) and capture `static/index.html` at
   1440×900 and 390×844, menu closed and open, in EN plus one of UK/RU. Save them under `docs/roadmap/T-594_screens/`.
2. On a touch device or in device emulation, check that tapping the backdrop closes the menu and that ☰ opens it.
3. Open the PR `autopilot/aws-worker` → `main`, wait for green CI on the head and merge it. CI runs `test_navigation.py`
   inside the locale parity step.
