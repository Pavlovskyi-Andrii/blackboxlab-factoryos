# Owner Home and Growth Manager: test plan and findings (T-733, issue #452 §8)

Date: 2026-11-24 · Author: Claude (interactive session).
Object under test: the clickable prototype `docs/prototypes/owner-home-growth/index.html`, served in the FactoryOS
Learning sandbox (`/learn/view/owner-home`) from a local build of `main` (v5.19.1 + this branch). Demo data only.

## 1. What this document claims, and what it does not
| Tier | Done? | What it tells us |
|---|---|---|
| 1. Expert review (Claude) | **Done** | Whether the screens follow the agreed patterns. This is opinion, not user evidence |
| 2. Automated checks on the prototype | **Done** | Overflow, errors, text size, completeness of three languages, number of clicks per task |
| 3. Test with people (owner + 3–4 people he brings) | **NOT STARTED** | The only evidence of comprehension. Script in §5 |

No person has used the prototype yet. No percentage below describes people.

## 2. Automated checks (tier 2), run 2026-11-24
Ran against the sandboxed Learning route with the production CSP (`sandbox allow-scripts; default-src 'none'`).

| Check | Scope | Result |
|---|---|---|
| Page errors, console errors | 8 states × 9 views × 3 languages × 2 widths (390, 1440) = 432 renders | 0 |
| Horizontal overflow | same 432 | 0 |
| Visible text below 12 px | same 432 | 0 (one 11 px badge found and fixed during the run) |
| Untranslated string keys on screen | same 432 | 0 |
| Same keys and placeholders in EN/UK/RU | `test_owner_home_prototype.py` | pass |
| No network loads, storage optional | `test_owner_home_prototype.py` | pass |
| Script parses | `node --check` | pass |

### Tasks of issue §8, measured as clicks from the first screen
"Clicks" are the deliberate actions in a scripted run (Playwright). Typing in fields is not counted, as the issue says.
Each row was run at 390 and 1440 px with the same result.

| Task | State | Path in the prototype | Clicks | Current dashboard (audit §6) |
|---|---|---|---|---|
| T1 find «start a goal» | empty | «+ New goal» and «Set a goal» on the first screen | 0 | No path |
| T2 start a MyCast growth goal | empty | Product card «Set a goal» → summary «Here is what I understood» → «Start the goal» | **2** | No path |
| T2 (full wizard, new product) | empty | Header «New goal» → 5 × Continue → Start | 7 | No path |
| T3 find and review the draft variants | approval | «Compare» in the Needs-you strip | 1 | About 4, across 2 pages |
| T4 decide, and see the consequence first | approval | Compare → «Choose B»; the text «Nothing is published» is shown before and after | 2 | About 5 |
| T4 reject without a reason | approval | Refused with «Write a reason first» | — | — |
| T5 tell a click from a registration from a payment | completed | Results: definitions + funnel with «counted from» column | 1 | Partly no path |
| T6 expert: history, tokens, MCP | working | Agent team → Pro version | 2 | 1–2 |
| T7 recover a stopped step | failed | «Retry» in the banner | 1 | About 3 |
| Approval reachable on the first phone screen | approval | «Compare» button inside the first 844 px at 390 px | yes | no |
| Pro version switch visible on the first screen | every state | header button, desktop and phone | yes | — |

Finding during the run: the first version needed **7 clicks for T2**, which misses the target of ≤ 3. The product card
now opens the summary step directly, already filled in (benchmark pattern P-02, «here is my read, correct me»), so T2
takes 2. The full six-step wizard stays for a new product, where nothing is known yet.

## 3. Expert review (tier 1): issue §4 questions on the prototype
| Question | Prototype | Remaining risk |
|---|---|---|
| Purpose in 10 seconds | One promise line on Home, and the new-user screen «FactoryOS grows your products» with four numbered steps | Untested with people |
| One primary action per context | One blue button per card or strip | Header «New goal» and card «Compare» can both be blue on Home in the approval state |
| What is happening / finished / blocked / needs me | «Needs you» strip, «Working now» with claim time and last sign of life, one status word per product | The words need real data from `GET /api/factory/owner-home` (B-05) |
| Real vs demo values | Every screen shows «DEMO DATA»; the funnel shows «not measured» and «not connected» instead of zeros | — |
| Status consistency | Six owner words mapped to existing enums (IA spec §5) | Mapping is a design; B-05 must test it |
| Mobile | Bottom tabs, approval on the first screen, sticky wizard actions | Real touch test not done |
| RU/UK/EN | Complete and parity-tested | Copy not reviewed by a native editor |
| Keyboard and focus | All controls are buttons or inputs; visible focus ring; heading focus after navigation | Not tested with a screen reader |

## 4. Acceptance targets carried into the people test
These are targets to check. None of them has been met by people yet.
- At least 4 of 5 participants explain what FactoryOS is for after 10 seconds on Home. With n = 4–5 this is reported as a count.
- T1–T3 completed without hints and without a wrong destructive action by every participant.
- T2 in ≤ 3 deliberate actions (met in the scripted run: 2).
- Approval reachable on the first phone screen (met in the scripted run).
- No participant believes that choosing a variant publishes it (T4 comprehension question).

## 5. Script for the owner and the 3–4 people he brings (tier 3)
Duration 10–15 minutes per person, one person at a time, phone or laptop. The facilitator does not explain the product.
The participant may stop at any time. No recording without consent. Notes record actions and answers, not names.

1. Open the prototype at «New user». Ten seconds, then hide the screen: «What is this product for?» Write the answer as said.
2. Switch to «Empty»: «Start a goal to get more people to register for MyCast.» Count clicks; note hesitations over 5 seconds.
3. Switch to «Awaiting approval»: «Something waits for you. Find it and decide.» After the decision: «What happened now? Is anything published?»
4. Ask the participant to reject both variants. Watch whether they find the reason field.
5. Switch to «Completed», open Results: «How many people registered from variant B? How many paid?» The correct answer for paid is «not measured / not connected».
6. Switch to «Failed»: «Something broke. Fix it.»
7. «Where would you see what the agents did in detail?» Expected: Agent team or Pro version.
8. «Go back to the old full dashboard, then return.»
9. Closing: «What was confusing? What would you remove?»

Record per participant: device, language, task success (yes, with hint, or no), clicks, the question 1 answer, the question 3 answer, and any wrong destructive action. Results go into §6 of this file as counts.

## 6. Results with people
**NOT STARTED.** The owner said on 2026-11-23 that he will bring 3–4 people. This section stays empty until a session happens.
