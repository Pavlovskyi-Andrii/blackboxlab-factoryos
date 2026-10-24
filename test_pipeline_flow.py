"""T-532 Live pipeline + handoff trace regression.

Static checks always run. The fixture rendering check runs the real inline renderer from
static/index.html under Node against a deterministic workflow: source artifact -> worker run ->
output -> downstream worker edges with running/done/blocked/failed states, plus the stacked
mobile fallback. Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it the check is
reported as SKIPPED, never as passed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- pipeline-flow:begin"
END = "// --- pipeline-flow:end"


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
    require(re.search(r"\.pfHop\{display:grid;grid-template-columns:22px minmax\(0,1\.1fr\) 16px", css), "desktop hop row missing")
    mobile = re.search(r"@media\(max-width:820px\)\{[^\n]*\.pfHop\{grid-template-columns:1fr[^\n]*", css)
    require(mobile is not None and ".pfArrow{padding-top:0;text-align:left;line-height:1;transform:rotate(90deg)" in mobile.group(0),
            "stacked mobile fallback missing")
    require(".pfHop.running{" in css and "prefers-reduced-motion:reduce){.pfHop.running" in css, "live movement / reduced-motion styles missing")
    require('id="pipelineFlow"' in html and html.index('id="pipeline"') < html.index('id="pipelineFlow"'), "flow container must sit under the pipeline cards")
    require("renderPipelineFlow(S.selectedJobFlow)" in script, "pipeline() must render the selected job flow")
    require("innerHTML" not in block and "document." not in block and "fetch(" not in block, "renderer must stay pure (no DOM/network)")
    require(not re.search(r"token|api_key|password|secret|content", block, re.I), "renderer must not read secret fields or artifact content")
    keys = set(re.findall(r"tr\('(pflow\.[a-zA-Z.]*[a-zA-Z])'", block)) | set(re.findall(r"pfNone\('(pflow\.[a-zA-Z.]+)'\)", block))
    keys |= set(re.findall(r"'(pflow\.[a-zA-Z]+)'", block))
    keys |= {f"pflow.state.{s}" for s in ("running", "done", "blocked", "failed", "queued", "unknown")}
    keys |= {f"pflow.origin.{s}" for s in ("source", "earlier")}
    for key in sorted(keys):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist in EN/UK/RU")
    return keys


R = {n: f"run-{n}" for n in ("research", "script", "visual", "voice", "render")}
A = {"seed": "art-seed", "research": "art-research", "script": "art-script"}


def hop(order, run, agent, stage, state, inputs, outputs=(), downstream=(), error=""):
    return {"order": order, "run_id": run, "agent": agent, "stage": stage, "status": state, "state": state,
            "started_at": "2026-10-24T14:00:00+00:00", "finished_at": None if state == "running" else "2026-10-24T14:01:00+00:00",
            "error": error, "inputs": list(inputs), "outputs": list(outputs), "downstream": list(downstream)}


def inp(artifact, title, agent, source_run, origin):
    return {"artifact_id": artifact, "title": title, "kind": "text", "source_agent": agent, "source_run_id": source_run, "origin": origin}


def down(run, agent, state, artifact):
    return {"run_id": run, "agent": agent, "state": state, "artifact_id": artifact}


HOPS = [
    hop(1, R["research"], "Researcher", "research", "done", [inp(A["seed"], "Opportunity brief", "Scout", None, "source")],
        [{"artifact_id": A["research"], "title": "Research pack", "kind": "research"}],
        [down(R["script"], "Scriptwriter", "done", A["research"])]),
    hop(2, R["script"], "Scriptwriter", "script", "done", [inp(A["research"], "Research pack", "Researcher", R["research"], "run")],
        [{"artifact_id": A["script"], "title": "Draft <script>alert(1)</script>", "kind": "text"}],
        [down(R["visual"], "Visual Director", "running", A["script"]), down(R["voice"], "Voice Agent", "failed", A["script"]),
         down(R["render"], "Render Agent", "blocked", A["script"]), down(R["render"], "Render Agent", "blocked", A["script"])]),
    hop(3, R["visual"], "Visual Director", "visual", "running", [inp(A["script"], "Draft script", "Scriptwriter", R["script"], "run")]),
    hop(4, R["voice"], "Voice Agent", "voice", "failed", [inp(A["script"], "Draft script", "Scriptwriter", R["script"], "run")],
        error="Timed out <img src=x onerror=alert(2)>"),
    hop(5, R["render"], "Render Agent", "made_up_stage", "blocked",
        [inp(A["script"], "Draft script", "Scriptwriter", R["script"], "run"), inp("bad'id);alert(3)//", "Forged ref", "Scout", None, "source")],
        error="Missing required upstream artifacts: Voice Agent"),
]
COUNTS = {"running": 1, "done": 2, "blocked": 1, "failed": 1, "queued": 0, "unknown": 0}
FIXTURES = {
    "live": {"job_id": "job", "hops": HOPS, "edges": [], "sources": [], "counts": COUNTS, "live": True, "truncated": False},
    "idle": {"job_id": "job", "hops": HOPS[:2], "edges": [], "sources": [], "counts": {**COUNTS, "running": 0, "failed": 0, "blocked": 0},
             "live": False, "truncated": True},
    "empty": {"job_id": "job", "hops": [], "edges": [], "sources": [], "counts": COUNTS, "live": False, "truncated": False},
    "missing": None,
}

HARNESS = r"""
let LANG='en';
%(helpers)s
%(i18n)s
%(tr)s
%(block)s
const fixtures=%(fixtures)s,out={};
for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fixtures))out[lang+':'+k]=renderPipelineFlow(fixtures[k])}
process.stdout.write(JSON.stringify(out));
"""


def hop_html(html, order):
    start = html.index(f'data-hop="{order}"')
    end = html.find("</li>", start)
    return html[start:end]


def render_checks(out):
    for key, html in out.items():
        require(not re.search(r"\bpflow\.[a-z]+(\.[a-z]+)*\b", html), f"untranslated key leaked in {key}")
        require("<script>alert" not in html and "<img src=x" not in html, f"untrusted text not escaped in {key}")
        require("alert(3)" not in html, f"forged artifact id must never reach markup in {key}")
    live = out["en:live"]
    require(re.findall(r'data-hop="(\d+)" data-state="([a-z]+)"', live) ==
            [("1", "done"), ("2", "done"), ("3", "running"), ("4", "failed"), ("5", "blocked")], "hops must render in run order with states")
    for order in range(1, 6):
        h = hop_html(live, order)
        positions = [h.index(c) for c in ('class="pfCol pfIn"', 'class="pfRun"', 'class="pfCol pfOut"', 'class="pfCol pfDown"')]
        require(positions == sorted(positions) and h.count('class="pfArrow"') == 3, f"hop {order} must read input -> run -> output -> downstream")
    first = hop_html(live, 1)
    require("Opportunity brief" in first and "source artifact" in first and 'class="pfArt source"' in first, "seed must render as a source artifact")
    require(f'data-trace-run="{R["research"]}" data-trace-artifact="{A["seed"]}"' in first, "input edge must open the exact handoff trace")
    require("Research pack" in first and f'data-trace-run="{R["script"]}" data-trace-artifact="{A["research"]}"' in first, "output -> downstream edge missing")
    second = hop_html(live, 2)
    downstream = re.findall(r'class="pfDownItem ([a-z]+)" data-trace-run="([^"]+)"', second)
    require(downstream == [("running", R["visual"]), ("failed", R["voice"]), ("blocked", R["render"])], f"fan-out downstream edges: {downstream}")
    require("&lt;script&gt;alert(1)" in second, "output title must be escaped")
    running = hop_html(live, 3)
    require('class="pfPacket"' in running and "Producing…" in running and "No downstream worker yet" in running, "running hop must show movement, not invented output")
    require(live.count('class="pfPacket"') == 1, "only running hops animate")
    require('data-live="on"' in live and "Moving now: Visual Director" in live, "live movement header missing")
    for state, n in (("running", 1), ("done", 2), ("blocked", 1), ("failed", 1)):
        require(f'data-count="{state}">{n} {state}<' in live, f"{state} count missing")
    failed = hop_html(live, 4)
    require('class="pfBadge failed"' in failed and "Timed out &lt;img" in failed, "failed hop error missing")
    blocked = hop_html(live, 5)
    require('class="pfBadge blocked"' in blocked and "Missing required upstream artifacts" in blocked and "made_up_stage" in blocked,
            "blocked hop / unknown stage fallback missing")
    require("Forged ref" in blocked and blocked.count("data-trace-artifact") == 1 and '<span class="pfArt source">' in blocked,
            "invalid ids must render as plain text, not as a trace button")
    require('data-live="off"' in out["en:idle"] and "No worker is running for this job" in out["en:idle"] and "Showing the latest 2 runs" in out["en:idle"],
            "idle / truncated header missing")
    require('class="pfList"' not in out["en:empty"] and "No worker runs for this job yet" in out["en:empty"] and out["en:missing"] == out["en:empty"],
            "empty flow must render an explicit empty state")
    require("Зараз працює: Visual Director" in out["uk:live"] and "заблоковано" in out["uk:live"], "UK labels missing")
    require("Сейчас работает: Visual Director" in out["ru:live"] and "ошибка" in out["ru:live"], "RU labels missing")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, block, i18n, helpers, tr = extract(html)
    keys = static_checks(html, script, block)
    print(f"Pipeline flow static checks passed ({len(keys)} localized keys)")
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
    print("Pipeline flow fixture rendering passed (ordered handoff trace, running/done/blocked/failed, mobile fallback, EN/UK/RU)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
