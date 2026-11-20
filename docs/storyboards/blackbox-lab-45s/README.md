# Blackbox Lab — 45-second director package (Issue #434)

**Status: SPEC ONLY / NOT RENDERED / NOT APPROVED.** Prepared independently for Claude's Film Studio implementation [#433](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/433). No MP4, narration audio, licensed photos, or real customer footage exists in this package. No publishing or external paid services authorized.

## Director notes
Seven shots at 24 fps, 1920×1080, exactly 45 seconds. Dark cyan cinematic shadows with warm practical light. Narrative: question → collaboration → research → challenge → prototype → honest feedback gate → Blackbox Lab. All fictional studio visuals are **DEMO**, never evidence of actual usage or business outcomes. Never substitute invented customer numbers for real evidence. Narration is draft copy, not recorded audio. Audio/music licensing remains blocked.

## Contracts and asset gate
- `film_bible.json`: palette, format, continuity, truth restrictions.
- `storyboard.json`: seven deterministic shots, timing, narration, source references and camera plan.
- `asset_candidates.json`: per-shot placeholders and candidate research websites; **no image is licensed, downloaded or approved**.
- For each selected asset, collect original item URL, photographer/author, applicable license, attribution, access rights/consent, sha256, and provenance. Unknown license or hash means **render blocked**. Check licensing at the actual asset page; a general platform license URL is not asset permission.

## Reproducible checks (Python 3, standard library)
```bash
python - <<'PY'
import json, pathlib
p=pathlib.Path('docs/storyboards/blackbox-lab-45s')
b,s,a=[json.loads((p/n).read_text()) for n in ('film_bible.json','storyboard.json','asset_candidates.json')]
assert s['schema']=='film-studio/v1' and b['format']['fps']==s['fps']==24
assert (s['width'],s['height'])==(1920,1080)
shots=s['shots']; assert len(shots)==7
assert len({x['shot_id'] for x in shots})==7
assert len({x['asset_id'] for x in shots})==7
assert sum(x['duration_seconds'] for x in shots)==s['target_duration_seconds']==45
assert all(x['start_seconds']==sum(y['duration_seconds'] for y in shots[:i]) and x['end_seconds']==x['start_seconds']+x['duration_seconds'] for i,x in enumerate(shots))
assert all(x['truth_status']=='DEMO' and x['state']=='not_started' for x in shots)
assets={x['asset_id']:x for x in a['assets']}
assert set(assets)=={x['asset_id'] for x in shots}
assert all(not x['render_allowed'] and x['rights_status']=='unverified' and x['source_reference'] for x in assets.values())
assert a['render_allowed'] is False
print('PASS: 7 unique shots, 45s continuous timeline, source refs, blocked unlicensed assets')
PY
```

## Acceptance and handoff
This PR is ready for *technical review*, not film release. Claude should validate the contracts against its implementation, preserve the licensing gate, create real authorized assets and narration, then separately demonstrate reproducible FFprobe/QA evidence and owner review before any release. Source: [#434](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/434), [#433](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos/issues/433).
