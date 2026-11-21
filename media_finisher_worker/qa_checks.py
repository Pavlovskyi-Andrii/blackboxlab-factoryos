"""Objective QA checks for the AI Media Finisher (GitHub #427, R-0089).

Pure functions over probe results, timelines and layout numbers. Nothing here looks at pixels: caption boxes are
estimated from the same layout constants the renderers use, and the report says so. Face/object occlusion, caption
readability on real frames and cut naturalness stay with the human reviewer.
"""
import math

NOT_CHECKED = ["face/object occlusion", "caption readability on real frames", "cut naturalness"]
REMOTION_CAPTION_FONT_PX = 54
_GLYPH_ADVANCE_EM = 0.62  # average advance of bold DejaVu Sans, Latin and Cyrillic; an estimate, not a font metric


def source_problems(probe: dict, size_bytes: int) -> list:
    """Reasons a source cannot be edited as a Talking Head video; empty when it can."""
    problems = []
    if int(size_bytes or 0) < 1024:
        problems.append("the file is empty or truncated")
    if not probe.get("video_codec") or int(probe.get("width") or 0) <= 0 or int(probe.get("height") or 0) <= 0:
        problems.append("no decodable video stream")
    if not probe.get("audio_codec"):
        problems.append("no audio stream (speech is required)")
    if float(probe.get("duration") or 0) < 1.0:
        problems.append("duration is under 1 second")
    return problems


def ass_layout(width: int, height: int, zones: dict) -> dict:
    """Overlay geometry of the FFmpeg/ASS renderer, kept inside the profile's safe zones."""
    side = max(float(zones.get("left", 0.0)), float(zones.get("right", 0.12)))
    return {"caption_font": max(26, int(width * .062)), "graphic_font": max(22, int(width * .052)),
            "margin_h": max(35, math.ceil(width * side)),
            "caption_margin_v": math.ceil(height * (float(zones.get("bottom", 0.20)) + .02)),
            "graphic_margin_v": math.ceil(height * (float(zones.get("top", 0.12)) + .02))}


def remotion_caption_max_width(zones: dict) -> float:
    """Widest centred caption plate (share of the frame) that stays out of the left and right safe zones."""
    side = max(float(zones.get("left", 0.0)), float(zones.get("right", 0.12)))
    return max(.3, min(.78, 1 - 2 * side))


def _caption_box(text: str, zones: dict, width: int, height: int, engine: str) -> dict:
    words = text.split() or [""]
    if engine == "remotion":
        font, pad_x, pad_y = REMOTION_CAPTION_FONT_PX, 22, 14
        max_w = width * remotion_caption_max_width(zones)
        content_w = max(1.0, max_w - 2 * pad_x)
        text_w = len(text) * _GLYPH_ADVANCE_EM * font
        lines = max(1, math.ceil(text_w / content_w))
        box_w = min(max_w, text_w + 2 * pad_x)
        box_h = lines * font * 1.05 + 2 * pad_y
        bottom_y = height * (1 - (max(.20, float(zones.get("bottom", .20))) + .04))
    else:
        layout = ass_layout(width, height, zones)
        font = layout["caption_font"]
        content_w = max(1.0, width - 2 * layout["margin_h"])
        box_w = len(text) * _GLYPH_ADVANCE_EM * font + 8  # one line: the ASS style does not wrap
        box_h = font * 1.2 + 8
        bottom_y = height - layout["caption_margin_v"]
    longest = max(len(w) for w in words) * _GLYPH_ADVANCE_EM * font
    return {"x0": (width - box_w) / 2, "x1": (width + box_w) / 2, "y0": bottom_y - box_h, "y1": bottom_y,
            "longest_word_px": longest, "content_px": content_w}


def safe_zone_violations(captions: list, zones: dict, width: int, height: int, engine: str) -> dict:
    """Estimated caption boxes against the platform safe zones (top/bottom/left/right shares of the frame)."""
    if engine not in ("remotion", "ffmpeg_fast"):
        return {"method": "not_estimated_for_engine", "violations": [], "checked": 0}
    limits = {"top": height * float(zones.get("top", .12)), "bottom": height * (1 - float(zones.get("bottom", .20))),
              "left": width * float(zones.get("left", 0.0)), "right": width * (1 - float(zones.get("right", .12)))}
    violations = []
    for i, caption in enumerate(captions):
        text = str(caption.get("text") or " ".join(caption.get("words") or []))
        box = _caption_box(text, zones, width, height, engine)
        found = {"top": limits["top"] - box["y0"], "bottom": box["y1"] - limits["bottom"],
                 "left": limits["left"] - box["x0"], "right": box["x1"] - limits["right"],
                 "word_overflow": box["longest_word_px"] - box["content_px"] if engine == "remotion" else 0}
        for edge, overflow in found.items():
            if overflow > 1 and len(violations) < 50:
                violations.append({"caption_index": i, "edge": edge, "overflow_px": int(round(overflow)), "text": text[:80]})
    return {"method": "estimated_caption_bbox_v1", "violations": violations, "checked": len(captions)}


def caption_timeline_issues(captions: list, cut_output_times: list, duration: float) -> list:
    """Caption groups that cross a cut, overlap the next group, run past the video or carry more than three words."""
    issues = []
    for i, caption in enumerate(captions):
        start, end = float(caption.get("start") or 0), float(caption.get("end") or 0)
        if end <= start:
            issues.append({"caption_index": i, "issue": "empty_or_reversed"})
        if any(start + .02 < x < end - .02 for x in cut_output_times):
            issues.append({"caption_index": i, "issue": "crosses_cut"})
        if i + 1 < len(captions) and end > float(captions[i + 1].get("start") or 0) + .001:
            issues.append({"caption_index": i, "issue": "overlaps_next"})
        if end > duration + .25:
            issues.append({"caption_index": i, "issue": "past_end_of_video"})
        if len(caption.get("words") or []) > 3:
            issues.append({"caption_index": i, "issue": "more_than_three_words"})
    return issues


def duration_check(source_duration: float, removed_seconds: float, final_duration: float) -> dict:
    """The measured length of the final file against what the cut list says it should be."""
    expected = max(0.0, float(source_duration) - float(removed_seconds))
    tolerance = max(.25, expected * .01)
    delta = float(final_duration) - expected
    return {"expected_sec": round(expected, 3), "measured_sec": round(float(final_duration), 3), "delta_sec": round(delta, 3),
            "tolerance_sec": round(tolerance, 3), "ok": abs(delta) <= tolerance}


def stream_sync_check(probe: dict) -> dict:
    """Video and audio stream lengths of the final file, from FFprobe."""
    video, audio = float(probe.get("video_duration") or 0), float(probe.get("audio_duration") or 0)
    if video <= 0 or audio <= 0:
        return {"status": "not_run", "detail": "stream durations are not reported for this container"}
    delta = round(video - audio, 3)
    return {"status": "pass" if abs(delta) <= .15 else "warn", "video_sec": round(video, 3), "audio_sec": round(audio, 3),
            "delta_sec": delta}


def qa_report(checks: list) -> dict:
    """One verdict from the gate results. `pass` never means approved: the owner still reviews the video."""
    statuses = [c.get("status") for c in checks]
    overall = ("fail" if "fail" in statuses else "needs_review" if "warn" in statuses
               else "incomplete" if "not_run" in statuses else "pass")
    return {"version": 1, "overall": overall, "checks": checks, "not_checked": list(NOT_CHECKED), "human_review_required": True}
