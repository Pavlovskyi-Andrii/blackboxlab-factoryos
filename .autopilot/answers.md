# Owner answers

Append owner answers to blocked roadmap tasks here.

Format:

```
## T-000
Owner answer or supplied non-secret decision.
```

Never paste secret values into this file. Secrets belong in the runtime secret store/environment only.

## Standing owner grants (2026-10-30)
Owner granted Claude, permanently and without asking each time:
1. Write code, create branches and PRs, maintain ROADMAP.md and assign Owner lanes.
2. Merge Claude's own PRs into `main` once CI is green on the current head (this is the normal CI-gated Render deploy path).
3. On the EC2 worker host: read logs/state, update the worker checkout (`git pull`), and restart the worker/supervisor services when they are stuck.
4. Close stale PRs and Issues with a comment explaining why.
Still owner-only (unchanged safety invariants): secrets/tokens, any paid service or API, real social publishing, deleting data or irreversible AWS/Render infrastructure changes, Telegram pairing (T-506), Metricool credentials (T-520).
