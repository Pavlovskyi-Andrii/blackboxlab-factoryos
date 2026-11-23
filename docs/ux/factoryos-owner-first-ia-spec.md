# FactoryOS owner-first information architecture (T-732, issue #452 §5)

Date: 2026-11-23 · Author: Claude (interactive session) · Status: **draft for Checkpoint A**.
The owner chooses one of three directions; this document is written for the recommended one (direction 2) and is
revised after the choice. Nothing here changes the production dashboard.

Base: `v5.19.1` (9 groups, 37 menu items).
Inputs: `docs/ux/factoryos-current-state-audit.md` (defects D-01…D-17), `docs/research/ploy-public-ux-functional-benchmark.md`
(patterns P-01…P-16), owner answers in `.autopilot/answers.md` «#452».
Owner-facing comparison of the directions: `docs/prototypes/owner-home-growth/checkpoint-a.html`, wireframes in
`docs/screenshots/t-732/direction-{1,2,3}-wireframe.png`.

## 1. Who the first screen is for
Owner answer 2026-11-23: **the owner and future clients**. So the first screen must work in two situations:
- **The owner, daily, with data**: what waits for me, how my products are doing, is anything running.
- **A new client, first visit, no data**: what is this, what can I do here, how do I start.

The pilot audience for MyCast (also an owner answer) is a busy person who wants compressed information and to stay
in focus on one chosen topic; episodes arrive in Telegram; landing languages EN/UK/RU.

## 2. The three directions
| | 1. Today | 2. Products and goals (recommended) | 3. Conversation |
|---|---|---|---|
| Main object on the first screen | The queue: needs you / working / done | Products, each with a goal, funnel and next step | One input "What are we doing today?" |
| Owner, daily | Strong | Strong | Medium |
| New client, empty account | Weak: an empty queue explains nothing | Strong: "add your first product, set a goal" | Medium: the person must invent a question |
| Product results visible | Small | Yes | Only when asked |
| Approval on the first phone screen | Yes | Yes | Yes |
| New backend needed | None | A thin `goal` entity | An always-on server-side model; paid calls are off by default |

Why 2: it is the only direction that answers D-01 (what is this) for a new client **and** D-02/D-10 (what waits for
me, how are my products doing) for the owner, and it is built from stores that already exist plus one small entity.
Direction 1 survives inside it as the "Needs you" strip and page. Direction 3's input can be added later as a
shortcut into the goal wizard, without making it the main screen.

## 3. Navigation: before and after (direction 2)

### 3.1 New top level
| New item | Purpose | Replaces / absorbs |
|---|---|---|
| **Home** | Products and goals, the "Needs you" strip, working now, spend | Control Room as the default view |
| **Needs you** (with count) | One list of everything waiting for the owner | The "You need to do" part of Workers, Open questions, Review, pending social plan, MVP owner gates |
| **Results** | Funnels and evidence per product | Owner console → MyCast listeners, Launchpad funnel, Performance, Analytics |
| **Agent team** (secondary) | Who works, history, time, tokens, cost, MCP | Agent Office, Agents, Workers, Build Progress, Autopilot, Supervisor, Error Center, Pipeline, Browser agent |
| **All tools** (secondary) | Every existing studio and page, grouped as today | Everything else |

The "Frequent" block added in `v5.19.1` stays at the top of the sidebar.
The Control Room page stays available under All tools → Overview for as long as the owner wants it (a flag decides the
default, §8).

### 3.2 Every current item mapped
"Where" is the place in the new navigation; nothing is removed.

| Current group → item | Opens today | Where after | Change |
|---|---|---|---|
| Overview → Control Room | page top | All tools → Overview → Control Room | No longer the default |
| Overview → Pipeline | drawer | Agent team → Pipeline | — |
| Overview → Supervisor | scroll | Agent team → Supervisor | Gets its own view instead of a scroll |
| Overview → Error Center | scroll | Agent team → Errors; failures also appear in Needs you | — |
| Create content → New Job | drawer | All tools → Content → New job; also a goal step | — |
| Create content → Jobs | scroll | All tools → Content → Jobs | Own view |
| Create content → Discovery, Revideo, Content Brain, Media Finisher | drawers | All tools → Content | — |
| Create content → Variants, Package, Outputs | drawers, need a selected job | All tools → Content (inside a job) | Reached from a job, not from the menu |
| Review & publish → Review | drawer | Needs you (approvals) and All tools → Publish | Pending approvals counted in Needs you |
| Review & publish → Publish | drawer | All tools → Publish | — |
| Growth & learning → Performance, Analytics | drawers | Results | — |
| Growth & learning → Experiments | drawer | Results → content experiments (`/api/experiments`) | Kept apart from MVP A/B experiments |
| Automation & team → Autopilot, Agents, Workers | drawers | Agent team | "You need to do" moves to Needs you |
| Automation & team → Browser agent | page `/static/surfer/` | Agent team → Browser agent | — |
| Automation & team → Google Sheets | page | All tools → Data → Google Sheets | — |
| MVP Builder → Projects | page | Home (products) and All tools → MVP Builder | Products on Home come from the same registry |
| MVP Builder → MyCast podcast | page | Home → MyCast; All tools → MyCast settings | — |
| MVP Builder → Decision Memory, MyBrief | pages | Home (as product cards) and All tools → MVP Builder | — |
| Review & publish → Social autopilot, LinkedIn, OLX | pages | Needs you (pending weekly plan) and All tools → Publishing channels | — |
| Mods & skills → Connected | scroll | All tools → Mods and skills | Own view |
| Learning → Learning | page | All tools → Learning; "How it works" link on Home | — |
| System → Build Progress, Release QA | drawers | Agent team → Build progress, Release QA | — |
| System → Owner console | scroll | Its tabs move: Telegram tasks, Claude↔Codex, Battle runs → Agent team; MyCast listeners, Voice briefs → Results | Card disappears once every tab has a home |
| System → Brand strategy | scroll | All tools → Brand strategy; step 1 "Goal & KPI" feeds the goal wizard | — |
| System → Settings | no page (D-16) | All tools → Settings: language, connections, Access vault, flags | Gets a page |
| `/relay`, `/learn`, MyCast public pages | pages | unchanged | — |

### 3.3 Addresses for every view (D-08)
Each top-level view and each goal gets a hash address so Telegram messages, runbooks and the morning brief can link to
the exact place: `#home`, `#needs`, `#results`, `#team`, `#tools`, `#goal-<id>`, `#compare-<experiment id>`.
Existing `#vault` keeps working. The router shows the view in `location.hash` on load and on `hashchange`; an unknown
hash opens Home. Drawers keep their current open functions, so old handlers and tests stay valid.

## 4. Home: what is drawn and where each value comes from
Rule (Amendment A1.3): **a tile without a backend source is not drawn**. An empty section is hidden, not shown as zero.

| Block | Shown when | Source (existing) | Owner-visible text |
|---|---|---|---|
| Promise line + "New goal" | Always | Static copy (EN/UK/RU) | "Your products grow here. Set a goal. Agents research, prepare variants and measure. You decide what goes out." |
| Needs you strip (count + first item) | Count > 0 | `GET /api/factory/open-questions` `.items`; `GET /api/factory/owner-desk` `.runbooks[].status.state` ≠ done; `GET /api/factory/team-tasks` `.totals.waiting_owner`; MVP projects with `approval` pending (`GET /api/mvp-factory` `.projects[]`); social items in `draft` (`GET /api/factory/social` `.items[]`) | Count, the most urgent item, its action button |
| Product cards | One per MVP project; plus "Content" if content jobs exist | `GET /api/mvp-factory` `.projects[]` (`title`, `stage`, `blocked`, `launchpad`, `recommendation`) | Name, goal or "No goal yet", one status word, next step |
| Funnel on a product card | The product has a goal | Launchpad `FUNNEL` and evidence (`mvp_launchpad.py`); MyCast sign-ups and activations from `GET /api/factory/mycast/listeners` | Per step: a number, `0`, or "not measured" (A1.2). Payment: "not connected" until T-709-H |
| Working now | Always | `GET /api/factory/lane-board` `.lanes[].state`, `.task_id`, `.heartbeat_age_seconds`, `.started_at` | "Claude · <task> · took it at 14:02 · last sign of life 2 min ago", or "Nobody is working right now" |
| Spend | Always | `GET /api/usage` (`today_cost_usd`) and `FACTORY_DAILY_BUDGET_USD` | "$0 today · paid services off · limit $10 a day" |
| First-run block | No MVP project and no job | Same sources, empty | "Add your first product" with two example goals; link to "How FactoryOS works" |

Not on Home: the Agent Office illustration (moves to Agent team), connection catalogue, the five-step content strip,
mods, brand strategy, browser agent, worker results.

## 5. One status vocabulary for the owner (D-04)
The owner sees six words. Each maps to existing enums; the technical value stays visible in Agent team.

| Owner word (EN / UK / RU) | Shown when (existing values) |
|---|---|
| Needs you / Потрібно від вас / Нужно от вас | Owner-desk runbook not done; open question; MVP stage `owner_review` or `spec_review`; experiment preview awaiting approval; Launchpad gate G3–G5 waiting; social item `draft` in mode A |
| Working / Працює / Работает | Lane state Working; Relay execution `claimed` or `running` with a fresh heartbeat |
| Waiting / Чекає / Ждёт | Relay `queued`; MVP `build_queued`; assigned but not claimed |
| Done, checked / Готово, перевірено / Готово, проверено | Evidence level `checked` or `accepted`; Relay `done` with merged PR + CI |
| Stopped / Зупинено / Остановлено | Lane Blocked; Relay `blocked` or `failed`; social `failed` or `missed`; the card says why and offers the safe action (Retry, Fix, runbook) |
| No connection / Немає зв'язку / Нет связи | Lane Offline or Stale; heartbeat older than the lane's limit |

"Idle" is not shown as a status on Home: an idle agent is simply not in "Working now".

## 6. Journeys

### 6.1 Owner, daily (phone)
1. Opens Home (or a link from the morning brief to `#needs`).
2. Sees "Needs you · 3" and the first item: "MyCast: compare landing variants A and B".
3. Taps Compare → side-by-side A/B with differences highlighted, intended channel, cost "$0", what approval does and
   does not do ("Approving marks B as the winner. Nothing is published.").
4. Approves B, or rejects with a reason, or "Later" (returns tomorrow). Decision is logged with actor and time.
5. Back on Home the strip shows the next item. The MyCast card shows the next step.
Error path: an agent stops → the item appears in Needs you as "Stopped: <reason>" with Retry or the runbook.

### 6.2 Future client, first visit (desktop)
1. Home with no products: promise line, "Add your first product", two example goals, "How FactoryOS works".
2. Adds a product (name, link, language) → the product card appears with "No goal yet · Set a goal".
3. Goal wizard: one question per screen, Back keeps answers, sticky actions on a phone (P-01, P-02):
   product → result wanted (e.g. "first 100 genuine registrations") → audience → channel → period →
   "Here is what I understood" (editable summary; unknown fields say "unknown") → Start.
4. Start creates **one** planned run (claimed through Relay). Home shows it under Working now.
Error path: no worker online → the goal is saved as "Waiting" and the card says "No agent is connected yet" with the
connection guide, instead of a spinner.

### 6.3 Specialist (Agent team)
Home → Agent team → agent or run → history, artifacts, time, tokens, cost, MCP configuration; back returns to the same
place (hash address). Nothing in this view is removed by #452.

## 7. Visual rules for new surfaces (D-06, D-12, D-17)
Added as new tokens next to the existing colour variables; existing screens are not refactored in this ticket.
- Colours: keep the current palette (`--bg`, `--panel`, `--cyan`, `--blue`, `--green`, `--amber`). Amber = needs you,
  cyan = working, green = done and checked, a red token for stopped. Semantic colour is never the only signal: every
  state also has its word.
- Type scale: 12 / 14 / 16 / 20 / 28 px. **Nothing below 12 px.** Body 14–16 px.
- Spacing scale: 4 / 8 / 12 / 16 / 24 / 32 px; layout by `gap`.
- Targets: at least 32 px on desktop and 44 px on touch.
- Contrast: WCAG AA for ordinary text in both the dark product theme and any light surface.
- Motion: no ambient animation on Home; respect `prefers-reduced-motion`. "Live" indicators only when a heartbeat is
  fresh.
- Breakpoints for new surfaces: 600 and 1024 px only.

## 8. Rollout and rollback (for S5, not this ticket)
- Flag `FACTORY_OWNER_HOME_ENABLED`, default off. Off = today's dashboard, unchanged.
- On = Home is the default view; Control Room remains in All tools.
- Every new view only reads existing APIs except the goal entity; switching the flag off loses nothing.

## 9. Open for the owner (Checkpoint A)
1. Direction: 1, 2 or 3 (recommended 2).
2. Should Home show the content-production area as a product card ("Blackbox Lab content"), or only MVP products?
   Default: show it as a card while content jobs exist.

## 10. Next (T-733)
Clickable prototype in the chosen direction (Home, Needs you, goal wizard, goal page with funnel, A/B compare, eight
states, EN/UK/RU, phone and desktop), the Growth Manager RFC with the field mapping, and the test script for the owner
and the 3–4 people he brings.
