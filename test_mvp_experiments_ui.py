"""T-609 A/B Tester S2: experiment branch lanes in the MVP panel (acceptance plan §6.3 of the S0 review).

Static checks always run: the renderers are pure, every mvpx.* key exists in EN/UK/RU, the only network calls go to
/api/mvp-factory S1 routes, every button is bound to an S1 handler, and the lane CSS stacks A above B without fixed
widths. The fixture check builds real experiments through the S1 `Experiments` API on a temp registry and renders
them with the real inline renderers under Node for owner, member and viewer in EN/UK/RU: lane A precedes lane B in
DOM order (also when the input order is reversed), the mode badge matches mvpx.mode.*, the compare card never carries
a winner, publish/spend/outreach are shown as unavailable and user text is escaped. Node is required when
FACTORYOS_REQUIRE_NODE=1 (CI); without it the check is reported as SKIPPED, never as passed.

The 375 px / 1440 px layout check needs a real browser. None is used here, so it is reported as NOT VERIFIED.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from mvp_experiments import Experiments
from mvp_factory import MvpRegistry

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- mvp-experiments:begin"
END = "// --- mvp-experiments:end"
PID = "mycast"
HOSTILE = "<img src=x onerror=alert(1)>"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    tail = script.split(END, 1)[1].split("// --- mvp-builder:end", 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    assigns = "\n".join(l for l in script.split("\n") if l.startswith("Object.assign(I18N."))
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    when = re.search(r"^function mvpWhen\(at\)\{.*\}$", script, re.M).group(0)
    return script, block, tail, i18n + "\n" + assigns, helpers, tr, when


def static_checks(html, script, block, tail):
    require("fetch(" not in block and "document." not in block and "innerHTML" not in block, "renderers must stay pure")
    # Network: the S2 code talks only to the S1 experiment routes.
    urls = re.findall(r"fetch\('([^']*)'", tail) + re.findall(r"'(/api/[^']*)'", tail)
    require(urls and all(u.startswith("/api/mvp-factory/") for u in urls), f"S2 must only call /api/mvp-factory: {urls}")
    for route in ("'/draft'", "'/approve-preview'", "'/decision'", "'/experiments'"):
        require(route in tail, f"S2 handler for S1 route {route} missing")
    require(not re.search(r"publish|spend|outreach|/jobs|/approve'", tail), "S2 handlers must not reach publish/spend/outreach/job routes")
    # Buttons: each one is bound to an S1 handler; nothing else is clickable.
    handlers = re.findall(r'<button[^>]*?onclick="([a-zA-Z]+)\(', block)
    require(sorted(set(handlers)) == ["mvpxApprove", "mvpxDecide", "mvpxSave"], f"unexpected button handlers: {handlers}")
    require(block.count("<button") == 3, "exactly three buttons: save draft, approve preview, record decision")
    for fn in ("mvpxSave", "mvpxApprove", "mvpxDecide"):
        require(f"async function {fn}(" in tail, f"handler {fn} missing")
    require("if(!pid||!mvpOwner())return" in tail.split("async function mvpxApprove(", 1)[1].split("\n}", 1)[0], "approve is owner-only")
    require("if(!pid||!mvpOwner())return" in tail.split("async function mvpxDecide(", 1)[1].split("\n}", 1)[0], "decision is owner-only")
    require("winner" not in block, "the renderer must not read or print a winner field")
    # Wiring into the existing MVP panel.
    require("+mvpPipelineHtml(c)+mvpxPanelHtml()" in script, "experiment section must render inside the MVP panel")
    require("loadMvpCycle(id);loadMvpExperiments(id)" in script, "opening a project must load its experiments")
    require("mvpxSaveKeep(panel);" in script and "mvpxRestoreKeep(panel);" in script, "typed drafts must survive re-render")
    # Layout CSS: lanes stack vertically, full width, chips wrap, nothing fixed-width.
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(".mvpxLanes{display:flex;flex-direction:column" in css, "lanes must stack vertically (A on top, B below)")
    require(re.search(r"\.mvpxLane\{[^}]*min-width:0;width:100%;box-sizing:border-box", css), "lanes must be full width")
    require(re.search(r"\.mvpxStages\{[^}]*display:flex;flex-wrap:wrap", css), "stage chips flow left to right and wrap")
    mvpx_css = " ".join(re.findall(r"\.mvpx[^{]*\{[^}]*\}", css))
    require(not re.search(r"(?<![-\w])(width|min-width):\s*[1-9]\d*px", mvpx_css), "no fixed pixel widths in experiment CSS")
    require("white-space:nowrap" not in mvpx_css, "no nowrap text in experiment CSS")
    # i18n: every key the S2 code uses exists in EN/UK/RU.
    code = block + tail
    keys = set(re.findall(r"tr\('(mvpx\.[A-Za-z_.]*[A-Za-z_])'", code))
    keys |= {f"mvpx.mode.{m}" for m in ("segment", "controlled")} | {f"mvpx.modeNote.{m}" for m in ("segment", "controlled")}
    keys |= {f"mvpx.compare.{m}" for m in ("segment", "controlled", "segmentNote", "controlledNote")}
    keys |= {f"mvpx.stage.{s}" for s in ("concept", "landing", "content", "channels", "metrics")}
    keys |= {f"mvpx.chip.{s}" for s in ("done", "empty", "placeholder", "notInstrumented")}
    keys |= {f"mvpx.state.{s}" for s in ("draft", "closed")} | {f"mvpx.posts.{k}" for k in ("short", "medium")}
    keys |= {f"mvpx.f.{k}" for k in ("headline", "subhead", "cta", "bullets", "short", "medium")}
    keys |= {f"mvpx.choice.{c}" for c in ("continue_a", "continue_b", "both", "iterate", "pivot", "stop")}
    keys |= {f"mvpx.err.{c}" for c in ("copy_health_claim", "copy_personal_data", "text_too_long", "stale_revision", "experiment_closed")}
    for key in sorted(keys):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist exactly once in EN/UK/RU")
    require("for(const k of ['mvpx.err.'+code," in script, "S1 error codes must map to mvpx.err.* text")
    return keys


def fixtures():
    """Real S1 experiments on a temp registry: fresh, drafted (A approved, B pending), controlled, closed, hostile."""
    tmp = tempfile.mkdtemp(prefix="factoryos-mvpx-ui-")
    reg = MvpRegistry(Path(tmp) / "mvp_factory.json")
    reg.snapshot()
    ex = Experiments(reg)

    def make(exp_id, mode="SEGMENT_COMPARISON", labels=("Business focus", "Personal goals")):
        ex.create(PID, {"id": exp_id, "mode": mode, "concept_id": "mc-focus-001",
                        "hypothesis": "Founders and personal-goal listeners respond to different positioning.",
                        "branches": [{"id": "a", "label": labels[0], "persona": "entrepreneurs"},
                                     {"id": "b", "label": labels[1], "persona": "personal_goals"}]}, actor_role="owner")

    copy_a = {"headline": "Start the day focused on your business", "subhead": "One short daily audio briefing.",
              "cta": "Listen to a sample", "bullets": ["Your sources", "Your schedule"],
              "posts": {"short": ["Morning focus in 7 minutes.", "Your briefing, your sources."], "medium": ["A longer draft."]}}
    copy_b = {"headline": "Start the day focused on your goal", "subhead": "Carefully sourced ideas on a theme you pick.",
              "cta": "Listen to a sample", "posts": {"short": ["One small prompt a day."]}}
    make("mc-exp-fresh")
    make("mc-exp-focus-001")
    ex.save_draft(PID, "mc-exp-focus-001", "a", copy_a, actor_role="owner")
    ex.save_draft(PID, "mc-exp-focus-001", "b", copy_b, actor_role="member")
    ex.approve_preview(PID, "mc-exp-focus-001", "a", 1, actor_role="owner")
    make("mc-exp-controlled", mode="CONTROLLED_AB")
    make("mc-exp-closed")
    ex.save_draft(PID, "mc-exp-closed", "a", copy_a, actor_role="owner")
    ex.decide(PID, "mc-exp-closed", {"choice": "iterate", "note": "Rewrite B first."}, actor_role="owner")
    make("mc-exp-hostile", labels=(HOSTILE, "<script>x</script>"))
    ex.save_draft(PID, "mc-exp-hostile", "a", dict(copy_a, headline=HOSTILE), actor_role="owner")
    listed = {e["id"]: e for e in ex.r._load()["projects"][PID]["experiments"].values()}
    from mvp_experiments import view
    out = {k: view(v) for k, v in listed.items()}
    reversed_exp = json.loads(json.dumps(out["mc-exp-focus-001"]))
    reversed_exp["branches"].reverse()
    out["reversed"] = reversed_exp
    return out


HARNESS = r"""
let LANG='en';
%(helpers)s
%(i18n)s
%(tr)s
%(when)s
%(block)s
const fx=%(fixtures)s,roles={owner:{owner:true,ro:false},member:{owner:false,ro:false},viewer:{owner:false,ro:true}},out={};
for(const lang of ['en','uk','ru']){LANG=lang;
 out[lang]={badge:{segment:tr('mvpx.mode.segment'),controlled:tr('mvpx.mode.controlled')},compare:tr('mvpx.compare.segment'),locked:tr('mvpx.locked'),metrics:tr('mvpx.metrics'),r:{}};
 for(const role of Object.keys(roles))for(const k of Object.keys(fx))out[lang].r[role+':'+k]=mvpxExperimentHtml(fx[k],roles[role]);
 out[lang].section=mvpxSectionHtml({experiments:[fx['mc-exp-focus-001']]},{owner:true,line:{text:'<b>x</b>',err:true}});
 out[lang].empty=mvpxSectionHtml({experiments:[]},{owner:true});
 out[lang].loading=mvpxSectionHtml(null,{});
 out[lang].failed=mvpxSectionHtml(null,{err:true});
}
process.stdout.write(JSON.stringify(out));
"""


def pos(html, needle, what):
    i = html.find(needle)
    require(i >= 0, f"{what} missing")
    return i


def render_checks(out):
    for lang in ("en", "uk", "ru"):
        o = out[lang]
        for key, h in o["r"].items():
            visible = re.sub(r'\s(class|id|for|data-[a-z-]+|aria-[a-z]+)="[^"]*"', "", h)
            require(not re.search(r"\bmvpx\.[a-zA-Z]", visible), f"{lang} {key}: untranslated key")
            require(not re.search(r"\{\w+\}", visible), f"{lang} {key}: unresolved placeholder")
            # A above B in DOM order, then compare; header first (keyboard order header → A → B → compare).
            a, b = pos(h, 'data-branch="a"', f"{key} lane A"), pos(h, 'data-branch="b"', f"{key} lane B")
            head, cmp = pos(h, "data-mode-badge=", f"{key} mode badge"), pos(h, 'class="mvpxCompare"', f"{key} compare")
            require(head < a < b < cmp, f"{lang} {key}: order must be header → A → B → compare")
            require(h.count('class="mvpxLane"') == 2, f"{key}: exactly two lanes")
            require(not re.search(r"winner\"|data-winner|lift|significance", h), f"{key}: compare must carry no winner/lift")
            require(h.count(o["locked"]) == 2 and h.count(o["metrics"]) == 2, f"{lang} {key}: each lane says metrics not instrumented and publish/spend/outreach unavailable")
            require("<img" not in h and "<script>" not in h, f"{lang} {key}: user text must be escaped")
            if key.startswith("viewer:"):
                require(not re.search(r"<(button|input|textarea|select)\b", h), f"{lang} {key}: viewers get no controls")
            if key.startswith("member:"):
                require("mvpxApprove(" not in h and "mvpxDecide(" not in h, f"{lang} {key}: member cannot approve or decide")
        seg, ctl = o["r"]["owner:mc-exp-focus-001"], o["r"]["owner:mc-exp-controlled"]
        require(f'data-mode-badge="segment">{o["badge"]["segment"]}<' in seg, f"{lang}: segment badge must match mvpx.mode.segment")
        require(f'data-mode-badge="controlled">{o["badge"]["controlled"]}<' in ctl, f"{lang}: controlled badge must match mvpx.mode.controlled")
        require(f'<b>{o["compare"]}</b>' in seg and 'data-compare="segment"' in seg, f"{lang}: segment compare card must say no winner")
        require(o["r"]["owner:reversed"].replace("\n", "") == seg.replace("\n", ""), f"{lang}: A renders above B even if data order is reversed")
        require("&lt;b&gt;x&lt;/b&gt;" in o["section"] and 'data-panel="mvp-experiments"' in o["section"], f"{lang}: status line escaped")
        for k in ("empty", "loading", "failed"):
            require('data-panel="mvp-experiments"' in o[k] and "mvpx." not in o[k].replace('class="mvpx', ""), f"{lang}: {k} state")

    en = out["en"]["r"]
    seg = en["owner:mc-exp-focus-001"]
    lane_a = seg[seg.index('data-branch="a"'):seg.index('data-branch="b"')]
    lane_b = seg[seg.index('data-branch="b"'):seg.index('class="mvpxCompare"')]
    require("Preview approved · revision 1" in lane_a and "mvpxApprove(" not in lane_a, "A r1 approved: no approve button")
    require("Revision 1 waits for preview approval" in lane_b and 'data-rev="1"' in lane_b and "mvpxApprove(" in lane_b,
            "B r1 pending: owner sees approve r1")
    require("Branch A · Business focus" in lane_a and "Branch B · Personal goals" in lane_b, "lane titles")
    require("Start the day focused on your business" in lane_a and "Start the day focused on your goal" in lane_b, "per-branch copy")
    require('data-stage="landing">Landing draft <small>ready' in lane_b and 'data-stage="metrics">Metrics <small>not instrumented' in lane_b,
            "stage chips Concept → Landing → Content → Channels → Metrics")
    require(lane_a.index('data-stage="concept"') < lane_a.index('data-stage="landing"') < lane_a.index('data-stage="content"')
            < lane_a.index('data-stage="channels"') < lane_a.index('data-stage="metrics"'), "stage chips order")
    require("Facebook: placeholder, no connector. Nothing is sent." in lane_a and "TikTok: placeholder" in lane_a, "channel placeholders")
    require("not a randomized A/B test" in seg and "Segment comparison: no winner" in seg, "segment header + compare text")
    require("mvpxDecide(" in seg and "Record decision" in seg, "owner can record a decision")
    fresh = en["owner:mc-exp-fresh"]
    require(fresh.count("No draft yet") == 2 and "mvpxApprove(" not in fresh and fresh.count("mvpxSave(") == 2, "fresh: two empty lanes")
    closed = en["owner:mc-exp-closed"]
    require("<button" not in closed and "Decision: Iterate" in closed and "Rewrite B first." in closed, "closed: decision shown, no buttons")
    require("No winner" in en["owner:mc-exp-controlled"] or "no winner" in en["owner:mc-exp-controlled"], "controlled compare text")
    require("&lt;img src=x onerror=alert(1)&gt;" in en["owner:mc-exp-hostile"], "hostile label/copy rendered as text")
    member = en["member:mc-exp-focus-001"]
    require("mvpxSave(" in member and "Only the owner approves previews" in member, "member can draft, owner-only note shown")
    require("Порівняння сегментів: переможця немає" in out["uk"]["r"]["owner:mc-exp-focus-001"], "UK compare text")
    require("Сравнение сегментов: победителя нет" in out["ru"]["r"]["owner:mc-exp-focus-001"], "RU compare text")
    require("Гілка A" in out["uk"]["r"]["owner:mc-exp-focus-001"] and "Ветка B" in out["ru"]["r"]["owner:mc-exp-focus-001"], "UK/RU lane titles")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, block, tail, i18n, helpers, tr, when = extract(html)
    keys = static_checks(html, script, block, tail)
    print(f"A/B Tester S2 UI static checks passed ({len(keys)} localized mvpx.* keys)")
    fx = fixtures()
    require(fx["mc-exp-focus-001"]["comparison"]["winner"] is None, "S1 must never return a winner")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the fixture rendering check")
        print("SKIPPED fixture rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
    else:
        program = HARNESS % {"helpers": helpers, "i18n": i18n, "tr": tr, "when": when, "block": block,
                             "fixtures": json.dumps(fx)}
        result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
        if result.returncode:
            raise SystemExit(f"renderer harness failed:\n{result.stderr[-2000:]}")
        render_checks(json.loads(result.stdout))
        print("A/B Tester S2 UI fixture rendering passed (A above B, mode badge, no winner, owner/member/viewer, EN/UK/RU)")
    print("NOT VERIFIED: 375 px / 1440 px layout in a real browser (no browser in this run)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
