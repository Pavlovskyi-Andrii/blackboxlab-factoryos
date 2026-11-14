"""Zero-network tests for the disabled-by-default Paperclip -> Relay observe-only bridge (GitHub #368, S0b)."""
import hashlib
import importlib
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relay import RelayStore
from relay_execution import RelayQueue
from integrations.paperclip import BridgeSettings, MappingStore, PaperclipBridge, PaperclipClient, sign_event
from integrations.paperclip.bridge import loopback_url_problem

SECRET = "test-only-not-a-secret-0123456789abcdef"
NOW = 1_800_000_000


def _no_network(*args, **kwargs):
    raise AssertionError("network access attempted in an offline test")


class FakePaperclip:
    """Stands in for GET /api/issues/{id}; records every call."""

    def __init__(self, known=("PC-1", "PC-2", "PC-3"), script=None):
        self.known = set(known)
        self.script = list(script or [])
        self.calls = []

    def __call__(self, method, url, headers, timeout):
        self.calls.append((method, url, timeout))
        assert method == "GET", "bridge must never write to Paperclip"
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, BaseException):
                raise step
            return step, b""
        return (200 if url.rsplit("/", 1)[-1] in self.known else 404), b"{}"


class BridgeCase(unittest.TestCase):
    def setUp(self):
        guard = patch.multiple(socket, socket=_no_network, create_connection=_no_network)
        guard.start()
        self.addCleanup(guard.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.relay_path = root / "relay.json"
        self.relay = RelayStore(self.relay_path)
        self.claude_ticket, _ = self.relay.create("Claude task", "body", owner="claude")
        self.gemini_ticket, _ = self.relay.create("Gemini task", "body", owner="gemini")
        self.other_claude, _ = self.relay.create("Second Claude task", "body", owner="claude")
        self.settings = BridgeSettings(enabled=True, base_url="http://127.0.0.1:3100", state_path=str(root / "bridge" / "map.json"),
                                       secret=SECRET, max_retries=1, timeout_s=1.0, rate_per_minute=60)
        self.fake = FakePaperclip()
        self.sleeps = []
        self.bridge = self.make_bridge()

    def make_bridge(self, settings=None, fake=None):
        settings = settings or self.settings
        client = PaperclipClient(settings, transport=fake or self.fake, sleep=self.sleeps.append)
        return PaperclipBridge(settings, self.relay.get, client=client, clock=lambda: NOW)

    def relay_digest(self):
        return hashlib.sha256(self.relay_path.read_bytes()).hexdigest()

    @staticmethod
    def event(event_id="evt-00000001", kind="issue.wake", issue="PC-1", relay_id=None, occurred=NOW - 10, **issue_extra):
        issue_body = {"id": issue, "company_id": "co-1", "run_id": "run-9", "relay_ticket_id": relay_id}
        issue_body.update(issue_extra)
        return json.dumps({"event_id": event_id, "type": kind, "occurred_at": occurred, "issue": issue_body}).encode()

    def send(self, raw, bridge=None, secret=SECRET, stamp=NOW):
        headers = {"X-Paperclip-Timestamp": str(stamp), "X-Paperclip-Signature": sign_event(secret, str(stamp), raw)}
        return (bridge or self.bridge).handle_event(headers, raw)


class TestValidMapping(BridgeCase):
    def test_valid_event_proposes_read_only_mapping(self):
        before = self.relay_digest()
        status, body = self.send(self.event(relay_id=self.claude_ticket["id"]))
        self.assertEqual((status, body["code"]), (200, "mapping_proposed"))
        mapping = body["mapping"]
        self.assertEqual(mapping["mode"], "observe_only")
        self.assertEqual(mapping["state"], "proposed")
        chain = mapping["relay"]
        self.assertEqual(chain["relay_ticket_id"], self.claude_ticket["id"])
        self.assertEqual(chain["paperclip_issue_id"], "PC-1")
        self.assertEqual(chain["paperclip_run_id"], "run-9")
        self.assertEqual(chain["relay_stage"], "queued")          # queued, not claimed
        self.assertEqual(chain["relay_run_id"], "")
        self.assertEqual(chain["evidence_level"], "claimed")       # agent words only
        self.assertFalse(chain["verified"])
        self.assertEqual(body["relay_side_effects"], "none")
        self.assertEqual(self.relay_digest(), before, "Relay store must not change")
        ticket = self.relay.get(self.claude_ticket["id"])
        self.assertEqual(ticket["execution"]["state"], "queued")
        self.assertEqual(ticket["execution"]["attempts"], 0)
        self.assertEqual(self.fake.calls[0][0], "GET")

    def test_claimed_by_relay_worker_reported_as_claimed_not_done(self):
        claimed = RelayQueue(self.relay).claim("aws-worker")      # Relay's own worker, not the bridge
        self.assertEqual(claimed["id"], self.claude_ticket["id"])
        run_id = self.relay.get(self.claude_ticket["id"])["execution"]["run_id"]
        status, body = self.send(self.event(relay_id=self.claude_ticket["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(body["mapping"]["relay"]["relay_stage"], "claimed")
        self.assertTrue(run_id)
        self.assertEqual(body["mapping"]["relay"]["relay_run_id"], run_id)
        self.assertFalse(body["mapping"]["relay"]["verified"])

    def test_mapping_file_has_no_secret(self):
        self.send(self.event(relay_id=self.claude_ticket["id"]))
        text = Path(self.settings.state_path).read_text("utf-8")
        self.assertNotIn(SECRET, text)
        self.assertNotIn(SECRET, repr(self.settings))


class TestIdempotency(BridgeCase):
    def test_duplicate_replay_creates_no_second_item(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        first = self.send(raw)
        calls = len(self.fake.calls)
        second = self.send(raw)
        self.assertEqual(second[0], 200)
        self.assertEqual(second[1]["code"], "duplicate_event")
        self.assertEqual(second[1]["mapping"]["mapping_id"], first[1]["mapping"]["mapping_id"])
        self.assertEqual(len(self.fake.calls), calls, "replay must not call Paperclip again")
        state = json.loads(Path(self.settings.state_path).read_text("utf-8"))
        self.assertEqual(len(state["mappings"]), 1)

    def test_replay_after_restart_keeps_mapping(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        first = self.send(raw)
        restarted = self.make_bridge()                      # fresh process, same state file
        status, body = self.send(raw, bridge=restarted)
        self.assertEqual((status, body["code"]), (200, "duplicate_event"))
        self.assertEqual(body["mapping"]["mapping_id"], first[1]["mapping"]["mapping_id"])

    def test_double_claim_of_one_relay_ticket_rejected(self):
        self.send(self.event(relay_id=self.claude_ticket["id"]))
        status, body = self.send(self.event("evt-00000002", issue="PC-2", relay_id=self.claude_ticket["id"]))
        self.assertEqual((status, body["code"]), (409, "double_claim_rejected"))

    def test_paperclip_issue_cannot_be_remapped(self):
        self.send(self.event(relay_id=self.claude_ticket["id"]))
        status, body = self.send(self.event("evt-00000002", relay_id=self.other_claude["id"]))
        self.assertEqual((status, body["code"]), (409, "paperclip_issue_already_mapped"))

    def test_stale_event_rejected(self):
        self.send(self.event(relay_id=self.claude_ticket["id"], occurred=NOW - 10))
        status, body = self.send(self.event("evt-00000002", relay_id=self.claude_ticket["id"], occurred=NOW - 100))
        self.assertEqual((status, body["code"]), (409, "stale_event"))

    def test_cancellation_withdraws_only_the_proposal(self):
        self.send(self.event(relay_id=self.claude_ticket["id"]))
        before = self.relay_digest()
        status, body = self.send(self.event("evt-00000002", kind="issue.cancelled", relay_id=self.claude_ticket["id"]))
        self.assertEqual((status, body["code"]), (200, "proposal_cancelled"))
        self.assertEqual(body["mapping"]["state"], "cancelled")
        self.assertEqual(self.relay_digest(), before)
        self.assertEqual(self.relay.get(self.claude_ticket["id"])["execution"]["state"], "queued")
        # Once withdrawn, another Paperclip issue may propose for the same ticket.
        status, _ = self.send(self.event("evt-00000003", issue="PC-2", relay_id=self.claude_ticket["id"]))
        self.assertEqual(status, 200)

    def test_cancel_unknown_mapping(self):
        status, body = self.send(self.event(kind="issue.cancelled", relay_id=self.claude_ticket["id"]))
        self.assertEqual((status, body["code"]), (404, "nothing_to_cancel"))


class TestRejections(BridgeCase):
    def assertRejected(self, result, status, code):
        self.assertEqual((result[0], result[1]["code"]), (status, code))
        self.assertFalse(Path(self.settings.state_path).exists(), "rejected event must not persist a mapping")

    def test_unauthenticated_event(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        self.assertRejected(self.bridge.handle_event({}, raw), 401, "unauthenticated")

    def test_wrong_signature(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        self.assertRejected(self.send(raw, secret="x" * 40), 401, "unauthenticated")

    def test_body_tampered_after_signing(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        headers = {"X-Paperclip-Timestamp": str(NOW), "X-Paperclip-Signature": sign_event(SECRET, str(NOW), raw)}
        tampered = raw.replace(b"PC-1", b"PC-2")
        self.assertRejected(self.bridge.handle_event(headers, tampered), 401, "unauthenticated")

    def test_stale_signature_timestamp(self):
        raw = self.event(relay_id=self.claude_ticket["id"])
        self.assertRejected(self.send(raw, stamp=NOW - 3600), 401, "stale_signature")

    def test_wrong_owner(self):
        self.assertRejected(self.send(self.event(relay_id=self.gemini_ticket["id"])), 409, "unexpected_task_owner")

    def test_forged_relay_id(self):
        self.assertRejected(self.send(self.event(relay_id="R-9999")), 404, "unknown_relay_ticket")

    def test_forged_paperclip_issue(self):
        self.assertRejected(self.send(self.event(issue="PC-404", relay_id=self.claude_ticket["id"])), 404,
                            "unknown_paperclip_issue")

    def test_invalid_data(self):
        cases = [
            (self.event(relay_id="../relay.json"), "invalid_relay_ticket_id"),
            (self.event(issue="PC 1; rm -rf /", relay_id=self.claude_ticket["id"]), "invalid_paperclip_issue_id"),
            (self.event(kind="issue.checkout", relay_id=self.claude_ticket["id"]), "unsupported_event_type"),
            (self.event(event_id="x", relay_id=self.claude_ticket["id"]), "invalid_event_id"),
            (self.event(relay_id=self.claude_ticket["id"], occurred="yesterday"), "invalid_occurred_at"),
            (self.event(relay_id=self.claude_ticket["id"], run_id={"$ne": 1}), "invalid_run_id"),
        ]
        for raw, code in cases:
            with self.subTest(code=code):
                self.assertRejected(self.send(raw), 400, code)

    def test_malformed_payload(self):
        self.assertRejected(self.send(b"{not json"), 400, "malformed_json")
        self.assertRejected(self.send(b"[1, 2]"), 400, "malformed_payload")
        self.assertRejected(self.send(b"\xff\xfe"), 400, "malformed_json")
        self.assertRejected(self.send(b"x" * 20000), 413, "payload_too_large")

    def test_rate_limit(self):
        settings = BridgeSettings(**{**self.settings.__dict__, "rate_per_minute": 2})
        bridge = self.make_bridge(settings)
        codes = [self.send(self.event("evt-0000000%d" % i, relay_id="bad"), bridge=bridge)[0] for i in range(3)]
        self.assertEqual(codes, [400, 400, 429])


class TestPaperclipFailure(BridgeCase):
    def test_unavailable_paperclip_fails_closed(self):
        fake = FakePaperclip(script=[ConnectionRefusedError(), ConnectionRefusedError()])
        result = self.send(self.event(relay_id=self.claude_ticket["id"]), bridge=self.make_bridge(fake=fake))
        self.assertEqual((result[0], result[1]["code"], result[1]["reason"]), (503, "paperclip_unavailable", "unavailable"))
        self.assertEqual(len(fake.calls), 2)                  # 1 try + max_retries=1
        self.assertFalse(Path(self.settings.state_path).exists())

    def test_timeout_retry_then_success(self):
        fake = FakePaperclip(script=[TimeoutError(), 200])
        result = self.send(self.event(relay_id=self.claude_ticket["id"]), bridge=self.make_bridge(fake=fake))
        self.assertEqual(result[0], 200)
        self.assertEqual(len(fake.calls), 2)
        self.assertTrue(all(call[2] == 1.0 for call in fake.calls))
        self.assertEqual(len(self.sleeps), 1)
        self.assertLessEqual(self.sleeps[0], 2.0)

    def test_timeout_exhausts_capped_retries(self):
        fake = FakePaperclip(script=[TimeoutError()] * 10)
        result = self.send(self.event(relay_id=self.claude_ticket["id"]), bridge=self.make_bridge(fake=fake))
        self.assertEqual((result[0], result[1]["reason"]), (503, "timeout"))
        self.assertEqual(len(fake.calls), 2)

    def test_auth_error_from_paperclip_not_retried(self):
        fake = FakePaperclip(script=[403])
        result = self.send(self.event(relay_id=self.claude_ticket["id"]), bridge=self.make_bridge(fake=fake))
        self.assertEqual((result[0], result[1]["reason"]), (503, "http_403"))
        self.assertEqual(len(fake.calls), 1)

    def test_retry_caps_clamped_from_env(self):
        settings = BridgeSettings.from_env({"PAPERCLIP_BRIDGE_MAX_RETRIES": "50", "PAPERCLIP_BRIDGE_TIMEOUT_S": "600",
                                            "PAPERCLIP_BRIDGE_RATE_PER_MIN": "100000"})
        self.assertEqual((settings.max_retries, settings.timeout_s, settings.rate_per_minute), (2, 10.0, 60))


class TestSecureDefaults(BridgeCase):
    def test_disabled_by_default(self):
        settings = BridgeSettings.from_env({})
        self.assertFalse(settings.enabled)
        bridge = PaperclipBridge(settings, self.relay.get)
        status, body = bridge.handle_event({}, self.event(relay_id=self.claude_ticket["id"]))
        self.assertEqual((status, body["code"]), (503, "bridge_closed"))
        self.assertIn("disabled", body["reasons"])

    def test_enabled_but_missing_settings_fails_closed(self):
        settings = BridgeSettings.from_env({"PAPERCLIP_BRIDGE_ENABLED": "1"})
        self.assertEqual(set(settings.problems()), {"secret_missing", "state_path_missing", "base_url_missing"})

    def test_only_loopback_ip_allowed(self):
        self.assertEqual(loopback_url_problem("http://127.0.0.1:3100"), "")
        for url in ("http://0.0.0.0:3100", "http://localhost:3100", "https://127.0.0.1:3100", "http://10.0.0.5:3100",
                    "http://127.0.0.1", "http://user:pw@127.0.0.1:3100", "http://127.0.0.1:3100/api",
                    "http://169.254.169.254:80", "http://example.com:3100"):
            with self.subTest(url=url):
                self.assertTrue(loopback_url_problem(url))

    def test_import_opens_no_network_and_app_does_not_import_bridge(self):
        sys.modules.pop("integrations.paperclip.bridge", None)
        importlib.import_module("integrations.paperclip.bridge")   # socket guard is active
        app_source = Path(__file__).with_name("app.py").read_text("utf-8")
        self.assertNotIn("paperclip", app_source.lower())

    def test_no_real_work_triggered_across_full_flow(self):
        before = self.relay_digest()
        for i, kind in enumerate(("issue.wake", "issue.updated", "issue.cancelled")):
            self.send(self.event("evt-1000000%d" % i, kind=kind, relay_id=self.claude_ticket["id"], occurred=NOW - 30 + i))
        self.assertEqual(self.relay_digest(), before)
        self.assertTrue(all(call[0] == "GET" for call in self.fake.calls))
        for ticket in self.relay.list():
            self.assertEqual(ticket["execution"]["state"], "queued")
            self.assertEqual(len(ticket["history"]), 1)

    def test_mapping_store_rejects_corrupt_state(self):
        path = Path(self.settings.state_path)
        path.parent.mkdir(parents=True)
        path.write_text("[]", "utf-8")
        with self.assertRaises(ValueError):
            MappingStore(path).load()


if __name__ == "__main__":
    unittest.main()
