"""#237 Security Check findings: schema, mandatory redaction, consent-gated export. Synthetic fixtures only."""
import json

import security_findings as sf


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def valid(**over):
    base = {"rule_id": "AUTH-001", "title": "Owner route reachable without session", "severity": "high",
            "evidence_source": "static_analysis", "location": "app.py:/api/example (handler)", "reproducibility": "always",
            "uncertainty": "confirmed", "remediation": "Require the owner session on this route.",
            "user_consent_status": "granted", "target": "pilot_client_site"}
    base.update(over)
    return base


def test_valid_and_incomplete():
    finding, problems = sf.validate_finding(valid())
    require(problems == [] and finding["rule_id"] == "AUTH-001", f"valid finding rejected: {problems}")
    _, problems = sf.validate_finding({"rule_id": "AUTH-001"})
    require(len([p for p in problems if p.endswith("required")]) == len(sf.REQUIRED) - 1, f"missing fields: {problems}")
    for bad, msg in ((valid(severity="urgent"), "severity"), (valid(rule_id="auth 1"), "rule_id"),
                     (valid(user_consent_status="maybe"), "user_consent_status"), (valid(evidence_source="vibes"), "evidence_source"),
                     (valid(user_consent_status="not_required"), "only valid for target own_repository"),
                     (valid(uncertainty="confirmed", reproducibility="not_reproduced"), "cannot be confirmed")):
        finding, problems = sf.validate_finding(bad)
        require(finding is None and any(msg in p for p in problems), f"{msg}: {problems}")
    require(sf.validate_finding("not a dict") == (None, ["finding must be an object"]), "non-object")
    own, problems = sf.validate_finding(valid(user_consent_status="not_required", target="own_repository"))
    require(problems == [] and own, "own repository needs no third-party consent")


def test_redaction():
    secrets = {
        "telegram": "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsawQ",
        "github": "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2",
        "anthropic": "sk-ant-api03-abcdefghijklmnop",
        "openai": "sk-proj-abcdefghijklmnopqrstuvwxyz012345",
        "aws": "AKIA" + "ABCDEFGHIJKLMNOP",
        "jwt": "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "bearer": "Bearer abcdef0123456789abcdef",
        "kv": "api_key=Zx9-very-secret-value",
        "hex": "a" * 40,
    }
    for name, value in secrets.items():
        out = sf.redact(f"found {value} in config")
        require(value not in out and sf.REDACTED in out, f"{name} not redacted: {out}")
    text = ("contact admin@client-example.com; https://user:pw@api.client-example.com/v1?sig=SECRETSIG&x=1; "
            "http://10.0.3.7:8080/admin http://192.168.1.20/ http://172.20.0.4 http://127.0.0.1:5432 db.internal svc.local")
    out = sf.redact(text)
    for leak in ("admin@client-example.com", "user:pw", "SECRETSIG", "10.0.3.7", "192.168.1.20", "172.20.0.4", "127.0.0.1",
                 "db.internal", "svc.local"):
        require(leak not in out, f"{leak} leaked: {out}")
    require("https://api.client-example.com/v1" not in out and "api.client-example.com/v1?" in out, "public host kept, query masked")
    require(sf.redact(out) == out, "redaction must be idempotent")
    require(sf.redact("Plain text with 8.8.8.8 and example.com") == "Plain text with 8.8.8.8 and example.com",
            "public, non-secret text is left alone")
    # Validation redacts every string field, including nested details, before anything is stored.
    finding, problems = sf.validate_finding(valid(location="http://10.1.2.3/admin",
                                                  details={"evidence": ["token: " + secrets["github"], {"who": "ops@client.example"}]}))
    dumped = json.dumps(finding)
    require(problems == [] and secrets["github"] not in dumped and "10.1.2.3" not in dumped and "ops@client.example" not in dumped,
            f"finding not redacted: {dumped}")


def test_export_fails_closed():
    report = json.loads(sf.export_findings([valid(), valid(rule_id="DEP-12", severity="medium", uncertainty="likely")],
                                           audit_id="pilot-001"))
    require(report["read_only"] is True and len(report["findings"]) == 2, "consented export")
    for status in ("pending", "denied"):
        try:
            sf.export_findings([valid(), valid(user_consent_status=status)], audit_id="pilot-001")
            raise AssertionError(f"export with consent {status} must be refused")
        except PermissionError as exc:
            require(status in str(exc), str(exc))
    for bad in ([], [valid(severity="urgent")]):
        try:
            sf.export_findings(bad, audit_id="pilot-001")
            raise AssertionError("invalid export accepted")
        except ValueError:
            pass
    leaked = sf.export_findings([valid(remediation="rotate " + "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2")], audit_id="a@b.example")
    require("ghp_" not in leaked and "a@b.example" not in leaked, "export is redacted")


if __name__ == "__main__":
    test_valid_and_incomplete()
    test_redaction()
    test_export_fails_closed()
    print("Security Check findings schema, redaction and consent-gated export passed (synthetic fixtures, no scanning)")
