"""Brand strategy passport → Master Brief (owner 2026-11-14, "запускай этап 1, паспорт для MyCast").

A 7-step chain (after Vladimir Bez's "7 prompts for a content plan", adapted for FactoryOS with Grok): goal & KPI →
unpacking & positioning → audience → tone of voice → content pillars → funnel TOFU/MOFU/BOFU → offer & CTA. Each step
sees the approved results of the earlier ones. A content manager can copy a step's prompt into any chat (cheat-sheet
mode) or press "draft" — one LLM call through the factory budget guard, only on that click — then edit and approve.
The approved steps assemble into one Master Brief that later becomes the shared context of every factory agent.
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

from fastapi import HTTPException, Request
from fastapi.responses import PlainTextResponse

BRAND_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
MAX_TEXT = 20000
MAX_INPUT = 1200
INPUT_KEYS = ("niche", "product", "platforms", "situation", "business_task")
UNPACK_QUESTIONS = (
    "В чём ваши сильные стороны и экспертиза?",
    "Какой у вас реальный опыт и кейсы (цифры, истории)?",
    "Чем вы отличаетесь от конкурентов?",
    "Чего больше всего боится и что болит у вашей аудитории?",
    "Какие вопросы аудитория задаёт чаще всего?",
    "На какие темы вы можете говорить уверенно и глубоко?",
    "Как вы обычно говорите (Tone of Voice): примеры фраз, что для вас недопустимо?",
)

ROLE = "Ты — Senior Content Strategist в системе FactoryOS (Blackbox Lab). Отвечай по-русски, структурированно, без воды: результат передаётся другим агентам фабрики."

STEPS = (
    {"n": 1, "key": "goal", "title": {"uk": "Ціль і KPI", "ru": "Цель и KPI", "en": "Goal & KPI"},
     "prompt": """Задача: определить цель контента на ближайшие 30 дней.

Сформулируй:
1. Главная цель на 30 дней (одна, конкретная, измеримая).
2. 2–3 вспомогательные цели.
3. Ключевые метрики (с приоритетом).
4. Какие типы контента нужны под эту цель.
5. Чего категорически не нужно делать на этом этапе."""},
    {"n": 2, "key": "unpacking", "title": {"uk": "Розпаковка і позиціонування", "ru": "Распаковка и позиционирование", "en": "Unpacking & positioning"},
     "prompt": """Проведи распаковку проекта по ответам автора на 7 вопросов (ниже).
Сформируй:

### Резюме позиционирования
1. Кто я как автор / что за продукт.
2. Чем полезен контент.
3. Для кого он.
4. Чем он отличается.
5. Какие темы раскрывать в первую очередь."""},
    {"n": 3, "key": "audience", "title": {"uk": "Аналіз аудиторії", "ru": "Анализ аудитории", "en": "Audience"},
     "prompt": """На основе распаковки проанализируй целевую аудиторию.
1. Выдели 3–5 сегментов.
2. Для каждого: кто это; что уже знает; главная проблема; чего боится; какие вопросы задаёт; какие возражения мешают; какой контент нужен.
3. Отдельно: главные боли; сильные желания; темы с сильным откликом; темы, которые не трогать или подавать осторожно.
Без общих фраз: документ используют исследователь, писатель и сценарист."""},
    {"n": 4, "key": "tone", "title": {"uk": "Tone of Voice і правила", "ru": "Tone of Voice и правила", "en": "Tone of voice & rules"},
     "prompt": """На основе распаковки создай редакционный профиль.
1. Общий стиль: как звучит контент; допустимы ли ирония, жёсткость, эмоции.
2. Правила текста: длина абзацев, постов и сценариев; уровень простоты; как начинать и заканчивать.
3. Что использовать: слова, формулировки, приёмы, форматы примеров.
4. Чего избегать: запрещённые слова и клише, канцелярит, «нейросетевые» фразы, излишняя рекламность.
5. Пример хорошего тона (2–3 предложения), пример плохого тона и короткая инструкция, которую можно вставить в системный промт писателя и сценариста."""},
    {"n": 5, "key": "pillars", "title": {"uk": "Контентні стовпи", "ru": "Контентные столпы", "en": "Content pillars"},
     "prompt": """Разработай ровно 4 контентных столпа.
Для каждого: конкретное небанальное название; какую задачу решает; для какого сегмента; какую часть доверия или продаж усиливает; какие форматы подходят (пост, Reels/Shorts, длинное видео, карусель, подкаст).
В конце — соотношение столпов в процентах (сумма 100%)."""},
    {"n": 6, "key": "funnel", "title": {"uk": "Воронка TOFU / MOFU / BOFU", "ru": "Воронка TOFU / MOFU / BOFU", "en": "Funnel TOFU / MOFU / BOFU"},
     "prompt": """Собери контентную воронку: TOFU (привлечение), MOFU (прогрев, доверие, экспертность), BOFU (заявка, продажа, переход к продукту).
Для каждого этапа: задачи; подходящие столпы и рубрики; темы; форматы; уместный CTA; чего не делать.
В конце — соотношение TOFU / MOFU / BOFU на ближайшие 30 дней в процентах. Документ обязателен для сценариста YouTube и агента, который режет шортсы."""},
    {"n": 7, "key": "offer", "title": {"uk": "Офер і CTA", "ru": "Оффер и CTA", "en": "Offer & CTA"},
     "prompt": """Свяжи контент с продуктом и действиями аудитории.
Сформируй:
1. Основной оффер.
2. Мягкие CTA для охватного контента (TOFU).
3. CTA для вовлечения.
4. CTA для прогрева (MOFU).
5. CTA для заявок и продаж (BOFU).
6. CTA для перехода на сайт / в рассылку / в личные сообщения.
7. Таблица: какой CTA для какого столпа и этапа воронки.
Никаких общих «подписывайтесь»: только точные действия."""},
)
STATES = ("empty", "draft", "approved")

# --- Stage 2 (owner 2026-11-14, "делай этап 2"): monthly plan + content matrix (pillar × funnel) → factory jobs.
FUNNEL = ("TOFU", "MOFU", "BOFU")
MAX_PLAN_ITEMS = 60
PLAN_FIELDS = ("title", "pillar", "funnel", "format", "platform", "hook", "cta")
PLAN_PROMPT = """Составь контент-план на {days} дней: ровно {count} публикаций (≈{per_week} в неделю).
Строго соблюдай столпы и их проценты (шаг 5), соотношение воронки TOFU/MOFU/BOFU (шаг 6), Tone of Voice (шаг 4) и карту CTA (шаг 7).
Площадки: {platforms}.

Ответь ТОЛЬКО JSON-массивом без пояснений, каждый элемент:
{{"day": 1-{days}, "title": "тема публикации", "pillar": "название столпа из шага 5", "funnel": "TOFU|MOFU|BOFU",
 "format": "Reels|Shorts|карусель|пост|длинное видео|Stories|подкаст", "platform": "одна площадка",
 "hook": "первая фраза/кадр", "cta": "точный CTA из карты CTA"}}"""


def _now() -> int:
    return int(time.time())


class StoreUnreadable(RuntimeError):
    """The strategy file exists but cannot be read or parsed: refuse to write over it (Codex review on #357)."""


class StrategyStore:
    def __init__(self, path: Path, *, seeds: Optional[dict] = None):
        self.path, self._thread_lock, self.seeds = Path(path), threading.Lock(), seeds or {}

    @contextlib.contextmanager
    def lock(self):
        """Thread lock plus an interprocess flock held from read to replace, so two workers cannot lose updates."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock, open(str(self.path) + ".lock", "a+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise StoreUnreadable(f"brand strategy file unreadable: {type(exc).__name__}") from exc
        if not isinstance(data, dict):
            raise StoreUnreadable("brand strategy file is not an object")
        return data

    def _save(self, data: dict) -> None:
        tmp = self.path.with_name(f"{self.path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    @staticmethod
    def blank(brand: str, name: str = "") -> dict:
        return {"brand": brand, "name": name or brand, "inputs": {k: "" for k in INPUT_KEYS},
                "answers": ["" for _ in UNPACK_QUESTIONS],
                "steps": {str(s["n"]): {"state": "empty", "text": "", "updated": 0, "by": ""} for s in STEPS},
                "version": 0, "approved_at": 0}

    def _passport(self, data: dict, brand: str) -> dict:
        seed = self.seeds.get(brand)
        if brand not in data:
            data[brand] = json.loads(json.dumps(seed)) if seed else self.blank(brand)
        elif seed and "plan" not in data[brand] and seed.get("plan"):
            data[brand]["plan"] = json.loads(json.dumps(seed["plan"]))   # stage 2 seed for passports saved before it
        return data[brand]

    def get(self, brand: str) -> dict:
        with self.lock():
            data = self._load()
            fresh = brand not in data or ("plan" not in data[brand] and bool((self.seeds.get(brand) or {}).get("plan")))
            p = self._passport(data, brand)
            if _ensure_ids(p) or fresh:
                self._save(data)
            return p

    def brands(self) -> list:
        with self.lock():
            data = self._load()
            for b in self.seeds:
                self._passport(data, b)
            return [{"brand": b, "name": p.get("name", b), "approved": sum(s["state"] == "approved" for s in p["steps"].values()),
                     "version": p.get("version", 0)} for b, p in sorted(data.items())]

    def update(self, brand: str, fn) -> dict:
        with self.lock():
            data = self._load()
            p = self._passport(data, brand)
            _ensure_ids(p)
            if fn(p) is False:                    # the change was refused (e.g. stale draft): write nothing
                return p
            self._save(data)
            return p


def context_for(p: dict, n: int) -> str:
    """Brand inputs plus the approved (or, failing that, drafted) results of the steps before n."""
    i = p.get("inputs") or {}
    labels = {"niche": "Ниша", "product": "Продукт / услуга", "platforms": "Площадки", "situation": "Текущая ситуация",
              "business_task": "Главная бизнес-задача"}
    parts = ["## Данные проекта"] + [f"- {labels[k]}: {i.get(k) or '—'}" for k in INPUT_KEYS]
    if n == 2:
        parts.append("\n## Ответы автора на 7 вопросов")
        for q, a in zip(UNPACK_QUESTIONS, p.get("answers") or []):
            parts.append(f"- {q}\n  {a or '—'}")
    for s in STEPS:
        if s["n"] >= n:
            break
        st = p["steps"][str(s["n"])]
        if st["text"].strip():
            mark = "" if st["state"] == "approved" else " (черновик, не утверждён)"
            parts.append(f"\n## Шаг {s['n']}. {s['title']['ru']}{mark}\n{st['text'].strip()}")
    return "\n".join(parts)


def prompt_for(p: dict, n: int) -> tuple:
    step = STEPS[n - 1]
    return ROLE, f"{context_for(p, n)}\n\n## Задание (шаг {n} из 7)\n{step['prompt']}"


def plan_prompt(p: dict, settings: dict) -> tuple:
    count = settings["per_week"] * settings["weeks"]
    task = PLAN_PROMPT.format(days=settings["weeks"] * 7, count=count, per_week=settings["per_week"],
                              platforms=settings["platforms"] or (p.get("inputs") or {}).get("platforms") or "—")
    return ROLE, f"{master_brief(p, approved_only=False)}\n\n## Задание: контент-план\n{task}"


def _clean(v, n=300) -> str:
    return " ".join(str(v or "").split())[:n]


def parse_plan(text: str, settings: dict) -> list:
    """The LLM's JSON array → validated rows (unknown funnel → TOFU, day clamped, at most MAX_PLAN_ITEMS)."""
    raw = str(text or "")
    a, b = raw.find("["), raw.rfind("]")
    try:
        rows = json.loads(raw[a:b + 1]) if a >= 0 and b > a else []
    except ValueError:
        rows = []
    days, out = settings["weeks"] * 7, []
    for r in rows if isinstance(rows, list) else []:
        if not isinstance(r, dict) or not _clean(r.get("title")):
            continue
        try:
            day = min(days, max(1, int(r.get("day") or 1)))
        except (TypeError, ValueError):
            day = 1
        item = {k: _clean(r.get(k), 300 if k in ("title", "hook", "cta") else 80) for k in PLAN_FIELDS}
        item["funnel"] = item["funnel"].upper() if item["funnel"].upper() in FUNNEL else "TOFU"
        item["day"] = day
        item["id"] = "pi_" + secrets.token_hex(5)
        out.append(item)
        if len(out) >= MAX_PLAN_ITEMS:
            break
    return sorted(out, key=lambda x: x["day"])


def _ensure_ids(p: dict) -> bool:
    """Every plan row gets a durable id (Codex review on #358: never address rows by array index)."""
    changed = False
    for it in (p.get("plan") or {}).get("items") or []:
        if not it.get("id"):
            it["id"] = "pi_" + secrets.token_hex(5)
            changed = True
    return changed


def plan_view(plan: dict) -> dict:
    """Dates from the start day plus the content matrix: counts per pillar × funnel stage."""
    import datetime as _dt
    items = plan.get("items") or []
    try:
        start = _dt.date.fromisoformat((plan.get("settings") or {}).get("start") or "")
    except ValueError:
        start = None
    rows = [{**it, "date": (start + _dt.timedelta(days=it["day"] - 1)).isoformat() if start else ""} for it in items]
    pillars = sorted({it.get("pillar") or "—" for it in items})
    matrix = {pl: {f: sum(1 for it in items if (it.get("pillar") or "—") == pl and it["funnel"] == f) for f in FUNNEL}
              for pl in pillars}
    total = max(1, len(items))
    funnel_share = {f: round(100 * sum(1 for it in items if it["funnel"] == f) / total) for f in FUNNEL}
    return {**plan, "items": rows, "matrix": matrix, "funnel_share": funnel_share}


def plan_settings(body: dict) -> dict:
    import datetime as _dt
    start = str(body.get("start") or "")
    try:
        _dt.date.fromisoformat(start)
    except ValueError:
        start = (_dt.date.today() + _dt.timedelta(days=(7 - _dt.date.today().weekday()) % 7 or 7)).isoformat()  # next Monday
    try:
        per_week = min(14, max(1, int(body.get("per_week") or 5)))
        weeks = min(6, max(1, int(body.get("weeks") or 4)))
    except (TypeError, ValueError):
        per_week, weeks = 5, 4
    weeks = min(weeks, max(1, MAX_PLAN_ITEMS // per_week))      # never ask for more rows than are kept (≤ 60)
    return {"start": start, "per_week": per_week, "weeks": weeks, "platforms": _clean(body.get("platforms"), 200)}


def job_brief(p: dict, it: dict) -> str:
    tone = (p["steps"]["4"]["text"] or "").strip()
    return "\n".join([
        f"Бренд: {p.get('name') or p['brand']}",
        f"Столп: {it.get('pillar')} · этап воронки: {it['funnel']} · формат: {it.get('format')} · площадка: {it.get('platform')}",
        f"Хук: {it.get('hook')}", f"CTA: {it.get('cta')}",
        "", "Tone of Voice (из паспорта бренда):", tone[:1500] or "—"])


def master_brief(p: dict, *, approved_only: bool = True) -> str:
    lines = [f"# Master Brief — {p.get('name') or p['brand']}",
             f"_FactoryOS · версия {p.get('version', 0)} · {time.strftime('%Y-%m-%d', time.gmtime(p.get('approved_at') or _now()))}_", ""]
    missing = []
    for s in STEPS:
        st = p["steps"][str(s["n"])]
        if st["state"] != "approved":
            missing.append(s["title"]["ru"])
        if st["state"] == "approved":
            lines += [f"## {s['n']}. {s['title']['ru']}", st["text"].strip(), ""]
        elif not approved_only and st["text"].strip():
            lines += [f"## {s['n']}. {s['title']['ru']} — ЧЕРНОВИК, не утверждён", st["text"].strip(), ""]
    if missing:
        lines += ["> Ещё не утверждено: " + ", ".join(missing), ""]
    return "\n".join(lines)


def install_strategy_routes(app, store: StrategyStore, *, identity: Callable,
                            draft: Callable[[str, str, str], Awaitable[dict]],
                            create_job: Optional[Callable[[str, str, str], Awaitable[str]]] = None) -> None:
    """draft(agent, system, user) → {"content": ..., "cost_usd": ...}; raises RuntimeError with a readable reason."""

    def owner(request: Request):
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    def brand_ok(brand: str) -> str:
        if not BRAND_RE.fullmatch(brand or ""):
            raise HTTPException(404, "unknown brand")
        return brand

    def step_ok(n: int) -> int:
        if not 1 <= int(n) <= len(STEPS):
            raise HTTPException(404, "unknown step")
        return int(n)

    async def body(request: Request) -> dict:
        try:
            b = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        if not isinstance(b, dict):
            raise HTTPException(400, "json object required")
        return b

    @app.exception_handler(StoreUnreadable)
    async def _unreadable(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse({"detail": str(exc)}, status_code=503)

    def view(p: dict) -> dict:
        return {**p, "plan": plan_view(p.get("plan") or {}), "questions": list(UNPACK_QUESTIONS),
                "step_meta": [{"n": s["n"], "key": s["key"], "title": s["title"], "prompt": prompt_for(p, s["n"])[1]} for s in STEPS],
                "role": ROLE}

    @app.get("/api/factory/strategy")
    def strategy_brands(request: Request):
        owner(request)
        return {"brands": store.brands()}

    @app.get("/api/factory/strategy/{brand}")
    def strategy_get(brand: str, request: Request):
        owner(request)
        return {"passport": view(store.get(brand_ok(brand)))}

    @app.post("/api/factory/strategy/{brand}/inputs")
    async def strategy_inputs(brand: str, request: Request):
        owner(request)
        b = await body(request)

        def apply(p):
            for k in INPUT_KEYS:
                if k in b:
                    p["inputs"][k] = str(b[k] or "")[:MAX_INPUT]
            if isinstance(b.get("answers"), list):
                p["answers"] = [str(x or "")[:MAX_INPUT] for x in b["answers"][:len(UNPACK_QUESTIONS)]]
                p["answers"] += [""] * (len(UNPACK_QUESTIONS) - len(p["answers"]))
            if b.get("name"):
                p["name"] = str(b["name"])[:80]
        return {"passport": view(store.update(brand_ok(brand), apply))}

    @app.post("/api/factory/strategy/{brand}/steps/{n}")
    async def strategy_save(brand: str, n: int, request: Request):
        owner(request)
        b, n = await body(request), step_ok(n)
        text = str(b.get("text") or "")[:MAX_TEXT]
        approve = b.get("approve") is True

        def apply(p):
            st = p["steps"][str(n)]
            st.update(text=text, updated=_now(), by="owner", rev=int(st.get("rev", 0)) + 1,
                      state="approved" if approve and text.strip() else ("draft" if text.strip() else "empty"))
            if approve and text.strip():
                p["version"] = int(p.get("version", 0)) + 1
                p["approved_at"] = _now()
        return {"passport": view(store.update(brand_ok(brand), apply))}

    @app.post("/api/factory/strategy/{brand}/steps/{n}/draft")
    async def strategy_draft(brand: str, n: int, request: Request):
        owner(request)
        n = step_ok(n)
        p = store.get(brand_ok(brand))
        base = dict(p["steps"][str(n)])           # what the step looked like when the draft was asked for
        system, user = prompt_for(p, n)
        try:
            out = await draft("Angle Strategist", system, user)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)[:300])
        stale = {}

        def apply(q):
            cur = q["steps"][str(n)]
            # Codex review on #357: an edit, approval or another draft made meanwhile always wins over this one.
            if (cur.get("updated"), cur.get("text"), cur.get("state")) != (base.get("updated"), base.get("text"), base.get("state")):
                stale["yes"] = True
                return False
            cur.update(text=str(out.get("content") or "")[:MAX_TEXT], state="draft", updated=_now(), by="llm",
                       rev=int(cur.get("rev", 0)) + 1)
        q = store.update(brand, apply)
        if stale:
            raise HTTPException(409, "the step changed while the draft was being written; nothing was overwritten")
        return {"passport": view(q), "cost_usd": out.get("cost_usd", 0)}

    @app.post("/api/factory/strategy/{brand}/plan/generate")
    async def strategy_plan_generate(brand: str, request: Request):
        """One owner-clicked LLM call: a dated monthly plan built on the Master Brief (drafts labelled)."""
        owner(request)
        settings = plan_settings(await body(request))
        p = store.get(brand_ok(brand))
        base_rev = int((p.get("plan") or {}).get("rev", 0))
        system, user = plan_prompt(p, settings)
        try:
            out = await draft("Angle Strategist", system, user)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)[:300])
        items = parse_plan(out.get("content"), settings)
        if not items:
            raise HTTPException(502, "the model did not return a usable plan; nothing was changed")

        stale = {}

        def apply(q):
            cur = q.get("plan") or {}
            if int(cur.get("rev", 0)) != base_rev or any(it.get("job_claim") for it in cur.get("items") or []):
                stale["yes"] = True                # rows changed or a job is being created meanwhile: keep them
                return False
            q["plan"] = {"settings": settings, "items": items, "updated": _now(), "by": "llm", "rev": base_rev + 1}
        q = store.update(brand, apply)
        if stale:
            raise HTTPException(409, "the plan changed while the new one was being written; nothing was replaced")
        return {"passport": view(q), "cost_usd": out.get("cost_usd", 0)}

    ITEM_RE = re.compile(r"^pi_[0-9a-f]{10}$")

    def find(q: dict, item_id: str) -> Optional[dict]:
        return next((it for it in (q.get("plan") or {}).get("items") or [] if it.get("id") == item_id), None)

    @app.post("/api/factory/strategy/{brand}/plan/items/{item_id}/delete")
    def strategy_plan_delete(brand: str, item_id: str, request: Request):
        owner(request)

        def apply(q):
            it = find(q, item_id) if ITEM_RE.fullmatch(item_id or "") else None
            if not it:
                raise HTTPException(404, "unknown plan item")
            if it.get("job_claim"):
                raise HTTPException(409, "a job is being created for this row")
            q["plan"]["items"].remove(it)
            q["plan"]["rev"] = int(q["plan"].get("rev", 0)) + 1
        return {"passport": view(store.update(brand_ok(brand), apply))}

    @app.post("/api/factory/strategy/{brand}/plan/items/{item_id}/job")
    async def strategy_plan_job(brand: str, item_id: str, request: Request):
        """A plan row becomes a factory job (inbox) whose brief carries pillar, funnel stage, hook, CTA and tone.
        Codex review on #358: the row is claimed atomically under the store lock before the job exists, so two clicks
        make one job, and the job is attached to the row by its durable id, never by position."""
        owner(request)
        if create_job is None:
            raise HTTPException(503, "job creation is not available")
        if not ITEM_RE.fullmatch(item_id or ""):
            raise HTTPException(404, "unknown plan item")
        token, claimed = secrets.token_hex(6), {}

        def claim(q):
            it = find(q, item_id)
            if not it:
                raise HTTPException(404, "unknown plan item")
            if it.get("job_id"):
                claimed["existing"] = it["job_id"]
                return False
            c = it.get("job_claim") or {}
            if c and _now() - int(c.get("at", 0)) < 120:
                raise HTTPException(409, "a job for this row is already being created")
            it["job_claim"] = {"token": token, "at": _now()}
            claimed["row"], claimed["brief"] = dict(it), job_brief(q, it)
        p = store.update(brand_ok(brand), claim)
        if "existing" in claimed:
            return {"passport": view(p), "job_id": claimed["existing"], "existing": True}
        row = claimed["row"]
        try:
            job_id = await create_job(row["title"], claimed["brief"], row.get("format") or "")
        except Exception:
            store.update(brand, lambda q: (find(q, item_id) or {}).pop("job_claim", None))
            raise

        def attach(q):
            it = find(q, item_id)
            if it and (it.get("job_claim") or {}).get("token") == token:
                it.pop("job_claim", None)
                it["job_id"] = job_id
        return {"passport": view(store.update(brand, attach)), "job_id": job_id, "existing": False}

    @app.get("/api/factory/strategy/{brand}/brief.md")
    def strategy_brief(brand: str, request: Request, drafts: int = 0):
        owner(request)
        p = store.get(brand_ok(brand))
        return PlainTextResponse(master_brief(p, approved_only=not drafts), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'inline; filename="master-brief-{brand}.md"'})
