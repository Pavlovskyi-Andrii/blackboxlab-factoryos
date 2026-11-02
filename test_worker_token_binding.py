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


def asgi_post(path, bearer=None, body=b"{}", content_type="application/json"):
    """POST through the full ASGI app, auth middleware included. Returns (status, body)."""
    import asyncio
    headers = [(b"host", b"testserver"), (b"content-type", content_type.encode())]
    if bearer is not None:
        headers.append((b"authorization", ("Bearer " + bearer).encode("ascii")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": b"", "headers": headers,
             "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent, delivered = [], []

    async def receive():
        if not delivered:
            delivered.append(True)
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    return start["status"], b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


class OwnerDeskWorkerMiddlewareTest(unittest.TestCase):
    """2026-11-02: the middleware rejected worker calls to /api/factory/owner-desk/worker/* before the
    route's own worker check ran, so owner questions were never answered. Test through the real app."""

    def test_worker_token_reaches_owner_desk_worker_routes(self):
        with patch.object(factory, "FACTORY_PASSWORD", "set-so-auth-is-enforced"), \
             patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", "primary-worker-token"):
            status, body = asgi_post("/api/factory/owner-desk/worker/claim", "primary-worker-token", b'{"worker_id":"t"}')
            self.assertEqual(status, 200, body)
            status, body = asgi_post("/api/factory/owner-desk/worker/selftest", "primary-worker-token")
            self.assertEqual(status, 200, body)
            status, _ = asgi_post("/api/factory/owner-desk/worker/claim", None, b'{"worker_id":"t"}')
            self.assertEqual(status, 401)
            status, _ = asgi_post("/api/factory/owner-desk/worker/claim", "wrong", b'{"worker_id":"t"}')
            self.assertEqual(status, 401)
            # MyCast delivery passes the middleware with the worker token (409 here: no Telegram in CI),
            # and is rejected without it.
            boundary = "testboundary"
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"episode_id\"\r\n\r\nmycast-2026-11-03\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio\"; filename=\"a.mp3\"\r\n"
                    f"Content-Type: audio/mpeg\r\n\r\nID3\r\n--{boundary}--\r\n").encode()
            status, body_out = asgi_post("/api/factory/mycast/worker/deliver", "primary-worker-token", body,
                                         content_type="multipart/form-data; boundary=" + boundary)
            self.assertEqual(status, 409, body_out)
            status, _ = asgi_post("/api/factory/mycast/worker/deliver", None, body,
                                  content_type="multipart/form-data; boundary=" + boundary)
            self.assertEqual(status, 401)
            # The worker token never opens the owner's side of the desk.
            status, _ = asgi_post("/api/factory/owner-desk/questions", "primary-worker-token",
                                  b'{"task_id":"T-506","question":"x"}')
            self.assertEqual(status, 401)


if __name__ == "__main__":
    unittest.main()
