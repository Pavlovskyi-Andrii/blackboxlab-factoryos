"""Narration for a Film Studio render (T-735, S2 of #433): one recorded or synthesized line per shot.

Contract `film-studio/narration/v1` (a JSON file next to the WAV lines, kept private with the render):

    {"schema": "film-studio/narration/v1", "project_id": "...",
     "voice": {"source": "piper" | "owner_recording", "model": "ru_RU-dmitri-medium", "model_sha256": "...",
               "dataset_licence": "CC0", "model_url": "https://...", "consent": "...", "notes": "..."},
     "lines": {"s01": {"path": "s01.wav", "sha256": "..."}, ...}}

Each line starts `LEAD_SEC` after its shot starts and must end before the shot ends (no line runs into the next
shot). A WAV whose sha256 does not match, a line for an unknown shot or a line that is too long is refused.
Synthesis (`python -m film_studio.narration --model voice.onnx --out DIR`) is offline: Piper runs locally on a
model file that is already on disk; nothing here downloads or calls a provider.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional

from .plan import sha256_file
from .schema import ValidationError

SCHEMA_NARRATION = "film-studio/narration/v1"
SOURCES = ("piper", "owner_recording")
LEAD_SEC = 0.25          # the line starts this long after the cut
TAIL_GAP_SEC = 0.2       # and ends at least this long before the next one
_SHA = re.compile(r"^[0-9a-f]{64}$")
_PATH = re.compile(r"^[A-Za-z0-9._-]{1,80}\.wav$")


def wav_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / float(w.getframerate())


def load(path: Path, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Validate a narration file against the plan; return {"voice", "lines": [{shot_id, path, start_sec, ...}]}."""
    path = Path(path)
    errors: List[str] = []
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValidationError("narration", [f"unreadable: {exc}"])
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA_NARRATION:
        raise ValidationError("narration", [f"schema: expected {SCHEMA_NARRATION!r}"])
    if set(doc) - {"schema", "project_id", "voice", "lines", "notes"}:
        errors.append(f"unknown keys {sorted(set(doc) - {'schema', 'project_id', 'voice', 'lines', 'notes'})}")
    if doc.get("project_id") != plan["project_id"]:
        errors.append("project_id differs from the render plan")
    voice = doc.get("voice")
    if not isinstance(voice, dict) or voice.get("source") not in SOURCES:
        errors.append(f"voice.source: one of {list(SOURCES)}")
        voice = {}
    elif voice["source"] == "piper":
        for k in ("model", "model_sha256", "dataset_licence", "model_url"):
            if not voice.get(k):
                errors.append(f"voice.{k}: required for a synthesized voice")
        if voice.get("model_sha256") and not _SHA.match(str(voice["model_sha256"])):
            errors.append("voice.model_sha256: 64 lowercase hex characters")
    elif not voice.get("consent"):
        errors.append("voice.consent: an owner recording needs the owner's consent note")
    shots = {s["shot_id"]: s for s in plan["shots"]}
    fps = plan["fps"]
    starts, t = {}, 0
    for s in plan["shots"]:
        starts[s["shot_id"]] = t
        t += s["frames"]
    lines_in = doc.get("lines")
    if not isinstance(lines_in, dict) or not lines_in:
        errors.append("lines: a non-empty object {shot_id: {path, sha256}}")
        lines_in = {}
    out: List[Dict[str, Any]] = []
    for sid, line in sorted(lines_in.items()):
        if sid not in shots:
            errors.append(f"lines.{sid}: unknown shot")
            continue
        if not isinstance(line, dict) or not _PATH.match(str(line.get("path") or "")) \
                or not _SHA.match(str(line.get("sha256") or "")):
            errors.append(f"lines.{sid}: needs a plain .wav file name and its sha256")
            continue
        wav = path.parent / line["path"]
        if not wav.is_file():
            errors.append(f"lines.{sid}: {line['path']} is missing")
            continue
        if sha256_file(wav) != line["sha256"]:
            errors.append(f"lines.{sid}: sha256 mismatch (file changed after the narration was approved)")
            continue
        try:
            dur = wav_seconds(wav)
        except (wave.Error, EOFError) as exc:
            errors.append(f"lines.{sid}: not a PCM WAV ({exc})")
            continue
        room = shots[sid]["frames"] / fps - LEAD_SEC - TAIL_GAP_SEC
        if dur > room:
            errors.append(f"lines.{sid}: {dur:.2f} s does not fit the shot ({room:.2f} s available)")
            continue
        out.append({"shot_id": sid, "path": str(wav.resolve()), "sha256": line["sha256"],
                    "start_sec": round(starts[sid] / fps + LEAD_SEC, 3), "duration_sec": round(dur, 3)})
    if errors:
        raise ValidationError("narration", errors)
    return {"voice": {k: v for k, v in voice.items() if isinstance(v, (str, int, float))}, "lines": out,
            "file_sha256": sha256_file(path)}


def synthesize_piper(storyboard: Dict[str, Any], model: Path, out: Path, *, dataset_licence: str, model_url: str,
                     language: str = "ru") -> Path:
    """Write one WAV per shot from `voiceover_<language>` with a local Piper model, plus narration.json."""
    from piper import PiperVoice  # optional dependency, only for synthesis

    out.mkdir(parents=True, exist_ok=True)
    voice = PiperVoice.load(str(model))
    lines = {}
    for shot in storyboard["shots"]:
        text = shot.get(f"voiceover_{language}")
        if not text:
            continue
        wav = out / f"{shot['shot_id']}.wav"
        with wave.open(str(wav), "wb") as w:
            voice.synthesize_wav(text, w)
        lines[shot["shot_id"]] = {"path": wav.name, "sha256": sha256_file(wav)}
    doc = {"schema": SCHEMA_NARRATION, "project_id": storyboard["project_id"],
           "voice": {"source": "piper", "model": Path(model).name.replace(".onnx", ""),
                     "model_sha256": sha256_file(Path(model)), "dataset_licence": dataset_licence,
                     "model_url": model_url, "notes": "synthesized offline with Piper; text = storyboard voiceover"},
           "lines": lines}
    target = out / "narration.json"
    target.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def main(argv: Optional[List[str]] = None) -> int:
    from .render import SHOTPACK, guard_private_output, RenderError

    p = argparse.ArgumentParser(prog="python -m film_studio.narration",
                                description="Synthesize the storyboard narration offline with a local Piper model.")
    p.add_argument("--model", required=True, help="local Piper .onnx model (its .onnx.json next to it)")
    p.add_argument("--out", required=True, help="private output directory (outside the repository)")
    p.add_argument("--dataset-licence", required=True, help="licence of the voice's training data, from its MODEL_CARD")
    p.add_argument("--model-url", required=True, help="where the model was downloaded from")
    p.add_argument("--storyboard", default=str(SHOTPACK / "storyboard.json"))
    a = p.parse_args(argv)
    try:
        guard_private_output(Path(a.out))
    except RenderError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    storyboard = json.loads(Path(a.storyboard).read_text(encoding="utf-8"))
    target = synthesize_piper(storyboard, Path(a.model), Path(a.out), dataset_licence=a.dataset_licence,
                              model_url=a.model_url)
    print(target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
