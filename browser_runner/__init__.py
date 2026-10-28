"""Provider-neutral, fail-closed browser action runner contracts."""
from .playwright_executor import BrowserRuntimePolicy, run_playwright
from .core import (
    ACTION_CLASSES,
    ALLOWED_STEPS,
    BrowserActionPlan,
    BrowserActionResult,
    PolicyError,
    approval_matches,
    canonical_payload_hash,
    redact,
    run_mock,
    validate_plan,
)

__all__ = [
    "ACTION_CLASSES",
    "ALLOWED_STEPS",
    "BrowserActionPlan",
    "BrowserActionResult",
    "PolicyError",
    "approval_matches",
    "canonical_payload_hash",
    "redact",
    "run_mock",
    "validate_plan",
    "BrowserRuntimePolicy",
    "run_playwright",
]
