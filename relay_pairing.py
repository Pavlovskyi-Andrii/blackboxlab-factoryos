"""Owner-initiated Relay worker credential rotation; never store plaintext secrets.

The owner-only HTTPS endpoint displays each newly generated bearer token only in
its creation response. That token remains valid for worker polling until rotated;
it is NOT a single-use or short-lived bootstrap token. Generating a new token
revokes the previously paired token. The persistent file contains only a
SHA-256 digest. No new cloud resource, API billing, email or log is involved.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets


def create_pairing(path: Path) -> dict:
    path = Path(path)
    token = secrets.token_urlsafe(36)
    timestamp = datetime.now(timezone.utc).isoformat()
    stored = {
        "version": 1,
        "digest": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "created_at": timestamp,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(stored) + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    os.replace(tmp, path)
    path.chmod(0o600)
    return {"token": token, "created_at": timestamp}


def valid_pairing(path: Path, token: str) -> bool:
    if not isinstance(token, str) or len(token) < 40:
        return False
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    digest = str(data.get("digest") or "") if isinstance(data, dict) else ""
    if len(digest) != 64:
        return False
    candidate = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(candidate, digest)


def pairing_status(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"configured": False, "created_at": None}
    if not isinstance(data, dict):
        return {"configured": False, "created_at": None}
    return {"configured": len(str(data.get("digest") or "")) == 64,
            "created_at": data.get("created_at")}
