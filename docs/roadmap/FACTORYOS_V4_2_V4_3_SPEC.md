# FactoryOS v4.2–v4.3 — UX Clarity, Worker Transparency & Revideo MVP

**Date:** 2026-10-20  
**Owner:** Factory Builder  
**Status:** ACTIVE  
**Source:** owner review of the live v4.1 UI after the first real LLM pilot.

## Why this exists

v4.1 proved the production loop can reach the human approval gate on real LLM work. The next bottleneck is not orchestration — it is trust and usability. The owner must immediately understand what every screen, metric, button, worker and artifact means, and must be able to inspect what every worker actually produced.

After that transparency layer is complete, FactoryOS will add a Revideo MVP: ingest a successful public video/topic, analyze its hook/structure, create an original evidence-bounded rewrite, prepare the new content package, and later hand it to a configurable media/video provider. The system must not clone or repost copyrighted video blindly; it should create an original inspired-by production package.

---

# v4.2 — UX Clarity / i18n / Worker Transparency

## Goals

1. No mixed-language UI on EN / UK / RU routes.
2. Every important control explains what it does.
3. Worker cards show the actual latest output for the selected job.
4. Clicking a worker opens the selected-job result first, before historical ledger data.
5. Approval Studio makes the approval decision understandable without inspecting logs.
6. Content Brain renders arbitrary backend values safely and never crashes on non-string data.
7. Existing human approval, spend guards and provenance remain unchanged.

## Required changes

### A. Crash/error fixes
- Replace unsafe browser string escaping with type-safe coercion.
- Normalize dates, object/array previews and provider payloads before rendering.
- Fix the live Content Brain error: `(s || "").replace is not a function`.
- Empty/missing fields render as an explicit localized empty state, never JS exceptions.

### B. Explanatory UX
Add a reusable help tooltip component to:
- Approval Studio;
- Autonomous Factory / Cycle Control;
- Content Brain;
- Variant Studio;
- Package Studio;
- Publishing Engine;
- Performance Feedback;
- Experiment Lab;
- Worker Results;
- Agent Office worker cards.

Tooltip content must answer:
- what this is;
- what it changes;
- whether it costs money;
- whether it can publish;
- what happens next.

### C. Complete EN / UK / RU localization
Move remaining user-facing dynamic labels into i18n:
- summary counters;
- workflow states;
- approval field labels;
- publishing actions;
- performance labels;
- cycle labels;
- worker drawer headings and explanations;
- empty states;
- prompts/confirmations where practical.

Technical IDs, provider names, model IDs and raw persisted artifact content are not translated.

### D. Worker Evidence
For the selected job, every worker card must expose:
- latest artifact title/kind;
- meaningful output preview;
- run status/mode/model;
- timestamp;
- tokens/cost;
- input handoffs;
- output artifact count;
- media URL if present.

Worker hover tooltip must show:
- role;
- current step;
- latest selected-job result;
- selected-job cost/tokens;
- click instruction.

Worker drawer must begin with a **Selected Job Result** section:
- full latest output content;
- media preview/link;
- exact artifact metadata;
- latest run accounting;
- input provenance.

Historical runs/artifacts remain below it.

### E. Approval Studio clarity
Each approval item must clearly explain:
- Hook — first 1–3 seconds / attention capture;
- Script — final narration/text;
- Sources — evidence used;
- Fact / QA warnings — risks before publishing;
- Variant diff — alternative versions and why selected;
- Publish target — nothing publishes until separate publish action;
- regeneration buttons — only that component is rerun and may cost money;
- approval button — sends to queue, does not publish.

Legacy verification jobs without a Content Package should be visually labelled **legacy / incomplete package**, so they are not confused with the real v4.1 pilot.

## Definition of Done — v4.2

- Content Brain screenshot case no longer throws a JS exception.
- EN / UK / RU UI regression checks pass for all new keys.
- Hovering a worker with selected-job output shows that actual output preview.
- Clicking that worker shows full selected-job artifact content at the top.
- Approval Studio clearly shows the real pilot package and labels legacy incomplete items.
- No paid provider calls in CI.

---

# v4.3 — Revideo MVP / Original Rewrite Pipeline

## Product intent

Turn a public successful video/topic into a new, original short-form concept and production package without blind copying.

### Input
- source URL;
- optional transcript supplied manually;
- optional title/topic/note;
- future transcript adapter.

### Pipeline

```text
Source video / URL
→ Transcript / source text
→ Structure Analyzer
→ Hook Pattern Extractor
→ Originality / Evidence Guard
→ Rewrite Strategist
→ New Script + Hook candidates
→ Fact Checker
→ Content Package
→ Human Approval
→ Video adapter / compositor
→ Publishing queue
```

### Required Revideo artifacts
- source reference;
- transcript or source notes;
- source hook pattern;
- pacing/structure analysis;
- reusable pattern description;
- prohibited-copy notes;
- new angle;
- new hook candidates;
- rewritten original script;
- source/evidence list;
- originality note;
- media brief;
- Content Package linkage.

### Guardrails
- Do not download/re-upload a source creator's media as a default workflow.
- Do not imitate a creator's identity/voice.
- New script must be materially rewritten and evidence-bounded.
- Source URL stays in provenance.
- Human approval remains mandatory before publishing.

### Provider interfaces
1. Transcript adapter:
   - manual transcript baseline;
   - generic webhook provider contract for STT/transcript extraction.
2. Video adapter:
   - generic webhook contract;
   - later providers can be configured without changing pipeline business logic.
3. Media output:
   - returned URL/file metadata is stored as a real artifact and visible in Worker Evidence.

### v4.3 MVP UX
A dedicated **Revideo** workspace:
- paste source URL;
- paste transcript/source text;
- Run analysis;
- see source pattern vs original rewrite side-by-side;
- create production job;
- open resulting Variant / Package / Approval workflow.

## Definition of Done — v4.3 MVP

- One source URL + transcript can produce an original rewrite record.
- Analysis/rewrite are persisted with provenance.
- User can create a production job from the rewrite.
- Worker results and resulting package are inspectable.
- No media is auto-published.
- If a video provider is configured, generated media becomes a real artifact; if not, UI explicitly says provider is not configured.
- CI remains zero-spend.
