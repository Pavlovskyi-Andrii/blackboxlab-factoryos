# Blackbox Lab — 45-second AI Film Studio shotpack

**Date:** 20 November 2026. **Owner approval:** AI Film Studio feature concept; **this file is a proposed first creative treatment**, not a rendered film or authorization to publish.

**Issue:** #434 (ChatGPT creative scope only). Main implementation: #433, Claude. Related Media Finisher: #427 / PR #428; existing motion reference: #353. Durable owner record: https://app.notion.com/p/41e8fbbd6dd5816fa097cc7ff466a065

## Creative objective

A believable cinematic, technology-documentary teaser for FactoryOS / Blackbox Lab. **45 seconds, 7 shots, 16:9, 1920×1080, 24 fps**, private first. No fabricated sales, revenue, users, external publication or verified autonomy. All reenacted UI and synthetic visuals carry a visible **DEMO** label.

## Ordered shot list

| Time (s) | Shot | Main visual | Narration |
| --- | --- | --- | --- |
| 0–5 | s01 · Ночной город | pexels-5847759 · slow_dolly_in | Что, если идея сможет пройти путь до реального продукта? |
| 5–11 | s02 · Вопрос | pexels-10410074 · subtle_pan_right | Сначала вопрос. Затем — спор, гипотезы и поиск доказательств. |
| 11–17 | s03 · Факты | pexels-7983347 · slow_dolly_in | Агенты собирают факты и отделяют сигналы от догадок. |
| 17–24 | s04 · Прототип | pexels-5496464 · subtle_pan_left | План превращается в прототип. Прототип — в проверяемый эксперимент. |
| 24–30 | s05 · Креатив | pexels-17489156 · slow_orbit_2_5d | Из этих материалов рождаются сценарии, визуалы и новые версии видео. |
| 30–36 | s06 · Контроль | pexels-5926378 · static_with_graphic | Но публикация и реальные действия требуют контроля человека. |
| 36–45 | s07 · Финал | pexels-8344064 · slow_pull_out | FactoryOS. Blackbox Lab. Не обещание успеха — лаборатория, в которой мы проверяем, что действительно работает. |

The target is a deliberate cinematic pace: motivated edits, no unnecessary zoom flashes; slow pan/push under 8% crop. Voice and footage must be verified, synced, and human-reviewed. Shot-level regeneration is preferred over redoing the entire film.

## Contracts

- `film_bible.json` — palette, lighting, camera, continuity, truth and music/voice policy.
- `storyboard.json` — versioned sequence, timing, shot assets, voiceover, transitions, state, explicit non-rendered markers.
- `asset_candidates.json` — candidate Pexels source URLs and general licence policy. **All rights_status fields are candidate_unverified and allowed_to_render=false**. Before production, fetch the original page, verify author and restrictions, record authorization context, download with consent into private media storage, store SHA256, and record attribution/changes. Never treat this shotpack as the license approval step. Some photographer names were not yet confirmed.
- Generated image/video references require their own provenance and approval; do not use model-generated scenes as evidence that the depicted business events happened.

## QA / minimal acceptance for Claude

1. Validate 7 unique IDs, ascending non-overlapping times and sum exactly 45.0 seconds.
2. Block render if asset provenance / rights / checksum missing; never silently use arbitrary web images.
3. Support `photo_cinema` entirely offline with an FFmpeg/Remotion 720p proxy and a real reproducible MP4.
4. Any unavailable image-to-video provider must visibly fall back to **photo animation** with correct method label, not a fake "generated motion".
5. Perform ffprobe/full-decode, actual audio measurement, readability/safe-zone checks, preserve original source and provide owner preview. Do not publish.
6. Critical dependency: PR #428 has an open media privacy issue; use private authenticated playback, not world-readable final URLs.

## Candidate asset sources and usage

All candidate source pages refer to individual photos on Pexels. General provider policy: https://www.pexels.com/license/ (free use subject to terms). Pexels image pages are creative **references only**, not a credential to render a photo before per-item check. Credits/photographer names must be completed before use.

- `pexels-5847759` (city_night) — https://www.pexels.com/photo/cityscape-of-modern-megapolis-in-night-time-5847759/ · author: Charles Parker · rights: **unverified**.
- `pexels-10410074` (office_night) — https://www.pexels.com/photo/windows-of-a-building-during-night-time-10410074/ · author: to verify · rights: **unverified**.
- `pexels-7983347` (research) — https://www.pexels.com/photo/keyboard-and-computer-laptop-screen-7983347/ · author: to verify · rights: **unverified**.
- `pexels-5496464` (prototype) — https://www.pexels.com/photo/person-using-silver-and-black-laptop-computer-5496464/ · author: Pavel Danilyuk · rights: **unverified**.
- `pexels-17489156` (media_infrastructure) — https://www.pexels.com/photo/computer-server-in-data-center-room-17489156/ · author: to verify · rights: **unverified**.
- `pexels-5926378` (approval) — https://www.pexels.com/photo/crop-faceless-person-using-laptop-in-darkness-5926378/ · author: to verify · rights: **unverified**.
- `pexels-8344064` (brand_glow) — https://www.pexels.com/photo/close-up-shot-of-neon-lights-8344064/ · author: to verify · rights: **unverified**.

## Next work handoff

Claude owns runtime code, backend, UI and media integration. This creative package is isolated in `docs/storyboards/blackbox-lab-45s/**`; **no claim** on Claude implementation or PR #428. Run a real private proof with asset provenance and compare it to this planned shot list. No new paid provider calls, trial credits, real social publishing or production deploys without approval.
