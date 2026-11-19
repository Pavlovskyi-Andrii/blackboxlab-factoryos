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


def render(episode: dict, mode: str = "ok") -> tuple[int, Path, list, tempfile.TemporaryDirectory]:
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "ep.json").write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")
    config = {"speaker_id_map": {"mykyta": 1, "tetiana": 2}, "phoneme_id_map": {c: [n] for n, c in enumerate(sorted(UK))}}
    (root / "voice.onnx.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    spoken: list = []
    fake_piper(spoken, mode=mode)
    code = mr.main(str(root / "ep.json"), str(root / "voice.onnx"), str(root / "out"))
    return code, root / "out", spoken, tmp


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
        assert (out / "mycast-render-fixture.wav").exists() and not list(out.glob("part-*.wav"))
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
    digits = UK | set("0123456789")
    assert mr.speakable("GPT-5 у 2026", digits)[0] == "джі пі ті -5 у 2026"  # a voice that knows digits keeps them
    assert mr.voice_alphabet({"phoneme_id_map": {"ə": [1], "a": [2]}}) is None


def test_audio_qa_refuses_bad_audio():
    for mode, reason in (("silent", "has sound"), ("truncated", "duration")):
        code, out, _, tmp = render(fixture(), mode)
        with tmp:
            assert code == 2, mode
            assert not (out / "mycast-render-fixture.wav").exists()  # nothing left to convert, upload or deliver
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
    assert "if-no-files-found: error" in flow and "-f null -" in flow
    assert "ls docs/prototypes/mycast/episodes/*.json | sort | tail -n 1" in flow  # never re-render the whole archive
    assert "contents: read" in flow and "secrets." not in flow


if __name__ == "__main__":
    test_editorial_source_without_url()
    test_speakable_text()
    test_audio_qa_refuses_bad_audio()
    test_thresholds_match_server_preflight()
    test_workflow_contract()
    print("mycast render tests passed")
