# Surfer benchmark — 2026-11-16 (T-670)

Owner request: «Браузерный агент (Сёрфер) — доведи работу до идеала, чтобы любой ИИ мог им пользоваться в середине
проекта. Дай ему задания и проверь, как он справляется.»

**Method.** 33 real read tasks were queued on production (`https://blackboxlab-factoryos.onrender.com`, v5.10.0)
through the agent REST `POST /api/factory/browser/agent/tasks` and polled with `GET …/agent/tasks/<id>`, between
21:07 and 21:45 UTC. They ran on the EC2 Chromium worker behind the egress proxy. The tasks are what an AI usually
needs in the middle of a project: docs pages, a README, release notes, a changelog, a PyPI page, Wikipedia, SPAs,
redirects, a very long page, cookie banners and anti-bot pages, a missing selector, a 404, a slow page, a table, and a
domain that does not exist. Each result was judged by what an AI could do with it, not only by `status`.
Re-run: `python tools/surfer_benchmark.py` (same tasks, prints a table).

## Numbers (before the fix, production)

- 33 tasks queued → 31 finished, **2 refused with HTTP 429**. 23 tasks were sent in one burst and the queue holds at
  most 20 active tasks.
- Status: 28 `done`, 2 `waiting_human`, 1 `blocked`. `done` overstated success: in **17 of the 28** the AI did not get
  what it asked for. Main causes: menus instead of content, content cut off, an anti-bot page, a 404 page.
- Run time on the worker: median **5 s**, mean 6.6 s, max 19 s. A missing selector costs 8 s of waiting.
- Wait in the queue: median 50 s, max 172 s. The worker runs one task at a time, so a burst of 23 tasks queues up.
  A single task waits 3–18 s.
- **Fully useful answers: 12 of 31** (WORKS below). Partly useful: 15. Wrong or misleading: 4 (FastAPI false captcha, StackOverflow twice, npm).

## Results (before)

| Stage | Status | Evidence | Problem |
|---|---|---|---|
| Python docs `pathlib`, no selectors | PARTIAL | done in 4 s; `body` 6000 chars | first ~1000 chars are the language and version menus, the text stops after 6000 chars, no way to read on |
| Python docs, selector `#pathlib.Path.glob` | PARTIAL | done; `missing: true` | an id with dots needs `[id="pathlib.Path.glob"]` (66 chars, WORKS); nothing told the AI that |
| Python docs, `[id="pathlib.Path.glob"]` | WORKS | done in 3 s, 66 chars, the exact signature | — |
| MDN Using Fetch, `main h1` + `main article` | PARTIAL | h1 19 chars; `main article` missing | MDN has no `<article>` in `main`; no hint |
| MDN, `main h1` + `main` | PARTIAL | `main` 6000 chars | cut at 6000 chars, no paging |
| playwright.dev locators (Docusaurus), no selectors | PARTIAL | `body` 6000 chars | starts with "Skip to main content / Docs / API / …" navigation; content cut |
| FastAPI docs, `article` | BROKEN | `waiting_human` / `captcha` while `article` returned 6000 chars | false positive: the page has a reCAPTCHA iframe (probe: `iframe[src*="recaptcha"]` matched); the content was readable |
| docs.github.com REST pulls, no selectors | PARTIAL | `body` 6000 chars | site header, plan picker, sidebar first; content cut |
| docs.github.com, `main h1` + `#article-contents` | PARTIAL | h1 36 chars; `#article-contents` missing | guessed selector; no hint how to find the right one |
| GitHub README, `article.markdown-body` | WORKS | done in 7 s, 1415 chars, whole README | — |
| GitHub releases, `section h2` | PARTIAL | 842 chars | versions present, mixed with "Sorry, something went wrong" from lazy widgets |
| pip changelog, no selectors | PARTIAL | `body` 6000 chars | navigation first, the changelog cut |
| PyPI requests, `h1.package-header__name` + summary class | PARTIAL | both `missing` | PyPI changed its class names; no hint |
| PyPI requests, `h1` + `p.package-description__summary` | PARTIAL | h1 "requests 2.34.2" OK; summary missing | as above |
| Wikipedia article, `#firstHeading` + `#mw-content-text p` | WORKS | done in 3 s; 21 + 4409 chars | — |
| react.dev/learn (SPA), no selectors | PARTIAL | `body` 6000 chars | navigation first; content cut |
| react.dev/learn, `wait_for: article h1` | WORKS | done in 3 s, "Quick Start" | — |
| Redirect `https://python.org/` → www | WORKS | done in 2 s, final `https://www.python.org` | HTTP redirects are followed inside the request |
| Cross-site redirect pypi.python.org → pypi.org | WORKS | done in 4 s, final `https://pypi.org`, 4261 chars | — |
| Very long page (`os` module), no selectors | PARTIAL | `body` 6000 chars | page is ~100× longer; no paging |
| StackOverflow question (anti-bot) | BROKEN | `done`, `body` 0 chars; probe: title "Just a moment..." | Cloudflare interstitial reported as success |
| npm package page (anti-bot) | BROKEN | `done`, 261 chars "Performing security verification" | anti-bot page reported as success |
| Missing selector `#does-not-exist` on example.com | WORKS | `missing: true`, task finished, other selector read | 8 s wait per missing selector; no hint |
| 404 page on docs.python.org | PARTIAL | `done`, 1554 chars of the 404 page | no HTTP status, so a 404 looks like a page |
| Slow page (httpbin delay 8 s) | WORKS | done in 10 s | — |
| Table (List of HTTP status codes), `table.wikitable` | WORKS | `missing: true` (the page uses lists, not tables) | the benchmark's selector was wrong; the report was right |
| Domain that does not exist | PARTIAL | `blocked` / `host_not_public` in 0 s | correct and fast, but the code does not say "domain does not exist" |
| raw.githubusercontent README | WORKS | done in 5 s, 2309 chars of Markdown | the clean way to read GitHub files |
| example.com `h1`, `p`, `title` (probe) | WORKS | `h1` missing, `p` 900 chars | example.com's current page; reported correctly |
| FastAPI challenge-marker probe | WORKS | `iframe[src*="recaptcha"]` attached | confirmed the cause of the false `captcha` |
| Burst of 23 tasks | PARTIAL | 2 × HTTP 429 "Забагато завдань у черзі" | Ukrainian-only message, no retry advice for an AI |

## What was changed (T-671, T-672)

| Stage | Status | Evidence | Problem |
|---|---|---|---|
| Main text instead of `body` (menus, sidebars, cookie banners, header/footer removed) + title, description, ≤150 links | WORKS | real Chromium on local pages: `RUN_BROWSER_FIXTURE=1 python test_browser_reading.py` — text starts at the article `h1`, no menu/cookie/sidebar/footer words, table cells kept | verified on local fixture pages only; live after merge + EC2 sync |
| Up to 100 000 chars, read in chunks (`offset` → `next_offset`) | WORKS | `test_web_surfer.py`: 33 000-char page read back exactly in 20 000-char chunks; selector text > 6000 marked `truncated` and pageable | live after merge (server) + EC2 sync (worker sends the long text) |
| JS-rendered pages: wait ≤ 5 s for network idle | WORKS | real Chromium fixture: content fetched by JS after 0.6 s is in the text | live after EC2 sync |
| HTTP status reported, `hints` for 4xx/5xx | WORKS | real Chromium fixture: 404 → `http_status: 404`; hint test | live after merge + EC2 sync |
| `hints` for every blocker (bad domain, timeout, anti-bot, missing selector + `[id="a.b"]` tip, little text → `wait_for`, redirect) | WORKS | `test_web_surfer.py` `test_hints_name_the_next_step` | hints for old blocker codes work right after merge (server only) |
| Anti-bot pages → `waiting_human` / `bot_challenge` (never bypassed) | WORKS | real Chromium fixture ("Just a moment..." page) + fake-browser test | live after EC2 sync |
| Invisible reCAPTCHA / captcha widget on a readable page no longer stops a read | WORKS | real Chromium fixture (`size=invisible` iframe) + fake test (≥ 1500 chars of text); draft plans keep the strict rule | live after EC2 sync |
| `net::ERR_*` code as blocker (no URL or message) | WORKS | fake-browser test with a secret-bearing URL in the error | live after EC2 sync |
| JS redirect to another site: `redirect_to` + one automatic follow in `web_read` (same URL rules) | WORKS | fake tests: target reported without query; private target not followed | HTTP redirects already worked before |
| `queue_ahead` for queued tasks; 429 message also in English with retry advice | WORKS | `test_web_surfer.py`, `test_browser_tasks.py` | the 20-task cap itself is unchanged (safety bound) |
| MCP tool descriptions with examples and the read → chunk → hints workflow | WORKS | `test_tool_descriptions_teach_usage`; `docs/guides/surfer-mcp.md` | — |
| Agent REST returns the same `view` (`?offset=&max_chars=&links=`) | WORKS | `test_browser_tasks.py` route test (no TestClient) | live after merge |
| Executor origin check refused private IP literals only by accident of the proxy | WORKS | `test_browser_playwright.py` `OriginGuardTest` (T-672) | the egress proxy already refused them; now both layers do |
| EC2 worker restarts when `browser_runner/` changes | WORKS | `python -m autopilot.test_autopilot` | before, only `autopilot/*.py` triggered a reload |

## After (honest status)

| Stage | Status | Evidence | Problem |
|---|---|---|---|
| Re-run of the benchmark on production after the change | NOT STARTED | the PR is not merged; Render serves v5.10.0 without T-671 | run `python tools/surfer_benchmark.py` after merge and after the EC2 worker has synced `main` |
| Server part (hints, chunks of what arrives, descriptions, REST view, redirect follow, English 429) | UNKNOWN | unit tests only | live on Render after merge (CI-gated deploy) |
| Worker part (main text, links, HTTP status, net codes, anti-bot, invisible captcha, JS wait) | UNKNOWN | unit tests + real Chromium against local pages; public sites are unreachable from this build container (egress allowlist) | live after the EC2 worker merges `main` and restarts (automatic: `sync_branch` → `code_updated`, because `autopilot/browser_tasks.py` changed) |

Expected after both parts are live, from the evidence above: the 7 PARTIAL "menus / cut at 6000" rows become full
main text in chunks; the 3 anti-bot/false-captcha BROKEN rows become a correct `waiting_human` with a next step
(or `done` for FastAPI); the 404, missing-selector and bad-domain rows get explicit hints. Not expected to change:
anti-bot sites stay unreadable by design (no bypass), queue wait under bursts (one worker), and guessed selectors that
do not exist (the hint now tells the AI to read the main text first).

Data: raw task JSON was kept in the session scratchpad only; the table above is the complete summary.
