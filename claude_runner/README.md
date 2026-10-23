# FactoryOS Claude Code Pro Runner

This runner connects a trusted machine running the native Claude Code CLI to FactoryOS.

## 1. Install and sign in to Claude Code

Install Claude Code using Anthropic's official instructions. Then run `claude`, use `/login`, and choose the Claude account with your Pro subscription. Run `/status` inside Claude Code and confirm the subscription account is active.

Important: keep `ANTHROPIC_API_KEY` unset if you want Claude Code to use your Pro subscription instead of separately billed API usage.

## 2. Configure FactoryOS connection

Set these environment variables:

- `FACTORY_URL` — your FactoryOS public URL.
- `FACTORY_CLAUDE_RUNNER_TOKEN` — copy it from FactoryOS Connections → Claude Code Pro.
- `FACTORY_REPO` — local path to the Blackbox Lab FactoryOS Git repository.

## 3. Verify once

Run:

```
python claude_runner/runner.py --verify --once
```

This performs one tiny Claude Code request only to verify that the native CLI can authenticate. If no `ANTHROPIC_API_KEY` is present and the call succeeds, FactoryOS reports `subscription_verified`.

## 4. Keep the runner online

Run:

```
python claude_runner/runner.py
```

The runner currently provides connection/auth/heartbeat state. Task claim/delegation is the next T-508 layer and will keep the same safety rules: non-main branch, bounded turns, tests/evidence, no direct production deploy.

If FactoryOS still shows the runner as offline, keep `runner.py` running continuously; the online state intentionally expires when heartbeats stop.
