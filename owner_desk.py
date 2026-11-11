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
        "id": "T-520",
        "title": "Подключить первый реальный публикатор (Metricool)",
        "why": "Сейчас публикация работает только в ручном режиме. Metricool уже подключён к YouTube/TikTok/Instagram; FactoryOS нужен серверный доступ к нему.",
        "time": "≈20 минут",
        "steps": [
            {"id": "plan", "title": "Проверьте тариф и доступ к Metricool API",
             "do": ["В веб-кабинете Metricool откройте меню ☰ → Account settings → Plans and billing. Узнайте текущий тариф.",
                    "Только Advanced и Custom дают доступ к REST API; Free и Starter, даже с подключённым Metricool MCP, его не дают.",
                    "Если тариф подходит, откройте Account settings → API → Access token. Никому не пересылайте токен."],
             "check": "Тариф Advanced/Custom подтверждён в Plans and billing, вкладка API и поле Access token доступны.",
             "if": [{"when": "Тариф Free/Starter, вкладки API нет или предлагается Upgrade", "then": "СТОП: не покупать и не менять тариф. Сообщите, что API платный. Публиковать пока только вручную после отдельного одобрения; MCP не равен серверному API."}]},
            {"id": "ids", "title": "Найдите userId, blogId и секретный API-токен",
             "do": ["API access token (userToken) находится в Account settings → API → Access token. Это секрет. " + NO_SECRETS,
                    "Откройте в веб-кабинете бренд blackboxlab7. В URL найдите оба параметра: userId=… (пользователь) и blogId=… (бренд).",
                    "Не путайте userId, blogId и access token; не размещайте токен в тикетах/чатах/PR."],
             "check": "Оба числовых ID видны в URL выбранного бренда, а отдельный токен доступен только в защищённом разделе API.",
             "if": [{"when": "В URL нет userId или blogId", "then": "Откройте бренд в полной веб-версии Metricool, переключитесь на него в списке и проверьте адрес ещё раз; при отсутствии не угадывайте ID."}]},
            {"id": "render", "title": "Добавьте переменные в Render",
             "do": [RENDER_ENV + " — добавьте по одной:",
                    "FACTORY_PUBLISHER_ADAPTER = metricool",
                    "FACTORY_METRICOOL_TOKEN = ваш userToken",
                    "FACTORY_METRICOOL_USER_ID = ваш userId",
                    "FACTORY_METRICOOL_BLOG_ID = ваш blogId",
                    "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS = false (если ваш контент не для детей; иначе true)",
                    "FACTORY_PUBLISHER_SCHEDULER_ENABLED не трогайте: автопубликация остаётся выключенной, каждый пост одобряете вы.",
                    RENDER_SAVE],
             "check": "Статус этой карточки станет «Готово» (сервер видит адаптер metricool как настроенный).",
             "if": [{"when": "Статус «metricool выбран, но не настроен»", "then": "Не хватает одной из трёх переменных TOKEN / USER_ID / BLOG_ID или в имени опечатка. Сверьте имена буква в букву."},
                    {"when": "Статус «выбран manual»", "then": "Не добавлена FACTORY_PUBLISHER_ADAPTER=metricool или деплой ещё не закончился."},
                    {"when": "Предупреждение про YouTube audience", "then": "Добавьте FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS со значением false или true."}]},
        ],
        "done": "Карточка показывает «Готово»: FactoryOS видит настроенный адаптер Metricool (без показа секретов).",
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
                    {"when": "Ошибка от Metricool", "then": "Ничего не повторяйте вслепую, чтобы не было дубля. Выделите текст ошибки и спросите меня."}]},
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
             "do": ["Для каждого приложения провайдер требует точный адрес возврата (redirect URL). Его создаёт задача T-552, которая ещё не сделана.",
                    "Когда T-552 будет готова, я заменю этот шаг пошаговыми инструкциями по каждому провайдеру с готовыми адресами."],
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
        "id": "D-240",
        "covers": [240, 241, 242],  # these Issues link to this card on the Team tasks page
        "title": "Решить, брать ли задачи #240, #241, #242",
        "why": "Три технические задачи Claude ждут не работы, а формальных зависимостей: #240 — эпик MVP Factory #186, #241 — эпик Relay/Telegram #41, #242 — задачи Gemini #202 и #203. Эпики открыты неделями, поэтому без вашего решения эти задачи так и будут висеть.",
        "time": "≈3 минуты",
        "steps": [
            {"id": "read", "title": "Посмотрите, что это за задачи",
             "do": ["#240 — тесты состояний MVP Factory (без запуска нового продукта): https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/240",
                    "#241 — Relay не шлёт вам одно и то же уведомление дважды после перезапуска сервера: https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/241",
                    "#242 — страница «Задачи команды» честно показывает stale / 403 / offline: https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/242",
                    "Мой совет: #240 и #241 можно брать сейчас — это только тесты и надёжность, без изменения продукта. #242 лучше после задач Gemini #202 и #203 (они в его очереди, скорее всего сегодня)."],
             "check": "Вы решили по каждой задаче: «брать сейчас» или «ждать».",
             "if": [{"when": "Не понятно, о чём задача", "then": "Выделите её строку и нажмите «Спросить про этот шаг» — я объясню простыми словами."}]},
            {"id": "unblock", "title": "Снимите зависимость у тех, что «брать сейчас»",
             "do": ["Откройте задачу по ссылке выше → справа вверху «…» (три точки) → Edit.",
                    "Найдите строку, которая начинается с Depends: и замените её на: Depends: none (решение владельца)",
                    "Нажмите Update comment. Остальной текст не трогайте."],
             "check": "В описании задачи теперь строка Depends: none. Очередь Claude (Queue Keeper) сама переведёт её в «готова» при следующем обновлении «Задач команды».",
             "if": [{"when": "Нет кнопки Edit", "then": "Вы не вошли в GitHub под своим аккаунтом. Войдите и повторите."},
                    {"when": "Не хотите править GitHub", "then": "Просто напишите мне в чат: «бери #240 и #241» — я сделаю то же самое сам."}]},
            {"id": "verify", "title": "Убедитесь, что задача пошла в работу",
             "do": ["Откройте на сайте «Задачи команды» → нажмите «Обновить сейчас»."],
             "check": "У Claude задача видна как следующая в очереди, а затем появляется PR со ссылкой на неё.",
             "if": [{"when": "Задача всё ещё в «заблокировано»", "then": "Проверьте, что строка Depends сохранена именно в описании задачи, а не в комментарии."}]},
        ],
        "done": "По каждой из задач #240, #241, #242 принято решение; снятые взяты в работу.",
    },
    {
        "id": "HF-213",
        "title": "Использовать кредиты Higgsfield до их сгорания (≈90 кредитов, до 7 ноября)",
        "why": "Пробные кредиты сгорают. Короткий план: 4 кадра для трейлера AI Business League, по 2 дубля, лимит 80 кредитов. Промпты уже готовы. У Claude нет подключения к Higgsfield, поэтому запускаете вы или ChatGPT, где Higgsfield подключён.",
        "time": "≈30–40 минут",
        "steps": [
            {"id": "prompts", "title": "Откройте готовые промпты",
             "do": ["Файл: https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/blob/main/docs/prototypes/agent-hangout/trailer-brief/BRIEF.md → раздел «3. Higgsfield prompt pack».",
                    "Там 4 промпта: G1 монолит, G2 две сферы и луч, G3 превращение ролей, G4 десять комнат. В каждом кадре нет текста — надписи добавлю я кодом."],
             "check": "Вы видите четыре промпта с негативными подсказками.",
             "if": [{"when": "Файл не открывается", "then": "Войдите в GitHub: репозиторий приватный."}]},
            {"id": "generate", "title": "Сгенерируйте кадры (лимит 80 кредитов)",
             "do": ["В Higgsfield (сами или через ChatGPT) для каждого промпта: модель Kling v3.0, 5 секунд, 16:9, максимальное качество.",
                    "Порядок: G1 → G2 → G3 → G4, по 2 дубля. По оценке ≈10 кредитов за кадр, всего ≈80.",
                    "После каждого дубля смотрите остаток. Если кадр уже хороший — второй дубль не делайте и сэкономьте кредиты."],
             "check": "Есть 4–8 роликов по 5 секунд, кредитов ушло не больше 80.",
             "if": [{"when": "Цена за кадр больше 10 кредитов", "then": "Делайте по одному дублю, начиная с G1 и G2 — это самые важные кадры."},
                    {"when": "В кадре появился мусорный текст или лица", "then": "Не тратьте ещё кредит: я закрою это наложением в монтаже."},
                    {"when": "Higgsfield просит карту или платную подписку", "then": "СТОП: только бесплатные кредиты. Напишите мне."}]},
            {"id": "handoff", "title": "Передайте ролики мне",
             "do": ["Скачайте ролики и пришлите ссылки или файлы мне в чат (приватно, никуда не публикуя)."],
             "check": "Я соберу из них трейлер с точными надписями и пришлю на просмотр.",
             "if": [{"when": "Ролики слишком большие для чата", "then": "Положите их в Google Drive с доступом по ссылке только для вас и пришлите ссылку."}]},
        ],
        "done": "Кредиты использованы до сгорания, ролики у Claude, ничего не опубликовано.",
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
