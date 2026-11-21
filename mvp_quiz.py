"""T-634 "Help us improve" quiz + analyst agent (#270, owner 2026-11-16: no human in the feedback loop).

A short, optional quiz at the bottom of an MVP page (first: MyCast; T-636: MyBrief and Decision Memory, each with its
own questions and themes in `QUIZZES`). Answers go into the T-630 Product Evolution
ledger as consented, in-product feedback; an analyst pass after each answer looks for a theme that crossed the owner's
threshold and, when one did, writes a V2 proposal and hands it to Builder through one Relay ticket (standing rule).

Rules
- The quiz is optional and asks for consent; without `consent: true` nothing is stored.
- One answer per participant per quiz version: a signed-in listener counts once; an anonymous visitor is keyed by a
  per-day hash of the client address (never stored in clear). Per-client and global daily caps.
- Only signed-in listeners who actually used the product count toward a theme (`q_use` != "not_yet"): an anonymous
  identity rotates daily and cannot be a unique person for the threshold. Anonymous answers are kept as feedback.
- Threshold (owner default): at least MIN_PEOPLE unique people support the theme, at least MIN_SHARE of the version's
  sample, and contrary answers below half the support. Synthetic data never counts and never reaches Relay.
- Auto hand-off is on by default and has a kill switch (FACTORY_QUIZ_AUTO_V2=0): then proposals wait for the owner.
  Nothing here merges, deploys or publishes; a hand-off is a Relay task, the code still goes through PR + CI.
- Rewards and e-mails are recorded but held while their flags are off (FACTORY_QUIZ_REWARDS, FACTORY_QUIZ_MAIL):
  the gift terms and the mail provider are the owner's call (T-634-H). No gift is promised on the page while off.
- An e-mail is kept only with a separate contact consent, and the owner can delete a submission (with its e-mail).
- T-636: a product without its own accounts (`identity: workspace`) counts only people signed in to FactoryOS (a hashed
  workspace identity) and never grants or promises a gift (`rewards: False`); a theme belongs to one product's quiz.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import JSONResponse

from mvp_evolution import EvolutionError, EvolutionStore, clean_text

LANGS = ("uk", "ru", "en")
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,180}\.[A-Za-z]{2,24}$")
PER_CLIENT_DAILY = 3
GLOBAL_DAILY = 500
MIN_ANSWERS = 3
FREE_TEXT_MAX = 500
REWARD_DAYS = 7
POLICY = "quiz-threshold"


def _t(uk: str, ru: str, en: str) -> dict[str, str]:
    return {"uk": uk, "ru": ru, "en": en}


# Themes the quiz can surface, with the V2 change the analyst proposes once a theme crosses the threshold.
THEMES: dict[str, dict[str, Any]] = {
    "shorter-episodes": {"title": _t("Коротші епізоди (5 хв)", "Короче эпизоды (5 мин)", "Shorter 5-minute episodes"),
                         "change": "Offer a 5-minute episode length in the configurator and generate to it",
                         "test": "A listener picks 5 minutes and the next episode is 4–6 minutes long"},
    "longer-episodes": {"title": _t("Довші епізоди (20+ хв)", "Длиннее эпизоды (20+ мин)", "Longer 20+ minute deep dives"),
                        "change": "Offer a 20-minute deep-dive length",
                        "test": "A listener picks 20 minutes and the next episode is 18–24 minutes long"},
    "text-transcript": {"title": _t("Текстова версія епізоду", "Текстовая версия эпизода", "A text transcript of each episode"),
                        "change": "Show a transcript with source links next to each episode in My podcasts",
                        "test": "Every ready episode in the library has a readable transcript with its source links"},
    "voice-choice": {"title": _t("Вибір голосів ведучих", "Выбор голосов ведущих", "Choosing the hosts' voices"),
                     "change": "Let the listener choose between at least three voice pairs",
                     "test": "A listener switches the voice pair and the next episode uses it"},
    "ask-follow-up": {"title": _t("Поставити питання після епізоду", "Задать вопрос после эпизода", "Asking a follow-up question"),
                      "change": "Add an 'ask about this episode' box that answers from the episode's sources",
                      "test": "A question about an episode gets an answer citing that episode's sources"},
    "offline-download": {"title": _t("Завантаження для офлайну", "Скачивание для офлайна", "Download for offline listening"),
                         "change": "Add a download button for ready episodes",
                         "test": "A ready episode downloads as an audio file that plays offline"},
    "shorter-setup": {"title": _t("Швидше налаштування", "Быстрее настройка", "A faster setup"),
                      "change": "Cut the configurator to a 3-step quick start with defaults",
                      "test": "A new listener gets to 'ready' in 3 steps or fewer"},
    "better-voices": {"title": _t("Природніші голоси", "Более естественные голоса", "More natural voices"),
                      "change": "Switch the default voices to the most natural available option and A/B them",
                      "test": "Listeners rate the new default voice higher than the old one in a blind pair"},
    "better-topic-match": {"title": _t("Точніші теми", "Более точные темы", "Topics that match better"),
                           "change": "Let the listener mark an item 'off topic' and use it to filter later episodes",
                           "test": "Items marked off topic stop appearing in the next three episodes"},
    "email-delivery": {"title": _t("Епізод на пошту", "Эпизод на почту", "Episodes by e-mail"),
                       "change": "Offer e-mail delivery of the daily episode next to Telegram",
                       "test": "A listener who chose e-mail receives the next episode by e-mail"},
    "podcast-app-feed": {"title": _t("Стрічка для подкаст-застосунку", "Лента для подкаст-приложения", "A private feed for podcast apps"),
                         "change": "Give each listener a private RSS feed for Apple Podcasts / Pocket Casts",
                         "test": "The private feed URL plays the latest episode in a podcast app"},
    # T-636 MyBrief for a profession (mybrief-pro)
    "shorter-brief": {"title": _t("Коротший брифінг (3 пункти)", "Короче брифинг (3 пункта)", "A shorter 3-item briefing"),
                      "change": "Offer a 3-item 'two-minute' briefing next to the full one",
                      "test": "A reader picks the short briefing and gets exactly 3 items, each with its source link"},
    "deeper-brief": {"title": _t("Детальніший розбір кожного пункту", "Подробнее разбор каждого пункта", "More detail on each item"),
                     "change": "Add an expandable 'more detail' block to each briefing item, written from the same source",
                     "test": "Every item opens a longer explanation that cites the item's own source"},
    "custom-topics": {"title": _t("Свої професія і теми", "Свои профессия и темы", "My own profession and topics"),
                      "change": "Let the reader type a profession and topics that are not in the catalog and record the request",
                      "test": "A reader enters a profession outside the catalog and it is saved as a request the owner can see"},
    "fresh-daily-brief": {"title": _t("Свіжий брифінг щодня", "Свежий брифинг каждый день", "A fresh briefing every day"),
                          "change": "Refresh the briefing from dated sources on a schedule instead of a fixed demo set",
                          "test": "The briefing shows items dated within the last 48 hours, each with a dated https source"},
    "job-relevance-note": {"title": _t("Пояснення «чому це важливо для моєї роботи»", "Пояснение «почему это важно для моей работы»", "A 'why it matters for my job' note"),
                           "change": "Add one line per item explaining why it matters for the chosen profession",
                           "test": "Every item of a briefing carries a profession-specific 'why it matters' line"},
    "save-share-items": {"title": _t("Зберегти пункт або поділитися ним", "Сохранить пункт или поделиться им", "Saving and sharing an item"),
                         "change": "Add 'copy link' and 'save for later' to each briefing item",
                         "test": "A reader copies a link to one item and the link opens that item with its source"},
    "better-brief-match": {"title": _t("Точніше під мою професію", "Точнее под мою профессию", "A better fit for my profession"),
                           "change": "Let the reader mark an item 'not for my job' and use it to reorder the next briefing",
                           "test": "An item marked 'not for my job' is not shown first in the reader's next briefing"},
    "more-sources": {"title": _t("Більше джерел до кожного пункту", "Больше источников к каждому пункту", "More sources per item"),
                     "change": "Show at least two independent dated sources for an item when they exist",
                     "test": "An item with two known sources lists both, and an item with one says it has a single source"},
    "scannable-layout": {"title": _t("Брифінг, який легко переглянути", "Брифинг, который легко просмотреть", "A briefing that is easier to scan"),
                         "change": "Put a one-line headline list above the full briefing",
                         "test": "The briefing starts with a headline list whose entries jump to the full items"},
    "brief-by-email": {"title": _t("Брифінг на пошту", "Брифинг на почту", "The briefing by e-mail"),
                       "change": "Offer a weekly e-mail delivery of the briefing with an unsubscribe link",
                       "test": "A reader who opted in receives the next briefing by e-mail and can unsubscribe in one click"},
    "brief-in-telegram": {"title": _t("Брифінг у Telegram", "Брифинг в Telegram", "The briefing in Telegram"),
                          "change": "Offer delivery of the briefing to the reader's Telegram",
                          "test": "A reader who linked Telegram receives the next briefing there"},
    # T-636 AI Decision Memory (decision-memory)
    "auto-capture": {"title": _t("Автоматичний збір рішень", "Автоматический сбор решений", "Decisions captured automatically"),
                     "change": "Suggest new decisions from DECISIONS.md changes for the owner to confirm instead of typing them",
                     "test": "A new DECISIONS.md entry appears as a suggested decision that is saved only after the owner confirms"},
    "ask-the-memory": {"title": _t("Запитати пам’ять своїми словами", "Спросить память своими словами", "Asking the memory a question"),
                       "change": "Add a question box that answers from recorded decisions and links to them",
                       "test": "A question about a past choice returns the matching decisions with their rationale and sources"},
    "link-to-work": {"title": _t("Зв’язок рішення із задачами та PR", "Связь решения с задачами и PR", "Linking a decision to tasks and PRs"),
                     "change": "Let a decision list the roadmap tasks and pull requests that implement it",
                     "test": "A decision shows its linked task ids and PR links, and each link opens"},
    "export-decisions": {"title": _t("Експорт рішень", "Экспорт решений", "Exporting decisions"),
                         "change": "Add a Markdown export of one decision or the filtered list",
                         "test": "The export of a decision contains its rationale, responsible person, sources and reviews"},
    "faster-entry": {"title": _t("Швидше записати рішення", "Быстрее записать решение", "Recording a decision faster"),
                     "change": "Add a two-field quick entry (decision + why) and make the other fields optional later",
                     "test": "A decision is saved with two fields and is listed as missing its review date"},
    "better-search": {"title": _t("Легше знайти старе рішення", "Легче найти старое решение", "Finding a past decision more easily"),
                      "change": "Search across rationale, sources and reviews, with filters by responsible person and date",
                      "test": "A word that occurs only in a review finds the decision that review belongs to"},
    "review-reminders": {"title": _t("Нагадування про перегляд рішення", "Напоминания о пересмотре решения", "Reminders to review a decision"),
                         "change": "Show decisions whose review date has passed at the top of the page with a counter",
                         "test": "A decision past its review date is listed first and counted in a 'due for review' badge"},
    "reminders-in-telegram": {"title": _t("Нагадування у Telegram", "Напоминания в Telegram", "Review reminders in Telegram"),
                              "change": "Send the owner a Telegram message when a decision becomes due for review",
                              "test": "A decision reaching its review date produces exactly one Telegram reminder"},
    "reminders-by-email": {"title": _t("Нагадування на пошту", "Напоминания на почту", "Review reminders by e-mail"),
                           "change": "Send the owner an e-mail when a decision becomes due for review",
                           "test": "A decision reaching its review date produces exactly one e-mail reminder"},
}


def _o(oid: str, uk: str, ru: str, en: str, theme: str = "", contra: tuple = ()) -> dict[str, Any]:
    return {"id": oid, "text": _t(uk, ru, en), "theme": theme, "contra": list(contra)}


QUIZZES: dict[str, dict[str, Any]] = {
    "mycast": {
        "version": "mycast-q1", "name": "MyCast", "api": "/api/mycast/quiz", "access": "public", "identity": "listener",
        "rewards": True, "peers": _t("Інші слухачі", "Другие слушатели", "Other listeners"),
        "summary": {"job": (("listens", "q_use"), ("length", "q_length")), "helped": (("add", "q_add"), ("channel", "q_channel")),
                    "failed": "q_fix"},
        "title": _t("Допоможіть покращити MyCast", "Помогите улучшить MyCast", "Help us improve MyCast"),
        "questions": [
            {"id": "q_use", "kind": "single", "text": _t("Як часто ви слухаєте MyCast?", "Как часто вы слушаете MyCast?", "How often do you listen to MyCast?"),
             "options": [_o("daily", "Щодня", "Каждый день", "Every day"), _o("weekly", "Кілька разів на тиждень", "Несколько раз в неделю", "A few times a week"),
                         _o("rarely", "Рідко", "Редко", "Rarely"), _o("not_yet", "Ще не слухав(ла)", "Ещё не слушал(а)", "Not yet")]},
            {"id": "q_length", "kind": "single", "text": _t("Яка довжина епізоду вам зручніша?", "Какая длина эпизода вам удобнее?", "Which episode length suits you?"),
             "options": [_o("short", "Коротко, 5 хв", "Коротко, 5 мин", "Short, 5 min", "shorter-episodes"),
                         _o("same", "Як зараз", "Как сейчас", "As it is now", "", ("shorter-episodes", "longer-episodes")),
                         _o("long", "Довше, 20+ хв", "Длиннее, 20+ мин", "Longer, 20+ min", "longer-episodes")]},
            {"id": "q_add", "kind": "multi", "max": 2, "text": _t("Що додати? (до двох)", "Что добавить? (до двух)", "What should we add? (up to two)"),
             "options": [_o("transcript", "Текст епізоду", "Текст эпизода", "A transcript", "text-transcript"),
                         _o("voices", "Вибір голосів", "Выбор голосов", "Voice choice", "voice-choice"),
                         _o("ask", "Питання до епізоду", "Вопрос к эпизоду", "Ask about the episode", "ask-follow-up"),
                         _o("offline", "Завантаження офлайн", "Скачивание офлайн", "Offline download", "offline-download"),
                         _o("nothing", "Нічого не треба", "Ничего не нужно", "Nothing")]},
            {"id": "q_fix", "kind": "single", "text": _t("Що заважає найбільше?", "Что мешает больше всего?", "What gets in the way most?"),
             "options": [_o("setup", "Довге налаштування", "Долгая настройка", "Setup takes too long", "shorter-setup"),
                         _o("voice", "Голос звучить штучно", "Голос звучит искусственно", "The voice sounds robotic", "better-voices"),
                         _o("topics", "Теми не ті", "Темы не те", "Topics miss the mark", "better-topic-match"),
                         _o("none", "Нічого не заважає", "Ничего не мешает", "Nothing")]},
            {"id": "q_channel", "kind": "single", "text": _t("Де вам зручніше отримувати епізод?", "Где вам удобнее получать эпизод?", "Where would you rather get your episode?"),
             "options": [_o("telegram", "Telegram, як зараз", "Telegram, как сейчас", "Telegram, as now", "", ("email-delivery", "podcast-app-feed")),
                         _o("email", "На пошту", "На почту", "By e-mail", "email-delivery"),
                         _o("app", "У подкаст-застосунку", "В подкаст-приложении", "In a podcast app", "podcast-app-feed"),
                         _o("web", "На сайті", "На сайте", "On the website")]},
        ],
        "free_text": _t("Своїми словами: що б ви змінили?", "Своими словами: что бы вы изменили?", "In your own words: what would you change?"),
    },
    # T-636: MyBrief is a public page without accounts -> no gift; only people signed in to FactoryOS shape themes.
    "mybrief-pro": {
        "version": "mybrief-q1", "name": "MyBrief", "api": "/api/mybrief/public/quiz", "access": "public", "identity": "workspace",
        "rewards": False, "peers": _t("Інші читачі", "Другие читатели", "Other readers"),
        "summary": {"job": (("reads", "q_use"), ("size", "q_length")), "helped": (("add", "q_add"), ("channel", "q_channel")),
                    "failed": "q_fix"},
        "title": _t("Допоможіть покращити MyBrief", "Помогите улучшить MyBrief", "Help us improve MyBrief"),
        "questions": [
            {"id": "q_use", "kind": "single", "text": _t("Ви вже відкривали брифінг MyBrief?", "Вы уже открывали брифинг MyBrief?", "Have you opened a MyBrief briefing yet?"),
             "options": [_o("several", "Так, кілька разів", "Да, несколько раз", "Yes, several times"), _o("once", "Так, один раз", "Да, один раз", "Yes, once"),
                         _o("not_yet", "Ще ні", "Ещё нет", "Not yet")]},
            {"id": "q_length", "kind": "single", "text": _t("Скільки має вміщати один брифінг?", "Сколько должен вмещать один брифинг?", "How much should one briefing hold?"),
             "options": [_o("short", "Коротко: 3 пункти на 2 хвилини", "Коротко: 3 пункта на 2 минуты", "Short: 3 items, two minutes", "shorter-brief"),
                         _o("same", "Як зараз", "Как сейчас", "As it is now", "", ("shorter-brief", "deeper-brief")),
                         _o("deep", "Детальніше про кожен пункт", "Подробнее о каждом пункте", "More detail on each item", "deeper-brief")]},
            {"id": "q_add", "kind": "multi", "max": 2, "text": _t("Що додати? (до двох)", "Что добавить? (до двух)", "What should we add? (up to two)"),
             "options": [_o("own", "Свої професія і теми", "Свои профессия и темы", "My own profession and topics", "custom-topics"),
                         _o("fresh", "Свіжий брифінг щодня", "Свежий брифинг каждый день", "A fresh briefing every day", "fresh-daily-brief"),
                         _o("why", "Чому це важливо для моєї роботи", "Почему это важно для моей работы", "Why it matters for my job", "job-relevance-note"),
                         _o("save", "Зберегти або поділитися пунктом", "Сохранить или поделиться пунктом", "Save or share an item", "save-share-items"),
                         _o("nothing", "Нічого не треба", "Ничего не нужно", "Nothing")]},
            {"id": "q_fix", "kind": "single", "text": _t("Що заважає найбільше?", "Что мешает больше всего?", "What gets in the way most?"),
             "options": [_o("match", "Пункти не про мою роботу", "Пункты не про мою работу", "Items are not about my job", "better-brief-match"),
                         _o("sources", "Замало джерел, щоб довіряти", "Мало источников, чтобы доверять", "Too few sources to trust it", "more-sources"),
                         _o("scan", "Важко швидко переглянути", "Трудно быстро просмотреть", "Hard to scan quickly", "scannable-layout"),
                         _o("none", "Нічого не заважає", "Ничего не мешает", "Nothing")]},
            {"id": "q_channel", "kind": "single", "text": _t("Де вам зручніше читати брифінг?", "Где вам удобнее читать брифинг?", "Where would you rather read the briefing?"),
             "options": [_o("web", "На сайті, як зараз", "На сайте, как сейчас", "On the website, as now", "", ("brief-by-email", "brief-in-telegram")),
                         _o("email", "На пошті", "На почте", "By e-mail", "brief-by-email"),
                         _o("telegram", "У Telegram", "В Telegram", "In Telegram", "brief-in-telegram")]},
        ],
        "free_text": _t("Своїми словами: що б ви змінили у брифінгу?", "Своими словами: что бы вы изменили в брифинге?", "In your own words: what would you change in the briefing?"),
    },
    # T-636: Decision Memory is owner-only (#187), so its quiz sits behind the same login and has no gift either.
    "decision-memory": {
        "version": "decision-memory-q1", "name": "Decision Memory", "api": "/api/decision-memory/quiz", "access": "owner",
        "identity": "workspace", "rewards": False, "peers": _t("Інші користувачі", "Другие пользователи", "Other users"),
        "summary": {"job": (("opens", "q_use"), ("capture", "q_capture")), "helped": (("add", "q_add"), ("reminders", "q_channel")),
                    "failed": "q_fix"},
        "title": _t("Допоможіть покращити Decision Memory", "Помогите улучшить Decision Memory", "Help us improve Decision Memory"),
        "questions": [
            {"id": "q_use", "kind": "single", "text": _t("Як часто ви відкриваєте Decision Memory?", "Как часто вы открываете Decision Memory?", "How often do you open Decision Memory?"),
             "options": [_o("weekly", "Щотижня", "Каждую неделю", "Every week"), _o("monthly", "Кілька разів на місяць", "Несколько раз в месяц", "A few times a month"),
                         _o("rarely", "Рідко", "Редко", "Rarely"), _o("not_yet", "Ще не користувався(лась)", "Ещё не пользовался(ась)", "Not yet")]},
            {"id": "q_capture", "kind": "single", "text": _t("Як рішення мають потрапляти в пам’ять?", "Как решения должны попадать в память?", "How should decisions get into the memory?"),
             "options": [_o("manual", "Записую сам(а), як зараз", "Записываю сам(а), как сейчас", "I write them myself, as now", "", ("auto-capture",)),
                         _o("auto", "Збирати автоматично, я лише підтверджую", "Собирать автоматически, я только подтверждаю", "Collect them automatically, I only confirm", "auto-capture")]},
            {"id": "q_add", "kind": "multi", "max": 2, "text": _t("Що додати? (до двох)", "Что добавить? (до двух)", "What should we add? (up to two)"),
             "options": [_o("ask", "Запитати пам’ять своїми словами", "Спросить память своими словами", "Ask the memory a question", "ask-the-memory"),
                         _o("links", "Зв’язок із задачами та PR", "Связь с задачами и PR", "Links to tasks and PRs", "link-to-work"),
                         _o("export", "Експорт рішень", "Экспорт решений", "Export of decisions", "export-decisions"),
                         _o("nothing", "Нічого не треба", "Ничего не нужно", "Nothing")]},
            {"id": "q_fix", "kind": "single", "text": _t("Що заважає найбільше?", "Что мешает больше всего?", "What gets in the way most?"),
             "options": [_o("entry", "Довго заповнювати поля", "Долго заполнять поля", "Filling the fields takes too long", "faster-entry"),
                         _o("find", "Важко знайти старе рішення", "Трудно найти старое решение", "A past decision is hard to find", "better-search"),
                         _o("forget", "Забуваю переглянути рішення", "Забываю пересмотреть решение", "I forget to review decisions", "review-reminders"),
                         _o("none", "Нічого не заважає", "Ничего не мешает", "Nothing")]},
            {"id": "q_channel", "kind": "single", "text": _t("Куди надсилати нагадування про перегляд?", "Куда присылать напоминание о пересмотре?", "Where should a review reminder reach you?"),
             "options": [_o("page", "Досить сторінки, як зараз", "Достаточно страницы, как сейчас", "The page is enough, as now", "", ("reminders-in-telegram", "reminders-by-email")),
                         _o("telegram", "У Telegram", "В Telegram", "In Telegram", "reminders-in-telegram"),
                         _o("email", "На пошту", "На почту", "By e-mail", "reminders-by-email")]},
        ],
        "free_text": _t("Своїми словами: що б ви змінили?", "Своими словами: что бы вы изменили?", "In your own words: what would you change?"),
    },
}


def quiz_themes(pid: str) -> set:
    """The themes one product's quiz can surface: the analyst never acts on another product's theme."""
    return {t for q in QUIZZES[pid]["questions"] for o in q["options"] for t in [o["theme"], *o["contra"]] if t}


def workspace_person(identity: Any) -> str:
    """T-636: a stable id for a product without its own accounts - a FactoryOS sign-in with an e-mail (hashed, the
    address itself is never stored here) or the owner. A guest or viewer session without an e-mail is nobody."""
    ident = identity if isinstance(identity, dict) else {}
    email = str(ident.get("email") or "").strip().lower()
    if email:
        return "ws-" + hashlib.sha256(email.encode()).hexdigest()[:16]
    return "ws-owner" if ident.get("role") == "owner" else ""


class QuizError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _flag(name: str, default: str = "0") -> bool:
    return os.environ.get(name, default).strip() == "1"


def thresholds() -> dict[str, Any]:
    def num(name, default, cast):
        try:
            return cast(os.environ.get(name, "") or default)
        except ValueError:
            return default
    return {"min_people": max(3, num("FACTORY_QUIZ_MIN_PEOPLE", 10, int)),
            "min_share": min(1.0, max(0.1, num("FACTORY_QUIZ_MIN_SHARE", 0.40, float))),
            "auto_handoff": _flag("FACTORY_QUIZ_AUTO_V2", "1")}


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


class QuizService:
    """Quiz state in one JSON file (submissions index, caps, rewards, outbox, analyst log); feedback goes to T-630."""

    def __init__(self, path: Path, evolution: EvolutionStore, *, clock: Callable[[], float] = time.time,
                 create_ticket: Optional[Callable[..., dict]] = None,
                 grant_days: Optional[Callable[[str, int, str], bool]] = None):
        self.path, self.evo, self.clock = Path(path), evolution, clock
        self.create_ticket, self.grant_days = create_ticket, grant_days
        self._lock = threading.Lock()

    # --- storage -------------------------------------------------------------------------------------------------
    def _load(self) -> dict[str, Any]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("submissions"), dict) and data.get("salt"):
                for k, v in (("daily", {}), ("rewards", []), ("outbox", []), ("analyst", [])):
                    data.setdefault(k, v)
                return data
        except FileNotFoundError:
            return {"salt": secrets.token_hex(16), "submissions": {}, "daily": {}, "rewards": [], "outbox": [], "analyst": []}
        except (OSError, ValueError):
            pass
        raise QuizError("quiz_store_unreadable", 503)

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for k, cap in (("rewards", 5000), ("outbox", 5000), ("analyst", 300)):
            del data[k][:-cap]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)
        try:
            self.path.chmod(0o600)
        except OSError:
            pass

    # --- public quiz ---------------------------------------------------------------------------------------------
    def quiz(self, pid: str) -> dict[str, Any]:
        if pid not in QUIZZES:
            raise QuizError("unknown_quiz", 404)
        q = QUIZZES[pid]
        gifts = bool(q["rewards"]) and _flag("FACTORY_QUIZ_REWARDS")  # T-636: never promised where there are no accounts
        out = {"project": pid, "version": q["version"], "name": q["name"], "title": q["title"], "questions": q["questions"],
               "free_text": q["free_text"], "rewards_enabled": gifts, "reward_days": REWARD_DAYS if gifts else 0, "validate": None}
        lead = self._leading_theme(pid)
        if lead:  # adaptive: ask the next people whether the emerging theme really matters to them
            title = THEMES[lead]["title"]
            peers = q["peers"]
            out["validate"] = {"theme": lead, "text": _t(f"{peers['uk']} просять: «{title['uk']}». Ви б цим користувалися?",
                                                         f"{peers['ru']} просят: «{title['ru']}». Вы бы этим пользовались?",
                                                         f"{peers['en']} ask for: “{title['en']}”. Would you use it?")}
        return out

    def _leading_theme(self, pid: str) -> str:
        try:
            view = self.evo.view(pid)
        except EvolutionError:
            return ""
        open_themes = {p.get("theme") for p in view["proposals"] if p["state"] != "declined"
                       and p["from_version"] == view["current_version"]}
        mine = quiz_themes(pid)
        for th in view["themes"].get(view["current_version"], []):
            if th["theme"] in mine and th["theme"] not in open_themes and th["unique_support"] >= 3:
                return th["theme"]
        return ""

    def submit(self, pid: str, body: dict[str, Any], *, client: str, listener: str = "") -> dict[str, Any]:
        if pid not in QUIZZES:
            raise QuizError("unknown_quiz", 404)
        quiz = QUIZZES[pid]
        if body.get("consent") is not True:
            raise QuizError("consent_required")
        if body.get("version") != quiz["version"]:
            raise QuizError("quiz_changed", 409)
        answers = body.get("answers") if isinstance(body.get("answers"), dict) else {}
        chosen: dict[str, list[str]] = {}
        for q in quiz["questions"]:
            raw = answers.get(q["id"])
            if raw in (None, "", []):
                continue
            ids = raw if isinstance(raw, list) else [raw]
            ids = [str(i) for i in ids]
            valid = {o["id"] for o in q["options"]}
            if any(i not in valid for i in ids) or len(set(ids)) != len(ids):
                raise QuizError("bad_answer")
            if q["kind"] == "single" and len(ids) != 1 or q["kind"] == "multi" and len(ids) > q.get("max", 2):
                raise QuizError("bad_answer")
            chosen[q["id"]] = ids
        if len(chosen) < MIN_ANSWERS:
            raise QuizError("too_few_answers")
        free = clean_text(body.get("free_text"), FREE_TEXT_MAX)
        validate = body.get("validate") if isinstance(body.get("validate"), dict) else None
        email, contact = str(body.get("email") or "").strip()[:254], body.get("contact_consent") is True
        if email and (not contact or not EMAIL_RE.match(email)):
            raise QuizError("bad_email" if contact else "contact_consent_required")
        themes, contra = [], []
        # Codex review #412: an anonymous identity rotates daily, so one person could count as many. Only signed-in
        # listeners (one stable identity per quiz version) and people who actually used the product shape themes.
        used = bool(listener) and chosen.get("q_use", [""])[0] != "not_yet"
        if used:
            for q in quiz["questions"]:
                for oid in chosen.get(q["id"], []):
                    opt = next(o for o in q["options"] if o["id"] == oid)
                    if opt["theme"]:
                        themes.append(opt["theme"])
                    contra.extend(opt["contra"])
            if validate and validate.get("theme") in quiz_themes(pid) and validate.get("answer") in ("yes", "no"):
                (themes if validate["answer"] == "yes" else contra).append(validate["theme"])
        themes = list(dict.fromkeys(themes))[:5]
        contra = [c for c in dict.fromkeys(contra) if c not in themes][:5]
        now = self.clock()
        day = _day(now)
        with self._lock:
            data = self._load()
            ckey = hashlib.sha256(f"{data['salt']}|{day}|{client}".encode()).hexdigest()[:20]
            who = f"listener:{listener}" if listener else f"anon:{ckey}"
            phash = hashlib.sha256(f"{data['salt']}|{pid}|{quiz['version']}|{who}".encode()).hexdigest()[:24]
            if phash in data["submissions"]:
                raise QuizError("already_answered", 409)
            counts = data["daily"].setdefault(day, {"total": 0, "clients": {}})
            if counts["total"] >= GLOBAL_DAILY or counts["clients"].get(ckey, 0) >= PER_CLIENT_DAILY:
                raise QuizError("daily_limit", 429)
            sid = "qz-" + secrets.token_hex(5)
            summ = quiz["summary"]
            labels = {q["id"]: ", ".join(next(o for o in q["options"] if o["id"] == i)["text"]["en"] for i in ids)
                      for q in quiz["questions"] for ids in [chosen.get(q["id"], [])] if ids}
            try:
                fb = self.evo.add_feedback(pid, {
                    "consent": True, "consent_ref": f"{pid}-quiz:{quiz['version']}:{sid}", "participant": who,
                    "source": "in_product", "tried": "yes" if used else "no",
                    "job": f"{quiz['name']} quiz {quiz['version']}: " + "; ".join(f"{k} {labels.get(q, '?')}" for k, q in summ["job"]),
                    "helped": "; ".join(f"{k}: {labels.get(q, '—')}" for k, q in summ["helped"]),
                    "failed": "; ".join(x for x in (f"in the way: {labels[summ['failed']]}" if labels.get(summ["failed"]) else "", free) if x),
                    "themes": themes, "contra": contra, "idempotency_key": f"quiz:{phash}"}, actor_role="agent", actor="quiz")
            except EvolutionError as exc:
                raise QuizError(exc.code, exc.status)
            fid = fb["feedback"]["id"]
            data["submissions"][phash] = {"id": sid, "at": _iso(now), "project": pid, "version": quiz["version"],
                                          "feedback_id": fid, "listener": listener or None, "counted": used,
                                          "email": email if (email and contact) else None}
            counts["total"] += 1
            counts["clients"][ckey] = counts["clients"].get(ckey, 0) + 1
            data["daily"] = {d: v for d, v in data["daily"].items() if d >= day}
            reward = self._reward(data, sid, listener, bool(quiz["rewards"]))
            if email and contact:
                data["outbox"].append({"id": f"mail:{sid}:thanks", "at": _iso(now), "submission": sid, "template": "thanks",
                                       "status": "held_flag_off" if not _flag("FACTORY_QUIZ_MAIL") else "held_no_provider"})
            self._save(data)
        actions = self.analyze(pid)
        anon = "sign_in_to_count" if quiz["identity"] == "listener" else "anonymous_not_counted"
        return {"id": sid, "counted": used, "reason": "" if used else (anon if not listener else "not_used_yet"),
                "reward": reward, "analyst": actions,
                "stored": ["answers", "free_text"] + (["email"] if email else [])}

    def _reward(self, data: dict, sid: str, listener: str, product_has_gifts: bool = True) -> dict[str, Any]:
        """A gift is for a signed-in listener only, once per quiz version (the submission is already unique)."""
        if not product_has_gifts:  # T-636: no product accounts -> nothing to add days to, and nothing is recorded as held
            return {"status": "none", "reason": "no_accounts"}
        if not listener:
            return {"status": "none", "reason": "sign_in_for_gift"}
        entry = {"id": f"reward:{sid}", "listener": listener, "days": REWARD_DAYS, "status": "held_flag_off"}
        if _flag("FACTORY_QUIZ_REWARDS") and self.grant_days:
            entry["status"] = "granted" if self.grant_days(listener, REWARD_DAYS, entry["id"]) else "not_granted"
        data["rewards"].append(entry)
        return {"status": entry["status"], "days": REWARD_DAYS if entry["status"] == "granted" else 0}

    # --- analyst agent -------------------------------------------------------------------------------------------
    def analyze(self, pid: str) -> list[dict[str, Any]]:
        """Propose a V2 change for each theme past the threshold and, under the standing rule, hand it to Builder."""
        cfg = thresholds()
        try:
            view = self.evo.view(pid)
        except EvolutionError:
            return []
        version, mine = view["current_version"], quiz_themes(pid) if pid in QUIZZES else set()
        taken = {p.get("theme") for p in view["proposals"] if p["state"] != "declined" and p["from_version"] == version}
        actions = []
        if cfg["auto_handoff"] and self.create_ticket:  # retry a hand-off that failed earlier (e.g. Relay down)
            for p in view["proposals"]:
                if p["state"] == "proposed" and p.get("proposed_by") == "agent" and p.get("theme") in mine \
                        and p["from_version"] == version and not p.get("synthetic"):
                    try:
                        done = self.evo.policy_handoff(pid, p["id"], policy=POLICY, evidence={"retry": True, "theme": p["theme"]},
                                                       create_ticket=self.create_ticket)["proposal"]
                        actions.append({"theme": p["theme"], "proposal": p["id"], "handoff": "handed_off", "ticket": done["ticket_id"], "retry": True})
                    except EvolutionError as exc:
                        actions.append({"theme": p["theme"], "proposal": p["id"], "error": exc.code, "retry": True})
        for th in view["themes"].get(version, []):
            name = th["theme"]
            if name not in mine or name in taken:
                continue
            if th["unique_support"] < cfg["min_people"] or th["share"] < cfg["min_share"] or th["unique_contra"] * 2 >= th["unique_support"]:
                continue
            spec = THEMES[name]
            evidence = {"theme": name, "people": th["unique_support"], "contrary": th["unique_contra"],
                        "sample": th["sample_size"], "share": th["share"], "min_people": cfg["min_people"],
                        "min_share": cfg["min_share"]}
            try:
                prop = self.evo.propose(pid, {
                    "title": spec["title"]["en"], "theme": name, "feedback_ids": th["support_ids"][:50],
                    "problem": f"{th['unique_support']} of {th['sample_size']} people ({round(th['share'] * 100)}%) asked for: "
                               f"{spec['title']['en']}; {th['unique_contra']} answered against.",
                    "change": spec["change"], "acceptance_test": spec["test"],
                    "idempotency_key": f"analyst:{pid}:{version}:{name}"}, actor_role="agent", actor="quiz-analyst")["proposal"]
                action = {"theme": name, "proposal": prop["id"], "handoff": "waiting_owner", **evidence}
                if cfg["auto_handoff"] and self.create_ticket:
                    done = self.evo.policy_handoff(pid, prop["id"], policy=POLICY, evidence=evidence,
                                                   create_ticket=self.create_ticket)["proposal"]
                    action["handoff"], action["ticket"] = "handed_off", done["ticket_id"]
            except EvolutionError as exc:
                action = {"theme": name, "error": exc.code}
            actions.append(action)
            with self._lock:
                data = self._load()
                data["analyst"].append(dict(action, at=_iso(self.clock()), project=pid, version=version))
                self._save(data)
        return actions

    # --- owner view / privacy ------------------------------------------------------------------------------------
    def stats(self, pid: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
        subs = [s for s in data["submissions"].values() if s["project"] == pid]
        return {"project": pid, "version": QUIZZES.get(pid, {}).get("version"), "thresholds": thresholds(),
                "submissions": len(subs), "counted": sum(1 for s in subs if s["counted"]),
                "signed_in": sum(1 for s in subs if s["listener"]), "with_email": sum(1 for s in subs if s["email"]),
                "rewards": {k: sum(1 for r in data["rewards"] if r["status"] == k) for k in ("held_flag_off", "granted", "not_granted")},
                "outbox": {k: sum(1 for m in data["outbox"] if m["status"] == k) for k in ("held_flag_off", "held_no_provider", "sent")},
                "flags": {"rewards": _flag("FACTORY_QUIZ_REWARDS"), "mail": _flag("FACTORY_QUIZ_MAIL")},
                "analyst": [a for a in data["analyst"] if a.get("project") == pid][-20:],
                "latest": [{k: s[k] for k in ("id", "at", "version", "feedback_id", "counted")} for s in subs[-30:]]}

    def delete(self, pid: str, sid: str) -> dict[str, Any]:
        with self._lock:
            data = self._load()
            key = next((k for k, s in data["submissions"].items() if s["id"] == sid and s["project"] == pid), None)
            if not key:
                raise QuizError("not_found", 404)
            fid = data["submissions"].pop(key)["feedback_id"]
            data["outbox"] = [m for m in data["outbox"] if m.get("submission") != sid]
            self._save(data)
        try:
            self.evo.delete_feedback(pid, fid, actor_role="owner", actor="quiz-privacy-delete")
        except EvolutionError:
            pass
        return {"deleted": sid}


def install_mvp_quiz_routes(app, service: QuizService, identity_fn: Callable, *,
                            listener_fn: Callable[[Request], str] = lambda request: "",
                            client_fn: Callable[[Request], str] = lambda request: "?") -> None:
    """Per product quiz: GET/POST on its `api` path - public and capped (MyCast, MyBrief) or owner-only (Decision
    Memory). Owner/member: stats. Owner: privacy delete."""

    def _err(exc: QuizError):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    def _role(request: Request) -> str:
        return str((identity_fn(request) or {}).get("role") or "")

    def _mount(pid: str, spec: dict[str, Any]) -> None:
        owner_only = spec["access"] == "owner"

        def _listener(request: Request) -> str:
            if spec["identity"] == "listener":
                return listener_fn(request) or ""
            return workspace_person(identity_fn(request))

        def _denied(request: Request):
            role = _role(request)
            if role == "owner":
                return None
            return JSONResponse({"detail": "owner_only" if role else "login_required"}, status_code=403 if role else 401)

        def quiz_get():
            try:
                return service.quiz(pid)
            except QuizError as exc:
                return _err(exc)

        def quiz_get_owner(request: Request):
            return _denied(request) or quiz_get()

        async def quiz_submit(request: Request):
            denial = _denied(request) if owner_only else None
            if denial is not None:
                return denial
            try:
                body = await request.json()
            except (ValueError, TypeError):
                body = None
            if not isinstance(body, dict):
                return JSONResponse({"detail": "bad_body"}, status_code=400)
            try:
                return service.submit(pid, body, client=client_fn(request), listener=_listener(request))
            except QuizError as exc:
                return _err(exc)

        slug = pid.replace("-", "_")
        app.get(spec["api"], name=f"{slug}_quiz")(quiz_get_owner if owner_only else quiz_get)
        app.post(spec["api"], name=f"{slug}_quiz_submit")(quiz_submit)

    for pid, spec in QUIZZES.items():  # T-636: one pair of routes per product quiz
        _mount(pid, spec)

    @app.get("/api/mvp-quiz/{project_id}/stats")
    def mvp_quiz_stats(project_id: str, request: Request):
        role = _role(request)
        if role not in ("owner", "member"):
            return JSONResponse({"detail": "login_required" if not role else "forbidden"}, status_code=401 if not role else 403)
        return service.stats(project_id)

    @app.post("/api/mvp-quiz/{project_id}/submissions/{submission_id}/delete")
    def mvp_quiz_delete(project_id: str, submission_id: str, request: Request):
        if _role(request) != "owner":
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        try:
            return service.delete(project_id, submission_id)
        except QuizError as exc:
            return _err(exc)
