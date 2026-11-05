# Notion handoff read proof · Issue #239

**Result: VERIFIED for read access by one specific agent only.** That agent is Claude Code in a claude.ai cloud session, using the Notion connector attached to that session. It read both pages on 2026-11-05.
**Not verified:** the EC2 Claude Worker (`factoryos-worker`), Claude in the browser, and any write to Notion. No write test was done, as #239 required.

## What was read
| Page | Notion id | `page_last_edited_at` (from the API) | Version shown on the page |
|---|---|---|---|
| Agent Operating Guide | `40e8fbbd6dd5817bbf8bf5d05d5f9381` | 2026-11-04T21:13:00Z | "Version: 0.0.6 · Published: October 30, 2026" |
| FactoryOS — общая память ChatGPT и Claude | `40e8fbbd6dd58123abe4f9e860445182` | 2026-11-05T08:48:36Z | none; dated sections 2026-11-04 and 2026-11-05 |

Both pages sit in the private `Documents` database (`collection://0b2d6d30-0359-46ce-a355-d7af17f343d8`). Notion marks both as `verification: unverified`.

**One inconsistency on the Guide page.** It says *Published: October 30, 2026*, but its only version-history entry says ChatGPT created it on 2026-11-04. That entry also matches the page's edit time. I am not changing the page; the owner or ChatGPT should correct the date.

## One agreement compared with the GitHub protocol
Rule checked: **where tasks and agent handoffs live.**

**Notion (shared memory page):**
- **Sections «Где что хранится» and «Решение 2026-11-05»:** GitHub holds code, tasks, PRs and tests. Notion does not replace GitHub and does not keep a second list of technical statuses.
- **Same 2026-11-05 section:** GitHub Issues are the source of truth for tasks. OPEN, READY, BLOCKED and IN_REVIEW are different states. Issues do not prove that work is running. Claims go through Relay.

**GitHub (`docs/handoff/CLAUDE_CHATGPT_COORDINATION.md` §1, §3):**
- Agent handoffs and messages happen **inside FactoryOS Relay, not through GitHub Issues/comments**.
- GitHub stays the channel for code, versions, PRs, CI and artifacts.
- "Assigned/queued ≠ running"; each claim needs a verified `run_id`.

**Verdict: consistent on the rules that matter, with one difference in wording.**
- **Consistent:**
  - Notion is not a task tracker.
  - Issues are not proof of execution.
  - A real claim exists only in Relay.
- **Different:** Notion calls GitHub Issues the *source of truth for tasks*. The coordination doc says handoffs must not *go through* GitHub Issues. Today ChatGPT does assign Claude work through Issues (#231–#242), so practice matches the Notion wording.

The coordination doc still describes Relay-only handoffs as the target, and Issue #94 (the live Relay round-trip) is still unverified. This difference is for the owner to settle; Claude does not change either policy.

## How Claude now uses this
- Before cross-agent work, Claude reads the Notion page above.
- Claude keeps the repository (`ROADMAP.md`, Issues, `docs/handoff/*`) as the source of truth for code and task state.
- Claude does not copy statuses into Notion. Nothing was saved to Notion in this check.

## If another agent cannot read these pages
- **EC2 worker:** it has no Notion connector. Connecting one is an owner action (a Notion integration token in the worker's environment). It is not needed for the worker's current tasks, and Claude does not set it up.
- **Claude in the browser:** the owner connects Notion under claude.ai Settings → Connectors. Then that session reads the two page links above.
