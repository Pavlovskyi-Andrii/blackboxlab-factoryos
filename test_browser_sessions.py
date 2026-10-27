"""Deterministic T-560-B isolation and takeover regression."""
from browser_runner.sessions import SessionBinding, SessionRegistry, challenge_checkpoint, authorize_resume


def main():
    registry = SessionRegistry()
    registry.bind(SessionBinding("ws-a", "x", "account", "session://a"))
    registry.bind(SessionBinding("ws-b", "x", "account", "session://b"))
    assert registry.resolve("ws-a", "x", "account") == "session://a"
    assert registry.resolve("ws-b", "x", "account") == "session://b"
    assert registry.resolve("ws-a", "instagram", "account") is None
    registry.disconnect("ws-a", "x", "account")
    assert registry.resolve("ws-a", "x", "account") is None
    assert registry.resolve("ws-b", "x", "account") == "session://b"

    cp = challenge_checkpoint("p1", "ws-b", "account", 3, "hash-1", "2fa")
    assert cp.state == "waiting_human" and cp.completed_steps == 3
    for args in [
        {"owner_authorized": False, "workspace_id": "ws-b", "account_binding_id": "account", "payload_hash": "hash-1"},
        {"owner_authorized": True, "workspace_id": "ws-a", "account_binding_id": "account", "payload_hash": "hash-1"},
        {"owner_authorized": True, "workspace_id": "ws-b", "account_binding_id": "account", "payload_hash": "changed"},
    ]:
        try:
            authorize_resume(cp, **args)
            raise AssertionError("unsafe resume was allowed")
        except PermissionError:
            pass
    resumed = authorize_resume(cp, owner_authorized=True, workspace_id="ws-b",
                               account_binding_id="account", payload_hash="hash-1")
    assert resumed.state == "resumed" and resumed.completed_steps == 3
    print("Browser session isolation and takeover tests passed")


if __name__ == "__main__":
    main()
