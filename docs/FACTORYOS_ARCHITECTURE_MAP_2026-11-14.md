# FactoryOS architecture map — as-is and proposed boundaries

**Date:** 2026-11-15 · **Owner:** ChatGPT · **Source issue:** [#367](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/367) · **Status:** architecture inventory / proposal, not an implementation or deployment claim.

## 1. Evidence vocabulary

- **Code inspected on main:** the linked source files below were read at the start of this document. This proves their *implementation exists in Git*, not that the corresponding production feature is healthy.
- **Documented contract:** a specification or code comment describes an intended rule; this is not independent live acceptance.
- **Partial:** some modules, UI, or APIs exist but the complete user-facing loop is not evidenced.
- **Unverified:** no correlated live request, worker claim/start/finish, response delivery, CI and deployed SHA were established by this document. Do not upgrade an item based on HTTP 200, a heartbeat, a PR URL, or a claimed test.

## 2. As-is inventory and ownership

| Boundary | Main-repository evidence | Present responsibility | Evidence level / limitation |
|---|---|---|---|
| HTTP/API integration and Telegram ingress | [app.py](../app.py) | FastAPI entrypoint, route wiring, environment-backed config, integrations and Telegram dispatch | Code inspected; large shared integration surface; runtime E2E unverified |
| Durable owner inbox | [relay.py](../relay.py) | File-backed RelayStore, owner tickets, Telegram/web presentation, intake | Code inspected; a ticket is not a worker claim |
| Exclusive task execution | [relay_execution.py](../relay_execution.py) | RelayQueue and recorded worker lifecycle; queued/claimed/running/finished states | Code inspected; historical event and run_id correlation needed for proof |
| Agent messaging | [relay_agent_messages.py](../relay_agent_messages.py), [PR #314](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/pull/314) | Proposed authenticated cross-agent messaging | PR remains a separate review surface; do not presume production bridge |
| MVP registry | [mvp_factory.py](../mvp_factory.py) | Durable projects, stage transitions, idempotency and evidence-link shape checks | Code inspected; link shape is not proof of outcome |
| MVP handoffs/artifacts | [mvp_pipeline.py](../mvp_pipeline.py), [MVP Factory spec](MVP_FACTORY_SPEC.md) | Research/spec artifacts and gated handoffs; Relay remains sole executor | Partial; no complete pilot E2E established |
| MVP Builder offline contracts | [mvp_builder_request.py](../mvp_builder_request.py), [mvp_builder_preflight.py](../mvp_builder_preflight.py), [mvp_builder_manifest.py](../mvp_builder_manifest.py), [mvp_builder_projection.py](../mvp_builder_projection.py) | Validation, preflight, QA manifest and truthful projection | Documented by spec; offline validators do not claim tasks |
| MyCast product | [mycast.py](../mycast.py), [mycast_accounts.py](../mycast_accounts.py) | Voice generation, listener/account and delivery paths | Code referenced by app.py; consent, real delivery and cost gates require live verification |
| Content production | [app.py](../app.py) and existing Content Factory integrations | Draft and approved content workflows | Do not infer a standalone bounded Content Factory module from the name; publishing always needs approval |
| Existing Claude worker | [ROADMAP.md](../ROADMAP.md), [Issue #61](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/61) | Existing EC2 worker via authenticated Relay/Supervisor | Remote EC2/SSM/Supervisor and end-to-end Telegram delivery **not verified** here |

The [coordination protocol](handoff/CLAUDE_CHATGPT_COORDINATION.md) is explicitly a **draft**, not proof that authenticated ChatGPT↔Claude inbox handoff works. [AGENTS.md](../AGENTS.md) prohibits parallel ownership, direct main writes and unauthorized live actions. [TEAM_PLAN](handoff/TEAM_PLAN_2026-11-06.md) is dated; its historical status is not a live snapshot.

## 3. As-is control flow (conceptual, not an E2E claim)

```text
Owner / Telegram / Web / GitHub Issue
                |
                v
        FastAPI app.py
          |           \
          v            v
      RelayStore     MVP registry / product-specific stores
          |
          v
      RelayQueue  <---- worker claim / lifecycle events
          |
          v
      Existing Claude worker (EC2; remote state unverified)
          |
          +----> branch / commit / PR / CI (verify at GitHub)
          |
          +----> Telegram response (delivery evidence required)
```

**Single dispatcher:** only RelayQueue may authorize execution/claims. An MVP stage, a GitHub issue, a browser task or a Paperclip-like external dashboard must not become a competing execution queue.

## 4. Proposed boundaries (no refactor authorized by this document)

```text
                        FactoryOS platform
      Identity / owner gates / approvals / evidence / audit
                              |
                Canonical Project-Task-Run contracts
                              |
                ONE Relay queue and claim authority
                 /                  |               \
           MVP Factory         Content Factory     Agent Office
                 |                  |               |
           product specs       draft campaigns     factual projections
                 \                  |              /
                  Independent products (MyCast, etc.)
                         only via scoped adapters
```

**Platform** owns identity, task ownership, idempotency, durable execution events, cost/publishing approval and evidence provenance. **Factory engines** own domain-specific planning and artifacts but never their own worker claims. **Products** own domain data, user-facing delivery and explicit consent; they should consume platform contracts through narrow adapters instead of importing arbitrary `app.py` internals.

### Minimal conceptual contract

| Object | Minimal fields | Authority / invariant |
|---|---|---|
| Project | `project_id`, owner, spec URL, approval state | Product/MVP registry; no implicit build approval |
| Task | `task_id`, `project_id`, Owner, Depends, files_scope, acceptance, cost ceiling, idempotency key | Approved planner or owner; Relay admission validates gates |
| Run | `run_id`, `task_id`, claim lease, worker identity, lifecycle timestamps | **Relay only**; at most one active eligible claim for task/scope |
| Artifact | `artifact_id`, `run_id`, type, immutable reference/hash | Producer writes; consumers cannot treat a link as verification |
| Evidence | `evidence_id`, source, subject, observed timestamp, verifier, status | External verification (GitHub CI, Render deploy, Telegram delivery) must be correlated, not inferred |
| Approval | approver, action, scope, decision, timestamp | Human owner for spending, publishing, deployment and product acceptance |
| Outcome | result, linked verified evidence, accepted_by, timestamp | Derived from independently verified facts and owner acceptance; never from an LLM assertion alone |

Example chain: `project:mycast → issue:#N → relay:R-N → run:run-N → PR/CI → verified deployment → owner approval → accepted outcome`. **These IDs are illustrative placeholders**, not real execution evidence. Store the canonical ID mapping once; projections must read it rather than inventing new IDs.

## 5. Coupling and failure risks

1. **Monolithic app.py:** many unrelated integrations share one file and deployment. PR #314 currently touches it; [#369](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/369) also scopes it. Avoid concurrent edits until scopes are coordinated.
2. **Multiple file-backed stores:** RelayStore, MVP registry, artifact and product stores have separate durability/idempotency boundaries. Cross-store operations need an explicit reconciliation contract; never assume atomic multi-store commits.
3. **Claim ambiguity:** GitHub Issue creation, Relay intake and a worker heartbeat are not a successful claim. Enforce task/scope exclusivity and report stale/unknown leases as unknown, not free.
4. **Auth and consent:** owner-only APIs, Telegram pairing, listener consent and publication gates differ by product. Do not flatten them into one permissive shared token.
5. **Extraction risk:** moving MyCast or MVP Factory before dependency mapping can break `app.py` imports, route authentication, event IDs and persistent storage paths.
6. **Evidence laundering:** a URL that matches a regex or a successful Render deploy does not prove a user received a Telegram reply.

## 6. Safe incremental sequence for Claude's independent review

1. **Read-only dependency map:** list imports, routes, stores, write boundaries and PR overlaps from main; classify implemented/partial/unknown. No infrastructure access or secrets needed.
2. **Contract-only review:** independently validate the Project→Task→Run→Artifact→Evidence→Approval→Outcome model, identity and versioning; map it to current Relay records before adding adapters.
3. **Offline adapters and tests:** test one MVP task projection and one product artifact through a fake Relay with duplicate events, stale claims, owner mismatch, unavailable CI and denied approval. Feature flag OFF by default.
4. **Small reviewed PRs:** isolate domain adapters one at a time with existing CI and reviewer approval. No changes to live `autopilot/`, worker scheduler, production credentials, or paid resources.
5. **Live acceptance only by separate owner gate:** require one correlated real `run_id`, claimed/running/finished events, Telegram delivery receipt, relevant green CI and matching deployed SHA. If any evidence is missing, status remains partial/unverified.

## 7. Explicit non-goals and verification checklist

This document **does not** prove #41/#61/T-590/T-591 E2E, restore an EC2 timer, assign Claude, create an MVP, merge code or publish content. It proposes no new cloud service, dispatcher, billing or authorization bypass.

Review checklist: compare every linked path against current main; verify no overlapping active PR before implementation; run deterministic tests for any later code change; check GitHub CI on the *exact PR head* (absence of PR-triggered runs is not green); correlate worker events with a single `run_id`; confirm actual Telegram delivery and Render SHA independently; obtain owner approval before deploy/publish/spend.
