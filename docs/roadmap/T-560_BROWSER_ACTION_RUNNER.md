# T-560 — Browser Action Runner (Surfer/Runner)

## Purpose

Add a provider-neutral browser automation worker for FactoryOS when an official API or connector is unavailable or insufficient.

This worker is not Relay. Relay remains the owner-facing project/status surface. Browser Action Runner is an execution worker that performs bounded browser actions and returns evidence.

## Operating rule

1. Prefer official APIs/connectors first.
2. Use Browser Action Runner only as a fallback for UI-only workflows.
3. Never store plaintext passwords, session cookies, recovery codes, access tokens or 2FA secrets in Git, ROADMAP, logs, artifacts or normal database fields.
4. Credential inputs are opaque credential_ref / session_ref identifiers resolved by a vault/session provider at execution time.
5. A spreadsheet may hold only an account alias / credential reference. It must not be treated as a password vault.
6. CAPTCHA, unexpected 2FA, security challenge, account-lock or consent screens stop the run and request human takeover. Do not bypass anti-bot or security controls.
7. Every irreversible external action (publish/post/send/delete/purchase/submit) is fail-closed and requires the existing FactoryOS human-approval gate bound to the exact immutable action snapshot.
8. Reusable browser sessions must be isolated per workspace + provider + account binding.

## Initial architecture

FactoryOS job -> BrowserActionPlan -> policy validator -> session/vault resolver -> browser executor adapter -> evidence collector -> BrowserActionResult -> Worker Results / Trace Viewer

The executor must be adapter-based so the implementation can later support Playwright, a remote browser provider, TinyFish-style browser execution, or another compatible runtime without changing the plan/result contracts.

## Core contracts

### BrowserActionPlan

Required fields:
- plan_id
- workspace_id
- provider / site
- account_binding_id
- credential_ref or session_ref (opaque only)
- ordered bounded steps
- action_class: read | draft | upload | publish | send | destructive
- immutable payload hash
- approval requirement + approval snapshot ID when applicable
- timeout / max steps / max retries

Representative bounded steps:
- navigate
- click
- fill
- select
- upload
- wait_for
- extract
- screenshot
- submit (approval-gated)

### BrowserActionResult

Return only factual execution evidence:
- status: planned | running | waiting_human | done | blocked | failed
- completed step count
- redacted action log
- final URL
- screenshot/artifact references when available
- external receipt/URL only if actually observed
- blocker reason
- timestamps / duration
- executor/provider identity

Never fabricate success, receipts, IDs, metrics or screenshots.

## Social workflow target

The first practical recipes should support draft-mode flows for:
- X/Twitter web
- Instagram web
- Telegram web/channel UI when API use is not suitable
- generic CMS / website form

A social recipe may log in/reuse a session, navigate, attach media, fill caption/text and prepare the final submit step. The actual publish click remains approval-gated.

## Account portability

The runner must integrate with the existing workspace/provider binding model from T-550:
- disconnect one account without deleting FactoryOS history;
- replace an account binding cleanly;
- prevent cross-workspace session reuse;
- preserve audit history using account binding IDs, not secrets.

## Human takeover

When a challenge appears:
- persist a redacted checkpoint;
- mark waiting_human;
- expose the exact site + step + reason;
- resume only from an owner-authorized checkpoint;
- never ask the worker to read or print a one-time code from secret storage.

## Security / privacy invariants

- redact password/token/cookie/authorization fields from logs and screenshots metadata;
- prohibit arbitrary shell/file-system commands inside browser plans;
- enforce allowlisted domains per recipe;
- enforce max step count and timeout;
- preserve signed-media/auth boundaries;
- no background publish after approval expires or payload changes;
- payload hash mismatch invalidates approval.

## MVP sequence

### T-560-A — Browser runner contracts + policy engine
Pure deterministic contracts, validation, redaction and mocked executor. No real browser and no credentials.

### T-560-B — Session/vault abstraction + human takeover
Opaque secret/session references, workspace isolation, checkpoint/resume state. Still no real social publishing.

### T-560-C — Real browser executor + generic recipe
Playwright or equivalent adapter behind the interface, domain allowlist, evidence capture, deterministic test fixture.

### T-560-D — Social draft recipes
X/Instagram/Telegram-web draft preparation with final submit fenced by approval.

### T-560-E — Runner observability
Worker Results + Trace Viewer show plan, steps, checkpoint, screenshots/artifacts and final factual result.

## Non-goals for MVP

- CAPTCHA bypass
- stealth/anti-detection tooling
- automated account creation
- scraping private data without authorization
- automatic irreversible publishing
- storing credentials in spreadsheets or Git
- replacing official APIs when a stable API already covers the task
