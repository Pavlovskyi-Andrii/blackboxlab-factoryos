# Owner answers

Append owner answers to blocked roadmap tasks here.

Format:

```
## T-000
Owner answer or supplied non-secret decision.
```

Never paste secret values into this file. Secrets belong in the runtime secret store/environment only.

## Standing owner grants (2026-10-30)
Owner granted Claude, permanently and without asking each time:
1. Write code, create branches and PRs, maintain ROADMAP.md and assign Owner lanes.
2. Merge Claude's own PRs into `main` once CI is green on the current head (this is the normal CI-gated Render deploy path).
3. On the EC2 worker host: read logs/state, update the worker checkout (`git pull`), and restart the worker/supervisor services when they are stuck.
4. Close stale PRs and Issues with a comment explaining why.
Still owner-only (unchanged safety invariants): secrets/tokens, any paid service or API, real social publishing, deleting data or irreversible AWS/Render infrastructure changes, Telegram pairing (T-506), Metricool credentials (T-520).

## Owner answers 2026-11-15
- T-590-H: owner verified `/api/version` build_sha `60c983bd19fd…` == latest main commit. Production runs main.
- T-560-G: owner reports FACTORY_VAULT_KEY is set in Render (not yet confirmed via `/api/factory/vault/status`).
- T-606: Jules web reports "not yet available in your region" (Ukraine); owner connected it via VPN to the repository. Owner prefers a Gemini CLI worker on the existing EC2 host (zero extra spend) over Jules.
- T-520: Metricool API needs a paid plan; owner does not want to pay before testing. Free plan = 20 posts/month in Metricool's own UI. Owner open to a FactoryOS-native publisher instead. No reverse-engineering of private provider APIs.
- D-240: owner decision — take #240 and #241 now (Depends: none, owner decision). #242 waits.


## Owner answers 2026-11-16
- Merging: owner confirms Claude merges its own PRs itself (after green CI on the current head, no conflicts) and then checks the Render deploy.
- Versioning: owner wants one version shown everywhere on the site (sidebar said v5.3, header v5.7.1), the README changelog continued from v5.7 to today, a new current version on the site and on GitHub, and versioning kept up from now on. Rules: CLAUDE.md "Versioning and releases".

## T-702 (owner 2026-11-18, relayed from the owner task page)
- Approval mode: A — the owner approves the whole weekly plan with one action, then approved items publish by themselves. A is the default; B (rules) and C (each post) stay opt-in settings.
- Platform order (owner 2026-11-18): Telegram channel → LinkedIn → Instagram/TikTok → OLX.

## 2026-11-18 — owner task page answers
- Social publishing approval: mode A (approve the weekly plan once; approved items publish by themselves).
- Platform order: Telegram channel → LinkedIn → Instagram/TikTok → OLX.
- Google search through Gemini: not wanted (Free tier has no grounding); FACTORY_WEB_SEARCH_PROVIDER removed in Render, Surfer search uses Wikipedia (verified on prod 10:39 UTC).
- T-607-H Gemini worker on EC2: deferred.
- T-624: Claude lane token works (Relay write as `claude` verified 10:46 UTC); ChatGPT lane write not yet verified.

## 2026-11-23 — T-726 (relayed by the parent session)
- Owner answered «Да» to: allow Claude to read the Surfer "waiting for owner" list so it can mirror the requests as tickets on the owner task page. Read-only; the owner still answers on the Surfer page.

## 2026-11-21..23 — owner task page answers
- T-620-H MyCast referral terms approved: +7 days premium to both, once, when the friend's first episode is out, max 50 friends.
- T-702-H Telegram channel set up; every post must carry a teaser image (done in T-713).
- T-701-H OLX partner app approved and connected (owner-confirmed).
- T-722-H Surfer actions switched on; first allowlisted site blackboxlab-factoryos.onrender.com; agents may read the Surfer pending list (T-726).

## #452 (owner 2026-11-23, in the Claude session; T-731 / T-732 / T-733 (first numbered T-726–T-728 on the branch; renumbered because main took T-726/T-727))
- Amendment A1 to Issue #452 approved («Утверждаю, заводи 3 задачи»).
- The first screen is designed for the owner **and for future clients**.
- MyCast pilot audience: a busy person (businesspeople are one example, not the only one) who wants compressed information and to stay in focus on one chosen topic. Channel: Telegram — that is where the listener receives the episodes. Landing languages: English, Ukrainian, Russian.
- Usability test: the owner will bring 3–4 people for the prototype test.
- Priority: T-590–T-593 may be closed; #452 starts right after them.
- Read-only access to `docs.ploy.ai` and `ploy.ai` approved for the cloud environment (public pages only); `linear.app` and `posthog.com` added the same way for the two reference products.

## #452 Checkpoint A (owner 2026-11-24 ~04:10 UTC, relayed to the #452 session by the coordination session)
- Owner's words: «давай вариант 2. только оставь кнопку типа переключить на про версию сайта (типа на текущую версию)».
- Direction 2 «Продукты и цели» is chosen for T-733.
- The new home keeps a visible switch to the current full dashboard («Pro version» / «Pro-версія» / «Pro-версия») and a way back; nothing of the current UI is removed; the choice is remembered per browser.
- Blackbox Lab content card: not answered; default applies (a separate product card while content jobs exist).

## MyCast voices: ElevenLabs (owner 2026-11-27, interactive Claude session)
- Owner asked: «подключи ElevenLabs, выбор бесплатных голосов в MyCast.pro». Shown the limits found that day (free plan about 10,000 credits a month, roughly 10 minutes of speech, no commercial licence; one 15-minute episode is more than the monthly allowance; Starter about $6 a month), the owner chose **«Не подключать»**.
- MyCast keeps the Gemini voices only. Do not add an ElevenLabs integration, key or paid plan unless the owner asks again.
- The limits came from one web search of third-party pricing guides, not from ElevenLabs' own terms; re-check them before any future proposal.

## #452 owner gate (owner 2026-11-27, in the Claude session)
- «да, начинай со счётчика, тест параллельно»: implementation starts with B-01, the first-party MyCast visit counter (T-743); the people test with the owner's 3–4 people runs in parallel.
- Payment (T-709-H): the owner asked which provider can be connected and whether Stripe works. Answered in chat; decision still open.

## T-709-H (owner 2026-11-27, in the Claude session)
- «ФОП нету, и от этого отталкиваемся — ищем варианты, как можно проплатить». No FOP; the options without one are compared in `docs/business_experiments/LEAGUE_OWNER_DECISIONS.md` §3.1. Provider not chosen yet.
