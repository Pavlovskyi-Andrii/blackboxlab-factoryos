"""Edit Decision List + objective QA checks (GitHub #427, R-0089). Pure Python: no FFmpeg, no FastAPI."""
from media_finisher_worker import edit_decisions as edl, qa_checks

PROFILE = {"speech_cleanup": {"silence_trim": True, "pause_threshold_sec": 0.4, "pre_handle_sec": 0.1, "post_handle_sec": 0.15,
                              "semantic_duplicate_planner": True, "start_on_speech": True}}


def w(word, start, end, confidence=0.98):
    return {"word": word, "start": start, "end": end, "confidence": confidence}


def by_kind(plan, kind):
    return [d for d in plan["decisions"] if d["kind"] == kind]


# 1. A plain pause: same handles as before, one applied decision with a reason, a confidence and an undo handle.
words = [w("hello", 0.0, 0.3), w("world", 0.32, 0.6), w("again", 1.8, 2.1)]
plan = edl.plan_edits([{"start": 0.7, "end": 1.7, "reason": "silence>0.40s"}], words, 3.0, PROFILE)
assert [(c["start"], c["end"]) for c in plan["cuts"]] == [(0.8, 1.55)], plan["cuts"]
d = plan["decisions"][0]
assert d["applied"] and d["kind"] == "silence" and d["confidence"] == 0.95 and d["id"] == "d001"
assert d["restore"] == {"option": "edit_overrides.restore_ids", "value": "d001"} and plan["cuts"][0]["decision_ids"] == ["d001"]
audit = edl.audit_cuts(words, plan["cuts"], plan["decisions"])
assert audit["ok"] and audit["kept_words"] == 3 and not audit["removed_words"]

# 2. Undo by id and by source range: the cut disappears, the decision stays visible with the reason it was kept.
for overrides in ({"restore_ids": ["d001"]}, {"restore_ranges": [{"start": 0.9, "end": 1.5}]}):
    restored = edl.plan_edits([{"start": 0.7, "end": 1.7}], words, 3.0, PROFILE, overrides)
    assert restored["cuts"] == [] and restored["decisions"][0]["kept_reason"] == "restored_by_reviewer"
# Overrides are untrusted input: a wrong shape changes nothing.
for junk in ("restore everything", {"restore_ids": "d001"}, {"restore_ranges": ["x"]}, None):
    assert edl.plan_edits([{"start": 0.7, "end": 1.7, "reason": "silence>0.40s"}], words, 3.0, PROFILE, junk)["cuts"] == plan["cuts"]

# 3. A quiet word inside an amplitude "silence" is never cut: the cut shrinks to the longest word-free part.
quiet = [w("so", 0.0, 0.3), w("yes", 1.0, 1.2), w("next", 2.6, 2.9)]
plan = edl.plan_edits([{"start": 0.4, "end": 2.5}], quiet, 3.2, PROFILE)
d = plan["decisions"][0]
assert d["applied"] and d["confidence"] == 0.8 and "yes" in d["notes"][0]
assert (d["source_start"], d["source_end"]) == (1.23, 2.35), d
audit = edl.audit_cuts(quiet, plan["cuts"], plan["decisions"])
assert audit["ok"] and audit["kept_words"] == 3
# The old planner cut 0.5-2.35 here and dropped "yes" from the video and the captions; the audit catches exactly that.
bad = edl.audit_cuts(quiet, [{"start": 0.5, "end": 2.35}], [])
assert not bad["ok"] and [x["word"] for x in bad["lost_words"]] == ["yes"]
clipped = edl.audit_cuts(quiet, [{"start": 0.4, "end": 0.95}, {"start": 2.5, "end": 2.7}], [])
assert not clipped["ok"] and [x["word"] for x in clipped["clipped_words"]] == ["next"]
# No word-free part long enough -> the pause is kept and says why.
crowded = [w("a", 0.0, 0.5), w("b", 0.62, 0.9), w("c", 0.95, 1.4)]
plan = edl.plan_edits([{"start": 0.45, "end": 1.1}], crowded, 2.0, PROFILE)
assert plan["cuts"] == [] and plan["decisions"][0]["kept_reason"] == "word_protected"

# 4. The pause after the end of a sentence keeps a longer breath than a pause in the middle of one.
mid = edl.plan_edits([{"start": 1.0, "end": 2.0}], [w("one", 0.5, 0.9), w("two", 2.1, 2.4)], 3.0, PROFILE)["cuts"][0]
end = edl.plan_edits([{"start": 1.0, "end": 2.0}], [w("one.", 0.5, 0.9), w("Two", 2.1, 2.4)], 3.0, PROFILE)["cuts"][0]
assert mid["start"] == 1.1 and end["start"] == 1.2 and mid["end"] == end["end"] == 1.85

# 5. The video starts on speech: leading dead air goes without a pre-handle.
lead = edl.plan_edits([{"start": 0.0, "end": 1.0}], [w("hi", 1.05, 1.3)], 2.0, PROFILE)["cuts"][0]
assert (lead["start"], lead["end"]) == (0.0, 0.85)

# 6. Adaptive pause cutoff: a slow speaker's ordinary gaps are not cut, a fast speaker keeps the profile value.
slow = [w(f"w{i}", i * 0.8, i * 0.8 + 0.5) for i in range(20)]                # every gap is 0.3 s
slow_plan = edl.plan_edits([{"start": 0.52, "end": 0.78}, {"start": 8.5, "end": 8.8}], slow, 16.0,
                           {"speech_cleanup": {"pause_threshold_sec": 0.25, "pre_handle_sec": 0.05, "post_handle_sec": 0.05}})
assert slow_plan["pause_threshold"]["method"] == "speaker_median_gap_x2.5" and slow_plan["pause_threshold"]["effective_sec"] == 0.75
assert slow_plan["cuts"] == [] and all(d["kept_reason"] == "below_adaptive_pause_threshold" for d in slow_plan["decisions"])
fast = [w(f"w{i}", i * 0.35, i * 0.35 + 0.3) for i in range(20)]
assert edl.adaptive_pause_threshold(fast, {"pause_threshold_sec": 0.4})["effective_sec"] == 0.4
assert edl.adaptive_pause_threshold(slow, {"pause_threshold_sec": 0.4, "adaptive_pause": False})["method"] == "fixed"
assert edl.adaptive_pause_threshold(words, {})["method"] == "fixed_too_few_gaps"

# 7. Fillers (RU/UK/EN): removed with the word named; a low-confidence one may be a real short word and is kept.
filler_profile = {"speech_cleanup": {"silence_trim": False, "filler_trim": True, "semantic_duplicate_planner": False}}
fillers = [w("Привет", 0.0, 0.35), w("э", 0.42, 0.67, 0.97), w("мир", 0.75, 1.05), w("эм", 1.18, 1.42, 0.3), w("дальше", 1.5, 1.9),
           w("е-е", 2.0, 2.3, 0.9), w("um,", 2.4, 2.6, 0.9), w("ok", 2.7, 2.9)]
plan = edl.plan_edits([], fillers, 3.0, filler_profile)
kept = [d for d in plan["decisions"] if not d["applied"]]
assert plan["summary"]["applied_by_kind"]["filler"] == 3 and len(kept) == 1 and kept[0]["kept_reason"] == "low_asr_confidence"
audit = edl.audit_cuts(fillers, plan["cuts"], plan["decisions"])
assert audit["ok"] and sorted(x["word"] for x in audit["removed_words"]) == ["um,", "е-е", "э"] and audit["kept_words"] == 5

# 8. An immediately repeated phrase: the second copy is proposed for removal, every removed word is listed.
dup = [w("we", 0, .2), w("can", .25, .5), w("we", .9, 1.1), w("can", 1.15, 1.4), w("start", 1.5, 1.9)]
plan = edl.plan_edits([], dup, 2.2, {"speech_cleanup": {"silence_trim": False, "filler_trim": False}})
d = by_kind(plan, "duplicate")[0]
assert d["applied"] and [x["index"] for x in d["removed_words"]] == [2, 3] and (d["source_start"], d["source_end"]) == (0.9, 1.4)
assert edl.audit_cuts(dup, plan["cuts"], plan["decisions"])["ok"]
unsure = [dict(x, confidence=0.4) for x in dup]
assert edl.plan_edits([], unsure, 2.2, {"speech_cleanup": {"silence_trim": False, "filler_trim": False}})["cuts"] == []

# 9. Two cuts with an empty sliver between them are joined (no flash frame); a sliver holding a kept word is not.
joined = edl.plan_edits([{"start": 0.35, "end": 0.92}], [w("go", 0.0, 0.3), w("uh", 0.75, 0.9), w("on", 1.2, 1.5)], 2.0,
                        {"speech_cleanup": {"pause_threshold_sec": 0.4, "pre_handle_sec": 0.05, "post_handle_sec": 0.05,
                                            "semantic_duplicate_planner": False}})
assert len(joined["cuts"]) == 1 and len(joined["cuts"][0]["decision_ids"]) == 2, joined["cuts"]
assert edl.audit_cuts([w("go", 0.0, 0.3), w("uh", 0.75, 0.9), w("on", 1.2, 1.5)], joined["cuts"], joined["decisions"])["ok"]

# 10. Deterministic: the same input gives the same decisions and ids.
assert edl.plan_edits([{"start": 0.4, "end": 2.5}], quiet, 3.2, PROFILE) == edl.plan_edits([{"start": 0.4, "end": 2.5}], quiet, 3.2, PROFILE)

# --- QA checks -------------------------------------------------------------------------------------------------------
ok_probe = {"duration": 12.0, "width": 1080, "height": 1920, "video_codec": "h264", "audio_codec": "aac"}
assert qa_checks.source_problems(ok_probe, 5_000_000) == []
assert qa_checks.source_problems({**ok_probe, "audio_codec": ""}, 5_000_000) == ["no audio stream (speech is required)"]
assert "no decodable video stream" in qa_checks.source_problems({**ok_probe, "video_codec": "", "width": 0}, 5_000_000)
assert len(qa_checks.source_problems({"duration": 0}, 10)) == 4

ZONES = {"top": 0.12, "bottom": 0.20, "right": 0.12, "left": 0.0}
caps = [{"start": 0.0, "end": 0.9, "text": "we can start", "words": ["we", "can", "start"]},
        {"start": 0.9, "end": 1.8, "text": "автоматически использовать преимущества", "words": ["автоматически", "использовать", "преимущества"]}]
for engine in ("remotion", "ffmpeg_fast"):
    short = qa_checks.safe_zone_violations(caps[:1], ZONES, 1080, 1920, engine)
    assert short["method"] == "estimated_caption_bbox_v1" and short["violations"] == [] and short["checked"] == 1, (engine, short)
# Both engines wrap a long group between words (the ASS style used to be one line and ran into the side zones:
# seen on a rendered frame on 2026-11-20, fixed with WrapStyle 0). A single word wider than the plate still overflows.
for engine in ("remotion", "ffmpeg_fast"):
    assert qa_checks.safe_zone_violations(caps, ZONES, 1080, 1920, engine)["violations"] == [], engine
    giant = qa_checks.safe_zone_violations([{"text": "x" * 40}], ZONES, 1080, 1920, engine)["violations"]
    assert "word_overflow" in [x["edge"] for x in giant], (engine, giant)
box = qa_checks._caption_box("как искусственный интеллект", ZONES, 540, 960, "ffmpeg_fast")
assert box["x1"] <= 540 * (1 - 0.12) and box["y1"] <= 960 * (1 - 0.20) and box["y1"] - box["y0"] > 2 * 33   # two rows, in the zones
assert qa_checks.safe_zone_violations(caps, ZONES, 1080, 1920, "ffmpeg_captions_only")["method"] == "not_estimated_for_engine"
# Both renderers keep captions out of the zones the profile gives them, including a wider right zone.
layout = qa_checks.ass_layout(1080, 1920, ZONES)
assert layout["caption_margin_v"] >= 1920 * 0.20 and layout["graphic_margin_v"] >= 1920 * 0.12 and layout["margin_h"] >= 1080 * 0.12
assert qa_checks.remotion_caption_max_width(ZONES) == 0.76 and qa_checks.remotion_caption_max_width({"right": 0.2}) == 0.6

issues = qa_checks.caption_timeline_issues(
    [{"start": 0.0, "end": 1.0, "words": ["a"]}, {"start": 0.9, "end": 2.0, "words": ["a", "b", "c", "d"]}, {"start": 2.0, "end": 9.0, "words": ["z"]}],
    [1.5], 3.0)
assert sorted((x["caption_index"], x["issue"]) for x in issues) == [(0, "overlaps_next"), (1, "crosses_cut"), (1, "more_than_three_words"), (2, "past_end_of_video")]
assert qa_checks.caption_timeline_issues(caps, [0.9], 2.0) == []

assert qa_checks.duration_check(60.0, 12.5, 47.55)["ok"] and not qa_checks.duration_check(60.0, 12.5, 49.0)["ok"]
assert qa_checks.stream_sync_check({"video_duration": 47.5, "audio_duration": 47.52})["status"] == "pass"
assert qa_checks.stream_sync_check({"video_duration": 47.5, "audio_duration": 46.9})["status"] == "warn"
assert qa_checks.stream_sync_check({})["status"] == "not_run"

assert qa_checks.qa_report([{"id": "a", "status": "pass"}])["overall"] == "pass"
assert qa_checks.qa_report([{"id": "a", "status": "pass"}, {"id": "b", "status": "not_run"}])["overall"] == "incomplete"
assert qa_checks.qa_report([{"id": "a", "status": "warn"}, {"id": "b", "status": "not_run"}])["overall"] == "needs_review"
report = qa_checks.qa_report([{"id": "a", "status": "warn"}, {"id": "b", "status": "fail"}])
assert report["overall"] == "fail" and report["human_review_required"] is True and "face/object occlusion" in report["not_checked"]
# --- #427 follow-up: a repeat or filler cut follows the sound, not only the ASR word times -------------------------
# From the real run of 2026-11-20: the repeated phrase was reported as ending at 29.44 s while speech ran to 29.83 s;
# the cut ended at 29.44 and 0.39 s of the removed word stayed in the video.
said = [w("громкость", 23.72, 24.36), w("голоса", 24.40, 24.88), w("выравнивается", 25.00, 25.76), w("автоматически", 25.96, 26.68),
        w("выравнивается", 27.76, 28.56), w("автоматически", 28.76, 29.44), w("конце", 31.04, 32.04), w("получается", 32.16, 32.72)]
quiet = [{"start": 27.04, "end": 27.656}, {"start": 29.829, "end": 31.01}]
profile = {"speech_cleanup": {"pause_threshold_sec": 0.4, "pre_handle_sec": 0.1, "post_handle_sec": 0.15}}
plan = edl.plan_edits(quiet, said, 36.0, profile)
repeat = by_kind(plan, "duplicate")[0]
assert repeat["applied"] and repeat["source_end"] >= 29.829 and repeat["source_start"] <= 27.66, repeat
assert any(n.startswith("end_moved_to_silence_edge") for n in repeat["notes"])
audit = edl.audit_cuts(said, plan["cuts"], plan["decisions"])
assert audit["ok"] and audit["wordless_slivers"] == [], audit["wordless_slivers"]
assert not any(29.44 < c["start"] < 29.83 or 29.44 < c["end"] < 29.82 for c in plan["cuts"])   # no edge inside the leftover speech
# One cut now covers the pause, the repeat and the pause after it.
assert any(c["start"] <= 27.2 and c["end"] >= 30.8 for c in plan["cuts"]), plan["cuts"]

# The edge never crosses a neighbouring kept word, and never moves when no silence is near.
tight = [w("one", 0.0, 0.4), w("two", 0.5, 0.9), w("one", 1.0, 1.4), w("two", 1.5, 1.9), w("three", 2.05, 2.5)]
plan = edl.plan_edits([{"start": 1.95, "end": 2.6}], tight, 3.0, {"speech_cleanup": {"silence_trim": False}})
repeat = by_kind(plan, "duplicate")[0]
assert repeat["source_end"] <= 2.05 - edl.WORD_GUARD_SEC + 1e-6 and repeat["source_start"] == 1.0, repeat
assert edl.audit_cuts(tight, plan["cuts"], plan["decisions"])["ok"]
plan = edl.plan_edits([{"start": 5.0, "end": 6.0}], tight, 7.0, {"speech_cleanup": {"silence_trim": False}})
assert by_kind(plan, "duplicate")[0]["source_end"] == 1.9 and by_kind(plan, "duplicate")[0]["notes"] == []

# The audit names what the transcript cannot prove: a wordless sliver between two cuts, and a long pause that stayed.
talk = [w("alpha", 0.0, 0.5), w("beta", 3.0, 3.5)]
audit = edl.audit_cuts(talk, [{"start": 0.6, "end": 1.2}, {"start": 1.55, "end": 2.9}], [])
assert audit["ok"] and audit["wordless_slivers"] == [{"source_start": 1.2, "source_end": 1.55, "seconds": 0.35}]
audit = edl.audit_cuts(talk + [w("gamma", 1.25, 1.5)], [{"start": 0.6, "end": 1.2}, {"start": 1.55, "end": 2.9}], [])
assert audit["wordless_slivers"] == []                                                # a kept word lives there
audit = edl.audit_cuts(talk, [{"start": 0.6, "end": 1.0}, {"start": 2.0, "end": 2.9}], [])
assert audit["wordless_slivers"] == []                                                # a second of footage is not a sliver
kept_pause = {"id": "d001", "kind": "silence", "applied": False, "source_start": 6.07, "source_end": 7.61, "pause_sec": 1.55,
              "kept_reason": "word_protected", "removed_words": []}
short_pause = dict(kept_pause, id="d002", pause_sec=0.5)
audit = edl.audit_cuts(talk, [], [kept_pause, short_pause, dict(kept_pause, id="d003", applied=True)])
assert [p["id"] for p in audit["long_pauses_kept"]] == ["d001"] and audit["long_pauses_kept"][0]["kept_reason"] == "word_protected"

# Loudness is read from FFmpeg's EBU R128 summary of the final file.
summary = """[Parsed_ebur128_0 @ 0x1] t: 26.9  M: -15.1 S: -15.0  I: -15.2 LUFS  LRA: 4.1 LU
[Parsed_ebur128_0 @ 0x1] Summary:

  Integrated loudness:
    I:         -15.6 LUFS
    Threshold: -26.0 LUFS

  Loudness range:
    LRA:         4.3 LU

  True peak:
    Peak:       -1.3 dBFS
"""
assert qa_checks.parse_ebur128(summary) == (-15.6, -1.3)                              # the summary, not a running value
assert qa_checks.parse_ebur128("") == (None, None) and qa_checks.parse_ebur128("no audio stream") == (None, None)
assert qa_checks.parse_ebur128("Summary:\n  I: -70.0 LUFS\n  Peak: -inf dBFS")[0] is None   # silence is "not measured"
print("Media Finisher edit-decision and QA tests passed")
