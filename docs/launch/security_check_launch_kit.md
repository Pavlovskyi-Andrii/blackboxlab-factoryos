# Blackbox Lab Security Check — international launch drafts

**Issue:** #102 · **State:** DRAFT/NOT PUBLISHED · 2026-11-03. Linked to #101 (scope and consent) and #114 (owned code audit). No company has consented to a review or been contacted by this work. Do not use this as a ledger of real customers.

## Landing page (English, private draft)

**Headline:** A clearer security picture before you ship.

**Subheadline:** A limited, consent-based code and configuration review for indie SaaS teams. Find out which source-level security risks deserve attention—without a production pentest or a promise of complete coverage.

**What we review:** mutually agreed code snapshot and dependency manifests; access-control paths, misconfiguration patterns, supply-chain warnings and accidental secret exposure with safe redaction. We triage reported issues, distinguish checked evidence from suspicions and suggest prioritized next steps.

**You receive:** a concise confidential report with summary, affected file areas/line ranges where safe, confirmed vs suspected findings, limitations and remediation priorities. This is **not** a penetration test, security certification or guarantee of safety.

**Pilot call to action (not wired to real collection):** “Ask for the free pilot scope.” A later **$99 introductory offer is a pricing hypothesis** pending demonstrated fulfilment and legal/payment readiness.

**Consent & privacy notice:** Never send keys or passwords. We access only explicitly authorized repositories/commits, read-only, within a documented time window. No production scans. We do not submit client code to external AI services without separate written, provider-specific consent. Retention and deletion dates must be agreed and operationally verified before engagement.

## Public social copy — drafts only

**Bio, LinkedIn:** Blackbox Lab builds practical AI-powered engineering tools. Our AI Security Check pilot explores permission-based, read-only code reviews for small software teams: transparent limitations, actionable priorities, no security theatre. Contact only after the owner approves a channel.

**Facebook page about:** Build with AI. Ship with evidence. We test pragmatic, tightly scoped workflows for engineering, security review and personalized information tools. Private pilot concepts, no certifications or client case studies claimed.

**Post 1 — authentication reality:** “A route-level guard can be correct while an earlier middleware check blocks the real worker—or lets a caller through unexpectedly. Source review should examine *both*. Our demo uses a repository we control; it is not a scan of anyone else’s system. #SecurityEngineering”

**Post 2 — finding or hypothesis?:** “An automated scanner finding is a lead for investigation, not proof. A useful report labels ‘verified’, ‘suspected’ and ‘not checked’, explains impact, and points to a safer next step. That’s the standard we’re prototyping at Blackbox Lab. #BuildInPublic”

## 30-second welcome video storyboard — script only, NOT rendered

| Time | Visual | Spoken English / subtitles |
|---|---|---|
| 0–5 s | Original motion graphic: small app launch screen; no customer logos | “Your app is almost ready to launch.” |
| 5–11 s | Animated code snapshot; highlighted ‘permissions’ / ‘dependencies’ | “But did you check the parts of the code that can put users at risk?” |
| 11–19 s | Redacted, fictional example report: ‘checked’ versus ‘needs review’ | “Blackbox Lab is piloting a focused, permission-based source review—with clear evidence and limits.” |
| 19–25 s | Three simple steps: agree scope → read-only review → prioritized report | “We touch only what you authorize. No production hacking. No blanket guarantees.” |
| 25–30 s | Generic brand title, inactive CTA | “Want to see the pilot scope? Ask for the sample report.” |

Production rule: use original or appropriately licensed assets only; synthetic voice, if added, must be disclosed and rights checked. This is a storyboard, **not a playable video**.

## Independent-auditor rubric (only after authorized opt-in)

1. Freeze consented repo/commit, tools and safe data boundaries. Never export private source/code excerpts into a model without provider-specific written opt-in and verified billing conditions.
2. Produce one deterministic static evidence baseline; redact tokens. Record tool, version, rule licence and timestamps.
3. Run each **authorized** independent reviewer on the same sanitized context and rubric without sharing other reviewer conclusions; do not invent unavailable reviewers.
4. Require finding ID, category, source pointer, supporting non-exploit observation, estimated severity, confidence, fix and unknowns. De-duplicate by exact file/line/issue class.
5. Human-triage substantial claims; disagreements remain visible. Only verified facts reach client ‘confirmed’ section. Never advertise three-model coverage when fewer actually ran.

## Approval checkpoints

Owner must approve: chosen 10 recipients and draft messages, sending channel/sender, actual landing/video/social publication, legal scope, licence rights, model/code-transfer permissions, any use-based costs and any real client access. **No sending, scraping, production testing, account creation or billing has occurred.**

## Draft acquisition funnel

Candidate (uncontacted) → outreach approved → contacted (with evidence) → replied/opt-in → authorized scope → limited review → report delivered → feedback → optional paid offer → actual receipt. In the absence of evidence, stay at candidate.
