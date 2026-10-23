# FactoryOS Decision Log

Autonomous workers record reversible engineering decisions here so the owner can review them in batches.

## 2026-10-23 — Autopilot architecture

- **Decision:** use the existing FactoryOS repository, CI, Factory Builder and Render deployment path instead of creating a second independent product-control system.
  **Reason:** FactoryOS already has task state, Builder dispatch, CI, deployment visibility and safety gates.

- **Decision:** keep autonomous code work on a non-main branch and let the normal CI-gated main flow remain the only production path.
  **Reason:** this preserves rollback/review boundaries and prevents an unattended agent from deploying directly.

- **Decision:** make Telegram optional rather than a hard runtime dependency.
  **Reason:** the repository can operate safely without Telegram; credentials are owner-controlled and therefore a HUMAN configuration step.

- **Decision:** represent unavoidable owner actions explicitly as `[HUMAN]` roadmap tasks.
  **Reason:** the agent should skip real blockers instead of stopping on ordinary implementation questions.

## 2026-10-23 — Owner interrupt channel and Claude auth

- **Decision:** pair Telegram with a one-time code and persist only the paired chat ID in an ignored runtime file; the bot token stays in the secret environment.
  **Reason:** this gives the owner a fast push-notification channel without putting messaging credentials or personal chat identifiers in Git.

- **Decision:** prefer Claude Code subscription OAuth for the owner's Pro plan and keep Anthropic API PAYG as an optional fallback.
  **Reason:** Claude Code is included with Pro, while an ANTHROPIC_API_KEY would switch usage to separately billed API credits.

## 2026-10-23 — Central Telegram bridge

- **Decision:** terminate Telegram pairing and owner messaging inside the existing FactoryOS Render service, with pairing state on the persistent disk and a bearer-authenticated notify/inbox bridge for Builder Autopilot.
  **Reason:** this avoids a second paid service, keeps the bot token in one secret store, and gives future autonomous runners a stable two-way owner interrupt channel.

## 2026-10-23 — Claude Code Pro connection boundary

- **Decision:** connect Claude Code Pro to FactoryOS through a trusted native Claude Code runner instead of storing Claude subscription credentials in the FactoryOS web service.
  **Reason:** Pro authentication is a native Claude Code OAuth login; keeping it on the runner preserves the subscription boundary, while FactoryOS only stores a scoped runner token and heartbeat state. API remains an optional paid fallback for truly headless 24/7 execution.
