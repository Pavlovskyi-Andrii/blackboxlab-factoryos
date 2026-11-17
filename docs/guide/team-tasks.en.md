# Documentation: the "Team tasks" page (`Team Tasks`)

This guide is for the Owner. It describes how the "Team tasks" page is built, what the elements on it mean, the task statuses and the data sources.

## 1. Where the data comes from

The data model gathers information exclusively by reading the following sources:

#### GitHub API

- **Issues**: repository tasks. The executor (agent) is taken from the first line of the description (`Owner: Claude`, `Owner: ChatGPT`, `Owner: Gemini`).
- **Pull Requests**: merge requests. The executor is taken from the branch prefix (`claude/`, `chatgpt/`, `gemini/`).
- **Check Runs (CI)**: statuses of automated tests and CI checks on the head commits of open PRs.

#### EC2 snapshot / agent lanes (Lanes / Heartbeat)

- Agent activity status (online/offline) and the time of the last "pulse" (`heartbeat_age_seconds`).

#### ROADMAP.md

- Tasks marked `[HUMAN]` that are waiting for the Owner to act.

#### Owner Desk (the Owner's decision cards)

- Decision cards that explain the steps to unblock or approve tasks.

## 2. What the agent tiles mean

The page has a tile for each agent (**Claude**, **ChatGPT**, **Gemini**) and one for the **Owner**.

Each tile contains:
- **Online status indicator**: shows whether the agent is active right now, based on the heartbeat from EC2.
- **Current task (Current)**: the active task in progress (`in_progress`, `review`, `ci_failed`).
- **Next task (Next)**: the first task in the queue (`queued`).
- **Last completed (Last Done)**: a recently completed task (`done`).
- **Status counters**: the number of tasks in each state and the total number of tasks completed in the last 7 days (`done_7d`).

## 3. Task statuses and progress

The progress bar shows which stage a task is at:

| Status | Progress | Meaning |
|---|---|---|
| `queued` | 0% | The task is in the queue and has not been picked up yet. |
| `blocked` | 0% | The task is blocked by the `blocked` label, by dependencies or by an Owner condition. |
| `waiting_owner` | 0% | The task is waiting for the Owner to act (`ROADMAP [HUMAN]` or a decision card). |
| `in_progress` | 40% | An agent is working on the task (a Draft PR has been created). |
| `ci_failed` | 60% | The PR is ready or still a draft, but the CI checks failed. |
| `review` | 85% | The PR is ready and waiting for review. |
| `done` | 100% | The task is complete (the PR was merged or the Issue was closed). |

## 4. Status reasons and details (`reason`)

For precise diagnosis, a text reason is shown next to the status (below are the labels from the English dashboard UI):

- **"CI failed — the executor must fix it" (`ci_failed`)**: the CI checks in GitHub Actions failed.
- **"waiting for CI" (`ci_running`)**: the CI checks are still running on the PR commit.
- **"waiting for Claude review" (`awaiting_review`)**: the PR is ready for review by a reviewer or the owner.
- **"draft PR — work in progress" (`draft_pr`)**: a Draft PR is open and work is ongoing.
- **"waiting for Gemini (tries every 5 minutes…)" (`gemini_loop`)**: a Gemini task with the `gemini` label; the Gemini loop in GitHub Actions comes for it roughly every 5 minutes.
- **"not started yet" (`not_started`)**: the task is in the queue and work has not started.
- **"needs your action" / "your decision" (`owner_action` / `owner_decision`)**: a decision or action from the Owner is required.
- **"blocked (label)" (`blocked_label`)**: the Issue has the `blocked` label.
- **"waiting for #N — your decision" (`depends`)**: the task is waiting for linked issues/tasks to be closed (`Depends: #...`).
- **"waiting for your approval" (`owner_gate`)**: the title contains a start restriction (for example, `CONDITIONAL` or `только после`, meaning "only after").
- **"taken by another executor" (`blocked_by_other`)**: the task is blocked for another reason, for example another executor has already taken it.

## 5. Tabs and Queue Keeper

- **Agent tabs**: switch the view between all of the team's tasks and the detailed lists of individual members (Claude, ChatGPT, Gemini, Owner).
- **Queue Keeper (#231)**: determines which open tasks are ready to be picked up right now (the default target is 10 ready tasks). It is calculated only for the Claude lane. It automatically sorts tasks into the three groups listed below.

Queue Keeper groups:
- `ready`: fully ready to start;
- `blocked`: blocked (labels, unresolved `Depends:`, owner conditions);
- `in_review`: already has an open or merged PR.

## 6. The "Refresh now" button

- Task data is cached to reduce load on the GitHub API, with a refresh period of **180 seconds (TTL)**.
- Pressing **"Refresh now"** forces a fresh fetch from GitHub and the EC2 snapshot.
- To avoid exceeding API limits, there is a minimum interval between refreshes of **20 seconds** (`min_refresh`).
