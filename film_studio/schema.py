"""Strict validators for the Film Studio contracts (T-730).

Every document is untrusted data: text fields are length-limited and stripped of control characters by refusal,
unknown keys are rejected, and nothing in a text field is ever interpreted (the renderer passes captions to FFmpeg
through files, never through the filter graph).

Rights policy (fail closed): an asset may be listed with any rights_status, but only `verified` assets with a full
provenance record (url, author, licence, attribution, sha256, verifier, timestamp, local file) can be rendered.
"""
from __future__ import annotations

import re
from fractions import Fraction
from typing import Any, Dict, List

from . import SCHEMA_ASSET_MANIFEST, SCHEMA_FILM_BIBLE, SCHEMA_STORYBOARD

CAMERA_PRESETS = (
    "slow_dolly_in",
    "slow_pull_out",
    "subtle_pan_left",
    "subtle_pan_right",
    "slow_orbit_2_5d",
    "static_with_graphic",
)
TRANSITIONS = ("cut", "fade_in", "crossfade", "fade_out")
RENDERERS = ("photo_cinema", "hybrid_film", "generative_cinema")
SHOT_STATES = ("not_started", "planned", "rendering", "rendered", "failed", "approved", "rejected")
RIGHTS_STATUSES = ("verified", "candidate_unverified", "unknown", "rejected")
SOURCE_TYPES = ("licensed_stock", "owner_supplied", "original_procedural")
VISUAL_SOURCES = ("licensed_stock_candidate", "licensed_stock", "owner_supplied", "original_procedural")

MAX_TEXT = 600
MAX_SHOTS = 24
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_LANG_KEY = re.compile(r"^voiceover_[a-z]{2}$")

STORYBOARD_KEYS = {"schema", "project_id", "revision", "format", "creative_goal", "narration_policy", "render",
                   "dependencies", "shots"}
FORMAT_KEYS = {"width", "height", "fps", "seconds", "ratio", "preview_width", "preview_height", "language"}
SHOT_KEYS = {"shot_id", "scene_id", "start_sec", "duration_sec", "end_sec", "label", "visual_source", "asset_id",
             "visual_brief", "camera", "graphics", "transition", "state", "renderer", "rights_verified",
             "requires_owner_approval", "fallback"}
CAMERA_KEYS = {"preset", "zoom_max"}
GRAPHICS_KEYS = {"title", "overlay_generated_by_code", "demonstration_label"}
TRANSITION_KEYS = {"type", "duration_sec"}

BIBLE_KEYS = {"schema", "project_id", "revision", "date", "approved_direction", "format", "genre", "palette",
              "camera_bible", "locations", "continuity", "truth_policy", "audio", "output", "related_issues"}

MANIFEST_KEYS = {"schema", "project_id", "created_at", "notes", "assets"}
ASSET_KEYS = {"id", "role", "source_type", "provider", "url", "author", "licence", "attribution", "changes",
              "rights_status", "verified_at", "verified_by", "sha256", "local_path", "layers", "substitutes_for",
              "notes"}
LICENCE_KEYS = {"name", "url"}
LAYER_KEYS = {"local_path", "sha256"}


class ValidationError(ValueError):
    """A contract document is malformed. `errors` lists every problem found (not only the first)."""

    def __init__(self, doc: str, errors: List[str]):
        self.doc = doc
        self.errors = list(errors)
        super().__init__(f"{doc}: " + "; ".join(self.errors))


class _Check:
    def __init__(self, doc: str):
        self.doc = doc
        self.errors: List[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def keys(self, obj: Any, allowed: set, where: str, required: set = frozenset()) -> bool:
        if not isinstance(obj, dict):
            self.err(f"{where}: must be an object")
            return False
        extra = sorted(set(obj) - allowed)
        if extra:
            self.err(f"{where}: unknown keys {extra}")
        missing = sorted(k for k in required if k not in obj)
        if missing:
            self.err(f"{where}: missing keys {missing}")
        return True

    def text(self, value: Any, where: str, *, optional: bool = False, limit: int = MAX_TEXT) -> None:
        if value is None and optional:
            return
        if not isinstance(value, str) or not value.strip():
            self.err(f"{where}: must be a non-empty string")
            return
        if len(value) > limit:
            self.err(f"{where}: longer than {limit} characters")
        if _CONTROL.search(value):
            self.err(f"{where}: contains control characters")

    def ident(self, value: Any, where: str) -> None:
        if not isinstance(value, str) or not _ID.match(value):
            self.err(f"{where}: must be an id of letters, digits, '_', '.', '-' (max 64)")

    def raise_if_any(self) -> None:
        if self.errors:
            raise ValidationError(self.doc, self.errors)


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _frac(value: Any) -> Fraction:
    # Decimal text of the JSON number, so 0.4 is exactly 2/5 (not the binary float).
    return Fraction(str(value))


def _check_format(c: _Check, fmt: Any, where: str) -> None:
    if not c.keys(fmt, FORMAT_KEYS, where, {"width", "height", "fps", "seconds", "ratio"}):
        return
    w, h, fps, secs = fmt.get("width"), fmt.get("height"), fmt.get("fps"), fmt.get("seconds")
    for name, v in (("width", w), ("height", h), ("fps", fps)):
        if not isinstance(v, int) or isinstance(v, bool) or v <= 0:
            c.err(f"{where}.{name}: must be a positive integer")
    if not _number(secs) or secs <= 0 or secs > 600:
        c.err(f"{where}.seconds: must be a number in (0, 600]")
    ratio = fmt.get("ratio")
    if isinstance(ratio, str) and re.match(r"^\d+:\d+$", ratio) and isinstance(w, int) and isinstance(h, int) and h:
        a, b = (int(x) for x in ratio.split(":"))
        if Fraction(w, h) != Fraction(a, b):
            c.err(f"{where}: {w}x{h} is not {ratio}")
    else:
        c.err(f"{where}.ratio: must look like '16:9' and match width/height")
    for name in ("preview_width", "preview_height"):
        if name in fmt and (not isinstance(fmt[name], int) or fmt[name] <= 0):
            c.err(f"{where}.{name}: must be a positive integer")
    if "language" in fmt and (not isinstance(fmt["language"], str) or not re.match(r"^[a-z]{2}$", fmt["language"])):
        c.err(f"{where}.language: must be a 2-letter code")


def validate_storyboard(doc: Any, bible: Dict[str, Any] = None) -> Dict[str, Any]:
    """Validate a storyboard; with `bible`, also check it against the Film Bible. Returns the document unchanged."""
    c = _Check("storyboard")
    if not c.keys(doc, STORYBOARD_KEYS, "storyboard", {"schema", "project_id", "revision", "format", "shots"}):
        c.raise_if_any()
    if doc.get("schema") != SCHEMA_STORYBOARD:
        c.err(f"schema: expected {SCHEMA_STORYBOARD!r}, got {doc.get('schema')!r}")
    c.ident(doc.get("project_id"), "project_id")
    if not isinstance(doc.get("revision"), int) or doc.get("revision") < 1:
        c.err("revision: must be a positive integer")
    for k in ("creative_goal", "narration_policy"):
        if k in doc:
            c.text(doc[k], k)
    fmt = doc.get("format")
    _check_format(c, fmt, "format")
    shots = doc.get("shots")
    if not isinstance(shots, list) or not (1 <= len(shots) <= MAX_SHOTS):
        c.err(f"shots: must be a list of 1..{MAX_SHOTS} shots")
        c.raise_if_any()
    fps = fmt.get("fps") if isinstance(fmt, dict) else None
    total = fmt.get("seconds") if isinstance(fmt, dict) else None
    max_zoom = None
    moves = None
    if bible:
        cam = bible.get("camera_bible") or {}
        max_zoom = cam.get("max_zoom")
        moves = set(cam.get("moves") or [])
    seen = set()
    cursor = Fraction(0)
    for i, shot in enumerate(shots):
        where = f"shots[{i}]"
        if not c.keys(shot, SHOT_KEYS | {k for k in (shot if isinstance(shot, dict) else {}) if _LANG_KEY.match(k)},
                      where, {"shot_id", "start_sec", "duration_sec", "end_sec", "asset_id", "camera", "transition"}):
            continue
        sid = shot.get("shot_id")
        c.ident(sid, f"{where}.shot_id")
        if sid in seen:
            c.err(f"{where}.shot_id: duplicate {sid!r}")
        seen.add(sid)
        c.ident(shot.get("asset_id"), f"{where}.asset_id")
        for k in ("scene_id",):
            if k in shot:
                c.ident(shot[k], f"{where}.{k}")
        for k in ("label", "visual_brief"):
            if k in shot:
                c.text(shot[k], f"{where}.{k}")
        for k in shot:
            if _LANG_KEY.match(k):
                c.text(shot[k], f"{where}.{k}")
        if "visual_source" in shot and shot["visual_source"] not in VISUAL_SOURCES:
            c.err(f"{where}.visual_source: one of {list(VISUAL_SOURCES)}")
        if "renderer" in shot and shot["renderer"] not in RENDERERS:
            c.err(f"{where}.renderer: one of {list(RENDERERS)}")
        if "state" in shot and shot["state"] not in SHOT_STATES:
            c.err(f"{where}.state: one of {list(SHOT_STATES)}")
        for k in ("rights_verified", "requires_owner_approval"):
            if k in shot and not isinstance(shot[k], bool):
                c.err(f"{where}.{k}: must be true/false")
        start, dur, end = shot.get("start_sec"), shot.get("duration_sec"), shot.get("end_sec")
        if not all(_number(v) for v in (start, dur, end)):
            c.err(f"{where}: start_sec/duration_sec/end_sec must be numbers")
        else:
            fs, fd, fe = _frac(start), _frac(dur), _frac(end)
            if fd <= 0:
                c.err(f"{where}.duration_sec: must be > 0")
            if fs != cursor:
                c.err(f"{where}.start_sec: {start} leaves a gap/overlap (expected {float(cursor):g})")
            if fs + fd != fe:
                c.err(f"{where}.end_sec: start + duration != end")
            if isinstance(fps, int) and (fd * fps).denominator != 1:
                c.err(f"{where}.duration_sec: {dur}s is not a whole number of frames at {fps} fps")
            cursor = fe
        cam = shot.get("camera")
        if c.keys(cam, CAMERA_KEYS, f"{where}.camera", {"preset"}):
            preset = cam.get("preset")
            if preset not in CAMERA_PRESETS:
                c.err(f"{where}.camera.preset: one of {list(CAMERA_PRESETS)}")
            elif moves is not None and preset not in moves:
                c.err(f"{where}.camera.preset: {preset!r} is not in the Film Bible camera moves")
            zm = cam.get("zoom_max", 1.0)
            if not _number(zm) or zm < 1.0 or zm > 1.5:
                c.err(f"{where}.camera.zoom_max: must be within [1.0, 1.5]")
            elif _number(max_zoom) and zm > max_zoom:
                c.err(f"{where}.camera.zoom_max: {zm} exceeds the Film Bible max_zoom {max_zoom}")
        tr = shot.get("transition")
        if c.keys(tr, TRANSITION_KEYS, f"{where}.transition", {"type"}):
            if tr.get("type") not in TRANSITIONS:
                c.err(f"{where}.transition.type: one of {list(TRANSITIONS)}")
            td = tr.get("duration_sec", 0)
            if not _number(td) or td < 0 or td > 2:
                c.err(f"{where}.transition.duration_sec: must be within [0, 2]")
            elif _number(dur) and dur > 0 and _frac(td) * 2 > _frac(dur):
                c.err(f"{where}.transition.duration_sec: longer than half the shot")
        gr = shot.get("graphics")
        if gr is not None and c.keys(gr, GRAPHICS_KEYS, f"{where}.graphics"):
            c.text(gr.get("title"), f"{where}.graphics.title", optional=True, limit=80)
            c.text(gr.get("demonstration_label"), f"{where}.graphics.demonstration_label", optional=True, limit=24)
    if _number(total) and cursor != _frac(total):
        c.err(f"shots: durations sum to {float(cursor):g}s, format.seconds is {total}")
    if bible:
        if bible.get("project_id") != doc.get("project_id"):
            c.err("project_id: storyboard and Film Bible differ")
        if isinstance(fmt, dict) and bible.get("format") != fmt:
            c.err("format: storyboard and Film Bible formats differ")
    c.raise_if_any()
    return doc


def validate_film_bible(doc: Any) -> Dict[str, Any]:
    c = _Check("film_bible")
    if not c.keys(doc, BIBLE_KEYS, "film_bible",
                  {"schema", "project_id", "revision", "format", "camera_bible", "truth_policy", "output"}):
        c.raise_if_any()
    if doc.get("schema") != SCHEMA_FILM_BIBLE:
        c.err(f"schema: expected {SCHEMA_FILM_BIBLE!r}, got {doc.get('schema')!r}")
    c.ident(doc.get("project_id"), "project_id")
    if not isinstance(doc.get("revision"), int) or doc.get("revision") < 1:
        c.err("revision: must be a positive integer")
    _check_format(c, doc.get("format"), "format")
    cam = doc.get("camera_bible")
    if not isinstance(cam, dict):
        c.err("camera_bible: must be an object")
    else:
        moves = cam.get("moves")
        if not isinstance(moves, list) or not moves or any(m not in CAMERA_PRESETS for m in moves):
            c.err(f"camera_bible.moves: non-empty list of {list(CAMERA_PRESETS)}")
        mz = cam.get("max_zoom")
        if not _number(mz) or mz < 1.0 or mz > 1.5:
            c.err("camera_bible.max_zoom: must be within [1.0, 1.5]")
    truth = doc.get("truth_policy")
    if not isinstance(truth, dict) or not truth.get("label_reenactments"):
        c.err("truth_policy.label_reenactments: required (the DEMO label text)")
    else:
        c.text(truth.get("label_reenactments"), "truth_policy.label_reenactments", limit=24)
    out = doc.get("output")
    # Fail closed: Film Studio output is private and needs a human review before anything else happens.
    if not isinstance(out, dict) or out.get("private_only") is not True or out.get("human_review_required") is not True:
        c.err("output: private_only and human_review_required must both be true")
    c.raise_if_any()
    return doc


def validate_asset_manifest(doc: Any) -> Dict[str, Any]:
    c = _Check("asset_manifest")
    if not c.keys(doc, MANIFEST_KEYS, "asset_manifest", {"schema", "project_id", "assets"}):
        c.raise_if_any()
    if doc.get("schema") != SCHEMA_ASSET_MANIFEST:
        c.err(f"schema: expected {SCHEMA_ASSET_MANIFEST!r}, got {doc.get('schema')!r}")
    c.ident(doc.get("project_id"), "project_id")
    assets = doc.get("assets")
    if not isinstance(assets, list) or not assets:
        c.err("assets: must be a non-empty list")
        c.raise_if_any()
    seen = set()
    for i, a in enumerate(assets):
        where = f"assets[{i}]"
        if not c.keys(a, ASSET_KEYS, where, {"id", "source_type", "rights_status"}):
            continue
        aid = a.get("id")
        c.ident(aid, f"{where}.id")
        if aid in seen:
            c.err(f"{where}.id: duplicate {aid!r}")
        seen.add(aid)
        st = a.get("source_type")
        if st not in SOURCE_TYPES:
            c.err(f"{where}.source_type: one of {list(SOURCE_TYPES)}")
        rs = a.get("rights_status")
        if rs not in RIGHTS_STATUSES:
            c.err(f"{where}.rights_status: one of {list(RIGHTS_STATUSES)}")
        for k in ("role", "provider", "author", "attribution", "changes", "verified_by", "notes", "verified_at"):
            if a.get(k) is not None:
                c.text(a[k], f"{where}.{k}")
        for k in ("substitutes_for",):
            if a.get(k) is not None:
                c.ident(a[k], f"{where}.{k}")
        if a.get("url") is not None:
            _check_url(c, a["url"], st, f"{where}.url")
        lic = a.get("licence")
        if lic is not None and c.keys(lic, LICENCE_KEYS, f"{where}.licence", {"name", "url"}):
            c.text(lic.get("name"), f"{where}.licence.name")
            _check_url(c, lic.get("url"), st, f"{where}.licence.url")
        if a.get("sha256") is not None and (not isinstance(a["sha256"], str) or not _SHA256.match(a["sha256"])):
            c.err(f"{where}.sha256: must be 64 lowercase hex characters")
        if a.get("local_path") is not None:
            _check_local_path(c, a["local_path"], f"{where}.local_path")
        layers = a.get("layers")
        if layers is not None:
            if not isinstance(layers, dict) or set(layers) - {"foreground"}:
                c.err(f"{where}.layers: only a 'foreground' layer is supported")
            else:
                fg = layers.get("foreground")
                if c.keys(fg, LAYER_KEYS, f"{where}.layers.foreground", {"local_path", "sha256"}):
                    _check_local_path(c, fg.get("local_path"), f"{where}.layers.foreground.local_path")
                    if not isinstance(fg.get("sha256"), str) or not _SHA256.match(fg["sha256"]):
                        c.err(f"{where}.layers.foreground.sha256: must be 64 lowercase hex characters")
        if rs == "verified":
            # A verified asset carries its whole provenance record; anything missing means it is not verified.
            for k in ("url", "author", "licence", "attribution", "sha256", "verified_at", "verified_by", "local_path"):
                if not a.get(k):
                    c.err(f"{where}: rights_status 'verified' requires {k}")
    c.raise_if_any()
    return doc


def _check_url(c: _Check, url: Any, source_type: Any, where: str) -> None:
    if not isinstance(url, str) or len(url) > 500 or _CONTROL.search(url) or " " in url:
        c.err(f"{where}: must be a URL string")
        return
    if url.startswith("https://"):
        return
    # Original assets point at the code that made them; owner uploads at the owner's private store.
    if url.startswith("repo://") and source_type == "original_procedural":
        return
    if url.startswith("owner://") and source_type == "owner_supplied":
        return
    c.err(f"{where}: must be https:// (repo:// only for original_procedural, owner:// only for owner_supplied)")


def _check_local_path(c: _Check, path: Any, where: str) -> None:
    # Relative to the manifest's directory; no absolute paths, no escaping upwards.
    if (not isinstance(path, str) or not path or path.startswith("/") or "\\" in path
            or any(part in ("..", "") for part in path.split("/")) or _CONTROL.search(path)):
        c.err(f"{where}: must be a relative path inside the manifest directory")


def manifest_from_candidates(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Convert the shot pack's `asset_candidates.json` (film-studio/assets/v1) into an asset manifest v1.

    Nothing is upgraded: candidates keep their rights status, so they validate but cannot render.
    """
    if not isinstance(doc, dict) or doc.get("schema") != "film-studio/assets/v1":
        raise ValidationError("asset_candidates", ["schema: expected 'film-studio/assets/v1'"])
    assets = []
    for a in doc.get("assets") or []:
        rs = a.get("rights_status")
        assets.append({
            "id": a.get("id"),
            "role": a.get("role"),
            "source_type": "licensed_stock",
            "provider": a.get("provider"),
            "url": a.get("page"),
            "author": a.get("author"),
            "licence": {"name": f"{a.get('provider') or 'Provider'} License", "url": a.get("licence_reference")},
            "rights_status": rs if rs in RIGHTS_STATUSES else "unknown",
            "verified_at": a.get("verified_at"),
            "sha256": a.get("asset_sha256"),
            "local_path": a.get("local_path"),
        })
    manifest = {"schema": SCHEMA_ASSET_MANIFEST, "project_id": doc.get("project_id"), "assets": assets}
    return validate_asset_manifest(manifest)
