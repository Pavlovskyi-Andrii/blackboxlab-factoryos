# FactoryOS v4.7 — Direct Raw Video → Publishing

**Status:** IN PROGRESS — internal pipeline verified in CI and production; real external publisher post still pending.  
**Goal:** let an owner upload a raw video directly to AI Media Finisher and carry the finished deliverable all the way into the same human-approval and publishing system without forcing the normal idea/variant/LLM pipeline.

## Flow

```text
owner raw video upload
→ AI Media Finisher
→ finished master and/or Shorts/Reels clips
→ deterministic source-only publish pack (zero LLM spend)
→ QA evidence
→ HUMAN APPROVAL
→ immutable approved publish snapshot
→ explicit schedule
→ publisher adapter
→ real platform receipt
```

## Source-only publish pack

For a fresh job that enters through a direct raw upload, FactoryOS creates one synthetic source variant and one Content Package only after Media Finisher reaches READY.

The pack is derived from:
- persisted transcript words/captions from the Media Finisher report;
- owner-supplied job title and brief;
- measured final duration and Media Finisher cost;
- exact uploaded-media/edit-job provenance.

It does **not** invent:
- verified claims;
- CTA text;
- hashtags;
- thumbnail claims;
- external sources or performance metrics.

The fact-check state explicitly says that spoken claims were not independently verified and owner review is required.

## Deliverable selection

- Full-edit mode: the final Media Finisher master is reviewable/publishable.
- Split-only mode: the internal master is not exposed as a deliverable; the exact generated short clip becomes the approval/publishing asset.
- Full + split mode: the final master remains primary while short clips remain traceable artifacts.

## Safety

- The synthetic pack is only created for a fresh direct-upload job with no existing normal production package/selected variant.
- Existing partial production state is never silently replaced.
- Media Finisher still cannot approve or publish by itself.
- Publishing still requires human approval and an explicit schedule action.
- The immutable v4.6.2 approval snapshot remains the object passed to the publisher.

## Acceptance

- [x] direct upload can start Media Finisher without a pre-existing Content Package;
- [x] READY direct upload creates one selected source variant + one ready Content Package without an LLM call;
- [x] pack script comes from persisted transcript evidence when available;
- [x] source-only verification boundary is explicit;
- [x] split-only approval resolves the exact short clip, not the internal master;
- [x] direct raw job can pass human approval and enter the publishing queue;
- [x] UI route shows Media Finisher → Approval → Publishing;
- [x] GitHub CI PASS — run `39768976136`;
- [x] production deploy LIVE — FactoryOS `dep-dbcv090u01pc73bphrh0`, Media Finisher `dep-dbcv026k1f9s73b3piug`;
- [ ] owner-approved real platform post verified through configured publisher.
