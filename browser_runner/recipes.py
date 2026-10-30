"""T-560-C: generic, provider-neutral browser recipes.

A recipe turns a small declarative description of a web form into a bounded
`BrowserActionPlan`. Recipes never carry credentials, never choose their own
origin allowlist (that stays in the trusted `BrowserRuntimePolicy`) and never
add a submit step unless asked; a submit step makes the plan approval-gated.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .core import BrowserActionPlan, PolicyError


def generic_form_recipe(
    *,
    plan_id: str,
    workspace_id: str,
    account_binding_id: str,
    session_ref: str,
    start_url: str,
    fields: Sequence[Mapping[str, Any]] = (),
    uploads: Sequence[Mapping[str, Any]] = (),
    preview_selector: str = "",
    ready_selector: str = "",
    extract_selectors: Sequence[str] = (),
    screenshot: bool = True,
    submit_selector: str = "",
    provider: str = "generic",
    timeout_seconds: int = 60,
    max_steps: int = 20,
) -> BrowserActionPlan:
    """Build navigate → fill/select → upload → preview → wait → extract → screenshot.

    `fields` items are `{"selector": ..., "value": ...}` with optional
    `"kind": "select"` (default `fill`). `uploads` items are
    `{"selector": ..., "path": <relative to the trusted staging root>}`.
    A non-empty `submit_selector` appends a final `submit` step and marks the
    plan `publish`, so executors require a matching human approval for it.
    """
    steps: list[dict[str, Any]] = [{"type": "navigate", "url": start_url}]
    for item in fields:
        kind = item.get("kind", "fill")
        if kind not in {"fill", "select"} or set(item) - {"selector", "value", "kind"}:
            raise PolicyError("recipe_field_invalid")
        steps.append({"type": kind, "selector": item["selector"], "value": item["value"]})
    for item in uploads:
        if set(item) != {"selector", "path"}:
            raise PolicyError("recipe_upload_invalid")
        steps.append({"type": "upload", "selector": item["selector"], "path": item["path"]})
    if preview_selector:
        steps.append({"type": "click", "selector": preview_selector})
    if ready_selector:
        steps.append({"type": "wait_for", "selector": ready_selector})
    for selector in extract_selectors:
        steps.append({"type": "extract", "selector": selector})
    if screenshot:
        steps.append({"type": "screenshot"})
    action_class = "upload" if uploads else "draft"
    if submit_selector:
        steps.append({"type": "submit", "selector": submit_selector})
        action_class = "publish"
    return BrowserActionPlan(
        plan_id=plan_id, workspace_id=workspace_id, provider=provider,
        account_binding_id=account_binding_id, session_ref=session_ref,
        action_class=action_class, steps=tuple(steps),
        timeout_seconds=timeout_seconds, max_steps=max_steps,
    )
