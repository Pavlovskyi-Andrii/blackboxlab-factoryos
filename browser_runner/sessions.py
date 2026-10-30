"""T-560-B: opaque credential/session references, isolation and human takeover.

Secrets never appear in plans, logs, results, checkpoints or persisted registry files.
A ``credential_ref`` (``vault://...``) is resolved only at execution time through a
``CredentialVault`` scoped to workspace + provider + account binding; the resolved
value is wrapped in ``SecretValue``, which never renders its content. A ``session_ref``
(``session://...``) is only usable by the exact binding it was registered for.

Challenge pages (2FA/CAPTCHA/security/consent/lock) stop the run at ``waiting_human``
and persist a redacted checkpoint. Resume requires owner authorization, is single-use,
and continues after the last completed step so irreversible steps are never replayed.
No network, browser or real vault backend is touched by this module.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import os
from pathlib import Path
import secrets as _secrets
import time
from typing import Any, Callable, Dict, Mapping, Optional, Protocol, Tuple
from urllib.parse import urlsplit

from .core import (
    REDACTED, BrowserActionPlan, BrowserActionResult, PolicyError, _needs_approval,
    approval_matches, canonical_payload_hash, redact, validate_plan,
)


SESSION_REF_PREFIX = "session://"
CREDENTIAL_REF_PREFIX = "vault://"
CHALLENGE_REASONS = frozenset({"2fa", "captcha", "security_challenge", "consent", "account_locked"})
# Only these credential fields may be resolved by a worker. One-time codes, TOTP seeds,
# recovery codes and cookies are human-only: the worker must never read them.
RESOLVABLE_SECRET_KINDS = frozenset({"username", "password"})
IRREVERSIBLE_STEPS = frozenset({"submit"})


class SessionIsolationError(PermissionError):
    """Session/credential reference is not valid for this workspace/account binding."""


class VaultError(PermissionError):
    """Credential reference could not be resolved within its scope."""


def _valid_ref(ref: str, prefix: str) -> bool:
    return (
        isinstance(ref, str) and ref.startswith(prefix) and len(ref) > len(prefix)
        and len(ref) <= 256 and not any(ch.isspace() for ch in ref)
    )


def _atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, sort_keys=True, indent=2)
    os.replace(str(tmp), str(path))


class SecretValue:
    """Resolved secret; renders as redacted everywhere except an explicit reveal()."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        if not isinstance(value, str) or not value:
            raise VaultError("empty secret")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return REDACTED

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("SecretValue cannot be serialized")


class CredentialVault(Protocol):
    def resolve(self, credential_ref: str, *, workspace_id: str, provider: str,
                account_binding_id: str, kind: str) -> SecretValue: ...


class InMemoryVault:
    """Deterministic vault for tests/dev. Real backends implement CredentialVault."""

    def __init__(self):
        self._entries: Dict[str, Tuple[Tuple[str, str, str], Dict[str, str]]] = {}

    def __repr__(self) -> str:
        return f"InMemoryVault(refs={len(self._entries)})"

    def put(self, credential_ref: str, *, workspace_id: str, provider: str,
            account_binding_id: str, values: Mapping[str, str]) -> None:
        if not _valid_ref(credential_ref, CREDENTIAL_REF_PREFIX):
            raise VaultError("only opaque vault:// references are accepted")
        if not all((workspace_id, provider, account_binding_id)):
            raise VaultError("workspace, provider and account binding are required")
        scope = (workspace_id, provider, account_binding_id)
        existing = self._entries.get(credential_ref)
        if existing and existing[0] != scope:
            raise VaultError("credential_ref already scoped to another binding")
        self._entries[credential_ref] = (scope, dict(values))

    def resolve(self, credential_ref: str, *, workspace_id: str, provider: str,
                account_binding_id: str, kind: str) -> SecretValue:
        if kind not in RESOLVABLE_SECRET_KINDS:
            raise VaultError(f"credential kind not resolvable by worker: {kind}")
        entry = self._entries.get(credential_ref)
        if entry is None or entry[0] != (workspace_id, provider, account_binding_id):
            # Same message for missing and out-of-scope refs: no existence oracle.
            raise VaultError("credential_ref not available for this binding")
        value = entry[1].get(kind)
        if not value:
            raise VaultError(f"credential kind missing: {kind}")
        return SecretValue(value)


@dataclass(frozen=True)
class SessionBinding:
    workspace_id: str
    provider: str
    account_binding_id: str
    session_ref: str
    active: bool = True


class SessionRegistry:
    """Opaque session refs isolated per workspace + provider + account binding.

    When ``path`` is given the registry persists (refs only, never session material),
    so a session handoff survives a worker restart.
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._sessions: Dict[Tuple[str, str, str], SessionBinding] = {}
        if self._path and self._path.exists():
            for item in json.loads(self._path.read_text(encoding="utf-8")):
                binding = SessionBinding(**item)
                self._check(binding)
                self._sessions[self._key(binding)] = binding

    @staticmethod
    def _key(binding: SessionBinding) -> Tuple[str, str, str]:
        return (binding.workspace_id, binding.provider, binding.account_binding_id)

    @staticmethod
    def _check(binding: SessionBinding) -> None:
        if not all((binding.workspace_id, binding.provider, binding.account_binding_id)):
            raise ValueError("workspace, provider and account binding are required")
        if not _valid_ref(binding.session_ref, SESSION_REF_PREFIX):
            raise ValueError("only opaque session references are accepted")

    def _save(self) -> None:
        if self._path:
            _atomic_write_json(self._path, [asdict(b) for b in self._sessions.values()])

    def bind(self, binding: SessionBinding) -> None:
        self._check(binding)
        key = self._key(binding)
        for other_key, other in self._sessions.items():
            if other_key != key and other.session_ref == binding.session_ref:
                raise SessionIsolationError("session_ref already bound to another workspace/account")
        self._sessions[key] = binding
        self._save()

    def resolve(self, workspace_id: str, provider: str, account_binding_id: str) -> Optional[str]:
        binding = self._sessions.get((workspace_id, provider, account_binding_id))
        return binding.session_ref if binding and binding.active else None

    def resolve_for_plan(self, plan: BrowserActionPlan) -> str:
        bound = self.resolve(plan.workspace_id, plan.provider, plan.account_binding_id)
        if not bound or bound != plan.session_ref:
            raise SessionIsolationError("session_ref not bound to this workspace/account")
        return bound

    def disconnect(self, workspace_id: str, provider: str, account_binding_id: str) -> None:
        key = (workspace_id, provider, account_binding_id)
        if key in self._sessions:
            # Keep the inactive record for audit history; it never resolves again.
            self._sessions[key] = replace(self._sessions[key], active=False)
            self._save()


@dataclass(frozen=True)
class Checkpoint:
    plan_id: str
    workspace_id: str
    account_binding_id: str
    completed_steps: int
    payload_hash: str
    reason: str
    state: str = "waiting_human"
    checkpoint_id: str = ""
    provider: str = ""
    site: str = ""
    step_index: int = 0
    step_type: str = ""
    irreversible_done: Tuple[int, ...] = ()
    created_at: float = 0.0


def _site(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "")[:253]
    except ValueError:
        return ""


def challenge_checkpoint(plan_id: str, workspace_id: str, account_binding_id: str,
                         completed_steps: int, payload_hash: str, reason: str, *,
                         provider: str = "", site: str = "", step_type: str = "",
                         irreversible_done: Tuple[int, ...] = ()) -> Checkpoint:
    if reason not in CHALLENGE_REASONS:
        raise ValueError("unsupported challenge reason")
    if completed_steps < 0 or not payload_hash:
        raise ValueError("invalid checkpoint")
    if any(i < 1 or i > completed_steps for i in irreversible_done):
        raise ValueError("irreversible steps must be within completed steps")
    return Checkpoint(
        plan_id, workspace_id, account_binding_id, completed_steps, payload_hash, reason,
        checkpoint_id=f"cp_{_secrets.token_hex(8)}", provider=provider, site=_site(site),
        step_index=completed_steps + 1, step_type=step_type,
        irreversible_done=tuple(sorted(set(irreversible_done))), created_at=round(time.time(), 3),
    )


def authorize_resume(checkpoint: Checkpoint, *, owner_authorized: bool,
                     workspace_id: str, account_binding_id: str, payload_hash: str) -> Checkpoint:
    if not owner_authorized:
        raise PermissionError("human authorization required")
    if (checkpoint.workspace_id, checkpoint.account_binding_id, checkpoint.payload_hash) != (
        workspace_id, account_binding_id, payload_hash
    ):
        raise PermissionError("checkpoint binding or payload changed")
    if checkpoint.state != "waiting_human":
        raise PermissionError("checkpoint is not waiting")
    return replace(checkpoint, state="resumed")


class CheckpointStore:
    """Redacted takeover checkpoints. waiting_human -> resumed -> consumed, single-use."""

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path else None
        self._items: Dict[str, Checkpoint] = {}
        if self._path and self._path.exists():
            for item in json.loads(self._path.read_text(encoding="utf-8")):
                item["irreversible_done"] = tuple(item.get("irreversible_done") or ())
                cp = Checkpoint(**item)
                self._items[cp.checkpoint_id] = cp

    def _save(self) -> None:
        if self._path:
            _atomic_write_json(self._path, [asdict(cp) for cp in self._items.values()])

    def save(self, checkpoint: Checkpoint) -> None:
        if not checkpoint.checkpoint_id or checkpoint.checkpoint_id in self._items:
            raise ValueError("checkpoint id missing or already stored")
        self._items[checkpoint.checkpoint_id] = checkpoint
        self._save()

    def get(self, checkpoint_id: str) -> Optional[Checkpoint]:
        return self._items.get(checkpoint_id)

    def waiting(self, workspace_id: str) -> Tuple[Checkpoint, ...]:
        return tuple(cp for cp in self._items.values()
                     if cp.workspace_id == workspace_id and cp.state == "waiting_human")

    def resume(self, checkpoint_id: str, *, owner_authorized: bool, workspace_id: str,
               account_binding_id: str, payload_hash: str) -> Checkpoint:
        cp = self._items.get(checkpoint_id)
        if cp is None:
            raise PermissionError("unknown checkpoint")
        resumed = authorize_resume(cp, owner_authorized=owner_authorized, workspace_id=workspace_id,
                                   account_binding_id=account_binding_id, payload_hash=payload_hash)
        self._items[checkpoint_id] = resumed
        self._save()
        return resumed

    def consume(self, checkpoint_id: str) -> Checkpoint:
        cp = self._items.get(checkpoint_id)
        if cp is None or cp.state != "resumed":
            raise PermissionError("checkpoint not authorized for resume")
        consumed = replace(cp, state="consumed")
        self._items[checkpoint_id] = consumed
        self._save()
        return cp


ChallengeProbe = Callable[[int, Mapping[str, Any]], str]


def _blocked(plan: BrowserActionPlan, reason: str, completed: int = 0) -> BrowserActionResult:
    return BrowserActionResult(plan_id=plan.plan_id, status="blocked",
                               completed_steps=completed, blocker_reason=reason)


def _resolve_auth(plan: BrowserActionPlan, sessions: SessionRegistry,
                  vault: Optional[CredentialVault]) -> Dict[str, SecretValue]:
    kinds = set()
    for step in plan.steps:
        if "credential_field" in step:
            kind = step["credential_field"]
            if step.get("type") != "fill" or "value" in step:
                raise PolicyError("credential_field is only allowed on fill steps without value")
            if kind not in RESOLVABLE_SECRET_KINDS:
                raise PolicyError(f"credential kind not resolvable by worker: {kind}")
            kinds.add(kind)
    if plan.session_ref:
        sessions.resolve_for_plan(plan)
        if kinds:
            raise PolicyError("session_ref plans cannot request credential fields")
        return {}
    if not _valid_ref(plan.credential_ref, CREDENTIAL_REF_PREFIX):
        raise SessionIsolationError("credential_ref must be an opaque vault:// reference")
    if vault is None:
        raise VaultError("credential vault unavailable")
    return {
        kind: vault.resolve(plan.credential_ref, workspace_id=plan.workspace_id,
                            provider=plan.provider, account_binding_id=plan.account_binding_id,
                            kind=kind)
        for kind in sorted(kinds)
    }


def run_mock_resumable(plan: BrowserActionPlan, *, sessions: SessionRegistry,
                       checkpoints: CheckpointStore, vault: Optional[CredentialVault] = None,
                       challenge_probe: Optional[ChallengeProbe] = None,
                       resume_checkpoint_id: str = "") -> BrowserActionResult:
    """Deterministic session-aware executor with human takeover; no browser/network.

    ``challenge_probe(index, step)`` stands in for page inspection before each step and
    returns a challenge reason or "". Resume state is read from the trusted store, never
    from the caller, and is consumed before any step runs (at-most-once).
    """
    try:
        validate_plan(plan)
    except PolicyError as exc:
        return _blocked(plan, str(exc))
    if _needs_approval(plan) and not approval_matches(plan):
        return _blocked(plan, "matching human approval snapshot and payload hash required")
    payload_hash = canonical_payload_hash(plan)

    try:
        credentials = _resolve_auth(plan, sessions, vault)
    except (PolicyError, PermissionError) as exc:
        return _blocked(plan, str(exc))

    start, irreversible_done = 0, ()
    if resume_checkpoint_id:
        cp = checkpoints.get(resume_checkpoint_id)
        if cp is None or (cp.plan_id, cp.workspace_id, cp.account_binding_id, cp.payload_hash) != (
            plan.plan_id, plan.workspace_id, plan.account_binding_id, payload_hash
        ):
            return _blocked(plan, "checkpoint does not match this plan/binding/payload")
        try:
            cp = checkpoints.consume(resume_checkpoint_id)
        except PermissionError as exc:
            return _blocked(plan, str(exc))
        start, irreversible_done = cp.completed_steps, tuple(cp.irreversible_done)

    log = [{"index": i, "type": plan.steps[i - 1].get("type"), "status": "already_completed"}
           for i in range(1, start + 1)]
    final_url = next((str(s.get("url") or "") for s in reversed(plan.steps[:start])
                      if s.get("type") == "navigate"), "")
    done = list(irreversible_done)
    for index in range(start + 1, len(plan.steps) + 1):
        step = plan.steps[index - 1]
        kind = step.get("type")
        if index in done:  # defense in depth: never re-run an irreversible step
            return _blocked(plan, "irreversible_step_replay_blocked", index - 1)
        reason = challenge_probe(index, step) if challenge_probe else ""
        if reason:
            cp = challenge_checkpoint(
                plan.plan_id, plan.workspace_id, plan.account_binding_id, index - 1, payload_hash,
                reason, provider=plan.provider, site=final_url, step_type=str(kind),
                irreversible_done=tuple(done),
            )
            checkpoints.save(cp)
            log.append({"type": "checkpoint", "status": "waiting_human",
                        "checkpoint_id": cp.checkpoint_id, "site": cp.site,
                        "step_index": cp.step_index, "step_type": cp.step_type, "reason": reason})
            return BrowserActionResult(
                plan_id=plan.plan_id, status="waiting_human", completed_steps=index - 1,
                action_log=tuple(log), final_url=final_url, blocker_reason=reason, executor="mock",
            )
        if "credential_field" in step:
            # Simulated fill: the secret is used here only and never logged.
            credentials[step["credential_field"]].reveal()
        if kind == "navigate":
            final_url = str(step.get("url") or "")
        if kind in IRREVERSIBLE_STEPS:
            done.append(index)
        log.append({"index": index, "type": kind, "input": redact(dict(step)), "status": "simulated"})

    return BrowserActionResult(
        plan_id=plan.plan_id, status="done", completed_steps=len(plan.steps),
        action_log=tuple(log), final_url=final_url, executor="mock",
    )
