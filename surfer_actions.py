"""T-720 Surfer action sessions: the browser agent acts in the owner's accounts (server side).

Spec: docs/roadmap/T-720_SURFER_ACTIONS.md. A session is one live page on the EC2 Surfer worker. An agent drives it
step by step through four tools (MCP and REST): web_open, web_act, web_snapshot, web_close. Render cannot reach EC2,
so the worker polls: ``worker_claim`` hands out one command, ``worker_result`` takes the outcome (status, snapshot,
screenshot). The tool call waits for that outcome.

What this module guarantees:
- every step is reviewed against the owner's allowlist with ``browser_runner.action_policy`` before it is queued,
  and the worker reviews it again on the live page; a step that needs the owner waits as
  ``needs_owner_confirmation`` and is not executed until the owner confirms it;
- secrets: a vault value is read only when the worker claims the command and travels only in that response; text the
  owner types is kept in memory only; neither is written to a step, a snapshot or the audit log;
- every step is written to the audit log (who, lane, URL without query, action, element label, result, screenshot).

T-720 ships the engine closed (``ClosedGate``); the owner's flag, allowlist and caps arrive with T-721.
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse

from browser_runner import action_policy as policy

SESSION_ID_RE = re.compile(r"^ws_[0-9a-f]{16}$")
STEP_ID_RE = re.compile(r"^wa_[0-9a-f]{16}$")
REF_RE = re.compile(r"^e[0-9]{1,6}$")
SELECTOR_RE = re.compile(r"^[^\x00-\x1f<>{};]{1,200}$")
LOGIN_RE = re.compile(r"^([a-z0-9][a-z0-9_.-]{0,39})/([\w.@+ -]{1,80})$")
AGENT_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,40}$")

IDLE_SECONDS = 300                   # no command from the agent for this long: the session is closed
OWNER_WAIT_SECONDS = 900             # while it waits for the owner (confirmation, code, takeover)
MAX_LIFETIME_SECONDS = 1800
MAX_STEPS_PER_SESSION = 200
KEEP_CLOSED_SESSIONS = 15
LEASE_SECONDS = 120                  # a claimed command the worker never reported
WAIT_DEFAULT, WAIT_MAX = 45, 50
POLL_SECONDS = 0.4
MAX_VALUE = 10_000
MAX_SHOT_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_TEXT = 30_000
MAX_ELEMENTS = 200
TEXT_DEFAULT, TEXT_AFTER_ACT, TEXT_MAX = 4000, 1200, 20_000
ELEMENTS_DEFAULT = 80
AUDIT_MAX_LINES = 5000

OPEN_STATUSES = ("opening", "active", "waiting_human", "needs_owner_confirmation", "takeover")
OWNER_WAIT_STATUSES = ("waiting_human", "needs_owner_confirmation", "takeover")
STEP_FINAL = ("done", "failed", "blocked", "refused", "rejected", "cancelled")
OWNER_KINDS = ("human_input", "takeover_click", "takeover_type", "takeover_key", "takeover_scroll", "save_login")

TOOLS = [
    {
        "name": "web_open",
        "description": "ACT on a site in the owner's signed-in account: open a live browser session (one page kept "
                       "across steps) and get its snapshot. Works only on sites the owner put on the Surfer allowlist "
                       "and only with your own lane MCP token. Returns {session_id, status, url, title, text, "
                       "elements:[{ref, kind, name, value?, href?, secret?}], hints}. Then use web_act with a ref. "
                       "With session_id it navigates the existing session to another url instead. One session at a "
                       "time; close it with web_close when done. Statuses: done, running (call web_snapshot), "
                       "needs_owner_confirmation (the owner must confirm this step on the Surfer page), waiting_human "
                       "(login, captcha or code: the owner takes over; nothing is solved), refused, blocked, failed. "
                       "For reading public pages use web_read instead.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "https:// address on an allowlisted site."},
                "session": {"type": "string", "description": "Optional saved login 'site/account' bound to this site "
                                                             "by the owner; by default the site's own login is used."},
                "session_id": {"type": "string", "description": "Navigate this live session instead of opening one."},
                "wait_seconds": {"type": "integer", "minimum": 0, "maximum": WAIT_MAX},
                "agent": {"type": "string", "description": "Who is asking; a label for the history."},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_act",
        "description": "One step in a live session: click, fill, select, check, press, upload, scroll, wait_for, back. "
                       "Point at an element with 'ref' from the latest snapshot (or a CSS 'selector' matching exactly "
                       "one element). fill: 'value', or for login fields 'value_from': "
                       "'vault:site/account#username' / '#password' (you never see the value; secret fields accept "
                       "only this). select: 'value' is the option value or label. check: 'value' true/false. press: "
                       "'key' (Enter, Tab, Escape, arrows...). upload: 'asset_id' of a file the owner approved. "
                       "scroll: 'value' up/down, or a ref to bring into view. wait_for: 'selector' or 'value' (text). "
                       "Returns the new snapshot. Payment, delete, security settings, messages to people, publishing "
                       "and anything outside the allowlist return needs_owner_confirmation: tell the owner, then "
                       "poll web_snapshot with the step_id. Example: {\"session_id\": \"ws_…\", \"action\": \"fill\", "
                       "\"ref\": \"e4\", \"value\": \"Kyiv\"}.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "action": {"type": "string", "enum": [a for a in policy.ACTIONS if a != "goto"]},
                "ref": {"type": "string", "description": "Element ref from the latest snapshot, e.g. e12."},
                "selector": {"type": "string", "description": "CSS selector matching exactly one element."},
                "value": {"type": ["string", "boolean"]},
                "value_from": {"type": "string", "description": "vault:site/account#username or #password."},
                "key": {"type": "string", "enum": list(policy.KEYS)},
                "asset_id": {"type": "string", "description": "Owner-approved upload file id (su_…)."},
                "wait_seconds": {"type": "integer", "minimum": 0, "maximum": WAIT_MAX},
            },
            "required": ["session_id", "action"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_snapshot",
        "description": "The current page of a live session: title, url, a chunk of its main text, the interactive "
                       "elements with refs, and the state of the last (or the given) step. Use it after a 'running' "
                       "answer, while a step waits for the owner, or to read more text (offset) or find elements "
                       "(filter by label, max_elements).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string"},
                "step_id": {"type": "string", "description": "Report this step's status (default: the last step)."},
                "refresh": {"type": "boolean", "description": "Read the page again on the worker (default: only "
                                                              "when no step is in flight and the snapshot is old)."},
                "offset": {"type": "integer", "minimum": 0},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": TEXT_MAX},
                "max_elements": {"type": "integer", "minimum": 0, "maximum": MAX_ELEMENTS},
                "filter": {"type": "string", "description": "Only elements whose label contains this text."},
            },
            "required": ["session_id"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_close",
        "description": "Close a live session (the browser page is closed; nothing else changes).",
        "inputSchema": {"type": "object", "properties": {"session_id": {"type": "string"}},
                        "required": ["session_id"], "additionalProperties": False},
    },
]
TOOL_NAMES = frozenset(t["name"] for t in TOOLS)

BLOCKER_HINTS = (
    ("stale_ref", "The page changed and this ref is gone or is another element now. Call web_snapshot and use the "
                  "new refs."),
    ("selector_matched", "The selector must match exactly one element. Use a ref from web_snapshot."),
    ("left_allowlist", "The step tried to leave the owner's allowlist and was stopped in the browser. If the owner "
                       "wants that site, he adds it on the Surfer page."),
    ("submit_not_allowed", "This site is allowed without 'submit', so the form was not sent. The owner can switch "
                           "'submit' on for it on the Surfer page."),
    ("secret_field_needs_vault_reference", "This is a secret field: pass value_from 'vault:site/account#password'; "
                                           "a typed value is never accepted."),
    ("vault_", "The vault reference does not fit: it must be the login the owner bound to this site, '#password' "
               "only into a password field, '#username' only into a text field."),
    ("element_timeout", "The element did not become ready in time. Call web_snapshot; it may be hidden or covered."),
    ("element_disabled", "The element is disabled on the page."),
    ("net_err", "The browser could not load the page (network error)."),
    ("worker_lost", "The browser worker restarted and the page is gone. Open a new session."),
)


def _now_iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _int_arg(args: dict, name: str, default: int, low: int, high: int) -> int:
    try:
        value = int(args.get(name, default) if args.get(name) is not None else default)
    except (TypeError, ValueError):
        raise HTTPException(400, f"{name} must be a number")
    return max(low, min(value, high))


class ClosedGate:
    """The gate of T-720: nothing may act. T-721 replaces it with the owner's flag, allowlist and caps."""

    loopback = False

    def status(self) -> dict:
        return {"enabled": False, "reason": "Surfer actions are not switched on yet (T-721: owner flag and allowlist)"}

    def require(self, lane: str) -> None:
        raise HTTPException(503, self.status()["reason"])

    def allow(self) -> list:
        return []

    def count(self, kind: str) -> None:
        raise HTTPException(503, self.status()["reason"])

    def secret(self, value_from: str) -> str:
        return ""

    def storage_state(self, login: str) -> Optional[dict]:
        return None

    def save_storage_state(self, login: str, state: dict) -> bool:
        return False

    def upload(self, asset_id: str) -> Optional[dict]:
        return None


class ActionStore:
    """Sessions, their steps, the latest snapshot, screenshots and the audit log, as files under DATA_DIR."""

    def __init__(self, data_dir: Path, *, clock: Callable[[], float] = time.time):
        self.root = Path(data_dir) / "surfer_actions"
        self.sessions_dir, self.snaps, self.shots = self.root / "sessions", self.root / "snaps", self.root / "shots"
        self.audit_path = self.root / "audit.jsonl"
        self.clock, self.lock = clock, threading.RLock()
        self._volatile: Dict[str, str] = {}             # step id -> text the owner typed; memory only

    # --- files ------------------------------------------------------------------------------------------------
    def _read(self, session_id: str) -> Optional[dict]:
        if not SESSION_ID_RE.fullmatch(session_id or ""):
            return None
        try:
            doc = json.loads((self.sessions_dir / f"{session_id}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return doc if isinstance(doc, dict) and isinstance(doc.get("session"), dict) else None

    def _write(self, doc: dict) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        path = self.sessions_dir / f"{doc['session']['id']}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)

    def _all(self) -> List[dict]:
        docs = []
        for path in self.sessions_dir.glob("ws_*.json") if self.sessions_dir.is_dir() else []:
            doc = self._read(path.stem)
            if doc:
                docs.append(doc)
        return sorted(docs, key=lambda d: d["session"].get("created", 0))

    def _prune(self) -> None:
        closed = [d for d in self._all() if d["session"]["status"] == "closed"]
        for doc in closed[:-KEEP_CLOSED_SESSIONS] if len(closed) > KEEP_CLOSED_SESSIONS else []:
            sid = doc["session"]["id"]
            for step in doc.get("steps") or []:
                for ext in ("png", "jpg"):
                    (self.shots / f"{step['id']}.{ext}").unlink(missing_ok=True)
            (self.snaps / f"{sid}.json").unlink(missing_ok=True)
            (self.sessions_dir / f"{sid}.json").unlink(missing_ok=True)

    def audit(self, **row: Any) -> None:
        row = {"at": _now_iso(self.clock()), **{k: v for k, v in row.items() if v not in (None, "", [], {})}}
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            try:
                lines = self.audit_path.read_text(encoding="utf-8").splitlines() if self.audit_path.is_file() else []
            except OSError:
                lines = []
            lines.append(json.dumps(row, ensure_ascii=False))
            tmp = self.audit_path.with_suffix(".tmp")
            tmp.write_text("\n".join(lines[-AUDIT_MAX_LINES:]) + "\n", encoding="utf-8")
            tmp.replace(self.audit_path)

    def audit_tail(self, limit: int = 100) -> List[dict]:
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines[-max(1, min(limit, 1000)):]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
        return list(reversed(out))

    def _audit_step(self, session: dict, step: dict, result: str = "") -> None:
        element = step.get("element") or {}
        value = step.get("value")
        if step.get("value_from"):
            value = step["value_from"]                      # the reference, never the value
        elif element.get("secret") or step.get("kind") in OWNER_KINDS:
            value = "***" if step.get("kind") in ("human_input", "takeover_type") or value else None
        self.audit(session=session["id"], step=step["id"], who=step.get("by") or "", lane=session.get("lane") or "",
                   url=policy.log_url(step.get("page_url") or session.get("url") or ""),
                   action=step.get("action") or step.get("kind"), element=str(element.get("name") or "")[:120],
                   element_kind=element.get("kind"), value=(str(value)[:200] if value not in (None, "") else None),
                   klass=(step.get("review") or {}).get("klass"), reasons=(step.get("review") or {}).get("reasons"),
                   result=result or step.get("status"), blocker=step.get("blocker"),
                   confirmed_by=step.get("confirmed_by"), screenshot=step["id"] if step.get("screenshot") else None)

    # --- sessions ---------------------------------------------------------------------------------------------
    def _expire(self) -> None:
        now = self.clock()
        for doc in self._all():
            s = doc["session"]
            if s["status"] not in OPEN_STATUSES:
                continue
            limit = OWNER_WAIT_SECONDS if s["status"] in OWNER_WAIT_STATUSES else IDLE_SECONDS
            reason = ""
            if now - s.get("created", now) > MAX_LIFETIME_SECONDS:
                reason = "max_lifetime"
            elif now - s.get("last_activity", now) > limit:
                reason = "owner_did_not_answer" if s["status"] in OWNER_WAIT_STATUSES else "idle_timeout"
            if reason:
                self._close(doc, reason, by="system")

    def _close(self, doc: dict, reason: str, *, by: str) -> None:
        s = doc["session"]
        if s["status"] == "closed":
            return
        now = self.clock()
        s.update(status="closed", closed=int(now), close_reason=reason[:80], closed_by=by)
        for step in doc["steps"]:
            if step["status"] not in STEP_FINAL:
                step.update(status="cancelled", blocker="session_closed:" + reason[:60], finished=int(now))
                self._volatile.pop(step["id"], None)
        self._write(doc)
        self.audit(session=s["id"], who=by, lane=s.get("lane") or "", action="close", result=reason)
        self._prune()

    def live(self) -> Optional[dict]:
        with self.lock:
            self._expire()
            for doc in self._all():
                if doc["session"]["status"] in OPEN_STATUSES:
                    return doc["session"]
        return None

    def create_session(self, *, lane: str, agent: str, url: str, login: str = "") -> tuple:
        with self.lock:
            self._expire()
            for doc in self._all():
                s = doc["session"]
                if s["status"] in OPEN_STATUSES:
                    idle = int(self.clock() - s.get("last_activity", self.clock()))
                    mine = f" Your session is {s['id']}: continue it or call web_close." if s.get("lane") == lane else ""
                    raise HTTPException(409, f"another Surfer session is live (lane {s.get('lane')}, idle {idle}s); "
                                             f"one at a time, retry in a few minutes.{mine}")
            now = int(self.clock())
            session = {"id": "ws_" + secrets.token_hex(8), "lane": lane, "agent": agent, "status": "opening",
                       "created": now, "last_activity": now, "start_url": policy.log_url(url), "url": "",
                       "title": "", "login": login, "extra_origins": [], "steps_total": 0}
            doc = {"session": session, "steps": []}
            step = self._add(doc, {"kind": "open", "url": url}, by=lane)
            self._write(doc)
            self.audit(session=session["id"], who=lane, lane=lane, action="open", url=policy.log_url(url),
                       result="queued")
            return session, step

    def _add(self, doc: dict, spec: dict, *, by: str, status: str = "queued") -> dict:
        s = doc["session"]
        if s["steps_total"] >= MAX_STEPS_PER_SESSION:
            self._close(doc, "step_limit", by="system")
            raise HTTPException(409, "this session reached its step limit and was closed; open a new one")
        s["steps_total"] += 1
        s["last_activity"] = int(self.clock())
        step = {"id": "wa_" + secrets.token_hex(8), "seq": s["steps_total"], "status": status, "by": by,
                "created": int(self.clock()), "page_url": s.get("url") or "", **spec}
        doc["steps"].append(step)
        return step

    def get(self, session_id: str) -> Optional[dict]:
        with self.lock:
            self._expire()
            return self._read(session_id)

    def list(self) -> List[dict]:
        with self.lock:
            self._expire()
            return list(reversed(self._all()))

    def snapshot(self, session_id: str) -> dict:
        if not SESSION_ID_RE.fullmatch(session_id or ""):
            return {}
        try:
            value = json.loads((self.snaps / f"{session_id}.json").read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def screenshot(self, step_id: str) -> Path:
        if STEP_ID_RE.fullmatch(step_id or ""):
            for ext in ("png", "jpg"):
                path = self.shots / f"{step_id}.{ext}"
                if path.is_file():
                    return path
        raise HTTPException(404, "no screenshot")

    def find_step(self, step_id: str) -> tuple:
        if not STEP_ID_RE.fullmatch(step_id or ""):
            return None, None
        for doc in self._all():
            for step in doc["steps"]:
                if step["id"] == step_id:
                    return doc, step
        return None, None

    # --- steps ------------------------------------------------------------------------------------------------
    def pending(self, doc: dict) -> Optional[dict]:
        """The step that is queued, running or waiting for the owner (one at a time per session)."""
        for step in doc["steps"]:
            if step["status"] not in STEP_FINAL:
                return step
        return None

    def add_step(self, session_id: str, spec: dict, *, by: str, status: str = "queued",
                 volatile: str = "") -> dict:
        with self.lock:
            self._expire()
            doc = self._read(session_id)
            if not doc or doc["session"]["status"] == "closed":
                raise HTTPException(404, "no such live session (it may have timed out); open a new one")
            waiting = self.pending(doc)
            if waiting:
                raise HTTPException(409, f"step {waiting['id']} is {waiting['status']}; wait for it "
                                         "(web_snapshot) or close the session")
            step = self._add(doc, spec, by=by, status=status)
            if volatile:
                self._volatile[step["id"]] = volatile
            if status == "needs_owner_confirmation":
                doc["session"]["status"] = "needs_owner_confirmation"
            self._write(doc)
            if status != "queued":
                self._audit_step(doc["session"], step)
            return step

    def record_refusal(self, session_id: str, spec: dict, *, by: str, blocker: str) -> None:
        doc = self.get(session_id)
        if doc:
            self._audit_step(doc["session"], {"id": "", "by": by, "status": "refused", "blocker": blocker,
                                              "page_url": doc["session"].get("url") or "", **spec})

    def decide(self, step_id: str, *, confirm: bool, owner: str = "owner") -> dict:
        """The owner confirms or rejects a step that waits for him."""
        with self.lock:
            self._expire()
            doc, step = self.find_step(step_id)
            if not doc or step["status"] != "needs_owner_confirmation" or doc["session"]["status"] == "closed":
                raise HTTPException(409, "this step is not waiting for confirmation")
            session = doc["session"]
            session["last_activity"] = int(self.clock())
            reasons = list((step.get("review") or {}).get("reasons") or [])
            if confirm:
                step.update(status="queued", confirmed_by=owner, confirmed_at=int(self.clock()),
                            confirmed_reasons=reasons)
                if "leaves_allowlist" in reasons:
                    element = step.get("element") or {}
                    target = step.get("url") or element.get("href") or (element.get("form") or {}).get("action") or ""
                    origin = policy.origin_of(target)
                    if origin and origin not in session["extra_origins"]:
                        session["extra_origins"] = (session["extra_origins"] + [origin])[-10:]
                session["status"] = "active"
            else:
                step.update(status="rejected", blocker="rejected_by_owner", finished=int(self.clock()),
                            confirmed_by=owner)
                session["status"] = "active"
            self._write(doc)
            self._audit_step(session, step, "confirmed" if confirm else "rejected")
            return step

    def stop(self, session_id: str, *, by: str, reason: str = "stopped") -> dict:
        with self.lock:
            doc = self._read(session_id)
            if not doc:
                raise HTTPException(404, "unknown session")
            self._close(doc, reason, by=by)
            return doc["session"]

    def stop_all(self, *, by: str, reason: str) -> int:
        with self.lock:
            count = 0
            for doc in self._all():
                if doc["session"]["status"] in OPEN_STATUSES:
                    self._close(doc, reason, by=by)
                    count += 1
            return count

    # --- worker -----------------------------------------------------------------------------------------------
    def worker_claim(self, live: str, gate: Any) -> dict:
        """One command for the worker. ``live`` is the session whose page the worker holds ('' when none)."""
        with self.lock:
            self._expire()
            now = self.clock()
            target = None
            for doc in self._all():
                s = doc["session"]
                if s["status"] not in OPEN_STATUSES:
                    continue
                if s.get("opened") and s["id"] != live:
                    self._close(doc, "worker_lost", by="system")      # the worker no longer holds this page
                    continue
                target = doc
            if live and (not target or target["session"]["id"] != live):
                return {"command": None, "close": True}
            if not target:
                return {"command": None, "close": False}
            session = target["session"]
            step = self.pending(target)
            if not step or step["status"] == "needs_owner_confirmation":
                return {"command": None, "close": False}
            if step["status"] == "running" and step.get("lease_until", 0) > now:
                return {"command": None, "close": False}
            if step["status"] == "running":                           # claimed, never reported
                step.update(status="failed", blocker="worker_did_not_report", finished=int(now))
                self._write(target)
                self._audit_step(session, step)
                return {"command": None, "close": False}
            if step["kind"] != "open" and not live:
                self._close(target, "worker_lost", by="system")
                return {"command": None, "close": False}
            step.update(status="running", claimed=int(now), lease_until=int(now + LEASE_SECONDS))
            self._write(target)
            command = {k: step[k] for k in ("id", "kind", "action", "ref", "selector", "value", "value_from", "key",
                                            "url", "expect", "confirmed_reasons", "submit", "x", "y", "dy")
                       if k in step}
            command["session_id"] = session["id"]
            command["policy"] = {"allow": gate.allow(), "extra_origins": list(session.get("extra_origins") or []),
                                 "takeover": session["status"] == "takeover"}
            try:
                if step["kind"] == "open" and session.get("login"):
                    command["storage_state"] = gate.storage_state(session["login"])
                if step.get("value_from"):
                    command["secret_value"] = gate.secret(step["value_from"])
                if step["kind"] in ("human_input", "takeover_type"):
                    command["secret_value"] = self._volatile.pop(step["id"], "")
                if step.get("asset_id"):
                    info = gate.upload(step["asset_id"]) or {}
                    command["file_name"] = str(info.get("name") or "")
            except Exception:
                pass                                                   # the worker reports the missing value
            return {"command": command, "close": False}

    def worker_result(self, step_id: str, body: dict, gate: Any) -> dict:
        status = str(body.get("status") or "")
        if status not in ("done", "failed", "blocked", "refused", "needs_confirmation", "waiting_human"):
            raise HTTPException(400, "bad status")
        shot = body.get("screenshot_b64") or ""
        raw = b""
        if shot:
            try:
                raw = base64.b64decode(shot, validate=True)
            except ValueError:
                raise HTTPException(400, "bad screenshot")
            if len(raw) > MAX_SHOT_BYTES or not (raw.startswith(b"\x89PNG") or raw.startswith(b"\xff\xd8")):
                raise HTTPException(400, "bad screenshot")
        with self.lock:
            doc, step = self.find_step(step_id)
            if not doc or step["status"] != "running":
                raise HTTPException(409, "command is not running")
            session = doc["session"]
            now = int(self.clock())
            snap = body.get("snapshot") if isinstance(body.get("snapshot"), dict) else {}
            if raw:
                self.shots.mkdir(parents=True, exist_ok=True)
                ext = "png" if raw.startswith(b"\x89PNG") else "jpg"
                (self.shots / f"{step_id}.{ext}").write_bytes(raw)
            if snap:
                clean = clean_snapshot(snap)
                clean["step"] = step_id
                clean["at"] = now
                self.snaps.mkdir(parents=True, exist_ok=True)
                tmp = self.snaps / f"{session['id']}.tmp"
                tmp.write_text(json.dumps(clean, ensure_ascii=False), encoding="utf-8")
                tmp.replace(self.snaps / f"{session['id']}.json")
                session.update(url=clean["url"], title=clean["title"])
            if step["kind"] == "open" and status in ("done", "waiting_human"):
                session["opened"] = now
            element = body.get("element") if isinstance(body.get("element"), dict) else None
            if element and not step.get("element"):
                step["element"] = clean_element(element)
            review = body.get("review") if isinstance(body.get("review"), dict) else None
            if review:
                step["review"] = {"klass": str(review.get("klass") or "")[:20],
                                  "reasons": [str(r)[:40] for r in (review.get("reasons") or [])][:10]}
            step.update(screenshot=bool(raw), blocker=str(body.get("blocker") or "")[:120])
            events = [e for e in (body.get("events") or []) if isinstance(e, dict)][:10]
            if events:
                step["events"] = [{"event": str(e.get("event") or "")[:40], "url": str(e.get("url") or "")[:300]}
                                  for e in events]
            if body.get("redirect_to"):
                step["redirect_to"] = str(body["redirect_to"])[:300]
            if body.get("http_status"):
                try:
                    step["http_status"] = int(body["http_status"])
                except (TypeError, ValueError):
                    pass
            step.pop("lease_until", None)
            session["last_activity"] = now
            if status == "needs_confirmation":
                step["status"] = "needs_owner_confirmation"
                step["expect"] = policy.fingerprint(step.get("element"))
                session["status"] = "needs_owner_confirmation"
            else:
                step.update(status="done" if status == "waiting_human" else status, finished=now)
                if session["status"] != "takeover":
                    ack = session.get("challenge_ack") == policy.log_url(session.get("url") or "")
                    if status == "waiting_human" and not ack:
                        session.update(status="waiting_human", wait_reason=step["blocker"] or "security_challenge")
                    elif step["kind"] == "open" and status not in ("done", "waiting_human"):
                        self._write(doc)
                        self._audit_step(session, step)
                        self._close(doc, "open_failed:" + (step["blocker"] or status), by="system")
                        return step
                    elif session["status"] in ("opening", "waiting_human", "needs_owner_confirmation"):
                        session["status"] = "active"
                        session.pop("wait_reason", None)
            state = body.get("storage_state")
            if step["kind"] == "save_login" and isinstance(state, dict) and session.get("login"):
                try:
                    step["saved"] = bool(gate.save_storage_state(session["login"], state))
                except Exception:
                    step["saved"] = False
            self._write(doc)
            self._audit_step(session, step)
            return step


def clean_element(raw: dict) -> dict:
    """Bounded, typed copy of an element description from the worker (nothing else is stored)."""
    out: Dict[str, Any] = {}
    for key, limit in (("ref", 8), ("kind", 12), ("tag", 12), ("type", 20), ("role", 20), ("name", 160),
                       ("autocomplete", 30), ("hint", 200), ("href", 500), ("value", 200)):
        if raw.get(key) not in (None, ""):
            out[key] = str(raw[key])[:limit]
    for key in ("disabled", "required", "secret", "submit", "checked", "filled", "in_view"):
        if key in raw:
            out[key] = bool(raw[key])
    if out.get("secret"):
        out.pop("value", None)
    form = raw.get("form")
    if isinstance(form, dict):
        out["form"] = {"action": str(form.get("action") or "")[:500], "method": str(form.get("method") or "")[:8],
                       "submit_label": str(form.get("submit_label") or "")[:160],
                       **{k: bool(form.get(k)) for k in ("has_password", "has_new_password", "has_payment", "has_otp")}}
    options = raw.get("options")
    if isinstance(options, list):
        out["options"] = [{"value": str(o.get("value") or "")[:120], "label": str(o.get("label") or "")[:120]}
                          for o in options[:40] if isinstance(o, dict)]
    return out


def clean_snapshot(raw: dict) -> dict:
    markers = raw.get("markers") if isinstance(raw.get("markers"), dict) else {}
    elements = [clean_element(e) for e in (raw.get("elements") or [])[:MAX_ELEMENTS] if isinstance(e, dict)]
    elements = [e for e in elements if REF_RE.fullmatch(e.get("ref") or "")]
    try:
        total = int(raw.get("elements_total") or len(elements))
    except (TypeError, ValueError):
        total = len(elements)
    return {"url": policy.safe_url(str(raw.get("url") or "")), "title": str(raw.get("title") or "")[:300],
            "text": str(raw.get("text") or "")[:MAX_SNAPSHOT_TEXT], "page_id": str(raw.get("page_id") or "")[:20],
            "elements": elements, "elements_total": max(total, len(elements)),
            "markers": {"challenge": str(markers.get("challenge") or "")[:40],
                        "login_wall": bool(markers.get("login_wall")), "code_prompt": bool(markers.get("code_prompt"))}}


def _agent_element(el: dict, page_origin: str) -> dict:
    out = {"ref": el["ref"], "kind": el.get("kind") or "other", "name": el.get("name") or ""}
    if el.get("kind") == "input" and el.get("type") not in (None, "", "text"):
        out["type"] = el["type"]
    for key in ("value", "checked", "filled", "options"):
        if key in el and el[key] not in ("", None):
            out[key] = el[key]
    href = el.get("href") or ""
    if href:
        out["href"] = href[len(page_origin):] or "/" if page_origin and href.startswith(page_origin + "/") else href
    for key in ("disabled", "required", "secret", "submit"):
        if el.get(key):
            out[key] = True
    return out


def _hint_for(blocker: str) -> str:
    for prefix, text in BLOCKER_HINTS:
        if blocker.startswith(prefix):
            return text
    return ""


def view(store: ActionStore, doc: dict, step: Optional[dict], *, offset: int = 0, max_chars: int = TEXT_DEFAULT,
         max_elements: int = ELEMENTS_DEFAULT, name_filter: str = "") -> dict:
    """What an agent sees: the step's outcome and the page. No secrets, no screenshot."""
    session = doc["session"]
    out: Dict[str, Any] = {"session_id": session["id"], "status": session["status"]}
    hints: List[str] = []
    if step:
        out["step_id"] = step["id"]
        status = step["status"]
        if status in ("queued", "running"):
            out["status"] = "running"
            out["next"] = "call web_snapshot with this session_id and step_id in a few seconds"
        elif status == "needs_owner_confirmation":
            out["status"] = status
            element = step.get("element") or {}
            out["preview"] = {"action": step.get("action") or step.get("kind"), "element": element.get("name") or "",
                              "reasons": (step.get("review") or {}).get("reasons") or [],
                              "url": policy.log_url(step.get("page_url") or session.get("url") or "")}
            hints.append("This step waits for the owner: he confirms or rejects it on the FactoryOS Surfer page "
                         "(/static/surfer/index.html). Tell him what you are about to do and why, then call "
                         "web_snapshot with step_id to see his decision. Do not retry the step.")
        elif status == "done":
            out["status"] = "done" if session["status"] in ("active", "opening") else session["status"]
        else:
            out["status"] = status                         # failed, blocked, refused, rejected, cancelled
        if step.get("blocker"):
            out["blocker"] = step["blocker"]
            hint = _hint_for(step["blocker"])
            if hint:
                hints.append(hint)
        if status == "rejected":
            hints.append("The owner rejected this step. Do not try it again; ask him what to do instead.")
        for key in ("redirect_to", "http_status"):
            if step.get(key):
                out[key] = step[key]
        popups = [e["url"] for e in step.get("events") or [] if e.get("event") == "popup_closed" and e.get("url")]
        if popups:
            hints.append(f"The click opened a new tab ({popups[0]}); it was closed. Use web_open with session_id "
                         "and that url to go there in this session.")
    if session["status"] == "closed":
        out["status"] = "closed" if not step or step["status"] in ("done", "cancelled") else out["status"]
        out["close_reason"] = session.get("close_reason") or ""
        if out["close_reason"]:
            hint = _hint_for(out["close_reason"])
            if hint:
                hints.append(hint)
        if hints:
            out["hints"] = hints
        return out
    if session["status"] == "waiting_human":
        out["wait_reason"] = session.get("wait_reason") or ""
        hints.append("The page asks for something only the owner can do (login, captcha, or a code sent to him). "
                     "FactoryOS never solves or bypasses it. Tell the owner to open the Surfer page and take over; "
                     "call web_snapshot later to continue.")
    elif session["status"] == "takeover":
        hints.append("The owner is driving the page himself right now. Wait and call web_snapshot later.")
    snap = store.snapshot(session["id"])
    if snap:
        text = str(snap.get("text") or "")
        offset = max(0, min(offset, len(text)))
        chunk = text[offset:offset + max_chars]
        end = offset + len(chunk)
        page_origin = policy.origin_of(snap.get("url") or "")
        elements = snap.get("elements") or []
        needle = name_filter.strip().lower()
        if needle:
            elements = [e for e in elements if needle in str(e.get("name") or "").lower()]
        out.update(url=snap.get("url") or "", title=snap.get("title") or "", text=chunk, offset=offset,
                   total_chars=len(text), next_offset=end if end < len(text) else None,
                   elements=[_agent_element(e, page_origin) for e in elements[:max_elements]],
                   elements_total=int(snap.get("elements_total") or len(elements)))
        if len(elements) > max_elements or out["elements_total"] > len(snap.get("elements") or []):
            hints.append("Not all elements are listed: use 'filter' (part of a label), a larger max_elements, or "
                         "scroll the page.")
        markers = snap.get("markers") or {}
        if markers.get("login_wall") and session["status"] == "active":
            login = session.get("login") or ""
            hints.append("The page shows a login form. " + (
                f"Fill it with value_from 'vault:{login}#username' and 'vault:{login}#password', then press the "
                "sign-in button. If it asks for a code afterwards, the owner takes over." if login else
                "No saved login is bound to this site: the owner signs in himself on the Surfer page (Take over)."))
    if hints:
        out["hints"] = hints
    return out


async def _wait(store: ActionStore, step_id: str, seconds: int, *, sleep=asyncio.sleep,
                clock: Callable[[], float] = time.monotonic) -> tuple:
    deadline = clock() + seconds
    while True:
        doc, step = store.find_step(step_id)
        if not doc or step["status"] not in ("queued", "running") or clock() >= deadline:
            return doc, step
        await sleep(POLL_SECONDS)


def _session_for(store: ActionStore, session_id: str, lane: str) -> dict:
    doc = store.get(str(session_id or ""))
    if not doc or doc["session"].get("lane") != lane:        # a lane sees only its own sessions
        raise HTTPException(404, "unknown session")
    return doc


def _check_url(url: str, gate: Any) -> str:
    import browser_tasks
    url = str(url or "").strip()
    if getattr(gate, "loopback", False) and policy.host_of(url) == "127.0.0.1" and len(url) <= 2000:
        return url
    return browser_tasks.check_url(url)


async def web_open(store: ActionStore, gate: Any, args: dict, lane: str, **kw) -> dict:
    gate.require(lane)
    url = _check_url(args.get("url"), gate)
    wait = _int_arg(args, "wait_seconds", WAIT_DEFAULT, 0, WAIT_MAX)
    allow = gate.allow()
    if args.get("session_id"):
        doc = _session_for(store, args["session_id"], lane)
        session = doc["session"]
        verdict = policy.review("goto", None, session.get("url") or "", allow, url=url,
                                extra_origins=session.get("extra_origins") or (), loopback=gate.loopback)
        spec = {"kind": "goto", "action": "goto", "url": url,
                "review": {"klass": verdict["klass"], "reasons": verdict["reasons"]}}
        if verdict["decision"] == policy.DECISION_REFUSE:
            store.record_refusal(session["id"], spec, by=lane, blocker=verdict["detail"])
            raise HTTPException(400, f"refused: {verdict['detail']}")
        gate.count("step")
        step = store.add_step(session["id"], spec, by=lane, status="needs_owner_confirmation"
                              if verdict["decision"] == policy.DECISION_CONFIRM else "queued")
    else:
        if not policy.url_allowed(allow, url, loopback=gate.loopback):
            sites = ", ".join(e["pattern"] for e in allow if e.get("enabled"))[:300] or "none yet"
            store.audit(who=lane, lane=lane, action="open", url=policy.log_url(url), result="refused",
                        blocker="off_allowlist")
            raise HTTPException(403, f"this site is not on the owner's Surfer allowlist (allowed: {sites}). The owner "
                                     "adds sites on /static/surfer/index.html; for reading a public page use web_read.")
        entry = policy.match(allow, policy.host_of(url)) or {}
        login = str(args.get("session") or "").strip() or str(entry.get("login") or "")
        if login and (not LOGIN_RE.fullmatch(login) or login != str(entry.get("login") or "")):
            raise HTTPException(403, "this saved login is not bound to the site by the owner"
                                     + (f"; the site's login is {entry['login']}" if entry.get("login") else ""))
        gate.count("session")
        agent = str(args.get("agent") or "").strip()
        session, step = store.create_session(lane=lane, agent=agent if AGENT_RE.fullmatch(agent) else "", url=url,
                                             login=login)
    doc, step = await _wait(store, step["id"], wait, **kw)
    return view(store, doc, step)


async def web_act(store: ActionStore, gate: Any, args: dict, lane: str, **kw) -> dict:
    gate.require(lane)
    doc = _session_for(store, args.get("session_id"), lane)
    session = doc["session"]
    if session["status"] == "closed":
        raise HTTPException(409, f"the session is closed ({session.get('close_reason') or ''}); open a new one")
    if session["status"] in OWNER_WAIT_STATUSES:
        raise HTTPException(409, f"the session is {session['status']}: the owner has to act on the Surfer page first; "
                                 "call web_snapshot to see when it continues")
    action = str(args.get("action") or "")
    if action not in policy.ACTIONS or action == "goto":
        raise HTTPException(400, "unknown action")
    wait = _int_arg(args, "wait_seconds", WAIT_DEFAULT, 0, WAIT_MAX)
    ref, selector = str(args.get("ref") or "").strip(), str(args.get("selector") or "").strip()
    if ref and not REF_RE.fullmatch(ref):
        raise HTTPException(400, "ref looks like e12 (from the latest snapshot)")
    if selector and not SELECTOR_RE.fullmatch(selector):
        raise HTTPException(400, "bad CSS selector")
    value = args.get("value")
    if isinstance(value, bool):
        value = "true" if value else "false"
    value = None if value is None else str(value)
    if value is not None and len(value) > MAX_VALUE:
        raise HTTPException(400, "value is too long")
    value_from, key = str(args.get("value_from") or "").strip(), str(args.get("key") or "").strip()
    if value_from and not policy.VAULT_REF_RE.fullmatch(value_from):
        raise HTTPException(400, "value_from looks like vault:site/account#password")
    if value_from and value is not None:
        raise HTTPException(400, "pass value or value_from, not both")
    spec: Dict[str, Any] = {"kind": "act", "action": action}
    for name, item in (("ref", ref), ("selector", selector), ("value", value), ("value_from", value_from),
                       ("key", key)):
        if item not in (None, ""):
            spec[name] = item
    if action == "upload":
        asset = gate.upload(str(args.get("asset_id") or ""))
        if not asset:
            raise HTTPException(404, "unknown asset_id: only files the owner approved on the Surfer page can be "
                                     "uploaded")
        spec["asset_id"] = asset["id"]
        spec["value"] = asset.get("name") or ""
    snap = store.snapshot(session["id"])
    element = None
    if ref:
        element = next((e for e in snap.get("elements") or [] if e.get("ref") == ref), None)
        if element is None:
            raise HTTPException(409, "this ref is not in the latest snapshot (stale_ref); call web_snapshot")
        spec["element"] = element
        spec["expect"] = policy.fingerprint(element)
    status = "queued"
    if element is not None or action in ("back", "scroll", "wait_for", "press"):
        verdict = policy.review(action, element, session.get("url") or "", gate.allow(), key=key,
                                value_from=value_from, has_value=value not in (None, ""),
                                extra_origins=session.get("extra_origins") or (), loopback=gate.loopback)
        spec["review"] = {"klass": verdict["klass"], "reasons": verdict["reasons"]}
        if verdict["decision"] == policy.DECISION_REFUSE and (element is not None or not selector):
            store.record_refusal(session["id"], spec, by=lane, blocker=verdict["detail"])
            hint = _hint_for(verdict["detail"])
            raise HTTPException(400, f"refused: {verdict['detail']}" + (f". {hint}" if hint else ""))
        if verdict["decision"] == policy.DECISION_CONFIRM:
            status = "needs_owner_confirmation"
    gate.count("step")
    step = store.add_step(session["id"], spec, by=lane, status=status)
    doc, step = await _wait(store, step["id"], wait if status == "queued" else 0, **kw)
    return view(store, doc, step, max_chars=TEXT_AFTER_ACT)


async def web_snapshot(store: ActionStore, gate: Any, args: dict, lane: str, **kw) -> dict:
    gate.require(lane)
    doc = _session_for(store, args.get("session_id"), lane)
    session = doc["session"]
    step = None
    if args.get("step_id"):
        step = next((s for s in doc["steps"] if s["id"] == args["step_id"]), None)
        if step is None:
            raise HTTPException(404, "unknown step")
    pending = store.pending(doc)
    snap = store.snapshot(session["id"])
    stale = store.clock() - float(snap.get("at") or 0) > 20
    if session["status"] == "active" and not pending and (args.get("refresh") is True or (
            args.get("refresh") is None and step is None and stale)):
        gate.count("step")
        fresh = store.add_step(session["id"], {"kind": "snapshot", "action": "snapshot"}, by=lane)
        doc, step = await _wait(store, fresh["id"], WAIT_DEFAULT, **kw)
    else:
        doc = store.get(session["id"]) or doc
        step = step or (doc["steps"][-1] if doc["steps"] else None)
        if step:
            step = next((s for s in doc["steps"] if s["id"] == step["id"]), step)
    return view(store, doc, step, offset=_int_arg(args, "offset", 0, 0, 10_000_000),
                max_chars=_int_arg(args, "max_chars", TEXT_DEFAULT, 200, TEXT_MAX),
                max_elements=_int_arg(args, "max_elements", ELEMENTS_DEFAULT, 0, MAX_ELEMENTS),
                name_filter=str(args.get("filter") or "")[:80])


def web_close(store: ActionStore, gate: Any, args: dict, lane: str) -> dict:
    if not lane:
        raise HTTPException(403, "a lane MCP token is required")
    doc = _session_for(store, args.get("session_id"), lane)
    session = store.stop(doc["session"]["id"], by=lane, reason="closed_by_agent")
    return {"session_id": session["id"], "status": "closed", "close_reason": session.get("close_reason") or ""}


async def call_tool(name: str, args: dict, *, store: ActionStore, gate: Any, lane: str) -> dict:
    if not isinstance(args, dict):
        raise HTTPException(400, "arguments must be an object")
    if not lane:
        # T-624: the shared MCP token carries no identity, so it may read (web_read) but never act.
        raise HTTPException(403, "Surfer actions need your own lane MCP token (FACTORY_MCP_LANE_TOKEN_CLAUDE / "
                                 "_CHATGPT / _GEMINI); the shared MCP token may not act")
    if name == "web_open":
        return await web_open(store, gate, args, lane)
    if name == "web_act":
        return await web_act(store, gate, args, lane)
    if name == "web_snapshot":
        return await web_snapshot(store, gate, args, lane)
    if name == "web_close":
        return web_close(store, gate, args, lane)
    raise HTTPException(404, "unknown tool")


def owner_session_view(store: ActionStore, doc: dict) -> dict:
    """The owner sees everything except values: steps with element labels, reasons, screenshot flags."""
    session = dict(doc["session"])
    steps = []
    for step in doc["steps"]:
        element = step.get("element") or {}
        row = {k: step[k] for k in ("id", "seq", "kind", "action", "status", "by", "created", "finished", "blocker",
                                    "screenshot", "review", "value_from", "confirmed_by", "redirect_to", "key",
                                    "saved") if k in step}
        row["element"] = {k: element[k] for k in ("name", "kind", "type", "href") if k in element}
        row["url"] = policy.log_url(step.get("url") or step.get("page_url") or "")
        if step.get("value") not in (None, "") and not element.get("secret") and step.get("kind") == "act":
            row["value"] = str(step["value"])[:200]
        steps.append(row)
    session["steps"] = steps
    snap = store.snapshot(session["id"])
    session["page"] = {"url": snap.get("url") or "", "title": snap.get("title") or "",
                       "markers": snap.get("markers") or {}, "step": snap.get("step") or ""}
    return session


def install_routes(app, *, store: ActionStore, gate_fn: Callable[[], Any], identity: Callable,
                   authorize_worker: Callable, lane_identity: Callable[[Request], str]) -> None:
    """Agent REST (lane token), worker protocol (worker token) and the owner's read/stop routes."""

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def owner(request: Request) -> None:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    @app.post("/api/factory/surfer/agent/{tool}")
    async def surfer_agent_tool(tool: str, request: Request):
        lane = lane_identity(request)
        if not lane:
            raise HTTPException(401, "lane MCP token required")
        if tool not in TOOL_NAMES:
            raise HTTPException(404, "unknown tool")
        return await call_tool(tool, await body_of(request), store=store, gate=gate_fn(), lane=lane)

    @app.post("/api/factory/browser/worker/actions/claim")
    async def surfer_worker_claim(request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        body = await body_of(request)
        live = str(body.get("live") or "")
        return store.worker_claim(live if SESSION_ID_RE.fullmatch(live) else "", gate_fn())

    @app.post("/api/factory/browser/worker/actions/{step_id}/result")
    async def surfer_worker_result(step_id: str, request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        if not STEP_ID_RE.fullmatch(step_id):
            raise HTTPException(404, "unknown command")
        step = store.worker_result(step_id, await body_of(request), gate_fn())
        return {"ok": True, "status": step["status"]}

    @app.get("/api/factory/browser/worker/actions/{step_id}/file")
    def surfer_worker_file(step_id: str, request: Request):
        if not authorize_worker(request):
            raise HTTPException(401, "Worker token required")
        doc, step = store.find_step(step_id)
        if not doc or step["status"] != "running" or not step.get("asset_id"):
            raise HTTPException(404, "no file for this command")
        info = gate_fn().upload(step["asset_id"])
        if not info or not Path(info["path"]).is_file():
            raise HTTPException(404, "file is gone")
        return FileResponse(info["path"], media_type="application/octet-stream",
                            headers={"Cache-Control": "no-store"})

    @app.get("/api/factory/surfer/owner/sessions")
    def surfer_owner_sessions(request: Request):
        owner(request)
        return {"gate": gate_fn().status(), "sessions": [owner_session_view(store, d) for d in store.list()]}

    @app.get("/api/factory/surfer/owner/steps/{step_id}/screenshot")
    def surfer_owner_screenshot(step_id: str, request: Request):
        owner(request)
        path = store.screenshot(step_id)
        return FileResponse(path, media_type="image/png" if path.suffix == ".png" else "image/jpeg",
                            headers={"Cache-Control": "private, no-store"})

    @app.post("/api/factory/surfer/owner/sessions/{session_id}/stop")
    def surfer_owner_stop(session_id: str, request: Request):
        owner(request)
        return {"session": store.stop(session_id, by="owner", reason="stopped_by_owner")}

    @app.get("/api/factory/surfer/owner/audit")
    def surfer_owner_audit(request: Request, limit: int = 100):
        owner(request)
        return {"audit": store.audit_tail(limit)}
