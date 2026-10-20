# Blackbox Lab — FactoryOS

Private AI content production control room for Blackbox Lab.

FactoryOS orchestrates specialized AI workers through a visible production pipeline while preserving a human approval gate before publishing. The service is deployed on Render from `main`.

## Active roadmap

The living technical specification and progress tracker for the next major product cycle is here:

- [FactoryOS v4.0 — Technical Specification & Roadmap](docs/roadmap/FACTORYOS_V4_TECH_SPEC.md)

This document is the source of truth for milestone status, Definition of Done, progress checkboxes, known gaps and the next action from v3.25 through v4.0.

## Product changelog

### v3.80 — Performance Feedback Loop — 2026-10-20
- Added persisted time-series performance snapshots for views, reach, watch time, retention, completion, engagement and follower delta without fabricating unavailable metrics.
- Added published-content identity mapping and traceable attribution back to idea, Content Package, selected variant, angle/hook, variant worker run IDs, source evidence and measured production cost.
- Added cost-per-1k-views only when real views exist plus angle cohort comparisons using only available retention/completion values.
- Added manual analytics input and a provider-neutral webhook analytics adapter; missing provider metrics remain absent.
- Added mobile Performance workspace for factual metrics, attribution and cohort comparison.

### v3.70 — Publishing Engine — 2026-10-20
- Approval no longer publishes automatically. It creates one idempotent publishing queue item tied to the approved package/variant.
- Added approved → scheduled → publishing → published/failed state handling, schedule model, publish attempt count, stable idempotency keys and external publish receipts.
- Added manual publisher confirmation as the safe baseline plus a provider-neutral webhook adapter for an external publisher.
- Uncertain external outcomes are persisted and require explicit confirmation before retrying the same idempotency key.
- Added mobile Publishing workspace for queue, scheduling, retry/history and real post confirmation.

### v3.60 — Approval Studio — 2026-10-20
- Added mobile-first Approval Studio with package preview context, final script/hook, source evidence, fact/QA warnings, measured cost, duration, variants, provenance and publish-target state.
- Added approve/reject with persisted reasons, approval history/audit records and variant comparison/diff context.
- Added targeted hook/script/caption/voice regeneration paths. Model regeneration shows a pre-call cost estimate; downstream invalidation remains scoped to affected components.
- Human approval is now explicitly separated from publishing.
- Release verification stayed zero-spend: CI `39391145024` passed compile, runtime regressions, HTML and JavaScript checks; production commit `e94cfff4094221acaf4f61b8c10ba9e7adfa1c01` is LIVE on Render deploy `dep-dbbi2m6k1f9s73bs9rk0` with clean startup and repeated `/health 200`.

### v3.50 — Content Package / Shorts Factory — 2026-10-20
- Added a persisted Content Package schema linked to the selected production variant and job.
- Packages now contain the final script, 1–3 second hook, scene breakdown, voice-over, generated SRT subtitles, title, description, CTA, hashtags, thumbnail concept, media brief, source list, fact-check report, structured QA, estimated duration and measured production cost.
- Added the Content Packager worker. Live package creation uses one explicit budget-guarded LLM call; CI and release regression use deterministic zero-spend package generation.
- Added provider-neutral media adapter contracts for TTS, image, video, stock/B-roll and manual media without hardcoding vendors into production workflow logic.
- Visual Director and Voice Agent now consume the selected Content Package manifest rather than raw script output.
- Added mobile-first Package Studio with scene/script/VO/SRT/source/fact-check/provider visibility.
- Added downloadable ZIP and JSON exports. ZIP bundles script, VO, subtitles, scenes, publishing metadata, sources, fact-check and media brief.
- Added stale-output fences: changing the selected variant invalidates the package and downstream pipeline; rebuilding a package invalidates Visual → Voice → Render → QA.
- Verified zero-spend CI run `39382663013` and production commit `54c17937242219d35c2df93f339a9dfba55802da` on Render deploy `dep-dbbgu2rm8hqs738tvkog`.

### v3.40 — Production Pipeline 2.0 — 2026-10-20
- Replaced the single script path with a three-variant production workflow: Angle Strategist → Hook Generator → Scriptwriter → Fact Checker → Hook Optimizer → Editor → structured QA.
- Added persisted production-variant batches with separate angle, hook, script, fact-check, edited-script, QA, decision and provenance data.
- Added structured QA findings instead of a synthetic quality score: unsupported claim, weak hook, duplicated angle, missing source, slow intro, unclear CTA, excessive length, unsafe/sensitive claim and fact conflict.
- Added automatic evidence-based recommendation plus manual winner selection in a mobile-first Variant Studio.
- Added targeted partial reruns for angle/hook/script/fact-check/hook optimization/editor/QA; reruns fence the job back to the script stage so stale downstream media cannot silently continue.
- Added variant cost comparison. Shared batch-run spend is allocated evenly for comparison while exact provider spend remains measured in the agent-run ledger.
- Updated pipeline/Agent Office visibility for the new worker graph and fixed live script-stage worker visualization.
- Extended zero-spend CI to generate and compare a three-variant demo batch without provider calls.
- Verified live: CI run `39380515484` passed; production commit `0410358433509703b5ae26f8e0246f625d967298`; Render deploy `dep-dbbgkaei0phs738fog7g` is live with clean startup and health checks.

### v3.30 — Content Brain / Idea Factory — 2026-10-20
- Added persistent source signals, idea storage, fingerprint deduplication and traceable provenance.
- Added manual/URL ingestion plus a configurable scheduled RSS source adapter through `FACTORY_SIGNAL_FEEDS`.
- Added the full idea pipeline: Scout → Researcher → Idea Strategist → Idea Verifier → Idea Queue.
- Researcher is constrained to persisted source signals; Strategist refines the content angle; Verifier returns shortlist/reject/needs-research decisions, risk flags and reasons.
- Added a mobile-first Content Brain workspace with signal ingestion, feed collection, shortlist generation, research/verification details, select/reject actions and one-tap creation of a production job.
- Preserved provider budget guards and explicit paid execution: release CI/verification remains zero-spend.
- Verified production on Render: commit `00225f9ed45253f33c1d9159eba2eb090e6e9fb1`, deploy `dep-dbbgdagubc0c73d4qbng`, successful startup and health checks.

### v3.25 — Baseline Closure — 2026-10-19
- Confirmed the controlled paid production run in Render: 7 live LLM runs, 9 artifacts, 5,846 total tokens and $0.029902 provider cost.
- Confirmed the pipeline stopped at `waiting_approval`, preserving the human approval gate before publishing.
- Synchronized `live-llm`, Night 1 hardening and mobile parity as completed in the build manifest.
- Disabled the one-shot paid verification startup trigger after success while retaining the historical evidence summary.
- Promoted the runtime build identity to v3.25 and moved the active roadmap to v3.30 Content Brain / Idea Factory.

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
