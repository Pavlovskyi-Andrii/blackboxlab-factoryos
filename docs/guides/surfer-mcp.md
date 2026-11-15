# Surfer — web search and page reading for every connected agent (T-560-H)

FactoryOS exposes its browser agent through the MCP endpoint `https://blackboxlab-factoryos.onrender.com/mcp`
(token: `FACTORY_MCP_TOKEN`, as `Authorization: Bearer …`). Any MCP client — ChatGPT connector, Claude connector,
Gemini CLI — gets three tools:

| Tool | What it does |
|---|---|
| `web_search` | `{query, limit?, provider?: auto/gemini/wikipedia, lang?, agent?}` → `{provider, results: [{title, url, snippet}], answer?}` |
| `web_read` | `{url, selectors?, wait_for?, wait_seconds?, agent?}` → the text the real Chromium read (every match per selector; a missing selector is `missing: true`) |
| `web_task` | `{task_id}` → status/result of a `web_read` that took longer than `wait_seconds` |

Limits: public `https://` pages only, read-only (no logins, forms, purchases), ≤ 5 selectors, 6000 chars per selector,
20 active tasks, 200 MCP tasks per day. Pages run on the EC2 worker (`docs/guides/browser-agent.md`); if it is down,
`web_read` returns `queued`.

Search: Wikipedia by default (free, no key). Google search through Gemini works after the owner sets
`FACTORY_WEB_SEARCH_PROVIDER=gemini` in Render (may be billed beyond the free quota; capped at 100/day).
Search engine result pages cannot be read through `web_read`: they block the worker as automated traffic.

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
