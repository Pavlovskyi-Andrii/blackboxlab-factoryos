# Surfer — web search and page reading for every connected agent (T-560-H)

FactoryOS exposes its browser agent through the MCP endpoint `https://blackboxlab-factoryos.onrender.com/mcp`
(token: `FACTORY_MCP_TOKEN`, as `Authorization: Bearer …`). Any MCP client — ChatGPT connector, Claude connector,
Gemini CLI — gets three tools:

| Tool | What it does |
|---|---|
| `web_search` | `{query, limit?, provider?: auto/gemini/wikipedia, lang?, agent?}` → `{provider, results: [{title, url, snippet}], answer?, note?}` |
| `web_read` | `{url, selectors?, wait_for?, wait_seconds?, max_chars?, agent?}` → the page as a real Chromium saw it (see below) |
| `web_task` | `{task_id, offset?, max_chars?, links?}` → status/result of a `web_read`, and the next chunks of its text |

### How an AI should use it (T-671)

1. **Start without selectors.** `web_read {"url": "https://docs.python.org/3/library/pathlib.html"}` returns the page's
   **main text** (menus, sidebars, cookie banners and the site header/footer removed), `title`, `description`,
   `http_status` and `links` (up to 40 of the page's https links; `web_task … links: 150` for all).
2. **Long pages come in chunks.** `text` is 8000 chars by default (`max_chars` up to 20000). When `next_offset` is a
   number, call `web_task {"task_id": "bt_…", "offset": <next_offset>}`; it is `null` on the last chunk. Up to
   100 000 chars per page are kept.
3. **Selectors for precise parts.** `web_read {"url": "https://pypi.org/project/requests/", "selectors": ["h1"]}`
   returns `texts: [{selector, text, chars, truncated?, missing?}]` (every match, ≤ 6000 chars each in `texts`; a
   longer selector text is read in chunks with `web_task … offset`). An id with dots works as written (`#os.path.join`
   also matches the literal id, T-674; `[id="os.path.join"]` works too); a Sphinx/Python-docs `<dt>` is read with its
   `<dd>` description.
4. **JavaScript pages.** The worker waits up to 5 s for the network to go quiet. If the text is still nearly empty, the
   answer says so in `hints`; retry with `wait_for` (e.g. `"article h1"`).
5. **Read `hints`.** Every answer that needs action says what to do: domain does not exist, HTTP 404, selector missing,
   anti-bot page (`waiting_human` / `bot_challenge` — use another source: an API, `raw.githubusercontent.com`, a mirror),
   timeout, redirect to another site (`web_read` follows one JavaScript redirect itself; `redirect_to` shows where).
6. **Queue.** Tasks run one at a time on the EC2 worker (each 2–20 s). If the result is not ready within
   `wait_seconds` (default 40), you get `queued`/`running`, `queue_ahead` and a `task_id`; poll `web_task` every 5–10 s.

Status values: `done`, `queued`, `running`, `blocked` (refused by a rule or the site moved away), `failed` (network/
timeout; see `blocker` and `hints`), `waiting_human` (CAPTCHA/2FA/anti-bot page — never bypassed).

Limits: public `https://` pages only, read-only (GET only; no forms, posting, purchases; signing in only with a saved login the owner allowed, below), ≤ 5 selectors, 20 active
tasks (beyond that: HTTP 429, retry in a minute), 200 MCP tasks per day. Pages run on the EC2 worker
(`docs/guides/browser-agent.md`); if it is down, `web_read` returns `queued`.

The same view is on the agent REST: `GET /api/factory/browser/agent/tasks/<id>?offset=8000&max_chars=8000&links=40`
returns `{task, view}`.

Search: Wikipedia by default (free, no key). Google search through Gemini works after the owner sets
`FACTORY_WEB_SEARCH_PROVIDER=gemini` in Render (may be billed beyond the free quota; capped at 100/day).
Search engine result pages cannot be read through `web_read`: they block the worker as automated traffic.

Benchmark of 31 real tasks, what works and what does not: `docs/verification/surfer-benchmark-2026-11-16.md`.

## Connecting

- **Gemini CLI** (`~/.gemini/settings.json`):
  `{"mcpServers": {"factoryos": {"httpUrl": "https://blackboxlab-factoryos.onrender.com/mcp", "headers": {"Authorization": "Bearer <FACTORY_MCP_TOKEN>"}}}}`
- **Claude Code**: `claude mcp add --transport http factoryos https://blackboxlab-factoryos.onrender.com/mcp --header "Authorization: Bearer <FACTORY_MCP_TOKEN>"`
- **ChatGPT / claude.ai custom connector**: connector URL `https://blackboxlab-factoryos.onrender.com/mcp?key=<FACTORY_MCP_TOKEN>`
  (legacy query-key fallback; the connector UI does not send custom headers).

Never paste the token into chat, Git or issues.

Quick check:
```bash
curl -s https://blackboxlab-factoryos.onrender.com/mcp -H "Authorization: Bearer $FACTORY_MCP_TOKEN" \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"web_search","arguments":{"query":"Playwright"}}}'
```

## FactoryOS's own agents (EC2)

The Gemini coder loop on EC2 uses the same tools without MCP: `POST /api/factory/surfer/worker/{web_search|web_read|web_task}`
with the worker token it already has (`/etc/factoryos/claude-worker.env`). Before writing code it may run up to 3 searches
and read up to 2 pages; the log shows `Surfer research: N searches, M pages`. Set `GEMINI_RESEARCH=0` to turn it off.

## Signed-in reads with a saved login (T-560-L)

`web_read` takes an optional `"session": "site/account"` (for example `"github/main"`). The page then opens signed in
with a browser session the owner saved in **Connections → Access vault** — still read-only, GET only.

- The owner must switch **"🤖 Agents: on"** for that session in the vault. It is off by default and goes off again
  whenever a new session file is uploaded.
- The page must be on one of the session's cookie domains; cookies never go to another site. A redirect to another
  site is followed anonymously.
- A refused value returns the list of allowed logins (`site/account (domains)`), never cookies.
- The agent's answer and the task record carry no cookies; the EC2 worker gets the decrypted state only in the claim
  response and drops it after the task.
- OLX and LinkedIn are not done this way: they block the EC2 worker and forbid automation (official APIs: T-700, T-701).

Example: `{"url": "https://github.com/notifications", "session": "github/main"}`.

## Shared agent workspace

The same `/mcp` endpoint also carries the Claude ↔ ChatGPT ↔ Gemini workspace (threads and handoffs on Relay).
Writing there needs a per-lane token instead of `FACTORY_MCP_TOKEN`: see `docs/guides/agent-workspace-mcp.md`.

## Acting on a site: `web_open`, `web_act`, `web_snapshot`, `web_close` (T-720, T-721)

Reading is open to every connected agent. **Acting** (clicks, forms, uploads in the owner's signed-in accounts) is a
separate, gated surface. Full spec: `docs/roadmap/T-720_SURFER_ACTIONS.md`.

- It is **off** until the owner sets `FACTORY_SURFER_ACTIONS_ENABLED=1` in Render, and works only on the sites and
  action classes he enabled on the Surfer page (`/static/surfer/index.html`). Nothing is on by default.
- It needs your **own lane token** (`FACTORY_MCP_LANE_TOKEN_CLAUDE` / `_CHATGPT` / `_GEMINI`); the shared MCP token
  may read but not act. The same tools are available over REST: `POST /api/factory/surfer/agent/{tool}`.
- One live session at a time: idle 5 min, 30 min at most. Close it with `web_close`.

| Tool | Input | Output |
|---|---|---|
| `web_open` | `{url, session?, session_id?}` | opens a live page (or navigates an existing session) → snapshot |
| `web_act` | `{session_id, action, ref \| selector, value?, value_from?, key?, asset_id?}` | one step → new snapshot |
| `web_snapshot` | `{session_id, step_id?, offset?, max_chars?, max_elements?, filter?, refresh?}` | the page and the state of a step |
| `web_close` | `{session_id}` | closes the page |

How to drive it:

1. `web_open {"url": "https://…"}` → `elements: [{ref: "e4", kind: "input", name: "City"}, …]` and a chunk of text.
2. `web_act {"session_id": "ws_…", "action": "fill", "ref": "e4", "value": "Kyiv"}`; then `click` the button's ref.
   Actions: `click`, `fill`, `select`, `check`, `press`, `upload`, `scroll`, `wait_for`, `back`.
3. Login fields: `"value_from": "vault:site/account#username"` and `"#password"`. You never see the value, and a
   secret field accepts nothing else. A snapshot never contains secret-field values, cookies or screenshots.
4. Read `status` on every answer:
   - `done` — continue with the new refs (refs change when the page changes; an old one is `stale_ref`).
   - `running` — call `web_snapshot {session_id, step_id}` in a few seconds.
   - `needs_owner_confirmation` — payment, delete, security settings, a message to someone, publishing, or a step
     outside what the owner enabled. Tell the owner what you are about to do; he confirms or rejects it on the
     Surfer page; poll `web_snapshot` with the `step_id`. Do not retry the step.
   - `waiting_human` — a login the vault could not finish, a captcha, or a code sent to the owner. FactoryOS never
     solves or bypasses these: the owner takes over on the Surfer page.
   - `refused` / `blocked` / `failed` — see `blocker` and `hints`.
5. Daily caps apply (40 sessions, 600 steps by default); the answer is HTTP 429 until 00:00 UTC.
