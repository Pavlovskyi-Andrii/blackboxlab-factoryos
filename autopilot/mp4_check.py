"""Is this a watchable MP4? A small ISO-BMFF box walker, no ffprobe needed (Render has none).

Used by the server (duel uploads) and by the worker's runner (picking a render to upload), so a forged header, a
truncated file or an audio-only MP4 never becomes a take that can be scored (Codex review on #409).

A file passes only when: the top-level boxes start with `ftyp` and tile the whole file exactly (no truncation, no
trailing garbage), there is a non-empty `mdat`, and `moov` has a `mvhd` with a positive duration and at least one
`trak` whose `mdia/hdlr` handler type is `vide`.
"""
from __future__ import annotations

import struct
from typing import Iterator, Optional, Tuple

Box = Tuple[bytes, int, int]   # (type, payload_start, payload_end)


def _boxes(data: bytes, start: int, end: int) -> Iterator[Box]:
    pos = start
    while pos < end:
        if end - pos < 8:
            raise ValueError("truncated box header")
        size, kind = struct.unpack(">I4s", data[pos:pos + 8])
        header = 8
        if size == 1:
            if end - pos < 16:
                raise ValueError("truncated large box header")
            size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
            header = 16
        elif size == 0:
            size = end - pos
        if size < header or pos + size > end:
            raise ValueError("box overruns its parent (truncated or forged)")
        yield kind, pos + header, pos + size
        pos += size


def _child(data: bytes, start: int, end: int, kind: bytes) -> Optional[Box]:
    return next((b for b in _boxes(data, start, end) if b[0] == kind), None)


def _duration(data: bytes, mvhd: Box) -> float:
    _, s, e = mvhd
    if e - s < 20:
        raise ValueError("short mvhd")
    if data[s] == 1:
        if e - s < 32:
            raise ValueError("short mvhd v1")
        timescale, duration = struct.unpack(">IQ", data[s + 20:s + 32])
    else:
        timescale, duration = struct.unpack(">II", data[s + 12:s + 20])
    return duration / timescale if timescale else 0.0


def inspect(data: bytes) -> dict:
    """{"ok": bool, "reason": str, "duration": seconds}. Never raises."""
    try:
        top = list(_boxes(data, 0, len(data)))
        if not top or top[0][0] != b"ftyp" or top[0][2] - top[0][1] < 8:
            return {"ok": False, "reason": "not an MP4 (no ftyp box first)", "duration": 0.0}
        kinds = {k for k, _, _ in top}
        mdat = [b for b in top if b[0] == b"mdat"]
        if not mdat or all(e - s <= 0 for _, s, e in mdat):
            return {"ok": False, "reason": "MP4 has no media data", "duration": 0.0}
        if b"moov" not in kinds:
            return {"ok": False, "reason": "MP4 has no moov box", "duration": 0.0}
        _, ms, me = next(b for b in top if b[0] == b"moov")
        mvhd = _child(data, ms, me, b"mvhd")
        duration = _duration(data, mvhd) if mvhd else 0.0
        has_video = False
        for kind, ts, te in _boxes(data, ms, me):
            if kind != b"trak":
                continue
            mdia = _child(data, ts, te, b"mdia")
            hdlr = _child(data, mdia[1], mdia[2], b"hdlr") if mdia else None
            if hdlr and hdlr[2] - hdlr[1] >= 12 and data[hdlr[1] + 8:hdlr[1] + 12] == b"vide":
                has_video = True
        if not has_video:
            return {"ok": False, "reason": "MP4 has no video track", "duration": duration}
        if duration <= 0:
            return {"ok": False, "reason": "MP4 has no duration", "duration": duration}
        return {"ok": True, "reason": "", "duration": round(duration, 3)}
    except (ValueError, struct.error) as exc:
        return {"ok": False, "reason": f"broken MP4: {exc}", "duration": 0.0}
