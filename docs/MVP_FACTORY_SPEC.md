# MVP Factory — implementation contract (Issue #186)

Owner: ChatGPT (this specification and prototype); Builder: Claude (subsequent integration only after explicit handoff). Depends: existing Agent Office, Relay, CI. Status: SPEC + STATIC PROTOTYPE, NOT LIVE.

## Position in FactoryOS
Render a separate **MVP Factory** section below Agent Office, visually distinct from **Content Factory**. Do not create a second autonomous scheduler. Reuse existing Relay events, worker identities, approvals, GitHub Issue/PR links and audit trail.

## Roles and handoffs
1. **MVP Manager** (orchestrator, not a new LLM subscription): owns queue and status, chooses next eligible task, records evidence.
2. **Product Analyst / Spec Writer**: turns idea into problem, buyer, offer, scope, success metric, dependencies, 24–72-hour validation experiment.
3. **Claude Builder**: assigned only after spec approved, codes a web preview on an isolated branch and opens a draft PR. No duplicate worker ownership.
4. **QA / Security**: independently reviews tests, secrets, route permissions and readiness. Missing CI is BLOCKED, not green.
5. **Deploy Agent**: proposes preview on existing free infrastructure; no new cloud resources or public deploy without owner approval.
6. **Content Factory**: receives a marketing brief only after preview review and owner approval; never automatically publishes.

## State machine
idea -> researching -> spec_draft -> spec_review -> build_queued -> building -> qa_review -> preview_ready -> owner_review -> validated | rejected.
blocked can be entered from any nonterminal state with reason, timestamp and source.
Do not advance state on an LLM assertion; require a concrete evidence link or approved action. Unknown is not complete.

## Minimum data contract
```json
{
  "id":"mvp-187",
  "title":"AI Decision Memory",
  "issue":187,
  "stage":"idea",
  "owner":"MVP Manager",
  "builder":"Claude (not yet assigned)",
  "depends_on":[186],
  "status_source":"GitHub Issue #187",
  "updated_at":null,
  "evidence":[],
  "cost_usd":0,
  "approval":{"deploy":false,"outreach":false,"publish":false}
}
```
Never present static seed data as live telemetry. Link to original issues. No credentials in artifacts.

## Pilot backlog
- #187 AI Decision Memory: decision, evidence, owner, expected outcome, follow-up.
- #188 MyBrief for a profession: 3 audience examples, sourced briefings, consent-based feedback.
- #189 AI Release Guardian: GitHub PR check-run status; skipped/no jobs != passing.

## Acceptance / checks
- UI panel displays three pilots and clearly labels seed/demo status.
- Separate from Content Factory and Agent Office; EN/UK/RU localization when integrated.
- Click through to canonical GitHub Issues; no fake timers, token use or worker heartbeat.
- One real pilot demonstrates spec -> code PR -> CI -> reviewed preview -> owner decision.
- Security and CI stay mandatory. No spending, messages, publication, or infrastructure changes without approval.

## Build order
A. Static prototype in `static/mvp-factory-preview.html` (this PR).
B. Claude review and integrate panel with existing dashboard under a separate follow-up issue, respecting current ownership and active PRs.
C. Wire actual Relay/GitHub data; unit/smoke/locale tests; no fabricated progress.
D. End-to-end pilot #189 or #187, then optional Content Factory handoff.
