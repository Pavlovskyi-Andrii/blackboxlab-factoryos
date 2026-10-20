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
| v3.30 | Content Brain / Idea Factory | DONE | FactoryOS сам находит и ранжирует темы |
| v3.40 | Production Pipeline 2.0 | DONE | многоступенчатое производство качественного сценария |
| v3.50 | Content Package / Shorts Factory | DONE | готовый production package для ролика |
| v3.60 | Approval Studio | DONE | удобное мобильное редакторское одобрение |
| v3.70 | Publishing Engine | DONE | очередь и контролируемая публикация |
| v3.80 | Feedback Loop | DONE | реальные performance-метрики возвращаются в FactoryOS |
| v3.90 | Self-Improving Factory | DONE | evidence-based оптимизация workers/prompts/models |
| v4.0 | Autonomous Content Factory | DONE | полный замкнутый production loop |
| v4.1 | Production Hardening / Real Pilot | DONE | первый real paid cycle + production hardening |
| v4.2 | UX Clarity / Worker Transparency | DONE | понятный UI, tooltips, i18n и реальные outputs workers |
| v4.3 | Revideo / Original Rewrite MVP | DONE | URL/transcript → original rewrite → production + video adapter hook |
| v4.4 | Real Media Provider Foundation | IN PROGRESS | async media jobs + Descript verified; Runway runtime verification pending |

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

**Status: DONE**

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

- [x] Source adapter interface.
- [x] Manual URL ingestion.
- [x] Source deduplication.
- [x] Signal persistence.
- [x] Scout generation.
- [x] Researcher enrichment.
- [x] Idea Strategist.
- [x] Idea Verifier.
- [x] Idea Queue UI.
- [x] Idea provenance trace.
- [x] Cost/token accounting.
- [x] Mobile UI.
- [x] Regression tests.

### Текущий implementation progress

- **v3.30 DONE и LIVE**: production commit `00225f9ed45253f33c1d9159eba2eb090e6e9fb1`, Render deploy `dep-dbbgdagubc0c73d4qbng`.
- Persistent `source_signals` и `content_ideas`, fingerprint-based deduplication и provenance работают.
- Source adapter layer поддерживает manual/URL ingestion и настраиваемый scheduled RSS collector через `FACTORY_SIGNAL_FEEDS`.
- Scout создаёт shortlist-кандидаты из persisted signals.
- Researcher формирует evidence pack только по сохранённым источникам.
- Idea Strategist уточняет title/angle/audience/why-now/novelty/complexity без добавления неподтверждённых фактов.
- Idea Verifier возвращает `shortlist / reject / needs_research`, risk flags и reason.
- Mobile Content Brain workspace показывает signals, Idea Queue, research/strategy/verification, позволяет выбрать/отклонить идею и создать production job.
- Все model calls остаются spend-guarded; автоматический paid release test не запускался.
- GitHub CI run `39379172168` прошёл compile, zero-spend smoke/regression, HTML и JavaScript checks.
- Render подтвердил startup, configured LLM provider и повторные `/health 200 OK`.

## Definition of Done

Пользователь может не вводить тему вручную: FactoryOS сам получает signals, создаёт несколько traceable ideas и предлагает shortlist для запуска production.

---

# 7. v3.40 — Production Pipeline 2.0

**Status: DONE**

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

- [x] Angle Strategist.
- [x] Hook Generator.
- [x] Multiple candidate artifacts.
- [x] Candidate comparison.
- [x] Fact Checker.
- [x] Structured QA schema.
- [x] Partial rerun.
- [x] Downstream invalidation.
- [x] Variant provenance.
- [x] Variant cost comparison.
- [x] Pipeline visualization update.
- [x] Regression tests.

## Definition of Done

Одна idea может породить несколько production variants, а система умеет показать, почему выбран/отклонён каждый вариант.

### Реализовано

- По умолчанию создаётся batch из 3 production variants.
- Каждый variant хранит angle, hook, script, fact-check, optimized hook, edited script, structured QA, decision reason и provenance.
- Structured QA использует конкретные findings вместо выдуманного общего quality score.
- Variant Studio показывает сравнение вариантов, причины выбора/отклонения, findings и распределённую измеренную стоимость.
- Shared batch model cost распределяется между вариантами только для comparison; фактический общий provider spend остаётся точным в `agent_runs`.
- Partial rerun поддерживает angle / hook / script / factcheck / optimize / editor / QA и переводит job обратно в `script`, чтобы downstream stages не использовали устаревший результат.
- Выбранный variant становится свежим Editor + Fact Checker handoff для Visual/Voice/Render/QA.
- Zero-spend CI создаёт demo batch из трёх вариантов и проверяет selection, structured findings, artifacts и manual winner switch.
- Production commit: `0410358433509703b5ae26f8e0246f625d967298`.
- CI: `39380515484` PASS.
- Render: `dep-dbbgkaei0phs738fog7g` LIVE, startup clean, `/health` = 200.
- Controlled paid variant generation не запускалась в release verification; live calls остаются explicit и защищены job/day budgets.

---

# 8. v3.50 — Content Package / Shorts Factory

**Status: DONE**

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

- [x] ContentPackage schema.
- [x] Script → scene breakdown.
- [x] VO artifact.
- [x] Subtitle/SRT generation.
- [x] Caption/title/description package.
- [x] Thumbnail concept.
- [x] Media brief.
- [x] Provider adapter interface.
- [x] Package preview UI.
- [x] Cost aggregation.
- [x] Download/export package.
- [x] Regression tests.

## Definition of Done

Для approved script FactoryOS создаёт единый traceable Content Package, достаточный для сборки short-form video.

### Реализовано

- Content Package schema v1.0 хранится отдельно от обычных artifacts и связан с job + selected variant.
- Package содержит final script, hook, scene breakdown, voice-over, SRT, title, description, CTA, hashtags, thumbnail concept, media brief, source list, fact-check, structured QA, duration и measured cost.
- Source list строится только из persisted Researcher / Tech Verifier artifacts, URL и fact-check evidence — новые источники не выдумываются.
- SRT и estimated duration формируются локально и детерминированно из voice-over.
- Live package generation использует один explicit Content Packager model call внутри job/day budget guards; CI использует zero-spend deterministic mode.
- Generic media adapter contract отделяет business logic от провайдера: TTS, image, video, stock и manual upload path конфигурируются независимо.
- Visual Director и Voice Agent получают Content Packager manifest как upstream dependency.
- Package Studio работает на desktop/mobile и показывает script, hook, VO, SRT, scenes, metadata, thumbnail/media brief, sources, fact-check и adapter readiness.
- Экспорт доступен как ZIP bundle и JSON; ZIP содержит script, VO, SRT, scenes, metadata, sources, fact-check и media brief.
- Если selected variant меняется, package становится stale и job возвращается на script stage; если package перестраивается вручную, downstream возвращается на visual stage.
- CI `39382663013` — PASS.
- Production commit `54c17937242219d35c2df93f339a9dfba55802da`, Render deploy `dep-dbbgu2rm8hqs738tvkog` — LIVE.

---

# 9. v3.60 — Approval Studio

**Status: DONE**

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

- [x] Approval queue.
- [x] Mobile-first preview.
- [x] Partial regeneration actions.
- [x] Cost-before-rerun confirmation.
- [x] Variant diff.
- [x] Reject reason persistence.
- [x] Approval history.
- [x] Audit log.
- [x] Regression tests.

## Definition of Done

Владелец может полноценно управлять production approval с телефона без просмотра технических логов.

### Реализовано

- Approval queue агрегирует job, свежий Content Package, выбранный variant, render preview, provenance, QA/fact warnings, measured cost/duration, publish state и decision history.
- Approve и Reject сохраняются в отдельном audit ledger; reject требует причину.
- Approve больше не запускает публикацию: он только создаёт controlled publishing queue item.
- Targeted regeneration поддерживает hook/script/caption/voice; hook/script используют существующий partial-rerun fence, caption перестраивает только publishing metadata, voice инвалидирует Render → QA.
- До платного model rerun UI/API возвращают консервативную estimate; фактическая стоимость остаётся в agent run accounting.
- Variant diff показывает конкретно изменившиеся поля без synthetic quality score.
- Mobile-first Approval Studio доступен из основной навигации.
- Zero-spend CI `39391145024` PASS; production commit `e94cfff4094221acaf4f61b8c10ba9e7adfa1c01` / Render `dep-dbbi2m6k1f9s73bs9rk0` LIVE.

---

# 10. v3.70 — Publishing Engine

**Status: DONE**

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

- [x] Publisher adapter interface.
- [x] Publishing queue.
- [x] Schedule model.
- [x] Idempotent publish action.
- [x] Publish history.
- [x] Failure/retry policy.
- [x] Mobile queue UI.
- [x] Integration with selected publisher.
- [x] Regression tests.

## Definition of Done

Approved Content Package можно безопасно запланировать и опубликовать, а FactoryOS знает фактический publish status.

### Реализовано

- Persisted publishing queue использует state flow `approved → scheduled → publishing → published / failed`.
- Queue item создаётся только после human approval и связан с конкретным fresh package + selected variant.
- Stable SHA-256 idempotency key предотвращает duplicate publish для одного package/variant; повтор действия для published item возвращает idempotent result.
- Manual publisher adapter является безопасным baseline: FactoryOS не выдумывает факт публикации и требует реальный external post ID перед `published`.
- Provider-neutral webhook adapter поддерживает внешнего publisher; timeout/network outcome помечается uncertain и требует подтверждения перед retry.
- Сохраняются schedule, attempt count, failure, external post ID/URL, published timestamp и publish receipt artifact.
- Mobile Publishing workspace позволяет планировать, запускать/retry и подтверждать реальный post.
- Zero-spend regression проверяет schedule → manual handoff → real receipt → duplicate-safe повтор.

---

# 11. v3.80 — Performance Feedback Loop

**Status: DONE**

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

- [x] Analytics adapter.
- [x] Published-content identity mapping.
- [x] Metrics persistence.
- [x] Time-series snapshots.
- [x] Attribution graph.
- [x] Content performance dashboard.
- [x] Cost vs outcome comparison.
- [x] Hook/angle cohort comparison.
- [x] Regression tests.

## Definition of Done

Можно открыть опубликованный ролик и пройти цепочку:

`performance → content package → script → hook → worker runs → source signals`.

### Реализовано

- Performance snapshots хранят time-series значения только для реально пришедших/введённых метрик; отсутствующие поля не создаются.
- Поддерживаются views, reach, watch time, retention, completion, likes, comments, shares, saves, follower delta и content duration.
- Attribution связывает publish item → job → originating idea → package → selected variant → angle/hook → variant provenance/run IDs → source list → measured production cost.
- Cost per 1k views вычисляется только при наличии views > 0.
- Angle cohort comparison усредняет retention/completion только по строкам, где эти метрики реально существуют.
- Manual analytics entry работает без внешнего провайдера; generic webhook adapter готов для platform analytics.
- Mobile Performance workspace показывает published/measured counts, real views, attribution и cohorts.
- CI fixture доказала, что snapshot с `views + retention + likes` сохраняет ровно эти три метрики и не дорисовывает остальные.

---

# 12. v3.90 — Self-Improving Factory

**Status: DONE**

## Цель

Factory Supervisor использует накопленные реальные данные для evidence-based улучшений, но ни одно изменение workflow не может попасть в production без изолированного эксперимента и ручного решения владельца.

## Supervisor может предлагать

- изменить prompt;
- сменить model tier только внутри явного allowlist;
- изменить количество candidates;
- изменить hook pattern;
- предложить production routing;
- предложить cost/latency optimization;
- связать предложение с конкретными findings и measured evidence.

## Supervisor НЕ может

Самостоятельно:

- менять safety invariants;
- отключать approval;
- увеличивать spend limits;
- публиковать;
- применять непроверенные prompt/workflow изменения прямо в production;
- автоматически активировать treatment после эксперимента.

## Experiment framework

```text
proposal + evidence
→ hypothesis
→ immutable control / treatment workflow versions
→ pre-run job assignment
→ controlled production
→ real published/performance measurements
→ outcome + cost comparison
→ owner accept / reject
→ manual production rollout
→ optional rollback
```

## Tasks

- [x] Improvement proposal schema.
- [x] Evidence links.
- [x] Experiment object.
- [x] Control / treatment workflow versions.
- [x] Outcome comparison.
- [x] Cost comparison.
- [x] Manual approval for rollout.
- [x] Rollback support.
- [x] Experiment history UI.

## Реализовано

- Improvement proposal хранит hypothesis, evidence и конкретный allowlisted workflow patch.
- Workflow versions immutable для уже назначенных jobs; experiment arm назначается до первого worker run.
- Runtime может экспериментально менять только ограниченный набор production-параметров: candidate count, worker prompt addenda, allowlisted model, hook pattern и routing notes.
- Human approval, publishing gate, spend limits и прочие safety controls не являются изменяемыми experiment parameters.
- Published performance attribution теперь содержит workflow version, experiment ID и control/treatment arm.
- Evaluation использует только реально сохранённые platform metrics. Для отсутствующей метрики значение не придумывается.
- Experiment comparison показывает primary outcome, sample counts, observed effect, average measured production cost и duration.
- Treatment не активируется автоматически даже при положительном результате. Rollout требует явного owner confirmation.
- Rollback возвращает предыдущую production workflow version и оставляет audit trail.
- Experiment Lab добавлен в EN / UK / RU и показывает proposals, diffs, assignments, measurements, recommendation, rollout и rollback actions.
- CI regression проходит полный deterministic zero-spend сценарий control (3 candidates) vs treatment (4 candidates), factual performance snapshots, recommendation, confirmation fence, rollout и rollback.

## Production evidence

- Functional commit: `c9ef037db619b4e475bf9b66ed1c32442573a805`.
- GitHub CI: `39402528845` — PASS.
- Render deploy: `dep-dbbjeo1srm7s7389md60` — LIVE.
- Production startup: clean; Builder bridge ready; LLM provider configured.
- Repeated production `/health`: 200 OK.
- Release verification remained zero-spend; no real social post or paid experiment was triggered.

## Definition of Done

FactoryOS доказательно связывает measured result с конкретной control/treatment workflow version, показывает outcome/cost comparison, не применяет treatment автоматически, требует owner approval для rollout и умеет безопасно вернуться на предыдущую production version.

---

# 13. v4.0 — Autonomous Content Factory

**Status: DONE**

## Цель

Замкнуть полный production loop так, чтобы данные между Content Brain, production, approval, publishing, analytics и learning передавались внутри FactoryOS без ручного copy/paste, при сохранении human approval и spend controls.

## v4.0 acceptance scenario

На телефоне пользователь может:

1. открыть FactoryOS и Autopilot / Cycle Control;
2. увидеть автоматически собранные signals или создать cycle из доступных signals;
3. получить shortlist и verified idea через Content Brain;
4. без ручного переноса создать связанный production job;
5. получить competing variants + Content Package + QA/source provenance;
6. дойти до `waiting_approval`, где Autopilot обязательно останавливается;
7. вручную Approve и получить idempotent publishing queue item;
8. выполнить отдельное явное schedule/publish действие и сохранить реальный external receipt;
9. получить только реально пришедшие performance metrics;
10. связать metrics обратно с cycle / idea / job / package / variant / workflow;
11. сформировать evidence-bounded learning;
12. при достаточном evidence создать improvement proposal для controlled experiment;
13. запустить следующий child cycle с текущим owner-approved workflow.

## Реализовано

- Persistent `factory_cycles` + cycle event ledger.
- Полная lineage: source signals → idea → job → workflow version → publish ID → performance → learning.
- Content Brain → production bridge без ручного copy/paste.
- Autopilot coordinator для signal/idea/production/package пути.
- Scheduled RSS collector создаёт готовый cycle из реально новых signals, но не запускает платную генерацию автоматически.
- Live Autopilot требует явного cost confirmation до paid LLM work; day/job budget guards остаются hard limits.
- Autopilot всегда останавливается на HUMAN APPROVAL.
- Approval не публикует: он только создаёт duplicate-safe publishing queue item.
- Publish receipt и performance snapshots автоматически синхронизируются в originating cycle.
- Learning строится только из persisted platform metrics; отсутствующие metrics не придумываются.
- Observed performance не считается causal proof. Улучшение workflow только создаёт proposal для v3.90 controlled experiment.
- Next cycle хранит `parent_cycle_id` и использует текущую owner-approved active workflow version.
- Mobile Autopilot / Cycle Control добавлен в EN / UK / RU.

## Acceptance evidence

Zero-spend CI acceptance реально прошёл полный deterministic путь:

```text
persisted signal
→ selected / verified idea fixture
→ Factory Cycle
→ linked production job
→ Production Pipeline 2.0 variants
→ Content Package
→ QA / waiting_approval
→ explicit human approval
→ idempotent publishing queue
→ manual factual publish receipt fixture
→ persisted views / retention / completion metrics
→ cycle learning
→ next child cycle
```

Проверено дополнительно:

- до approval у cycle отсутствует publish ID;
- manual publisher требует внешний post ID/receipt;
- performance attribution содержит exact Factory Cycle ID и workflow version;
- next cycle не получает непроверенный treatment автоматически;
- smoke/CI не совершает платных LLM-вызовов.

## Production evidence

- Functional commit: `c02c568f3ad976286a7e8da5e7282013f06b4654`.
- Final production head: `3cd54bba6aeaf0be33af863525ec3202b4aab7aa`.
- GitHub CI: `39406148458` — PASS.
- Render deploy: `dep-dbbjsohsrm7s738a5bc0` — LIVE.
- Production startup: clean; Builder bridge ready; LLM provider configured.
- Repeated production `/health`: 200 OK.
- Release acceptance remained zero-spend: real paid v4 Autopilot and real social publishing were intentionally not triggered.

## Definition of Done

**DONE.** Без ручного переноса данных между внутренними модулями FactoryOS работает traceable путь:

```text
signal
→ idea
→ research
→ production
→ content package
→ HUMAN APPROVAL
→ publishing queue
→ factual publish receipt
→ real analytics
→ learning
→ controlled improvement proposal / next cycle
```

Human approval, explicit publishing, spend budgets, evidence boundaries и controlled workflow rollout сохранены.

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

## 2026-10-20 — v4.4 media foundation LIVE / Descript pilot PASS / Runway VERIFY pending

- Добавлен persistent async media-job lifecycle для Revideo: `queued → submitted → processing → ready/failed`.
- Сохраняются provider job ID, request/response, error, media URL, timestamps и связь с Revideo/project production job.
- Добавлены `FACTORY_VIDEO_STATUS_ENDPOINT` для provider polling и `FACTORY_VIDEO_CALLBACK_TOKEN` для защищённого callback completion.
- Revideo UI показывает текущий render status, блокирует повторный generate во время активной задачи и поддерживает explicit refresh; copy добавлен в EN/UK/RU.
- Готовый media URL сохраняется в Revideo и как Render Agent video artifact, поэтому результат виден в Worker Evidence.
- Zero-spend regression теперь проверяет полный async media lifecycle и Render Agent artifact; CI `39441923218` PASS.
- Production head `7edec23c0d0258abb4978fcfbeab272d4260b97c`; Render `dep-dbbnsjpsrm7s738fqbj0` LIVE; startup clean; repeated `/health 200 OK`.
- Проведён реальный Descript pilot: Agent Underlord создал 8-секундную vertical 1080×1920 / 30 fps композицию и Descript успешно опубликовал реальный 1080p Video output.
- Runway пока остаётся `VERIFY`: архитектура FactoryOS готова принять async Runway job через generic provider contract, но milestone нельзя закрывать до фактического Runway provider call из FactoryOS с сохранённым provider job/result.
- Human approval/publishing boundary не изменён; auto-publish не включён.

## 2026-10-20 — v4.2 + v4.3 DONE / Revideo MVP LIVE

- По итогам owner-review интерфейса зафиксировано отдельное ТЗ `FACTORYOS_V4_2_V4_3_SPEC.md`.
- v4.2: исправлена небезопасная обработка non-string UI values, расширены EN/UK/RU переводы и explanatory tooltips.
- Worker Results/Agent drawer теперь показывают фактический selected-job output, артефакт, run accounting, handoffs, media URL и provenance.
- Approval Studio объясняет Hook / Script / Sources / QA / Variant diff / Publish target / regeneration и отделяет legacy incomplete jobs от реальных review-ready packages.
- v4.2 commit `776266595cfd7a78d87490b4c9c6590006589fe1`; CI `39433576856` PASS.
- v4.3: добавлен Revideo workspace и persistence: source URL/transcript → structure analysis → originality guard → original rewrite → production job.
- Добавлены Transcript Agent, Structure Analyzer, Rewrite Strategist и provider-neutral transcript/video webhook contracts.
- Revideo не перезаливает source media по умолчанию, не имитирует identity/voice автора и не обходит human approval.
- External video generation разрешается только явно и только при configured provider + fresh Content Package; реальный URL сохраняется как Render Agent media artifact.
- v4.3 commit `f7d7245db3f303f90a395377e44c360bbeb9fa34`; CI `39434473401` PASS.
- Render `dep-dbbn5aui0phs738nl4pg` — LIVE; startup clean, provider configured, repeated `/health 200 OK`.
- Следующий этап: подключить реального video provider и провести один controlled Revideo media pilot без автоматической публикации.


## 2026-10-20 — v4.1 First Real LLM Pilot DONE / waiting for owner review

- Запущен первый real-world paid Factory Cycle на двух публичных source signals: Reuters + OpenAI.
- Pilot tag: `v4.1-real-world-pilot-2026-10-20-1`; cycle `15bea544-b055-44c6-84d4-833083c9befe`.
- Conservative preflight quote: **$0.4636**; hard cumulative ceiling: **$0.75**.
- Первый live проход обнаружил production-only SQLite lock в variant persistence после уже завершённого model call. Publish не создавался.
- Исправление: SQLite busy timeout 30s + устранение nested writer transactions в live Production Pipeline 2.0.
- Добавлен zero-spend regression, который проходит именно live persistence branch с deterministic fake workers.
- Pilot безопасно продолжен на том же cycle, без нового full-cycle запуска; already-spent provider usage включён в тот же cumulative cap.
- Финальный результат: **$0.188066**, **22 live runs**, **40,023 tokens**, `approval_gate_reached=true`, `publish_created=false`.
- Job: `d0eeac5e-3fea-4fd2-bd22-2f15878101c2`.
- Idea: **AI’s Next Competitive Test: Turning Model Output Into Product Adoption**.
- Hardening commit `7994b61f15c3d37dc80c70cf81dd80eeaafc6d6c`; CI `39424673537` PASS.
- Resume deploy `dep-dbbm5j0ae00c7399k3t0` — LIVE; repeated `/health 200 OK`.
- Следующий шаг намеренно не автоматизирован: owner открывает Approval Studio, проверяет конкретный script/package/sources/QA и только после этого отдельно решает, публиковать ли материал.


## 2026-10-20 — v4.0 Autonomous Content Factory DONE

- Добавлена persistent Factory Cycle lineage: signals → idea → job → workflow → publish → performance → learning.
- Закрыт главный handoff gap: verified Content Brain idea создаёт production job внутри FactoryOS без ручного переноса brief/source data.
- Autopilot ведёт cycle до готового Content Package/QA и обязательно останавливается на human approval.
- Live paid Autopilot запускается только после explicit cost confirmation; RSS collection может подготовить cycle, но не тратить provider budget автоматически.
- Approval/publishing/performance автоматически синхронизируются обратно в originating cycle.
- Learning использует только реальные persisted metrics и при достаточном evidence создаёт лишь controlled-experiment proposal, а не auto-rollout.
- Добавлен parent/child next-cycle lineage и mobile Autopilot / Cycle Control (EN/UK/RU).
- CI `39406148458` — PASS: полный zero-spend closed-loop acceptance + compile + HTML + JS.
- Functional commit `c02c568f3ad976286a7e8da5e7282013f06b4654`; final production head `3cd54bba6aeaf0be33af863525ec3202b4aab7aa`.
- Render `dep-dbbjsohsrm7s738a5bc0` — LIVE; clean startup, configured LLM provider, repeated `/health 200 OK`.
- Реальный paid v4 cycle и реальная соцсеть в release acceptance не запускались намеренно.


## 2026-10-20 — v3.90 Self-Improving Factory DONE

- Proposal schema расширена hypothesis, evidence и concrete allowlisted workflow patch.
- Добавлены immutable workflow versions и job-level control/treatment assignments до первого worker run.
- Добавлены factual outcome/cost/duration comparison и workflow attribution в performance feedback.
- Treatment promotion отделён от experiment result: rollout требует owner confirmation; reject и rollback сохраняют audit trail.
- Safety/spend/approval/publish invariants нельзя менять через experiment patch.
- Добавлен mobile-friendly Experiment Lab с EN / UK / RU интерфейсом.
- CI `39402528845` — PASS, включая zero-spend полный control/treatment → metrics → recommendation → rollout → rollback regression.
- Production `c9ef037db619b4e475bf9b66ed1c32442573a805` / Render `dep-dbbjeo1srm7s7389md60` — LIVE; startup clean, repeated `/health 200 OK`.
- Следующий milestone: v4.0 Autonomous Content Factory acceptance/closure.


## 2026-10-20 — v3.60 → v3.80 release train DONE

- v3.60 Approval Studio: mobile review queue, preview/evidence, approve/reject, reject reasons, audit history, variant diff, scoped regeneration and cost-before-rerun.
- v3.70 Publishing Engine: human approval separated from publish, persisted queue/schedule, stable idempotency keys, manual real-receipt baseline, webhook adapter and uncertainty-safe retry.
- v3.80 Performance Feedback Loop: real metric snapshots, published identity mapping, end-to-end attribution, cost/outcome and angle cohorts without invented metrics.
- GitHub CI `39391145024` — PASS: compile, zero-spend runtime regression, HTML structure and JavaScript syntax.
- Production commit `e94cfff4094221acaf4f61b8c10ba9e7adfa1c01`.
- Render deploy `dep-dbbi2m6k1f9s73bs9rk0` — LIVE; clean application startup, configured LLM provider and repeated `/health 200 OK`.
- Release verification did not execute paid LLM generation or real social publishing.
- Следующий milestone: v3.90 Self-Improving Factory.

## 2026-10-20 — v3.50 Content Package / Shorts Factory DONE

- Добавлен отдельный Content Package schema v1.0 и persistent storage.
- Selected production variant автоматически преобразуется в scenes, VO, SRT, title/description/CTA/hashtags, thumbnail concept и media brief.
- Source/fact-check provenance и measured provider/job cost сохраняются в package.
- Добавлен provider-neutral media adapter registry для TTS/image/video/stock/manual.
- Добавлен mobile-first Package Studio и ZIP/JSON export.
- Downstream dependency переведён на Content Packager manifest; stale package/media защищены invalidation fence.
- Zero-spend CI `39382663013` прошёл compile, runtime regression, HTML и JS.
- Production `54c17937242219d35c2df93f339a9dfba55802da` / `dep-dbbgu2rm8hqs738tvkog` — LIVE.
- Следующий milestone: v3.60 Approval Studio.

## 2026-10-20 — v3.40 Production Pipeline 2.0 DONE

- Linear script stage заменён на competing-variant workflow.
- Добавлены Angle Strategist, Hook Generator, Fact Checker, Hook Optimizer и Editor.
- Production batch создаёт 3 angle/hook/script variants и сохраняет отдельные artifacts/provenance.
- Fact Checker и structured QA сохраняют конкретные findings: unsupported claim, weak hook, duplicated angle, missing source, slow intro, unclear CTA, excessive length, unsafe/sensitive claim и fact conflict.
- Variant Studio доступен на desktop/mobile: comparison, findings, decision reason, cost, manual selection и partial rerun.
- Partial rerun fence возвращает job к script stage и инвалидирует downstream path.
- CI `39380515484` — PASS; zero-spend variant regression прошёл без provider calls.
- Render deploy `dep-dbbgkaei0phs738fog7g` — LIVE; application startup clean, provider configured, repeated health checks 200.
- Следующий milestone: v3.50 Content Package / Shorts Factory.

## 2026-10-20 — v3.30 Content Brain DONE / v3.40 next

- Завершена цепочка Signal Collector → Scout → Researcher → Idea Strategist → Idea Verifier → Idea Queue.
- Добавлен configurable scheduled RSS adapter без hardcoded внешних источников.
- Добавлен mobile-first Content Brain workspace с provenance, decisions и переходом выбранной идеи в production job.
- CI run `39379172168` — PASS.
- Production deploy `dep-dbbgdagubc0c73d4qbng` — LIVE, startup чистый, `/health` = 200.
- Release verification осталась zero-spend; платный Content Brain запуск выполняется только по явному действию пользователя и внутри budget guards.
- Следующий milestone: v3.40 Production Pipeline 2.0.

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

**NEXT: v4.4 — Runway runtime binding + controlled end-to-end Revideo media pilot**

v4.4 media foundation уже live: persistent async media jobs, provider polling/callback, UI status и Render Agent artifact path проверены; отдельный реальный Descript composition/publish pilot прошёл успешно.

Следующий обязательный acceptance:

`public source URL + transcript → original rewrite → production variants → fresh Content Package → real Runway generation job → optional Descript assembly/edit → Render Agent media artifact → human review`.

Milestone v4.4 остаётся **IN PROGRESS**, пока FactoryOS не выполнит и не сохранит фактический Runway provider job/result. Публикация остаётся отдельным explicit действием после human approval; отсутствие provider credentials/status должно отображаться честно, без fake media.
