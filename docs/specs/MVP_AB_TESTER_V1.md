# MVP Factory — A/B Tester agent and Concept Backlog | Implementation spec V1

**Status:** OWNER CONCEPT APPROVED FOR CAPTURE; this document is a proposed technical contract, NOT an implemented agent or authorization to publish.  
**Date:** 2026-11-13 (Europe/Kyiv).  
**Origin:** owner voice direction: MyCast should help people keep focus on personal goals, with sub-niches; MVP Builder must support an A/B Tester that drafts alternate landing pages and ad/social copy.  
**Documentation owner:** ChatGPT, issue #346. **Engineering owner (proposed):** Claude, through an independently claimed implementation issue after docs review.  
**Related:** MVP Factory epic #186, MVP Builder spec docs/MVP_FACTORY_SPEC.md; MyCast #105 / #305; Steve Blank Customer Development playbook PR #343; Notion MVP Center https://app.notion.com/p/4108fbbd6dd58132a73bd94934e34bd1; Notion MyCast focus concept https://app.notion.com/p/4178fbbd6dd58112a404c5be4ea559f5.  
**Hard limits:** no new paid APIs, cloud, advertisements, third-party messaging or publishing without owner approval; no direct-main writes, no duplicate scheduler, no agent double-claim.

## 1. User outcome and why

**User story:** As the owner of several MVP products, I want to save any new concept under its existing project and run reliable experiments comparing landing-page messages and marketing post drafts, so we can choose what to validate or build based on evidence rather than tastes.

There are **two independent features**:
1. **Concept Backlog**: durable project-scoped ideas, rationale, lifecycle and links.
2. **A/B Tester**: a named MVP Factory specialist that plans, produces, instruments, QA-checks, compares and reports two or more variants, with a human publication/expense gate.

Do not create a new company/project per niche. MyCast is one core product; goal-focus, founders/business, health/habits, career/study, sports/AI interests are candidate **tracks/personas**, not separate launched businesses. The user's broad notion of a "productivity audience" is a market hypothesis, NOT one measurable experimental cohort.

## 2. Where new concepts live (do not create new Notion schema)

- **Notion**: use the **existing** MVP Center / "MVP Center — концепции, воркеры и 30 этапов" page as canonical product index. Add a "Concept Backlog" section grouped by product, linked to an existing detailed product concept/decision page. Avoid creating a new database, table schema, unrelated top-level page or project-specific folder without the owner's authorization.
- **Each entry (text/template, no schema migration):** stable concept_id, project, date/source, what changed, target problem, target segment, hypothesis, potential user value, proposed first experiment, decision status, uncertainty, design reference, evidence links, owner, related GitHub Issue/PR.
- **Lifecycle:** idea_captured -> needs_discovery -> hypothesis_ready -> experiment_prepared -> validated | iterating | pivoted | rejected. States are descriptive Notion notes until code supports verified lifecycle. Never infer validation from a merged PR.
- **GitHub**: technical specs/PRs/issues for code, reviewed artifacts and versioned source. **FactoryOS MVP registry**: link to existing concept, experiment and evidence without importing all Notion content or creating a second canonical truth.
- **Read before write**: identify existing project entry, append the smallest change and reference it, do not create duplicate concept cards.

**First canonical concept entry:** MC-FOCUS-001; MyCast / Focus Engine. Hypothesis: a personal morning podcast that revisits user-selected goals, brings relevant sourced ideas and offers one achievable daily prompt may help users keep an important objective salient. Candidate personas: business founders, personal habits (nutrition/fitness/learning), careers, special interests. Claims that it improves focus, habits or weight are **unverified**. Do not provide medical advice or health outcome promises.

## 3. Product placement and single-owner rules

Existing: docs/MVP_FACTORY_SPEC.md says MVP Factory uses mvp_factory.py registry/API, static/mvp-factory/ UI, existing Relay, owner approval, GitHub artifacts; MVP Builder M1 contracts are mvp_builder_request.py, mvp_builder_preflight.py, mvp_builder_manifest.py and mvp_builder_projection.py. Claude must verify current source and open PRs before implementation.

Proposed pipeline:

Owner idea -> MVP Manager / Concept Backlog -> Market Research / Customer Discovery -> Hypothesis & primary metric -> **A/B Tester** (experiment design / variants) -> UI Prototype Worker + **Content Factory** (draft-only creative) -> QA/Security -> Owner review -> (explicit approval for any real publication / spend) -> exposure / conversion evidence -> A/B Tester analysis -> Feedback Manager + Financial Scorer -> MVP Manager decision -> Product Manager backlog.

**Division of responsibilities:**
- MVP Manager: experiment priority, approved hypothesis and handoff; chooses continue/iterate/pivot/stop with owner.
- Market Researcher: real customer problem and segment definition; no fabricated market validation.
- **A/B Tester (new named agent/role):** pre-register test, choose experiment type, specify controlled variable, create copy/variant briefs, request draft renders, enforce exposure/metrics integrity, analyze results and warnings. Not a second scheduler, ChatGPT subscription, parallel worker pool or autonomous ad publisher.
- UI/HTML Builder: drafts/implements variant pages within scoped paths and existing stack.
- Content Factory: drafts platform-specific ad/social creatives, never posts without owner approval and applicable consent.
- QA/Security Reviewer: checks compliance, contrast/accessibility, localization, event correctness, privacy and isolated test traffic.
- Feedback Manager: interviews users about why they did or didn't act, with consent.
- Financial Scorer: cost and optional revenue attribution; unknown costs are unknown, not zero.
- Claude engineering: uses one owner/claim/branch/PR at a time; all code needs tests and independent review.

Reuse Relay queue/claims and MVP Factory status; **do not add** a separate cron, duplicate RelayQueue or unapproved new architecture.

## 4. Three test types: never confuse them

### Mode SEGMENT_COMPARISON (MyCast first recommended exploratory mode)

A = "MyCast for entrepreneurs — focus on business goals".  
B = "MyCast for personal goals — habits / learning / nutrition".

These **do not form a randomized A/B test** if each gets different audiences, placements or creative contexts. Label the report "audience + positioning exploration", stratify by audience/channel, count signups and activated listeners separately, and do NOT claim statistically that A beat B. Can draft two separate landing pages and two sets of ad copy but no live publishing by default.

### Mode CONTROLLED_AB (real A/B within one audience)

Same audience, acquisition source, offer and conversion window. Randomly assign visitors to an immutable A or B, for example entrepreneur headline A "Start your day focused on your business" vs entrepreneur headline B "Personal business briefing in your headphones". Only one intended variable differs; keep price, CTA, route and onboarding consistent. Stable assignment under the chosen consent/privacy rules. Define primary metric and stopping condition **before** traffic begins. Report uncertainty and guardrails.

### Mode CREATIVE_COMPARE (posts or ads)

Same target segment and destination landing page, with two platform-appropriate post/ad drafts. Only compare actual performance if source, targeting, budget, placement and timing are controlled and approved. Organic posts with different audiences/times are observational; report as such. No publishing, ad spend, account access or third-party messages without explicit owner consent.

## 5. Agent request and artifact contract

Before generating any variant, the agent needs:

- project_id, concept_id, owner, version, source and evidence links;
- objective, personas, customer problem, current alternative, hypothesis, falsification criterion;
- experiment_mode and eligible audience, approved distribution channels (none by default);
- exactly one controlled variable for CONTROLLED_AB; primary metric and minimum meaningful effect; time window / sample policy;
- baseline, available product flow / pages, constraints on claim accuracy, language EN/UK/RU and brand;
- approvals with explicit false defaults: preview, deployment, publish, outreach, spending, and privacy-sensitive analytics.

**Proposed versioned manifest** (adapt into existing MVP contracts after code audit; not a new Notion schema):

~~~json
{
  "schema_version": "mvp-ab-1",
  "experiment_id": "MC-EXP-FOCUS-001",
  "project_id": "mycast",
  "concept_id": "MC-FOCUS-001",
  "mode": "SEGMENT_COMPARISON",
  "state": "draft",
  "hypothesis": "Different audience promises attract distinct users",
  "audience": ["entrepreneurs", "personal_habits"],
  "primary_metric": "verified_signup_rate",
  "secondary_metrics": ["cta_click_rate", "activation_rate", "week2_return"],
  "stop_rule": {"basis": "preregistered", "min_eligible_per_variant": null, "max_duration_days": null},
  "variants": [
    {"id": "a", "persona": "entrepreneurs", "headline": "Focus on your business", "landing_ref": null, "creative_refs": []},
    {"id": "b", "persona": "personal_habits", "headline": "Focus on your personal goal", "landing_ref": null, "creative_refs": []}
  ],
  "controls": {
    "approval_preview": false,
    "approval_deploy": false,
    "approval_publish": false,
    "approval_spend": false,
    "approval_contact": false,
    "consent_required": true
  },
  "evidence": [],
  "observations": {"eligible": null, "exposed": null, "converted": null},
  "decision": "pending"
}
~~~

All fields may be mapped into existing data models rather than creating new tables. If a schema migration is truly needed, Claude must propose it with compatibility and rollback before changes. Store version identifiers and source links, not credentials or unnecessary personal data.

**Outputs for each draft experiment:**
1. experiment manifest and reasoning (what differs and why);
2. two responsive, accessible landing drafts or preview routes, preferably shared template + variant data (not duplicated apps);
3. headline/subhead/CTA, 3 concise benefit bullets, social proof only if sourced, privacy/limitations block, legal-friendly wording;
4. **two ad/social text drafts per variant**: short and medium copy, suggested channel, CTA, UTM plan; no real publishing;
5. screenshot / deterministic rendered proof and source file/PR links;
6. pre-registered metrics, event instrumentation status, QA report, open risk/approval list;
7. honest results and manager handoff. Never show synthetic counts as real analytics.

## 6. Preview and exposure workflow

### P0 — safe offline draft-only (first deliverable)

- MVP Factory experiment card under existing product. User selects "Create experiment", test type, goal/segment, primary metric, variants (A/B).
- A/B Tester produces a structured brief and two landing/creative drafts, clearly marked **PREVIEW / NOT LIVE**.
- Variant preview switcher in existing MVP Factory section. Side-by-side comparison on desktop, stacked mobile.
- Save draft state and immutable revision references in existing permitted registry; persist across restart using existing storage policy. Provide artifact links and the exact agent run/claim id.
- Owner can approve a specific revision for preview testing. This is NOT permission for public deploy, ad publication, emails, or paid traffic.

### P1 — controlled distribution and measurement (after P0 review)

- Use existing routed preview only if owner approves access and current security/privacy policy supports it.
- For CONTROLLED_AB use server-stable eligible assignment within one audience. Deterministic keyed randomization (or equivalent justified method); isolate by experiment_id and immutable revision; no fingerprinting or silent re-assignment on refresh.
- CONSENT: track only what applicable privacy policy and consent allow. No raw IP, email addresses, transcripts, user goals or sensitive personal health topics in analytics events. Where consent is absent, fail closed for individual-level tracking. Offer aggregate-only counts if technically and legally justified; document uncertainty.
- Exclude internal QA and bot visits; deduplicate retries and duplicate signups using existing safe, pseudonymous identity where available.
- Support feature flags / kill switch. Suspended/ended experiments must not accumulate new exposure claims.
- No "winner" badge if eligible denominators, instrumentation, sample adequacy or assignment are unknown.
- If public publication is not authorized, reporting remains preview/demo data, labeled as such.

### P2 — analysis and repeatable learning

- Collect factual exposure/conversion counts and cohort-quality signals.
- Show per-variant numerator/denominator, sample window, split, source/segment, dedup rules, guardrails, uncertainty and missing telemetry.
- For sufficiently sized controlled experiments, provide an uncertainty interval (e.g. Wilson for proportions) and effect estimate; pre-registered threshold / stop rule, no repeated peeking presented as conclusive significance. For small tests say "inconclusive".
- For SEGMENT_COMPARISON show separate per-segment funnels, *not* a causal winning variant.
- Capture complaints, reasons, and value-in-use from Feedback Manager. Do not optimize click-through at the expense of actual first podcast and repeat listening.
- Manager records decision: continue | iterate | pivot | stop with evidence, alternative interpretation and next hypothesis.

## 7. Analytics and guardrails

Use the existing event/event journal wherever viable; audit first. **Proposed events** (namespace under MVP Factory if needed):
- experiment_draft_created, variant_revision_created, preview_qa_passed, owner_approval_recorded;
- experiment_exposed (only after legitimate exposure), cta_clicked;
- signup_completed (actual backend success), goal_selected (if real), episode_created (real audio), episode_played (actual player), episode_listened_60pct (if measured lawfully), week2_return (cohort), real_payment_confirmed;
- experiment_paused, experiment_completed, analysis_recorded.

Avoid inventing events not actually implemented; unsupported stages explicitly show "no instrumentation". IDs: experiment_id, revision, variant_id, event_id (idempotent), anonymous/consented user reference where authorized, timestamp UTC, approved acquisition-source tags. No secret or sensitive goal data in event payload.

**Primary metric must match the test's stage:**
- Pre-product exploration: honest verified signup / eligible unique landing views (if both are actually measurable).
- Functional MVP: first real podcast listened / eligible unique signup.
- Retention learning: repeat usage / eligible activated cohort.
- Commercial Validation: real confirmed paid conversion, never survey-only willingness to pay.

Track cost per activated user and TTS/LLM cost before claiming $1/month viable. Product-quality guardrails: broken login, privacy incident, misleading medical/financial claim, high unsubscribe, time-to-first-audio, content source quality. Any safety/privacy breach -> pause.

## 8. UI in MVP Factory (not a new top-level product)

- Add product card's **Concepts** and **Experiments** drill-downs inside the existing MVP Factory/Builder panel. Do not rebuild the global navigation.
- Concept card: concept ID, short thesis, status, owner, date, evidence, linked experiment(s), source.
- Experiment card: mode clearly visible, A/B previews, experiment owner, main hypothesis, traffic status (draft/preview/live/paused), approvals, current verified funnel, caveats, cost.
- Tabs/sections: **Brief**, **Variations**, **Content Drafts**, **Metrics**, **Decision/Evidence**.
- "Request experiment draft" invokes existing permitted MVP Manager/Relay task pattern; no fake running indicator. A named A/B Tester role does not imply an autonomous worker is configured.
- Buttons only if they have a real backing action; no fake launch/test buttons.
- EN/UK/RU parity; accessible contrast, keyboard navigation, mobile layout, responsive media; source controls in owner-only UI.
- Publish or paid campaign buttons require explicit separate owner action with identity, revision, destination, budget and terms, and are OUT OF SCOPE for P0/P1 by default.

## 9. Interface/handoff contracts

**MVP Manager -> A/B Tester:**
- source concept and hypothesis, prior research links, target persona, immutable experiment brief, owners, success metric, allowed asset types, known limits.

**A/B Tester -> UI Builder + Content Factory:**
- clear per-variant content schema, controlled variable, content restrictions, language, SEO/meta requirements, no unsupported benefit claims, exact CTA, no auto-post.

**QA -> Manager:**
- tested routes/screens, accessibility, localization, content claim checks, analytics assertion, event source verification, status/errors, CI link.

**Manager -> Owner:**
- preview links and recommended next action; exact permissions needed; no user outreach or public promotion merely because draft exists.

**A/B Tester -> Feedback Manager:**
- cohort/segment IDs (pseudonymous), observed behavior, interview questions, data limitations, consent scope.

The handoff lives inside existing Relay when possible, with idempotency and factual state. GitHub issues document implementation; they are not a substitute for a live agent's runtime messages. Only one active coding worker per scope.

## 10. Example MyCast experiment package

**Concept:** MC-FOCUS-001 — user-selected focus, interests and goals. Draft voice format: "your goal today" -> 2–3 grounded relevant updates -> one optional concrete next step. Do not promise health outcomes.

**Exploration pair:**
- Segment A: entrepreneurs. Landing: "Start the day focused on your business"; subhead about personal project priorities and relevant business updates; CTA "Listen to a sample".
- Segment B: people working on a personal habit. Landing: "Start the day focused on your goal"; subhead about carefully sourced ideas for a user-selected theme and short focus prompt; CTA "Listen to a sample".
- Two short + two medium ad copy drafts for each. **Only previews** until approved. Track each persona's funnel separately; no overall "winner".

**True A/B example (later):**
- Same entrepreneurs audience, same channel/targeting, same sample and CTA.
- A: "Start the day focused on your business."
- B: "A personal briefing for the business you are building."
- Pre-register exposure and target metric; only headline differs. User's goal selection and audio format remain identical. **Results only after real traffic and credible measurement**.

## 11. Security, safety, privacy, spend and owner gates

- **Never auto-publish** to social networks, ad accounts, Telegram users, email recipients or new public sites.
- **Never auto-enable** paid API billing, buy domains, allocate advertising budgets, new paid hosts or spend credits without separate consent.
- Store no API keys/secrets in PRs, variant output, analytics, source URLs or browser assets.
- Only existing auth/CSRF/session and owner permission checks for experiment approvals, logs and drafts. Prevent variant preview XSS, HTML injection, redirect abuse, disclosure of private user content and unintended public links.
- For health/habit niches do not claim verified weight loss, treatment or medical personalization. For finance, do not claim guaranteed returns. Validate content and sources; suppress unsupported testimonials or fake counters.
- Use no real user goals/behavior records in demo fixtures. Minimize and expire telemetry per existing privacy policy.
- If approval/consent/policy constraints are unclear, feature stays draft/blocked with an actionable reason.

## 12. Required tests and proof

**Unit/integration:**
1. stable concept_id -> project mapping, no duplicate on retry;
2. experiment manifest schema validation, immutable versioning and exact controlled-variable checks for CONTROLLED_AB;
3. assignment stable across repeat visits, no cross-experiment contamination, balanced under deterministic sample, consent handling, no fingerprinting;
4. stop / pause / insufficient sample / missing denominator / broken tracker => no "winner";
5. event idempotency, UTC windows, excludes bots/internal tests, privacy-safe event payload;
6. unsupported events -> "not instrumented" vs numeric zero;
7. no marketing copy published and no paid call on preview generation;
8. two variants / two creative briefs preserved under restart and linked to the concept;
9. authorizations: unauthorized actor cannot approve/deploy/publish/spend or view private test data;
10. EN/UK/RU locale parity, mobile preview layout, keyboard flow, HTML/XSS/URL validation.

**End-to-end acceptance:**
- Owner creates MyCast MC-FOCUS-001 experiment from MVP Factory; sees **SEGMENT_COMPARISON**, hypothesis and explicit draft state.
- A/B Tester uses an authenticated single Relay claim; outputs two distinct responsive landing previews and at least two ad/social copy drafts per variant with revision IDs and exact file/PR links.
- QA confirms test modes and source claims, no real social publication, and no fabricated exposures/conversions.
- Owner sees variants side-by-side; can choose whether to approve a preview. No real public traffic without additional permission.
- A CONTROLLED_AB fixture proves stable assignments and correct numerator/denominator. Demo metrics clearly marked **synthetic**; missing actual analytics display unknown, not zero.
- Fact-based manager decision can cite source evidence and record continue/iterate/pivot/stop. No standalone scheduler or duplicate Relay worker.
- New code in isolated branch, focused tests, FactoryOS CI green, independent Claude/owner review per current engineering rules. No self-merge.

**Engineering verification commands** (run only where code changes actually warrant them): Python compile and smoke as specified in AGENTS.md, dedicated A/B tests, locale parity, dashboard/unit fixtures. Report exact commands and results, plus not-verified integration links.

## 13. Suggested Claude delivery slices (separate claims/PRs, no parallel file ownership)

- **Slice S0 — audit & architecture**: inspect real MVP Factory code/routes/events, active PR overlap, auth policy; produce minimal diff/file map and choose storage of existing models. Confirm contract; no migration by default.
- **Slice S1 — concepts + offline A/B preview**: existing MVP UI gets Concepts / Experiments, versioned draft manifests, two deterministic landing variants and copy drafts from approved input; no real analytics or publishing.
- **Slice S2 — QA and event integration**: safe, consent-compliant event plumbing and controlled experiment assignment only if current platform supports it; mocked deterministic tests and factual states.
- **Slice S3 — analysis + feedback handoff**: reporting with uncertainty, segment vs randomized differentiation, owner decision and Content Factory handoff, no live campaign by default.

**Dependencies / launch gate:** S1 after S0 and docs review; S2 after S1; S3 after S2. If any task overlaps active MyCast account/landing builder PR, stop and ask for coordination. Existing MVP Builder M2/Relay acceptance may block true worker execution. No claim "agent live" until proven runtime claim/events/PR/tests/CI and owner-visible result.

## 14. Definition of done for this specification

- [x] Precise concept placement and no new workspace schema proposed.
- [x] Distinction between audience exploration and actual randomized A/B.
- [x] Named agent responsibilities, preview assets, content variants and strict approvals.
- [x] Existing module references, proposed manifest, analytics/events, test matrix and staged plan.
- [ ] Claude confirms current code model, relevant open PR overlaps, effort and acceptance.
- [ ] Implementation tasks actually claimed, PRs opened and CI green.
- [ ] Real A/B experiment live with approved traffic and verified outcomes.

**References:** Notion MVP Center (link above); docs/MVP_FACTORY_SPEC.md; AGENTS.md; ROADMAP.md; MyCast concept #105 and scope #305; Customer Development playbook in PR #343. Steve Blank's Customer Development supports hypothesis-driven validation, but this particular A/B architecture, endpoints and metrics are **our proposal**, not a quotation from the book.
