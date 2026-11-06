# MyCast configurator prototype (#261)

The first MVP Factory pilot (#186). On this page a listener picks topics, a region, a watch list, a voice, a schedule and a delivery channel. Then they hear a labelled demo, review it and approve the profile.

It is a prototype. Nothing is generated, scheduled, sent or published, and no paid API is called. The page makes no network requests.

To open it, use the sidebar on the site (**MVP Factory → MyCast podcast**), go to `/static/mycast-configurator/index.html`, or open `index.html` locally. No server is needed.

| File | Role (builder) |
|---|---|
| `spec.json` | **Product Strategist**: the machine-readable contract (ids, limits, states, channel rules). |
| `configurator.js` | Logic as a UMD module with no DOM: a taxonomy of 10 categories and 93 subtopics labelled in EN/UK/RU, validation, the watch list, honest channel states, the state machine, and the profile JSON. |
| `index.html` | **Web Builder**: the UK/RU/EN UI. It has an aurora hero with a pipeline simulation, the three-builder section, nested topics with search, region and watch list, voice and schedule, delivery, the player, approval, and a sticky "podcast DNA" card with generated SVG cover art. |
| `test_configurator.js` | **QA & Launch**: 14 deterministic node tests, run in CI. |

## Honesty rules (from the issue)
- With no audio available there is no preview, and the state stays `draft`.
- Browser speech is a **demo**, labelled `demo_not_ai_episode`. It never counts as an AI episode and cannot be downloaded.
- The waveform moves only between the speech engine's real `start` and `end` events.
- Telegram is the main channel and can be chosen in a draft, but it is always shown as "not connected". Nothing is ever shown as delivered.
- Viber, WhatsApp and email are visible as "planned" and cannot be chosen.
- Download exists only for a real local audio file.
- Approval needs a preview, a review step and an explicit checkbox. Any later edit, including a watch-list change, drops the profile back to `draft`. The exported JSON always has `active: false`.
- The hero animation is labelled as a simulation. The Scout, Researcher, Editor and Voice agents are not running.
- Motion respects `prefers-reduced-motion` (the SVG animations are paused and nothing drifts) and slows down on low-power or data-saver devices.

## QA (2026-11-06)
- `node static/mycast-configurator/test_configurator.js`: 14/14 pass.
- Headless Chromium at 390×844 and 1440×900:
  - 0 page errors and no horizontal overflow;
  - 3 topics picked, including the new Food category;
  - 2 watch-list items added, one with Enter and one with the button;
  - Viber's radio is disabled and Telegram is selected;
  - the flow ends `approved` with `active: false`, and the delivery status reads `not_connected`.
- Reduced motion: the `calm` class is applied and the SVG animations report as paused.

## Not done here
- `docs/prototypes/mycast/` belongs to #107 and was not touched.
- Real generation, scheduling and Telegram delivery are separate tasks. They need the owner's approval, a connected bot, consent and an end-to-end test.
