# AI Hangout video pilot · Issue #220

These are two private test videos with **$0 incremental cost**. Both are drawn frame by frame from code (HTML canvas in headless Chromium) and encoded with ffmpeg. No generator credits, no Higgsfield job, no paid API, no deployment, no publishing.

## Where to watch
- A **private Claude artifact** (owner-only until the owner shares it) shows all three files with posters and the comparison sheet: https://claude.ai/artifact/JnhhBYpY6mXSJ9xBev7URd
- Locally, `./render.sh` rebuilds everything into `out/` (gitignored), including `out/index.html`. MP4s are not committed to git: they are reproducible build outputs.

## The two hypotheses
| | A · cinematic teaser | B · audio-reactive podcast scene |
|---|---|---|
| File | `teaser_a_16x9.mp4` | `podcast_b_16x9.mp4`, `podcast_b_9x16.mp4` |
| Length | 10.0 s | 17.0 s |
| Video | 1280×720, 30 fps, H.264 High, yuv420p | 1280×720 and 720×1280, 30 fps, H.264 High |
| Audio | AAC silent track | AAC 44.1 kHz mono, peak −0.5 dB, mean −17.1 dB |
| faststart | yes | yes |
| Size | 2.75 MB | 4.05 MB / 3.74 MB |

All values come from `ffprobe` (`out/probe.txt`) and `volumedetect` on the rendered files.

- **A** shows particle tori as two "minds", amber and cyan, above a grid floor. The camera keeps moving and never freezes. An evidence beam connects the minds with packets flowing both ways. The title "Two minds. One mission." is kinetic serif type, ending on an AI HANGOUT lockup. A permanent `DEMO · CONCEPT` label stays on screen.
- **B** shows two abstract crystal hosts, clearly not people. Their mouth bars are driven by the **measured loudness** of the real audio. The "ГОВОРИТЬ" indicator and the speaker glow follow **measured speaker timing**. The scene also has a rolling waveform coloured by speaker, word-exact captions and DEMO evidence cards.

## Audio source and timing (B)
- **Audio.** The audio is `docs/prototypes/mycast/audio/2026-11-02.mp3`, the MyCast pilot already committed to this repository, with synthetic Piper voices. The clip is 0.9 s to 17.9 s. No Telegram media or credentials were used.
- **Timing.** `prepare_audio.py` runs `ffmpeg silencedetect`, then maps the script's sentences, in order with their host, onto the detected speech intervals. For this clip, 5 of 5 sentences matched (`timing: measured`). If counts ever disagree, timing is spread by sentence length and labelled `estimated`.
- **Gemini voices.** The owner preferred the Gemini voices (#215). They are rendered only on the server, so they were not available to this session. Dropping a Gemini MyCast mp3 plus its episode JSON into `render.sh` gives the same scene with those voices.

## Mobile 9:16 reframing plan
- **B** is already rendered at 720×1280. The hosts stack top and bottom, only the latest evidence card is shown, captions are 30 px, and the waveform sits above the captions.
- **A** should be recomposed, not cropped. The minds stack vertically with a vertical beam, the title moves to the upper third, and the lower third stays clear for captions. `scene_a.html` already takes `?w=&h=`, so this is a layout pass rather than new tooling.

## Comparison (Claude's first assessment; the owner decides)
| Criterion | A | B |
|---|---|---|
| Clear in 3 s | medium: the idea lands at 4–6 s with the title | strong: "two AI voices, one podcast" reads at once |
| Visual originality | strong: title-sequence feel | medium: closer to a familiar AI-avatar idiom |
| Text accuracy | exact: type drawn in code | exact: captions are the script, timed to pauses |
| Motion | strong: continuous orbit and dolly | medium: mostly static framing, audio-driven motion |
| Dual-host audio | none: silent by design | intelligible, but the Piper pilot voice the owner found weak |
| Readable on POCO Android | check the small DEMO badge and chips at 720p | good in 9:16; the 16:9 footer is too small for phones |
| Generative defects | none: no generator used | none |
| Time / cost | $0; all three files render in about 1 min on 4 CPU cores | included |
| Repeatability | deterministic | deterministic; any new MP3 and script can be dropped in |

## Files
- `scene_a.html` and `scene_b.html` are the scenes. Each exposes `window.render(t)` and draws exactly the frame at time `t`.
- `render_frames.js` is the frame renderer (Playwright + Chromium, no network).
- `prepare_audio.py` produces loudness per frame and who-speaks-when captions from an MP3 and its episode JSON.
- `render.sh` runs the whole pipeline: frames, H.264/AAC faststart MP4, posters, and ffprobe evidence.

## Not done here (needs separate owner approval)
- **Higgsfield.** The account shows 110 credits including a trial that expires 2026-11-07. An earlier estimate put Kling v3 at 10 credits per 5 s. Nothing was spent and no job was submitted. A run needs the owner to name the model, the output, a credit cap and where the result may go.
- **Public release.** No YouTube, TikTok, Telegram channel or other posting.
