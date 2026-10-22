# Blackbox Lab — FactoryOS

Private AI content production control room for Blackbox Lab.

FactoryOS orchestrates specialized AI workers through a visible production pipeline while preserving a human approval gate before publishing. The service is deployed on Render from `main`.

## Active roadmap

The living technical specification and progress tracker for the next major product cycle is here:

- [FactoryOS v4.0 — Technical Specification & Roadmap](docs/roadmap/FACTORYOS_V4_TECH_SPEC.md)
- [FactoryOS v4.5 — AI Editing / Media Finisher](docs/roadmap/FACTORYOS_V4_5_AI_EDITING_SPEC.md) — **DONE**: real uploaded-video production pilot verified end-to-end, with word-level ASR, deterministic cuts, captions/graphics, audio finishing, QA frame samples, traceable artifacts and return to HUMAN APPROVAL.
- [FactoryOS v4.6 — Video → Approval → Publishing](docs/roadmap/FACTORYOS_V4_6_VIDEO_PUBLISH_SPEC.md) — **IN PROGRESS**: bind the exact final Media Finisher artifact to approval, publishing, real platform receipt and analytics.

This document is the source of truth for milestone status, Definition of Done, progress checkboxes, known gaps and the next action from v3.25 through v4.0.

## Product changelog

### v4.6.1 — Exact Media Binding Hardening — 2026-10-22
- Runtime/UI version advanced from v4.5 to v4.6.1.
- Approval now resolves the video artifact from the latest exact Media Finisher edit job instead of choosing an arbitrary recent video.
- A finished render is invalidated for approval when the selected variant or Content Package changes after rendering; Media Finisher must rerun against the current production inputs.
- Regression coverage now proves stale media is blocked, then proves the newly rerun artifact is the exact asset carried into the publishing queue and publisher payload.

### v4.6 — Video → Approval → Publishing — IN PROGRESS — 2026-10-22
- Approval Studio now resolves the finished AI Media Finisher video as the primary review asset when an edit job exists, and blocks approval until the latest edit is READY.
- Publishing queue provenance is bound to the exact Content Package, selected variant and final media artifact; the media artifact participates in the duplicate-safe idempotency key.
- Publisher webhook payloads now include the approved final video URL/artifact plus title, description, CTA, hashtags and thumbnail concept from the Content Package.
- Manual and adapter publication paths persist Publisher receipts with external post ID/URL and final-media provenance, then synchronize the production job / Factory Cycle into published state.
- Publishing Engine now previews the actual bound video and exposes the real post URL; an optional due-item scheduler is available but remains disabled by default.
- Human approval remains mandatory. Real provider publication is not claimed until CI, deployment and one owner-approved external post are verified.

### v4.5 — AI Media Finisher — DONE — 2026-10-21 / 2026-10-22
- Added a separate Docker Media Finisher worker using FFmpeg, faster-whisper and a Remotion-capable renderer for deterministic short-form post-production; constrained workers use a CPU-safe FFmpeg overlay path.
- Added word timing, pause/duplicate cleanup, persisted cut lists, 1–3 word captions, jump-cut masking/push-ins, approved-text emphasis graphics, LUFS audio finishing and safe-zone evidence.
- Added traceable edit jobs/evidence in FactoryOS, stage reruns with parent lineage, final-video artifacts and forced return to HUMAN APPROVAL with no automatic publishing.
- Added direct raw-video upload to a selected production job. Uploads are stored as signed, unguessable source artifacts so the external Finisher worker can fetch them without weakening the private FactoryOS session boundary.
- Added in-dashboard Before/After video previews plus removed time, cut/caption/graphics counts, render stage and audio/safe-zone summary.
- Added deterministic QA frame sampling around selected cut boundaries and graphics moments; sample images are persisted with the edit report for visual review.
- Fixed callback/auth, cold-start recovery, source-download retry, Whisper/PyAV compatibility, server-side watchdog recovery and single-heavy-job serialization for the constrained Render worker.
- **Production pilot verified:** real uploaded source **349.7 s** → approximately **232 s** finished output, **126 cuts**, **103 caption groups**, **5 graphics**, edit job `1806649b-ca4f-4a0c-a9cd-5a7e7744328e` READY in **1592.41 s**, callback **HTTP 200**.
- A second serialized real-media job `1f276df4-a8c4-41e6-b29d-28ed3adebb12` also reached READY with callback HTTP 200, validating queue serialization and recovery.
- Human visual approval remains mandatory for each asset before publishing; v4.5 completion does not enable or bypass automatic publishing.

### v4.4 — Real Media Provider Foundation — 2026-10-20
- Added persistent asynchronous media jobs for Revideo with `queued → submitted → processing → ready/failed` lifecycle, provider job IDs, response/error persistence and duplicate-safe render visibility.
- Added provider polling through `FACTORY_VIDEO_STATUS_ENDPOINT` plus authenticated callback completion through `FACTORY_VIDEO_CALLBACK_TOKEN`.
- Revideo now exposes the latest media job, shows live render status in EN / UK / RU, prevents duplicate generation while a render is active and allows explicit status refresh.
- A completed provider result is persisted back to the Revideo project and saved as a real Render Agent video artifact for Worker Evidence.
- Added zero-spend regression coverage for the asynchronous media lifecycle; CI `39441923218` PASS.
- Production commit `7edec23c0d0258abb4978fcfbeab272d4260b97c`; Render deploy `dep-dbbnsjpsrm7s738fqbj0` LIVE with clean startup and repeated `/health 200 OK`.
- Completed a real Descript integration pilot in Blackbox Lab's Drive: Agent Underlord created an 8-second 1080×1920 / 30 fps composition and Descript published a real 1080p video successfully.
- **Status: DONE (provider-neutral foundation).** The generic media bridge and a real Descript provider path are verified. Runway runtime remains a separate adapter-specific verification backlog item and is not claimed as verified.
- Human approval and publishing remain separate; no automatic social publishing was enabled.

### v4.3 — Revideo / Original Rewrite MVP — 2026-10-20
- Added a dedicated Revideo workspace: source URL + transcript/source text → structure analysis → original rewrite → production job.
- Added persistent Revideo provenance and specialized Transcript Agent, Structure Analyzer and Rewrite Strategist worker evidence.
- Added originality guardrails: no blind source-media re-upload, no creator identity/voice imitation by default, no close-copy rewrite, and evidence boundaries remain explicit.
- Revideo output includes a new angle, hook candidates, rewritten script, caption, voice-over, originality notes and media brief.
- Revideo can hand off into the existing Variant → Content Package → Approval pipeline while preserving the source URL and worker artifacts.
- Added provider-neutral transcript and video webhook contracts. External video generation requires explicit confirmation and a fresh Content Package; no provider is hardcoded.
- If a configured video provider returns a real media URL, FactoryOS persists it as a Render Agent video artifact visible in Worker Evidence.
- No Revideo action publishes automatically.
- CI `39434473401` PASS; production commit `f7d7245db3f303f90a395377e44c360bbeb9fa34`; Render `dep-dbbn5aui0phs738nl4pg` LIVE with clean startup and repeated `/health 200 OK`.

### v4.2 — UX Clarity / i18n / Worker Transparency — 2026-10-20
- Added explanatory tooltips/help across Approval, Cycle Control, Content Brain, Variants, Package, Publishing, Performance, Experiments and Worker Results.
- Expanded EN / UK / RU product copy so workflow states and actions are understandable without reading technical logs.
- Worker cards now surface the selected-job result, output preview, mode/model, handoffs, token/cost accounting and artifact count; worker detail prioritizes the selected-job artifact.
- Approval Studio now explains what is being approved and distinguishes legacy/incomplete packages from current review-ready packages.
- Hardened UI rendering against non-string backend values and normalized structured artifact payloads before SQLite persistence.
- CI `39433576856` PASS; production commit `776266595cfd7a78d87490b4c9c6590006589fe1`; Render `dep-dbbn2h8473hc73dpqiig` was LIVE and then superseded by v4.3.

### v4.1 — Production Hardening / First Real LLM Pilot — 2026-10-20
- Ran the first fenced paid Factory Cycle on two real public source signals (Reuters + OpenAI) with one idea and a hard cumulative pilot ceiling of $0.75.
- Conservative preflight quote was $0.4636. The one-shot verification fence was persisted before the first provider call, preventing a restart from silently creating a second paid cycle.
- The first live pass uncovered a real SQLite writer-contention bug in the live variant persistence path after a completed model call. No publish action occurred.
- Hardened SQLite with a 30-second busy timeout and removed nested writer transactions by committing production-variant state before saving variant artifacts.
- Added a zero-spend regression that exercises the live variant persistence branch with deterministic fake workers, proving the production transaction path no longer deadlocks.
- Added resumable pilot execution on the same cycle and same original spend window, with a cumulative pilot budget guard applied to Content Brain, variant workers, Content Packager and live pipeline workers.
- Resumed the original cycle rather than starting over. The successful real pilot reached the human approval gate with cumulative measured provider cost **$0.188066**, **22 live runs** and **40,023 tokens**.
- Pilot result: `approval_gate_reached=true`, `publish_created=false`. Nothing was scheduled or published.
- Real pilot cycle: `15bea544-b055-44c6-84d4-833083c9befe`; job: `d0eeac5e-3fea-4fd2-bd22-2f15878101c2`; generated idea: **“AI’s Next Competitive Test: Turning Model Output Into Product Adoption”**.
- Hardening commit `7994b61f15c3d37dc80c70cf81dd80eeaafc6d6c`; CI `39424673537` PASS; resume deploy `dep-dbbm5j0ae00c7399k3t0` LIVE with repeated `/health 200 OK`.
- Next step is owner review in Approval Studio. Publishing remains a separate explicit action after review.

### v4.0 — Autonomous Content Factory — 2026-10-20
- Added persistent Factory Cycles that carry source signals, the selected idea, production job, workflow version, publishing receipt, factual performance and learning as one traceable lineage.
- Added a direct Content Brain → production bridge: verified ideas create linked production jobs without manual copy/paste, while preserving source provenance and the exact pinned workflow version.
- Added Autopilot orchestration that can collect/attach signals, generate and verify ideas, build production variants and a Content Package, and then **stops at the human approval gate**.
- Added explicit paid-work confirmation before Autopilot can start live model calls. Existing daily/job budget guards remain hard limits.
- Scheduled RSS collection can create a ready Factory Cycle from newly discovered signals, but never starts paid generation automatically.
- Approval, publishing state, real publish receipts and performance snapshots now synchronize back into the originating Factory Cycle.
- Added evidence-bounded cycle learning from real persisted metrics. Observed performance is never treated as causal proof; any workflow improvement becomes a controlled v3.90 experiment rather than an automatic production change.
- Added next-cycle lineage: a learned cycle can spawn a child cycle using only the currently owner-approved active workflow.
- Added mobile Autopilot / Cycle Control in EN / UK / RU.
- Zero-spend CI run `39406148458` passed the full deterministic closed-loop acceptance: signal → idea → production → package → human approval → publishing receipt fixture → real persisted metrics → learning → next cycle, plus compile/HTML/JavaScript checks.
- Functional commit `c02c568f3ad976286a7e8da5e7282013f06b4654`; production head `3cd54bba6aeaf0be33af863525ec3202b4aab7aa`; Render deploy `dep-dbbjsohsrm7s738a5bc0` is LIVE with clean startup and repeated `/health 200 OK`.
- No paid v4 production cycle and no real social post were executed as part of release verification.

### v3.90 — Self-Improving Factory — 2026-10-20
- Added evidence-backed improvement proposals with explicit hypotheses and concrete, allowlisted workflow changes.
- Added immutable workflow versions and locked job-level control/treatment assignment before the first worker run.
- Added controlled experiment objects that compare factual published outcomes plus measured production cost and duration; missing metrics remain absent.
- Added a production workflow fence: Supervisor proposals never auto-promote, safety/spend/publishing controls are not experiment-editable, and model changes are restricted to an explicit allowlist.
- Added manual owner-approved rollout, explicit reject decisions and rollback to the pre-rollout workflow version.
- Added Experiment Lab in EN / UK / RU for proposals, workflow diffs, arm assignment, measured comparison, rollout and rollback history.
- Added workflow/experiment attribution to published performance records so a result can be traced to the exact tested workflow version.
- Zero-spend CI run `39402528845` passed compile, deterministic control/treatment production, factual metric attribution, measured recommendation, manual rollout/rollback, HTML and JavaScript checks.
- Production commit `c9ef037db619b4e475bf9b66ed1c32442573a805` is LIVE on Render deploy `dep-dbbjeo1srm7s7389md60` with clean startup, configured LLM provider and repeated `/health 200 OK`.

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
