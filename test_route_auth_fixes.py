"""#114 route audit fixes, through the real ASGI app (auth middleware included). No network, no production."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-routeauth-"))
import app as factory  # noqa: E402

AUTH_ON = "auth-enabled-for-tests"


def call(method, path, *, bearer=None, cookie=None, body=b"{}"):
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if bearer:
        headers.append((b"authorization", ("Bearer " + bearer).encode()))
    if cookie:
        headers.append((b"cookie", f"{factory.COOKIE_NAME}={cookie}".encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
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


class RouteAuthFixes(unittest.TestCase):
    def setUp(self):
        self.p = [patch.object(factory, "FACTORY_PASSWORD", AUTH_ON)]
        for p in self.p:
            p.start()
        self.owner = factory.session_token(factory.FACTORY_USER)
        self.viewer = factory._role_session_token("viewer", "guest")

    def tearDown(self):
        for p in self.p:
            p.stop()

    def test_a1_public_health_is_liveness_only(self):
        status, body = call("GET", "/health")
        self.assertEqual(status, 200)
        self.assertEqual(set(json.loads(body)), {"ok", "service", "version"})
        self.assertNotIn(b"real_pilot", body)
        status, body = call("GET", "/health", cookie=self.owner)
        self.assertIn("paid_verification", json.loads(body))                   # staff still see the details

    def test_c1_worker_posts_need_the_worker_token_not_a_session(self):
        hb = json.dumps({"task_id": "T-1", "status": "idle", "branch": "x"}).encode()
        self.assertEqual(call("POST", "/api/claude-worker/heartbeat", cookie=self.owner, body=hb)[0], 401)
        self.assertEqual(call("POST", "/api/operator-worker/heartbeat", cookie=self.owner,
                              body=json.dumps({"operator_id": "claude"}).encode())[0], 401)
        self.assertEqual(call("POST", "/api/local-booster/heartbeat", cookie=self.owner)[0], 401)
        with patch.object(factory, "FACTORY_CLAUDE_WORKER_TOKEN", "w-token"):
            self.assertEqual(call("POST", "/api/claude-worker/heartbeat", bearer="w-token", body=hb)[0], 200)
        self.assertEqual(call("GET", "/api/local-booster/status", cookie=self.owner)[0], 200)   # dashboard GETs stay

    def test_c2_media_job_callback_reaches_its_own_token_check(self):
        with patch.object(factory, "FACTORY_VIDEO_CALLBACK_TOKEN", "cb"):
            self.assertNotEqual(call("POST", "/api/media-jobs/abc123/callback", bearer="cb",
                                     body=json.dumps({"status": "done"}).encode())[0], 401)
            self.assertEqual(call("POST", "/api/media-jobs/abc123/callback", bearer="wrong")[0], 401)
        self.assertEqual(call("POST", "/api/media-jobs/abc123/callback", bearer="cb")[0], 401)       # unset: closed

    def test_c7_mycast_prefixes_do_not_leak(self):
        self.assertEqual(call("GET", "/api/mycast/accounts-admin")[0], 401)
        self.assertEqual(call("GET", "/api/mycast/voicesX")[0], 401)
        self.assertNotEqual(call("GET", "/api/mycast/demo/status")[0], 401)
        self.assertNotEqual(call("GET", "/api/mycast/voices")[0], 401)
        self.assertNotEqual(call("GET", "/api/mycast/account/config")[0], 401)

    def test_b1_viewer_get_on_a_cycle_does_not_sync(self):
        with patch.object(factory, "sync_factory_cycle", side_effect=AssertionError("GET must not sync")), \
             patch.object(factory, "get_factory_cycle", return_value={"id": "c1", "status": "draft"}):
            status, body = call("GET", "/api/factory-cycles/c1", cookie=self.viewer)
        self.assertEqual((status, json.loads(body)["id"]), (200, "c1"))

    def test_b2_viewer_get_on_media_never_archives(self):
        row = {"id": "a1", "kind": "video", "url": "https://finisher.example/tmp/x.mp4", "mime_type": "video/mp4"}
        with patch.object(factory, "_artifact_media_row", return_value=row), \
             patch.object(factory, "_artifact_archive_file", return_value=(None, None)), \
             patch.object(factory, "_is_ephemeral_finisher_url", return_value=True), \
             patch.object(factory, "_archive_media_artifact", side_effect=AssertionError("viewer must not archive")):
            status, _ = call("GET", "/api/artifacts/a1/media", cookie=self.viewer)
        self.assertNotEqual(status, 500)


    def test_launchpad_board_is_behind_the_session_and_writes_behind_the_role(self):
        # T-704 (Codex review of #432): through the real app and its auth middleware.
        base = "/api/mvp-factory/mycast/launchpad"
        idea = json.dumps({"type": "idea_card", "who": "w", "problem": "p", "where_noticed": ["own_experience"]}).encode()
        for method, path in (("GET", base), ("POST", base + "/artifacts"), ("POST", base + "/approvals"), ("POST", base + "/gates/G1")):
            status, body = call(method, path, body=idea)
            self.assertEqual(status, 401, (method, path))                      # signed out: no board data, no write
            self.assertNotIn(b"checks", body)
        status, body = call("GET", base, cookie=self.viewer)
        self.assertEqual(status, 200)                                          # a signed-in viewer may read
        # T-705: MyCast starts with the manual D1–D3 benchmark run (seed_benchmark at startup). Every count comes from
        # the stored records, and the checks after D1–D3 are still unknown: nothing is invented.
        board = json.loads(body)
        first = board["checks"][0]
        self.assertEqual(first["actual"], sum(1 for a in board["artifacts"]
                                              if a["check"] == first["id"] and not a["test"] and not a["synthetic"]))
        self.assertGreater(first["actual"], 0)
        self.assertEqual({c["actual"] for c in board["checks"][3:]}, {"unknown"})
        self.assertEqual(call("POST", base + "/artifacts", cookie=self.viewer, body=idea)[0], 403)   # and never write
        self.assertEqual(call("POST", base + "/approvals", cookie=self.viewer, body=b'{"artifact":"a-1","kind":"outreach"}')[0], 403)
        status, body = call("POST", base + "/artifacts", cookie=self.owner, body=idea)
        self.assertEqual((status, json.loads(body)["artifact"]["id"]), (200, f"a-{board['artifact_count'] + 1}"))   # the next id after the seeded records
        self.assertEqual(call("GET", "/api/mvp-factory/no-such-project/launchpad", cookie=self.owner)[0], 404)
        # The page itself is a public static file with no data in it; it opens the project named in the link.
        status, page = call("GET", "/static/mvp-factory/launchpad.html")
        self.assertEqual(status, 200)
        self.assertNotIn(b"own_experience", page)
        self.assertIn(b"get('project')||'mycast'", page)
        status, cards = call("GET", "/static/mvp-factory/index.html")
        self.assertIn(b"launchpad.html?project='+encodeURIComponent(p.id)", cards)


class StaticDirectoryIndexTest(unittest.TestCase):
    def test_directory_urls_serve_their_index_page(self):
        # Owner 2026-11-23: the T-700-H runbook link /static/linkedin/ answered 404.
        for name, marker in (("linkedin", b"FactoryOS \xc2\xb7 LinkedIn"), ("surfer", b"FactoryOS \xc2\xb7 Surfer"), ("olx", b"FactoryOS \xc2\xb7 OLX")):
            status, page = call("GET", f"/static/{name}/")
            self.assertEqual(status, 200, name)
            self.assertIn(marker, page)
            self.assertIn(b'<a href="/"', page)   # every owner page leads back to the dashboard
        self.assertEqual(call("GET", "/static/no-such-page/")[0], 404)


class BridgeTokenTest(unittest.TestCase):
    def test_c4_dedicated_bridge_token_replaces_the_mcp_token(self):
        class Req:
            def __init__(self, tok): self.headers = {"authorization": "Bearer " + tok}
        with patch.object(factory, "FACTORY_MCP_TOKEN", "mcp"), patch.dict(os.environ, {"FACTORY_TELEGRAM_BRIDGE_TOKEN": ""}):
            self.assertTrue(factory._telegram_bridge_authorized(Req("mcp")))           # unchanged until configured
        with patch.object(factory, "FACTORY_MCP_TOKEN", "mcp"), patch.dict(os.environ, {"FACTORY_TELEGRAM_BRIDGE_TOKEN": "bridge"}):
            self.assertFalse(factory._telegram_bridge_authorized(Req("mcp")))
            self.assertTrue(factory._telegram_bridge_authorized(Req("bridge")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
