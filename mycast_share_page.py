"""T-645: the shared MyCast episode card (/mycast/e/<token>), owner voice request 2026-11-16.

What a recipient of a shared episode sees, with no login:

* a coverflow of glass cards: the author's episode in the middle (cover = the same generative "DNA" cover the
  configurator draws, title, date, length, own player), demo episodes about ancient cities around it, swipe / arrows /
  keyboard, each card with its own play button when it really has audio;
* a compact glass player bar (round cover, title, subtitle, share, play/pause, seek);
* "About this podcast": topics, category mix, geography (Ukraine / world only), schedule and voice from the author's
  saved settings. Never: chat id, e-mail, slug, share code, file id, followed accounts, own free-text topics or a
  custom city.

Demo cards come from `static/mycast-share/demos.json`. A card plays only when its file sits in
`static/mycast-share/audio/` and the owner approved it (`approved_by_owner: true`); otherwise it says "soon" and has
no play button (T-645-H). T-665: a card also plays a track the owner generated with Gemini in the owner console
(`mycast_demo_audio.py`, kept under DATA_DIR) once the owner approved it. City pictures are generative SVG drawn here, no external images.
T-620 guarantees stay: noindex/no-store (route headers), revocable token, every model/user string escaped.
"""
from __future__ import annotations

import base64
import html
import json
import math
import re
from pathlib import Path
from typing import Optional

BASE = Path(__file__).parent
DEMO_MANIFEST = BASE / "static" / "mycast-share" / "demos.json"
DEMO_AUDIO_DIR = BASE / "static" / "mycast-share" / "audio"
DEMO_AUDIO_RE = re.compile(r"^/static/mycast-share/audio/[a-z0-9][a-z0-9_-]{0,60}\.(mp3|m4a|ogg)$")
# T-665: owner-generated, owner-approved tracks kept under DATA_DIR and served by mycast_demo_audio.
DEMO_SERVER_AUDIO_RE = re.compile(r"^/mycast/demo/[a-z0-9][a-z0-9_-]{0,39}\.(uk|ru|en)\.mp3$")
_DEMO_AUDIO_SOURCE = None   # callable(city, lang) -> approved public URL or None; set by app.py


def set_demo_audio_source(fn) -> None:
    global _DEMO_AUDIO_SOURCE
    _DEMO_AUDIO_SOURCE = fn
LANGS = ("uk", "ru", "en")
SITE = "https://mycast.pro"

# Mirrors index.html COLORS and configurator.js TAXONOMY top-level labels (test_mycast_share_page checks parity).
CATS = {
    "sports": ("#ff7a6b", {"en": "Sports", "uk": "Спорт", "ru": "Спорт"}),
    "tech": ("#4fe3ff", {"en": "IT & technology", "uk": "IT та технології", "ru": "IT и технологии"}),
    "news": ("#a78bfa", {"en": "Ukraine, world and local news", "uk": "Новини України, світу та міста", "ru": "Новости Украины, мира и города"}),
    "business": ("#fbbf24", {"en": "Business and personal finance", "uk": "Бізнес та особисті фінанси", "ru": "Бизнес и личные финансы"}),
    "health": ("#34d399", {"en": "Health and lifestyle", "uk": "Здоров'я та стиль життя", "ru": "Здоровье и образ жизни"}),
    "culture": ("#f472b6", {"en": "Culture and entertainment", "uk": "Культура та розваги", "ru": "Культура и развлечения"}),
    "travel": ("#60a5fa", {"en": "Travel and city", "uk": "Подорожі та місто", "ru": "Путешествия и город"}),
    "science": ("#818cf8", {"en": "Science and education", "uk": "Наука та освіта", "ru": "Наука и образование"}),
    "auto": ("#fb923c", {"en": "Automotive and transport", "uk": "Авто та транспорт", "ru": "Авто и транспорт"}),
    "hobbies": ("#a3e635", {"en": "Food and hobbies", "uk": "Їжа та хобі", "ru": "Еда и хобби"}),
}

T = {
    "uk": {"by": "Подкаст {name}", "anon": "Подкаст MyCast", "min": "хв", "yours": "Ваш випуск", "demo": "Демо", "soon": "Скоро",
           "play": "Слухати", "pause": "Пауза", "share": "Поділитися", "copied": "Посилання скопійовано", "prev": "Попередня картка",
           "next": "Наступна картка", "carousel": "Випуски", "slide": "Картка {i} з {n}", "about": "Про подкаст",
           "topics": "Теми", "topics_n": "тем обрано", "geo": "Географія", "when": "Коли", "voice": "Голос", "length": "Тривалість",
           "geo_names": {"ukraine": "Україна", "world": "Світ"},
           "freq": {"daily": "Щодня", "weekdays": "У будні", "days": "У вибрані дні"},
           "days": {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт", "fri": "Пт", "sat": "Сб", "sun": "Нд"},
           "modes": {"narrator": "Один ведучий", "two_hosts": "Два ведучі"}, "langs": {"uk": "Українська", "ru": "Русский", "en": "English"},
           "demo_note": "Демо-випуски показують, як звучать голоси ведучих MyCast. Вони не є частиною подкасту автора.",
           "soon_note": "Цей демо-випуск ще готується — відтворення з’явиться, коли його затвердять.",
           "make_own": "Створити свій подкаст", "play_err": "Не вдалося відтворити. Спробуйте ще раз трохи пізніше.",
           "note": "Цей випуск відкрив автор. Його бачить кожен, хто має посилання; сторінка не індексується пошуковиками. "
                   "Автор може закрити посилання будь-коли — тоді воно перестане працювати.",
           "lang_label": "Мова сторінки"},
    "ru": {"by": "Подкаст {name}", "anon": "Подкаст MyCast", "min": "мин", "yours": "Выпуск автора", "demo": "Демо", "soon": "Скоро",
           "play": "Слушать", "pause": "Пауза", "share": "Поделиться", "copied": "Ссылка скопирована", "prev": "Предыдущая карточка",
           "next": "Следующая карточка", "carousel": "Выпуски", "slide": "Карточка {i} из {n}", "about": "О подкасте",
           "topics": "Темы", "topics_n": "тем выбрано", "geo": "География", "when": "Когда", "voice": "Голос", "length": "Длительность",
           "geo_names": {"ukraine": "Украина", "world": "Мир"},
           "freq": {"daily": "Ежедневно", "weekdays": "По будням", "days": "В выбранные дни"},
           "days": {"mon": "Пн", "tue": "Вт", "wed": "Ср", "thu": "Чт", "fri": "Пт", "sat": "Сб", "sun": "Вс"},
           "modes": {"narrator": "Один ведущий", "two_hosts": "Два ведущих"}, "langs": {"uk": "Українська", "ru": "Русский", "en": "English"},
           "demo_note": "Демо-выпуски показывают, как звучат голоса ведущих MyCast. Они не входят в подкаст автора.",
           "soon_note": "Этот демо-выпуск ещё готовится — воспроизведение появится, когда его утвердят.",
           "make_own": "Создать свой подкаст", "play_err": "Не удалось воспроизвести. Попробуйте ещё раз чуть позже.",
           "note": "Этот выпуск открыл автор. Его видит каждый, у кого есть ссылка; страница не индексируется поисковиками. "
                   "Автор может закрыть ссылку в любой момент — тогда она перестанет работать.",
           "lang_label": "Язык страницы"},
    "en": {"by": "{name}'s podcast", "anon": "A MyCast podcast", "min": "min", "yours": "The author's episode", "demo": "Demo", "soon": "Soon",
           "play": "Listen", "pause": "Pause", "share": "Share", "copied": "Link copied", "prev": "Previous card",
           "next": "Next card", "carousel": "Episodes", "slide": "Card {i} of {n}", "about": "About this podcast",
           "topics": "Topics", "topics_n": "topics chosen", "geo": "Geography", "when": "When", "voice": "Voice", "length": "Length",
           "geo_names": {"ukraine": "Ukraine", "world": "World"},
           "freq": {"daily": "Daily", "weekdays": "On weekdays", "days": "On chosen days"},
           "days": {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat", "sun": "Sun"},
           "modes": {"narrator": "One narrator", "two_hosts": "Two hosts"}, "langs": {"uk": "Українська", "ru": "Русский", "en": "English"},
           "demo_note": "Demo episodes show how the MyCast hosts sound. They are not part of the author's podcast.",
           "soon_note": "This demo episode is still being prepared; playback appears once it is approved.",
           "make_own": "Make your own podcast", "play_err": "Could not play. Please try again a little later.",
           "note": "The author made this episode public. Anyone with the link can listen; search engines are asked not to "
                   "index it. The author can turn the link off at any time, and then it stops working.",
           "lang_label": "Page language"},
}


# ---- the author's DNA, public part only --------------------------------------------------------------------------
def dna(code: str) -> Optional[dict]:
    """Topic ids, schedule and voice from a saved share code; None when it cannot be read. Nothing identifying."""
    from mycast_listener_delivery import DURATIONS, TOPICS, WEEKDAYS, _SPEC
    raw = str(code or "")[:8000]
    try:
        data = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("v") != _SPEC["share_version"] or data.get("n") != len(TOPICS):
        return None
    ids, geo = [], {"ukraine": 0, "world": 0}
    for row in data.get("t") if isinstance(data.get("t"), list) else []:
        if isinstance(row, list) and row and isinstance(row[0], int) and not isinstance(row[0], bool) and 0 <= row[0] < len(TOPICS):
            tid = TOPICS[row[0]][0]
            if tid in ids:
                continue
            ids.append(tid)
            scope = row[1] if len(row) > 1 else ""
            if scope == "u":
                geo["ukraine"] += 1
            elif scope == "w":
                geo["world"] += 1                      # "c" (a custom city or country) is never shown: it can locate a person
    custom_cats = []
    for group, items in (data.get("c") or {}).items() if isinstance(data.get("c"), dict) else []:
        if isinstance(items, list) and str(group).split(".")[0] in CATS:
            custom_cats += [str(group).split(".")[0]] * len([i for i in items[:5] if str(i).strip()])
    o = data.get("o") if isinstance(data.get("o"), list) else []
    s = data.get("s") if isinstance(data.get("s"), list) else []
    at = s[1] if len(s) > 1 and isinstance(s[1], str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", s[1]) else "07:30"
    return {"ids": sorted(ids), "custom_cats": custom_cats, "geo": geo,
            "language": o[1] if len(o) > 1 and o[1] in LANGS else "uk",
            "mode": o[0] if o and o[0] in ("narrator", "two_hosts") else "two_hosts",
            "time": at, "frequency": s[2] if len(s) > 2 and s[2] in ("daily", "weekdays", "days") else "daily",
            "days": [d for d in (s[3] if len(s) > 3 and isinstance(s[3], list) else []) if d in WEEKDAYS],
            "duration": s[4] if len(s) > 4 and s[4] in DURATIONS else 10}


def topic_label(tid: str, lang: str) -> str:
    from mycast_listener_delivery import LANG_COL, TOPICS
    for row in TOPICS:
        if row[0] == tid:
            return row[LANG_COL[lang]]
    return tid


def _cat(tid: str) -> str:
    return tid.split(".")[0]


# ---- the generative cover: a port of index.html coverSVG() --------------------------------------------------------
def _fnv(s: str) -> int:
    h = 2166136261
    for ch in s:
        h ^= ord(ch)
        h = (h * 16777619) & 0xFFFFFFFF
    return h


def _fix1(x: float) -> str:
    """JS Number.toFixed(1) for the positive values used here (round half up on the decimal string)."""
    return f"{math.floor(x * 10 + 0.5 + 1e-9) / 10:.1f}"


def cover_svg(ids: list, lang: str, *, gid: str = "cv") -> str:
    """Same drawing as the configurator's DNA cover: one ring per topic coloured by category. `gid` keeps gradient ids
    unique when several covers share a page."""
    ids = sorted(ids)
    cats = list(dict.fromkeys(_cat(i) for i in ids))
    c1 = CATS.get(cats[0], ("#5b43ff",))[0] if cats else "#5b43ff"
    c2 = CATS.get(cats[1], ("#00c8ff",))[0] if len(cats) > 1 else "#00c8ff"
    rings = []
    for i, tid in enumerate(ids[:12]):
        h = _fnv(tid)
        r = 34 + i * 7.5
        ln = 0.35 + (h % 55) / 100
        signed = h - (1 << 32) if h >= (1 << 31) else h       # JS `h >> 8` works on a signed int32
        start = int(math.fmod(signed >> 8, 360))
        circ = 2 * math.pi * r
        color = CATS.get(_cat(tid), ("#8b7bff",))[0]
        rings.append(f'<circle cx="120" cy="120" r="{_fix1(r)}" fill="none" stroke="{color}" stroke-width="4.5" '
                     f'stroke-linecap="round" stroke-dasharray="{_fix1(circ * ln)} {_fix1(circ)}" transform="rotate({start} 120 120)" opacity=".92"/>')
    label = " · ".join(CATS[c][1][lang] for c in cats[:2] if c in CATS)
    empty = '<circle cx="120" cy="120" r="60" fill="none" stroke="#2a3366" stroke-width="2" stroke-dasharray="4 8"/>'
    return (f'<svg viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg"><defs><radialGradient id="{gid}" cx="35%" cy="30%">'
            f'<stop offset="0" stop-color="{c1}" stop-opacity=".55"/><stop offset=".6" stop-color="{c2}" stop-opacity=".18"/>'
            f'<stop offset="1" stop-color="#0b1024"/></radialGradient></defs>'
            f'<rect width="240" height="240" fill="#0b1024"/><rect width="240" height="240" fill="url(#{gid})"/>{"".join(rings) or empty}'
            f'<circle cx="120" cy="120" r="22" fill="#070a16"/><circle cx="120" cy="120" r="5" fill="#eef1ff"/>'
            f'<text x="16" y="28" fill="#eef1ff" font-family="Georgia,serif" font-size="20" font-weight="700">MyCast</text>'
            f'<text x="16" y="224" fill="#c8cee8" font-family="ui-monospace,Menlo,monospace" font-size="10">{_esc_js(label or "— — —")}</text></svg>')


def _esc_js(s: str) -> str:
    """index.html esc(): the same entities, so the cover is byte-identical to the configurator's."""
    return html.escape(str(s)).replace("&#x27;", "&#39;")


# ---- demo cards ---------------------------------------------------------------------------------------------------
_MOTIFS = {
    # Line-art silhouettes on the DNA-style background (own drawing, no external images).
    "temple": '<path d="M62 150h116M70 142h100M76 104h88l-44-24z" stroke="#fff3df" stroke-width="3" fill="none" stroke-linejoin="round"/>'
              + "".join(f'<path d="M{82 + k * 15.2:.1f} 108v32" stroke="#fff3df" stroke-width="5" stroke-linecap="round"/>' for k in range(6))
              + '<path d="M40 170q40-14 80-12t80 12" stroke="#ffd7a8" stroke-width="2" fill="none" opacity=".7"/>',
    "colosseum": '<path d="M52 150V100q68-26 136 0v50" stroke="#fff3df" stroke-width="3" fill="none"/>'
                 + "".join(f'<path d="M{60 + k * 17} 148v-14a7 7 0 0 1 14 0v14" stroke="#fff3df" stroke-width="2.4" fill="none"/>' for k in range(7))
                 + "".join(f'<path d="M{63 + k * 17} 124v-10a5.5 5.5 0 0 1 11 0v10" stroke="#ffd7a8" stroke-width="2" fill="none"/>' for k in range(7))
                 + '<path d="M52 150h136" stroke="#fff3df" stroke-width="3"/>',
    "tholos": '<ellipse cx="120" cy="96" rx="44" ry="10" stroke="#fff3df" stroke-width="3" fill="none"/>'
              + "".join(f'<path d="M{88 + k * 16} 102v44" stroke="#fff3df" stroke-width="5" stroke-linecap="round"/>' for k in range(5))
              + '<path d="M70 150h100M64 158h112" stroke="#fff3df" stroke-width="3"/><path d="M30 120l30-34 20 18 24-30" stroke="#ffd7a8" stroke-width="2" fill="none" opacity=".6"/>',
    "wreath": '<path d="M120 160c-40-6-56-40-50-76M120 160c40-6 56-40 50-76" stroke="#fff3df" stroke-width="3" fill="none"/>'
              + "".join(f'<ellipse cx="{x}" cy="{y}" rx="5" ry="10" transform="rotate({a} {x} {y})" fill="#ffd7a8" opacity=".85"/>'
                        for x, y, a in ((76, 98, -20), (80, 118, -40), (90, 136, -60), (104, 150, -75), (164, 98, 20), (160, 118, 40), (150, 136, 60), (136, 150, 75)))
              + '<path d="M120 84l6 14h15l-12 9 5 15-14-9-14 9 5-15-12-9h15z" fill="#fff3df"/>',
    "volcano": '<path d="M44 158l52-62h48l52 62z" stroke="#fff3df" stroke-width="3" fill="none" stroke-linejoin="round"/>'
               + '<path d="M106 92q-8-20 6-30t4-28M126 92q10-16 2-30" stroke="#ffd7a8" stroke-width="2.4" fill="none" opacity=".8"/>'
               + "".join(f'<path d="M{66 + k * 12} 158v-18" stroke="#fff3df" stroke-width="4" stroke-linecap="round"/>' for k in range(3)),
}


def city_svg(motif: str, palette: list, label: str, *, gid: str) -> str:
    a, b = (palette + ["#ff9a6b", "#8b7bff"])[:2]
    arcs = "".join(f'<circle cx="120" cy="120" r="{40 + k * 14}" fill="none" stroke="{a if k % 2 else b}" stroke-width="2" '
                   f'stroke-dasharray="{60 + k * 22} {400}" transform="rotate({k * 47} 120 120)" opacity=".45"/>' for k in range(6))
    return (f'<svg viewBox="0 0 240 240" xmlns="http://www.w3.org/2000/svg"><defs><radialGradient id="{gid}" cx="50%" cy="38%">'
            f'<stop offset="0" stop-color="{a}" stop-opacity=".75"/><stop offset=".55" stop-color="{b}" stop-opacity=".25"/>'
            f'<stop offset="1" stop-color="#140f24"/></radialGradient></defs><rect width="240" height="240" fill="#140f24"/>'
            f'<rect width="240" height="240" fill="url(#{gid})"/>{arcs}{_MOTIFS.get(motif, _MOTIFS["temple"])}'
            f'<text x="16" y="28" fill="#fff3df" font-family="Georgia,serif" font-size="20" font-weight="700">MyCast</text>'
            f'<text x="16" y="224" fill="#ffe6cc" font-family="ui-monospace,Menlo,monospace" font-size="10">{html.escape(label)}</text></svg>')


def _loc(v, lang: str) -> str:
    if isinstance(v, dict):
        return str(v.get(lang) or v.get("en") or next(iter(v.values()), ""))[:240]
    return str(v or "")[:240]


def demo_cards(lang: str, *, manifest: Path = DEMO_MANIFEST, audio_dir: Path = DEMO_AUDIO_DIR, server_audio=None) -> list:
    """Demo cards from the manifest. `audio` is kept only for an owner-approved local file that exists, or (T-665) an
    owner-approved track from the server store (`server_audio(city, lang)`)."""
    server_audio = _DEMO_AUDIO_SOURCE if server_audio is None else server_audio
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except Exception:
        return []
    out = []
    for d in (data.get("demos") or [])[:12] if isinstance(data, dict) else []:
        if not isinstance(d, dict) or not re.fullmatch(r"[a-z0-9_-]{1,40}", str(d.get("id") or "")):
            continue
        audio = str(d.get("audio") or "")
        playable = (d.get("approved_by_owner") is True and bool(DEMO_AUDIO_RE.match(audio))
                    and (audio_dir / audio.rsplit("/", 1)[1]).is_file())
        meta = _loc(d.get("meta"), lang)
        if not playable and server_audio:
            try:
                url = server_audio(d["id"], lang)
            except Exception:
                url = None
            if isinstance(url, str) and DEMO_SERVER_AUDIO_RE.match(url):
                audio, playable = url, True
                track_lang = url.rsplit(".", 2)[1]
                if track_lang != lang:                       # say so when only another language is approved
                    meta = f"{meta} · {track_lang.upper()}"
        palette = [c for c in (d.get("palette") or []) if isinstance(c, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", c)]
        out.append({"id": d["id"], "name": _loc(d.get("name"), lang), "title": _loc(d.get("title"), lang),
                    "desc": _loc(d.get("desc"), lang), "meta": meta,
                    "motif": str(d.get("motif") or "temple"), "palette": palette, "audio": audio if playable else None})
    return out


# ---- language -----------------------------------------------------------------------------------------------------
def pick_lang(query: str, accept: str, author: str) -> str:
    """?lang= first, then the browser's first supported language, then the author's."""
    if query in LANGS:
        return query
    for part in str(accept or "").split(",")[:8]:
        tag = part.split(";")[0].strip().lower()[:2]
        if tag in LANGS:
            return tag
    return author if author in LANGS else "uk"


def _js(value) -> str:
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# ---- page ---------------------------------------------------------------------------------------------------------
def render(rec: dict, day: str, entry: dict, *, token: str, page: str, lang: str = "", accept: str = "",
           demos: Optional[list] = None) -> str:
    from mycast_public import first_name
    d = dna(rec.get("code") or "")
    lang = pick_lang(lang, accept, (d or {}).get("language", "uk"))
    t, e = T[lang], html.escape
    name = first_name(rec)
    title = str(entry.get("title") or f"MyCast · {day}")[:64]
    by = t["by"].format(name=name) if name else t["anon"]
    minutes = max(1, round(int(entry.get("seconds") or 0) / 60)) if entry.get("seconds") else 0
    meta = day + (f" · {minutes} {t['min']}" if minutes else "")
    if d:
        voice = f"{t['modes'][d['mode']]} · {t['langs'][d['language']]}"
        freq = t["freq"][d["frequency"]]
        if d["frequency"] == "days" and d["days"]:
            freq = " ".join(t["days"][x] for x in d["days"])
        when = f"{freq} · {d['time']} · {d['duration']} {t['min']}"
        meta += f" · {t['modes'][d['mode']]}"
    url = f"{SITE}/mycast/e/{token}"
    demos = demo_cards(lang) if demos is None else demos
    n = 1 + len(demos)
    cover = cover_svg(d["ids"] if d else [], lang, gid="cv0")

    def card(i, art, kicker, h, desc, meta_line, src, soon=False):
        play = (f'<button class="play" type="button" data-play="{i}" aria-label="{e(t["play"])}: {e(h)}"><span class="pi" aria-hidden="true"></span>'
                f'<span class="pl">{e(t["play"])}</span></button>') if src else f'<span class="soon">{e(t["soon"])}</span>'
        return (f'<article class="card{" own" if i == 0 else ""}" data-i="{i}" data-src="{e(src or "")}" role="group" '
                f'aria-roledescription="slide" aria-label="{e(t["slide"].format(i=i + 1, n=n))}">'
                f'<div class="art">{art}</div><div class="body"><div class="row1"><span class="kick">{e(kicker)}</span>'
                f'<span class="count">{i + 1} / {n}</span></div><h2>{e(h)}</h2><p class="desc">{e(desc)}</p>'
                f'<div class="row2"><span class="meta">{e(meta_line)}</span>{play}</div>'
                + (f'<p class="hint">{e(t["soon_note"])}</p>' if soon else "") + "</div></article>")

    cards = [card(0, cover, t["yours"], title, by, meta, f"/mycast/e/{token}/audio.mp3")]
    tracks = [{"t": title, "s": by, "src": f"/mycast/e/{token}/audio.mp3"}]
    for k, dm in enumerate(demos, start=1):
        art = city_svg(dm["motif"], dm["palette"], dm["name"], gid=f"cv{k}")
        cards.append(card(k, art, f'{t["demo"]} · {dm["name"]}', dm["title"], dm["desc"], dm["meta"], dm["audio"], soon=not dm["audio"]))
        tracks.append({"t": dm["title"], "s": f'{t["demo"]} · {dm["name"]}', "src": dm["audio"] or ""})
    dots = "".join(f'<button type="button" class="dot" data-go="{i}" aria-label="{e(t["slide"].format(i=i + 1, n=n))}"></button>' for i in range(n))

    about = ""
    if d:
        counts: dict = {}
        for c in [_cat(i) for i in d["ids"]] + d["custom_cats"]:
            if c in CATS:
                counts[c] = counts.get(c, 0) + 1
        total = max(1, sum(counts.values()))
        mix = "".join(f'<i style="width:{100 * v / total:.1f}%;background:{CATS[c][0]}"></i>' for c, v in counts.items())
        legend = "".join(f'<span style="--c:{CATS[c][0]}">{e(CATS[c][1][lang])} · {v}</span>' for c, v in counts.items())
        chips = "".join(f'<span class="chip" style="--c:{CATS.get(_cat(i), ("#8b7bff",))[0]}">{e(topic_label(i, lang))}</span>' for i in d["ids"][:24])
        geo = " · ".join(f'{t["geo_names"][k]} {v}' for k, v in d["geo"].items() if v)
        rows = [(t["geo"], e(geo)) if geo else None, (t["when"], e(when)), (t["voice"], e(voice))]
        dl = "".join(f'<div class="dr"><dt>{e(k)}</dt><dd>{v}</dd></div>' for k, v in (r for r in rows if r))
        about = (f'<section class="about glass" aria-labelledby="ab"><div class="ah"><div class="mini">{cover_svg(d["ids"], lang, gid="cva")}</div>'
                 f'<div><h2 id="ab">{e(t["about"])}</h2><p class="mute">{e(by)}</p></div>'
                 f'<div class="num"><b>{sum(counts.values())}</b><span>{e(t["topics_n"])}</span></div></div>'
                 f'<div class="mix" aria-hidden="true">{mix}</div><div class="legend">{legend}</div>'
                 f'<div class="chips" aria-label="{e(t["topics"])}">{chips}</div><dl>{dl}</dl></section>')

    cur_attr = ' aria-current="true"'
    langs = "".join(f'<a href="?lang={code}" hreflang="{code}"{cur_attr if code == lang else ""}>{code.upper()}</a>' for code in LANGS)
    data = {"tracks": tracks, "url": url, "title": title, "copied": t["copied"], "play": t["play"], "pause": t["pause"],
            "err": t["play_err"], "soon": t["soon"]}
    return f"""<!DOCTYPE html>
<html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow"><meta name="referrer" content="no-referrer"><title>{e(title)} · MyCast</title>
<meta name="description" content="{e(by)} · {e(meta)}"><meta name="theme-color" content="#1a1430">
<meta property="og:type" content="music.song"><meta property="og:site_name" content="MyCast">
<meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(by)} · {e(meta)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{SITE}/static/mycast-configurator/mycast-logo-512.png">
<link rel="icon" href="/static/mycast-configurator/mycast-favicon-32.png" sizes="32x32" type="image/png">
<style>{CSS}</style></head><body><div class="glow" aria-hidden="true"></div><div class="wrap">
<header><a class="brand" href="{e(page)}"><img src="/static/mycast-configurator/mycast-icon-64.png" width="28" height="28" alt=""><span>MyCast<b>.pro</b></span></a>
<nav class="langs" aria-label="{e(t['lang_label'])}">{langs}</nav></header>
<main>
<section class="stage" aria-roledescription="carousel" aria-label="{e(t['carousel'])}">
<div class="deck" id="deck" tabindex="0">{"".join(cards)}</div>
<div class="ctrl"><button class="nav" type="button" id="prev" aria-label="{e(t['prev'])}">‹</button><div class="dots">{dots}</div><button class="nav" type="button" id="next" aria-label="{e(t['next'])}">›</button></div>
</section>
<div class="bar glass" id="bar"><div class="disc" id="disc">{cover_svg(d["ids"] if d else [], lang, gid="cvb")}</div>
<div class="bt"><b id="bt">{e(title)}</b><span id="bs">{e(by)}</span><div class="seek"><input type="range" id="seek" min="0" max="1000" value="0" aria-label="{e(t['length'])}"><span id="tm">0:00</span></div></div>
<button class="ib" type="button" id="share" aria-label="{e(t['share'])}"><svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg></button>
<button class="pp" type="button" id="pp" aria-label="{e(t['play'])}"><span class="pi" aria-hidden="true"></span></button></div>
<p class="mute msg" id="msg" role="status" aria-live="polite"></p>
{about}
<section class="cta"><a class="btn primary" href="{e(page)}">{e(t['make_own'])}</a>
<p class="mute">{e(t['demo_note'])}</p><p class="mute">{e(t['note'])}</p></section>
</main></div><audio id="au" preload="none"></audio>
<script>var D={_js(data)};{JS}</script>
</body></html>"""


CSS = """:root{color-scheme:dark;--bg:#140f24;--ink:#fff8f0;--mute:#d9cfe6;--dim:#a99fbf;--glass:rgba(255,255,255,.09);--glass2:rgba(255,255,255,.14);
--edge:rgba(255,255,255,.22);--warm:#ffb37a;--coral:#ff7a6b;--display:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--body:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;--cw:min(76vw,300px)}
*{box-sizing:border-box}html,body{margin:0;overflow-x:hidden}
body{min-height:100vh;background:var(--bg);color:var(--ink);font:16px/1.5 var(--body)}
.glow{position:fixed;inset:0;z-index:-1;background:radial-gradient(60vmax 40vmax at 50% -6%,rgba(255,170,110,.42),transparent 62%),
radial-gradient(50vmax 40vmax at -10% 40%,rgba(139,123,255,.30),transparent 60%),radial-gradient(50vmax 40vmax at 110% 70%,rgba(79,227,255,.16),transparent 60%),
radial-gradient(40vmax 30vmax at 50% 110%,rgba(255,122,107,.22),transparent 60%),var(--bg)}
.wrap{max-width:1080px;margin:0 auto;padding:16px 16px 40px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px}
.brand{display:flex;align-items:center;gap:8px;color:var(--ink);text-decoration:none;font:700 18px/1 var(--display)}.brand img{border-radius:8px}.brand b{color:var(--warm)}
.langs{display:flex;gap:4px;padding:4px;border-radius:999px;background:var(--glass);border:1px solid var(--edge);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.langs a{min-width:36px;padding:6px 8px;border-radius:999px;color:var(--mute);text-decoration:none;font:600 12px/1 var(--body);text-align:center}
.langs a[aria-current]{background:rgba(255,255,255,.18);color:var(--ink)}
.glass{background:var(--glass);border:1px solid var(--edge);backdrop-filter:blur(22px) saturate(140%);-webkit-backdrop-filter:blur(22px) saturate(140%);
box-shadow:0 20px 50px rgba(10,5,25,.35),inset 0 1px 0 rgba(255,255,255,.18)}
.stage{position:relative;margin:10px -16px 8px;padding:8px 16px 0;overflow-x:hidden;overflow-x:clip}
.deck{display:flex;gap:14px;overflow-x:auto;scroll-snap-type:x mandatory;padding:8px 2px 16px;outline:none}
.card{flex:none;width:var(--cw);scroll-snap-align:center;border-radius:30px;overflow:hidden;background:var(--glass2);border:1px solid var(--edge);
backdrop-filter:blur(24px) saturate(150%);-webkit-backdrop-filter:blur(24px) saturate(150%);box-shadow:0 24px 60px rgba(10,5,25,.45),inset 0 1px 0 rgba(255,255,255,.25)}
.art{padding:10px 10px 0}.art svg{display:block;width:100%;aspect-ratio:1;border-radius:22px}
.body{padding:12px 18px 18px}.row1,.row2{display:flex;align-items:center;justify-content:space-between;gap:8px}
.kick{font:600 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--warm);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.count{flex:none;font:600 12px/1 var(--body);color:var(--mute);padding:5px 9px;border-radius:999px;background:rgba(255,255,255,.12)}
.card h2{margin:8px 0 4px;font:600 22px/1.2 var(--display);overflow-wrap:anywhere;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.desc{margin:0 0 12px;color:var(--mute);font-size:14px;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.meta{color:var(--dim);font-size:12.5px}.hint{margin:10px 0 0;color:var(--dim);font-size:12px}
.play{flex:none;display:inline-flex;align-items:center;gap:8px;min-height:44px;padding:0 16px 0 12px;border:0;border-radius:999px;cursor:pointer;
background:linear-gradient(90deg,#ffb37a,#ff7a6b);color:#2a0d08;font:700 14px/1 var(--body)}
.soon{flex:none;padding:8px 12px;border-radius:999px;border:1px dashed var(--edge);color:var(--mute);font:600 12px/1 var(--body)}
.pi{display:inline-block;width:0;height:0;border-left:11px solid currentColor;border-top:7px solid transparent;border-bottom:7px solid transparent}
.on .pi,.pp.on .pi{width:11px;height:13px;border:0;border-left:4px solid currentColor;border-right:4px solid currentColor}
.ctrl{display:flex;align-items:center;justify-content:center;gap:14px;margin-top:2px}.nav{display:none}.dots{display:flex;justify-content:center;gap:6px}
.dot{width:8px;height:8px;padding:0;border:0;border-radius:99px;background:rgba(255,255,255,.3);cursor:pointer;transition:width .25s}
.dot[aria-current="true"]{width:22px;background:var(--ink)}
.deck.cf{display:block;position:relative;height:calc(var(--cw) + 250px);overflow:visible;perspective:1100px;touch-action:pan-y;padding:0}
.deck.cf .card{position:absolute;left:50%;top:0;margin-left:calc(var(--cw) / -2);transition:transform .45s cubic-bezier(.2,.7,.2,1),opacity .45s,filter .45s;will-change:transform}
.deck.cf .card.side{cursor:pointer;filter:saturate(.85) brightness(.85)}.deck.cf .card.side .play{pointer-events:none}
.deck.cf .card.far{opacity:0;pointer-events:none}
.stage.js .nav{display:grid;place-items:center;width:44px;height:44px;border-radius:50%;border:1px solid var(--edge);
background:var(--glass2);color:var(--ink);font:400 26px/1 var(--body);cursor:pointer;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.bar{position:sticky;bottom:12px;z-index:50;display:flex;align-items:center;gap:12px;margin:14px auto 0;max-width:560px;padding:10px 10px 10px 10px;border-radius:999px}
.disc{flex:none;width:48px;height:48px;border-radius:50%;overflow:hidden;border:1px solid var(--edge)}.disc svg{width:100%;height:100%;display:block}
.bar.playing .disc{animation:spin 8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}
.bt{flex:1;min-width:0;display:flex;flex-direction:column}.bt b,.bt span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.bt b{font-size:14px}.bt>span{font-size:12px;color:var(--mute)}
.seek{display:flex;align-items:center;gap:8px}.seek input{flex:1;min-width:0;accent-color:#ffb37a;height:18px;margin:0}.seek span{font:600 11px/1 ui-monospace,monospace;color:var(--mute)}
.ib,.pp{flex:none;display:grid;place-items:center;width:44px;height:44px;border-radius:50%;border:1px solid var(--edge);background:rgba(255,255,255,.1);color:var(--ink);cursor:pointer}
.pp{width:52px;height:52px;border:0;background:var(--ink);color:#1a1430}.pp:disabled{opacity:.4;cursor:default}
.msg{text-align:center;min-height:1.4em;margin:8px 0 0;font-size:13px}
.about{margin:22px auto 0;max-width:760px;padding:20px;border-radius:28px}
.ah{display:flex;align-items:center;gap:14px}.ah h2{margin:0;font:600 22px/1.2 var(--display)}.mini{flex:none;width:64px;height:64px;border-radius:16px;overflow:hidden}.mini svg{display:block;width:100%;height:100%}
.num{margin-left:auto;text-align:right}.num b{display:block;font:600 30px/1 var(--display)}.num span{font-size:11px;color:var(--mute)}
.mix{display:flex;height:8px;border-radius:99px;overflow:hidden;margin:16px 0 8px;background:rgba(255,255,255,.08)}.mix i{display:block}
.legend{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:12px;color:var(--mute)}.legend span::before{content:"";display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--c);margin-right:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0}.chip{padding:5px 11px;border-radius:999px;font-size:13px;background:rgba(255,255,255,.08);border:1px solid color-mix(in srgb,var(--c) 60%,transparent)}
dl{margin:0}.dr{display:grid;grid-template-columns:120px 1fr;gap:10px;padding:9px 0;border-top:1px solid rgba(255,255,255,.1)}dt{color:var(--mute);font-size:14px}dd{margin:0}
.cta{max-width:760px;margin:20px auto 0;text-align:center}.mute{color:var(--mute);font-size:13px}
.btn{display:inline-block;min-height:48px;padding:13px 22px;border-radius:999px;text-decoration:none;font-weight:700}
.btn.primary{background:linear-gradient(90deg,#ffb37a,#ff7a6b);color:#2a0d08;box-shadow:0 10px 30px rgba(255,122,107,.35)}
a:focus-visible,button:focus-visible,input:focus-visible,.deck:focus-visible{outline:3px solid #ffd7a8;outline-offset:3px}
@media(min-width:760px){:root{--cw:320px}}
@media(max-width:520px){.dr{grid-template-columns:1fr;gap:2px}.num b{font-size:24px}}
@media(prefers-reduced-motion:reduce){.deck.cf .card,.dot{transition:none}.bar.playing .disc{animation:none}}"""

JS = r"""(function(){
var deck=document.getElementById('deck'),cards=[].slice.call(deck.querySelectorAll('.card')),dots=[].slice.call(document.querySelectorAll('.dot')),
au=document.getElementById('au'),pp=document.getElementById('pp'),bar=document.getElementById('bar'),seek=document.getElementById('seek'),
tm=document.getElementById('tm'),msg=document.getElementById('msg'),cur=0,loaded=0,n=cards.length;
deck.classList.add('cf');deck.parentNode.classList.add('js');
function wide(){return window.innerWidth>=760}
function off(i){var d=((i-cur)%n+n)%n;return d>n/2?d-n:d}
function layout(){cards.forEach(function(c,i){var d=off(i),a=Math.abs(d),w=c.offsetWidth,sx=wide()?.78:.62;
c.style.transform='translateX('+(d*w*sx)+'px) translateZ('+(-a*120)+'px) rotateY('+(d===0?0:(d<0?32:-32))+'deg) scale('+(1-Math.min(a,2)*.12)+')';
c.style.zIndex=20-a;c.classList.toggle('side',a>0);c.classList.toggle('far',a>2);c.setAttribute('aria-hidden',a>0?'true':'false');
c.querySelectorAll('button').forEach(function(b){b.tabIndex=a>0?-1:0})});
dots.forEach(function(d,i){d.setAttribute('aria-current',i===cur?'true':'false')})}
function go(i){cur=((i%n)+n)%n;layout()}
document.getElementById('prev').onclick=function(){go(cur-1)};document.getElementById('next').onclick=function(){go(cur+1)};
dots.forEach(function(d){d.onclick=function(){go(+d.getAttribute('data-go'))}});
deck.addEventListener('keydown',function(ev){if(ev.key==='ArrowLeft'){go(cur-1);ev.preventDefault()}else if(ev.key==='ArrowRight'){go(cur+1);ev.preventDefault()}});
document.addEventListener('keydown',function(ev){var t=ev.target.tagName;if(t==='INPUT'||t==='TEXTAREA'||ev.target===deck)return;
if(ev.key==='ArrowLeft')go(cur-1);else if(ev.key==='ArrowRight')go(cur+1)});
var x0=null,y0=0,moved=false;
deck.addEventListener('pointerdown',function(ev){x0=ev.clientX;y0=ev.clientY;moved=false});
deck.addEventListener('pointermove',function(ev){if(x0!==null&&Math.abs(ev.clientX-x0)>10)moved=true});
deck.addEventListener('pointerup',function(ev){if(x0===null)return;var dx=ev.clientX-x0,dy=ev.clientY-y0;x0=null;
if(Math.abs(dx)>40&&Math.abs(dx)>Math.abs(dy)){go(cur+(dx<0?1:-1))}});
deck.addEventListener('pointercancel',function(){x0=null});
cards.forEach(function(c,i){c.addEventListener('click',function(ev){if(moved){moved=false;return}if(i!==cur){go(i);ev.preventDefault();ev.stopPropagation()}},true)});
window.addEventListener('resize',layout);
function fmt(s){s=Math.max(0,Math.floor(s||0));return Math.floor(s/60)+':'+('0'+s%60).slice(-2)}
function state(){var on=!au.paused&&!au.ended;bar.classList.toggle('playing',on);pp.classList.toggle('on',on);pp.setAttribute('aria-label',on?D.pause:D.play);
cards.forEach(function(c,i){var b=c.querySelector('.play');if(!b)return;var o=on&&i===loaded;b.classList.toggle('on',o);b.querySelector('.pl').textContent=o?D.pause:D.play})}
function load(i){var tr=D.tracks[i];if(!tr||!tr.src)return false;loaded=i;au.src=tr.src;msg.textContent='';
document.getElementById('bt').textContent=tr.t;document.getElementById('bs').textContent=tr.s;
var art=cards[i].querySelector('.art svg');if(art){document.getElementById('disc').innerHTML=art.outerHTML.replace(/id="cv(\d+)"/,'id="cvd$1"').replace(/url\(#cv(\d+)\)/,'url(#cvd$1)')}
seek.value=0;tm.textContent='0:00';return true}
function toggle(i){if(i!==loaded||!au.getAttribute('src')){au.pause();if(!load(i))return}
if(au.paused){var p=au.play();if(p&&p.catch)p.catch(function(){msg.textContent=D.err})}else au.pause()}
cards.forEach(function(c,i){var b=c.querySelector('.play');if(b)b.onclick=function(ev){ev.stopPropagation();toggle(i)}});
pp.onclick=function(){toggle(loaded)};
['play','pause','ended'].forEach(function(k){au.addEventListener(k,state)});
au.addEventListener('error',function(){if(au.getAttribute('src')){msg.textContent=D.err;state()}});
au.addEventListener('timeupdate',function(){if(au.duration){seek.value=Math.round(1000*au.currentTime/au.duration)}tm.textContent=fmt(au.currentTime)});
seek.addEventListener('input',function(){if(au.duration)au.currentTime=au.duration*seek.value/1000});
document.getElementById('share').onclick=function(){if(navigator.share){navigator.share({title:D.title,url:D.url}).catch(function(){});return}
if(navigator.clipboard){navigator.clipboard.writeText(D.url).then(function(){msg.textContent=D.copied},function(){msg.textContent=D.url})}else msg.textContent=D.url};
layout();state()})();"""
