# How the Gemini coder works

This document describes how FactoryOS processes tasks automatically with the Gemini coder.

## How it works

### 1. The `gemini` label on an Issue
- The task is marked with the `gemini` label in a GitHub Issue.
- The first line of the task description must be `Owner: Gemini`; without it the loop does not pick up the task.

### 2. The loop on EC2 (every 5 minutes)
- The worker on EC2 regularly (once every 5 minutes) checks for tasks with the `gemini` label.
- It takes the open task with the lowest number that does not yet have a `gemini/issue-N` branch. If the branch already exists, the task is skipped and is not done a second time.
- Each run makes up to 15 attempts to call the model, with a pause between them.

### 3. The FactoryOS proxy
- The worker calls the FactoryOS proxy (`/api/factory/gemini/worker/...`) and has no direct access to the Gemini API key.
- Only stable Gemini Flash models are allowed.

### 4. Creating the `gemini/issue-N` branch and a PR
- The generated code is committed to the `gemini/issue-N` branch.
- A Pull Request (PR) with the changes is opened.

### 5. Review by Claude
- The Claude model checks the prepared PR, reviews it and decides whether to merge.

## What to do if Google is overloaded

- If Google Gemini returns errors or timeouts (upstream codes 502/504): don't worry, the worker will retry automatically in the next cycle (5 minutes later).
- The free daily Gemini quota resets at midnight Pacific time (08:00 UTC). If the quota runs out in the evening, Gemini sits idle until morning; this is not a fault.
- If the API stays unavailable, you can remove the `gemini` label from the task or hand it to another agent (for example, Claude).

## Security

- The Gemini API key is stored only in the Render / FactoryOS configuration and is never passed to the EC2 worker or to the public repository.
