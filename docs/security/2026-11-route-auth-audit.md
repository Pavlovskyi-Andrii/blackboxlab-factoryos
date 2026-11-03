# FactoryOS route authentication audit — 2026-11-03

**Issue:** #114 · **Owner:** ChatGPT · **Scope:** repository `main`, read-only static source inspection · **Live probing:** none · **Cost:** zero.

## Method and limits

I fetched complete `app.py`, `relay.py`, `owner_desk.py` and `mycast.py` from `main`, extracted all `@app.get/post/put/delete/patch/head/options` declarations, and examined route bodies against `auth_middleware` (`app.py:688-735`). Counts: **202 method/path declarations** (app.py: 184; relay.py: 11; owner_desk.py: 5; mycast.py: 2). Mounted `/static` is middleware-public but is not a decorator; the websocket surface, dynamically attached routes, and OAuth redirect semantics require a separate audit. A static inspection cannot establish the deployed auth configuration, prove runtime rejection, or show absence of all vulnerabilities.

`auth_middleware` requires a valid session except public login/guest/health/MCP entry paths, public static/media paths, authenticated worker/bridge/booster tokens, the Telegram webhook, and a media callback path when a callback token exists. Authenticated `viewer` requests are limited to read methods (and `/logout`), with explicit denial of known token/download endpoints; workspace members get separate route/resource restrictions. **Important:** the middleware's session fallback means an owner session can reach some worker routes without the worker credential; this is not the same as an anonymous or outsider bypass.

For route entries marked "session (owner/viewer GET; writes owner)", that is the **middleware minimum**, not evidence of a further per-route owner guard. Role decisions for sensitive resources should be read together with tenancy and the individual handler.

## Findings and regression actions

| Grade | Location | Finding / consequence | Recommendation and full-ASGI regression |
|---|---|---|---|
| A | `app.py:688-720`, `app.py:4863-4870`, `app.py:10099-10106` | **No confirmed unauthenticated data mutation** found in these bypass paths: media endpoints accept public requests but require a matching HMAC token; webhook `app.py:892-895` validates its secret; MCP `app.py:1105-1111` validates its bearer key. Static-only result, not penetration proof. | Test GET to each signed media URL without token or wrong token (403); webhook POST with missing/wrong secret (403); disabled/wrong-token MCP (401/503). |
| B | `app.py:718-725` | **No confirmed viewer-write bypass**: middleware rejects non-GET/HEAD/OPTIONS for viewer sessions and separately blocks viewer access to booster token/ZIP and viewer invite. However `/logout` is exempt. | Real ASGI with a viewer cookie: POST integration disconnect and POST task start must return 403 with unchanged state; owner control still succeeds. |
| C1 | `app.py:699`, `owner_desk.py:505-523` | Historically, `/api/factory/owner-desk/worker/*` was missing from worker middleware allowlist, breaking legitimate calls. Current `main` has the allowlist **and** route worker checks. Likewise `/api/factory/mycast/worker/*`. | Keep `test_worker_token_binding.OwnerDeskWorkerMiddlewareTest`: a valid token passes actual ASGI middleware; absent/wrong token returns 401. Repeat for new worker endpoints. |
| C2 | `app.py:695-701`, `app.py:10302-10316`, `app.py:10336-10344` | Worker/booster prefixes are gated primarily in middleware; e.g. the heartbeat and local-booster token handlers don't recheck token themselves. A normal authenticated owner can call these routes (viewer write rejected). **Defense-in-depth gap**, not a demonstrated outsider bypass. | Add explicit `_claude_worker_authorized` / `_local_booster_authorized` to worker-only handlers where owner access is not intended, and a test that a session-only owner cannot impersonate a worker. Keep a separate owner-only token endpoint for onboarding. |
| C3 | `app.py:694`, `app.py:10505-10515` | Media callback is middleware-public only when its token is configured; handler then checks bearer token. With callback token absent, normal session auth applies. Configuration-dependent dual behavior is hard to reason about. | Make callback require a configured credential fail-closed (503 if absent), then always validate callback bearer. ASGI test for unset, absent, wrong and correct token. |
| C4 | `app.py:687-736`, `app.py:11575-11598` | Numerous non-mutating FactoryOS read endpoints rely only on session and are therefore viewable by read-only viewer roles. This might be intentional; it is **not established** that all task/worker metadata should be viewer-visible. | Write an explicit role policy: owner-only for operational telemetry/task internals if sensitive, viewer only for approved dashboards. ASGI test GET for viewer across these paths. |
| D | `app.py:10511-10513`, `app.py:4920` | Some exception text from media processing is included in HTTP errors; upstream messages could expose implementation details or untrusted URLs. No secret leaked in this audit. | Sanitize errors to a fixed public category, add tests with synthetic key-looking text and ensure response does not contain it. |

**Priority for Claude:** confirm C2/C3 intent and add ASGI role tests before changing auth. No application files have been changed in this PR. This audit is a source map, not a claim that security testing against production occurred.

## Full route inventory

Entries cover each declared decorator, not mounted static files, and describe the minimum gate. Per-route middleware checks are **not** equivalent to an authorization policy for data belonging to another workspace.

| Method | Path | Source line | Accessible principal (minimum) | Enforcement point |
|---|---|---|---|---|
| GET | `/login` | `app.py:738` | public entry (route-level checks as noted) | public/session setup |
| POST | `/login` | `app.py:790` | public entry (route-level checks as noted) | public/session setup |
| POST | `/auth/google` | `app.py:799` | public entry (route-level checks as noted) | public/session setup |
| GET | `/guest` | `app.py:817` | public entry (route-level checks as noted) | public/session setup |
| GET | `/api/viewer-invite` | `app.py:824` | owner session | middleware + explicit owner role |
| GET | `/api/factory/telegram/status` | `app.py:834` | owner session | middleware + explicit owner role |
| POST | `/api/factory/telegram/pairing/start` | `app.py:842` | owner session | middleware + explicit owner role |
| POST | `/api/factory/telegram/test` | `app.py:878` | owner session | middleware + explicit owner role |
| POST | `/api/integrations/telegram/webhook` | `app.py:892` | webhook secret | webhook check in handler |
| POST | `/api/factory/telegram/bridge/notify` | `app.py:959` | bridge token or session | bridge token in middleware and handler |
| GET | `/api/factory/telegram/bridge/inbox` | `app.py:979` | bridge token or session | bridge token in middleware and handler |
| POST | `/logout` | `app.py:990` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/mcp` | `app.py:1105` | public entry (route-level checks as noted) | MCP token in handler |
| GET | `/mcp` | `app.py:1156` | public entry (route-level checks as noted) | MCP token in handler |
| GET | `/health` | `app.py:1164` | public entry (route-level checks as noted) | public/session setup |
| GET | `/media-archive/{archive_id}` | `app.py:4863` | public URL with signed HMAC token | token signature in handler |
| GET | `/api/artifacts/{artifact_id}/media` | `app.py:4892` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory-cycles` | `app.py:9132` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory-cycles/{cycle_id}` | `app.py:9136` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory-cycles` | `app.py:9142` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory-cycles/{cycle_id}/quote` | `app.py:9149` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory-cycles/{cycle_id}/run` | `app.py:9154` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory-cycles/{cycle_id}/sync` | `app.py:9168` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory-cycles/{cycle_id}/learn` | `app.py:9175` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory-cycles/{cycle_id}/next` | `app.py:9182` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/approval` | `app.py:9192` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/approval/history` | `app.py:9201` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/media-finisher/preview` | `app.py:9206` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/approval/quote/{component}` | `app.py:9211` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/reject` | `app.py:9217` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/approval/regenerate` | `app.py:9231` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/idea-link/{idea_id}` | `app.py:9258` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/publisher-adapters` | `app.py:9263` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/publishing` | `app.py:9267` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/{publish_id}/schedule` | `app.py:9271` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/{publish_id}/publish` | `app.py:9292` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/{publish_id}/dry-run` | `app.py:9342` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/{publish_id}/confirm` | `app.py:9348` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/{publish_id}/refresh` | `app.py:9362` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/publishing/run-due` | `app.py:9369` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/analytics-adapters` | `app.py:9394` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/performance` | `app.py:9398` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/performance/{publish_id}` | `app.py:9402` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/performance/snapshots` | `app.py:9408` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/performance/{publish_id}/sync` | `app.py:9415` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/` | `app.py:9436` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/en` | `app.py:9437` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/uk` | `app.py:9438` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/ru` | `app.py:9439` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/version` | `app.py:9443` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/integrations` | `app.py:9454` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/integrations/{provider}/disconnect` | `app.py:9463` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/integrations/{provider}/connect` | `app.py:9477` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/integrations/disconnect-all` | `app.py:9499` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/integrations/{provider}/switch` | `app.py:9510` | owner session | middleware + explicit owner role |
| GET | `/api/oauth/providers` | `app.py:9536` | owner session | middleware + explicit owner role |
| POST | `/api/oauth/{provider}/authorize` | `app.py:9540` | owner session | middleware + explicit owner role |
| GET | `/api/oauth/{provider}/callback` | `app.py:9548` | owner session | middleware + explicit owner role |
| POST | `/api/oauth/{provider}/disconnect` | `app.py:9567` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/status` | `app.py:9580` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/workspace` | `app.py:9659` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/workspaces` | `app.py:9666` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/release-readiness` | `app.py:9683` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/intelligence` | `app.py:9687` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/content-brain` | `app.py:9692` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/collect` | `app.py:9696` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/signals` | `app.py:9704` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/generate` | `app.py:9715` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/process` | `app.py:9727` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/ideas` | `app.py:9738` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/content-brain/ideas/{idea_id}/status` | `app.py:9748` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs` | `app.py:9764` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/select` | `app.py:9778` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/move` | `app.py:9783` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/run` | `app.py:9792` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/approve` | `app.py:9852` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/agents/{agent_name}/rerun` | `app.py:9915` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/agents` | `app.py:9960` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/agents/{agent_name}` | `app.py:9975` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/handoffs/{run_id}/{artifact_id}` | `app.py:10028` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/browser-runs` | `app.py:10052` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/browser-runs/{artifact_id}` | `app.py:10056` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/discovery` | `app.py:10065` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/discovery/candidates` | `app.py:10069` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/discovery/collect` | `app.py:10076` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/discovery/{candidate_id}/revideo` | `app.py:10083` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/media-source/{upload_id}` | `app.py:10099` | public URL with signed HMAC token | token signature in handler |
| POST | `/api/jobs/{job_id}/media-finisher/upload` | `app.py:10110` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory/claude-code/status` | `app.py:10269` | owner session | middleware + explicit owner role |
| GET | `/api/factory/claude-code/worker-token` | `app.py:10275` | owner session | middleware + explicit owner role |
| POST | `/api/factory/claude-code/pair-token` | `app.py:10282` | owner session | middleware + explicit owner role |
| GET | `/api/factory/claude-code/pair-token/status` | `app.py:10294` | owner session | middleware + explicit owner role |
| POST | `/api/claude-worker/heartbeat` | `app.py:10302` | Claude worker token or session | middleware worker token; session authenticated |
| POST | `/api/claude-worker/task-result` | `app.py:10314` | Claude worker token or session | middleware worker token; session authenticated |
| POST | `/api/operator-worker/heartbeat` | `app.py:10318` | operator worker token or session | operator worker token in middleware |
| GET | `/api/factory/operators/runtime` | `app.py:10330` | owner session | middleware + explicit owner role |
| GET | `/api/local-booster/status` | `app.py:10336` | local booster token or session | booster token in middleware; viewer restrictions |
| GET | `/api/local-booster/token` | `app.py:10342` | local booster token or session | booster token in middleware; viewer restrictions |
| GET | `/api/local-booster/package.zip` | `app.py:10346` | local booster token or session | booster token in middleware; viewer restrictions |
| POST | `/api/local-booster/heartbeat` | `app.py:10364` | local booster token or session | booster token in middleware; viewer restrictions |
| POST | `/api/local-booster/claim` | `app.py:10370` | local booster token or session | booster token in middleware; viewer restrictions |
| POST | `/api/local-booster/{edit_job_id}/progress` | `app.py:10394` | local booster token or session | booster token in middleware; viewer restrictions |
| POST | `/api/local-booster/{edit_job_id}/complete` | `app.py:10436` | local booster token or session | booster token in middleware; viewer restrictions |
| GET | `/api/media-finisher/profiles` | `app.py:10461` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/media-finisher` | `app.py:10465` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/media-finisher/{edit_job_id}` | `app.py:10469` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/media-finisher` | `app.py:10475` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/media-finisher/{edit_job_id}/refresh` | `app.py:10486` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/media-finisher/{edit_job_id}/archive` | `app.py:10494` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/media-finisher/{edit_job_id}/callback` | `app.py:10505` | callback bearer token (if configured) / session | callback bearer check in route |
| POST | `/api/media-finisher/{edit_job_id}/rerun/{stage}` | `app.py:10517` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/revideo` | `app.py:10527` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/revideo/adapters` | `app.py:10531` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/revideo` | `app.py:10535` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/revideo/{project_id}` | `app.py:10542` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/revideo/{project_id}/quote` | `app.py:10548` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/revideo/{project_id}/analyze` | `app.py:10554` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/revideo/{project_id}/create-job` | `app.py:10571` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/revideo/{project_id}/render` | `app.py:10578` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/media-jobs` | `app.py:10591` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/media-jobs/{media_job_id}` | `app.py:10595` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/media-jobs/{media_job_id}/refresh` | `app.py:10601` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/media-jobs/{media_job_id}/callback` | `app.py:10609` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/media-adapters` | `app.py:10623` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/content-package` | `app.py:10627` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/content-package/generate` | `app.py:10644` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/content-package/export.json` | `app.py:10657` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/content-package/export.zip` | `app.py:10665` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/variants` | `app.py:10676` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/variants/generate` | `app.py:10689` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}` | `app.py:10698` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/jobs/{job_id}/variants/{variant_id}/select` | `app.py:10706` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/quality` | `app.py:10712` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/jobs/{job_id}/artifacts` | `app.py:10719` | session (owner/viewer GET; writes owner) | session middleware |
| DELETE | `/api/artifacts/{artifact_id}` | `app.py:10733` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/usage` | `app.py:10762` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/agents/{agent_name}/mcp` | `app.py:10770` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/agents/{agent_name}/mcp` | `app.py:10781` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/agents/{agent_name}/mcp/{connection_id}/toggle` | `app.py:10804` | session (owner/viewer GET; writes owner) | session middleware |
| DELETE | `/api/agents/{agent_name}/mcp/{connection_id}` | `app.py:10819` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/agents/{agent_name}/mcp/{connection_id}/tools` | `app.py:10833` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/agents/{agent_name}/mcp/{connection_id}/call` | `app.py:10846` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory/autopilot` | `app.py:11149` | owner session | middleware + explicit owner role |
| GET | `/api/factory/delegation-board` | `app.py:11153` | owner session | middleware + explicit owner role |
| GET | `/api/factory/lane-board` | `app.py:11165` | owner session | middleware + explicit owner role |
| GET | `/api/factory/worker-overview` | `app.py:11203` | owner session | middleware + explicit owner role |
| GET | `/api/factory/roles` | `app.py:11271` | owner session | middleware + explicit owner role |
| POST | `/api/factory/roles/assignment` | `app.py:11277` | owner session | middleware + explicit owner role |
| GET | `/api/factory/routing` | `app.py:11308` | owner session | middleware + explicit owner role |
| GET | `/api/battles` | `app.py:11325` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/battles` | `app.py:11330` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/battles/{battle_id}` | `app.py:11338` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/battles/{battle_id}/results` | `app.py:11343` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/battles/{battle_id}/outcomes` | `app.py:11367` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/battles/{battle_id}/leaderboard` | `app.py:11375` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/battles/{battle_id}/reviews` | `app.py:11382` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/battles/{battle_id}/reviews` | `app.py:11388` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory/delegation-control` | `app.py:11558` | owner session | middleware + explicit owner role |
| GET | `/api/claude-worker/control` | `app.py:11564` | Claude worker token or session | middleware worker token; session authenticated |
| POST | `/api/claude-worker/control/ack` | `app.py:11570` | Claude worker token or session | middleware worker token; session authenticated |
| GET | `/api/factory/builder` | `app.py:11575` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory/tasks` | `app.py:11586` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/factory/tasks/{task_id}` | `app.py:11590` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory/tasks/{task_id}/start` | `app.py:11600` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory/tasks` | `app.py:11650` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/factory/tasks/{task_id}/status` | `app.py:11663` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/improvements` | `app.py:11687` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/improvements/{proposal_id}/accept` | `app.py:11691` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/improvements/{proposal_id}/dismiss` | `app.py:11699` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/improvements` | `app.py:11710` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/self-improvement` | `app.py:11718` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/workflow/active` | `app.py:11722` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/experiments` | `app.py:11726` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/improvements/{proposal_id}/experiment` | `app.py:11730` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/experiments/{experiment_id}/assign` | `app.py:11737` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/experiments/{experiment_id}/evaluate` | `app.py:11745` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/experiments/{experiment_id}/rollout` | `app.py:11752` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/experiments/{experiment_id}/rollback` | `app.py:11759` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/experiments/{experiment_id}/reject` | `app.py:11766` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/agents/{agent_name}/memory` | `app.py:11778` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/agents/{agent_name}/memory` | `app.py:11784` | session (owner/viewer GET; writes owner) | session middleware |
| DELETE | `/api/agents/{agent_name}/memory/{memory_id}` | `app.py:11793` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/supervisor` | `app.py:11807` | session (owner/viewer GET; writes owner) | session middleware |
| POST | `/api/supervisor/run` | `app.py:11811` | session (owner/viewer GET; writes owner) | session middleware |
| GET | `/api/relay` | `relay.py:1142` | owner session | middleware + explicit owner role |
| POST | `/api/relay` | `relay.py:1151` | owner session | middleware + explicit owner role |
| GET | `/api/relay/{ticket_id}` | `relay.py:1163` | owner session | middleware + explicit owner role |
| POST | `/api/relay/{ticket_id}/status` | `relay.py:1171` | owner session | middleware + explicit owner role |
| POST | `/api/relay/{ticket_id}/notes` | `relay.py:1186` | owner session | middleware + explicit owner role |
| POST | `/api/relay/{ticket_id}/run` | `relay.py:1198` | owner session | middleware + explicit owner role |
| POST | `/api/relay/intake/github-issue` | `relay.py:1214` | owner session | middleware + explicit owner role |
| POST | `/api/relay/worker/claim` | `relay.py:1237` | Claude worker token or session | middleware + route worker guard |
| POST | `/api/relay/worker/roadmap-claim` | `relay.py:1246` | Claude worker token or session | middleware + route worker guard |
| POST | `/api/relay/worker/event` | `relay.py:1262` | Claude worker token or session | middleware + route worker guard |
| GET | `/relay` | `relay.py:1282` | owner session | middleware + explicit owner role |
| GET | `/api/factory/owner-desk` | `owner_desk.py:473` | owner session | middleware + explicit owner role |
| POST | `/api/factory/owner-desk/questions` | `owner_desk.py:485` | owner session | middleware + explicit owner role |
| POST | `/api/factory/owner-desk/worker/selftest` | `owner_desk.py:496` | Claude worker token or session | middleware + route worker guard |
| POST | `/api/factory/owner-desk/worker/claim` | `owner_desk.py:505` | Claude worker token or session | middleware + route worker guard |
| POST | `/api/factory/owner-desk/worker/answer` | `owner_desk.py:514` | Claude worker token or session | middleware + route worker guard |
| POST | `/api/factory/mycast/worker/deliver` | `mycast.py:80` | Claude worker token or session | middleware + authorize_worker in route |
| POST | `/api/factory/mycast/worker/voice-deliver` | `mycast.py:197` | Claude worker token or session | middleware + authorize_worker in route |

## Additional route surfaces outside this decorator table

- `/static/*` and `/.well-known/*`: publicly served by middleware; audit contents for unintended secrets.
- WebSocket handlers (`@app.websocket`) and any `app.mount` or other runtime registration require separate protocol-level checks; `auth_middleware("http")` alone does not protect a WebSocket handshake.
- `/api/media-finisher/{edit_job_id}/callback` has a configured-secret shortcut and explicit handler check.
- `/media-source/{upload_id}` and `/media-archive/{archive_id}` are bearer-in-query signed URLs: retain HMAC validation and avoid logging or publicly exposing URLs.
- Tenant member permissions are delegated to `tenancy.member_route_allowed`/`tenancy.path_resources`; that is a separate ACL review, not an assurance made here.

## Recommended follow-up ownership

Claude should own authorization fixes; Gemini G2 (#123) may add the full-ASGI permission matrix **only after this report is reviewed and merged**. No real calls to cloud, Telegram, or Google were made.
