# MVP Factory and pilots: how it works

> Checked against the code and `ROADMAP.md` on 2026-11-16. If the dashboard shows something else, the dashboard is right and this guide is out of date.

## What it is

**MVP Factory** (the «MVP Builder» group in the menu) is a registry of small test products. Every idea goes through the same stages, and every step forward is backed by an evidence link. Only you make the final call: «validated» or «rejected».

Code: `mvp_factory.py` (registry and API `/api/mvp-factory`), spec: `docs/MVP_FACTORY_SPEC.md`, epic #186.

## How it works, step by step

1. **An idea** enters the registry as a project at stage `idea`.
2. **Stages** move strictly one at a time: `idea` → `researching` → `spec_draft` → `spec_review` → `build_queued` → `building` → `qa_review` → `preview_ready` → `owner_review` → `validated` or `rejected`.
3. **Evidence.** Every step forward needs a link: a GitHub issue, PR, commit or CI run, or a `/static/...` page. An AI saying «done» is not evidence. Only the shape of the link is checked, not its meaning, and the system says so openly.
4. **Agents** may move a project only through research and spec. They are not allowed to move it into build, preview, verdict or rejection.
5. **Your decision.** Only the owner sets `validated` and `rejected`.

Each project card has an agent «autopilot»: the Researcher prepares research and 3 variants, the Spec Writer writes the spec, then everything stops at your spec approval. It is off by default and runs on the free Gemini key.

## The pilots

| Pilot | What it is for | What actually exists |
|---|---|---|
| **AI Decision Memory** (#187) | A decision log: decision, reason, responsible person, sources, expected outcome, review date | Built (T-614): page `/static/decision-memory/index.html`, owner only. Demo data is read from `DECISIONS.md`. No AI is called. In the registry the agent takes the pilot up to `spec_review`. Waiting for you: 5 interviews and a decision (T-614-H1) |
| **MyBrief for a profession** (#188) | A sample briefing for 3 professions, every item linked to a real source | Built (T-615): public page `/static/mybrief/index.html`, feedback only after a consent tick. Waiting for you: a 48-hour test, you send the link personally (T-615-H) |
| **AI Release Guardian** (#189) | A PR readiness board: which CI checks really passed | Built (T-616): `/static/mvp-factory/release-guardian.html`, read-only on GitHub. Only `success` passes; skipped, neutral and «no checks» never count as success. In the registry the pilot starts at `idea`; you move its stages |

## The V1 → V2 improvement cycle (#270)

Module `mvp_evolution.py`, page `static/mvp-factory/evolution.html`. It never changes a project's stage.

1. Feedback is stored only with explicit consent. The participant's name is not stored, only a hash.
2. The first cohort target is 10 real, substantive feedback records; the next is 100. Demo data is marked and never counted.
3. Feedback is grouped into themes: how many people support it, what speaks against it, and confidence (fewer than 3 people means «insufficient»).
4. A V2 proposal cites specific feedback and carries an acceptance test. Only you approve or decline it.
5. The hand-off to the builder creates exactly one Relay ticket. «Shipped» requires a link to a merged PR or commit.
6. You release V2, then the original participants retest the new version.

Not built yet: contracts for the 13 roles (T-631), builder-side claiming through Relay events (T-632), in-product usage events (T-633).

## A/B experiments

Built (T-608–T-610, #348): a project can hold an experiment with exactly two branches, A on top and B below.

- `SEGMENT_COMPARISON` mode compares audiences and **never declares a winner**. `CONTROLLED_AB` is draft-only for now: there is no random assignment.
- You approve each branch's preview. A button creates one Content Factory draft per branch, with no publishing.
- No metrics, spending or outreach are written here. You choose the outcome: `continue_a`, `continue_b`, `both`, `iterate`, `pivot` or `stop`.

## What you do

- Approve the spec before a build and set the final verdict.
- Contact people yourself: FactoryOS sends nothing to anyone.
- Approve V2 proposals and the release of a new version.

## Where to look

- Menu → **MVP Builder** → **Projects**: project rows and a button that opens the MVP Factory page (`/static/mvp-factory/index.html`).
- On a project card: the preview link, «Product Evolution · V1→V2», and for #189 «AI Release Guardian».
- Your tasks: Worker Center → «Your tasks».

## Limits

- No full run of «spec → PR → CI → preview → your decision» has happened yet.
- Nothing is published, spends money or leaves the system without your approval.
- The registry never starts workers itself: the Relay queue is the only executor.
