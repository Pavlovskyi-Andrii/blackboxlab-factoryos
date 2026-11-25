"""Original procedural stills for Photo Cinema stand-in shots (T-730).

Used when no verified licensed photo is available: every pixel is drawn by this code from a fixed seed, with no
third-party input, so its rights are known (original work of this repository). Each still has a background and an
alpha foreground layer for parallax. These are illustrations, NOT photographs, and the renderer labels them so.

    python -m film_studio.procedural --out DIR [--storyboard ...] [--candidates ...]
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from . import SCHEMA_ASSET_MANIFEST
from .plan import sha256_file
from .schema import validate_asset_manifest

W, H = 2560, 1440
GENERATOR = "film_studio.procedural/1"
TEAL = (57, 217, 233)
ICE = (220, 239, 255)
WARM = (242, 169, 106)
DEEP = (6, 16, 25)

Color = Tuple[int, int, int]


class Canvas:
    """Float RGB image (0..1) plus helpers; all randomness comes from one seeded generator."""

    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.img = np.zeros((H, W, 3), np.float32)

    def gradient(self, top: Color, bottom: Color) -> None:
        t = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
        self.img[:] = (np.array(top, np.float32) * (1 - t) + np.array(bottom, np.float32) * t) / 255

    def layer(self) -> Tuple[Image.Image, ImageDraw.ImageDraw]:
        im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        return im, ImageDraw.Draw(im)

    def over(self, im: Image.Image, blur: float = 0) -> None:
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        a = np.asarray(im, np.float32) / 255
        self.img = self.img * (1 - a[..., 3:4]) + a[..., :3] * a[..., 3:4]

    def add(self, im: Image.Image, blur: float = 0, gain: float = 1.0) -> None:
        if blur:
            im = im.filter(ImageFilter.GaussianBlur(blur))
        a = np.asarray(im, np.float32) / 255
        self.img = self.img + a[..., :3] * a[..., 3:4] * gain

    def glow(self, x: float, y: float, r: float, color: Color, gain: float = 1.0) -> None:
        im, d = self.layer()
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*color, 255))
        self.add(im, blur=r * 0.9, gain=gain)

    def haze(self, y0: float, y1: float, color: Color, strength: float) -> None:
        yy = np.arange(H, dtype=np.float32)[:, None, None]
        mid, half = (y0 + y1) / 2, max(1.0, (y1 - y0) / 2)
        band = np.exp(-((yy - mid) / half) ** 2) * strength
        self.img = self.img * (1 - band) + np.array(color, np.float32) / 255 * band

    def finish(self) -> Image.Image:
        img = self.img
        # Grade: lift shadows towards deep teal, keep highlights warm, soft roll-off, vignette, film grain.
        img = img + np.array([0.0, 0.012, 0.02], np.float32) * (1 - np.clip(img * 3, 0, 1))
        img = 1 - np.exp(-img * 1.6)
        yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
        v = ((xx - W / 2) / (W / 2)) ** 2 * 0.55 + ((yy - H / 2) / (H / 2)) ** 2 * 0.75
        img = img * np.clip(1 - 0.42 * v, 0.25, 1)[..., None]
        img = img + self.rng.normal(0, 0.012, (H, W, 1)).astype(np.float32)
        return Image.fromarray(np.uint8(np.clip(img, 0, 1) * 255), "RGB")


def _fg() -> Tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def _bokeh(rng, n: int, colors: List[Color], rmin: int, rmax: int, ymin: float = 0, ymax: float = 1,
           alpha=(40, 110)) -> Image.Image:
    im, d = _fg()
    for _ in range(n):
        r = int(rng.integers(rmin, rmax))
        x, y = rng.uniform(-0.05, 1.05) * W, rng.uniform(ymin, ymax) * H
        c = colors[int(rng.integers(0, len(colors)))]
        d.ellipse((x - r, y - r, x + r, y + r), fill=(*c, int(rng.integers(*alpha))),
                  outline=(*c, min(255, alpha[1] + 50)), width=max(2, r // 14))
    return im.filter(ImageFilter.GaussianBlur(max(6, rmax // 5)))


def city_night(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((10, 22, 40), (30, 34, 48))
    c.glow(W * 0.62, H * 0.62, 700, (90, 60, 50), 0.35)
    for depth, (lo, hi, col, blur, lit) in enumerate([(220, 520, (16, 28, 44), 6, 0.30),
                                                       (320, 760, (9, 18, 30), 2, 0.22)]):
        im, d = c.layer()
        x = -40
        while x < W:
            bw = int(rng.integers(70, 190)) * (1 + depth)
            top = int(H * 0.72 - rng.integers(lo, hi))
            d.rectangle((x, top, x + bw, H), fill=(*col, 255))
            if rng.random() < 0.3:
                d.rectangle((x + bw // 2 - 3, top - 90, x + bw // 2 + 3, top), fill=(*col, 255))
            for wy in range(top + 18, int(H * 0.78), 26 + depth * 8):
                for wx in range(x + 10, x + bw - 14, 22 + depth * 10):
                    if rng.random() < lit:
                        warm = rng.random() < 0.55
                        d.rectangle((wx, wy, wx + 8 + depth * 6, wy + 11 + depth * 6),
                                    fill=(*(WARM if warm else ICE), int(rng.integers(120, 240))))
            x += bw + int(rng.integers(4, 30))
        c.over(im, blur=blur)
        c.haze(H * 0.55, H * 0.78, (40, 60, 78), 0.18 - depth * 0.08)
    # Wet street: dark band with vertical light reflections.
    im, d = c.layer()
    d.rectangle((0, int(H * 0.78), W, H), fill=(5, 12, 20, 240))
    for _ in range(140):
        x = rng.uniform(0, W)
        col = WARM if rng.random() < 0.6 else TEAL
        d.line((x, H * 0.79, x + rng.uniform(-6, 6), H * rng.uniform(0.86, 1.0)), fill=(*col, 60), width=4)
    c.over(im, blur=7)
    fg = _bokeh(rng, 16, [WARM, TEAL, ICE], 40, 110, 0.05, 0.95, alpha=(25, 70))
    fim, fd = _fg()
    fd.rectangle((0, int(H * 0.9), W, H), fill=(2, 6, 10, 235))
    for x in range(0, W, 180):
        fd.rectangle((x, int(H * 0.84), x + 14, H), fill=(2, 6, 10, 235))
    fg.alpha_composite(fim.filter(ImageFilter.GaussianBlur(3)))
    return fg


def office_night(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((8, 16, 28), (12, 24, 36))
    im, d = c.layer()
    cols, rows = 14, 9
    cw, rh = W / cols, H / rows
    for i in range(cols):
        for j in range(rows):
            x, y = i * cw, j * rh
            d.rectangle((x + 10, y + 10, x + cw - 10, y + rh - 10), fill=(14, 30, 44, 255))
            r = rng.random()
            if r < 0.22:
                d.rectangle((x + 16, y + 16, x + cw - 16, y + rh - 16), fill=(*WARM, int(rng.integers(90, 190))))
            elif r < 0.36:
                d.rectangle((x + 16, y + 16, x + cw - 16, y + rh - 16), fill=(*TEAL, int(rng.integers(60, 140))))
    c.over(im, blur=3)
    for _ in range(6):
        c.glow(rng.uniform(0.1, 0.9) * W, rng.uniform(0.2, 0.8) * H, 160, WARM, 0.18)
    c.haze(H * 0.6, H * 1.1, (20, 36, 52), 0.25)
    fim, fd = _fg()
    # Our own window frame, close to the lens.
    fd.rectangle((0, 0, 120, H), fill=(3, 7, 12, 250))
    fd.rectangle((W * 0.58, 0, W * 0.58 + 70, H), fill=(3, 7, 12, 250))
    fd.rectangle((0, H * 0.83, W, H), fill=(3, 7, 12, 250))
    fg = fim.filter(ImageFilter.GaussianBlur(10))
    fg.alpha_composite(_bokeh(rng, 10, [WARM, ICE], 30, 80, 0.1, 0.8, alpha=(25, 60)))
    return fg


def _screen(d: ImageDraw.ImageDraw, rng, box, lines: int, accent: Color) -> None:
    x0, y0, x1, y1 = box
    d.rounded_rectangle(box, radius=14, fill=(10, 34, 52, 255), outline=(*accent, 200), width=4)
    lh = (y1 - y0 - 60) / max(1, lines)
    for k in range(lines):
        y = y0 + 40 + k * lh
        length = (x1 - x0 - 120) * rng.uniform(0.25, 0.95)
        d.line((x0 + 50 + (k % 3) * 24, y, x0 + 50 + length, y), fill=(*(accent if k % 5 == 0 else (70, 110, 130)), 230),
               width=max(4, int(lh * 0.32)))


def research(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((7, 14, 24), (16, 22, 30))
    im, d = c.layer()
    d.polygon([(0, H * 0.70), (W, H * 0.62), (W, H), (0, H)], fill=(20, 26, 32, 255))
    _screen(d, rng, (W * 0.30, H * 0.12, W * 0.74, H * 0.56), 14, TEAL)
    d.rectangle((W * 0.50 - 16, H * 0.56, W * 0.50 + 16, H * 0.66), fill=(18, 24, 30, 255))
    for k in range(4):
        x, y = W * (0.10 + 0.2 * k), H * (0.70 + 0.04 * (k % 2))
        d.polygon([(x, y), (x + 300, y - 22), (x + 330, y + 150), (x + 26, y + 172)], fill=(196, 204, 206, 235))
        for j in range(5):
            d.line((x + 40, y + 30 + j * 24, x + 250 - (j * 37) % 90, y + 14 + j * 24), fill=(70, 80, 90, 220),
                   width=6)
    c.over(im, blur=2)
    c.glow(W * 0.52, H * 0.34, 520, TEAL, 0.32)
    c.glow(W * 0.12, H * 0.2, 260, WARM, 0.25)
    fim, fd = _fg()
    fd.ellipse((W * 0.80, H * 0.62, W * 1.02, H * 1.1), fill=(4, 8, 12, 245))
    fg = fim.filter(ImageFilter.GaussianBlur(18))
    fg.alpha_composite(_bokeh(rng, 8, [WARM], 30, 70, 0.0, 0.4, alpha=(20, 55)))
    return fg


def prototype(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((5, 10, 18), (14, 18, 24))
    im, d = c.layer()
    d.polygon([(0, H * 0.66), (W, H * 0.66), (W, H), (0, H)], fill=(22, 24, 28, 255))
    # Laptop: screen and keyboard deck in perspective.
    _screen(d, rng, (W * 0.26, H * 0.16, W * 0.70, H * 0.62), 18, TEAL)
    d.polygon([(W * 0.22, H * 0.63), (W * 0.74, H * 0.63), (W * 0.84, H * 0.86), (W * 0.12, H * 0.86)],
              fill=(40, 46, 54, 255))
    for j in range(5):
        for k in range(16):
            x = W * 0.18 + k * W * 0.038 + j * 6
            y = H * 0.66 + j * H * 0.035
            d.rectangle((x, y, x + W * 0.03, y + H * 0.025), fill=(24, 28, 34, 255))
    c.over(im, blur=1.5)
    c.glow(W * 0.48, H * 0.40, 560, TEAL, 0.30)
    c.glow(W * 0.48, H * 0.78, 420, TEAL, 0.12)
    c.glow(W * 0.92, H * 0.18, 300, WARM, 0.35)
    fg = _bokeh(rng, 14, [WARM, TEAL], 40, 110, 0.0, 0.5, alpha=(25, 70))
    return fg


def media_infrastructure(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((6, 14, 22), (10, 20, 28))
    vx, vy = W * 0.5, H * 0.48
    im, d = c.layer()
    d.polygon([(0, H), (W, H), (vx + 60, vy + 40), (vx - 60, vy + 40)], fill=(14, 24, 32, 255))
    d.polygon([(0, 0), (W, 0), (vx + 60, vy - 60), (vx - 60, vy - 60)], fill=(8, 14, 20, 255))
    for side in (-1, 1):
        for k in range(12):
            t0, t1 = k / 12, (k + 1) / 12
            def px(t, y):
                x_edge = W / 2 + side * W / 2
                return x_edge + (vx + side * 60 - x_edge) * t, y + (vy - y) * t
            a, b = px(t0 ** 0.6, 0), px(t1 ** 0.6, 0)
            cc, dd = px(t1 ** 0.6, H), px(t0 ** 0.6, H)
            d.polygon([a, b, cc, dd], fill=(18 + k, 30 + k, 40 + k, 255), outline=(5, 10, 16, 255))
            for _ in range(14):
                tt = rng.uniform(t0, t1) ** 0.6
                yy = rng.uniform(0.15, 0.85) * H
                x, y = px(tt, yy)
                r = max(2, 9 * (1 - tt))
                col = TEAL if rng.random() < 0.7 else WARM
                d.ellipse((x - r, y - r, x + r, y + r), fill=(*col, 255))
    c.over(im, blur=1.5)
    c.glow(vx, vy, 360, (120, 220, 240), 0.35)
    c.haze(vy - 200, vy + 260, (30, 70, 86), 0.22)
    fim, fd = _fg()
    fd.rectangle((W * 0.9, 0, W, H), fill=(3, 7, 11, 250))
    for k in range(20):
        y = H * 0.08 + k * H * 0.045
        fd.ellipse((W * 0.91, y, W * 0.91 + 20, y + 20), fill=(*TEAL, 230))
    fg = fim.filter(ImageFilter.GaussianBlur(14))
    return fg


def approval(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((5, 10, 18), (12, 16, 22))
    im, d = c.layer()
    d.polygon([(0, H * 0.72), (W, H * 0.72), (W, H), (0, H)], fill=(18, 20, 24, 255))
    box = (W * 0.30, H * 0.16, W * 0.72, H * 0.66)
    d.rounded_rectangle(box, radius=18, fill=(10, 30, 46, 255), outline=(*TEAL, 210), width=5)
    d.rectangle((W * 0.34, H * 0.24, W * 0.68, H * 0.46), fill=(16, 44, 62, 255), outline=(60, 110, 130, 255), width=3)
    d.rounded_rectangle((W * 0.34, H * 0.52, W * 0.49, H * 0.60), radius=14, fill=(44, 82, 88, 255),
                        outline=(*TEAL, 255), width=3)
    d.rounded_rectangle((W * 0.53, H * 0.52, W * 0.68, H * 0.60), radius=14, fill=(63, 104, 86, 255),
                        outline=(105, 220, 170, 255), width=3)
    d.rectangle((W * 0.505, H * 0.66, W * 0.525, H * 0.73), fill=(20, 24, 30, 255))
    c.over(im, blur=1.5)
    c.glow(W * 0.51, H * 0.40, 600, TEAL, 0.25)
    c.glow(W * 0.12, H * 0.30, 340, WARM, 0.45)
    fim, fd = _fg()
    for k in range(7):
        ang = -0.9 + k * 0.28
        x0, y0 = W * 0.06, H * 1.02
        fd.ellipse((x0 + math.cos(ang) * 380 - 90, y0 + math.sin(ang) * 520 - 40,
                    x0 + math.cos(ang) * 380 + 90, y0 + math.sin(ang) * 520 + 40), fill=(3, 9, 8, 240))
    fg = fim.filter(ImageFilter.GaussianBlur(16))
    fg.alpha_composite(_bokeh(rng, 6, [WARM], 40, 90, 0.05, 0.5, alpha=(20, 50)))
    return fg


def brand_glow(c: Canvas) -> Image.Image:
    rng = c.rng
    c.gradient((4, 8, 14), (8, 14, 22))
    cx, cy = W * 0.5, H * 0.47
    im, d = c.layer()
    for k in range(9):
        r = 120 + k * 58
        col = TEAL if k % 3 else WARM
        start = rng.uniform(0, 360)
        d.arc((cx - r, cy - r * 0.62, cx + r, cy + r * 0.62), start, start + rng.uniform(120, 300),
              fill=(*col, 230), width=8)
    c.add(im, blur=10, gain=1.4)
    c.add(im, blur=1, gain=0.8)
    c.glow(cx, cy, 300, TEAL, 0.35)
    im, d = c.layer()
    d.polygon([(0, H * 0.80), (W, H * 0.80), (W, H), (0, H)], fill=(6, 12, 18, 255))
    c.over(im)
    c.haze(H * 0.75, H * 0.86, (30, 80, 96), 0.18)
    fg = _bokeh(rng, 40, [TEAL, ICE, WARM], 8, 26, 0.0, 1.0, alpha=(60, 160))
    return fg


SCENES: Dict[str, Callable[[Canvas], Image.Image]] = {
    "city_night": city_night,
    "office_night": office_night,
    "research": research,
    "prototype": prototype,
    "media_infrastructure": media_infrastructure,
    "approval": approval,
    "brand_glow": brand_glow,
}


def generate(out_dir: Path, shots: List[Dict[str, str]], project_id: str, *,
             generated_at: str = None) -> Dict[str, object]:
    """Draw one background + foreground pair per shot and return a validated asset manifest (written too).

    shots: [{"shot_id", "role", "substitutes_for"}]; role picks the scene.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = generated_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    assets = []
    for i, s in enumerate(shots):
        role = s["role"]
        if role not in SCENES:
            raise ValueError(f"no procedural scene for role {role!r}")
        seed = 4330 + i * 101 + sum(map(ord, role))
        c = Canvas(seed)
        fg = SCENES[role](c)
        bg_name, fg_name = f"orig-{s['shot_id']}-{role}.png", f"orig-{s['shot_id']}-{role}.fg.png"
        c.finish().save(out_dir / bg_name, optimize=False)
        fg.save(out_dir / fg_name, optimize=False)
        assets.append({
            "id": f"orig-{s['shot_id']}-{role}",
            "role": role,
            "source_type": "original_procedural",
            "provider": "FactoryOS (this repository)",
            "url": f"repo://film_studio/procedural.py#{role}",
            "author": f"{GENERATOR}, seed {seed} (code-drawn, no third-party input)",
            "licence": {"name": "Original work of the FactoryOS repository owner", "url": "repo://film_studio/procedural.py"},
            "attribution": "not required (original work)",
            "changes": "none (rendered as generated)",
            "rights_status": "verified",
            "verified_at": generated_at,
            "verified_by": f"{GENERATOR}: generated in this run from code only",
            "sha256": sha256_file(out_dir / bg_name),
            "local_path": bg_name,
            "layers": {"foreground": {"local_path": fg_name, "sha256": sha256_file(out_dir / fg_name)}},
            "substitutes_for": s.get("substitutes_for"),
            "notes": "Procedural illustration, not a photograph; stands in while licensed photos are unverified.",
        })
    manifest = {
        "schema": SCHEMA_ASSET_MANIFEST,
        "project_id": project_id,
        "created_at": generated_at,
        "notes": "Original procedural stand-ins generated offline by film_studio.procedural ($0, no network).",
        "assets": [{k: v for k, v in a.items() if v is not None} for a in assets],
    }
    validate_asset_manifest(manifest)
    (out_dir / "asset_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def shots_from_shotpack(storyboard: Dict, candidates: Dict) -> List[Dict[str, str]]:
    roles = {a.get("id"): a.get("role") for a in candidates.get("assets") or []}
    return [{"shot_id": s["shot_id"], "role": roles.get(s["asset_id"]), "substitutes_for": s["asset_id"]}
            for s in storyboard["shots"]]


def main(argv=None) -> int:
    repo = Path(__file__).resolve().parent.parent
    pack = repo / "docs/storyboards/blackbox-lab-45s"
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True)
    p.add_argument("--storyboard", default=str(pack / "storyboard.json"))
    p.add_argument("--candidates", default=str(pack / "asset_candidates.json"))
    a = p.parse_args(argv)
    sb = json.loads(Path(a.storyboard).read_text(encoding="utf-8"))
    cand = json.loads(Path(a.candidates).read_text(encoding="utf-8"))
    m = generate(Path(a.out), shots_from_shotpack(sb, cand), sb["project_id"])
    print(json.dumps({"assets": len(m["assets"]), "manifest": str(Path(a.out) / "asset_manifest.json")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
