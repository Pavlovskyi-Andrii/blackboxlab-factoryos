"""T-581 Operator assignment UI regression.

Static checks always run. The fixture check drives the real T-580 role API (factory_roles /
factory_role_assignment) through representative Content (Scriptwriter) and Engineering (Engineer)
assignment changes, then renders each resulting board with the real inline renderers from
static/index.html under Node: the role panel, the per-worker operator chip shown on every worker
card and the tooltip detail. Offline / auth-pending / unverified operators must render as such,
never as ready. Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it the check is
reported as SKIPPED, never as passed.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-roles-ui-")
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""
os.environ["FACTORY_GEMINI_API_KEY"] = ""

import app  # noqa: E402
from starlette.requests import Request  # noqa: E402

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- role-operators:begin"
END = "// --- role-operators:end"
SECRET_LLM = "sk-fixture-LLM-must-not-render"
SECRET_GEMINI = "gem-fixture-must-not-render"


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    assigns = "\n".join(l for l in script.split("\n") if l.startswith("Object.assign(I18N."))
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return script, block, i18n + "\n" + assigns, helpers, tr


def static_checks(html, script, block):
    require("innerHTML" not in block and "document." not in block and "fetch(" not in block, "renderers must stay pure")
    require(not re.search(r"token|api_key|password|secret", block, re.I), "renderers must not reference secret fields")
    require("api('/api/factory/roles')" in script and "api('/api/factory/roles/assignment',{method:'POST'" in script,
            "UI must read and write the owner-only T-580 role API")
    require("+renderWorkerOperatorChip(roBoard,name)" in script and "renderWorkerOperatorDetail(roBoard,name)" in script,
            "office worker cards must show the current operator")
    require("renderWorkerOperatorChip(roBoard,a.name)" in script, "agent directory cards must show the current operator")
    require("(roBoard?renderRoleOperators(roBoard):'')" in script, "Workers page must include the role assignment panel")
    require('onchange="roAssign(this.dataset.roleAssign,this.value)"' in block, "role select must post the assignment")
    for word in ("publish", "deploy", "approve"):
        require(f"'{word}'" not in block, f"role UI must not offer {word}")
    keys = set(re.findall(r"tr\('(ro\.[a-zA-Z_.]*[a-zA-Z_])'", block)) | set(re.findall(r"tr\('(ro\.[a-zA-Z_.]*[a-zA-Z_])'", script))
    keys |= {f"ro.st.{s}" for s in ("online", "configured", "configured_unverified", "auth_pending", "offline", "policy", "unknown")}
    keys |= {f"ro.group.{g}" for g in ("content", "engineering")}
    for key in sorted(keys):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist in EN/UK/RU")
    return keys


def request():
    return Request({"type": "http", "headers": [], "method": "GET", "path": "/"})


def assign(role, operator):
    return app.factory_role_assignment(app.RoleAssignmentRequest(role=role, operator=operator), request())


def fixtures():
    """Real API boards for a deterministic sequence of owner assignment changes."""
    app.request_identity = lambda _r: {"role": "owner"}
    out = {"default": app.factory_roles(request())}
    out["content_claude"] = assign("scriptwriter", "claude")              # Content role -> Claude (runner offline)
    app.FACTORY_GEMINI_API_KEY = SECRET_GEMINI
    out["eng_gemini"] = assign("engineer", "gemini")                      # Engineering role -> Gemini (key, unprobed)
    app.FACTORY_LLM_API_KEY = SECRET_LLM
    app.claude_worker_runtime.update({"last_seen": app.time.time(), "node": {"auth_mode": "subscription"}})
    out["eng_claude_online"] = assign("engineer", "claude")               # Engineering role -> Claude (heartbeat)
    out["content_auto"] = assign("scriptwriter", "auto")                  # back to default
    hostile = json.loads(json.dumps(out["content_auto"]))
    hostile["roles"][0]["label"] = "<script>alert(1)</script>"
    out["hostile"] = hostile
    return out


HARNESS = r"""
let LANG='en';
%(helpers)s
%(i18n)s
%(tr)s
%(block)s
const fixtures=%(fixtures)s,workers=%(workers)s,out={};
for(const lang of ['en','uk','ru']){LANG=lang;for(const k of Object.keys(fixtures)){const b=fixtures[k];
 out[lang+':'+k]={panel:renderRoleOperators(b),chips:Object.fromEntries(workers.map(w=>[w,renderWorkerOperatorChip(b,w)])),
  detail:Object.fromEntries(workers.map(w=>[w,renderWorkerOperatorDetail(b,w)]))}}}
out.none={panel:renderRoleOperators(null),chip:renderWorkerOperatorChip(null,'Scout')};
process.stdout.write(JSON.stringify(out));
"""


def role_card(panel, role):
    m = re.search(r'<div class="roRole" data-role="%s".*?</select></label>.*?</div></div>' % role, panel)
    require(m is not None, f"role card {role} missing")
    return m.group(0)


def chip_op(chip):
    return re.search(r'data-worker-operator="([a-z]*)" data-operator-status="([a-z_]+)"', chip).groups()


def render_checks(out, fx):
    for key, r in out.items():
        if key == "none":
            continue
        blob = r["panel"] + "".join(r["chips"].values()) + "".join(r["detail"].values())
        require(SECRET_LLM not in blob and SECRET_GEMINI not in blob, f"secret rendered in {key}")
        require(not re.search(r"\bro\.[a-z]+(\.[a-z_]+)*\b", re.sub(r'class="[^"]*"', "", blob)), f"untranslated key in {key}")
        require(all(r["chips"][w] for w in app.AGENTS), f"every worker card needs an operator chip in {key}")
    require(out["none"] == {"panel": "", "chip": ""}, "no role board (e.g. non-owner) must render nothing")

    d = out["en:default"]
    require('data-panel="role-operators"' in d["panel"] and "Content roles" in d["panel"] and "Engineering roles" in d["panel"],
            "role panel groups missing")
    for rid in ("scout", "researcher", "scriptwriter", "reviewer", "qa", "engineer", "supervisor"):
        card = role_card(d["panel"], rid)
        require('data-assigned="auto" data-explicit="0"' in card and "Auto · default" in card, f"{rid} default must be Auto")
        require('<option value="auto" selected>' in card, f"{rid} select must show Auto selected")
    eng = role_card(d["panel"], "engineer")
    require('value="chatgpt"' not in eng and all(f'value="{o}"' in eng for o in ("claude", "gemini", "auto")),
            "Engineer select must offer only eligible operators")
    require('data-group="engineering"' in eng and "No pipeline worker yet" in eng, "engineer has no pipeline runtime")
    # nothing is configured: operators render as auth pending / offline, never as ready
    require('data-operator="chatgpt">ChatGPT <em class="roSt warn" data-operator-status="auth_pending">auth pending' in d["panel"],
            "ChatGPT auth pending missing")
    require('data-operator="claude">Claude <em class="roSt bad" data-operator-status="offline">offline' in d["panel"], "Claude offline missing")
    require('data-operator="gemini">Gemini <em class="roSt warn" data-operator-status="auth_pending">' in d["panel"], "Gemini auth pending missing")
    require('data-operator-status="online"' not in d["panel"] + "".join(d["chips"].values()), "nothing may render as online")
    require(chip_op(d["chips"]["Scriptwriter"]) == ("auto", "auth_pending") and "Auto → ChatGPT · auth pending" in d["chips"]["Scriptwriter"],
            "Auto worker chip must show the real runtime and its auth-pending state")
    require(chip_op(d["chips"]["Design Partner"]) == ("", "none") and "no assignable role" in d["chips"]["Design Partner"],
            "workers outside any role must say so")

    # Content role change: Scriptwriter -> Claude while the runner is offline
    c = out["en:content_claude"]
    sw = role_card(c["panel"], "scriptwriter")
    require('data-assigned="claude" data-explicit="1"' in sw and '<option value="claude" selected>' in sw, "Scriptwriter assignment not shown")
    require('data-current-operator="claude">Claude <em class="roSt bad" data-operator-status="offline">offline' in sw,
            "Scriptwriter must show Claude offline")
    require("Runs today on: ChatGPT" in sw and "assignment not enforced yet" in sw, "runtime truth must stay visible")
    for w in fx["content_claude"]["roles"][2]["workers"]:
        require(chip_op(c["chips"][w]) == ("claude", "offline") and "Claude · offline" in c["chips"][w], f"{w} card must show Claude offline")
    require("Scriptwriter → Claude · offline" in c["detail"]["Hook Generator"], "tooltip detail must show role → operator")
    require(chip_op(c["chips"]["Scout"]) == ("auto", "auth_pending"), "unrelated roles must stay unchanged")

    # Engineering role change: Engineer -> Gemini with key configured but never probed
    g = out["en:eng_gemini"]
    eng = role_card(g["panel"], "engineer")
    require('data-assigned="gemini"' in eng and '<option value="gemini" selected>' in eng, "Engineer -> Gemini not shown")
    require('data-operator-status="configured_unverified">configured · not verified' in eng, "Gemini must render as not verified")
    require('data-assigned="claude"' in role_card(g["panel"], "scriptwriter"), "earlier Content assignment must persist")

    # Engineer -> Claude with a live heartbeat; ChatGPT key configured
    o = out["en:eng_claude_online"]
    eng = role_card(o["panel"], "engineer")
    require('data-assigned="claude"' in eng and 'data-current-operator="claude">Claude <em class="roSt ok" data-operator-status="online">online' in eng,
            "Engineer must show Claude online only once the heartbeat is real")
    require('data-operator="chatgpt">ChatGPT <em class="roSt ok" data-operator-status="configured">key configured' in o["panel"],
            "ChatGPT configured key status missing")
    require(chip_op(o["chips"]["Supervisor"]) == ("auto", "policy"), "Auto without runtime stays a policy, not ready")

    a = out["en:content_auto"]
    sw = role_card(a["panel"], "scriptwriter")
    require('data-assigned="auto" data-explicit="0"' in sw, "reset to Auto not shown")
    require(chip_op(a["chips"]["Scriptwriter"]) == ("auto", "configured"), "Auto chip follows the real runtime status")

    h = out["en:hostile"]["panel"]
    require("<script>alert" not in h and "&lt;script&gt;alert(1)&lt;/script&gt;" in h, "role labels must be escaped")
    require("Контентні ролі" in out["uk:default"]["panel"] and "очікує авторизації" in out["uk:default"]["panel"], "UK labels missing")
    require("Инженерные роли" in out["ru:default"]["panel"] and "офлайн" in out["ru:content_claude"]["chips"]["Editor"], "RU labels missing")


def main():
    html = HTML.read_text(encoding="utf-8")
    script, block, i18n, helpers, tr = extract(html)
    keys = static_checks(html, script, block)
    print(f"Operator assignment UI static checks passed ({len(keys)} localized keys)")
    fx = fixtures()
    require(fx["content_auto"]["assignments"] == {"engineer": "claude"}, f"API state: {fx['content_auto']['assignments']}")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the fixture rendering check")
        print("SKIPPED fixture rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    program = HARNESS % {"helpers": helpers, "i18n": i18n, "tr": tr, "block": block,
                         "fixtures": json.dumps(fx), "workers": json.dumps(app.AGENTS)}
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"renderer harness failed:\n{result.stderr[-2000:]}")
    render_checks(json.loads(result.stdout), fx)
    print("Operator assignment UI fixture rendering passed (Content + Engineering changes, offline/auth-pending/unverified, EN/UK/RU)")


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
