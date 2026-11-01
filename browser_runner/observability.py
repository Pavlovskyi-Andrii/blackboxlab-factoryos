"""T-560-E: read-only Browser Runner view for Worker Results and Trace Viewer.

``build_run_view`` turns a plan + result (+ optional checkpoint) into a display dict.
It only reports evidence that the plan/result already carry. It never adds a step,
receipt, screenshot or status. Values are whitelisted per field, not copied:
- fill/select values are shown as character counts only;
- credential/session refs are shown as their kind, never as the value;
- URLs lose userinfo, query and fragment;
- artifact refs must match the private ``artifact://browser/<name>`` form;
- a receipt is shown only when the result status is ``done``.
"""
from __future__ import annotations

import re
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

from .core import (
    IRREVERSIBLE_ACTIONS,
    REDACTED,
    BrowserActionPlan,
    BrowserActionResult,
    approval_matches,
    canonical_payload_hash,
    redact,
)

RESULT_STATUSES = frozenset({"planned", "running", "waiting_human", "done", "blocked", "failed"})
STOP_STATUSES = frozenset({"waiting_human", "blocked", "failed"})
STEP_LOG_STATES = frozenset({"done", "simulated", "already_completed"})
VIEW_VERSION = 1

_ARTIFACT_RE = re.compile(r"^artifact://browser/[A-Za-z0-9][A-Za-z0-9._-]{0,119}$")
_HEX_RE = re.compile(r"^[0-9a-f]{16,64}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,119}$")
_SECRET_PAIR_RE = re.compile(
    r"(?i)\b(password|passwd|secret|token|cookie|authorization|api[_-]?key|session|sid|otp)\b\s*[=:]\s*\S+"
)
_AUTH_RE = re.compile(r"(?i)\b(bearer|basic)\s+\S+")
_LONG_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-+/=.]{32,}")
_LOG_INT_KEYS = ("index", "step_index", "completed_steps", "text_chars")
_LOG_TEXT_KEYS = ("type", "status", "step_type", "reason")


def scrub_text(value: Any, limit: int = 200) -> str:
    """Free text (reasons, selectors) with secret-looking material replaced."""
    text = str(value or "").replace("\n", " ").strip()
    text = _AUTH_RE.sub(REDACTED, text)
    text = _SECRET_PAIR_RE.sub(lambda m: f"{m.group(1)}={REDACTED}", text)
    text = _LONG_TOKEN_RE.sub(REDACTED, text)
    return text[:limit]


def safe_url(value: Any) -> str:
    """scheme://host[:port]/path only; anything else (or non-http) becomes empty."""
    try:
        parts = urlsplit(str(value or ""))
        host, port = parts.hostname, parts.port
    except ValueError:
        return ""
    if parts.scheme not in {"http", "https"} or not host:
        return ""
    netloc = host + (f":{port}" if port else "")
    path = "/".join(scrub_text(seg, 80) for seg in parts.path.split("/"))[:200]
    return f"{parts.scheme}://{netloc}{path}"


def _safe_id(value: Any) -> str:
    text = str(value or "")
    return text if _ID_RE.match(text) and not _LONG_TOKEN_RE.fullmatch(text) else ""


def _safe_hash(value: Any) -> str:
    text = str(value or "")
    return text if _HEX_RE.match(text) else ""


def _int(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _step_summary(index: int, step: Mapping[str, Any]) -> dict[str, Any]:
    kind = str(step.get("type") or "")
    out: dict[str, Any] = {"index": index, "type": kind}
    if kind == "navigate":
        out["target"] = safe_url(step.get("url"))
    elif step.get("selector"):
        out["target"] = scrub_text(step.get("selector"), 160)
    if kind in {"fill", "select"} and isinstance(step.get("value"), str):
        out["value_chars"] = len(step["value"])
    if kind == "upload":
        name = str(step.get("file") or step.get("path") or "").replace("\\", "/").rsplit("/", 1)[-1]
        out["file"] = scrub_text(name, 120)
    if step.get("credential_field"):
        out["uses_vault_credential"] = True
    return out


def _log_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key in _LOG_INT_KEYS:
        if _int(entry.get(key)) is not None:
            out[key] = entry[key]
    for key in _LOG_TEXT_KEYS:
        if entry.get(key):
            out[key] = scrub_text(entry[key], 120)
    if entry.get("site"):
        out["site"] = scrub_text(entry["site"], 253)
    for key in ("text_sha256", "payload_hash"):
        if _safe_hash(entry.get(key)):
            out[key] = entry[key]
    if _safe_id(entry.get("checkpoint_id")):
        out["checkpoint_id"] = entry["checkpoint_id"]
    if isinstance(entry.get("artifact_ref"), str) and _ARTIFACT_RE.match(entry["artifact_ref"]):
        out["artifact_ref"] = entry["artifact_ref"]
    return out


def _checkpoint_view(checkpoint: Any, log: list[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if checkpoint is not None:
        return {
            "checkpoint_id": _safe_id(getattr(checkpoint, "checkpoint_id", "")),
            "state": scrub_text(getattr(checkpoint, "state", ""), 40),
            "site": scrub_text(getattr(checkpoint, "site", ""), 253),
            "step_index": _int(getattr(checkpoint, "step_index", None)),
            "step_type": scrub_text(getattr(checkpoint, "step_type", ""), 40),
            "reason": scrub_text(getattr(checkpoint, "reason", ""), 120),
            "completed_steps": _int(getattr(checkpoint, "completed_steps", None)),
            "created_at": getattr(checkpoint, "created_at", None) or None,
        }
    entry = next((e for e in reversed(log) if e.get("type") == "checkpoint"), None)
    if entry is None:
        return None
    return {
        "checkpoint_id": entry.get("checkpoint_id", ""),
        "state": entry.get("status", "waiting_human"),
        "site": entry.get("site", ""),
        "step_index": entry.get("step_index"),
        "step_type": entry.get("step_type", ""),
        "reason": entry.get("reason", ""),
        "completed_steps": entry.get("completed_steps"),
        "created_at": None,
    }


def build_run_view(
    plan: BrowserActionPlan,
    result: BrowserActionResult,
    checkpoint: Any = None,
    *,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
) -> dict[str, Any]:
    if result.plan_id != plan.plan_id:
        raise ValueError("result does not belong to this plan")
    warnings: list[str] = []
    status = result.status if result.status in RESULT_STATUSES else "unknown"
    if status == "unknown":
        warnings.append("unknown_result_status")
    total = len(plan.steps)
    completed = _int(result.completed_steps)
    if completed is None or completed > total:
        warnings.append("completed_steps_out_of_range")
        completed = min(max(completed or 0, 0), total)

    log = [_log_entry(e) for e in result.action_log if isinstance(e, Mapping)]
    by_index = {e["index"]: e for e in log if "index" in e and e.get("type") != "checkpoint"}
    stopped_at = completed + 1 if status in STOP_STATUSES and completed < total else None
    steps = []
    for index, step in enumerate(plan.steps, 1):
        item = _step_summary(index, step)
        entry = by_index.get(index)
        if entry and entry.get("status") in STEP_LOG_STATES:
            item["state"] = entry["status"]
            for key in ("text_chars", "text_sha256", "artifact_ref"):
                if key in entry:
                    item[key] = entry[key]
        elif index == stopped_at:
            item["state"] = "stopped"
        elif status == "running" and index == completed + 1:
            item["state"] = "running"
        else:
            item["state"] = "pending"
        steps.append(item)

    refs = [r for r in result.artifacts if isinstance(r, str)]
    refs += [e["artifact_ref"] for e in log if "artifact_ref" in e]
    artifacts = []
    for ref in refs:
        if _ARTIFACT_RE.match(ref) and ref not in artifacts:
            artifacts.append(ref)
    rejected = sum(1 for r in set(refs) if not _ARTIFACT_RE.match(r))
    if rejected:
        warnings.append("artifact_refs_rejected")

    receipt = ""
    if result.external_receipt:
        if status == "done":
            raw = str(result.external_receipt)
            receipt = safe_url(raw) if "://" in raw else scrub_text(raw, 160)
        else:
            warnings.append("receipt_ignored_status_not_done")

    first_nav = next((s.get("url") for s in plan.steps if s.get("type") == "navigate"), "")
    needs_approval = plan.action_class in IRREVERSIBLE_ACTIONS or any(s.get("type") == "submit" for s in plan.steps)
    view = {
        "view_version": VIEW_VERSION,
        "plan": {
            "plan_id": scrub_text(plan.plan_id, 120),
            "workspace_id": scrub_text(plan.workspace_id, 120),
            "provider": scrub_text(plan.provider, 60),
            "site": (urlsplit(safe_url(first_nav)).hostname or "") if first_nav else "",
            "account_binding_id": scrub_text(plan.account_binding_id, 120),
            "action_class": plan.action_class,
            "auth_kind": "session_ref" if plan.session_ref else ("credential_ref" if plan.credential_ref else "none"),
            "step_count": total,
            "max_steps": plan.max_steps,
            "timeout_seconds": plan.timeout_seconds,
            "payload_hash": canonical_payload_hash(plan),
            "approval": {
                "required": needs_approval,
                "snapshot_id": scrub_text(plan.approval_snapshot_id, 120),
                "payload_hash_matches": approval_matches(plan),
            },
        },
        "status": status,
        "executor": scrub_text(result.executor, 40),
        "progress": {
            "completed": completed,
            "total": total,
            "percent": round(100 * completed / total) if total else 0,
        },
        "steps": steps,
        "blocker": (
            {"reason": scrub_text(result.blocker_reason, 200), "stopped_at_step": stopped_at,
             "stopped_step_type": steps[stopped_at - 1]["type"] if stopped_at else ""}
            if status in STOP_STATUSES or result.blocker_reason else None
        ),
        "checkpoint": _checkpoint_view(checkpoint, log) if (checkpoint is not None or status == "waiting_human") else None,
        "action_log": log,
        "final_url": safe_url(result.final_url),
        "artifacts": artifacts,
        "receipt": receipt or None,
        "receipt_observed": bool(receipt),
        "started_at": started_at,
        "finished_at": finished_at,
        "warnings": warnings,
    }
    # Defence in depth: key-based redaction over the whole view.
    return redact(view)


def run_view_title(view: Mapping[str, Any]) -> str:
    plan = view.get("plan") or {}
    return " · ".join(x for x in (str(plan.get("provider") or "browser"), str(plan.get("action_class") or ""),
                                  str(view.get("status") or "")) if x)
