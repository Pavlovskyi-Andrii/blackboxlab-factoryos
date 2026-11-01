"""Owner desk: step-by-step runbooks for [HUMAN] ROADMAP tasks and owner questions answered by the Claude worker.

Runbooks are static, reviewed text (Russian, the owner's working language). Every step says what to do,
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

QUOTE_MAX = 800
QUESTION_MAX = 1500
ANSWER_MAX = 6000
MAX_OPEN_QUESTIONS = 20
MAX_KEPT_QUESTIONS = 200
CLAIM_LEASE_SECONDS = 900
QUESTION_STATES = ("pending", "answering", "answered", "failed")

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
            {"id": "plan", "title": "Проверьте, что ваш тариф Metricool даёт API",
             "do": ["Войдите в Metricool → настройки аккаунта (Account settings) → раздел API.",
                    "Если раздел есть и там виден токен (userToken) — API доступен."],
             "check": "Вы видите userToken и userId.",
             "if": [{"when": "Раздела API нет или Metricool предлагает перейти на другой тариф", "then": "СТОП. Апгрейд тарифа — это платное решение, по правилам проекта я его не принимаю. Напишите мне, и я предложу бесплатный вариант (например, публикацию через вебхук или вручную с подтверждением)."}]},
            {"id": "ids", "title": "Соберите три значения",
             "do": ["userToken — секрет. " + NO_SECRETS,
                    "userId — число из того же раздела API.",
                    "blogId — номер бренда: выберите бренд blackboxlab7 и посмотрите в адресной строке параметр blogId=…"],
             "check": "У вас три значения: токен, userId, blogId.",
             "if": [{"when": "В адресе нет blogId", "then": "Переключитесь на бренд через выпадающий список брендов вверху и обновите страницу. Если всё равно нет — задайте мне вопрос по этому шагу."}]},
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
]
RUNBOOK_BY_ID = {r["id"]: r for r in RUNBOOKS}


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
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,})\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),              # AWS access key id
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
        return [{k: v for k, v in q.items() if k != "claimed_ts"} for q in items[-limit:]]

    def create(self, task_id: str, step_id: str, quote: str, question: str) -> dict[str, Any]:
        if task_id not in RUNBOOK_BY_ID:
            raise ValueError("unknown task")
        quote, question = _clean(quote, QUOTE_MAX), _clean(question, QUESTION_MAX)
        if not question:
            raise ValueError("empty question")
        steps = {s["id"] for s in RUNBOOK_BY_ID[task_id]["steps"]}
        step_id = step_id if step_id in steps else ""
        with self._lock:
            items = self._load()
            self._expire_leases(items)
            if sum(1 for q in items if q.get("status") in ("pending", "answering")) >= MAX_OPEN_QUESTIONS:
                raise OverflowError("too many open questions")
            item = {"id": "Q-" + secrets.token_hex(4), "task_id": task_id, "step_id": step_id, "quote": quote,
                    "question": question, "status": "pending", "created_at": _now_iso(), "answer": ""}
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
                              notify_owner: Optional[Callable[[str], Any]] = None) -> None:
    def require_owner(request: Request) -> None:
        if (identity_fn(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    def require_worker(request: Request) -> None:
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")

    @app.get("/api/factory/owner-desk")
    def owner_desk(request: Request):
        require_owner(request)
        try:
            status = status_fn() or {}
        except Exception:
            status = {}
        books = [{**r, "status": status.get(r["id"]) or {"state": "unknown", "detail": ""}} for r in RUNBOOKS]
        return {"runbooks": books, "questions": store.list(), "answer_mode": "worker_between_tasks"}

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
        if notify_owner and item.get("status") == "answered":
            try:
                notify_owner(f"💬 Ответ на ваш вопрос по {item['task_id']} готов: Worker Center → «Ваши задачи».")
            except Exception:
                pass
        return {"ok": True, "status": item.get("status")}
