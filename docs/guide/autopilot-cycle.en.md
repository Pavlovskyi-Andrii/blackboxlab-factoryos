# Autopilot and Cycle Control: how it works

> Checked against the code and `ROADMAP.md` (T-646) on 2026-11-16. If the dashboard shows something else, the dashboard is right.

## What it is

**Autopilot** is the Cycle Control screen under «Automation & team» → «Autopilot» in the menu. It carries one idea through the content factory: from fresh material to a finished short video, and back to a lesson for the next idea.

**A cycle** is one such trip of one idea. Agents pass the work along; you decide at the approval step.

## How it works, step by step

| Step | Who acts | What happens |
|---|---|---|
| 1. Signals | agent | Collects fresh material: news, links, your notes |
| 2. Idea | agent | Turns signals into ideas, checks facts, picks the strongest |
| 3. Production | agent | Script, hook, captions, voice: a ready content package |
| 4. Your approval | you | The factory stops and waits for you |
| 5. Publishing | you | You choose the platform and press publish yourself |
| 6. Real numbers | you + agent | Real views and retention, no invented numbers |
| 7. Lesson | agent | Compares with earlier videos and suggests one change |

Agents do steps 1–3 on their own after you press «Run to review». After that the cycle always waits for your action.

## How to set a goal

In the «Start a new cycle» form choose where to start: from the newest signals or from a ready idea in Content Brain. Then you can set a target (all optional):

- **Brand** — agents get its Master Brief.
- **Topic** — new signals that mention it are used. If none do, all new signals are used and the card says so.
- **Platform** and **audience** — go into the writing brief. You still choose the real platform when publishing.

The target is shown on every card. «Change target» is available until production starts.

## Stop and continue

- **«Stop»** — for a cycle in ready, running or failed state. A running cycle stops at the next handoff between steps; an AI call already in progress is not cut off. Nothing is deleted.
- **«Resume»** — returns a stopped cycle to work. If it has not reached approval yet, press «Run to review» again.
- **«Retry»** — after an error, continues from the failed step; finished steps are not repeated.
- **«Sync state»** — re-reads the job, publishing and metrics state for free.

## What «human approval» means

Nothing is published without your «yes». The cycle stops at step 4, and only you approve or reject the package. Publishing is a separate button that you press yourself.

## Budgets and limits

- **Demo mode** (no AI model connected): no paid calls. It cannot invent ideas from signals, so start from a ready idea.
- **With a paid model** you see a cost ceiling before each run and must confirm it. Without confirmation the run does not start.
- Hard limits still apply: per day `FACTORY_DAILY_BUDGET_USD` and per job `FACTORY_JOB_BUDGET_USD` (code defaults 10 and 3 USD).

## Where to see progress

- The cycle card: a 7-step bar, a «What to do now» box, the target, buttons.
- «Step results» open the real signals, idea, job, publishing and metrics.
- «Event history» is the cycle log. At the top there is a collapsible «How does Autopilot work?» block.

## Limits

- Creating a cycle starts nothing by itself: agents start only when you press the button.
- You enter the metrics yourself unless an analytics sync is connected.
- Do not confuse this with the `autopilot/` folder: that is a separate EC2 worker that writes code from `ROADMAP.md`. It has its own pause / resume / retry controls (`autopilot/control.py`) and does not publish content.
