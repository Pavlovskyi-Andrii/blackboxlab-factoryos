"""MyCast chapter timecodes (owner 2026-11-27: "тайм-кодів немає, їх потрібно додати").

The script writer marks where each section starts: episode["chapters"] = [{"line": 0, "title": "Вступ"}, ...].
Both voice paths know when each line starts in the audio:
- Piper renders line by line, so its starts are exact;
- Gemini voices a chunk of lines per call, so a line's start inside a chunk is placed by its share of the chunk's
  characters (a few seconds off at most).
`caption_block` turns that into "0:00 Вступ" lines, which Telegram makes clickable in an audio caption.
Standard library only: the server, the CI renderer and the tests import it.
"""
from __future__ import annotations

MAX_CHAPTERS = 12
MAX_TITLE_CHARS = 48


def clean_chapters(episode: dict) -> list[dict]:
    """Valid chapters only, in order: an int line inside the script, strictly increasing, a short one-line title.
    A broken entry is dropped, never the episode. The first chapter always starts at 0:00."""
    lines = episode.get("lines") if isinstance(episode, dict) else None
    raw = episode.get("chapters") if isinstance(episode, dict) else None
    if not isinstance(lines, list) or not lines or not isinstance(raw, list):
        return []
    out: list[dict] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        line, title = item.get("line"), item.get("title")
        if isinstance(line, bool) or not isinstance(line, int) or not 0 <= line < len(lines):
            continue
        if not isinstance(title, str) or not " ".join(title.split()):
            continue
        if out and line <= out[-1]["line"]:
            continue
        title = " ".join(title.split())
        if len(title) > MAX_TITLE_CHARS:
            title = title[:MAX_TITLE_CHARS - 1].rstrip() + "…"
        out.append({"line": line, "title": title})
        if len(out) == MAX_CHAPTERS:
            break
    if len(out) < 2:  # one chapter is no table of contents
        return []
    out[0] = {**out[0], "line": 0}
    return out


def chunk_line_starts(chunks: list[list], chunk_seconds: list[float], pause: float) -> list[float]:
    """Start second of every line when each chunk is one TTS call followed by `pause` seconds of silence.
    Inside a chunk a line starts at its share of the chunk's characters."""
    starts: list[float] = []
    offset = 0.0
    for chunk, seconds in zip(chunks, chunk_seconds):
        total = sum(len(text) for _, text in chunk) or 1
        done = 0
        for _, text in chunk:
            starts.append(offset + seconds * done / total)
            done += len(text)
        offset += seconds + pause
    return starts


def clock(seconds: float) -> str:
    whole = max(0, int(seconds + 0.5))
    hours, rest = divmod(whole, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}" if hours else f"{minutes}:{secs:02d}"


def caption_block(episode: dict, line_starts: list[float]) -> str:
    """"0:00 Вступ\\n1:12 OpenAI …", or "" when the script has no usable chapters or the timing does not match it."""
    chapters = clean_chapters(episode)
    if not chapters or len(line_starts) != len(episode.get("lines") or []):
        return ""
    return "\n".join(f"{clock(line_starts[c['line']])} {c['title']}" for c in chapters)
