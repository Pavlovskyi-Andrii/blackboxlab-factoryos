"""MyCast public podcast page and share card (owner 2026-11-13).

/mycast/u/{slug} used to jump straight into the configurator. It is now a page of its own, made for sharing on
Facebook, Telegram, X or WhatsApp: who the podcast belongs to (first name only), what is inside (topics, geography,
who they follow, schedule, voices), a player for the latest episode — only when the listener turned that on — and a
"make one like this" button that opens the configurator with these settings (the old link behaviour, referral kept).

/mycast/u/{slug}/card.png is the 1200x630 picture social networks show for that link (og:image).
Nothing private is on either: no email, chat id, calendar contents or delivery history.
"""
from __future__ import annotations

import hashlib
import html
import io
import re
import threading
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

ROOT = Path(__file__).parent / "static" / "mycast-configurator"
SITE = "https://mycast.pro"
CARD_W, CARD_H = 1200, 630
_CARDS: dict = {}
_CARD_LOCK = threading.Lock()
PLAYS_PER_HOUR = 60
_PLAYS: dict = {}

T = {
    "uk": {"title": "Подкаст {name}", "anon": "слухача MyCast", "sub": "Персональний подкаст MyCast",
           "topics": "Теми", "geo": "Географія", "follows": "Стежу", "when": "Коли", "voice": "Голос",
           "daily": "щодня", "weekdays": "у будні", "days": "у вибрані дні", "min": "хв",
           "two_hosts": "два ведучі", "narrator": "один ведучий", "lang": {"uk": "українською", "ru": "російською", "en": "англійською"},
           "listen": "Останній випуск", "no_audio": "Автор ще не відкрив свої випуски для прослуховування за посиланням.",
           "make_same": "Створити такий самий", "make_own": "Створити свій подкаст", "share": "Поділитися",
           "copy": "Скопіювати посилання", "copied": "Скопійовано", "desc": "{n} тем · {when} · {voice}"},
    "ru": {"title": "Подкаст {name}", "anon": "слушателя MyCast", "sub": "Персональный подкаст MyCast",
           "topics": "Темы", "geo": "География", "follows": "Слежу", "when": "Когда", "voice": "Голос",
           "daily": "ежедневно", "weekdays": "по будням", "days": "в выбранные дни", "min": "мин",
           "two_hosts": "два ведущих", "narrator": "один ведущий", "lang": {"uk": "на украинском", "ru": "на русском", "en": "на английском"},
           "listen": "Последний выпуск", "no_audio": "Автор ещё не открыл свои выпуски для прослушивания по ссылке.",
           "make_same": "Создать такой же", "make_own": "Создать свой подкаст", "share": "Поделиться",
           "copy": "Скопировать ссылку", "copied": "Скопировано", "desc": "{n} тем · {when} · {voice}"},
    "en": {"title": "{name}'s podcast", "anon": "A MyCast listener", "sub": "A personal MyCast podcast",
           "topics": "Topics", "geo": "Geography", "follows": "Following", "when": "When", "voice": "Voice",
           "daily": "daily", "weekdays": "on weekdays", "days": "on chosen days", "min": "min",
           "two_hosts": "two hosts", "narrator": "one host", "lang": {"uk": "in Ukrainian", "ru": "in Russian", "en": "in English"},
           "listen": "Latest episode", "no_audio": "The author has not opened their episodes for listening by link yet.",
           "make_same": "Make one like this", "make_own": "Make your own podcast", "share": "Share",
           "copy": "Copy link", "copied": "Copied", "desc": "{n} topics · {when} · {voice}"},
}


GEO_NAMES = {"world": {"uk": "Світ", "ru": "Мир", "en": "World"}, "Ukraine": {"uk": "Україна", "ru": "Украина", "en": "Ukraine"},
             "Україна": {"uk": "Україна", "ru": "Украина", "en": "Ukraine"}}


def first_name(rec: dict) -> str:
    return str(rec.get("name") or "").split(" ")[0][:40]


def summary(rec: dict, profile: dict) -> dict:
    lang = profile.get("language") if profile.get("language") in T else "uk"
    t = T[lang]
    name = first_name(rec)
    topics = [re.sub(r"\s*\([^)]*\)$", "", x) for x in profile.get("topics") or []] + list(profile.get("custom") or [])
    geo = []
    for x in profile.get("topics") or []:
        m = re.search(r"\(([^)]+)\)$", x)
        if m and m.group(1) not in geo:
            geo.append(m.group(1))
    geo = [GEO_NAMES.get(g, {}).get(lang, g) for g in geo]
    follows = [re.sub(r"^https?://(www\.)?[^/]+/", "", f.split(" ", 1)[1] if " " in f else f).rstrip("/")[:40]
               for f in profile.get("follows") or []]
    when = f"{t[profile.get('frequency', 'daily')]} · {profile.get('time', '07:30')} · {profile.get('duration_min', 10)} {t['min']}"
    voice = f"{t[profile.get('mode', 'two_hosts')]} · {t['lang'].get(lang, '')}"
    return {"lang": lang, "t": t, "name": name, "title": t["title"].format(name=name) if name else t["anon"],
            "topics": topics, "geo": geo, "follows": follows, "when": when, "voice": voice,
            "desc": t["desc"].format(n=len(topics), when=when, voice=voice)}


def latest_audio(rec: dict) -> Optional[tuple]:
    """(day, file_id) of the newest sent episode — only when the listener allowed listening by link."""
    if not rec.get("public_audio"):
        return None
    for day, e in sorted((rec.get("deliveries") or {}).items(), reverse=True):
        if e.get("status") == "sent" and e.get("file_id"):
            return day, e["file_id"]
    return None


def allow_play(slug: str, now: float) -> bool:
    hits = [t for t in _PLAYS.get(slug, []) if now - t < 3600]
    if len(hits) >= PLAYS_PER_HOUR:
        _PLAYS[slug] = hits
        return False
    _PLAYS[slug] = hits + [now]
    return True


def _chips(items, cls="chip") -> str:
    return "".join(f'<span class="{cls}">{html.escape(i)}</span>' for i in items)


def render_page(rec: dict, profile: dict, *, page: str) -> str:
    s = summary(rec, profile)
    t, slug, e = s["t"], rec["slug"], html.escape
    url = f"{SITE}/mycast/u/{slug}"
    card = f"{SITE}/mycast/u/{slug}/card.png?v={card_version(rec)}"
    make_same = f"{page}#p={rec['code']}&from={slug}"
    audio = latest_audio(rec)
    player = (f'<audio controls preload="none" src="/mycast/u/{slug}/latest.mp3"></audio><p class="mute">{e(audio[0])}</p>'
              if audio else f'<p class="mute">{e(t["no_audio"])}</p>')
    rows = [(t["topics"], _chips(s["topics"])), (t["geo"], _chips(s["geo"], "chip g") if s["geo"] else ""),
            (t["follows"], _chips(s["follows"], "chip f") if s["follows"] else ""),
            (t["when"], e(s["when"])), (t["voice"], e(s["voice"]))]
    dna = "".join(f'<div class="row"><dt>{e(k)}</dt><dd>{v}</dd></div>' for k, v in rows if v)
    share_text = quote(f"{s['title']} — MyCast")
    shares = [("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={quote(url)}"),
              ("Telegram", f"https://t.me/share/url?url={quote(url)}&text={share_text}"),
              ("X", f"https://twitter.com/intent/tweet?url={quote(url)}&text={share_text}"),
              ("WhatsApp", f"https://wa.me/?text={share_text}%20{quote(url)}")]
    share_html = "".join(f'<a class="btn" target="_blank" rel="noopener" href="{e(h)}">{e(n)}</a>' for n, h in shares)
    initial = e((s["name"] or "M")[:1].upper())
    return f"""<!DOCTYPE html>
<html lang="{s['lang']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(s['title'])} · MyCast</title>
<meta name="description" content="{e(s['desc'])}">
<meta property="og:type" content="website"><meta property="og:site_name" content="MyCast">
<meta property="og:title" content="{e(s['title'])} · MyCast"><meta property="og:description" content="{e(s['desc'])}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{e(card)}">
<meta property="og:image:width" content="{CARD_W}"><meta property="og:image:height" content="{CARD_H}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{e(card)}">
<link rel="icon" href="/static/mycast-configurator/mycast-favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/static/mycast-configurator/mycast-apple-touch.png">
<style>
:root{{--bg:#0b1024;--card:#121a38;--edge:#26325e;--ink:#eef2ff;--mute:#9aa6cf;--a:#4fe3ff;--b:#d23fa6}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;background-attachment:fixed!important;background:radial-gradient(1200px 600px at 10% -10%,#2a1d6b 0,transparent 60%),var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}}
.wrap{{max-width:760px;margin:0 auto;padding:20px 16px 48px}}
header{{display:flex;align-items:center;gap:10px;font:700 13px/1 ui-monospace,monospace;letter-spacing:.16em;color:var(--mute);text-transform:uppercase}}
header img{{border-radius:8px}}header a{{color:inherit;text-decoration:none}}header b{{color:#b65bd6;text-transform:none;letter-spacing:.04em}}
.hero{{margin:22px 0;padding:22px;border:1px solid var(--edge);border-radius:20px;background:linear-gradient(135deg,#1a2350,#121a38);display:flex;gap:16px;align-items:center}}
.av{{flex:none;width:64px;height:64px;border-radius:50%;display:grid;place-items:center;font:700 26px/1 system-ui;background:linear-gradient(135deg,var(--a),#8b7bff,var(--b));color:#0b1024}}
h1{{margin:0;font-size:clamp(22px,5vw,30px)}}.mute{{color:var(--mute);margin:4px 0 0;font-size:14px}}
section{{margin:16px 0;padding:18px;border:1px solid var(--edge);border-radius:18px;background:var(--card)}}
h2{{margin:0 0 10px;font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--mute)}}
audio{{width:100%}}dl{{margin:0}}.row{{display:grid;grid-template-columns:110px 1fr;gap:10px;padding:8px 0;border-top:1px dashed var(--edge)}}.row:first-child{{border-top:0}}
dt{{color:var(--mute);font-size:14px}}dd{{margin:0;display:flex;flex-wrap:wrap;gap:6px}}
.chip{{padding:4px 10px;border-radius:999px;background:#1d2a5a;border:1px solid #2f3f7d;font-size:13px}}.chip.f{{background:#2a1d4d;border-color:#5b3f8f}}.chip.g{{background:#0e3a48;border-color:#4fe3ff}}
.btns{{display:flex;flex-wrap:wrap;gap:8px}}.btn{{display:inline-block;padding:10px 16px;border-radius:12px;border:1px solid var(--edge);background:#18214a;color:var(--ink);text-decoration:none;font-weight:600;cursor:pointer;font-size:15px}}
.btn.primary{{border:0;background:linear-gradient(90deg,#ff8a6b,#ff6a88);color:#1a0d12}}
@media(max-width:520px){{.row{{grid-template-columns:1fr;gap:4px}}}}
</style></head><body><div class="wrap">
<header><a href="{e(page)}"><img src="/static/mycast-configurator/mycast-icon-64.png" width="32" height="32" alt=""></a><a href="{e(page)}">MyCast<b>.pro</b></a></header>
<div class="hero"><div class="av" aria-hidden="true">{initial}</div><div><h1>{e(s['title'])}</h1><p class="mute">{e(t['sub'])}</p></div></div>
<section><h2>{e(t['listen'])}</h2>{player}</section>
<section><dl>{dna}</dl></section>
<section><div class="btns"><a class="btn primary" href="{e(make_same)}">{e(t['make_same'])}</a><a class="btn" href="{e(page)}">{e(t['make_own'])}</a></div></section>
<section><h2>{e(t['share'])}</h2><div class="btns">{share_html}<button class="btn" type="button" id="copy">{e(t['copy'])}</button></div></section>
</div>
<script>document.getElementById('copy').onclick=function(){{var b=this;navigator.clipboard&&navigator.clipboard.writeText({url!r}).then(function(){{b.textContent={t['copied']!r}}})}};</script>
</body></html>"""


def card_version(rec: dict) -> str:
    return hashlib.sha256(f"{rec.get('code')}|{first_name(rec)}".encode()).hexdigest()[:10]


def _font(bold: bool, size: int):
    from PIL import ImageFont
    return ImageFont.truetype(str(ROOT / "fonts" / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def _fit(draw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def card_png(rec: dict, profile: dict) -> bytes:
    key = (rec["slug"], card_version(rec))
    with _CARD_LOCK:
        if key in _CARDS:
            return _CARDS[key]
    from PIL import Image, ImageDraw
    s = summary(rec, profile)
    img = Image.new("RGB", (CARD_W, CARD_H), (11, 16, 36))
    px = img.load()
    for y in range(CARD_H):                                  # soft violet glow, top-left
        for x in range(0, CARD_W, 4):
            d = ((x - 120) ** 2 + (y + 80) ** 2) ** 0.5
            k = max(0.0, 1 - d / 900)
            c = (int(11 + 30 * k), int(16 + 13 * k), int(36 + 70 * k))
            for dx in range(4):
                if x + dx < CARD_W:
                    px[x + dx, y] = c
    draw = ImageDraw.Draw(img)
    icon = Image.open(ROOT / "mycast-icon-512.png").convert("RGB").resize((150, 150))
    mask = Image.new("L", (150, 150), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 149, 149), radius=34, fill=255)
    img.paste(icon, (64, 64), mask)
    draw.text((240, 78), "MyCast", font=_font(True, 40), fill=(238, 242, 255))
    draw.text((240 + draw.textlength("MyCast", font=_font(True, 40)), 78), ".pro", font=_font(True, 40), fill=(182, 91, 214))
    draw.text((240, 132), _fit(draw, s["title"], _font(True, 54), 900), font=_font(True, 54), fill=(255, 255, 255))
    draw.text((64, 250), _fit(draw, s["when"] + " · " + s["voice"], _font(False, 28), 1070), font=_font(False, 28), fill=(154, 166, 207))
    x, y, chip_font = 64, 310, _font(True, 26)
    for label, is_geo in ([(x, False) for x in s["topics"]] + [(g, True) for g in s["geo"]])[:12]:
        label = _fit(draw, label, chip_font, 360)
        w = int(draw.textlength(label, font=chip_font)) + 36
        if x + w > CARD_W - 64:
            x, y = 64, y + 58
            if y > 430:
                break
        draw.rounded_rectangle((x, y, x + w, y + 44), radius=22, fill=(14, 58, 72) if is_geo else (29, 42, 90),
                               outline=(79, 227, 255) if is_geo else (63, 84, 160), width=2)
        draw.text((x + 18, y + 8), label, font=chip_font, fill=(238, 242, 255))
        x += w + 12
    if s["follows"]:
        line = s["t"]["follows"] + ": " + ", ".join(s["follows"][:6])
        draw.text((64, 500), _fit(draw, line, _font(False, 28), 1070), font=_font(False, 28), fill=(214, 160, 240))
    draw.rectangle((0, CARD_H - 10, CARD_W, CARD_H), fill=(210, 63, 166))
    draw.rectangle((0, CARD_H - 10, CARD_W // 2, CARD_H), fill=(79, 227, 255))
    draw.text((CARD_W - 64 - draw.textlength("mycast.pro", font=_font(True, 28)), 556), "mycast.pro", font=_font(True, 28), fill=(154, 166, 207))
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    data = out.getvalue()
    with _CARD_LOCK:
        if len(_CARDS) > 200:
            _CARDS.clear()
        _CARDS[key] = data
    return data
