#!/usr/bin/env bash
# #220 video pilot: render both private test videos with $0 incremental cost.
# Needs: node + Playwright/Chromium (preinstalled in Claude cloud sessions; `npx playwright install chromium` elsewhere),
# ffmpeg/ffprobe, python3. No network, no paid service, no generation credits.
#
#   ./render.sh [out_dir]          # default out_dir: ./out (gitignored)
#
# Outputs: teaser_a_16x9.mp4, podcast_b_16x9.mp4, podcast_b_9x16.mp4, poster frames and probe.txt (ffprobe evidence).
set -euo pipefail
cd "$(dirname "$0")"
OUT="${1:-out}"; FPS=30
mkdir -p "$OUT"
EP=../../mycast/episodes/2026-11-02.json        # committed pilot script (synthetic hosts)
MP3=../../mycast/audio/2026-11-02.mp3           # committed pilot audio (Piper TTS, owner-only pilot already in repo)

encode() { # frames_dir out.mp4 [audio]
  local frames=$1 dst=$2 audio=${3:-}
  if [[ -n "$audio" ]]; then
    ffmpeg -v error -y -framerate $FPS -i "$frames/f_%05d.jpg" -i "$audio" -map 0:v -map 1:a \
      -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -c:a aac -b:a 128k -ar 44100 -shortest -movflags +faststart "$dst"
  else  # silent teaser still carries an AAC track (silence) so every player treats it the same
    ffmpeg -v error -y -framerate $FPS -i "$frames/f_%05d.jpg" -f lavfi -i anullsrc=r=44100:cl=stereo -map 0:v -map 1:a \
      -c:v libx264 -preset slow -crf 20 -pix_fmt yuv420p -c:a aac -b:a 64k -shortest -movflags +faststart "$dst"
  fi
}

echo "== A: cinematic teaser (10 s, 1280x720)"
node render_frames.js scene_a.html "$OUT/frames_a" $FPS 1280 720
encode "$OUT/frames_a" "$OUT/teaser_a_16x9.mp4"
cp "$OUT/frames_a/f_00280.jpg" "$OUT/poster_a.jpg"

echo "== B: audio-reactive podcast scene (17 s, measured speaker timing)"
python3 prepare_audio.py "$EP" "$MP3" 0.9 17 $FPS "$OUT/audio_b"
node render_frames.js scene_b.html "$OUT/frames_b" $FPS 1280 720 "$OUT/audio_b/data.json"
encode "$OUT/frames_b" "$OUT/podcast_b_16x9.mp4" "$OUT/audio_b/clip.wav"
cp "$OUT/frames_b/f_00285.jpg" "$OUT/poster_b.jpg"
node render_frames.js scene_b.html "$OUT/frames_b_v" $FPS 720 1280 "$OUT/audio_b/data.json"
encode "$OUT/frames_b_v" "$OUT/podcast_b_9x16.mp4" "$OUT/audio_b/clip.wav"
cp "$OUT/frames_b_v/f_00285.jpg" "$OUT/poster_b_9x16.jpg"

echo "== ffprobe evidence"
: > "$OUT/probe.txt"
for f in "$OUT"/*.mp4; do
  {
    echo "### $(basename "$f")  $(stat -c %s "$f") bytes"
    ffprobe -v error -show_entries format=duration,format_name:stream=codec_type,codec_name,profile,width,height,r_frame_rate,pix_fmt,sample_rate,channels -of default=nw=1 "$f"
    # faststart: the moov atom must come before mdat
    python3 - "$f" <<'PY'
import sys
data = open(sys.argv[1], "rb").read(64 * 1024)
m, d = data.find(b"moov"), data.find(b"mdat")
print("faststart=" + ("yes" if m != -1 and (d == -1 or m < d) else "no"))
PY
  } >> "$OUT/probe.txt"
done
cat "$OUT/probe.txt"
rm -rf "$OUT"/frames_*
