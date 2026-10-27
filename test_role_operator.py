"""T-580 Role / Operator separation regression.

Proves roles are exposed separately from operators, canonical workers are unchanged, operator
status never leaks secrets or fabricates readiness, assignment is owner-only and validated, and
the existing agent API stays backward-compatible.
"""
import json
import os
import sys
import tempfile

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-roles-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

import app  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from starlette.requests import Request  # noqa: E402

OWNER = {"role": "owner"}
VIEWER = {"role": "viewer"}


def require(cond, msg):
    if not cond:
        raise AssertionError(msg)


def request():
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


def as_identity(identity):
    app.request_identity = lambda _r: identity


def refused(fn, code):
    try:
        fn()
    except HTTPException as exc:
        require(exc.status_code == code, f"expected {code}, got {exc.status_code}")
        return
    raise AssertionError(f"expected HTTP {code}")


agents_before = [a["name"] for a in app.list_agents()["agents"]]
as_identity(OWNER)
board = app.factory_roles(request())
roles = {r["id"]: r for r in board["roles"]}
ops = {o["id"]: o for o in board["operators"]}

require(set(ops) == {"chatgpt", "claude", "gemini", "auto"}, "operators")
for rid in ("scout", "researcher", "scriptwriter", "reviewer", "qa", "engineer", "supervisor"):
    require(rid in roles, f"missing role {rid}")
for r in board["roles"]:
    require(all(w in app.AGENTS for w in r["workers"]), f"{r['id']} references non-canonical worker")
    require(r["assigned_operator"] == "auto" and not r["explicit"], "default must be auto")
    require(r["enforced"] is False, "assignment must not claim enforcement")
require(roles["scout"]["runtime_operator"] == "chatgpt", "live LLM worker runtime")
require(roles["engineer"]["runtime_operator"] == "", "engineer has no pipeline runtime")

# offline / unconfigured is explicit, never fabricated as ready
require(ops["chatgpt"]["status"] == "auth_pending" and ops["chatgpt"]["online"] is False, "chatgpt unconfigured")
require(ops["gemini"]["status"] == "auth_pending" and ops["gemini"]["online"] is False, "gemini unconfigured")
require(ops["claude"]["status"] == "offline" and ops["claude"]["auth"] == "pending", "claude offline")

# configured keys are reported as booleans/status only, never as values
app.FACTORY_LLM_API_KEY = "sk-secret-llm"
app.FACTORY_GEMINI_API_KEY = "gem-secret"
app.claude_worker_runtime.update({"last_seen": app.time.time(), "node": {"auth_mode": "subscription"}})
ops = {o["id"]: o for o in app.factory_roles(request())["operators"]}
require(ops["chatgpt"]["status"] == "configured" and ops["chatgpt"]["online"] is True, "chatgpt configured")
require(ops["gemini"]["status"] == "configured_unverified" and ops["gemini"]["online"] is None, "gemini unverified")
require(ops["claude"]["status"] == "online" and ops["claude"]["auth"] == "ready", "claude online")
blob = json.dumps(app.factory_roles(request()))
require("sk-secret-llm" not in blob and "gem-secret" not in blob, "secret leaked")

# assignment: validated, persisted, owner-only
def assign(role, operator):
    return app.factory_role_assignment(app.RoleAssignmentRequest(role=role, operator=operator), request())

out = assign("scriptwriter", "claude")
r = {x["id"]: x for x in out["roles"]}
require(r["scriptwriter"]["assigned_operator"] == "claude" and r["scriptwriter"]["explicit"], "assigned")
require(r["scriptwriter"]["runtime_operator"] == "chatgpt", "runtime unchanged by assignment")
require(assign("scriptwriter", "auto")["assignments"] == {}, "auto clears assignment")
assign("engineer", "gemini")
require(app.factory_roles(request())["assignments"] == {"engineer": "gemini"}, "persisted")
refused(lambda: assign("engineer", "chatgpt"), 409)
refused(lambda: assign("engineer", "gpt"), 422)
refused(lambda: assign("nope", "claude"), 404)
as_identity(VIEWER)
refused(lambda: assign("scout", "claude"), 403)
refused(lambda: app.factory_roles(request()), 403)
as_identity(OWNER)

# backward compatibility: canonical worker list and agent API unchanged
require([a["name"] for a in app.list_agents()["agents"]] == agents_before, "agent list changed")
require(all(a in app.AGENTS for a in ("Scout", "QA Agent", "Supervisor")), "canonical names")
print("T-580 role/operator regression passed")
