"""T-721 Surfer policy gate: what the action sessions of T-720 may do, decided on the server, fail closed.

Owner 2026-11-22: "сам, на разрешённых сайтах". The owner keeps an allowlist of sites with action classes; nothing is
on by default. Order of checks for every tool call:

1. ``FACTORY_SURFER_ACTIONS_ENABLED`` (owner-set in Render, off by default) and the owner's pause switch;
2. lane identity (per-lane MCP token, T-624); the shared token never gets here;
3. the allowlist: domain pattern + classes read / navigate / fill / submit / upload (+ an optional vault login);
4. per-day caps on sessions and steps.

The step-level review (payment, delete, security, messaging, publishing, leaving the allowlist → the owner confirms)
lives in ``browser_runner.action_policy`` and is called by ``surfer_actions``. This module also keeps the files the
owner approved for upload.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from fastapi import HTTPException, Request

from browser_runner import action_policy as policy

FLAG_ENV = "FACTORY_SURFER_ACTIONS_ENABLED"
SESSIONS_CAP_ENV, STEPS_CAP_ENV = "FACTORY_SURFER_ACTIONS_MAX_SESSIONS_PER_DAY", "FACTORY_SURFER_ACTIONS_MAX_STEPS_PER_DAY"
SESSIONS_CAP_DEFAULT, STEPS_CAP_DEFAULT = 40, 600
SESSIONS_CAP_MAX, STEPS_CAP_MAX = 500, 5000
MAX_ENTRIES = 40
LANES = ("claude", "chatgpt", "gemini")
ENTRY_ID_RE = re.compile(r"^al_[0-9a-f]{12}$")
UPLOAD_ID_RE = re.compile(r"^su_[0-9a-f]{12}$")
LOGIN_RE = re.compile(r"^([a-z0-9][a-z0-9_.-]{0,39})/([\w.@+ -]{1,80})$")
UPLOAD_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".txt", ".pdf", ".mp4", ".mov", ".csv"})
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOADS = 30

# The owner's first list (brief 2026-11-22). Shown on the page as suggestions; none is in the allowlist until the
# owner adds it himself, and he chooses the classes.
PRESETS = (
    {"pattern": "blackboxlab-factoryos.onrender.com", "classes": ["read", "navigate", "fill", "submit"],
     "note": "FactoryOS and its product pages"},
    {"pattern": "docs.google.com", "classes": ["read", "navigate", "fill", "submit"], "note": "Google Forms / Sheets"},
    {"pattern": "olx.ua", "classes": ["read", "navigate", "fill"], "note": "OLX cabinet"},
    {"pattern": "dashboard.render.com", "classes": ["read", "navigate"], "note": "Render dashboard"},
    {"pattern": "www.linkedin.com", "classes": ["read", "navigate"], "note": "LinkedIn Developers"},
    {"pattern": "github.com", "classes": ["read", "navigate"], "note": "GitHub settings"},
)


def flag_on(env: Mapping[str, str]) -> bool:
    return str(env.get(FLAG_ENV, "") or "").strip().lower() in ("1", "true", "yes", "on")


def _cap(env: Mapping[str, str], name: str, default: int, high: int) -> int:
    try:
        return max(1, min(int(str(env.get(name, "") or default)), high))
    except (TypeError, ValueError):
        return default


class NoVault:
    """No vault configured: no login can be bound, nothing is resolved."""

    def logins(self) -> List[str]:
        return []

    def secret(self, provider: str, account: str, kind: str) -> str:
        return ""

    def has_secret(self, provider: str, account: str) -> bool:
        return False

    def storage_state(self, provider: str, account: str) -> Optional[dict]:
        return None

    def save_storage_state(self, provider: str, account: str, state: dict) -> bool:
        return False


class PolicyGate:
    def __init__(self, data_dir: Path, *, env: Optional[Mapping[str, str]] = None, vault: Any = None,
                 clock: Callable[[], float] = time.time, loopback: bool = False):
        self.root = Path(data_dir) / "surfer_actions"
        self.path = self.root / "policy.json"
        self.upload_dir = self.root / "uploads"
        self.env = os.environ if env is None else env
        self.vault = vault or NoVault()
        self.clock, self.lock = clock, threading.RLock()
        self.loopback = loopback               # tests and the self-test only; never read from the environment

    # --- state file -------------------------------------------------------------------------------------------
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.setdefault("allow", [])
        data.setdefault("paused", False)
        data.setdefault("usage", {})
        data.setdefault("uploads", [])
        return data

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def _day(self) -> str:
        return time.strftime("%Y-%m-%d", time.gmtime(self.clock()))

    # --- what surfer_actions asks -----------------------------------------------------------------------------
    def caps(self) -> dict:
        return {"sessions": _cap(self.env, SESSIONS_CAP_ENV, SESSIONS_CAP_DEFAULT, SESSIONS_CAP_MAX),
                "steps": _cap(self.env, STEPS_CAP_ENV, STEPS_CAP_DEFAULT, STEPS_CAP_MAX)}

    def usage(self) -> dict:
        usage = self._load()["usage"]
        today = usage.get("day") == self._day()
        return {"day": self._day(), "sessions": int(usage.get("sessions") or 0) if today else 0,
                "steps": int(usage.get("steps") or 0) if today else 0}

    def status(self) -> dict:
        data = self._load()
        flag = flag_on(self.env)
        reason = ""
        if not flag:
            reason = f"Surfer actions are off: the owner sets {FLAG_ENV}=1 in Render"
        elif data["paused"]:
            reason = "Surfer actions are paused by the owner (the pause switch on the Surfer page)"
        return {"enabled": flag and not data["paused"], "flag": flag, "paused": bool(data["paused"]),
                "reason": reason, "caps": self.caps(), "usage": self.usage(),
                "sites_enabled": sum(1 for e in data["allow"] if e.get("enabled"))}

    def require(self, lane: str) -> None:
        status = self.status()
        if not status["enabled"]:
            raise HTTPException(503, status["reason"])
        if lane not in LANES:
            raise HTTPException(403, "Surfer actions need a lane MCP token")

    def allow(self) -> List[dict]:
        if not self.status()["enabled"]:
            return []
        return [{"pattern": e["pattern"], "classes": list(e.get("classes") or []), "enabled": True,
                 "login": e.get("login") or ""} for e in self._load()["allow"] if e.get("enabled")]

    def count(self, kind: str) -> None:
        key = "sessions" if kind == "session" else "steps"
        with self.lock:
            data = self._load()
            usage = data["usage"] if data["usage"].get("day") == self._day() else {"day": self._day()}
            used, cap = int(usage.get(key) or 0), self.caps()[key]
            if used >= cap:
                raise HTTPException(429, f"daily Surfer cap reached ({cap} {key} per UTC day); it resets at 00:00 UTC")
            usage[key] = used + 1
            data["usage"] = usage
            self._save(data)

    @staticmethod
    def _login(login: str) -> Optional[tuple]:
        found = LOGIN_RE.fullmatch(str(login or ""))
        return (found.group(1), found.group(2)) if found else None

    def _bound(self, login: str) -> bool:
        return any(e.get("enabled") and e.get("login") == login for e in self._load()["allow"])

    def secret(self, value_from: str) -> str:
        """The vault value for 'vault:site/account#kind', only for a login an enabled allowlist entry names."""
        ref = policy.VAULT_REF_RE.fullmatch(str(value_from or ""))
        if not ref or not self.status()["enabled"] or not self._bound(f"{ref.group(1)}/{ref.group(2)}"):
            return ""
        try:
            return str(self.vault.secret(ref.group(1), ref.group(2), ref.group(3)) or "")
        except Exception:
            return ""

    def has_login_secret(self, login: str) -> bool:
        parts = self._login(login)
        try:
            return bool(parts and self._bound(login) and self.vault.has_secret(*parts))
        except Exception:
            return False

    def storage_state(self, login: str) -> Optional[dict]:
        parts = self._login(login)
        if not parts or not self._bound(login) or not self.status()["enabled"]:
            return None
        try:
            state = self.vault.storage_state(*parts)
        except Exception:
            return None
        return state if isinstance(state, dict) else None

    def save_storage_state(self, login: str, state: dict) -> bool:
        parts = self._login(login)
        if not parts or not self._bound(login) or not isinstance(state, dict):
            return False
        return bool(self.vault.save_storage_state(parts[0], parts[1], state))

    # --- the owner's allowlist --------------------------------------------------------------------------------
    def entries(self) -> List[dict]:
        return [dict(e) for e in self._load()["allow"]]

    def logins(self) -> List[str]:
        try:
            return sorted({str(x) for x in self.vault.logins() if LOGIN_RE.fullmatch(str(x))})
        except Exception:
            return []

    def save_entry(self, body: dict) -> dict:
        pattern = policy.clean_pattern(body.get("pattern"))
        if not pattern:
            raise HTTPException(400, "pattern must be a site domain like olx.ua (it covers its subdomains); a shared "
                                     "suffix such as com.ua or onrender.com is not accepted")
        classes = policy.clean_classes(body.get("classes"))
        if "read" not in classes:
            classes = ["read"] + classes
        login = str(body.get("login") or "").strip()
        if login and (not LOGIN_RE.fullmatch(login) or login not in self.logins()):
            raise HTTPException(400, "login must be a saved vault login 'site/account' (Access vault)")
        note = " ".join(str(body.get("note") or "").split())[:120]
        with self.lock:
            data = self._load()
            entry_id = str(body.get("id") or "")
            entry = next((e for e in data["allow"] if e["id"] == entry_id), None) if entry_id else None
            if entry_id and entry is None:
                raise HTTPException(404, "unknown allowlist entry")
            if any(e["pattern"] == pattern and e is not entry for e in data["allow"]):
                raise HTTPException(409, "this site is already on the list")
            if entry is None:
                if len(data["allow"]) >= MAX_ENTRIES:
                    raise HTTPException(409, f"the allowlist holds at most {MAX_ENTRIES} sites")
                entry = {"id": "al_" + secrets.token_hex(6), "added": int(self.clock())}
                data["allow"].append(entry)
            entry.update(pattern=pattern, classes=classes, enabled=body.get("enabled") is True, login=login,
                         note=note, updated=int(self.clock()))
            self._save(data)
            return dict(entry)

    def remove_entry(self, entry_id: str) -> bool:
        with self.lock:
            data = self._load()
            keep = [e for e in data["allow"] if e["id"] != entry_id]
            if len(keep) == len(data["allow"]):
                return False
            data["allow"] = keep
            self._save(data)
            return True

    def set_paused(self, paused: bool) -> bool:
        with self.lock:
            data = self._load()
            data["paused"] = bool(paused)
            self._save(data)
            return data["paused"]

    # --- files the owner approved for upload ------------------------------------------------------------------
    def uploads(self) -> List[dict]:
        return [dict(u) for u in self._load()["uploads"]]

    def upload(self, asset_id: str) -> Optional[dict]:
        if not UPLOAD_ID_RE.fullmatch(str(asset_id or "")):
            return None
        row = next((u for u in self._load()["uploads"] if u["id"] == asset_id), None)
        if not row:
            return None
        path = self.upload_dir / (row["id"] + row["ext"])
        return {"id": row["id"], "name": row["name"], "path": str(path)} if path.is_file() else None

    def add_upload(self, name: str, raw: bytes) -> dict:
        clean = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(str(name or "")))[:80].strip(" .") or "file"
        ext = os.path.splitext(clean)[1].lower()
        if ext not in UPLOAD_TYPES:
            raise HTTPException(400, "file type not allowed: " + ", ".join(sorted(UPLOAD_TYPES)))
        if not raw or len(raw) > MAX_UPLOAD_BYTES:
            raise HTTPException(400, f"file must be 1 byte … {MAX_UPLOAD_BYTES // (1024 * 1024)} MB")
        with self.lock:
            data = self._load()
            if len(data["uploads"]) >= MAX_UPLOADS:
                raise HTTPException(409, f"at most {MAX_UPLOADS} approved files; remove one first")
            row = {"id": "su_" + secrets.token_hex(6), "name": clean, "ext": ext, "bytes": len(raw),
                   "added": int(self.clock())}
            self.upload_dir.mkdir(parents=True, exist_ok=True)
            (self.upload_dir / (row["id"] + ext)).write_bytes(raw)
            data["uploads"].append(row)
            self._save(data)
            return dict(row)

    def remove_upload(self, asset_id: str) -> bool:
        with self.lock:
            data = self._load()
            row = next((u for u in data["uploads"] if u["id"] == asset_id), None)
            if not row:
                return False
            (self.upload_dir / (row["id"] + row["ext"])).unlink(missing_ok=True)
            data["uploads"] = [u for u in data["uploads"] if u["id"] != asset_id]
            self._save(data)
            return True


def install_routes(app, *, gate: PolicyGate, store: Any, identity: Callable) -> None:
    """Owner-only: the gate's state, the allowlist, the pause switch, and the decision on a waiting step."""

    def owner(request: Request) -> None:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def state() -> dict:
        taken = {e["pattern"] for e in gate.entries()}
        return {"gate": gate.status(), "allow": gate.entries(), "logins": gate.logins(),
                "classes": list(policy.ACTION_CLASSES),
                "presets": [dict(p) for p in PRESETS if p["pattern"] not in taken]}

    @app.get("/api/factory/surfer/owner/policy")
    def surfer_policy(request: Request):
        owner(request)
        return state()

    @app.post("/api/factory/surfer/owner/policy/allow")
    async def surfer_policy_allow(request: Request):
        owner(request)
        entry = gate.save_entry(await body_of(request))
        store.audit(who="owner", action="allowlist_save", element=entry["pattern"],
                    value=",".join(entry["classes"]) + (" on" if entry["enabled"] else " off"))
        return {"entry": entry, **state()}

    @app.post("/api/factory/surfer/owner/policy/allow/{entry_id}/delete")
    def surfer_policy_allow_delete(entry_id: str, request: Request):
        owner(request)
        if not ENTRY_ID_RE.fullmatch(entry_id) or not gate.remove_entry(entry_id):
            raise HTTPException(404, "unknown allowlist entry")
        store.audit(who="owner", action="allowlist_delete", element=entry_id)
        return state()

    @app.post("/api/factory/surfer/owner/policy/pause")
    async def surfer_policy_pause(request: Request):
        owner(request)
        paused = gate.set_paused((await body_of(request)).get("paused") is True)
        closed = store.stop_all(by="owner", reason="paused_by_owner") if paused else 0
        store.audit(who="owner", action="pause" if paused else "resume", result=f"{closed} session(s) closed")
        return {"paused": paused, "closed": closed, **state()}

    @app.post("/api/factory/surfer/owner/steps/{step_id}/{decision}")
    def surfer_step_decision(step_id: str, decision: str, request: Request):
        owner(request)
        if decision not in ("confirm", "reject"):
            raise HTTPException(404, "unknown decision")
        if decision == "confirm" and not gate.status()["enabled"]:
            raise HTTPException(409, gate.status()["reason"])
        step = store.decide(step_id, confirm=decision == "confirm")
        return {"step": {"id": step["id"], "status": step["status"]}}
