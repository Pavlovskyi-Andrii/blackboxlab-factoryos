# FactoryOS Relay Telegram bot command guide

A reference guide for the owner covering every command of the FactoryOS Relay Telegram bot.

## Command list

### /start
- **What it does:** Starts the bot and shows the initial greeting with help.
- **Example:** `/start`

### /help
- **What it does:** Shows full help for all bot commands.
- **Example:** `/help`

### /pair
- **What it does:** Links this Telegram chat to FactoryOS using a one-time code. FactoryOS shows the code when you start pairing; without a code the command does nothing. `/start CODE` works the same way.
- **Example:** `/pair 123456` (replace 123456 with your code)

### /status
- **What it does:** Shows the bot's current operating status and the state of the task queue and workers.
- **Example:** `/status`

### /tasks
- **What it does:** Lists all active tasks (queued, in progress, needing attention).
- **Example:** `/tasks`

### /relay
- **What it does:** Shows a general overview of the Relay system and active tasks.
- **Example:** `/relay`

### /roadmap
- **What it does:** Shows the current Roadmap and its tasks.
- **Example:** `/roadmap`

### /task
- **What it does:** Opens a task card by its identifier (ID).
- **Example:** `/task R-0001`

### /history
- **What it does:** Shows the history of events, status changes and actions in Relay and GitHub.
- **Example:** `/history`

### /github
- **What it does:** Shows the status of the GitHub repository, open PRs and CI check results.
- **Example:** `/github`

### /issue
- **What it does:** Puts an open GitHub Issue into the worker's execution queue.
- **Example:** `/issue 41`

### /battles
- **What it does:** Shows the list and status of test runs (Battle Runs).
- **Example:** `/battles`

### /battle
- **What it does:** Shows detailed information about a specific Battle Run.
- **Example:** `/battle battle_3f9c2a1b7d4e5f60` (take the ID from the `/battles` list)

### /workers
- **What it does:** Shows the status and state of the workers (Claude, ChatGPT, Gemini) and operators.
- **Example:** `/workers`

### /operators
- **What it does:** Shows the state and status of the available operator lines.
- **Example:** `/operators`

### /new
- **What it does:** Creates a new task in Relay and sends it to a worker's queue.
- **Example:** `/new Fix the error when loading data`

### /work
- **What it does:** Moves a task to the "In progress" status (`in progress`).
- **Example:** `/work R-0001`

### /done
- **What it does:** Completes a task and moves it to the "Done" status (`done`).
- **Example:** `/done R-0001`

### /need
- **What it does:** Marks a task as needing the owner's attention (need_you).
- **Example:** `/need R-0001`

### /inbox
- **What it does:** Returns a task to its initial "Inbox" status.
- **Example:** `/inbox R-0001`
