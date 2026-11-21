"""Owner 2026-11-13: MyCast public podcast page, share card and opt-in listening by link. Offline."""
import json
import os
import pathlib
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-public-"))

import fastapi  # noqa: E402

import mycast_accounts as ma  # noqa: E402
import mycast_public as mp  # noqa: E402
from test_mycast_listener_delivery import CODE, Clock, at  # noqa: E402

SECRET = "s3cret"


class Req:
    def __init__(self, body=None, cookie=""):
        self._body, self.cookies = body, ({ma.COOKIE: cookie} if cookie else {})

    async def json(self):
        return self._body


def run(coro):
    import asyncio
    return asyncio.run(coro) if hasattr(coro, "__await__") else coro


class PublicPageTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.clock = Clock(at("2026-11-13", "08:00"))
        self.store = ma.ListenerStore(pathlib.Path(self.tmp.name) / "l.json", clock=self.clock)
        self.audio = []
        app = fastapi.FastAPI()
        ma.install_mycast_account_routes(app, self.store, secret=SECRET, bot_token=lambda: "", bot_username=lambda: "",
                                         google_client_id=lambda: "", google_verify=lambda c: {}, clock=self.clock,
                                         fetch_audio=lambda fid: self.audio.append(fid) or b"ID3mp3")
        self.h = {r.path: r.endpoint for r in app.routes if hasattr(r, "endpoint")}
        rec = self.store.login({"provider": "telegram", "pid": "777", "name": "Андрій <b>Тест</b>", "chat_id": "777"})
        self.slug = rec["slug"]
        self.store.save_code(self.slug, CODE, approved=True)
        self.cookie = ma.sign(SECRET, self.slug, self.clock())

    def tearDown(self):
        self.tmp.cleanup()

    def test_page_shows_the_podcast_not_the_editor_and_nothing_private(self):
        r = self.h["/mycast/u/{slug}"](self.slug)
        page = r.body.decode()
        self.assertEqual(r.status_code, 200)
        self.assertIn("Подкаст Андрій", page)
        self.assertIn('property="og:image"', page)
        self.assertIn(f"/mycast/u/{self.slug}/card.png?v=", page)
        self.assertIn(f"#p={CODE}&amp;from={self.slug}", page)             # "make one like this" keeps the referral
        self.assertIn("Професійний бокс", page)
        self.assertNotIn("777", page)
        self.assertNotIn("<b>Тест", page)                                  # surname dropped, markup never raw
        self.assertNotIn("latest.mp3", page)                               # listening by link is off by default
        self.assertNotIn('data-play="0"', page)
        self.assertIn(' id="pp" aria-label="Слухати" disabled', page)      # nothing to play: the bar's button is off
        self.assertTrue(self.h["/mycast/u/{slug}"]("nope").headers["location"].endswith("#missing"))

    def test_glass_page_matches_the_episode_page_and_switches_language(self):
        """T-710 (variant A): the same glass coverflow as /mycast/e/<token>, demo cities included, UK/RU/EN by ?lang=."""
        import mycast_share_page as sp
        page = self.h["/mycast/u/{slug}"](self.slug).body.decode()
        self.assertIn(sp.CSS, page)
        self.assertIn(sp.JS, page)
        self.assertEqual(page.count('<article class="card'), 1 + len(sp.demo_cards("uk")))
        self.assertIn('class="soon"', page)                                # demo tracks wait for the owner's approval
        self.assertIn("Автор ще не відкрив", page)
        self.assertNotIn("noindex", page)                                  # the profile page stays shareable and indexable
        self.assertIn(f'<link rel="canonical" href="https://mycast.pro/mycast/u/{self.slug}">', page)
        for name in ("Facebook", "Telegram", "WhatsApp"):
            self.assertIn(f">{name}</a>", page)
        ru = self.h["/mycast/u/{slug}"](self.slug, lang="ru").body.decode()
        self.assertIn('<html lang="ru">', ru)
        self.assertIn("Создать такой же", ru)
        self.assertIn("Профессиональный бокс", ru)                         # catalogue topics follow the page language
        self.assertIn('hreflang="ru" aria-current="true"', ru)
        self.assertIn('<html lang="uk">', self.h["/mycast/u/{slug}"](self.slug, lang="zz").body.decode())
        approved = mp.render_page(self.store.get(self.slug), __import__("mycast_listener_delivery").decode_profile(CODE), page="/p",
                                  demos=[{"id": "rome", "name": "<Rome>", "title": "T", "desc": "D", "meta": "M", "motif": "temple",
                                          "palette": [], "audio": "/mycast/demo/rome.uk.mp3"}])
        self.assertIn('data-src="/mycast/demo/rome.uk.mp3"', approved)
        self.assertNotIn("<Rome>", approved)
        self.assertNotIn(' id="pp" aria-label="Слухати" disabled', approved)

    def test_card_is_a_1200x630_png_and_cached(self):
        r = self.h["/mycast/u/{slug}/card.png"](self.slug)
        self.assertEqual((r.status_code, r.media_type), (200, "image/png"))
        from PIL import Image
        import io
        self.assertEqual(Image.open(io.BytesIO(r.body)).size, (1200, 630))
        from mycast_listener_delivery import decode_profile
        self.assertIs(mp.card_png(self.store.get(self.slug), decode_profile(CODE)), r.body)    # cached bytes
        self.assertEqual(self.h["/mycast/u/{slug}/card.png"]("zzzzzzzz").status_code, 404)

    def test_listening_by_link_only_after_the_listener_opts_in(self):
        with self.store._lock:
            data = self.store._load()
            data["listeners"][self.slug]["deliveries"] = {"2026-11-12": {"status": "sent", "file_id": "F1"},
                                                          "2026-11-13": {"status": "failed"}}
            self.store._save(data)
        audio = self.h["/mycast/u/{slug}/latest.mp3"]
        self.assertEqual(audio(self.slug).status_code, 404)
        self.assertEqual(run(self.h["/api/mycast/account/sharing"](Req({"public_audio": True}))).status_code, 401)
        on = run(self.h["/api/mycast/account/sharing"](Req({"public_audio": True}, self.cookie)))
        self.assertTrue(on["listener"]["public_audio"])
        r = audio(self.slug)
        self.assertEqual((r.status_code, r.body, self.audio), (200, b"ID3mp3", ["F1"]))
        opened = self.h["/mycast/u/{slug}"](self.slug).body.decode()
        self.assertIn(f'data-src="/mycast/u/{self.slug}/latest.mp3"', opened)
        self.assertIn('data-play="0"', opened)
        self.assertIn("MyCast · 2026-11-12", opened)
        mp._PLAYS[self.slug] = [self.clock()] * mp.PLAYS_PER_HOUR
        self.assertEqual(audio(self.slug).status_code, 429)
        mp._PLAYS.clear()
        run(self.h["/api/mycast/account/sharing"](Req({"public_audio": "yes"}, self.cookie)))    # only a real true turns it on
        self.assertEqual(audio(self.slug).status_code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
