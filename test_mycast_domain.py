"""mycast.pro (owner 2026-11-13): only MyCast on its own domain; FactoryOS stays on onrender.com."""
import asyncio
import os
import tempfile
import unittest

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-domain-"))
import app as factory  # noqa: E402


def get(path, host="mycast.pro", query=""):
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET", "scheme": "https",
             "path": path, "raw_path": path.encode(), "query_string": query.encode(),
             "headers": [(b"host", host.encode())], "server": (host, 443), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)
    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    return start["status"], headers, b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")


class MyCastDomainTest(unittest.TestCase):
    def test_root_and_unknown_paths_open_mycast(self):
        for path in ("/", "/uk", "/api/status", "/login", "/static/index.html"):
            status, headers, _ = get(path)
            self.assertEqual((status, headers.get("location")), (302, factory.MYCAST_PAGE), path)
        self.assertEqual(get("/", query="p=abc")[1]["location"], factory.MYCAST_PAGE + "?p=abc")

    def test_mycast_paths_are_served(self):
        self.assertEqual(get(factory.MYCAST_PAGE)[0], 200)
        for path in ("/privacy", "/terms"):
            status, _, body = get(path)
            self.assertEqual(status, 200)
            self.assertIn(b"calendar.readonly", get("/privacy")[2])
        self.assertEqual(get("/api/mycast/account/config")[0], 200)
        self.assertEqual(get("/health")[0], 200)

    def test_www_redirects_to_apex_and_factoryos_is_unchanged(self):
        status, headers, _ = get("/", host="www.mycast.pro")
        self.assertEqual((status, headers["location"]), (301, "https://mycast.pro" + factory.MYCAST_PAGE))
        self.assertEqual(get("/terms", host="www.mycast.pro")[1]["location"], "https://mycast.pro/terms")
        status, _, body = get("/", host="blackboxlab-factoryos.onrender.com")
        self.assertNotEqual(status, 302)                                   # dashboard (or its login) as before
        self.assertEqual(get("/privacy", host="blackboxlab-factoryos.onrender.com")[0], 200)


if __name__ == "__main__":
    unittest.main(verbosity=2)
