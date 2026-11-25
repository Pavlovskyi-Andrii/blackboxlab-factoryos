"""Pure, measured-offset chapter index for MyCast audio (Issue #468).

No speech-rate guesses. Callers supply offsets measured on the FINAL rendered
audio timeline, including silence, crossfades and encoder adjustments.
This module does not send Telegram messages or mutate production state.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class MeasuredSection:
    title: str
    start_ms: int
    end_ms: Optional[int] = None


def validate_chapters(sections: Iterable[MeasuredSection], duration_ms: int) -> list[dict]:
    """Return validated sections; raise ValueError rather than publish guesses."""
    if type(duration_ms) is not int or duration_ms <= 0:
        raise ValueError("final audio duration must be a positive integer")
    items = list(sections)
    previous_end = 0
    result = []
    for index, item in enumerate(items):
        if not isinstance(item, MeasuredSection) or not isinstance(item.title, str) or not item.title.strip():
            raise ValueError("each chapter needs a non-empty title")
        if any(ord(char) < 32 or ord(char) == 127 for char in item.title):
            raise ValueError("chapter titles must not contain control characters")
        start, end = item.start_ms, item.end_ms
        if type(start) is not int or (end is not None and type(end) is not int):
            raise ValueError("chapter offsets must be integer milliseconds")
        if start < previous_end or start >= duration_ms:
            raise ValueError("chapters must be ordered, non-overlapping and within audio")
        if end is not None and (end <= start or end > duration_ms):
            raise ValueError("invalid chapter end")
        if index + 1 < len(items):
            next_start = items[index + 1].start_ms
            if type(next_start) is not int or next_start <= start:
                raise ValueError("chapter starts must strictly increase")
            if end is not None and end > next_start:
                raise ValueError("chapters overlap")
        result.append({"title": item.title.strip(), "start_ms": start, **({"end_ms": end} if end is not None else {})})
        previous_end = end if end is not None else start
    return result


def timestamp(ms: int) -> str:
    if type(ms) is not int or ms < 0:
        raise ValueError("timestamp must be non-negative integer milliseconds")
    total_seconds = ms // 1000
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


def format_ukrainian_chapters(sections: Iterable[MeasuredSection], duration_ms: int) -> str:
    """Format only validated offsets. Telegram caption/reply choice is caller-owned."""
    chapters = validate_chapters(sections, duration_ms)
    return "\n".join(f"{timestamp(c['start_ms'])} — {c['title']}" for c in chapters)
