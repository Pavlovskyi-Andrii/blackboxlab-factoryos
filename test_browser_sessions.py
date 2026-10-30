"""Deterministic T-560-B session/vault isolation and human takeover regression.

Runs as a script (CI) or via ``python3 -m unittest test_browser_sessions``.
No browser, network, provider or real vault is used.
"""
from dataclasses import replace
import json
import pickle
from pathlib import Path
import tempfile
import unittest

from browser_runner import BrowserActionPlan, canonical_payload_hash
from browser_runner.sessions import (
    CheckpointStore, InMemoryVault, SecretValue, SessionBinding, SessionIsolationError,
    SessionRegistry, VaultError, authorize_resume, challenge_checkpoint, run_mock_resumable,
)


SECRET = "S3cr3t-Pa55!word"
USERNAME = "owner-login-alias"


def make_plan(workspace="ws-a", *, session_ref="", credential_ref="", action_class="draft",
              steps=None, approve=False, plan_id="plan-1"):
    plan = BrowserActionPlan(
        plan_id=plan_id, workspace_id=workspace, provider="x", account_binding_id="acct",
        action_class=action_class, steps=tuple(steps or (
            {"type": "navigate", "url": "https://example.com/compose"},
            {"type": "fill", "selector": "#caption", "value": "hello"},
        )),
        session_ref=session_ref, credential_ref=credential_ref,
    )
    if approve:
        plan = replace(plan, approval_snapshot_id="approval-1",
                       approved_payload_hash=canonical_payload_hash(plan))
    return plan


PUBLISH_STEPS = (
    {"type": "navigate", "url": "https://example.com/compose?draft=1"},
    {"type": "fill", "selector": "#caption", "value": "hello"},
    {"type": "submit", "selector": "button.publish"},
    {"type": "navigate", "url": "https://example.com/settings"},
    {"type": "fill", "selector": "#bio", "value": "bio"},
    {"type": "screenshot"},
)


class Probe:
    """Fixture page: reports a challenge once at given step indices and records executions."""

    def __init__(self, challenges=None):
        self.challenges = dict(challenges or {})
        self.seen = []

    def __call__(self, index, step):
        reason = self.challenges.pop(index, "")
        if not reason:
            self.seen.append((index, step.get("type")))
        return reason


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sessions = SessionRegistry(self.root / "sessions.json")
        self.sessions.bind(SessionBinding("ws-a", "x", "acct", "session://a"))
        self.sessions.bind(SessionBinding("ws-b", "x", "acct", "session://b"))
        self.checkpoints = CheckpointStore(self.root / "checkpoints.json")
        self.vault = InMemoryVault()
        self.vault.put("vault://ws-a/x/acct", workspace_id="ws-a", provider="x",
                       account_binding_id="acct", values={"username": USERNAME, "password": SECRET})

    def tearDown(self):
        self._tmp.cleanup()

    def assert_no_secret(self, *objects):
        for obj in objects:
            text = obj if isinstance(obj, str) else repr(obj)
            self.assertNotIn(SECRET, text)
            self.assertNotIn(USERNAME, text)
        for path in self.root.iterdir():
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(SECRET, text)
            self.assertNotIn(USERNAME, text)

    def run_plan(self, plan, **kwargs):
        return run_mock_resumable(plan, sessions=self.sessions, checkpoints=self.checkpoints,
                                  vault=self.vault, **kwargs)


class SessionIsolationTests(Base):
    def test_registry_isolation_and_disconnect(self):
        self.assertEqual(self.sessions.resolve("ws-a", "x", "acct"), "session://a")
        self.assertEqual(self.sessions.resolve("ws-b", "x", "acct"), "session://b")
        self.assertIsNone(self.sessions.resolve("ws-a", "instagram", "acct"))
        self.sessions.disconnect("ws-a", "x", "acct")
        self.assertIsNone(self.sessions.resolve("ws-a", "x", "acct"))
        self.assertEqual(self.sessions.resolve("ws-b", "x", "acct"), "session://b")
        reloaded = SessionRegistry(self.root / "sessions.json")
        self.assertIsNone(reloaded.resolve("ws-a", "x", "acct"))
        self.assertEqual(reloaded.resolve("ws-b", "x", "acct"), "session://b")

    def test_no_session_crossover(self):
        self.assertEqual(self.run_plan(make_plan("ws-a", session_ref="session://a")).status, "done")
        self.assertEqual(self.run_plan(make_plan("ws-b", session_ref="session://b")).status, "done")
        crossed = self.run_plan(make_plan("ws-b", session_ref="session://a"))
        self.assertEqual(crossed.status, "blocked")
        self.assertIn("not bound", crossed.blocker_reason)
        with self.assertRaises(SessionIsolationError):
            self.sessions.bind(SessionBinding("ws-b", "x", "other", "session://a"))
        with self.assertRaises(ValueError):
            self.sessions.bind(SessionBinding("ws-a", "x", "acct", "cookie=abc"))
        self.sessions.disconnect("ws-a", "x", "acct")
        self.assertEqual(self.run_plan(make_plan("ws-a", session_ref="session://a")).status, "blocked")

    def test_no_credential_crossover(self):
        steps = ({"type": "navigate", "url": "https://example.com/login"},
                 {"type": "fill", "selector": "#user", "credential_field": "username"},
                 {"type": "fill", "selector": "#pw", "credential_field": "password"})
        ok = self.run_plan(make_plan("ws-a", credential_ref="vault://ws-a/x/acct", steps=steps))
        self.assertEqual(ok.status, "done")
        crossed = self.run_plan(make_plan("ws-b", credential_ref="vault://ws-a/x/acct", steps=steps))
        self.assertEqual(crossed.status, "blocked")
        self.assertIn("not available for this binding", crossed.blocker_reason)
        missing = self.run_plan(make_plan("ws-b", credential_ref="vault://ws-b/x/acct", steps=steps))
        self.assertEqual(missing.blocker_reason, crossed.blocker_reason)
        no_vault = run_mock_resumable(make_plan("ws-a", credential_ref="vault://ws-a/x/acct", steps=steps),
                                      sessions=self.sessions, checkpoints=self.checkpoints)
        self.assertEqual(no_vault.status, "blocked")
        with self.assertRaises(VaultError):
            self.vault.put("vault://ws-a/x/acct", workspace_id="ws-b", provider="x",
                           account_binding_id="acct", values={"password": "x"})
        self.assert_no_secret(ok, crossed, missing)


class SecretHandlingTests(Base):
    def test_secret_value_never_renders(self):
        value = SecretValue(SECRET)
        self.assertEqual(value.reveal(), SECRET)
        self.assert_no_secret(repr(value), str(value), f"{value}", repr([value]), repr(self.vault))
        with self.assertRaises(TypeError):
            pickle.dumps(value)

    def test_human_only_material_is_not_resolvable(self):
        for kind in ("otp", "totp_seed", "recovery_code", "cookie"):
            with self.assertRaises(VaultError):
                self.vault.resolve("vault://ws-a/x/acct", workspace_id="ws-a", provider="x",
                                   account_binding_id="acct", kind=kind)
            steps = ({"type": "fill", "selector": "#otp", "credential_field": kind},)
            result = self.run_plan(make_plan("ws-a", credential_ref="vault://ws-a/x/acct", steps=steps))
            self.assertEqual(result.status, "blocked")

    def test_plaintext_and_session_mixing_rejected(self):
        plain = self.run_plan(make_plan("ws-a", session_ref="session://a", steps=(
            {"type": "fill", "selector": "#pw", "password": SECRET},)))
        self.assertEqual(plain.status, "blocked")
        self.assertIn("plaintext secret", plain.blocker_reason)
        mixed = self.run_plan(make_plan("ws-a", session_ref="session://a", steps=(
            {"type": "fill", "selector": "#pw", "credential_field": "password"},)))
        self.assertEqual(mixed.status, "blocked")
        raw_ref = self.run_plan(make_plan("ws-a", credential_ref=SECRET))
        self.assertEqual(raw_ref.status, "blocked")
        self.assert_no_secret(plain, mixed, raw_ref)


class HumanTakeoverTests(Base):
    def publish_plan(self, **kwargs):
        return make_plan("ws-b", session_ref="session://b", action_class="publish",
                         steps=PUBLISH_STEPS, approve=True, **kwargs)

    def test_challenge_stops_at_waiting_human_and_resume_skips_irreversible(self):
        plan = self.publish_plan()
        first = Probe({4: "2fa"})
        stopped = self.run_plan(plan, challenge_probe=first)
        self.assertEqual(stopped.status, "waiting_human")
        self.assertEqual(stopped.completed_steps, 3)
        self.assertEqual(stopped.blocker_reason, "2fa")
        self.assertEqual(stopped.external_receipt, "")
        self.assertEqual([i for i, _ in first.seen], [1, 2, 3])

        waiting = CheckpointStore(self.root / "checkpoints.json").waiting("ws-b")
        self.assertEqual(len(waiting), 1)
        cp = waiting[0]
        self.assertEqual((cp.site, cp.step_index, cp.step_type, cp.reason), ("example.com", 4, "navigate", "2fa"))
        self.assertEqual(cp.irreversible_done, (3,))
        self.assertEqual(CheckpointStore(self.root / "checkpoints.json").waiting("ws-a"), ())
        self.assertNotIn("draft=1", (self.root / "checkpoints.json").read_text(encoding="utf-8"))

        # Not yet owner-authorized: the runner must refuse to resume.
        early = self.run_plan(plan, challenge_probe=Probe(), resume_checkpoint_id=cp.checkpoint_id)
        self.assertEqual(early.status, "blocked")
        for kwargs in (
            {"owner_authorized": False, "workspace_id": "ws-b", "account_binding_id": "acct", "payload_hash": cp.payload_hash},
            {"owner_authorized": True, "workspace_id": "ws-a", "account_binding_id": "acct", "payload_hash": cp.payload_hash},
            {"owner_authorized": True, "workspace_id": "ws-b", "account_binding_id": "acct", "payload_hash": "changed"},
        ):
            with self.assertRaises(PermissionError):
                self.checkpoints.resume(cp.checkpoint_id, **kwargs)

        store = CheckpointStore(self.root / "checkpoints.json")  # survives worker restart
        store.resume(cp.checkpoint_id, owner_authorized=True, workspace_id="ws-b",
                     account_binding_id="acct", payload_hash=canonical_payload_hash(plan))
        self.checkpoints = store
        second = Probe()
        done = self.run_plan(plan, challenge_probe=second, resume_checkpoint_id=cp.checkpoint_id)
        self.assertEqual(done.status, "done")
        self.assertEqual(done.completed_steps, 6)
        self.assertEqual([i for i, _ in second.seen], [4, 5, 6])
        executed_submits = [i for i, kind in first.seen + second.seen if kind == "submit"]
        self.assertEqual(executed_submits, [3])
        self.assertEqual([e["status"] for e in done.action_log[:3]], ["already_completed"] * 3)
        self.assertEqual(done.external_receipt, "")

        replay = self.run_plan(plan, challenge_probe=Probe(), resume_checkpoint_id=cp.checkpoint_id)
        self.assertEqual(replay.status, "blocked", "resume token is single-use")
        self.assertEqual(store.get(cp.checkpoint_id).state, "consumed")

    def test_resume_rejects_changed_plan(self):
        plan = self.publish_plan()
        self.run_plan(plan, challenge_probe=Probe({4: "captcha"}))
        cp = self.checkpoints.waiting("ws-b")[0]
        self.checkpoints.resume(cp.checkpoint_id, owner_authorized=True, workspace_id="ws-b",
                                account_binding_id="acct", payload_hash=cp.payload_hash)
        changed_steps = PUBLISH_STEPS[:4] + ({"type": "fill", "selector": "#bio", "value": "other"},)
        changed = make_plan("ws-b", session_ref="session://b", action_class="publish",
                            steps=changed_steps, approve=True)
        probe = Probe()
        result = self.run_plan(changed, challenge_probe=probe, resume_checkpoint_id=cp.checkpoint_id)
        self.assertEqual(result.status, "blocked")
        self.assertEqual(probe.seen, [])
        other_ws = make_plan("ws-a", session_ref="session://a", action_class="publish",
                             steps=PUBLISH_STEPS, approve=True)
        self.assertEqual(self.run_plan(other_ws, resume_checkpoint_id=cp.checkpoint_id).status, "blocked")

    def test_second_challenge_carries_irreversible_fence(self):
        plan = self.publish_plan()
        self.run_plan(plan, challenge_probe=Probe({4: "2fa"}))
        cp1 = self.checkpoints.waiting("ws-b")[0]
        self.checkpoints.resume(cp1.checkpoint_id, owner_authorized=True, workspace_id="ws-b",
                                account_binding_id="acct", payload_hash=cp1.payload_hash)
        again = self.run_plan(plan, challenge_probe=Probe({6: "security_challenge"}),
                              resume_checkpoint_id=cp1.checkpoint_id)
        self.assertEqual(again.status, "waiting_human")
        cp2 = self.checkpoints.waiting("ws-b")[0]
        self.assertNotEqual(cp2.checkpoint_id, cp1.checkpoint_id)
        self.assertEqual((cp2.completed_steps, cp2.irreversible_done), (5, (3,)))

    def test_credential_login_challenge_has_no_secret_anywhere(self):
        steps = ({"type": "navigate", "url": "https://example.com/login"},
                 {"type": "fill", "selector": "#user", "credential_field": "username"},
                 {"type": "fill", "selector": "#pw", "credential_field": "password"},
                 {"type": "click", "selector": "#continue"},
                 {"type": "fill", "selector": "#caption", "value": "draft"})
        plan = make_plan("ws-a", credential_ref="vault://ws-a/x/acct", steps=steps)
        stopped = self.run_plan(plan, challenge_probe=Probe({5: "2fa"}))
        self.assertEqual(stopped.status, "waiting_human")
        cp = self.checkpoints.waiting("ws-a")[0]
        self.checkpoints.resume(cp.checkpoint_id, owner_authorized=True, workspace_id="ws-a",
                                account_binding_id="acct", payload_hash=cp.payload_hash)
        done = self.run_plan(plan, challenge_probe=Probe(), resume_checkpoint_id=cp.checkpoint_id)
        self.assertEqual(done.status, "done")
        self.assert_no_secret(stopped, done, json.dumps([dict(e) for e in done.action_log], default=str))

    def test_legacy_checkpoint_contract(self):
        cp = challenge_checkpoint("p1", "ws-b", "account", 3, "hash-1", "2fa")
        self.assertEqual((cp.state, cp.completed_steps, cp.step_index), ("waiting_human", 3, 4))
        with self.assertRaises(ValueError):
            challenge_checkpoint("p1", "ws-b", "account", 3, "hash-1", "bypass")
        with self.assertRaises(ValueError):
            challenge_checkpoint("p1", "ws-b", "account", 1, "hash-1", "2fa", irreversible_done=(2,))
        resumed = authorize_resume(cp, owner_authorized=True, workspace_id="ws-b",
                                   account_binding_id="account", payload_hash="hash-1")
        self.assertEqual(resumed.state, "resumed")
        with self.assertRaises(PermissionError):
            authorize_resume(resumed, owner_authorized=True, workspace_id="ws-b",
                             account_binding_id="account", payload_hash="hash-1")


def main():
    unittest.main(module=__name__, verbosity=1)


if __name__ == "__main__":
    main()
