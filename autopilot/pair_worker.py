"""One-time local pairing of an existing EC2 subscription worker with FactoryOS.

This CLI is deliberately interactive and root-only. The secret never appears in
the argv list, terminal history, Git, HTTP logs, or output; user copies it from
the owner-only FactoryOS Connections dialog. No paid API credentials are used.
"""
from __future__ import annotations

import getpass
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

from autopilot.supervisor import PAID_KEYS

DEFAULT_ENV = Path("/etc/factoryos/claude-worker.env")
KEY = "FACTORY_CLAUDE_WORKER_TOKEN"
ROOT_UID = 0
SUPERVISOR_SERVICE = "factoryos-runner-supervisor.service"
# Same list the supervisor refuses to run with, so pairing and preflight agree.
_FORBIDDEN = PAID_KEYS
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,256}$")
# Anthropic API keys also match the token alphabet; never store one by mistake.
_ANTHROPIC_KEY_PREFIX = "sk-ant-"


class PairingError(ValueError):
    pass


def _line_key(raw: str) -> str:
    line = raw.strip()
    if not line or line.startswith("#") or "=" not in line:
        return ""
    return line.split("=", 1)[0].strip()


def _configured_values(lines: list[str]) -> dict[str, str]:
    items = {}
    for raw in lines:
        key = _line_key(raw)
        if key:
            items[key] = raw.split("=", 1)[1].strip().strip("\"'")
    return items


def pair_token(path: Path, token: str) -> None:
    """Atomic secret write; preserves all other settings and file permissions."""
    path = Path(path)
    if not isinstance(token, str) or not _TOKEN_RE.fullmatch(token):
        raise PairingError("invalid_factoryos_worker_token_format")
    if token.startswith(_ANTHROPIC_KEY_PREFIX):
        raise PairingError("anthropic_api_key_not_accepted")
    if path.is_symlink() or not path.is_file():
        raise PairingError("worker_env_not_regular_file")
    stat = path.stat()
    if stat.st_mode & 0o077:
        raise PairingError("worker_env_permissions_too_open")
    if stat.st_uid != ROOT_UID:
        raise PairingError("worker_env_not_owned_by_root")
    parent = path.parent.stat()
    if parent.st_uid != ROOT_UID or parent.st_mode & 0o022:
        raise PairingError("worker_env_directory_not_protected")
    try:
        content = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise PairingError("worker_env_not_utf8") from None
    lines = content.splitlines()
    before = _configured_values(lines)
    if any(before.get(k) for k in _FORBIDDEN):
        raise PairingError("paid_api_override_present")
    safe_lines = [line for line in lines if _line_key(line) != KEY]
    safe_lines.append(KEY + "=" + token)
    fd, temporary = tempfile.mkstemp(prefix=".claude-worker-", dir=str(path.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(safe_lines) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chown(temporary, stat.st_uid, stat.st_gid)
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> int:
    if os.geteuid() != ROOT_UID:
        print("Run via sudo on the existing trusted EC2 host.", file=sys.stderr)
        return 2
    if not sys.stdin.isatty():
        print("Interactive terminal required; refusing piped/CLI secrets.", file=sys.stderr)
        return 2
    print("FactoryOS internal worker pairing. No Anthropic API billing.")
    try:
        token = getpass.getpass("Paste FactoryOS worker token (hidden): ").strip()
        pair_token(DEFAULT_ENV, token)
    except (KeyboardInterrupt, EOFError):
        print("\nPairing cancelled; nothing saved.", file=sys.stderr)
        return 2
    except (PairingError, OSError) as exc:
        print("Pairing blocked: " + (
            str(exc) if isinstance(exc, PairingError) else "configuration_error"
        ), file=sys.stderr)
        return 2
    finally:
        token = ""
    print("Internal token saved in the protected worker environment file.")
    # The local supervisor performs the OAuth and PAYG preflight again. No
    # direct systemctl start of Claude or any browser/publisher service here.
    service = subprocess.run(
        ["systemctl", "start", SUPERVISOR_SERVICE],
        capture_output=True, text=True, check=False, timeout=60,
    )
    if service.returncode:
        print("Saved, but supervisor check could not start. Inspect systemd status.")
        return 1
    print("Supervisor check requested. Verify worker state in FactoryOS.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
