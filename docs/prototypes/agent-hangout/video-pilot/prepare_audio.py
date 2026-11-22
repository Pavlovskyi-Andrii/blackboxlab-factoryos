"""Audio analysis for scene B (#220): per-frame loudness + who-speaks-when captions, from a real MP3.

Usage: python prepare_audio.py <episode.json> <audio.mp3> <start_s> <duration_s> <fps> <out_dir>
Writes <out_dir>/clip.wav (the trimmed audio) and <out_dir>/data.json for scene_b.html.

Speaker timing is measured, not guessed: ffmpeg silencedetect finds the pauses, and the episode's sentences
(in script order, with their host A/B) are mapped onto the detected speech intervals. If the counts disagree,
sentences are spread over the speech time by length, and data.json says so (timing: "estimated").
"""
from __future__ import annotations

import array
import json
import math
import re
import subprocess
import sys
from pathlib import Path


def speech_intervals(audio: Path, start: float, dur: float) -> list[tuple[float, float]]:
    log = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(start), "-t", str(dur), "-i", str(audio),
                          "-af", "silencedetect=noise=-35dB:d=0.3", "-f", "null", "-"],
                         capture_output=True, text=True, check=True).stderr
    marks = [(m.group(1), float(m.group(2))) for m in re.finditer(r"silence_(start|end): ([0-9.]+)", log)]
    speech, cursor = [], 0.0
    for kind, t in marks:
        if kind == "start" and t - cursor > 0.15:
            speech.append((cursor, t))
        if kind == "end":
            cursor = t
    if dur - cursor > 0.15 and (not marks or marks[-1][0] == "end"):
        speech.append((cursor, dur))
    return speech


def loudness(wav_pcm: bytes, rate: int, fps: int, frames: int) -> list[float]:
    samples = array.array("h", wav_pcm)
    hop = rate // fps
    out = []
    for i in range(frames):
        chunk = samples[i * hop:(i + 1) * hop]
        out.append(math.sqrt(sum(s * s for s in chunk) / len(chunk)) / 32768 if chunk else 0.0)
    peak = max(out) or 1.0
    return [round(min(1.0, v / peak), 3) for v in out]


def main() -> int:
    episode, audio, start, dur, fps, out = sys.argv[1:7]
    start, dur, fps, out = float(start), float(dur), int(fps), Path(out)
    out.mkdir(parents=True, exist_ok=True)
    ep = json.loads(Path(episode).read_text(encoding="utf-8"))
    hosts = {k: v.get("name", k) for k, v in (ep.get("hosts") or {}).items()}
    sentences = [(host, s.strip()) for host, text in ep["lines"]
                 for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    speech = speech_intervals(Path(audio), start, dur)
    used = sentences[:len(speech)]
    timing = "measured"
    if len(used) < len(speech):  # more pauses than sentences in the window: spread by length instead
        timing = "estimated"
        total = sum(len(s) for _, s in sentences)
        speak = speech[-1][1] - speech[0][0]
        t, used_speech = speech[0][0], []
        for host, s in sentences:
            d = speak * len(s) / total
            used_speech.append((t, t + d))
            t += d
        speech, used = used_speech, sentences
    captions = [{"start": round(a, 2), "end": round(b, 2), "host": h, "name": hosts.get(h, h), "text": s}
                for (a, b), (h, s) in zip(speech, used) if a < dur]
    rate = 22050
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", audio, "-ac", "1", "-ar", str(rate),
                          "-f", "s16le", "-"], capture_output=True, check=True).stdout
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", audio, "-ac", "1",
                    str(out / "clip.wav")], check=True)
    frames = int(round(dur * fps))
    data = {"duration": dur, "fps": fps, "timing": timing, "captions": captions, "level": loudness(pcm, rate, fps, frames),
            "source": {"episode": ep.get("id"), "title": ep.get("title"), "voice_model": ep.get("voice_model"),
                       "clip": f"{start:.2f}s + {dur:.2f}s"}}
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(f"{len(captions)} captions ({timing}), {frames} loudness frames")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
