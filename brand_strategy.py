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
        if brand not in data:
            seed = self.seeds.get(brand)
            data[brand] = json.loads(json.dumps(seed)) if seed else self.blank(brand)
        return data[brand]

    def get(self, brand: str) -> dict:
        with self.lock():
            data = self._load()
            fresh = brand not in data
            p = self._passport(data, brand)
            if fresh:
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
                            draft: Callable[[str, str, str], Awaitable[dict]]) -> None:
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
        return {**p, "questions": list(UNPACK_QUESTIONS),
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

    @app.get("/api/factory/strategy/{brand}/brief.md")
    def strategy_brief(brand: str, request: Request, drafts: int = 0):
        owner(request)
        p = store.get(brand_ok(brand))
        return PlainTextResponse(master_brief(p, approved_only=not drafts), media_type="text/markdown; charset=utf-8",
                                 headers={"Content-Disposition": f'inline; filename="master-brief-{brand}.md"'})
