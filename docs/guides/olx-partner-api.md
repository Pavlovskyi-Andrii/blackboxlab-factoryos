# OLX Partner API — what FactoryOS uses (T-701)

Read on 2026-11-18. `developer.olx.ua` answered both the cloud session and the FactoryOS server browser with a
CloudFront `403 Request blocked`, so the text was read from the Internet Archive copy of the same pages
(`web.archive.org/web/2025/...`). The live API host (`www.olx.ua/api/...`) was **not** called. Re-check details against
the live docs once the owner has partner access (T-701-H).

Sources:

- [S1] API reference "OLX Partner API (2.0)": https://developer.olx.ua/api/doc
  (archive: https://web.archive.org/web/2025/https://developer.olx.ua/api/doc). OpenAPI file linked there:
  https://developer.olx.ua/swagger/v2/partner_api.yaml (not read: same CloudFront block).
- [S2] "Отримання доступу до API": https://developer.olx.ua/ua/articles/getting-access-to-api
- [S3] FAQ: https://developer.olx.ua/ua/articles/faq
- Not read: terms https://developer.olx.ua/ua/terms-and-conditions (blocked) — see open questions.

## Partner registration and approval [S2, S3]

1. Sign in to the Developer Portal with an existing OLX account (the portal itself uses OLX OAuth).
2. "Підключити додаток" (connect an application) and fill in the form. The app shows "Очікується підтвердження"
   (awaiting confirmation) while OLX reviews it.
3. OLX e-mails the decision; on success the portal shows the **Client ID** and **Client Secret**.
4. Callback URL: "Ваші додатки" → "Редагувати додаток" → "Переспрямувати URL". Several URLs may be listed, separated by
   spaces; avoid `&` and `#` [S1, S3]. FactoryOS uses `https://blackboxlab-factoryos.onrender.com/api/oauth/olx/callback`.

The public pages do **not** say what the review checks (business account, company data, volume, website). That is
open question 1.

Other facts: one client_id/secret manages adverts of one country only (UA here) [S3 #8]; there is **no test
environment** — tests use a real (possibly separate) OLX account [S3 #9]; the API manages only adverts of the
authorised account [S3 #6].

## Authentication: OAuth 2.0 [S1 "Authentication"]

| Item | Value |
|---|---|
| Authorize URL | `https://www.olx.ua/oauth/authorize/?client_id=…&response_type=code&state=…&scope=read+write+v2&redirect_uri=…` |
| Token URL | `POST https://www.olx.ua/api/open/oauth/token` |
| Grant types | `authorization_code` (user context: adverts, messages), `client_credentials` (config data only: categories, cities; cannot add adverts), `refresh_token` |
| Scopes | `v2`, `read`, `write` (default `v2 read write`; an app has a closed list of allowed scopes) |
| Code lifetime | 10 minutes (troubleshooting, "Authorization code doesn't exist") |
| Access token | `expires_in` 86400 s (24 h), `token_type: bearer` |
| Refresh token | valid 30 days (2592000 s), may rotate on refresh ("a new refresh token each day"); unused for a month → user must re-authorise |
| `redirect_uri` | optional with one callback URL; if sent in the authorize step it is **mandatory** in the code exchange |
| Revoke endpoint | **none documented** |

Token request fields are shown as a JSON-looking object (`grant_type`, `client_id`, `client_secret`, `code`, `scope`,
`redirect_uri` / `refresh_token`). The docs do not state the content type; FactoryOS sends
`application/x-www-form-urlencoded`, the OAuth 2.0 standard (RFC 6749 §4.1.3), for both grant types (DECISIONS T-701). Refreshing a still-valid access token returns the same token.

## API calls [S1]

Base: `https://www.olx.ua/api/partner`. Every call: `Authorization: Bearer <token>` and **`Version: 2.0`** (required;
missing → 400 "Missing required 'Version' header"). `Accept-Language: uk|ru` switches language in Ukraine. Send
`Content-Type: application/json` only on POST/PUT (on GET it causes 400, FAQ #2).

| Purpose | Method + path | Used by FactoryOS |
|---|---|---|
| Current user | `GET /users/me` (id, name, email, is_business…) | yes, account label after connect |
| Regions / cities / districts | `GET /regions`, `/regions/{id}`, `/cities?offset&limit` (default 1000), `/cities/{id}`, `/cities/{id}/districts`, `/districts`, `/districts/{id}` | yes (read-only pickers) |
| Location by coordinates | `GET /locations?latitude&longitude` | no |
| Languages / currencies | `GET /languages`, `GET /currencies` | no |
| Categories | `GET /categories?parent_id`, `GET /categories/{id}` (`photos_limit`, `is_leaf`), `GET /categories/suggestion?q` (q ≥ 3 chars) | yes |
| Category attributes | `GET /categories/{id}/attributes` (code, label, unit, validation, values) | yes |
| List own adverts | `GET /adverts?offset&limit&external_id&category_ids` | yes, `external_id` lookup for unknown outcomes |
| Create advert | `POST /adverts` | yes (after owner approval) |
| Get advert | `GET /adverts/{id}` | yes (status refresh) |
| Update advert | `PUT /adverts/{id}` (full body) | **not yet** — TODO, would need re-approval |
| Delete advert | `DELETE /adverts/{id}` (only when not active) | no |
| Commands | `POST /adverts/{id}/commands` `{"command": "activate"\|"deactivate"\|"finish"\|"extend", "is_success": bool}` (`is_success` required for deactivate; `extend` not available in UA) | `deactivate` only |
| Statistics | `GET /adverts/{id}/statistics` (advert_views, phone_views, users_observing) | no |
| Moderation reason | `GET /adverts/{id}/moderation-reason` | no (TODO) |
| Threads / messages | `GET /threads`, `GET/POST /threads/{id}/messages`, `POST /threads/{id}/commands` | no |
| **Paid**: packets, paid features, payments | `/packets`, `/zones`, `/users/me/packets`, `/adverts/{id}/packets`, `/paid-features`, `/adverts/{id}/paid-features`, `/users/me/account-balance`, `/users/me/billing` | **never** (no paid calls without owner approval) |

### Create advert body

Required: `title`, `description`, `category_id` (leaf category), `advertiser_type` (`private`|`business`),
`contact` (`name`, `phone`), `location` (`city_id`, optional `district_id`, `latitude`, `longitude`), `attributes`
(array of `{code, value}` only; required ones per category). Optional: `images` (array of `{url}` — OLX downloads
public URLs; "Remote file not exists" if unreachable; count limited by the category's `photos_limit`), `price`
(`value`, `currency`, `negotiable`, `trade`, `budget`), `salary` (jobs), `external_id`, `external_url` (jobs in PL
only), `courier` (not UA), `auto_extend_enabled`.

Validation rules (documented): title 16–70 characters; description 80–9000; no character from
`! ? . , - = + # % & @ * _ > < : ( ) |` three times in a row; capital letters ≤ 50 % of the text; no e-mail, www
address or phone number in title/description. Extra unknown fields → 400 "Error while decoding JSON data".

### Advert lifecycle and statuses

POST returns the advert. `new` → OLX moderation (usually seconds) → `active` until `valid_to`. `limited` = the free
limit for the category is used up: a **paid packet** must be bought and the advert activated (FactoryOS stops there
and shows it to the owner). Other statuses: `removed_by_user`, `outdated`, `unconfirmed`, `unpaid`, `moderated`,
`blocked`, `disabled`, `removed_by_moderator`. Refresh/extend at most once per 14 days (country-dependent).

### Errors and limits

Standard HTTP codes (400, 401, 403, 404, 406, 415, 429, 500). Validation errors:
`{"error": {"status": 400, "title", "detail", "validation": [{"field", "title", "detail"}]}}`. OAuth errors use
`{"error": "invalid_grant", "error_description": …}`. Rate limit: max **4500 requests per 5 minutes per IP**; above that
the IP is blocked for 30 minutes (FAQ #11). Unsupported API version → 404.

## How FactoryOS maps it (olx_publisher.py)

- OAuth provider `olx` in `oauth_framework.py`, env `FACTORY_OAUTH_OLX_CLIENT_ID` / `FACTORY_OAUTH_OLX_CLIENT_SECRET`;
  tokens only in the encrypted token vault (needs `FACTORY_VAULT_KEY`, T-560-G). Refresh before each write; a
  rotated refresh token is stored back. Expired refresh token → `olx_reconnect_required`.
- `FACTORY_OLX_ENABLED=1` turns OLX writes on (publish, deactivate; off by default). Read-only reference/status calls
  with the owner's token work while it is off. Approval is bound to the connected OLX account. `FACTORY_OLX_LANGUAGE=uk|ru` (default `uk`).
- Draft → owner approval (SHA-256 of the exact advert JSON) → one `POST /adverts` with `external_id` = draft id.
  Timeout / 5xx / reply without id → «unknown outcome»: no resend; «Проверить на OLX» does a read-only
  `GET /adverts?external_id=…`, or the owner confirms by hand.
- Owner page: `/static/olx/index.html` (RU/UK/EN).
- For T-702: `olx_publisher.publish_approved(store=…, flow=…, workspace=…, draft_id=…)` keeps every fence.

## Open questions / TODO

1. What OLX's app review requires (business account? company data? website?) — not in public docs; the owner sees it in
   the portal form (T-701-H).
2. Partner terms (`/terms-and-conditions`) — not readable from here; the owner should read them before approval.
3. No documented token revoke: «Отключить» only deletes the tokens in FactoryOS; access stays valid until it expires
   (24 h access / 30 days refresh) unless revoked in the OLX account.
4. Token request content type (JSON vs form) is not stated; form encoding (RFC 6749) is used. If the first connect
   fails with `exchange_failed`, try JSON.
5. `PUT /adverts/{id}` (edit a live advert), moderation reason, statistics and messages are not built yet.
6. Image hosting: OLX downloads images from public URLs. FactoryOS media is signed/private; the owner pastes public
   https links for now.
