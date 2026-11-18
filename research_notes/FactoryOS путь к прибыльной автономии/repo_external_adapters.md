# FactoryOS repository audit: adapters to the outside world ("tentacles") and the safety controls around them

Audit date: 2026-11-17. Repository: `/home/user/blackboxlab-factoryos`, HEAD `11a3330` (2026-11-17 21:47 +0200,
"Merge pull request #416: T-592 …"), `APP_VERSION = "v5.12.0"` (`app.py:79`). Method: read-only code and document
audit (Grep / Read / read-only git). The clone is **shallow** (`git rev-parse --is-shallow-repository` → `true`;
98 commits visible, 2026-11-13 … 2026-11-17), so git-history claims cover only that window. No `.env` was read, no
live host was called, no FactoryOS MCP tool was used. "Source" below is a file path (with line or heading) or a git
command, because this is a local audit.

Status grades used: **live-verified** (repo contains an evidence note or document), **tests-only** (code plus
deterministic tests, no live evidence in the repo), **planned**, **blocked-on-human**, **unknown**.

## Key claims

| # | Claim | Source (file path / git evidence) | Date / version | Confidence |
|---|---|---|---|---|
| 1 | FactoryOS has never produced a real external post. `T-520` (configure first real publisher) and `T-521` (first owner-approved real post) are both open `[HUMAN]` tasks; the publisher adapter defaults to `manual`. | `ROADMAP.md:420-427`; `app.py:289`; `README.md:293-294` ("publish_created=false") | 2026-11-17, v5.12.0 | verified_primary |
| 2 | There is no payment, billing, checkout or invoicing code anywhere. MyCast counts free-trial days but enforcement is off by default and there is nothing to pay with. | Grep `stripe\|paddle\|lemonsqueez\|liqpay\|fondy\|wayforpay\|paypal\|monobank\|checkout\|invoice\|paywall` over `*.py` (only a secret-scan regex and browser deny-lists match); `mycast_library.py:27,57-58` | 2026-11-17 | verified_primary |
| 3 | No code exists for Gmail or any e-mail sending, for Notion, for HubSpot API calls or for vidIQ. HubSpot is an OAuth registry entry and a UI label only; e-mail is planned task `T-635` (open). | Greps listed in "Absence checks"; `oauth_framework.py:87-95`; `app.py:11196` (adapters = youtube, linkedin only); `ROADMAP.md:841`; `app.py:2064` | 2026-11-17 | verified_primary |
| 4 | The only outward channels with live evidence in the repo are: the Telegram owner bot, the GitHub branch → PR → CI loop, the read-only Surfer browser, Gemini API calls (TTS / text) and two small historical paid LLM pilots. Every "write to a public platform" adapter is tests-only or blocked on the owner. | `ROADMAP.md:103-106` (T-591-H); `git log` (PRs to #416); `docs/verification/surfer-benchmark-2026-11-16.md`; `README.md:287-294, 377` | 2026-10-19 … 2026-11-17 | verified_primary |
| 5 | Three real publisher adapters exist in code: Metricool scheduler (needs a paid Metricool plan, so blocked by the zero-spend policy), direct YouTube Data API upload (merged 2026-11-15, zero-network tests only) and LinkedIn text posts (merged 2026-11-17, ships dark behind `FACTORY_LINKEDIN_ENABLED`). TikTok and Instagram have provider specs but no adapter. | `app.py:9330-9345, 9503-9577`; `youtube_publisher.py:1-13`; `linkedin_publisher.py:1-13, 72-75`; `git log -- youtube_publisher.py linkedin_publisher.py`; `docs/research/metricool_api.md`; `.autopilot/answers.md` (2026-11-15, T-520) | 2026-11-17 | verified_primary |
| 6 | The publish approval gate is real and fail-closed (current owner approval of the same job, immutable snapshot hash, media SHA-256 re-check, UNIQUE idempotency key, "uncertain outcome" fence). But approval is a plain cookie-session POST, the approver is recorded as the hard-coded string `"owner"`, and a workspace member may also approve and publish in their workspace. No second factor, no approver identity. | `app.py:10917-10989, 9516-9523, 2500, 8781-8794, 11646-11667`; `docs/security/2026-11-route-auth-audit.md` rows 89, 129 | 2026-11-17 | verified_primary (identity gap = inference from code) |
| 7 | USD budget guards (`FACTORY_DAILY_BUDGET_USD=10`, `FACTORY_JOB_BUDGET_USD=3`, pilot ceiling 0.75) cover only the OpenAI-compatible metered path. Gemini usage (TTS, transcription, search grounding, peer review, video) is limited by about ten separate per-feature daily counters and by the external assumption that the Google project has no billing. Paid video generation is gated by a client-supplied boolean, not a priced budget. There is no global spend kill switch. | `app.py:277-278, 116, 3850-3855, 7302-7307, 12383-12386`; caps in `web_surfer.py:41`, `telegram_group.py:37`, `voice_transcribe.py:25`, `mycast_listener_delivery.py:39`, `peer_review.py:25`, `mycast_demo.py:30`, `mycast_voices.py:46`; `connection_capabilities.py:74-88` | 2026-11-17 | verified_primary |
| 8 | "Subscription, not API" is enforced in code: the worker scrubs `ANTHROPIC_API_KEY` and similar variables, the root supervisor treats paid-key variables as a fault, and the Gemini worker refuses to start when key variables are set (except an opt-in free-tier key). Agent CLIs used: Claude Code, Gemini CLI, Codex CLI. | `autopilot/delegation.py:27-43`; `autopilot/supervisor.py:25-31`; `autopilot/gemini_worker.py:28-41, 108-113`; `autopilot/codex_relay_worker.py:1-13` | 2026-11-17 | verified_primary |
| 9 | The route audit (2026-11-08) covered 240 routes and found 18 issues (A 1, B 2, C 7, D 8); 9 were fixed by 2026-11-09. Still open: fail-open when `FACTORY_PASSWORD` is empty (D-6), no login rate limit (D-8), MCP token accepted in the URL (D-1), viewer-triggered outbound MCP call (D-5), and others. The baseline's SSRF review of 16 `urlopen` call sites has no recorded follow-up. | `docs/security/2026-11-route-auth-audit.md` (Fix status table); `docs/security/2026-11-02-baseline.md` (findings 5-6, "Not covered"); `app.py:372-375`; Grep `ssrf\|defusedxml` → only the baseline | 2026-11-02 / 2026-11-09 | verified_primary |
| 10 | The owner session cookie is a static `HMAC(FACTORY_SECRET, FACTORY_USER)` with no expiry or server-side revocation; one shared `FACTORY_MCP_TOKEN` is held by every connected AI client and is accepted as `?key=`; per-lane tokens are not yet set (`T-624` open). | `app.py:332-337, 355-356, 1797-1812`; `docs/guides/agent-workspace-mcp.md`; `ROADMAP.md:163` | 2026-11-17 | verified_primary |
| 11 | Prompt-injection defence for web content is structural (read-only GET-only browser, egress proxy, tool-restricted agent runs, owner-only task intake) plus a text label in two places. The Surfer returns raw page text to any MCP client with no wrapper, and it can read pages under a saved logged-in session. No content scanning exists. | `browser_runner/playwright_executor.py:43-50`; `browser_runner/egress_proxy.py:1-7`; `tools/gemini_issue_pr.cjs:104`; `autopilot/codex_relay_worker.py:127-133`; `browser_tasks.py:225-237, 305-316`; Grep `prompt.?inject\|untrusted` | 2026-11-17 | verified_primary (sufficiency = inference) |
| 12 | There are at least nine parallel task or message stores: `ROADMAP.md`, Relay tickets, GitHub Issues, the Builder `factory_tasks` table, Owner Desk questions, agent-workspace handoffs, the Claude ↔ Codex inbox, Telegram group threads and the legacy Telegram bridge inbox, plus Notion outside the code. The repo itself records that Notion and the coordination protocol disagree about where tasks live. | `docs/handoff/NOTION_READ_PROOF_2026-11-05.md` ("Verdict"); `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md` §1, §3; module docstrings of `relay_execution.py`, `agent_workspace.py`, `relay_agent_messages.py`, `owner_desk.py`, `telegram_group.py`, `team_tasks.py` | 2026-11-05 … 2026-11-17 | verified_primary |
| 13 | `app.py` is a monolith: 13,742 lines, 817,351 bytes, 213 route decorators, 727 top-level functions, 39 tables; the dashboard is a single 1.07 MB `static/index.html`. New adapters are separate modules with injected dependencies, but each still needs edits in `app.py`. `mods/` is a vendored Claude Code plugin folder, not an adapter plugin system. | `wc -l app.py`, `wc -c app.py static/index.html`; Grep counts; `mods/README.md`; `mods_registry.py:1-14, 29-44` | 2026-11-17 | verified_primary |
| 14 | Operations are single-node and thin: one uvicorn process, SQLite and JSON files on a 1 GB Render disk, no backup code, DBOS durability for one flow only, kill switches are environment variables. On 2026-11-17 `main` was overwritten by 1,214 junk commits from the owner's account and was restored with a force-with-lease push; branch protection was added after the incident. | `render.yaml`; `README_RENDER.md`; Grep `backup` → none; `ROADMAP.md:740-754`; `DECISIONS.md:1841-1848`; `README.md:35-36` | 2026-11-17 | verified_primary |
| 15 | The bottleneck is the owner, not engineering: 16 open `[HUMAN]` tasks against 24 open agent tasks and 89 completed agent tasks. Every market-facing step (publisher, first post, OAuth apps, LinkedIn app, MyBrief outreach, Decision Memory interviews, referral terms, mail service) is owner-blocked. | `grep -c '^- \[ \] \[HUMAN\]' ROADMAP.md` → 16; list at `ROADMAP.md` (T-520, T-521, T-551, T-700-H, T-615-H, T-614-H1, T-620-H, T-634-H …) | 2026-11-17 | verified_primary |

## 1. Adapter inventory

Legend for "Grade": see top of file. "Tests" names the test file; line counts are from `wc -l`. CI runs 103 distinct
test commands (`.github/workflows/ci.yml`, 570 lines); the repo has 108 `test_*.py` files at the root and 9 under
`autopilot/`.

### 1.1 Summary table

| Adapter | What it can do today | Auth | Safety gates | Tests | Live proof | Grade |
|---|---|---|---|---|---|---|
| Telegram owner bot (Relay) | Paired private chat only: text, link, voice, video, document or photo becomes a Relay ticket; about 20 commands (`/tasks`, `/task`, `/new`, `/issue`, `/proof`, `/ask`, `/roadmap`, `/github`, `/workers`, `/battles`); inline buttons assign a lane, retry, cancel, accept or reject; stage cards pushed back. | Bot token in env; webhook header = HMAC of the bot token; one-time pairing code stored hashed, TTL 600 s. | `update_id` dedupe; other chats ignored; "Done" refused while a run is active; `/proof` built only from server history. | `test_relay_telegram.py` (319), `test_relay_acceptance.py`, `test_telegram_web_compare.py`, `test_telegram_operator_lanes.py`, `test_relay_notify_dedupe.py` | `ROADMAP.md:103-106`: T-591-H done 2026-11-17, server verdict VERIFIED for `R-0087 · run-351295eb0d92` (owner's screen is the evidence; the agent session got 401). T-592-H (Telegram vs web) still open. | live-verified (owner-attested) |
| Telegram team group | `/discuss`, replies, `/stop`, `/decision` with confirm buttons; Claude answers through the owner-question queue, Gemini answers directly (cap 40 per day); ChatGPT shown as not connected. | Same bot; group paired by one-time code from the owner's private chat. | Only the paired owner can act; decisions need a confirm tap and are stored in the bridge's own file. | `test_telegram_group.py` (195) | None found in the repo. | tests-only |
| Telegram to MyCast listeners | Sends an MP3 episode to a listener's own chat; sample and test sends. | Telegram Login Widget HMAC with 24 h freshness; listener cookie `ml1\|slug\|exp\|HMAC`. | Explicit listener opt-in; 3 test sends per listener per day; 10 listener episodes per UTC day globally. | `test_mycast_listener_delivery.py` (443), `test_mycast_accounts.py` | Owner report that nothing arrived 11-13 Nov (bug #317, `mycast_listener_delivery.py:1-3`); no later delivery evidence in the repo. Owner's own daily episode `T-603` is open ("Open: 7 live mornings", `ROADMAP.md:138-146`). | tests-only (live part unverified) |
| Publishing queue + approval gate | Approve → queue item → explicit schedule → publish; manual path asks the owner to paste the real post ID. | Owner or member session. | See claim 6; scheduler loop off unless `FACTORY_PUBLISHER_SCHEDULER_ENABLED=1` (`app.py:292, 8303`). | `smoke_tests.py:948-970` (1,370 lines total) | README: pilots reached the approval gate and published nothing. | tests-only for real publishing |
| Publishing dry-run (T-542) | Builds the exact per-platform plan and a receipt preview for YouTube Shorts, TikTok and Instagram Reels with no outbound call. | Session. | `outbound_calls: 0`, `spend_usd: 0.0`, `real_publish.allowed: False`, plan hash idempotent (`app.py:9579-9674`). | `test_publishing_dry_run.py` (308) | Not applicable (never calls out). | tests-only (by design) |
| Metricool adapter | Normalises media to Metricool hosting, creates a scheduler post, reconciles status. | `X-Mc-Auth` token plus user and blog IDs from env. | Default-workspace only; a Metricool schedule ID is never treated as a platform receipt. | Covered in `smoke_tests.py` and dry-run tests | `ROADMAP.md:422`: live runtime reported `adapter=manual`, `metricool_configured=false` (2026-10-26). `docs/research/metricool_api.md`: REST endpoints never tested on a live account; API needs the Advanced plan (from $53 per month annual, repo's reading of Metricool pages on 2026-11-01). Owner declined to pay (`.autopilot/answers.md`). | blocked-on-human / blocked by zero-spend |
| YouTube direct publisher (T-552-YT) | Google OAuth (exchange, refresh, revoke, channel identity), resumable upload of the exact archived file; Shorts only. | OAuth 2.0 with PKCE; client secret from env; tokens in the AES-256-GCM vault. | Privacy defaults to `private`; made-for-kids must be declared; SHA-256 of the file must equal the approved digest; uncertain outcome is never retried blindly. | `test_youtube_publisher.py` (330), zero network | None. "Live connection = HUMAN T-520, first post = HUMAN T-521" (`ROADMAP.md:558`). | tests-only, blocked-on-human |
| LinkedIn text posts (T-700) | Owner-only draft → approve (text SHA-256 frozen) → publish through `POST /rest/posts`. | OpenID Connect + `w_member_social`; 60-day token, no refresh token (`DECISIONS.md` "T-700"). | Off unless `FACTORY_LINKEDIN_ENABLED=1`; edit drops approval; atomic claim; uncertain outcome resolved only by the owner. | `test_linkedin_publisher.py` (212) | None; `T-700-H` open. Merged 2026-11-17 (`eeadcd1`, #414). | tests-only, blocked-on-human |
| Generic webhook publisher | POSTs the approved snapshot to `FACTORY_PUBLISHER_ENDPOINT`. | Bearer token from env. | Same gate; payload carries the idempotency key. | smoke tests | None. | tests-only |
| TikTok, Instagram | Provider specs only (authorize / token / revoke URLs and scopes). | — | Authorize refuses with `adapter_missing`. | `test_oauth_framework.py` (328, mocks) | None. | planned |
| HubSpot | Provider spec (`crm.objects.contacts.read/write`) and a "Connections" label. No API call anywhere. | — | — | mocks only | None. | planned |
| OAuth framework + vault | State store (TTL 600 s, single use), PKCE, token vault; AES-256-GCM files under `DATA_DIR/vault/`, records bound to workspace, provider and account through GCM associated data; key rotation. | `FACTORY_VAULT_KEY` (32 bytes) in Render env. | No key → `UnavailableTokenVault` (fail closed); OTP, TOTP seeds and recovery codes refused at write time; owner-only routes; secrets never returned. | `test_oauth_framework.py`, `test_browser_vault.py` (321), `test_vault_ui.py` | `ROADMAP.md:362-366`: owner confirmed `configured: true` on 2026-11-17 (agents cannot read that endpoint). | live-verified for key presence only |
| Surfer / browser agent | Read-only: public https page → main text, links, HTTP status, screenshot; up to 100,000 chars in chunks; optional read under a saved vault session on that session's cookie domains. Exposed as MCP `web_read`, `web_task`, `web_search`, as an agent REST and as a worker route. | `FACTORY_MCP_TOKEN` or lane token; `FACTORY_BROWSER_AGENT_TOKEN` (≥ 32 chars) for the agent REST; worker token for claim and result. | GET/HEAD/OPTIONS only; origin allowlist; egress proxy refuses private addresses at connection time; CAPTCHA, 2FA and anti-bot pages stop as `waiting_human`; 20 active tasks; 200 agent tasks per day; submit always blocked (`trusted_approval_verifier_not_configured`). | `test_web_surfer.py` (402), `test_browser_tasks.py` (529), `test_browser_playwright.py` (540), `test_browser_reading.py`, `test_browser_sessions.py`, `test_browser_social.py` | `docs/verification/surfer-benchmark-2026-11-16.md`: 33 tasks on production v5.10.0; 31 finished; fully useful 12 of 31; partly useful 15; wrong or misleading 4. Post-fix production re-run: "NOT STARTED"; fixed parts "UNKNOWN". | live-verified (read-only, pre-fix numbers) |
| Web search | Wikipedia API by default; Google Search grounding through Gemini when the owner opts in (cap 100 per day). | Server Gemini key. | Per-day cap; at most 3 Gemini calls per search. | `test_web_surfer.py` | `ROADMAP.md:343`: on 2026-11-17 a live search tried Gemini and fell back to Wikipedia (`gemini-2.5-flash` 404, two other models 429 RESOURCE_EXHAUSTED: free daily quota used up). | live-verified (with quota exhaustion) |
| Social draft recipes (X, Instagram, Telegram web) | Build a draft in the site composer and stop before the final click. | Saved vault session. | Real executor always blocks submit; selectors "have not been verified against the live sites" (`browser_runner/social.py:15-18`). | `test_browser_social.py` (mock executor) | None. | tests-only |
| FactoryOS MCP server (`/mcp`) | 15 tools: 3 design tools, 3 Surfer tools, 9 workspace tools (threads, handoffs). | Shared token (read-only for the workspace) or per-lane tokens (writes). | Idempotency key on every write; credential-shaped bodies refused; 120 writes per hour; a lane cannot review its own handoff; handoff claim goes through the Relay ROADMAP claim. | `test_agent_workspace.py` (331) | `ROADMAP.md:148-163`: lane tokens not set (`T-624` open); live round trip not done. Surfer part is live (see above). | Surfer live-verified; workspace tests-only, blocked-on-human |
| Outbound MCP client | Owner configures an MCP endpoint per agent with an env-var name for the token and an allowlist of tools; manual `tools/list` and `tools/call`. | Bearer from a named env var. | Tool allowlist; connection disabled by default; `mcp_call_log` audit table. Agent runs only list tools (`app.py:7289`), they do not call them. | smoke tests | None. Still labelled `"execution":"configuration_only"` (`app.py:12581`). | tests-only |
| GitHub intake and PR loop | Polls owner-authored Issues (first line `Owner: …`) every ≥ 5 min into Relay; Telegram `/issue N`; worker opens PRs with `gh pr create`; Codex reviews posted by the Claude worker; Builder dispatches `factory-builder.yml`. | `FACTORY_GITHUB_READ_TOKEN` (read) and `FACTORY_GITHUB_TOKEN` (workflow dispatch) on Render; the worker's own `gh` login on EC2. | Other authors ignored; T-ID dedupe; failed GitHub read = unknown, never success; push and merge are disallowed tools for the model, the runner pushes. | `test_issue_intake.py`, `test_intake_pagination.py`, `test_roadmap_claims.py`, `test_t599_acceptance.py`, `test_release_guardian.py` | `git log`: PR numbers up to #416, 16 merge commits and one "FactoryOS AWS Worker" commit in the 5-day window; Codex-review commits (`e96310b`, `34e0540`, `748b6f2`). `docs/verification/R-0058_relay_e2e_2026-11-10.md` recorded the PR step as BROKEN on 2026-11-10; fix recorded at `DECISIONS.md:937`. | live-verified |
| EC2 Claude worker (`autopilot/`) | Daemon loop: ROADMAP tasks, Relay tickets, owner questions, browser tasks, Codex reviews, MyCast scripts; `claude -p` with bounded turns and time. | Claude Code subscription login; worker token; pairing token. | See §3.2. Root supervisor timer every 60 s, at most 3 restarts per hour. | `autopilot/test_*.py` (9 files, about 2,300 lines) | `ROADMAP.md:119` (2026-11-01: usage limit hit at 12:01 UTC, resumed 16:22 UTC), `ROADMAP.md:128` (2026-11-02 owner-desk answers). `T-593-H` (worker moves on by itself) open. | live-verified (basic operation) |
| Gemini worker (T-607) | Gemini CLI as a third coding lane for `Owner: gemini` tasks. | Google-account login or opt-in free-tier key; narrow token `FACTORY_GEMINI_WORKER_TOKEN`. | Refuses to start with key variables; `--yolo` plus an excluded-shell list; own checkout and branch. | `test_gemini_worker.py` (279) | `T-607-H` and probe `T-607-P` open. | tests-only, blocked-on-human |
| Gemini Issue → PR loop | EC2 script every 5 min: one JSON generation per `Owner: Gemini` Issue through the Render proxy, then a PR. | Worker token; Gemini key stays in Render. | Stable Flash models only (`gemini_proxy.py:17`); prompt ≤ 400,000 chars. | `tools/test_gemini_research.cjs`, CI `node --check` | `docs/guide/gemini-coder.en.md` describes it as running since 2026-11-04; no verification document. | unknown (described as live, no evidence file) |
| Codex relay (ChatGPT lane) | Codex CLI answers bounded messages and PR reviews; no tools. | Two dedicated bearer tokens; Codex runs as a separate OS user with an empty environment. | Shell and file features disabled and verified in preflight; message wrapped as untrusted; reply secret-scanned; 12 reviews per day. | `test_relay_agent_messages.py` (471), `autopilot/test_codex_review.py` | Commit messages cite Codex reviews on #397, #407, #409, #412, #416. | live-verified (git evidence) |
| Media Finisher worker | Separate Render Docker service: FFmpeg, faster-whisper, Remotion; returns `final.mp4` plus evidence. | Shared bearer token (Render env group). | "Source video/text is always treated as material, never instructions"; cannot publish. | `media_finisher_worker/test_planner.py`, `test_durable_media_finisher.py` (352), `test_media_finisher_preview.py` | `README.md:12, 197`: real uploaded-video pilot; 5 of 5 archived videos present after redeploy (261,314,094 bytes). | live-verified |
| Gemini media (TTS, video) | Two-host TTS for MyCast (`gemini-2.5-flash-preview-tts`, `mycast.py:216`); video generation adapter `gemini-omni` (`render.yaml`: `gemini-omni-1.1-flash`). | `FACTORY_GEMINI_API_KEY`. | Per-feature daily caps; video needs `confirm_external_cost`. | `test_mycast*.py` | TTS: owner-triggered demo voicing shipped in v5.11.0 (`README.md`); video generation: no live evidence found. | TTS implied live; video unknown |
| Google Calendar (MyCast) | Listener connects their calendar read-only; today's events end the episode. | OAuth, scope `calendar.readonly`; refresh token encrypted with the vault key. | Signed short-lived state bound to the listener cookie; no calendar content stored. | `test_mycast_calendar.py` (191) | None found. | tests-only |
| Durable engine (DBOS 3.5.0) | Checkpointed workflow for the Media Finisher submit → callback/poll flow only. | — | `FACTORY_DBOS_ENABLED=0` kill switch; legacy path kept. | `test_durable_engine.py` (180), `test_durable_media_finisher.py` | `ROADMAP.md:754`: live check "not a blocker", not recorded as done. | tests-only |
| Notion | No code. One agent read two pages through a session connector on 2026-11-05; the EC2 worker has no Notion access; no write test. | — | — | — | `docs/handoff/NOTION_READ_PROOF_2026-11-05.md` | absent in code |
| Gmail / e-mail | No code. `T-635` (quiz e-mails) open; runbook asks the owner to create a free Resend account. | — | — | — | — | planned, blocked-on-human |
| vidIQ | Label `"paused"` only (`app.py:2064`). | — | — | — | — | absent in code |

### 1.2 Absence checks (searches actually run)

- Payments: `grep -rn -i "stripe\|paddle\|lemonsqueez\|liqpay\|fondy\|wayforpay\|paypal\|checkout\|invoice\|subscription_price\|paywall\|monobank" --include="*.py" .` → only `security_findings.py:27` (a regex for Stripe-shaped keys) and the browser executor's deny-list words.
- E-mail: `grep -rn -i "gmail\|smtp\|sendgrid\|mailgun\|postmark\|resend\.com\|ses\.amazonaws\|send_email\|sendmail\|mailchimp" --include="*.py" .` → only Owner Desk runbook text about Resend. `FACTORY_MAIL_API_KEY` appears only in runbook strings; `mvp_quiz.py:301` records mail as `held_flag_off` / `held_no_provider`.
- Notion: `grep -rn -i "notion" --include="*.py" .` → `open_questions.py` (`"notion": False`) and one text string in `mvp_factory.py`.
- HubSpot: `grep -rn -i "hubspot\|hubapi" --include="*.py" .` → provider spec, labels, tests, runbook text. No request to `api.hubapi.com` outside the spec constants.
- vidIQ: `grep -rn -i "vidiq"` → `app.py:2064, 5267, 7954` (labels and a hint) and two docs.
- Backups: `grep -n -i "backup\|snapshot.*disk\|restore.*db\|export.*db"` over non-test `*.py`, `README_RENDER.md`, `docs/ACCOUNT_PORTABILITY.md` → nothing.
- Emergency stop: `grep -n -i "emergency\|panic\|stop.all\|halt\|kill switch"` → only two feature kill switches (`durable_engine.py:20`, `mvp_quiz.py:15`).
- External hosts referenced in non-test Python (`grep -h -o "https?://…"`): `api.telegram.org`, `generativelanguage.googleapis.com`, `www.googleapis.com`, `oauth2.googleapis.com`, `accounts.google.com`, `api.github.com`, `api.linkedin.com`, `www.linkedin.com`, `app.metricool.com`, `api.openai.com` (default LLM base URL), `open.tiktokapis.com`, `graph.facebook.com`, `api.hubapi.com` (spec constants only), Wikipedia through `web_surfer.py`.

### 1.3 What the publishing path does, step by step

1. `POST /api/jobs/{id}/approve` requires status `waiting_approval`, a ready Content Package and ready media; it records an approval decision and creates a queue item; "no publish action executed" (`app.py:11646-11667`).
2. `POST /api/publishing/{id}/schedule` needs an ISO timestamp with timezone (`app.py:10896-10915`).
3. `POST /api/publishing/{id}/publish` refuses unless scheduled, due, not uncertain, and `_publish_approval_gate` returns empty (`app.py:10935-10989`). The gate fails closed on a missing, foreign, non-approved or stale decision (`app.py:10917-10933`).
4. `_publish_via_adapter` dispatches by `FACTORY_PUBLISHER_ADAPTER`: `manual` → owner must confirm a real post ID; `metricool`; `youtube`; else generic webhook (`app.py:9548-9577`). Non-default workspaces are refused server credentials.
5. A receipt artifact is written once per publish ID (`app.py:9484-9501`).

Design inconsistency worth knowing: the Metricool payload hard-codes YouTube `"privacy":"public"` (`app.py:9325`), while the direct YouTube adapter defaults to `private` (`youtube_publisher.py:144`).

## 2. LLM providers, models, and spend controls

### 2.1 Who is called and how it is paid

| Path | Provider and model in code | Billing mode | Source |
|---|---|---|---|
| Content pipeline "live LLM" (Scout, Researcher, Hook Writer and others) | OpenAI-compatible endpoint, default base `https://api.openai.com/v1`, default model string `gpt-5.6-terra`, hard-coded price table (0.20/1.20, 2.00/12.00, 4.00/20.00 USD per 1M tokens for three model names) | Metered API key `FACTORY_LLM_API_KEY`; demo mode when absent | `app.py:99-113` |
| Coding and operations agent | Claude Code CLI (`claude -p`) | Claude subscription login; API-key variables scrubbed | `autopilot/delegation.py:262-278`, `autopilot/relay_tasks.py:250-251` |
| Third coding lane | Gemini CLI (`gemini -p … --yolo`) | Google login (free personal tier) or opt-in free-tier key | `autopilot/delegation.py:280-287` |
| Reviews and agent messages | Codex CLI | ChatGPT subscription (per `autopilot/codex_review.py:107`) | `autopilot/codex_relay_worker.py` |
| Gemini text (Issue → PR, group answers, peer review, sub-topics, voice transcription) | Stable Gemini Flash models resolved from the key's model list | Server key `FACTORY_GEMINI_API_KEY`, intended free tier | `gemini_proxy.py:17, 45-70` |
| Gemini TTS | `gemini-2.5-flash-preview-tts` | Same key | `mycast.py:216` |
| Gemini video | `gemini-omni-1.1-flash`, 9:16, 720p | Same key; flagged `may_incur_charges: True` | `render.yaml`; `connection_capabilities.py:74-88` |
| Speech-to-text in Media Finisher | faster-whisper `small` on CPU | Local compute on Render | `render.yaml` |
| MyCast fallback voice | Piper TTS in GitHub Actions | Actions minutes | `autopilot/mycast_daily.py:1-7` |

Not verified here: whether the model names and the price table in `app.py:104-109` match the vendor's current
catalogue and prices. That needs a pricing-page check by another researcher.

Measured historical spend recorded in the repo: 7 live LLM runs, 5,846 tokens, $0.029902 (v3.25, 2026-10-19,
`README.md:377`); 22 live runs, 40,023 tokens, $0.188066 against a $0.75 ceiling (v4.1, 2026-10-20,
`README.md:287-294`). Whether `FACTORY_LLM_API_KEY` is set in production today is **unknown** (it is not in
`render.yaml`).

### 2.2 Spend guards and limits found

- Policy text: "ZERO ADDITIONAL SPEND … with a fail-closed spending guard. Subscription access must never be silently replaced with PAYG API usage" (`ROADMAP.md:27`).
- USD ledger guard: before each live model call the code checks today's recorded cost plus the worst-case next call against `FACTORY_DAILY_BUDGET_USD` (default 10) and per job against `FACTORY_JOB_BUDGET_USD` (default 3) (`app.py:7302-7307, 3850-3855, 4952-4957, 11606-11609`).
- Explicit cost confirmation before an Autopilot cycle (`confirm_cost`, `app.py:10742-10745`) and before Revideo analysis and render (`app.py:12366-12386`).
- One-shot pilot fence with a cumulative ceiling (`FACTORY_REAL_PILOT_MAX_USD`, default 0.75, `app.py:116, 2249-2257`).
- Per-feature daily counters on the Gemini key: web search 100, Telegram group 40, voice transcription 30, voice samples 40, MyCast public demo 30 (5 per client), demo audio 10 (5 per run), listener episodes 10, sub-topics 300 (30 per client), peer reviews 20, Codex reviews 12.
- Queue and turn bounds: Claude ROADMAP run 10-160 turns and 600-7,200 s (`autopilot/delegation.py:22-23`); Relay ticket default 60 turns and 1,800 s (`autopilot/relay_tasks.py:246-247`); browser queue 20 active tasks and 200 agent tasks per day.
- Subscription-limit handling: the whole queue waits for the reset instead of switching to a key (`autopilot/autopilot.py:78-81`; live note `ROADMAP.md:119`).
- Idempotency: UNIQUE `idempotency_key` on the publishing queue (`app.py:2500`); `update_id` dedupe for Telegram; `run_id` + `event_id` fencing for worker events (`autopilot/relay_tasks.py:111-130`); client idempotency keys on every MCP workspace write; deterministic DBOS workflow IDs and `edit_job_id` as the worker's idempotency key (`durable_media_finisher.py:9-13`).
- Kill switches (all environment variables, so they need a Render redeploy): `FACTORY_DBOS_ENABLED`, `FACTORY_LINKEDIN_ENABLED`, `FACTORY_PUBLISHER_SCHEDULER_ENABLED`, `FACTORY_GITHUB_ISSUE_INTAKE`, `FACTORY_QUIZ_AUTO_V2`, `FACTORY_QUIZ_MAIL`, `FACTORY_QUIZ_REWARDS`, `FACTORY_WEB_SEARCH_PROVIDER`, `FACTORY_METRICOOL_RECONCILE_ENABLED`, `FACTORY_MYCAST_ENFORCE_TRIAL`, `GEMINI_RESEARCH`, `AUTOPILOT_*`.
- Runtime controls without redeploy: owner pause / resume / retry of the Claude worker, applied after the current task (`autopilot/control.py:1-7`, `app.py:13472-13486`); cycle Stop / Resume; Relay Retry / Cancel from Telegram.

### 2.3 Gaps in spend control

- Gemini calls are outside the USD ledger. The hard stop is that the Google project has no billing, which the code cannot check (`docs/handoff/GEMINI_EC2_WORKER.md`: "Without billing Google cannot charge"). Whether the Render key's project has billing is **unknown**.
- No aggregate cap across Gemini features, and they share one free quota. Evidence that the quota is already binding: `ROADMAP.md:343` (429 RESOURCE_EXHAUSTED on 2026-11-17).
- `confirm_external_cost` and `confirm_cost` are request booleans supplied by the client; they prove a click, not a budget.
- No way to stop all spending and all outbound actions with one runtime action. The Gemini worker is stopped only by `systemctl` over SSH (`docs/handoff/GEMINI_EC2_WORKER.md`, "Stop / pause").

## 3. Security posture

### 3.1 The two security documents

`docs/security/2026-11-02-baseline.md` (pip-audit 2.9.0, gitleaks 8.30.1, bandit 1.8.6; repository only):
- 20 dependency advisories in 6 packages, only in a Python 3.9 resolution; fixed by pinning Python 3.13, security floors in `requirements.txt` and `pip-audit` in CI.
- Temporary AWS credentials inside two presigned S3 URLs in git history (commits `f514ce5`, `aa4ef11`, 2026-10-26); verified expired; the stale branch was left for the owner to delete.
- 103 bandit findings in non-test files; 13 SQL findings judged false positives; **16 `urlopen` call sites with variable URLs marked "Medium (to review)" for SSRF**; RSS parsed with `xml.etree`.
- Declared blind spots: no dynamic testing, no browser JavaScript review, no Render or AWS IAM review, GitHub secret scanning not enabled (paid for private repos).

`docs/security/2026-11-route-auth-audit.md` (2026-11-08, 240 route objects):
- Identity types: owner, viewer, member, Claude worker token, operator worker token, local-booster token, Telegram webhook secret, Telegram bridge token, MCP token, media-finisher callback token, MyCast listener cookie, signed media URL.
- Fixed by 2026-11-09: A-1 (`/health` leaked pilot and spend data), B-1 and B-2 (viewer GETs that wrote state), C-1 (worker routes accepted an owner session), C-2, C-3, C-4 (bridge shared the MCP token; fix needs the owner to set `FACTORY_TELEGRAM_BRIDGE_TOKEN`), C-7, D-2. Regression test: `test_route_auth_fixes.py` (112 lines).
- Still open: C-5, C-6, D-1, D-3, D-4, D-5, D-6, D-7, D-8.
- Confirmed adequate in that audit: token isolation between worker types, HMAC-signed media URLs, Telegram webhook secret plus paired-chat check, listener cookie separation from staff cookies.

### 3.2 Controls that exist

- Safety invariants in `CLAUDE.md` and `AGENTS.md`: no push to `main`, no force-push, no weakening of the approval gate, no automatic paid calls, no reading `.env`, no direct production deploy, no fabricated receipts or metrics.
- Worker tool boundary: allowlist of tools for ROADMAP runs (`Read`, `Edit`, `Write`, `Glob`, `Grep`, `python`, `git status/diff/log/show/add/commit`, `ls`, `mkdir`) and a deny-list (`git push`, checkout of main, `git reset --hard`, `render`, `gh workflow run`, `gh pr merge`) (`autopilot/delegation.py:64-101`). Relay-ticket runs use the deny-list only (`autopilot/relay_tasks.py:250-251`); `--dangerously-skip-permissions` is added only when `AUTOPILOT_SKIP_PERMISSIONS=1`, which `docker-compose.autopilot.yml:11` sets and whose value on EC2 is **unknown**.
- Push evidence: the runner snapshots remote refs before and after a run; a changed remote ref marks the result failed (`autopilot/delegation.py:123-138`); the server rejects a "done" without exactly one captured commit (`app.py:567-598`).
- Secret handling: env-only secrets; vault as above; redaction regexes on worker output and Relay notes (`relay_execution.py:27-37`, `autopilot/relay_tasks.py:209-211`); credential-shaped message bodies refused (`agent_secret_scan.py`); provider error bodies never stored for YouTube and LinkedIn.
- Signed media: `/media-archive/*` and `/media-source/*` need an HMAC token (`docs/security/2026-11-route-auth-audit.md`, "Checked and found adequate").
- Tenancy: jobs are the tenancy root; members are limited to an allowlist of routes and their own workspace (`workspace_tenancy.py` docstring); server publisher credentials are not shared across workspaces (`app.py:9552-9554`).
- Evidence protocol: levels claimed < linked < checked < accepted; only the server writes checks; `publish` needs the owner (`evidence.py:1-33`).
- Peer review: Gemini reviews risky PRs (auth, tokens, vault, payments, budgets, publishing, CI) after green CI, 20 per day (`peer_review.py` docstring).
- Audit trails: `approval_decisions` table, Relay ticket history, `mcp_call_log`, delegation-control audit (last 200 entries, `app.py:13347`), job `event()` log, workspace ledger (14-day retention).

### 3.3 What is missing for an autonomous agent that handles money

Each item is my inference from the code unless a document is cited.

1. Approver identity and step-up. Approval is one authenticated POST; `actor` is always `"owner"` (`app.py:8790`); no second factor, no per-action confirmation code, no record of who or from where.
2. Session hygiene. Static non-expiring owner token (`app.py:332-337`); no login rate limit (D-8, open); fail-open if `FACTORY_PASSWORD` is empty (D-6, open; `app.py:372-375`); production value never checked by the audit.
3. Shared machine credential. One `FACTORY_MCP_TOKEN` for all AI clients, accepted in the URL (D-1, open). `web_surfer.py:17-19` states the `agent` argument "is never treated as an authenticated identity".
4. Web-content injection. Raw page text goes to the calling model. A logged-in session can be used for reads, so a hostile page could try to steer an agent that also holds write tools elsewhere. The repo's defences are tool restriction and labels, not detection.
5. No money primitives. No ledger of income, no payment provider, no refund path, no reconciliation, no per-counterparty limits, no dual control.
6. No tamper-evident log. Logs are SQLite rows and JSON files on the same disk as the app; nothing is hash-chained or shipped off-host.
7. No backup or restore procedure in the repo; single 1 GB disk; SQLite; one process (`durable_engine.py:14-15` says the SQLite system DB serves exactly one process).
8. No global emergency stop (see §2.3).
9. Configuration drift. 182 distinct environment variable names are read in non-test Python (Grep count) against about 25 declared in `render.yaml`; the rest live only in the Render dashboard.
10. Infrastructure review never done (baseline "Not covered"): Render and AWS IAM, the EC2 host that holds the Claude, Gemini and Codex logins and the GitHub credential.
11. SSRF review outstanding (baseline finding 5). The outbound MCP client accepts any `http://` or `https://` endpoint with no private-address check (`app.py:12590-12592`); owner-configured, so low likelihood, but a viewer GET can trigger the call (D-5).
12. Repository integrity. The 2026-11-17 overwrite of `main` (`DECISIONS.md:1841-1848`) shows the owner's own account was the largest risk to the codebase until branch protection was added that day; the recovery itself used a force push, which `CLAUDE.md` forbids, under an explicit one-off owner permission.

## 4. Control planes and task flow

### 4.1 Documented flow

Owner writes in Telegram or opens a GitHub Issue → Relay ticket `R-xxxx` (`queued`) → EC2 worker claims it
(`claimed`, `run_id`) → branch → PR → CI → Codex and/or human review → merge → Render auto-deploy after green
checks → result card in Telegram (`docs/guide/how-factoryos-works.en.md` §3). ROADMAP tasks take the same claim
path since T-599: one Relay ticket per task, `run_id` fenced (`ROADMAP.md`, T-599 progress notes).

### 4.2 Stores that hold tasks, messages or decisions

| # | Store | Location | Writers |
|---|---|---|---|
| 1 | ROADMAP queue | `ROADMAP.md` in git (964 lines) | Owner, Claude, planners |
| 2 | Relay tickets | `DATA_DIR/relay.json` | Telegram, web `/relay`, Issue intake, ROADMAP claims |
| 3 | GitHub Issues | GitHub | Owner, ChatGPT (`Owner:` first line, `gemini` label) |
| 4 | Builder tasks | `factory_tasks` table in SQLite | Dashboard, MCP `submit_design_review` |
| 5 | Owner Desk questions and `[HUMAN]` runbooks | Question store; static runbook text | Owner, `/ask`, group bridge, MVP agents |
| 6 | Agent workspace threads and handoffs | `relay.json`, key `agent_workspace` | Claude, ChatGPT, Gemini lanes over MCP |
| 7 | Claude ↔ Codex inbox | `relay.json` | Two relay tokens |
| 8 | Telegram group threads and decisions | `telegram-group.json` | Owner in the group |
| 9 | Legacy Telegram bridge inbox | `telegram_owner.json`, last 100 messages | Any owner text also lands here (`app.py:1748-1756`) |
| 10 | Owner answers and decisions | `.autopilot/answers.md`, `DECISIONS.md` (1,965 lines) | Agents |
| 11 | Notion | External | ChatGPT, owner; one Claude session can read |
| 12 | Product-side queues | jobs, factory cycles, publishing queue, improvement proposals, experiments, MVP registry, battle runs, browser tasks | Dashboard and agents |

### 4.3 Where duplication and drift already show

- Notion states "GitHub Issues are the source of truth for tasks"; the coordination protocol states handoffs go "inside FactoryOS Relay, not through GitHub Issues/comments"; practice follows Notion (Issues #231-#242). The proof document leaves it "for the owner to settle" (`docs/handoff/NOTION_READ_PROOF_2026-11-05.md`).
- The coordination protocol is still a draft: "НЕ працюючий автоматичний зв'язок"; live two-way channel not verified (`docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, header and last paragraph; `CLAUDE.md`, Issue #94).
- One Telegram text creates a Relay ticket and is also appended to the legacy bridge inbox (`relay.py:1334-1338`, `app.py:1748-1756`).
- Two things are called "Autopilot": the content Cycle Control and the EC2 coding worker (`docs/guide/autopilot-cycle.en.md`, "Limits").
- Two Gemini coding paths exist side by side: the Issue → PR loop and the T-607 CLI worker (`docs/handoff/GEMINI_EC2_WORKER.md`, first paragraph).
- Merged code was not what ran: on 2026-11-10 the EC2 checkout was 26 commits behind `main` and ran the old runner (`docs/verification/R-0058_relay_e2e_2026-11-10.md`, F1).

Mitigations in place: a single claim primitive (`RelayQueue.claim_roadmap`) shared by the worker and MCP handoffs;
"assigned is not running" rendered everywhere from the same read model (`lane_board.py` docstring); Issue intake
links instead of duplicating when a `roadmap:T-xxx` ticket exists.

## 5. Architecture shape and cost of adding an adapter

- Size: `app.py` 13,742 lines / 817,351 bytes; 84 import lines; 727 top-level functions; 47 classes; 39 `CREATE TABLE` statements; 213 route decorators; 10 startup hooks. `relay.py` 2,067 lines; `owner_desk_i18n.py` 1,458; `smoke_tests.py` 1,370. `static/index.html` 1,072,890 bytes.
- Churn: `app.py` changed in 43 of the 98 visible commits (`git log --oneline -- app.py | wc -l`).
- Pattern for newer features: a module with pure logic and an `install_*_routes(app, …)` function that receives callables (identity, worker auth, clock, HTTP transport). 29 such install calls in `app.py`. Network is injectable, so tests run with zero network (`youtube_publisher.py:11`, `linkedin_publisher.py:12`).
- What a new outward adapter still has to touch in the core, judged from T-700 (commit `eeadcd1`) and T-552-YT (`133450b`): import and wiring in `app.py`; `OAUTH_FLOW` adapters dict (`app.py:11196`); `PORTABLE_INTEGRATIONS` and `CONNECTIONS` (`app.py:2049-2071`); the `if/elif` dispatch in `_publish_via_adapter` (`app.py:9562-9565`) when it joins the media publish queue; the auth middleware bypass list for any token-authenticated route (`app.py:1426-1436`); `oauth_framework.PROVIDERS`; the member allowlist in `workspace_tenancy.py`; the single-file dashboard and three locales (`test_locale_parity.py`); a CI step.
- There is no adapter registry or interface that the core discovers. `connection_capabilities.py` (95 lines) only projects connection status for the UI. `mods_registry.py` lists switchable worker skills and video tools; `mods/` holds three vendored Claude Code plugins loaded with `--plugin-dir` (`mods/README.md`).
- The lowest-touch extension point that already exists is the outbound MCP client (owner adds an endpoint, an env-var name and a tool allowlist; `app.py:4133-4258, 12574-12660`). It is manual-call only and still marked configuration-only.

Judgement (inference): adding a read-only or owner-triggered adapter is cheap, about one module plus 5-8 small
core edits, as the three-day YouTube and one-day LinkedIn additions show. The monolith is a maintenance and
review risk, not a blocker to adding adapters.

## Counter-evidence and caveats

- The shallow clone hides history before 2026-11-13. Older live evidence is taken from README and ROADMAP notes written by the agents themselves; these are self-reports, though they are specific (deploy IDs, CI run IDs, SHAs).
- "Live-verified" here means "the repository records live evidence". I did not call the live host, so nothing was re-verified today. Production environment values (password set, adapter selected, keys present) are unknown by design.
- Safety engineering is unusually careful for a solo project: fail-closed defaults, honest "unknown" states, idempotency, uncertain-outcome handling, zero-network tests, a self-run route audit with regression tests, and explicit "not verified" language. A sceptical reading should not understate this.
- The absence of a payment adapter may be deliberate sequencing rather than neglect: the policy forbids payment actions without approval, and there is no validated offer yet.
- The Surfer benchmark numbers (12 of 31 fully useful) are from before the fix; the fix exists but its production re-run is recorded as not started, so current quality is unknown, not necessarily poor.
- The YouTube claim that unaudited API projects are limited to private uploads comes from `docs/research/oauth_providers.md` (repo's reading of Google's revision history on 2026-11-01). I did not re-check it; it should be verified against Google's current documentation before it is used in the report.
- Metricool plan price and API-plan requirement are likewise the repo's reading of Metricool pages on 2026-11-01, not re-verified.
- The model names and prices hard-coded in `app.py:104-109` are code facts only.
- Member approval (claim 6) matters only if `FACTORY_WORKSPACE_MEMBERS` is set; with a single owner the practical exposure is the session-hygiene items, not members.
- Whether headless use of consumer subscriptions (Claude, ChatGPT, Gemini free tier) to produce output delivered to third-party MyCast listeners fits those plans' terms is not addressed anywhere in the repo.

## Implications for FactoryOS

1. The outside-world surface is almost entirely inward-facing. FactoryOS can read the web, write code, open PRs, talk to its owner on Telegram and synthesise audio. It cannot yet post publicly, e-mail anyone, take a payment or record a customer. A revenue loop needs four things that do not exist: an offer page with a payment link, a way to deliver to a paying customer, a way to reach prospects, and a record of who paid.
2. The cheapest path to the first money does not need new autonomy. A hosted payment link from a provider that works for a Ukraine-based seller, plus the existing `FACTORY_MYCAST_ENFORCE_TRIAL` flag, would turn MyCast's trial counter into a paywall with one small adapter (webhook → grant days). That is a week of work in this codebase's pattern; it is blocked only by an owner decision on price and provider.
3. Stop building publisher adapters until one is used. Three exist and none has posted. The next step is `T-520` + `T-521` on YouTube or `T-700-H` on LinkedIn, done by the owner in under an hour each. If the YouTube private-only restriction is confirmed, LinkedIn text posts are the only zero-cost public channel that the code can drive today.
4. Free-tier capacity is a product ceiling. Listener episodes are capped at 10 per day and the Gemini free quota was exhausted on 2026-11-17 by search alone. A paid MyCast with more than about ten daily listeners requires a paid TTS budget, which the zero-spend policy forbids. The policy and the product are in direct conflict; the owner must price that in before selling.
5. Before any money moves, fix the cheap, high-value security items: refuse to start on Render with an empty password (D-6), add a login rate limit (D-8), give the owner session an expiry, drop `?key=` for everything except the one lane that needs it and set the lane tokens (`T-624`), record the real approver identity, and add an off-host backup of `DATA_DIR`. These are days, not weeks.
6. Add one runtime stop. A single owner-only switch (dashboard and Telegram) that pauses the worker, disables the publisher scheduler and refuses every provider call would replace a dozen environment flags that need a redeploy.
7. Collapse the control planes instead of adding more. Relay already has the claim primitive; declare it the only place a task can be claimed, treat GitHub Issues as intake only, keep Notion for narrative memory, and retire the legacy Telegram bridge inbox and the Builder `factory_tasks` list. The agent-workspace MCP (another store, not yet live) should wait until there is revenue to coordinate around.
8. Do not let the Surfer near write tools. It is safe today because it is read-only and its consumers are tool-restricted. The planned "submit with approval" step (T-560 trusted approval verifier) would make web content an input to an agent that can act; that needs real injection testing first, which the repo does not have.
9. The owner is the constraint. 16 open human tasks, including every market-facing one, against 89 finished agent tasks means more agent throughput yields nothing. The rational sequence is: owner clears two or three market-facing tasks, the system proves one paid delivery, and only then is more autonomy worth building.

## Sources

Only files actually opened or commands actually run.

- `CLAUDE.md`, `AGENTS.md`, `GEMINI.md`, `README.md`, `README_RENDER.md`, `MORNING_QA_2026-10-19.md`, `ROADMAP.md` (searched and read in parts), `DECISIONS.md` (searched; sections T-560-F, T-700, incident 2026-11-17), `.autopilot/answers.md`, `.env.autopilot.example`, `.gitignore`, `render.yaml`, `requirements.txt`, `docker-compose.autopilot.yml`
- `app.py` (searched; read lines 86-125, 262-610, 1629-1795, 1797-1979, 2044-2071, 4118-4258, 8781-8801, 9484-9703, 10888-11045, 11170-11369, 11646-11711, 12352-12394, 12574-12660)
- `relay.py` (805-979, 1320-1439), `relay_execution.py`, `relay_agent_messages.py`, `team_tasks.py`, `lane_board.py`, `operator_lanes.py`, `supervisor_routing.py`, `owner_desk.py`, `evidence.py`, `release_guardian.py`, `security_findings.py`, `peer_review.py`, `voice_transcribe.py`, `workspace_tenancy.py`, `morning_brief.py`, `battle_runs.py`
- `telegram_group.py`, `telegram_battles.py`, `telegram_web_compare.py`
- `youtube_publisher.py`, `linkedin_publisher.py`, `oauth_framework.py`
- `browser_tasks.py`, `web_surfer.py`, `browser_runner/__init__.py`, `core.py`, `social.py`, `egress_proxy.py`, `playwright_executor.py`, `vault.py`
- `agent_workspace.py`, `connection_capabilities.py`, `mods_registry.py`, `mods/README.md`, `frontend/connections_catalog.js`
- `gemini_proxy.py`, `durable_engine.py`, `durable_media_finisher.py`, `media_finisher_worker/README.md`, `media_finisher_worker/app.py` (grep)
- `mycast.py` (grep), `mycast_calendar.py`, `mycast_listener_delivery.py`, `mycast_library.py` (grep), `mycast_accounts.py` (grep), `mvp_factory.py`, `mvp_evolution.py`, `mvp_cycle.py`, `mvp_quiz.py` (grep), `faceless_crm.py`
- `autopilot/autopilot.py`, `delegation.py`, `relay_tasks.py`, `claude_pro_worker.py`, `control.py`, `supervisor.py`, `gemini_worker.py`, `codex_relay_worker.py`, `browser_tasks.py`, `mycast_daily.py`, `mycast_listeners.py`
- `deploy/gemini-worker/factoryos-gemini-worker.service`, `deploy/systemd/*`, `deploy/codex-relay/factoryos-codex-relay.timer`
- `.github/workflows/ci.yml` (grep), `factory-builder.yml`, `gemini-coder.yml`, `mycast-render.yml`, `release.yml` (heads), `tools/gemini_issue_pr.cjs` (grep)
- `docs/security/2026-11-02-baseline.md`, `docs/security/2026-11-route-auth-audit.md` (lines 1-367)
- `docs/research/metricool_api.md`, `docs/research/oauth_providers.md`
- `docs/guides/browser-agent.md`, `docs/guides/surfer-mcp.md`, `docs/guides/agent-workspace-mcp.md`
- `docs/verification/surfer-benchmark-2026-11-16.md`, `docs/verification/R-0058_relay_e2e_2026-11-10.md`
- `docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md`
- `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, `docs/handoff/NOTION_READ_PROOF_2026-11-05.md`, `docs/handoff/GEMINI_EC2_WORKER.md`
- `docs/RELAY.md`, `docs/guide/telegram-commands.en.md`, `telegram-relay-proof.en.md`, `oauth.en.md`, `how-factoryos-works.en.md`, `autopilot-cycle.en.md`, `gemini-coder.en.md`, `docs/specs/EVIDENCE_PROTOCOL.md`
- Git commands: `git log -1`, `git log --oneline | wc -l`, `git rev-parse --is-shallow-repository`, `git shortlog -sn`, `git log --format=… -- <file>` for the adapter modules, `git log --oneline -- app.py | wc -l`, `git log | grep -i codex`, `git branch -a`
