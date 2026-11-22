"""T-588 Supervisor routing policy regression.

Proves explicit assignment wins over Auto, offline operators are skipped, HUMAN tasks stay blocked, and no
provider gains production/publish privileges by being selected, both in the pure policy and the owner API.
"""
import json
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-routing-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import supervisor_routing as sr  # noqa: E402


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


ALL_ON = {"claude": True, "gemini": True, "chatgpt": True}
TASK = {"id": "T-900", "human": False, "done": False, "owner": ""}

# Auto: bounded preference order, offline skipped.
r = sr.route_task(TASK, availability=ALL_ON)
require((r["state"], r["operator"], r["source"]) == ("routed", "claude", "auto"), f"auto picks claude: {r}")
r = sr.route_task(TASK, availability={"claude": False, "gemini": True})
require((r["state"], r["operator"]) == ("routed", "gemini"), f"offline claude skipped: {r}")
r = sr.route_task(TASK, availability={"claude": False, "gemini": False, "chatgpt": True})
require(r["state"] == "waiting" and r["operator"] is None and r["reason"] == "no_online_operator",
        f"chatgpt is not an engineering Auto candidate: {r}")
require("chatgpt" not in r["considered"] and len(r["considered"]) <= sr.AUTO_MAX_CANDIDATES, "auto is bounded")
# unknown/unverified (None) and stale lanes are not online
avail = sr.operator_availability(
    [{"operator_id": "claude", "availability": "stale"}, {"operator_id": "gemini", "availability": "unconfigured"}],
    [{"id": "gemini", "online": None}, {"id": "claude", "online": False}])
require(avail == {"claude": False, "gemini": False, "chatgpt": False}, f"only positive online counts: {avail}")
require(sr.route_task(TASK, availability=avail)["state"] == "waiting", "nobody online -> waiting")
avail = sr.operator_availability([{"operator_id": "gemini", "availability": "online"}], [{"id": "chatgpt", "online": True}])
require(avail == {"claude": False, "gemini": True, "chatgpt": True}, f"lane/status online: {avail}")
r = sr.route_task({**TASK}, role="scriptwriter", availability={"chatgpt": False, "claude": True})
require(r["operator"] == "claude", f"content auto skips offline chatgpt: {r}")
r = sr.route_task(TASK, availability=ALL_ON, eligible=["gemini"])
require(r["operator"] == "gemini", f"auto limited to eligible operators: {r}")

# Explicit assignment wins over Auto: task Owner first, then the owner's role assignment.
r = sr.route_task({**TASK, "owner": "gemini"}, availability=ALL_ON, role_assignments={"engineer": "claude"})
require((r["operator"], r["source"]) == ("gemini", "task_owner"), f"task owner wins: {r}")
r = sr.route_task(TASK, availability=ALL_ON, role_assignments={"engineer": "gemini"})
require((r["state"], r["operator"], r["source"]) == ("routed", "gemini", "role_assignment"), f"role assignment wins: {r}")
for none in ("any", "auto", ""):
    r = sr.route_task({**TASK, "owner": none}, availability=ALL_ON, role_assignments={"engineer": "auto"})
    require(r["source"] == "auto" and r["operator"] == "claude", f"owner {none!r} is not explicit")
# Explicit + offline: wait for the assigned operator, never silently rerouted to an online one.
r = sr.route_task(TASK, availability={"claude": True, "gemini": False}, role_assignments={"engineer": "gemini"})
require((r["state"], r["operator"], r["reason"]) == ("waiting", "gemini", "assigned_operator_offline"),
        f"explicit offline waits: {r}")
r = sr.route_task({**TASK, "owner": "gpt5"}, availability=ALL_ON)
require(r["state"] == "blocked" and r["operator"] is None and r["reason"] == "unknown_operator", f"unknown owner: {r}")

# HUMAN tasks stay blocked whatever is assigned or online; done tasks are not routed.
for owner in ("", "claude", "gemini"):
    r = sr.route_task({**TASK, "human": True, "owner": owner}, availability=ALL_ON, role_assignments={"engineer": "claude"})
    require((r["state"], r["operator"], r["reason"]) == ("blocked", None, "human_task"), f"HUMAN stays blocked: {r}")
require(sr.route_task({**TASK, "done": True}, availability=ALL_ON)["state"] == "done", "done task")

# No privilege grant by selection: every outcome has the same fully-denied privileges and executes nothing.
outcomes = [sr.route_task({**TASK, "owner": op}, availability=ALL_ON, role=role)
            for op in ("", "claude", "gemini", "chatgpt") for role in sr.AUTO_POLICY]
for r in outcomes:
    require(r["privileges"] == sr.PRIVILEGES and r["executes"] is False, f"privileges must not vary: {r}")
require(all(v is False for k, v in sr.PRIVILEGES.items() if k != "requires_human_publish_approval")
        and sr.PRIVILEGES["requires_human_publish_approval"] is True, "privileges fully denied")
outcomes[0]["privileges"]["publish"] = True
require(sr.PRIVILEGES["publish"] is False, "route privileges are a copy")

# Owner API: real roadmap + real T-580 assignments.
import app  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

req = Request({"type": "http", "headers": [], "method": "GET", "path": "/"})
app.request_identity = lambda _r: {"role": "owner"}
FIXTURE = """## v
- [ ] T-901 Auto task
- [ ] T-902 Gemini task
  Owner: gemini
- [ ] [HUMAN] T-903 Human task
  Owner: claude
- [x] T-904 Done task
"""
_parse = app._parse_roadmap_tasks
app._parse_roadmap_tasks = lambda text=None: _parse(FIXTURE if text is None else text)
lanes = [{"operator_id": "claude", "availability": "online"}, {"operator_id": "gemini", "availability": "offline"}]
out = app.get_supervisor_routing(lanes)
routes = {x["task_id"]: x for x in out["routes"]}
require(set(routes) == {"T-901", "T-902", "T-903"}, f"open tasks only: {routes}")
require((routes["T-901"]["state"], routes["T-901"]["operator"]) == ("routed", "claude"), "API auto")
require((routes["T-902"]["state"], routes["T-902"]["operator"]) == ("waiting", "gemini"), "API explicit offline waits")
require(routes["T-903"]["state"] == "blocked", "API HUMAN blocked")
app.factory_role_assignment(app.RoleAssignmentRequest(role="engineer", operator="gemini"), req)
lanes[1]["availability"] = "online"
routes = {x["task_id"]: x for x in app.get_supervisor_routing(lanes)["routes"]}
require((routes["T-901"]["operator"], routes["T-901"]["source"]) == ("gemini", "role_assignment"), "API role assignment")
require(app.get_role_operator_board()["assignments"] == {"engineer": "gemini"}, "routing does not mutate assignments")
app.FACTORY_GEMINI_API_KEY = "gem-secret-value"
app.claude_worker_runtime.update({"last_seen": 0})
blob = json.dumps(app.factory_routing(req))
require("gem-secret-value" not in blob, "no secrets in routing API")
require(all(x["privileges"] == sr.PRIVILEGES for x in json.loads(blob)["routes"]), "API privileges denied")
app.request_identity = lambda _r: {"role": "viewer"}
try:
    app.factory_routing(req)
    raise AssertionError("viewer must be refused")
except HTTPException as exc:
    require(exc.status_code == 403, "owner-only")

# Table-driven test for route_task inputs and expected outcomes
table_tests = [
    ("done_task", {"id": "T-101", "done": True}, "engineer", {}, ALL_ON, None, "done", None, "roadmap", "task_done"),
    ("human_task", {"id": "T-102", "human": True, "owner": "claude"}, "engineer", {}, ALL_ON, None, "blocked", None, "roadmap", "human_task"),
    ("unknown_owner", {"id": "T-103", "owner": "invalid_op"}, "engineer", {}, ALL_ON, None, "blocked", None, "task_owner", "unknown_operator"),
    ("explicit_owner_online", {"id": "T-104", "owner": "gemini"}, "engineer", {}, ALL_ON, None, "routed", "gemini", "task_owner", "explicit_assignment"),
    ("explicit_owner_offline", {"id": "T-105", "owner": "gemini"}, "engineer", {}, {"gemini": False}, None, "waiting", "gemini", "task_owner", "assigned_operator_offline"),
    ("role_assignment_online", {"id": "T-106"}, "engineer", {"engineer": "gemini"}, ALL_ON, None, "routed", "gemini", "role_assignment", "explicit_assignment"),
    ("auto_routing_first_candidate", {"id": "T-107"}, "engineer", {}, ALL_ON, None, "routed", "claude", "auto", "auto_policy"),
    ("auto_routing_fallback", {"id": "T-108"}, "engineer", {}, {"claude": False, "gemini": True}, None, "routed", "gemini", "auto", "auto_policy"),
    ("auto_routing_all_offline", {"id": "T-109"}, "engineer", {}, {"claude": False, "gemini": False}, None, "waiting", None, "auto", "no_online_operator"),
    ("unknown_role_safe_default", {"id": "T-110"}, "nonexistent_role", {}, ALL_ON, None, "waiting", None, "auto", "no_eligible_operator"),
    ("empty_task_input", {}, "engineer", {}, ALL_ON, None, "routed", "claude", "auto", "auto_policy"),
]

for name, t_task, t_role, t_assign, t_avail, t_elig, exp_state, exp_op, exp_source, exp_reason in table_tests:
    res = sr.route_task(t_task, role=t_role, role_assignments=t_assign, availability=t_avail, eligible=t_elig)
    require((res["state"], res["operator"], res["source"], res["reason"]) == (exp_state, exp_op, exp_source, exp_reason),
            f"table test failed for {name}: {res}")

print("T-588 supervisor routing regression passed")
