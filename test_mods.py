"""T-620 Mods & skills: vendored plugins (A), registry and switches (B), worker runtime (C), video duel (D).

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
from autopilot import delegation as dg  # noqa: E402
from autopilot import mods_runtime as rt  # noqa: E402
from autopilot import relay_tasks  # noqa: E402

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


def make(tmp=None, **hooks):
    store = mr.ModsStore(Path(tmp or tempfile.mkdtemp(prefix="factoryos-mods-")) / "mods.json")
    app = fastapi.FastAPI()
    mr.install_mods_routes(app, store, identity=lambda r: {"role": r.role}, worker_auth=lambda r: r.worker, **hooks)
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


PLAN_ALL = {"enabled": ["brand-strategy", "grilling", "poteto-mode", "product-film"],
            "plugins": [{"id": "poteto-mode", "plugin": "pstack", "invoke": "/pstack:poteto-mode"},
                        {"id": "grilling", "plugin": "grilling", "invoke": ""},
                        {"id": "product-film", "plugin": "product-film", "invoke": ""}]}


def test_runtime_resolve_fails_closed():
    off = rt.resolve(ROOT, "roadmap", None, True)
    require(off == {"mods": [], "plugins": [], "applied": False, "note": "mods plan unavailable (server unreachable)"}, off)
    require(rt.resolve(ROOT, "roadmap", {"plugins": []}, False)["applied"], "no mods switched on is a clean run")
    require(not rt.resolve(ROOT, "roadmap", PLAN_ALL, False)["applied"], "old CLI must run without mods")
    road = rt.resolve(ROOT, "roadmap", PLAN_ALL, True)
    require(road["mods"] == ["poteto-mode", "grilling"] and road["applied"], f"roadmap loads dev mods only: {road}")
    relay = rt.resolve(ROOT, "relay", PLAN_ALL, True)
    require(relay["plugins"] == ["pstack", "grilling", "product-film"], f"relay plugins: {relay}")
    for bad in ("../etc", "nope", "a/b"):
        r = rt.resolve(ROOT, "roadmap", {"plugins": [{"id": "grilling", "plugin": bad}]}, True)
        require(not r["applied"] and not r["mods"], f"plugin folder {bad!r} accepted")
    calls = []
    r = rt.prepare(ROOT, "roadmap", plan_fn=lambda: {"plugins": []}, support_fn=lambda: calls.append(1) or False)
    require(r["applied"] and not calls, "CLI probed although nothing is switched on")


def test_runtime_flags_prompt_and_tools():
    import subprocess
    repo = Path(tempfile.mkdtemp(prefix="factoryos-mods-repo-"))
    subprocess.run(["git", "init", "-q", "-b", "work", str(repo)], check=True)
    ctx = rt.resolve(ROOT, "roadmap", PLAN_ALL, True)
    task = {"id": "T-999", "title": "x"}
    plain = dg.build_delegation(task, repo)["cmd"]
    require("--plugin-dir" not in plain and "Skill" not in plain and plain[2].startswith("Работай"), "no-mod run changed")
    cmd = dg.build_delegation(task, repo, mods=ctx)["cmd"]
    require(cmd[2].startswith("/pstack:poteto-mode Работай строго по CLAUDE.md"), "poteto-mode not invoked first")
    dirs = [cmd[i + 1] for i, a in enumerate(cmd) if a == "--plugin-dir"]
    require(dirs == [str(repo.resolve() / "mods" / "pstack"), str(repo.resolve() / "mods" / "grilling")], dirs)
    require(cmd.index("--append-system-prompt") < cmd.index("--allowedTools"), "variadic tool list would eat the flags")
    rules = cmd[cmd.index("--append-system-prompt") + 1]
    require("headless" in rules and "DECISIONS.md" in rules and "Autonomy section does not apply" in rules, rules)
    allowed = cmd[cmd.index("--allowedTools") + 1:cmd.index("--disallowedTools")]
    require({"Skill", "Task", "Agent"} <= set(allowed), "skills/subagents not allowed while poteto-mode is on")
    require({"Bash(dsp:*)", "Bash(git push:*)"} <= set(cmd[cmd.index("--disallowedTools") + 1:]), "safety deny-list lost")
    film = rt.cli_args(rt.resolve(ROOT, "relay", {"plugins": [PLAN_ALL["plugins"][2]]}, True), Path("/w"))
    require(film[:2] == ["--plugin-dir", "/w/mods/product-film"] and "BLOCKED" in film[-1], film)


def test_runtime_reports_runs():
    sent = []

    class R:
        status_code = 200

    os.environ.pop("FACTORYOS_URL", None)
    require(not rt.report_run({"mods": []}, run_id="r", task="T", kind="roadmap", result="done", duration_seconds=1,
                              post=lambda *a, **k: sent.append(k) or R()), "reported without a server")
    os.environ.update(FACTORYOS_URL="https://factory.example", FACTORY_CLAUDE_WORKER_TOKEN="t" * 40)
    try:
        ok = rt.report_run({"mods": ["grilling"], "applied": True}, run_id="run-1", task="T-1", kind="relay",
                           result="weird", duration_seconds=12.34, post=lambda *a, **k: sent.append((a, k)) or R())
        (url,), kw = sent[-1]
        require(ok and url == "https://factory.example/api/mods/worker/run", url)
        require(kw["json"] == {"run_id": "run-1", "task": "T-1", "kind": "relay", "result": "failed", "duration_seconds": 12.3,
                               "mods": ["grilling"], "applied": True, "note": ""}, kw["json"])

        class Bad:
            status_code = 500
        require(rt.fetch_plan(get=lambda *a, **k: Bad()) is None, "server error must mean no plan")
        require(rt.fetch_plan(get=lambda *a, **k: (_ for _ in ()).throw(OSError())) is None, "network error must mean no plan")
        # Relay: run_one loads the plan, passes it to the executor and reports the executor's real outcome.
        seen = {}
        orig = (relay_tasks.claim, relay_tasks.execute_isolated, rt.prepare, rt.report_run)
        relay_tasks.claim = lambda: {"id": "R-0001", "execution": {"run_id": "run-77"}}
        relay_tasks.execute_isolated = lambda t, repo, **k: seen.update(mods=k["mods"]) or {"status": "blocked"}
        rt.prepare = lambda repo, kind: {"mods": ["product-film"], "plugins": ["product-film"], "applied": True, "kind": kind}
        rt.report_run = lambda ctx, **k: seen.update(report=k)
        try:
            relay_tasks.run_one(ROOT)
        finally:
            relay_tasks.claim, relay_tasks.execute_isolated, rt.prepare, rt.report_run = orig
        require(seen["mods"]["kind"] == "relay" and seen["report"]["result"] == "blocked"
                and seen["report"]["run_id"] == "run-77", seen)
    finally:
        os.environ.pop("FACTORYOS_URL", None)
        os.environ.pop("FACTORY_CLAUDE_WORKER_TOKEN", None)


def test_video_duel():
    jobs, tickets = [], []

    async def create_job(title, brief, fmt):
        jobs.append((title, brief, fmt))
        return f"job-{len(jobs)}"

    def create_ticket(title, body, key):
        tickets.append((title, body, key))
        return f"R-{len(tickets):04d}"
    store, h = make(create_job=create_job, create_ticket=create_ticket,
                    job_state=lambda j: {"status": "review"}, ticket_state=lambda t: {"status": "inbox", "execution": "queued"})
    new, start = h[("POST", "/api/factory/mods/duels")], h[("POST", "/api/factory/mods/duels/{duel_id}/arms/{arm}/start")]
    upd, toggle = h[("POST", "/api/factory/mods/duels/{duel_id}/arms/{arm}")], h[("POST", "/api/factory/mods/{mod_id}")]
    require(status_of(new, Req({"title": "x", "brief": "y"}, role="member")) == 403, "member created a duel")
    for bad in ({"title": "", "brief": "y"}, {"title": "x", "brief": "y", "factory_tool": "product-film"}):
        require(status_of(new, Req(bad)) == 422, f"bad duel accepted: {bad}")
    v = run(new(Req({"title": "Launch", "brief": "Show the MyCast daily podcast", "factory_tool": "media-finisher"})))
    d = v["duels"][0]
    require(d["id"] == "D-0001" and [a["tool"] for a in d["arms"]] == ["media-finisher"] * 2 + ["product-film"] * 2, d)
    require(not d["verdict"]["ready"] and d["verdict"]["missing"] == ["a1", "a2", "b1", "b2"], "verdict without scores")
    require(status_of(start, "D-0001", "b1", Req()) == 409 and not tickets, "B arm started while product-film is off")
    require(status_of(start, "D-0009", "a1", Req()) == 404 and status_of(start, "D-0001", "c1", Req()) == 404, "bad ids")
    run(start("D-0001", "a1", Req())); run(start("D-0001", "a1", Req()))   # second click: same job
    require(len(jobs) == 1 and jobs[0][2] == "Shorts" and "ТОЛЬКО ЧЕРНОВИК" in jobs[0][1] and "media-finisher" in jobs[0][1],
            f"A arm job wrong: {jobs}")
    run(toggle("product-film", Req({"enabled": True})))
    v = run(start("D-0001", "b2", Req()))
    require(len(tickets) == 1 and tickets[0][2] == "mods-duel:D-0001:b2" and "/product-film:product-film" in tickets[0][1]
            and "Ничего не публиковать" in tickets[0][1], f"B arm ticket wrong: {tickets}")
    arms = {a["id"]: a for a in v["duels"][0]["arms"]}
    require(arms["a1"]["job_id"] == "job-1" and arms["a1"]["live"] == {"status": "review"}, arms["a1"])
    require(arms["b2"]["ticket_id"] == "R-0001" and arms["b2"]["live"]["execution"] == "queued", arms["b2"])
    require(mod(v, "product-film")["uses"] == 1, "product-film use not counted")
    for bad in ({"score": 6}, {"score": True}, {"score": "5"}, {"result_url": "javascript:alert(1)"}, {}):
        require(status_of(upd, "D-0001", "a1", Req(bad)) == 422, f"bad arm update accepted: {bad}")
    require(status_of(upd, "D-0001", "a2", Req({"score": 3})) == 409, "scored a take that does not exist")
    for arm, score in (("a1", 4), ("a2", 2), ("b1", 5)):
        v = run(upd("D-0001", arm, Req({"score": score, "result_url": "https://example.com/v.mp4"})))
    require(not v["duels"][0]["verdict"]["ready"], "verdict from three scores")
    v = run(upd("D-0001", "b2", Req({"score": 4})))
    ver = v["duels"][0]["verdict"]
    require(ver == {"ready": True, "avg_a": 3.0, "avg_b": 4.5, "winner": "b", "winner_tool": "product-film"}, ver)
    v = run(upd("D-0001", "b2", Req({"score": None})))
    require(not v["duels"][0]["verdict"]["ready"], "clearing a score must withdraw the verdict")

    async def boom(*a):
        raise RuntimeError("db down")
    store2, h2 = make(create_job=boom)
    run(h2[("POST", "/api/factory/mods/duels")](Req({"title": "x", "brief": "y"})))
    st = h2[("POST", "/api/factory/mods/duels/{duel_id}/arms/{arm}/start")]
    require(status_of(st, "D-0001", "a1", Req()) == 502, "failed start not reported")
    require("starting" not in store2.read()["duels"]["D-0001"]["arms"]["a1"], "failed start must release the arm")


TESTS = [test_video_duel, test_runtime_resolve_fails_closed, test_runtime_flags_prompt_and_tools, test_runtime_reports_runs,
         test_vendored_plugins, test_no_binaries_or_external_publishing, test_pstack_bundle_is_complete,
         test_defaults_and_owner_only, test_toggle_history_and_worker_plan, test_runs_compare_and_uses,
         test_unreadable_state_fails_safe, test_dashboard_wiring]

if __name__ == "__main__":
    for t in TESTS:
        t()
        print("ok", t.__name__)
    print(f"Mods tests passed: {len(TESTS)}")
