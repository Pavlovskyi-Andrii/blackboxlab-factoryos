"""T-560-A deterministic zero-secret browser runner regression."""
from dataclasses import replace

from browser_runner import (
    BrowserActionPlan,
    approval_matches,
    canonical_payload_hash,
    redact,
    run_mock,
)


def plan(*, action_class="draft", steps=(), **kwargs):
    return BrowserActionPlan(
        plan_id="plan-1",
        workspace_id="ws-a",
        provider="example",
        account_binding_id="acct-1",
        action_class=action_class,
        steps=tuple(steps),
        session_ref="session://ws-a/example/acct-1",
        **kwargs,
    )


def redaction_checks():
    raw = {
        "password": "hunter2",
        "nested": {"api_key": "abc", "session_ref": "session://safe-ref"},
        "header": "Bearer secret-token",
        "caption": "hello",
    }
    clean = redact(raw)
    assert clean["password"] == "***REDACTED***"
    assert clean["nested"]["api_key"] == "***REDACTED***"
    assert clean["nested"]["session_ref"] == "session://safe-ref"
    assert clean["header"] == "***REDACTED***"
    assert clean["caption"] == "hello"


def validation_checks():
    bad = plan(steps=({"type": "shell", "command": "rm -rf /"},))
    result = run_mock(bad)
    assert result.status == "blocked" and "unsupported step type" in result.blocker_reason

    secret = plan(steps=({"type": "fill", "selector": "#password", "password": "plaintext"},))
    result = run_mock(secret)
    assert result.status == "blocked" and "plaintext secret material" in result.blocker_reason

    off_scheme = plan(steps=({"type": "navigate", "url": "file:///etc/passwd"},))
    result = run_mock(off_scheme)
    assert result.status == "blocked" and "http(s)" in result.blocker_reason


def hash_checks():
    base = plan(steps=({"type": "fill", "selector": "#caption", "value": "hello"},))
    first = canonical_payload_hash(base)
    second = canonical_payload_hash(base)
    changed = canonical_payload_hash(replace(base, steps=({"type": "fill", "selector": "#caption", "value": "changed"},)))
    assert first == second and first != changed

    approved = replace(base, approval_snapshot_id="approval-1", approved_payload_hash=first)
    assert approval_matches(approved)
    assert not approval_matches(replace(approved, approved_payload_hash="0" * 64))


def approval_checks():
    publish = plan(
        action_class="publish",
        steps=(
            {"type": "navigate", "url": "https://example.com/compose"},
            {"type": "fill", "selector": "#caption", "value": "hello"},
            {"type": "submit", "selector": "button.publish"},
        ),
    )
    blocked = run_mock(publish)
    assert blocked.status == "blocked" and blocked.completed_steps == 0
    assert "approval" in blocked.blocker_reason

    wrong = replace(publish, approval_snapshot_id="approval-1", approved_payload_hash="0" * 64)
    assert run_mock(wrong).status == "blocked"

    approved = replace(
        publish,
        approval_snapshot_id="approval-1",
        approved_payload_hash=canonical_payload_hash(publish),
    )
    done = run_mock(approved)
    assert done.status == "done" and done.completed_steps == 3
    assert done.final_url == "https://example.com/compose"
    assert done.external_receipt == ""

    draft_submit = plan(steps=({"type": "submit", "selector": "#save"},))
    assert run_mock(draft_submit).status == "blocked", "submit is approval-gated even for draft plans"


def evidence_checks():
    draft = plan(
        steps=(
            {"type": "navigate", "url": "https://example.com/editor"},
            {"type": "fill", "selector": "#caption", "value": "draft text"},
            {"type": "screenshot", "label": "prepared"},
        )
    )
    done = run_mock(draft)
    assert done.status == "done" and done.completed_steps == 3
    assert all(item["status"] == "simulated" for item in done.action_log)
    assert "draft text" in str(done.action_log)
    assert "receipt" not in str(done.action_log).lower()


def main():
    redaction_checks()
    validation_checks()
    hash_checks()
    approval_checks()
    evidence_checks()
    print("Browser Action Runner policy tests passed")


if __name__ == "__main__":
    main()
