"""Credential-shaped text detector shared by the agent relay server and the Codex worker (no dependencies, so the
worker can be installed without the FactoryOS checkout and its .env)."""
import re

SECRET_SCAN = re.compile(
    r"sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}"
    r"|\b\d{6,12}:[A-Za-z0-9_-]{30,}\b|Bearer\s+[A-Za-z0-9._~+/=-]{12,}"
    r"|-----BEGIN [A-Z ]*PRIVATE KEY-----|\bAKIA[0-9A-Z]{16}\b|\bsk-[A-Za-z0-9_-]{20,}"
    r"|\bAIza[0-9A-Za-z_-]{30,}|\bxox[abpr]-[A-Za-z0-9-]{10,}"
    r"|(?i:\b[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)[A-Z0-9_]*\s*[:=]\s*['\"]?"
    r"(?=[A-Za-z_+/=-]*\d)[A-Za-z0-9_+/=-]{20,})"
)


def contains_secret(text) -> bool:
    return bool(SECRET_SCAN.search(str(text or "")))
