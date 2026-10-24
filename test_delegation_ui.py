"""T-536-D Worker / Delegation Control Center UI regression.

Static checks always run. The fixture rendering check runs the real inline renderers from
static/index.html under Node: desktop/mobile layout, task states, worker online/stale/offline,
telemetry, counts and the T-536-E execution timeline. Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it the
check is reported as SKIPPED, never as passed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- delegation-center:begin"
END = "// --- delegation-center:end"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]  # skip the rest of the marker comment line
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return script, block, i18n, helpers, tr


def static_checks(html, script, block):
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(".dcGrid{display:grid;grid-template-columns:minmax(0,1.4fr) minmax(0,1fr)" in css, "desktop two-column grid missing")
    mobile = re.search(r"@media\(max-width:820px\)\{[^\n]*\.dcGrid\{grid-template-columns:1fr\}", css)
    require(mobile is not None, "mobile stacked grid missing")
    require(".dcMini{position:sticky" in css, "sticky mobile mini-status missing")
    require('onclick="openDelegationCenter()"' in html and 'data-i18n="dc.nav"' in html, "Workers navigation entry missing")
    require('id="dcPage"' in html and 'id="dcBody"' in html and 'data-i18n="dc.title"' in html, "Control Center page missing")
    require("/api/factory/delegation-board" in script, "Control Center must read the owner-safe delegation board API")
    require("innerHTML" not in block and "document." not in block and "fetch(" not in block, "renderers must stay pure (no DOM/network)")
    require(not re.search(r"token|api_key|password|secret", block, re.I), "renderers must not reference secret fields")
    keys = set(re.findall(r"tr\('(dc\.[a-zA-Z.]*[a-zA-Z])'", block))
    keys |= {f"dc.state.{s}" for s in ("done", "running", "queued", "blocked", "human")}
    keys |= {f"dc.connection.{s}" for s in ("online", "stale", "offline")}
    keys |= {f"dc.stage.{s}" for s in ("starting", "syncing", "idle", "running", "pushing", "blocked", "failed", "unknown")}
    keys |= {f"dc.tl.{s}" for s in ("queued", "picked", "running", "checks", "commit", "push", "outcome", "done", "blocked", "failed")}
    keys |= {f"dc.tl.status.{s}" for s in ("observed", "unavailable", "pending", "skipped")}
    keys |= set(re.findall(r'data-i18n="(dc\.[a-zA-Z.]+)"', html))
    for key in sorted(keys):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist in EN/UK/RU")
    return keys


NOW_TREE = [
    {"id": "T-500", "title": "Legacy done", "state": "done", "source": "roadmap", "planner": "", "parent": "", "depends": [],
     "goal": "", "done_criteria": "", "queue_position": None, "depth": 0, "children_done": 0, "children_total": 0, "children": []},
    {"id": "T-536", "title": "Control Center", "state": "queued", "source": "roadmap", "planner": "", "parent": "", "depends": [],
     "goal": "", "done_criteria": "", "queue_position": 1, "depth": 0, "children_done": 1, "children_total": 4, "children": [
        {"id": "T-536-A", "title": "Board API", "state": "done", "source": "ChatGPT", "planner": "ChatGPT", "parent": "T-536", "depends": [],
         "goal": "expose board", "done_criteria": "board regression passes", "queue_position": None, "depth": 1,
         "children_done": 0, "children_total": 0, "children": []},
        {"id": "T-536-B", "title": "Telemetry <script>alert(1)</script>", "state": "running", "source": "ChatGPT", "planner": "ChatGPT",
         "parent": "T-536", "depends": ["T-536-A"], "goal": "live telemetry", "done_criteria": "telemetry regression",
         "queue_position": None, "depth": 1, "children_done": 0, "children_total": 0, "children": []},
        {"id": "T-536-C", "title": "Hierarchy", "state": "blocked", "source": "ChatGPT", "planner": "ChatGPT", "parent": "T-536",
         "depends": ["T-536-A"], "goal": "tree", "done_criteria": "parser regression", "queue_position": None, "depth": 1,
         "children_done": 0, "children_total": 0, "children": []},
        {"id": "T-536-D", "title": "UI", "state": "queued", "source": "ChatGPT", "planner": "ChatGPT", "parent": "T-536",
         "depends": ["T-536-B", "T-536-C"], "goal": "page", "done_criteria": "fixtures render", "queue_position": 2, "depth": 1,
         "children_done": 0, "children_total": 0, "children": []},
    ]},
    {"id": "T-520", "title": "Publish approval", "state": "human", "source": "roadmap", "planner": "", "parent": "", "depends": [],
     "goal": "", "done_criteria": "", "queue_position": None, "depth": 0, "children_done": 0, "children_total": 0, "children": []},
]
COUNTS = {"done": 2, "running": 1, "queued": 2, "blocked": 1, "human": 1, "total": 7, "safe_remaining": 4}
QUEUE = [{"id": "T-536-D", "unmet_dependencies": ["T-536-B", "T-536-C"]}]
RESULTS = [{"task_id": "T-536-C", "result": "blocked", "commit": "", "summary": "parser needs owner input", "need": "owner decision"}]
TELEMETRY = {"available": True, "stage": "running", "elapsed_seconds": 522.4, "head_sha": "21bacb1abc", "branch": "autopilot-phone",
             "cpu_percent": 12.5, "cpu_source": "proc_stat", "memory_mb": 1234.4, "memory_total_mb": 3800.0, "queue_depth": 4,
             "memory_source": "proc_meminfo", "worker_uptime_seconds": 900}
SECRET = "sk-fixture-SECRET-must-not-render"
SHA = "5fb2d3cc8823d2330bdb113eec415c5a8670c94f"
T0 = 1792850400.0  # 2026-10-24 14:00 UTC


def ev(kind, status, at=None, source=None, **extra):
    return {"kind": kind, "status": status, "at": at, "source": source, **extra}


TIMELINES = {
    "T-500": {"task_id": "T-500", "phase": "roadmap", "attempts": 0, "events": [ev("queued", "observed", source="roadmap", roadmap_line=12)]
              + [ev(k, "unavailable") for k in ("picked", "running", "checks", "commit", "push")]
              + [ev("outcome", "observed", source="roadmap", result="done")]},
    "T-536-A": {"task_id": "T-536-A", "phase": "result", "attempts": 2, "events": [
        ev("queued", "observed", source="roadmap", roadmap_line=104),
        ev("picked", "observed", T0, "worker_result"),
        ev("running", "observed", T0, "worker_result", duration_seconds=522.0, exit_code=0, timed_out=False),
        ev("checks", "observed", source="worker_result", items=[{"command": "python smoke_tests.py", "passed": None},
                                                               {"command": "python test_delegation_ui.py", "passed": None}]),
        ev("commit", "observed", source="worker_result", sha=SHA, url="https://github.com/example/factoryos/commit/" + SHA,
           commit_count=1, files=["app.py", "static/index.html"], file_count=2),
        ev("push", "unavailable"),
        ev("outcome", "observed", T0 + 540, "worker_result", result="done", summary="board <img src=x onerror=alert(2)>", need="", violations=[]),
    ]},
    "T-536-B": {"task_id": "T-536-B", "phase": "running", "attempts": 0, "events": [
        ev("queued", "observed", source="roadmap", roadmap_line=110),
        ev("picked", "observed", T0, "heartbeat"), ev("running", "observed", T0, "heartbeat", stage="running", elapsed_seconds=522.4)]
        + [ev(k, "pending") for k in ("checks", "commit", "push", "outcome")]},
    "T-536-C": {"task_id": "T-536-C", "phase": "result", "attempts": 1, "events": [
        ev("queued", "observed", source="roadmap", roadmap_line=117), ev("picked", "observed", None, "worker_result"),
        ev("running", "observed", None, "worker_result", duration_seconds=61.0, exit_code=1, timed_out=True),
        ev("checks", "skipped"), ev("commit", "skipped", sha="javascript:alert(3)", url="javascript:alert(3)"), ev("push", "skipped"),
        ev("outcome", "observed", T0, "worker_result", result="blocked", summary="parser needs owner input", need="owner decision",
           violations=["timed out"])]},
    "T-536-D": {"task_id": "T-536-D", "phase": "queued", "attempts": 0,
                "events": [ev("queued", "observed", source="roadmap", roadmap_line=124)] + [ev(k, "pending") for k in
                           ("picked", "running", "checks", "commit", "push", "outcome")]},
}


def board(connection, age, telemetry, active="T-536-B"):
    return {
        "tree": NOW_TREE, "planner_queue": QUEUE, "counts": COUNTS, "recent_results": RESULTS, "timelines": TIMELINES,
        "next_task": {"id": "T-536-D", "title": "UI"},
        "active_task": {"id": active, "title": "Telemetry"} if active else None,
        "worker": {"connection": connection, "online": connection == "online", "heartbeat_age_seconds": age,
                   "active_task_id": active, "last_error": "", "token": SECRET, "telemetry": telemetry,
                   "node": {"branch": "autopilot-phone", "subscription": "Claude Pro", "auth_mode": "subscription",
                            "hostname": "phone", "platform": "android", "worker_token": SECRET}},
    }


FIXTURES = {
    "online": board("online", 7, TELEMETRY),
    "stale": board("stale", 4000, {**TELEMETRY, "cpu_percent": None, "cpu_source": "unsupported", "memory_mb": None,
                                   "memory_total_mb": None, "memory_source": "unsupported"}),
    "offline": board("offline", None, None, active=None),
}

HARNESS = r"""
let LANG='en';
%(helpers)s
%(i18n)s
%(tr)s
%(block)s
const fixtures=%(fixtures)s,out={};
for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fixtures)){out[lang+':'+k]=renderDelegationCenter(fixtures[k],{});out[lang+':'+k+':all']=renderDelegationCenter(fixtures[k],{showDone:true,open:{'T-536':false}});for(const id of ['T-500','T-536-A','T-536-C','T-536-D','T-404'])out[lang+':'+k+':tl:'+id]=renderDelegationCenter(fixtures[k],{showDone:true,selected:id})}}
process.stdout.write(JSON.stringify(out));
"""


def render_checks(out):
    for key, html in out.items():
        require(not re.search(r"\bdc\.[a-z]+(\.[a-z]+)*\b", re.sub(r'class="[^"]*"', "", html)), f"untranslated key leaked in {key}")
        require(SECRET not in html, f"secret value rendered in {key}")
        require("<script>alert" not in html and "&lt;script&gt;alert(1)" in html, f"task title not escaped in {key}")
        planner, worker = html.find('data-column="planner"'), html.find('data-column="worker"')
        require(0 < planner < worker and 'class="dcGrid"' in html, f"planner column must precede worker column in {key}")
        require(html.index("data-mini") < html.index('class="dcGrid"'), f"mini-status must precede the columns in {key}")
    online, stale, offline = out["en:online"], out["en:stale"], out["en:offline"]
    for state in ("done", "running", "queued", "blocked", "human"):
        require(f'data-state="{state}"' in online, f"{state} task card missing")
    require('data-connection="online"' in online and ">Online<" in online, "online worker state missing")
    require('data-connection="stale"' in stale and "last known" in stale, "stale worker state missing")
    require('data-connection="offline"' in offline and "No heartbeat received yet." in offline and "No active task" in offline,
            "offline worker state missing")
    require("autopilot-phone@21bacb1" in online, "branch@head missing")
    require("08:42" in online and ">running<" in online, "stage/elapsed missing")
    require("12.5%" in online and "1234 / 3800 MB" in online, "CPU/memory missing when known")
    require("12.5%" not in stale and stale.count('class="dcNa"') >= 2, "unknown CPU/memory must render as unavailable")
    require("7s ago" in online and "1h ago" in stale, "heartbeat age missing")
    mini = online[online.index("data-mini"):online.index('class="dcSummary"')]
    require(all(x in mini for x in ("Online", "T-536-B", "running", "08:42", "12.5% CPU")), f"mini-status incomplete: {mini}")
    for name, value in (("done", 2), ("running", 1), ("queued", 2), ("blocked", 1), ("safe_remaining", 4), ("human_remaining", 1)):
        require(f'data-count="{name}"><b>{value}</b>' in online, f"{name} count missing")
    require("waiting for T-536-B, T-536-C" in online, "unmet dependencies missing")
    require('data-task="T-500"' not in online and "Show 1 completed" in online, "completed roots must collapse behind a toggle")
    require('data-task="T-500"' in out["en:online:all"] and "Hide completed" in out["en:online:all"], "show-completed toggle broken")
    require('data-group="T-536" open' in online and 'data-group="T-536" ontoggle' in out["en:online:all"], "group expand/collapse state ignored")
    require("Owner input needed: owner decision" in online, "blocked result need missing")
    require("Онлайн" in out["uk:online"] and "Офлайн" in out["ru:offline"], "localized connection labels missing")
    timeline_checks(out)


def events(html):
    block = html[html.index("data-timeline="):]
    return re.findall(r'data-event="([a-z]+)" data-status="([a-z]+)"', block)


def timeline_checks(out):
    online, offline = out["en:online"], out["en:offline"]
    require('data-timeline="T-536-B"' in online and "dcTimeline sheet" not in online, "active task timeline must show inline by default")
    require(events(online) == [("queued", "observed"), ("picked", "observed"), ("running", "observed"), ("checks", "pending"),
                               ("commit", "pending"), ("push", "pending"), ("outcome", "pending")], f"running timeline events: {events(online)}")
    require("2026-10-24 14:00 UTC" in online and "08:42" in online, "running timeline timestamp/elapsed missing")
    require('data-timeline="T-536-C"' in offline, "without an active task the last result's timeline is shown")
    for task in ("T-500", "T-536-A", "T-536-B", "T-536-C", "T-536-D"):
        require(f'data-open-timeline="{task}"' in out["en:online:all"], f"timeline button missing for {task}")
    require('data-open-timeline="T-520"' not in out["en:online:all"], "HUMAN tasks have no delegation timeline")
    done = out["en:online:tl:T-536-A"]
    require('data-timeline="T-536-A"' in done and "dcTimeline sheet" in done, "selected timeline must open as a sheet")
    require(events(done) == [("queued", "observed"), ("picked", "observed"), ("running", "observed"), ("checks", "observed"),
                             ("commit", "observed"), ("push", "unavailable"), ("done", "observed")], f"done timeline events: {events(done)}")
    require(f'href="https://github.com/example/factoryos/commit/{SHA}"' in done and f'data-commit="{SHA}"' in done and ">5fb2d3cc<" in done,
            "exact commit evidence link missing")
    require("$ python smoke_tests.py" in done and "$ python test_delegation_ui.py" in done and "per-command pass/fail not reported" in done,
            "reported check commands missing")
    require("2 files changed" in done and "<code>static/index.html</code>" in done and "2 attempts" in done, "changed files/attempts missing")
    require("ROADMAP line 104" in done and "time unavailable" in done and "Duration: 08:42" in done and "exit 0" in done, "event details missing")
    require("2026-10-24 14:09 UTC" in done, "outcome timestamp missing")
    require("<img src=x" not in done and "&lt;img src=x" in done, "timeline summary must be escaped")
    blocked = out["en:online:tl:T-536-C"]
    require(events(blocked)[-1] == ("blocked", "observed") and ("commit", "skipped") in events(blocked), f"blocked timeline: {events(blocked)}")
    require('href="javascript' not in blocked and "timed out" in blocked and "Owner input needed: owner decision" in blocked, "blocked timeline details")
    legacy = out["en:online:tl:T-500"]
    require([s for _, s in events(legacy)] == ["observed"] + ["unavailable"] * 5 + ["observed"] and legacy.count(">unavailable<") >= 5,
            "missing events must render as unavailable")
    require([s for _, s in events(out["en:online:tl:T-536-D"])] == ["observed"] + ["pending"] * 6, "queued timeline must show pending steps")
    require('data-timeline="T-536-B"' in out["en:online:tl:T-404"] and "dcTimeline sheet" not in out["en:online:tl:T-404"],
            "unknown selection falls back to the active task")
    require("Хронологія виконання" in out["uk:online:tl:T-536-A"] and "Хронология выполнения" in out["ru:online:tl:T-536-A"],
            "localized timeline labels missing")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, block, i18n, helpers, tr = extract(html)
    keys = static_checks(html, script, block)
    print(f"Delegation Control Center static checks passed ({len(keys)} localized keys)")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the fixture rendering check")
        print("SKIPPED fixture rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    program = HARNESS % {"helpers": helpers, "i18n": i18n, "tr": tr, "block": block, "fixtures": json.dumps(FIXTURES)}
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"renderer harness failed:\n{result.stderr[-2000:]}")
    render_checks(json.loads(result.stdout))
    print("Delegation Control Center fixture rendering passed (desktop/mobile, online/stale/offline, timeline, EN/UK/RU)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
