"""R-0110 OLX publish preflight: category rules, duplicate readback, owner acknowledgement, read-only advert status.
Offline: fake HTTP, in-memory vault, handlers called directly (no TestClient: CI has no httpx)."""
import io
import json
import os
import pathlib
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-olx-pre-"))

from fastapi import FastAPI, HTTPException  # noqa: E402

import olx_preflight as pf  # noqa: E402
import olx_publisher as op  # noqa: E402
from oauth_framework import MemoryTokenVault, OAuthFlow, TokenSet  # noqa: E402
from test_olx_publisher import ENV, FakeHttp, call  # noqa: E402

SAMSUNG = "942142458"                                        # the owner's original advert: read, never changed
ADVERT = {"title": "Смартфон Samsung Galaxy S21 128 ГБ",
          "description": "Продаю смартфон Samsung Galaxy S21, 128 ГБ пам'яті, у гарному стані. Батарея тримає день, "
                         "екран без подряпин, повний комплект із коробкою.",
          "category_id": "1535", "advertiser_type": "private", "contact": {"name": "Андрій"},
          "location": {"city_id": 268}, "images": ["https://cdn.example.com/s21.jpg"],
          "price": {"value": "9000"}, "attributes": [{"code": "state", "value": "used"}]}
CATEGORY = (200, {"data": {"id": 1535, "name": "Мобільні телефони", "is_leaf": True, "photos_limit": 8}})
ATTRS = (200, {"data": [{"code": "state", "label": "Стан", "validation": {"required": True},
                         "values": [{"code": "used", "label": "Вживане"}, {"code": "new", "label": "Нове"}]},
                        {"code": "price", "validation": {"required": True}},
                        {"code": "color", "validation": {"required": False}, "values": []}]})
ORIGINAL = {"id": int(SAMSUNG), "status": "active", "url": "https://www.olx.ua/d/uk/942142458/",
            "title": "Смартфон Samsung Galaxy S21, 128 ГБ!", "category_id": 1535, "external_id": None}
OTHER = {"id": 5, "status": "active", "url": "https://www.olx.ua/d/5.html", "title": "Інший товар",
         "category_id": 1535}


class RulesTest(unittest.TestCase):
    def test_presence_reports_names_only(self):
        env = {"FACTORY_OAUTH_OLX_CLIENT_ID": "value-cid", "FACTORY_OAUTH_OLX_CLIENT_SECRET": " ",
               "FACTORY_VAULT_KEY": "value-vault"}
        out = pf.presence(env)
        self.assertEqual(out["FACTORY_OAUTH_OLX_CLIENT_ID"], "present")
        self.assertEqual(out["FACTORY_OAUTH_OLX_CLIENT_SECRET"], "missing")        # blank counts as missing
        self.assertEqual(out["FACTORY_OLX_ENABLED"], "missing")
        self.assertNotIn("value-", json.dumps(out))
        buf = io.StringIO()
        with mock.patch.dict(os.environ, env), redirect_stdout(buf):
            import runpy
            runpy.run_module("olx_preflight", run_name="__main__")
        self.assertIn('"FACTORY_VAULT_KEY": "present"', buf.getvalue())
        self.assertNotIn("value-", buf.getvalue())

    def test_category_rules_come_from_the_api(self):
        advert = op.clean_advert({**ADVERT, "images": ["https://cdn.example.com/%d.jpg" % i for i in range(3)],
                                  "attributes": [{"code": "state", "value": "broken"}, {"code": "ghost", "value": "x"}]})
        http = FakeHttp((200, {"id": 1535, "is_leaf": False, "photos_limit": 2}), ATTRS)
        problems = pf.category_problems(http, "AT", advert)
        self.assertEqual(problems, ["olx_category_not_leaf", "olx_photos_over_limit_2", "olx_attribute_value:state",
                                    "olx_attribute_unknown:ghost"])
        self.assertEqual([c[1].rsplit("/api/partner", 1)[1] for c in http.calls],
                         ["/categories/1535", "/categories/1535/attributes"])
        self.assertTrue(all(c[0] == "GET" and "Content-Type" not in c[2] and c[2]["Version"] == "2.0"
                            for c in http.calls))
        missing = op.clean_advert({**ADVERT, "attributes": []})
        self.assertEqual(pf.category_problems(FakeHttp(CATEGORY, ATTRS), "AT", missing),
                         ["olx_attribute_missing:state"])          # `price` is the advert's price object
        self.assertEqual(pf.category_problems(FakeHttp(CATEGORY, ATTRS), "AT", op.clean_advert(ADVERT)), [])

    def test_title_key_and_paging(self):
        self.assertEqual(pf.title_key("Смартфон Samsung Galaxy S21, 128 ГБ!"), pf.title_key("смартфон samsung galaxy s21 128 гб"))
        page = [{**OTHER, "id": i} for i in range(pf.PAGE_LIMIT)]
        http = FakeHttp((200, {"data": page}), (200, {"data": [ORIGINAL]}))
        rows, complete = pf.own_adverts(http, "AT")
        self.assertEqual((len(rows), complete), (pf.PAGE_LIMIT + 1, True))
        self.assertTrue(http.calls[1][1].endswith("/adverts?offset=50&limit=50"))
        rows, complete = pf.own_adverts(FakeHttp((200, {"data": [{"id": 9, "status": "active"}]})), "AT")
        self.assertFalse(complete)                                  # no title → cannot rule out a duplicate


class RoutesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.vault = MemoryTokenVault()
        self.http = FakeHttp()
        self.flow = OAuthFlow("https://factory.test", lambda spec: os.environ.get(spec.client_id_env, ""), self.vault,
                              adapters={"olx": op.OlxOAuthAdapter(self.http)})
        self.env = {"FACTORY_OLX_ENABLED": "1"}
        self.store = op.AdvertStore(pathlib.Path(self.tmp.name))
        app = FastAPI()
        op.install_routes(app, store=self.store, flow=self.flow,
                          identity=lambda r: {"role": r.headers.get("x-role")}, workspace=lambda: "default",
                          env=self.env)
        self.ep = {(getattr(r, "path", ""), tuple(sorted(getattr(r, "methods", ())))): r.endpoint for r in app.routes}
        self.patch = mock.patch.dict(os.environ, ENV)
        self.patch.start()
        self.vault.put("default", "olx", TokenSet(access_token="AT", refresh_token="RT", account_id="olx:user:7",
                                                  account_label="Andrii"))

    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()

    def route(self, path, *args, method="POST", **kw):
        return call(self.ep[(path, (method,))], *args, **kw)

    def approved(self, advert=ADVERT):
        d = self.route("/api/factory/olx/drafts", body={"advert": advert})["draft"]
        return self.route("/api/factory/olx/drafts/{draft_id}/approve", d["id"])["draft"]

    def preflight(self, draft_id, *adverts):
        self.http.answers += [(200, {"access_token": "AT", "refresh_token": "RT"}), CATEGORY, ATTRS,
                              (200, {"data": list(adverts)})]
        return self.route("/api/factory/olx/drafts/{draft_id}/preflight", draft_id)

    def publish(self, draft_id):
        return self.route("/api/factory/olx/drafts/{draft_id}/publish", draft_id)

    def posts(self):
        return [c for c in self.http.calls if c[0] != "GET" and not c[1].endswith("/oauth/token")]

    def test_routes_are_owner_only(self):
        for path, method, args in (("/api/factory/olx/drafts/{draft_id}/preflight", "POST", ("olx_000000000000",)),
                                   ("/api/factory/olx/drafts/{draft_id}/preflight/ack", "POST", ("olx_000000000000",)),
                                   ("/api/factory/olx/adverts/{advert_id}", "GET", (SAMSUNG,))):
            with self.assertRaises(HTTPException) as err:
                self.route(path, *args, method=method, role="member", body={"confirm": True})
            self.assertEqual(err.exception.status_code, 403)
        self.assertEqual(self.http.calls, [])

    def test_publish_requires_a_preflight_for_this_exact_advert(self):
        d = self.approved()
        self.http.answers.append((200, {"access_token": "AT", "refresh_token": "RT"}))
        with self.assertRaises(HTTPException) as err:
            self.publish(d["id"])
        self.assertEqual(err.exception.detail, "olx_preflight_required")
        out = self.preflight(d["id"], OTHER)
        self.assertEqual((out["needs_ack"], out["draft"]["preflight"]["problems"]), ([], []))
        self.assertEqual(self.posts(), [])                          # the preflight is read-only
        self.http.answers += [(200, {"access_token": "AT", "refresh_token": "RT"}),
                              (200, {"data": {"id": 77, "status": "new", "url": "https://www.olx.ua/d/77.html"}})]
        self.assertEqual(self.publish(d["id"])["draft"]["result"]["advert_id"], "77")
        self.assertEqual(len(self.posts()), 1)
        # An edit drops approval and preflight; a re-approval alone is not enough.
        d2 = self.approved()
        self.preflight(d2["id"])
        self.route("/api/factory/olx/drafts/{draft_id}/edit", d2["id"],
                   body={"advert": {**ADVERT, "title": "Смартфон Samsung Galaxy S21 256 ГБ"}})
        self.assertIsNone(self.store.get(d2["id"])["preflight"])
        self.route("/api/factory/olx/drafts/{draft_id}/approve", d2["id"])
        self.http.answers.append((200, {"access_token": "AT", "refresh_token": "RT"}))
        with self.assertRaises(HTTPException) as err:
            self.publish(d2["id"])
        self.assertEqual(err.exception.detail, "olx_preflight_required")
        self.assertEqual(len(self.posts()), 1)

    def test_duplicate_of_the_original_needs_exact_owner_ack_and_original_is_untouched(self):
        d = self.approved()
        out = self.preflight(d["id"], ORIGINAL, OTHER)
        self.assertEqual(out["needs_ack"], [SAMSUNG])
        self.assertEqual(out["draft"]["preflight"]["duplicates"][0]["url"], "https://www.olx.ua/d/uk/942142458/")
        self.assertNotIn("title", json.dumps(out["draft"]["preflight"]))   # other adverts' text is not stored
        self.http.answers.append((200, {"access_token": "AT", "refresh_token": "RT"}))
        with self.assertRaises(HTTPException) as err:
            self.publish(d["id"])
        self.assertEqual(err.exception.detail, "olx_duplicate_needs_ack")
        for bad in ({"advert_ids": [SAMSUNG]}, {"confirm": True, "advert_ids": []},
                    {"confirm": True, "advert_ids": [SAMSUNG, "5"]}):
            with self.assertRaises(HTTPException):
                self.route("/api/factory/olx/drafts/{draft_id}/preflight/ack", d["id"], body=bad)
        acked = self.route("/api/factory/olx/drafts/{draft_id}/preflight/ack", d["id"],
                           body={"confirm": True, "advert_ids": [SAMSUNG]})
        self.assertEqual(acked["draft"]["preflight"]["ack"], [SAMSUNG])
        self.http.answers += [(200, {"access_token": "AT", "refresh_token": "RT"}),
                              (200, {"data": {"id": 78, "status": "new"}})]
        self.assertEqual(self.publish(d["id"])["draft"]["status"], "published")
        writes = self.posts()
        self.assertEqual([(m, u.rsplit("/api/partner", 1)[1]) for m, u, _, _ in writes], [("POST", "/adverts")])
        self.assertEqual(json.loads(writes[0][3])["external_id"], d["id"])
        self.assertFalse(any(SAMSUNG in c[1] for c in self.http.calls))  # the original is not even addressed

    def test_problems_stale_account_and_draft_already_on_olx_block(self):
        d = self.approved({**ADVERT, "attributes": []})
        out = self.preflight(d["id"])
        self.assertEqual(out["draft"]["preflight"]["problems"], ["olx_attribute_missing:state"])
        self.http.answers.append((200, {"access_token": "AT", "refresh_token": "RT"}))
        with self.assertRaises(HTTPException) as err:
            self.publish(d["id"])
        self.assertEqual(err.exception.detail, "olx_preflight_problems")
        d2 = self.approved()
        out = self.preflight(d2["id"], {**OTHER, "id": 90, "external_id": d2["id"]})
        self.assertIn("olx_draft_already_on_olx_reconcile", out["draft"]["preflight"]["problems"])
        d3 = self.approved()
        self.preflight(d3["id"])
        draft = self.store.get(d3["id"])
        with self.assertRaises(HTTPException) as err:
            pf.check(draft, "olx:user:7", now=draft["preflight"]["checked_at"] + pf.PREFLIGHT_MAX_AGE + 1)
        self.assertEqual(err.exception.detail, "olx_preflight_stale")
        with self.assertRaises(HTTPException) as err:
            pf.check(draft, "olx:user:8")
        self.assertEqual(err.exception.detail, "olx_preflight_required")
        pf.check(draft, "olx:user:7")
        self.assertEqual(self.posts(), [])

    def test_incomplete_readback_needs_the_incomplete_marker(self):
        d = self.approved()
        out = self.preflight(d["id"], {"id": 9, "status": "active"})
        self.assertEqual(out["needs_ack"], ["incomplete"])
        self.route("/api/factory/olx/drafts/{draft_id}/preflight/ack", d["id"],
                   body={"confirm": True, "advert_ids": ["incomplete"]})
        pf.check(self.store.get(d["id"]), "olx:user:7")

    def test_readback_of_an_existing_advert_and_rate_limit(self):
        self.http.answers += [(200, {"access_token": "AT", "refresh_token": "RT"}),
                              (200, {"data": dict(ORIGINAL)})]
        out = self.route("/api/factory/olx/adverts/{advert_id}", SAMSUNG, method="GET")
        self.assertEqual(out["advert"], {"advert_id": SAMSUNG, "olx_status": "active",
                                         "url": "https://www.olx.ua/d/uk/942142458/", "valid_to": ""})
        self.assertEqual(self.http.calls[-1][0], "GET")
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/adverts/{advert_id}", "../users/me", method="GET")
        self.assertEqual(err.exception.status_code, 400)
        d = self.approved()
        self.http.answers += [(200, {"access_token": "AT", "refresh_token": "RT"})]
        self.http.answers.append(lambda: (429, b""))
        with self.assertRaises(HTTPException) as err:
            self.route("/api/factory/olx/drafts/{draft_id}/preflight", d["id"])
        self.assertEqual((err.exception.status_code, err.exception.detail), (429, "olx_rate_limited"))
        self.assertEqual(err.exception.headers, {"Retry-After": "60"})
        self.assertIsNone(self.store.get(d["id"]).get("preflight"))
        stored = pathlib.Path(self.tmp.name, "olx_adverts.json").read_text(encoding="utf-8")
        for secret in ('"AT"', '"RT"', "csecret"):
            self.assertNotIn(secret, stored)


if __name__ == "__main__":
    unittest.main()
