# AI Business League: Claude-directed trailer brief · Issue #213

**Status:** creative direction and zero-spend preflight only. **Nothing was generated**: no Higgsfield job, no trial credits, no paid API, no publishing. Every number in the film is a concept label, never a claim.
**For A/B:** this is Claude's version. ChatGPT's version uses the same target (55 s, 16:9 master, 9:16 cutdown) and is compared with the rubric at the end.

## 1. Director's treatment
**Title:** *What if AI had to build a real business?*
**Idea in one line:** the film is the opening credits of an experiment that has not started yet. It ends on a question, not a victory.

The film is shot as a **title sequence**. One continuous camera move travels through a dark sculptural space, and the type acts as architecture. The words are built from the same material as the set: slabs, extrusions and light passing through the letters. Two agent forms (amber and cyan, the same identity as AI Hangout concept A, #216) never meet. Every exchange between them travels on a single beam of light. The sculptures change role by changing shape:
- **Scout** is a lens.
- **Critic** is a blade.
- **Builder** is a lattice.
- **Analyst** is a set of rings.

The arc is curiosity → friction → test → humility → invitation. The honesty rules are part of the style. Mock data is printed with a **DEMO** stencil as a design element. The ending card says "A proposed experiment."

### Visual identity
- **Palette:** void black `#05060a`, warm amber `#ff8a3d`, cold cyan `#53e0ff`, a violet accent `#9b8cff` for "memory", and paper white `#f3f1ea` for type. One yellow `#ffd166` is reserved for the DEMO stencil only.
- **Type:** a heavy high-contrast serif for statements, with outline italics for the "what if" words, plus a mono face for data and DEMO labels. **All final type is composited, never generated** (see §4).
- **Materials:** smoked glass, brushed dark metal, light through dust. No faces, no humans, no robots, no logos of model providers.
- **Camera:** never static. Slow dolly and orbit, with one whip transition per act. 24 fps master.

## 2. Storyboard (55 s, 16:9 master)
| # | Time | Shot | Camera | On-screen text (composited) | Source |
|---|---|---|---|---|---|
| 1 | 0–6 | A monolith slab rises out of black water; light leaks through its seams. | Low push-in, tilting up the slab. | `WHAT IF` (outline) → `AI HAD TO BUILD` → `A REAL BUSINESS?` | Higgsfield **G1** + type |
| 2 | 6–12 | Two light forms ignite at opposite ends of a long dark hall; a beam snaps between them. | Fast dolly along the beam. | `TWO AGENTS. ONE MISSION.` | Higgsfield **G2** + type |
| 3 | 12–20 | Evidence cards fly along the beam and pile into a graph; one card cracks. | Orbit around the graph. | Cards: `HYPOTHESIS`, `EVIDENCE?`, `DEMO` stencil | Procedural (#220 renderer) |
| 4 | 20–30 | The forms morph into roles in rhythm: lens, blade, lattice, rings. | Four matched cuts on the beat, the camera keeps moving. | `SCOUT · CRITIC · BUILDER · ANALYST` | Higgsfield **G3** (one continuous morph) + labels |
| 5 | 30–40 | Loop sculpture: QUESTION → TEST → EVIDENCE → RETHINK as four rotating rings; a hypothesis is stamped `REJECTED`. | Push through the rings. | `$0 TEST` · `REJECTED` · `RETHINK` (DEMO data) | Procedural |
| 6 | 40–48 | Wide: ten small rooms light up across a dark landscape, each with two lights. | Crane up and back. | `10 TEAMS · $1,000 HYPOTHETICAL BUDGET · LEARN IN PUBLIC` · `FUTURE VISION` | Higgsfield **G4** + type |
| 7 | 48–55 | Lights dim, then a title lockup carved from the same slab as shot 1. | Slow pull-back to black. | `AI BUSINESS LEAGUE` / `BLACKBOX LAB` / `A proposed experiment.` | Procedural lockup |

**9:16 cutdown (30 s):** shots 1 (4 s), 2 (5 s), 4 (8 s), 5 (6 s) and 7 (7 s). Recompose rather than crop: forms stack vertically and the beam runs vertically. Type sits in the upper third, the bottom 20 % stays clear for platform UI, and every word is at least 6 % of frame height.

**Teaser hook (6 s, standalone):** shot 1 compressed. A black screen, then `WHAT IF`, then a hard cut on the downbeat to the slab rising with `AI HAD TO BUILD A REAL BUSINESS?`, then `AI BUSINESS LEAGUE · SOON` on a DEMO stencil.

## 3. Higgsfield prompt pack (short shots only; run only after approval)
Each prompt is one 5 s shot, 16:9, no text in frame. Text is always added in post. Negative prompts are listed because generators often draw unwanted letters, faces and logos.

**G1, monolith (5 s)**
> Cinematic title-sequence shot. A massive black monolith slab slowly rises out of still black water in a vast dark void. Thin lines of warm amber light leak through seams in the slab and scatter in floating dust. Slow low-angle push-in, camera tilting up along the slab, never static. Smoked glass and brushed dark metal, high contrast, volumetric light, 24 fps, anamorphic, film grain. No text, no letters, no people, no logos.
> Negative: text, letters, watermark, faces, humans, robots, logos, cartoon, low detail.

**G2, two lights and a beam (5 s)**
> A long dark hall of smoked glass walls. At the far left a sculptural amber light form ignites; at the far right a cold cyan light form ignites. A single thin beam of white light snaps between them and small glowing packets travel along it. Fast smooth dolly along the beam, slight orbit. Moody, cinematic, volumetric haze, reflections on a black floor, 24 fps. No text, no people, no logos.
> Negative: text, letters, faces, humans, robots, logos, explosions, fireworks.

**G3, role morph (5 s)**
> An abstract glowing amber sculpture continuously morphs: first into a glass lens, then a sharp blade, then an open metal lattice, then concentric rotating rings. Each change is smooth and physical, like liquid metal. Dark void background, rim light, dust in the air, camera slowly orbiting and never stopping. Cinematic, high contrast, 24 fps. No text, no people.
> Negative: text, letters, faces, humans, hands, robots, logos, cartoon.

**G4, ten rooms (5 s)**
> Aerial night shot over a dark minimalist landscape. Ten small glass pavilions light up one after another, each containing two tiny glowing lights, one amber and one cyan, connected by a thin beam. Camera cranes up and back slowly, revealing the grid of pavilions. Cinematic, volumetric fog, high contrast, 24 fps. No text, no people, no logos.
> Negative: text, letters, city lights, cars, faces, humans, logos.

## 4. Post-production (deterministic, $0)
- **Tools:** the #220 pipeline in `docs/prototypes/agent-hangout/video-pilot/` (canvas scenes → frames → ffmpeg). Remotion is an alternative if React-based timelines are preferred. Both are free and run locally or in CI.
- **Generated shots** come in as background plates (G1–G4). Exact type, cards, graphs, loops, DEMO stencils and the lockup are drawn on top in code. This keeps every word and number exact.
- **Grade:** lift blacks to `#05060a`, then a gentle teal-orange split matching the palette. Add a grain overlay of about 4 %.
- **Type animation:** words rise 0.4 em with a 60° X-rotation and a 1.1 s ease-out, offset by 0.18 s per word. That is the same curve as concept A, so the trailer and the product page match.
- **Export:** 1920×1080 at 24 fps, H.264 High, yuv420p, AAC 48 kHz, `+faststart`. The 9:16 version is 1080×1920. Verify both with ffprobe.

## 5. Sound and rhythm
- **Music:** original music only (composed or generated under a licence the owner approves later). Until then, temp tracks are not used.
- **Tempo:** 92 BPM, one beat every 0.65 s.
  - 0–12 s: pulse and drone.
  - 12–30 s: rising sequence. The role morphs land on beats 21–24.
  - 30–40 s: drop to a single low hit at `REJECTED`, a "humility" moment.
  - 40–55 s: wide pad, resolving into the title on a single chime.
- **Sound design:** a glass "ting" when the beam connects, a paper-flip for evidence cards, a low thud for stamps.

## 6. Higgsfield preflight (no generation)
- **This Claude session has no Higgsfield connector or MCP.** I searched the tools available here. Two other connected services can generate video: vidIQ (`vidiq_generate_video`, charged per second) and Canva (`create-video`). Both spend credits. Neither was called, and neither is Higgsfield.
- **ChatGPT's access does not carry over.** A Higgsfield subscription connected to ChatGPT does not give Claude access. To let Claude run it, the owner would connect Higgsfield to the Claude account as a connector (Settings → Connectors), if Higgsfield offers one. Running the prompts from ChatGPT's connected Higgsfield is also fine, because the prompts above are tool-neutral.

## 7. Cost estimate and approval checklist
The figures below come from the ChatGPT-side check (#213/#220) and are **not checked in Claude's account**: Kling v3.0, 5 s, 16:9 is about **10 credits**. The account shows 110 credits, including a trial that expires 2026-11-07.

| Plan | Shots | Takes | Estimated credits |
|---|---|---|---|
| Minimal | G1, G2 | 2 each | ~40 |
| Recommended | G1–G4 | 2 each | ~80 |
| Hook only | G1 | 3 | ~30 |

Everything else is procedural at $0. **Before any generation the owner confirms:**
1. which plan (minimal, recommended or hook only), or exact shots;
2. model and output (for example Kling v3.0, 5 s, 16:9, 1080p);
3. a hard credit cap (stop at that number even if a take is bad);
4. whether the trial credits may be used before they expire on 2026-11-07;
5. where the results may go (private review only; no public posting without a separate yes).

## 8. A/B comparison rubric (same brief, same 55 s target)
Score each from 1 to 5. The owner scores blind: versions are labelled X and Y, not by agent.

| Criterion | What 5 looks like |
|---|---|
| Legibility | Every word readable on a phone at first view; no generated letter artifacts. |
| Originality | Would not be mistaken for a stock template or another brand's ad. |
| Camera flow | The camera never stalls; cuts feel motivated by the beat. |
| Story clarity | A first-time viewer can say what the League is in one sentence. |
| Honesty | Future and mock elements are clearly labelled; no implied revenue or live agents. |
| Budget | Credits used against the cap; reuse of procedural shots. |
| Time | Hours from approval to a reviewable cut. |
