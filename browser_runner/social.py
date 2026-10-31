"""T-560-D: social web draft recipes (X/Twitter, Instagram, Telegram web).

Fallback only, for when an official API/connector is unavailable. A recipe
prepares text/media in the site's composer up to the final submit boundary and
stops there. It never carries credentials: the session is looked up in the
``SessionRegistry`` by workspace + provider + account binding, so a caller can
neither pick another workspace's session nor smuggle a cookie/password in.

The final publish/send step is built separately by ``final_submit_plan`` as an
irreversible plan that needs a matching human approval snapshot. This module
deliberately has no helper that creates an approval; approval comes only from
the FactoryOS owner approval gate. The real Playwright executor still blocks
every submit until a trusted server-side approval verifier exists (T-560-C).

Default selectors are best-effort descriptions of each site's composer and have
not been verified against the live sites; trusted runner configuration can
override them per provider. The origin allowlist stays in the trusted
``BrowserRuntimePolicy``; a recipe never widens it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import PurePosixPath
import re
import time
from typing import Any, Callable, Mapping, Optional, Sequence

from .core import (
    BrowserActionPlan, BrowserActionResult, PolicyError, canonical_payload_hash, validate_plan,
)
from .playwright_executor import BrowserRuntimePolicy, run_playwright
from .sessions import CheckpointStore, SessionIsolationError, SessionRegistry, challenge_checkpoint


_MEDIA_TYPES = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".mp4", ".mov"})
_TELEGRAM_CHANNEL_RE = re.compile(r"@?[A-Za-z][A-Za-z0-9_]{3,31}")


@dataclass(frozen=True)
class SocialSite:
    provider: str
    origin: str
    max_text_chars: int
    max_media: int
    min_media: int
    submit_action_class: str
    selectors: Mapping[str, str]


SOCIAL_SITES: Mapping[str, SocialSite] = {
    "x": SocialSite(
        provider="x", origin="https://x.com", max_text_chars=280, max_media=4, min_media=0,
        submit_action_class="publish",
        selectors={
            "composer": '[data-testid="tweetTextarea_0"]',
            "media_input": 'input[data-testid="fileInput"]',
            "media_ready": '[data-testid="attachments"]',
            "submit": '[data-testid="tweetButton"]',
        },
    ),
    "instagram": SocialSite(
        provider="instagram", origin="https://www.instagram.com", max_text_chars=2200,
        max_media=10, min_media=1, submit_action_class="publish",
        selectors={
            "open_composer": 'svg[aria-label="New"]',
            "media_input": 'div[role="dialog"] input[type="file"]',
            "next": 'div[role="dialog"] div[role="button"]:has-text("Next")',
            "composer": 'div[role="dialog"] div[aria-label="Write a caption..."]',
            "submit": 'div[role="dialog"] div[role="button"]:has-text("Share")',
        },
    ),
    "telegram": SocialSite(
        provider="telegram", origin="https://web.telegram.org", max_text_chars=4096,
        max_media=10, min_media=0, submit_action_class="send",
        selectors={
            "composer": 'div.input-message-input[contenteditable="true"]',
            "media_input": 'input[type="file"][multiple]',
            "media_ready": ".popup-new-media",
            "media_caption": '.popup-new-media div.input-message-input[contenteditable="true"]',
            "submit": "button.btn-send",
            "media_submit": ".popup-new-media button.btn-primary",
        },
    ),
}
# Telegram captions on media are shorter than plain messages.
_TELEGRAM_MEDIA_CAPTION_CHARS = 1024


@dataclass(frozen=True)
class SocialDraft:
    """A draft-only plan plus the description of its (not yet included) final step."""

    provider: str
    plan: BrowserActionPlan
    submit_step: Mapping[str, Any]
    submit_action_class: str
    text_chars: int
    media_count: int


def _check_media(site: SocialSite, media: Sequence[str]) -> None:
    if not site.min_media <= len(media) <= site.max_media:
        raise PolicyError("social_media_count_out_of_bounds")
    for name in media:
        if not isinstance(name, str) or not name or len(name) > 240:
            raise PolicyError("social_media_path_invalid")
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or "\\" in name:
            raise PolicyError("social_media_must_be_relative_to_staging_root")
        if path.suffix.lower() not in _MEDIA_TYPES:
            raise PolicyError("social_media_type_disallowed")


def _steps(site: SocialSite, sel: Mapping[str, str], start_url: str, text: str,
           media: Sequence[str]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = [{"type": "navigate", "url": start_url}]
    uploads = [{"type": "upload", "selector": sel["media_input"], "path": m} for m in media]
    if site.provider == "x":
        steps.append({"type": "wait_for", "selector": sel["composer"]})
        if text:
            steps.append({"type": "fill", "selector": sel["composer"], "value": text})
        if uploads:
            steps += uploads + [{"type": "wait_for", "selector": sel["media_ready"]}]
    elif site.provider == "instagram":
        steps.append({"type": "click", "selector": sel["open_composer"]})
        # Instagram's flow: media first, then crop → filter → caption screens.
        steps += uploads
        steps += [{"type": "click", "selector": sel["next"]} for _ in range(2)]
        steps.append({"type": "wait_for", "selector": sel["composer"]})
        if text:
            steps.append({"type": "fill", "selector": sel["composer"], "value": text})
    else:  # telegram
        steps.append({"type": "wait_for", "selector": sel["composer"]})
        if uploads:
            steps += uploads + [{"type": "wait_for", "selector": sel["media_ready"]}]
            if text:
                steps.append({"type": "fill", "selector": sel["media_caption"], "value": text})
        elif text:
            steps.append({"type": "fill", "selector": sel["composer"], "value": text})
    steps.append({"type": "screenshot"})
    return steps


def social_draft_recipe(
    *,
    provider: str,
    plan_id: str,
    workspace_id: str,
    account_binding_id: str,
    sessions: SessionRegistry,
    text: str = "",
    media: Sequence[str] = (),
    telegram_channel: str = "",
    site_origin: str = "",
    selectors: Optional[Mapping[str, str]] = None,
    timeout_seconds: int = 120,
    max_steps: int = 24,
) -> SocialDraft:
    """Build a draft-only plan that stops right before the final publish/send click.

    ``media`` are paths relative to the trusted upload staging root.
    ``site_origin`` defaults to the provider's official origin; a different
    origin (fixtures) still has to be allowlisted by the trusted runtime policy.
    ``selectors`` may override known selector keys only (trusted runner config).
    """
    site = SOCIAL_SITES.get(provider)
    if site is None:
        raise PolicyError("social_provider_unsupported")
    session_ref = sessions.resolve(workspace_id, provider, account_binding_id)
    if not session_ref:
        raise SessionIsolationError("no active session bound to this workspace/provider/account")
    sel = dict(site.selectors)
    if selectors:
        if set(selectors) - set(sel):
            raise PolicyError("social_selector_key_unknown")
        sel.update(selectors)
    if not isinstance(text, str):
        raise PolicyError("social_text_invalid")
    media = tuple(media)
    _check_media(site, media)
    limit = site.max_text_chars
    if provider == "telegram" and media:
        limit = _TELEGRAM_MEDIA_CAPTION_CHARS
    if len(text) > limit:
        raise PolicyError("social_text_too_long")
    if not text and not media:
        raise PolicyError("social_draft_empty")

    if provider != "telegram" and telegram_channel:
        raise PolicyError("telegram_channel_only_for_telegram")
    origin = (site_origin or site.origin).rstrip("/")
    if provider == "x":
        start_url = origin + "/compose/tweet"
    elif provider == "instagram":
        start_url = origin + "/"
    else:
        if not _TELEGRAM_CHANNEL_RE.fullmatch(telegram_channel or ""):
            raise PolicyError("telegram_channel_handle_invalid")
        start_url = origin + "/k/#@" + telegram_channel.lstrip("@")

    plan = BrowserActionPlan(
        plan_id=plan_id, workspace_id=workspace_id, provider=provider,
        account_binding_id=account_binding_id, session_ref=session_ref,
        action_class="upload" if media else "draft",
        steps=tuple(_steps(site, sel, start_url, text, media)),
        timeout_seconds=timeout_seconds, max_steps=max_steps,
    )
    validate_plan(plan)  # rejects secret-like text (e.g. "Bearer …") and bounds
    submit_selector = sel["media_submit"] if provider == "telegram" and media else sel["submit"]
    return SocialDraft(
        provider=provider, plan=plan,
        submit_step={"type": "submit", "selector": submit_selector},
        submit_action_class=site.submit_action_class,
        text_chars=len(text), media_count=len(media),
    )


def final_submit_plan(draft: SocialDraft) -> BrowserActionPlan:
    """The same draft plus its final publish/send step, without any approval.

    The owner approval gate binds a snapshot to ``canonical_payload_hash`` of this
    plan; every executor refuses it until that approval matches exactly.
    """
    plan = draft.plan
    return replace(
        plan, plan_id=plan.plan_id + ":submit", action_class=draft.submit_action_class,
        steps=plan.steps + (dict(draft.submit_step),), max_steps=max(plan.max_steps, len(plan.steps) + 1),
        approval_snapshot_id="", approved_payload_hash="",
    )


def run_social_draft(
    draft: SocialDraft,
    *,
    policy: BrowserRuntimePolicy,
    sessions: SessionRegistry,
    checkpoints: Optional[CheckpointStore] = None,
    playwright_factory: Optional[Callable[[], Any]] = None,
    clock: Callable[[], float] = time.monotonic,
) -> BrowserActionResult:
    """Run a draft on the guarded browser executor; never the final submit.

    The session binding is re-checked at run time (it may have been disconnected
    or replaced since the draft was built). A challenge page yields
    ``waiting_human`` and, with a store, a persisted redacted checkpoint.
    """
    plan = draft.plan
    if plan.action_class not in {"draft", "upload"} or any(
        dict(step).get("type") == "submit" for step in plan.steps
    ):
        return BrowserActionResult(plan_id=plan.plan_id, status="blocked",
                                   blocker_reason="social_draft_must_not_submit", executor="playwright")
    try:
        sessions.resolve_for_plan(plan)
    except SessionIsolationError:
        return BrowserActionResult(plan_id=plan.plan_id, status="blocked",
                                   blocker_reason="session_not_bound_to_workspace_account",
                                   executor="playwright")
    result = run_playwright(plan, policy=policy, playwright_factory=playwright_factory, clock=clock)
    if result.status != "waiting_human" or checkpoints is None:
        return result
    next_step = plan.steps[result.completed_steps] if result.completed_steps < len(plan.steps) else {}
    cp = challenge_checkpoint(
        plan.plan_id, plan.workspace_id, plan.account_binding_id, result.completed_steps,
        canonical_payload_hash(plan), result.blocker_reason, provider=plan.provider,
        site=result.final_url or str(plan.steps[0].get("url") or ""),
        step_type=str(dict(next_step).get("type") or ""),
    )
    checkpoints.save(cp)
    log = list(result.action_log)
    log[-1] = {**log[-1], "checkpoint_id": cp.checkpoint_id, "site": cp.site, "step_index": cp.step_index}
    return replace(result, action_log=tuple(log))
