"""Owner desk: step-by-step runbooks for [HUMAN] ROADMAP tasks and owner questions answered by the Claude worker.

Runbooks are static, reviewed text. Russian (the owner's working language) is the source; EN and UK
translations live in owner_desk_i18n.py and are served by `?lang=`. Every step says what to do,
how to check it worked, and what to do for each known failure. Live status comes from facts the server
already has (Telegram pairing, publisher adapter, build SHA); nothing here calls a provider.

Questions: the owner highlights runbook text and asks about it. The question is queued here; the Claude
worker on EC2 claims it with its worker token, answers read-only from the repository and posts the answer
back. Secrets are never requested or shown: runbooks tell the owner to type secrets only into Render, AWS
or a terminal, and the worker prompt forbids asking for them.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel

from owner_desk_i18n import RUNBOOK_I18N, STATUS_DETAILS

QUOTE_MAX = 800
QUESTION_MAX = 1500
ANSWER_MAX = 6000
MAX_OPEN_QUESTIONS = 20
MAX_KEPT_QUESTIONS = 200
CLAIM_LEASE_SECONDS = 900
QUESTION_STATES = ("pending", "answering", "answered", "failed")
# Internal round-trip probe: the worker asks itself a question so the site → worker → answer → Telegram
# chain is proven regularly without the owner and without a Claude run. Never shown in the owner UI.
SELFTEST_TASK = "SELFTEST"
TELEGRAM_TASK = "TELEGRAM"  # owner-only `/ask` input; not a ROADMAP runbook
STALE_QUESTION_SECONDS = 3600

RENDER_ENV = ("Render → Dashboard → сервис blackboxlab-factoryos → вкладка Environment → "
              "кнопка Add Environment Variable")
RENDER_SAVE = ("Нажмите Save, rebuild, and deploy (или Save changes, затем Manual Deploy → Deploy latest commit). "
               "Дождитесь, пока во вкладке Events деплой станет Live (обычно 5–15 минут).")
NO_SECRETS = "Секрет вставляйте только в Render / AWS / терминал. Никогда не отправляйте его в чат, Telegram или в вопрос на сайте."

RUNBOOKS: list[dict[str, Any]] = [
    {
        "id": "T-506",
        "title": "Привязать Telegram-бота владельца",
        "why": "Через этот канал FactoryOS присылает вам статусы, вопросы воркера и кнопки Retry. Без привязки T-590/T-591 нельзя закрыть.",
        "time": "≈10 минут",
        "steps": [
            {"id": "check", "title": "Проверьте, может быть, уже готово",
             "do": ["Посмотрите на статус этой карточки вверху: если «Готово» — бот уже привязан.",
                    "Либо откройте раздел «Подключения» → блок «Telegram-канал владельца»."],
             "check": "Если там «Подключено» — сразу переходите к шагу «Тестовое сообщение».",
             "if": [{"when": "Написано «Токен бота ещё не добавлен в Render»", "then": "Идите по шагам по порядку, начиная с «Создайте бота»."},
                    {"when": "Написано «Бот настроен, но чат владельца ещё не привязан»", "then": "Пропустите два шага про токен и начните с «Запустите привязку»."}]},
            {"id": "bot", "title": "Создайте бота (или возьмите существующего)",
             "do": ["В Telegram откройте @BotFather (с синей галочкой).",
                    "Отправьте /newbot, придумайте имя, затем username, который заканчивается на bot (например blackboxlab_factory_bot).",
                    "BotFather пришлёт токен вида 123456789:AA… — это секрет. " + NO_SECRETS],
             "check": "У вас есть токен, и бот открывается по ссылке t.me/<username>.",
             "if": [{"when": "«Sorry, this username is already taken»", "then": "Придумайте другой username, он должен быть уникальным и заканчиваться на bot."},
                    {"when": "Бот уже есть, а токен потерян", "then": "В @BotFather: /mybots → ваш бот → API Token. Кнопка Revoke выдаёт новый токен, старый перестанет работать."}]},
            {"id": "render", "title": "Добавьте токен в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_TELEGRAM_BOT_TOKEN, Value: токен от BotFather (без пробелов и кавычек).",
                    RENDER_SAVE],
             "check": "После деплоя статус в «Подключениях» сменится на «Бот настроен, но чат владельца ещё не привязан».",
             "if": [{"when": "Статус всё ещё «Токен бота ещё не добавлен»", "then": "Деплой ещё не закончился, или переменная сохранена в другом сервисе. Проверьте имя ключа буква в букву и что деплой в Events — Live."},
                    {"when": "Деплой упал (Failed)", "then": "Токен тут ни при чём. Откройте лог деплоя в Render и задайте мне вопрос, выделив этот шаг: я разберу ошибку."}]},
            {"id": "pair", "title": "Запустите привязку",
             "do": ["В FactoryOS: «Подключения» → «Telegram-канал владельца» → «Начать привязку».",
                    "Команда вида /pair ABCD1234 скопируется сама. Откройте вашего бота и отправьте её (или нажмите Start по ссылке, если она появилась).",
                    "Код действует 10 минут."],
             "check": "Через несколько секунд бот ответит, а статус станет «Подключено».",
             "if": [{"when": "Ошибка «Telegram bot token is not configured» (503)", "then": "Вернитесь к шагу «Добавьте токен в Render»: сервер токена не видит."},
                    {"when": "Ошибка «Telegram pairing could not be initialized» (502)", "then": "Telegram не принял токен. Скопируйте токен заново из @BotFather (/mybots → API Token), замените значение в Render и задеплойте ещё раз."},
                    {"when": "Бот молчит после /pair", "then": "Код истёк (10 минут) или команда ушла не тому боту. Нажмите «Начать привязку» ещё раз и отправьте новую команду именно вашему боту."}]},
            {"id": "test", "title": "Тестовое сообщение",
             "do": ["В том же блоке нажмите «Тестовый push»."],
             "check": "В Telegram пришло «✅ FactoryOS Telegram channel test». Задача выполнена: напишите мне «T-506 готово».",
             "if": [{"when": "Ошибка «not paired» (409)", "then": "Привязка не завершилась. Повторите шаг «Запустите привязку»."},
                    {"when": "Ошибка 502 при тесте", "then": "Бот заблокирован в этом чате или токен заменили. Откройте бота, нажмите Start/Restart и повторите тест."}]},
        ],
        "done": "Статус «Подключено» и тестовое сообщение пришло.",
    },
    {
        "id": "T-590-H",
        "title": "Сверить, что на проде нужная версия",
        "why": "Последний шаг T-590: подтвердить, что Render запустил именно тот коммит, который влит в main.",
        "time": "≈2 минуты",
        "steps": [
            {"id": "sha", "title": "Сравните коммит на проде с main",
             "do": ["Посмотрите строку «Сейчас на проде» в статусе этой карточки: это build_sha, который отдаёт сам сервер.",
                    "Откройте github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/commits/main и сравните первые 7 символов последнего коммита."],
             "check": "Совпадает — напишите мне «T-590 sha совпал».",
             "if": [{"when": "На проде более старый коммит", "then": "Деплой ещё идёт или упал. Render → сервис → Events: если Failed — задайте мне вопрос по этому шагу; если In progress — подождите 10 минут."},
                    {"when": "Вместо SHA написано local", "then": "Сервер запущен не из Render (например, локально). Это нормально только для теста; на проде так быть не должно — спросите меня."}]},
        ],
        "done": "build_sha на проде совпадает с последним коммитом main.",
    },
    {
        'id': 'T-520',
        'title': 'Подключить прямую публикацию в YouTube',
        'why': 'Публикуем в YouTube Shorts напрямую через официальный бесплатный YouTube Data API, без платного Metricool. Нужен ваш собственный «ключ приложения» в Google Cloud и одно подключение канала.',
        'time': '≈30 минут',
        'steps': [
            {
                'id': 'project',
                'title': 'Создайте проект в Google Cloud',
                'do': [
                    'Откройте console.cloud.google.com и войдите тем Google-аккаунтом, которому принадлежит YouTube-канал.',
                    'Вверху слева нажмите на выбор проекта → New project. Имя: factoryos-youtube. Нажмите Create и выберите этот проект вверху.',
                    'Карта и Billing не нужны: YouTube Data API бесплатен в пределах квоты.',
                ],
                'check': 'Вверху страницы выбран проект factoryos-youtube.',
                'if': [
                    {
                        'when': 'Google просит включить Billing или привязать карту',
                        'then': 'СТОП: не привязывайте. Для этой задачи оплата не нужна — задайте вопрос по этому шагу.',
                    },
                ],
            },
            {
                'id': 'api',
                'title': 'Включите YouTube Data API v3',
                'do': [
                    'Меню ☰ → APIs & Services → Library.',
                    'В поиске наберите YouTube Data API v3 → откройте → Enable.',
                ],
                'check': 'На странице API написано API Enabled (или кнопка Manage).',
                'if': [
                    {
                        'when': 'Кнопки Enable нет, есть Manage',
                        'then': 'API уже включён — переходите дальше.',
                    },
                ],
            },
            {
                'id': 'consent',
                'title': 'Настройте экран согласия (Google Auth Platform)',
                'do': [
                    'Меню ☰ → APIs & Services → OAuth consent screen (раздел может называться Google Auth Platform) → Get started.',
                    'App name: FactoryOS. User support email: ваш email. Audience: External. Contact email: ваш email. Согласитесь с правилами → Create.',
                    'Слева Audience → Publish app → Confirm. Статус станет In production. Это важно: в режиме Testing подключение отваливается каждые 7 дней.',
                    'Проверку Google (verification) проходить не нужно: приложением пользуетесь только вы.',
                ],
                'check': 'В Audience написано Publishing status: In production.',
                'if': [
                    {
                        'when': 'Google пишет, что нужна verification',
                        'then': "Для личного использования её можно не проходить: при входе будет предупреждение «Google hasn't verified this app», его можно пропустить (шаг «Подключите канал»).",
                    },
                ],
            },
            {
                'id': 'client',
                'title': 'Создайте OAuth-клиент',
                'do': [
                    'Слева Clients (или APIs & Services → Credentials → Create credentials → OAuth client ID).',
                    'Application type: Web application. Name: FactoryOS.',
                    'Authorized redirect URIs → Add URI → вставьте ровно: https://blackboxlab-factoryos.onrender.com/api/oauth/youtube/callback',
                    'Нажмите Create. Появятся Client ID (заканчивается на .apps.googleusercontent.com) и Client secret (начинается с GOCSPX-). Client secret — секрет, Google может показать его только один раз: нажмите Download JSON или сразу сохраните в менеджер паролей. ' + NO_SECRETS,
                ],
                'check': 'У вас сохранены Client ID и Client secret.',
                'if': [
                    {
                        'when': 'Ошибка redirect_uri_mismatch позже при подключении',
                        'then': 'Адрес в Authorized redirect URIs отличается хоть одним символом. Скопируйте адрес из этого шага заново (https, без слэша в конце) и сохраните клиент.',
                    },
                    {
                        'when': 'Client secret больше не показывается',
                        'then': 'В карточке клиента нажмите Add secret, создайте новый, а старый удалите.',
                    },
                ],
            },
            {
                'id': 'render',
                'title': 'Добавьте переменные в Render',
                'do': [
                    RENDER_ENV + ' — добавьте по одной:',
                    'FACTORY_OAUTH_GOOGLE_CLIENT_ID = ваш Client ID',
                    'FACTORY_OAUTH_GOOGLE_CLIENT_SECRET = ваш Client secret. ' + NO_SECRETS,
                    'FACTORY_PUBLISHER_ADAPTER = youtube (если там стоит manual — замените значение)',
                    'FACTORY_YOUTUBE_MADE_FOR_KIDS = false (контент не для детей; true — если для детей). Это юридическое заявление для YouTube, поэтому значение по умолчанию не ставится.',
                    'FACTORY_YOUTUBE_PRIVACY не добавляйте: по умолчанию видео загружается как private (видно только вам).',
                    'FACTORY_VAULT_KEY уже должен быть задан (T-560-G): в нём хранится токен канала.',
                    RENDER_SAVE,
                ],
                'check': 'Деплой Live. Статус этой карточки: «YouTube выбран, не готово: youtube_not_connected» — значит, осталось подключить канал.',
                'if': [
                    {
                        'when': 'В статусе client_not_configured или client_secret_missing',
                        'then': 'Опечатка в имени FACTORY_OAUTH_GOOGLE_CLIENT_ID / _SECRET или деплой ещё идёт.',
                    },
                    {
                        'when': 'В статусе vault_unavailable',
                        'then': 'Не задан FACTORY_VAULT_KEY — сначала задача T-560-G.',
                    },
                    {
                        'when': 'В статусе youtube_audience_unset',
                        'then': 'Добавьте FACTORY_YOUTUBE_MADE_FOR_KIDS со значением false или true.',
                    },
                ],
            },
            {
                'id': 'connect',
                'title': 'Подключите канал',
                'do': [
                    'На сайте FactoryOS: «Подключения» → YouTube → «Подключить». Вас перебросит на страницу Google.',
                    'Выберите аккаунт (или бренд-аккаунт), которому принадлежит канал.',
                    "Если появится «Google hasn't verified this app»: нажмите Advanced → Go to FactoryOS (unsafe). Это ваше собственное приложение, предупреждение ожидаемо.",
                    'Разрешите доступ (загрузка видео и просмотр канала) → Continue.',
                ],
                'check': 'Вас вернуло на FactoryOS, всплыло «YouTube: аккаунт подключён», статус карточки — «Готово» с названием канала.',
                'if': [
                    {
                        'when': 'youtube_channel_missing',
                        'then': 'У выбранного Google-аккаунта нет YouTube-канала. Подключите заново и выберите аккаунт/бренд с каналом.',
                    },
                    {
                        'when': 'state_expired или state_invalid',
                        'then': 'Прошло больше 10 минут или страницу обновили. Нажмите «Подключить» ещё раз.',
                    },
                    {
                        'when': 'owner session required',
                        'then': 'Вы не вошли на сайт FactoryOS как владелец в этом браузере. Войдите и повторите.',
                    },
                    {
                        'when': 'access_denied / provider_denied',
                        'then': 'На странице Google нажали Cancel. Повторите и нажмите Continue.',
                    },
                ],
            },
        ],
        'done': 'Карточка «Готово»: FactoryOS видит адаптер youtube и подключённый канал (без показа секретов).',
    },
    {
        "id": "T-521",
        "title": "Первый реальный пост с вашим одобрением",
        "why": "Проверяет весь путь: готовое видео → ваше одобрение точного снимка → публикация → квитанция с реальной ссылкой.",
        "time": "≈15 минут",
        "requires": "T-520",
        "steps": [
            {"id": "pick", "title": "Выберите готовую работу",
             "do": ["Откройте «Review» (Approval Studio) и выберите задание с готовым видео.",
                    "Начните с одной площадки (например, YouTube Shorts)."],
             "check": "Видео, заголовок, описание и площадка — именно те, что вы хотите опубликовать.",
             "if": [{"when": "Нет ни одного готового видео", "then": "Сначала нужен прогон фабрики до финального видео. Напишите мне — я поставлю это задачей."}]},
            {"id": "approve", "title": "Одобрите точный снимок",
             "do": ["Нажмите одобрение публикации. Одобряется неизменяемый снимок: если потом что-то поменять, одобрение придётся дать заново."],
             "check": "Статус задания — одобрено, видна площадка.",
             "if": [{"when": "Кнопка одобрения неактивна", "then": "Не пройдена проверка качества или не хватает метаданных. Выделите текст ошибки на экране и спросите меня."}]},
            {"id": "publish", "title": "Опубликуйте и проверьте квитанцию",
             "do": ["Откройте «Publish» (Publishing Studio) и запустите публикацию одобренного снимка."],
             "check": "В квитанции появилась внешняя ссылка или ID поста, и пост виден на площадке.",
             "if": [{"when": "Ошибка «approval required»", "then": "После одобрения что-то изменилось. Вернитесь к шагу «Одобрите точный снимок»."},
                    {"when": "Ошибка от YouTube", "then": "Ничего не повторяйте вслепую, чтобы не было дубля. Выделите текст ошибки и спросите меня."}]},
        ],
        "done": "Внешняя ссылка/ID поста сохранены как квитанция публикатора и привязаны к циклу фабрики.",
    },
    {
        "id": "T-551",
        "title": "OAuth-приложения провайдеров (Google/YouTube, TikTok, Meta/Instagram, HubSpot)",
        "why": "Нужно для подключения клиентских аккаунтов напрямую, без Metricool.",
        "time": "1–3 дня (включая проверки у провайдеров)",
        "requires": "T-552",
        "steps": [
            {"id": "wait", "title": "Пока не начинайте",
             "do": ["Google / YouTube уже делается в карточке T-520 — там готовый адрес возврата и все шаги.",
                    "TikTok, Instagram и HubSpot — позже: у них приложения проходят проверку площадки. Когда дойдёт очередь, я добавлю сюда шаги с готовыми адресами."],
             "check": "Ничего делать не нужно.",
             "if": [{"when": "Хотите начать раньше", "then": "Можно заранее создать аккаунты разработчика (Google Cloud, Meta for Developers, TikTok for Developers, HubSpot developer) — это бесплатно и ни к чему не обязывает."}]},
        ],
        "done": "У каждого провайдера есть боевые client credentials только в секретном хранилище и одобренный callback URL.",
    },
    {
        "id": "T-560-G",
        "title": "Ключ шифрования хранилища (FACTORY_VAULT_KEY) в Render",
        "why": "Без ключа зашифрованное хранилище логинов, браузерных сессий и OAuth-токенов выключено, и фабрика отказывается их сохранять. Ключ ничего платного не включает.",
        "time": "≈5 минут",
        "steps": [
            {"id": "generate", "title": "Сгенерируйте ключ",
             "do": ["На своём компьютере в папке проекта выполните: python -c \"from browser_runner.vault import generate_key; print(generate_key())\"",
                    "Получится строка из 44 символов, это секрет. " + NO_SECRETS],
             "check": "Строка длиной 44 символа, оканчивается на «=».",
             "if": [{"when": "Ошибка «No module named cryptography»", "then": "Сначала выполните pip install cryptography, потом повторите."}]},
            {"id": "render", "title": "Добавьте ключ в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_VAULT_KEY, Value: ваш ключ (без пробелов и кавычек).",
                    "Сохраните ключ ещё в менеджере паролей: без него сохранённые сессии и токены не расшифровать.",
                    RENDER_SAVE],
             "check": "GET /api/factory/vault/status показывает configured: true.",
             "if": [{"when": "configured: false и причина «must be 32 bytes»", "then": "Ключ вставлен не полностью или с пробелом. Сгенерируйте новый и вставьте заново."}]},
        ],
        "done": "GET /api/factory/vault/status показывает configured: true.",
    },
    {
        "id": "T-560-I",
        "title": "Включить поиск Google через Gemini для Сёрфера (по желанию)",
        "why": "Сейчас инструмент web_search ищет только по Википедии (бесплатно, без ключа). Поиск Google через уже подключённый ключ Gemini бесплатен в пределах дневной квоты Google, но на проекте с включённой оплатой сверх квоты он платный. Фабрика ограничивает его 100 запросами в сутки.",
        "time": "≈5 минут",
        "steps": [
            {"id": "decide", "title": "Решите, нужен ли поиск Google",
             "do": ["Если в Google AI Studio у проекта ключа Gemini не подключена оплата (Free tier), сверх квоты Google просто откажет, денег не спишет.",
                    "Если оплата подключена, сверх бесплатной квоты поиск тарифицируется. Лимит фабрики 100 запросов в сутки."],
             "check": "Вы знаете, бесплатный у ключа уровень или платный, и согласны с этим.",
             "if": [{"when": "Не хотите никакого риска оплаты", "then": "Ничего не делайте: web_search продолжит работать через Википедию."}]},
            {"id": "render", "title": "Включите в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_WEB_SEARCH_PROVIDER, Value: gemini (это не секрет).",
                    RENDER_SAVE],
             "check": "web_search через MCP отвечает \"provider\": \"gemini_google_search\".",
             "if": [{"when": "Ответ всё ещё provider: wikipedia с пометкой «failed»", "then": "Ключ Gemini не даёт поиск (квота или модель). Напишите мне, я посмотрю по типу ошибки."}]},
        ],
        "done": "web_search возвращает provider gemini_google_search.",
    },
    {
        "id": "T-620-H",
        "title": "MyCast: утвердить условия «+7 дней другу и +7 вам» и включить акцию",
        "why": "Акция с приглашениями собрана и проверена тестами, но по #305 она скрыта, пока вы не утвердите правила. Приглашения при этом уже записываются в журнал, так что после включения никто не потеряет бонус.",
        "time": "≈15 минут",
        "steps": [
            {"id": "decide", "title": "Проверьте правила акции",
             "do": ["Правило сейчас: вы и друг получаете по +7 дней один раз, когда другу пришёл первый настоящий выпуск в Telegram.",
                    "Ничего не дают: приглашение самого себя (тот же Telegram), повторная регистрация того же друга, регистрация без выпуска, больше 50 друзей.",
                    "Бесплатные дни считаются с первого выпуска. Отключение доставки после окончания дней пока выключено (FACTORY_MYCAST_ENFORCE_TRIAL) — это отдельное решение."],
             "check": "Вы согласны с этими правилами.",
             "if": [{"when": "Хотите давать другу +7 сразу при регистрации (как 07.11)", "then": "Добавьте в Render ещё FACTORY_MYCAST_FRIEND_BONUS=signup."},
                    {"when": "Хотите другие условия (другое число дней, лимит)", "then": "Напишите мне правило — я поменяю код и тесты, акцию пока не включайте."}]},
            {"id": "render", "title": "Включите акцию в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_MYCAST_REFERRALS, Value: 1 (это не секрет).",
                    RENDER_SAVE],
             "check": "GET https://mycast.pro/api/mycast/account/config показывает \"referrals_enabled\": true, на сайте видна плашка с днями и кнопка «Скопировать приглашение».",
             "if": [{"when": "Всё ещё false", "then": "Сверьте имя переменной буква в букву и что деплой в Events — Live."}]},
            {"id": "e2e", "title": "Проверьте на живом сайте",
             "do": ["Скопируйте приглашение в своём кабинете на mycast.pro и откройте его со второго Telegram-аккаунта (друга).",
                    "Друг входит, сохраняет и утверждает подкаст, включает доставку и получает первый выпуск.",
                    "В кабинете у обоих появляется «+7 дней» в строке «Приглашения»."],
             "check": "У обоих +7 дней ровно один раз; повторные выпуски ничего не добавляют.",
             "if": [{"when": "У друга выпуск пришёл, а дней нет", "then": "Напишите мне дату: я посмотрю запись в журнале приглашений (там указана причина отказа)."}]},
        ],
        "done": "referrals_enabled: true, и живая проверка с другом дала +7 дней обоим.",
    },
    {
        "id": "T-645-H",
        "title": "MyCast: сделать и утвердить демо-выпуски про Афины, Рим и другие города",
        "why": "На странице выпуска, которым делится автор, рядом с его карточкой стоят демо-карточки городов (Афины, Рим, Дельфы, Олимпия, Помпеи). Сейчас у них пометка «Скоро» и нет кнопки воспроизведения: готовых демо-аудио нет, а платно я их не генерирую. Как только вы дадите аудио и одобрите его, карточки начнут играть.",
        "time": "≈30 минут",
        "steps": [
            {"id": "choose", "title": "Проверьте список городов и тексты карточек",
             "do": ["Откройте любую свою ссылку на выпуск (mycast.pro/mycast/e/…) и пролистайте карточки влево и вправо.",
                    "Названия и описания лежат в static/mycast-share/demos.json (украинский, русский, английский).",
                    "Если хотите другие города или тексты — напишите мне, я поменяю файл."],
             "check": "Список городов и подписи вас устраивают.",
             "if": [{"when": "Хотите меньше карточек", "then": "Напишите, какие убрать: карточки без аудио можно просто удалить из списка."}]},
            {"id": "audio", "title": "Дайте аудио для демо",
             "do": ["Нужен короткий выпуск двух ведущих на 1–2 минуты про каждый город, MP3 до 3 МБ, без чужой музыки.",
                    "Вариант А: пришлите свои MP3 (например, выпуск MyCast из вашего Telegram, сделанный на тему истории).",
                    "Вариант Б: напишите мне «озвучь демо городов через Gemini» и подтвердите, что ваш ключ Gemini бесплатный или что вы согласны на расход. Без такого подтверждения я ничего не озвучиваю.",
                    "Картинки не нужны: обложки городов рисуются кодом в стиле «ДНК подкаста»."],
             "check": "Для каждого нужного города есть MP3.",
             "if": [{"when": "Gemini отвечает лимитом или ошибкой", "then": "Ничего не платите сверх плана: напишите мне, я сделаю по одному городу в день в пределах бесплатной квоты."}]},
            {"id": "approve", "title": "Прослушайте и одобрите",
             "do": ["Прослушайте каждый файл целиком.",
                    "Напишите мне «одобряю демо: athens, rome …» — я положу файлы в static/mycast-share/audio/ и поставлю approved_by_owner: true в отдельном PR.",
                    "После мержа и обычного деплоя карточки начнут играть."],
             "check": "На странице выпуска у одобренных городов кнопка «Слухати» и звук играет; у остальных по-прежнему «Скоро».",
             "if": [{"when": "Карточка всё ещё «Скоро»", "then": "Проверьте, что деплой в Render Events — Live; если да, напишите мне название города."}]},
        ],
        "done": "Хотя бы Афины и Рим играют на mycast.pro/mycast/e/… с вашим одобрением в demos.json.",
    },
    {
        "id": "T-605",
        "title": "Добавить ключ Gemini API в Render",
        "why": "Нужен для живых голосов MyCast (Gemini озвучивает диалог двух ведущих) и для проверки подключения Gemini на сайте. Сам ключ ничего платного не включает.",
        "time": "≈10 минут",
        "steps": [
            {"id": "key", "title": "Создайте ключ в Google AI Studio",
             "do": ["Откройте aistudio.google.com и войдите своим Google-аккаунтом.",
                    "Слева Get API key → Create API key → выберите или создайте проект.",
                    "Ключ вида AIza… — это секрет. " + NO_SECRETS],
             "check": "Ключ создан и виден в списке ключей как активный.",
             "if": [{"when": "Google просит привязать карту или включить Billing", "then": "СТОП. Для бесплатного уровня карта не нужна. Не подключайте оплату — напишите мне, проверим бесплатный вариант."},
                    {"when": "Нет кнопки Create API key", "then": "Сначала создайте проект (Create project), потом повторите."}]},
            {"id": "render", "title": "Добавьте ключ в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_GEMINI_API_KEY, Value: ваш ключ (без пробелов и кавычек).",
                    "Не добавляйте и не меняйте FACTORY_VIDEO_ADAPTER: это включило бы платную генерацию видео.",
                    RENDER_SAVE],
             "check": "Статус этой карточки станет «Готово»: сервер видит ключ.",
             "if": [{"when": "Статус не меняется после деплоя", "then": "Сверьте имя переменной буква в букву и что деплой в Events — Live."},
                    {"when": "Деплой упал", "then": "Ключ тут ни при чём. Выделите текст ошибки и спросите меня."}]},
        ],
        "done": "Сервер видит FACTORY_GEMINI_API_KEY; ключ хранится только в Render.",
    },
    {
        "id": "T-606",
        "title": "Подключить Gemini (Jules) к GitHub",
        "why": "Gemini как программист работает на серверах Google и берёт задачи из GitHub. Ни наш сервер, ни ключ API ему для этого не нужны.",
        "time": "≈10 минут",
        "steps": [
            {"id": "install", "title": "Подключите Jules к репозиторию",
             "do": ["Откройте jules.google.com и войдите тем же Google-аккаунтом.",
                    "Нажмите Connect to GitHub и дайте доступ только к репозиторию blackboxlab-factoryos, а не ко всем.",
                    "Если GitHub спрашивает про права — подтвердите их для этого одного репозитория."],
             "check": "В Jules виден репозиторий blackboxlab-factoryos.",
             "if": [{"when": "Jules предлагает платный план", "then": "СТОП: нужен бесплатный уровень. Если он недоступен — напишите мне."},
                    {"when": "Репозитория нет в списке", "then": "GitHub → Settings → Applications → Jules → Configure → Repository access → добавьте blackboxlab-factoryos."}]},
            {"id": "first", "title": "Дайте первую задачу",
             "do": ["Откройте в GitHub задачу для Gemini (первая строка — Owner: Gemini; номера я пришлю).",
                    "Поставьте на неё метку jules (Labels → jules) или вставьте ссылку на задачу в Jules.",
                    "Jules покажет план — подтвердите его."],
             "check": "Jules открыл PR из ветки gemini/… — дальше проверяю и вливаю я.",
             "if": [{"when": "Jules хочет менять папку autopilot/ или файлы CI", "then": "Отклоните план и напишите мне: правила (AGENTS.md) это запрещают."},
                    {"when": "Jules просит ключ API или другой секрет", "then": "Не давайте: ему он не нужен. Спросите меня."}]},
        ],
        "done": "Jules подключён к репозиторию и открыл первый PR.",
    },
    {
        "id": "T-624",
        "title": "Отдельные MCP-токены для Claude и ChatGPT",
        "why": "Общий FACTORY_MCP_TOKEN не говорит серверу, кто пишет. Чтобы Claude и ChatGPT могли писать в общий тред и передавать друг другу задачи, у каждого нужен свой токен — тогда подделать автора нельзя.",
        "time": "≈15 минут",
        "steps": [
            {"id": "tokens", "title": "Создайте два разных токена",
             "do": ["В терминале выполните два раза: python -c \"import secrets;print(secrets.token_urlsafe(32))\" — получится два разных токена.",
                    "Первый — для Claude, второй — для ChatGPT. Не используйте FACTORY_MCP_TOKEN или пароль повторно.",
                    "Токен — это секрет. " + NO_SECRETS],
             "check": "У вас два разных токена длиной больше 32 символов.",
             "if": [{"when": "Нет Python на компьютере", "then": "Подойдёт любой генератор паролей: 40+ случайных букв и цифр, у каждого агента свой."}]},
            {"id": "render", "title": "Добавьте токены в Render",
             "do": [RENDER_ENV + ".",
                    "Key: FACTORY_MCP_LANE_TOKEN_CLAUDE, Value: первый токен. Key: FACTORY_MCP_LANE_TOKEN_CHATGPT, Value: второй токен.",
                    "Key: FACTORY_MCP_LANE_URL_KEY, Value: chatgpt (обычная настройка: коннектор ChatGPT не умеет передавать заголовки, поэтому его токен идёт в адресе).",
                    RENDER_SAVE],
             "check": "Worker Center → GET /api/factory/agent-workspace показывает lanes.claude.enabled и lanes.chatgpt.enabled = true.",
             "if": [{"when": "Там написано, почему дорожка выключена", "then": "Причина указана текстом (короткий, повторяется, совпадает с другим ключом) — создайте новый токен."}]},
            {"id": "connect", "title": "Переподключите ChatGPT и Claude",
             "do": ["ChatGPT → Settings → Connectors → коннектор FactoryOS → адрес https://blackboxlab-factoryos.onrender.com/mcp?key=<токен ChatGPT>.",
                    "Claude Code: claude mcp add --transport http factoryos https://blackboxlab-factoryos.onrender.com/mcp --header \"Authorization: Bearer <токен Claude>\".",
                    "Токен вставляйте только в настройки коннектора. " + NO_SECRETS],
             "check": "В ChatGPT видны инструменты post_message и list_handoffs, а запрос list_handoffs отвечает без LANE_AUTH_REQUIRED.",
             "if": [{"when": "Ответ LANE_AUTH_REQUIRED", "then": "Коннектор всё ещё использует общий FACTORY_MCP_TOKEN — замените адрес на токен ChatGPT."},
                    {"when": "Ответ 401", "then": "Проверьте, что FACTORY_MCP_LANE_URL_KEY = chatgpt и деплой в Events — Live."}]},
        ],
        "done": "У Claude и ChatGPT свои токены; сервер сам определяет, кто пишет.",
    },
    {
        "id": "T-607-H",
        "title": "Запустить Gemini-воркер на EC2",
        "why": "Gemini-воркер — третий программист: на EC2 он сам берёт задачи ROADMAP с Owner: gemini, запускает тесты и делает коммит. Работает только на бесплатном уровне Google.",
        "time": "≈20 минут",
        "steps": [
            {"id": "key", "title": "Ключ из отдельного проекта без биллинга",
             "do": ["AI Studio → Projects → Create project (например, factoryos-gemini-worker).",
                    "API Keys → Create API key в этом проекте. В колонке Billing Tier должно быть Free tier.",
                    "На этом проекте никогда не нажимайте Set up billing."],
             "check": "Ключ создан, его проект — Free tier.",
             "if": [{"when": "Вместо Free tier видно платный уровень", "then": "СТОП: этот ключ не годится. Создайте новый проект без биллинга."}]},
            {"id": "env", "title": "Файл настроек воркера",
             "do": ["На EC2 под ec2-user: mkdir -p ~/.config/factoryos && touch ~/.config/factoryos/gemini-worker.env && chmod 600 ~/.config/factoryos/gemini-worker.env",
                    "Откройте его: nano ~/.config/factoryos/gemini-worker.env (или vi).",
                    "Впишите строки FACTORYOS_URL=https://blackboxlab-factoryos.onrender.com, FACTORY_GEMINI_AUTH=api-key-free-tier, GEMINI_API_KEY=ваш ключ и FACTORY_GEMINI_WORKER_TOKEN=токен из шага Render. Токен и секрет живут только в этом файле и в Render — никогда не отправляйте их в чат, git или Telegram."],
             "check": "ls -l ~/.config/factoryos/gemini-worker.env показывает -rw------- и владельца ec2-user.",
             "if": [{"when": "No such file or directory", "then": "Сначала выполните команду mkdir/touch из первого пункта: файла ещё нет."}]},
            {"id": "render", "title": "Токен воркера в Render",
             "do": ["На EC2: python3 -c \"import secrets; print(secrets.token_urlsafe(36))\" — это токен воркера.",
                    "Render → сервис FactoryOS → Environment → добавьте FACTORY_GEMINI_WORKER_TOKEN с этим значением и сохраните. Тот же токен впишите в файл настроек. Это секрет: никогда не отправляйте его в чат."],
             "check": "Render задеплоил сервис (Events — Live).",
             "if": [{"when": "Деплой упал", "then": "Токен ни при чём. Выделите текст ошибки и спросите меня."}]},
            {"id": "service", "title": "Отдельная копия и служба",
             "do": ["git clone https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos ~/factoryos-gemini && cd ~/factoryos-gemini && git checkout -b autopilot/gemini-worker origin/main && git push -u origin autopilot/gemini-worker",
                    "sudo cp ~/factoryos-gemini/deploy/gemini-worker/factoryos-gemini-worker.service /etc/systemd/system/ && sudo systemctl daemon-reload && sudo systemctl enable --now factoryos-gemini-worker"],
             "check": "FactoryOS → Workers показывает Gemini онлайн; journalctl -u factoryos-gemini-worker -n 30 без ошибок.",
             "if": [{"when": "Refusing to start: GOOGLE_API_KEY is set", "then": "Уберите эту переменную из окружения: разрешён только GEMINI_API_KEY в файле настроек."},
                    {"when": "Воркер пишет про лимит (subscription_limit)", "then": "Это бесплатный лимит Google. Ничего не делайте: воркер подождёт и продолжит сам."}]},
        ],
        "done": "Gemini-воркер онлайн и взял пробную задачу T-607-P.",
    },
    {
        "id": "T-615-H",
        "title": "Запустить 48-часовую проверку MyBrief",
        "why": "Пилот MyBrief (#188) готов: 3 профессии, брифинги с реальными источниками, отзыв только с согласия. Узнать, нужен ли он людям, можно только показав ссылку живым людям — это рассылка, её решаете вы.",
        "time": "≈20 минут сейчас + 5 минут через 48 часов",
        "steps": [
            {"id": "review", "title": "Посмотрите страницу",
             "do": ["Откройте https://blackboxlab-factoryos.onrender.com/static/mybrief/index.html (вход не нужен).",
                    "Выберите профессию, нажмите «Показать брифинг» и откройте 2–3 ссылки на источники."],
             "check": "Каждый пункт ведёт на настоящую страницу GitHub, GOV.UK или IRS с той же датой.",
             "if": [{"when": "Ссылка не открывается или текст не совпадает", "then": "Не рассылайте. Напишите мне номер пункта — я заменю его."},
                    {"when": "Страница пишет «Не удалось загрузить демо-каталог»", "then": "Деплой ещё не дошёл. Подождите 10 минут и обновите страницу."}]},
            {"id": "share", "title": "Отправьте ссылку людям сами",
             "do": ["Выберите до 5 знакомых на каждую профессию: разработчик, учитель, бухгалтер.",
                    "Отправьте им ссылку лично (мессенджер, почта) с одной фразой: «Посмотри и оставь отзыв, если не жалко 2 минуты»."],
             "check": "Ссылка ушла хотя бы 3 людям по каждой профессии.",
             "if": [{"when": "Хочется разослать широко или опубликовать в соцсетях", "then": "Сначала напишите мне: публичный запуск — отдельное решение, лимит отзывов 300 в день."}]},
            {"id": "result", "title": "Через 48 часов посмотрите итог",
             "do": ["Войдите в FactoryOS и откройте https://blackboxlab-factoryos.onrender.com/api/mybrief/feedback.",
                    "Посмотрите число отзывов, среднюю оценку и ответы «читал бы каждую неделю»."],
             "check": "Напишите мне «MyBrief: N отзывов, оценка X» — я запишу событие в MVP Builder, а решение validated/rejected остаётся за вами.",
             "if": [{"when": "Отзывов нет совсем", "then": "Это тоже результат. Напишите мне — предложу другой текст приглашения или другие профессии."}]},
        ],
        "done": "Ссылку получили реальные люди, через 48 часов есть итог по отзывам и ваше решение по пилоту.",
    },
    {
        "id": "T-598-H1",
        "title": "Право workflow для GitHub-токена воркера (рекомендую)",
        "why": "Воркер дважды (30.10 и 01.11) часами стоял, потому что его коммит менял CI-файл, а GitHub не пускает такой push без права workflow. С этим правом он не застревает. Слияние в main по-прежнему только с вашего согласия.",
        "time": "≈3 минуты",
        "steps": [
            {"id": "connect", "title": "Откройте терминал на сервере",
             "do": ["AWS Console → EC2 → Instances → ваш инстанс → кнопка Connect → вкладка Session Manager → Connect."],
             "check": "Открылся чёрный терминал с приглашением вида sh-5.2$.",
             "if": [{"when": "Кнопка Connect серая или «SSM Agent is not online»", "then": "Подождите 1–2 минуты и обновите страницу. Если не помогло — спросите меня по этому шагу."}]},
            {"id": "refresh", "title": "Добавьте право workflow",
             "do": ["Вставьте и выполните: sudo -u ec2-user gh auth refresh -h github.com -s workflow",
                    "Команда покажет одноразовый код из 8 символов и адрес github.com/login/device.",
                    "Откройте этот адрес в браузере, где вы вошли в GitHub как Pavlovskyi-Andrii, введите код и нажмите Authorize."],
             "check": "В терминале появится «✓ Authentication complete».",
             "if": [{"when": "«not logged in to any hosts»", "then": "У воркера нет входа через gh. Ничего не делайте дальше и спросите меня: значит, он пушит другим способом."},
                    {"when": "Код истёк или «expired_token»", "then": "Запустите команду ещё раз и введите новый код быстрее (он живёт 15 минут)."},
                    {"when": "Браузер просит войти в другой аккаунт", "then": "Выйдите и войдите как Pavlovskyi-Andrii — именно его токен использует воркер."}]},
            {"id": "verify", "title": "Проверьте",
             "do": ["Выполните: sudo -u ec2-user gh auth status"],
             "check": "В строке Token scopes есть 'workflow'. Напишите мне «H1 готово».",
             "if": [{"when": "workflow в списке нет", "then": "Повторите шаг «Добавьте право workflow»: авторизация в браузере не была подтверждена."}]},
        ],
        "done": "Push воркера с изменением .github/workflows принимается GitHub.",
    },
    {
        "id": "T-598-H2",
        "title": "Право ec2:DescribeInstances для роли сервера (пока не нужно)",
        "why": "Код, который читает это право, ещё не написан: статус «EC2 API» в Worker Center сейчас всегда «неизвестно». Выдавать право сейчас бесполезно.",
        "time": "≈5 минут",
        "optional": True,
        "steps": [
            {"id": "later", "title": "Отложено",
             "do": ["Ничего не делайте. Когда появится код, использующий это право, я обновлю этот шаг готовой инструкцией для IAM."],
             "check": "—",
             "if": []},
        ],
        "done": "Worker Center показывает реальное состояние инстанса.",
    },
    {
        "id": "T-614-H1",
        "title": "Decision Memory (#187): посмотреть превью, провести 5 интервью, принять решение",
        "why": "Пилот собран: решения FactoryOS из DECISIONS.md с обоснованием и ссылками, поля «ответственный», «ожидаемый итог» и «ревью». Дальше нужны вы: агент не может сам двигать пилот дальше ревью ТЗ, а писать людям для интервью — внешний контакт.",
        "time": "≈30 минут на превью + 5 интервью по 30 минут",
        "steps": [
            {"id": "preview", "title": "Откройте превью",
             "do": ["Войдите в FactoryOS как владелец и откройте /static/decision-memory/index.html.",
                    "Посмотрите на плитки вверху: сколько решений без ответственного и без ожидаемого итога."],
             "check": "Видны реальные решения из DECISIONS.md со ссылками на строки файла.",
             "if": [{"when": "Страница пишет «Нужно войти»", "then": "Войдите через /login и откройте страницу снова."},
                    {"when": "Страница пишет «Не удалось загрузить данные»", "then": "Напишите мне: проверю журнал сервиса."}]},
            {"id": "fill", "title": "Заполните 3–5 решений по-настоящему",
             "do": ["Выберите несколько решений, итог которых вы уже знаете или хотите проверить.",
                    "Кнопка «Заполнить поля»: ответственный, ожидаемый итог, дата ревью.",
                    "Для уже понятного решения нажмите «Записать ревью» и выберите итог."],
             "check": "Плитка «ревью пора провести» или «без ожидаемого итога» изменилась; после перезагрузки страницы данные на месте.",
             "if": [{"when": "Ошибка «Текст похож на секрет»", "then": "Уберите из текста ключи и пароли: такие данные сюда не сохраняются."}]},
            {"id": "interviews", "title": "Проведите 5 интервью",
             "do": ["Откройте скрипт docs/mvp/decision-memory/INTERVIEW_SCRIPT.md (ссылка внизу страницы).",
                    "Сами напишите 5 людям, которые регулярно принимают решения в команде, и договоритесь о 30 минутах. FactoryOS никому не пишет.",
                    "Заметки храните у себя, не в репозитории: он публичный."],
             "check": "Есть 5 заметок со шкалой оценки из конца скрипта.",
             "if": [{"when": "Не удаётся найти 5 человек", "then": "Проведите сколько получилось и отметьте это в итоговом событии."}]},
            {"id": "decide", "title": "Запишите решение в MVP Builder",
             "do": ["Откройте MVP Builder → проект «AI Decision Memory».",
                    "Проведите стадии build_queued → building → qa_review → preview_ready → owner_review событиями со ссылками на PR и превью.",
                    "Последним шагом выберите validated или rejected и в комментарии укажите сводку интервью (без имён)."],
             "check": "Проект в MVP Builder в статусе validated или rejected с вашим событием.",
             "if": [{"when": "Кнопка «Продвинуть» отказывает", "then": "Нужна ссылка-доказательство: GitHub PR/issue или /static/…; вставьте её в поле."}]},
        ],
        "done": "Пилот decision-memory в MVP Builder закрыт вашим решением validated или rejected со сводкой интервью.",
    },
    {
        "id": "T-630-H",
        "title": "Product Evolution (#270): первая когорта из 10 отзывов и первое решение по V2",
        "why": "Цикл улучшения MVP готов: отзывы только с согласия → темы → предложение V2 → ваше одобрение → одна задача Builder в Relay → выпуск → повторная проверка. Писать людям и одобрять изменения продукта — ваше решение; агент не рассылает приглашения и не одобряет предложения сам.",
        "time": "≈20 минут на подготовку + 10 разговоров по 15–30 минут + 10 минут на решение",
        "steps": [
            {"id": "channel", "title": "Выберите пилот и канал",
             "do": ["Откройте MVP Builder → карточка пилота (например «MyBrief for a profession») → кнопка «Product Evolution · V1→V2».",
                    "Нажмите «Синтетический демо-цикл» и посмотрите, как выглядит весь цикл на выдуманных данных (они помечены и нигде не считаются).",
                    "Решите сами, каким каналом зовёте людей (личное сообщение, почта) и какой фразой просите согласие хранить ответы."],
             "check": "Вы знаете пилот, канал и фразу согласия; демо показывает плашку «СИНТЕТИЧЕСКОЕ ДЕМО».",
             "if": [{"when": "Хочется разослать приглашения массово или опубликовать", "then": "Сначала напишите мне: массовая рассылка и публикация — отдельное решение, здесь не включены."}]},
            {"id": "collect", "title": "Соберите 10 содержательных отзывов",
             "do": ["Поговорите с людьми сами. Без наводящих вопросов: пробовал ли, какую задачу хотел решить, что помогло, что не вышло, что добавить или убрать, важность, заплатил бы и за какой период.",
                    "После каждого разговора: «Добавить отзыв», метка участника (например P1 — сама метка не хранится), галочка согласия, где дано согласие, ответы и 1–3 тега темы.",
                    "Для MyBrief можно нажать «Импортировать отзывы MyBrief с согласием» — они посчитаются как отзывы, но не как содержательные."],
             "check": "Плитка «Уникальные содержательные отзывы (реальные)» показывает 10 / 10.",
             "if": [{"when": "Человек отозвал согласие", "then": "Нажмите у его записи «Удалить (согласие отозвано)» — запись удаляется навсегда."},
                    {"when": "Набралось меньше 10 за неделю", "then": "Это тоже результат: темы будут с уверенностью «недостаточно/низкая». Напишите мне — предложу другой сегмент."}]},
            {"id": "decide", "title": "Решите по первому предложению V2",
             "do": ["Посмотрите блок «Темы отзывов»: «за», «против», выборку и уверенность. Большинство — сигнал, а не приказ.",
                    "Если предложение уже есть — «Одобрить (владелец)» или «Отклонить (владелец)». Если нет — «Предложить улучшение» с id отзывов и тестом приёмки.",
                    "После одобрения нажмите «Передать Builder»: появится ровно одна задача в Relay (по умолчанию Claude)."],
             "check": "В трассировке предложения видно Relay R-…; статус VERIFIED появится только когда задача закрыта с run_id и проверенными доказательствами.",
             "if": [{"when": "Кнопка «Одобрить» отвечает owner_only", "then": "Войдите как владелец: участник команды не может одобрять."}]},
            {"id": "retest", "title": "Выпустите V2 и спросите тех же людей",
             "do": ["Когда PR смержен, нажмите «Отметить выпущенным» и вставьте ссылку на PR.",
                    "В «Выпустить следующую версию» вставьте ссылку на PR или запуск Actions — версия станет v2 (это не публичный релиз).",
                    "Спросите исходных участников, решило ли изменение их задачу, и запишите отзыв с «Проверка выпущенного предложения»."],
             "check": "В трассировке «Повторная проверка» есть ответы исходных участников (решено / частично / нет).",
             "if": [{"when": "«Выпустить» отвечает nothing_shipped", "then": "Сначала отметьте предложение выпущенным со ссылкой на смерженный PR."}]},
        ],
        "done": "У пилота 10 реальных содержательных отзывов, ваше решение по первому предложению V2 и, после выпуска, ответы исходных участников.",
    },
    {
        "id": "T-591-H",
        "title": "Живая приёмка Telegram: одна тестовая задача от начала до конца",
        "why": "Последний шаг T-590, T-591 и T-591-A: код и тесты готовы, но DONE требует настоящего прогона в вашем чате. Написать боту можете только вы, а подтвердить, что всё реально произошло, — только сервер.",
        "time": "≈15 минут (в основном ожидание воркера)",
        "steps": [
            {"id": "prep", "title": "Проверьте, что прод и воркер живы",
             "do": ["Откройте https://blackboxlab-factoryos.onrender.com/health — должна открыться страница со статусом ok, а не ошибка 502.",
                    "В Telegram отправьте боту /status.",
                    "В ответе найдите строку Claude: нужен 🟢 онлайн и свежий сигнал (секунды или минуты назад)."],
             "check": "Сайт отвечает, Claude онлайн.",
             "if": [{"when": "Сайт отвечает 502 или долго грузится", "then": "Render просыпается или идёт деплой. Подождите 5 минут и откройте снова; если в Render → Events деплой Failed — задайте мне вопрос по этому шагу."},
                    {"when": "У Claude ⚪ офлайн или 🟡 сигнал просрочен", "then": "Воркер на EC2 не запущен или завис. Не перезапускайте сами: задайте мне вопрос по этому шагу, я пришлю точную команду проверки."},
                    {"when": "Бот вообще не отвечает", "then": "Чат отвязан. Пройдите заново T-506 (кнопка «Начать привязку»)."}]},
            {"id": "send", "title": "Отправьте тестовую задачу",
             "do": ["Отправьте боту обычное сообщение (без /new): T-591 приёмка: ответь текущим UTC-временем и первой открытой задачей ROADMAP, код не меняй.",
                    "Бот ответит «Создал тикет» с номером вида R-0123. Запишите номер."],
             "check": "Пришла карточка тикета «В очереди», а не «работает»: выполнение ещё не началось.",
             "if": [{"when": "Бот прислал «Выбери исполнителя»", "then": "Вы отправили через /new. Нажмите кнопку Claude под сообщением."},
                    {"when": "На одно сообщение пришло два тикета", "then": "Это ошибка дедупликации. Не продолжайте: задайте вопрос по этому шагу и укажите оба номера."}]},
            {"id": "wait", "title": "Дождитесь, пока воркер возьмёт и выполнит задачу",
             "do": ["Ничего не нажимайте. Обычно за 1–10 минут придут уведомления «⚙️ работает над задачей», затем «🏁 закончил работу».",
                    "В любой момент можно нажать 🔄 Обновить под карточкой: там этапы со временем в UTC и run_id."],
             "check": "Пришло уведомление «🏁 закончил работу» с ответом воркера.",
             "if": [{"when": "Через 15 минут всё ещё «В очереди»", "then": "Воркер не берёт задачи. Отправьте /workers и задайте мне вопрос по этому шагу, приложив ответ."},
                    {"when": "Пришло «🙋 нужна твоя помощь» или «❌ ошибка выполнения»", "then": "Прочитайте причину в уведомлении. Нажмите ↻ Retry один раз; если повторилось — задайте вопрос по этому шагу."},
                    {"when": "Карточка показывает «⚠️ Worker без связи»", "then": "Воркер пропал во время работы. Сервер сам задачу не перезапускает: нажмите ↻ Retry, когда /workers снова покажет Claude онлайн."}]},
            {"id": "proof", "title": "Проверьте приёмку по фактам сервера",
             "do": ["Отправьте боту /proof R-0123 (ваш номер).",
                    "Или на сайте под своим входом владельца откройте /api/relay/R-0123/acceptance."],
             "check": "В ответе «✅ ПОДТВЕРЖДЕНО сервером» и галочки у всех строк: сообщение из привязанного чата, ровно один тикет, claim с run_id, running, done, итог воркера, уведомление доставлено.",
             "if": [{"when": "«❔ НЕ подтверждено» и ⏳ у строки «уведомление доставлено»", "then": "Сервер не получил подтверждения от Telegram. Проверьте, что сообщение «🏁» действительно пришло, и задайте вопрос по этому шагу."},
                    {"when": "Ошибка 403 на сайте", "then": "Вы вошли не как владелец. Выйдите и войдите основным аккаунтом."}]},
            {"id": "report", "title": "Сохраните доказательство",
             "do": ["Скопируйте весь ответ /proof: в нём только номера, run_id и время в UTC.",
                    "Вставьте его комментарием в GitHub Issue #41 или напишите мне «T-591 приёмка R-0123 подтверждена» — я сверю по серверу и закрою T-590, T-591 и T-591-A."],
             "check": "Отчёт приёмки есть в Issue #41 или у меня.",
             "if": [{"when": "Нет доступа к GitHub с телефона", "then": "Достаточно написать мне номер тикета: вердикт сервера я прочитаю сам."}]},
        ],
        "done": "/proof по тестовой задаче показывает «ПОДТВЕРЖДЕНО сервером», отчёт приложен к Issue #41.",
    },
    {
        "id": "T-592-H",
        "title": "Сверить Telegram и сайт по одной задаче (скриншоты)",
        "why": "T-592 требует доказательства глазами: одна и та же задача и этап в Telegram и на сайте, без «призрачного running», на телефоне и компьютере. Автотесты это проверяют, а скриншот вашего настоящего Telegram может сделать только владелец.",
        "time": "≈10 минут",
        "steps": [
            {"id": "same", "title": "Сравните одну задачу в двух местах",
             "do": ["Возьмите тикет из T-591-H (или любой свежий) и в Telegram нажмите 🔄 Обновить под его карточкой.",
                    "На сайте откройте /relay и ту же задачу, затем Worker Center → строка Claude."],
             "check": "Этап (например done), run_id и время последней связи совпадают.",
             "if": [{"when": "На сайте этап новее, чем в Telegram", "then": "Нажмите 🔄 Обновить ещё раз: Telegram показывает снимок на момент сообщения."},
                    {"when": "Сайт показывает «работает», а /workers — простаивает", "then": "Это и есть «призрачный running». Сделайте скриншоты обоих экранов и задайте мне вопрос по этому шагу."}]},
            {"id": "screens", "title": "Сделайте 4 скриншота",
             "do": ["Телефон: Telegram с карточкой тикета и сайт Worker Center.",
                    "Компьютер: сайт /relay с этой задачей и Worker Center.",
                    "Проверьте, что колонки Planned / In Progress / Completed / Blocked в Build Progress видны целиком, без горизонтальной прокрутки."],
             "check": "4 скриншота, на всех одна и та же задача и этап.",
             "if": [{"when": "Колонки обрезаны или есть горизонтальная прокрутка", "then": "Приложите этот скриншот: это ошибка T-592, я исправлю."}]},
            {"id": "report", "title": "Передайте скриншоты",
             "do": ["Закройте на скриншотах номер чата и имена, если они видны, приложите их к Issue #56 и напишите мне «T-592 скриншоты готовы»."],
             "check": "Скриншоты в Issue #56.",
             "if": [{"when": "Не хотите выкладывать в публичный репозиторий", "then": "Напишите мне, совпало ли всё; закрою T-592 по вашему подтверждению с пометкой, что скриншоты у владельца."}]},
        ],
        "done": "Одна задача показывает одинаковый этап в Telegram и на сайте на телефоне и компьютере; скриншоты приложены.",
    },
    {
        "id": "T-593-H",
        "title": "Подтвердить, что воркер сам переходит к следующей безопасной задаче",
        "why": "T-593 закрывается только на живом EC2: после проверенного коммита воркер сам берёт следующую безопасную задачу ROADMAP, не пушит в main и не тратит платные API. Код и тесты на это есть; живую очередь и счета видите только вы.",
        "time": "≈5 минут, затем проверка через сутки",
        "steps": [
            {"id": "ci", "title": "Проверьте, что main зелёный",
             "do": ["Откройте github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/actions?query=branch%3Amain.",
                    "Посмотрите последний запуск CI на main."],
             "check": "Последний запуск зелёный (✓).",
             "if": [{"when": "Красный (✗)", "then": "Не чините сами. Задайте мне вопрос по этому шагу со ссылкой на запуск."}]},
            {"id": "next", "title": "Посмотрите, что воркер взял следующую задачу",
             "do": ["В Telegram отправьте /workers, на сайте откройте Worker Center.",
                    "Найдите у Claude последний результат (задача и коммит) и текущую задачу."],
             "check": "После последнего результата done воркер взял следующую задачу ROADMAP (видно «работает над T-…» или новый claim в /history), а не повторяет ту же.",
             "if": [{"when": "Воркер простаивает, а /roadmap показывает открытые задачи агентов", "then": "Возможно, все они ждут Depends/HUMAN или заняты другой сессией. Задайте вопрос по этому шагу — я проверю очередь."},
                    {"when": "Одна и та же задача берётся снова и снова", "then": "Это зацикливание. Задайте вопрос по этому шагу и приложите ответ /history."}]},
            {"id": "safety", "title": "Через сутки проверьте безопасность",
             "do": ["Откройте github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/commits/main: каждый коммит должен прийти через PR (в названии номер #…).",
                    "Проверьте счета Anthropic, OpenAI и Google Cloud: новых платных списаний от FactoryOS нет."],
             "check": "Прямых пушей в main нет, новых платных расходов нет.",
             "if": [{"when": "В main есть коммит без PR", "then": "Сразу напишите мне его хеш: это нарушение правил, разберу."},
                    {"when": "Появилось платное списание", "then": "Напишите мне сумму и сервис. Ключи и пароли не присылайте."}]},
        ],
        "done": "Воркер сам перешёл к следующей безопасной задаче после проверенного коммита; main зелёный; прямых пушей и платных расходов нет.",
    },
]
RUNBOOK_BY_ID = {r["id"]: r for r in RUNBOOKS}


RUNBOOK_LANGS = ("ru", "en", "uk")


def localize_runbook(runbook: dict[str, Any], lang: str) -> dict[str, Any]:
    """The runbook in `lang`; the Russian source is the fallback for anything not translated."""
    tr = (RUNBOOK_I18N.get(lang) or {}).get(runbook["id"])
    if not tr:
        return {**runbook, "lang": "ru"}
    steps = []
    for step in runbook.get("steps") or []:
        st = (tr.get("steps") or {}).get(step["id"]) or {}
        steps.append({**step, **{k: st[k] for k in ("title", "do", "check", "if") if k in st}})
    return {**runbook, **{k: tr[k] for k in ("title", "why", "time", "done") if k in tr}, "steps": steps, "lang": lang}


def status_detail(status: dict[str, Any], lang: str) -> dict[str, Any]:
    """Live status with its line in `lang`: status_fn gives `detail_key` + `args`, or a plain `detail`."""
    key = status.get("detail_key")
    if not key:
        return status
    table = STATUS_DETAILS.get(lang) or STATUS_DETAILS["ru"]
    template = table.get(key) or STATUS_DETAILS["ru"].get(key) or ""
    try:
        detail = template.format(**(status.get("args") or {}))
    except (KeyError, IndexError, ValueError):
        detail = template
    return {k: v for k, v in status.items() if k not in ("detail_key", "args")} | {"detail": detail}


def runbook_text(runbook: dict[str, Any]) -> str:
    """Plain-text rendering for the worker prompt."""
    lines = [f"{runbook['id']} — {runbook['title']}", runbook.get("why", "")]
    for n, step in enumerate(runbook.get("steps") or [], 1):
        lines.append(f"Шаг {n} [{step['id']}]: {step['title']}")
        lines += [f"  - {d}" for d in step.get("do") or []]
        lines.append(f"  Проверка: {step.get('check', '')}")
        lines += [f"  Если «{b['when']}» → {b['then']}" for b in step.get("if") or []]
    lines.append("Готово, когда: " + runbook.get("done", ""))
    return "\n".join(lines)


_SECRET_PATTERNS = (
    re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"),            # Telegram bot token
    re.compile(r"\bsk-ant-[A-Za-z0-9_-]{8,}"),                 # Anthropic key
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"), # GitHub token
    re.compile(r"\bAIza[A-Za-z0-9_-]{20,}\b"),                 # Google API key
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),              # AWS access key id
    re.compile(r"(?i)\b(bearer)(\s+)[A-Za-z0-9_.~+/-]{8,}"),    # Bearer header
    re.compile(r"(?i)\b(token|secret|password|api[_-]?key)(\s*[:=]\s*)\S{8,}"),
)


def scrub_secrets(text: str) -> str:
    """Owners paste things; a secret the server does not know yet must still never be stored."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) + m.group(2) if m.lastindex and m.lastindex >= 2 else "") + "[скрыто]", text)
    return text


def _clean(text: Any, limit: int) -> str:
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", str(text or ""))
    return scrub_secrets(text).strip()[:limit]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class QuestionStore:
    """Small JSON-file queue. One process (the web app) writes it; the lock covers its threads."""

    def __init__(self, path: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [q for q in value if isinstance(q, dict)] if isinstance(value, list) else []

    def _save(self, items: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-MAX_KEPT_QUESTIONS:], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def _expire_leases(self, items: list[dict[str, Any]]) -> None:
        now = self.clock()
        for q in items:
            if q.get("status") == "answering" and now - float(q.get("claimed_ts") or 0) > CLAIM_LEASE_SECONDS:
                q["status"] = "pending"
                q.pop("claimed_ts", None)
                q.pop("worker_id", None)

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            items = self._load()
            self._expire_leases(items)
        owner_items = [q for q in items if q.get("task_id") not in (SELFTEST_TASK, TELEGRAM_TASK)]
        return [{k: v for k, v in q.items() if k != "claimed_ts"} for q in owner_items[-limit:]]

    def queue_stats(self) -> dict[str, Any]:
        """Open owner questions and the age of the oldest one (seconds)."""
        now = self.clock()
        with self._lock:
            items = self._load()
            self._expire_leases(items)
        open_items = [q for q in items if q.get("task_id") != SELFTEST_TASK and q.get("status") in ("pending", "answering")]
        ages = []
        for q in open_items:
            try:
                ages.append(now - datetime.fromisoformat(str(q.get("created_at"))).timestamp())
            except ValueError:
                pass
        oldest = max(ages) if ages else 0.0
        stale = [q.get("task_id") for q, age in zip(open_items, ages) if age > STALE_QUESTION_SECONDS]
        return {"open": len(open_items), "oldest_seconds": oldest, "stale_tasks": stale}

    def create(self, task_id: str, step_id: str, quote: str, question: str, source_key: str = "",
               meta: Optional[dict] = None) -> dict[str, Any]:
        if task_id not in RUNBOOK_BY_ID and task_id not in (SELFTEST_TASK, TELEGRAM_TASK):
            raise ValueError("unknown task")
        quote, question = _clean(quote, QUOTE_MAX), _clean(question, QUESTION_MAX)
        if not question:
            raise ValueError("empty question")
        steps = {s["id"] for s in RUNBOOK_BY_ID[task_id]["steps"]} if task_id in RUNBOOK_BY_ID else set()
        step_id = step_id if step_id in steps else ""
        with self._lock:
            items = self._load()
            self._expire_leases(items)
            if source_key:
                existing = next((q for q in items if q.get("source_key") == source_key), None)
                if existing:
                    return existing
            if task_id == SELFTEST_TASK and any(q.get("task_id") == SELFTEST_TASK and q.get("status") in ("pending", "answering") for q in items):
                raise OverflowError("a self-test is already in flight")
            if sum(1 for q in items if q.get("status") in ("pending", "answering")) >= MAX_OPEN_QUESTIONS:
                raise OverflowError("too many open questions")
            item = {"id": "Q-" + secrets.token_hex(4), "task_id": task_id, "step_id": step_id, "quote": quote,
                    "question": question, "status": "pending", "created_at": _now_iso(), "answer": ""}
            if source_key:
                item["source_key"] = _clean(source_key, 120)
            if meta and isinstance(meta, dict):  # #129: where the answer goes back (a Telegram group thread id)
                item["meta"] = {str(k)[:40]: _clean(str(v), 80) for k, v in list(meta.items())[:5]}
            items.append(item)
            self._save(items)
        return item

    def claim(self, worker_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            items = self._load()
            self._expire_leases(items)
            for q in items:
                if q.get("status") == "pending":
                    q.update(status="answering", claimed_ts=self.clock(), worker_id=_clean(worker_id, 80))
                    self._save(items)
                    return {k: v for k, v in q.items() if k != "claimed_ts"}
            self._save(items)
        return None

    def finish(self, qid: str, outcome: str, answer: str) -> dict[str, Any]:
        """outcome: answered | failed | requeue (worker could not run, e.g. subscription limit)."""
        if outcome not in ("answered", "failed", "requeue"):
            raise ValueError("bad outcome")
        with self._lock:
            items = self._load()
            for q in items:
                if q.get("id") != qid:
                    continue
                if q.get("status") != "answering":
                    raise LookupError("question is not being answered")
                q.pop("claimed_ts", None)
                if outcome == "requeue":
                    q["status"] = "pending"
                    q.pop("worker_id", None)
                else:
                    q.update(status=outcome, answer=_clean(answer, ANSWER_MAX), answered_at=_now_iso())
                self._save(items)
                return q
        raise LookupError("unknown question")


class OwnerQuestionRequest(BaseModel):
    task_id: str
    step_id: str = ""
    quote: str = ""
    question: str


class WorkerClaimRequest(BaseModel):
    worker_id: str = ""


class WorkerAnswerRequest(BaseModel):
    id: str
    outcome: str
    answer: str = ""


def install_owner_desk_routes(app, store: QuestionStore, identity_fn: Callable[[Request], Any], *,
                              authorize_worker: Callable[[Request], bool],
                              status_fn: Callable[[], dict[str, dict[str, str]]],
                              redact_fn: Callable[[str], str] = lambda s: s,
                              notify_owner: Optional[Callable[[str], Any]] = None,
                              route_answer: Optional[Callable[[dict], bool]] = None) -> None:
    def require_owner(request: Request) -> None:
        if (identity_fn(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    def require_worker(request: Request) -> None:
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")

    @app.get("/api/factory/owner-desk")
    def owner_desk(request: Request, lang: str = "ru"):
        require_owner(request)
        lang = lang if lang in RUNBOOK_LANGS else "ru"
        try:
            status = status_fn() or {}
        except Exception:
            status = {}
        books = [{**localize_runbook(r, lang), "status": status_detail(status.get(r["id"]) or {"state": "unknown", "detail": ""}, lang)}
                 for r in RUNBOOKS]
        return {"runbooks": books, "lang": lang, "questions": store.list(), "answer_mode": "worker_between_tasks"}

    @app.post("/api/factory/owner-desk/questions")
    def owner_desk_ask(payload: OwnerQuestionRequest, request: Request):
        require_owner(request)
        try:
            item = store.create(payload.task_id, payload.step_id, redact_fn(payload.quote), redact_fn(payload.question))
        except OverflowError:
            raise HTTPException(429, "Too many unanswered questions; wait for answers first")
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return {"ok": True, "question": item}

    @app.post("/api/factory/owner-desk/worker/selftest")
    def owner_desk_selftest(request: Request):
        require_worker(request)
        try:
            item = store.create(SELFTEST_TASK, "", "", "round-trip self-test")
        except OverflowError:
            return {"ok": True, "queued": False, "reason": "already in flight"}
        return {"ok": True, "queued": True, "id": item["id"]}

    @app.post("/api/factory/owner-desk/worker/claim")
    def owner_desk_claim(payload: WorkerClaimRequest, request: Request):
        require_worker(request)
        item = store.claim(payload.worker_id)
        if not item:
            return {"question": None}
        book = RUNBOOK_BY_ID.get(item["task_id"]) or {}
        return {"question": item, "runbook_text": runbook_text(book) if book else ""}

    @app.post("/api/factory/owner-desk/worker/answer")
    def owner_desk_answer(payload: WorkerAnswerRequest, request: Request):
        require_worker(request)
        try:
            item = store.finish(payload.id, payload.outcome, redact_fn(payload.answer))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except LookupError as exc:
            raise HTTPException(409, str(exc))
        if route_answer and item.get("status") == "answered":
            try:
                if route_answer(item):  # #129: a group-thread answer is posted to the group, not the private chat
                    return {"ok": True, "status": item.get("status")}
            except Exception:
                pass
        if notify_owner and item.get("status") == "answered":
            try:
                if item.get("task_id") == TELEGRAM_TASK:
                    answer = str(item.get("answer") or "") or "Claude вернул пустой ответ."
                    parts = [answer[i:i + 3800] for i in range(0, len(answer), 3800)]
                    for n, part in enumerate(parts, 1):
                        notify_owner(f"💬 Claude · ответ на {item['id']} ({n}/{len(parts)})\n{part}")
                else:
                    notify_owner(selftest_message(store.queue_stats()) if item.get("task_id") == SELFTEST_TASK else
                                 f"💬 Ответ на ваш вопрос по {item['task_id']} готов: Worker Center → «Ваши задачи».")
            except Exception:
                pass
        return {"ok": True, "status": item.get("status")}


def selftest_message(stats: dict[str, Any]) -> str:
    text = "✅ Круговая проверка: сайт → воркер → ответ → Telegram работают."
    if stats.get("open"):
        text += f" Ваших вопросов в очереди: {stats['open']}, самый старый ждёт {int(stats.get('oldest_seconds', 0) // 60)} мин."
    else:
        text += " Ваших вопросов в очереди нет."
    if stats.get("stale_tasks"):
        text += " ⚠️ Дольше часа без ответа: " + ", ".join(sorted(set(stats["stale_tasks"]))) + "."
    return text
