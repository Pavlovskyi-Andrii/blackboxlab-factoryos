"""Offline FFmpeg Photo Cinema renderer (T-730).

    python -m film_studio.render --out DIR --procedural-standins [--proxy] [--only s03]
    python -m film_studio.render --out DIR --manifest asset_manifest.json      (verified licensed/owner assets)

Each shot: still -> 2.5D camera move (zoompan on a 2x oversampled still, plus a foreground layer moving faster
for parallax when the asset has one) -> code-drawn title, DEMO label and captions -> its own H.264 clip, cached by
content. Assembly joins the clips with crossfades into an exact-length H.264/AAC MP4. No network, no paid calls.
Captions reach FFmpeg through text files (`textfile=`, `expansion=none`), so storyboard text is never parsed as
filter syntax. Exit codes: 0 PASS, 3 BLOCKED (rights), 4 QA FAIL, 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import RENDERER_VERSION
from .plan import PlanError, RightsBlocked, build_plan, sha256_file
from .schema import ValidationError, manifest_from_candidates, validate_asset_manifest

REPO = Path(__file__).resolve().parent.parent
SHOTPACK = REPO / "docs/storyboards/blackbox-lab-45s"
FONT_DIRS = ("/usr/share/fonts/truetype/dejavu", "/usr/share/fonts/dejavu", "/usr/share/fonts/TTF")
PROXY = (1280, 720)
# How far the camera travels: fraction of the free margin (pan) and of the parallax layer's extra width.
PAN = {"subtle_pan_right": (0.2, 0.8), "subtle_pan_left": (0.8, 0.2), "slow_orbit_2_5d": (0.25, 0.75)}
FG_PATH = {
    "slow_dolly_in": (0.40, 0.60), "slow_pull_out": (0.60, 0.40), "subtle_pan_right": (0.10, 0.90),
    "subtle_pan_left": (0.90, 0.10), "slow_orbit_2_5d": (0.95, 0.05), "static_with_graphic": (0.5, 0.5),
}
FG_EXTRA = 0.14
STANDIN_NOTE = {"ru": "иллюстрация, не фото", "uk": "ілюстрація, не фото", "en": "illustration, not a photo"}
BRAND_LINE = "BLACKBOX LAB  //  FACTORYOS"


class RenderError(RuntimeError):
    pass


def find_fonts() -> Dict[str, str]:
    for d in FONT_DIRS:
        reg, bold = Path(d) / "DejaVuSans.ttf", Path(d) / "DejaVuSans-Bold.ttf"
        if reg.is_file() and bold.is_file():
            return {"regular": str(reg), "bold": str(bold)}
    raise RenderError("DejaVu Sans fonts not found (Film Bible typography); install fonts-dejavu-core")


def ffmpeg_available() -> bool:
    return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _ease(var: str, span: float) -> str:
    return f"(1-cos(PI*min({var}/{span:.6f},1)))/2"


def camera_expressions(preset: str, zoom_max: float, frames: int) -> Dict[str, str]:
    """zoompan z/x/y expressions; `on` is the output frame number, eased with a cosine in/out."""
    e = _ease("on", max(1, frames - 1))
    zm = f"{zoom_max:.4f}"
    if preset == "slow_dolly_in":
        z = f"1+({zm}-1)*{e}"
    elif preset == "slow_pull_out":
        z = f"{zm}-({zm}-1)*{e}"
    elif preset in ("subtle_pan_right", "subtle_pan_left"):
        z = zm
    elif preset == "slow_orbit_2_5d":
        z = f"1+({zm}-1)*(0.55+0.45*{e})"
    elif preset == "static_with_graphic":
        z = f"1+({zm}-1)*0.3"
    else:
        raise RenderError(f"unknown camera preset {preset!r}")
    a, b = PAN.get(preset, (0.5, 0.5))
    x = f"(iw-iw/zoom)*({a}+({b - a:.3f})*{e})"
    y = "(ih-ih/zoom)/2"
    return {"z": z, "x": x, "y": y}


def caption_lines(text: Optional[str], width: int = 52) -> str:
    return "\n".join(textwrap.wrap(" ".join((text or "").split()), width=width)) if text else ""


def _text_filter(textfile: str, font: str, size: int, color: str, x: str, y: str, extra: str = "") -> str:
    return (f"drawtext=textfile={textfile}:expansion=none:fontfile={font}:fontsize={size}:fontcolor={color}"
            f":x={x}:y={y}" + (":" + extra if extra else ""))


def shot_command(plan: Dict[str, Any], shot: Dict[str, Any], *, manifest_dir: Path, work: Path,
                 out_clip: Path, fonts: Dict[str, str]) -> List[str]:
    """Write the shot's text files under `work/text` and return its FFmpeg argv (run with cwd=work)."""
    W, H, fps = plan["width"], plan["height"], plan["fps"]
    k = H / 1080
    L = shot["frames"] + shot["tail_frames"]
    secs = L / fps
    asset = shot["asset"]
    bg = (manifest_dir / asset["local_path"]).resolve()
    fg_rel = ((asset.get("layers") or {}).get("foreground") or {}).get("local_path")
    cam = camera_expressions(shot["camera"]["preset"], float(shot["camera"]["zoom_max"]), L)

    tdir = work / "text"
    tdir.mkdir(parents=True, exist_ok=True)
    sid = shot["shot_id"]
    files = {}

    def put(name: str, value: str) -> str:
        rel = f"text/{sid}.{name}.txt"
        (work / rel).write_text(value, encoding="utf-8")
        files[name] = rel
        return rel

    label = None
    if asset.get("source_type") == "original_procedural":
        label = f"{plan['demo_text']} · {STANDIN_NOTE.get(plan['language'], STANDIN_NOTE['en'])}"
    elif shot.get("demo_label"):
        label = shot["demo_label"]

    chain = [f"scale={2 * W}:{2 * H}:flags=lanczos",
             f"zoompan=z='{cam['z']}':x='{cam['x']}':y='{cam['y']}':d={L}:s={W}x{H}:fps={fps}", "setsar=1"]
    graph = [f"[0:v]{','.join(chain)}[bg]"]
    last = "bg"
    argv = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(bg)]
    if fg_rel:
        fg = (manifest_dir / fg_rel).resolve()
        argv += ["-loop", "1", "-framerate", str(fps), "-t", f"{secs:.6f}", "-i", str(fg)]
        fw, fh = int(round(W * (1 + FG_EXTRA) / 2)) * 2, int(round(H * (1 + FG_EXTRA) / 2)) * 2
        a, b = FG_PATH[shot["camera"]["preset"]]
        span = max(1, L - 1) / fps
        fx = f"-({fw - W})*({a}+({b - a:.3f})*{_ease('t', span)})"
        graph.append(f"[1:v]scale={fw}:{fh}:flags=lanczos,format=rgba[fg]")
        graph.append(f"[bg][fg]overlay=x='{fx}':y=-{(fh - H) // 2}:shortest=1:eval=frame[par]")
        last = "par"
    fx_text = []
    fx_text.append(_text_filter(put("brand", BRAND_LINE), fonts["bold"], round(24 * k), "0x39d9e9",
                                f"{round(96 * k)}", f"{round(70 * k)}", "shadowx=2:shadowy=2:shadowcolor=black@0.6"))
    if label:
        fx_text.append(_text_filter(put("label", label), fonts["bold"], round(24 * k), "0x061019",
                                    f"w-tw-{round(96 * k)}", f"{round(64 * k)}",
                                    f"box=1:boxcolor=0xf2a96a@0.92:boxborderw={round(12 * k)}"))
    if shot.get("title"):
        fade_in = "if(lt(t\\,0.3)\\,0\\,if(lt(t\\,0.9)\\,(t-0.3)/0.6\\,1))"
        fx_text.append(_text_filter(put("title", shot["title"]), fonts["bold"], round(62 * k), "0xdcefff",
                                    f"{round(96 * k)}", f"h-{round(330 * k)}",
                                    f"alpha='{fade_in}':shadowx=3:shadowy=3:shadowcolor=black@0.7"))
    cap = caption_lines(shot.get("caption"))
    if cap:
        fx_text.append(_text_filter(put("caption", cap), fonts["regular"], round(36 * k), "white",
                                    "(w-tw)/2", f"h-th-{round(92 * k)}",
                                    f"line_spacing={round(10 * k)}:box=1:boxcolor=black@0.5:boxborderw={round(18 * k)}"))
    tail = list(fx_text)
    t_in = shot["transition_in"]
    if t_in["type"] == "fade_from_black" and t_in["frames"]:
        tail.append(f"fade=t=in:st=0:d={t_in['frames'] / fps:.6f}")
    if shot.get("fade_out_frames"):
        fo = shot["fade_out_frames"]
        tail.append(f"fade=t=out:st={(L - fo) / fps:.6f}:d={fo / fps:.6f}")
    tail.append("format=yuv420p")
    graph.append(f"[{last}]{','.join(tail)}[v]")
    argv += ["-filter_complex", ";".join(graph), "-map", "[v]", "-frames:v", str(L), "-r", str(fps),
             "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-an",
             "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", str(out_clip)]
    return argv


LOUDNESS = {"I": -16.0, "TP": -1.5, "LRA": 11.0}   # web/podcast target, measured again by the QA receipt


def assemble_command(plan: Dict[str, Any], clips: Sequence[Path], out_mp4: Path,
                     narration: Optional[Sequence[Dict[str, Any]]] = None) -> List[str]:
    """Join shot clips (crossfade or cut) and add the audio: a silent bed, plus each narration line placed at its
    shot (adelay) and the mix normalised to LOUDNESS. The result is exactly total_frames long."""
    fps, shots = plan["fps"], plan["shots"]
    if len(clips) != len(shots):
        raise RenderError("one clip per shot is required")
    argv = ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y"]
    for c in clips:
        argv += ["-i", str(c)]
    duration = plan["total_frames"] / fps
    argv += ["-f", "lavfi", "-t", f"{duration:.6f}", "-i", "anullsrc=r=48000:cl=stereo"]
    lines = list(narration or [])
    for line in lines:
        argv += ["-i", str(line["path"])]
    graph = [f"[{i}:v]settb=AVTB,setpts=PTS-STARTPTS[c{i}]" for i in range(len(clips))]
    bed = len(clips)
    audio_map = f"{bed}:a"
    if lines:
        labels = []
        for k, line in enumerate(lines):
            ms = int(round(float(line["start_sec"]) * 1000))
            graph.append(f"[{bed + 1 + k}:a]aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,"
                         f"adelay={ms}|{ms}[n{k}]")
            labels.append(f"[n{k}]")
        graph.append(f"[{bed}:a]{''.join(labels)}amix=inputs={len(lines) + 1}:duration=first:normalize=0:"
                     f"dropout_transition=0,loudnorm=I={LOUDNESS['I']}:TP={LOUDNESS['TP']}:LRA={LOUDNESS['LRA']},"
                     f"aresample=48000,apad,atrim=0:{duration:.6f}[aout]")
        audio_map = "[aout]"
    cur, elapsed = "c0", shots[0]["frames"]
    for i in range(1, len(shots)):
        t_in = shots[i]["transition_in"]
        nxt = f"j{i}"
        if t_in["type"] == "crossfade" and t_in["frames"]:
            graph.append(f"[{cur}][c{i}]xfade=transition=fade:duration={t_in['frames'] / fps:.6f}"
                         f":offset={elapsed / fps:.6f}[{nxt}]")
        else:
            graph.append(f"[{cur}][c{i}]concat=n=2:v=1:a=0[{nxt}]")
        cur = nxt
        elapsed += shots[i]["frames"]
    graph.append(f"[{cur}]fps={fps},format=yuv420p[vout]")
    argv += ["-filter_complex", ";".join(graph), "-map", "[vout]", "-map", audio_map,
             "-frames:v", str(plan["total_frames"]), "-r", str(fps),
             "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-profile:v", "high", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-t", f"{duration:.6f}",
             "-map_metadata", "-1", "-metadata", "comment=FactoryOS Film Studio private DEMO render, not for publication",
             "-movflags", "+faststart", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
             str(out_mp4)]
    return argv


def run(argv: List[str], cwd: Path, timeout: int = 900) -> None:
    proc = subprocess.run(argv, cwd=str(cwd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                          timeout=timeout)
    if proc.returncode != 0:
        raise RenderError(f"{argv[0]} failed ({proc.returncode}): {proc.stderr.strip()[-1500:]}")


def guard_private_output(out: Path) -> None:
    """The film stays private: never inside the repository (git, /static) except the ignored data/ directory."""
    out = out.resolve()
    try:
        rel = out.relative_to(REPO)
    except ValueError:
        return
    if not rel.parts or rel.parts[0] != "data":
        raise RenderError(f"--out {out} is inside the repository; use a directory outside it (or data/)")


def clip_path(work: Path, shot: Dict[str, Any]) -> Path:
    return work / "shots" / f"{shot['shot_id']}-{shot['cache_key'][:16]}.mp4"


def render_shots(plan: Dict[str, Any], *, manifest_dir: Path, work: Path, only: Sequence[str] = (),
                 fonts: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
    """Render missing shot clips and those named in `only`; reuse the rest. Returns per-shot status records."""
    fonts = fonts or find_fonts()
    unknown = sorted(set(only) - {s["shot_id"] for s in plan["shots"]})
    if unknown:
        raise RenderError(f"--only names unknown shots {unknown}")
    (work / "shots").mkdir(parents=True, exist_ok=True)
    records = []
    for shot in plan["shots"]:
        clip = clip_path(work, shot)
        if clip.is_file() and shot["shot_id"] not in only:
            status = "cached"
        else:
            tmp = clip.with_suffix(".part.mp4")
            run(shot_command(plan, shot, manifest_dir=manifest_dir, work=work, out_clip=tmp, fonts=fonts), work)
            tmp.replace(clip)
            status = "rendered"
        records.append({"shot_id": shot["shot_id"], "status": status, "clip": str(clip.relative_to(work)),
                        "clip_sha256": sha256_file(clip), "frames": shot["frames"] + shot["tail_frames"]})
    return records


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main(argv: Optional[List[str]] = None) -> int:
    from . import qa
    from .procedural import generate, shots_from_shotpack

    p = argparse.ArgumentParser(prog="python -m film_studio.render", description=__doc__.split("\n\n")[0])
    p.add_argument("--out", required=True, help="private output directory (outside the repository)")
    p.add_argument("--storyboard", default=str(SHOTPACK / "storyboard.json"))
    p.add_argument("--bible", default=str(SHOTPACK / "film_bible.json"))
    p.add_argument("--candidates", default=str(SHOTPACK / "asset_candidates.json"))
    p.add_argument("--manifest", help="asset manifest v1 (verified assets); default: the shot pack candidates")
    p.add_argument("--procedural-standins", action="store_true",
                   help="render every shot from an original procedural still (labelled, not a photo)")
    p.add_argument("--proxy", action="store_true", help="1280x720 proxy instead of the storyboard size")
    p.add_argument("--only", action="append", default=[], help="re-render this shot (repeatable)")
    p.add_argument("--crossfade", type=float, default=0.5, help="crossfade seconds at storyboard cuts (0 = cut)")
    p.add_argument("--dry-run", action="store_true", help="validate and print the plan; run nothing")
    p.add_argument("--narration", help="narration.json (film-studio/narration/v1): one WAV line per shot")
    a = p.parse_args(argv)

    out = Path(a.out)
    try:
        guard_private_output(out)
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    storyboard, bible = _load(Path(a.storyboard)), _load(Path(a.bible))
    overrides: Dict[str, str] = {}
    if a.procedural_standins:
        adir = out / "assets"
        mpath = adir / "asset_manifest.json"
        candidates = _load(Path(a.candidates))
        if not mpath.is_file():
            generate(adir, shots_from_shotpack(storyboard, candidates), storyboard["project_id"])
        manifest, mdir = validate_asset_manifest(_load(mpath)), adir
        for asset in manifest["assets"]:
            for s in storyboard["shots"]:
                if asset.get("substitutes_for") == s["asset_id"] and asset["id"].startswith(f"orig-{s['shot_id']}-"):
                    overrides[s["shot_id"]] = asset["id"]
    elif a.manifest:
        manifest, mdir = validate_asset_manifest(_load(Path(a.manifest))), Path(a.manifest).resolve().parent
        # A manifest asset that `substitutes_for` a storyboard asset replaces it in that shot (e.g. an owner photo).
        for asset in manifest["assets"]:
            for s in storyboard["shots"]:
                if asset.get("substitutes_for") == s["asset_id"]:
                    overrides[s["shot_id"]] = asset["id"]
    else:
        manifest, mdir = manifest_from_candidates(_load(Path(a.candidates))), Path(a.candidates).resolve().parent

    size = PROXY if a.proxy else None
    try:
        plan = build_plan(storyboard, bible, manifest, manifest_dir=mdir, size=size, crossfade_sec=a.crossfade,
                          overrides=overrides)
    except RightsBlocked as exc:
        receipt = qa.blocked_receipt(storyboard, exc.blocked)
        (out / "qa_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({"status": "BLOCKED", "blocked": exc.blocked}, ensure_ascii=False, indent=2))
        return 3
    except (ValidationError, PlanError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    (out / "render_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    voice = None
    if a.narration:
        from .narration import load as load_narration
        try:
            voice = load_narration(Path(a.narration), plan)
        except ValidationError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
    if a.dry_run:
        fonts = {"regular": "DejaVuSans.ttf", "bold": "DejaVuSans-Bold.ttf"}
        cmds = [shot_command(plan, s, manifest_dir=mdir, work=out, out_clip=clip_path(out, s), fonts=fonts)
                for s in plan["shots"]]
        print(json.dumps({"plan_sha256": plan["plan_sha256"], "total_frames": plan["total_frames"],
                          "commands": cmds}, ensure_ascii=False, indent=1))
        return 0
    if not ffmpeg_available():
        print("ERROR: ffmpeg/ffprobe not installed", file=sys.stderr)
        return 2
    records = render_shots(plan, manifest_dir=mdir, work=out, only=a.only)
    film = out / "film.mp4"
    tmp = out / "film.part.mp4"
    run(assemble_command(plan, [out / r["clip"] for r in records], tmp, (voice or {}).get("lines")), out)
    tmp.replace(film)
    receipt = qa.run_qa(film, plan, records, manifest_dir=mdir, frames_dir=out / "frames", narration=voice)
    (out / "qa_receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("status", "film", "milestones")}, ensure_ascii=False, indent=2))
    return 0 if receipt["status"] == "PASS" else 4


if __name__ == "__main__":
    sys.exit(main())
