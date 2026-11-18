# TinyFish and the browser-automation agent stack (state as of 2026-11-17/18)

Scope: the most reliable and cheapest way for FactoryOS to act on websites that have no official API, and what TinyFish
specifically adds. Research-only; nothing in the repository was changed.

Method and labels. WebFetch worked only for github.com and pypi.org, so those pages were opened in full. Every other
vendor page (tinyfish.ai, browser-use.com, browserbase.com, anthropic.com, openai.com, ai.google.dev, aws.amazon.com,
steel.dev, skyvern.com, cloudflare.com) was read only through a search extract restricted to the official domain; these are
marked "search extract of <URL>". Press and leaderboard aggregators are marked as such. Confidence values:
verified_primary = page opened, or an official-domain extract with an exact figure; reported_secondary = press, aggregator
or law-firm summary; vendor_claim = a vendor's statement about itself; inference = my reasoning.

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | TinyFish today is a hosted "web infrastructure for AI agents" with four APIs: Search and Fetch are **free** (search extract: 30 searches/min and 500/hour; Fetch 150 URLs/min and 1,000/day; no card), Agent costs **$0.016 per step** (model, stealth browser, anti-bot and proxy included, 2 concurrent runs), and Browser costs **$0.002/min** (5 concurrent). Billing is a prepaid wallet with no subscription, an $8 starting balance and a $10 minimum top-up. Older Starter ($15) and Pro ($150) plans were discontinued. | search extract of https://www.tinyfish.ai/blog/search-and-fetch-are-now-free-for-every-agent-everywhere and https://www.tinyfish.ai/blog/tinyfish-vs-browserbase | 2026 (pages undated in extract) | verified_primary (official domain, figures conflict slightly across TinyFish pages) |
| 2 | TinyFish cannot be self-hosted except through custom Enterprise on-prem or VPC deals. Its open parts are MIT SDKs (AgentQL with 1.5k stars, cookbook with 2.3k, MCP servers), a stealth fork of Playwright, and `bigset-oss` (AGPL-3.0). | https://github.com/tinyfish-io ; search extract of https://tinyfish.ai/blog/tinyfish-vs-browser-use-cloud-agents-vs-local-agents and https://www.agentql.com/ | repos updated 2026-11-13..17 | verified_primary |
| 3 | TinyFish raised a $47M Series A led by ICONIQ in August 2025. Press names Google, DoorDash and ClassPass as customers. Scale claims ("hundreds of thousands of agents") are unverified, and reported headcount ranges from 25 to 70. | https://www.businesswire.com/news/home/20250820555825/en/TinyFish-launches-with-47-million-to-define-the-era-of-Enterprise-Web-Agents ; https://siliconangle.com/2025/08/20/tinyfish-raises-47m-expand-deployment-enterprise-web-agents/ | 2025-08-20 | reported_secondary / vendor_claim |
| 4 | TinyFish claims 81.9% on Online-Mind2Web "hard" tasks against Operator 43.2%, Claude Computer Use 32.4% and Browser Use 8.1%, scored by its own judge. The Steel aggregator lists it at 90.0% on Online-Mind2Web. Neither figure is comparable with human-evaluated results. | search extract of https://www.tinyfish.ai/blog/mind2web ; search extract of https://leaderboard.steel.dev/leaderboards/online-mind2web | 2026 (undated) | vendor_claim |
| 5 | Self-reported WebVoyager scores (about 85-90%) overstate real-web ability. On Online-Mind2Web (300 tasks, 136 live sites, human evaluation), most 2025 agents did not beat the 2024 SeeAct baseline; Claude CU 3.7 and Operator were the exceptions. LLM judges agree with humans only about 79-87% of the time, and tasks were revised up to 2026-05-15, so scores from different dates are not comparable. | https://github.com/OSU-NLP-Group/Online-Mind2Web ; search extract of https://arxiv.org/abs/2504.01382 | COLM 2025; repo updated 2026-05 | verified_primary |
| 6 | browser-use (open source) is MIT-licensed with about 121k stars; v1.0.6 shipped 2026-11-16, after 6 releases in 7 days. It runs a local Chromium with any OpenAI, Anthropic or Google model, or with Ollama. Stealth and CAPTCHA solving exist only in the paid cloud. | https://github.com/browser-use/browser-use ; https://pypi.org/project/browser-use/ | 1.0.6, 2026-11-16 | verified_primary |
| 7 | Browser Use Cloud charges $0.06 per browser-hour and $5/GB for residential proxy traffic, in prepaid credits with no subscription. The vendor quotes a median task at $0.006 on bu-ultrafast, but $0.70-$1.64 per *successful* task with Claude Opus 4.7 (V2-V4 agent, 1-5 minutes). | search extract of https://docs.browser-use.com/cloud/pricing and https://browser-use.com/posts/bu-ultrafast-is-live | 2026 | verified_primary (vendor-measured costs = vendor_claim) |
| 8 | Playwright is free and Apache-2.0; v1.65.2 shipped 2026-11-14. Playwright MCP (Apache-2.0, 39.8k stars) drives the browser from accessibility snapshots, not pixels, and says it is "**not** a security boundary". Microsoft now recommends `playwright-cli` plus skills for coding agents because it is "more token-efficient". | https://pypi.org/project/playwright/ ; https://github.com/microsoft/playwright-mcp ; https://github.com/microsoft/playwright-cli | 2026-11 | verified_primary |
| 9 | Claude in Chrome is included in the paid Claude plans (Pro, Max, Team and Enterprise; newer pages also list Ultra). It runs only in Google Chrome. Since the owner already pays for Claude Pro, it costs nothing extra, but it is interactive and needs the owner's browser, so it is not a server API. | search extract of https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome and https://claude.com/pricing | 2026-11 | verified_primary |
| 10 | Anthropic's own prompt-injection figures for browser use: 23.6% attack success without mitigations, 11.2% with them (Aug 2025 pilot); about 1% for Opus 4.5 against a Best-of-N attacker (late 2025); "<0.08%" for the current product configuration; 0.3% against Fable 5 (GA post). On Gray Swan, Opus 4.7 shows about 0.1% on a single attempt and **5-6% after 100 adaptive attempts**. | search extract of https://www.anthropic.com/research/prompt-injection-defenses , https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely , https://www.anthropic.com/engineering/how-we-contain-claude | 2025-08 to 2026 | vendor_claim |
| 11 | OpenAI's help center says ChatGPT agent is "no longer available" (replaced by "ChatGPT Work") and that Atlas has been deprecated. No computer-use tool line was found on the API pricing page. | search extract of https://help.openai.com/en/articles/11752874-chatgpt-agent and https://openai.com/index/introducing-chatgpt-atlas/ | 2026 | verified_primary (extract only; details of "ChatGPT Work" not verified) |
| 12 | Gemini computer use is billed as ordinary tokens and is not on the free tier. The 2.5 Pro Computer Use preview cost $1.25 per 1M input tokens and $10 per 1M output tokens. Amazon Nova Act became GA in Dec 2025 at **$4.75 per agent-hour**, us-east-1 only, with a free local API key that has daily limits. | search extract of https://ai.google.dev/gemini-api/docs/pricing ; https://aws.amazon.com/nova/pricing/ ; https://aws.amazon.com/blogs/aws/build-reliable-ai-agents-for-ui-workflow-automation-with-amazon-nova-act-now-generally-available/ | 2025-12 / 2026 | verified_primary |
| 13 | Prices of managed cloud browsers: Browserbase gives 1 free browser-hour with a 15-minute session cap, then $20/month for 100 h or $99/month for 500 h. Steel gives $30 of one-time credits (90 days), then $0.10/h. Hyperbrowser gives 5,000 free credits (1 credit = $0.001) with 1 concurrent session. None of these is a lasting free production tier. | search extract of https://docs.browserbase.com/account/billing/plans , https://docs.steel.dev/overview/pricinglimits , https://www.hyperbrowser.ai/pricing | 2026 | verified_primary |
| 14 | Amazon v. Perplexity (Comet): a district court granted a preliminary injunction in March 2026. The Ninth Circuit reversed it on 2026-08-04, holding that the *user*, not the agent developer, accesses the site; the holding is narrow. Rehearing was denied on 2026-09-10, an amended complaint followed on 2026-09-21, and the case is still active. | https://www.geekwire.com/2026/judge-blocks-perplexitys-ai-bot-from-shopping-on-amazon-in-early-test-of-agentic-commerce/ ; https://www.americanbar.org/groups/litigation/resources/newsletters/privacy-data-security/ninth-circuit-holds-human-user-not-developer-ai-agent-responsible-websites-accessed/ | 2026-03 to 2026-11 | reported_secondary |
| 15 | Cloudflare now classifies agent traffic cryptographically through Web Bot Auth "signed agents". The first cohort was ChatGPT agent, Goose, Browserbase and Anchor Browser. A self-run, unsigned headless Chromium on a datacenter IP is the traffic class most likely to be challenged. FactoryOS's own Surfer found that 5 search engines refuse its EC2 IP. | search extract of https://blog.cloudflare.com/signed-agents/ and https://developers.cloudflare.com/bots/concepts/bot/signed-agents/ ; repo `web_surfer.py` docstring (2026-11-15) | 2025-2026 | verified_primary + inference |

## Detailed findings

### 1. TinyFish: what it is today

**Takeaway.** TinyFish (formerly the AgentQL team) is a closed, hosted web-agent platform. For FactoryOS it offers one
thing that is new and free: **free Search and Fetch APIs**. The paid "Agent" product would only replace something
FactoryOS already does with Playwright. Its benchmark leadership is self-measured.

- **Product line.** TinyFish offers four endpoints: Search, Fetch, Agent and Browser. The Agent API is `POST
  agent.tinyfish.ai/v1/automation/run` (synchronous) or `/run-sse` (streaming). It takes `url` and `goal` and
  authenticates with `X-API-Key`. Optional fields: `browser_profile: "stealth"` and `proxy_config` with `country_code`
  for protected or geo-restricted sites; saved login state through "Browser Context Profiles" (`use_profile`,
  `profile_id`); and a CLI that streams NDJSON. (search extract of https://docs.tinyfish.ai/key-concepts/endpoints ,
  https://docs.tinyfish.ai/api-reference/automation/run-browser-automation-with-sse-streaming ,
  https://docs.tinyfish.ai/agent-api/browser-context-profiles , https://docs.tinyfish.ai/cli/commands)
- **TinyFish's own anti-bot guide.** It warns that "a COMPLETED status doesn't guarantee success", so the caller must
  inspect the result for blocked-page signs. (search extract of https://docs.tinyfish.ai/anti-bot-guide) This is the same
  "done overstates success" failure that FactoryOS measured in its own Surfer benchmark (see §8).
- **Pricing (official domain, via extract).**
  - Search and Fetch are free with no card. Limits: Search 30/min and 500/hour; Fetch 150 URLs/min and 1,000/day.
  - Agent: $0.016 per step, with model inference, stealth browser, anti-bot and proxy included; 2 concurrent runs on
    pay-as-you-go.
  - Browser: $0.002/min (equal to 1 credit per 4 minutes), 5 concurrent sessions, 60-minute session cap.
  - Billing: wallet, no subscription, $8 starting balance, $10 minimum top-up; Enterprise is custom.

  (search extract of https://www.tinyfish.ai/blog/search-and-fetch-are-now-free-for-every-agent-everywhere ,
  https://www.tinyfish.ai/blog/tinyfish-vs-browserbase , https://www.tinyfish.ai/blog/browserbase-pricing)

  Conflicts: one third-party listing gives free limits of 5 searches/min and 25 fetches/min, and TinyFish blogs mention
  500 free credits or "up to $13" instead of $8. The older Starter ($15/month, 1,650 credits) and Pro ($150/month) plans
  appear on stale pages, and a TinyFish blog says they were discontinued. (search extract of
  https://www.stork.ai/en/tinyfish , aggregator)
- **Self-hosting and lock-in.** TinyFish describes itself as "a managed service with partial open source components
  (AgentQL)". On-prem and VPC deployment come only with custom Enterprise contracts. (search extract of
  https://tinyfish.ai/blog/tinyfish-vs-browser-use-cloud-agents-vs-local-agents , https://www.agentql.com/)
  - Public repositories (opened):
    - `tinyfish-cookbook`: 2,332 stars, MIT.
    - `agentql`: 1,509 stars, MIT. It contains a query language, Playwright integrations, a REST API, Python/JS SDKs and a
      debugger.
    - `bigset-oss`: "self-hostable live datasets populated by TinyFish web agents", AGPL-3.0, 1,708 stars.
    - `agentql-mcp`, `tinyfish-mcp-server` (says Search and Fetch are free), and `tf-playwright-stealth` (a stealth fork).
  - All were updated 2026-11-13..17, so the projects are active. (https://github.com/tinyfish-io)
  - The agentql README does not say where queries execute or whether a key is required
    (https://github.com/tinyfish-io/agentql), and its PyPI page failed to load. **Unverified: whether AgentQL queries can
    run without the hosted service.**
  - Inference: the agent "brain", the stealth stack and the proxies are proprietary and hosted, so lock-in is high for
    Agent and Browser. For Search and Fetch lock-in is low, because those are interchangeable HTTP calls.
- **Maturity and customers.**
  - Funding: $47M Series A in August 2025, led by ICONIQ, with USVP, Mango Capital, MongoDB Ventures and others. The CEO
    cited a 3-4 year runway. (https://www.businesswire.com/news/home/20250820555825/en/TinyFish-launches-with-47-million-to-define-the-era-of-Enterprise-Web-Agents ;
    https://builtin.com/articles/tinyfish-launches-raises-47m-series-a-20250822 , press)
  - Customers: press and investors name Google (early pilot), DoorDash and ClassPass. (https://siliconangle.com/2025/08/20/tinyfish-raises-47m-expand-deployment-enterprise-web-agents/ ,
    press; https://www.digitalcommerce360.com/2025/08/21/tinyfish-47-million-funding-enterprise-web-agent-platform/)
  - No independent case study with numbers was found.
- **Benchmarks (vendor).**
  - TinyFish says it ran all 300 Online-Mind2Web tasks and published the runs: 81.9% on hard tasks vs Operator 43.2%,
    Claude Computer Use 32.4% and Browser Use 8.1%. The judge was its own, with about 85% stated agreement with humans.
    (search extract of https://www.tinyfish.ai/blog/mind2web ; also
    https://dev.to/tinyfishie/openai-operator-scores-43-on-hard-web-tasks-we-scored-81-here-are-all-300-runs-2jh1)
  - The Steel aggregator lists TinyFish at 90.0% on Online-Mind2Web, below "ABP with Claude Opus 4.6" at 90.53%, and
    warns that human, WebJudge and custom judges give different scores. (search extract of
    https://leaderboard.steel.dev/leaderboards/online-mind2web)
  - Caveat: the competitor numbers appear to come from older agent versions; Browser Use at 8.1% conflicts with Browser
    Use's own claims.
- **What TinyFish adds for FactoryOS (inference).**
  1. A free web-search API that works from a server, which fills the Surfer's biggest gap: search engines block the EC2
     IP.
  2. Fetch as a second opinion for pages the anonymous EC2 Chromium cannot read, if the free tier really covers rendered
     pages. **Unverified**: whether Fetch renders JavaScript or passes anti-bot pages for free.
  3. A paid managed agent with stealth and proxies. Under ZERO ADDITIONAL SPEND this is out of scope, and "stealth +
     residential proxy" sits uncomfortably close to the repository's own non-goal of not bypassing anti-bot controls.

### 2. browser-use (open source and cloud)

**Takeaway.** browser-use is the strongest free, self-hostable LLM browser agent. The library costs nothing, but every
task costs model tokens, and in the vendor's own figures a reliable model costs about $0.70-1.64 per successful task. It is
not free in any practical sense unless it runs on a free-tier model.

- **Facts from the opened repository and PyPI.**
  - MIT license, about 121.4k stars, 13.6k forks.
  - v1.0.6 released 2026-11-16, after 1.0.1-1.0.5 between Nov 10 and Nov 15. The API is churning quickly, and pinning
    versions is advisable.
  - Python ≥3.11.
  - Models: the default is the vendor's `bu-4.0` gateway (also `-mini` and `-pro`). Built-in clients are `ChatOpenAI`,
    `ChatAnthropic` and `ChatGoogle`; any Pydantic AI model works, and Ollama works through a `base_url`.
  - The CLI is `browser-use` (with `--doctor` and `login`); the repo also ships an MCP `server.json`.
  - "Cloud browsers solve CAPTCHAs automatically" using stealth browsers and proxies. Local browsers make no stealth
    claims. The README admits "no browser configuration guarantees that every CAPTCHA can be avoided or solved".
  - The repo's only benchmark is the vendor's "Browser Use Benchmark v2", a 60-task subset with no numbers in the text.
  - The README contains instructions addressed to AI agents (send feedback, pin versions). This is a small example of a
    repository text steering agents.

  (https://github.com/browser-use/browser-use ; https://pypi.org/project/browser-use/)
- **Cloud pricing (official docs via extract).**
  - $0.06 per browser-hour, billed per minute with a 1-minute minimum.
  - Proxy traffic: $5/GB through home-IP proxies; $0.20/GB direct or through your own proxy.
  - Prepaid credits from $5, with 1 credit = $1 and no subscription.
  - Agent tasks: bu-ultrafast has a median of $0.006 per task. With Claude Opus 4.7, a *successful* task costs $0.70 (V2,
    about 1 minute), $0.87 (V3, about 2 minutes) or $1.64 (V4, about 5 minutes) on production traffic.
  - The vendor's comparison page puts its model cost at about 11¢ per task on its own benchmark.

  (search extract of https://docs.browser-use.com/cloud/pricing , https://browser-use.com/posts/bu-ultrafast-is-live ,
  https://browser-use.com/best-web-agents)

  Conflicts: the pricing calculator shows $10/GB and a $0.01 per-task init fee, and a scaling guide shows $0.02 per
  browser-hour (probably stale). (search extract of https://browser-use.com/pricing-calculator ,
  https://browser-use.com/posts/run-browser-automation-at-scale) New Google, GitHub or Microsoft signups get $1 of
  cloud credit. (repo README)
- **Reliability.** No independent, recent human-evaluated success rate for browser-use was found.
  - The Online-Mind2Web repository table reports judge agreement with humans, not success rates. For Browser Use
    trajectories, agreement ranges from 63.3% (AgentTrek judge) to 89.3% (WebJudge o4-mini).
    (https://github.com/OSU-NLP-Group/Online-Mind2Web)
  - Skyvern's marketing cites Browser Use at 89.1% on WebVoyager. (search extract of
    https://www.skyvern.com/blog/browser-use-vs-automation-anywhere/ , competitor)
  - TinyFish's marketing cites 8.1% on hard Online-Mind2Web tasks (competitor). The spread from 8% to 89% shows how much
    these numbers depend on the benchmark and the judge.

### 3. Playwright, Playwright MCP and playwright-cli: the free deterministic layer

**Takeaway.** Scripted Playwright costs nothing per run, is reproducible and fast (FactoryOS measures a median of 5 s),
and is the right executor for any task that repeats on a known site. LLM-driven agents only pay off for one-off,
exploratory or frequently changing flows. The best use of an LLM here is to *write and repair* Playwright scripts at
development time, not to drive the browser on every run.

- **Playwright.** Apache-2.0, v1.65.2 released 2026-11-14, bundling Chromium 159, Firefox 159 and WebKit 27.2.
  (https://pypi.org/project/playwright/)
- **Playwright MCP** (Apache-2.0, 39.8k stars). (https://github.com/microsoft/playwright-mcp)
  - It works from the accessibility tree ("not pixel-based input"), which "avoids ambiguity common with
    screenshot-based approaches".
  - Default mode is a persistent profile, with the caveat that "a persistent profile can only be used by one browser
    instance at a time". `--isolated` mode and `--storage-state` are available.
  - Extension mode can attach to the user's logged-in Chrome or Edge tabs.
  - Security, quoted from the README: "Playwright MCP is **not** a security boundary"; `--allowed-origins` defaults to
    all origins and "does not affect redirects"; `browser_run_code_unsafe` is "RCE-equivalent".
- **playwright-cli** (Apache-2.0, 15.3k stars). (https://github.com/microsoft/playwright-cli)
  - Microsoft recommends it for coding agents (Claude Code, Copilot) because it is "more token-efficient": it avoids
    "loading large tool schemas and verbose accessibility trees". No numbers are given.
  - Named sessions; `--persistent` writes the profile to disk; headless sessions are killed after 1 hour idle.
  - `install --skills` adds agent skills.
- **When scripted Playwright beats LLM agents (inference, supported by the evidence above).**
  - The task repeats on the same site.
  - Exact output or audit trails matter. FactoryOS binds approvals to an immutable payload hash, and an LLM that
    re-plans each run cannot guarantee the same action.
  - Cost must be zero.
  - Latency matters: 5 s versus 1-5 minutes per agent task in the browser-use figures above.
  - The site's content is untrusted, so prompt-injection exposure must be avoided.

  LLM agents win for long-tail, never-repeated tasks on unfamiliar sites, and only if someone pays the token cost and
  reviews the result.

### 4. Alternatives: pricing and benchmarks

| Tool | What it is | License / self-host | Price (as found) | Benchmark claims | Source |
|---|---|---|---|---|---|
| Stagehand (Browserbase) | `act` / `extract` / `observe` on top of Playwright, plus self-healing; Model Gateway | MIT, 26.1k stars; runs locally with Chrome (`localBrowser.launch()`); response caching is server-side on Browserbase only | Library free; needs an LLM key unless Browserbase's gateway is used | "2x faster than Playwright cloud equivalent" (no methodology) | https://github.com/browserbase/stagehand (opened) |
| Browserbase | Managed cloud browsers | SaaS | Free: 1 browser-hour, 15-minute sessions; $20/month for 100 h (overage $0.12/h); $99/month for 500 h ($0.10/h); x402 pay-per-use at $0.12/h | — | search extract of https://docs.browserbase.com/account/billing/plans , https://x402.browserbase.com/ |
| Steel | Managed browsers; runs a public leaderboard | SaaS; open-source browser API exists (not verified this session) | Launch plan $0 plus usage, with $30 one-time credits (90 days), $0.10/h; Scale $0.08/h. An older llms.txt says "100 hours/month free" (stale) | — | search extract of https://steel.dev/pricing , https://docs.steel.dev/overview/pricinglimits |
| Hyperbrowser | Managed browsers | SaaS | Free 5,000 credits (= $5), 1 concurrent session, 7-day retention; Startup $30/month; Scale $100/month | — | search extract of https://www.hyperbrowser.ai/pricing (page possibly about 11 months old) |
| Skyvern | Vision and LLM workflow agent | AGPL-3.0; "anti-bot measures" only in the managed cloud | Conflicting: "$0.05 per step" vs Hobby $29/month (30k credits) and Pro $149/month | WebVoyager 85.85% (Skyvern 2.0, Jan 2025, run in its cloud on GPT-4o); WebBench 64.4% | search extract of https://www.skyvern.com/blog/skyvern-2-0-webvoyager-benchmark-results/ , https://github.com/skyvern-ai/skyvern |
| Anthropic computer use (API) | Screenshot and action tool for Claude models | API | Token-billed (not re-verified this session); paid API, so outside zero-spend | OSWorld-Verified: top Claude entries 83-86% (aggregators) | see OSWorld row |
| Claude in Chrome | Browser extension agent in the user's own Chrome | Consumer product | Included in Pro, Max, Team and Enterprise (and Ultra) | Injection rates in Key claim 10 | search extract of https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome , https://claude.com/pricing |
| OpenAI ChatGPT agent / Atlas / Operator | Consumer agents | — | ChatGPT agent "no longer available", replaced by "ChatGPT Work"; Atlas "has since been deprecated". Historical limits: 40 agent messages/month on Plus, 400 on Pro | Operator 43.2% (TinyFish's test) | search extract of https://help.openai.com/en/articles/11752874-chatgpt-agent , https://openai.com/index/introducing-chatgpt-atlas/ |
| Gemini computer use | Tool in the Gemini API | API | Regular token pricing; **no free tier**; 2.5 Pro CU preview $1.25 in / $10 out per 1M tokens (≤200k context) | — | search extract of https://ai.google.dev/gemini-api/docs/pricing , https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing |
| Amazon Nova Act | Agent SDK and model for UI workflows | AWS service | $4.75 per agent-hour of elapsed time, human-in-the-loop waiting excluded; free local API key "with daily limits"; GA Dec 2025; us-east-1 only | — | search extract of https://aws.amazon.com/nova/pricing/ , https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html |

**Benchmarks, with dates and caveats.**

- **Online-Mind2Web** (300 tasks, 136 live sites, human evaluation; Xue et al., "An Illusion of Progress?", COLM 2025).
  - Frontier agents "show a drastic drop" from their self-reported WebVoyager numbers. WebVoyager covers only 15 sites,
    uses LLM-synthesised tasks, and relies on an automatic judge with poor agreement.
  - Most agents did not beat SeeAct (2024); Claude Computer Use 3.7 and Operator were the exceptions.
  - WebJudge reaches about 85% agreement with humans.
  - An AlphaXiv listing summarises frontier agents at about 30-61%, versus about 90% on WebVoyager (not checked against
    the paper's tables).

  (search extract of https://arxiv.org/abs/2504.01382 ; https://github.com/OSU-NLP-Group/Online-Mind2Web)

  The benchmark repository changed in 2025-2026:
  - six tasks were replaced on 2026-05-15;
  - a v2 submission schema with outsourced human evaluation arrived 2026-05-23;
  - GPT-6 Luna is now the recommended WebJudge backbone (87.4% agreement) because o4-mini was retired;
  - tasks "should start from the specified websites, not Google Search".

  Scores from different dates are therefore not directly comparable. (https://github.com/OSU-NLP-Group/Online-Mind2Web)
- **OSWorld-Verified** (desktop computer use; aggregators, low confidence on exact numbers).
  - The top entries are in the mid-80s, above the reported human baseline of about 72.36%: claude-fable-5 at 86.0%
    (Yutori board, 2026-08-01), Qwen3.8-Max at 86.1% (Steel board), Claude Opus 5 at 83.4%. Presenc.ai lists an
    "Intelligence-Indeed Agent" at 90.19% on the official board.
  - The harder **OSWorld-Verified 2.0** has its best entry at **31.4%** (Claude Opus 5, BenchLeader, 2026-10-07).
    Presenc.ai says the best official entry fully completes 44%.
  - The leaders disagree between sites, and self-reported and verified runs are mixed together.

  (search extracts of https://yutori.com/leaderboards/osworld-verified , https://leaderboard.steel.dev/leaderboards/osworld/ ,
  https://www.benchleader.com/benchmarks/osworld_2 , https://presenc.ai/research/osworld-computer-use-leaderboard-2026)
- **WebArena.** Not researched this round; no 2026 figure was verified.

### 5. Operational reality

- **Anti-bot.**
  - FactoryOS evidence (2026-11-15): DuckDuckGo, Mojeek, Startpage, Brave and Bing all refuse the EC2 runner's
    datacenter IP as automated traffic, and the project explicitly treats bypassing this as a non-goal. (repo
    `web_surfer.py` docstring)
  - Cloudflare's "signed agents" use Web Bot Auth: Ed25519 HTTP message signatures checked against a published key
    directory. The first cohort was ChatGPT agent, Goose (Block), Browserbase and Anchor Browser. Since 2026-07-01
    Cloudflare tags traffic as "Direct" or "Intermediary" access. Visa and Mastercard agentic-commerce protocols build on
    Web Bot Auth. (search extract of https://blog.cloudflare.com/signed-agents/ ,
    https://developers.cloudflare.com/bots/concepts/bot/signed-agents/ ,
    https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/)
  - A single user reports signature failures after key rotation. (https://community.cloudflare.com/t/existing-verified-agent-failing-web-bot-auth-signature-verification/949809 ,
    anecdotal)
  - Inference: the web is splitting into identified agents (signed, accountable) and anonymous bots (challenged). A
    one-person project can in principle publish its own Web Bot Auth keys, but recognition as a "signed agent" requires
    Cloudflare's policy approval (not verified for small operators).
- **CAPTCHA.** Paid clouds advertise automatic CAPTCHA solving (browser-use cloud) or "stealth" profiles (TinyFish).
  FactoryOS's policy is to stop at `waiting_human`. Using a vendor that solves CAPTCHAs automatically would quietly break
  that policy. (repo `docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md`, rule 6)
- **Logins, sessions and 2FA.**
  - Every tool handles sessions with persisted storage state or profiles: Playwright MCP profiles and `--storage-state`;
    playwright-cli `--persistent`; TinyFish Browser Context Profiles; browser-use cloud profiles.
  - FactoryOS already has an AES-256-GCM vault for Playwright `storage_state`, keyed to workspace, provider and account.
    It holds sessions the owner logged into once by hand (2FA and CAPTCHA done by a human) and refuses to store
    OTP/TOTP seeds. (repo `browser_runner/vault.py` docstring)
  - That is the right pattern. No vendor adds anything essential here, and handing session cookies to a third-party
    cloud widens the attack surface. (inference)
- **Cost per task (inference; assumptions stated).**

  | Option | Cost per task | Assumptions |
  |---|---|---|
  | Scripted Playwright on the existing EC2 | ≈$0 marginal | The instance is already paid for; measured median runtime 5 s |
  | TinyFish Agent | ≈$0.16-0.48 | 10-30 steps at $0.016; the $8 starting balance ≈ 500 steps ≈ 15-50 tasks |
  | browser-use cloud agent, cheap model | ≈$0.006-0.01 | Vendor median; reliability on hard tasks unknown |
  | browser-use cloud or OSS with a frontier model | ≈$0.70-1.64 per *successful* task | Vendor's Opus 4.7 figures |
  | Nova Act | ≈$0.08-0.40 per task | 1-5 minutes at $4.75/h, plus AWS resources |
  | Managed browser time alone | ≈$0.06-0.12 per browser-hour | Excludes the LLM |

- **Speed and failure.** FactoryOS's own Surfer benchmark is the most relevant local evidence (repo
  `docs/verification/surfer-benchmark-2026-11-16.md`, 33 production tasks):
  - median runtime 5 s, but queue waits up to 172 s because the worker runs one task at a time;
  - the queue refused 2 of 33 tasks with HTTP 429;
  - **status "done" overstated success in 17 of 28 cases**, and only **12 of 31** answers were fully useful;
  - failures came from navigation menus instead of content, a 6,000-character cut-off with no paging, false CAPTCHA
    detection, and anti-bot pages.

  These are content-extraction and contract problems, not "the browser lacks an LLM" problems.

### 6. Legal and terms-of-service limits

- **Amazon v. Perplexity (Comet).**
  - March 2026: Judge Chesney found "strong evidence" that Comet accessed Amazon "without authorization" and granted a
    preliminary injunction. (https://www.geekwire.com/2026/judge-blocks-perplexitys-ai-bot-from-shopping-on-amazon-in-early-test-of-agentic-commerce/ ;
    https://www.cnbc.com/2026/03/10/amazon-wins-court-order-to-block-perplexitys-ai-shopping-agent.html)
  - 2026-08-04: the Ninth Circuit reversed, holding that because Comet acts only at the user's direction, the user is the
    one accessing the site. Commentators stress the holding is narrow and tied to Comet's architecture.
    (https://www.americanbar.org/groups/litigation/resources/newsletters/privacy-data-security/ninth-circuit-holds-human-user-not-developer-ai-agent-responsible-websites-accessed/ ;
    https://www.mediapost.com/publications/article/417007/appeals-court-sides-against-amazon-lifts-perplexi.html)
  - 2026-09-10: rehearing denied. 2026-09-21: Amazon filed an amended complaint aimed at Comet for iOS (cookies sent to
    Perplexity's cloud). The case remains active as of early November 2026. (search extract of
    https://thenextweb.com/news/amazon-loses-perplexity-comet-ai-shopping-ruling , press)
  - Inference for FactoryOS: this reasoning helps a user-directed agent acting on the user's own account. It does not
    help an autonomous company running agents on its own initiative, and contract claims under site terms are a separate
    matter.
- **hiQ v. LinkedIn (9th Cir. 2022).** Scraping public data is not by itself a CFAA violation; contract-based
  enforcement is separate. (secondary, already cited in the sibling notes `ext_messaging_email_crm.md`:
  https://www.revenueflow.com/blog/linkedin-web-scraping)
- **Platform terms.**
  - LinkedIn User Agreement §8.2 prohibits "bots or other unauthorized automated methods to access the Services".
    (https://conductatlas.com/platform/linkedin/linkedin-user-agreement/provision/CA-P-023526/prohibition-on-bots-or-inauthentic-automated-engagement/ ,
    secondary)
  - TikTok's terms ban automated data extraction without approval. (same aggregator, cited in `ext_social_publishing.md`)
- **Legitimately automatable (inference, conservative).**
  - Reading public pages whose terms and robots rules allow it.
  - The owner's own accounts on services whose terms allow automation, or that expose an official API (prefer the API).
  - Filling drafts up to the submit boundary, with human approval of the final step. FactoryOS already enforces this:
    `browser_runner/social.py` stops before submit and the executor blocks every submit.
- **Not legitimately automatable.** LinkedIn or TikTok account automation, account creation, CAPTCHA or anti-bot evasion,
  scraping behind logins against the terms, and outreach without consent.

### 7. Security: prompt injection through web content

- **Anthropic's figures for its own product** (vendor):
  - 23.6% attack success without mitigations and 11.2% with them in the August 2025 Claude in Chrome pilot;
  - about 1% for Opus 4.5 against an internal Best-of-N attacker (late 2025), with the warning that no browser agent is
    immune;
  - "<0.08%" for the current product configuration, and 0.3% against Fable 5 in the GA post;
  - on Gray Swan, Opus 4.7 is about 0.1% on a single attempt but **5-6% after 100 adaptive attempts**.

  (search extract of https://www.anthropic.com/research/prompt-injection-defenses ,
  https://claude.com/resources/articles/claude-in-chrome-generally-available ,
  https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely ,
  https://www.anthropic.com/engineering/how-we-contain-claude)
- **Independent and secondary findings** (all reported_secondary, primary papers not opened):
  - Brave showed indirect injection against Perplexity Comet that exfiltrated email and one-time passwords.
  - Zenity Labs' "PleaseFix" research extended to Claude in Chrome, Gemini in Chrome, Comet, Atlas and Copilot in Edge.
  - A University of Washington study of 7 agentic browsers found that 4 let attackers bypass the same-origin policy.
  - A second-hand TechTimes figure says Atlas blocked only 5.8-6% of malicious pages (low confidence).
  - arXiv 2610.15138, "The Agent Clicks Approve", reports that injected page text makes agents authorize access the task
    never named; only the title was seen.
  - An arXiv survey (2601.17548) warns that vendor internal benchmarks overstate defence against adaptive attacks.

  (search extracts listing https://arxiv.org/pdf/2610.15138 , https://arxiv.org/pdf/2601.17548 ,
  https://blog.cyberdesserts.com/ai-browser-security-risks/)
- **Practical mitigations (inference; several already implemented in FactoryOS).**
  - Deterministic scripts for any action that writes.
  - A read-only default, a per-task origin allowlist, and blocking of POST/PUT and private IPs. All of these exist in
    `browser_runner` and the egress proxy.
  - Treat page text as data: never let text read from the web become instructions to a lane that holds credentials or
    publishing rights.
  - Keep the approval gate bound to an immutable payload hash, which already exists.
  - No vendor-side CAPTCHA solving or stealth.
  - Never run Playwright MCP's `browser_run_code_unsafe`; remember that `--allowed-origins` "does not affect redirects".
  - Isolated profiles per account.

### 8. TinyFish vs the existing FactoryOS runner: what is actually missing

- The repository already contains:
  - a provider-neutral `BrowserActionPlan` with bounded steps and action classes;
  - a fail-closed approval binding;
  - session and vault references with human takeover at CAPTCHA or 2FA;
  - an SSRF-safe egress proxy;
  - an adapter design that names "TinyFish-style browser execution" as a future adapter.

  (repo `browser_runner/core.py`, `sessions.py`, `vault.py`, `docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md`)
- The measured gaps are content extraction (main-content detection, paging past 6,000 characters, selector hints), honest
  status reporting ("done" vs "useful"), queue throughput (one worker, 20 active tasks), and **search**, which is blocked
  from the EC2 IP. (repo `docs/verification/surfer-benchmark-2026-11-16.md`, `web_surfer.py`)
- Only the search gap is something TinyFish solves for free. The others are fixed with deterministic code (for example a
  readability-style extractor), which costs nothing. (inference)

## Counter-evidence and caveats

- **The case for LLM agents.** Agents keep improving: OSWorld-Verified tops are in the mid-80s, above the human baseline,
  and vendors report $0.006 median tasks. If FactoryOS gets a paying customer whose workflow is a long tail of unfamiliar
  sites, a pay-per-use agent (TinyFish at $0.016/step or browser-use cloud) may be cheaper than founder hours.
  Counter-counter: there is no such customer today, and OSWorld 2.0 (best entry 31-44%) and Online-Mind2Web show that hard,
  realistic tasks still fail often.
- **Benchmarks are unreliable.** Many headline numbers are self-run with self-chosen judges: TinyFish 81.9% or 90%;
  Skyvern 85.85% on WebVoyager with GPT-4o in its own cloud; browser-use's own benchmark. Aggregator sites disagree on who
  leads OSWorld. WebVoyager is documented as inflated. Treat every vendor figure as an upper bound.
- **Unfamiliar model names.** Several 2026 model names in the sources (GPT-6 Luna/Sol, Claude Fable 5, Claude Opus 4.7
  and 5, Gemini 3.8 Flash and 4) are newer than my training data. They are reported exactly as the sources state them and
  were not independently checked.
- **TinyFish free tier may change.** "Free search and fetch" is a growth tactic by a venture-funded company; limits
  already differ between pages (30/min vs 5/min). Building a hard dependency on it is risky, so keep it behind the
  existing provider abstraction with Wikipedia as the fallback.
- **Ukraine availability is unverified** for TinyFish, browser-use cloud, Browserbase, Steel, Hyperbrowser and Nova Act;
  Nova Act runs in us-east-1 only. No sanctions or geo-restriction clause was found, and none was searched for
  specifically.
- **OpenAI status.** "ChatGPT agent retired" and "Atlas deprecated" come only from official-domain search extracts; an
  unconfirmed blog says Atlas shut down on 2026-08-09. What "ChatGPT Work" can do in a browser was not verified.
- **Legal uncertainty.** The Ninth Circuit Comet ruling is narrow, is under continued litigation, and concerns US law
  (CFAA and California law) only. EU or Ukrainian law was not researched. Meta v. Bright Data (2024, logged-out scraping)
  comes from training knowledge only and was **not re-verified this session**; do not cite it as verified.
- **Prompt-injection figures** for Claude in Chrome are vendor-internal. Independent adaptive attacks reach 5-6% even on
  Anthropic's own reporting.
- **Not covered:** WebArena 2026 numbers; Anthropic computer-use API token overhead; Steel's open-source browser API
  license; Browserbase's free tier (1 hour vs 60 minutes, possibly the same).

## Implications for FactoryOS

**Bottom line.** The cheapest reliable way to act on API-less sites is the setup FactoryOS already has: deterministic
Playwright on the existing EC2 host, with human-in-the-loop sessions and an approval gate. Improve its extraction, and use
LLMs only to author or repair scripts at development time. Use TinyFish only for its **free Search API**, as an optional
Surfer search provider. None of these tools creates views, subscribers, leads or revenue; they only lower the labour cost
of tasks. With zero revenue, any per-task agent spend has no payback path today.

Verdicts:

| Tool | Verdict | Why / conditions | Cost |
|---|---|---|---|
| Playwright (existing EC2 runner) | **ADOPT / KEEP** | Free, Apache-2.0, deterministic, 5 s median, already behind the vault, egress proxy and approval gate. Next: main-content extraction, paging past 6,000 characters, a "useful vs done" status, a site-specific selector registry, and a second worker or concurrency once demand exists. | $0 marginal (existing EC2) |
| playwright-cli plus skills / Playwright MCP | **ADOPT for development time only** | Claude Code (existing Pro plan) uses them to explore a site and generate or repair deterministic recipes for `browser_runner`. Not a production runtime: "not a security boundary". | $0 |
| TinyFish Search and Fetch (free) | **PILOT** | An optional `web_search` provider for the Surfer, off by default, behind the existing provider switch, capped per day, with Wikipedia kept as fallback. Needs the owner to create an account and a key stored as a secret, which the owner must do. Check the terms and Ukraine availability first. | $0 within free limits |
| TinyFish Agent / Browser (paid) | **REFERENCE** | $0.016/step is cheap per task, but the stealth and proxy design conflicts with T-560 rule 6, it is proprietary and hosted, and it needs paid top-ups. Revisit only for a paying customer's long-tail workflow, through the existing adapter interface. | ≈$0.16-0.48 per task |
| browser-use OSS | **REFERENCE** (pilot later) | The best free agent library (MIT), but its value depends on paid frontier tokens ($0.70-1.64 per successful task, vendor figures). It churns fast (6 releases in 7 days). Pilot only for a concrete owner-triggered exploratory task, and only on a model already paid for. | $0 library + model tokens |
| browser-use Cloud, Browserbase, Steel, Hyperbrowser | **REJECT now** | New paid infrastructure; the free credits are one-time trials; residential proxies and CAPTCHA solving conflict with policy. | $20-100/month or usage |
| Stagehand | **REFERENCE** | A good hybrid design idea: a cached, self-healing `act`. But caching is Browserbase-side, and it needs an LLM key. | $0 library + tokens |
| Skyvern | **REFERENCE** | AGPL-3.0 with anti-bot in the cloud only; benchmark from Jan 2025; conflicting pricing. | — |
| Claude in Chrome | **ADOPT (owner-supervised only)** | Already included in the owner's Claude Pro. Good for one-off tasks in the owner's own logged-in accounts with the owner watching; not for unattended or Telegram-triggered automation. Follow Anthropic's safe-use guidance and keep sensitive sites off. | $0 (existing subscription) |
| Anthropic / Gemini computer-use APIs | **REJECT now** | Token-billed paid APIs; Gemini CU has no free tier. Revisit only with revenue. | paid tokens |
| OpenAI ChatGPT agent / Atlas | **REJECT** (retired or deprecated per help center) | Check what the owner's existing ChatGPT plan offers under "ChatGPT Work" before relying on it. | — |
| Amazon Nova Act | **REFERENCE** | GA, $4.75/agent-hour, free local key with daily limits. us-east-1 only; Ukraine eligibility unverified; adds AWS spend once deployed. | paid beyond free key |

Specific recommendations:

1. Fix the Surfer's measured failure modes with deterministic code before considering any LLM browser agent: only 12 of
   31 answers were fully useful, and 17 of 28 "done" statuses were wrong.
2. Never let a vendor solve CAPTCHAs or use residential proxies on FactoryOS's behalf. That would quietly violate the
   repository's own "do not bypass anti-bot" invariant.
3. Keep page content away from lanes that hold credentials or publishing rights.
4. If an LLM agent is ever piloted, run it read-only, origin-allowlisted, on the EC2 runner's egress proxy, with a
   per-day cost cap and with results reviewed by a human.

## Sources

Opened in full (WebFetch):

- https://github.com/browser-use/browser-use
- https://pypi.org/project/browser-use/
- https://github.com/microsoft/playwright-mcp
- https://github.com/microsoft/playwright-cli
- https://pypi.org/project/playwright/
- https://github.com/tinyfish-io
- https://github.com/tinyfish-io/agentql
- https://github.com/browserbase/stagehand
- https://github.com/OSU-NLP-Group/Online-Mind2Web
- (https://pypi.org/project/agentql/ was attempted and failed to load)

Read through search extracts (official domain unless marked):

- TinyFish:
  - https://www.tinyfish.ai/blog/search-and-fetch-are-now-free-for-every-agent-everywhere
  - https://www.tinyfish.ai/blog/tinyfish-vs-browserbase
  - https://www.tinyfish.ai/blog/browserbase-pricing
  - https://tinyfish.ai/blog/tinyfish-vs-browser-use-cloud-agents-vs-local-agents
  - https://www.tinyfish.ai/blog/mind2web
  - https://docs.tinyfish.ai/key-concepts/endpoints
  - https://docs.tinyfish.ai/api-reference/automation/run-browser-automation-with-sse-streaming
  - https://docs.tinyfish.ai/anti-bot-guide
  - https://docs.tinyfish.ai/agent-api/browser-context-profiles
  - https://docs.tinyfish.ai/cli/commands
  - https://www.agentql.com/
- TinyFish press and aggregators:
  - https://www.businesswire.com/news/home/20250820555825/en/TinyFish-launches-with-47-million-to-define-the-era-of-Enterprise-Web-Agents
  - https://siliconangle.com/2025/08/20/tinyfish-raises-47m-expand-deployment-enterprise-web-agents/
  - https://builtin.com/articles/tinyfish-launches-raises-47m-series-a-20250822
  - https://www.digitalcommerce360.com/2025/08/21/tinyfish-47-million-funding-enterprise-web-agent-platform/
  - https://www.stork.ai/en/tinyfish
  - https://dev.to/tinyfishie/openai-operator-scores-43-on-hard-web-tasks-we-scored-81-here-are-all-300-runs-2jh1
- browser-use:
  - https://docs.browser-use.com/cloud/pricing
  - https://browser-use.com/posts/bu-ultrafast-is-live
  - https://browser-use.com/pricing-calculator
  - https://browser-use.com/posts/run-browser-automation-at-scale
  - https://browser-use.com/best-web-agents
- Managed browsers:
  - https://docs.browserbase.com/account/billing/plans
  - https://x402.browserbase.com/
  - https://steel.dev/pricing
  - https://docs.steel.dev/overview/pricinglimits
  - https://www.hyperbrowser.ai/pricing
- Skyvern:
  - https://www.skyvern.com/blog/skyvern-2-0-webvoyager-benchmark-results/
  - https://github.com/skyvern-ai/skyvern (extract only)
  - https://www.skyvern.com/blog/browser-use-vs-automation-anywhere/
- Anthropic:
  - https://support.claude.com/en/articles/12012173-get-started-with-claude-in-chrome
  - https://claude.com/pricing
  - https://support.claude.com/en/articles/12902428-use-claude-in-chrome-safely
  - https://www.anthropic.com/research/prompt-injection-defenses
  - https://claude.com/resources/articles/claude-in-chrome-generally-available
  - https://www.anthropic.com/engineering/how-we-contain-claude
- OpenAI:
  - https://help.openai.com/en/articles/11752874-chatgpt-agent
  - https://openai.com/index/introducing-chatgpt-atlas/
  - https://developers.openai.com/api/docs/pricing
- Google:
  - https://ai.google.dev/gemini-api/docs/pricing
  - https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing
- Amazon:
  - https://aws.amazon.com/nova/pricing/
  - https://aws.amazon.com/blogs/aws/build-reliable-ai-agents-for-ui-workflow-automation-with-amazon-nova-act-now-generally-available/
  - https://docs.aws.amazon.com/nova-act/latest/userguide/what-is-nova-act.html
- Benchmarks:
  - https://arxiv.org/abs/2504.01382
  - https://leaderboard.steel.dev/leaderboards/online-mind2web
  - https://yutori.com/leaderboards/osworld-verified
  - https://leaderboard.steel.dev/leaderboards/osworld/
  - https://www.benchleader.com/benchmarks/osworld_2
  - https://presenc.ai/research/osworld-computer-use-leaderboard-2026
- Cloudflare:
  - https://blog.cloudflare.com/signed-agents/
  - https://developers.cloudflare.com/bots/concepts/bot/signed-agents/
  - https://developers.cloudflare.com/bots/reference/bot-verification/web-bot-auth/
  - https://community.cloudflare.com/t/existing-verified-agent-failing-web-bot-auth-signature-verification/949809 (anecdotal)
- Legal (press and law-firm):
  - https://www.geekwire.com/2026/judge-blocks-perplexitys-ai-bot-from-shopping-on-amazon-in-early-test-of-agentic-commerce/
  - https://www.cnbc.com/2026/03/10/amazon-wins-court-order-to-block-perplexitys-ai-shopping-agent.html
  - https://www.americanbar.org/groups/litigation/resources/newsletters/privacy-data-security/ninth-circuit-holds-human-user-not-developer-ai-agent-responsible-websites-accessed/
  - https://www.mediapost.com/publications/article/417007/appeals-court-sides-against-amazon-lifts-perplexi.html
  - https://thenextweb.com/news/amazon-loses-perplexity-comet-ai-shopping-ruling
- Security (secondary):
  - https://arxiv.org/pdf/2610.15138 (title only)
  - https://arxiv.org/pdf/2601.17548
  - https://blog.cyberdesserts.com/ai-browser-security-risks/
- Repository evidence (local files, read directly):
  - `docs/verification/surfer-benchmark-2026-11-16.md`
  - `docs/guides/browser-agent.md`
  - `docs/roadmap/T-560_BROWSER_ACTION_RUNNER.md`
  - `web_surfer.py`
  - `browser_runner/core.py`, `sessions.py`, `vault.py`, `social.py`, `recipes.py`
- Already cited by sibling notes and reused here:
  - https://www.revenueflow.com/blog/linkedin-web-scraping
  - https://conductatlas.com/platform/linkedin/linkedin-user-agreement/provision/CA-P-023526/prohibition-on-bots-or-inauthentic-automated-engagement/
