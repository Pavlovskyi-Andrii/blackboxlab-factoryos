# RFC: internal Growth Manager and Owner Home (T-733, issue #452 §6–§7)

Date: 2026-11-24 · Author: Claude (interactive session) · Status: **proposal for the owner gate**. Nothing here is built.
Base: `main` at v5.19.1 plus T-729/T-730. Direction: 2 «Products and goals», chosen by the owner on 2026-11-24
(`.autopilot/answers.md` «#452 Checkpoint A»).
Related: `docs/ux/factoryos-owner-first-ia-spec.md` (screens), `docs/research/ploy-public-ux-functional-benchmark.md`
(patterns), prototype `docs/prototypes/owner-home-growth/index.html` (Learning → «New home: products and goals»).

## 1. Summary
FactoryOS already has most of a growth manager. Its parts are spread over several modules:
- the Launchpad test card and funnel (`mvp_launchpad.py`);
- the A/B experiment with owner-only approval and decision (`mvp_experiments.py`);
- evidence levels (`evidence.py`);
- the research agents (`mvp_launchpad_agents.py`);
- Relay claims and run ids (`relay_execution.py`);
- the social weekly plan (`social_autopilot.py`).

This RFC adds **one small entity, the Goal**. It also adds a **read model** that shows one goal across those stores,
and **one first-party visit counter** for MyCast pages. There is no new scheduler, queue, claim system, agent runtime,
paid service or publishing path.

## 2. Non-goals
- Not a site builder, hosting, a CRM, ad buying or outbound messaging (benchmark R-04…R-07).
- No schedule or webhook triggers. Goals start by hand. Schedules stay design-only until the owner authorises them separately.
- No change to the publishing gate, the social autopilot approval modes or the Surfer policy.
- No production dashboard replacement. Owner Home sits behind a flag; the current dashboard stays as «Pro version».

## 3. Mapping: mission fields → existing storage
The issue lists 23 mission fields (Amendment A1 said 24; the list has 23). "Missing" rows are the only new storage.

| Field | Where it lives today | Status |
|---|---|---|
| `id` | — | **Missing**: `goal_id` (`g-<slug>-<n>`) |
| `project_id` | `mvp_factory` project id | Exists |
| `goal` | MVP brief `goal` text; brand passport step 1 "Goal & KPI" (free text) | **Missing as structure**: `outcome` {text, metric, target, until} |
| `hypothesis` | Launchpad `test_card.hypothesis`; `mvp_experiments` `hypothesis` | Exists |
| `audience` | Launchpad `test_card.audience`; experiment branch `persona` | Exists |
| `channel` | Launchpad `test_card.channel`, `CHANNELS`; experiment `CHANNELS = ("facebook","tiktok")` | Exists, **gap**: experiments do not know `telegram` (small change, §11 B-03) |
| `inputs` | Launchpad artifacts (idea cards, market facts, signals) | Exists |
| `steps` | `mvp_cycle.py` phases battle/build/promote/learn; Launchpad checks D1…LEARN | Exists as phases; the goal adds the ordered step list of §5 (read model, not storage) |
| `dependencies` | Launchpad `GATE_CHECKS` | Exists |
| `owner` | Relay claim `lane` / `worker_id`; project owner | Exists |
| `state` | MVP `STAGES`, Relay execution states, evidence levels, experiment state | Exists, **projected** (§4) |
| `trigger` | Owner button (Discovery run is owner-started) | Exists (manual only) |
| `estimated_cost` | — | **Missing**: per step, from the executor table (§7); `$0` for every current executor |
| `approved_cost_cap` | `FACTORY_DAILY_BUDGET_USD` (global); experiment branch `approval.spend=false` | Exists globally; goal stores `cost_cap_usd`, default `0` |
| `approval_policy` | Experiment `approval{preview,publish,spend,outreach}`; Launchpad owner-only gates; social modes A/B/C | Exists |
| `artifacts` | Launchpad artifacts; experiment branch `copy`, `content_job_id` | Exists |
| `evidence` | Launchpad `LEVELS`; `evidence.py` | Exists |
| `started_at` / `finished_at` | Relay ticket history; MVP events | Exists |
| `metrics` | Launchpad `FUNNEL` and `NUMBERS` (manual); experiment `measurement{eligible_views,signups,activated,cost_usd}`; MyCast accounts | Exists, **gap**: no visit or variant counter (§8) |
| `errors` | Relay `blocked`/`failed` with reason; experiment branch `blocked` | Exists |
| `idempotency_key` | Experiment create `idempotency_key`; Relay `event_id` | Exists; the goal adds `goal:<id>:<step>:<revision>` |
| `version` | Experiment branch `revision`; `SCHEMA` strings | Exists; the goal adds `revision` |

## 4. States: proposed vocabulary → existing enums
No backend enum is renamed. The goal's state is computed from the stores below. It is never stored twice.

| Proposed (issue §7) | Computed from | Owner word (IA spec §5) |
|---|---|---|
| `draft` | Goal saved, not started | Waiting |
| `planned` | Goal started; next step has no Relay ticket yet | Waiting |
| `queued` | Relay ticket `queued` | Waiting |
| `claimed` / `working` | Relay execution in `ACTIVE_STATES` (`claimed`, `running`, `checkpoint`, `committed`, `pushed`) with a fresh heartbeat | Working |
| `needs_review` | Experiment branch preview awaiting `approve-preview`; Launchpad gate G3–G5 waiting; open question | Needs you |
| `approved` / `rejected` | Experiment `decision` (`CHOICES`), Launchpad gate decision | Done, checked / Stopped |
| `published` | Social item in `SENT_STATES` with `published` | Done, checked |
| `measured` | Funnel step with a measured value inside the goal window | Done, checked |
| `learned` | Launchpad `LEARN` check passed and G5 decided | Done, checked |
| `blocked` / `failed` | Relay `blocked`/`failed`; experiment branch `blocked` | Stopped |
| `cancelled` | Goal `cancelled_at` set by the owner | Stopped |

## 5. Vertical slice: «MyCast: first 100 genuine registrations»
Each step lists: who runs it, what it reads, what it writes, its pre- and post-conditions, and how it recovers.

| # | Step | Executor (today) | Pre-condition | Post-condition (evidence) | Recovery |
|---|---|---|---|---|---|
| 1 | Goal draft | Owner in the wizard | Product exists | Goal record, `revision=1`, cost cap `$0` | Edit or cancel |
| 2 | Research | `DiscoveryAgents` (Gemini Flash free tier for writing; search goes through `WEB_SEARCH`, Wikipedia unless T-560-I); Surfer page reads | Goal started by the owner | Launchpad D1–D3 artifacts, at most `linked`; every source with URL and date | Relay Retry; a failed source becomes "unknown", never a guess |
| 3 | Two hypotheses | EC2 Claude worker through a Relay ticket (subscription, $0) | D1–D3 present | Two `test_card`s with `hypothesis`, `audience`, `target_event`, `period` | Retry; the owner can edit cards |
| 4 | Two landing drafts | EC2 Claude worker → `POST …/experiments/{id}/branches/{a,b}/draft` | Test cards exist | Branch `copy` in EN/UK/RU; DENY and PII validators pass | Validator error → step `blocked` with the code |
| 5 | QA | Deterministic checks (copy validators, link check, language parity, 390 px render) + Claude worker review | Both drafts exist | QA report artifact `checked` | A failing check blocks step 6 |
| 6 | Owner decision | Owner: `approve-preview`, then `decision` | QA report exists | Decision with actor, time and reason; **no publication** | Undo before step 7 |
| 7 | Publication draft | `social_autopilot` plan item, status `draft` | Decision made | Draft post that links to the chosen variant | The owner approves it under the active mode (owner chose A on 2026-11-18); nothing else publishes |
| 8 | Measure | First-party counter (§8) + MyCast accounts | Variant page live (owner-approved) | Funnel per variant: visits, registrations, first episode; payment "not connected" | Unknown stays unknown; the owner and test accounts are excluded |
| 9 | Learn | Claude worker summary → Launchpad `LEARN`, G5 proposal | Window closed or the owner asks | Summary citing counts, window and cost; next experiment proposal | The owner decides G5 |

"Done" for the goal means the artifacts exist, and the result is either measured or reported as unavailable.

### Genuine registration
- A MyCast account created through a real Telegram or Google sign-in, counted once per `provider:pid` key.
- Not counted: the owner's own keys and test accounts.
- The account store has no flag for this today. Proposal: `FACTORY_MYCAST_EXCLUDE_KEYS` (non-secret list of `provider:pid`) plus a `test: true` mark on accounts created by QA (B-04).
- The baseline count is read once through the owner API on the day the goal starts and stored on the goal with its date.

## 6. Goal entity
Stored inside the existing MVP registry record (`mvp_factory.json`, `projects[pid].goals[]`). It reuses the
registry lock and event log; there is no new file and no new database.

```json
{
  "id": "g-mycast-1",
  "revision": 1,
  "outcome": {"text": "First 100 genuine registrations", "metric": "genuine_registrations", "target": 100,
               "until": "2026-12-31"},
  "audience": "Busy people who want compressed news on one chosen topic",
  "channels": ["telegram"],
  "languages": ["en", "uk", "ru"],
  "cost_cap_usd": 0,
  "baseline": {"value": null, "measured_at": null},
  "experiment_ids": [],
  "test_card_ids": [],
  "state": "draft",
  "created_by": "owner", "created_at": "…", "started_at": null, "cancelled_at": null,
  "idempotency_key": "…"
}
```

Changing the objective mid-run creates `revision + 1`. Steps already running finish under the old revision and are
shown as such. New steps use the new revision. Nothing is silently rewritten.

## 7. Executors and incremental cost (A1.7)
| Step | Executor | Runs on | Incremental cost |
|---|---|---|---|
| Research | `DiscoveryAgents` + `WEB_SEARCH` + Surfer reads | Render process; Gemini free tier; EC2 Surfer | $0 |
| Hypotheses, drafts, review, learning summary | EC2 Claude worker via Relay claim | Owner's Claude subscription | $0 |
| QA checks | Python validators, Playwright render | Render / CI | $0 |
| Publication | `social_autopilot` | Owner-approved channels | $0 (no ads) |
| Measuring | First-party counter, account store | Render | $0 |
| Ads, paid enrichment, outbound mail | — | — | **No executor at $0. Not proposed.** |

Known limit: research search is Wikipedia unless the owner opts in to Google search (T-560-I, declined on 2026-11-18). This narrows what step 2 can source. The screen will say so; it will not pretend broader coverage.

## 8. First-party visit and variant counter (first implementation PR)
The gap that blocks an honest funnel (A1.2). The design:
- `POST /api/mycast/v`: public, no auth, rate-limited per IP hash. Body: `{page, variant, ch}` only.
- Stored as JSON lines in `DATA_DIR/mycast_visits.jsonl`: `{ts, page, variant, channel, day_key, synthetic}`. `day_key`
  is a hash of (IP, user agent, UTC day, server salt) that rotates daily. The raw IP and user agent are never stored.
- No cookie, no localStorage, no third-party script. Known bots are dropped by user agent. The `?synthetic=1` flag is
  set by QA runs, and those rows are excluded from counts.
- `channel` comes from `?ch=` on the link the post carries, for example `?ch=tg&v=b`. The variant comes from the page
  that was served.
- Registrations get the same `variant` and `channel`. The configurator already forwards `ref`; it would forward `v`
  and `ch` the same way into the account record (`acq: {variant, channel}`).
- Retention: rows older than 120 days are compacted into daily counts.
- Feature flag `FACTORY_MYCAST_VISITS_ENABLED`, default off.
- Privacy page wording changes need the owner's review before the flag is turned on.

## 9. API (proposed; follows `/api/mvp-factory/{pid}/…` conventions)
| Method and path | Who | What |
|---|---|---|
| `POST /api/mvp-factory/{pid}/goals` | owner, member of the workspace | Create a goal draft (idempotency key required) |
| `GET /api/mvp-factory/{pid}/goals/{gid}` | owner, member, viewer | Read model: goal, computed state, plan steps with sources, funnel, evidence, next action |
| `POST /api/mvp-factory/{pid}/goals/{gid}/start` | owner | Creates the first step's Relay ticket. Refused if the cost cap would be exceeded |
| `POST /api/mvp-factory/{pid}/goals/{gid}/revise` | owner | New revision |
| `POST /api/mvp-factory/{pid}/goals/{gid}/cancel` | owner | Cancel; open tickets are released, finished artifacts stay |
| `GET /api/factory/owner-home` | owner, member (scoped), viewer | Home read model: the IA spec §4 table, one source per tile |
| `POST /api/mycast/v` | public | Visit event (§8) |

Decisions reuse the existing experiment endpoints (`approve-preview`, `decision`), so there is no second approval API.
Members only see goals of their workspace (`workspace_tenancy.py`). Viewers never see write controls.

## 10. Safety invariants
- One active claim per step, using the existing Relay claim. A second claim is refused.
- A chat message, a Telegram reply or an agent output is never an approval. Approvals come only from the owner's
  authenticated button on a specific decision record.
- Publishing, spending and outreach each need their own scoped approval. The cost cap defaults to `0`.
- No credentials in goal records, logs, artifacts, pages or Notion.
- Synthetic and test rows are flagged at write time and excluded from every count.
- "Unknown" is never shown as `0`.

## 11. Backlog (atomic, after the owner gate)
| ID | Task | Files | Depends | Tests |
|---|---|---|---|---|
| B-01 | **First-party visit and variant counter** (first PR) | new `mycast_visits.py`; route in `app.py`; one `fetch` beacon in `mycast_public.py` pages and `static/mycast-configurator/index.html`; `test_mycast_visits.py` | — | Rate limit, no PII stored, bot drop, synthetic excluded, flag off = 404, counts per variant and channel |
| B-02 | Goal entity + read model | `mvp_factory.py` (goals in the record), new `growth_goals.py`, routes; `test_growth_goals.py` | — | Create/idempotency, revision, cancel releases tickets, computed state from fixtures, member scoping |
| B-03 | `telegram` channel for experiments | `mvp_experiments.py` `CHANNELS`; tests | — | Existing experiment tests + new channel |
| B-04 | Genuine registration filter | `mycast_accounts.py` (`test` mark, exclusion list), owner listener API | — | Owner and test keys excluded; baseline read |
| B-05 | Owner Home read model `GET /api/factory/owner-home` | new `owner_home.py`; `test_owner_home.py` | B-02 | One source per tile; hidden when empty; unknown ≠ 0 |
| B-06 | Owner Home UI behind `FACTORY_OWNER_HOME_ENABLED` with the «Pro version» switch remembered per browser | `static/index.html` (new view, hash routes), EN/UK/RU strings | B-05 | `test_locale_parity.py`, `test_navigation.py`, screenshots 390/768/1440 |
| B-07 | Goal wizard + goal page UI | `static/index.html` | B-02, B-06 | Same as B-06 + wizard keeps answers on Back |
| B-08 | A/B compare view on the experiment | `static/mvp-factory/` or `static/index.html` | B-03 | Decision ≠ publish wording; reject needs a reason |

### First PR to file level (B-01)
- `mycast_visits.py`: `VisitLog(path)`, `record(page, variant, channel, ip, ua, synthetic)`, `counts(since, until)`.
  A daily salt is kept in `DATA_DIR`, and the module never keeps IP or user agent.
- `app.py`: `install_mycast_visit_routes(app, VisitLog(DATA_DIR / "mycast_visits.jsonl"))` behind `FACTORY_MYCAST_VISITS_ENABLED`.
- `mycast_public.py`: the served pages add one same-origin beacon (no library), with the variant taken from the page.
- `test_mycast_visits.py`; CI line next to the MyCast tests.
- Not in this PR: UI, goals, experiments.

## 12. Test strategy
Unit tests for each new module. Contract tests for every new route, including auth for owner, member, viewer and anonymous. One end-to-end run on a fixture with synthetic rows that must not appear in counts. Screenshots at 390, 768 and 1440 in EN, UK and RU for each UI PR. Approval-gate tests: a goal never publishes or spends without the scoped approval record.

## 13. Rollout and rollback
- Three flags, all default off: `FACTORY_MYCAST_VISITS_ENABLED`, `FACTORY_GROWTH_GOALS_ENABLED`, `FACTORY_OWNER_HOME_ENABLED`.
- Each flag can be switched off without data loss. Goal records stay in the registry, and visit logs stay on disk.
- No schema migration of existing stores; goals are an optional list in the project record.
- The current dashboard stays reachable as «Pro version» in every configuration.
