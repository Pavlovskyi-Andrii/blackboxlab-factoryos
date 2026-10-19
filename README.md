# Blackbox Lab — FactoryOS

Private AI content production control room for Blackbox Lab.

FactoryOS orchestrates specialized AI workers through a visible production pipeline while preserving a human approval gate before publishing. The service is deployed on Render from `main`.

## Active roadmap

The living technical specification and progress tracker for the next major product cycle is here:

- [FactoryOS v4.0 — Technical Specification & Roadmap](docs/roadmap/FACTORYOS_V4_TECH_SPEC.md)

This document is the source of truth for milestone status, Definition of Done, progress checkboxes, known gaps and the next action from v3.25 through v4.0.

## Product changelog

### v3.24 — Mobile Control Room + Controlled Paid Verification — 2026-10-19
- Restored Agent Office worker cards on phone layouts instead of hiding them below 700 px; workers remain visible, live-state aware and clickable.
- Reworked mobile navigation into a horizontal touch rail and kept Jobs, Pipeline, Error Center, Outputs, Analytics, Release QA and worker drawers operational on small screens.
- Added mobile-safe layouts for creation forms, job controls, metrics, full-screen operational pages and agent detail drawers while preserving the existing desktop layout.
- Added an explicitly approved one-shot paid production verification that runs the pipeline to the QA approval gate, records real live-worker artifacts, input/output tokens and provider cost, and persists a pre-call fence so a restart cannot auto-repeat spend.
- Exposed only a safe verification summary through /health; artifact contents and secrets remain private.
- CI remains zero-spend because smoke tests clear the provider API key.


### v3.23 — Release Readiness / Morning QA — 2026-10-19
- Added a live Release QA workspace that summarizes production state, roadmap completion, failed jobs, open incidents, current provider spend and build identity.
- Added explicit runtime safety checks for the human approval gate, provider budget guards, spend-safe retry behavior, private authentication, live LLM configuration and Builder bridge.
- Added structured known-gap reporting instead of hiding incomplete capabilities: the controlled paid LLM end-to-end verification remains intentionally pending, and voice/video providers remain unconfigured.
- Added the /api/release-readiness endpoint and extended the zero-spend regression suite to protect its contract and safety invariants.
- Morning QA does not execute paid model calls.
- Verified live: GitHub CI passed Python, zero-spend regression, HTML and JavaScript checks; Render started v3.23 successfully with Builder/LLM readiness and health checks.

### v3.22 — Responsive / i18n + Regression Guard — 2026-10-19
- Localized Error Center, Worker Results, Handoff Trace and Factory Intelligence dynamic states across EN / UK / RU, including recovery confirmations and structured analytics insights.
- Removed stale hardcoded UI versioning and added mobile-first navigation/layout overrides for the new operational surfaces, drawers, analytics workspace and error recovery cards.
- Added a zero-spend standalone smoke/regression suite covering health/provider readiness, status data shapes, worker outputs/handoffs, approval gating, recovery retry policy, intelligence contracts and i18n completeness.
- Wired the regression suite into GitHub Actions alongside Python compilation, HTML structure checks and inline JavaScript syntax validation.
- Smoke tests explicitly clear the LLM API key, so CI cannot spend provider balance.
- Verified in production: GitHub CI passed all compile/smoke/HTML/JavaScript checks and Render deployed v3.22 with successful startup and health checks.

### v3.21 — Factory Intelligence — 2026-10-19
- Added a dedicated Analytics workspace comparing worker reliability, measured latency, tokens, provider cost, failures and artifact production.
- Added recent-job comparisons with persisted run cost/time/failures plus pipeline artifact coverage and stale-stage signals.
- Added evidence-based optimization insights for failure hotspots, cost drivers, latency bottlenecks and incomplete job coverage.
- Explicitly labels artifact coverage as pipeline readiness rather than inventing a subjective AI quality score.
- Uses existing persisted ledgers only; no destructive schema migration was introduced.
- Verified live on Render: successful build, application startup and production health checks.

### v3.20 — Operations & Error Center (Night 5) — 2026-10-19
- Added a dedicated Operations / Error Center with classified incidents, recovery guidance, resolved history and recorded run cost.
- Split billing, configuration, budget, dependency, rate-limit, provider-response, transport and unknown failures into explicit recovery policies.
- Automatic retry is now limited to explicitly safe transient failures; timeout/network/provider-uncertain cases require manual confirmation to reduce duplicate spend risk.
- Added stale-incident retry fencing and budget preflight checks to manual worker recovery.
- Reconciled Night 4 as deployed and verified Night 5 live on Render with successful startup and health checks.

### v3.4 — Live Pipeline Motion — 2026-10-19
- Added live stage highlighting driven by actual worker runtime state rather than a cosmetic timer.
- Active pipeline stages show the worker currently executing and a moving data packet toward the next stage.
- Existing Agent Office dependency edges continue to animate only when source/target activity is real.
- Preserved the human approval boundary before publishing.

### v3.3 — Handoff Trace Viewer — 2026-10-19
- Added clickable worker-to-worker handoffs on the main dashboard.
- Added persisted provenance tracing: exact artifact, source run, target run, stage, timestamps, token usage and provider cost.
- Trace Viewer uses recorded `run_inputs` and artifacts; it does not invent or reconstruct missing inputs.

### v3.2 — Worker Results & Handoffs — 2026-10-19
- Added latest output preview for every worker directly on the main dashboard.
- Added worker state, execution mode/model and visible failure state.
- Added incoming `← source` and outgoing `→ target` handoff chips.
- Added animated Agent Office dependency flow and a handoff activity stream.
- Worker cards remain clickable for full history, artifacts and accounting.

### v3.1 — Live LLM Hardening — 2026-10-19
- Hardened live LLM execution with bounded output tokens per worker call.
- Added conservative preflight budget checks so one paid call cannot knowingly exceed the configured job/day provider cap.
- Corrected failed-run accounting so failed live executions remain identified as `live_llm`.
- Preserved human approval before publishing and existing authentication boundaries.

### v3.0 — Overnight FactoryOS roadmap — 2026-10-18
- Introduced the overnight product-improvement roadmap and build manifest.
- Added structured roadmap steps for live LLM hardening, worker visibility, trace viewing, live pipeline visualization, error center, responsive/i18n work, smoke tests and morning QA.

## Safety invariants

- Human approval is required before publishing.
- Authentication must not be weakened as part of product iterations.
- Provider spend is bounded by configured job/day budgets.
- Secrets stay in environment variables and are never rendered in the UI.
- Product iterations avoid destructive schema/data migrations unless explicitly reviewed.

## Deployment

Render auto-deploys the `main` branch after the configured GitHub checks pass.
