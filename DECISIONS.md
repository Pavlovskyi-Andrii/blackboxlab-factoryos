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
