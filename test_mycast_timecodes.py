"""#468/#219 MyCast measured section timecodes + owner Telegram caption, retries without a duplicate MP3.

No network, no Telegram, no Gemini: fake openers and injected senders. Run: python test_mycast_timecodes.py
"""
import asyncio
import base64
import io
import json
import socket
import tempfile
from pathlib import Path
from urllib import error as urlerror

from fastapi import HTTPException
from starlette.datastructures import UploadFile

import mycast
import mycast_timecodes as mt
from test_mycast import _App, _Req, _Resp, fake_mp3, speech_pcm

SECTIONS = [{"line": 0, "title": "Світ AI"}, {"line": 3, "title": "Гроші і стартапи"}, {"line": 6, "title": "Наша кухня"}]


def _episode(eid="mycast-2026-11-25", n_lines=9, sections=SECTIONS):
    ep = {"id": eid, "title": "MyCast · 25 листопада", "language": "uk",
          "lines": [["A" if i % 2 == 0 else "B", ("Слово " * 40).strip()] for i in range(n_lines)]}
    if sections is not None:
        ep["sections"] = sections
    return ep


class _JReq(_Req):
    def __init__(self, worker, body):
        super().__init__(worker)
        self.body = body

    async def json(self):
        return self.body


def test_normalize_sections():
    raw = [{"line": 6, "title": "  Наша   кухня "}, {"line": 0, "title": "Світ"}, {"line": 0, "title": "дубль"},
           {"line": 99, "title": "поза"}, {"line": True, "title": "bool"}, {"line": "2", "title": "рядок"},
           {"line": 3, "title": ""}, "garbage", {"line": 4, "title": "Т" * 80}]
    out = mt.normalize_sections(raw, 9)
    assert out == [{"line": 0, "title": "Світ"}, {"line": 4, "title": "Т" * mt.TITLE_CHARS}, {"line": 6, "title": "Наша кухня"}]
    assert mt.normalize_sections(None, 9) == [] and mt.normalize_sections({"line": 0}, 9) == []
    many = [{"line": n, "title": f"Розділ {n}"} for n in range(30)]
    assert len(mt.normalize_sections(many, 30)) == mt.MAX_SECTIONS


def test_build_index_never_guesses():
    secs = mt.normalize_sections(SECTIONS, 9)
    ok = mt.build_index(secs, {0: 0.0, 3: 61.234, 6: 130.5}, pcm_seconds=200.0, mp3_seconds=200.07)
    assert ok["status"] == "ok" and [c["start"] for c in ok["chapters"]] == [0.0, 61.23, 130.5]
    assert ok["encoder_drift_seconds"] == 0.07
    # A boundary that was not measured (inside a TTS call, older render) → explicit unavailable, no estimate.
    for starts, mp3, reason in (({0: 0.0, 6: 130.5}, 200.0, "not_measured"),
                                ({0: 0.0, 3: 140.0, 6: 130.5}, 200.0, "not_monotonic"),
                                ({0: 0.0, 3: 60.0, 6: 205.0}, 200.0, "outside_audio"),
                                ({0: 0.0, 3: 60.0, 6: 130.0}, 201.2, "mp3_drift"),
                                ({0: 0.0, 3: 60.0, 6: 130.0}, None, "no_mp3_length")):
        index = mt.build_index(secs, starts, pcm_seconds=200.0, mp3_seconds=mp3)
        assert index["status"] == "unavailable" and index["reason"] == reason and index["chapters"] == [], (reason, index)
        assert mt.chapters_block(index).startswith("⏱ Таймкоди недоступні: ")
    assert mt.build_index([], {}, pcm_seconds=10, mp3_seconds=10)["status"] == "none"
    assert mt.chapters_block(mt.build_index([], {}, pcm_seconds=10, mp3_seconds=10)) == ""
    assert mt.stamp(0.99) == "00:00" and mt.stamp(61.9) == "01:01" and mt.stamp(3725) == "1:02:05"
    assert mt.chapters_block(ok) == "⏱ Зміст:\n00:00 Світ AI\n01:01 Гроші і стартапи\n02:10 Наша кухня"


def test_long_caption_keeps_timecodes():
    secs = [{"line": n, "title": "Дуже довга назва розділу для перевірки ліміту " + str(n)} for n in range(12)]
    index = mt.build_index(mt.normalize_sections(secs, 12), {n: n * 65.0 for n in range(12)}, pcm_seconds=900, mp3_seconds=900)
    base = "🎧 MyCast · 25 листопада · ~8 хв\n" + "\n".join(f"• Джерело номер {n} з довгою назвою " + "x" * 60 for n in range(6))
    caption = mt.compose_caption(base, index)
    assert len(caption) <= mt.CAPTION_LIMIT and caption.startswith("🎧 MyCast")
    assert caption.endswith(mt.chapters_block(index)) and "11:55 " in caption  # every timecode survives
    assert "Джерело номер 5" not in caption  # sources gave way, whole lines only
    # Even an oversized first line cannot push the block out.
    assert mt.compose_caption("X" * 3000, index).endswith(mt.chapters_block(index))
    assert len(mt.compose_caption("X" * 3000, index)) <= mt.CAPTION_LIMIT
    # No sections: exactly the old caption.
    assert mt.compose_caption("🎧 a\n• b", None) == "🎧 a\n• b"


def _gemini_opener(seconds_per_chunk, calls):
    def opener(req, timeout):
        body = json.loads(req.data)
        calls.append(body)
        n = len(calls) - 1
        pcm = b"\x00\x10" * int(24000 * seconds_per_chunk[n % len(seconds_per_chunk)])  # 4096: loud enough for QC
        return _Resp(json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {
            "mimeType": "audio/L16;codec=pcm;rate=24000", "data": base64.b64encode(pcm).decode()}}]}}]}).encode())
    return opener


def test_gemini_boundaries_are_measured_pcm_offsets():
    ep = _episode()
    calls, marks = [], {}
    lengths = [3.2, 4.1, 2.7]
    pcm, rate = mycast.gemini_tts_pcm("K", ep, model="m", voices=("Puck", "Leda"), opener=_gemini_opener(lengths, calls), marks=marks)
    # Each section opens its own TTS call even though the text would fit into one.
    assert len(calls) == 3 and sum(len(c) for c in mycast.episode_chunks(ep["lines"])) == 9
    assert len(mycast.episode_chunks(ep["lines"])) == 1 and len(mycast.episode_chunks(ep["lines"], {0, 3, 6})) == 3
    pause = int(24000 * 0.35)
    samples = [int(24000 * s) for s in lengths]  # what the fake Gemini returned, sample for sample
    assert marks == {0: 0.0, 3: round((samples[0] + pause) / 24000, 6), 6: round((samples[0] + samples[1] + 2 * pause) / 24000, 6)}
    # Alignment against the PCM itself: the sample at each mark is the first one of its chunk, preceded by the pause.
    for line in (3, 6):
        at = round(marks[line] * rate) * 2
        assert pcm[at:at + 2] == b"\x00\x10" and pcm[at - 2:at] == b"\x00\x00"
    # 2 voices: the owner's pair reaches every call.
    for body in calls:
        cfg = body["generationConfig"]["speechConfig"]["multiSpeakerVoiceConfig"]["speakerVoiceConfigs"]
        assert [c["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] for c in cfg] == ["Puck", "Leda"]
    # Without sections the chunking (and the number of free-tier calls) is unchanged.
    calls.clear()
    mycast.gemini_tts_pcm("K", _episode(sections=None), model="m", opener=_gemini_opener(lengths, calls))
    assert len(calls) == 1


def _voice_route(state, sent, log):
    app = _App()

    def tts(key, episode, model="", voices=(), stats=None, marks=None):
        state["voices_seen"].append(voices)
        return mycast.gemini_tts_pcm(key, episode, model="m", voices=voices, stats=stats, marks=marks,
                                     opener=_gemini_opener([20.0, 25.0, 30.0], []))

    def send(audio, filename, title, caption):
        if state.get("telegram") == "uncertain":
            raise mycast.TelegramUncertain("timeout")
        if state.get("telegram") == "down":
            raise RuntimeError("telegram said no")
        sent.append({"filename": filename, "caption": caption})
    mycast.install_mycast_voice_routes(app, log, authorize_worker=lambda r: r.worker, send_audio=send,
                                       paired=lambda: state["paired"], api_key=lambda: "K", voices=lambda: state["pair"],
                                       tts=tts, encode=lambda pcm, rate: fake_mp3(len(pcm) / 2 / rate))
    route = app.routes["/api/factory/mycast/worker/voice-deliver"]

    def call(body):
        try:
            return 200, asyncio.run(route(_JReq(True, body)))
        except HTTPException as exc:
            return exc.status_code, exc.detail
    return call


def test_voice_route_caption_retry_consent_am_pm():
    log = mycast.DeliveryLog(Path(tempfile.mkdtemp()) / "d.json")
    sent, state = [], {"paired": True, "pair": ("Charon", "Kore"), "voices_seen": []}
    call = _voice_route(state, sent, log)
    am = _episode("mycast-2026-11-25-am", n_lines=9)
    for line in am["lines"]:
        line[1] = ("Слово " * 22).strip()  # 198 words → ~85 s expected; 75 s of measured audio passes QC
    pm = json.loads(json.dumps(am))
    pm["id"] = "mycast-2026-11-25-pm"

    # Consent / chat: unpaired owner chat → nothing sent, nothing claimed; a chat id in the body is never used.
    state["paired"] = False
    assert call({"episode": am}) == (409, "Telegram owner chat is not paired") and sent == [] and log.delivered() == []
    state["paired"] = True

    # Ambiguous Telegram outcome: claim kept, no MP3 resent on any later retry (Gemini or Piper).
    state["telegram"] = "uncertain"
    assert call({"episode": am, "chat_id": "999"})[0] == 504
    state["telegram"] = None
    assert call({"episode": am}) == (200, {"sent": False, "duplicate": True, "voice": "gemini"}) and sent == []
    assert [a["status"] for a in log.attempts(am["id"])] == ["uncertain", "duplicate_refused"]

    # Definite Telegram failure: released, so the next attempt delivers exactly once.
    state["telegram"] = "down"
    assert call({"episode": pm, "chat_id": "999"}) == (502, "voice delivery failed") and pm["id"] not in log.delivered()
    state["telegram"], state["pair"] = None, ("Puck", "Leda")
    code, body = call({"episode": pm, "chat_id": "999"})
    assert code == 200 and body["sent"] and body["chapters"]["status"] == "ok", body
    starts = [c["start"] for c in body["chapters"]["chapters"]]
    pause = int(24000 * 0.35) / 24000
    assert starts == [0.0, round(20.0 + pause, 2), round(45.0 + 2 * pause, 2)]
    caption = sent[-1]["caption"]
    assert caption.startswith("🎧 MyCast") and "голоси Gemini" in caption and len(caption) <= mt.CAPTION_LIMIT
    assert caption.endswith("⏱ Зміст:\n00:00 Світ AI\n00:20 Гроші і стартапи\n00:45 Наша кухня")
    assert call({"episode": pm})[1]["duplicate"] is True and len(sent) == 1
    assert [a["status"] for a in log.attempts(pm["id"])] == ["failed:voice_failed", "sent", "duplicate_refused"]
    assert log.attempts(pm["id"])[1]["chapters"] == "ok"
    assert state["voices_seen"][-1] == ("Puck", "Leda")

    # AM and PM of the same day are separate episodes: each is sent once, neither blocks the other.
    am2 = dict(am, id="mycast-2026-11-26-am")
    assert call({"episode": am2})[1]["sent"] is True and len(sent) == 2
    assert sent[-1]["filename"] == "mycast-2026-11-26-am.mp3"

    # An episode with section tags the audio cannot place gets an explicit "unavailable", never invented times.
    def no_marks_tts(key, episode, model="", voices=(), stats=None):
        return mycast.gemini_tts_pcm(key, episode, model="m", voices=voices, stats=stats, opener=_gemini_opener([25.0], []))
    app = _App()
    mycast.install_mycast_voice_routes(app, log, authorize_worker=lambda r: True, send_audio=lambda *a: sent.append({"caption": a[3]}),
                                       paired=lambda: True, api_key=lambda: "K", tts=no_marks_tts,
                                       encode=lambda pcm, rate: fake_mp3(len(pcm) / 2 / rate))
    body = asyncio.run(app.routes["/api/factory/mycast/worker/voice-deliver"](_JReq(True, {"episode": dict(am, id="mycast-2026-11-27-am")})))
    assert body["chapters"] == {**body["chapters"], "status": "unavailable", "reason": "not_measured"}
    assert sent[-1]["caption"].endswith("⏱ Таймкоди недоступні: межі розділів не виміряно")


def test_piper_route_uses_render_measurements():
    app, sent = _App(), []
    log = mycast.DeliveryLog(Path(tempfile.mkdtemp()) / "d.json")
    state = {"telegram": None}

    def send(audio, filename, title, caption):
        if state["telegram"] == "uncertain":
            raise mycast.TelegramUncertain("reset")
        sent.append(caption)
    mycast.install_mycast_routes(app, log, authorize_worker=lambda r: True, send_audio=send, paired=lambda: True)
    deliver = app.routes["/api/factory/mycast/worker/deliver"]

    def call(eid, chapters, seconds=60.0):
        try:
            return 200, asyncio.run(deliver(_Req(True), episode_id=eid, title="MyCast", caption="🎧 MyCast · ~1 хв\n• Джерело",
                                            audio=UploadFile(io.BytesIO(fake_mp3(seconds)), filename="a.mp3"), chapters=chapters))
        except HTTPException as exc:
            return exc.status_code, exc.detail
    measured = {"episode_id": "mycast-2026-11-25", "n_lines": 9, "sections": SECTIONS, "pcm_seconds": 59.6,
                "line_starts": {str(n): round(n * 6.62, 3) for n in range(9)}, "source": "piper-wav-frames"}
    code, body = call("mycast-2026-11-25", json.dumps(measured, ensure_ascii=False))
    assert code == 200 and body["chapters"]["status"] == "ok"
    assert [c["start"] for c in body["chapters"]["chapters"]] == [0.0, 19.86, 39.72]
    assert sent[-1] == "🎧 MyCast · ~1 хв\n• Джерело\n\n⏱ Зміст:\n00:00 Світ AI\n00:19 Гроші і стартапи\n00:39 Наша кухня"
    # The MP3 is 3 s longer than the WAV the offsets came from → unavailable, audio still goes out.
    code, body = call("mycast-2026-11-26", json.dumps(dict(measured, pcm_seconds=57.0)))
    assert code == 200 and body["chapters"]["reason"] == "mp3_drift" and "Таймкоди недоступні" in sent[-1]
    # Old worker / old render: no field → the caption and the answer are exactly as before.
    assert call("mycast-2026-11-27", "") == (200, {"sent": True, "duplicate": False, "seconds": fake_mp3_seconds(60.0)})
    assert sent[-1] == "🎧 MyCast · ~1 хв\n• Джерело"
    # Garbage measurement → unavailable, never a crash.
    assert call("mycast-2026-11-28", "{not json")[1]["chapters"]["status"] == "unavailable"
    # Ambiguous Telegram outcome on the Piper path: kept claimed, the retry is refused as a duplicate.
    state["telegram"] = "uncertain"
    assert call("mycast-2026-11-29", "")[0] == 504
    state["telegram"] = None
    assert call("mycast-2026-11-29", "") == (200, {"sent": False, "duplicate": True})
    assert [a["status"] for a in log.attempts("mycast-2026-11-29")] == ["uncertain", "duplicate_refused"]


def fake_mp3_seconds(seconds):
    return mycast.mp3_report(fake_mp3(seconds))["seconds"]


def test_send_audio_failure_classes():
    def raising(exc):
        def opener(req, timeout):
            raise exc
        return opener
    cases = ((urlerror.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b"")), RuntimeError, False),
             (urlerror.URLError(ConnectionRefusedError()), RuntimeError, False),
             (urlerror.URLError(socket.gaierror()), RuntimeError, False),
             (urlerror.URLError(TimeoutError()), mycast.TelegramUncertain, True),
             (TimeoutError(), mycast.TelegramUncertain, True),
             (ConnectionResetError(), mycast.TelegramUncertain, True))
    for exc, kind, uncertain in cases:
        try:
            mycast.telegram_send_audio("t", "c", b"x", filename="f", title="t", caption="", opener=raising(exc))
            raise AssertionError("must raise")
        except RuntimeError as got:
            assert isinstance(got, kind) and isinstance(got, mycast.TelegramUncertain) is uncertain, (exc, got)
    try:
        mycast.telegram_send_audio("t", "c", b"x", filename="f", title="t", caption="", opener=lambda r, timeout: _Resp(b"<html>"))
        raise AssertionError("must raise")
    except mycast.TelegramUncertain:
        pass
    # The caption that reaches Telegram is capped below its 1024 limit.
    seen = {}

    def ok(req, timeout):
        seen["body"] = req.data
        return _Resp(b'{"ok": true, "result": {"audio": {"file_id": "F"}}}')
    mycast.telegram_send_audio("t", "4242", b"x", filename="f", title="t", caption="я" * 1500, opener=ok)
    assert ("я" * 1000).encode() in seen["body"] and ("я" * 1001).encode() not in seen["body"]


def test_worker_uncertain_and_measured_download():
    from autopilot import mycast_daily as md
    import autopilot.test_mycast_daily as tmd

    # download_mp3 picks up the render's measurement for this episode only.
    def gh_fn(*args):
        out = Path(args[args.index("-D") + 1])
        (out / "mycast-2026-11-25.mp3").write_bytes(b"ID3audio")
        (out / "mycast-2026-11-25.chapters.json").write_text(json.dumps({"episode_id": "mycast-2026-11-25", "line_starts": {"0": 0}}))
        return 0, ""
    measured = {}
    assert md.download_mp3("1", "mycast-2026-11-25", gh_fn=gh_fn, measured=measured) == b"ID3audio"
    assert measured["line_starts"] == {"0": 0}
    other = {}
    assert md.download_mp3("1", "mycast-2026-11-24", gh_fn=gh_fn, measured=other) == b"" and other == {}

    # Telegram did not confirm the Gemini episode → no Piper resend, one honest notice, no retries today.
    state_path = Path(tempfile.mkdtemp()) / "mycast.json"
    at = tmd.kyiv_ts(2026, 11, 25, 7, 30)
    names = ("generate_episode", "publish", "sync_branch", "wait_render", "download_mp3", "deliver", "deliver_gemini")
    saved = {n: getattr(md, n) for n in names}
    saved_conf = md.relay_tasks.configured
    try:
        md.relay_tasks.configured = lambda: True
        md.generate_episode = lambda day, run_cli=None, status_text="": ("ok", dict(tmd.good_episode(), id="mycast-2026-11-25"))
        md.sync_branch = lambda: ""
        md.publish = lambda ep: "sha1"
        md.deliver_gemini = lambda ep: "uncertain"
        md.wait_render = lambda sha: (_ for _ in ()).throw(AssertionError("no Piper render after an unconfirmed send"))
        md.deliver = lambda *a, **k: (_ for _ in ()).throw(AssertionError("no Piper upload after an unconfirmed send"))
        msgs = []
        assert md.run_daily(state_path, now=at, send=lambda t: msgs.append(t) or True) == "delivered"
        assert sum("не підтвердив" in m for m in msgs) == 1 and any(m.startswith("📝") for m in msgs)
        assert md.run_daily(state_path, now=at + 3 * md.RETRY_SPACING_SECONDS, send=msgs.append) == "idle"
        # Piper path: the measurement goes to the server with the audio; an unconfirmed answer stops retries too.
        state_path.unlink()
        md.deliver_gemini = lambda ep: "unavailable"
        md.wait_render = lambda sha: "42"
        md.download_mp3 = lambda run_id, eid, measured=None: measured.update({"line_starts": {"0": 0.0}}) or b"ID3audio"
        got = []
        md.deliver = lambda ep, audio, measured=None: got.append(measured) or "uncertain"
        msgs = []
        assert md.run_daily(state_path, now=at, send=lambda t: msgs.append(t) or True) == "delivered"
        assert got == [{"line_starts": {"0": 0.0}}] and sum("не підтвердив" in m for m in msgs) == 1
    finally:
        for n, v in saved.items():
            setattr(md, n, v)
        md.relay_tasks.configured = saved_conf


def test_prompt_asks_for_section_tags_not_times():
    from autopilot import mycast_daily as md
    text = md.PROMPT.format(date="2026-11-25", date_human="25 листопада 2026", factory_status="-")
    assert '"sections": [{"line": 0' in text and "Час не пиши" in text


def main():
    test_normalize_sections()
    test_build_index_never_guesses()
    test_long_caption_keeps_timecodes()
    test_gemini_boundaries_are_measured_pcm_offsets()
    test_voice_route_caption_retry_consent_am_pm()
    test_piper_route_uses_render_measurements()
    test_send_audio_failure_classes()
    test_worker_uncertain_and_measured_download()
    test_prompt_asks_for_section_tags_not_times()
    print("MyCast timecode tests passed")


if __name__ == "__main__":
    main()
