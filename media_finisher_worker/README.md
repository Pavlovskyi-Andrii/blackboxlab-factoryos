# FactoryOS v4.5 — AI Media Finisher worker

A separate heavy post-production worker for FactoryOS. The web control plane submits an immutable editing profile plus raw/generated media; this service performs deterministic media work and sends evidence back to FactoryOS.

## Implemented pipeline

1. Download source media without modifying it.
2. FFmpeg normalization to the profile target (default 1080×1920 / 30fps / H.264).
3. faster-whisper word-level timestamps.
4. FFmpeg silence detection; default threshold 0.4s with 0.10s / 0.15s handles.
5. Conservative exact-repeat detection for immediately duplicated phrases.
6. Non-destructive cut list plus clean render.
7. Caption groups of 1–3 words that do not cross cut boundaries.
8. Motion plan: 7–10% jump-cut masks, opening motion within 3s, sparse push-ins.
9. Approved-text-only emphasis graphics from the Content Package.
10. Remotion render for captions, motion and emphasis graphics.
11. FFmpeg voice loudness finish targeting −14 LUFS. Music is never added unless a future approved-asset input explicitly supplies it.
12. Safe-zone contract report (top 12%, bottom 20%, right 12%) plus mandatory visual-review note.
13. final.mp4 plus transcript/cut/caption/motion/graphics/audio/safe-zone/edit-summary evidence returned through the callback contract.

## Edit decisions and measured QA (GitHub #427)

- `edit_decisions.py` turns silences, fillers and exact repeats into a decision list: reason, confidence, removed words and an undo handle per decision. A silence cut never touches a transcribed word; the pause cutoff follows the speaker (never below the profile value). `audit_cuts` re-checks the final cut list for lost or clipped words.
- Undo: submit the job again with `options.edit_overrides = {"restore_ids": ["d003"]}` or `{"restore_ranges": [{"start": 12.1, "end": 13.0}]}` (source seconds).
- A source FFprobe cannot read, or one without video, audio or length, fails at the `validate` stage with a readable reason. A final file that does not decode is deleted and the job fails.
- `qa_checks.py` builds the QA report: decode of every frame, black and silent stretches, length against the cut list, stream lengths, caption timeline, loudness, and caption boxes *estimated* from the renderer's layout numbers. It does not look at pixels: face/object occlusion, readability and cut naturalness stay with the reviewer.
- Per job, next to `final.mp4` and `captions.srt`: `source-reference.json`, `transcript.json`, `edit-decisions.json`, `timeline.json`, `qa-report.json`, `render-metrics.json`. They are not served by `/files`; the same data goes to FactoryOS in the authenticated callback. Working copies are deleted after a verified final.
- Tests: `python -m media_finisher_worker.test_edit_decisions`, `python -m media_finisher_worker.test_pipeline_contract` (stand-ins instead of FFmpeg/Whisper: orchestration only, not a render).

The source video/text is always treated as material, never instructions. The worker cannot publish. FactoryOS moves the result back to HUMAN APPROVAL.

## API

- POST /jobs — submit an edit job.
- GET /jobs/{id} — poll status.
- GET /files/{id}/final.mp4 — final artifact.
- GET /health.

Set FINISHER_API_TOKEN for service auth. Set FACTORYOS_CALLBACK_BASE_URL and FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN so callbacks reach FactoryOS.

## Render

Deploy with media_finisher_worker/Dockerfile and attach a persistent disk at /var/data.

The first real pilot is still required before v4.5 is marked DONE. Human review must verify cut naturalness, face/object obstruction and caption readability. The current safe-zone evidence is an estimate from layout numbers, not computer-vision proof. Audit and plan: `docs/roadmap/AI_VIDEO_EDITOR_V1_PROPOSAL.md`.
