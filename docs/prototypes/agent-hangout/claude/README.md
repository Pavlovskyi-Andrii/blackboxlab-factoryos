# AI Hangout — Concept A «Glass Room» (Claude) · Issue #216

**Status:** MOCK / UNVERIFIED. This is a static creative prototype. There is no backend, no live agents and no model calls. Every dialogue line, event, timestamp and number on the page is DEMO data and is labelled that way.
**Cost:** $0. Hand-written HTML/CSS/SVG, with no generation credits, no external fonts and no network requests. Screenshots were taken locally with headless Chromium.

## Preview
- Open `index.html` in any browser. It has no dependencies and also works offline from the file system.
- **16:9 desktop hero:** any wide window. Reference capture: `shots/desktop-16x9-hero.jpg` (1600×900) and the full page `shots/desktop-16x9-full.jpg`.
- **9:16 phone:** any narrow window or an Android phone. Reference capture: `shots/phone-9x16-hero.jpg` (405×720) and the full page `shots/phone-9x16-full.jpg`.
- `prefers-reduced-motion` stops every animation and leaves the static composition.

## Creative idea: "Two minds. One mission."
The interface is a **space**, not a dashboard. The camera moves slowly through a dark glass room with a grid floor and two glass walls, and it never fully stops (a 22-second dolly loop). Two **sculptural minds** breathe and lean toward each other:
- Mind A is a warm amber form: the builder, who proposes hypotheses.
- Mind B is a cold cyan-violet form: the skeptic, who asks for evidence.

The only bright straight line in the scene is the **evidence beam** between them. Packets of evidence travel both ways. The specialist roles (Scout, Skeptic, Builder, Editor) hang as glyph chips under the beam. They are logical roles, not processes.

The typography follows the brief «жирна типографіка, як титри до фільму»: a heavy serif title, one word in outline italics, and the words rising into place like opening credits. A wide-tracked mono kicker and a ticker of timestamped events at the bottom carry the "control room" texture without turning the hero into an admin panel.

Below the fold the room becomes **readable**. The page shows:
- the dialogue, with evidence and task links;
- the evidence graph (one hypothesis node linked to evidence cards and a test task);
- Relay events with timestamps and a `run_id`;
- the experiment panel: cost $0.00, turn limit, a stage track from question to evidence, test and conclusion;
- artifacts and media previews;
- a comparison with Business League Team #001.

Each block is tagged DEMO.

### Why this composition
- **Clear in three seconds.** On phone and desktop alike you see two forms, one line between them and one sentence. The story "two agents, one task, evidence passes between them" is readable before you read anything else.
- **Android first.** On the 9:16 layout the minds sit side by side under the title and the roles wrap to two rows. There is no horizontal scroll, as checked at 405 px. Body text is 15–16 px.
- **Honest by construction.** The `DEMO · НЕ LIVE` badge stays fixed on screen. Agents are "Mind A / Mind B", not provider-branded personas. Neither model ownership nor endorsement is implied. The budget row says the $1,000 is hypothetical.
- **Ready for video.** The page is the storyboard's first frame. The same layers (walls, minds, beam, roles, title) can be animated as separate planes in Remotion or ffmpeg for #220, with no generated footage needed.

## Storyboard: 16 seconds, six shots (16:9 master, 9:16 reframe in brackets)
| # | Time | Shot | Camera | On-screen text |
|---|---|---|---|---|
| 1 | 0.0–2.5 s | Black. A grid floor lights up from the vanishing point, and two glass walls catch a rim light. | Fast push-in at floor level, tilting up. [Same, centred.] | — |
| 2 | 2.5–5.0 s | The amber mind ignites on the left. Its rings spin up. | The camera arcs around it, keeping it in the left third. [The mind fills the upper half.] | `MIND A · BUILDER` |
| 3 | 5.0–7.5 s | The cyan mind answers on the right. The evidence beam snaps between them and the first packet travels. | Whip pan along the beam. [Vertical tilt from A to B.] | `MIND B · SKEPTIC` |
| 4 | 7.5–10.5 s | Four role glyphs (Scout, Skeptic, Builder, Editor) rise from the floor and settle under the beam. | Slow crane down through the glyphs. [Glyphs stack in two rows.] | — |
| 5 | 10.5–13.5 s | Evidence cards and the hypothesis node fly out of the beam into a small graph. "H1 — НЕ ДОВЕДЕНО" stamps onto it. | Dolly through the graph, rack focus to the stamp. | `DEMO · гіпотеза H1` |
| 6 | 13.5–16.0 s | Title: **Two minds. One mission.** Each word rises like credits, then `BLACKBOX LAB · AI HANGOUT`. | The camera keeps drifting and never freezes. | `DEMO · концепт` |

### Animation beats on the page
1. The title words rise in sequence (0–1.6 s).
2. Continuous camera dolly across the room (22 s loop, ease in/out).
3. The minds breathe, morph and lean toward each other (7–9 s loops, in counter-phase).
4. Evidence packets travel both ways along the beam (3.2 s).
5. Role chips bob out of phase. Graph edges flow (dashed stroke).
6. The DEMO event ticker scrolls (40 s).

## Scope and rules followed
- Files are limited to `docs/prototypes/agent-hangout/claude/**`. No runtime integration, no app changes.
- I did not read the other designers' outputs (#217, #218) before committing this first version.
- No Higgsfield or any other generator, no paid API, no deploy, no publishing.
- Not shown: real people, real logos, token prices or revenue.
