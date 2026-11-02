# FactoryOS autonomous build mode

You are implementing FactoryOS without conversational supervision. Do not ask "continue?" and do not wait for approval for ordinary reversible engineering choices.

## Coordination with ChatGPT (owner agreement)

Before delegating work to ChatGPT, reviewing a ChatGPT PR, changing a task's `Owner:`, or planning a cross-agent handoff, **read `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`**. This file distinguishes owner-approved operating rules from an **open question** about AI-generated technical tasks; do not interpret that question as owner authorization to change product priorities. Use FactoryOS Relay for future agent messages, not GitHub as the operational inbox. The live two-way connection is **not verified** (Issue #94). Preserve explicit claims/ownership and do not duplicate another agent's active task.

## Execution loop

1. Read `ROADMAP.md`.
2. Take the first unchecked task that is not marked `[HUMAN]`.
3. Read `.autopilot/answers.md` for prior owner answers.
4. Inspect current code and existing behavior before editing.
5. Make the smallest safe implementation that satisfies the task's DONE criterion.
6. Record non-obvious reversible choices in `DECISIONS.md`.
7. Run the task's DONE command plus the relevant FactoryOS regression checks.
8. Fix failures, up to three implementation attempts.
9. When green, mark only that task `[x]`, commit it with the task ID in the subject, and write `.autopilot/status.json`.

## Status contract

Write:

```json
{
  "task": "T-502",
  "status": "done | blocked | failed",
  "summary": "concise factual summary",
  "need": "what the owner must provide, only when blocked",
  "checks": ["commands actually run"],
  "commit": "commit sha when done"
}
```

## Human escalation

Block only when the task genuinely requires one of:
- a secret or credential that is not already configured;
- payment or a paid-provider confirmation;
- access to an external account;
- explicit approval of real publishing;
- an irreversible product/business choice that cannot be safely defaulted.

Do not block for naming, refactoring, layout, implementation detail, or other reversible engineering decisions. Make a reasonable choice and record it in `DECISIONS.md`.

## Safety invariants

- Never push directly to `main` or `master`.
- Never force-push or delete branches.
- Never weaken the human approval gate before publishing.
- Never enable paid provider calls automatically.
- Never read, print, commit, rewrite, or expose `.env` or secret values.
- Never edit production environment variables.
- Never trigger a production deploy directly; production changes reach Render only through the normal CI-gated main-branch flow.
- Never delete or weaken tests merely to obtain a green run.
- Preserve authentication and signed-media boundaries.
- Preserve provider budget limits and idempotency fences.
- Do not fabricate provider receipts, metrics, media success, CI success, or deployment success.

## Default verification

For Python/backend changes:

```bash
python -m py_compile app.py smoke_tests.py media_finisher_worker/app.py media_finisher_worker/test_planner.py
python -m media_finisher_worker.test_planner
DATA_DIR=/tmp/factoryos-autopilot FACTORY_PASSWORD="" FACTORY_LLM_API_KEY="" python smoke_tests.py
```

For dashboard changes also validate the inline JavaScript with the same extraction + `node --check` pattern used by `.github/workflows/ci.yml`.

One roadmap task = one focused commit.
