# Blackbox Lab — FactoryOS

Private AI content production control room for Blackbox Lab.

FactoryOS orchestrates specialized AI workers through a visible production pipeline while preserving a human approval gate before publishing. The service is deployed on Render from `main`.

## Active roadmap

The living technical specification and progress tracker for the next major product cycle is here:

- [FactoryOS v4.0 — Technical Specification & Roadmap](docs/roadmap/FACTORYOS_V4_TECH_SPEC.md)
- [FactoryOS v4.5 — AI Editing / Media Finisher](docs/roadmap/FACTORYOS_V4_5_AI_EDITING_SPEC.md) — **DONE**: real uploaded-video production pilot verified end-to-end, with word-level ASR, deterministic cuts, captions/graphics, audio finishing, QA frame samples, traceable artifacts and return to HUMAN APPROVAL.
- [FactoryOS v4.6 — Video → Approval → Publishing](docs/roadmap/FACTORYOS_V4_6_VIDEO_PUBLISH_SPEC.md) — **IN PROGRESS**: bind the exact final Media Finisher artifact to approval, publishing, real platform receipt and analytics.
- [FactoryOS v4.7 — Direct Raw Video → Publishing](docs/roadmap/FACTORYOS_V4_7_RAW_VIDEO_PUBLISH_SPEC.md) — **IN PROGRESS**: carry direct owner-uploaded video through Media Finisher, zero-spend publish pack, approval and the same immutable publishing boundary.
- [FactoryOS v4.8 — Durable Finished Media](docs/roadmap/FACTORYOS_V4_8_DURABLE_MEDIA_SPEC.md) — **DONE**: finished worker media is persisted on the FactoryOS disk before approval; live post-redeploy inventory verified 5/5 archived videos present with 0 missing.
- **FactoryOS v5.0 — Builder Autopilot — READY TO MERGE**: repository-driven autonomous engineering loop with machine-checkable roadmap tasks, isolated Claude Code runner, explicit HUMAN blockers, decision log, runtime status in Build Progress and CI guardrails. Source of truth: `ROADMAP.md`.

This document is the source of truth for milestone status, Definition of Done, progress checkboxes, known gaps and the next action from v3.25 through v4.0.

## Product changelog

Versioning rules (2026-11-16): `APP_VERSION` in `app.py` is the only version. The dashboard header, the sidebar badge
and `/health` all show it, and `test_versioning.py` fails CI if this changelog's first entry, the sidebar fallback and
`APP_VERSION` disagree. Minor = new features, patch = fixes only. A release PR bumps the version and adds its entry
here; after it merges, `.github/workflows/release.yml` tags the merge commit and publishes the GitHub Release.
v5.8.0 and v5.9.0 below were written on 2026-11-16 from the merged PRs of their weeks: the app showed `v5.7.1`
during that time. v5.9.0 ends at #252 (2026-11-08); the later merges of that day (#266, #288, #290–#295) and
#297, #298 are in v5.10.0.

### v5.19.0 — Surfer requests mirrored for the owner — 2026-11-23

- `surfer_pending` (MCP, Claude lane only, read-only): what the Surfer waits for from the owner right now — a step to confirm, a code or login, a takeover — with a short RU/UK/EN text and the link to the Surfer page, so Claude can mirror it as tickets on the owner task page. No screenshots, values, codes or URLs; answering stays on the Surfer page (T-726, #458).

### v5.18.2 — Surfer worker never stays stuck on one page — 2026-11-23

- Surfer: every action command has a 90-second deadline. A page that never answers (a script that does not return) no longer blocks the Surfer worker: the browser is killed, the step reports `worker_timeout`, the session closes and the next session or page read gets a fresh browser. Also: the link-click wait follow-ups (#457) (#459).

### v5.18.1 — Surfer: a link click waits for in-page navigation — 2026-11-23

- Surfer: after a click on a link, the agent's snapshot waits briefly for the URL to change, so sites that navigate in-page (GitHub, single-page apps) show the new page instead of the old one. Found in the first clean live session (open the repo page → click Issues) (#456).

### v5.18.0 — Surfer: login choices, no false code wall — 2026-11-23

- Surfer after the first live session: a code (2FA) wall needs a field that looks like the code box, so a page that only mentions SMS codes no longer stops the agent; the site's "vault login" list shows passwords and saved browser sessions; a new login can be bound and saved after the owner signs in once with Take over; "How the Surfer signs in" help on the Surfer page with a link to Access vault (`/#vault`); the stray "null" under "Add a site" is gone (#455).

### v5.17.0 — Surfer acts on allowed sites, Google Sheets for agents, post images, Surfer worker — 2026-11-21 … 2026-11-23
- **Surfer actions (new):** the browser agent can click, fill forms and upload files in the owner's signed-in
  accounts, driven by Claude / ChatGPT through MCP (`web_open`, `web_act`, `web_snapshot`, `web_close`) with their
  own lane key. One live page at a time on the Surfer worker; passwords are filled only by vault reference and never
  shown; every step is in the action log (T-720, #448).
- **Surfer policy gate:** off until the owner sets `FACTORY_SURFER_ACTIONS_ENABLED=1`; an allowlist of sites with
  action classes that starts empty; payment, delete, security settings, messages to people, publishing and anything
  outside the list wait for the owner's confirmation; login walls, captchas and SMS codes go to the owner and are
  never solved; daily caps (T-721, #449).
- **Surfer page** `/static/surfer/index.html` (RU/UK/EN): the open session with screenshots, Confirm / Reject / Stop,
  a box for the SMS code, Take over, the allowlist, a pause switch, approved upload files, the action log. Owner
  runbook T-722-H (T-722, #450).
- **Surfer recipes:** a successful session saved as a recipe with parameters and replayed without AI under the same
  rules (`web_recipe`); it stops at the first mismatch (T-723, #451).
- **Surfer self-test:** one scenario on a fixture site, in CI with a page double and in real Chromium on request
  (T-724, #453).
- **Google Sheets for agents:** `sheet_list` / `sheet_read` / `sheet_append` through the official Sheets API, only for
  spreadsheets the owner added, off until `FACTORY_GOOGLE_SHEETS_ENABLED=1`; page `/static/sheets/index.html`
  (T-725, #447).
- **Social autopilot:** every post gets a teaser image (Telegram photo, LinkedIn Images API) (T-713, #444).
- **Surfer worker:** browser tasks run in their own process on EC2 with a Surfer lane in Worker Center and a
  loop-heartbeat watchdog; owner step T-714-H installs the unit (T-714, #445).
- **Rules and answers:** a promise to report back is always scheduled (#446); owner answers of 2026-11-21 (#441).

### v5.16.0 — Launchpad Discovery agents, agent workspace panel, AI Video Editor decisions, worker catch-up — 2026-11-21
- **MVP Builder · Launchpad (Business League L2):** the manual MyCast D1–D3 run is imported as the benchmark (the
  MyCast board no longer starts empty; its G1/G2 stay proposals), an owner-started Discovery run fills D1–D3 from
  fetched public sources on the free Gemini key, and the Launchpad page shows a read-only comparison of agent output
  against the benchmark (EN/UK/RU). A quote, price or date that is not in the fetched text becomes "unknown" (T-705, #439).
- **Worker Center:** a panel for the shared agent workspace, inside the technical details (T-626, #439).
- **MVP workers:** versioned contracts for the 13 logical roles (T-631, #439).
- **AI Media Finisher → AI Video Editor v1:** word-safe edit decisions with reasons, confidence and undo, a measured QA
  report and render metrics as review evidence; a final file that does not decode fails the job. No real render or
  pilot is claimed yet (R-0089, #428).
- **Owner Issue intake:** GitHub Issues are polled every 120 s instead of 300 s (#413).
- **EC2 worker:** it was 50 commits behind `main` since 2026-11-17 because of a merge conflict; it is back on current
  code, so the Surfer fix for ids with dots (T-674) now runs on production reads.
- **Docs:** FactoryOS architecture map (#417); Film Studio 45 s storyboard package, rights-gated (#435).

### v5.15.0 — Business League Launchpad in MVP Builder, MyCast render without apt — 2026-11-20 … 2026-11-21
- **MVP Builder · Launchpad (Business League L1):** a board per project that takes an idea to first sales through
  checks D1–D7, a 7-day MVP, channels and gates G1–G5. Facts need a source and a date, missing data stays
  "unknown", a zero is shown as zero, test and synthetic records are never counted, and likes or views are not
  demand. No agent decides a gate on its own work; spend and outreach approvals are the owner's. The page
  (`/static/mvp-factory/launchpad.html`, UK/RU/EN) is read-only and is linked from every project card; MyCast is the
  first board and starts empty. Nothing is posted, sent, advertised or charged (T-704, #432).
- **MyCast daily render:** the render job needs no apt — FFmpeg comes from a pip package and the job takes about
  half a minute; the MP3 is checked by decoding it in full (#431).

### v5.14.0 — "Forgot password?" sign-in link through Telegram, MyCast daily render — 2026-11-19 … 2026-11-20
- **Login:** "Forgot password?" on the FactoryOS login page: send `/login` to the FactoryOS bot from the paired private
  Telegram chat and get a one-time, 10-minute sign-in link; the password itself is not shown or changed (T-712).
- **MyCast daily render:** sources without a link, branch sync, speakable text and audio QA (MC-01, #426); the
  render workflow skips the unconditional apt step, caches the voice and tests sync-before-publish (#429).
- **MyCast demo voicing:** one manifest snapshot per run (follow-up to T-711).

### v5.13.0 — MyCast glass profile page, social publishing, Surfer signed-in reads — 2026-11-17 … 2026-11-19
- **MyCast:** the profile page `/mycast/u/<slug>` has the same glass coverflow as the episode page, with UK/RU/EN by
  `?lang=` (T-710); "My podcasts" is in the configurator header and in the share step (T-703, #422); each demo city
  has its own pair of hosts for the owner's voicing (T-711); "Help us improve" quiz with an analyst loop (T-634, #412).
- **Social publishing, always behind the owner's approval:** LinkedIn text posts (T-700, #414), OLX adverts through
  the OLX Partner API (T-701, #421), weekly plan with exactly-once scheduled publishing (T-702, #420).
- **Surfer:** opens pages signed in with a saved vault login (T-560-L, #418); reads GitHub release pages and ids
  with dots in full (T-674, #419).
- **Worker Center:** server-side Telegram ↔ site check and a simpler view (T-592, #416); worker sync resolves
  ROADMAP-only merge conflicts by itself (T-673, #411).
- **Planning:** Business League L1 spec queued (T-704, #423); owner tasks and MyCast discovery benchmark (T-705, #424).

### v5.12.0 — Watchable video duel, releases for every version, main restored — 2026-11-17
- **Video duel** (T-MODS-E): every take plays in its card (9:16 player); the worker's runner uploads the product-film
  render of a B take, the owner can upload any take; only a real MP4 up to 80 MB is kept, with size, sha256 and
  uploader shown under the player; 1–5 stars to score.
- **Releases:** v5.9.0 published on #252, so every version from v5.6 to v5.11.0 has a GitHub Release (#407, #408).
- **Repository:** `main` restored to v5.11.0 after an activity-generator overwrite; `main` is now protected against
  force pushes and deletion (owner ruleset, 2026-11-17).

### v5.11.0 — Surfer for AI agents, Content making-of, guides in RU/UK, MyCast demo voices — 2026-11-16
- **Surfer:** live benchmark of 33 real read tasks and fixes so any AI can use it mid-project: main page text without
  menus, links, HTTP status, long pages in chunks, hints for every blocker, anti-bot pages reported as needing a
  human, private IP literals refused in the executor too (#405). Web search tries `gemini-flash-lite-latest` and
  moves to the next model on 429, at most 3 calls (#400).
- **Content / Promotion:** runs interrupted by a restart are closed; clicking a content row opens its own pipeline,
  where it stopped and the agent chain with errors and next steps (#404).
- **Guides:** /learn guides in RU/UK/EN and 7 new "how it works" guides (#402).
- **Autopilot:** server error and status messages of Cycle Control in EN/UK/RU (#401).
- **MyCast:** owner-triggered Gemini voicing of the demo cities on the share page, played only after owner approval
  (#403).
- **Releases:** release workflow can backfill past versions; owner runbook for the one-time v5.9.0 release
  (#396, #397, #398, #399).

### v5.10.0 — Evidence, MVP Builder, Brand Strategy, Durable Engine, Mods & Skills — 2026-11-08 … 2026-11-16
- **Version sync and releases:** the sidebar badge (was a hard-coded `v5.3`), header and `/health` now all show
  `APP_VERSION`; changelog restarted from v5.6; git tags and an automatic GitHub Release workflow.
- **Owner tools:** owner voice messages → Gemini transcript → text Relay ticket (#295); route audit fixes and the
  FactoryOS Team group bridge (#297); morning brief at 08:00 Kyiv and P2 regressions (#298); Queue Keeper reads
  "Depends: none" (#292); ChatGPT lane taken over by Claude (#293).
- **Relay:** per-ticket branch + PR round trip with CI/merge back to Telegram (#294).
- **MVP Builder M1B–M1D** build request (#288); evidence-command visual concept (#266); MyCast sub-topics, voice
  history and calendar wishes (#290, #291).
- **Evidence Protocol** (#299, #300, #301, #303, #304, #306): No Evidence — No Done; CI read from Actions runs; deploy
  check against Render; owner accept buttons; Proof panel in Agent Office; Gemini reviews risky or large Claude PRs.
- **Security:** encrypted vault AES-256-GCM with Access vault UI (#302); server GitHub reads use the read-only token
  (#301); Cookie-Editor paste for vault sessions (#355, #356).
- **MVP Builder:** cycle Battle → Build → Promote → Learn with five agents and agent chat (#310); autonomous hand-off
  with evidence and an owner gate before build (#311); Faceless Creator brief (#330) and Faceless Models CRM (#360);
  A/B Tester S1–S3 (#371, #373, #376, #389); AI Release Guardian (#383); AI Decision Memory pilot (#384); MyBrief for
  a profession (#386); Product Evolution S1 (#392).
- **Brand strategy → Master Brief** (#357, #358, #361): 7-step passport, monthly content plan with pillar × funnel
  matrix, plan row → job, agents follow the Master Brief.
- **Durable engine** (#379): DBOS Transact inside FastAPI and a durable AI Media Finisher (stages 0–1).
- **Mods & skills** (#390): sidebar section with one-button switches for poteto-mode, grilling, product-film and the
  brand-strategy pipeline; with/without numbers for worker runs; video duel A1/A2 against B1/B2.
- **Agents and Relay:** Claude ↔ Codex agent relay (#318, #324, #325, #326, #328, #331); browser agent task queue,
  EC2 worker, saved vault sessions (#334, #335, #339, #349, #350); Surfer web tools for every connected agent over MCP
  (#375, #381, #388); shared agent workspace tools on `/mcp` (#391); Gemini worker on the owner's Google login (#387);
  verifiable Telegram acceptance `/proof` (#393); Autopilot Cycle Control for beginners (#395); Relay runs limited to
  60 turns / 30 min (#362); blocked-task wake loop fixed (#382).
- **Publishing:** direct YouTube publisher with Google OAuth (#377). Real posting still needs owner approval.
- **MyCast:** episodes 1–30 min (#322), episode history (#329), mycast.pro with privacy/terms, robots and sitemap
  (#333, #349), Google Calendar read-only (#341), header sign-in and public podcast page (#344, #345), referral +7
  after a friend's first episode (#363), MVP V1 library and revocable public links (#385), share card (#394),
  accurate daily reports (#315, #316, #317).
- **Dashboard:** owner feedback round (#308), MVP Builder on the dashboard (#309), Content / Promotion rename (#320),
  local open questions on home (#323), owner console for background modules (#336–#338), Learning section and the
  cinematic explainer (#364, #366), Approval Studio fixes (#374).

### v5.9.0 — Gemini Lane, Team Tasks, MyCast Beta, Relay Round Trip — 2026-11-03 … 2026-11-08
- **Gemini lane:** Gemini CLI Actions with least privilege, then manual only (#131, #178); Issue → PR pipeline (#146);
  model update, timeout, 503 backoff and Flash fallback, error detail, night shift (#143, #148, #149, #157, #158);
  every 5 minutes on EC2 with the key kept in Render (#164); Google's real status and key check (#209, #210);
  Gemini-written tests and guides (#162, #183–#185, #191–#193, #196, #197, #214, #224, #225, #227, #228, #230, #243,
  #247, #250, #252, #257, #268).
- **Team and owner tools:** Team tasks page with PR/CI status and EC2 GitHub fallback (#182, #198, #251, #253);
  Telegram `/workers` per executor (#159); owner desk cards (#249); Queue Keeper counts (#245).
- **Relay:** intake through the EC2 GitHub snapshot (#254, #262); dirty-path reporting and `.autopilot/` as runtime
  space (#276, #277); worker sync never rebases (#211).
- **Security:** route authorization inventory (#145); publish approval gate and findings schema (#246).
- **MyCast:** full episode by 06:00 Kyiv (#222), owner-feedback format (#226), audio QC and source/date gate (#244),
  configurator on the site and beta batches (#263, #267, #271, #278, #279, #280), Gemini voice picker and Telegram
  pairing (#284), 7 free days + 7 per friend (#285).
- **MVP Builder / MVP Factory:** phase 1 registry, API and overview (#271); M1A build request contract (#287); AI
  Hangout pack (#223).

### v5.8.0 — Operator Lanes, Relay Control Room, Browser Runner, Builder Autopilot Hardening — 2026-10-27 … 2026-11-02
- **Operators:** FactoryOS roles separated from operators; live Claude and Gemini operator telemetry; Telegram Claude
  and Gemini lanes (T-580); dependency-aware scheduler and task owner lanes (#62).
- **Browser Action Runner** (T-560-A/B/C, #35): contracts and policy engine, isolated session registry with human
  takeover, guarded Playwright executor with a zero-spend fixture.
- **Workers:** zero-PAYG self-healing Runner Supervisor (T-562); per-EC2 worker credential and secure interactive
  pairing (T-563, T-564, #44); Python 3.9 on AWS EC2 (#59); reboot-proof worker venv (#73); worker reloads runner code
  (#84); pause the whole queue on a Claude subscription limit (#81).
- **Relay:** Telegram live control center with status, GitHub CI and history (#42); real Claude queue, heartbeat and
  execution history (#43); lifecycle integration (#63); Telegram worker states and `/work` retry fixes (#64, #65);
  verified server-side ROADMAP claims and factual run events (T-599, #68–#71, #80).
- **Dashboard:** six semantic multilingual navigation groups (#66); CI dashboard screenshots for UI tasks (#82);
  owner desk with step-by-step HUMAN runbooks (#83, #112); UI fixes from the screenshot review (#108).
- **Security:** security baseline (#109); Python 3.13 pin, dependency floors and pip-audit in CI (#116).
- **MyCast:** pilot episode with zero-spend TTS (#110); daily episode script, render and Telegram audio (#117); Gemini
  two-host voices with Piper fallback (#127).
- **Docs:** Claude ↔ ChatGPT coordination rules (#95); OAuth provider research (#91); Metricool access audit (#90);
  Gemini onboarding (#121); MCP handoff protocol spec (#128).

### v5.7.1 — One-tap Relay Telegram Pairing — 2026-10-26
- Mobile Relay Telegram pairing and status controls.
- Runtime version advanced to `v5.7.1`.

### v5.7 — Relay Mobile Task Inbox — 2026-10-26
- Persistent Relay ticket journal with history and notes.
- Telegram auto-ticketing with inline actions, a mobile board, Operator-ready metadata and startup webhook sync.
- Zero-spend regression coverage.

### v5.6 — Native Gemini Omni Video Provider — 2026-10-26
- Native Gemini Interactions API video provider with URI delivery and durable media archival.
- Render configuration and zero-spend regression coverage.

### v5.5.1 — Production Runtime Observability — 2026-10-26
- Runtime version advanced to `v5.5.1`.
- Added a non-secret `PUBLISHER_RUNTIME` startup event with publisher adapter, scheduler state, Metricool readiness, reconciliation state, analytics adapter and queue counts; credentials are never logged.
- Production verification on Render: publisher scheduler enabled at 60-second cadence; durable archive inventory 5/5 present, 0 missing, 261,314,094 bytes.
- Production verification snapshot: publisher adapter remains `manual`, server-side Metricool credentials are not yet complete, publishing queue is empty, Approval has 4 waiting jobs and 0 approval decisions. Real posting therefore remains fail-closed.
- Closed obsolete PRs #17 and #19 so the repository keeps only the newer `autopilot/claude_pro_worker.py` runner architecture.

### v5.5 — Production Closure — 2026-10-26
- Metricool scheduler now normalizes the exact approved durable media into provider-hosted media before scheduling.
- Added Metricool reconciliation: scheduled items remain `publishing` until provider state proves publication; factual external ID/URL is persisted when available, provider failures remain failures instead of fabricated receipts.
- Added `POST /api/publishing/{publish_id}/refresh` and background reconciliation in the publisher scheduler.
- Enabled the publisher scheduler and reconciliation in the live FactoryOS Render service without bypassing the human approval boundary.
- Added resilient Termux Claude worker supervision: crash restart loop, wake-lock integration, protected local env file and Termux:Boot installer.
- PR #27 and its merge commit passed `syntax-and-smoke`; both FactoryOS and Media Finisher deployed successfully on Render.

### v5.3.1 — Account Portability Foundation — 2026-10-24
- Reworked Connections so Metricool, YouTube, Instagram, TikTok and HubSpot are provider slots instead of owner-specific identities.
- Added durable workspace/provider binding metadata plus owner-only Connect / Disconnect / Change account actions. Disconnect never deletes jobs, artifacts, approvals or analytics.
- Removed the hard-coded TikTok account label from runtime state.
- Disconnecting Metricool now fences the real publishing transport; disconnecting an individual social channel fences that destination.
- Added HubSpot to Connections as the CRM / Growth slot. The standalone product intentionally does not reuse the separate ChatGPT HubSpot OAuth grant.
- Added the v5.5 sellable-workspace roadmap for provider OAuth, encrypted token storage, full tenant scoping and customer A → customer B replacement acceptance.
- Architecture and current boundary: [docs/ACCOUNT_PORTABILITY.md](docs/ACCOUNT_PORTABILITY.md).

### v5.3 — Metricool Publisher Adapter — 2026-10-23
- Added a native server-side Metricool publisher adapter for Instagram Reels, TikTok and YouTube Shorts.
- Metricool receives only the immutable metadata snapshot frozen at human approval plus the exact approved final video URL; later Content Package edits cannot drift into the scheduled post.
- The adapter uses Metricool's scheduler endpoint and keeps the API token server-side. User ID / brand ID / token are runtime configuration, never frontend values.
- FactoryOS explicitly declares AI-generated/AI-edited content in platform-specific fields for Instagram, TikTok and YouTube.
- YouTube `madeForKids` must be explicitly configured; FactoryOS refuses to guess that compliance setting.
- A Metricool scheduled-post ID is stored only as provider scheduling evidence and is never treated as a real platform post ID. Final publication still requires a factual platform receipt.
- T-519 is closed. T-520/T-521 remain HUMAN gates for Metricool API credentials and the first owner-approved real external post.

### v5.2 — Analytics Return Provenance — 2026-10-23
- Closed safe roadmap task T-522 without weakening the real-publisher HUMAN gates.
- Every persisted performance snapshot now records the factual external post ID/URL plus exact published media artifact, Media Finisher edit job, approved content snapshot hash, approval decision and workflow/experiment assignment.
- Missing platform metrics remain absent; the analytics path does not synthesize unavailable measurements.
- The only remaining v5 roadmap tasks are HUMAN gates: configure the first real publisher and approve/verify the first real external post.

### v5.1 — Viral Discovery Loop — 2026-10-23
- Closed T-510 provider-neutral Discovery acceptance with explicit source URL, platform, factual metric, timestamp, provenance and deduplication evidence.
- Added deterministic evidence-based breakout ranking using only supplied `breakout_score`, VPH, engagement and views; missing metrics remain missing instead of being imputed.
- Discovery Studio now shows rank position and the number of measured ranking signals for each candidate.
- Closed T-512 with traceable Discovery → Revideo → production lineage preserving the exact candidate ID and supplied performance evidence.
- Closed T-513 with a zero-spend deterministic acceptance path: Discovery → Revideo → three production variants → Content Package → Media Finisher fixture → QA → HUMAN APPROVAL.
- The T-513 acceptance explicitly proves that no publishing queue item is created before human approval.

### v5.0 — Builder Autopilot — 2026-10-23
- Added repository-native `ROADMAP.md` with machine-checkable DONE criteria and explicit `[HUMAN]` blockers.
- Added `CLAUDE.md`, `DECISIONS.md`, `.autopilot/answers.md` and a machine-readable status contract so autonomous implementation does not stop for ordinary reversible decisions.
- Added a Docker-isolated Claude Code runner with bounded turns, task timeout, three-failure stop, safe-branch enforcement and optional owner-only Telegram escalation.
- Autopilot pins one exact task per invocation, refuses a false `done` unless the ROADMAP checkbox really closed, then advances to the next non-HUMAN task.
- Build Progress now shows repository roadmap progress, next safe task, HUMAN blockers, runtime status and recent autonomous decisions in EN / UK / RU.
- Added dedicated autopilot unit tests plus compose, Python, smoke, HTML and JavaScript CI guardrails.
- No paid model calls, external publishing, production secrets or human approval boundaries are enabled or weakened by this release.

### v4.8.2 — Durable Media Closure Verification — 2026-10-23
- Added a production startup inventory check for durable AI Media Finisher archives.
- GitHub CI run `39933231662` passed on commit `d85db541aacebbbefbc2035ad871316aee4355ec`.
- FactoryOS deploy `dep-dbdim1k9v7es73e0ulh0` reached LIVE.
- After that fresh deploy, persistent storage verification reported **5/5 archived video artifacts present, 0 missing, 261,314,094 bytes**.
- v4.8 durable-media persistence/redeploy acceptance is now closed. Real social publishing remains the separate v4.6/v4.7 external-provider gate.

### v4.8.1 — Signed Archive Access Hotfix — 2026-10-22
- Fixed the auth boundary for durable finished-media URLs: signed `/media-archive/{id}` links now bypass the login middleware and reach their HMAC token validation, just like signed raw-media source URLs.
- Without this fix an external publisher could receive the correct durable URL but still get redirected/401 because it has no FactoryOS session cookie.
- Session-protected API/UI routes remain private; only the signed media path is public before token validation.

### v4.8 — Durable Finished Media — 2026-10-22
- Production inspection found a real release blocker: Media Finisher `/files/...` outputs lived on the worker's ephemeral filesystem and older verified pilot URLs returned 404 after worker redeploys.
- FactoryOS now detects worker-local finished-media URLs and streams masters / Shorts-Reels clips onto its own persistent Render disk before human approval.
- Durable copies record byte count, SHA-256, source URL, edit-job/artifact provenance and are served through signed `/media-archive/{id}` links.
- Artifact URLs, edit-job output URLs and matching persisted report URLs are rewritten to the durable FactoryOS link.
- Approval is blocked while the selected publishable video is still worker-ephemeral; archive failure is explicit instead of silently allowing a dead publish URL.
- External media URLs that are already durable are left untouched.

### v4.7 — Direct Raw Video → Publish Pack — 2026-10-22
- A video uploaded directly into AI Media Finisher no longer dead-ends at Approval Studio because it lacks the normal AI-generated Variant/Content Package.
- When a direct raw upload finishes successfully, FactoryOS creates a deterministic **zero-LLM-spend** source variant and Content Package from persisted transcript evidence plus owner-supplied job title/brief.
- The generated pack explicitly marks spoken claims as **not independently verified**, keeps CTA/hashtags empty by default, and never invents a thumbnail claim.
- Split-only jobs bind the actual Shorts/Reels clip — not the internal master — into human approval and the publishing queue.
- Direct raw uploads now follow one traceable path: upload → Media Finisher → QA → zero-spend publish pack → HUMAN APPROVAL → immutable publish snapshot → schedule → publisher.
- Existing jobs with partial normal production state are not silently overwritten by the synthetic raw-media pack.
- Zero-spend CI `39768976136` passed all compile/runtime/frontend checks; production commit `cf7357775e6ee7e8d71d61cf71a25588a0d98177` is LIVE on FactoryOS deploy `dep-dbcv090u01pc73bphrh0` and Media Finisher deploy `dep-dbcv026k1f9s73b3piug`, with clean startup and `/health 200 OK`.

### v4.6.2 — Immutable Approval → Publish Snapshot — 2026-10-22
- Approval now freezes the exact publishing metadata (title, description, CTA, hashtags and thumbnail concept) alongside the exact approved video artifact.
- The frozen snapshot is hashed and linked to the approval decision; post-approval Content Package edits can no longer drift into the publisher payload.
- Publishing idempotency now includes the approved metadata snapshot hash in addition to job, package, variant and media artifact.
- Publisher receipts preserve approval-decision, content-snapshot and final-media provenance.
- The publish endpoint now refuses unscheduled items; an explicit schedule action is mandatory before any manual or external publisher execution.
- Publishing Engine shows the approved metadata snapshot, snapshot hash, approval decision and exact approved media before execution.

### v4.6.1 — Exact Media Binding Hardening — 2026-10-22
- Runtime/UI version advanced from v4.5 to v4.6.1.
- Approval now resolves the video artifact from the latest exact Media Finisher edit job instead of choosing an arbitrary recent video.
- A finished render is invalidated for approval when the selected variant or Content Package changes after rendering; Media Finisher must rerun against the current production inputs.
- Regression coverage now proves stale media is blocked, then proves the newly rerun artifact is the exact asset carried into the publishing queue and publisher payload.

### v4.6 — Video → Approval → Publishing — IN PROGRESS — 2026-10-22
- Approval Studio now resolves the finished AI Media Finisher video as the primary review asset when an edit job exists, and blocks approval until the latest edit is READY.
- Publishing queue provenance is bound to the exact Content Package, selected variant and final media artifact; the media artifact participates in the duplicate-safe idempotency key.
- Publisher webhook payloads now include the approved final video URL/artifact plus title, description, CTA, hashtags and thumbnail concept from the Content Package.
- Manual and adapter publication paths persist Publisher receipts with external post ID/URL and final-media provenance, then synchronize the production job / Factory Cycle into published state.
- Publishing Engine now previews the actual bound video and exposes the real post URL; an optional due-item scheduler is available but remains disabled by default.
- Human approval remains mandatory. Real provider publication is not claimed until CI, deployment and one owner-approved external post are verified.

### v4.5 — AI Media Finisher — DONE — 2026-10-21 / 2026-10-22
- Added a separate Docker Media Finisher worker using FFmpeg, faster-whisper and a Remotion-capable renderer for deterministic short-form post-production; constrained workers use a CPU-safe FFmpeg overlay path.
- Added word timing, pause/duplicate cleanup, persisted cut lists, 1–3 word captions, jump-cut masking/push-ins, approved-text emphasis graphics, LUFS audio finishing and safe-zone evidence.
- Added traceable edit jobs/evidence in FactoryOS, stage reruns with parent lineage, final-video artifacts and forced return to HUMAN APPROVAL with no automatic publishing.
- Added direct raw-video upload to a selected production job. Uploads are stored as signed, unguessable source artifacts so the external Finisher worker can fetch them without weakening the private FactoryOS session boundary.
- Added in-dashboard Before/After video previews plus removed time, cut/caption/graphics counts, render stage and audio/safe-zone summary.
- Added deterministic QA frame sampling around selected cut boundaries and graphics moments; sample images are persisted with the edit report for visual review.
- Fixed callback/auth, cold-start recovery, source-download retry, Whisper/PyAV compatibility, server-side watchdog recovery and single-heavy-job serialization for the constrained Render worker.
- **Production pilot verified:** real uploaded source **349.7 s** → approximately **232 s** finished output, **126 cuts**, **103 caption groups**, **5 graphics**, edit job `1806649b-ca4f-4a0c-a9cd-5a7e7744328e` READY in **1592.41 s**, callback **HTTP 200**.
- A second serialized real-media job `1f276df4-a8c4-41e6-b29d-28ed3adebb12` also reached READY with callback HTTP 200, validating queue serialization and recovery.
- Human visual approval remains mandatory for each asset before publishing; v4.5 completion does not enable or bypass automatic publishing.

### v4.4 — Real Media Provider Foundation — 2026-10-20
- Added persistent asynchronous media jobs for Revideo with `queued → submitted → processing → ready/failed` lifecycle, provider job IDs, response/error persistence and duplicate-safe render visibility.
- Added provider polling through `FACTORY_VIDEO_STATUS_ENDPOINT` plus authenticated callback completion through `FACTORY_VIDEO_CALLBACK_TOKEN`.
- Revideo now exposes the latest media job, shows live render status in EN / UK / RU, prevents duplicate generation while a render is active and allows explicit status refresh.
- A completed provider result is persisted back to the Revideo project and saved as a real Render Agent video artifact for Worker Evidence.
- Added zero-spend regression coverage for the asynchronous media lifecycle; CI `39441923218` PASS.
- Production commit `7edec23c0d0258abb4978fcfbeab272d4260b97c`; Render deploy `dep-dbbnsjpsrm7s738fqbj0` LIVE with clean startup and repeated `/health 200 OK`.
- Completed a real Descript integration pilot in Blackbox Lab's Drive: Agent Underlord created an 8-second 1080×1920 / 30 fps composition and Descript published a real 1080p video successfully.
- **Status: DONE (provider-neutral foundation).** The generic media bridge and a real Descript provider path are verified. Runway runtime remains a separate adapter-specific verification backlog item and is not claimed as verified.
- Human approval and publishing remain separate; no automatic social publishing was enabled.

### v4.3 — Revideo / Original Rewrite MVP — 2026-10-20
- Added a dedicated Revideo workspace: source URL + transcript/source text → structure analysis → original rewrite → production job.
- Added persistent Revideo provenance and specialized Transcript Agent, Structure Analyzer and Rewrite Strategist worker evidence.
- Added originality guardrails: no blind source-media re-upload, no creator identity/voice imitation by default, no close-copy rewrite, and evidence boundaries remain explicit.
- Revideo output includes a new angle, hook candidates, rewritten script, caption, voice-over, originality notes and media brief.
- Revideo can hand off into the existing Variant → Content Package → Approval pipeline while preserving the source URL and worker artifacts.
- Added provider-neutral transcript and video webhook contracts. External video generation requires explicit confirmation and a fresh Content Package; no provider is hardcoded.
- If a configured video provider returns a real media URL, FactoryOS persists it as a Render Agent video artifact visible in Worker Evidence.
- No Revideo action publishes automatically.
- CI `39434473401` PASS; production commit `f7d7245db3f303f90a395377e44c360bbeb9fa34`; Render `dep-dbbn5aui0phs738nl4pg` LIVE with clean startup and repeated `/health 200 OK`.

### v4.2 — UX Clarity / i18n / Worker Transparency — 2026-10-20
- Added explanatory tooltips/help across Approval, Cycle Control, Content Brain, Variants, Package, Publishing, Performance, Experiments and Worker Results.
- Expanded EN / UK / RU product copy so workflow states and actions are understandable without reading technical logs.
- Worker cards now surface the selected-job result, output preview, mode/model, handoffs, token/cost accounting and artifact count; worker detail prioritizes the selected-job artifact.
- Approval Studio now explains what is being approved and distinguishes legacy/incomplete packages from current review-ready packages.
- Hardened UI rendering against non-string backend values and normalized structured artifact payloads before SQLite persistence.
- CI `39433576856` PASS; production commit `776266595cfd7a78d87490b4c9c6590006589fe1`; Render `dep-dbbn2h8473hc73dpqiig` was LIVE and then superseded by v4.3.

### v4.1 — Production Hardening / First Real LLM Pilot — 2026-10-20
- Ran the first fenced paid Factory Cycle on two real public source signals (Reuters + OpenAI) with one idea and a hard cumulative pilot ceiling of $0.75.
- Conservative preflight quote was $0.4636. The one-shot verification fence was persisted before the first provider call, preventing a restart from silently creating a second paid cycle.
- The first live pass uncovered a real SQLite writer-contention bug in the live variant persistence path after a completed model call. No publish action occurred.
- Hardened SQLite with a 30-second busy timeout and removed nested writer transactions by committing production-variant state before saving variant artifacts.
- Added a zero-spend regression that exercises the live variant persistence branch with deterministic fake workers, proving the production transaction path no longer deadlocks.
- Added resumable pilot execution on the same cycle and same original spend window, with a cumulative pilot budget guard applied to Content Brain, variant workers, Content Packager and live pipeline workers.
- Resumed the original cycle rather than starting over. The successful real pilot reached the human approval gate with cumulative measured provider cost **$0.188066**, **22 live runs** and **40,023 tokens**.
- Pilot result: `approval_gate_reached=true`, `publish_created=false`. Nothing was scheduled or published.
- Real pilot cycle: `15bea544-b055-44c6-84d4-833083c9befe`; job: `d0eeac5e-3fea-4fd2-bd22-2f15878101c2`; generated idea: **“AI’s Next Competitive Test: Turning Model Output Into Product Adoption”**.
- Hardening commit `7994b61f15c3d37dc80c70cf81dd80eeaafc6d6c`; CI `39424673537` PASS; resume deploy `dep-dbbm5j0ae00c7399k3t0` LIVE with repeated `/health 200 OK`.
- Next step is owner review in Approval Studio. Publishing remains a separate explicit action after review.

### v4.0 — Autonomous Content Factory — 2026-10-20
- Added persistent Factory Cycles that carry source signals, the selected idea, production job, workflow version, publishing receipt, factual performance and learning as one traceable lineage.
- Added a direct Content Brain → production bridge: verified ideas create linked production jobs without manual copy/paste, while preserving source provenance and the exact pinned workflow version.
- Added Autopilot orchestration that can collect/attach signals, generate and verify ideas, build production variants and a Content Package, and then **stops at the human approval gate**.
- Added explicit paid-work confirmation before Autopilot can start live model calls. Existing daily/job budget guards remain hard limits.
- Scheduled RSS collection can create a ready Factory Cycle from newly discovered signals, but never starts paid generation automatically.
- Approval, publishing state, real publish receipts and performance snapshots now synchronize back into the originating Factory Cycle.
- Added evidence-bounded cycle learning from real persisted metrics. Observed performance is never treated as causal proof; any workflow improvement becomes a controlled v3.90 experiment rather than an automatic production change.
- Added next-cycle lineage: a learned cycle can spawn a child cycle using only the currently owner-approved active workflow.
- Added mobile Autopilot / Cycle Control in EN / UK / RU.
- Zero-spend CI run `39406148458` passed the full deterministic closed-loop acceptance: signal → idea → production → package → human approval → publishing receipt fixture → real persisted metrics → learning → next cycle, plus compile/HTML/JavaScript checks.
- Functional commit `c02c568f3ad976286a7e8da5e7282013f06b4654`; production head `3cd54bba6aeaf0be33af863525ec3202b4aab7aa`; Render deploy `dep-dbbjsohsrm7s738a5bc0` is LIVE with clean startup and repeated `/health 200 OK`.
- No paid v4 production cycle and no real social post were executed as part of release verification.

### v3.90 — Self-Improving Factory — 2026-10-20
- Added evidence-backed improvement proposals with explicit hypotheses and concrete, allowlisted workflow changes.
- Added immutable workflow versions and locked job-level control/treatment assignment before the first worker run.
- Added controlled experiment objects that compare factual published outcomes plus measured production cost and duration; missing metrics remain absent.
- Added a production workflow fence: Supervisor proposals never auto-promote, safety/spend/publishing controls are not experiment-editable, and model changes are restricted to an explicit allowlist.
- Added manual owner-approved rollout, explicit reject decisions and rollback to the pre-rollout workflow version.
- Added Experiment Lab in EN / UK / RU for proposals, workflow diffs, arm assignment, measured comparison, rollout and rollback history.
- Added workflow/experiment attribution to published performance records so a result can be traced to the exact tested workflow version.
- Zero-spend CI run `39402528845` passed compile, deterministic control/treatment production, factual metric attribution, measured recommendation, manual rollout/rollback, HTML and JavaScript checks.
- Production commit `c9ef037db619b4e475bf9b66ed1c32442573a805` is LIVE on Render deploy `dep-dbbjeo1srm7s7389md60` with clean startup, configured LLM provider and repeated `/health 200 OK`.

### v3.80 — Performance Feedback Loop — 2026-10-20
- Added persisted time-series performance snapshots for views, reach, watch time, retention, completion, engagement and follower delta without fabricating unavailable metrics.
- Added published-content identity mapping and traceable attribution back to idea, Content Package, selected variant, angle/hook, variant worker run IDs, source evidence and measured production cost.
- Added cost-per-1k-views only when real views exist plus angle cohort comparisons using only available retention/completion values.
- Added manual analytics input and a provider-neutral webhook analytics adapter; missing provider metrics remain absent.
- Added mobile Performance workspace for factual metrics, attribution and cohort comparison.

### v3.70 — Publishing Engine — 2026-10-20
- Approval no longer publishes automatically. It creates one idempotent publishing queue item tied to the approved package/variant.
- Added approved → scheduled → publishing → published/failed state handling, schedule model, publish attempt count, stable idempotency keys and external publish receipts.
- Added manual publisher confirmation as the safe baseline plus a provider-neutral webhook adapter for an external publisher.
- Uncertain external outcomes are persisted and require explicit confirmation before retrying the same idempotency key.
- Added mobile Publishing workspace for queue, scheduling, retry/history and real post confirmation.

### v3.60 — Approval Studio — 2026-10-20
- Added mobile-first Approval Studio with package preview context, final script/hook, source evidence, fact/QA warnings, measured cost, duration, variants, provenance and publish-target state.
- Added approve/reject with persisted reasons, approval history/audit records and variant comparison/diff context.
- Added targeted hook/script/caption/voice regeneration paths. Model regeneration shows a pre-call cost estimate; downstream invalidation remains scoped to affected components.
- Human approval is now explicitly separated from publishing.
- Release verification stayed zero-spend: CI `39391145024` passed compile, runtime regressions, HTML and JavaScript checks; production commit `e94cfff4094221acaf4f61b8c10ba9e7adfa1c01` is LIVE on Render deploy `dep-dbbi2m6k1f9s73bs9rk0` with clean startup and repeated `/health 200`.

### v3.50 — Content Package / Shorts Factory — 2026-10-20
- Added a persisted Content Package schema linked to the selected production variant and job.
- Packages now contain the final script, 1–3 second hook, scene breakdown, voice-over, generated SRT subtitles, title, description, CTA, hashtags, thumbnail concept, media brief, source list, fact-check report, structured QA, estimated duration and measured production cost.
- Added the Content Packager worker. Live package creation uses one explicit budget-guarded LLM call; CI and release regression use deterministic zero-spend package generation.
- Added provider-neutral media adapter contracts for TTS, image, video, stock/B-roll and manual media without hardcoding vendors into production workflow logic.
- Visual Director and Voice Agent now consume the selected Content Package manifest rather than raw script output.
- Added mobile-first Package Studio with scene/script/VO/SRT/source/fact-check/provider visibility.
- Added downloadable ZIP and JSON exports. ZIP bundles script, VO, subtitles, scenes, publishing metadata, sources, fact-check and media brief.
- Added stale-output fences: changing the selected variant invalidates the package and downstream pipeline; rebuilding a package invalidates Visual → Voice → Render → QA.
- Verified zero-spend CI run `39382663013` and production commit `54c17937242219d35c2df93f339a9dfba55802da` on Render deploy `dep-dbbgu2rm8hqs738tvkog`.

### v3.40 — Production Pipeline 2.0 — 2026-10-20
- Replaced the single script path with a three-variant production workflow: Angle Strategist → Hook Generator → Scriptwriter → Fact Checker → Hook Optimizer → Editor → structured QA.
- Added persisted production-variant batches with separate angle, hook, script, fact-check, edited-script, QA, decision and provenance data.
- Added structured QA findings instead of a synthetic quality score: unsupported claim, weak hook, duplicated angle, missing source, slow intro, unclear CTA, excessive length, unsafe/sensitive claim and fact conflict.
- Added automatic evidence-based recommendation plus manual winner selection in a mobile-first Variant Studio.
- Added targeted partial reruns for angle/hook/script/fact-check/hook optimization/editor/QA; reruns fence the job back to the script stage so stale downstream media cannot silently continue.
- Added variant cost comparison. Shared batch-run spend is allocated evenly for comparison while exact provider spend remains measured in the agent-run ledger.
- Updated pipeline/Agent Office visibility for the new worker graph and fixed live script-stage worker visualization.
- Extended zero-spend CI to generate and compare a three-variant demo batch without provider calls.
- Verified live: CI run `39380515484` passed; production commit `0410358433509703b5ae26f8e0246f625d967298`; Render deploy `dep-dbbgkaei0phs738fog7g` is live with clean startup and health checks.

### v3.30 — Content Brain / Idea Factory — 2026-10-20
- Added persistent source signals, idea storage, fingerprint deduplication and traceable provenance.
- Added manual/URL ingestion plus a configurable scheduled RSS source adapter through `FACTORY_SIGNAL_FEEDS`.
- Added the full idea pipeline: Scout → Researcher → Idea Strategist → Idea Verifier → Idea Queue.
- Researcher is constrained to persisted source signals; Strategist refines the content angle; Verifier returns shortlist/reject/needs-research decisions, risk flags and reasons.
- Added a mobile-first Content Brain workspace with signal ingestion, feed collection, shortlist generation, research/verification details, select/reject actions and one-tap creation of a production job.
- Preserved provider budget guards and explicit paid execution: release CI/verification remains zero-spend.
- Verified production on Render: commit `00225f9ed45253f33c1d9159eba2eb090e6e9fb1`, deploy `dep-dbbgdagubc0c73d4qbng`, successful startup and health checks.

### v3.25 — Baseline Closure — 2026-10-19
- Confirmed the controlled paid production run in Render: 7 live LLM runs, 9 artifacts, 5,846 total tokens and $0.029902 provider cost.
- Confirmed the pipeline stopped at `waiting_approval`, preserving the human approval gate before publishing.
- Synchronized `live-llm`, Night 1 hardening and mobile parity as completed in the build manifest.
- Disabled the one-shot paid verification startup trigger after success while retaining the historical evidence summary.
- Promoted the runtime build identity to v3.25 and moved the active roadmap to v3.30 Content Brain / Idea Factory.

### v3.24 — Mobile Control Room + Controlled Paid Verification — 2026-10-19
- Restored Agent Office worker cards on phone layouts instead of hiding them below 700 px; workers remain visible, live-state aware and clickable.
- Reworked mobile navigation into a horizontal touch rail and kept Jobs, Pipeline, Error Center, Outputs, Analytics, Release QA and worker drawers operational on small screens.
- Added mobile-safe layouts for creation forms, job controls, metrics, full-screen operational pages and agent detail drawers while preserving the existing desktop layout.
- Added an explicitly approved one-shot paid production verification that runs the pipeline to the QA approval gate, records real live-worker artifacts, input/output tokens and provider cost, and persists a pre-call fence so a restart cannot auto-repeat spend.
- Exposed only a safe verification summary through /health; artifact contents and secrets remain private.
- CI remains zero-spend because smoke tests clear the provider API key.


### v3.23 — Release Readiness / Morning QA — 2026-10-19
- Added a live Release QA workspace that summarizes production state, roadmap completion, failed jobs, open incidents, current provider spend and build identity.
- Added explicit runtime safety checks for the human approval gate, provider budget guards, spend-safe retry behavior, private authentication, live LLM configuration and Builder bridge.
- Added structured known-gap reporting instead of hiding incomplete capabilities: the controlled paid LLM end-to-end verification remains intentionally pending, and voice/video providers remain unconfigured.
- Added the /api/release-readiness endpoint and extended the zero-spend regression suite to protect its contract and safety invariants.
- Morning QA does not execute paid model calls.
- Verified live: GitHub CI passed Python, zero-spend regression, HTML and JavaScript checks; Render started v3.23 successfully with Builder/LLM readiness and health checks.

### v3.22 — Responsive / i18n + Regression Guard — 2026-10-19
- Localized Error Center, Worker Results, Handoff Trace and Factory Intelligence dynamic states across EN / UK / RU, including recovery confirmations and structured analytics insights.
- Removed stale hardcoded UI versioning and added mobile-first navigation/layout overrides for the new operational surfaces, drawers, analytics workspace and error recovery cards.
- Added a zero-spend standalone smoke/regression suite covering health/provider readiness, status data shapes, worker outputs/handoffs, approval gating, recovery retry policy, intelligence contracts and i18n completeness.
- Wired the regression suite into GitHub Actions alongside Python compilation, HTML structure checks and inline JavaScript syntax validation.
- Smoke tests explicitly clear the LLM API key, so CI cannot spend provider balance.
- Verified in production: GitHub CI passed all compile/smoke/HTML/JavaScript checks and Render deployed v3.22 with successful startup and health checks.

### v3.21 — Factory Intelligence — 2026-10-19
- Added a dedicated Analytics workspace comparing worker reliability, measured latency, tokens, provider cost, failures and artifact production.
- Added recent-job comparisons with persisted run cost/time/failures plus pipeline artifact coverage and stale-stage signals.
- Added evidence-based optimization insights for failure hotspots, cost drivers, latency bottlenecks and incomplete job coverage.
- Explicitly labels artifact coverage as pipeline readiness rather than inventing a subjective AI quality score.
- Uses existing persisted ledgers only; no destructive schema migration was introduced.
- Verified live on Render: successful build, application startup and production health checks.

### v3.20 — Operations & Error Center (Night 5) — 2026-10-19
- Added a dedicated Operations / Error Center with classified incidents, recovery guidance, resolved history and recorded run cost.
- Split billing, configuration, budget, dependency, rate-limit, provider-response, transport and unknown failures into explicit recovery policies.
- Automatic retry is now limited to explicitly safe transient failures; timeout/network/provider-uncertain cases require manual confirmation to reduce duplicate spend risk.
- Added stale-incident retry fencing and budget preflight checks to manual worker recovery.
- Reconciled Night 4 as deployed and verified Night 5 live on Render with successful startup and health checks.

### v3.4 — Live Pipeline Motion — 2026-10-19
- Added live stage highlighting driven by actual worker runtime state rather than a cosmetic timer.
- Active pipeline stages show the worker currently executing and a moving data packet toward the next stage.
- Existing Agent Office dependency edges continue to animate only when source/target activity is real.
- Preserved the human approval boundary before publishing.

### v3.3 — Handoff Trace Viewer — 2026-10-19
- Added clickable worker-to-worker handoffs on the main dashboard.
- Added persisted provenance tracing: exact artifact, source run, target run, stage, timestamps, token usage and provider cost.
- Trace Viewer uses recorded `run_inputs` and artifacts; it does not invent or reconstruct missing inputs.

### v3.2 — Worker Results & Handoffs — 2026-10-19
- Added latest output preview for every worker directly on the main dashboard.
- Added worker state, execution mode/model and visible failure state.
- Added incoming `← source` and outgoing `→ target` handoff chips.
- Added animated Agent Office dependency flow and a handoff activity stream.
- Worker cards remain clickable for full history, artifacts and accounting.

### v3.1 — Live LLM Hardening — 2026-10-19
- Hardened live LLM execution with bounded output tokens per worker call.
- Added conservative preflight budget checks so one paid call cannot knowingly exceed the configured job/day provider cap.
- Corrected failed-run accounting so failed live executions remain identified as `live_llm`.
- Preserved human approval before publishing and existing authentication boundaries.

### v3.0 — Overnight FactoryOS roadmap — 2026-10-18
- Introduced the overnight product-improvement roadmap and build manifest.
- Added structured roadmap steps for live LLM hardening, worker visibility, trace viewing, live pipeline visualization, error center, responsive/i18n work, smoke tests and morning QA.

## Telegram: /brief (morning brief)

Owner opt-in voice brief, sent at 08:00 Europe/Kyiv to the paired private Telegram chat (#106, `morning_brief.py`). Off by default.

- `/brief on` / `/brief off`: turn the daily brief on or off.
- `/brief test`: send the composed text only (no voice, no Gemini call) so the owner can check it first.
- `/brief`: show the current state and the result of the last send.

Content comes only from data FactoryOS already holds: PRs merged in the last 24 h, open PRs with red CI, active Relay tickets (including how many wait for the owner) and open questions. If the GitHub snapshot is missing, the brief says GitHub status is unknown instead of guessing. One brief per Kyiv date, up to 3 tries 20 min apart, none at or after 11:00. Cost: one Gemini TTS call per day on the existing free-tier key. Commands from any other chat are ignored.

## Safety invariants

- Human approval is required before publishing.
- Authentication must not be weakened as part of product iterations.
- Provider spend is bounded by configured job/day budgets.
- Secrets stay in environment variables and are never rendered in the UI.
- Product iterations avoid destructive schema/data migrations unless explicitly reviewed.

## Deployment

Render auto-deploys the `main` branch after the configured GitHub checks pass.

Relay E2E check 2026-11-14
