"""Secure pairing for an existing EC2 Claude subscription runner (no network)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from relay_pairing import create_pairing, valid_pairing, pairing_status


class TestRelayPairing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "relay_worker_pair.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_unconfigured_fails_closed(self):
        self.assertFalse(valid_pairing(self.path, "a"*64))
        self.assertFalse(pairing_status(self.path)["configured"])

    def test_secret_not_persisted_and_validates(self):
        created = create_pairing(self.path)
        token = created["token"]
        self.assertGreaterEqual(len(token), 40)
        stored = self.path.read_text()
        self.assertNotIn(token, stored)
        self.assertEqual(len(json.loads(stored)["digest"]), 64)
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)
        self.assertTrue(pairing_status(self.path)["configured"])
        self.assertNotIn("token", pairing_status(self.path))
        bad_token = token[:-1] + ("x" if token[-1] != "x" else "y")
        self.assertFalse(valid_pairing(self.path, bad_token))
        self.assertTrue(valid_pairing(self.path, token))
        self.assertFalse(valid_pairing(self.path, token))

    def test_expired_pairing_fails(self):
        created = create_pairing(self.path)
        token = created["token"]
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["created_at"] = "2000-01-01T00:00:00+00:00"
        self.path.write_text(json.dumps(data) + "\n", encoding="utf-8")
        self.assertFalse(valid_pairing(self.path, token))

    def test_rotation_invalidates_previous(self):
        old = create_pairing(self.path)["token"]
        new = create_pairing(self.path)["token"]
        self.assertNotEqual(old, new)
        self.assertFalse(valid_pairing(self.path, old))
        self.assertTrue(valid_pairing(self.path, new))

    def test_corruption_fails_closed(self):
        self.path.write_text("{not json")
        self.assertFalse(valid_pairing(self.path, "a"*64))
        self.assertFalse(pairing_status(self.path)["configured"])


if __name__ == "__main__":
    unittest.main()
