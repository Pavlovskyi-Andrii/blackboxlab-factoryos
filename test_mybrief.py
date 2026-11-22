"""T-615 MyBrief pilot (#188): fixture honesty, topic filtering, opt-in feedback, caps, withdraw and route auth.
Offline: the real ASGI app is called in-process; no network, no provider."""
import asyncio
import copy
import json
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-mybrief-"))
import app as factory  # noqa: E402
import mybrief  # noqa: E402
from mvp_factory import MvpRegistry  # noqa: E402

AUTH_ON = "auth-enabled-for-tests"
CATALOG = mybrief.load_catalog()


def call(method, path, *, query="", cookie=None, body=b"{}", client="203.0.113.7"):
    headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
    if cookie:
        headers.append((b"cookie", f"{factory.COOKIE_NAME}={cookie}".encode()))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode(), "query_string": query.encode(), "headers": headers,
             "server": ("testserver", 80), "client": (client, 50000), "root_path": ""}
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
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        return start["status"], json.loads(raw or b"{}")
    except ValueError:
        return start["status"], {}


class CatalogTest(unittest.TestCase):
    def test_shipped_fixture_is_valid_and_honest(self):
        self.assertEqual(mybrief.validate_catalog(CATALOG), [])
        self.assertEqual(CATALOG["kind"], "demo_fixture")
        self.assertGreaterEqual(len(CATALOG["professions"]), 3)
        for prof in CATALOG["professions"]:
            self.assertGreaterEqual(len(prof["items"]), 3, prof["id"])
            for item in prof["items"]:
                src = item["source"]
                self.assertTrue(src["url"].startswith("https://"), item["id"])
                self.assertLessEqual(src["date"], CATALOG["generated_at"])
                self.assertEqual(src["verified_via"], "surfer_web_read")

    def test_validation_refuses_unsourced_future_or_unverified_items(self):
        def broken(mutate):
            cat = copy.deepcopy(CATALOG)
            mutate(cat["professions"][0]["items"][0])
            return mybrief.validate_catalog(cat)

        self.assertTrue(broken(lambda i: i["source"].update(url="http://example.com/x")))
        self.assertTrue(broken(lambda i: i["source"].update(url="")))
        self.assertTrue(broken(lambda i: i["source"].update(date="2099-01-01")))
        self.assertTrue(broken(lambda i: i["source"].update(verified_via="memory")))
        self.assertTrue(broken(lambda i: i.update(topic="nope")))
        self.assertTrue(broken(lambda i: i.update(summary="")))
        live = copy.deepcopy(CATALOG)
        live["kind"] = "live"
        self.assertTrue(mybrief.validate_catalog(live))
        two = copy.deepcopy(CATALOG)
        two["professions"] = two["professions"][:2]
        self.assertTrue(mybrief.validate_catalog(two))

    def test_compose_filters_topics_and_dedupes_sources(self):
        brief = mybrief.compose(CATALOG, "accountant", ["making-tax-digital"])
        self.assertEqual({i["topic"] for i in brief["items"]}, {"making-tax-digital"})
        full = mybrief.compose(CATALOG, "accountant", [])
        self.assertEqual(len(full["items"]), len(CATALOG["professions"][2]["items"]))
        self.assertEqual(len({s["url"] for s in full["sources"]}), len(full["sources"]))
        self.assertIn("Not live news", full["note"])
        with self.assertRaises(mybrief.MyBriefError):
            mybrief.compose(CATALOG, "astronaut", [])
        with self.assertRaises(mybrief.MyBriefError):
            mybrief.compose(CATALOG, "teacher", ["models"])


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.t = [1_800_000_000.0]
        self.store = mybrief.FeedbackStore(Path(self.dir.name) / "fb.json", CATALOG, clock=lambda: self.t[0])

    def tearDown(self):
        self.dir.cleanup()

    def code(self, body, client="c1"):
        with self.assertRaises(mybrief.MyBriefError) as ctx:
            self.store.submit(body, client)
        return ctx.exception.code

    def ok(self, **kw):
        return dict({"consent": True, "profession": "teacher", "topics": ["curriculum"], "rating": 4}, **kw)

    def test_nothing_is_stored_without_explicit_consent(self):
        for consent in (None, False, "true", 1, "yes"):
            self.assertEqual(self.code(self.ok(consent=consent)), "consent_required")
        self.assertFalse((Path(self.dir.name) / "fb.json").exists())

    def test_input_is_validated_and_personal_data_redacted(self):
        self.assertEqual(self.code(self.ok(rating=0)), "bad_rating")
        self.assertEqual(self.code(self.ok(rating=True)), "bad_rating")
        self.assertEqual(self.code(self.ok(topics=["models"])), "unknown_topic")
        self.assertEqual(self.code(self.ok(profession="pilot")), "unknown_profession")
        receipt = self.store.submit(self.ok(comment="mail me jane.doe@example.com or +44 20 7946 0958 <b>", name="Jane",
                                            email="jane@example.com", would_read_weekly=True), "198.51.100.77")
        raw = (Path(self.dir.name) / "fb.json").read_text()
        for leaked in ("jane", "Jane", "7946", "<b>", "198.51.100.77", receipt["withdraw_token"]):
            self.assertNotIn(leaked, raw)
        entry = json.loads(raw)["entries"][0]
        self.assertEqual(set(entry), {"id", "at", "profession", "topics", "rating", "would_read_weekly", "comment",
                                      "consent", "withdraw_hash"})
        self.assertIn("[email removed]", entry["comment"])
        self.assertIn("[number removed]", entry["comment"])

    def test_daily_caps_per_client_and_global(self):
        for _ in range(mybrief.PER_CLIENT_DAILY):
            self.store.submit(self.ok(), "c1")
        self.assertEqual(self.code(self.ok(), "c1"), "daily_limit")
        self.store.submit(self.ok(), "c2")          # another visitor is not blocked
        self.t[0] += 86400                          # next UTC day: the per-client counter resets
        self.store.submit(self.ok(), "c1")
        with patch.object(mybrief, "GLOBAL_DAILY", 1):
            self.assertEqual(self.code(self.ok(), "c3"), "daily_limit")

    def test_withdraw_needs_the_token_and_deletes(self):
        receipt = self.store.submit(self.ok(), "c1")
        with self.assertRaises(mybrief.MyBriefError):
            self.store.withdraw(receipt["id"], "wrong")
        self.assertEqual(self.store.summary()["total"], 1)
        self.assertTrue(self.store.withdraw(receipt["id"], receipt["withdraw_token"])["withdrawn"])
        self.assertEqual(self.store.summary()["total"], 0)

    def test_summary_aggregates_without_withdraw_hashes(self):
        self.store.submit(self.ok(rating=5, would_read_weekly=True), "c1")
        self.store.submit(self.ok(rating=3, would_read_weekly=False), "c2")
        s = self.store.summary()
        self.assertEqual(s["by_profession"]["teacher"]["avg_rating"], 4.0)
        self.assertEqual((s["by_profession"]["teacher"]["weekly_yes"], s["by_profession"]["teacher"]["weekly_no"]), (1, 1))
        self.assertNotIn("withdraw_hash", json.dumps(s))


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.p = patch.object(factory, "FACTORY_PASSWORD", AUTH_ON)
        self.p.start()
        self.owner = factory.session_token(factory.FACTORY_USER)
        self.viewer = factory._role_session_token("viewer", "guest")

    def tearDown(self):
        self.p.stop()

    def test_public_demo_works_signed_out(self):
        status, cat = call("GET", "/api/mybrief/public/catalog")
        self.assertEqual(status, 200)
        self.assertEqual(len(cat["professions"]), 3)
        self.assertNotIn("headline", json.dumps(cat))                     # the picker gets counts, not item text
        status, brief = call("GET", "/api/mybrief/public/brief", query="profession=software-developer&topics=models")
        self.assertEqual(status, 200)
        self.assertTrue(brief["items"])
        self.assertEqual({i["topic"] for i in brief["items"]}, {"models"})
        self.assertEqual(call("GET", "/api/mybrief/public/brief", query="profession=x")[0], 404)
        self.assertEqual(call("GET", "/static/mybrief/index.html")[0], 200)

    def test_feedback_route_requires_consent_and_can_be_withdrawn(self):
        body = {"profession": "accountant", "topics": ["tax-law"], "rating": 5}
        status, out = call("POST", "/api/mybrief/public/feedback", body=json.dumps(body).encode(), client="198.51.100.1")
        self.assertEqual((status, out.get("detail")), (400, "consent_required"))
        status, out = call("POST", "/api/mybrief/public/feedback", body=json.dumps(dict(body, consent=True)).encode(),
                           client="198.51.100.1")
        self.assertEqual(status, 200)
        status, _ = call("POST", f"/api/mybrief/public/feedback/{out['id']}/withdraw",
                         body=json.dumps({"token": out["withdraw_token"]}).encode())
        self.assertEqual(status, 200)

    def test_summary_is_signed_in_owner_or_member_only(self):
        self.assertEqual(call("GET", "/api/mybrief/feedback")[0], 401)
        self.assertEqual(call("GET", "/api/mybrief/feedback", cookie=self.viewer)[0], 403)
        status, out = call("GET", "/api/mybrief/feedback", cookie=self.owner)
        self.assertEqual((status, out["project"]), (200, "mybrief-pro"))

    def test_public_prefix_does_not_leak_neighbours(self):
        self.assertEqual(call("GET", "/api/mybrief/publicX")[0], 401)
        self.assertEqual(call("GET", "/api/mybrief/feedback-export")[0], 401)


class RegistryLinkTest(unittest.TestCase):
    def test_pilot_prototype_is_linked_without_moving_the_stage(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "mvp.json"
            reg = MvpRegistry(path, clock=lambda: 1_800_000_000.0)
            reg.snapshot()
            data = json.loads(path.read_text())
            self.assertEqual(data["projects"]["mybrief-pro"]["prototype"], mybrief.PAGE)
            data["projects"]["mybrief-pro"]["prototype"] = ""          # an older registry, seeded before T-615
            path.write_text(json.dumps(data))
            snap = {p["id"]: p for p in reg.snapshot()["projects"]}
            self.assertEqual(snap["mybrief-pro"]["prototype"], mybrief.PAGE)
            self.assertEqual(snap["mybrief-pro"]["stage"], "idea")
            self.assertEqual(len([e for e in snap["mybrief-pro"]["history"]]), 1)

    def test_page_script_uses_only_public_api_and_has_consent_gate(self):
        html = (Path(__file__).parent / "static" / "mybrief" / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count("<script>"), 1)
        script = html.split("<script>", 1)[1].split("</script>", 1)[0]
        self.assertEqual(set(re.findall(r"/api/[a-z/-]+", script)), {"/api/mybrief/public/"})
        self.assertIn('id="send" type="submit" disabled', html)
        self.assertIn("consent: true", script)
        self.assertNotIn("innerHTML", script)


if __name__ == "__main__":
    unittest.main()
