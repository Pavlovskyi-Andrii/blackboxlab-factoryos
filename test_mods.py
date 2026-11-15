"""T-611 Mods & skills: vendored plugins (A), registry and switches (B).

Run: python test_mods.py
"""
from __future__ import annotations

import json
import os
import re
import asyncio
import tempfile
from pathlib import Path

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-mods-"))
import fastapi  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import mods_registry as mr  # noqa: E402

ROOT = Path(__file__).resolve().parent
MODS = ROOT / "mods"


def require(ok, msg):
    if not ok:
        raise AssertionError(msg)


def test_vendored_plugins():
    readme = (MODS / "README.md").read_text(encoding="utf-8")
    for folder, skill in (("pstack", "poteto-mode"), ("grilling", "grilling"), ("product-film", "product-film")):
        manifest = json.loads((MODS / folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
        require(manifest["name"] == folder, f"{folder}: plugin name {manifest['name']!r}")
        require(manifest.get("license") == "MIT", f"{folder}: license not recorded")
        require((MODS / folder / "LICENSE").is_file(), f"{folder}: upstream LICENSE missing")
        text = (MODS / folder / "skills" / skill / "SKILL.md").read_text(encoding="utf-8")
        require(re.search(rf"^name: {re.escape(skill)}$", text, re.M), f"{folder}: SKILL.md lost its name")
        require(f"`{folder}/`" in readme, f"{folder}: provenance row missing in mods/README.md")
    require(re.search(r"\| `[0-9a-f]{7}` \(", readme), "upstream commits not pinned in mods/README.md")


def test_no_binaries_or_external_publishing():
    for path in MODS.rglob("*"):
        if not path.is_file():
            continue
        head = path.read_bytes()[:4]
        require(head not in (b"\x7fELF", b"MZ\x90\x00") and head[:2] != b"MZ" and head not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"),
                f"executable binary vendored: {path.relative_to(ROOT)}")
    pf = MODS / "product-film" / "skills" / "product-film"
    require(not (pf / "bin").exists(), "product-film bundled binaries must stay removed")
    require(not (pf / "scripts" / "publish.sh").exists() and not (pf / "scripts" / "_common.sh").exists(),
            "display.dev publish scripts must stay removed")
    skill = (pf / "SKILL.md").read_text(encoding="utf-8")
    front = skill.split("---", 2)[1]
    require("publish.sh" not in front and "dsp " not in front, "publish tools must not be pre-allowed")
    require("FactoryOS build" in skill and "Never publish" in skill, "product-film FactoryOS banner missing")
    require("display.dev" not in (pf / "references" / "publish.md").read_text(encoding="utf-8").split("FactoryOS removed")[1],
            "publish reference must keep review files local")


def test_pstack_bundle_is_complete():
    skills = MODS / "pstack" / "skills"
    poteto = (skills / "poteto-mode" / "SKILL.md").read_text(encoding="utf-8")
    # poteto-mode routes to bundled skills by name; each one it names must ship with it.
    for name in ("architect", "swarm", "arena", "interrogate", "unslop", "technical-writing", "no-comments",
                 "figure-it-out", "show-me-your-work", "benchmark-checklist"):
        require(f"**{name}**" in poteto or f"`/{name}`" in poteto, f"poteto-mode no longer routes to {name}")
        require((skills / name / "SKILL.md").is_file(), f"pstack skill {name} missing")
    for ref in re.findall(r"\(`(playbooks/[a-z0-9-]+\.md)`\)", poteto):
        require((skills / "poteto-mode" / ref).is_file(), f"poteto-mode playbook {ref} missing")
    require((MODS / "pstack" / "docs" / "harness" / "claude-code.md").is_file(), "Claude Code adapter missing")
    require((MODS / "pstack" / "agents" / "poteto-agent.md").is_file(), "poteto-agent subagent missing")


class Req:
    def __init__(self, body=None, role="owner", worker=False):
        self.body, self.role, self.worker = body, role, worker

    async def json(self):
        if isinstance(self.body, Exception):
            raise self.body
        return self.body


def run(x):
    return asyncio.run(x) if asyncio.iscoroutine(x) else x


def make(tmp=None):
    store = mr.ModsStore(Path(tmp or tempfile.mkdtemp(prefix="factoryos-mods-")) / "mods.json")
    app = fastapi.FastAPI()
    mr.install_mods_routes(app, store, identity=lambda r: {"role": r.role}, worker_auth=lambda r: r.worker)
    h = {(next(iter(r.methods)), r.path): r.endpoint for r in app.routes if hasattr(r, "methods")}
    return store, h


def status_of(fn, *args):
    try:
        run(fn(*args))
    except HTTPException as exc:
        return exc.status_code
    return 200


def mod(view, mod_id):
    return next(m for m in view["mods"] if m["id"] == mod_id)


def test_defaults_and_owner_only():
    store, h = make()
    get, toggle = h[("GET", "/api/factory/mods")], h[("POST", "/api/factory/mods/{mod_id}")]
    v = get(Req())
    require([m["id"] for m in v["mods"]] == [m["id"] for m in mr.CATALOG], "catalog order changed")
    require(mod(v, "brand-strategy")["enabled"] and not mod(v, "poteto-mode")["enabled"], "defaults wrong")
    require(all(m["enabled"] for m in v["mods"] if not m["toggle"]), "built-in tools must read as on")
    require(not store.path.exists(), "reading must not write state")
    for role in ("member", "viewer"):
        require(status_of(get, Req(role=role)) == 403, f"{role} can read mods")
        require(status_of(toggle, "grilling", Req({"enabled": True}, role=role)) == 403, f"{role} can switch")
    require(status_of(toggle, "nope", Req({"enabled": True})) == 404, "unknown mod accepted")
    require(status_of(toggle, "revideo", Req({"enabled": False})) == 409, "built-in tool switched off")
    for bad in ({"enabled": "yes"}, {}, ValueError("x")):
        require(status_of(toggle, "grilling", Req(bad)) in (400, 422), f"bad body accepted: {bad!r}")


def test_toggle_history_and_worker_plan():
    store, h = make()
    toggle, plan = h[("POST", "/api/factory/mods/{mod_id}")], h[("GET", "/api/mods/worker/plan")]
    require(status_of(plan, Req()) == 401, "worker plan open without the worker token")
    require(run(plan(Req(worker=True)))["plugins"] == [], "nothing is loaded before the owner switches a mod on")
    v = run(toggle("poteto-mode", Req({"enabled": True})))
    run(toggle("poteto-mode", Req({"enabled": True})))          # same state twice: one history row
    run(toggle("product-film", Req({"enabled": True})))
    m = mod(v, "poteto-mode")
    require(m["enabled"] and m["since"] and len(m["history"]) == 1 and m["history"][0]["enabled"], "switch not recorded")
    p = run(plan(Req(worker=True)))
    require(p["plugins"] == [{"id": "poteto-mode", "plugin": "pstack", "invoke": "/pstack:poteto-mode"},
                             {"id": "product-film", "plugin": "product-film", "invoke": ""}], f"plan wrong: {p}")
    require("brand-strategy" in p["enabled"] and all(x["id"] != "brand-strategy" for x in p["plugins"]),
            "brand strategy is a server feature, not a worker plugin")
    run(toggle("poteto-mode", Req({"enabled": False})))
    require([x["id"] for x in run(plan(Req(worker=True)))["plugins"]] == ["product-film"], "switch-off not applied")
    require(len(mod(h[("GET", "/api/factory/mods")](Req()), "poteto-mode")["history"]) == 2, "switch-off not in history")


def test_runs_compare_and_uses():
    store, h = make()
    post = h[("POST", "/api/mods/worker/run")]
    require(status_of(post, Req({"run_id": "r1", "result": "done"})) == 401, "run accepted without worker token")
    for bad in ({"result": "done"}, {"run_id": "r1", "result": "maybe"}, {"run_id": "r1", "result": "done", "mods": ["revideo"]},
                {"run_id": "r1", "result": "done", "kind": "x"}, {"run_id": "bad id!", "result": "done"},
                {"run_id": "r1", "result": "done", "duration_seconds": "x"}):
        require(status_of(post, Req(bad, worker=True)) == 422, f"bad run accepted: {bad}")

    def rec(i, result, mods, applied=True, dur=600):
        return run(post(Req({"run_id": f"run-{i}", "task": "T-1", "result": result, "duration_seconds": dur,
                             "mods": mods, "applied": applied}, worker=True)))
    require(rec(1, "done", ["poteto-mode"])["recorded"] and not rec(1, "done", ["poteto-mode"])["recorded"], "run_id not idempotent")
    c = mr.view(store.read())
    require(not mod(c, "poteto-mode")["compare"]["ready"] and mod(c, "poteto-mode")["compare"]["done_rate_delta"] is None,
            "comparison claimed from one run")
    rec(2, "done", ["poteto-mode"]); rec(3, "failed", ["poteto-mode"])
    rec(4, "done", ["poteto-mode"], applied=False)                 # mods could not be applied: counts as without
    rec(5, "failed", []); rec(6, "blocked", [])
    v = mr.view(store.read())
    cmp = mod(v, "poteto-mode")["compare"]
    require(cmp["with"]["runs"] == 3 and cmp["with"]["done"] == 2 and cmp["without"]["runs"] == 3, f"split wrong: {cmp}")
    require(cmp["ready"] and cmp["done_rate_delta"] == round(2 / 3 - 1 / 3, 3), f"delta wrong: {cmp}")
    require(cmp["with"]["avg_minutes"] == 10.0, "duration average wrong")
    require(mod(v, "poteto-mode")["uses"] == 3, "uses must count only applied runs")
    require(v["runs_total"] == 6 and v["recent_runs"][0]["run_id"] in {"run-6", "run-5"}, "recent runs wrong")


def test_unreadable_state_fails_safe():
    store, h = make()
    store.path.write_text("{broken", encoding="utf-8")
    require(store.enabled("brand-strategy") is True and store.enabled("grilling") is False, "bad file must mean defaults")
    store.use("grilling")                                          # never raises
    require(store.path.read_text(encoding="utf-8") == "{broken", "a broken state file must not be overwritten silently")
    require(status_of(h[("GET", "/api/factory/mods")], Req()) == 503, "unreadable state must be reported")
    require(status_of(h[("GET", "/api/mods/worker/plan")], Req(worker=True)) == 503, "worker must see the failure")


def test_dashboard_wiring():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    require('data-nav-group="mods"' in html and 'id="modsCard"' in html, "Mods & skills section missing")
    for m in mr.CATALOG:
        require(f'"mods.m.{m["id"]}.name"' in html and f'"mods.m.{m["id"]}.desc"' in html, f"{m['id']}: no dashboard copy")
    require("loadMods();" in html and "const mdc=$('#modsCard');if(mdc)mdc.style.display=readOnly?'none':''" in html,
            "card not loaded or not hidden from viewers")


TESTS = [test_vendored_plugins, test_no_binaries_or_external_publishing, test_pstack_bundle_is_complete,
         test_defaults_and_owner_only, test_toggle_history_and_worker_plan, test_runs_compare_and_uses,
         test_unreadable_state_fails_safe, test_dashboard_wiring]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok", t.__name__)
    print(f"Mods tests passed: {len(TESTS)}")
