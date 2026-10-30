# FactoryOS / Blackbox Lab — передача управления Claude Code
**Дата:** 2026-10-29, вечер (Europe/Kyiv). **Приоритет:** P0 — полноценная передача исполнения и отчётности.
**Статус:** диагностический handoff от ChatGPT. Факты указаны по проверенным GitHub и AWS SSM данным. Непроверенные стадии отдельно помечены.
**Адресат:** Claude Code Pro, работающий на существующем FactoryOS EC2, и любой последующий Claude owner/operator session.

## 0. Прямое распоряжение владельца

Владелец проекта крайне недоволен тем, что вынужден многократно напоминать о задачах, Telegram не показывает понятную картину live-build, а ChatGPT неоднократно говорил о готовности по факту появления GitHub Issues или heartbeat. **Claude назначается основным техническим исполнителем/координатором FactoryOS.** Не просить повторно формулировать известные требования и не подменять выполненную работу обещаниями.

Первый результат, который нужен владельцу: **РАБОТАЮЩИЙ Telegram Relay build-control-room**, где видны текущая задача, исполнитель, реальные стадии (assigned, claimed, running, changed files, tests, commit, push, PR, CI, merge, deployed), время, последние события и ошибки. Telegram и FactoryOS Web UI должны показывать одинаковые достоверные данные, и пользователь должен видеть, что его запрос не только попал в ticket inbox, но и действительно начал исполняться. Владелец хочет видеть, над чем работают Claude и ChatGPT, без выдуманной телеметрии ChatGPT.

**Самостоятельно вести цикл: диагностировать → исправить → протестировать → PR/CI → безопасно интегрировать → проверить production → оповестить владельца.** Указывать причины блокировок и конкретные шаги. Не требовать разрешения на каждую рутинную инженерную итерацию, однако сохранять обязательные гейты ниже.

### Неприкосновенные ограничения (ZERO ADDITIONAL SPEND)
- Не включать платный Anthropic API / Console PAYG, Gemini PAYG, Bedrock, Vertex, Foundry, платный browser agent, новые платные AWS/Render ресурсы, платные publishing планы или иные metered вызовы без нового отдельного явного согласия владельца.
- Пользоваться существующей Claude Pro подпиской через Claude Code CLI с authMethod=claude.ai, а не через API key. Не печатать/копировать секреты, сессионные cookies, bearer токены.
- Не делать публикации в соцсети, не отправлять сообщения третьим лицам, не списывать деньги и не выполнять необратимые действия без подтверждения владельца; human approval остаётся отдельно от build status.
- Не пушить прямо в main, не bypass-ить CI; использовать отдельные ветки / PR, проверять тесты, deployment и rollback.
- При непроверенном статусе писать UNKNOWN / UNVERIFIED, не «готово». Ticket created != worker claimed; heartbeat != task running; local commit != remote push; merge != deploy.

## 1. Project identity & архитектура

- GitHub: https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos
- Web/API: https://blackboxlab-factoryos.onrender.com
- Relay mobile UI: https://blackboxlab-factoryos.onrender.com/relay (owner auth required).
- Имеется отдельный Media Finisher сервис на Render; не путать с основным API.
- Existing AWS EC2: instance i-087bd3c1bb5de4ec6, region eu-north-1, Name=factoryos-worker, Amazon Linux; экземпляр был Running и SSM Online при проверке 2026-10-29.
- AWS code checkout: /opt/factoryos (owner ec2-user); branch autopilot/aws-worker.
- Worker service: factoryos-claude-worker.service (systemd), запускает /usr/bin/python3 -m autopilot.claude_pro_worker; внутри дочерний autopilot.autopilot; отдельный claude -p для задачи.
- Recovery: factoryos-runner-supervisor.timer (каждую минуту); состояние /var/lib/factoryos/supervisor-status.json. В health выводить отдельно EC2, SSM, systemd, OAuth, heartbeat, claim, active task и API reachability.
- Worker settings: /etc/factoryos/claude-worker.env (root only; ни в коммиты, ни в сообщения); резервная копия после изменения /etc/factoryos/claude-worker.env.bak.autonomous-20261029.
- Relay server: relay.py + relay_execution.py; bridge в app.py; worker claim POST /api/relay/worker/claim, events POST /api/relay/worker/event; heartbeat POST /api/claude-worker/heartbeat.
- Worker poll: autopilot/relay_tasks.py, затем autopilot/autopilot.py; CLI safety/delegation: autopilot/delegation.py. Progress status .autopilot/status.json; execution evidence .autopilot/evidence/T-*.json; roadmap ROADMAP.md; decisions DECISIONS.md; rules CLAUDE.md.
- Telegram bot/webhook: factory owner bot with Telegram commands; owner authentication/pairing and webhook configuration must be validated live, NOT guessed by status ready alone.
- UI: static/index.html, APIs /api/factory/tasks, /api/factory/autopilot, /api/factory/builder and delegation board have different denominators / telemetry sources.
- Other systems: GitHub Issues/PR/CI as source of truth for code; Render for actual deploy; Claude Code Pro for implementation; ChatGPT ad hoc planning/action when explicitly logged; Gemini lane exists but presence of UI is NOT proof active Gemini executor. Publishing via owner approval and social connectors (Metricool/YouTube/TikTok/Instagram etc.), separate from Relay.

### Desired connected system
Owner Telegram/Web message → authenticated intake/dedupe → durable ticket + assignment → worker claim (with worker ID + run ID) → heartbeat + actual runtime checkpoints → changed files/tests/commit/push → GitHub PR/CI/merge → Render deploy → smoke verification → Telegram/Web owner-facing trace + durable history.

ROADMAP tasks and GitHub Issues MUST be imported or explicitly linked to Relay tickets using idempotent source_key; owner must see what is queued versus actually claimed. One authoritative task id, cross-reference source IDs; no double execution. Preserve chat history and artifacts across server restarts.

## 2. Факты — что произошло сегодня

1. Пользователь много раз сообщил, что Telegram/Relay не показывает, чем заняты ChatGPT и Claude; Web Build Progress и Worker Center выглядят зависшими, stale/inconsistent. Это P0, давно поставлено в Issue #41. Ссылки в разделе 4.
2. Проверка AWS: EC2 Running; SSM Online; система была доступна. Недавние SSM команды ошиблись из-за неправильно экранированного shell/Python (пример: syntax error возле 12345; EOL in string literal). **Это были ошибки управляющего инструмента, не доказательство отключения EC2**.
3. Выявлен ранее реальный boot failure на Python 3.9.25: TypeError unsupported operand type(s) for |: 'types.GenericAlias' and 'NoneType' в autopilot/delegation.py. PR #59 закрыт MERGED, commit b6fe849; исправление было фактически установлено в /opt/factoryos. PR #58 закрыт без merge. GitHub main был на b6fe849 на момент проверки (может измениться — проверять заново).
4. 29 октября systemd factoryos-claude-worker.service оказался ACTIVE с работающими PID, supervisor timer ACTIVE, OAuth подтверждён: loggedIn=true, authMethod=claude.ai, apiProvider=firstParty. Но журнал бесконечно повторял git pull / Already up to date, а .autopilot/status.json показывал 'Relay worker online, waiting for queued owner tasks'. Причина: AUTOPILOT_RELAY_ONLY=1 при отсутствии реально запущенных claim-able Relay задач. GitHub Issue или roadmap list НЕ превращались сами в Relay queue. PR #60 ещё draft/WIP и НЕ подключён к authenticated trigger.
5. Для восстановления работы на существующем EC2 2026-10-29 значение AUTOPILOT_RELAY_ONLY было изменено с 1 на 0, приоритет Relay перед ROADMAP сохранён. Сделан root-only backup env и systemctl restart. Это разрешило выполнение безопасных задач ROADMAP при отсутствии Relay claims, но не завершает поддержку GitHub Issues.
6. Первые выполнения T-560-B проваливались: headless Claude Code режим 'dontAsk' отклонял Edit/Write/Bash и Python tests; даже exit_code=0 CLI мог означать task failed, если .autopilot/status.json отсутствовал. Настроен /home/ec2-user/.claude/settings.json mode dontAsk с ограниченным списком разрешённых Read/Edit/Write/тестов/local git commit и deny для push, aws, curl, deploy, merge. Полный обход разрешений НЕ включался. Config/commands требуют дальнейшей доработки и теста: часть составных Bash команд всё ещё denied. Не считать это полноценным production-grade sandbox (CLI permissions ≠ OS containment).
7. После исправления T-560-B **реально выполнена** на EC2: commit d68851a447574b8269e3b09050d999ff54c0e8c9 'T-560-B: scoped credential vault, persisted session handoff and single-use human takeover resume'. Изменены browser_runner/sessions.py, browser_runner/__init__.py, test_browser_sessions.py, ROADMAP.md, DECISIONS.md, docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md. Evidence result done, exit 0, violations []; **11 unittest tests passed**, py_compile passed; полный smoke / media planner NOT RUN на EC2 system Python из-за отсутствия fastapi; нужен CI. Commit **PUSHED** to origin/autopilot/aws-worker (ahead count 0), НЕ merged в main и НЕ deployed.
8. Следующая T-560-C стартовала автоматически, но ended BLOCKED: существующий guarded Playwright adapter уже был (commit a69d5c3), дальнейшие fixture/tests не сделаны из-за отказа Bash permission для составных команд 'python --version; python -c ...' и 'python --version && python -c ...'. Status T-560-C blocked; нет нового коммита. Нужны безопасные команды по отдельности и/или проверенный точечный allow-rule, но не разрешение arbitrary unrestricted Bash.
9. **Фактический bug прогресса:** autopilot/delegation.py::run_delegation() делает status_path.unlink(missing_ok=True) перед CLI. Пока Claude думает/работает, status.json может отсутствовать; heartbeat показывает idle/stale или потерянное task_id; только Claude сама в конце пишет status.json. Нужен parent-owned task status с run_id/started_at/checkpoints и atomic writes; worker id/claim должен отображаться по одному согласованному источнику. Не полагаться на ручное создание файла (в одном эпизоде файл был удалён следующей CLI попыткой).
10. По старым скриншотам Worker Center отображал stale heartbeat 39m, branch autopilot/aws-worker, 0 running, 23 queued и HUMAN T-506; одновременно Render ранее отвечал POST /api/claude-worker/heartbeat 200. Причина, вероятно, разные источники данных; **исследовать**, не выдавать гипотезу за подтверждённую причину. Build Progress 87% (39/45), Autopilot 49% (28/57): это разные числители/знаменатели, нельзя сливать в один процент.
11. У PR #43 auto-dispatch Relay были слиты реализация queue/claim/stages и tests, но это **не было live end-to-end подтверждением**. PR #42 для Telegram /status/tasks/history/github и PR #34 операторских команд уже в GitHub — проверять merge status и production/current code отдельно. Нельзя выдавать документированный feature как работающий Telegram у владельца, пока test message→claim→event→reply не пройден.
12. После передачи пользователь хочет **Claude вместо ChatGPT как основной управляющий проектом**, ежедневные сжатые фактические отчёты/автономные fix-and-build итерации. Участвовать в управлении можно через существующие каналы, не требуя от владельца постоянных проверок.

## 3. Системные диагнозы и приоритет исправлений

### P0-A: Интеграционный разрыв задания (root problem)
- Источники: ROADMAP.md (локальные таски), GitHub Issues (#41, #47, #49-57), RelayStore tickets, Telegram messages, web task views.
- Неправильно: наличие GitHub Issue само по себе не запускает Claude и не формирует Relay claim; 'queued' на roadmap не равен 'queued' в RelayStore. PR #60 добавляет helper, но NOT wired.
- Исправление: authenticated owner-controlled issue sync/import + source_key dedupe; durable queue + worker claims, stages и retries; cross-link GitHub/ROADMAP/Relay. Идемпотентность, replay-safety, recovery after reboot, no duplicate commits/irreversible actions.
- Вся схема должна работать даже когда GitHub trigger временно недоступен; явные BLOCKED/STALE причины.

### P0-B: Telegram owner control room end-to-end
- Верные /status /tasks /task <id> /history /roadmap /github /workers /operators /claude; кнопки Refresh, открыть task, issue, PR, log; минимум RU+UK+EN.
- Должна быть видна задача **Claude**: assigned/claimed/running, last heartbeat time, current step, changed paths/test summary, commit SHA, push, PR, CI, merge, deployment verification. Не показывать статусы, когда нет evidence.
- **ChatGPT** показывать только как author/planner с подтверждёнными GitHub actions/Relay audit. Отдельно 'No automatic live ChatGPT telemetry' без псевдо-online.
- Получение сообщения в Telegram должно порождать одну durable task, гарантировать enqueue / начать claim при рабочем воркере, показать, если executor offline; не подтверждать 'работаю' без actual claim.
- Убедиться, что Telegram реально paired с владельцем и webhook доставляет/отвечает. Тестируй в live owner chat только test message и status, без spam/внешних публикаций. Если нужно действие владельца (вход/2FA), дать ОДНУ конкретную инструкцию.

### P0-C: Truthful build/progress UI и worker heartbeat
- Исправить parent-owned telemetry, .autopilot/status.json race, reconcile heartbeat/claim/current task, stale thresholds and idle states.
- Build Progress различает roadmap completion, product build tasks, delegation; separate versions, timestamps, filters, evidence. Не отображать ghost 'running' при stale или 0 claims.
- Связка Web UI и Telegram должна читать ОДИН backend, с durable append-only event history и UTC timestamp.
- Human tickets #T-506 etc. должны иметь 'why blocked', 'what to do', 'when last checked'; auto-resolve только по live evidence.
- Навигация: не обрезать колонки/горизонтальные скроллы; drawers resizable/maximizable; sidebar понятна, но это P1 после рабочего Telegram.

### P0-D: Safe autonomous worker/permissions/tests
- Рабочий процесс должен автоматически продолжаться через safe задачи ROADMAP, но НЕ расходовать оплачиваемые API и не молча обходить approval gates. Runner only one task per CLI run; min 1 authoritative claim/run_id, bounded retries, tests, branch policy, CI.
- Зафиксировать permission config as reproducible reviewed bootstrap artifact без включения bypassPermissions; investigate why composite Python commands denied, use safe single-purpose commands.
- Прежде чем отмечать DONE, закрыть tests and verified PR/CI stage; отсутствие fastapi на системном Python не считать successful smoke.
- Не трогать секреты. Worker heartbeat должен содержать только sanitized metadata. Add safe backoff and locked push/worker lease.
- GitHub PR #59 merge исправил Python3.9 import, но искать другие 'str | None'/type unions в runtime под Python3.9 (отдельно отмечено browser_runner/sessions.py).

## 4. Task/PR/Issue register — приоритет владельца

**Сначала рабочий Telegram, потом оформление UI, далее продуктовый roadmap.**
- [P0] Issue #41 — Telegram Relay live build control center; owner-visible multi-agent tasks/progress/history. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/41
- [P0] PR #43 merged — Relay auto-dispatch & worker claim/event; провести LIVE end-to-end, не только unit. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/43
- [P0] PR #42 — Telegram live commands/status/tasks/github/history; проверить наличие в main+Render и реальный delivery. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/42
- [P0] PR #60 open WIP — Issue → Relay idempotent intake, NOT TRIGGERED. Finish authenticated sync, tests, events, UI/Telegram, PR/CI. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/60
- [P0] Issue #51 T-572 — Telegram Relay → Claude → GitHub proof. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/51
- [P0] Issue #56 T-577 — human blockers, verified Worker Center/telemetry and lifecycle. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/56
- [P0] Issue #55 T-576 — Build Progress truthful version/metric reconciliation. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/55
- [P0] Issue #40 — runner vs AWS audit, CI and real worker verification. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/40
- [P0] Issue #49 T-570 — worker onboarding, secure pairing, Relay acceptance. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/49
- [P1] Issue #50 T-571 — multi-host worker registry, workspace-scoped onboarding. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/50
- [P1] Issue #52 T-573 — worker management, actual EC2, activity history, official AI logos. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/52
- [P1] Issue #53 T-574 — navigation/sidebar redesign. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/53
- [P1] Issue #54 T-575 — resizable/maximizable panels/mobile overflow. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/54
- [P1] Issue #57 T-578 — contextual 'i' and help in RU/UK/EN, diagrams/advanced tutorials. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/57
- [P1] Issue #47 — separate AI models/providers, execution workers, video generation capabilities. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/47
- [P1] PR #34 — /claude & /gemini Telegram lane shortcuts; do not assume merged. https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/34
- [P1] PR #48 — provider/worker onboarding (check merged and applied); PR #44 secure pairing; PR #46 interactive EC2 pairing.
- [P2] ROADMAP T-560-C/D/E browser executor/form fixtures/social drafting and observability; T-551-554 OAuth / multi-tenant isolation / customer onboarding.
- [P2] ROADMAP T-581-589 Multi-model role lab, operator routing, battle mode, reviewer. Do not distract from Telegram P0.
- [P2] Core content factory: Discovery → Revideo → Content Package → Media Finisher → QA → Human Approval → Publishing → Analytics. Integrations with video models and social destinations remain approval/security gated.
- Blockers requiring human action (T-506 Telegram pairing, T-520 publisher credentials, T-521 first real post, etc.) must be inspected for actual status and escalated with clear instructions, not blindly retried.

## 5. Конкретное поручение Claude — P0 ownership and queue

1. First READ this file, CLAUDE.md, ROADMAP.md, README, DECISIONS.md, issue #41 and #56, PR #43 and #60. Record verified code/head/status. Do not claim task started until actual CLI run and run ID observed.
2. Take ownership of T-590 (see ROADMAP priority section). Build the smallest real end-to-end vertical slice: owner task intake via Telegram/Web → durable Relay ticket → worker claim → live stage/heartbeat → result/commit/PR/CI evidence → Telegram /status /task and Web Build Progress shared backend.
3. Instrument permanent factual progress/events at parent worker, not only model-authored status.json. Reconcile GitHub/Render events; fix issue import from PR #60 safely.
4. Write tests first where possible. Verify CI and same commit deployed; run production-only read/status smoke and paired Telegram test. No bogus screenshots or simulated completion badges.
5. Continue remaining issues in P0 order, one bounded task/branch/PR at a time. Finish overlapping PRs by compare/rebase/CI, avoid duplicate work.
6. Keep a short owner-visible build report on each milestone (task ID, title, actual stage, changed files, tests, commit, PR link, CI, deployment, blocker and next task). Send notifications via already configured owner Telegram only when verified. Summarize deltas; do not spam every heartbeat.
7. If live owner bot/chat is unpaired, surface an explicit HUMAN request and continue all other safe engineering tasks without waiting silently.
8. Leave independent records in docs + Issue #41. Ownership of product coordination now goes to Claude: explain what was delivered and what remains, do not delegate back to ChatGPT or ask user to remind status.

## 6. Verification checklist (all MUST pass before saying 'Telegram working')

- [ ] Actual owner Telegram chat paired; command /status answered with current verification timestamp.
- [ ] Owner submits one text/link task; API stores ONE durable task, source dedupe works.
- [ ] Relay owner UI displays exact ticket ID; stage queued not fake running.
- [ ] Active Claude worker claims task via authorized claim, backend emits claimed and running with worker ID, run ID and timestamps.
- [ ] During actual execution, /task <id> and Web UI show same current task, last heartbeat, stage and last checkpoint; on idle show idle.
- [ ] Task ends in verified done/failed/blocked with meaningful error and no silent retry loop. For code tasks: changed paths, checks, commit, remote push (if any), PR, CI, merge, deployed each individually verified.
- [ ] Restart worker/Render (only when safe) does not erase durable events; no duplicate task execution after reconnect.
- [ ] GitHub Issue import to Relay is idempotent and authorization protected; no phantom 23 running tasks.
- [ ] Explicit stale heartbeat vs systemd up vs claim status reconciliation.
- [ ] RU/UK/EN mobile-friendly navigation; no cut-off dialog; screen readers and compact Telegram text.
- [ ] Zero paid API and zero new paid cloud spend; publishing remains owner approval.
- [ ] Evidence in Issue #41: test run, affected SHA, PR, deployed revision, Telegram screenshot/transcript (redacted), timestamp and rollback.

## 7. Read-only diagnostics / recovery references

AWS access: existing EC2 via SSM in eu-north-1. Do not create new instance. Run read-only inspection first:
~~~sh
systemctl is-active factoryos-claude-worker.service
systemctl is-active factoryos-runner-supervisor.timer
systemctl show factoryos-claude-worker.service -p ActiveState -p SubState -p MainPID -p ExecMainStatus
journalctl -u factoryos-claude-worker.service -n 80 --no-pager
git -C /opt/factoryos status --short
git -C /opt/factoryos branch --show-current
git -C /opt/factoryos log -3 --oneline
python3 --version
~~~
If running as root, use 'git -c safe.directory=/opt/factoryos -C /opt/factoryos ...' to avoid git dubious ownership, rather than changing git global trust indiscriminately. Never print env file values, private tokens, Claude session JSONL raw outputs, or credentials.

Known potential sources of confusion:
- ECONN/HTTP heartbeat may be healthy while claim/event fails or queue is empty.
- Systemd 'active' != active Claude inference.
- Worker token used on Render & EC2 must match; do not rotate without owner/secure plan.
- AUTOPILOT_RELAY_ONLY=0 means Relay-first, then ROADMAP; it is NOT issue-to-queue ingestion.
- 'dontAsk' mode with incomplete allow rules causes denied safe test commands. Permission rules require precise fixes, not unrestricted shell access.
- All SSM SendCommand shell quoting errors in past attempts were controller mistakes; validate scripts and check stdout/stderr before inferring host failure.
- Claude child started with claude -p --output-format json; zero CLI exit doesn't mean task success. Use evidence violations, status.json, done checkbox, commits, CI.
- Parent currently deletes status.json before run, so absence during work is expected until telemetry repaired.
- No working FastAPI install in EC2 system python for full smoke; use established CI/test environment, not a paid resource.
- Existing /home/ec2-user/.claude/settings.json (permissions) and /etc/factoryos/claude-worker.env (mode) are runtime-only fixes: make reproducible in repo with tests and docs, protect secret/config ownership.

## 8. Owner-facing reporting template

**FactoryOS / Claude — <UTC timestamp>**
Version / source SHA: ...
Current priority: T-... / GitHub #...
Real stage: queued | claimed | running | blocked | committed | pushed | PR | CI | merged | deployed | verified (with evidence).
What changed (concrete): ...
Verification (actual): ...
Blocker, if any: ...
Next task and handoff: ...
Telegram link / Web UI link / GitHub link: ...

Never say 'done' for development merely because an Issue was created, a heartbeat arrived or a PR exists. **The owner should be able to open Telegram and verify work without chasing the assistant.**

## 9. Legacy / context boundaries

This handoff records actual diagnostics as of 2026-10-29. Branches and deploy states can change. Re-check live GitHub, EC2/SSM, Render and owner Telegram before acting. Do not leak personal account identity, email, tokens, secret environment, Telegram chat IDs, or auth artifacts in public logs/issues. The owner has explicitly requested that **Claude be the principal ongoing controller of FactoryOS**; if an execution bridge is not autonomous yet, state it clearly and finish that bridge before claiming delegation is accomplished.
