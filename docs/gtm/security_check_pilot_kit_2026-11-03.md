# Blackbox Lab AI Security Check — restricted pilot kit (draft, 2026-11-03)

**Tracking:** #101 (commercial hypothesis), #98 (owned-repository baseline), #114 (route-auth audit). **Status: PRIVATE DRAFT. No sales, outreach, customer consent, payments, or third-party scans have taken place under this package.**

## Pilot offer

**Working headline:** Know what to fix before your app goes live.

A focused, permission-based **read-only source-code and configuration review** for small SaaS applications. The first experiment offers a *free opt-in review* of one small, mutually scoped repository or component. **$99 is an introductory price hypothesis for a later paid pilot, not a live checkout or proven market price.**

**What the client receives:** a concise report containing the agreed scope and commit, reproducible *non-exploit* checks, confirmed versus suspected findings, severity and business relevance, high-priority remediation, and explicit limitations.

**In scope, with written authorization:** dependency manifests, static authentication/authorization paths, configuration hygiene, accidental secrets patterns (redacted), common supply-chain risks, selected web code. Review only agreed repository/branch/files, in read-only mode.

**Out of scope by default:** penetration testing, site/API/network scanning, exploit attempts, active production traffic, brute force, regulatory certification, guaranteed vulnerability detection, private code transfer to third-party AI without separate consent. Do not advertise expert certification or human expert review unless actually performed.

## Permission and privacy gate (before accessing anything)

1. Verify the signer represents and can authorize the specified repository/company, using a documented company channel.
2. Obtain written scope: repository or provided archive, exact branch/SHA, date window, allowed tools, personnel, read-only method and exclusions.
3. State data handling: no production credentials; redact unexpected secrets instead of reproducing them; least privilege, local encryption/access controls, delete client copies within the *agreed* retention window. Do not promise a fixed retention deadline until operations can prove it.
4. Explain **AI provider transfer separately**. By default no customer code or sensitive excerpts go to external Claude/Gemini/ChatGPT models. Opt-in must list providers, payloads, privacy, use and retention.
5. Confirm commercial-use rights of each scanner/version/ruleset. Open-source scanners and third-party rule packs are NOT interchangeable licences.
6. Validate ability to deliver and route high-severity or disputed findings to qualified human review, where needed. Obtain owner approval before commitments, real client contact, payment setup or publication.

## Demonstration report — based on owned FactoryOS source (not a customer audit)

**Target:** own `Pavlovskyi-Andrii/blackboxlab-factoryos` source, as documented in `docs/security/2026-11-02-baseline.md` and draft `docs/security/2026-11-route-auth-audit.md` (PR #145). The latter inventories 202 route decorators in `app.py`, `relay.py`, `owner_desk.py`, `mycast.py`, **static inspection only**. This document does NOT reproduce sensitive values, perform a live attack, or assert new exploited vulnerabilities.

| Example finding | Evidence from own source | Confidence / status | Recommended remediation |
|---|---|---|---|
| Middleware/route auth consistency | The owner-desk worker-token regression was repaired after the middleware rejected a legitimate worker; route audit now lists analogous guard surfaces | Historical regression confirmed by source and tests; new bypass not verified | Add full ASGI auth matrix tests for owner/viewer/worker/unauthenticated requests; fail closed on token absence |
| Conditional media callback credential | `app.py` callback path uses a configured bearer token; route behavior depends on its configuration | Review item, **not** confirmed external bypass | Require explicit configured credential; test unset/missing/wrong/correct paths |
| Dependency patch baseline | 2026-11-02 baseline found older Python 3.9 resolution vulnerabilities; 3.13/CI floors and `pip-audit` were subsequently added | Baseline documented; current production package set not independently checked here | Keep secure Python 3.13 dependency floors, CI audit; verify production package versions from authorized logs |

**Method limits:** Source inspection is not exploitation, a pentest, certification or proof there are no other vulnerabilities. Report identifiers should be sanitized before any public marketing example.

## Private landing-page copy

**Blackbox Lab AI Security Check**

*Launching an app? Get a clearer picture of the code risks that matter first.*

A focused read-only look at one agreed small codebase. We review dependencies, access-control patterns and risky configuration, then give you a short prioritized report with what is confirmed, what still needs verification and what to fix next.

**Pilot:** Request a free, permission-based sample review. Later $99 paid pilot subject to proof of value and clear scope.

**CTA (inactive draft only):** Request the scope and consent form.

**Not a pentest.** No production scanning or guarantees. We access nothing without written authorization and don't send your code to external AI providers without separate permission.

## Commercial tooling checklist (review before customer use)

| Tool / material | Licence decision |
|---|---|
| `pip-audit` | Check current release licence and advisory source; only use per terms |
| `gitleaks` | Check licence/version; do not retain/display actual credentials |
| `bandit` | Check licence/version and false positives; never equate automated flags with proof |
| `Semgrep` engine and rule packs | **Not approved for commercial SaaS based on this draft.** Review Semgrep CE commercial terms and each ruleset licence before use; replace unclear tooling with permitted alternatives |

This table is a **licensing due-diligence queue**, not legal clearance. Specific package/ruleset versions, terms and commercial service rights require owner/licence review.

## Evidence ledger and release gates

| Gate | Evidence | Status |
|---|---|---|
| Positioning and scoped offer | This draft | Drafted, needs review |
| Owned-repo sample report | Baseline #98 and draft #114 | Partial, not reviewed for public use |
| Commercial scanner licence approval | Checklist above | Blocked |
| Client written authorization | No client yet | Blocked |
| Prospect contact & opt-in | No messages sent | Not started |
| Actual $99 purchase, fulfilment and receipt | No checkout/receipts | Not started |
| Public site/ads/outreach | Owner approval required | Not authorized |

**Next valid milestone:** owner reviews limited free-pilot scope and approves a vetted, private sample before any public sales claim or message.