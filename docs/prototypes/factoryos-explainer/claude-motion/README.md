# FactoryOS: cinematic motion explainer (Claude variant, #353)

This is a 75-second playable HTML story. It follows one task through FactoryOS from the owner's question to an evidence-based decision. The story covers:
- AI debate, product spec, build/QA, Relay and Agent Office;
- two independent A/B branches, each with its own owner-gated promotion;
- the learning loop;
- a final pull-back over the whole system.

Shot list, narration and claim check: [STORYBOARD.md](STORYBOARD.md).

## Run

Open `index.html` in a browser. It is one self-contained file with no build step and no server.

- Plays automatically on open. There is no sound.
- Controls:
  - **Play/Pause**: <kbd>Space</kbd>;
  - **Restart**;
  - **Back/Next scene**: <kbd>←</kbd>/<kbd>→</kbd>;
  - **Home**: jumps to the start;
  - the timeline scrubber;
  - the 9-scene navigator;
  - the RU/UK/EN switch;
  - «Меньше движения» (reduce motion).
- URL parameters for review and screenshots:
  - `?t=42` opens paused at second 42;
  - `&lang=en`;
  - `&reduced=1`;
  - `?paused=1` opens at 0 without autoplay.
- Test hook: `window.explainer` with `seek(t)`, `play()`, `pause()`, `goScene(i)`, `state()`.

## How it works

- **Timeline.** Every frame is a pure function of the time `t`. This covers the camera `viewBox`, every element's opacity, link drawing and the packet positions. Because of this:
  - pause freezes the picture exactly;
  - resume, seeking and scene jumps always show the same frame for the same `t`;
  - restart resets everything.
- **Camera.** Keyframes in `CAM` set the camera position and view width. Zoom is interpolated in log space with cubic easing.
  - The subject is framed above the caption band.
  - Portrait screens get a tighter frame and a 3-column scene navigator.
- **Packet.** Waypoints are listed in `MAIN`, `BR(600)` (A), `BR(1400)` (B) and `DEC`.

## Browser support and performance

- Built on SVG, CSS and `requestAnimationFrame`: no canvas, WebGL, libraries or fonts to download.
- Checked in headless Chromium (Playwright) at 1440×900 and 390×844:
  - no JavaScript errors;
  - no requests outside the file;
  - no horizontal overflow.
- Should work in any current Chrome, Edge, Firefox or Safari.
- The world is about 200 SVG nodes, so it runs comfortably at 60 fps on a laptop.

## Accessibility

- `prefers-reduced-motion` is respected; it can also be toggled with «Меньше движения».
- In reduced mode:
  - the camera cuts to each shot's settled framing;
  - packets step between waypoints instead of gliding;
  - the monitor push becomes a cut.
- Captions sit in an `aria-live` region. The stage's `aria-label` carries the current scene text.
- All controls are real buttons with visible keyboard focus. Text on dark backgrounds meets contrast requirements.

## Zero cost and rights

- No paid services, API keys, network calls, analytics, stock media, music, external fonts or logos.
- All shapes, icons and animation are original code in this folder.
- Brand names (Facebook, TikTok, GitHub, Notion) appear only as plain-text channel labels.
- The film contains no real user data and no metric values.

## Optional MP4 export (not done here)

No video file is included. Nothing below has been rendered or verified.

A no-cost way to make one:
1. Step `explainer.seek(i / 30)` for `i = 0..2250` in headless Chromium.
2. Save a screenshot per frame at 1920×1080.
3. Encode with `ffmpeg -framerate 30 -i f%05d.png -c:v libx264 -pix_fmt yuv420p out.mp4`.

Before calling the MP4 done, check it with `ffprobe`.

## Evidence

The `screenshots/` folder holds desktop frames at 1440×900 for every shot, plus the monitor push, and mobile frames at 390×844 for 5 shots.
