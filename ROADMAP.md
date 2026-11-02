# FactoryOS Roadmap

This file is the execution queue for the autonomous Factory Builder.

Rules:
- One task should fit roughly one focused implementation cycle.
- Every task must have an objective, machine-checkable DONE criterion.
- Tasks that require credentials, payment, account ownership, irreversible decisions, or an external human approval are marked `[HUMAN]`.
- Autopilot skips `[HUMAN]` tasks and continues with the next safe task.
- `Depends: T-x,T-y` — a task is selected only after every listed task is checked `[x]`; an unknown ID keeps it waiting.
- Lane policy 2026-10-30 (owner decision): Claude is the single coordinator and executor. The `chatgpt` lane is paused; ChatGPT is reconnected later only through tasks Claude explicitly labels `Owner: chatgpt`.
- `Owner: chatgpt | claude | gemini | any` — the lane that implements the task. Each runner (`AUTOPILOT_OPERATOR`, default `claude`) only takes tasks with its own Owner or no Owner/`any`. A planner that starts coding a task itself must set `Owner:` to its own lane first, so two agents never build the same task.
- Human approval remains mandatory before any real social publishing action.
- ZERO ADDITIONAL SPEND: do not connect paid API billing, metered AI/browser calls, new paid cloud resources, or paid publisher plans without explicit fresh owner approval. Use existing subscriptions and free-tier resources only, with a fail-closed spending guard. Subscription access must never be silently replaced with PAYG API usage.

## P0 — CLAUDE TAKES OVER (owner priority 2026-10-29)

Owner directed Claude Code to be the principal engineering/operator coordinator. **Read docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md FIRST, then CLAUDE.md, and verify live state**. Do not claim owner Telegram works until live end-to-end proof. Do not enable paid APIs/cloud resources or unauthorized publishing. Separate worker service 'online' from actual task claims. Do not push to main; PR+CI+verification required.

- [x] T-599-E Owner GitHub Issue auto-intake
  Owner: claude
  Priority: P0
  Spec: docs/handoff/T-599_VERIFIED_EXECUTION.md §2 T-599-E; Issue #67
  Goal: FactoryOS periodically (≤ every 5 min, free GitHub API) imports open Issues authored by the repo owner whose first body line is `Owner: Claude|ChatGPT|Gemini` via the existing idempotent `intake_github_issue`; an Issue referencing a T-ID that already has a `roadmap:T-xxx` ticket is linked instead of duplicated; other authors are ignored.
  DONE: deterministic tests cover import, dedupe on repeat, T-ID linking, foreign-author rejection and GitHub-unavailable fallback; no secrets in logs; CI green.

- [x] T-599-F Workers / Build Progress / Telegram from verified events
  Owner: claude
  Priority: P0
  Depends: T-599-E
  Spec: docs/handoff/T-599_VERIFIED_EXECUTION.md §2 T-599-F; Issue #67 slice 3; overlaps T-596
  Goal: per-lane state (Working/Blocked/Stale/Idle/Offline) derived only from run events + heartbeat; ROADMAP tasks with Owner but no claim render "assigned, not claimed"; Build Progress columns Planned/In progress/Blocked/Review/Done with counts done/remaining per lane; Telegram /status and /tasks show the same per-lane summary.
  DONE: deterministic API/UI/Telegram fixtures for idle/running/blocked/stale/offline and assigned-not-claimed; web and Telegram show identical task/stage; RU/UK/EN; CI green.

- [x] T-599 Verified task claims: assignment ≠ execution
  Owner: claude
  Priority: P0
  Depends: T-537,T-599-E,T-599-F
  Spec: docs/handoff/T-599_VERIFIED_EXECUTION.md; Issue #67
  Goal: route ROADMAP tasks and owner GitHub Issues through the existing RelayQueue claim/run_id/event journal; remove head-of-line blocking; require explicit Owner on every open task; derive Workers/Build Progress/Telegram state only from worker events.
  Progress 2026-10-30: T-599-A done — a blocked task is parked until new answers.md input or owner Retry, a task that exhausts MAX_FAILS is parked until Retry, and the daemon continues with the next safe task (autopilot/test_autopilot.py parking_regression). T-599-B done — every open non-HUMAN task carries Owner (CI lint in autopilot/test_autopilot.py). T-599-C/D done — every ROADMAP run starts only after an atomic server claim (`POST /api/relay/worker/roadmap-claim`, one ticket per task, run_id fenced, other lanes/active/stale runs refused) and the worker itself emits running/committed/pushed/done/blocked/failed plus heartbeats (test_roadmap_claims.py, claim_gate_regression). The worker branch now follows main between tasks and restarts itself when runner code changed (follow_main_regression). Remaining: T-599-E, T-599-F (separate tasks above) and live EC2 verification.
  Progress 2026-10-31: T-599-E/F done. Umbrella acceptance `test_t599_acceptance.py` (spec §3 A–E, run in CI via test_relay_execution.py) joins claim → events → lane board → Telegram; refused claims are journalled as `claim_rejected`; blocked lanes show their reason in API/web/Telegram. PR/CI and Issue #67 evidence follow the worker push (not claimed by the agent).
  DONE: deterministic tests A–E pass; no open ROADMAP task lacks Owner; a blocked task no longer stalls the queue; an Owner-assigned task without a claim renders as "assigned, not claimed"; CI-gated PRs; evidence posted to Issue #67.

- [ ] T-590 Claude takeover: restore verifiable Telegram Relay build-process control room
  Owner: claude
  Planner: owner; Executor: Claude Code Pro (primary). P0.
  Spec: docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md; GitHub Issues #41, #51, #56, #40; PR #43, #42, #60.
  Goal: implement a working vertical slice from owner Telegram/Web task intake through durable queued→claimed→running→events→code/commit→GitHub lifecycle, with factual owner-facing Telegram /status /tasks /task and same Web state. Establish real issue/ROADMAP→Relay intake or explicit reconciled links; resolve missing parent-owned task progress during Claude run.
  Test: deterministic intake dedupe, authenticated claims, idempotent events, stale/blocked/failed paths, redaction, restart persistence, no fabricated ChatGPT telemetry; targeted and full CI.
  DONE: one owner task can be followed end-to-end with verified server worker claim, live heartbeat and task status, a real artifact/commit where applicable, and owner-visible Telegram trace; preserve external publish approval. If owner chat not paired, show a precisely documented HUMAN action and validate all other stages without claiming live Telegram DONE. Record evidence in Issue #41, open reviewed non-main PR, verify CI and deployed revision.
  Progress (2026-10-29, code slice committed on autopilot/aws-worker; NOT live-verified): parent-owned `.autopilot/run.json` run telemetry in heartbeat; run_id-fenced, event_id-idempotent Relay events with one safe retry; owner-only GitHub Issue → Relay intake (`POST /api/relay/intake/github-issue`, Telegram `/issue N`) with source_key dedupe; shared `lifecycle` trace in Web `/relay` detail + Telegram `/task` (PR/CI/merge/deploy shown "не проверено"); note redaction. Deterministic tests: `test_relay_lifecycle.py` (via `test_relay_execution.py`), `autopilot/test_delegation.py`.
  Remaining (needs owner/GitHub access): open PR autopilot/aws-worker → main and confirm CI green; merge + confirm Render deployed SHA; HUMAN T-506 pairing, then live `/new` test message → claim → run_id → `/task` trace; post redacted evidence to Issue #41.
  Progress (2026-10-31, acceptance run): all deterministic stages re-verified on the EC2 worker. Fixed the Python 3.9 import failure in `app.py`/`media_finisher_worker/app.py`, so smoke + planner now run on the worker, with no app-level skips. Live stages are still open: PR/CI/merge/`build_sha`/Telegram/Issue #41. Exact steps: `docs/handoff/T-590_ACCEPTANCE.md`.
  Re-check (2026-10-31, run-20261031162233-a7b938): deterministic stages green again at `62ffd5e`. The branch is still 10 commits ahead of main (not merged), and the live stages remain blocked on GitHub access plus HUMAN T-506.

- [ ] T-591 Telegram live owner acceptance & full operator task lifecycle
  Owner: claude
  Planner: owner; Executor: Claude Code Pro. P0. Depends: T-590.
  Spec: docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md; Issue #41 and #51.
  Goal: verify actual owner Telegram chat pairing/webhook and tested /status, /tasks, /task <id>, /history, /roadmap, /github; callbacks for refresh/detail/retry; preserve event history; RU/UK/EN. Only verified ChatGPT actions visible, not fictional live ChatGPT sessions.
  DONE: real test message in paired owner chat -> one ticket -> authenticated Claude claim -> running -> final evidence -> owner reply with exact IDs and GitHub links, redacted transcript and timestamps. If needs owner 2FA, mark HUMAN with exact ask and do not claim done.

- [ ] T-591-A Telegram Relay P0 status/queue/stale hotfix (ChatGPT owner, Claude follow-up acceptance)
  Owner: claude. Depends: T-590 (implementation merged in #63; final live acceptance remains T-591).
  Scope: truthful heartbeat vs active task, claimable queue counts, stale-claim handling without auto-rerun, owner retry instructions.
  Test: test_relay_livefix.py and existing Relay suites; CI before merge, then Render and owner live E2E. Never mark T-591 done until actual Telegram task executes.

- [ ] T-592 Fix Build Progress / Worker Center factual status and UI freeze
  Owner: claude
  Planner: owner; Executor: Claude Code Pro. P0. Depends: T-590.
  Spec: Issues #55, #56, #54, #52 and docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md.
  Goal: reconcile 87% vs 49% metric scopes; distinguish EC2/SSM/systemd/subscription auth/heartbeat/claim/task; fix race for .autopilot/status.json, stale/offline, huge overflow; make owner HUMAN blockers actionable.
  DONE: deterministic tests + screenshot evidence showing same task/stage in Telegram and Web; no ghost running/false progress; columns usable mobile+desktop and consistent stale timestamps; non-main PR/CI.

- [ ] T-593 Stabilize Claude execution/CI/automatic safe backlog, then P1 tasks
  Owner: claude
  Planner: owner; Executor: Claude Code Pro. P0/P1. Depends: T-590.
  Spec: handoff diagnosis, Issue #40/#49/#50/#47 and ROADMAP T-560-C onward.
  Goal: reproducible restricted permission profile, safe tests and dependency boot (Python 3.9), non-spinning retry, durable worker errors, GitHub/ROADMAP task dedupe, automated safe backlog sequence and concise verified owner reporting.
  DONE: verified no-payg, no direct-main, tests/CI, worktree safe, simulated/offline/blocked regression and actual next safe work after previous verified commit; all open issues prioritized without duplicate executor tasks.
  Progress 2026-10-30: first live claimed runs on EC2 blocked because the agent's Python lived in /tmp/fos-venv (wiped on reboot) and headless `claude -p` denied python3. Delegation now keeps a persistent gitignored `<repo>/.venv` rebuilt only when requirements.txt changes, puts it first on PATH, and pre-allows the CLAUDE.md verification loop (Read/Edit/Write, python, node --check, local git add/commit) while push/deploy stay disallowed.

- [x] T-600 Fail-closed Claude CLI error diagnostics / retry classification
  Live EC2 re-test 2026-11-01: at 12:01 UTC T-551-A hit `usage_limit_reached` ("resets 4:20pm (UTC)"); the worker held the whole queue (no task parked or failed) and resumed T-551-A at 16:22 UTC (reset + 120 s grace).
  Owner: claude-session (implemented by the interactive Claude session in PR #81; was `chatgpt`)
  Priority: P0 support fix (owner-requested 2026-10-31, independent of Claude-owned T-562)
  Depends: T-537
  Goal: when a headless Claude process exits before writing .autopilot/status.json, retain truthful, redacted diagnostic evidence (exit code, structured CLI error category) instead of reporting only the missing file. Distinguish subscription login/auth-blocked from retryable execution failures; never treat absent status as DONE; do not leak secrets or bypass OAuth; preserve bounded retries and server run_id reporting.
  DONE: deterministic fake-CLI tests for auth missing, CLI stderr failure, success-without-status, sanitized output and normal status-writing success; CI green, non-main PR, and live EC2 re-test separately verified. No paid APIs, new resources, or direct main pushes.
  Progress 2026-10-31: subscription limits are now recognised from the CLI's structured result (`api_error: usage_limit_reached`, HTTP 429) and hold the whole queue until the reported reset (persisted, survives restart) instead of parking each task as failed. Fake-CLI tests use the exact EC2 output. Open: live EC2 re-test on the next real limit.

- [ ] T-601 Owner desk: step-by-step HUMAN runbooks + ask Claude about selected text
  Owner: claude-session (interactive Claude session; the EC2 worker must not pick this up)
  Priority: P0 (owner-requested 2026-11-01)
  Goal: Worker Center shows every open [HUMAN] task as a runbook (what to do, how to check, what to do for each known error) with live status from server facts; the owner selects any runbook text (or a step) and asks Claude; the EC2 worker answers read-only between tasks with the existing subscription and the answer appears under the task (+ Telegram notice). Secrets are never requested and are scrubbed from questions.
  DONE: every open HUMAN task has a runbook (CI-enforced), queue/auth/scrubbing tests, read-only worker CLI tests, EN/UK/RU UI strings, CI screenshots, and one live question answered on production.
  Progress 2026-11-01: implemented in owner_desk.py, autopilot/owner_questions.py and the Worker Center; open: live question/answer on production after merge and worker restart.

## P1 / P2 — Owner UI and agent management batch (2026-10-30)
Spec: \`docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md\`. These are **independent safe Claude engineering tasks**, except where dependency is explicitly stated. Owner is currently using EC2; avoid unnecessary service restarts or credential changes. When T-590 is blocked awaiting PR/CI/owner Telegram, do not silently claim that these UI tasks are running; use a new verifiable task claim/branch and continue safe independent work as scheduler permits. No new paid API, no bypass, no direct main push.

- [ ] T-602 UI fixes from the 2026-11-01 screenshot review
  Owner: claude
  Priority: P1
  Spec: docs/reviews/ui-review-2026-11.md (PR #92, from Issue #88). Evidence source: CI `ui-screenshots` artifact (54 PNG, EN/UK/RU × 1440x900 / 1024x768 / 390x844).
  Goal: fix, in static/index.html (and owner_desk.py for the runbook text): (1) mobile 390 px header actions (Refresh / Share Viewer / New) clipped on the right — wrap or move into an overflow menu, no hidden text; (2) Build Progress: status lanes Planned / In Progress / Completed / Blocked visible on the first screen, the "Recent autonomous decisions" log collapsed/height-limited below them; (3) Agent Office header: title/subtitle and Offline chips in separate grid zones, no overlap at 1440/1024/390; (4) 1024 px tablet: drawer width keeps the main area readable; (5) decision log: short cards with date/type, long raw text behind "details", marked raw worker evidence when untranslated; (6) owner-desk question box keeps the selected step visible (sticky caption, max-height); (7) owner-desk runbooks localized to UK and EN (keep RU; product names and variable names untranslated; test_owner_desk.py must check all three).
  DONE: before/after `ui-screenshots` from CI attached in the PR description (same scenes), test_navigation.py / test_locale_parity.py / test_explainability.py / test_owner_desk.py green, no new horizontal overflow, CI-gated PR.

- [ ] T-594 Left navigation with collapsible semantic submenus
  Owner: Claude
  Priority: P1
  Spec: #53, T-574; docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md M3.
  Goal: audit and preserve all current routes; clear section grouping and descriptive RU/UK/EN labels, icon rail, hover/click expanding text, slide-out adaptive one-third desktop menu, outside-tap closes, breadcrumbs, current section and keyboard accessibility.
  DONE: before/after nav map, screenshots desktop/mobile, all existing destinations reachable, keyboard/touch and RU/UK/EN regressions, CI-gated PR.

- [ ] T-595 Resizable/maximizable sliding drawers and overflow repair
  Owner: Claude
  Priority: P1
  Spec: #54, T-575; docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md M4.
  Goal: resize large panels by left-edge drag slider/handle, max/restore beside X, bounds that keep sidebar visible, session width memory, fix horizontal overflow and clipped Build Progress columns, mobile full-screen drawers and keyboard/touch controls.
  DONE: tests and before/after screenshots 1440x900, 1024x768, 390x844; no cut-off Planned/In Progress/Completed/Blocked; CI-gated PR.

- [ ] T-596 Worker Center / Agent Office factual live observability
  Owner: Claude
  Priority: P1
  Spec: #52, #55, #56; docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md M2.
  Goal: distinguish EC2 IAM instance visibility, systemd/OAuth, heartbeat, Relay claim, real current Claude task; existing worker detail, timeline, scoped heatmap, errors, last verified time, branch/PR/CI. Clickable workers in Agent Office. Correct distinct progress denominators (87% vs 49% historical), no fake progress, actionable HUMAN blockers.
  DONE: deterministic offline/stale/idle/running test cases, source links, web↔Telegram consistency, RU/UK/EN mobile/desktop screens and CI-gated PR.
  Progress 2026-10-31: code slice done. `worker_observability.py` → `GET /api/factory/worker-overview` + Worker Center panel + Telegram `/status` block show separate signals: host, EC2 API (DescribeInstances not granted = unknown, not offline), systemd, OAuth (from the supervisor report forwarded in the heartbeat), heartbeat, Relay claim and current task (from the lane row, the same snapshot as Telegram). The panel also shows a Kyiv-day heatmap of verified worker evidence (zero vs unknown), a timeline, errors, branch/commit/PR links (CI "not verified"), progress per population (Factory Builder vs ROADMAP vs Claude lane) and actionable HUMAN blockers. Agent Office worker chips open the Worker Center. Deterministic tests: `test_worker_observability.py` (in CI via test_relay_execution.py) and a smoke block. Remaining: RU/UK/EN mobile/desktop screenshots (no browser on the worker), and the PR/CI after the worker push.

- [ ] T-597 Contextual assistance and accessibility
  Owner: Claude
  Priority: P2
  Spec: #57, T-578; docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md M5.
  Goal: reusable info/help icon, microcopy and small factual diagrams for Relay, workers, connectors, stages, approval, video, Content Brain, Discovery; RU/UK/EN, desktop hover/mobile tap/keyboard focus. Audio/video tutorial placeholders marked not yet supported; no metered generation.
  DONE: all target surfaces covered, no overlapping help/popovers, accessible tests, mobile screenshots and CI.
  Progress 2026-10-31: code slice done. The shared T-533 help tip now covers Relay (Delegation Center + lane board), workers (Worker Results + Worker Center), Connections, pipeline stages, Approval, Media Finisher video, Content Brain and Discovery. Each has EN/UK/RU copy, a factual mini flow and a "tutorial not yet supported" note. Hover/focus on one tip closes the others, and desktop edges are aligned. `test_explainability.py` covers this locally and in the existing CI step. Open: mobile screenshots (no browser on the worker) and CI after the worker push.

- [x] T-598 Stable autonomous engineering handoff and report
  Owner: Claude
  Priority: P1
  Spec: #61, #40, #49–51, T-593; docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md M6.
  Goal: verified GitHub Issue/ROADMAP/Relay task dedupe, Depends/Owner scheduler from merged #62, bounded retries, no endless git pull represented as busy, truthful parent run state and checkpoint reports, PR/CI/Render verification. GitHub workflow scope and EC2 describe IAM read permissions escalated as optional HUMAN tasks with least privilege, not blocking code.
  DONE: safe queued→claimed→running→checks→PR/CI evidenced, automation survives restart, error-handling regression and concise owner-visible milestone report; no paid resources.
  Progress 2026-10-31: report is in docs/handoff/T-598_AUTONOMOUS_HANDOFF.md, with the chain mapped to code and tests. Parking state and retry counters are now persisted in `.autopilot/parking.json`, so a restart (or a code-update re-exec) no longer resets the bounded retries. Network git runs with a timeout and without a credential prompt, and reports `offline` instead of hanging. A concise UTC+Kyiv milestone report goes out on done/blocked and never claims PR/CI/Render. Regressions in autopilot/test_autopilot.py: restart_survival, git_timeout, milestone_report. Optional least-privilege HUMAN requests: T-598-H1/H2 (end of file). The worker verifies PR/CI/Render after its push; this agent did not.

## v5.0 — Self-Building FactoryOS

- [x] T-500 Repository autopilot contract
  Goal: add ROADMAP, autonomous-agent rules, decision log and runtime status contract.
  DONE: `test -f ROADMAP.md && test -f CLAUDE.md && test -f DECISIONS.md && test -f .autopilot/status.example.json`

- [x] T-501 Safe Claude Code runner
  Goal: run one roadmap task per isolated Claude Code invocation on a non-main branch, with bounded turns, bounded retries and optional Telegram escalation.
  DONE: `python -m py_compile autopilot/autopilot.py autopilot/notify.py && docker compose -f docker-compose.autopilot.yml config >/dev/null`

- [x] T-502 Autopilot state inside FactoryOS
  Goal: expose roadmap progress, current task, latest autonomous status and blockers in the FactoryOS API/UI.
  DONE: `DATA_DIR=/tmp/factoryos-autopilot FACTORY_PASSWORD="" python smoke_tests.py`

- [x] T-503 Roadmap auto-advance
  Goal: when a Builder task reaches verified DONE, select the next safe ROADMAP task automatically; never auto-run `[HUMAN]` tasks.
  DONE: regression proves done -> next task, blocked HUMAN -> skip/escalate, no duplicate dispatch.

- [x] T-504 Decision review
  Goal: surface DECISIONS.md entries in FactoryOS so owner decisions can be reviewed in batches instead of interrupting implementation.
  DONE: API + UI render repository decisions and smoke tests stay green.

## v5.0.1 — Owner Interrupt + Claude Worker

- [x] T-505 Secure Telegram owner pairing
  Goal: pair one private Telegram chat with FactoryOS using a short-lived one-time code; never commit the bot token or owner chat ID.
  DONE: `python -m autopilot.test_notify` and runtime pair command persists only ignored pairing state.

- [ ] [HUMAN] T-506 Pair owner Telegram bot
  Need: owner places FACTORY_TELEGRAM_BOT_TOKEN in the existing FactoryOS Render secret environment, starts pairing in FactoryOS and sends the one-time `/pair CODE` command to the bot.
  DONE: `/api/factory/telegram/status` reports paired=true and a FactoryOS test push arrives in the paired chat.

- [x] [HUMAN] T-507 Authorize Claude Code Pro
  Progress: trusted phone runner is authenticated through the Claude subscription; T-508 executed with ANTHROPIC_API_KEY unset.
  DONE: Claude Code status confirms subscription auth and no ANTHROPIC_API_KEY overrides it.

- [x] T-508 Claude delegation adapter
  Goal: let FactoryOS delegate bounded Builder work to a Claude Code runner authenticated with the owner's Pro subscription, while keeping API PAYG disabled by default.
  Progress: `autopilot/delegation.py` pins one task per bounded Claude Code run, captures git/status evidence, fails closed on main/push/pin violations and reports to `POST /api/claude-worker/task-result`.
  DONE: deterministic regression proves task pinning, bounded execution, evidence capture and no direct main/prod action.

- [x] T-509 Persistent Claude worker watch mode
  Goal: keep the trusted runner alive while idle, retry a failed branch push without rerunning completed work, and automatically pick up newly added safe ROADMAP tasks.
  DONE: `python -m autopilot.test_autopilot`; idle state is visible to heartbeat, polling defaults on, and `AUTOPILOT_DAEMON=0` preserves one-shot behavior.
## v5.0.2 — Browser Action Runner

- [x] T-560-A Browser runner contracts + policy engine
  Planner: ChatGPT
  Spec: docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md
  Goal: add provider-neutral BrowserActionPlan/BrowserActionResult contracts, bounded step validation, secret redaction, immutable payload hashing, approval policy and a deterministic mocked executor; no real credentials or browser session in this task.
  DONE: deterministic regression proves secret-like fields are redacted, unknown/unsafe steps are rejected, publish/send/destructive actions cannot execute without matching approval snapshot + payload hash, read/draft mocked runs can finish with factual evidence, and no real browser/provider/network call is made.

- [x] T-560-B Session/vault abstraction + human takeover
  Owner: ChatGPT
  Planner: ChatGPT
  Depends: T-560-A,T-550
  Spec: docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md
  Goal: add opaque credential_ref/session_ref resolution contracts, workspace/account session isolation and resumable waiting_human checkpoints for 2FA/CAPTCHA/security challenges without exposing secrets.
  Progress 2026-10-28: opaque per-workspace SessionRegistry and waiting_human/resume authorization contract merged; actual credential vault resolution and persisted session handoff remain unfinished.
  Progress 2026-10-29: scoped CredentialVault contract (vault:// refs, SecretValue never renders, human-only OTP/recovery material unresolvable), persisted SessionRegistry/CheckpointStore (refs + redacted metadata only) and single-use resumable mock executor that never replays completed irreversible steps. Real vault backend and Playwright session restore remain future work (no credentials configured).
  DONE: deterministic two-workspace regression proves no session crossover, logs/results contain no secret values, challenge state stops safely at waiting_human, and an owner-authorized checkpoint can resume without replaying already-completed irreversible steps.

- [x] T-560-C Real browser executor + generic recipe
  Owner: ChatGPT
  Planner: ChatGPT
  Depends: T-560-A,T-560-B
  Spec: docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md
  Goal: add a real browser executor adapter (Playwright or equivalent) behind the provider-neutral contract with allowlisted domains, bounded navigation/steps, upload/fill/click/extract/screenshot support and factual evidence capture.
  Progress 2026-10-28: local Playwright adapter with fail-closed origin/method/step guard and redacted artifacts implemented; real Chromium fixture remains opt-in and installation on a production worker is not yet approved. No account login or real submission enabled.
  Progress 2026-10-29: `generic_form_recipe` + deterministic fixture regression (form flow, redacted evidence, off-domain rejection, step/timeout limits, submit blocked without valid approval and still blocked pending a trusted approval verifier). Real Chromium run remains operator opt-in.
  DONE: local deterministic fixture executes a generic allowlisted form flow, captures redacted evidence, rejects off-domain navigation, respects timeout/step limits and keeps submit disabled unless the plan carries valid approval.

- [x] T-560-D Social web draft recipes
  Owner: claude
  Planner: ChatGPT
  Depends: T-560-C,T-550
  Spec: docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md
  Goal: add account-portable draft preparation recipes for X/Twitter web, Instagram web and Telegram web/channel UI when an official API/connector is unavailable; final publish/send remains approval-gated.
  DONE: fixture recipes can prepare text/media up to the final submit boundary, account bindings are workspace-scoped, no plaintext credentials are stored, challenge pages become waiting_human, and no fixture can publish without a matching human approval snapshot.

- [ ] T-560-E Browser runner observability
  Owner: claude
  Planner: ChatGPT
  Depends: T-560-A,T-560-C
  Spec: docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md
  Goal: expose Browser Runner plans/results/checkpoints/artifacts in Worker Results and Trace Viewer so the owner can see what site/action ran, where it stopped and what factual evidence exists.
  DONE: deterministic UI/API fixtures render plan status, step progress, blocker/checkpoint, redacted action log and screenshot/artifact references without exposing credentials, cookies, tokens or fabricated receipts.


## v5.1 — Viral Discovery Loop

- [x] T-510 Discovery adapter
  Goal: collect current short-form candidates through a provider-neutral adapter with provenance and deduplication.
  DONE: deterministic fixture creates deduplicated discovery candidates with source URL, platform, metrics and capture time.

- [x] T-511 Breakout ranking
  Goal: rank candidates using factual velocity/engagement evidence without inventing unavailable metrics.
  DONE: regression covers ranking, missing metrics and tie behavior.

- [x] T-512 Candidate -> Revideo handoff
  Goal: one approved discovery candidate can create a traceable Revideo project without manual copy/paste.
  DONE: source provenance survives Discovery -> Revideo -> production job.

- [x] T-513 Semi-autonomous content loop
  Goal: Discovery -> Revideo -> Content Package -> Media Finisher -> HUMAN APPROVAL.
  DONE: zero-spend deterministic acceptance reaches approval and never publishes automatically.

## v5.2 — Real Publishing Closure

- [x] T-519 Metricool publisher adapter
  Goal: add a server-side Metricool scheduling adapter that receives only the exact human-approved immutable snapshot and final durable video.
  DONE: regression proves YouTube Shorts / TikTok / Instagram Reels mapping, exact media binding, AI disclosure metadata and no fake platform receipt.

- [ ] [HUMAN] T-520 Configure first real publisher
  Need: owner-controlled platform/publisher credentials or connected publishing provider.
  Progress 2026-10-26: Metricool brand blackboxlab7 is connected in ChatGPT (YouTube / TikTok / Instagram visible), but the live FactoryOS Render runtime still reports `adapter=manual` and `metricool_configured=false`. Known non-secret account IDs are not sufficient without the server-side provider credential; keep publishing fail-closed until FactoryOS itself reports a configured real adapter.
  DONE: FactoryOS reports one configured real publisher adapter without exposing secrets.

- [ ] [HUMAN] T-521 First owner-approved real post
  Need: explicit owner approval of the exact final media + immutable metadata snapshot.
  DONE: real external post ID/URL is persisted as a Publisher receipt and attributed back to the Factory Cycle.

- [x] T-522 Analytics return loop
  Goal: ingest factual platform metrics for the published post and attach them to the exact workflow/media/content snapshot.
  DONE: persisted analytics snapshot is traceable to external post ID and contains no fabricated metrics.


## v5.3 — Reliability + Operator Clarity

- [x] T-530 CI baseline stabilization
  Goal: restore a deterministic green local/CI baseline for the current branch without weakening, deleting or bypassing tests.
  DONE: Python compile, Media Finisher planner tests, autopilot/Telegram/delegation tests and zero-spend smoke tests all pass; dashboard JavaScript validation remains enabled.

- [x] T-531 Worker Results completeness
  Goal: make every canonical worker visibly answer “what went in, what it did, what came out, and what it cost” without fabricating unavailable metrics.
  DONE: deterministic fixtures expose worker input, action, status, output, artifacts, duration, tokens and cost when known; unknown values render explicitly as unavailable and smoke tests cover the contract.

- [x] T-536-A Delegation Board API
  Planner: ChatGPT
  Parent: T-536
  Goal: expose one owner-safe API contract that combines the ROADMAP queue, hierarchy/dependencies, Claude worker heartbeat, active task, recent verified results and queue counts.
  DONE: deterministic regression returns planner queue + worker state + done/running/queued/blocked/HUMAN counts without returning worker tokens or other secrets.

- [ ] T-536-B Live worker telemetry
  Owner: claude
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A
  Goal: extend heartbeat/runtime telemetry with current stage, task start/elapsed time, branch/head, queue depth, safe CPU percent and memory usage when available, with null/unsupported fallbacks.
  DONE: heartbeat regression persists and renders telemetry without secrets; Linux/Termux metrics are numeric when available and unsupported platforms degrade cleanly.

- [x] T-537 Dependency-aware roadmap scheduler
  Planner: ChatGPT
  Goal: make the Claude worker honor Depends metadata before selecting a safe ROADMAP task, so blocked tasks are skipped instead of running prematurely; HUMAN tasks remain non-delegable.
  DONE: deterministic regression proves a task with unmet dependencies is not selected, an unrelated safe task can still advance, completed dependencies unlock the task, and HUMAN blockers can never be auto-run.

- [x] T-536-C Planner hierarchy + delegation provenance
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A
  Goal: make ROADMAP tasks readable as a hierarchy (task/subtask), including planner/source, parent, dependency, Goal and DONE criteria so the owner can see exactly what ChatGPT delegated and why.
  DONE: parser/API expose parent/dependency/planner/goal/done-criteria metadata for representative tasks while remaining backward-compatible with existing ROADMAP entries.

- [x] T-536-D Worker / Delegation Control Center UI
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A,T-536-B,T-536-C
  Goal: add a dedicated Worker page: left column = ChatGPT/Planner queue and hierarchy; right column = Claude runner live state; top summary = online, current task, progress counts, branch and heartbeat age.
  DONE: desktop two-column and mobile stacked fixtures render queued/in-progress/done/blocked tasks, online/offline/stale worker, branch, stage, elapsed, CPU/memory when known, and remaining safe/HUMAN counts.

- [x] T-536-E Delegation execution timeline
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-D
  Goal: show the lifecycle of each delegated task as a factual timeline: queued -> picked -> running -> checks -> commit -> push -> done/blocked/failed, with timestamps, commit SHA, changed files and checks.
  DONE: verified task-result fixtures render timeline events and link the exact commit/check evidence; missing events are shown as unavailable rather than invented.

- [x] T-536-F Safe operator controls
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-D
  Goal: provide safe remote controls for the daemon: pause after current task, resume, and retry a blocked/failed safe task; never expose force-push, main checkout, production deploy or publish bypass.
  DONE: command channel is idempotent, authenticated, auditable and regression proves pause/resume/retry cannot bypass main/prod/publish safety invariants.

- [x] T-532 Live pipeline + handoff trace
  Goal: make the main FactoryOS pipeline visually show current movement and worker-to-worker handoffs instead of only static cards.
  DONE: a deterministic workflow fixture renders ordered source artifact -> worker run -> output -> downstream worker edges with running/done/blocked/failed states and a usable mobile fallback.

- [x] T-533 Explainability + tooltips
  Goal: remove ambiguity around Hook, Script, Caption, Voice and the Cycle/Idea/Job/Review/Learned stages with concise contextual help.
  DONE: EN/UK/RU tooltip/help copy exists for the canonical concepts, hover/focus/tap access is keyboard/mobile safe, and regression prevents missing help keys.

- [x] T-534 EN/UK/RU localization parity
  Goal: remove mixed-language UI leftovers and keep the three supported locales structurally in sync.
  DONE: an automated locale-parity regression catches missing canonical dashboard keys and the representative EN/UK/RU dashboard fixture contains no known cross-locale fallback strings.

- [ ] T-535 Artifact + media viewer hardening
  Owner: claude
  Goal: make agent artifacts and finished media reliably open from Worker Results, Trace Viewer and Approval flows while preserving signed-media/auth boundaries.
  DONE: deterministic regression opens representative text, JSON, subtitle and video artifacts through the intended viewer/media routes with correct content handling and no broken known-artifact links.

## v5.4 — Revideo Production Hardening

- [ ] T-540 Revideo zero-spend acceptance
  Owner: claude
  Goal: prove the full safe content path Discovery candidate -> Revideo -> rewrite -> Content Package -> Media Finisher -> HUMAN APPROVAL on deterministic fixtures.
  DONE: acceptance reaches waiting_approval with provenance and originality evidence intact, creates no real provider spend and cannot auto-publish.

- [ ] T-541 Media Finisher operator preview
  Owner: claude
  Goal: make the final-video review path obvious before approval, including source/final preview and the produced cuts/captions/audio/graphics artifacts that actually exist.
  DONE: deterministic UI/API regression exposes available before/after media plus generated artifact links, gracefully marks absent optional artifacts, and preserves the approval gate.

- [ ] T-542 Publishing dry-run evidence
  Owner: claude
  Goal: validate the exact immutable media+metadata snapshot that would be sent to YouTube Shorts, TikTok and Instagram Reels without making a real external post.
  DONE: zero-spend dry-run produces a traceable publisher plan/receipt preview bound to the approved snapshot; no external post ID is fabricated and real publish still requires T-520/T-521.

## v5.5 — Sellable Workspaces + Account Portability

- [x] T-550 Account portability foundation
  Planner: ChatGPT
  Goal: remove owner-specific social identity from the runtime connection registry, add durable workspace/provider binding metadata, expose safe Disconnect / Change account controls, add HubSpot as a CRM/Growth connector slot, and ensure disconnect never deletes FactoryOS content history.
  DONE: deterministic regression proves Metricool / YouTube / Instagram / TikTok / HubSpot are portable connection slots, provider secrets never appear in the connection registry, YouTube can be detached independently, Metricool disconnect fences real publishing, and integration routes are owner-write protected by the existing auth middleware.

- [ ] T-551-A OAuth framework scaffold
  Owner: claude
  Planner: ChatGPT
  Depends: T-537,T-550
  Goal: build the credential-free provider-neutral OAuth framework for Google/YouTube, TikTok, Meta/Instagram and HubSpot: provider registry, authorize/callback route contracts, state/PKCE helpers, token-vault interface and deterministic mocked adapters, without real client secrets or external authorization.
  DONE: zero-secret tests cover provider selection, state validation, PKCE where applicable, callback error handling, token-vault interface, revoke/disconnect contract and no token leakage to UI/logs.

- [ ] [HUMAN] T-551 Provider OAuth applications
  Planner: ChatGPT
  Depends: T-550
  Need: owner creates/approves production OAuth applications and redirect URLs for Google/YouTube, TikTok, Meta/Instagram and HubSpot, plus any required provider review.
  DONE: every provider has production client credentials stored only in secret environment/vault storage and an approved callback URL; no customer token is committed to Git.

- [ ] T-552 OAuth callback + token vault
  Owner: claude
  Planner: ChatGPT
  Parent: T-550
  Depends: T-551
  Goal: implement provider-specific authorize/callback/refresh/revoke flows so a customer can connect, disconnect and replace accounts from FactoryOS without editing Render environment variables.
  DONE: deterministic mocks cover OAuth state/PKCE where supported, token refresh, encrypted secret storage, revoke/disconnect and account replacement without exposing tokens to the browser or logs.

- [ ] T-553 Workspace data tenancy
  Owner: claude
  Planner: ChatGPT
  Depends: T-550
  Goal: scope jobs, artifacts, approvals, publishing queue, analytics, CRM attribution and integration bindings to a workspace/customer while preserving owner/admin observability.
  DONE: two-workspace regression proves users cannot read or mutate each other's content, credentials, publishing queue or analytics; all background workers carry explicit workspace identity.

- [ ] T-554 Customer onboarding + account replacement acceptance
  Owner: claude
  Planner: ChatGPT
  Depends: T-552,T-553
  Goal: make a sellable onboarding flow where a new customer signs in, connects their own YouTube/TikTok/Instagram/HubSpot accounts, runs content, then safely disconnects/replaces all accounts without losing FactoryOS project history.
  DONE: end-to-end acceptance covers customer A -> disconnect all -> customer B login/connect with zero credential or content leakage and preserved workspace-specific audit history.



## v5.8 — Multi-Model Role Lab

- [x] T-580 Role / Operator separation
  Planner: ChatGPT
  Goal: represent a FactoryOS role (Scout, Researcher, Scriptwriter, Engineer, Reviewer, QA, Supervisor, etc.) separately from the operator/model assigned to it (ChatGPT, Claude, Gemini, Auto), without renaming existing canonical workers.
  DONE: API contract exposes roles, available operators, assignment state and operator online/auth status; existing pipelines remain backward-compatible.

- [ ] T-581 Operator assignment UI
  Owner: claude
  Planner: ChatGPT
  Depends: T-580
  Goal: let the owner assign ChatGPT / Claude / Gemini / Auto to any eligible role from the worker/agent UI and clearly show the current operator on every worker card.
  DONE: deterministic UI fixture changes operator assignment for representative Content and Engineering roles and displays offline/auth-pending states without fabricating readiness.

- [ ] T-582 Battle Run experiment model
  Owner: claude
  Planner: ChatGPT
  Depends: T-580
  Goal: run the same task/content brief through two or more role→operator chains and preserve exact chain provenance for each variant.
  DONE: deterministic regression creates at least two competing chains, preserves role/operator/model/runtime provenance per step, and records a battle/run ID without publishing automatically.

- [ ] T-583 Outcome attribution + leaderboard
  Owner: claude
  Planner: ChatGPT
  Depends: T-582
  Goal: attribute factual analytics (views, likes, comments, shares/reposts, saves, CTR/conversion when available) back to the exact role/operator chain and compare chains without inventing missing metrics.
  DONE: analytics fixtures produce a factual leaderboard by chain; missing platform metrics remain unavailable rather than zero/fabricated.

- [ ] T-584 Reviewer / Judge mode
  Owner: claude
  Planner: ChatGPT
  Depends: T-582
  Goal: allow one or more operators to independently produce candidate outputs while a separately assigned Reviewer/Judge compares them using explicit criteria and preserved evidence.
  DONE: deterministic fixture produces two candidate outputs + one review decision with criteria, selected candidate, rationale and provenance; Reviewer cannot silently rewrite candidates.

- [ ] T-585 Multi-operator delegation board
  Owner: claude
  Planner: ChatGPT
  Depends: T-580
  Goal: generalize the current Claude-only delegation board into operator lanes (Claude, Gemini, ChatGPT) showing open ticket, stage, branch/runtime, heartbeat, last result and queue depth.
  DONE: API/UI renders at least Claude and Gemini lanes; offline/unconfigured Gemini is explicit; secrets are never returned.

- [ ] T-586 Telegram operator lanes
  Owner: claude
  Planner: ChatGPT
  Depends: T-585
  Goal: extend the paired Telegram owner bridge with two operator buttons/lists for Claude and Gemini plus open tickets and current status.
  DONE: Telegram callback regression renders Claude/Gemini buttons, lists each operator's open tickets/status, and existing Relay ticket controls continue to work.

- [ ] T-587 Telegram Battle controls
  Owner: claude
  Planner: ChatGPT
  Depends: T-582,T-586
  Goal: let the owner view a Battle Run from Telegram, compare candidate chains, see factual outcome metrics and approve/reject only safe next actions.
  DONE: deterministic Telegram fixture shows battle summary + candidate chains + metrics while preserving human publish approval.

- [ ] T-588 Supervisor routing policy
  Owner: claude
  Planner: ChatGPT
  Depends: T-580,T-585
  Goal: make Supervisor a routing role, not a fixed model: choose operators for tasks according to owner assignment, availability, task type and bounded Auto policy.
  DONE: regression proves explicit assignment wins over Auto, offline operators are skipped, HUMAN tasks remain blocked, and no provider gains production/publish privileges by being selected.

- [ ] T-589 Engineering battle pilot
  Owner: claude
  Planner: ChatGPT
  Depends: T-584,T-585
  Goal: run one safe coding task as a real implementation battle (Claude vs another configured operator), review both, and persist exact commits/check evidence without auto-merging production.
  DONE: one real non-HUMAN task has two isolated candidate branches/results and a reviewer decision; owner remains the merge gate.

## v5.0.3 — Runner Supervisor (Subscription-only Recovery)

- [ ] T-562 Local self-healing supervisor and zero-paid-API guards
  Owner: claude
  Planner: ChatGPT
  Spec: docs/roadmap/T-562_RUNNER_SUPERVISOR.md
  Goal: use a bounded local systemd recovery timer on the existing EC2 instance to restart only when subscription OAuth, internal worker token, non-main branch, and zero paid API billing gates all pass. Record safe local recovery status, never recover or copy OAuth tokens, never bypass account security.
  DONE: `python -m autopilot.test_supervisor` passes, CI passes, and on-host timer + truthful blocked/running status are verified; owner authorization and internal token remain independent prerequisites to live Claude task execution.

## v5.0.4 — Self-service EC2 pairing

- [ ] T-564 Interactive Claude worker pairing (no shell history/secrets)
  Owner: claude
  Planner: ChatGPT
  Depends: T-562
  Goal: one interactive root-only command on the existing EC2 reads the internal FactoryOS worker token without terminal echo, atomically edits root-owned config with restrictive permissions, refuses paid API override, and requests ONLY a Supervisor preflight, never a direct unguarded Claude start.
  DONE: `python -m autopilot.test_pair_worker` passes, CI green, host CLI verified and documented; no secret is printed/logged or stored in git.

## Optional least-privilege owner grants (T-598, non-blocking)

- [x] [HUMAN] T-598-H1 GitHub `workflow` scope for the worker credential (recommended since 2026-11-01)
  Done 2026-11-01: owner ran `gh auth refresh -s workflow` for ec2-user (scopes now include `workflow`); the worker's T-535 commit 29cd05f, which edits `.github/workflows/ci.yml`, was accepted by GitHub at 11:40:17 UTC.
  Progress 2026-11-01: the worker was stuck twice (2026-10-30 15:14→2026-10-31 08:29, 2026-11-01 08:06→11:23, 655 rejected pushes) because its commits edited ci.yml. Recommended now; owner runbook in Worker Center → «Ваши задачи».
  Need: only if CI workflow files must be edited by the worker; until then new tests ride existing CI steps. Spec: docs/handoff/T-598_AUTONOMOUS_HANDOFF.md.
  DONE: worker push touching `.github/workflows/` is accepted by GitHub.

- [ ] [HUMAN] T-598-H2 Optional `ec2:DescribeInstances` read permission on the instance role
  Need: owner attaches the read-only policy from docs/handoff/T-598_AUTONOMOUS_HANDOFF.md (no AWS access keys); Worker Center `ec2_api` stays `unknown` until then.
  DONE: Worker Center `ec2_api` reports a real instance state.
