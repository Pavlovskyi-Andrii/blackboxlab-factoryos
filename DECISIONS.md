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
