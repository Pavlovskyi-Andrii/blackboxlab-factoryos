"""T-560-B: opaque session bindings and human takeover checkpoints.

No credentials are resolved or persisted by this module.
"""
from dataclasses import dataclass, replace
from typing import Mapping


@dataclass(frozen=True)
class SessionBinding:
    workspace_id: str
    provider: str
    account_binding_id: str
    session_ref: str
    active: bool = True


@dataclass(frozen=True)
class Checkpoint:
    plan_id: str
    workspace_id: str
    account_binding_id: str
    completed_steps: int
    payload_hash: str
    reason: str
    state: str = "waiting_human"


class SessionRegistry:
    def __init__(self):
        self._sessions: dict[tuple[str, str, str], SessionBinding] = {}

    def bind(self, binding: SessionBinding) -> None:
        if not all((binding.workspace_id, binding.provider, binding.account_binding_id)):
            raise ValueError("workspace, provider and account binding are required")
        if not binding.session_ref.startswith("session://"):
            raise ValueError("only opaque session references are accepted")
        self._sessions[(binding.workspace_id, binding.provider, binding.account_binding_id)] = binding

    def resolve(self, workspace_id: str, provider: str, account_binding_id: str) -> str | None:
        binding = self._sessions.get((workspace_id, provider, account_binding_id))
        return binding.session_ref if binding and binding.active else None

    def disconnect(self, workspace_id: str, provider: str, account_binding_id: str) -> None:
        key = (workspace_id, provider, account_binding_id)
        if key in self._sessions:
            self._sessions[key] = replace(self._sessions[key], active=False)


def challenge_checkpoint(plan_id: str, workspace_id: str, account_binding_id: str,
                         completed_steps: int, payload_hash: str, reason: str) -> Checkpoint:
    if reason not in {"2fa", "captcha", "security_challenge", "consent", "account_locked"}:
        raise ValueError("unsupported challenge reason")
    if completed_steps < 0 or not payload_hash:
        raise ValueError("invalid checkpoint")
    return Checkpoint(plan_id, workspace_id, account_binding_id, completed_steps, payload_hash, reason)


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
