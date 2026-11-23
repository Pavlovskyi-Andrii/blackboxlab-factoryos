# FactoryOS current-state UX audit (T-727, issue #452 §4)

Date: 2026-11-23 · Author: Claude (interactive session) · Version audited: `v5.18.1` (`main` at `9e26cbc`).

## 1. What was and was not observed

| Source | Status |
|---|---|
| Local FactoryOS started from `main` with an empty `DATA_DIR`, no password, no provider keys (the same fixture the CI `ui-screenshots` job uses) | **Observed**: 72 screenshots, 4 widths × 3 languages × 6 scenes, with first-screen measurements |
| Production `https://blackboxlab-factoryos.onrender.com` | `/health` answers `v5.18.1`. Owner pages and APIs answer 401 to this session. **The owner's real logged-in screen was not observed.** Authentication was not bypassed |
| Source code (`static/index.html`, `app.py`, feature modules) | Read |
| Earlier review `docs/reviews/ui-review-2026-11.md` | Used as history; its findings are not repeated unless still present |

Consequence: numbers below describe the product with **no real data**. With the owner's data the page is longer, not
shorter (more jobs, more projects, more questions), so the findings on length and density are a lower bound. Findings
that depend on real data (status contradictions between live workers) are marked "fixture only".

Reproduce:
```bash
DATA_DIR=/tmp/fos-ui FACTORY_PASSWORD="" FACTORY_LLM_API_KEY="" python -m uvicorn app:app --port 8000 &
UI_AUDIT=1 UI_EXTRA_VIEWPORTS=1 UI_SHOTS_DIR=/tmp/shots python tools/ui_screenshots.py
```
Screenshots: `docs/screenshots/t-727/`. All measurements: `docs/screenshots/t-727/first-screen-metrics.json`.

## 2. Inventory

### 2.1 Pages (routes that return HTML)
| Route | What it is | Reached from |
|---|---|---|
| `/`, `/en`, `/uk`, `/ru` | The dashboard: one page, `static/index.html` | Login |
| `/login`, `/login/recover`, `/logout`, `/auth/google`, `/guest` | Access | — |
| `/relay` | Relay ticket view | Links in Telegram and the dashboard |
| `/learn`, `/learn/view/{id}` | Learning section and sandboxed prototypes | Navigation → Learning |
| `/static/mvp-factory/` (`index`, `launchpad`, `evolution`, `faceless-crm`, `release-guardian`) | MVP Builder pages | Navigation → MVP Builder |
| `/static/social/`, `/static/linkedin/`, `/static/olx/`, `/static/sheets/`, `/static/surfer/` | Owner pages for publishing, sheets and the Surfer | Cards and runbooks; **not in the navigation** |
| `/static/decision-memory/`, `/static/mybrief/` | MVP pilots | MVP Builder |
| `/mycast`, `/mycast/u/{slug}`, `/mycast/e/{token}`, `/mycast/demo/{name}`, `/factory/mycast-demos`, `/privacy`, `/terms` | MyCast public pages | Public |

The application also has 381 API routes. The largest groups: `/api/mycast` 26, `/api/jobs` 24, `/api/mvp-factory` 24,
`/api/factory/surfer` 22, `/api/relay` 15, `/api/factory/social` 13.

### 2.2 Dashboard navigation: 9 groups, 31 items
"Opens" is how the item behaves: **scroll** = jumps to a card further down the same page; **drawer** = an overlay panel;
**page** = another HTML page. No item has its own URL, so no screen of the dashboard can be linked or bookmarked
(the only exception is `/#vault`).

| Group | Items (opens) |
|---|---|
| Overview | Control Room (page top), Pipeline (drawer), Supervisor (scroll), Error Center (scroll) |
| Create content | New Job (drawer), Jobs (scroll), Discovery, Revideo, Content Brain, Media Finisher, Variants, Package, Outputs (drawers; three need a selected job) |
| Review & publish | Review (drawer), Publish (drawer) |
| Growth & learning | Performance, Analytics, Experiments (drawers) |
| Automation & team | Autopilot, Agents, Workers (drawers), Browser agent (scroll) |
| MVP Builder | Projects (page), MyCast podcast (page) |
| Mods & skills | Connected (scroll) |
| Learning | Learning (page) |
| System | Build Progress, Release QA (drawers), Owner console, Brand strategy (scroll), Settings |

### 2.3 What the Control Room page contains, top to bottom
Seen in `home-full-1440-en.png`: (1) "Ready to run" five-step strip; (2) four counters; (3) Agent Office scene with 19
agent cards, beside Connections; (4) Content / Promotion jobs and Selected Job; (5) MVP Builder projects; (6) Open
questions; (7) Browser agent; (8) Owner console; (9) Brand strategy with content plan; (10) Connected features and
skills; (11) Factory Supervisor and Design Partner; (12) Operations / Error Center; (13) Worker Results and Handoffs.
Thirteen blocks on one page.

### 2.4 Where the owner's own actions live
| What the owner must see | Where it is today | Actions from the first screen |
|---|---|---|
| Tasks waiting for the owner ("You need to do: 19" in the fixture) | Navigation → Automation & team → Workers → top of the drawer | 2 (3 on a phone: open menu first) |
| Open questions from MVP projects | Sixth block of the page | Scroll about 5 screens on a phone |
| Approvals before publishing | Review drawer; social weekly plan on `/static/social/` (not in navigation) | 1; the social plan has no navigation entry |
| What is being worked on now | Build Progress drawer; Agent Office scene; lane board inside Workers | 1–2 |
| Morning brief | Telegram only | Not in the dashboard |
| Results of a product (MyCast registrations, activations) | Owner console → "MyCast listeners" tab; Launchpad funnel on a separate page | Scroll + 1 |

## 3. First-screen measurements (local fixture, English, "home" scene)

| Measure | 1440×900 | 1024×768 | 768×1024 | 390×844 |
|---|---|---|---|---|
| Page length, in screens | 8.6 | 12.5 | 9.7 | 19.2 |
| Controls on the first screen / on the page | 62 / 302 | 42 / 301 | 52 / 276 | 30 / 273 |
| Controls smaller than 32 px on the first screen | 21 | 14 | 11 | 9 |
| Text pieces on the first screen below 12 px / all | 281 / 386 (73 %) | 77 / 150 (51 %) | 203 / 290 (70 %) | 32 / 68 (47 %) |
| Smallest font on the first screen | 7 px | 8 px | 8 px | 7 px |
| Words on the whole page | 4,694 | 5,038 | 4,946 | 3,983 |
| Horizontal overflow, JavaScript errors | none | none | none | none |

Headings a person meets on the first screen: "Blackbox Lab — FactoryOS", "Ready to run", "Agent Office — Your AI team
working together", "Connections". No heading says what the product is for or what the person should do next.

## 4. The questions of issue §4

| Question | Answer from evidence | Evidence |
|---|---|---|
| First 10 seconds: can a new person say what the product is for? | **Unlikely — expert judgement, not a user test.** The only description is a 12 px subtitle "AI content production control room". It describes one of at least five product areas (content, MVP Builder, MyCast, Relay/workers, Surfer). The largest element is a decorative office scene | `home-1440-en.png` |
| First 30 seconds: can the person start a goal without technical settings? | **No goal concept exists.** The primary button is "New Job" (a video production job). "Grow MyCast" cannot be started anywhere as one action | Code: no `goal` entity (benchmark §7) |
| One primary action per context? | No. The first screen has 62 controls on desktop; two blue buttons compete (step 3 "Run Factory" and "New Job") | Metrics |
| What is happening now / finished / blocked / needs approval? | Present, but in five places with five vocabularies (§5, D-04) | — |
| Real state vs demonstration | The Agent Office shows 19 named agents "standing by" with a decorative scene whether or not anything runs. The counters are real ("1 agent runs", "0 tokens"). A fresh install shows two sample jobs without a "sample" label | `home-1440-en.png`; fixture only for the sample jobs |
| Evidence, tokens, time, cost, the agent behind a result | Available in drawers (Agents, Proof, Build Progress). Cost: one counter "USD 0.0000 / USD 10.0000"; no cost per goal | — |
| Mobile navigation reachability | Works: ☰ opens a labelled menu with hints. Closed, it is a 46 px rail of 15+ icons without labels | `menu-open-390-en.png`, `home-390-en.png` |
| RU/UK/EN | Parity is enforced by `test_locale_parity.py`. Visible leftovers: "Share Viewer" stays English in the Russian header; product names stay English by design | `home-390-ru.png` |
| Keyboard, focus, reduced motion | `:focus-visible` rules exist (15), `prefers-reduced-motion` is honoured in 3 places, 54 `aria-label`s. A full keyboard pass was **not** done in this audit | Source |
| Status consistency | See D-04 | — |
| Connections clarity | The card separates "Publishing", "CRM / Growth", "AI models and agents" and says "An AI provider and worker are separate connections". Issue #47 remains open for the provider / worker / host distinction | `home-1440-en.png` |
| Onboarding, zero state, failure | The five-step strip is the only onboarding and covers content production only. Zero states exist per card ("No browser tasks yet"). There is no first-run explanation of the product | — |
| Sensitive infrastructure as primary content | None seen on the first screen. Worker host details are inside drawers | — |

## 5. Defects

Severity: **P0** = stops the owner from understanding or acting; **P1** = slows or misleads; **P2** = polish.
"Kind": O = observed on the fixture, S = from source, E = expert judgement.

| ID | Sev. | Defect | Kind | Evidence |
|---|---|---|---|---|
| D-01 | P0 | The first screen does not say what FactoryOS is for or what to do next. The subtitle names one product area of five | O, E | `home-1440-en.png`, `home-390-en.png` |
| D-02 | P0 | Things that wait for the owner are not on the first screen. The fixture has 19 owner tasks and 2 open questions; the first screen shows none of them, and no count | O | `worker-center-768-en.png`, §2.4 |
| D-03 | P0 | The product has no "goal". Work can be started only as a production job or an MVP project, so "grow MyCast" has no entry point and no single page | S | Benchmark §7 |
| D-04 | P1 | Five status vocabularies on one screen: "Factory online / No active run" (sidebar), "19 agents · standing by", "Offline" (Claude, ChatGPT, Gemini), per-agent "Idle · Auto → ChatGPT · auth pending", and the step strip "Ready to run". A reader cannot tell whether anything is working | O | `home-1440-en.png` |
| D-05 | P1 | The page is 8.6 screens long on desktop and 19.2 on a phone, with 13 unrelated blocks. Reaching "Open questions" on a phone takes about 5 screens of scrolling | O | Metrics, `home-full-1440-en.png` |
| D-06 | P1 | Small text: 73 % of first-screen text on desktop is below 12 px; the smallest is 7 px. Agent cards, counters' captions and Connections rows are 8–11 px | O | Metrics |
| D-07 | P1 | The largest element on the first screen is the Agent Office illustration. It is the technical view the owner asked to move out of first place, and it looks "live" while idle | O, E | `home-1440-en.png` |
| D-08 | P1 | No screen has an address. Eight navigation items scroll the long page, twenty open drawers. Nothing can be linked from Telegram, a runbook or a brief to "the approval that waits for you" | S | §2.2 |
| D-09 | P1 | Owner pages outside the navigation: social plan, LinkedIn, OLX, Sheets, Surfer are linked only from Owner Desk runbooks, not from the dashboard menu | S | §2.1 |
| D-10 | P1 | Results of the owner's products are not on the first screen. MyCast registrations sit in a tab of the Owner console, the funnel on a separate Launchpad page, and visits or payments are not measured at all | S | Benchmark §7 |
| D-11 | P1 | On a phone the first screen is used by the header (title, three language buttons, Refresh, Share Viewer, New task) and the five-step strip; the owner's own status starts on the second screen | O | `home-390-ru.png` |
| D-12 | P2 | 21 of 62 first-screen controls on desktop are smaller than 32 px (9 of 30 on a phone) | O | Metrics |
| D-13 | P2 | The phone rail shows 15+ icons without labels when the menu is closed; several look alike (two "lightning" icons, two "list" icons) | O | `home-390-en.png` |
| D-14 | P2 | A fresh install shows two sample jobs and a sample content plan without a "sample" mark | O (fixture only) | `home-full-1440-en.png` |
| D-15 | P2 | "Share Viewer" is not translated in the Russian and Ukrainian headers | O | `home-390-ru.png`, `home-390-uk.png` |
| D-16 | P2 | "Settings" is a navigation item without a page | S | §2.2 |
| D-17 | P2 | Design tokens: 12 colour variables, no spacing or type scale, about ten different breakpoints (480–1500 px). New screens cannot be made consistent by reuse alone | S | `static/index.html` `:root` |

Not defects, kept as they are: no horizontal overflow at any width; no JavaScript errors; the phone menu with hints;
locale parity tests; per-card zero states; the separation of provider and worker in Connections; the Workers drawer
that opens with "You need to do" before technical detail.

## 6. Baseline for the tasks of issue §8

Paths are counted from the navigation structure and the code, not clicked through with real data (the fixture has no
MyCast experiment). "No path" means the task cannot be completed at all.

| Task | Shortest path today | Baseline |
|---|---|---|
| T1 explain the purpose; find "start a goal" | Read the subtitle; no "goal" exists | Purpose: unmeasured (needs people). Start a goal: **no path** |
| T2 start a MyCast growth goal and find its status | — | **No path** |
| T3 find and review a draft landing variant | Navigation → MVP Builder → Projects → MyCast → experiments | About 4 actions, across 2 pages |
| T4 approve or reject and understand the consequence | Experiment preview approval on the MVP page; wording of consequences not checked with users | About 5 actions; comprehension unmeasured |
| T5 tell a lead from a click from a payment | Sign-ups: Owner console tab. Clicks: not measured. Payments: not implemented | **Partly no path** |
| T6 expert: agent history, time, tokens, cost, MCP | Agents drawer / Proof / Build Progress | 1–2 actions; works |
| T7 handle a blocked or failed task | Workers drawer → task → runbook → Retry | About 3 actions; works |

Times and success rates with people: **unmeasured**. They will be measured in T-728 with the owner and the 3–4 people he
brings, on the prototype and, for comparison, on these current screens.

## 7. Five biggest blockers (owner summary item a)
1. The first screen does not answer "what is this and what do I do now" (D-01).
2. What waits for the owner is two clicks and one drawer away, and is not counted on the first screen (D-02).
3. There is no goal: the owner cannot say "grow MyCast" to the product and follow that one thing (D-03).
4. Five different status wordings side by side; the decorative office looks alive when nothing runs (D-04, D-07).
5. One page of 13 blocks, 9–19 screens long, with most text under 12 px (D-05, D-06).
