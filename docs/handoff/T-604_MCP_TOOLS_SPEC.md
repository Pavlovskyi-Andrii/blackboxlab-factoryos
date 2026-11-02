# T-604 — MCP handoffs and FactoryOS Team Telegram chat: client/API specification

**Author:** ChatGPT · **Requested by:** owner, 2026-11-02 · **Issue:** #115 (specification) · **Implementation owner:** Claude, #94 · **Status:** SPEC ONLY; no live group chat, ChatGPT execution route or Gemini runtime has been demonstrated. This PR adds documentation, not code.

## Goal and source of truth

The owner wants one **private Telegram group** where the owner can ask a question, see separate, attributed viewpoints from Claude, ChatGPT and (when connected) Gemini, discuss alternatives, and explicitly approve a shared decision. **FactoryOS Relay is the single source of messages, conversation threads, tasks, claims, decisions and audit history.** Telegram is one client; a matching Worker Center thread view can be built from the same events. GitHub remains for code/PR/CI/evidence, NOT the operational inbox. Avoid a second queue or a Telegram-only state store.

A message is **not** automatically a task, a suggestion is **not** owner approval, a model-named placeholder is **not** a live operator, and reading a message is **not** proof that a model ran. Keep approval and read-receipt/status separate. Owner instructions take priority.

## Verified current repository facts (main, checked 2026-11-02)

- **[verified source: `app.py`]** Existing `POST /mcp` supports JSON-RPC methods `initialize`, `ping`, `tools/list`, `tools/call`, plus `notifications/initialized`. The **only** registered tools today are `get_design_context`, `list_build_tasks`, `submit_design_review`. There are no `post_message`, `read_thread`, handoff or chat tools yet.
- **[verified source: `app.py`]** `_factory_mcp_authorized` checks configured `FACTORY_MCP_TOKEN` with Bearer header (also has a query-key fallback). Treat query-string token as legacy; for new write tools require header/scoped credential, avoid token-bearing URLs, and never log credentials.
- **[verified source: `relay_execution.py`]** `RelayQueue` has durable state, atomic task claim/run IDs, events and owner lanes. Reuse its storage/locking, idempotency and recovery model; extend it rather than bypass it.
- **[verified source: `app.py`]** The current webhook endpoint `/api/integrations/telegram/webhook` verifies Telegram webhook secret. After existing command handling, it explicitly **ignores non-private chats**. Group membership/identity binding and group message handling are **not yet implemented**.
- **[verified source: `app.py`]** Existing `_telegram_send_to(chat_id, text)` sends via the configured bot; owner pairing currently stores one **private** chat ID. Do not replace or reuse that private pairing for group authorization.
- **[verified source: `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, #94]** ChatGPT hourly inbox and actual Relay round trip are goals, not proven working capabilities. A direct owner-to-ChatGPT command remains valid.
- **[not verified]** Whether this ChatGPT account's connected FactoryOS MCP can actually be invoked in a scheduled automation, with appropriate scopes and persistent authorization. The currently available GitHub connector here can read/write GitHub; it does **not** itself constitute an authenticated FactoryOS Relay/MCP channel. Exact rate ceilings/error formats of a future ChatGPT connector must be probed.
- **[not verified]** Current deployed Render SHA, owner Telegram group chat_id, Telegram bot group permissions, group webhook delivery, ChatGPT subscription-as-runtime automation, Jules/Gemini worker execution, or a true multi-agent discussion. No claim of "online" until evidenced.

## MVP user experience (one bot, one private group)

1. Owner creates a private Telegram group **FactoryOS Team** and adds the **existing FactoryOS bot**. A bot cannot be assumed to create the group for the owner. Group is unbound until an **owner-authenticated pairing** records immutable Telegram `chat.id`, owner Telegram `user.id`, optional `message_thread_id` and a timestamp. **Never trust display names or group titles**. Bind through signed/expiring approval in owner-authenticated web UI or challenge from the already paired private DM; require both ends and prove the invoking user is the known owner. No public self-pairing.
2. Message sent by the approved owner in the bound group becomes a Relay `thread_message` event with `thread_id`, `message_id`, `tg_update_id`, `chat_id`, `from=owner`, text, timestamp and `dedupe_key`. Others in the group are ignored for commands by default, or explicitly granted `participant` read/write without authority to approve/assign.
3. `/discuss <topic>` or a reply to an ongoing discussion starts a **bounded discussion**, not code execution. Relay records the ordered transcript and creates max one turn per available agent in round 1. The bot publishes results tagged **[Claude]**, **[ChatGPT]**, **[Gemini]** with timestamps/status and a source event ID; messages come from *one bot*, not falsely from individual Telegram accounts. A missing agent reads `offline/unavailable — not called`, not a synthetic answer.
4. Optional single follow-up round after owner `/continue` (or a bounded explicit request); no automatic endless agent-on-agent loops or new paid API usage. Initial max 2 rounds, 3 agents, 1 reply each per round, text cap and hard deadline; adjustable only with safe owner controls. `/stop` or `/close` cancels further turns and records the state.
5. `/decision <statement>` presents a **preview** in the bound chat. Only known owner confirms via an authenticated callback (short expiry, chat/user match), then stores `owner_decision` with revision, version/sha of shared rules, UTC author and originating `thread_id`. A proposal or majority vote is **not** approved automatically. All agents see the approved event on next authorized sync.
6. To test, owner asks e.g. **"Как именовать задачи GPT / Claude / Gemini, чтобы исключить дубли?"**, watches a sequential exchange and confirms a decision. A successful run requires evidence of each *genuinely executed* turn, event IDs and honest offline states. Group message alone must not invoke production, publishing, writing code, changing accounts, or billing.

**Telegram API caveat [official docs]:** privacy mode affects which group messages reach a bot. Telegram currently documents an optional Bot-to-Bot Communication Mode, but this MVP uses **one existing bot and Relay**, therefore does not depend on bot-to-bot messages or on creating three bot identities. See https://core.telegram.org/bots/features and https://core.telegram.org/bots/api .

## Data and security contract

- `thread = {thread_id, chat_id, status: open|paused|closed, origin: telegram, created_by_owner_id, created_at, last_message_id, topic, revision, rounds_used, max_rounds}`
- `message = {message_id, thread_id, from: owner|claude|chatgpt|gemini|system, to: []|[...], kind: question|comment|proposal|answer|decision|status, body, timestamp_utc, source_update_id?, reply_to?, actor_auth_subject, run_id?, dedupe_key, visibility: owner_team, evidence_refs: []}`
- `handoff = {handoff_id, task_id, thread_id, from, to, priority, depends: [], files_scope: [], objective, done: [], state: queued|claimed|running|review|done|blocked|released, run_id?, lease_expires_at?, artifacts: []}`
- `decision = {decision_id, thread_id, accepted_by_owner_id, approved_at, text, revision, source_message_id, rules_file_sha?, acknowledgment_status_by_lane}`
- Every state mutation is durable/atomic, scope-checked, idempotent by client-generated `idempotency_key` plus origin update ID. Preserve original provenance, never accept user-written `from=claude` as authenticated identity. Redact secrets, forbid private Gmail/content in shared chat, cap retention with owner-initiated export/delete.
- **No capability escalation:** owner command permission belongs only to the verified owner Telegram user ID; worker tokens identify a single worker lane (or separately scope credentials). A shared `FACTORY_MCP_TOKEN` is not proof of being the `claude` or `gemini` model. Do not allow arbitrary `from` impersonation. If no per-lane auth, keep write operations blocked.
- Legacy private chat remains intact; group bridge is separately opt-in, validated and revocable. Webhook secret, membership and owner ID must all be checked; reject updates from unbound chats before persisting any data.
- No secret prompt injection from group members; treat content as untrusted task input. Do not bypass `Depends`, files scope or owner approval. Every claim requires unique `run_id`; a message or `seen` marker is not a claim.

## Proposed MCP tools (new: Claude implements behind authenticated /mcp)

All tools use existing JSON-RPC `tools/call` with `params.name` and `params.arguments` plus bearer lane credentials; the **server** derives `actor` from the authenticated principal. Shapes below are *proposals, not currently exposed tools*. On errors, prefer structured JSON `{code, message, retryable, details?}` returned with MCP `isError: true` for domain problems; authentication/invalid JSON are HTTP 401/403 and 400 where appropriate; use stable error codes rather than leaking stack traces. All write responses include `event_id`, `at`, `idempotent_replay`.

### `post_message`
Input: `{thread_id:string, body:string, kind:"comment"|"proposal"|"answer"|"status", reply_to?:string, idempotency_key:string}`. Recipient/scopes derive from bound thread; owner decision cannot be written with this tool. Output: `{message_id, thread_id, event_id, at, idempotent_replay}`. Errors: `THREAD_NOT_FOUND`, `THREAD_CLOSED`, `NOT_A_PARTICIPANT`, `LENGTH_EXCEEDED`, `DUPLICATE_CONFLICT`, `RATE_LIMITED`.

### `read_thread`
Input: `{thread_id:string, after_message_id?:string, limit?:integer}` (1–100, default 50). Output: `{thread, messages:[...], next_cursor?, policy_sha?, your_ack_revision?}`. Errors: `THREAD_NOT_FOUND`, `FORBIDDEN`, `CURSOR_INVALID`. Pagination and explicit read acknowledgments; read must **not** be treated as model reasoning/execution proof.

### `list_handoffs`
Input: `{state?:"queued"|"claimed"|"review"|"blocked"|"all", limit?:integer, cursor?:string}`. Target lane is bound to token, cannot be overridden by input. Output `{items:[handoff...], next_cursor?, policy_sha}`. Errors `UNAUTHORIZED_LANE`, `CURSOR_INVALID`.

### `claim_handoff`
Input: `{handoff_id:string, idempotency_key:string, policy_sha:string, requested_files_scope?:string[]}`. Atomic claim must validate lane, target, `Depends`, no active conflicting `task_id/files_scope`, freshness of policy SHA, and lease; must fail closed if Relay unavailable. Output `{handoff_id, run_id, lease_expires_at, files_scope, event_id, idempotent_replay}`. Errors `CLAIM_CONFLICT`, `DEPENDENCY_PENDING`, `POLICY_STALE`, `AUTH_FAILED`, `NOT_ASSIGNED`, `RELAY_UNAVAILABLE`.

### `submit_handoff_result`
Input: `{handoff_id:string, run_id:string, summary:string, artifact_urls:string[], checks:{name:string,status:"pass"|"fail"|"not_run",evidence?:string}[], idempotency_key:string}`. Server validates signed/assigned run and allowed GitHub URL host/repo/branch. Return `{state:"review", event_id, at, idempotent_replay}` — **not merged or done**. Errors `RUN_ID_MISMATCH`, `LEASE_EXPIRED`, `ARTIFACT_INVALID`, `CONFLICT`.

### `release_handoff`
Input: `{handoff_id:string, run_id:string, reason:"done_review"|"blocked"|"cancelled"|"owner_reassign", checkpoint?:{branch?:string,commit?:string,pr_url?:string,notes?:string}, idempotency_key:string}`. `owner_reassign` available only to authenticated owner. Output `{state:"released"|"blocked", event_id, at, idempotent_replay}`. Errors `RUN_ID_MISMATCH`, `NOT_PERMITTED`, `ALREADY_RELEASED`. Release prevents concurrent double execution and preserves checkpoint.

**Group-chat-specific server endpoints** (separate from MCP; exact route names are implementation details): authenticated owner `POST /api/factory/team-chat/pair/init`; webhook handler for approved group; owner `GET /api/factory/team-chat/threads`; scoped `POST /api/factory/team-chat/decision/confirm`; safe text-only `sendMessage` projection. The user sees group discussion by Telegram bot, and the same messages in Worker Center when its read view is implemented.

## Client capability and startup verification

- **[verified code]** This repository's `/mcp` supports a tool-discovery response with the three current tools; **new tools above are not implemented**.
- **[not verified]** ChatGPT automation can independently invoke the user's FactoryOS MCP tools at a scheduled time, use a persistent credential, or receive an event push. Do **not** claim a 24/7 participant until a real authorized tool execution succeeds; GitHub reading alone cannot substitute.
- **[not verified]** Claude subscription CLI can process chat messages asynchronously inside existing EC2 quotas without consuming paid API; prove the actual run, status and rate-limit behavior before showing Claude "responding".
- **[not verified]** Gemini/Jules receives Relay chat turns; treat Gemini as unavailable until #119 / roadmap T-607/T-606 has proven runtime authorization.
- Each agent on boot reads current `AGENTS.md` / `CLAUDE.md` or `GEMINI.md` + a future shared policy, sends SHA acknowledgment, and is denied **new task claims** when stale; mere SHA acknowledgment is not proof of understanding. Conversations may remain readable if claims are blocked.

## Acceptance / testing matrix (implementation task #94 + Telegram group slice)

1. Group never bound: injected update from arbitrary group is ignored; no message or notification leaks.
2. Real owner-bound private group: owner `/discuss` creates one Relay thread and one visible bot acknowledgment; same `update_id` delivered twice creates one event; reply threading works.
3. Spoof: other group member cannot bind, launch discussion or approve a decision, even with display name identical to owner.
4. Two live lanes: authenticated Claude and ChatGPT **each** post a real answer; origin labels faithfully match execution evidence, replies land in owner group; transcript matches Relay read view.
5. Gemini offline: exact status shows unavailable, no fabricated answer; after verified runtime, Gemini can participate without duplicating the same task claim.
6. Boundedness: max turns / rate limits / owner stop; no agent-to-agent ping-pong forever, no unsolicited generation or API billing.
7. Owner confirmation creates a versioned decision, updates shared policy only via reviewable PR or explicitly approved write path, and each lane reports SHA acknowledgment before claiming next task.
8. Crash/restart / stale / conflict / secret-redaction / permission tests; CI passes; deployed SHA verified; real owner Telegram round-trip evidence logged without storing private group content in public issue/PR.

### Suggested delivery order (zero extra spend)

1. **P0:** Claude reviews this doc (#115) and builds durable per-thread read/write and per-lane MCP auth in #94.
2. **P0:** Claude adds Telegram private-group binding and `/discuss`, `/stop`, `/decision` projection on top of Relay, preserving existing paired DM and Telegram commands. First demo with owner + real Claude only is acceptable as *partial* success.
3. **P0:** Prove ChatGPT authenticated read/post path with a genuinely available tool and one live short round-trip. If impossible, mark `integration_blocked` and show what integration is missing; do not use a paid OpenAI API without approval or fabricate a ChatGPT voice.
4. **P1:** Include Gemini only when worker actually connected; verify owner-controlled three-participant discussion.
5. Owner audition: naming-policy test discussion, 2 bounded rounds, explicit /decision, all traces in Relay and on Telegram. Do not mark "three agents in one working chat" until this test passes.

**References:** #94, #115, `ROADMAP.md`, `app.py`, `relay_execution.py`, `AGENTS.md`, `CLAUDE.md`, `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`, Telegram official https://core.telegram.org/bots/features (group privacy and bot communication).
