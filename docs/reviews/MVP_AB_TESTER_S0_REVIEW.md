# MVP A/B Tester: S0 technical audit and review of spec PR #347

**Issue:** #348 (S0 audit). **Spec under review:** PR #347, `docs/specs/MVP_AB_TESTER_V1.md` and
`docs/prototypes/mvp-builder/ab-branches-preview.html`. These were read from `pr347` (`git fetch origin pull/347/head:pr347`,
head `e6a45ba`, merge-base with `origin/main` `3618169`). The PR has the same commits as remote branch `chatgpt/mvp-ab-tester-spec`.
**Code audited:** working tree at `883b644`, with `origin/main` (`e8a6bac`) merged in. **Date:** 2026-11-14. **Author:** Claude (S0 only).

> **Status: SPEC REVIEWED. THE A/B TESTER IS NOT BUILT.** No code, route, registry field, UI, Relay task or Content
> Factory handoff for experiments exists in FactoryOS. This document changes no code. It does not authorize
> publishing, ad spend, paid APIs or outreach.

---

## 1. Verdict on PR #347

**Merge it as a spec (docs only), after the corrections in section 4.** The PR touches only two new files
(`git diff origin/main...pr347 --stat`: spec +385 lines, prototype +90 lines). It adds no code, CI change or schema
change, so it cannot break the build.

What is right and should be kept:
- It separates SEGMENT_COMPARISON (audience and positioning exploration) from CONTROLLED_AB (randomized test within one
  audience). It forbids a "winner" claim without real denominators (§4, §6 P2, §7A.5 item 7).
- Every approval defaults to false. There is no auto-publish, no paid API and no new scheduler, Relay queue or Notion schema (§3, §11).
- Unknown values are shown as "not instrumented", never as zero (§7A.3). Demo data is labelled (§12).
- The work is staged into S0–S3 with one claim per scope (§13).
- The prototype says "DEMO · not connected to real campaigns" and "segment comparison, not a randomized A/B test".
  It contains no fake metrics: every metric card says "Нет данных / Not measured".

What blocks treating it as an implementation contract **as written**:
- It has two incompatible data shapes (§5 `variants[]` with `mode`, and §7A.2 `branches[]` with `comparison_type`). IDs differ
  between them (`"a"` vs `"A"`), and both differ from the registry's ID format.
- It assumes the MVP Builder M1 contracts are live integration points. They are not wired into the app (see 2.4).
- It adds a third mode (CREATIVE_COMPARE), per-branch analytics events and consent tracking. Nothing in the current
  stack supports these, and they are out of scope for S1–S3.
- The A/B Tester sits in the pipeline *before* build. In the existing state machine, Content Factory and promotion
  come *after* `validated` (`mvp_cycle.py:22-27`, `mvp_factory.py:41`). The spec does not say how an experiment
  relates to the project stage.

---

## 2. Integration map (what exists today)

All references below were read in this session. "Does not exist" means a grep of the tree found nothing.

### 2.1 MVP registry: `mvp_factory.py` (315 lines)

| Item | Location | Notes |
|---|---|---|
| Stages / NEXT / ROLE | `mvp_factory.py:33-41` | 11 stages, `idea` … `validated`/`rejected`. |
| Owner-only and agent-forbidden targets | `mvp_factory.py:42,45` | `validated`/`rejected` are owner-only. Agents can never move a project into `build_queued`, `preview_ready`, `owner_review`, `validated` or `rejected`. |
| Event kinds | `mvp_factory.py:46` | `advance, block, unblock, reject, note`. |
| Evidence link shape | `mvp_factory.py:50-52` | GitHub issue/pull/commit/actions, `/static/...`, `/api/mvp-factory/<pid>/artifacts/<name>`. Checked for shape only (`EVIDENCE_CHECK`, `:54`). |
| ID format | `mvp_factory.py:53` | `^[a-z0-9][a-z0-9-]{1,40}$`, lowercase only. |
| Project record (seed) | `mvp_factory.py:96-98` | `id, title, issue, stage, blocked, prototype, cost_usd, approval{deploy,outreach,publish}, created_at, updated_at` |
| Project record (owner-added) | `mvp_factory.py:228-230` | Same fields, plus `brief` (≤ 8000 chars). |
| File format | `mvp_factory.py:99` | `{"version":1,"projects":{id:record},"events":[...],"keys":{...}}` |
| Storage | `mvp_factory.py:102-129`; `app.py:947` | One JSON file `DATA_DIR/mvp_factory.json`. Atomic `os.replace`, one `threading.Lock`. Events capped at `MAX_EVENTS=2000`. A damaged file returns 503 and is never reseeded (`:122`). |
| `snapshot()` | `mvp_factory.py:131-140` | Returns **the whole project dict** plus recommendation, progress and the last 20 events. |
| `record()` | `mvp_factory.py:142-201` | The only stage mutator. Idempotent by key, with conflict detection (409). Applies the owner and agent gates. |
| `add_project()` | `mvp_factory.py:203-236` | Owner or member only. |
| Routes | `mvp_factory.py:265-315` | `GET /api/mvp-factory` (`:274`), `POST /api/mvp-factory/{project_id}/events` (`:281`, owner/member), `POST /api/mvp-factory/projects` (`:300`). |
| Install | `app.py:1124` | `install_mvp_factory_routes(app, MVP_REGISTRY, request_identity)` |

There is **no `experiment`, `concept`, `variant` or `branch` field** anywhere in the registry.

### 2.2 MVP Builder pipeline and cycle (wired in `app.py`)

| Item | Location | Notes |
|---|---|---|
| Pipeline state | `mvp_pipeline.py:132-170` | Separate file `DATA_DIR/mvp_pipeline.json` per project: `autopilot, variant, spec_version, build_ticket, last_error`. |
| Artifact store | `mvp_pipeline.py:34-61` | `DATA_DIR/mvp_artifacts/<pid>/<name>`. Name `^[a-z0-9_.-]{1,60}$`, ≤ 60 000 chars. |
| Agent hand-off tick | `mvp_pipeline.py:243-280` | Research → spec (Gemini, free key) → owner approval → one Relay ticket for build. |
| Existing scheduler | `app.py:9635-9643` (`mvp_pipeline_loop`, 60 s), started at `app.py:7846` | **The A/B Tester must not add a second loop.** |
| Relay build ticket | `app.py:980-983` | `RELAY_STORE.create(..., source={"channel":"mvp","source_key":key}, owner="claude")` |
| Build done = evidence | `app.py:974-977` (`_mvp_ticket_done`) | Merged PR + CI, no override. |
| Owner helper | `app.py:986-989` (`_mvp_owner`) | Owner only, or owner+member. |
| Artifact read | `app.py:992-1000` | Any signed-in user. Served as `text/markdown` or `application/json` only. |
| Autopilot toggle | `app.py:1003-1012` | Owner only. |
| **Spec approval (pattern to reuse)** | `app.py:1015-1029` | Owner only. Writes a registry `advance` with the artifact as evidence and `idempotency_key=f"mvp:{pid}:approve:{version}"`. |
| Spec redo (Battle A/B/C) | `app.py:1032-1047` | `variant` = A/B/C research variant. **This is a name collision with experiment branches A/B** (correction C3). |
| Cycle view | `app.py:1050-1063`; `mvp_cycle.py:22-87` | Phases battle/build/promote/learn. `learn` has no stages (`mvp_cycle.py:26`). The Promoter agent (`engine:"content_factory"`) is active only at `validated` (`mvp_cycle.py:36-37`). |
| Agent chat | `app.py:1066-1105`; `mvp_cycle.py:89-128` | Claude roles go through `OWNER_QUESTIONS`, Gemini roles answer directly. |

### 2.3 UI

- **Dashboard** `static/index.html`: MVP card `#mvpProjects` (`:756`), new-project modal (`:783`), loader `fetch('/api/mvp-factory')` (`:3018`),
  `mvpProjects()` (`:3037`), `mvpRenderPanel()` (`:3158`), `mvpPipelineHtml()` (`:3183`, holds the spec approval gate and the A/B/C variant select at `:3197`).
  i18n keys `mvpb.*`, `mvpp.*` and `mvpc.*` (`:2270-2277`) are covered by `test_locale_parity.py`. The mobile breakpoint is at `:533`.
- **Standalone page** `static/mvp-factory/index.html` (223 lines): reads `GET /api/mvp-factory` (`:159`) and posts events (`:208`).
- CI extracts and runs `node --check` on both inline scripts (`.github/workflows/ci.yml:209-217` and `:256-261`).
- The PR #347 prototype `docs/prototypes/mvp-builder/ab-branches-preview.html` is a standalone static file. Nothing links to it.

### 2.4 Builder M1 contracts: offline only

`mvp_builder_request.py`, `mvp_builder_preflight.py`, `mvp_builder_manifest.py` and `mvp_builder_projection.py` are pure modules. Only their
own tests import them (`ci.yml:262-268`). **`app.py` does not import any of them.** The spec's §3/§5 phrase "adapt into existing MVP contracts" must not
be read as "there is a live manifest pipeline to plug into".

`/api/factory/mvp` **does not exist**. The real prefix is `/api/mvp-factory`.

### 2.5 Relay

- `relay.py:52` `RelayStore`. `create()` (`:118-175`) is idempotent by `source.source_key`. Tickets start `inbox` / `execution.state="queued"`.
- Routes are set up by `install_relay_routes` (`relay.py:1594`). These include `POST /api/relay/worker/claim` (`:1696`), `.../roadmap-claim` (`:1705`) and `.../worker/event` (`:1721`).
  A ticket becomes "claimed" only through an authenticated worker claim.
- `autopilot/relay_tasks.py:1-6` runs tickets with the existing Claude subscription worker inside the existing autopilot loop. It has no second process.
- Any A/B Tester job (a variant copy draft, a landing build) must be a normal `RELAY_STORE.create(...)` ticket with a deterministic
  `source_key` such as `mvp:<pid>:exp:<exp>:<branch>:<artifact>:r<rev>`. This is the same pattern as `app.py:981`. Until a worker
  actually claims the ticket, the UI shows queued/blocked.

### 2.6 Content Factory / Content Brain / brand strategy

- A Content Factory unit is a **job**: `POST /api/jobs` → `create_job` (`app.py:10704-10716`). It inserts an `inbox` / `idle`
  job and **does not start any LLM run**.
- Content Brain: `GET/POST /api/content-brain*` (`app.py:10632-10688`). It makes paid LLM calls behind `_content_brain_budget_guard`
  (`app.py:3572`). **The A/B Tester must not call it implicitly.**
- `brand_strategy.py`: a plan row becomes a job through `strategy_plan_job` (`brand_strategy.py:571-610`). The row is claimed atomically under the store lock.
  `job_id` is attached by durable id. `brand_for_job()` (`:392-411`) gives the brand's Master Brief to the agents of that job
  (used at `app.py:7997-8002`). A job made elsewhere can be linked with `POST /api/factory/strategy/{brand}/jobs/{job_id}/link` (`:612-618`).
  **This is the right template for a per-branch Content Factory handoff**: one job per branch, attached by durable id, claimed atomically,
  and linked to the MyCast brand so it inherits the Master Brief.
- `battle_runs.py` (T-582/T-583/T-584, `battle_runs.py:1-16`) already does chain-level outcome attribution that uses "only real performance
  snapshots" (`build_leaderboard`, `:651`). Its concept (attribute only after a human-approved publish) should be reused in S3. Its storage
  (SQLite, operator chains) is a different thing, so do not merge the two.

### 2.7 Approval and publishing gate (must not be weakened)

- `POST /api/jobs/{job_id}/approve` (`app.py:10792-10812`) records `approval_decisions`. It **only queues** a publish item:
  "Publishing still requires a separate schedule/publish action".
- `_publish_approval_gate()` (`app.py:10074-10090`) is the last check before any adapter runs. It needs the latest `approved` decision
  for **that job**, and a stale or foreign decision fails closed. Publishing also needs explicit scheduling first (`app.py:10092-10100`).
- The viewer role is read-only for every non-GET request (`app.py:1224-1228`). Note: `GET /api/mvp-factory` returns the whole project
  record to any signed-in user, viewers included, so **no personal data may ever enter an experiment record**.

**How branch-level approvals reuse this:**
1. *Preview approval of a branch revision* is an MVP-registry decision. Add an owner-only route modelled on `/spec/approve` (`app.py:1015`).
   It writes one registry event with evidence = the branch artifact link and
   `idempotency_key = mvp:<pid>:exp:<exp>:<branch>:approve-preview:r<rev>`. It sets `branch.approval.preview = {"rev": n, "event_id": ...}`.
   Approving revision n never approves n+1.
2. *Publish approval of branch creatives* is **not** an MVP-registry flag. It is the existing job approval (`/api/jobs/{id}/approve`) on that
   branch's own Content Factory job. It then goes through the unchanged `_publish_approval_gate`. An MVP flag must never satisfy the publish gate.
3. *Spend / outreach / paid channels*: these have no backing action today. They stay `false` and read-only in S1–S3 (shown as disabled with a reason).

### 2.8 Where `experiment` with branches A/B lives (recommended)

Put it **inside the existing project record** in `mvp_factory.json`. Do not add a new file, DB, Notion database, cron or service:

```jsonc
// data["projects"]["mycast"]["experiments"] = { "<experiment_id>": {...} }   (absent key == no experiments)
{
  "id": "mc-exp-focus-001",            // ID_RE-compatible (mvp_factory.py:53); display as MC-EXP-FOCUS-001
  "schema": "mvp-experiment/1",
  "mode": "SEGMENT_COMPARISON",        // enum: SEGMENT_COMPARISON | CONTROLLED_AB  (CREATIVE_COMPARE deferred)
  "concept_id": "mc-focus-001",
  "hypothesis": "...", "primary_metric": "verified_signup_rate", "metric_status": "not_instrumented",
  "state": "draft",                     // draft | preview_approved | closed   (no "live" in S1–S3)
  "created_at": "...", "created_by": "<email>", "revision": 1,
  "branches": [                         // exactly 2, order is A then B; UI order derives from this, no "position" field
    {"id": "a", "label": "Business focus", "persona": "entrepreneurs",
     "revision": 1, "artifacts": {"landing": "/api/mvp-factory/mycast/artifacts/exp-mc-exp-focus-001-a-r1.json"},
     "content_job_id": null, "relay_ticket": null,
     "stage": "concept_proposed", "blocked": null,
     "approval": {"preview": null, "publish": false, "spend": false, "outreach": false},
     "channels": [{"id": "facebook", "status": "placeholder"}, {"id": "tiktok", "status": "placeholder"}],
     "measurement": {"eligible_views": null, "signups": null, "activated": null, "cost_usd": null}},
    {"id": "b", "...": "same shape"}
  ],
  "decision": null                      // owner-only: {"choice": "continue_a|continue_b|both|iterate|pivot|stop", "event_id", "evidence"}
}
```

- Write it only through new `MvpRegistry` methods under the same `_lock`, `_load`/`_save` and `keys` idempotency table. Every mutation
  also appends an event to `data["events"]` (fields `project`, `experiment`, `branch`, `evidence`, `evidence_check`), so the audit trail stays single.
- Add **no stage** to `STAGES`. The project stage and the experiment state are orthogonal. Adding a stage would change `progress()`
  (`mvp_factory.py:239-248`), `mvp_cycle` phases and existing tests.
- Do not bump `version` and do not write a migration in `_load`. Treat a missing `experiments` key as empty (see the #313 collision in section 3).
- Keep variant copy (headline, subhead, CTA, bullets, ad drafts) as JSON artifacts in the existing `ArtifactStore`, not inline in the registry.
  The registry stores only references, revisions and states, so `snapshot()` stays small.

### 2.9 Code ownership

`mvp_factory.py`, `mvp_pipeline.py`, `mvp_cycle.py`, the MVP sections of `app.py`/`static/index.html` and `static/mvp-factory/` are
Claude-owned (`docs/MVP_FACTORY_SPEC.md:3`; `mvp_factory.py:3-4`). The PR #347 spec names ChatGPT as documentation owner and Claude as the
proposed engineering owner. **`ROADMAP.md` contains no A/B or experiment task** (a grep for `mvp|a/b|experiment` hits only T-582 Battle Run, `ROADMAP.md:460`).
S1–S3 therefore need ROADMAP entries with `Owner: claude`, as `CLAUDE.md` and `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md` §1 require, before anyone claims them.

---

## 3. Collision check (git only; no GitHub API available in this audit)

Method: `git fetch origin --prune`, `git branch -r` (155 remote branches), then filtered by
`mvp|builder|mycast|ab|explainer|experiment|concept`. For each branch I ran `git log -3` and `git diff --stat origin/main...<branch>`.

| Remote branch | Ahead of main | Files vs main | Overlap with A/B scope |
|---|---|---|---|
| `chatgpt/mvp-ab-tester-spec` (= PR #347) | 3 | the two spec files | Under review here. Docs only. |
| **`chatgpt/faceless-creator-mvp-builder-313`** | 13 (last 2026-11-13) | `mvp_factory.py` +97, `test_mvp_factory.py` +208 | **HIGH.** It changes `_seed` and `_load`, sets the registry `"version": 2`, adds a one-time intake marker and backfill. Any experiment change in `mvp_factory.py` would conflict, and the versioning would collide. |
| `chatgpt/blank-mycast-customer-development` (PR #343 per spec) | 2 | `docs/growth/STARTUP_OWNER_MANUAL_MYCAST_PLAYBOOK.md` | Content source for the hypotheses only. No file overlap. |
| `chatgpt/factoryos-explainer-promo-v2` | 2 | `docs/prototypes/factoryos-explainer/chatgpt-promo/index.html` | None. |
| `chatgpt/issue-186-mvp-factory` | 7 (last 2026-11-04) | `mvp_manager.py`, `static/index.html`, `docs/MVP_FACTORY_SPEC.md`, … | Stale draft (#194 lineage, superseded per `MVP_FACTORY_SPEC.md:55`). It touches `static/index.html`. Do not rebase it. |
| `chatgpt/mycast-merged-pr-truth-20261112` | 2 | `autopilot/mycast_daily.py` + test | None. |
| `claude/mycast-317` | 1 (last 2026-11-12) | MyCast listener delivery, `static/mycast-configurator/*` | None with the MVP files. Relevant only if a pilot ever reuses the configurator (not proposed). |
| `feature/mycast-pwa-topic-picker-105` | 4 | `docs/prototypes/mycast/*` | None. |
| `chatgpt/issue-124-mycast-independent-script` | 1 | `docs/prototypes/mycast/variants/chatgpt/README.md` | None. |
| `mycast/daily` | 14 | `docs/prototypes/mycast/episodes/*.json` (bot) | None. |
| `claude/mycast-gemini-voice`, `claude/t603-mycast-daily`, `mycast/pilot-episode` | 0 | already in main | None. |
| `feat/factoryos-relay-mvp` | no merge base | old history (2026-10-26) | None. Unrelated root. |

**This session's own branch** (`ccr-5612b330-fr6sm2`, reported as PR #364): `git diff --stat origin/main...HEAD` shows
`docs/prototypes/factoryos-explainer/claude-motion/**`, plus `test_explainer_motion.py`, `DECISIONS.md` (+9) and `.github/workflows/ci.yml` (+2).
It touches none of the MVP/A-B files. `ci.yml` and `DECISIONS.md` are append-style shared files, so they carry a trivial rebase risk for S1 and nothing more.

**Could not verify** (no GitHub API in this audit): PR numbers and open/closed state for any branch other than #347, PRs from forks, draft PRs
without a pushed branch, review status, CI status of #347, the content of issues #346/#348/#105/#305, Relay claims on the live server, and the Notion pages.
The PR numbers for #343 and #364 come from the caller and the spec, not from git. I also tried to render the prototype at 375/768/1440 px with Playwright, but Chromium
is not installed and `playwright install` failed in this sandbox. **Prototype mobile overflow is therefore not verified.** Static reading of its CSS
(`@media(max-width:610px)` → single column, `↓` connectors) suggests no horizontal overflow, but this is unproven.

**Sequencing rule:** S1 must not start while `chatgpt/faceless-creator-mvp-builder-313` is unmerged and unclosed. If it merges first, S1 rebases
onto `version: 2` and still adds no migration. If it is abandoned, S1 still leaves `version` untouched.

---

## 4. Corrections requested to the spec (PR #347)

1. **One schema, not two.** Delete the §5 `variants[]` manifest, or mark it superseded, and keep a single `branches[]` model (section 2.8 of
   this review). Use one field name, `mode`, not `mode`/`comparison_type`. Use lowercase IDs that match `ID_RE` (`mc-exp-focus-001`, branches `a`/`b`)
   and display them in uppercase. Remove `position: "top"/"bottom"` from data, because A-above-B is a rendering rule derived from branch order.
2. **Labelling is mandatory and enforced in code.** Every experiment carries `mode` ∈ {`SEGMENT_COMPARISON`, `CONTROLLED_AB`}. The UI header, the compare
   card and every exported report show it. For `SEGMENT_COMPARISON`, the system **refuses** to compute or display a winner, lift or significance (API returns
   `winner: null, reason: "segment_comparison"`). `CONTROLLED_AB` cannot be created in S1–S3 because no assignment or consent plumbing exists. It is
   accepted by the validator only as a declared future mode, with `state` limited to `draft`. Defer `CREATIVE_COMPARE` to a later spec.
3. **Rename to avoid collision with the existing Battle variants.** `mvp_pipeline` and the dashboard already use "variant A/B/C" for research/spec
   alternatives (`app.py:1041-1044`, `static/index.html:3197`). Experiment lanes must be called **branches** in code, API and i18n keys (`mvpx.*`), never "variant".
4. **No fake metrics, ever.** All `measurement` values default to `null` and render "— / not instrumented". No synthetic counts exist outside test fixtures, and
   fixtures carry `demo: true` and never reach the production registry. A metric value is accepted only with an evidence link of a real source. No
   such source exists today, so S1–S3 contain **no metric-write API at all**.
5. **No automatic public pages or campaigns.** Landing drafts are JSON copy rendered inside the authenticated dashboard (escaped text, shared
   template). They are not new public routes, not `/static/` pages, not GitHub Pages, and not files under `mvps/`. A public landing page needs a later
   explicit owner decision and its own task.
6. **No paid APIs.** Creating an experiment or branch draft makes zero provider calls. Copy is entered by the owner, or drafted by an
   explicit owner click through the existing free Gemini path (`_gemini_text`, the same as research/spec) or the existing Claude worker queue. It never goes through
   Content Brain or any budgeted LLM path. A test asserts that no provider function is called on create.
7. **No third-party outreach.** No email, Telegram, DM or social account action is reachable from any experiment route. `approval.outreach` stays `false`
   and has no setter in S1–S3.
8. **No sensitive personal data in tracking.** Branch B ("personal goals": habits, nutrition, fitness) must never put a user's goal, health
   topic or free-text intention into an event, UTM tag, campaign name, artifact name or ad-audience definition. Segment labels are coarse marketing
   personas written by the owner (`entrepreneurs`, `personal_goals`), not inferred user attributes. No health or weight-loss claims appear in copy (§11 already
   says this; add it to the QA checklist and to a validator deny-list test for the copy JSON).
9. **Facebook / TikTok are placeholders only.** Channel cards have `status: "placeholder"` and the text "no connector. Nothing is sent". No
   ad-account, pixel, SDK or API integration exists, and none is proposed in S1–S3. Remove "campaign_ref", "UTM plan" and "budget" as editable fields until a
   real connector is audited. Keep them as `null` read-only fields.
10. **Per-branch IDs, attribution and approvals.** Every artifact, Relay ticket `source_key`, Content Factory job and approval event carries
    `project_id + experiment_id + branch_id + revision`. A preview approval is per branch and per revision (section 2.7, point 1). Publish approval stays the existing
    job approval and is not an MVP flag. Any event without a `branch_id` is "unassigned", never guessed.
11. **Fix the factual claims about existing code** in §3 and §5. The M1 contracts are offline modules not used by `app.py`. The route prefix is `/api/mvp-factory`.
    There is already one scheduler (`mvp_pipeline_loop`), and the A/B Tester must reuse it or none.
12. **Relation to project stage.** State explicitly that an experiment is orthogonal to the 11-stage project machine. It adds no stage and does not
    move the project. A project at any non-terminal stage may hold draft experiments, and a `rejected` project cannot create new ones.
13. **Scope trims for S1–S3.** Remove from the S1–S3 scope (move to "future, needs new spec") the following: random assignment, consent/telemetry events (§7 event list),
    Wilson intervals, Feedback Manager interviews, cost-per-activated-user, the kill switch for live traffic, and the Notion "Concept Backlog" automation.
    Concepts stay a reference field (`concept_id` + link) in S1. Do not build a concept lifecycle engine.
14. **Prototype fixes** (`ab-branches-preview.html`): the file has `lang="ru"` and is Russian-only. Either mark it "RU-only design reference" or add EN/UK.
    `role="status"` with `aria-live` on the inspector is fine. Emoji are decorative and need `aria-hidden`. The `button` cards carry no real action, so label
    them "details" and not as actions. Keep the "DEMO" pill.

---

## 5. Safe task split (one PR each, Owner: claude, after #347 merges with corrections)

### S1: registry experiment model and API (backend only, offline)
- **Files:** `mvp_factory.py` (new `MvpRegistry.create_experiment / update_branch_draft / approve_branch_preview / record_decision`,
  new validator `validate_experiment()`, routes inside `install_mvp_factory_routes`), new `test_mvp_experiments.py`, `.github/workflows/ci.yml` (+2 lines:
  compile + run), `DECISIONS.md`, `ROADMAP.md` (task entry).
- **Routes (proposed):** `POST /api/mvp-factory/{pid}/experiments` (owner/member). `POST .../experiments/{exp}/branches/{b}/draft` (owner/member;
  saves the copy JSON artifact and bumps the revision). `POST .../branches/{b}/approve-preview` (owner only). `POST .../experiments/{exp}/decision` (owner only).
  Reads go through the existing `GET /api/mvp-factory` snapshot.
- **DONE:** `python test_mvp_experiments.py` passes. `python test_mvp_factory.py`, `test_mvp_pipeline.py`, `test_mvp_cycle.py`, `test_mvp_state_machine.py` are unchanged and pass.
  Default verification (`py_compile`, `media_finisher_worker.test_planner`, `smoke_tests.py`) passes. An old v1 (and v2) registry file without `experiments` loads byte-identical until the first experiment write.

### S2: dashboard UI: branch lanes inside the existing MVP panel
- **Files:** `static/index.html` only (an "Experiments" section in `mvpRenderPanel()` / a new `mvpExperimentHtml()`, i18n `mvpx.*` EN/UK/RU, CSS near `:459-534`),
  `test_locale_parity.py` (only if new key families need registration), a UI source-assertion test (new `test_mvp_experiments_ui.py`), `ci.yml`.
  No change to `static/mvp-factory/index.html` in S2. It may get a read-only list later.
- **Behaviour:** shared header (mode badge, hypothesis, draft state) → lane **A on top**, lane **B below** (DOM order A then B on every viewport) →
  per-lane stage chips (Concept → Landing draft → Content draft → Channel placeholders → Metrics "not instrumented") → compare card that shows "Segment comparison: no winner"
  for SEGMENT_COMPARISON. The only enabled buttons are those with a backing S1 route: save draft, approve preview (owner), record decision (owner).
  Viewers see everything read-only.
- **DONE:** `node --check` on the extracted dashboard script (the `ci.yml:209-217` pattern), `python test_locale_parity.py` with `FACTORYOS_REQUIRE_NODE=1`, the
  new UI test, and the S1 tests all pass. Where a browser is available, a screenshot at 375 px and 1440 px is attached to the PR.

### S3: per-branch Content Factory handoff (drafts only)
- **Files:** `app.py` (MVP section near `:947-1105`: one owner-only route `POST /api/mvp-factory/{pid}/experiments/{exp}/branches/{b}/content-job`),
  `mvp_factory.py` (store `content_job_id` with an atomic claim in the `strategy_plan_job` style), tests, `ci.yml`.
- **Behaviour:** create **one** inbox job per branch through the existing `create_job` (`app.py:10705`). The brief carries experiment, branch, revision, persona,
  copy constraints and "draft only; no publish". Optionally link the job to the MyCast brand passport through the existing `/api/factory/strategy/{brand}/jobs/{job_id}/link`
  so that `brand_for_job` supplies the Master Brief. A second click returns the same job. The job is not run automatically. Publishing stays behind `/api/jobs/{id}/approve` and
  `_publish_approval_gate`, unchanged.
- **DONE:** tests prove one job per branch under concurrent clicks, that a job for A never appears under B, that no `publishing_queue` row is created, that no
  provider/LLM function is called, and that the job's approval cannot be satisfied by an MVP preview approval. All earlier suites pass.

Out of scope for S1–S3 (needs a new spec and an owner decision): public landing routes, random assignment, analytics events, consent, ad connectors, spend.

---

## 6. Acceptance tests

### 6.1 Unit: registry schema and validation (S1, `test_mvp_experiments.py`)
1. A valid SEGMENT_COMPARISON with branches `a`,`b` is stored under `projects[pid].experiments[id]`. `snapshot()` exposes it, and project `stage` and `progress` are unchanged.
2. Refused: one branch or three branches; duplicate branch ids; ids failing `ID_RE`; unknown `mode`; `CONTROLLED_AB` with any state other than `draft`; unknown fields.
3. Any non-null `measurement` value, `approval.publish/spend/outreach = true`, or a channel status other than `placeholder` in the input → refused (`metrics_not_supported`, `approval_not_settable`).
4. Copy deny-list: health/medical outcome claims ("lose weight", "cure", "guaranteed") in branch copy → refused with a reason. Fields that look like personal data (email, phone) → refused.
5. Idempotency: the same key and payload return the first result. The same key with a different payload → 409 (mirrors `test_mvp_factory.py:72-112`).
6. Preview approval is per revision: approving `a` r1 and then saving a draft makes r2 unapproved. Approving `a` leaves `b` untouched. A non-owner gets 403.
7. Isolation: blocking branch `b` leaves branch `a` state unchanged. The experiment is not "done" or "failed" because of one branch.
8. Decision: owner only. For SEGMENT_COMPARISON the stored decision has no `winner`/`lift` fields. A `rejected` project refuses new experiments (409).
9. Backward compatibility: a v1 registry file and a v2 file (the #313 shape) without `experiments` load unchanged. A damaged file still returns 503.
10. Every mutation appends exactly one event that carries `experiment`, `branch`, `evidence_check: "link_shape_only"`.

### 6.2 API (S1/S3, FastAPI `TestClient` in the style of `test_mvp_factory.py:177-260`)
- A viewer POST returns 403 (middleware `app.py:1224-1228`). A member can draft but cannot approve. An owner can approve.
- `GET /api/mvp-factory` returns the experiment with `mode` and all metrics `null`.
- S3: the content-job route returns 200 twice with the same `job_id`. The `jobs` table gains exactly one row per branch. `publishing_queue` is unchanged.

### 6.3 UI (S2)
- Source assertions: the experiment markup renders lane `a` before lane `b` in DOM order. The mode badge text matches i18n `mvpx.mode.segment`. For
  SEGMENT_COMPARISON the compare card contains no "winner" key. No `fetch` to any non-`/api/mvp-factory` URL is added. No button exists without a handler bound to an S1/S3 route.
- Locale parity EN/UK/RU for all `mvpx.*` keys (`test_locale_parity.py`).
- Layout: at 1440 px the lanes stack vertically (A top, B bottom), and each lane flows left→right. At 375 px, `document.documentElement.scrollWidth <= clientWidth`
  (no horizontal overflow), lanes are full width, and keyboard tab order is header → A → B → compare. In CI without a browser, this is reported as **not verified**, never as passed.

### 6.4 Offline pilot (after S2; no publishing, no spend)
Create MyCast experiment `mc-exp-focus-001`, `mode: SEGMENT_COMPARISON`, `concept_id: mc-focus-001`, under the existing `mycast` project.
- **Branch A: Business focus** (persona `entrepreneurs`). Headline "Start the day focused on your business". Subhead: one short daily audio briefing on
  the priorities and sources you choose for your company. CTA "Listen to a sample". Two short and two medium social copy drafts. Channel cards: Facebook and TikTok as placeholders.
- **Branch B: Personal goals** (persona `personal_goals`). Headline "Start the day focused on your goal". Subhead: carefully sourced ideas on a theme
  you pick, plus one small prompt. No health or outcome promises. CTA "Listen to a sample". Same draft counts and placeholders.
- **Expected visible result:** both drafts are visible in the dashboard, A above B. The header reads "SEGMENT_COMPARISON: audience and positioning exploration, not a
  randomized A/B test". All metrics read "not instrumented". Publish/spend/outreach are shown as disabled, "not available". No public URL exists. No Relay ticket
  or Content Factory job exists unless the owner clicks S3's button, and then a job is created in `inbox`, nothing more.
- **Evidence for the pilot record:** registry event links to the two artifact JSONs, plus the PR links for S1/S2. No exposure or conversion numbers.

---

## 7. Status statement

- **A/B Tester: NOT BUILT.** There is no experiment model, route, UI, Relay task type or Content Factory handoff in the codebase as of `883b644` / `origin/main e8a6bac`.
- **PR #347: spec reviewed.** Recommendation: merge as docs after corrections 1–14. It is not an implementation and not an authorization to publish.
- **Next step:** add ROADMAP entries S1–S3 (`Owner: claude`). Resolve the `chatgpt/faceless-creator-mvp-builder-313` overlap on `mvp_factory.py` first, then claim S1.
- Nothing in this review was published, deployed, sent to a third party or paid for.
