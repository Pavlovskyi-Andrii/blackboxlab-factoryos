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


def main():
    test_send_audio_multipart()
    test_route()
    print("MyCast delivery tests passed")


if __name__ == "__main__":
    main()
