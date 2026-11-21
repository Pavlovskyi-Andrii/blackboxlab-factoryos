"""Reversible, word-safe Edit Decision List for the AI Media Finisher (GitHub #427, R-0089).

Pure planning code: no FFmpeg, network, clock or randomness, so the same transcript and silences always give the same
decisions. Every proposed removal is one decision with a reason, a confidence and the words it removes. A decision that
is not applied stays in the list with the reason it was kept, so a reviewer can see what the editor left alone and can
restore any applied cut. Transcript text is material, never instructions.
"""
import re
from typing import Optional

EDL_VERSION = 1
WORD_GUARD_SEC = 0.03   # a silence cut never comes closer than this to a transcribed word
MIN_CUT_SEC = 0.08      # shorter silence cuts are not worth a jump cut
MIN_KEEP_SEC = 0.25     # a kept sliver shorter than this with no word in it is a flash shot between two jump cuts
DEFAULT_FILLERS = ("э", "ээ", "эээ", "э-э", "э-э-э", "эм", "эмм", "мм", "ммм", "м-м", "м-м-м", "гм", "е-е", "е-е-е",
                   "uh", "umm", "um", "erm", "er", "eh", "hmm", "hm")
_SENTENCE_END = re.compile(r"[.!?…][\"'»”)]*$")


def _num(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _confidence(word: dict) -> float:
    value = word.get("confidence")
    return 1.0 if value is None else max(0.0, min(1.0, _num(value)))


def _word_ref(index: int, word: dict) -> dict:
    return {"index": index, "word": str(word.get("word") or ""), "start": round(_num(word.get("start")), 3),
            "end": round(_num(word.get("end")), 3)}


def adaptive_pause_threshold(words: list, cleanup: dict) -> dict:
    """Pause length worth cutting for this speaker: never below the profile value, higher for a slow, deliberate one.

    A fixed 0.4 s cutoff removes the natural breaths of a slow speaker and makes the edit jumpy, so the cutoff follows
    the speaker's own median gap between words (x2.5, capped). Too few gaps to judge -> the profile value is used.
    """
    base = max(0.1, _num(cleanup.get("pause_threshold_sec"), 0.4))
    if not cleanup.get("adaptive_pause", True):
        return {"base_sec": base, "effective_sec": base, "method": "fixed"}
    gaps = sorted(g for g in (_num(b.get("start")) - _num(a.get("end")) for a, b in zip(words, words[1:])) if 0.02 <= g <= 3.0)
    if len(gaps) < 12:
        return {"base_sec": base, "effective_sec": base, "method": "fixed_too_few_gaps", "gaps": len(gaps)}
    median = gaps[len(gaps) // 2]
    cap = max(base, _num(cleanup.get("adaptive_pause_max_sec"), 0.8))
    effective = round(min(cap, max(base, median * 2.5)), 3)
    return {"base_sec": base, "effective_sec": effective, "method": "speaker_median_gap_x2.5",
            "median_gap_sec": round(median, 3), "gaps": len(gaps)}


def _free_span(a: float, b: float, words: list) -> tuple:
    """Longest part of [a, b] that touches no transcribed word, and the indexes of the words that were in the way."""
    spans, touched, cursor = [], [], a
    for i, w in sorted(enumerate(words), key=lambda x: _num(x[1].get("start"))):
        ws, we = _num(w.get("start")) - WORD_GUARD_SEC, _num(w.get("end")) + WORD_GUARD_SEC
        if we <= a or ws >= b or we <= ws:
            continue
        touched.append(i)
        if ws > cursor:
            spans.append((cursor, ws))
        cursor = max(cursor, we)
    if cursor < b:
        spans.append((cursor, b))
    best = max(spans, key=lambda s: s[1] - s[0]) if spans else None
    return best, touched


def _silence_decisions(silences: list, words: list, cleanup: dict, threshold: float) -> list:
    pre = _num(cleanup.get("pre_handle_sec"), 0.1)
    post = _num(cleanup.get("post_handle_sec"), 0.15)
    sentence_extra = max(0.0, _num(cleanup.get("sentence_pause_extra_sec"), 0.1))
    start_on_speech = bool(cleanup.get("start_on_speech", True))
    out = []
    for silence in silences:
        s0, s1 = _num(silence.get("start")), _num(silence.get("end"))
        if s1 <= s0:
            continue
        middle = (s0 + s1) / 2
        before = [w for w in words if (_num(w.get("start")) + _num(w.get("end"))) / 2 < middle]
        after_sentence = bool(before and _SENTENCE_END.search(str(before[-1].get("word") or "").strip()))
        leading = start_on_speech and s0 <= 0.05
        a = 0.0 if leading else s0 + pre + (sentence_extra if after_sentence else 0.0)
        b = s1 - post
        if b - a < MIN_CUT_SEC:
            continue
        decision = {"kind": "silence", "source_start": round(a, 3), "source_end": round(b, 3),
                    "reason": str(silence.get("reason") or "silence"), "pause_sec": round(s1 - s0, 3),
                    "after_sentence_end": after_sentence, "confidence": 0.95, "applied": True, "kept_reason": "",
                    "removed_words": [], "notes": []}
        if s1 - s0 < threshold:
            decision.update(applied=False, kept_reason="below_adaptive_pause_threshold", confidence=0.5)
        else:
            span, touched = _free_span(a, b, words)
            if touched:
                decision["notes"].append("shrunk_to_protect_words: " + " ".join(str(words[i].get("word") or "") for i in touched[:6]))
                decision["confidence"] = 0.8
            if not span or span[1] - span[0] < MIN_CUT_SEC:
                decision.update(applied=False, kept_reason="word_protected")
            else:
                decision.update(source_start=round(span[0], 3), source_end=round(span[1], 3))
        out.append(decision)
    return out


def _filler_decisions(words: list, cleanup: dict) -> list:
    """Isolated hesitation tokens, removed by their ASR word timing without touching the neighbouring words."""
    fillers = set(cleanup.get("filler_words") or DEFAULT_FILLERS)
    max_duration = max(.12, _num(cleanup.get("filler_max_duration_sec"), 1.35))
    min_confidence = _num(cleanup.get("filler_min_confidence"), 0.5)
    out = []
    for i, item in enumerate(words):
        raw = str(item.get("word") or "").strip().lower()
        token = re.sub(r"[^\wа-яёіїєґ'-]+", "", raw, flags=re.UNICODE)
        if token not in fillers:
            continue
        start, end = _num(item.get("start")), _num(item.get("end"))
        if end <= start or end - start > max_duration:
            continue
        prev_end = _num(words[i - 1].get("end"), start) if i > 0 else start
        next_start = _num(words[i + 1].get("start"), end) if i + 1 < len(words) else end
        left_room, right_room = max(0.0, start - prev_end), max(0.0, next_start - end)
        pad_before, pad_after = min(.055, left_room * .48), min(.075, right_room * .48)
        confidence = round(_confidence(item), 3)
        applied = confidence >= min_confidence
        out.append({"kind": "filler", "source_start": round(max(0, start - pad_before), 3), "source_end": round(end + pad_after, 3),
                    "reason": "filler_word:" + token, "confidence": confidence, "applied": applied,
                    "kept_reason": "" if applied else "low_asr_confidence", "removed_words": [_word_ref(i, item)], "notes": []})
    return out


def _duplicate_decisions(words: list, cleanup: dict) -> list:
    """Conservative exact-repeat detector: only an immediately repeated 2-6 word phrase; the second copy is removed."""
    min_confidence = _num(cleanup.get("duplicate_min_confidence"), 0.5)
    tokens = [re.sub(r"[^\w']+", "", str(w.get("word") or "").lower()) for w in words]
    out = []
    i = 0
    while i < len(tokens):
        matched = False
        for n in range(6, 1, -1):
            if i + 2 * n > len(tokens):
                continue
            a, b = tokens[i:i + n], tokens[i + n:i + 2 * n]
            if a == b and all(a):
                start, end = _num(words[i + n].get("start")), _num(words[i + 2 * n - 1].get("end"))
                if 0 < end - start <= 6.0:
                    confidence = round(0.9 * min(_confidence(w) for w in words[i:i + 2 * n]), 3)
                    applied = confidence >= min_confidence
                    out.append({"kind": "duplicate", "source_start": round(start, 3), "source_end": round(end, 3),
                                "reason": "exact_consecutive_duplicate", "confidence": confidence, "applied": applied,
                                "kept_reason": "" if applied else "low_asr_confidence",
                                "removed_words": [_word_ref(j, words[j]) for j in range(i + n, i + 2 * n)], "notes": []})
                    i += 2 * n
                    matched = True
                    break
        if not matched:
            i += 1
    return out


LONG_PAUSE_SEC = 1.0    # a pause this long that stays in the video is shown to the reviewer
SNAP_MAX_SEC = 0.6      # how far a word-timed cut edge may move to reach the real edge of the sound
SNAP_INTO_SILENCE_SEC = 0.03
SLIVER_MAX_SEC = 0.6    # a kept piece shorter than this between two cuts, with no word in it, is suspicious


def _snap_to_acoustic_edges(decision: dict, silences: list, words: list) -> None:
    """ASR word times are estimates: speech often runs past a word's reported end (or starts before its start).
    A filler or repeat cut that trusts them leaves a fragment of the removed word in the video. Where a detected
    silence begins shortly after the cut (or ends shortly before it), the cut edge moves to that acoustic edge,
    never across a neighbouring kept word."""
    idx = [w["index"] for w in decision["removed_words"]]
    if not idx:
        return
    first, last = min(idx), max(idx)
    prev_end = _num(words[first - 1].get("end")) if first > 0 else 0.0
    next_start = _num(words[last + 1].get("start")) if last + 1 < len(words) else float("inf")
    a, b = decision["source_start"], decision["source_end"]
    edges = sorted((_num(s.get("start")), _num(s.get("end"))) for s in silences if _num(s.get("end")) > _num(s.get("start")))
    after = next((s0 for s0, s1 in edges if s0 >= b - 0.05 and s0 - b <= SNAP_MAX_SEC), None)
    if after is not None:
        new_b = min(after + SNAP_INTO_SILENCE_SEC, next_start - WORD_GUARD_SEC)
        if new_b > b + 0.01:
            decision["source_end"] = round(new_b, 3)
            decision["notes"].append(f"end_moved_to_silence_edge: +{new_b - b:.2f}s")
    before = next((s1 for s0, s1 in reversed(edges) if s1 <= a + 0.05 and a - s1 <= SNAP_MAX_SEC), None)
    if before is not None:
        new_a = max(before - SNAP_INTO_SILENCE_SEC, prev_end + WORD_GUARD_SEC, 0.0)
        if new_a < a - 0.01:
            decision["source_start"] = round(new_a, 3)
            decision["notes"].append(f"start_moved_to_silence_edge: -{a - new_a:.2f}s")


def _apply_overrides(decisions: list, overrides) -> None:
    """Reviewer undo: `restore_ids` or `restore_ranges` (source seconds) turn applied cuts back into kept footage."""
    if not isinstance(overrides, dict):
        return
    ids = {str(x) for x in (overrides.get("restore_ids") or [])[:500]} if isinstance(overrides.get("restore_ids"), list) else set()
    ranges = [x for x in (overrides.get("restore_ranges") or [])[:500] if isinstance(x, dict)] if isinstance(overrides.get("restore_ranges"), list) else []
    for d in decisions:
        if not d["applied"]:
            continue
        length = max(.001, d["source_end"] - d["source_start"])
        hit = d["id"] in ids or any(
            min(d["source_end"], _num(r.get("end"))) - max(d["source_start"], _num(r.get("start"))) >= length * .5 for r in ranges)
        if hit:
            d.update(applied=False, kept_reason="restored_by_reviewer")


def merge_cuts(decisions: list, duration: float, words: list) -> list:
    """Applied decisions -> ordered, non-overlapping source ranges to remove."""
    removed = {w["index"] for d in decisions for w in d["removed_words"]}
    kept = [(_num(w.get("start")), _num(w.get("end"))) for i, w in enumerate(words) if i not in removed]
    prepared = sorted(({"start": max(0.0, d["source_start"]), "end": min(duration, d["source_end"]), "reason": d["reason"],
                        "decision_ids": [d["id"]]} for d in decisions if d["source_end"] > d["source_start"]),
                      key=lambda x: (x["start"], x["end"]))
    merged = []
    for item in prepared:
        gap = item["start"] - merged[-1]["end"] if merged else None
        # A sliver with no kept word in it would be a flash frame between two jump cuts, so the cuts are joined.
        empty_sliver = gap is not None and gap < MIN_KEEP_SEC and not any(s < item["start"] and e > merged[-1]["end"] for s, e in kept)
        if merged and (gap <= 0.02 or empty_sliver):
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            merged[-1]["decision_ids"].extend(item["decision_ids"])
            if item["reason"] not in merged[-1]["reason"]:
                merged[-1]["reason"] += "+" + item["reason"]
        else:
            merged.append(item)
    return [{**x, "start": round(x["start"], 3), "end": round(x["end"], 3)} for x in merged if x["end"] - x["start"] >= 0.05]


def plan_edits(silences: list, words: list, duration: float, profile: dict, overrides: Optional[dict] = None) -> dict:
    cleanup = profile.get("speech_cleanup") or {}
    threshold = adaptive_pause_threshold(words, cleanup)
    decisions = []
    if cleanup.get("silence_trim", True):
        decisions.extend(_silence_decisions(silences, words, cleanup, threshold["effective_sec"]))
    if cleanup.get("filler_trim", True):
        decisions.extend(_filler_decisions(words, cleanup))
    if cleanup.get("semantic_duplicate_planner", True):
        decisions.extend(_duplicate_decisions(words, cleanup))
    for d in decisions:
        if d["kind"] in ("filler", "duplicate"):
            _snap_to_acoustic_edges(d, silences, words)
    decisions.sort(key=lambda d: (d["source_start"], d["source_end"], d["kind"]))
    for n, d in enumerate(decisions, 1):
        d["id"] = f"d{n:03d}"
        d["restore"] = {"option": "edit_overrides.restore_ids", "value": d["id"]}
    _apply_overrides(decisions, overrides)
    cuts = merge_cuts([d for d in decisions if d["applied"]], duration, words)
    in_cuts = {i for c in cuts for i in c["decision_ids"]}
    for d in decisions:
        if d["applied"] and d["id"] not in in_cuts:
            d.update(applied=False, kept_reason="below_min_cut_length")
    applied = [d for d in decisions if d["applied"]]
    return {"version": EDL_VERSION, "pause_threshold": threshold, "decisions": decisions, "cuts": cuts,
            "summary": {"proposed": len(decisions), "applied": len(applied), "kept": len(decisions) - len(applied),
                        "applied_by_kind": {k: sum(1 for d in applied if d["kind"] == k) for k in ("silence", "filler", "duplicate")},
                        "removed_seconds": round(sum(c["end"] - c["start"] for c in cuts), 3)}}


def audit_cuts(words: list, cuts: list, decisions: list, tolerance: float = 0.02) -> dict:
    """Independent check of the final cut list against the transcript: which words go, and whether any goes by accident.

    `lost_words` are words that fall inside a cut although no applied decision names them; `clipped_words` are kept
    words a cut bites into. Both must be empty for the word-safety gate to pass.
    """
    intended = {}
    for d in decisions:
        if d.get("applied"):
            for w in d.get("removed_words") or []:
                intended[w["index"]] = d
    lost, clipped, removed = [], [], []
    for i, w in enumerate(words):
        start, end = _num(w.get("start")), _num(w.get("end"))
        middle = (start + end) / 2
        dropped = any(_num(c["start"]) <= middle <= _num(c["end"]) for c in cuts)
        overlap = sum(max(0.0, min(end, _num(c["end"])) - max(start, _num(c["start"]))) for c in cuts)
        if i in intended:
            removed.append({**_word_ref(i, w), "decision_id": intended[i]["id"], "reason": intended[i]["reason"]})
        elif dropped:
            lost.append(_word_ref(i, w))
        elif overlap > tolerance:
            clipped.append({**_word_ref(i, w), "overlap_sec": round(overlap, 3)})
    # A short kept piece between two cuts that holds no kept word: usually the tail of a removed word that the
    # ASR timing missed. The transcript cannot prove it silent, so it is reported for the reviewer.
    kept = [(_num(w.get("start")), _num(w.get("end"))) for i, w in enumerate(words) if i not in intended]
    ordered = sorted(cuts, key=lambda c: _num(c["start"]))
    slivers = []
    for left, right in zip(ordered, ordered[1:]):
        a, b = _num(left["end"]), _num(right["start"])
        if 0.02 < b - a < SLIVER_MAX_SEC and not any(a <= (s + e) / 2 <= b for s, e in kept):
            slivers.append({"source_start": round(a, 3), "source_end": round(b, 3), "seconds": round(b - a, 3)})
    long_pauses = [{"id": d.get("id"), "source_start": d["source_start"], "source_end": d["source_end"],
                    "pause_sec": d.get("pause_sec"), "kept_reason": d.get("kept_reason")}
                   for d in decisions if d.get("kind") == "silence" and not d.get("applied")
                   and _num(d.get("pause_sec")) >= LONG_PAUSE_SEC]
    return {"ok": not lost and not clipped, "lost_words": lost, "clipped_words": clipped, "removed_words": removed,
            "kept_words": len(words) - len(removed) - len(lost), "tolerance_sec": tolerance,
            "wordless_slivers": slivers, "long_pauses_kept": long_pauses}
