"""T-723 Surfer recipes: owner-approved saving, parameters, replay under the same gate, stop at the first mismatch."""
import asyncio
import json
import os
import tempfile
import unittest
from unittest import mock

TMP = tempfile.mkdtemp(prefix="factoryos-surfer-recipes-")
os.environ["DATA_DIR"] = TMP
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")
os.environ.pop("FACTORY_SURFER_ACTIONS_ENABLED", None)

from fastapi import HTTPException  # noqa: E402

import surfer_actions as sa  # noqa: E402
import surfer_fixture_site as fixture  # noqa: E402
import surfer_policy as sp  # noqa: E402
import surfer_recipes as sr  # noqa: E402
from test_surfer_owner import OwnerHarness  # noqa: E402
from test_surfer_policy import LOGIN  # noqa: E402


class RecipeHarness(OwnerHarness):
    def setUp(self):
        super().setUp()
        self.recipes = sr.RecipeStore(self.dir, clock=self.clock)

    def record_wizard(self, name="Andrii"):
        view = self.open("/wizard")
        self.act(view, "fill", "Full name", value=name)
        self.act(view, "select", "Plan", value="Pro")
        view2 = self.act(view, "click", "Next")
        self.act(view2, "check", "I agree", value=True)
        self.act(view2, "fill", "Comment", value="first run")
        self.act(view2, "click", "Save")
        return view["session_id"]

    def close(self, session_id):
        sa.web_close(self.store, self.gate, {"session_id": session_id}, "claude")
        self.runner.pump()

    def replay(self, recipe, params=None, lane="claude"):
        run = self.recipes.start_run(recipe, lane, lane)
        return asyncio.run(sr.replay(self.store, self.gate, self.recipes, run, recipe,
                                     sr.check_params(recipe, params or {}), sleep=self._tick, clock=self.clock))


class SaveTest(RecipeHarness):
    def test_recipe_keeps_actions_labels_and_parameters_not_page_content(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "  Wizard  form ", {"2": "full_name", "6": "comment"})
        self.assertRegex(recipe["id"], sr.RECIPE_ID_RE)
        self.assertEqual((recipe["name"], recipe["site"], recipe["lane"], recipe["params"]),
                         ("Wizard form", "shop.example", "claude", ["comment", "full_name"]))
        self.assertEqual([(s["kind"], s.get("action"), (s.get("target") or {}).get("name"), s.get("param"),
                           s.get("value")) for s in recipe["steps"]],
                         [("open", None, None, None, None), ("act", "fill", "Full name", "full_name", None),
                          ("act", "select", "Plan", None, "Pro"), ("act", "click", "Next", None, None),
                          ("act", "check", "I agree", None, "true"), ("act", "fill", "Comment", "comment", None),
                          ("act", "click", "Save", None, None)])
        self.assertEqual(recipe["steps"][1]["example"], "Andrii")
        self.assertEqual(sr.public_recipe(recipe), {"id": recipe["id"], "name": "Wizard form", "site": "shop.example",
                                                    "params": ["comment", "full_name"], "steps": 7})

    def test_saving_is_validated(self):
        sid = self.record_wizard()
        doc = self.store.get(sid)
        for name in ("", "x", "a" * 61, "<script>"):
            with self.assertRaises(HTTPException, msg=name):
                self.recipes.save(doc, name)
        for params in ({"2": "Full Name"}, {"4": "next"}, {"99": "x"}, {"1": "url"}):
            with self.assertRaises(HTTPException, msg=params):
                self.recipes.save(doc, "Wizard", params)
        self.recipes.save(doc, "Wizard")
        with self.assertRaises(HTTPException) as err:
            self.recipes.save(doc, "wizard")
        self.assertEqual(err.exception.status_code, 409)
        empty = {"session": {"id": "ws_" + "0" * 16, "lane": "claude"}, "steps": []}
        with self.assertRaises(HTTPException):
            self.recipes.save(empty, "Empty")

    def test_login_recipe_keeps_vault_references_and_marks_where_the_owner_acted(self):
        self.site.sms_step = True
        view = self.open("/login")
        self.act(view, "fill", "Email", value_from=f"vault:{LOGIN}#username")
        self.act(view, "fill", "Password", value_from=f"vault:{LOGIN}#password")
        self.act(view, "click", "Sign in")
        self.owner(view["session_id"], "human_input", text=fixture.SMS_CODE, submit=True)
        after = self.run_tool(sa.web_snapshot, {"session_id": view["session_id"], "refresh": True})
        self.act(after, "fill", "Note", value="hello")
        recipe = self.recipes.save(self.store.get(view["session_id"]), "Login and note")
        kinds = [(s["kind"], s.get("action"), s.get("value_from")) for s in recipe["steps"]]
        self.assertEqual(kinds, [("open", None, None), ("act", "fill", f"vault:{LOGIN}#username"),
                                 ("act", "fill", f"vault:{LOGIN}#password"), ("act", "click", None),
                                 ("handoff", None, None), ("act", "fill", None)])
        text = json.dumps(recipe) + self.recipes.path.read_text(encoding="utf-8")
        for secret in (fixture.PASSWORD, fixture.SMS_CODE):
            self.assertNotIn(secret, text)
        with self.assertRaises(HTTPException):                       # a vault step cannot become a parameter
            self.recipes.save(self.store.get(view["session_id"]), "Bad", {"3": "password"})
        self.close(view["session_id"])
        self.site.signed_in = False
        run = self.replay(recipe)                                     # the site asks for the code: it stops there
        self.assertEqual((run["status"], run["reason"], run["at_step"]), ("stopped", "2fa", 4))
        self.assertEqual(self.status({"session_id": run["session_id"]}), "waiting_human")


class ReplayTest(RecipeHarness):
    def test_replay_runs_without_ai_with_new_parameters(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard", {"2": "full_name"})
        self.close(sid)
        before = dict(self.gate.usage())
        run = self.replay(recipe, {"full_name": "Olena"})
        self.assertEqual((run["status"], run["reason"], run["at_step"], run["steps_total"]), ("done", "", 7, 7))
        self.assertEqual(self.site.events[-1], {"event": "wizard", "name": "Olena", "plan": "pro", "agree": "yes",
                                                "comment": "first run"})
        self.assertEqual(self.gate.usage()["sessions"], before["sessions"] + 1)        # the same caps count
        self.assertEqual(self.gate.usage()["steps"], before["steps"] + 6)
        rows = [r for r in self.store.audit_tail(30) if r.get("session") == run["session_id"]]
        self.assertEqual(rows[0]["action"], "recipe_done")
        self.assertIn(("fill", "Olena"), [(r["action"], r.get("value")) for r in rows])   # every step is in the log
        self.assertEqual(self.status({"session_id": run["session_id"]}), "active")       # left open for the caller

    def test_replay_stops_at_the_first_mismatch_and_leaves_the_session_to_the_agent(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard")
        self.close(sid)
        original = self.site.dom

        def changed(path):
            dom = original(path)
            if path == "/wizard/2":
                dom["elements"][1]["name"] = "Your comment"            # the site renamed a field
            return dom
        with mock.patch.object(self.site, "dom", changed):
            run = self.replay(recipe)
            self.assertEqual((run["status"], run["reason"], run["at_step"]), ("stopped", "element_not_found", 6))
            self.assertEqual(self.site.events[-1]["comment"], "first run")           # nothing new was submitted
            view = self.run_tool(sa.web_snapshot, {"session_id": run["session_id"]})
            self.assertEqual((view["status"], view["title"]), ("done", "Form step 2"))
            self.act(view, "fill", "Your comment", value="by the agent")             # the agent takes it from here
            done = self.act(view, "click", "Save")
        self.assertEqual((done["status"], done["title"], len(self.site.events)), ("done", "Done", 2))

    def test_replay_stops_when_the_page_is_not_the_recorded_one(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard")
        self.close(sid)
        recipe["steps"][4]["page"] = "https://shop.example/another"
        run = self.replay(recipe)
        self.assertEqual((run["status"], run["reason"], run["at_step"]), ("stopped", "page_differs", 5))
        target = recipe["steps"][1]["target"]
        twin = {"kind": "input", "type": "text", "name": "Full name", "form": {"action": "https://shop.example/wizard"}}
        self.assertEqual(sr.match_element({"elements": [dict(twin, ref="e1")]}, target), ("e1", ""))
        self.assertEqual(sr.match_element({"elements": [dict(twin, ref="e1"), dict(twin, ref="e2")]}, target),
                         ("", "element_ambiguous"))
        self.assertEqual(sr.match_element({"elements": [dict(twin, ref="e1", name="Full  name!")]}, target),
                         ("", "element_not_found"))

    def test_same_path_with_another_record_in_the_query_is_another_page(self):
        # Codex review on #451: /edit?id=123 recorded, the site lands on /edit?id=456 with the same labels.
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard")
        self.close(sid)
        self.assertEqual(recipe["steps"][1]["page_query"], "")
        original = self.store.snapshot

        def other_record(session_id):
            snap = original(session_id)
            if snap.get("url", "").endswith("/wizard"):
                snap["url"] += "?id=456"
            return snap
        with mock.patch.object(self.store, "snapshot", other_record):
            run = self.replay(recipe)
        self.assertEqual((run["status"], run["reason"], run["at_step"]), ("stopped", "page_differs", 2))
        self.assertEqual(len(self.site.events), 1)
        self.assertNotEqual(sr._query_mark("https://a.b/edit?id=123"), sr._query_mark("https://a.b/edit?id=456"))
        self.assertEqual(sr._query_mark("https://a.b/e?x=1&y=2"), sr._query_mark("https://a.b/e?y=2&x=1"))
        self.assertNotIn("123", sr._query_mark("https://a.b/edit?id=123"))

    def test_a_replay_cut_by_a_restart_is_interrupted_and_never_resumed(self):
        # Codex review on #451: a run must not stay "running" forever after the web service restarts.
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard")
        self.close(sid)
        run = self.recipes.start_run(recipe, "claude", "claude")
        self.recipes.update_run(run["id"], at_step=4, session_id="ws_" + "1" * 16)
        self.assertEqual(self.recipes.run(run["id"])["status"], "running")
        restarted = sr.RecipeStore(self.dir, clock=self.clock)          # a new web process
        events, launches = len(self.site.events), self.pw.launches
        state = asyncio.run(sr.call_tool({"run_id": run["id"]}, store=self.store, gate=self.gate, recipes=restarted,
                                         lane="claude"))
        self.assertEqual((state["status"], state["at_step"]), ("interrupted", 4))
        self.assertIn("restarted", state["reason"])
        self.assertIn("1–3", state["reason"])
        for _ in range(5):
            self.runner.pump()
        self.assertEqual((len(self.site.events), self.pw.launches), (events, launches))    # nothing was replayed
        self.assertEqual(restarted.runs()[0]["status"], "interrupted")

    def test_a_sensitive_step_waits_for_the_owner_again_on_every_replay(self):
        self.site.signed_in = True
        view = self.open("/account")
        waiting = self.act(view, "click", "Delete account")
        self.store.decide(waiting["step_id"], confirm=True)            # the owner confirmed it once, in that session
        self.runner.pump()
        self.assertEqual(self.site.events, [{"event": "account_delete"}])
        recipe = self.recipes.save(self.store.get(view["session_id"]), "Delete my account")
        self.close(view["session_id"])
        run = self.replay(recipe)
        self.assertEqual((run["status"], run["reason"]), ("stopped", "needs_owner_confirmation"))
        self.assertEqual(len(self.site.events), 1)                     # not deleted a second time
        self.assertEqual(self.status({"session_id": run["session_id"]}), "needs_owner_confirmation")

    def test_replay_obeys_the_gate(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard")
        self.close(sid)
        self.gate.save_entry({**self.entry, "classes": ["read", "navigate"]})     # the owner took "fill" away
        run = self.replay(recipe)
        self.assertEqual((run["status"], run["reason"], run["at_step"]), ("stopped", "needs_owner_confirmation", 2))
        self.close(run["session_id"])
        self.gate.save_entry({**self.entry, "enabled": False})                    # and then the whole site
        run = self.replay(recipe)
        self.assertEqual((run["status"], run["at_step"]), ("stopped", 1))
        self.assertIn("allowlist", run["reason"])
        self.env[sp.FLAG_ENV] = "0"
        run = self.replay(recipe)
        self.assertIn(sp.FLAG_ENV, run["reason"])
        self.assertEqual(len(self.site.events), 1)


class ToolAndRoutesTest(RecipeHarness):
    def tool(self, args, lane="claude"):
        return sr.call_tool(args, store=self.store, gate=self.gate, recipes=self.recipes, lane=lane)

    def test_agent_tool_lists_starts_and_reports_but_cannot_save(self):
        sid = self.record_wizard()
        recipe = self.recipes.save(self.store.get(sid), "Wizard", {"2": "full_name"})

        async def scenario():
            with self.assertRaises(HTTPException) as err:
                await self.tool({}, lane="")
            self.assertEqual(err.exception.status_code, 403)
            listed = await self.tool({})
            self.assertEqual(listed, {"recipes": [sr.public_recipe(recipe)]})
            with self.assertRaises(HTTPException) as err:             # the recording session is still open
                await self.tool({"recipe": "Wizard", "params": {"full_name": "Olena"}})
            self.assertEqual(err.exception.status_code, 409)
            sa.web_close(self.store, self.gate, {"session_id": sid}, "claude")
            self.runner.pump()
            for bad in ({"recipe": "Nope"}, {"recipe": "Wizard"}, {"recipe": "Wizard", "params": {"x": "1"}},
                        {"recipe": "Wizard", "params": {"full_name": "a", "extra": "b"}}):
                with self.assertRaises(HTTPException, msg=bad):
                    await self.tool(bad)
            run = await self.tool({"recipe": "wizard", "params": {"full_name": "Olena"}})
            self.assertEqual((run["status"], run["by"]), ("running", "claude"))
            with self.assertRaises(HTTPException) as err:             # another lane cannot read this run
                await self.tool({"run_id": run["id"]}, lane="chatgpt")
            self.assertEqual(err.exception.status_code, 404)
            for _ in range(400):
                self.runner.pump()
                await asyncio.sleep(0.005)
                state = await self.tool({"run_id": run["id"]})
                if state["status"] != "running":
                    break
            return state
        with mock.patch.object(sa, "POLL_SECONDS", 0.005):
            state = asyncio.run(scenario())
        self.assertEqual((state["status"], state["at_step"]), ("done", 7))
        self.assertEqual(self.site.events[-1]["name"], "Olena")
        self.assertNotIn("save", sr.TOOL["description"].lower().split("replayed")[1])

    def test_owner_routes(self):
        from fastapi import FastAPI
        from starlette.requests import Request
        role = {"value": "owner"}
        app = FastAPI()
        sr.install_routes(app, store=self.store, gate=self.gate, recipes=self.recipes,
                          identity=lambda r: {"role": role["value"]})

        def call(method, path, params=None, body=None):
            route = next(r for r in app.routes if getattr(r, "path", "") == path and method in r.methods)
            raw = json.dumps(body or {}).encode()

            async def receive():
                return {"type": "http.request", "body": raw, "more_body": False}
            request = Request({"type": "http", "method": method, "path": path, "query_string": b"", "headers": []},
                              receive)

            async def run():
                result = route.endpoint(**(params or {}), request=request)
                return await result if asyncio.iscoroutine(result) else result
            return asyncio.run(run())
        base = "/api/factory/surfer/owner/recipes"
        sid = self.record_wizard()
        role["value"] = "viewer"
        for method, path, params in (("GET", base, None), ("POST", base, None),
                                     ("POST", base + "/{recipe_id}/delete", {"recipe_id": "rc_000000000000"}),
                                     ("POST", base + "/{recipe_id}/run", {"recipe_id": "rc_000000000000"})):
            with self.assertRaises(HTTPException) as err:
                call(method, path, params)
            self.assertEqual(err.exception.status_code, 403)
        role["value"] = "owner"
        made = call("POST", base, None, {"session_id": sid, "name": "Wizard", "params": {"2": "full_name"}})["recipe"]
        self.assertEqual(made["steps"][1], {"kind": "act", "action": "fill", "param": "full_name", "example": "Andrii",
                                            "seq": 2, "element": "Full name"})
        self.assertEqual(self.store.audit_tail(1)[0]["action"], "recipe_save")
        cleared = {"session": {"id": sid}, "steps": [
            {"id": "wa_" + "0" * 16, "seq": 1, "kind": "act", "action": "fill", "status": "done", "by": "claude",
             "element": {"name": "Note", "kind": "input"}}]}
        self.assertEqual(sa.owner_session_view(self.store, cleared)["steps"][0]["value"], "")   # can be a parameter
        with self.assertRaises(HTTPException) as err:
            call("POST", base, None, {"session_id": "ws_" + "0" * 16, "name": "Other"})
        self.assertEqual(err.exception.status_code, 404)
        self.close(sid)
        with self.assertRaises(HTTPException):
            call("POST", base + "/{recipe_id}/run", {"recipe_id": made["id"]}, {"params": {}})
        with mock.patch.object(sa, "POLL_SECONDS", 0.005):
            started = call("POST", base + "/{recipe_id}/run", {"recipe_id": made["id"]},
                           {"params": {"full_name": "Petro"}})["run"]
        self.assertEqual((started["by"], started["lane"], started["status"]), ("owner", "claude", "running"))
        listing = call("GET", base)
        self.assertEqual((len(listing["recipes"]), listing["runs"][0]["id"]), (1, started["id"]))
        call("POST", base + "/{recipe_id}/delete", {"recipe_id": made["id"]})
        self.assertEqual(call("GET", base)["recipes"], [])

    def test_real_app_lists_the_tool_and_keeps_it_off(self):
        from test_agent_workspace import LANE_TOKENS, SHARED, mcp_call
        import app as factory
        _, listed = mcp_call(factory, {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, SHARED)
        self.assertIn("web_recipe", {t["name"] for t in listed["result"]["tools"]})
        for token, needle in ((SHARED, "shared MCP token may not act"), (LANE_TOKENS["claude"], sp.FLAG_ENV)):
            _, out = mcp_call(factory, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "web_recipe", "arguments": {}}}, token)
            self.assertTrue(out["result"].get("isError"))
            self.assertIn(needle, out["result"]["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
