"""T-738: Claude worker offline alert policy (pure; no network, no Telegram)."""
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import worker_offline_alert as woa


def utc(text: str) -> float:
    return datetime.fromisoformat(text).replace(tzinfo=timezone.utc).timestamp()


class Harness:
    def __init__(self, ok=True):
        self.sent, self.ok = [], ok
        self.dir = tempfile.TemporaryDirectory()
        self.state = Path(self.dir.name) / "worker_offline_alert.json"

    def send(self, text, silent):
        self.sent.append((text, silent))
        return self.ok

    def tick(self, last_seen, now, started_at=0.0, supervisor=None, environ=None):
        return woa.tick(last_seen=last_seen, now=now, started_at=started_at, state_path=self.state,
                        send=self.send, supervisor=supervisor, environ=environ or {})


class WorkerOfflineAlertTest(unittest.TestCase):
    def setUp(self):
        self.h = Harness()
        self.addCleanup(self.h.dir.cleanup)

    def test_2026_11_24_incident_gets_one_silent_alert_and_one_back_message(self):
        last = utc("2026-11-24T22:05:48")
        self.assertEqual(self.h.tick(last, last + 14 * 60), "none")  # 14 min: still fine
        self.assertEqual(self.h.tick(last, last + 15 * 60), "offline")
        text, silent = self.h.sent[-1]
        self.assertIn("последний сигнал 25.11 00:05 по Киеву", text)  # 22:05 UTC = 00:05 Kyiv
        self.assertIn(woa.FIRST_CHECK, text)
        self.assertIn("MyCast", text)
        self.assertTrue(silent)  # 00:20 Kyiv: no sound
        for minutes in (16, 60, 17 * 60):  # the rest of the silence: nothing new
            self.assertEqual(self.h.tick(last, last + minutes * 60), "none")
        self.assertEqual(len(self.h.sent), 1)
        back = utc("2026-11-25T15:20:00")
        self.assertEqual(self.h.tick(back, back + 5), "back")
        text, silent = self.h.sent[-1]
        self.assertIn("снова на связи", text)
        self.assertIn("17 ч 14 мин", text)
        self.assertFalse(silent)  # 17:20 Kyiv
        self.assertEqual(self.h.tick(back, back + 65), "none")
        self.assertEqual(woa.load_state(self.h.state), {})

    def test_never_seen_worker_and_fresh_heartbeat_stay_quiet(self):
        now = utc("2026-11-25T10:00:00")
        self.assertEqual(self.h.tick(0, now), "none")
        self.assertEqual(self.h.tick(now - 30, now), "none")
        self.assertEqual(self.h.sent, [])

    def test_startup_grace_waits_for_the_worker_to_reach_a_new_server(self):
        last = utc("2026-11-25T09:00:00")
        started = last + 3600  # server restarted an hour later; the restored heartbeat is old
        self.assertEqual(self.h.tick(last, started + 60, started_at=started), "none")
        self.assertEqual(self.h.tick(last, started + woa.STARTUP_GRACE_SECONDS, started_at=started), "offline")

    def test_restart_with_saved_state_does_not_repeat_the_alert(self):
        last = utc("2026-11-25T09:00:00")
        self.assertEqual(self.h.tick(last, last + 1000), "offline")
        again = Harness()
        self.addCleanup(again.dir.cleanup)
        again.state = self.h.state  # same DATA_DIR file after a deploy
        self.assertEqual(again.tick(last, last + 9000, started_at=last + 5000), "none")
        self.assertEqual(again.sent, [])

    def test_failed_send_keeps_state_and_retries(self):
        h = Harness(ok=False)
        self.addCleanup(h.dir.cleanup)
        last = utc("2026-11-25T09:00:00")
        self.assertEqual(h.tick(last, last + 1000), "send_failed")
        self.assertEqual(woa.load_state(h.state), {})
        h.ok = True
        self.assertEqual(h.tick(last, last + 1060), "offline")
        self.assertEqual(len(h.sent), 2)

    def test_send_exception_is_contained(self):
        def boom(text, silent):
            raise RuntimeError("Telegram API sendMessage failed")
        last = utc("2026-11-25T09:00:00")
        result = woa.tick(last_seen=last, now=last + 1000, started_at=0, state_path=self.h.state, send=boom,
                          environ={})
        self.assertEqual(result, "send_failed")

    def test_kill_switch_and_threshold_bounds(self):
        last = utc("2026-11-25T09:00:00")
        self.assertEqual(self.h.tick(last, last + 9999, environ={woa.ENABLED_ENV: "0"}), "disabled")
        self.assertEqual(woa.offline_after({}), 900)
        self.assertEqual(woa.offline_after({woa.AFTER_ENV: "30"}), woa.MIN_AFTER_SECONDS)
        self.assertEqual(woa.offline_after({woa.AFTER_ENV: "999999"}), woa.MAX_AFTER_SECONDS)
        self.assertEqual(woa.offline_after({woa.AFTER_ENV: "soon"}), 900)
        self.assertEqual(self.h.tick(last, last + 1000, environ={woa.AFTER_ENV: "1800"}), "none")

    def test_supervisor_reason_is_shown_only_when_it_explains_the_silence(self):
        d = woa.Decision("offline", {}, utc("2026-11-25T09:00:00"), 1000)
        blocked = woa.offline_text(d, {"status": "blocked", "reason": "subscription_auth_required"})
        self.assertIn("Последний отчёт супервизора: blocked (subscription_auth_required).", blocked)
        self.assertNotIn("супервизора", woa.offline_text(d, {"status": "running", "reason": "service_active"}))
        self.assertNotIn("супервизора", woa.offline_text(d, None))

    def test_quiet_hours_follow_kyiv_time(self):
        self.assertTrue(woa.quiet(utc("2026-11-25T21:00:00")))  # 23:00 Kyiv
        self.assertTrue(woa.quiet(utc("2026-11-26T05:59:00")))  # 07:59 Kyiv
        self.assertFalse(woa.quiet(utc("2026-11-26T06:00:00")))  # 08:00 Kyiv
        self.assertFalse(woa.quiet(utc("2026-11-25T20:59:00")))  # 22:59 Kyiv

    def test_new_silence_after_recovery_is_reported_again(self):
        last = utc("2026-11-25T09:00:00")
        self.assertEqual(self.h.tick(last, last + 1000), "offline")
        self.assertEqual(self.h.tick(last + 1200, last + 1205), "back")
        self.assertEqual(self.h.tick(last + 1200, last + 1200 + 900), "offline")
        self.assertEqual([t.split()[0] for t, _ in self.h.sent], ["⚠️", "✅", "⚠️"])

    def test_corrupt_state_file_is_treated_as_empty(self):
        self.h.state.write_text("{not json", encoding="utf-8")
        last = utc("2026-11-25T09:00:00")
        self.assertEqual(self.h.tick(last, last + 1000), "offline")


if __name__ == "__main__":
    unittest.main()
