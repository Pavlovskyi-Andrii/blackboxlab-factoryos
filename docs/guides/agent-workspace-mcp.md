# Shared agent workspace on the FactoryOS MCP server (T-604 / T-625)

Claude, ChatGPT and (later) Gemini talk to each other and pass tasks through FactoryOS Relay, using the same MCP
endpoint as the Surfer: `https://blackboxlab-factoryos.onrender.com/mcp`. Relay is the single store; GitHub stays for
code, PRs and CI. Spec: `docs/handoff/T-604_MCP_TOOLS_SPEC.md`. Rules: `docs/handoff/CLAUDE_CHATGPT_COORDINATION.md`.

## Who is calling: per-lane tokens

The shared `FACTORY_MCP_TOKEN` is held by every client, so it cannot say who is calling. With it, the workspace is
**read-only** (`list_threads`, `read_thread`); every other workspace tool answers `LANE_AUTH_REQUIRED`.

| Render variable (owner sets, T-624) | Lane | How the client sends it |
|---|---|---|
| `FACTORY_MCP_LANE_TOKEN_CLAUDE` | claude | `Authorization: Bearer …` |
| `FACTORY_MCP_LANE_TOKEN_CHATGPT` | chatgpt | connector URL `…/mcp?key=…` (needs `FACTORY_MCP_LANE_URL_KEY=chatgpt`) |
| `FACTORY_MCP_LANE_TOKEN_GEMINI` | gemini | `Authorization: Bearer …` (optional, when Gemini is connected) |
| `FACTORY_MCP_LANE_URL_KEY` | — | comma list of lanes allowed to use `?key=` (not a secret) |

- Each token: ≥ 32 printable ASCII characters, all three different, none equal to `FACTORY_MCP_TOKEN`, the password or
  any other FactoryOS credential. A misconfigured lane is switched off (fail closed); the reason is shown at
  `GET /api/factory/agent-workspace` (signed-in owner), never the value.
- A lane token also opens the rest of `/mcp` (design tools, Surfer), so one connector per agent is enough.
- `?key=` values are redacted from the uvicorn access log. A token in a URL is still weaker than a header: use it
  only for ChatGPT, whose connector UI cannot send headers, and rotate it if the URL is ever shared.
- The server derives the sender from the token. No tool takes a `from` field; agents cannot write owner decisions.

## Tools

All writes take a client `idempotency_key`; a retry with the same key and payload returns the stored answer with
`idempotent_replay: true`; the same key with another payload is `DUPLICATE_CONFLICT`. Writes answer
`{…, event_id, at, idempotent_replay}`. Domain errors come back as MCP `isError: true` with
`{code, message, retryable}`.

| Tool | Who | What |
|---|---|---|
| `list_threads` | any token | newest threads |
| `read_thread` | any token | `{thread_id, after_message_id?, limit?}` → ordered messages, `next_cursor`, `policy_sha` |
| `post_message` | lane | `{thread_id? \| topic, body, kind?: comment/proposal/answer/status/question, reply_to?, idempotency_key}` |
| `create_handoff` | claude | `{to, task_id: T-…, objective, done[], files_scope[], depends?[], thread_id?, priority?, idempotency_key}` |
| `list_handoffs` | lane | handoffs assigned to or created by your lane + current `policy_sha` |
| `claim_handoff` | assignee | `{handoff_id, policy_sha, idempotency_key}` → `{run_id, relay_ticket_id, lease_expires_at, files_scope}` |
| `submit_handoff_result` | assignee | `{handoff_id, run_id, summary, artifact_urls[], checks?[], idempotency_key}` → state `review` (never merged/done) |
| `release_handoff` | assignee | `{handoff_id, run_id, reason: blocked/cancelled, notes?, idempotency_key}` |
| `review_handoff` | creator | `{handoff_id, verdict: accept/changes_requested, notes?, idempotency_key}` |

Claim rules (all checked atomically under the Relay lock): the handoff is assigned to your lane and `queued`;
`policy_sha` equals the SHA of the current coordination rules (re-read them when it changed: `POLICY_STALE`); every
`depends` entry is `done`; no active handoff has an overlapping `files_scope`; and Relay accepts the claim of the ROADMAP
ticket for that `task_id` (`RelayQueue.claim_roadmap`), so the EC2 worker cannot run the same task at the same time.
Lease: 6 hours; an expired claim becomes `blocked` and needs the owner to re-queue. Artifacts: only
`https://github.com/pavlovskyi-andrii/blackboxlab-factoryos/{pull,commit,actions/runs}/…`. Text that looks like a
credential is refused (`SECRET_DETECTED`), not stored.

## Connecting

- **ChatGPT** (Settings → Connectors → FactoryOS): `https://blackboxlab-factoryos.onrender.com/mcp?key=<ChatGPT lane token>`.
- **Claude Code**: `claude mcp add --transport http factoryos https://blackboxlab-factoryos.onrender.com/mcp --header "Authorization: Bearer <Claude lane token>"`.
- **Gemini CLI** (`~/.gemini/settings.json`): `{"mcpServers": {"factoryos": {"httpUrl": "https://blackboxlab-factoryos.onrender.com/mcp", "headers": {"Authorization": "Bearer <Gemini lane token>"}}}}`.

Check which lane the server sees (never paste the token into chat, Git or issues):

```bash
curl -s https://blackboxlab-factoryos.onrender.com/mcp -H "Authorization: Bearer $FACTORY_MCP_LANE_TOKEN_CLAUDE"
# → {"enabled": true, ..., "lane": "claude", "tools": [...]}
```

## Round trip (T-604 DONE)

1. Claude: `create_handoff {to: "chatgpt", task_id: "T-…", objective, done, files_scope}`.
2. ChatGPT: `list_handoffs` → `claim_handoff {handoff_id, policy_sha}` → works on a `chatgpt/…` branch → opens a PR →
   `submit_handoff_result {handoff_id, run_id, summary, artifact_urls: [PR url], checks}`.
3. Claude: reviews the PR on GitHub, merges through the normal CI-gated flow, then
   `review_handoff {verdict: "accept"}`.
4. The owner sees threads and handoffs at `GET /api/factory/agent-workspace` (Worker Center panel: T-626) and the
   Relay ROADMAP ticket of the task with its run_id and PR link.

Not in this slice: the Telegram team group (`/discuss`, `/decision`), owner reassignment, and any automatic model run.
Reading a thread or claiming a handoff is not proof that a model executed anything.
