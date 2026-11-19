# AI Media Finisher → autonomous AI Video Editor (v1, $0) — audit, upgrade proposal, first slice

GitHub #427 · Relay R-0089 · branch `relay/r-0089-dc5e1ebc` · 2026-11-19 · author: Claude

**Status: assigned → claimed (R-0089) → first slice implemented and tested at logic level → NOT completed.**
No real MP4 was rendered in this session: the agent host has no FFmpeg, faster-whisper or Remotion stack and no owner
footage. Acceptance on real footage is open (see §4).

## 1. AUDIT — what exists, what was missing

Most of the tutorial baseline was already built as `v4.5-ai-media-finisher`. This task must not rebuild it.

| Area | Already in the repo (before this branch) | Evidence |
|---|---|---|
| Pipeline | download (retry, size quota) → normalize → word-level ASR → silence/filler/exact-repeat cuts → FFmpeg cut → captions → motion/graphics → loudness → frame samples → callback | `media_finisher_worker/app.py` |
| ASR | faster-whisper `small`, word timestamps, VAD, separate process | `media_finisher_worker/transcribe_runner.py` |
| Captions | 1–3 words, keyword highlight, no group across a cut, SRT | `group_captions`, `_write_srt` |
| Render | Remotion composition, plus an FFmpeg/ASS engine for the low-memory worker | `remotion/src/index.tsx`, `_render_ffmpeg_fast` |
| Audio | `loudnorm` to −14 LUFS, measured after render; no music unless an approved asset exists | `_audio_finish` |
| Orchestration | one DBOS workflow per edit job, kill switch, legacy watchdog | `durable_media_finisher.py`, T-612 |
| Review | edit profiles, evidence artifacts, operator preview, QA hand-off, human approval gate | `app.py` (`MEDIA_FINISHER_EVIDENCE`, T-541), `test_media_finisher_preview.py` |

`factory_build_manifest.json` shows `v4.5-ai-media-finisher` as `in_progress` with `real_user_video_pilot: pending`.
That is a manifest label, not a running claim (#55).

Gaps found by reading the code (numbers 1–11 are closed by this branch at logic level):

1. The cut list had only start/end/reason: no confidence, no undo, no `edit-decisions.json`.
2. **Silence cuts ignored the transcript.** A quiet word below −35 dB inside an amplitude "silence" was cut out of the
   video, and `map_words_after_cuts` then dropped it from the captions without a trace. Nothing checked for lost words.
3. One fixed 0.4 s pause cutoff for every speaker.
4. `safe_zone_report.violations` was a hard-coded empty list.
5. **Captions sat inside the bottom safe zone.** Remotion: CSS resolves percentage padding against the frame *width*,
   so `paddingBottom: 24%` put the caption plate about 13.5 % above the bottom of a 1080×1920 frame (zone: 20 %), and
   top graphics at 9 % (zone: 12 %). FFmpeg/ASS engine: `MarginV` 18 % and 10 % against the same zones. Found by
   geometry; **not yet confirmed on a rendered frame**.
6. The 0.08 s caption tail overlapped the next group: two plates on screen for about two frames.
7. A zoom on every cut, including a 0.1 s removal and cuts 0.3 s apart.
8. A broken source failed with "Command … returned non-zero exit status", with no stage.
9. The final file was never decoded as a check; no black/silent-stretch check; no length-vs-cut-list check; no stage
   timing or resource numbers.
10. Remotion's `public/jobs/<id>` copy and all working copies stayed on the 5 GB disk forever.
11. No `source-reference.json`, `transcript.json`, `timeline.json`, `qa-report.json`, `render-metrics.json`.

Still missing after this branch: `preview.mp4` proxy, job cancellation, storage retention, version comparison, a UI
control for undo (the worker accepts it, the dashboard does not send it yet), face-aware framing, conditional denoise,
music ducking, presets B/C, checked Ukrainian ASR quality, and the real pilot.

## 2. MY UPGRADE

### What I would change in the spec
The tutorial optimises for visible effects. What makes an automatic edit look amateur is different: a clipped word, a
flash shot between two cuts, a caption under the platform UI, a zoom that shakes. So the order is **correctness of the
cut first, proof second, motion third**.

### Ranked upgrades (impact × build cost × runtime cost)

| # | Upgrade | Impact | Build | Runtime | Decision |
|---|---|---|---|---|---|
| 1 | Word-safe, reversible Edit Decision List with an independent word audit | high | low | none | **done here — the upgrade I own** |
| 2 | Measured QA gate: decode, black, silence, length, stream sync, estimated caption boxes | high | low | one decode pass | done here (pixels still human) |
| 3 | Shot-hold punch-in (alternate 100 % / 108 % per shot, hold to the next cut) instead of a 0.38 s pulse | high | low | none | V1.5 — needs a render to judge |
| 4 | Low-res `preview.mp4` + render cache keyed by source SHA-256, EDL hash and profile version | medium-high | medium | saves time | V1.5 |
| 5 | Face-aware caption placement and reframe (free CPU detector) | high on landscape sources | medium-high | moderate | V2, after the pilot |
| 6 | Hook variants as A/B drafts | medium | medium | 2× render | owner decision; no "viral score" |
| 7 | LLM semantic cuts (meaning-level repeats, false starts) | medium-high | medium | metered or non-deterministic | rejected for V1 ($0, determinism) |
| 8 | Beat matching | low | medium | low | rejected: no music by default |

### The upgrade I own: the cut is proven, not assumed
`media_finisher_worker/edit_decisions.py` (pure, deterministic):
- every proposed removal is one decision: kind, source range, reason, confidence, the words it removes, an undo handle;
- a silence cut is shrunk to the longest part that touches no transcribed word (30 ms guard); if nothing is left the
  pause is kept with `word_protected`;
- the pause cutoff follows the speaker (median gap × 2.5, never below the profile value, capped at 0.8 s);
- the pause after the end of a sentence keeps 0.1 s more; the video starts on speech;
- a low-confidence filler or repeat stays in the list as a proposal, not as a cut;
- a wordless sliver under 0.25 s between two cuts is merged instead of becoming a flash shot;
- `audit_cuts` re-checks the final cut list against the transcript without trusting the planner: `lost_words` and
  `clipped_words` must be empty;
- undo: `options.edit_overrides = {"restore_ids": ["d003"]}` or `{"restore_ranges": [{"start": 12.1, "end": 13.0}]}`.

Why this beats surface animation: it is the one property a viewer notices in the first seconds and an owner cannot
check by eye on every video, it costs no runtime, and it turns "trust the AI edit" into a list the owner can read and
reverse.

### Weak assumptions and safer fallbacks
- **Fixed 0.4 s pause**: now a floor, not a rule (above). The multiplier is a default to calibrate on real footage.
- **Zoom on every cut**: only when at least 0.25 s was removed and not within 0.8 s of the previous zoom.
- **Engagement claims**: none are made. Decisions, profile version and source hash are stored so real platform metrics
  can be compared later.
- **CPU-only runtime**: unmeasured until now. `render-metrics.json` records wall time per stage, real-time factor, child
  CPU seconds and peak memory. The low-memory worker renders with the FFmpeg/ASS engine and reports no motion.
- **Remotion licence**: free for individuals and very small companies, paid company licence above that — the owner
  should confirm against remotion.dev/license. The FFmpeg/ASS engine is the fallback with no such licence.
- **ASR timing**: Whisper word ends can stretch into a pause. The planner then keeps more of the pause (safe side).
  Trusting acoustics over a stretched word is a V1.5 item that needs real footage.

### V1 → V1.5 → V2
- **V1 (this branch + pilot)**: Talking Head 1080×1920, word-safe EDL, measured QA, artifacts per job, fail-closed
  source, cleanup. Benefit: no lost words, a readable and reversible edit list.
- **V1.5**: undo buttons in the preview, `preview.mp4`, render cache, shot-hold punch-in, cancellation, per-stage
  progress with `failed_stage` in the dashboard. Benefit: a second version in minutes instead of a full re-run.
- **V2**: face-aware placement, presets B (Dynamic Short) and C (AI Podcast/Explainer), analytics from real metrics.

Presets B and C remain data contracts only. Nothing in the UI says they work.

### Needs the owner's decision
1. Real, authorised source footage for the pilot (RU/UK/EN), and where the result may be stored.
2. Remotion licence status for the owner's company.
3. On a repeated phrase: remove the second copy (current) or the first (the usual "last take wins")?
4. An LLM pass for meaning-level cuts — only through an already-paid subscription route, or not at all.
5. Whisper `small` vs `medium` for Ukrainian/Russian accuracy against CPU time.
6. Presets B/C and hook variants: product scope.

## 3. EXECUTION

- **Claim**: Relay ticket R-0089 (single run). Local branch names show no other branch for this slice; open PRs were
  not checked (no GitHub access on the agent host).
- **Files**: `media_finisher_worker/edit_decisions.py`, `qa_checks.py` (new); `media_finisher_worker/app.py`
  (validate stage, decision list, QA report, metrics, artifacts, cleanup, caption tail, zoom gating, ASS margins,
  worker `v4.6.0-worker`); `remotion/src/index.tsx` (safe-zone offsets in pixels of height, plate width inside the
  side zones); `app.py` (three new evidence kinds in the preview: edit decisions, measured QA, render metrics).
- **Job artifacts** (in the worker's private job directory): `source-reference.json` (SHA-256, probe, host only — a
  signed URL is never stored), `transcript.json`, `edit-decisions.json`, `timeline.json` (output → source time map),
  `captions.srt`, `qa-report.json`, `render-metrics.json`, `final.mp4`. The unauthenticated `/files` route exposes
  nothing new; the JSON travels in the authenticated callback. `preview.mp4` is **not** produced yet.
- **Tests**: `python -m media_finisher_worker.test_edit_decisions` (planner + QA, pure),
  `python -m media_finisher_worker.test_pipeline_contract` (stage order, artifacts, undo, broken source, undecodable
  final, retry — FFmpeg/Whisper replaced by stand-ins, so it proves orchestration, not a render),
  `python -m media_finisher_worker.test_planner` (extended). All three are in CI.
- **Real artifact receipt**: none. Not claimed.

## 4. Open acceptance (not done)

| Acceptance item | State |
|---|---|
| Reproducible source → final MP4 on real footage, FFprobe + decode verified | open: needs the worker image and owner footage |
| No lost words at cuts | logic proven by tests; to confirm on real ASR output |
| Captions in safe zones, visible restrained motion | geometry fixed and estimated; **no rendered frame checked** |
| Audio and safe-zone report, EDL, timeline, cost/time | produced by the code path; real numbers come with the pilot |
| Preview + owner approval flow | existing gate unchanged; new evidence listed in the preview; undo UI open |
| Failure test for a broken source / retry | done with stand-ins |
| Green CI and a focused PR | CI not run from this host; the runner pushes the branch |

## 5. Proposed subtasks (no GitHub issues created)

| # | Subtask | Ready? |
|---|---|---|
| 1 | Pilot: one owner video through the deployed worker; attach receipts through private storage | blocked: owner footage |
| 2 | Render one fixture in the worker image in CI and check caption/graphic positions on frames | ready |
| 3 | Preview: list edit decisions with Restore → re-run with `edit_overrides` | ready after this branch merges |
| 4 | `preview.mp4` low-res proxy before the full export | ready |
| 5 | Cancel a worker job | ready |
| 6 | Shot-hold punch-in | after 2 |
| 7 | Render cache keyed by source SHA-256 + EDL hash + profile version | ready |
| 8 | Face detection for caption placement | after 1 |
| 9 | Ukrainian filler list and ASR accuracy check | after 1 |
| 10 | Dashboard per-stage progress with `failed_stage` and reason | ready |
| 11 | Build manifest: `v4.5-ai-media-finisher` must not read as "in progress" without a claim (#55) | ready |
| 12 | Retention and storage quota for worker job directories | ready |
