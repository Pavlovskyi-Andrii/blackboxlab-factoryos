# Paperclip and comparable "AI company OS" products — state as of 2026-11-17

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | Paperclip is MIT-licensed, self-hosted, and large: 114.5k stars, 19.0k forks, 8,218 commits, 3,875 open issues, about 3k open PRs. Stack: Express REST API (Node.js 24.11+), React + Vite UI, PostgreSQL via Drizzle, pnpm monorepo. | https://github.com/paperclipai/paperclip ; https://raw.githubusercontent.com/paperclipai/paperclip/master/AGENTS.md | fetched 2026-11-17 | verified_primary |
| 2 | Latest release is v2026.1106.0 (2026-11-06): 515 commits from 27 contributors, DB migrations 0334-0374, and a breaking removal ("The Pipelines experiment is removed"). Ten releases between 25 Aug and 6 Nov 2026, i.e. a feature release every 1-2 weeks. | https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0 ; https://github.com/paperclipai/paperclip/releases | 2026-11-06 | verified_primary |
| 3 | Paperclip already ships the generic control-plane surface FactoryOS is building: org chart, goal ancestry, ticket threads, heartbeats, company/agent/project budgets with auto-pause, approval gates, atomic task checkout with a single assignee, activity log, config versioning with rollback, multi-company isolation, routines, skills, plugins. | https://github.com/paperclipai/paperclip ; https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md | fetched 2026-11-17 | verified_primary |
| 4 | Twelve built-in adapters, including `claude_local`, `codex_local`, `gemini_local` (experimental), `openclaw_gateway`, `process` and `http` (webhook). The `http` adapter POSTs `runId`, `agentId`, `companyId`, `context.taskId`, `context.wakeReason`, `context.commentId`; the external agent calls back to the Paperclip API with an API key. | https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/overview.md ; https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/http.md | fetched 2026-11-17 | verified_primary |
| 5 | Paperclip defines itself as "Control plane, not execution plane"; budget enforcement is described as best effort; it is explicitly not a general chat app, not a Jira/GitHub replacement, and does not provide filesystem isolation. | https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/PRODUCT.md | fetched 2026-11-17 | verified_primary |
| 6 | Software cost is zero, but self-hosting adds a second stack: Node.js 24.11+, pnpm 9.15+, embedded PostgreSQL by default or PostgreSQL 17 for production, Docker image on GHCR, 73 DB connections per server process by default. No CPU/RAM sizing is published. | https://github.com/paperclipai/paperclip ; https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DOCKER.md ; https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DATABASE.md | fetched 2026-11-17 | verified_primary |
| 7 | Anthropic policy constrains the "run it on my Claude subscription" plan: from 2026-04-04 third-party harnesses could no longer use subscription limits (pay-as-you-go instead), and from 2026-06-15 "Agent SDK and claude -p usage on subscription plans will draw from a new monthly Agent SDK credit, separate from your interactive usage limits". | https://github.com/paperclipai/paperclip/issues/2681 ; https://github.com/anthropics/claude-code/issues/59823 | 2026-04-03 and 2026-05-16 (quoting Anthropic email / docs) | reported_secondary (primary text quoted inside GitHub issues; Anthropic pages not opened) |
| 8 | Paperclip's `claude_local` adapter runs Claude Code headless (`claude --print ...`), with `dangerouslySkipPermissions` defaulting to `true` and `maxTurnsPerRun` defaulting to 300. Under claim 7, such runs on a Claude Pro plan would be metered against the Agent SDK credit, not the interactive allowance. | https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/claude-local.md | fetched 2026-11-17 | verified_primary for adapter behaviour; inference for the billing consequence |
| 9 | Heartbeats burn tokens when idle: one idle wake measured +180,456 input, +1,892,418 cached-input and +12,963 output tokens; in an 11-agent, 8-day sample, 5 mostly idle agents used 66% of context and delivered 6% of issues. Issue open since 2026-04-11, still reproduced on v2026.1106.0. | https://github.com/paperclipai/paperclip/issues/3401 | 2026-04-11 to 2026-11-07 | reported_secondary (user measurements on the primary tracker) |
| 10 | Spend guardrails have open defects: "160 of 400 runs burned against an exhausted quota in 9h" (#11597, open); flat-rate subscription runs are logged at $0, so a dollar budget does not stop them (80 runs in under 3.5 h, 79 failing, cost page showing $0). | https://github.com/paperclipai/paperclip/issues/11597 ; https://github.com/paperclipai/paperclip/discussions/16618 | 2026-08-18 ; 2026-10-17 | reported_secondary (user reports on the primary tracker) |
| 11 | Claude subscription connections stop working about 8 hours after sign-in and cannot refresh; opened 2026-09-20, still open in November 2026 with no fix in a released build per commenters. | https://github.com/paperclipai/paperclip/issues/13725 | 2026-09-20 to 2026-11 | verified_primary (issue tracker) |
| 12 | No verifiable case of a Paperclip-run company earning revenue was found. The two user write-ups opened report no revenue; the "zero-human journalism company" author later reported "about an hour of human review per article", a hallucinated "MIT study", and a publisher agent "silently dead for four days". | https://github.com/paperclipai/paperclip/discussions/5416 ; https://github.com/paperclipai/paperclip/discussions/16618 | 2026-05-07 to 2026-08-20 ; 2026-10-17 | verified_primary for what the posts say; inference that no audited case exists |
| 13 | Secondary sources say Paperclip's founder ("Dotta") admitted on a podcast that Paperclip itself had no revenue (at about 38k stars), and that the official hosted "Paperclip Cloud" is a waitlist without a price. | https://www.stork.ai/blog/ai-wont-run-your-company-heres-why ; https://www.stork.ai/en/paperclip ; README waitlist link at https://github.com/paperclipai/paperclip | spring 2026 ; pages read 2026-10-04 | reported_secondary (search-result summaries only; pages not opened, podcast not located). Waitlist link itself: verified_primary |
| 14 | Polsia (closed, hosted "autonomous company" service) reports $16-18.7M ARR, of which about $9.7-11M is recurring subscription per third-party analyses; it reportedly raised $30M at a $250M valuation (May 2026) and has a 2.1/5 Trustpilot score. This is Polsia's own revenue from founders, not evidence that the companies it runs are profitable. | https://www.sofarbot.com/stories/polsia-ben-broca-500000-monthly-revenue ; https://preuve.ai/blog/polsia-review ; https://aiolum.com/story/polsia/ | Aug-Sep 2026 | reported_secondary (search-result summaries only; pages not opened; figures company-reported and disputed) |
| 15 | Paperclip is not the only open control plane: Multica (56.5k stars, source-available "Apache 2.0 plus conditions", 31 agent CLIs, Go + Next.js + PostgreSQL 17), ChatDev 2.0 (34.8k stars, Apache-2.0, released 2026-01-07), MetaGPT (71.3k stars, MIT, newest README news item March 2025). Generic agent orchestration is a commodity. | https://github.com/multica-ai/multica ; https://github.com/OpenBMB/ChatDev ; https://github.com/FoundationAgents/MetaGPT | fetched 2026-11-17 | verified_primary for the figures; inference for "commodity" |

## Research method and access limits (read before relying on these notes)

- The session's network policy let WebFetch open only `github.com` and `raw.githubusercontent.com`. These hosts failed DNS resolution and could not be opened: `paperclip.ing`, `www.eesel.ai`, `www.stork.ai`, `dev.to`, `www.kunalganglani.com`, `hn.algolia.com`. `api.github.com` returned HTTP 403. Some `github.com/.../blob/...` pages returned HTTP 503 and were re-read via `raw.githubusercontent.com`.
- The shared WebSearch budget for the whole workflow ran out after nine searches by this researcher. Three planned searches did not run: Anthropic subscription/Agent SDK policy, Polsia criticism, and independent autonomy benchmarks (Project Vend, TheAgentCompany).
- Consequence: every Paperclip fact below marked verified_primary comes from the project's own GitHub repository, docs, releases, issues and discussions. Everything about commercial comparables (Polsia, Lindy, Relevance AI, Manus, Genspark, MGX, Devin) and all third-party reviews of Paperclip rests on search-result summaries; the pages were not opened. They are labelled as such and must not be quoted as verified prices.
- No Hacker News thread was found or opened. The one search for it returned only blogs.

## 1. What Paperclip actually provides

### Takeaway
Paperclip is a real, very active, MIT-licensed control plane (not an agent framework) that packages almost every generic orchestration primitive FactoryOS has been hand-building. It is also young (first issues dated early March 2026), fast-churning and carries about 3.9k open issues.

### Cited findings

Identity and maturity
- Stars 114.5k, forks 19.0k, watchers 491, 8,218 commits, MIT licence; issues tab 3.9k, PR tab 3k. — [repo](https://github.com/paperclipai/paperclip) (fetched 2026-11-17)
- Exactly 3,875 open issues in the open-issue filter. — [issues](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc)
- The earliest issues visible are dated 4-8 March 2026 (#7 on Mar 4, #49 and #63 on Mar 5, #187 on Mar 7), consistent with a public launch in early March 2026. — [issues](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc). The repository creation date itself was not verified (GitHub API returned 403).
- README FAQ: the project is maintained by "the Paperclip team", who report merging "over 2,700 pull requests". — [README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md)
- Release list (GitHub publish dates, all 2026): v2026.824.1 (25 Aug), v2026.831.0 and v2026.831.1 (2 Sep), v2026.916.0 (16 Sep), v2026.916.1 (21 Sep), v2026.1001.0 (2 Oct), v2026.1005.0 (6 Oct), v2026.1012.0 (12 Oct), v2026.1023.0 (24 Oct), v2026.1106.0 (6 Nov, "Latest"). Calendar versioning; betas are promoted to stable. Older releases exist but were not listed on the page read. — [releases](https://github.com/paperclipai/paperclip/releases)
- v2026.1106.0: 515 commits from 27 contributors; the native "Paperclip Runner" becomes the default for new Claude, Codex, OpenCode and Pi agents on macOS and Linux (Linux needs GNU libc 2.39+); GitHub Copilot added as a native harness; pinned Claude Agent SDK 0.3.286 (Claude Code 2.1.286) and Codex 0.160.0; migrations 0334-0374 run on upgrade; "The Pipelines experiment is removed"; "Run failures no longer reach Sentry by default". — [release notes](https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0)
- Search-result summary of the same release page: "2638 commits to master since this release", i.e. master moves far ahead of tagged releases. — [release page](https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0) (figure seen in a search summary, not in the fetched text)

Feature set (README)
- Org chart: "Hierarchies, roles, reporting lines. Your agents have a boss, a title, and a job description." — [repo](https://github.com/paperclipai/paperclip)
- Goals: tasks and projects carry their goal ancestry so agents see why a task exists. Tickets: task threads keep conversations, plans, blockers, files and run history. Heartbeats: agents wake on assignment, follow-up messages or schedules ("If it can receive a heartbeat, it's hired."). Budgets: company, agent and project budgets with threshold alerts and pauses. Governance: review and approval stages, hire approvals, pause/reassign/stop. — [repo](https://github.com/paperclipai/paperclip)
- "Why Paperclip is special": atomic task checkout (one assignee plus execution locks), persistent work context with session resume, runtime skill injection, governance with rollback (versioned config), goal-aware execution, portable company templates (export/import with secret scrubbing), company-scoped access boundaries. — [README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md)
- Engineering invariants in the repo's own agent instructions: "Single-assignee task model", "Atomic issue checkout semantics", "Approval gates for governed actions", "Budget hard-stop auto-pause behavior", "Activity logging for mutating actions". — [AGENTS.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/AGENTS.md)
- Roadmap items marked done include: plugin system, scheduled routines, better budgeting, agent reviews and approvals, multiple human users, cloud/sandbox agents, enforced outcomes, MCP tool gateway and apps, secrets manager with per-agent access, activity log, self-healing runs, agent evals and feedback, multi-model and multi-harness teams. Not done: memory/knowledge (in progress), agent chat (in progress), cloud deployments (in progress), work queues, self-organization, automatic organizational learning, desktop app, bring-your-own ticket system (Asana/Linear/Jira). — [repo](https://github.com/paperclipai/paperclip)
- Channels: Slack, Discord, Telegram and AgentMail exist only as experimental chat and email connectors that must be enabled in instance settings. README also claims a "Mobile Ready" UI. — [README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md)
- Telemetry is on by default (anonymous usage data); disable with `PAPERCLIP_TELEMETRY_DISABLED=1` or `DO_NOT_TRACK=1`. — [repo](https://github.com/paperclipai/paperclip)

Product definition (PRODUCT.md)
- "Control plane, not execution plane. Paperclip orchestrates." A company is the top-level object; one instance can run many companies; "Every employee is an agent." Example goal in the doc: "Create the #1 AI note-taking app that does $1M MRR within 3 months." — [PRODUCT.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/PRODUCT.md)
- The human is the "board": sets the goal, approves the CEO agent's strategy, sets budgets, reviews approvals and outputs. Budget enforcement is described as best effort. — [PRODUCT.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/PRODUCT.md)
- Explicitly out of scope: a general chat app, a Jira/GitHub replacement, enterprise RBAC first, filesystem isolation (left to the OS), raw logs as the main surface. The doc contains no pricing or revenue model for Paperclip; it mentions an optional enterprise edition. — [PRODUCT.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/PRODUCT.md)

Adapters
- Built in: `claude_local`, `codex_local`, `gemini_local` (experimental, "not yet in the stable type enum"), `kimi_local`, `opencode_local`, `cursor`, `pi_local`, `hermes_local`, `hermes_gateway`, `openclaw_gateway`, `process` (arbitrary shell commands), `http` (webhooks to external agents). External adapters are npm packages loaded through the plugin system. — [adapters overview](https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/overview.md)
- `claude_local`: needs the `claude` CLI and one of `ANTHROPIC_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`, or a subscription login; environment test runs `claude --print - --output-format stream-json --verbose`; `dangerouslySkipPermissions` defaults to `true` ("required for headless runs where interactive approval is impossible"); `maxTurnsPerRun` defaults to 300; sessions resume between heartbeats; quota errors wait until the reported reset time or a one-hour backoff. — [claude-local.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/claude-local.md)

Self-hosting requirements and running cost
- Node.js 24.11+ and pnpm 9.15+; quickstart `npx paperclipai@latest onboard --yes`; UI and API on `http://localhost:3100`; embedded PostgreSQL is created automatically; production points at your own Postgres; subscription sign-in also needs Python 3 and the provider CLI on the host. — [repo](https://github.com/paperclipai/paperclip)
- Deployment modes: `local_trusted` (loopback only, no login) and `authenticated` with `private` (Tailscale/VPN/LAN) or `public` (explicit public URL, stricter checks, reverse proxy recommended). — [DEPLOYMENT-MODES.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DEPLOYMENT-MODES.md)
- Docker: image `ghcr.io/paperclipai/paperclip:sha-<FULL_SHA>` for AMD64 and ARM64, port 3100, required `BETTER_AUTH_SECRET` and `PAPERCLIP_TOOL_ACTION_SIGNING_SECRET`; the image preinstalls `claude`, `codex` and OpenCode CLIs; approvals fail closed if signing key material cannot be loaded. No memory or CPU sizing guidance. — [DOCKER.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DOCKER.md)
- Database: embedded PostgreSQL when `DATABASE_URL` is unset (data in `~/.paperclip/instances/default/db/`); PostgreSQL 17 via Docker; hosted Supabase "is a good option with a free tier" (500 MB, projects pause after one week of inactivity); "Total with defaults | 73" connections per server process; logical backups exclude uploads, workspace files and the secrets master key. — [DATABASE.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DATABASE.md)
- Hosted offering: the README carries a "Sign up for the Paperclip Cloud waitlist" link; docs refer to "Cloud-managed instances" and a "Paperclip-hosted OAuth broker" for Google Workspace. — [repo](https://github.com/paperclipai/paperclip), [DEPLOYMENT-MODES.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DEPLOYMENT-MODES.md), [release notes](https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0)

### Inferences
- Running Paperclip costs nothing in licences, and on an existing machine nothing in infrastructure, provided the EC2 host has spare memory for a Node process plus embedded Postgres (the instance size is unknown to this researcher, and Paperclip publishes no sizing). The real cost is model consumption and operator time.
- With 41 migrations in a single release, a removed experiment, and master thousands of commits ahead of the latest tag, upgrades are a recurring maintenance task, not a one-off install.

### Gaps
- Official pricing of Paperclip Cloud: could not open `paperclip.ing`. A search summary (pages read 2026-10-04) says "Official hosted plan: Waitlist, no price", and that a separate entity (Paperclip.inc OU) had a EUR 10/month hosted plan shutting down on 2026-10-02; third-party hosts quote $21-149/month. None of this was verified. — [stork.ai/en/paperclip](https://www.stork.ai/en/paperclip), [paperclipcloud.com](https://paperclipcloud.com/) (not opened)
- Language percentages, contributor count, repository creation date: not retrievable.
- Company behind Paperclip, funding, team size: not verified. A search summary says that as of June 2026 there was "no disclosed company, team, or funding". — [rywalker.com/research/paperclip](https://rywalker.com/research/paperclip) (not opened)

## 2. Overlap with FactoryOS components

### Takeaway
FactoryOS is re-building most of a generic agent control plane that exists as open source. What FactoryOS has that Paperclip does not is domain-specific: the content and MVP pipelines, the publish-approval gate, Telegram as the primary console, and a Python/DBOS runtime already deployed.

### Cited findings (FactoryOS side read from the local repository on 2026-11-17)
- Relay stores tickets in `DATA_DIR/relay.json`, takes any Telegram message as a ticket, and has four states (Inbox, In progress, Need you, Done). — `docs/RELAY.md`
- `relay_execution.py` (`RelayQueue`: `enqueue`, `claim`, `claim_roadmap`, `event`, `record_review`, `reconcile_pull_requests`, `reconcile_deploys`), `relay_agent_messages.py` (`send`, `claim`, `ack` with claim tokens and leases), `agent_workspace.py` (`create_handoff`, `claim_handoff`, `submit_handoff_result`, `release_handoff`, `review_handoff`), `lane_board.py` and `operator_lanes.py` (heartbeat TTLs, stale detection, claims). `app.py` is 13,742 lines at `APP_VERSION = "v5.12.0"`; the repo root holds 176 Python files. — local repository
- Owner policy: "ZERO ADDITIONAL SPEND ... Subscription access must never be silently replaced with PAYG API usage." — `ROADMAP.md` line 27
- The Claude-ChatGPT live two-way connection is documented as not verified, and the coordination document is "NOT a working automatic link". — `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md` (2026-11-01)

Mapping (Paperclip facts cited in section 1)

| FactoryOS component | Paperclip equivalent | Assessment |
|---|---|---|
| Relay tickets, statuses, history | Issues with sub-issues, blockers, comments, documents, run history | Paperclip is richer and relational (Postgres) versus a JSON file |
| Claims, leases, run ids | Single-assignee model, atomic checkout with execution locks, `runId` per heartbeat | Equivalent concept; Paperclip's is a tested invariant with many adapters |
| Agent messages and handoffs between lanes | Task threads, approval handoffs, experimental "Cases" | Equivalent; Paperclip ties all conversation to tasks |
| Worker Center / Agent Office | Org chart, agent pages, run transcripts, costs page, community "Office" and 3D dashboard plugins | Paperclip ahead on breadth; visual office views already exist as plugins ([#14612](https://github.com/paperclipai/paperclip/discussions/14612), [#16223](https://github.com/paperclipai/paperclip/discussions/16223) — titles only) |
| Budgets | Company/agent/project budgets, hard-stop auto-pause, cost ledger | Paperclip ahead in design, but dollar budgets are inert on flat-rate subscriptions (section 3) |
| Human approval gate | Approval stages, hire approvals, signed tool-gateway actions, fail-closed signing | Different target: Paperclip governs hires, reviews and tool actions; FactoryOS gates publishing, outreach and payment |
| Telegram control | Experimental chat connectors; community plugin "Approve hires and budgets ... from Slack or Telegram" ([#15386](https://github.com/paperclipai/paperclip/discussions/15386), 2026-10-06, title only); request "Allow linking remote channels to talk to the CEO via telegram/whatsApp" open since 2026-03-28 ([#2004](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc)) | FactoryOS ahead: Telegram is its first-class console |
| ChatGPT and Gemini lanes | `codex_local` (Codex CLI), `gemini_local` (experimental); v2026.1012.0 lets outside assistants "like Claude Code and Codex" connect over MCP ([releases](https://github.com/paperclipai/paperclip/releases)) | Paperclip drives CLIs; it has no adapter for the ChatGPT web product |
| DBOS durable workflows | "Self-healing runs & automatic recovery" (roadmap, done) | Different mechanism; FactoryOS's step checkpointing is more explicit |
| Content Factory, MVP Factory, browser runner, Surfer, Notion memory, Metricool/vidIQ | None (memory/knowledge still in progress on the roadmap) | FactoryOS only; this is the actual product work |

### Inferences
- The generic parts (ticket bus, claims, heartbeats, budgets, office views) are where FactoryOS duplicates open source and gains no sellable differentiation.
- Paperclip's list of control-plane invariants is a good acceptance checklist for Relay, whether or not Paperclip is installed.

### Gaps
- No hands-on comparison was run; the assessment is from documentation on both sides.

## 3. Documented outcomes, criticisms and failure modes

### Takeaway
There is no verifiable evidence that any Paperclip-run "company" earns revenue, and the project's own tracker documents the failure modes that matter most under a zero-spend, subscription-only policy: idle token burn, quota-blind scheduling, wake loops, and dollar budgets that do not bind on flat-rate plans.

### Cited findings

Outcomes
- "I built a Zero-Human Journalism Company on Paperclip" (2026-05-07, 7 upvotes, 11 comments): five to six agents on a Claude Max subscription; no audience, traffic, subscriber or revenue figures; later reply (2026-08-20) says the author adds "about an hour of human review per article for facts and judgment"; reported problems include rate-limit stalls, a CEO infinite loop, an agent that invented an "MIT study", and a publisher "silently dead for four days". — [discussion #5416](https://github.com/paperclipai/paperclip/discussions/5416)
- CyberNative AI LLC (2026-10-17): more than 13,000 tasks run on Paperclip with one human founder; recurring "loops, stuck work, and runs that spend budget doing nothing"; no revenue or customer numbers; the author sells a guardrail pack at $49 one-time or $19/month, i.e. monetises tooling for Paperclip users rather than reporting income from the autonomous business. — [discussion #16618](https://github.com/paperclipai/paperclip/discussions/16618)
- A discussion search for revenue/customers/paying returned nine threads; none of the visible titles or metadata reports revenue. "Running 9 AI businesses on one Paperclip instance" (2026-03-14, 1 upvote, 7 comments) was seen by title only. The most discussed thread is "Tokens consumption" (11 votes, 21 comments, unanswered). — [discussions search](https://github.com/paperclipai/paperclip/discussions?discussions_q=revenue+OR+customers+OR+%22paying%22+sort%3Atop)
- Secondary reports (search summaries; pages not opened): the founder "admitted the platform itself has yet to generate any revenue" on a podcast; "38,000 stars but zero revenue"; users range "from security firms to dentists to roofing companies". The podcast episode was not located. — [stork.ai](https://www.stork.ai/blog/ai-wont-run-your-company-heres-why), [videohighlight](https://videohighlight.com/v/Yp5KiHBSpZo)
- The founder's own conference framing is a "human control plane for AI labor", which is more modest than "zero-human company". — [ai.engineer talk page](https://ai.engineer/talks/h403btjldDQ-paperclip-open-source-human-control-plane-ai) (search summary; page not opened)

Failure modes on the project's tracker
- Idle heartbeat cost: default timer about 15 minutes; one idle wake +180,456 input, +1,892,418 cached-input, +12,963 output tokens; 48 timer heartbeats per day for one idle agent producing no work; worst single agent 859.6M context tokens and zero delivered issues. Mitigation `skipTimerWhenNoActionableWork` exists but has caveats; `heartbeat.maxDailyCostCents` is unset by default. No maintainer fix; a contributor classed it as backlog. — [issue #3401](https://github.com/paperclipai/paperclip/issues/3401)
- Quota-blind scheduling: on a Claude subscription, the parsed reset time was stored but did not gate new runs — "160 of 400 runs burned against an exhausted quota in 9h"; 16 issues froze in `in_progress`. Open, no maintainer response visible. — [issue #11597](https://github.com/paperclipai/paperclip/issues/11597)
- Related open issues by title: "maxTurnsPerRun is ignored on the default engine, so the runaway cap enforces nothing" (#14069), unbounded wake loops (#15052, #6523, #7496), "Concurrent wakeups exhaust the DB pool and freeze the server" (#14196), quota failures misclassified as stuck work (#10344), a proposed loop-detection circuit breaker open since 2026-03-09 (#390). — [issue search](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+runaway+OR+%22burned%22+OR+%22infinite+loop%22+OR+%22budget+exceeded%22+sort%3Acomments-desc) (titles and counts only; 213 matches)
- Seventeen issues about subscription limits and quota handling were listed, most still open or in review as of 2026-11-15. — [issue search](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+%22Agent+SDK+credit%22+OR+%22extra+usage%22+OR+%22subscription+limits%22+sort%3Aupdated-desc)
- Dollar budgets do not bind on subscriptions: "flat-rate subscription runs are logged at $0, so a dollar budget won't stop them"; one loop produced 80 runs in under 3.5 hours with 79 failing on the same usage limit while the cost page showed $0; the author cut scheduled cycles from about 212 to about 47 per day. — [discussion #16618](https://github.com/paperclipai/paperclip/discussions/16618)
- Claude subscription auth: connections die about 8 hours after sign-in because only the access token is stored; workaround is a long-lived `claude setup-token` secret. — [issue #13725](https://github.com/paperclipai/paperclip/issues/13725)
- Top feature requests by reactions are provider coverage and cost control: local LLMs via Ollama (#187), OpenRouter (#1068), cost estimates for subscription-billed agents (#339), token-based budgets (#1756), automatic model fallback at quota (#3317), pause a whole company (#2582). — [issues by reactions](https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc)

Anthropic subscription policy (directly relevant to "zero additional spend")
- Anthropic email quoted by a user on 2026-04-03: "Starting April 4 at 12pm PT / 8pm BST, you'll no longer be able to use your Claude subscription limits" for third-party harnesses; such use needs "a pay-as-you-go option billed separately from your subscription"; "Your subscription still covers all Claude products, including Claude Code and Claude Cowork." No Paperclip maintainer answered whether Paperclip is affected; the issue is still open. — [paperclip issue #2681](https://github.com/paperclipai/paperclip/issues/2681)
- Anthropic docs quoted on 2026-05-16: "Starting June 15, 2026, Agent SDK and claude -p usage on subscription plans will draw from a new monthly Agent SDK credit, separate from your interactive usage limits." The quoted source is `code.claude.com/docs/en/headless`, with details in a support article (ID 15036540) that was not opened. Whether wrappers that spawn `claude --print` count was described by commenters as undocumented. — [claude-code issue #59823](https://github.com/anthropics/claude-code/issues/59823)

Third-party reviews (search summaries only; pages not opened; several reviewers sell competing products)
- Criticisms reported: it "simulates a company rather than building one"; no quality filter; "no evals, no benchmarks, and no quality guarantees" for importable templates; glitches such as 404s on instruction files and agents ignoring overrides; a warning that a retry loop can burn "thousands of dollars of API credits in hours". Praise: oversight of five or more agents "finally feels manageable"; one rating of roughly 7.8/10. — [eesel.ai](https://www.eesel.ai/blog/paperclip-ai-review), [stork.ai](https://www.stork.ai/blog/ai-wont-run-your-company-heres-why), [dev.to](https://dev.to/kunal_d6a8fea2309e1571ee7/paperclip-ai-review-i-tried-to-build-a-zero-human-company-in-a-weekend-2026-16d), [vibecoding.app](https://vibecoding.app/blog/paperclip-review)

### Inferences
- Paperclip's `claude_local` runs are headless `claude --print` or Agent SDK sessions, so on a Claude Pro plan they would draw on the separate Agent SDK credit rather than the interactive allowance. A multi-agent org chart with 15-minute heartbeats would exhaust a small credit quickly, after which work either stops or needs pay-as-you-go billing, which the FactoryOS owner policy forbids. The same constraint applies to any FactoryOS worker that drives Claude Code headless; this needs checking by whoever covers Anthropic terms.
- The absence of revenue evidence after eight months and 114k stars suggests that orchestration is not the binding constraint on making money; distribution, product-market fit and output quality are.
- The best-documented "success" of this ecosystem is selling tools, hosting, templates and guardrail packs to other agent-company builders.

### Gaps
- Per-plan Agent SDK credit amounts and exhaustion behaviour were not verified in this session (no search budget, Anthropic hosts not opened). The researcher's unverified recollection is a credit equal to the plan price, e.g. about $20/month on Pro; treat as unconfirmed.
- No audited financials for any Paperclip-run business were found. Absence of evidence in a limited search is not proof of absence.
- No Hacker News discussion was retrieved.

## 4. Comparable products (November 2026)

### Takeaway
The category splits into open control planes (Paperclip, Multica, ChatDev, MetaGPT), agent runtimes (OpenClaw), and closed hosted services that sell credits or take a revenue share (Polsia, Lindy, Relevance AI, Manus, Genspark, MGX, Devin, Hercules). Only vendors' own revenue is documented; customer profit is not.

### Table

| Product | What it does | Pricing | Open source | Evidence of results | Confidence |
|---|---|---|---|---|---|
| Paperclip | Control plane for agent "companies" | Free self-hosted; cloud waitlist | Yes, MIT | No verified customer revenue | verified_primary — [repo](https://github.com/paperclipai/paperclip) |
| Multica | Workspace where humans and coding agents share issues; drives 31 installed agent CLIs; Go, Next.js 16, PostgreSQL 17; Docker required | Self-host free; cloud prices not shown on the page | Source-available: "Multica License" (Apache 2.0 plus conditions on hosted services, commercial embedding, branding); 56.5k stars | None documented | verified_primary — [repo](https://github.com/multica-ai/multica) |
| OpenClaw | Self-hosted personal agent reachable through Telegram, WhatsApp, Slack and 20+ channels; an "employee", not a company layer | Free | Yes, MIT; about 394.7k stars | None documented; README warns "Treat inbound messages as untrusted input." | verified_primary — [repo](https://github.com/openclaw/openclaw) |
| MetaGPT / MGX | Multi-agent framework simulating a software company; MGX is the commercial product, launched 2025-02-19 | Framework free; MGX "from $20/month" per a directory listing | Framework MIT, 71.3k stars; MGX closed | Product Hunt rankings (March 2025) only; newest README news item is March 2025 | verified_primary for the repo — [repo](https://github.com/FoundationAgents/MetaGPT); MGX price reported_secondary, unverified |
| ChatDev 2.0 | Zero-code multi-agent workflow platform (YAML), web console, Python SDK; 2.0 released 2026-01-07 | Free | Yes, Apache-2.0, 34.8k stars | None documented | verified_primary — [repo](https://github.com/OpenBMB/ChatDev) |
| Polsia | Hosted service that runs a "company" for a founder | Unpublished; reports range from $20 to $49-50/month plus 20% of ad spend and 3% to 20% of revenue | No | Company-reported ARR $16.07M (Aug 2026) to $18.7M (15 Sep 2026), recurring part about $9.7-11M; $30M raise at $250M valuation (May 2026); Trustpilot 2.1/5 | reported_secondary, search summaries only — [sofarbot](https://www.sofarbot.com/stories/polsia-ben-broca-500000-monthly-revenue), [preuve.ai](https://preuve.ai/blog/polsia-review), [aiolum](https://aiolum.com/story/polsia/), [aiweekly](https://aiweekly.co/alerts/polsia-solo-founder-raises-30m-at-250m-valuation) |
| Lindy | No-code agent builder for business workflows | Conflicting: free tier with 400 credits and plans at $19.99 / $49.99 / $299, or $49.99 / $99.99 / $199.99 with no free tier | No | None found | reported_secondary, unverified — [lindy.ai blog](https://www.lindy.ai/blog/relevance-ai-pricing), [eesel](https://www.eesel.ai/blog/lindy-vs-relevance-ai) |
| Relevance AI | Agent "workforce" builder; two meters (Actions and Vendor Credits) since September 2025 | Conflicting: entry $19 or $29/month; free plan reported both as retired and as about 100 credits/day | No | None found | reported_secondary, unverified — [g2](https://www.g2.com/products/relevance-ai/pricing), [agentshortlist](https://agentshortlist.com/compare/lindy-vs-relevance-ai) |
| Manus | General-purpose task agent | About $20/month for 4,000 credits, $40/month for 8,000; team price conflicting | No | None found | reported_secondary, unverified — [spiritt.ai](https://spiritt.ai/resources/guides/is-manus-worth-it), [sokosumi](https://www.sokosumi.com/compare/manus-vs-genspark) |
| Genspark | Agentic search and "super agent" workspace | Free; Plus $24.99/month (10,000 credits); Pro $249.99/month (125,000 credits); Team $40/seat | No | None found | reported_secondary, unverified — [fluxgravity](https://fluxgravity.io/guides/genspark-pricing), [aipricecompare](https://aipricecompare.org/apps/genspark.html) |
| Devin (Cognition) | Autonomous software engineer | Not found in this session | No | Not researched | no data; do not cite a price |
| Hercules (hercules.app) | AI app builder plus "Hercules Agents" (persistent workers with triggers, guardrails, versions, run analytics, evaluation) | Not captured | No; its acceptable-use policy forbids reverse engineering | Not researched | from the repository's own teardown `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md` (2026-10-25); site not opened |

### Inferences
- Polsia's figures, even if accurate, measure what founders pay Polsia. The split into subscriptions, a revenue cut and an ad-spend cut means Polsia earns when customers spend, whether or not customers profit.
- For a zero-spend founder, every closed product in the table is a new recurring cost with credit-based metering; none removes the need for a paying customer.

### Gaps
- No official pricing page of any commercial product was opened. All prices above need re-verification before the report quotes them.
- Devin, Hercules pricing, and independent benchmarks of autonomous businesses (Anthropic/Andon Labs Project Vend, TheAgentCompany) were not researched because the search budget ran out.

## 5. Migration, integration and lock-in

### Takeaway
Legal lock-in is low (MIT, self-hosted, standard Postgres, export/import of companies). Operational lock-in and migration cost are high for a solo founder: a second stack, a different data model, weekly upgrades with migrations, and guardrails that misbehave on subscription billing.

### Cited findings
- Stack is Node.js/Express, React/Vite, Drizzle/PostgreSQL in a pnpm monorepo. — [AGENTS.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/AGENTS.md). FactoryOS is Python/FastAPI with JSON files and SQLite (DBOS). — local repository
- Lowest-effort integration is the `http` adapter: Paperclip POSTs a wake to a URL and the external service calls the Paperclip API back with an API key; the adapter is "fire-and-forget", with no stdout capture or live run view. — [http.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/http.md)
- Since v2026.1012.0, "Outside assistants like Claude Code and Codex can connect over MCP". — [releases](https://github.com/paperclipai/paperclip/releases)
- Companies, agents and skills can be exported and imported with secret scrubbing. — [README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md)
- Public exposure needs authenticated mode, an explicit public URL and a reverse proxy; first-admin bootstrap on a public instance needs a CLI invite. — [DEPLOYMENT-MODES.md](https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DEPLOYMENT-MODES.md)
- Upgrades run schema migrations (0334-0374 in one release) and can remove features. — [release notes](https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0)

### Inferences (effort estimates are judgement, not measurement)
- Reference only: zero integration cost; a few days to port specific guardrails into Relay.
- Pilot as a side board: about one to two days to run Paperclip in `local_trusted` mode with embedded Postgres on an existing machine and register FactoryOS as one `http` agent. No data migration, fully reversible, $0 if no extra model usage is triggered.
- Full adoption as the control plane: weeks of work. Relay tickets, claims, handoffs, Telegram flows, the publish-approval gate and the lane model would all need re-mapping; Telegram control would regress to an experimental connector; the Render service would need Postgres or a second host; every Paperclip release becomes an upgrade task. None of it brings a customer closer.

### Gaps
- The Paperclip REST API reference (`docs/api`) was not read, so callback endpoints and agent authentication details are unconfirmed.

## Counter-evidence and caveats

- Case for adoption: Paperclip has more engineering throughput in two weeks (515 commits, 27 contributors) than a solo founder can match in a year, and its invariants (atomic checkout, approval gates, hard-stop budgets, activity log) are exactly what FactoryOS needs. A founder who keeps hand-building these is spending scarce time on a commodity. This argument is sound; it supports "stop building generic control plane", not necessarily "migrate now".
- Open issue count is not a clean quality signal: 3,875 open issues partly reflect popularity and many feature requests. The quality signal is which issues stay open: loop breakers (since March 2026), heartbeat cost (since April 2026), quota gating (since August 2026).
- The token-burn and quota-burn numbers are individual user reports, measured on specific versions (for example 2026.722.0) and configurations. They show the failure mode exists; they are not averages.
- The "founder admitted no revenue" claim is second-hand, dates from roughly spring 2026 (38k stars), and may be outdated; a hosted cloud with managed sign-in now appears in the docs. Paperclip the company may have revenue by November 2026. This was not verified either way.
- The Anthropic policy text is quoted from GitHub issues, not read on Anthropic's site, and its application to locally spawned `claude --print` wrappers was called undocumented by commenters. It may have changed since June 2026.
- All commercial pricing and all Polsia figures are unverified search summaries with internal contradictions. Several review sites cited sell competing products (eesel.ai, lindy.ai) or hosting (Hostinger, Contabo).
- This researcher found no revenue case; the search was limited to GitHub discussions and nine web searches. A profitable Paperclip-run business may exist outside those sources.
- Pages not opened (search-result summaries only): https://www.eesel.ai/blog/paperclip-ai-review ; https://www.stork.ai/blog/ai-wont-run-your-company-heres-why ; https://www.stork.ai/en/paperclip ; https://dev.to/kunal_d6a8fea2309e1571ee7/paperclip-ai-review-i-tried-to-build-a-zero-human-company-in-a-weekend-2026-16d ; https://vibecoding.app/blog/paperclip-review ; https://videohighlight.com/v/Yp5KiHBSpZo ; https://ai.engineer/talks/h403btjldDQ-paperclip-open-source-human-control-plane-ai ; https://rywalker.com/research/paperclip ; https://paperclipcloud.com/ ; https://paperclip.ing/changelog/ ; https://www.sofarbot.com/stories/polsia-ben-broca-500000-monthly-revenue ; https://preuve.ai/blog/polsia-review ; https://aiolum.com/story/polsia/ ; https://aiweekly.co/alerts/polsia-solo-founder-raises-30m-at-250m-valuation ; https://www.lindy.ai/blog/relevance-ai-pricing ; https://www.eesel.ai/blog/lindy-vs-relevance-ai ; https://www.g2.com/products/relevance-ai/pricing ; https://agentshortlist.com/compare/lindy-vs-relevance-ai ; https://spiritt.ai/resources/guides/is-manus-worth-it ; https://www.sokosumi.com/compare/manus-vs-genspark ; https://fluxgravity.io/guides/genspark-pricing ; https://aipricecompare.org/apps/genspark.html

## Implications for FactoryOS

Verdict: REFERENCE DESIGN now, with an optional time-boxed, zero-cost local PILOT later. Do not adopt Paperclip as the production control plane, and do not reject it.

Reasons
1. The binding constraint is revenue, not orchestration. FactoryOS has no paying customer; Paperclip and its showcased users show no verified revenue either. Swapping control planes changes nothing a customer would pay for.
2. Paperclip under the owner's rules is at its weakest. It assumes many always-on agents; on one Claude Pro plan, headless runs appear to fall under a separate metered credit, dollar budgets do not bind on flat-rate usage, and quota handling has open defects. The owner rule "Subscription access must never be silently replaced with PAYG API usage" is exactly the risk here.
3. Migration cost is real and recurring (second stack, Postgres, weekly migrations, Telegram regression) for a solo operator.
4. Yes, FactoryOS is re-building something that exists. The right response is to stop extending the generic parts, not to spend weeks migrating them.

What to do
- Freeze new generic control-plane features (more office views, new lane mechanics, new board types). Open source has commoditised them: Paperclip 114.5k stars, Multica 56.5k. They are not a product to sell.
- Port these Paperclip lessons into Relay, each a small task:
  - Event-driven wakes only; no timer that wakes an LLM when there is no actionable work (Paperclip's `skipTimerWhenNoActionableWork`, issue #3401).
  - Budgets in units that bind on subscriptions: runs per day, turns per run, wall-clock, and quota windows, not dollars (discussion #16618, issue #1756).
  - Quota-aware gate: when a provider returns a limit with a reset time, create no new runs for that lane until then (issue #11597).
  - Loop breaker: after two identical failures stop automatic reassignment and raise a "Need you" ticket (discussion #16618, issue #390).
  - A blocked ticket must name an owner and the event that unblocks it (discussion #16618).
  - Keep single-assignee atomic claim, fail-closed signed approvals and an activity log for every mutating action as explicit invariants with tests (Paperclip AGENTS.md).
  - Treat agent "done" as a claim to verify by external evidence; the journalism case shows fabricated sources and a publisher dead for four days without anyone noticing (discussion #5416).
- Keep what Paperclip lacks: Telegram as the console, the mandatory human approval before publishing, outreach or payment, and the content and MVP pipelines.
- Optional pilot, only after a first revenue experiment is running: one to two days, Paperclip in `local_trusted` mode with embedded Postgres on an existing machine, FactoryOS registered as a single `http` agent, heartbeat timers off, telemetry off (`DO_NOT_TRACK=1`). Success test: does the Paperclip board save the owner time compared with Telegram plus Relay over one week? If not, delete it. Do not put it on Render or the public internet.
- Revisit adoption if either happens: the owner approves an API or Max-level budget for several concurrent agents, or FactoryOS needs multi-tenant "one company per customer" isolation, which Paperclip has and Relay does not.
- Do not buy Polsia, Lindy, Relevance AI, Manus, Genspark or Hercules subscriptions for this purpose; each is a new metered cost and none supplies customers.

## Sources

Pages actually opened on 2026-11-17:
- https://github.com/paperclipai/paperclip
- https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/AGENTS.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/PRODUCT.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DEPLOYMENT-MODES.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DOCKER.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/doc/DATABASE.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/overview.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/http.md
- https://raw.githubusercontent.com/paperclipai/paperclip/master/docs/adapters/claude-local.md
- https://github.com/paperclipai/paperclip/tree/master/doc
- https://github.com/paperclipai/paperclip/tree/master/docs
- https://github.com/paperclipai/paperclip/tree/master/docs/adapters
- https://github.com/paperclipai/paperclip/releases
- https://github.com/paperclipai/paperclip/releases/tag/v2026.1106.0
- https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+is%3Aopen+sort%3Areactions-%2B1-desc
- https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+runaway+OR+%22burned%22+OR+%22infinite+loop%22+OR+%22budget+exceeded%22+sort%3Acomments-desc
- https://github.com/paperclipai/paperclip/issues?q=is%3Aissue+%22Agent+SDK+credit%22+OR+%22extra+usage%22+OR+%22subscription+limits%22+sort%3Aupdated-desc
- https://github.com/paperclipai/paperclip/issues/2681
- https://github.com/paperclipai/paperclip/issues/3401
- https://github.com/paperclipai/paperclip/issues/11597
- https://github.com/paperclipai/paperclip/issues/13725
- https://github.com/paperclipai/paperclip/discussions?discussions_q=revenue+OR+customers+OR+%22paying%22+sort%3Atop
- https://github.com/paperclipai/paperclip/discussions/categories/show-and-tell
- https://github.com/paperclipai/paperclip/discussions/5416
- https://github.com/paperclipai/paperclip/discussions/16618
- https://github.com/anthropics/claude-code/issues?q=is%3Aissue+%22Agent+SDK+credit%22+sort%3Acomments-desc
- https://github.com/anthropics/claude-code/issues/59823
- https://github.com/multica-ai/multica
- https://github.com/openclaw/openclaw
- https://github.com/FoundationAgents/MetaGPT
- https://github.com/OpenBMB/ChatDev
- Local repository files: `ROADMAP.md`, `docs/RELAY.md`, `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md`, `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, `relay.py`, `relay_execution.py`, `relay_agent_messages.py`, `agent_workspace.py`, `lane_board.py`, `operator_lanes.py`, `app.py`
