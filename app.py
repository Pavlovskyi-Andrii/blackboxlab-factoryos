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
        if s in ("working","done"):
            states[a]=s
    states["Supervisor"] = supervisor_runtime.get("state", "monitoring")
    return states

def next_action(job):
    if not job: return "Create your first job."
    if job["status"] == "waiting_approval": return "Review the output, then click Approve & Publish."
    if job["status"] == "running": return f"Factory is working on {job['stage']}."
    if job["status"] == "done": return "Review analytics or create the next job."
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
    try:
        report = supervisor_audit(auto_heal=supervisor_runtime["auto_heal"], persist=True)
        supervisor_runtime["last_report"] = report
        supervisor_runtime["last_run"] = report["checked_at"]
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
        await asyncio.sleep(45)

@app.on_event("startup")
async def start_supervisor():
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
        "supervisorState": supervisor_runtime.get("state", "monitoring")
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
                agent_runtime[a]="working"; event(job_id,f"{a}: working"); await broadcast({"type":"agent","agent":a,"state":"working"})
                await asyncio.sleep(1.1)
                agent_runtime[a]="done"; event(job_id,f"{a}: completed"); await broadcast({"type":"agent","agent":a,"state":"done"})
        con=db(); con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,"Review gate: waiting for approval"); await broadcast()
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
                agent_runtime[a]="working"; event(job_id,f"{a}: working"); await broadcast(); await asyncio.sleep(1.2)
                agent_runtime[a]="done"; event(job_id,f"{a}: completed"); await broadcast()
        con=db(); con.execute("UPDATE jobs SET stage='analytics',status='done',progress=100,updated_at=? WHERE id=?",(ts(),job_id)); con.commit(); con.close()
        event(job_id,"Factory run completed"); await broadcast()
    finally:
        running_jobs.discard(job_id)

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
