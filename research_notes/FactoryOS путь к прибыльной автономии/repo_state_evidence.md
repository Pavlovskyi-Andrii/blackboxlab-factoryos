# FactoryOS repository state — evidence-graded audit (2026-11-17)

Read-only audit of `/home/user/blackboxlab-factoryos` at `main` = `11a3330` (merge of PR #416, 2026-11-17 21:47 +0200).
Nothing in the repository was edited. Full git history was read from a separate bare clone (the working checkout is a
shallow clone of 98 commits); PR and Issue counts come from the GitHub REST API (read-only).

Grades used: **LIVE** = live-verified in production with a cited evidence document; **LIVE-ONCE** = one recorded live run,
not repeated; **TESTS** = deterministic tests/fixtures only (code may be deployed, behaviour in production not evidenced);
**PLANNED**; **HUMAN** = blocked on an open `[HUMAN]` task; **UNKNOWN** = no evidence either way.

## Key claims

| # | Claim | Source (file path / git evidence) | Date / version | Confidence |
|---|---|---|---|---|
| 1 | The project is 30 days old: first commit 2026-10-18, 826 commits on `main` (529 first-parent), 283 PRs of which 247 merged, 35 closed unmerged, 1 open; 133 Issues (59 open). | `git log main --reverse`, `git rev-list --count main`; GitHub REST `pulls?state=all`, `issues?state=all` | 2026-10-18 … 2026-11-17 | verified_primary |
| 2 | Code volume: 236 Python files / 78,179 lines (`app.py` 13,742); 118 Python test files / 28,783 lines plus `smoke_tests.py` (1,370); `static/index.html` is 1.07 MB; CI runs 99 distinct test files. | `git ls-files \| xargs wc -l`; `.github/workflows/ci.yml` | main `11a3330` | verified_primary |
| 3 | Production is up and serves the current release: `/health` → `{"ok":true,"service":"factoryos","version":"v5.12.0"}` (HTTP 200); `/api/version` → 401 `authentication required`. | `curl` at 2026-11-17 20:38:40 UTC; `app.py:79` (`APP_VERSION = "v5.12.0"`) | 2026-11-17 | verified_primary |
| 4 | No real external post has ever been published. `[HUMAN] T-520` (first real publisher) and `T-521` (first real post) have been open since 2026-10-23 (25 days). All three publishers (Metricool, YouTube, LinkedIn) are tests-only. | `ROADMAP.md:420-427`, `:345-354`, `:553-558`; `git log -S"T-520 " -- ROADMAP.md` → `166ad10` 2026-10-23; `README.md:141` | 2026-11-17 | verified_primary |
| 5 | No revenue, payment, customer or sales contact is recorded. No payment integration exists in code (search for Stripe/Paddle/LiqPay/Fondy/WayForPay/PayPal: only a secret-scanner regex). The only GTM kit states "No sales, outreach, customer consent, payments, or third-party scans have taken place". | `grep -rIli 'stripe\|paddle\|…'`; `security_findings.py:27`; `docs/gtm/security_check_pilot_kit_2026-11-03.md:5`; `DECISIONS.md:825` ("There is no billing yet") | 2026-11-17 | verified_primary |
| 6 | No customer validation has been run. `T-615-H` (MyBrief outreach) and `T-614-H1` (5 interviews) are open; `T-630-H` (10 interviews) was ticked only as "superseded", not performed; owner decided "no manual interviews" on 2026-11-16. | `ROADMAP.md:785-789`, `:801-805`, `:820-825`; `DECISIONS.md:1876-1881` | 2026-11-17 | verified_primary |
| 7 | 16 `[HUMAN]` tasks are open; 7 of them gate distribution, validation or monetisation (T-520, T-521, T-700-H, T-620-H, T-615-H, T-614-H1, T-634-H). | `grep -c '^- \[ \] \[HUMAN\]' ROADMAP.md` = 16; classification in §7 | 2026-11-17 | verified_primary |
| 8 | Effort went mostly inward: 78 of 138 ROADMAP tasks (56.5 %) are agent coordination / tooling / observability / UI; 16 (11.6 %) are distribution/sales/validation and none of those has live evidence. A keyword pass over the 247 merged PR titles gives about 54 % internal, 18 % MVP product, 15 % infra, 8 % content, 5 % distribution. | `ROADMAP.md` (all 138 checkbox lines, classified by task ID, §7); PR titles from GitHub REST | 2026-11-17 | inference (classification is mine; counts are verified) |
| 9 | The P0 "Telegram Relay control room" was first server-verified end to end on 2026-11-17 (ticket R-0087), 19 days after it became P0; the evidence is the owner's screen (the agent session got HTTP 401). Parent tasks T-590/T-591/T-591-A/T-592/T-593 are still unchecked. | `ROADMAP.md:58-106`; `DECISIONS.md:1937-1944`; `git log -S"T-590 "` → 2026-10-29 | 2026-11-17 | reported_secondary |
| 10 | The autonomous EC2 worker produced 44 commits on `main`, 43 of them between 2026-10-29 and 2026-11-02 and 1 since (a one-line README change, PR #365). It stalled repeatedly (stale branch, dirty tree, rejected pushes, usage limit, a ~300-message Telegram loop). | `git log main --author='FactoryOS AWS Worker'`; `DECISIONS.md:325,470,771,936,1408,1904`; `ROADMAP.md:958`; `docs/verification/R-0058_relay_e2e_2026-11-10.md` | 2026-10-29 … 2026-11-17 | verified_primary |
| 11 | Almost all code since 2026-11-02 comes from interactive Claude cloud sessions, self-merged: 160 of 247 merged PRs are from `claude/` or `ccr-` branches; median time from PR creation to merge is 6.6 minutes (106 PRs merged within 5 minutes). | GitHub REST `pulls` (`head.ref`, `created_at`, `merged_at`); `.autopilot/answers.md:17,31` | 2026-11-17 | verified_primary |
| 12 | ChatGPT lane: paused by owner decision 2026-10-30; 25 PRs merged, 20 closed unmerged or open (44 % not merged); the shared MCP workspace has never had a live round trip (`T-624` open; "live two-way connection is not verified", Issue #94 open). | `ROADMAP.md:24`, `:148-166`; `DECISIONS.md:304-305`; `CLAUDE.md` (coordination section); GitHub REST `pulls` | 2026-11-17 | verified_primary |
| 13 | Gemini: the Issue→PR loop merged 21 small PRs (P3 tests/docs) on 2026-11-04 … 2026-11-08 and none since; the Relay Gemini worker is not set up (`T-607-H` open, probe file absent); the free Gemini quota returned 429 on 2026-11-15, -16 and -17. | GitHub REST `pulls` (`gemini/` heads); `ROADMAP.md:928-945`, `:343`; `DECISIONS.md:1532,1837`; `ls docs/verification/` | 2026-11-17 | verified_primary |
| 14 | The one cross-agent link demonstrably working in production through FactoryOS's own relay is automatic Codex review of PRs (advisory comments with real blocking findings on PR #412 and #416). | GitHub REST `issues/412/comments`, `issues/416/comments`; `DECISIONS.md:1005-1011` | 2026-11-17 | verified_primary |
| 15 | MyCast is the only product with evidence of real recurring use, and the user is the owner: a daily episode script was committed for 16 consecutive dates (2026-11-02 … 2026-11-17). No count of external listeners exists anywhere in the repository. | `git log main..mycast/daily`; `ROADMAP.md:138-146`, `:947-948`; `grep -rn '[0-9]\+ listeners'` (no hits) | 2026-11-17 | verified_primary (scripts); UNKNOWN (deliveries, listeners) |

## 1. Live host (2026-11-17 20:38:40 UTC)

- `curl -sS https://blackboxlab-factoryos.onrender.com/health` → HTTP 200, `{"ok":true,"service":"factoryos","version":"v5.12.0"}` (0.64 s).
- `curl -sS https://blackboxlab-factoryos.onrender.com/api/version` → HTTP 401, `{"detail":"authentication required"}`.
- `app.py:79` has `APP_VERSION = "v5.12.0"`; `README.md:30` first changelog entry is v5.12.0 (2026-11-17). So Render serves a build
  of the newest release. The exact deployed SHA cannot be confirmed without the owner's sign-in. The last recorded SHA match is
  the owner's own check on 2026-11-15 (`.autopilot/answers.md:23`).
- Nothing else on the host was touched. Engine status (`durable_engine.launched`), publisher adapter, queue sizes and user
  counts sit behind authentication: UNKNOWN from here.

## 2. Git and repository statistics

| Metric | Value | How measured |
|---|---|---|
| First commit | 2026-10-18 03:11 +0300 ("Blackbox Lab FactoryOS — Render version") | `git log main --reverse` |
| Commits on `main` | 826 (529 first-parent, 133 merge commits); 31 distinct days | `git rev-list --count [--first-parent] main` |
| Commits on all refs | 1,508 across 187 branches; 8 tags (v5.6 … v5.12.0) | `git rev-list --count --all`, `git branch`, `git tag` |
| Commits per ISO week (`main`) | W42 111 (one day, 10-18) · W43 246 · W44 134 · W45 204 · W46 84 · W47 47 (two days) | `git log --date=format:%G-W%V` |
| PRs | 283 total: 247 merged, 35 closed unmerged, 1 open (#413) | GitHub REST `pulls?state=all` |
| Merged PRs per ISO week | W43 22 · W44 39 · W45 90 · W46 73 · W47 23 (two days); peak day 2026-11-13 with 25 | same |
| Merged PRs by branch prefix | `ccr-` 92, `claude/` 68, `chatgpt/` 25, `gemini/` 21, `autopilot/` 3, `relay/` 1, `mycast/` 1, other 36 | same |
| PR creation → merge | median 6.6 min; 106 within 5 min; 162 within 15 min; 8 over 24 h | same |
| Issues | 133 total, 59 open, 74 closed (first 2026-10-28) | GitHub REST `issues?state=all` |
| Tracked files | 740 (236 `.py`, 223 `.md`, 30 `.html`) | `git ls-files` |
| Python | 78,179 lines; non-test 48,026; `app.py` 13,742; `relay.py` 2,067 | `wc -l` |
| Tests | 118 Python `test_*.py` (108 root, 9 `autopilot/`, 1 `media_finisher_worker/`), 28,783 lines; `smoke_tests.py` 1,370 lines; 2 JS test files | `git ls-files \| grep test_` |
| Front end | about 15,500 lines of JS/HTML/CSS (vendored files excluded); `static/index.html` 1,072,890 bytes | `wc` |
| Docs | 223 Markdown files, 19,135 lines; `DECISIONS.md` 1,965 lines / 300 KB; `ROADMAP.md` 964 lines | `wc` |

Reading the trend: commit counts fall after W45 because work moved from direct commits to squash-merged PRs; merged PRs per
week are the better throughput measure and they peaked in W45–W46. Throughput is high. What it was spent on is §7.

Authorship (`git log main`, author name and `Co-Authored-By` trailers): 216 commits carry a Claude Opus trailer, 44 a generic
Claude trailer, 42 the "FactoryOS AWS Worker" trailer. All 283 PRs were opened under the owner's GitHub account or
`github-actions[bot]`, so GitHub authorship does not separate humans from agents.

## 3. Component status map

| Component | Grade | Evidence | What is not proven |
|---|---|---|---|
| **Relay bus** (tickets, atomic claim, `run_id`, events) | LIVE (limited) | Ticket R-0087 verified by the server from its own history on 2026-11-17: Telegram intake → one ticket → claim + run_id → running → done → Bot API delivery receipt (`ROADMAP.md:103-106`, `DECISIONS.md:1937-1944`). First live round trip 2026-11-11, R-0063 (`DECISIONS.md:935-942`). | The agent session "gets HTTP 401 on owner APIs and therefore did not re-read R-0087 itself; the owner's screen is the evidence" (`DECISIONS.md:1942`). T-590, T-591, T-591-A, T-592, T-593 are still `[ ]` (`ROADMAP.md:58-101`). |
| Relay ticket → own branch → PR → CI → merge | LIVE-ONCE | PR #365 from `relay/r-0075-…` merged 2026-11-14; the change is one README line (`README.md:473`). | Of 3 `relay/` PRs, 2 were closed unmerged (#370, #372). On 2026-11-10 the same path was BROKEN: no ticket branch, no PR (`docs/verification/R-0058_relay_e2e_2026-11-10.md:18-21`). |
| **Telegram control room** | LIVE | Bot paired 2026-11-02 (`ROADMAP.md:253-254`); 6-hourly self-test message (`DECISIONS.md:649`); `/proof` verdict 2026-11-17. | `T-592-H` (Telegram vs web comparison) open (`ROADMAP.md:108-112`). Incident: about 300 cards sent in a loop on 2026-11-15 (`DECISIONS.md:1408`). |
| **Worker Center / Agent Office** | TESTS + deployed; acceptance HUMAN | `test_worker_observability.py`, `test_worker_center_simple.py`, `test_drawers.py`; redesigned on 2026-11-17 (`DECISIONS.md:1958-1965`). | `T-592`, `T-594`–`T-597`, `T-602` unchecked for missing screenshot/CI evidence (`ROADMAP.md:175-215`); `T-592-H`, `T-593-H` open. |
| **Owner desk** (HUMAN runbooks, ask Claude) | LIVE | 2026-11-02 14:15–14:25 UTC the EC2 worker answered two real owner questions (`ROADMAP.md:127-128`). | The first questions on 2026-11-01 were never claimed (401 from middleware) until fixed (`DECISIONS.md:647`). |
| **Autopilot EC2 worker** (Claude Code on subscription) | LIVE, unreliable | 44 commits on `main`; batch PRs #80 and #111 ("25 tasks", 2026-11-01); usage-limit hold observed live 2026-11-01 12:01→16:22 UTC (`ROADMAP.md:119`). Active again 2026-11-17 on its branch (T-626, T-631 commits, not on `main`). | `T-593-H` open (`ROADMAP.md:114-116`). Stalls listed in §8. Only 1 worker commit reached `main` between 2026-11-03 and 2026-11-17. |
| **Gemini Issue→PR coder** (`gemini-coder.yml`, EC2 loop) | LIVE, dormant | 21 merged PRs 2026-11-04 … 2026-11-08, all P3 tests/docs/i18n (GitHub REST). | No merged `gemini/` PR after 2026-11-08; 6 closed unmerged. |
| **Gemini Relay worker** (T-607) | TESTS; HUMAN | `test_gemini_worker.py`; runbook `docs/handoff/GEMINI_EC2_WORKER.md`. | `T-607-H` and `T-607-P` open (`ROADMAP.md:928-945`); `docs/verification/T-607_gemini_probe.md` does not exist. Jules (`T-606`) "not yet available in your region" (`.autopilot/answers.md:25`). |
| **ChatGPT lane** | Works only through GitHub PRs; paused | 25 merged PRs (2026-10-27 … 2026-11-14). | "The `chatgpt` lane is paused" (`ROADMAP.md:24`). "ChatGPT stays 'not connected': a ChatGPT subscription gives no programmatic access, only the paid per-token OpenAI API" (`DECISIONS.md:946`). |
| **Shared MCP workspace** (T-604 / T-625) | TESTS; HUMAN | `test_agent_workspace.py`; tools exist on `/mcp` (`ROADMAP.md:156-161`). | Lane tokens not set (`T-624` open, `ROADMAP.md:163-166`); no live Claude → ChatGPT → review round trip; panel `T-626` open. |
| **Claude ↔ Codex relay, automatic PR review** | LIVE | Comments "🤖 Codex review · automatic, via the FactoryOS agent relay · advisory only" with blocking findings on PR #412 (2026-11-17 14:15 UTC) and #416 (19:41 UTC), both then fixed. | Advisory only; it never blocks a merge (`DECISIONS.md:1010`). |
| **Evidence Protocol** (levels claimed/linked/checked/accepted) | TESTS + deployed; live UNKNOWN | Tier 1–2.6 merged as #299–#306 (`README.md:61-62`, `DECISIONS.md:878-930`), `test_evidence.py`. | `docs/specs/EVIDENCE_PROTOCOL.md:3` still says "проект ТЗ, не реализовано" (stale header). No live metric of "claimed but not confirmed" is recorded in the repo. |
| **Content Factory pipeline** (signals → idea → variants → package → approval) | LIVE-ONCE (2026-10-20), since then TESTS | First paid cycle reached the approval gate: $0.188066, 22 live runs, 40,023 tokens, `publish_created=false` (`README.md:286-297`). | Snapshot 2026-10-26: "Approval has 4 waiting jobs and 0 approval decisions" (`README.md:141`). Owner on 2026-11-16: «Контент / Продвижение — оно не работает» (`ROADMAP.md:894`); fixes T-690/T-691 are tests-only. |
| **AI Media Finisher** | LIVE (2026-10-21/22) | Real 349.7 s video → about 232 s, 126 cuts, job READY in 1,592 s (`README.md:252-253`); 5/5 archives present after redeploy (`README.md:197`). | DBOS-durable version: tests only; the live check is listed as "not a blocker" and not recorded as done (`ROADMAP.md:754`). |
| Discovery / Revideo | TESTS (fixtures); one Descript pilot | Deterministic acceptance (`ROADMAP.md:398-412`, `:510-513`); a real 8-second Descript render on 2026-10-20 (`README.md:263`). | "Runway runtime … is not claimed as verified" (`README.md:264`). |
| **Publishers** — Metricool | TESTS; HUMAN | Adapter T-519 (`ROADMAP.md:416-418`). | Runtime "still reports `adapter=manual` and `metricool_configured=false`" (`ROADMAP.md:422`); "Metricool API needs a paid plan; owner does not want to pay before testing" (`.autopilot/answers.md:26`). |
| Publishers — YouTube direct | TESTS (zero network); HUMAN | `test_youtube_publisher.py` (`ROADMAP.md:553-558`). | "Live connection = HUMAN T-520, first post = HUMAN T-521". |
| Publishers — LinkedIn | TESTS; HUMAN | `test_linkedin_publisher.py`; dark until `FACTORY_LINKEDIN_ENABLED=1` (`ROADMAP.md:345-354`). | `T-700-H` open since 2026-11-17. Messaging is partner-only and people search has no public API, so neither is built (`DECISIONS.md:1923-1924`). |
| Publishers — OLX | PLANNED | "planned, no code yet" (`ROADMAP.md:356-360`). | Needs partner registration. |
| Analytics return loop | TESTS | T-522 on fixtures (`ROADMAP.md:429-431`). | No real post exists to measure. |
| **Browser runner / Surfer** | LIVE (read-only), measured | 33 real read tasks on production 2026-11-16: 31 finished, 2 refused with 429; "Fully useful answers: 12 of 31", 15 partial, 4 wrong or misleading; median run 5 s, median queue wait 50 s (`docs/verification/surfer-benchmark-2026-11-16.md:16-23`). First real EC2 run 2026-11-13 (`DECISIONS.md:1045-1046`). | Re-run after the fixes: "NOT STARTED" (same doc `:84`). It cannot act: "the executor refuses submit unconditionally" (`DECISIONS.md:1032`). LinkedIn and OLX answer 403 from EC2 (`DECISIONS.md:1920-1921`). `web_search` falls back to Wikipedia while the Gemini quota is exhausted (`ROADMAP.md:343`). |
| **MVP Factory / MVP Builder** (registry, cycle, hand-off, A/B tester, Product Evolution) | TESTS + deployed | `test_mvp_*.py` (9 files); spec status "integrated, not a full pipeline yet" (`docs/MVP_FACTORY_SPEC.md:5`, 2026-11-08). | No MVP has been built through the hand-off: the target directory `mvps/` does not exist (`ls mvps`). Agents may not move a pilot past spec review (`DECISIONS.md:977`). |
| **MyCast — owner's daily episode** | LIVE (owner only) | Daily script commits `MyCast daily episode mycast-2026-11-02 … -11-17` on branch `mycast/daily` (16 dates); delivery confirmed for 2026-11-02 (`docs/handoff/TEAM_PLAN_2026-11-06.md:14`) and 2026-11-05, rated 7/10 by the owner (`ROADMAP.md:948`, `DECISIONS.md:676`). | `T-603` (7 consecutive delivered mornings + feedback) still `[ ]` (`ROADMAP.md:138-146`); per-day delivery receipts live on the server, not in the repo. |
| **MyCast — public product** (mycast.pro, configurator, Telegram/Google sign-in, listener delivery, library, share links) | Deployed; usage UNKNOWN | Domain bought 2026-11-13 (`DECISIONS.md:1020`); open beta accounts (`DECISIONS.md:799-806`); library and links T-620 (`ROADMAP.md:756-761`). | Listener delivery had no sender until 2026-11-13: "nothing read that flag … never sent", found on the owner's own test podcast (`DECISIONS.md:994-996`). Referrals off (`T-620-H`), trial not enforced, "no billing yet" (`DECISIONS.md:825`). No listener numbers in the repo. Cap: 10 listener episodes per UTC day overall (`DECISIONS.md:999`). |
| MyCast demo audio (T-665), quiz + analyst (T-634) | TESTS; HUMAN | `test_mycast_demo_audio.py`, `test_mvp_quiz.py`. | `T-645-H` and `T-634-H` open; quiz needs ≥ 10 signed-in people and ≥ 40 % share before it does anything (`DECISIONS.md:1882-1884`, `:1912-1914`). |
| **MyBrief** | Deployed static demo; HUMAN | Public page with a 13-item fixture written once on 2026-11-15, "No server-side generation" (`DECISIONS.md:1528-1531`). | `T-615-H` open: no link was sent to anyone (`ROADMAP.md:785-789`). |
| **Decision Memory** | TESTS; owner-only; HUMAN | `test_decision_memory.py`; 216 records parsed from `DECISIONS.md`; "no LLM or provider call" (`DECISIONS.md:1559`, `:1571`). | `T-614-H1` open: no interviews (`ROADMAP.md:801-805`). |
| Release Guardian | TESTS; owner-only | `test_release_guardian.py` (`ROADMAP.md:728-734`). | No external user. |
| **Durable engine (DBOS)** | TESTS + deployed; live UNKNOWN | `test_durable_engine.py` and `test_durable_media_finisher.py` incl. SIGKILL recovery (`ROADMAP.md:740-753`). | Production `durable_engine.launched=true` not recorded; `/health` shows only the version. |
| **OAuth framework / vault** | TESTS; vault key owner-confirmed; OAuth HUMAN | `test_oauth_framework.py`, `test_browser_vault.py`; `T-560-G` closed on the owner's word 2026-11-17 (`ROADMAP.md:362-366`). | `T-551` (provider OAuth apps) open since 2026-10-24; `T-552`, `T-554` depend on it (`ROADMAP.md:539-572`). "Agents cannot read that endpoint without the owner's sign-in." |
| Workspace tenancy (sellable workspaces) | TESTS | Two-workspace regression (`ROADMAP.md:560-565`). | No second customer has ever existed. |
| Versioning / releases | LIVE | 8 tags; `/health` = `APP_VERSION`. | — |
| Notion as memory | Outside the runtime | One cloud session read two Notion pages on 2026-11-05; "Not verified: the EC2 Claude Worker … and any write to Notion" (`docs/handoff/NOTION_READ_PROOF_2026-11-05.md:3-4`). | The EC2 worker "has no Notion connector" (same doc `:43`). |
| Metricool / vidIQ / HubSpot / Gmail | Metricool: adapter, not configured. vidIQ: "outside FactoryOS" only (`docs/roadmap/FACTORYOS_V4_4_SPEC.md:65`). HubSpot: an OAuth slot name only (`oauth_framework.py`). Gmail: no code. | `grep -rIli hubspot\|vidiq\|gmail --include='*.py'` | No CRM contour exists in code. |

## 4. Open `[HUMAN]` tasks (16)

"Open since" is the first commit that added the ID to `ROADMAP.md` (`git log main --reverse -S"<ID>" -- ROADMAP.md`).

| ID | Line | Open since | Age (days) | What it gates |
|---|---|---|---|---|
| T-520 Configure first real publisher | `ROADMAP.md:420` | 2026-10-23 (`166ad10`) | 25 | Any real post; T-521; live YouTube connection |
| T-521 First owner-approved real post | `:425` | 2026-10-23 | 25 | First publisher receipt, analytics loop on real data, every content learning loop |
| T-551 Provider OAuth applications | `:539` | 2026-10-24 (`b8bfab8`) | 24 | T-552 (OAuth callback/vault), T-554 (customer onboarding = "sellable" flow) |
| T-598-H2 `ec2:DescribeInstances` (optional) | `:962` | 2026-10-31 | 17 | Worker Center `ec2_api` signal only |
| T-606 Connect Jules | `:952` | 2026-11-02 | 15 | Effectively obsolete: owner prefers Gemini CLI on EC2 (`.autopilot/answers.md:25`) |
| T-592-H Compare Telegram and web | `:108` | 2026-11-15 (parent T-592 since 2026-10-29) | 2 (19) | Closing T-592 |
| T-593-H Confirm the worker advances by itself | `:114` | 2026-11-15 (parent T-593 since 2026-10-29) | 2 (19) | Closing T-593; the claim "autonomous" |
| T-624 Per-lane MCP tokens | `:163` | 2026-11-15 (T-604 since 2026-11-02, Issue #94 since 2026-11-01) | 2 (16) | Any live Claude ↔ ChatGPT/Gemini handoff; T-626, T-632 |
| T-560-I Google search via Gemini | `:339` | 2026-11-15 | 2 | Owner opted in 2026-11-17; still Wikipedia because of 429 |
| T-607-H Gemini worker on EC2 | `:938` | 2026-11-15 | 2 | T-607, T-607-P: the third lane |
| T-620-H MyCast referral terms | `:763` | 2026-11-15 | 2 | The only growth mechanic in MyCast |
| T-615-H MyBrief 48-hour validation | `:785` | 2026-11-15 | 2 | First external feedback on MyBrief |
| T-614-H1 Decision Memory interviews | `:801` | 2026-11-15 | 2 | First external feedback on Decision Memory |
| T-645-H Approve MyCast demo episodes | `:1` | 2026-11-16 | 1 | Playable demos on shared-episode pages |
| T-700-H LinkedIn app + account | `:351` | 2026-11-17 | 0 | Any LinkedIn post; T-701 |
| T-634-H Quiz gift terms + mail service | `:835` | 2026-11-17 | 0 | Quiz rewards, T-635 e-mails |

Closed HUMAN tasks (8): T-506 (Telegram pairing, done 2026-11-02), T-507, T-605 (Gemini key, verified 2026-11-05), T-598-H1
(2026-11-01), T-560-G (2026-11-17), T-591-H (2026-11-17), T-VERSION-H (done by Claude), T-630-H (superseded, not performed).

Pattern: the owner closes HUMAN tasks that unblock agent infrastructure within days (pairing, keys, scopes, vault). The three
oldest open ones are exactly the ones that put something in front of the market (publisher, post, OAuth apps). GTM Issues
outside the ROADMAP are also open and untouched: #101 "Sell first 3 paid AI Security Check pilots ($99)" and #102 "Global
10-company outreach" (both 2026-11-01), #78 "customer validation evidence" (2026-10-31), #342 "Customer Development playbook
for MyCast" (2026-11-13).

## 5. Has any real publishing, outreach, customer contact, user traffic or payment happened?

**Evidence against (strong):**
- Publishing: T-520/T-521 open (`ROADMAP.md:420-427`); publishers tests-only; "Real posting still needs owner approval"
  (`README.md:79`); first paid pilot ended with "Nothing was scheduled or published" (`README.md:294`).
- Outreach: `docs/business_experiments/02_CLAUDE_HANDOFF_BUSINESS_DIRECTION.md:33`: "Нет разрешения запускать лендинги,
  закупать рекламу, писать клиентам или выставлять реальные счета." `T-615-H`, `T-614-H1` open. ChatGPT's GTM PRs were closed
  unmerged: #153 (Security Check pilot offer), #154 (Launch Agent, 10-company outreach kit), #343 (MyCast Customer Development
  playbook).
- Payment: no payment provider in code or `requirements.txt`; MyCast "open beta is free" (`DECISIONS.md:825`); the $99
  Security Check price is "a hypothesis … not a live checkout" (`docs/gtm/security_check_pilot_kit_2026-11-03.md:11`).
- Customers: the two-workspace tenancy and "customer A → customer B" flows exist only as regressions (`ROADMAP.md:560-572`).

**Evidence for (weak, all owner-side):**
- The owner uses MyCast daily (16 script commits; episode of 2026-11-05 rated 7/10).
- The owner bought `mycast.pro` on 2026-11-13 and the public pages are served (`DECISIONS.md:1020-1023`).
- Listener accounts are open to anyone with Telegram or Google. The only documented listener is the owner: "the owner's
  website podcast was saved, approved and 'delivery on' on 2026-11-11" (`DECISIONS.md:996`). Whether anyone else signed up is
  UNKNOWN: searches for listener counts, sign-ups, visitors, waitlist and "first user" in `DECISIONS.md`, `docs/handoff/`,
  `docs/verification/` returned nothing.
- Real external systems were touched only as owner-side pilots: a $0.188 LLM cycle (2026-10-20), a Descript render, Gemini TTS.

Verdict: no publishing, no outreach, no customer contact and no payment. External traffic is unknown and probably near zero,
because no distribution action has ever been taken.

## 6. Money facts recorded in the repository (context for "zero additional spend")

- Render blueprint: web service plan `0.5c-512mb` with a 1 GB disk and Media Finisher plan `1c-2g` with a 5 GB disk
  (`render.yaml:12`, `:81`, `:87`, `:112`). Plan prices were not checked here.
- "Claude's $100 subscription" (`DECISIONS.md:950`); ChatGPT subscription used for Codex device login (`DECISIONS.md:992`).
- GitHub Actions: the 2,000 free minutes were used up by 2026-11-08, budget set to $5 (`DECISIONS.md:828-829`), then "$5 in
  two days", including 22 Factory Builder dispatch runs "that all failed in ~20 s" (`DECISIONS.md:1133-1135`).
- Paid LLM calls: one fenced pilot, $0.188066 (`README.md:293`).
- `render.yaml:38-43` sets `FACTORY_VIDEO_ADAPTER: gemini-omni` (model `gemini-omni-1.1-flash`), while `ROADMAP.md:949` says
  "FACTORY_VIDEO_ADAPTER stays unset (no paid video)". Which is live is UNKNOWN.

## 7. Effort allocation

### 7a. ROADMAP tasks (all 138 checkbox lines; 98 done, 40 open)

Each task ID was assigned to one bucket by hand (script kept in the session scratchpad; mapping below).

| Bucket | Total | Share | Done | Open | Open HUMAN | Open agent |
|---|---|---|---|---|---|---|
| A. Internal agent coordination / tooling / observability / UI | 78 | 56.5 % | 55 | 23 | 6 | 17 |
| B. Content production | 12 | 8.7 % | 12 | 0 | 0 | 0 |
| C1. Customer-facing product (MVP end-user features) | 8 | 5.8 % | 6 | 2 | 1 | 1 |
| C2. MVP-factory meta-tooling (A/B tester, feedback loop, quiz) | 8 | 5.8 % | 5 | 3 | 0 | 3 |
| D. Distribution / sales / monetisation / validation | 16 | 11.6 % | 7 | 9 | 7 | 2 |
| E. Security / infra | 16 | 11.6 % | 13 | 3 | 2 | 1 |

- Agent-completed tasks only (90 non-HUMAN `[x]`): A 51 (56.7 %), B 12 (13.3 %), C1 6 (6.7 %), C2 5 (5.6 %), D 6 (6.7 %),
  E 10 (11.1 %).
- Bucket D "done" = T-519 Metricool adapter, T-522 analytics loop, T-542 dry run, T-552-YT YouTube, T-560-D social draft
  recipes, T-700 LinkedIn, plus T-630-H (superseded). All are tests or fixtures; **zero D tasks have live evidence**.
- Mapping. A: T-590–T-604 family, T-624–T-626, T-500–T-509, T-560-A/B/C/E/H/I/J/K, T-670/671/673, T-531–T-537, T-580–T-589,
  T-MODS-A/B/C, T-631/632, T-VERSION(-H), T-667, T-606, T-607(-H/-P). B: T-510–T-513, T-540, T-541, T-MODS-D/E, T-646, T-647,
  T-690, T-691. C1: T-603, T-614, T-615, T-616, T-620, T-645, T-645-H, T-665. C2: T-608–T-610, T-630, T-633–T-636.
  D: T-519–T-522, T-542, T-552-YT, T-554, T-560-D, T-700, T-700-H, T-701, T-614-H1, T-615-H, T-620-H, T-630-H, T-634-H.
  E: T-530, T-550, T-551, T-551-A, T-552, T-553, T-560-F, T-560-G, T-562, T-564, T-598-H1/H2, T-605, T-611, T-612, T-672.

### 7b. Merged PR titles (247), keyword rules, approximate

| Bucket | PRs | Share |
|---|---|---|
| A. Internal coordination / tooling / UI | 133 | 53.8 % |
| C. MVP product (39 of 45 titles mention MyCast) | 45 | 18.2 % |
| E. Security / infra / CI / releases | 38 | 15.4 % |
| B. Content production | 19 | 7.7 % |
| D. Distribution / publishing | 12 | 4.9 % |

Rules are first-match keyword regexes on the title, so individual PRs are misfiled in both directions (for example a release
PR counted under C, a version PR under D). Treat each share as ± 5 points. The ROADMAP undercounts product work because most
MyCast work ran through Issues (#261, #281, #305, #317) rather than ROADMAP tasks; the PR view corrects for that.

Both views agree: more than half of all engineering output is the machinery for agents to coordinate and for the owner to
watch them; about 5–12 % touches distribution, none of it live.

## 8. Multi-agent coordination — how it actually performed

**Claude (interactive cloud sessions).** The real engine: 160 of 247 merged PRs. Self-merges under the standing grant
(`.autopilot/answers.md:17,31`). Parallel sessions collided on task IDs: "main merged its own T-611 … then main took T-620
too … Final ids are the non-numeric T-MODS-A…D, so parallel agents numbering T-6xx cannot collide again"
(`DECISIONS.md:1613-1616`); a duplicate `T-645-H` existed with two meanings (`DECISIONS.md:1945-1946`). Limits bite: on
2026-11-03 "Claude takes, until Friday: review and merge only (limit-saving mode)" and "Claude is a single merge point"
(`docs/handoff/TEAM_PLAN_2026-11-06.md:22,26`).

**Claude EC2 worker ("autopilot").** Chronology of stalls, all from the repository's own records:
- 2026-10-30: "Root cause of 'Claude has tasks but does nothing': the EC2 worker pulled only `autopilot/aws-worker`, which was
  12 commits behind main" (`DECISIONS.md:325`).
- 2026-10-30: a reboot wiped the Python venv and headless `claude -p` denied `python3` (`DECISIONS.md:328`).
- 2026-10-30 15:14 → 10-31 08:29 and 2026-11-01 08:06 → 11:23: "655 rejected pushes" because commits edited `ci.yml` (`ROADMAP.md:958`).
- 2026-10-31: `usage_limit_reached` was not recognised, "so 13 tasks were parked as 'failed' in ~20 minutes" (`DECISIONS.md:470`).
  After the fix the worker held the queue 12:01 → 16:22 UTC on 2026-11-01 (`ROADMAP.md:119`).
- About 2026-11-04: "worker was down ~7 h" (title of PR #211); an interrupted rebase (`DECISIONS.md:697`).
- From 2026-11-04: Render's GitHub token got 403 "every 5 minutes", "so owner Issues never reached Relay" (`DECISIONS.md:730`).
- 2026-11-05 21:20 UTC → 11-06: "every Claude ticket blocked" by an untracked state file (`DECISIONS.md:771`).
- 2026-11-06 → 11-11: branch never merged `main`; on 2026-11-10 the checkout was "26 commits behind", "Merged to main ≠ live
  on the worker" (`docs/verification/R-0058_relay_e2e_2026-11-10.md:29-37`); the owner's live test R-0063 ran the legacy path
  (`DECISIONS.md:936`).
- 2026-11-14: R-0074 "stopped at 25 turns and reported a cut JSON tail" (`DECISIONS.md:1142-1145`).
- 2026-11-15: T-590 "was re-run every ~2 minutes and Telegram received ~300 cards" (`DECISIONS.md:1408`); the worker branch
  holds six commits "T-590: … re-check 2026-11-15 … stays open" from that day (`git log --all --author='FactoryOS AWS Worker'`).
- 2026-11-15 → 11-17: worker "stayed on 2026-11-15 code (36 commits behind main)" until a manual merge (#410)
  (`ROADMAP.md:392`, `DECISIONS.md:1904-1906`).

**ChatGPT.** Planner for 30 ROADMAP tasks (`grep -c 'Planner: ChatGPT'`), executor through the GitHub connector, never through
Relay. Paused 2026-10-30 (`DECISIONS.md:304-305`); its open tasks were retagged to Claude. PR #293 (2026-11-08) is titled
"ChatGPT lane taken over". Its Relay inbox draft #314 had "six security-review blockers" and was re-implemented by Claude as
#318 (`DECISIONS.md:984`). The coordination doc's own last line: "Живий двосторонній канал, автоматичний claim ChatGPT та
тестовий прогін ще не підтверджені" (`docs/handoff/CLAUDE_CHATGPT_COORDINATION.md:62`). Practice contradicts the rule that
handoffs go through Relay: "Today ChatGPT does assign Claude work through Issues (#231–#242)"
(`docs/handoff/NOTION_READ_PROOF_2026-11-05.md:33`).

**Gemini.** On 2026-11-03: "Gemini cannot open PRs yet … All five of its runs so far were `skipped`"
(`docs/handoff/TEAM_PLAN_2026-11-06.md:20`). Then 21 merged P3 PRs in five days and nothing after 2026-11-08. The lane board
showed it "Offline · 0 done" while it merged six PRs (`DECISIONS.md:726`). Free-tier limits recur: `gemini-2.5-flash` 404 on
the owner's key (`DECISIONS.md:941`); 429 RESOURCE_EXHAUSTED on 2026-11-16 (`DECISIONS.md:1837`) and 2026-11-17
(`ROADMAP.md:343`); the same free key is shared by MyCast TTS, Surfer search, voice transcription, peer review, subtopics and
the group chat (`DECISIONS.md:1443-1444`, `:845`, `:928`, `:945`, `:949`).

**"Assigned is not running."** The owner's original complaint (`docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md:45`: Telegram/Relay
did not show what ChatGPT and Claude were doing; Worker Center looked stale) produced T-599 "assignment ≠ execution"
(`ROADMAP.md:48-56`) and most of bucket A. A lane kept reading "Blocked" three days after the block (`DECISIONS.md:725`).

**Other incident.** 2026-11-17: `main` was overwritten by a contribution-graph generator run from the owner's account
("1214 commits 'Intense commit …'"); Claude restored it with a leased force-push on explicit owner permission; branch
protection was added afterwards (`DECISIONS.md:1841-1849`, `README.md:35-36`).

## Counter-evidence and caveats

- **The engineering is real and unusually disciplined.** 118 test files, CI with pip-audit, fail-closed publish gates, an
  honest evidence vocabulary (WORKS / BROKEN / UNKNOWN in `docs/verification/`), and a documented habit of not claiming live
  success. A report must not call the Relay, Telegram bot, owner desk, Media Finisher, Surfer (read) or Codex review "missing":
  each has live evidence.
- **Thirty days is short.** "Open for 25 days" is a large share of the project's life, not a long absolute delay. The MVP wave
  started on 2026-11-15; its HUMAN tasks are 0–2 days old, so it is too early to call them neglected.
- **The human gate is by design.** The owner's policy forbids agents from publishing, outreach or payments, so the absence of
  distribution is a policy outcome as much as a failure. The repo shows the policy also became the bottleneck.
- **Server-side state is invisible to this audit.** Listener accounts, delivered episodes, approval decisions, publishing
  queue, MyBrief feedback entries and Relay ticket history live on Render's disk. "No evidence in the repository" is not
  proof of zero; it is proof that nothing was recorded where agents and reviewers can see it.
- **Live grades lean on owner-side observation.** R-0087, the vault key and the SHA match are recorded from the owner's screen
  or word, because agent sessions get 401 on owner APIs. They are reported_secondary, not independently re-verified.
- **Classification is judgment.** Moving the browser runner and Surfer (10 tasks) from A to "product capability" would lower A
  to about 49 %; moving C2 into A would raise it to about 62 %. The conclusion does not change in either case.
- **ROADMAP is not the whole backlog.** 133 Issues carry a second, partly overlapping task system; ROADMAP lacks most MyCast work.
- **Stale documents exist.** `docs/specs/EVIDENCE_PROTOCOL.md:3` says "не реализовано" although Tier 1–2.6 is merged;
  `README.md:12-16` still lists v4.6/v4.7 "IN PROGRESS" and v5.0 "READY TO MERGE".
- **Worker productivity is under-counted on `main`.** The EC2 worker also runs non-commit work: the daily MyCast script, owner
  Q&A, browser read tasks, Codex review requests. And it resumed ROADMAP tasks on 2026-11-17 (T-626, T-631 on its branch).
- **Limited scope of the Surfer numbers.** 12 of 31 is the pre-fix score; fixes shipped in v5.11.0 but no post-fix run is recorded.

## Implications for FactoryOS

1. **Describe the system accurately in the report.** Working in production: FastAPI app (v5.12.0), Telegram bot and Relay
   tickets, owner desk, Claude EC2 worker (intermittent), Media Finisher, read-only Surfer, Codex PR review, the owner's daily
   MyCast. Not working or never exercised: any publisher, any outreach, any payment, the ChatGPT and Gemini Relay lanes, the
   shared MCP workspace, the MVP Builder hand-off, multi-tenant onboarding.
2. **"Autonomous AI company" is not what the evidence shows.** It shows one very productive interactive coding agent with a
   human approving almost nothing in review (median 6.6 minutes to merge) and approving everything at the market boundary
   (zero times so far). Autonomy is highest where risk to revenue is lowest.
3. **The binding constraint is the owner's market-facing actions, not agent capacity.** Seven open HUMAN tasks stand between
   the code and a first external signal. More coordination tooling cannot shorten that queue; each new feature has so far
   added a HUMAN task (LinkedIn → T-700-H, quiz → T-634-H, demos → T-645-H).
4. **The multi-lane design has not paid for itself.** ChatGPT and Gemini together produced 46 of 247 merged PRs, mostly small,
   at the cost of the coordination protocol, lane boards, workspace MCP, Gemini worker runtime, operator/battle model and
   repeated takeovers. The only durable cross-model value on record is Codex review. A sceptical plan would freeze lanes at
   "Claude builds, Codex reviews" until there is revenue.
5. **MyCast is the only candidate with a usage signal, and that signal is one user.** It also has the only built growth and
   access mechanics (accounts, share links, referral ledger, trial switch). The cheapest next evidence is not code: turn on
   what exists (T-620-H), put the link in front of people, and read the listener table.
6. **Replacing interviews with an in-product quiz removes the last mandatory human contact with users.** The quiz threshold
   (≥ 10 signed-in respondents) cannot fire without traffic that no task currently creates. The report should flag this as
   automation substituting for validation.
7. **Free-tier dependence is already a reliability problem.** One free Gemini key backs at least six features and returned
   429 on three consecutive days; GitHub Actions minutes ran out mid-month. "Zero additional spend" is being paid for in
   stalls and owner attention.
8. **Stop counting `[x]` as progress toward profit.** 98 tasks are done; the number of tasks with a customer-side DONE
   criterion that has been met is zero. A useful internal metric would be "external events per week" (posts, replies,
   sign-ups, payments), currently 0.

## Sources

Local repository (opened and read, `main` = `11a3330`):
- `/home/user/blackboxlab-factoryos/ROADMAP.md` (all 964 lines)
- `/home/user/blackboxlab-factoryos/README.md` (lines 1–310, changelog)
- `/home/user/blackboxlab-factoryos/DECISIONS.md` (heading index; sections at lines 304–331, 468–475, 640–699, 724–739,
  767–866, 925–1049, 1078–1097, 1133–1150, 1406–1447, 1496–1575, 1611–1631, 1665–1684, 1754–1795, 1835–1965; keyword searches)
- `/home/user/blackboxlab-factoryos/.autopilot/answers.md`
- `/home/user/blackboxlab-factoryos/CLAUDE.md`
- `/home/user/blackboxlab-factoryos/docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, `TEAM_PLAN_2026-11-06.md`,
  `NOTION_READ_PROOF_2026-11-05.md`, `T-590_ACCEPTANCE.md`; `CLAUDE_TAKEOVER_2026-10-29.md` (keyword search only)
- `/home/user/blackboxlab-factoryos/docs/verification/R-0058_relay_e2e_2026-11-10.md`, `surfer-benchmark-2026-11-16.md`
- `/home/user/blackboxlab-factoryos/docs/specs/EVIDENCE_PROTOCOL.md`
- `/home/user/blackboxlab-factoryos/docs/business_experiments/01_PRODUCT_HYPOTHESES.md`, `02_CLAUDE_HANDOFF_BUSINESS_DIRECTION.md`
- `/home/user/blackboxlab-factoryos/docs/gtm/security_check_pilot_kit_2026-11-03.md` (lines 1–30)
- `/home/user/blackboxlab-factoryos/docs/MVP_FACTORY_SPEC.md` (status lines), `render.yaml`, `requirements.txt`,
  `.github/workflows/*.yml` (structure), `app.py:79`, `mvp_factory.py` (stage list)

Git (full bare clone of `origin`, read-only): `git log`, `git rev-list --count`, `git shortlog`, `git log -S… -- ROADMAP.md`,
`git log --author='FactoryOS AWS Worker'`, `git log main..mycast/daily`, `git branch`, `git tag`.

GitHub REST API (read-only, 2026-11-17): `repos/<owner>/blackboxlab-factoryos/pulls?state=all` (283 rows),
`…/issues?state=all` (133 non-PR rows), `…/issues/412/comments`, `…/issues/416/comments`.

Live host (unauthenticated GET, 2026-11-17 20:38:40 UTC): `https://blackboxlab-factoryos.onrender.com/health`,
`https://blackboxlab-factoryos.onrender.com/api/version`.

Not opened: any `.env` file, any authenticated endpoint, any FactoryOS MCP tool.
