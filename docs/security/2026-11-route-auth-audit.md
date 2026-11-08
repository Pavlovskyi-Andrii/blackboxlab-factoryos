# FactoryOS route authorization audit (Issue #114)

**Date:** 2026-11-08 · **Type:** read-only audit, no code changed · **Scope:** every HTTP/WebSocket route of the FastAPI app.

## Method

- Routes were enumerated at runtime: `app.py` was imported locally with `DATA_DIR=/tmp/audit FACTORY_PASSWORD=x` and `app.routes` was iterated; each endpoint was resolved to its source with `inspect.getsourcelines`. `file:line` in this document is the **decorator line** of the handler.
- Each handler body was scanned for its own checks (`role != "owner"`, `_owner_guard`, `require_owner`, `is_owner`, `_claude_worker_authorized`/`authorize_worker`, `_telegram_webhook_authorized`, `_telegram_bridge_authorized`, `_factory_mcp_authorized`, callback tokens, URL signatures, listener cookie). Every result was then read by hand.
- The middleware decision was modelled from `auth_middleware` (app.py:764–797): `public_paths` (app.py:765), `public_prefixes` (app.py:766), the token-conditional bypass flags (app.py:767–775), the viewer branch (app.py:784–788) and the member allowlist (`workspace_tenancy.MEMBER_ROUTES`, workspace_tenancy.py:100; `_workspace_member_denial`, app.py:799).
- Dynamic local checks (no network, empty provider keys, temp data dir): (1) every route called with no credentials; (2) every non-GET route called with a viewer cookie; (3) targeted probes listed per finding. Nothing was run against production, and production environment values were not inspected.
- **Snapshot caveat:** `app.py` and `relay.py` were being edited by another process during the audit (app.py grew from 12051 to 12078 lines; `relay.py` line numbers moved by ~130). Line numbers below are from the final snapshot (app.py 12078 lines, relay.py 1770 lines). Re-run the enumeration before acting on a specific line.

**Total: 240 route objects** = 234 HTTP routes defined by FactoryOS code + 4 FastAPI built-ins (`/openapi.json`, `/docs`, `/docs/oauth2-redirect`, `/redoc`) + 1 WebSocket (`/ws`) + 1 static mount (`/static`). By file: app.py 189 (incl. mount and `/ws`), relay.py 11, mycast_accounts.py 11, owner_desk.py 5, voice_settings.py 4, mycast_demo.py 4, gemini_proxy.py 3, mycast_voices.py 3, mvp_factory.py 3, mycast.py 2, FastAPI 4. `oauth_framework.py` installs no routes (it is used by app.py's `/api/oauth/*` handlers).

### Roles and credentials (what "who can call" means)

| Caller | How identified | Defined at |
|---|---|---|
| public | nothing | `public_paths` / `public_prefixes` (app.py:765–766) |
| owner | staff cookie = HMAC of `FACTORY_USER` (app.py:276), or `v2\|owner\|email` | app.py:295–314 |
| viewer | `v2\|viewer\|email` (Google viewer allowlist or `/guest` invite) | app.py:295–314; MW app.py:784 |
| member | `v3\|member\|email\|workspace` (T-553 tenancy) | app.py:302–307; allowlist workspace_tenancy.py:100 |
| Claude worker token | Bearer = `FACTORY_CLAUDE_WORKER_TOKEN`, `..._EC2`, or a paired relay token | `_claude_worker_authorized` app.py:364 |
| operator worker token | Bearer = `FACTORY_OPERATOR_WORKER_TOKEN` | app.py:372 |
| local-booster token | Bearer = `FACTORY_LOCAL_BOOSTER_TOKEN` | `_local_booster_authorized` app.py:355 |
| Telegram webhook | header `X-Telegram-Bot-Api-Secret-Token` = HMAC(bot token) | app.py:518–531 |
| Telegram bridge | Bearer = **`FACTORY_MCP_TOKEN`** | app.py:534 |
| MCP token | Bearer or `?key=` = `FACTORY_MCP_TOKEN` | app.py:1098–1112 |
| media-finisher callback | Bearer = `FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN` (falls back to shared token) | app.py:266; route app.py:10683 |
| MyCast listener | cookie `mycast_listener` = `ml1\|slug\|exp\|HMAC(FACTORY_SECRET)` | mycast_accounts.py:242–258 |
| signed media URL | `?token=` = HMAC(FACTORY_SECRET, purpose:id) | app.py:4960 (`_media_archive_signature`) |

**Middleware behaviour, important for the whole table:**

1. Token-conditional bypasses (app.py:767–775) only skip the session check **when the token is valid**. With a missing/wrong token the request falls through to normal session auth, so an **owner (and, for GET, viewer) session can also reach those paths** unless the route checks the token itself.
2. Viewer branch (app.py:784–788): viewer may use only `GET`/`HEAD`/`OPTIONS` (plus `POST /logout`); additionally `GET /api/local-booster/token`, `GET /api/local-booster/package.zip` and `GET /api/viewer-invite` are refused. Verified dynamically: every non-GET route returns `403 viewer access is read-only` for a viewer, except public/bypassed routes and `/logout`. **So a viewer can only mutate state through a GET handler that writes** (B-1, B-2).
3. The HTTP middleware does not run for the WebSocket `/ws`; that route checks the staff cookie itself (app.py:12068).
4. If `FACTORY_PASSWORD` is empty, `request_identity` returns owner for every request (app.py:316–318) — see D-6.

## Summary of findings

| ID | Pri | Route | Location | One line |
|---|---|---|---|---|
| A-1 | A (low impact) | `GET /health` | app.py:1266 (`get_real_pilot` app.py:1479) | Public, returns private real-pilot metadata (job/cycle ids, idea title, source URLs, error text, spend). |
| B-1 | B | `GET /api/factory-cycles/{cycle_id}` | app.py:9290 → app.py:8933, 8875 | Viewer GET rewrites cycle status and, with a performance snapshot, creates a new learning artifact / improvement proposal on **every** call. |
| B-2 | B | `GET /api/artifacts/{artifact_id}/media` | app.py:4997 → app.py:5113, 5144 | Viewer (and member) GET can download remote media to disk and `UPDATE artifacts`. |
| C-1 | C | `/api/claude-worker/heartbeat`, `/task-result`, `/api/operator-worker/heartbeat`, all `/api/local-booster/*` | app.py:10480–10614 | Bypassed by MW when token valid, but no own check: owner session can forge worker heartbeats/results; inconsistent with `/api/claude-worker/control` which refuses sessions. |
| C-2 | C | `POST /api/media-jobs/{media_job_id}/callback` | app.py:10787 | Own token check exists, but MW returns 401 to the external token holder first (verified). |
| C-3 | C | `/api/factory/voice/settings` (GET, POST), `/history`, `/worker/brief-deliver` | voice_settings.py:99, 110, 164, 179 | `request` bound as a required query parameter → 422 for owner and worker (500 with `?request=x`); fail-closed, but the legitimate callers cannot use them. Worker token is still enforced by MW. |
| C-4 | C | `/api/factory/telegram/bridge/notify`, `/inbox` | app.py:534, 1061, 1081 | Bridge reuses `FACTORY_MCP_TOKEN`, which the public `/mcp` connector also accepts in the URL; MCP connector holder can read the owner's Telegram inbox and message the owner. |
| C-5 | C | `POST /api/mvp-factory/{project_id}/events`, `/projects` | mvp_factory.py:249, 268 (checks :252, :197) | Route admits `member`, member allowlist blocks it at MW. |
| C-6 | C | `POST /api/oauth/{provider}/authorize` vs `GET .../callback` | workspace_tenancy.py:110; app.py:9726 | Member may start OAuth but callback is owner-only and not allowlisted for members. Needs confirmation (vault is unavailable in prod anyway). |
| C-7 | C | `public_prefixes` | app.py:766, 775 | `/api/mycast/demo`, `/api/mycast/account`, `/api/mycast/voices` have no trailing `/`: any future path beginning with these strings is public (verified: `/api/mycast/accounts-admin` → 404 instead of 401). `/register` is bypassed but has no route. |
| D-1 | D | `/mcp` | app.py:1105 | MCP token accepted as `?key=` query parameter (ends up in access logs / browser history). |
| D-2 | D | `/mcp` tools/call, agent MCP tools/call, artifact media | app.py:1255, 11022, 11039, 5009 | Raw exception text returned to caller. |
| D-3 | D | `POST /api/mycast/demo` | mycast_demo.py:218–220 | Per-client cap keyed on client-supplied `X-Forwarded-For`; one client can use the whole 30/day (spend still bounded). Needs confirmation of Render's XFF handling. |
| D-4 | D | `POST /api/mycast/voices/{voice}/sample` | mycast_voices.py:170–176 | Synchronous Gemini TTS call inside an `async def` under a lock blocks the event loop for all users while it runs (bounded: 40/day, finite voice×language set). |
| D-5 | D | `GET /api/agents/{agent}/mcp/{conn}/tools` | app.py:11011 | Viewer GET makes an outbound request to an owner-configured MCP server with the server-side credential env; no local write. |
| D-6 | D | all | app.py:316–318 | Fail-open when `FACTORY_PASSWORD` is empty (everyone is owner, incl. `GET /api/factory/claude-code/worker-token`). render.yaml declares it `sync: false`; production value needs confirmation. |
| D-7 | D | `/api/mycast/account/*` | mycast_accounts.py | No global cap on listener records (each Google/Telegram login can create one; 4000-char code each); referral bonus is farmable with throwaway accounts. Product decision; needs confirmation. |
| D-8 | D | `POST /login` | app.py:866 | No rate limit / lockout on password login. |

**Counts:** A 1 · B 2 · C 7 · D 8.

**Checked and found adequate** (evidence for the "known-intentional public routes"):

- `/mycast`, `/mycast/u/{slug}` — redirects only; slug regex `^[a-z0-9]{8}$`, no private fields beyond the share code the listener chose to save (mycast_accounts.py:441).
- `/api/mycast/demo*` — script must start with a demo intro and is length-capped (mycast_demo.py:51–68); global daily cap 30 and counter per UTC day (mycast_demo.py:30, 97, 121–150); job ids are 128-bit random; provider error text not returned. Weakness only in the per-client cap (D-3).
- `/api/mycast/voices*` — voice must be in the fixed list, text is fixed server-side, cached per voice×language, 40/day cap (mycast_voices.py:120–155). Blocking issue D-4 only.
- `/api/mycast/account*` — listener cookie is HMAC-signed with an expiry and a distinct `ml1|` payload, so it cannot be confused with a staff cookie (`v2|`, `v3|`, owner HMAC) and vice versa; cookie `httponly`, `samesite=lax`. Telegram Login Widget HMAC + 24 h freshness (mycast_accounts.py:59–76); Google ID token verified against the configured client id and `email_verified` (mycast_accounts.py:337–353). Every mutating route requires the listener cookie; Telegram sends are limited to the listener's own chat, 3/day (mycast_accounts.py:208–220). Delivery requires explicit consent. Only abuse-at-scale concern D-7.
- `/api/factory/voice/worker/brief-deliver` **does require the worker token**: no token → 401, wrong token → 401 (MW, verified); with the token the route currently fails with 422 (C-3).
- `/api/factory/voice/settings` and `/history` are owner-only in code (`is_owner` wired at app.py:709), currently unreachable for everyone (C-3).
- Token isolation verified: the local-booster token cannot reach `/api/claude-worker/*` (401) and the Claude worker token cannot reach `/api/local-booster/token` (401); the Claude worker token does not open owner routes (route checks read the cookie identity).
- Telegram webhook: secret header checked in route (app.py:968); relay actions and inbox writes only for the paired private chat (relay.py:1187, 1305; app.py:1041).
- `/media-archive/*`, `/media-source/*`: HMAC URL token checked before any file access; unauthenticated probe returns 403.
- Every unauthenticated call to a non-public route returned 401 (API) or 303 to `/login` (pages) in the local probe.

## Detailed findings

Test sketches below follow `OwnerDeskWorkerMiddlewareTest` in `test_worker_token_binding.py`: go through the full ASGI app (`asgi_get` / `asgi_post`, middleware included) with `patch.object(factory, "FACTORY_PASSWORD", "set-so-auth-is-enforced")`. Viewer cases need a cookie header; `asgi_get`/`asgi_post` would need an optional `cookie=` argument that appends `(b"cookie", f"{factory.COOKIE_NAME}={factory._role_session_token('viewer','guest')}".encode())`.

### A-1 — `GET /health` publishes private pilot data without login

- **Route:** `GET /health`, app.py:1266 (handler app.py:1267; data from `get_real_pilot`, app.py:1479).
- **Who:** anyone (`/health` is in `public_paths`, app.py:765; no check in route).
- **Why:** besides liveness, the response includes `real_pilot` with `job_id`, `cycle_id`, `idea_title`, `source_urls`, `quote_usd`, `max_usd`, `cost_usd`, `error` (free text from the stored verification detail), plus `paid_verification` spend/tokens and `llm_model`. This is internal business/operational data, read without authentication. Read-only, no mutation, so impact is limited; rated A because it meets "reachable without login and reads private data". If the owner considers pilot metadata public, downgrade to D.
- **Fix:** keep `/health` to `{"ok", "service", "version"}` (what Render's health check needs); move `paid_verification` / `real_pilot` to the authenticated `/api/status` or `/api/release-readiness`.
- **Regression test:** `status, body = asgi_get("/health")` with `FACTORY_PASSWORD` patched and no cookie → `200`, and `set(json.loads(body)) <= {"ok","service","version"}`; assert `b"real_pilot"` and `b"idea_title"` not in body.

### B-1 — viewer GET on a factory cycle writes state and creates artifacts/proposals

- **Route:** `GET /api/factory-cycles/{cycle_id}`, app.py:9290 → `sync_factory_cycle(cycle_id, True)` app.py:8933 → `derive_cycle_learning` app.py:8875.
- **Who:** owner, viewer (middleware allows all GETs for viewer, app.py:784–788; no route check). Members are not allowlisted.
- **Why:** `sync_factory_cycle` calls `_cycle_update(...)` (status/phase/publish_id). When a performance snapshot exists it calls `derive_cycle_learning`, which on **every call** inserts a new `cycle_learning` artifact (`save_artifact`), a cycle event, and — when the metric delta is ≥ 5 % or ≤ −5 % with ≥ 2 comparable items — a **new improvement proposal** (`create_improvement_proposal` + `UPDATE improvement_proposals`). It is not idempotent, so any viewer (or a polling dashboard) can multiply proposals/artifacts. The same write path is intentionally exposed as `POST /api/factory-cycles/{cycle_id}/sync` (app.py:9322), which viewers cannot call.
- **Fix:** make the GET read-only: `get_factory_cycle(cycle_id, True)` only; leave reconciliation/learning to the POST `/sync` and `/learn` routes. Optionally make `derive_cycle_learning` idempotent per (cycle, snapshot id).
- **Regression test:** seed a cycle with a job, publish item and a performance snapshot; with a viewer cookie `asgi_get(f"/api/factory-cycles/{cid}")` twice → `200`; assert the counts of `artifacts WHERE kind='cycle_learning'`, `improvement_proposals` and the cycle's `updated_at` are unchanged. Then `asgi_post(f"/api/factory-cycles/{cid}/sync")` with the viewer cookie → `403`.

### B-2 — viewer GET on artifact media can download and rewrite the artifact

- **Route:** `GET /api/artifacts/{artifact_id}/media`, app.py:4997 → `_archive_media_artifact` app.py:5113 (`UPDATE artifacts SET url=...` app.py:5144).
- **Who:** owner, viewer, member (member allowlisted for this GET, own workspace only).
- **Why:** if the artifact is a video whose URL is an ephemeral finisher URL and no archive exists, the GET downloads the remote file into `MEDIA_ARCHIVE_DIR`, writes metadata, and updates the artifact row. A viewer thereby causes outbound downloads, disk usage and a DB write. Effect is deterministic and arguably beneficial (durability), so severity is low, but it violates "viewer is read-only".
- **Fix:** in the GET, only serve an existing archive or redirect to the source; queue archival through the existing owner path (`POST /api/media-finisher/{id}/archive`, app.py:10672) or a background job not triggered by role-viewer requests. Alternatively skip `_archive_media_artifact` when `request_identity(request)["role"] == "viewer"`.
- **Regression test:** patch `factory._download_media_to_path` with a `Mock`; seed a video artifact with an ephemeral finisher URL; viewer `asgi_get(f"/api/artifacts/{aid}/media")`; assert the mock was not called and the artifact row's `url`/`meta_json` is unchanged.

### C-1 — worker routes without their own token check accept an owner session

- **Routes:** `POST /api/claude-worker/heartbeat` app.py:10480, `POST /api/claude-worker/task-result` app.py:10492, `POST /api/operator-worker/heartbeat` app.py:10496, `GET /api/local-booster/status` app.py:10514, `GET /api/local-booster/token` app.py:10520, `GET /api/local-booster/package.zip` app.py:10524, `POST /api/local-booster/heartbeat` app.py:10542, `POST /api/local-booster/claim` app.py:10548, `POST /api/local-booster/{edit_job_id}/progress` app.py:10572, `POST /api/local-booster/{edit_job_id}/complete` app.py:10614.
- **Where:** only the middleware bypass (app.py:767–770) checks the token; there is no check inside the route. Without a valid token the request falls through to session auth.
- **Why:** verified locally: owner session → `POST /api/claude-worker/heartbeat` 200, `POST /api/operator-worker/heartbeat` 200, `POST /api/local-booster/heartbeat` 200; while `GET /api/claude-worker/control` with the same session → 401 because that route says "an owner session must not be able to impersonate the runner" (app.py:11814). An owner browser session (or anything that can ride on it) can forge worker telemetry, submit Builder task results (`ingest_claude_worker_result`, app.py:485 — still validated, it cannot mark "done" without one captured commit), claim/complete local-booster jobs with uploaded media. Viewer is limited to `GET /api/local-booster/status` (token and package are explicitly denied, app.py:785). Severity is moderate: owner is trusted, but this is the "middleware is the only check" pattern the issue asks about, and it contradicts the explicit rule at app.py:11814.
- **Fix:** add explicit checks in each route: `if not _claude_worker_authorized(request): raise HTTPException(401, ...)`, `_operator_worker_authorized`, `_local_booster_authorized`. For `/api/local-booster/token` and `package.zip`, which the owner legitimately downloads from the dashboard, keep an owner-session path but make it explicit (`role == "owner" or _local_booster_authorized`).
- **Regression test:** with an owner cookie and no Bearer: `asgi_post("/api/claude-worker/heartbeat", ...)`, `/task-result`, `/api/operator-worker/heartbeat`, `/api/local-booster/heartbeat`, `/claim` → all `401`; with the correct token → `200`; cross-token (`FACTORY_LOCAL_BOOSTER_TOKEN` on `/api/claude-worker/heartbeat`) → `401`.

### C-2 — media-jobs callback: route checks a token the middleware never lets through

- **Route:** `POST /api/media-jobs/{media_job_id}/callback`, app.py:10787 (token check app.py:10789–10792).
- **Why:** the path is not in any middleware bypass, so an external provider with the correct `FACTORY_VIDEO_CALLBACK_TOKEN` and no session gets `401 authentication required` from the middleware (verified locally). Only an owner session can reach the route (members are not allowlisted, viewers cannot POST); the token is then required only if configured. No code in the repo builds this callback URL for a provider (searched `app.py` for its construction) — needs confirmation whether any external system calls it.
- **Fix:** either remove the route, or add a bypass like the finisher's: `(FACTORY_VIDEO_CALLBACK_TOKEN and re.fullmatch(r"/api/media-jobs/[0-9a-fA-F-]+/callback", path))`, and make the route **require** the token (fail closed when unset).
- **Regression test:** patch `FACTORY_VIDEO_CALLBACK_TOKEN="cb"`; `asgi_post("/api/media-jobs/<id>/callback", "cb", ...)` → not 401 (404 for unknown id); with `"wrong"` and with no bearer → 401.

### C-3 — `/api/factory/voice/*` routes unusable (FastAPI binds `request` as a query parameter)

- **Routes:** `GET/POST /api/factory/voice/settings` voice_settings.py:99, 110; `GET /api/factory/voice/history` voice_settings.py:164; `POST /api/factory/voice/worker/brief-deliver` voice_settings.py:179.
- **Why:** voice_settings.py:11 has `from __future__ import annotations`, and `Request` is imported inside each `install_*` function, so FastAPI cannot resolve the string annotation `"Request"` against module globals and treats `request` as a required query parameter. Verified: owner → 422 on all three owner routes; worker with valid token → 422 on brief-deliver; with `?request=x` → 500 (the string reaches `is_owner`/`authorize_worker`). Fail-closed (no bypass of the owner/worker checks), but the owner cannot read/change voice settings and the morning brief cannot be delivered. `test_voice_settings.py` calls the handler functions directly, so it does not catch this. The middleware does enforce the worker token for brief-deliver (no token → 401, wrong token → 401; verified).
- **Fix:** import `Request` at module level in voice_settings.py (as mycast.py does), or drop the `__future__` import for this module.
- **Regression test:** through the ASGI app: owner cookie `asgi_get("/api/factory/voice/settings")` → 200; viewer → 403; worker token `asgi_post("/api/factory/voice/worker/brief-deliver", token, b'{"date":"bad"}')` → 400 (reaches the route), no token → 401, owner cookie without token → 401. Generic guard: assert no route in `factory.app.routes` has a query param named `request`.

### C-4 — Telegram bridge shares the MCP connector credential

- **Routes:** `POST /api/factory/telegram/bridge/notify` app.py:1061, `GET /api/factory/telegram/bridge/inbox` app.py:1081; auth `_telegram_bridge_authorized` app.py:534 compares against `FACTORY_MCP_TOKEN`.
- **Why:** `FACTORY_MCP_TOKEN` is the credential given to the Claude custom connector for `/mcp` and is accepted there as a URL query parameter (`?key=`, app.py:1105). The same value lets its holder read the owner's private Telegram inbox (up to 100 messages) and send arbitrary text to the owner's chat as FactoryOS. Privilege scope of the connector credential is wider than "design partner MCP" (get context, list tasks, submit design review).
- **Fix:** introduce a separate `FACTORY_TELEGRAM_BRIDGE_TOKEN` (fall back to the current behaviour only if explicitly configured), and stop accepting the MCP token in the bridge.
- **Regression test:** patch `FACTORY_MCP_TOKEN="mcp"` and a distinct bridge token; `asgi_get("/api/factory/telegram/bridge/inbox", "mcp")` → 401/403; with the bridge token → 200.

### C-5 — MVP factory routes admit `member` but the middleware does not

- **Routes:** `POST /api/mvp-factory/{project_id}/events` mvp_factory.py:249 (check :252), `POST /api/mvp-factory/projects` mvp_factory.py:268 (check in `add_project`, :197).
- **Why:** the route allows `role in ("owner","member")`, but `/api/mvp-factory*` is not in `MEMBER_ROUTES` (workspace_tenancy.py:100), so members get 403 from `_workspace_member_denial`. Effective callers: owner only. Also `GET /api/mvp-factory` (mvp_factory.py:242) has no own check and is visible to viewers (docstring says intended).
- **Fix:** decide: either drop `member` from the route checks (owner-only), or allowlist the routes for members with a workspace binding. Record the decision in DECISIONS.md.
- **Regression test:** member cookie (`_member_session_token`) → POST events → expect the decided status; viewer → 403; owner → 200.

### C-6 — OAuth: member can start a flow it can never finish (needs confirmation)

- **Routes:** `POST /api/oauth/{provider}/authorize` app.py:9718 (member-allowlisted, workspace_tenancy.py:110); `GET /api/oauth/{provider}/callback` app.py:9726 (route requires `role == "owner"`; not member-allowlisted).
- **Why:** a member's authorize succeeds (when adapters exist), but the provider redirect to the callback is refused for the member. In production the token vault is `UnavailableTokenVault`, so authorize refuses anyway; this becomes live with T-552.
- **Fix:** before enabling real adapters, either allow the callback for the member whose subject is bound to the OAuth state (state already binds `_oauth_subject`), or remove `authorize|disconnect` from the member allowlist.
- **Regression test:** with a mock adapter and memory vault: member authorize → callback with returned state as the same member → expect the decided outcome (connected, or 403 at authorize).

### C-7 — public prefixes without a path boundary; dead `/register` bypass

- **Where:** app.py:766 (`"/api/mycast/demo"`, `"/api/mycast/account"`, `"/api/mycast/voices"`), app.py:775 (`request.url.path=="/register"`).
- **Why:** `startswith` without a trailing `/` makes any future route whose path merely begins with these strings public with no middleware check (e.g. a later `/api/mycast/accounts-admin` or `/api/mycast/voices-config`). Verified: `GET /api/mycast/accounts-admin` and `/api/mycast/demonstration` return 404 (passed the middleware) where other unknown API paths return 401. `/register` is bypassed but no such route exists.
- **Fix:** match exact paths or `prefix + "/"`: e.g. `p == "/api/mycast/demo" or p.startswith("/api/mycast/demo/")`; remove `/register`.
- **Regression test:** unauthenticated `asgi_get("/api/mycast/accounts-admin")` → 401 (not 404); `asgi_get("/register")` → 303/401.

### D-1 — MCP token accepted in the query string

- app.py:1105. Tokens in URLs end up in proxy/access logs and browser history. If a client really cannot send headers, keep it but document and rotate; otherwise remove. Test: `asgi_get("/mcp?key=<token>")` → 401 once removed.

### D-2 — exception text returned to callers

- `/mcp` `tools/call` returns `str(exc)` (app.py:1255); agent MCP `tools` / `call` return `HTTPException(502, str(exc))` (app.py:11022, 11039); artifact media 410 includes `str(exc)[:220]` (app.py:5009). Can reveal internal hostnames, paths or provider messages to MCP-token holders/viewers. Fix: log the exception, return a category. Test: patch the inner call to raise `RuntimeError("secret-host:1234")`, assert the body does not contain it.

### D-3 — demo per-client cap trusts `X-Forwarded-For`

- mycast_demo.py:218–220 takes the **first** `X-Forwarded-For` value, which the client controls if the edge proxy appends rather than overwrites (Render behaviour needs confirmation). One client can rotate the header and consume the whole daily cap (30), denying the demo to others for the day. Spend stays bounded by the global cap. Fix: use the right-most proxy-added address (or `request.client.host` behind a trusted proxy config). Test: unit-test `_client_id` with `X-Forwarded-For: spoof, real` → expect `real`; ASGI: 6 starts with different spoofed first hops from the same peer → 6th is 429.

### D-4 — voice sample generation blocks the event loop

- mycast_voices.py:170–176: `async def mycast_voice_sample` calls `samples.sample(...)` directly; that performs the synchronous Gemini TTS request while holding a lock. During generation the whole server (dashboard, workers, webhooks) stalls. Bounded by 40/day and the fixed voice×language set. Fix: `await anyio.to_thread.run_sync(samples.sample, voice, lang)` (as mycast_demo does with a thread). Test: patch `tts` with a 1 s sleep; concurrently call `/health`; assert it returns well before 1 s.

### D-5 — viewer can trigger outbound MCP calls

- `GET /api/agents/{agent_name}/mcp/{connection_id}/tools`, app.py:11011: calls `mcp_list_tools` against the owner-configured endpoint with the credential named by `auth_env`. No local write; `tools/list` is read-only by protocol. Consider owner-only or cached listings. Test: viewer GET with `mcp_list_tools` mocked → assert not called (if made owner-only).

### D-6 — fail-open when `FACTORY_PASSWORD` is empty

- app.py:316–318 returns an owner identity for every request when the password is unset (used deliberately by CI/smoke tests). In that mode `GET /api/factory/claude-code/worker-token` and every owner route are public. render.yaml declares `FACTORY_PASSWORD` with `sync: false`; `/api/release-readiness` warns (app.py:4001). Production value not checked (needs confirmation). Fix option: refuse to start when `RENDER` is set and the password is empty. Test: with `RENDER=1` and empty password, startup raises / `/api/status` → 503.

### D-7 — listener accounts are uncapped

- mycast_accounts.py: each successful Telegram/Google login can create a record (with a ≤4000-char share code); there is no global cap or per-IP signup limit, and the referral bonus (+7 days per friend, up to 50) can be farmed with throwaway accounts. Product/abuse decision; needs confirmation. Test: once a cap exists, N+1 logins → 429.

### D-8 — no rate limit on password login

- `POST /login`, app.py:866: constant-time compare but unlimited attempts. Fix: per-IP/global backoff. Test: 20 bad attempts → later attempts 429.

## Full route table

Legend — **MW** = `auth_middleware` (app.py:764). "MW session" = a staff session is required (unauthenticated: 401 for `/api/*`, 303 to `/login` otherwise). "MW bypass if valid X" = the session check is skipped only when token X is valid; otherwise normal session rules apply. "viewer session" appears only where the viewer branch lets the method through. "member session (allowlist + own workspace)" = allowed by `MEMBER_ROUTES` and every id in the path must belong to the member's workspace. "route: none" = no authorization logic inside the handler.

| # | Method | Path | file:line | Who can call | Where enforced |
|---|---|---|---|---|---|
| 1 | GET | `/openapi.json` | fastapi (built-in) | owner session, viewer session | MW session; route: none |
| 2 | GET | `/docs` | fastapi (built-in) | owner session, viewer session | MW session; route: none |
| 3 | GET | `/docs/oauth2-redirect` | fastapi (built-in) | owner session, viewer session | MW session; route: none |
| 4 | GET | `/redoc` | fastapi (built-in) | owner session, viewer session | MW session; route: none |
| 5 | GET | `/static/*` | app.py (mount) | anyone | MW public prefix `/static/`; StaticFiles mount (`static/`) |
| 6 | GET | `/favicon.ico` | app.py:171 | anyone | MW public; route: none |
| 7 | GET | `/mycast` | app.py:177 | anyone | MW public; route: none |
| 8 | GET | `/api/relay` | relay.py:1466 | owner session | MW session; route: owner |
| 9 | POST | `/api/relay` | relay.py:1475 | owner session | MW session; route: owner |
| 10 | GET | `/api/relay/{ticket_id}` | relay.py:1487 | owner session | MW session; route: owner |
| 11 | POST | `/api/relay/{ticket_id}/status` | relay.py:1495 | owner session | MW session; route: owner |
| 12 | POST | `/api/relay/{ticket_id}/notes` | relay.py:1510 | owner session | MW session; route: owner |
| 13 | POST | `/api/relay/{ticket_id}/run` | relay.py:1522 | owner session | MW session; route: owner |
| 14 | POST | `/api/relay/intake/github-issue` | relay.py:1538 | owner session | MW session; route: owner |
| 15 | POST | `/api/relay/worker/claim` | relay.py:1561 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 16 | POST | `/api/relay/worker/roadmap-claim` | relay.py:1570 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 17 | POST | `/api/relay/worker/event` | relay.py:1586 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 18 | GET | `/relay` | relay.py:1606 | owner session | MW session; route: owner |
| 19 | POST | `/api/factory/mycast/worker/deliver` | mycast.py:185 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 20 | POST | `/api/factory/mycast/worker/voice-deliver` | mycast.py:327 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 21 | GET | `/api/factory/voice/settings` | voice_settings.py:99 | nobody in practice (422 for every caller) | MW session; route: owner (C-3) |
| 22 | POST | `/api/factory/voice/settings` | voice_settings.py:110 | nobody in practice (422 for every caller) | MW session; route: owner (C-3) |
| 23 | GET | `/api/factory/voice/history` | voice_settings.py:164 | nobody in practice (422 for every caller) | MW session; route: owner (C-3) |
| 24 | POST | `/api/factory/voice/worker/brief-deliver` | voice_settings.py:179 | Claude worker token passes MW, then 422 (C-3); no/wrong token: 401 | MW bypass if valid Claude worker token; route: worker token |
| 25 | GET | `/api/factory/gemini/worker/models` | gemini_proxy.py:45 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 26 | POST | `/api/factory/gemini/worker/generate` | gemini_proxy.py:53 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 27 | GET | `/api/mycast/demo/status` | mycast_demo.py:229 | anyone | MW public; route: none |
| 28 | POST | `/api/mycast/demo` | mycast_demo.py:233 | anyone | MW public prefix; route: script validation, 30/day global + 5/client cap (D-3) |
| 29 | GET | `/api/mycast/demo/{job_id}` | mycast_demo.py:246 | anyone | MW public; route: none |
| 30 | GET | `/api/mycast/demo/{job_id}/audio` | mycast_demo.py:253 | anyone | MW public; route: none |
| 31 | GET | `/api/mycast/voices` | mycast_voices.py:165 | anyone | MW public; route: none |
| 32 | POST | `/api/mycast/voices/{voice}/sample` | mycast_voices.py:169 | anyone | MW public prefix; route: fixed voice list + fixed text, 40/day cap, cache (D-4) |
| 33 | GET | `/api/mycast/voices/{voice}/{lang}.wav` | mycast_voices.py:180 | anyone | MW public; route: none |
| 34 | GET | `/api/mycast/account/config` | mycast_accounts.py:304 | anyone | MW public; route: none |
| 35 | GET | `/api/mycast/account/me` | mycast_accounts.py:316 | anyone (listener cookie) | MW public; route: listener cookie |
| 36 | POST | `/api/mycast/account/telegram` | mycast_accounts.py:324 | anyone with valid Telegram Login Widget data (HMAC by bot token, ≤24 h); links to current listener if signed in | MW public prefix; route: Telegram widget HMAC + listener cookie |
| 37 | POST | `/api/mycast/account/google` | mycast_accounts.py:337 | anyone with a valid Google ID token for the configured client id | MW public prefix; route: Google token verify |
| 38 | POST | `/api/mycast/account/podcast` | mycast_accounts.py:355 | anyone (listener cookie) | MW public; route: listener cookie |
| 39 | POST | `/api/mycast/account/delivery` | mycast_accounts.py:372 | anyone (listener cookie) | MW public; route: listener cookie |
| 40 | POST | `/api/mycast/account/telegram/test` | mycast_accounts.py:380 | anyone (listener cookie) | MW public; route: listener cookie |
| 41 | POST | `/api/mycast/account/delivery/sample` | mycast_accounts.py:399 | anyone (listener cookie) | MW public; route: listener cookie |
| 42 | POST | `/api/mycast/account/logout` | mycast_accounts.py:422 | anyone | MW public; route: none |
| 43 | DELETE | `/api/mycast/account` | mycast_accounts.py:428 | anyone (listener cookie) | MW public; route: listener cookie |
| 44 | GET | `/mycast/u/{slug}` | mycast_accounts.py:441 | anyone | MW public; route: none |
| 45 | POST | `/api/factory/connections/gemini/verify` | gemini_proxy.py:98 | owner session | MW session; route: owner |
| 46 | GET | `/api/mvp-factory` | mvp_factory.py:242 | owner session, viewer session | MW session; route: none |
| 47 | POST | `/api/mvp-factory/{project_id}/events` | mvp_factory.py:249 | owner session | MW session (member not allowlisted); route: owner/member (C-5) |
| 48 | POST | `/api/mvp-factory/projects` | mvp_factory.py:268 | owner session | MW session (member not allowlisted); route: owner/member via registry (C-5) |
| 49 | GET | `/api/factory/owner-desk` | owner_desk.py:536 | owner session | MW session; route: owner |
| 50 | POST | `/api/factory/owner-desk/questions` | owner_desk.py:548 | owner session | MW session; route: owner |
| 51 | POST | `/api/factory/owner-desk/worker/selftest` | owner_desk.py:559 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 52 | POST | `/api/factory/owner-desk/worker/claim` | owner_desk.py:568 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 53 | POST | `/api/factory/owner-desk/worker/answer` | owner_desk.py:577 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 54 | GET | `/login` | app.py:813 | anyone | MW public; route renders form |
| 55 | POST | `/login` | app.py:866 | anyone with owner username+password | MW public; route: password compare (no rate limit, D-8) |
| 56 | POST | `/auth/google` | app.py:875 | anyone with a verified Google ID token for an allowlisted email | MW public; route: Google token verify + allowlist role |
| 57 | GET | `/guest` | app.py:893 | anyone with viewer invite token | MW public; route: HMAC compare of invite token |
| 58 | GET | `/api/viewer-invite` | app.py:900 | owner session | MW session + viewer deny-list; route: owner |
| 59 | GET | `/api/factory/telegram/status` | app.py:910 | owner session | MW session; route: owner |
| 60 | POST | `/api/factory/telegram/pairing/start` | app.py:918 | owner session | MW session; route: owner |
| 61 | POST | `/api/factory/telegram/test` | app.py:954 | owner session | MW session; route: owner |
| 62 | POST | `/api/integrations/telegram/webhook` | app.py:968 | Telegram (secret header); actions further limited to paired private chat | MW bypass (path, unconditional); route: webhook secret + paired chat id |
| 63 | POST | `/api/factory/telegram/bridge/notify` | app.py:1061 | bridge token (= MCP token) | MW bypass if valid MCP token; route: MCP token (C-4) |
| 64 | GET | `/api/factory/telegram/bridge/inbox` | app.py:1081 | bridge token (= MCP token) | MW bypass if valid MCP token; route: MCP token (C-4) |
| 65 | POST | `/logout` | app.py:1092 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 66 | POST | `/mcp` | app.py:1207 | MCP token holder (Bearer or `?key=`) | MW public; route: MCP token (503 if unset) |
| 67 | GET | `/mcp` | app.py:1258 | MCP token holder (Bearer or `?key=`) | MW public; route: MCP token (503 if unset) |
| 68 | GET | `/health` | app.py:1266 | anyone | MW public; route: none (see A-1) |
| 69 | GET | `/media-archive/{archive_id}` | app.py:4968 | anyone with signed URL | MW public prefix; route: HMAC(FACTORY_SECRET) URL token |
| 70 | GET | `/api/artifacts/{artifact_id}/media` | app.py:4997 | owner session, viewer session, member session (own workspace) | MW session; route: none; GET may download + update artifact (B-2) |
| 71 | GET | `/api/factory-cycles` | app.py:9286 | owner session, viewer session | MW session; route: none |
| 72 | GET | `/api/factory-cycles/{cycle_id}` | app.py:9290 | owner session, viewer session | MW session; route: none; GET writes state (B-1) |
| 73 | POST | `/api/factory-cycles` | app.py:9296 | owner session | MW session; route: none |
| 74 | GET | `/api/factory-cycles/{cycle_id}/quote` | app.py:9303 | owner session, viewer session | MW session; route: none |
| 75 | POST | `/api/factory-cycles/{cycle_id}/run` | app.py:9308 | owner session | MW session; route: none |
| 76 | POST | `/api/factory-cycles/{cycle_id}/sync` | app.py:9322 | owner session | MW session; route: none |
| 77 | POST | `/api/factory-cycles/{cycle_id}/learn` | app.py:9329 | owner session | MW session; route: none |
| 78 | POST | `/api/factory-cycles/{cycle_id}/next` | app.py:9336 | owner session | MW session; route: none |
| 79 | GET | `/api/approval` | app.py:9346 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 80 | GET | `/api/jobs/{job_id}/approval/history` | app.py:9355 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 81 | GET | `/api/jobs/{job_id}/media-finisher/preview` | app.py:9360 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 82 | GET | `/api/jobs/{job_id}/approval/quote/{component}` | app.py:9365 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 83 | POST | `/api/jobs/{job_id}/reject` | app.py:9371 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 84 | POST | `/api/jobs/{job_id}/approval/regenerate` | app.py:9385 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 85 | POST | `/api/jobs/{job_id}/idea-link/{idea_id}` | app.py:9412 | owner session | MW session; route: none |
| 86 | GET | `/api/publisher-adapters` | app.py:9417 | owner session, viewer session | MW session; route: none |
| 87 | GET | `/api/publishing` | app.py:9421 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 88 | POST | `/api/publishing/{publish_id}/schedule` | app.py:9425 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 89 | POST | `/api/publishing/{publish_id}/publish` | app.py:9464 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 90 | POST | `/api/publishing/{publish_id}/dry-run` | app.py:9520 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 91 | POST | `/api/publishing/{publish_id}/confirm` | app.py:9526 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 92 | POST | `/api/publishing/{publish_id}/refresh` | app.py:9540 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 93 | POST | `/api/publishing/run-due` | app.py:9547 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 94 | GET | `/api/analytics-adapters` | app.py:9572 | owner session, viewer session | MW session; route: none |
| 95 | GET | `/api/performance` | app.py:9576 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 96 | GET | `/api/performance/{publish_id}` | app.py:9580 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 97 | POST | `/api/performance/snapshots` | app.py:9586 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 98 | POST | `/api/performance/{publish_id}/sync` | app.py:9593 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 99 | GET | `/ru` | app.py:9614 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 100 | GET | `/uk` | app.py:9614 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 101 | GET | `/en` | app.py:9614 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 102 | GET | `/` | app.py:9614 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 103 | GET | `/api/version` | app.py:9621 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 104 | GET | `/api/integrations` | app.py:9632 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 105 | POST | `/api/integrations/{provider}/disconnect` | app.py:9641 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 106 | POST | `/api/integrations/{provider}/connect` | app.py:9655 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 107 | POST | `/api/integrations/disconnect-all` | app.py:9677 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 108 | POST | `/api/integrations/{provider}/switch` | app.py:9688 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 109 | GET | `/api/oauth/providers` | app.py:9714 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 110 | POST | `/api/oauth/{provider}/authorize` | app.py:9718 | owner session, member session (allowlist + own workspace) | MW session; route: none (C-6) |
| 111 | GET | `/api/oauth/{provider}/callback` | app.py:9726 | owner session | MW session (member not allowlisted); route: owner + OAuth state bound to subject (C-6) |
| 112 | POST | `/api/oauth/{provider}/disconnect` | app.py:9745 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 113 | GET | `/api/status` | app.py:9758 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 114 | GET | `/api/workspace` | app.py:9837 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 115 | GET | `/api/workspaces` | app.py:9844 | owner session, viewer session | MW session; route: none |
| 116 | GET | `/api/release-readiness` | app.py:9861 | owner session, viewer session | MW session; route: none |
| 117 | GET | `/api/intelligence` | app.py:9865 | owner session, viewer session | MW session; route: none |
| 118 | GET | `/api/content-brain` | app.py:9870 | owner session, viewer session | MW session; route: none |
| 119 | POST | `/api/content-brain/collect` | app.py:9874 | owner session | MW session; route: none |
| 120 | POST | `/api/content-brain/signals` | app.py:9882 | owner session | MW session; route: none |
| 121 | POST | `/api/content-brain/generate` | app.py:9893 | owner session | MW session; route: none |
| 122 | POST | `/api/content-brain/process` | app.py:9905 | owner session | MW session; route: none |
| 123 | POST | `/api/content-brain/ideas` | app.py:9916 | owner session | MW session; route: none |
| 124 | POST | `/api/content-brain/ideas/{idea_id}/status` | app.py:9926 | owner session | MW session; route: none |
| 125 | POST | `/api/jobs` | app.py:9942 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 126 | POST | `/api/jobs/{job_id}/select` | app.py:9956 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 127 | POST | `/api/jobs/{job_id}/move` | app.py:9961 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 128 | POST | `/api/jobs/{job_id}/run` | app.py:9970 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 129 | POST | `/api/jobs/{job_id}/approve` | app.py:10030 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 130 | POST | `/api/jobs/{job_id}/agents/{agent_name}/rerun` | app.py:10093 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 131 | GET | `/api/agents` | app.py:10138 | owner session, viewer session | MW session; route: none |
| 132 | GET | `/api/agents/{agent_name}` | app.py:10153 | owner session, viewer session | MW session; route: none |
| 133 | GET | `/api/handoffs/{run_id}/{artifact_id}` | app.py:10206 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 134 | GET | `/api/browser-runs` | app.py:10230 | owner session, viewer session | MW session; route: none |
| 135 | GET | `/api/browser-runs/{artifact_id}` | app.py:10234 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 136 | GET | `/api/discovery` | app.py:10243 | owner session, viewer session | MW session; route: none |
| 137 | POST | `/api/discovery/candidates` | app.py:10247 | owner session | MW session; route: none |
| 138 | POST | `/api/discovery/collect` | app.py:10254 | owner session | MW session; route: none |
| 139 | POST | `/api/discovery/{candidate_id}/revideo` | app.py:10261 | owner session | MW session; route: none |
| 140 | GET | `/media-source/{upload_id}` | app.py:10277 | anyone with signed URL | MW public prefix; route: HMAC(FACTORY_SECRET) URL token |
| 141 | POST | `/api/jobs/{job_id}/media-finisher/upload` | app.py:10288 | owner session, member session (own workspace) | MW session; route: none (issues signed URL) |
| 142 | GET | `/api/factory/claude-code/status` | app.py:10447 | owner session | MW session; route: owner |
| 143 | GET | `/api/factory/claude-code/worker-token` | app.py:10453 | owner session | MW session; route: owner |
| 144 | POST | `/api/factory/claude-code/pair-token` | app.py:10460 | owner session | MW session; route: owner |
| 145 | GET | `/api/factory/claude-code/pair-token/status` | app.py:10472 | owner session | MW session; route: owner |
| 146 | POST | `/api/claude-worker/heartbeat` | app.py:10480 | Claude worker token, owner session | MW bypass if valid Claude worker token; else session; route: none (C-1) |
| 147 | POST | `/api/claude-worker/task-result` | app.py:10492 | Claude worker token, owner session | MW bypass if valid Claude worker token; else session; route: none (C-1) |
| 148 | POST | `/api/operator-worker/heartbeat` | app.py:10496 | operator worker token, owner session | MW bypass if valid operator worker token; else session; route: none (C-1) |
| 149 | GET | `/api/factory/operators/runtime` | app.py:10508 | owner session | MW session; route: owner |
| 150 | GET | `/api/local-booster/status` | app.py:10514 | local-booster token, owner session, viewer session | MW bypass if valid local-booster token; else session; route: none (C-1) |
| 151 | GET | `/api/local-booster/token` | app.py:10520 | local-booster token, owner session (viewer explicitly 403) | MW bypass if valid local-booster token; MW viewer deny-list; route: none (C-1) |
| 152 | GET | `/api/local-booster/package.zip` | app.py:10524 | local-booster token, owner session (viewer explicitly 403) | MW bypass if valid local-booster token; MW viewer deny-list; route: none (C-1) |
| 153 | POST | `/api/local-booster/heartbeat` | app.py:10542 | local-booster token, owner session | MW bypass if valid local-booster token; else session; route: none (C-1) |
| 154 | POST | `/api/local-booster/claim` | app.py:10548 | local-booster token, owner session | MW bypass if valid local-booster token; else session; route: none (C-1) |
| 155 | POST | `/api/local-booster/{edit_job_id}/progress` | app.py:10572 | local-booster token, owner session | MW bypass if valid local-booster token; else session; route: none (C-1) |
| 156 | POST | `/api/local-booster/{edit_job_id}/complete` | app.py:10614 | local-booster token, owner session | MW bypass if valid local-booster token; else session; route: none (C-1) |
| 157 | GET | `/api/media-finisher/profiles` | app.py:10639 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 158 | GET | `/api/media-finisher` | app.py:10643 | owner session, viewer session | MW session; route: none |
| 159 | GET | `/api/media-finisher/{edit_job_id}` | app.py:10647 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 160 | POST | `/api/jobs/{job_id}/media-finisher` | app.py:10653 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 161 | POST | `/api/media-finisher/{edit_job_id}/refresh` | app.py:10664 | owner session | MW session; route: none |
| 162 | POST | `/api/media-finisher/{edit_job_id}/archive` | app.py:10672 | owner session | MW session; route: none |
| 163 | POST | `/api/media-finisher/{edit_job_id}/callback` | app.py:10683 | finisher callback token (when configured), owner session | MW bypass for hex id path if callback token configured; route: same token if configured |
| 164 | POST | `/api/media-finisher/{edit_job_id}/rerun/{stage}` | app.py:10695 | owner session | MW session; route: none |
| 165 | GET | `/api/revideo` | app.py:10705 | owner session, viewer session | MW session; route: none |
| 166 | GET | `/api/revideo/adapters` | app.py:10709 | owner session, viewer session | MW session; route: none |
| 167 | POST | `/api/revideo` | app.py:10713 | owner session | MW session; route: none |
| 168 | GET | `/api/revideo/{project_id}` | app.py:10720 | owner session, viewer session | MW session; route: none |
| 169 | GET | `/api/revideo/{project_id}/quote` | app.py:10726 | owner session, viewer session | MW session; route: none |
| 170 | POST | `/api/revideo/{project_id}/analyze` | app.py:10732 | owner session | MW session; route: none |
| 171 | POST | `/api/revideo/{project_id}/create-job` | app.py:10749 | owner session | MW session; route: none |
| 172 | POST | `/api/revideo/{project_id}/render` | app.py:10756 | owner session | MW session; route: none |
| 173 | GET | `/api/media-jobs` | app.py:10769 | owner session, viewer session | MW session; route: none |
| 174 | GET | `/api/media-jobs/{media_job_id}` | app.py:10773 | owner session, viewer session | MW session; route: none |
| 175 | POST | `/api/media-jobs/{media_job_id}/refresh` | app.py:10779 | owner session | MW session; route: none |
| 176 | POST | `/api/media-jobs/{media_job_id}/callback` | app.py:10787 | owner session (+ video callback token if configured); external token holder gets 401 from MW | MW session; route: video callback token if configured (C-2) |
| 177 | GET | `/api/media-adapters` | app.py:10801 | owner session, viewer session | MW session; route: none |
| 178 | GET | `/api/jobs/{job_id}/content-package` | app.py:10805 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 179 | POST | `/api/jobs/{job_id}/content-package/generate` | app.py:10822 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 180 | GET | `/api/jobs/{job_id}/content-package/export.json` | app.py:10835 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 181 | GET | `/api/jobs/{job_id}/content-package/export.zip` | app.py:10843 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 182 | GET | `/api/jobs/{job_id}/variants` | app.py:10854 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 183 | POST | `/api/jobs/{job_id}/variants/generate` | app.py:10867 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 184 | POST | `/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}` | app.py:10876 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 185 | POST | `/api/jobs/{job_id}/variants/{variant_id}/select` | app.py:10884 | owner session, member session (allowlist + own workspace) | MW session; route: none |
| 186 | GET | `/api/jobs/{job_id}/quality` | app.py:10890 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 187 | GET | `/api/jobs/{job_id}/artifacts` | app.py:10897 | owner session, viewer session, member session (allowlist + own workspace) | MW session; route: none |
| 188 | DELETE | `/api/artifacts/{artifact_id}` | app.py:10911 | owner session | MW session; route: none |
| 189 | GET | `/api/usage` | app.py:10940 | owner session, viewer session | MW session; route: none |
| 190 | GET | `/api/agents/{agent_name}/mcp` | app.py:10948 | owner session, viewer session | MW session; route: none |
| 191 | POST | `/api/agents/{agent_name}/mcp` | app.py:10959 | owner session | MW session; route: none |
| 192 | POST | `/api/agents/{agent_name}/mcp/{connection_id}/toggle` | app.py:10982 | owner session | MW session; route: none |
| 193 | DELETE | `/api/agents/{agent_name}/mcp/{connection_id}` | app.py:10997 | owner session | MW session; route: none |
| 194 | GET | `/api/agents/{agent_name}/mcp/{connection_id}/tools` | app.py:11011 | owner session, viewer session | MW session; route: none; outbound MCP call (D-5) |
| 195 | POST | `/api/agents/{agent_name}/mcp/{connection_id}/call` | app.py:11024 | owner session | MW session; route: none |
| 196 | GET | `/api/factory/autopilot` | app.py:11327 | owner session, viewer session | MW session; route: none |
| 197 | GET | `/api/factory/delegation-board` | app.py:11331 | owner session | MW session; route: owner |
| 198 | GET | `/api/factory/lane-board` | app.py:11349 | owner session | MW session; route: owner |
| 199 | POST | `/api/factory/team-tasks/worker/snapshot` | app.py:11430 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 200 | GET | `/api/factory/team-tasks` | app.py:11447 | owner session | MW session; route: owner |
| 201 | GET | `/api/factory/worker-overview` | app.py:11453 | owner session | MW session; route: owner |
| 202 | GET | `/api/factory/roles` | app.py:11521 | owner session | MW session; route: owner |
| 203 | POST | `/api/factory/roles/assignment` | app.py:11527 | owner session | MW session; route: owner |
| 204 | GET | `/api/factory/routing` | app.py:11558 | owner session | MW session; route: owner |
| 205 | GET | `/api/battles` | app.py:11575 | owner session, viewer session | MW session; route: none |
| 206 | POST | `/api/battles` | app.py:11580 | owner session | MW session; route: none |
| 207 | GET | `/api/battles/{battle_id}` | app.py:11588 | owner session, viewer session | MW session; route: none |
| 208 | POST | `/api/battles/{battle_id}/results` | app.py:11593 | owner session | MW session; route: none |
| 209 | POST | `/api/battles/{battle_id}/outcomes` | app.py:11617 | owner session | MW session; route: none |
| 210 | GET | `/api/battles/{battle_id}/leaderboard` | app.py:11625 | owner session, viewer session | MW session; route: none |
| 211 | GET | `/api/battles/{battle_id}/reviews` | app.py:11632 | owner session, viewer session | MW session; route: none |
| 212 | POST | `/api/battles/{battle_id}/reviews` | app.py:11638 | owner session | MW session; route: none |
| 213 | POST | `/api/factory/delegation-control` | app.py:11808 | owner session | MW session; route: owner |
| 214 | GET | `/api/claude-worker/control` | app.py:11814 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 215 | POST | `/api/claude-worker/control/ack` | app.py:11820 | Claude worker token | MW bypass if valid Claude worker token; else session; route: Claude worker token |
| 216 | GET | `/api/factory/builder` | app.py:11825 | owner session, viewer session | MW session; route: none |
| 217 | GET | `/api/factory/tasks` | app.py:11836 | owner session, viewer session | MW session; route: none |
| 218 | GET | `/api/factory/tasks/{task_id}` | app.py:11840 | owner session, viewer session | MW session; route: none |
| 219 | POST | `/api/factory/tasks/{task_id}/start` | app.py:11850 | owner session | MW session; route: none |
| 220 | POST | `/api/factory/tasks` | app.py:11900 | owner session | MW session; route: none |
| 221 | POST | `/api/factory/tasks/{task_id}/status` | app.py:11913 | owner session | MW session; route: none |
| 222 | GET | `/api/improvements` | app.py:11937 | owner session, viewer session | MW session; route: none |
| 223 | POST | `/api/improvements/{proposal_id}/accept` | app.py:11941 | owner session | MW session; route: none |
| 224 | POST | `/api/improvements/{proposal_id}/dismiss` | app.py:11949 | owner session | MW session; route: none |
| 225 | POST | `/api/improvements` | app.py:11960 | owner session | MW session; route: none |
| 226 | GET | `/api/self-improvement` | app.py:11968 | owner session, viewer session | MW session; route: none |
| 227 | GET | `/api/workflow/active` | app.py:11972 | owner session, viewer session | MW session; route: none |
| 228 | GET | `/api/experiments` | app.py:11976 | owner session, viewer session | MW session; route: none |
| 229 | POST | `/api/improvements/{proposal_id}/experiment` | app.py:11980 | owner session | MW session; route: none |
| 230 | POST | `/api/experiments/{experiment_id}/assign` | app.py:11987 | owner session | MW session; route: none |
| 231 | POST | `/api/experiments/{experiment_id}/evaluate` | app.py:11995 | owner session | MW session; route: none |
| 232 | POST | `/api/experiments/{experiment_id}/rollout` | app.py:12002 | owner session | MW session; route: none |
| 233 | POST | `/api/experiments/{experiment_id}/rollback` | app.py:12009 | owner session | MW session; route: none |
| 234 | POST | `/api/experiments/{experiment_id}/reject` | app.py:12016 | owner session | MW session; route: none |
| 235 | GET | `/api/agents/{agent_name}/memory` | app.py:12028 | owner session, viewer session | MW session; route: none |
| 236 | POST | `/api/agents/{agent_name}/memory` | app.py:12034 | owner session | MW session; route: none |
| 237 | DELETE | `/api/agents/{agent_name}/memory/{memory_id}` | app.py:12043 | owner session | MW session; route: none |
| 238 | GET | `/api/supervisor` | app.py:12057 | owner session, viewer session | MW session; route: none |
| 239 | POST | `/api/supervisor/run` | app.py:12061 | owner session | MW session; route: none |
| 240 | WS | `/ws` | app.py:12068 | owner, viewer, member (session cookie) | route (HTTP middleware does not run for websockets); own cookie check |
