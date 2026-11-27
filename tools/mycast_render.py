"""Render a MyCast episode script (JSON) into one audio file with two Piper voices.

Zero spend: Piper is an open-source local TTS; this runs on a CI runner, not on the EC2 worker.
Usage: python tools/mycast_render.py EPISODE.json MODEL.onnx OUT_DIR
       python tools/mycast_render.py --batch LIST MODEL.onnx OUT_DIR   (LIST = NUL-separated episode paths)
Writes OUT_DIR/<id>.md (transcript + sources) and, only when the audio passes QA and the MP3 decodes with the
right length, OUT_DIR/<id>.wav and OUT_DIR/<id>.mp3. Each episode is rendered on its own. FFmpeg does the MP3;
it comes from the imageio-ffmpeg pip package when that is installed (no apt, no ffprobe needed).

The Ukrainian Piper voice reads raw characters and knows lowercase Cyrillic only: Latin words, capital letters and
digits are dropped without an error. `speakable` rewrites the text for the voice (the transcript keeps the original),
and `audio_problems` refuses silent, truncated or wrongly sized audio instead of uploading it.
"""
from __future__ import annotations

import array
import json
import re
import sys
import unicodedata
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: the shared chapter timecodes
from mycast_chapters import caption_block  # noqa: E402

PAUSE_SECONDS = 0.45

# Audio QA thresholds: the same values as the server-side preflight in mycast.py (test_mycast_render keeps them equal).
QC_WORDS_PER_MINUTE = 140
QC_DURATION_RATIO = (0.45, 2.2)
QC_MAX_SILENCE_SECONDS = 6.0
QC_SILENCE_RMS = 160
QC_CHUNK_CHARS_PER_SECOND = 14.0
QC_CHUNK_MIN_RATIO = 0.35
QC_MIN_VOICED_SHARE = 0.3

EDITORIAL_LABEL = "думка ведучих, не джерело"

# Brand and product names the hosts say every day, as they sound in Ukrainian.
SPOKEN_NAMES = {
    "openai": "оупен ей ай", "chatgpt": "чат джі пі ті", "gpt": "джі пі ті", "claude": "клод", "code": "код",
    "anthropic": "антропік", "gemini": "джеміні", "google": "гугл", "microsoft": "майкрософт",
    "factoryos": "фекторі о ес", "github": "гітхаб", "telegram": "телеграм", "mycast": "майкаст",
    "blackbox": "блекбокс", "lab": "леб", "relay": "рілей", "launchpad": "лаунчпед", "codex": "кодекс",
    "nasdaq": "насдак", "the": "зе", "ai": "ей ай", "news": "ньюз", "flash": "флеш", "youtube": "ютуб",
}
LETTER_NAMES = {
    "a": "ей", "b": "бі", "c": "сі", "d": "ді", "e": "і", "f": "еф", "g": "джі", "h": "ейч", "i": "ай", "j": "джей",
    "k": "кей", "l": "ел", "m": "ем", "n": "ен", "o": "оу", "p": "пі", "q": "кю", "r": "ар", "s": "ес", "t": "ті",
    "u": "ю", "v": "ві", "w": "дабл ю", "x": "ікс", "y": "вай", "z": "зед",
}
DIGRAPHS = (("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("oo", "у"), ("ee", "і"), ("ck", "к"), ("qu", "кв"))
LATIN = dict(zip("abcdefghijklmnopqrstuvwxyz",
                 ["а", "б", "к", "д", "е", "ф", "г", "х", "і", "дж", "к", "л", "м", "н", "о", "п", "к", "р", "с", "т",
                  "у", "в", "в", "кс", "і", "з"]))
ONES = ["нуль", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять", "десять", "одинадцять",
        "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять",
        "дев'ятнадцять"]
TENS = ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят", "вісімдесят", "дев'яносто"]
HUNDREDS = ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот", "дев'ятсот"]
THOUSANDS = ["", "тисяча", "дві тисячі", "три тисячі", "чотири тисячі", "п'ять тисяч", "шість тисяч", "сім тисяч",
             "вісім тисяч", "дев'ять тисяч"]
APOSTROPHES = "'ʼ’`"


def number_words(digits: str) -> str:
    """Cardinal in words up to 9999; longer numbers and ones with a leading zero are read digit by digit."""
    if len(digits) > 4 or (len(digits) > 1 and digits[0] == "0"):
        return " ".join(ONES[int(d)] for d in digits)
    n = int(digits)
    if n < 20:
        return ONES[n]
    words = [THOUSANDS[n // 1000], HUNDREDS[n // 100 % 10]]
    rest = n % 100
    words += [ONES[rest]] if 0 < rest < 20 else [TENS[rest // 10], ONES[rest % 10] if rest % 10 else ""]
    return " ".join(w for w in words if w)


def latin_word(word: str) -> str:
    low = word.lower()
    if low in SPOKEN_NAMES:
        return SPOKEN_NAMES[low]
    if word.isupper() and len(word) <= 5:  # an abbreviation: API, SDK, CRM
        return " ".join(LETTER_NAMES[c] for c in low)
    for pair, sound in DIGRAPHS:
        low = low.replace(pair, sound)
    return "".join(LATIN.get(c, c) for c in low)


def voice_alphabet(config: dict) -> set | None:
    """Characters a raw-text Piper voice can say; None for phoneme-based voices, whose text is left as written."""
    symbols = set(config.get("phoneme_id_map") or {})
    return symbols if "а" in symbols and "о" in symbols else None


def speakable(text: str, alphabet: set | None) -> tuple[str, set]:
    """Rewrite one line for a raw-text voice. Returns (text, characters that still cannot be voiced)."""
    if alphabet is None:
        return text, set()

    def known(ch: str) -> bool:
        return ch.isspace() or all(part in alphabet for part in unicodedata.normalize("NFD", ch))

    text = re.sub(r"[A-Za-z]+", lambda m: " " + latin_word(m.group()) + " ", text)
    if not all(known(d) for d in "0123456789"):
        text = re.sub(r"(?<!\d)\d{1,3}(?:[,\u00a0 ]\d{3})+(?!\d)", lambda m: re.sub(r"\D", "", m.group()), text)  # 1,000
        text = re.sub(r"(?<=\d)\.(?=\d)", " крапка ", text)
        text = re.sub(r"(?<=\d),(?=\d)", " кома ", text)
        text = re.sub(r"\d+", lambda m: " " + number_words(m.group()) + " ", text)
    apostrophe = next((a for a in APOSTROPHES if a in alphabet), "")
    out, unvoiced = [], set()
    for ch in text:
        if ch in APOSTROPHES:
            out.append(apostrophe)
        elif known(ch):
            out.append(ch)
        elif known(ch.lower()):
            out.append(ch.lower())
        elif ch in "—–-" and known(","):
            out.append(", " if ch != "-" else " ")
        else:
            if ch not in "«»“”„\"()[]…":
                unvoiced.add(ch)
            out.append(" ")
    spoken = re.sub(r"\s+([,.!?:;])", r"\1", re.sub(r"\s+", " ", "".join(out))).strip()
    return re.sub(r"(,\s*){2,}", ", ", spoken), unvoiced


def pcm_report(pcm: bytes, rate: int) -> dict:
    """Duration, the longest run of near-silence and the share of voiced 100 ms windows of 16-bit mono PCM."""
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) - len(pcm) % 2])
    window = max(1, rate // 10)
    longest = run = voiced = total = 0
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window:4]
        rms = (sum(x * x for x in chunk) / len(chunk)) ** 0.5 if chunk else 0.0
        run = run + 1 if rms < QC_SILENCE_RMS else 0
        voiced += rms >= QC_SILENCE_RMS
        total += 1
        longest = max(longest, run)
    return {"seconds": round(len(samples) / rate, 2) if rate else 0.0,
            "max_silence_seconds": round(longest * window / rate, 2) if rate else 0.0,
            "voiced_share": round(voiced / total, 3) if total else 0.0}


def audio_problems(report: dict, lines: list, chunk_stats: list) -> list[str]:
    """Why this audio must not be delivered; an empty list means it passed."""
    problems = []
    expected = sum(len(str(t).split()) for _, t in lines) / QC_WORDS_PER_MINUTE * 60
    lo, hi = QC_DURATION_RATIO
    if not lo * expected <= report["seconds"] <= hi * expected:
        problems.append(f"duration {report['seconds']:.0f}s outside expected {lo * expected:.0f}-{hi * expected:.0f}s")
    if report["max_silence_seconds"] > QC_MAX_SILENCE_SECONDS:
        problems.append(f"silence of {report['max_silence_seconds']:.0f}s")
    if report["voiced_share"] < QC_MIN_VOICED_SHARE:
        problems.append(f"only {report['voiced_share']:.0%} of the audio has sound")
    for n, (chars, seconds) in enumerate(chunk_stats, 1):
        if seconds < QC_CHUNK_MIN_RATIO * chars / QC_CHUNK_CHARS_PER_SECOND:
            problems.append(f"line {n} truncated ({seconds:.1f}s for {chars} chars)")
            break
    return problems


def source_line(src: dict) -> str:
    """One transcript line per source. The hosts' own commentary has no link and is labelled, never shown as a source."""
    title = str(src.get("title") or "без назви").strip()
    url = str(src.get("url") or "").strip()
    date = str(src.get("date") or "без дати").strip()
    if src.get("kind") == "editorial" or not url:
        return f"- {title} — {EDITORIAL_LABEL if src.get('kind') == 'editorial' else 'без посилання'}, {date}"
    return f"- [{title}]({url}) — {date}"


def transcript(episode: dict, seconds: float | None) -> str:
    hosts = episode["hosts"]
    length = f"Тривалість: {seconds:.0f} с" if seconds is not None else "Тривалість: аудіо ще не відрендерено"
    text = [f"# {episode.get('title', episode['id'])}", "", f"_{episode.get('note', '')}_", "", length, ""]
    text += [f"**{hosts[h]['name']}:** {t}" for h, t in episode["lines"]]
    text += ["", "## Джерела"] + [source_line(s) for s in episode.get("sources", []) if isinstance(s, dict)]
    return "\n".join(text) + "\n"


def synthesize(voice, text: str, speaker_id: int, path: Path) -> None:
    with wave.open(str(path), "wb") as wav_file:
        try:  # piper-tts >= 1.3
            from piper import SynthesisConfig
            voice.synthesize_wav(text, wav_file, syn_config=SynthesisConfig(speaker_id=speaker_id))
        except ImportError:  # piper-tts 1.2
            voice.synthesize(text, wav_file, speaker_id=speaker_id)


def render_episode(episode_path: str, model_path: str, out_dir: str) -> Path | None:
    """Render one episode. Returns the WAV, or None when the audio failed QA (the transcript is still written)."""
    from piper import PiperVoice

    episode = json.loads(Path(episode_path).read_text(encoding="utf-8"))
    config = json.loads(Path(model_path + ".json").read_text(encoding="utf-8"))
    speakers = config.get("speaker_id_map") or {}
    alphabet = voice_alphabet(config)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    script = out / f"{episode['id']}.md"
    script.write_text(transcript(episode, None), encoding="utf-8")  # the text survives even if the audio fails

    voice = PiperVoice.load(model_path)
    parts, chunk_stats, unvoiced = [], [], set()
    final = out / f"{episode['id']}.wav"
    try:
        for n, (host, text) in enumerate(episode["lines"]):
            name = episode["hosts"][host]["speaker"]
            spoken, missing = speakable(text, alphabet)
            unvoiced |= missing
            part = out / f"{episode['id']}.part-{n:03d}.wav"
            parts.append(part)
            synthesize(voice, spoken, int(speakers[name]), part)
            with wave.open(str(part), "rb") as made:
                chunk_stats.append((len(spoken), made.getnframes() / made.getframerate()))
        with wave.open(str(parts[0]), "rb") as first:
            params = first.getparams()
        silence = b"\x00" * int(params.framerate * PAUSE_SECONDS) * params.sampwidth * params.nchannels
        with wave.open(str(final), "wb") as dst:
            dst.setparams(params)
            for part in parts:
                with wave.open(str(part), "rb") as src:
                    dst.writeframes(src.readframes(src.getnframes()))
                dst.writeframes(silence)
        with wave.open(str(final), "rb") as check:
            report = pcm_report(check.readframes(check.getnframes()), check.getframerate())
    except BaseException:
        final.unlink(missing_ok=True)
        raise
    finally:
        for part in parts:
            part.unlink(missing_ok=True)

    if unvoiced:
        print("characters the voice cannot say (skipped): " + " ".join(sorted(unvoiced)))
    problems = audio_problems(report, episode["lines"], chunk_stats)
    if problems:
        final.unlink()  # a failed episode leaves no audio behind, so nothing can upload or deliver it
        print(f"AUDIO QA FAILED for {episode['id']}: " + "; ".join(problems))
        return None
    script.write_text(transcript(episode, report["seconds"]), encoding="utf-8")
    # Every line is its own WAV followed by the same pause, so these starts are exact.
    starts, offset = [], 0.0
    for _, seconds in chunk_stats:
        starts.append(offset)
        offset += seconds + PAUSE_SECONDS
    chapters = caption_block(episode, starts)
    if chapters:  # the worker appends it to the Telegram caption ("0:00 Вступ" lines are clickable there)
        (out / f"{episode['id']}.chapters.txt").write_text(chapters + "\n", encoding="utf-8")
    print(f"rendered {final} ({report['seconds']:.1f} s, {len(parts)} lines, longest silence "
          f"{report['max_silence_seconds']:.1f} s, voiced {report['voiced_share']:.0%})")
    return final


def ffmpeg_exe() -> str:
    """The FFmpeg to use: MYCAST_FFMPEG, else the binary shipped in the imageio-ffmpeg pip package (what the render
    workflow installs, so the job needs no apt), else the system one. '' when there is none."""
    import os
    import shutil

    chosen = os.environ.get("MYCAST_FFMPEG", "").strip()
    if chosen:
        return chosen
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # not installed, or no binary for this platform
        return shutil.which("ffmpeg") or ""


MP3_CHECK_RATE = 16000  # the MP3 is decoded to 16 kHz mono 16-bit PCM and its real length is counted from the bytes


def to_mp3(wav: Path, mp3: Path) -> str:
    """Convert with FFmpeg, then decode the whole MP3 back to PCM and compare its real length with the WAV.
    Returns a problem or ''. Only FFmpeg is needed (no ffprobe): the length comes from the decoded audio itself."""
    import subprocess

    ffmpeg = ffmpeg_exe()
    if not ffmpeg:
        return "no ffmpeg found"

    def run(*args: str) -> tuple[int, bytes]:
        try:
            done = subprocess.run([ffmpeg, *args], capture_output=True, timeout=600, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, type(exc).__name__.encode()
        return done.returncode, done.stdout or b""

    if run("-loglevel", "error", "-y", "-i", str(wav), "-codec:a", "libmp3lame", "-b:a", "96k", str(mp3))[0]:
        return "mp3 conversion failed"
    code, pcm = run("-v", "error", "-xerror", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", str(MP3_CHECK_RATE), "-")
    if code or not pcm:
        return "mp3 does not decode"
    with wave.open(str(wav), "rb") as src:
        seconds = src.getnframes() / src.getframerate()
    decoded = len(pcm) / 2 / MP3_CHECK_RATE
    if abs(decoded - seconds) > 1:
        return f"mp3 length {decoded:.1f}s differs from the audio ({seconds:.1f}s)"
    return ""


def render_batch(episode_paths: list[str], model_path: str, out_dir: str, *, convert=to_mp3) -> int:
    """Render every episode on its own: one bad episode never hides the others, and an MP3 exists in OUT_DIR only
    after it passed every check. Returns 0 when all episodes produced a checked MP3, else 1."""
    failed = []
    for path in episode_paths:
        mp3 = None
        try:
            wav = render_episode(path, model_path, out_dir)
            problem = "audio QA" if wav is None else ""
            if wav is not None:
                mp3 = wav.with_suffix(".mp3")
                problem = convert(wav, mp3)
        except Exception as exc:  # a broken script must not stop the other episodes
            problem = f"{type(exc).__name__}: {exc}"[:200]
        if problem:
            if mp3 is not None:
                mp3.unlink(missing_ok=True)  # never leave an unchecked or partial MP3 for the upload step
            failed.append(path)
            print(f"FAILED {path}: {problem}")
        else:
            print(f"ok {path} -> {mp3}")
    print(f"{len(episode_paths) - len(failed)}/{len(episode_paths)} episodes rendered")
    return 1 if failed or not episode_paths else 0


def main(argv: list[str]) -> int:
    """EPISODE.json MODEL.onnx OUT_DIR, or --batch LIST MODEL.onnx OUT_DIR (LIST = NUL-separated episode paths)."""
    if argv and argv[0] == "--batch":
        listed, model_path, out_dir = argv[1:4]
        paths = [p for p in Path(listed).read_bytes().decode("utf-8").split("\0") if p.strip()]
    else:
        episode_path, model_path, out_dir = argv[:3]
        paths = [episode_path]
    return render_batch(paths, model_path, out_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
