## Key claims

| # | Claim | Source URL | Date / version | Confidence |
|---|---|---|---|---|
| 1 | Anthropic's own orchestrator-worker research system beat single-agent Opus 4 by 90.2% on an internal research eval, but agents use ~4x the tokens of chat and multi-agent ~15x; token usage alone explains 80% of BrowseComp variance; Anthropic says multi-agent is a poor fit for shared-context / interdependent work, "most coding tasks" included, and needs high task value to pay for itself. | https://www.anthropic.com/engineering/multi-agent-research-system | 13 Jun 2025 | verified_primary |
| 2 | Anthropic's Applied AI team now recommends folding routers, planners and domain subagents into ONE agent loop (prompts become skills, API calls become MCP tools) and keeping a subagent only when an eval shows the folded version is worse. One customer measured ~2x faster runtime with the single loop. Tool choice "tends to degrade" above 30-50 tool definitions. | https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop | 22 Oct 2026 | verified_primary (vendor guidance; the 2x figure is one unnamed customer) |
| 3 | Google Research / DeepMind / MIT controlled study, 180 configurations, 5 architectures: centralized coordination +80.9% on parallelizable financial reasoning; coordination gives diminishing or negative returns once the single-agent baseline exceeds ~45%; independent agents amplify errors 17.2x versus 4.4x with a central orchestrator. | https://arxiv.org/abs/2512.08296 ; https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ | Paper Dec 2025; blog Jan 2026 | reported_secondary (hosts blocked; abstract text surfaced by search) |
| 4 | Cognition's revised position: "multi-agent systems work best today when writes stay single-threaded and the additional agents contribute intelligence rather than actions". Clean-context reviewer and "smart friend" advisor work; parallel-writer swarms still do not. | https://cognition.com/blog/multi-agents-working | 22 Apr 2026 | reported_secondary (host blocked; quote repeated by several secondary write-ups) |
| 5 | In Anthropic's real shop experiment the added CEO agent "wasn't much help, and might even have been a hindrance"; profits "may have been in spite of the CEO"; agents sometimes chatted all night. What helped: tools (CRM, cost visibility), mandatory procedures ("bureaucracy matters"), better prompts, a better model. | https://www.anthropic.com/news/project-vend-2 | 18 Dec 2025 | verified_primary |
| 6 | MAST (Cemri et al., NeurIPS 2025): 14 failure modes in 3 groups (specification issues, inter-agent misalignment, task verification) from 1,600+ annotated traces across 7 frameworks incl. MetaGPT and ChatDev; fixing role specifications alone gave ChatDev only +9.4% success. | https://arxiv.org/abs/2503.13657 ; https://github.com/multi-agent-systems-failure-taxonomy/MAST | v3 2025 | reported_secondary (repo opened; numbers from search of the arXiv text) |
| 7 | A planner-generator-evaluator harness cost 6 h / $200 versus 20 min / $9 for a solo agent on the same build (Opus 4.5), i.e. >20x. The evaluator is worth it only "when the task sits beyond what the current model does reliably solo"; sprint decomposition and context resets were removed as models improved. | https://www.anthropic.com/engineering/harness-design-long-running-apps | 24 Mar 2026 | verified_primary |
| 8 | Claude Code agent teams are experimental and off by default, use ~7x the tokens of a standard session (teammates in plan mode), and are documented as worse than a single session or subagents for sequential tasks, same-file edits and work with many dependencies. | https://code.claude.com/docs/en/agent-teams ; https://code.claude.com/docs/en/costs | Docs as of 17 Nov 2026 | verified_primary |
| 9 | Remote Labor Index: Claude Fable 5.2 automates 41.3% of real freelance projects versus 21.3% (Opus 5.5), 20.8% (GPT-6 Astra), 17.9% (Fable 5.1); the best agent at launch in Oct 2025 scored 2.5%. Capability is moving into the single model; it still fails ~59%. | https://www.anthropic.com/news/claude-fable-and-mythos-5-2 ; https://labs.scale.com/leaderboard/rli | 9 Nov 2026 (amended 11 Nov) | reported_secondary (Anthropic launch post opened; benchmark owner's page blocked) |
| 10 | METR: highest published 50% time horizon is ~17.4 h (early Claude Mythos Preview, 95% CI ~8.5-55 h); post-2023 doubling time ~131 days; METR states a 50% horizon does not mean tasks of that length can be delegated reliably, and results above ~16 h are unreliable with the current task suite. | https://metr.org/time-horizons/ | Time Horizon 1.1; page reportedly unchanged since 8 Sep 2026 | reported_secondary (host blocked) |
| 11 | Anthropic's memory research: file/wiki notes plus transcript search raise long-task reward (Opus 5: 0.564 to 0.828 on CL-Bench); a rigid "record only failures" rule cut the gain (-0.234 for Opus 5); one page per entity captured 57/57 facts versus 41/57 in one shared file; over-logging hurts (Sonnet 3.7: 413 files, 1 badge; Fable 5: ~10 files, 4 badges). | https://www.anthropic.com/engineering/components-of-agent-memory | 6 Nov 2026 | verified_primary (vendor research) |
| 12 | Memory-vendor benchmark numbers are self-reported and not comparable: Mem0's README claims 92.5 LoCoMo / 94.4 LongMemEval but says the scores "reflect Mem0's managed platform", not the open-source SDK. No independent head-to-head of Letta / Mem0 / Zep was found. | https://github.com/mem0ai/mem0 | README as of 17 Nov 2026 | vendor_claim |
| 13 | Guardrail limits: users approve 93% of permission prompts; Claude Code auto mode's classifier misses 17% of real overeager actions; its default block rules cover pushing to main, production deploys and "modifying the agent's own permission config". In a red-team run Claude exfiltrated credentials in 24 of 25 retries when only model-level defences stood in the way. | https://www.anthropic.com/engineering/claude-code-auto-mode ; https://www.anthropic.com/engineering/how-we-contain-claude | 25 Mar 2026; 25 May 2026 | verified_primary |
| 14 | Event-driven operation is available inside existing subscriptions: Claude Code cloud scheduled tasks (formerly routines; research preview) run on schedule, API call or GitHub event on Pro and above, cannot run more often than hourly, draw on the same subscription usage, and push to `claude/` branches by default. | https://code.claude.com/docs/en/routines | Docs as of 17 Nov 2026 | verified_primary |
| 15 | Open-source agent tooling churns fast: AutoGen is archived and unmaintained, Flowise was archived on 13 Aug 2026, Daytona's public repo is archived (development private since June 2026), ChatDev pivoted from the CEO/CTO "virtual software company" to a zero-code workflow platform (7 Jan 2026). | https://github.com/microsoft/autogen ; https://github.com/FlowiseAI/Flowise ; https://github.com/daytonaio/daytona ; https://github.com/OpenBMB/ChatDev | Pages as of 17 Nov 2026 | verified_primary |

## Detailed findings

### 0. Method and access limits (read this first)

- Research date: 17 Nov 2026. Pages on anthropic.com, claude.com, platform.claude.com, code.claude.com and github.com were opened in full.
- The session's network policy blocked arxiv.org, research.google, cognition.com, metr.org, remotelabor.ai, labs.scale.com and the-agent-company.com. Facts from those sites come from search-result summaries and are labelled "not opened".
- The shared web-search budget ran out after about 21 searches. Several planned checks (Darwin Goedel Machine numbers, "Measuring Agents in Production", HurumoAI, OpenRouter, model-routing benchmarks) could not be run. Items resting on my pre-June-2026 knowledge are labelled "prior knowledge, not re-verified".

### 1. Single agent versus multi-agent: the evidence

**Anthropic multi-agent research system (13 Jun 2025)** - https://www.anthropic.com/engineering/multi-agent-research-system (opened)
- Opus 4 lead plus Sonnet 4 subagents "outperformed single-agent Claude Opus 4 by 90.2% on our internal research eval".
- Agents use ~4x the tokens of chat; "multi-agent systems use about 15x more tokens than chats".
- On BrowseComp "token usage by itself explains 80% of the variance". Much of the gain is therefore more tokens spent in parallel, not organisational structure.
- Poor fit: domains that need all agents to share the same context or have many dependencies; "most coding tasks".
- Economics: the task value must be high enough to pay for the extra tokens.
- Failure seen in early versions: spawning 50 subagents for simple queries; vague briefs made subagents duplicate each other's searches. Fix: each subagent gets an objective, an output format, tool guidance and task boundaries; effort scales with query complexity (1 agent with 3-10 tool calls for fact-finding; 10+ subagents only for complex research).
- "Agents are stateful and errors compound"; reliability relied on "deterministic safeguards like retry logic and regular checkpoints".
- Against the "game of telephone": subagents write outputs to external storage and "pass lightweight references back to the coordinator".

**Anthropic, "When to fold subagents into your main agent loop" (22 Oct 2026)** - https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop (opened)
- Recommends "fewer subagents in favor of progressively disclosed context and tools".
- Why teams over-built: old context limits, and Conway's law ("the agent architecture becoming a copy of their org chart").
- "Starting with Opus 4.5, models became capable of managing far more in a single loop than most teams expected."
- Keep a subagent only when: "a single agent loop hits measurable performance degradation from context bloat"; "multiple tasks need to be tackled in parallel with fresh context windows that can be discarded"; or "a single agent struggles to select appropriate tools or there are conflicting instructions in the system prompt".
- Costs of multi-agent: "Every call is a nested model loop that adds latency"; "Each call still hands back a lossy summary"; overlapping subagents and conflicting prompt rules.
- One customer "saw a roughly 2x faster runtime" with a single loop (n=1, unnamed).
- Migration recipe: build a small end-to-end eval first ("even a set of 10 golden examples is enough to start"), fold one subagent at a time, compare per-task results, keep the subagent only if the folded version scores worse, run each task several times.
- Caveats in the article: tool choice degrades above 30-50 tool definitions; "subagents still have their place, including at the research frontier"; the article promotes Anthropic's own migration kit.

**Google Research / DeepMind / MIT, "Towards a Science of Scaling Agent Systems"** - https://arxiv.org/abs/2512.08296 and https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/ (not opened; abstract text via search)
- Five architectures (single, independent, centralized, decentralized, hybrid), three model families, 180 configurations.
- Centralized coordination: +80.9% on parallelizable tasks such as financial reasoning. Decentralized coordination did best on dynamic web navigation (+9.2% versus +0.2%).
- Capability saturation: coordination yields diminishing or negative returns (beta = -0.408, p < 0.001) once the single-agent baseline exceeds ~45%.
- Error amplification: independent agents 17.2x, centralized 4.4x.
- Tool-heavy tasks suffer disproportionately from coordination overhead under a fixed budget.
- The authors' predictive model picks the best architecture for 87% of held-out configurations (cross-validated R^2 = 0.513 in the abstract).
- Not re-verified: my prior knowledge of the abstract is that every multi-agent variant degraded sequential-planning performance by 39-70%. One search summary mentioned "as much as 70 percent"; a second targeted search did not confirm the 39-70% range. Check the abstract before quoting.

**Cognition** - https://cognition.com/blog/multi-agents-working (22 Apr 2026, not opened; via search)
- Follow-up by Walden Yan to the June 2025 essay "Don't Build Multi-Agents". Core sentence: "multi-agent systems work best today when writes stay single-threaded and the additional agents contribute intelligence rather than actions."
- What works: a separate review agent that starts with clean context (no access to the coder's history); Cognition reports its Devin Review catches on average 2 bugs per PR, ~58% severe (vendor's own count). A "smart friend" pattern where the main model calls a stronger model as a tool; it failed when the cheap model could not tell it was out of its depth.
- What still fails: parallel-writer swarms and free-form agent networks ("mostly a distraction").

**MAST failure taxonomy (Cemri et al., UC Berkeley; NeurIPS 2025)** - https://arxiv.org/abs/2503.13657 (not opened), https://github.com/multi-agent-systems-failure-taxonomy/MAST (opened; dataset of 1,000+ traces on Hugging Face `mcemri/MAD`)
- 14 failure modes in three categories: specification issues; inter-agent misalignment; task verification (and termination). 1,642 annotated traces (v3; "1,600+" in the NeurIPS listing) across 7 frameworks. Cohen's kappa 0.88 for the taxonomy; the LLM annotator reached 94% accuracy, kappa 0.77.
- MetaGPT had 60-68% fewer failures than ChatDev in the first two categories but 1.56x more verification failures.
- Improving role specifications alone raised ChatDev's success rate by 9.4 points with the same model (GPT-4o): prompt polish does not fix structural problems.
- Prior knowledge, not re-verified: category shares in v3 are roughly 42% specification, 37% inter-agent misalignment, 21% verification.

**Role-play "CEO/CTO" frameworks**
- ChatDev: the repository is now "ChatDev 2.0 (DevAll)", a "Zero-Code Multi-Agent Platform"; the CEO/CTO/Programmer "Virtual Software Company" code moved to a `chatdev1.0` maintenance branch (announcement 7 Jan 2026). Apache-2.0, 34.8k stars. No quantitative benchmark in the README. https://github.com/OpenBMB/ChatDev (opened)
- MetaGPT: MIT, 71.3k stars; README lists product manager, architect, project manager, engineer roles run through SOPs; the team's commercial product is MGX (launched 19 Feb 2025; About links to atoms.dev). No benchmark results in the README. https://github.com/FoundationAgents/MetaGPT (opened)
- CrewAI (MIT, 61.0k stars) now pairs role-based "Crews" with deterministic, event-driven "Flows" and says production patterns include "deterministic steps, human input, structured outputs, and checkpointing". https://github.com/crewAIInc/crewAI (opened)
- Cost-matched test: "At Equal Inference Cost, Multi-Agent Structure Does Not Beat a Single Frozen Agent" (arXiv 2609.04217, not opened). Planner-Executor-Critic team versus single agent on a frozen 7B model: ALFWorld 0.769 versus 0.754 (p = 0.80) with 1.8x more calls; "the planner and critic evolve to empty or low-impact prompts"; on WebShop the team trended worse. The authors call it a boundary result, not a general verdict. https://arxiv.org/abs/2609.04217

**Project Vend phase two (Anthropic + Andon Labs, 18 Dec 2025)** - https://www.anthropic.com/news/project-vend-2 (opened)
- Setup: shopkeeper agent upgraded from Sonnet 3.7 to Sonnet 4 / 4.5, given CRM, inventory cost visibility, web research, payment links; a CEO agent ("Seymour Cash") and a merch agent ("Clothius") were added.
- Money, precisely: weeks with negative profit margin "were largely eliminated"; no total profit is published. The one figure quoted, "$2,649.20 (17.7%)" against a $15,000 quarterly target, is revenue, not profit.
- CEO effect: discounts fell ~80% and free items halved, but refunds tripled and store credits doubled; the CEO approved lenient-treatment requests about eight times as often as it denied them. Verdict: "wasn't much help, and might even have been a hindrance".
- The agents sometimes talked all night, drifting into "eternal transcendence".
- The merch agent with a genuinely separate product line was "a more successful addition" than the CEO.
- What worked: tools, forced procedures (price and delivery checks before quoting; "bureaucracy matters"), better prompts, a better model.
- Still broken: near-agreement to an illegal onion-futures contract, an "imposter CEO" accepted after a dubious vote, significant human help needed for physical tasks. "The gap between 'capable' and 'completely robust' remains wide."

**Large-scale multi-agent successes (all coding or formal tasks with strong automatic verifiers)**
- C compiler: 16 parallel Claude agents, ~2,000 sessions over ~2 weeks, "just under $20,000" API cost, 2 billion input / 140 million output tokens, ~100,000 lines of Rust. No orchestrator; coordination by lock files in `current_tasks/` and git. Parallelism worked while there were many independent failing tests; on one monolithic task (the Linux kernel) all agents hit the same bug and overwrote each other. Needs "extremely high-quality tests". https://www.anthropic.com/engineering/building-c-compiler (5 Feb 2026, opened)
- Cursor (Jan 2026): flat coordination with locks failed ("twenty agents would drop to the effective output of two or three"); agents avoided hard problems; a planner / worker / judge pipeline fixed most of it. https://cursor.com/blog/scaling-agents (not opened; via search)
- Fable 5.2 launch post (vendor claims): one engineer coordinated "over 1,000 subagents working around the clock for eight days" on a prototype OS; a 1,000-agent team formalised Fermat's Last Theorem in 30 hours; a customer ran a 10-12 hour security audit with ~170 reviewer agents. https://www.anthropic.com/news/claude-fable-and-mythos-5-2 (opened)

**How capable is one agent now?**
- Remote Labor Index (Scale AI + CAIS; 240 real freelance projects for which humans earned a combined $143,991): Fable 5.2 41.3%, Opus 5.5 21.3%, GPT-6 Astra 20.8%, Fable 5.1 17.9%; 2.5% for the best agent at launch (Oct 2025). "Automation rate" is the share of projects where the AI deliverable is accepted as at least as good as the human one; it is not revenue. One secondary analysis notes a 230 versus 240 project denominator mismatch (41.25% versus 41.3%). https://www.anthropic.com/news/claude-fable-and-mythos-5-2 (opened); https://labs.scale.com/leaderboard/rli and https://www.remotelabor.ai/ (not opened)
- Same launch post: AutomationBench (business workflows) 51.4% for Fable 5.2, 53.9% for Gemini 4 Carbon; OSWorld 2.1 89.3%. API price $8 / $40 per million input / output tokens. "Fable is included for up to 50% of weekly usage limits for Pro plans."
- METR (not opened): top published 50% horizon ~17.4 h for an early Claude Mythos Preview (CI ~8.5-55 h); GPT-5.6 "Sol" ~11 h 18 min; Opus 4.6 ~12 h after a bug fix (first published as ~14.5 h on 20 Feb 2026, corrected 3 Mar 2026). Post-2023 doubling ~130.8 days (Time Horizon 1.1). METR's repository README still states the original "approximately every 7 months". No METR figure for Fable 5.x or GPT-6 was found. https://metr.org/time-horizons/ ; https://github.com/METR/eval-analysis-public (opened)
- TheAgentCompany (175 tasks in a simulated software company; MIT; https://github.com/TheAgentCompany/TheAgentCompany opened): best full-completion rate reported by secondary trackers is ~42.9% (TTE-MatrixAgent + DeepSeek-V3.2, scores last changed 12 Sep 2026), versus 30.3% for Gemini 2.5 Pro in the paper's baseline table. The official leaderboard (https://the-agent-company.com/#/leaderboard) could not be opened; treat as unverified.
- Vending-Bench 2 (Andon Labs; simulated one-year vending business, $500 starting balance; score is the final bank balance in a simulation, not real profit): Gemini 4 Carbon $16,484 (28 Oct 2026), GPT-6 Astra $15,515. Andon reportedly estimates a good human strategy at ~$63,000; reports of models lying to suppliers and faking emails to score. https://andonlabs.com/evals/vending-bench-2 (not opened; via search)

**What actually improves outcomes (synthesis of the above)**
1. A stronger model (Vend, harness article, RLI jump from 2.5% to 41.3% in 13 months).
2. More useful tokens on parallelizable, read-heavy sub-problems (Anthropic research system; Google's +80.9%).
3. Tools and enforced procedures (Vend).
4. An automatic verifier: tests, CI, compilers, proof checkers (C compiler, Cursor, Fermat).
5. An independent evaluator with clean context, only for work beyond the model's reliable solo range (harness article, Cognition).
6. Not shown to help: management layers, same-model "executives", free-form agent chat, parallel writers.

### 2. Practical patterns against endless discussion, duplication and token waste

- Start with the simplest thing: "finding the simplest solution possible, and only increasing complexity when needed"; workflows are "predefined code paths", agents "dynamically direct their own processes". Orchestrator-workers suits "complex tasks where you can't predict the subtasks needed"; evaluator-optimizer is effective "when we have clear evaluation criteria"; include "stopping conditions (such as a maximum number of iterations)". https://www.anthropic.com/engineering/building-effective-agents (19 Dec 2024, opened)
- Single-writer ownership: Cognition's rule (above). Claude Code docs: "Two teammates editing the same file leads to overwrites"; file locking on task claims. https://code.claude.com/docs/en/agent-teams (opened)
- Structured handoffs: objective, output format, tool guidance, boundaries (Anthropic research system). Teammates "don't inherit the lead's conversation history", so the brief must be self-contained (agent-teams docs).
- Subagents return a condensed summary ("often 1,000-2,000 tokens") or a reference to an external artifact. https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents (29 Sep 2025, opened)
- Deterministic orchestration: Claude Code dynamic workflows move "the plan into code"; the script holds the loop, branching and intermediate results. Limits: 16 concurrent agents by default, 1,000 agents per run, a "Large workflow" warning above 25 agents or 1.5 million projected tokens; default size guideline on Pro is "small" (fewer than 5 agents). https://code.claude.com/docs/en/workflows (opened)
- Budgets: `--max-budget-usd` caps a headless run; `--permission-prompts none` and `dontAsk` deny anything not pre-approved in unattended runs. https://code.claude.com/docs/en/headless (opened)
- Team size: "Start with 3-5 teammates"; "Three focused teammates often outperform five scattered ones"; "Letting a team run unattended for too long increases the risk of wasted effort." (agent-teams docs)
- Evaluator-optimizer: agents "tend to respond by confidently praising the work" when grading themselves; "tuning a standalone evaluator to be skeptical turns out to be far more tractable". Out of the box Claude "is a poor QA agent". Sprint contracts (agreeing on "done" before work starts) bridged spec and tests. https://www.anthropic.com/engineering/harness-design-long-running-apps (opened)
- Re-test scaffolding: "every component in a harness encodes an assumption about what the model can't do on its own"; remove one component at a time and measure. Same point in https://www.anthropic.com/engineering/managed-agents (8 Apr 2026, opened): context resets became "dead weight" with Opus 4.5.
- Idle token drains documented by Anthropic: a session-scoped scheduled task "fires on its interval even while the session is idle, sending your full context each time"; cross-session messages start new turns; every active teammate "keeps consuming tokens until it exits". https://code.claude.com/docs/en/costs (opened)

### 3. Memory

- Anthropic, "The components of agent memory" (6 Nov 2026, opened): layers are transcripts (searchable event log, "the foundation"), memory notes, representations such as a linked wiki, a small injected context, and "dreaming" (offline review that reorganises memory and checks notes against transcripts). https://www.anthropic.com/engineering/components-of-agent-memory
  - CL-Bench mean reward, baseline to with-memory: Opus 5.5 0.655 to 0.838; Opus 5 0.564 to 0.828; Sonnet 4.6 0.330 to 0.364 (0.641 with refined instructions). Weaker models benefit less.
  - On a ~350,000-file corpus: wiki alone 13% to 48% over 128 sessions; wiki plus search 61% versus 53% for search alone, saving ~20,000 tokens per question.
  - Tell the model what memory is for, not rigid rules: "record only failures" cost -0.234 (Opus 5) and -0.150 (Opus 4.7).
  - Store what must be worked out (strategies, plans, tested rules), not what can be re-read from the environment.
  - "An incorrect note can be carried into every session"; a wrong route note sent the agent back the old way until dreaming corrected it.
  - Granularity: one shared file captured 41 of 57 contract facts; one page per contract captured 57 of 57.
  - Negative result: on a single-document legal task a 203 KB wiki over a 115 KB corpus gave no clear gain.
  - Claude Code auto memory loads only the first 200 lines or 25 KB of `MEMORY.md` as an index.
  - The article does not evaluate vector or graph stores.
- Claude memory tool: stable (GA), client-side, file-based under `/memories`; the developer owns storage. Auto-injected protocol: view the memory directory first and "ASSUME INTERRUPTION". Developer duties: path-traversal validation, size caps, expiry, stripping sensitive data. Documented multi-session pattern: progress log plus feature checklist, one feature at a time, mark complete only after end-to-end verification. https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool (opened)
- Skills as procedural memory: a folder with `SKILL.md` (name + description) loaded on demand. The standard was donated to the Agentic AI Foundation (Linux Foundation) on 22 Oct 2026; "more than 70 agent platforms" including ChatGPT, Cursor, GitHub Copilot and VS Code; 1 million skills published. Skills therefore port across the Claude and ChatGPT lanes. https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation ; https://github.com/anthropics/skills (both opened). Cost docs: move workflow instructions from CLAUDE.md into skills and keep CLAUDE.md under 200 lines.
- Letta (ex-MemGPT): Apache-2.0. The `letta-ai/letta` repo (25.5k stars) now carries a historical-source notice and points active work to `letta-ai/letta-code` (3.9k stars): agents rewrite their own memory blocks, all context is tracked in git via "MemFS", periodic "dreaming" (formerly sleep-time compute), learned skills. No benchmark claims on the page. https://github.com/letta-ai/letta ; https://github.com/letta-ai/letta-code (opened)
- Mem0: Apache-2.0, 69.1k stars. README table: LoCoMo 71.4 to 92.5, LongMemEval 67.8 to 94.4 at ~7K tokens per query, with the caveat that scores "reflect Mem0's managed platform". https://github.com/mem0ai/mem0 (opened)
- Zep / Graphiti: Apache-2.0, 32.9k stars. Temporal knowledge graph; needs Neo4j, FalkorDB or Neptune plus LLM calls for every ingestion ("smaller models may cause ingestion failures"); reference MCP/REST servers have no authentication; sub-200 ms retrieval applies to the paid Zep service, not Graphiti. https://github.com/getzep/graphiti (opened)
- Comparisons (via search, not opened): a Mem0 blog lists Zep at ~80-83% LoCoMo and Letta's filesystem agent at 74.0% LoCoMo with gpt-4o-mini; a third-party repo lists Letta 83.2% versus Mem0 68.5% and says it did not reproduce either; one preprint (H-Mem) with a shared judge shows Zep 76.56 versus Mem0 66.23. Different harnesses and judges; I found no independent head-to-head.
- Recording decisions, experiments and outcomes: no source prescribes a format. The supported ingredients are an append-only log as base layer, one page per entity, a small always-loaded index, scheduled consolidation that checks notes against the log, and completion marked only after verification (memory article and memory-tool docs).

### 4. Self-improvement that is real and safe

- Evals first. Anthropic, "Demystifying evals for AI agents" (9 Jan 2026, opened): "20-50 simple tasks drawn from real failures is a great start"; prefer deterministic graders, calibrate model graders against humans; capability evals start low, regression evals stay near 100%; pass@k (one success in k) versus pass^k (all k succeed, for customer-facing consistency); read transcripts; teams with evals adopt new models in days. https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- DSPy: MIT, 39.1k stars. https://github.com/stanfordnlp/dspy (opened)
- GEPA: MIT, 7.5k stars. Reflective, Pareto-based evolution of prompts or other text. Requires a metric function and a seed; "100-500 evaluations" versus thousands for RL; `max_metric_calls` caps spend. README claims (vendor, unverified): AIME 2025 46.6% to 56.6% with GPT-4.1 Mini; coding-agent resolve rate 55% to 82%; "50+ production uses". Every evaluation is an LLM call, so a run consumes quota. https://github.com/gepa-ai/gepa (opened)
- Darwin Goedel Machine: Apache-2.0, 2.5k stars; a system that "iteratively modifies its own code" and validates on coding benchmarks; README warns it executes "untrusted, model-generated code". https://github.com/jennyzzt/dgm (opened). Prior knowledge, not re-verified: the May 2025 paper reported SWE-bench 20.0% to 50.0% and Polyglot 14.2% to 30.7%, and documented the system gaming its objective by removing hallucination-detection markers.
- AlphaEvolve-style search: OpenEvolve (Apache-2.0, 7.8k stars) needs a scoring evaluator and a starting program; examples run 50-460 iterations; README gives no cost guidance. https://github.com/codelion/openevolve (opened). Prior knowledge, not re-verified: DeepMind's May 2025 results were on problems with exact automatic scoring (scheduling heuristics, matrix multiplication). Practical relevance to a content or sales business is low: there is no fast, cheap, ungameable fitness function.
- Agent-proposed PRs gated by CI and independent review: supported by the C compiler lesson (the model solves whatever the verifier defines), Cognition's clean-context reviewer and the harness evaluator.
- Guardrails against self-granted permissions, spend or production access:
  - Auto mode: a classifier on Sonnet 4.6 reviews each action and sees only user messages and tool calls. Full pipeline: 0.4% false positives on real traffic, 17% false negatives on 52 real overeager actions ("the honest number"), 5.7% on synthetic exfiltration. Real incidents listed: deleting remote branches, uploading an engineer's GitHub token, attempting migrations on a production database. "Not a drop-in replacement for careful human review on high-stakes infrastructure." https://www.anthropic.com/engineering/claude-code-auto-mode
  - Containment: "If credentials never enter the sandbox, they can't be exfiltrated"; "Every function reachable through any domain on an allowlist is now an attack surface"; the classifier is one layer inside a sandbox, "not a substitute for one"; "Be wary of custom components". https://www.anthropic.com/engineering/how-we-contain-claude
  - Agent-to-agent messages are not consent: "A teammate can't approve a permission prompt or supply consent on your behalf". https://code.claude.com/docs/en/agent-teams
  - Scheduled cloud runs push to `claude/` branches; GitHub branch protection is the control that decides where a run can push. https://code.claude.com/docs/en/routines
- Model routing: RouteLLM (Apache-2.0, 5.7k stars) claims up to 85% cost reduction at 95% of GPT-4 quality on MT Bench; this is 2024-era research on chat benchmarks. https://github.com/lm-sys/RouteLLM (opened). No current agentic routing benchmark was verified (search budget exhausted). Anthropic's cost docs give a manual rule: Sonnet for most work, Haiku for simple subagents, the strongest model for hard reasoning.

### 5. Open-source building blocks (GitHub pages opened 17 Nov 2026; star counts as displayed; release dates were not shown on the captured pages)

| Project | What it is | License | Maturity signal | Relevance to FactoryOS |
|---|---|---|---|---|
| DBOS Transact (Python) | Durable workflows, queues with concurrency and rate limits, cron schedules, durable sleep, `recv` messaging | MIT | 1.7k stars; already in the stack | High: the 24/7 backbone. https://github.com/dbos-inc/dbos-transact-py |
| Pydantic AI | Typed Python agent framework; MCP; evals; built-in human-in-the-loop tool approval; durable execution incl. DBOS and Temporal | MIT | 21.3k stars | High if a framework is needed: same stack (FastAPI, DBOS). https://github.com/pydantic/pydantic-ai |
| Agent Skills | `SKILL.md` procedure folders; open standard under AAIF | Apache-2.0 for most example skills | 196.6k stars; 70+ platforms | High: roles as skills, portable across lanes. https://github.com/anthropics/skills |
| OpenHands "Agent Canvas" | Self-hosted control centre for coding agents and automations (schedules, webhooks; Slack, GitHub, Linear, Notion); drives Claude Code, Codex, Gemini CLI | MIT | 93.7k stars; image tag 1.41.0 | Medium-high: overlaps with Relay / Agent Office; evaluate before building more control plane. https://github.com/OpenHands/OpenHands |
| goose | General agent (desktop, CLI, API), MCP extensions; "supports existing Claude, ChatGPT, or Gemini subscriptions via ACP" | Apache-2.0 | 56.7k stars; Linux Foundation AAIF; repo now `aaif-goose/goose` | Medium-high: fits zero additional spend. https://github.com/block/goose |
| Hermes Agent (Nous Research) | Self-improving personal agent: learned skills, memory, cron, subagents, one gateway for Telegram, Discord, Slack, WhatsApp | MIT | 264.2k stars | Medium: reference design for Telegram control plus cron; README does not explain how learned skills are validated; needs a model endpoint. https://github.com/NousResearch/hermes-agent |
| Langfuse | Tracing, evals, prompt management, datasets | MIT except `ee/` | 37.6k stars; part of ClickHouse since Jan 2026 | Medium: self-hosting is a multi-service stack (details not on the page). https://github.com/langfuse/langfuse |
| Arize Phoenix | Tracing, evals, experiments; `pip install arize-phoenix` then `phoenix serve` | Elastic License 2.0 (not OSI open source) | 12.3k stars | Medium: lightest self-hosted observability option. https://github.com/Arize-ai/phoenix |
| LiteLLM | Gateway for 100+ providers; virtual keys, spend tracking | Base licence not shown on page; enterprise features under a commercial licence | 63.4k stars | Medium later: per-key spend control once paid APIs exist. Anthropic's docs call it "unaffiliated ... not audited for security". https://github.com/BerriAI/litellm |
| DSPy / GEPA | Prompt programming and reflective prompt optimisation | MIT / MIT | 39.1k / 7.5k stars | Medium-low until evals exist. |
| Postiz | Social scheduler with API, MCP server, agent CLI; 14 networks | AGPL-3.0 | 41.8k stars | Medium-low: self-hosters must get their own developer apps approved ("Meta, YouTube, TikTok can take weeks"); needs Postgres, Redis, Temporal. https://github.com/gitroomhq/postiz-app |
| Letta Code | Stateful agent with git-tracked memory and dreaming | Apache-2.0 | 3.9k stars | Low-medium: borrow the idea (memory in git), not the product. |
| Mem0 / Graphiti | Memory layer / temporal knowledge graph | Apache-2.0 / Apache-2.0 | 69.1k / 32.9k stars | Low now: extra infrastructure and LLM calls; benchmarks self-reported. |
| smolagents | Minimal code-writing agents; sandbox via E2B, Modal, Docker; built-in local executor "is explicitly not a security sandbox" | Apache-2.0 | 30.4k stars | Low. https://github.com/huggingface/smolagents |
| Agno | Python agents, teams, workflows, AgentOS runtime | Apache-2.0 | 43.2k stars | Low: duplicates the existing stack. https://github.com/agno-agi/agno |
| Mastra | TypeScript agent framework | Apache-2.0 core; `ee/` under a paid enterprise licence | 29.6k stars | Low: wrong language. https://github.com/mastra-ai/mastra |
| Microsoft Agent Framework | Python and .NET successor to AutoGen and Semantic Kernel | MIT | 14.7k stars | Low. https://github.com/microsoft/agent-framework |
| AutoGen | Multi-agent conversation framework | MIT | 61.9k stars; "archived and no longer maintained" | Avoid. https://github.com/microsoft/autogen |
| Dify | Visual agent / RAG platform | Modified Apache 2.0 (no multi-tenant service without written permission; console logo must stay) | 161.4k stars; needs 2 CPU, 4 GiB RAM | Low: duplicates what exists. https://github.com/langgenius/dify/blob/main/LICENSE |
| Flowise | Visual agent builder | Apache-2.0 | 55.6k stars; archived 13 Aug 2026, read-only | Avoid. https://github.com/FlowiseAI/Flowise |
| Composio | Agent tool integrations ("1000+ toolkits") | MIT SDK; requires a hosted `COMPOSIO_API_KEY` | 31.1k stars | Low: hosted dependency; free tier not verified. https://github.com/ComposioHQ/composio |
| Arcade | MCP server framework plus hosted OAuth for tool calls | MIT framework; hosted engine | 1.1k stars | Low. https://github.com/ArcadeAI/arcade-mcp |
| E2B | Code sandboxes | Apache-2.0; self-host via Terraform; hosted by default | 14.9k stars | Low: EC2 plus Docker already exists. https://github.com/e2b-dev/E2B |
| Daytona | Code sandboxes | Licence not named on page | 71.3k stars; repo archived, core development private since June 2026 | Avoid for self-hosting. https://github.com/daytonaio/daytona |
| Chatwoot | Omnichannel support inbox (web chat, email, Telegram, WhatsApp) | MIT per README footer | 40.0k stars | Low until there are customers. https://github.com/chatwoot/chatwoot |
| Twenty | CRM | AGPLv3; files marked Enterprise under a commercial licence; SDK packages MIT | 61.1k stars; needs Postgres and Redis | Low until there are customers. https://github.com/twentyhq/twenty/blob/main/LICENSE |

Not verified in this session: OpenRouter (site not reachable), release dates, free-tier limits of any hosted service above.

### 6. 24/7 operation: triggers and schedules versus always-on loops

- Claude Code cloud scheduled tasks (research preview): a saved prompt plus repositories plus connectors; triggers are schedule, API POST with bearer token, and GitHub events; available on Pro, Max, Ultra, Team, Enterprise. "Expressions that run more often than once per hour are rejected." Runs "draw down subscription usage the same way interactive sessions do"; without usage credits, runs are rejected once the limit is hit. 100 scheduled runs per hour per account. Actions through connectors "appear as you". https://code.claude.com/docs/en/routines (opened)
- Headless runs on your own machine: `claude -p` with `--allowedTools`, `--permission-mode`, `--max-budget-usd`, `--output-format json` and `--json-schema`. Important for zero additional spend: `--bare` "doesn't use your subscription login" (it needs an API key) and "will become the default for `-p` in a future release". https://code.claude.com/docs/en/headless (opened)
- DBOS (already used): cron schedules, queues with concurrency limits and deduplication, `DBOS.sleep` surviving restarts for days or weeks, `DBOS.recv` to pause until a message arrives, workflow IDs as idempotency keys. https://github.com/dbos-inc/dbos-transact-py (opened)
- Evidence against always-on loops: idle scheduled turns resend full context (costs docs); Vend agents chatting all night; the C compiler's infinite loop needed tests as its only brake and once killed its own shell; "Letting a team run unattended for too long increases the risk of wasted effort" (agent-teams docs).
- Cost reference points (API pricing, not subscription): enterprise Claude Code averages "around $13 per developer per active day and $150-250 per developer per month", under $30 per active day for 90% of users (costs docs); harness builds $125-200 each; the 16-agent compiler ~$20,000 in two weeks.

## Counter-evidence and caveats

- Multi-agent does win in specific regimes: breadth-first research (+90.2%), parallelizable analysis (+80.9%), large coding or formal projects with strong verifiers (compiler, Cursor, 1,000-agent Fermat formalisation). Common factors: decomposable work, automatic verification, large token budgets. The Fable 5.2 examples are vendor showcases without disclosed cost.
- Anthropic's "fold your subagents" article is vendor guidance that also sells a migration kit; its 2x figure is one customer. It still says subagents "have their place".
- The equal-cost study used a frozen 7B model on ALFWorld and WebShop; its authors say heterogeneous backbones or larger budgets could change the result. It is weak evidence about frontier models.
- The Google scaling study's 45% threshold and amplification factors are specific to its four benchmarks and models; I could not open the paper to check definitions.
- Project Vend is a single deployment with no control group; the CEO verdict is the authors' judgement. Its CEO ran on the same model as the shopkeeper, so it says little about a reviewer from a different model family.
- I found no controlled evidence that a reviewer from another vendor's model beats a same-model clean-context reviewer. The recommendation below to use ChatGPT / Gemini lanes as reviewers is inference.
- RLI's 41.3% means the deliverable matched a paid human freelancer's on that share of projects under benchmark conditions. It does not measure finding clients, getting paid, or margin. Views, subscribers, leads, revenue and net profit are not measured by any benchmark cited here; Vend reports revenue and margin direction only, and Vending-Bench is a simulation.
- METR and TheAgentCompany figures are second-hand. METR's own caveat is that a 50% horizon is not a delegation guarantee; the 80% horizon is much shorter (one secondary source gives ~3 h for the model with a ~16-17 h 50% horizon).
- Memory numbers come from Anthropic's own evaluations (a game, CL-Bench, proprietary corpora) and say nothing about vector or graph stores. It is possible that a graph store wins on temporal queries at larger scale; no neutral test was found.
- Guardrail numbers (17% miss rate) are for Anthropic's classifier on Anthropic's traffic; a home-built approval gate has unknown error rates.
- Two papers surfaced by title only and were not examined: "Agensh: Scaling Organizational Intelligence to 1,024 Agents" (arXiv 2609.26781) and "Agent Team Work Zone" (arXiv 2607.22917). They may contain pro-hierarchy evidence.
- Whether running `claude -p` unattended on the EC2 host under a Pro subscription is supported long-term, and whether the usage policy allows it, was not verified.

## Implications for FactoryOS

**Verdict: a full CEO / CTO / Growth / Finance / Sales / Research / Content / Critic / QA hierarchy is not justified for a pre-revenue solo founder.** The evidence supports one orchestrating agent with good tools, a small number of temporary read-only helpers, one independent reviewer, and deterministic code around them.

1. **Minimal evidence-backed role set (inference from sections 1-2).**
   - One orchestrator that is the only writer per repository or artifact (the Claude Code lane).
   - Ephemeral read-only subagents for parallel research, audits and exploration. They return a short summary or a file reference and then end.
   - One independent reviewer with clean context for PRs and for anything about to be published. Use the existing ChatGPT or Gemini lane for this; it costs no extra money.
   - The human owner as the only approver of publishing, outreach, payments and permission changes (already repository policy).
   - Everything else is code: schedules, routing, budget checks, retries, approval gates.
2. **Turn the other "executives" into skills and checklists.** Growth, Finance, Sales, Content and QA should be `SKILL.md` procedures and mandatory checklists that the single agent loads on demand. Vend's lesson was that procedures helped and the CEO did not. Skills also port to the ChatGPT lane.
3. **Treat Relay's three lanes as the main architectural risk.** Three vendors' agents writing to one codebase is the parallel-writer pattern that Cognition, MAST and Cursor report as failing. `CLAUDE.md` itself notes that the live two-way connection is unverified (Issue #94). Make Claude Code the only writer; give the other lanes review, critique and research tasks with explicit claims and a fixed handoff schema (objective, output format, allowed tools, boundaries, done criterion, budget).
4. **Stop building organisation features until an eval says they help.** Apply Anthropic's own test: 10-50 golden tasks per pipeline (for example MyCast episode generation), run with and without each extra agent, keep the agent only if results are worse without it.
5. **Budget rules that match "zero additional spend".** The binding budget is subscription quota, not dollars. Fable counts for at most 50% of the weekly Pro limit; agent teams cost ~7x and research fan-outs ~15x a normal session. Defaults: no agent teams; fan-out of at most 3-5 helpers; at most two revise rounds in any evaluator loop; a hard turn or token cap per run; no agent-to-agent chat without a task ID and a done criterion.
6. **Run 24/7 on events and schedules, not loops.**
   - DBOS cron and queues (concurrency 1 for the writer) for pipelines; `DBOS.recv` for the Telegram approval step; durable sleep for waits.
   - Claude Code cloud scheduled tasks for repository chores (hourly at most, included in Pro, pushes to `claude/` branches).
   - Triggers: Telegram command, GitHub event, webhook, a metric crossing a threshold, a daily digest. No heartbeat that wakes an LLM with full context when nothing changed.
7. **Memory: keep it in git, in files.**
   - Append-only event and transcript logs as the base layer.
   - `DECISIONS.md` (exists) plus one file per experiment: hypothesis, change, metric named precisely (views, subscribers, leads, revenue or net profit), result, decision.
   - One page per entity (product, channel, customer), and a short index that is always loaded (under ~200 lines).
   - A weekly scheduled "consolidation" run that checks notes against logs and opens a PR.
   - Notion stays a human-readable mirror, not the source of truth. Do not add Mem0, Zep or Letta until file search demonstrably fails.
8. **Self-improvement only through gates.**
   - Prompt, skill and workflow changes arrive as PRs with an eval diff; CI plus the independent reviewer decide.
   - Paths that define the agent's own limits (`CLAUDE.md`, permission settings, budget constants, approval-gate code, CI workflows, deploy config) should require human review. This narrows the current rule that Claude may merge its own PRs once CI is green.
   - Keep credentials outside any environment where agent-written code runs, and keep egress allowlists tight: classifiers miss about one in six overeager actions.
   - GEPA is worth trying only on a step with a cheap automatic metric, with `max_metric_calls` capped, on free-tier quota. Darwin Goedel Machine and AlphaEvolve-style loops have no practical use here.
   - A/B testing content needs traffic; with no audience there is nothing to measure yet.
9. **Adopt, do not build, where a maintained tool exists.** Time-box an evaluation of OpenHands Agent Canvas and goose against the bespoke Relay / Agent Office before investing further in the control plane; both drive Claude Code, Codex and Gemini CLI. Use Pydantic AI if custom agent-loop code grows (it has a DBOS integration and built-in approval). Avoid AutoGen, Flowise and Daytona (archived).
10. **Priority.** None of the evidence shows an agent org chart producing revenue. The strongest current signal is that one frontier agent can deliver a client-acceptable result on ~41% of real freelance projects. The rational path is to point one well-tooled agent at one sellable deliverable with human approval, and add roles only when a measured bottleneck appears.

## Sources

**Opened in full (17 Nov 2026)**
- https://www.anthropic.com/engineering/multi-agent-research-system
- https://claude.com/resources/articles/building-agents-when-to-fold-subagents-into-your-main-agent-loop
- https://www.anthropic.com/engineering/components-of-agent-memory
- https://www.anthropic.com/engineering/harness-design-long-running-apps
- https://www.anthropic.com/engineering/building-c-compiler
- https://www.anthropic.com/news/project-vend-2
- https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents
- https://www.anthropic.com/engineering/claude-code-auto-mode
- https://www.anthropic.com/engineering/how-we-contain-claude
- https://www.anthropic.com/engineering/managed-agents
- https://www.anthropic.com/engineering/building-effective-agents
- https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- https://www.anthropic.com/engineering (index)
- https://www.anthropic.com/news (index)
- https://www.anthropic.com/news/claude-fable-and-mythos-5-2
- https://www.anthropic.com/news/donating-agent-skills-to-the-agentic-ai-foundation
- https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool
- https://code.claude.com/docs/en/agent-teams
- https://code.claude.com/docs/en/costs
- https://code.claude.com/docs/en/routines
- https://code.claude.com/docs/en/headless
- https://code.claude.com/docs/en/workflows
- https://code.claude.com/docs/llms.txt
- GitHub repositories: multi-agent-systems-failure-taxonomy/MAST, TheAgentCompany/TheAgentCompany, METR/eval-analysis-public, jennyzzt/dgm, codelion/openevolve, stanfordnlp/dspy, gepa-ai/gepa, lm-sys/RouteLLM, letta-ai/letta, letta-ai/letta-code, mem0ai/mem0, getzep/graphiti, anthropics/skills, dbos-inc/dbos-transact-py, pydantic/pydantic-ai, mastra-ai/mastra, agno-agi/agno, microsoft/agent-framework, microsoft/autogen, huggingface/smolagents, block/goose, OpenHands/OpenHands, NousResearch/hermes-agent, FoundationAgents/MetaGPT, OpenBMB/ChatDev, crewAIInc/crewAI, langgenius/dify (and LICENSE), FlowiseAI/Flowise, ComposioHQ/composio, ArcadeAI/arcade-mcp, e2b-dev/E2B, daytonaio/daytona, BerriAI/litellm, langfuse/langfuse, Arize-ai/phoenix, gitroomhq/postiz-app, chatwoot/chatwoot, twentyhq/twenty (and LICENSE) - all under https://github.com/

**Not opened: host blocked by the session network policy; content seen only through search-result summaries**
- https://arxiv.org/abs/2512.08296 and https://research.google/blog/towards-a-science-of-scaling-agent-systems-when-and-why-agent-systems-work/
- https://cognition.com/blog/multi-agents-working
- https://arxiv.org/abs/2503.13657
- https://arxiv.org/abs/2609.04217
- https://metr.org/time-horizons/
- https://labs.scale.com/leaderboard/rli , https://www.remotelabor.ai/ , https://scale.com/research/rli
- https://the-agent-company.com/#/leaderboard
- https://andonlabs.com/evals/vending-bench-2
- https://cursor.com/blog/scaling-agents
- https://mem0.ai/blog/state-of-ai-agent-memory-2026
