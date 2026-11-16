"""Owner 2026-11-14: one "Learning" place in FactoryOS with three shelves.

  mine        — материалы, которые владелец проходил сам (метод бренд-стратегии, настройки Google, браузер-агент)
  explainers  — обучалки по системе: HTML-ролики и интерактивные прототипы
  guide       — «как это работает»: гайд по проекту FactoryOS и справочники

Everything is read from files already in the repo (or, for the 7-step method, from brand_strategy.STEPS), so the shelf
never drifts from the source. Pages sit behind the normal dashboard login. HTML prototypes are served with a CSP
sandbox (opaque origin: they can animate but cannot read FactoryOS cookies or call its API). Markdown is rendered by a
tiny escape-first renderer — no raw HTML from documents ever reaches the browser.
"""
from __future__ import annotations

import html
import re
from pathlib import Path
from typing import Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

SECTIONS = ("mine", "explainers", "guide")
LANGS = ("ru", "uk", "en")
DEFAULT_LANG = "ru"

CATALOG = (
    # --- Моё обучение -------------------------------------------------------------------------------------------
    {"id": "brand-method", "section": "mine", "kind": "steps", "path": "brand_strategy.py", "lang": "ru",
     "title": {"ru": "Метод бренд-стратегии: 7 шагов", "uk": "Метод бренд-стратегії: 7 кроків", "en": "Brand strategy method: 7 steps"},
     "desc": {"ru": "Разбор карусели из 7 промтов и адаптация Grok: цель → распаковка → аудитория → тон → столпы → воронка → CTA. Те же промты использует раздел «Бренд-стратегия».",
              "uk": "Розбір каруселі з 7 промтів і адаптація Grok: ціль → розпаковка → аудиторія → тон → стовпи → воронка → CTA. Ті самі промти використовує розділ «Бренд-стратегія».",
              "en": "The 7-prompt carousel and its Grok adaptation: goal → unpacking → audience → tone → pillars → funnel → CTA. The Brand strategy card uses the same prompts."}},
    {"id": "google-calendar", "section": "mine", "kind": "md", "path": "docs/guides/google-calendar-setup.md", "lang": "en",
     "title": {"ru": "Google Календарь и OAuth: как мы настраивали", "uk": "Google Календар і OAuth: як ми налаштовували", "en": "Google Calendar & OAuth setup"},
     "desc": {"ru": "Пошагово: проект в Google Cloud, экран согласия, тестовые пользователи, секрет, проверка.",
              "uk": "Покроково: проєкт у Google Cloud, екран згоди, тестові користувачі, секрет, перевірка.",
              "en": "Step by step: Google Cloud project, consent screen, test users, secret, verification."}},
    {"id": "browser-agent", "section": "mine", "kind": "md", "path": "docs/guides/browser-agent.md", "lang": "en",
     "title": {"ru": "Браузерный агент и сохранённая сессия", "uk": "Браузерний агент і збережена сесія", "en": "Browser agent & saved session"},
     "desc": {"ru": "Как агент читает страницы, зачем экспорт куки из Cookie-Editor и что ему запрещено.",
              "uk": "Як агент читає сторінки, навіщо експорт кукі з Cookie-Editor і що йому заборонено.",
              "en": "How the agent reads pages, why the Cookie-Editor export, and what it may not do."}},
    {"id": "oauth", "section": "mine", "kind": "md", "path": "docs/guide/oauth.md", "lang": "ru",
     "title": {"ru": "OAuth-подключения", "uk": "OAuth-підключення", "en": "OAuth connections"},
     "desc": {"ru": "Какие сервисы подключаются через OAuth и где хранятся токены.", "uk": "Які сервіси підключаються через OAuth і де зберігаються токени.",
              "en": "Which services connect via OAuth and where tokens live."}},
    # --- Обучалки по системе --------------------------------------------------------------------------------------
    {"id": "motion-explainer", "section": "explainers", "kind": "html", "path": "docs/prototypes/factoryos-explainer/claude-motion/index.html", "lang": "ru",
     "title": {"ru": "Ролик FactoryOS · 75 секунд (Claude)", "uk": "Ролик FactoryOS · 75 секунд (Claude)", "en": "FactoryOS film · 75 seconds (Claude)"},
     "desc": {"ru": "Камера следует за одной задачей: дебаты → ТЗ → сборка → Relay → ветки A/B → промо с одобрением → обучение → вся система. #353.",
              "uk": "Камера стежить за однією задачею: дебати → ТЗ → збірка → Relay → гілки A/B → промо зі схваленням → навчання → уся система. #353.",
              "en": "The camera follows one task: debate → spec → build → Relay → A/B branches → approved promo → learning → whole system. #353."}},
    {"id": "promo-explainer", "section": "explainers", "kind": "html", "path": "docs/prototypes/factoryos-explainer/chatgpt-promo/index.html", "lang": "ru",
     "title": {"ru": "FactoryOS V2: интерактивный обзор (ChatGPT)", "uk": "FactoryOS V2: інтерактивний огляд (ChatGPT)", "en": "FactoryOS V2 interactive overview (ChatGPT)"},
     "desc": {"ru": "Страница-обзор: отделы, передачи работы, A/B-ветки. Вчерашний HTML из PR #352.",
              "uk": "Сторінка-огляд: відділи, передачі роботи, A/B-гілки. Вчорашній HTML з PR #352.",
              "en": "Overview page: departments, handoffs, A/B branches. Yesterday's HTML from PR #352."}},
    {"id": "ab-branches", "section": "explainers", "kind": "html", "path": "docs/prototypes/mvp-builder/ab-branches-preview.html", "lang": "ru",
     "title": {"ru": "MVP Builder: ветки A и B (прототип)", "uk": "MVP Builder: гілки A і B (прототип)", "en": "MVP Builder: branches A and B (prototype)"},
     "desc": {"ru": "Как идея раздваивается на две аудитории со своими лендингами и промо. Вчерашний HTML из PR #347; это прототип, A/B Tester ещё не построен.",
              "uk": "Як ідея роздвоюється на дві аудиторії зі своїми лендингами та промо. Вчорашній HTML з PR #347; це прототип, A/B Tester ще не побудовано.",
              "en": "How one idea splits into two audiences with their own landings and promo. Yesterday's HTML from PR #347; a prototype — A/B Tester is not built yet."}},
    # --- Как это работает --------------------------------------------------------------------------------------------
    {"id": "how-it-works", "section": "guide", "kind": "md", "path": "docs/guide/how-factoryos-works.md", "lang": "ru",
     "title": {"ru": "Как устроен FactoryOS — гайд по проекту", "uk": "Як влаштований FactoryOS — гайд по проєкту", "en": "How FactoryOS works — project guide"},
     "desc": {"ru": "Карта системы на одной странице: кто что делает, где что смотреть, какие правила нельзя обойти.",
              "uk": "Карта системи на одній сторінці: хто що робить, де що дивитися, які правила не можна обійти.",
              "en": "The system on one page: who does what, where to look, which rules cannot be bypassed."}},
    {"id": "telegram", "section": "guide", "kind": "md", "path": "docs/guide/telegram-commands.md", "lang": "ru",
     "title": {"ru": "Команды Telegram-бота", "uk": "Команди Telegram-бота", "en": "Telegram bot commands"},
     "desc": {"ru": "Как ставить задачи агентам из Telegram и что значит каждый статус.", "uk": "Як ставити задачі агентам з Telegram і що означає кожен статус.",
              "en": "How to give agents tasks from Telegram and what each status means."}},
    {"id": "relay", "section": "guide", "kind": "md", "path": "docs/RELAY.md", "lang": "en",
     "title": {"ru": "Relay: передача задач между агентами", "uk": "Relay: передача задач між агентами", "en": "Relay: handing work between agents"},
     "desc": {"ru": "Тикеты, claim, события, почему «назначено» ещё не значит «выполняется».", "uk": "Тікети, claim, події, чому «призначено» ще не означає «виконується».",
              "en": "Tickets, claims, events — why assigned is not the same as running."}},
    {"id": "team-tasks", "section": "guide", "kind": "md", "path": "docs/guide/team-tasks.md", "lang": "ru",
     "title": {"ru": "Задачи команды", "uk": "Задачі команди", "en": "Team tasks"},
     "desc": {"ru": "Страница задач команды: кто владеет задачей и как она движется.", "uk": "Сторінка задач команди: хто володіє задачею і як вона рухається.",
              "en": "The team tasks page: who owns a task and how it moves."}},
    {"id": "mycast", "section": "guide", "kind": "md", "path": "docs/guide/mycast.md", "lang": "ru",
     "title": {"ru": "MyCast для владельца", "uk": "MyCast для власника", "en": "MyCast for the owner"},
     "desc": {"ru": "Когда приходит выпуск, голоса, доставка, лимиты.", "uk": "Коли приходить випуск, голоси, доставка, ліміти.", "en": "When the episode arrives, voices, delivery, limits."}},
    {"id": "mvp-factory", "section": "guide", "kind": "md", "path": "docs/MVP_FACTORY_SPEC.md", "lang": "en",
     "title": {"ru": "MVP Factory: стадии и роли", "uk": "MVP Factory: стадії та ролі", "en": "MVP Factory: stages and roles"},
     "desc": {"ru": "Контракт MVP-конвейера: стадии, кто их двигает, какие доказательства нужны.", "uk": "Контракт MVP-конвеєра: стадії, хто їх рухає, які докази потрібні.",
              "en": "The MVP pipeline contract: stages, who moves them, what evidence is required."}},
    {"id": "surfer", "section": "guide", "kind": "md", "lang": "ru", "path": "docs/guide/surfer.md",
     "title": {"ru": "Сёрфер: поиск и чтение сайтов для агентов", "uk": "Серфер: пошук і читання сайтів для агентів",
               "en": "Surfer: web search and page reading for agents"},
     "desc": {"ru": "Что умеют web_search, web_read и web_task, кто ими пользуется, какие лимиты и чего Сёрфер не делает.",
              "uk": "Що вміють web_search, web_read і web_task, хто ними користується, які ліміти й чого Серфер не робить.",
              "en": "What web_search, web_read and web_task do, who uses them, the limits, and what the Surfer refuses to do."}},
    {"id": "agent-workspace", "section": "guide", "kind": "md", "lang": "ru", "path": "docs/guide/agent-workspace.md",
     "title": {"ru": "Общее пространство Claude ↔ ChatGPT", "uk": "Спільний простір Claude ↔ ChatGPT", "en": "Shared workspace Claude ↔ ChatGPT"},
     "desc": {"ru": "Ветки, сообщения и передача задач через Relay: токены агентов, путь create → claim → result → review.",
              "uk": "Гілки, повідомлення й передача задач через Relay: токени агентів, шлях create → claim → result → review.",
              "en": "Threads, messages and task handoffs through Relay: per-agent tokens and the create → claim → result → review path."}},
    {"id": "gemini-coder", "section": "guide", "kind": "md", "path": "docs/guide/gemini-coder.md", "lang": "ru",
     "title": {"ru": "Gemini-кодер", "uk": "Gemini-кодер", "en": "Gemini coder"},
     "desc": {"ru": "Что делает бесплатный Gemini-агент и где его границы.", "uk": "Що робить безкоштовний Gemini-агент і де його межі.", "en": "What the free Gemini agent does and where its limits are."}},
)
BY_ID = {item["id"]: item for item in CATALOG}

# T-667: a Markdown guide may have translations next to its original, named `<stem>.<lang>.md`
# (docs/guide/mycast.md → docs/guide/mycast.uk.md). The path is derived only from the catalog entry and a language
# from LANGS — never from request text — so `?lang=` cannot reach any other file.
NO_TRANSLATION = {
    "ru": {"ru": "", "uk": "Этот материал пока есть только на украинском.", "en": "Этот материал пока есть только на английском."},
    "uk": {"ru": "Цей матеріал поки є лише російською.", "uk": "", "en": "Цей матеріал поки є лише англійською."},
    "en": {"ru": "This guide is only available in Russian so far.", "uk": "This guide is only available in Ukrainian so far.", "en": ""},
}
STEPS_INTRO = {
    "ru": ("Метод бренд-стратегии: 7 шагов",
           "Источник: карусель «7 промтов» (Владимир Без) и адаптация Grok под FactoryOS. Каждый шаг — отдельный промт; "
           "одобренные шаги собираются в Master Brief, который получают агенты контента. Работать с методом можно в карточке "
           "<b>Бренд-стратегия</b> на главной панели."),
    "uk": ("Метод бренд-стратегії: 7 кроків",
           "Джерело: карусель «7 промтів» (Володимир Без) і адаптація Grok під FactoryOS. Кожен крок — окремий промт; "
           "схвалені кроки збираються в Master Brief, який отримують агенти контенту. Працювати з методом можна в картці "
           "<b>Бренд-стратегія</b> на головній панелі."),
    "en": ("Brand strategy method: 7 steps",
           "Source: the \u201c7 prompts\u201d carousel (Volodymyr Bez) and its Grok adaptation for FactoryOS. Each step is one prompt; "
           "approved steps are assembled into the Master Brief that the content agents receive. Work with the method in the "
           "<b>Brand strategy</b> card on the main dashboard."),
}


def normalize_lang(lang: Optional[str]) -> str:
    lang = (lang or "").strip().lower()[:5]
    return lang if lang in LANGS else DEFAULT_LANG


def doc_path(item: dict, lang: str) -> str:
    """Repo-relative path of `item` in `lang` (the original for its own language). `lang` must be in LANGS."""
    if lang not in LANGS:
        raise ValueError(lang)
    if lang == item["lang"] or item["kind"] != "md":
        return item["path"]
    p = Path(item["path"])
    return p.with_name(f"{p.stem}.{lang}{p.suffix}").as_posix()


def available_langs(base: Path, item: dict) -> list:
    if item["kind"] == "steps":
        return list(LANGS)
    if item["kind"] != "md":
        return [item["lang"]]
    return [lang for lang in LANGS if (base / doc_path(item, lang)).is_file()]


def resolve_doc(base: Path, item: dict, lang: str) -> tuple:
    """(repo-relative path, language actually served): the translation if present, otherwise the original."""
    lang = normalize_lang(lang)
    path = doc_path(item, lang)
    if (base / path).is_file():
        return path, lang
    return item["path"], item["lang"]

# Prototypes may animate, but in an opaque origin with no network: no cookies, no API, no external fetches.
SANDBOX_CSP = ("sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
               "img-src data: blob:; font-src data:; media-src data: blob:")
PAGE_CSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; base-uri 'none'; form-action 'none'"

_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def _inline(text: str) -> str:
    out = html.escape(text, quote=True)
    out = _CODE.sub(lambda m: f"<code>{m.group(1)}</code>", out)
    out = _BOLD.sub(lambda m: f"<b>{m.group(1)}</b>", out)
    out = _LINK.sub(lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener noreferrer">{m.group(1)}</a>', out)
    return out


def render_markdown(src: str) -> str:
    """Escape-first Markdown subset: headings, paragraphs, lists, quotes, fenced code, tables, `code`, **bold**, links."""
    out, para, lst, table = [], [], None, []
    lines = src.replace("\r\n", "\n").split("\n")

    def flush():
        nonlocal para, lst, table
        if para:
            out.append("<p>" + " ".join(_inline(p) for p in para) + "</p>"); para = []
        if lst:
            out.append(f"<{lst[0]}>" + "".join(f"<li>{_inline(i)}</li>" for i in lst[1]) + f"</{lst[0]}>"); lst = None
        if table:
            rows = [r for r in table if not re.fullmatch(r"\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?", r.strip())]
            cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
            if cells:
                head = "".join(f"<th>{_inline(c)}</th>" for c in cells[0])
                body = "".join("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>" for r in cells[1:])
                out.append(f'<div class="tbl"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            table = []

    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("```"):
            flush(); code = []; i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i]); i += 1
            out.append("<pre><code>" + html.escape("\n".join(code)) + "</code></pre>"); i += 1; continue
        m = re.match(r"^(#{1,4})\s+(.*)$", line)
        if m:
            flush(); n = len(m.group(1)); out.append(f"<h{n}>{_inline(m.group(2))}</h{n}>")
        elif re.match(r"^\s*(---|\*\*\*)\s*$", line):
            flush(); out.append("<hr>")
        elif line.lstrip().startswith("|"):
            if para or lst:
                flush()
            table.append(line)
        elif re.match(r"^\s*>\s?", line):
            flush(); out.append("<blockquote>" + _inline(re.sub(r"^\s*>\s?", "", line)) + "</blockquote>")
        elif re.match(r"^\s*([-*]|\d+\.)\s+", line):
            kind = "ol" if re.match(r"^\s*\d+\.", line) else "ul"
            if table or para or (lst and lst[0] != kind):
                flush()
            lst = lst or (kind, [])
            lst[1].append(re.sub(r"^\s*([-*]|\d+\.)\s+", "", line))
        elif not line.strip():
            flush()
        elif lst and line.startswith("  "):
            lst[1][-1] += " " + line.strip()
        else:
            if table or lst:
                flush()
            para.append(line.strip())
        i += 1
    flush()
    return "\n".join(out)


def render_steps(steps, lang: str = DEFAULT_LANG) -> str:
    lang = normalize_lang(lang)
    head, intro = STEPS_INTRO[lang]
    parts = [f"<h1>{html.escape(head)}</h1>", f"<p>{intro}</p>"]
    for s in steps:
        title = s["title"].get(lang) or s["title"].get("ru") or s["title"].get("en", "")
        parts.append(f"<h2>{int(s['n'])}. {html.escape(title)}</h2>")
        parts.append("<pre class=\"prompt\">" + html.escape(s.get("prompt", "")) + "</pre>")
    return "\n".join(parts)


def _page(title: str, body: str, lang: str = DEFAULT_LANG) -> str:
    return f"""<!doctype html><html lang="{normalize_lang(lang)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title><style>
:root{{color-scheme:dark}}body{{margin:0;background:#070b16;color:#e9effc;font:16px/1.6 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif}}
main{{max-width:860px;margin:0 auto;padding:28px 18px 60px}}h1{{font-size:28px;line-height:1.2;letter-spacing:-.02em}}h2{{font-size:21px;margin-top:30px}}h3{{font-size:17px}}
a{{color:#7fd8ff}}code{{background:#131c33;border-radius:5px;padding:1px 5px;font:13px ui-monospace,Menlo,monospace}}
pre{{background:#0d1426;border:1px solid #22314a;border-radius:10px;padding:12px;overflow:auto;white-space:pre-wrap}}pre code{{background:none;padding:0}}
blockquote{{margin:12px 0;padding:8px 14px;border-left:3px solid #5ee7ff;background:#0d1426;color:#c9d5ea}}
.tbl{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}th,td{{border:1px solid #22314a;padding:6px 8px;text-align:left;vertical-align:top}}th{{background:#111a2e}}
hr{{border:0;border-top:1px solid #22314a;margin:24px 0}}li{{margin:3px 0}}
.langnote{{margin:0 0 18px;padding:8px 12px;border:1px solid #6b5520;border-radius:10px;background:#1d1708;color:#ffd894;font-size:14px}}
</style></head><body><main>{body}</main></body></html>"""


def install_learn_routes(app, *, base: Path, steps_source: Callable[[], tuple],
                         identity: Optional[Callable[[Request], dict]] = None) -> None:
    def _item(item_id: str) -> dict:
        item = BY_ID.get(item_id)
        if not item:
            raise HTTPException(404, "unknown item")
        return item

    def _exists(item: dict) -> bool:
        return item["kind"] == "steps" or (base / item["path"]).is_file()

    @app.get("/api/learn")
    def learn_catalog():
        return {"sections": list(SECTIONS),
                "items": [{"id": i["id"], "section": i["section"], "kind": i["kind"], "title": i["title"], "desc": i["desc"],
                           "source": i["path"], "lang": i["lang"], "langs": available_langs(base, i),
                           "available": _exists(i)} for i in CATALOG]}

    @app.get("/learn", response_class=HTMLResponse)
    def learn_page():
        return FileResponse(base / "static" / "learn" / "index.html", media_type="text/html",
                            headers={"Cache-Control": "no-store"})

    @app.get("/learn/view/{item_id}")
    def learn_view(item_id: str, lang: str = DEFAULT_LANG):
        item = _item(item_id)
        if not _exists(item):
            raise HTTPException(404, "not in this build yet")
        if item["kind"] == "html":
            return FileResponse(base / item["path"], media_type="text/html",
                                headers={"Content-Security-Policy": SANDBOX_CSP, "X-Content-Type-Options": "nosniff",
                                         "Cache-Control": "no-store"})
        want = normalize_lang(lang)
        if item["kind"] == "steps":
            body, served = render_steps(steps_source(), want), want
        else:
            path, served = resolve_doc(base, item, want)
            body = render_markdown((base / path).read_text(encoding="utf-8"))
            note = NO_TRANSLATION[want][served]
            if note:   # the guide's real language stays visible when there is no translation yet
                body = f'<p class="langnote" data-served-lang="{served}">{html.escape(note)}</p>\n' + body
        return HTMLResponse(_page(item["title"][want], body, served),
                            headers={"Content-Security-Policy": PAGE_CSP, "X-Content-Type-Options": "nosniff",
                                     "Content-Language": served})
