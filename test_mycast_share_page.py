"""T-645: the shared MyCast episode card (/mycast/e/<token>). Offline: no Telegram, no Gemini, no network.

Covers escaping, the absence of private fields, the honest demo manifest (no play without an approved local file),
language choice, the DNA cover being the configurator's own drawing, and the inline JS parsing under node."""
import base64
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import mycast_listener_delivery as mld
import mycast_share_page as sp
from test_mycast_library import Base
from test_mycast_listener_delivery import CODE, at, ready_listener

ROOT = pathlib.Path(__file__).parent
IDS = [t[0] for t in mld.TOPICS]


def code(**kw):
    data = {"v": 1, "n": len(IDS), "t": [[IDS.index("tech.ai.claude"), "w"], [IDS.index("sports.boxing.pro"), "u"],
                                         [IDS.index("sports.football.upl"), "c", "Буча-Секретна"]],
            "c": {"tech.ai": ["моя приватна тема"]}, "f": [["x", "@private_follow"]],
            "s": ["Europe/Kyiv", "07:30", "days", ["mon", "fri"], 15], "o": ["two_hosts", "uk", ["Charon", "Kore"]],
            "d": "telegram", "x": "вільний текст автора", "k": [1, 1]}
    data.update(kw)
    return base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")


class RouteTest(Base):
    def publish(self, title="MyCast · 2026-11-13", profile=None):
        s = ready_listener(self.store)
        if profile:
            self.store.save_code(s, profile, approved=True)
        self.clock.t = at("2026-11-13", "07:31")
        self.d.claim(s, "2026-11-13")
        self.d.finish(s, "2026-11-13", True, seconds=720, file_id="SECRETFILE", title=title)
        token = self.visibility(s, "2026-11-13", True)["episode"]["public_url"].rsplit("/", 1)[1]
        return s, token

    def page(self, token, **kw):
        r = self.h[("GET", "/mycast/e/{token}")](token, **kw)
        return r, r.body.decode()

    def test_card_shows_player_cover_demos_and_public_dna_only(self):
        prof = code()
        s, token = self.publish(profile=prof)
        r, body = self.page(token)
        self.assertEqual(r.status_code, 200)
        self.assertEqual((r.headers["x-robots-tag"], r.headers["cache-control"]), ("noindex, nofollow", "no-store"))
        self.assertIn('<meta name="robots" content="noindex,nofollow">', body)
        self.assertIn(f'data-src="/mycast/e/{token}/audio.mp3"', body)
        self.assertIn('aria-roledescription="carousel"', body)
        self.assertIn("1 / 6", body)                                         # own episode + 5 demo cards
        self.assertIn("Claude", body)                                       # a chosen topic
        self.assertIn("Пн Пт · 07:30 · 15 хв", body)
        self.assertIn("Два ведучі · Українська", body)
        self.assertIn("Андрій", body)
        for private in ("777", "SECRETFILE", prof[:20], CODE[:20], s, "Тест", "private_follow", "Буча-Секретна",
                        "моя приватна тема", "вільний текст", "Europe/Kyiv", "Charon"):
            self.assertNotIn(private, body, private)

    def test_hostile_title_is_escaped_everywhere(self):
        evil = '</script><script>alert(1)</script>"\'<img src=x onerror=alert(2)>'
        _, token = self.publish(title=evil)
        _, body = self.page(token)
        self.assertNotIn("<script>alert", body)
        self.assertNotIn("<img src=x", body)
        self.assertEqual(body.count("<script>"), 1)
        self.assertEqual(body.count("</script>"), 1)
        script = body.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertNotIn("<", script.split(";", 1)[0])                      # the data blob has no raw '<'

    def test_language_query_then_browser_then_author(self):
        _, token = self.publish(profile=code())
        self.assertIn('<html lang="uk"', self.page(token)[1])
        self.assertIn('<html lang="en"', self.page(token, lang="en")[1])
        self.assertIn("About this podcast", self.page(token, lang="en")[1])
        self.assertIn("О подкасте", self.page(token, lang="ru")[1])
        self.assertEqual(sp.pick_lang("", "ru-RU,ru;q=0.9,en;q=0.8", "uk"), "ru")
        self.assertEqual(sp.pick_lang("", "de-DE,fr;q=0.8", "en"), "en")
        self.assertEqual(sp.pick_lang("xx", "", "zz"), "uk")

    def test_revoked_link_is_gone(self):
        s, token = self.publish()
        self.visibility(s, "2026-11-13", False)
        self.assertEqual(self.page(token)[0].status_code, 404)


class DemoManifestTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        (self.dir / "audio").mkdir()
        (self.dir / "audio" / "athens-uk.mp3").write_bytes(b"ID3")

    def tearDown(self):
        self.tmp.cleanup()

    def cards(self, demos):
        (self.dir / "demos.json").write_text(json.dumps({"demos": demos}), encoding="utf-8")
        return sp.demo_cards("uk", manifest=self.dir / "demos.json", audio_dir=self.dir / "audio")

    def test_only_an_approved_local_file_plays(self):
        base = {"id": "athens", "name": {"uk": "Афіни"}, "title": {"uk": "Акрополь"}}
        ok = self.cards([dict(base, audio="/static/mycast-share/audio/athens-uk.mp3", approved_by_owner=True)])
        self.assertEqual(ok[0]["audio"], "/static/mycast-share/audio/athens-uk.mp3")
        for bad in (dict(base, audio="/static/mycast-share/audio/athens-uk.mp3", approved_by_owner=False),
                    dict(base, audio="/static/mycast-share/audio/missing.mp3", approved_by_owner=True),
                    dict(base, audio="https://evil.example/a.mp3", approved_by_owner=True),
                    dict(base, audio="/static/mycast-share/audio/../../app.py", approved_by_owner=True),
                    dict(base, audio="/static/mycast-share/audio/athens-uk.mp3", approved_by_owner="yes")):
            self.assertIsNone(self.cards([bad])[0]["audio"], bad)
        self.assertEqual(self.cards([dict(base, id="../x")]), [])

    def test_soon_card_has_no_play_and_demo_text_is_escaped(self):
        demos = sp.demo_cards("uk", manifest=self.dir / "none.json")
        self.assertEqual(demos, [])
        demos = self.cards([{"id": "x", "name": {"uk": "<b>X</b>"}, "title": {"uk": "<script>t</script>"}, "audio": None}])
        rec = {"name": "Андрій", "code": code()}
        body = sp.render(rec, "2026-11-13", {"title": "T", "seconds": 60}, token="tok", page="/mycast", demos=demos)
        self.assertNotIn("<script>t", body)
        self.assertIn("&lt;b&gt;X&lt;/b&gt;", body)
        self.assertEqual(body.count('class="play"'), 1)                     # only the author's episode
        self.assertIn('class="soon"', body)

    def test_repo_manifest_is_honest(self):
        data = json.loads((ROOT / "static/mycast-share/demos.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(data["demos"]), 2)
        for d in data["demos"]:
            for key in ("name", "title", "desc", "meta"):
                self.assertEqual(set(d[key]), {"uk", "ru", "en"}, (d["id"], key))
            self.assertIn(d["motif"], sp._MOTIFS)
            if d.get("audio"):                                               # no audio is claimed without owner approval
                self.assertIs(d.get("approved_by_owner"), True)
                self.assertTrue((ROOT / d["audio"].lstrip("/")).is_file(), d["audio"])


class DnaTest(unittest.TestCase):
    def test_bad_codes_and_custom_scopes(self):
        self.assertIsNone(sp.dna("not base64 !!"))
        self.assertIsNone(sp.dna(base64.urlsafe_b64encode(b'{"v":9}').decode()))
        d = sp.dna(code())
        self.assertEqual(d["geo"], {"ukraine": 1, "world": 1})               # the custom city is not counted or shown
        self.assertEqual(d["ids"], sorted(["tech.ai.claude", "sports.boxing.pro", "sports.football.upl"]))
        self.assertEqual(d["custom_cats"], ["tech"])
        body = sp.render({"name": "", "code": "broken"}, "2026-11-13", {}, token="tok", page="/mycast", demos=[])
        self.assertIn("MyCast · 2026-11-13", body)                          # still a working page without settings
        self.assertNotIn('class="about', body)

    def test_categories_match_the_configurator(self):
        page = (ROOT / "static/mycast-configurator/index.html").read_text(encoding="utf-8")
        colors = dict(re.findall(r"(\w+):'(#[0-9a-f]{6})'", re.search(r"const COLORS = \{([^}]*)\}", page).group(1)))
        self.assertEqual(colors, {k: v[0] for k, v in sp.CATS.items()})
        if not shutil.which("node"):
            self.skipTest("node not installed")
        out = subprocess.run(["node", "-e", "const C=require('./static/mycast-configurator/configurator.js');"
                              "console.log(JSON.stringify(C.TAXONOMY.map(c=>[c.id,c.label])))"],
                             capture_output=True, text=True, check=True, cwd=ROOT)
        self.assertEqual({k: v for k, v in json.loads(out.stdout)}, {k: v[1] for k, v in sp.CATS.items()})

    def test_cover_is_the_configurator_drawing(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        page = (ROOT / "static/mycast-configurator/index.html").read_text(encoding="utf-8")
        src = page[page.index("function hash(s)"):page.index("/* The hero simulation")]
        ids = ["tech.ai.claude", "science.space.missions" if "science.space.missions" in IDS else IDS[-1], "sports.boxing.pro",
               "news.local.events" if "news.local.events" in IDS else IDS[40]] + IDS[50:60]
        labels = {k: v[1]["uk"] for k, v in sp.CATS.items()}
        js = (f"const COLORS={json.dumps({k: v[0] for k, v in sp.CATS.items()})};const LABELS={json.dumps(labels, ensure_ascii=False)};"
              f"const profile={{topics:Object.fromEntries({json.dumps(ids)}.map(i=>[i,{{}}]))}};"
              "function catOf(id){return id.split('.')[0]}function catLabel(c){return LABELS[c]}"
              + re.search(r"^function esc\(s\).*$", page, re.M).group(0) + src + ";process.stdout.write(coverSVG())")
        out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True)
        self.assertEqual(sp.cover_svg(ids, "uk"), out.stdout)


class ScriptTest(unittest.TestCase):
    def test_inline_js_parses(self):
        if not shutil.which("node"):
            self.skipTest("node not installed")
        body = sp.render({"name": "A", "code": code()}, "2026-11-13", {"title": "T", "seconds": 60}, token="tok", page="/mycast")
        script = body.split("<script>", 1)[1].split("</script>", 1)[0]
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(script)
        try:
            subprocess.run(["node", "--check", f.name], check=True, capture_output=True)
        finally:
            pathlib.Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main(verbosity=2)
