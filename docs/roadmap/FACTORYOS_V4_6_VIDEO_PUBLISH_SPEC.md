# FactoryOS v4.6 — Video → Approval → Publishing

**Status:** IN PROGRESS — v4.6/v4.6.1/v4.6.2 are live and regression-verified. The only remaining closure gate is a configured real publisher plus one owner-approved external post receipt.  
**Goal:** carry the exact Media Finisher output through human approval into a duplicate-safe publishing action, persist the real platform receipt, and expose the same asset throughout Approval Studio and Publishing Engine.

## Pipeline

```text
raw/generated video
→ AI Media Finisher
→ final video artifact + QA evidence
→ HUMAN APPROVAL of that exact artifact
→ publishing_queue bound to package + variant + media artifact
→ schedule
→ explicit publisher adapter action
→ external post ID / URL
→ Publisher receipt artifact
→ published job/cycle
→ performance ingestion
```

## What v4.6 changes

### 1. Approval is media-aware

If a production job has a Media Finisher edit job, Approval Studio cannot approve it until the latest edit is `ready` and a publishable video artifact exists.

The approval payload records:
- final media artifact ID;
- Media Finisher edit-job ID;
- exact package/variant already used by the existing approval gate.

Text-only / legacy jobs that never entered Media Finisher preserve the existing approval behavior.

### 2. Publishing queue is bound to the exact final render

The idempotency key now includes:

```text
job + content package + selected variant + final media artifact + approved metadata snapshot hash
```

A new render therefore creates a distinct publish identity instead of accidentally reusing a queue item tied to an older video.

The queue persists:
- media artifact ID;
- media URL;
- media title / MIME type;
- Media Finisher edit-job ID;
- approval decision ID and approval timestamp;
- immutable publishing metadata snapshot;
- SHA-256 hash of that approved metadata snapshot.

If the selected variant or Content Package changes after Media Finisher renders, the older render is no longer approval-ready. The video must be rerun against the current package/variant before approval.

### 3. Publisher adapter receives the real media

The webhook contract now carries:
- `media_url`;
- media artifact provenance;
- platform / target / schedule;
- the **approved snapshot** of title, description, CTA, hashtags and thumbnail concept (never a later mutable package state);
- stable idempotency key.

FactoryOS still does not invent a platform receipt. A publish is only considered complete when the adapter returns a real external post ID, or the owner explicitly confirms a manual post.

### 4. Receipts close the loop

Both webhook and manual confirmation paths create a Publisher `publish_receipt` artifact with:
- external post ID;
- external URL;
- published time;
- platform;
- final media provenance;
- approval decision ID and approved content-snapshot hash.

The production job moves to `published`, and the Factory Cycle is synchronized into the analytics phase.

### 5. Scheduled execution

An optional scheduler can execute due, already-approved queue items:

- `FACTORY_PUBLISHER_SCHEDULER_ENABLED=1`
- `FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC=60` (15–600 supported)

It is off by default. Human approval and explicit scheduling remain mandatory.

## UI

Approval Studio:
- uses the finished Media Finisher artifact as the primary video preview;
- shows the exact artifact that will be approved;
- blocks approval if the latest Media Finisher run is not ready.

Publishing Engine:
- shows the bound final video;
- shows the immutable approved metadata snapshot, snapshot hash and approval decision;
- shows adapter / scheduler state;
- exposes real external post URL after publication.

## Acceptance checks

- [x] final Media Finisher artifact resolves into Approval Studio;
- [x] approval is blocked while a Media Finisher job is incomplete;
- [x] publish idempotency includes final media artifact + approved content snapshot hash;
- [x] publisher webhook payload contains final video URL + package metadata;
- [x] manual and adapter receipts preserve media + approval + content snapshot provenance;
- [x] published receipt updates job and Factory Cycle;
- [x] UI displays the approved/publish-bound video;
- [x] regression coverage added;
- [x] v4.6/v4.6.1 GitHub CI PASS and production deployment from `main`;
- [x] v4.6.2 code remains covered by current-main GitHub CI PASS (`39933231662`) and production deploy (`dep-dbdim1k9v7es73e0ulh0`);
- [ ] real publisher adapter configured;
- [ ] one owner-approved real social post verified end-to-end with external post ID/URL.

## Safety boundary

Media Finisher never auto-approves. v4.6 does not change that boundary.

A scheduled publisher can only act on an item that:
1. came from a human-approved job;
2. is bound to a specific package, variant and media artifact;
3. carries the immutable metadata snapshot that was approved;
4. was explicitly scheduled.

Retries reuse the same idempotency key. Uncertain external outcomes require confirmation before retry.
