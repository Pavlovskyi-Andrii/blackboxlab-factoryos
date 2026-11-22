# Surfer: web search and page reading for AI agents

## What it is

The Surfer is the FactoryOS browser agent that connected AI agents (ChatGPT, Claude, Gemini) can use. It can search the web and read public pages. Pages are opened by a real Chromium in anonymous mode on the EC2 worker; no browser runs on the Render server. The Surfer only reads: it does not sign in, fill in forms or buy anything.

## Three tools

| Tool | What it does |
|---|---|
| `web_search` | Search through an official API. Returns up to 10 results: title, address, short snippet. |
| `web_read` | Queues a "read this page" task and waits for the answer. Returns the text of the page or of chosen CSS selectors, and whether a screenshot was taken. |
| `web_task` | Shows the status and result of a `web_read` task that did not finish within the wait time. |

## How to use it

1. The agent calls `web_search` with a `query` field and gets a list of links.
2. The agent opens the link it needs with `web_read` and a `url` field (`https://` only). Up to 5 CSS selectors can go in `selectors`; without them the whole page (`body`) is read.
3. `web_read` waits up to `wait_seconds` (default 40, maximum 50 seconds). If the page is not ready, the agent gets a `task_id` with status `queued` or `running`.
4. A few seconds later the agent calls `web_task` with that `task_id` and picks up the result.

By default search goes through Wikipedia (official API, free, no key; the language is set with `lang`, default `en`). Google search through Gemini is turned on only when the owner sets `FACTORY_WEB_SEARCH_PROVIDER=gemini` in Render: it can be billed beyond the free quota.

## Who can use it

- Any MCP client with the shared `FACTORY_MCP_TOKEN` on the `/mcp` endpoint (header `Authorization: Bearer …` or, for connectors that cannot send headers, `?key=`).
- An agent with its own lane token (`FACTORY_MCP_LANE_TOKEN_CLAUDE`, `_CHATGPT`, `_GEMINI`) — such a token also opens all of `/mcp`.
- FactoryOS's own agents on EC2 (the Gemini coder) — through `POST /api/factory/surfer/worker/{web_search|web_read|web_task}` with the worker token they already have.

The `agent` field (chatgpt, claude, gemini…) is only a label for the history, not a verified identity: the shared token is the same for everyone.

## Limits and restrictions

- Search query: 1 to 300 characters; `limit` 1 to 10 (default 5).
- Search through Gemini: at most 100 per day (UTC). After the cap, `auto` mode quietly falls back to Wikipedia, while an explicit `provider: gemini` gets error 429.
- Provider request timeouts: Wikipedia 20 seconds, Gemini 45 seconds. The Gemini answer is cut to 4000 characters.
- `web_read`: up to 5 selectors, up to 6000 characters of text per selector, screenshot up to 2 MB. The worker waits up to 8 seconds for each selector, then marks it `missing`.
- Queue: at most 20 active tasks (queued and running) for everyone together. Tasks through MCP: at most 200 per 24 hours (one shared counter for all MCP clients); the EC2 worker has its own counter of 200.
- Addresses: `https://` only, no login or password inside the address, up to 2000 characters. `localhost`, `.local`, `.internal`, `.localhost` domains and internal IPs are refused. On the worker every browser connection goes through a proxy that lets only public addresses through.
- `web_task` only sees tasks of its own source: MCP tasks cannot be read with the worker token, and the other way round.

## What the Surfer does not do

- It does not sign in, submit forms, publish or buy: form submission is fully disabled in the executor.
- It does not read search engine result pages: they block the datacenter address as automated traffic, and bypassing blocks is not a goal of the project.
- It does not solve CAPTCHA or 2FA: such a task gets status `waiting_human`, and the owner has to look at it.
- If the EC2 worker is off, `web_read` simply returns `queued`.

## Where to look

- The owner sees tasks on the dashboard in the "Browser agent" card (menu item "Browser agent"): the latest 10 tasks with status, text read and screenshot. Tasks queued by agents through MCP show up there too.
- The daily count of Gemini searches is kept in `web_search_usage.json` in `DATA_DIR`.
- Detailed technical connection guide: `docs/guides/surfer-mcp.md`.

## FAQ

**Why did search return Wikipedia, not Google?** Gemini search is off (no owner setting), the daily cap is used up, or Gemini answered with an error. The reason comes in the `note` field.

**A task is stuck in `queued`. Is it broken?** Most likely the EC2 worker is not running right now or the queue is busy. Check later with `web_task`.

**Can the Surfer sign in to my account?** Not through MCP. The Surfer for agents only reads public pages.
