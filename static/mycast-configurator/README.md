# MyCast configurator prototype (#261)

A static page: the listener picks topics, region, schedule, voice and delivery. They hear a labelled demo, review it and approve the profile. It is a prototype. Nothing is generated, scheduled, sent or published, and no paid API is called.

Open `index.html` in a browser. No server is needed.

| File | Role |
|---|---|
| `configurator.js` | Logic as a UMD module with no DOM: taxonomy (8 categories, 81 subtopics, EN/UK/RU labels), validation, state machine, preview rules, profile JSON. |
| `index.html` | UK/RU/EN UI. The draft is kept in `localStorage`; reads and writes are wrapped so a blocked storage still renders. |
| `spec.json` | Machine-readable contract: ids, limits, states, channel rules. |
| `test_configurator.js` | 11 deterministic node tests, run in CI. |

## Honesty rules (from the issue)
- No audio available: no preview, and the state stays `draft`.
- Browser speech is a **demo**, labelled `demo_not_ai_episode`. It never counts as an AI episode and cannot be downloaded.
- Download only exists for a real local audio file. Telegram and email show "not connected".
- Approval needs a preview, a review step and an explicit checkbox. Any later edit drops the profile back to `draft`. The exported JSON always has `active: false`.

## QA (2026-11-05)
- `node static/mycast-configurator/test_configurator.js` → 11/11 pass.
- Headless Chromium at 390×844 and 1440×900: 0 page errors, no horizontal overflow, 82 checkboxes rendered.
- Flow draft → preview (browser speech) → reviewed → approved: state `approved`, `active: false`, Download stays disabled.
- If `speechSynthesis.speak` throws, the status says playback stopped and the UI does not hang.

## Not done here
- Integration into the dashboard sidebar (`static/index.html`) waits for PR #194, which edits the same file.
- `docs/prototypes/mycast/` belongs to #107 and is untouched.
- Real generation, scheduling and Telegram/email delivery are separate tasks that need owner approval.
