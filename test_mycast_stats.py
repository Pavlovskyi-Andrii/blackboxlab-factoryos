"""T-746: owner statistics of MyCast listening — who gets episodes, for how long, who drops off. Offline."""
import json
import re
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

import mycast_stats
from mycast_stats import build, install_mycast_stats_routes, listener_row

ROOT = Path(__file__).resolve().parent
NOW = 1_800_000_000            # 2027-01-15 UTC
DAY = 86400


def day(offset):
    return time.strftime("%Y-%m-%d", time.gmtime(NOW + offset * DAY))


def listener(slug, *, created=-20, episodes=(), active=True, paused="", code=True, chat=True, approved=True,
             failures=(), plays=None, acq=None, reason="HTTPError:Forbidden"):
    rec = {"slug": slug, "name": slug.title() + " Surname", "provider": "telegram", "key": "secret-key-" + slug,
           "created": NOW + created * DAY, "code": "CODE" if code else "", "chat_id": "777" if chat else ""}
    if approved and code:
        rec["approved_code"] = "CODE"
    rec["delivery"] = {"active": active, **({"paused_reason": paused} if paused else {})}
    rec["deliveries"] = {day(o): {"status": "sent", "seconds": 600, "file_id": "F" + str(o)} for o in episodes}
    for o in failures:
        rec["deliveries"][day(o)] = {"status": "failed", "failures": 2, "reason": reason}
    if plays:
        rec["plays"] = plays
    if acq:
        rec["acq"] = acq
    return rec


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.people = [
            listener("nopod", code=False, episodes=()),
            listener("notg", chat=False),
            listener("fresh", episodes=(-2, -1, 0)),
            listener("loyal", episodes=range(-12, 1), plays={"own": 3, "shared": 2, "last_own_at": NOW - DAY}, acq={"channel": "tg"}),
            listener("quick", episodes=(-10, -9), active=False, paused="listener_stopped"),
            listener("later", episodes=range(-15, -8), active=False, paused="listener_stopped"),
            listener("broken", episodes=(-6, -5, -4, -3), failures=(-2, -1)),
            listener("oops", episodes=(-9, -8, -7, -6, -5, -4, -3), failures=(-2, -1), reason="TimeoutError:"),
        ]
        self.rep = build(self.people, {"deleted": {"total": 2, "by_days": {"0-2": 1, "14+": 1}, "had_episode": 1}}, NOW)
        self.rows = {r["slug"]: r for r in self.rep["listeners"]}

    def test_segments(self):
        seg = {s: r["segment"] for s, r in self.rows.items()}
        self.assertEqual(seg, {"nopod": "never_started", "notg": "never_started", "fresh": "listening_new",
                               "loyal": "listening_long", "quick": "dropped_early", "later": "stopped_later",
                               "broken": "stopped_later", "oops": "listening_long"})   # our failure is not leaving
        self.assertEqual(self.rep["segments"], {"never_started": 2, "dropped_early": 1, "stopped_later": 2,
                                                "listening_new": 1, "listening_long": 2})

    def test_rows_count_minutes_and_status(self):
        loyal = self.rows["loyal"]
        self.assertEqual((loyal["episodes"], loyal["minutes"], loyal["listening_span_days"]), (13, 130.0, 13))
        self.assertEqual((loyal["site_plays"], loyal["shared_plays"], loyal["channel"]), (3, 2, "tg"))
        self.assertEqual(self.rows["quick"]["setup"], "stopped_by_listener")
        self.assertEqual(self.rows["broken"]["setup"], "blocked_bot")
        self.assertEqual(self.rows["oops"]["setup"], "delivery_failing")
        self.assertIn("Forbidden", self.rows["broken"]["last_failure"])
        self.assertEqual(self.rows["notg"]["setup"], "telegram_not_linked")
        self.assertEqual(self.rows["loyal"]["first_name"], "Loyal")

    def test_funnel_retention_and_deleted(self):
        funnel = {f["step"]: f["count"] for f in self.rep["funnel"]}
        self.assertEqual(funnel, {"registered": 8, "podcast_set_up": 7, "telegram_linked": 6, "first_episode": 6,
                                  "three_days": 4, "seven_days": 1, "played_on_site": 1})   # "later" has exactly 7 days, not more
        ret = {r["day"]: (r["eligible"], r["still_receiving"]) for r in self.rep["retention"]}
        self.assertEqual(ret[3], (5, 4))
        self.assertEqual(self.rep["deleted_accounts"]["total"], 2)
        self.assertEqual(self.rep["deleted_accounts"]["by_days_after_signup"]["0-2"], 1)

    def test_nothing_private_in_the_report(self):
        text = json.dumps(self.rep)
        for private in ("777", "CODE", "secret-key", "Surname", "F0"):
            self.assertNotIn(private, text)
        self.assertTrue(any("not «listened»" in x for x in self.rep["limits"]))


class StoreTest(unittest.TestCase):
    def test_plays_snapshot_and_anonymous_deletion(self):
        from mycast_accounts import ListenerStore
        with tempfile.TemporaryDirectory() as d:
            clock = [NOW]
            store = ListenerStore(Path(d) / "l.json", clock=lambda: clock[0])
            rec = store.login({"provider": "telegram", "pid": "1", "name": "A", "chat_id": "1"})
            store.count_play(rec["slug"], "own")
            store.count_play(rec["slug"], "own")
            store.count_play(rec["slug"], "shared")
            store.count_play(rec["slug"], "nonsense")
            store.count_play("nobody12", "own")
            snap = store.snapshot()
            self.assertEqual(snap["listeners"][rec["slug"]]["plays"], {"own": 2, "shared": 1, "last_own_at": NOW})
            clock[0] = NOW + 5 * DAY
            self.assertTrue(store.delete(rec["slug"]))
            stats = store.snapshot()["stats"]
            self.assertEqual(stats["deleted"], {"total": 1, "by_days": {"3-6": 1}})
            self.assertNotIn(rec["slug"], (Path(d) / "l.json").read_text())


class RouteAndPageTest(unittest.TestCase):
    def test_owner_only(self):
        from fastapi import FastAPI, HTTPException
        app = FastAPI()
        role = ["viewer"]
        install_mycast_stats_routes(app, load=lambda: {"listeners": {"a": listener("loyal", episodes=(-1,))}},
                                    identity=lambda r: {"role": role[0]}, clock=lambda: NOW)
        h = {r.path: r.endpoint for r in app.routes if hasattr(r, "methods")}
        with self.assertRaises(HTTPException) as ctx:
            h["/api/factory/mycast/stats"](None)
        self.assertEqual(ctx.exception.status_code, 403)
        role[0] = "owner"
        self.assertEqual(h["/api/factory/mycast/stats"](None)["total"], 1)

    def test_app_wiring_and_play_counting(self):
        app_src = (ROOT / "app.py").read_text(encoding="utf-8")
        self.assertIn("install_mycast_stats_routes(app, load=MYCAST_LISTENERS.snapshot, identity=request_identity)", app_src)
        acc = (ROOT / "mycast_accounts.py").read_text(encoding="utf-8")
        self.assertEqual(acc.count("store.count_play("), 3)       # own replay, profile player, shared episode

    def page(self):
        return (ROOT / "static/mycast-stats/index.html").read_text(encoding="utf-8")

    def test_page_three_languages_no_network(self):
        html = self.page()
        self.assertIsNone(re.search(r"https?://", html))
        self.assertIn('fetch("/api/factory/mycast/stats",{credentials:"same-origin"})', html)
        self.assertEqual(html.count("<script>"), 1)

    @unittest.skipUnless(shutil.which("node"), "node needed")
    def test_page_strings_match(self):
        js = self.page().split("<script>", 1)[1].split("</script>", 1)[0]
        block = js[js.index("const T="):js.index("const SEG=")]
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.js"
            f.write_text(block + "\nprocess.stdout.write(JSON.stringify(T));", encoding="utf-8")
            table = json.loads(subprocess.run(["node", str(f)], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(set(table["ru"]), set(table["en"]))
        self.assertEqual(set(table["uk"]), set(table["en"]))
        for seg in mycast_stats.SEGMENTS:
            self.assertIn("seg_" + seg, table["en"])
        for step in ("registered", "podcast_set_up", "telegram_linked", "first_episode", "three_days", "seven_days",
                     "played_on_site"):
            self.assertIn("f_" + step, table["en"])


if __name__ == "__main__":
    unittest.main()
