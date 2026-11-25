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

## Narration and owner photos (S2, T-735)

```bash
# one WAV per shot from the storyboard voiceover, offline with a local Piper model (download it once, privately)
python -m film_studio.narration --model /private/voices/ru_RU-dmitri-medium.onnx --out /private/vo \
  --dataset-licence "CC0" --model-url https://huggingface.co/rhasspy/piper-voices/tree/main/ru/ru_RU/dmitri/medium
# render with narration (placed per shot, mixed to -16 LUFS / -1.5 dBTP, measured again in qa_receipt.json)
python -m film_studio.render --out /private/film --manifest /private/assets/asset_manifest.json --narration /private/vo/narration.json
```

`narration.json` (`film-studio/narration/v1`) pins every WAV by sha256; a line that would run into the next shot is
refused. An owner recording uses `"source": "owner_recording"` with a `consent` note. An owner photo replaces a stock
shot with a manifest asset `"source_type": "owner_supplied"`, `"url": "owner://…"`, `"substitutes_for": "<storyboard
asset id>"`. Owner photos and voice stay in the private directory, never in git.

## Faceless Creator A/B (T-737, issue #469)

A private 9:16 clip in which one clothed synthetic presenter changes her fictional face in a snap while body, hoodie,
room and voice stay the same. Everything is drawn or synthesised by `face_switch.py` (no third-party media, no real
person); voice = local espeak-ng when installed. About two minutes per clip on two CPUs.

```bash
python -m film_studio.face_switch --variant A --out /private/faceless/a-v1     # privacy angle
python -m film_studio.face_switch --variant B --out /private/faceless/b-v1     # creative-control angle
python test_face_switch.py
```

Output: `brief.json`, `script.json` (timed lines and switches), `render_plan.json`, `video.mp4` (1080x1920, 30 fps,
H.264 + AAC), `frames/` (before / after every switch + contact sheet) and `qa_receipt.json`
(`faceless-ab/qa-receipt/v1`): ffprobe, full decode, 9:16, 25–40 s, frame count, loudness, black stretches, the burned-in
«AI · SYNTHETIC DEMO» label, and per switch the mean change of the face area against hoodie and room (decoded frames).

## Not in S1

Narration audio input (S1 lays a silent AAC track and burns the narration in as captions), Media Finisher assembly
(loudness, private playback; after PR #442), the UI, hybrid/generative renderers (spec only). See ROADMAP T-730 «Blocked».
