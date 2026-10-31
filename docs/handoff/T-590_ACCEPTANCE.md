# T-590 — acceptance status (2026-10-31)

Run: parent-owned `run-20261031102116-db8d49` on EC2, branch `autopilot/aws-worker`, head before `a51556b`.
Rule: a stage counts as verified only with evidence. Everything else is UNVERIFIED.

## Stage-by-stage

| Stage (handoff §6) | State | Evidence |
|---|---|---|
| Intake → one durable ticket, source_key dedupe | verified, deterministic | `test_relay_lifecycle.py`, `test_issue_intake.py` (incl. app-level pass, now also on Py 3.9), `test_t599_acceptance.py` |
| Authenticated claim, run_id, claim_rejected, other-lane refusal | verified, deterministic | `test_relay_execution.py`, `test_t599_acceptance.py`, `test_worker_token_binding.py` |
| Idempotent events (event_id replay, superseded run 409) | verified, deterministic | `test_relay_lifecycle.py` |
| Stale / blocked / failed paths, no auto-rerun | verified, deterministic | `test_relay_livefix.py`, `test_lane_board.py`, `autopilot.test_autopilot` |
| Redaction of notes/issue text | verified, deterministic | `test_relay_lifecycle.py`, `test_issue_intake.py` |
| Restart persistence (JSON store reload) | verified, deterministic | `test_relay_execution.py` |
| Web `/relay` + Telegram `/status` `/tasks` `/task` share one read model | verified, deterministic | `test_lane_board.py` (API endpoint case now runs on Py 3.9), `test_relay_telegram.py` |
| No fabricated ChatGPT telemetry; PR/CI/merge/deploy shown "не проверено" | verified, deterministic | `test_lane_board.py`, `test_relay_lifecycle.py` |
| Publish approval gate untouched | verified | `smoke_tests.py` (signed media + approval paths) |
| Live server claim of this run on Render | UNVERIFIED here | parent requires a claim before starting (`claim_roadmap`, fail-closed); this sandbox cannot read Render |
| Commit pushed to `origin/autopilot/aws-worker` | UNVERIFIED | parent pushes only `done` runs; this run is `blocked` |
| PR → `main`, CI green | NOT DONE | `gh`/network denied to the delegated agent |
| Merge + Render deployed SHA | NOT DONE | needs PR first; check `GET /api/version` → `build_sha` |
| Paired owner Telegram chat, live `/new` → claim → `/task` trace | NOT DONE — HUMAN T-506 | `/api/factory/telegram/status` must report `paired=true` |
| Issue #41 evidence comment | NOT DONE | needs GitHub access |

## Fixed in this run
`app.py` (3 annotations) and `media_finisher_worker/app.py` (9) used `X | None`, which fails at import on the EC2 worker's Python 3.9. So the CLAUDE.md smoke and planner checks could not run on the worker at all. They now use `Optional[...]`. The two `skipIf(py<3.10)` app-level tests run on 3.9 too.

## Re-check (2026-10-31, run `run-20261031162233-a7b938`, head `62ffd5e`)
- All deterministic stages above re-ran green on Python 3.9: compile, the planner (with `FINISHER_DATA_DIR` as in CI), `smoke_tests.py`, `test_relay_execution` (58 tests: lifecycle, livefix, roadmap claims, lane board, issue intake, T-599 A–E), `test_relay_telegram` + `test_worker_token_binding` + `autopilot.test_delegation` (11), and `autopilot.test_autopilot`.
- `autopilot/aws-worker` is 10 commits ahead of `origin/main` (`76ba72f`). `ae18547` and the T-599-E/F/T-599 commits are **not** on main yet, so no deployed revision can contain them.
- The agent still has no network, `gh` or `curl`, so the PR, CI, `build_sha`, Telegram pairing and Issue #41 stages remain UNVERIFIED. Nothing new was claimed.

## Exact remaining actions

1. **Session with GitHub access (Claude interactive, standing grant):** push `autopilot/aws-worker`, then open PR `autopilot/aws-worker → main`. Wait for CI on the current head; merge only when it is green.
2. **After merge:** `GET https://blackboxlab-factoryos.onrender.com/api/version` must return `build_sha` equal to the merge commit.
3. **HUMAN, owner only (T-506):** put `FACTORY_TELEGRAM_BOT_TOKEN` in the FactoryOS Render secret env. Start Telegram pairing in FactoryOS and send the one-time `/pair CODE` to the bot. Done when `/api/factory/telegram/status` shows `paired=true`.
4. **Live trace:** in the paired chat, send `/new test: T-590 live trace` and wait for `claimed` with a run_id. Then send `/task <id>` and check that it matches the `/relay` web detail. Post the redacted transcript, the SHA, the PR, the CI run and `build_sha` to Issue #41, and only then tick T-590.
