# Ploy public UX and functional benchmark for FactoryOS (T-731, issue #452 S0–S1)

Date: 2026-11-23 · Author: Claude (interactive session) · Scope: public pages only, clean-room.
Format precedent: `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md`.

This document covers deliverables 1 and 2 of issue #452 (benchmark + capability matrix; merged by Amendment A1.4).
It describes what Ploy **documents**. It is not proof that Ploy's product works well, converts well or is pleasant to use.

## 1. Access, terms and what was not observed

### 1.1 What was read
- 18 pages of `docs.ploy.ai` and 3 pages of `ploy.ai` (home, `/ploybooks`, `/pricing`), plus `terms-of-service`, both
  `robots.txt` files and `docs.ploy.ai/llms.txt`. Retrieved 2026-11-23, one page at a time, two seconds apart.
  Read in full: introduction, quick-start, core-concepts, projects, ploybooks, experiments, ploy-chat, notifications.
  Read by section: analytics, publishing, credits, site-builder, tips-and-tricks, working-with-a-team, the two
  marketing pages. Retrieved but used only through the docs index: ploy-lite, webhooks, launch-checklist, documents.
- The pages were requested as Markdown (`Accept: text/markdown`). This is an interface Ploy publishes for AI tools:
  `llms.txt` says "Fetch any result URL with Accept: text/markdown for the full page", and the docs `robots.txt` has the
  line "AI search & training crawlers — explicitly allowed".
- Two adjacent references: Linear docs (`/docs/inbox`, `/docs/triage`, `/docs/my-issues`) and PostHog docs
  (`/docs/product-analytics/funnels`, `/docs/experiments/analyzing-results`).

### 1.2 Terms that limit this work
Source: `https://ploy.ai/terms-of-service`, "Last Updated: April 13, 2026", read 2026-11-23. The use restrictions forbid to:
- "Reverse engineer, decompile, disassemble, or attempt to derive the source code of the Services";
- "Copy, modify, or create derivative works of the Services or related documentation";
- "Use the Services to develop a competing product or service";
- "Access the Services through automated means (including bots, scrapers, or crawlers) other than interfaces provided by Ploy".

How this work stays inside them:
- No Ploy account was created and no logged-in screen was opened, so "the Services" were not used at all.
- No code, bundle, API or prompt was inspected.
- The repository holds short quotes, links and our own descriptions. No Ploy page, screenshot, logo or asset is stored.
- FactoryOS Growth Manager is an internal tool for the owner's own products. It is not offered as a website or
  marketing platform. If FactoryOS is ever sold to clients with a growth module, this paragraph must be re-read by the
  owner before that offer is made (A1 answer: the first screen is designed for the owner and for future clients).

### 1.3 Not observed
| Item | Why | Effect on this document |
|---|---|---|
| The authenticated Ploy app | No account, by decision | Every statement about the app is "documented by vendor", never "observed" |
| Images inside the docs and the marketing site | Hosted on a CDN that is not opened; only alt text was read | Typography, colour, spacing, density and motion of Ploy are **not described** here (issue §3A.7 stays unanswered for Ploy) |
| Videos, webinars, third-party reviews | Not opened | No claims about real-world results or user satisfaction |
| YC and Product Hunt pages | Seen only as search-result summaries | Used for one fact (company background), marked low confidence |

## 2. Summary

Ploy is documented as a marketing-website platform: an in-app agent builds and edits pages by chat, the site is hosted
and published by Ploy, analytics are built in, and repeated work is saved as "Ploybooks" that run by hand, on a schedule
or from a webhook. Most of that product (hosting, site builder, domains, visitor identification, credits) is outside
what FactoryOS needs.

What is worth taking is the **owner-facing shell around the agents**, because that is exactly what FactoryOS lacks:

1. **Start from a goal, not from a tool.** Setup asks for the outcome, shows a three-line read of the business that the
   user can correct, then offers a short list of goals. Each chosen goal starts its own piece of work.
2. **One short queue of things that need the person** ("For you"), with two card types — needs your answer, or a
   recommendation — and a rule that a suggestion starts work only when the person presses its action.
3. **One page per goal**: the outcome in one sentence, the queue, then a work log, a plan, outputs and context.
4. **Draft first, publish separately.** Recommendations arrive with drafts already built and tagged "Draft"; promoting
   an experiment winner is explicitly not publishing.
5. **Statuses that say what is true and what to do**: "N pages changed since last publish", "Publishing paused" with one
   sentence of reason, "No data yet", "Gathering visitors", "Needs manual repair".

The five patterns are general interaction patterns. Each is re-designed for FactoryOS in §5; none requires copying
Ploy's layout, wording or brand.

## 3. Overlap Matrix (issue §1.4, extended by Amendment A1.1)

"Adds" = what #452 contributes on top. Nothing here opens a second write path to a claimed file.

| Existing task / asset | State on 2026-11-23 | Surfaces and files | What #452 adds | Conflict rule |
|---|---|---|---|---|
| #53 / T-594 sidebar groups | Issue open; code on main; ROADMAP unchecked (screenshots outstanding) | `static/index.html` nav markup, `docs/roadmap/T-594_NAV_MAP.md` | A goal-oriented grouping proposal in the IA spec (T-732) | Spec only. Navigation code changes happen in S5 as a follow-up to T-594, never as a parallel rewrite |
| #67 / T-599 verified claims | Done (`[x]`) | `relay_execution.py`, `lane_board.py` | Owner Home reads these as its source for "working now" | Read-only reuse |
| #47 Connections clarity | Issue open | `frontend/connections_catalog.js`, `connection_capabilities.py` | Audit finding only (T-732) | Not touched |
| #41 Telegram/Relay proof | Issue open; T-590/T-591 closed 2026-11-23 | `relay.py`, `relay_acceptance.py` | Nothing | Not touched |
| T-595, T-596, T-597, T-602 UI batch | Code on main; unchecked (screenshots outstanding) | drawers, Worker Center, help tips | T-732 screenshots can close their evidence gap as a side effect | Evidence only |
| `docs/reviews/ui-review-2026-11.md` | Done | 54 CI screenshots, findings P1–P3 | Baseline for the T-732 audit; not repeated | — |
| #348 / T-608–T-610 A/B tester | Done | `mvp_experiments.py`, `static/mvp-factory/` | Growth Manager uses it as the variant and decision store; proposes "guardrail" and "exposure" as additions | RFC only (T-733) |
| T-704 / T-705 Launchpad | Done | `mvp_launchpad.py`, `mvp_launchpad_agents.py`, `docs/specs/BUSINESS_LEAGUE_LAUNCHPAD.md` | Growth Manager uses its test card, funnel and gates; adds the missing Goal entity | RFC only |
| T-630 / T-634 evolution and quiz | Done | `mvp_evolution.py`, `mvp_quiz.py` | Learning step reads their results | Read-only reuse |
| T-702 social autopilot | Done; real accounts are owner tasks | `social_autopilot.py` | Distribution step = a draft in the existing weekly plan | No new publisher |
| #305 MyCast | Done; live parts with the owner | `mycast*.py`, `static/mycast-configurator/` | A designed visit + variant event (RFC); no code in this ticket | Not touched |
| #186 MVP Factory epic, #342 CustDev playbook, #346 A/B spec, #160 AI Collective, #102 Launch Agent | Open concept or spec issues | Documents | Cross-linked as context in the RFC | No duplicate tickets are opened |
| #437 / PR #443 sandbox previews (ChatGPT) | Open PR | Sandbox service | Possible later host for landing variants | Not touched; no dependency in S0–S4 |
| `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md` | Done | Document | Format reused; the Hercules ideas on versions, run analytics and limits are not repeated here | — |

## 4. Competitor Evidence Ledger

Columns follow issue §3. Retrieval date for every row: **2026-11-23**. Evidence type `doc` = official documentation,
`mkt` = official marketing page, `tos` = terms. Confidence is confidence that **the page says this**, not that the
product does it. "Observed" would mean seen in the running app; no row has that status.

| ID | Source (page § section) | Type | Conf. | What the page says | Inference (ours) | FactoryOS relevance | Constraint |
|---|---|---|---|---|---|---|---|
| E-01 | ploy.ai home § hero | mkt | high | Headline "Your website should be working harder than you are."; one line of promise; actions "Start Free" and "Get Demo" | One promise, two actions on the first screen | Owner Home promise line | Marketing page, not the app |
| E-02 | ploy.ai home § Monitor / Act / Surface | mkt | high | Three verbs explain the loop: watch, act, show the next step | A three-step mental model is offered before any feature list | "What can I do here?" block | Marketing claim |
| E-03 | docs /quick-start § Step 1 | doc | high | Setup asks for the website, optionally the business, then goals | Onboarding begins with outcome | Goal picker | — |
| E-04 | docs /quick-start § What Ploy learned | doc | high | A summary "in three highlighted lines" with gaps found; the user can Edit, then Continue | The system shows its understanding and lets the user correct it before work | "My read of the project" card in the goal wizard | — |
| E-05 | docs /quick-start § Choose your goals | doc | high | Six named goals, one preselected, "Something else" for free text | Short closed list + escape hatch | Goal list ("Grow MyCast", "Validate a new MVP", "Something else") | — |
| E-06 | docs /quick-start § Moving between questions | doc | high | Each question has Continue and Back; answers are kept; on a phone both stay at the bottom | One question per screen, sticky actions on mobile | Wizard mechanics | — |
| E-07 | docs /quick-start § After setup | doc | high | A three-step tour runs "while your first chats start working" | Waiting time is used to teach | First-run state | — |
| E-08 | docs /quick-start § Step 2 | doc | high | Each chosen goal starts its own chat that begins work; several goals end by offering three options to pick from | Work starts without a second prompt; choices are offered as three options | "Two variants + reasons" step | Starting work without asking conflicts with FactoryOS approval rules — see R-02 |
| E-09 | docs /quick-start § Your first publish | doc | high | The first page is published once without asking, to a Ploy address | Vendor trades consent for a quick "shareable link" | — | **Rejected** (R-01) |
| E-10 | docs /quick-start § Follow up in For you | doc | high | "For you" shows recommendations and work awaiting a response; cards "Needs input" and "Recommendation"; "A suggestion starts work only when you choose its action"; Dismiss with Undo | A single attention queue with typed cards | "Needs you" row | — |
| E-11 | docs /core-concepts § Glossary | doc | high | 16 terms: Workspace, Site, Chat, Project, Ploybook, Ploy's Agent, Agent, Deploy, Design System, Brand, Assets, Documents, Preview, Publish, Custom Domain, Integrations | The vocabulary is large; "Agent" is described as working "behind the scenes" | Agents as drill-down, not as the first screen | — |
| E-12 | docs /projects § intro | doc | high | A project gives work "one home: a goal, a live dashboard, a task plan, and a daily check-in" | Goal is the container; chats and playbooks hang under it | Goal page | — |
| E-13 | docs /projects § The dashboard | doc | high | Page order: goal, "For you", tabs Work, Dashboard, Plan, Chats, Outputs, Context; a chart without data reads "No data yet" | Fixed page skeleton per goal; empty charts are labelled, not hidden | Goal page skeleton; "not instrumented" label | — |
| E-14 | docs /projects § The dashboard (Work) | doc | high | A log "one entry per piece of work, grouped by day", next check-in under "Up next" | Activity is shown as dated results, not as live animation | "Working now / Done" log from Relay events | — |
| E-15 | docs /projects § Daily check-in | doc | high | A daily run puts recommendations in the queue; some come with pages already built, tagged Draft, with "Review and publish" | Recommendation + ready draft + one review action | Morning brief → Home cards | Uses vendor credits each day; FactoryOS equivalent must be $0 |
| E-16 | docs /projects § Daily check-in | doc | high | The check-in "updates a card when something it says is no longer true, and removes a card when its work is done" | Queue hygiene is a stated rule | Card lifecycle rule | — |
| E-17 | docs /site-builder § Compare a review copy | doc | high | Original and draft "Side by side or with Wipe"; red removed, green added, yellow rewritten; "Highlight changes" and "Scroll Sync" switches | A diff view designed for non-developers | A/B approval screen | Colours are a common diff convention, not Ploy's trade dress |
| E-18 | docs /experiments § intro, Create | doc | high | Tests one section of one page; form fields: name, page, section, Hypothesis, Goal, Guardrail (optional) | Hypothesis is a required field of the form; a guardrail metric protects against a harmful winner | Add "guardrail" to the experiment card | Feature is "available on request" (E-21) |
| E-19 | docs /experiments § Statuses | doc | high | Not started, Publish required, Needs proof, Gathering visitors, Completed, Archived, Needs manual repair | Statuses name the blocker or the honest phase | Status vocabulary for the funnel | Meaning of "Needs proof" is not explained on the page — unknown |
| E-20 | docs /experiments § Choose a champion | doc | high | "Promoting is not publishing." | Decision and release are two separate acts | Approve ≠ publish in the approval screen | — |
| E-21 | docs /experiments § Limits | doc | high | Experiments is enabled per workspace on request by e-mail to sales; visitors who refuse cookies "always see the champion and are not counted" | The feature is gated; consent refusal is excluded from results | Exclusion rule for our funnel | Do not describe Ploy experiments as generally available |
| E-22 | docs /experiments § Guardrail warnings | doc | high | "Guardrail at risk: <event>" once every version "has enough visitors" | The page admits a minimum sample before judging | "Not enough data" state | Threshold is not stated — unknown |
| E-23 | docs /ploybooks § What a Ploybook Is | doc | high | "a plain-language guide, broken into phases and checklist steps"; "a guide, not a rigid macro" | Playbook = readable document, not a flow chart | Playbook spec is Markdown-like text plus typed inputs | — |
| E-24 | docs /ploybooks § Creating from a chat | doc | high | Run once in a chat, then save; "A freshly authored Ploybook is a draft"; test run before scheduling | Automation is earned by one successful manual run | "Manual first" rule for Growth Manager playbooks | — |
| E-25 | docs /ploybooks § When a schedule ends | doc | high | A new schedule ends after 90 days by default; reminder three days before | Automations expire unless renewed | Design-only for us: schedules carry an end date | Schedules are not authorised in #452 |
| E-26 | docs /ploybooks § Managing | doc | high | "Keep a human in the loop for anything that sends." Drafts for review rather than auto-sending | Vendor recommends the same gate FactoryOS enforces | Confirms draft-only distribution | Recommendation, not an enforced control in Ploy |
| E-27 | docs /publishing § Publish your site | doc | high | Production tile reads "Up to date", "N pages changed since last publish" or "Site changed since last publish" | Drift between draft and live is always visible | "Draft differs from published" indicator | — |
| E-28 | docs /publishing § Publishing paused, failed | doc | high | One sentence explains why; "Fix does not publish your site"; "Do not treat an earlier attempt as a successful publish" | Recovery action is separated from the risky action | Failed-state card: reason, safe fix, retry | — |
| E-29 | docs /publishing § Automatic Publishing | doc | high | Off by default, per site; scopes "Preview only" and "Preview + Production"; a scheduled run without permission "must stop for a manual publish" | Standing permission is explicit, scoped and revocable | Matches social autopilot modes A/B/C | — |
| E-30 | docs /publishing § Restore | doc | high | Restore a version in the editor, then publish; each target shows last publish time and who published; agent publishes carry a mark | Rollback is two steps; actor is recorded | Audit line on every publish | — |
| E-31 | docs /analytics § Built-in events | doc | high | Named events: `page.viewed`, `session.*`, `cta.clicked`, `form.started`, `form.submitted`, `experiment.exposed` and others | A small fixed event vocabulary feeds goals and experiments | Our own event names for MyCast pages | Names are ours to choose; do not reuse Ploy's |
| E-32 | docs /analytics § When a visitor refuses | doc | high | Without consent: no stored visitor ID, an anonymous ID "that resets every day", IP not stored, visits still counted | Cookieless counting is presented as the fallback | Our default mode (no cookie at all) | Legal sufficiency is the site owner's responsibility (the page says so) |
| E-33 | docs /analytics § Built-in Analytics | doc | high | Channels: Direct, Organic Search, AI, Social, Referral, Email, Paid Search, Paid Social | Channel is a first-class dimension | `channel` on the visit event (Telegram, LinkedIn, direct) | — |
| E-34 | docs /credits § What spends AI credits | doc | high | A yes/no table of what costs credits; "For a large job, Ploy's Agent estimates the cost and asks you first" | Cost is explained before the action | Cost line on the approval card ($0 default) | Ploy is metered; FactoryOS is not |
| E-35 | docs /credits § When you run out | doc | high | Work finished so far "stays saved"; the chat stops and shows a notice | Budget exhaustion is a recoverable state | "Low budget / limit reached" state | — |
| E-36 | docs /credits § Understand what used your credits | doc | high | Usage grouped by chat, user or usage type; "Missing attribution does not mean no usage occurred" | Cost can be traced to a piece of work; gaps are admitted | Cost per goal; "unknown ≠ zero" | — |
| E-37 | docs /ploy-chat § Send while replying, Stop | doc | high | Enter adds to the current reply, Ctrl/Cmd+Enter queues; Stop ends the reply but background work may continue and "may pick the task back up" | Steering mid-run exists; Stop is not a hard stop | Our cancel must be a real cancel (Relay run state) | — |
| E-38 | docs /tips-and-tricks § 7 | doc | high | "Agent silently stops mid-task" is acknowledged; advice: send "continue" | A known weakness: silent stall | FactoryOS already detects stale runs — keep that visible | Vendor's own admission |
| E-39 | docs /notifications | doc | high | Alerts "when a chat finishes or needs your answer"; in-app bell, browser, e-mail, Slack; reply to the e-mail to answer | Two notification reasons only | Telegram notices: finished, needs you | — |
| E-40 | docs /working-with-a-team § roles | doc | high | Owner, Admin, Member; a Member can be limited to chosen workspaces; publishing by the agent needs Owner or Admin | Three roles; publish is role-gated | Matches `workspace_tenancy.py` owner / member / viewer | — |
| E-41 | ploy.ai /ploybooks | mkt | high | A public gallery of playbooks with category filter, author, description, "read the steps and expected outputs, then run it" | Templates are shown with expected outputs before running | Playbook card shows outputs and cost before "Run" | — |
| E-42 | ploy.ai /pricing | mkt | medium | Plans Free, Starter, Pro, Enterprise; "Start without a credit card" | — | Cost of the alternative (owner summary item f) | Prices change; re-check before quoting |
| E-43 | Web search summary of YC / Product Hunt listings | assumption | low | Ploy was founded by a Webflow co-founder; raised a seed round | — | Context only | Not read at the source |

## 5. UX pattern inventory with decisions (issue §3A)

Decision: **adopt** = take the general interaction pattern; **adapt** = take the idea, change the mechanics; **reject**.
"Validated?" states whether any user test backs the pattern **for FactoryOS**. None does yet: every expected effect below
is a hypothesis to be checked in T-733 with the owner and the 3–4 people he brings.

| # | Pattern | Problem it solves | Evidence | Strength | Weakness / risk | Decision for FactoryOS | Independent implementation | Validated? |
|---|---|---|---|---|---|---|---|---|
| P-01 | Goal-first start | A new user does not know which tool to open | E-03, E-05 | The first question is about the outcome | A fixed goal list can hide other features | **Adopt** | Owner Home has "Start a goal" with 2–3 goals that FactoryOS can really run today, plus "Something else" that opens the existing New Job / MVP paths | Hypothesis |
| P-02 | "Here is my read — correct me" | The user cannot tell what the system understood | E-04 | Builds trust before work starts; cheap to correct | A confident but wrong summary misleads | **Adapt** | The goal wizard shows the existing brand passport step 1 and Launchpad test card as an editable summary; unknown fields say "unknown", never a guess | Hypothesis |
| P-03 | Typed attention queue | Requests for the owner are scattered | E-10, E-16; Linear Inbox "Priority" tab | One place, two card types, explicit action, dismiss + undo | Becomes a second inbox if cards are not removed when stale | **Adopt** | "Needs you" row fed only by existing sources (open questions, owner desk, approvals, gates). A card disappears when its source says resolved | Hypothesis |
| P-04 | One page per goal with a fixed skeleton | Work on one goal lives in many screens | E-12, E-13, E-14 | Predictable; outcome first | Six tabs is a lot on a phone | **Adapt** | Goal page: outcome → needs you → funnel → work log → variants → evidence. Four sections, no tab row on a phone | Hypothesis |
| P-05 | Recommendation that arrives with a draft | "The agent will do it" is abstract | E-15 | The owner reviews a thing, not a promise | Costs compute for drafts nobody wants | **Adapt** | Drafts are produced only inside an approved goal, never speculatively; the card shows "Draft" and the reason | Hypothesis |
| P-06 | Side-by-side compare with change highlight | A/B review is hard to do by memory | E-17 | Fast, non-technical | Needs both versions rendered the same way | **Adopt** | A vs B view with synchronized scroll and a "show differences" switch; phone shows a swipe between A and B | Hypothesis |
| P-07 | Decide ≠ publish | One click doing two things causes accidents | E-20, E-28 | Two explicit steps | One more step | **Adopt** (already a FactoryOS invariant) | Approval card states exactly what approval does and does not do | Matches existing gate |
| P-08 | Statuses that name the blocker | "In progress" hides the truth | E-19, E-27, E-28 | The status is also the instruction | Needs a real source per status | **Adopt** | Status vocabulary bound to backend enums; a status with no source is not shown (A1.3) | Partly: `evidence.py` levels already work this way |
| P-09 | Labelled emptiness ("No data yet") | Empty charts look broken or look like zero | E-13, E-22; PostHog "no color = not significant" | Honest | — | **Adopt**, extended | Three values per funnel step: number, 0, "not instrumented" (A1.2), plus "not enough data to compare" | Hypothesis |
| P-10 | Guardrail metric | A variant can win the goal and harm something else | E-18, E-22 | Simple safety rule | Needs a second measured event | **Adapt** | Optional guardrail on the experiment card (for MyCast: activation must not fall while sign-ups rise). RFC item, not built | Hypothesis |
| P-11 | Playbook as a readable document, earned by one manual run | Automations nobody understands | E-23, E-24, E-41 | Reviewable by a non-developer | Free text is hard to validate | **Adapt** | Growth playbook = typed fields from the existing test card + readable steps; "manual first" | Hypothesis |
| P-12 | Automation that expires | Forgotten schedules spend money | E-25 | Safe default | — | **Adopt in design only** | Any future schedule carries an end date and a reminder. Schedules stay design-only in #452 | Not applicable yet |
| P-13 | Scoped standing permission | Asking every time is tiring; never asking is unsafe | E-29 | Explicit scope, off by default | — | **Already present** | Social autopilot modes A/B/C. No change | Existing behaviour |
| P-14 | Cost before action, cost per piece of work | Surprise spending | E-34, E-36 | Trust | FactoryOS has little cost data per run | **Adapt** | Approval card shows "$0 — no paid service" or the real figure; cost per goal reads "unknown" where not measured | Hypothesis |
| P-15 | Two notification reasons | Notification noise | E-39 | Clear contract | — | **Already present** | Telegram: finished, needs you | Existing behaviour |
| P-16 | Three-verb explanation of the product | "What is this?" in the first ten seconds | E-01, E-02 | Short | Marketing tone can overpromise | **Adapt** | One factual line + three verbs tied to real modules; no numbers on the first screen unless they come from the backend | Hypothesis (task T1) |

### Rejected
| # | What | Evidence | Why rejected |
|---|---|---|---|
| R-01 | Publishing the first result without asking | E-09 | Violates the FactoryOS approval gate |
| R-02 | Starting work for every selected goal immediately | E-08 | Each run must be claimed and visible; a goal starts one planned run after the owner confirms the summary |
| R-03 | Chat as the main interface | E-37, E-11 | FactoryOS already has structured stores (test card, experiments, gates); a form with real fields is easier to verify than a chat |
| R-04 | Site builder, hosting, domains, CMS, migrations | docs index | Outside FactoryOS; MyCast pages already exist |
| R-05 | Visitor identification and contact enrichment | docs index (`/visitor-identification`, `/contact-tools`) | Personal-data risk and paid data; contradicts the cookieless, no-PII design |
| R-06 | Ad campaigns, outbound e-mail | E-08 | No paid ads or outbound messages by default (issue §6.7) |
| R-07 | Credits and metering | E-34 | FactoryOS runs on existing subscriptions at $0 incremental cost |
| R-08 | A 16-term vocabulary on the first screen | E-11 | Owner Home uses four nouns: product, goal, variant, result |

## 6. Functional workflow map (issue §3B)

Classification: **D** = documented by vendor only · **U** = unknown from public pages · **O** = out of scope for FactoryOS.
No capability is classified "observed".

| Capability | Objective | Inputs / user choices | Agent actions (documented) | Outputs | Approval and validation | Failure and recovery | Class |
|---|---|---|---|---|---|---|---|
| Business onboarding | Understand the business and pick goals | Website URL, optional description, goals, design intent | Reads the site, writes a three-line summary and gaps | Summary, recommended goals, first chats | User edits the summary; Continue | Leaving setup: "Resume workspace setup" | D |
| Positioning research | Clear messaging | Goal "Improve brand positioning" | Researches customers and competitors, proposes three hero options with one-line reasons | Mockups, chosen page built | User picks one of three | U (source quality and citations are not documented) | D / U |
| Brand and design tokens | Consistent look | Existing site, Figma file or style questions | Extracts colours, fonts, spacing into a design system | Design system applied to every page | User can update it by request | U | D, O |
| Site and landing generation | A page | Prompt, design system | Builds pages on a fixed web stack | Page in live preview | Preview desktop and mobile; private pages stay unpublished | Versions restore | D, O |
| Chat edits and preview | Iterate | Plain-language requests; direct text edit in preview | Edits code; queue or steer while replying | Updated preview | — | Stop (may resume); silent stall acknowledged (E-38) | D |
| Content and SEO | Traffic | Goal "Organic traffic" | Audits ranking and AI-answer presence; shows top three opportunities; builds the first | Page; offer of a weekly playbook | User confirms the weekly run | U | D |
| Playbooks | Repeatable work | Saved from a chat or written; inputs parameterized | Follows phases and steps with the same tools as chat | A run in its own chat; optional working memory | Test run before scheduling; drafts for anything that sends (recommended) | Schedule expiry; missing integration blocks the schedule | D |
| Triggers | Run without a person | Manual, schedule (plain language, timezone, end date), webhook payload | Runs the playbook with the payload as context | Run history | Production publish needs a standing permission | Run "must stop for a manual publish" without permission | D |
| Experiments | Choose the better section | Page, section, hypothesis, goal event, guardrail, split 10–90 % | Drafts the challenger; measures both | Results per version; guardrail warning | Person promotes; person publishes | "Needs manual repair" (meaning U) | D (on request only) |
| Analytics and feedback | See what works | None for hosted sites; snippet or server key otherwise | Tracks events; builds dashboards by request | Dashboards, channel breakdown | Owner/admin controls settings | Consent refusal → cookieless counting | D |
| Publish, versions, recovery | Go live safely | Targets Production / Preview | Builds and deploys a snapshot | Live site, last-publish line with actor | Role-gated; automatic publishing off by default (except E-09) | Paused / failed with Fix and Publish again; restore then publish | D |
| Access, privacy, budget | Control | Roles, workspace limits, credits | — | Usage by chat / user / type | Estimate before a large job | Out-of-credits keeps finished work | D |
| Autonomous ad buying, full campaign execution | — | — | Docs describe "paused draft campaigns" and approval before any ad-account change | — | — | — | **U — not asserted** |

## 7. Capability matrix: Ploy ↔ FactoryOS ↔ Growth Manager (deliverable 2)

"FactoryOS today" is from the code on `main` at `9e26cbc`. Owner / Depends name real tasks.

| Capability (Ploy, documented) | FactoryOS today | Growth Manager decision | Priority | Owner / Depends |
|---|---|---|---|---|
| Goal-first onboarding (E-03–E-05) | No goal entity. Brand passport step 1 "Goal & KPI"; MVP brief `goal` field | New thin `goal` entity + wizard | P1 | Claude / T-733 RFC → S5 |
| Attention queue (E-10) | Open questions card, Owner Desk inside the Workers drawer, approvals in several studios, morning brief in Telegram only | One "Needs you" row composed from those sources | P1 | Claude / T-732 spec → S5 |
| Goal page (E-12–E-14) | MVP project page + Launchpad tab + experiments view, separate | One projection page per goal | P1 | Claude / T-733 |
| Daily check-in with drafts (E-15) | `morning_brief.py` (Telegram), `mvp_cycle.py` phases | Show the brief's items as Home cards; no new scheduler | P2 | Claude / depends on Home |
| Compare view (E-17) | `docs/prototypes/mvp-builder/ab-branches-preview.html`, experiments preview | Side-by-side A/B approval screen | P1 | Claude / T-733 prototype |
| Experiment with hypothesis and goal (E-18) | `mvp_experiments.py`: hypothesis, primary_metric, two branches, owner-only approval and decision | Reuse as is | — | Done (T-608–T-610) |
| Guardrail metric (E-18, E-22) | Not found | Optional field, design only | P2 | Claude / RFC |
| Exposure and visit events (E-31) | Not found for MyCast pages; only invite `ref` | Designed first-party cookieless event; first PR candidate | P1 | Claude / RFC → S5; privacy wording needs owner review |
| Funnel (E-13, PostHog funnels) | Launchpad `FUNNEL` with manual evidence; evolution funnel with manual counts | Same steps, fed by measured events where they exist; "not instrumented" elsewhere | P1 | Claude / depends on the visit event |
| Payment step | Not implemented | Shown as "not instrumented" | — | Owner / T-709-H |
| Playbook as document (E-23, E-24) | Launchpad test card (typed fields); Surfer recipes; mods | Growth playbook = test card + readable steps; manual trigger only | P2 | Claude / RFC |
| Schedule and webhook triggers (E-25) | DBOS engine, social autopilot scheduler | Design only; not authorised | P3 | Needs separate owner approval |
| Honest publish states (E-27, E-28) | Social autopilot item statuses (`draft/approved/failed/missed`, `publishing/published/uncertain`) | Reuse; show drift "draft differs from published" where data exists | P2 | Claude / RFC |
| Standing permission scopes (E-29) | Social autopilot modes A/B/C (owner chose A) | Reuse | — | Done (T-702) |
| Cost before action (E-34) | No per-goal cost; usage strip on Control Room | Cost line on approval card; "unknown" where not measured | P2 | Claude / RFC |
| Roles (E-40) | `workspace_tenancy.py` owner / member / viewer | Reuse; goal belongs to a project and its workspace | — | Done (T-553) |
| Site builder, hosting, visitor identification, ads, credits | — | Rejected (R-04–R-07) | — | — |

## 8. Adjacent references (issue §3C)

Chosen because each documents one mechanism FactoryOS needs and Ploy documents only briefly. Retrieved 2026-11-23.

### 8.1 Linear — attention queue and triage
- `linear.app/docs/inbox`: the Inbox is "where you’ll find important updates"; a **Priority** tab "separates notifications
  that need your attention from other updates"; notifications can be snoozed and come back at a chosen time.
- `linear.app/docs/triage`: incoming items wait in a separate list and get exactly four outcomes — accept, decline, mark
  as duplicate, snooze.
- `linear.app/docs/my-issues`: assigned work is "grouped in a focus order such as urgent work, … blockers, …"; "Some
  sections only appear when they apply."

Taken for FactoryOS: (a) the queue has a small closed set of outcomes per card — approve, reject, ask, later;
(b) "later" is a real state with a return time, so the card does not rot; (c) sections with nothing in them are not
drawn. Compared with Ploy's "For you" (E-10), Linear documents the outcomes and ordering more precisely; Ploy documents
the link between a card and a ready draft. FactoryOS needs both.
Expected effect: fewer places to look for owner actions. Status: hypothesis; measured by tasks T4 and T7.

### 8.2 PostHog — funnel denominators and honest experiment results
- `posthog.com/docs/product-analytics/funnels`: a funnel can show conversion as "Overall conversion … relative to the
  first step" or "Relative to the previous step"; step order can be sequential, strict or any.
- `posthog.com/docs/experiments/analyzing-results`: an exposures panel shows how many users saw each variant and helps
  verify "sufficient sample size"; a result has "No color" when it "is not statistically significant".

Taken for FactoryOS: (a) every funnel step shows its own denominator and states which of the two conversion bases it
uses (issue §6.9 asks for step-specific denominators); (b) exposure counts are shown before any comparison;
(c) with small numbers the screen says "not enough data to compare" instead of naming a winner. For the MyCast pilot
the numbers will be small, so the default presentation is counts, not percentages.
Expected effect: the owner can tell a lead from a click from a payment (task T5). Status: hypothesis.

## 9. Where FactoryOS can be better than what Ploy documents
- **Verified execution.** Ploy's docs acknowledge silent stalls (E-38) and a Stop that may not stop (E-37). FactoryOS
  already has claims, run ids, stale detection and evidence levels. Owner Home should show that advantage in plain words
  ("claimed 14:02, last sign of life 2 minutes ago").
- **Approval as an invariant.** Ploy recommends a human in the loop (E-26) and has one automatic publish (E-09).
  FactoryOS enforces the gate in code and tests.
- **Evidence levels.** Nothing in the public pages matches `claimed < linked < checked < accepted`.
- **Zero incremental spend.** Ploy is credit-metered (E-34).

## 10. Limits of this benchmark
- It is a reading of documentation. Whether Ploy's users reach their goals faster is unknown.
- Visual design was not observed (§1.3). The FactoryOS visual direction in T-732/T-733 is therefore designed
  independently and cannot be a copy.
- Documentation changes; every row carries its date. Re-check before quoting any row outside this repository.
- "Used by a competitor" is not "validated". Section 5 marks every transferred pattern as a hypothesis.

## Sources
Ploy (official): `https://docs.ploy.ai/` pages `introduction`, `quick-start`, `core-concepts`, `ploy-chat`, `projects`,
`site-builder`, `ploybooks`, `experiments`, `analytics`, `publishing`, `tips-and-tricks`, `credits`, `notifications`,
`ploy-lite`, `webhooks`, `hosting/launch-checklist`, `working-with-a-team`, `documents`, `llms.txt`, `robots.txt`;
`https://ploy.ai/` (home), `https://ploy.ai/ploybooks`, `https://ploy.ai/pricing`, `https://ploy.ai/terms-of-service`,
`https://ploy.ai/robots.txt`.
Linear: `https://linear.app/docs/inbox`, `https://linear.app/docs/triage`, `https://linear.app/docs/my-issues`.
PostHog: `https://posthog.com/docs/product-analytics/funnels`, `https://posthog.com/docs/experiments/analyzing-results`.
Third-party (search summaries only, low confidence): Y Combinator launch page and Product Hunt listing for Ploy.
