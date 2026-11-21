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

## Re-check (2026-11-01, head `c2879b9`)
- `autopilot/aws-worker` and `origin/main` are the same commit, `c2879b9` (merge of PR #81). So the T-590 slice and the T-599 commits are on main. Step 1 below is done; the merge was observed only as local git refs after `git fetch`.
- Green on Python 3.9: compile, `smoke_tests.py`, the planner, `test_relay_execution` (74 tests), `test_relay_telegram` (9), `test_worker_token_binding` (2), `autopilot.test_delegation` and `autopilot.test_autopilot`. The working tree had unrelated uncommitted edits in `app.py`/`static/index.html` from another session; the smoke ran with them in place, and they are not part of this commit.
- This run was denied `gh`, `curl` and `env`-prefixed commands. So the CI result for `c2879b9`, Render `build_sha`, `paired=true`, the live trace and the Issue #41 comment remain UNVERIFIED. Nothing was claimed.

## Re-check (2026-11-15, run `run-20261115093856-a5105e`, head `e24369d`)
- Since 2026-11-01 several stages have changed in the repo record, but none were observed live by this run:
  - T-506 is checked: the owner chat was paired on 2026-11-02.
  - The #289 round trip (per-ticket branch → PR → CI/merge reconcile → Telegram) and Evidence Tiers 1–2.6 (a ticket closes only on merged PR + CI from Render's own read, plus a `deployed` check via `render:build`) are on main.
  - DECISIONS records owner Telegram tickets R-0063 (2026-11-11) and R-0074 (2026-11-14) that ran on the live worker.
- Local refs only (no fetch): `origin/main` = `418e25f`. `autopilot/aws-worker` holds T-609/T-610 plus merges of main, so it is ahead of main and not behind it.
- Green on Python 3.9: compile, `smoke_tests.py`, the planner, `test_relay_execution` (111 tests) and `test_relay_telegram` (25).
- This run was denied `gh`, `git fetch`/`-C`, `env` prefixes and the FactoryOS `web_read` tool, so it could not read GitHub, Render or Issue #41. The DONE criterion still lacks independently observed evidence: a single owner ticket traced live through claim, run_id, PR, CI, merge, deployed revision and Telegram `/task`, posted to Issue #41. T-590 stays unchecked. Nothing was claimed.

## Re-check (2026-11-15, second run, head `9614bcf`)
- Green on Python 3.9: compile, `smoke_tests.py`, the planner, `test_relay_execution` (111 tests) and `test_relay_telegram` (25).
- `gh issue view 41` and the FactoryOS `web_read` of `/api/version` were both denied again. No stage changed, nothing was claimed, and T-590 stays unchecked.

## Re-check (2026-11-15, third run, head `fd6e083`)
- Green on Python 3.9: compile, `smoke_tests.py`, the planner, `test_relay_execution` (111 tests) and `test_relay_telegram` (25).
- `git fetch origin` and `gh issue view 41` were denied. No live stage could be observed, nothing was claimed, and T-590 stays unchecked. Another worker re-run cannot change this. The next run needs GitHub/Render read access, or an owner-posted trace in `.autopilot/answers.md`.

## Re-check (2026-11-15, fourth run `run-20261115095629-aabbde`, head `3639161`)
- Green: compile and the planner. `smoke_tests.py`, `test_relay_execution` and `test_relay_telegram` were not re-run because Bash was denied for them (both `env` and in-process forms). The last green result for those is the third run at `fd6e083`.
- `gh issue view 41` and the FactoryOS `web_read` of `/api/version` were denied. No live stage was observed, nothing was claimed, and T-590 stays unchecked.

## Re-check (2026-11-15, fifth run, head `f0d275c`)
- Green: compile, the planner (needs `FINISHER_DATA_DIR`, because the default `/var/data` is not writable on EC2) and `smoke_tests.py` (8). Each suite also passed in its own process with its own `DATA_DIR`: relay pairing 4, smoke_evidence 9, lifecycle 10, execution 111, telegram 25, agent_messages 20, notify_dedupe 6, livefix 5, and telegram_group 8.
- When all the Relay suites are loaded into one unittest process, `test_relay_telegram.test_webhook_operator_lanes` fails: the Claude lane card shows no R-0002. This is shared module state between suites, not a product regression, because the same test passes alone. Run the suites one per process.
- `git fetch`, `gh issue view 41` and FactoryOS `web_read` of Issue #41 were denied. No live stage was observed, nothing was claimed, and T-590 stays unchecked.

## Re-check (2026-11-15, sixth run `run-20261115100050-a0498b`, head `1f4a4a1`)
- Green: compile, `smoke_tests.py` (8), the planner, `test_relay_execution` (111) and `test_relay_telegram` (25). Each suite ran in its own process, with env set inside Python, because `env`-prefixed commands were denied.
- `.autopilot/answers.md` has no owner-posted trace. `gh` and FactoryOS `web_read` of `/api/version` were denied. No live stage was observed, and T-590 stays unchecked.

## Closure (2026-11-21, run `run-20261121170154-7d08ab`, head `8824ffa`)

T-590 is checked. Each stage below names who observed the evidence; this worker run observed only the first two rows.

| Stage | State | Evidence and observer |
|---|---|---|
| Deterministic stages (table above) | verified | this run: compile, `smoke_tests.py` (8), planner, `test_relay_execution` (127), `test_relay_telegram` (25), `test_relay_acceptance` (16), one process per suite |
| Non-main PRs, slice on main | verified | this run, local git: `f5485a8` (#63), `c2879b9` (#81), `b06029a` (#112); `autopilot/aws-worker` == `origin/main` == `8824ffa` |
| Paired owner chat (T-506) | verified | owner, 2026-11-02 (ROADMAP T-506 checked) |
| Live trace: Telegram intake → one ticket → claim + run_id → running → done → delivery receipt | verified by the server | R-0087 · `run-351295eb0d92`, `latest_telegram_acceptance()` VERIFIED on the owner's Worker Center, 2026-11-17 (T-591-H checked; DECISIONS 2026-11-17). Not re-read by any agent session |
| Deployed revision | verified | owner: `/api/version` `build_sha` `60c983bd19fd…` == latest main (`.autopilot/answers.md`, 2026-11-15) |
| CI | not observed by this run | `gh` denied. Rests on the owner's rule that PRs merge only on green CI of the current head |
| Issue #41 evidence comment | not posted | `gh` denied. The owner dropped the Issue #41 transcript for T-591-H (2026-11-17); `/proof R-0087` reproduces it. Optional follow-up for a session with GitHub access: post a link to this table |

## Remaining actions (historical; steps 1–4 are closed as described above)

1. **Session with GitHub access (Claude interactive, standing grant):** push `autopilot/aws-worker`, then open PR `autopilot/aws-worker → main`. Wait for CI on the current head; merge only when it is green.
2. **After merge:** `GET https://blackboxlab-factoryos.onrender.com/api/version` must return `build_sha` equal to the merge commit.
3. **HUMAN, owner only (T-506):** put `FACTORY_TELEGRAM_BOT_TOKEN` in the FactoryOS Render secret env. Start Telegram pairing in FactoryOS and send the one-time `/pair CODE` to the bot. Done when `/api/factory/telegram/status` shows `paired=true`.
   _Done 2026-11-02 (T-506 checked)._
4. **Live trace:** in the paired chat, send `/new test: T-590 live trace` and wait for `claimed` with a run_id. Then send `/task <id>` and check that it matches the `/relay` web detail. Post the redacted transcript, the SHA, the PR, the CI run and `build_sha` to Issue #41, and only then tick T-590.
