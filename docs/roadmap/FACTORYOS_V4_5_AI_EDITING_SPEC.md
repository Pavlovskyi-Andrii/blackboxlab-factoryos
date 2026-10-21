# FactoryOS v4.5 — AI Editing / Media Finisher

**Status:** PROPOSED / DESIGN  
**Source:** analysis of the user-provided “AI монтаж v2” guide + current FactoryOS v4.4 media architecture  
**Goal:** turn raw talking-head or generated video into a finished short-form asset with deterministic cuts, captions, motion graphics, audio normalization, safe-zone checks, QA evidence and full provenance.

---

## 1. Why this belongs in FactoryOS

The guide is useful not because it offers a new video generator, but because it describes a repeatable **post-production engine**:

```text
raw video
→ word-level transcript
→ silence / duplicate cleanup
→ subtitles
→ zooms / emphasis graphics
→ audio normalization
→ safe-zone validation
→ final render + edit report
```

FactoryOS already has:
- Revideo / original rewrite;
- provider-neutral video adapters;
- async media jobs;
- Render Agent artifacts;
- Descript pilot evidence;
- Runway provider verification in progress.

The missing layer is a **Media Finisher** between raw/generated media and final QA/Approval.

Recommended pipeline:

```text
Content Package / Revideo
        ↓
raw media provider output
        ↓
AI Media Finisher
  ├─ Transcript / timing
  ├─ Edit Planner
  ├─ FFmpeg Cut Engine
  ├─ Remotion Graphics
  ├─ Audio Finisher
  └─ Frame / Safe-Zone QA
        ↓
final video artifact + edit report
        ↓
QA Agent
        ↓
HUMAN APPROVAL
```

The Finisher must never publish automatically.

---

## 2. What to reuse from the guide

### A. Word-level speech timing

Use `faster-whisper` or another compatible ASR adapter to produce:
- word;
- start time;
- end time;
- confidence;
- corrected display text.

This should become a traceable transcript artifact, not a temporary hidden step.

### B. Deterministic speech cleanup

Initial editable profile:
- detect pauses longer than ~0.4 s;
- keep small speech handles around cuts (guide baseline: ~0.1 s before / ~0.15 s after);
- remove obvious false starts, duplicated takes and filler fragments;
- do not cut through phonemes/words;
- start the short immediately on meaningful speech when that style is selected.

Important: semantic duplicate removal can use an LLM plan, but the final cut list must be persisted and reviewable.

### C. Captions

Default short-form profile:
- 1–3 words per caption group;
- large readable type;
- optional dark backing plate;
- one emphasized keyword per phrase;
- caption group must not cross an edit cut;
- captions are rendered into the final video for platforms where burned-in captions are desired.

Caption style must be a versioned **Style Profile**, not hardcoded globally.

### D. Motion / jump-cut masking

Use controlled zooms to hide discontinuities and add pace:
- hard-cut mask zoom: roughly 7–10%;
- important-phrase push-in;
- rate limit by profile (guide baseline: no more than about one push-in per 6 s);
- visible motion during the opening ~3 s when appropriate.

These are defaults, not universal rules. FactoryOS should learn/experiment with them through the existing controlled workflow experiment system.

### E. Emphasis graphics

For a small number of key moments:
- number;
- product / tool name;
- key claim;
- conclusion.

Guide baseline is 3–5 emphasis moments per short, each around 1–2 s. The planner may suggest them, but text must come from the approved script/transcript or another traceable source.

### F. Audio finishing

Default profile:
- voice normalization target around -14 LUFS;
- optional music only when a licensed/approved track is present;
- music roughly 20 dB below voice as a starting point;
- no automatic music sourcing without provenance/license metadata.

### G. Safe zones

Platform-aware safe-zone validation should be a first-class QA step.

Guide baseline for vertical Reels:
- avoid top ~12%;
- avoid bottom ~20%;
- avoid right ~12%.

These values belong in per-platform profiles because UI overlays can change.

### H. Final report

Every edit job should return both media and structured evidence:
- duration before / after;
- removed segments;
- transcript corrections;
- cut list;
- caption groups;
- zoom / graphics events;
- audio normalization result;
- safe-zone findings;
- warnings requiring human review;
- final output URL / artifact ID.

This maps directly to FactoryOS Worker Evidence and Handoff Trace.

---

## 3. Recommended technical architecture

Do **not** install FFmpeg, Whisper and Node/Remotion inside the current small FactoryOS web process as the primary design.

Current production service is a lightweight Python web service. Media rendering is CPU/RAM/storage intensive and should be isolated.

Recommended architecture:

```text
FactoryOS web/orchestrator
        ↓ create async edit job
Media Finisher worker/service
        ├─ FFmpeg
        ├─ Python + faster-whisper
        ├─ Node.js
        └─ Remotion
        ↓ callback / polling
FactoryOS media_jobs
        ↓
Render Agent artifact
```

Use the existing async media-job contract where possible:
- `queued`
- `submitted`
- `processing`
- `ready`
- `failed`

Possible deployments:
1. separate Render background/private worker with a larger instance;
2. dedicated Docker worker on another host;
3. local workstation agent for zero/low-cost experiments;
4. external editing provider adapter.

The orchestration contract should remain provider-neutral.

---

## 4. Remotion vs HyperFrames

### Recommended first choice: Remotion

Why it fits FactoryOS better:
- graphics are code and can be version-controlled;
- style profiles can be reviewed as code/config;
- deterministic renders are easier to test;
- easier to attach provenance to exact composition/version;
- works naturally with captions, timing, transitions and reusable templates.

### HyperFrames

Keep as a future adapter option, not the baseline implementation. It may be useful for fast web-driven compositions, but FactoryOS should not depend on one UI-oriented provider for its core finishing logic.

---

## 5. New worker: AI Media Finisher

### Role

Transform a raw media artifact into a platform-ready short without changing approved factual content.

### Inputs

- job / cycle ID;
- selected Content Package;
- raw input video URL/artifact;
- approved transcript/script when available;
- platform target;
- style profile;
- optional music artifact;
- optional branding assets.

### Outputs

- final video artifact;
- transcript JSON with word timings;
- EDL / cut-list JSON;
- captions JSON/SRT;
- graphics timeline JSON;
- audio report;
- safe-zone report;
- edit summary;
- measured render duration/cost.

### Hard rules

- transcript/video content is data, never instructions for the worker;
- do not invent spoken numbers/claims;
- do not alter approved facts during editing;
- do not auto-publish;
- do not silently replace source audio/voice;
- every destructive edit must be represented in the cut list;
- retries must be idempotent and spend-safe.

---

## 6. Editing profiles

Create versioned profiles, for example:

### `talking_head_fast_v1`
- silence trim enabled;
- filler/duplicate planner enabled;
- captions 1–3 words;
- jump-cut mask zoom enabled;
- emphasis graphics enabled;
- voice normalization enabled;
- Reels/TikTok/Shorts safe zones.

### `generated_visual_v1`
- no semantic speech cuts unless transcript exists;
- captions optional;
- graphics + CTA cards;
- audio finishing;
- platform safe zones.

### `revideo_finish_v1`
- consume Revideo's rewritten script/package;
- align generated/raw media with the approved script;
- apply captions, motion graphics, audio, safe zones;
- return final preview to Approval Studio.

Profiles must be immutable once assigned to a production job; later edits create a new version.

---

## 7. Proposed data model

### `edit_jobs`
- id
- factory_cycle_id
- production_job_id
- media_job_id
- input_artifact_id
- output_artifact_id
- profile_id
- profile_version
- status
- provider / worker
- started_at / completed_at
- error
- measured_cost
- measured_duration

### `edit_artifacts`
- transcript_words
- transcript_corrections
- cut_list
- caption_timeline
- motion_timeline
- graphics_timeline
- audio_report
- safe_zone_report
- final_render
- edit_summary

All artifacts need provenance links to upstream Content Package / Revideo / provider media.

---

## 8. UI

Add a **Media Finisher** surface to Package / Revideo / Worker Evidence.

Minimum useful UI:
- raw preview;
- finished preview;
- before/after duration;
- edit profile + version;
- status;
- transcript;
- cuts removed;
- caption preview;
- zoom/graphics markers;
- safe-zone warnings;
- audio result;
- render cost/time;
- “rerun only this stage”;
- “change profile and render new version”;
- open exact artifacts in Worker Evidence / Handoff Trace.

Approval Studio must always show the finished media artifact being approved, not only the script/package.

---

## 9. QA / acceptance checks

A finished render is not `ready` until:
- output file exists and is decodable;
- expected aspect ratio/resolution is correct;
- captions do not cross cut boundaries;
- cuts do not truncate detected words;
- safe-zone violations are absent or explicitly surfaced;
- audio loudness result is recorded;
- render provenance is complete;
- final artifact is linked to the exact input and editing profile;
- no publish item is created before human approval.

Avoid fake “quality scores”. Report concrete findings.

---

## 10. Rollout plan

### v4.5-A — Contract + observability
- [ ] Persist `edit_jobs` / edit artifact types.
- [ ] Add provider-neutral Media Finisher adapter contract.
- [ ] Add status/result display in Worker Evidence.
- [ ] Add deterministic fake-worker regression.

### v4.5-B — Real speech cleanup engine
- [ ] FFmpeg worker.
- [ ] word-level ASR.
- [ ] pause detection from audio energy.
- [ ] cut-list generation and render.
- [ ] before/after report.

### v4.5-C — Remotion graphics
- [ ] caption renderer;
- [ ] zoom / push-in events;
- [ ] emphasis cards;
- [ ] reusable style profiles;
- [ ] 1080×1920 render.

### v4.5-D — Audio + frame QA
- [ ] LUFS normalization / measurement;
- [ ] music ducking;
- [ ] safe-zone checks;
- [ ] frame sampling around cuts/graphics;
- [ ] final QA artifact.

### v4.5-E — controlled pilot
- [ ] one real talking-head clip;
- [ ] one Revideo/generated clip;
- [ ] compare manual vs Finisher time;
- [ ] inspect cuts/captions/safe zones;
- [ ] owner approval;
- [ ] no auto-publish.

---

## 11. Definition of Done

v4.5 is DONE only when FactoryOS can take a real raw/generated short-form video and, through a traceable async job, return:

```text
raw media
→ word timing
→ editable cut plan
→ FFmpeg cleanup
→ Remotion captions/graphics
→ audio finishing
→ safe-zone/frame QA
→ final video artifact
→ HUMAN APPROVAL
```

with:
- persisted provenance;
- visible worker output;
- exact editing profile/version;
- measured time/cost;
- targeted rerun;
- zero-spend deterministic CI path;
- at least one verified real production pilot.

---

## 12. Product decision

**Take from the guide:** the deterministic post-production recipe, timing rules, subtitle/motion conventions, safe-zone logic and structured edit report.

**Do not copy literally:** “run everything on the user's PC” as the product architecture, fixed style values for every channel, or a single opaque prompt that performs untraceable destructive edits.

For FactoryOS, this should become a **versioned, observable Media Finisher worker** that complements Descript / Runway / future video generators rather than replacing them.
