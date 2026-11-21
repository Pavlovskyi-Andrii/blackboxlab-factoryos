"""Sandbox security regression checks. Run with python -m unittest discover -s sandbox -p test_server.py."""
import io
import os
import unittest
import zipfile
from pathlib import Path

import server


def make_zip(files):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, raw in files.items():
            z.writestr(name, raw)
    return buf.getvalue()


class SandboxSecurityTests(unittest.TestCase):
    def setUp(self):
        # Avoid shared state if tests are invoked after an import.
        self.before = set(server.SITES)

    def tearDown(self):
        for site_id in set(server.SITES) - self.before:
            server.SITES.pop(site_id, None)

    def test_four_sites_import_independently(self):
        ids = []
        for i in range(4):
            data = make_zip({"export/index.html": f"<h1>Demo {i}</h1>", "export/style.css": "h1{color:red}"})
            info = server.import_zip(data, f"demo-{i}.zip")
            ids.append(info["id"])
            self.assertEqual(info["files"], 2)
            self.assertEqual((server.ROOT / info["id"] / "index.html").read_text(), f"<h1>Demo {i}</h1>")
            url = server.link(info["id"])
            from urllib.parse import urlparse, parse_qs
            q = parse_qs(urlparse(url).query)
            self.assertTrue(server.verified(info["id"], q["exp"][0], q["sig"][0]))
        self.assertEqual(len(set(ids)), 4)

    def test_zip_slip_rejected(self):
        with self.assertRaises(server.InvalidArchive):
            server.import_zip(make_zip({"../x.html": "<h1>bad</h1>", "index.html": "ok"}), "bad.zip")

    def test_symlink_rejected(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("index.html", "ok")
            link = zipfile.ZipInfo("other.html")
            link.create_system = 3
            link.external_attr = (0o120777 << 16)
            z.writestr(link, "index.html")
        with self.assertRaises(server.InvalidArchive):
            server.import_zip(buf.getvalue(), "bad-link.zip")

    def test_script_and_unknown_extension_not_accepted(self):
        with self.assertRaises(server.InvalidArchive):
            server.import_zip(make_zip({"index.html": "ok", "setup.sh": "do not execute"}), "bad.zip")

    def test_missing_index_rejected(self):
        with self.assertRaises(server.InvalidArchive):
            server.import_zip(make_zip({"readme.txt": "hello"}), "not-site.zip")

    def test_expired_or_forged_signature_rejected(self):
        site_id = "abcdef12345678"
        self.assertFalse(server.verified(site_id, "1", server.sign(site_id, 1)))
        exp = int(__import__("time").time()) + 50
        self.assertFalse(server.verified(site_id, exp, "0" * 64))

    def test_bad_authorization_rejected(self):
        handler = object.__new__(server.Handler)
        handler.headers = {"Authorization": "Bearer attacker"}
        self.assertFalse(handler.auth())

    def test_strict_preview_policy_present(self):
        self.assertIn("script-src 'none'", __import__("inspect").getsource(server.Handler.do_GET))


if __name__ == "__main__":
    unittest.main()
