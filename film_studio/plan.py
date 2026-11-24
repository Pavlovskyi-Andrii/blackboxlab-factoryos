"""Deterministic per-shot render plan with the rights gate (T-730).

Times are integer frames: every shot is `duration_sec * fps` frames, the shots tile the film exactly, and a
crossfade borrows `tail_frames` extra frames from the outgoing shot so the assembled film keeps its exact length.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import RENDERER_VERSION, SCHEMA_RENDER_PLAN
from .schema import validate_asset_manifest, validate_film_bible, validate_storyboard

FADE_OUT_SEC = Fraction(3, 4)


class RightsBlocked(RuntimeError):
    """One or more shots have no renderable asset. `blocked` lists {shot_id, asset_id, reason}."""

    def __init__(self, blocked: List[Dict[str, str]]):
        self.blocked = blocked
        super().__init__("rights gate: " + "; ".join(f"{b['shot_id']}/{b['asset_id']}: {b['reason']}" for b in blocked))


class PlanError(ValueError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _frames(seconds: Any, fps: int) -> int:
    f = Fraction(str(seconds)) * fps
    if f.denominator != 1:
        raise PlanError(f"{seconds}s is not a whole number of frames at {fps} fps")
    return int(f)


def _nearest_frames(seconds: Any, fps: int) -> int:
    """Transitions do not change the film length, so they are rounded to the nearest frame (0.4 s -> 10 at 24)."""
    f = Fraction(str(seconds)) * fps
    return int(f + Fraction(1, 2))


def check_asset(asset: Optional[Dict[str, Any]], asset_id: str, base_dir: Path) -> Optional[str]:
    """Return why an asset cannot render, or None when it can. Reads the file to compare its sha256."""
    if asset is None:
        return "asset not in manifest"
    if asset.get("rights_status") != "verified":
        return f"rights_status is {asset.get('rights_status')!r}, not 'verified'"
    path = (base_dir / asset["local_path"]).resolve()
    try:
        path.relative_to(base_dir.resolve())
    except ValueError:
        return "local_path escapes the manifest directory"
    if not path.is_file():
        return "local file missing"
    if sha256_file(path) != asset["sha256"]:
        return "sha256 mismatch (file differs from the verified one)"
    fg = (asset.get("layers") or {}).get("foreground")
    if fg:
        fpath = (base_dir / fg["local_path"]).resolve()
        if not fpath.is_file():
            return "foreground layer missing"
        if sha256_file(fpath) != fg["sha256"]:
            return "foreground layer sha256 mismatch"
    return None


def build_plan(storyboard: Dict[str, Any], bible: Dict[str, Any], manifest: Dict[str, Any], *,
               manifest_dir: Path, size: Optional[tuple] = None, crossfade_sec: float = 0.5,
               overrides: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Validate the three contracts and return the render plan. Raises RightsBlocked when any shot is blocked.

    overrides: {shot_id: asset_id} renders a shot from another manifest asset (e.g. an original stand-in); the
    plan records both ids so the receipt says what was substituted.
    """
    validate_film_bible(bible)
    validate_storyboard(storyboard, bible)
    validate_asset_manifest(manifest)
    if manifest.get("project_id") != storyboard["project_id"]:
        raise PlanError("asset manifest project_id differs from the storyboard")
    overrides = dict(overrides or {})
    shot_ids = [s["shot_id"] for s in storyboard["shots"]]
    unknown = sorted(set(overrides) - set(shot_ids))
    if unknown:
        raise PlanError(f"overrides name unknown shots {unknown}")
    fmt = storyboard["format"]
    fps = fmt["fps"]
    width, height = size or (fmt["width"], fmt["height"])
    if Fraction(width, height) != Fraction(fmt["width"], fmt["height"]):
        raise PlanError(f"{width}x{height} changes the aspect ratio {fmt['ratio']}")
    if width % 2 or height % 2:
        raise PlanError("width and height must be even for H.264 4:2:0")
    xfade_frames = _nearest_frames(crossfade_sec, fps) if crossfade_sec else 0
    by_id = {a["id"]: a for a in manifest["assets"]}
    lang = fmt.get("language", "ru")
    demo_text = bible["truth_policy"]["label_reenactments"]

    shots = storyboard["shots"]
    blocked: List[Dict[str, str]] = []
    entries: List[Dict[str, Any]] = []
    start = 0
    for i, shot in enumerate(shots):
        frames = _frames(shot["duration_sec"], fps)
        sid = shot["shot_id"]
        asset_id = overrides.get(sid, shot["asset_id"])
        asset = by_id.get(asset_id)
        why = check_asset(asset, asset_id, manifest_dir)
        if why:
            blocked.append({"shot_id": sid, "asset_id": asset_id, "reason": why})
        renderer = shot.get("renderer", "photo_cinema")
        fallback = None
        if renderer == "hybrid_film":
            # No image-to-video provider is connected or approved: say so and use photo animation.
            fallback = "hybrid_film unavailable (no approved provider) -> photo_cinema"
        elif renderer == "generative_cinema":
            blocked.append({"shot_id": sid, "asset_id": asset_id,
                            "reason": "generative_cinema needs separate owner approval of credits"})
        tr = shot["transition"]
        if i == 0:
            t_in = {"type": "fade_from_black", "frames": _nearest_frames(tr.get("duration_sec", 0), fps)
                    if tr["type"] == "fade_in" else 0, "source": "storyboard"}
        elif tr["type"] == "crossfade":
            t_in = {"type": "crossfade", "frames": _nearest_frames(tr.get("duration_sec", 0), fps), "source": "storyboard"}
        elif tr["type"] == "cut" and xfade_frames:
            t_in = {"type": "crossfade", "frames": xfade_frames, "source": "default_crossfade"}
        else:
            t_in = {"type": "cut", "frames": 0, "source": "storyboard"}
        if t_in["type"] == "crossfade" and t_in["frames"] * 2 > min(frames, entries[-1]["frames"]):
            raise PlanError(f"{sid}: crossfade longer than half a shot")
        entry = {
            "shot_id": sid,
            "index": i,
            "start_frame": start,
            "frames": frames,
            "tail_frames": 0,
            "transition_in": t_in,
            "fade_out_frames": _nearest_frames(FADE_OUT_SEC, fps) if i == len(shots) - 1 else 0,
            "camera": {"preset": shot["camera"]["preset"], "zoom_max": shot["camera"].get("zoom_max", 1.0)},
            "title": (shot.get("graphics") or {}).get("title"),
            "demo_label": (shot.get("graphics") or {}).get("demonstration_label"),
            "caption": shot.get(f"voiceover_{lang}"),
            "renderer": "photo_cinema",
            "renderer_requested": renderer,
            "fallback": fallback,
            "storyboard_asset_id": shot["asset_id"],
            "asset": _asset_record(asset, asset_id),
        }
        if i > 0 and t_in["type"] == "crossfade":
            entries[-1]["tail_frames"] = t_in["frames"]
        entries.append(entry)
        start += frames
    if blocked:
        raise RightsBlocked(blocked)
    total = start
    if total != _frames(fmt["seconds"], fps):
        raise PlanError("shot frames do not add up to the film length")
    base = {"width": width, "height": height, "fps": fps, "renderer_version": RENDERER_VERSION,
            "demo_text": demo_text}
    for e in entries:
        # Content only: the same pixels in, the same shot settings -> the same clip (provenance text excluded).
        a = e["asset"]
        content = {"sha256": a.get("sha256"), "fg": ((a.get("layers") or {}).get("foreground") or {}).get("sha256"),
                   "source_type": a.get("source_type")}
        shot = {k: v for k, v in e.items() if k not in ("index", "asset", "start_frame", "storyboard_asset_id")}
        e["cache_key"] = canonical_sha({"base": base, "shot": shot, "asset": content})
    plan = {
        "schema": SCHEMA_RENDER_PLAN,
        "project_id": storyboard["project_id"],
        "storyboard_revision": storyboard["revision"],
        "storyboard_sha256": canonical_sha(storyboard),
        "film_bible_sha256": canonical_sha(bible),
        "renderer": "photo_cinema",
        "renderer_version": RENDERER_VERSION,
        "width": width,
        "height": height,
        "fps": fps,
        "total_frames": total,
        "duration_sec": f"{total / fps:.3f}",
        "demo_text": demo_text,
        "language": lang,
        "shots": entries,
    }
    plan["plan_sha256"] = canonical_sha(plan)
    return plan


def _asset_record(asset: Optional[Dict[str, Any]], asset_id: str) -> Dict[str, Any]:
    if not asset:
        return {"id": asset_id}
    keep = ("id", "source_type", "provider", "url", "author", "licence", "attribution", "changes", "rights_status",
            "verified_at", "verified_by", "sha256", "local_path", "layers", "substitutes_for")
    return {k: asset[k] for k in keep if asset.get(k) is not None}
