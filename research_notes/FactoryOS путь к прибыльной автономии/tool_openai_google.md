# OpenAI and Google agent stacks as platforms for FactoryOS (state: 17 November 2026)

**Read this first - evidence limits of these notes.**
- The session's network policy blocked direct opening of `platform.openai.com`, `developers.openai.com`, `help.openai.com`, `openai.com`, `chatgpt.com`, `openai.github.io`, `ai.google.dev`, `geminicli.com`, `adk.dev`, `jules.google`, `antigravity.google`, `developers.google.com`, `support.google.com`. `cloud.google.com` resolved but its pricing pages were too large to read. Only `github.com` and `pypi.org` could be opened.
- The shared web-search budget ran out after three search rounds. Hosted-tool prices, AgentKit status, Codex automations, ChatGPT tasks/agent limits, Agent Engine prices, media-model prices and the Jules country list could therefore **not** be verified. They are listed under Gaps, not guessed.
- Evidence tags used below: **[O]** = page opened and read by me (GitHub / PyPI / local repo). **[S]** = official page read only through a search-engine summary restricted to the official domain, page not opened. **[3P]** = third-party blog via search summary. **[T]** = my training knowledge (mid-2026 or older), not re-verified - orientation only, do not cite as current.

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | Gemini CLI stopped serving free-tier individual accounts and Google AI Pro/Ultra on 18 June 2026; only Code Assist Standard/Enterprise licences, Google Cloud and API-key auth remain. Individuals are sent to Antigravity CLI. | https://github.com/google-gemini/gemini-cli/discussions/28017 ; https://github.com/google-gemini/gemini-cli/discussions/27274 | Posts of 19 May and 18 June 2026 | verified_primary |
| 2 | FactoryOS's Gemini worker (T-607) is designed around exactly that removed path ("Login with Google", personal free tier); its runbook already records the login "falling back to Enter Gemini API Key", and the owner switched to a free-tier API key on 15 Nov 2026. | Local repo: `docs/handoff/GEMINI_EC2_WORKER.md`, `ROADMAP.md` (T-607) | 15 Nov 2026 | verified_primary |
| 3 | Since 25 March 2026 the Gemini CLI free tier had already been limited to Flash models, and Google announced detection of "using Gemini CLI OAuth with third-party software" as policy-violating use. | https://github.com/google-gemini/gemini-cli/discussions/22970 | 18 Mar 2026 | verified_primary |
| 4 | Antigravity CLI (the replacement) has a headless print mode (`-p`, `--output-format json/stream-json`, `--json-schema`), accepts `GEMINI_API_KEY`, and enforces weekly quotas; the repo states no licence and publishes no quota numbers. | https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md ; https://github.com/google-antigravity/antigravity-cli | v1.5.10 (Nov 2026) | verified_primary |
| 5 | Codex CLI is Apache-2.0, releases almost daily (stable 0.169.0 on 13 Nov 2026), and officially signs in with a ChatGPT plan (Plus, Pro, Business, Edu, Enterprise); it has a non-interactive `codex exec` mode and an SDK that wraps the CLI. | https://github.com/openai/codex ; https://github.com/openai/codex/releases ; https://github.com/openai/codex/blob/main/sdk/typescript/README.md | 13-17 Nov 2026 | verified_primary |
| 6 | Codex on ChatGPT Plus ($20/month) is limited to an estimated 15-160 GPT-6.1 Sol, 5-45 GPT-6 Astra or 350-3,000 GPT-6 Luna messages per five hours (ranges, not guarantees; weekly limits also reported). | https://chatgpt.com/codex/pricing/ | Nov 2026 (search summary) | reported_secondary |
| 7 | OpenAI's official GitHub Action for Codex requires an API key (paid API); its README does not offer ChatGPT-plan login for CI. | https://github.com/openai/codex-action | Nov 2026 | verified_primary |
| 8 | ChatGPT can connect to custom MCP servers with read and write tools, but write actions may need per-action confirmation, and the only scheduling of MCP-using agents found in official docs is for Enterprise workspace agents. No official API drives a consumer ChatGPT subscription as a worker. | https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt ; https://developers.openai.com/api/docs/guides/custom-mcp-server | Nov 2026 (search summary) | reported_secondary |
| 9 | OpenAI Agents SDK (Python) is MIT, provider-agnostic, still 0.x: stable 0.24.0 (15 Oct 2026); November alphas remove `Runner` aliases and rename approval modes - breaking changes roughly monthly. | https://github.com/openai/openai-agents-python/releases ; https://pypi.org/project/openai-agents/ | 15 Oct - 16 Nov 2026 | verified_primary |
| 10 | Google ADK is Apache-2.0, at 2.14.1 (12 Nov 2026), ~bi-weekly releases, graph-based Workflow Runtime, `adk eval`, MCP tools, human confirmation; A2A became stable only in 2.14.0 (7 Nov 2026), which also contains breaking changes. | https://pypi.org/project/google-adk/ ; https://github.com/google/adk-python/releases | 7-12 Nov 2026 | verified_primary |
| 11 | OpenAI API list prices per 1M tokens: GPT-6 Astra $10 in / $1 cached / $50 out; GPT-6.1 Sol $2 / $0.20 / $10; GPT-6.1 Terra $1 / $5; GPT-6 Luna $0.10 / $0.01 / $0.50. Batch and Flex are 50% of standard. | https://developers.openai.com/api/docs/pricing | Nov 2026 (search summary; page not opened) | reported_secondary |
| 12 | Gemini 4 Argon costs $2 in / $10 out per 1M tokens only until 30 Nov 2026, then $4 / $20 (cached $0.10 -> $0.20; batch 50%). It is paid-only. Gemini 3.8 Flash batch prices also double on 1 Jan 2027. | https://ai.google.dev/gemini-api/docs/pricing | Nov 2026 (search summary; page not opened) | reported_secondary |
| 13 | Jules free plan: 15 tasks per rolling 24 h and 3 concurrent; Pro 100 / 15; Ultra 300 / 60. Jules has scheduled tasks, a CLI and an API-key GitHub Action. Availability in Ukraine was not verified. | https://jules.google/docs/usage-limits/ (search summary) ; https://github.com/google-labs-code/jules-action (opened) | Nov 2026 | reported_secondary |
| 14 | Interop standards are real and converging: MCP spec 2026-07-28 (stateless, removes sessions and the initialize handshake, deprecates HTTP+SSE and Dynamic Client Registration); A2A v1.0.0 (12 Mar 2026) under the Linux Foundation; Agent Skills and AGENTS.md each above 25k GitHub stars. | https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx ; https://github.com/a2aproject/A2A/releases | 28 Jul 2026 ; 12 Mar 2026 | verified_primary |
| 15 | None of these stacks addresses FactoryOS's actual bottleneck (no revenue, no paying customer); under "zero additional spend" the only officially supported unattended lanes are Codex CLI on an existing ChatGPT plan and Jules on its free plan. | Synthesis of rows 1-13 | 17 Nov 2026 | inference |

---

## 1. OpenAI stack

### 1.1 Agents SDK

**Takeaway.** A capable, open-source, self-hostable orchestration library, but still 0.x with monthly breaking changes, and it needs paid model tokens - it does not unlock a ChatGPT subscription.

**Cited findings**
- Python package `openai-agents` 0.24.0, released 15 Oct 2026; Python 3.10-3.14; MIT licence; 30.7k GitHub stars. [O] https://pypi.org/project/openai-agents/ ; https://github.com/openai/openai-agents-python
- Feature set per README: agents, handoffs and agents-as-tools, input/output guardrails, human-in-the-loop, sessions (automatic history), built-in tracing, function / MCP / hosted tools, sandbox agents (long tasks in a container), realtime and voice agents. [O] https://github.com/openai/openai-agents-python
- Provider-agnostic: Responses and Chat Completions APIs plus "100+ other LLMs" through optional LiteLLM / any-llm. [O] https://github.com/openai/openai-agents-python
- Optional extras show the integration surface: `redis`, `sqlalchemy`, `mongodb`, `dapr`, `temporal`, `docker`, `e2b`, `modal`, `cloudflare`, `daytona`, `vercel`, `runloop`, `blaxel`, `s3`, `encrypt`, `realtime`, `voice`, `viz`. [O] https://pypi.org/project/openai-agents/
- Release cadence and churn (all 2026): 0.22.0 on 19 Aug (breaking), 0.23.0 on 2 Oct (strict tools, approval restoration, encrypted history), 0.24.0 on 15 Oct. [O] https://github.com/openai/openai-agents-python/releases
- Pre-release line `0.24.0-alpha.6/7/8` (3, 8, 16 Nov 2026; GitHub-only wheels, not PyPI) rewrites the API: `Runner` aliases removed in favour of `Agent.run()`, approval modes renamed (`auto` -> `native`, `approve` -> `preapproved`), new `SessionStore` / `SQLiteSessionStore`, `RunBudget` (caps on requests, tokens or cost), `before_complete` hook, native OpenTelemetry export, `NetworkPolicy` for commands, read-only workspaces, MCP resources/prompts/elicitation. [O] https://github.com/openai/openai-agents-python/releases
- April 2026: OpenAI added native sandbox execution and a redesigned harness (Python first; providers Blaxel, Cloudflare, Daytona, E2B, Modal, Runloop, Vercel). [3P, not opened] https://techcrunch.com/2026/04/15/openai-updates-its-agents-sdk-to-help-enterprises-build-safer-more-capable-agents/
- TypeScript package `@openai/agents` reported at 0.20.0 (8 Oct 2026). [3P, not opened] https://www.developersdigest.tech/blog/openai-agents-sdk-whats-new-2026

**Inferences**
- Lock-in is low at library level (MIT, any model), moderate in practice: hosted tools, default tracing and sandbox providers pull toward OpenAI and paid third parties.
- For FactoryOS the SDK overlaps with what exists: Relay (handoffs, claims, run_id fencing), DBOS (durable steps), approval gates (guardrails / HITL). The genuinely new pieces would be tracing and `RunBudget`-style cost caps.

**Gaps**
- Where traces are stored and whether tracing is free could not be re-checked (docs host blocked).

### 1.2 AgentKit, Agent Builder, ChatKit

**Takeaway.** Not verifiable in this session beyond the fact that ChatKit is an Apache-2.0 UI kit whose backend calls OpenAI session endpoints. Treat as a hosted, API-billed product line.

**Cited findings**
- ChatKit (`openai/chatkit-js`): "batteries-included framework" for chat UIs (streaming, widgets, attachments, threads); Apache-2.0; quickstart has the server call `openai.chatkit.sessions.create`, i.e. an OpenAI-hosted session. [O] https://github.com/openai/chatkit-js
- Official docs now describe a "Plugins" experience in ChatGPT (packaging MCP servers, apps) under `developers.openai.com/plugins/...`. [S] https://developers.openai.com/plugins/quickstart

**Gaps**
- Current status, pricing and limits of Agent Builder / AgentKit in November 2026: no source reached. [T] AgentKit was announced 6 Oct 2025 (Agent Builder beta, ChatKit, connector registry, evals), billed through normal API tokens.

### 1.3 Responses API hosted tools

**Gaps (nothing verified).** Prices of web search, file search, code interpreter / containers and computer use as of November 2026 could not be read. [T, 2025 price list, stale] web search about $10 per 1,000 calls plus tokens; file search $2.50 per 1,000 calls plus $0.10/GB/day storage; code interpreter $0.03 per container session. Any use is paid API spend and therefore outside the zero-spend policy.

### 1.4 Codex (CLI, SDK, cloud, Action)

**Takeaway.** Codex is the one officially supported way to turn an existing ChatGPT subscription into a coding worker. It is capped by five-hour and weekly limits, and its CI Action wants a paid API key.

**Cited findings**
- Codex CLI: "a coding agent from OpenAI that runs locally"; Apache-2.0; recommended auth is "Sign in with ChatGPT" for Plus, Pro, Business, Edu or Enterprise; API key is the alternative. [O] https://github.com/openai/codex
- Latest stable 0.169.0 on 13 Nov 2026; twelve `0.171.0-alpha` builds between 14 and 17 Nov 2026. [O] https://github.com/openai/codex/releases
- 0.169.0 notes confirm: `codex exec` (non-interactive) and `codex review`, with project config and MCP servers disabled in untrusted directories unless `--trust`; app-server; MCP; plugin marketplace; skills; subagents; an opt-in Cloud connection from the terminal; plan-approval handoff. [O] https://github.com/openai/codex/releases
- Non-interactive docs live at `developers.openai.com/codex/noninteractive` (repo file is a redirect stub). [O] https://github.com/openai/codex/blob/main/docs/exec.md
- Codex SDK (TypeScript): "wraps the `codex` CLI ... spawns the CLI and exchanges JSONL events over stdin/stdout"; threads persist in `~/.codex/sessions` and resume with `resumeThread()`; JSON-schema structured output; injects `CODEX_API_KEY`. [O] https://github.com/openai/codex/blob/main/sdk/typescript/README.md
- `openai/codex-action`: users "must provide an API key for their chosen provider"; safety strategies `drop-sudo` (default), `unprivileged-user`, `read-only`, `unsafe`. No ChatGPT-plan login is described. [O] https://github.com/openai/codex-action
- Plans: Codex is included in ChatGPT Free, Go, Plus, Pro, Business and Enterprise. [S] https://chatgpt.com/codex/pricing/
- Plus estimates per five hours: 15-160 GPT-6.1 Sol messages, 5-45 GPT-6 Astra, 350-3,000 GPT-6 Luna. [S] https://chatgpt.com/codex/pricing/
- Pro starts at $100/month with $200 and $500 tiers and currently no five-hour limit; estimates "are not fixed message limits"; cloud tasks may consume more allowance than local messages; Plus and Pro can buy extra credits; a typical GPT-6.1 Sol task uses 2-15 credits. [S] https://developers.openai.com/codex/pricing
- Third-party reports disagree on whether the five-hour window was suspended in July 2026 and restored for Plus on 25 Aug 2026; weekly limits are consistently reported. [3P] https://munderdiffl.in/blog/codex-pricing/ ; https://www.morphllm.com/codex-pricing

**Inferences**
- `codex exec` on the existing EC2 host with a stored ChatGPT sign-in is technically the same pattern as the current Claude worker. Whether OpenAI's terms permit unattended, scripted use of a consumer plan was **not** verified (terms page blocked); the CI Action requiring an API key suggests OpenAI steers automation to paid API.
- At 15-160 Sol messages per five hours a Plus lane is a small part-time worker, not a 24/7 one.

**Gaps**
- Codex "automations" (scheduled runs): no source reached. [T] The Codex desktop app (Feb 2026) had scheduled Automations running in the background.

### 1.5 Can a ChatGPT subscription be an unattended worker?

**Takeaway.** Not through any official API or connector. ChatGPT is an MCP *client* a human drives; it is not addressable as a worker. Scheduled, unattended tool-writing on a consumer plan is unverified and probably blocked by confirmations.

**Cited findings**
- Custom MCP servers can be added directly from Plugins, without Developer Mode, after acknowledging a risk warning per server. [S] https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- ChatGPT supports read and write tools; for write actions it "may ask for confirmation"; some risky actions are blocked outright. [S] https://developers.openai.com/api/docs/guides/custom-mcp-server
- The search summary states that custom MCP connections with full MCP support are available to Business and Enterprise/Edu on the web, with admin controls per action. [S] https://help.openai.com/en/articles/11391654-chatgpt-business-release-notes
- The only scheduling tied to custom MCP found: Enterprise workspaces can schedule recurring runs for workspace agents. [S] https://help.openai.com/en/articles/10128477-chatgpt-enterprise-and-edu-release-notes
- FactoryOS already exposes its own `/mcp` server that ChatGPT uses (`list_build_tasks`, `get_design_context`, `submit_design_review`), and needs a `?key=` URL credential because "the ChatGPT connector cannot send headers". [O] local `ROADMAP.md` (T-604, T-624), `DECISIONS.md` (T-625)
- FactoryOS's own coordination protocol says the live two-way channel and the hourly ChatGPT check are "not verified" and must show `integration_blocked` if tools are unavailable. [O] local `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`

**Inferences**
- The hourly "ChatGPT checks its inbox, claims and writes a result" loop depends on two unverified conditions: a scheduled ChatGPT run can call a custom connector, and it can perform write actions without a human confirming. FactoryOS is right to treat it as blocked until a live round trip is observed.
- The supported substitute is Codex (`codex exec` or Codex cloud), which uses the same subscription.

**Gaps**
- ChatGPT scheduled tasks and agent-mode limits for Plus in November 2026: not reached. [T] Tasks launched January 2025 with about 10 active tasks; ChatGPT agent launched July 2025 with about 40 agent messages/month on Plus.

---

## 2. Google stack

### 2.1 Agent Development Kit (ADK)

**Takeaway.** The most complete open-source agent framework of the two vendors (graph runtime, evaluation, A2A, self-hostable, model-agnostic), but it moves fast and would mean re-platforming a system that already works.

**Cited findings**
- `google-adk` 2.14.1, released 12 Nov 2026; Python 3.11+; Apache-2.0; 22.3k stars; "release cadence is roughly bi-weekly". [O] https://pypi.org/project/google-adk/ ; https://github.com/google/adk-python
- Languages: Python, plus sibling Java, Kotlin, Go and TypeScript implementations. [O] https://github.com/google/adk-python
- ADK 2.0 GA dates: Python 19 May 2026, Go 30 June, TypeScript 21 Aug; 2.0 replaced the hierarchical executor with a graph-based Workflow Runtime and broke API, event model and session schema versus 1.x. [S] https://adk.dev/2.0/
- Features: Workflow Runtime (routing, loops, retries, state, human-in-the-loop, nested workflows), Task API for agent-to-agent delegation, multi-agent hierarchies, tools from functions / OpenAPI / MCP, no-code Agent Config, tool confirmation, `adk eval`, dev UI. [O] https://pypi.org/project/google-adk/
- Deployment: `adk deploy docker`, Cloud Run, or "Agent Runtime on Gemini Enterprise Agent Platform (formerly Vertex AI Agent Engine)". [O] https://github.com/google/adk-python
- Recent releases (2026): 2.9.0 on 10 Sep (FallbackModel failover, YAML graph workflows, failed nodes re-run on resume); 2.10.0 on 25 Sep (experimental skill lifecycle, OpenAI reasoning models); 2.11.0 on 2 Oct (SQLite memory service, tool confirmation in workflows); 2.12.0 on 13 Oct (`require_confirmation` on workflow nodes); 2.13.0 on 23 Oct (MongoDB session and memory); 2.14.0 on 7 Nov (A2A, execution environments and evaluation declared stable; multi-run evals; breaking changes). [O] https://github.com/google/adk-python/releases
- The 1.x line still gets backports (1.39.1 on 27 Aug 2026). [O] https://github.com/google/adk-python/releases

**Inferences**
- ADK runs on FactoryOS's existing servers at no licence cost, and can call Gemini free-tier models; so cost is engineering time only.
- Six minor releases in ten weeks, with breaking changes inside minors, is a maintenance tax for a solo founder.

### 2.2 Agent Engine / Gemini Enterprise Agent Platform

**Takeaway.** Managed, paid Google Cloud runtime; it duplicates Render + EC2 and breaks the zero-spend rule.

**Cited findings**
- Vertex AI Agent Engine has been renamed "Agent Runtime" within "Gemini Enterprise Agent Platform". [O] https://github.com/google/adk-python
- Google's pricing page is now titled "Agent Platform Pricing". [O, title only - body too large to read] https://cloud.google.com/vertex-ai/generative-ai/pricing

**Gaps**
- Current vCPU-hour / GiB-hour, session and memory-bank prices and any free tier: not readable. [T, 2025, stale] runtime was about $0.0864 per vCPU-hour and $0.009 per GiB-hour.

### 2.3 Gemini CLI and Antigravity CLI

**Takeaway.** The "free Gemini coding lane" premise is obsolete. Gemini CLI is now an enterprise / API-key tool; the free individual path is Antigravity CLI with undisclosed weekly quotas.

**Cited findings**
- 18 Mar 2026 announcement: from 25 March "Gemini Pro models will only be accessible via paid subscriptions"; free tier limited to Flash; traffic prioritised by licence type; detection of policy-violating use such as "using Gemini CLI OAuth with third-party software". [O] https://github.com/google-gemini/gemini-cli/discussions/22970
- 19 May 2026 announcement: Gemini CLI will stop serving Google AI Pro, Ultra and free-tier users on 18 June 2026; unchanged for Code Assist Standard/Enterprise and Google Cloud; "remains accessible with paid Gemini and Gemini Enterprise Agent Platform API keys"; the project stays Apache-2.0. [O] https://github.com/google-gemini/gemini-cli/discussions/27274
- 18 June 2026 announcement: stopped; "Enterprise users with Gemini Code Assist licenses and API key authentication remain completely unaffected". [O] https://github.com/google-gemini/gemini-cli/discussions/28017
- Current README: "Designed for Gemini Code Assist Standard / Enterprise licenses"; not tuned for Gemini 4+ models; auth = Google sign-in for paid Code Assist licences, Gemini API key (usage-based billing), or Vertex AI; headless `gemini -p` with `--output-format json` / `stream-json`; MCP via `~/.gemini/settings.json`; weekly stable releases. [O] https://github.com/google-gemini/gemini-cli
- The CLI quota page still lists 250 requests/day on an unpaid Gemini API key, Flash models only, and notes that Antigravity CLI replaced Gemini CLI for unpaid and Google One users. [S] https://geminicli.com/docs/resources/quota-and-pricing/
- `run-gemini-cli` GitHub Action authenticates with `GEMINI_API_KEY`, Vertex AI, Code Assist or Workload Identity Federation. [O] https://github.com/google-github-actions/run-gemini-cli
- Antigravity CLI: terminal agent sharing an engine with the Antigravity 2.0 desktop app; public repo, no licence stated; changelog up to 1.5.10. [O] https://github.com/google-antigravity/antigravity-cli
- Antigravity CLI changelog: headless `-p` runs with `--print-timeout` (exit code 3 on timeout), `--output-format json` / `stream-json` with `finished_reason`, `--json-schema`; `GEMINI_API_KEY` connections including Gemini 4 models (1.5.8); turns stop immediately on weekly-quota, spend-cap and prepaid-balance errors (1.5.10); models Gemini 4 Hydrogen, Gemini 4 Carbon, Gemini 3.8 Flash; non-Gemini models behind a gateway; skills, MCP, plugins. [O] https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md
- Antigravity plans: Free at $0/month, or Google AI Plus / Pro / Ultra for higher limits and optional credit overages; no request numbers published on the overview page. [S] https://antigravity.google/docs/overview/
- Anecdotal (GitHub users, May-June 2026): weekly quota exhausted by one small task; a roughly $20/month account hit "Individual quota reached" with a reset of about 167 hours. No maintainer gave official numbers. [O] https://github.com/google-antigravity/antigravity-cli/issues/37

**Inferences**
- A free-tier AI Studio key in Gemini CLI is the ambiguous case: Google's May post says "paid" keys, the June post says "API key authentication", the quota page still shows a free row. Only a live probe (T-607-P) settles it.
- A lane that can be exhausted for a week by one task cannot be scheduled against.

### 2.4 Jules

**Takeaway.** The officially supported asynchronous Gemini coding agent, with a free plan large enough for a pilot and no infrastructure to run.

**Cited findings**
- Limits: free 15 tasks per rolling 24 hours, 3 concurrent; Pro 100 / 15; Ultra 300 / 60. [S] https://jules.google/docs/usage-limits/
- A changelog entry mentions 60 tasks/day and 5 concurrent, undated and without a tier - conflicting. [S] https://jules.google/docs/changelog/
- Docs exist for Scheduled Tasks, Suggested Tasks, a CLI and "Continuous AI". [S] https://jules.google/docs/scheduled-tasks/
- `jules-action` (MIT, 269 stars): triggers Jules from issues, PRs, cron schedules or manual dispatch with a `JULES_API_KEY`; Jules works in a cloud VM and opens PRs; README says "powered by Gemini 3 Pro" and advises an allowlist for issue-triggered runs. [O] https://github.com/google-labs-code/jules-action
- FactoryOS already has an open owner task to connect Jules on the free tier (T-606). [O] local `ROADMAP.md`

**Gaps**
- Country availability including Ukraine: no source reached. [T, 2025] Jules was described as available wherever Gemini models are available.

### 2.5 Gemini API free tier, paid prices, media models

**Cited findings**
- Usage tiers: Free (active project only), Tier 1 (linked billing), higher tiers by cumulative spend; actual limits are shown per project in AI Studio. [S] https://ai.google.dev/gemini-api/docs/rate-limits
- Free-tier numbers differ by source: 5-15 requests/minute and up to 1,000 requests/day; Pro models reported removed from the free tier on 1 April 2026; limits apply per project, not per key; free-tier prompts may be used to improve Google products. [3P] https://dev.to/hassann/gemini-api-free-tier-in-2026-limits-models-and-when-you-get-billed-4081 ; https://www.aifreeapi.com/en/posts/gemini-api-free-tier-complete-guide
- FactoryOS's own observation: "5 RPM free quota" on its AI Studio key, shared across MyCast and the issue loop. [O] local `docs/handoff/GEMINI_EC2_WORKER.md`
- Grounding with Google Search: 5,000 free prompts/month on Gemini 3.x, then $14 per 1,000; not available on the free tier for Gemini 3 and newer. [3P] https://www.cloudzero.com/blog/gemini-pricing/

**Gaps**
- Veo, image models, Gemini TTS and Lyria prices in November 2026: not readable. [T, late 2025 - early 2026, stale] Veo 3.1 about $0.40/s standard and $0.15/s fast; Nano Banana about $0.039/image; Flash TTS about $0.50 in / $10 out per 1M tokens.

---

## 3. API price list, November 2026 (USD per 1M tokens)

All rows are **[S]/[3P]: read through search summaries, official pages not opened.** Verify before use.

| Model | Input | Cached input | Output | Discounts and notes |
|---|---|---|---|---|
| OpenAI GPT-6 Astra (flagship) | 10.00 | 1.00 (cache write 12.50) | 50.00 | Batch 5.00 / 0.50 / 25.00. Fast mode 20 / 2 / 100; Ultrafast 60 / 300 |
| OpenAI GPT-6.2 Astra | 8.00 | 0.40 | 40.00 | Newer listing on the model page |
| OpenAI GPT-6.1 Sol / GPT-6.2 Sol | 2.00 | 0.20 | 10.00 | Batch 1.00 / 5.00. Above 272k input tokens: 4.00 in / 15.00 out [3P] |
| OpenAI GPT-6.1 Terra | 1.00 | about 0.05 | 5.00 | Flex 0.50 / 0.025 / 2.50 |
| OpenAI GPT-6 Luna (cheap) | 0.10 | 0.01 | 0.50 | Flex 0.05 / 0.005 / 0.25; price since 22 Sep 2026 [3P] |
| Google Gemini 4 Argon (flagship) | 2.00, then 4.00 from 1 Dec 2026 | 0.10, then 0.20 | 10.00, then 20.00 | Batch 1.00 / 0.05 / 5.00, doubling 1 Dec. Implicit caching only (95% off, prompts of 4,096+ tokens). Paid tier only |
| Google Gemini 3.8 Flash | batch 0.375, then 0.75 from 1 Jan 2027 | 0.0375 + $0.50 per 1M tokens per hour storage | batch 1.875, then 3.75 | Standard rate inferred as 2x batch (0.75 / 3.75 now) |
| Google Gemini 3.5 Flash-Lite | 0.15 | 0.02 + $1.00 per 1M per hour | 1.25 | Table headers were ambiguous in the summary |
| Google Gemini 3.1 Flash-Lite | 0.125 (audio 0.25) | 0.0125 + $0.50 per 1M per hour | 0.75 | Possibly batch rates |

Sources: https://developers.openai.com/api/docs/pricing ; https://openai.com/api-fast-mode/ ; https://help.openai.com/en/articles/20001415-chatgpt-rate-card-enterprise-token-based-pricing ; https://ai.google.dev/gemini-api/docs/pricing ; third-party cross-checks https://www.cloudzero.com/blog/openai-pricing/ and https://www.nops.io/blog/openai-api-pricing/.

Illustrative costs (my arithmetic from the table; inference):
- One call of 10k input + 2k output tokens: Luna about $0.002; Terra $0.02; Sol $0.04; Argon $0.04 now and $0.08 from 1 Dec; Astra $0.20.
- One coding-agent task of 2M input tokens (90% cached) + 50k output: Sol about $1.26; Astra about $6.30. Twenty such tasks a day on Sol is roughly $750/month - the scale of what a flat subscription absorbs.

---

## 4. Interoperability standards

**Takeaway.** MCP is the one that matters operationally for FactoryOS today; Agent Skills and AGENTS.md are cheap, portable conventions; A2A is mature on paper but FactoryOS has no counterpart to talk to.

**Cited findings**
- MCP spec releases: 2025-06-18, 2025-11-25, and 2026-07-28 (current stable). [O] https://github.com/modelcontextprotocol/modelcontextprotocol/releases
- MCP 2026-07-28 changes: protocol sessions and `Mcp-Session-Id` removed; `initialize` handshake removed (version and capabilities travel in `_meta`); new required `server/discover`; POSTs need `Mcp-Method` / `Mcp-Name` headers; SSE resumability removed; tasks moved to an extension; server-initiated requests replaced by `input_required` results; Roots, Sampling, Logging and the HTTP+SSE transport deprecated; Dynamic Client Registration deprecated in favour of Client ID Metadata Documents. [O] https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx
- A2A: v1.0.0 on 12 Mar 2026, v1.0.1 on 28 May 2026; Linux Foundation project contributed by Google, described as part of the Agentic AI Foundation; SDKs for Python, Go, JS/TS, Java, .NET, Rust; 26.6k stars. [O] https://github.com/a2aproject/A2A ; https://github.com/a2aproject/A2A/releases
- A2A v1.0.0 added `tasks/list`, removed OAuth implicit and password flows, added device-code and PKCE. [O] https://github.com/a2aproject/A2A/releases
- Agent Skills: open format originated by Anthropic; a folder with `SKILL.md` (name, description, instructions) plus optional scripts/references/assets; 27.4k stars. [O] https://github.com/agentskills/agentskills
- Skills appear in all three ecosystems: Codex release notes (skills, plugin marketplace), Antigravity CLI changelog (skills, imported Claude Code commands), ADK 2.10.0 (experimental skill lifecycle), Agents SDK alpha ("supplied skills"). [O] https://github.com/openai/codex/releases ; https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md ; https://github.com/google/adk-python/releases
- AGENTS.md: "a simple, open format for guiding coding agents"; 25.5k stars; repo carries a Technical Charter. [O] https://github.com/agentsmd/agents.md

**Inferences**
- FactoryOS's `/mcp` server should be tested against 2026-07-28 clients: the removal of sessions and the initialize handshake is a server-side behaviour change, and `?key=` URL credentials sit awkwardly beside the tightened OAuth guidance.
- One `AGENTS.md` plus a shared `skills/` folder is the cheapest way to keep Claude, Codex, Jules and Antigravity behaving alike.

---

## Counter-evidence and caveats

- **Against "reject the frameworks".** Both SDKs are free, self-hostable and model-agnostic; ADK's `adk eval` and the Agents SDK's `RunBudget` and tracing cover things FactoryOS has built by hand or lacks. If FactoryOS were starting today, ADK would be a defensible base.
- **Against "Codex on a subscription is safe".** I could not open OpenAI's terms. The Action requiring an API key, and Google's explicit crackdown on OAuth reuse (row 3), show vendors tightening subscription-as-automation. A plan-limit or policy change can remove a lane overnight - exactly what happened to Gemini CLI on 18 June 2026.
- **Against "free tiers are a stable foundation".** In 2026 Google removed Pro from the free CLI tier (March), ended free CLI access (June), and scheduled price doublings for Gemini 4 Argon (1 Dec 2026) and Gemini 3.8 Flash (1 Jan 2027). Prices are not only falling.
- **Against my Gemini CLI conclusion.** The quota page still lists a free API-key row (250 requests/day, Flash). The free-key path may work; it was not tested here.
- **Source quality.** Every price and plan limit in sections 1.4, 2.4, 2.5 and 3 is from search summaries. Summaries mixed model generations (GPT-5.6 and GPT-6 names on the same Codex page) and flagged internal conflicts (Sol cached rate $0.10 vs $0.20; Jules 15 vs 60 tasks/day).
- **Version oddity.** The Agents SDK alphas are numbered `0.24.0-alpha.x` but dated after 0.24.0 stable; I report them as shown.

## Implications for FactoryOS

1. **The lanes are not the constraint.** FactoryOS has no revenue and no paying customer. A second or third coding lane raises output of code and content (at best views), not leads, revenue or net profit. Every item below is cost and attention; none is income.
2. **Stop investing in the Gemini CLI worker (T-607).** Its design premise - personal Google login on the free tier - was withdrawn by Google on 18 June 2026. Verdict: **reject** as a strategic lane. Run the existing probe once with the free-tier key; if it fails, close the task rather than rebuilding on Antigravity.
3. **Jules: pilot, small.** It is Google's supported async agent, costs nothing to host, and 15 tasks/day exceeds what one founder can review. Precondition: the owner confirms it works from a Ukrainian account. Keep Claude as reviewer and keep the human gate.
4. **Codex CLI on the existing ChatGPT plan: pilot only if a second engineering lane is truly needed.** It is the legitimate replacement for the "hourly ChatGPT check" idea. Use `codex exec` on the existing EC2 with the same claim / run_id fencing as the Claude worker. Read OpenAI's terms on automated use first. Do not buy Pro.
5. **ChatGPT-as-worker through the MCP connector: keep as `integration_blocked`.** Keep ChatGPT as an interactive planner/reviewer that a human drives; do not build scheduling around it.
6. **Agents SDK and ADK: reference, not adoption.** Borrow three ideas into the current code: per-run budget caps, an evaluation set run in CI, and OpenTelemetry-style traces. Re-platforming onto either would cost weeks and buy no customer.
7. **AgentKit / Agent Builder, hosted tools, Agent Engine: reject for now.** All are paid, hosted and duplicate Render + EC2 + Relay + DBOS.
8. **Gemini API free tier: keep for prototypes, not for a paid product.** Price MyCast on paid-tier rates (and on the post-December Argon price), because a product that only works inside a 5 RPM free quota cannot serve paying customers, and free-tier data may be used by Google.
9. **Standards: adopt the cheap ones.** Maintain one `AGENTS.md` and portable skills; schedule a compatibility check of `/mcp` against MCP 2026-07-28; ignore A2A until there is an external agent to talk to.

| Stack | Problem it would solve | FactoryOS already has | Incremental cost | Verdict |
|---|---|---|---|---|
| OpenAI Agents SDK | Orchestration, guardrails, tracing | Relay, DBOS, approval gates | $0 licence + paid tokens + migration weeks | Reference |
| AgentKit / Agent Builder / ChatKit | Visual workflows, chat UI | Agent Office UI | Paid API; hosted lock-in | Reject (ChatKit: reference) |
| Codex CLI / SDK | Second coding lane on ChatGPT plan | Claude worker on EC2 | $0 if Plus already paid; plan-limited | Pilot (conditional) |
| ChatGPT + MCP connector | Planner/reviewer with FactoryOS tools | `/mcp` server, lane tokens | $0 | Keep interactive; unattended = blocked |
| Google ADK | Graph workflows, eval, A2A | Relay, DBOS | $0 licence + migration weeks | Reference |
| Agent Engine / Agent Platform | Managed agent hosting | Render + EC2 | Paid GCP | Reject |
| Gemini CLI | Free Gemini coding lane | T-607 worker code | Free path withdrawn | Reject |
| Antigravity CLI | Replacement free lane | - | $0, opaque weekly quota | Reference (watch) |
| Jules | Async Gemini coding agent | T-606 planned | $0 on free plan | Pilot |
| Gemini API free tier | TTS / LLM for prototypes | MyCast voice | $0 within quota | Adopt for prototypes only |

## Sources

**Opened and read**
- https://github.com/google-gemini/gemini-cli
- https://github.com/google-gemini/gemini-cli/discussions/22970
- https://github.com/google-gemini/gemini-cli/discussions/27274
- https://github.com/google-gemini/gemini-cli/discussions/28017
- https://github.com/google-antigravity/antigravity-cli
- https://github.com/google-antigravity/antigravity-cli/blob/main/CHANGELOG.md
- https://github.com/google-antigravity/antigravity-cli/issues/37
- https://github.com/google-github-actions/run-gemini-cli
- https://github.com/google-labs-code/jules-action
- https://github.com/google/adk-python
- https://github.com/google/adk-python/releases
- https://pypi.org/project/google-adk/
- https://github.com/openai/openai-agents-python
- https://github.com/openai/openai-agents-python/releases
- https://pypi.org/project/openai-agents/
- https://github.com/openai/codex
- https://github.com/openai/codex/releases
- https://github.com/openai/codex/blob/main/docs/exec.md
- https://github.com/openai/codex/blob/main/sdk/typescript/README.md
- https://github.com/openai/codex-action
- https://github.com/openai/chatkit-js
- https://github.com/a2aproject/A2A
- https://github.com/a2aproject/A2A/releases
- https://github.com/modelcontextprotocol/modelcontextprotocol/releases
- https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/changelog.mdx
- https://github.com/agentsmd/agents.md
- https://github.com/agentskills/agentskills
- https://cloud.google.com/vertex-ai/generative-ai/pricing (title only; body not readable)
- Local repository: `docs/handoff/GEMINI_EC2_WORKER.md`, `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, `ROADMAP.md`, `DECISIONS.md`

**Not opened - read only through search summaries (network policy blocked the hosts)**
- https://developers.openai.com/api/docs/pricing
- https://developers.openai.com/codex/pricing ; https://chatgpt.com/codex/pricing/
- https://help.openai.com/en/articles/12584461-developer-mode-and-mcp-apps-in-chatgpt
- https://developers.openai.com/api/docs/guides/custom-mcp-server
- https://ai.google.dev/gemini-api/docs/pricing ; https://ai.google.dev/gemini-api/docs/rate-limits
- https://geminicli.com/docs/resources/quota-and-pricing/
- https://jules.google/docs/usage-limits/ ; https://jules.google/docs/changelog/
- https://antigravity.google/docs/overview/
- https://adk.dev/2.0/
- Third-party blogs named inline (cloudzero.com, nops.io, munderdiffl.in, morphllm.com, dev.to, aifreeapi.com, techcrunch.com, developersdigest.tech)
