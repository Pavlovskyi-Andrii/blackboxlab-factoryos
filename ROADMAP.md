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

- [ ] [HUMAN] T-507 Authorize Claude Code Pro
  Need: owner signs the native Claude Code CLI into the Pro subscription on a trusted PC/VPS runner using /login; keep ANTHROPIC_API_KEY unset so Pro usage is not overridden by separately billed API usage.
  DONE: FactoryOS Claude Code Pro connection reports runner online + subscription_verified.

- [ ] T-508 Claude delegation adapter
  Goal: let FactoryOS delegate a bounded task packet to Claude Code and ingest the result/commit/test evidence back into Builder state.
  DONE: deterministic regression proves task pinning, bounded execution, evidence capture and no direct main/prod action.

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
