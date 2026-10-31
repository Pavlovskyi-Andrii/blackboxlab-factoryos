"""T-595 resizable/maximizable side drawers and Build Progress overflow regression.

Static checks pin the CSS contract: drawer width comes from --drawer-w and is capped so the sidebar stays
visible, <=900px drawers are full screen without grip/max controls, and the Build Progress / lane / Worker
Center grids wrap columns instead of cutting off Planned / In Progress / Completed / Blocked.

The behaviour run executes the real drawer script (// --- drawer:begin … drawer:end) in Node against the
real drawer markup, reusing the minimal DOM from test_navigation.py. No browser is needed. It drives the
left-edge grip with pointer events (mouse and touch both dispatch pointer events), the keyboard separator,
the max/restore button, Escape, session width memory and window resizes at 1440x900, 1024x768 and 390x844.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from test_locale_parity import FOREIGN_LETTERS, extract, parse_tables, require
from test_navigation import DOM_HARNESS, check_script_syntax

HTML = Path(__file__).resolve().parent / "static" / "index.html"

DRAWERS = ("taskPage", "dcPage", "qaPage", "intelPage", "brainPage", "variantPage", "packagePage", "cyclePage",
           "discoveryPage", "revideoPage", "finisherPage", "approvalPage", "publishingPage", "performancePage",
           "experimentPage", "agentDrawer")
KEYS = ("drawerCtl.resize", "drawerCtl.resizeHint", "drawerCtl.maximize", "drawerCtl.restore", "drawerCtl.close", "drawerCtl.width")
# Viewports from the DONE criterion, with the sidebar's right edge the CSS gives at that width (sticky column / 46px rail).
VIEWPORTS = ((1440, 220), (1024, 46), (390, 0))


def drawer_chunk(html, drawer_id):
    """Balanced <section>/<aside> extraction: Content Brain nests <section class="brainPanel"> inside its drawer."""
    m = re.search(r'<(section|aside) class="[^"]*" id="' + drawer_id + '">', html)
    require(m is not None, f"drawer #{drawer_id} markup missing")
    tag, depth = m.group(1), 0
    for t in re.finditer(r"<(/?)" + tag + r"\b[^>]*>", html[m.start():]):
        depth += -1 if t.group(1) else 1
        if depth == 0:
            return html[m.start():m.start() + t.end()]
    raise AssertionError(f"drawer #{drawer_id} is not closed")


def check_css(css):
    tail = css.split("/* T-595", 1)
    require(len(tail) == 2, "T-595 drawer CSS block missing")
    tail = tail[1]
    require(".resizableDrawer{width:var(--drawer-w," in tail, "drawer width is not driven by --drawer-w")
    require("max-width:calc(100vw - var(--drawer-side,0px) - 16px)!important" in tail, "drawer max width does not keep the sidebar visible")
    require(".resizableDrawer.maximized{width:calc(100vw - var(--drawer-side,0px) - 16px)!important}" in tail, "maximized drawer covers the sidebar")
    require(".drawerGrip{position:absolute;left:0;" in tail and "touch-action:none" in tail and "cursor:ew-resize" in tail, "left-edge grip is not a touch-safe resize handle")
    require(".drawerGrip:focus-visible" in tail and ".drawerMax:focus-visible" in tail, "drawer controls have no keyboard focus ring")
    phone = re.search(r"@media\(max-width:900px\)\{\.resizableDrawer,\.resizableDrawer\.maximized\{width:100vw!important;max-width:none!important[^}]*\}\.drawerGrip,\.drawerMax\{display:none!important\}\}", tail)
    require(phone is not None, "<=900px drawers are not full screen, or grip/max stay visible")
    require(".dcPage{inset:0 0 0 auto!important" in tail and ".dcPage.open{transform:translateX(0)!important}" in tail, "Worker Center is not a right-side drawer")
    # Columns wrap instead of being cut off: each board's last unconditional rule is an auto-fit grid capped at 100%.
    for board, minimum in ((".taskBoard", 180), (".lbBoard", 150), (".lbLanes", 210), (".dcSummary", 120)):
        rule = f"{board}{{grid-template-columns:repeat(auto-fit,minmax(min(100%,{minimum}px),1fr))}}"
        require(rule in tail, f"{board} columns can still be cut off")
        later = tail.split(rule, 1)[1]
        require(f"{board}{{" not in later, f"a later {board} rule overrides the wrapping grid")
    require(".taskCol,.lbCol,.lbLane,.lbItem{min-width:0;overflow-wrap:anywhere}" in tail, "long task titles can push columns out of the drawer")
    require("overflow-x:hidden" in tail.split(".taskBody,.dcBody", 1)[1].split("}", 1)[0], "drawer bodies can still scroll the whole panel sideways")


def check_locales(tables):
    for key in KEYS:
        en = tables["en"].get(key)
        require(en, f"en missing {key}")
        for lang in ("uk", "ru"):
            value = tables[lang].get(key)
            require(value and value != en, f"{lang} {key} missing or untranslated")
            require(not FOREIGN_LETTERS[lang].search(value), f"{lang} {key} uses letters from the other language")
        require("{px}" in tables["en"]["drawerCtl.width"], "width text has no value placeholder")


HARNESS = r"""
Object.defineProperty(El.prototype,'style',{get(){return this._style||(this._style={props:{},setProperty(k,v){this.props[k]=String(v)},getPropertyValue(k){return this.props[k]||''}})}});
Object.defineProperty(El.prototype,'previousElementSibling',{get(){const s=this.parentNode.children,i=s.indexOf(this);return i>0?s[i-1]:null}});
Object.defineProperty(El.prototype,'lastElementChild',{get(){const c=this.children;return c[c.length-1]||null}});
const _append=El.prototype.appendChild;
El.prototype.appendChild=function(n){const p=n.parentNode;if(p&&p.childNodes){const i=p.childNodes.indexOf(n);if(i>=0)p.childNodes.splice(i,1)}return _append.call(this,n)};
El.prototype.insertAdjacentHTML=function(pos,html){
 const tmp=new El('div',{},this.ownerDocument);parseInto(tmp,html,this.ownerDocument);const nodes=tmp.childNodes.splice(0);
 if(pos==='afterbegin'){nodes.forEach(n=>n.parentNode=this);this.childNodes.unshift(...nodes)}
 else if(pos==='beforebegin'){const p=this.parentNode,i=p.childNodes.indexOf(this);nodes.forEach(n=>n.parentNode=p);p.childNodes.splice(i,0,...nodes)}
 else throw Error('insertAdjacentHTML '+pos+' not stubbed');
};
El.prototype.setPointerCapture=function(){};
let CUR=null;
El.prototype.click=function(){fire(CUR,'click',this)};
El.prototype.getBoundingClientRect=function(){return {left:0,right:this.id==='appSideNav'?CUR.side:0}};
function boot({width=1440,side=220,lang='en',session={}}={}){
 const env={timers:[],closed:[],session:Object.assign({},session),observers:[],width,side,winListeners:[]};CUR=env;
 const doc={listeners:[],_mutation(el,k){for(const o of env.observers)for(const [t,opts] of o.targets)if(t===el&&(!opts.attributeFilter||opts.attributeFilter.includes(k)))o.pending=true},_visible:()=>true};
 const root=new El('html',{},doc),body=root.appendChild(new El('body',{},doc));parseInto(body,MARKUP,doc);
 Object.assign(doc,{documentElement:root,body,activeElement:body,
  querySelector:s=>root.querySelector(s),querySelectorAll:s=>root.querySelectorAll(s),getElementById:id=>root.querySelector('#'+id),
  addEventListener:(type,fn,capture)=>doc.listeners.push({type,fn,capture:capture===true})});
 const ctx={document:doc,console,innerWidth:width,
  sessionStorage:{getItem:k=>k in env.session?env.session[k]:null,setItem:(k,v)=>{env.session[k]=String(v)}},
  setTimeout:f=>{env.timers.push(f);return env.timers.length},
  MutationObserver:class{constructor(cb){this.cb=cb;this.targets=[];this.pending=false;env.observers.push(this)}observe(t,o){this.targets.push([t,o])}disconnect(){this.targets=[]}},
  matchMedia:q=>{const m=/\((max|min)-width:(\d+)px\)/.exec(q);return {matches:m[1]==='max'?ctx.innerWidth<=+m[2]:ctx.innerWidth>=+m[2],addEventListener(){}}},
  addEventListener:(type,fn)=>env.winListeners.push({type,fn})};
 ctx.window=ctx;
 for(const [fn,id] of CLOSERS)ctx[fn]=()=>{env.closed.push(id);doc.getElementById(id).classList.remove('open')};
 vm.createContext(ctx);vm.runInContext(CODE,ctx);vm.runInContext('LANG='+JSON.stringify(lang)+';drawerInit()',ctx);
 Object.assign(env,{doc,ctx});tick(env);return env;
}
function tick(env){for(let n=0;n<50;n++){let did=false;env.timers.splice(0).forEach(f=>{did=true;f()});for(const o of env.observers)if(o.pending){o.pending=false;did=true;o.cb([])}if(!did)return}}
function fire(env,type,target,extra){
 const ev=Object.assign({type,target,defaultPrevented:false,preventDefault(){this.defaultPrevented=true},stopPropagation(){}},extra||{});
 for(const l of env.doc.listeners)if(l.type===type&&l.capture)l.fn(ev);
 if(type==='click')for(let n=target;n&&n.nodeType===1;n=n.parentNode){const code=n.attrs.onclick;if(code)vm.runInContext('(function(event){'+code+'\n})',env.ctx).call(n,ev)}
 for(const l of env.doc.listeners)if(l.type===type&&!l.capture)l.fn(ev);
 tick(env);return ev;
}
const $$=(e,s)=>e.doc.querySelector(s);
const D=(e,id)=>$$(e,'#'+id);
const open=(e,id)=>{D(e,id).classList.add('open');tick(e)};
const W=(e,id)=>parseInt(D(e,id).style.getPropertyValue('--drawer-w'),10);
const grip=(e,id)=>D(e,id).querySelector('.drawerGrip');
const maxBtn=(e,id)=>D(e,id).querySelector('.drawerMax');
const key=(e,el,k,extra)=>{el.focus();return fire(e,'keydown',el,Object.assign({key:k,shiftKey:false},extra||{}))};
const drag=(e,id,xs,extra)=>{const g=grip(e,id);fire(e,'pointerdown',g,Object.assign({pointerId:1,button:0},extra||{}));const seen=xs.map(x=>{fire(e,'pointermove',g,{clientX:x,pointerId:1});return W(e,id)});fire(e,'pointerup',g,{pointerId:1});return seen};
const resize=(e,width,side)=>{e.ctx.innerWidth=width;e.width=width;e.side=side;e.winListeners.filter(l=>l.type==='resize').forEach(l=>l.fn({}));tick(e)};
const fails=[];const ok=(c,m)=>{if(!c)fails.push(m)};
const out={fails,viewports:[],langs:{}};

// 1. Every drawer gets a left-edge separator grip and a max/restore button right before ×, grouped so the title stays left.
{
 const e=boot();
 for(const id of IDS){
  const el=D(e,id),g=el.firstElementChild,head=el.querySelector('.closeX').parentNode;
  ok(el.classList.contains('resizableDrawer'),id+': not marked resizable');
  ok(g&&g.classList.contains('drawerGrip')&&g.getAttribute('role')==='separator'&&g.getAttribute('aria-orientation')==='vertical'&&g.getAttribute('tabindex')==='0'&&g.getAttribute('aria-controls')===id,id+': grip is not a focusable vertical separator for the drawer');
  ok(head.classList.contains('drawerHeadActions')&&head.children.length===2&&head.children[0].classList.contains('drawerMax')&&head.parentNode.lastElementChild===head,id+': max button is not beside × at the end of the header');
  ok(maxBtn(e,id).getAttribute('type')==='button'&&maxBtn(e,id).getAttribute('aria-pressed')==='false'&&maxBtn(e,id).getAttribute('aria-label')===EN['drawerCtl.maximize'],id+': max button ARIA');
  ok(el.querySelector('.closeX').getAttribute('aria-label'),id+': × has no accessible name');
 }
 vm.runInContext('drawerInit()',e.ctx);
 ok(IDS.every(id=>D(e,id).querySelectorAll('.drawerGrip').length===1&&D(e,id).querySelectorAll('.drawerMax').length===1),'drawerInit is not idempotent');
}

// 2. Default ~65% width (agent drawer keeps its compact size), bounds keep the sidebar visible, at each DONE viewport.
for(const [width,side] of VIEWPORTS){
 const e=boot({width,side}),r={width,side,drawers:{}};
 for(const id of IDS){open(e,id);const w=W(e,id),g=grip(e,id);r.drawers[id]={w,left:width-w,max:+g.getAttribute('aria-valuemax'),now:+g.getAttribute('aria-valuenow')};D(e,id).classList.remove('open');tick(e)}
 r.sideVar=e.doc.documentElement.style.getPropertyValue('--drawer-side');
 r.full=vm.runInContext('drawerFull()',e.ctx);
 out.viewports.push(r);
}

// 3. Pointer drag (mouse and touch) on the left edge: follows the pointer, clamps to [min, sidebar-safe max], remembered per session.
{
 const e=boot();open(e,'taskPage');
 const seen=drag(e,'taskPage',[300,100,1300,540]);
 ok(seen.join()==='1140,1204,360,900','drag widths: '+seen.join());
 ok(e.session['factoryos_drawer_w.taskPage']==='900','drag width not remembered: '+e.session['factoryos_drawer_w.taskPage']);
 ok(!D(e,'taskPage').classList.contains('resizing'),'resizing state stuck after pointerup');
 fire(e,'pointermove',grip(e,'taskPage'),{clientX:700});ok(W(e,'taskPage')===900,'pointer move after release still resizes');
 D(e,'taskPage').classList.remove('open');tick(e);open(e,'taskPage');ok(W(e,'taskPage')===900,'width lost after close/reopen');
 open(e,'dcPage');ok(W(e,'dcPage')===936,'one drawer width leaked into another: '+W(e,'dcPage'));
 const again=boot({session:e.session});open(again,'taskPage');ok(W(again,'taskPage')===900,'width not restored in the same session');
 const touch=boot();open(touch,'dcPage');const t=drag(touch,'dcPage',[640],{pointerType:'touch'});ok(t[0]===800,'touch drag: '+t[0]);
 const right=boot();open(right,'taskPage');fire(right,'pointerdown',grip(right,'taskPage'),{pointerId:1,button:2});fire(right,'pointermove',grip(right,'taskPage'),{clientX:300});
 ok(W(right,'taskPage')===936,'right-button press starts a resize');
}

// 4. Keyboard separator: arrows (Shift = bigger step), Home/End bounds, Enter toggles maximize; unrelated keys pass through.
{
 const e=boot();open(e,'taskPage');const g=grip(e,'taskPage');const seq=[];
 for(const [k,extra] of [['ArrowLeft'],['ArrowLeft',{shiftKey:true}],['ArrowRight'],['Home'],['End'],['ArrowLeft']]){const ev=key(e,g,k,extra);ok(ev.defaultPrevented,k+' not handled');seq.push(W(e,'taskPage'))}
 ok(seq.join()==='968,1096,1064,360,1204,1204','keyboard widths: '+seq.join());
 ok(g.getAttribute('aria-valuenow')==='1204'&&g.getAttribute('aria-valuemin')==='360'&&g.getAttribute('aria-valuetext')==='1204 px, 84% of the window','separator values not exposed: '+g.getAttribute('aria-valuetext'));
 key(e,g,'Enter');ok(D(e,'taskPage').classList.contains('maximized')&&maxBtn(e,'taskPage').getAttribute('aria-pressed')==='true','Enter does not maximize');
 key(e,g,'ArrowRight');ok(!D(e,'taskPage').classList.contains('maximized')&&W(e,'taskPage')===1172,'arrow from maximized does not restore and step: '+W(e,'taskPage'));
 ok(key(e,g,'x').defaultPrevented===false,'unrelated keys are swallowed');
}

// 5. Max/restore beside ×: toggles state + ARIA, remembered for the session, a drag from maximized restores to a sized drawer.
{
 const e=boot();open(e,'dcPage');const b=maxBtn(e,'dcPage');
 fire(e,'click',b);
 ok(D(e,'dcPage').classList.contains('maximized')&&b.getAttribute('aria-pressed')==='true'&&b.getAttribute('aria-label')===EN['drawerCtl.restore']&&b.textContent==='❐','maximize state/ARIA');
 ok(grip(e,'dcPage').getAttribute('aria-valuenow')==='1204','maximized width not reported to the separator');
 ok(e.session['factoryos_drawer_max.dcPage']==='1','maximized state not remembered');
 D(e,'dcPage').classList.remove('open');tick(e);open(e,'dcPage');ok(D(e,'dcPage').classList.contains('maximized'),'maximized state lost on reopen');
 fire(e,'click',b);ok(!D(e,'dcPage').classList.contains('maximized')&&W(e,'dcPage')===936&&b.getAttribute('aria-label')===EN['drawerCtl.maximize'],'restore does not return to the previous width');
 fire(e,'click',b);const seen=drag(e,'dcPage',[740]);ok(!D(e,'dcPage').classList.contains('maximized')&&seen[0]===700&&e.session['factoryos_drawer_max.dcPage']==='0','drag from maximized: '+seen[0]);
 ok(e.closed.length===0,'max/restore closed a drawer');
}

// 6. Escape closes the top drawer only; an open nav menu, help tooltip or modal is closed first instead.
{
 const e=boot();open(e,'taskPage');open(e,'dcPage');
 key(e,e.doc.body,'Escape');ok(e.closed.join()==='dcPage','Escape did not close the top drawer: '+e.closed.join());
 key(e,e.doc.body,'Escape');ok(e.closed.join()==='dcPage,taskPage','second Escape did not close the next drawer');
 ok(key(e,e.doc.body,'Escape').defaultPrevented===false,'Escape without a drawer is swallowed');
 for(const [sel,cls] of [['#appSideNav','navOpen'],['#tip','open'],['#modal','open']]){
  const f=boot();open(f,'agentDrawer');$$(f,sel).classList.add(cls);key(f,f.doc.body,'Escape');ok(f.closed.length===0,'Escape closed the drawer while '+sel+' was open');
 }
}

// 7. Phones and narrow tablets: full screen, no resize or maximize from pointer, keyboard or button.
{
 const e=boot({width:390,side:0});open(e,'taskPage');
 drag(e,'taskPage',[200]);fire(e,'click',maxBtn(e,'taskPage'));
 ok(!D(e,'taskPage').classList.contains('maximized')&&!e.session['factoryos_drawer_max.taskPage']&&!D(e,'taskPage').classList.contains('resizing'),'phone drawer can be maximized or dragged');
 ok(e.session['factoryos_drawer_w.taskPage']===undefined,'phone drag stored a width');
}

// 8. Window resize re-clamps open drawers without overwriting the remembered width.
{
 const e=boot({session:{'factoryos_drawer_w.taskPage':'1150'}});open(e,'taskPage');ok(W(e,'taskPage')===1150,'remembered width not applied');
 resize(e,1024,46);ok(W(e,'taskPage')===962,'resize does not keep the sidebar visible: '+W(e,'taskPage'));
 ok(e.session['factoryos_drawer_w.taskPage']==='1150','resize overwrote the remembered width');
 resize(e,1440,220);ok(W(e,'taskPage')===1150,'growing the window does not restore the remembered width');
}

// 9. RU/UK/EN labels the operator hears on the controls.
for(const lang of ['en','uk','ru']){
 const e=boot({lang});open(e,'taskPage');const g=grip(e,'taskPage');
 out.langs[lang]={resize:g.getAttribute('aria-label'),hint:g.getAttribute('title'),max:maxBtn(e,'taskPage').getAttribute('aria-label'),value:g.getAttribute('aria-valuetext'),close:$$(e,'#taskPage .closeX').getAttribute('aria-label')};
 fire(e,'click',maxBtn(e,'taskPage'));out.langs[lang].restore=maxBtn(e,'taskPage').getAttribute('aria-label');
}
process.stdout.write(JSON.stringify(out));
"""


def check_dom_behaviour(html, script, i18n, assigns, tr, tables):
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the drawer behaviour run")
        print("SKIPPED drawer behaviour run: node is not installed")
        return
    chunks = [drawer_chunk(html, d) for d in DRAWERS]
    closers = []
    for d, chunk in zip(DRAWERS, chunks):
        fn = re.search(r'<button class="closeX" onclick="(close\w+)\(\)"', chunk)
        require(fn is not None, f"#{d} has no × close handler")
        closers.append([fn.group(1), d])
    markup = ('<aside class="side" id="appSideNav"></aside><span class="helpTipWrap" id="tip"></span><div class="modal" id="modal"></div>'
              + "".join(chunks))
    block = re.search(r"^// --- drawer:begin.*?^// --- drawer:end$", script, re.S | re.M)
    require(block is not None, "drawer script block markers missing")
    parts = [
        re.search(r"^function textValue\(v\)\{.*?^\}$", script, re.S | re.M),
        re.search(r"^const esc=.*$", script, re.M),
        re.search(r"^function navMenuOpen\(\).*$", script, re.M),
    ]
    require(all(parts), "textValue/esc/navMenuOpen not found for the behaviour run")
    code = "\n".join([i18n, *assigns, "let LANG='en';", tr, *(p.group(0) for p in parts),
                      block.group(0).replace("\ndrawerInit();\n", "\n")])
    require(block.group(0).count("\ndrawerInit();\n") == 1, "drawer script no longer initializes itself")
    prefix = DOM_HARNESS[:DOM_HARNESS.index("function boot(")]
    program = (f"const MARKUP={json.dumps(markup)};const CODE={json.dumps(code)};const IDS={json.dumps(list(DRAWERS))};"
               f"const CLOSERS={json.dumps(closers)};const VIEWPORTS={json.dumps(VIEWPORTS)};const EN={json.dumps(tables['en'])};\n"
               + prefix + HARNESS)
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, f"drawer behaviour harness crashed: {result.stderr.strip()[-1500:]}")
    out = json.loads(result.stdout)
    require(not out["fails"], "drawer behaviour:\n  " + "\n  ".join(out["fails"]))
    for r in out["viewports"]:
        width, side = r["width"], r["side"]
        if width <= 900:
            require(r["full"], f"{width}px is not treated as full screen")
            continue
        require(not r["full"] and r["sideVar"] == f"{side}px", f"{width}px: sidebar edge not published: {r['sideVar']}")
        cap = width - side - 16
        for d, v in r["drawers"].items():
            expected = min(cap, round(width * (0.42 if d == "agentDrawer" else 0.65)))
            require(v["w"] == expected, f"{width}px {d}: default width {v['w']} != {expected}")
            require(v["left"] >= side + 16 and v["max"] == cap and v["now"] == v["w"], f"{width}px {d}: covers the sidebar or wrong bounds {v}")
    for lang, r in out["langs"].items():
        t = tables[lang]
        require(r["resize"] == t["drawerCtl.resize"] and r["hint"] == t["drawerCtl.resizeHint"], f"{lang} grip label not localized: {r}")
        require(r["max"] == t["drawerCtl.maximize"] and r["restore"] == t["drawerCtl.restore"], f"{lang} max/restore not localized: {r}")
        require(r["value"] == t["drawerCtl.width"].replace("{px}", "936").replace("{pct}", "65"), f"{lang} width value text: {r['value']}")
    print(f"Drawer behaviour passed: {len(DRAWERS)} drawers at {', '.join(f'{w}px' for w, _ in VIEWPORTS)}; pointer/touch drag, "
          "keyboard separator, max/restore, Escape order, session width memory, resize clamp, EN/UK/RU labels")


def main():
    html = HTML.read_text(encoding="utf-8")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    check_css(css)
    script, i18n, _task_copy, _task_fn, assigns, tr = extract(html)
    tables = parse_tables(i18n, assigns)
    check_locales(tables)
    # All four Build Progress columns and all lane-board columns are still rendered; wrapping, not hiding, keeps them visible.
    require("const cols=[['todo',tr('build.planned')],['in_progress',tr('build.inProgress')],['done',tr('build.completed')],['blocked',tr('build.blocked')]];" in script,
            "Build Progress no longer renders Planned / In Progress / Completed / Blocked")
    require("['planned','in_progress','blocked','review','done']" in script, "lane board columns changed")
    require('data-i18n-aria-label="drawerCtl.resize" data-i18n-title="drawerCtl.resizeHint"' in script, "grip labels are not refreshed by applyLanguage")
    check_script_syntax(script)
    check_dom_behaviour(html, script, i18n, assigns, tr, tables)
    print(f"Drawers passed: {len(DRAWERS)} resizable drawers, sidebar-safe bounds, full-screen phones, wrapping Build Progress/lane/Worker Center columns")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
