"""Render a MyCast episode script (JSON) into one audio file with two Piper voices.

Zero spend: Piper is an open-source local TTS; this runs on a CI runner, not on the EC2 worker.
Usage: python tools/mycast_render.py EPISODE.json MODEL.onnx OUT_DIR
Writes OUT_DIR/<id>.wav and OUT_DIR/<id>.md (transcript + sources).
"""
from __future__ import annotations

import json
import sys
import wave
from pathlib import Path

PAUSE_SECONDS = 0.45


def synthesize(voice, text: str, speaker_id: int, path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        try:  # piper-tts >= 1.3
            from piper import SynthesisConfig
            voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(speaker_id=speaker_id))
        except ImportError:  # piper-tts 1.2
            voice.synthesize(text, wav_file, speaker_id=speaker_id)


def main(episode_path: str, model_path: str, out_dir: str) -> int:
    from piper import PiperVoice

    episode = json.loads(Path(episode_path).read_text(encoding="utf-8"))
    config = json.loads(Path(model_path + ".json").read_text(encoding="utf-8"))
    speakers = config.get("speaker_id_map") or {}
    voice = PiperVoice.load(model_path)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    parts = []
    for n, (host, text) in enumerate(episode["lines"]):
        name = episode["hosts"][host]["speaker"]
        part = out / f"part-{n:03d}.wav"
        synthesize(voice, text, int(speakers[name]), part)
        parts.append(part)

    final = out / f"{episode['id']}.wav"
    with wave.open(str(parts[0]), "rb") as first:
        params = first.getparams()
    silence = b"\x00" * int(params.framerate * PAUSE_SECONDS) * params.sampwidth * params.nchannels
    with wave.open(str(final), "wb") as dst:
        dst.setparams(params)
        for part in parts:
            with wave.open(str(part), "rb") as src:
                dst.writeframes(src.readframes(src.getnframes()))
            dst.writeframes(silence)
            part.unlink()
    with wave.open(str(final), "rb") as check:
        seconds = check.getnframes() / check.getframerate()

    hosts = episode["hosts"]
    transcript = [f"# {episode['title']}", "", f"_{episode.get('note', '')}_", "", f"Тривалість: {seconds:.0f} с", ""]
    transcript += [f"**{hosts[h]['name']}:** {t}" for h, t in episode["lines"]]
    transcript += ["", "## Джерела"] + [f"- [{s['title']}]({s['url']}) — {s['date']}" for s in episode.get("sources", [])]
    (out / f"{episode['id']}.md").write_text("\n".join(transcript) + "\n", encoding="utf-8")
    print(f"rendered {final} ({seconds:.1f} s, {len(parts)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
