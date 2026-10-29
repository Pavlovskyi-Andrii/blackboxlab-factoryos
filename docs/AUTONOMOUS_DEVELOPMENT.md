# FactoryOS Autonomous Development — operating rules

## Goal
Keep FactoryOS development moving between owner conversations through a separately running, explicitly configured Claude Worker on existing infrastructure. ChatGPT conversations are for task definition, review and status, not a claim of continuous execution.

## Pipeline
Owner request → scoped GitHub Issue with acceptance criteria → authorized, idempotent Relay intake → queued ticket → Claude Worker claims ticket → branch/commits/tests → draft PR → CI → review/approval → merge/deploy according to existing policy.

## Source of truth
GitHub Issues: scope, priorities, acceptance criteria, PR references. Relay: queue, assignment, worker events, timestamps, blockers, heartbeat. Worker must report claimed, running, step, blocked, PR-created, completed/failed with ticket and issue identifiers. Site and Telegram read the same events. No invented completion percentages: only objective metrics, otherwise named stage and last heartbeat.

## Autonomy policy
For safe, reversible implementation within approved scope, diagnose and fix without waiting for repeated owner prompts. Report in present tense: what is being done, actual evidence, next step, blocker. Do not claim work is happening while no executor is running. Avoid duplicate ticket creation and parallel conflicting tasks. Keep changes on feature branches and PRs, with CI and review before merge. No unauthorized external publishing or bypassing owner authentication.

## Cost and security guardrails
Use existing EC2/Render/GitHub and existing Claude subscription only when its usage mode is allowed; never turn on metered API billing, create paid infrastructure, or incur additional charges without separate explicit owner approval. Do not place passwords, session cookies or tokens in GitHub Issues, logs, or chat. Enforce authorization and least privilege. Stop and surface blockers when a safe action cannot proceed.

## First milestone
1. Finish PR #60 GitHub Issue → Relay intake with authorization, deduplication and tests.
2. Enqueue T-575 / Issue #54 via authorized path and verify claimed → running → event logs.
3. Validate objective progress and last activity for T-576 / #55 and telemetry for T-577 / #56.
4. Add website and Telegram read-only status from Relay events.
5. Verify unattended restart, queue persistence, failure recovery and notification before calling the builder autonomous.

## Important distinction
An hourly ChatGPT monitoring task can report changes but is not a continuously running coding agent. The persistent worker must be independently deployed and verified on the existing server. This document records desired behavior, not proof that unattended execution is already enabled.
