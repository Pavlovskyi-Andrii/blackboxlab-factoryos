"""T-MODS-C: the Claude worker loads the mods the owner switched on in the dashboard (Mods & skills).

Per run: read the plan from FactoryOS (worker token), keep only plugin folders that exist in the checkout the run
uses, and turn them into ``--plugin-dir`` flags plus one system prompt that keeps the run headless and inside
CLAUDE.md. Then report the run with the mods it really loaded, so the dashboard can compare with/without.

Fail-safe in one direction only: anything uncertain (server unreachable, CLI without ``--plugin-dir``, a plugin
folder missing) means the run goes ahead WITHOUT mods and is reported as ``applied: false`` with the reason.
A mod is never loaded that the server did not list.
"""
from __future__ import annotations

import os
import pathlib
import subprocess
from typing import Any, Callable, Optional

# product-film is only for video tickets (Relay); ROADMAP engineering runs load the development mods only.
RUN_MODS = {"roadmap": ("poteto-mode", "grilling"), "relay": ("poteto-mode", "grilling", "product-film")}

BASE_RULES = (
    "FactoryOS mods loaded for this run: {mods}. This run is headless: never ask the user a question and never wait "
    "for an answer. The repository CLAUDE.md and the task prompt override every skill: no push, merge, deploy, "
    "publishing, uploads, purchases, paid APIs, external messages or new external accounts; never print secrets."
)
RULES = {
    "poteto-mode": (
        "poteto-mode: follow its matched playbook and principles, but its Autonomy section does not apply here. "
        "External actions (team chat, tickets, PR comments, evals, Shipping/Babysit playbooks) are not allowed. "
        "If a subagent model slug is rejected, omit the model so the subagent runs on the parent model."
    ),
    "grilling": (
        "grilling, headless single pass: before you edit code, grill your own plan. Build the design tree, answer "
        "every frontier question yourself with the recommended answer and evidence from the code, and continue "
        "until the frontier is empty. Record the settled decisions as a short dated section in DECISIONS.md. A "
        "question only the owner can answer (secret, payment, external account, publishing, irreversible business "
        "choice) ends the run as blocked with that need, as CLAUDE.md says."
    ),
    "product-film": (
        "product-film: render locally with Playwright and ffmpeg only. If Node 18+, ffmpeg or Playwright is missing, "
        "stop and report BLOCKED naming the missing tool. Never commit rendered video to git: keep the film folder "
        "under /tmp/factoryos-films/ and report the MP4, poster and review page paths."
    ),
}
# Extra tools a ROADMAP run needs only when a mod is loaded (headless runs deny everything not pre-allowed).
EXTRA_TOOLS = {"poteto-mode": ("Skill", "Task", "Agent"), "grilling": ("Skill",), "product-film": ("Skill",)}

_PLUGIN_DIR_SUPPORT: Optional[bool] = None


def endpoint() -> tuple:
    return (os.environ.get("FACTORYOS_URL", "").strip().rstrip("/"),
            os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN", "").strip())


def fetch_plan(*, get: Optional[Callable[..., Any]] = None) -> Optional[dict]:
    url, token = endpoint()
    if not url or not token:
        return None
    if get is None:
        import requests
        get = requests.get
    try:
        r = get(f"{url}/api/mods/worker/plan", headers={"Authorization": f"Bearer {token}"}, timeout=10)
        if not 200 <= int(getattr(r, "status_code", 0)) < 300:
            return None
        data = r.json()
        return data if isinstance(data, dict) and isinstance(data.get("plugins"), list) else None
    except Exception:
        return None


def cli_supports_plugin_dir(*, runner: Callable[..., Any] = subprocess.run) -> bool:
    global _PLUGIN_DIR_SUPPORT
    if _PLUGIN_DIR_SUPPORT is None:
        try:
            out = runner(["claude", "--help"], text=True, capture_output=True, timeout=30, check=False)
            _PLUGIN_DIR_SUPPORT = "--plugin-dir" in str(out.stdout or "") + str(out.stderr or "")
        except Exception:
            _PLUGIN_DIR_SUPPORT = False
    return bool(_PLUGIN_DIR_SUPPORT)


def resolve(repo: pathlib.Path, kind: str, plan: Optional[dict], supports: bool) -> dict:
    """Decide what this run loads. Returns {mods, plugins, applied, note}; plugins are folder names under mods/."""
    wanted = RUN_MODS.get(kind, ())
    if plan is None:
        return {"mods": [], "plugins": [], "applied": False, "note": "mods plan unavailable (server unreachable)"}
    rows = [p for p in plan.get("plugins") or [] if isinstance(p, dict) and p.get("id") in wanted]
    if not rows:
        return {"mods": [], "plugins": [], "applied": True, "note": ""}
    if not supports:
        return {"mods": [], "plugins": [], "applied": False, "note": "claude CLI has no --plugin-dir"}
    mods, plugins, missing = [], [], []
    for row in rows:
        folder = str(row.get("plugin") or "")
        if folder and "/" not in folder and ".." not in folder and \
                (pathlib.Path(repo) / "mods" / folder / ".claude-plugin" / "plugin.json").is_file():
            mods.append(row["id"])
            plugins.append(folder)
        else:
            missing.append(row["id"])
    if missing:
        return {"mods": [], "plugins": [], "applied": False, "note": "plugin folder missing: " + ", ".join(missing)}
    return {"mods": mods, "plugins": plugins, "applied": True, "note": ""}


def prepare(repo: pathlib.Path, kind: str, *, plan_fn=fetch_plan, support_fn=cli_supports_plugin_dir) -> dict:
    plan = plan_fn()
    wants_any = plan is not None and any(isinstance(p, dict) and p.get("id") in RUN_MODS.get(kind, ())
                                         for p in plan.get("plugins") or [])
    return resolve(repo, kind, plan, support_fn() if wants_any else True)


def cli_args(ctx: dict, base: pathlib.Path) -> list:
    """--plugin-dir flags (relative to the checkout the run uses) and the headless rules."""
    if not ctx.get("mods"):
        return []
    args: list = []
    for folder in ctx["plugins"]:
        args += ["--plugin-dir", str(pathlib.Path(base) / "mods" / folder)]
    rules = [BASE_RULES.format(mods=", ".join(ctx["mods"]))] + [RULES[m] for m in ctx["mods"] if m in RULES]
    return args + ["--append-system-prompt", "\n\n".join(rules)]


def prompt_prefix(ctx: dict) -> str:
    return "/pstack:poteto-mode " if "poteto-mode" in (ctx.get("mods") or []) else ""


def extra_tools(ctx: dict) -> list:
    out: list = []
    for m in ctx.get("mods") or []:
        out += [t for t in EXTRA_TOOLS.get(m, ()) if t not in out]
    return out


def report_run(ctx: dict, *, run_id: str, task: str, kind: str, result: str, duration_seconds: float,
               post: Optional[Callable[..., Any]] = None) -> bool:
    """Best effort: a lost report only means one run is missing from the comparison."""
    url, token = endpoint()
    if not url or not token or not run_id:
        return False
    if post is None:
        import requests
        post = requests.post
    result = result if result in ("done", "blocked", "failed") else "failed"
    try:
        r = post(f"{url}/api/mods/worker/run", headers={"Authorization": f"Bearer {token}"}, timeout=10,
                 json={"run_id": run_id[:120], "task": task[:40], "kind": kind, "result": result,
                       "duration_seconds": round(float(duration_seconds or 0), 1), "mods": list(ctx.get("mods") or []),
                       "applied": bool(ctx.get("applied")), "note": str(ctx.get("note") or "")[:200]})
        return 200 <= int(getattr(r, "status_code", 0)) < 300
    except Exception:
        return False
