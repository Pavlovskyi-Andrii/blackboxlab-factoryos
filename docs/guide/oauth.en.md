# OAuth connections in FactoryOS

This document describes the architecture and process of connecting external accounts (YouTube, TikTok, Instagram, HubSpot) to FactoryOS through OAuth 2.0 (T-551).

## 1. How social account connections work

Social accounts are connected using the OAuth 2.0 protocol (with PKCE, RFC 7636, for providers that support that standard):

### Step 1. Starting authorization (`OAuthFlow.start`)
- The user requests an authorization link for a provider (for example, YouTube or Instagram).
- The system checks that configuration is present (`Client ID`) and that nothing is blocking (the adapter and `TokenVault` are ready).
- A protective one-time `state` parameter is generated, plus (when PKCE is enabled) `code_verifier` / `code_challenge`.
- The user is redirected to the provider's external authorization page (`authorize_url`).

### Step 2. Authorization by the account owner
- The user approves access to the requested permissions (`scopes`) in the provider's interface.
- The provider redirects the browser to the FactoryOS `redirect_uri` (`/api/oauth/{provider}/callback`) with an authorization code (`code`) and the `state` passed earlier.

### Step 3. Completing the connection (`OAuthFlow.complete`)
- FactoryOS checks that `state` is valid and has not expired.
- The provider adapter (`OAuthAdapter`) exchanges `code` for access tokens (`access_token`, `refresh_token`).
- The tokens are saved in the vault (`TokenVault`). Secrets are never returned in public API responses.

### Step 4. Disconnecting an account (`OAuthFlow.disconnect`)
- FactoryOS attempts to revoke access (`revoke`) on the provider side and deletes the tokens locally from `TokenVault`.
- The content and publishing history in FactoryOS is kept in full.

## 2. Why the `state` parameter is needed

The `state` parameter is a random one-time token that the FactoryOS server creates when authorization starts:

- **CSRF protection**: it guarantees that the authorization callback was initiated by the current user, within the same session.
- **Context binding**: it keeps the link to the workspace (`workspace`), the provider and the requester (`subject`).
- **Security and lifetime (TTL)**:
  `state` is single-use and is deleted as soon as `consume` is called.
  It has a limited lifetime (`STATE_TTL_SECONDS = 600`, i.e. 10 minutes).
  The server keeps a limit on pending authorizations in memory (`MAX_PENDING_STATES = 200`).

## 3. What the system owner needs to do (T-551)

To enable OAuth integrations in production, the system owner must register OAuth 2.0 apps in the developer consoles of the relevant services and set environment variables.

### Setting the Redirect URI in provider consoles

In the app settings, add a Redirect URI in this format:
`https://<your-domain>/api/oauth/<provider_id>/callback`

Examples:
- Google / YouTube: `https://<your-domain>/api/oauth/youtube/callback`
- TikTok: `https://<your-domain>/api/oauth/tiktok/callback`
- Meta / Instagram: `https://<your-domain>/api/oauth/instagram/callback`
- HubSpot: `https://<your-domain>/api/oauth/hubspot/callback`

### Environment variables

The owner sets the following keys in the server environment (secrets are never stored in the repository):

- **Google / YouTube**: `FACTORY_OAUTH_GOOGLE_CLIENT_ID`, `FACTORY_OAUTH_GOOGLE_CLIENT_SECRET`
- **TikTok**: `FACTORY_OAUTH_TIKTOK_CLIENT_KEY`, `FACTORY_OAUTH_TIKTOK_CLIENT_SECRET`
- **Meta / Instagram**: `FACTORY_OAUTH_META_APP_ID`, `FACTORY_OAUTH_META_APP_SECRET`
- **HubSpot**: `FACTORY_OAUTH_HUBSPOT_CLIENT_ID`, `FACTORY_OAUTH_HUBSPOT_CLIENT_SECRET`

> **Note**: until full adapters and the encrypted token vault (T-552) are implemented, the authorization methods return the matching blocker status (`vault_unavailable`, `adapter_missing`, or `client_not_configured` if the provider keys are not set).
