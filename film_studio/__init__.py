"""FactoryOS AI Film Studio (GitHub #433, ROADMAP T-730).

S1 slice: versioned contracts (storyboard, film bible, asset manifest) with a strict validator, a deterministic
per-shot render plan, an offline FFmpeg "Photo Cinema" renderer (still image -> 2.5D camera move) and a QA receipt.
No network, no paid providers, no publishing. Rights fail closed: a shot whose asset is not `verified` with a
matching sha256 never renders.
"""

SCHEMA_STORYBOARD = "film-studio/storyboard/v1"
SCHEMA_FILM_BIBLE = "film-bible/v1"
SCHEMA_ASSET_MANIFEST = "film-studio/asset-manifest/v1"
SCHEMA_RENDER_PLAN = "film-studio/render-plan/v1"
SCHEMA_QA_RECEIPT = "film-studio/qa-receipt/v1"
RENDERER_VERSION = "photo_cinema/1"
