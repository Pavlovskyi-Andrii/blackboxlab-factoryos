# "Your tasks": the owner desk

This is where the jobs only the owner can do are collected. Agents neither take them nor work around them.

## What it is

- The "Your tasks" block is a list of step-by-step runbooks for tasks marked `[HUMAN]` in `ROADMAP.md`.
- It currently holds 21 runbooks, for example T-506 (pair the Telegram bot), T-605 (Gemini key in Render), T-521 (first real post with your approval), T-645-H (approve the MyCast demo episodes).
- A CI test makes sure every open `[HUMAN]` task in `ROADMAP.md` has a runbook.

## What a card contains

- The task number and title, a status and a short fact line.
- A short note on why it is needed and the estimated time ("Time").
- Steps. Each step has what to do, "How to check", and "If something goes wrong" (ready answers for known errors).
- "Done when": the sign that the task counts as done.

## Statuses

| Status | Meaning |
|---|---|
| "To do" | the task is waiting for you |
| "Check" | a fact needs comparing, for example the version in production |
| "Waiting" | another task comes first (for example T-592-H waits for T-591-H) |
| "Optional" | you may skip it |
| "Done" | the server sees that it is done |
| "Unknown" | the server has no data to check it |

The fact line comes from what the server already knows. Examples: `gemini_key_ok` means "The Gemini key is in Render", `gemini_key_missing` means there is no key yet; `tg_paired` means Telegram is connected; for T-591-H it is the `/proof` verdict for the newest Telegram ticket. The server calls no external provider for this.

## How to complete a task

1. Open a card with the status "To do" (the first such card opens by itself).
2. Follow the steps in order in the external service: Render, Telegram, Google AI Studio, GitHub and so on.
3. After each step, check the result against "How to check".
4. The status changes by itself once the server sees the fact. For example, T-605 becomes "Done" when the server sees `FACTORY_GEMINI_API_KEY` after the Render deploy.
5. There is no "mark as done" button: a status cannot be set by hand.

## If something is unclear

- Select text in a step or press "Ask about this step", then "Send".
- The Claude worker on EC2 picks up the question and answers between its tasks, only reading the repository: usually within minutes, sometimes up to an hour.
- The answer appears under the card, and Telegram sends a notice.
- Do not paste tokens or passwords: the server cuts out text that looks like a secret. At most 20 questions can wait at once.

## Why agents do not do this themselves

Under the project rules (`CLAUDE.md`) an agent stops and hands the job to the owner when it needs:

- a secret or key that is not configured yet (keys go only into Render, AWS or a terminal);
- a payment or a paid-provider confirmation;
- access to an external account (Google, YouTube, GitHub, Telegram);
- explicit approval of a real publication;
- an irreversible product or business decision.

Agents are also forbidden to change production environment variables or to turn on paid calls.

## Where to find it

- Main dashboard → "Workers" in the menu → the "Worker / Delegation Control Center" window → the "Your tasks" block at the very top.
- Only the owner sees this block. The same `[HUMAN]` tasks also appear on the "Team tasks" page in the owner tile.

## Limits

- Not every card has a live check: some have a fixed status ("To do", "Optional") or "Unknown".
- The runbook text is static: agents change it through a normal PR.
- The `[x]` mark in `ROADMAP.md` is set separately, by a commit to the repository, not from this block.
