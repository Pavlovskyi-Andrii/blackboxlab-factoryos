"""T-560-A: provider-neutral browser runner contracts and fail-closed policy.

This module intentionally performs no network or browser calls. It defines the stable
plan/result contract, validates bounded actions, rejects plaintext secret material, binds
approval to an immutable payload hash, and provides a deterministic mock executor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse


ALLOWED_STEPS = frozenset(
    {"navigate", "click", "fill", "select", "upload", "wait_for", "extract", "screenshot", "submit"}
)
ACTION_CLASSES = frozenset({"read", "draft", "upload", "publish", "send", "destructive"})
IRREVERSIBLE_ACTIONS = frozenset({"publish", "send", "destructive"})
REDACTED = "***REDACTED***"
_MAX_STEPS_HARD = 64
_MAX_TIMEOUT_SECONDS = 300
_MAX_RETRIES = 3

_SECRET_KEY_RE = re.compile(r"(?:^|_)(password|passwd|secret|token|cookie|authorization|api[_-]?key|recovery[_-]?code)(?:$|_)", re.I)
_SECRET_STRING_RE = re.compile(r"^\s*(?:bearer|basic)\s+\S+", re.I)


class PolicyError(ValueError):
    """Plan is malformed or violates the zero-secret/bounded-action policy."""


@dataclass(frozen=True)
class BrowserActionPlan:
    plan_id: str
    workspace_id: str
    provider: str
    account_binding_id: str
    action_class: str
    steps: tuple[Mapping[str, Any], ...]
    credential_ref: str = ""
    session_ref: str = ""
    timeout_seconds: int = 60
    max_steps: int = 20
    max_retries: int = 0
    approval_snapshot_id: str = ""
    approved_payload_hash: str = ""


@dataclass(frozen=True)
class BrowserActionResult:
    plan_id: str
    status: str
    completed_steps: int = 0
    action_log: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    final_url: str = ""
    external_receipt: str = ""
    blocker_reason: str = ""
    executor: str = "mock"


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    if lowered.endswith("_ref") or lowered.endswith("_id"):
        return False
    return bool(_SECRET_KEY_RE.search(lowered))


def redact(value: Any) -> Any:
    """Recursively redact secret-like fields and authorization strings for evidence/logging."""
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            out[key_s] = REDACTED if _is_secret_key(key_s) else redact(item)
        return out
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str) and _SECRET_STRING_RE.match(value):
        return REDACTED
    return value


def _contains_plaintext_secret(value: Any, path: str = "") -> str:
    """Return the first secret-like path containing literal material, else empty string."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_s = str(key)
            child = f"{path}.{key_s}" if path else key_s
            if _is_secret_key(key_s) and item not in ("", None):
                return child
            hit = _contains_plaintext_secret(item, child)
            if hit:
                return hit
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            hit = _contains_plaintext_secret(item, f"{path}[{index}]")
            if hit:
                return hit
    elif isinstance(value, str) and _SECRET_STRING_RE.match(value):
        return path or "<string>"
    return ""


def _canonical_payload(plan: BrowserActionPlan) -> dict[str, Any]:
    """Fields that approval binds to; approval metadata itself is deliberately excluded."""
    return {
        "plan_id": plan.plan_id,
        "workspace_id": plan.workspace_id,
        "provider": plan.provider,
        "account_binding_id": plan.account_binding_id,
        "action_class": plan.action_class,
        "steps": [dict(step) for step in plan.steps],
        "credential_ref": plan.credential_ref,
        "session_ref": plan.session_ref,
        "timeout_seconds": plan.timeout_seconds,
        "max_steps": plan.max_steps,
        "max_retries": plan.max_retries,
    }


def canonical_payload_hash(plan: BrowserActionPlan) -> str:
    payload = json.dumps(_canonical_payload(plan), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def approval_matches(plan: BrowserActionPlan) -> bool:
    return bool(
        plan.approval_snapshot_id.strip()
        and plan.approved_payload_hash.strip()
        and plan.approved_payload_hash == canonical_payload_hash(plan)
    )


def _validate_url(url: Any) -> None:
    if not isinstance(url, str) or not url.strip():
        raise PolicyError("navigate step requires a non-empty url")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise PolicyError("navigate url must be absolute http(s)")


def validate_plan(plan: BrowserActionPlan) -> None:
    for name in ("plan_id", "workspace_id", "provider", "account_binding_id"):
        if not getattr(plan, name).strip():
            raise PolicyError(f"{name} is required")
    if plan.action_class not in ACTION_CLASSES:
        raise PolicyError(f"unsupported action_class: {plan.action_class!r}")
    if bool(plan.credential_ref) == bool(plan.session_ref):
        raise PolicyError("exactly one of credential_ref or session_ref is required")
    if not 1 <= int(plan.timeout_seconds) <= _MAX_TIMEOUT_SECONDS:
        raise PolicyError("timeout_seconds out of bounds")
    if not 1 <= int(plan.max_steps) <= _MAX_STEPS_HARD:
        raise PolicyError("max_steps out of bounds")
    if not 0 <= int(plan.max_retries) <= _MAX_RETRIES:
        raise PolicyError("max_retries out of bounds")
    if len(plan.steps) > plan.max_steps:
        raise PolicyError("plan exceeds max_steps")
    for index, step in enumerate(plan.steps):
        if not isinstance(step, Mapping):
            raise PolicyError(f"step {index} must be a mapping")
        kind = step.get("type")
        if kind not in ALLOWED_STEPS:
            raise PolicyError(f"unsupported step type at {index}: {kind!r}")
        if kind == "navigate":
            _validate_url(step.get("url"))
        secret_path = _contains_plaintext_secret(step)
        if secret_path:
            raise PolicyError(f"plaintext secret material is forbidden in plan steps: {secret_path}")


def _needs_approval(plan: BrowserActionPlan) -> bool:
    return plan.action_class in IRREVERSIBLE_ACTIONS or any(step.get("type") == "submit" for step in plan.steps)


def run_mock(plan: BrowserActionPlan) -> BrowserActionResult:
    """Deterministically execute a plan without network/browser side effects."""
    try:
        validate_plan(plan)
    except PolicyError as exc:
        return BrowserActionResult(plan_id=plan.plan_id, status="blocked", blocker_reason=str(exc))

    if _needs_approval(plan) and not approval_matches(plan):
        return BrowserActionResult(
            plan_id=plan.plan_id,
            status="blocked",
            blocker_reason="matching human approval snapshot and payload hash required",
        )

    log: list[Mapping[str, Any]] = []
    final_url = ""
    for index, step in enumerate(plan.steps, start=1):
        if step.get("type") == "navigate":
            final_url = str(step.get("url") or "")
        log.append({"index": index, "type": step.get("type"), "input": redact(dict(step)), "status": "simulated"})

    return BrowserActionResult(
        plan_id=plan.plan_id,
        status="done",
        completed_steps=len(plan.steps),
        action_log=tuple(log),
        final_url=final_url,
        executor="mock",
    )
