# T-598 — Stable autonomous engineering handoff and report (2026-10-31)

Scope: backlog M6 (`docs/roadmap/CLAUDE_OWNER_BACKLOG_2026-10-30.md`), Issues #40/#49–51/#61, T-593.
Each line below names the code and the deterministic test that proves it. Nothing here claims PR, CI, merge,
Render deploy or owner Telegram delivery. Those stages are evidenced separately, after the worker push.

## Execution chain: queued → claimed → running → checks → pushed

| Stage | Where | Proof |
|---|---|---|
| Dedupe GitHub Issue / ROADMAP / Relay | `intake_github_issue` links an Issue naming a T-ID to the existing `roadmap:T-…` ticket. The server holds one ticket per ROADMAP task (T-599-C/E). | `test_issue_intake.py` (`test_import_and_dedupe_on_repeat`, `test_task_id_links_existing_roadmap_ticket`), `test_roadmap_claims.py` |
| Depends/Owner scheduler (#62) | `autopilot.selectable`: open, not HUMAN, owner lane matches, every `Depends:` checked | `dependency_and_owner_regression`, `roadmap_owner_lint` |
| Atomic claim before any code change | `relay_tasks.claim_roadmap`. A refused claim defers the task, and the agent never starts. | `claim_gate_regression`, `test_t599_acceptance.py` |
| Running / committed / pushed / done events | `relay_tasks.RunReporter` is fenced by run_id with sequential event ids | `claim_gate_regression` asserts exactly `running, committed, pushed, done` |
| Checks | `delegation.verify_evidence`: one commit with the task ID, ROADMAP box closed, zero CLI exit, status matches commit | `autopilot.test_delegation` |
| Truthful parent run state | `.autopilot/run.json` is parent-written. A dead pid is reported as `stale`, never as `running`. | `autopilot.test_delegation`, `claude_pro_worker.run_snapshot` |

## New in T-598

- **Automation survives restart.** The parked-blocked, parked-failed and per-task attempt counters are now kept
  in `.autopilot/parking.json` (gitignored, atomically replaced). Before this change, every restart reset them,
  and that includes the automatic `code_updated` re-exec after each runner change on main. So a red task could
  run `MAX_FAILS` times per restart, without limit. Proof: `restart_survival_regression` restarts the daemon
  after every iteration. A red task runs exactly `MAX_FAILS` times, a blocked task stays parked until
  `answers.md` changes, and healthy work still runs. Corrupt state is ignored. The test is mutation-checked:
  with loading disabled, the red task loops.
- **No endless `git pull` shown as busy.** `git pull`, `fetch` and `push` run with `GIT_TERMINAL_PROMPT=0` and
  a timeout (`AUTOPILOT_GIT_TIMEOUT_SECONDS`, default 120 s, clamp 10–600). A hung or unreachable remote now
  gives `sync_branch → "offline"` / `push_branch → False`, which feeds the existing bounded push-retry path.
  Proof: `git_timeout_regression`.
- **Concise milestone report.** `autopilot.milestone_report` builds a report of at most 10 lines, sent only on
  `done` and `blocked`: UTC and Kyiv time, task and stage, owner and executor lanes, branch@SHA, changed files,
  reported checks, blocker and next selectable task. It always says
  `PR / CI / Render: not verified by the worker`. Proof: `milestone_report_regression`.

## Optional HUMAN requests (least privilege, not blocking code)

These two requests are added to ROADMAP as `[HUMAN]` tasks. Engineering does not wait for them.

1. **GitHub `workflow` scope** for the worker's GitHub credential. It is only needed to edit
   `.github/workflows/*.yml`. Until it is granted, new tests ride in existing CI steps (the T-594…T-597
   precedent).
2. **`ec2:DescribeInstances`** read-only permission for the instance role. It is only needed so Worker Center
   `ec2_api` can say more than `unknown · describe_instances_not_granted`. Proposed policy (owner applies it,
   with no AWS access keys):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ec2:DescribeInstances",
    "Resource": "*"
  }]
}
```

`DescribeInstances` does not support resource-level restriction, so `Resource` must be `*`. The permission is
read-only and free.

## Not verified by this run

PR creation, CI result, merge to main and Render deploy for this commit happen after the worker pushes the
branch. Live Telegram delivery of the milestone report needs T-506 pairing (HUMAN). No paid resource was
created or called.
