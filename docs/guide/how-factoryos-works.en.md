# How FactoryOS works: a project guide

This page explains the whole system at a glance:
- who does what;
- where to look for it;
- which rules cannot be bypassed.

Details on each part are in the other guides of the "How it works" section.

> Checked against the code on 2026-11-14. If anything here differs from what the dashboard shows, the dashboard is right: it means this guide is out of date.

## 1. What the system is made of

| Part | What it is | Where it lives |
|---|---|---|
| **FactoryOS dashboard** | The website where you see and approve everything | Render, `blackboxlab-factoryos.onrender.com` |
| **Server** | A FastAPI application (`app.py` and the modules next to it) | Render. Deploys happen only after green CI on `main` |
| **EC2 worker** | A separate machine where the agents actually work: Claude, the browser, MyCast | AWS EC2, the `autopilot/` loop |
| **GitHub** | Code, tasks (issues), PRs, CI checks | `blackboxlab-factoryos` |
| **Telegram bot** | Assigns tasks to agents and sends back results and MyCast | The Relay bot |
| **Notion** | Concepts, decisions, research, project memory | Notion workspace |

## 2. Who does what

- **You (the owner).** You set goals and priorities. You approve publications, spending, major releases and anything that goes outside. Nothing is published without your "yes".
- **Claude.** Writes code in a separate branch, opens PRs, runs tests, reviews architecture and carries out tasks from Telegram through Relay.
- **ChatGPT / Codex.** Write specifications and prototypes and do automated PR reviews. Blocking comments from Codex are fixed before merging.
- **Gemini.** A free helper: does research, drafts and documentation, and voices MyCast.
- **Browser agent.** Reads pages in a browser on EC2, including under a saved session. It only reads and never publishes anything.

## 3. How a task travels

1. **Task.** You write it in Telegram or create an issue on GitHub.
2. **Relay.** The task becomes an `R-xxxx` ticket with status `queued`. This means "assigned", but not yet "in progress".
3. **Claim.** The worker on EC2 picks up the ticket, and the status becomes `claimed`, then `running`. Only from this moment is work actually happening.
4. **Branch and PR.** The agent makes changes in a separate branch and opens a PR.
5. **CI.** GitHub Actions runs the checks. Red CI means the PR must not be merged.
6. **Review.** Codex and/or a human review the PR. Blocking comments are fixed.
7. **Merge → deploy.** After merging into `main`, Render deploys the new version on its own, but only after green CI.
8. **Reply in Telegram.** You receive the outcome: a PR, a link or a clear reason for the failure.

**If a task failed on a limit.** Claude gets up to 60 turns and 30 minutes per run. If that was not enough, the bot says so. Split the task into steps or press Retry.

## 4. Dashboard sections

| Group | What is there |
|---|---|
| **Overview** | Control Room, pipeline, Supervisor, error center |
| **Content creation** | Jobs, Discovery, Revideo, Content Brain, Media Finisher, variants, package, files |
| **Review and publishing** | Review: approve or send back for rework. Publish: schedule and publication receipts |
| **Growth and learning** | Performance with real metrics, Analytics, Experiments |
| **Automation and team** | Autopilot (always stops at review), agents, workers, browser agent |
| **MVP Builder** | MVP projects with stages and evidence, MyCast |
| **System** | Build Progress, Release QA, owner console (Telegram tasks, Claude ↔ Codex, MyCast listeners), brand strategy, settings |
| **Learning** | This page: your learning, system tutorials, guides |

## 5. The content factory

1. **Brand strategy.** 7 steps: goal → unpacking → audience → tone → pillars → funnel → CTA. Approved steps are assembled into the **Master Brief**. Each content agent receives its own part of the brief.
2. **30-day plan.** Tasks are created from the plan. A task created from a plan row remembers which brand it belongs to.
3. **Production.** Script → voice → video → finishing (subtitles, sound, safe zones).
4. **Review.** You approve or send it back for rework.
5. **Publish.** A separate, explicit action after approval. There is no auto-publishing.
6. **Performance.** Only real metrics from the platforms. No metrics, no "learning".

## 6. MVP Builder

- Every project has a stage: idea → research → specification → build → preview → owner review → validated/rejected.
- A stage is advanced only by an event with evidence: a link to a PR, commit, CI run or artifact.
- Only you set the final stages (`validated` / `rejected`).
- **A/B Tester** is only a specification for now (PR #347, analysis in #348). Comparing two audiences is a "segment comparison", not a randomized A/B test.

## 7. MyCast

- Your personal episode arrives in Telegram before 06:00 Kyiv time. More in the "MyCast for the owner" guide.
- The listener website: `mycast.pro`. Sign-in is through Telegram; Google is needed only for the calendar.
- Referrals: a friend gets +7 days right away. The person who invited them gets +7 only after the friend's first real episode.

## 8. Rules that cannot be bypassed

- Publishing, spending and any messages to third parties require your explicit approval.
- Paid model calls are never turned on automatically. Content Brain has a budget limit.
- Secrets are never written in chat, never land in the repository and are never shown on screen. They are stored in Render or in an encrypted store (vault).
- Nobody pushes to `main` directly: only through a PR with green CI.
- Tests must not be disabled or weakened to get green CI.
- Metrics, publication receipts and deploy success must never be made up. Where there is no data, it says "no data".

## 9. Where to look if something is wrong

| Question | Where the answer is |
|---|---|
| What are the agents doing right now? | Owner console → Telegram tasks. There are also Agents and Workers |
| Why did a task fail? | The Telegram message (it has the direct reason), the error center |
| What changed in the code? | GitHub → PRs and `DECISIONS.md` |
| What is in the plan? | Build Progress (`ROADMAP.md`) |
| How much was spent on Actions? | GitHub → Billing. CI runs only on PRs and `main`, screenshots only on `main` |
