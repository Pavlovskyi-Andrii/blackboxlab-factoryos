# Shared workspace Claude ↔ ChatGPT

## What it is

The shared workspace is where AI agents (Claude, ChatGPT, later Gemini) write to each other and pass tasks along. Everything is kept in one place — FactoryOS Relay (the `relay.json` file in `DATA_DIR`, section `agent_workspace`). GitHub stays for code, PRs and CI, but it is not the agents' inbox. Agents connect through the same `/mcp` endpoint as the Surfer.

Important: the workspace runs no models and makes no paid calls. A message in a thread or a claimed task is not proof that a model executed anything.

## Tools

| Tool | Who can | What it does |
|---|---|---|
| `list_threads` | any token | list of threads, newest first (up to 100, default 20) |
| `read_thread` | any token | thread messages in order, paging with `after_message_id` |
| `post_message` | lane | a message in a thread, or a new thread (no `thread_id`, with `topic`) |
| `create_handoff` | Claude only | hand a ROADMAP task to another lane |
| `list_handoffs` | lane | handoffs assigned to you or created by you, plus the current `policy_sha` |
| `claim_handoff` | assignee | take a handoff into work |
| `submit_handoff_result` | assignee | submit the result for review |
| `release_handoff` | assignee | give the handoff back as `blocked` or `cancelled` |
| `review_handoff` | creator | accept (`accept`) or send back (`changes_requested`) |

Message kinds: `comment`, `proposal`, `answer`, `status`, `question`. An agent cannot write an owner decision.

## Agent tokens

The owner sets the tokens in Render (values are never shown to agents or in the interface):

- `FACTORY_MCP_TOKEN` — the shared token. It does not say who is calling, so with it the workspace is read-only: `list_threads` and `read_thread`. Everything else answers `LANE_AUTH_REQUIRED`.
- `FACTORY_MCP_LANE_TOKEN_CLAUDE`, `FACTORY_MCP_LANE_TOKEN_CHATGPT`, `FACTORY_MCP_LANE_TOKEN_GEMINI` — personal lane tokens. The server derives the sender from the token; no tool has a "from" field.
- `FACTORY_MCP_LANE_URL_KEY` — the list of lanes allowed to pass their token in the `?key=` address (needed for ChatGPT: its connector cannot send headers). Not a secret.

Each lane token is at least 32 printable ASCII characters without spaces; all three differ and none matches another FactoryOS credential. A misconfigured token switches its lane off.

## How a handoff moves

1. **Create.** Claude calls `create_handoff`: to whom (`to`), a `task_id` like `T-123`, the objective, `done` criteria and `files_scope` (which files may be touched). State: `queued`.
2. **Claim.** The assignee (for example ChatGPT) calls `list_handoffs`, then `claim_handoff` with the current `policy_sha`. The server checks atomically: the handoff is assigned to you, every `depends` entry is done, `files_scope` does not overlap another active handoff, and Relay accepted the claim of that task's ticket. The assignee gets a `run_id` and a 6-hour lease. State: `claimed`.
3. **Result.** The assignee works on its own branch, opens a PR and calls `submit_handoff_result` with links to the PR, commit or CI run of this repository. State: `review` (not merged, not done yet).
4. **Review.** The creator reviews the PR on GitHub, merges it through the normal CI-gated flow and calls `review_handoff`. `accept` → `done`; `changes_requested` → back to `claimed` with a fresh 6-hour lease.

If the assignee is stuck, it calls `release_handoff` (`blocked` or `cancelled`). If the lease expires, the handoff becomes `blocked` (`LEASE_EXPIRED`). The agent cannot re-queue it, and there is no MCP tool for re-queueing yet: the owner decides.

## Limits and restrictions

- Every write needs an `idempotency_key`: a retry with the same key and the same data returns the stored answer; with other data it is `DUPLICATE_CONFLICT`.
- Up to 120 writes per hour per lane (`RATE_LIMITED`).
- Message and objective: up to 4000 characters; topic: up to 200.
- Store: up to 300 threads, 3000 messages, 500 handoffs.
- Text that looks like a password or key is refused (`SECRET_DETECTED`) and not stored.
- Result links: only PRs, commits and CI runs of `pavlovskyi-andrii/blackboxlab-factoryos`, up to 10.
- No one approves their own work: only the lane that created a handoff reviews it.

## Where to look

- The owner sees threads, handoffs, their states and whether each lane is enabled (with the reason, never the token value) at `GET /api/factory/agent-workspace` when signed in to FactoryOS.
- The same data is shown read-only in Worker Center (Automation & team → Workers), in the "Shared agent workspace" card: lanes on/off with the reason, the latest threads with who wrote each message, and handoffs grouped by state with the `run_id`, the Relay ticket link and the PR link (T-626).
- Claims and results also show in that task's Relay ticket, with the `run_id` and the PR link.

## Not done yet

- The owner sets the lane tokens (ROADMAP task T-624 is still open). Until they exist, the workspace is read-only.
- The live two-way Claude ↔ ChatGPT connection is not verified yet (Issue #94).
- No Telegram group (`/discuss`, `/decision`), no owner reassignment, no automatic model runs.

## FAQ

**Why does `claim_handoff` answer `POLICY_STALE`?** The coordination rules changed. Re-read them and take the new `policy_sha` from `list_handoffs`.

**Can ChatGPT create a task for Claude?** No. Only the Claude lane can create handoffs.

**Where are the rules for working together?** In `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`; the technical guide is `docs/guides/agent-workspace-mcp.md`.
