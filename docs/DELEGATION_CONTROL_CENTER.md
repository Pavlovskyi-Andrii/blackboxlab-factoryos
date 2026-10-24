# FactoryOS — Worker / Delegation Control Center

## Purpose

Give the owner one place to understand the complete delegation loop between ChatGPT/Planner and the trusted Claude Code worker without opening Termux or GitHub.

The board is operational observability, not a second source of truth. The versioned ROADMAP remains the task queue; verified delegation evidence and heartbeat data remain the execution truth.

## Screen model

### Top status strip

Show:
- Worker connection: Online / Stale / Offline.
- Subscription/auth mode: e.g. Claude Pro · subscription.
- Current branch and HEAD short SHA.
- Current task and worker stage.
- Heartbeat age and task elapsed time.
- CPU percent and memory MB when supported; otherwise “Unavailable”.
- Queue summary: Done / Running / Queued / Blocked / HUMAN.
- Remaining safe task count.

Never show worker token, OAuth token, API keys, Telegram token, raw environment variables or secret-bearing command lines.

### Left column — Planner / ChatGPT

Render the ROADMAP as an owner-readable delegation tree rather than a flat checklist.

Each task card contains:
- task ID and title;
- parent/subtask relationship;
- Planner/Source (ChatGPT, Claude, Owner, Roadmap/legacy);
- status: queued / running / done / blocked / HUMAN;
- dependency IDs;
- Goal;
- machine-checkable DONE criterion;
- queue position;
- created/planned provenance when available.

Parent tasks can collapse/expand. Example:

T-536 Worker / Delegation Control Center
  T-536-A Delegation Board API          DONE
  T-536-B Live worker telemetry         RUNNING
  T-536-C Planner hierarchy             QUEUED
  T-536-D Control Center UI             QUEUED

This is the answer to “what did ChatGPT delegate and what is still left?”

### Right column — Claude Worker

One large live worker card should answer:
- Is the worker actually connected?
- What task is it executing now?
- What stage is it in?
- How long has it been running?
- What branch/commit is it on?
- CPU/memory now?
- When was the last heartbeat?
- What was the last verified result?
- Is it blocked and what owner input is required?

Stages should be factual and coarse: syncing, idle, delegated/running, checking, committing, pushing, blocked, failed. Do not fabricate fine-grained percentages when the runner cannot prove them.

### Execution timeline

For the selected task, show factual events in chronological order:

Queued -> Picked -> Running -> Checks -> Commit -> Push -> Done

or end in Blocked / Failed.

Each evidence-bearing event may include:
- timestamp;
- check command and pass/fail;
- commit SHA;
- changed file count/list;
- duration;
- Claude-reported token/cost metadata when genuinely available;
- error/blocker summary.

Never infer a check, commit, push or cost that was not observed.

### History

Keep recent delegated task results so the owner can answer:
- what completed today;
- which task failed;
- what commit implemented it;
- which checks ran;
- what remains in the queue.

## API contract

Add an owner-safe GET /api/factory/delegation-board that combines:
- parsed ROADMAP queue + metadata;
- get_claude_code_status();
- verified recent task results;
- active runtime state;
- aggregate counts.

The endpoint must be secret-free.

ROADMAP metadata convention for new tasks:

- [ ] T-123 Title
  Planner: ChatGPT
  Parent: T-120
  Depends: T-121,T-122
  Goal: ...
  DONE: ...

Existing ROADMAP entries without these fields remain valid.

## Worker telemetry

Extend heartbeat with optional fields only:
- stage
- task_started_at
- elapsed_seconds
- head_sha
- queue_depth
- cpu_percent
- memory_mb
- worker_uptime_seconds

Termux/Linux should collect safe process telemetry. Other platforms return null rather than failing.

## Safe controls

Controls are phase 2 and must be command-oriented, authenticated and idempotent:
- Pause after current task
- Resume
- Retry blocked/failed safe task

No button may:
- force-push;
- switch to main/master;
- trigger production deploy;
- bypass HUMAN publishing approval;
- expose or edit secrets.

## Mobile

On phones, stack Planner above Worker and keep a sticky mini-status bar with:
Online · T-536-B · Running · 08:42 · 12% CPU

The timeline opens as a bottom sheet/detail view so the queue remains readable.

## Acceptance

The owner should be able to open FactoryOS and understand within ~5 seconds:
1. whether the Claude phone worker is alive;
2. what it is doing now;
3. what ChatGPT queued;
4. what was just completed and committed;
5. what comes next;
6. whether anything needs human action.
