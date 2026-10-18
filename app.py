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
APP_VERSION = "v3.12"
BUILD_SHA = os.environ.get("RENDER_GIT_COMMIT", "local")
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

AGENT_DEPENDENCIES = {
    "Scout": [],
    "Researcher": ["Scout"],
    "Tech Verifier": ["Scout","Researcher"],
    "Hook Writer": ["Researcher","Tech Verifier"],
    "Scriptwriter": ["Hook Writer","Researcher","Tech Verifier"],
    "Visual Director": ["Scriptwriter"],
    "Voice Agent": ["Scriptwriter"],
    "Render Agent": ["Visual Director","Voice Agent"],
    "QA Agent": ["Render Agent","Scriptwriter","Tech Verifier"],
    "Publisher": ["QA Agent","Render Agent"],
    "Analyst": ["Publisher"],
    "Supervisor": [],
}

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
FACTORY_DAILY_BUDGET_USD = float(os.environ.get("FACTORY_DAILY_BUDGET_USD", "10"))
FACTORY_JOB_BUDGET_USD = float(os.environ.get("FACTORY_JOB_BUDGET_USD", "3"))
AGENT_TIMEOUT_SECONDS = int(os.environ.get("AGENT_TIMEOUT_SECONDS", "180"))
AGENT_MAX_RETRIES = int(os.environ.get("AGENT_MAX_RETRIES", "1"))

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
        seg=request.url.path.strip("/").split("/",1)[0]
        lang=seg if seg in ("en","uk","ru") else "en"
        return RedirectResponse(f"/login?lang={lang}", status_code=303)
    return await call_next(request)

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, lang: str = "en"):
    lang=lang if lang in ("en","uk","ru") else "en"
    if request_is_authed(request):
        return RedirectResponse(f"/{lang}", status_code=303)
    copy={
      "en":{"sub":"Private AI content production control room","user":"Username","password":"Password","enter":"Enter FactoryOS"},
      "uk":{"sub":"Приватний центр керування AI-виробництвом контенту","user":"Користувач","password":"Пароль","enter":"Увійти до FactoryOS"},
      "ru":{"sub":"Приватный центр управления AI-производством контента","user":"Пользователь","password":"Пароль","enter":"Войти в FactoryOS"},
    }[lang]
    return HTMLResponse(f"""<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width,initial-scale=1'>
    <title>Blackbox Lab — FactoryOS Login</title>
    <style>
    body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(700px 420px at 50% 0,#163f6255,transparent 65%),#07101b;color:#fff;font:14px Inter,system-ui,Arial}}
    .box{{width:min(410px,90vw);background:linear-gradient(180deg,#0e1d2d,#0a1522);border:1px solid #284963;border-radius:20px;padding:28px;box-shadow:0 24px 80px #000a}}
    h1{{margin:0 0 6px;font-size:24px}}.sub{{color:#8ca0b4;margin-bottom:18px}}
    input{{width:100%;box-sizing:border-box;margin:7px 0;padding:12px;background:#07111d;color:#fff;border:1px solid #28465f;border-radius:10px}}
    button{{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#1677ff,#0db7f5);color:#fff;font-weight:800;cursor:pointer}}
    .cube{{width:42px;height:42px;border:2px solid #16bdf6;transform:rotate(30deg);border-radius:7px;margin-bottom:18px;box-shadow:0 0 24px #16bdf655}}
    .langs{{display:flex;gap:5px;justify-content:flex-end;margin-bottom:14px}}.langs a{{font-size:10px;color:#8297ac;text-decoration:none;border:1px solid #294761;padding:5px 7px;border-radius:7px}}.langs a.active{{color:#fff;background:#153b63}}
    </style></head><body><form class='box' method='post' action='/login'>
    <div class='langs'><a href='/login?lang=en' class='{"active" if lang=="en" else ""}'>EN</a><a href='/login?lang=uk' class='{"active" if lang=="uk" else ""}'>УКР</a><a href='/login?lang=ru' class='{"active" if lang=="ru" else ""}'>RU</a></div>
    <div class='cube'></div><h1>Blackbox Lab — FactoryOS</h1><div class='sub'>{copy["sub"]}</div>
    <input type='hidden' name='lang' value='{lang}'>
    <input name='username' placeholder='{copy["user"]}' autocomplete='username' required>
    <input name='password' type='password' placeholder='{copy["password"]}' autocomplete='current-password' required>
    <button type='submit'>{copy["enter"]}</button></form></body></html>""")

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), lang: str = Form("en")):
    lang=lang if lang in ("en","uk","ru") else "en"
    if not (hmac.compare_digest(username, FACTORY_USER) and hmac.compare_digest(password, FACTORY_PASSWORD)):
        msg={"en":"Invalid username or password","uk":"Невірний логін або пароль","ru":"Неверный логин или пароль"}[lang]
        retry={"en":"Try again","uk":"Спробувати ще раз","ru":"Попробовать снова"}[lang]
        return HTMLResponse(f"{msg}. <a href='/login?lang={lang}'>{retry}</a>", status_code=401)
    response = RedirectResponse(f"/{lang}", status_code=303)
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
agent_progress = {
    name: {"progress":0,"step":"Idle","job_id":None,"run_id":None,"started_at":None,"updated_at":None}
    for name in AGENTS
}
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
    CREATE TABLE IF NOT EXISTS improvement_proposals(
      id TEXT PRIMARY KEY,
      fingerprint TEXT UNIQUE NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      title TEXT NOT NULL,
      rationale TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'proposed',
      source TEXT NOT NULL DEFAULT 'Supervisor',
      action_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_improvements_status ON improvement_proposals(status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS agent_memory(
      id TEXT PRIMARY KEY,
      agent TEXT NOT NULL,
      kind TEXT NOT NULL DEFAULT 'learning',
      content TEXT NOT NULL,
      source TEXT NOT NULL DEFAULT 'manual',
      source_job_id TEXT,
      confidence REAL NOT NULL DEFAULT 1.0,
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_agent_memory_agent ON agent_memory(agent, active, created_at DESC);
    CREATE TABLE IF NOT EXISTS run_inputs(
      run_id TEXT NOT NULL,
      artifact_id TEXT NOT NULL,
      source_agent TEXT NOT NULL,
      created_at TEXT NOT NULL,
      PRIMARY KEY(run_id,artifact_id)
    );
    CREATE INDEX IF NOT EXISTS idx_run_inputs_run ON run_inputs(run_id);
    CREATE TABLE IF NOT EXISTS agent_run_steps(
      id TEXT PRIMARY KEY,
      run_id TEXT NOT NULL,
      job_id TEXT,
      agent TEXT NOT NULL,
      step_key TEXT NOT NULL,
      label TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'running',
      progress INTEGER NOT NULL DEFAULT 0,
      started_at TEXT NOT NULL,
      finished_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_run_steps_run ON agent_run_steps(run_id, started_at);
    CREATE INDEX IF NOT EXISTS idx_run_steps_agent ON agent_run_steps(agent, started_at DESC);
    CREATE TABLE IF NOT EXISTS agent_mcp_connections(
      id TEXT PRIMARY KEY,
      agent TEXT NOT NULL,
      name TEXT NOT NULL,
      transport TEXT NOT NULL DEFAULT 'streamable_http',
      endpoint TEXT NOT NULL,
      auth_env TEXT DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'configured',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_agent_mcp_agent ON agent_mcp_connections(agent, enabled, updated_at DESC);
    CREATE TABLE IF NOT EXISTS factory_tasks(
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      description TEXT DEFAULT '',
      category TEXT NOT NULL DEFAULT 'product',
      priority TEXT NOT NULL DEFAULT 'medium',
      status TEXT NOT NULL DEFAULT 'todo',
      owner TEXT NOT NULL DEFAULT 'Factory Builder',
      order_index INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_factory_tasks_status ON factory_tasks(status, order_index, updated_at DESC);
    CREATE TABLE IF NOT EXISTS factory_task_steps(
      id TEXT PRIMARY KEY,
      task_id TEXT NOT NULL,
      step_key TEXT NOT NULL,
      label TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'todo',
      progress INTEGER NOT NULL DEFAULT 0,
      order_index INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_factory_task_steps_unique ON factory_task_steps(task_id, step_key);
    CREATE INDEX IF NOT EXISTS idx_factory_task_steps_task ON factory_task_steps(task_id, order_index);
    """)
    task_cols={row["name"] for row in con.execute("PRAGMA table_info(factory_tasks)").fetchall()}
    for name,ddl in [
        ("builder_state","TEXT NOT NULL DEFAULT 'idle'"),
        ("requested_at","TEXT"),
        ("builder_note","TEXT DEFAULT ''"),
    ]:
        if name not in task_cols:
            con.execute(f"ALTER TABLE factory_tasks ADD COLUMN {name} {ddl}")
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

def sync_factory_tasks():
    tasks=[
      ("foundation-cloud","Cloud deployment on Render","FactoryOS runs online with persistent state and private login.","infrastructure","high","done","Factory Builder",10),
      ("clickable-agents","Clickable worker profiles","Every worker opens a profile with history, artifacts, time, tokens and cost.","observability","high","done","Factory Builder",20),
      ("supervisor-agent","Factory Supervisor","Supervisor monitors workers, failures, health and process improvements.","supervision","high","done","Factory Builder",30),
      ("agent-memory","Persistent worker memory","Workers retain approved process learnings and manual rules.","intelligence","high","done","Factory Builder",40),
      ("handoff-provenance","Handoff provenance","Track which upstream artifacts were passed into every worker run.","observability","high","done","Factory Builder",50),
      ("targeted-rerun","Targeted worker reruns","Re-run one worker and flag downstream outputs for rebuild.","workflow","high","done","Factory Builder",60),
      ("worker-progress","Transparent worker progress","Show live percent, current sub-step and persistent step history on hover and click.","observability","high","done","Factory Builder",70),
      ("mcp-registry","Per-worker MCP registry","Each worker can keep its own MCP server configurations without storing secrets.","connectors","high","done","Factory Builder",80),
      ("task-center","Build Progress task center","Separate tab shows product tasks, status, checkmarks and completion progress.","product","high","done","Factory Builder",90),
      ("task-launcher","Launch builder work from FactoryOS","Start a roadmap task from the website, emit an auditable builder event and expose its execution checklist.","product","high","done","Factory Builder",95),
      ("multilingual-ui","EN / UK / RU interface","Serve dedicated English, Ukrainian and Russian UI routes with a persistent language switcher.","product","high","done","Factory Builder",98),
      ("design-refresh","Dashboard visual redesign","Refine spacing, hierarchy, cards and interactive states while preserving observability.","design","high","in_progress","Factory Builder",99),
      ("mcp-execution","MCP execution bridge","Invoke approved MCP tools from a worker run with capability restrictions and audit logs.","connectors","high","in_progress","Factory Builder",100),
      ("live-llm","Live LLM worker adapter","Replace demo Scout/Researcher/Verifier/Writer execution with real model calls and usage accounting.","intelligence","high","todo","Factory Builder",110),
      ("voice-adapter","Voice provider adapter","Generate narration and attach real audio artifacts with usage accounting.","generation","medium","todo","Factory Builder",120),
      ("video-adapter","Video/render provider adapter","Create real video outputs while preserving approval and budget gates.","generation","medium","todo","Factory Builder",130),
      ("analytics-loop","Analytics learning loop","Feed retention, CTR and engagement learnings back into Scout/Hook Writer/Scriptwriter.","analytics","high","todo","Factory Builder",140),
      ("artifact-compare","Artifact version comparison","Compare two worker outputs side by side and select the winner.","quality","medium","todo","Factory Builder",150)
    ]
    con=db(); now=ts()
    for task in tasks:
        task_id,title,description,category,priority,status,owner,order_index=task
        current=con.execute("SELECT status,created_at FROM factory_tasks WHERE id=?",(task_id,)).fetchone()
        created=current["created_at"] if current else now
        completed=now if status=="done" and (not current or current["status"]!="done") else (con.execute("SELECT completed_at FROM factory_tasks WHERE id=?",(task_id,)).fetchone()["completed_at"] if current else None)
        con.execute("""INSERT INTO factory_tasks(id,title,description,category,priority,status,owner,order_index,created_at,updated_at,completed_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(id) DO UPDATE SET
                         title=excluded.title,description=excluded.description,category=excluded.category,
                         priority=excluded.priority,owner=excluded.owner,
                         order_index=excluded.order_index""",
                    (task_id,title,description,category,priority,status,owner,order_index,created,now,completed))
    con.commit(); con.close()

sync_factory_tasks()

DEFAULT_BUILD_STEPS = [
    ("understand","Understand task & acceptance criteria"),
    ("inspect","Inspect current code, state & dependencies"),
    ("plan","Plan the smallest safe implementation"),
    ("implement","Implement the change"),
    ("test","Run CI / regression checks"),
    ("deploy","Deploy through CI-gated Render auto-deploy"),
    ("verify","Verify live behavior & close the task"),
]

def ensure_factory_task_steps(task_id):
    con=db(); now=ts()
    existing=con.execute("SELECT COUNT(*) c FROM factory_task_steps WHERE task_id=?",(task_id,)).fetchone()["c"]
    if not existing:
        for idx,(key,label) in enumerate(DEFAULT_BUILD_STEPS, start=1):
            con.execute("""INSERT INTO factory_task_steps(id,task_id,step_key,label,status,progress,order_index,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (str(uuid.uuid4()),task_id,key,label,"todo",0,idx*10,now,now))
        con.commit()
    rows=[dict(x) for x in con.execute("""SELECT * FROM factory_task_steps
                                          WHERE task_id=? ORDER BY order_index""",(task_id,)).fetchall()]
    con.close()
    return rows

def get_factory_task_steps(task_id):
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT * FROM factory_task_steps
                                          WHERE task_id=? ORDER BY order_index""",(task_id,)).fetchall()]
    con.close()
    return rows

def set_factory_task_step(task_id, step_key, status, progress=None):
    if status not in ("todo","in_progress","done","blocked"):
        raise ValueError("Unknown step status")
    con=db(); now=ts()
    row=con.execute("SELECT id FROM factory_task_steps WHERE task_id=? AND step_key=?",(task_id,step_key)).fetchone()
    if not row:
        con.close()
        return False
    if progress is None:
        progress={"todo":0,"in_progress":35,"done":100,"blocked":0}[status]
    con.execute("""UPDATE factory_task_steps
                   SET status=?,progress=?,updated_at=?,completed_at=?
                   WHERE task_id=? AND step_key=?""",
                (status,max(0,min(100,int(progress))),now,now if status=="done" else None,task_id,step_key))
    con.commit(); con.close()
    return True

def task_execution_progress(task_id):
    steps=get_factory_task_steps(task_id)
    if not steps:
        return {"steps":[],"done":0,"total":0,"progress":0}
    done=sum(1 for x in steps if x["status"]=="done")
    partial=sum(int(x.get("progress") or 0) for x in steps)
    return {"steps":steps,"done":done,"total":len(steps),"progress":round(partial/len(steps),1)}

def apply_build_manifest():
    path=BASE/"factory_build_manifest.json"
    if not path.exists():
        return 0
    try:
        payload=json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    updates=payload.get("tasks",{})
    if not isinstance(updates,dict):
        return 0
    applied=0; con=db(); now=ts()
    for task_id,update in updates.items():
        if not isinstance(update,dict):
            continue
        row=con.execute("SELECT id FROM factory_tasks WHERE id=?",(task_id,)).fetchone()
        if not row:
            meta=update.get("meta") or {}
            title=meta.get("title") or task_id
            con.execute("""INSERT INTO factory_tasks(id,title,description,category,priority,status,owner,order_index,created_at,updated_at,completed_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                        (task_id,title,meta.get("description",""),meta.get("category","product"),
                         meta.get("priority","medium"),update.get("status","todo"),meta.get("owner","Factory Builder"),
                         int(meta.get("order_index",9990)),now,now,now if update.get("status")=="done" else None))
        elif update.get("status") in ("todo","in_progress","done","blocked"):
            next_status=update["status"]
            builder_state="done" if next_status=="done" else ("active" if next_status=="in_progress" else next_status)
            con.execute("""UPDATE factory_tasks
                           SET status=?,builder_state=?,updated_at=?,completed_at=?,
                               builder_note=CASE WHEN ?='active' THEN 'Factory Builder is processing this task' ELSE builder_note END
                           WHERE id=?""",
                        (next_status,builder_state,now,now if next_status=="done" else None,builder_state,task_id))
        con.commit()
        ensure_factory_task_steps(task_id)
        for step_key,step_update in (update.get("steps") or {}).items():
            if isinstance(step_update,str):
                set_factory_task_step(task_id,step_key,step_update)
            elif isinstance(step_update,dict):
                set_factory_task_step(task_id,step_key,step_update.get("status","todo"),step_update.get("progress"))
        applied+=1
    con.close()
    return applied

apply_build_manifest()

class JobCreate(BaseModel):
    title: str
    brief: str = ""
    presenter: str = "AI presenter"
    format: str = "Long + Shorts"
    language: str = "English"
    outputs: int = 8

class Move(BaseModel): stage: str

class McpConnectionCreate(BaseModel):
    name: str
    endpoint: str
    transport: str = "streamable_http"
    auth_env: str = ""

class McpConnectionToggle(BaseModel):
    enabled: bool

class FactoryTaskCreate(BaseModel):
    title: str
    description: str = ""
    category: str = "product"
    priority: str = "medium"
    owner: str = "Factory Builder"

class FactoryTaskStatus(BaseModel):
    status: str

def event(job_id, message):
    con=db(); con.execute("INSERT INTO events(job_id,ts,message) VALUES(?,?,?)",(job_id,ts(),message)); con.commit(); con.close()

def job_dict(r): return dict(r) if r else None

def get_jobs():
    con=db(); rows=con.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall(); con.close(); return [dict(x) for x in rows]

def get_job(job_id):
    con=db(); row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone(); con.close()
    return dict(row) if row else None

def collect_agent_inputs(job_id, agent):
    deps=AGENT_DEPENDENCIES.get(agent,[])
    if not deps or not job_id:
        return {"artifacts":[],"missing":[]}
    con=db()
    artifacts=[]
    missing=[]
    for dep in deps:
        row=con.execute("""SELECT id,agent,kind,title,content,url,mime_type,created_at
                           FROM artifacts WHERE job_id=? AND agent=?
                           ORDER BY created_at DESC LIMIT 1""",(job_id,dep)).fetchone()
        if row:
            artifacts.append(dict(row))
        else:
            missing.append(dep)
    con.close()
    return {"artifacts":artifacts,"missing":missing}

def set_agent_progress(agent, progress=None, step=None, job_id=None, run_id=None, state=None):
    current=agent_progress.setdefault(agent,{"progress":0,"step":"Idle","job_id":None,"run_id":None,"started_at":None,"updated_at":None})
    now=ts()
    if progress is not None: current["progress"]=max(0,min(100,int(progress)))
    if step is not None: current["step"]=step
    if job_id is not None: current["job_id"]=job_id
    if run_id is not None: current["run_id"]=run_id
    if current.get("started_at") is None and current.get("progress",0)>0: current["started_at"]=now
    current["updated_at"]=now
    if state is not None: agent_runtime[agent]=state
    return dict(current)

def record_run_step(run_id, job_id, agent, step_key, label, progress, status="completed"):
    step_id=str(uuid.uuid4())
    now=ts()
    finished=now if status in ("completed","failed","skipped") else None
    con=db()
    con.execute("""INSERT INTO agent_run_steps(id,run_id,job_id,agent,step_key,label,status,progress,started_at,finished_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (step_id,run_id,job_id,agent,step_key,label,status,int(progress),now,finished))
    con.commit(); con.close()
    return step_id

async def push_agent_progress(agent, run_id, job_id, step_key, label, progress, state="working", persist=True):
    snapshot=set_agent_progress(agent,progress,label,job_id,run_id,state)
    if persist:
        record_run_step(run_id,job_id,agent,step_key,label,progress,"completed")
    await broadcast({"type":"agent_progress","agent":agent,"state":state,"progress":snapshot})

def reset_agent_progress(agent, state="idle", step="Idle"):
    agent_runtime[agent]=state
    agent_progress[agent]={"progress":0 if state=="idle" else 100 if state=="done" else 0,
                           "step":step,"job_id":None,"run_id":None,"started_at":None,"updated_at":ts()}

def get_agent_progress_snapshot(agent):
    current=dict(agent_progress.get(agent,{}) or {})
    if current.get("run_id") or agent_runtime.get(agent) in ("working","failed"):
        return current
    con=db()
    row=con.execute("""SELECT s.progress,s.label,s.job_id,s.run_id,s.started_at,s.finished_at,r.status run_status
                       FROM agent_run_steps s
                       JOIN agent_runs r ON r.id=s.run_id
                       WHERE s.agent=? ORDER BY s.started_at DESC LIMIT 1""",(agent,)).fetchone()
    con.close()
    if row:
        return {
            "progress":int(row["progress"] or 0),
            "step":row["label"],
            "job_id":row["job_id"],
            "run_id":row["run_id"],
            "started_at":row["started_at"],
            "updated_at":row["finished_at"] or row["started_at"],
        }
    if agent=="Supervisor":
        return {"progress":100,"step":"Continuous monitoring","job_id":None,"run_id":None,"started_at":None,"updated_at":ts()}
    return current or {"progress":0,"step":"Idle","job_id":None,"run_id":None,"started_at":None,"updated_at":None}

def get_agent_mcp_connections(agent):
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT * FROM agent_mcp_connections
                                          WHERE agent=? ORDER BY enabled DESC,updated_at DESC""",(agent,)).fetchall()]
    con.close()
    for x in rows: x["enabled"]=bool(x["enabled"])
    return rows

def get_factory_tasks():
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT * FROM factory_tasks
                                          ORDER BY CASE status WHEN 'in_progress' THEN 0 WHEN 'todo' THEN 1 WHEN 'blocked' THEN 2 ELSE 3 END,
                                                   order_index, updated_at DESC""").fetchall()]
    con.close()
    for row in rows:
        exec_state=task_execution_progress(row["id"])
        row["steps"]=exec_state["steps"]
        row["step_done"]=exec_state["done"]
        row["step_total"]=exec_state["total"]
        row["execution_progress"]=exec_state["progress"]
    total=len(rows); done=sum(1 for x in rows if x["status"]=="done")
    active=sum(1 for x in rows if x["status"]=="in_progress")
    blocked=sum(1 for x in rows if x["status"]=="blocked")
    queued=sum(1 for x in rows if x.get("builder_state")=="queued")
    building=sum(1 for x in rows if x.get("builder_state")=="active")
    return {"tasks":rows,"total":total,"done":done,"active":active,"blocked":blocked,
            "queued":queued,"building":building,
            "progress":round(done/total*100,1) if total else 100}

def start_agent_run(agent, job_id=None, stage=None, model="simulation-v3"):
    run_id=str(uuid.uuid4())
    con=db()
    con.execute("""INSERT INTO agent_runs(id,job_id,agent,stage,status,started_at,model)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id,job_id,agent,stage,"running",ts(),model))
    con.commit(); con.close()
    return run_id

def attach_run_inputs(run_id, inputs):
    if not inputs:
        return
    con=db()
    for item in inputs:
        con.execute("""INSERT OR IGNORE INTO run_inputs(run_id,artifact_id,source_agent,created_at)
                       VALUES(?,?,?,?)""",(run_id,item["id"],item["agent"],ts()))
    con.commit(); con.close()

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
        "Visual Director": ("image","Storyboard / visual plan",f"DEMO OUTPUT — Visual plan for: {title}\n\nShots: macro hardware / terminal / Ghidra UI / animated data flow / presenter inserts.\nVisual rule: every abstract claim should get an on-screen proof or diagram.\nImage preview below is the current FactoryOS office concept.","/static/demo_storyboard.svg","image/svg+xml"),
        "Voice Agent": ("audio","Narration plan",f"DEMO OUTPUT — Voice plan for: {title}\n\nLanguage: {(job or {}).get('language','English')}\nDelivery: concise, confident, curious; short clauses for Shorts, slower explanatory cadence for long-form.\nNo real audio file yet — voice provider is not configured."),
        "Render Agent": ("video","Render manifest",f"DEMO OUTPUT — Render manifest for: {title}\n\nTarget: 16:9 long video + vertical cut-downs.\nCaptions: burned-in for short-form.\nStatus: no real video asset yet — video provider is not configured."),
        "QA Agent": ("analysis","QA report",f"DEMO OUTPUT — QA checklist for: {title}\n\n✓ stage completeness checked\n✓ human approval gate preserved\n⚠ factual/source validation is still demo-only\n⚠ voice/video providers are not configured\nRecommendation: do not auto-publish until live artifact validation is enabled."),
        "Publisher": ("text","Publishing package",f"DEMO OUTPUT — Publishing package for: {title}\n\nYouTube: title + description + chapters + thumbnail brief\nTikTok/Reels: compact caption + 3–5 topic-specific hashtags\nPublishing remains approval-gated."),
        "Analyst": ("analysis","Performance learning brief",f"DEMO OUTPUT — Analytics plan for: {title}\n\nTrack: hook hold, 30-second retention, average percentage viewed, CTR, comments per 1k views, saves/shares.\nFeedback loop: promote winning hook/angle patterns back to Scout and Hook Writer."),
        "Supervisor": ("analysis","Factory audit","Factory Supervisor audit: runtime health, connection readiness, stalled work, cost/time signals and process-improvement backlog."),
    }
    return templates.get(agent,("text","Agent output",f"DEMO OUTPUT for {title}"))

def add_agent_memory(agent, content, kind="learning", source="manual", source_job_id=None, confidence=1.0):
    if agent not in AGENTS:
        raise ValueError(f"Unknown agent: {agent}")
    normalized=" ".join((content or "").split())
    if not normalized:
        return None
    con=db()
    duplicate=con.execute("""SELECT id FROM agent_memory
                             WHERE agent=? AND active=1 AND lower(content)=lower(?)
                             LIMIT 1""",(agent,normalized)).fetchone()
    if duplicate:
        con.close()
        return duplicate["id"]
    memory_id=str(uuid.uuid4())
    con.execute("""INSERT INTO agent_memory(id,agent,kind,content,source,source_job_id,confidence,active,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (memory_id,agent,kind,normalized,source,source_job_id,float(confidence),1,ts()))
    con.commit(); con.close()
    return memory_id

def get_agent_memory(agent, limit=30):
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT * FROM agent_memory
                                          WHERE agent=? AND active=1
                                          ORDER BY created_at DESC LIMIT ?""",
                                       (agent,limit)).fetchall()]
    con.close()
    return rows

def improvement_memory_targets(text):
    t=(text or "").lower()
    targets={"Supervisor"}
    if any(k in t for k in ("hook","retention","ctr","title","thumbnail")):
        targets.update({"Hook Writer","Scriptwriter","Analyst"})
    if any(k in t for k in ("research","source","fact","verify","evidence","technical")):
        targets.update({"Researcher","Tech Verifier","QA Agent"})
    if any(k in t for k in ("visual","image","shot","storyboard")):
        targets.add("Visual Director")
    if any(k in t for k in ("voice","narration","audio")):
        targets.add("Voice Agent")
    if any(k in t for k in ("render","video","caption")):
        targets.add("Render Agent")
    if any(k in t for k in ("publish","platform","youtube","tiktok","instagram")):
        targets.update({"Publisher","Analyst"})
    if any(k in t for k in ("topic","trend","idea","search")):
        targets.add("Scout")
    return sorted(targets)

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
    mem=con.execute("SELECT COUNT(*) c FROM agent_memory WHERE agent=? AND active=1",(agent,)).fetchone()["c"]
    con.close()
    data=dict(row); data["artifacts"]=art; data["memory_count"]=mem
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
    today=con.execute("""SELECT COALESCE(SUM(cost_usd),0) c FROM agent_runs
                         WHERE substr(started_at,1,10)=?""",(datetime.now(timezone.utc).date().isoformat(),)).fetchone()["c"]
    con.close()
    data=dict(row)
    data["today_cost_usd"]=float(today or 0)
    data["daily_budget_usd"]=FACTORY_DAILY_BUDGET_USD
    data["job_budget_usd"]=FACTORY_JOB_BUDGET_USD
    return data

def get_job_cost(job_id):
    con=db(); row=con.execute("SELECT COALESCE(SUM(cost_usd),0) c FROM agent_runs WHERE job_id=?",(job_id,)).fetchone(); con.close()
    return float(row["c"] or 0)

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

def sync_improvement_proposals(report):
    suggestions=[]
    for text in report.get("improvements",[]):
        suggestions.append({
            "title": text[:110],
            "rationale": text,
            "action": {"type":"process_improvement","requires_review":True},
        })
    for finding in report.get("findings",[]):
        rec=finding.get("recommendation")
        if rec:
            suggestions.append({
                "title": f"Resolve: {finding.get('title','Factory issue')}"[:110],
                "rationale": rec,
                "action": {"type":"finding_resolution","code":finding.get("code"),"requires_review":True},
            })
    con=db()
    for item in suggestions[:12]:
        fingerprint=hashlib.sha256((item["title"]+"|"+item["rationale"]).encode("utf-8")).hexdigest()
        now=ts()
        con.execute("""INSERT OR IGNORE INTO improvement_proposals
                       (id,fingerprint,created_at,updated_at,title,rationale,status,source,action_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()),fingerprint,now,now,item["title"],item["rationale"],"proposed","Supervisor",json.dumps(item["action"])))
    con.commit(); con.close()

def get_improvement_proposals(status="proposed", limit=8):
    con=db()
    if status:
        rows=con.execute("""SELECT * FROM improvement_proposals WHERE status=?
                            ORDER BY updated_at DESC LIMIT ?""",(status,limit)).fetchall()
    else:
        rows=con.execute("SELECT * FROM improvement_proposals ORDER BY updated_at DESC LIMIT ?",(limit,)).fetchall()
    con.close()
    out=[]
    for row in rows:
        d=dict(row)
        try:d["action"]=json.loads(d.pop("action_json") or "{}")
        except Exception:d["action"]={}
        out.append(d)
    return out

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

def get_job_quality(job_id):
    job=get_job(job_id)
    if not job:
        return None
    checks={stage:validate_stage_outputs(job_id,stage) for stage in STAGES if AGENT_MAP.get(stage)}
    expected=sum(x["expected"] for x in checks.values())
    ready=sum(x["ready"] for x in checks.values())
    con=db()
    stage_times={}
    for stage in STAGES:
        agents=AGENT_MAP.get(stage,[])
        if not agents:
            continue
        placeholders=",".join("?" for _ in agents)
        row=con.execute(f"SELECT MAX(created_at) t FROM artifacts WHERE job_id=? AND agent IN ({placeholders})",
                        (job_id,*agents)).fetchone()
        stage_times[stage]=row["t"] if row else None
    con.close()
    stale=[]
    newest_upstream=None
    for stage in STAGES:
        current=stage_times.get(stage)
        if current:
            if newest_upstream and current < newest_upstream:
                stale.append(stage)
            if newest_upstream is None or current > newest_upstream:
                newest_upstream=current
    return {
        "job_id":job_id,"stage":job["stage"],"checks":checks,
        "ready":ready,"expected":expected,
        "coverage":round((ready/expected*100),1) if expected else 100,
        "stale_stages":stale,"stage_times":stage_times,"fresh":not stale
    }

async def execute_agent(agent, stage, job_id, delay=1.1):
    job=get_job(job_id)
    last_error=None
    total_attempts=max(1,AGENT_MAX_RETRIES+1)
    for attempt in range(1,total_attempts+1):
        input_pack=collect_agent_inputs(job_id,agent)
        run_id=start_agent_run(agent,job_id,stage)
        attach_run_inputs(run_id,input_pack["artifacts"])
        set_agent_progress(agent,3,"Starting run",job_id,run_id,"working")
        event(job_id,f"{agent}: working (attempt {attempt}/{total_attempts})")
        await broadcast({"type":"agent","agent":agent,"state":"working","attempt":attempt})

        try:
            await push_agent_progress(agent,run_id,job_id,"inputs","Checking upstream inputs",8)
            if input_pack["missing"]:
                missing=", ".join(input_pack["missing"])
                raise RuntimeError(f"Missing required upstream artifacts from: {missing}")

            await push_agent_progress(agent,run_id,job_id,"context","Preparing context & memory",20)
            await asyncio.sleep(max(0.05,delay*0.15))

            await push_agent_progress(agent,run_id,job_id,"tools","Checking MCP/tool capabilities",34)
            mcp=get_agent_mcp_connections(agent)
            enabled_mcp=[x for x in mcp if x["enabled"]]
            await asyncio.sleep(max(0.05,delay*0.12))

            await push_agent_progress(agent,run_id,job_id,"generate","Producing output",52)
            async def demo_step():
                await asyncio.sleep(max(0.05,delay*0.40))
                return agent_artifact_template(agent,job)
            kind,title,content,*extra=await asyncio.wait_for(demo_step(),timeout=AGENT_TIMEOUT_SECONDS)

            await push_agent_progress(agent,run_id,job_id,"validate","Validating output",76)
            await asyncio.sleep(max(0.05,delay*0.13))

            kwargs={}
            if extra:
                if len(extra)>0: kwargs["url"]=extra[0]
                if len(extra)>1: kwargs["mime_type"]=extra[1]

            await push_agent_progress(agent,run_id,job_id,"save","Saving artifact & ledger",91)
            save_artifact(agent,kind,title,content,job_id=job_id,run_id=run_id,
                          meta={"mode":"demo","stage":stage,"attempt":attempt,
                                "enabled_mcp":[x["name"] for x in enabled_mcp]},**kwargs)
            finish_agent_run(run_id,status="completed",
                             meta={"mode":"demo","attempt":attempt,
                                   "enabled_mcp":[x["name"] for x in enabled_mcp],
                                   "note":"No paid model or MCP tool call was made."})
            record_run_step(run_id,job_id,agent,"complete","Completed",100,"completed")
            set_agent_progress(agent,100,"Completed",job_id,run_id,"done")
            event(job_id,f"{agent}: completed")
            await broadcast({"type":"agent_progress","agent":agent,"state":"done","progress":agent_progress[agent]})
            return
        except asyncio.TimeoutError:
            last_error=f"Timed out after {AGENT_TIMEOUT_SECONDS}s"
        except Exception as exc:
            last_error=str(exc)

        record_run_step(run_id,job_id,agent,"failed",last_error,agent_progress.get(agent,{}).get("progress",0),"failed")
        finish_agent_run(run_id,status="failed",error=last_error,
                         meta={"mode":"demo","attempt":attempt})
        set_agent_progress(agent,agent_progress.get(agent,{}).get("progress",0),f"Failed: {last_error}",job_id,run_id,"failed")
        event(job_id,f"{agent}: attempt {attempt} failed — {last_error}")
        await broadcast({"type":"agent_progress","agent":agent,"state":"failed","progress":agent_progress[agent]})
        if attempt < total_attempts:
            event(job_id,f"{agent}: retrying")
            set_agent_progress(agent,5,"Retrying",job_id,run_id,"working")
            await asyncio.sleep(min(2,attempt))
            continue
        raise RuntimeError(f"{agent} failed after {total_attempts} attempt(s): {last_error}")

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

    usage=get_usage_summary()
    if usage["daily_budget_usd"] > 0 and usage["today_cost_usd"] >= usage["daily_budget_usd"]:
        add("critical","daily_budget_reached","Daily provider budget reached",
            f"Today's recorded provider cost is USD {usage['today_cost_usd']:.4f}, at or above the USD {usage['daily_budget_usd']:.2f} limit.",
            "Keep new paid agent work blocked until the budget is reviewed.")
    elif usage["daily_budget_usd"] > 0 and usage["today_cost_usd"] >= usage["daily_budget_usd"]*0.8:
        add("warning","daily_budget_warning","Daily provider budget above 80%",
            f"Today's recorded provider cost is USD {usage['today_cost_usd']:.4f}.",
            "Review remaining planned work and reserve budget for high-value stages.")

    # Data-driven agent performance checks.
    perf=[]
    for agent in AGENTS:
        if agent=="Supervisor":
            continue
        m=get_agent_metrics(agent)
        if not m["runs"]:
            continue
        perf.append((agent,m))
        if m["runs"] >= 3 and m["success_rate"] < 90:
            add("warning","low_success_rate",f"Low success rate: {agent}",
                f"{agent} completed {m['success_rate']}% of {m['runs']} recorded runs.",
                "Inspect recent failures, tighten the input contract and add a bounded retry only for transient errors.")
        if m["avg_duration_ms"] > 120000:
            add("warning","slow_agent",f"Slow agent: {agent}",
                f"Average recorded run time is {round(m['avg_duration_ms']/1000,1)} seconds.",
                "Profile this step, reduce unnecessary context, parallelize safe sub-tasks or switch provider/model.")
        avg_cost=(m["cost_usd"]/m["runs"]) if m["runs"] else 0
        if avg_cost > 1.0:
            add("warning","high_agent_cost",f"High cost per run: {agent}",
                f"Average recorded provider cost is USD {avg_cost:.4f} per run.",
                "Reduce context/output size, route simpler work to a cheaper model, and set a hard per-run budget.")

    # Process-improvement advice: keep a prioritized, data-aware backlog.
    if not any(x["code"] == "llm_demo" for x in findings):
        improvements.append("Keep artifact schemas strict so Supervisor can validate quality, not only runtime state.")
    if perf:
        slowest=max(perf,key=lambda x:x[1]["avg_duration_ms"])
        if slowest[1]["avg_duration_ms"]>0:
            improvements.append(
                f"Current time bottleneck: {slowest[0]} averages {round(slowest[1]['avg_duration_ms']/1000,1)}s per run. Optimize this stage first."
            )
        costliest=max(perf,key=lambda x:(x[1]["cost_usd"]/x[1]["runs"]) if x[1]["runs"] else 0)
        avg=(costliest[1]["cost_usd"]/costliest[1]["runs"]) if costliest[1]["runs"] else 0
        if avg>0:
            improvements.append(f"Current cost bottleneck: {costliest[0]} averages USD {avg:.4f} per run.")
    improvements.extend([
        "Use bounded retries + timeout per agent, and store the exact failure reason in the ledger.",
        "Before Publish, require QA checks for factual support, duplicate content, title/thumbnail fit and platform policy.",
        "Feed winning retention/CTR patterns from Analyst back into Scout, Hook Writer and Scriptwriter.",
    ])
    improvements=list(dict.fromkeys(improvements))[:5]

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
        sync_improvement_proposals(report)
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
@app.get("/en")
@app.get("/uk")
@app.get("/ru")
def root():
    return FileResponse(BASE/"static"/"index.html", headers={"Cache-Control":"no-store, no-cache, must-revalidate, max-age=0","Pragma":"no-cache"})

@app.get("/api/version")
def version():
    return {"version":APP_VERSION,"build_sha":BUILD_SHA,"service":"factoryos"}

@app.get("/api/status")
def status():
    jobs=get_jobs(); sid=current_selected(jobs); selected=next((j for j in jobs if j["id"]==sid),None)
    con=db(); ev=[dict(x) for x in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 60").fetchall()]; con.close()
    report = supervisor_runtime.get("last_report") or supervisor_audit(auto_heal=False, persist=False)
    return {
        "factory":"online","version":APP_VERSION,"buildSha":BUILD_SHA,"jobs":jobs,"selectedJobId":sid,"selectedJob":selected,
        "selectedJobQuality": get_job_quality(sid) if sid else None,
        "events":ev,"connections":CONNECTIONS,"stages":STAGES,
        "agentStates":agent_states(jobs),"agentProgress":{a:get_agent_progress_snapshot(a) for a in AGENTS},"agentMap":AGENT_MAP,
        "runningJobs":list(running_jobs),"nextAction":next_action(selected),
        "supervisor": report,
        "supervisorState": supervisor_runtime.get("state", "monitoring"),
        "usage": get_usage_summary(),
        "agentMetrics": {a:get_agent_metrics(a) for a in AGENTS},
        "improvementProposals": get_improvement_proposals("proposed",5),
        "buildProgress": get_factory_tasks(),
        "runtimePolicy": {
            "agent_timeout_seconds":AGENT_TIMEOUT_SECONDS,
            "max_retries":AGENT_MAX_RETRIES,
            "daily_budget_usd":FACTORY_DAILY_BUDGET_USD,
            "job_budget_usd":FACTORY_JOB_BUDGET_USD
        }
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
    usage=get_usage_summary()
    if usage["today_cost_usd"] >= FACTORY_DAILY_BUDGET_USD:
        return {"ok":False,"message":"Daily provider budget reached. Increase the budget only after review."}
    if get_job_cost(job_id) >= FACTORY_JOB_BUDGET_USD:
        return {"ok":False,"message":"This job reached its provider budget. Review its agent ledger before continuing."}
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

async def rerun_single_agent(job_id, agent_name, stage):
    try:
        event(job_id,f"Manual rerun: {agent_name} started")
        await execute_agent(agent_name,stage,job_id,delay=1.0)
        con=db()
        con.execute("UPDATE jobs SET stage=?,status='idle',progress=?,updated_at=? WHERE id=?",
                    (stage,int(STAGES.index(stage)/(len(STAGES)-1)*100),ts(),job_id))
        con.commit(); con.close()
        event(job_id,f"Manual rerun: {agent_name} completed; downstream stages require rebuild")
        await broadcast()
    except Exception as exc:
        con=db()
        con.execute("UPDATE jobs SET stage=?,status='failed',updated_at=? WHERE id=?",(stage,ts(),job_id))
        con.commit(); con.close()
        event(job_id,f"Manual rerun failed for {agent_name}: {exc}")
        await broadcast({"type":"job_failed","jobId":job_id,"error":str(exc)})
    finally:
        running_jobs.discard(job_id)

@app.post("/api/jobs/{job_id}/agents/{agent_name}/rerun")
async def rerun_agent(job_id:str,agent_name:str):
    job=get_job(job_id)
    if not job:
        raise HTTPException(404,"Job not found")
    if agent_name not in AGENT_SPECS or agent_name=="Supervisor":
        raise HTTPException(400,"This agent cannot be rerun on a content job")
    stage=AGENT_SPECS[agent_name].get("stage")
    if stage not in STAGES:
        raise HTTPException(400,"Agent stage is not part of the content pipeline")
    if job_id in running_jobs:
        return {"ok":False,"message":"Wait for the current job run to finish first"}
    running_jobs.add(job_id)
    con=db()
    con.execute("UPDATE jobs SET stage=?,status='running',progress=?,updated_at=? WHERE id=?",
                (stage,int(STAGES.index(stage)/(len(STAGES)-1)*100),ts(),job_id))
    con.commit(); con.close()
    event(job_id,f"Manual rerun requested: {agent_name}; downstream outputs will require rebuild")
    asyncio.create_task(rerun_single_agent(job_id,agent_name,stage))
    await broadcast()
    return {"ok":True,"message":f"{agent_name} rerun started"}

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
    for r in runs:
        try:r["meta"]=json.loads(r.pop("meta_json") or "{}")
        except Exception:r["meta"]={}
        r["inputs"]=[dict(x) for x in con.execute(
            """SELECT ri.source_agent,a.id,a.kind,a.title,a.created_at
               FROM run_inputs ri JOIN artifacts a ON a.id=ri.artifact_id
               WHERE ri.run_id=? ORDER BY a.created_at""",(r["id"],)
        ).fetchall()]
    con.close()
    for a in artifacts:
        try:a["meta"]=json.loads(a.pop("meta_json") or "{}")
        except Exception:a["meta"]={}
    con2=db()
    steps=[dict(x) for x in con2.execute("""SELECT s.*,j.title job_title
                                            FROM agent_run_steps s
                                            LEFT JOIN jobs j ON j.id=s.job_id
                                            WHERE s.agent=? ORDER BY s.started_at DESC LIMIT 120""",(agent_name,)).fetchall()]
    con2.close()
    return {
        "name":agent_name,
        "spec":AGENT_SPECS.get(agent_name,{}),
        "dependencies":AGENT_DEPENDENCIES.get(agent_name,[]),
        "state":agent_states(get_jobs()).get(agent_name,"idle"),
        "metrics":get_agent_metrics(agent_name),
        "progress":get_agent_progress_snapshot(agent_name),
        "mcp":get_agent_mcp_connections(agent_name),
        "steps":steps,
        "runs":runs,
        "artifacts":artifacts,
        "memory":get_agent_memory(agent_name),
        "providerMode":"demo" if CONNECTIONS.get("LLM",{}).get("state")=="demo" else "live"
    }

@app.get("/api/jobs/{job_id}/quality")
def job_quality(job_id:str):
    quality=get_job_quality(job_id)
    if not quality:
        raise HTTPException(404,"Job not found")
    return quality

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

@app.get("/api/agents/{agent_name}/mcp")
def list_agent_mcp(agent_name:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    return {
        "agent":agent_name,
        "connections":get_agent_mcp_connections(agent_name),
        "execution":"configuration_only",
        "note":"Credentials are never stored here. auth_env names an environment variable. Live MCP invocation is the next connector milestone."
    }

@app.post("/api/agents/{agent_name}/mcp")
async def add_agent_mcp(agent_name:str,item:McpConnectionCreate):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    if item.transport not in ("streamable_http","sse"):
        raise HTTPException(400,"Supported transports: streamable_http, sse")
    endpoint=item.endpoint.strip()
    if not endpoint.startswith(("https://","http://")):
        raise HTTPException(400,"Remote MCP endpoint must start with http:// or https://")
    auth_env=item.auth_env.strip()
    if auth_env and not auth_env.replace("_","").isalnum():
        raise HTTPException(400,"auth_env must be an environment variable name, not a secret value")
    connection_id=str(uuid.uuid4()); now=ts()
    con=db()
    con.execute("""INSERT INTO agent_mcp_connections(id,agent,name,transport,endpoint,auth_env,enabled,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (connection_id,agent_name,item.name.strip() or "MCP Server",item.transport,endpoint,auth_env,0,"configured",now,now))
    con.commit(); con.close()
    event(None,f"MCP configured for {agent_name}: {item.name}")
    await broadcast()
    return {"ok":True,"id":connection_id}

@app.post("/api/agents/{agent_name}/mcp/{connection_id}/toggle")
async def toggle_agent_mcp(agent_name:str,connection_id:str,item:McpConnectionToggle):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    con=db()
    row=con.execute("SELECT id FROM agent_mcp_connections WHERE id=? AND agent=?",(connection_id,agent_name)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"MCP connection not found")
    con.execute("UPDATE agent_mcp_connections SET enabled=?,status=?,updated_at=? WHERE id=?",
                (1 if item.enabled else 0,"enabled" if item.enabled else "configured",ts(),connection_id))
    con.commit(); con.close()
    event(None,f"MCP {'enabled' if item.enabled else 'disabled'} for {agent_name}")
    await broadcast()
    return {"ok":True}

@app.delete("/api/agents/{agent_name}/mcp/{connection_id}")
async def delete_agent_mcp(agent_name:str,connection_id:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    con=db()
    row=con.execute("SELECT name FROM agent_mcp_connections WHERE id=? AND agent=?",(connection_id,agent_name)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"MCP connection not found")
    con.execute("DELETE FROM agent_mcp_connections WHERE id=?",(connection_id,))
    con.commit(); con.close()
    event(None,f"MCP removed from {agent_name}: {row['name']}")
    await broadcast()
    return {"ok":True}

@app.get("/api/factory/tasks")
def factory_tasks():
    return get_factory_tasks()

@app.get("/api/factory/tasks/{task_id}")
def factory_task_detail(task_id:str):
    con=db(); row=con.execute("SELECT * FROM factory_tasks WHERE id=?",(task_id,)).fetchone(); con.close()
    if not row:
        raise HTTPException(404,"Task not found")
    task=dict(row)
    exec_state=task_execution_progress(task_id)
    task.update({"steps":exec_state["steps"],"step_done":exec_state["done"],"step_total":exec_state["total"],"execution_progress":exec_state["progress"]})
    return task

@app.post("/api/factory/tasks/{task_id}/start")
async def start_factory_task(task_id:str):
    con=db(); row=con.execute("SELECT * FROM factory_tasks WHERE id=?",(task_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Task not found")
    if row["status"]=="in_progress":
        con.close()
        return {"ok":True,"message":"Task is already queued for Factory Builder","task":factory_task_detail(task_id),"already_queued":True}
    now=ts()
    con.execute("""UPDATE factory_tasks
                   SET status='in_progress',builder_state='queued',requested_at=?,updated_at=?,completed_at=NULL,
                       builder_note='Queued from FactoryOS. Factory Builder checks the queue on the autonomous cycle.'
                   WHERE id=?""",(now,now,task_id))
    con.commit(); con.close()
    steps=ensure_factory_task_steps(task_id)
    first_pending=next((x for x in steps if x["status"]!="done"),None)
    if first_pending:
        set_factory_task_step(task_id,first_pending["step_key"],"in_progress",15)
    payload={
        "event":"BUILDER_TASK_STARTED","task_id":task_id,"title":row["title"],
        "description":row["description"],"category":row["category"],"priority":row["priority"],
        "owner":row["owner"],"requested_at":now,
        "instruction":"Inspect repository, implement safely, run CI, deploy, verify, and update factory_build_manifest.json for this task."
    }
    print(json.dumps(payload,ensure_ascii=False),flush=True)
    event(None,f"Builder task started from FactoryOS: {row['title']}")
    await broadcast({"type":"builder_task_started","taskId":task_id})
    return {"ok":True,"message":"Task queued for Factory Builder","task":factory_task_detail(task_id),"already_queued":False}

@app.post("/api/factory/tasks")
async def create_factory_task(item:FactoryTaskCreate):
    task_id=str(uuid.uuid4()); now=ts()
    con=db()
    next_order=con.execute("SELECT COALESCE(MAX(order_index),0)+10 n FROM factory_tasks").fetchone()["n"]
    con.execute("""INSERT INTO factory_tasks(id,title,description,category,priority,status,owner,order_index,created_at,updated_at)
                   VALUES(?,?,?,?,?,'todo',?,?,?,?)""",
                (task_id,item.title.strip(),item.description.strip(),item.category,item.priority,item.owner,next_order,now,now))
    con.commit(); con.close()
    event(None,f"Build task created: {item.title}")
    await broadcast()
    return {"ok":True,"id":task_id}

@app.post("/api/factory/tasks/{task_id}/status")
async def update_factory_task_status(task_id:str,item:FactoryTaskStatus):
    if item.status not in ("todo","in_progress","done","blocked"):
        raise HTTPException(400,"Unknown task status")
    con=db()
    row=con.execute("SELECT title FROM factory_tasks WHERE id=?",(task_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Task not found")
    now=ts()
    builder_state={"todo":"idle","in_progress":"queued","done":"done","blocked":"blocked"}[item.status]
    con.execute("""UPDATE factory_tasks SET status=?,builder_state=?,updated_at=?,completed_at=? WHERE id=?""",
                (item.status,builder_state,now,now if item.status=="done" else None,task_id))
    con.commit(); con.close()
    ensure_factory_task_steps(task_id)
    if item.status=="done":
        for step in get_factory_task_steps(task_id):
            set_factory_task_step(task_id,step["step_key"],"done",100)
    elif item.status=="blocked":
        current=next((x for x in get_factory_task_steps(task_id) if x["status"]=="in_progress"),None)
        if current: set_factory_task_step(task_id,current["step_key"],"blocked",current.get("progress") or 0)
    event(None,f"Build task {item.status}: {row['title']}")
    await broadcast({"type":"builder_task_status","taskId":task_id,"status":item.status})
    return {"ok":True}

@app.get("/api/improvements")
def list_improvements(status:str="proposed", limit:int=30):
    return {"proposals":get_improvement_proposals(status if status!="all" else None,min(max(limit,1),100))}

@app.post("/api/improvements/{proposal_id}/accept")
async def accept_improvement(proposal_id:str):
    con=db(); row=con.execute("SELECT title,rationale FROM improvement_proposals WHERE id=?",(proposal_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Proposal not found")
    con.execute("UPDATE improvement_proposals SET status='accepted',updated_at=? WHERE id=?",(ts(),proposal_id))
    con.commit(); con.close()
    memory_text=f"Approved process learning: {row['rationale']}"
    targets=improvement_memory_targets(row["title"]+" "+row["rationale"])
    for agent in targets:
        add_agent_memory(agent,memory_text,kind="process_learning",source=f"Supervisor proposal {proposal_id}",confidence=1.0)
    event(None,f"Supervisor improvement accepted: {row['title']} → memory for {', '.join(targets)}")
    await broadcast()
    return {"ok":True,"memory_targets":targets}

@app.post("/api/improvements/{proposal_id}/dismiss")
async def dismiss_improvement(proposal_id:str):
    con=db(); row=con.execute("SELECT title FROM improvement_proposals WHERE id=?",(proposal_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Proposal not found")
    con.execute("UPDATE improvement_proposals SET status='dismissed',updated_at=? WHERE id=?",(ts(),proposal_id))
    con.commit(); con.close()
    event(None,f"Supervisor improvement dismissed: {row['title']}")
    await broadcast()
    return {"ok":True}

class MemoryCreate(BaseModel):
    content: str
    kind: str = "learning"
    confidence: float = 1.0

@app.get("/api/agents/{agent_name}/memory")
def agent_memory(agent_name:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    return {"agent":agent_name,"memory":get_agent_memory(agent_name)}

@app.post("/api/agents/{agent_name}/memory")
async def create_agent_memory(agent_name:str,item:MemoryCreate):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    memory_id=add_agent_memory(agent_name,item.content,item.kind,"manual",confidence=max(0,min(1,item.confidence)))
    event(None,f"Memory added to {agent_name}")
    await broadcast()
    return {"ok":True,"id":memory_id}

@app.delete("/api/agents/{agent_name}/memory/{memory_id}")
async def archive_agent_memory(agent_name:str,memory_id:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    con=db()
    row=con.execute("SELECT id FROM agent_memory WHERE id=? AND agent=?",(memory_id,agent_name)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Memory not found")
    con.execute("UPDATE agent_memory SET active=0 WHERE id=?",(memory_id,))
    con.commit(); con.close()
    event(None,f"Memory archived for {agent_name}")
    await broadcast()
    return {"ok":True}

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
