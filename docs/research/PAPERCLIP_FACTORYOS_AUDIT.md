# Paperclip × FactoryOS — compatibility audit, threat model and offline bridge POC (GitHub #368, S0/S0b)

Date: 2026-11-14 · Owner: Claude · Relay: R-0078 · Status: **S0 partly BLOCKED/UNKNOWN, S0b done (offline)**

This memo authorizes nothing. No Paperclip install happened, there were no paid calls, no production or Relay
changes, and no merge or deploy. The next step is the owner's decision at the end.

## 0. What was and was not verified in this session

| Item | Result | Evidence |
|---|---|---|
| Upstream Paperclip repo/docs/releases read | **NOT VERIFIED.** WebFetch and `gh api` were denied on this worker (don't-ask permission mode). | Tool denials in the R-0078 session |
| Exact release / audited commit pinned | **BLOCKED/UNKNOWN.** No version is recommended until someone reads the tag. | — |
| EC2 spare capacity | **Measured, read-only, no secrets:** `/proc/meminfo` MemTotal 931 880 kB (~0.9 GiB), MemAvailable 292 560 kB (~286 MiB); swap 2 GiB with ~496 MiB already used; `/proc/loadavg` 0.09. CPU count and disk could not be read (Bash denied). | `/proc/meminfo`, `/proc/loadavg` |
| Bridge POC + offline tests | **Done**: 31 tests green, 0 network (socket guard) | `python test_paperclip_bridge.py` |
| Production Relay queue / worker / Render deploy unchanged | **Not independently verified** (no Render or relay.json access from here). The diff touches no `app.py`, `autopilot/`, `render.yaml`, `deploy/` or `.github/`. | `git show --stat` |

### Upstream facts: prior knowledge only, re-verify before S1

These come from earlier knowledge of the public repo, **not from a read today**. Treat each one as a checklist line
to confirm against a pinned tag:

- **Project:** `paperclipai/paperclip`, a Node.js server with a React UI. It orchestrates "companies" of agents through
  issues, heartbeats/wakeups, atomic issue checkout and per-agent budgets.
- **License:** believed MIT. Check `LICENSE` at the pinned tag and audit transitive licenses (`pnpm licenses list`).
- **Runtime:** Node.js 20+ and pnpm 9+. Default storage is an embedded PostgreSQL under the user's home data dir;
  an external Postgres can be set through `DATABASE_URL`.
- **Network:** default port **3100**. The `local_trusted` mode binds to loopback with **no login**. The
  `authenticated` mode adds board login and needs private/public exposure settings.
- **API auth:** agent API keys sent as `Authorization: Bearer …`, plus board sessions/tokens. Check how keys are
  scoped (per agent, per company) and rotated.
- **Adapters:** local CLI adapters (Claude Code, Codex), `process` and `http`. The HTTP adapter POSTs a wake payload
  (agent/run/issue context) to a configured URL. Its auth header, timeout, retry and how it reports results back are
  **not confirmed**, and the UI may mark the adapter "Coming soon".
- **Install:** the quickstart uses `npx paperclipai onboard`, which resolves to `@latest`. **Do not use it.** Clone
  the pinned tag, check its commit hash, and run `pnpm install --frozen-lockfile` as an unprivileged user with
  bootstrap scripts read first.
- **Cancellation semantics** and **data retention/export:** unknown. Must be read in source before S1.

## 1. Capacity verdict

The host has ~0.9 GiB RAM, ~286 MiB available, and already uses swap while the production Claude worker runs.
Node + pnpm install/build + embedded Postgres + the Paperclip server needs well over 1 GiB during install, and
several hundred MiB at rest (an estimate, not a measurement). **A test install on this EC2 is rejected:** it would
compete with the live worker for memory and could OOM-kill it.

**Sandbox plan instead (S1, owner-gated):**

1. Use the owner's local machine or a disposable dev VM the owner already has (no new paid instance), with Docker or a
   dedicated unprivileged user.
2. Clone the pinned tag and check its commit SHA. Read `package.json` scripts and any `postinstall` before running them.
3. Run `pnpm install --frozen-lockfile --ignore-scripts`, then run only the scripts that were reviewed.
4. Start in `local_trusted` mode bound to `127.0.0.1:3100`, with a separate data dir and DB. Add no agents with real
   CLI credentials, register no model keys, and leave budgets at 0.
5. Create one mock company, one mock issue and the HTTP adapter pointed at a local echo. Record RSS/CPU/disk.
6. Tear down by deleting the data dir. Production is not touched at any step.

## 2. Options

| | A. Isolated read-only dashboard with mock tasks | **B. Paperclip → optional adapter → Relay (observe/propose only)** | C. Adopt patterns/UI only |
|---|---|---|---|
| Live dependency | None (separate sandbox) | Optional, disabled by default; Relay works the same with it off | None |
| Dispatch / claim owner | Paperclip, for mock data only | **Relay only.** Paperclip events become proposals and never claim. | Relay |
| Value | Lets us judge the UX of org charts, budgets and heartbeats | One pane correlating Paperclip issues/runs to Relay tickets, with real evidence | Ideas (atomic checkout, budget caps, heartbeat UI) carried into Relay/Agent Office |
| Risk | Low; extra machine resources | Medium: a second scheduler unless Paperclip agents are disabled, plus webhook auth and a stale mapping | Lowest |
| Cost | Sandbox time | Sandbox, plus bridge upkeep and a version-pinning burden | Engineering time only |
| Reversible | Yes | Yes (flag off, delete mapping file) | Yes |

**Recommendation: C now, plus B kept as a disabled POC (this PR). Consider A only as a short owner-approved sandbox
pilot (S1).** Paperclip cannot be pinned or capacity-checked today, the EC2 host has no spare memory, and the main
value (budgets, heartbeats, org view) overlaps with Relay, Agent Office and the Evidence Protocol that already exist.

**Why a full Paperclip-for-Relay migration is not part of this issue:**

- Paperclip's checkout/wakeup/budget engine is itself a dispatcher. Running it next to Relay creates two sources of
  claims (double execution, conflicting budgets).
- Relay carries the guarantees the owner relies on: unique claims, stale-claim release, roadmap claim fences, the
  Evidence Protocol (`claimed → linked → checked → accepted`), Telegram/owner verdicts, and the #41 E2E.
  Paperclip has none of these as of today's knowledge.
- Paperclip expects agent CLI credentials or API keys. Using the Claude Code subscription as an "API key" for a
  third-party scheduler is not something we can assume is allowed or safe.
- It would need production changes (a new service, ports, secrets). The issue forbids all of these.

## 3. As-is and proposed flow (single source of truth = Relay)

```
AS-IS
 Owner / GitHub Issue (Owner: Claude) ──► Relay (Render, relay.json)
     queued ──claim(worker_id)──► claimed/run_id ──► running ──► committed ──► pushed ──► PR ──► CI ──► merged ──► deployed
                         ▲                                                          │
                 Claude worker (EC2 autopilot/)                            Evidence: claimed→linked→checked→accepted

PROPOSED (B, optional, flag OFF by default)
 Paperclip (sandbox, 127.0.0.1:3100)                    FactoryOS
   issue.wake / issue.updated / issue.cancelled
        │ HMAC-signed POST (loopback/tunnel only)
        ▼
   integrations/paperclip/bridge.py ──read-only RelayStore.get──► Relay ticket (unchanged)
        │ writes ONLY its own mapping file
        ▼
   proposed mapping {paperclip_issue ↔ relay_ticket, observed stage, evidence level}
        ╳ never: create/claim/enqueue/cancel Relay ticket, call GitHub, wake worker, write to Paperclip
```

### Correlation chain (one task)

| Field | Source | Example |
|---|---|---|
| `project_id` | `ticket.source.repo` (GitHub) or channel | `Pavlovskyi-Andrii/blackboxlab-factoryos` |
| `issue_or_task_id` | `source.issue_number` / `source.task_id` | `368` / `T-602` |
| `relay_ticket_id` | Relay | `R-0078` |
| `relay_run_id` | `execution.run_id`, set **only** by Relay `claim` | empty while queued |
| `paperclip_company_id`, `paperclip_issue_id`, `paperclip_run_id` | Paperclip event (signed) | `co-1`, `PC-1`, `run-9` |
| `branch`, `pr_url` | Relay execution evidence | `relay/r-0078-…`, GitHub PR URL |
| `relay_stage` | `queued` (nobody claimed) / `claimed` (a Relay worker holds it) / `done`/`blocked`/`failed` (worker report) | — |
| `evidence_level`, `verified`, `owner_accepted` | `evidence.level()` | `done` + `claimed` ≠ verified; only `checked`/`accepted` count |

## 4. Threat model and mitigations

| Threat | Mitigation in POC / required for S1 |
|---|---|
| `local_trusted` API (no auth) reachable by other local users or processes | S1: dedicated unprivileged user and container/network namespace, bound to `127.0.0.1` only; `authenticated` mode before any non-sandbox use. Port 3100 is never exposed (no security-group or tunnel change without approval). |
| SSRF through the bridge's outbound call | Only `http://127.0.0.1:<port>` is accepted (no hostnames → no DNS rebinding; metadata IP refused). Redirects are refused, env proxies ignored. The only call is a GET. |
| Webhook forgery / replay | HMAC-SHA256 over `timestamp.body` with a ≥32-char secret, ±300 s skew window, and a persisted `event_id` dedupe that survives restart. Note: this signing scheme is **ours**. If the Paperclip HTTP adapter can only send a static header, S1 must add a tiny signing shim or reject the adapter. |
| Forged IDs / injection in payload | Strict regex allowlists for event, issue, run, company and Relay IDs; type checks; 16 KiB body cap; unknown event types rejected. |
| Prompt injection via Paperclip issue text | The bridge ignores titles and bodies completely and passes no text to agents. Relay stays the only path to a worker. |
| Token exposure | Secrets are `repr=False`, never returned or persisted (tested). No real credentials in fixtures. `.env` is untouched. |
| Unauthorized GitHub / task changes | The bridge has no GitHub client and only a read-only Relay lookup. Tested: the relay.json hash is unchanged across wake/update/cancel. |
| Shell access | No subprocess anywhere. Paperclip `process`/CLI adapters stay disabled in S1. |
| Provider billing | S1 budgets = 0, no model keys, no Claude subscription credentials given to Paperclip. |
| Overlapping scheduling / double claim | Relay is the only claimer. One Relay ticket ↔ one active Paperclip issue (`double_claim_rejected`). A Paperclip issue cannot be re-pointed. |
| Stale state | Out-of-order events rejected (`stale_event`). The mapping records Relay's state at observation time, and the UI must show it with its timestamp. |
| Restart recovery | Atomic `os.replace` mapping file; event log capped at 5000. Replay after restart returns the stored mapping. |
| Paperclip down / slow | Timeout clamp 0.5–10 s, ≤2 retries with capped backoff, no retry on 4xx. Fails closed (`503 paperclip_unavailable`, nothing stored). |
| Flooding | In-process rate cap of 1–60 events per minute. |

## 5. POC (S0b) — `integrations/paperclip/`

- `bridge.py`: `BridgeSettings` (env, flag OFF, clamps, fail-closed `problems()`), `PaperclipClient` (read-only GET,
  injected transport), `MappingStore` (own JSON file), `PaperclipBridge.handle_event(headers, raw) → (status, body)`.
- Not mounted in `app.py` (a test asserts this). Mounting a route is S1.
- Tests: `test_paperclip_bridge.py` (31 tests, socket guard active). Also imported by `test_relay_execution.py`, so the
  existing CI step runs them without a workflow edit.
- Coverage: valid mapping, queued vs claimed, duplicate replay, replay after restart, double claim, remap, stale event,
  cancellation, unauthenticated, wrong signature, tampered body, stale signature, wrong owner, forged Relay ID, forged
  Paperclip issue, invalid data, malformed payload, size cap, rate cap, Paperclip unavailable, timeout + retry,
  retry exhaustion, 403 not retried, env clamps, disabled by default, missing settings, loopback-only URLs, import
  without network, no real work across the full flow, corrupt state.

## 6. Decision memo

- **Recommendation: patterns only (C) now. Keep the bridge POC disabled. Do not install on the production EC2.**
- **Owner decisions needed:**
  1. Allow an S1 sandbox pilot (option A + bridge) on the owner's own machine or an existing dev VM? If yes, someone
     with network access must first pin the release tag and commit and record its license.
  2. Or close as "patterns only": file follow-ups for budget caps and a heartbeat view in Agent Office.
- **Risks if adopted later:** a second scheduler, version churn of a young project, unclear HTTP-adapter auth and
  cancellation, and memory pressure on the current EC2.
- Any Relay-linked execution needs a second explicit approval, confirmed #41 behaviour, unique claim ownership, a
  bounded budget, an E2E audit and a rollback plan.
