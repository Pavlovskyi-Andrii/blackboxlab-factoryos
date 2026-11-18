# Claude Code and Anthropic agent infrastructure as the substrate of a 24/7 autonomous company (state as of 17-18 Nov 2026)

Scope: what Claude Code and related Anthropic products can and cannot do unattended, what they cost, what the terms allow, and what this means for FactoryOS under "ZERO ADDITIONAL SPEND" (existing Claude Pro only).

Method and source limits: network policy blocked direct fetches of code.claude.com, support.claude.com, claude.com, platform.claude.com and anthropic.com. Facts from those sites come from **search extracts of the official URL** (labelled "search extract"). Pages opened in full: the Claude Code `CHANGELOG.md` on GitHub (top 100k chars, versions 2.1.323-2.1.327) and the `claude-agent-sdk` PyPI page. API model ids and prices were also cross-checked against the bundled `claude-api` skill reference (cached 2026-11-03) shipped with Claude Code 2.1.327. FactoryOS facts come from the local repository. I also observed one thing first-hand: this research run is itself a Claude Code 2.1.327 cloud session. Its tool surface includes spawning child sessions, cross-session messaging, scheduled tasks ("triggers"), PR-activity subscriptions and inbound webhooks.

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | Subscription OAuth is "intended exclusively" for ordinary use of Claude Code and native Anthropic apps. Developers building products or services, including Agent SDK products, must use API keys. Third parties may not offer claude.ai login, route requests through Free/Pro/Max/Ultra credentials on behalf of users, or collect or intermediate Claude credentials. | https://code.claude.com/docs/en/legal-and-compliance ; https://code.claude.com/docs/en/agent-sdk/overview | live docs, Nov 2026 (search extract) | verified_primary (search extract) |
| 2 | `claude setup-token` mints a one-year OAuth token (`CLAUDE_CODE_OAUTH_TOKEN`) for CI and scripts on Pro/Max/Ultra/Team/Enterprise. GitHub Actions with that token bill the subscription, not the API. In `-p` mode, a present `ANTHROPIC_API_KEY` always wins and bills the API. | https://code.claude.com/docs/en/authentication ; https://code.claude.com/docs/en/headless ; https://code.claude.com/docs/en/github-actions | Nov 2026 (search extract) | verified_primary (search extract) |
| 3 | Anthropic cut subscription access for OpenClaw and other third-party harnesses on 4 Apr 2026. Secondary sources say the legal terms were updated on 20 Feb 2026, after a 9 Jan 2026 block that was reversed. Whether a harness that shells out to `claude -p` counts is contested. | https://news.ycombinator.com/item?id=47633396 ; https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use | Feb-Apr 2026 | reported_secondary |
| 4 | Pro costs $20/month ($17/month billed annually) and includes Claude Code. Pro and Max have a 5-hour session limit plus a weekly limit, shared across Claude chat, Claude Code, cloud sessions and scheduled tasks. Anthropic may add further caps at its discretion. | https://claude.com/pricing ; https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work ; https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan | Nov 2026 (search extract) | verified_primary (search extract) |
| 5 | The new Ultra plan is $200/month (monthly billing only), with 10x Pro usage per week and no 5-hour limit for verified accounts. Fable usage is capped at 50% of the weekly limit, and the plan includes a $200 monthly API credit. Max is $100/month for 5x. Sources conflict on whether "Max 20x" still exists or was renamed Ultra. | https://support.claude.com/en/articles/17728952-what-is-the-ultra-plan ; https://support.claude.com/en/articles/11049741-what-is-the-max-plan | Nov 2026 (search extract) | verified_primary (search extract), tier naming conflicting |
| 6 | Fable models are not included in Pro limits; they need paid usage credits. A free Pro Fable week ran 9-16 Nov 2026 and has ended. Opus "uses meaningfully more of your quota" than Sonnet. | https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan ; https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code | Nov 2026 (search extract) | verified_primary (search extract) |
| 7 | Scheduled tasks (formerly "routines") run in the cloud on Pro and above. They are a research preview, count against plan limits, are capped at 100 scheduled runs/hour per account and 30 "run now"/API runs/hour per task, and have no overage without usage credits. The April 2026 launch post gave daily caps (Pro 5, Max 15, Team/Enterprise 25), which the current docs no longer state. | https://code.claude.com/docs/en/routines ; https://claude.com/resources/articles/introducing-routines-in-claude-code | Nov 2026; launch ~Apr 2026 | verified_primary (search extract), conflicting over time |
| 8 | Cloud sessions (Claude Code on the web) are available on Pro, Max, Ultra, Team and Enterprise. They count against plan usage, with no separate VM charge. Network secrets are available on Pro. | https://code.claude.com/docs/en/web-quickstart ; https://code.claude.com/docs/en/cloud-environments | Nov 2026 (search extract) | verified_primary (search extract) |
| 9 | Agent teams are experimental and off by default (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS`). They are token-intensive, CLI only, and never spawned in `-p`/Agent SDK mode. Channels (Telegram, Discord and iMessage plugins) are a research preview that only works while a session is open. | https://code.claude.com/docs/en/agent-teams ; https://code.claude.com/docs/en/channels | Nov 2026 (search extract) | verified_primary (search extract) |
| 10 | Claude Agent SDK (Python) 0.2.184 was released 18 Nov 2026. It is MIT-licensed, has the PyPI classifier "3 - Alpha", and points to Anthropic's Commercial Terms. | https://pypi.org/project/claude-agent-sdk/ | 18 Nov 2026 | verified_primary |
| 11 | API list prices per 1M tokens (input/output): Opus 5.5 $4/$20, Sonnet 5.5 $2/$10, Haiku 5.5 $0.10/$0.50 (for prompts up to 100K tokens). Batch is 50% off. Cache reads cost $0.20 (Opus 5.5), $0.10 (Sonnet 5.5) and $0.01 (Haiku 5.5). Cache writes cost 1.25x (5-minute TTL) or 2x (1-hour TTL). | https://platform.claude.com/docs/en/about-claude/pricing ; claude-api skill (cached 2026-11-03) | Nov 2026 | verified_primary (search extract and skill) |
| 12 | Managed Agents is in beta (`managed-agents-2026-04-01`). It bills tokens plus $0.08 per session-hour of *running* time (idle time is free) and supports cron "scheduled deployments", vaults, outcomes and multi-agent workflows. It is not available on Bedrock or Vertex. | https://platform.claude.com/docs/en/managed-agents/overview ; https://claude.com/blog/claude-managed-agents | Nov 2026 (search extract and skill) | verified_primary (search extract) |
| 13 | On 6 May 2026 Anthropic doubled Claude Code's 5-hour limits for Pro, Max, Team and seat-based Enterprise, and removed the spring 2026 peak-hours reduction for Pro and Max. | https://www.anthropic.com/news/higher-limits-spacex | 6 May 2026 (search extract) | verified_primary (search extract) |
| 14 | Ukraine is a supported country except Crimea, Donetsk, Kherson, Luhansk and Zaporizhzhia regions. The API docs list only three excluded regions, so the lists are inconsistent. | https://www.anthropic.com/supported-countries ; https://platform.claude.com/docs/en/api/supported-regions | policy page dated 12 Nov 2026 (search extract) | verified_primary (search extract) |
| 15 | FactoryOS's autopilot already reimplements, for the Claude lane, much of what Claude Code now ships natively: scheduling, a daemon worker, inter-session messaging, a phone/Telegram control surface and limit-reset handling. Relay's unique value is only the cross-vendor lane and the audit/approval layer. | local repo `autopilot/delegation.py`, `autopilot/claude_pro_worker.py`, `autopilot/TERMUX_BOOT.md` plus rows 7-9 | 17 Nov 2026 | inference |

---

## 1. Capabilities: what runs unattended, and GA vs beta

### Takeaway
Claude Code now has native primitives for almost every layer of an "autonomous dev worker": a headless CLI, cloud sessions, cron-style scheduled tasks, cross-session messaging, Projects, a Telegram channel, GitHub Actions, hooks, skills and plugins. Most of the *unattended* and *multi-agent* pieces are research preview, beta or experimental, and all subscription use draws on one shared, capped quota.

### Cited findings
- **Headless / non-interactive.** `claude -p` runs programmatically. `--bare` skips the subscription path and ignores `CLAUDE_CODE_OAUTH_TOKEN`. A present `ANTHROPIC_API_KEY` is always used in `-p` mode ([headless docs, search extract](https://code.claude.com/docs/en/headless)). Cloud `-p` (`claude -p --cloud` / `--environment`) does not accept API keys. Its session-control scope is capped at 30 days, so the one-year inference-only setup token does not cover it, and the docs suggest running `claude -p` from a long-lived host instead ([self-hosted environments testing, search extract](https://code.claude.com/docs/en/self-hosted-environments-testing)).
- **Release cadence and maturity.** The changelog's newest entry is 2.1.327 (no dates on the page). Recent entries touch `-p` hangs, headless resume losing messages, agent teams, background agents, auto mode, the sandbox, plugins and scheduled tasks ([CHANGELOG.md, opened](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)). Examples:
  - 2.1.327: "Fixed `claude -p` hanging before its first request when the fetch of a model's settings stalled" and "Self-hosted runner: Fixed `claude -p` started by a session's script or hook waiting out rate limits".
  - 2.1.325: "Fixed background sessions started on your claude.ai login using (and billing) an API key or token". This was a real billing-leak bug.
  - 2.1.325: "Changed scheduled tasks and `/loop` to ask before running a skill that declares `allowed-tools` or hooks".
  - 2.1.326: "Changed terminal and VS Code sessions with no mode set to start in auto mode, not Manual mode". Also: "Fixed auto mode staying on its local classifier, which counts toward usage".
  - 2.1.323: "Added an options menu (stop, switch to usage credits, upgrade) when a model needs usage credits".
- **Cloud sessions (Claude Code on the web).** Available on Pro, Max, Ultra, Team and Enterprise (premium or Code seats). Each session counts toward plan usage with "no separate charge for the cloud VM". Network secrets are available on Pro and above. Admins can disable the feature ([web quickstart / cloud environments, search extract](https://code.claude.com/docs/en/web-quickstart)).
- **Scheduled tasks (formerly routines).** A research preview on Pro and above. Runs count against usage. Limits are 100 scheduled runs/hour/account and 30 "run now"/API runs/hour/task, with no overage; without usage credits, extra runs are rejected until the window resets ([routines docs, search extract](https://code.claude.com/docs/en/routines)). The April 2026 launch article gave daily caps of Pro 5 / Max 15 / Team-Enterprise 25 routines per day ([launch post, search extract](https://claude.com/resources/articles/introducing-routines-in-claude-code)). The current docs no longer mention daily caps, so the effective Pro ceiling is unclear (see Gaps). First-hand: this session's scheduling tool says the minimum interval is "normally hourly".
- **Agent teams.** Experimental, enabled by an env var, with known limits on resumption, coordination and shutdown. They are token-intensive and **not spawned in `-p` or Agent SDK sessions**, and are not in Desktop ([agent-teams docs, search extract](https://code.claude.com/docs/en/agent-teams)). Agent view is a research preview ([agent-view, search extract](https://code.claude.com/docs/en/agent-view)).
- **Projects and cross-session messaging.** Projects (public beta, Pro/Max/Ultra only) are one long-running conversation that opens parallel threads in the cloud or, via Remote Control, on your computer. Cross-session messaging uses `ListAgents` / `SendMessage` (v2.1.224+). Messages between machines route through Anthropic, and cross-machine discovery needs a claude.ai sign-in, not an API key ([cross-session messaging, search extract](https://code.claude.com/docs/en/cross-session-messaging)).
- **Channels.** MCP servers that push outside events into an open session. Telegram, Discord and iMessage are in the research preview. The Telegram plugin polls locally (no public URL), only paired sender IDs can post, and messages only arrive while the session is open ([channels docs, search extract](https://code.claude.com/docs/en/channels)).
- **GitHub.** The open-source Claude Code GitHub Action can use an OAuth token, in which case runs bill the subscription ([github-actions docs, search extract](https://code.claude.com/docs/en/github-actions)). The managed **Code Review** product is GA for Team/Enterprise only. It has no flat price, averages about $15-25 per review, and is billed through usage credits separately from plan usage ([code-review-costs, search extract](https://code.claude.com/docs/en/code-review-costs)).
- **Skills, AGENTS.md, plugins, MCP, hooks.** Claude Code skills follow the open Agent Skills standard ([skills docs, search extract](https://code.claude.com/docs/en/skills); [agentskills.io](https://agentskills.io/home)). Claude Code reads `AGENTS.md` only when no `CLAUDE.md` exists, unless a setting enables both; this needs v2.1.277+ ([memory docs, search extract](https://code.claude.com/docs/en/memory)). Plugins, hooks and MCP are mature, frequently patched parts of the CLI ([CHANGELOG](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)).
- **Auto mode.** A classifier approves safe actions and blocks risky ones. It is no longer framed as a research preview, needs Opus/Sonnet 4.6+, Haiku 5.5 or Fable, and admins can disable it ([what's new, search extract](https://code.claude.com/docs/en/whats-new)). Its classifier "counts toward usage" ([CHANGELOG 2.1.326](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md)).
- **Claude Agent SDK.** Python package `claude-agent-sdk` 0.2.184, released 18 Nov 2026, MIT, classifier "3 - Alpha", referring to Commercial Terms ([PyPI, opened](https://pypi.org/project/claude-agent-sdk/)). The SDK overview says third-party developers may not offer claude.ai login or rate limits for their products, including agents built on the Agent SDK, unless previously approved ([Agent SDK overview, search extract](https://code.claude.com/docs/en/agent-sdk/overview)).
- **API-side agent infrastructure** (claude-api skill reference, cached 2026-11-03; [pricing, search extract](https://platform.claude.com/docs/en/about-claude/pricing)):
  - Managed Agents is beta (`managed-agents-2026-04-01`). Anthropic hosts the loop and a per-session container. It adds cron "scheduled deployments", vaults (secrets substituted at egress), outcomes (a grader loop), multi-agent workflows and session budgets. It is not on Bedrock or Vertex.
  - The memory tool is `memory_20250818`, on the non-beta client in most SDKs.
  - Server code execution is `code_execution_20260521`, with no beta header.
  - Computer use is beta on all platforms. Opus 5.5 on the Claude API accepts only `computer_toolset_20260801` (GA).
  - Compaction and context editing are beta.

### Inferences
- The *capabilities* exist natively. What makes them hard to rely on 24/7 is their **status** (preview, beta or experimental, with frequent behavioural changes in a CLI that releases several times a week) and the **shared quota**, not missing features.
- `-p` (what FactoryOS uses) is the most stable unattended entry point. Agent teams are explicitly unavailable there.

### Gaps
- Whether cloud sessions are formally "GA" or still "research preview" was not found.
- Whether auto mode is available on Pro subscriptions, as opposed to only "users on the Anthropic API", is ambiguous in the extract.
- Whether Pro still has a per-day cap on scheduled tasks is not stated in current docs.

---

## 2. Plans, limits, API prices, and what a 24/7 workload costs

### Takeaway
Pro ($20) is a capped, shared, unpublished-size quota. It cannot sustain a 24/7 agent, and the first thing to break is the 5-hour window, then the weekly cap. The cheapest *subscription* step up is Max at $100/month (5x). For product-side LLM calls, metered API use of Haiku 5.5 or Sonnet 5.5 with caching and batch is far cheaper than any plan upgrade, but it is new spend.

### Cited findings
- **Pro:** $20/month, or $17/month billed annually ($200 up front). Claude Code is included ([pricing, search extract](https://claude.com/pricing)). There is a 5-hour session limit plus a weekly limit, both shared across Claude and Claude Code ([usage limits, search extract](https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work)). Pro users can enable usage credits to continue past limits ([Claude Code models/limits, search extract](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)).
- **Max:** $100/month for 5x Pro per 5 hours and per week. Max has a separate weekly Fable limit ([Max plan, search extract](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)). An older Max page lists Max 20x at $200, while the Ultra page and the homepage show a $200 "Ultra" tier instead, so the tiers conflict.
- **Ultra:** $200/month, monthly only. It gives 10x Pro usage weekly and **no 5-hour limit once the account is verified**. Fable is capped at 50% of weekly usage. Anthropic says additional caps "may apply… at our discretion". Usage credits are billed at standard API rates. The plan includes a $200/month API credit for the Claude Platform ([Ultra plan, search extract](https://support.claude.com/en/articles/17728952-what-is-the-ultra-plan)). Monthly API credits included with Max cannot be used in Claude Code or the apps ([Max plan, search extract](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)).
- **Fable on Pro:** not included; usage credits only. Fable 5.2 needs Claude Code 2.1.321+. A one-week Pro promo ran 9-16 Nov 2026 ([Fable on your plan, search extract](https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan)). Opus "uses meaningfully more of your quota" ([models/limits, search extract](https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code)).
- **2026 limit changes:**
  - Spring 2026: peak-hours limit reduction on Claude Code.
  - 6 May 2026: Anthropic doubled Claude Code's 5-hour limits for Pro/Max/Team/seat Enterprise and removed the peak-hours reduction ([Anthropic news, search extract](https://www.anthropic.com/news/higher-limits-spacex)).
  - Weekly-limit promotions after May are reported inconsistently by secondary blogs ([truefoundry](https://www.truefoundry.com/blog/claude-code-limits-explained), not opened).
- **API prices per 1M tokens** ([pricing, search extract](https://platform.claude.com/docs/en/about-claude/pricing); skill table cached 2026-11-03):

  | Model | Input | Output | Cache read | Batch (input/output) |
  |---|---|---|---|---|
  | Opus 5.5 | $4 | $20 | $0.20 | $2 / $10 |
  | Sonnet 5.5 | $2 | $10 | $0.10 | $1 / $5 |
  | Haiku 5.5 (prompt ≤100K) | $0.10 | $0.50 | $0.01 | $0.05 / $0.25 |
  | Haiku 5.5 (prompt >100K) | $0.50 | $2.50 | $0.05 | — |
  | Fable 5.2 | $8 | $40 | $0.20 | — |

  - Cache writes cost 1.25x (5-minute TTL) or 2x (1-hour TTL). The batch discount stacks with caching. Batch is not available for Managed Agents sessions (skill `shared/prompt-caching.md`, `cost-optimization.md`).
  - Opus 5.5 thinking cannot be disabled (default effort `medium`). Thinking tokens bill as output whether or not they are displayed (skill).
- **Managed Agents:** tokens plus $0.08 per session-hour, metered only while "running" (idle time is free). It replaces container-hour billing and has no seat fees. Anthropic's worked example is a one-hour Opus 5.5 session with 50K input and 15K output tokens for $0.58 ([pricing / blog, search extract](https://claude.com/blog/claude-managed-agents)).

### Cost model (inference; my assumptions, list prices above, not measured)
One "agent turn" is a 60K-token prompt (58K cache-read, 2K newly cache-written at 1.25x) plus 1.5K output tokens including thinking.

| Option | Per turn | Continuous loop, 1 turn/min 24/7 (~43k turns/mo) | Event-driven, 300 tasks × 15 turns (4.5k turns/mo) |
|---|---|---|---|
| Haiku 5.5 API | ~$0.0016 | ~$68/mo | ~$7/mo |
| Sonnet 5.5 API | ~$0.026 | ~$1,100/mo | ~$115/mo |
| Opus 5.5 API | ~$0.052 | ~$2,200/mo | ~$230/mo |
| Sonnet 5.5 API **without caching** | ~$0.135 | ~$5,800/mo | ~$600/mo |
| Managed Agents runtime surcharge | — | +$57.60/mo if always "running" | +~$4/mo (assuming ~10 min per task) |
| Claude Pro | $20 flat | **not possible**: the 5-hour and weekly caps stop it | plausible for a few tasks per day, Sonnet-first |
| Max 5x / Ultra | $100 / $200 flat | not possible on Max; Ultra has no 5-hour cap but a weekly 10x Pro cap | comfortable on Max for dev work |

Caching is a 4-5x lever. Batch halves any work nobody waits on. Subscriptions are the cheapest substrate for *development work by the owner*. They are not a legal substrate for customer-facing product traffic (section 3).

### Gaps
- Anthropic publishes no token or message numbers for Pro's 5-hour or weekly limits. Users can only see percentages in Settings > Usage.
- Whether "Max 20x" still exists or was replaced by Ultra could not be confirmed.
- The size of the Max plan's monthly API credit was not verified.

---

## 3. Terms: subscription credentials for automation, CI and third-party harnesses

### Takeaway
The owner's own `claude -p` scripts, CI runs and cloud or scheduled sessions on his own subscription and his own code are documented, supported uses. Two things are prohibited, with active enforcement since April 2026: using the subscription to **power a product or other people's requests** (MyCast or MyBrief for users, a public bot), and running it **inside a third-party harness** via OAuth tokens.

### Cited findings
- The legal page says OAuth is meant only for subscription holders' ordinary use of Claude Code and native Anthropic apps. Developers building products or services, "including those using the Agent SDK", should use API keys through Claude Console or a supported cloud provider. Anthropic does not permit third parties to offer claude.ai login, to route requests through Free/Pro/Max/Ultra credentials on behalf of their users, or to collect, store or intermediate Claude credentials or session tokens ([legal and compliance, search extract](https://code.claude.com/docs/en/legal-and-compliance)).
- `claude setup-token` is documented for "CI pipelines and scripts where browser login isn't available". It is tied to the subscription of whoever ran it and can only make model requests ([authentication, search extract](https://code.claude.com/docs/en/authentication)).
- The Individual Consumer Terms (dated 8 Oct 2025) govern Free/Pro/Max, "including usage of Claude Code and Claude Cowork through those plans". API use falls under the Commercial Terms ([Legal Center, search extract](https://www.anthropic.com/legal); [API for individual use, search extract](https://support.anthropic.com/en/articles/8987200-can-i-use-the-anthropic-api-for-individual-use)). I could not retrieve the consumer terms' exact clause on automated access.
- **Enforcement timeline** (secondary sources):
  - 9 Jan 2026: a first block, reversed after backlash.
  - 20 Feb 2026: terms updated ([AlternativeTo](https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use)).
  - 4 Apr 2026: subscription OAuth stopped working for OpenClaw and was announced for other third-party harnesses. Claude Code, Claude.ai and Desktop are unaffected ([HN thread](https://news.ycombinator.com/item?id=47633396); [MindStudio](https://www.mindstudio.ai/blog/anthropic-openclaw-ban-oauth-authentication)).
  - An HN commenter argued that OpenClaw itself shelled out to `claude -p`, so the technical boundary is contested ([HN](https://news.ycombinator.com/item?id=47633396)).
- Google applies the same pattern: it flags "Gemini CLI OAuth with third-party software" as policy-violating, and ended personal Gemini CLI access on 18 Jun 2026 ([sibling notes `tool_openai_google.md`, rows 1 and 3](https://github.com/google-gemini/gemini-cli/discussions/22970)).

### Inferences
- FactoryOS's *build lane* is on the permitted side: owner-run `claude -p` against the owner's repository from his own device, with the official CLI and its own login. Its **architecture**, however, resembles OpenClaw: a home-grown orchestrator plus a dashboard plus a Telegram front end driving `claude -p`. If Anthropic tightens enforcement on "harness-like" `claude -p` usage, FactoryOS is exposed. Keeping the Claude lane inside first-party surfaces (cloud sessions, scheduled tasks, GitHub Action) lowers that risk.
- Any feature that serves **end users** must not call Claude through the Pro worker. Under zero spend that means no Claude in the product path until there is revenue or approved API spend.

---

## 4. Non-coding business operations (sales, content, support)

### Takeaway
Claude Code is a capable *operator console* for business tasks, through MCP connectors, skills, web fetch and browser automation. Its safety model is a permission system for tool calls, not a business-approval workflow. Unattended runs either disable the gate (`--dangerously-skip-permissions`) or delegate it to a probabilistic classifier (auto mode). The human approval gate for publishing and outreach therefore has to be enforced outside the model, through tool allowlists, hooks, and side-effect tools that only create drafts.

### Cited findings
- Connectors are MCP servers. Claude.ai connectors are not available through the setup token ("can't… fetch claude.ai connectors") ([authentication, search extract](https://code.claude.com/docs/en/authentication)). First-hand: this cloud session exposes Gmail, Calendar, Drive, Notion, Linear, Sentry, Shopify, vidIQ, Canva and Figma connectors as deferred MCP tools, including send and publish actions such as `Gmail send_message`, `vidIQ social_post_publish` and `instagram_publish_reel`. A misconfigured unattended session can therefore publish.
- Permission levers:
  - `--allowedTools` / `--disallowedTools`.
  - Permission modes: manual, plan, auto, bypass.
  - PreToolUse hooks that can deny.
  - A Bash sandbox that refuses writes to `.claude` settings, skills and hooks (2.1.325).
  - Managed settings for organisations.
  ([CHANGELOG](https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md); [hooks reference](https://code.claude.com/docs/en/hooks))
- Auditability: session transcripts and events, hook logs, `-p --output-format json`/stream-json, and OpenTelemetry on the API side (skill). Code Review's spend dashboards are Team/Enterprise only.
- Managed Agents permission policies (`always_allow` / `always_ask` / `auto`) and vault credentials are the API-side equivalent (skill `managed-agents-tools.md`). They are a cleaner design than a phone daemon, but paid.

### Inferences
- For sales, content and support, the bottleneck is not the agent substrate. It is distribution, approvals and a paying customer, as other notes in this project document. Claude Code does not change that.

---

## 5. Lock-in, portability, and comparison with Codex and Gemini CLI

### Cited findings
- **Portable:** MCP (open spec; the sibling notes record the 2026-07-28 revision), Agent Skills (open standard, agentskills.io, with a `.agents/skills/` convention) and AGENTS.md (read by Claude Code since v2.1.277) ([skills](https://code.claude.com/docs/en/skills); [memory](https://code.claude.com/docs/en/memory); [agentskills.io](https://agentskills.io/home)).
- **Anthropic-only:** hooks and settings format, plugins marketplace, cloud sessions, scheduled tasks, Projects, Channels, Remote Control, cross-session messaging (not with API keys or on Bedrock, Vertex or Foundry), and Managed Agents (not on Bedrock or Vertex) ([cross-session messaging](https://code.claude.com/docs/en/cross-session-messaging); skill `platform-availability.md`).
- **Codex CLI:** Apache-2.0, `codex exec` headless mode, signs in with a ChatGPT plan; its official GitHub Action requires an API key. **Gemini CLI:** personal and free-tier access ended 18 Jun 2026, replaced by Antigravity CLI with weekly quotas ([sibling notes, `tool_openai_google.md` rows 1-7](https://github.com/openai/codex)).

### Inferences
- Claude Code's *subscription CI* path (the GitHub Action with an OAuth token) is more generous than Codex's (API key only). Its *third-party harness* stance is stricter than OpenAI's (OpenClaw moved to Codex OAuth after the April ban; secondary sources, [MindStudio](https://www.mindstudio.ai/blog/anthropic-openclaw-ban-oauth-authentication)).
- Keeping FactoryOS instructions in AGENTS.md and skills, and integrations in MCP, keeps switching cost low. Building on Projects, Channels or scheduled tasks increases lock-in to research-preview features.

---

## Counter-evidence and caveats

- **Preview churn.** Scheduled tasks, Channels, agent view and agent teams are research preview or experimental, and Projects is public beta. The scheduled-task limits already changed from daily caps (April 2026) to hourly caps (Nov 2026). Building core operations on them risks breakage with each release, and the CLI ships near-daily (2.1.323 to 2.1.327 within days).
- **Quota opacity and discretion.** No published token numbers. Every plan page reserves the right to add weekly, monthly, model or feature caps "at our discretion". Spring 2026 saw a peak-hours cut, later removed (6 May). A 24/7 design that depends on Pro quota depends on a number Anthropic can change unilaterally.
- **Billing-leak risk.** 2.1.325 fixed background sessions billing an API key or token instead of the claude.ai login. In `-p` mode a stray `ANTHROPIC_API_KEY` always wins. 2.1.323 added a "switch to usage credits" prompt. Under zero spend, usage credits must stay disabled at the account level, and the environment must never carry an API key. FactoryOS already unsets the key (`autopilot/TERMUX_BOOT.md`).
- **Policy ambiguity.** "Ordinary use" is undefined. Enforcement against harnesses is real (April 2026), and the `claude -p` boundary is disputed. Most enforcement details come from secondary blogs and HN (anecdotal).
- **Auto mode is not an approval gate.** It is a classifier, and it costs usage. Changelog entries show it repeatedly tightened which allow-rules it honours, so it is still evolving.
- **Agent SDK maturity.** "3 - Alpha" on PyPI despite 0.2.184 releases. That is not a stable base for a product.
- **Model quality vs cost.** Haiku 5.5's low price is attractive, but I found no independent evidence that it is good enough for FactoryOS's agentic tasks.
- **Regional caveat.** Supported-regions lists disagree (three vs five excluded Ukrainian regions). I did not verify payment acceptance for Ukrainian cards; the owner already pays for Pro.

---

## Implications for FactoryOS (opinionated)

1. **Stop building agent-orchestration plumbing for the Claude lane.** Claude Code already ships each piece, at the same $0 marginal cost on Pro:

   | FactoryOS component | Native Claude Code equivalent |
   |---|---|
   | Termux phone daemon | cloud sessions |
   | Autopilot cron | scheduled tasks or the GitHub Action |
   | Claude-to-Claude parts of Relay | cross-session messaging and Projects |
   | Telegram control of the Claude lane | Channels and Remote Control |
   | Worker Center views of Claude runs | claude.ai/code |

   Keep Relay only for what is unique: the cross-vendor lane (whose value shrank after Gemini CLI personal access ended in June 2026), the audit trail and the publishing approval gate.
2. **Pro is a development substrate, not a production substrate.** Use it for owner-directed build work (`claude -p`, cloud sessions, a few scheduled tasks per day, Sonnet by default and Opus sparingly). Never route MyCast, MyBrief or any user-facing request through the Pro worker; that is the prohibited "on behalf of users" pattern. Before revenue, product paths should use free tiers already approved, or none.
3. **Harden the unattended Claude worker.** Prefer `--allowedTools` allowlists plus PreToolUse deny hooks for publish, send and pay tools over `--dangerously-skip-permissions`; the flag is optional in `autopilot/delegation.py`, so keep it off. Keep `ANTHROPIC_API_KEY` absent and usage credits disabled. Treat a usage-limit stop as normal; FactoryOS already maps it to `blocked`.
4. **What breaks first on Pro:** the 5-hour window during any long Opus run or parallel agents, then the weekly cap. Agent teams and dynamic workflows multiply consumption. Plan for roughly a few focused agent hours a day, not 24/7.
5. **Cheapest upgrade path, once justified by revenue:**
   - For dev throughput: Max 5x at $100/month.
   - For product LLM calls: the API with Haiku 5.5 or Sonnet 5.5, prompt caching and batch. Roughly $7-115/month for an event-driven workload of about 4.5k turns (assumptions above), versus about $1.1k/month for a continuous Sonnet loop.
   - Ultra at $200 only if the 5-hour cap is the binding constraint. Its $200 API credit could fund the product path, but that is unverified for Max.
   - Managed Agents ($0.08 per running hour plus tokens) is the "grown-up" version of FactoryOS's worker architecture. It is worth evaluating only after there is paying demand.
6. **Verdict per capability:**

| Capability | Verdict | Why |
|---|---|---|
| `claude -p` headless on own Pro login | **Adopt** (already in use) | Documented, permitted, $0; harden permissions |
| Cloud sessions (Claude Code on the web) | **Adopt / pilot** | Replaces the fragile phone daemon; no VM charge; same quota |
| Scheduled tasks (routines) | **Pilot** | Research preview; quota-bound; good for 1-3 daily jobs |
| GitHub Action with `CLAUDE_CODE_OAUTH_TOKEN` | **Pilot** | Subscription-billed @claude on issues and PRs; watch quota |
| Managed Code Review | **Reject** | Team/Enterprise plus usage credits, about $15-25 per review |
| Subagents / skills / hooks / MCP / plugins | **Adopt** | Free, mostly portable (Agent Skills, MCP); hooks enforce gates |
| AGENTS.md + skills as instruction format | **Adopt** | Lowers lock-in across Claude, Codex and Gemini lanes |
| Agent teams | **Reference** | Experimental, token-heavy, not in `-p` |
| Channels (Telegram) | **Reference / pilot** | Research preview; needs an open session; could replace Claude-lane Telegram glue |
| Cross-session messaging / Projects | **Reference → pilot** | Overlaps Relay's Claude-to-Claude role; Anthropic-hosted |
| Claude Agent SDK | **Reject now** (reference) | Products must use API keys, which is paid; Alpha |
| Managed Agents (+ scheduled deployments, vaults) | **Reference** | Beta, paid; revisit after revenue |
| Memory tool / computer use / code-exec sandbox | **Reference** | API-only, paid; FactoryOS has Notion and Playwright |
| Fable models | **Reject** | Not in Pro limits; usage credits only |
| Usage credits / pay-as-you-go | **Reject** (owner policy) | Explicit new spend; keep disabled |

---

## Sources (pages actually opened in full, or read via official-domain search extract)

Opened in full:
- https://raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md (versions 2.1.323-2.1.327; first 100k of 1.32M chars)
- https://pypi.org/project/claude-agent-sdk/ (0.2.184, 18 Nov 2026)
- Local repository: `autopilot/delegation.py` (lines 255-282, 368-465), `autopilot/claude_pro_worker.py`, `autopilot/TERMUX_BOOT.md`; sibling notes `tool_openai_google.md` (Key claims)
- claude-api skill reference bundled with Claude Code 2.1.327 (model table cached 2026-11-03; `shared/prompt-caching.md`, `cost-optimization.md`, `managed-agents-core.md`, `managed-agents-scheduled-deployments.md`, `platform-availability.md`)

Official pages read via search extract (direct fetch blocked by proxy):
- https://code.claude.com/docs/en/legal-and-compliance
- https://code.claude.com/docs/en/authentication
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/self-hosted-environments-testing
- https://code.claude.com/docs/en/github-actions
- https://code.claude.com/docs/en/agent-sdk/overview
- https://code.claude.com/docs/en/routines
- https://code.claude.com/docs/en/web-quickstart
- https://code.claude.com/docs/en/cloud-environments
- https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/agent-view
- https://code.claude.com/docs/en/whats-new
- https://code.claude.com/docs/en/channels
- https://code.claude.com/docs/en/cross-session-messaging
- https://code.claude.com/docs/en/code-review-costs
- https://code.claude.com/docs/en/skills
- https://code.claude.com/docs/en/memory
- https://support.claude.com/en/articles/11647753-how-do-usage-and-length-limits-work
- https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan
- https://support.claude.com/en/articles/11049741-what-is-the-max-plan
- https://support.claude.com/en/articles/17728952-what-is-the-ultra-plan
- https://support.claude.com/en/articles/15424964-claude-fable-models-on-your-plan
- https://support.claude.com/en/articles/14552983-models-usage-and-limits-in-claude-code
- https://claude.com/pricing
- https://claude.com/resources/articles/introducing-routines-in-claude-code
- https://claude.com/blog/claude-managed-agents
- https://platform.claude.com/docs/en/about-claude/pricing
- https://platform.claude.com/docs/en/managed-agents/overview
- https://platform.claude.com/docs/en/api/supported-regions
- https://www.anthropic.com/supported-countries
- https://www.anthropic.com/news/higher-limits-spacex
- https://www.anthropic.com/legal
- https://agentskills.io/home

Secondary or anecdotal (search extract only):
- https://news.ycombinator.com/item?id=47633396
- https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use
- https://www.mindstudio.ai/blog/anthropic-openclaw-ban-oauth-authentication
- https://www.truefoundry.com/blog/claude-code-limits-explained
