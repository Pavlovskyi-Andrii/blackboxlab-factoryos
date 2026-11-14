"""Faceless Models CRM (#359): offline state, validation, owner-only access."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from faceless_crm import FacelessCrm, CrmError, install_faceless_crm_routes


class Req:
    def __init__(self, body=None):
        self.body = body or {}
    async def json(self):
        return self.body


class FacelessCrmTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "crm.json"
        self.store = FacelessCrm(self.path)

    def tearDown(self):
        self.tmp.cleanup()

    def test_durable_models_and_tasks_without_fake_data(self):
        self.assertEqual(self.store.snapshot()["models"], [])
        item = self.store.create({"alias": "Synthetic Demo", "niche": "travel", "channel": "youtube"})
        self.assertEqual(item["stage"], "idea")
        task = self.store.add_task(item["id"], {"title": "Create non-explicit demo brief"})
        self.assertFalse(task["done"])
        self.store.set_task(item["id"], task["id"], True)
        self.store.update(item["id"], {"stage": "research", "notes": "Synthetic testing only"})
        state = FacelessCrm(self.path).snapshot()
        self.assertEqual(len(state["models"]), 1)
        self.assertEqual(state["models"][0]["stage"], "research")
        self.assertTrue(state["models"][0]["tasks"][0]["done"])
        self.assertTrue(all(e.get("model_id") == item["id"] for e in state["events"]))
        self.assertEqual(self.store.snapshot()["models"], state["models"])

    def test_validation_and_corruption_preserve_existing_content(self):
        item = self.store.create({"alias": "Demo Persona"})
        old = self.path.read_text(encoding="utf-8")
        for payload in ({"alias": "X"}, {"channel": "unknown"}, {"stage": "published"},
                        {"notes": 1}, {"bad": "field"}):
            with self.assertRaises(CrmError):
                self.store.update(item["id"], payload)
        with self.assertRaises(CrmError):
            self.store.add_task(item["id"], {"title": ""})
        with self.assertRaises(CrmError):
            self.store.set_task(item["id"], "missing", True)
        self.assertEqual(old, self.path.read_text(encoding="utf-8"))
        self.path.write_text("not json", encoding="utf-8")
        with self.assertRaises(CrmError) as exc:
            self.store.snapshot()
        self.assertEqual(exc.exception.status, 503)
        self.assertEqual(self.path.read_text(encoding="utf-8"), "not json")

    def test_owner_auth_gate_on_all_endpoints(self):
        app = FastAPI()
        role = {"current": None}
        install_faceless_crm_routes(app, self.store, lambda req: ({"role": role["current"]} if role["current"] else None))
        route_map = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if getattr(r, "methods", None)}
        get = route_map[("GET", "/api/faceless-crm")]
        create = route_map[("POST", "/api/faceless-crm/models")]
        update = route_map[("POST", "/api/faceless-crm/models/{model_id}")]
        add = route_map[("POST", "/api/faceless-crm/models/{model_id}/tasks")]
        toggle = route_map[("POST", "/api/faceless-crm/models/{model_id}/tasks/{task_id}")]
        self.assertEqual(get(Req()).status_code, 401)
        role["current"] = "viewer"
        self.assertEqual(get(Req()).status_code, 403)
        self.assertEqual(asyncio.run(create(Req({"alias": "TEST"}))).status_code, 403)
        self.assertEqual(asyncio.run(update("x", Req({"stage": "active"}))).status_code, 403)
        self.assertEqual(asyncio.run(add("x", Req({"title": "task"}))).status_code, 403)
        self.assertEqual(asyncio.run(toggle("x", "y", Req({"done": True}))).status_code, 403)
        role["current"] = "owner"
        model = asyncio.run(create(Req({"alias": "Demo"})))
        self.assertEqual(get(Req())["models"][0]["id"], model["id"])
        self.assertEqual(asyncio.run(update(model["id"], Req({"stage": "ready"})))["stage"], "ready")
        task = asyncio.run(add(model["id"], Req({"title": "Internal QA"})))
        self.assertTrue(asyncio.run(toggle(model["id"], task["id"], Req({"done": True})))["done"])
        self.assertEqual(asyncio.run(toggle(model["id"], task["id"], Req({"done": "true"}))).status_code, 400)


if __name__ == "__main__":
    unittest.main()
