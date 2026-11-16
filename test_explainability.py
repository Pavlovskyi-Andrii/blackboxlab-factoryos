"""T-533 Explainability + tooltips regression.

Static checks always run: every canonical concept (Hook, Script, Caption, Voice and the
Cycle/Idea/Job/Review/Learned stages) must have non-empty explain.* copy in EN, UK and RU, every
helpTip() call site must use a known concept, and the tooltip CSS/handlers must stay keyboard,
hover and tap safe. The fixture check runs the real inline helper under Node with a minimal fake
DOM. Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it the check is reported as
SKIPPED, never as passed.

T-597 extends the same helper to the Relay, worker, connector, stage, approval, video, Content Brain
and Discovery surfaces: each heading has exactly one tip, each surface tip carries a factual mini flow
and a "tutorial not yet supported" note in EN/UK/RU, and hovering or focusing one tip closes any other
open tip so bubbles never overlap.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- explain:begin"
END = "// --- explain:end"
CANONICAL = ["hook", "script", "caption", "voice", "cycle", "idea", "job", "review", "learned",
             "relay", "worker", "connector", "stage", "approval", "video", "brain", "discovery"]
# T-597 surface help: each concept carries a factual mini flow and a not-yet-supported tutorial note.
SURFACES = ["relay", "worker", "connector", "stage", "approval", "video", "brain", "discovery"]
# Static headings get a mounted tip (applyLanguage); JS-rendered headings call helpTip() directly.
MOUNTS = {"dc.title": "relay", "worker.title": "worker", "connections.title": "connector",
          "approval.title": "approval", "finisher.title": "video", "brain.title": "brain", "discovery.title": "discovery"}
# T-691: the pipeline heading now renders inside the expanded content row ("making of").
RENDERED = {"lb.title": "relay", "wo.title": "worker", "pipeline.title": "stage"}
LOCALES = ("en", "uk", "ru")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return script, block, i18n, helpers, tr


def locale_blocks(i18n):
    starts = [i18n.index(f"\n {lang}:{{") for lang in LOCALES] + [len(i18n)]
    return {lang: i18n[starts[n]:starts[n + 1]] for n, lang in enumerate(LOCALES)}


def explain_copy(block):
    return dict(re.findall(r'"(explain\.[a-zA-Z]+)":"((?:[^"\\]|\\.)*)"', block))


def flow_copy(block):
    return dict(re.findall(r'"explainFlow\.([a-zA-Z]+)":"((?:[^"\\]|\\.)*)"', block))


def surface_checks(html, script, block, i18n):
    flows = {lang: flow_copy(b) for lang, b in locale_blocks(i18n).items()}
    for lang in LOCALES:
        require(set(flows[lang]) == set(SURFACES), f"{lang} explainFlow.* must cover exactly {SURFACES}")
        for c in SURFACES:
            steps = flows[lang][c].split(" → ")
            require(len(steps) >= 3 and all(s.strip() for s in steps), f"{lang} {c} flow needs >=3 non-empty steps")
            require(len(steps) == len(flows["en"][c].split(" → ")), f"{lang} {c} flow step count differs from EN")
    tutorial = {lang: explain_copy(b).get("explain.tutorial", "") for lang, b in locale_blocks(i18n).items()}
    require(re.search(r"not yet supported", tutorial["en"], re.I), "EN tutorial placeholder must say not yet supported")
    require("не підтримується" in tutorial["uk"] and "не поддерживается" in tutorial["ru"], "UK/RU tutorial placeholder missing")
    # No metered generation and no media player behind the placeholder.
    require(not re.search(r"<(audio|video|iframe)\b", block) and "fetch(" not in block, "tutorial placeholder must not load or generate media")
    body = html.split("<body>", 1)[1]
    for term, concept in MOUNTS.items():
        m = re.search(r'data-i18n="' + re.escape(term) + r'">[^<]*</h([23])><span class="helpTipMount" data-help-tip="([a-z]+)" data-help-term="'
                      + re.escape(term) + r'"></span></div>', body)
        require(m is not None, f"{term} heading needs a mounted help tip beside it (outside the heading's native title)")
        require(m.group(2) == concept, f"{term} must explain {concept}, got {m.group(2)}")
        require(body.count(f'data-help-term="{term}"') == 1, f"{term} has more than one help tip")
    for term, concept in RENDERED.items():
        require(f"esc(tr('{term}'))+helpTip('{concept}',tr('{term}'))" in script, f"{term} renderer must show the {concept} help tip")
    require("document.querySelectorAll('[data-help-tip]').forEach(el=>{el.innerHTML=helpTip(el.dataset.helpTip," in script,
            "applyLanguage must (re)mount heading tips in the active language")
    require("addEventListener('mouseover'" in block and "addEventListener('focusin'" in block, "hover/focus must close other open tips")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(re.search(r"@media\(min-width:821px\)\{\.helpTipWrap\.helpTipWrap\.alignL", css), "edge alignment must not override the mobile sheet")
    require(not re.search(r"\n\.helpTipWrap\.helpTipWrap \.helpTipText\{max-width", css), "a later max-width rule would override the mobile sheet")
    return flows


def static_checks(html, script, block, i18n):
    concepts = re.search(r"const EXPLAIN_CONCEPTS=\[([^\]]*)\]", block)
    require(concepts is not None, "EXPLAIN_CONCEPTS missing")
    require(re.findall(r"'([a-z]+)'", concepts.group(1)) == CANONICAL, "EXPLAIN_CONCEPTS must list the canonical concepts")
    copies = {lang: explain_copy(b) for lang, b in locale_blocks(i18n).items()}
    required = {f"explain.{c}" for c in CANONICAL} | {"explain.aria"}
    for lang in LOCALES:
        missing = required - set(copies[lang])
        require(not missing, f"{lang} missing help keys: {sorted(missing)}")
        require(set(copies[lang]) == set(copies["en"]), f"{lang} explain.* keys out of parity with EN")
        for key in required:
            require(len(copies[lang][key].strip()) >= (8 if key == "explain.aria" else 40), f"{lang} {key} copy too short")
        require("{term}" in copies[lang]["explain.aria"], f"{lang} explain.aria must name the term")
    for lang in ("uk", "ru"):
        for key in required:
            require(copies[lang][key] != copies["en"][key], f"{lang} {key} is an untranslated EN fallback")
    calls = set(re.findall(r"helpTip\('([a-z]+)'", script)) | set(re.findall(r'data-help-tip="([a-z]+)"', html))
    require(calls <= set(CANONICAL), f"helpTip() uses unknown concepts: {sorted(calls - set(CANONICAL))}")
    require(calls == set(CANONICAL), f"concepts without a UI help entry: {sorted(set(CANONICAL) - calls)}")
    for anchor in ("cycle.statCycles", "cycle.statReview", "cycle.statLearned", "cycle.idea", "cycle.job", "cycle.learning",
                   "package.hook", "package.script", "package.voice", "package.srt", "approval.hook", "approval.script"):
        require(re.search(r"helpTip\('[a-z]+',tr\('" + re.escape(anchor) + r"'\)\)", script), f"help entry missing next to {anchor}")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(".helpTipWrap.helpTipWrap.open .helpTipText" in css, "tap/click open state missing")
    require(".helpTip:focus-visible+.helpTipText" in css and ".helpTip:focus-visible{outline" in css, "keyboard focus access missing")
    require(re.search(r"@media\(hover:hover\)\{\.helpTipWrap\.helpTipWrap:hover \.helpTipText\{display:block\}\}", css),
            "hover must be limited to hover-capable devices")
    mobile = re.search(r"@media\(max-width:820px\)\{\.helpTip\{width:(\d+)px;height:(\d+)px[^\n]*position:fixed", css)
    require(mobile is not None and min(int(mobile.group(1)), int(mobile.group(2))) >= 24, "mobile tap target / bottom sheet missing")
    require("text-transform:none" in css.split(".helpTipWrap.helpTipWrap .helpTipText{", 1)[1].split("}", 1)[0],
            "tooltip text must not inherit uppercase labels")
    require('type="button" class="helpTip"' in block and "aria-describedby" in block and 'role="tooltip"' in block, "accessible markup missing")
    require("e.key!=='Escape'" in block and "addEventListener('click'" in block and "},true);" in block, "Escape / capture click handlers missing")
    require("fetch(" not in block and "innerHTML" not in block, "help helper must stay local (no network / HTML injection)")
    return copies


HARNESS = r"""
let LANG='en';
const listeners={};
class ClassList{constructor(){this.s=new Set()}add(...c){c.forEach(x=>this.s.add(x))}remove(...c){c.forEach(x=>this.s.delete(x))}contains(c){return this.s.has(c)}toggle(c,on){on?this.s.add(c):this.s.delete(c);return on}}
class El{constructor(cls,parent){this.classList=new ClassList();cls.split(' ').forEach(c=>c&&this.classList.add(c));this.parentNode=parent||null;this.attrs={};this.children=[]}
 setAttribute(k,v){this.attrs[k]=String(v)}closest(sel){const c=sel.slice(1);let n=this;while(n){if(n.classList&&n.classList.contains(c))return n;n=n.parentNode}return null}
 querySelector(sel){const c=sel.slice(1);return this.children.find(x=>x.classList.contains(c))||null}}
const body=new El('body'),wraps=[];
function mount(){const w=new El('helpTipWrap',body),b=new El('helpTip',w);b.setAttribute('aria-expanded','false');w.children.push(b);wraps.push(w);return [w,b]}
const document={activeElement:body,addEventListener(t,f,cap){listeners[t]=f},querySelectorAll(sel){const cls=sel.split('.').filter(Boolean);return wraps.filter(w=>cls.every(c=>w.classList.contains(c)))}};
%(helpers)s
%(i18n)s
%(tr)s
%(block)s
const out={markup:{},dom:{}};
for(const lang of ['en','uk','ru']){LANG=lang;out.markup[lang]={};for(const c of EXPLAIN_CONCEPTS)out.markup[lang][c]=helpTip(c,c==='hook'?'Hook <b>"x"</b>':'');out.markup[lang].unknown=helpTip('bogus','x')}
const ev=t=>({target:t,key:'',preventDefault(){this.prevented=true},stopPropagation(){this.stopped=true}});
const [w1,b1]=mount(),[w2,b2]=mount(),st=()=>[w1.classList.contains('open'),b1.attrs['aria-expanded'],w2.classList.contains('open'),b2.attrs['aria-expanded']];
let e=ev(b1);listeners.click(e);out.dom.tapOpen=st();out.dom.stopped=!!(e.stopped&&e.prevented);
listeners.click(ev(b2));out.dom.tapOther=st();
listeners.click(ev(b2));out.dom.tapClose=st();
listeners.click(ev(b1));listeners.click(ev(body));out.dom.outside=st();
listeners.click(ev(b1));document.activeElement=b1;listeners.keydown({key:'Escape'});out.dom.escape=st();out.dom.muted=w1.classList.contains('muted');
listeners.focusout({target:b1});out.dom.blurUnmuted=!w1.classList.contains('muted');
listeners.click(ev(b1));listeners.mouseover({target:b2});out.dom.hoverOther=st();
listeners.click(ev(b1));listeners.focusin({target:b2});out.dom.focusOther=st();
listeners.click(ev(b1));listeners.mouseover({target:b1});out.dom.hoverSelf=st();
process.stdout.write(JSON.stringify(out));
"""


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("'", "&#39;").replace('"', "&quot;")


def render_checks(out, copies, flows):
    for lang in LOCALES:
        ids = set()
        for concept in CANONICAL:
            m = out["markup"][lang][concept]
            require("explainFlow." not in m, f"{lang}/{concept} untranslated flow key leaked")
            if concept in SURFACES:
                steps = flows[lang][concept].split(" → ")
                expected_flow = ('<span class="helpTipFlow">' + '<span class="helpTipArrow">→</span>'.join(
                    f'<span class="helpTipStep">{escape(s)}</span>' for s in steps) + "</span>")
                require(expected_flow in m, f"{lang}/{concept} mini flow diagram missing or out of order")
                require(f'<span class="helpTipSoon">{escape(copies[lang]["explain.tutorial"])}</span>' in m,
                        f"{lang}/{concept} tutorial placeholder missing")
                require(m.index("helpTipFlow") > m.index('role="tooltip"') and m.endswith("</span></span>"),
                        f"{lang}/{concept} flow must live inside the tooltip described by the button")
            else:
                require("helpTipFlow" not in m and "helpTipSoon" not in m, f"{lang}/{concept} must keep the plain T-533 tooltip")
            require(m.startswith('<span class="helpTipWrap"><button type="button" class="helpTip" data-explain="' + concept + '" aria-expanded="false"'),
                    f"{lang}/{concept} must render a focusable button")
            tip_id = re.search(r'aria-describedby="(helpTip\d+)"', m).group(1)
            require(f'role="tooltip" id="{tip_id}"' in m, f"{lang}/{concept} tooltip not linked by aria-describedby")
            ids.add(tip_id)
            expected = copies[lang][f"explain.{concept}"].replace("&", "&amp;").replace("'", "&#39;").replace('"', "&quot;")
            require(expected in m, f"{lang}/{concept} help copy missing from tooltip")
            require(not re.search(r"\bexplain\.[a-z]+\b", m), f"{lang}/{concept} untranslated key leaked")
        require(len(ids) == len(CANONICAL), f"{lang} tooltip ids must be unique")
        hook = out["markup"][lang]["hook"]
        require("<b>" not in hook and "Hook &lt;b&gt;&quot;x&quot;&lt;/b&gt;" in hook, f"{lang} term must be escaped in aria-label")
        require(out["markup"][lang]["unknown"] == "", "unknown concepts must not render help")
    require('aria-label="What is cycle?"' in out["markup"]["en"]["cycle"], "EN aria label")
    require('aria-label="Що таке cycle?"' in out["markup"]["uk"]["cycle"], "UK aria label")
    require('aria-label="Что такое cycle?"' in out["markup"]["ru"]["cycle"], "RU aria label")
    dom = out["dom"]
    require(dom["tapOpen"] == [True, "true", False, "false"] and dom["stopped"], f"tap must open one tip without triggering the card: {dom}")
    require(dom["tapOther"] == [False, "false", True, "true"], f"opening a tip must close the others: {dom}")
    require(dom["tapClose"] == [False, "false", False, "false"], f"second tap must close: {dom}")
    require(dom["outside"] == [False, "false", False, "false"], f"tap outside must close: {dom}")
    require(dom["escape"] == [False, "false", False, "false"] and dom["muted"], f"Escape must close and hide the focused tip: {dom}")
    require(dom["blurUnmuted"], "leaving focus must reset the Escape mute")
    require(dom["hoverOther"] == [False, "false", False, "false"], f"hovering another tip must close the open one (no overlap): {dom}")
    require(dom["focusOther"] == [False, "false", False, "false"], f"focusing another tip must close the open one (no overlap): {dom}")
    require(dom["hoverSelf"] == [True, "true", False, "false"], f"hovering the open tip must keep it open: {dom}")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, block, i18n, helpers, tr = extract(html)
    copies = static_checks(html, script, block, i18n)
    flows = surface_checks(html, script, block, i18n)
    print(f"Explainability static checks passed ({len(CANONICAL)} concepts, {len(MOUNTS) + len(RENDERED)} surface headings x EN/UK/RU)")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the fixture rendering check")
        print("SKIPPED fixture rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    program = HARNESS % {"helpers": helpers, "i18n": i18n, "tr": tr, "block": block}
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"help harness failed:\n{result.stderr[-2000:]}")
    render_checks(json.loads(result.stdout), copies, flows)
    print("Explainability fixture checks passed (accessible markup, flows, tutorial placeholder, escaping, "
          "tap/outside/Escape/blur/hover/focus, EN/UK/RU)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
