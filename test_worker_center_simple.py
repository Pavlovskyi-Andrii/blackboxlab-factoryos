"""Owner 2026-11-17: the Worker Center opens with one summary of what the owner must do, who works now, and the
Telegram ↔ site comparison card for T-592-H; everything technical is collapsed. Renders the real inline renderers in Node."""
import json
import os
import re
import shutil
import subprocess
import unittest

from test_worker_observability import ui_program

RUNBOOK = {"why": "why", "time": "1 min", "done": "done when", "steps": [{"id": "s", "title": "Step", "do": ["do it"], "check": "ok", "if": []}]}
DESK = {"lang": "ru", "questions": [], "runbooks": [
    {**RUNBOOK, "id": "T-520", "title": "Подключить публикацию", "status": {"state": "todo", "detail": ""}},
    {**RUNBOOK, "id": "T-591-H", "title": "Приёмка Telegram", "status": {"state": "done", "detail": "Подтверждено сервером: R-0087 · run-1"}},
    {**RUNBOOK, "id": "T-592-H", "title": "Сверить Telegram и сайт", "status": {"state": "todo", "detail": "Сервер сравнил"}},
    {**RUNBOOK, "id": "T-521", "title": "Первый пост", "status": {"state": "blocked", "detail": "Ждёт T-520"}},
    {**RUNBOOK, "id": "T-645-H", "title": "Демо-эпизоды", "status": {"state": "unknown", "detail": ""}},
    {**RUNBOOK, "id": "T-645-H", "title": "Демо-эпизоды (дубль)", "status": {"state": "todo", "detail": ""}},
    {**RUNBOOK, "id": "T-551", "title": "OAuth", "status": {"state": "optional", "detail": ""}},
]}
OVERVIEW = {"human_blockers": [{"id": "T-645-H", "title": "Generate demo episodes", "answered": False},
                               {"id": "T-999-H", "title": "Roadmap-only task", "need": "do the thing", "answered": False}]}
COMPARE = {"verdict": "match", "ticket_id": "R-0087", "ticket_title": "T-591 приёмка",
           "telegram": {"stage": "done", "run_id": "run-1", "last_contact": "2026-11-17 10:00:00", "at": "2026-11-17T10:05:00+00:00"},
           "rows": [{"field": "stage", "telegram": "done", "site": "done", "match": True},
                    {"field": "run_id", "telegram": "run-1", "site": "run-1", "match": True},
                    {"field": "last_contact", "telegram": "2026-11-17 10:00:00", "site": "2026-11-17 10:00:00", "match": True}],
           "problems": [], "confirmation": None}
LANES = {"lanes": {"claude": {"state": "working", "task_id": "T-700", "stage": "running", "last_event": {"action": "running", "at": "2026-11-17T10:00:00+00:00"}},
                   "gemini": {"state": "idle"}}}


def program():
    html, _, code = ui_program()
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    start = script.index("let odLast=null")
    block = script[start:script.index("// --- worker-center-simple:end")]
    od_i18n = "\n".join(l for l in script.splitlines() if l.startswith("Object.assign(I18N.") and '"od.' in l)
    return html, script, code + "\n" + od_i18n + "\n" + block


class TestWorkerCenterSimple(unittest.TestCase):
    def test_static_wiring(self):
        html, script, _ = program()
        dc = re.search(r"^function dcRender\(\)\{.*?\}$", script, re.M | re.S).group(0)
        # Summary first, then who works now, then everything technical inside one collapsed <details>.
        order = [dc.index(x) for x in ("renderOwnerDesk(", "renderWorkingNow(", "wcTech", "renderWorkerOverview(", "renderDelegationCenter(")]
        self.assertEqual(order, sorted(order))
        self.assertIn("/api/factory/telegram-web-compare", script)
        for key in ("wc.need", "wc.tech", "wc.now", "wc.cmp.yes", "wc.cmp.no", "wc.cmp.v.match", "wo.okAll"):
            self.assertEqual(html.count(f'"{key}":'), 3, key)

    def test_rendering(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required")
            self.skipTest("node is not installed")
        _, _, code = program()
        mismatch = {**COMPARE, "verdict": "outdated", "rows": [{**COMPARE["rows"][0], "telegram": "running", "match": False}]}
        prog = code + "\nconst D=" + json.dumps(DESK) + ",O=" + json.dumps(OVERVIEW) + ",C=" + json.dumps(COMPARE) \
            + ",M=" + json.dumps(mismatch) + ",L=" + json.dumps(LANES) + ",out={};" \
            "for(const lang of ['en','uk','ru']){LANG=lang;out[lang]=renderOwnerDesk(D,O,C);out[lang+':now']=renderWorkingNow(L);out[lang+':cmp']=wcCompareCard(M);out[lang+':none']=wcCompareCard({verdict:'no_view',ticket_id:'R-0001',rows:[]})}" \
            "process.stdout.write(JSON.stringify(out));"
        r = subprocess.run([node, "-"], input=prog, capture_output=True, text=True, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])
        out = json.loads(r.stdout)
        ru = out["ru"]
        # Three things wait for the owner (T-520, T-592-H, T-645-H); T-521 is listed but "later"; T-999-H comes from ROADMAP.
        self.assertIn("Нужно от вас: 4", ru)  # T-520, T-592-H, T-645-H, T-999-H
        self.assertEqual(ru.count('data-task="T-645-H"'), 2)  # <details> + its body: listed once, duplicate dropped
        self.assertIn('data-task="T-999-H"', ru)
        self.assertNotIn("Неизвестно", ru)
        self.assertNotIn("Generate demo episodes", ru)  # the runbook (interface language) wins over the ROADMAP title
        main, _, rest = ru.partition('class="wcGroup')
        self.assertNotIn('data-task="T-591-H"', main)  # done tasks are folded away
        self.assertIn("Сделано (1)", ru)
        self.assertIn("Необязательно (1)", ru)
        self.assertNotIn(" open", re.findall(r"<details class=\"wcGroup[^>]*>", ru)[0])
        self.assertLess(main.index('data-task="T-520"'), main.index('data-task="T-521"'))  # waiting-for-you before later
        self.assertLess(main.index('data-task="T-592-H"'), main.index('data-task="T-520"'))  # the live comparison card first
        self.assertIn('class="wcCompare" data-verdict="match" data-ticket="R-0087"', main)
        self.assertIn("Telegram и сайт совпадают ✓", main)
        self.assertIn('data-compare="match"', main)
        self.assertIn("Как сделать", main)
        self.assertIn("Telegram and the site match ✓", out["en"])
        self.assertIn("Потрібно від вас: 4", out["uk"])
        self.assertIn('data-verdict="outdated"', out["ru:cmp"])
        self.assertIn('data-match="0"', out["ru:cmp"])
        self.assertIn("disabled", out["ru:none"].split('data-compare="match"')[1].split(">")[0])
        now = out["ru:now"]
        self.assertEqual(now.count('class="wcLane"'), 3)
        self.assertIn('data-lane="claude" data-state="working"', now)
        self.assertIn("T-700", now)
        self.assertIn('data-lane="chatgpt" data-state="offline"', now)
        for key, html in out.items():
            self.assertIsNone(re.search(r">(wc|wo|od|lb|dc)\.[a-z]", html), key)  # no raw i18n keys


if __name__ == "__main__":
    unittest.main()
