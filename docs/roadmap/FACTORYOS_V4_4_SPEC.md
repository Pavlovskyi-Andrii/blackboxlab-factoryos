# FactoryOS v4.4 — Viral Discovery + Real Media Provider

**Date:** 2026-10-20  
**Owner:** Factory Builder  
**Status:** IN PROGRESS

## Goal

Close the remaining Revideo automation gap above and below v4.3:

```text
public outlier / breakout video
→ factual discovery metrics
→ transcript
→ Revideo original rewrite
→ normal production / Content Package
→ real generated media artifact
→ human approval
→ controlled publishing
```

Discovery must rank/compare only metrics actually supplied by the discovery source. Media generation must use original assets/prompts and must never bypass human approval.

## A. Viral Discovery

### Candidate schema
Persist:
- platform;
- source URL / external ID;
- video title;
- creator/channel;
- thumbnail;
- topic/language/format;
- published timestamp/duration;
- views;
- views per hour;
- engagement rate;
- breakout/outlier score supplied by provider;
- transcript when available;
- raw supported metrics;
- provenance;
- Revideo project linkage.

### Intake modes
1. Manual/API intake.
2. Generic discovery webhook provider.
3. Startup seed bridge for externally discovered candidates.
4. Scheduled topic discovery when a webhook + topics are configured.

### Honesty rule
FactoryOS must not invent a synthetic virality/quality score. Sorting may use provider-supplied breakout score/VPH/views, and missing metrics remain missing.

### UI
Dedicated Discovery workspace:
- factual metrics;
- thumbnail/source link;
- transcript preview;
- adapter status;
- manual candidate intake;
- provider collection;
- one-click Create Revideo.

## B. First real discovery validation

Use the connected vidIQ tool outside FactoryOS to validate discovery:
- niche: AI automation/tools;
- format: YouTube Shorts;
- use outlier/breakout performance;
- pull transcript for a promising candidate;
- feed the candidate into the FactoryOS discovery/Revideo path without copying its wording.

Initial candidate:
- video ID: `F716dUB2ZWE`
- title: `5 AI Tools Google Has That You NEED to Know`
- source: YouTube / Ben Kimball Ai
- observed discovery evidence at test time: ~108k views, breakout score ~53, engagement ~2.9%.
- transcript retrieved successfully through vidIQ.

The candidate is reference material for structure and topic mechanics only.

## C. Media Provider

v4.3 already has a provider-neutral video webhook contract. v4.4 must:
- expose whether a real endpoint is configured;
- require explicit external-cost confirmation;
- send a fresh Content Package;
- include guardrails: no source footage reuse and no creator identity/voice imitation;
- persist returned URL as a real Render Agent video artifact;
- make the artifact visible in Worker Evidence and Approval Studio.

A real external provider cannot be marked DONE until credentials/connection exist and one controlled media generation completes.

## Safety

- no automatic re-upload of source media;
- no identity/voice imitation of source creator;
- no automatic publishing;
- human approval required;
- transcript/video external providers require cost confirmation;
- provenance preserved end-to-end;
- CI must remain zero-spend.

## Definition of Done

### Discovery
- candidate persistence/dedup works;
- public performance metrics are preserved exactly;
- candidate converts to linked Revideo project;
- EN / UK / RU Discovery UI works;
- generic discovery provider contract works;
- scheduled collection only runs when explicitly configured;
- zero-spend CI passes.

### Real Media
- configured provider produces one real video artifact from a fresh Revideo Content Package;
- returned media can be previewed from Worker Evidence/Approval;
- human approval remains before publish;
- cost/external provider action is explicit and auditable.

