"""Regression for independent, backwards-compatible worker token authorization."""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-token-test-"))

from starlette.requests import Request
import app as factory


def request(bearer=None):
    headers = [] if bearer is None else [(b"authorization", ("Bearer " + bearer).encode("ascii"))]
    return Request({"type": "http", "headers": headers})


class WorkerTokenTest(unittest.TestCase):
    def test_existing_token_remains_valid_when_ec2_token_added(self):
        with patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", "primary-keep-other-runners"), \
             patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN_EC2", "ec2-specific-secondary"):
            self.assertTrue(factory._claude_worker_authorized(request("primary-keep-other-runners")))
            self.assertTrue(factory._claude_worker_authorized(request("ec2-specific-secondary")))
            self.assertFalse(factory._claude_worker_authorized(request("wrong")))
            self.assertFalse(factory._claude_worker_authorized(request()))
            self.assertFalse(factory._claude_worker_authorized(request("primary-keep-other-runners " + "x")))

    def test_ec2_token_unset_fails_closed(self):
        with patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", "primary"), \
             patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN_EC2", ""):
            self.assertTrue(factory._claude_worker_authorized(request("primary")))
            self.assertFalse(factory._claude_worker_authorized(request("secondary")))


if __name__ == "__main__":
    unittest.main()
