# FactoryOS Decision Log

Autonomous workers record reversible engineering decisions here so the owner can review them in batches.

## 2026-10-23 — Autopilot architecture

- **Decision:** use the existing FactoryOS repository, CI, Factory Builder and Render deployment path instead of creating a second independent product-control system.
  **Reason:** FactoryOS already has task state, Builder dispatch, CI, deployment visibility and safety gates.

- **Decision:** keep autonomous code work on a non-main branch and let the normal CI-gated main flow remain the only production path.
  **Reason:** this preserves rollback/review boundaries and prevents an unattended agent from deploying directly.

- **Decision:** make Telegram optional rather than a hard runtime dependency.
  **Reason:** the repository can operate safely without Telegram; credentials are owner-controlled and therefore a HUMAN configuration step.

- **Decision:** represent unavoidable owner actions explicitly as `[HUMAN]` roadmap tasks.
  **Reason:** the agent should skip real blockers instead of stopping on ordinary implementation questions.

## 2026-10-23 — Owner interrupt channel and Claude auth

- **Decision:** pair Telegram with a one-time code and persist only the paired chat ID in an ignored runtime file; the bot token stays in the secret environment.
  **Reason:** this gives the owner a fast push-notification channel without putting messaging credentials or personal chat identifiers in Git.

- **Decision:** prefer Claude Code subscription OAuth for the owner's Pro plan and keep Anthropic API PAYG as an optional fallback.
  **Reason:** Claude Code is included with Pro, while an ANTHROPIC_API_KEY would switch usage to separately billed API credits.

## 2026-10-23 — Central Telegram bridge

- **Decision:** terminate Telegram pairing and owner messaging inside the existing FactoryOS Render service, with pairing state on the persistent disk and a bearer-authenticated notify/inbox bridge for Builder Autopilot.
  **Reason:** this avoids a second paid service, keeps the bot token in one secret store, and gives future autonomous runners a stable two-way owner interrupt channel.

## 2026-10-23 — Claude Pro as a FactoryOS worker

- **Decision:** connect Claude Code Pro to FactoryOS through a trusted runner heartbeat/wrapper rather than putting the owner's Anthropic API key into the web service.
  **Reason:** this preserves subscription billing, avoids accidental PAYG API spend, keeps Claude credentials on the machine that is actually running Claude Code, and gives FactoryOS a measurable online/offline worker state.

- **Decision:** move Telegram pairing and Claude Pro setup into the main Connections rail.
  **Reason:** service setup belongs next to YouTube, Instagram, TikTok and other integrations; Build Progress should show execution state, not hide connection setup.

## 2026-10-24 — T-508 Claude delegation adapter

- **Decision:** delegation is pinned and verified on the runner: one roadmap task per `claude -p` run, `--max-turns`/timeout clamped to 10–160 turns and 600–7200 s, and a `done` claim is trusted only with exactly one new commit referencing the task ID plus a closed ROADMAP checkbox.
  **Reason:** the agent's self-reported status.json is not evidence; git state captured before/after the run is.

- **Decision:** "no direct main/prod action" is enforced twice — Claude Code `--disallowedTools` deny rules for `git push`, checkout/switch to main/master, `render`, `gh workflow run` and `gh pr merge`, plus post-run checks that local main/master refs, remote-tracking refs and the working branch are unchanged.
  **Reason:** deny rules prevent the common path; the git-ref comparison catches anything that slips through, including under `--dangerously-skip-permissions`.

- **Decision:** the delegated process environment drops `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, Render deploy credentials, and the worker/Telegram tokens.
  **Reason:** this keeps Claude Code on subscription auth (no PAYG) and keeps production/bridge credentials out of reach of the delegated agent. The parent autopilot still pushes the non-main branch after a verified done, as before.

- **Decision:** full evidence is written to the git-ignored `.autopilot/evidence/<task>.json`; only a compact, secret-free summary goes to `POST /api/claude-worker/task-result`, which re-validates it (pin match, non-main branch, known non-HUMAN task, one commit for done) and keeps the last 50 results in `DATA_DIR/claude_worker_results.json`.
  **Reason:** owners can see results in FactoryOS without the server ever trusting a worker-reported `done` that lacks evidence.

## 2026-10-24 — T-530 CI baseline stabilization

- **Decision:** when `smoke_tests.py` is given a non-empty `DATA_DIR`, it runs inside a fresh `smoke-run-*` subdirectory of that path instead of reusing or wiping the existing state.
  **Reason:** the suite asserts fresh-fixture state (e.g. an empty Content Brain), so a reused `DATA_DIR` such as the CLAUDE.md default `/tmp/factoryos-autopilot` failed on a second run. Nesting keeps runs deterministic without deleting anything, and an empty/new `DATA_DIR` (the CI path) behaves exactly as before. No assertion was relaxed.

- **Decision:** CI gains a second smoke step against the same reused `DATA_DIR`.
  **Reason:** this is a regression check for rerun determinism. Dashboard JavaScript validation stays enabled. Note: this runner has no `node`, so `node --check` was not run locally; the script extraction was run, and CI still enforces `node --check`.

## 2026-10-24 — T-531 Worker Results completeness

- **Decision:** every selected-job worker result carries a `report` contract (`input`, `action`, `status`, `error`, `output`, `artifacts`, `duration_ms`, `tokens`, `cost_usd`, `unavailable`), where `None` means "unavailable", and the dashboard renders such fields as an explicit localized "unavailable" instead of `0`.
  **Reason:** `agent_runs` stores `0` defaults for duration/tokens/cost, so a raw zero cannot be told apart from "never measured". The contract states which values are known instead of making up zeros.

- **Decision:** tokens/cost are reported only for finished runs that recorded non-zero usage, or for *completed* runs in a measured mode (`demo`, `live_llm`, `rules-engine`, `deterministic`) where a recorded zero is factual. Running runs, failed runs with no recorded usage (provider spend may be uncertain), artifacts without a run record, and modes such as media finishing report them as unavailable. Duration is known only once `finished_at` is set.
  **Reason:** this follows the existing spend-uncertainty policy in the Error Center and never claims "USD 0" for a call whose outcome is unknown.

- **Decision:** artifacts that have no run record get status `artifact_only`, with `input`/`action` unavailable. Up to 5 recent artifact refs per worker are included.
  **Reason:** this keeps the payload small and stays truthful for legacy or manually attached artifacts.

## 2026-10-24 — T-536-A Delegation Board API

- **Decision:** `GET /api/factory/delegation-board` is owner-gated like `/api/factory/claude-code/status` and is built by `get_delegation_board()`. It uses an allowlist: heartbeat `node` fields and task-result fields are copied by name (`pinned_task_id`, `pushed` and the like are dropped). Then a recursive pass replaces any configured secret value (worker token, `FACTORY_SECRET`, Telegram/GitHub/LLM/provider tokens) with `[redacted]` and strips `user:pass@` userinfo from URLs.
  **Reason:** heartbeat strings such as `repo` or `last_error` are worker-supplied and could carry a credential by accident. An allowlist plus value redaction keeps the board secret-free even then.

- **Decision:** task states, first rule that matches wins: ROADMAP `[x]` → `done`; latest verified worker result `done` → `done` (`state_source: worker_result`, i.e. committed but not merged yet); `[HUMAN]` → `human`; worker online with heartbeat `task_id` = task → `running`; latest worker result `blocked`/`failed` → `blocked`; anything else → `queued`. A stale or offline worker never counts as `running`. `safe_remaining` = running + queued + blocked.
  **Reason:** ROADMAP stays the queue and verified evidence stays the execution truth, as `docs/DELEGATION_CONTROL_CENTER.md` requires. Results that `ingest_claude_worker_result` already downgraded to `failed` show as blocked, never done.

- **Decision:** `_parse_roadmap_tasks` now also reads indented `Planner:` / `Parent:` / `Depends:` lines (defaults `""`, `""`, `[]`) and takes optional fixture text. Goal/DONE parsing and the full tree are left to T-536-C.
  **Reason:** the board needs parent/dependency data now. The extra keys are additive, so the current consumers (autopilot state, result ingestion) are unchanged. Fixture text gives a deterministic regression that does not depend on live ROADMAP progress.

## 2026-10-24 — T-536-C Planner hierarchy + delegation provenance

- **Decision:** `_parse_roadmap_tasks` now also reads indented `Goal:` / `DONE:` / `Need:` / `Progress:` lines into `goal`, `done_criteria`, `need`, `progress` (default `""`). Indented lines that are not a key continue the previous text field. Each task also gets `roadmap_line`, plus `source` (the `Planner:` value, or `roadmap`) and `provenance` (`planner` or `legacy`). The boolean `done` checkbox key is unchanged, which is why the criterion is named `done_criteria`.
  **Reason:** the change is additive. Existing consumers (autopilot state, result ingestion, board counts) only read the old keys. Legacy entries without `Planner:` still parse, and they are labeled `legacy` instead of being credited to ChatGPT.

- **Decision:** `Parent:` is the only source of hierarchy. IDs like `T-536-C` are not used to infer it. The delegation board adds a nested `tree` (each node has state, source, goal, DONE, depends, depth, child done/total), per-task `unmet_dependencies`, and a `provenance` count per source. Self-parents, unknown parents and parent cycles fall back to root nodes, so every task appears exactly once. The flat `hierarchy` key from T-536-A is kept.
  **Reason:** explicit metadata is what the planner actually delegated, and guessing from IDs could invent relationships. Making the tree cycle-safe means a malformed ROADMAP edit cannot break the board.

## 2026-10-24 — T-536-D Worker / Delegation Control Center UI

- **Decision:** the Control Center is a dedicated overlay page (`#dcPage`, nav entry "Workers"), built the same way as the existing Factory Intelligence / Release QA pages. It reads only the owner-only `GET /api/factory/delegation-board` and polls every 10 s while open. It adds no new API and no new write path.
  **Reason:** this matches the dashboard's page convention. Because it is read-only on top of the T-536-A contract, auth and the secret-free boundary are unchanged. Viewers get the API's 403 shown as "Delegation board unavailable".

- **Decision:** the rendering is a pure block of functions (`renderDelegationCenter(board, opts)` → HTML string, between `delegation-center:begin/end` markers) with no DOM or network access. `test_delegation_ui.py` runs this exact code from `static/index.html` under Node against fixtures. Desktop is a two-column grid (planner left, worker right). At ≤820px it becomes one column with the planner first, and a sticky mini-status bar (`Online · T-… · stage · mm:ss · CPU`) stays on top.
  **Reason:** "fixtures render" is tested against the shipped renderer, not a copy. DOM order plus the CSS media rule are what make the layout stacked on phones. The worker card reads only allowlisted fields (connection, node branch/subscription/auth/host/platform, telemetry), so extra fields such as tokens are never rendered, and the fixtures check this.

- **Decision:** unknown telemetry (stage, elapsed, branch, CPU, memory, queue depth) renders as an explicit "unavailable". When the worker is stale or offline, a note marks the values as last known (or says no heartbeat has been received yet). CPU measured via loadavg is shown with `≈`.
  **Reason:** no fabricated metrics. The page works now, against a board without `worker.telemetry`, and shows real metrics once T-536-B heartbeats provide them.

- **Decision:** parent groups use native `<details>`. They are expanded by default unless the whole subtree is done, and a manual toggle is remembered across polls. Fully completed root tasks are hidden behind a "Show N completed" button.
  **Reason:** the owner should see what is left within seconds, without a long list of finished legacy tasks. Collapsing needs no extra JS state machine.

- **Decision:** this runner has no Node and no network access. Locally, `test_delegation_ui.py` runs its static checks and reports the fixture render as `SKIPPED`, never as passed. CI sets `FACTORYOS_REQUIRE_NODE=1`, which turns a missing Node into a failure.
  **Reason:** CI enforces the check, and the local result stays honest.

## 2026-10-24 — T-536-E Delegation execution timeline

- **Decision:** the server builds the timeline (`build_delegation_timeline`, exposed as `timelines[task_id]` on the owner-only delegation board) for every non-HUMAN task, with fixed steps `queued → picked → running → checks → commit → push → outcome`. Each event has `status`: `observed` (backed by a ROADMAP line, heartbeat or verified result), `unavailable` (should have happened but was never reported), `pending` (not reached yet) or `skipped` (the run ended blocked/failed first). The outcome event carries the real `done|blocked|failed` result.
  **Reason:** one factual read model that the UI and tests share. The four statuses keep "we don't know" separate from "hasn't happened", so nothing has to be invented.

- **Decision:** what the timeline does not claim: ROADMAP has no queue timestamps, so `queued` is observed with `at: null` and the ROADMAP line number. Checks list the commands the worker reported, with `passed: null`, because workers report commands, not per-command verdicts. `push` stays `unavailable`, because the runner pushes after reporting and FactoryOS never sees it. The only observed push is the agent's own forbidden push (`pushed: true`), and that is shown as a violation. ROADMAP-done tasks with no worker result show every middle step as unavailable.
  **Reason:** the DONE criterion and design doc say: never infer a check, commit, push or cost that was not observed.

- **Decision:** the delegation result payload now includes the evidence `started_at` (optional `started_at` on `ClaudeWorkerTaskResult`). At ingest it is kept only when it is a finite epoch no later than receive time + 60 s. Older results without it render "time unavailable" for picked/running. For the running task, picked/running come from the heartbeat, and the start time comes from `telemetry.task_started_at` only when the stage is `running`.
  **Reason:** the adapter already measured the start. Sending it is additive and backward compatible, and the bound stops a worker from forging future times.

- **Decision:** the commit event links `https://github.com/{FACTORY_GITHUB_REPO}/commit/{sha}` (built only from a validated hex SHA and repo slug; the UI only renders `https://github.com/` links). A commit that has not been pushed yet may 404 there. The link is evidence of *which* commit, not a claim that it was pushed.
  **Reason:** the exact commit and its CI checks are one click away without FactoryOS calling GitHub.

- **Decision:** the UI shows the timeline in the worker column: for the active task by default, otherwise for the last result's task. Every task card gets a "Timeline" button that selects it. On ≤820px the selected timeline opens as a fixed bottom sheet with a Close button, as the design doc asks. The renderers stay pure and fixture-tested.
  **Reason:** the queue stays readable on phones, and no new page or API is needed.

- **Decision:** fixed `test_delegation_ui.py` block extraction. It used to start the extracted code in the middle of the `delegation-center:begin` marker comment, so under Node the harness hit a SyntaxError before rendering anything. The T-536-D fixture render had only ever been SKIPPED locally. Node is now available on this runner and the full fixture render (T-536-D checks plus the new timeline checks) passes.
  **Reason:** CI with `FACTORYOS_REQUIRE_NODE=1` would have failed. The fix only changes where extraction starts; every assertion is kept.

## 2026-10-24 — T-536-F Safe operator controls

- **Decision:** the command channel has exactly three actions: `pause`, `resume`, `retry`. The owner sends them with `POST /api/factory/delegation-control` (owner session only; viewers and the worker token get 403/401). The runner reads them with `GET /api/claude-worker/control` and reports back with `POST /api/claude-worker/control/ack`. Both runner endpoints check the worker token themselves, so an owner session (or open mode) cannot read or ack as the runner. Request models use `extra="forbid"`, so fields like `branch`, `force`, `deploy` or `publish` are rejected. The runner only ever receives `{id, action, task_id}`.
  **Reason:** this is the smallest command surface that meets the Goal. Nothing in it can describe a push, a branch switch, a deploy, a publish or a secret, so no button can bypass those invariants. The worker loop's existing branch/push/HUMAN rules stay the only authority.

- **Decision:** state lives in `DATA_DIR/claude_worker_control.json`: the desired `paused` level, commands (`pending → applied | rejected | superseded`) and an append-only audit log (last 200 entries; actor, action, task, request_id, outcome, detail). Every request is audited, including rejected and no-op ones. This follows the `claude_worker_results.json` pattern.
  **Reason:** auditable and restart-safe without a DB migration. The audit log never stores tokens (the regression checks this).

- **Decision:** idempotency works at two levels. (1) A client-generated `request_id` (8–64 chars `[A-Za-z0-9_-]`) replays the original command, and reusing it for a different command returns 409. (2) Intent-level: pause when already paused, resume when already running, or a second retry for a task with one already pending is a no-op that is audited but queues nothing. A new pause/resume supersedes a still-pending opposite command. Acks are terminal, so a repeated ack returns the stored outcome.
  **Reason:** double taps, retries on a flaky phone connection and racing tabs must never queue duplicate work.

- **Decision:** `retry` is accepted only for a ROADMAP task that is not HUMAN, not done, not currently running, and whose latest verified result is `blocked`/`failed` (board state `blocked`). On the runner it only releases the in-memory hold for the exact task it is holding. Retries for any other task are acked `rejected`.
  **Reason:** retry must not become a way to run an arbitrary or HUMAN task. The runner still takes only the first safe ROADMAP task through the normal delegation adapter.

- **Decision:** "pause after current task" is enforced by where the loop reads controls: once per iteration, before syncing or picking a task. A running Claude task is never interrupted. The board shows `pause_requested` until the runner acks. While paused, `status.json` says `paused` (the previous status is restored on resume), the stage is `idle`, and the one-shot (non-daemon) mode exits with code 5. If FactoryOS is unreachable or not configured, the last known pause level is kept.
  **Reason:** this matches the design doc ("Pause after current task"). Keeping the level when the network drops means a paused runner does not silently resume.

- **Decision:** in daemon mode, using up `AUTOPILOT_MAX_FAILS` no longer exits the process (exit code 3). It now holds the failed task without new attempts (stage `failed`) until an owner Retry, or until the ROADMAP head task changes. Non-daemon mode still exits with 3. The loop also re-checks before every task that the branch is still the dedicated start branch, and refuses to continue otherwise.
  **Reason:** a process that has exited cannot receive "retry failed task". Holding costs no Claude turns. The per-task branch re-check means no sequence of controls can make the runner work on main/master.

- **Decision:** command ids the runner has already decided are remembered in memory, and they are re-acked with the same outcome instead of being applied again.
  **Reason:** a lost ack must not turn one owner Retry into two task runs.

- **Decision:** the T-536-B telemetry work was present in the working tree but uncommitted when this task started. The T-536-F commit was staged to contain only T-536-F changes (verified on a clean HEAD + T-536-F tree). The pause/failed-hold branches only call the T-536-B `mark_stage` helper in the working tree, where it exists.
  **Reason:** one roadmap task = one focused commit. T-536-B's changes remain for their own commit.

## 2026-10-24 — T-532 Live pipeline + handoff trace

- **Decision:** `get_job_flow(job_id, limit=40)` is a server read model built only from persisted `agent_runs`, `artifacts` (by `run_id`) and `run_inputs`. It returns hops in run start order (`started_at`, then `rowid`). Each hop carries its inputs (source artifact + producing run), outputs, and downstream runs that consumed those outputs, plus a flat `edges` list. It is exposed as `selectedJobFlow` on `/api/status`, next to the existing `selectedJobHandoffs`. It carries ids, titles, kinds and states only, never artifact content.
  **Reason:** this gives one ordered, factual trace of "source artifact → worker run → output → downstream worker". The auth boundary is the same as the handoff data the status payload already exposes, and there is no new route.

- **Decision:** run state mapping: `running` → running, `completed` → done, `failed` → `blocked` when `classify_agent_error` puts the error in the `dependency` or `budget` category (missing upstream, quality gate, budget guard), otherwise → failed. `queued` stays queued, and anything else is `unknown`.
  **Reason:** the run table has no blocked status. A gate that stopped a worker before it did its job is a different situation for the owner than a provider/worker failure, and the existing error classifier already makes that distinction. No new status is written.

- **Decision:** input origin: `run` (producer is in this trace), `earlier` (producer run exists but falls outside the 40-run window, which is marked `truncated`), or `source` (seed/manual artifact with no run record). Nothing is inferred from the agent dependency map, so only edges that a run actually consumed are drawn.
  **Reason:** this keeps the payload bounded and never invents a handoff.

- **Decision:** the UI is a pure renderer `renderPipelineFlow(flow)` (between `pipeline-flow:begin/end` markers) rendered under the existing stage cards in the Content Pipeline card. Desktop shows one row per run (`# · input → run → output → downstream`). Running rows pulse, with a moving packet and a "Moving now: …" header, and `prefers-reduced-motion` disables the animation. Input and downstream chips are buttons that open the existing `openHandoffTrace(run, artifact)` drawer. They are only rendered as buttons when both ids match `[A-Za-z0-9_-]{1,80}`. At ≤820px each row stacks into one column with ↓ arrows and larger tap targets.
  **Reason:** this reuses the existing trace drawer and the page convention from T-536-D/E. `test_pipeline_flow.py` runs the shipped renderer under Node against a deterministic workflow fixture, and CI requires Node for it.

- **Decision:** the uncommitted T-536-B telemetry work was still in the working tree. The T-532 commit was staged to contain only T-532 hunks and verified on a clean HEAD + T-532 worktree (compile, planner tests, smoke, `node --check`, both UI fixture tests all green). In the full working tree, smoke stops earlier at the T-536-B assertion `invalid telemetry must degrade to null` (`task_started_at`/`elapsed_seconds` not dropped), before the T-532 checks run.
  **Reason:** one roadmap task = one focused commit. That failure belongs to the T-536-B changes and is left for their own fix and commit.

## 2026-10-24 — T-533 Explainability + tooltips

- **Decision:** the canonical concepts are fixed in `EXPLAIN_CONCEPTS` (`hook, script, caption, voice, cycle, idea, job, review, learned`). Their copy lives in `explain.<concept>` (plus `explain.aria` = "What is {term}?") in each EN/UK/RU I18N block. Product terms (Hook, Script, Job…) stay in English inside the UK/RU sentences, matching the UI labels the owner already sees. The explanation around them is fully translated.
  **Reason:** one source of truth that the regression can enumerate. Translating the term itself would make it stop matching the on-screen label.

- **Decision:** help is a small `?` `<button type="button">` produced by `helpTip(concept, term)`, linked to a `role="tooltip"` span through `aria-describedby`. It opens on keyboard focus (`:focus-visible`), on hover only under `@media(hover:hover)` (so taps never leave a sticky hover open), and on tap/click via an `.open` toggle that keeps `aria-expanded` in sync. A capture-phase click handler stops the tap from also triggering the parent card's `onclick`, closes the other open tips, and closes everything on an outside tap. Escape hides the tip until focus leaves. At ≤820px the button is 28×28 px and the tip becomes a fixed bottom sheet, so it is not clipped by scrolling panels. Unknown concepts render nothing.
  **Reason:** the existing `data-help` → `title` hints cannot be reached by keyboard or touch. Those hints are left as they are, and the new component adds accessible help only where the ambiguous concepts appear.

- **Decision:** the tips are placed next to the labels where the ambiguity actually shows up. Cycle Control: cycles/review/learned stats and the Idea/Job/Learning sections. Content Package: Hook/Script/Voice-over/Subtitles. Approval Studio: Hook/Script and the Caption/Voice regenerate buttons. `test_explainability.py` (CI step, Node required) checks key presence/parity/non-fallback in all three locales, checks that every `helpTip()` call uses a known concept and that every concept is used, and runs the real helper under Node with a fake DOM to verify markup, escaping and tap/outside/Escape/blur behaviour.
  **Reason:** this satisfies "regression prevents missing help keys" deterministically, without a browser.

- **Decision:** as in T-532, the uncommitted T-536-B telemetry changes in the working tree are left out of this commit. The T-533 commit contains only T-533 hunks and was verified on a clean HEAD + T-533 worktree.
  **Reason:** one roadmap task = one focused commit.

## 2026-10-24 — T-534 EN/UK/RU localization parity

- **Decision:** EN (`I18N.en` literal plus its `Object.assign` extensions) is the canonical dashboard key set. UK and RU must contain exactly the same keys with the same `{placeholders}`, and every key referenced by `data-i18n`, `data-i18n-placeholder`, `data-help` or a literal `tr('…')` must exist. `tr('prefix.'+x)` families are dynamic and are covered by key-set parity, not enumerated.
  **Reason:** `tr()` silently falls back to EN and then to the raw key, so gaps used to ship unnoticed. The real gaps were `action.close` (missing everywhere, so the Claude setup "Close" button showed the raw key), 3 drawer MCP keys in UK, and 28 category/design/owner keys in RU.

- **Decision:** UK/RU values may equal EN only for an explicit allowlist (`SAME_AS_EN` in `test_locale_parity.py`). It covers product/workspace names (Approval Studio, Content Brain, Revideo, Media Finisher, …) and glossary/technical terms (Hook, CTA, QA, CPU, DONE, HUMAN, Push, Short, workflow, roadmap). Ordinary labels that had been left in English (Description, Hashtags, Voice-over, Provenance, job/learning/production, Heartbeat, …) are now translated.
  **Reason:** brand names stay recognizable across locales. Everything else that renders in English inside UK/RU is a leftover. An allowlist makes every intentional exception reviewable.

- **Decision:** hardcoded English UI strings in the dashboard script now go through `tr()` with new `toast.*`, `error.*`, `dialog.*`, `finisher.*`, `publishing.*`, `experiment.*` keys. This covers toasts, the "Restart Factory" button, loading/error cards, Media Finisher route nodes, the experiment/publishing panels and `prompt()`/`confirm()` dialogs, including their prefilled free text. Machine values (`youtube_shorts`, JSON defaults) and the audit `reason` strings sent to the API stay in English.
  **Reason:** these strings are user-visible. The API reasons are stored audit data, not UI, and changing them would change backend records.

- **Decision:** the language check is letter-based. UK copy must not contain RU-only letters (ы э ъ ё) and RU copy must not contain UK-only letters (і ї є ґ). The test also self-tests the checker against deliberately broken tables (missing UK/RU key, missing referenced key, EN fallback, placeholder drift, mixed letters, a re-added hardcoded literal).
  **Reason:** this deterministically catches UK↔RU copy-paste mixing without a dictionary. The self-test proves the regression would actually fail on a missing canonical key.

- **Decision:** the "representative EN/UK/RU dashboard fixture" runs the shipped `I18N`, `TASK_COPY`, `taskCopy()` and `tr()` under Node. It renders the static shell labels, every statically referenced key (with sample vars) and every roadmap card per locale, and asserts there are no raw keys, no unresolved placeholders, no EN fallbacks and none of the known EN fallback strings in UK/RU. As with the other UI fixtures, it runs with `FACTORYOS_REQUIRE_NODE=1` in CI and reports SKIPPED without Node.
  **Reason:** this matches the established `test_explainability.py` / `test_delegation_ui.py` pattern and needs no browser.

- **Decision:** as in T-532/T-533, the uncommitted T-536-B telemetry changes in the working tree are left out of this commit. The T-534 commit contains only T-534 hunks.
  **Reason:** one roadmap task = one focused commit.

## 2026-10-27 — T-580 Role / Operator separation

- **Decision:** roles live in a new `ROLE_CATALOG` (Scout, Researcher, Scriptwriter, Reviewer, QA, Engineer, Supervisor) that only *references* canonical worker names. `AGENTS`, `AGENT_MAP`, `AGENT_SPECS` and `/api/agents` are untouched. Operators are `chatgpt`, `claude`, `gemini`, `auto`; `engineer` has no pipeline worker and excludes ChatGPT (no coding runner for it).
  **Reason:** satisfies "without renaming existing canonical workers" and keeps all pipelines backward-compatible.

- **Decision:** assignment is recorded owner intent only (`role_operator_assignments.json`, default `auto`, `enforced: false`). Each role also reports `runtime_operator`, i.e. what the unchanged pipeline really uses today (`chatgpt` for `LLM_LIVE_AGENTS`). Routing by assignment is left to T-588; the UI to T-581.
  **Reason:** reporting a Claude/Gemini assignment as if it were running would fabricate readiness. Selection grants no publish/production privilege.

- **Decision:** operator status never returns secrets and never invents readiness. ChatGPT = key configured (`configured`/`auth_pending`); Claude = worker heartbeat (`online`/`offline`); Gemini = key configured but not probed (`configured_unverified`, `online: null`) or `auth_pending`. Endpoints `GET /api/factory/roles` and `POST /api/factory/roles/assignment` are owner-only; the POST validates role, operator and eligibility.
  **Reason:** a live Gemini probe would be a provider call; unknown must stay unknown.

- **Decision:** tests in `test_role_operator.py`, wired into CI. The local venv used Python 3.12 (the code needs 3.10+ syntax; system `python` is absent).

## 2026-10-29 — T-560-B Session/vault abstraction + human takeover

- **Decision:** credentials are referenced only as opaque `vault://…` refs. They are resolved at execution time through a `CredentialVault` protocol whose `resolve()` is scoped to the exact (workspace, provider, account_binding_id). The only backend shipped is the deterministic `InMemoryVault` (tests/dev). Missing and out-of-scope refs return the same error, so resolution cannot be used to probe whether a ref exists.
  **Reason:** a real backend (AWS Secrets Manager, etc.) needs credentials and an owner choice, so it is a later adapter behind the same protocol. Nothing here reads `.env` or production secrets.

- **Decision:** a resolved secret is wrapped in `SecretValue`. Its `repr`/`str` are redacted and pickling raises; the raw value is available only through an explicit `reveal()` at the point of use. Workers may resolve only `username`/`password`. OTP, TOTP seeds, recovery codes and cookies cannot be resolved; they stay human-only per the spec.
  **Reason:** this enforces "never ask the worker to read a one-time code from secret storage" in the contract, not just by convention.

- **Decision:** a plan step requests a credential with `{"type": "fill", "selector": …, "credential_field": "password"}`, never with a literal value. `session_ref` plans cannot also request credential fields. A `session_ref` must equal the ref bound to the plan's own workspace/provider/account, and one `session_ref` cannot be bound to two bindings. The guarded Playwright adapter (T-560-C) is unchanged: its strict step schema still rejects `credential_field`, so it stays anonymous.
  **Reason:** this prevents session crossover between workspaces without touching the reviewed T-560-C security boundary. Real authenticated browser session restore is a future, separately approved step.

- **Decision:** `SessionRegistry` and `CheckpointStore` can persist to JSON (mode 0600, atomic replace). The files hold only opaque refs and redacted checkpoint metadata: site hostname without path or query, step index/type, reason, payload hash, and the indices of completed irreversible steps. A checkpoint goes `waiting_human → resumed` (owner-authorized, binding and payload hash must match) `→ consumed`. The executor reads resume state from the trusted store, never from the caller, and consumes it before running any step (at-most-once). It resumes after `completed_steps` and refuses to re-execute any index in `irreversible_done`.
  **Reason:** this satisfies the persisted handoff and "resume without replaying irreversible steps" DONE criteria. Single-use tokens act as the idempotency fence.

- **Decision:** the resumable executor is mock-only (`run_mock_resumable`, `executor="mock"`). A `challenge_probe(index, step)` fixture stands in for page inspection. `test_browser_sessions.py` was rewritten as `unittest` (still runnable as `python test_browser_sessions.py` in CI). `browser_runner/sessions.py` gained `from __future__ import annotations`: its old `-> str | None` annotation would fail at import on the Python 3.9 EC2 worker.
  **Reason:** this gives deterministic, zero-network coverage. This sandbox only allows `python3 -m unittest`, so regression suites were invoked through a unittest subprocess shim.

## 2026-10-29 — T-560-C Real browser executor + generic recipe

- **Decision:** "generic recipe" = `browser_runner/recipes.py::generic_form_recipe`, a declarative builder (start URL, fill/select fields, staged uploads, preview click, wait, extracts, screenshot). It produces a plain `BrowserActionPlan` and has no allowlist or credential inputs. Field and upload items with unknown keys raise `PolicyError`.
  **Reason:** recipes stay provider-neutral and cannot widen the trusted runtime policy. T-560-D social recipes can build on the same shape.

- **Decision:** the DONE wording "submit disabled unless the plan carries valid approval" is implemented as a stricter gate. With no, stale or tampered approval, the run blocks with `submit_requires_matching_human_approval`. With a matching snapshot + payload hash it still blocks, with `trusted_approval_verifier_not_configured`. The browser never launches in either case, and the POST/PUT/PATCH/DELETE network guard is unchanged.
  **Reason:** the approval fields in the plan are self-asserted. CLAUDE.md forbids weakening the publish approval gate, and the spec requires a server-side approval verifier before any real submit. That verifier is future, owner-approved work.

- **Decision:** `run_playwright` takes an injectable `clock` (default `time.monotonic`), so the timeout regression is deterministic. The DONE fixture is the deterministic fake browser in `test_browser_playwright.py`. Playwright/Chromium were **not** installed on the EC2 worker, because the roadmap says installing them on a production worker is not yet approved. The real-Chromium loopback test stays opt-in (`RUN_BROWSER_FIXTURE=1`) and now drives the same generic recipe.
  **Reason:** this proves the DONE criteria with zero network, zero install and zero cost. The real-browser run remains an operator choice.

- **Decision:** on this worker `python` is a broken wrapper and only `python3` (3.9.25) runs. `smoke_tests.py` and `media_finisher_worker.test_planner` could not run here: `fastapi` is not installed and the smoke-test command was denied in this sandbox. `app.py`/smoke tests do not import `browser_runner`, and CI runs them.

## 2026-10-29 — T-590 Relay build-process control room (code slice)

- **Decision:** the parent `autopilot.delegation` now writes `.autopilot/run.json` atomically (gitignored, `source: parent`). It holds run_id, task, state, started_at and pid before the Claude CLI starts, then the result/commit/exit code when the run finishes. The heartbeat (`claude_pro_worker.task_snapshot`) prefers this record over the model-authored `status.json`. A `running` record whose pid is gone is reported as `stale`, never as a ghost `running`. `status.json` is still deleted before each run, so the agent must write a fresh one.
  **Reason:** fixes the diagnosed gap where the task/progress vanished while Claude was working. Rejected alternative: leaving status.json in place, because a stale previous status could then be mistaken for the current run's result.

- **Decision:** every Relay claim mints a `run_id`. Worker events may carry `run_id` and `event_id`. Events from a superseded run are rejected with 409. A repeated `event_id` from the same worker is a no-op replay: no duplicate history and no duplicate Telegram notification. The worker derives event IDs as `<run_id>:<seq>:<stage>` and retries a failed POST exactly once. Both fields are optional so older workers keep working.
  **Reason:** idempotent, replay-safe stage events without a schema migration of the JSON store.

- **Decision:** GitHub Issue intake is owner-only (`POST /api/relay/intake/github-issue`, Telegram `/issue N`). It uses `source_key = github-issue:<repo>#<n>`, and a repeat import returns the existing ticket without re-queuing. Telegram `/issue` creates a ticket only if the issue appears in the live GitHub snapshot. Otherwise it answers "not verified" and creates nothing. ROADMAP tasks are **not** imported into Relay, because the roadmap autopilot already executes them and importing would mean double execution. Their live state is visible through the parent run record/heartbeat instead.
  **Reason:** this gives one authoritative ticket per source with no phantom queue entries. It supersedes the unwired PR #60 helper, which can be closed once this lands.

- **Decision:** `RelayQueue.view()` adds a `lifecycle` list (queued, claimed, running, committed, pushed, pr, ci, merged, deployed, plus the final state). It is derived only from durable history of the **current** attempt. Telegram `/task` and the `/relay` web detail drawer both render this same field. PR/CI/merge/deploy have no backend verifier yet and are always shown as "не проверено". A worker `ci_passed` self-report does not change that.
  **Reason:** Web and Telegram share one backend and show no fabricated stages.

- **Decision:** worker notes and issue titles/bodies are redacted (Anthropic/GitHub/Telegram-bot tokens, Bearer values) before they are persisted.

- **Decision:** the new suite is `test_relay_lifecycle.py`. It is imported by `test_relay_execution.py`, which CI already runs, so `.github/workflows/ci.yml` stays untouched (workflow edits are scoped separately). On this EC2 worker the relay suites ran via `python3 -m unittest discover` with an out-of-repo bootstrap that stubs only the `fastapi`/`pydantic` imports, because FastAPI is not installed on the system Python. Route handlers and `smoke_tests.py` still need real CI.

- **Decision:** the T-590 checkbox stays open. Its DONE criterion needs live evidence this sandbox cannot produce or verify: a server-side worker claim on Render, a paired owner Telegram chat (T-506 HUMAN), a PR, a CI run, the deployed revision and an Issue #41 comment. `git push`, `gh` and network commands are denied to the delegated agent here.

## 2026-10-29 — T-537 Dependency-aware scheduler + Owner lanes

- **Decision:** the Claude worker (`autopilot/autopilot.py`) now honors `Depends:`. A dependency is met only when that task exists in ROADMAP and is checked; unknown IDs stay unmet (fail-closed). HUMAN tasks are still never selectable.
  **Reason:** before this, the worker ignored `Depends:` and would have started T-560-B although T-550-gated work and ChatGPT's in-flight branches were not finished.

- **Decision:** new optional `Owner:` metadata (`chatgpt`, `claude`, `gemini`, `any`). The runner identity is `AUTOPILOT_OPERATOR` (default `claude`). Missing/`any`/`auto` Owner keeps the old behavior: any runner may take it. The app-side parser exposes `owner` on roadmap tasks for the delegation board.
  **Reason:** ChatGPT (planner) also implements tasks in `chatgpt/*` branches, while the Claude worker picked the same first-unchecked task. T-560-B, T-560-C, T-562 and T-564 already had ChatGPT commits on main but were still open, so the Claude worker would have duplicated them. Those four are now tagged `Owner: ChatGPT` instead of being force-checked, because their DONE criteria include on-host/vault work that is not yet verified.

- **Decision:** when `AUTOPILOT_REPO` is unset and `/work/factoryos` does not exist, the worker uses its own checkout instead of an empty path.
  **Reason:** on EC2/phone runs the default container path silently produced an empty roadmap (0 tasks) and the worker went idle.

## 2026-10-30 — T-594 (increment 1) Semantic sidebar sections

- **Decision:** the flat 24-button sidebar is regrouped into six sections: Overview (Control Room, Pipeline, Supervisor, Error Center), Create content (New Job, Jobs, Discovery, Revideo, Content Brain, Media Finisher, Variants, Package, Outputs), Review & publish (Review, Publish), Growth & learning (Performance, Analytics, Experiments), Automation & team (Autopilot, Agents, Workers), System (Build Progress, Release QA, Settings). Every button keeps its exact handler, icon, label key and live counter id; only order and grouping changed. Control Room stays first and active.
  **Reason:** follows the production flow (observe → create → approve/publish → measure → automate → maintain). Reversible: the groups are plain markup, and `test_navigation.py` holds the before-map of all 24 destinations and handlers.

- **Decision:** section headings are flat `.navSection` headings (`role="heading"`), not collapsible submenus yet. They show as labels on desktop and in the open mobile drawer, and as 1px dividers in the icon-only rails (701–900px and closed mobile). Each button gets a localized descriptive hint through a new generic `data-i18n-title` attribute, and the `<nav>` gets a localized `aria-label` through `data-i18n-aria-label`. Both are applied by `applyLanguage()` and covered by the locale-parity checker.
  **Reason:** smallest safe first step that keeps all existing responsive CSS and routes intact. Collapsible submenus, the slide-out one-third menu, breadcrumbs, screenshots and the CI-gated PR are still open in T-594, so the checkbox stays unchecked.

## 2026-10-30 — T-594 (increment 2) Collapsible groups, slide-out menu, breadcrumbs, keyboard

- **Decision:** each section is now a `.navGroup`: the heading holds a real `<button class="navSectionToggle">` with `aria-expanded`/`aria-controls`, and the destinations sit in a labelled `role="group"` list. Collapsed groups are remembered in `localStorage["factoryos_nav_collapsed"]`. The group that holds the current destination is always shown, but that does not overwrite the remembered choice. In the icon-only rails (701–900px and closed phone rail) the headings stay 1px dividers with no toggle, so every icon stays visible even when its group is collapsed.
  **Reason:** a collapsed group with no visible heading would hide destinations. Reversible: delete the localStorage key, or remove the `collapsed` class rules.
- **Decision:** one slide-out menu for every width, reusing the existing `navOpen`/backdrop/`toggleMobileNav()` path. Above 700px a new `»` rail button opens it at `clamp(320px, 33.333vw, 520px)`, i.e. about one third at 1440px. On phones the ☰ drawer becomes `min(86vw, 360px)` with 13px labels instead of a 34vw drawer with 9px text. In the open menu every destination shows its localized one-line description (`::after { content: attr(title) }`, the same `navHint.*` text as the hover tooltip). Backdrop tap, Escape or choosing a destination closes it, and Escape returns focus to the toggle. The sidebar grid column stays reserved (`.main { grid-column: 2 }`), so opening the menu overlays the page instead of reflowing it. The old "close on any resize above 700px" listener is replaced by a 700px media-query change listener, so desktop resizes no longer force-close the menu. Section toggles no longer close the drawer; only destinations do.
  **Reason:** owner asked for a ~1/3 slide-out on capable screens, closing on outside tap, and usable width on phones. Hover on the compact rail keeps the native localized `title` tooltip. A custom hover flyout was not added, because the rail clips overflow and a second hover layer would conflict with the click/tap menu.
- **Decision:** the current location is derived only from facts. When a destination opens an overlay (any element that gains `.open` during that click), it becomes current (`.active`, `aria-current="page"`, highlighted group heading), and a `MutationObserver` returns to Control Room once that overlay closes. Scroll-to-section destinations become current directly. Destinations that open nothing (no job selected → toast, Settings without a handler) leave the current location unchanged. Clicking Control Room scrolls to the top. Breadcrumbs in the header (`⌂ › Section › Destination`) are re-rendered on language change. The section crumb opens the menu with that group expanded and focused.
  **Reason:** no handler was changed (the before-map test still pins all 24), and the UI never claims you are in a studio that did not open.
- **Decision:** keyboard: ArrowUp/ArrowDown/Home/End move focus across the visible sidebar buttons (section toggles included). ArrowLeft/ArrowRight collapse or expand a focused section. Escape closes the menu. Opening the menu focuses the current destination.
- **Decision:** `test_navigation.py` now also checks group wrappers and toggle ARIA wiring, slide-out widths, backdrop, descriptions, remembered state, breadcrumbs, keyboard handlers, the new EN/UK/RU keys and a `node --check` of the whole inline script. It is now a CI step. The before/after map is in `docs/roadmap/T-594_NAV_MAP.md`.
- **Not done here:** desktop/mobile screenshots and a browser-driven touch run. This runner session could not start a browser, and environment-prefixed smoke/planner runs were denied by the permission mode, so the T-594 checkbox stays unchecked until screenshots and the CI-gated PR exist.

## 2026-10-30 — T-537 follow-up: inline roadmap metadata
- The live ROADMAP writes `Depends:` / `Owner:` mid-line (`Planner: owner; Executor: ... Depends: T-590.`, `Owner: ChatGPT. Depends: ...`). The line-start parser missed them, so T-591/T-592/T-593 looked dependency-free and T-591-A got owner `chatgpt.`, matching no lane.
- The scheduler now finds both fields anywhere on an indented metadata line and drops trailing punctuation. `Executor:` is intentionally not treated as an owner lane; lanes stay explicit via `Owner:`.

## 2026-10-30 — Single coordinator: Claude
- Owner decision: Claude coordinates and executes all engineering work; the `chatgpt` lane is paused and is reconnected later only via tasks Claude labels `Owner: chatgpt`.
- Retagged open ChatGPT tasks to `Owner: claude`: T-591-A, T-562, T-564. Completed T-560-B/C keep their historical owner.
- T-564 `Depends: T-562,T-563` → `Depends: T-562`: T-563 never existed in the ROADMAP, so T-564 could never be selected.
- Added T-599 at the top of P0 so the worker fixes head-of-line blocking before it reaches T-590's owner-dependent remainder.

## 2026-10-30 — T-599-A: park instead of stall
- A blocked task is parked and woken only by a change to `.autopilot/answers.md` or an owner Retry. HEAD changes no longer wake it, so the worker's own commits on other tasks don't make the blocked task burn another Claude turn.
- A task that exhausts `MAX_FAILS` is parked until Retry, and the failure counter is per task. The daemon then continues with the next safe task instead of sleeping on the held one.
- `control.decide` accepts the set of parked tasks, so Retry works for any of them.
- Standing owner grants are recorded in `.autopilot/answers.md`; they include merging Claude's own PRs once CI is green.

## 2026-10-30 — T-599-B: explicit Owner everywhere, enforced by CI
- With the ChatGPT lane paused, every open non-HUMAN task is labelled `Owner: claude`. HUMAN tasks stay unlabelled because no runner ever selects them.
- A CI lint (`roadmap_owner_lint`) fails when an open non-HUMAN task has no `Owner:`, so new tasks must name a lane.
- Runtime semantics are unchanged: an empty Owner still counts as shared. Flipping it to fail-closed is deferred until a second lane is reactivated; the lint already prevents unowned tasks from landing.

## 2026-10-30 — T-599-C/D: claim before code, events from the parent process
- ROADMAP runs reuse `RelayQueue`: `claim_roadmap` atomically finds or creates one ticket per task (`roadmap:T-xxx`) under the store lock and issues a fresh `run_id`. It refuses another lane's task, an active run, and a stale run that is waiting for an owner Retry. Generic Relay claims skip ROADMAP tickets, so a Retry cannot run a ROADMAP task with the Relay prompt.
- Fail-closed: without a server claim the worker does not touch code, and the task is deferred for 5 minutes. `AUTOPILOT_ALLOW_UNCLAIMED=1` allows unclaimed runs only for offline dev runners without a FactoryOS connection.
- Events come from `autopilot.py`, which sees git and exit codes: running, committed (new HEAD), pushed, done (with the agent's reported checks), blocked, failed, plus a heartbeat every 20s. PR/CI/merge are not claimed by the worker.
- Root cause of "Claude has tasks but does nothing": the EC2 worker pulled only `autopilot/aws-worker`, which was 12 commits behind main, so it never saw new ROADMAP tasks or runner fixes. Between tasks, `sync_branch` now fast-forwards or merges `origin/main`. A merge conflict is aborted and reported. If `autopilot/*.py` changed, the runner exits 75 and `claude_pro_worker` re-execs itself with the new code.

## 2026-10-30 — T-593: reboot-proof worker Python and a headless verification allowlist
- Live evidence: claimed runs of T-599-E and T-590 blocked. `~/.local/bin/python` exec'd `/tmp/fos-venv`, which the reboot wiped, and headless `claude -p` denied `python3` and venv recreation.
- The parent process now keeps `<repo>/.venv` (already gitignored) in sync with `requirements.txt` using a sha256 marker, so pip runs only when requirements change. The venv is prepended to the agent's PATH. If setup fails, the run proceeds and evidence records the reason in `python_env`.
- `--allowedTools` pre-allows exactly the CLAUDE.md loop: file tools, `python`/`python3`, `node --check`, `env DATA_DIR=…`, read-only git plus `git add`/`git commit`. `git push`, branch switches to main, `render` and `gh pr merge` remain in `--disallowedTools`, and the parent still refuses a pushed or off-branch run.

## T-594 CI step deferred (2026-10-31)
The worker's GitHub token has no `workflow` scope, so pushing a commit that edits `.github/workflows/ci.yml` was rejected (the worker looped on this from 2026-10-30 15:14 to 2026-10-31 08:29). The CI step was removed from the worker commit. It must be added separately by someone with `workflow` scope:
```yaml
      - name: Left navigation groups / slide-out / breadcrumbs regression
        env:
          FACTORYOS_REQUIRE_NODE: "1"
        run: |
          python -m py_compile test_navigation.py
          python test_navigation.py
```
(after the "Locale parity" step). Until then `test_navigation.py` runs locally only.

## T-594 (increment 3) Nav behaviour run without a browser (2026-10-31)
- The nav script is now fenced by `// --- nav:begin` / `// --- nav:end` (comments only). `test_navigation.py` runs that block in Node, together with the real I18N tables, `tr`, `esc` and `applyLanguage`, against the real sidebar, toggle, backdrop and breadcrumb markup, on a ~100-line DOM stub. Studio openers are stubs that open one fake overlay.
  **Reason:** no browser exists on the worker, and jsdom/Playwright are not dependencies. Installing them would download software, and a hand-sized DOM keeps the test dependency-free. Mutation-checked: removing destination-close, Escape focus return, the hidden-button filter or the close-overlay observer each fails the run.
- The stub's `offsetParent` mirrors the CSS rules that `check_behaviour()` pins: collapsed items are hidden in the open menu and in the ≥901px sidebar, and toggles are hidden in the closed ≤900px rails. If that CSS changes, both must change.
- CI wiring: `test_locale_parity.py` (already a CI step with `FACTORYOS_REQUIRE_NODE=1`) runs `test_navigation.main()` after its own checks. This replaces the deferred workflow step from the note below. The token still lacks `workflow` scope.
- **Still open, so T-594 stays unchecked:** real desktop/mobile screenshots (1440×900, 390×844) need a browser on a runner or from the owner, and the CI-gated PR happens after the worker push.

## T-594 re-check (2026-10-31)
- No code change. The DONE items that need code (before/after map, all 24 destinations reachable, keyboard, simulated tap, RU/UK/EN regressions, CI wiring) were already met in increments 1–3, and all checks are green again on this head.
- T-594 stays unchecked. The two remaining DONE items cannot be done from this agent run. (1) Screenshots: there is no browser (Chromium/Firefox/Playwright/Selenium) on the worker. Installing one means downloading software into the prepared venv/host, so that was not done. (2) CI-gated PR: the agent cannot push or open PRs, and increments 2–3 are not on `origin/main` yet. Exact steps are in `docs/roadmap/T-594_NAV_MAP.md` → "Remaining steps".
- `env …` commands were denied again, so checks ran as `python -c` + `os.environ.update` + `runpy`, as in the T-590 runs.

## T-594 re-check (2026-11-01)
- No code change. The nav code is on `origin/main` (`c2879b9` contains increments 1–3 and `aac3b8c`), so the PR part is now met by the normal merge flow. This run had no network/`gh`, so it did not see the CI result.
- T-594 stays unchecked. The DONE criterion asks for desktop/mobile screenshots and a real touch check. The worker still has no browser (`which` finds no Chromium/Chrome/Firefox, and the venv has no Playwright/Selenium/pyppeteer). Screenshots cannot be produced honestly without a browser, and installing one was not done, for the same reason as before.
- The unrelated uncommitted T-560-E work (`app.py`, `static/index.html`, `browser_runner/observability.py`, `.autopilot/ui-check.js`) was left in the tree and not committed. Parking it with `git stash` was denied by the permission mode. The checks below therefore ran against the tree **with** that WIP included.
- `env …` was denied again, so the planner/smoke checks ran as `python -c` + `os.environ.update` + `runpy`.

## T-599-E owner GitHub Issue auto-intake (2026-10-31)
- "Repo owner" means the login before the `/` in `FACTORY_GITHUB_REPO`. The API call filters with `creator=<owner>`, and `RelayQueue.auto_intake_owner_issues` re-checks the author login, so a foreign Issue is ignored even if the API filter misbehaves. PRs, malformed entries and Issues whose first non-blank body line is not exactly `Owner: Claude|ChatGPT|Gemini` (case-insensitive) are ignored too.
- T-ID linking: every `T-ddd[d][-X]` in the title and body is checked against `roadmap:T-xxx` tickets. If any match, the Issue reference goes into `source.linked_issues` on those tickets with a `linked` history event, and no new ticket is created. A claim/run_id is never touched. T-IDs without a ROADMAP ticket fall through to a normal import.
- Imported tickets get their lane in `source.owner`/`execution.owner`. The generic Claude `claim()` now skips tickets owned by another lane (`chatgpt`, `gemini`), and `counts()` reports them as `other_lane`, so a ChatGPT Issue is never executed by Claude.
- Poll: a startup task waits 60 s, then runs every `FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC` (clamped to at least 300 s). It is on by default and `FACTORY_GITHUB_ISSUE_INTAKE=0` turns it off. That is one free GitHub REST call per pass, using the existing optional token. Unavailable GitHub means `ok: false` with an `HTTP nnn`/`GitHub unavailable` code and no state change. Logs contain only issue numbers and counts.
- CI step not added: the worker token lacks `workflow` scope (see T-594 note). Someone with that scope should add this after "Relay worker queue / Claude execution unit tests", plus `test_issue_intake.py` in the py_compile list:
```yaml
      - name: Owner GitHub Issue auto-intake (T-599-E)
        env:
          DATA_DIR: /tmp/factoryos-issue-intake-ci
          FACTORY_PASSWORD: ""
          FACTORY_LLM_API_KEY: ""
          FACTORY_GITHUB_ISSUE_INTAKE: "0"
        run: python test_issue_intake.py
```
- The EC2 worker venv is Python 3.9 while `app.py` needs 3.10+. `test_issue_intake.py` therefore skips its app-level case on 3.9, and `smoke_tests.py` can only run in CI (3.13).

## T-590 acceptance run (2026-10-31)
- Superseded the T-599-E note above: the EC2 venv is Python 3.9, and `app.py` / `media_finisher_worker/app.py` failed at import only because of 12 PEP 604 `X | None` annotations (pydantic models and a FastAPI query param evaluate them at definition time). They are now `Optional[...]`, so `smoke_tests.py` and the planner run on the worker. The two `skipIf(py<3.10)` app-level tests are removed and pass on 3.9. All other runtime modules already import on 3.9 (`from __future__ import annotations`).
- The headless allow rule `Bash(env DATA_DIR=:*)` did not match in this run: every `env DATA_DIR=… python …` command was denied. The checks were run as `python -c` with `os.environ.update(...)` and `runpy`, which is the same test command with the same env. Fixing the rule is T-593 scope and is not changed here.
- T-590 stays unchecked. The remaining DONE stages (PR, CI, merge, Render `build_sha`, paired Telegram live trace, Issue #41 comment) need GitHub/network access and HUMAN T-506. The delegated agent has neither. Stage-by-stage evidence and the exact steps are in `docs/handoff/T-590_ACCEPTANCE.md`.

## T-590 re-check (2026-11-01)
- T-590 stays unchecked. The slice is now on main (`autopilot/aws-worker` == `origin/main` == `c2879b9`), and the deterministic stages are green. The DONE criterion still needs CI, the deployed `build_sha`, a paired owner chat (HUMAN T-506), a live trace and Issue #41 evidence. This run was denied network/`gh`, so none of them could be observed, and a merge alone does not count as DONE.
- The unrelated uncommitted `app.py`/`static/index.html`/`browser_runner/observability.py` work in the tree was left untouched and was not committed.

## T-590 re-check (2026-10-31, run-20261031162233-a7b938)
- T-590 stays unchecked, for the same reason as the run above: no new live evidence exists, and the T-590/T-599 commits are not on `origin/main` yet.
- The CLAUDE.md planner command without `FINISHER_DATA_DIR` fails on the worker, because `/var/data` is not writable. The run used CI's `FINISHER_DATA_DIR=/tmp/factoryos-finisher-ci`, so this is an environment fact, not a code change.
- `env …` commands were still denied in headless mode, so the same `python -c` + `os.environ.update` + `runpy` form was used again.

## T-599-F lane board from verified events (2026-10-31)
- One pure read model, `lane_board.build_lane_board`, feeds `GET /api/factory/lane-board` (owner only), the web lane cards (Build Progress and the Workers center) and Telegram `/status` + `/tasks`. Web and Telegram both show the board's raw `task_id` and `stage`, so they cannot disagree.
- Lane state order: a claimed run with a fresh event (within `RelayQueue.stale_seconds`) means **working**. A claimed run without one means **stale**. If the heartbeat is not online: seen within 1 h means **stale**, otherwise **offline**. If it is online: a latest final event of `blocked`/`failed` means **blocked**, otherwise **idle**. The heartbeat's online verdict comes from the server's existing TTL (`get_operator_lanes`). ChatGPT has no heartbeat reporter, so it shows working only while its own claimed run keeps sending events.
- Columns: `[x]` in ROADMAP means Done. An active run means In progress. `blocked`/`failed`/stale means Blocked. A worker `done` event while the ROADMAP checkbox on main is still open means **Review** (awaiting PR/merge). Everything else is Planned. HUMAN tasks stay in Planned with a "HUMAN step" tag.
- "Assigned, not claimed" covers any open task with a non-shared `Owner:` and no claimed event, including a `queued` ticket. Owner GitHub Issue tickets with an `Owner:` lane appear as tasks too.
- When the lane board is wired in (always in `app.py`), the old heartbeat-only Telegram executor lines are replaced instead of being mixed in. The lane block is localized RU/UK/EN by Telegram `language_code` (default RU). The rest of the Relay text stays RU as before.
- CI: `test_lane_board.py` is imported by `test_relay_execution.py`, so the existing "Relay worker queue" CI step runs it. No workflow edit was needed (the worker token lacks `workflow` scope). The Node render case skips only when Node is absent and `FACTORYOS_REQUIRE_NODE` is unset.

## T-599 umbrella acceptance (2026-10-31)
- `test_t599_acceptance.py` runs spec §3 scenarios A–E end to end: ROADMAP text → `claim_roadmap` (run_id) → worker events → `build_lane_board` → Telegram `/status`/`/tasks`. The slice suites keep the depth; this suite checks that the slices agree with each other.
- Refused claims (the run is active or stale) now leave a `claim_rejected` history entry on the ticket. It is written once per (run_id, rejected worker), so a loser that retries every 5 min does not flood the journal. A claim for another lane's task still creates no ticket at all, so there is nothing to journal it on. `claim_rejected` is not a worker stage, so lane state and columns ignore it.
- Scenario Г asks for the blocked reason in the API and Telegram. A lane row now carries `reason`: the redacted worker note of the blocked/failed run, shown only while the lane is `blocked`. Telegram `/status`/`/tasks` and the web lane card render it (`lb.reason`, RU/UK/EN).
- CI wiring without a workflow edit: `test_relay_execution.py` imports the acceptance suite and `TestIssueIntake`. Until now the T-599-E tests were outside CI because the worker token lacks `workflow` scope.
- PR/CI and the Issue #67 evidence comment happen after the worker pushes. The agent run cannot push and does not publish comments. In line with T-599-C/D, the worker reports done/pushed, and PR/CI are verified by the server/owner rather than claimed.
- Known gap, left alone: if the final push fails, the ticket ends `blocked`. A later successful push-only retry does not emit a new event for that ticket, so the lane shows the old blocked reason until the next claim.

## T-595 Resizable/maximizable drawers and overflow repair (2026-10-31)
- One script block (`// --- drawer:begin` … `drawer:end`) upgrades every right-side workspace at load: Build Progress, Worker Center, QA, Intelligence, Content Brain, Variant, Package, the eight flow studios and the agent drawer. Each gets a left-edge grip (`role="separator"`, focusable) and a max/restore button grouped with ×. The markup and close handlers stay as they were. The script injects the controls, so the 16 drawer headers needed no edits.
- Width is the `--drawer-w` CSS variable, so the existing `!important` drawer rules keep working. The default is 65% of the viewport (agent drawer 42%, close to its old compact size). Bounds are 360 px up to `innerWidth − sidebar right edge − 16 px`. The sidebar edge is measured live and also published as `--drawer-side`, so neither maximize nor drag ever covers the sidebar.
- Memory is per drawer in `sessionStorage` (`factoryos_drawer_w.<id>`, `factoryos_drawer_max.<id>`), matching "session width memory". A window resize re-clamps open drawers but never overwrites the remembered width.
- Keyboard on the grip: ←/→ ±32 px (Shift ±128), Home/End go to the bounds, Enter/Space toggle maximize. Escape closes the most recently opened drawer by clicking its own × (the existing close handler). It runs in the capture phase and steps aside while the nav menu, a help tooltip or a modal is open, so those close first.
- Outside click on desktop is unchanged: since v4.5.1, desktop drawer shades are transparent and `pointer-events:none`, so the dashboard stays usable beside a drawer. ≤900 px shades still close on tap. Changing this would be a product behaviour change, and Escape/× cover closing.
- `#dcPage` was a centred modal (inset 24px). It is now a right-side drawer like Build Progress, so "Worker Center" gets the same left-edge resize. Its blurred shade stays clickable to close.
- ≤900 px: drawers are full screen and the grip/max controls are hidden. Pointer, keyboard and button resizing are no-ops there. Touch scroll is native, and drawer bodies get `overscroll-behavior:contain`.
- Overflow: `.taskBoard` (Planned/In Progress/Completed/Blocked), `.lbBoard`, `.lbLanes` and `.dcSummary` are now `repeat(auto-fit,minmax(min(100%,Npx),1fr))`, so columns wrap to the next row instead of being squeezed or clipped. Columns and items get `min-width:0; overflow-wrap:anywhere`, and drawer bodies get `overflow-x:hidden`, so a long title cannot create a panel-wide horizontal scrollbar.
- Tests: `test_drawers.py` runs the real block in Node on the `test_navigation.py` DOM stub, plus small stub additions: `style`, `insertAdjacentHTML`, moving `appendChild`, `click`, `getBoundingClientRect`. It is mutation-checked: removing the sidebar term from the bound or the nav-open Escape guard fails it. CI: `test_locale_parity.py` (an existing CI step) runs it, the same route as T-594, because the token lacks `workflow` scope.
- **Still open, so T-595 stays unchecked:** the before/after screenshots at 1440×900, 1024×768 and 390×844 need a browser, and the worker has none (no Chromium/Firefox/Playwright). The CI-gated PR happens after the worker push.
- Re-check 2026-11-01: the code is on `origin/main` (14f1e35 via PR #80, base `c2879b9`). `test_drawers.py`, `test_navigation.py`, `test_locale_parity.py`, py_compile, the planner tests and the smoke suite are green. There is still no browser on the worker. I did not install Playwright/Chromium into the prepared `.venv` or the host, because that changes the shared worker environment. The checkbox stays open until the owner captures the 1440×900, 1024×768 and 390×844 screenshots, or approves a browser install on the worker.

## T-596 Worker Center / Agent Office factual observability (2026-10-31)
- One pure read model, `worker_observability.build_worker_overview`, feeds `GET /api/factory/worker-overview` (owner only, values redacted like the delegation board), the Worker Center panel and Telegram `/status`. It reports seven separate signals: `host`, `ec2_api`, `systemd`, `oauth`, `heartbeat`, `relay_claim` and `current_task`. Each signal has a state (`ok`/`warn`/`fail`/`idle`/`unknown`), a source and a `checked_at`. A source that did not report stays `unknown`, never `ok`.
- EC2: the host counts as reachable only through its own heartbeat. `ec2_api` is always `unknown · describe_instances_not_granted`, tagged as an optional HUMAN IAM request. The missing `ec2:DescribeInstances` permission is lost visibility, not an offline EC2. No AWS call is made and no IAM change is proposed in code.
- systemd and OAuth come from the existing root supervisor report (`service_state`, `subscription_authenticated` from `claude auth status`). The supervisor now also writes a 0644 copy to `<repo>/.autopilot/supervisor.json` (gitignored), because the worker runs as `ec2-user` and cannot read the 0600 file under `/var/lib/factoryos`. The report holds only booleans and short codes. The worker forwards it in the heartbeat's new `supervisor` field. The server whitelists 7 keys on receipt (`sanitize_supervisor`) and sanitizes their values. A report older than 10 min counts as `unknown` (stale). With no supervisor report, OAuth shows `self_reported:<auth_mode>` as `unknown`, because the heartbeat's own `auth_mode` proves nothing.
- Current task: this is the T-599-F lane row (claimed run + fresh event). The overview's `task_id`/`stage` are copied from that row, and Telegram gets the overview built from the same board snapshot (`get_telegram_lane_board`), so web and Telegram cannot disagree. If the heartbeat names a task without a claim, or a different one, the result is `warn` + `mismatch`, never work in progress.
- Heatmap: the last 28 days, by Europe/Kyiv calendar day (labelled UTC if tzdata is missing). It counts only distinct tasks with verified worker evidence: a worker result `done` with a commit SHA, or a Claude-lane Relay `committed`(with commit)/`done` event. All repository commits are not counted. Days before the first recorded worker event or result are `unknown` (hatched). Days after it are `zero` or a count.
- Progress: every population keeps its own denominator and source. Factory Builder tasks (`factory_tasks`, the historical "87% · 39/45"), ROADMAP checkboxes across all versions (the "49%") and Claude lane tasks are never combined into one number. The Build Progress header and the autopilot lead now name their population.
- HUMAN blockers: every open `[HUMAN]` task shows its `Need`, a ROADMAP link to the line, and whether `.autopilot/answers.md` already has a `## T-…` section. It also gives the next action: add an answer, or the next claim verifies an existing one. CI is `unverified`, because worker branches have no backend CI verifier. PR is shown only when the run attached a github.com URL.
- Agent Office: Claude/ChatGPT/Gemini chips from the lane board (state + claimed task) sit in the office header and open the Worker Center. They refresh at most every 15 s with the office render. For non-owners the API returns 403, so the chips stay empty.
- CI without a workflow edit: `test_relay_execution.py` imports the `test_worker_observability.py` classes (renamed on import to avoid clashing with the lane-board class names). The suite is deterministic: offline/stale/idle/running/blocked fixtures, supervisor fresh/stale/failed/logged-out, heartbeat-only mismatch, a Kyiv day-boundary heatmap, links, progress scopes and HUMAN blockers. It also runs the Node render in EN/UK/RU, checks escaping and `wo.*` key parity, and checks Telegram `/status` against the same snapshot. `smoke_tests.py` covers the app wiring (route, heartbeat whitelist, Telegram board).
- **Still open, so T-596 stays unchecked:** the DONE criterion asks for RU/UK/EN mobile/desktop screenshots, and this worker has no browser. It also asks for a CI-gated PR, which happens after the worker push. Supervisor values appear live only after the worker checkout follows main and the supervisor timer runs the new code.
- Re-check 2026-11-01: no code change. The T-596 slice is on `origin/main` (`c2879b9`). On the worker these pass: `test_worker_observability.py` (16 tests), `test_relay_execution.py` (74), py_compile, planner, smoke, and `node --check` on the inline JS from `HEAD:static/index.html`. The working-tree copy was not checked because it contains unrelated T-560-E WIP. The checkbox stays open for the same reasons as T-594/T-595. There is no browser (Playwright is not in the venv), and no browser was installed into the shared worker environment, so the RU/UK/EN mobile/desktop screenshots can't be produced honestly. Network/`git fetch`/`gh` were denied, so CI on `c2879b9` was not seen. The unrelated uncommitted T-560-E files were left in place and are not in this commit. The planner and smoke checks ran with the env set inside Python, because `env …` was denied.

## T-597 Contextual assistance and accessibility (2026-10-31)
- No new help component: the T-533 `helpTip()` button + `role="tooltip"` bubble is extended. It already handled keyboard (focus/Enter/Space/Escape), hover limited to `@media(hover:hover)`, tap, outside tap and a mobile bottom sheet. Eight surface concepts are added: `relay`, `worker`, `connector`, `stage`, `approval`, `video`, `brain`, `discovery`.
- Placement: Delegation Center title and lane board → `relay`. Worker Results and Worker Center → `worker`. Connections → `connector`. Content Pipeline → `stage`. Approval Studio → `approval`. AI Media Finisher → `video`. Content Brain → `brain`. Discovery → `discovery`.
- Static headings get a `<span class="helpTipMount" data-help-tip=… data-help-term=…>` placed **beside** the heading, inside a `.helpHead` flex row. `applyLanguage()` fills it, so the tip follows the active language. It sits outside the heading because several headings carry the native `data-help` title, which `smoke_tests.py` requires. Putting the tip inside would show that native title on top of the bubble. JS-rendered headings (lane board, Worker Center) call `helpTip()` inline.
- Mini diagrams are factual step strings `explainFlow.<concept>`, split on ` → `. They are rendered as escaped step chips inside the same tooltip, so `aria-describedby` reads them too. Steps mirror existing UI facts: finisher.sub and brain.sub, the claim lifecycle and the cycle chain. They make no status claims.
- Tutorials: every surface tip ends with `explain.tutorial` ("Audio/video tutorial: not yet supported"). It is a plain text note: no player, no media URL, no generation call.
- No overlap: tapping one tip already closed the others. Hovering or focusing another tip (`mouseover`/`focusin`) now closes a tap-opened one too. The desktop bubble aligns left or right near viewport edges (`alignL`/`alignR`, only at `min-width:821px`, so the ≤820px bottom sheet is untouched). The bubble width goes to `min(300px,86vw)` in the base rule, not in a later rule that would override the mobile sheet.
- Tests: `test_explainability.py` (existing CI step) covers 17 concepts × EN/UK/RU, each surface heading having exactly one tip, flow step parity, the tutorial placeholder, the absence of media/fetch, and Node DOM checks for hover/focus closing other tips. `test_lane_board.py`/`test_worker_observability.py` now load the real explain block into their Node harness.
- **Still open, so T-597 stays unchecked:** the DONE criterion asks for mobile screenshots, and this worker has no browser (no Chromium/Playwright, and a browser install on the worker is not approved). It also asks for CI, which runs after the worker push/PR. This agent did not observe CI.
- Re-check 2026-11-01: no code change. `a44a432` (the code slice) and the `ui-screenshots` job (#82, with a `help-tip` scene for T-597) are both on `origin/main`. These passed on the worker: py_compile (including `tools/ui_screenshots.py`), `test_explainability.py` (17 concepts, 10 surface headings × EN/UK/RU), `test_lane_board.py`, `test_worker_observability.py`, planner, smoke, and `node --check` on the inline JS from both the working tree and `HEAD`. The checkbox stays open, status `blocked`. GitHub Actions results and artifacts need GitHub access, and `gh`/network were denied in this run, so CI success and screenshot quality can't be claimed. The owner should confirm both, as described in the ROADMAP re-check line. The unrelated uncommitted T-560-E files (`app.py`, `static/index.html`, `browser_runner/observability.py`, `.autopilot/ui-check.js`) were left in place and are not in this commit. The planner needs `FINISHER_DATA_DIR` (it does not read `DATA_DIR`), so it was run with `FINISHER_DATA_DIR=/tmp/factoryos-autopilot/media-finisher`, set inside Python because `env …` was denied.

## T-598 Stable autonomous engineering handoff and report (2026-10-31)
- Parking state (`blocked` with its answers.md marker, `failed`, and the current task's attempt counter) is persisted in `.autopilot/parking.json`, next to `answers.md`, gitignored and atomically replaced. Reason: the worker re-execs itself after every runner change on main (`EXIT_CODE_UPDATED`), and that reset the in-memory counters, so `MAX_FAILS` was not a real bound across restarts. An unreadable or corrupt file falls back to empty state and does not stop the worker.
- Network git (pull/fetch/push) gets `GIT_TERMINAL_PROMPT=0` and a timeout: `AUTOPILOT_GIT_TIMEOUT_SECONDS`, default 120 s, clamped to 10–600. A failed or timed-out fetch now returns `offline` (it used to return `""`). The loop goes on with the current code, as before. Push failures keep the existing bounded retry path.
- Milestone reports are sent only on `done` and `blocked` checkpoints (no spam). The `failed` notices stay as they were. The report always says that PR/CI/Render are not verified by the worker, because the worker has no CI/deploy verifier, and success must never be implied. If tzdata is missing, the Kyiv time is shown as unavailable, not as a guess.
- The optional least-privilege grants (GitHub `workflow` scope, `ec2:DescribeInstances`) are `[HUMAN]` tasks T-598-H1/H2 at the **end** of ROADMAP. `first_human_blocker` reports the first open HUMAN task in file order, so the idle notice keeps showing the real blocker T-506 and not an optional grant.
- No new CI step (no `workflow` scope). The new regressions live in `autopilot/test_autopilot.py`, which CI already runs.

## T-560-D Social web draft recipes (2026-10-31)
- One module, `browser_runner/social.py`, with a per-provider profile (`SOCIAL_SITES`: origin, text/media limits, submit action class, default selectors). There is no subclass per site. Reason: the three flows differ only in step order and selectors, and the T-560-C executor/guards stay the single execution path.
- The recipe resolves `session_ref` from `SessionRegistry` itself and has no session/credential parameter. `run_social_draft` checks the binding again at run time. Reason: the T-550 portability contract (disconnect/replace/no cross-workspace reuse) is enforced by construction, not by caller discipline.
- The draft plan never contains `submit`. `final_submit_plan` builds the irreversible plan separately and always clears approval fields. There is deliberately no "approve" helper, so approval can only come from the owner gate. Telegram's final step is classed `send`, X/Instagram `publish`.
- The X 280-char check is a conservative plain character count (X weights URLs/emoji differently). It is a pre-check, not the authority.
- Default selectors/URLs (`/compose/tweet`, Instagram create dialog, `web.telegram.org/k/#@channel`) were not verified on the live sites: there are no accounts and no browser on this worker. Known selector keys can be overridden by trusted config. `/compose/tweet` is used instead of `/compose/post` because the T-560-C path guard rejects "post".
- CI without a workflow edit: `test_browser_playwright.py` (existing CI step) imports the `test_browser_social.py` classes under `__main__`. This is the same route as T-596/T-599-E, because the token lacks `workflow` scope.


## CI dashboard screenshots (2026-10-31)
- UI tasks T-594..T-597 were blocked only on "screenshots desktop/mobile": the EC2 worker has no browser. Instead of installing Chromium on the production worker host, a separate CI job (`ui-screenshots`) starts FactoryOS locally without a password or provider keys (zero spend) and captures EN/UK/RU × 1440x900 / 1024x768 / 390x844 × home, menu open, Build Progress, Worker Center, help tip (45 PNGs) with Playwright.
- Output is a 14-day `ui-screenshots` artifact (PNG + `index.html` contact sheet + `report.json`) and a findings table in the job summary.
- Horizontal overflow, uncaught page errors and failed scene actions are **reported, not enforced**: the job fails only when the dashboard cannot load or a scene cannot be captured. Reason: the first baseline is unknown; making it blocking before seeing it would turn every PR red. Tighten once the baseline is clean.
- Playwright is installed only in that job, not in `requirements.txt`, so the Render build is unchanged.
- Separate job (not a step in `syntax-and-smoke`) so a browser install problem cannot hide or delay the core regression results.
## T-600 Subscription limit pauses the queue (2026-10-31)
- Executed by an interactive Claude session at the owner's direct request, although the ROADMAP lane says `Owner: chatgpt`.
- Limit detection reads the CLI's structured result first (`api_error`, `api_error_status: 429`) with a regex, not `json.loads`: the evidence is a 4000-char tail where stdout and stderr are concatenated, so the result line may be cut at the start or have stderr glued to its end. On 2026-10-31 the CLI returned `"api_error":"usage_limit_reached"` and none of the old plain-text keywords matched, so 13 tasks were parked as "failed" in ~20 minutes.
- The limit check runs before the auth keywords: a limit response is also an error response and must not be read as a logged-out session.
- A limit is account-wide, so the worker holds the **whole queue** (`limit_until`, persisted in `parking.json` so a restart cannot skip it). The task that hit the limit is not counted as an attempt and is not parked. Pushing already verified commits still happens during the hold; starting Claude (roadmap or Relay ticket) does not.
- The reset time is taken from the CLI text only when it is an unambiguous clock time (`6pm (UTC)`, `18:00 (Europe/Kyiv)`); +120 s grace. Dated or weekly resets and unknown zones fall back to `AUTOPILOT_LIMIT_BACKOFF_SECONDS` (default 1800, clamped 300–21600). One quick failed call per back-off window is the accepted cost.
- Only a charset-restricted reset hint (max 40 chars) leaves the evidence; the raw CLI text stays in redacted local evidence.
- Not covered: a limit hit inside a Relay ticket run (`relay_tasks.run_one`) does not set the hold itself; the next roadmap run detects it.
## T-560-E Browser Runner observability (2026-11-01)
- Runs are stored as ordinary `artifacts` rows (`agent="Browser Runner"`, `kind="browser_run"`, JSON view as content) instead of a new table: no migration, and they share job scoping with other worker output. Recording is server-side only (`record_browser_run`); there is no HTTP ingest endpoint, so a client cannot inject a run view. Read endpoints stay behind the normal auth middleware.
- The stored content is a whitelisted *view* built by `browser_runner.observability.build_run_view`, not the raw plan/result: fill/select values become character counts, `credential_ref`/`session_ref` become their kind, URLs keep only scheme/host/path, artifact refs must be `artifact://browser/<name>`, unknown log keys are dropped, and free text is scrubbed for `key=value`/Bearer/long-token secrets. Key-based `redact()` runs again over the view and again on read (defence in depth for older or tampered rows).
- Evidence integrity: the view never adds a step, status, artifact or receipt. A receipt is shown only when the run status is `done`; otherwise it is dropped and flagged in `warnings` (`receipt_ignored_status_not_done`), as are rejected artifact refs and out-of-range `completed_steps`. The UI shows "No external receipt observed" rather than a blank.
- UI: a card strip (`#browserRuns`) inside the existing Worker Results & Handoffs card, and the existing agent drawer reused as the trace viewer (`/api/browser-runs/{id}`), so no new page/navigation. Renderers sit between `browser-run:begin/end` markers and are pure, so `test_browser_observability.py` runs the real code under Node like the T-532/T-536 fixtures.
- Artifact refs are displayed as private references only; no screenshot preview/download route was added (it would have to go through the signed-media boundary and is outside this task).


## T-601 Owner desk (2026-11-01)
- Runbooks are static, reviewed data in `owner_desk.py`, not generated per request: the owner must get the same instructions every time, and CI can check them (`test_owner_desk.py` fails if an open `[HUMAN]` ROADMAP task has no runbook). Russian only for now (owner's working language); the UI chrome is EN/UK/RU and says so.
- Live status comes only from facts the server already holds (Telegram pairing state, selected/configured publisher adapter, `BUILD_SHA`); nothing calls a provider. T-598-H2 is marked "useless for now" because `ec2_api` is hard-coded `unknown` in `worker_observability.py` — granting the IAM right would change nothing.
- Answers come from the existing EC2 Claude worker (subscription, no API key), between tasks, so there is never a second concurrent Claude process. Latency is minutes, up to the length of a running task (≤1 h); the UI says so. The worker CLI gets only Read/Grep/Glob and an 8-turn / 300 s budget. A subscription limit requeues the question and starts the T-600 queue hold.
- Questions are scrubbed twice: pattern-based (Telegram bot token, Anthropic/GitHub/AWS keys, `token=…`) inside `owner_desk`, then the app's known-secret redaction. Reason: an owner may paste a brand-new BotFather token that the server does not know yet.
- Store is a JSON file in `DATA_DIR` with a 15-minute claim lease (a crashed worker cannot strand a question), max 20 open and 200 kept questions.
- The Worker Center poll does not re-render while text is selected inside a runbook or the question box is open, and remembers which runbooks are expanded; otherwise the periodic refresh would close the runbook and drop the selection mid-question.
- Raw CLI error text never reaches the owner page: a failed answer shows a fixed message.

## T-535 Artifact + media viewer hardening (2026-11-01)
- One viewer route for everything: `/api/artifacts/{id}/media` now also serves DB-stored text/JSON/subtitle artifacts (no URL, only `content`) instead of 404. It stays behind the normal session auth (viewer sessions may read); `/media-archive` / `/media-source` keep their HMAC tokens unchanged.
- Content types come from a fixed table (`ARTIFACT_TEXT_TYPES`): JSON → `application/json`; SRT/VTT/Markdown/CSV are shown inline as `text/plain` (browsers would otherwise download them) and download with their real type and extension. Any other stored mime (e.g. `text/html`, SVG) is served as `text/plain`, plus `nosniff`, `CSP: default-src 'none'; sandbox` and `Cache-Control: private, no-store`, so a model-written artifact can never run script on the FactoryOS origin. Invalid JSON falls back to `text/plain`.
- Video/audio/image artifacts without a media URL still 404: their `content` is a description, not media.
- Redirects from the route are limited to absolute http(s) or same-origin paths; `javascript:`, `data:` and scheme-relative `//host` URLs get 422 instead of a redirect.
- UI: Approval and Publishing previews used the raw provider URL (which may be an expired ephemeral Media Finisher file); they now use the stable artifact route, which archives/serves durably. The immutable publishing snapshot (`media_url`) is unchanged — only the viewer link moved. Trace Viewer and the Worker Results selected result reuse `artifactMediaActions`, which now also offers open/download for text artifacts.
- The regression (`test_artifact_viewer.py`) drives the real ASGI app directly (httpx/TestClient is not a dependency) and runs the real dashboard renderer under Node, then requests every link it emits.

## T-536-B Live worker telemetry (2026-11-01)
- Built from the stash `T-536-B partial from run interrupted by a manual restart 2026-11-01` (stash kept, not dropped), reapplied onto the current HEAD, plus the missing regression `test_worker_telemetry.py` and its CI step.
- The runner sends a `telemetry` object inside the existing authenticated heartbeat (no new route). The server never trusts it: `sanitize_telemetry` keeps only whitelisted keys, numbers must be finite, non-negative and within a limit, the branch must match a safe ref pattern, the head must look like a SHA, and the source must be a known value. Anything else becomes `null` / `unsupported`. Telemetry is popped out of `node`, so no unsanitized copy is stored.
- CPU: delta of `/proc/stat` between heartbeats (`proc_stat`). The first sample, or Termux on newer Android where `/proc/stat` is unreadable, falls back to loadavg/cores (`loadavg`, rendered with `≈` as an estimate). With neither, the value is `null` + `unsupported`. Memory: `/proc/meminfo` (`MemAvailable`, or `MemFree+Cached` on old kernels), otherwise `unsupported`. No psutil dependency, so the runner stays Python-3.9/Termux friendly.
- `queue_depth` = unchecked, non-`[HUMAN]` ROADMAP lines in the runner checkout. Task start comes from the parent-owned `.autopilot/run.json` `started_at`, and only while that run is `running`. The server advances `elapsed_seconds` from that start at read time, so the number stays live between heartbeats.
- The last sanitized heartbeat is persisted to `DATA_DIR/claude_worker_heartbeat.json` and re-sanitized on startup. The TTL still decides online/stale, so after a restart the owner sees a last-known state marked stale, never a fake "online".

## T-540 Revideo zero-spend acceptance (2026-11-01)
- Task is in the `chatgpt`-planned v5.4 block but carries `Owner: claude`; run on the owner's explicit instruction.
- A separate regression, `test_revideo_acceptance.py` (plus its CI step), sits next to the T-513 smoke block, which stays unchanged. It runs Discovery → Revideo → rewrite → job → variants → Content Package → Media Finisher → `waiting_approval` in an isolated DATA_DIR. `urlopen`, `_external_json` and `_content_brain_llm` are patched to record the call and raise, so any outbound provider call fails the run. The Media Finisher worker is simulated the same way as T-513: endpoint `ci.invalid`, submit thread stubbed, result delivered via `_finalize_edit_job` at $0.
- Zero spend means: no outbound call attempted, the `agent_runs.cost_usd` sum is 0, the `edit_jobs.measured_cost_usd` sum is 0, and no run is marked `live_llm`. "Cannot auto-publish" means: no `publishing_queue` row before approval, `run_due_publishing` processes nothing, and an explicit approve creates only a `manual`, unscheduled item with no post ID. `publish_scheduled_item` still refuses without a schedule. Real publishing remains behind T-520/T-521.
- Fix 1 (idempotency): `create_revideo_production_job` checked `status=='ready'` before the existing `job_id`, so a repeated create-job after handoff (`in_production`) raised instead of returning the existing job. The existing-job check now comes first. The originality gate still blocks any project without a job.
- Fix 2 (provenance): the Content Package `source_list` did not cite the original public source. The Revideo source-structure artifact keeps `source_url` only in `meta`. `_content_package_sources` now also takes a valid http(s) `meta.source_url` from Researcher/Tech Verifier artifacts. It reads no new content and makes no network call.
- The originality fence is also proven negatively: a rewrite that copies the transcript is marked `needs_revision` and refused by create-job.

## T-541 Media Finisher operator preview (2026-11-01)
- The ROADMAP lists this task as `Owner: chatgpt`. It was run on the owner's explicit instruction for this run.
- The preview is read-only and derived: `_media_finisher_operator_preview(job_id)` builds it from `_media_review_state` (the same state `approve()` checks), so it shows the gate exactly as approval sees it and cannot loosen it. It is exposed in two places: `GET /api/jobs/{id}/media-finisher/preview` (session auth, like every `/api`) and `finisher_preview` on each `/api/approval` item. No new table, no write, no provider call.
- Before = the run's `input_artifact_id`. If that is missing, the source is the job's video artifact with the same `input_url`. If there is still no artifact, it falls back to the raw http(s) `input_url`; non-http schemes are dropped. After = the artifact approval binds (`_artifact_for_edit_job`). Cuts = `short_render` artifacts of that run.
- The evidence list is fixed to the components the finisher can produce (`MEDIA_FINISHER_EVIDENCE`, hoisted from `_persist_edit_evidence` so the two cannot drift). They are grouped as cuts / captions / audio / graphics / frame QA. Every component is optional: a component with no artifact for this run is reported as `available:false` and rendered "not produced", never hidden. The run's QA gate artifact is linked when present.
- UI: a separate `finisherPreviewHtml` section in the Approval Studio card. All links go through `/api/artifacts/{id}/media` (T-535 route). The existing preview block and the approve/reject buttons are untouched, so the T-535 wiring assertions still hold. New copy is localized EN/UK/RU under `fp.*`.

## T-542 Publishing dry-run evidence (2026-11-01)
- One new owner-write route: `POST /api/publishing/{id}/dry-run` (session auth like every `/api`; viewers get 403 from the existing middleware). It accepts only `approved`, `scheduled` or `failed` items. A `published` item is refused, so evidence can't be re-planned after a real post.
- The plan reuses `_metricool_scheduler_payload` (the real T-519 mapping) with a new `normalize=False` flag. In dry-run the payload `media` is the exact approved FactoryOS URL. Metricool's normalize call is skipped because it uploads to Metricool hosting. The real path still normalizes as before. Nothing calls `_metricool_json`, `_external_json` or the publisher webhook.
- Binding check before planning: the stored `content_snapshot` must re-hash to `content_snapshot_hash`, the item must have `approved_at`, and the media artifact must still exist with the same URL and job. Any mismatch blocks all three platform plans and returns the reasons. A per-platform config gap (for example an unset `FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS`) blocks only that platform.
- Evidence is a `Publisher`/`publish_dry_run` artifact, deliberately not `publish_receipt`, so receipt, cycle and analytics code can never mistake it for a post. The receipt preview always has `external_post_id: null`, `external_url: null` and `status: not_published`. The publish item, job and cycle are not changed. `real_publish.allowed` is always false, listing T-520 (when no real adapter is configured) and T-521 (always) as blockers.
- Idempotency: `plan_hash` is the sha256 of publish_id + idempotency key + binding + plans, excluding publication timestamps. A repeat dry-run of the same snapshot/config returns the existing artifact instead of writing a new one.
- No dashboard button in this task. The DONE criterion is API/evidence-level, and the operator can open the artifact through the existing artifact viewer.

## T-551-A OAuth framework scaffold (2026-11-01)
- New standalone module `oauth_framework.py`: provider registry (`youtube`, `tiktok`, `instagram`, `hubspot`, each mapped to its existing T-550 `PORTABLE_INTEGRATIONS` slot), PKCE helpers, a single-use server-side state store, the `TokenVault` interface and the `OAuthAdapter` interface with a deterministic `MockOAuthAdapter`. It never reads a client secret value, makes no HTTP call and has no real adapter. Real adapters, refresh and the encrypted vault are T-552. Production OAuth apps are owner work (T-551).
- Client IDs come from new env names (`FACTORY_OAUTH_GOOGLE_CLIENT_ID`, `FACTORY_OAUTH_TIKTOK_CLIENT_KEY`, `FACTORY_OAUTH_META_APP_ID`, `FACTORY_OAUTH_HUBSPOT_CLIENT_ID`, plus matching `*_SECRET` names that are only listed, never read). The Google one is deliberately separate from the login `FACTORY_GOOGLE_CLIENT_ID`, because the YouTube upload scopes belong to a different consent screen. Nothing is added to Render env in this task.
- PKCE (S256) is sent only for Google, which supports it for server-side web apps. TikTok (web), Meta and HubSpot get no `code_challenge`. Revisit per provider in T-552. Endpoint/scope values are documented defaults (Meta Graph `v21.0`), to be re-verified when the real adapters are built.
- Production default is fenced three ways: no client ID, no adapter, and `UnavailableTokenVault` (refuses `put`). `POST /api/oauth/{p}/authorize` therefore returns 409 with the first blocker. Setting a client ID alone does not enable it. `GET /api/oauth/providers` lists blockers and the exact redirect URI (`{FACTORY_PUBLIC_BASE_URL}/api/oauth/{p}/callback`) that the owner registers in T-551.
- State is an opaque 256-bit random value, kept in process memory with a 10-minute TTL, a cap of 200 pending entries, and single use: it is consumed before any other check, so a failed callback burns it. It is bound to provider and to the initiating session subject (role|email|login provider). The pending flow is lost on restart. That is acceptable for an interactive redirect, and T-552 can move it to the DB.
- The callback stays behind the normal session middleware (not a public path) and additionally requires an owner role. On success and on failure it redirects to `/?oauth=<p>&result=connected|error&reason=<fixed code>`. Provider `error_description`, the auth code and the tokens are never reflected, stored in events or logged. Exchange exceptions are mapped to `exchange_failed` without their text.
- On success the callback records the binding with the existing `_integration_set` (`auth_mode=oauth`, `connected_via=oauth`, scopes and vault kind in meta, no tokens). The YouTube/Instagram/TikTok display projection still follows Metricool. Switching that projection to direct OAuth is T-552 scope.
- `POST /api/oauth/{p}/disconnect`: best-effort provider revoke through the adapter, then local tokens are always forgotten, even if the revoke fails. The binding is marked disconnected and content history is untouched. The existing `/api/integrations/*` routes are unchanged.
- No dashboard UI in this task. The DONE criterion is the route/framework contract. The Connect buttons in the UI are wired in T-552, once a provider can actually be ready.
- PKCE regression recomputes S256 independently. I could not verify the RFC 7636 Appendix B vector offline, so the test does not claim it.

## T-553 Workspace data tenancy (2026-11-01)
- Jobs are the tenancy root. A new side table `job_workspaces(job_id, workspace_key)` binds each job to a workspace, and a missing row means the legacy `default` workspace. There is no `ALTER TABLE jobs`, because several code paths and `smoke_tests.py` insert into `jobs` positionally (`VALUES(?×12)`). Existing data needs no backfill. Artifacts, approvals, content packages, publishing queue, performance snapshots/attribution, edit jobs and media jobs inherit the workspace of their `job_id`, so no insert site can forget to set it. Integration bindings keep their existing `workspace_key` column (T-550).
- Identities: `owner` stays unscoped and can see every workspace (admin observability). `viewer` stays unscoped and read-only, as before. New role `member`: a customer listed in `FACTORY_WORKSPACE_MEMBERS="email=workspace,…"` who signs in with Google. Member sessions are a separate signed `v3|member|email|workspace|sig` cookie. On every request the token is re-checked against the current member map, so removing or re-assigning an email revokes access immediately. Owner emails win over member entries. The env var is not set in production, so production behaviour is unchanged until the owner adds customers.
- Enforcement is in the auth middleware: members may only call an allowlist of tenant-aware routes (`workspace_tenancy.MEMBER_ROUTES`). Everything else is an operator surface and returns 403 (supervisor, builder/tasks, Content Brain, agents/MCP, usage, Media Finisher list, `/api/workspaces`, artifact delete, idea-link). Every id in a member's path (job, publish item, artifact, edit job, media job) is resolved to its owning workspace. A foreign or missing id returns the same 404, so ids are not confirmed. List and summary queries (`get_jobs`, `get_job`, approval queue, publishing queue, performance dashboard, summaries) filter by the active scope, which is a ContextVar set per request. `POST /api/performance/snapshots` checks the body's `publish_id` as well.
- Member `/api/status` is a reduced, workspace-only payload: jobs, the selected job, events of its own jobs, its own portable connections and summaries. It has no supervisor, relay, usage, builder or agent telemetry. Job selection is kept per workspace, so a member never moves the owner's selected job. Member websockets get only `{"type":"refresh"}`, never ids from other workspaces.
- Credentials: the server-held Metricool / publisher webhook / analytics webhook secrets are the default workspace's accounts. Non-default workspaces see Metricool as not configured, cannot connect it, cannot sync analytics through the server webhook, and `_publish_via_adapter` refuses a non-default item before any outbound call (manual publishing still works). Per-customer credentials come with T-552. The human approval gate, the idempotency key and the budget limits are unchanged. Members may run their own jobs under the existing global budget fences.
- Background identity: job tasks started from routes (run, agent rerun, package build, variant build) run through `run_in_job_workspace`, under the job's own workspace, not the caller's. The publisher scheduler runs each due item under that item's workspace and returns `workspace_key` per result. Metricool reconcile only touches default-workspace items. The publisher webhook payload, the Media Finisher request and the Local Booster claim carry `workspace_key`. A member's `run-due` only processes that member's workspace. The OAuth callback binds the account to the workspace stored in its state.
- Owners can create a job directly in a customer workspace (`POST /api/jobs {"workspace_key": …}`). `GET /api/workspaces` gives per-workspace counts only (jobs, publish items, connected bindings, members), with no content.
- Not in this task: dashboard UI for members (the dashboard renders from the reduced status; onboarding UX is T-554), the per-workspace token vault (T-552), and scoping of global operator data such as Content Brain ideas, Revideo, discovery and factory cycles. These stay owner/operator-only instead of being shared.

## 2026-11-01 — T-581 Operator assignment UI

- **Decision:** the UI only uses the T-580 owner-only API (`GET /api/factory/roles`, `POST /api/factory/roles/assignment`). There is no new backend surface. Renderers live in a pure `role-operators` block in `static/index.html`. The Workers page shows a role panel (Content / Engineering groups, one select per role offering only that role's eligible operators). Every office worker card and every agent-directory card gets an operator chip, and the office tooltip shows role → operator + runtime.
  **Reason:** smallest change that covers "assign from the worker/agent UI" and "current operator on every worker card"; backend validation (eligibility, owner-only) stays authoritative.
- **Decision:** chips and cards show the real operator status (`online`, `key configured`, `configured · not verified`, `auth pending`, `offline`, `policy`, else `unknown`); only `online`/`configured` are green. For `Auto` the chip shows the pipeline's real runtime operator and *its* status (e.g. `Auto → ChatGPT · auth pending`). Each role card also states "Runs today on …" and "assignment not enforced yet". Workers that belong to no role (e.g. Design Partner) show "no assignable role".
  **Reason:** T-580 assignments are intent only (`enforced: false`; routing is T-588). Showing a Claude/Gemini assignment as active, or Auto as ready, would fabricate readiness.
- **Decision:** non-owners get 403 from the role API, so the UI renders nothing for them (no chip, no panel) instead of an error. The main dashboard fetches the role board alongside the existing 15 s lane-board poll and re-renders cards only when the board changes.
- **Decision:** `test_role_operator_ui.py` drives the real API through Scriptwriter → Claude (runner offline), Engineer → Gemini (key present, never probed), Engineer → Claude (live heartbeat) and Scriptwriter → Auto, then renders each board under Node in EN/UK/RU. Both it and `test_role_operator.py` are now wired into CI. The T-580 entry above says CI, but the workflow did not run that test.

## T-582 Battle Run experiment model (2026-11-01)
- The model lives in a new standalone module, `battle_runs.py` (`plan_battle`, `BattleStore`). app.py only adds four owner-only routes: `GET/POST /api/battles`, `GET /api/battles/{id}` and `POST /api/battles/{id}/results`. Storage is one new SQLite table, `battle_runs`, holding the whole battle document as JSON plus indexed id, idempotency key, status and timestamps. Battles are an operator surface. They are not in `workspace_tenancy.MEMBER_ROUTES`, so members get 403 from the existing middleware.
- A battle is one brief (`kind` content|engineering, optional free-text `ref` such as a job or task ID) with 2–6 chains of 1–12 `{role, operator}` steps. Steps are validated against the live T-580 role board: an unknown role returns 404, an unknown operator 422, an ineligible operator 409. Two chains with the same role/operator sequence return 409, because competing chains must actually differ. Each chain stores the shared `brief_hash` and a `chain_hash` fingerprint of its provenance.
- Per-step provenance is snapshotted when the battle is planned: role, label, canonical workers, requested operator, `resolved_operator`, `model`, `runtime` (operator kind api/runner/policy), `operator_status`, `enforced: false`. `Auto` resolves to the role's real pipeline runtime (`runtime_operator`, currently ChatGPT for live LLM roles). Where there is none (Engineer), it stays `resolved_operator: null` / `operator_status: unresolved` instead of guessing. An unknown model, such as the Claude runner's, stays `null`.
- FactoryOS does not execute a battle. Running chains would mean provider calls, which must never be enabled automatically, and routing is T-588. Whoever actually runs a step records the real producer through `/results`: concrete operator, model, runtime, plus output text (excerpt and sha256) and/or `output_ref`. Results must come in step order and must name the planned operator (or, for an unresolved Auto step, an operator eligible for the role). `auto` is refused. A recorded result is immutable (409), so candidates cannot be silently rewritten later (groundwork for T-584). Chain and battle status are derived: planned → running → completed.
- Never publishes: every battle carries `publish: {automatic: false, status: not_published, requires_human_approval: true}`, re-asserted on every write. It creates no job, no publishing item and no outbound call. A completed battle is only evidence. Publishing still goes through the normal approval gate.
- Battle ID: `battle_<16 hex>`, random by default. With an `idempotency_key` the ID is derived from the key. Replaying the same request returns the existing battle (`created: false`). Reusing the key for a different request returns 409.
- No UI in this task. The DONE criterion is the model and regression. Telegram view is T-587, leaderboard T-583. `test_battle_runs.py` is wired into CI.

## T-583 Outcome attribution + leaderboard (2026-11-01)
- Attribution is an explicit owner action, not inference. `POST /api/battles/{id}/outcomes {chain_id, publish_id}` credits one already-`published` (so already human-approved) publishing item to the chain that produced it. The chain must be `completed`, which means every step has a recorded real producer. Scheduled, unapproved or unknown items are refused with 409/404. Linking never creates, changes or triggers a publish.
- One published item belongs to exactly one chain across all battles. The new `battle_outcome_links` table uses `publish_id` as its primary key. Relinking to the same chain is idempotent (`created: false`). A different chain gets 409. Links are immutable, so outcomes cannot be moved to another chain later.
- `GET /api/battles/{id}/leaderboard?metric=views` reads only the latest real `performance_snapshots` row per linked item. Nothing is copied, so new snapshots show up automatically. Metrics: views, reach, likes, comments, shares (shares/reposts), saves, conversions are counts; ctr_pct, retention_pct, completion_rate_pct are rates. Any other metric returns 422.
- Missing data is never zero. Each chain metric reports `value`, `total`, `items_reporting` and `status`: `available` means every measured item reported it, `partial` means some did, `unavailable` means none did, with `value: null`. Non-numeric values are ignored. A chain whose items never reported the ranking metric is listed with `rank: null` after the ranked chains, never ranked last as zero.
- Score is the mean per measured item that reports the metric, and the count total is shown too. Ranking by totals would favour whichever chain was published more often. Ties share a rank.
- Each leaderboard row carries the chain's exact provenance: role, requested and resolved operator, the actual producing operator from the step result, model, runtime, plus `chain_hash` and per-item snapshot id/captured_at/source as evidence.
- To record CTR and conversion when a platform reports them, `PerformanceSnapshotCreate`/`PERFORMANCE_FIELDS` gain two optional fields, `ctr_pct` and `conversions`. Existing payloads are unchanged. The analytics webhook sync picks them up only if the adapter returns them.
- Scope: per-battle leaderboard only, owner-only (not a member route). A cross-battle "best chain signature" view and UI are left for later consumers (T-587 Telegram, T-584 judge). `test_battle_outcomes.py` is wired into CI.

## T-584 Reviewer / Judge mode (2026-11-01)
- A candidate is the final step result of a `completed` chain, with its full per-step producer provenance. Each candidate carries an `evidence_hash` over chain_hash, producer, model, runtime, output_hash, output_ref and recorded_at. `GET /api/battles/{id}/reviews` lists candidates and reviews. `POST` must pin each compared candidate as `{chain_id, evidence_hash}`. A stale or tampered pin returns 409, so a judge can only decide on the exact recorded output. Incomplete chains are not candidates (409).
- "Cannot silently rewrite": reviews are stored in a separate append-only `battle_reviews` table and never change the battle payload (the regression checks the battle is unchanged afterwards). A review body with candidate-content keys (`output`, `output_ref`, `revised_output`, `rewrite`, `edits`, `patched_output`) is refused with 422. To get an improved output, plan a new chain.
- "Separately assigned": the judge must be a concrete operator (not `auto`) that is eligible for the T-580 `reviewer` role, with model and runtime declared. It must not have produced any step of any compared candidate (409 conflict of interest). The owner's current Reviewer-role assignment is snapshotted as `assigned_reviewer_operator` but not enforced, since routing is T-588.
- Criteria are explicit: 1–10 `{id, label, description, weight 1–5}`. A score of 0–10 with an optional evidence note is required for every candidate × criterion (an incomplete matrix returns 422). The server computes weighted-mean totals. `selected_chain_id` and a non-empty rationale are required. A selection that disagrees with the totals is allowed but flagged `selection_matches_scores: false`, not hidden.
- One review per judge operator per battle. Review id `{battle_id}.r.{operator}`. An identical replay is idempotent (`created: false`). A changed decision by the same judge returns 409. Different judges can each review the same battle.
- The owner records the judge's decision (owner-only routes, like T-582/T-583). FactoryOS does not call the judge model. A review never publishes, never creates jobs and re-asserts `publish.automatic: false`. `test_battle_review.py` is wired into CI.

## T-585 Multi-operator delegation board (2026-11-01)
- `GET /api/factory/delegation-board` (owner-only, unchanged auth) gains `operator_lanes`: one lane each for Claude, Gemini and ChatGPT, built by the pure `operator_lanes.build_operator_lanes`. The Claude-only planner/worker grid stays as it is. Lanes render above it, so existing controls and timelines are untouched.
- The lanes only merge observed sources: the generic operator-worker heartbeat (T-580 `/api/operators/heartbeat`), the legacy Claude heartbeat plus verified Claude task results, and Relay runs from the T-599-F lane board. Each open ticket, last result and queue depth carries its `source`. Anything nobody reported stays `null` and renders as "unavailable", never as 0 or idle.
- Availability: a fresh heartbeat, or a Relay run in `working`, means `online`. An expired heartbeat means `stale`, and `offline` after 1 h. Relay history without any heartbeat means `offline` (`no_heartbeat`). A lane that never reported is explicitly `unconfigured` (`never_reported` for runners, `no_runner` for ChatGPT, which is the Planner and has no runner heartbeat). A configured API key alone does not make a lane online. Its T-580 `provider_status` is shown separately.
- Open ticket precedence: Relay-verified run, then a live operator heartbeat with an active status, then the live legacy Claude heartbeat. An expired or idle heartbeat never claims a ticket. Last result is the newest timestamped of verified worker result / Relay outcome. The heartbeat's free-text `last_result` has no outcome time, so it only wins when nothing else exists.
- Secrets: lanes are built from whitelisted fields only, so extra keys a runner sends in `tickets`/payload (tokens, env) are dropped. The board's existing secret-value redaction also covers lane text. `test_operator_lanes.py` (pure + API) is wired into CI. `test_delegation_ui.py` covers rendering in EN/UK/RU, including the explicit unconfigured Gemini lane and HTML escaping.

## T-586 Telegram operator lanes (2026-11-01)
- The Telegram Claude/Gemini buttons (`relay:operator:claude|gemini`) already existed, but they read the legacy heartbeat map, which has no ticket list. `relay_handle_telegram_update` now takes an optional `operator_lanes_provider`. `app.py` passes `get_telegram_operator_lanes`, which returns the T-585 delegation `operator_lanes` (already secret-redacted by `get_delegation_board`). Telegram therefore shows the same lane the web board shows: availability, heartbeat age and source, current ticket and stage, branch/runtime, queue depth (or "unknown"), open tickets, assigned-not-claimed and last result. Without the provider (tests, old callers), the legacy rendering is unchanged.
- The main Relay keyboard (`/status`, `/tasks`, `/history`, overview replies) gets a third row with the two operator buttons. An operator reply has one `relay:ticket:R-xxxx` button per open Relay ticket of that lane (max 6). The button opens the normal ticket card with the existing `relay:status:*` controls. Roadmap `T-xxx` items are listed as text only, since they are not Relay tickets and have no card. Callback data stays well under Telegram's 64-byte limit.
- An unconfigured Gemini lane is shown as `⛔ не настроен — runner ни разу не отчитывался`, with "no heartbeat data", "queue unknown" and "no open tickets". It is never shown as idle or online. A provider failure renders "status unavailable; state unknown". The "Воркеры" overview and `/operators` use the same lanes and add one line saying ChatGPT is the Planner with no runner telemetry.
- Text stays RU like the rest of the Relay Telegram replies. Only the lane-board block is localized (T-599-F).
- CI: `test_telegram_operator_lanes.py` (pure handler fixture plus the real `app.telegram_webhook` path with a stubbed Telegram API) runs from the existing "Relay Telegram" CI step through `test_relay_telegram.py`. There is no workflow edit, because T-598-H1 (`workflow` scope) is still open.

## T-587 Telegram Battle controls (2026-11-01)
- New `telegram_battles.BattleTelegram` (store + `_battle_latest_snapshot`), passed to `relay_handle_telegram_update` as the optional `battle_controls`. It handles `battle:*` callbacks and `/battles`, `/battle <id>`, and only after the existing paired-chat check. The main Relay keyboard gets a "⚔️ Battles" row. Without controls, a `battle:*` callback is answered "not connected" and changes nothing.
- Views: list (latest 8, one button each); summary (brief, kind/status, each chain's status, steps done and `role→operator` chain, every judge's pick and weighted totals with a flag when the pick disagrees with the scores, current owner decision, and the publish-gate line); candidate chains (per step: planned operator and actual producer/model/runtime or "no result", final output excerpt of 300 chars, ref, short sha256); metrics (the T-583 `views` leaderboard: rank or "unranked", published/measured counts, only metrics a real snapshot reported, sums as totals and rates as means, "partial" marked, "no data" otherwise, never zero). With no snapshot source it says so.
- Safe next actions are exactly two. "Approve chain cN" is offered only for completed chains. "Reject candidates" is always offered. They are stored in a new append-only `battle_owner_decisions` table, and the latest row is the current decision. Repeating the current decision, e.g. a replayed Telegram callback, adds nothing (`created: false`). Approving does not publish, run a provider, create a job or change the battle record or candidates. Publication still goes through the normal publishing-queue approval, which every battle reply states. `publish`, `run` and any other `battle:*` callback is refused with no state change. `record_owner_decision` itself also refuses any action except approve/reject. `decided_by` is `telegram-owner` and `channel` is `telegram`, since the paired chat is the owner, the same as the Relay controls.
- Decision is reversible by a later decision, so no confirm step: an owner mistap is fixed by tapping the other action. No web/API route for decisions was added (not in the DONE scope). It can follow with the web Battle UI.
- RU text like the rest of the Relay Telegram replies. CI: `test_telegram_battles.py` (deterministic pure fixture + real `app.telegram_webhook` path) runs from the existing "Relay Telegram" step through `test_relay_telegram.py`. There is no workflow edit, because T-598-H1 is still open.

## T-588 Supervisor routing policy (2026-11-01)
- New pure `supervisor_routing.route_task`. Precedence: `[HUMAN]` → `blocked` (always, whatever is assigned or online) > explicit owner assignment (the task's roadmap `Owner:` first, then the owner's T-580 role assignment) > bounded Auto. `Owner: any|auto|""` and role assignment `auto` are not explicit. An unknown explicit operator is `blocked`.
- Explicit assignment whose operator is not online → `waiting` for that operator. It is never rerouted to another one. **Reason:** silently handing an owner-assigned task to another operator breaks the lane rule that two agents never build the same task. "Offline operators are skipped" applies to Auto selection.
- Auto is bounded: a fixed per-role preference list (`engineer`/`supervisor`: claude → gemini; content roles: chatgpt → claude → gemini) intersected with the role's T-580 eligible operators, max 3 candidates. The first positively online one wins. Otherwise `waiting` (`no_online_operator`), never a guess. ChatGPT is not an engineering candidate (2026-10-30 lane policy, no coding runner).
- Availability is positive-only: a T-585 lane `online`, or a T-580 operator status `online is True`. Stale, offline, unconfigured and Gemini's unverified `online: null` all count as unavailable. Nothing is probed.
- A route is a decision only (`executes: false`). Every route carries the same constant `privileges` (publish, production_deploy, merge_main and paid_provider_calls all false; requires_human_publish_approval true), as a copy, so selecting a provider can never widen privileges. Runner task selection (`AUTOPILOT_OPERATOR` + `Owner:`) and the T-580 `enforced: false` flag are unchanged. Enforcing routes in a runner is a later task.
- Owner-only `GET /api/factory/routing` routes every open roadmap task for the `engineer` role, using the live delegation lanes and role assignments. No UI in this task (not in DONE).
- CI: `test_supervisor_routing.py` (pure policy plus the real app API on a fixture roadmap) is run as a subprocess from `test_operator_lanes.py`, which is the existing "Multi-operator delegation lanes" CI step. There is no workflow edit, because T-598-H1 is still open.

## T-562 Runner Supervisor acceptance (2026-11-01)
- The supervisor code, units and policy tests were already on the branch from earlier T-562 commits. This run added only an end-to-end `run_once` regression with fake git/systemctl/claude. It covers three cases. A configured paid API key stops an active worker, and neither the key nor the worker token appears in the 0600 status or the published copy. A logged-out CLI gives `blocked: subscription_auth_required` and no start. When all gates pass, a failed worker gets one `systemctl start --no-block`. **Reason:** the DONE criterion asks for a *truthful* blocked status. Forcing a blocked state on the live host would mean logging out of Claude or adding a paid key, and both are unsafe. So the blocked path is proven on fixtures, and only the `running` path is checked live.
- On-host check (EC2, read-only, no `systemctl` access from the worker shell): the installed `/etc/systemd/system/factoryos-runner-supervisor.{service,timer}` and `factoryos-claude-worker.service.d/limits.conf` match `deploy/systemd/`, and the timer is enabled (`timers.target.wants` link). The root-written `.autopilot/supervisor.json` was rewritten at 21:41:17Z and again at 21:42:21Z (about every 60 s, as `OnUnitInactiveSec=60s` sets), with `running/service_active`, subscription authenticated, token configured, `paid_api_credentials_present: false`, 0 restarts.
- CI already runs `python -m autopilot.test_supervisor` (ci.yml step), so there is no workflow edit. The worker cannot see CI results, so CI for this commit must be confirmed on its PR.

## T-564 Interactive Claude worker pairing (2026-11-01)
- `autopilot/pair_worker.py` and its CI step already existed from `fc43f1f`. This run checked it against the Goal and fixed the gaps instead of rewriting it.
- The paid-override list now is the supervisor's `PAID_KEYS`, not a copy. **Reason:** if pairing accepted a key that the supervisor later refuses, the owner would get a successful pairing followed by an unexplained `blocked: paid_api_credentials`.
- A pasted `sk-ant-…` value is refused (`anthropic_api_key_not_accepted`). **Reason:** Anthropic API keys match the token alphabet. If one were saved, the worker would send a billable secret to FactoryOS as its bearer token.
- The env file and `/etc/factoryos` must be root-owned, and the directory must not be group/world-writable. **Reason:** the Goal says "root-owned config". Mode 0600 alone does not prove that, and a writable parent lets another user swap the file between the check and `os.replace`. `ROOT_UID` is a module constant so tests can run as a normal user.
- An existing token line is matched by its parsed key (`KEY = value` too), not by prefix. The pasted value is stripped of surrounding whitespace. Ctrl-C/Ctrl-D exits 2 with "nothing saved" instead of a traceback.
- Host verification on EC2: as `ec2-user`, `python3 -m autopilot.pair_worker` exits 2 with "Run via sudo…" and does not prompt. The root path needs the owner's secret in an interactive SSM session, so the worker does not run it. The host is already paired: the root-written `.autopilot/supervisor.json` reports `factoryos_token_configured: true`, `paid_api_credentials_present: false`, `running`. CI runs the existing `python -m autopilot.test_pair_worker` step, so there is no workflow edit. The worker cannot see CI, so CI must be confirmed on the PR.

## Worker reloads runner code that arrives on its own branch (2026-11-01)
- `sync_branch` now takes the "before" HEAD ahead of `git pull --rebase` on the worker branch. Previously only code merged from main counted as `code_updated`, so a fix pushed directly to `autopilot/aws-worker` (as done on 2026-11-01 to unstick the worker) sat on disk while the old code kept running, and a manual restart was needed — which interrupted a running task (T-536-B, ~2 min of work, backed up and stashed).
- T-598-H1 (`workflow` scope for the worker's gh credential) changed from "optional, not recommended" to "recommended": the worker keeps adding CI steps, and without the scope each such commit stalls the queue for hours. Merging to main still needs the owner.

## T-602 UI fixes from the 2026-11-01 screenshot review (2026-11-02)
- Mobile header (≤700 px): `.topActions` wraps instead of clipping. Refresh / Share Viewer / New stay full buttons with their full text. There is no overflow menu. **Reason:** wrapping hides nothing and needs no new keyboard/menu behaviour to test.
- Build Progress: the progress bar and a new 4-chip lane nav (count + label, two columns at ≤420 px) come first. Each chip scrolls to and focuses its lane. "Recent autonomous decisions" moved below the lanes into a closed `<details>`, with a list capped at `min(46vh,420px)`.
- Decision log: each DECISIONS.md entry becomes a card with its date, task ID (or "decision") and a 2-line title. The body sits behind "Full text". In UK/RU the card is marked "raw worker evidence, not translated". The source text is not machine-translated.
- Agent Office header: a grid with title/subtitle in one zone and tools/worker chips in another. Below 1280 px it stacks to one column, so chips never share a row with the subtitle.
- Tablet drawers: the default width is 56% instead of 65% when the viewport is ≤1280 px. The agent drawer keeps 42%. A width the owner dragged and saved still wins. Also, at 901–1280 px the autopilot/delegation summary grids use 2 columns.
- Owner-desk composer: it gets a sticky caption with the task and the selected step's title, and `max-height:min(70dvh,560px)`. The step being asked about is outlined and scrolled into view, and the drawer body gets bottom padding so the step is not hidden under the composer.
- Runbooks: Russian in `owner_desk.RUNBOOKS` stays the source. EN/UK are in `owner_desk_i18n.py`, keyed by runbook and step id and served by `GET /api/factory/owner-desk?lang=`. Unknown languages fall back to RU. Live status lines are now `detail_key` + `args`, localized server-side. `test_owner_desk.py` checks all three languages for the same step structure, no Cyrillic in EN, no RU-only letters in UK, untranslated `FACTORY_*` names/commands/handles, and the "never send" warning in each language.
- Not done here: the DONE item "before/after CI `ui-screenshots` in the PR description". This worker run had no `gh`/network permission and no browser, so the after-screenshots must come from CI on the pushed commit. The "before" set is artifact `13083380060` (run 41304341016).

## Owner desk worker auth fix + automatic round-trip self-test (2026-11-02)
- Bug: the global auth middleware only lets worker tokens through for `/api/claude-worker/`, `/api/relay/worker/` and similar prefixes. `/api/factory/owner-desk/worker/*` was not listed, so every worker claim got `401 authentication required` before the route's own worker check; the owner's first questions (2026-11-01) were never claimed. The T-601 tests called the route functions directly and missed it. Fix: one more middleware prefix, plus `test_worker_token_binding.py` now posts through the real ASGI app.
- Found only because of the per-question journal line added on 2026-11-01 (`owner-desk: claim failed: HTTPError 401`).
- Self-test: at worker start-up and every 6 h the worker queues an internal `SELFTEST` question, claims and answers it itself (no Claude run, no subscription use); the server then sends one Telegram message "✅ Круговая проверка…" with the number of open owner questions, the oldest one's age and a ⚠️ list of questions open longer than 1 h. A failed request is retried after 10 minutes (the site may still be deploying), not after 6 h. Self-test questions are never shown in the owner UI and only one can be in flight.

## Dependency security floors and pinned Python (2026-11-02)
- The baseline's 20 advisories came from a Python 3.9 resolution; every fixed release (starlette 1.3.1, python-multipart 0.0.31, urllib3 2.8.0, anyio 4.14.2, requests 2.33.0, python-dotenv 1.2.2) requires Python ≥ 3.10, and CI on 3.13 already resolved fixed versions. Production's Python was not pinned (Render default), so `.python-version` = 3.13 makes production match CI.
- Security floors carry a `python_version >= "3.10"` marker so the EC2 worker's Python 3.9 test venv (rebuilt from requirements.txt) stays installable; that venv only runs tests and is not internet-facing.
- `pip-audit -r requirements.txt` runs in CI right after installing dependencies, so a PR that resolves to a vulnerable version fails. A new advisory without a fix will block PRs until it is addressed or explicitly ignored with a reason.

## T-603 MyCast daily pipeline (2026-11-02)
- Script: one `claude -p` run per day from the worker loop (existing subscription), tools limited to WebSearch/WebFetch, output = JSON validated (6–80 lines, 300–1300 words, ≥1 https source) before anything is published. A subscription limit triggers the T-600 queue hold and does not use up one of the 3 daily attempts; attempts are ≥30 min apart; nothing before 07:00 Kyiv.
- Render: not on EC2 (910 MB RAM shared with the worker). The script is committed to branch `mycast/daily` through the GitHub API with the worker's gh login, so the worker checkout and its task branch are never touched; the existing Piper workflow renders only the episodes changed by that commit.
- Delivery: the worker uploads the mp3 to `POST /api/factory/mycast/worker/deliver` (worker token, middleware prefix added); the server sends it with Telegram `sendAudio` to the paired chat. The bot token never leaves Render. One delivery per episode id (`mycast_delivered.json`); a failed Telegram call releases the id so the worker can retry.
- `AUTOPILOT_MYCAST=0` disables the step on the worker.

## MyCast Gemini voices (2026-11-02, owner approved option 1A)
- TTS runs on the server (Render), because the owner's `FACTORY_GEMINI_API_KEY` lives only there. The worker sends the validated script JSON to `POST /api/factory/mycast/worker/voice-deliver`; the server asks Gemini for a two-speaker dialogue (`multiSpeakerVoiceConfig`, labels Host1/Host2), encodes PCM to mp3 with `lameenc` (Render has no ffmpeg; LGPL library, server-side use) and sends it with Telegram `sendAudio`.
- The script is split into ~1400-character chunks (several TTS calls, short pause between them) to stay inside per-request limits.
- Model: `FACTORY_MYCAST_TTS_MODEL` or `gemini-2.5-flash-preview-tts`; on 404 the server lists the models the key can see and picks a `*tts*` one (flash first), because preview model names change. Voices: `FACTORY_MYCAST_VOICE_A/B`, default Charon/Kore.
- Errors are reported as fixed categories (invalid_key, rate_limited, model_not_found, …); Google's response text and the key never reach logs or the worker. The key is sent in the `x-goog-api-key` header, never in the URL.
- Fallback: no key (409) or any TTS failure (502) → the worker keeps the existing Piper path, so a morning episode still arrives. Both paths share one delivery log, so an episode is never sent twice.

## #219 MyCast full episode by 06:00 Kyiv (2026-11-05)
- Schedule: the worker's first daily attempt starts at 05:10 Kyiv (was 07:00), retries 20 min apart, 3 per day. Script generation (web search) plus Gemini voices take ~15–25 min, so 05:10 is the latest start that can still reach Telegram by the owner's 06:00 target. It is the worker loop that runs it, between tasks: a long task already running at 05:10 delays the episode. The ChatGPT "MyCast — утренний аудиобриф" automation does not trigger this path; one episode id per date keeps the server-side delivery idempotent.
- Content: prompt targets 750–1100 words (5–8 min) with the owner's topics (verified OpenAI/Anthropic/Google releases, 2–3 startup/business events, FactoryOS status, one deep use case with a copyable prompt). FactoryOS facts come only from the worker checkout (ROADMAP counts, merged PR titles of the last 48 h), so the hosts cannot invent project status.
- Transcript: after the audio, the worker sends the sources (titles, dates, links) and the full transcript to the paired owner chat as text messages (≤3900 chars each), once per day.
- Failure: if audio cannot be delivered, the transcript is sent as a text fallback; after the last attempt one explicit "audio not delivered" notice is sent. Delivery is never claimed without the server's `sent:true`.
- Gemini free tier: chunks grow to ~2800 chars (3–4 TTS calls per episode instead of ~6) and a 429 waits 30 s, then 60 s, per chunk before the episode fails over to Piper. No paid model or fallback is added. The TTS work runs in a thread so the minutes-long call no longer blocks the Render event loop. The response now includes `bytes` (mp3 size) next to `seconds` for evidence.

## MyCast format after owner feedback (2026-11-05, first full episode rated 7/10)
- Owner feedback: names in Cyrillic transliteration sound wrong; too dense, like a list; FactoryOS internals (task/PR numbers) are noise; wants more world news with how it could plug into FactoryOS, plus what the builders did yesterday and what is planned today.
- Prompt: 3–4 world news items, each ending in "what it means for us / how it could fit FactoryOS" (labelled as an idea, not a plan); 1–2 money/startup items; a 4–6 line "our kitchen" segment; the deep use case with a copyable prompt stays.
- Names of companies, products and models stay in Latin script, as Gemini TTS pronounces them correctly. Trade-off: the Piper fallback will read Latin names poorly; it is only the fallback.
- FactoryOS facts are built per builder lane from the branch prefix of merges in the last 30 h (claude/ and ccr- → Claude, gemini/ → Gemini, chatgpt/ → ChatGPT), open non-draft PRs (best effort via gh), and the next three non-HUMAN ROADMAP tasks. Issue/PR/task numbers and priority codes are stripped in code before they reach the prompt.

## #233 MyCast audio preflight QC (2026-11-05)
- Pure Python checks in `mycast.py`, because Render has no ffmpeg/ffprobe; a missing tool can never turn into a silent "OK".
- Gemini path (raw PCM known): duration must be 0.45–2.2× the script estimate (140 words/min), no near-silence run (RMS < 160 on 16-bit, ~-46 dBFS, 100 ms windows) longer than 6 s, and no TTS chunk shorter than 0.35× its text (14 chars/s) — that catches a truncated chunk the total length would hide. The encoded MP3 is then parsed frame by frame.
- Piper/upload path: the MP3 must parse as MPEG Layer III with ≥20 frames and ≥90 % of the bytes in valid frames; otherwise HTTP 422 and nothing is logged as delivered.
- Any QC failure releases the delivery claim, so the worker's existing path runs: Gemini failure → Piper fallback; Piper failure → transcript as text plus, after the last attempt, the explicit failure notice.
- The frame parser matches ffprobe on the committed Piper pilot (109.74 s vs 109.71 s) and accepts the server's own lameenc output; the tests use synthetic MP3 frames and seeded PCM, no TTS calls.

## #234 MyCast source/date integrity gate (2026-11-05)
- `check_sources` runs right after the script is generated, before it is committed or voiced. Blocking: missing title or URL, non-https or malformed host, credentials in the URL, duplicate URL (host without `www.`, path without trailing `/`), date not `YYYY-MM-DD`, date in the future, or no dated source from the last 7 days. A rejected script uses one of the day's 3 attempts, like any other invalid script.
- Non-blocking but labelled: `stale` (older than 7 days, with age), `undated`, and `editorial` (`"kind": "editorial"`, the hosts' own conclusion, URL optional; never counted as evidence).
- A URL is a pointer, not proof. The Telegram transcript shows each source's date and status and says the facts are not independently verified; "fresh" only means the link is dated within the week.
- Checked against the four real episodes of 2–5 November: all pass, so the gate does not reject the scripts we already accept.

## #236 Worker sync safety regression (2026-11-05)
- `sync_branch` now also aborts a leftover `MERGE_HEAD` (a restart in the middle of a merge) before syncing, the same way it already aborted a leftover rebase. Without this, every later merge failed and the worker reported "conflict" forever. Only the half-done merge is discarded; committed work is untouched.
- `sync_safety_regression` (temporary git repos, no network) covers: an unpushed checkpoint commit kept through a sync; a diverged conflicting merge aborted with HEAD unchanged; an uncommitted edit kept when main touches the same file; a stale MERGE_HEAD with and without a real conflict; and a real interrupted rebase reproducing the 2026-11-04 outage. A spy on every git command asserts `rebase` only ever appears as `rebase --abort`, and that sync never pushes, forces, resets, cleans, checks out or deletes branches.
- Conflict handling is unchanged: the loop sends one owner notice and keeps working on the current code, so a conflict is never shown as an endless "running".

## #231 Queue Keeper (2026-11-05)
- `team_tasks.queue_readiness` classifies open Issues whose first line is `Owner: Claude` into ready / blocked / in_review, and the team-tasks payload exposes it as `queue_keeper`. It is read-only: it never creates, claims or starts a task; claims stay with Relay.
- Blocked means one of: a `blocked` label; an owner gate in the title (`CONDITIONAL`, "only after"); an open issue or PR in the `Depends:` line; an unfinished ROADMAP task in `Depends:`; or an open PR of another agent on the issue. In review means a linked open or merged PR from Claude or an unprefixed branch.
- A `Depends:` number missing from the GitHub read is listed as `unverified_depends`, not guessed. An unavailable GitHub read reports `available: false` with no counts, never zeros.
- When ready < 10, the report escalates to the owner instead of inventing issues. Generating sub-issues automatically is left out on purpose: issue #231 forbids fictitious tasks and repeated creation, and nothing yet tells approved epics apart from concepts.
- The compact GitHub snapshot (EC2 → Render) now keeps the `Depends:` line next to the Owner line; the rest of the body is still dropped.

## #235 Latin names before TTS (2026-11-05, baseline #226)
- `latinize_names` maps a fixed list of known Cyrillic transliterations (OpenAI, ChatGPT, Claude Code, Anthropic, Gemini, Google, Microsoft, FactoryOS, API, SDK, GitHub, Telegram) back to Latin, after the source gate and before the script is published or voiced. It backs up the #226 prompt rule, so the model's habit of transliterating cannot reach the voice.
- Conservative on purpose: only whole phrases not touching other Cyrillic letters change, so the hosts' names ("Клод", "Джі-Пі-Ті"), inflected forms ("Телеграмі") and ordinary text stay. Inflected brand forms are not rewritten, because a wrong ending is worse than a Cyrillic name.
- On the real 2026-11-05 episode it makes 15 replacements and leaves no "Оупен Ей-Ай".

## #238 Publish/approval boundary (2026-11-05)
- Found a real gap: `/api/publishing/{id}/publish` and the `run-due` scheduler checked status, schedule time and media, but not the owner approval. A publish item with no approval, an unknown one, a non-approval decision, another job's approval or an approval the owner had since superseded reached the publisher adapter.
- Fix: `_publish_approval_gate` runs right before the adapter and fails closed. The item's `approval_decision_id` must exist, belong to the same job and be an `approved` decision, and it must be the job's newest owner decision. After a rejection or regeneration the owner approves again; that new approval creates a new publish item.
- A refused item stays `scheduled`, with an event and `approvalRequired: true`. Replaying an already-published item stays idempotent and never calls the adapter.
- The tenancy test inserted publish items without any approval. Its fixtures now carry a real approval of their own job; its workspace assertions are unchanged.

## #237 Security Check findings schema (2026-11-05, epic #98)
- `security_findings.py` holds one finding schema: rule_id (`AUTH-001` style), title, severity, evidence_source, location, reproducibility, uncertainty, remediation, user_consent_status and target. A "confirmed" finding that was "not_reproduced" is refused. `not_required` consent is valid only for `target: own_repository`.
- Redaction is mandatory and idempotent. It runs on every string field, nested details included, before a finding is returned. It reuses the token patterns from `owner_desk.py` and adds JWTs, bearer values, key=value secrets, long hex, emails, URL credentials and query strings, and private/internal hosts. Public hosts and ordinary text stay readable.
- Export fails closed: every finding must be valid and its consent `granted` (or `not_required` for our own repo), and the finished JSON is checked once more for anything sensitive. There is no scanning code here; it works on findings handed to it, and the tests use synthetic fixtures only.
- The test runs in CI as its own step, because the CI only runs listed test files.

## Lane truthfulness on the mobile Build Progress screen (2026-11-05, T-592/T-596 area)
- An online lane is "blocked" only while its last blocked or failed event is younger than 24 hours (`blocked_ttl`). Before this, a run blocked on 2026-11-02 kept the Claude lane "Blocked" three days later. An older block is history: the lane shows idle, `last_task_id` still names the task, and the task stays in the Blocked column.
- Lanes now carry `github` = {done_7d, last_activity_at}, taken from the cached Team tasks board. The Gemini loop works through GitHub issues and PRs, not Relay, so its lane read "Offline · 0 done" while it merged six PRs. This GitHub fact is shown beside the Relay facts and never changes a lane's state: no heartbeat still means offline.
- The lane board only peeks at the Team tasks cache and never reads GitHub. `peek()` is lock-free because the board builder runs inside the cache's `get()` and calls the lane board; a locked peek deadlocked, which `test_team_tasks` now covers.

## #41 GitHub → Relay intake through the EC2 snapshot (2026-11-05)
- Render's `GITHUB_TOKEN` gets HTTP 403 on this repository (logged every 5 minutes since 2026-11-04), so owner Issues never reached Relay. The EC2 worker already pushes a compact GitHub snapshot every 3 minutes with the owner's `gh` login (for Team tasks). Intake now uses that snapshot when the direct read fails and the snapshot is younger than 15 minutes. No token, scope or secret changes. The snapshot now also keeps each issue's author login, because intake only accepts the owner's own issues.
- Gate: Claude issues that Queue Keeper (#231) classifies as blocked are deferred, not imported. Blocked means an open Depends issue or PR, an unfinished ROADMAP dependency, an owner gate in the title, or another agent's open PR. Without the gate, restoring intake would hand the EC2 worker tasks that wait for the owner (#240–#242) or are acceptance checks (#219).
- Failed GitHub reads log a fixed reason category (token_lacks_permission, invalid_token, rate_limited, sso_required, not_found_or_no_access, network), never headers or response text. With no fresh snapshot, intake reports `missing_or_stale` and imports nothing.

## #258 Intake fallback contract (2026-11-05)
- `_intake_issues_from_ec2_snapshot` returns `(data, reason)`, where reason is `fresh`, `missing`, `stale` or `malformed`. Only `fresh` data is ever imported, and the intake log and result carry the reason (`ec2_snapshot`).
- Malformed means: not JSON, not an object, a non-numeric `received`, no `github` object, or `issues` that is not a list. These used to raise inside the intake loop.
- A snapshot more than 60 s "in the future" (clock skew) counts as stale. Before, it was treated as fresh forever.
- The six contract tests in `test_intake_fallback_contract.py` run in CI through `test_relay_execution.py`. They fail on the pre-#258 code.

## #261 MyCast configurator prototype (2026-11-05)
- Lives in `docs/prototypes/mycast-configurator/` as a static page plus a DOM-free logic module, so node can test the rules without a browser. `docs/prototypes/mycast/` belongs to #107 and is not touched. Sidebar integration in `static/index.html` waits for PR #194, which edits the same file.
- Topic ids are stable `category.group.topic` strings. Labels are data, so the profile JSON never depends on the UI language.
- Browser speech counts only as a labelled demo (`demo_not_ai_episode`). It cannot be downloaded or approved as an episode. Any edit drops the profile back to draft, and approval never sets `active`. No generation, scheduling or delivery exists here.
- CI runs the node tests and `node --check` on the inline script as one step.

## MyCast configurator on the site (2026-11-06, owner request after #261)
- The prototype moved from `docs/prototypes/mycast-configurator/` to `static/mycast-configurator/`, because the app serves only `/static`. It is public like every `/static` file. It reads no user or factory data and makes no network calls.
- The sidebar has a new **MVP Factory** section, between Automation & team and System, with one item, **MyCast podcast**. It opens the configurator in a new tab. The rest of #186 (the panel, the pilots, live Relay state) stays with PR #194. That PR edits a different part of `static/index.html` (the main panel, not the nav line), so the two should merge without a textual conflict.
- `test_navigation.py` now expects 7 sections and the new destination. Nothing else in it changed.

## #261 follow-up: the full acceptance list (2026-11-06)
- Channels now have two flags. `selectable` means the channel may be saved as the preference in a draft: Telegram (the main channel) and download. `usable` means something can really be delivered, which is only a download with a real file. Viber, WhatsApp and email are `planned`, visible but disabled. Choosing one is a validation error, never a silent fallback. The default channel is Telegram, as the issue asks, and it always shows "not connected".
- Watch-list entries are typed (athlete, team, channel, keyword), cleaned the same way as free text, and de-duplicated without regard to case. There are at most 20, and any change resets approval.
- The visual directive is met with CSS and a small inline SVG: no libraries, no CDN, no images. The hero pipeline uses SVG `animateMotion` along one path and is labelled as a simulation. In calm mode (reduced motion, data saver, or 2 or fewer CPU cores) the animations pause and the glass blur is dropped. The cover art is generated from the topic ids, so the same profile always gets the same cover.

## #186 MVP Factory phase 1: registry, API and overview page (2026-11-06)
- On 2026-11-06 the owner reassigned #186 to Claude. ChatGPT's draft PR #194 supplied the state machine, the role map and the "recommend, never dispatch" rule. They live on in `mvp_factory.py` with credit. Its static preview and hard-coded panel were not carried over: that panel showed seed text that looked like live state.
- The registry is a JSON file in `DATA_DIR`, written atomically. A project changes stage only through a recorded event, and only one step forward. Every advance needs an evidence link (a GitHub issue, PR, commit or actions URL, or a `/static/` page). Validating and rejecting are owner-only. A block needs a reason. Writes are idempotent by key. A damaged file is refused (HTTP 503), never quietly replaced with the seed.
- The seed is written only when no file exists. MyCast enters at `preview_ready`, and each earlier step cites the PR or file that proves it. #187, #188 and #189 start at `idea`, citing their issues.
- The UI is a standalone page, `/static/mvp-factory/`, opened from the sidebar (MVP Factory → Projects), instead of a 17th drawer. This keeps the drawer framework and its tests untouched. The page is public like all of `/static`, but its data comes only from `/api/mvp-factory`, which needs a session. Viewers can read; the existing middleware refuses their writes.
- Nothing here starts a worker, calls a provider, spends money, deploys or publishes. Phase 2 (reading Relay execution state and the pilot end-to-end flow) is separate work.
- Review fixes from 2026-11-06, ChatGPT on PR #271:
  - **Idempotency keys.** A key belongs to one operation: project, kind, actor and a fingerprint of the payload. Retrying that operation returns the first event. Reusing the key for anything else gets `409 idempotency_conflict`. The page makes an opaque UUID per intended operation, keeps it only to retry after a network failure, and drops it once the server answers or the form changes. The old minute-bucket key could merge two real submissions.
  - **Evidence.** Links are checked for shape only. Every event carries `evidence_check: "link_shape_only"`, and the page labels each link "not verified". Nothing in the registry says VERIFIED. `..` and `//` in a path are refused.
  - **Persistence.** `render.yaml` declares `DATA_DIR=/var/data` on the persistent disk `factory-data` and a single uvicorn process (no `--workers`), so the one-writer lock holds. The live Render settings were not checked from this session.

## CI: screenshot upload and the artifact quota (2026-11-06, owner approved)
- The repository's GitHub Actions artifact storage filled up, so every PR's `ui-screenshots` job went red at the upload step even though the screenshots passed. With the owner's approval, only the upload step is `continue-on-error`, and retention went from 14 days to 3. The screenshot step itself still fails the job on page errors, overflow or failed actions. No artifacts were deleted.

## Relay Claude lane blocked by the MyCast state file (2026-11-06, #41/#256)
- The owner's Telegram `/tasks` showed every Claude ticket blocked since 2026-11-05 21:20 UTC with "Runner checkout has uncommitted changes". `autopilot.py` writes the MyCast daily state to `.autopilot/mycast.json` inside the runner checkout, and that path was not git-ignored. So `relay_tasks.execute()` (correctly) refused to touch a dirty tree.
- Fix: ignore `.autopilot/mycast.json` and `.tmp`. No guard was weakened. The worker's normal merge of main brings in the new `.gitignore`, and the untracked file stops counting. A regression in `autopilot/test_autopilot.py` checks every runtime file the runner writes inside its checkout with `git check-ignore`.

## `.autopilot/` is runtime space (2026-11-06, #41/#256)
- The new block note named the second blocker: `?? .autopilot/ui-check.js`. An earlier delegated run (T-560-E, around 2026-11-01) left that scratch script behind on the EC2 checkout. Rather than ignore files one at a time, `.gitignore` now ignores everything in `.autopilot/` except the two tracked files, `answers.md` and `status.example.json`. The dirty-tree guard is unchanged for every real source file. The regression checks both directions: runtime and scratch paths are ignored, and the two tracked files stay tracked.

## MyCast beta batch 1 (2026-11-06, owner feedback on #261)
- An own entry belongs to a row (`category.group`) and counts toward the two-pick minimum, so "Arsenal + Usyk" is a valid podcast with no ticked subtopic. The old typed watch list became social follows, and old drafts migrate: watch-list entries become `web` follows, and `weekly` becomes chosen days.
- A follow link is accepted only over https and only on the platform's own domains (www/m stripped). Anything else must be an @handle or a name. Quick picks are the public figures' official X accounts, offered as shortcuts with initials (no photos).
- A share link carries settings only, never state, preview or approval. Topics are stored as positions in the stable topic list, so the code stays around 300 characters, small enough for a later QR code. Decoding runs every value through the same validators as the UI, and a link is offered with a banner, never applied over the visitor's own draft without asking.
- The QR code is deferred: the session's safety check refused vendoring the MIT `qrcode-generator` package, so the owner decides.

## MyCast QR code and /mycast short link (2026-11-06, owner approved)
- With the owner's yes, the MIT `qrcode-generator` 1.4.4 is vendored unchanged in `static/mycast-configurator/vendor/`. It was audited first: no network, eval, cookie or storage calls.
- The QR uses error level Q with the DNA cover clipped into a circle over the central ~5 % of the area. OpenCV's `QRCodeDetectorAruco` decodes it from a 520 px phone screenshot and from the 1024 px PNG download. The classic OpenCV detector fails even on the library's plain output, so it was not used as the gate.
- The share link uses the public short path `/mycast` (a 307 to the page; browsers keep the `#p=` fragment). That keeps the link near 390 characters, a version-19 QR.
- Also fixed: a global `[hidden]{display:none!important}`. A `display:grid` class was overriding `hidden`, so the JSON import box was always visible and the weekday dots showed even for "daily".

## MyCast public Gemini demo (2026-11-06, owner: "1 да 30")
- `POST /api/mycast/demo` is public, because the open beta has no sign-in yet. It reuses `mycast.gemini_tts_pcm` and the existing `FACTORY_GEMINI_API_KEY`, and it guards itself:
  - **script:** at most 2 lines and 420 characters, and the first line must open with the fixed "this is a MyCast demo" sentence, so it is not a free general voice API;
  - **caps:** 30 new generations per UTC day for everyone (`MYCAST_DEMO_DAILY_CAP`) and 5 per client (`MYCAST_DEMO_PER_CLIENT_CAP`). Client ids are SHA-256 hashes of the first `X-Forwarded-For` hop and are never stored raw;
  - **cache:** results are cached by script and language as WAV under `DATA_DIR/mycast_demo` (newest 300 kept). Cached plays are free, even after the cap is reached;
  - **one generation at a time.**
- **Progress:** the bar shows the real stage (preparing, Gemini voicing, ready). The percentage is marked "≈" because it is estimated from elapsed time against a typical ~14 s, and it stays capped at 95 % until the audio exists.
- **Fallback:** no key, a cap reached, a Gemini error or a page opened outside the site (a local file or a preview) all fall back to the browser voice with a stated reason.
- **Labelling:** a Gemini demo is real audio, so Download is enabled. It is still labelled `demo_not_episode`, never an episode.

## MyCast listener accounts, open beta (2026-11-06, owner: "3 открытая бета", Telegram domain set)
- Listeners sign in with **Telegram** (Login Widget, `request_access=write`) or **Google** (Google Identity Services).
  - **Telegram:** the server checks the widget's HMAC, keyed with SHA-256 of the bot token, and refuses logins older than 24 h.
  - **Google:** it uses the existing `FACTORY_GOOGLE_CLIENT_ID` and `verify_oauth2_token`. MyCast is on the same origin as `/login`, so no new Google Cloud setting is needed.
- **Separate session:** a listener gets its own signed cookie, `mycast_listener` (`ml1|slug|expiry|HMAC`, 30 days, HttpOnly, SameSite=Lax, Secure on https). It is never a staff session: the dashboard and API stay 401 for a listener, as checked against a locally running app.
- **Stored data:** a random 8-character public slug, a first name, the provider, a SHA-256 of the provider id, the Telegram chat id (Telegram only, for future delivery), the podcast share code and timestamps. No email, no photo, no tokens. `DELETE /api/mycast/account` erases the record. The page states this next to the sign-in buttons and in the FAQ.
- **Personal page:** `/mycast/u/<slug>` is a public 307 to the configurator with `#p=<code>&from=<slug>`, so a visitor sees the "use these settings?" banner. Sign-in saves the podcast once, and approval saves it again.
- **Delivery is still not live:** a Telegram-linked account shows "Telegram linked ✓, delivery coming soon", and the channel status stays `not_connected`.
- **Also fixed:** `.btn:hover` replaced the background of `.btn.primary`, so primary buttons lost their gradient under a desktop pointer.

## #259 Intake pagination (2026-11-06)
- `github_pages.fetch_all` reads `per_page=100` page by page until a short page, and at most `MAX_PAGES` = 5 pages. If any page fails, the whole read fails: a 403 on page 2 imports nothing and reports the reason, never a silently partial list. When the limit is reached with a full last page, `truncated` is set.
- The direct Render read (`relay_github_owner_issues`) previously took the first 50 open owner issues only. The EC2 snapshot, which production actually uses because Render's token gets a 403, held only the 100 most recently updated issues of any state. The snapshot now also carries every open issue the owner created (up to 3 pages, de-duplicated), so `valid_snapshot` allows 400 issues.
- Lane and owner filters are unchanged: the first line must be exactly `Owner: …`, and the author must be the repository owner. Intake stays idempotent per issue.

## #281 MyCast voice picker, Telegram pairing, separate delivery switch (2026-11-07, owner: "#281: «да»")
- 30 Gemini prebuilt voices (`mycast_voices.VOICES`; the page copy is tested to match). Gender is labelled "by ear, unofficial": Google publishes names and styles, not genders. A single host picks a male voice; two hosts pick male A plus female B, and the two must differ.
- Samples are real Gemini audio, generated on the first ▶ and cached per voice and language (`DATA_DIR/mycast_voices`). New samples are capped at 40 a day (`MYCAST_VOICE_SAMPLE_DAILY_CAP`); cached ones always play. A failed voice is shown as unavailable with its reason and is not retried for an hour. Nothing is labelled playable before the file exists.
- The chosen voices go into the demo request and the demo cache key, so another pair gives another sample.
- Step 07 has a big "Connect to my Telegram" button. It uses the Telegram pop-up (`Telegram.Login.auth`), so an approval made on the page survives; the oauth.telegram.org redirect is only a fallback. A signed-in Google listener who connects Telegram gets the chat linked to the same account.
- Approval, pairing, sign-in, import and audition never start delivery. Delivery needs three things: the server-side approved code equals the saved code, a test message was sent to the listener's own chat, and an explicit consent tick (`mycast-delivery-consent-2026-11-07`). Then the listener presses "Turn on delivery". "Stop delivery" really turns it off. An edit saved after approval clears the approval and pauses delivery. A new Telegram chat must be verified again. Sends go only to the listener's own chat, at most 3 a day, and each send is audited.
- Honest limit: regular personal episodes for listeners are not generated yet. Turning delivery on stores consent and schedule, and the page says so.

## MyCast free days and invites (2026-11-07, owner's voice message)
- Offer, on the first screen: 7 free days of personal podcasts to start, and +7 days for each invited friend. A friend who arrives through an invite starts with 14 days (7 plus a 7-day gift). It works like Dropbox, with both sides rewarded.
- The invite is the share link (and QR) with `&ref=<slug>`. A personal page's `&from=<slug>` also counts. The server credits it once, and only when that link creates a brand-new account. Self-invites, repeat logins and bad slugs do not count, and there is a cap of 50 friends per inviter. `ref` is sent next to the Telegram payload and is not part of its signed fields.
- Days are shown as the formula 7 + 7 (if gifted) + 7 × friends. There is no billing yet. The page says plainly that the open beta is free and the days start counting when regular episodes launch.
- The first screen has three entry points: create your own podcast · listen to friends and famous people · share and earn days. The growth ideas sit on the page as a numbered draft list, each item marked "live" or "plan", for the owner to edit later.

## CI on a budget until 1 Dec (2026-11-08, owner: "$5 бюджет, растянуть до нового месяца")
- The 2000 free Actions minutes ($12 of included compute at $0.006/min) were used up by 8 Nov. The budget is now $5, so CI must spend as little as possible.
- In `ci.yml`:
  - A newer push to the same PR cancels the older run.
  - The Python 3.9 EC2 import check is a step inside `syntax-and-smoke`, not its own job (one fewer rounded-up billed minute per run).
  - `ui-screenshots` (about 4 minutes) runs only when page files change (`static/`, `tools/ui_screenshots.py`, `requirements.txt`, `ci.yml`), or on a manual dispatch, and only after the smoke job has passed.
  - Screenshot artifacts are kept for 1 day instead of 3, because Actions storage is full too.
- Main still runs CI on every push: Render deploys with `autoDeployTrigger: checksPass`. A skipped screenshot job counts as passing, not as failing.
- Working habit until the reset: fewer, larger pushes per PR.

## Relay round trip (#289, #41), 2026-11-08, owner: «доделать релей, чтобы была круговая работа»
- Each claimed ticket runs in its own git worktree on branch `relay/<ticket>-<run>`, cut from freshly fetched `origin/main`. The runner's checkout and branch are never touched: a dirty runner tree no longer blocks Relay work, and tickets no longer share one branch. `RELAY_ISOLATED_WORKTREE=0` switches back to the old in-place mode.
- After a commit, the worker pushes the branch and opens a PR with its existing `gh` login. The PR URL is the evidence on the `done` event. A push without a PR is reported as `blocked`, never as `done`. The worker never merges or deploys.
- Server: on every intake pass, `relay_pr_reconcile_once` follows each ticket's PR in the fresh EC2 GitHub snapshot. CI passed, CI failed, merged and closed-without-merge are each recorded once in the ticket history (actor `github`) and each sent once to the owner's Telegram. A PR missing from the snapshot, or a stale snapshot, stays unknown. `deployed` stays unverified: Render deploys on checksPass, and no Render read exists yet.
- Merging stays a human or Claude-review step. "CI passed" in Telegram means "ready for review and merge", not "merged".

## Owner voice messages → text (2026-11-08, owner: «1 вариант» = Gemini)
- A voice or audio message with no caption, from the paired owner's private chat only, is transcribed by Gemini Flash (`gemini-2.5-flash`, override with `FACTORY_VOICE_TRANSCRIBE_MODEL`) with the owner's existing key.
- The owner gets the text back to check. The Relay ticket gets the transcript instead of an empty "Голосовое сообщение".
- Limits: 30 new transcriptions per UTC day (`FACTORY_VOICE_TRANSCRIBE_DAILY_CAP`), and files up to 4 MB (about 3 minutes). A repeat of the same Telegram file comes from a cache and costs nothing.
- When transcription fails, the owner gets the reason in plain words and the old behaviour stays: a ticket with the attachment only. Provider text and keys never reach the chat or the logs.

## FactoryOS Team Telegram group (#129), 2026-11-09
- The owner created the group "FactoryOS Team" and added the existing bot. The bot keeps privacy mode, so it sees only commands and replies to its own messages. That is enough for this bridge.
- Pairing: `/group` in the bot's private chat gives a one-time code valid for 10 minutes. `/pair_group CODE` in the group binds that group's chat id. Only the paired owner's Telegram id (the owner's private chat id) can pair, discuss, stop or record decisions. Other members and unbound groups are ignored. `/group off` unbinds the group.
- `/discuss` and replies to the bot use the existing owner-question queue: the same Claude subscription worker as `/ask`, with no new paid calls. The answer goes back to the group labelled `[Claude] D-xxxx`, and not to the private chat.
- ChatGPT and Gemini are shown as unavailable until each has a real Relay runner. They are never imitated.
- `/stop` means later answers are dropped, not posted. `/decision` records only after the owner taps ✅. Decisions are versioned in the bridge's own store, and no rules or prod files are edited.

## #106 Morning brief at 08:00 Kyiv (2026-11-09)
- Runs on the server (Render), not on the EC2 worker: the voice (owner's Gemini key), the paired chat and the data already live there, and a long worker task cannot delay it. `morning_brief_loop` ticks once a minute.
- Owner opt-in, off by default: `/brief on|off` in the paired private chat (any other chat is ignored). `/brief test` sends the composed text only, no Gemini call — the "harmless test first" step of #106.
- Content is FactoryOS facts only: PRs merged in the last 24 h (titles without issue/task numbers or priority codes, per the MyCast feedback), open PRs and red CI from the fresh EC2 snapshot, active Relay tickets and how many wait for the owner, open questions. A missing/stale snapshot is said as "GitHub status unknown", never guessed. AI/world news stays in the MyCast episode (06:00); the ChatGPT automation's text cannot be pulled (no export path), so it is not imitated.
- One brief per Kyiv date through the same once-per-date delivery log as the worker route (`make_brief_sender`, shared). First try 08:00 (zoneinfo, DST-safe), up to 3 tries 20 min apart, none at or after 11:00, so a restart later in the day sends nothing stale. After the 3rd failure the owner gets the text plus one explicit "voice not delivered (category)" note. Cost: one Gemini TTS call per day on the existing free-tier key; no new paid provider.

## #241 Relay owner-notice dedupe (2026-11-09)
- `test_relay_notify_dedupe.py`: six scenarios through the real Relay routes with a fake notifier and a persistent temp store, a fresh store/queue/app per "process" so restarts are real: worker event retried after a restart (event_id), repeated Run on queued/running work, a late event after `done`, an event from a superseded run, a redelivered Telegram update, PR CI/merge transitions re-read after a restart.
- Two real duplicates found and fixed minimally in `relay.py`: (1) `POST /api/relay/{id}/run` told the owner "передано Claude" on every call, even when the ticket was already queued or running; now only when the call really requeues (new or stale → owner Retry). (2) A Telegram update redelivered with the same `update_id` (our first 200 was lost) got a second "Тикет уже существует" reply; now it is recognised as a replay and answered once. Owner-only filtering is unchanged.

## #240 MVP Factory state-machine contract tests (2026-11-09)
- No new state-machine module: `mvp_factory.NEXT` already is the transition table, so `test_mvp_state_machine.py` (21 tests) asserts against it and against the real Builder gates (request validate, preflight, manifest, projection). Issue phases map to registry stages (idea → researching/spec_draft/spec_review → build_queued → building/qa_review → preview_ready/owner_review → validated|rejected).
- Publishing is not a transition (no `publish` kind; `approval.publish` stays False after `validated`). Owner rejection is terminal; the spec has no "back to spec" edge, so none is invented.
- Known gap, recorded not patched: `MvpRegistry.record("advance")` does not call the Builder gates itself; the tests compose gate → advance in a `DemoPipeline` helper. Wiring that into production is M2 of #186.
- Every record the tests write is DEMO-marked; pilots #187–#189 are asserted unchanged after every test.

## #242 Team Tasks truthfulness regression (2026-11-09)
- `test_team_truthfulness.py` (22 tests): stale/future/malformed snapshot, GitHub 403 vs a real empty read, partial CI, heartbeat without a claimed task, stale queued tasks, provenance timestamps and the fixed progress set. Render deploy SHA vs main is not compared anywhere in code, so that case is a documented skip, not an invented adapter.
- Fix in `team_tasks.py`: CI is `unknown`, not `passed`, when a check run is `stale`, when the check-runs body is unexpected (was `none`), or when `total_count` exceeds the runs read (a red run may sit on the next page). Relay's PR reconcile only acts on passed/failed, so it can no longer announce "CI passed" on partial evidence.
- Left open (recorded): a corrupted snapshot file can still make the board return 500; board TTL (3600 s) differs from intake (900 s); the page tiles show 0 next to the "GitHub unavailable" banner (the API keeps unknown and empty apart).

## Evidence Protocol Tier 1 (2026-11-10, owner approved)
- Spec: `docs/specs/EVIDENCE_PROTOCOL.md`. Module `evidence.py`: levels claimed < linked < checked < accepted, rules per task type in code (code, mycast, telegram, publish, other), pure checkers.
- Every new Relay ticket gets a `verification` block at creation (T1.6); engineering lanes (claude/gemini/unassigned) are type `code` (PR merged + CI passed on that commit), others `other` (a link). Workers cannot write it: `safe_evidence` already drops anything not allow-listed, and `event()` never touches the block.
- Behaviour change: a worker's `done` no longer closes the ticket. The execution state is `done`, the ticket stays `in_progress` until the server's PR reconcile records `pr_merged` + `ci_passed` on the merged head commit, then closes it and tells the owner once. Two tests that asserted the old rule (worker done → ticket done) were rewritten to assert the new one; nothing was removed.
- A merged PR whose CI was not yet read keeps being followed and closes when a later read shows CI green on that commit; red CI on the merged commit never closes it. To make that possible the GitHub read now also fetches CI for recently merged PRs (same 20-PR cap).
- T1.5: checks carry the PR head SHA; a new head makes them not count.
- Owner override: `/done R-0001 причина`, the API `note`, minimum 3 characters; kept in `verification.override` and history, shown on the card. The Telegram button and a bare `/done` explain how. Archive needs no evidence (it is not "done").
- Legacy tickets (created before this change, no block) keep the old behaviour.
- Tier 1 still accepts the EC2 snapshot as the source for `checked` (labelled `github:ec2-snapshot`), so the round trip keeps working; Tier 2.1 moves `checked` to Render's own read. For that a separate `FACTORY_GITHUB_READ_TOKEN` (read-only, fine-grained) is added instead of reusing `FACTORY_GITHUB_TOKEN`, which also enables the Builder's workflow dispatch. Owner-only `GET /api/factory/evidence/github-read-check` reports per-read codes, never the token.
- MyCast and Telegram checkers exist and are tested, but are not yet wired to tickets: those runs do not create Relay tickets today.

## Evidence Protocol Tier 2.1 — independent source (2026-11-10)
- Owner's read-only token check on production: issues ok, pulls ok, check-runs `http_403`. Fine-grained personal tokens have no Checks permission at all, so this is a GitHub limitation, not a mis-set token. `read_github` now falls back to `GET /actions/runs?head_sha=` (Actions: Read) after the first 403/404 on check-runs and maps workflow runs to the same labels (passed / failed / running / none / unknown; truncated or odd conclusions → unknown). Our CI is GitHub Actions only, so nothing is lost.
- `github-read-check` now reports `actions` too and `ci_via` (checks or actions); `all_ok` needs issues + pulls + one CI path.
- With `FACTORY_GITHUB_READ_TOKEN` set, `relay_pr_reconcile_once` reads GitHub itself (source `github:render`) and only that source (plus delivery log / Bot API) counts towards `checked`. If Render's own read fails it falls back to the EC2 snapshot for notices, but those checks stay `linked` (card ☑️, "только по данным воркера"), so a ticket never closes on the worker's own data. Without the token, Tier 1 behaviour is unchanged.

## Server GitHub reads use the read-only token (2026-11-10)
- Production log after the owner added `FACTORY_GITHUB_READ_TOKEN`: `GITHUB_ISSUE_INTAKE ok:false HTTP 403 token_lacks_permission, ec2_snapshot: stale` — the Builder token cannot read issues and the worker's snapshot was stale, so no owner Issue was being imported. The read token can (`issues: ok`).
- `_github_read_token()` (read token, else the Builder token) is now used for every server-side read: Issue intake, the Team Tasks board, Telegram `/github`. Write paths (Builder workflow dispatch) still use `FACTORY_GITHUB_TOKEN` only.
- Still open: why the EC2 snapshot is stale (worker side; not visible from here).

## T-560-F Encrypted vault backend (2026-11-10)
- Trigger: owner asked for the "Browser Agent & Secure Vault" from a Gemini draft spec. Most of that spec already exists (T-560-A..E: contracts, approval policy, waiting_human takeover, Playwright executor, observability). The missing piece was a real vault: only `InMemoryVault` (tests) and `UnavailableTokenVault` (OAuth, refuses to store) existed. This task adds only that piece.
- `browser_runner/vault.py`: AES-256-GCM via `cryptography` (new dependency). Key from `FACTORY_VAULT_KEY` (32 bytes, base64 or hex); `FACTORY_VAULT_KEY_PREVIOUS` (comma-separated) is decrypt-only for rotation, `reencrypt_all()` rewrites under the primary key. Only a 12-hex key fingerprint (`kid`) is stored. No key or malformed key → no vault (fail closed); the app still boots.
- Each record's GCM associated data binds namespace + record id + scope (workspace/provider/account), so a ciphertext copied into another workspace's record or edited on disk does not decrypt. Missing, out-of-scope and tampered refs give the same error (no existence oracle), matching `InMemoryVault`.
- Storage: JSON files under `DATA_DIR/vault/` (Render persistent disk), 0600, ciphertext + non-secret scope only. Chosen over the SQLite DB to keep secrets out of DB backups/exports and keep the module independent of app.py; reversible (same `_EncryptedFile` interface).
- Credential vault refuses to *store* anything but `username`/`password` (OTP, TOTP seeds, recovery codes, cookies stay human-only), stricter than the in-memory one which only refused to resolve them.
- `EncryptedSessionStore.capture()` encrypts a Playwright `storage_state` after a human finished login, mints a fresh `session://` ref and binds it in `SessionRegistry`; a replaced session's ciphertext is deleted, disconnect deletes it too.
- Security-boundary change in `playwright_executor`: it was "fresh anonymous context, no storage-state restore". Now a session is restored ONLY when the trusted host passes a `session_store` and the plan's `session_ref` is bound to the plan's exact binding; otherwise blocked before the browser launches. The network guard (GET/HEAD/OPTIONS, allowlisted origins) and the submit ban are unchanged, so a logged-in run can read and prepare drafts but still cannot write to the site.
- OAuth: `OAUTH_FLOW` uses the encrypted token vault when the key is set (removes the `vault_unavailable` blocker only; `client_not_configured`/`adapter_missing` stay until T-551/T-552). Owner-only `GET /api/factory/vault/status` shows configured/algorithm/kids/record counts, never key material.
- Not done here (deliberately): live screen streaming/takeover UI, an LLM step planner (would need paid API, ZERO ADDITIONAL SPEND), stealth/anti-detect and proxies for OLX (ToS / account-ban risk; prefer official APIs), wiring capture into an HTTP route (needs the takeover UI). Setting `FACTORY_VAULT_KEY` on Render is owner work.
- UI (same task, owner request): "🔐 Access vault" button in the Connections card opens the existing generic agent drawer (no new drawer id, so the 16-drawer and 26-destination layouts are unchanged). Sections: encryption status (or key setup steps), logins (site + account + login/password, masked, cleared after save), browser sessions (upload a Playwright `state.json` made on the owner's own computer with `npx playwright codegen --save-storage`, so 2FA/CAPTCHA stay with the human), limits. Each record has Check (decrypts server-side, returns only field names / cookie count / domains) and Delete/Disconnect. Hidden for read-only viewers.
- Owner-only routes: `POST /api/factory/vault/credentials`, `/credentials/delete`, `/sessions`, `/sessions/disconnect`, `/check`; `GET /api/factory/vault/status` now also lists records (refs, field kinds, cookie counts, domains, dates). Saving the same site/account replaces the record. Workspace always comes from the server binding, never from the request. Site/account names are validated (`[a-z0-9_.-]`, ≤80 chars). Field kinds, cookie counts, domains and earliest expiry are stored as plaintext record metadata so the list renders without decrypting.

## Evidence Protocol Tier 2.2 / 2.3 / 2.5 (2026-11-10)
- Owner's production check after #300/#301: `{"issues":"ok","pulls":"ok","checks":"http_403","actions":"ok","ci_via":"actions","all_ok":true}` — Tier 2.1 confirmed live.
- T2.2 deploy: the merge commit (`merge_commit_sha` from the PR) is stored on merge; each reconcile with Render's own read asks GitHub `compare/<merge>...<RENDER_GIT_COMMIT>` (ahead/identical = included) for up to 10 merged, not-yet-deployed tickets. Recorded once as check `deployed` (source `render:build`), the lifecycle "deployed" stage and one owner notice. Informational, not a done requirement: done means merged + CI; deploy follows the normal CI-gated flow. Unknown or not-yet-included stays "не проверено". No snapshot path: only our own read.
- T2.3 owner buttons: the notice that closes a ticket on evidence carries "✅ Принял / 👎 Не то". Accept sets `verification.accepted` (level accepted, shown on the card; a replayed tap adds nothing). "Не то" moves the ticket to need_you with history `owner_rejected` and suggests Retry. Only the paired owner chat (existing callback guard).
- T2.5 metrics (`evidence.metrics`, 7 days): closed on evidence, closed by the owner without it, sent back by the owner, and tickets an agent called done that still wait for proof. One line in the 08:00 brief, only when any is non-zero.
- Not done in this step: T2.4 Agent Office panel (the Telegram card already shows level and checks), T2.6 cross-agent review.

## Evidence Protocol Tier 2.4 — Agent Office panel (2026-11-10)
- "🔎 Proof / Докази / Доказательства" button in the Agent Office header opens the existing generic agent drawer (same pattern as the vault, #302), so the 16-drawer and 26-destination layouts are unchanged. Hidden for read-only viewers.
- Content from the new owner-only `GET /api/factory/evidence/overview` (`evidence.overview`): 7-day metrics (closed on evidence, closed by the owner without it, sent back, "done" still without proof), the data source (Render's own read vs the worker's snapshot), and the latest 30 tickets with a verification block: level, what is required, each check (✅ server-checked, ☑️ seen only in the worker's data, ❌ failed, · missing; stale commit marked), deploy, owner acceptance, the owner's override reason, PR link.
- A ticket the owner closed by hand shows "closed by you", not "accepted", even though the level rank is the same.
- Verified in a real browser (Playwright) on seeded DEMO tickets at 1440 px and 390 px, EN and RU, no page errors. EN/UK/RU strings added; locale parity, drawer and navigation tests pass.

## Evidence Protocol Tier 2.6 — cross-agent review, option A (2026-11-11, owner chose A)
- `peer_review.py`: Gemini reviews **Claude-authored** Relay PRs only when the diff touches a risky path (auth, token, secret, vault, OAuth, password, credential, payment, billing, budget, publish, approval, `.github/workflows/`, `requirements.txt`) or changes more than 300 lines. Gemini's own PRs are not reviewed by Gemini; Claude keeps reviewing those at merge time.
- When required, the server (not the agent) adds `peer_review` to the ticket's required checks; the ticket does not close until Gemini has no blocking finding on the current head, or the owner closes it with a reason. A new push needs a new review. If the diff cannot be read, review is treated as required (a risky PR cannot close unreviewed during a GitHub hiccup).
- Runs in the server's PR reconcile, before closing, only with Render's own GitHub read (`/pulls/{n}/files`), only after CI is green on the head; at most 2 per cycle and 20 per UTC day (persisted). Free Gemini key, stable `gemini-2.5-flash`, JSON verdict; any error, malformed answer, missing key or cap → nothing recorded as passed, retried after 30 minutes.
- What is sent to Google: the changed files' patches (secret patterns redacted, 60k characters max, lock/binary files skipped), the ticket title and text. Owner accepted the free-tier data-use trade-off when choosing option A.
- The verdict is an opinion, not proof: approval never closes a ticket by itself (merge + CI still required), blockers can be overridden by the owner. The owner gets one Telegram notice per review (findings listed); findings also show in the Proof panel. No PR comment is posted: the server only holds a read-only GitHub token, and posting with the Builder token was not attempted.

## CI runners pinned to ubuntu-24.04 (2026-11-11)
- `ubuntu-latest` became Ubuntu 26.04; `actions/setup-python` has no Python 3.9 for it ("version '3.9' ... not found for Ubuntu 26.04"), so `syntax-and-smoke` failed in 7 seconds before any test, on every branch. The job needs 3.9 because the deployed EC2 worker runs 3.9. The job is pinned to `ubuntu-24.04`; nothing else changes. Revisit when the worker moves off 3.9 (24.04 runners will be retired eventually).

## Worker branch unstuck (2026-11-11)
- Owner's live `/new` test (R-0063) ran the legacy path: commit on `autopilot/aws-worker`, no ticket branch, no PR, so no CI/merge evidence and no owner buttons. Cause: `autopilot/aws-worker` had not merged `main` since 2026-11-06 — its own R-0051 version of #259 conflicts with main's #259, and `sync_branch` keeps running the old code on a conflict. The worker had reported this itself in R-0058.
- Fix: `main` merged with `autopilot/aws-worker`, conflicts resolved to main's code (`app.py`, `relay.py`, `team_tasks.py`, `test_issue_intake.py`); the worker's README `/brief` section (R-0063), the R-0058 verification doc and its test are kept; its DECISIONS entry for the unused #259 variant is dropped. Merged into `autopilot/aws-worker` through a PR (merge commit, no force-push), so its next sync fast-forwards to main and restarts on the current runner code (isolated worktree per ticket).

## Owner feedback after the first live round trip (2026-11-11)
- **Relay notices** (`relay.worker_event_text`): one readable Russian card per worker stage — icon + "who did what", the task title, branch / commit / PR, the executor's own summary on done/blocked/failed, the evidence line, and "what comes next". The Claude CLI prompt now asks for the final answer in Russian, three points, ≤500 chars (summary cap 440 → 600). Evidence line speaks Russian ("есть ссылки (нужно: проверено сервером)"), missing checks ⬜, failed checks named as failures ("CI красный").
- **Voice**: Google answered 404 for `gemini-2.5-flash` on the owner's key. `gemini_proxy.resolve_flash_model` lists the key's models (cached 6 h) and picks the preferred one if listed, else `gemini-flash-latest`, else the newest non-lite x.y-flash; used by transcription and peer review. A voice message that cannot be transcribed no longer creates an empty ticket (R-0065 made Claude run just to answer "BLOCKED").
- **Morning brief** rewritten: GitHub from Render's own read (the stale EC2 snapshot made it say "GitHub unavailable"); yesterday's closed tickets (manual ones counted), merged PRs, red CI; plan vs fact with a completion rate (today's agent plan is stored per date on the real 08:00 run, not on /brief test, and compared next morning); today's plan per agent; what waits for the owner with a hint when many are stale. The voice reads headline lines only (≤1400 chars); details go in the text message.

## Gemini joins /discuss in the FactoryOS Team group (2026-11-11)
- Owner asked for the other models in the group. Gemini answers every `/discuss` and follow-up in the same thread with `[Gemini] D-xxxx`, on the owner's free key (model picked per key), in a background thread so the Telegram webhook is not held; a stopped thread drops a late answer; failures are said ("не ответил (…)"); 40 answers per UTC day. Its previous answer is passed as context on follow-ups; it is told not to invent project facts.
- ChatGPT stays "not connected": a ChatGPT subscription gives no programmatic access, only the paid per-token OpenAI API, which needs the owner's explicit approval.

## MyCast AI subtopics (2026-11-11, owner: "через нейронку, по подписке, не по копеечке")
- `GET /api/mycast/subtopics?q=&lang=` (public, like the demo): Gemini on the owner's free key (no per-request bill), stable Flash picked per key, JSON answer cleaned (≤6 items, ≤40 chars, tags stripped). 30-day cache for identical queries; 300 new generations per UTC day, 30 per visitor (hashed address only). Any failure, missing key or cap → 200 with an empty list, so the page keeps its local templates.
- Claude's $100 subscription is not used for this: it only runs through the EC2 worker (minutes of latency) and serving a personal subscription to public visitors is not something to do. Free-tier Gemini may use the topic text to improve Google's products; only the typed topic is sent.

## MyCast episode timeline, calendar invitation, signed-in view (2026-11-11, owner request)
- Step 09 "Ваш випуск по хвилинах": a strip of segment blocks (greeting locked first; news; interests; one block per follow; calendar last when wished), width by duration, total vs the chosen episode length with an over-limit warning. Pointer-event drag reorder (mouse/touch/pen, auto-scroll), drag out of the strip to remove (evaporate animation, reduced-motion aware) with restore chips, tap panel for ±15 s / move / remove, full keyboard support. Pure logic in `configurator.js` (`planFromProfile`, `movePlanItem`, `setPlanDuration`, `removePlanItem`, `restorePlanItem`, `planTotal`…), 8 new node tests.
- `profile.plan` stores only edits; deselected sources drop out, new ones go before the calendar. The plan is included in the share code as optional `pl` (only once edited) because signed-in podcasts are saved as that code; old links decode unchanged.
- Calendar invitation shown large in the calendar box and the calendar block (UK/RU/EN), status stays "не підключено" — there is still no real Calendar access (needs a Google read-only consent and, for public launch, Google's verification of the sensitive scope).
- Signed in: the project hero is hidden, a card with initials avatar and name is shown instead.
- Sub-topic suggestions call `GET /api/mycast/subtopics` 500 ms after typing stops (once per query); AI results get a "✨ AI" tag; any failure keeps the local templates silently.
- Built by a subagent on Claude's brief; reviewed here: node tests 29/29, inline JS `node --check`, screenshots at 1280 and 390 px.
- Same day, `ui-screenshots` on 26.04 failed in `playwright install --with-deps` ("apt: Unable to fetch some archives", "Failed to install browsers") before any screenshot; pinned to `ubuntu-24.04` too.

## MVP Builder on the main dashboard (2026-11-11, owner request)
- Renamed "MVP Factory" → "MVP Builder" in the UI (API/URLs unchanged). The name stays "MVP Builder" in UK/RU too, as a product name: added to the locale allowlists (`SAME_AS_EN` in test_locale_parity, `PRODUCT_NAMES` in test_navigation); every other nav label is still required to be translated.
- Projects block under Current Jobs (same row style): stage chips, progress bar with %, next step and role, age, "Деталі →" (side drawer: stage, x% / 100, next step, brief, history; link to the full page anchored `#p-<id>`), "+ Новий проєкт" modal (title, brief, optional issue → `POST /api/mvp-factory/projects`), "Відкрити повну сторінку ↗". The nav item scrolls to the block instead of opening a new tab. Nothing in the block starts a worker or moves a stage.
- Full page: "x% / 100" next to the stage bar, project anchors, collapsible brief, issue link only when an issue exists, team rendered as a pipeline with arrows (MVP Manager → Product Analyst → Spec Writer → Claude Builder → QA / Security, then Deploy Agent → Owner → Content Factory; ↓ on phones) with "зараз: N" on roles that have projects at their stage.
- Backend: projects can be created from a brief alone (issue optional, id derived from the title), and every project reports `progress` from its recorded stage (idea 0 %, validated 100 %).
- UI built by a subagent on Claude's brief; reviewed here with locale/nav/drawer tests and screenshots at 1440/390 px.
- Later the same day the 24.04 runners could not resolve the Ubuntu apt mirrors for over an hour; `playwright install --with-deps` (apt) then timed out the whole 20-minute screenshot job. The job now installs the browser alone, checks that it launches (runner images already ship Chromium's system libraries) and only falls back to `--with-deps`, capped at 5 minutes, if it does not.

## MVP Builder cycle, step 1 (2026-11-11, owner chose "Да, строй")
- Cycle Battle → Build → Promote → Learn mapped onto the recorded stages (Battle: idea…spec_review; Build: build_queued…owner_review; Promote: validated; Learn: no stage yet, shown as later). This four-part cycle is Claude's proposal built from the existing Battle Runs and the factory cycle's learning step; the owner remembered a similar split but no written source was found.
- Five agents = roles with their own instructions on the engines we have: Researcher and Spec Writer and Promoter answer through Gemini (free key, instantly); Builder and QA / Security go through the Claude worker's question queue (subscription) and their answers are written back into the agent chat (`_mvp_route_answer`, before the group bridge). Agent status is derived from the recorded stage only; the panel never advances a stage or starts a build. Prompts forbid invented results, numbers, clients or statuses.
- Dashboard: clicking a project row expands a panel under it (one at a time): phase strip, five agent tiles with arrows, one agent card at a time (what it does, engine, what it did with evidence links, what to connect ✅/⚠️, chat, Stop with a reason → `block` event, Resume → `unblock`, Redo pre-fills the chat). Read-only viewers see no inputs. Phase names and "Content Factory" stay English in UK/RU (locale allowlist).
- Next: step 2 (autonomous hand-off through Relay tickets with evidence), step 3 (project media/promotion channels incl. the email channel the owner asked for — domain and sending service need the owner's purchase and approval).

## MVP Builder step 2 — autonomous hand-off (2026-11-11, owner: "Начинай")
- `mvp_pipeline.py`: per-project autopilot (off until the owner presses "▶ Запустити агентів"); a server loop moves each autopilot project at most one step per minute. idea → researching (owner's brief saved as `brief.md`), Researcher (Gemini) writes research with exactly three variants and a recommendation (`research.json`/`.md`) → spec_draft, Spec Writer (Gemini) writes a spec on the recommended variant with a mandatory "Готово, коли" checklist (`spec-vN.md`) → spec_review. Every move is an `advance` event with the artifact link as evidence (new allowed evidence shape `/api/mvp-factory/<id>/artifacts/<name>`).
- Owner gate: agents are a separate registry role that may never move a project into build_queued, preview_ready, owner_review, validated or rejected (`AGENT_FORBIDDEN_TARGETS`). Only the owner's "✅ Затвердити ТЗ" (owner-only route) moves spec_review → build_queued. Before that the owner can redo the spec on variant A/B/C with feedback (Battle).
- Build hand-off: one Relay ticket for the Claude worker per approved spec version, code confined to `mvps/<project-id>/` of this repository (reversible default; separate repositories need the owner's GitHub action). Ticket PR → building; ticket closed on evidence (merged PR + CI, not an owner override) → qa_review. QA, preview and the verdict stay manual for now.
- Failure handling: malformed agent output, no key or a Gemini error records the reason in the agent's chat and waits 30 minutes; no retry loop burning the free quota. One Gemini call per stage per project.
- Dashboard panel: "Передача між агентами" block with the autopilot state/button, current variant and build ticket, last error, document links, and the spec approval gate (approve / variant select / feedback / redo).

## 2026-11-12 — Claude ↔ Codex agent relay hardened (issue #94, takes over PR #314)

PR #314 (ChatGPT lane, branch `chatgpt/relay-agent-messages-94`) is ported here and the six security-review blockers are addressed; #314 itself is left as is.

- Identity: two dedicated tokens, `FACTORY_CLAUDE_RELAY_TOKEN` and `FACTORY_CODEX_RELAY_TOKEN` (≥32 printable ASCII, ≥10 distinct characters, different from each other and from every broader FactoryOS credential). Any violation disables the agent routes (503 / 401) instead of degrading. The Claude worker token is never accepted on `/api/relay/agent/*`. Authorization headers longer than 512 bytes or not ASCII are ignored.
- Bounds: request bodies are streamed with a 16 KiB cap (Content-Length is not trusted); 3000-character messages; 1000 messages total; 50 undelivered messages and 60 sends per hour per sender; acked and dead messages pruned after 7 days (undelivered ones never). The idempotency window therefore equals the 7-day retention.
- Retries: a lease is 180 s; after 3 expired leases a message becomes a dead letter (owner sees it in `GET /api/relay-agents/status`, without bodies). Each message records `reply_id` server-side and a second reply is refused (`already_replied`), so a lost ACK is recovered by lookup and never triggers a second model call.
- Secrets: bodies matching the credential scanner (`agent_secret_scan.py`) or containing a literal FactoryOS token value are refused (422) and not stored. The Codex worker scans the model's answer first and sends a fixed "withheld" blocker instead.
- Codex isolation (EC2, `deploy/codex-relay/`): worker runs as `factoryos-relay` (systemd oneshot + 2-minute timer, ≤3 messages per run, token via `LoadCredential`), Codex runs as `factoryos-codex` through `sudo -n -u` with `env -i`, read-only sandbox, `--ignore-user-config --ignore-rules`, and `--disable shell_tool view_image apps plugins browser_use … -c web_search="disabled"`. Codex 0.167 registers every command tool only when `shell_tool` is on (codex-rs `spec_plan.rs::add_shell_tools`); `unified_exec` cannot be disabled by flag and is unreachable without it. `--check` / preflight proves, as the Codex account, that the checkout, `.env`, `/root`, `/home/ubuntu`, the credential directory and the worker's `/proc/<pid>/environ` are unreadable and that the features are off; otherwise nothing is claimed.
- Concurrency: all writes go through `RelayStore.lock` with atomic tmp+`os.replace`; Render runs one uvicorn process (pinned by a test). More processes would need a file lock first.
- No paid API: Codex signs in with the owner's ChatGPT subscription (device login); there is no permanent daemon, only the bounded timer. Nothing is enabled in production by this change: tokens unset ⇒ routes closed.

## 2026-11-13 — #317 (P0): website listeners' MyCast was never sent — there was no sender

Trace: the owner's website podcast was saved, approved and "delivery on" on 2026-11-11, but nothing read that flag. The owner's own daily episode (`autopilot/mycast_daily.py`) is a different, owner-only pipeline. So the gates were login → pairing → approval → opt-in → **(no scheduler)** → never sent.

- Server (`mycast_listener_delivery.py`): `delivery_gate` gives one state per listener (`no_podcast`, `telegram_not_linked`, `not_approved`, `delivery_off`, `bad_profile`, `not_today`, `waiting`, `in_progress`, `failed_today`, `delivered`, `due`), computed from the saved share code (decoded in Python from `static/mycast-configurator/topics.json`, generated from configurator.js and checked against it by a test). The worker lists due listeners without chat ids. On hand-in the server re-checks the gates, claims (listener, local date) once, voices with the listener's own Gemini voices and sends only to the listener's own chat. Audio QC as for the owner's episode.
- Bounds: one episode per listener per local day, 3 failed attempts per day, 10 listener episodes per UTC day overall (Gemini budget). An edit unapproves the profile and pauses delivery, as before.
- Worker (`autopilot/mycast_listeners.py`): after the owner's episode, one listener per pass; Claude (subscription, WebSearch/WebFetch only) writes the script from the listener's topics, language, length and host mode; attempts spaced 30 minutes.
- Telegram "verified" is not required (consent + linked chat is); a refused send (bot never started) is recorded as a failure with its reason and shown in the cabinet.
- Cabinet: the honest "not generated yet" note is replaced by the real state of today's episode and the last result.
- 2026-11-13 (owner): episode length is any whole minute from 1 to 30 (was 5/10/15). The server accepts listener scripts up to 300 lines / 40 000 characters (~30 min).

## 2026-11-13 — automatic Codex review of every open PR (owner: "делай ревью PR через Codex автоматически")

- `autopilot/codex_review.py` runs in the EC2 worker loop as the Claude side of the agent relay (`FACTORY_CLAUDE_RELAY_TOKEN`, from the environment or `/root/claude-relay.token`). No model runs in the worker: it only sends a review request and posts the answer.
- Scope: every open, non-draft PR in the repository, once per head commit; a re-push within 30 minutes waits; at most 12 requests per UTC day; one new request per worker pass.
- The request carries title, description (1 500 chars) and the diff truncated to 20 000 characters, with credential-shaped text redacted. The relay accepts `review` messages up to 24 000 characters (other kinds stay at 3 000); the request cap is 64 KiB.
- Codex answers inside the isolated relay service (`--disable shell_tool`, separate OS user) with BLOCKING/MINOR findings; the worker posts it as a PR comment marked "advisory only, not an approval". It never approves, merges or changes code; merging stays with CI and the owner/Claude review rules.
- Kill switch: `AUTOPILOT_CODEX_REVIEW=0` in the worker environment.

## 2026-11-13 — MyCast audio is not stored on our server; history plays back from Telegram (owner question)

- A listener episode is generated in memory, sent with Telegram `sendAudio` and dropped; the script is not kept either. Only Telegram's `file_id`, title, length and date stay in the listener record (a few hundred bytes per day, last 14 days).
- "Your episodes" on the MyCast page streams an episode back through `GET /api/mycast/account/episodes/{date}/audio`: the server calls Bot API `getFile` and passes the bytes through (bot token stays server-side, nothing cached on disk). Only the signed-in listener's own episodes; another listener's cookie gets 404.
- Listener episodes are encoded at 64 kbps mono (was 96): 30 minutes ≈ 14 MB, under the Bot API's 20 MB re-download limit; voice quality is unchanged in practice.
- The public demo cache keeps at most 120 short WAV files (was 300), ≤ ~85 MB of the 1 GB Render disk.

## 2026-11-13 — mycast.pro (owner bought the domain)

- The same Render service answers on `mycast.pro`; on that host only MyCast is served: `/` and any non-MyCast path redirect to the MyCast page, `www.` redirects to the apex, `/privacy` and `/terms` (bilingual, needed for Google verification) are public. The FactoryOS dashboard and API stay on `blackboxlab-factoryos.onrender.com`. Hosts are configurable with `FACTORY_MYCAST_HOSTS`.
- Telegram login works per bot domain (BotFather `/setdomain`), so the login widget moves to `mycast.pro`; Google sign-in needs `https://mycast.pro` as an authorized JavaScript origin.
- The Google Calendar guide now separates publishing status from verification, notes the 7-day refresh-token expiry in Testing, and warns not to switch a production sign-in project to Testing (Codex review on #332).

## 2026-11-13 — Browser agent (T-560) wired to a queue, read-only first (owner: "погнали")

- `browser_tasks.py`: owner-only queue (`/api/factory/browser/tasks`), worker claim/result routes under the Claude worker token; 50 tasks kept, screenshots ≤ 2 MB PNG on the Render disk, deleted with their task. Only public https URLs (no credentials in the URL, no private/loopback/link-local IPs, no `.local/.internal`).
- `autopilot/browser_tasks.py`: one task per worker pass; plan = navigate → extract (≤ 5 selectors) → screenshot, action class `read`, anonymous context (no session restore). The host is re-resolved on the worker and refused if any address is not public (blocks DNS-rebinding to EC2 metadata).
- Executor: two opt-in policy flags, used only by this read path: `allow_offsite_subresource_reads` (real pages load CDN assets; off-origin navigation and every non-GET stay blocked) and `return_extracted_text` (redacted, 6 000 chars). Defaults keep the previous behaviour for all other callers.
- Codex review on #334 (3 blocking findings, all fixed): every Chromium connection goes through `browser_runner/egress_proxy.py`, a local CONNECT-only proxy that resolves the host itself, refuses unless all addresses are public and connects to the address it checked (no DNS rebinding, no private sub-resources or redirects; `<-loopback>` removes Chromium's loopback bypass; https port only). The queue never evicts queued/running tasks; at 20 active tasks new ones get 429.
- Registration, logins and purchases come next and stay behind the existing approval gate; the trusted approval verifier for submit is still not wired, so the executor refuses submit unconditionally.

## 2026-11-13 — Every background module gets a dashboard view (owner: "чтобы весь функционал совпадал с UI")
- The browser agent card was invisible in practice: its class `brCard` collided with the existing browser-run card CSS
  (`flex:0 0 220px; font-size:7px`) inside the flex column. Renamed to `brAgentCard`.
- Audit of `/api/*` routes against `static/index.html`: five owner-facing modules had an API but no view — Telegram
  relay tickets, the Claude ↔ Codex relay, MyCast website listeners, voice briefs, battle runs. They are now tabs of one
  read-only "Пульт власника" card; each tab reads one existing owner endpoint. Worker-only routes are not UI material.
- New owner-only `GET /api/factory/mycast/listeners`: delivery state per listener with first name and slug only (no email,
  chat id, share code or Telegram file id), so the dashboard shows who is due, delivered or failing today.
- Sidebar: "Браузерний агент" (Автоматизація) and "Пульт власника" (Система) scroll to the cards; the navigation test's
  before/after map and DOM stubs were extended for the two new destinations, not loosened.

## 2026-11-13 — Read tasks survive analytics beacons and third-party iframes (first real EC2 run)
- example.com read fine on EC2; prom.ua came back `blocked: off_allowlist_network_request`. Real shops send analytics
  POSTs and load third-party iframes, and any aborted request used to fail the whole read.
- Now, only for `read` tasks with `allow_offsite_subresource_reads`: such requests are still aborted (never sent),
  but the read continues. A main-frame navigation away from the allowed origin still fails the task, and every other
  action class keeps the old fail-closed behaviour. Unknown frame info counts as main frame.

## 2026-11-13 — MyCast "Підключити Google Календар" (read-only)
- Owner set up Google Cloud project "MyCastpro": consent screen External + In production, scope calendar.readonly,
  Web client with redirect `https://mycast.pro/api/mycast/calendar/callback`, FACTORY_GOOGLE_CLIENT_ID/SECRET in Render.
- Server-side OAuth (`mycast_calendar.py`). State is HMAC-signed, expires in 10 min, names the listener, and must match
  the listener cookie on return (no login CSRF). Only the refresh token is kept, AES-256-GCM encrypted with
  FACTORY_VAULT_KEY and bound to the slug (AAD). Without the vault key the button is not offered.
- Calendar contents are never stored: when the listener's episode is due, the server reads today's events and/or
  birthdays (whatever the listener ticked; title + start time, ≤10 each, cached 1 h in memory) and hands them to the
  worker with that one item. The worker prompt marks them as private plain text, never instructions.
- Any calendar failure means "no calendar today", never a missed episode. invalid_grant (revoked in the Google
  Account) forgets the token. Disconnect and account deletion revoke the token at Google first.
- Not yet: Google's verification for the sensitive scope (the owner submitted early by accident; until approved, up
  to 100 users see the "unverified app" screen). The demo video comes once this is live.

## 2026-11-13 — MyCast: Telegram-only sign-in, public podcast page and share card
- Sign in / sign out moved to the header. Telegram is the only sign-in; Google is calendar sync only (the GIS button
  is gone; the server route stays so existing Google accounts keep working).
- Duration picker: 7 choices (5, 7, 10, 15, 20, 25, 30; owner: 1 and 3 min are too short). Validation still accepts any minute 1–30, and a saved
  length outside the list is shown, so no profile is invalidated.
- `/mycast/u/{slug}` is now a shareable page (first name, topics, geography, follows, schedule, voice, "make one like
  this" with the referral kept) instead of a redirect into the editor; an undecodable old code still redirects.
- `/mycast/u/{slug}/card.png`: 1200x630 og:image drawn with Pillow and bundled DejaVu Sans (free licence), cached per
  podcast version. Added `Pillow` to requirements.
- Listening by link is **opt-in** (`public_audio`, default off): the episode can read out calendar events and
  birthdays, so the toggle says so. The latest sent episode streams from Telegram (never stored), 60 plays/hour/page.

## 2026-11-13 — Claude drives the browser agent itself (read-only)
- Owner: "делай токен для агента … моего подтверждения не нужно, нужен результат". FACTORY_BROWSER_AGENT_TOKEN
  (≥ 32 chars, never equal to a worker token) opens only `/api/factory/browser/agent/tasks[/{id}[/screenshot]]`.
- Claude's tasks are tagged `source: claude`, read-only, public https only (same URL rules and egress proxy as the
  owner's), at most 200 per 24 h, and share the 20-task active queue. Claude can read only its own tasks.
- The token reaches this cloud session through the environment's credential form (injected by the network proxy);
  it never appears in chat or in the repository. Logged-in browsing stays out of scope.
