"""MyCast Piper render: sources without a link, text the voice can say, audio QA. No Piper, no network.

Run: python -m tools.test_mycast_render
"""
from __future__ import annotations

import json
import math
import struct
import sys
import tempfile
import types
import wave
from pathlib import Path

from tools import mycast_render as mr

ROOT = Path(__file__).resolve().parents[1]
UK = set("абвгґдеєжзиіїйклмнопрстуфхцчшщьюя .,!?:;-'") | {"̆", "̈"}  # й and ї decompose to и/і + mark
RATE = 22050


def fake_piper(spoken: list, *, mode: str = "ok") -> None:
    """A stand-in for the piper package: a tone per character (ok), silence, or a clipped tone (truncated)."""
    class Voice:
        @classmethod
        def load(cls, path):
            return cls()

        def synthesize_wav(self, text, wav_file, syn_config=None):
            spoken.append((text, syn_config.speaker_id))
            frames = int(len(text) / 14 * RATE) if mode != "truncated" else RATE // 20
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(RATE)
            level = 0 if mode == "silent" else 8000
            wav_file.writeframes(b"".join(struct.pack("<h", int(level * math.sin(i / 8))) for i in range(frames)))

    class SynthesisConfig:
        def __init__(self, speaker_id=0):
            self.speaker_id = speaker_id

    sys.modules["piper"] = types.SimpleNamespace(PiperVoice=Voice, SynthesisConfig=SynthesisConfig)


def fake_mp3(wav: Path, mp3: Path) -> str:
    mp3.write_bytes(b"ID3" + wav.read_bytes()[:64])
    return ""


def render(episode: dict, mode: str = "ok", convert=fake_mp3) -> tuple[int, Path, list, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "ep.json").write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")
    spoken: list = []
    fake_piper(spoken, mode=mode)
    code = mr.render_batch([str(root / "ep.json")], voice_files(root), str(root / "out"), convert=convert)
    return code, root / "out", spoken, tmp


def voice_files(root: Path) -> str:
    config = {"speaker_id_map": {"mykyta": 1, "tetiana": 2}, "phoneme_id_map": {c: [n] for n, c in enumerate(sorted(UK))}}
    (root / "voice.onnx.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return str(root / "voice.onnx")


def fixture() -> dict:
    return json.loads((ROOT / "tools/fixtures/mycast_render_fixture.json").read_text(encoding="utf-8"))


def test_editorial_source_without_url():
    # The daily runs for 909bffb and 1c5cda0 died here with KeyError: 'url' after the audio was already rendered.
    episode = fixture()
    assert any("url" not in s for s in episode["sources"])
    code, out, spoken, tmp = render(episode)
    with tmp:
        assert code == 0
        text = (out / "mycast-render-fixture.md").read_text(encoding="utf-8")
        assert f"- Висновки ведучих та ідеї для FactoryOS — {mr.EDITORIAL_LABEL}, 2026-11-19" in text
        assert "- [MyCast render fixture](https://github.com/Pavlovskyi-Andrii/blackboxlab-factoryos) — 2026-11-19" in text
        assert "Тривалість:" in text and "ще не відрендерено" not in text
        assert "OpenAI" in text  # the transcript keeps the original spelling
        assert (out / "mycast-render-fixture.wav").exists() and not list(out.glob("*part-*.wav"))
        assert (out / "mycast-render-fixture.mp3").exists()
        assert [speaker for _, speaker in spoken] == [1, 2, 1, 2]
    assert mr.source_line({"title": "T", "date": "2026-11-19"}) == "- T — без посилання, 2026-11-19"
    assert mr.source_line({}) == "- без назви — без посилання, без дати"


def test_speakable_text():
    code, out, spoken, tmp = render(fixture())
    tmp.cleanup()
    said = " ".join(text for text, _ in spoken)
    assert not set(said) - {c for c in UK if len(c) == 1 and not 0x300 <= ord(c) < 0x370} - set("йї"), sorted(set(said) - UK)
    for heard in ("майкаст", "оупен ей ай", "клод код", "джеміні", "телеграм", "гітхаб", "ей пі ай", "дуже важливо",
                  "джі пі ті - шість крапка два", "дві тисячі двадцять шість", "п'ять", "лапки"):
        assert heard in said, heard
    assert "«" not in said and "  " not in said

    assert mr.speakable("OpenAI і Claude", None) == ("OpenAI і Claude", set())  # phoneme voices get the text as written
    assert mr.speakable("Курс € росте", UK) == ("курс росте", {"€"})
    assert mr.latin_word("Surfer") == "сурфер" and mr.latin_word("CRM") == "сі ар ем" and mr.latin_word("Tech") == "теч"
    assert [mr.number_words(n) for n in ("0", "7", "15", "40", "83", "100", "375", "1000", "2026", "007", "12345")] == [
        "нуль", "сім", "п'ятнадцять", "сорок", "вісімдесят три", "сто", "триста сімдесят п'ять", "тисяча",
        "дві тисячі двадцять шість", "нуль нуль сім", "один два три чотири п'ять"]
    for written, heard in (("1,000 доларів", "тисяча доларів"), ("3 750 000", "три сім п'ять нуль нуль нуль нуль"),
                           ("3,5 відсотка", "три кома п'ять відсотка"), ("версія 6.2", "версія шість крапка два"),
                           ("2,500", "дві тисячі п'ятсот"), ("у 2026, 15 разів", "у дві тисячі двадцять шість, п'ятнадцять разів")):
        assert mr.speakable(written, UK)[0] == heard, mr.speakable(written, UK)[0]
    digits = UK | set("0123456789")
    assert mr.speakable("GPT-5 у 2026", digits)[0] == "джі пі ті -5 у 2026"  # a voice that knows digits keeps them
    assert mr.voice_alphabet({"phoneme_id_map": {"ə": [1], "a": [2]}}) is None


def test_audio_qa_refuses_bad_audio():
    for mode, reason in (("silent", "has sound"), ("truncated", "duration")):
        code, out, _, tmp = render(fixture(), mode)
        with tmp:
            assert code == 1, mode
            assert not list(out.glob("*.wav")) and not list(out.glob("*.mp3"))  # nothing left to upload or deliver
            assert "ще не відрендерено" in (out / "mycast-render-fixture.md").read_text(encoding="utf-8")
    lines = [["A", "слово " * 140]]
    good = {"seconds": 60.0, "max_silence_seconds": 0.5, "voiced_share": 0.9}
    assert mr.audio_problems(good, lines, [(840, 60.0)]) == []
    assert "silence of 9s" in mr.audio_problems(dict(good, max_silence_seconds=9.0), lines, [])[0]
    assert "duration 20s" in mr.audio_problems(dict(good, seconds=20.0), lines, [])[0]
    assert "line 2 truncated" in mr.audio_problems(good, lines, [(100, 7.0), (840, 3.0)])[0]

    tone = b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(RATE * 2))
    report = mr.pcm_report(tone + b"\x00\x00" * RATE * 3 + tone, RATE)
    assert report["seconds"] == 7.0 and 2.9 <= report["max_silence_seconds"] <= 3.1 and 0.5 < report["voiced_share"] < 0.6
    assert mr.pcm_report(b"", RATE) == {"seconds": 0.0, "max_silence_seconds": 0.0, "voiced_share": 0.0}


def test_thresholds_match_server_preflight():
    import mycast

    for name in ("QC_WORDS_PER_MINUTE", "QC_DURATION_RATIO", "QC_MAX_SILENCE_SECONDS", "QC_SILENCE_RMS",
                 "QC_CHUNK_CHARS_PER_SECOND", "QC_CHUNK_MIN_RATIO"):
        assert getattr(mr, name) == getattr(mycast, name), name
    with wave.open(str(Path(tempfile.gettempdir()) / "mycast-render-qc.wav"), "wb") as w:  # same maths as the server
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
        w.writeframes(b"\x00\x00" * RATE)
    assert mycast.pcm_report(b"\x00\x00" * RATE, RATE)["max_silence_seconds"] == mr.pcm_report(b"\x00\x00" * RATE, RATE)["max_silence_seconds"]


def test_workflow_contract():
    flow = (ROOT / ".github/workflows/mycast-render.yml").read_text(encoding="utf-8")
    assert "pull_request:" in flow and "tools/fixtures/mycast_render_fixture.json" in flow
    assert "if-no-files-found: error" in flow
    assert 'tools/mycast_changed_episodes.sh "${{ github.event.before }}" > episodes.list' in flow and "HEAD~1" not in flow
    assert "tools/mycast_render.py --batch episodes.list" in flow and "for ep in" not in flow and "libmp3lame" not in flow
    assert "if: ${{ !cancelled() }}" in flow  # transcripts and the checked MP3s are uploaded even when an episode fails
    assert "contents: read" in flow and "secrets." not in flow
    # Setup: no apt at all (it once took 9 minutes of a 20-minute job) — FFmpeg comes from a pip package — and the
    # voice comes from the cache.
    setup = flow[flow.index("- uses: actions/setup-python"):flow.index("- name: Render episodes")]
    commands = "\n".join(line for line in flow.splitlines() if not line.lstrip().startswith("#"))
    assert "apt-get" not in commands and "ffprobe" not in commands and "imageio-ffmpeg" in setup
    assert "actions/cache@v4" in setup and "piper-voice-uk_UA-ukrainian_tts-medium-v1" in setup
    assert setup.index("actions/cache@v4") < setup.index("huggingface.co") and "--retry 3" in setup


def test_batch_keeps_good_episodes_and_only_checked_mp3():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        good, other = fixture(), dict(fixture(), id="mycast-other one")
        broken = dict(fixture(), id="mycast-broken", lines=[["A", "текст"], ["C", "немає такого ведучого"]])
        bad_mp3 = dict(fixture(), id="mycast-bad-mp3")
        paths = []
        for name, episode in (("a broken.json", broken), ("b bad mp3.json", bad_mp3), ("c good.json", good), ("d *.json", other)):
            (root / name).write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")
            paths.append(str(root / name))
        (root / "not-json.json").write_text("{", encoding="utf-8")
        paths.insert(0, str(root / "not-json.json"))

        def convert(wav: Path, mp3: Path) -> str:
            mp3.write_bytes(b"partial")  # ffmpeg can leave a partial file behind
            return "mp3 does not decode" if "bad-mp3" in mp3.name else ""

        fake_piper([])
        out = root / "out"
        assert mr.render_batch(paths, voice_files(root), str(out), convert=convert) == 1  # the run is red...
        assert sorted(p.name for p in out.glob("*.mp3")) == ["mycast-other one.mp3", "mycast-render-fixture.mp3"]  # ...the good audio is kept
        assert not (out / "mycast-bad-mp3.mp3").exists() and not list(out.glob("*part-*"))
        assert not list(out.glob("mycast-broken.*"))  # a malformed script leaves nothing behind
        assert mr.render_batch([], voice_files(root), str(out)) == 1  # nothing to render is not a success

        # The command line: NUL-separated list, file names with spaces and glob characters arrive unchanged.
        seen = []
        real, mr.render_batch = mr.render_batch, lambda paths, model, out_dir: seen.append((paths, model, out_dir)) or 0
        try:
            (root / "list").write_bytes("a b.json\0c *.json\0".encode())
            assert mr.main(["--batch", str(root / "list"), "m.onnx", "o"]) == 0 and mr.main(["one.json", "m.onnx", "o"]) == 0
        finally:
            mr.render_batch = real
        assert seen == [(["a b.json", "c *.json"], "m.onnx", "o"), (["one.json"], "m.onnx", "o")]


def test_to_mp3_checks_the_file():
    import os
    import shutil
    import subprocess

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "x.wav"
        with wave.open(str(wav), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(RATE)
            w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(i / 8))) for i in range(RATE * 3)))
        real_run, saved_env = subprocess.run, os.environ.get("MYCAST_FFMPEG")
        calls = []

        def restore_env():
            if saved_env is None:
                os.environ.pop("MYCAST_FFMPEG", None)
            else:
                os.environ["MYCAST_FFMPEG"] = saved_env

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return types.SimpleNamespace(returncode=replies[len(calls) - 1][0], stdout=replies[len(calls) - 1][1])

        def pcm(seconds):
            return b"\x00\x00" * int(mr.MP3_CHECK_RATE * seconds)

        subprocess.run = fake_run
        os.environ["MYCAST_FFMPEG"] = "/opt/custom/ffmpeg"
        try:
            for replies, want in (([(1, b"")], "mp3 conversion failed"), ([(0, b""), (1, b"")], "mp3 does not decode"),
                                  ([(0, b""), (0, b"")], "mp3 does not decode"),           # decoded to nothing
                                  ([(0, b""), (0, pcm(9.0))], "mp3 length 9.0s differs"),  # the real decoded length
                                  ([(0, b""), (0, pcm(1.5))], "mp3 length 1.5s differs"),  # a truncated file
                                  ([(0, b""), (0, pcm(3.02))], "")):
                calls.clear()
                got = mr.to_mp3(wav, wav.with_suffix(".mp3"))
                assert (want in got) if want else got == "", (replies, got)
            assert [c[0] for c in calls] == ["/opt/custom/ffmpeg"] * 2  # one binary does both steps, no ffprobe
            assert "libmp3lame" in calls[0] and "s16le" in calls[1] and "-xerror" in calls[1]
            assert mr.ffmpeg_exe() == "/opt/custom/ffmpeg"
        finally:
            subprocess.run = real_run
            restore_env()

        # Without the override: the pip-packaged binary when imageio-ffmpeg is installed, else the system one.
        os.environ.pop("MYCAST_FFMPEG", None)
        saved_module = sys.modules.get("imageio_ffmpeg")
        try:
            sys.modules["imageio_ffmpeg"] = types.SimpleNamespace(get_ffmpeg_exe=lambda: "/pip/ffmpeg")
            assert mr.ffmpeg_exe() == "/pip/ffmpeg"
            sys.modules["imageio_ffmpeg"] = types.SimpleNamespace(get_ffmpeg_exe=lambda: 1 / 0)  # no binary for the platform
            assert mr.ffmpeg_exe() == (shutil.which("ffmpeg") or "")
        finally:
            if saved_module is None:
                sys.modules.pop("imageio_ffmpeg", None)
            else:
                sys.modules["imageio_ffmpeg"] = saved_module
            restore_env()

        exe = mr.ffmpeg_exe()
        if exe:  # the real tool, where the machine has one: a true encode, decode and length check
            mp3 = wav.with_suffix(".mp3")
            assert mr.to_mp3(wav, mp3) == "" and mp3.stat().st_size > 1000
            mp3.write_bytes(mp3.read_bytes()[: mp3.stat().st_size // 3])  # a file cut to a third
            decoded = real_run([exe, "-v", "quiet", "-i", str(mp3), "-f", "s16le", "-ac", "1", "-ar", str(mr.MP3_CHECK_RATE), "-"],
                               capture_output=True).stdout
            assert len(decoded) / 2 / mr.MP3_CHECK_RATE < 1.6  # its decoded length is far outside the 1 s tolerance
            os.environ["MYCAST_FFMPEG"] = "/nonexistent/ffmpeg"
            try:
                assert mr.to_mp3(wav, wav.with_suffix(".2.mp3")) == "mp3 conversion failed"
            finally:
                restore_env()



def test_changed_episodes_cover_the_whole_push():
    import subprocess

    script = ROOT / "tools/mycast_changed_episodes.sh"
    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)

        def git(*args):
            return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                                   *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

        def commit(name, text="{}"):
            (repo / name).parent.mkdir(parents=True, exist_ok=True)
            (repo / name).write_text(text, encoding="utf-8")
            git("add", "-A"), git("commit", "-q", "-m", name)
            return git("rev-parse", "HEAD")

        warnings = []

        def changed(before=""):
            done = subprocess.run(["bash", str(script), before], cwd=repo, check=True, capture_output=True)
            warnings.append(done.stderr.decode("utf-8"))
            return [Path(p).name for p in done.stdout.decode("utf-8").split("\0") if p]

        git("init", "-q")
        base = commit("docs/prototypes/mycast/episodes/2026-11-01.json")
        commit("docs/prototypes/mycast/episodes/2026-11-02.json")
        commit("docs/prototypes/mycast/episodes/2026-11-03.json")
        assert changed(base) == ["2026-11-02.json", "2026-11-03.json"]  # a two-commit push renders both episodes
        commit("README.md", "x")
        assert changed(base) == ["2026-11-02.json", "2026-11-03.json"]  # even when the last commit has no episode
        commit("tools/x.py", "x")
        assert changed(git("rev-parse", "HEAD~1")) == ["2026-11-03.json"]  # no episode in the push: the newest one
        assert changed("0" * 40) == ["2026-11-03.json"] and changed("") == ["2026-11-03.json"]  # new branch / manual run
        assert not any(warnings)
        # An unavailable base: the last commit still decides (the morning episode is rendered), with a warning.
        assert changed("deadbeef" * 5) == ["2026-11-03.json"] and "::warning::push base" in warnings[-1]
        before = git("rev-parse", "HEAD")
        commit("docs/prototypes/mycast/episodes/2026-11-04 special *.json")
        commit("docs/prototypes/mycast/episodes/2026-11-05 україна.json")
        assert changed(before) == ["2026-11-04 special *.json", "2026-11-05 україна.json"]  # spaces, globs, non-ASCII
        # A renamed episode is rendered under its new name, alone or next to an edited one.
        before = git("rev-parse", "HEAD")
        (repo / "docs/prototypes/mycast/episodes/2026-11-01.json").write_text('{"lines": "long enough to be seen as a rename"}', encoding="utf-8")
        git("add", "-A"), git("commit", "-q", "-m", "content")
        before = git("rev-parse", "HEAD")
        git("mv", "docs/prototypes/mycast/episodes/2026-11-01.json", "docs/prototypes/mycast/episodes/2026-10-31.json")
        git("commit", "-q", "-m", "rename")
        assert changed(before) == ["2026-10-31.json"]  # not the newest-file fallback
        commit("docs/prototypes/mycast/episodes/2026-11-02.json", '{"edited": true}')
        assert changed(before) == ["2026-10-31.json", "2026-11-02.json"]
        commit("tools/y.py", "x")
        assert changed(git("rev-parse", "HEAD~1")) == ["2026-11-05 україна.json"]


if __name__ == "__main__":
    test_changed_episodes_cover_the_whole_push()
    test_batch_keeps_good_episodes_and_only_checked_mp3()
    test_to_mp3_checks_the_file()
    test_editorial_source_without_url()
    test_speakable_text()
    test_audio_qa_refuses_bad_audio()
    test_thresholds_match_server_preflight()
    test_workflow_contract()
    print("mycast render tests passed")
