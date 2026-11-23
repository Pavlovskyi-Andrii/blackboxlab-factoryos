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
