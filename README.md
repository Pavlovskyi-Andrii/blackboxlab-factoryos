# Blackbox Lab — FactoryOS

Private AI content production control room for Blackbox Lab.

FactoryOS orchestrates specialized AI workers through a visible production pipeline while preserving a human approval gate before publishing. The service is deployed on Render from `main`.

## Product changelog

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
