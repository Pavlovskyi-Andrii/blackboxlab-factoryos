# FactoryOS Roadmap

This file is the execution queue for the autonomous Factory Builder.

Rules:
- One task should fit roughly one focused implementation cycle.
- Every task must have an objective, machine-checkable DONE criterion.
- Tasks that require credentials, payment, account ownership, irreversible decisions, or an external human approval are marked `[HUMAN]`.
- Autopilot skips `[HUMAN]` tasks and continues with the next safe task.
- Human approval remains mandatory before any real social publishing action.

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
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A
  Goal: extend heartbeat/runtime telemetry with current stage, task start/elapsed time, branch/head, queue depth, safe CPU percent and memory usage when available, with null/unsupported fallbacks.
  DONE: heartbeat regression persists and renders telemetry without secrets; Linux/Termux metrics are numeric when available and unsupported platforms degrade cleanly.

- [x] T-536-C Planner hierarchy + delegation provenance
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A
  Goal: make ROADMAP tasks readable as a hierarchy (task/subtask), including planner/source, parent, dependency, Goal and DONE criteria so the owner can see exactly what ChatGPT delegated and why.
  DONE: parser/API expose parent/dependency/planner/goal/done-criteria metadata for representative tasks while remaining backward-compatible with existing ROADMAP entries.

- [ ] T-536-D Worker / Delegation Control Center UI
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-A,T-536-B,T-536-C
  Goal: add a dedicated Worker page: left column = ChatGPT/Planner queue and hierarchy; right column = Claude runner live state; top summary = online, current task, progress counts, branch and heartbeat age.
  DONE: desktop two-column and mobile stacked fixtures render queued/in-progress/done/blocked tasks, online/offline/stale worker, branch, stage, elapsed, CPU/memory when known, and remaining safe/HUMAN counts.

- [ ] T-536-E Delegation execution timeline
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-D
  Goal: show the lifecycle of each delegated task as a factual timeline: queued -> picked -> running -> checks -> commit -> push -> done/blocked/failed, with timestamps, commit SHA, changed files and checks.
  DONE: verified task-result fixtures render timeline events and link the exact commit/check evidence; missing events are shown as unavailable rather than invented.

- [ ] T-536-F Safe operator controls
  Planner: ChatGPT
  Parent: T-536
  Depends: T-536-D
  Goal: provide safe remote controls for the daemon: pause after current task, resume, and retry a blocked/failed safe task; never expose force-push, main checkout, production deploy or publish bypass.
  DONE: command channel is idempotent, authenticated, auditable and regression proves pause/resume/retry cannot bypass main/prod/publish safety invariants.

- [ ] T-532 Live pipeline + handoff trace
  Goal: make the main FactoryOS pipeline visually show current movement and worker-to-worker handoffs instead of only static cards.
  DONE: a deterministic workflow fixture renders ordered source artifact -> worker run -> output -> downstream worker edges with running/done/blocked/failed states and a usable mobile fallback.

- [ ] T-533 Explainability + tooltips
  Goal: remove ambiguity around Hook, Script, Caption, Voice and the Cycle/Idea/Job/Review/Learned stages with concise contextual help.
  DONE: EN/UK/RU tooltip/help copy exists for the canonical concepts, hover/focus/tap access is keyboard/mobile safe, and regression prevents missing help keys.

- [ ] T-534 EN/UK/RU localization parity
  Goal: remove mixed-language UI leftovers and keep the three supported locales structurally in sync.
  DONE: an automated locale-parity regression catches missing canonical dashboard keys and the representative EN/UK/RU dashboard fixture contains no known cross-locale fallback strings.

- [ ] T-535 Artifact + media viewer hardening
  Goal: make agent artifacts and finished media reliably open from Worker Results, Trace Viewer and Approval flows while preserving signed-media/auth boundaries.
  DONE: deterministic regression opens representative text, JSON, subtitle and video artifacts through the intended viewer/media routes with correct content handling and no broken known-artifact links.

## v5.4 — Revideo Production Hardening

- [ ] T-540 Revideo zero-spend acceptance
  Goal: prove the full safe content path Discovery candidate -> Revideo -> rewrite -> Content Package -> Media Finisher -> HUMAN APPROVAL on deterministic fixtures.
  DONE: acceptance reaches waiting_approval with provenance and originality evidence intact, creates no real provider spend and cannot auto-publish.

- [ ] T-541 Media Finisher operator preview
  Goal: make the final-video review path obvious before approval, including source/final preview and the produced cuts/captions/audio/graphics artifacts that actually exist.
  DONE: deterministic UI/API regression exposes available before/after media plus generated artifact links, gracefully marks absent optional artifacts, and preserves the approval gate.

- [ ] T-542 Publishing dry-run evidence
  Goal: validate the exact immutable media+metadata snapshot that would be sent to YouTube Shorts, TikTok and Instagram Reels without making a real external post.
  DONE: zero-spend dry-run produces a traceable publisher plan/receipt preview bound to the approved snapshot; no external post ID is fabricated and real publish still requires T-520/T-521.
