# FactoryOS — Owner's consolidated Claude implementation backlog
**2026-10-30 · Claude Code Pro is principal builder · P0 first · not a completion report**

Owner: finish promised-but-unfinished work from October 27–29 without repeated reminders. Deliver an actually working Telegram live build control room first, then truthful worker/build dashboards, then left-navigation/submenus, resizable slide-out panels, and explainable mobile UI. **Read this spec plus** \`docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md\`, \`CLAUDE.md\`, \`ROADMAP.md\`, \`DECISIONS.md\` and issues #61, #41, #51–57 before implementation. Reconcile with merged PRs #42/#43/#62 and open PRs #34/#60; avoid rebuilding features that already exist. Every work order below has a GitHub issue, criteria and dependency.

## Facts and current blockers (verified 2026-10-30)
- Existing AWS EC2: \`i-087bd3c1bb5de4ec6\` in \`eu-north-1\`; \`ec2-user\`, checkout \`/opt/factoryos\`, branch \`autopilot/aws-worker\`, service \`factoryos-claude-worker.service\`. Owner's \`systemctl status\` showed **active** but only repeating \`git pull --rebase\`; do NOT equate active to actually working.
- Owner's \`aws sts get-caller-identity\` succeeded via instance role **FactoryOSWorkerRole**, so access/secret keys are **not required**. \`aws ec2 describe-instances\` failed UnauthorizedOperation because \`ec2:DescribeInstances\` is not granted. Read-only cloud observability is an optional separate IAM improvement; **not a blocker for Telegram coding**. Do not change IAM/policies or create cost without owner approval.
- \`claude auth status\` previously printed \`loggedIn:false\` for **ssm-user**, while worker runs as **ec2-user** with separate HOME. Verify ec2-user OAuth; do not infer it logged out, reset sessions, or request credentials unnecessarily.
- Owner's local check on 30 Oct: \`T-590\` \`status=blocked\`; \`run.json\` absent; \`status.json\` reports committed slice at \`86b6c21\` on origin/autopilot/aws-worker, **not live verified**. Reported blocker: PR/CI/merge/Render deploy and real owner Telegram test. The worker has restrictions on git push / gh / network, while parent runner handles safe branch push.
- Main has merged PR #62 for \`Depends:\` / \`Owner:\` scheduler; branch was diverged (ahead 5, behind 1); **rebase/merge with care and zero force-push, preserve working changes**, avoid duplicating ChatGPT-owned/merged tasks.
- Initial T-590 slice already implements parent-owned \`.autopilot/run.json\`, run_id-fenced idempotent events, owner-only GitHub Issue → Relay intake, shared Telegram/Web lifecycle, and deterministic \`test_relay_lifecycle.py\`. Existing PR #60 remains WIP and its helper should be reconciled, not duplicated. Production acceptance absent.
- Prior \`T-560-B\` committed \`d68851a\`; \`T-560-C\` pushed \`f660044\`; initial workflow \`.github/workflows/ci.yml\` changes blocked by GitHub OAuth missing \`workflow\` permission. That rejected workflow patch was preserved at \`/home/ec2-user/factoryos-handoff/T-560-C-unpublished-ci-workflow.patch\`. Only use explicitly authorized CI workflow changes.
- All statuses and timestamps must come from actual runner/Relay/GitHub/Render/Telegram evidence. No fabricated online activity or made-up percent completion.

## Delivery sequence and assigned tickets

### M0 — Release plumbing / unblock T-590 (P0: #61, #41, T-590)
- Open a **draft PR** from \`autopilot/aws-worker\` to \`main\`, attach current implementation evidence and clear outstanding issues; reconcile merged scheduler #62 without force-push; resolve conflicts through reviewed changes in a separate safe branch if needed.
- Check CI and fix failures; integrate after verified green checks/review, then inspect actual Render deployed SHA and API/Relay health.
- Owner can be busy with EC2; do not restart EC2 service or mutate authentication without safely checking no live task.
- Acceptance: GitHub PR + actual CI statuses + merged SHA + Render deployed SHA, each separately verified, with links. Do not mark T-590 done solely because PR exists. If unable to merge or deploy, surface exact actionable blocker and continue **other safe independent work**.

### M1 — Telegram real control room (P0: #41, #51, T-590/T-591)
- Owner message or \`/new\` → precisely one persistent Relay ticket → authenticated claim by **actual Claude worker** → run_id + started_at + live checkpoint/heartbeat + bounded execution → result/errors → change evidence/commit/push/PR/CI/merge/deploy stages. Queue is not execution; status transitions must be strictly sourced and idempotent. Cross-reference Issue/ROADMAP/Relay using source_key, not just GitHub title.
- Telegram commands \`/status\`, \`/tasks\`, \`/task <id>\`, \`/history\`, \`/roadmap\`, \`/github\`, \`/workers\`, \`/operators\`, optional \`/claude\` \`/gemini\`. Real inline Refresh/Details/PR/Log/Retry controls, correct RU/UK/EN and owner-chat auth; mobile-friendly.
- Persist event history and human input over restarts; report queue position and stale/offline/blocked states, actionable reasons, no duplicate Telegram receipts or unnecessary repeated notifications. ChatGPT lane only for explicitly audited actions, else \`no live telemetry\`.
- Web \`/relay\`, Telegram and Worker Center must read same record. If bot unpaired, verify \`T-506\` and request exact owner pairing action without claiming live success. Never dump bot tokens, auth secrets, chat IDs.
- Acceptance: real paired owner test \`/new safe test\` → actual claim/run events → final status received in same chat + in Web, replay/restart/security tests, PR/CI/deploy proof and redacted evidence in #41/#61. No auto social publishing.

### M2 — Truthful Build Progress / Worker Center / agent activity (P0/P1: #52, #55, #56, T-592)
- Reconcile originally displayed Build Progress **87% (39/45)** vs Autopilot **49% (28/57)** as distinct populations with labelled denominators and provenance, not a made-up common percent. Separate product jobs, roadmap, delegation, historical versions vs current.
- Worker Overview distinguishes EC2 running/SSM, systemd, claude.ai OAuth, heartbeat to Render, relay queue, run_id, active child process, actual claim/stage and last checked timestamp. Do not present EC2 IAM \`DescribeInstances\` UnauthorizedOperation as full EC2 offline.
- Click existing Claude worker for host/status/activity timeline, changed files, tests, branch, PR, CI; include blocked reasons and next safe action. Separate existing workers from \`Add worker\` onboarding.
- Worker activity heatmap/calendar must attribute to verified worker commits/runs/PR rather than all repo commits. Show zero vs unknown days separately; drilldown, filters and timezone Kyiv. Official AI brand icons only if legitimate assets; mark planned models as planned.
- HUMAN blockers such as \`T-506\` clickable with precisely needed action, paired evidence check and recovery. Collapsed decision summaries rather than long raw debug walls. No fake running animations/percent bars; check actual changes + recent heartbeat.
- Acceptance: desktop/mobile parity, stale/failed/idle scenarios, links back to primary sources, smoke/CI and screenshots.

### M3 — Left menu into submenus (P1: #53, T-574)
- Audit every current top nav item and map old→new; group in collapsible sidebar headings: **Overview & tasks**, **Ideas/Discovery**, **Create/Video**, **Review & Publish**, **Growth/Analytics**, **Agents/Automation**, **Connections/Settings** (names illustrative, use only existing features).
- Distinguish specific nouns, e.g. \`Поиск идей и трендов\` vs \`Discovery\`, \`Аналитика контента\` vs vague \`Метрики\`. Consistent icons, one-line hints and current section highlight; keep all routes, anchors and permissions reachable.
- Desktop: compact icons, expand with descriptions on hover/tap, remembered accordion group state, accessible keyboard navigation. Owner previously requested a slide-out menu **around one third of the screen** on capable viewports, closing when tapping outside; on narrow phones use usable adaptive width instead of illegible 1/3. Preserve persistent sidebar when working with right panels.
- RU/UK/EN labels, dark cyber operating UI, mobile 390px, desktop 1440px, no lost routes. Before/after nav map + screenshots + checks.

### M4 — Sliders, panels and window usability (P1: #54, T-575)
- In \`#taskPage\`, \`#dcPage\`, Build Progress/Worker Center and other large overlay drawers: visible LEFT-edge drag handle for resize, sensible initial ~65% viewport desktop width, min/max bounds respecting sidebar; maximize/restore icon next to X, remember last width, keyboard accessible resizing, outside-tap/Escape close.
- Fix horizontal overflow/cut-off \`Planned/In Progress/Completed/Blocked\` columns. Each grid/table adapts to breakpoint; sticky headers or clearly signalled internal scroll when necessary. Not a massive horizontal scrollbar for entire document.
- Mobile drawer full width, no clipped forms/buttons, touch drag and scroll, safe focus/ARIA. Test at 1440x900, 1024x768, 390x844. Screenshot before/after, JS syntax/DOM regression and CI.
- Existing charts/graphs: genuinely working time-range selectors/sliders, no inert controls, no synthetic metrics.

### M5 — Help, Agent Office and fit/finish (P1/P2: #57 T-578, #47)
- Reusable info icon/tooltips for ambiguous screens, providers, approvals, queued vs running, costs, connections, agent roles, workers. Desktop hover, mobile tap, focus management and dismiss. Compact mini flow diagrams and RU/UK/EN, accessibility.
- Agent Office workers actually clickable: role, status, current task, handoff, last event, artifacts, time/tokens/cost only when measured. Trace Viewer/build-process links, clear ownership and team task routing; do not fabricate worker or Gemini online state.
- Confirm language switch, usable mobile design, task search and filter; consistent dark style. No premature introduction of paid integrations.

### M6 — autonomous execution, permissions and reporting (P0 ongoing: T-593, #40, #49, #50)
- One claim/run at a time, correct dependency-aware and owner-aware scheduler (#62), no duplicate re-execution from GitHub Issues vs ROADMAP, bounded retries and checkpoints; persistent run status in worker parent. Prevent idle \`git pull\` loop being shown as active engineering.
- Claude Code uses **existing subscription**, not API key. A safe reviewed allowlist can support local coding/tests/commits but not arbitrary \`Bash\`, paid AWS changes or production access. Diagnose permission denials precisely.
- OAuth GitHub workflow scope and role \`ec2:DescribeInstances\` belong to **separate least-privilege HUMAN requests** if needed; give exact AWS policy proposal to owner but don't modify without approval. No AWS access keys.
- Report each milestone with UTC and Kyiv time, task and stage, owner/executor, files changed, tests, branch SHA, PR, CI, Render deploy, current blocker and next task. Report at safe checkpoints to owner Telegram when it actually works, without spam.

## Delivery rules / acceptance gate
1. Existing Issues #41, #51–57, #61 remain authority; **don't duplicate open issues**. Record progress and link PRs under those issues.
2. Keep implementation to small reviewable commits and one PR per independent milestone/feature where feasible. Handle shared branch and concurrent owner EC2 sessions safely. No force pushes or direct main writes.
3. Real CI + smoke + mobile/desktop screenshots, RU/UK/EN parity and redacted evidence required. If external owner Telegram or cloud auth inaccessible, mark **BLOCKED (HUMAN)** for exactly that check, finish safe engineering work and proceed to unrelated independent tasks.
4. No ungrounded success language. \`Created ticket\` ≠ \`claimed\` ≠ \`running\` ≠ \`committed\` ≠ \`pushed\` ≠ \`CI passed\` ≠ \`deployed\` ≠ \`owner tested\`.
5. **Owner intent: Claude should actively take these tasks without needing the owner to continuously prompt or unlock artificial dependency chains.** Report the actual first claimed task ID and real progress before saying work has started.
