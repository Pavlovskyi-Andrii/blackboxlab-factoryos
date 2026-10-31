"""T-560-D social web draft recipes regression (X, Instagram, Telegram web).

Deterministic: uses the T-560-C fake browser, never a real site, account,
credential or network. CI runs it through ``test_browser_playwright.py``.
"""
from dataclasses import replace
import inspect
from pathlib import Path
import tempfile
import unittest

from browser_runner.core import PolicyError, canonical_payload_hash
from browser_runner.playwright_executor import BrowserRuntimePolicy, run_playwright
from browser_runner.sessions import (
    CheckpointStore, SessionBinding, SessionIsolationError, SessionRegistry, run_mock_resumable,
)
from browser_runner.social import (
    SOCIAL_SITES, final_submit_plan, run_social_draft, social_draft_recipe,
)
from test_browser_playwright import FakePlaywright, not_launched


ORIGINS = {
    "x": "https://x.fixture.example",
    "instagram": "https://ig.fixture.example",
    "telegram": "https://tg.fixture.example",
}
DRAFT_TEXT = "Private launch draft for owner review"


class SocialBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "uploads").mkdir()
        (self.root / "uploads" / "cover.png").write_bytes(b"\x89PNG\r\n\x1a\nfixture")
        (self.root / "uploads" / "clip.mp4").write_bytes(b"fixture-video")
        self.sessions = SessionRegistry(self.root / "sessions.json")
        for provider in SOCIAL_SITES:
            self.sessions.bind(SessionBinding("ws-a", provider, "brand-a", f"session://ws-a/{provider}"))
            self.sessions.bind(SessionBinding("ws-b", provider, "brand-b", f"session://ws-b/{provider}"))
        self.checkpoints = CheckpointStore(self.root / "checkpoints.json")
        self.policy = BrowserRuntimePolicy(
            allowed_origins=tuple(ORIGINS.values()), artifact_root=self.root / "artifacts",
            upload_root=self.root / "uploads",
        )

    def draft(self, provider, **overrides):
        args = dict(
            provider=provider, plan_id=f"social-{provider}", workspace_id="ws-a",
            account_binding_id="brand-a", sessions=self.sessions, text=DRAFT_TEXT,
            media=["cover.png"], site_origin=ORIGINS[provider],
        )
        if provider == "telegram":
            args["telegram_channel"] = "@factory_news"
        args.update(overrides)
        return social_draft_recipe(**args)

    def run_draft(self, draft, factory=FakePlaywright, **kwargs):
        return run_social_draft(draft, policy=self.policy, sessions=self.sessions,
                                checkpoints=self.checkpoints, playwright_factory=factory, **kwargs)


class SocialDraftPreparation(SocialBase):
    def test_each_provider_prepares_text_and_media_up_to_submit_boundary(self):
        caption_selector = {
            "x": SOCIAL_SITES["x"].selectors["composer"],
            "instagram": SOCIAL_SITES["instagram"].selectors["composer"],
            "telegram": SOCIAL_SITES["telegram"].selectors["media_caption"],
        }
        for provider in SOCIAL_SITES:
            with self.subTest(provider=provider):
                fake = FakePlaywright()
                draft = self.draft(provider)
                self.assertEqual(draft.plan.action_class, "upload")
                self.assertNotIn("submit", [s["type"] for s in draft.plan.steps])
                self.assertEqual(draft.plan.steps[-1]["type"], "screenshot")
                self.assertEqual(draft.submit_step["type"], "submit")
                self.assertEqual((draft.text_chars, draft.media_count), (len(DRAFT_TEXT), 1))
                result = self.run_draft(draft, factory=lambda: fake)
                self.assertEqual(result.status, "done", result.blocker_reason)
                self.assertEqual(result.completed_steps, len(draft.plan.steps))
                state = fake.chromium.browser.context.page.state
                self.assertEqual(state[caption_selector[provider]], DRAFT_TEXT)
                self.assertEqual(state["uploaded"], "cover.png")
                self.assertEqual(result.external_receipt, "")
                self.assertEqual(result.final_url, ORIGINS[provider])
                self.assertEqual(len(result.artifacts), 1)
                self.assertNotIn(DRAFT_TEXT, repr(result))
                self.assertNotIn("factory_news", repr(result))

    def test_text_only_drafts_and_instagram_needs_media(self):
        for provider in ("x", "telegram"):
            draft = self.draft(provider, media=[])
            self.assertEqual(draft.plan.action_class, "draft")
            self.assertEqual(self.run_draft(draft).status, "done")
        with self.assertRaisesRegex(PolicyError, "social_media_count_out_of_bounds"):
            self.draft("instagram", media=[])
        with self.assertRaisesRegex(PolicyError, "social_draft_empty"):
            self.draft("x", text="", media=[])

    def test_default_official_origins_pass_runtime_guard(self):
        policy = replace(self.policy, allowed_origins=tuple(s.origin for s in SOCIAL_SITES.values()))
        for provider in SOCIAL_SITES:
            with self.subTest(provider=provider):
                draft = self.draft(provider, site_origin="")
                self.assertTrue(draft.plan.steps[0]["url"].startswith(SOCIAL_SITES[provider].origin))
                result = run_social_draft(draft, policy=policy, sessions=self.sessions,
                                          playwright_factory=FakePlaywright)
                self.assertEqual(result.status, "done", result.blocker_reason)

    def test_provider_limits_and_media_staging(self):
        cases = [
            ("x", {"text": "x" * 281}, "social_text_too_long"),
            ("x", {"media": ["cover.png"] * 5}, "social_media_count_out_of_bounds"),
            ("instagram", {"media": ["cover.png"] * 11}, "social_media_count_out_of_bounds"),
            ("instagram", {"text": "x" * 2201}, "social_text_too_long"),
            ("telegram", {"text": "x" * 1025}, "social_text_too_long"),
            ("x", {"media": ["../secret.png"]}, "social_media_must_be_relative_to_staging_root"),
            ("x", {"media": ["/etc/cover.png"]}, "social_media_must_be_relative_to_staging_root"),
            ("x", {"media": ["notes.txt"]}, "social_media_type_disallowed"),
            ("telegram", {"telegram_channel": "@a"}, "telegram_channel_handle_invalid"),
            ("telegram", {"telegram_channel": "evil.example/x"}, "telegram_channel_handle_invalid"),
            ("x", {"telegram_channel": "@factory_news"}, "telegram_channel_only_for_telegram"),
            ("x", {"selectors": {"password": "#pw"}}, "social_selector_key_unknown"),
            ("linkedin", {}, "social_provider_unsupported"),
        ]
        for provider, overrides, reason in cases:
            with self.subTest(provider=provider, reason=reason):
                with self.assertRaisesRegex(PolicyError, reason):
                    if provider == "linkedin":
                        social_draft_recipe(provider=provider, plan_id="p", workspace_id="ws-a",
                                            account_binding_id="brand-a", sessions=self.sessions,
                                            text="hi")
                    else:
                        self.draft(provider, **overrides)
        # A plain Telegram message may be longer than a media caption.
        self.assertEqual(self.draft("telegram", media=[], text="x" * 1025).text_chars, 1025)
        self.assertEqual(self.draft("x", media=["cover.png", "clip.mp4"]).media_count, 2)

    def test_off_allowlist_site_blocked_before_launch(self):
        draft = self.draft("x", site_origin="https://evil.example")
        result = self.run_draft(draft, factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason), ("blocked", "off_allowlist_navigation"))


class SocialAccountBindings(SocialBase):
    def test_bindings_are_workspace_scoped(self):
        draft = self.draft("x")
        self.assertEqual(draft.plan.session_ref, "session://ws-a/x")
        # ws-b cannot draft with ws-a's account binding, nor ws-a with ws-b's.
        with self.assertRaises(SessionIsolationError):
            self.draft("x", workspace_id="ws-b")
        with self.assertRaises(SessionIsolationError):
            self.draft("x", account_binding_id="brand-b")
        # A plan carrying another workspace's session never launches the browser.
        crossed = replace(draft, plan=replace(draft.plan, session_ref="session://ws-b/x"))
        result = self.run_draft(crossed, factory=not_launched)
        self.assertEqual((result.status, result.blocker_reason),
                         ("blocked", "session_not_bound_to_workspace_account"))

    def test_disconnect_and_replace_account(self):
        draft = self.draft("instagram")
        self.sessions.disconnect("ws-a", "instagram", "brand-a")
        result = self.run_draft(draft, factory=not_launched)
        self.assertEqual(result.blocker_reason, "session_not_bound_to_workspace_account")
        with self.assertRaises(SessionIsolationError):
            self.draft("instagram")
        # Replacing the account: the old draft stays fenced, a new draft uses the new binding.
        self.sessions.bind(SessionBinding("ws-a", "instagram", "brand-a", "session://ws-a/instagram-v2"))
        self.assertEqual(self.run_draft(draft, factory=not_launched).status, "blocked")
        fresh = self.draft("instagram")
        self.assertEqual(fresh.plan.session_ref, "session://ws-a/instagram-v2")
        self.assertEqual(self.run_draft(fresh).status, "done")
        # Other providers/workspaces are untouched.
        self.assertEqual(self.sessions.resolve("ws-b", "instagram", "brand-b"), "session://ws-b/instagram")


class SocialNoPlaintextCredentials(SocialBase):
    def test_recipe_has_no_credential_inputs_and_stores_refs_only(self):
        params = set(inspect.signature(social_draft_recipe).parameters)
        for name in ("password", "credential_ref", "session_ref", "cookie", "token", "credentials"):
            self.assertNotIn(name, params)
        with self.assertRaises(TypeError):
            self.draft("x", password="hunter2")
        for provider in SOCIAL_SITES:
            draft = self.draft(provider)
            self.assertEqual(draft.plan.credential_ref, "")
            self.assertTrue(draft.plan.session_ref.startswith("session://"))
        stored = (self.root / "sessions.json").read_text()
        self.assertNotIn("cookie", stored.lower())
        self.assertNotIn("password", stored.lower())

    def test_secret_like_text_rejected(self):
        with self.assertRaisesRegex(PolicyError, "plaintext secret material"):
            self.draft("x", text="Bearer abc.def.ghi")


class SocialChallenges(SocialBase):
    def test_challenge_page_becomes_waiting_human_with_persisted_checkpoint(self):
        for provider, challenge in (("x", "2fa"), ("instagram", "captcha"), ("telegram", "2fa")):
            with self.subTest(provider=provider):
                def factory():
                    fake = FakePlaywright()
                    fake.chromium.browser.context.page.challenge = challenge
                    return fake
                draft = self.draft(provider)
                result = self.run_draft(draft, factory=factory)
                self.assertEqual((result.status, result.blocker_reason), ("waiting_human", challenge))
                self.assertEqual(result.completed_steps, 1)
                self.assertEqual(result.external_receipt, "")
                cp = self.checkpoints.get(result.action_log[-1]["checkpoint_id"])
                self.assertEqual((cp.state, cp.provider, cp.reason), ("waiting_human", provider, challenge))
                self.assertEqual(cp.site, ORIGINS[provider].split("//")[1])
                self.assertEqual((cp.step_index, cp.step_type), (2, draft.plan.steps[1]["type"]))
                self.assertEqual(cp.payload_hash, canonical_payload_hash(draft.plan))
                with self.assertRaises(PermissionError):
                    self.checkpoints.resume(cp.checkpoint_id, owner_authorized=False, workspace_id="ws-a",
                                            account_binding_id="brand-a", payload_hash=cp.payload_hash)
        persisted = (self.root / "checkpoints.json").read_text()
        self.assertNotIn(DRAFT_TEXT, persisted)
        self.assertNotIn("session://", persisted)


class SocialPublishGate(SocialBase):
    def approved(self, plan):
        return replace(plan, approval_snapshot_id="owner-approval-1",
                       approved_payload_hash=canonical_payload_hash(plan))

    def test_final_submit_needs_matching_human_approval(self):
        for provider in SOCIAL_SITES:
            with self.subTest(provider=provider):
                draft = self.draft(provider)
                final = final_submit_plan(draft)
                self.assertEqual(final.steps[:-1], draft.plan.steps)
                self.assertEqual(final.steps[-1], draft.submit_step)
                self.assertEqual(final.action_class, SOCIAL_SITES[provider].submit_action_class)
                self.assertEqual((final.approval_snapshot_id, final.approved_payload_hash), ("", ""))
                mock = dict(sessions=self.sessions, checkpoints=self.checkpoints)
                result = run_mock_resumable(final, **mock)
                self.assertEqual((result.status, result.completed_steps), ("blocked", 0))
                # Approval of one payload does not cover edited text.
                approved = self.approved(final)
                edited = final_submit_plan(self.draft(provider, text=DRAFT_TEXT + "!"))
                stolen = replace(edited, approval_snapshot_id=approved.approval_snapshot_id,
                                 approved_payload_hash=approved.approved_payload_hash)
                self.assertEqual(run_mock_resumable(stolen, **mock).status, "blocked")
                # Only the exact approved snapshot passes the gate (mock executor, no network).
                self.assertEqual(run_mock_resumable(approved, **mock).status, "done")

    def test_real_browser_never_publishes_even_with_matching_approval(self):
        for provider in SOCIAL_SITES:
            with self.subTest(provider=provider):
                final = final_submit_plan(self.draft(provider))
                result = run_playwright(final, policy=self.policy, playwright_factory=not_launched)
                self.assertEqual(result.blocker_reason, "submit_requires_matching_human_approval")
                result = run_playwright(self.approved(final), policy=self.policy,
                                        playwright_factory=not_launched)
                self.assertEqual((result.status, result.blocker_reason),
                                 ("blocked", "trusted_approval_verifier_not_configured"))
                self.assertEqual(result.external_receipt, "")
                # The draft runner refuses submit plans outright.
                draft = self.draft(provider)
                smuggled = replace(draft, plan=self.approved(final))
                result = self.run_draft(smuggled, factory=not_launched)
                self.assertEqual((result.status, result.blocker_reason),
                                 ("blocked", "social_draft_must_not_submit"))


if __name__ == "__main__":
    unittest.main()
