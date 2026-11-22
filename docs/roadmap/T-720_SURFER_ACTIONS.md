# T-720 … T-724 — Surfer actions: the browser agent that acts in the owner's accounts

Owner brief 2026-11-22 (quiz answers). Until now the Surfer only reads (`web_search`, `web_read`, `web_task`).
The owner wants a tool that acts on sites instead of him and instead of Claude/ChatGPT: clicks, fills forms,
uploads files, in accounts he is already signed in to.

Uses: (1) forms and clicks in his own cabinets, (2) collecting data from sites into a Google Sheet (T-725, another
session), (3) testing his own MVPs as a user, (4) content upload/publishing where no official API exists.

## Owner decisions (the spec)

| Topic | Decision |
|---|---|
| Accounts | Only accounts the owner already has and is signed in to. No account creation, no rented numbers or SMS services, no captcha solving, no anti-bot or fingerprint evasion, no proxy tricks. A site that refuses the server (OLX answers 403 to EC2) is reported as it is and the task stops. |
| Phone / SMS / captcha / 2FA | Only the owner's own number. The session goes to `waiting_human` with a screenshot; the owner types the code or takes over, then it continues. |
| Control | "By itself, on allowed sites": the owner keeps an allowlist of sites and action classes; inside it the Surfer acts without asking. Payment/purchase, deleting, password/security settings, messages to other people, publishing, and anything outside the allowlist always need the owner's confirmation of that exact step (screenshot + what will happen). Nothing is on by default. |
| Login | Combined: saved vault login first (password from the encrypted vault, never shown to agents); if it fails or a code is asked, the owner takes over on the page; only the session (cookies/storage state) is kept, encrypted. |
| Brain | The calling agent (Claude/ChatGPT through MCP, on the owner's subscriptions) drives step by step from page snapshots. No paid API calls from the server. A successful run can be saved as a recipe and replayed without AI. |
| Where the owner works | Claude/ChatGPT (MCP), a FactoryOS page, and human requests exposed so a parent Claude session can mirror them on the owner's task page. |

## Architecture

```
agent (MCP /mcp or REST /api/factory/surfer/agent/*, per-lane token)
   │ web_open / web_act / web_snapshot / web_close
   ▼
surfer_actions.py on Render ── gate (T-721: flag, allowlist, classifier, caps, lane) ── audit log
   │ one command at a time, kept in DATA_DIR/surfer_actions/
   ▼  the worker polls (Render cannot reach EC2)
POST /api/factory/browser/worker/actions/claim  →  autopilot/browser_actions.py (Surfer worker, EC2)
POST /api/factory/browser/worker/actions/{id}/result  ←  browser_runner/action_session.py (one live Chromium page)
```

- A **session** is one live page on the worker, kept across steps. One session at a time. Idle timeout 5 min,
  15 min while it waits for the owner, hard lifetime 30 min, 200 steps.
- The worker executes one command, takes a screenshot and a new snapshot, and reports. The MCP call waits up to
  ~45 s for that report; a slower step returns `running` and the agent calls `web_snapshot`.
- Read tasks (`web_read`) keep running while a session is live: they borrow the same Chromium with a fresh
  anonymous context.
- Playwright never runs on Render. Worker code is Python 3.9 compatible.

## Tools (MCP + the same over REST)

| Tool | Input | Output |
|---|---|---|
| `web_open` | `{url, session?: 'site/account', session_id?}` | opens a live session (or navigates an existing one) → snapshot |
| `web_act` | `{session_id, action, ref \| selector, value?, value_from?, asset_id?, key?}` | runs one step → snapshot |
| `web_snapshot` | `{session_id, step_id?, offset?, max_chars?, max_elements?, filter?}` | current page: title, url, a chunk of the main text, interactive elements |
| `web_close` | `{session_id}` | closes the session |

Actions: `click`, `fill`, `select`, `check`, `press`, `upload`, `scroll`, `wait_for`, `back`.

A snapshot element: `{ref, kind, name, type?, value?, checked?, options?, href?, disabled?, required?, secret?, submit?}`.
`ref` (`e12`) is stamped on the element (`data-fos-ref`) and stays the same while the document lives. Before acting the
worker describes the element again and compares it with what the agent saw; a different element is `stale_ref`.

Limits of v1: main frame only (no iframes, no shadow DOM), a new tab is closed and reported, downloads are off.

## Secrets

- A snapshot never carries the value of a password/secret field (`type=password`, secret autocomplete values, names
  like `otp`, `cvv`, `token`), cookies or storage.
- An agent cannot type into a secret field. It passes `value_from: 'vault:site/account#password'` (or `#username`);
  the server reads the value from the encrypted vault only when the worker claims the command and hands it to the
  worker in that one response; it is not written to the command record, the audit log or any result.
  `#password` goes only into a `type=password` field, `#username` only into a visible text field, and only on a
  domain whose allowlist entry names that login.
- The worker remembers the secrets it typed in the session and replaces them in every snapshot (a "show password"
  toggle does not leak them). Fields the owner typed into during a takeover are treated as secret fields.
- Screenshots are for the owner only.
- Audit: who (lane or owner), URL (no query), action, element label, result, screenshot id; values typed into
  secret fields, vault values and everything the owner types are stored as `***`.

## Policy gate (T-721)

Fail closed, on the server, and checked again on the worker with the same pure module
(`browser_runner/action_policy.py`).

1. `FACTORY_SURFER_ACTIONS_ENABLED` (owner-set in Render; off by default) and the owner's pause switch.
2. Lane identity from the per-lane MCP token (T-624). The shared MCP token may read, it may not act.
3. Allowlist: domain pattern (`olx.ua` covers its subdomains) + action classes `read`, `navigate`, `fill`,
   `submit`, `upload` + optional vault login. `web_open` on a site outside the allowlist is refused.
4. Inside a session, a step waits for the owner (`needs_owner_confirmation`, with a preview) when it is
   - payment / purchase, delete, security settings, a message to other people, publishing;
   - a class the owner did not switch on for this site;
   - a navigation that leaves the allowlist, or a write on a page outside it;
   - a control without a readable label.
5. Login wall, captcha, anti-bot page, SMS/2FA code → `waiting_human`. Nothing is solved or bypassed.
6. Caps per UTC day: sessions and steps.

The classifier reads labels in English, Russian and Ukrainian. It is a heuristic: a false alarm costs one
confirmation; a site the owner allows with `submit` is a site he trusts the agents to submit forms on.

## Owner page (T-722) `static/surfer/index.html` (RU/UK/EN)

Live session with its steps and screenshots; Confirm / Reject / Stop; a box for the SMS code or text the page asks
for; Take over (screenshot + click coordinates + typed text, enough to finish a login); allowlist editor; pause
switch; approved upload files; audit history. `GET /api/factory/surfer/owner/pending` lists what waits for the owner,
so another agent session can mirror it.

## Recipes (T-723)

After a session the owner can save its successful steps as a recipe with parameters. A replay runs the steps
without AI under the same gate, stops at the first mismatch and hands the live session to an agent or the owner.

## Self-test (T-724)

A local fixture site (login form, multi-step form, file upload, delete button, payment button, captcha-like wall)
proves: an allowlisted fill + submit runs, sensitive steps wait, off-allowlist is refused, secrets never reach
snapshots or logs, a takeover continues the session, a recipe replays. CI uses a page double; the same scenario runs
against real Chromium with `RUN_BROWSER_FIXTURE=1`.

## Non-goals

Creating accounts, solving or bypassing captcha / anti-bot checks, SMS services, residential proxies, fingerprint
changes, paid browser or LLM APIs on the server, acting without a lane identity.
