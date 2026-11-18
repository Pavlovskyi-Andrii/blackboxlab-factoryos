# FactoryOS: how ready is it to earn revenue? (repository audit)

Audit date: 2026-11-18 (project date 2026-11-17). Repository `/home/user/blackboxlab-factoryos`, HEAD `11a3330`
("Merge pull request #416", 2026-11-17), `APP_VERSION = "v5.12.0"` (`app.py:79`). This is a read-only code and document
audit. I did not read any `.env`, did not call authenticated FactoryOS endpoints and did not use FactoryOS MCP tools.
The local clone is shallow: 98 commits, 2026-11-13 … 2026-11-17 (`git rev-parse --is-shallow-repository` → `true`;
`git log --format=%ad --date=short | sort | uniq -c`). So git-history claims cover only those five days. I made two
read-only GitHub API reads, both noted where used: `git ls-remote origin` and GitHub `get_commit`/`get_file_contents`
on branch `chatgpt/blank-mycast-customer-development`.

Status grades used below: **live-verified** (a repo document records a real run, with its evidence), **tests-only**
(code plus deterministic tests, no recorded live run), **planned**, **blocked-on-human** (an open `[HUMAN]` task), **unknown**.

## Key claims

| # | Claim | Source (file / git evidence) | Date / version | Confidence |
|---|---|---|---|---|
| 1 | The repo has no payment, billing, checkout, invoice, paywall or pricing code and no payment configuration. The only matches are a regex for Stripe-shaped secrets in a secret scanner and false positives. No Telegram payment methods are called (`sendInvoice`, `XTR`, `pre_checkout_query`, `successful_payment`: 0 hits). | `security_findings.py:27`; greps listed in §1; Bot API methods used: `sendMessage`, `answerCallbackQuery`, `setWebhook`, `sendAudio`, `getFile`, `getUpdates` only | HEAD 11a3330, v5.12.0 | verified_primary |
| 2 | ROADMAP has no task at all for payments, pricing or invoicing: 98 done, 40 open, 16 open `[HUMAN]` tasks, and none of them concerns taking money. | `ROADMAP.md` (`grep -cE '^- \[x\]'` = 98, `'^- \[ \]'` = 40, `'^- \[ \] \[HUMAN\]'` = 16) | 2026-11-17 | verified_primary |
| 3 | Revenue = 0 and customers = 0. Every business document says so explicitly ("No sales, outreach, customer consent, payments … have taken place"; "Нет разрешения … выставлять реальные счета"). | `docs/gtm/security_check_pilot_kit_2026-11-03.md:5`; `docs/business_experiments/02_CLAUDE_HANDOFF_BUSINESS_DIRECTION.md:33` | 2026-11-01 … 11-08 | verified_primary |
| 4 | MyCast is the most complete public product: the mycast.pro domain (owner bought it 2026-11-13), Telegram/Google listener accounts, daily personal episodes delivered to the listener's own Telegram, a library, revocable public episode links, a 7+7 referral ledger and a free-days counter that can be enforced. | `DECISIONS.md` «2026-11-13 — mycast.pro», «#317», «2026-11-15 — T-620»; `mycast_accounts.py`, `mycast_library.py`, `mycast_listener_delivery.py` | 2026-11-13 … 11-15 | verified_primary (code); live use beyond the owner: unknown |
| 5 | MyCast already has an entitlement mechanism that a payment could plug into: `free_days = 7 + referrals×7 + bonus_days`, `ListenerStore.grant_bonus(slug, days≤31, key)` adds days idempotently, and `FACTORY_MYCAST_ENFORCE_TRIAL=1` stops delivery when access ends. Both the enforcement and the referral offer are OFF by default. | `mycast_library.py:40,57-58,214-240`; `mycast_accounts.py:163-181`; `mycast_listener_delivery.py:118-120` | T-620/T-634, 2026-11-15/17 | verified_primary (tests-only) |
| 6 | MyCast capacity is capped at 10 listener episodes per UTC day across all listeners (the Gemini free-tier budget). TTS uses a preview model (`gemini-2.5-flash-preview-tts`) on the free key. | `mycast_listener_delivery.py:39`; `mycast.py:216`; `DECISIONS.md` «T-620» last bullet | 2026-11-15 | verified_primary |
| 7 | Listener scripts are written by the owner's personal Claude subscription on EC2. This contradicts the repo's own 2026-11-11 rule: "serving a personal subscription to public visitors is not something to do". The conflict is not reconciled anywhere. | `autopilot/mycast_listeners.py:1-5`; `DECISIONS.md:950` vs `DECISIONS.md` «#317» bullet "Worker" | 2026-11-11 vs 2026-11-13 | verified_primary (the contradiction); ToS consequence = inference |
| 8 | The only written MyCast price hypothesis is **$1/month after a 7-day trial**. It sits on an unmerged branch and is explicitly marked "not proven by sales". With 10 episodes/day, the gross ceiling is about $10–23/month. | GitHub `chatgpt/blank-mycast-customer-development` @095c0a8, `docs/growth/STARTUP_OWNER_MANUAL_MYCAST_PLAYBOOK.md` §2, §5 V1, H08 (not on main: `ls docs/growth` fails) | 2026-11-13 | verified_primary (doc); ceiling = inference |
| 9 | No external MyCast listener, MyBrief respondent or interview is recorded anywhere in the repo. The owner is the documented first listener (website podcast set up 2026-11-11). The only quality signal is the owner rating his first full episode 7/10 on 2026-11-05. | `DECISIONS.md:676`, `:996`; `grep -rniE "[0-9]+ (listeners\|users\|subscribers)"` over `*.md` → no hits | 2026-11-05 … 11-17 | verified_primary (absence in repo); real count = unknown |
| 10 | Every validation step that would produce demand evidence is a blocked `[HUMAN]` task: T-645-H (demo audio), T-620-H (referral terms), T-634-H (quiz gifts + mail key), T-615-H (MyBrief 48 h test), T-614-H1 (5 interviews), T-520/T-521 (first publisher, first post), T-700-H (LinkedIn app). | `ROADMAP.md:1,351,420,425,763,785,801,835` | 2026-11-15 … 11-17 | verified_primary |
| 11 | Content Factory has never made a real external post. The publisher adapter defaults to `manual`; the Metricool API needs a paid plan the owner declined. The YouTube and LinkedIn adapters are code-complete but wait for owner OAuth. The repo has no audience numbers. | `app.py:289`; `.autopilot/answers.md:26`; `ROADMAP.md:420-427,553-558,345-355`; `docs/research/metricool_api.md:9` | 2026-11-01 … 11-17 | verified_primary |
| 12 | The highest-ticket packaged offer is the "AI Security Check" (free pilot, then a $99 price hypothesis). It is a private draft. The owner never selected it, it has no ROADMAP task, the scanner licences are "Blocked", and no prospect has been contacted. Claude recommended it as the first program on 2026-11-03; the owner instead picked MyCast, MyBrief, Decision Memory and Release Guardian as the first MVP wave (2026-11-15). | `docs/gtm/security_check_pilot_kit_2026-11-03.md` (evidence ledger); `docs/handoff/TEAM_PLAN_2026-11-06.md:32,59-63`; `ROADMAP.md:726,776` | 2026-11-03 … 11-15 | verified_primary |
| 13 | ZERO ADDITIONAL SPEND is the binding policy. Real publishing, outreach, payment setup and any paid API are owner-only. Recurring costs nevertheless exist: two paid Render services with disks, a GitHub Actions budget the owner raised after using $5 in two days, the mycast.pro domain and a Claude subscription. The repo states no monthly totals. | `ROADMAP.md:27`; `docs/roadmap/T-562_RUNNER_SUPERVISOR.md:3`; `.autopilot/answers.md:20`; `render.yaml` (`0.5c-512mb` + 1 GB, `1c-2g` + 5 GB); `DECISIONS.md:829,1133-1135` | 2026-10-27 … 11-14 | verified_primary (existence); amounts unknown |
| 14 | The owner works from Ukraine. Jules reported "not yet available in your region (Ukraine)", and Kyiv time drives schedules. The repo has no legal entity, FOP, merchant account or tax setup, and the MyCast terms name no operator, contact, price or refund rule. | `.autopilot/answers.md:25`; `static/mycast-configurator/terms.html` (13 Nov 2026 edition); grep for `ФОП\|FOP\|LLC\|merchant\|VAT` → no relevant hits | 2026-11-13/15 | verified_primary |
| 15 | Engineering effort runs mostly on platform work, not revenue. In the visible 76 non-merge commits (11-13 … 11-17): about 25 agent infrastructure/ops, 25 product/MVP, 11 content/publishing, 10 release/docs. None touched pricing or payments. The Hercules teardown recommends still more internal platform work and puts "external productization" last. | `git log --no-merges --format=%s` keyword bucketing (see §7); `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md` "Recommended order" | 2026-10-25; 11-13 … 11-17 | verified_primary (counts); bucketing = inference |

## 1. Payment, billing, checkout, invoice, subscription and pricing code

**Verdict: none exists (verified_primary, by exhaustive search).**

Searches run over the whole repository, excluding `.git`, `research_notes` and `node_modules`, case-insensitive:

| Term | Files hit | What the hits are |
|---|---|---|
| `stripe` | 3 | `security_findings.py:27` (a regex for Stripe-style **secret keys**, used for redaction); `mods/product-film/.../kit.js`, `puppet.js` (the colour name "stripe") |
| `paddle`, `lemonsqueezy`, `lemon squeezy`, `liqpay`, `wayforpay`, `fondy`, `monobank`, `paypal`, `gumroad`, `patreon`, `boosty`, `ko-fi`, `buy me a coffee`, `invoice` | 0 each | — |
| `telegram stars`, `sendInvoice`, `pre_checkout`, `successful_payment`, `createInvoiceLink`, `answerPreCheckoutQuery`, `refundStarPayment`, word `XTR` | 0 (one false positive: "stars" in `mvp_evolution.py:13` means rating stars) | — |
| `checkout` | 41 | all `actions/checkout@v4` or git checkouts |
| `\bpayment` (19 files), `\bbilling` (31), `\bpricing` (7) | — | Policy text ("no payment"), Google Billing warnings in owner runbooks (`owner_desk.py`, `owner_desk_i18n.py`: "STOP … do not add a card"), an error classifier (`app.py:7757` `billing_exhausted`), a peer-review risk regex (`peer_review.py:29`), demo-brief news text (`static/mybrief/demo-briefs.json`) |
| `\bsubscription` (59) | — | Always the **owner's AI subscriptions** (Claude Pro/"subscription worker", Gemini free tier), never customer subscriptions (`app.py:3455-3456`, `relay_execution.py:1`, `mvp_builder_preflight.py:148-151`) |
| `\bprice\b`, `\brevenue`, `\bpaid plan`, `\bcharge\b`, `\bwaitlist` | — | News-fixture text, "may incur an external provider charge" confirmations, `.autopilot/answers.md:26` (Metricool paid plan declined), `docs/handoff/TEAM_PLAN_2026-11-06.md:62` (a MyCast "waitlist landing page" as a *plan*) |

Telegram Bot API methods actually used in Python: `sendMessage` (52), `answerCallbackQuery` (24), `setWebhook` (2), `sendAudio`, `getFile`, `getUpdates` (grep of `"sendX"` string literals and `/method` paths). No payment method is among them.

Monetisation-shaped code that does exist (all **tests-only**, none of it attached to money):
- **MyCast free-access period.** `FREE_DAYS, FRIEND_DAYS, MAX_REFERRALS = 7, 7, 50` (`mycast_library.py:40`). Free days start at the first delivered episode. `FACTORY_MYCAST_ENFORCE_TRIAL=1` makes the delivery gate return `trial_ended` (`mycast_library.py:57-58,236-240`; `mycast_listener_delivery.py:118-120`). It is OFF by default (open beta, owner decision). The guide says: "there is no payment" (`docs/guide/mycast.en.md:76`).
- **Idempotent day grants.** `ListenerStore.grant_bonus(slug, days, key)`: 1–31 days, once per key, audited (`mycast_accounts.py:163-181`). It was written for quiz gifts. Inference: this is exactly the hook a paid purchase would use, with the payment charge id as the idempotency key.
- **Referral ledger.** Append-only and idempotent, with anti-self-referral rules (`mycast_library.py` docstring; `DECISIONS.md` «T-620»). The offer is hidden until `FACTORY_MYCAST_REFERRALS=1` (T-620-H).
- **Provider spend guards.** These guard the owner's spend, not customers' (`app.py:277-278` `FACTORY_DAILY_BUDGET_USD` default 10, `FACTORY_JOB_BUDGET_USD` default 3).

## 2. CRM, lead capture, analytics, waitlists, referral, quiz

### 2.1 `faceless_crm.py` is not a sales CRM
- It is an "Owner-only, non-explicit Faceless Models CRM": a private tracker for **draft synthetic faceless model personas** with alias, niche, channel (`none/instagram/tiktok/youtube/fanvue/other`), stage (`idea … archived`), tasks and an event log. It has "no adult-media storage, face processing, outreach, publishing, payments … or third-party API calls" (`faceless_crm.py:1-4,22-23`). Registered as MVP project `faceless-models-crm` (#359). The registry brief says "Not approved: … adult-content hosting, payments, publishing or automated outreach. PR #360 is code under review, not evidence of deployment or validated demand" (`faceless_crm.py:308-318`). Merged 2026-11-14 (`git log -- faceless_crm.py` → `1732eb5`). Grade: **tests-only**; it has nothing to do with customers or leads.
- It belongs to a separate hypothesis, **Faceless Creator SaaS** (#313): a "privacy-first SaaS for adult verified creators" that would swap the creator's face for a synthetic AI persona. Stage 0 is demand testing only (`mvp_factory.py:60-81`). The brief records platform responses: OnlyFans support said in writing (2026-11-12) that substantially changing a creator's appearance is not allowed. Fanvue, Fansly and LoyalFans were asked on 2026-11-13; answers are pending. "Own adult-content sales platform … NOT part of this MVP. No approval for adult hosting, payments, autopublishing" (`mvp_factory.py:72-77`). Grade: **planned** (concept, not approved for build).

### 2.2 Real CRM and e-mail
- **HubSpot.** Only an OAuth provider definition (`oauth_framework.py:87-95`) and runbook text saying it "comes later" (`owner_desk_i18n.py:518-527`). The production OAuth apps are `[HUMAN] T-551` (open, `ROADMAP.md:539`). No HubSpot API call exists. Grade: **blocked-on-human / planned**.
- **E-mail.** No sending code (`grep -rniE "gmail|smtp|resend|sendgrid|mailgun|postmark" --include=*.py`, non-test files: only runbook text). Resend on a free plan is the planned provider (`owner_desk_i18n.py:42-46`); the sender is open task T-635 (`ROADMAP.md:841`), blocked on `[HUMAN] T-634-H` (mail key). Grade: **planned**.

### 2.3 Lead-capture surfaces that exist
| Surface | What it stores | Grade |
|---|---|---|
| MyCast listener accounts (Telegram / Google sign-in) | random slug, first name, provider + SHA-256 of the provider id, Telegram chat id (for delivery), podcast settings. **No e-mail, no photo, no token** (`mycast_accounts.py:1-19`) | tests-only + live for the owner (DECISIONS.md:996) |
| MyCast delivery opt-in | explicit consent version `mycast-delivery-consent-2026-11-07` plus a test message to one's own chat (`mycast_accounts.py:41`) | tests-only |
| MyBrief feedback (public, consent tick) | profession, topics, 1–5 rating, would-read-weekly, comment ≤500 chars with e-mails and phones **redacted**; no IP, name or e-mail; caps 5/client/day, 300/day (`mybrief.py:1-14`; `DECISIONS.md` «T-615») | tests-only |
| MyCast "Help us improve" quiz (T-634) | consented in-product feedback; optional e-mail **only with a separate contact consent**; gifts and e-mails held while their flags are off (`mvp_quiz.py:1-20`) | tests-only; gifts and mail blocked-on-human (T-634-H) |
| Referral ledger (T-620) | invite decisions with hashed identities (`mycast_library.py:15-24`) | tests-only; offer hidden (T-620-H) |

What is **absent**:
- No waitlist form (the only "waitlist" mention is the plan text in `TEAM_PLAN_2026-11-06.md:62`).
- No web analytics on any public page. A `grep` for `googletagmanager|gtag(|plausible|umami|posthog|mixpanel|amplitude|clarity.ms|metrika|segment.com` found only the English word "plausible" in three code comments.
- No visit→signup→delivery funnel instrumentation. The Product Evolution funnel (`invited, activated, used, returned, abandoned`) is entered by hand and stays "unknown until recorded with a source" (`mvp_evolution.py:45,378-398`; `docs/guide/mvp-pilots.en.md`).
- The MyCast quiz asks about usage, length, features, irritants and delivery channel (`q_use`, `q_length`, `q_add`, `q_fix`, `q_channel` in `mvp_quiz.py`), but **no willingness-to-pay or price question**. A grep for `pay|price|ціна|цена|заплат` in `mvp_quiz.py` found nothing.

### 2.4 Evidence of real leads or users
- None in the repository. `grep -rniIE "(real|first|live) (listener|user|customer|lead|subscriber)s?|\b[0-9]+ (listeners|users|subscribers|followers|views)\b" --include=*.md` gave no relevant hits.
- The draft MyCast Master Brief, written by Claude, says "Продукт работает (открытая бета), первые слушатели" (`brand_strategy_seeds.py:15`). That is an unverified draft statement.
- An owner-only endpoint `GET /api/factory/mycast/listeners` exists (`DECISIONS.md:1040`) and would hold the real count. I did not call it (authenticated). Real count: **unknown**.

## 3. MVPs: what exists, what was validated, what is pending, what charging would need

### 3.1 MyCast (personal AI podcast in Telegram, mycast.pro)
**Exists (code merged, deterministic tests):**
- **Public site.** mycast.pro is served by the same Render service and limited to MyCast paths. It has `/privacy`, `/terms`, robots and a sitemap (`app.py:1355-1374,1376-1387`; `DECISIONS.md` «2026-11-13 — mycast.pro (owner bought the domain)»).
- **Configurator.** Topics, AI subtopics, region, follows, voice (30 Gemini voices with samples), schedule, 1–30 minute length, optional Google Calendar read-only (`docs/guide/mycast.en.md` §4; `README.md` v5.10.0 MyCast line).
- **Delivery.**
  - Listener episodes are written per listener on EC2 by Claude (owner subscription, WebSearch/WebFetch) and voiced on Render by Gemini TTS (Charon + Kore by default).
  - Audio QC runs before sending, then the episode goes to the listener's own Telegram chat. One per listener per local day, 3 failures/day, **10 per UTC day overall** (`mycast_listener_delivery.py:1-13,39`; `autopilot/mycast_listeners.py:1-6`).
  - Audio is not stored; playback re-streams from Telegram `getFile` (`DECISIONS.md` «2026-11-13 — MyCast audio is not stored»).
- **V1 (T-620).** Library (newest 200), revocable `/mycast/e/<token>` links (noindex, no-store), referral ledger, access period (`ROADMAP.md:756-761`).
- **Share card (T-645)** and **owner-approved demo audio (T-665)** (`ROADMAP.md:1-11,768-773`).
- **Improve quiz plus an automatic V1→V2 analyst (T-634).** Themes with at least 10 people and 40% support become Relay tickets (`DECISIONS.md` «2026-11-17 — T-634»).

**Validation done:**
- Owner dogfooding only. The Piper episode reached the owner's Telegram on 2026-11-02 (`docs/handoff/TEAM_PLAN_2026-11-06.md` §1 "Live checks"). The Piper voice was then judged "unlistenable" by the owner (`ROADMAP.md` T-603 progress). The first full Gemini episode was rated **7/10** by the owner (`DECISIONS.md:676`, 2026-11-05).
- The owner set up his own website podcast on 2026-11-11. It was not sent until the #317 fix on 2026-11-13 (`DECISIONS.md:994-1003`).
- T-603 "7 consecutive mornings delivered + owner feedback" is still open (`ROADMAP.md:138-146`). A sibling note reports 16 consecutive daily script commits on `mycast/daily` (2026-11-02 … 11-17, via the GitHub API). I confirmed only that the branch exists (`git ls-remote origin "refs/heads/mycast*"` → `refs/heads/mycast/daily`).
- Grade: **live-verified for the owner as listener**. External listeners: **unknown, none recorded**.

**Pending (`[HUMAN]`):**
- T-645-H: generate, listen to and approve the demo episodes (`ROADMAP.md:1-4`).
- T-620-H: approve the referral terms and set `FACTORY_MYCAST_REFERRALS=1`. Trial enforcement is "a separate later business decision" (`ROADMAP.md:763-766`).
- T-634-H: gift terms plus a Resend mail key on mycast.pro (`ROADMAP.md:835-839`).
- Plus T-635 and T-636 (code, waiting on T-634-H).

**Price and positioning written down:**
- The only explicit price is a **$1/month after 7 free days** hypothesis (H08) in the Customer Development playbook on the unmerged branch `chatgpt/blank-mycast-customer-development` (commit 095c0a8, 2026-11-13, owner-authored, "docs(growth): refocus MyCast hypothesis on personal goals and focus tracks (#342)"). The file is absent on main (`ls docs/growth` → no such directory).
- The playbook itself insists that $1 "is not margin". It requires per-episode costing (`LLM + TTS + storage + fees + support + trial/referral bonuses`) before any paid model (§8). It reframes MyCast as "keep focus on your goals", with no first segment chosen (§2).
- The draft Master Brief (Claude, 2026-11-14) offers "7 дней бесплатно, +7 за друга" and targets "300 регистраций через Telegram" in 30 days. It lists "Сколько стоит?" among the audience's top questions, with no answer (`brand_strategy_seeds.py:15-24,30-45,84-90`).

**What would have to be true to charge for MyCast (repo-grounded):**
1. **An owner decision on price and terms.** It is a business choice the CLAUDE.md escalation rules reserve for the owner ("payment or a paid-provider confirmation"; `CLAUDE.md:40`).
2. **A payment rail.** None exists. Delivery is via a Telegram bot, so the natural rail is Telegram Stars. A sibling note reports Telegram's rule that digital goods in bots must be sold for Stars (`ext_messaging_email_crm.md:45`, citing https://telegram.org/tos/bot-developers; I did not open it). Whether Stars payouts work for a Ukraine-based individual is unresearched (same note, line 61).
3. **A generation path that may serve paying third parties.** Today:
   - The owner's personal Claude subscription writes listener scripts (`autopilot/mycast_listeners.py:4`), against the repo's own principle (`DECISIONS.md:950`).
   - TTS is a preview Gemini model on a free key that other features share, and that key returned 429 in production (`DECISIONS.md:1835-1840`).
   - Free-tier Gemini "may use the topic text to improve Google's products" (`DECISIONS.md:950`).
4. **Capacity above 10 episodes/day.** Otherwise revenue is capped near zero (see §8).
5. **An operator identity, contact and refund/price clauses in the terms.** The current terms have none (`static/mycast-configurator/terms.html`).
6. **Demand evidence beyond the owner.**

### 3.2 MyBrief for a profession (`mybrief-pro`, #188, T-615)
- **Exists.**
  - A public page `/static/mybrief/index.html` with a **static demo fixture**: 3 professions (software developer, school teacher in England, accountant/tax adviser in the US and UK), 13 items total (4 + 4 + 5), each with a dated source read by the FactoryOS Surfer on 2026-11-15 (`static/mybrief/demo-briefs.json`: `kind: demo_fixture`, `generated_at: 2026-11-15`).
  - "No server-side generation: zero calls, zero spend" (`DECISIONS.md` «T-615»). Consent-gated feedback (`mybrief.py:1-14`).
- **Not built.** No subscription, no recurring generation, no delivery, no accounts.
- **Validation.** Not started: `[HUMAN] T-615-H` "owner … sends the link personally to up to 5 people per profession … after 48 h reads /api/mybrief/feedback" (`ROADMAP.md:785-789`).
- **Grade.** Demo page **tests-only**; validation **blocked-on-human**.
- **Charging would require.** A generation and delivery pipeline (none), a payment rail and an audience. MyBrief is further from money than MyCast.

### 3.3 AI Decision Memory (#187, T-614)
- **Exists.** An **owner-only** web page over FactoryOS's own `DECISIONS.md`. It has no AI, provider, network, payment or publishing call. "Issue #187 does not authorize public access" (`decision_memory.py:1-17`). An interview script with a cost/WTP question exists: "Do you pay for any tool for this today … Roughly how much?" (`docs/mvp/decision-memory/INTERVIEW_SCRIPT.md:31`). The decision rule is 3 of 5 interviews showing a real, costly problem (`:57`).
- **Validation.** `[HUMAN] T-614-H1`: review, 5 interviews, decide (`ROADMAP.md:801-804`). Not done.
- **Grade.** **tests-only**; it is not even publicly reachable. It is the furthest from a sale: a single-tenant internal tool.

### 3.4 Other MVP-registry items
- **AI Release Guardian (#189, T-616).** An owner-only, read-only GitHub PR readiness board, at stage `idea` in the registry (`ROADMAP.md:728-734`; `docs/guide/mvp-pilots.en.md`). No external user path.
- **A/B Tester (T-608–T-610).** Internal. It never declares a winner, and controlled A/B stays draft-only because "no randomized assignment exists" (`mvp_experiments.py:1-12`).
- **MVP Factory overall.** "No full run of «spec → PR → CI → preview → your decision» has happened yet" (`docs/guide/mvp-pilots.en.md`, Limits; `docs/MVP_FACTORY_SPEC.md` build order D "Open").

## 4. Business hypotheses already written down

| Document | Hypotheses / content | Status and what is (not) authorised |
|---|---|---|
| `docs/business_experiments/01_PRODUCT_HYPOTHESES.md` (2026-11-01, ChatGPT discussion) | H1 AI Media Factory (paid video packages); H2 AI Team for Business (paid pilot per process); H3 Startup Validation Lab (fixed-price validation experiment); H4 (reserve) AI Engineering Team. Method: one narrow segment and one paid offer, 20–30 personal contacts in 14 days, count pilot payments not clicks | "исследовательские идеи, НЕ утверждённые"; "Решение о fork: не принято"; "Никакого решения сейчас не зафиксировано" (`:3-4`, last line). Not authorised to create tickets or campaigns |
| `docs/business_experiments/02_CLAUDE_HANDOFF_BUSINESS_DIRECTION.md` (2026-11-01) | Context handoff to Claude for the same four hypotheses | "Нет разрешения запускать лендинги, закупать рекламу, писать клиентам или выставлять реальные счета" (`:33`); "Не добавляй новые обязательные задачи в ROADMAP" |
| `docs/gtm/security_check_pilot_kit_2026-11-03.md` (ChatGPT PR #153, carried over by Claude 2026-11-08) | "Blackbox Lab AI Security Check": consent-based, read-only source/config review for small SaaS; free opt-in sample, then **$99 introductory price hypothesis**; deliverable report; scope and permission gate; private landing copy; tooling licence checklist | "PRIVATE DRAFT … Nothing here may be used with clients, prices or publicly without the owner's approval". Evidence ledger: licence approval **Blocked**; client authorization **Blocked**; prospect contact **Not started**; $99 purchase **Not started**; public site/ads **Not authorized**. Supporting assets: `security_findings.py` (schema, redaction, consent-gated export, tests only, "never scans anything"), `docs/security/2026-11-02-baseline.md`, `docs/security/2026-11-route-auth-audit.md` (own repo). No landing page in `static/` (`grep -rli "security check" static/` → none); no ROADMAP task |
| `docs/handoff/TEAM_PLAN_2026-11-06.md` (Claude, 2026-11-03) | "Goal of the company: earn money" (`:4`). Money track "after the P0 communication loop works": 1) Security Check landing + $99 pilot first; 2) MyCast waitlist landing after T-603 proves quality; 3) MyBrief/MyFeed concept only (`:59-65`). Owner decision (c) requested: which program gets the first landing test (`:32`) | No recorded owner answer selecting Security Check. On 2026-11-15 the owner chose the "first MVP wave": MyCast #305, Decision Memory #187, MyBrief #188, Release Guardian #189 (`ROADMAP.md:726,776`). None of them has a landing-page demand test with a price |
| `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md` (2026-10-25) | **Hercules** (hercules.app) = (1) a chat-driven full-stack AI App Builder (hosting, DB, auth, e-mail, payments …) and (2) "Hercules Agents" (reusable autonomous workers with triggers, guardrails, versions, evaluations). The analysis is public/clean-room only, because its AUP forbids reverse engineering | Conclusion: do **not** become a generic app builder. Copy primitives: version registry, evaluation lab, run analytics, guardrail engine, budgets, multi-account connectors, skills registry. Differentiate as "an operating system for AI + human production teams" with provenance and approval as business primitives, plus a possible creator marketplace/payout ledger. Commerce/payments rated P2 (row 26). Candidate backlog HERC-P0/P1 "not added to ROADMAP yet". Recommended order ends with "external productization". Inference: the teardown adds internal-platform scope and gives no revenue path |
| `brand_strategy.py` + `brand_strategy_seeds.py` (2026-11-14) | A 7-step "brand passport → Master Brief" (goal/KPI, positioning, audience, tone, pillars, TOFU/MOFU/BOFU funnel, offer/CTA), with an LLM "draft" button through the budget guard. Seeded with a **MyCast draft by Claude**: offer "7 дней бесплатно, +7 за друга", KPI "300 регистраций", a 4-week plan at 5 posts/week on Instagram/YouTube/TikTok/Telegram from 2026-11-16 | Every step is `state: "draft"` by Claude awaiting owner approval (`brand_strategy_seeds.py:1-5`). No published post exists (T-521 open). The 300-registration KPI conflicts with the 10 episodes/day cap |
| `docs/growth/STARTUP_OWNER_MANUAL_MYCAST_PLAYBOOK.md` (branch only, 2026-11-13) | A Blank/Dorf Customer Development playbook for MyCast. H01–H12 (problem, audio, personalisation, Telegram, quality, onboarding, retention, **$1/month price**, trial, referral, channel, unit cost); discovery gate of 10 interviews (≥6 confirm the problem); a 30-day plan | "рабочий стандарт / план экспериментов, не отчёт"; "приглашений не отправляли"; the first segment is "не выбрано". Not merged to main |
| Faceless Creator SaaS #313 and Faceless Models CRM #359 | Adult-creator face-replacement SaaS concept; persona-operations CRM | Draft "не погоджене на розробку"; payments and adult hosting explicitly not approved (`mvp_factory.py:63-80`; `faceless_crm.py:308-318`) |

## 5. Content Factory: output, quality gates, publishing, channels, audience

- **What it produces.**
  - A "Content Package" schema v1.0 with `final_script, hook, scenes, voice_over, subtitles_srt, title, description, cta, hashtags, thumbnail_concept, media_brief, source_list, fact_check_report, estimated_duration_sec, production_cost` (`app.py:6911-6916`).
  - Variant QA types: `unsupported_claim, weak_hook, duplicated_angle, missing_source, slow_intro, unclear_cta, excessive_length, unsafe_sensitive_claim, fact_conflict` (`app.py:4904-4907`).
  - AI Media Finisher edits uploaded talking-head video: ASR, cuts, captions, graphics, audio, Shorts/Reels.
- **Live-verified pilot (2026-10-21/22).** A real 349.7 s upload became about 232 s. It had 126 cuts, 103 caption groups and 5 graphics, and took 1,592 s of processing. A second job also reached READY (`docs/roadmap/FACTORYOS_V4_5_AI_EDITING_SPEC.md` §13). Durable media: "5/5 present, 0 missing, 261,314,094 bytes" after redeploy (`docs/roadmap/FACTORYOS_V4_8_DURABLE_MEDIA_SPEC.md:71`).
- **Idea generation needs a paid LLM key.** It uses an OpenAI-compatible endpoint by default (`app.py:101-113`), with $10/day and $3/job caps. Without the key the cycle runs in "demo mode", where idea generation from signals "fails honestly with 'Live LLM provider is not configured'" (`DECISIONS.md:1697`). Whether production has a key is **unknown**; CI runs with `FACTORY_LLM_API_KEY=""` (`CLAUDE.md` default verification).
- **AI video generation needs a billing-enabled Gemini project.** The Gemini Omni video adapter requires "Gemini API billing enabled … before a paid video test" (`README_RENDER.md:36-50`). That conflicts with the free-tier-only key policy (`DECISIONS.md:1471-1473`). Inference: under ZERO SPEND, AI video generation is effectively unavailable.
- **Quality gate.** Human approval before every external action. The dry-run pilot recorded `approval_gate_reached=true`, `publish_created=false` (`README.md:294`). Grade: **live-verified up to the approval gate**.
- **Real publishing: none (verified_primary).**
  - `FACTORY_PUBLISHER_ADAPTER` defaults to `manual` (`app.py:289`). `[HUMAN] T-520` (configure first real publisher) and `T-521` (first owner-approved real post) are open (`ROADMAP.md:420-427`).
  - Metricool: the API requires Advanced/Custom ("from $53/mo annual or $67/mo monthly", as recorded in `docs/research/metricool_api.md`, citing metricool.com, 2026-11-01; not re-verified by me). The owner declined to pay (`.autopilot/answers.md:26`).
  - YouTube direct publisher (T-552-YT) and LinkedIn (T-700) are code-complete with zero-network tests. They need owner OAuth (T-520, `T-700-H`).
  - OLX adverts (T-701) are planned only (`ROADMAP.md:356-360`).
- **Channels named in the repo.**
  - Metricool brand `blackboxlab7` with Instagram `blackboxlab7`, TikTok `@blackboxlab` and a YouTube channel ("проверено в аккаунте, 2026-11-01", `docs/research/metricool_api.md:9`).
  - Telegram bot `@FactoryOS_Blackboxbot`. It is also the bot that MyCast listeners receive episodes from (`ROADMAP.md:254`; `brand_strategy_seeds.py:13`).
  - vidIQ is "paused" (`app.py:2064`).
- **Audience numbers.** None anywhere in the repo (grep of `subscribers|followers|views` with digits in `*.md` → only feature descriptions).

## 6. Constraints that shape monetisation

- **Owner location: Ukraine.** Evidence: "Jules web reports 'not yet available in your region' (Ukraine)" (`.autopilot/answers.md:25`); schedules run on Europe/Kyiv (`docs/guide/mycast.en.md` §1; `render.yaml` `FACTORY_METRICOOL_TIMEZONE`). No business entity, merchant or tax setup is recorded (grep `ФОП|FOP|ТОВ|LLC|sole proprietor|merchant|VAT|ПДВ` → no relevant hits). Sibling note `biz_services_leadgen.md` (key claim 15, external sources) reports that Stripe does not onboard Ukrainian sellers and that Paddle/Lemon Squeezy exclude services. That is **reported_secondary**; I did not open those pages.
- **Spend policy.**
  - "ZERO ADDITIONAL SPEND: do not connect paid API billing, metered AI/browser calls, new paid cloud resources, or paid publisher plans without explicit fresh owner approval … Subscription access must never be silently replaced with PAYG API usage" (`ROADMAP.md:27`).
  - Owner rule 2026-10-27 (`docs/roadmap/T-562_RUNNER_SUPERVISOR.md:3`).
  - AGENTS.md: "No paid APIs, paid plans, new cloud resources, ads, real publishing or messages to real people" (`AGENTS.md:19`).
- **Approval rules.**
  - Owner-only: "secrets/tokens, any paid service or API, real social publishing, deleting data or irreversible AWS/Render infrastructure changes" (`.autopilot/answers.md:20`).
  - Escalation includes "payment or a paid-provider confirmation" and "explicit approval of real publishing" (`CLAUDE.md:40-42`).
  - "Contact people yourself: FactoryOS sends nothing to anyone" (`docs/guide/mvp-pilots.en.md`).
  - The owner wants the human removed from the feedback loop as far as possible ("максимально убираем человека", 2026-11-16, `ROADMAP.md:831`; "no manual interviews", `DECISIONS.md:1876`). Outreach and payments remain human-gated.
- **Subscriptions and accounts named.**
  - Claude: "Claude Pro" (`DECISIONS.md:32`, 2026-10-23; `docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md:16`), but "Claude's $100 subscription" (`DECISIONS.md:950`, 2026-11-11). **The tier is inconsistent in the repo.**
  - ChatGPT subscription: "gives no programmatic access" (`DECISIONS.md:946`).
  - Gemini: free-tier API key on Render; Gemini CLI on EC2 under the owner's Google login (`DECISIONS.md:1421-1424`).
  - Metricool: free plan, 20 posts/month in its UI (`.autopilot/answers.md:26`). vidIQ: paused in FactoryOS.
  - GitHub Actions: 2,000 free minutes used up by 2026-11-08, then a $5 budget, then raised after "$5 in two days" (`DECISIONS.md:826-829,1133-1135`).
  - Domain mycast.pro: bought by the owner (`DECISIONS.md` «2026-11-13»).
- **Infrastructure.**
  - Render (Frankfurt) runs two paid services: web `0.5c-512mb` with a 1 GB disk, and the media finisher `1c-2g` (Docker) with a 5 GB disk (`render.yaml:9,12,81,84,87,112`). README_RENDER "Why paid + disk?" confirms the web service is paid.
  - AWS: one existing EC2 instance in eu-north-1, Amazon Linux, "Do not create new instance" (`docs/handoff/CLAUDE_TAKEOVER_2026-10-29.md:27,140`). **The instance type is not stated in the repo** (grep `t[234]g?\.(nano|micro|small|medium|large)|instance type` → no hits).
  - Monthly totals for Render, EC2, Claude and domain: **unknown** from the repo.

## 7. Where the effort goes (inference from git and ROADMAP)

- **Commit mix.** Visible non-merge commits from 2026-11-13 to 11-17 (76 in total), bucketed by keywords in the subject: about 25 agent infrastructure/ops (Relay, Telegram, workers, MCP, Surfer, DBOS), 25 product/MVP (MyCast, quiz, MVP registry, A/B, faceless), 11 content/publishing, 10 release/docs, 5 other. Zero subjects mention pricing or payments; `git log --all -i -E --grep="pric|payment|billing|checkout|waitlist|landing|revenue|monet|paid"` matched only "paid API"/"zero-spend" wording.
- **Code size.** 176 top-level Python files (108 of them tests), about 39.5k lines of non-test top-level Python and about 26.5k lines of tests, plus a 4,939-line dashboard `static/index.html`. That is a large surface to maintain, with no revenue.
- **ROADMAP priorities.** The P0 section is "CLAUDE TAKES OVER" (Telegram/Relay control room). The "money track" of 2026-11-06 was conditioned on that P0 loop and has not started.
- **The binding constraint is decisional, not technical.** Of the 16 open `[HUMAN]` tasks, 9 gate demand evidence or distribution: T-645-H, T-620-H, T-634-H, T-615-H, T-614-H1, T-520, T-521, T-551, T-700-H.

## 8. Distance to a first real payment (my assessment)

Status ladder for the best candidate, MyCast:

| Step | State | Evidence |
|---|---|---|
| Product that delivers value repeatedly | Done for the owner (7/10 self-rating) | `DECISIONS.md:676`; T-603 open |
| Public acquisition surface | Done (mycast.pro, share pages); demo audio not approved | T-645-H open |
| Accounts + entitlement ledger | Done (days, grants, enforcement flag off) | `mycast_library.py`, `mycast_accounts.py:163` |
| Price and offer decided by owner | **Missing** ($1/mo is a branch-only hypothesis) | playbook @095c0a8 |
| Payment rail | **Missing** (0 code, 0 tasks) | §1 greps; ROADMAP count |
| Terms with operator, price, refund | **Missing** | `terms.html` |
| Generation path allowed and sized for paying users | **Missing / conflicting** | `mycast_listeners.py:4` vs `DECISIONS.md:950`; cap 10/day |
| ≥10 external users who listen and come back | **Missing / unknown** | no records |

**Revenue ceiling under the current constraints (inference, stated assumptions).**
- Assumptions: each paying listener takes 3–7 episodes per week; cap = 10 episodes per UTC day. That supports about 10–23 paying listeners.
- At the $1/month hypothesis: **about $10–23/month gross**, before Telegram/payment fees and Ukrainian tax.
- At an illustrative $5/month: about $50–115/month.
- Either way this does not cover a $100/month Claude subscription (if that figure in `DECISIONS.md:950` is current), let alone Render. A MyCast payment would be a **demand signal, not a business**, unless generation moves to paid metered APIs. That needs explicit owner approval, and the playbook's H12 per-episode costing has not been done.

## 9. Judgement: the single asset closest to a sellable offer within 14 days

**MyCast.** It is the only asset with a live public domain, real end-user accounts, a working delivery channel (the listener's own Telegram), an idempotent day-entitlement ledger and an enforcement switch. Taking money needs one new event ("payment succeeded → `grant_bonus(slug, N, charge_id)`") plus owner decisions, not a new product.
- Engineering estimate (inference): about 2–4 focused days for a Stars invoice, pre-checkout and success handling, refund, terms update and tests, reusing `grant_bonus` and the existing bot webhook.
- Everything else is owner work.

**The 5 missing pieces, in priority order:**
1. **Owner price/offer decision and terms.**
   - Pick a price and period. Sizing hint (my inference): $1 tests only payment friction, not value.
   - Turn on `FACTORY_MYCAST_ENFORCE_TRIAL=1` for new cohorts, decide T-620-H.
   - Add operator identity, contact, price and refund wording to `/terms`.
2. **A payment rail compatible with Telegram and Ukraine.** Telegram Stars is the obvious fit for a bot-delivered digital good, per the sibling note's sources. Payout feasibility for a Ukraine-based individual must be confirmed first. No code exists today.
3. **A generation path that may legally serve paying third parties, with known unit cost.**
   - Resolve the Claude-consumer-subscription conflict (`autopilot/mycast_listeners.py:4` vs `DECISIONS.md:950`).
   - Resolve the free-tier preview TTS dependency, shared with other features and already hitting 429.
   - Compute cost per episode (playbook H12) before setting the price.
4. **Demand evidence from people other than the owner.**
   - Close T-645-H (approved demo audio).
   - Have the owner personally invite 10–15 people (playbook D3).
   - Add one willingness-to-pay question to the quiz (none today).
   - Add a minimal visit → signup → delivery-on → D7 funnel. There is no analytics today.
5. **Capacity and brand hygiene.**
   - Raise or re-architect the 10/day cap before promising anything public. The draft KPI of 300 sign-ups is infeasible at 10/day.
   - Consider a MyCast-named bot instead of `@FactoryOS_Blackboxbot` for paying listeners (minor, inference).

**Runner-up for faster cash per sale: the AI Security Check pilot.**
- It needs no payment code: a manual invoice would do, if a Ukraine-compatible rail exists. Its offer copy, scope/consent gate, findings schema and own-repo samples already exist.
- It is blocked by things code cannot fix: owner authorisation, scanner licence clearance (Semgrep "Not approved"), credibility (a solo founder without security credentials, "Not a pentest"), customer code going to consumer AI subscriptions (the kit forbids that by default), and owner-led outreach.
- Sold as a done-for-you service, the AI Media Finisher (verified on real video in October) is a similar manual-service candidate with no external samples published.

## Counter-evidence and caveats

- **"Closest to sellable" is not "most likely to be profitable".** MyCast is B2C with a $1 price hypothesis and a 10/day ceiling. On the repo's own numbers it cannot cover existing subscriptions. A higher-ticket manual B2B service (Security Check, video finishing) could pay more per sale, but has no product evidence and needs owner selling time, which the repo shows is the scarcest resource. Nine demand-gating `[HUMAN]` tasks are open.
- **The shallow clone hides most history.** I cannot exclude that payment experiments existed before 2026-11-13 and were removed. Current HEAD has none, and the 2026-11-01 … 11-08 documents state that none happened.
- **The real MyCast listener count is unknown** (owner-only endpoint not called). "First listeners" appears in a Claude-written draft (`brand_strategy_seeds.py:15`) but is not evidence. A sibling note's "16 consecutive daily scripts" is GitHub-API evidence I did not reproduce.
- **The Claude subscription tier is inconsistent** in the repo ("Claude Pro" vs "$100 subscription"). The cost figures in §8 depend on it.
- **External platform facts are second-hand here.** Telegram Stars rules and payout rate, Stripe's unavailability in Ukraine, and Metricool pricing come from sibling notes or repo docs that cite external pages. I did not open those pages. Verify before the report relies on them.
- **ToS for consumer subscriptions.** Whether using a consumer Claude subscription or the free Gemini tier to produce a product for paying third parties is permitted is **inference to be verified externally**. The repo itself flags the concern (`DECISIONS.md:950`) but never resolves it.
- **"tests-only" grades mean deterministic tests in the repo.** I did not run the test suite.
- **Counter-argument to choosing MyCast.** The owner's own playbook says the core JTBD ("focus on goals" vs "news digest") and the first segment are unchosen. Charging before the problem interviews may only measure friends' goodwill. The counter-counter-argument: a real payment, even small, is stronger evidence than any quiz answer, which the playbook itself says ("Платёж сильнее устного «я бы заплатил»", H08).

## Implications for FactoryOS

1. **Freeze platform expansion until one paid signal exists.** Defer the Hercules P0 backlog, more MVP pilots, the faceless-creator concept and more agent lanes. The repo already has more product surface (176 modules, 4 pilots, 2 content publishers) than any customer has seen.
2. **Make MyCast the single money experiment for 14 days, framed honestly as a demand test.**
   - Add a ROADMAP task "MyCast paid access via Telegram Stars", reusing `grant_bonus` and the enforcement flag (Claude can build it; switching it on is `[HUMAN]`).
   - Add one owner `[HUMAN]` task bundling the price, terms, Stars/payout check and T-620-H decisions.
   - Close T-645-H first so the share page sells with real audio.
3. **Fix the legitimacy of the generation path before taking any money.**
   - Either keep MyCast at "friends and family, explicitly beta" scale, or get owner approval for a small metered budget per paying user, sized from a measured cost per episode.
   - Do not let a personal Claude subscription become the production backend for paying customers.
4. **Instrument the funnel minimally and ask the money question.** One server-side counter per stage (visit, signup, delivery on, D7 episode played or delivered) and one WTP question in `mvp_quiz.QUIZZES["mycast"]`. Without these, the automatic V1→V2 loop optimises features with no revenue signal.
5. **Keep the Security Check kit as the B2B fallback, but only if the owner commits sales time.** It needs licence clearance and owner outreach, not code. Do not build a Security Check product before one prospect agrees to a scoped free sample.
6. **Treat "autonomous AI company" as out of reach until a human-gated loop has produced revenue once.** All demand-creating steps (outreach, publishing, payment setup) are owner-gated by design, and should stay so. Autonomy can then be added to the steps that proved to make money.

## Sources

Local repository files actually read (HEAD `11a3330`):
- `CLAUDE.md`, `AGENTS.md:19`, `.autopilot/answers.md`, `ROADMAP.md` (lines 1-60, 138-165, 345-362, 405-430, 539-560, 726-870, HUMAN list), `README.md` (lines 1-120, 294), `README_RENDER.md` (1-50), `render.yaml`
- `DECISIONS.md` (by grep and sections: 32-37, 659-690, 718-722, 777-790, 826-832, 900-912, 940-956, 994-1050, 1133-1147, 1447-1545, 1655-1700, 1835-1840, 1874-1902, 1918-1935)
- `docs/business_experiments/01_PRODUCT_HYPOTHESES.md`, `docs/business_experiments/02_CLAUDE_HANDOFF_BUSINESS_DIRECTION.md`, `docs/gtm/security_check_pilot_kit_2026-11-03.md`, `docs/handoff/TEAM_PLAN_2026-11-06.md`, `docs/HERCULES_PUBLIC_COMPETITIVE_TEARDOWN.md`
- `docs/MVP_FACTORY_SPEC.md`, `docs/guide/mycast.en.md`, `docs/guide/mvp-pilots.en.md`, `docs/research/metricool_api.md` (1-40), `docs/roadmap/FACTORYOS_V4_5_AI_EDITING_SPEC.md` (§13), `docs/roadmap/FACTORYOS_V4_8_DURABLE_MEDIA_SPEC.md:71`, `docs/roadmap/T-562_RUNNER_SUPERVISOR.md:3`, `docs/mvp/decision-memory/INTERVIEW_SCRIPT.md` (grep)
- `faceless_crm.py`, `mvp_factory.py` (1-120), `mybrief.py` (1-45), `static/mybrief/demo-briefs.json` (parsed), `decision_memory.py` (1-30), `mvp_quiz.py` (1-140), `mvp_evolution.py` (1-20, grep), `mvp_experiments.py` (1-12)
- `mycast_accounts.py` (1-45, 160-185), `mycast_library.py` (1-60, 214-240), `mycast_listener_delivery.py` (1-60, 118-120), `mycast_public.py` (210-240), `mycast.py` (216-271 grep), `autopilot/mycast_listeners.py` (1-30)
- `brand_strategy.py` (1-50), `brand_strategy_seeds.py` (1-100), `security_findings.py` (1-25), `app.py` (by grep: 79, 101-113, 277-292, 1355-1425, 2064, 4904-4916, 6911-6925), `static/mycast-configurator/terms.html` (text extracted), `static/mycast-configurator/privacy.html` (grep)

Git commands:
- `git log --oneline`, `git rev-parse --is-shallow-repository`, `git shortlog -sn --all`
- `git log --all -i -E --grep=...`, `git log --no-merges --format=%s`, `git log -- faceless_crm.py`, `git log -- docs/business_experiments`
- `git ls-remote origin` (read-only)

GitHub API (read-only):
- `get_commit` 095c0a89f6c35fbefd4cf3b9e618debaee072e88 and `get_file_contents` `docs/growth/STARTUP_OWNER_MANUAL_MYCAST_PLAYBOOK.md` at that commit (https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/commit/095c0a89f6c35fbefd4cf3b9e618debaee072e88)
- root listing of `refs/heads/mycast/daily`

Sibling research notes (same project; cross-referenced as reported_secondary, their external URLs not opened by me):
- `research_notes/FactoryOS путь к прибыльной автономии/ext_messaging_email_crm.md` (lines 39-61, Telegram Stars)
- `.../biz_services_leadgen.md` (lines 29, 89-91, Ukraine payment rails, FOP tax)
- `.../repo_state_evidence.md` (key claim 15, mycast/daily scripts)
- `.../repo_external_adapters.md` (lines 18, 246, 253)
