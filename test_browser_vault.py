"""Deterministic T-560-F encrypted vault regression.

Runs as a script (CI) or via ``python3 -m unittest test_browser_vault``.
No browser, network, provider or production key is used; keys are generated per test.
"""
import base64
import json
import os
from pathlib import Path
import pickle
import stat
import tempfile
import unittest

from browser_runner import BrowserActionPlan
from browser_runner.playwright_executor import BrowserRuntimePolicy, run_playwright
from browser_runner.sessions import (
    CheckpointStore, SecretValue, SessionRegistry, VaultError, run_mock_resumable,
)
from browser_runner.vault import (
    KEY_ENV, PREVIOUS_KEY_ENV, EncryptedCredentialVault, EncryptedSessionStore, Keyring,
    SecretState, VaultConfigError, generate_key, make_token_vault, vault_paths, vault_status,
)
from oauth_framework import OAuthFlow, TokenSet
from test_browser_playwright import FakeBrowser, FakeChromium, FakePlaywright


PASSWORD = "Pa55-very-secret-word!"
COOKIE = "sid-cookie-value-9f8e7d"
STATE = {
    "cookies": [{"name": "sid", "value": COOKIE, "domain": "fixture.example", "path": "/",
                 "expires": -1, "httpOnly": True, "secure": True, "sameSite": "Lax"}],
    "origins": [{"origin": "https://fixture.example",
                 "localStorage": [{"name": "token", "value": "ls-token-abc123"}]}],
}


def keyring(env=None):
    return Keyring.from_env(env or {KEY_ENV: generate_key()})


def all_bytes(root: Path) -> bytes:
    return b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())


class KeyConfig(unittest.TestCase):
    def test_missing_key_means_no_vault(self):
        self.assertIsNone(Keyring.from_env({}))
        status = vault_status(env={})
        self.assertFalse(status["configured"])
        self.assertIn(KEY_ENV, status["reason"])

    def test_malformed_key_fails_closed_without_echoing_it(self):
        bad = "not-a-valid-key-value"
        with self.assertRaises(VaultConfigError) as ctx:
            Keyring.from_env({KEY_ENV: bad})
        self.assertNotIn(bad, str(ctx.exception))
        self.assertFalse(vault_status(env={KEY_ENV: bad})["configured"])

    def test_hex_and_base64_keys_accepted_and_never_rendered(self):
        raw = os.urandom(32)
        for value in (raw.hex(), base64.b64encode(raw).decode(), base64.urlsafe_b64encode(raw).decode()):
            ring = Keyring.from_env({KEY_ENV: value})
            self.assertNotIn(value, repr(ring))
            self.assertNotIn(value, json.dumps(vault_status(env={KEY_ENV: value})))
        with self.assertRaises(TypeError):
            pickle.dumps(ring)


class VaultBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.env = {KEY_ENV: generate_key()}
        self.ring = keyring(self.env)
        self.paths = vault_paths(self.root)


class CredentialVaultRegression(VaultBase):
    def vault(self, ring=None):
        return EncryptedCredentialVault(self.paths["credential"], ring or self.ring)

    def test_roundtrip_is_scoped_and_ciphertext_only(self):
        v = self.vault()
        v.put("vault://olx/main", workspace_id="ws-a", provider="olx", account_binding_id="acct",
              values={"username": "owner@example.com", "password": PASSWORD})
        got = self.vault().resolve("vault://olx/main", workspace_id="ws-a", provider="olx",
                                   account_binding_id="acct", kind="password")
        self.assertIsInstance(got, SecretValue)
        self.assertEqual(got.reveal(), PASSWORD)
        self.assertNotIn(PASSWORD, repr(got))
        disk = all_bytes(self.root)
        self.assertNotIn(PASSWORD.encode(), disk)
        self.assertNotIn(b"owner@example.com", disk)
        mode = stat.S_IMODE(self.paths["credential"].stat().st_mode)
        self.assertEqual(mode, 0o600)

    def test_other_workspace_and_missing_ref_look_identical(self):
        v = self.vault()
        v.put("vault://olx/main", workspace_id="ws-a", provider="olx", account_binding_id="acct",
              values={"password": PASSWORD})
        errors = []
        for kwargs in (dict(workspace_id="ws-b", provider="olx", account_binding_id="acct"),
                       dict(workspace_id="ws-a", provider="github", account_binding_id="acct"),
                       dict(workspace_id="ws-a", provider="olx", account_binding_id="other")):
            with self.assertRaises(VaultError) as ctx:
                v.resolve("vault://olx/main", kind="password", **kwargs)
            errors.append(str(ctx.exception))
        with self.assertRaises(VaultError) as ctx:
            v.resolve("vault://missing", workspace_id="ws-a", provider="olx",
                      account_binding_id="acct", kind="password")
        errors.append(str(ctx.exception))
        self.assertEqual(len(set(errors)), 1)
        with self.assertRaises(VaultError):  # a ref cannot be rebound to another scope
            v.put("vault://olx/main", workspace_id="ws-b", provider="olx",
                  account_binding_id="acct", values={"password": "x"})

    def test_human_only_material_is_refused(self):
        v = self.vault()
        for kind in ("otp", "totp_seed", "recovery_code", "cookies"):
            with self.assertRaises(VaultError):
                v.put("vault://x", workspace_id="ws", provider="p", account_binding_id="a",
                      values={kind: "123456"})
        with self.assertRaises(VaultError):
            v.resolve("vault://x", workspace_id="ws", provider="p", account_binding_id="a", kind="otp")

    def test_tampering_or_moving_ciphertext_does_not_decrypt(self):
        v = self.vault()
        for ws in ("ws-a", "ws-b"):
            v.put(f"vault://{ws}", workspace_id=ws, provider="olx", account_binding_id="acct",
                  values={"password": f"{PASSWORD}-{ws}"})
        data = json.loads(self.paths["credential"].read_text())
        # Swap ws-b's ciphertext into ws-a's record: AAD binding must reject it.
        data["vault://ws-a"]["envelope"] = data["vault://ws-b"]["envelope"]
        self.paths["credential"].write_text(json.dumps(data))
        with self.assertRaises(VaultError):
            v.resolve("vault://ws-a", workspace_id="ws-a", provider="olx",
                      account_binding_id="acct", kind="password")

    def test_wrong_key_cannot_read_and_rotation_works(self):
        v = self.vault()
        v.put("vault://r", workspace_id="ws", provider="p", account_binding_id="a",
              values={"password": PASSWORD})
        with self.assertRaises(VaultError):
            self.vault(keyring()).resolve("vault://r", workspace_id="ws", provider="p",
                                          account_binding_id="a", kind="password")
        new_env = {KEY_ENV: generate_key(), PREVIOUS_KEY_ENV: self.env[KEY_ENV]}
        rotated_ring = Keyring.from_env(new_env)
        rotated = self.vault(rotated_ring)
        self.assertEqual(rotated.reencrypt_all(), 1)
        only_new = self.vault(Keyring.from_env({KEY_ENV: new_env[KEY_ENV]}))
        self.assertEqual(only_new.resolve("vault://r", workspace_id="ws", provider="p",
                                          account_binding_id="a", kind="password").reveal(), PASSWORD)
        kids = vault_status(self.root, env=new_env)["records_by_kid"]["credential"]
        self.assertEqual(kids, {rotated_ring.primary_kid: 1})

    def test_works_with_existing_resumable_runner(self):
        v = self.vault()
        v.put("vault://login", workspace_id="ws-a", provider="x", account_binding_id="acct",
              values={"username": "alias", "password": PASSWORD})
        plan = BrowserActionPlan(
            plan_id="p", workspace_id="ws-a", provider="x", account_binding_id="acct",
            action_class="draft", credential_ref="vault://login", steps=(
                {"type": "navigate", "url": "https://example.com/login"},
                {"type": "fill", "selector": "#u", "credential_field": "username"},
                {"type": "fill", "selector": "#p", "credential_field": "password"},
            ),
        )
        result = run_mock_resumable(plan, sessions=SessionRegistry(), checkpoints=CheckpointStore(),
                                    vault=v)
        self.assertEqual(result.status, "done")
        self.assertNotIn(PASSWORD, json.dumps(result.__dict__, default=str))


class SessionStoreRegression(VaultBase):
    def store(self, ring=None):
        registry = SessionRegistry(self.paths["session_registry"])
        return EncryptedSessionStore(self.paths["session"], ring or self.ring, registry), registry

    def test_capture_load_replace_disconnect(self):
        store, registry = self.store()
        ref = store.capture(workspace_id="ws-a", provider="olx", account_binding_id="acct",
                            storage_state=STATE)
        self.assertTrue(ref.startswith("session://"))
        self.assertEqual(registry.resolve("ws-a", "olx", "acct"), ref)
        disk = all_bytes(self.root)
        self.assertNotIn(COOKIE.encode(), disk)
        self.assertNotIn(b"ls-token-abc123", disk)

        store2, _ = self.store()  # survives restart
        state = store2.load(ref, workspace_id="ws-a", provider="olx", account_binding_id="acct")
        self.assertIsInstance(state, SecretState)
        self.assertEqual(state.reveal()["cookies"][0]["value"], COOKIE)
        self.assertNotIn(COOKIE, repr(state))
        with self.assertRaises(TypeError):
            pickle.dumps(state)
        with self.assertRaises(VaultError):
            store2.load(ref, workspace_id="ws-b", provider="olx", account_binding_id="acct")

        new_ref = store2.capture(workspace_id="ws-a", provider="olx", account_binding_id="acct",
                                 storage_state=STATE)
        self.assertNotEqual(new_ref, ref)
        with self.assertRaises(VaultError):  # replaced session is gone
            store2.load(ref, workspace_id="ws-a", provider="olx", account_binding_id="acct")
        self.assertNotIn(ref, self.paths["session"].read_text())

        self.assertTrue(store2.disconnect(workspace_id="ws-a", provider="olx", account_binding_id="acct"))
        with self.assertRaises(VaultError):
            store2.load(new_ref, workspace_id="ws-a", provider="olx", account_binding_id="acct")

    def test_rejects_malformed_state(self):
        store, _ = self.store()
        for bad in ([], {"cookies": "x"}, {"cookies": [], "origins": [], "extra": 1}):
            with self.assertRaises(VaultError):
                store.capture(workspace_id="ws", provider="p", account_binding_id="a", storage_state=bad)


class CapturingBrowser(FakeBrowser):
    seen = {}

    def new_context(self, **kwargs):
        CapturingBrowser.seen = kwargs
        return super().new_context(**kwargs)


class CapturingChromium(FakeChromium):
    def __init__(self):
        self.browser = CapturingBrowser()


class CapturingPlaywright(FakePlaywright):
    def __init__(self):
        self.chromium = CapturingChromium()


class PlaywrightRestoreRegression(VaultBase):
    def setUp(self):
        super().setUp()
        self.policy = BrowserRuntimePolicy(allowed_origins=("https://fixture.example",),
                                           artifact_root=self.root / "artifacts")
        self.registry = SessionRegistry(self.paths["session_registry"])
        self.store = EncryptedSessionStore(self.paths["session"], self.ring, self.registry)
        self.ref = self.store.capture(workspace_id="ws-a", provider="generic",
                                      account_binding_id="acct", storage_state=STATE)

    def plan(self, workspace="ws-a", ref=None):
        return BrowserActionPlan(
            plan_id="restore", workspace_id=workspace, provider="generic", account_binding_id="acct",
            session_ref=self.ref if ref is None else ref, action_class="read",
            steps=({"type": "navigate", "url": "https://fixture.example/dashboard"},
                   {"type": "screenshot"}),
        )

    def test_restored_state_reaches_context_but_not_result(self):
        CapturingBrowser.seen = {}
        result = run_playwright(self.plan(), policy=self.policy, playwright_factory=CapturingPlaywright,
                                session_store=self.store)
        self.assertEqual(result.status, "done", result.blocker_reason)
        self.assertEqual(CapturingBrowser.seen["storage_state"]["cookies"][0]["value"], COOKIE)
        self.assertNotIn(COOKIE, json.dumps(result.__dict__, default=str))
        self.assertNotIn(COOKIE.encode(), all_bytes(self.root / "artifacts"))

    def test_other_workspace_or_unbound_ref_blocks_before_browser_launch(self):
        for p in (self.plan(workspace="ws-b"), self.plan(ref="session://forged")):
            CapturingBrowser.seen = {}
            result = run_playwright(p, policy=self.policy, playwright_factory=CapturingPlaywright,
                                    session_store=self.store)
            self.assertEqual(result.status, "blocked")
            self.assertEqual(result.blocker_reason, "session_unavailable_for_binding")
            self.assertEqual(CapturingBrowser.seen, {})

    def test_without_store_context_stays_anonymous(self):
        CapturingBrowser.seen = {}
        run_playwright(self.plan(), policy=self.policy, playwright_factory=CapturingPlaywright)
        self.assertNotIn("storage_state", CapturingBrowser.seen)

    def test_restored_session_still_cannot_write(self):
        p = BrowserActionPlan(
            plan_id="w", workspace_id="ws-a", provider="generic", account_binding_id="acct",
            session_ref=self.ref, action_class="publish",
            steps=({"type": "navigate", "url": "https://fixture.example/new"},),
        )
        result = run_playwright(p, policy=self.policy, playwright_factory=CapturingPlaywright,
                                session_store=self.store)
        self.assertEqual(result.status, "blocked")


class TokenVaultRegression(VaultBase):
    def test_encrypted_token_vault_roundtrip_and_status(self):
        v = make_token_vault(self.paths["oauth_token"], self.ring)
        v.put("ws-a", "youtube", TokenSet(access_token="ya29.access-secret",
                                          refresh_token="1//refresh-secret", scopes=("a", "b")))
        again = make_token_vault(self.paths["oauth_token"], self.ring)
        tokens = again.get("ws-a", "youtube")
        self.assertEqual(tokens.refresh_token, "1//refresh-secret")
        self.assertIsNone(again.get("ws-b", "youtube"))
        status = again.status("ws-a", "youtube")
        self.assertEqual((status["encrypted"], status["durable"], status["vault"]), (True, True, "encrypted"))
        self.assertNotIn("secret", json.dumps(status))
        self.assertNotIn(b"access-secret", all_bytes(self.root))
        self.assertTrue(again.delete("ws-a", "youtube"))
        self.assertIsNone(again.get("ws-a", "youtube"))

    def test_oauth_flow_no_longer_reports_vault_unavailable(self):
        flow = OAuthFlow(redirect_base="https://factory.example", client_id_lookup=lambda spec: "",
                         vault=make_token_vault(self.paths["oauth_token"], self.ring))
        registry = flow.public_registry()
        self.assertTrue(registry)
        for entry in registry:
            self.assertNotIn("vault_unavailable", entry["blockers"])
            self.assertEqual(entry["vault"], "encrypted")
            self.assertIn("client_not_configured", entry["blockers"])  # still owner work (T-551)


def main():
    unittest.main(module=__name__, verbosity=1)


if __name__ == "__main__":
    main()
