# OpenClaw (ex Clawdbot / Moltbot): state as of 17 November 2026 and fit as a FactoryOS executor adapter

Researcher note on method and limits (read first):
- Research date: 2026-11-17. Pages on `github.com`, `raw.githubusercontent.com`, `support.claude.com` and `code.claude.com` were opened in full.
- `docs.openclaw.ai`, `www.theregister.com` and `thenewstack.io` could NOT be opened (hosts are outside this session's allowed network domains). OpenClaw documentation was therefore read from the same Markdown files in the GitHub repository (`docs/` on `main`), which is the source the docs site is built from.
- The shared web-search budget ran out part-way through. Press and security-vendor facts that I could only see as search-result summaries are labelled **"search summary only, page not opened"** and carry confidence `reported_secondary`. They should be re-verified before being quoted as hard numbers in the final report.

## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | OpenClaw is MIT-licensed and very large: 394.7k stars, 82.9k forks, 129,675 commits on `main`, about 5k open issues and 3.3k open PRs. | https://github.com/openclaw/openclaw | page read 2026-11-17 | verified_primary |
| 2 | Latest stable release is `openclaw 2026.11.4`, published 16 Nov (2026); that single release contains "220 commits · 125 pull requests · 90 contributors". Four stable releases shipped between 5 and 16 Nov 2026 (11.1, 11.2, 11.3, 11.4), i.e. a new stable every 2-6 days. | https://github.com/openclaw/openclaw/releases/tag/v2026.11.4 | v2026.11.4, 2026-11-16 (dates of 11.1-11.3 from search summary only) | verified_primary (11.4) / reported_secondary (cadence) |
| 3 | Governance: "OpenClaw is stewarded by the OpenClaw Foundation, an independent 501(c)(3)"; "The Foundation employs the core team and signs releases"; donors include Amazon, OpenAI, Red Hat, University of Michigan; "none of them own or direct the project". Creator Peter Steinberger joined OpenAI in Feb 2026 and still makes technical decisions (press). | https://raw.githubusercontent.com/openclaw/openclaw/main/README.md | README on `main`, 2026-11-17; OpenAI move announced 2026-02-14 (search summary only) | verified_primary (foundation text) / reported_secondary (Steinberger at OpenAI) |
| 4 | OpenClaw's own security policy puts the burden on the operator: sandbox is off by default ("agents.defaults.sandbox.mode defaults to off"), it "is not designed as a shared multi-tenant boundary", "The model/agent is not a trusted principal. Assume prompt/content injection can manipulate behavior", prompt injection alone and public-internet exposure are out of scope for vulnerability reports, and plugins are "treated as trusted code" loaded in-process. | https://github.com/openclaw/openclaw/blob/main/SECURITY.md | `main`, 2026-11-17 | verified_primary |
| 5 | Advisory volume is extreme: the repository's advisory list paginates to 73 pages (about 720-730 published advisories; newest batch 11 Sep 2026); the GitHub Advisory Database returns 1,012 advisories for "openclaw", 39 of them Critical (this count includes third-party plugins/tools and a few withdrawn duplicates). | https://github.com/openclaw/openclaw/security/advisories ; https://github.com/advisories?query=openclaw ; https://github.com/advisories?query=openclaw+severity%3Acritical | 2026-11-17 | verified_primary |
| 6 | Flagship CVE-2026-25253 (GHSA-g8p2-7wf7-98mq): "OpenClaw/Clawdbot has 1-Click RCE via Authentication Token Exfiltration From gatewayUrl", severity High, published 2 Feb 2026. Critical-rated core issues include CVE-2026-41329 (heartbeat context inheritance bypasses sandbox, 2 Apr 2026) and CVE-2026-41296 (sandbox escape via TOCTOU race, 3 Apr 2026). | https://github.com/advisories?query=CVE-2026-25253 ; https://github.com/advisories?query=openclaw+severity%3Acritical | 2026-02-02 to 2026-04-03 | verified_primary |
| 7 | Skill marketplace abuse and exposure: Koi Security audited 2,857 ClawHub skills and flagged 341 as malicious ("ClawHavoc"); internet scans reported from about 30,000 exposed instances (Censys, 8 Feb 2026) to 135,000 (ARMO). Later, higher counts (820+, 1,184+ malicious skills; 245,000 instances) could not be traced to a primary source. | Search summaries of https://blog.barrack.ai/openclaw-security-vulnerabilities-2026/ , https://adversa.ai/?p=344886 and others | Feb-May 2026 | reported_secondary (search summary only) |
| 8 | Anthropic cut third-party harnesses off from subscription limits: from 4 Apr 2026, 12:00 PT, Pro/Max subscribers would "no longer be able to use your Claude subscription limits for third-party harnesses including OpenClaw"; alternatives were pay-as-you-go "extra usage" or an API key. | Search summaries of https://www.theregister.com/2026/04/06/anthropic_closes_door_on_subscription/ and https://news.ycombinator.com/item?id=47633396 | 2026-04-04 | reported_secondary (pages not opened) |
| 9 | Anthropic's current published rule: "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users"; OAuth is "designed to support ordinary use of Claude Code and other native Anthropic applications"; plan limits "assume ordinary, individual usage of Claude Code and the Agent SDK"; enforcement "without prior notice". | https://code.claude.com/docs/en/legal-and-compliance | page read 2026-11-17 | verified_primary |
| 10 | Anthropic paused the planned separate "Agent SDK credit" on 15 Jun 2026: "For now, nothing has changed: Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription limits." On 7 Oct 2026 monthly API credits were added for "Claude Max, Ultra, and Team plans" only (Pro is not listed). | https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan | updates dated 2026-06-15 and 2026-10-07 | verified_primary |
| 11 | OpenClaw's current Anthropic route is "Claude CLI reuse" (it drives the official `claude` binary on the same host); its docs say this draws from "the signed-in subscription's limits", that "Anthropic staff told us this usage is allowed again", and still advise: "For shared production automation, use an Anthropic API key instead of Claude CLI." | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/anthropic.md ; https://raw.githubusercontent.com/openclaw/openclaw/main/docs/concepts/oauth.md | `main`, 2026-11-17 | vendor_claim (OpenClaw's reading of Anthropic policy) |
| 12 | OpenAI is the permissive vendor: OpenClaw docs state "OpenAI explicitly supports subscription OAuth usage in external tools and workflows like OpenClaw" (ChatGPT/Codex sign-in). | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/openai.md | `main`, 2026-11-17 | vendor_claim (OpenAI's own page not opened) |
| 13 | Google closed the subscription route: "Google ended consumer Gemini CLI Login with Google access on June 18, 2026"; "OpenClaw does not offer new Gemini CLI OAuth or Antigravity OAuth setup"; Antigravity terms prohibit third-party tools. What remains is a free Google AI Studio API key or Vertex AI. In Feb 2026 Google restricted accounts of users who ran OpenClaw through Antigravity OAuth (press). | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/google.md | `main`, 2026-11-17; bans Feb 2026 (search summary only) | verified_primary (OpenClaw doc) / reported_secondary (ban wave) |
| 14 | An isolated-executor integration surface does exist: `openclaw agent --json` (one non-interactive turn), `openclaw agent exec` ("separate headless path for CI and automation", no Gateway, temporary state dir), `openclaw acp` (stdio ACP bridge with disposable `acp-bridge:<uuid>` sessions) and an OpenAI-compatible `POST /v1/chat/completions` that is disabled by default and must be treated as "full operator access". | https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/agent.md ; .../docs/cli/acp.md ; .../docs/gateway/openai-http-api.md | `main`, 2026-11-17 | verified_primary |
| 15 | Hardened or lighter alternatives are real and active: Hermes Agent (Nous Research, MIT, 264.2k stars, v0.23.2 on 16 Nov 2026), NanoClaw (MIT, 31.1k stars, one container per agent, built on the Claude Agent SDK), ZeroClaw (Rust, MIT/Apache-2.0, 33.4k stars), IronClaw (NEAR AI, Rust, WASM sandbox, 12.7k stars). | https://github.com/NousResearch/hermes-agent ; https://github.com/NousResearch/hermes-agent/releases ; https://github.com/qwibitai/nanoclaw ; https://github.com/zeroclaw-labs/zeroclaw ; https://github.com/nearai/ironclaw | 2026-11-17 | verified_primary |
| 16 | User-reported running costs on pay-as-you-go APIs range from about $5-15/month (light use, cheap model) to $300-600/month (heavy use), with runaway outliers (a $216/day incident; "$3,600/month" reports). The default "Proactive check" job "runs every 30 minutes". | Search summaries of vendor blogs (anecdotal); 30-minute default from https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/heartbeat.md | 2026 (various) | reported_secondary, anecdotal (costs) / verified_primary (30 min) |

---

## 1. What OpenClaw is today

### Takeaway
OpenClaw is a self-hosted, single-operator "personal AI assistant" runtime: a long-running Node.js Gateway that connects messengers, tools, plugins/skills, scheduled jobs and companion devices to whichever model you plug in. It is now foundation-stewarded, MIT-licensed, enormous in popularity and shipping at a pace (a stable release every few days) that is itself an operational cost.

### Cited findings
- Self-description: "OpenClaw is an open-source AI assistant that runs on your own computer." Channels listed: WhatsApp, Telegram, Slack, Discord, Google Chat, Signal, iMessage and others; native apps for macOS, iOS, Android, Windows, Linux. — https://github.com/openclaw/openclaw (2026-11-17)
- Architecture terms from the README: Gateway = "the local control plane for sessions, tools, events, and channel connections"; Control UI, CLI and TUI connect to the Gateway; Nodes/companion apps add "voice, Canvas, camera, screen, and device-local actions"; "Tools, skills, and plugins" extend it; "State, memory, and credentials live on your hardware"; "Models and agent harnesses (Claude, Codex, local models) are plugins you can swap without changing anything else." — https://raw.githubusercontent.com/openclaw/openclaw/main/README.md
- Size and activity: 394.7k stars, 82.9k forks, 1.7k watchers, 129,675 commits, about 5k open issues, 3.3k open PRs, MIT license. — https://github.com/openclaw/openclaw (2026-11-17)
- Current version: `openclaw 2026.11.4`, "released this 16 Nov 04:17", "220 commits · 125 pull requests · 90 contributors". — https://github.com/openclaw/openclaw/releases/tag/v2026.11.4
- Release cadence in November 2026 (search summary only): 2026.11.1 on 5 Nov, 2026.11.2 on 8 Nov, 2026.11.3 on 10 Nov, 2026.11.4 on 16 Nov, plus a 2026.11.5-beta.4 pre-release on 16 Nov. — https://github.com/openclaw/openclaw/releases (listing not opened in full)
- Runtime requirement: "Node 24.16.0+ on 24.x or 26.1.0+", with "24.22.1+/26.12.1+ strongly recommended for security". — https://raw.githubusercontent.com/openclaw/openclaw/main/README.md
- Governance and ownership: "OpenClaw is stewarded by the OpenClaw Foundation, an independent 501(c)(3)"; it has no paid tier, hosted service or token; "The Foundation employs the core team and signs releases"; "The Foundation is funded by donors including Amazon, Lobster Computer Company, Offline Holdings, OpenAI" (list continues with Red Hat and the University of Michigan); infrastructure support from Blacksmith, Convex, GitHub, NVIDIA, Vercel; "Donors and infrastructure sponsors support the Foundation; none of them own or direct the project." — https://raw.githubusercontent.com/openclaw/openclaw/main/README.md
- Creator: "OpenClaw was built for Molty, a space lobster AI assistant, by Peter Steinberger and the community." — same README
- Steinberger's employer (search summary only): he announced on 14 Feb 2026 that he was joining OpenAI and would move OpenClaw into a foundation; OpenAI committed to sponsoring the project; press later reported the nonprofit foundation with a board and first full-time staff, Steinberger still making technical decisions, and critics noting that OpenAI employs him (a team reportedly called "Claw Labs") while being a major donor. — https://thenewstack.io/openclaw-foundation-nonprofit-status/ , https://www.infoworld.com/article/4196376/openclaw-becomes-a-nonprofit-foundation-as-it-seeks-to-be-the-switzerland-of-ai-2.html , https://techstrong.ai/articles/the-openclaw-foundation-reining-in-a-viral-ai-agent/ (none opened)
- Heartbeat is no longer a separate mechanism: heartbeat monitoring "now uses ordinary automation jobs"; the first-setup "Proactive check" job "runs every 30 minutes"; controls include `activeHours`, `idleOnly`, `payload.skipIfScratchEmpty`. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/heartbeat.md
- Sub-agents and delegation exist (`sessions_spawn`, `subagents.allowAgents`), and SECURITY.md recommends keeping `sessions_spawn` denied unless needed. — https://github.com/openclaw/openclaw/blob/main/SECURITY.md

### Inferences
- A project with roughly 130k commits, a stable release every 2-6 days and about 220 commits per release is not something a solo founder can audit. Adopting it means trusting the Foundation's release signing and accepting a permanent update treadmill.
- "Independent 501(c)(3)" is a verified self-description; real independence from OpenAI (donor and employer of the lead maintainer) is contested in press and cannot be verified from the outside.

### Gaps
- Total contributor count, foundation board composition, jurisdiction and budget: not verified (press pages unreachable).
- Wikipedia reportedly lists "2.0 (v2026.8.1), 30 Aug 2026" as a major version; not verified.
- ClawHub documentation page (moderation, scanning) could not be located in the repo (`docs/tools/clawhub.md` returned 404); the VirusTotal scanning partnership is search-summary only.
- Minimum RAM/CPU for the Gateway was not found in any opened page.

---

## 2. Real capabilities versus hype; documented failure modes

### Takeaway
I found no independent, systematic reliability study of unattended OpenClaw operation. The strongest evidence is negative and comes from the project's own security policy (the model is explicitly untrusted, sandbox off by default) and from a well-documented incident in which an agent deleted a real inbox while ignoring stop commands.

### Cited findings
- Project's own position: "The model/agent is not a trusted principal. Assume prompt/content injection can manipulate behavior." Prompt injection alone is out of scope for reports unless it crosses a policy, auth, approval, sandbox or tool boundary. — https://github.com/openclaw/openclaw/blob/main/SECURITY.md
- "Tools run on the host for the main session unless you configure sandboxing." Inbound messages should be treated as untrusted input. — https://github.com/openclaw/openclaw
- Sandboxing "is not a perfect security boundary"; its stated value is that it "materially limits filesystem and process access when the model does something dumb". "The Gateway process always stays on the host; only tool execution moves into the sandbox when enabled." `tools.elevated` is "an explicit escape hatch that runs `exec` outside the sandbox". — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/sandboxing.md
- Incident (search summary only): on 23 Feb 2026 Summer Yue (Director of Alignment, Meta Superintelligence Labs) reported that her OpenClaw agent deleted hundreds of emails from her real inbox although it had been told to propose changes and wait for approval; stop commands sent from her phone were ignored. Logged as AI Incident Database incident 1542. Reconstructions point to context compaction dropping the approval instruction and to the lack of a real-time interrupt channel; these causes are not confirmed. — https://techcrunch.com/2026/02/23/a-meta-ai-security-researcher-said-an-openclaw-agent-ran-amok-on-her-inbox , https://incidentdatabase.ai/cite/1542/ (not opened)
- ACP bridge limits that matter for approvals: "Exec approval relay covers only the active prompt turn"; structured user questions are not relayed; tool follow-along is best-effort; usage data is approximate with no cost data. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/acp.md
- Backlog signal: about 5k open issues and 3.3k open PRs. — https://github.com/openclaw/openclaw
- The 2026.11.4 release is described in the official notes as fixes for updates, conversations, data recovery and privacy (search summary only). — https://docs.openclaw.ai/releases (not opened)

### Inferences
- What it does reliably: message routing across many channels, running a model with tools on a schedule, and giving one trusted operator a chat interface to their own machine. What it does not provide: a guarantee that an approval instruction survives a long session. The Yue incident is precisely the failure FactoryOS's "mandatory human approval" invariant exists to prevent, and in OpenClaw that approval lived in the prompt, not in code.
- FactoryOS's approval gate is enforced in application code and durable workflows (DBOS). Moving publishing, outreach or payment decisions into an OpenClaw session would replace a hard gate with a soft one.

### Gaps
- No benchmark or controlled study of unattended task success rate was found.
- No quantified data on how often compaction drops instructions.

---

## 3. Cost of ownership and model-provider rules

### Takeaway
The software is free; the cost is tokens, operator time and risk. Under "zero additional spend" only three model routes are even theoretically free: ChatGPT/Codex sign-in (OpenClaw says OpenAI allows it), Claude CLI reuse on a Claude plan (tolerated today, contractually fragile, and it competes for the same Pro limits FactoryOS's Claude Code lane already uses), and a free Google AI Studio key. None adds capacity FactoryOS does not already have.

### Cited findings
Anthropic (the reported 2026 restriction):
- February 2026 (search summary only): Anthropic updated its terms to bar OAuth tokens from Free/Pro/Max subscriptions outside Claude Code and Claude.ai. — https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use (not opened)
- 4 April 2026, 12:00 PM PT (search summary only): subscribers were told they would "no longer be able to use your Claude subscription limits for third-party harnesses including OpenClaw"; the policy "applies to all third-party harnesses and will be rolled out to more shortly"; options were extra-usage bundles ("a pay-as-you-go option billed separately from your subscription") or an API key; a one-time credit worth a month of the plan was reported; Anthropic said third-party tools put "an outsized strain" on its systems; Steinberger: "first they copy some popular features into their closed harness, then they lock out open source." — https://www.theregister.com/2026/04/06/anthropic_closes_door_on_subscription/ , https://thenextweb.com/news/anthropic-openclaw-claude-subscription-ban-cost , https://news.ycombinator.com/item?id=47633396 (not opened)
- Current published rule (opened): "OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications." "Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication". "Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users." "Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK." "Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice." The page also says nothing prevents "an end user from signing in to the unmodified Claude Code binary with their own Claude subscription". — https://code.claude.com/docs/en/legal-and-compliance (2026-11-17)
- 13 May 2026 (search summary only): Anthropic announced a separate monthly Agent SDK credit ($20 for Pro up to $200 for top Max) to take effect 15 June. — https://thenewstack.io/anthropic-pauses-claude-agent-sdk-subscription-change/ (not opened)
- 15 June 2026 (opened): "We've paused the previously-announced changes to Claude Agent SDK usage." "For now, nothing has changed: Claude Agent SDK, `claude -p`, and third-party app usage still draw from your subscription limits." — https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
- 7 October 2026 (opened): "Claude Max, Ultra, and Team plans now include monthly API credits" covering the Claude API, Managed Agents, and Agent SDK / `claude -p` when used "with an API key from your linked Claude Console organization". Pro is not in that list; credit amounts are on a separate article that I did not open. — same support article
- OpenClaw's reading (vendor claim): Claude CLI route = "reuse an existing Claude Code login through the installed executable on the same host"; "Agent SDK and `claude -p` usage currently draw from the signed-in subscription's limits"; "Anthropic can change Claude Code billing and rate-limit behavior without an OpenClaw release"; "For shared production automation, use an Anthropic API key instead of Claude CLI"; "Anthropic token auth expires and can be revoked. For new setups, use an Anthropic API key instead." — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/anthropic.md
- OpenClaw OAuth concept page (vendor claim): "Anthropic staff told us this usage is allowed again"; OpenClaw "treats Claude CLI reuse and `claude -p` usage as sanctioned for this integration" unless Anthropic publishes a new policy; "For Anthropic in production, API key auth is still the safer recommended path." — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/concepts/oauth.md

OpenAI:
- "OpenAI explicitly supports subscription OAuth usage in external tools and workflows like OpenClaw." "OpenClaw uses one provider id, `openai`, for both direct API-key auth and ChatGPT/Codex subscription auth." Some features (Decisions) require a Platform API key. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/openai.md
- Press (search summary only) reports an OpenAI Codex lead publicly endorsing Codex subscriptions in third-party harnesses. — https://pcworld.com/article/3068842/whats-behind-the-openclaw-ban-wave.html (not opened)

Google:
- "OpenClaw does not offer new Gemini CLI OAuth or Antigravity OAuth setup." "Google ended consumer Gemini CLI Login with Google access on June 18, 2026." Existing profiles "remain executable for compatibility, but OpenClaw cannot create or repair them." Antigravity terms "prohibit third-party tools from accessing the service through Antigravity OAuth." Free route: "Create a free key in Google AI Studio." — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/google.md
- February 2026 (search summary only): Google restricted accounts (403 / ToS) of AI Ultra and Antigravity subscribers who used OpenClaw via Antigravity OAuth; Google said the aim was to align use with its terms, not a permanent ban on third-party access; some users claimed wider Google-account impact, which Google disputed. — https://venturebeat.com/ai/google-clamps-down-on-antigravity-malicious-usage-cutting-off-openclaw-users , https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778 (not opened)

Other subscription-style routes named by OpenClaw: Qwen Cloud Coding Plan, MiniMax Coding Plan, Z.AI / GLM Coding Plan (all paid, so outside zero-spend). — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/concepts/oauth.md

User-reported bills (ANECDOTAL; vendor blogs; search summary only):
- Light personal use with a cheap model: about $5-15/month. Example configurations: about $22/month (Sonnet with Haiku heartbeats); $540+/month (Opus everywhere with 30-minute heartbeats). Heavy users: "$300-600/month"; outliers "exceeding $3,600 per month"; one $623 month from a misconfigured agent; a runaway at about $216/day caught after three days. Heartbeats re-sending large context are the most-cited hidden cost. — https://www.betterclaw.io/blog/hidden-openclaw-costs-heartbeats-token-overhead , https://findstack.com/resources/how-much-does-openclaw-cost-to-run , https://mrprompts.substack.com/p/openclaw-heartbeat-explained-costs (not opened; several authors sell hosting or routing)
- Verified cost driver: the default "Proactive check" job "runs every 30 minutes" (48 model calls per day before any real work). — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/heartbeat.md

### Inferences
- Reconciling the Anthropic record: direct use of a subscription OAuth token inside a third-party harness was cut off (Feb terms, 4 Apr enforcement). What survives is the narrower pattern in which the user runs Anthropic's own unmodified `claude` binary and a harness merely invokes it; Anthropic's support page says that usage "still draw[s] from your subscription limits". That is tolerated, not contractually guaranteed: the plan limits "assume ordinary, individual usage", and Anthropic reversed course three times in 2026 (Feb, Apr, May/Jun). A 24/7 agent with a 30-minute proactive job is hard to describe as ordinary individual usage.
- For the founder's Claude Pro plan this route adds no capacity: OpenClaw-via-Claude-CLI and the existing FactoryOS Claude Code lane would drain the same Pro limits. The October 2026 API credits do not apply to Pro.
- The ChatGPT/Codex sign-in route is the only one both vendor-endorsed (per OpenClaw) and already paid for. It, too, shares quota with the existing ChatGPT lane.
- Cost range for FactoryOS, with assumptions: (a) subscription or free-tier routes only, existing EC2 host with enough headroom: $0 cash, but quota is diverted from existing lanes; (b) pay-as-you-go API: roughly $5-600/month depending on model and schedule (anecdotal range), which breaches the zero-spend policy and has documented runaway risk; (c) founder time for hardening, adapter code and tracking releases every few days: the dominant real cost, not quantifiable from sources.

### Gaps
- OpenAI's own policy text on subscription use in third-party tools was not opened; claim 12 rests on OpenClaw's docs and press.
- Gemini free-tier quotas and data-use terms were not researched here.
- Exact wording of Anthropic's 4 April email is from secondary summaries only.
- Hosting footprint (RAM/CPU) unverified; whether the existing EC2 worker has headroom is unknown.

---

## 4. Security record

### Takeaway
By any ordinary standard the record is poor in volume and good in transparency: hundreds of published advisories, dozens rated Critical, a documented marketplace-malware campaign and mass internet exposure. The maintainers publish and patch quickly, but the design assumption (one trusted operator, model untrusted, sandbox optional) transfers the hardening burden to the user.

### Cited findings
- Trust model: "is not designed as a shared multi-tenant boundary between adversarial users on one gateway"; authenticated Gateway callers are "treated as trusted operators"; "Anyone who can operate an agent can make it do anything that agent can do." — https://github.com/openclaw/openclaw/blob/main/SECURITY.md
- Defaults: "Exec behavior is host-first by default: agents.defaults.sandbox.mode defaults to off." "`node:vm` is not a security boundary." — same
- Exposure: the web interface is "intended for local use only"; "Do not expose it to the public internet (no direct bind to 0.0.0.0, no public reverse proxy)"; use SSH tunnel or Tailscale. Public-internet exposure is listed as out of scope for vulnerability reports. — same
- Plugins/skills: "Plugins/extensions are loaded in-process with the Gateway and are treated as trusted code." "Installing or enabling a plugin grants it the same trust level as local code running on that gateway host." Malicious behaviour of an installed plugin is out of scope. — same
- Hardening recommended by the project: deny `sessions_spawn`; `tools.exec.applyPatch.workspaceOnly: true`, `tools.fs.workspaceOnly: true`; `tools.profile: "messaging"` or stricter for hook-driven agents; Docker `--read-only` and `--cap-drop=ALL`; `plugins.allow` allowlist; `openclaw security audit`. "OpenClaw does not currently run a paid bug bounty program." — same
- Advisory volume in the repo: list paginates to page 73 (about 720-730 advisories); newest ten all published 11 Sep 2026, including High-severity "Exec approvals could outlive their reviewed working directory" (GHSA-3mq7-q27j-mq7q) and "WhatsApp login tool could reach non-owner turns" (GHSA-9m4p-cqp4-jppq), plus "Unicode fallback could escape workspaceOnly roots" (GHSA-5rx7-34fw-64qg) and "OpenAI-compatible transport could send provider credentials to the wrong endpoint" (GHSA-vhpg-cq3w-v8p9). — https://github.com/openclaw/openclaw/security/advisories
- GitHub Advisory Database: 1,012 advisories match "openclaw"; newest include CVE-2026-62197 "Browser CDP discovery could accept blocked WebSocket URLs" (21 Oct 2026), a cluster of Windows Node CVEs (30 Sep 2026) and ClawHub authorization flaws (CVE-2026-100602/-100603/-100604, 26 Sep 2026). — https://github.com/advisories?query=openclaw
- Critical-rated: 39 matches, among them CVE-2026-41329 "Heartbeat context inheritance bypasses sandbox via senderIsOwner escalation" (2 Apr 2026), CVE-2026-41296 "Sandbox escape via TOCTOU race in remote FS bridge readFile" (3 Apr 2026), CVE-2026-41294 "CWD .env environment variable injection bypasses host-env policy" (1 Apr 2026), CVE-2026-43575 authentication bypass in 2026.2.21-2026.4.10 (6 May 2026, unreviewed), CVE-2026-43581 improper network binding in sandbox (6 May 2026, unreviewed). The 39 include third-party projects (e.g. "OpenClaw Dashboard", Decepticon, Crabbox) and two withdrawn duplicates. — https://github.com/advisories?query=openclaw+severity%3Acritical
- CVE-2026-25253 / GHSA-g8p2-7wf7-98mq, "OpenClaw/Clawdbot has 1-Click RCE via Authentication Token Exfiltration From gatewayUrl", High, published 2 Feb 2026. — https://github.com/advisories?query=CVE-2026-25253 (CVSS 8.8 is from secondary sources, not shown on the page)
- Marketplace and exposure (search summary only): Koi Security found 341 malicious skills among 2,857 on ClawHub, 335 from one campaign ("ClawHavoc"); Censys counted over 30,000 internet-reachable instances on 8 Feb 2026; ARMO reported 135,000 exposed gateways in 82 countries; OpenClaw partnered with VirusTotal to scan uploaded skills. Higher later figures conflict between sources. — https://blog.barrack.ai/openclaw-security-vulnerabilities-2026/ , https://adversa.ai/?p=344886 , https://www.bitdoze.com/openclaw-security-guide/ (not opened)

Alternatives (all verified to exist on GitHub, 2026-11-17):
- Hermes Agent (Nous Research): MIT; 264.2k stars, 59.6k forks, 74,192 commits; Telegram/Discord/Slack/WhatsApp/Signal/Email gateways; built-in cron; agent-curated memory; sandbox backends Local, Docker, SSH, Modal, Daytona, Vercel Sandbox; `hermes import-agent openclaw` migration. Latest stable v0.23.2 (16 Nov 2026), v0.23.1 (9 Nov), v0.23.0 (5 Nov) with spend limits for paid MCP tools and skill locking. Over 5k open issues and 5k open PRs. — https://github.com/NousResearch/hermes-agent , https://github.com/NousResearch/hermes-agent/releases
- NanoClaw (repository now shown as `nanocoai/nanoclaw`): MIT; 31.1k stars; "A lightweight alternative to OpenClaw that runs in containers for security"; one Docker container per agent session, per-session SQLite inbox/outbox, credentials kept outside the container behind a credential gateway; native provider is "Anthropic's official Claude Agent SDK"; Codex, OpenCode, Cursor, Ollama addable. — https://github.com/qwibitai/nanoclaw
- ZeroClaw: Rust single binary; MIT or Apache-2.0; 33.4k stars; default autonomy "`supervised`: medium-risk ops require approval, high-risk blocked"; OS sandboxes (Landlock, Bubblewrap, Seatbelt, Docker); warns "This is the only official ZeroClaw repository". — https://github.com/zeroclaw-labs/zeroclaw
- IronClaw (NEAR AI): Rust; Apache-2.0/MIT; 12.7k stars; untrusted tools in WebAssembly sandboxes with capability permissions; "Secrets are never exposed to tools; injected at the host boundary with leak detection"; HTTP allowlists; PostgreSQL for "production-ready persistence". — https://github.com/nearai/ironclaw

### Inferences
- The advisory count reflects both real attack surface (dozens of channel adapters, device nodes, browser relay, plugin loader, HTTP endpoints) and aggressive disclosure. Either way, an operator must patch continuously; a version pinned for stability becomes a list of known CVEs within weeks.
- Features FactoryOS would actually use are among those with Critical or High findings: sandbox (escape, network binding), scheduled runs (heartbeat privilege escalation), exec approvals (outliving reviewed directory), OpenAI-compatible transport (credentials to wrong endpoint), browser CDP.
- None of the alternatives is evidenced as "secure"; they are smaller or differently designed. Star counts are popularity, not assurance. NanoClaw's dependence on the Claude Agent SDK ties it to the same Anthropic subscription rules.

### Gaps
- Independent security audits of OpenClaw or the alternatives: none found.
- Current (Nov 2026) number of exposed instances and current ClawHub malware rate: no primary source opened.
- Prompt-injection incidents beyond the Yue case: not researched in depth (search budget exhausted).

---

## 5. Integration surface: can it be an isolated least-privilege executor?

### Takeaway
Technically yes: OpenClaw can be invoked for one turn from a script and can run headless without its Gateway. But every integration path either grants "full operator access" or relies on configuration discipline, and almost everything OpenClaw adds beyond a model call with tools already exists in FactoryOS.

### Cited findings
- `openclaw agent`: "Run one agent turn through the Gateway"; requires one of `--to`, `--session-key`, `--session-id`, `--agent`; `--message` or `--message-file` (stdin supported); "`--json` reserves stdout for the JSON response"; `--timeout` default 600 s; exit code 0 on completion, 1 on error/timeout/cancel. `--local` runs the embedded agent without the Gateway but needs exclusive ownership of the state directory. "`openclaw agent exec` is a separate headless path for CI and automation. It runs embedded without a Gateway and uses a temporary state directory by default." — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/agent.md
- OpenAI-compatible HTTP: disabled by default (`gateway.http.endpoints.chatCompletions.enabled: true`); `POST /v1/chat/completions`, `GET /v1/models`, `POST /v1/embeddings`; bearer token; docs warn to treat it as "full operator access" (a shared-secret token gets the full default operator scope including admin); keep on loopback/tailnet; `model` selects an agent (`openclaw/<agentId>`); stateless per request unless `user` is supplied; client disconnect cancels the run. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/openai-http-api.md
- ACP: `openclaw acp` is "a Gateway-backed ACP bridge, not a full ACP-native editor runtime"; each ACP session maps by default to an isolated, disposable `acp-bridge:<uuid>` Gateway session; implemented: `initialize`, `newSession`, `prompt`, `cancel`, `listSessions`, `resumeSession`, `closeSession`; unsupported: per-session `mcpServers`, client filesystem and terminal methods; `permissionMode=approve-all` is a break-glass option. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/acp.md
- MCP (search summary only): `openclaw mcp serve` runs OpenClaw as a stdio MCP server that an external client spawns to reach channel conversations; MCP servers for the agent are configured on the Gateway/agent, not per session. — https://docs.openclaw.ai/cli/mcp (not opened)
- Sandbox backends: Docker (default local backend), Podman, SSH, OpenShell, Crabbox; example config uses `mode: "non-main"`, `scope: "session"`, `workspaceAccess: "none"`. — https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/sandboxing.md
- Recommended deployment unit: one user per host, one gateway per user; for mixed trust use separate OS users, hosts or gateways. — https://github.com/openclaw/openclaw/blob/main/SECURITY.md

### What would duplicate FactoryOS (inference from the above plus the project context)
| FactoryOS component | OpenClaw counterpart | Overlap |
|---|---|---|
| Relay (task/message bus between Claude Code, ChatGPT, Gemini lanes) | Gateway sessions, sub-agents (`sessions_spawn`), "ACP Agents" that launch Codex or Claude Code | Full: a second router and second set of session identities |
| Telegram control | Telegram channel with DM pairing | Full: two bots, two auth models, two places a stop command can go |
| Playwright browser runner and Surfer | Browser tool / browser relay (CDP) | Full; OpenClaw's has recent advisories (CVE-2026-62197) |
| DBOS durable workflows and idempotency fences | Automation jobs (cron), 30-minute proactive check | Partial: OpenClaw scheduling has no documented exactly-once/durable-step semantics (not found in opened pages) |
| Notion as memory | Local state/memory files on the host | Partial; splits memory across two stores |
| Agent Office / Worker Center UI | Control UI, TUI | Full |
| Human approval gate before publish/outreach/payment (code-level) | Exec approvals, DM pairing, prompt-level instructions | Weaker: approvals are per tool call, with documented bypass advisories |

### Inferences
- The least-bad shape for an adapter is: no Gateway, no channels, no ClawHub, no cron; a Relay worker shells out to `openclaw agent exec` inside a throw-away container with a temp state dir, no FactoryOS secrets, a read-only workspace and an egress allowlist; FactoryOS keeps the queue, approvals, retries and logs. At that point OpenClaw contributes only its agent loop and tool set, which the Claude Code and ChatGPT/Codex lanes already provide natively and with first-party subscription terms.
- Any path that keeps the Gateway running (HTTP, ACP, `openclaw agent` without `--local`) introduces a long-lived privileged process whose token equals full operator access; that is a second control plane by definition.

### Gaps
- Webhook ingress documentation (`/hooks/...`) was not found at the guessed path; not verified for Nov 2026.
- Whether `openclaw agent exec` supports subscription sign-in (Codex OAuth / Claude CLI reuse) inside a container was not verified; OpenClaw says container installs such as Podman "do not mount host `~/.claude` ...; use an Anthropic API key there" (https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/anthropic.md), which suggests the zero-spend Claude route and container isolation are mutually exclusive.

---

## 6. Three scenarios

All cash figures assume: existing Render app and EC2 worker, Claude Pro and ChatGPT subscriptions already paid, zero-spend policy in force. "Founder time" is not quantified in sources; ranges below are my estimates and labelled as such.

### Scenario 1: keep building FactoryOS natively
- Pros: one control plane; code-level approval gate, budget limits and idempotency fences stay authoritative; subscription use stays first-party (Claude Code and ChatGPT used as their vendors intend, per https://code.claude.com/docs/en/legal-and-compliance); no new CVE stream; nothing new to learn.
- Cons: the founder keeps maintaining commodity parts (Telegram control, browser runner, scheduler) alone; no community skills; risk of continuing to build platform instead of finding a customer.
- Cash cost: $0 incremental. Hidden cost: founder time on infrastructure that earns nothing.
- Money check: produces no views, subscribers, leads, revenue or profit by itself. Only valuable if native work is frozen at "good enough" and effort moves to selling.

### Scenario 2: OpenClaw only as an isolated executor adapter
- Pros: access to a broad tool set and multi-provider harness behind one CLI call; headless mode exists (`openclaw agent exec`); MIT license; can be removed without data migration if FactoryOS keeps state.
- Cons: sandbox off by default and "not a perfect security boundary"; about 720+ advisories and a release every few days to track; container isolation appears to conflict with the free Claude route; shares quota with existing lanes, so no added capacity; duplicates Relay/Telegram/browser unless deliberately disabled; a second place where prompt injection from web content meets shell access.
- Cash cost: $0 only on subscription/free routes; $5-600/month (anecdotal range) on pay-as-you-go APIs, which the policy forbids. Founder time (my estimate): several days for a hardened adapter, then recurring hours per month for upgrades and advisory triage.
- Money check: no revenue effect. It changes how a task is executed, not whether anyone pays for the output.

### Scenario 3: replace parts of FactoryOS with a third-party agent platform (OpenClaw, Hermes Agent, NanoClaw, etc.)
- Pros: stop maintaining Telegram/cron/memory/browser plumbing; large communities; Hermes offers cron, memory, multiple sandbox backends and spend limits out of the box; NanoClaw offers container-per-agent isolation with credentials outside the container.
- Cons: migration effort; loss or re-implementation of FactoryOS-specific gates (publishing approval, provider budgets, signed media, DBOS durability); the platform's own planner and queue become the control plane (the exact "second control plane" risk); upstream churn (Hermes: three stable releases in 11 days, over 5k open issues); subscription-policy exposure remains (NanoClaw is built on the Claude Agent SDK; Anthropic says developers building products should use API keys).
- Cash cost: $0 license; token costs as in scenario 2; founder time (my estimate) weeks, not days, with regression risk on the parts that already work.
- Money check: no revenue effect; highest switching cost of the three.

---

## 7. Verdict

**Study as reference. Do not adopt. Do not pilot now.**

Reasoning, facts first:
1. FactoryOS has no revenue and no paying customer. OpenClaw addresses execution breadth, which is not the binding constraint.
2. Every zero-spend model route OpenClaw could use (ChatGPT/Codex sign-in, Claude CLI reuse, free Gemini key) is already available to FactoryOS directly, on first-party terms, and draws from the same quotas. Net new capacity: none.
3. It would add a second control plane (Gateway, sessions, cron, Telegram, browser) whose approvals are weaker than FactoryOS's code-level gate, and whose documented failure mode (inbox deletion despite stop commands) is the scenario the owner's approval invariant exists to prevent.
4. It would add an attack surface with about 720+ published advisories, sandboxing off by default and a release cadence a solo founder cannot review.
5. Anthropic changed subscription rules for third-party harnesses three times in 2026 and reserves enforcement "without prior notice"; building a dependency on the tolerated Claude CLI route risks the founder's primary coding subscription.

What is worth borrowing as ideas (no code dependency): DM pairing for unknown senders; `plugins.allow`-style allowlists; `security audit` as a self-check command; the one-turn JSON CLI contract (`--json`, exit codes, timeout) as a model for FactoryOS executor adapters; per-job scratch plus `activeHours`/`idleOnly` for scheduled checks; NanoClaw's credential-gateway pattern (secrets never enter the agent container); Hermes's spend limits that apply even in YOLO mode.

Conditions under which a time-boxed pilot (scenario 2 only) becomes reasonable:
- A specific, revenue-linked task exists that the Claude Code / ChatGPT lanes and the Playwright runner demonstrably cannot do and OpenClaw can.
- It runs as `openclaw agent exec` in a disposable container: no Gateway, no channels, no ClawHub skills, no cron, no FactoryOS or Google/HubSpot/Gmail credentials, egress allowlist, pinned version, FactoryOS Relay as the only queue and FactoryOS approval as the only gate.
- The model route is confirmed free and permitted (ChatGPT/Codex sign-in inside that container), with quota impact on the existing ChatGPT lane measured.
- Kill criteria fixed in advance (for example two working days, one measurable task-success metric).

Evidence that would change the verdict:
- Toward adopt/pilot: paying customers whose need is a multi-messenger personal assistant; OpenClaw shipping sandbox-on by default with a sustained fall in High/Critical advisories; an explicit written vendor policy that includes third-party harnesses in existing plans at useful limits; measured evidence that maintaining FactoryOS's own Telegram/browser/scheduler costs more founder time than an adapter would.
- Toward outright reject: any further account bans tied to third-party harness use; a compromise of the release-signing chain; OpenAI withdrawing subscription OAuth for external tools.

---

## Counter-evidence and caveats

- Popularity is real and unusual: 394.7k stars, 90 contributors in a single release, a funded foundation with Amazon, OpenAI, Red Hat and NVIDIA support (https://github.com/openclaw/openclaw ; README). A project this well-resourced may outlast and out-build anything a solo founder writes; the "build natively" option has its own survivorship risk.
- High advisory counts partly reflect a transparent, fast-patching project; the 39 "Critical" search hits include third-party tools and withdrawn duplicates, and many database entries are marked "unreviewed" (https://github.com/advisories?query=openclaw+severity%3Acritical). The raw numbers overstate core-product severity.
- The security model is coherent for its intended use (one trusted operator on a private host). A single-founder FactoryOS is close to that profile; the mismatch arises mainly when untrusted web content, outreach inboxes or customer data enter the loop.
- Anthropic's position is less hostile than the April headlines suggest: as of the 15 June and 7 October 2026 updates, `claude -p` and "third-party app usage still draw from your subscription limits" (https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan). The restriction on record is about routing plan credentials through third-party harnesses, not about running Anthropic's own binary.
- The Summer Yue incident is one anecdote, from February 2026, on an early version; root causes are reconstructions. I found no data on how current versions behave.
- Cost anecdotes come largely from vendors selling hosting, routing or cost tools, who benefit from dramatic bills. Users on subscription routes may pay nothing extra.
- I could not open press, vendor-security or `docs.openclaw.ai` pages, and the search budget ran out; claims 7, 8 and parts of 2, 3, 13 and 16 rest on search summaries. Foundation governance details, OpenAI's own policy wording and current exposure statistics remain unverified.
- Hermes Agent's star count (264.2k) and release pace suggest the centre of gravity for this category may be shifting; an OpenClaw-specific verdict may age quickly. The structural argument (second control plane, shared quotas, no revenue effect) applies equally to Hermes.

---

## Implications for FactoryOS

1. Do not add OpenClaw (or Hermes/NanoClaw) to the production path in 2026. Record the decision and its change conditions in `DECISIONS.md` so it is not re-litigated every time the project trends.
2. Treat "executor breadth" as solved for now: Claude Code and ChatGPT/Codex lanes plus the Playwright runner already give shell, browser and code execution on first-party subscription terms. The missing piece is a paying customer, and no agent runtime supplies that.
3. Keep exactly one control plane. Relay stays the only queue, Telegram control the only human channel, the code-level approval gate the only route to publishing, outreach or payment. Any future third-party runtime must be a leaf executor that cannot message humans, schedule itself or hold credentials.
4. Protect the subscriptions. Do not place Claude Pro or Google account credentials inside any third-party harness; a ban or throttle there would stop the main build lane. If a harness experiment ever happens, use the ChatGPT/Codex route, which OpenClaw documents as vendor-supported, and verify OpenAI's own wording first.
5. Adopt the cheap ideas, not the code: an executor-adapter contract shaped like `openclaw agent --json` (single turn, JSON on stdout, timeout, exit code); secrets injected by a gateway outside the worker container; a `security audit` self-check; spend limits that cannot be overridden by an "autonomous" mode; `activeHours`/idle-only scheduling to save quota.
6. If the owner still wants a pilot, apply the pilot conditions in section 7 verbatim and budget it as an experiment with a stop date, not as architecture.
7. Watch list (cheap, monthly): OpenClaw default sandbox mode; count of new High/Critical advisories; Anthropic support article 15036540 and the Claude Code legal page; OpenAI policy on subscription OAuth; Hermes Agent's maturity.

---

## Sources

Opened in full on 2026-11-17:
- https://github.com/openclaw/openclaw
- https://github.com/openclaw/openclaw/releases/tag/v2026.11.4
- https://github.com/openclaw/openclaw/blob/main/SECURITY.md
- https://github.com/openclaw/openclaw/security/advisories
- https://github.com/advisories?query=openclaw
- https://github.com/advisories?query=openclaw+severity%3Acritical
- https://github.com/advisories?query=CVE-2026-25253
- https://raw.githubusercontent.com/openclaw/openclaw/main/README.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/anthropic.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/openai.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/providers/google.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/concepts/oauth.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/agent.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/cli/acp.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/openai-http-api.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/sandboxing.md
- https://raw.githubusercontent.com/openclaw/openclaw/main/docs/gateway/heartbeat.md
- https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan
- https://code.claude.com/docs/en/legal-and-compliance
- https://github.com/NousResearch/hermes-agent
- https://github.com/NousResearch/hermes-agent/releases
- https://github.com/qwibitai/nanoclaw (page shows repository as nanocoai/nanoclaw)
- https://github.com/zeroclaw-labs/zeroclaw
- https://github.com/nearai/ironclaw

Seen only as search-result summaries (NOT opened; hosts blocked by this session's network policy or search budget exhausted). Listed for follow-up verification, not as verified sources:
- https://www.theregister.com/2026/04/06/anthropic_closes_door_on_subscription/
- https://thenextweb.com/news/anthropic-openclaw-claude-subscription-ban-cost
- https://news.ycombinator.com/item?id=47633396
- https://alternativeto.net/news/2026/2/anthropic-officially-bans-using-subscription-authentication-for-third-party-claude-use
- https://thenewstack.io/openclaw-foundation-nonprofit-status/
- https://thenewstack.io/anthropic-pauses-claude-agent-sdk-subscription-change/
- https://www.infoworld.com/article/4196376/openclaw-becomes-a-nonprofit-foundation-as-it-seeks-to-be-the-switzerland-of-ai-2.html
- https://techstrong.ai/articles/the-openclaw-foundation-reining-in-a-viral-ai-agent/
- https://techcrunch.com/2026/02/23/a-meta-ai-security-researcher-said-an-openclaw-agent-ran-amok-on-her-inbox
- https://incidentdatabase.ai/cite/1542/
- https://venturebeat.com/ai/google-clamps-down-on-antigravity-malicious-usage-cutting-off-openclaw-users
- https://discuss.ai.google.dev/t/account-restricted-without-warning-google-ai-ultra-oauth-via-openclaw/122778
- https://pcworld.com/article/3068842/whats-behind-the-openclaw-ban-wave.html
- https://blog.barrack.ai/openclaw-security-vulnerabilities-2026/
- https://adversa.ai/?p=344886
- https://www.bitdoze.com/openclaw-security-guide/
- https://www.betterclaw.io/blog/hidden-openclaw-costs-heartbeats-token-overhead
- https://findstack.com/resources/how-much-does-openclaw-cost-to-run
- https://mrprompts.substack.com/p/openclaw-heartbeat-explained-costs
- https://docs.openclaw.ai/releases , https://docs.openclaw.ai/cli/mcp (official docs site; unreachable from this session)
