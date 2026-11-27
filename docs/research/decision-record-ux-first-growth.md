# Decision record: UX-first Owner Home and internal Growth Manager (issue #452)

Date: 2026-11-24 · Author: Claude (interactive session) · Tasks: T-731, T-732, T-733.

## Decisions made by the owner
| Date | Decision | Source |
|---|---|---|
| 2026-11-23 | Amendment A1 to #452 approved; three ROADMAP tasks | This session |
| 2026-11-23 | First screen is for the owner **and future clients**; MyCast pilot audience = busy people who want compressed news on one chosen topic; channel Telegram; landing languages EN/UK/RU; owner brings 3–4 people for the test | This session |
| 2026-11-24 | Direction 2 «Products and goals»; keep a visible switch to the current full dashboard («Pro version») and back, remembered per browser | Relayed by the coordination session, `.autopilot/answers.md` «#452 Checkpoint A» |

## Decisions made by Claude (reversible)
| Decision | Alternatives considered | Why |
|---|---|---|
| Benchmark from Ploy's public docs only, fetched as Markdown | Create an account; read third-party reviews | The terms forbid competitive use of the service and automated access to it; the docs offer a Markdown interface for AI tools |
| Adopt 7 patterns, adapt 7, keep 2 that FactoryOS already has, reject 8 (benchmark §5) | Copy Ploy's chat-first app | Chat-first needs an always-on server-side model and hides product state; FactoryOS already has structured stores |
| Goal = one small entity inside the MVP registry record | A new goals service or database | Everything else already exists; one store and one lock are easier to keep consistent |
| Goal state is computed, never stored twice | A stored goal status | Two copies of a status drift; the audit found five status vocabularies already |
| Quick start from the product card opens a prefilled summary | Always the 6-step wizard | Measured 7 clicks vs the target of ≤ 3; the summary pattern (P-02) brings it to 2 |
| First implementation PR = first-party visit counter (B-01) | Start with the Home UI | Without visits and variants, the funnel cannot be honest; every later screen depends on it |
| Counter without cookies, IP or user agent stored; daily-rotating hash | A third-party analytics script | Privacy, $0, no consent banner needed for a cookie that does not exist (the privacy page wording still goes to the owner) |
| Owner Home behind `FACTORY_OWNER_HOME_ENABLED`, current dashboard as «Pro version» | Replace the dashboard | The owner asked to keep it; a flag gives rollback without data loss |
| The Blackbox Lab content card is shown as its own product card while content jobs exist | Hide content from Home | Owner did not answer; this was the stated default |
| Prototype lives in the Learning sandbox, not on the production dashboard | A hidden route on the dashboard | No production change before the owner gate; the sandbox has no network and no cookies |

## Open for the owner gate
1. Approve the backlog order in RFC §11, starting with B-01 (visit counter). Or name another first PR.
2. Run the people test (script in `growth-manager-test-plan-and-findings.md` §5), or allow S5 to start without it.
3. The privacy page wording for the visit counter (needed before the B-01 flag is turned on).
4. Payment provider (existing T-709-H): until it exists, the «Paid» step stays «not connected».
