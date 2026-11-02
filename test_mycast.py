"""T-603 server side: Telegram sendAudio multipart, one delivery per episode, worker-only route. No network."""
import asyncio
import io
import json
import tempfile
from pathlib import Path

from fastapi import HTTPException
from starlette.datastructures import UploadFile

import mycast


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
        return _Resp(b'{"ok": true}')
    mycast.telegram_send_audio("123:TOKEN", "4242", b"ID3-audio-bytes", filename="mycast-2026-11-03.mp3",
                               title="MyCast · 3 листопада", caption="🎧 test", opener=opener)
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

    def call(req, episode_id="mycast-2026-11-03", data=b"ID3audio"):
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
    assert call(_Req(True)) == {"sent": True, "duplicate": False}
    assert call(_Req(True)) == {"sent": False, "duplicate": True}  # one Telegram message per episode
    assert len(sent) == 1 and sent[0][1] == "mycast-2026-11-03.mp3"
    assert status(lambda: call(_Req(True), episode_id="mycast-2026-11-04", data=b"")) == 413


def _episode(n_lines=6, text="Слово " * 60):
    return {"id": "mycast-2026-11-03", "title": "MyCast", "language": "uk",
            "lines": [["A" if i % 2 == 0 else "B", text.strip()] for i in range(n_lines)]}


def test_gemini_tts():
    import base64 as b64
    ep = _episode()
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
    try:
        mycast.gemini_tts_pcm("K", ep, opener=limited)
        raise AssertionError("429 must raise")
    except mycast.GeminiTTSError as exc:
        assert exc.category == "rate_limited"


def test_voice_route():
    app, sent = _App(), []
    log = mycast.DeliveryLog(Path(tempfile.mkdtemp()) / "d.json")
    state = {"key": "", "fail": None}

    def tts(key, episode, model="", voices=()):
        if state["fail"]:
            raise mycast.GeminiTTSError(state["fail"])
        return b"\x00\x00" * 24000, 24000
    mycast.install_mycast_voice_routes(app, log, authorize_worker=lambda r: r.worker, send_audio=lambda *a: sent.append(a),
                                       paired=lambda: True, api_key=lambda: state["key"], tts=tts, encode=lambda pcm, rate: b"MP3")
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
    code, body = call()
    assert code == 200 and body["sent"] and body["voice"] == "gemini" and body["seconds"] == 1
    assert sent[0][0] == b"MP3" and "Gemini" in sent[0][3]
    assert call()[1]["duplicate"] is True and len(sent) == 1


def test_pcm_to_mp3():
    try:
        import lameenc  # noqa: F401
    except ImportError:
        print("SKIPPED pcm_to_mp3: lameenc not installed here (CI installs it from requirements.txt)")
        return
    mp3 = mycast.pcm_to_mp3(b"\x00\x00" * 24000, 24000)
    assert len(mp3) > 100 and (mp3[:3] == b"ID3" or mp3[0] == 0xFF)


def main():
    test_send_audio_multipart()
    test_route()
    test_gemini_tts()
    test_voice_route()
    test_pcm_to_mp3()
    print("MyCast delivery tests passed")


if __name__ == "__main__":
    main()
