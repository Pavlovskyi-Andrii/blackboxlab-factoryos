"""T-703 prototypes: three glass-style variants of the public profile page /mycast/u/<slug>, for the owner to pick.

Static mock-ups with sample data (the owner's own page as of 2026-11-18). Nothing here is served by the app:
`python docs/prototypes/mycast/profile-glass/build.py` writes a.html, b.html and c.html next to this file.
The style (tokens, glass, cover, coverflow) comes from mycast_share_page, so the chosen variant matches /mycast/e/<token>.
"""
import html
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE.parents[3]))

import mycast_share_page as sp  # noqa: E402

e = html.escape
NAME, DAY, LANG = "Andrey", "2026-11-18", "uk"
IDS = ["tech.ai.llm_launches", "tech.ai.openai", "tech.ai.claude", "tech.ai.workflows", "tech.devops.aws",
       "tech.devops.containers", "science.science_topics.space", "tech.ai.agents", "tech.ai.gemini"]
FOLLOWS = ["@lennysan", "@yongfook", "@arvidkahl", "nutlope", "mckaywrigley", "@rowancheung", "mattshumer_"]
WHEN, VOICE = "Щодня · 07:30 · 15 хв", "Два ведучі · Українська"
TITLE, SUB = f"Подкаст {NAME}", "Персональний подкаст MyCast"
SHARE_ICON = ('<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path d="M12 3v12M7 8l5-5 5 5M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" '
              'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>')


def chips() -> str:
    return "".join(f'<span class="chip" style="--c:{sp.CATS[i.split(".")[0]][0]}">{e(sp.topic_label(i, LANG))}</span>' for i in IDS)


def follows() -> str:
    return "".join(f'<span class="chip fo">{e(f)}</span>' for f in FOLLOWS)


def mix() -> tuple:
    counts: dict = {}
    for i in IDS:
        counts[i.split(".")[0]] = counts.get(i.split(".")[0], 0) + 1
    bar = "".join(f'<i style="width:{100 * v / len(IDS):.1f}%;background:{sp.CATS[c][0]}"></i>' for c, v in counts.items())
    legend = "".join(f'<span style="--c:{sp.CATS[c][0]}">{e(sp.CATS[c][1][LANG])} · {v}</span>' for c, v in counts.items())
    return bar, legend


def head(label: str, extra_css: str) -> str:
    return (f'<!DOCTYPE html><html lang="{LANG}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<meta name="robots" content="noindex"><title>{e(TITLE)} · MyCast — {e(label)}</title><style>{sp.CSS}{EXTRA}{extra_css}</style></head>'
            f'<body><div class="glow" aria-hidden="true"></div><div class="wrap"><header><a class="brand" href="#">'
            f'<img src="/static/mycast-configurator/mycast-icon-64.png" width="28" height="28" alt=""><span>MyCast<b>.pro</b></span></a>'
            f'<nav class="langs"><a href="#" aria-current="true">UK</a><a href="#">RU</a><a href="#">EN</a></nav></header><main>')


EXTRA = """
.chip.fo{--c:#b79cff;background:rgba(183,156,255,.12)}.lab{margin:16px 0 0;font:600 11px/1.2 var(--body);letter-spacing:.12em;text-transform:uppercase;color:var(--warm)}
.chips{margin:8px 0 0}.shareRow{display:flex;flex-wrap:wrap;justify-content:center;gap:8px;margin:14px 0 0}
.sb{display:inline-grid;place-items:center;min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--edge);background:var(--glass);color:var(--ink);
font:600 13px/1 var(--body);text-decoration:none;backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.btn.ghost{background:var(--glass);border:1px solid var(--edge);color:var(--ink);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px)}
.cta .btn{margin:4px}.pl2{display:flex;align-items:center;gap:12px}.pl2 .pp{flex:none}.pl2 .seek{flex:1}
"""

SHARES = "".join(f'<a class="sb" href="#">{n}</a>' for n in ("Facebook", "Telegram", "X", "WhatsApp", "Скопіювати посилання"))
CTA = ('<section class="cta"><a class="btn primary" href="#">Створити такий самий</a><a class="btn ghost" href="#">Створити свій подкаст</a>'
       f'<div class="shareRow">{SHARES}</div></section>')


def about(with_head: bool = True) -> str:
    bar, legend = mix()
    top = (f'<div class="ah"><div class="mini">{sp.cover_svg(IDS, LANG, gid="cva")}</div><div><h2>Про подкаст</h2><p class="mute">{e(TITLE)}</p></div>'
           f'<div class="num"><b>{len(IDS)}</b><span>тем обрано</span></div></div>') if with_head else ""
    return (f'<section class="about glass">{top}<div class="mix">{bar}</div><div class="legend">{legend}</div>'
            f'<p class="lab">Теми</p><div class="chips">{chips()}</div><p class="lab">Стежу</p><div class="chips">{follows()}</div>'
            f'<dl style="margin-top:14px"><div class="dr"><dt>Коли</dt><dd>{e(WHEN)}</dd></div><div class="dr"><dt>Голос</dt><dd>{e(VOICE)}</dd></div></dl></section>')


def variant_a() -> str:
    """Coverflow: the same deck as the episode page — the latest episode in the middle, demo cities on the sides."""
    demos = sp.demo_cards(LANG)
    n = 1 + len(demos)

    def card(i, art, kicker, h, desc, meta, playable):
        play = ('<button class="play" type="button"><span class="pi"></span><span class="pl">Слухати</span></button>' if playable
                else '<span class="soon">Скоро</span>')
        return (f'<article class="card" data-i="{i}"><div class="art">{art}</div><div class="body"><div class="row1"><span class="kick">{e(kicker)}</span>'
                f'<span class="count">{i + 1} / {n}</span></div><h2>{e(h)}</h2><p class="desc">{e(desc)}</p>'
                f'<div class="row2"><span class="meta">{e(meta)}</span>{play}</div></div></article>')

    cards = [card(0, sp.cover_svg(IDS, LANG, gid="cv0"), "Останній випуск", TITLE, SUB, f"{DAY} · 15 хв · Два ведучі", True)]
    for k, d in enumerate(demos, start=1):
        cards.append(card(k, sp.city_svg(d["motif"], d["palette"], d["name"], gid=f"cv{k}"), f'Демо · {d["name"]}', d["title"], d["desc"], d["meta"], False))
    dots = "".join(f'<button type="button" class="dot" data-go="{i}"></button>' for i in range(n))
    js = sp.JS
    return (head("A · Карусель", "") + f'<section class="stage"><div class="deck" id="deck" tabindex="0">{"".join(cards)}</div>'
            f'<div class="ctrl"><button class="nav" type="button" id="prev">‹</button><div class="dots">{dots}</div><button class="nav" type="button" id="next">›</button></div></section>'
            f'<div class="bar glass" id="bar"><div class="disc" id="disc">{sp.cover_svg(IDS, LANG, gid="cvb")}</div>'
            f'<div class="bt"><b id="bt">MyCast · {DAY}</b><span id="bs">{e(TITLE)}</span><div class="seek"><input type="range" id="seek" min="0" max="1000" value="0"><span id="tm">0:00</span></div></div>'
            f'<button class="ib" type="button" id="share">{SHARE_ICON}</button><button class="pp" type="button" id="pp"><span class="pi"></span></button></div>'
            f'<p class="mute msg" id="msg"></p>{about()}{CTA}</main></div><audio id="au" preload="none"></audio>'
            f'<script>var D={{"tracks":[{{"t":"MyCast · {DAY}","s":"{TITLE}","src":""}}],"url":"#","title":"","copied":"","play":"Слухати","pause":"Пауза","err":"","soon":"Скоро"}};{js}</script></body></html>')


CSS_B = """
.heroB{margin:14px auto 0;max-width:560px;padding:14px;border-radius:34px;text-align:center}
.heroB .cover{border-radius:24px;overflow:hidden}.heroB .cover svg{display:block;width:100%}
.heroB h1{margin:16px 0 2px;font:600 30px/1.15 var(--display)}.heroB .sub{margin:0;color:var(--mute);font-size:14px}
.pills{display:flex;flex-wrap:wrap;justify-content:center;gap:6px;margin:12px 0 4px}.pill{padding:6px 12px;border-radius:999px;background:rgba(255,255,255,.12);font:600 12px/1 var(--body);color:var(--mute)}
.playB{display:flex;align-items:center;gap:12px;margin:14px 0 0;padding:10px 14px 10px 10px;border-radius:999px;background:rgba(20,15,36,.45);border:1px solid var(--edge);text-align:left}
.playB .pp{width:56px;height:56px}.playB .bt b{font-size:14px}
"""


def variant_b() -> str:
    """Cover: one big glass hero with the DNA cover, the name and a large player, then the "About" panel."""
    return (head("B · Обкладинка", CSS_B) + f'<section class="heroB glass"><div class="cover">{sp.cover_svg(IDS, LANG, gid="cv0")}</div>'
            f'<h1>{e(TITLE)}</h1><p class="sub">{e(SUB)}</p><div class="pills"><span class="pill">{len(IDS)} тем</span><span class="pill">Щодня · 07:30</span>'
            f'<span class="pill">15 хв</span><span class="pill">Два ведучі</span></div>'
            f'<div class="playB"><button class="pp" type="button"><span class="pi"></span></button><div class="bt"><b>Останній випуск</b><span>{DAY} · 15 хв</span>'
            f'<div class="seek"><input type="range" min="0" max="1000" value="0"><span>0:00</span></div></div><button class="ib" type="button">{SHARE_ICON}</button></div></section>'
            f'{about(with_head=False)}{CTA}</main></div></body></html>')


CSS_C = """
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:14px auto 0;max-width:760px}.tile{padding:16px;border-radius:26px;min-width:0}.w2{grid-column:1/-1}
.who{display:flex;align-items:center;gap:14px}.who .disc{width:76px;height:76px}.who h1{margin:0;font:600 26px/1.15 var(--display)}.who p{margin:2px 0 0;color:var(--mute);font-size:13px}
.big{display:block;font:600 34px/1 var(--display)}.tile .lab{margin:0 0 8px}.tile small{color:var(--mute);font-size:12.5px}
.pl2 .pp{width:56px;height:56px}.tile .chips{margin:0}
.dock{position:sticky;bottom:12px;z-index:50;display:flex;gap:8px;align-items:center;max-width:560px;margin:14px auto 0;padding:8px;border-radius:999px}
.dock .btn{flex:1;text-align:center;min-height:44px;padding:12px 14px;font-size:14px}.dock .ib{flex:none}
"""


def variant_c() -> str:
    """Tiles: a bento grid of glass tiles and a sticky glass dock with the main action."""
    bar, legend = mix()
    return (head("C · Плитки", CSS_C) + '<div class="grid">'
            f'<section class="tile glass w2 who"><div class="disc">{sp.cover_svg(IDS, LANG, gid="cv0")}</div><div><h1>{e(TITLE)}</h1><p>{e(SUB)}</p></div></section>'
            f'<section class="tile glass w2"><p class="lab">Останній випуск · {DAY}</p><div class="pl2"><button class="pp" type="button"><span class="pi"></span></button>'
            f'<div class="seek"><input type="range" min="0" max="1000" value="0"><span>0:00</span></div></div></section>'
            f'<section class="tile glass"><p class="lab">Теми</p><b class="big">{len(IDS)}</b><small>тем обрано</small><div class="mix">{bar}</div></section>'
            f'<section class="tile glass"><p class="lab">Коли</p><b class="big">07:30</b><small>Щодня · 15 хв</small></section>'
            f'<section class="tile glass w2"><p class="lab">Теми</p><div class="chips">{chips()}</div><div class="legend" style="margin-top:10px">{legend}</div></section>'
            f'<section class="tile glass w2"><p class="lab">Стежу</p><div class="chips">{follows()}</div></section>'
            f'<section class="tile glass"><p class="lab">Голос</p><b style="font:600 18px/1.2 var(--display)">Два ведучі</b><br><small>Українська</small></section>'
            f'<section class="tile glass"><p class="lab">Поділитися</p><div class="chips"><span class="chip fo">Facebook</span><span class="chip fo">Telegram</span>'
            f'<span class="chip fo">X</span><span class="chip fo">WhatsApp</span></div></section></div>'
            f'<div class="dock glass"><a class="btn primary" href="#">Створити такий самий</a><button class="ib" type="button">{SHARE_ICON}</button></div>'
            '<section class="cta"><a class="btn ghost" href="#">Створити свій подкаст</a></section></main></div></body></html>')


if __name__ == "__main__":
    for name, fn in (("a", variant_a), ("b", variant_b), ("c", variant_c)):
        (HERE / f"{name}.html").write_text(fn(), encoding="utf-8")
        print("wrote", name + ".html")
