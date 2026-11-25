"""MyCast section timecodes (#219/#468): measured from the final audio, never estimated from the text.

The episode script carries structured section tags: `"sections": [{"line": 0, "title": "Світ AI"}, ...]`, where
`line` is the index of the line that opens the section. A renderer reports the measured start second of every line
it can place exactly in the final PCM (Piper: every line, it renders them one by one; Gemini: the first line of each
TTS call, so a section always opens a new call). Pauses between parts are inside those offsets because they are
counted from the PCM bytes actually written.

`build_index` turns sections + measured starts into chapters, or into an explicit "unavailable" with a reason when
any boundary is not measured or the MP3 length drifts from the PCM (encoder delay/padding beyond the tolerance).
Pure functions only: no I/O, no clock.
"""
from __future__ import annotations

MAX_SECTIONS = 12
TITLE_CHARS = 48
MP3_TOLERANCE_SECONDS = 0.5   # |MP3 - PCM| above this means the offsets may not match what the listener hears
CAPTION_LIMIT = 1000          # Telegram allows 1024 caption characters; telegram_send_audio cuts at 1000

UNAVAILABLE_REASONS = {
    "not_measured": "межі розділів не виміряно",
    "not_monotonic": "виміряні межі йдуть не по черзі",
    "outside_audio": "межа розділу за кінцем аудіо",
    "mp3_drift": "довжина MP3 відрізняється від виміряного аудіо",
    "no_mp3_length": "довжину MP3 не виміряно",
}


def normalize_sections(raw, n_lines: int) -> list[dict]:
    """Valid section tags only, sorted by line, one per line, at most MAX_SECTIONS. Bad tags are dropped, never
    moved: a section whose line is unknown has no honest place in the audio."""
    if not isinstance(raw, list):
        return []
    seen, out = set(), []
    for item in raw:
        if not isinstance(item, dict):
            continue
        line, title = item.get("line"), " ".join(str(item.get("title") or "").split())
        if isinstance(line, bool) or not isinstance(line, int) or not 0 <= line < n_lines or not title or line in seen:
            continue
        seen.add(line)
        out.append({"line": line, "title": title[:TITLE_CHARS]})
    return sorted(out, key=lambda s: s["line"])[:MAX_SECTIONS]


def section_breaks(sections: list[dict]) -> set[int]:
    return {s["line"] for s in sections}


def build_index(sections: list[dict], line_starts: dict, *, pcm_seconds: float, mp3_seconds: float | None,
                tolerance: float = MP3_TOLERANCE_SECONDS) -> dict:
    """status: none (no sections) | ok | unavailable. Offsets are seconds of the final PCM, rounded to 0.01."""
    base = {"pcm_seconds": round(float(pcm_seconds or 0), 2),
            "mp3_seconds": round(float(mp3_seconds), 2) if mp3_seconds is not None else None}
    if not sections:
        return {"status": "none", "chapters": [], **base}

    def unavailable(reason: str) -> dict:
        return {"status": "unavailable", "reason": reason, "chapters": [], **base}

    starts = {}
    for key, value in (line_starts or {}).items():
        try:
            starts[int(key)] = float(value)
        except (TypeError, ValueError):
            continue
    chapters = []
    for section in sections:
        if section["line"] not in starts:
            return unavailable("not_measured")
        chapters.append({"line": section["line"], "start": round(starts[section["line"]], 2), "title": section["title"]})
    if any(b["start"] <= a["start"] for a, b in zip(chapters, chapters[1:])) or chapters[0]["start"] < 0:
        return unavailable("not_monotonic")
    if chapters[-1]["start"] >= base["pcm_seconds"]:
        return unavailable("outside_audio")
    if mp3_seconds is None:
        return unavailable("no_mp3_length")
    drift = round(float(mp3_seconds) - float(pcm_seconds), 2)
    if abs(drift) > tolerance:
        return unavailable("mp3_drift")
    return {"status": "ok", "chapters": chapters, "encoder_drift_seconds": drift, **base}


def stamp(seconds: float) -> str:
    """Whole seconds, rounded down: a jump lands at or just before the section, never after its first word."""
    total = max(0, int(seconds))
    h, rest = divmod(total, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60:02d}:{rest % 60:02d}"


def chapters_block(index: dict | None) -> str:
    """The Ukrainian caption block; '' when the episode has no sections (older scripts look as before)."""
    if not index or index.get("status") == "none":
        return ""
    if index.get("status") != "ok":
        return "⏱ Таймкоди недоступні: " + UNAVAILABLE_REASONS.get(str(index.get("reason")), "немає точних вимірів")
    return "\n".join(["⏱ Зміст:"] + [f"{stamp(c['start'])} {c['title']}" for c in index["chapters"]])


def compose_caption(base: str, index: dict | None, limit: int = CAPTION_LIMIT) -> str:
    """Timecodes first: the base caption gives up whole trailing lines (sources) so the block always fits."""
    block = chapters_block(index)
    if not block:
        return str(base or "")[:limit]
    block = block[:limit]
    room = limit - len(block) - 2
    kept: list[str] = []
    for line in str(base or "").splitlines():
        if len("\n".join(kept + [line])) > room:
            if not kept and room > 1:
                kept.append(line[:room - 1] + "…")
            break
        kept.append(line)
    head = "\n".join(kept).strip()
    return f"{head}\n\n{block}" if head else block
