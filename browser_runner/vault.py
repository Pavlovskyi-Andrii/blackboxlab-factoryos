"""T-560-F: encrypted vault backend (AES-256-GCM) for browser credentials, browser
sessions and OAuth tokens.

What it stores, always as ciphertext on disk:
- worker-resolvable login fields (``username`` / ``password``) behind ``vault://`` refs;
- Playwright ``storage_state`` (cookies + localStorage) behind ``session://`` refs, so a
  session the owner logged into once (2FA/CAPTCHA done by a human) can be reused;
- OAuth ``TokenSet`` records for ``oauth_framework`` (T-552 storage half).

Rules:
- The master key comes only from ``FACTORY_VAULT_KEY`` (32 bytes, base64 or 64 hex
  chars). ``FACTORY_VAULT_KEY_PREVIOUS`` is decrypt-only, for rotation. No key -> no
  vault: callers get ``None`` and must stay fail-closed. Key bytes are never logged,
  returned or persisted; only a short key fingerprint (``kid``) is stored.
- Every record is bound to its namespace, record id and scope (workspace / provider /
  account binding) through GCM associated data. A ciphertext copied to another scope
  or edited on disk does not decrypt.
- Human-only material (OTP codes, TOTP seeds, recovery codes) is refused at write time.
- Plaintext exists only in process memory, wrapped in objects that render as redacted.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
import secrets as _secrets
import threading
import time
from typing import Any, Dict, Mapping, Optional, Tuple

from .core import REDACTED
from .sessions import (
    CREDENTIAL_REF_PREFIX, RESOLVABLE_SECRET_KINDS, SESSION_REF_PREFIX, SecretValue,
    SessionBinding, SessionRegistry, VaultError, _atomic_write_json, _valid_ref,
)

KEY_ENV = "FACTORY_VAULT_KEY"
PREVIOUS_KEY_ENV = "FACTORY_VAULT_KEY_PREVIOUS"
ALGORITHM = "AES-256-GCM"
ENVELOPE_VERSION = 1
MAX_SESSION_STATE_BYTES = 1_000_000
MAX_CREDENTIAL_VALUE_CHARS = 4096


class VaultConfigError(ValueError):
    """The configured master key is malformed. Message never contains key material."""


def _parse_key(raw: str, env_name: str) -> bytes:
    value = (raw or "").strip()
    if len(value) == 64:
        try:
            key = bytes.fromhex(value)
            if len(key) == 32:
                return key
        except ValueError:
            pass
    for decoder in (base64.b64decode, base64.urlsafe_b64decode):
        try:
            key = decoder(value + "=" * (-len(value) % 4))
        except (binascii.Error, ValueError):
            continue
        if len(key) == 32:
            return key
    raise VaultConfigError(f"{env_name} must be 32 bytes (base64 or 64 hex characters)")


def _kid(key: bytes) -> str:
    return hashlib.sha256(b"factoryos-vault-kid:" + key).hexdigest()[:12]


def generate_key() -> str:
    """Helper for the owner: a fresh base64 key to paste into the secret environment."""
    return base64.b64encode(_secrets.token_bytes(32)).decode("ascii")


class Keyring:
    """Primary key encrypts; primary + previous decrypt."""

    __slots__ = ("_primary_kid", "_keys")

    def __init__(self, primary: bytes, previous: Tuple[bytes, ...] = ()):
        if len(primary) != 32 or any(len(k) != 32 for k in previous):
            raise VaultConfigError("vault keys must be 32 bytes")
        self._primary_kid = _kid(primary)
        self._keys: Dict[str, bytes] = {_kid(k): k for k in previous}
        self._keys[self._primary_kid] = primary

    def __repr__(self) -> str:
        return f"Keyring(kid={self._primary_kid}, keys={len(self._keys)})"

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("Keyring cannot be serialized")

    @property
    def primary_kid(self) -> str:
        return self._primary_kid

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> Optional["Keyring"]:
        env = os.environ if env is None else env
        raw = env.get(KEY_ENV, "")
        if not raw.strip():
            return None
        primary = _parse_key(raw, KEY_ENV)
        previous = tuple(
            _parse_key(part, PREVIOUS_KEY_ENV)
            for part in env.get(PREVIOUS_KEY_ENV, "").split(",") if part.strip()
        )
        return cls(primary, previous)

    def encrypt(self, plaintext: bytes, aad: bytes) -> Dict[str, Any]:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        nonce = _secrets.token_bytes(12)
        ct = AESGCM(self._keys[self._primary_kid]).encrypt(nonce, plaintext, aad)
        return {
            "v": ENVELOPE_VERSION, "alg": ALGORITHM, "kid": self._primary_kid,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ct": base64.b64encode(ct).decode("ascii"),
        }

    def decrypt(self, envelope: Mapping[str, Any], aad: bytes) -> bytes:
        from cryptography.exceptions import InvalidTag
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        try:
            if envelope.get("v") != ENVELOPE_VERSION or envelope.get("alg") != ALGORITHM:
                raise VaultError("vault_record_unreadable")
            key = self._keys.get(str(envelope.get("kid")))
            if key is None:
                raise VaultError("vault_key_unavailable")
            nonce = base64.b64decode(envelope["nonce"])
            ct = base64.b64decode(envelope["ct"])
            return AESGCM(key).decrypt(nonce, ct, aad)
        except VaultError:
            raise
        except (InvalidTag, KeyError, TypeError, ValueError, binascii.Error):
            raise VaultError("vault_record_unreadable") from None


def _aad(namespace: str, record_id: str, scope: Tuple[str, ...]) -> bytes:
    return json.dumps(["factoryos-vault", namespace, record_id, list(scope)],
                      separators=(",", ":")).encode("utf-8")


class _EncryptedFile:
    """One JSON file of ``{record_id: {scope, envelope, updated_at}}``; ciphertext only."""

    def __init__(self, path: Path, keyring: Keyring, namespace: str):
        self._path = Path(path)
        self._keyring = keyring
        self._namespace = namespace
        self._lock = threading.RLock()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}

    def put(self, record_id: str, scope: Tuple[str, ...], plaintext: bytes,
            meta: Optional[Mapping[str, Any]] = None) -> None:
        """``meta`` is stored in plaintext: only non-secret labels (e.g. field kinds)."""
        with self._lock:
            items = self._load()
            existing = items.get(record_id)
            if existing and tuple(existing.get("scope") or ()) != scope:
                raise VaultError("record already scoped to another binding")
            items[record_id] = {
                "scope": list(scope),
                "envelope": self._keyring.encrypt(plaintext, _aad(self._namespace, record_id, scope)),
                "updated_at": round(time.time(), 3),
                "meta": dict(meta or {}),
            }
            _atomic_write_json(self._path, items)

    def entries(self) -> Tuple[Dict[str, Any], ...]:
        """Non-secret listing: record id, scope, update time, key id, plaintext meta."""
        with self._lock:
            items = self._load()
        return tuple({
            "id": record_id, "scope": tuple(item.get("scope") or ()),
            "updated_at": item.get("updated_at"), "kid": (item.get("envelope") or {}).get("kid"),
            "meta": dict(item.get("meta") or {}),
        } for record_id, item in items.items())

    def get(self, record_id: str, scope: Tuple[str, ...]) -> Optional[bytes]:
        with self._lock:
            item = self._load().get(record_id)
        if item is None or tuple(item.get("scope") or ()) != scope:
            return None
        return self._keyring.decrypt(item["envelope"], _aad(self._namespace, record_id, scope))

    def update_meta(self, record_id: str, scope: Tuple[str, ...], updates: Mapping[str, Any]) -> bool:
        """Changes plaintext labels only; the ciphertext and its AAD are untouched."""
        with self._lock:
            items = self._load()
            item = items.get(record_id)
            if item is None or tuple(item.get("scope") or ()) != scope:
                return False
            item["meta"] = {**dict(item.get("meta") or {}), **dict(updates)}
            _atomic_write_json(self._path, items)
            return True

    def delete(self, record_id: str, scope: Tuple[str, ...]) -> bool:
        with self._lock:
            items = self._load()
            item = items.get(record_id)
            if item is None or tuple(item.get("scope") or ()) != scope:
                return False
            del items[record_id]
            _atomic_write_json(self._path, items)
            return True

    def reencrypt_all(self) -> int:
        """Rotation: rewrite every record under the current primary key."""
        with self._lock:
            items = self._load()
            for record_id, item in items.items():
                scope = tuple(item.get("scope") or ())
                aad = _aad(self._namespace, record_id, scope)
                plaintext = self._keyring.decrypt(item["envelope"], aad)
                item["envelope"] = self._keyring.encrypt(plaintext, aad)
            _atomic_write_json(self._path, items)
            return len(items)

    def kids(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        with self._lock:
            for item in self._load().values():
                kid = str((item.get("envelope") or {}).get("kid"))
                counts[kid] = counts.get(kid, 0) + 1
        return counts


def _scope(workspace_id: str, provider: str, account_binding_id: str) -> Tuple[str, str, str]:
    if not all(isinstance(v, str) and v for v in (workspace_id, provider, account_binding_id)):
        raise VaultError("workspace, provider and account binding are required")
    return (workspace_id, provider, account_binding_id)


class EncryptedCredentialVault:
    """Durable ``CredentialVault``: same semantics as ``InMemoryVault``, encrypted at rest."""

    kind = "encrypted"

    def __init__(self, path: Path, keyring: Keyring):
        self._file = _EncryptedFile(path, keyring, "credential")

    def __repr__(self) -> str:
        return "EncryptedCredentialVault()"

    def put(self, credential_ref: str, *, workspace_id: str, provider: str,
            account_binding_id: str, values: Mapping[str, str]) -> None:
        if not _valid_ref(credential_ref, CREDENTIAL_REF_PREFIX):
            raise VaultError("only opaque vault:// references are accepted")
        scope = _scope(workspace_id, provider, account_binding_id)
        clean: Dict[str, str] = {}
        for kind, value in dict(values).items():
            if kind not in RESOLVABLE_SECRET_KINDS:
                # OTP / TOTP seeds / recovery codes / cookies stay human-only.
                raise VaultError(f"credential kind not storable: {kind}")
            if not isinstance(value, str) or not value or len(value) > MAX_CREDENTIAL_VALUE_CHARS:
                raise VaultError(f"invalid credential value for {kind}")
            clean[kind] = value
        if not clean:
            raise VaultError("no credential values")
        self._file.put(credential_ref, scope, json.dumps(clean).encode("utf-8"),
                       meta={"kinds": sorted(clean)})

    def entries(self, workspace_id: str) -> Tuple[Dict[str, Any], ...]:
        return tuple({
            "ref": e["id"], "provider": e["scope"][1], "account": e["scope"][2],
            "kinds": list(e["meta"].get("kinds") or ()), "updated_at": e["updated_at"], "kid": e["kid"],
        } for e in self._file.entries() if len(e["scope"]) == 3 and e["scope"][0] == workspace_id)

    def find_ref(self, *, workspace_id: str, provider: str, account_binding_id: str) -> Optional[str]:
        scope = _scope(workspace_id, provider, account_binding_id)
        for e in self._file.entries():
            if e["scope"] == scope:
                return e["id"]
        return None

    def check(self, credential_ref: str, *, workspace_id: str, provider: str,
              account_binding_id: str) -> Dict[str, Any]:
        """Decrypts in memory and reports only which fields are present."""
        try:
            raw = self._file.get(credential_ref, _scope(workspace_id, provider, account_binding_id))
        except VaultError:
            raw = None
        if raw is None:
            return {"ok": False, "reason": "not_decryptable"}
        return {"ok": True, "fields": sorted(json.loads(raw.decode("utf-8")))}

    def resolve(self, credential_ref: str, *, workspace_id: str, provider: str,
                account_binding_id: str, kind: str) -> SecretValue:
        if kind not in RESOLVABLE_SECRET_KINDS:
            raise VaultError(f"credential kind not resolvable by worker: {kind}")
        try:
            raw = self._file.get(credential_ref, _scope(workspace_id, provider, account_binding_id))
        except VaultError:
            raw = None
        if raw is None:
            # Same message for missing, out-of-scope and tampered refs: no existence oracle.
            raise VaultError("credential_ref not available for this binding")
        value = json.loads(raw.decode("utf-8")).get(kind)
        if not value:
            raise VaultError(f"credential kind missing: {kind}")
        return SecretValue(value)

    def delete(self, credential_ref: str, *, workspace_id: str, provider: str,
               account_binding_id: str) -> bool:
        return self._file.delete(credential_ref, _scope(workspace_id, provider, account_binding_id))

    def reencrypt_all(self) -> int:
        return self._file.reencrypt_all()


class SecretState:
    """Decrypted Playwright storage_state; renders redacted, cannot be serialized."""

    __slots__ = ("_value",)

    def __init__(self, value: Dict[str, Any]):
        self._value = value

    def reveal(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self._value))

    def __repr__(self) -> str:
        return REDACTED

    __str__ = __repr__

    def __reduce__(self):
        raise TypeError("SecretState cannot be serialized")


_SAME_SITE = {"no_restriction": "None", "none": "None", "lax": "Lax", "strict": "Strict", "unspecified": "Lax"}


def from_cookie_export(cookies: Any) -> Dict[str, Any]:
    """Owner 2026-11-13: Google refuses sign-in inside Playwright's browser, so a session can also come from the
    owner's everyday Chrome via a cookie-export extension (Cookie-Editor / EditThisCookie JSON list). Converted to a
    Playwright storage_state; values are kept as they are and only ever stored encrypted."""
    if not isinstance(cookies, list) or not cookies:
        raise VaultError("cookie export must be a non-empty list")
    out = []
    for c in cookies[:500]:
        if not isinstance(c, Mapping) or not c.get("name") or not c.get("domain"):
            raise VaultError("cookie export entries need name and domain")
        expires = c.get("expirationDate", c.get("expires", -1))
        out.append({"name": str(c["name"]), "value": str(c.get("value") or ""), "domain": str(c["domain"]),
                    "path": str(c.get("path") or "/"),
                    "expires": float(expires) if isinstance(expires, (int, float)) and not c.get("session") else -1,
                    "httpOnly": bool(c.get("httpOnly")), "secure": bool(c.get("secure")),
                    "sameSite": _SAME_SITE.get(str(c.get("sameSite") or "unspecified").lower(), "Lax")})
    return {"cookies": out, "origins": []}


def _validate_storage_state(state: Any) -> bytes:
    if not isinstance(state, Mapping):
        raise VaultError("storage_state must be an object")
    cookies, origins = state.get("cookies", []), state.get("origins", [])
    if not isinstance(cookies, list) or not isinstance(origins, list):
        raise VaultError("storage_state must contain cookies/origins lists")
    if set(state) - {"cookies", "origins"}:
        raise VaultError("storage_state has unexpected fields")
    raw = json.dumps({"cookies": cookies, "origins": origins}, sort_keys=True).encode("utf-8")
    if len(raw) > MAX_SESSION_STATE_BYTES:
        raise VaultError("storage_state too large")
    return raw


def _state_summary(state: Mapping[str, Any]) -> Dict[str, Any]:
    """Non-secret shape of a storage_state: counts, domains and earliest cookie expiry."""
    cookies = [c for c in state.get("cookies") or [] if isinstance(c, Mapping)]
    origins = [o for o in state.get("origins") or [] if isinstance(o, Mapping)]
    domains = sorted({str(c.get("domain") or "").lstrip(".")[:253] for c in cookies} - {""})[:20]
    expiries = [float(c["expires"]) for c in cookies
                if isinstance(c.get("expires"), (int, float)) and c["expires"] > 0]
    return {"cookies": len(cookies), "origins": len(origins), "domains": domains,
            "earliest_expiry": min(expiries) if expiries else None}


class EncryptedSessionStore:
    """Encrypted browser sessions behind opaque ``session://`` refs.

    ``capture`` is called after a human finished login (incl. 2FA/CAPTCHA) in a takeover
    session: it encrypts the storage_state, mints a fresh session_ref and binds it in the
    ``SessionRegistry`` for exactly one workspace/provider/account binding.
    """

    kind = "encrypted"

    def __init__(self, path: Path, keyring: Keyring, registry: SessionRegistry):
        self._file = _EncryptedFile(path, keyring, "session")
        self._registry = registry

    def __repr__(self) -> str:
        return "EncryptedSessionStore()"

    def capture(self, *, workspace_id: str, provider: str, account_binding_id: str,
                storage_state: Mapping[str, Any]) -> str:
        scope = _scope(workspace_id, provider, account_binding_id)
        raw = _validate_storage_state(storage_state)
        previous = self._registry.resolve(*scope)
        session_ref = f"{SESSION_REF_PREFIX}{_secrets.token_hex(16)}"
        self._file.put(session_ref, scope, raw, meta=_state_summary(json.loads(raw)))
        self._registry.bind(SessionBinding(workspace_id, provider, account_binding_id, session_ref))
        if previous:
            self._file.delete(previous, scope)  # replaced session material is not kept
        return session_ref

    def load(self, session_ref: str, *, workspace_id: str, provider: str,
             account_binding_id: str) -> SecretState:
        scope = _scope(workspace_id, provider, account_binding_id)
        if self._registry.resolve(*scope) != session_ref:
            raise VaultError("session_ref not available for this binding")
        try:
            raw = self._file.get(session_ref, scope)
        except VaultError:
            raw = None
        if raw is None:
            raise VaultError("session_ref not available for this binding")
        return SecretState(json.loads(raw.decode("utf-8")))

    def entries(self, workspace_id: str) -> Tuple[Dict[str, Any], ...]:
        return tuple({
            "ref": e["id"], "provider": e["scope"][1], "account": e["scope"][2],
            "updated_at": e["updated_at"], "kid": e["kid"], **e["meta"],
        } for e in self._file.entries()
            if len(e["scope"]) == 3 and e["scope"][0] == workspace_id
            and self._registry.resolve(*e["scope"]) == e["id"])

    def check(self, *, workspace_id: str, provider: str, account_binding_id: str) -> Dict[str, Any]:
        """Decrypts in memory; returns counts, domains and earliest cookie expiry, no values."""
        scope = _scope(workspace_id, provider, account_binding_id)
        ref = self._registry.resolve(*scope)
        if not ref:
            return {"ok": False, "reason": "no_session"}
        try:
            state = self.load(ref, workspace_id=workspace_id, provider=provider,
                              account_binding_id=account_binding_id).reveal()
        except VaultError:
            return {"ok": False, "reason": "not_decryptable"}
        return {"ok": True, **_state_summary(state)}

    def set_agent_use(self, *, workspace_id: str, provider: str, account_binding_id: str, allowed: bool) -> bool:
        """T-560-L: owner switch. Off by default and again after every re-capture (new cookies = new consent)."""
        scope = _scope(workspace_id, provider, account_binding_id)
        ref = self._registry.resolve(*scope)
        return bool(ref and self._file.update_meta(ref, scope, {"agent_use": bool(allowed)}))

    def agent_use(self, *, workspace_id: str, provider: str, account_binding_id: str) -> bool:
        scope = _scope(workspace_id, provider, account_binding_id)
        ref = self._registry.resolve(*scope)
        return any(e["id"] == ref and e["scope"] == scope and e["meta"].get("agent_use") is True
                   for e in self._file.entries()) if ref else False

    def disconnect(self, *, workspace_id: str, provider: str, account_binding_id: str) -> bool:
        scope = _scope(workspace_id, provider, account_binding_id)
        current = self._registry.resolve(*scope)
        self._registry.disconnect(*scope)
        return bool(current and self._file.delete(current, scope))

    def reencrypt_all(self) -> int:
        return self._file.reencrypt_all()


def _token_vault_base():
    from oauth_framework import TokenSet, TokenVault  # local import: optional coupling
    return TokenSet, TokenVault


def make_token_vault(path: Path, keyring: Keyring):
    """Durable encrypted ``oauth_framework.TokenVault`` (storage half of T-552)."""
    TokenSet, TokenVault = _token_vault_base()

    class EncryptedTokenVault(TokenVault):
        kind = "encrypted"
        durable = True
        encrypted = True

        def __init__(self):
            self._file = _EncryptedFile(path, keyring, "oauth_token")

        def __repr__(self) -> str:
            return "EncryptedTokenVault()"

        @staticmethod
        def _id(workspace: str, provider: str) -> Tuple[str, Tuple[str, str]]:
            if not workspace or not provider:
                raise VaultError("workspace and provider are required")
            return f"oauth:{workspace}:{provider}", (workspace, provider)

        def put(self, workspace, provider, tokens):
            record_id, scope = self._id(workspace, provider)
            payload = {
                "access_token": tokens.access_token, "refresh_token": tokens.refresh_token,
                "expires_in": int(tokens.expires_in or 0), "scopes": list(tokens.scopes or ()),
                "account_id": tokens.account_id, "account_label": tokens.account_label,
            }
            self._file.put(record_id, scope, json.dumps(payload).encode("utf-8"))

        def get(self, workspace, provider):
            record_id, scope = self._id(workspace, provider)
            try:
                raw = self._file.get(record_id, scope)
            except VaultError:
                return None
            if raw is None:
                return None
            data = json.loads(raw.decode("utf-8"))
            data["scopes"] = tuple(data.get("scopes") or ())
            return TokenSet(**data)

        def delete(self, workspace, provider):
            record_id, scope = self._id(workspace, provider)
            return self._file.delete(record_id, scope)

        def reencrypt_all(self) -> int:
            return self._file.reencrypt_all()

    return EncryptedTokenVault()


def vault_status(data_dir: Optional[Path] = None, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    """Owner-visible projection: configured or not, why, and key ids in use. No secrets."""
    try:
        keyring = Keyring.from_env(env)
    except VaultConfigError as exc:
        return {"configured": False, "reason": str(exc), "algorithm": ALGORITHM}
    if keyring is None:
        return {"configured": False, "reason": f"{KEY_ENV} not set", "algorithm": ALGORITHM}
    out: Dict[str, Any] = {"configured": True, "algorithm": ALGORITHM, "primary_kid": keyring.primary_kid}
    if data_dir is not None:
        root = Path(data_dir) / "vault"
        out["records_by_kid"] = {
            name: _EncryptedFile(root / f"{name}.json", keyring, name).kids()
            for name in ("credential", "session", "oauth_token")
        }
    return out


def vault_paths(data_dir: Path) -> Dict[str, Path]:
    root = Path(data_dir) / "vault"
    return {
        "credential": root / "credential.json",
        "session": root / "session.json",
        "session_registry": root / "session_registry.json",
        "oauth_token": root / "oauth_token.json",
    }
