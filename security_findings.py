"""Security Check findings (#237, epic #98): one schema for read-only audit findings, mandatory redaction before a
finding is stored or exported, and an export that fails closed without the audited party's consent.

Offline only: this module never scans anything. Callers hand it findings; it validates, redacts and packages them.
"""
from __future__ import annotations

import json
import re
from typing import Any

from owner_desk import _SECRET_PATTERNS as _TOKEN_PATTERNS  # one list of known token shapes for the whole repo

SEVERITIES = ("info", "low", "medium", "high", "critical")
REPRODUCIBILITY = ("always", "intermittent", "not_reproduced")
UNCERTAINTY = ("confirmed", "likely", "possible")
CONSENT = ("granted", "pending", "denied", "not_required")  # not_required: our own repository only
EVIDENCE_SOURCES = ("static_analysis", "dependency_advisory", "configuration_review", "manual_review", "test_run")
REQUIRED = ("rule_id", "title", "severity", "evidence_source", "location", "reproducibility", "uncertainty",
            "remediation", "user_consent_status", "target")
REDACTED = "[redacted]"

_RULE_ID = re.compile(r"^[A-Z][A-Z0-9]{1,15}-\d{1,4}$")  # e.g. AUTH-001, DEP-12
_EXTRA = (
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{12,}", re.I),                     # Authorization header values
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),  # JWT
    re.compile(r"\b(?:sk|rk|pk)_(?:live|test)_[A-Za-z0-9]{12,}"),                 # Stripe-style keys
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),                                       # OpenAI-style keys
    re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),                                # Slack tokens
    re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key)\s*[:=]\s*['\"]?(?!\[)[^\s'\"&]{6,}"),  # key=value secrets (not an already-masked value)
    re.compile(r"\b[0-9a-f]{40,}\b", re.I),                                       # long hex (keys, signed digests)
)
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_URL_USERINFO = re.compile(r"(?i)\b(https?://)[^/\s@]+@")
_URL_QUERY = re.compile(r"(?i)\b(https?://[^\s?#]+)\?[^\s#]*")  # query strings often carry signatures and tokens
_PRIVATE_HOST = re.compile(
    r"(?i)\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|169\.254\.\d{1,3}\.\d{1,3}|localhost|[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:internal|local|lan|corp))\b")


def redact(value: Any) -> str:
    """Mask tokens, credentials, emails, URL credentials/queries and internal addresses. Idempotent."""
    text = str(value if value is not None else "")
    for pattern in _TOKEN_PATTERNS + _EXTRA:
        text = pattern.sub(REDACTED, text)
    text = _URL_USERINFO.sub(lambda m: m.group(1) + REDACTED + "@", text)
    text = _URL_QUERY.sub(lambda m: m.group(1) + "?" + REDACTED, text)
    text = _EMAIL.sub("[email]", text)
    text = _PRIVATE_HOST.sub("[internal-host]", text)
    return text


def _redact_tree(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _redact_tree(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_tree(v) for v in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return redact(value)


def validate_finding(raw: Any) -> tuple[dict | None, list[str]]:
    """Returns (redacted finding, problems). A finding with problems is never stored or exported."""
    if not isinstance(raw, dict):
        return None, ["finding must be an object"]
    problems = [f"{field}: required" for field in REQUIRED if not str(raw.get(field) or "").strip()]
    checks = (("severity", SEVERITIES), ("reproducibility", REPRODUCIBILITY), ("uncertainty", UNCERTAINTY),
              ("user_consent_status", CONSENT), ("evidence_source", EVIDENCE_SOURCES))
    for field, allowed in checks:
        if raw.get(field) and raw.get(field) not in allowed:
            problems.append(f"{field}: must be one of {', '.join(allowed)}")
    if raw.get("rule_id") and not _RULE_ID.fullmatch(str(raw["rule_id"])):
        problems.append("rule_id: format like AUTH-001")
    if raw.get("user_consent_status") == "not_required" and raw.get("target") != "own_repository":
        problems.append("user_consent_status: not_required is only valid for target own_repository")
    if raw.get("uncertainty") == "confirmed" and raw.get("reproducibility") == "not_reproduced":
        problems.append("uncertainty: a finding that was not reproduced cannot be confirmed")
    finding = _redact_tree({k: raw.get(k) for k in REQUIRED + ("details",) if k in raw})
    return (None if problems else finding), problems


def export_findings(findings: list, *, audit_id: str) -> str:
    """JSON report for the audited party. Fails closed: every finding must be valid and consented."""
    if not findings:
        raise ValueError("no findings to export")
    out = []
    for n, raw in enumerate(findings, 1):
        finding, problems = validate_finding(raw)
        if problems:
            raise ValueError(f"finding {n} invalid: {'; '.join(problems)}")
        if finding["user_consent_status"] not in ("granted", "not_required"):
            raise PermissionError(f"finding {n}: consent is {finding['user_consent_status']}; export refused")
        out.append(finding)
    report = {"audit_id": redact(audit_id), "read_only": True, "findings": out}
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if redact(text) != text:  # belt and braces: nothing sensitive may survive into the export
        raise ValueError("export still contains sensitive values after redaction")
    return text
