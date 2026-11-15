# AI Decision Memory — validation interview script (#187, T-614)

Purpose: learn whether people who make recurring product/engineering decisions lose track of *why* they decided and
*whether it worked*, and whether a decision log with a mandatory expected outcome and a follow-up date would change
their behaviour. This is problem validation, not a sales pitch. Contacting anyone is an owner action (see the
`[HUMAN] T-614-H1` runbook); no message is sent by FactoryOS.

Who: 5 people who make or record team decisions weekly (founder, tech lead, product manager, solo builder running
AI agents). Adults, invited personally, with their consent to take notes. Do not record audio without explicit consent.
Do not collect company secrets: ask them to describe decisions in general terms.

Length: 25–30 minutes. One interviewer, one note-taker if possible.

## 1. Context (5 min)

1. What is your role, and how many decisions a week would you say you make that someone else will rely on later?
2. Where do those decisions live today? (chat, tickets, docs, ADRs, nowhere)
3. Who else needs to know about them, and how do they find out?

## 2. The last real decision (10 min) — ask about the past, not about hypotheticals

4. Tell me about the last decision you made that you later had to explain or revisit. What happened?
5. When you revisited it, how did you find the original reasoning? How long did it take?
6. Did you know at the time what result you expected? Did you write it down?
7. Did anyone check later whether it worked? Who, and when? What triggered the check?
8. What did it cost when the reasoning was lost? (time, a repeated mistake, a conflict, money — their words)

## 3. Current workarounds (5 min)

9. What have you tried to keep decisions findable? Why did you stop, or why does it work?
10. Do you pay for any tool for this today, or spend team time on it? Roughly how much?

## 4. Preview reaction (5 min) — show the page only now

Show `/static/decision-memory/index.html` (owner's session; FactoryOS's own decisions, no third-party data). Say plainly
that it is a prototype with FactoryOS's real decision log and that the empty fields are real gaps, not a bug.

11. What is the first thing you would do on this page?
12. Which field would you actually fill in every time? Which would you skip?
13. If a reminder said "review due: did this decision work?", would you answer it? Through which channel?
14. What would make this useless for you?

## 5. Close (2 min)

15. If this existed for your team next week, would you try it on real decisions for two weeks? (yes / maybe / no — and why)
16. May I follow up with you in two weeks? (record consent and preferred channel)

## Scoring (fill in after each interview, no names in the repository)

| Signal | Evidence to note |
| --- | --- |
| Problem is real | They describe a concrete past decision whose reasoning or outcome was lost (Q4–Q8) |
| Problem is costly | They name a cost in their own words (Q8, Q10) |
| Expected outcome is the gap | They did not write down the expected result or never checked it (Q6–Q7) |
| Willingness to try | "Yes" to Q15 with a concrete team/decision in mind |

Decision rule for the owner (suggested, owner may change): continue if at least 3 of 5 interviews show a real, costly
problem **and** at least 2 say "yes" to Q15; otherwise reject or reframe the pilot in MVP Builder with the notes as
evidence. Store notes privately (not in this public repository); record only the aggregate in the MVP Builder event.
