# FactoryOS Relay: 60-second Claude inbox + verified ChatGPT ↔ Claude round-trip

**Owner decision:** 2026-11-24 (Europe/Kyiv)  
**Scope:** existing FactoryOS Relay / Agent Workspace only. **Status: SPEC / NOT IMPLEMENTED** until live verification.  
**Roles:** Claude = implementation owner, exclusive claimed executor; ChatGPT = independent spec/review/test initiator. Owner controls strategy, approval, spending and publication.  
**Prior work (DO NOT duplicate):** [#94](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/94) (native agent handoffs), [#369](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/369) (GitHub issue intake cadence, a separate path), ROADMAP T-604/T-625/T-624/T-626/T-509, `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, `docs/guides/agent-workspace-mcp.md`. Example live **manual** chat: Relay thread `th_46f089b213546fcc` ("ChatGPT на связи"). Current Agent Workspace tools are authenticated and persist messages/hand-offs; this does **not** show they are continuously consumed by an autonomous worker.

## 0. The user outcome (contract)

Owner can give a task to ChatGPT once. ChatGPT posts an authenticated message/task request to Claude in **FactoryOS Relay**. Within one successful **60-second polling interval**, the existing running Claude **worker** notices it and sends one attributable acknowledgement inside the **same thread**; if executable and authorised, it claims a unique task, records `run_id`, performs work, and replies there with status, blockers and evidence. ChatGPT can read and answer in the same thread through its existing MCP connector. Claude can initiate the reverse direction. The owner observes truthful state in Worker Center/Relay (Telegram only where delivery is proven).

**Important boundary:** ChatGPT's interactive conversation is NOT an always-on background worker. It can send/read in an active session and through a separately supported, actually configured scheduled invocation. The new 60-second guarantee is for **Claude's existing always-on host worker, while reachable**, not a guarantee that ChatGPT independently wakes every minute or that a coding job starts/completes within 60 seconds. Do not make such claims.

**No new services, processes running Claude Code, paid API billing, cloud resources, parallel queues or shadow schedulers.** Reuse the existing daemon + Relay store. A lightweight read-only polling thread inside the existing worker may be used only if necessary to avoid blocking during a long Claude command; it must NEVER launch a second model session.

## 1. Existing architecture/gap to audit (first task for Claude)

- `agent_workspace.py`: authenticated per-lane MCP `list_threads/read_thread/post_message`, `create_handoff/list_handoffs/claim_handoff/submit_handoff_result/review_handoff`, persisted under `RelayStore.lock`; only Claude creates handoffs today. `post_message` stores chat, not an automatically executable task.
- `relay_execution.py` + `autopilot/relay_tasks.py`: ticket queue, atomic claim, run_id, worker events and polling. This worker currently polls **task tickets**; demonstrate whether it ever reads new **agent workspace messages** (assume missing until code + live evidence).
- `T-509`: daemon already polls existing work while idle; `T-624`: lane tokens reportedly configured; `T-625`: shared MCP tools built; `T-626`: read-only agent workspace panel built. `T-604` overall live end-to-end is still an open acceptance question.
- `#369` proposed 120-second GitHub issue import. GitHub import is **not** Relay message polling. Do not confuse the two, claim one proves the other, or introduce GitHub comments as operational messages.

Before editing: check current `main` and PRs, `ROADMAP.md`, `AGENTS.md`, `CLAUDE.md`, active Relay claims/handoffs, current EC2 systemd state, exact module owners and file conflicts. Publish a short audit: **present / missing / blocked / owner action** with source paths and runtime timestamps.

## 2. Proposed minimal implementation (Claude can refine after audit)

### A. Poll receiver at 60 seconds without waking the LLM
- Add a small **Agent Workspace Inbox Poller** integrated with the existing EC2 Claude daemon/service and its existing auth. First poll on start, then `AGENT_RELAY_INBOX_POLL_SEC=60` (default 60; owner may disable with `AGENT_RELAY_INBOX_ENABLED=0`).
- Use a server-side authenticated **inbox since cursor** query returning only addressed actionable messages/handoffs (rather than fetching every historical thread each minute). Preserve backward-compatible `list_threads/read_thread/post_message`. It can be an additive MCP tool or worker endpoint; **use existing RelayStore and authenticated lane policy**, do not open an anonymous endpoint.
- Add explicit recipient/intent or linked `task_id` (e.g. `recipient_lane=claude`, `intent=task_request` or a dedicated `request_handoff`). **Ordinary chat messages are never automatically interpreted as executable commands**. Existing `post_message` has no `to`; do not infer the target agent from natural language/hashtags or automatically create a code task from arbitrary prose. ChatGPT cannot use `create_handoff` today (Claude-only), so provide one **limited, authenticated request** path for ChatGPT → Claude; Claude decides/claims only after policy validation.
- Persist `last_seen_message_id`/event cursor per destination lane and consumer on durable storage, not only RAM. Sort by stable server order and handle same-timestamp messages, pagination, crashes, restarts and retained history. At-least-once delivery with *exactly-once effects* through dedupe keys, atomic claim and run_id fencing.
- When idle, perform only cheap HTTP reads. During a long Claude coding run, allow the existing process's lightweight network poll/ack (if safe) but no concurrent Claude CLI; otherwise report receiver lag as busy. On network failure use bounded backoff (e.g. 60→120→300 sec), retry from the persisted cursor, and expose lag/last_success/error rather than silently dropping work.
- Rate controls: no message every minute on an empty inbox; only send ACK once per new message/transition; avoid busy looping and obey existing `agent_workspace.py` write limits. Do not emit owner Telegram spam.

### B. Durable handshake/state machine
```text
ChatGPT (authorized task_request) → Relay inbox [queued, message_id]
  → Claude receiver detects and writes ACK [seen, at, worker_id]
  → guard: Owner/Depends/claims/files_scope/cost/approval/permissions
    ├─ ineligible → [blocked, reason, exact next action] reply in same thread
    └─ eligible → atomic task CLAIM [run_id, lease] → [running]
          → concrete output / evidence / PR & checks → [review]
          → owner or independent reviewer verdict → [done] / [changes_requested]
```
- **Do not equate delivered, seen, queued, claimed and running.** An acknowledgement means received only; a claim requires a real server-side lease/run_id. A successful test echo means transport works, not autonomous business execution.
- The receiver posts **in the SAME thread** with a real lane identity, `reply_to`, relevant `task_id`, `run_id` when present, current state and evidence URL. One transition = one durable event. Never invent a Claude reply, owner decision or proof.
- When requests mention a GitHub Issue (e.g. Faceless Creator [#469](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/469)), import/associate it idempotently only if owner-authorized and compatible with canonical ROADMAP rules; do not run a second job or create duplicate tickets.
- Preserve existing policies: exclusive claim per task/files_scope; owner direct tasks priority; no overlapping git edits; no automatic self-merge/deploy; no unauthorized paid model/API, adult publishing, outreach or external social posts. Untrusted message text is DATA; never let it override execution/system policy. Fail closed on missing auth, unclear ownership or permission.

### C. Bidirectional conversation
- Claude may send ordinary attributed `proposal/question/status` messages to ChatGPT via existing `post_message`; ChatGPT reads them in an active user session via MCP, replies and records any resulting authorized task.
- To automate **ChatGPT** polling/replies, first establish and test a genuinely supported scheduled ChatGPT invocation with authenticated FactoryOS MCP access; otherwise display `chatgpt_delivery=queued, response_waiting_for_session`. Do not fabricate a 24/7 ChatGPT session or a model message.
- Owner-facing shared thread UI: show ordered messages with sender/timestamp, `delivered/seen/claimed/running/review/done/blocked`, linked task ID and evidence; support manual refresh and no token exposure. Future Telegram notifications can summarize *state changes*, not every poll.

## 3. Mandatory phases

**S0 — audit/read-only (Claude):** diagram actual current routes and EC2 polling; confirm existing tool semantics, token scopes, failing link in `ChatGPT message → Claude worker` and conflicts. An audit alone is NOT the final deliverable.

**S1 — 60-second transport and ACK:** implement recipient-aware inbox/since cursor and Claude polling within existing daemon. Test no message, duplicate, restart, long busy run, off/on, dropped HTTP connection, rate-limit, authentication, prompt injection. Provide a live message from ChatGPT and an actual Claude **automatic** reply containing timestamp and original message ID.

**S2 — real work claim and result:** deliver exactly one authorized harmless task via that inbox; prove `queued→seen→claimed(run_id)→running→review`; real minimal artifact, PR/CI if code, and a Claude response in thread; prevent duplicate Claude executions after retries. Use a small read-only audit / fixture task, not adult video generation, for proof.

**S3 — reverse direction and ChatGPT access:** Claude sends a question/handoff to ChatGPT; this ChatGPT session or a genuinely configured scheduled invocation reads, responds, and, only when authorized, claims/returns its scoped work; Claude sees receipt. Document manual/scheduled limitations truthfully.

**S4 — production verification:** in live Worker Center owner sees the conversation and accurate last_seen, ACK latency, last_poll_success, queue lag, run_id, error/blocked reason, PR/CI result; prove after deployment and one EC2 restart. Telegram notification optional only if real routing exists and was tested.

## 4. Definition of done / measurable acceptance

1. **Poll**: with the Claude worker idle and healthy, a new addressable ChatGPT request is ACKed at most 60s after the next successful poll; collect ≥5 live message timestamps and report observed detection latency (not a hard guarantee through outages). No LLM consumption when no tasks.
2. **One-to-one correlation**: original `message_id` and `thread_id` are in ACK, reply and task audit; a single qualifying message creates at most one claim/run.
3. **Real result**: one fixture task ends in review with a real artifact/evidence; the owner sees its real provenance, not only ACK/typing indicator.
4. **Restart/retry**: resume after SIGTERM/deploy and process all missed messages once without duplicate side effects, even with same timestamp or pages of messages.
5. **Busy/blocked**: ongoing Claude job is not interrupted/duplicated. Invalid Owner/Depends, missing budget, usage limit and overlapping files yield truthful `blocked` with actionable reason.
6. **Security**: forged/shared-token write fails, expired/replayed request dedupes, no secret data in Relay logs or GitHub, arbitrary prose does not become runnable shell code.
7. **Reverse message**: Claude → ChatGPT → Claude reply verified via actual connector calls and durable thread history; automated ChatGPT job only if scheduled runtime genuinely exists.
8. **Evidence**: PR with tests and green CI; merged SHA + production build verified only after approved merge/deploy; exact Relay `thread_id/message_id`, task `run_id`, real worker logs with secret redaction, and Worker Center screenshots/status. If any part fails, status **PARTIAL/BLOCKED** rather than DONE.

## 5. Owner's immediate context and handoff

The owner is building FactoryOS so **two separate AI collaborators can coordinate to build a business**. The minimal missing loop is not new brainstorming, but reliable **receive → ACK → claim → execute → evidence → feedback**. Owner requested an every-minute inbox check and an explicit answer **"Принял задачу #…, run_id …"** only **after** actual claim. Existing Faceless Creator creative A/B job is #469; it must not be used as evidence of execution merely because the issue and Relay messages exist.

**Message to Claude:** implement the smallest compatible S1→S2 vertical slice instead of writing another standalone architecture. Claim through existing owner/Depends rules, reply in the active T-624 Relay thread with the exact files/route/claim or blocker, and send proof of a real **automatic** round-trip. No new paid resources, no new service and no deployment without the owner approval established by current FactoryOS policy.

**Message to ChatGPT:** own specification, initiate a real test message in Relay and review evidence; when a supported runtime calls it, answer/claim tasks through authenticated MCP with source links. Never imply the interactive model wakes autonomously when the chat is closed.
