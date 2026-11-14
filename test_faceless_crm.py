"""Faceless Models CRM (#359): offline state, validation, owner-only access."""
import asyncio
import json
import os
import stat
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
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

    def test_invalid_nested_records_are_rejected_without_mutation(self):
        item = self.store.create({"alias": "Synthetic Demo"})
        good = json.loads(self.path.read_text(encoding="utf-8"))
        malformed = []
        bad = json.loads(json.dumps(good))
        bad["models"][item["id"]] = {}
        malformed.append(bad)
        bad = json.loads(json.dumps(good))
        bad["models"][item["id"]]["tasks"] = [{"id": "t1", "done": "yes"}]
        malformed.append(bad)
        bad = json.loads(json.dumps(good))
        bad["models"][item["id"]]["tasks"] = {}
        malformed.append(bad)
        bad = json.loads(json.dumps(good))
        bad["events"] = [{"action": "created"}]
        malformed.append(bad)
        for invalid in malformed:
            text = json.dumps(invalid, ensure_ascii=False)
            self.path.write_text(text, encoding="utf-8")
            for check in (self.store.snapshot,
                          lambda: self.store.set_task(item["id"], "x", True)):
                with self.assertRaises(CrmError) as exc:
                    check()
                self.assertEqual(exc.exception.code, "crm_unreadable")
                self.assertEqual(exc.exception.status, 503)
            self.assertEqual(text, self.path.read_text(encoding="utf-8"))

    def test_save_sync_order_and_failed_write_does_not_replace_data(self):
        actual_fsync = os.fsync
        actual_replace = os.replace
        calls = []

        def observe_sync(fd):
            calls.append("sync_dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "sync_file")
            actual_fsync(fd)

        def observe_replace(src, dst):
            calls.append("replace")
            actual_replace(src, dst)

        with patch("faceless_crm.os.fsync", side_effect=observe_sync):
            with patch("faceless_crm.os.replace", side_effect=observe_replace):
                model = self.store.create({"alias": "Stable Test"})
        self.assertEqual(calls, ["sync_file", "replace", "sync_dir"])
        saved = self.path.read_bytes()
        with patch("faceless_crm.os.replace", side_effect=OSError("simulated rename failure")):
            with self.assertRaises(CrmError) as exc:
                self.store.update(model["id"], {"stage": "research"})
        self.assertEqual(exc.exception.code, "crm_write_failed")
        self.assertEqual(self.path.read_bytes(), saved)
        with patch("faceless_crm.os.fsync", side_effect=OSError("simulated sync failure")):
            with self.assertRaises(CrmError) as exc:
                self.store.update(model["id"], {"stage": "research"})
        self.assertEqual(exc.exception.code, "crm_write_failed")
        self.assertEqual(self.path.read_bytes(), saved)

    def test_create_rejects_silently_dropped_fields(self):
        with self.assertRaises(CrmError) as exc:
            self.store.create({"alias": "Demo", "notes": "not accepted during creation"})
        self.assertEqual(exc.exception.code, "bad_fields")
        self.assertEqual(self.store.snapshot()["models"], [])

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


    def test_separate_mvp_concept_intake_is_non_destructive(self):
        from mvp_factory import MvpRegistry
        from faceless_crm import register_crm_mvp_project_once
        reg = MvpRegistry(Path(self.tmp.name) / "mvp.json")
        marker = Path(self.tmp.name) / "crm-intake.marker"
        self.assertTrue(register_crm_mvp_project_once(reg, marker))
        initial = reg.snapshot()["projects"]
        self.assertEqual(len([p for p in initial if p.get("issue") == 359]), 1)
        self.assertFalse(register_crm_mvp_project_once(reg, marker))
        marker.unlink()
        self.assertFalse(register_crm_mvp_project_once(reg, marker))
        self.assertEqual(len([p for p in reg.snapshot()["projects"] if p.get("issue") == 359]), 1)
        # Occupied canonical ID cannot overwrite unrelated owner data.
        other = MvpRegistry(Path(self.tmp.name) / "collision.json")
        other.add_project("faceless-models-crm", "Unrelated owner's project", 999, actor_role="owner")
        alt_marker = Path(self.tmp.name) / "collision.marker"
        self.assertTrue(register_crm_mvp_project_once(other, alt_marker))
        projects = other.snapshot()["projects"]
        self.assertEqual(next(p for p in projects if p["id"] == "faceless-models-crm")["issue"], 999)
        crm = [p for p in projects if p.get("issue") == 359]
        self.assertEqual(len(crm), 1)
        self.assertNotEqual(crm[0]["id"], "faceless-models-crm")
        self.assertEqual(crm[0]["stage"], "idea")
        self.assertFalse(crm[0]["approval"]["publish"])

    def test_concurrent_intake_creates_one_project_and_one_marker(self):
        from mvp_factory import MvpRegistry
        from faceless_crm import register_crm_mvp_project_once
        registry = MvpRegistry(Path(self.tmp.name) / "parallel.json")
        marker = Path(self.tmp.name) / "parallel.marker"
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: register_crm_mvp_project_once(registry, marker),
                                    range(8)))
        self.assertEqual(sum(results), 1)
        self.assertTrue(marker.exists())
        self.assertEqual(len([p for p in registry.snapshot()["projects"]
                              if p.get("issue") == 359]), 1)

if __name__ == "__main__":
    unittest.main()
