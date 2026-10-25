# Hercules public competitive teardown for FactoryOS

Date: 2026-10-25  
Scope: public / clean-room analysis only.

## Scope and legal boundary

Hercules' public Acceptable Use Policy prohibits reverse-engineering, decompilation, disassembly, attempts to derive source code/models/algorithms/architecture, security bypass, scraping/crawling of the platform, and reconstruction of model internals. This document therefore uses only Hercules' public website, public documentation index, changelog, status/trust pages, legal pages, and publicly visible product descriptions. It does **not** attempt to access private code, hidden APIs, authenticated internals, or bypass controls.

The goal is competitive product analysis: understand product primitives, compare them with FactoryOS, and design our own implementation independently.

## Executive summary

Hercules is best understood as two adjacent products:

1. **AI App Builder** — chat-driven full-stack app creation with hosting, backend, database, auth, files, email, payments, AI, analytics, environments, versioning, publishing and integrations.
2. **Hercules Agents** — reusable autonomous workers with instructions, triggers, integrations, channels, guardrails, versions, run history, analytics, evaluation and auto-improvement.

The strongest ideas for FactoryOS are **not** the generic app-builder features. The best transferable primitives are:

- draft / publish / rollback versions for workers, prompts and workflows;
- test cases + scorers + evaluation runs before a worker/workflow version becomes active;
- run analytics: cost, latency, error rate, tools used, success rating and provenance;
- auto-improve suggestions generated from factual run history;
- spend/time/run limits with owner approval for higher-risk actions;
- multi-account connectors with workspace/environment scoping;
- reusable Skills / SOPs that can be attached at workspace, workflow and worker level;
- clone / transfer / export primitives for sellable customer workspaces;
- development/sandbox environments before production;
- enterprise-style audit and access controls.

FactoryOS should **not** become a general no-code app builder. Our strategic differentiation is stronger if the main object remains a **traceable AI+human production workflow**:
Discovery -> Revideo -> production -> Media Finisher -> QA -> HUMAN APPROVAL -> publishing -> analytics -> learning.

## What Hercules appears to optimize for

- Broad horizontal market: internal tools, SaaS, ERP/CRM, websites, mobile apps.
- End-to-end ownership of the application lifecycle.
- Low-code/no-code experience with AI as the primary builder.
- Built-in infrastructure to reduce integration friction.
- Separate persistent Agent product for repetitive work.
- Enterprise expansion through SSO, data residency, permissions, audit, backups and support.

## Public architecture signals — do not over-interpret

Public status pages label deployed app frontend as a **Cloudflare Worker** and deployed app backend as **Convex**. Hercules' Trust Center also lists AWS as a production backend/cloud provider and includes services such as S3, SES, ElastiCache, KMS and Secrets Manager; PlanetScale, Cloudflare and Vercel also appear as subprocessors/providers. These are public operational signals, not a complete architecture diagram.

For FactoryOS, the actionable lesson is architectural, not vendor-specific:
- isolate runtime vs build environment;
- separate dev and production data;
- scope secrets by environment;
- keep runtime cost attribution visible;
- make deployment and rollback explicit;
- make portability/export a first-class product feature.

## Feature inventory and recommendation matrix

Legend:
- **KEEP** = FactoryOS already has a strong equivalent; continue.
- **P0** = copy the product idea soon, independently.
- **P1** = high-value next phase.
- **P2** = later, after tenancy/sellability.
- **SKIP** = not strategically relevant now.
- **DIFF** = keep our own differentiated implementation.

| # | Hercules public feature | Area | FactoryOS view | Recommendation | Impact | Effort |
|---|---|---|---|---|---:|---:|
| 1 | Build by chat | Builder | We already orchestrate work conversationally | KEEP | 4 | 2 |
| 2 | Build / Plan / Debug modes | Builder | Useful for separating planning vs execution vs incident diagnosis | P0 | 5 | 2 |
| 3 | Background agent runs | Builder | Phone Claude daemon already proves this model | KEEP | 5 | 2 |
| 4 | Stop long-running agent | Builder | Safe pause exists; stronger stop semantics useful | P1 | 4 | 2 |
| 5 | Cross-thread context summaries | Builder | Useful for long project continuity | P1 | 3 | 3 |
| 6 | Multiple concurrent agents | Builder | Natural next step after dependency scheduler | P1 | 5 | 4 |
| 7 | Roadmap -> initiatives -> milestones | Planning | FactoryOS ROADMAP already stronger in machine-checkable DONE criteria | DIFF | 5 | 2 |
| 8 | Skills: reusable instructions | Knowledge | We need reusable SOP/policy blocks | P0 | 5 | 2 |
| 9 | Skill scope: user / org / app | Knowledge | Map to owner / workspace / workflow / worker | P1 | 5 | 3 |
| 10 | Skills marketplace | Ecosystem | Valuable only after external FactoryOS users exist | P2 | 3 | 4 |
| 11 | Web search by builder | Tools | Available through connected assistants; not core FactoryOS runtime | P2 | 2 | 3 |
| 12 | Large file attachments | Builder | Important for briefs/media/reference docs | P1 | 4 | 2 |
| 13 | Screenshot/annotation/element context | UX | Useful for UI QA and creative feedback | P1 | 4 | 3 |
| 14 | Screen recording as context | UX | Useful later for client/operator feedback | P2 | 3 | 3 |
| 15 | Code editor in platform | Dev | GitHub + Claude is enough now | SKIP | 2 | 5 |
| 16 | Query/import database from chat | Data | Useful for operational analytics/admin | P2 | 3 | 3 |
| 17 | Publish app from agent | Deploy | We deliberately keep CI/merge/deploy gates | DIFF | 5 | 3 |
| 18 | MCP control from external assistants | Platform | Strong fit for FactoryOS as an orchestration backend | P1 | 5 | 4 |
| 19 | ChatGPT integration | Platform | Useful distribution/channel later | P2 | 3 | 4 |
| 20 | Built-in database | App platform | FactoryOS already persists workflow state | KEEP | 4 | 2 |
| 21 | Serverless backend/API routes | App platform | Current API + Render approach sufficient | KEEP | 3 | 2 |
| 22 | Files/media storage | Media | FactoryOS durable media archive is strategically important | KEEP | 5 | 3 |
| 23 | Built-in hosting | App platform | Do not recreate cloud platform | SKIP | 1 | 5 |
| 24 | Domains / registrar | App platform | Not core | SKIP | 1 | 5 |
| 25 | Built-in email | App platform | Use external providers/connectors | SKIP | 2 | 4 |
| 26 | Commerce/payments | App platform | Marketplace payment flow matters later; not full commerce platform | P2 | 4 | 5 |
| 27 | App analytics | Analytics | We need workflow/business analytics, not generic page analytics | DIFF | 4 | 3 |
| 28 | AI Gateway | AI infra | Provider-neutral model routing can matter later | P2 | 4 | 4 |
| 29 | Scheduled/recurring events | Automation | Essential for agents and content schedules | P1 | 4 | 3 |
| 30 | Push notifications | Notifications | Telegram/in-app first; push later | P2 | 2 | 3 |
| 31 | Internationalization | UX | EN/UK/RU already implemented | KEEP | 3 | 2 |
| 32 | PWA/mobile install | UX | Mobile operator use is important; current responsive UI first | P2 | 3 | 3 |
| 33 | Native App Store publishing | App platform | Not core | SKIP | 1 | 5 |
| 34 | Visual editor | Builder | Not core for FactoryOS | SKIP | 2 | 5 |
| 35 | Branding/SEO tools | App platform | Only for client portal/marketplace later | P2 | 2 | 3 |
| 36 | App audits across product/design/engineering/security | Quality | Strong idea: unified audit worker | P1 | 4 | 3 |
| 37 | Security audit | Quality | Add before multi-tenant launch | P1 | 5 | 3 |
| 38 | Browser workflow tests | Quality | Useful for key approval/publish/mobile flows | P1 | 5 | 3 |
| 39 | Automatic version history | Change mgmt | We need this for prompts/workflows/config | P0 | 5 | 3 |
| 40 | Branches with isolated backend | Change mgmt | Great model for risky workflow/config changes | P1 | 5 | 5 |
| 41 | Dev vs Production environments | Change mgmt | High value before external customers | P1 | 5 | 4 |
| 42 | Clone production data to dev | Testing | Later with strict privacy/sanitization | P2 | 3 | 4 |
| 43 | Secrets scoped by environment | Security | Extend current server-side secret discipline | P1 | 5 | 3 |
| 44 | Scheduled DB backups | Reliability | Needed for sellable workspaces | P1 | 4 | 2 |
| 45 | Export code/data/files | Portability | Very strong trust/sales feature | P1 | 5 | 3 |
| 46 | Duplicate an app | Portability | Translate to Clone Workspace / Clone Factory | P1 | 5 | 3 |
| 47 | Transfer app between organizations | Portability | Excellent pattern for selling/reassigning client workspaces | P1 | 5 | 4 |
| 48 | Data residency / move region | Enterprise | Later enterprise feature | P2 | 3 | 5 |
| 49 | Public backend URL / API | Platform | FactoryOS API already exists; formalize external API contracts later | P2 | 3 | 3 |
| 50 | Serverless scale claims | Infra | Use managed infrastructure instead of reproducing it | SKIP | 2 | 5 |
| 51 | 250+ App Integrations | Connectors | Broad catalog later; start with strategic providers | P2 | 4 | 5 |
| 52 | Organization-shared connections | Connectors | Strong fit for workspace integrations | P1 | 5 | 3 |
| 53 | Multiple accounts per provider | Connectors | Directly matches customer/account portability goal | P0 | 5 | 3 |
| 54 | Connection scoped to environment | Connectors | Useful for test vs production social accounts | P1 | 5 | 3 |
| 55 | Personal Chat Connectors | Connectors | Could map to owner/operator private tools | P2 | 3 | 3 |
| 56 | Custom MCP by URL + OAuth | Connectors | Good extensibility model | P1 | 5 | 4 |
| 57 | Per-tool approval policy | Safety | FactoryOS HUMAN gate is stronger for publishing; generalize it | P0 | 5 | 3 |
| 58 | Sensitive tool-call approval UI | Safety | Add approve once / always / reject / comment policy model | P1 | 5 | 3 |
| 59 | Users / roles / permissions | Access | Mandatory for customer workspaces | P1 | 5 | 4 |
| 60 | Per-app teammate permissions | Access | Map to workspace/project roles | P1 | 5 | 3 |
| 61 | Authentication audit log | Security | Mandatory before enterprise sales | P1 | 5 | 3 |
| 62 | SSO/SAML | Enterprise | Later, after paid B2B traction | P2 | 3 | 5 |
| 63 | Social/email/SMS/password auth portal | Auth | We need simpler customer auth, not a full auth product | P1 | 4 | 4 |
| 64 | Security response headers | Security | Low-cost hardening | P1 | 4 | 1 |
| 65 | Cloud usage alerts | Cost | FactoryOS needs spend/usage alerts by worker/workspace | P0 | 5 | 2 |
| 66 | AI usage history with source attribution | Cost | Directly useful for cost accounting | P0 | 5 | 2 |
| 67 | Per-function cloud usage metrics | Cost | Map to worker/tool/provider/cycle costs | P1 | 4 | 3 |
| 68 | Privacy / enterprise data controls | Enterprise | Later, but design tenancy correctly now | P2 | 4 | 5 |
| 69 | Separate persistent Agents product | Agents | FactoryOS workers are already core product objects | KEEP | 5 | 2 |
| 70 | Trigger: schedule | Agents | Needed | P1 | 4 | 2 |
| 71 | Trigger: private URL/webhook | Agents | Needed for integrations | P1 | 4 | 2 |
| 72 | Trigger: external app event | Agents | Needed after connectors mature | P1 | 5 | 4 |
| 73 | Agent channels: Slack/Linear/GitHub/Teams/Telegram/WhatsApp/X | Agents | Telegram first; business channels later | P2 | 4 | 4 |
| 74 | Guardrails on input/action/output | Safety | Important extension beyond one publish gate | P0 | 5 | 4 |
| 75 | Draft -> publish Agent versions | Agents | Excellent change-control primitive | P0 | 5 | 3 |
| 76 | Agent rollback to previous version | Agents | Same versioning system | P0 | 5 | 2 |
| 77 | Run history with exact actions | Observability | FactoryOS already has trace/timeline; deepen it | KEEP | 5 | 2 |
| 78 | Mark run good/bad | Evaluation | Simple high-value feedback signal | P0 | 5 | 1 |
| 79 | Convert real run into test case | Evaluation | Strong feature for regression library | P0 | 5 | 2 |
| 80 | Analytics: frequency / failure / duration / tools / score / cost | Evaluation | One of the highest-value gaps | P0 | 5 | 3 |
| 81 | Auto-improve from run history | Evaluation | High leverage after metrics/test cases exist | P1 | 5 | 4 |
| 82 | Issues generated by auto-improve | Evaluation | Useful after auto-improve | P1 | 4 | 3 |
| 83 | Test case library | Evaluation | Core prerequisite for safe autonomous improvement | P0 | 5 | 3 |
| 84 | AI scorers defined in natural language | Evaluation | Strong fit for creative QA + worker QA | P0 | 5 | 3 |
| 85 | Evaluation runs comparing Agent versions | Evaluation | Required before auto-promoting new versions | P0 | 5 | 4 |
| 86 | Per-run cost/time limits | Safety/cost | Very high value for autonomous workers | P0 | 5 | 2 |
| 87 | Agent folders/tags/favorites | UX | Useful once many workers/workflows exist | P2 | 2 | 2 |
| 88 | Duplicate Agent | Templates | Useful for vertical templates | P1 | 4 | 2 |

## Top 12 ideas to implement in FactoryOS

### P0 — highest leverage

1. **Worker/Workflow Version Registry**
   - draft -> test -> publish -> rollback
   - immutable version ID attached to every run
   - prompt/instruction/tool/guardrail snapshot

2. **Evaluation Lab**
   - test cases from real runs
   - manual and AI scorers
   - compare old vs new worker/workflow version
   - block publishing/activation if regression threshold is missed

3. **Run Analytics**
   - duration, cost, tokens, provider/tool calls, retries, error class
   - quality score and owner good/bad feedback
   - breakdown by worker, workflow, workspace and client

4. **Guardrail Policy Engine**
   - input policy
   - tool/action policy
   - output policy
   - policies: allow, require approval, block
   - retain existing non-bypassable HUMAN publish boundary

5. **Budget and Runtime Limits**
   - max spend/run
   - max time/run
   - daily/workspace budget alerts
   - require owner approval above threshold

6. **Multiple accounts per provider**
   - workspace-bound YouTube/TikTok/Instagram/HubSpot/Metricool accounts
   - Change account without deleting project history
   - test vs production account separation

7. **Skills / SOP Registry**
   - reusable instructions attached to workspace/workflow/worker
   - versioned
   - owner-visible source/provenance

### P1 — after P0 foundation

8. **Auto-improve**
   - analyze failed/low-score runs
   - propose changes, never silently publish them
   - run evaluation suite against proposal
   - owner approves promotion

9. **Clone Workspace / Clone Factory**
   - copy workflow configuration, roles, skills and templates
   - do not copy credentials by default
   - optionally copy demo/fixture data

10. **Transfer / Reassign Workspace**
    - customer A -> customer B / new owner
    - content/audit history preserved
    - credentials detached and reconnected by receiving owner

11. **Export / Backup**
    - export jobs, artifacts metadata, approvals, analytics, workflow versions and customer-owned files
    - scheduled backups

12. **Sandbox environment**
    - test workflows/connectors against fixtures or test credentials
    - separate from production workspace

## Where FactoryOS can be better than Hercules

### 1. Vertical orchestration, not generic building
Hercules' breadth is its strength and its weakness. FactoryOS can be much clearer:
**AI/human team that runs a measurable production process.**

### 2. Stronger end-to-end provenance
FactoryOS already binds:
source -> candidate -> rewrite -> production job -> finished media -> approval -> immutable publish snapshot -> platform receipt -> analytics.

That chain should become a major commercial differentiator.

### 3. HUMAN approval as a visible business primitive
Instead of only asking for approval on risky tool calls, FactoryOS can make approval a first-class workflow object:
- what exactly is being approved;
- artifact/version hash;
- who approved;
- what changed after approval;
- which external action was allowed.

### 4. Creator marketplace / human talent layer
Hercules focuses on AI agents and apps. FactoryOS can add:
- verified human AI-video creators;
- assignments;
- contests/bounties;
- creator scorecards;
- reliability/speed/quality metrics;
- payout ledger;
- client selection and managed matching.

This is a more defensible niche than competing head-on with a general app builder.

### 5. Creative performance loop
The end state can be:
brief -> variants -> publish -> factual performance -> learn -> next creative hypothesis.

Agent evaluations measure worker quality; creative analytics measure market quality. Combining both is a strong moat.

## What we should NOT copy now

- generic AI app builder;
- domain registrar;
- full email infrastructure;
- full commerce platform;
- native mobile-store build pipeline;
- generic website visual editor;
- broad hosting platform;
- thousands of connectors before we know the top 10 that customers use;
- enterprise SSO/data residency before we have B2B traction.

These would consume engineering time without strengthening the immediate Blackbox/FactoryOS business model.

## Candidate backlog — not added to ROADMAP yet

These are proposals for owner review, not autonomous work items:

- HERC-P0-01 Worker/workflow version registry
- HERC-P0-02 Run feedback: good/bad + notes
- HERC-P0-03 Test case library from real runs
- HERC-P0-04 Natural-language scorers
- HERC-P0-05 Evaluation runs + regression gate
- HERC-P0-06 Worker cost/latency/error/tool analytics
- HERC-P0-07 Guardrail policy engine
- HERC-P0-08 Per-run/time/workspace spend limits
- HERC-P0-09 Skills/SOP registry
- HERC-P1-01 Auto-improve proposals
- HERC-P1-02 Clone Workspace
- HERC-P1-03 Transfer/Reassign Workspace
- HERC-P1-04 Export + scheduled backup
- HERC-P1-05 Sandbox environment
- HERC-P1-06 Workspace roles + audit log

Recommended order:
**observability -> evaluation -> versioning -> guardrails/budgets -> auto-improve -> workspace portability -> external productization.**

## Competitive positioning

Do not position FactoryOS as:
> "Another AI app builder."

Better:
> **FactoryOS is an operating system for AI + human production teams. It delegates work, proves what happened, controls spend and approvals, and carries the exact result from brief to published outcome and analytics.**

For the creator/agency direction:
> **FactoryOS runs the entire creative supply chain: brand brief -> AI + creator production -> QA -> approval -> publish -> performance -> learning.**

## Public sources used

- https://hercules.app/
- https://hercules.app/home
- https://hercules.app/changelog
- https://hercules.app/changelog/hercules-agents
- https://hercules.app/changelog/app-integrations
- https://hercules.app/changelog/chat-connectors
- https://hercules.app/changelog/development-environments
- https://hercules.app/changelog/agent-modes
- https://hercules.app/changelog/security-response-headers
- https://hercules.app/changelog/cloud-usage-alerts
- https://hercules.app/changelog/organization-usage-history
- https://hercules.app/mcp-setup
- https://hercules.app/docs/llms.txt
- https://hercules.app/customers
- https://status.hercules.app/
- https://trust.hercules.app/
- https://hercules.app/legal/acceptable-use-policy
- https://hercules.app/legal/product-specific-terms
- https://hercules.app/legal/terms-of-service

## Review note

Public documentation and product behavior can change. Re-check Hercules before using a specific feature claim in customer-facing competitive material.
