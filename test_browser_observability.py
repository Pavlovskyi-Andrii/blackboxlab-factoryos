"""T-560-E Browser Runner observability regression.

Deterministic, no browser/network/provider. Covers:
- the read-only run view (browser_runner.observability) for done / waiting_human / blocked /
  executor-shaped runs: plan status, step progress, blocker/checkpoint, redacted action log,
  artifact refs, no credential/cookie/token values and no fabricated receipt;
- the API read model in app.py (record -> list by job -> single trace -> 404);
- the real inline dashboard renderers from static/index.html under Node (EN/UK/RU).
Node is required when FACTORYOS_REQUIRE_NODE=1 (CI); without it the rendering check is
reported as SKIPPED, never as passed.
"""
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

if not os.environ.get("DATA_DIR"):
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="factoryos-browser-obs-")
else:
    os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="browser-obs-", dir=os.environ["DATA_DIR"]) \
        if Path(os.environ["DATA_DIR"]).is_dir() else os.environ["DATA_DIR"]
os.environ["FACTORY_PASSWORD"] = ""
os.environ["FACTORY_LLM_API_KEY"] = ""

from browser_runner import (  # noqa: E402
    BrowserActionPlan, BrowserActionResult, CheckpointStore, InMemoryVault, SessionBinding,
    SessionRegistry, canonical_payload_hash, run_mock, run_mock_resumable,
)
from browser_runner.observability import build_run_view, safe_url, scrub_text  # noqa: E402

HTML = Path(__file__).resolve().parent / "static" / "index.html"
BEGIN = "// --- browser-run:begin"
END = "// --- browser-run:end"

PASSWORD = "S3cr3t-Pa55!word"
USERNAME = "owner-login-alias"
COOKIE = "sessid=abcdef0123456789abcdef0123456789"
TOKEN = "tok_" + "Z" * 40
CAPTION = "draft caption with a private note"
SECRETS = (PASSWORD, USERNAME, COOKIE, TOKEN, CAPTION, "abcdef0123456789abcdef0123456789", "vault://", "session://")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def no_secrets(obj, where):
    text = obj if isinstance(obj, str) else json.dumps(obj, default=str)
    for value in SECRETS:
        require(value not in text, f"secret-like value {value[:12]!r} leaked in {where}")


def plan(**kw):
    base = dict(
        plan_id="plan-obs-1", workspace_id="ws-a", provider="x", account_binding_id="acct-1",
        action_class="draft", session_ref="session://ws-a/x/acct-1",
        steps=(
            {"type": "navigate", "url": f"https://user:pw@x.example.com/compose?token={TOKEN}#frag"},
            {"type": "fill", "selector": "#caption", "value": CAPTION},
            {"type": "screenshot"},
        ),
    )
    base.update(kw)
    return BrowserActionPlan(**base)


# ---------------------------------------------------------------- view fixtures
def done_fixture():
    p = plan()
    return p, run_mock(p), None


def waiting_fixture(tmp):
    sessions = SessionRegistry(Path(tmp) / "sessions.json")
    checkpoints = CheckpointStore(Path(tmp) / "checkpoints.json")
    vault = InMemoryVault()
    vault.put("vault://ws-a/x/acct-1", workspace_id="ws-a", provider="x", account_binding_id="acct-1",
              values={"username": USERNAME, "password": PASSWORD})
    sessions.bind(SessionBinding("ws-a", "x", "acct-1", "session://ws-a/x/acct-1"))
    p = plan(plan_id="plan-obs-2", session_ref="", credential_ref="vault://ws-a/x/acct-1", steps=(
        {"type": "navigate", "url": "https://x.example.com/login"},
        {"type": "fill", "selector": "#user", "credential_field": "username"},
        {"type": "fill", "selector": "#pass", "credential_field": "password"},
        {"type": "click", "selector": "#login"},
    ))
    result = run_mock_resumable(p, sessions=sessions, checkpoints=checkpoints, vault=vault,
                                challenge_probe=lambda i, s: "2fa" if i == 4 else "")
    cp_id = next(e["checkpoint_id"] for e in result.action_log if e.get("type") == "checkpoint")
    return p, result, checkpoints.get(cp_id)


def blocked_fixture():
    p = plan(plan_id="plan-obs-3", action_class="publish", steps=(
        {"type": "navigate", "url": "https://x.example.com/compose"},
        {"type": "fill", "selector": "#caption", "value": CAPTION},
        {"type": "submit", "selector": "button.publish"},
    ))
    return p, run_mock(p), None


def executor_fixture():
    """Shaped like run_playwright output, plus hostile values a buggy adapter could emit."""
    p = plan(plan_id="plan-obs-4", provider="x<img src=x onerror=alert(1)>", steps=(
        {"type": "navigate", "url": "https://x.example.com/compose"},
        {"type": "extract", "selector": "#status"},
        {"type": "screenshot"},
        {"type": "upload", "selector": "input[type=file]", "file": "/srv/uploads/ws-a/clip.mp4"},
        {"type": "click", "selector": "#next"},
    ))
    result = BrowserActionResult(
        plan_id=p.plan_id, status="blocked", completed_steps=3, executor="playwright",
        final_url=f"https://x.example.com/compose?{COOKIE}",
        blocker_reason=f"request_blocked cookie: {COOKIE} Authorization: Bearer {TOKEN}",
        external_receipt="https://x.example.com/status/123",  # must not render: run did not finish
        artifacts=("artifact://browser/browser-0123abcd.png", "file:///etc/passwd"),
        action_log=(
            {"index": 1, "type": "navigate", "status": "done", "cookie": COOKIE},
            {"index": 2, "type": "extract", "status": "done", "text_chars": 42,
             "text_sha256": "a" * 64, "text": PASSWORD},
            {"index": 3, "type": "screenshot", "status": "done",
             "artifact_ref": "artifact://browser/browser-0123abcd.png"},
        ),
    )
    return p, result, None


def view_checks(tmp):
    views = {}

    p, r, cp = done_fixture()
    v = build_run_view(p, r, cp, started_at="2026-11-01T08:00:00Z", finished_at="2026-11-01T08:00:02Z")
    no_secrets(v, "done view")
    require(v["status"] == "done" and v["progress"] == {"completed": 3, "total": 3, "percent": 100}, "done progress wrong")
    require([s["state"] for s in v["steps"]] == ["simulated"] * 3, "done steps must reflect the action log")
    require(v["steps"][0]["target"] == "https://x.example.com/compose", "navigate target must drop userinfo/query/fragment")
    require(v["steps"][1]["value_chars"] == len(CAPTION) and "value" not in v["steps"][1], "fill value must be a char count")
    require(v["plan"]["site"] == "x.example.com" and v["plan"]["auth_kind"] == "session_ref", "plan site/auth wrong")
    require(v["plan"]["approval"] == {"required": False, "snapshot_id": "", "payload_hash_matches": False}, "draft approval wrong")
    require(v["receipt"] is None and v["receipt_observed"] is False, "mock run must not have a receipt")
    require(v["artifacts"] == [] and v["blocker"] is None and v["checkpoint"] is None, "done run invented evidence")
    require(all("input" not in e for e in v["action_log"]), "raw step input must not be logged")
    views["done"] = v

    p, r, cp = waiting_fixture(tmp)
    v = build_run_view(p, r, cp)
    no_secrets(v, "waiting view")
    require(v["status"] == "waiting_human" and v["progress"]["completed"] == 3, "waiting progress wrong")
    require([s["state"] for s in v["steps"]] == ["simulated", "simulated", "simulated", "stopped"], "stopped step wrong")
    require(v["steps"][1].get("uses_vault_credential") is True and "value_chars" not in v["steps"][1], "vault fill shape wrong")
    require(v["plan"]["auth_kind"] == "credential_ref", "credential ref must be shown by kind only")
    c = v["checkpoint"]
    require(c and c["checkpoint_id"] == cp.checkpoint_id and c["state"] == "waiting_human" and c["step_index"] == 4
            and c["step_type"] == "click" and c["reason"] == "2fa" and c["site"] == "x.example.com", f"checkpoint view wrong: {c}")
    require(v["blocker"] == {"reason": "2fa", "stopped_at_step": 4, "stopped_step_type": "click"}, "waiting blocker wrong")
    # Without the stored checkpoint the view falls back to the log entry.
    require(build_run_view(p, r)["checkpoint"]["checkpoint_id"] == cp.checkpoint_id, "checkpoint log fallback missing")
    views["waiting"] = v

    p, r, cp = blocked_fixture()
    v = build_run_view(p, r, cp)
    no_secrets(v, "blocked view")
    require(v["status"] == "blocked" and v["progress"]["completed"] == 0, "blocked progress wrong")
    require(v["steps"][0]["state"] == "stopped" and {s["state"] for s in v["steps"][1:]} == {"pending"}, "blocked steps wrong")
    require(v["plan"]["approval"]["required"] is True and v["plan"]["approval"]["payload_hash_matches"] is False,
            "publish without approval must show missing approval")
    require("approval" in v["blocker"]["reason"] and v["receipt"] is None, "blocked publish view wrong")
    approved = replace(p, approval_snapshot_id="approval-1", approved_payload_hash=canonical_payload_hash(p))
    va = build_run_view(approved, run_mock(approved))
    require(va["plan"]["approval"]["payload_hash_matches"] is True and va["plan"]["approval"]["snapshot_id"] == "approval-1",
            "matching approval must be shown")
    require(va["receipt"] is None, "simulated publish must not fabricate a receipt")
    views["blocked"] = v

    p, r, cp = executor_fixture()
    v = build_run_view(p, r, cp)
    no_secrets(v, "executor view")
    require(v["executor"] == "playwright" and v["progress"]["completed"] == 3, "executor view wrong")
    require([s["state"] for s in v["steps"]] == ["done", "done", "done", "stopped", "pending"], "executor step states wrong")
    require(v["steps"][1]["text_chars"] == 42 and v["steps"][1]["text_sha256"] == "a" * 64, "extract evidence missing")
    require(v["steps"][2]["artifact_ref"] == "artifact://browser/browser-0123abcd.png", "screenshot ref missing")
    require(v["steps"][3]["file"] == "clip.mp4", "upload must show basename only")
    require(v["artifacts"] == ["artifact://browser/browser-0123abcd.png"], "only private artifact refs may be listed")
    require(v["receipt"] is None and "receipt_ignored_status_not_done" in v["warnings"], "unfinished receipt must be ignored")
    require("artifact_refs_rejected" in v["warnings"], "rejected artifact ref must be flagged")
    require(v["final_url"] == "https://x.example.com/compose", "final URL must drop query")
    require("cookie" not in json.dumps(v["action_log"]) and all("text" not in e for e in v["action_log"]),
            "unknown log keys must not be copied")
    views["executor"] = v

    bad = BrowserActionResult(plan_id=p.plan_id, status="done", completed_steps=99, external_receipt="rcpt-1")
    vb = build_run_view(p, bad)
    require(vb["progress"]["completed"] == 5 and "completed_steps_out_of_range" in vb["warnings"], "out-of-range not flagged")
    require(vb["receipt"] == "rcpt-1", "receipt reported by a finished run should be shown as-is")
    try:
        build_run_view(p, BrowserActionResult(plan_id="other", status="done"))
        raise AssertionError("mismatched plan/result must be rejected")
    except ValueError:
        pass
    require(safe_url("javascript:alert(1)") == "" and safe_url("ftp://x") == "", "non-http URL must be dropped")
    require(PASSWORD not in scrub_text(f"password={PASSWORD}"), "scrub_text must hide key=value secrets")
    print(f"Browser run view checks passed ({len(views)} fixtures)")
    return views


# ---------------------------------------------------------------- API read model
def api_checks(tmp):
    import app

    def route_exists(path):
        return any(getattr(r, "path", None) == path and "GET" in (getattr(r, "methods", set()) or set()) for r in app.app.routes)

    require(route_exists("/api/browser-runs") and route_exists("/api/browser-runs/{artifact_id}"), "browser run routes missing")
    require("browser-runs" not in inspect.getsource(app.auth_middleware), "browser run API must stay behind authentication")
    job_id = "job-browser-obs"
    stored = {}
    for name, fixture in (("done", done_fixture()), ("waiting", waiting_fixture(tmp)),
                          ("blocked", blocked_fixture()), ("executor", executor_fixture())):
        stored[name] = app.record_browser_run(job_id, *fixture)
    runs = app.browser_runs(job_id)["runs"]
    require(len(runs) == 4 and {r["id"] for r in runs} == {s["id"] for s in stored.values()}, "job runs listing wrong")
    no_secrets(runs, "API listing")
    one = app.browser_run_trace(stored["waiting"]["id"])
    require(one["view"]["status"] == "waiting_human" and one["view"]["checkpoint"]["reason"] == "2fa", "single trace wrong")
    require(app.browser_runs("other-job")["runs"] == [], "runs must be scoped by job")
    try:
        app.browser_run_trace("missing")
        raise AssertionError("missing run must 404")
    except app.HTTPException as exc:
        require(exc.status_code == 404, "missing run must 404")
    # A non-browser artifact id must not be readable through this endpoint.
    other = app.save_artifact("Writer", "script", "not a browser run", {"plan": {}, "token": TOKEN}, job_id=job_id)
    try:
        app.browser_run_trace(other)
        raise AssertionError("non-browser artifact must not be served")
    except app.HTTPException:
        pass
    # Defence in depth: a stored row with secret-keyed fields is redacted on read.
    tampered = app.save_artifact(app.BROWSER_RUNNER_AGENT, app.BROWSER_RUN_KIND, "tampered",
                                 {"plan": {"plan_id": "p"}, "status": "done", "cookie": COOKIE, "api_key": TOKEN}, job_id=job_id)
    no_secrets(app.browser_run_trace(tampered), "tampered row")
    require("selectedJobBrowserRuns" in app.status(), "status must expose selectedJobBrowserRuns")
    print("Browser run API checks passed (record, list by job, trace, 404, kind scoping, redaction on read)")
    return [app.browser_run_trace(stored[n]["id"]) for n in ("done", "waiting", "blocked", "executor")]


# ---------------------------------------------------------------- dashboard renderers
def extract(html):
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    block = script.split(BEGIN, 1)[1].split("\n", 1)[1].split(END, 1)[0]
    i18n = script[script.index("const I18N="):script.index("const TASK_COPY=")]
    helpers = script[script.index("function textValue(v){"):]
    helpers = helpers[:helpers.index("\n", helpers.index("const esc="))]
    tr = re.search(r"^function tr\(key,vars=\{\}\)\{.*\}$", script, re.M).group(0)
    return script, block, i18n, helpers, tr


def static_checks(html, script, block):
    require('id="browserRuns"' in html, "Worker Results browser run strip missing")
    require("/api/browser-runs/" in script and "selectedJobBrowserRuns" in script, "dashboard must read the browser run API")
    require("innerHTML" not in block and "document." not in block and "fetch(" not in block, "renderers must stay pure")
    require(not re.search(r"password|cookie|token|secret", block, re.I), "renderers must not read secret fields")
    keys = set(re.findall(r"tr\('(brun\.[a-zA-Z_.]*[a-zA-Z_])'", block))
    keys |= {f"brun.state.{s}" for s in ("planned", "running", "waiting_human", "done", "blocked", "failed", "unknown")}
    keys |= {f"brun.step.{s}" for s in ("done", "simulated", "already_completed", "stopped", "running", "pending")}
    keys |= {f"brun.auth.{s}" for s in ("session_ref", "credential_ref", "none")}
    keys |= {f"brun.{s}" for s in ("plan", "steps", "blocker", "log", "artifacts", "evidence")}
    for key in sorted(keys):
        require(html.count(f'"{key}":') == 3, f"i18n key {key} must exist in EN/UK/RU")
    return keys


HARNESS = r"""
let LANG='en';
%(helpers)s
%(i18n)s
%(tr)s
%(block)s
const runs=%(runs)s,out={};
for(const lang of ['en','uk','ru']){LANG=lang;runs.forEach((r,i)=>{out[lang+':card:'+i]=renderBrowserRunCard(r);out[lang+':trace:'+i]=renderBrowserRun(r)})}
out['en:hostile-id']=renderBrowserRunCard({id:"x');alert(1);//",view:{}});
out['en:empty']=renderBrowserRun({});
process.stdout.write(JSON.stringify(out));
"""


def render_checks(out, runs):
    for key, html in out.items():
        no_secrets(html, key)
        require(not re.search(r"\bbrun\.[a-z_]+(\.[a-z_]+)*\b", html), f"untranslated key leaked in {key}")
        require("<img src=x" not in html, f"unescaped provider in {key}")
    done, waiting, blocked, executor = (out[f"en:trace:{i}"] for i in range(4))
    for i, run in enumerate(runs):
        card = out[f"en:card:{i}"]
        require(f'data-browser-run="{run["id"]}"' in card and f'data-status="{run["view"]["status"]}"' in card, f"card {i} wrong")
        for section in ("plan", "steps", "log", "artifacts", "evidence"):
            require(f'data-br-section="{section}"' in out[f"en:trace:{i}"], f"trace {i} missing {section}")
    require("3/3 steps" in done and "No external receipt observed" in done and 'data-br-section="blocker"' not in done, "done trace wrong")
    require(f"{len(CAPTION)} characters typed" in done and "not required for read/draft actions" in done, "done evidence wrong")
    require("No screenshot or artifact recorded." in done, "done run must not invent artifacts")
    require('data-br-checkpoint="1"' in waiting and "Waiting for human takeover" in waiting and "2fa" in waiting, "checkpoint missing")
    require('data-step-state="stopped"' in waiting and "step 4 (click)" in waiting, "stopped step missing")
    require("vault credential (value hidden)" in waiting and "opaque vault reference (value hidden)" in waiting, "vault display wrong")
    require("required — no matching approval snapshot" in blocked and 'data-br-section="blocker"' in blocked, "blocked trace wrong")
    require("artifact://browser/browser-0123abcd.png" in executor and "private reference, not published" in executor, "artifact ref missing")
    require("extracted 42 characters · sha256 aaaaaaaaaaaa…" in executor, "extract evidence missing")
    require('data-br-warnings="1"' in executor and "receipt_ignored_status_not_done" in executor, "integrity warnings missing")
    require("No external receipt observed" in executor and "/status/123" not in executor, "unfinished receipt rendered")
    require("file:///etc/passwd" not in executor, "non-private artifact ref rendered")
    require("data-browser-run" not in out["en:hostile-id"] and "alert(1)" not in out["en:hostile-id"], "hostile id must not be clickable")
    require('data-status="unknown"' in out["en:empty"], "empty view must render as unknown")
    require("Очікує втручання людини" in out["uk:trace:1"] and "Ожидает вмешательства человека" in out["ru:trace:1"], "UK/RU missing")


def ui_checks(runs):
    html = HTML.read_text(encoding="utf-8")
    script, block, i18n, helpers, tr = extract(html)
    keys = static_checks(html, script, block)
    print(f"Browser run dashboard static checks passed ({len(keys)} localized keys)")
    node = shutil.which("node")
    if not node:
        if os.environ.get("FACTORYOS_REQUIRE_NODE") == "1":
            raise SystemExit("node is required for the fixture rendering check")
        print("SKIPPED fixture rendering check: node is not installed (CI runs it with FACTORYOS_REQUIRE_NODE=1)")
        return
    program = HARNESS % {"helpers": helpers, "i18n": i18n, "tr": tr, "block": block, "runs": json.dumps(runs)}
    result = subprocess.run([node, "-"], input=program, capture_output=True, text=True, timeout=60)
    if result.returncode:
        raise SystemExit(f"renderer harness failed:\n{result.stderr[-2000:]}")
    render_checks(json.loads(result.stdout), runs)
    print("Browser run fixture rendering passed (status, progress, checkpoint, redacted log, artifacts, no receipt, EN/UK/RU)")


def main():
    with tempfile.TemporaryDirectory() as tmp:
        view_checks(tmp)
        runs = api_checks(tmp)
    ui_checks(runs)


if __name__ == "__main__":
    try:
        main()
    except AssertionError as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
