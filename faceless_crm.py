"""Owner-only, non-explicit Faceless Models CRM for FactoryOS MVP Builder (#359).

This is a private workflow tracker: no adult-media storage, face processing, outreach,
publishing, payments, creator verification claims, or third-party API calls.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from fastapi import Request
from fastapi.responses import JSONResponse

STAGES = ("idea", "research", "onboarding", "ready", "active", "paused", "archived")
CHANNELS = ("none", "instagram", "tiktok", "youtube", "fanvue", "other")
MAX_MODELS = 100
MAX_TASKS = 100
MAX_EVENTS = 2000


class CrmError(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        raise CrmError("invalid_text")
    return re.sub(r"[\x00-\x1f<>]", " ", value).strip()[:limit]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class FacelessCrm:
    """Single-process JSON store, atomically saved on a persistent DATA_DIR volume."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def _read(self) -> dict:
        try:
            content = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"version": 1, "models": {}, "events": []}
        except (OSError, ValueError) as exc:
            raise CrmError("crm_unreadable", 503) from exc
        if not (isinstance(content, dict) and content.get("version") == 1
                and isinstance(content.get("models"), dict)
                and isinstance(content.get("events"), list)):
            raise CrmError("crm_unreadable", 503)
        return content

    def _write(self, content: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content["events"] = content["events"][-MAX_EVENTS:]
        name = ""
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".faceless-crm-", suffix=".tmp",
                                             delete=False) as file:
                name = file.name
                json.dump(content, file, ensure_ascii=False, indent=2)
            os.replace(name, self.path)
        finally:
            if name and os.path.exists(name):
                os.unlink(name)

    @staticmethod
    def _event(data: dict, model_id: str, action: str, detail: str) -> None:
        data["events"].append({"id": uuid.uuid4().hex[:16], "model_id": model_id,
                               "action": action, "detail": detail, "at": _now()})

    def snapshot(self) -> dict:
        with self.lock:
            data = self._read()
            models = sorted(data["models"].values(), key=lambda m: (m["created_at"], m["id"]), reverse=True)
            return {"models": models, "stages": list(STAGES), "channels": list(CHANNELS),
                    "events": data["events"][-80:][::-1],
                    "note": "Internal tracker only. No automated contact, publishing or real-content processing."}

    def create(self, body: dict) -> dict:
        alias = _text(body.get("alias", ""), 70)
        if len(alias) < 2:
            raise CrmError("alias_required")
        niche = _text(body.get("niche", ""), 80)
        channel = _text(body.get("channel", "none"), 24)
        if channel not in CHANNELS:
            raise CrmError("bad_channel")
        with self.lock:
            data = self._read()
            if len(data["models"]) >= MAX_MODELS:
                raise CrmError("model_limit", 409)
            model_id = uuid.uuid4().hex[:12]
            now = _now()
            model = {"id": model_id, "alias": alias, "niche": niche, "channel": channel,
                     "stage": "idea", "notes": "", "tasks": [], "created_at": now,
                     "updated_at": now}
            data["models"][model_id] = model
            self._event(data, model_id, "created", "Owner created a draft persona card")
            self._write(data)
            return model

    def update(self, model_id: str, body: dict) -> dict:
        allowed = {"alias", "niche", "channel", "stage", "notes"}
        if not body or set(body) - allowed:
            raise CrmError("bad_fields")
        updates = {}
        for field, value in body.items():
            updates[field] = _text(value, {"alias": 70, "niche": 80, "channel": 24,
                                           "stage": 32, "notes": 1000}[field])
        if "alias" in updates and len(updates["alias"]) < 2:
            raise CrmError("alias_required")
        if "channel" in updates and updates["channel"] not in CHANNELS:
            raise CrmError("bad_channel")
        if "stage" in updates and updates["stage"] not in STAGES:
            raise CrmError("bad_stage")
        with self.lock:
            data = self._read()
            model = data["models"].get(model_id)
            if not model:
                raise CrmError("not_found", 404)
            changed = [field for field, value in updates.items() if model.get(field) != value]
            if changed:
                model.update(updates)
                model["updated_at"] = _now()
                self._event(data, model_id, "updated", "Updated: " + ", ".join(sorted(changed)))
                self._write(data)
            return model

    def add_task(self, model_id: str, body: dict) -> dict:
        if set(body) != {"title"}:
            raise CrmError("bad_fields")
        title = _text(body.get("title"), 120)
        if not title:
            raise CrmError("title_required")
        with self.lock:
            data = self._read()
            model = data["models"].get(model_id)
            if not model:
                raise CrmError("not_found", 404)
            if len(model["tasks"]) >= MAX_TASKS:
                raise CrmError("task_limit", 409)
            task = {"id": uuid.uuid4().hex[:12], "title": title, "done": False, "created_at": _now()}
            model["tasks"].append(task)
            model["updated_at"] = _now()
            self._event(data, model_id, "task_added", "Added an internal checklist task")
            self._write(data)
            return task

    def set_task(self, model_id: str, task_id: str, done: bool) -> dict:
        if type(done) is not bool:
            raise CrmError("bad_done")
        with self.lock:
            data = self._read()
            model = data["models"].get(model_id)
            if not model:
                raise CrmError("not_found", 404)
            task = next((t for t in model["tasks"] if t["id"] == task_id), None)
            if not task:
                raise CrmError("task_not_found", 404)
            if task["done"] != done:
                task["done"] = done
                model["updated_at"] = _now()
                self._event(data, model_id, "task_done" if done else "task_reopened",
                            "Changed checklist completion; no external work was performed")
                self._write(data)
            return task


def install_faceless_crm_routes(app, store: FacelessCrm, identity_fn: Callable) -> None:
    """Only the actual FactoryOS owner can read or write the private CRM."""
    def _deny(request: Request):
        identity = identity_fn(request) or {}
        if not identity:
            return JSONResponse({"detail": "login_required"}, status_code=401)
        if identity.get("role") != "owner":
            return JSONResponse({"detail": "owner_only"}, status_code=403)
        return None

    def _result(fn):
        try:
            return fn()
        except CrmError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    async def _json(request: Request):
        try:
            body = await request.json()
        except (ValueError, TypeError):
            raise CrmError("bad_body")
        if not isinstance(body, dict):
            raise CrmError("bad_body")
        return body

    @app.get("/api/faceless-crm")
    def faceless_crm_list(request: Request):
        denial = _deny(request)
        return denial if denial is not None else _result(store.snapshot)

    @app.post("/api/faceless-crm/models")
    async def faceless_crm_create(request: Request):
        denial = _deny(request)
        if denial is not None:
            return denial
        try:
            return store.create(await _json(request))
        except CrmError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.post("/api/faceless-crm/models/{model_id}")
    async def faceless_crm_update(model_id: str, request: Request):
        denial = _deny(request)
        if denial is not None:
            return denial
        try:
            return store.update(model_id, await _json(request))
        except CrmError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.post("/api/faceless-crm/models/{model_id}/tasks")
    async def faceless_crm_add_task(model_id: str, request: Request):
        denial = _deny(request)
        if denial is not None:
            return denial
        try:
            return store.add_task(model_id, await _json(request))
        except CrmError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)

    @app.post("/api/faceless-crm/models/{model_id}/tasks/{task_id}")
    async def faceless_crm_set_task(model_id: str, task_id: str, request: Request):
        denial = _deny(request)
        if denial is not None:
            return denial
        try:
            body = await _json(request)
            if set(body) != {"done"}:
                raise CrmError("bad_fields")
            return store.set_task(model_id, task_id, body["done"])
        except CrmError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)
