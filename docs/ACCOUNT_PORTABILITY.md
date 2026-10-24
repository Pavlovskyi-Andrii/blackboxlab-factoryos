# FactoryOS Account Portability

## Goal

FactoryOS must be sellable without being tied to the original owner's social or CRM accounts. A workspace can detach an integration, keep its FactoryOS content/audit history, and later bind a different customer's account.

## What v5.3.1 implements

- Portable connection slots for Metricool, YouTube, Instagram, TikTok and HubSpot.
- A persistent `integration_accounts` metadata table keyed by `workspace_key + provider`.
- No provider tokens or secrets are returned by the connection registry.
- Owner UI actions for Connect, Disconnect and Change account.
- Disconnecting a provider preserves jobs, artifacts, approvals and analytics.
- Disconnecting Metricool disables the real Metricool publishing transport; disconnecting one social network fences only that destination.
- HubSpot appears as a CRM / Growth slot, but FactoryOS does not borrow the separate ChatGPT HubSpot OAuth grant.

## Current boundary

The deployed FactoryOS instance is still a **single production workspace**. The integration table already carries a workspace key, but jobs, artifacts, approvals, publishing queue and analytics are not yet tenant-scoped.

That means v5.3.1 is account portability, not complete SaaS multi-tenancy.

The current Metricool connection also uses server-side credentials. "Connect" can re-enable the existing configured publisher workspace, while switching to an entirely different customer account still requires provider OAuth/credential onboarding.

## Sellable target

The target flow is:

```
Customer login
  -> workspace
  -> Connect YouTube / TikTok / Instagram / HubSpot
  -> create + approve + publish content
  -> analytics + CRM attribution
  -> Disconnect all
  -> credentials revoked / detached
  -> FactoryOS project history remains in that customer's workspace
```

A second customer then gets a different workspace and separate provider credentials.

## Security invariants

1. Provider access/refresh tokens never go to browser JavaScript.
2. Tokens are never stored in Git or returned by `/api/status`.
3. OAuth callbacks must validate state and use PKCE where the provider supports it.
4. Disconnect/revoke is auditable and cannot delete content history.
5. Publishing still requires the existing human approval gate.
6. Background workers must carry an explicit workspace identity before full multi-tenancy is enabled.
7. Customer A must never be able to read or publish through Customer B's provider binding.

## Next work

See ROADMAP v5.5:

- T-551 — production OAuth applications / redirect URLs.
- T-552 — OAuth callbacks, refresh/revoke and encrypted token vault.
- T-553 — full workspace data tenancy.
- T-554 — end-to-end customer onboarding and account replacement acceptance.
