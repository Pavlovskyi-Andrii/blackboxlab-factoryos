"""T-626: Worker Center panel for the shared agent workspace (GET /api/factory/agent-workspace).

The fixtures are real ``AgentWorkspace.overview`` answers (empty store, a disabled lane, an active handoff), rendered
by the dashboard's pure ``renderAgentWorkspace`` in node for EN/UK/RU, as test_lane_board.py does.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import agent_workspace as aw
from relay import RelayStore
from relay_execution import RelayQueue

HTML = Path(__file__).resolve().parent / "static" / "index.html"
TOKENS = {"claude": "ui-claude-7Qm2Vx9Lp4Rt8Wz1Ny6Kd3Hs5Jb0Fc", "chatgpt": "ui-chatgpt-3Hd8Ks2Lq9Wx5Vn1Mz7Rt4Pb6Yc0Jf"}
ENV = {aw.TOKEN_ENV[lane]: value for lane, value in TOKENS.items()} | {aw.URL_KEY_ENV: "chatgpt"}
PR = "https://github.com/pavlovskyi-andrii/blackboxlab-factoryos/pull/4242"


def ui_program():
    html = HTML.read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split("// --- agent-workspace:begin", 1)[1].split("\n", 1)[1].split("// --- agent-workspace:end", 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    assigns = "\n".join(l for l in script.splitlines() if l.startswith("Object.assign(I18N.") and '"aw.' in l)
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    stub = "const document={addEventListener(){},querySelectorAll(){return []}};\n"
    return html, block, "let LANG='en';\n" + stub + helpers + "\n" + i18n + "\n" + assigns + "\n" + tr + "\n" + block


class WorkspaceUiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.n = 0

    def tearDown(self):
        self.tmp.cleanup()

    def workspace(self):
        self.n += 1
        store = RelayStore(Path(self.tmp.name) / f"relay{self.n}.json")
        return aw.AgentWorkspace(store, RelayQueue(store), policy=lambda: "policy-1")

    def fixture_empty(self):
        return aw.owner_view(self.workspace(), aw.lane_status({}), {})

    def fixture_disabled_lane(self):
        ws = self.workspace()
        first = ws.post_message("claude", {"topic": "Panel layout", "body": "Proposal: <script>alert(1)</script>",
                                           "kind": "proposal", "idempotency_key": "m-1"})
        ws.post_message("chatgpt", {"thread_id": first["thread_id"], "body": "Agreed", "kind": "answer",
                                    "idempotency_key": "m-2"})
        return aw.owner_view(ws, aw.lane_status(ENV), ENV)

    def fixture_active_handoff(self):
        ws = self.workspace()
        for key, task, path in (("h-1", "T-901", "docs/a.md"), ("h-2", "T-902", "docs/b.md")):
            ws.create_handoff("claude", {"to": "chatgpt", "task_id": task, "objective": "Write " + path,
                                         "done": ["file exists"], "files_scope": [path], "idempotency_key": key})
        ids = {h["task_id"]: h["handoff_id"] for h in ws.overview()["handoffs"]}
        claimed = ws.claim_handoff("chatgpt", {"handoff_id": ids["T-901"], "policy_sha": "policy-1",
                                               "idempotency_key": "c-1"})
        second = ws.claim_handoff("chatgpt", {"handoff_id": ids["T-902"], "policy_sha": "policy-1",
                                              "idempotency_key": "c-2"})
        ws.submit_handoff_result("chatgpt", {"handoff_id": ids["T-902"], "run_id": second["run_id"],
                                             "summary": "Docs written", "artifact_urls": [PR], "idempotency_key": "s-1"})
        view = aw.owner_view(ws, aw.lane_status(ENV), ENV)
        view["_claimed"] = claimed
        return view

    def test_api_view(self):
        empty = self.fixture_empty()
        self.assertEqual((empty["threads"], empty["handoffs"], empty["handoff_states"]), ([], [], {}))
        self.assertFalse(any(l["enabled"] for l in empty["lanes"].values()))
        self.assertIn("FACTORY_MCP_LANE_TOKEN_CLAUDE is not set", empty["lanes"]["claude"]["problem"])

        disabled = self.fixture_disabled_lane()
        self.assertTrue(disabled["lanes"]["claude"]["enabled"] and disabled["lanes"]["chatgpt"]["enabled"])
        self.assertFalse(disabled["lanes"]["gemini"]["enabled"])
        self.assertEqual(disabled["url_key_lanes"], ["chatgpt"])
        msgs = disabled["threads"][0]["recent_messages"]
        self.assertEqual([(m["from"], m["kind"]) for m in msgs], [("claude", "proposal"), ("chatgpt", "answer")])

        active = self.fixture_active_handoff()
        self.assertEqual(active["handoff_states"], {"claimed": 1, "review": 1})
        claimed = next(h for h in active["handoffs"] if h["state"] == "claimed")
        self.assertEqual(claimed["run_id"], active["_claimed"]["run_id"])
        self.assertTrue(claimed["relay_ticket_id"])
        review = next(h for h in active["handoffs"] if h["state"] == "review")
        self.assertEqual(review["artifacts"], [PR])
        for view in (empty, disabled, active):
            dump = json.dumps(view)
            for token in TOKENS.values():
                self.assertNotIn(token, dump)

    def test_static_wiring(self):
        html, block, _ = ui_program()
        self.assertIn("api('/api/factory/agent-workspace')", html)
        self.assertIn("renderAgentWorkspace(awLast)", html)
        self.assertNotIn("innerHTML", block)
        self.assertNotIn("fetch(", block)
        self.assertNotIn("method:", block)  # read-only: no writes from the panel
        self.assertIsNone(re.search(r"token|api_key|password|secret", block, re.I))
        keys = set(re.findall(r"tr\('(aw\.[a-zA-Z_.]*[a-zA-Z_])'", block))
        keys |= {f"aw.state.{s}" for s in ("queued", "claimed", "review", "blocked", "done", "released")}
        keys |= {"aw.enabled", "aw.disabled"}
        for key in keys:
            self.assertEqual(html.count(f'"{key}":'), 3, f"{key} must exist in EN/UK/RU")

    def test_rendering(self):
        node = shutil.which("node")
        if not node:
            if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
                self.fail("node is required for the agent workspace rendering check")
            self.skipTest("node is not installed")
        fixtures = {"empty": self.fixture_empty(), "disabled": self.fixture_disabled_lane(),
                    "active": self.fixture_active_handoff()}
        _, _, code = ui_program()
        program = code + "\nconst fx=" + json.dumps(fixtures) + ",out={};" \
            "for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fx))out[lang+':'+k]=renderAgentWorkspace(fx[k])}" \
            "out.none=renderAgentWorkspace(null);process.stdout.write(JSON.stringify(out));"
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])
        out = json.loads(result.stdout)
        self.assertEqual(out.pop("none"), "")
        words = {"en": ("Connected", "Off", "No threads yet", "In review"),
                 "uk": ("Підключено", "Вимкнено", "Тредів ще немає", "На перевірці"),
                 "ru": ("Подключено", "Выключено", "Тредов пока нет", "На проверке")}
        for key, html in out.items():
            lang, name = key.split(":")
            self.assertIsNone(re.search(r">aw\.[a-z]", html), key)  # no raw i18n keys
            for token in TOKENS.values():
                self.assertNotIn(token, html, key)
            self.assertIn('data-lane="gemini" data-enabled="0"', html, key)
            self.assertIn("FACTORY_MCP_LANE_TOKEN_GEMINI is not set", html, key)
            self.assertIn(words[lang][1], html, key)
        for lang in ("en", "uk", "ru"):
            empty, disabled, active = out[lang + ":empty"], out[lang + ":disabled"], out[lang + ":active"]
            self.assertIn('data-empty="1"', empty)
            self.assertIn(words[lang][2], empty)
            self.assertIn('data-lane="claude" data-enabled="0"', empty)
            self.assertIn('data-lane="claude" data-enabled="1"', disabled)
            self.assertIn(words[lang][0], disabled)
            self.assertIn('data-from="claude" data-kind="proposal"', disabled)
            self.assertIn('data-from="chatgpt" data-kind="answer"', disabled)
            self.assertNotIn("<script>alert", disabled)
            self.assertIn("&lt;script&gt;", disabled)
            self.assertIn('data-group="claimed"', active)
            self.assertIn('data-group="review"', active)
            self.assertIn(words[lang][3], active)
            run_id = fixtures["active"]["_claimed"]["run_id"]
            ticket = fixtures["active"]["_claimed"]["relay_ticket_id"]
            self.assertIn(f'data-run="{run_id}"', active)
            self.assertIn(f'data-relay="{ticket}"', active)
            self.assertIn(f'href="{PR}"', active)
            self.assertIn('data-task="T-901" data-state="claimed"', active)


if __name__ == "__main__":
    unittest.main()
