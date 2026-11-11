"""Owner voice → text via Gemini (owner: «1 вариант», 2026-11-08). Offline: fake Telegram, fake Gemini."""
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import voice_transcribe as vt

VOICE = {"kind": "voice", "file_id": "F1", "file_unique_id": "U1", "mime_type": "audio/ogg", "duration": 7}


class TranscriberTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.calls = []

        def fetch(token, file_id):
            self.calls.append(file_id)
            return b"OggS-audio"

        def transcribe(key, audio, mime):
            assert (key, audio, mime) == ("k", b"OggS-audio", "audio/ogg")
            return "Привіт, зроби тест круга Relay"
        self.tr = vt.VoiceTranscriber(Path(self.dir.name), api_key=lambda: "k", bot_token=lambda: "1:t",
                                      fetch=fetch, transcribe=transcribe, clock=lambda: self.t[0], daily_cap=2)

    def tearDown(self):
        self.dir.cleanup()

    def test_transcribes_and_caches_the_same_file(self):
        self.assertEqual(self.tr(VOICE), ("Привіт, зроби тест круга Relay", ""))
        self.assertEqual(self.tr(VOICE)[0], "Привіт, зроби тест круга Relay")
        self.assertEqual(self.calls, ["F1"])                                     # a repeat costs nothing

    def test_daily_cap_and_reset(self):
        self.tr({**VOICE, "file_unique_id": "a"}); self.tr({**VOICE, "file_unique_id": "b"})
        self.assertEqual(self.tr({**VOICE, "file_unique_id": "c"}), (None, "daily_limit"))
        self.t[0] += 86400
        self.assertEqual(self.tr({**VOICE, "file_unique_id": "c"})[1], "")

    def test_refusals(self):
        self.assertEqual(self.tr({"kind": "photo", "file_id": "x"}), (None, "not_voice"))
        self.assertEqual(self.tr({**VOICE, "file_id": ""}), (None, "no_file"))
        no_key = vt.VoiceTranscriber(Path(self.dir.name) / "n", api_key=lambda: "", bot_token=lambda: "1:t")
        self.assertEqual(no_key(VOICE), (None, "not_configured"))

        def boom(*a):
            raise vt.TranscribeError("rate_limited")
        failing = vt.VoiceTranscriber(Path(self.dir.name) / "f", api_key=lambda: "k", bot_token=lambda: "1:t",
                                      fetch=lambda *a: b"x", transcribe=boom)
        self.assertEqual(failing(VOICE), (None, "rate_limited"))

    def test_gemini_request_and_parsing(self):
        seen = {}

        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False

        def opener(req, timeout=0):
            seen["url"], seen["body"] = req.full_url, json.loads(req.data)
            seen["key"] = req.headers.get("X-goog-api-key")
            return Resp(json.dumps({"candidates": [{"content": {"parts": [{"text": " Текст повідомлення "}]}}]}).encode())
        self.assertEqual(vt.gemini_transcribe("k", b"abc", "audio/ogg", opener=opener), "Текст повідомлення")
        self.assertIn(":generateContent", seen["url"])
        self.assertEqual(seen["key"], "k")
        self.assertEqual(seen["body"]["contents"][0]["parts"][1]["inline_data"]["mime_type"], "audio/ogg")
        empty = lambda req, timeout=0: Resp(b'{"candidates":[]}')
        with self.assertRaises(vt.TranscribeError):
            vt.gemini_transcribe("k", b"abc", "audio/ogg", opener=empty)

    def test_telegram_refuses_long_files(self):
        class Resp(io.BytesIO):
            def __enter__(self): return self
            def __exit__(self, *a): return False
        big = lambda req, timeout=0: Resp(json.dumps({"ok": True, "result": {"file_path": "v.oga", "file_size": vt.MAX_BYTES + 1}}).encode())
        with self.assertRaises(vt.TranscribeError) as ctx:
            vt.telegram_file_bytes("1:t", "F1", opener=big)
        self.assertEqual(ctx.exception.reason, "too_long")


class WebhookTest(unittest.TestCase):
    """The real ASGI app: the owner's voice becomes a ticket with the transcript; another chat is never transcribed."""

    def post(self, chat_id, update_id):
        from test_worker_token_binding import asgi_post
        body = {"update_id": update_id, "message": {"message_id": update_id, "chat": {"id": chat_id, "type": "private"},
                                                    "voice": {"file_id": "F9", "file_unique_id": "U9", "duration": 5, "mime_type": "audio/ogg"}}}
        return asgi_post("/api/integrations/telegram/webhook", body=json.dumps(body).encode())

    def test_owner_voice_becomes_a_text_ticket(self):
        from test_worker_token_binding import factory
        sent, calls = [], []
        fake = lambda att: (calls.append(att["file_id"]) or ("Додай файл перевірки Relay", ""))
        with patch.object(factory, "VOICE_TRANSCRIBER", fake), \
             patch.object(factory, "_telegram_webhook_authorized", return_value=True), \
             patch.object(factory, "_telegram_load_state", return_value={"chat_id": "42"}), \
             patch.object(factory, "_telegram_send_to", side_effect=lambda c, t: sent.append((str(c), t))), \
             patch.object(factory, "_telegram_api", return_value={"ok": True}):
            status, _ = self.post(42, 7701)
            self.assertEqual(status, 200)
            self.assertEqual(calls, ["F9"])
            self.assertTrue(any("Распознал голосовое" in t and "Додай файл" in t for _, t in sent))
            ticket = next(t for t in factory.RELAY_STORE.list(limit=50) if (t.get("source") or {}).get("update_id") == 7701)
            self.assertIn("Додай файл перевірки Relay", ticket["title"] + ticket.get("body", ""))
            status, _ = self.post(93, 7702)                                      # not the paired owner
            self.assertEqual(status, 200)
            self.assertEqual(calls, ["F9"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
