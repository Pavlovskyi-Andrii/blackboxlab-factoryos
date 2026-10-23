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

## 2026-10-23 — Claude Pro as a FactoryOS worker

- **Decision:** connect Claude Code Pro to FactoryOS through a trusted runner heartbeat/wrapper rather than putting the owner's Anthropic API key into the web service.
  **Reason:** this preserves subscription billing, avoids accidental PAYG API spend, keeps Claude credentials on the machine that is actually running Claude Code, and gives FactoryOS a measurable online/offline worker state.

- **Decision:** move Telegram pairing and Claude Pro setup into the main Connections rail.
  **Reason:** service setup belongs next to YouTube, Instagram, TikTok and other integrations; Build Progress should show execution state, not hide connection setup.
