import asyncio
import json
import sqlite3
import uuid
import os
import hmac
import hashlib
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factory.db"
STAGES = ["inbox","research","script","visual","voice","render","qa","publish","analytics"]
AGENT_MAP = {
    "research": ["Scout","Researcher","Tech Verifier"],
    "script": ["Hook Writer","Scriptwriter"],
    "visual": ["Visual Director"],
    "voice": ["Voice Agent"],
    "render": ["Render Agent"],
    "qa": ["QA Agent"],
    "publish": ["Publisher"],
    "analytics": ["Analyst"],
}
AGENTS = [a for stage in STAGES for a in AGENT_MAP.get(stage, [])] + ["Supervisor"]

AGENT_SPECS = {
    "Scout": {"stage":"research","role":"Trend & topic scout","goal":"Find timely, high-potential content opportunities and useful source leads."},
    "Researcher": {"stage":"research","role":"Research analyst","goal":"Build a reliable evidence pack, key facts, angles and source notes."},
    "Tech Verifier": {"stage":"research","role":"Technical verifier","goal":"Challenge claims, flag uncertainty and verify technical plausibility."},
    "Hook Writer": {"stage":"script","role":"Hook specialist","goal":"Create opening hooks and retention beats that earn the next second of attention."},
    "Scriptwriter": {"stage":"script","role":"Long-form scriptwriter","goal":"Turn verified research into a clear, engaging narrative."},
    "Visual Director": {"stage":"visual","role":"Visual director","goal":"Translate the script into shots, screen recordings, graphics and image prompts."},
    "Voice Agent": {"stage":"voice","role":"Voice producer","goal":"Prepare narration, delivery notes and final voice assets."},
    "Render Agent": {"stage":"render","role":"Video producer","goal":"Assemble scenes, captions, timing and final video renders."},
    "QA Agent": {"stage":"qa","role":"Quality controller","goal":"Check factual consistency, completeness, output readiness and policy risks."},
    "Publisher": {"stage":"publish","role":"Distribution manager","goal":"Package and schedule platform-specific publishing assets."},
    "Analyst": {"stage":"analytics","role":"Performance analyst","goal":"Turn performance data into concrete recommendations for the next production cycle."},
    "Supervisor": {"stage":"supervision","role":"Factory supervisor","goal":"Monitor every agent, detect failures, auto-heal safe issues and continuously improve the process."},
}

app = FastAPI(title="Blackbox Lab FactoryOS v3")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

FACTORY_USER = os.environ.get("FACTORY_USER", "blackboxlab")
FACTORY_PASSWORD = os.environ.get("FACTORY_PASSWORD", "")
FACTORY_SECRET = os.environ.get("FACTORY_SECRET", secrets.token_hex(32))
COOKIE_NAME = "factoryos_session"

def session_token(username: str) -> str:
    return hmac.new(
        FACTORY_SECRET.encode("utf-8"),
        username.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

def request_is_authed(request: Request) -> bool:
    if not FACTORY_PASSWORD:
        return True
    token = request.cookies.get(COOKIE_NAME, "")
    return hmac.compare_digest(token, session_token(FACTORY_USER))

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = {"/login", "/health"}
    if request.url.path.startswith("/static/") or request.url.path in public_paths:
        return await call_next(request)
    if not request_is_authed(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "authentication required"}, status_code=401)
        return RedirectResponse("/login", status_code=303)
    return await call_next(request)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if request_is_authed(request):
        return RedirectResponse("/", status_code=303)
    return HTMLResponse("""<!doctype html><html><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>Blackbox Lab — FactoryOS Login</title>
    <style>
    body{margin:0;min-height:100vh;display:grid;place-items:center;background:#07101b;color:#fff;font:14px Inter,system-ui,Arial}
    .box{width:min(390px,90vw);background:#0d1827;border:1px solid #20354e;border-radius:18px;padding:26px;box-shadow:0 20px 70px #0008}
    h1{margin:0 0 6px;font-size:24px}.sub{color:#7f93ac;margin-bottom:18px}
    input{width:100%;box-sizing:border-box;margin:7px 0;padding:12px;background:#07111d;color:#fff;border:1px solid #20354e;border-radius:10px}
    button{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#1677ff,#0db7f5);color:#fff;font-weight:800;cursor:pointer}
    .cube{width:42px;height:42px;border:2px solid #16bdf6;transform:rotate(30deg);border-radius:7px;margin-bottom:18px;box-shadow:0 0 24px #16bdf655}
    </style></head><body><form class='box' method='post' action='/login'>
    <div class='cube'></div><h1>Blackbox Lab — FactoryOS</h1><div class='sub'>Private AI content production control room</div>
    <input name='username' placeholder='Username' autocomplete='username' required>
    <input name='password' type='password' placeholder='Password' autocomplete='current-password' required>
    <button type='submit'>Enter FactoryOS</button></form></body></html>""")

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...)):
    if not (hmac.compare_digest(username, FACTORY_USER) and hmac.compare_digest(password, FACTORY_PASSWORD)):
        return HTMLResponse("Invalid username or password. <a href='/login'>Try again</a>", status_code=401)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        COOKIE_NAME,
        session_token(FACTORY_USER),
        httponly=True,
        secure=bool(os.environ.get("RENDER")),
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response

@app.post("/logout")
def logout():
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(COOKIE_NAME)
    return response

@app.get("/health")
def health():
    return {"ok": True, "service": "factoryos"}

clients: set[WebSocket] = set()
running_jobs: set[str] = set()
selected_job_id: Optional[str] = None
agent_runtime = {name: "idle" for name in AGENTS}
supervisor_runtime = {
    "state": "monitoring",
    "last_run": None,
    "last_report": None,
    "last_signature": None,
    "auto_heal": True,
}

# Local MVP knows only what was verified during setup. Standalone server cannot reuse ChatGPT plugin auth.
CONNECTIONS = {
    "Metricool": {"state":"connected","detail":"Brand connected"},
    "YouTube": {"state":"connected","detail":"Connected in Metricool"},
    "Instagram": {"state":"connected","detail":"Connected in Metricool"},
    "TikTok": {"state":"connected","detail":"@blackboxlab"},
    "vidIQ": {"state":"paused","detail":"Paused for now"},
    "LLM": {"state":"demo","detail":"Agents are simulated in v3"},
    "Voice": {"state":"not_configured","detail":"Provider not selected"},
    "Video": {"state":"not_configured","detail":"Provider not selected"},
}

def ts(): return datetime.now(timezone.utc).isoformat()

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS jobs(
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      brief TEXT DEFAULT '',
      stage TEXT NOT NULL DEFAULT 'inbox',
      presenter TEXT DEFAULT 'AI presenter',
      format TEXT DEFAULT 'Long + Shorts',
      language TEXT DEFAULT 'English',
      outputs INTEGER DEFAULT 8,
      status TEXT DEFAULT 'idle',
      progress INTEGER DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      job_id TEXT,
      ts TEXT NOT NULL,
      message TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS supervisor_reports(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      ts TEXT NOT NULL,
      score INTEGER NOT NULL,
      critical_count INTEGER NOT NULL,
      warning_count INTEGER NOT NULL,
      report_json TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS agent_runs(
      id TEXT PRIMARY KEY,
      job_id TEXT,
      agent TEXT NOT NULL,
      stage TEXT,
      status TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      duration_ms INTEGER DEFAULT 0,
      model TEXT DEFAULT 'simulation',
      input_tokens INTEGER DEFAULT 0,
      output_tokens INTEGER DEFAULT 0,
      cost_usd REAL DEFAULT 0,
      error TEXT,
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_agent_runs_agent ON agent_runs(agent, started_at DESC);
    CREATE INDEX IF NOT EXISTS idx_agent_runs_job ON agent_runs(job_id, started_at DESC);
    CREATE TABLE IF NOT EXISTS artifacts(
      id TEXT PRIMARY KEY,
      run_id TEXT,
      job_id TEXT,
      agent TEXT NOT NULL,
      kind TEXT NOT NULL,
      title TEXT NOT NULL,
      content TEXT DEFAULT '',
      url TEXT,
      mime_type TEXT,
      created_at TEXT NOT NULL,
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_artifacts_agent ON artifacts(agent, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_artifacts_job ON artifacts(job_id, created_at DESC);
    """)
    n = con.execute("SELECT COUNT(*) c FROM jobs").fetchone()["c"]
    if n == 0:
        seeds = [
            ("NSA released Ghidra for free","Explain Ghidra and reverse engineering with a clear demo","research","AI presenter","Long + Shorts","English",8),
            ("Can AI understand firmware?","Show what AI can infer from firmware and where it fails","inbox","Faceless","Short only","English",3),
        ]
        for s in seeds:
            jid = str(uuid.uuid4())
            stage=s[2]; p=int(STAGES.index(stage)/(len(STAGES)-1)*100)
            con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (jid,s[0],s[1],stage,s[3],s[4],s[5],s[6],"idle",p,ts(),ts()))
            con.execute("INSERT INTO events(job_id,ts,message) VALUES(?,?,?)",(jid,ts(),f"Created: {s[0]}"))
    con.commit(); con.close()

init_db()

class JobCreate(BaseModel):
    title: str
    brief: str = ""
    presenter: str = "AI presenter"
    format: str = "Long + Shorts"
    language: str = "English"
    outputs: int = 8

class Move(BaseModel): stage: str

def event(job_id, message):
    con=db(); con.execute("INSERT INTO events(job_id,ts,message) VALUES(?,?,?)",(job_id,ts(),message)); con.commit(); con.close()

def job_dict(r): return dict(r) if r else None

def get_jobs():
    con=db(); rows=con.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall(); con.close(); return [dict(x) for x in rows]

def get_job(job_id):
    con=db(); row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone(); con.close()
    return dict(row) if row else None

def start_agent_run(agent, job_id=None, stage=None, model="simulation-v3"):
    run_id=str(uuid.uuid4())
    con=db()
    con.execute("""INSERT INTO agent_runs(id,job_id,agent,stage,status,started_at,model)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id,job_id,agent,stage,"running",ts(),model))
    con.commit(); con.close()
    return run_id

def finish_agent_run(run_id, status="completed", input_tokens=0, output_tokens=0, cost_usd=0.0, error=None, meta=None):
    con=db(); row=con.execute("SELECT started_at FROM agent_runs WHERE id=?",(run_id,)).fetchone()
    finished=ts()
    duration_ms=0
    if row:
        duration_ms=max(0,int((datetime.fromisoformat(finished)-datetime.fromisoformat(row["started_at"])).total_seconds()*1000))
    con.execute("""UPDATE agent_runs SET status=?,finished_at=?,duration_ms=?,input_tokens=?,output_tokens=?,cost_usd=?,error=?,meta_json=?
                   WHERE id=?""",
                (status,finished,duration_ms,int(input_tokens or 0),int(output_tokens or 0),float(cost_usd or 0),error,json.dumps(meta or {}),run_id))
    con.commit(); con.close()
    return duration_ms

def save_artifact(agent, kind, title, content="", job_id=None, run_id=None, url=None, mime_type=None, meta=None):
    artifact_id=str(uuid.uuid4())
    con=db()
    con.execute("""INSERT INTO artifacts(id,run_id,job_id,agent,kind,title,content,url,mime_type,created_at,meta_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id,run_id,job_id,agent,kind,title,content,url,mime_type,ts(),json.dumps(meta or {})))
    con.commit(); con.close()
    return artifact_id

def agent_artifact_template(agent, job):
    title=job["title"] if job else "FactoryOS"
    brief=(job or {}).get("brief","")
    templates={
        "Scout": ("analysis","Opportunity scan",f"DEMO OUTPUT — Topic: {title}\n\nSignals checked: searchability, novelty, visual potential, audience curiosity.\nPrimary angle: explain what looks like a black box and show the mechanism clearly.\nNext handoff: Researcher should validate claims and gather primary-source evidence."),
        "Researcher": ("research","Research brief",f"DEMO OUTPUT — Research pack for: {title}\n\nWorking brief: {brief or 'No brief supplied.'}\nEvidence plan: official docs / repositories / primary sources first, then credible secondary context.\nOpen questions: what can be demonstrated safely, what needs qualification, and what visual proof will make the explanation believable."),
        "Tech Verifier": ("analysis","Technical verification",f"DEMO OUTPUT — Verification pass for: {title}\n\nChecks: terminology, architecture assumptions, cause/effect claims, demo feasibility.\nResult: no real external verification has run yet because the LLM/research provider is still in demo mode. Treat generated claims as placeholders until a live verifier is connected."),
        "Hook Writer": ("text","Hook candidates",f"DEMO OUTPUT — Hooks for: {title}\n\n1. “This tool lets you look inside software you were never given the source code for.”\n2. “A government-grade reverse-engineering tool is free — but what can it actually see?”\n3. “I gave a black box to an AI-assisted reverse-engineering workflow. Here is what came back.”"),
        "Scriptwriter": ("text","Draft script",f"DEMO OUTPUT — Script skeleton for: {title}\n\nHOOK → why the viewer should care\nCONTEXT → what the technology is\nDEMO → show one concrete transformation or discovery\nLIMITS → what the tool cannot know\nPAYOFF → what this means for developers / security / hardware people\nCTA → next experiment."),
        "Visual Director": ("image","Storyboard / visual plan",f"DEMO OUTPUT — Visual plan for: {title}\n\nShots: macro hardware / terminal / Ghidra UI / animated data flow / presenter inserts.\nVisual rule: every abstract claim should get an on-screen proof or diagram.\nImage preview below is the current FactoryOS office concept.",url="/static/office_scene.svg",mime_type="image/svg+xml"),
        "Voice Agent": ("audio","Narration plan",f"DEMO OUTPUT — Voice plan for: {title}\n\nLanguage: {(job or {}).get('language','English')}\nDelivery: concise, confident, curious; short clauses for Shorts, slower explanatory cadence for long-form.\nNo real audio file yet — voice provider is not configured."),
        "Render Agent": ("video","Render manifest",f"DEMO OUTPUT — Render manifest for: {title}\n\nTarget: 16:9 long video + vertical cut-downs.\nCaptions: burned-in for short-form.\nStatus: no real video asset yet — video provider is not configured."),
        "QA Agent": ("analysis","QA report",f"DEMO OUTPUT — QA checklist for: {title}\n\n✓ stage completeness checked\n✓ human approval gate preserved\n⚠ factual/source validation is still demo-only\n⚠ voice/video providers are not configured\nRecommendation: do not auto-publish until live artifact validation is enabled."),
        "Publisher": ("text","Publishing package",f"DEMO OUTPUT — Publishing package for: {title}\n\nYouTube: title + description + chapters + thumbnail brief\nTikTok/Reels: compact caption + 3–5 topic-specific hashtags\nPublishing remains approval-gated."),
        "Analyst": ("analysis","Performance learning brief",f"DEMO OUTPUT — Analytics plan for: {title}\n\nTrack: hook hold, 30-second retention, average percentage viewed, CTR, comments per 1k views, saves/shares.\nFeedback loop: promote winning hook/angle patterns back to Scout and Hook Writer."),
        "Supervisor": ("analysis","Factory audit","Factory Supervisor audit: runtime health, connection readiness, stalled work, cost/time signals and process-improvement backlog."),
    }
    return templates.get(agent,("text","Agent output",f"DEMO OUTPUT for {title}"))

def get_agent_metrics(agent):
    con=db()
    row=con.execute("""SELECT COUNT(*) runs,
                              COALESCE(SUM(duration_ms),0) duration_ms,
                              COALESCE(AVG(duration_ms),0) avg_duration_ms,
                              COALESCE(SUM(input_tokens),0) input_tokens,
                              COALESCE(SUM(output_tokens),0) output_tokens,
                              COALESCE(SUM(cost_usd),0) cost_usd,
                              COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed_runs,
                              COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) failed_runs,
                              MAX(finished_at) last_run
                       FROM agent_runs WHERE agent=?""",(agent,)).fetchone()
    art=con.execute("SELECT COUNT(*) c FROM artifacts WHERE agent=?",(agent,)).fetchone()["c"]
    con.close()
    data=dict(row); data["artifacts"]=art
    data["success_rate"]=round((data["completed_runs"]/data["runs"]*100),1) if data["runs"] else 0
    return data

def get_usage_summary():
    con=db()
    row=con.execute("""SELECT COUNT(*) runs,
                              COALESCE(SUM(duration_ms),0) duration_ms,
                              COALESCE(SUM(input_tokens),0) input_tokens,
                              COALESCE(SUM(output_tokens),0) output_tokens,
                              COALESCE(SUM(cost_usd),0) cost_usd
                       FROM agent_runs""").fetchone()
    con.close()
    return dict(row)

def backfill_legacy_history():
    """Convert old demo completion events into ledger entries once, so existing jobs have visible history."""
    con=db()
    existing=con.execute("SELECT COUNT(*) c FROM agent_runs WHERE agent!='Supervisor'").fetchone()["c"]
    if existing:
        con.close()
        return 0
    rows=con.execute("""SELECT e.job_id,e.ts,e.message,j.stage,j.title
                        FROM events e LEFT JOIN jobs j ON j.id=e.job_id
                        WHERE e.message LIKE '%: completed'
                        ORDER BY e.id""").fetchall()
    created=0
    for row in rows:
        agent=row["message"][:-len(": completed")]
        if agent not in AGENTS or agent=="Supervisor":
            continue
        run_id=str(uuid.uuid4())
        stage=AGENT_SPECS.get(agent,{}).get("stage") or row["stage"]
        con.execute("""INSERT INTO agent_runs(id,job_id,agent,stage,status,started_at,finished_at,duration_ms,model,input_tokens,output_tokens,cost_usd,meta_json)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (run_id,row["job_id"],agent,stage,"completed",row["ts"],row["ts"],0,"legacy-demo",0,0,0.0,json.dumps({"mode":"legacy-demo","backfilled":True})))
        job=con.execute("SELECT * FROM jobs WHERE id=?",(row["job_id"],)).fetchone()
        if job:
            kind,title,content,*extra=agent_artifact_template(agent,dict(job))
            url=extra[0] if len(extra)>0 else None
            mime=extra[1] if len(extra)>1 else None
            con.execute("""INSERT INTO artifacts(id,run_id,job_id,agent,kind,title,content,url,mime_type,created_at,meta_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()),run_id,row["job_id"],agent,kind,title,content,url,mime,row["ts"],json.dumps({"mode":"legacy-demo","backfilled":True})))
        created+=1
    con.commit(); con.close()
    return created

def validate_stage_outputs(job_id, stage):
    expected=AGENT_MAP.get(stage,[])
    if not expected:
        return {"ok":True,"expected":0,"ready":0,"missing":[]}
    con=db()
    missing=[]
    ready=0
    for agent in expected:
        run=con.execute("""SELECT id,status FROM agent_runs
                           WHERE job_id=? AND agent=? AND stage=?
                           ORDER BY started_at DESC LIMIT 1""",(job_id,agent,stage)).fetchone()
        artifact_count=0
        if run:
            artifact_count=con.execute("SELECT COUNT(*) c FROM artifacts WHERE run_id=?",(run["id"],)).fetchone()["c"]
        if run and run["status"]=="completed" and artifact_count>0:
            ready+=1
        else:
            missing.append(agent)
    con.close()
    return {"ok":not missing,"expected":len(expected),"ready":ready,"missing":missing}

async def execute_agent(agent, stage, job_id, delay=1.1):
    job=get_job(job_id)
    run_id=start_agent_run(agent,job_id,stage)
    agent_runtime[agent]="working"
    event(job_id,f"{agent}: working")
    await broadcast({"type":"agent","agent":agent,"state":"working"})
    try:
        await asyncio.sleep(delay)
        kind,title,content,*extra=agent_artifact_template(agent,job)
        kwargs={}
        if extra:
            if len(extra)>0: kwargs["url"]=extra[0]
            if len(extra)>1: kwargs["mime_type"]=extra[1]
        save_artifact(agent,kind,title,content,job_id=job_id,run_id=run_id,meta={"mode":"demo","stage":stage},**kwargs)
        finish_agent_run(run_id,status="completed",meta={"mode":"demo","note":"No paid model call was made."})
        agent_runtime[agent]="done"
        event(job_id,f"{agent}: completed")
        await broadcast({"type":"agent","agent":agent,"state":"done"})
    except Exception as exc:
        finish_agent_run(run_id,status="failed",error=str(exc),meta={"mode":"demo"})
        agent_runtime[agent]="failed"
        event(job_id,f"{agent}: failed — {exc}")
        await broadcast({"type":"agent","agent":agent,"state":"failed"})
        raise

def current_selected(jobs):
    global selected_job_id
    if selected_job_id and any(j["id"]==selected_job_id for j in jobs): return selected_job_id
    selected_job_id = jobs[0]["id"] if jobs else None
    return selected_job_id

def agent_states(jobs):
    states = {a:"idle" for a in AGENTS}
    # last status wins, but running has priority
    for j in jobs:
        idx = STAGES.index(j["stage"])
        if j["status"] == "done":
            for st in STAGES[1:]:
                for a in AGENT_MAP.get(st,[]): states[a]="done"
            continue
        for st_i, st in enumerate(STAGES[1:], start=1):
            for a in AGENT_MAP.get(st,[]):
                if st_i < idx: states[a]="done"
                elif st_i == idx:
                    if j["status"] == "running": states[a]="working"
                    elif j["status"] == "waiting_approval": states[a]="waiting"
    # runtime event state can show a currently active agent more precisely
    for a,s in agent_runtime.items():
        if s in ("working","done","failed"):
            states[a]=s
    states["Supervisor"] = supervisor_runtime.get("state", "monitoring")
    return states

def next_action(job):
    if not job: return "Create your first job."
    if job["status"] == "waiting_approval": return "Review the output, then click Approve & Publish."
    if job["status"] == "running": return f"Factory is working on {job['stage']}."
    if job["status"] == "done": return "Review analytics or create the next job."
    if job["status"] == "failed": return "Open the failed agent history, inspect the error, then retry the job."
    if job["stage"] == "inbox": return "Click Run Factory to start research."
    return "Click Run Factory to continue from this stage."

def _parse_dt(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return datetime.now(timezone.utc)

def supervisor_audit(auto_heal=False, persist=False):
    jobs = get_jobs()
    findings = []
    healed = []
    improvements = []
    now_dt = datetime.now(timezone.utc)

    def add(severity, code, title, detail, recommendation):
        findings.append({
            "severity": severity,
            "code": code,
            "title": title,
            "detail": detail,
            "recommendation": recommendation,
        })

    # Production-readiness checks.
    if CONNECTIONS.get("LLM", {}).get("state") == "demo":
        add("critical", "llm_demo", "Agents are still simulated",
            "Research, writing and verification agents currently simulate work instead of producing real artifacts.",
            "Connect a real LLM provider and require every agent to save an output artifact before the next stage.")
        improvements.append("Replace simulated Research/Script agents with a real LLM adapter and artifact validation.")

    for name in ("Voice", "Video"):
        if CONNECTIONS.get(name, {}).get("state") == "not_configured":
            add("warning", f"{name.lower()}_missing", f"{name} provider is not configured",
                f"The pipeline can reach the {name.lower()} stage but cannot produce a real {name.lower()} asset yet.",
                f"Choose and connect a {name.lower()} provider before enabling unattended publishing.")

    if CONNECTIONS.get("vidIQ", {}).get("state") == "paused":
        add("info", "vidiq_paused", "vidIQ is paused",
            "Keyword intelligence is not feeding the Scout or Analyst yet.",
            "Keep it paused for now or reconnect later when we automate topic selection.")

    # Runtime health and safe self-healing.
    for j in jobs:
        age = (now_dt - _parse_dt(j["updated_at"])).total_seconds()
        expected = int(STAGES.index(j["stage"]) / (len(STAGES) - 1) * 100)

        if j["status"] == "failed":
            add("critical", "failed_job", f"Failed job: {j['title']}",
                "A pipeline stage raised an exception and the job is paused.",
                "Open the responsible agent ledger, inspect the error, then retry from the current stage.")

        if j["status"] == "running" and j["id"] not in running_jobs:
            add("critical", "orphan_job", f"Orphaned running job: {j['title']}",
                "The database says the job is running, but no worker task owns it.",
                "Reset it to ready and restart from the current stage.")
            if auto_heal:
                con = db()
                con.execute("UPDATE jobs SET status='idle',updated_at=? WHERE id=?", (ts(), j["id"]))
                con.commit(); con.close()
                event(j["id"], "Supervisor auto-heal: orphaned run reset to ready")
                healed.append(f"Reset orphaned job '{j['title']}' to ready.")

        if j["status"] == "running" and age > 180:
            add("critical", "stuck_job", f"Possible stalled job: {j['title']}",
                f"No job update has been recorded for {int(age)} seconds.",
                "Stop the stalled stage, capture the error, and retry with a bounded retry policy.")

        if j["status"] == "waiting_approval" and age > 1800:
            add("warning", "approval_wait", f"Approval waiting: {j['title']}",
                "This job has been waiting for human review for more than 30 minutes.",
                "Surface the review task more prominently or send a notification.")

        if j["status"] not in ("waiting_approval", "done") and abs(j["progress"] - expected) > 20:
            add("warning", "progress_mismatch", f"Progress mismatch: {j['title']}",
                f"Stage {j['stage']} and stored progress {j['progress']}% disagree.",
                "Calculate progress from completed stage artifacts instead of storing it independently.")

    # Reset impossible agent runtime states.
    if not running_jobs:
        stale_agents = [a for a, state in agent_runtime.items() if state == "working" and a != "Supervisor"]
        if stale_agents:
            add("warning", "orphan_agents", "Agents marked working with no active job",
                ", ".join(stale_agents),
                "Reset stale runtime states and tie agent state to a job execution id.")
            if auto_heal:
                for a in stale_agents:
                    agent_runtime[a] = "idle"
                healed.append("Reset stale agent runtime states.")

    # Process-improvement advice: always keep a small prioritized backlog.
    if not any(x["code"] == "llm_demo" for x in findings):
        improvements.append("Add per-agent artifact schemas so Supervisor can validate output quality, not only runtime state.")
    improvements.extend([
        "Add retry limits + timeout per agent, with failure reason stored in the job log.",
        "Measure duration, cost and success rate per stage; Supervisor should optimize the slowest/most expensive stage.",
        "Before Publish, require QA checks for factual support, duplicate content, title/thumbnail fit and platform policy.",
    ])
    improvements = improvements[:4]

    penalties = {"critical": 24, "warning": 9, "info": 2}
    score = max(0, 100 - sum(penalties.get(x["severity"], 0) for x in findings))
    critical_count = sum(1 for x in findings if x["severity"] == "critical")
    warning_count = sum(1 for x in findings if x["severity"] == "warning")
    state = "attention" if critical_count else ("watch" if warning_count else "healthy")
    report = {
        "score": score,
        "state": state,
        "findings": findings,
        "improvements": improvements,
        "healed": healed,
        "checked_at": ts(),
        "auto_heal": bool(supervisor_runtime.get("auto_heal", True)),
        "summary": (
            "Critical intervention required" if critical_count
            else "Factory is stable, with improvements available" if warning_count
            else "Factory health looks good"
        ),
    }
    if persist:
        con = db()
        con.execute(
            "INSERT INTO supervisor_reports(ts,score,critical_count,warning_count,report_json) VALUES(?,?,?,?,?)",
            (report["checked_at"], score, critical_count, warning_count, json.dumps(report)),
        )
        con.commit(); con.close()
    return report

async def supervisor_cycle():
    supervisor_runtime["state"] = "working"
    agent_runtime["Supervisor"] = "working"
    started=ts()
    try:
        report = supervisor_audit(auto_heal=supervisor_runtime["auto_heal"], persist=False)
        supervisor_runtime["last_report"] = report
        supervisor_runtime["last_run"] = report["checked_at"]
        signature=json.dumps({
            "score":report.get("score"),
            "codes":[x.get("code") for x in report.get("findings",[])],
            "healed":report.get("healed",[]),
        },sort_keys=True)
        # Persist Supervisor work only when the health picture changes, avoiding ledger spam every cycle.
        if signature != supervisor_runtime.get("last_signature"):
            run_id=start_agent_run("Supervisor",None,"supervision",model="rules-engine")
            con=db()
            con.execute(
                "INSERT INTO supervisor_reports(ts,score,critical_count,warning_count,report_json) VALUES(?,?,?,?,?)",
                (report["checked_at"],report["score"],
                 sum(1 for x in report["findings"] if x["severity"]=="critical"),
                 sum(1 for x in report["findings"] if x["severity"]=="warning"),
                 json.dumps(report))
            )
            con.commit(); con.close()
            content=json.dumps(report,indent=2)
            save_artifact("Supervisor","analysis","Factory health audit",content,run_id=run_id,meta={"mode":"rules-engine"})
            finish_agent_run(run_id,status="completed",meta={"mode":"rules-engine","started_cycle":started})
            supervisor_runtime["last_signature"]=signature
    except Exception as exc:
        supervisor_runtime["last_report"] = {
            "score": 0, "state": "attention", "findings": [{
                "severity": "critical", "code": "supervisor_error", "title": "Supervisor audit failed",
                "detail": str(exc), "recommendation": "Inspect the server log and fix the audit exception."
            }], "improvements": [], "healed": [], "checked_at": ts(), "auto_heal": True,
            "summary": "Supervisor encountered an internal error"
        }
    finally:
        supervisor_runtime["state"] = "monitoring"
        agent_runtime["Supervisor"] = "monitoring"
        await broadcast({"type": "supervisor"})

async def supervisor_loop():
    while True:
        await supervisor_cycle()
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_supervisor():
    backfilled=backfill_legacy_history()
    if backfilled:
        event(None,f"Ledger migration: backfilled {backfilled} historical agent runs")
    asyncio.create_task(supervisor_loop())

async def broadcast(payload=None):
    dead=[]; msg=json.dumps(payload or {"type":"refresh"})
    for ws in list(clients):
        try: await ws.send_text(msg)
        except Exception: dead.append(ws)
    for ws in dead: clients.discard(ws)

@app.get("/")
def root(): return FileResponse(BASE/"static"/"index.html")

@app.get("/api/status")
def status():
    jobs=get_jobs(); sid=current_selected(jobs); selected=next((j for j in jobs if j["id"]==sid),None)
    con=db(); ev=[dict(x) for x in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 60").fetchall()]; con.close()
    report = supervisor_runtime.get("last_report") or supervisor_audit(auto_heal=False, persist=False)
    return {
        "factory":"online","jobs":jobs,"selectedJobId":sid,"selectedJob":selected,
        "events":ev,"connections":CONNECTIONS,"stages":STAGES,
        "agentStates":agent_states(jobs),"agentMap":AGENT_MAP,
        "runningJobs":list(running_jobs),"nextAction":next_action(selected),
        "supervisor": report,
        "supervisorState": supervisor_runtime.get("state", "monitoring"),
        "usage": get_usage_summary(),
        "agentMetrics": {a:get_agent_metrics(a) for a in AGENTS}
    }

@app.post("/api/jobs")
async def create_job(j: JobCreate):
    jid=str(uuid.uuid4()); con=db()
    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid,j.title,j.brief,"inbox",j.presenter,j.format,j.language,j.outputs,"idle",0,ts(),ts()))
    con.commit(); con.close(); event(jid,f"Created: {j.title}")
    global selected_job_id; selected_job_id=jid
    await broadcast(); return {"id":jid}

@app.post("/api/jobs/{job_id}/select")
async def select_job(job_id:str):
    global selected_job_id
    if not any(j["id"]==job_id for j in get_jobs()): raise HTTPException(404,"Job not found")
    selected_job_id=job_id; await broadcast(); return {"ok":True}

@app.post("/api/jobs/{job_id}/move")
async def move_job(job_id:str,m:Move):
    if m.stage not in STAGES: raise HTTPException(400,"Unknown stage")
    con=db(); r=con.execute("SELECT id FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not r: con.close(); raise HTTPException(404,"Job not found")
    p=int(STAGES.index(m.stage)/(len(STAGES)-1)*100)
    con.execute("UPDATE jobs SET stage=?,status='idle',progress=?,updated_at=? WHERE id=?",(m.stage,p,ts(),job_id)); con.commit(); con.close()
    event(job_id,f"Moved manually to {m.stage}"); await broadcast(); return {"ok":True}

@app.post("/api/jobs/{job_id}/run")
async def run_job(job_id:str):
    if job_id in running_jobs: return {"ok":True,"message":"Already running"}
    jobs=get_jobs(); job=next((j for j in jobs if j["id"]==job_id),None)
    if not job: raise HTTPException(404,"Job not found")
    if job["status"] == "waiting_approval": return {"ok":False,"message":"Approval required"}
    running_jobs.add(job_id); asyncio.create_task(run_until_review(job_id)); return {"ok":True}

async def run_until_review(job_id:str):
    try:
        jobs=get_jobs(); j=next(x for x in jobs if x["id"]==job_id)
        start=max(1,STAGES.index(j["stage"]))
        # stop at QA review gate
        for idx in range(start, STAGES.index("qa")+1):
            stage=STAGES[idx]
            con=db(); con.execute("UPDATE jobs SET stage=?,status='running',progress=?,updated_at=? WHERE id=?",
                (stage,int(idx/(len(STAGES)-1)*100),ts(),job_id)); con.commit(); con.close()
            await broadcast()
            for a in AGENT_MAP.get(stage,[]):
                await execute_agent(a, stage, job_id, delay=1.1)
            gate=validate_stage_outputs(job_id,stage)
            if not gate["ok"]:
                raise RuntimeError(f"Quality gate failed for {stage}: missing artifacts from {', '.join(gate['missing'])}")
            event(job_id,f"Quality gate passed: {stage} ({gate['ready']}/{gate['expected']} agent outputs)")
        con=db(); con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,"Review gate: waiting for approval"); await broadcast()
    except Exception as exc:
        con=db(); con.execute("UPDATE jobs SET status='failed',updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,f"Pipeline failed: {exc}")
        await broadcast({"type":"job_failed","jobId":job_id,"error":str(exc)})
    finally:
        running_jobs.discard(job_id)

@app.post("/api/jobs/{job_id}/approve")
async def approve(job_id:str):
    jobs=get_jobs(); j=next((x for x in jobs if x["id"]==job_id),None)
    if not j: raise HTTPException(404,"Job not found")
    if j["status"] != "waiting_approval": return {"ok":False,"message":"Job is not waiting for approval"}
    if job_id in running_jobs: return {"ok":True}
    running_jobs.add(job_id); asyncio.create_task(run_publish(job_id)); return {"ok":True}

async def run_publish(job_id:str):
    try:
        for stage in ["publish","analytics"]:
            idx=STAGES.index(stage)
            con=db(); con.execute("UPDATE jobs SET stage=?,status='running',progress=?,updated_at=? WHERE id=?",
                (stage,int(idx/(len(STAGES)-1)*100),ts(),job_id)); con.commit(); con.close(); await broadcast()
            for a in AGENT_MAP.get(stage,[]):
                await execute_agent(a, stage, job_id, delay=1.2)
            gate=validate_stage_outputs(job_id,stage)
            if not gate["ok"]:
                raise RuntimeError(f"Quality gate failed for {stage}: missing artifacts from {', '.join(gate['missing'])}")
            event(job_id,f"Quality gate passed: {stage} ({gate['ready']}/{gate['expected']} agent outputs)")
        con=db(); con.execute("UPDATE jobs SET stage='analytics',status='done',progress=100,updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,"Factory run completed"); await broadcast()
    except Exception as exc:
        con=db(); con.execute("UPDATE jobs SET status='failed',updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,f"Publishing pipeline failed: {exc}")
        await broadcast({"type":"job_failed","jobId":job_id,"error":str(exc)})
    finally:
        running_jobs.discard(job_id)

@app.get("/api/agents")
def list_agents():
    jobs=get_jobs()
    states=agent_states(jobs)
    return {
        "agents":[
            {
                "name":name,
                **AGENT_SPECS.get(name,{}),
                "state":states.get(name,"idle"),
                "metrics":get_agent_metrics(name),
            } for name in AGENTS
        ]
    }

@app.get("/api/agents/{agent_name}")
def agent_detail(agent_name:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    con=db()
    runs=[dict(x) for x in con.execute(
        """SELECT r.*, j.title job_title
           FROM agent_runs r LEFT JOIN jobs j ON j.id=r.job_id
           WHERE r.agent=? ORDER BY r.started_at DESC LIMIT 60""",(agent_name,)
    ).fetchall()]
    artifacts=[dict(x) for x in con.execute(
        """SELECT a.*, j.title job_title
           FROM artifacts a LEFT JOIN jobs j ON j.id=a.job_id
           WHERE a.agent=? ORDER BY a.created_at DESC LIMIT 80""",(agent_name,)
    ).fetchall()]
    con.close()
    for r in runs:
        try:r["meta"]=json.loads(r.pop("meta_json") or "{}")
        except Exception:r["meta"]={}
    for a in artifacts:
        try:a["meta"]=json.loads(a.pop("meta_json") or "{}")
        except Exception:a["meta"]={}
    return {
        "name":agent_name,
        "spec":AGENT_SPECS.get(agent_name,{}),
        "state":agent_states(get_jobs()).get(agent_name,"idle"),
        "metrics":get_agent_metrics(agent_name),
        "runs":runs,
        "artifacts":artifacts,
        "providerMode":"demo" if CONNECTIONS.get("LLM",{}).get("state")=="demo" else "live"
    }

@app.get("/api/jobs/{job_id}/quality")
def job_quality(job_id:str):
    job=get_job(job_id)
    if not job:
        raise HTTPException(404,"Job not found")
    checks={stage:validate_stage_outputs(job_id,stage) for stage in STAGES if AGENT_MAP.get(stage)}
    expected=sum(x["expected"] for x in checks.values())
    ready=sum(x["ready"] for x in checks.values())
    return {"job_id":job_id,"stage":job["stage"],"checks":checks,"ready":ready,"expected":expected,
            "coverage":round((ready/expected*100),1) if expected else 100}

@app.get("/api/jobs/{job_id}/artifacts")
def job_artifacts(job_id:str):
    if not get_job(job_id):
        raise HTTPException(404,"Job not found")
    con=db()
    rows=[dict(x) for x in con.execute(
        "SELECT * FROM artifacts WHERE job_id=? ORDER BY created_at DESC",(job_id,)
    ).fetchall()]
    con.close()
    for a in rows:
        try:a["meta"]=json.loads(a.pop("meta_json") or "{}")
        except Exception:a["meta"]={}
    return {"artifacts":rows}

@app.get("/api/usage")
def usage():
    return {
        "total":get_usage_summary(),
        "agents":{a:get_agent_metrics(a) for a in AGENTS},
        "note":"Token and cost fields are zero in demo mode. They become real provider usage after live APIs are connected."
    }

@app.get("/api/supervisor")
def get_supervisor_report():
    return supervisor_runtime.get("last_report") or supervisor_audit(auto_heal=False, persist=False)

@app.post("/api/supervisor/run")
async def run_supervisor_now():
    if supervisor_runtime.get("state") == "working":
        return {"ok": True, "message": "Supervisor audit is already running"}
    asyncio.create_task(supervisor_cycle())
    return {"ok": True, "message": "Supervisor audit started"}

@app.websocket("/ws")
async def ws(ws:WebSocket):
    if FACTORY_PASSWORD:
        token = ws.cookies.get(COOKIE_NAME, "")
        if not hmac.compare_digest(token, session_token(FACTORY_USER)):
            await ws.close(code=4401)
            return
    await ws.accept(); clients.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: clients.discard(ws)
