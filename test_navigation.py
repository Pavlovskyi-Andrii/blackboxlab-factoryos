"""T-594 left navigation regression: semantic groups, RU/UK/EN labels and route preservation.

Static checks. Every destination that existed before the regrouping (the before-map below, taken
from the pre-T-594 sidebar) must still be reachable from exactly one sidebar button with the same
handler. Each button belongs to a declared, collapsible section, carries a descriptive localized
hint, and every section heading / hint / menu control has a real EN, UK and RU translation. The
slide-out menu, remembered accordion state, breadcrumbs and keyboard handling are checked against
the markup, CSS and script. The inline script is syntax-checked with `node --check` when node is
available (required with FACTORYOS_REQUIRE_NODE=1).
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from test_locale_parity import FOREIGN_LETTERS, extract, parse_tables, require

HTML = Path(__file__).resolve().parent / "static" / "index.html"

# Before-map: label key -> click handler of the pre-T-594 flat sidebar (None = no handler).
BEFORE = {
    "nav.control": None,
    "approval.nav": "openApprovalStudio()",
    "publishing.nav": "openPublishingStudio()",
    "cycle.nav": "openAutonomousFactory()",
    "performance.nav": "openPerformanceStudio()",
    "experiment.nav": "openExperimentLab()",
    "brain.nav": "openContentBrain()",
    "discovery.nav": "openDiscoveryStudio()",
    "revideo.nav": "openRevideoStudio()",
    "finisher.nav": "openMediaFinisher()",
    "variant.nav": "S&&S.selectedJobId?openVariantStudio():toast(tr('toast.selectJob'))",
    "package.nav": "S&&S.selectedJobId?openPackageStudio():toast(tr('toast.selectJob'))",
    "nav.newJob": "openNew()",
    "nav.jobs": "document.querySelector('.jobs').scrollIntoView()",
    "nav.agents": "openAgentDirectory()",
    "nav.supervisor": "document.querySelector('.supervisor').scrollIntoView()",
    "nav.errors": "document.querySelector('.errorCenterCard').scrollIntoView()",
    "nav.pipeline": "openMakingOf()",
    "nav.build": "openBuildProgress()",
    "dc.nav": "openDelegationCenter()",
    "nav.outputs": "S&&S.selectedJobId?openJobOutputs(S.selectedJobId):toast(tr('toast.selectJob'))",
    "nav.analytics": "openFactoryIntelligence()",
    "nav.qa": "openReleaseReadiness()",
    "nav.settings": None,
    "mvp.nav": "openMvpFactory()",
    "mycast.nav": "openMyCastConfigurator()",
    "nav.browser": "openFactoryPage('surfer')",    # owner 2026-11-23: the sidebar opens the Surfer page; the read-only card is gone
    # Owner 2026-11-23: every standalone owner page has a sidebar entry.
    "nav.sheets": "openFactoryPage('sheets')",
    "nav.social": "openFactoryPage('social')",
    "nav.linkedin": "openFactoryPage('linkedin')",
    "nav.olx": "openFactoryPage('olx')",
    "nav.decisionMemory": "openFactoryPage('decision-memory')",
    "nav.mybrief": "openFactoryPage('mybrief')",
    "nav.ownerHub": "document.querySelector('.ohCard').scrollIntoView()",
    "nav.strategy": "document.querySelector('.stratCard').scrollIntoView()",   # owner 2026-11-14: brand strategy
    "nav.learn": "openLearning()",   # owner 2026-11-14: one Learning section (my learning, explainers, guide)
    "mods.nav": "document.querySelector('.modsCard').scrollIntoView()",   # owner 2026-11-15 (T-MODS): Mods & skills
}
GROUPS = ("overview", "create", "publish", "grow", "automation", "mvp", "mods", "learn", "system")
# Live counters updated by other renderers must keep their ids inside the sidebar.
COUNTERS = ("brainNavCount", "discoveryNavCount", "revideoNavCount", "variantNavCount", "packageNavState", "buildNavPct")


def nav_markup(html):
    m = re.search(r'<nav class="nav"[^>]*>(.*?)</nav>', html, re.S)
    require(m is not None, "sidebar <nav class=\"nav\"> missing")
    return m.group(0), m.group(1)


def parse_items(inner):
    """Return the sidebar as an ordered list of ('section', group) and ('button', attrs, body)."""
    items = []
    for m in re.finditer(r'<div class="navSection"([^>]*)>.*?</div>|<button([^>]*)>(.*?)</button>', inner, re.S):
        if m.group(1) is not None:
            group = re.search(r'data-nav-group="([^"]+)"', m.group(1))
            require(group is not None, "nav section without data-nav-group")
            require('role="heading"' in m.group(1), f"nav section {group.group(1)} is not exposed as a heading")
            items.append(("section", group.group(1)))
        else:
            items.append(("button", m.group(2), m.group(3)))
    return items


def attr(attrs, name):
    m = re.search(name + r'="([^"]*)"', attrs)
    return m.group(1) if m else None


def check_routes_and_groups(items):
    buttons = [i for i in items if i[0] == "button"]
    sections = [i[1] for i in items if i[0] == "section"]
    require(tuple(sections) == GROUPS, f"nav sections out of order or missing: {sections}")
    require(items[0] == ("section", "overview"), "sidebar must open with the Overview section")
    seen = {}
    current = None
    for item in items:
        if item[0] == "section":
            current = item[1]
            continue
        _, attrs, body = item
        key = re.search(r'data-i18n="([^"]+)"', body)
        require(key is not None, "nav button without a localized label")
        key = key.group(1)
        require(key not in seen, f"duplicate nav destination {key}")
        handler = attr(attrs, "onclick")
        handler = handler.replace("&amp;", "&") if handler else None
        require(key in BEFORE, f"unexpected nav destination {key}; update the before/after map")
        require(handler == BEFORE[key], f"{key} handler changed: {handler!r} != {BEFORE[key]!r}")
        require(attr(attrs, "data-nav-group") == current, f"{key} is tagged {attr(attrs, 'data-nav-group')} but sits under {current}")
        nav_id = attr(attrs, "data-nav-id")
        require(nav_id, f"{key} has no data-nav-id")
        require(attr(attrs, "data-i18n-title") == f"navHint.{nav_id}", f"{key} has no descriptive hint navHint.{nav_id}")
        require('class="navIcon" aria-hidden="true"' in body, f"{key} lost its icon")
        seen[key] = current
    require(set(seen) == set(BEFORE), f"destinations lost from the sidebar: {sorted(set(BEFORE) - set(seen))}")
    require(len(buttons) == len(BEFORE), "sidebar button count changed")
    require(seen["nav.control"] == "overview" and 'class="active"' in buttons[0][1], "Control Room must stay first and active")
    for group in GROUPS:
        require(group in seen.values(), f"section {group} is empty")
    return [attr(b[1], "data-nav-id") for b in buttons]


PRODUCT_NAMES = {"navGroup.mvp", "nav.linkedin", "nav.olx"}


def check_locales(tables, nav_ids):
    keys = [f"navGroup.{g}" for g in GROUPS] + ["navGroup.aria"] + [f"navHint.{n}" for n in nav_ids]
    keys += ["navMenu.open", "navMenu.close", "navCrumb.aria", "navCrumb.home"]
    for key in keys:
        en = tables["en"].get(key)
        require(en, f"en missing {key}")
        for lang in ("uk", "ru"):
            value = tables[lang].get(key)
            require(value, f"{lang} missing {key}")
            # Product names stay in English on purpose (owner 2026-11-11: "MVP Builder" in every language).
            require(value != en or key in PRODUCT_NAMES, f"{lang} {key} is untranslated EN copy")
            require(not FOREIGN_LETTERS[lang].search(value), f"{lang} {key} uses letters from the other language: {value}")
    require(tables["uk"]["navGroup.create"] != tables["ru"]["navGroup.create"], "UK and RU section labels must be distinct copy")


def check_collapsible_groups(inner):
    """Each section is a navGroup: a heading with a real toggle button that controls its item list."""
    groups = re.findall(r'<div class="navGroup" data-nav-group="([^"]+)">', inner)
    require(tuple(groups) == GROUPS, f"navGroup wrappers out of order or missing: {groups}")
    for group in GROUPS:
        toggle = re.search(r'<button type="button" class="navSectionToggle" id="navHead-' + group + r'"([^>]*)>(.*?)</button>', inner, re.S)
        require(toggle is not None, f"section {group} has no toggle button")
        require('aria-expanded="true"' in toggle.group(1), f"section {group} toggle has no aria-expanded")
        require(f'aria-controls="navItems-{group}"' in toggle.group(1), f"section {group} toggle does not control its list")
        require(f"onclick=\"toggleNavGroup('{group}')\"" in toggle.group(1), f"section {group} toggle is not wired")
        require(f'data-i18n="navGroup.{group}"' in toggle.group(2), f"section {group} toggle lost its localized label")
        items = re.search(r'<div class="navItems" id="navItems-' + group + r'" role="group" aria-labelledby="navHead-' + group + r'">(.*?)</div></div>', inner, re.S)
        require(items is not None, f"section {group} has no labelled item group")
        tags = re.findall(r'data-nav-group="([^"]+)" data-nav-id', items.group(1))
        require(tags and set(tags) == {group}, f"section {group} list holds foreign items: {tags}")


def check_behaviour(html, script, css):
    # Slide-out: ~1/3 on capable viewports, usable adaptive width on phones, outside tap closes.
    require("width:clamp(320px,33.333vw,520px)" in css, "desktop slide-out menu is not ~1/3 of the viewport")
    require(".side.navOpen{width:min(86vw,360px)" in css, "phone drawer must use a usable adaptive width")
    require('id="navBackdrop" onclick="closeMobileNav()"' in html, "outside tap no longer closes the menu")
    require(".navBackdrop.open{opacity:1;pointer-events:auto}" in css.split("@media(min-width:701px){", 1)[-1], "backdrop not active on desktop")
    require('id="navExpandToggle" aria-controls="appSideNav" aria-expanded="false"' in html, "desktop expand toggle missing")
    require('id="mobileNavToggle" aria-label="Open navigation" aria-controls="appSideNav"' in html, "phone toggle lost aria-controls")
    require("content:attr(title)" in css, "expanded menu does not show one-line descriptions")
    require(".navGroup.collapsed .navItems{display:none}" in css, "collapsed groups are not hidden")
    require(".side:not(.navOpen) .navGroup.collapsed .navItems{display:grid}" in css, "icon rails must keep every destination visible")
    # The rail hide rule must out-rank the toggle's display:flex!important (.nav .navSection .navSectionToggle:not(.active)).
    require(".side:not(.navOpen) .nav .navSection .navSectionToggle{display:none!important}" in css, "section toggles leak into the icon rail")
    # Remembered accordion state, current section, breadcrumbs, keyboard.
    require("const NAV_COLLAPSED_KEY='factoryos_nav_collapsed'" in script, "accordion state is not remembered")
    require("localStorage.setItem(NAV_COLLAPSED_KEY" in script, "accordion state is not persisted")
    require("set.has(g)&&!box.querySelector('.navItems>button.active')" in script, "current group can be restored collapsed")
    require("b.setAttribute('aria-current','page')" in script, "current destination is not exposed via aria-current")
    require('id="navCrumbs" data-i18n-aria-label="navCrumb.aria"' in html, "breadcrumb landmark missing")
    require("function renderNavCrumbs(" in script and "tr('navGroup.'+group)" in script, "breadcrumbs do not show the section")
    require("syncNavToggles();restoreNavGroups();renderNavCrumbs();" in script, "applyLanguage does not refresh nav state")
    require("new MutationObserver(" in script and "setNavCurrent('control')" in script, "closing a studio does not return to Control Room")
    for key in ("'ArrowDown','ArrowUp','Home','End'", "e.key==='ArrowRight'||e.key==='ArrowLeft'", "e.key==='Escape'&&navMenuOpen()"):
        require(key in script, f"keyboard handling missing: {key}")
    require("e.target.closest('.navItems>button')" in script, "only destinations, not section toggles, may close the menu")
    require("window.addEventListener('resize',()=>{if(!mobileNavEnabled())closeMobileNav()})" not in script, "desktop resize must not force-close the menu")


def check_script_syntax(script):
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the script syntax check")
        print("SKIPPED inline script syntax check: node is not installed")
        return
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "factoryos-ui.js"
        path.write_text(script, encoding="utf-8")
        result = subprocess.run([node, "--check", str(path)], capture_output=True, text=True, timeout=60)
    require(result.returncode == 0, f"inline dashboard script has a syntax error: {result.stderr.strip()[:400]}")


# Behaviour run: the real sidebar markup and the real nav script (// --- nav:begin … nav:end) are executed in
# Node against a minimal DOM. No browser is needed. Taps are click events (what a touch tap dispatches).
# _visible() mirrors the CSS rules pinned by check_behaviour(): collapsed items are hidden in the open menu
# and in the >=901px sidebar, and section toggles are hidden in the closed <=900px rails.
DOM_HARNESS = r"""
const vm=require('vm');
const VOID=new Set(['input','br','img','meta','link','hr']);
const decodeEnt=s=>s.replace(/&(amp|lt|gt|quot|#39);/g,(m,k)=>({amp:'&',lt:'<',gt:'>',quot:'"','#39':"'"}[k]));
class Text{constructor(d){this.nodeType=3;this.data=d;this.parentNode=null}get textContent(){return this.data}}
class ClassList{
 constructor(el){this.el=el}
 _get(){return (this.el.attrs.class||'').split(/\s+/).filter(Boolean)}
 _set(a){const v=a.join(' ');if(v===(this.el.attrs.class||''))return;this.el.attrs.class=v;this.el._mutated('class')}
 contains(c){return this._get().includes(c)}
 add(...cs){const a=this._get();cs.forEach(c=>{if(!a.includes(c))a.push(c)});this._set(a)}
 remove(...cs){this._set(this._get().filter(c=>!cs.includes(c)))}
 toggle(c,force){const on=force===undefined?!this.contains(c):!!force;if(on)this.add(c);else this.remove(c);return on}
}
function parseComp(t){const c={tag:null,id:null,cls:[],attrs:[]};t.replace(/\[([\w-]+)(?:="([^"]*)")?\]|([#.]?)([\w-]+)/g,(m,a,v,p,n)=>{if(a)c.attrs.push([a,v]);else if(p==='#')c.id=n;else if(p==='.')c.cls.push(n);else c.tag=n.toUpperCase();return ''});return c}
function parseSel(s){const sel=[];let comb=' ';for(const t of s.trim().replace(/\s*>\s*/g,' > ').split(/\s+/)){if(t==='>'){comb='>';continue}sel.push({comp:parseComp(t),comb});comb=' '}return sel}
function matchComp(el,c){return el.nodeType===1&&(!c.tag||el.tagName===c.tag)&&(!c.id||el.id===c.id)&&c.cls.every(k=>el.classList.contains(k))&&c.attrs.every(([a,v])=>a in el.attrs&&(v===undefined||el.attrs[a]===v))}
function matchFrom(el,sel,i){
 if(!matchComp(el,sel[i].comp))return false;if(i===0)return true;
 let p=el.parentNode;if(sel[i].comb==='>')return !!p&&p.nodeType===1&&matchFrom(p,sel,i-1);
 for(;p&&p.nodeType===1;p=p.parentNode)if(matchFrom(p,sel,i-1))return true;return false;
}
class El{
 constructor(tag,attrs,doc){this.nodeType=1;this.tagName=tag.toUpperCase();this.attrs=attrs;this.childNodes=[];this.parentNode=null;this.ownerDocument=doc;this.classList=new ClassList(this);this.scrolled=0}
 get children(){return this.childNodes.filter(n=>n.nodeType===1)}
 get firstElementChild(){return this.children[0]||null}
 get id(){return this.attrs.id||''}
 get title(){return this.attrs.title||''}set title(v){this.attrs.title=String(v)}
 set placeholder(v){this.attrs.placeholder=String(v)}
 get dataset(){const d={};for(const [k,v] of Object.entries(this.attrs))if(k.startsWith('data-'))d[k.slice(5).replace(/-([a-z])/g,(_,c)=>c.toUpperCase())]=v;return d}
 getAttribute(k){return k in this.attrs?this.attrs[k]:null}
 setAttribute(k,v){this.attrs[k]=String(v);this._mutated(k)}
 removeAttribute(k){delete this.attrs[k];this._mutated(k)}
 _mutated(k){this.ownerDocument._mutation(this,k)}
 appendChild(n){n.parentNode=this;this.childNodes.push(n);return n}
 get textContent(){return this.childNodes.map(n=>n.textContent).join('')}
 set textContent(v){this.childNodes=[];this.appendChild(new Text(String(v)))}
 set innerHTML(h){this.childNodes=[];parseInto(this,h,this.ownerDocument)}
 contains(n){for(;n;n=n.parentNode)if(n===this)return true;return false}
 matches(s){const sel=parseSel(s);return matchFrom(this,sel,sel.length-1)}
 closest(s){for(let n=this;n&&n.nodeType===1;n=n.parentNode)if(n.matches(s))return n;return null}
 querySelectorAll(s){const sel=parseSel(s),out=[];const walk=n=>{for(const c of n.children){if(matchFrom(c,sel,sel.length-1))out.push(c);walk(c)}};walk(this);return out}
 querySelector(s){return this.querySelectorAll(s)[0]||null}
 focus(){this.ownerDocument.activeElement=this}
 scrollIntoView(){this.scrolled++}
 get offsetParent(){return this.ownerDocument._visible(this)?this.parentNode:null}
}
function parseInto(parent,html,doc){
 const stack=[parent],re=/<!--[\s\S]*?-->|<(\/?)([a-zA-Z][\w-]*)([^>]*)>|([^<]+)/g;let m;
 while((m=re.exec(html))){
  if(m[4]!==undefined){stack[stack.length-1].appendChild(new Text(decodeEnt(m[4])));continue}
  if(m[2]===undefined)continue;const tag=m[2].toLowerCase();
  if(m[1]){for(let i=stack.length-1;i>0;i--)if(stack[i].tagName===tag.toUpperCase()){stack.length=i;break}continue}
  const attrs={};m[3].replace(/([\w-]+)(?:="([^"]*)")?/g,(_,k,v)=>{attrs[k]=v===undefined?'':decodeEnt(v);return ''});
  const el=new El(tag,attrs,doc);stack[stack.length-1].appendChild(el);if(!VOID.has(tag))stack.push(el);
 }
}
function boot({width=1440,lang='en',storage={},job=false}={}){
 const env={timers:[],calls:[],toasts:[],top:0,store:Object.assign({},storage),observers:[],width};
 const doc={listeners:[],
  _mutation(el,k){for(const o of env.observers)for(const [t,opts] of o.targets)if(t===el&&(!opts.attributeFilter||opts.attributeFilter.includes(k)))o.pending=true},
  _visible(el){
   const open=doc.getElementById('appSideNav').classList.contains('navOpen');
   for(let n=el;n&&n.nodeType===1;n=n.parentNode){
    if(n.classList.contains('navItems')&&n.parentNode.classList.contains('collapsed')&&(open||width>=901))return false;
    if(n.classList.contains('navSection')&&width<=900&&!open)return false;
   }
   return true;
  }};
 const root=new El('html',{},doc),body=root.appendChild(new El('body',{},doc));parseInto(body,MARKUP,doc);
 Object.assign(doc,{documentElement:root,body,activeElement:body,title:'',
  querySelector:s=>root.querySelector(s),querySelectorAll:s=>root.querySelectorAll(s),getElementById:id=>root.querySelector('#'+id),
  addEventListener:(type,fn,capture)=>doc.listeners.push({type,fn,capture:capture===true})});
 const ctx={document:doc,console,
  localStorage:{getItem:k=>k in env.store?env.store[k]:null,setItem:(k,v)=>{env.store[k]=String(v)},removeItem:k=>{delete env.store[k]}},
  setTimeout:f=>{env.timers.push(f);return env.timers.length},
  MutationObserver:class{constructor(cb){this.cb=cb;this.targets=[];this.pending=false;env.observers.push(this)}observe(t,o){this.targets.push([t,o])}disconnect(){this.targets=[];this.pending=false}},
  matchMedia:q=>{const m=/\((max|min)-width:(\d+)px\)/.exec(q);return {matches:m[1]==='max'?width<=+m[2]:width>=+m[2],addEventListener(){}}},
  scrollTo:()=>{env.top++},location:{href:''},render:()=>{},helpTitle:k=>k,toast:m=>env.toasts.push(m)};
 ctx.window=ctx;
 for(const fn of HANDLERS)ctx[fn]=()=>{env.calls.push(fn);doc.getElementById('studio').classList.add('open')};
 vm.createContext(ctx);vm.runInContext(CODE,ctx);
 vm.runInContext('LANG='+JSON.stringify(lang)+';S='+(job?'{selectedJobId:"j1"}':'null')+';applyLanguage()',ctx);
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
const nav=(e,id)=>$$(e,'.navItems>button[data-nav-id="'+id+'"]');
const tap=(e,el)=>fire(e,'click',el);
const key=(e,k)=>fire(e,'keydown',e.doc.activeElement,{key:k});
const focusId=e=>{const a=e.doc.activeElement;return a.id||a.dataset.navId||a.tagName};
const isOpen=e=>$$(e,'#appSideNav').classList.contains('navOpen');
const current=e=>e.doc.querySelectorAll('.navItems>button.active').map(b=>b.dataset.navId);
const crumbs=e=>$$(e,'#navCrumbs').children.filter(c=>!c.classList.contains('navCrumbSep')).map(c=>c.textContent);
const collapsed=(e,g)=>$$(e,'.navGroup[data-nav-group="'+g+'"]').classList.contains('collapsed');
const fails=[];const ok=(c,m)=>{if(!c)fails.push(m)};
const out={runs:[],langs:{},fails};

// 1. Every destination, tapped on its text label, with and without a selected job.
for(const job of [false,true])for(const id of IDS){
 const e=boot({job}),b=nav(e,id);tap(e,b.querySelector('[data-i18n]'));
 const r={id,job,calls:e.calls.slice(),toasts:e.toasts.slice(),top:e.top,current:current(e),aria:b.getAttribute('aria-current'),crumbs:crumbs(e),
  scrolled:['pipelineCard','supervisor','errorCenterCard','jobs','ohCard','stratCard','modsCard'].filter(c=>$$(e,'.'+c).scrolled),studio:$$(e,'#studio').classList.contains('open')};
 if(r.studio){$$(e,'#studio').classList.remove('open');tick(e);r.after=current(e);r.afterCrumbs=crumbs(e)}
 out.runs.push(r);
}

// 2. Remembered accordion state; the current group is never restored collapsed.
{
 const e=boot();tap(e,$$(e,'#navHead-grow'));
 ok(collapsed(e,'grow')&&$$(e,'#navHead-grow').getAttribute('aria-expanded')==='false','section toggle does not collapse');
 ok(e.store.factoryos_nav_collapsed==='["grow"]','collapsed section not remembered: '+e.store.factoryos_nav_collapsed);
 const again=boot({storage:e.store});ok(collapsed(again,'grow')&&!collapsed(again,'create'),'remembered section not restored after reload');
 tap(e,$$(e,'#navHead-grow'));ok(!collapsed(e,'grow')&&e.store.factoryos_nav_collapsed==='[]','re-expanding is not remembered');
 const cur=boot({storage:{factoryos_nav_collapsed:'["overview"]'}});
 ok(!collapsed(cur,'overview')&&cur.store.factoryos_nav_collapsed==='["overview"]','current section restored collapsed, or remembered choice overwritten');
}

// 3. Slide-out menu on desktop, tablet rail and phone: open, section toggles keep it open, outside tap / Escape / destination close it.
for(const width of [1440,1024,800,390]){
 const phone=width<=700,toggleId=phone?'mobileNavToggle':'navExpandToggle';let e=boot({width});const t=()=>$$(e,'#'+toggleId);
 tap(e,t());
 ok(isOpen(e)&&$$(e,'#navBackdrop').classList.contains('open'),width+': toggle does not open the menu');
 ok(t().getAttribute('aria-expanded')==='true'&&t().getAttribute('aria-label')===I18N_EN['navMenu.close'],width+': toggle ARIA not updated on open');
 ok(phone?t().textContent==='×':t().firstElementChild.textContent==='«',width+': toggle glyph not updated');
 ok(focusId(e)==='control',width+': opening does not focus the current destination ('+focusId(e)+')');
 tap(e,$$(e,'#navHead-system'));ok(isOpen(e)&&collapsed(e,'system'),width+': section toggle closed the menu or did nothing');
 tap(e,$$(e,'#navHead-system'));
 tap(e,$$(e,'#navBackdrop'));ok(!isOpen(e)&&!$$(e,'#navBackdrop').classList.contains('open'),width+': outside tap does not close the menu');
 ok(t().getAttribute('aria-expanded')==='false'&&t().getAttribute('aria-label')===I18N_EN['navMenu.open'],width+': toggle ARIA not reset on close');
 tap(e,t());key(e,'Escape');ok(!isOpen(e)&&focusId(e)===toggleId,width+': Escape does not close and return focus ('+focusId(e)+')');
 tap(e,t());tap(e,nav(e,'review'));ok(!isOpen(e)&&current(e).join()==='review',width+': choosing a destination does not close the menu');
}

// 4. Keyboard: arrows/Home/End over visible sidebar buttons, Left/Right collapse and expand a section.
{
 const e=boot();nav(e,'control').focus();
 const seq=['ArrowDown','ArrowUp','ArrowUp','ArrowUp','Home','End'].map(k=>{key(e,k);return focusId(e)});
 ok(seq.join()==='pipeline,control,navHead-overview,settings,navHead-overview,settings','desktop arrow/Home/End order: '+seq.join());
 $$(e,'#navHead-create').focus();const ev=fire(e,'keydown',e.doc.activeElement,{key:'ArrowLeft'});
 ok(ev.defaultPrevented&&collapsed(e,'create')&&$$(e,'#navHead-create').getAttribute('aria-expanded')==='false','ArrowLeft does not collapse a section');
 key(e,'ArrowDown');ok(focusId(e)==='navHead-publish','ArrowDown enters a collapsed section: '+focusId(e));
 $$(e,'#navHead-create').focus();key(e,'ArrowRight');key(e,'ArrowDown');ok(!collapsed(e,'create')&&focusId(e)==='newJob','ArrowRight does not expand a section: '+focusId(e));
 const rail=boot({width:800,storage:{factoryos_nav_collapsed:'["create"]'}});nav(rail,'errors').focus();key(rail,'ArrowDown');
 ok(focusId(rail)==='newJob','icon rail hides destinations of a collapsed section: '+focusId(rail));
 key(rail,'Home');ok(focusId(rail)==='control','icon rail focuses hidden section toggles: '+focusId(rail));
 const phone=boot({width:390,storage:{factoryos_nav_collapsed:'["create"]'}});tap(phone,$$(phone,'#mobileNavToggle'));nav(phone,'errors').focus();key(phone,'ArrowDown');
 ok(focusId(phone)==='navHead-create','open phone menu does not reach the collapsed section toggle: '+focusId(phone));
 ok(fire(phone,'keydown',nav(phone,'errors'),{key:'x'}).defaultPrevented===false,'unrelated keys are swallowed');
}

// 5. Breadcrumbs: the section crumb reveals and focuses its section in the menu, home returns to Control Room.
{
 const e=boot({storage:{factoryos_nav_collapsed:'["publish"]'}});
 ok(collapsed(e,'publish'),'fixture: publish should start collapsed');
 vm.runInContext("setNavCurrent('review')",e.ctx);ok(!collapsed(e,'publish'),'current destination hidden in a collapsed section');
 ok(e.store.factoryos_nav_collapsed==='["publish"]','showing the current section overwrote the remembered choice');
 tap(e,$$(e,'#navHead-publish'));ok(collapsed(e,'publish'),'fixture: collapse publish again');
 tap(e,$$(e,'#navCrumbs').children[2]);
 ok(isOpen(e)&&!collapsed(e,'publish')&&focusId(e)==='review','section crumb does not open the menu on its section ('+focusId(e)+')');
 key(e,'Escape');tap(e,$$(e,'#navCrumbs').children[0]);ok(current(e).join()==='control'&&e.top===1,'home crumb does not return to Control Room');
}

// 6. RU/UK/EN: what the operator actually sees after applyLanguage().
for(const lang of ['en','uk','ru']){
 const e=boot({lang}),side=$$(e,'#appSideNav');
 const r={labels:{},titles:{},aria:$$(e,'nav.nav').getAttribute('aria-label'),expand:$$(e,'#navExpandToggle').getAttribute('aria-label'),phone:$$(e,'#mobileNavToggle').getAttribute('aria-label')};
 side.querySelectorAll('[data-i18n]').forEach(el=>{r.labels[el.dataset.i18n]=el.textContent});
 side.querySelectorAll('.navItems>button').forEach(b=>{r.titles[b.dataset.navId]=b.title});
 tap(e,nav(e,'review'));r.crumbs=crumbs(e);r.home=$$(e,'#navCrumbs').children[0].getAttribute('aria-label');r.crumbAria=$$(e,'#navCrumbs').getAttribute('aria-label');
 out.langs[lang]=r;
}
process.stdout.write(JSON.stringify(out));
"""


def dom_inputs(html, script, i18n, assigns, tr):
    markup = [
        re.search(r'<button class="mobileNavToggle".*?<div class="navBackdrop"[^>]*></div>', html),
        re.search(r'<aside class="side" id="appSideNav">.*?</aside>', html, re.S),
        re.search(r'<nav class="navCrumbs"[^>]*></nav>', html),
    ]
    require(all(markup), "sidebar, toggle, backdrop or breadcrumb markup not found for the behaviour run")
    stubs = '<div id="studio" class="drawer"></div>' + "".join(f'<div class="{c}"></div>' for c in ("pipelineCard", "supervisor", "errorCenterCard", "jobs", "ohCard", "stratCard", "modsCard"))
    block = re.search(r"^// --- nav:begin.*?^// --- nav:end$", script, re.S | re.M)
    require(block is not None, "nav script block markers missing")
    parts = [
        re.search(r"^function textValue\(v\)\{.*?^\}$", script, re.S | re.M),
        re.search(r"^const esc=.*$", script, re.M),
        re.search(r"^function applyLanguage\(\)\{.*?^\}$", script, re.S | re.M),
    ]
    require(all(parts), "textValue/esc/applyLanguage not found for the behaviour run")
    code = "\n".join([i18n, *assigns, "let LANG='en',S=null;const $=s=>document.querySelector(s);", tr,
                      *(p.group(0) for p in parts), block.group(0)])
    return "\n".join(m.group(0) for m in markup) + stubs, code


def check_dom_behaviour(html, script, i18n, assigns, tr, tables, items):
    node = shutil.which("node")
    if not node:
        require(os.environ.get("FACTORYOS_REQUIRE_NODE") != "1", "node is required for the nav behaviour run")
        print("SKIPPED nav behaviour run: node is not installed")
        return
    markup, code = dom_inputs(html, script, i18n, assigns, tr)
    meta = {}
    for item in items:
        if item[0] == "button":
            key = re.search(r'data-i18n="([^"]+)"', item[2]).group(1)
            meta[attr(item[1], "data-nav-id")] = (key, attr(item[1], "data-nav-group"), BEFORE[key])
    handlers = sorted({fn for _, _, h in meta.values() if h for fn in re.findall(r"\b(open\w+)\(", h)})
    program = (f"const MARKUP={json.dumps(markup)};const CODE={json.dumps(code)};const IDS={json.dumps(list(meta))};"
               f"const HANDLERS={json.dumps(handlers)};const I18N_EN={json.dumps(tables['en'])};\n" + DOM_HARNESS)
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=120)
    require(result.returncode == 0, f"nav behaviour harness crashed: {result.stderr.strip()[-1500:]}")
    out = json.loads(result.stdout)
    require(not out["fails"], "nav behaviour:\n  " + "\n  ".join(out["fails"]))
    en = tables["en"]
    home = ["⌂", en["navGroup.overview"], en["nav.control"]]
    covered = set()
    for r in out["runs"]:
        nid, job = r["id"], r["job"]
        key, group, handler = meta[nid]
        where = f"{nid} ({'job selected' if job else 'no job'})"
        opened = ["⌂", en[f"navGroup.{group}"], en[key]]
        if handler is None:
            require(not r["calls"] and not r["toasts"] and not r["scrolled"], f"{where} has no handler but did something")
            if nid == "control":
                require(r["top"] == 1 and r["current"] == ["control"] and r["crumbs"] == home, f"{where} does not return to the top")
            else:
                require(r["current"] == ["control"], f"{where} opens nothing but claims to be the current page")
        elif "scrollIntoView" in handler:
            target = re.search(r"querySelector\('\.(\w+)'\)", handler).group(1)
            require(r["scrolled"] == [target] and not r["calls"], f"{where} did not scroll to .{target}: {r['scrolled']}")
            require(r["current"] == [nid] and r["aria"] == "page" and r["crumbs"] == opened, f"{where} not marked current: {r['current']} {r['crumbs']}")
        elif "selectedJobId" in handler and not job:
            require(not r["calls"] and r["toasts"] == [en["toast.selectJob"]], f"{where} must ask for a job first: {r}")
            require(r["current"] == ["control"] and r["crumbs"] == home, f"{where} claims a studio that did not open")
        else:
            fn = re.findall(r"\b(open\w+)\(", handler)[0]
            require(r["calls"] == [fn] and r["studio"], f"{where} did not reach {fn}(): {r['calls']}")
            require(r["current"] == [nid] and r["aria"] == "page" and r["crumbs"] == opened, f"{where} not marked current: {r['current']} {r['crumbs']}")
            require(r.get("after") == ["control"] and r.get("afterCrumbs") == home, f"{where} stays current after its studio closed")
        covered.add((nid, job))
    require(len(covered) == 2 * len(BEFORE), "behaviour run did not tap every destination")
    for lang, r in out["langs"].items():
        t = tables[lang]
        for key, text in r["labels"].items():
            require(text == t[key], f"{lang} sidebar shows {text!r} for {key}, expected {t[key]!r}")
        for nid, title in r["titles"].items():
            require(title == t[f"navHint.{nid}"], f"{lang} {nid} hint not applied: {title!r}")
        require(r["aria"] == t["navGroup.aria"] and r["crumbAria"] == t["navCrumb.aria"] and r["home"] == t["navCrumb.home"], f"{lang} nav/breadcrumb ARIA not localized")
        require(r["expand"] == t["navMenu.open"] and r["phone"] == t["navMenu.open"], f"{lang} menu toggles not localized")
        require(r["crumbs"] == ["⌂", t["navGroup.publish"], t["approval.nav"]], f"{lang} breadcrumbs wrong: {r['crumbs']}")
        require(set(r["labels"]) >= {f"navGroup.{g}" for g in GROUPS}, f"{lang} section headings missing")
        if lang != "en":
            require(r["crumbs"] != out["langs"]["en"]["crumbs"], f"{lang} breadcrumbs fall back to EN")
    print(f"Navigation behaviour passed: {len(out['runs'])} taps over {len(BEFORE)} destinations, slide-out at 1440/1024/800/390px, "
          "outside tap / Escape / destination close, keyboard, remembered sections, breadcrumbs, EN/UK/RU rendering")


def main():
    html = HTML.read_text(encoding="utf-8")
    nav, inner = nav_markup(html)
    check_collapsible_groups(inner)
    require('data-i18n-aria-label="navGroup.aria"' in nav, "sidebar has no localized accessible name")
    for counter in COUNTERS:
        require(f'id="{counter}"' in inner, f"live nav counter #{counter} missing from sidebar")
    items = parse_items(inner)
    nav_ids = check_routes_and_groups(items)
    script, i18n, _task_copy, _task_fn, assigns, tr = extract(html)
    tables = parse_tables(i18n, assigns)
    check_locales(tables, nav_ids)
    require("[data-i18n-title]" in script and "el.title=tr(el.dataset.i18nTitle)" in script, "applyLanguage does not localize nav hints")
    require("[data-i18n-aria-label]" in script, "applyLanguage does not localize the nav aria-label")
    css = html.split("<style>", 1)[1].split("</style>", 1)[0]
    require(".navSection{" in css, "nav section styling missing")
    require(".side.navOpen .navSection{" in css, "open mobile drawer must show section labels")
    require(".nav button:focus-visible{" in css, "keyboard focus ring for nav buttons missing")
    check_behaviour(html, script, css)
    check_script_syntax(script)
    check_dom_behaviour(html, script, i18n, assigns, tr, tables, items)
    print(f"Navigation passed: {len(BEFORE)} destinations preserved across {len(GROUPS)} collapsible sections, "
          "slide-out menu, breadcrumbs, keyboard handling, EN/UK/RU labels and hints present")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
