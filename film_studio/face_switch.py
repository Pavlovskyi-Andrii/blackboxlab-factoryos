"""Faceless Creator A/B, S1 (T-737, issue #469): a private 9:16 clip in which one clothed synthetic presenter changes
her fictional face in a snap while body, wardrobe, room and voice stay the same.

Offline and $0: every pixel is drawn by this module (original procedural illustration, no third-party image, no face
of a real person), the voice is local espeak-ng when installed (else captions only, and the receipt says so), and the
music bed and snap sound are synthesised here. The video is labelled AI / SYNTHETIC DEMO for its whole length and is a
private review render: never published, never in git.

    python -m film_studio.face_switch --variant A --out /private/faceless/a-v1
    python -m film_studio.face_switch --variant B --out /private/faceless/b-v1

Outputs in --out: brief.json, script.json (timed lines and switches), render_plan.json, video.mp4, frames/ (before /
after every switch + a contact sheet) and qa_receipt.json (`faceless-ab/qa-receipt/v1`: ffprobe, full decode,
9:16, duration, loudness, sha256, and the face-switch evidence: how much the face area changed across each switch
compared with the body and the room, measured on the decoded MP4).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import subprocess
import sys
import tempfile
import wave
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

GENERATOR = "film_studio.face_switch/1"
SCHEMA_BRIEF = "faceless-ab/brief/v1"
SCHEMA_SCRIPT = "faceless-ab/script/v1"
SCHEMA_PLAN = "faceless-ab/render-plan/v1"
SCHEMA_RECEIPT = "faceless-ab/qa-receipt/v1"
W, H, FPS = 1080, 1920, 30
SS = 2                                    # supersampling of the drawn sprites
SAMPLE_RATE = 48000
LABEL = "AI · SYNTHETIC DEMO"
DISCLAIMER = "AI-generated synthetic presenter · 18+ · no guarantee of anonymity or earnings"
MIN_SEC, MAX_SEC = 25.0, 40.0
HEAD_CENTER = (540, 760)                  # face centre in the frame (before camera moves)
HEAD_SCALE = 1.2                          # drawn face units -> final pixels
SPRITE = (820, 940)                       # head sprite size (final pixels); face centre inside it:
SPRITE_FACE = (410, 470)
MOUTH_STATES = 5
BLINK_STATES = 3
# QA regions (final frame pixels). Overlays (label, hook, persona chip, captions, CTA) are placed outside them.
FACE_BOX = (380, 560, 700, 960)
STILL_BOXES = ((270, 1140, 810, 1270), (20, 520, 230, 1000), (870, 600, 1060, 1000))
AFTER_SEC = 0.75                          # the "after" QA frame: flash, glitch, punch-in and sparkles are over

Color = Tuple[int, int, int]


# -- people: one body, three fictional faces ----------------------------------------------------------------------
SKIN: Color = (231, 189, 160)
SKIN_SHADE: Color = (205, 155, 128)
HOODIE: Color = (191, 176, 222)
HOODIE_SHADE: Color = (160, 143, 196)
HOODIE_DEEP: Color = (128, 112, 168)


@dataclass(frozen=True)
class Face:
    name: str
    hair: Color
    hair_hi: Color
    fringe: str               # "curtain" | "sweep" | "blunt"
    iris: Color
    lips: Color
    brow: Color
    face_w: float             # half width at the cheekbones
    jaw_w: float              # half width at the jaw
    chin_y: float             # chin below the face centre
    chin_w: float
    eye_dx: float             # half distance between the eyes
    eye_w: float
    eye_h: float
    brow_arch: float
    brow_th: float
    nose_len: float
    lip_w: float
    lip_full: float
    freckles: bool = False
    mark: bool = False
    liner: bool = False


FACES: Tuple[Face, ...] = (
    Face("Mia", hair=(92, 60, 44), hair_hi=(140, 98, 70), fringe="curtain", iris=(96, 128, 84), lips=(196, 112, 112),
         brow=(84, 56, 42), face_w=152, jaw_w=122, chin_y=214, chin_w=52, eye_dx=62, eye_w=70, eye_h=32,
         brow_arch=6, brow_th=10, nose_len=64, lip_w=40, lip_full=1.0, freckles=True),
    Face("Nova", hair=(168, 74, 40), hair_hi=(214, 120, 70), fringe="sweep", iris=(92, 124, 156), lips=(168, 64, 92),
         brow=(122, 58, 36), face_w=160, jaw_w=112, chin_y=228, chin_w=40, eye_dx=66, eye_w=76, eye_h=28,
         brow_arch=16, brow_th=9, nose_len=70, lip_w=44, lip_full=1.25, mark=True),
    Face("Rin", hair=(232, 208, 160), hair_hi=(255, 240, 204), fringe="blunt", iris=(78, 52, 36), lips=(222, 120, 150),
         brow=(150, 128, 104), face_w=148, jaw_w=118, chin_y=206, chin_w=34, eye_dx=60, eye_w=68, eye_h=34,
         brow_arch=9, brow_th=12, nose_len=58, lip_w=37, lip_full=1.1, liner=True),
)


def _spline(points: Sequence[Tuple[float, float]], closed: bool = True, steps: int = 14) -> List[Tuple[float, float]]:
    """Catmull-Rom through the points: smooth outlines from a handful of anatomical landmarks."""
    pts = list(points)
    n = len(pts)
    out = []
    rng = range(n) if closed else range(n - 1)
    for i in rng:
        p0 = pts[(i - 1) % n] if closed or i > 0 else pts[0]
        p1, p2 = pts[i], pts[(i + 1) % n]
        p3 = pts[(i + 2) % n] if closed or i + 2 < n else pts[-1]
        for s in range(steps):
            t = s / steps
            t2, t3 = t * t, t * t * t
            out.append(tuple(0.5 * ((2 * p1[k]) + (-p0[k] + p2[k]) * t + (2 * p0[k] - 5 * p1[k] + 4 * p2[k] - p3[k]) * t2
                                    + (-p0[k] + 3 * p1[k] - 3 * p2[k] + p3[k]) * t3) for k in (0, 1)))
    if not closed:
        out.append(pts[-1])
    return out


class Sprite:
    """Supersampled RGBA drawing surface in sprite coordinates (face centre = origin)."""

    def __init__(self, size: Tuple[int, int], origin: Tuple[float, float], scale: float = 1.0):
        self.size, self.origin, self.scale = size, origin, scale
        self.im = Image.new("RGBA", (size[0] * SS, size[1] * SS), (0, 0, 0, 0))

    def xy(self, pts):
        ox, oy, k = self.origin[0], self.origin[1], self.scale
        return [((ox + x * k) * SS, (oy + y * k) * SS) for x, y in pts]

    def poly(self, pts, fill, blur: float = 0) -> None:
        if not blur:
            ImageDraw.Draw(self.im).polygon(self.xy(pts), fill=fill)
            return
        layer = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(self.xy(pts), fill=fill)
        self.im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * SS * self.scale)))

    def ellipse(self, cx, cy, rx, ry, fill, blur: float = 0) -> None:
        box = self.xy([(cx - rx, cy - ry), (cx + rx, cy + ry)])
        if not blur:
            ImageDraw.Draw(self.im).ellipse([box[0], box[1]], fill=fill)
            return
        layer = Image.new("RGBA", self.im.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).ellipse([box[0], box[1]], fill=fill)
        self.im.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * SS * self.scale)))

    def line(self, pts, fill, width: float) -> None:
        ImageDraw.Draw(self.im).line(self.xy(pts), fill=fill, width=max(1, int(width * SS * self.scale)), joint="curve")

    def masked(self, mask_pts, draw_fn) -> None:
        """Draw into a layer that is clipped to a polygon (e.g. shading that must stay on the skin)."""
        layer = Sprite(self.size, self.origin, self.scale)
        draw_fn(layer)
        mask = Image.new("L", self.im.size, 0)
        ImageDraw.Draw(mask).polygon(self.xy(mask_pts), fill=255)
        alpha = Image.fromarray((np.asarray(layer.im.getchannel("A"), np.float32) *
                                 np.asarray(mask, np.float32) / 255).astype(np.uint8))
        layer.im.putalpha(alpha)
        self.im.alpha_composite(layer.im)

    def final(self) -> Image.Image:
        return self.im.resize(self.size, Image.LANCZOS)


def face_outline(f: Face) -> List[Tuple[float, float]]:
    top = 178
    marks = [(0, -top), (f.face_w * 0.80, -top * 0.80), (f.face_w * 0.98, -top * 0.38), (f.face_w, 0),
             (f.face_w * 0.95, 60), (f.jaw_w, 132), (f.chin_w + 18, f.chin_y - 32), (0, f.chin_y),
             (-f.chin_w - 18, f.chin_y - 32), (-f.jaw_w, 132), (-f.face_w * 0.95, 60), (-f.face_w, 0),
             (-f.face_w * 0.98, -top * 0.38), (-f.face_w * 0.80, -top * 0.80)]
    return _spline(marks)


def _rgba(c: Color, a: int = 255) -> Tuple[int, int, int, int]:
    return (c[0], c[1], c[2], a)


def _mix(a: Color, b: Color, t: float) -> Color:
    return tuple(int(round(a[i] * (1 - t) + b[i] * t)) for i in range(3))


def _hair_back(s: Sprite, f: Face) -> None:
    """Long bob behind the face: a full crown and two falls beside the neck that end in soft points."""
    w, j = f.face_w, f.jaw_w
    half = [(0, -254), (w * 0.55, -244), (w + 18, -188), (w + 36, -92), (w + 40, 10), (w + 36, 110), (w + 44, 200),
            (w + 62, 266), (w + 30, 302), (w - 6, 284), (j + 24, 236), (j + 6, 160), (0, 172)]
    pts = half + [(-x, y) for x, y in reversed(half[1:-1])]
    s.poly(_spline(pts, steps=10), _rgba(_mix(f.hair, (0, 0, 0), 0.25)))


def _hair_sheets(f: Face) -> List[List[Tuple[float, float]]]:
    """Front hair as a few sheets (polygons) per haircut; the length and outline match for every persona."""
    w = f.face_w

    def side_fall(side: int, part_x: float, inner: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
        outer = [(part_x, -254), (side * w * 0.62, -238), (side * (w + 16), -172), (side * (w + 28), -60),
                 (side * (w + 30), 60), (side * (w + 22), 170), (side * (w + 8), 252)]
        return outer + [(side * (w - 14), 172), (side * (w - 22), 60)] + inner

    if f.fringe == "curtain":
        return [side_fall(side, side * 3, [(side * (w - 34), -40), (side * w * 0.62, -112), (side * w * 0.34, -152),
                                           (side * w * 0.12, -180), (side * 3, -206)]) for side in (-1, 1)]
    if f.fringe == "sweep":
        part = -w * 0.42
        right = side_fall(1, part, [(w - 40, -62), (w * 0.52, -104), (w * 0.1, -120), (-w * 0.28, -150),
                                    (part, -204)])
        left = side_fall(-1, part, [(-w + 30, -82), (-w * 0.62, -172), (part - 6, -226)])
        return [left, right]
    cap = [(-w - 16, -172), (-w * 0.6, -240), (0, -258), (w * 0.6, -240), (w + 16, -172), (w * 0.95, -112),
           (w * 0.62, -104), (w * 0.3, -110), (0, -104), (-w * 0.3, -110), (-w * 0.62, -104), (-w * 0.95, -112)]
    return [cap] + [side_fall(side, side * w * 0.5, [(side * (w - 28), -96), (side * w * 0.8, -170)])
                    for side in (-1, 1)]


def _hair_front(s: Sprite, f: Face, outline: List[Tuple[float, float]]) -> None:
    sheets = _hair_sheets(f)
    s.masked(outline, lambda layer: [layer.poly(_spline([(x, y + 10) for x, y in sh], steps=8),
                                                _rgba(SKIN_SHADE, 120), blur=8) for sh in sheets])   # cast shadow
    for sh in sheets:
        s.poly(_spline(sh, steps=8), _rgba(f.hair))
    w, hi = f.face_w, _rgba(f.hair_hi, 170)
    for x0, y0, x1, y1 in ((-w * 0.58, -212, -w * 0.1, -238), (w * 0.12, -238, w * 0.6, -214)):
        s.line(_spline([(x0, y0), ((x0 + x1) / 2, (y0 + y1) / 2 - 12), (x1, y1)], closed=False, steps=8), hi, 6)
    for side in (-1, 1):
        for k in range(3):
            x = side * (w + 8 + k * 7)
            s.line(_spline([(x - side * 6, -90 + k * 20), (x + side * 4, 60), (x - side * 2, 190 - k * 10)],
                           closed=False, steps=8), _rgba(f.hair_hi, 90 - k * 20), 3)


def _eye(s: Sprite, f: Face, side: int, blink: int) -> None:
    cx, cy, ew, eh = side * f.eye_dx, -12, f.eye_w / 2, f.eye_h
    upper = _spline([(cx - ew, cy + 2), (cx - ew * 0.35, cy - eh * 0.58), (cx + ew * 0.35, cy - eh * 0.56),
                     (cx + ew, cy + 1)], closed=False, steps=10)
    lower = _spline([(cx + ew, cy + 1), (cx + ew * 0.3, cy + eh * 0.45), (cx - ew * 0.3, cy + eh * 0.47),
                     (cx - ew, cy + 2)], closed=False, steps=10)
    lash = _rgba((44, 30, 30))
    if blink == 2:                                                       # closed: a soft curved lash line
        closed = _spline([(cx - ew, cy + 2), (cx, cy + eh * 0.32), (cx + ew, cy + 1)], closed=False, steps=10)
        s.line(closed, lash, 4)
        return
    s.poly(upper + lower, _rgba((250, 246, 242)))
    s.masked(upper + lower, lambda layer: (
        layer.ellipse(cx + side * 2, cy + 1, eh * 0.62, eh * 0.62, _rgba(f.iris)),
        layer.ellipse(cx + side * 2, cy + 1, eh * 0.62, eh * 0.62, _rgba(_mix(f.iris, (0, 0, 0), 0.45), 90)),
        layer.ellipse(cx + side * 2, cy + 3, eh * 0.45, eh * 0.45, _rgba(f.iris)),
        layer.ellipse(cx + side * 2, cy + 1, eh * 0.24, eh * 0.24, _rgba((18, 14, 16))),
        layer.ellipse(cx + side * 2 - 5, cy - 5, 4.2, 4.2, _rgba((255, 255, 255), 235)),
        layer.poly(upper + [(cx + ew, cy - eh), (cx - ew, cy - eh)], _rgba(SKIN_SHADE, 70)),
    ))
    if blink == 1:                                                       # half: the lid covers the top half
        lid = upper + [(cx + ew, cy - 2), (cx, cy + eh * 0.12), (cx - ew, cy - 1)]
        s.poly(lid, _rgba(_mix(SKIN, SKIN_SHADE, 0.35)))
        s.line(_spline([(cx - ew, cy - 1), (cx, cy + eh * 0.12), (cx + ew, cy - 2)], closed=False, steps=8), lash, 4)
    else:
        s.line(upper, lash, 4.5)
        crease = [(x, y - 9) for x, y in upper[2:-2]]
        s.line(crease, _rgba(SKIN_SHADE, 160), 2)
    s.line(lower[2:-2], _rgba((120, 80, 70), 150), 1.6)
    if f.liner:
        s.poly([(cx + side * ew, cy + 1), (cx + side * (ew + 15), cy - 9), (cx + side * (ew - 6), cy - 4)],
               _rgba((30, 22, 22)))


def _mouth(s: Sprite, f: Face, state: int) -> None:
    o = state / (MOUTH_STATES - 1)                                        # 0 closed .. 1 wide
    cy, hw = 118, f.lip_w
    gap = 4 + o * 26
    top = _spline([(-hw, cy), (-hw * 0.5, cy - 8 * f.lip_full), (-hw * 0.12, cy - 11 * f.lip_full), (0, cy - 7 * f.lip_full),
                   (hw * 0.12, cy - 11 * f.lip_full), (hw * 0.5, cy - 8 * f.lip_full), (hw, cy)], closed=False, steps=6)
    if o > 0.05:
        inner_top = _spline([(-hw * 0.92, cy), (0, cy + 2), (hw * 0.92, cy)], closed=False, steps=8)
        inner_bot = _spline([(hw * 0.92, cy), (hw * 0.35, cy + gap), (-hw * 0.35, cy + gap), (-hw * 0.92, cy)],
                            closed=False, steps=8)
        cavity = inner_top + inner_bot
        s.poly(cavity, _rgba((86, 34, 40)))
        s.masked(cavity, lambda layer: (layer.poly([(-hw, cy - 2), (hw, cy - 2), (hw, cy + 3 + o * 5), (-hw, cy + 3 + o * 5)],
                                                   _rgba((246, 240, 236))),
                                        layer.ellipse(0, cy + gap + 6, hw * 0.5, 10, _rgba((176, 84, 92)))))
    upper_lip = top + _spline([(hw, cy), (hw * 0.4, cy + 2), (-hw * 0.4, cy + 2), (-hw, cy)], closed=False, steps=6)
    s.poly(upper_lip, _rgba(_mix(f.lips, (0, 0, 0), 0.08)))
    by = cy + (gap if o > 0.05 else 1)
    lower_lip = _spline([(-hw * 0.95, by - 1), (-hw * 0.4, by + 1), (hw * 0.4, by + 1), (hw * 0.95, by - 1),
                         (hw * 0.6, by + 9 * f.lip_full), (0, by + 13 * f.lip_full), (-hw * 0.6, by + 9 * f.lip_full)])
    s.poly(lower_lip, _rgba(f.lips))
    s.ellipse(-hw * 0.18, by + 6 * f.lip_full, hw * 0.22, 2.6, _rgba((255, 255, 255), 90))   # gloss
    if o <= 0.05:
        s.line(_spline([(-hw, cy), (0, cy + 2), (hw, cy)], closed=False, steps=6), _rgba((120, 56, 62)), 2.2)


def draw_head(f: Face, mouth: int, blink: int) -> Image.Image:
    s = Sprite(SPRITE, SPRITE_FACE, HEAD_SCALE)
    _hair_back(s, f)
    outline = face_outline(f)
    for side in (-1, 1):                                                  # ears, mostly under the hair
        s.ellipse(side * (f.face_w - 2), 8, 20, 36, _rgba(SKIN_SHADE))
        s.ellipse(side * (f.face_w + 1), 8, 12, 26, _rgba(SKIN))
    s.poly(outline, _rgba(SKIN))

    def shading(layer: Sprite) -> None:
        layer.ellipse(0, f.chin_y + 30, f.jaw_w * 0.9, 60, _rgba(SKIN_SHADE, 150), blur=18)       # under the jaw
        for side in (-1, 1):
            layer.ellipse(side * (f.face_w + 10), 40, 34, 120, _rgba(SKIN_SHADE, 110), blur=16)   # cheek turn
            layer.ellipse(side * (f.eye_dx + 26), 62, 36, 22, _rgba((236, 140, 140), 70), blur=10)  # blush
        layer.ellipse(0, -120, 90, 40, _rgba((255, 238, 226), 70), blur=20)                    # forehead light
    s.masked(outline, shading)
    # nose: a soft shadow down one side, a lit tip and small nostrils (no hard outline)
    s.ellipse(9, f.nose_len * 0.45, 7, f.nose_len * 0.42, _rgba(SKIN_SHADE, 60), blur=5)
    s.ellipse(0, f.nose_len + 6, 18, 9, _rgba(SKIN_SHADE, 110), blur=4)
    s.ellipse(-2, f.nose_len - 3, 11, 7, _rgba((250, 222, 200), 150), blur=2)
    for side in (-1, 1):
        s.ellipse(side * 9, f.nose_len + 5, 4.6, 2.8, _rgba((150, 92, 80), 150))
    if f.freckles:
        rng = np.random.default_rng(7)
        for _ in range(26):
            x, y = rng.uniform(-88, 88), rng.uniform(24, 70) - 0.2 * abs(rng.uniform(-40, 40))
            if abs(x) > 18 or y > 34:
                s.ellipse(x, y, 2.1, 2.1, _rgba((170, 104, 78), 150))
    if f.mark:
        s.ellipse(f.lip_w + 14, 98, 3, 3, _rgba((86, 50, 40)))
    for side in (-1, 1):
        _eye(s, f, side, blink)
        bx = side * f.eye_dx
        brow = _spline([(bx - side * 34, -42 + f.brow_arch * 0.2), (bx - side * 4, -52 - f.brow_arch * 0.5),
                        (bx + side * 26, -52 - f.brow_arch * 0.35), (bx + side * 44, -40)], closed=False, steps=8)
        s.line(brow, _rgba(f.brow), f.brow_th)
    _mouth(s, f, mouth)
    _hair_front(s, f, outline)
    return s.final()


def draw_torso() -> Image.Image:
    """The constant body: neck, hood and an oversized hoodie. Identical for every persona (wardrobe continuity)."""
    s = Sprite((W, H), (0, 0))
    cx, cy = HEAD_CENTER
    k = HEAD_SCALE
    s.poly(_spline([(cx - 66 * k, cy + 170 * k), (cx + 66 * k, cy + 170 * k), (cx + 78 * k, cy + 330 * k),
                    (cx - 78 * k, cy + 330 * k)]), _rgba(SKIN))                           # neck
    neck = [(cx - 66 * k, cy + 170 * k), (cx + 66 * k, cy + 170 * k), (cx + 78 * k, cy + 330 * k),
            (cx - 78 * k, cy + 330 * k)]
    s.masked(neck, lambda layer: layer.poly([(cx - 90 * k, cy + 150 * k), (cx + 90 * k, cy + 150 * k),
                                             (cx + 70 * k, cy + 246 * k), (cx, cy + 262 * k), (cx - 70 * k, cy + 246 * k)],
                                            _rgba(SKIN_SHADE, 230), blur=10))              # jaw shadow on the neck
    hood = [(cx - 230, cy + 372), (cx - 130, cy + 330), (cx, cy + 352), (cx + 130, cy + 330), (cx + 230, cy + 372),
            (cx + 180, cy + 450), (cx, cy + 480), (cx - 180, cy + 450)]
    s.poly(_spline(hood), _rgba(HOODIE_DEEP))
    body = [(cx - 420, H + 40), (cx - 410, cy + 640), (cx - 360, cy + 480), (cx - 230, cy + 412), (cx - 110, cy + 428),
            (cx, cy + 446), (cx + 110, cy + 428), (cx + 230, cy + 412), (cx + 360, cy + 480), (cx + 410, cy + 640),
            (cx + 420, H + 40)]
    s.poly(_spline(body), _rgba(HOODIE))
    s.poly(_spline([(cx - 120, cy + 414), (cx, cy + 464), (cx + 120, cy + 414), (cx + 90, cy + 448), (cx, cy + 492),
                    (cx - 90, cy + 448)]), _rgba(HOODIE_SHADE))                            # collar rib
    for side in (-1, 1):                                                                  # drawstrings and folds
        s.line([(cx + side * 52, cy + 466), (cx + side * 60, cy + 650), (cx + side * 56, cy + 690)],
               _rgba((246, 244, 250)), 7)
        s.ellipse(cx + side * 56, cy + 696, 8, 12, _rgba((226, 222, 236)))
        s.line(_spline([(cx + side * 270, cy + 560), (cx + side * 230, cy + 800), (cx + side * 250, cy + 1060)],
                       closed=False, steps=10), _rgba(HOODIE_SHADE, 200), 10)
        s.ellipse(cx + side * 380, cy + 600, 50, 170, _rgba(HOODIE_SHADE, 130), blur=24)
        s.ellipse(cx + side * 300, cy + 440, 90, 30, _rgba((255, 248, 255), 70), blur=18)   # shoulder light
    s.line(_spline([(cx - 150, cy + 1080), (cx, cy + 1050), (cx + 150, cy + 1080)], closed=False, steps=10),
           _rgba(HOODIE_SHADE), 8)                                                         # pocket seam
    return s.final()


def draw_room(seed: int = 469) -> Image.Image:
    """A creator's corner at dusk: window, ring light, fairy lights, shelf; soft focus like a phone portrait mode."""
    rng = np.random.default_rng(seed)
    y = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
    wall = (np.array((226, 206, 204), np.float32) * (1 - y) + np.array((176, 156, 182), np.float32) * y)
    img = Image.fromarray(np.repeat(wall, W, axis=1).astype(np.uint8), "RGB").convert("RGBA")
    d = ImageDraw.Draw(img)
    sky = np.linspace(0, 1, 760, dtype=np.float32)[:, None, None]
    sky = (np.array((246, 196, 168), np.float32) * (1 - sky) + np.array((132, 150, 206), np.float32) * sky)
    img.paste(Image.fromarray(np.repeat(sky, 330, axis=1).astype(np.uint8), "RGB"), (70, 330))
    d.rectangle([58, 318, 412, 1102], outline=(248, 242, 238), width=22)
    d.line([(235, 330), (235, 1090)], fill=(248, 242, 238), width=12)
    for k in range(9):
        d.line([(80, 380 + k * 80), (390, 380 + k * 80)], fill=(236, 226, 228), width=4)
    d.rectangle([700, 1150, 1080, 1180], fill=(150, 112, 96))                             # shelf
    for k, c in enumerate(((112, 140, 176), (210, 150, 120), (150, 176, 140), (230, 204, 150), (170, 132, 178))):
        d.rectangle([760 + k * 46, 1040 - (k % 2) * 30, 798 + k * 46, 1150], fill=c)
    for k in range(7):                                                                    # a plant
        ang = -1.1 + k * 0.36
        d.ellipse([1000 + 70 * math.cos(ang) - 34, 960 + 80 * math.sin(ang) - 16,
                   1000 + 70 * math.cos(ang) + 34, 960 + 80 * math.sin(ang) + 16], fill=(96, 150, 104))
    img = img.convert("RGB").filter(ImageFilter.GaussianBlur(7))
    # light sources are added after the blur, as soft additive bokeh: ring light, fairy lights, window glints
    light = np.zeros((H, W, 3), np.float32)

    def add(layer: Image.Image, blur: float, gain: float) -> None:
        nonlocal light
        light += np.asarray(layer.filter(ImageFilter.GaussianBlur(blur)), np.float32)[..., :3] * gain

    ring = Image.new("RGB", (W, H), 0)
    ImageDraw.Draw(ring).ellipse([650, 250, 1150, 750], outline=(255, 244, 228), width=30)
    add(ring, 6, 0.75)
    add(ring, 36, 0.6)
    bulbs = Image.new("RGB", (W, H), 0)
    bd = ImageDraw.Draw(bulbs)
    for k in range(17):
        x = 30 + k * 64
        yy = 214 + 46 * math.sin(k * 0.55)
        r = 13 + 4 * (k % 3)
        bd.ellipse([x - r, yy - r, x + r, yy + r], fill=(255, 196, 128))
    add(bulbs, 5, 0.9)
    add(bulbs, 22, 0.8)
    dots = Image.new("RGB", (W, H), 0)
    dd = ImageDraw.Draw(dots)
    for _ in range(18):
        x, yy, r = rng.uniform(0, W), rng.uniform(140, 1100), rng.uniform(16, 44)
        v = int(rng.uniform(40, 110))
        dd.ellipse([x - r, yy - r, x + r, yy + r], fill=(v, int(v * 0.85), int(v * 0.7)))
    add(dots, 4, 0.8)
    a = np.asarray(img, np.float32)
    a = 255 - (255 - a) * (1 - np.clip(light / 255, 0, 1))                                # screen blend
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    vignette = 1 - 0.3 * (((xx - W / 2) / (W * 0.8)) ** 2 + ((yy - H * 0.45) / (H * 0.8)) ** 2)
    return Image.fromarray(np.clip(a * vignette[..., None], 0, 255).astype(np.uint8), "RGB")


def sprite_sheet(faces: Sequence[Face] = FACES) -> Dict[Tuple[int, int, int], Image.Image]:
    return {(i, m, b): draw_head(f, m, b) for i, f in enumerate(faces) for m in range(MOUTH_STATES)
            for b in range(BLINK_STATES)}


# -- brief and script -------------------------------------------------------------------------------------------------
VARIANTS: Dict[str, Dict[str, Any]] = {
    "A": {
        "angle": "privacy",
        "hypothesis": "Adults 18+ who are curious about subscription creator platforms respond to the idea of choosing "
                      "a public creative identity that is not their own face.",
        "hook": "Your face ≠ your brand?",
        "beats": [
            {"say": "What if your face didn't have to be your brand?"},
            {"say": "I make content every day, but I choose which face the internet sees."},
            {"switch": 1},
            {"say": "Same me. Same room. Same outfit. A different public face."},
            {"say": "Keep your style, and decide how much of yourself you share."},
            {"switch": 2},
            {"say": "Switch your on-screen identity in a snap, and stay in control."},
            {"cta": "Join early access", "say": "Join the early access list."},
        ],
    },
    "B": {
        "angle": "creative control",
        "hypothesis": "The same audience responds to creative control: one clip, several digital personas, the creator "
                      "decides which one fits the content.",
        "hook": "One clip. Three personas.",
        "beats": [
            {"say": "One clip. Three different digital personas. Watch the face."},
            {"say": "Same scene, same outfit, same light."},
            {"switch": 1},
            {"say": "You stay the creator. The persona is a creative choice."},
            {"say": "Test which on-screen identity fits your content."},
            {"switch": 2},
            {"say": "Full creative control, without filming everything again."},
            {"cta": "Join early access", "say": "Join the early access list."},
        ],
    },
}
AUDIENCE = "Adults 18+ (hypothesis: women 18-25) curious about subscription creator platforms and privacy"
VOICE = {"engine": "espeak-ng", "voice": "en-us+f3", "speed_wpm": 155, "pitch": 62}
START_SEC, GAP_SEC, SWITCH_SEC, CTA_HOLD_SEC = 0.45, 0.32, 0.62, 2.4


def brief(variant: str) -> Dict[str, Any]:
    v = VARIANTS[variant]
    return {"schema": SCHEMA_BRIEF, "issue": 469, "task": "T-737", "variant": variant, "angle": v["angle"],
            "audience": AUDIENCE, "hypothesis": v["hypothesis"], "format": {"aspect": "9:16", "width": W, "height": H,
                                                                          "fps": FPS, "seconds": [MIN_SEC, MAX_SEC]},
            "presenter": "one fully clothed fictional adult, drawn procedurally; three fictional faces, no real person",
            "label": LABEL, "cta": "Join early access", "disclaimer": DISCLAIMER,
            "comparison_mode": "CREATIVE_COMPARISON (no statistical winner)", "publishing": "none (private review)",
            "cost_usd": 0}


def _tts(text: str, out: Path) -> Optional[np.ndarray]:
    """espeak-ng to mono float32 at SAMPLE_RATE; None when espeak-ng is not installed (captions-only fallback)."""
    exe = shutil.which("espeak-ng")
    if not exe:
        return None
    raw = out.with_suffix(".raw.wav")
    subprocess.run([exe, "-v", VOICE["voice"], "-s", str(VOICE["speed_wpm"]), "-p", str(VOICE["pitch"]), "-w", str(raw),
                    text], check=True, capture_output=True, timeout=60)
    subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar",
                    str(SAMPLE_RATE), "-af", "highpass=f=90,lowpass=f=9000,acompressor=threshold=-18dB:ratio=3",
                    "-c:a", "pcm_s16le", str(out)], check=True, capture_output=True, timeout=60)
    raw.unlink(missing_ok=True)
    return read_wav(out)


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
        if w.getnchannels() > 1:
            data = data.reshape(-1, w.getnchannels()).mean(axis=1)
    return data


def write_wav(path: Path, mono: np.ndarray) -> None:
    pcm = (np.clip(mono, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())


def build_script(variant: str, work: Path, words_per_sec: float = 2.6) -> Tuple[Dict[str, Any], Dict[str, np.ndarray]]:
    """Timed beats from the real length of each voice line (or a words-per-second estimate without TTS)."""
    if variant not in VARIANTS:
        raise ValueError("variant must be one of " + ", ".join(VARIANTS))
    v = VARIANTS[variant]
    t, lines, switches, cta, clips, persona, voice_ok = START_SEC, [], [], None, {}, 0, True
    for i, beat in enumerate(v["beats"]):
        if "switch" in beat:
            nxt = int(beat["switch"])
            if not 0 < nxt < len(FACES) or nxt == persona:
                raise ValueError("a switch must go to another persona")
            switches.append({"at": round(t + 0.12, 3), "from": persona, "to": nxt, "from_name": FACES[persona].name,
                             "to_name": FACES[nxt].name})
            persona, t = nxt, t + SWITCH_SEC
            continue
        text = beat["say"]
        audio = _tts(text, work / f"vo-{i:02d}.wav")
        if audio is None:
            voice_ok = False
            dur = len(text.split()) / words_per_sec
        else:
            clips[f"line-{i:02d}"] = audio
            dur = len(audio) / SAMPLE_RATE
        line = {"id": f"line-{i:02d}", "start": round(t, 3), "end": round(t + dur, 3), "text": text, "persona": persona}
        if "cta" in beat:
            cta = {"start": round(t, 3), "title": beat["cta"]}
        lines.append(line)
        t += dur + GAP_SEC
    end = t - GAP_SEC + CTA_HOLD_SEC
    if end < MIN_SEC:                                    # too short: hold the end card longer, never stretch speech
        end = MIN_SEC
    if end > MAX_SEC:
        raise ValueError(f"script runs {end:.1f} s, longer than {MAX_SEC:.0f} s")
    frames = int(round(end * FPS))
    script = {"schema": SCHEMA_SCRIPT, "variant": variant, "hook": v["hook"], "lines": lines, "switches": switches,
              "cta": cta, "duration": round(frames / FPS, 3), "frames": frames, "fps": FPS,
              "voice": dict(VOICE, used=voice_ok) if voice_ok else {"engine": "none", "used": False,
                                                                    "note": "espeak-ng not installed: captions only"}}
    return script, clips


# -- audio: voice + music bed + snap ------------------------------------------------------------------------------------
def _music(seconds: float, seed: int = 7) -> np.ndarray:
    """Soft four-chord pad with a light kick and hat at 120 bpm (original, synthesised here)."""
    n = int(seconds * SAMPLE_RATE)
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    chords = ((220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (261.63, 329.63, 392.0), (196.0, 246.94, 293.66))
    out = np.zeros(n, np.float32)
    bar = 2.0
    for k in range(int(math.ceil(seconds / bar))):
        a, b = int(k * bar * SAMPLE_RATE), min(n, int((k + 1) * bar * SAMPLE_RATE + 0.4 * SAMPLE_RATE))
        if a >= n:
            break
        tt = t[a:b] - k * bar
        env = np.minimum(1, tt / 0.35) * np.exp(-np.maximum(0, tt - bar) / 0.18)
        tone = sum(np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt + 0.4) for f in chords[k % 4])
        out[a:b] += 0.06 * env * tone
    rng = np.random.default_rng(seed)
    beat = 0.5
    for k in range(int(seconds / beat)):
        a = int(k * beat * SAMPLE_RATE)
        m = min(n - a, int(0.16 * SAMPLE_RATE))
        if m <= 0:
            break
        tt = np.arange(m) / SAMPLE_RATE
        out[a:a + m] += 0.22 * np.sin(2 * np.pi * (52 + 70 * np.exp(-tt / 0.03)) * tt) * np.exp(-tt / 0.07)
        h = a + int(0.25 * SAMPLE_RATE)
        hm = min(n - h, int(0.05 * SAMPLE_RATE))
        if hm > 0:
            noise = rng.standard_normal(hm).astype(np.float32)
            out[h:h + hm] += 0.03 * np.diff(noise, prepend=0) * np.exp(-np.arange(hm) / SAMPLE_RATE / 0.012)
    return out


def _snap(seed: int) -> np.ndarray:
    """A finger snap (sharp filtered click), a short whoosh before it and a bright shimmer after it."""
    rng = np.random.default_rng(seed)
    pre, post = int(0.22 * SAMPLE_RATE), int(0.5 * SAMPLE_RATE)
    out = np.zeros(pre + post, np.float32)
    whoosh = rng.standard_normal(pre).astype(np.float32)
    whoosh = np.convolve(whoosh, np.ones(24) / 24, mode="same") * np.linspace(0, 1, pre) ** 2
    out[:pre] += 0.35 * whoosh
    m = int(0.03 * SAMPLE_RATE)
    click = np.diff(rng.standard_normal(m + 1).astype(np.float32)) * np.exp(-np.arange(m) / SAMPLE_RATE / 0.004)
    out[pre:pre + m] += 0.9 * click
    tt = np.arange(post) / SAMPLE_RATE
    out[pre:] += 0.12 * np.sin(2 * np.pi * (1800 + 1400 * tt) * tt) * np.exp(-tt / 0.12)
    return out


def mix_audio(script: Dict[str, Any], clips: Dict[str, np.ndarray]) -> Tuple[np.ndarray, np.ndarray]:
    """Returns (mix, voice) at SAMPLE_RATE; the voice track alone drives the lip movement."""
    n = int(round(script["duration"] * SAMPLE_RATE))
    voice = np.zeros(n, np.float32)
    for line in script["lines"]:
        clip = clips.get(line["id"])
        if clip is None:
            continue
        a = int(line["start"] * SAMPLE_RATE)
        b = min(n, a + len(clip))
        voice[a:b] += clip[:b - a]
    peak = float(np.max(np.abs(voice))) or 1.0
    voice *= 0.7 / peak
    mix = voice + 0.35 * _music(script["duration"])[:n]
    for k, sw in enumerate(script["switches"]):
        fx = _snap(100 + k)
        a = int(sw["at"] * SAMPLE_RATE) - int(0.22 * SAMPLE_RATE)
        lo, hi = max(0, a), min(n, a + len(fx))
        mix[lo:hi] += 0.7 * fx[lo - a:hi - a]
    return mix, voice


def mouth_track(voice: np.ndarray, frames: int) -> List[int]:
    """Per-frame mouth state from the voice loudness (fast attack, slower release)."""
    hop = SAMPLE_RATE // FPS
    rms = np.array([math.sqrt(float(np.mean(voice[i * hop:(i + 1) * hop] ** 2))) if i * hop < len(voice) else 0.0
                    for i in range(frames)], np.float32)
    ref = float(np.percentile(rms[rms > 0], 90)) if np.any(rms > 0) else 1.0
    level, out = 0.0, []
    for r in rms / (ref or 1.0):
        level = max(float(r), level * 0.55)
        out.append(int(min(MOUTH_STATES - 1, round(level * (MOUTH_STATES - 1) * 0.95))))
    return out


def mouth_from_captions(script: Dict[str, Any], frames: int) -> List[int]:
    """Without a voice track the mouth still moves while a caption line is 'spoken' (syllable-rate pattern)."""
    out = []
    for i in range(frames):
        t = i / FPS
        speaking = any(line["start"] <= t < line["end"] for line in script["lines"])
        out.append(int((math.sin(t * 2 * math.pi * 3.4) * 0.5 + 0.5) * 3.2) + (1 if speaking else 0) if speaking else 0)
    return [min(MOUTH_STATES - 1, m) for m in out]


# -- overlays ---------------------------------------------------------------------------------------------------------
def _fonts() -> Dict[str, str]:
    from .render import find_fonts
    return find_fonts()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> List[str]:
    lines, cur = [], ""
    for word in text.split():
        trial = (cur + " " + word).strip()
        if draw.textlength(trial, font=font) <= width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    return lines + ([cur] if cur else [])


def _pill(text: str, font, pad=(22, 12), fill=(0, 0, 0, 165), color=(255, 255, 255, 255)) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    l, t, r, b = probe.textbbox((0, 0), text, font=font)
    im = Image.new("RGBA", (int(r - l + 2 * pad[0]), int(b - t + 2 * pad[1])), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, im.width - 1, im.height - 1], radius=im.height // 2, fill=fill)
    d.text((pad[0] - l, pad[1] - t), text, font=font, fill=color)
    return im


def _text_block(text: str, font, width: int, fill=(255, 255, 255, 255), stroke=7, spacing=10) -> Image.Image:
    probe = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    lines = _wrap(probe, text, font, width)
    heights = [probe.textbbox((0, 0), ln, font=font, stroke_width=stroke)[3] for ln in lines]
    im = Image.new("RGBA", (W, sum(heights) + spacing * (len(lines) - 1) + 2 * stroke), (0, 0, 0, 0))
    d, y = ImageDraw.Draw(im), stroke
    for ln, h in zip(lines, heights):
        tw = d.textlength(ln, font=font)
        d.text(((W - tw) / 2, y), ln, font=font, fill=fill, stroke_width=stroke, stroke_fill=(16, 10, 20, 255))
        y += h + spacing
    return im


def build_overlays(script: Dict[str, Any], variant: str) -> Dict[str, Any]:
    f = _fonts()
    bold = lambda size: ImageFont.truetype(f["bold"], size)            # noqa: E731
    regular = lambda size: ImageFont.truetype(f["regular"], size)      # noqa: E731
    ov: Dict[str, Any] = {
        "label": _pill(LABEL, bold(30)),
        "variant": _pill(f"{variant} · {VARIANTS[variant]['angle']}", regular(26), fill=(255, 255, 255, 150),
                         color=(40, 30, 50, 255)),
        "hook": _text_block(script["hook"], bold(70), 900, stroke=9),
        "captions": {line["id"]: _text_block(line["text"], bold(56), 880) for line in script["lines"]},
        "personas": [_pill(f"persona {sw['to'] + 1}/{len(FACES)} · {sw['to_name']}", bold(34), fill=(120, 80, 200, 215))
                     for sw in script["switches"]],
    }
    card = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shade = np.zeros((H, W, 4), np.uint8)
    ramp = np.clip((np.arange(H) - 1120) / 380, 0, 1) ** 1.4
    shade[..., 3] = (ramp[:, None] * 205).astype(np.uint8)
    shade[..., :3] = (26, 14, 40)
    card.alpha_composite(Image.fromarray(shade, "RGBA"))
    title = _text_block((script["cta"] or {}).get("title", "Join early access"), bold(84), 920, stroke=0)
    card.alpha_composite(title, (0, 1380))
    button = _pill("Early access · Faceless Creator", bold(42), pad=(40, 22), fill=(255, 255, 255, 240),
                   color=(70, 40, 120, 255))
    card.alpha_composite(button, ((W - button.width) // 2, 1530))
    note = _text_block(DISCLAIMER, regular(26), 940, fill=(240, 232, 248, 230), stroke=0, spacing=6)
    card.alpha_composite(note, (0, 1690))
    ov["cta"] = card
    return ov


# -- frames -----------------------------------------------------------------------------------------------------------
def blink_track(frames: int, switches: Sequence[float], seed: int = 3) -> List[int]:
    rng = np.random.default_rng(seed)
    out, t = [0] * frames, 1.3
    while t < frames / FPS:
        f0 = int(t * FPS)
        if not any(abs(t - s) < 0.5 for s in switches):
            for k, state in enumerate((1, 2, 2, 1)):
                if f0 + k < frames:
                    out[f0 + k] = state
        t += float(rng.uniform(2.6, 4.4))
    return out


def _sparkles(img: Image.Image, center: Tuple[float, float], age: float, seed: int) -> None:
    if not 0 <= age < 0.7:
        return
    rng = np.random.default_rng(seed)
    d = ImageDraw.Draw(img, "RGBA")
    alpha = int(255 * (1 - age / 0.7))
    for k in range(14):
        ang = k / 14 * 2 * math.pi + float(rng.uniform(-0.2, 0.2))
        r = 230 + 420 * age + float(rng.uniform(-30, 30))
        x, y = center[0] + r * math.cos(ang), center[1] + r * 1.15 * math.sin(ang)
        size = float(rng.uniform(8, 18)) * (1 - age / 0.9)
        d.polygon([(x, y - size * 2), (x + size * 0.5, y - size * 0.5), (x + size * 2, y), (x + size * 0.5, y + size * 0.5),
                   (x, y + size * 2), (x - size * 0.5, y + size * 0.5), (x - size * 2, y), (x - size * 0.5, y - size * 0.5)],
                  fill=(255, 250, 230, alpha))


def head_motion(t: float, mouth: int, since_switch: Optional[float]) -> Tuple[int, int, float]:
    dx = 7 * math.sin(2 * math.pi * t / 5.3) + 3 * math.sin(2 * math.pi * t / 2.3)
    dy = 5 * math.sin(2 * math.pi * t / 3.9) - 1.5 * mouth
    if since_switch is not None and 0 <= since_switch < 0.5:
        dy -= 12 * math.exp(-since_switch / 0.1)
    tilt = 1.8 * math.sin(2 * math.pi * t / 6.4)
    return int(round(dx)), int(round(dy)), tilt


def camera_scale(t: float, duration: float, switches: Sequence[float]) -> float:
    """A slow continuous push over the whole clip (so the room does not jump at a switch) plus a punch-in per snap."""
    s = 1.0 + 0.05 * t / max(duration, 1e-6)
    for ts in switches:
        if ts - 0.12 <= t < ts:
            s += 0.06 * (t - (ts - 0.12)) / 0.12
        elif ts <= t < ts + 0.35:
            s += 0.06 * (1 - (t - ts) / 0.35) ** 2
    return s


class FrameRenderer:
    def __init__(self, script: Dict[str, Any], variant: str, mouths: List[int]):
        self.script, self.variant, self.mouths = script, variant, mouths
        self.room, self.torso, self.sprites = draw_room(), draw_torso(), sprite_sheet()
        self.ov = build_overlays(script, variant)
        self.switch_at = [sw["at"] for sw in script["switches"]]
        self.blinks = blink_track(script["frames"], self.switch_at)

    def persona(self, t: float) -> Tuple[int, Optional[float], int]:
        persona, since, index = 0, None, -1
        for k, sw in enumerate(self.script["switches"]):
            if t >= sw["at"]:
                persona, since, index = sw["to"], t - sw["at"], k
        return persona, since, index

    def frame(self, i: int) -> Image.Image:
        t, sc = i / FPS, self.script
        persona, since, index = self.persona(t)
        near = any(-0.1 <= t - ts < 0.25 for ts in self.switch_at)
        mouth = 0 if near else self.mouths[i]
        dx, dy, tilt = head_motion(t, mouth, since)
        breath = 2.0 * math.sin(2 * math.pi * t / 4.0)
        img = self.room.copy()
        img.paste(self.torso, (0, int(round(breath))), self.torso)
        head = self.sprites[(persona, mouth, self.blinks[i])]
        if abs(tilt) > 0.05:
            head = head.rotate(tilt, resample=Image.BICUBIC, center=SPRITE_FACE)
        cx, cy = HEAD_CENTER
        img.paste(head, (cx - SPRITE_FACE[0] + dx, cy - SPRITE_FACE[1] + dy + int(round(breath * 0.6))), head)
        if since is not None:
            _sparkles(img, (cx + dx, cy + dy), since, 50 + index)
        s = camera_scale(t, sc["duration"], self.switch_at)
        fx, fy = 540.0, 820.0
        box = (fx - fx / s, fy - fy / s, fx + (W - fx) / s, fy + (H - fy) / s)
        img = img.resize((W, H), Image.BILINEAR, box=box)
        for ts in self.switch_at:
            age = t - ts
            if -0.04 <= age < 0.35:
                arr = np.asarray(img).astype(np.float32)
                if age >= 0:
                    g = 1 - age / 0.35
                    rng = np.random.default_rng(1000 + i)
                    for _ in range(9):
                        y0, hh = int(rng.integers(260, 1500)), int(rng.integers(16, 90))
                        arr[y0:y0 + hh] = np.roll(arr[y0:y0 + hh], int(rng.integers(-70, 71) * g), axis=1)
                    k = int(round(12 * g))
                    arr[..., 0] = np.roll(arr[..., 0], k, axis=1)
                    arr[..., 2] = np.roll(arr[..., 2], -k, axis=1)
                    flash = 0.9 * math.exp(-age / 0.06)
                else:
                    flash = 0.9 * (age + 0.04) / 0.04
                arr = arr * (1 - flash) + np.array((255, 250, 244), np.float32) * flash
                img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
        ov = self.ov
        img.paste(ov["label"], (44, 150), ov["label"])
        img.paste(ov["variant"], (W - 44 - ov["variant"].width, 152), ov["variant"])
        first = sc["lines"][0] if sc["lines"] else None
        if first and t < first["end"] + 0.4:
            img.paste(ov["hook"], (0, 222), ov["hook"])
        if since is not None and since < 1.8:
            chip = ov["personas"][index]
            img.paste(chip, ((W - chip.width) // 2, 300), chip)
        cta = sc.get("cta")
        if cta and t >= cta["start"]:
            card = ov["cta"]
            fade = min(1.0, (t - cta["start"]) / 0.3)
            if fade < 1:
                card = card.copy()
                card.putalpha(card.getchannel("A").point(lambda v: int(v * fade)))
            img.paste(card, (0, 0), card)
        else:
            line = next((ln for ln in sc["lines"] if ln["start"] <= t < ln["end"] + 0.25), None)
            if line:
                cap = ov["captions"][line["id"]]
                img.paste(cap, (0, 1440 - cap.height // 2), cap)
        return img


# -- render -----------------------------------------------------------------------------------------------------------
def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _canonical(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def render(variant: str, out: Path, *, crf: int = 20) -> Dict[str, Any]:
    from .render import guard_private_output
    guard_private_output(out)
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        raise RuntimeError("ffmpeg/ffprobe are required")
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="faceless-work-"))
    try:
        script, clips = build_script(variant, work)
        mix, voice = mix_audio(script, clips)
        frames = script["frames"]
        mouths = mouth_track(voice, frames) if clips else mouth_from_captions(script, frames)
        write_wav(work / "mix.wav", mix * 0.9)
        renderer = FrameRenderer(script, variant, mouths)
        video = out / "video.mp4"
        cmd = ["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-i", str(work / "mix.wav"), "-map", "0:v", "-map", "1:a",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", "-profile:v", "high",
               "-af", "loudnorm=I=-16:TP=-2:LRA=11", "-c:a", "aac", "-b:a", "160k", "-ar", str(SAMPLE_RATE),
               "-movflags", "+faststart", "-t", f"{script['duration']:.3f}", str(video)]
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            for i in range(frames):
                proc.stdin.write(renderer.frame(i).tobytes())
        finally:
            proc.stdin.close()
        err = proc.stderr.read().decode(errors="replace")
        if proc.wait() != 0:
            raise RuntimeError("ffmpeg failed: " + err[-800:])
        plan = {"schema": SCHEMA_PLAN, "generator": GENERATOR, "variant": variant, "width": W, "height": H, "fps": FPS,
                "frames": frames, "duration": script["duration"], "crf": crf, "preset": "veryfast",
                "faces": [f.__dict__ for f in FACES], "faces_sha256": _canonical([f.__dict__ for f in FACES]),
                "head_center": HEAD_CENTER, "head_scale": HEAD_SCALE,
                "qa_regions": {"face": FACE_BOX, "still": STILL_BOXES},
                "assets": "all procedural (drawn by this module), no third-party media, no real person",
                "voice": script["voice"], "music": "synthesised here (4-chord pad, kick, hat), seed 7",
                "script_sha256": _canonical(script)}
        for name, doc in (("brief.json", brief(variant)), ("script.json", script), ("render_plan.json", plan)):
            (out / name).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        receipt = qa_receipt(video, script, out)
        (out / "qa_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return receipt
    finally:
        shutil.rmtree(work, ignore_errors=True)


# -- QA ---------------------------------------------------------------------------------------------------------------
def decoded_frame(video: Path, t: float) -> np.ndarray:
    p = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-i", str(video), "-ss", f"{t:.3f}",
                        "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=120)
    if p.returncode != 0 or len(p.stdout) != W * H * 3:
        raise RuntimeError(f"cannot decode a frame at {t:.2f} s")
    return np.frombuffer(p.stdout, np.uint8).reshape(H, W, 3)


def region_diff(a: np.ndarray, b: np.ndarray, box: Sequence[int]) -> float:
    x0, y0, x1, y1 = box
    return float(np.mean(np.abs(a[y0:y1, x0:x1].astype(np.float32) - b[y0:y1, x0:x1].astype(np.float32))))


def switch_evidence(before: np.ndarray, after: np.ndarray) -> Dict[str, Any]:
    face = region_diff(before, after, FACE_BOX)
    still = max(region_diff(before, after, box) for box in STILL_BOXES)
    ratio = face / max(still, 0.5)
    return {"face_mean_abs_diff": round(face, 2), "still_max_mean_abs_diff": round(still, 2), "ratio": round(ratio, 1),
            "pass": face >= 18 and ratio >= 3 and still <= 8}


def label_present(frame: np.ndarray) -> bool:
    crop = frame[150:205, 44:400].astype(np.float32).mean(axis=2)
    return bool((crop < 90).mean() > 0.35 and (crop > 200).mean() > 0.03)


def qa_receipt(video: Path, script: Dict[str, Any], out: Path) -> Dict[str, Any]:
    from . import qa
    probe = qa.ffprobe(video)
    streams = probe.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), {})
    duration = float(probe.get("format", {}).get("duration") or 0)
    decode = qa.decode_pass(video)
    loud = qa.loudness(video) if a else {}
    black = qa.black_intervals(video)
    frames_dir = out / "frames"
    frames_dir.mkdir(exist_ok=True)
    evidence, tiles = [], []
    for k, sw in enumerate(script["switches"]):
        before = decoded_frame(video, sw["at"] - 0.30)
        after = decoded_frame(video, sw["at"] + AFTER_SEC)
        ev = {"switch": k + 1, "at": sw["at"], "from": sw["from_name"], "to": sw["to_name"],
              "before_t": round(sw["at"] - 0.30, 3), "after_t": round(sw["at"] + AFTER_SEC, 3),
              **switch_evidence(before, after)}
        for tag, arr in (("before", before), ("after", after)):
            path = frames_dir / f"switch{k + 1}-{tag}.jpg"
            Image.fromarray(arr).save(path, quality=88)
            ev[tag + "_jpg"] = path.name
            tiles.append(Image.fromarray(arr).resize((360, 640), Image.LANCZOS))
        evidence.append(ev)
    if tiles:
        sheet = Image.new("RGB", (360 * len(tiles), 640), (0, 0, 0))
        for k, tile in enumerate(tiles):
            sheet.paste(tile, (360 * k, 0))
        sheet.save(frames_dir / "contact_sheet.jpg", quality=86)
    label_ok = all(label_present(decoded_frame(video, t)) for t in (0.5, script["duration"] / 2, script["duration"] - 0.5))
    fps = str(v.get("r_frame_rate") or "")
    checks = {
        "codec_h264": v.get("codec_name") == "h264", "pix_fmt_yuv420p": v.get("pix_fmt") == "yuv420p",
        "vertical_9_16": int(v.get("width") or 0) * 16 == int(v.get("height") or 0) * 9 and v.get("width") == W,
        "fps_30": fps in ("30/1", "30000/1000"), "duration_25_40_s": MIN_SEC - 0.05 <= duration <= MAX_SEC + 0.05,
        "frame_count": int(v.get("nb_read_frames") or 0) == script["frames"],
        "audio_aac": a.get("codec_name") == "aac", "full_decode": decode["returncode"] == 0,
        "no_black_stretch": not black,
        "loudness_-16_lufs": loud.get("integrated_lufs") is not None and abs(loud["integrated_lufs"] + 16) <= 1.5,
        "true_peak_<=-1_dbtp": loud.get("true_peak_dbtp") is not None and loud["true_peak_dbtp"] <= -1.0,
        "face_switch_visible": bool(evidence) and all(e["pass"] for e in evidence),
        "synthetic_label_burned_in": label_ok,
    }
    return {"schema": SCHEMA_RECEIPT, "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks,
            "video": {"file": video.name, "sha256": _sha256(video), "bytes": video.stat().st_size,
                      "duration": round(duration, 3), "width": v.get("width"), "height": v.get("height"),
                      "r_frame_rate": fps, "frames": v.get("nb_read_frames"), "profile": v.get("profile")},
            "audio": {"codec": a.get("codec_name"), "sample_rate": a.get("sample_rate"), **loud},
            "voice": script["voice"], "face_switch_evidence": evidence, "decode": decode, "black_intervals": black,
            "cost_usd": 0, "paid_calls": 0, "network_calls": 0, "label": LABEL, "disclaimer": DISCLAIMER,
            "not_claimed": ["photorealism", "audience demand", "A/B winner", "owner score (only the owner scores)"],
            "generator": GENERATOR, "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Faceless Creator A/B S1: private 9:16 face-switch clip + QA receipt")
    ap.add_argument("--variant", choices=sorted(VARIANTS), required=True)
    ap.add_argument("--out", required=True, help="private output directory (outside the repository)")
    ap.add_argument("--crf", type=int, default=20)
    args = ap.parse_args(argv)
    receipt = render(args.variant, Path(args.out), crf=args.crf)
    print(json.dumps({"status": receipt["status"], "checks": receipt["checks"],
                      "face_switch_evidence": receipt["face_switch_evidence"], "video": receipt["video"]},
                     ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
