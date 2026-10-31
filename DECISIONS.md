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

