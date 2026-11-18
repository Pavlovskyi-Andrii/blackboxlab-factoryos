# Cost of running AI agents 24/7 for FactoryOS (state 17-18 Nov 2026)

> Method note. WebFetch to vendor sites is blocked by the session proxy, so every web fact below comes from a **search extract of the official URL** (labelled "SE") unless marked otherwise. Anthropic prices were cross-checked against the claude-api skill's model table (cached 2026-11-03). Facts reused from sibling notes in this folder are marked "[sibling: file]". Local repo facts cite file:line. 21 web searches used. Nothing was purchased or called.

## Key claims

| # | Claim | Source URL | Date/version | Confidence |
|---|---|---|---|---|
| 1 | Anthropic API per 1M tokens: Opus 5.5 $4 in / $20 out; Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50 (prompt <=100K; $0.50 / $2.50 above). Cache reads are 0.05x on Opus/Sonnet 5.5 ($0.20 / $0.10) and $0.01 on Haiku 5.5. Cache writes cost 1.25x (5-min) or 2x (1-h). Batch is 50% off. | https://platform.claude.com/docs/en/models/opus-5-5/overview ; https://platform.claude.com/docs/en/models/haiku-5-5/overview (SE) ; claude-api skill | skill cache 2026-11-03; SE Nov 2026 | verified_primary |
| 2 | OpenAI API per 1M tokens: GPT-6.2 Sol $2 / $0.10 cached / $10; GPT-6.2 Astra $8 / $0.40 / $40; GPT-6.1 Terra $1 / $0.05 / $5; GPT-6 Luna $0.10 / $0.01 / $0.50. Batch (or Flex) is 50%. Prompts over 272K input cost 2x input and 1.5x output. | https://developers.openai.com/api/docs/models/gpt-6.2-sol ; https://openai.com/index/introducing-gpt-6-1-terra/ ; https://developers.openai.com/api/docs/pricing (SE) | Nov 2026 | verified_primary (Terra/Luna, several official pages agree); reported_secondary (Sol/Astra, model page only) |
| 3 | Gemini 3.8 Flash costs $0.75 / $3.75 (intro) until 31 Dec 2026, then $1.50 / $7.50 from 1 Jan 2027. Batch is half. Free-tier limits are reported (forum) as about 20 requests/day on 3.8 Flash and about 500 on Flash-Lite. | https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8 ; https://blog.google/innovation-and-ai/models-and-research/gemini-models/3-8-flash-and-3-8-flash-cyber/ (SE); https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609 (SE) | Nov 2026 | verified_primary (price); reported_secondary (RPD) |
| 4 | Open-weight models on OpenRouter cost 1-2 orders of magnitude less per token: DeepSeek V4 Flash $0.054 / $0.242; GLM 5.2 weighted average $0.447 / $3.31; Kimi K3 input $0.24-$4.50 across about 20 providers. Prices differ by provider and caching is not uniform. | https://openrouter.ai/blog/insights/the-open-weight-models-that-matter-june-2026/ ; https://openrouter.ai/collections/discounted-models (SE) | Jun-Oct 2026 | reported_secondary |
| 5 | Claude plans: Pro $20 ($17/month billed annually); Max $100 (5x Pro, with a 5-hour limit, a weekly limit and a separate weekly Fable limit); Ultra $200 (10x Pro weekly; no 5-hour limit for verified accounts). **Max includes $100/month and Ultra $200/month of API credits**, which cannot be spent on interactive Claude Code or on extra usage. | https://claude.com/pricing ; https://support.claude.com/en/articles/11049741-what-is-the-max-plan ; https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans (SE) | credits since 7 Oct 2026 | verified_primary (SE) |
| 6 | Anthropic's consumer terms prohibit accessing the services "through automated or non-human means, whether through a bot, script, or otherwise", except via an Anthropic API key "or where we otherwise explicitly permit it". Claude Code docs permit `claude -p` and the Agent SDK on a plan, but limits "assume ordinary, individual usage", and routing plan credentials for other users is banned. | https://assets.claude.com/43c13f51a6d9755341433f79cf63c966ed9200ea.pdf (SE); https://code.claude.com/docs/en/legal-and-compliance [sibling: tool_openclaw.md] | 2026 | verified_primary |
| 7 | ChatGPT plans: Plus $20; Pro $100 / $200 / $500; Business $25 per seat per month monthly or $20 annual (minimum 2 seats); Premium seats $125 / $100 with no 5-hour limit. Codex on Plus: about 15-160 Sol-class messages per 5 hours. OpenAI's consumer terms ban "automatic or programmatic extraction of data or Output". | https://learn.chatgpt.com/docs/pricing ; https://help.openai.com/en/articles/8792828-chatgpt-business-overview ; https://openai.com/policies/row-terms-of-use/ (SE); [sibling: tool_openai_google.md] | Nov 2026 | verified_primary (SE) |
| 8 | Google AI Pro costs $19.99 (EUR 21.99); Ultra costs $99.99 or $199.99 (20x AI Pro). Ukraine is on the eligibility lists for both. Gemini CLI consumer login ended on 18 Jun 2026. | https://gemini.google/subscriptions/ ; https://support.google.com/googleone/answer/16476811 (SE); [sibling: tool_openai_google.md] | Nov 2026 | verified_primary (SE) |
| 9 | Chinese coding plans are the cheapest flat dev capacity: GLM Coding Plan Lite $12.6, Pro $56, Max $117.6 (promo prices, credit-based, single individual, "benefits may be restricted" via SDK-based or unsupported tools). Alibaba's Qwen Coding Plan Pro is $50/month for 6,000 requests per 5 hours and 90,000 per month. | https://z.ai/subscribe ; https://docs.z.ai/devpack/overview ; https://www.alibabacloud.com/help/en/model-studio/coding-plan (SE) | Nov 2026 | verified_primary (SE) |
| 10 | Agentic coding uses about 3,500x more tokens than a single-round reasoning task. Input and cache reads dominate cost even with caching on. Token use on the same task varies up to 30x between runs. A full task spec instead of a prose description cuts spend 29.7% and raises success 16.4%. | https://arxiv.org/html/2604.22750v3 ; https://arxiv.org/pdf/2608.25399 (SE) | 2026 | reported_secondary |
| 11 | Anthropic's benchmark for Claude Code: about $13 per developer per active day, $150-250 per developer per month, and 90% of users under $30 per active day (enterprise API billing). | https://code.claude.com/docs/en/costs (SE) | Nov 2026 | vendor_claim |
| 12 | Media is paid-only at API level: Veo 3.1 costs $0.40/s, Fast $0.10-0.12/s, Lite $0.05/s; Sora's API was discontinued on 24 Sep 2026; Lyria 3.5 costs $0.08 per full song and Lyria 3 $0.04 per 30-s clip, with no free tier; Google Cloud TTS costs $4-30 per 1M characters (Standard to Chirp 3 HD); OpenAI tts-1 costs $15 per 1M characters. | https://ai.google.dev/gemini-api/docs/pricing ; https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing (SE); [sibling: biz_content_farm.md]; https://www.assemblyai.com/blog/tts-api-pricing (SE) | Nov 2026 | verified_primary (Google); reported_secondary (TTS aggregators) |
| 13 | Render charges a workspace fee (Hobby $0 / Pro $25 / Scale $499) plus compute: Starter $7 (512 MB), Standard $25 (1 CPU / 2 GB), disk $0.25/GB-month. The FactoryOS blueprint (0.5c-512mb + 1 GB, 1c-2g + 5 GB) therefore costs about $33.50/month before any workspace fee. | https://render.com/pricing (SE); `render.yaml:12,81,87,112` | Nov 2026 | verified_primary (SE) + inference (mapping) |
| 14 | AWS: accounts created on or after 15 Jul 2025 get $100 + up to $100 in credits, and the free plan ends after 6 months or when credits run out. The t4g.small free trial (750 h/month) ends on 31 Dec 2026, with automatic on-demand billing from 1 Jan 2027. t3.micro on-demand costs $0.0104/h (about $7.6/month). | https://aws.amazon.com/free/ ; https://aws.amazon.com/ec2/faqs/ ; https://aws.amazon.com/ec2/instance-types/t3/ (SE) | pages updated Nov 2026 | verified_primary (SE) |
| 15 | With caching, one agent turn (60K context, 1.5K output) costs about $0.0015 on Haiku 5.5 or GPT-6 Luna, about $0.025 on Sonnet 5.5 or GPT-6.2 Sol, and about $0.05 on Opus 5.5. A 24/7 loop at 1 turn/minute therefore costs about $65, $1,100 or $2,200 per month. Without caching Sonnet costs about 5x more. | computed from rows 1-2 | 18 Nov 2026 | inference |

---

## 1. LLM API prices (Nov 2026)

### Closed frontier and cheap tiers (USD per 1M tokens)

| Vendor / model | Input | Cached input | Output | Batch | Notes / source |
|---|---|---|---|---|---|
| Anthropic Opus 5.5 | 4.00 | 0.20 read; write 5.00 (5 min) / 8.00 (1 h) | 20.00 | 2 / 10 | [SE](https://platform.claude.com/docs/en/models/opus-5-5/overview); skill. Thinking cannot be disabled (default effort `medium`); thinking is billed as output |
| Anthropic Sonnet 5.5 | 2.00 | 0.10 read; write 2.50 / 4.00 | 10.00 | 1 / 5 (50%) | [SE](https://platform.claude.com/docs/en/models/sonnet-5-5/overview) |
| Anthropic Haiku 5.5 (<=100K prompt) | 0.10 | 0.01 read; write 0.125 / 0.20 | 0.50 | 0.05 / 0.25 | [SE](https://platform.claude.com/docs/en/models/haiku-5-5/overview); >100K prompt: 0.50 / 2.50 |
| Anthropic Fable 5.2 (top tier) | 8.00 | 0.20 | 40.00 | 4 / 20 | skill `shared/models.md` |
| OpenAI GPT-6.2 Astra | 8.00 | 0.40 (write 10.00) | 40.00 | 50% | [SE](https://developers.openai.com/api/docs/models/gpt-6.2-astra); >272K input: 2x in, 1.5x out |
| OpenAI GPT-6.2 Sol | 2.00 | 0.10 (30-min retention) | 10.00 | 50% | [SE](https://developers.openai.com/api/docs/models/gpt-6.2-sol). The sibling note quoted GPT-6.1 Sol at $0.20 cached, which is the previous version |
| OpenAI GPT-6.1 Terra | 1.00 | 0.05 | 5.00 | 0.50 / 2.50 | [SE launch post](https://openai.com/index/introducing-gpt-6-1-terra/); the pricing page labels the half-price tier "Flex" in one version and "Batch" in another |
| OpenAI GPT-6 Luna | 0.10 | 0.01 | 0.50 | 0.05 / 0.25 | [SE model page](https://developers.openai.com/api/docs/models/gpt-6-luna.md) |
| Google Gemini 3.8 Flash | 0.75 (to 31 Dec) -> 1.50 | not found | 3.75 -> 7.50 | 0.375/1.875 -> 0.75/3.75 | [SE](https://ai.google.dev/gemini-api/docs/whats-new-gemini-3.8); same intro price on Vertex ([SE](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing)) |
| Google Gemini 3.5 Flash-Lite | 0.30 | not found | 2.50 | lower | [SE](https://ai.google.dev/gemini-api/docs/pricing); free tier "free of charge" |
| Google Gemini 3.1 Flash-Lite | 0.25 | not found | 1.50 | lower | [SE](https://ai.google.dev/gemini-api/docs/pricing) |
| Google Gemini 4 Argon | $2 / $10 until 30 Nov 2026, then $4 / $20 | | | | [sibling: tool_openai_google.md, search summary]. **Not confirmed in this session**: my search on ai.google.dev returned no Argon price. The subscription page names "Gemini 4 Argon", so the model exists ([SE](https://gemini.google/subscriptions/)) |

- Other Anthropic levers: fast mode on Opus 5.5 costs 2x ($8 / $40). Managed Agents adds $0.08 per running session-hour [sibling: tool_claude_code.md].
- The Gemini API tier table is based on spend. The Free tier has no spend figure, and Tier 1 is listed at "$10 per 10 minutes". New accounts start on the Free tier ([SE rate limits](https://ai.google.dev/gemini-api/docs/rate-limits); [SE billing](https://ai.google.dev/gemini-api/docs/billing)). Free-tier Google Search grounding is 500 requests/day, shared across Flash and Flash-Lite (SE pricing page).
- Gemini free-tier request limits are **reported by users, not official**: about 20 RPD on 3.8 Flash and about 500 RPD on Flash-Lite ([forum, anecdotal](https://discuss.ai.google.dev/t/gemini-3-8-flash-free-tier-20-rpd-is-too-limited-for-practical-evaluation/180609)). Another forum thread is titled "a 92% free tier quota" cut ([forum](https://discuss.ai.google.dev/t/do-they-really-think-we-wouldnt-notice-a-92-free-tier-quota/111262)). Free-tier prompts may be used to improve Google products (`DECISIONS.md:951`; [sibling: tool_openai_google.md]).
- FactoryOS evidence: one free Gemini key backs at least six features and returned 429 three days in a row [sibling: repo_state_evidence.md §6 / key insight 7].

### Open-weight models (via OpenRouter; indicative, Jun-Oct 2026 pages)
- DeepSeek V4 Flash costs $0.054 / $0.242 on OpenRouter and $0.14 / $0.28 on DeepSeek's own API. V4.1 Flash is about $0.05 / $0.20 at a discount. V4 Pro costs $1.06-1.12 / $3.17-3.37 ([SE OpenRouter June 2026](https://openrouter.ai/blog/insights/the-open-weight-models-that-matter-june-2026/); [SE discounted](https://openrouter.ai/collections/discounted-models)).
- Qwen3.6 Plus costs $0.325 / $1.95. A 1M-context Qwen costs $0.15 / $0.47. Qwen3.8 27B costs about $0.45 / $3.00-3.20 on some hosts ([SE](https://openrouter.ai/qwen)).
- Kimi K3 input ranges from $0.24 to $4.50 across about 20 providers. Kimi K2.6 is discounted to $0.39 / $1.64 (SE OpenRouter).
- GLM 5.2 averages $0.447 / $3.31 (weighted). GLM 5.1 costs $0.90 / $2.90 on one host. GLM-5.3-flash input ranges from $0.04 to $1.15 (SE OpenRouter).
- Not verified: Together, Fireworks, Groq and DeepInfra list prices, and the current OpenRouter ":free" model quotas. Fetch was blocked and the search budget was spent on higher-priority facts.
- Inference: open-weight output prices ($0.24-3.40) overlap with Haiku 5.5 / GPT-6 Luna ($0.50). The cheap closed tiers have **cheaper cached input** ($0.01) than many open-weight hosts list for uncached input. Example: GLM 5.2 uncached at a 60K context costs about $0.03 per turn, more than Sonnet 5.5 with caching. **Price per token is not price per turn; caching support decides.**

## 2. Subscriptions and what their terms say about unattended use

| Plan | Price | Limits (as published) | Automation / third-party harness |
|---|---|---|---|
| Claude Pro | $20 ($17/month billed annually) [sibling: tool_claude_code.md, SE claude.com/pricing] | 5-hour session limit plus a weekly limit, shared by the Claude apps and Claude Code. On 6 May 2026 Anthropic doubled Claude Code's 5-hour limits and removed the peak-hours cut ([SE](https://www.anthropic.com/news/higher-limits-spacex)) | **Owner's own Claude Code headless (`claude -p`, Agent SDK): permitted.** It draws from plan limits ([sibling: tool_openclaw.md, support article 15036540]). **Third-party harness or serving other users: prohibited.** Plan credentials may not be routed "on behalf of their users", and enforcement can come "without prior notice" ([code.claude.com legal](https://code.claude.com/docs/en/legal-and-compliance), sibling-verified). Consumer terms ban bots and scripts unless explicitly permitted ([SE consumer terms PDF](https://assets.claude.com/43c13f51a6d9755341433f79cf63c966ed9200ea.pdf)) |
| Claude Max | $100 (web) ([SE](https://support.claude.com/en/articles/11049741-what-is-the-max-plan)) | 5x Pro; 5-hour, weekly and separate weekly Fable limits; "we may limit your usage in other ways … at our discretion" | Same rules as Pro. **Includes $100/month of API credits** for the Claude API, Managed Agents and Agent SDK used with an API key from the linked Console org. The credits do not cover interactive Claude Code or extra usage ([SE](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans); [SE docs](https://platform.claude.com/docs/en/about-claude/api-credits-for-subscribers)). API-key use falls under the Commercial Terms, which permit product use |
| Claude Ultra | $200, monthly only | 10x Pro weekly; **no 5-hour limit for verified accounts**; Fable capped at 50% of weekly usage | $200/month API credit [sibling: tool_claude_code.md] |
| ChatGPT Plus | $20 ([SE](https://learn.chatgpt.com/docs/pricing)) | Codex: about 15-160 Sol-class / 5-45 Astra-class / 350-3,000 Luna-class messages per 5 hours; weekly limits are also reported [sibling: tool_openai_google.md] | **Codex CLI with ChatGPT sign-in, including non-interactive `codex exec`: officially supported.** The Codex GitHub Action needs an API key [sibling]. Consumer ToU ban "automatic or programmatic extraction of data or Output" ([SE](https://openai.com/policies/row-terms-of-use/)), so driving the ChatGPT web UI by script is prohibited. The repo already records that "a ChatGPT subscription gives no programmatic access" outside Codex (`DECISIONS.md:946`) |
| ChatGPT Pro | $100 / $200 / $500 (the $500 tier adds "Ultrafast"). An older openai.com page still shows a single $200 tier ([SE](https://learn.chatgpt.com/docs/pricing)) | Pro had "no five-hour limit" per sibling | as Plus |
| ChatGPT Business | $25 per seat monthly / $20 annual, minimum 2 seats. Premium seat $125 / $100 with no 5-hour limit ([SE](https://help.openai.com/en/articles/8792828-chatgpt-business-overview)) | | Business Terms (commercial) |
| Google AI Pro / Ultra | $19.99 (EUR 21.99) / $99.99 or $199.99. **Ukraine is eligible** ([SE](https://gemini.google/subscriptions/); [SE](https://support.google.com/googleone/answer/16476811)) | Jules free: 15 tasks per 24 h; Pro 100; Ultra 300 [sibling] | **Gemini CLI consumer login ended 18 Jun 2026.** Google treats "Gemini CLI OAuth with third-party software" as policy-violating, and Antigravity terms prohibit third-party tools [sibling: tool_openai_google.md, tool_openclaw.md]. The sanctioned automation path is an API key |
| GLM Coding Plan (Z.ai) | Lite $12.6 (list $18), Pro $56 ($80), Max $117.6 ([SE](https://z.ai/subscribe)) | Credits: Lite 2,000 per 5 h / 10,000 per week; Pro 12,000 / 60,000; off-peak usage is cheaper ([SE](https://docs.z.ai/devpack/overview)) | Single account, single individual. "Benefits may be restricted" through unsupported tools such as SDK-based access ([SE](https://docs.z.ai/devpack/faq)). **Tolerated inside supported coding tools only; not for product traffic** |
| Qwen Coding Plan (Alibaba Model Studio) | Pro $50; Lite about $8-10 (secondary sources conflict) | Pro: 6,000 requests per 5 h, 45,000 per week, 90,000 per month. Lite: about 1,200 per 5 h. Includes Qwen, GLM, Kimi and MiniMax models ([SE](https://www.alibabacloud.com/help/en/model-studio/coding-plan)) | Terms not read |
| Kimi Code | Bundled in a Kimi membership: about $19 / $39 / $99 / $199 (secondary) | 5-hour and weekly caps not published ([SE comparison, secondary](https://www.codeagentswarm.com/en/guides/kimi-code-plans-and-pricing)) | Not verified |

**Classification (inference from the terms above):**
- **Allowed:** an API key on any vendor; Codex CLI on a ChatGPT plan for the owner's own development; the owner's own Claude Code / `claude -p` on the owner's own machine within plan limits; the Gemini API free key, accepting that Google may train on the data.
- **Tolerated but fragile:** running Claude Code unattended for long periods on EC2. It is technically sanctioned, but the plan "assumes ordinary, individual usage", is capped every 5 hours and weekly, and Anthropic reserves discretionary caps. The repo records `usage_limit_reached` holds (`ROADMAP.md:125`). GLM and Qwen plans in their supported coding tools also fall here.
- **Prohibited:** third-party harnesses on Claude or Google consumer credentials; serving public users from a personal subscription (the repo already decided against it in `DECISIONS.md:951`); scripting the ChatGPT or Claude web UIs.

## 3. Token consumption of agentic workloads (measured where possible)
- Agentic coding tasks use about 3,500x more tokens than a single-round reasoning task and 1,200x more than multi-round chat. Input tokens, and specifically **cache reads, dominate raw volume and dollars** even with caching. Runs on the same task differ by up to 30x, and more tokens do not mean higher accuracy ([SE arXiv 2604.22750, Microsoft Research](https://arxiv.org/html/2604.22750v3)).
- On SWE-bench Verified, cutting a full spec down to a prose description raises token spend 29.7% and lowers success by 16.4%. Rerunning an identical spec gives a 1.34x spread ([SE arXiv 2608.25399](https://arxiv.org/pdf/2608.25399)).
- Claude Code enterprise average: about $13 per developer per active day, $150-250 per month, 90% under $30 per active day ([SE](https://code.claude.com/docs/en/costs); vendor figure). This is human-paced use, not 24/7.
- Cost per *resolved* SWE-bench task ranges from about $0.03 (DeepSeek V3.2) to $0.68 (Opus 4.5) in a commercial ranking, about 24x apart ([SE secondary](https://securityboulevard.com/2026/06/8-ai-coding-models-ranked-by-cost-per-task/)). These are older models and the vendor blog is not verified.
- Artificial Analysis reports per-task cost since June 2026 (index v4.1, 9 evaluations). Examples range from about $0.31 to $2.01 per index task across current models at similar scores ([SE](https://artificialanalysis.ai/articles/artificial-analysis-intelligence-index-v4-1)). These are tweet-level figures and partly conflicting.
- Always-on assistant: OpenClaw's default "proactive check" runs every 30 minutes. User-reported running cost is $5-15/month for light use on a cheap model, $300-600 for heavy use, and runaway outliers above $3,600 [sibling: tool_openclaw.md, anecdotal].
- FactoryOS's own measured paid usage is a single fenced pilot at $0.188066 (`README.md:293` via [sibling: repo_state_evidence.md]). **No per-task token logs exist, so all FactoryOS figures below are modelled.**
- Browser-agent token cost per step was not found (gap). Inference: screenshot-based steps add image tokens on every turn, so the DOM/text "Surfer" mode should be the default.

### Unit-cost model (inference; list prices; my assumptions)
Turn = 60K-token prompt (58K cache read + 2K cache write) + 1.5K output including thinking. Task = 15 turns. This is the same unit as [sibling: tool_claude_code.md] so the reports agree.

| Model | $/turn cached | $/15-turn task | 24/7 at 1 turn/min (43.2k turns/mo) | Heartbeat every 30 min (1.44k turns/mo) |
|---|---|---|---|---|
| Haiku 5.5 / GPT-6 Luna | ~0.0015 | ~0.023 | ~$65-70 | ~$2 |
| DeepSeek V4 Flash (OpenRouter, uncached) | ~0.0036 | ~0.054 | ~$155 | ~$5 |
| GPT-6.1 Terra | ~0.012 | ~0.19 | ~$535 | ~$18 |
| Gemini 3.8 Flash, uncached (cache price unknown), intro price | ~0.051 (about 0.10 from Jan 2027) | ~0.77 | ~$2,200 | ~$73 |
| Sonnet 5.5 / GPT-6.2 Sol | ~0.025 | ~0.38 | ~$1,100 | ~$37 |
| Opus 5.5 | ~0.052 | ~0.78 | ~$2,240 | ~$75 |
| GPT-6.2 Astra | ~0.10 | ~1.55 | ~$4,450 | ~$150 |
| Sonnet 5.5 **uncached** | ~0.135 | ~2.0 | ~$5,800 | ~$195 |
| Routed 80% Haiku / 20% Sonnet | ~0.0064 | ~0.10 | ~$275 | ~$9 |

Levers, ranked by effect (inference, consistent with the skill's cost guide, `shared/cost-optimization.md`):
1. Do not loop; trigger on events. Going from a 1-turn/min loop to a 30-min heartbeat cuts cost 30x.
2. Prompt caching: about 5x on Sonnet.
3. Routing routine steps to a cheap tier: about 4x.
4. Batch API for anything nobody waits on: 2x.
5. Better task specs: about 30% (arXiv).

The variance of 1.34x to 30x per task means budget caps must be enforced per task, not estimated.

## 4. Media generation prices
- **Video:** Veo 3.1 costs $0.40/s at 720p/1080p and $0.60/s at 4K. Veo 3.1 Fast costs $0.10/s at 720p and $0.12/s at 1080p. Veo 3.1 Lite costs $0.05/s at 720p. There is no free Veo API tier [sibling: biz_content_farm.md, Google Cloud pricing]. My own search could not re-confirm the Lite price on ai.google.dev. The **Sora API was discontinued on 24 Sep 2026** [sibling: OpenAI Help]. Kling 3.0 costs $0.084-0.168/s (secondary). Runway Gen-4.5 costs about $0.12/s (secondary). A 45-s Short costs $2.25 (Lite) to $18 (Veo 3.1) before retakes [sibling].
- **Images:** Nano Banana 2 costs about $0.067 per 1K image, Nano Banana 2 Lite about $0.034, and Nano Banana Pro $0.134-0.24. There is no free API tier [sibling: biz_content_farm.md].
- **Music:** Lyria 3.5 full song costs $0.08 on the paid tier, with no free tier. Lyria 3 30-s clip costs $0.04. Lyria 2 costs $0.06 per 30 s on Vertex ([SE](https://ai.google.dev/gemini-api/docs/pricing); [SE](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/lyria/lyria-002)).
- **TTS** (mostly secondary aggregators; Nov 2026):
  - OpenAI tts-1 costs $15 per 1M characters and tts-1-hd $30; tts-1 is being phased out. gpt-4o-mini-tts costs $0.60 per 1M text tokens + $12 per 1M audio tokens, about $0.015 per minute ([SE](https://www.assemblyai.com/blog/tts-api-pricing); [SE](https://costgoat.com/pricing/openai-tts)).
  - ElevenLabs API costs $40-80 per 1M characters by model. Sources conflict, up to $120-180.
  - Google Cloud TTS costs $4 (Standard), $16 (Neural2), $30 (Chirp 3 HD) and $160 (Studio) per 1M characters.
  - Gemini TTS is token-priced: about $0.50 in and $9-10 out per 1M tokens.
  - Gemini 3.8 Flash-Lite TTS pricing changes on 1 Jan 2027: free-tier use is free through 31 Dec 2026 and paid rates roughly double after that ([SE](https://ai.google.dev/gemini-api/docs/pricing)).
  - The ElevenLabs Free plan has no commercial licence. Starter costs $6 for 30k credits [sibling].
- **MyCast unit cost (inference):** a 10-minute episode is about 1,500 words, or about 9,000 characters.
  - TTS: about $0.04 on Cloud TTS Standard, $0.14 on Neural2 or tts-1, $0.27 on Chirp 3 HD, and $0.36-0.72 on ElevenLabs.
  - Script: on Sonnet 5.5, about 10K in + 3K out costs about $0.05; on Haiku 5.5, about $0.003.
  - **Total: about $0.05-0.75 per episode.** 100 episodes a month cost $5-75.
  - The current zero-spend path (Gemini free TTS with Piper fallback) works, but a 429 already degrades it (`DECISIONS.md:674`).

## 5. Hosting (context only)
- **Render:**
  - Workspace: Hobby $0, Pro $25, Scale $499 per month, plus compute.
  - Compute: Starter $7 (512 MB); Standard $25 (1 CPU, 2 GB). Workers have no free tier.
  - Storage: disk $0.25/GB-month. Postgres storage $0.30/GB-month, compute from about $6-7 (sources conflict).
  - All from [SE](https://render.com/pricing) and Render articles ([SE](https://render.com/articles/fastapi-hosting-cost)).
- **The FactoryOS blueprint** runs `0.5c-512mb` + 1 GB disk and the `1c-2g` Media Finisher + 5 GB disk (`render.yaml:12,81,87,112`). If both run 24/7 that is about $7 + $25 + $1.50 = **$33.50/month**, plus $25 if on a Pro workspace (inference: plan labels mapped to Starter/Standard by size). The Media Finisher alone is about 75% of that. Suspending it when idle is the cheapest saving available.
- **AWS:**
  - New accounts (on or after 15 Jul 2025) get $100 in credits, plus up to $100 more for activities. The free plan ends after 6 months or when credits run out ([SE](https://aws.amazon.com/free/); [SE blog](https://aws.amazon.com/blogs/aws/aws-free-tier-update-new-customers-can-get-started-and-explore-aws-with-up-to-200-in-credits/)).
  - Eligible instances include t3.micro/small, t4g.micro/small and the m7i/c7i-flex.large. The **t4g.small trial (750 h/month) ends 31 Dec 2026**, and those instances switch to On-Demand automatically on 1 Jan 2027 ([SE](https://aws.amazon.com/ec2/faqs/)).
  - t3.micro costs $0.0104/h, about $7.6/month ([SE](https://aws.amazon.com/ec2/instance-types/t3/)). I did not verify a t4g.small hourly price.
  - The repo shows the EC2 host has about 910 MB RAM shared with the worker (`DECISIONS.md:658`), so it is micro class. **Its free-tier status is unknown, which is a hidden cost cliff.**
- **Alternatives** (weak evidence):
  - Oracle Always Free A1: several 2026 posts say it was cut from 4 OCPU / 24 GB to 2 OCPU / 12 GB in June 2026, which is unconfirmed by Oracle ([SE secondary](https://terminalbytes.com/oracle-cloud-free-tier-changes-2026)).
  - Hetzner CAX31 went from EUR 11.99 to 15.99 from April 2026 ([SE secondary](https://www.bitdoze.com/hetzner-oracle-arm-performance/)). CX22 and CAX11 prices are not verified.
  - Fly.io and Railway were not researched.
- GitHub Actions: the 2,000 free minutes were exhausted by 8 Nov 2026, and a $5 budget burned in two days (`DECISIONS.md:828-829, 1133-1135` via [sibling: repo_state_evidence.md]).

## 6. Three budget scenarios (inference built on the facts above)

**Assumptions:**
- "Task" = 15 cached turns, as in §3.
- Owner time is not costed.
- Prices are list prices for Nov 2026, with the Jan 2027 Google increases noted.
- The founder already pays for a Claude plan and ChatGPT Plus.
- **The repo is inconsistent on the Claude plan:** Oct 2026 decisions say "Pro" (`DECISIONS.md:24-35`, `ROADMAP.md:263`), while the 2026-11-11 entry says "Claude's $100 subscription" (`DECISIONS.md:951`), i.e. Max.

### A. Zero additional spend ($0 new money; existing fixed costs: Claude plan $20 or $100, ChatGPT Plus $20, Render about $33-58)
- **What it buys:**
  - Development capacity: one owner-attended Claude Code lane within 5-hour/weekly caps; Codex on Plus (about 15-160 Sol-class messages per 5 h); Jules free (15 tasks per day, 3 concurrent).
  - Roughly 5-20 bounded coding tasks per day across all lanes on good days, with stalls at limits. This is a range inferred from the caps; real throughput was 43 worker commits in 4 days and then stalls [sibling: repo_state_evidence.md].
  - Product LLM calls: Gemini free tier only (about 20-500 RPD depending on model, per forum reports), already failing with 429s.
  - Media: Gemini free TTS plus local Piper; **no** video, image or music API.
  - **If the owner is on Max, the $100/month API credit is already-paid capacity:** about 65k Haiku turns or about 4k Sonnet turns a month for product-side calls under the Commercial Terms. Run it with a hard $0-overage limit in the Console. This must be verified before it is counted.
- **Impossible:**
  - A true 24/7 unattended frontier agent: weekly caps, plus the terms' "ordinary, individual usage".
  - Serving public users from a subscription.
  - Any reliability guarantee.
  - Paid media.
  - Scaling past free RPD.
  - CI beyond the free minutes.
- **Hidden cliffs:**
  - EC2 free plan or t4g.small trial expiry (31 Dec 2026, or 6 months after account creation).
  - Gemini 3.8 Flash and Flash-Lite TTS price changes on 1 Jan 2027.
  - Free-tier quota cuts without notice (forum "92%" thread).

### B. About $100/month
- **Option B1 (recommended if spend is approved): capped metered API for the product path.**
  - Spend: about $60-80 on cheap-tier API (Haiku 5.5 / GPT-6 Luna / Flash-Lite, with Sonnet or Sol for about 20% of hard steps), plus $20-40 on media (TTS, a few images or songs).
  - LLM capacity at about $0.0064 per routed turn and $70: about 11k turns, which is about 700 tasks a month or **about 25 tasks per day**. All-Haiku: about 45k turns. All-Sonnet: about 2.8k turns, or about 6 tasks per day.
  - Media at $30: about 100-200 MyCast episodes; or about 450 images; or about 13 Veo-Lite 45-s Shorts; or 375 Lyria songs.
- **Option B2: subscription upgrade.**
  - Pro to Max costs +$80 for 5x interactive capacity plus $100 of API credits, so the API credit alone covers the upgrade.
  - The value exists only if the owner is on Pro now.
  - Alternatively GLM Lite at $12.6 or Qwen Lite at about $10 as a third dev lane (supported tools only; Chinese provider; quality not evaluated here).
- **Still impossible:**
  - A frontier model looping 24/7: about $1,100/month on Sonnet.
  - Daily generated video at Veo standard: about $540/month for one 45-s Short a day.
  - Anything unattended that publishes: the approval gate is a policy, not a cost.
- **Marginal value of the first paid dollars:**
  - Highest: about $10-30 to make the **user-facing** path (MyCast subtopics and TTS, MyBrief) stop failing on free-tier 429s. That converts a broken demo into a testable product.
  - Lowest: more agent hours. The repo shows 98 tasks done and 0 customer-side outcomes [sibling: repo_state_evidence.md], so build capacity is not the bottleneck.

### C. About $500/month
- **Example mix:**
  - Claude Ultra $200: no 5-hour cap for verified accounts, 10x Pro weekly, $200 API credit.
  - About $150 metered API.
  - About $100 media.
  - About $50 hosting and CI buffer, for example a GitHub Actions budget or a second EC2 small instance after the free-tier cliff.
- **Capacity:**
  - About $350 of effective API (including the credit) at routed prices: about 55k turns, which is about 3,600 tasks a month or **about 120 per day**. With Sonnet only: about 14k turns, about 30 tasks per day.
  - Dev lane: near-continuous within the weekly cap.
  - Media at $100: about 300-700 podcast episodes; or about 1,500 images; or about 44 Veo-Lite Shorts; or 11 Veo-Fast 90-s videos a week.
- **Still impossible:**
  - A frontier-model 24/7 loop on Opus (about $2,200).
  - Daily full-quality generated video.
  - Unlimited Ultra: a weekly cap and discretionary caps remain.
- **Justified only after** a measured signal, i.e. paying users or a conversion rate. At zero revenue, spending $500 buys output volume, not evidence of demand.

## 7. Model selection and evaluation practice (quality per dollar)
- **Public leaderboards are a coarse filter.**
  - Artificial Analysis index v4.1 has 9 evaluations, including GDPval-AA v2 and Terminal-Bench v2.1. It publishes cost to run and, since June 2026, per-task cost, time and output tokens ([SE](https://artificialanalysis.ai/articles/artificial-analysis-intelligence-index-v4-1)).
  - Harness changes can swing coding scores by 22 or more points (secondary FAQ, [SE](https://www.morphllm.com/best-ai-coding-agents-2026)).
  - Cost does not track accuracy ([SE arXiv 2604.22750](https://arxiv.org/html/2604.22750v3); [SE harness study arXiv 2609.20804](https://arxiv.org/pdf/2609.20804)).
- **A private eval is decisive and cheap.** Inference, plus the skill's cost guide:
  - Take 20-50 real FactoryOS tasks: Relay tickets, MyCast scripts, Surfer extractions.
  - Use fixed specs and an automatic grader: tests, or schema plus an LLM judge on a cheap tier.
  - Run each candidate 3-5 times, because variance is 1.34-30x per task. The published bar for a production cutover is about 50 cases and at least 5 trials.
  - Score **cost per completed task** and latency, not $/token.
  - Run evals through the Batch API at 50% off.
  - Run open-weight candidates through one OpenRouter key.
  - Re-run monthly or when a model or price changes. Google doubles prices on 1 Jan 2027, and Sol 6.1 to 6.2 changed cached-input price.
  - Estimated cost per eval sweep: 50 tasks x 5 trials x 4 models x $0.02-0.40 per task, about $20-400. On cheap tiers alone it is **under $10**.
- **Try lower effort before routing.** Before building a multi-model cascade, try the strongest model at lower effort. The skill guide says newer models at lower effort often match older ones at high effort, and one model keeps one cache namespace (vendor guidance, Anthropic skill).

## Counter-evidence and caveats
- **Unconfirmed model names and prices.** Many November 2026 model names (GPT-6.x Sol/Terra/Luna/Astra, Gemini 3.8 / 4 Argon, Claude 5.5 family) post-date my training, so I could not check them against memory. Anthropic's are corroborated by the skill table; the others rest on search extracts of official pages. I found no Gemini 4 Argon API price myself.
- **Prices move both ways.** Google is doubling Gemini 3.8 Flash and Flash-Lite TTS prices on 1 Jan 2027, Sora disappeared, and free-tier quotas were cut in 2026. A cost model has a shelf life of weeks.
- **Subscription value is opaque.** Anthropic, OpenAI and Kimi do not publish absolute 5-hour or weekly token numbers, and the Claude Max/Ultra tier pages conflict: an older "Max 20x $200" versus the current "Ultra $200". "Subscription as worker" capacity therefore cannot be modelled precisely, and vendors reserve discretionary caps.
- **The Max API credit is not verified end to end.** Its existence comes from two official support/docs pages (search extract). Activation, expiry and overage behaviour are not verified. Do not count it until it shows in the Console.
- **Open-weight savings are overstated by list prices.** Uncached long-context turns on "cheap" open models can cost more than cached Haiku or Sonnet turns. Provider quality, quantisation and uptime vary, and a coding plan's terms restrict SDK and product use.
- **Token measurements are dominated by coding benchmarks.** I found no cited measurement for browser-agent or research-agent tokens per task, or for an always-on assistant beyond user anecdotes.
- **The Claude Code $13/day figure is a vendor average** from enterprise deployments of human-paced use. It is not a 24/7 agent and not a solo founder.
- **Counter-argument to "spend nothing":** zero spend already costs reliability (three days of 429s, CI minutes exhausted, worker stalls at usage limits) and owner attention, which is the scarcest resource. A capped $10-30 on the user-facing path may have higher ROI than any further zero-cost engineering.
- **Counter-argument to "spend $500":** at zero customers, the incremental output (more tasks, more media) has no measured revenue path. YouTube Shorts RPM is $0.02-1.48 per 1,000 views [sibling: biz_content_farm.md], so generated video cannot repay $2-18 per Short without large audiences.

## Implications for FactoryOS
1. **Settle the facts that change the budget before anything else (cost: $0).**
   - (a) Is the Claude plan Pro or Max? If Max, check whether the $100/month API credit is in the Console and set a $0 overage cap. It would be the cleanest legal source of product-side LLM calls at zero additional spend.
   - (b) EC2 account age, instance type and free-plan expiry, before 31 Dec 2026.
   - (c) The real Render invoice: workspace tier, and whether the Media Finisher runs 24/7.
2. **Do not build a 24/7 frontier loop.** Make agents event-driven: Relay tickets, owner messages, schedules. Use a Haiku 5.5 / Luna-class heartbeat at most, which costs $2-5/month even if paid. Loop design matters more than model choice: a 30x difference.
3. **Keep subscriptions for owner-led development only:** Claude Code on EC2 within caps and Codex on Plus. Never put subscription credentials into third-party harnesses or public-facing features. Google consumer OAuth is closed, so treat the Gemini lane as API-key-only.
4. **The first approved dollars should buy reliability of the user-facing path, not agent hours.**
   - Ask for a capped $10-30/month "product API" envelope: Haiku 5.5 or GPT-6 Luna for text, Cloud TTS Standard/Neural2 or tts-1 for MyCast.
   - Enforce it with the existing fail-closed spending guard, idempotency fences and per-feature daily caps.
   - Turn it on only when a real external test, such as a public MyCast beta link, is live.
5. **Require caching and batching** in every metered path: a stable prefix, 5-minute cache, Batch API for nightly MyBrief/MyCast generation. With these, $100/month buys about 25 routed tasks per day. Without them, about 6.
6. **Media: price per unit before building pipelines.**
   - Podcast audio costs $0.05-0.75 per episode, viable.
   - Generated video costs $2-18 per Short, not viable at Shorts RPM.
   - Lyria music costs $0.04-0.08 per track, cheap but legally untested.
   - Prefer audio products (MyCast) over video for unit economics.
7. **Establish a private eval before any model switch.** Build 30-50 FactoryOS tasks with automatic graders and 3-5 trials, measuring cost per completed task, monthly or on any price change. The budget is under $10 per sweep on cheap tiers.
8. **Budget ladder (opinionated):**
   - $0 now.
   - Then about $30/month when one product is in front of real users.
   - Then about $100/month only after a measured conversion signal, for example 10+ weekly active listeners, or anyone paying.
   - About $500/month only against revenue.
   - Track views, subscribers, leads, revenue and net profit separately. None is non-zero today.

## Sources
**Pages opened in full: none.** WebFetch to non-GitHub hosts is blocked by the session proxy. Every web URL cited inline above (marked SE) was read only as a **search extract** of that URL in WebSearch, run 18 Nov 2026 with `allowed_domains` set to the vendor's domain where possible. Secondary or anecdotal sources are labelled inline. The URLs, grouped by vendor:
- Anthropic: platform.claude.com model pages (opus-5-5, sonnet-5-5, haiku-5-5), claude.com/pricing, support.claude.com articles 11049741 and 17154008, platform.claude.com/docs/en/about-claude/api-credits-for-subscribers, anthropic.com/news/higher-limits-spacex, the consumer terms PDF at assets.claude.com, code.claude.com/docs/en/costs.
- OpenAI: developers.openai.com model pages (gpt-6.2-sol, gpt-6.2-astra, gpt-6-luna) and /api/docs/pricing, openai.com/index/introducing-gpt-6-1-terra/, help.openai.com rate card 20001415 and Business overview 8792828, learn.chatgpt.com/docs/pricing, openai.com/policies/row-terms-of-use/.
- Google: ai.google.dev pricing, rate-limits, billing and whats-new-gemini-3.8 pages; blog.google 3.8 Flash post; cloud.google.com Agent Platform pricing; Lyria 2 docs; gemini.google/subscriptions; support.google.com/googleone 16476811; two discuss.ai.google.dev forum threads (anecdotal).
- Open-weight models and coding plans: openrouter.ai (June 2026 open-weight post, discounted collection, /qwen); z.ai/subscribe; docs.z.ai devpack overview and FAQ; alibabacloud.com Model Studio coding plan; codeagentswarm.com (secondary).
- Research and evals: arxiv 2604.22750, 2608.25399 and 2609.20804; artificialanalysis.ai index v4.1 article; securityboulevard.com and morphllm.com (secondary).
- Media and TTS: assemblyai.com and costgoat.com TTS pricing (secondary).
- Hosting: render.com/pricing and the Render FastAPI cost article; aws.amazon.com/free, the EC2 FAQs, the T3 page and the AWS free-tier blog post; terminalbytes.com and bitdoze.com (secondary).

**Local files read:**
- `render.yaml`
- `DECISIONS.md`, lines about 24-35, 658-685 and 946-951
- `ROADMAP.md`, lines 27, 125 and 263
- claude-api skill: `SKILL.md`, `shared/models.md`, `shared/prompt-caching.md`, `shared/cost-optimization.md`
- Sibling notes in this folder: `tool_openai_google.md`, `tool_openclaw.md`, `tool_claude_code.md`, `biz_content_farm.md`, `repo_state_evidence.md`, `repo_external_adapters.md`. They are cited where their facts are reused, and their own source labels are kept.
