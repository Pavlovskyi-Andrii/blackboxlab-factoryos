# Business League · Launchpad protocol

**Status:** L1 (ROADMAP **T-704**) and L2 (**T-705**) are implemented. L3–L4 wait for the owner's decisions T-707-H,
T-708-H and T-709-H.
**Owner request:** 2026-11-18, in chat with Claude. The owner uploaded the *Product Launchpad 2027* curriculum
(Growth Factory), asked what FactoryOS can take from it, approved this spec and the ROADMAP entry. The owner also
relayed ChatGPT's analysis of the same curriculum; the points adopted from it are marked *(ChatGPT)*.
**Mirror:** Build Progress task `44c85c4a-0853-42c2-a8b1-4902c4da39c4`, created through the Design Partner MCP channel
(planned only). This file is the source of truth.

## Why

The curriculum takes a solo founder from idea search to first sales in 14 weeks: 7 weeks of evidence checks
(Discovery), a 7-day MVP and 6 weeks of acquisition channels. Every week runs the same loop (checklist → own attempt →
the same task done together → mentor gate) under strict honesty rules: a fact needs a source and a date, an honest
zero is a result, a like is not a lead and a lead is not a payment, and AI may structure material but never invents
facts or respondents.

That is the operating protocol the AI Business League lacks. Mixed-model teams tend to report progress they did not
make; this protocol replaces "the agents decided" with "the evidence passed a gate". MVP Builder becomes a factory of
verifiable business hypotheses, not only of prototypes.

What we do **not** take: the 14-week calendar, one agent per lesson, or fixed quotas (such as 20 signals) per project.
Agents can run desk research in parallel, but real customer answers, statistics and payments cannot be sped up.

## Position

- A Launchpad layer inside the existing **MVP Builder**: `mvp_factory.py` (registry, stages, evidence links,
  `AGENT_FORBIDDEN_TARGETS`), `mvp_pipeline.py` (agent hand-offs) and `mvp_cycle.py` (phases Battle → Build → Promote →
  Learn). No new taxonomy of stages: the protocol maps onto these phases.
- Same storage pattern as `mvp_experiments.py`: data in `projects[pid].launchpad` of `mvp_factory.json`, under the
  registry lock, idempotency table and event log. No second registry, scheduler, worker or service.
- Launchpad never changes a project stage. Stages still move only through `mvp_factory` advance events with evidence.
- Comparisons of two audiences or offers (D4–D6, channels) are branches of the existing A/B Tester
  (`mvp_experiments.py`, mode `SEGMENT_COMPARISON`), linked by `exp_id`, not a third system. A segment comparison is
  not a controlled A/B test and never declares a winner *(ChatGPT)*.
- Evidence uses the existing levels in `evidence.py`: claimed < linked < checked < accepted.
- The League (L4) reuses `battle_runs.py`: competing chains, the judge (T-584) and outcome attribution (T-583).

## Protocol

| Phase (`mvp_cycle`) | Check | Artifact | Target | Gate after |
|---|---|---|---|---|
| Battle | D1 Idea search | `idea_card` | 5+ ideas | — |
| Battle | D2 Search demand, competitors, reviews | `market_fact` | facts for every idea | G1: 5+ → 3 |
| Battle | D3 Communities and forums | `signal` | 10–20 real signals across the shortlist | G2: 3 → 1–2 |
| Battle | D4 Organic social check | `test_card`, `channel_entry` | 1–2 real actions, reactions recorded (zero allowed) | — |
| Battle | D5 Landing page + waitlist | `test_card`, `channel_entry` | working page, tracked target event, organic visits | — |
| Battle | D6 Paid demand test | `test_card`, `channel_entry` | only after D5; a draft until the owner approves spend | — |
| Battle | D7 Customer interviews | `interview_note` | several real conversations ending with a concrete ask | G3 |
| Build | MVP in 7 days | `channel_entry` (usage) | one user, one task, one result; manual/concierge allowed | G4 |
| Promote | 6 channels | `test_card`, `channel_entry` | direct sales, communities, organic content and demos, SEO + catalogs and launch platforms, partners/affiliates/micro-influencers, paid | — |
| Learn | Verdict and channel | `gate_decision` | one main channel and one main metric | G5 |

Targets are learning targets, not quotas. When a target is not met, the board shows the real count and where the
agents looked; nothing is invented to reach it.

## Gates and authority

| Gate | Question | Who decides |
|---|---|---|
| G1 | Which 3 ideas go on? Every deferred idea keeps its reason. | judge or owner |
| G2 | Which 1–2 directions get active tests? | judge or owner |
| G3 | Build the minimum version / change the key assumption / go back to another idea | owner |
| G4 | Did at least one real user complete the main scenario? Demo views, mock-ups and colleague opinions do not count. | owner |
| G5 | Verdict: continue (scale) / iterate / pivot / kill *(ChatGPT)*; when continuing, the main channel and metric for the next 30 days | owner |

- Agents may *propose* G1/G2 with a rationale and evidence refs. A **judge** is an operator that produced none of the
  compared work (the T-584 rule). No agent decides a gate on its own work.
- Thin evidence produces a named extra check, never an automatic build or scale-up.
- A decision records options, choice, rationale, evidence refs and `decided_by`.

## Agent loop

Each check runs the curriculum's weekly loop: checklist → producer agent attempt → a second model completes and checks
**the same artifact** (no new parallel task) → gate review. Every step is an event on the check, so the board shows who
produced, who reviewed and who decided.

## Artifact schemas (`mvp-launchpad/1`)

| Type | Fields |
|---|---|
| `idea_card` | who, situation, problem, desired_result, where_noticed (URL or `own_experience`), assumptions (kept apart from facts) |
| `market_fact` | idea_ref, source_url, source_kind (`primary` / `secondary`), observed_at, query, alternative, price, complaint, verdict (`for` / `against`), unknowns |
| `signal` | idea_ref, url, posted_at, situation, current_solution, author_words (≤ 280 chars, e-mails and phone numbers redacted), independent (yes/no) |
| `test_card` | one hypothesis, channel, audience, message, creative_ref, page_ref, target_event, period, spend_limit (default 0), stop_condition, success_signal, exp_id (optional A/B Tester link). Written before launch. |
| `interview_note` | consent_ref (required), participant (per-project hash only, never a name or contact), last_real_case, frequency, current_solution, time/money cost, consequences, user/payer/decider, ask_made, outcome (`agreed` / `refused` / `conditions` / `no_decision`) |
| `channel_entry` | channel, action, period, reach, clicks, leads, active_users, main_scenario_done, payments, time_spent_h, money_spent |
| `gate_decision` | gate, options, chosen, rationale, evidence_refs, decided_by |

Every record carries `test` and `synthetic` flags (default false), its evidence `level` and the actor that wrote it.

Source quality is expressed by the evidence level, `source_kind` and `independent`, not by a credibility score the
producing agent assigns itself: a self-assessed score is still only `claimed`.

## Honesty validators (the core of L1)

1. A `market_fact` or `signal` without a source URL and a date is rejected.
2. Missing data is stored as `unknown` and never filled by a model.
3. Zero results are valid entries and are shown as 0 ("honest zero"), never hidden.
4. `test` and `synthetic` records are excluded from every count, funnel, gate metric and score.
5. Likes, views, clicks and CTR never count as demand or payment.
6. A publication ban or zero reach is recorded as a blocker, not as absence of demand.
7. No gate passes on drafts, test or synthetic data.

### Status ladders

Forward only, one rung at a time, every move with evidence:

- campaign: draft → moderation → active → finished | stopped
- listing: submitted → published
- outreach: sent → replied → negotiating → test_confirmed → live
- deal: verbal_yes → invoiced → paid
- usage: demo_viewed → signed_up → main_scenario_done

Skipping a rung (verbal_yes → paid, sent → live) is rejected. `demo_viewed` never counts as usage.

### Evidence rule types (add to `evidence.py`)

| Type | Required level | Meaning |
|---|---|---|
| `market` | linked | a source URL and a date |
| `lead`, `usage` | checked | the server read a recorded form or product event |
| `payment` | accepted | the owner confirms, until a provider receipt checker exists |
| `outreach`, `spend` | accepted | owner approval before the action |

Agents write at most `linked`; `checked` comes only from server checkers; `accepted` only from the owner, as today.

## Budget and spend

- `spend_limit` defaults to 0, and every spend or outreach needs owner approval. ZERO ADDITIONAL SPEND stays in force.
- A paid test becomes eligible only after D5 has a working page, a tracked target event and a defined audience.
- Limit, period and stop condition are fixed before launch and locked for agents afterwards; one change per running test.
- Budget never compensates an unclear offer, and scaling is not a required outcome.
- Revenue is always shown net of model/API, services, commissions and ad spend. Learn shows whether the price covers
  the direct cost per customer (`yes` / `no` / `unknown`). No LTV from a short history.

## Funnels (Learn and the analytics loop)

For every channel, show the stage with the largest drop:

- paid: impression → click → lead → main_scenario_done → payment
- direct sales: contact → reply → call/demo → offer → payment
- communities: post/answer → dialog → click → useful action → payment

Slow channels (SEO: 30–90 days) are never compared with one week of direct outreach. This gives the planned
analytics loop business metrics instead of CTR alone.

## UI: the Launchpad tab

On the MVP Builder project page (`static/mvp-factory/`, the same `T` dictionary pattern):

- Discovery lane: D1–D7 cards with target vs actual (ideas 3/5, signals 7 of 10–20), evidence-level chips and an
  honest-zero badge.
- Gate cards: who may decide, pending or decided, rationale.
- A Needs-you strip for owner-only gates and approvals.
- MVP lane with the first-user gate; 6 channel cards with funnel and largest drop; the Learn card with verdict, main
  channel and metric.
- Status is an icon plus text, never colour only. EN/UK/RU parity. Mobile first at 360–430 px.

## L1 = T-704 (queued)

**Scope:** data contract, validators, gates, authority and the Launchpad tab.

**No external side effects:** no posts, DMs, e-mails, landing publication, ads, payments, partner deals or interviews
are executed. L1 stores plans and evidence only, and every approval flag stays false.

**Seed:** MyCast is the first real project on the board *(ChatGPT)*: its checks start empty and show `unknown`, with no
invented numbers. A separate, clearly labelled synthetic demo project may show a filled board (`synthetic` everywhere,
excluded from metrics).

**Suggested API** (follows `mvp_experiments.py`; actor roles owner / member / agent as in `mvp_factory.record`; every
write takes an idempotency key):

- `GET /api/mvp-factory/{pid}/launchpad`: board view (checks, counts without test/synthetic records, gates, funnels,
  needs-you items).
- `POST /api/mvp-factory/{pid}/launchpad/artifacts`: add an artifact, validated by type.
- `POST /api/mvp-factory/{pid}/launchpad/artifacts/{aid}/status`: one ladder step with evidence.
- `POST /api/mvp-factory/{pid}/launchpad/gates/{gate}`: propose (agent) or decide (judge or owner).
- `POST /api/mvp-factory/{pid}/launchpad/approvals`: owner-only spend or outreach approval of a `test_card`.

**Files:** new `mvp_launchpad.py` and `test_mvp_launchpad.py`; touch `app.py` (a one-line route install, like
`install_mvp_experiment_routes`), `evidence.py` (rule types), `mvp_cycle.py` (Learn facts), `static/mvp-factory/` (the
tab), `DECISIONS.md` and `.github/workflows/ci.yml` (the new test step, which this task allows).

**DONE:** see ROADMAP T-704.

## Later slices

- **L2 Discovery agents, T-705 (implemented in `mvp_launchpad_agents.py`, see DECISIONS.md «2026-11-21 — T-705»):** Researcher and Analyst fill D1–D3 from public sources with
  the existing free tools (FactoryOS `web_search` / `web_read`, Content Brain signals); maximum level `linked`. Their
  benchmark is the manual MyCast run of 2026-11-19 (`docs/business_experiments/mycast_launchpad/`: 6 ideas, 18 facts,
  13 signals, G1/G2 only proposed; the owner decides in T-706-H). `web_search` covers Wikipedia only until the owner
  opts in to Google search through Gemini (T-560-I), which can be billed beyond the free tier.
- **L3 MVP + Promote:** the 7-day MVP checklist with an API cost limit; channel journals fed by the analytics loop;
  Approval Studio extended from approve-publish to approve outreach, spend and payment.
- **L4 League:** `battle_runs` kind `business`. Two or three teams of mixed operators (ChatGPT + Claude, Claude +
  Gemini, all three) run the same protocol, with a judge per gate, a leaderboard built only from `checked` and
  `accepted` metrics, net-revenue scoring with penalties for false "done" claims (Evidence Protocol T2.5) and a season
  long enough for real market tests (ads, communities, SEO).

### Owner decisions before L3/L4 (`[HUMAN]` tasks with runbooks in Your tasks)

Options, sources and labelled recommendations: `docs/business_experiments/LEAGUE_OWNER_DECISIONS.md`.

- **T-707-H:** the League budget, who approves each spend, season length, team compositions and the judge.
- **T-708-H:** which real channels agents may act in, and from which accounts.
- **T-709-H:** the payment provider for the owner's country and business form.
