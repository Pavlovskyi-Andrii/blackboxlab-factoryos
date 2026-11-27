"""T-603 server side: Telegram sendAudio multipart, one delivery per episode, worker-only route. No network."""
import asyncio
import io
import json
import tempfile
from pathlib import Path

from fastapi import HTTPException
from starlette.datastructures import UploadFile

import mycast
import mycast_chapters


def fake_mp3(seconds: float, *, id3: bool = True) -> bytes:
    """Synthetic MPEG-1 Layer III stream (128 kbps, 44.1 kHz): valid frame headers, silent payload. No encoder needed."""
    frames, out = int(seconds * 44100 / 1152), bytearray()
    if id3:
        out += b"ID3\x04\x00\x00\x00\x00\x00\x0a" + b"\x00" * 10
    for n in range(frames):
        padding = 1 if n % 3 == 0 else 0
        out += bytes([0xFF, 0xFB, 0x90 | (padding << 1), 0x64]) + b"\x00" * (144 * 128000 // 44100 + padding - 4)
    return bytes(out)


def speech_pcm(seconds: float, rate: int = 24000, silent_gap: float = 0.0) -> bytes:
    """Deterministic speech-like PCM (pseudo-random, ~-20 dBFS) with an optional silent gap in the middle."""
    import array
    import random

    rnd = random.Random(7)
    loud = array.array("h", (rnd.randint(-3000, 3000) for _ in range(int(seconds * rate / 2))))
    gap = array.array("h", [0] * int(silent_gap * rate))
    return (loud + gap + loud).tobytes()


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_send_audio_multipart():
    seen = {}

    def opener(req, timeout):
        seen["url"], seen["body"], seen["ctype"] = req.full_url, req.data, req.headers.get("Content-type")
        return _Resp(b'{"ok": true, "result": {"audio": {"file_id": "AUDIO-1"}}}')
    file_id = mycast.telegram_send_audio("123:TOKEN", "4242", b"ID3-audio-bytes", filename="mycast-2026-11-03.mp3",
                                         title="MyCast · 3 листопада", caption="🎧 test", opener=opener)
    assert file_id == "AUDIO-1"                       # #317 history: kept instead of the audio itself
    assert seen["url"].endswith("/bot123:TOKEN/sendAudio")
    assert seen["ctype"].startswith("multipart/form-data; boundary=")
    body = seen["body"]
    assert b'name="chat_id"\r\n\r\n4242' in body and b"ID3-audio-bytes" in body
    assert 'MyCast · 3 листопада'.encode() in body and b'filename="mycast-2026-11-03.mp3"' in body
    try:
        mycast.telegram_send_audio("t", "c", b"x", filename="f", title="t", caption="", opener=lambda r, timeout: _Resp(b'{"ok": false}'))
        raise AssertionError("not-ok must raise")
    except RuntimeError:
        pass


class _App:
    def __init__(self):
        self.routes = {}

    def post(self, path):
        def deco(fn):
            self.routes[path] = fn
            return fn
        return deco


class _Req:
    def __init__(self, worker):
        self.worker = worker


def test_route():
    app, sent = _App(), []
    log = mycast.DeliveryLog(Path(tempfile.mkdtemp()) / "d.json")
    state = {"paired": True, "fail": False}

    def send(audio, filename, title, caption):
        if state["fail"]:
            raise RuntimeError("telegram down")
        sent.append((audio, filename, title))
    mycast.install_mycast_routes(app, log, authorize_worker=lambda r: r.worker, send_audio=send, paired=lambda: state["paired"])
    deliver = app.routes["/api/factory/mycast/worker/deliver"]

    def call(req, episode_id="mycast-2026-11-03", data=fake_mp3(30)):
        return asyncio.run(deliver(req, episode_id=episode_id, title="MyCast", caption="c",
                                   audio=UploadFile(io.BytesIO(data), filename="a.mp3")))

    def status(fn):
        try:
            fn()
        except HTTPException as exc:
            return exc.status_code
        return 200
    assert status(lambda: call(_Req(False))) == 401
    assert status(lambda: call(_Req(True), episode_id="../../etc")) == 400
    state["paired"] = False
    assert status(lambda: call(_Req(True))) == 409
    state["paired"] = True
    state["fail"] = True
    assert status(lambda: call(_Req(True))) == 502
    assert log.delivered() == []  # failed delivery can be retried
    state["fail"] = False
    first = call(_Req(True))
    assert first["sent"] is True and first["duplicate"] is False and 29 <= first["seconds"] <= 31
    assert call(_Req(True)) == {"sent": False, "duplicate": True}  # one Telegram message per episode
    assert len(sent) == 1 and sent[0][1] == "mycast-2026-11-03.mp3"
    assert status(lambda: call(_Req(True), episode_id="mycast-2026-11-04", data=b"")) == 413
    # Audio QC (#233): a corrupt or non-MP3 upload is refused and never logged as delivered.
    assert status(lambda: call(_Req(True), episode_id="mycast-2026-11-04", data=b"ID3audio" * 400)) == 422
    assert status(lambda: call(_Req(True), episode_id="mycast-2026-11-04", data=fake_mp3(0.2))) == 422
    assert "mycast-2026-11-04" not in log.delivered() and len(sent) == 1


def _episode(n_lines=6, text="Слово " * 60):
    return {"id": "mycast-2026-11-03", "title": "MyCast", "language": "uk",
            "lines": [["A" if i % 2 == 0 else "B", text.strip()] for i in range(n_lines)]}


def test_gemini_tts():
    import base64 as b64
    ep = _episode(n_lines=20)
    chunks = mycast.episode_chunks(ep["lines"])
    assert len(chunks) > 1 and sum(len(c) for c in chunks) == len(ep["lines"])  # split, nothing lost
    calls = []

    def opener(req, timeout):
        calls.append((req.get_method(), req.full_url, json.loads(req.data) if req.data else None, req.headers.get("X-goog-api-key")))
        if req.full_url.endswith(":generateContent") and "old-model" in req.full_url:
            err = Exception("404")
            err.code = 404
            raise err
        if "models?" in req.full_url:
            return _Resp(json.dumps({"models": [{"name": "models/gemini-x-pro"}, {"name": "models/gemini-9-flash-tts"}]}).encode())
        pcm = b"\x01\x00" * 2400
        return _Resp(json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": b64.b64encode(pcm).decode()}}]}}]}).encode())
    pcm, rate = mycast.gemini_tts_pcm("KEY123", ep, model="old-model", voices=("Charon", "Kore"), opener=opener)
    assert rate == 24000 and len(pcm) >= 4800 * len(chunks)
    gen = [c for c in calls if c[1].endswith(":generateContent")]
    assert "old-model" in gen[0][1] and all("gemini-9-flash-tts" in c[1] for c in gen[1:])  # discovered after 404
    body = gen[-1][2]
    cfg = body["generationConfig"]["speechConfig"]["multiSpeakerVoiceConfig"]["speakerVoiceConfigs"]
    assert [c["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] for c in cfg] == ["Charon", "Kore"]
    assert "Host1:" in body["contents"][0]["parts"][0]["text"] and all(c[3] == "KEY123" for c in calls)
    assert all("KEY123" not in c[1] for c in calls)  # key in a header, never in the URL

    def limited(req, timeout):
        err = Exception("429")
        err.code = 429
        raise err
    waited = []
    try:
        mycast.gemini_tts_pcm("K", ep, opener=limited, sleep=waited.append)
        raise AssertionError("429 must raise")
    except mycast.GeminiTTSError as exc:
        assert exc.category == "rate_limited"
    # Bounded: a persistent 429 is retried RATE_LIMIT_RETRIES times for the first chunk, then the episode fails.
    assert waited == [mycast.RATE_LIMIT_WAIT_SECONDS * (n + 1) for n in range(mycast.RATE_LIMIT_RETRIES)]

    # A single free-tier 429 in the middle of an episode waits once and the episode still completes.
    hits = {"n": 0}

    def once_limited(req, timeout):
        hits["n"] += 1
        if hits["n"] == 2:
            return limited(req, timeout)
        return opener(req, timeout)
    waited.clear()
    pcm, _ = mycast.gemini_tts_pcm("K", ep, model="gemini-9-flash-tts", opener=once_limited, sleep=waited.append)
    assert len(waited) == 1 and len(pcm) >= 4800 * len(chunks)


def test_voice_route():
    app, sent = _App(), []
    log = mycast.DeliveryLog(Path(tempfile.mkdtemp()) / "d.json")
    state = {"key": "", "fail": None, "seconds": None, "gap": 0.0, "stats": []}
    expected = mycast.expected_seconds(_episode()["lines"])
    encoded = fake_mp3(expected)

    def tts(key, episode, model="", voices=(), stats=None):
        if state["fail"]:
            raise mycast.GeminiTTSError(state["fail"])
        if stats is not None:
            stats.extend(state["stats"])
        return speech_pcm(state["seconds"] or expected, silent_gap=state["gap"]), 24000
    mycast.install_mycast_voice_routes(app, log, authorize_worker=lambda r: r.worker, send_audio=lambda *a: sent.append(a),
                                       paired=lambda: True, api_key=lambda: state["key"], tts=tts, encode=lambda pcm, rate: encoded)
    route = app.routes["/api/factory/mycast/worker/voice-deliver"]

    class _JReq(_Req):
        def __init__(self, worker, body):
            super().__init__(worker)
            self.body = body

        async def json(self):
            return self.body

    def call(worker=True, body=None):
        try:
            return 200, asyncio.run(route(_JReq(worker, body if body is not None else {"episode": _episode()})))
        except HTTPException as exc:
            return exc.status_code, exc.detail
    assert call(worker=False)[0] == 401
    assert call(body={"episode": {"id": "../x", "lines": []}})[0] == 400
    assert call() == (409, "gemini key not configured")  # worker falls back to Piper
    state["key"] = "K"
    state["fail"] = "rate_limited"
    assert call() == (502, "gemini tts: rate_limited") and log.delivered() == []
    state["fail"] = None
    # Audio QC (#233): each failure releases the claim, so nothing is logged as delivered and a retry stays possible.
    state["seconds"] = expected * 0.2
    assert call() == (502, f"audio qc: duration {expected * 0.2:.0f}s outside expected {expected * 0.45:.0f}-{expected * 2.2:.0f}s")
    state["seconds"], state["gap"] = None, 9.0
    assert call() == (502, "audio qc: silence of 9s")
    state["gap"], state["stats"] = 0.0, [(1400, 95.0), (1400, 8.0)]
    assert call() == (502, "audio qc: chunk 2 truncated (8s for 1400 chars)")
    assert log.delivered() == [] and sent == []
    state["stats"] = [(1400, 95.0), (1000, 70.0)]
    code, body = call()
    assert code == 200 and body["sent"] and body["voice"] == "gemini" and abs(body["seconds"] - expected) <= 1
    assert body["bytes"] == len(encoded) and sent[0][0] == encoded and "Gemini" in sent[0][3]
    assert call()[1]["duplicate"] is True and len(sent) == 1
    assert "\n0:00 " not in sent[0][3]  # no chapters in the script: no timecodes, as before
    # Chapters in the script (owner 2026-11-27): clickable "M:SS Title" lines, timed from each TTS chunk's length.
    lines = _episode()["lines"]
    chunks = mycast.episode_chunks(lines)
    per_chunk = [expected * sum(len(t) for _, t in c) / sum(len(t) for _, t in lines) for c in chunks]
    state["stats"] = [(sum(len(t) for _, t in c), sec) for c, sec in zip(chunks, per_chunk)]
    second = len(lines) // 2
    code, body = call(body={"episode": dict(_episode(), id="mycast-2026-11-28",
                                            chapters=[{"line": 0, "title": "Вступ"}, {"line": second, "title": "Новини"}])})
    assert code == 200 and body["sent"]
    starts = mycast.chunk_line_starts(chunks, per_chunk, mycast.CHUNK_PAUSE_SECONDS)
    assert sent[1][3].endswith(f"\n\n0:00 Вступ\n{mycast_chapters.clock(starts[second])} Новини"), sent[1][3]


def test_audio_qc():
    # Reference: the committed Piper pilot (MPEG-2 Layer III, 22.05 kHz); ffprobe reports 109.714 s for it.
    pilot = Path(__file__).resolve().parent / "docs" / "prototypes" / "mycast" / "audio" / "2026-11-02.mp3"
    if pilot.exists():
        assert abs(mycast.mp3_report(pilot.read_bytes())["seconds"] - 109.714) < 0.2
    # MP3: frames, duration, ID3 skip, garbage and truncation; no ffprobe involved.
    report = mycast.mp3_report(fake_mp3(60))
    assert report["frames"] == int(60 * 44100 / 1152) and 59 <= report["seconds"] <= 60 and report["valid_share"] > 0.99
    assert mycast.mp3_report(fake_mp3(10, id3=False))["frames"] > 0
    assert mycast.check_mp3(fake_mp3(60), expected=60)["seconds"] > 59
    for bad, reason in ((b"", "empty audio"), (b"\x00" * 50000, "not a decodable mp3"), (b"RIFF....WAVEfmt " * 900, "not a decodable mp3"),
                        (fake_mp3(30)[:2000] + b"\x13" * 40000, "not a decodable mp3")):
        try:
            mycast.check_mp3(bad)
            raise AssertionError(f"accepted bad audio: {reason}")
        except mycast.AudioQCError as exc:
            assert exc.reason == reason, exc.reason
    try:
        mycast.check_mp3(fake_mp3(10), expected=120)
        raise AssertionError("short file accepted")
    except mycast.AudioQCError as exc:
        assert exc.reason.startswith("duration 10s")
    # PCM: measured silence, not guessed.
    assert mycast.pcm_report(speech_pcm(20), 24000)["max_silence_seconds"] <= 0.2
    assert 7.5 <= mycast.pcm_report(speech_pcm(20, silent_gap=8), 24000)["max_silence_seconds"] <= 8.1
    lines = [["A", "слово " * 140]]  # 140 words → 60 s expected
    assert mycast.check_pcm(speech_pcm(60), 24000, lines, [(700, 50.0)])["seconds"] == 60.0
    for pcm, stats, start in ((b"", None, "empty"), (speech_pcm(10), None, "duration"), (speech_pcm(60, silent_gap=7), None, "silence"),
                              (speech_pcm(60), [(1400, 10.0)], "chunk 1 truncated")):
        try:
            mycast.check_pcm(pcm, 24000, lines, stats)
            raise AssertionError(f"accepted: {start}")
        except mycast.AudioQCError as exc:
            assert exc.reason.startswith(start), exc.reason


def test_delivery_log():
    tmp_path = Path(tempfile.mkdtemp()) / "log.json"
    log = mycast.DeliveryLog(tmp_path)
    assert log.claim("mycast-2026-11-03") is True
    assert log.claim("mycast-2026-11-03") is False

    log.release("mycast-2026-11-03")
    assert log.claim("mycast-2026-11-03") is True

    log_restarted = mycast.DeliveryLog(tmp_path)
    assert log_restarted.claim("mycast-2026-11-03") is False
    assert "mycast-2026-11-03" in log_restarted.delivered()


def test_episode_chunks():
    assert mycast.episode_chunks([]) == []

    def check_integrity(lines):
        chunks = mycast.episode_chunks(lines)
        flattened = [item for chunk in chunks for item in chunk]
        assert flattened == lines

    long_text = "a" * (mycast.CHUNK_CHARS + 500)
    lines_long = [("A", long_text)]
    assert mycast.episode_chunks(lines_long) == [[("A", long_text)]]
    check_integrity(lines_long)

    lines_mixed = [("A", "hello"), ("B", long_text), ("A", "world")]
    check_integrity(lines_mixed)

    line1 = ("A", "x" * (mycast.CHUNK_CHARS - 400))
    line2 = ("B", "y" * 400)
    line3 = ("A", "z" * 1)
    lines_boundary = [line1, line2, line3]
    chunks = mycast.episode_chunks(lines_boundary)
    assert chunks == [[line1, line2], [line3]]
    check_integrity(lines_boundary)

    exact_line = ("A", "k" * mycast.CHUNK_CHARS)
    lines_exact = [exact_line, ("B", "next")]
    assert mycast.episode_chunks(lines_exact) == [[exact_line], [("B", "next")]]
    check_integrity(lines_exact)


def test_pcm_to_mp3():
    try:
        import lameenc  # noqa: F401
    except ImportError:
        print("SKIPPED pcm_to_mp3: lameenc not installed here (CI installs it from requirements.txt)")
        return
    mp3 = mycast.pcm_to_mp3(b"\x00\x00" * 24000, 24000)
    assert len(mp3) > 100 and (mp3[:3] == b"ID3" or mp3[0] == 0xFF)
    real = mycast.check_mp3(mycast.pcm_to_mp3(speech_pcm(30), 24000), expected=30)  # the server's own encoder passes QC
    assert 29.5 <= real["seconds"] <= 30.5 and real["valid_share"] > 0.99


def main():
    test_delivery_log()
    test_send_audio_multipart()
    test_route()
    test_gemini_tts()
    test_voice_route()
    test_audio_qc()
    test_pcm_to_mp3()
    test_episode_chunks()
    print("MyCast delivery tests passed")


if __name__ == "__main__":
    main()
