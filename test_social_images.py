"""T-713 Social autopilot post images: teaser card, approval covers the image, Telegram sendPhoto, LinkedIn Images API.
Offline: fake HTTP and clock, handlers called directly (no TestClient: CI has no httpx)."""
import hashlib
import io
import json
import os
import pathlib
import re
import tempfile
import unittest
from unittest import mock

from fastapi import FastAPI, HTTPException
from PIL import Image

import linkedin_publisher as lp
import social_autopilot as sa
import social_images as si
from oauth_framework import MemoryTokenVault, OAuthFlow, TokenSet
from test_social_autopilot import ON, TOKEN, Clock, FakeAdapter, FakeHttp, call, kyiv, tg_ok

ROOT = pathlib.Path(__file__).resolve().parent
RU = "🚀 Мы запустили FactoryOS: фабрику, которая сама ведёт соцсети. Первый пост вышел без участия человека.\n\n" \
     "Подробнее: https://example.com/a"


class TeaserAndCardTest(unittest.TestCase):
    def test_teaser_takes_the_hook_without_emoji_or_links(self):
        t = si.teaser(RU)
        self.assertEqual(t["headline"], "Мы запустили FactoryOS: фабрику, которая сама ведёт соцсети. "
                                        "Первый пост вышел без участия человека.")
        self.assertNotIn("http", t["headline"] + t["sub"])
        self.assertEqual(t["lang"], "ru")
        self.assertEqual(si.teaser("Їжак і ґанок")["lang"], "uk")
        self.assertEqual(si.teaser("Hello")["lang"], "en")
        long = si.teaser("Перше речення про фабрику. " + "Друге речення дуже довге " * 10)
        self.assertEqual(long["headline"], "Перше речення про фабрику.")
        self.assertTrue(long["sub"].endswith("…") and len(long["sub"]) <= si.SUB_MAX + 1)
        word_cut = si.teaser("слово " * 40)["headline"]
        self.assertTrue(word_cut.endswith("…") and len(word_cut) <= si.HEADLINE_MAX + 1)
        self.assertEqual(si.teaser("  \n https://x.y \n")["headline"], "BlackBoxLab")
        self.assertEqual(si.teaser("### • Заголовок\nтекст")["headline"], "Заголовок")

    def test_card_is_a_deterministic_1080_png_with_cyrillic(self):
        png = si.render_card(RU, "factory")
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))
        img = Image.open(io.BytesIO(png))
        self.assertEqual((img.size, img.format), ((1080, 1080), "PNG"))
        self.assertEqual(png, si.render_card(RU, "factory"))
        self.assertNotEqual(png, si.render_card(RU + " другой", "factory"))
        self.assertLess(len(png), 1_000_000)
        # Headline glyphs are really drawn (not empty tofu boxes): the text area has many white pixels.
        crop = img.convert("L").crop((124, 220, 1000, 760))
        self.assertGreater(sum(crop.histogram()[241:]), 5000)
        for text in ("", "x", "a" * 4000, "😀" * 50, "Ünïcödé — ‘quotes’ № 5"):
            self.assertEqual(Image.open(io.BytesIO(si.render_card(text, "t" * 200))).size, (1080, 1080))
        self.assertTrue((si.FONT_DIR / "DejaVuSans-Bold.ttf").is_file())

    def test_ai_generator_is_owner_opt_in_and_falls_back(self):
        class Ai(si.ImageGenerator):
            name = "ai_test"

            def __init__(self, out):
                self.out, self.calls = out, 0

            def render(self, text, topic=""):
                self.calls += 1
                if isinstance(self.out, Exception):
                    raise self.out
                return self.out

        good = Ai(b"\x89PNG\r\n\x1a\n" + b"x" * 10)
        self.assertEqual(si.generator_from_env({}).name, "template_card")
        self.assertEqual(si.generator_from_env({}, ai=good).name, "template_card")     # off by default
        self.assertEqual(si.generator_from_env({"FACTORY_SOCIAL_AI_IMAGES": "0"}, ai=good).name, "template_card")
        on = si.generator_from_env({"FACTORY_SOCIAL_AI_IMAGES": "1"}, ai=good)
        self.assertEqual(on.render("x"), good.out)
        for bad in (Ai(RuntimeError("quota")), Ai(b"not a png")):
            gen = si.generator_from_env({"FACTORY_SOCIAL_AI_IMAGES": "1"}, ai=bad)
            self.assertEqual(gen.render("x"), si.render_card("x"))
            self.assertEqual(gen.last, "template_card")
        with tempfile.TemporaryDirectory() as tmp:
            meta = si.ImageMaker(pathlib.Path(tmp), gen).make("sp_0123456789ab", "x")
            self.assertEqual(meta["generator"], "template_card")

    def test_image_maker_verifies_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            maker = si.ImageMaker(pathlib.Path(tmp))
            meta = maker.make("sp_0123456789ab", RU, "factory")
            self.assertRegex(meta["file"], r"^sp_0123456789ab-[0-9a-f]{16}\.png$")
            path = pathlib.Path(tmp) / "social_images" / meta["file"]
            self.assertEqual(maker.read(meta), path.read_bytes())
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), meta["sha256"])
            self.assertIsNone(maker.read({**meta, "file": "../../etc/passwd"}))
            path.write_bytes(b"tampered")
            self.assertIsNone(maker.read(meta))
            maker.remove(meta)
            self.assertFalse(path.exists())
            with self.assertRaises(ValueError):
                maker.make("../x", "t")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.clock = Clock()
        self.env = dict(ON)
        self.images = si.ImageMaker(self.dir)
        self.store = sa.Store(self.dir, clock=self.clock, images=self.images)
        self.tg, self.li = FakeAdapter("telegram"), FakeAdapter("linkedin")
        self.pilot = sa.Autopilot(self.store, {"telegram": self.tg, "linkedin": self.li}, env=self.env,
                                  clock=self.clock)

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, item_id):
        return next(i for i in self.store.snapshot()["items"] if i["id"] == item_id)


class ApprovalTest(Base):
    def test_every_item_gets_an_image_and_the_approval_covers_it(self):
        item = self.store.create("telegram", RU, kyiv("2026-11-18T11:00"), topic="factory")
        meta = item["image"]
        self.assertEqual((meta["w"], meta["h"], meta["generator"]), (1080, 1080, "template_card"))
        self.assertTrue((self.dir / "social_images" / meta["file"]).is_file())
        approved = self.store.approve(item["id"])
        self.assertEqual(approved["approved_hash"], sa.approval_hash("telegram", RU, meta["sha256"]))
        self.assertNotEqual(approved["approved_hash"], sa.approval_hash("telegram", RU))
        out = self.pilot.tick()
        self.assertEqual(out["sent"], [item["id"]])
        image, alt = self.tg.images[0]
        self.assertEqual(hashlib.sha256(image).hexdigest(), meta["sha256"])
        self.assertEqual(alt, meta["headline"])

    def test_editing_the_text_redraws_the_image_and_drops_the_approval(self):
        item = self.store.create("telegram", RU, kyiv("2026-11-18T13:00"))
        self.store.approve(item["id"])
        old = item["image"]
        moved = self.store.edit(item["id"], planned_at=kyiv("2026-11-18T14:00"))       # time only: same image
        self.assertEqual((moved["image"]["file"], moved["status"]), (old["file"], "draft"))
        self.store.approve(item["id"])
        edited = self.store.edit(item["id"], text="Совсем другой текст поста про фабрику")
        self.assertEqual((edited["status"], edited["approved_hash"]), ("draft", ""))
        self.assertNotEqual(edited["image"]["sha256"], old["sha256"])
        self.assertFalse((self.dir / "social_images" / old["file"]).exists())        # the old teaser is gone
        self.store.delete(item["id"])
        self.assertEqual(list((self.dir / "social_images").glob("*.png")), [])

    def test_a_swapped_or_lost_image_file_is_never_sent(self):
        a = self.store.create("telegram", RU, kyiv("2026-11-18T11:00"))
        self.store.approve(a["id"])
        (self.dir / "social_images" / a["image"]["file"]).write_bytes(b"\x89PNG\r\n\x1a\nother")
        out = self.pilot.tick()
        self.assertEqual((out["sent"], out["waiting"]), ([], [a["id"]]))
        self.assertEqual(self.get(a["id"])["waiting"], ["image_missing"])
        self.assertEqual(self.tg.sent, [])
        # Claim refuses image bytes other than the approved ones.
        self.assertIsNone(self.store.claim(a["id"], image_sha="0" * 64))
        self.assertIsNone(self.store.claim(a["id"], image_sha=""))
        # A lost file: redrawn, and the approval goes back to the owner.
        (self.dir / "social_images" / a["image"]["file"]).unlink()
        self.assertEqual(self.store.ensure_images(), 1)
        fresh = self.get(a["id"])
        self.assertEqual((fresh["status"], fresh["waiting"]), ("draft", ["image_added_reapprove"]))
        self.store.approve(a["id"])
        self.assertEqual(self.pilot.tick()["sent"], [a["id"]])

    def test_items_from_before_images_get_one_and_need_a_new_approval(self):
        legacy = sa.Store(self.dir, clock=self.clock)                                   # T-702 store, no images
        d = legacy.create("telegram", "Old draft about the factory", kyiv("2026-11-19T10:00"))
        a = legacy.create("linkedin", "Old approved post about the factory", kyiv("2026-11-18T11:00"))
        legacy.approve(a["id"])
        self.assertNotIn("image", d)
        state = self.pilot.state()                                                      # page load backfills
        items = {i["id"]: i for i in state["items"]}
        self.assertTrue(items[d["id"]]["image_url"].startswith(f"/api/factory/social/items/{d['id']}/image?v="))
        self.assertEqual(items[a["id"]]["status"], "draft")
        self.assertEqual(state["images"], {"enabled": True, "generator": "template_card"})
        self.assertEqual(self.pilot.tick()["sent"], [])
        self.assertEqual(self.store.ensure_images(), 0)

    def test_failed_render_blocks_approval_until_an_image_exists(self):
        with mock.patch.object(self.images, "make", side_effect=OSError("disk")):
            item = self.store.create("telegram", RU, kyiv("2026-11-19T10:00"))
        self.assertIsNone(item["image"])
        with self.assertRaises(HTTPException) as err:
            self.store.approve(item["id"])
        self.assertEqual(err.exception.status_code, 409)
        self.assertEqual(self.store.approve_plan(0, 2 ** 40), [])
        self.assertEqual(self.store.ensure_images(), 1)
        self.assertEqual(self.store.approve_plan(0, 2 ** 40), [item["id"]])

    def test_rules_mode_approves_text_and_image_together(self):
        self.store.update_settings({"mode": "rules", "rules_opt_in": True})
        item = self.store.create("telegram", RU, kyiv("2026-11-18T11:00"))
        self.assertEqual(self.pilot.tick()["sent"], [item["id"]])
        self.assertEqual(self.get(item["id"])["approved_hash"],
                         sa.approval_hash("telegram", RU, item["image"]["sha256"]))


class TelegramPhotoTest(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\nfakeimage"

    def adapter(self, http):
        return sa.TelegramChannelAdapter(lambda: TOKEN, lambda: "@blackboxlab", http)

    @staticmethod
    def fields(body: bytes) -> dict:
        out = {}
        for part in body.split(b"--factoryos")[1:]:
            m = re.search(rb'name="(\w+)"', part)
            if m:
                out[m.group(1).decode()] = part.split(b"\r\n\r\n", 1)[1].rsplit(b"\r\n", 1)[0]
        return out

    def test_short_post_is_one_photo_with_caption(self):
        http = FakeHttp(tg_ok(77))
        out = self.adapter(http).publish("Привет <b>канал</b>", image=self.PNG, alt="Привет")
        self.assertEqual(out, {"url": "https://t.me/blackboxlab/77", "external_id": "77"})
        self.assertEqual(len(http.calls), 1)
        method, url, headers, body = http.calls[0]
        self.assertEqual((method, url), ("POST", f"https://api.telegram.org/bot{TOKEN}/sendPhoto"))
        self.assertTrue(headers["Content-Type"].startswith("multipart/form-data; boundary=factoryos"))
        f = self.fields(body)
        self.assertEqual((f["chat_id"], f["caption"].decode(), f["photo"]),
                         (b"@blackboxlab", "Привет <b>канал</b>", self.PNG))
        self.assertNotIn("parse_mode", f)

    def test_long_post_is_photo_with_headline_then_full_text_as_reply(self):
        text = "Заголовок поста\n\n" + "Длинный текст. " * 100
        self.assertGreater(len(text), sa.TG_CAPTION_MAX)
        http = FakeHttp(tg_ok(10), tg_ok(11))
        out = self.adapter(http).publish(text, image=self.PNG, alt="Заголовок поста")
        self.assertEqual(out, {"url": "https://t.me/blackboxlab/10", "external_id": "10,11"})
        self.assertEqual(self.fields(http.calls[0][3])["caption"].decode(), "Заголовок поста")
        reply = json.loads(http.calls[1][3])
        self.assertEqual(http.calls[1][1].rsplit("/", 1)[1], "sendMessage")
        self.assertEqual((reply["text"], reply["reply_parameters"]), (text, {"message_id": 10}))
        self.assertNotIn("parse_mode", reply)
        # Exactly 1024 UTF-16 units still fits in one caption; emoji count as two.
        one = FakeHttp(tg_ok(5))
        self.adapter(one).publish("я" * 1024, image=self.PNG)
        self.assertEqual(len(one.calls), 1)
        two = FakeHttp(tg_ok(6), tg_ok(7))
        self.adapter(two).publish("😀" * 513, image=self.PNG, alt="")
        self.assertEqual(len(two.calls), 2)
        self.assertLessEqual(sa.utf16_len(self.fields(two.calls[0][3])["caption"].decode()), sa.TG_CAPTION_MAX)

    def test_text_failing_after_the_photo_is_uncertain_with_the_photo_link(self):
        text = "x" * 2000
        for second in ((400, {}, {"ok": False}), TimeoutError(), (502, {}, b"")):
            with self.assertRaises(sa.PublishError) as err:
                self.adapter(FakeHttp(tg_ok(10), second)).publish(text, image=self.PNG, alt="x")
            self.assertEqual((err.exception.code, err.exception.uncertain, err.exception.url),
                             ("telegram_text_after_photo_failed", True, "https://t.me/blackboxlab/10"))
        with self.assertRaises(sa.PublishError) as err:                       # photo refused: nothing posted
            self.adapter(FakeHttp((403, {}, {"ok": False}))).publish(text, image=self.PNG)
        self.assertEqual((err.exception.code, err.exception.uncertain), ("telegram_bot_not_admin", False))
        with self.assertRaises(sa.PublishError) as err:
            self.adapter(FakeHttp(TimeoutError())).publish("short", image=self.PNG)
        self.assertEqual((err.exception.code, err.exception.uncertain), ("telegram_outcome_uncertain", True))

    def test_scheduler_records_the_half_published_link_and_never_resends(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = Clock()
            store = sa.Store(pathlib.Path(tmp), clock=clock, images=si.ImageMaker(pathlib.Path(tmp)))
            http = FakeHttp(tg_ok(10), (400, {}, {"ok": False}))
            pilot = sa.Autopilot(store, {"telegram": self.adapter(http)}, env=dict(ON), clock=clock)
            item = store.create("telegram", "Заголовок\n\n" + "текст " * 300, kyiv("2026-11-18T11:00"))
            store.approve(item["id"])
            self.assertEqual(pilot.tick()["uncertain"], [item["id"]])
            self.assertEqual(pilot.tick()["uncertain"], [])
            self.assertEqual(len(http.calls), 2)
            got = store.snapshot()["items"][0]
            self.assertEqual(got["result"], {"code": "telegram_text_after_photo_failed",
                                             "url": "https://t.me/blackboxlab/10"})
            photo = self.fields(http.calls[0][3])["photo"]
            self.assertEqual(hashlib.sha256(photo).hexdigest(), item["image"]["sha256"])


class LinkedInImageTest(unittest.TestCase):
    PNG = b"\x89PNG\r\n\x1a\nfakeimage"
    INIT = (200, {}, {"value": {"uploadUrl": "https://www.linkedin.com/dms-uploads/abc?ca=1",
                                "image": "urn:li:image:C4E10AQ_x-1", "uploadUrlExpiresAt": 1}})

    def test_upload_then_post_with_media_id(self):
        http = FakeHttp(self.INIT, (201, {}, b""), (201, {"x-restli-id": "urn:li:share:9"}, b""))
        urn = lp.upload_image(http, "AT", "urn:li:person:abc", self.PNG, "202510")
        out = lp.create_post(http, "AT", "urn:li:person:abc", "Пост #ai", "202510", image_urn=urn,
                             alt_text="Заголовок\nпоста")
        self.assertEqual(out["post_urn"], "urn:li:share:9")
        (m1, u1, h1, b1), (m2, u2, h2, b2), (m3, u3, h3, b3) = http.calls
        self.assertEqual((m1, u1), ("POST", "https://api.linkedin.com/rest/images?action=initializeUpload"))
        self.assertEqual(json.loads(b1), {"initializeUploadRequest": {"owner": "urn:li:person:abc"}})
        self.assertEqual((h1["LinkedIn-Version"], h1["X-Restli-Protocol-Version"]), ("202510", "2.0.0"))
        self.assertEqual((m2, u2, b2, h2["Authorization"]),
                         ("PUT", "https://www.linkedin.com/dms-uploads/abc?ca=1", self.PNG, "Bearer AT"))
        post = json.loads(b3)
        self.assertEqual(post["content"], {"media": {"id": "urn:li:image:C4E10AQ_x-1", "altText": "Заголовок поста"}})
        self.assertEqual(post["commentary"], r"Пост \#ai")
        text_only = FakeHttp((201, {"x-restli-id": "urn:li:share:1"}, b""))
        lp.create_post(text_only, "AT", "urn:li:person:abc", "t", "202510")
        self.assertNotIn("content", json.loads(text_only.calls[0][3]))

    def test_upload_failures_are_certain_and_the_token_stays_on_linkedin(self):
        evil = (200, {}, {"value": {"uploadUrl": "https://evil.example/upload", "image": "urn:li:image:x"}})
        cases = [(evil, "linkedin_image_init_failed", 1), ((200, {}, {"value": {}}), "linkedin_image_init_failed", 1),
                 ((401, {}, b""), "linkedin_auth_failed", 1), ((500, {}, b""), "linkedin_image_init_failed", 1),
                 (TimeoutError(), "linkedin_image_init_failed", 1)]
        for answer, code, n in cases:
            http = FakeHttp(answer)
            with self.assertRaises(lp.LinkedInError, msg=code) as err:
                lp.upload_image(http, "AT", "urn:li:person:abc", self.PNG, "202510")
            self.assertEqual((err.exception.code, err.exception.uncertain), (code, False))
            self.assertEqual(len(http.calls), n)
        for put in ((500, {}, b""), TimeoutError()):
            with self.assertRaises(lp.LinkedInError) as err:
                lp.upload_image(FakeHttp(self.INIT, put), "AT", "urn:li:person:abc", self.PNG, "202510")
            self.assertEqual((err.exception.code, err.exception.uncertain), ("linkedin_image_upload_failed", False))
        with self.assertRaises(lp.LinkedInError):
            lp.upload_image(FakeHttp(), "AT", "urn:li:person:abc", b"", "202510")
        with self.assertRaises(lp.LinkedInError):
            lp.create_post(FakeHttp(), "AT", "urn:li:person:abc", "t", "202510", image_urn="urn:li:share:1")
        self.assertFalse(lp.UPLOAD_HOST_RE.match("https://linkedin.com.evil.example/x"))
        self.assertTrue(lp.UPLOAD_HOST_RE.match("https://media.licdn.com/x"))

    def test_social_adapter_sends_the_image_through_send_text(self):
        vault, http = MemoryTokenVault(), FakeHttp()
        flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), vault,
                         adapters={"linkedin": lp.LinkedInOAuthAdapter(http)})
        creds = {"FACTORY_OAUTH_LINKEDIN_CLIENT_ID": "cid", "FACTORY_OAUTH_LINKEDIN_CLIENT_SECRET": "cs"}
        adapter = sa.LinkedInAdapter(flow, lambda: "default", env={"FACTORY_LINKEDIN_ENABLED": "1"})
        with mock.patch.dict(os.environ, creds):
            vault.put("default", "linkedin", TokenSet(access_token="AT", account_id="urn:li:person:abc"))
            http.answers += [self.INIT, (201, {}, b""), (201, {"x-restli-id": "urn:li:share:5"}, b"")]
            out = adapter.publish("hello", image=self.PNG, alt="hello")
            self.assertEqual(out["external_id"], "urn:li:share:5")
            self.assertEqual([c[0] for c in http.calls], ["POST", "PUT", "POST"])
            http.answers += [(403, {}, b"")]
            with self.assertRaises(sa.PublishError) as err:
                adapter.publish("again", image=self.PNG)
            self.assertEqual((err.exception.code, err.exception.uncertain), ("linkedin_permission_denied", False))
            self.assertEqual(len(http.calls), 4)                                   # no post call after the refusal


class RouteTest(Base):
    def test_image_route_is_owner_only_png(self):
        app = FastAPI()
        sa.install_routes(app, pilot=self.pilot, identity=lambda r: {"role": r.headers.get("x-role")})
        ep = next(r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/factory/social/items/{item_id}/image")
        item = self.store.create("telegram", RU, kyiv("2026-11-19T10:00"))
        with self.assertRaises(HTTPException) as err:
            call(ep, item["id"], role="member")
        self.assertEqual(err.exception.status_code, 403)
        resp = call(ep, item["id"])
        self.assertEqual((resp.media_type, resp.headers["cache-control"]), ("image/png", "private, max-age=86400"))
        self.assertEqual(hashlib.sha256(resp.body).hexdigest(), item["image"]["sha256"])
        for bad in ("sp_000000000000", "../../x"):
            with self.assertRaises(HTTPException) as err:
                call(ep, bad)
            self.assertEqual(err.exception.status_code, 404)


class WiringAndPageTest(unittest.TestCase):
    def test_app_wires_images_and_page_shows_them(self):
        src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("images=social_images.ImageMaker(DATA_DIR,social_images.generator_from_env())", src)
        self.assertIn("SOCIAL_AUTOPILOT.store.ensure_images", src)
        html = (ROOT / "static/social/index.html").read_text(encoding="utf-8")
        self.assertIn("i.image_url", html)
        self.assertIn('class="thumb"', html)
        for key in ("imgNote", "image_added_reapprove", "image_missing"):
            self.assertEqual(html.count(key + ":"), 3, key)


if __name__ == "__main__":
    unittest.main()
