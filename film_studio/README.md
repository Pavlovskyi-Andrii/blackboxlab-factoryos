# AI Film Studio — S1 (T-730, issue #433)

Script → storyboard → rights-checked stills → 2.5D camera moves → private MP4 → QA receipt. Offline, $0.

## Contracts (`schema.py`)

| Document | Schema | Notes |
| --- | --- | --- |
| storyboard | `film-studio/storyboard/v1` | shots tile the film exactly, whole frames, camera presets from the Film Bible |
| film bible | `film-bible/v1` | `output.private_only` and `human_review_required` must be `true` |
| asset manifest | `film-studio/asset-manifest/v1` | `verified` needs url, author, licence, attribution, sha256, verifier, time, local file |

`render_plan.json` (`film-studio/render-plan/v1`) and `qa_receipt.json` (`film-studio/qa-receipt/v1`) are outputs.
Unknown keys are rejected; an unverified, unknown or tampered asset blocks its shot (exit 3, BLOCKED receipt).

## Commands

Needs Python 3.9+, Pillow, NumPy, FFmpeg/FFprobe and DejaVu Sans. `--out` must be outside the repository (or in `data/`).

```bash
# 45 s film from original procedural stand-in stills (labelled "DEMO · иллюстрация, не фото"), 1920x1080
python -m film_studio.render --out /path/private/film --procedural-standins
# 720p proxy, then re-render only shot s03 (the others come from the per-shot cache)
python -m film_studio.render --out /path/private/proxy --procedural-standins --proxy
python -m film_studio.render --out /path/private/proxy --procedural-standins --proxy --only s03
# the shot pack's Pexels candidates: blocked until each photo is verified
python -m film_studio.render --out /path/private/check          # exit 3, qa_receipt.json status BLOCKED
# verified licensed / owner assets
python -m film_studio.render --out /path/private/film --manifest assets/asset_manifest.json
# plan and FFmpeg commands only
python -m film_studio.render --out /path/private/film --procedural-standins --dry-run
python test_film_studio.py
```

Output directory: `assets/` (stand-in stills + manifest), `shots/` (one cached clip per shot), `text/` (caption
files), `render_plan.json`, `film.mp4`, `frames/` (one mid-shot JPEG per shot), `qa_receipt.json`.

## Not in S1

Narration audio input (S1 lays a silent AAC track and burns the narration in as captions), Media Finisher assembly
(loudness, private playback; after PR #442), the UI, hybrid/generative renderers (spec only). See ROADMAP T-730 «Blocked».
