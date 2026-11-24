"""QA receipt for a Film Studio render (T-730): measured facts only, explicit PASS / FAIL / BLOCKED."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from . import RENDERER_VERSION, SCHEMA_QA_RECEIPT
from .plan import sha256_file

VOICE_NONE = {
    "source": "none",
    "track": "silent AAC stereo 48 kHz (anullsrc)",
    "captions": "narration text burned in as RU captions",
    "reason": ("no permitted Russian offline voice is available here: espeak/espeak-ng/flite/piper binaries are "
               "absent; the Piper RU voice models (huggingface.co) and other downloads are refused by this "
               "session's network policy; paid TTS is not allowed"),
}
REALISTIC_BLOCKED = ("photographic milestone not reached: www.pexels.com is refused by this session's network policy "
                     "(HTTP 403 from the agent proxy), so no candidate photo licence/author could be read or "
                     "verified and no photo was downloaded; every shot uses an original procedural stand-in still")


def _run(argv: List[str], timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def ffprobe(path: Path) -> Dict[str, Any]:
    p = _run(["ffprobe", "-v", "error", "-count_frames", "-show_entries",
              "format=duration,format_name,size:stream=index,codec_type,codec_name,profile,width,height,pix_fmt,"
              "r_frame_rate,avg_frame_rate,nb_read_frames,sample_rate,channels,duration",
              "-of", "json", str(path)])
    if p.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {p.stderr.strip()[-500:]}")
    return json.loads(p.stdout)


def decode_pass(path: Path) -> Dict[str, Any]:
    p = _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-xerror", "-i", str(path), "-f", "null", "-"])
    return {"returncode": p.returncode, "errors": p.stderr.strip()[-500:]}


def black_intervals(path: Path, min_sec: float = 0.25) -> List[Dict[str, float]]:
    p = _run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-vf",
              f"blackdetect=d={min_sec}:pic_th=0.98:pix_th=0.06", "-an", "-f", "null", "-"])
    out = []
    for m in re.finditer(r"black_start:([\d.]+) black_end:([\d.]+) black_duration:([\d.]+)", p.stderr):
        out.append({"start": float(m.group(1)), "end": float(m.group(2)), "duration": float(m.group(3))})
    return out


def sample_frames(path: Path, plan: Dict[str, Any], frames_dir: Path) -> List[Dict[str, Any]]:
    """One JPEG from the middle of every shot, for the owner's review (kept with the private render)."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for s in plan["shots"]:
        t = (s["start_frame"] + s["frames"] / 2) / plan["fps"]
        jpg = frames_dir / f"{s['shot_id']}.jpg"
        p = _run(["ffmpeg", "-nostdin", "-hide_banner", "-v", "error", "-y", "-ss", f"{t:.3f}", "-i", str(path),
                  "-frames:v", "1", "-q:v", "3", str(jpg)])
        out.append({"shot_id": s["shot_id"], "t": round(t, 3), "ok": p.returncode == 0 and jpg.is_file()})
    return out


def _check(name: str, ok: bool, measured: Any, expected: Any) -> Dict[str, Any]:
    return {"check": name, "result": "PASS" if ok else "FAIL", "measured": measured, "expected": expected}


def run_qa(film: Path, plan: Dict[str, Any], shot_records: List[Dict[str, Any]], *, manifest_dir: Path,
           frames_dir: Path) -> Dict[str, Any]:
    probe = ffprobe(film)
    v = next((s for s in probe["streams"] if s["codec_type"] == "video"), {})
    a = next((s for s in probe["streams"] if s["codec_type"] == "audio"), {})
    fps, total = plan["fps"], plan["total_frames"]
    expected_sec = total / fps
    dur = float(probe["format"].get("duration", 0))
    dec = decode_pass(film)
    blacks = black_intervals(film)
    # Fades at the head and tail are intended; any other black stretch is a defect.
    head = plan["shots"][0]["transition_in"]["frames"] / fps + 0.1
    tail = expected_sec - plan["shots"][-1]["fade_out_frames"] / fps - 0.1
    stray = [b for b in blacks if b["start"] > head and b["end"] < tail]
    checks = [
        _check("video codec", v.get("codec_name") == "h264", v.get("codec_name"), "h264"),
        _check("pixel format", v.get("pix_fmt") == "yuv420p", v.get("pix_fmt"), "yuv420p"),
        _check("resolution", (v.get("width"), v.get("height")) == (plan["width"], plan["height"]),
               f"{v.get('width')}x{v.get('height')}", f"{plan['width']}x{plan['height']}"),
        _check("frame rate", v.get("r_frame_rate") == f"{fps}/1", v.get("r_frame_rate"), f"{fps}/1"),
        _check("decoded video frames", str(v.get("nb_read_frames")) == str(total), v.get("nb_read_frames"), total),
        _check("container duration (s)", abs(dur - expected_sec) <= 0.05, round(dur, 3), f"{expected_sec:.3f}±0.05"),
        _check("audio codec", a.get("codec_name") == "aac", a.get("codec_name"), "aac"),
        _check("full decode pass", dec["returncode"] == 0 and not dec["errors"], dec, "returncode 0, no errors"),
        _check("no unintended black stretches", not stray, stray, "none outside the head fade-in / tail fade-out"),
    ]
    shots = []
    for s, r in zip(plan["shots"], shot_records):
        asset = s["asset"]
        on_disk = sha256_file((manifest_dir / asset["local_path"]).resolve())
        shots.append({
            "shot_id": s["shot_id"],
            "time_sec": [round(s["start_frame"] / fps, 3), round((s["start_frame"] + s["frames"]) / fps, 3)],
            "frames": s["frames"],
            "camera": s["camera"],
            "transition_in": s["transition_in"],
            "render": r,
            "asset": {k: asset.get(k) for k in ("id", "source_type", "url", "author", "licence", "attribution",
                                                 "rights_status", "verified_by", "sha256", "substitutes_for")},
            "asset_sha256_on_disk_matches": on_disk == asset.get("sha256"),
            "storyboard_asset_id": s["storyboard_asset_id"],
            "caption": s.get("caption"),
        })
    checks.append(_check("asset sha256 re-verified after render", all(x["asset_sha256_on_disk_matches"] for x in shots),
                         sum(x["asset_sha256_on_disk_matches"] for x in shots), len(shots)))
    checks.append(_check("every asset rights_status verified",
                         all(x["asset"]["rights_status"] == "verified" for x in shots),
                         [x["asset"]["rights_status"] for x in shots], "verified"))
    frames = sample_frames(film, plan, frames_dir)
    checks.append(_check("sampled mid-shot frames", all(f["ok"] for f in frames), sum(f["ok"] for f in frames),
                         len(frames)))
    status = "PASS" if all(c["result"] == "PASS" for c in checks) else "FAIL"
    standins = all(x["asset"]["source_type"] == "original_procedural" for x in shots)
    return {
        "schema": SCHEMA_QA_RECEIPT,
        "status": status,
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_id": plan["project_id"],
        "film": {"file": film.name, "sha256": sha256_file(film), "bytes": film.stat().st_size,
                 "width": v.get("width"), "height": v.get("height"), "fps": v.get("r_frame_rate"),
                 "frames": v.get("nb_read_frames"), "duration_sec": round(dur, 3),
                 "video": f"{v.get('codec_name')} {v.get('profile')}", "audio": f"{a.get('codec_name')} "
                 f"{a.get('sample_rate')} Hz {a.get('channels')} ch", "private": True},
        "plan_sha256": plan["plan_sha256"],
        "renderer": RENDERER_VERSION,
        "checks": checks,
        "shots": shots,
        "voice": VOICE_NONE,
        "cost": {"usd": 0.0, "paid_calls": 0, "network_calls_by_renderer": 0,
                 "note": "offline FFmpeg + Pillow on the session's container; no provider was called"},
        "milestones": {
            "technical_render": status,
            "realistic_photo_film": "BLOCKED" if standins else "NOT_ASSESSED",
            "realistic_photo_film_reason": REALISTIC_BLOCKED if standins else "",
            "narration": "BLOCKED",
            "narration_reason": VOICE_NONE["reason"],
            "owner_review": "PENDING (private; nothing published)",
        },
        "sampled_frames": frames,
        "black_intervals": blacks,
    }


def blocked_receipt(storyboard: Dict[str, Any], blocked: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "schema": SCHEMA_QA_RECEIPT,
        "status": "BLOCKED",
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "project_id": storyboard.get("project_id"),
        "film": None,
        "blocked": blocked,
        "reason": "rights gate: no shot renders without a verified asset whose file matches its sha256",
        "cost": {"usd": 0.0, "paid_calls": 0, "network_calls_by_renderer": 0},
    }
