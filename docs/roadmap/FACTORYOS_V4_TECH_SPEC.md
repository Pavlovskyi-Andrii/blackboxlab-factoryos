# FactoryOS v4.0 — Техническое задание и живой roadmap

**Проект:** Blackbox Lab — FactoryOS  
**Ветка:** `main`  
**Baseline:** v3.25  
**Создано:** 2026-10-19  
**Статус документа:** ACTIVE / living specification  
**Цель:** превратить FactoryOS из работающего AI orchestration control room в автономную, измеримую и самоулучшающуюся фабрику контента.

---

## 0. Как использовать этот документ

Этот файл является одновременно:

1. техническим заданием;
2. главным roadmap до v4.0;
3. журналом прогресса;
4. Definition of Done для каждого этапа;
5. точкой синхронизации между владельцем проекта и AI/Builder.

### Правило обновления

После каждого завершённого блока разработки:

- менять статус milestone;
- отмечать выполненные checkbox;
- записывать commit / deploy / verification evidence;
- фиксировать известные ограничения;
- не помечать этап DONE только по факту написания кода — нужен deploy + verification.

### Статусы

- `TODO` — не начато.
- `IN PROGRESS` — идёт реализация.
- `BLOCKED` — есть внешний blocker.
- `VERIFY` — код готов, ждём production verification.
- `DONE` — реализовано, задеплоено и проверено.

---

# 1. Product Vision

FactoryOS должен пройти путь:

```text
signals / trends / sources
        ↓
      ideas
        ↓
    research
        ↓
 angle + hooks
        ↓
     script
        ↓
 fact checking
        ↓
 content package
        ↓
    media build
        ↓
      QA
        ↓
 HUMAN APPROVAL
        ↓
 publishing queue
        ↓
 real analytics
        ↓
 learning / optimization
        ↓
 better next content
```

## Целевой пользовательский сценарий v4.0

Владелец открывает FactoryOS с телефона и видит несколько уже подготовленных системой идей/роликов.

Он:

1. просматривает идею, сценарий, источники и preview;
2. выбирает лучшие варианты;
3. при необходимости регенерирует только один компонент;
4. нажимает Approve;
5. FactoryOS ставит материал в очередь публикации;
6. после публикации забирает метрики;
7. связывает метрики с конкретными workers/prompts/models/handoffs;
8. предлагает улучшения следующего production cycle.

---

# 2. Неприкосновенные safety / product invariants

Эти правила нельзя ломать при развитии v4:

- [ ] Публикация требует human approval.
- [ ] Никакие credentials/secrets не отображаются в UI.
- [ ] Provider spend ограничен job/day budgets.
- [ ] Retry не должен создавать неконтролируемый повторный spend.
- [ ] Все worker handoffs должны оставаться traceable.
- [ ] Каждая production artifact должна иметь provenance.
- [ ] CI/smoke tests не должны совершать платные LLM-вызовы.
- [ ] Изменения prompts/workflows Supervisor'ом не применяются автоматически без контролируемого experiment/approval.
- [ ] Нельзя придумывать performance/quality metrics, которых реально нет в данных.

---

# 3. Текущий baseline — v3.24

## Уже существует

- live LLM worker execution;
- worker output visibility;
- worker-to-worker handoffs;
- Handoff Trace Viewer;
- live pipeline motion;
- Operations / Error Center;
- recovery policy и spend-safe retry;
- Factory Intelligence;
- EN / UK / RU UI;
- responsive/mobile control room;
- smoke/regression checks;
- Release QA workspace;
- human approval gate;
- Render deployment from `main`.

## Технические хвосты baseline

**Status: DONE**

- [x] Синхронизирован build manifest с реальным production state.
- [x] `live-llm` закрыт после production verification evidence.
- [x] `night-live-llm-hardening` закрыт после production verification evidence.
- [x] `mobile-parity` закрыт после production/mobile verification.
- [x] Зафиксирован baseline snapshot: version / commit / deploy / health / known gaps.

**Production evidence:** `v3.24-live-e2e-2026-10-19` → 7 live runs, 9 artifacts, 5,846 tokens, $0.029902, final state `waiting_approval`, approval gate reached. Одноразовый paid startup-trigger после успешной проверки отключён в v3.25.

---

# 4. Roadmap Overview

| Version | Milestone | Status | Главный результат |
|---|---|---|---|
| v3.25 | Baseline Closure | DONE | чистый и проверенный production baseline |
| v3.30 | Content Brain / Idea Factory | IN PROGRESS | FactoryOS сам находит и ранжирует темы |
| v3.40 | Production Pipeline 2.0 | TODO | многоступенчатое производство качественного сценария |
| v3.50 | Content Package / Shorts Factory | TODO | готовый production package для ролика |
| v3.60 | Approval Studio | TODO | удобное мобильное редакторское одобрение |
| v3.70 | Publishing Engine | TODO | очередь и контролируемая публикация |
| v3.80 | Feedback Loop | TODO | реальные performance-метрики возвращаются в FactoryOS |
| v3.90 | Self-Improving Factory | TODO | evidence-based оптимизация workers/prompts/models |
| v4.0 | Autonomous Content Factory | TODO | полный замкнутый production loop |

---

# 5. v3.25 — Baseline Closure

**Status: DONE**

## Цель

Полностью закрыть эпоху v3.x foundation перед наращиванием новой product logic.

## Scope

- привести `factory_build_manifest.json` к фактическому production состоянию;
- сохранить controlled paid-run evidence;
- подтвердить mobile parity;
- добавить единый build identity;
- зафиксировать known gaps.

## Tasks

- [x] Production LLM run evidence сохранён.
- [x] Есть input/output token accounting.
- [x] Есть provider cost accounting.
- [x] Есть artifact count / run IDs.
- [x] Pipeline остановился на approval gate.
- [x] Mobile dashboard проверен на phone width.
- [x] Manifest соответствует production.
- [x] README / changelog соответствует production.
- [x] Release QA показывает правильный current build.

## Definition of Done

`main` + Render + README + manifest + Release QA показывают одно и то же состояние.

---

# 6. v3.30 — Content Brain / Idea Factory

**Status: IN PROGRESS**

## Цель

FactoryOS должен перестать ждать только ручной темы и начать сам формировать очередь перспективных content ideas.

## Источники

Архитектура должна поддерживать подключаемые source adapters:

- URL / article;
- YouTube video/transcript;
- news/search sources;
- competitor content;
- manual notes;
- future social trend providers.

## Новый pipeline

```text
Signal Collector
  ↓
Scout
  ↓
Researcher
  ↓
Idea Strategist
  ↓
Idea Verifier
  ↓
Idea Queue
```

## Idea object

Минимальная схема:

- title;
- source signals;
- topic;
- angle;
- audience;
- why_now;
- novelty evidence;
- source links;
- risk flags;
- estimated production complexity;
- created_at;
- provenance.

## UI

Idea Queue должна показывать:

- новые signals;
- generated ideas;
- shortlisted ideas;
- rejected ideas;
- reasons;
- source provenance.

Пример operational summary:

```text
137 signals
24 generated ideas
7 shortlisted
3 selected for production
```

## Tasks

- [ ] Source adapter interface.
- [x] Manual URL ingestion.
- [x] Source deduplication.
- [x] Signal persistence.
- [x] Scout generation.
- [ ] Researcher enrichment.
- [ ] Idea Strategist.
- [ ] Idea Verifier.
- [ ] Idea Queue UI.
- [x] Idea provenance trace.
- [x] Cost/token accounting.
- [ ] Mobile UI.
- [x] Regression tests.

### Текущий implementation progress

- Backend foundation LIVE: commit `108256e400e3bfb5b643bbf3e89014f067056f7f`, Render deploy `dep-dbb7a8rsv6fc73bdftu0`.
- Добавлены persistent `source_signals` и `content_ideas`.
- Есть fingerprint-based deduplication.
- Есть API для ingestion, Idea Queue и изменения статуса идеи.
- Есть явный spend-guarded `signal → Scout → idea shortlist` generation endpoint; он не запускается автоматически.
- Сохраняются run/model/source provenance, tokens и provider cost.
- Zero-spend CI покрывает storage/dedup/API/parser contract.
- Следующий slice: Researcher enrichment → Idea Strategist → Idea Verifier → mobile Idea Queue UI.

## Definition of Done

Пользователь может не вводить тему вручную: FactoryOS сам получает signals, создаёт несколько traceable ideas и предлагает shortlist для запуска production.

---

# 7. v3.40 — Production Pipeline 2.0

**Status: TODO**

## Цель

Перейти от простого linear worker chain к production workflow с конкурирующими вариантами и формальной проверкой качества.

## Новый worker graph

```text
Scout
  ↓
Researcher
  ↓
Angle Strategist
  ↓
Hook Generator ──→ multiple candidates
  ↓
Script Writer
  ↓
Fact Checker
  ↓
Hook Optimizer
  ↓
Editor
  ↓
QA
```

## Требования

### Multiple candidates

Система должна уметь генерировать:

- несколько hooks;
- несколько angles;
- альтернативные script variants.

### Structured QA

QA должен возвращать не абстрактный score, а конкретные findings:

- unsupported claim;
- weak hook;
- duplicated angle;
- missing source;
- slow intro;
- unclear CTA;
- excessive length;
- unsafe / sensitive claim;
- fact conflict.

## Tasks

- [ ] Angle Strategist.
- [ ] Hook Generator.
- [ ] Multiple candidate artifacts.
- [ ] Candidate comparison.
- [ ] Fact Checker.
- [ ] Structured QA schema.
- [ ] Partial rerun.
- [ ] Downstream invalidation.
- [ ] Variant provenance.
- [ ] Variant cost comparison.
- [ ] Pipeline visualization update.
- [ ] Regression tests.

## Definition of Done

Одна idea может породить несколько production variants, а система умеет показать, почему выбран/отклонён каждый вариант.

---

# 8. v3.50 — Content Package / Shorts Factory

**Status: TODO**

## Цель

Выходом FactoryOS должен быть не просто текст, а структурированный пакет для производства короткого ролика.

## Content Package

Обязательные артефакты:

- final script;
- 1–3 sec hook;
- scene list;
- voice-over text;
- subtitle/SRT;
- title;
- description;
- CTA;
- hashtags;
- thumbnail concept;
- media brief;
- source list;
- fact-check report;
- estimated duration;
- production cost.

## Media layer

Подготовить adapter architecture для:

- TTS;
- image generation;
- video generation;
- stock/B-roll providers;
- local/manual media upload.

Провайдеры не должны быть hardcoded в бизнес-логику pipeline.

## Tasks

- [ ] ContentPackage schema.
- [ ] Script → scene breakdown.
- [ ] VO artifact.
- [ ] Subtitle/SRT generation.
- [ ] Caption/title/description package.
- [ ] Thumbnail concept.
- [ ] Media brief.
- [ ] Provider adapter interface.
- [ ] Package preview UI.
- [ ] Cost aggregation.
- [ ] Download/export package.
- [ ] Regression tests.

## Definition of Done

Для approved script FactoryOS создаёт единый traceable Content Package, достаточный для сборки short-form video.

---

# 9. v3.60 — Approval Studio

**Status: TODO**

## Цель

Превратить approval gate в полноценный мобильный редакторский workflow.

## UI

Approval Studio должен показывать:

- preview;
- script;
- sources;
- fact-check warnings;
- cost;
- duration;
- generated variants;
- provenance;
- publish target status.

## Actions

- Approve;
- Reject;
- regenerate hook only;
- regenerate script only;
- regenerate caption only;
- regenerate voice only;
- rerun selected worker;
- compare variants.

## Требования

Partial regeneration не должна заново оплачивать весь pipeline.

## Tasks

- [ ] Approval queue.
- [ ] Mobile-first preview.
- [ ] Partial regeneration actions.
- [ ] Cost-before-rerun confirmation.
- [ ] Variant diff.
- [ ] Reject reason persistence.
- [ ] Approval history.
- [ ] Audit log.
- [ ] Regression tests.

## Definition of Done

Владелец может полноценно управлять production approval с телефона без просмотра технических логов.

---

# 10. v3.70 — Publishing Engine

**Status: TODO**

## Цель

После approval материал должен перейти в контролируемую очередь публикации.

## Architecture

Предпочтительно использовать внешний publishing/analytics layer (например Metricool) там, где это сокращает сложность, сохраняя FactoryOS главным orchestrator.

## Publish state machine

```text
draft
→ ready_for_approval
→ approved
→ scheduled
→ publishing
→ published
→ failed
```

## Требования

- никакого publish до human approval;
- idempotency key для publish attempt;
- retry не должен создавать duplicate post;
- publish result должен сохраняться.

## Tasks

- [ ] Publisher adapter interface.
- [ ] Publishing queue.
- [ ] Schedule model.
- [ ] Idempotent publish action.
- [ ] Publish history.
- [ ] Failure/retry policy.
- [ ] Mobile queue UI.
- [ ] Integration with selected publisher.
- [ ] Regression tests.

## Definition of Done

Approved Content Package можно безопасно запланировать и опубликовать, а FactoryOS знает фактический publish status.

---

# 11. v3.80 — Performance Feedback Loop

**Status: TODO**

## Цель

Вернуть реальные результаты опубликованного контента обратно в pipeline.

## Metrics

Поддерживаемая модель должна позволять хранить:

- views;
- reach;
- watch time;
- retention;
- completion rate;
- likes;
- comments;
- shares;
- saves;
- follower/subscriber delta;
- publish timestamp;
- platform;
- content duration.

Если платформа не отдаёт метрику — FactoryOS не должен её выдумывать.

## Attribution

Каждый performance result должен связываться с:

- idea;
- sources;
- angle;
- hook;
- script;
- workers;
- model versions;
- prompts/workflow version;
- production cost.

## Tasks

- [ ] Analytics adapter.
- [ ] Published-content identity mapping.
- [ ] Metrics persistence.
- [ ] Time-series snapshots.
- [ ] Attribution graph.
- [ ] Content performance dashboard.
- [ ] Cost vs outcome comparison.
- [ ] Hook/angle cohort comparison.
- [ ] Regression tests.

## Definition of Done

Можно открыть опубликованный ролик и пройти цепочку:

`performance → content package → script → hook → worker runs → source signals`.

---

# 12. v3.90 — Self-Improving Factory

**Status: TODO**

## Цель

Factory Supervisor должен использовать накопленные реальные данные для evidence-based улучшений.

## Supervisor может предлагать

- изменить prompt;
- сменить model tier;
- убрать бесполезный worker step;
- добавить verification step;
- изменить количество candidates;
- изменить hook pattern;
- изменить production routing;
- оптимизировать cost/latency.

## Supervisor НЕ может

Самостоятельно без контролируемого процесса:

- менять safety invariants;
- отключать approval;
- увеличивать spend limits;
- публиковать;
- применять непроверенные prompt/workflow изменения прямо в production.

## Experiment framework

Каждое улучшение:

```text
proposal
→ hypothesis
→ controlled experiment
→ measured result
→ accept / reject
→ production rollout
```

## Tasks

- [ ] Improvement proposal schema.
- [ ] Evidence links.
- [ ] Experiment object.
- [ ] Control / treatment workflow versions.
- [ ] Outcome comparison.
- [ ] Cost comparison.
- [ ] Manual approval for rollout.
- [ ] Rollback support.
- [ ] Experiment history UI.

## Definition of Done

FactoryOS умеет доказательно показать: какое изменение workflow улучшило результат и почему его стоит принять.

---

# 13. v4.0 — Autonomous Content Factory

**Status: TODO**

## Цель

Замкнуть полный production loop.

## v4.0 acceptance scenario

На телефоне пользователь должен иметь возможность:

1. открыть FactoryOS;
2. увидеть автоматически найденные signals;
3. увидеть shortlist идей;
4. открыть готовые content variants;
5. просмотреть источники и QA;
6. одобрить лучший материал;
7. отправить его в publishing queue;
8. позже увидеть реальные performance metrics;
9. увидеть рекомендации Factory Intelligence/Supervisor;
10. запустить следующий улучшенный cycle.

## Definition of Done

v4.0 считается готовой, когда без ручного переноса данных между системами работает полный путь:

```text
signal
→ idea
→ research
→ production
→ content package
→ approval
→ publishing
→ analytics
→ learning
```

---

# 14. KPI проекта

## Reliability

- job completion rate;
- worker failure rate;
- retry rate;
- duplicate-spend incidents = 0;
- duplicate-publish incidents = 0.

## Cost

- cost per idea;
- cost per script;
- cost per approved package;
- cost per published item;
- cost per 1k views / relevant outcome when data exists.

## Speed

- signal → idea time;
- idea → script time;
- script → package time;
- approval → scheduled time.

## Quality proxies

Только измеримые показатели:

- QA findings per artifact;
- fact-check failure rate;
- rejection rate;
- regeneration rate;
- approval rate;
- real retention / engagement metrics where available.

Не использовать invented “AI quality score” без измеримого определения.

---

# 15. Приоритет реализации

Порядок обязателен, если нет критического blocker:

1. v3.25 baseline closure;
2. v3.30 Content Brain;
3. v3.40 Production Pipeline 2.0;
4. v3.50 Content Package;
5. v3.60 Approval Studio;
6. v3.70 Publishing;
7. v3.80 Feedback Loop;
8. v3.90 Self-Improving Factory;
9. v4.0 release.

Главный принцип: **сначала production value и measurable loop, потом косметика UI**.

---

# 16. Progress Log

Новые записи добавлять сверху.

## 2026-10-19 — v3.30 backend foundation LIVE

- Content Brain persistence, deduplication and Idea Queue API deployed.
- Spend-guarded Scout generation endpoint deployed; no automatic paid calls.
- CI passed zero-spend regressions for the new Content Brain contract.
- Render deploy: `dep-dbb7a8rsv6fc73bdftu0`.
- v3.30 remains IN PROGRESS: enrichment, strategist/verifier and mobile UI are next.

## 2026-10-19 — v3.25 Baseline Closure DONE / v3.30 started

- Production evidence подтверждён в Render: 7 live runs, 9 artifacts, 5,846 tokens, $0.029902.
- Pipeline завершил controlled paid verification в `waiting_approval`; human approval gate подтверждён.
- `live-llm`, Night 1 hardening и mobile parity синхронизированы как DONE.
- APP_VERSION поднят до v3.25.
- Одноразовый paid verification startup-trigger отключён; историческое evidence остаётся доступным.
- Следующий активный milestone: v3.30 Content Brain / Idea Factory.

## 2026-10-19 — Roadmap created

- Создано единое ТЗ FactoryOS v4.0.
- Baseline: v3.24.
- Следующий milestone: v3.25 — Baseline Closure.
- Новые feature milestones пока не начаты.

---

# 17. Current Next Action

**NEXT: v3.30 — Content Brain / Idea Factory**

Backend foundation уже live. NEXT: Researcher enrichment → Idea Strategist → Idea Verifier → mobile Idea Queue UI, затем переход к v3.40 Production Pipeline 2.0.
