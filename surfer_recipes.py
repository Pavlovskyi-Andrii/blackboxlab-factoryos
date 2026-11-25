"""T-723 Surfer recipes: a successful session saved as a parameterised recipe and replayed without AI.

- Saving is the owner's decision (owner route); an agent cannot save a recipe.
- A recipe keeps what the agent did, not what the page said: the address, the action, the element's label / kind /
  type, and the value. A vault reference stays a reference; a value typed into a secret field cannot exist in a step.
  Where the owner acted himself (a code, a takeover) the recipe has a ``handoff`` step.
- A replay calls the same ``web_open`` / ``web_act`` as an agent, so the same gate, allowlist, step review, caps and
  audit log apply. It finds each element again by its label in the fresh snapshot (exactly one match), checks that it
  is on the page it was recorded on, and stops at the first step that is not ``done``: a mismatch, a step that needs
  the owner, a login or captcha. The session stays open, so the agent or the owner continues from there.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException, Request

from browser_runner import action_policy as policy
import surfer_actions as sa

RECIPE_ID_RE = re.compile(r"^rc_[0-9a-f]{12}$")
RUN_ID_RE = re.compile(r"^rr_[0-9a-f]{12}$")
NAME_RE = re.compile(r"^[\w .,()№#+-]{2,60}$", re.UNICODE)
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
MAX_RECIPES = 50
MAX_RECIPE_STEPS = 80
KEEP_RUNS = 30
STEP_WAIT_SECONDS = 50

TOOL = {
    "name": "web_recipe",
    "description": "Saved Surfer recipes: a sequence of steps the owner approved after a successful session, replayed "
                   "without AI under the same allowlist and confirmation rules. {} lists the recipes (name, site, "
                   "params). {\"recipe\": \"name or rc_… id\", \"params\": {…}} starts a replay and returns run_id and "
                   "session_id at once. {\"run_id\": \"rr_…\"} returns its state: running, done, interrupted (the service "
                   "restarted: look at the page before starting it again), or stopped with the "
                   "step and the reason (a mismatch, a step that needs the owner, a login). After 'stopped' the "
                   "session is still open: continue it with web_snapshot / web_act, or close it with web_close.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "recipe": {"type": "string", "description": "Recipe name or id."},
            "params": {"type": "object", "description": "Values for the recipe's parameters.",
                       "additionalProperties": {"type": "string"}},
            "run_id": {"type": "string"},
        },
        "additionalProperties": False,
    },
}
TOOL_NAMES = frozenset({TOOL["name"]})


def _target(element: dict) -> dict:
    form = element.get("form") or {}
    return {"kind": str(element.get("kind") or ""), "type": str(element.get("type") or ""),
            "name": " ".join(str(element.get("name") or "").split())[:200],
            "form_path": _path(form.get("action") or ""), "secret": bool(element.get("secret"))}


def _path(url: str) -> str:
    logged = policy.log_url(url)
    origin = policy.origin_of(url)
    return logged[len(origin):] if origin and logged.startswith(origin) else ""


def _query_mark(url: str) -> str:
    """A fingerprint of the page's query string: `/edit?id=123` and `/edit?id=456` are different pages. The query
    itself can carry tokens, so only its hash is kept in a recipe."""
    from urllib.parse import parse_qsl, urlsplit
    try:
        pairs = sorted(parse_qsl(urlsplit(str(url or "")).query, keep_blank_values=True))
    except ValueError:
        pairs = []
    return hashlib.sha256(json.dumps(pairs).encode("utf-8")).hexdigest()[:16] if pairs else ""


def draft_from_session(doc: dict, params: Optional[Dict[str, str]] = None) -> List[dict]:
    """Recipe steps from a session's successful steps. ``params`` maps a step's seq to a parameter name."""
    params = {str(k): str(v) for k, v in (params or {}).items() if str(v).strip()}
    out: List[dict] = []
    for step in doc.get("steps") or []:
        kind = step.get("kind")
        if step.get("by") == "owner":
            if kind in ("human_input", "takeover_click", "takeover_type", "takeover_key") and step.get("status") == "done":
                if not out or out[-1]["kind"] != "handoff":
                    out.append({"kind": "handoff"})
            continue
        if step.get("status") != "done" or kind not in ("open", "goto", "act"):
            continue                                   # snapshots, refused, rejected and failed steps are not replayed
        seq = str(step.get("seq"))
        if kind in ("open", "goto"):
            out.append({"kind": kind, "url": str(step.get("url") or "")[:2000], "seq": step.get("seq")})
            continue
        row: Dict[str, Any] = {"kind": "act", "action": step.get("action"), "seq": step.get("seq"),
                               "page": policy.log_url(step.get("page_url") or ""),
                               "page_query": _query_mark(step.get("page_url") or "")}
        element = step.get("element") or {}
        if element:
            row["target"] = _target(element)
        elif step.get("selector"):
            row["selector"] = step["selector"]
        for key in ("key", "value_from", "asset_id"):
            if step.get(key):
                row[key] = step[key]
        if seq in params:
            name = params[seq]
            if not PARAM_RE.fullmatch(name):
                raise HTTPException(400, f"parameter name '{name}' must look like city or first_name")
            if step.get("action") not in ("fill", "select") or step.get("value_from") or element.get("secret"):
                raise HTTPException(400, f"step {seq} cannot be a parameter (only a typed or chosen value can)")
            row["param"] = name
            row["example"] = str(step.get("value") or "")[:200]
        elif step.get("value") not in (None, "") and not step.get("value_from") and step.get("action") != "upload":
            if element.get("secret"):
                raise HTTPException(409, "a step typed into a secret field cannot be saved")     # cannot happen
            row["value"] = str(step["value"])
        out.append(row)
    while out and out[-1]["kind"] == "handoff":
        out.pop()
    unknown = set(params) - {str(r.get("seq")) for r in out if r.get("param")}
    if unknown:
        raise HTTPException(400, f"no successful fill step with number {sorted(unknown)[0]}")
    return out


class RecipeStore:
    def __init__(self, data_dir: Path, *, clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "surfer_actions" / "recipes.json"
        self.clock, self.lock = clock, threading.RLock()
        self._active: set = set()                 # runs this process is replaying right now

    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        data = data if isinstance(data, dict) else {}
        data.setdefault("recipes", [])
        data.setdefault("runs", [])
        for run in data["runs"]:
            # A replay lives in the web process. After a restart nobody is running it: it is reported as
            # interrupted (terminal) and is never resumed or replayed, so no step can happen twice.
            if run.get("status") == "running" and run.get("id") not in self._active:
                run.update(status="interrupted", reason="the web service restarted during the replay; steps "
                           f"1–{max(0, int(run.get('at_step') or 1) - 1)} were done, the step in flight is unknown. "
                           "Check the page before starting it again", finished=int(self.clock()))
        return data

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["runs"] = data["runs"][-KEEP_RUNS:]
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def list(self) -> List[dict]:
        return [dict(r) for r in self._load()["recipes"]]

    def find(self, key: str) -> Optional[dict]:
        key = str(key or "").strip()
        rows = self._load()["recipes"]
        return next((r for r in rows if r["id"] == key), None) or next(
            (r for r in rows if r["name"].lower() == key.lower()), None)

    def save(self, doc: dict, name: str, params: Optional[Dict[str, str]] = None) -> dict:
        name = " ".join(str(name or "").split())
        if not NAME_RE.fullmatch(name):
            raise HTTPException(400, "the recipe name is 2–60 letters, digits, spaces or . , ( ) + - #")
        steps = draft_from_session(doc, params)
        if not steps or steps[0]["kind"] != "open":
            raise HTTPException(409, "this session has no successful steps to save")
        if len(steps) > MAX_RECIPE_STEPS:
            raise HTTPException(409, f"a recipe holds at most {MAX_RECIPE_STEPS} steps")
        session = doc["session"]
        with self.lock:
            data = self._load()
            if any(r["name"].lower() == name.lower() for r in data["recipes"]):
                raise HTTPException(409, "a recipe with this name already exists")
            if len(data["recipes"]) >= MAX_RECIPES:
                raise HTTPException(409, f"at most {MAX_RECIPES} recipes; delete one first")
            recipe = {"id": "rc_" + secrets.token_hex(6), "name": name, "lane": session.get("lane") or "",
                      "site": policy.host_of(steps[0]["url"]), "from_session": session["id"],
                      "created": int(self.clock()), "steps": steps,
                      "params": sorted({s["param"] for s in steps if s.get("param")}), "runs": 0}
            data["recipes"].append(recipe)
            self._save(data)
            return dict(recipe)

    def delete(self, recipe_id: str) -> bool:
        with self.lock:
            data = self._load()
            keep = [r for r in data["recipes"] if r["id"] != recipe_id]
            if len(keep) == len(data["recipes"]):
                return False
            data["recipes"] = keep
            self._save(data)
            return True

    def start_run(self, recipe: dict, lane: str, by: str) -> dict:
        with self.lock:
            data = self._load()
            run = {"id": "rr_" + secrets.token_hex(6), "recipe_id": recipe["id"], "recipe": recipe["name"],
                   "lane": lane, "by": by, "status": "running", "at_step": 0, "steps_total": len(recipe["steps"]),
                   "session_id": "", "reason": "", "started": int(self.clock())}
            data["runs"].append(run)
            self._active.add(run["id"])
            for row in data["recipes"]:
                if row["id"] == recipe["id"]:
                    row["runs"] = int(row.get("runs") or 0) + 1
            self._save(data)
            return dict(run)

    def update_run(self, run_id: str, **changes: Any) -> dict:
        with self.lock:
            data = self._load()
            run = next((r for r in data["runs"] if r["id"] == run_id), None)
            if run is None:
                raise HTTPException(404, "unknown run")
            run.update(changes)
            if run.get("status") != "running":
                self._active.discard(run_id)
            self._save(data)
            return dict(run)

    def run(self, run_id: str) -> Optional[dict]:
        return next((dict(r) for r in self._load()["runs"] if r["id"] == run_id), None)

    def runs(self) -> List[dict]:
        return [dict(r) for r in reversed(self._load()["runs"])]


def public_recipe(recipe: dict) -> dict:
    """What an agent sees of a recipe: no values."""
    return {"id": recipe["id"], "name": recipe["name"], "site": recipe.get("site") or "",
            "params": list(recipe.get("params") or []), "steps": len(recipe.get("steps") or [])}


def check_params(recipe: dict, params: Any) -> Dict[str, str]:
    params = params if isinstance(params, dict) else {}
    wanted = list(recipe.get("params") or [])
    missing = [name for name in wanted if not str(params.get(name) or "")]
    if missing:
        raise HTTPException(400, "missing recipe parameters: " + ", ".join(missing))
    extra = sorted(set(params) - set(wanted))
    if extra:
        raise HTTPException(400, "unknown recipe parameters: " + ", ".join(extra))
    out = {name: str(params[name]) for name in wanted}
    if any(len(v) > sa.MAX_VALUE for v in out.values()):
        raise HTTPException(400, "a parameter value is too long")
    return out


def match_element(snapshot: dict, target: dict) -> tuple:
    """(ref, '') for exactly one element with the recorded label, kind and type; ('', reason) otherwise."""
    found = [e for e in snapshot.get("elements") or [] if _target(e) == target]
    if len(found) == 1:
        return found[0]["ref"], ""
    return "", "element_not_found" if not found else "element_ambiguous"


async def replay(store: sa.ActionStore, gate: Any, recipes: RecipeStore, run: dict, recipe: dict,
                 params: Dict[str, str], **wait_kw: Any) -> dict:
    """Run the recipe step by step through the agent tools. Returns the final run record; never raises."""
    lane, session_id, index = run["lane"], "", 0

    def stop(status: str, reason: str) -> dict:
        store.audit(session=session_id, who="recipe", lane=lane, action="recipe_" + status, element=recipe["name"],
                    result=f"step {index} of {len(recipe['steps'])}", blocker=reason)
        return recipes.update_run(run["id"], status=status, reason=reason[:200], at_step=index,
                                  session_id=session_id, finished=int(store.clock()))

    try:
        for index, step in enumerate(recipe["steps"], 1):
            recipes.update_run(run["id"], at_step=index, session_id=session_id)
            if step["kind"] == "handoff":
                return stop("stopped", "owner_acted_here")       # he typed a code or drove the page himself
            if step["kind"] in ("open", "goto"):
                args = {"url": step["url"], "wait_seconds": STEP_WAIT_SECONDS}
                if session_id:
                    args["session_id"] = session_id
                view = await sa.web_open(store, gate, args, lane, **wait_kw)
                session_id = view.get("session_id") or session_id
            else:
                doc = store.get(session_id)
                session = (doc or {}).get("session") or {}
                if session.get("status") != "active":
                    return stop("stopped", "session_" + str(session.get("status") or "lost"))
                snapshot = store.snapshot(session_id)
                if step.get("page") and (policy.log_url(snapshot.get("url") or "") != step["page"]
                                         or _query_mark(snapshot.get("url") or "") != step.get("page_query", "")):
                    return stop("stopped", "page_differs")       # another address or another record (?id=…)
                args = {"session_id": session_id, "action": step["action"], "wait_seconds": STEP_WAIT_SECONDS}
                if step.get("target"):
                    ref, problem = match_element(snapshot, step["target"])
                    if problem:
                        return stop("stopped", problem)
                    args["ref"] = ref
                elif step.get("selector"):
                    args["selector"] = step["selector"]
                for key in ("key", "value_from", "asset_id", "value"):
                    if key in step:
                        args[key] = step[key]
                if step.get("param"):
                    args["value"] = params[step["param"]]
                view = await sa.web_act(store, gate, args, lane, **wait_kw)
            if view.get("status") != "done":
                return stop("stopped", str(view.get("blocker") or view.get("wait_reason") or view.get("status")))
        return stop("done", "")
    except HTTPException as exc:
        return stop("stopped", str(exc.detail)[:200])
    except Exception as exc:                                   # a replay must never take the web process down
        return stop("stopped", "internal_" + type(exc).__name__)


_BACKGROUND: set = set()


def start(store: sa.ActionStore, gate: Any, recipes: RecipeStore, recipe: dict, params: Any, lane: str, *,
          by: str) -> dict:
    """Check everything that can be checked up front, then replay in the background."""
    gate.require(lane)
    values = check_params(recipe, params)
    if store.live():
        raise HTTPException(409, "another Surfer session is live; a recipe needs its own session")
    run = recipes.start_run(recipe, lane, by)
    task = asyncio.get_running_loop().create_task(replay(store, gate, recipes, run, recipe, values))
    _BACKGROUND.add(task)
    task.add_done_callback(_BACKGROUND.discard)
    return run


async def call_tool(args: dict, *, store: sa.ActionStore, gate: Any, recipes: RecipeStore, lane: str) -> dict:
    if not isinstance(args, dict):
        raise HTTPException(400, "arguments must be an object")
    if not lane:
        raise HTTPException(403, "Surfer recipes need your own lane MCP token; the shared MCP token may not act")
    gate.require(lane)
    if args.get("run_id"):
        run = recipes.run(str(args["run_id"])) if RUN_ID_RE.fullmatch(str(args["run_id"])) else None
        if not run or run["lane"] != lane:
            raise HTTPException(404, "unknown run")
        return run
    if not args.get("recipe"):
        return {"recipes": [public_recipe(r) for r in recipes.list()]}
    recipe = recipes.find(args["recipe"])
    if not recipe:
        raise HTTPException(404, "unknown recipe; call web_recipe {} for the list")
    return start(store, gate, recipes, recipe, args.get("params"), lane, by=lane)


def install_routes(app, *, store: sa.ActionStore, gate: Any, recipes: RecipeStore, identity: Callable) -> None:
    def owner(request: Request) -> None:
        if (identity(request) or {}).get("role") != "owner":
            raise HTTPException(403, "Owner access required")

    async def body_of(request: Request) -> dict:
        try:
            data = await request.json()
        except ValueError:
            raise HTTPException(400, "json body required")
        return data if isinstance(data, dict) else {}

    def owner_view(recipe: dict) -> dict:
        steps = []
        for step in recipe["steps"]:
            row = {k: step[k] for k in ("kind", "action", "url", "param", "example", "value", "value_from", "key",
                                        "seq") if k in step}
            row["element"] = (step.get("target") or {}).get("name") or step.get("selector") or ""
            steps.append(row)
        return {**{k: recipe[k] for k in ("id", "name", "lane", "site", "created", "params", "runs")}, "steps": steps}

    @app.get("/api/factory/surfer/owner/recipes")
    def surfer_recipes(request: Request):
        owner(request)
        return {"recipes": [owner_view(r) for r in recipes.list()], "runs": recipes.runs()[:10]}

    @app.post("/api/factory/surfer/owner/recipes")
    async def surfer_recipe_save(request: Request):
        """The owner approves saving a session as a recipe: {session_id, name, params: {"<step number>": "name"}}."""
        owner(request)
        body = await body_of(request)
        doc = store.get(str(body.get("session_id") or ""))
        if not doc:
            raise HTTPException(404, "unknown session")
        recipe = recipes.save(doc, body.get("name"), body.get("params") if isinstance(body.get("params"), dict) else None)
        store.audit(session=doc["session"]["id"], who="owner", action="recipe_save", element=recipe["name"],
                    result=f"{len(recipe['steps'])} steps")
        return {"recipe": owner_view(recipe)}

    @app.post("/api/factory/surfer/owner/recipes/{recipe_id}/delete")
    def surfer_recipe_delete(recipe_id: str, request: Request):
        owner(request)
        if not RECIPE_ID_RE.fullmatch(recipe_id) or not recipes.delete(recipe_id):
            raise HTTPException(404, "unknown recipe")
        store.audit(who="owner", action="recipe_delete", element=recipe_id)
        return {"ok": True}

    @app.post("/api/factory/surfer/owner/recipes/{recipe_id}/run")
    async def surfer_recipe_run(recipe_id: str, request: Request):
        owner(request)
        recipe = recipes.find(recipe_id) if RECIPE_ID_RE.fullmatch(recipe_id) else None
        if not recipe:
            raise HTTPException(404, "unknown recipe")
        if recipe.get("lane") not in ("claude", "chatgpt", "gemini"):
            raise HTTPException(409, "this recipe has no lane")
        body = await body_of(request)
        # The session belongs to the lane that recorded the recipe, so that agent can continue after a stop.
        return {"run": start(store, gate, recipes, recipe, body.get("params"), recipe["lane"], by="owner")}
