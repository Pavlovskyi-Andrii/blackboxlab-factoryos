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


def summary(rec: dict, profile: dict, lang: str = "") -> dict:
    """`lang` overrides the page language (the author's by default). Topic names here stay as the author saved them (the
    share card uses them); render_page shows catalogue topics in the page language instead."""
    lang = lang if lang in T else (profile.get("language") if profile.get("language") in T else "uk")
    t = T[lang]
    voice_lang = profile.get("language") if profile.get("language") in T else "uk"
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
    voice = f"{t[profile.get('mode', 'two_hosts')]} · {t['lang'].get(voice_lang, '')}"
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


# T-710 (owner 2026-11-19, variant A): the profile page wears the glass style of the episode page /mycast/e/<token>.
PAGE_CSS = """
.chip{--c:#8b7bff}.chip.fo{--c:#b79cff;background:rgba(183,156,255,.12)}.chip.g{--c:#4fe3ff}
.lab{margin:16px 0 0;font:600 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--warm)}
.about .chips{margin:8px 0 0}.about dl{margin-top:14px}.shareRow{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin:14px 0 0}
.sb{display:inline-grid;place-items:center;min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--edge);background:var(--glass);color:var(--ink);
font:600 13px/1 var(--body);text-decoration:none;cursor:pointer;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.btn.ghost{background:var(--glass);border:1px solid var(--edge);color:var(--ink);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.cta .btn{margin:4px}"""


def render_page(rec: dict, profile: dict, *, page: str, lang: str = "", demos: Optional[list] = None) -> str:
    import mycast_share_page as sp
    s = summary(rec, profile, lang)
    lang = s["lang"]
    t, g, slug, e = s["t"], sp.T[lang], rec["slug"], html.escape
    url = f"{SITE}/mycast/u/{slug}"
    card = f"{SITE}/mycast/u/{slug}/card.png?v={card_version(rec)}"
    make_same = f"{page}#p={rec['code']}&from={slug}"
    audio = latest_audio(rec)
    src = f"/mycast/u/{slug}/latest.mp3" if audio else None
    d = sp.dna(rec.get("code") or "")
    ids = d["ids"] if d else []
    demos = sp.demo_cards(lang) if demos is None else demos
    n = 1 + len(demos)
    cards = [sp.card_html(g, 0, n, sp.cover_svg(ids, lang, gid="cv0"), t["listen"], s["title"], t["sub"], audio[0] if audio else "", src,
                          hint="" if audio else t["no_audio"], badge=False)]
    tracks = [{"t": f"MyCast · {audio[0]}" if audio else s["title"], "s": s["title"], "src": src or ""}]
    for k, dm in enumerate(demos, start=1):
        cards.append(sp.card_html(g, k, n, sp.city_svg(dm["motif"], dm["palette"], dm["name"], gid=f"cv{k}"), f'{g["demo"]} · {dm["name"]}',
                                  dm["title"], dm["desc"], dm["meta"], dm["audio"], hint="" if dm["audio"] else g["soon_note"]))
        tracks.append({"t": dm["title"], "s": f'{g["demo"]} · {dm["name"]}', "src": dm["audio"] or ""})
    dots = "".join(f'<button type="button" class="dot" data-go="{i}" aria-label="{e(g["slide"].format(i=i + 1, n=n))}"></button>' for i in range(n))

    counts: dict = {}
    for c in [i.split(".")[0] for i in ids] + (d["custom_cats"] if d else []):
        if c in sp.CATS:
            counts[c] = counts.get(c, 0) + 1
    total = max(1, sum(counts.values()))
    mix = "".join(f'<i style="width:{100 * v / total:.1f}%;background:{sp.CATS[c][0]}"></i>' for c, v in counts.items())
    legend = "".join(f'<span style="--c:{sp.CATS[c][0]}">{e(sp.CATS[c][1][lang])} · {v}</span>' for c, v in counts.items())
    topics = ([sp.topic_label(i, lang) for i in ids] + [str(c) for c in profile.get("custom") or []]) if d else s["topics"]
    blocks = [(t["topics"], _chips(topics)), (t["geo"], _chips(s["geo"], "chip g")), (t["follows"], _chips(s["follows"], "chip fo"))]
    chips = "".join(f'<p class="lab">{e(k)}</p><div class="chips">{v}</div>' for k, v in blocks if v)
    dl = "".join(f'<div class="dr"><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k, v in ((t["when"], s["when"]), (t["voice"], s["voice"])))
    about = (f'<section class="about glass" aria-labelledby="ab"><div class="ah"><div class="mini">{sp.cover_svg(ids, lang, gid="cva")}</div>'
             f'<div><h2 id="ab">{e(g["about"])}</h2><p class="mute">{e(s["title"])}</p></div>'
             f'<div class="num"><b>{len(topics)}</b><span>{e(g["topics_n"])}</span></div></div>'
             + (f'<div class="mix" aria-hidden="true">{mix}</div><div class="legend">{legend}</div>' if counts else "")
             + f'{chips}<dl>{dl}</dl></section>')

    share_text = quote(f"{s['title']} — MyCast")
    shares = [("Facebook", f"https://www.facebook.com/sharer/sharer.php?u={quote(url)}"),
              ("Telegram", f"https://t.me/share/url?url={quote(url)}&text={share_text}"),
              ("X", f"https://twitter.com/intent/tweet?url={quote(url)}&text={share_text}"),
              ("WhatsApp", f"https://wa.me/?text={share_text}%20{quote(url)}")]
    share_html = "".join(f'<a class="sb" target="_blank" rel="noopener" href="{e(h)}">{e(name)}</a>' for name, h in shares)
    cur_attr = ' aria-current="true"'
    langs = "".join(f'<a href="?lang={code}" hreflang="{code}"{cur_attr if code == lang else ""}>{code.upper()}</a>' for code in sp.LANGS)
    data = {"tracks": tracks, "url": url, "title": s["title"], "copied": t["copied"], "play": g["play"], "pause": g["pause"],
            "err": g["play_err"], "soon": g["soon"]}
    copy_js = ("document.getElementById('copy').onclick=function(){var b=this;navigator.clipboard&&navigator.clipboard.writeText(D.url)"
               ".then(function(){b.textContent=D.copied})};")
    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>{e(s['title'])} · MyCast</title>
<meta name="description" content="{e(s['desc'])}"><meta name="theme-color" content="#1a1430"><link rel="canonical" href="{e(url)}">
<meta property="og:type" content="website"><meta property="og:site_name" content="MyCast">
<meta property="og:title" content="{e(s['title'])} · MyCast"><meta property="og:description" content="{e(s['desc'])}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{e(card)}">
<meta property="og:image:width" content="{CARD_W}"><meta property="og:image:height" content="{CARD_H}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:image" content="{e(card)}">
<link rel="icon" href="/static/mycast-configurator/mycast-favicon-32.png" sizes="32x32" type="image/png">
<link rel="apple-touch-icon" href="/static/mycast-configurator/mycast-apple-touch.png">
<style>{sp.CSS}{PAGE_CSS}</style></head><body><div class="glow" aria-hidden="true"></div><div class="wrap">
<header><a class="brand" href="{e(page)}"><img src="/static/mycast-configurator/mycast-icon-64.png" width="28" height="28" alt=""><span>MyCast<b>.pro</b></span></a>
<nav class="langs" aria-label="{e(g['lang_label'])}">{langs}</nav></header>
<main><h1 style="position:absolute;left:-9999px">{e(s['title'])}</h1>
<section class="stage" aria-roledescription="carousel" aria-label="{e(g['carousel'])}">
<div class="deck" id="deck" tabindex="0">{"".join(cards)}</div>
<div class="ctrl"><button class="nav" type="button" id="prev" aria-label="{e(g['prev'])}">‹</button><div class="dots">{dots}</div><button class="nav" type="button" id="next" aria-label="{e(g['next'])}">›</button></div>
</section>
<div class="bar glass" id="bar"><div class="disc" id="disc">{sp.cover_svg(ids, lang, gid="cvb")}</div>
<div class="bt"><b id="bt">{e(tracks[0]['t'])}</b><span id="bs">{e(tracks[0]['s'])}</span><div class="seek"><input type="range" id="seek" min="0" max="1000" value="0" aria-label="{e(g['length'])}"><span id="tm">0:00</span></div></div>
<button class="ib" type="button" id="share" aria-label="{e(t['share'])}"><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
<button class="pp" type="button" id="pp" aria-label="{e(g['play'])}"{"" if any(x["src"] for x in tracks) else " disabled"}><span class="pi" aria-hidden="true"></span></button></div>
<p class="mute msg" id="msg" role="status" aria-live="polite"></p>
{about}
<section class="cta"><a class="btn primary" href="{e(make_same)}">{e(t['make_same'])}</a><a class="btn ghost" href="{e(page)}">{e(t['make_own'])}</a>
<div class="shareRow" aria-label="{e(t['share'])}">{share_html}<button class="sb" type="button" id="copy">{e(t['copy'])}</button></div>
<p class="mute">{e(g['demo_note'])}</p></section>
</main></div><audio id="au" preload="none"></audio>
<script>var D={sp._js(data)};{sp.JS}{copy_js}</script>
<script src="/static/mycast-configurator/v.js" data-page="profile" defer></script>
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


# ---- #305 / T-620: one public episode -------------------------------------------------------------------------
EP_T = {
    "uk": {"by": "Випуск подкасту {name}", "anon": "Випуск подкасту MyCast", "min": "хв", "share": "Поділитися",
           "copy": "Скопіювати посилання", "copied": "Скопійовано", "make_own": "Створити свій подкаст",
           "note": "Цей випуск відкрив автор. Його бачить кожен, хто має посилання; сторінка не індексується пошуковиками. "
                   "Автор може закрити посилання будь-коли — тоді воно перестане працювати.",
           "missing_h": "Випуск недоступний", "missing": "Автор закрив цей випуск або посилання неправильне."},
    "ru": {"by": "Выпуск подкаста {name}", "anon": "Выпуск подкаста MyCast", "min": "мин", "share": "Поделиться",
           "copy": "Скопировать ссылку", "copied": "Скопировано", "make_own": "Создать свой подкаст",
           "note": "Этот выпуск открыл автор. Его видит каждый, у кого есть ссылка; страница не индексируется поисковиками. "
                   "Автор может закрыть ссылку в любой момент — тогда она перестанет работать.",
           "missing_h": "Выпуск недоступен", "missing": "Автор закрыл этот выпуск или ссылка неверна."},
    "en": {"by": "An episode of {name}'s podcast", "anon": "A MyCast episode", "min": "min", "share": "Share",
           "copy": "Copy link", "copied": "Copied", "make_own": "Make your own podcast",
           "note": "The author made this episode public. Anyone with the link can listen; search engines are asked not to "
                   "index it. The author can turn the link off at any time, and then it stops working.",
           "missing_h": "Episode unavailable", "missing": "The author turned this episode off, or the link is wrong."},
}
_EP_CSS = """:root{color-scheme:dark;--bg:#0b1024;--card:#121a38;--edge:#26325e;--ink:#eef2ff;--mute:#9aa6cf}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:radial-gradient(1200px 600px at 10% -10%,#2a1d6b 0,transparent 60%),var(--bg);color:var(--ink);font:16px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
.wrap{max-width:680px;margin:0 auto;padding:20px 16px 48px}header a{color:var(--mute);text-decoration:none;font:700 13px/1 ui-monospace,monospace;letter-spacing:.16em;text-transform:uppercase}
section{margin:16px 0;padding:18px;border:1px solid var(--edge);border-radius:18px;background:var(--card)}h1{margin:0 0 4px;font-size:clamp(20px,5vw,28px)}
.mute{color:var(--mute);margin:4px 0 0;font-size:14px}audio{width:100%;margin-top:12px}.btns{display:flex;flex-wrap:wrap;gap:8px}
.btn{display:inline-block;min-height:44px;padding:10px 16px;border-radius:12px;border:1px solid var(--edge);background:#18214a;color:var(--ink);text-decoration:none;font-weight:600;cursor:pointer;font-size:15px}
.btn.primary{border:0;background:linear-gradient(90deg,#ff8a6b,#ff6a88);color:#1a0d12}a:focus-visible,.btn:focus-visible{outline:3px solid #4fe3ff;outline-offset:2px}"""


def _js(value: str) -> str:
    """A JS string literal that is safe inside <script> (the title comes from a model, so never trust it)."""
    import json
    return json.dumps(str(value)).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _ep_lang(rec: dict) -> str:
    try:
        from mycast_listener_delivery import decode_profile
        lang = decode_profile(rec.get("code") or "").get("language")
    except Exception:
        lang = "uk"
    return lang if lang in EP_T else "uk"


def render_episode_page(rec: dict, day: str, entry: dict, *, token: str, page: str) -> str:
    lang = _ep_lang(rec)
    t, e = EP_T[lang], html.escape
    name = first_name(rec)
    title = str(entry.get("title") or f"MyCast · {day}")[:64]
    by = t["by"].format(name=name) if name else t["anon"]
    minutes = max(1, round(int(entry.get("seconds") or 0) / 60)) if entry.get("seconds") else 0
    meta = day + (f" · {minutes} {t['min']}" if minutes else "")
    url = f"{SITE}/mycast/e/{token}"
    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{e(title)} · MyCast</title>
<meta name="description" content="{e(by)} · {e(meta)}">
<meta property="og:type" content="music.song"><meta property="og:site_name" content="MyCast">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(by)} · {e(meta)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{SITE}/static/mycast-configurator/mycast-logo-512.png">
<link rel="icon" href="/static/mycast-configurator/mycast-favicon-32.png" sizes="32x32" type="image/png">
<style>{_EP_CSS}</style></head><body><div class="wrap">
<header><a href="{e(page)}">MyCast.pro</a></header>
<main><section><h1>{e(title)}</h1><p class="mute">{e(by)} · {e(meta)}</p>
<audio controls preload="none" src="/mycast/e/{e(token)}/audio.mp3"></audio></section>
<section><div class="btns"><button class="btn" type="button" id="share">{e(t['share'])}</button>
<a class="btn primary" href="{e(page)}">{e(t['make_own'])}</a></div><p class="mute" id="msg" role="status" aria-live="polite"></p></section>
<p class="mute">{e(t['note'])}</p></main></div>
<script>document.getElementById('share').onclick=function(){{var u={_js(url)},m=document.getElementById('msg');
if(navigator.share){{navigator.share({{title:{_js(title)},url:u}}).catch(function(){{}});return}}
if(navigator.clipboard){{navigator.clipboard.writeText(u).then(function(){{m.textContent={_js(t['copied'])}}},function(){{m.textContent=u}})}}else m.textContent=u}};</script>
</body></html>"""


def render_episode_missing() -> str:
    t, e = EP_T["uk"], html.escape
    en = EP_T["en"]
    return f"""<!DOCTYPE html><html lang="uk"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>MyCast</title><style>{_EP_CSS}</style></head><body><div class="wrap">
<header><a href="/mycast">MyCast.pro</a></header><main><section><h1>{e(t['missing_h'])}</h1><p class="mute">{e(t['missing'])}</p>
<p class="mute" lang="en">{e(en['missing'])}</p></section><a class="btn primary" href="/mycast">{e(t['make_own'])}</a></main></div></body></html>"""
