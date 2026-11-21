"""T-713 Social autopilot post images: a 1080×1080 teaser card for every plan item, rendered locally (zero spend).

Owner 2026-11-21: «добавлять фото в каждый пост (в фото должно отображаться небольшой визуальный тизер того, что в
тексте)». The default generator draws a BlackBoxLab-style card with Pillow: the hook of the post (its first line or
sentence) as the headline, the next sentence as a sub-line, the topic as a chip, an accent colour picked from the text.
No network, no LLM, no paid call. Fonts are DejaVu Sans, shipped in the repo (Cyrillic-safe).

``ImageGenerator`` is the adapter interface. An AI image generator can be plugged in later through
``generator_from_env(env, ai=...)``, and only when the owner sets ``FACTORY_SOCIAL_AI_IMAGES=1`` (off by default);
when it fails the template card is used instead. Nothing in FactoryOS wires an AI generator today.

Images live in DATA_DIR/social_images/<item id>-<sha256 prefix>.png. The SHA-256 of the image is part of the item's
approval (``social_autopilot.approval_hash``), so the image the owner approved is exactly the image that is sent.
"""
from __future__ import annotations

import hashlib
import io
import os
import re
from pathlib import Path
from typing import Optional

W = H = 1080
FONT_DIR = Path(__file__).parent / "static" / "mycast-configurator" / "fonts"
FILE_RE = re.compile(r"^sp_[0-9a-f]{12}-[0-9a-f]{16}\.png$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
URL_RE = re.compile(r"https?://\S+")
HEADLINE_MAX = 110
SUB_MAX = 150
PALETTE = (((96, 165, 250), (167, 139, 250)), ((74, 222, 128), (45, 212, 191)), ((251, 191, 36), (248, 113, 113)),
           ((244, 114, 182), (167, 139, 250)), ((56, 189, 248), (74, 222, 128)))
FOOTER = {"uk": "Детальніше — у дописі", "ru": "Подробнее — в посте", "en": "Full story in the post"}


def ai_opt_in(env=None) -> bool:
    env = os.environ if env is None else env
    return str(env.get("FACTORY_SOCIAL_AI_IMAGES", "")).strip().lower() in ("1", "true", "yes")


def _plain(text: str) -> str:
    """Drop what DejaVu cannot draw (emoji, joiners, variation selectors) and list/markdown bullets."""
    out = "".join(ch for ch in text if ord(ch) < 0x1F000 and ch not in "‍️︎" and ord(ch) >= 32)
    out = re.sub(r"^[\s#*•\-–—>]+", "", out)
    return " ".join(out.split())


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    m = None
    for m in re.finditer(r"[.!?…](?=\s|$)", text[:limit + 1]):
        pass
    if m and m.end() >= limit // 2:
        return text[:m.end()]
    cut = text[:limit].rsplit(" ", 1)[0] if " " in text[:limit] else text[:limit]
    return cut.rstrip(",;:—– ") + "…"


def language(text: str) -> str:
    if re.search(r"[іїєґІЇЄҐ]", text):
        return "uk"
    if re.search(r"[а-яА-ЯёЁ]", text):
        return "ru"
    return "en"


def teaser(text: str) -> dict:
    """The hook of a post: {headline, sub, lang}. First line (or its first sentence) and the sentence after it."""
    lines = [_plain(URL_RE.sub("", ln)) for ln in str(text or "").split("\n")]
    lines = [ln for ln in lines if ln]
    if not lines:
        return {"headline": "BlackBoxLab", "sub": "", "lang": language(str(text or ""))}
    first = lines[0]
    m = re.search(r"[.!?…](?=\s)", first)
    if len(first) > HEADLINE_MAX and m and m.end() <= HEADLINE_MAX:
        headline, rest = first[:m.end()], first[m.end():].strip()
    else:
        headline, rest = _cut(first, HEADLINE_MAX), (first[len(_cut(first, HEADLINE_MAX)):].strip()
                                                     if len(first) > HEADLINE_MAX else "")
    headline = headline.rstrip(":").strip()
    if headline.endswith("…") and rest:
        rest = ""                                    # the headline already ends mid-sentence: no orphan tail
    sub = " ".join([rest] + lines[1:]).strip()
    return {"headline": headline, "sub": _cut(sub, SUB_MAX) if sub else "", "lang": language(str(text))}


def _font(bold: bool, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(FONT_DIR / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def _wrap(draw, text: str, font, width: int) -> list:
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=font) <= width:
            line = trial
            continue
        if line:
            lines.append(line)
        while draw.textlength(word, font=font) > width and len(word) > 1:    # one very long word
            k = len(word)
            while k > 1 and draw.textlength(word[:k], font=font) > width:
                k -= 1
            lines.append(word[:k])
            word = word[k:]
        line = word
    if line:
        lines.append(line)
    return lines


def _clip(draw, lines: list, n: int, font, width: int) -> list:
    if len(lines) <= n:
        return lines
    last = lines[n - 1]
    while last and draw.textlength(last + "…", font=font) > width:
        last = last[:-1]
    return lines[:n - 1] + [last.rstrip(" ,;:") + "…"]


def render_card(text: str, topic: str = "") -> bytes:
    """1080×1080 PNG teaser card. Deterministic: the same text and topic give the same bytes."""
    from PIL import Image, ImageChops, ImageDraw, ImageFilter
    t = teaser(text)
    acc1, acc2 = PALETTE[int(hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:8], 16) % len(PALETTE)]
    grad = Image.linear_gradient("L").resize((W, H))
    img = Image.composite(Image.new("RGB", (W, H), (26, 18, 58)), Image.new("RGB", (W, H), (9, 13, 28)), grad)
    glow = Image.new("RGB", (216, 216), (0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((140, -50, 260, 70), fill=tuple(int(c * .55) for c in acc1))
    gd.ellipse((-40, 160, 60, 260), fill=tuple(int(c * .35) for c in acc2))
    img = ImageChops.screen(img, glow.filter(ImageFilter.GaussianBlur(28)).resize((W, H)))
    draw = ImageDraw.Draw(img)
    for gx in range(80, W - 40, 60):                                   # faint lab grid of dots
        for gy in range(200, H - 160, 60):
            draw.point((gx, gy), fill=(40, 48, 84))
    # Brand row: a black box with an accent edge + the wordmark.
    draw.rounded_rectangle((80, 74, 128, 122), radius=10, fill=(4, 6, 14), outline=acc1, width=3)
    draw.rectangle((96, 90, 112, 106), fill=acc1)
    brand = _font(True, 30)
    x = 148
    for ch in "BLACKBOXLAB":
        draw.text((x, 80), ch, font=brand, fill=(231, 236, 255))
        x += draw.textlength(ch, font=brand) + 4
    if topic:
        chip_font = _font(True, 26)
        label = _clip(draw, _wrap(draw, _plain(topic), chip_font, 330), 1, chip_font, 330)
        label = label[0] if label else ""
        if label:
            cw = int(draw.textlength(label, font=chip_font)) + 40
            draw.rounded_rectangle((W - 80 - cw, 76, W - 80, 122), radius=23, fill=(22, 30, 62), outline=acc2, width=2)
            draw.text((W - 80 - cw + 20, 84), label, font=chip_font, fill=(231, 236, 255))
    # Headline: the largest size that fits five lines in the block.
    left, width = 124, W - 124 - 80
    size, lines, font = 92, [], None
    for size in (92, 84, 76, 68, 62, 56, 50, 46):
        font = _font(True, size)
        lines = _wrap(draw, t["headline"], font, width)
        if len(lines) <= 5 and len(lines) * int(size * 1.2) <= 520:
            break
    lines = _clip(draw, lines, 5, font, width)
    step = int(size * 1.2)
    sub_font = _font(False, 36)
    sub = _clip(draw, _wrap(draw, t["sub"], sub_font, width), 3, sub_font, width) if t["sub"] else []
    block = len(lines) * step + (40 + len(sub) * 50 if sub else 0)
    y = max(220, 200 + (680 - block) // 2)
    draw.rounded_rectangle((80, y + 8, 90, y + len(lines) * step - 10), radius=5, fill=acc1)
    for ln in lines:
        draw.text((left, y), ln, font=font, fill=(255, 255, 255))
        y += step
    y += 40
    for ln in sub:
        draw.text((left, y), ln, font=sub_font, fill=(170, 182, 220))
        y += 50
    # Footer: a pointer to the post text and the accent stripe.
    foot = _font(True, 30)
    note = FOOTER[t["lang"]] + "  →"
    draw.text((80, H - 118), note, font=foot, fill=acc2)
    draw.rectangle((0, H - 14, W // 2, H), fill=acc1)
    draw.rectangle((W // 2, H - 14, W, H), fill=acc2)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


class ImageGenerator:
    """Adapter interface: ``render(text, topic) -> PNG bytes``. ``name`` is recorded on the item."""
    name = ""

    def render(self, text: str, topic: str = "") -> bytes:
        raise NotImplementedError


class TemplateCardGenerator(ImageGenerator):
    name = "template_card"

    def render(self, text: str, topic: str = "") -> bytes:
        return render_card(text, topic)


class FallbackGenerator(ImageGenerator):
    """Owner-opted-in AI generator first; on any error (quota, network, bad output) the free template card."""

    def __init__(self, primary: ImageGenerator, fallback: ImageGenerator):
        self.primary, self.fallback = primary, fallback
        self.name = primary.name
        self.last = primary.name

    def render(self, text: str, topic: str = "") -> bytes:
        try:
            png = self.primary.render(text, topic)
            if isinstance(png, bytes) and png.startswith(b"\x89PNG\r\n\x1a\n"):
                self.last = self.primary.name
                return png
        except Exception:
            pass
        self.last = self.fallback.name
        return self.fallback.render(text, topic)


def generator_from_env(env=None, ai: Optional[ImageGenerator] = None) -> ImageGenerator:
    """Template card unless the owner set FACTORY_SOCIAL_AI_IMAGES=1 *and* an AI generator is wired in."""
    template = TemplateCardGenerator()
    if ai is not None and ai_opt_in(env):
        return FallbackGenerator(ai, template)
    return template


class ImageMaker:
    """Renders and stores one image per plan item under DATA_DIR/social_images/."""

    def __init__(self, data_dir: Path, generator: Optional[ImageGenerator] = None):
        self.dir = Path(data_dir) / "social_images"
        self.generator = generator or TemplateCardGenerator()

    def make(self, item_id: str, text: str, topic: str = "") -> dict:
        png = self.generator.render(text, topic)
        sha = hashlib.sha256(png).hexdigest()
        name = f"{item_id}-{sha[:16]}.png"
        if not FILE_RE.fullmatch(name):
            raise ValueError("bad item id")
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / (name + ".tmp")
        tmp.write_bytes(png)
        tmp.replace(self.dir / name)
        return {"file": name, "sha256": sha, "bytes": len(png), "w": W, "h": H,
                "generator": getattr(self.generator, "last", self.generator.name),
                "headline": teaser(text)["headline"]}

    def read(self, meta: Optional[dict]) -> Optional[bytes]:
        """The stored bytes, only if they still match the recorded SHA-256."""
        meta = meta or {}
        name, sha = str(meta.get("file") or ""), str(meta.get("sha256") or "")
        if not (FILE_RE.fullmatch(name) and SHA_RE.fullmatch(sha)):
            return None
        try:
            png = (self.dir / name).read_bytes()
        except OSError:
            return None
        return png if hashlib.sha256(png).hexdigest() == sha else None

    def remove(self, meta: Optional[dict]) -> None:
        name = str((meta or {}).get("file") or "")
        if FILE_RE.fullmatch(name):
            try:
                (self.dir / name).unlink()
            except OSError:
                pass
