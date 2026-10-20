import asyncio
import json
import sqlite3
import uuid
import os
import hmac
import hashlib
import secrets
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib import request as urlrequest, error as urlerror, parse as urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Form
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
APP_VERSION = "v3.40"
BUILD_SHA = os.environ.get("RENDER_GIT_COMMIT", "local")
GITHUB_REPO = os.environ.get("FACTORY_GITHUB_REPO", "Pavlovskyi-Andrii/blackboxlab-factoryos")
GITHUB_TOKEN = os.environ.get("FACTORY_GITHUB_TOKEN", "").strip()
BUILDER_WORKFLOW = os.environ.get("FACTORY_BUILDER_WORKFLOW", "factory-builder.yml")
FACTORY_MCP_TOKEN = os.environ.get("FACTORY_MCP_TOKEN", "").strip()

# Live LLM adapter. Defaults to an OpenAI-compatible Chat Completions endpoint,
# but the base URL and model are configurable so FactoryOS is not coupled to one vendor.
FACTORY_LLM_API_KEY = os.environ.get("FACTORY_LLM_API_KEY", "").strip()
FACTORY_LLM_BASE_URL = os.environ.get("FACTORY_LLM_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/")
FACTORY_LLM_API_MODE = os.environ.get("FACTORY_LLM_API_MODE", "responses").strip().lower()
FACTORY_LLM_MODEL = os.environ.get("FACTORY_LLM_MODEL", "gpt-5.6-terra").strip()
_DEFAULT_LLM_PRICES={
    "gpt-5.6-luna": (0.20, 1.20),
    "gpt-5.6-terra": (2.00, 12.00),
    "gpt-5.6-sol": (4.00, 20.00),
}
_default_input_price,_default_output_price=_DEFAULT_LLM_PRICES.get(FACTORY_LLM_MODEL,(0.0,0.0))
FACTORY_LLM_INPUT_USD_PER_1M = float(os.environ.get("FACTORY_LLM_INPUT_USD_PER_1M", str(_default_input_price)))
FACTORY_LLM_OUTPUT_USD_PER_1M = float(os.environ.get("FACTORY_LLM_OUTPUT_USD_PER_1M", str(_default_output_price)))
FACTORY_LLM_MAX_OUTPUT_TOKENS = max(128, min(4096, int(os.environ.get("FACTORY_LLM_MAX_OUTPUT_TOKENS", "1200"))))
# Historical production verification evidence remains queryable, but the startup trigger is disabled after the passed v3.24 run.
VERIFICATION_EVIDENCE_TAG = "v3.24-live-e2e-2026-10-19"
PAID_VERIFICATION_TAG = ""
LLM_LIVE_AGENTS = {
    "Scout","Researcher","Tech Verifier","Hook Writer","Angle Strategist","Hook Generator",
    "Scriptwriter","Fact Checker","Hook Optimizer","Editor","Visual Director","QA Agent","Publisher","Analyst",
}

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factory.db"
STAGES = ["inbox","research","script","visual","voice","render","qa","publish","analytics"]
AGENT_MAP = {
    "research": ["Scout","Researcher","Tech Verifier"],
    "script": ["Angle Strategist","Hook Generator","Scriptwriter","Fact Checker","Hook Optimizer","Editor"],
    "visual": ["Visual Director"],
    "voice": ["Voice Agent"],
    "render": ["Render Agent"],
    "qa": ["QA Agent"],
    "publish": ["Publisher"],
    "analytics": ["Analyst"],
}
AGENTS = list(dict.fromkeys([a for stage in STAGES for a in AGENT_MAP.get(stage, [])] + ["Hook Writer","Supervisor","Design Partner"]))

AGENT_DEPENDENCIES = {
    "Scout": [],
    "Researcher": ["Scout"],
    "Tech Verifier": ["Scout","Researcher"],
    "Hook Writer": ["Researcher","Tech Verifier"],
    "Angle Strategist": ["Researcher","Tech Verifier"],
    "Hook Generator": ["Angle Strategist","Researcher","Tech Verifier"],
    "Scriptwriter": ["Hook Generator","Angle Strategist","Researcher","Tech Verifier"],
    "Fact Checker": ["Scriptwriter","Researcher","Tech Verifier"],
    "Hook Optimizer": ["Hook Generator","Fact Checker"],
    "Editor": ["Scriptwriter","Hook Optimizer","Fact Checker"],
    "Visual Director": ["Editor"],
    "Voice Agent": ["Editor"],
    "Render Agent": ["Visual Director","Voice Agent"],
    "QA Agent": ["Render Agent","Editor","Fact Checker"],
    "Publisher": ["QA Agent","Render Agent"],
    "Analyst": ["Publisher"],
    "Supervisor": [],
    "Design Partner": [],
}

AGENT_SPECS = {
    "Scout": {"stage":"research","role":"Trend & topic scout","goal":"Find timely, high-potential content opportunities and useful source leads."},
    "Researcher": {"stage":"research","role":"Research analyst","goal":"Build a reliable evidence pack, key facts, angles and source notes."},
    "Tech Verifier": {"stage":"research","role":"Technical verifier","goal":"Challenge claims, flag uncertainty and verify technical plausibility."},
    "Hook Writer": {"stage":"script","role":"Legacy hook specialist","goal":"Preserve access to historical Hook Writer runs from the v3.x pipeline."},
    "Angle Strategist": {"stage":"script","role":"Angle strategist","goal":"Create distinct evidence-grounded narrative angles for competing production variants."},
    "Hook Generator": {"stage":"script","role":"Hook generator","goal":"Create a concrete 1–3 second opening hook for each production variant."},
    "Scriptwriter": {"stage":"script","role":"Script writer","goal":"Turn each verified angle and hook into a concise production-ready script variant."},
    "Fact Checker": {"stage":"script","role":"Fact checker","goal":"Identify unsupported claims, source gaps and factual conflicts in each script variant."},
    "Hook Optimizer": {"stage":"script","role":"Hook optimizer","goal":"Tighten hooks after fact checking without adding unsupported claims."},
    "Editor": {"stage":"script","role":"Content editor","goal":"Produce the clean final script for each variant while preserving verified claims and optimized hooks."},
    "Visual Director": {"stage":"visual","role":"Visual director","goal":"Translate the selected edited script into shots, screen recordings, graphics and image prompts."},
    "Voice Agent": {"stage":"voice","role":"Voice producer","goal":"Prepare narration, delivery notes and final voice assets from the selected variant."},
    "Render Agent": {"stage":"render","role":"Video producer","goal":"Assemble scenes, captions, timing and final video renders."},
    "QA Agent": {"stage":"qa","role":"Quality controller","goal":"Return structured findings for factual consistency, hook strength, sourcing, pacing, CTA and safety."},
    "Publisher": {"stage":"publish","role":"Distribution manager","goal":"Package and schedule platform-specific publishing assets."},
    "Analyst": {"stage":"analytics","role":"Performance analyst","goal":"Turn performance data into concrete recommendations for the next production cycle."},
    "Supervisor": {"stage":"supervision","role":"Factory supervisor","goal":"Monitor every agent, detect failures, auto-heal safe issues and continuously improve the process."},
    "Design Partner": {"stage":"design-system","role":"UI/UX design reviewer","goal":"Review FactoryOS screens against the premium cyber-office reference, propose concrete layout and visual-system improvements, and convert approved recommendations into build tasks."},
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
FACTORY_SIGNAL_FEEDS = [x.strip() for x in os.environ.get("FACTORY_SIGNAL_FEEDS", "").split(",") if x.strip()]
FACTORY_SIGNAL_COLLECTION_MINUTES = max(5, int(os.environ.get("FACTORY_SIGNAL_COLLECTION_MINUTES", "360")))

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
    public_paths = {"/login", "/health", "/mcp"}
    public_prefixes = ("/static/", "/.well-known/")
    if request.url.path.startswith(public_prefixes) or request.url.path in public_paths or request.url.path=="/register":
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

def _factory_mcp_authorized(request: Request) -> bool:
    if not FACTORY_MCP_TOKEN:
        return False

    # Claude custom connectors do not always expose custom request headers
    # in every client. Support a scoped query-key fallback in addition to
    # the normal Authorization: Bearer <token> flow.
    query_key=(request.query_params.get("key") or "").strip()
    if query_key and hmac.compare_digest(query_key,FACTORY_MCP_TOKEN):
        return True

    auth=request.headers.get("authorization","")
    if not auth.lower().startswith("bearer "):
        return False
    supplied=auth.split(" ",1)[1].strip()
    return hmac.compare_digest(supplied,FACTORY_MCP_TOKEN)

def _factory_mcp_text(value):
    if isinstance(value,str):
        text=value
    else:
        text=json.dumps(value,ensure_ascii=False,indent=2)
    return {"content":[{"type":"text","text":text}]}

def _design_context():
    tasks=get_factory_tasks()
    active=[{
        "id":x["id"],"title":x["title"],"description":x.get("description",""),
        "status":x["status"],"progress":x.get("execution_progress",0)
    } for x in tasks["tasks"] if x["status"]!="done"][:20]
    return {
        "product":"Blackbox Lab FactoryOS",
        "version":APP_VERSION,
        "live_url":"https://blackboxlab-factoryos.onrender.com",
        "design_goal":[
            "Premium dark cyber-operations product, not a game HUD.",
            "Agent Office should feel like a believable modern AI operations room with clear worker identity and status.",
            "Match the user's reference direction: cinematic office, realistic depth, restrained neon, strong hierarchy, dense but readable dashboard.",
            "Avoid cartoonish people, excessive borders, tiny unreadable labels and decorative clutter.",
            "Every worker must remain clickable; hover shows live progress; click opens history, artifacts, time, tokens, cost and MCP configuration.",
            "Keep EN / UK / RU localization and preserve the human approval gate before publishing."
        ],
        "current_structure":[
            "Left navigation",
            "Top command/search bar",
            "Five-step mission strip",
            "Agent Office scene",
            "Connections rail",
            "Factory Supervisor",
            "Content Pipeline",
            "Jobs + selected-job detail",
            "Build Progress roadmap"
        ],
        "active_build_tasks":active,
        "design_partner_mode":"Claude Free can connect TO this FactoryOS MCP server as a custom connector. Claude.ai itself is not used as an MCP endpoint."
    }

def _create_design_task_from_review(args):
    title=(args.get("title") or "Design review improvements").strip()[:180]
    summary=(args.get("summary") or "").strip()
    recs=args.get("recommendations") or []
    criteria=args.get("acceptance_criteria") or []
    lines=[]
    if summary:
        lines.append("Design review summary:\n"+summary)
    if recs:
        lines.append("Recommended changes:\n" + "\n".join(f"- {str(x).strip()}" for x in recs if str(x).strip()))
    if criteria:
        lines.append("Acceptance criteria:\n" + "\n".join(f"- {str(x).strip()}" for x in criteria if str(x).strip()))
    description="\n\n".join(lines).strip() or "Implement the approved design review while preserving current functionality and observability."
    task_id=str(uuid.uuid4()); now=ts()
    con=db()
    next_order=con.execute("SELECT COALESCE(MAX(order_index),0)+10 n FROM factory_tasks").fetchone()["n"]
    con.execute("""INSERT INTO factory_tasks(id,title,description,category,priority,status,owner,order_index,created_at,updated_at,builder_state)
                   VALUES(?,?,?,?,?,'todo',?,?,?,?,'idle')""",
                (task_id,title,description,"design","high","Design Partner",next_order,now,now))
    con.commit(); con.close()
    ensure_factory_task_steps(task_id)
    event(None,f"Design Partner added roadmap task: {title}")
    return {"ok":True,"task_id":task_id,"status":"todo","note":"Created as planned only. Human must explicitly start the build."}

FACTORY_MCP_TOOLS=[
    {
      "name":"get_design_context",
      "description":"Read the current FactoryOS design goals, layout structure, live URL and active build tasks before proposing UI changes.",
      "inputSchema":{"type":"object","properties":{},"additionalProperties":False}
    },
    {
      "name":"list_build_tasks",
      "description":"List FactoryOS roadmap tasks with status, progress and descriptions.",
      "inputSchema":{"type":"object","properties":{"status":{"type":"string","enum":["all","todo","in_progress","done","blocked"]}},"additionalProperties":False}
    },
    {
      "name":"submit_design_review",
      "description":"Submit an approved UI/UX review into FactoryOS as a planned design roadmap task. This never starts implementation automatically.",
      "inputSchema":{
        "type":"object",
        "properties":{
          "title":{"type":"string"},
          "summary":{"type":"string"},
          "recommendations":{"type":"array","items":{"type":"string"}},
          "acceptance_criteria":{"type":"array","items":{"type":"string"}}
        },
        "required":["title","summary","recommendations","acceptance_criteria"],
        "additionalProperties":False
      }
    }
]

@app.post("/mcp")
async def factory_mcp(request: Request):
    if not FACTORY_MCP_TOKEN:
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32001,"message":"FactoryOS MCP connector is disabled until FACTORY_MCP_TOKEN is configured."}},status_code=503)
    if not _factory_mcp_authorized(request):
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32000,"message":"Unauthorized"}},status_code=401)
    try:
        payload=await request.json()
    except Exception:
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}},status_code=400)
    req_id=payload.get("id")
    method=payload.get("method")
    params=payload.get("params") or {}
    if method=="initialize":
        result={
          "protocolVersion":params.get("protocolVersion") or "2025-03-26",
          "capabilities":{"tools":{"listChanged":False}},
          "serverInfo":{"name":"Blackbox Lab FactoryOS","version":APP_VERSION}
        }
        return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":result})
    if method=="notifications/initialized":
        return JSONResponse({},status_code=202)
    if method=="ping":
        return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":{}})
    if method=="tools/list":
        return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":{"tools":FACTORY_MCP_TOOLS}})
    if method=="tools/call":
        name=params.get("name"); args=params.get("arguments") or {}
        try:
            if name=="get_design_context":
                result=_factory_mcp_text(_design_context())
            elif name=="list_build_tasks":
                data=get_factory_tasks()
                wanted=args.get("status","all")
                rows=data["tasks"] if wanted=="all" else [x for x in data["tasks"] if x["status"]==wanted]
                result=_factory_mcp_text([{
                    "id":x["id"],"title":x["title"],"description":x.get("description",""),
                    "status":x["status"],"progress":x.get("execution_progress",0),
                    "priority":x["priority"],"owner":x["owner"]
                } for x in rows])
            elif name=="submit_design_review":
                created=_create_design_task_from_review(args)
                await broadcast({"type":"design_review_task","taskId":created["task_id"]})
                result=_factory_mcp_text(created)
            else:
                return JSONResponse({"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Unknown tool"}},status_code=404)
            return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":result})
        except Exception as exc:
            return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":{"isError":True,"content":[{"type":"text","text":str(exc)}]}})
    return JSONResponse({"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Method not found"}},status_code=404)

@app.get("/mcp")
def factory_mcp_info(request: Request):
    if not FACTORY_MCP_TOKEN:
        return JSONResponse({"enabled":False,"detail":"Set FACTORY_MCP_TOKEN in Render to enable the Claude/remote MCP connector."},status_code=503)
    if not _factory_mcp_authorized(request):
        return JSONResponse({"enabled":True,"detail":"Authentication required: Bearer token or ?key= token."},status_code=401)
    return {"enabled":True,"server":"Blackbox Lab FactoryOS","version":APP_VERSION,"tools":[x["name"] for x in FACTORY_MCP_TOOLS]}

@app.get("/health")
def health():
    verification=get_paid_verification()
    return {
        "ok": True,
        "service": "factoryos",
        "version": APP_VERSION,
        "factory_mcp_configured": bool(FACTORY_MCP_TOKEN),
        "llm_configured": bool(FACTORY_LLM_API_KEY),
        "llm_model": FACTORY_LLM_MODEL if FACTORY_LLM_API_KEY else None,
        "paid_verification": {
            "status": verification.get("status"),
            "live_runs": int(verification.get("live_runs") or 0),
            "total_tokens": int(verification.get("input_tokens") or 0) + int(verification.get("output_tokens") or 0),
            "cost_usd": round(float(verification.get("cost_usd") or 0), 6),
        },
    }

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
    "LLM": {
        "state":"connected" if FACTORY_LLM_API_KEY else "demo",
        "detail":f"Live model: {FACTORY_LLM_MODEL}" if FACTORY_LLM_API_KEY else "Live adapter ready; set FACTORY_LLM_API_KEY",
    },
    "Voice": {"state":"not_configured","detail":"Provider not selected"},
    "Video": {"state":"not_configured","detail":"Provider not selected"},
}

def ts(): return datetime.now(timezone.utc).isoformat()

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def get_paid_verification(tag=VERIFICATION_EVIDENCE_TAG):
    if not tag:
        return {"status":"disabled","live_runs":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}
    con=db()
    row=con.execute("SELECT * FROM system_verifications WHERE tag=?",(tag,)).fetchone()
    con.close()
    return dict(row) if row else {"tag":tag,"status":"pending","live_runs":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}

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
    CREATE TABLE IF NOT EXISTS system_verifications(
      tag TEXT PRIMARY KEY,
      status TEXT NOT NULL,
      job_id TEXT,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      live_runs INTEGER DEFAULT 0,
      input_tokens INTEGER DEFAULT 0,
      output_tokens INTEGER DEFAULT 0,
      cost_usd REAL DEFAULT 0,
      detail TEXT DEFAULT ''
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
    CREATE TABLE IF NOT EXISTS source_signals(
      id TEXT PRIMARY KEY,
      fingerprint TEXT UNIQUE NOT NULL,
      source_type TEXT NOT NULL DEFAULT 'manual',
      title TEXT NOT NULL,
      url TEXT DEFAULT '',
      content TEXT DEFAULT '',
      topic TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'new',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_source_signals_status ON source_signals(status, created_at DESC);
    CREATE TABLE IF NOT EXISTS content_ideas(
      id TEXT PRIMARY KEY,
      title TEXT NOT NULL,
      topic TEXT DEFAULT '',
      angle TEXT DEFAULT '',
      audience TEXT DEFAULT '',
      why_now TEXT DEFAULT '',
      source_signal_ids_json TEXT DEFAULT '[]',
      source_links_json TEXT DEFAULT '[]',
      status TEXT NOT NULL DEFAULT 'generated',
      score REAL DEFAULT 0,
      risk_flags_json TEXT DEFAULT '[]',
      complexity TEXT DEFAULT 'medium',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      provenance_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_content_ideas_status ON content_ideas(status, score DESC, created_at DESC);
    CREATE TABLE IF NOT EXISTS production_variants(
      id TEXT PRIMARY KEY,
      batch_id TEXT NOT NULL,
      job_id TEXT NOT NULL,
      ordinal INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'candidate',
      angle TEXT DEFAULT '',
      angle_reason TEXT DEFAULT '',
      hook TEXT DEFAULT '',
      hook_rationale TEXT DEFAULT '',
      script TEXT DEFAULT '',
      optimized_hook TEXT DEFAULT '',
      edited_script TEXT DEFAULT '',
      fact_check_json TEXT DEFAULT '{}',
      qa_json TEXT DEFAULT '{}',
      decision_reason TEXT DEFAULT '',
      allocated_cost_usd REAL DEFAULT 0,
      provenance_json TEXT DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_production_variants_job ON production_variants(job_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_production_variants_batch ON production_variants(batch_id, ordinal);
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
    CREATE TABLE IF NOT EXISTS mcp_call_log(
      id TEXT PRIMARY KEY,
      agent TEXT NOT NULL,
      connection_id TEXT NOT NULL,
      run_id TEXT,
      job_id TEXT,
      action TEXT NOT NULL,
      tool_name TEXT,
      status TEXT NOT NULL,
      started_at TEXT NOT NULL,
      finished_at TEXT,
      duration_ms INTEGER NOT NULL DEFAULT 0,
      error TEXT,
      result_preview TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_mcp_call_agent ON mcp_call_log(agent, started_at DESC);
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
    mcp_cols={row["name"] for row in con.execute("PRAGMA table_info(agent_mcp_connections)").fetchall()}
    for name,ddl in [
        ("allowed_tools_json","TEXT NOT NULL DEFAULT '[]'"),
        ("last_check_at","TEXT"),
        ("last_error","TEXT DEFAULT ''"),
    ]:
        if name not in mcp_cols:
            con.execute(f"ALTER TABLE agent_mcp_connections ADD COLUMN {name} {ddl}")
    task_cols={row["name"] for row in con.execute("PRAGMA table_info(factory_tasks)").fetchall()}
    for name,ddl in [
        ("builder_state","TEXT NOT NULL DEFAULT 'idle'"),
        ("requested_at","TEXT"),
        ("builder_note","TEXT DEFAULT ''"),
        ("workflow_run_id","TEXT"),
        ("workflow_url","TEXT"),
        ("workflow_status","TEXT"),
    ]:
        if name not in task_cols:
            con.execute(f"ALTER TABLE factory_tasks ADD COLUMN {name} {ddl}")
    idea_cols={row["name"] for row in con.execute("PRAGMA table_info(content_ideas)").fetchall()}
    for name,ddl in [
        ("research_json","TEXT NOT NULL DEFAULT '{}'"),
        ("strategy_json","TEXT NOT NULL DEFAULT '{}'"),
        ("verification_json","TEXT NOT NULL DEFAULT '{}'"),
        ("novelty_evidence","TEXT DEFAULT ''"),
        ("rejection_reason","TEXT DEFAULT ''"),
        ("verified_at","TEXT"),
    ]:
        if name not in idea_cols:
            con.execute(f"ALTER TABLE content_ideas ADD COLUMN {name} {ddl}")
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
      ("instant-builder","Instant website-to-Builder trigger","Start a FactoryOS roadmap task immediately through GitHub Actions, with live workflow status and hourly fallback.","automation","high","done","Factory Builder",99),
      ("design-partner","Claude design partner via FactoryOS MCP","Expose a secure remote MCP connector so Claude Free can read FactoryOS design context and submit structured design reviews back into the roadmap without paid API calls or automatic code execution.","design","high","in_progress","Design Partner",100),
      ("design-refresh","Dashboard visual redesign","Refine spacing, hierarchy, cards and interactive states while preserving observability.","design","high","in_progress","Factory Builder",99),
      ("mcp-execution","MCP execution bridge","Invoke approved MCP tools from a worker run with capability restrictions and audit logs.","connectors","high","in_progress","Factory Builder",100),
      ("live-llm","Live LLM worker adapter","Replace demo Scout/Researcher/Verifier/Writer execution with real model calls and usage accounting.","intelligence","high","todo","Factory Builder",110),
      ("mobile-parity","Mobile control-room parity","Keep workers, navigation, drawers, jobs, pipeline and operational actions fully usable on phone layouts.","product","high","done","Factory Builder",115),
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

def github_api(method, path, payload=None):
    if not GITHUB_TOKEN:
        raise RuntimeError("FACTORY_GITHUB_TOKEN is not configured")
    url=f"https://api.github.com/repos/{GITHUB_REPO}{path}"
    data=None
    headers={
        "Accept":"application/vnd.github+json",
        "Authorization":f"Bearer {GITHUB_TOKEN}",
        "X-GitHub-Api-Version":"2022-11-28",
        "User-Agent":"BlackboxLab-FactoryOS",
    }
    if payload is not None:
        data=json.dumps(payload).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urlrequest.Request(url,data=data,headers=headers,method=method)
    try:
        with urlrequest.urlopen(req,timeout=12) as resp:
            raw=resp.read().decode("utf-8","replace")
            return json.loads(raw) if raw else {}
    except urlerror.HTTPError as exc:
        body=exc.read().decode("utf-8","replace")
        raise RuntimeError(f"GitHub API {exc.code}: {body[:500]}") from exc
    except Exception as exc:
        raise RuntimeError(f"GitHub API error: {exc}") from exc

async def dispatch_builder_workflow(task):
    payload={
        "ref":"main",
        "inputs":{
            "task_id":task["id"],
            "title":task["title"],
            "description":task["description"] or "",
            "priority":task["priority"] or "medium",
        }
    }
    await asyncio.to_thread(github_api,"POST",f"/actions/workflows/{BUILDER_WORKFLOW}/dispatches",payload)
    return True

def _workflow_step_to_task_step(name):
    n=(name or "").lower()
    mapping=[
        ("understand task","understand"),
        ("inspect current","inspect"),
        ("plan the smallest","plan"),
        ("baseline ci","test"),
        ("queue ai implementation","implement"),
    ]
    for phrase,key in mapping:
        if phrase in n:
            return key
    return None

async def track_builder_dispatch(task_id, requested_at):
    # GitHub may take a few seconds to materialize a workflow_dispatch run.
    run=None
    for _ in range(18):
        await asyncio.sleep(4)
        try:
            runs=await asyncio.to_thread(
                github_api,"GET",
                f"/actions/workflows/{BUILDER_WORKFLOW}/runs?event=workflow_dispatch&branch=main&per_page=20"
            )
            for candidate in runs.get("workflow_runs",[]):
                title=candidate.get("display_title") or candidate.get("name") or ""
                if task_id in title:
                    run=candidate; break
            if run: break
        except Exception as exc:
            con=db(); con.execute("UPDATE factory_tasks SET builder_note=?,workflow_status=? WHERE id=?",
                                  (f"Workflow lookup error: {exc}","lookup_error",task_id)); con.commit(); con.close()
    if not run:
        con=db(); con.execute("""UPDATE factory_tasks SET builder_state='blocked',workflow_status='not_found',
                                 builder_note=? WHERE id=?""",
                              ("GitHub accepted the dispatch but the workflow run was not found.",task_id))
        con.commit(); con.close()
        await broadcast({"type":"builder_workflow","taskId":task_id,"status":"not_found"})
        return

    run_id=str(run["id"]); html_url=run.get("html_url") or ""
    con=db(); con.execute("""UPDATE factory_tasks SET builder_state='active',workflow_run_id=?,workflow_url=?,
                             workflow_status=?,builder_note=? WHERE id=?""",
                          (run_id,html_url,run.get("status") or "queued","GitHub Builder preflight is running.",task_id))
    con.commit(); con.close()
    await broadcast({"type":"builder_workflow","taskId":task_id,"status":"in_progress","runId":run_id})

    while True:
        await asyncio.sleep(5)
        try:
            run_data=await asyncio.to_thread(github_api,"GET",f"/actions/runs/{run_id}")
            jobs=await asyncio.to_thread(github_api,"GET",f"/actions/runs/{run_id}/jobs?per_page=20")
        except Exception as exc:
            con=db(); con.execute("UPDATE factory_tasks SET builder_note=? WHERE id=?",
                                  (f"Workflow tracking error: {exc}",task_id)); con.commit(); con.close()
            continue

        for job in jobs.get("jobs",[]):
            for step in job.get("steps",[]):
                task_step=_workflow_step_to_task_step(step.get("name"))
                if not task_step: continue
                status=step.get("status")
                conclusion=step.get("conclusion")
                if status=="completed" and conclusion=="success":
                    set_factory_task_step(task_id,task_step,"done",100)
                elif status=="completed" and conclusion not in (None,"success","skipped"):
                    set_factory_task_step(task_id,task_step,"blocked",35)
                elif status=="in_progress":
                    set_factory_task_step(task_id,task_step,"in_progress",55)

        gh_status=run_data.get("status") or "unknown"
        conclusion=run_data.get("conclusion")
        con=db()
        if gh_status=="completed":
            if conclusion=="success":
                # Immediate workflow handles kickoff/preflight. Actual code implementation continues in the autonomous Builder.
                impl=next((x for x in get_factory_task_steps(task_id) if x["step_key"]=="implement"),None)
                if impl and impl["status"]!="done":
                    set_factory_task_step(task_id,"implement","in_progress",20)
                con.execute("""UPDATE factory_tasks SET builder_state='active',workflow_status='completed',
                               builder_note=? WHERE id=?""",
                            ("Immediate GitHub preflight complete. Autonomous Factory Builder is continuing implementation.",task_id))
            else:
                con.execute("""UPDATE factory_tasks SET builder_state='blocked',workflow_status=?,builder_note=? WHERE id=?""",
                            (conclusion or "failed","GitHub Builder preflight failed. Inspect the workflow run.",task_id))
            con.commit(); con.close()
            await broadcast({"type":"builder_workflow","taskId":task_id,"status":conclusion or "completed"})
            return
        con.execute("UPDATE factory_tasks SET workflow_status=?,builder_state='active' WHERE id=?",(gh_status,task_id))
        con.commit(); con.close()
        await broadcast({"type":"builder_workflow","taskId":task_id,"status":gh_status})

async def reconcile_builder_workflows_once():
    if not GITHUB_TOKEN:
        return
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT id,workflow_run_id,workflow_status,status
                                          FROM factory_tasks
                                          WHERE status='in_progress' AND workflow_run_id IS NOT NULL
                                          ORDER BY updated_at""").fetchall()]
    con.close()
    for task in rows:
        run_id=str(task.get("workflow_run_id") or "").strip()
        if not run_id:
            continue
        try:
            run_data=await asyncio.to_thread(github_api,"GET",f"/actions/runs/{run_id}")
            jobs=await asyncio.to_thread(github_api,"GET",f"/actions/runs/{run_id}/jobs?per_page=20")
        except Exception:
            continue
        for job in jobs.get("jobs",[]):
            for step in job.get("steps",[]):
                task_step=_workflow_step_to_task_step(step.get("name"))
                if not task_step:
                    continue
                status=step.get("status"); conclusion=step.get("conclusion")
                if status=="completed" and conclusion=="success":
                    set_factory_task_step(task["id"],task_step,"done",100)
                elif status=="completed" and conclusion not in (None,"success","skipped"):
                    set_factory_task_step(task["id"],task_step,"blocked",35)
                elif status=="in_progress":
                    set_factory_task_step(task["id"],task_step,"in_progress",55)
        gh_status=run_data.get("status") or "unknown"
        conclusion=run_data.get("conclusion")
        con=db()
        if gh_status=="completed":
            if conclusion=="success":
                impl=next((x for x in get_factory_task_steps(task["id"]) if x["step_key"]=="implement"),None)
                if impl and impl["status"]=="todo":
                    set_factory_task_step(task["id"],"implement","in_progress",20)
                con.execute("""UPDATE factory_tasks SET builder_state='active',workflow_status='completed',
                               builder_note=? WHERE id=?""",
                            ("GitHub preflight completed. Waiting for the code implementation worker or a manual resume.",task["id"]))
            else:
                con.execute("""UPDATE factory_tasks SET builder_state='blocked',workflow_status=?,builder_note=? WHERE id=?""",
                            (conclusion or "failed","GitHub Builder preflight failed. Use Start build to retry.",task["id"]))
        else:
            con.execute("""UPDATE factory_tasks SET builder_state='active',workflow_status=?,builder_note=?
                           WHERE id=?""",
                        (gh_status,"GitHub Builder preflight is running.",task["id"]))
        con.commit(); con.close()

async def resume_stale_started_tasks():
    if not GITHUB_TOKEN:
        return
    live_states={"queued","in_progress","waiting","pending","requested","dispatching"}
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT * FROM factory_tasks
                                          WHERE status='in_progress' AND requested_at IS NOT NULL
                                          ORDER BY requested_at""").fetchall()]
    con.close()
    for task in rows:
        if (task.get("workflow_status") or "") in live_states:
            continue
        try:
            await dispatch_builder_workflow(task)
            con=db()
            con.execute("""UPDATE factory_tasks SET builder_state='queued',workflow_status='dispatching',
                           workflow_run_id=NULL,workflow_url=NULL,builder_note=?,updated_at=? WHERE id=?""",
                        ("Recovered after restart: immediate GitHub Builder preflight re-dispatched.",ts(),task["id"]))
            con.commit(); con.close()
            asyncio.create_task(track_builder_dispatch(task["id"],task.get("requested_at") or ts()))
            print(json.dumps({"event":"BUILDER_TASK_RECOVERED","task_id":task["id"]}),flush=True)
        except Exception as exc:
            con=db()
            con.execute("UPDATE factory_tasks SET builder_note=? WHERE id=?",
                        (f"Recovery dispatch failed; manual Resume remains available. {str(exc)[:250]}",task["id"]))
            con.commit(); con.close()

async def builder_reconcile_loop():
    await resume_stale_started_tasks()
    while True:
        try:
            await reconcile_builder_workflows_once()
            await broadcast({"type":"builder_reconcile"})
        except Exception as exc:
            print(json.dumps({"event":"BUILDER_RECONCILE_ERROR","error":str(exc)[:300]}),flush=True)
        await asyncio.sleep(15)

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
    allowed_tools: list[str] = []

class McpToolCall(BaseModel):
    tool_name: str
    arguments: dict = {}

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


class SignalCreate(BaseModel):
    title: str
    content: str = ""
    url: str = ""
    source_type: str = "manual"
    topic: str = ""

class IdeaCreate(BaseModel):
    title: str
    topic: str = ""
    angle: str = ""
    audience: str = ""
    why_now: str = ""
    source_signal_ids: list[str] = []
    source_links: list[str] = []
    score: float = 0
    risk_flags: list[str] = []
    complexity: str = "medium"

class IdeaStatus(BaseModel):
    status: str

class IdeaGenerateRequest(BaseModel):
    signal_ids: list[str] = []
    max_ideas: int = 5
    language: str = "English"

class IdeaProcessRequest(BaseModel):
    idea_ids: list[str] = []
    max_ideas: int = 3
    language: str = "English"

def event(job_id, message):
    con=db(); con.execute("INSERT INTO events(job_id,ts,message) VALUES(?,?,?)",(job_id,ts(),message)); con.commit(); con.close()

def job_dict(r): return dict(r) if r else None

def get_jobs():
    con=db(); rows=con.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall(); con.close(); return [dict(x) for x in rows]

def get_job(job_id):
    con=db(); row=con.execute("SELECT * FROM jobs WHERE id=?",(job_id,)).fetchone(); con.close()
    return dict(row) if row else None


def _signal_fingerprint(source_type, title, url, content):
    normalized="|".join([
        (source_type or "manual").strip().lower(),
        (url or "").strip().lower(),
        " ".join((title or "").split()).lower(),
        " ".join((content or "").split()).lower(),
    ])
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def _decode_json(value, fallback):
    try:
        return json.loads(value or "")
    except Exception:
        return fallback

def ingest_source_signal(payload):
    title=" ".join((payload.title or "").split()).strip()
    if not title:
        raise ValueError("Signal title is required")
    source_type=(payload.source_type or "manual").strip().lower()[:40] or "manual"
    url=(payload.url or "").strip()
    content=(payload.content or "").strip()
    topic=(payload.topic or "").strip()
    fingerprint=_signal_fingerprint(source_type,title,url,content)
    con=db()
    existing=con.execute("SELECT * FROM source_signals WHERE fingerprint=?",(fingerprint,)).fetchone()
    if existing:
        con.close()
        return {"created":False,"duplicate":True,"signal":dict(existing)}
    signal_id=str(uuid.uuid4()); now=ts()
    con.execute("""INSERT INTO source_signals(id,fingerprint,source_type,title,url,content,topic,status,created_at,updated_at,meta_json)
                   VALUES(?,?,?,?,?,?,?,'new',?,?,?)""",
                (signal_id,fingerprint,source_type,title,url,content,topic,now,now,json.dumps({"ingested_by":"manual_api"})))
    con.commit()
    row=con.execute("SELECT * FROM source_signals WHERE id=?",(signal_id,)).fetchone()
    con.close()
    return {"created":True,"duplicate":False,"signal":dict(row)}

def create_content_idea(payload):
    title=" ".join((payload.title or "").split()).strip()
    if not title:
        raise ValueError("Idea title is required")
    signal_ids=list(dict.fromkeys([str(x).strip() for x in (payload.source_signal_ids or []) if str(x).strip()]))
    links=list(dict.fromkeys([str(x).strip() for x in (payload.source_links or []) if str(x).strip()]))
    con=db()
    if signal_ids:
        placeholders=",".join("?" for _ in signal_ids)
        found={x["id"] for x in con.execute(f"SELECT id FROM source_signals WHERE id IN ({placeholders})",signal_ids).fetchall()}
        missing=[x for x in signal_ids if x not in found]
        if missing:
            con.close()
            raise ValueError("Unknown source signal id(s): "+", ".join(missing))
    idea_id=str(uuid.uuid4()); now=ts()
    provenance={"created_by":"manual_api","source_signal_ids":signal_ids}
    con.execute("""INSERT INTO content_ideas(
                     id,title,topic,angle,audience,why_now,source_signal_ids_json,source_links_json,
                     status,score,risk_flags_json,complexity,created_at,updated_at,provenance_json
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (idea_id,title,(payload.topic or "").strip(),(payload.angle or "").strip(),
                 (payload.audience or "").strip(),(payload.why_now or "").strip(),
                 json.dumps(signal_ids),json.dumps(links),"generated",float(payload.score or 0),
                 json.dumps(payload.risk_flags or []),(payload.complexity or "medium").strip(),
                 now,now,json.dumps(provenance)))
    con.commit()
    row=con.execute("SELECT * FROM content_ideas WHERE id=?",(idea_id,)).fetchone()
    con.close()
    return _idea_dict(row)

def _idea_dict(row):
    if not row:
        return None
    item=dict(row)
    item["source_signal_ids"]=_decode_json(item.pop("source_signal_ids_json","[]"),[])
    item["source_links"]=_decode_json(item.pop("source_links_json","[]"),[])
    item["risk_flags"]=_decode_json(item.pop("risk_flags_json","[]"),[])
    item["provenance"]=_decode_json(item.pop("provenance_json","{}"),{})
    item["research"]=_decode_json(item.pop("research_json","{}"),{})
    item["strategy"]=_decode_json(item.pop("strategy_json","{}"),{})
    item["verification"]=_decode_json(item.pop("verification_json","{}"),{})
    return item

def get_content_brain(limit=50):
    con=db()
    signals=[dict(x) for x in con.execute("""SELECT * FROM source_signals
                                             ORDER BY created_at DESC LIMIT ?""",(limit,)).fetchall()]
    ideas=[_idea_dict(x) for x in con.execute("""SELECT * FROM content_ideas
                                                 ORDER BY CASE status WHEN 'selected' THEN 0 WHEN 'shortlisted' THEN 1
                                                                      WHEN 'generated' THEN 2 WHEN 'rejected' THEN 3 ELSE 4 END,
                                                          score DESC, created_at DESC LIMIT ?""",(limit,)).fetchall()]
    signal_counts={x["status"]:x["c"] for x in con.execute("SELECT status,COUNT(*) c FROM source_signals GROUP BY status").fetchall()}
    idea_counts={x["status"]:x["c"] for x in con.execute("SELECT status,COUNT(*) c FROM content_ideas GROUP BY status").fetchall()}
    con.close()
    return {
        "summary":{
            "signals":sum(signal_counts.values()),
            "new_signals":int(signal_counts.get("new",0)),
            "ideas":sum(idea_counts.values()),
            "generated":int(idea_counts.get("generated",0)),
            "shortlisted":int(idea_counts.get("shortlisted",0)),
            "selected":int(idea_counts.get("selected",0)),
            "rejected":int(idea_counts.get("rejected",0)),
            "verified":sum(1 for x in ideas if x.get("verified_at")),
            "feeds_configured":len(FACTORY_SIGNAL_FEEDS),
        },
        "adapters":{
            "manual":{"enabled":True,"mode":"push"},
            "rss":{"enabled":bool(FACTORY_SIGNAL_FEEDS),"mode":"scheduled","feeds":len(FACTORY_SIGNAL_FEEDS),
                   "interval_minutes":FACTORY_SIGNAL_COLLECTION_MINUTES},
        },
        "signals":signals,
        "ideas":ideas,
    }

def _parse_idea_candidates(raw):
    text=(raw or "").strip()
    if text.startswith("```"):
        lines=text.splitlines()
        if lines and lines[0].startswith("```"):
            lines=lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines=lines[:-1]
        text="\n".join(lines).strip()
    start=text.find("[")
    end=text.rfind("]")
    if start<0 or end<=start:
        raise ValueError("Idea generator did not return a JSON array")
    data=json.loads(text[start:end+1])
    if not isinstance(data,list):
        raise ValueError("Idea generator response must be a JSON array")
    return [x for x in data if isinstance(x,dict)]

async def generate_ideas_from_signals(payload):
    if not FACTORY_LLM_API_KEY:
        raise RuntimeError("Live LLM provider is not configured")
    max_ideas=max(1,min(8,int(payload.max_ideas or 5)))
    con=db()
    pool=[dict(x) for x in con.execute(
        "SELECT * FROM source_signals ORDER BY created_at DESC LIMIT 50"
    ).fetchall()]
    con.close()
    wanted={str(x).strip() for x in (payload.signal_ids or []) if str(x).strip()}
    rows=[x for x in pool if not wanted or x["id"] in wanted][:12]
    if wanted and len({x["id"] for x in rows})!=len(wanted):
        raise ValueError("One or more source signal ids are unknown")
    if not rows:
        raise ValueError("No source signals available")
    usage=get_usage_summary()
    reserve=FACTORY_LLM_MAX_OUTPUT_TOKENS * FACTORY_LLM_OUTPUT_USD_PER_1M / 1000000
    if usage["today_cost_usd"] + reserve > FACTORY_DAILY_BUDGET_USD:
        raise RuntimeError("Daily provider budget would be exceeded by the next Content Brain call")
    signals="\n\n".join(
        f"SIGNAL_ID: {x['id']}\nTITLE: {x['title']}\nURL: {x.get('url') or '(none)'}\nTOPIC: {x.get('topic') or '(none)'}\nCONTENT: {_trim_llm_context(x.get('content',''),1600)}"
        for x in rows
    )
    pseudo_job={
        "title":"Content Brain idea shortlist",
        "brief":(
            f"Create up to {max_ideas} distinct short-form content ideas from these signals. "
            "Return only a JSON array. Each item must include title, topic, angle, audience, why_now, "
            "source_signal_ids, source_links, score from 0 to 1, risk_flags, and complexity. "
            "Use only supplied SIGNAL_ID values and never invent sources.\n\n"+signals
        ),
        "language":payload.language or "English",
        "format":"Short-form ideas",
        "presenter":"FactoryOS",
    }
    run_id=start_agent_run("Scout",None,"content_brain",model=FACTORY_LLM_MODEL)
    try:
        result=await asyncio.wait_for(
            asyncio.to_thread(_call_live_llm,"Scout",pseudo_job,{"artifacts":[],"missing":[]}),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        candidates=_parse_idea_candidates(result["content"])[:max_ideas]
        created=[]
        allowed={x["id"] for x in rows}
        for item in candidates:
            title=" ".join(str(item.get("title") or "").split()).strip()
            if not title:
                continue
            source_ids=[str(x) for x in (item.get("source_signal_ids") or []) if str(x) in allowed] or list(allowed)
            links=[str(x).strip() for x in (item.get("source_links") or []) if str(x).strip()]
            try:
                score=max(0.0,min(1.0,float(item.get("score") or 0)))
            except Exception:
                score=0.0
            idea=create_content_idea(IdeaCreate(
                title=title,topic=str(item.get("topic") or ""),angle=str(item.get("angle") or ""),
                audience=str(item.get("audience") or ""),why_now=str(item.get("why_now") or ""),
                source_signal_ids=source_ids,source_links=links,score=score,
                risk_flags=[str(x) for x in (item.get("risk_flags") or [])],
                complexity=str(item.get("complexity") or "medium"),
            ))
            provenance={"created_by":"content_brain_llm","worker":"Scout","run_id":run_id,"model":result.get("model")}
            con=db(); con.execute("UPDATE content_ideas SET provenance_json=? WHERE id=?",(json.dumps(provenance),idea["id"])); con.commit(); con.close()
            idea["provenance"]=provenance
            created.append(idea)
        created.sort(key=lambda x:float(x.get("score") or 0),reverse=True)
        for idea in created[:3]:
            con=db(); con.execute("UPDATE content_ideas SET status='shortlisted',updated_at=? WHERE id=?",(ts(),idea["id"])); con.commit(); con.close()
            idea["status"]="shortlisted"
        con=db()
        for signal in rows:
            con.execute("UPDATE source_signals SET status='processed',updated_at=? WHERE id=?",(ts(),signal["id"]))
        con.commit(); con.close()
        save_artifact("Scout","analysis","Content Brain raw shortlist",result["content"],run_id=run_id,meta={"content_brain":True,"idea_count":len(created)})
        finish_agent_run(run_id,status="completed",input_tokens=result["input_tokens"],output_tokens=result["output_tokens"],cost_usd=result["cost_usd"],meta={"content_brain":True,"idea_count":len(created)})
        return {"run_id":run_id,"model":result.get("model"),"cost_usd":round(float(result.get("cost_usd") or 0),6),"ideas":created}
    except Exception as exc:
        finish_agent_run(run_id,status="failed",error=str(exc),meta={"content_brain":True})
        raise


def _parse_json_object(raw):
    text=(raw or "").strip()
    if text.startswith("```"):
        lines=text.splitlines()
        if lines and lines[0].startswith("```"):
            lines=lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines=lines[:-1]
        text="\n".join(lines).strip()
    start=text.find("{"); end=text.rfind("}")
    if start<0 or end<=start:
        raise ValueError("Worker did not return a JSON object")
    data=json.loads(text[start:end+1])
    if not isinstance(data,dict):
        raise ValueError("Worker response must be a JSON object")
    return data

def _content_brain_llm(role, system, user, max_output_tokens=900):
    if not FACTORY_LLM_API_KEY:
        raise RuntimeError("Live LLM provider is not configured")
    limit=max(128,min(1200,int(max_output_tokens)))
    if FACTORY_LLM_API_MODE=="chat_completions":
        payload={
            "model":FACTORY_LLM_MODEL,
            "max_completion_tokens":limit,
            "messages":[{"role":"system","content":system},{"role":"user","content":user}],
        }
    else:
        payload={
            "model":FACTORY_LLM_MODEL,"max_output_tokens":limit,
            "instructions":system,"input":user,"store":False,
        }
    req=urlrequest.Request(
        _llm_endpoint(),
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization":f"Bearer {FACTORY_LLM_API_KEY}","Content-Type":"application/json","Accept":"application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req,timeout=max(15,AGENT_TIMEOUT_SECONDS)) as resp:
            raw=resp.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        body=exc.read().decode("utf-8","replace")[:1000]
        low=body.lower()
        if exc.code==429 and ("credit_balance_exhausted" in low or "insufficient_quota" in low or "no credits remaining" in low):
            raise RuntimeError("OpenAI API balance exhausted. Add API credits before continuing Content Brain.") from exc
        if exc.code==429:
            raise RuntimeError("OpenAI API rate limit reached. Retry Content Brain after a short wait.") from exc
        if exc.code in (401,403):
            raise RuntimeError("OpenAI API authentication failed. Check FACTORY_LLM_API_KEY and permissions.") from exc
        raise RuntimeError(f"LLM provider HTTP {exc.code}: {body}") from exc
    result=json.loads(raw)
    if FACTORY_LLM_API_MODE=="chat_completions":
        content=result["choices"][0]["message"]["content"]
        if isinstance(content,list):
            content="\n".join(x.get("text","") for x in content if isinstance(x,dict) and x.get("text"))
    else:
        parts=[]
        for item in result.get("output") or []:
            if item.get("type")!="message":
                continue
            for part in item.get("content") or []:
                if part.get("type")=="output_text" and part.get("text"):
                    parts.append(part["text"])
        content="\n".join(parts)
    content=str(content or "").strip()
    if not content:
        raise RuntimeError(f"{role} returned empty content")
    usage=result.get("usage") or {}
    input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    cost_usd=(input_tokens*FACTORY_LLM_INPUT_USD_PER_1M/1_000_000 + output_tokens*FACTORY_LLM_OUTPUT_USD_PER_1M/1_000_000)
    return {"content":content,"model":result.get("model") or FACTORY_LLM_MODEL,
            "input_tokens":input_tokens,"output_tokens":output_tokens,"cost_usd":cost_usd,
            "provider_request_id":result.get("id")}

def _content_brain_budget_guard(output_tokens=900):
    usage=get_usage_summary()
    reserve=max(128,int(output_tokens))*FACTORY_LLM_OUTPUT_USD_PER_1M/1_000_000
    if usage["today_cost_usd"] + reserve > FACTORY_DAILY_BUDGET_USD:
        raise RuntimeError("Daily provider budget would be exceeded by the next Content Brain call")
    return reserve

def _idea_source_bundle(idea):
    ids=idea.get("source_signal_ids") or []
    if not ids:
        return []
    con=db()
    placeholders=",".join("?" for _ in ids)
    rows=[dict(x) for x in con.execute(
        f"SELECT id,title,url,content,topic,source_type,created_at FROM source_signals WHERE id IN ({placeholders})",ids
    ).fetchall()]
    con.close()
    by_id={x["id"]:x for x in rows}
    return [by_id[x] for x in ids if x in by_id]

async def _run_content_brain_worker(agent, idea_id, label, system, user, max_output_tokens=900):
    _content_brain_budget_guard(max_output_tokens)
    run_id=start_agent_run(agent,None,"content_brain",model=FACTORY_LLM_MODEL)
    try:
        result=await asyncio.wait_for(
            asyncio.to_thread(_content_brain_llm,agent,system,user,max_output_tokens),
            timeout=AGENT_TIMEOUT_SECONDS,
        )
        parsed=_parse_json_object(result["content"])
        save_artifact(agent,"analysis",label,result["content"],run_id=run_id,
                      meta={"content_brain":True,"idea_id":idea_id,"model":result["model"],
                            "provider_request_id":result.get("provider_request_id")})
        finish_agent_run(run_id,status="completed",input_tokens=result["input_tokens"],
                         output_tokens=result["output_tokens"],cost_usd=result["cost_usd"],
                         meta={"content_brain":True,"idea_id":idea_id})
        return parsed,run_id,result
    except Exception as exc:
        finish_agent_run(run_id,status="failed",error=str(exc),meta={"content_brain":True,"idea_id":idea_id})
        raise

async def process_content_brain_ideas(payload):
    if not FACTORY_LLM_API_KEY:
        raise RuntimeError("Live LLM provider is not configured")
    max_ideas=max(1,min(5,int(payload.max_ideas or 3)))
    con=db()
    if payload.idea_ids:
        wanted=list(dict.fromkeys(str(x).strip() for x in payload.idea_ids if str(x).strip()))
        placeholders=",".join("?" for _ in wanted)
        rows=[_idea_dict(x) for x in con.execute(
            f"SELECT * FROM content_ideas WHERE id IN ({placeholders}) ORDER BY score DESC,created_at DESC",wanted
        ).fetchall()] if wanted else []
    else:
        rows=[_idea_dict(x) for x in con.execute(
            "SELECT * FROM content_ideas WHERE status IN ('generated','shortlisted') ORDER BY score DESC,created_at DESC LIMIT ?",
            (max_ideas,),
        ).fetchall()]
    con.close()
    rows=rows[:max_ideas]
    if not rows:
        raise ValueError("No ideas available for Researcher → Strategist → Verifier processing")
    processed=[]
    for idea in rows:
        sources=_idea_source_bundle(idea)
        source_text="\n\n".join(
            f"SIGNAL_ID: {x['id']}\nTITLE: {x['title']}\nURL: {x.get('url') or '(none)'}\nTOPIC: {x.get('topic') or '(none)'}\nCONTENT: {_trim_llm_context(x.get('content',''),2200)}"
            for x in sources
        ) or "(no persisted source signals)"
        researcher_system=(
            "You are the Researcher inside FactoryOS Content Brain. Use only supplied persisted signals. "
            "Do not invent sources or factual verification. Return JSON only with keys: research_summary, claims, "
            "source_signal_ids, source_links, missing_evidence. claims must be an array of concise evidence-backed claims."
        )
        researcher_user=(
            f"LANGUAGE: {payload.language}\nIDEA: {json.dumps({k:idea.get(k) for k in ('title','topic','angle','audience','why_now')},ensure_ascii=False)}\n\n"
            f"PERSISTED SIGNALS:\n{source_text}"
        )
        research,research_run,research_usage=await _run_content_brain_worker(
            "Researcher",idea["id"],"Content Brain research enrichment",researcher_system,researcher_user,850
        )

        strategist_system=(
            "You are the Idea Strategist inside FactoryOS. Refine a content idea using the supplied evidence pack. "
            "Do not add unsupported facts. Return JSON only with keys: title, angle, audience, why_now, novelty_evidence, "
            "complexity, score, strategy_notes. score must be 0..1."
        )
        strategist_user=(
            f"LANGUAGE: {payload.language}\nORIGINAL IDEA: {json.dumps(idea,ensure_ascii=False)[:6500]}\n"
            f"RESEARCH: {json.dumps(research,ensure_ascii=False)[:6500]}"
        )
        strategy,strategy_run,strategy_usage=await _run_content_brain_worker(
            "Idea Strategist",idea["id"],"Content Brain strategy refinement",strategist_system,strategist_user,750
        )

        verifier_system=(
            "You are the Idea Verifier inside FactoryOS. Judge whether the idea is ready for production based only on "
            "the supplied research and strategy. Return JSON only with keys: decision, score, risk_flags, "
            "verification_notes, rejection_reason. decision must be shortlist, reject, or needs_research. "
            "Never claim that an external fact was verified unless it is supported in the supplied persisted signals."
        )
        verifier_user=(
            f"LANGUAGE: {payload.language}\nRESEARCH: {json.dumps(research,ensure_ascii=False)[:6500]}\n"
            f"STRATEGY: {json.dumps(strategy,ensure_ascii=False)[:6500]}"
        )
        verification,verify_run,verify_usage=await _run_content_brain_worker(
            "Idea Verifier",idea["id"],"Content Brain verification decision",verifier_system,verifier_user,650
        )
        decision=str(verification.get("decision") or "needs_research").strip().lower()
        if decision not in ("shortlist","reject","needs_research"):
            decision="needs_research"
        try:
            score=max(0.0,min(1.0,float(verification.get("score",strategy.get("score",idea.get("score",0))) or 0)))
        except Exception:
            score=float(idea.get("score") or 0)
        status={"shortlist":"shortlisted","reject":"rejected","needs_research":"generated"}[decision]
        risks=[str(x).strip() for x in (verification.get("risk_flags") or []) if str(x).strip()]
        provenance=dict(idea.get("provenance") or {})
        provenance["content_brain_pipeline"]={
            "research_run_id":research_run,"strategy_run_id":strategy_run,"verification_run_id":verify_run,
            "model":FACTORY_LLM_MODEL,"processed_at":ts(),
        }
        con=db(); now=ts()
        con.execute("""UPDATE content_ideas SET
                       title=?,angle=?,audience=?,why_now=?,score=?,risk_flags_json=?,complexity=?,
                       research_json=?,strategy_json=?,verification_json=?,novelty_evidence=?,
                       rejection_reason=?,verified_at=?,status=?,updated_at=?,provenance_json=?
                       WHERE id=?""",
                    (str(strategy.get("title") or idea["title"]).strip(),
                     str(strategy.get("angle") or idea.get("angle") or "").strip(),
                     str(strategy.get("audience") or idea.get("audience") or "").strip(),
                     str(strategy.get("why_now") or idea.get("why_now") or "").strip(),
                     score,json.dumps(risks,ensure_ascii=False),
                     str(strategy.get("complexity") or idea.get("complexity") or "medium").strip(),
                     json.dumps(research,ensure_ascii=False),json.dumps(strategy,ensure_ascii=False),
                     json.dumps(verification,ensure_ascii=False),str(strategy.get("novelty_evidence") or "").strip(),
                     str(verification.get("rejection_reason") or "").strip(),now,status,now,
                     json.dumps(provenance,ensure_ascii=False),idea["id"]))
        con.commit()
        current=_idea_dict(con.execute("SELECT * FROM content_ideas WHERE id=?",(idea["id"],)).fetchone())
        con.close()
        processed.append(current)
    event(None,f"Content Brain processed {len(processed)} idea(s) through Researcher → Strategist → Verifier")
    return {"processed":processed,"count":len(processed)}

def _feed_text(node, names):
    for name in names:
        child=node.find(name)
        if child is not None and child.text:
            return child.text.strip()
    return ""

def collect_configured_signals(limit_per_feed=20):
    created=[]; duplicates=0; errors=[]
    for feed_url in FACTORY_SIGNAL_FEEDS:
        try:
            req=urlrequest.Request(feed_url,headers={"User-Agent":"BlackboxLab-FactoryOS-SignalCollector"})
            with urlrequest.urlopen(req,timeout=20) as resp:
                raw=resp.read(2_000_000)
            root=ET.fromstring(raw)
            entries=root.findall(".//item")
            if not entries:
                entries=root.findall(".//{http://www.w3.org/2005/Atom}entry")
            for node in entries[:max(1,min(50,int(limit_per_feed)))]:
                title=_feed_text(node,["title","{http://www.w3.org/2005/Atom}title"])
                link=_feed_text(node,["link"])
                if not link:
                    atom_link=node.find("{http://www.w3.org/2005/Atom}link")
                    if atom_link is not None:
                        link=(atom_link.attrib.get("href") or "").strip()
                content=_feed_text(node,[
                    "description","{http://www.w3.org/2005/Atom}summary","{http://www.w3.org/2005/Atom}content"
                ])
                if not title:
                    continue
                result=ingest_source_signal(SignalCreate(
                    title=title,content=content,url=link,source_type="rss",topic=""
                ))
                if result["created"]:
                    created.append(result["signal"])
                else:
                    duplicates+=1
        except Exception as exc:
            errors.append({"feed":feed_url,"error":str(exc)[:300]})
    return {"created":created,"created_count":len(created),"duplicates":duplicates,"errors":errors,
            "feeds_configured":len(FACTORY_SIGNAL_FEEDS)}

async def content_brain_collector_loop():
    if not FACTORY_SIGNAL_FEEDS:
        return
    while True:
        try:
            result=await asyncio.to_thread(collect_configured_signals,20)
            if result["created_count"]:
                event(None,f"Content Brain collected {result['created_count']} new RSS signal(s)")
                await broadcast({"type":"content_brain","action":"signals_collected","count":result["created_count"]})
        except Exception as exc:
            print(json.dumps({"event":"CONTENT_BRAIN_COLLECTOR_ERROR","error":str(exc)[:400]}),flush=True)
        await asyncio.sleep(FACTORY_SIGNAL_COLLECTION_MINUTES*60)

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
    for x in rows:
        x["enabled"]=bool(x["enabled"])
        try: x["allowed_tools"]=json.loads(x.pop("allowed_tools_json") or "[]")
        except Exception: x["allowed_tools"]=[]
    return rows

def _mcp_headers(connection, session_id=None):
    headers={
        "Content-Type":"application/json",
        "Accept":"application/json, text/event-stream",
        "User-Agent":"BlackboxLab-FactoryOS-MCP",
    }
    auth_env=(connection.get("auth_env") or "").strip()
    if auth_env:
        token=os.environ.get(auth_env,"").strip()
        if not token:
            raise RuntimeError(f"Required MCP auth environment variable {auth_env} is not configured")
        headers["Authorization"]=f"Bearer {token}"
    if session_id:
        headers["Mcp-Session-Id"]=session_id
    return headers

def _parse_mcp_body(raw):
    text_body=(raw or "").strip()
    if not text_body:
        return {}
    if text_body.startswith("{") or text_body.startswith("["):
        return json.loads(text_body)
    data_lines=[]
    for line in text_body.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    for candidate in reversed(data_lines):
        if candidate and candidate!="[DONE]":
            try:return json.loads(candidate)
            except Exception:continue
    raise RuntimeError("MCP server returned an unsupported response format")

def mcp_rpc(connection, method, params=None, session_id=None, notification=False):
    if connection.get("transport")!="streamable_http":
        raise RuntimeError("Live MCP execution currently supports streamable_http; SSE remains configuration-only")
    payload={"jsonrpc":"2.0","method":method}
    if not notification:
        payload["id"]=str(uuid.uuid4())
    if params is not None:
        payload["params"]=params
    req=urlrequest.Request(
        connection["endpoint"],
        data=json.dumps(payload).encode("utf-8"),
        headers=_mcp_headers(connection,session_id),
        method="POST",
    )
    try:
        with urlrequest.urlopen(req,timeout=20) as resp:
            raw=resp.read().decode("utf-8","replace")
            sid=resp.headers.get("Mcp-Session-Id") or session_id
            parsed=_parse_mcp_body(raw) if raw.strip() else {}
            if isinstance(parsed,dict) and parsed.get("error"):
                raise RuntimeError(f"MCP error: {parsed['error']}")
            return parsed,sid
    except urlerror.HTTPError as exc:
        body=exc.read().decode("utf-8","replace")
        raise RuntimeError(f"MCP HTTP {exc.code}: {body[:400]}") from exc

def mcp_session(connection):
    init,sid=mcp_rpc(connection,"initialize",{
        "protocolVersion":"2025-03-26",
        "capabilities":{},
        "clientInfo":{"name":"BlackboxLab FactoryOS","version":APP_VERSION},
    })
    try:
        mcp_rpc(connection,"notifications/initialized",{},sid,notification=True)
    except Exception:
        pass
    return init,sid

def record_mcp_audit(agent,connection_id,action,status,started_at,run_id=None,job_id=None,tool_name=None,error=None,result=None):
    finished=ts()
    try:
        duration_ms=max(0,int((datetime.fromisoformat(finished)-datetime.fromisoformat(started_at)).total_seconds()*1000))
    except Exception:
        duration_ms=0
    preview=""
    if result is not None:
        try: preview=json.dumps(result,ensure_ascii=False)[:900]
        except Exception: preview=str(result)[:900]
    con=db()
    con.execute("""INSERT INTO mcp_call_log(id,agent,connection_id,run_id,job_id,action,tool_name,status,started_at,finished_at,duration_ms,error,result_preview)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (str(uuid.uuid4()),agent,connection_id,run_id,job_id,action,tool_name,status,started_at,finished,duration_ms,error,preview))
    con.commit(); con.close()

def mcp_list_tools(agent, connection, run_id=None, job_id=None):
    started=ts()
    try:
        _,sid=mcp_session(connection)
        response,_=mcp_rpc(connection,"tools/list",{},sid)
        tools=((response or {}).get("result") or {}).get("tools",[])
        safe=[{"name":x.get("name",""),"description":x.get("description",""),"inputSchema":x.get("inputSchema",{})} for x in tools]
        record_mcp_audit(agent,connection["id"],"tools/list","completed",started,run_id,job_id,result={"tools":[x["name"] for x in safe]})
        con=db(); con.execute("UPDATE agent_mcp_connections SET status='reachable',last_check_at=?,last_error='',updated_at=? WHERE id=?",(ts(),ts(),connection["id"])); con.commit(); con.close()
        return safe
    except Exception as exc:
        record_mcp_audit(agent,connection["id"],"tools/list","failed",started,run_id,job_id,error=str(exc))
        con=db(); con.execute("UPDATE agent_mcp_connections SET status='error',last_check_at=?,last_error=?,updated_at=? WHERE id=?",(ts(),str(exc)[:500],ts(),connection["id"])); con.commit(); con.close()
        raise

def mcp_call_tool(agent, connection, tool_name, arguments, run_id=None, job_id=None):
    allowed=set(connection.get("allowed_tools") or [])
    if tool_name not in allowed:
        raise RuntimeError(f"Tool '{tool_name}' is not approved for {agent}")
    started=ts()
    try:
        _,sid=mcp_session(connection)
        response,_=mcp_rpc(connection,"tools/call",{"name":tool_name,"arguments":arguments or {}},sid)
        result=(response or {}).get("result",{})
        record_mcp_audit(agent,connection["id"],"tools/call","completed",started,run_id,job_id,tool_name,result=result)
        return result
    except Exception as exc:
        record_mcp_audit(agent,connection["id"],"tools/call","failed",started,run_id,job_id,tool_name,error=str(exc))
        raise

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

def _llm_endpoint():
    if FACTORY_LLM_API_MODE=="chat_completions":
        if FACTORY_LLM_BASE_URL.endswith("/chat/completions"):
            return FACTORY_LLM_BASE_URL
        return FACTORY_LLM_BASE_URL + "/chat/completions"
    if FACTORY_LLM_BASE_URL.endswith("/responses"):
        return FACTORY_LLM_BASE_URL
    return FACTORY_LLM_BASE_URL + "/responses"

def _llm_artifact_identity(agent):
    identities={
        "Scout":("analysis","Opportunity scan"),
        "Researcher":("research","Research brief"),
        "Tech Verifier":("analysis","Technical verification"),
        "Hook Writer":("text","Legacy hook candidates"),
        "Angle Strategist":("analysis","Angle candidates"),
        "Hook Generator":("text","Hook candidates"),
        "Scriptwriter":("text","Script variants"),
        "Fact Checker":("analysis","Fact-check findings"),
        "Hook Optimizer":("text","Optimized hooks"),
        "Editor":("text","Edited script variants"),
        "Visual Director":("text","Storyboard / visual plan"),
        "QA Agent":("analysis","Structured QA report"),
        "Publisher":("text","Publishing package"),
        "Analyst":("analysis","Performance learning brief"),
    }
    return identities.get(agent,("text",f"{agent} output"))

def _trim_llm_context(value, limit=5000):
    value=(value or "").strip()
    if len(value)<=limit:
        return value
    return value[:limit] + "\n...[truncated]"

def _call_live_llm(agent, job, input_pack):
    if not FACTORY_LLM_API_KEY:
        raise RuntimeError("FACTORY_LLM_API_KEY is not configured")
    spec=AGENT_SPECS.get(agent,{})
    memories=get_agent_memory(agent,limit=8)
    upstream=[]
    for art in input_pack.get("artifacts",[]):
        upstream.append(
            f"FROM {art.get('agent','unknown')} — {art.get('title','artifact')}:\n"
            + _trim_llm_context(art.get("content",""),4500)
        )
    memory_text="\n".join(
        f"- {m.get('content','')}" for m in memories if m.get("content")
    )
    system=(
        f"You are the {agent} inside Blackbox Lab FactoryOS. "
        f"Role: {spec.get('role','AI worker')}. Goal: {spec.get('goal','Produce the requested artifact')}. "
        "Produce the artifact itself, not commentary about being an AI. "
        "Be concise, operational and explicit about uncertainty. "
        "Never invent sources, test results, analytics or tool outputs. "
        "If evidence is missing, state exactly what still needs verification. "
        "Respect the requested language and preserve the human approval gate before publishing."
    )
    if agent=="QA Agent":
        system += (
            " Return JSON only with keys summary, release_decision and findings. "
            "release_decision must be pass or attention. findings must be an array of objects with type, severity, message and evidence. "
            "Allowed finding types: unsupported_claim, weak_hook, duplicated_angle, missing_source, slow_intro, unclear_cta, "
            "excessive_length, unsafe_sensitive_claim, fact_conflict. Severity must be info, warning or critical."
        )
    user=(
        f"JOB TITLE: {job.get('title','')}\n"
        f"BRIEF: {_trim_llm_context(job.get('brief',''),4000)}\n"
        f"LANGUAGE: {job.get('language','English')}\n"
        f"FORMAT: {job.get('format','')}\n"
        f"PRESENTER: {job.get('presenter','')}\n\n"
        f"UPSTREAM ARTIFACTS:\n{chr(10).join(upstream) if upstream else '(none)'}\n\n"
        f"APPROVED WORKER MEMORY:\n{memory_text or '(none)'}\n\n"
        "Return a production-ready artifact for this worker stage."
    )
    if FACTORY_LLM_API_MODE=="chat_completions":
        payload={
            "model":FACTORY_LLM_MODEL,
            "max_completion_tokens":FACTORY_LLM_MAX_OUTPUT_TOKENS,
            "messages":[
                {"role":"system","content":system},
                {"role":"user","content":user},
            ],
        }
    else:
        payload={
            "model":FACTORY_LLM_MODEL,
            "max_output_tokens":FACTORY_LLM_MAX_OUTPUT_TOKENS,
            "instructions":system,
            "input":user,
            "store":False,
        }
    data=json.dumps(payload).encode("utf-8")
    req=urlrequest.Request(
        _llm_endpoint(),
        data=data,
        headers={
            "Authorization":f"Bearer {FACTORY_LLM_API_KEY}",
            "Content-Type":"application/json",
            "Accept":"application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req,timeout=max(15,AGENT_TIMEOUT_SECONDS)) as resp:
            raw=resp.read().decode("utf-8")
    except urlerror.HTTPError as exc:
        body=exc.read().decode("utf-8","replace")[:1200]
        low=body.lower()
        if exc.code==429 and ("credit_balance_exhausted" in low or "insufficient_quota" in low or "no credits remaining" in low):
            raise RuntimeError("OpenAI API balance exhausted. Add API credits, wait a minute, then rerun this worker.") from exc
        if exc.code==429:
            raise RuntimeError("OpenAI API rate limit reached. FactoryOS will retry once; if it repeats, wait briefly and rerun.") from exc
        if exc.code in (401,403):
            raise RuntimeError("OpenAI API authentication failed. Check FACTORY_LLM_API_KEY and project permissions in Render.") from exc
        if exc.code==404 and ("model" in low or "not_found" in low):
            raise RuntimeError(f"Configured LLM model '{FACTORY_LLM_MODEL}' is unavailable for this API project. Change FACTORY_LLM_MODEL in Render.") from exc
        if exc.code==400:
            raise RuntimeError(f"OpenAI rejected the model request (HTTP 400). Check model/API-mode compatibility. Provider detail: {body}") from exc
        raise RuntimeError(f"LLM provider HTTP {exc.code}: {body}") from exc
    except Exception as exc:
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc
    try:
        result=json.loads(raw)
        if FACTORY_LLM_API_MODE=="chat_completions":
            content=result["choices"][0]["message"]["content"]
            if isinstance(content,list):
                content="\n".join(
                    x.get("text","") for x in content if isinstance(x,dict) and x.get("text")
                )
        else:
            parts=[]
            for item in result.get("output") or []:
                if item.get("type")!="message":
                    continue
                for block in item.get("content") or []:
                    if block.get("type")=="output_text" and block.get("text"):
                        parts.append(block["text"])
            content="\n".join(parts)
    except Exception as exc:
        raise RuntimeError("LLM provider returned an unsupported response shape") from exc
    content=str(content or "").strip()
    if not content:
        raise RuntimeError("LLM provider returned empty content")
    usage=result.get("usage") or {}
    input_tokens=int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    output_tokens=int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    cost_usd=(
        input_tokens * FACTORY_LLM_INPUT_USD_PER_1M / 1_000_000
        + output_tokens * FACTORY_LLM_OUTPUT_USD_PER_1M / 1_000_000
    )
    kind,title=_llm_artifact_identity(agent)
    return {
        "kind":kind,"title":title,"content":content,
        "model":result.get("model") or FACTORY_LLM_MODEL,
        "input_tokens":input_tokens,"output_tokens":output_tokens,
        "cost_usd":cost_usd,
        "provider_request_id":result.get("id"),
    }

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

def get_factory_intelligence(limit_jobs=8):
    content_agents=[a for a in AGENTS if a not in ("Supervisor","Design Partner")]
    con=db()
    worker_rows=[dict(x) for x in con.execute(
        """SELECT agent,
                  COUNT(*) runs,
                  COALESCE(SUM(CASE WHEN status='completed' THEN 1 ELSE 0 END),0) completed_runs,
                  COALESCE(SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END),0) failed_runs,
                  COALESCE(SUM(duration_ms),0) duration_ms,
                  COALESCE(AVG(duration_ms),0) avg_duration_ms,
                  COALESCE(SUM(input_tokens),0) input_tokens,
                  COALESCE(SUM(output_tokens),0) output_tokens,
                  COALESCE(SUM(cost_usd),0) cost_usd,
                  MAX(COALESCE(finished_at,started_at)) last_run
           FROM agent_runs
           WHERE agent NOT IN ('Supervisor','Design Partner')
           GROUP BY agent ORDER BY agent"""
    ).fetchall()]
    artifact_counts={x["agent"]:x["c"] for x in con.execute(
        """SELECT agent,COUNT(*) c FROM artifacts
           WHERE agent NOT IN ('Supervisor','Design Partner') GROUP BY agent"""
    ).fetchall()}
    recent_jobs=[dict(x) for x in con.execute(
        """SELECT j.id,j.title,j.status,j.stage,j.created_at,j.updated_at,
                  COUNT(r.id) runs,
                  COALESCE(SUM(CASE WHEN r.status='completed' THEN 1 ELSE 0 END),0) completed_runs,
                  COALESCE(SUM(CASE WHEN r.status='failed' THEN 1 ELSE 0 END),0) failed_runs,
                  COALESCE(SUM(r.duration_ms),0) duration_ms,
                  COALESCE(SUM(r.input_tokens),0) input_tokens,
                  COALESCE(SUM(r.output_tokens),0) output_tokens,
                  COALESCE(SUM(r.cost_usd),0) cost_usd
           FROM jobs j LEFT JOIN agent_runs r ON r.job_id=j.id
           GROUP BY j.id,j.title,j.status,j.stage,j.created_at,j.updated_at
           ORDER BY j.updated_at DESC LIMIT ?""",(limit_jobs,)
    ).fetchall()]
    con.close()

    known={row["agent"]:row for row in worker_rows}
    workers=[]
    for agent in content_agents:
        row=known.get(agent,{
            "agent":agent,"runs":0,"completed_runs":0,"failed_runs":0,
            "duration_ms":0,"avg_duration_ms":0,"input_tokens":0,"output_tokens":0,
            "cost_usd":0.0,"last_run":None,
        })
        row["artifacts"]=int(artifact_counts.get(agent,0))
        row["total_tokens"]=int(row.get("input_tokens",0) or 0)+int(row.get("output_tokens",0) or 0)
        row["success_rate"]=round((row["completed_runs"]/row["runs"]*100),1) if row["runs"] else 0
        row["avg_cost_usd"]=round((float(row["cost_usd"] or 0)/row["runs"]),6) if row["runs"] else 0.0
        workers.append(row)

    total_runs=sum(int(x["runs"] or 0) for x in workers)
    completed=sum(int(x["completed_runs"] or 0) for x in workers)
    failed=sum(int(x["failed_runs"] or 0) for x in workers)
    total_cost=sum(float(x["cost_usd"] or 0) for x in workers)
    total_duration=sum(int(x["duration_ms"] or 0) for x in workers)
    total_tokens=sum(int(x["total_tokens"] or 0) for x in workers)
    for row in workers:
        row["cost_share_pct"]=round((float(row["cost_usd"] or 0)/total_cost*100),1) if total_cost else 0

    job_metrics=[]
    for row in recent_jobs:
        quality=get_job_quality(row["id"]) or {}
        row["total_tokens"]=int(row.get("input_tokens",0) or 0)+int(row.get("output_tokens",0) or 0)
        row["artifact_coverage"]=float(quality.get("coverage",100 if not row["runs"] else 0))
        row["stale_stages"]=quality.get("stale_stages",[])
        row["fresh"]=bool(quality.get("fresh",True))
        job_metrics.append(row)

    avg_coverage=round(sum(x["artifact_coverage"] for x in job_metrics)/len(job_metrics),1) if job_metrics else 0
    measured=[x for x in workers if x["runs"]]
    reliable=sorted(measured,key=lambda x:(x["success_rate"],x["runs"]),reverse=True)
    costliest=sorted([x for x in measured if float(x["cost_usd"] or 0)>0],key=lambda x:float(x["cost_usd"] or 0),reverse=True)
    slowest=sorted([x for x in measured if float(x["avg_duration_ms"] or 0)>0],key=lambda x:float(x["avg_duration_ms"] or 0),reverse=True)
    hotspots=sorted([x for x in measured if x["failed_runs"]],key=lambda x:(x["failed_runs"],-x["success_rate"]),reverse=True)

    insights=[]
    if hotspots:
        x=hotspots[0]
        insights.append({
            "type":"reliability","severity":"warning","agent":x["agent"],
            "title":f"{x['agent']} is the current failure hotspot",
            "detail":f"{x['failed_runs']} failed run(s) across {x['runs']} measured run(s); success rate {x['success_rate']}%.",
        })
    if costliest:
        x=costliest[0]
        insights.append({
            "type":"cost","severity":"info","agent":x["agent"],
            "title":f"{x['agent']} drives the most measured provider spend",
            "detail":f"USD {float(x['cost_usd'] or 0):.4f}, {x['cost_share_pct']}% of persisted worker cost.",
        })
    if slowest:
        x=slowest[0]
        insights.append({
            "type":"latency","severity":"info","agent":x["agent"],
            "title":f"{x['agent']} has the highest average measured run time",
            "detail":f"Average {int(x['avg_duration_ms'] or 0)} ms across {x['runs']} run(s).",
        })
    incomplete=next((x for x in job_metrics if x["artifact_coverage"]<100 and x["status"]!="running"),None)
    if incomplete:
        insights.append({
            "type":"coverage","severity":"warning","job_id":incomplete["id"],
            "title":f"Recent job '{incomplete['title']}' is not fully covered",
            "detail":f"Artifact readiness coverage is {incomplete['artifact_coverage']}%; stale stages: {', '.join(incomplete['stale_stages']) or 'none detected'}.",
        })
    if not insights:
        insights.append({
            "type":"baseline","severity":"info",
            "title":"No optimization hotspot is measurable yet",
            "detail":"Run more production jobs to build a useful reliability, latency and cost baseline.",
        })

    return {
        "generated_at":ts(),
        "summary":{
            "runs":total_runs,"completed_runs":completed,"failed_runs":failed,
            "success_rate":round((completed/total_runs*100),1) if total_runs else 0,
            "duration_ms":total_duration,"tokens":total_tokens,"cost_usd":round(total_cost,6),
            "recent_avg_artifact_coverage":avg_coverage,
        },
        "leaders":{
            "reliability":reliable[0]["agent"] if reliable else None,
            "cost":costliest[0]["agent"] if costliest else None,
            "latency":slowest[0]["agent"] if slowest else None,
            "failure_hotspot":hotspots[0]["agent"] if hotspots else None,
        },
        "workers":workers,
        "jobs":job_metrics,
        "insights":insights,
        "measurement_note":"Reliability, latency, token usage and provider cost come from persisted agent runs. Artifact coverage measures pipeline readiness, not subjective content quality.",
    }

def get_release_readiness():
    jobs=get_jobs()
    build=get_factory_tasks()
    usage=get_usage_summary()
    report=supervisor_runtime.get("last_report") or supervisor_audit(auto_heal=False,persist=False)
    failed_jobs=[j for j in jobs if j.get("status")=="failed"]
    waiting_jobs=[j for j in jobs if j.get("status")=="waiting_approval"]
    running=[j for j in jobs if j.get("status")=="running"]
    unresolved_incidents=0
    spend_uncertain=0
    for job in jobs[:12]:
        center=get_job_error_center(job["id"])
        unresolved_incidents+=int(center["summary"].get("open",0))
        spend_uncertain+=int(center["summary"].get("spend_uncertain",0))

    task_by_id={x["id"]:x for x in build.get("tasks",[])}
    paid_verification_pending=any(
        task_by_id.get(task_id,{}).get("status")!="done"
        for task_id in ("live-llm","night-live-llm-hardening")
    )

    retry_probe=classify_agent_error("LLM provider request failed: timed out")
    checks=[
        {"id":"approval_gate","label":"Human approval gate","ok":True,
         "detail":"Publishing remains blocked until the job reaches waiting_approval and a human approves it."},
        {"id":"spend_guards","label":"Provider spend guards","ok":FACTORY_DAILY_BUDGET_USD>0 and FACTORY_JOB_BUDGET_USD>0,
         "detail":f"Daily cap USD {FACTORY_DAILY_BUDGET_USD:g}; per-job cap USD {FACTORY_JOB_BUDGET_USD:g}."},
        {"id":"uncertain_retry","label":"Spend-safe retry policy",
         "ok":bool(retry_probe.get("requires_confirmation")) and not bool(retry_probe.get("auto_retry")),
         "detail":"Timeout/network outcomes require manual confirmation instead of blind automatic retry."},
        {"id":"authentication","label":"Private authentication","ok":bool(FACTORY_PASSWORD),
         "detail":"Login protection is configured." if FACTORY_PASSWORD else "FACTORY_PASSWORD is not configured in this runtime."},
        {"id":"llm_provider","label":"Live LLM provider","ok":bool(FACTORY_LLM_API_KEY),
         "detail":f"{FACTORY_LLM_MODEL} via {FACTORY_LLM_API_MODE}." if FACTORY_LLM_API_KEY else "Live LLM key is not configured."},
        {"id":"builder_bridge","label":"Factory Builder bridge","ok":bool(GITHUB_TOKEN),
         "detail":"GitHub builder credential is configured." if GITHUB_TOKEN else "Builder uses fallback mode because GitHub credential is absent."},
    ]

    blockers=[]
    def add(severity,code,title,detail):
        blockers.append({"severity":severity,"code":code,"title":title,"detail":detail})
    if not FACTORY_LLM_API_KEY:
        add("critical","llm_not_configured","Live LLM provider is not configured","Content workers cannot complete real model-backed generation.")
    if not FACTORY_PASSWORD:
        add("warning","auth_not_configured","Private login is not configured","Production should keep FACTORY_PASSWORD configured.")
    if failed_jobs:
        add("critical","failed_jobs",f"{len(failed_jobs)} job(s) are failed","Resolve failed jobs in Error Center before unattended production.")
    if spend_uncertain:
        add("warning","uncertain_spend",f"{spend_uncertain} unresolved incident(s) have uncertain provider spend","Review provider-side completion before retrying these calls.")
    if paid_verification_pending:
        add("warning","paid_llm_verification","Intentional paid LLM end-to-end verification is still pending","Run one controlled paid worker only when you explicitly want to verify real artifact + token + cost accounting.")
    if CONNECTIONS.get("Voice",{}).get("state")=="not_configured":
        add("info","voice_provider","Voice provider is not configured","Narration remains a capability gap, not a hidden failure.")
    if CONNECTIONS.get("Video",{}).get("state")=="not_configured":
        add("info","video_provider","Video provider is not configured","Final rendering remains a capability gap, not a hidden failure.")

    critical=sum(1 for x in blockers if x["severity"]=="critical")
    state="blocked" if critical else ("ready_with_known_gaps" if blockers else "ready")
    return {
        "generated_at":ts(),"version":APP_VERSION,"build_sha":BUILD_SHA,"state":state,
        "summary":{
            "jobs":len(jobs),"running_jobs":len(running),"waiting_approval":len(waiting_jobs),
            "failed_jobs":len(failed_jobs),"open_incidents":unresolved_incidents,
            "spend_uncertain_incidents":spend_uncertain,
            "roadmap_progress":float(build.get("progress",0)),
            "roadmap_done":int(build.get("done",0)),"roadmap_total":int(build.get("total",0)),
            "provider_cost_usd":float(usage.get("cost_usd",0) or 0),
            "today_cost_usd":float(usage.get("today_cost_usd",0) or 0),
            "supervisor_score":int(report.get("score",0) or 0),
        },
        "checks":checks,"blockers":blockers,
        "remaining_paid_verification":paid_verification_pending,
        "next_priorities":[
            "Run one controlled paid LLM worker verification only with explicit approval.",
            "Select and connect voice/video providers before claiming full media-production readiness.",
            "Use Factory Intelligence and Error Center data to optimize workers after more real production runs.",
        ],
        "note":"This readiness snapshot reports measured/runtime facts and declared capability gaps. It does not execute paid provider calls.",
    }

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


VARIANT_QA_TYPES={
    "unsupported_claim","weak_hook","duplicated_angle","missing_source","slow_intro",
    "unclear_cta","excessive_length","unsafe_sensitive_claim","fact_conflict",
}
VARIANT_COMPONENTS=("angle","hook","script","factcheck","optimize","editor","qa")

def _normalize_qa_findings(findings):
    normalized=[]
    for raw in findings or []:
        if not isinstance(raw,dict):
            continue
        kind=str(raw.get("type") or "").strip().lower().replace(" ","_").replace("/","_")
        if kind not in VARIANT_QA_TYPES:
            continue
        severity=str(raw.get("severity") or "warning").strip().lower()
        if severity not in ("info","warning","critical"):
            severity="warning"
        message=str(raw.get("message") or "").strip()
        if not message:
            continue
        normalized.append({"type":kind,"severity":severity,"message":message,"evidence":str(raw.get("evidence") or "").strip()})
    return normalized

def _variant_dict(row):
    if not row:return None
    item=dict(row)
    item["fact_check"]=_decode_json(item.pop("fact_check_json","{}"),{})
    item["qa"]=_decode_json(item.pop("qa_json","{}"),{})
    item["provenance"]=_decode_json(item.pop("provenance_json","{}"),{})
    return item

def get_job_variants(job_id):
    empty={"job_id":job_id,"batch_id":None,"summary":{"variants":0,"selected":0,"rejected":0,"candidates":0,"allocated_cost_usd":0},"variants":[],"cost_note":"Shared batch-run provider cost is allocated evenly across variants for comparison; total job cost remains measured exactly in agent_runs."}
    if not job_id:return empty
    con=db()
    latest=con.execute("SELECT batch_id,MAX(created_at) created_at FROM production_variants WHERE job_id=? GROUP BY batch_id ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone()
    if not latest:
        con.close();return empty
    rows=[_variant_dict(x) for x in con.execute("SELECT * FROM production_variants WHERE job_id=? AND batch_id=? ORDER BY ordinal",(job_id,latest["batch_id"])).fetchall()]
    con.close()
    return {"job_id":job_id,"batch_id":latest["batch_id"],"summary":{"variants":len(rows),"selected":sum(1 for x in rows if x["status"]=="selected"),"rejected":sum(1 for x in rows if x["status"]=="rejected"),"candidates":sum(1 for x in rows if x["status"] in ("candidate","stale")),"allocated_cost_usd":round(sum(float(x.get("allocated_cost_usd") or 0) for x in rows),6)},"variants":rows,"cost_note":"Shared batch-run provider cost is allocated evenly across variants for comparison; total job cost remains measured exactly in agent_runs."}

def _variant_research_context(job_id):
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT agent,title,content,created_at FROM artifacts WHERE job_id=? AND agent IN ('Researcher','Tech Verifier') ORDER BY created_at DESC LIMIT 4""",(job_id,)).fetchall()]
    con.close()
    return "\n\n".join(f"{x['agent']} — {x['title']}:\n{_trim_llm_context(x.get('content',''),5000)}" for x in reversed(rows)) or "(no persisted research artifacts; do not invent evidence)"

def _variant_budget_guard(job_id, output_tokens=1200):
    reserve=max(128,int(output_tokens))*FACTORY_LLM_OUTPUT_USD_PER_1M/1_000_000
    usage=get_usage_summary()
    if usage["today_cost_usd"] + reserve > FACTORY_DAILY_BUDGET_USD:raise RuntimeError("Daily provider budget would be exceeded by the next variant call")
    if get_job_cost(job_id) + reserve > FACTORY_JOB_BUDGET_USD:raise RuntimeError("Job provider budget would be exceeded by the next variant call")

async def _variant_agent_call(agent,job_id,label,system,user,max_output_tokens=1100):
    _variant_budget_guard(job_id,max_output_tokens)
    run_id=start_agent_run(agent,job_id,"script",model=FACTORY_LLM_MODEL)
    set_agent_progress(agent,8,label,job_id,run_id,"working");event(job_id,f"{agent}: {label}")
    await broadcast({"type":"agent","agent":agent,"state":"working"})
    try:
        result=await asyncio.wait_for(asyncio.to_thread(_content_brain_llm,agent,system,user,max_output_tokens),timeout=AGENT_TIMEOUT_SECONDS)
        parsed=_parse_json_object(result["content"])
        save_artifact(agent,"analysis",label,result["content"],job_id=job_id,run_id=run_id,meta={"mode":"live_llm","stage":"script","variant_batch":True,"model":result["model"],"provider_request_id":result.get("provider_request_id")})
        finish_agent_run(run_id,status="completed",input_tokens=result["input_tokens"],output_tokens=result["output_tokens"],cost_usd=result["cost_usd"],meta={"mode":"live_llm","variant_batch":True})
        record_run_step(run_id,job_id,agent,"complete","Completed",100,"completed");set_agent_progress(agent,100,"Completed",job_id,run_id,"done")
        await broadcast({"type":"agent_progress","agent":agent,"state":"done","progress":agent_progress[agent]})
        return parsed,run_id,result
    except Exception as exc:
        finish_agent_run(run_id,status="failed",error=str(exc),meta={"mode":"live_llm","variant_batch":True});set_agent_progress(agent,20,f"Failed: {str(exc)[:160]}",job_id,run_id,"failed");raise

def _save_variant_piece(agent,job_id,run_id,batch_id,variant_id,component,title,content,extra=None):
    return save_artifact(agent,"analysis" if component in ("angle","factcheck","qa") else "text",title,content,job_id=job_id,run_id=run_id,meta={"mode":"live_llm" if FACTORY_LLM_API_KEY else "demo","stage":"script","variant_batch":True,"batch_id":batch_id,"variant_id":variant_id,"component":component,**(extra or {})})

def _select_variant_from_qa(variants,recommended=None):
    valid_ids={x["id"] for x in variants}
    if recommended in valid_ids:
        candidate=next(x for x in variants if x["id"]==recommended);findings=(candidate.get("qa") or {}).get("findings") or []
        if not any(x.get("severity")=="critical" for x in findings):return recommended
    ranked=[]
    for v in variants:
        findings=(v.get("qa") or {}).get("findings") or []
        ranked.append((sum(1 for x in findings if x.get("severity")=="critical"),sum(1 for x in findings if x.get("severity")=="warning"),v["ordinal"],v["id"]))
    ranked.sort();return ranked[0][3] if ranked else None

def _demo_variant_pipeline(job_id,candidate_count=3):
    job=get_job(job_id)
    if not job:raise ValueError("Job not found")
    batch_id=str(uuid.uuid4());now=ts()
    templates=[("Explain the hidden mechanism first","You think this is a black box — here is what is actually happening."),("Lead with the surprising limitation","The most interesting part is what this system cannot know."),("Start from a concrete experiment","I tested the claim on one concrete example. Here is what survived verification.")]
    con=db();variants=[]
    for n in range(candidate_count):
        variant_id=str(uuid.uuid4());angle,hook=templates[n%len(templates)]
        script=f"{hook}\n\nContext: {job['title']}.\nDemo variant {n+1}: explain one concrete mechanism, show the evidence boundary, state limitations, then end with a clear CTA."
        fact={"findings":[{"type":"missing_source","severity":"warning","message":"Demo mode has no live external source verification.","evidence":"simulation-v3"}]}
        qa={"decision":"keep" if n==0 else "reject","findings":[{"type":"missing_source","severity":"warning","message":"Demo variant only; live source verification is required.","evidence":"simulation-v3"}]}
        status="selected" if n==0 else "rejected";reason="Demo selection only — no live performance or source evidence." if n==0 else "Demo alternate retained for comparison.";provenance={"mode":"demo","batch_id":batch_id}
        con.execute("""INSERT INTO production_variants(id,batch_id,job_id,ordinal,status,angle,angle_reason,hook,hook_rationale,script,optimized_hook,edited_script,fact_check_json,qa_json,decision_reason,allocated_cost_usd,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(variant_id,batch_id,job_id,n+1,status,angle,"Deterministic demo angle",hook,"Deterministic demo hook",script,hook,script,json.dumps(fact),json.dumps(qa),reason,0,json.dumps(provenance),now,now))
        variants.append({"id":variant_id,"ordinal":n+1,"angle":angle,"hook":hook,"script":script,"status":status})
    con.commit();con.close()
    for agent,component in [("Angle Strategist","angle"),("Hook Generator","hook"),("Scriptwriter","script"),("Fact Checker","factcheck"),("Hook Optimizer","optimize"),("Editor","editor")]:
        run_id=start_agent_run(agent,job_id,"script",model="simulation-v3")
        for v in variants:_save_variant_piece(agent,job_id,run_id,batch_id,v["id"],component,f"Variant {v['ordinal']} · {component}",v["script"])
        finish_agent_run(run_id,status="completed",meta={"mode":"demo","variant_batch":True,"batch_id":batch_id});record_run_step(run_id,job_id,agent,"complete","Completed",100,"completed");set_agent_progress(agent,100,"Completed",job_id,run_id,"done")
    run_id=start_agent_run("QA Agent",job_id,"script",model="simulation-v3")
    for v in variants:_save_variant_piece("QA Agent",job_id,run_id,batch_id,v["id"],"qa",f"Variant {v['ordinal']} · structured QA",json.dumps({"decision":"keep" if v["ordinal"]==1 else "reject","findings":[{"type":"missing_source","severity":"warning","message":"Demo variant only; live source verification is required.","evidence":"simulation-v3"}]},indent=2))
    finish_agent_run(run_id,status="completed",meta={"mode":"demo","variant_batch":True,"batch_id":batch_id})
    _save_variant_piece("Editor",job_id,None,batch_id,variants[0]["id"],"selected","Selected production variant",variants[0]["script"],{"selected":True})
    event(job_id,f"Production Pipeline 2.0 demo batch created: {candidate_count} variants; variant 1 selected");return get_job_variants(job_id)

async def run_variant_pipeline(job_id,candidate_count=3):
    candidate_count=max(2,min(4,int(candidate_count or 3)))
    if not FACTORY_LLM_API_KEY:return _demo_variant_pipeline(job_id,candidate_count)
    job=get_job(job_id)
    if not job:raise ValueError("Job not found")
    batch_id=str(uuid.uuid4());research=_variant_research_context(job_id);language=job.get("language","English")
    angle_obj,angle_run,_=await _variant_agent_call("Angle Strategist",job_id,"Generating competing angles","You are Angle Strategist in FactoryOS Production Pipeline 2.0. Create genuinely distinct evidence-grounded narrative angles. Use only supplied research. Return JSON only: {\"angles\":[{\"angle\":\"...\",\"reason\":\"...\",\"audience\":\"...\"}]}. Return exactly "+str(candidate_count)+" angles. Do not invent facts.",f"JOB: {job['title']}\nBRIEF: {job.get('brief','')}\nLANGUAGE: {language}\nRESEARCH:\n{research}",1000)
    angles=[x for x in (angle_obj.get("angles") or []) if isinstance(x,dict) and str(x.get("angle") or "").strip()][:candidate_count]
    if len(angles)<candidate_count:raise RuntimeError(f"Angle Strategist returned {len(angles)} usable angles; expected {candidate_count}")
    con=db();now=ts();variants=[]
    for n,a in enumerate(angles,1):
        vid=str(uuid.uuid4());provenance={"batch_id":batch_id,"run_ids":{"angle":angle_run}}
        con.execute("INSERT INTO production_variants(id,batch_id,job_id,ordinal,status,angle,angle_reason,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(vid,batch_id,job_id,n,"candidate",str(a.get("angle") or "").strip(),str(a.get("reason") or "").strip(),json.dumps(provenance),now,now))
        variants.append({"id":vid,"ordinal":n,"angle":str(a.get("angle") or "").strip(),"angle_reason":str(a.get("reason") or "").strip()});_save_variant_piece("Angle Strategist",job_id,angle_run,batch_id,vid,"angle",f"Variant {n} · angle",json.dumps(a,ensure_ascii=False,indent=2))
    con.commit();con.close()
    hook_obj,hook_run,_=await _variant_agent_call("Hook Generator",job_id,"Generating hook candidates","You are Hook Generator. Create one specific 1–3 second opening hook for each supplied variant. Hooks must differ in mechanism, not just wording, and must not add unsupported claims. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"hook\":\"...\",\"rationale\":\"...\"}]}.",f"LANGUAGE: {language}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps(variants,ensure_ascii=False)}",1000)
    hooks={str(x.get("variant_id")):x for x in hook_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        h=hooks.get(v["id"]) or {};v["hook"]=str(h.get("hook") or "").strip();v["hook_rationale"]=str(h.get("rationale") or "").strip()
        if not v["hook"]:raise RuntimeError(f"Hook Generator missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["hook"]=hook_run
        con.execute("UPDATE production_variants SET hook=?,hook_rationale=?,provenance_json=?,updated_at=? WHERE id=?",(v["hook"],v["hook_rationale"],json.dumps(prov),ts(),v["id"]));_save_variant_piece("Hook Generator",job_id,hook_run,batch_id,v["id"],"hook",f"Variant {v['ordinal']} · hook",json.dumps(h,ensure_ascii=False,indent=2))
    con.commit();con.close()
    script_obj,script_run,_=await _variant_agent_call("Scriptwriter",job_id,"Writing script variants","You are Scriptwriter. Write a distinct concise production script for each supplied variant, keeping its angle and hook. Use only supplied research. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"script\":\"...\"}]}. Each script must contain a concrete payoff and CTA, and explicitly qualify uncertainty.",f"LANGUAGE: {language}\nFORMAT: {job.get('format','')}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps(variants,ensure_ascii=False)}",1200)
    scripts={str(x.get("variant_id")):x for x in script_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=scripts.get(v["id"]) or {};v["script"]=str(x.get("script") or "").strip()
        if not v["script"]:raise RuntimeError(f"Scriptwriter missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["script"]=script_run
        con.execute("UPDATE production_variants SET script=?,provenance_json=?,updated_at=? WHERE id=?",(v["script"],json.dumps(prov),ts(),v["id"]));_save_variant_piece("Scriptwriter",job_id,script_run,batch_id,v["id"],"script",f"Variant {v['ordinal']} · script",v["script"])
    con.commit();con.close()
    fact_obj,fact_run,_=await _variant_agent_call("Fact Checker",job_id,"Fact-checking variants","You are Fact Checker. Inspect each script against supplied persisted research only. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"findings\":[{\"type\":\"unsupported_claim|missing_source|fact_conflict\",\"severity\":\"info|warning|critical\",\"message\":\"...\",\"evidence\":\"...\"}],\"fact_summary\":\"...\"}]}. Never claim external verification that is not present in research.",f"RESEARCH:\n{research}\nSCRIPTS:\n{json.dumps([{k:v.get(k) for k in ('id','script')} for v in variants],ensure_ascii=False)}",1100)
    facts={str(x.get("variant_id")):x for x in fact_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=facts.get(v["id"]) or {};x["findings"]=_normalize_qa_findings(x.get("findings") or []);v["fact_check"]=x
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["factcheck"]=fact_run
        con.execute("UPDATE production_variants SET fact_check_json=?,provenance_json=?,updated_at=? WHERE id=?",(json.dumps(x,ensure_ascii=False),json.dumps(prov),ts(),v["id"]));_save_variant_piece("Fact Checker",job_id,fact_run,batch_id,v["id"],"factcheck",f"Variant {v['ordinal']} · fact check",json.dumps(x,ensure_ascii=False,indent=2))
    con.commit();con.close()
    opt_obj,opt_run,_=await _variant_agent_call("Hook Optimizer",job_id,"Optimizing hooks","You are Hook Optimizer. Improve each hook after reading fact-check findings. Preserve evidence boundaries; do not introduce new claims. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"optimized_hook\":\"...\",\"change_reason\":\"...\"}]}.",f"LANGUAGE: {language}\nVARIANTS:\n{json.dumps([{**{k:v.get(k) for k in ('id','hook')},'fact_check':v.get('fact_check')} for v in variants],ensure_ascii=False)}",850)
    opts={str(x.get("variant_id")):x for x in opt_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=opts.get(v["id"]) or {};v["optimized_hook"]=str(x.get("optimized_hook") or v.get("hook") or "").strip();prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["optimize"]=opt_run
        con.execute("UPDATE production_variants SET optimized_hook=?,provenance_json=?,updated_at=? WHERE id=?",(v["optimized_hook"],json.dumps(prov),ts(),v["id"]));_save_variant_piece("Hook Optimizer",job_id,opt_run,batch_id,v["id"],"optimize",f"Variant {v['ordinal']} · optimized hook",json.dumps(x,ensure_ascii=False,indent=2))
    con.commit();con.close()
    edit_obj,edit_run,_=await _variant_agent_call("Editor",job_id,"Editing production variants","You are Editor. Produce final edited script for each variant using its optimized hook and fact-check findings. Remove or qualify unsupported claims. Keep variants meaningfully distinct. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"edited_script\":\"...\",\"edit_notes\":\"...\"}]}.",f"LANGUAGE: {language}\nVARIANTS:\n{json.dumps([{k:v.get(k) for k in ('id','angle','optimized_hook','script','fact_check')} for v in variants],ensure_ascii=False)}",1200)
    edits={str(x.get("variant_id")):x for x in edit_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=edits.get(v["id"]) or {};v["edited_script"]=str(x.get("edited_script") or "").strip()
        if not v["edited_script"]:raise RuntimeError(f"Editor missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["editor"]=edit_run
        con.execute("UPDATE production_variants SET edited_script=?,provenance_json=?,updated_at=? WHERE id=?",(v["edited_script"],json.dumps(prov),ts(),v["id"]));_save_variant_piece("Editor",job_id,edit_run,batch_id,v["id"],"editor",f"Variant {v['ordinal']} · edited script",v["edited_script"])
    con.commit();con.close()
    qa_obj,qa_run,_=await _variant_agent_call("QA Agent",job_id,"Comparing variants with structured QA","You are QA Agent comparing competing content variants before downstream production. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"decision\":\"keep|reject\",\"reason\":\"...\",\"findings\":[{\"type\":\"unsupported_claim|weak_hook|duplicated_angle|missing_source|slow_intro|unclear_cta|excessive_length|unsafe_sensitive_claim|fact_conflict\",\"severity\":\"info|warning|critical\",\"message\":\"...\",\"evidence\":\"...\"}]}],\"recommended_variant_id\":\"...\"}. Do not use a made-up quality score. Recommend based on concrete findings only.",f"LANGUAGE: {language}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps([{k:v.get(k) for k in ('id','angle','optimized_hook','edited_script','fact_check')} for v in variants],ensure_ascii=False)}",1200)
    qa_map={str(x.get("variant_id")):x for x in qa_obj.get("variants") or [] if isinstance(x,dict)};con=db();hydrated=[]
    for v in variants:
        q=qa_map.get(v["id"]) or {"decision":"keep","reason":"QA returned no variant-specific decision","findings":[]};q["findings"]=_normalize_qa_findings(q.get("findings") or []);v["qa"]=q
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["qa"]=qa_run
        con.execute("UPDATE production_variants SET qa_json=?,provenance_json=?,updated_at=? WHERE id=?",(json.dumps(q,ensure_ascii=False),json.dumps(prov),ts(),v["id"]));_save_variant_piece("QA Agent",job_id,qa_run,batch_id,v["id"],"qa",f"Variant {v['ordinal']} · structured QA",json.dumps(q,ensure_ascii=False,indent=2));hydrated.append({**v,"provenance":prov})
    con.commit();con.close()
    selected_id=_select_variant_from_qa(hydrated,str(qa_obj.get("recommended_variant_id") or ""))
    if not selected_id:raise RuntimeError("Structured QA could not select a production variant")
    run_ids=[angle_run,hook_run,script_run,fact_run,opt_run,edit_run,qa_run];con=db();placeholders=",".join("?" for _ in run_ids);total_cost=float(con.execute(f"SELECT COALESCE(SUM(cost_usd),0) c FROM agent_runs WHERE id IN ({placeholders})",run_ids).fetchone()["c"] or 0);allocated=round(total_cost/len(variants),6) if variants else 0
    for v in hydrated:
        selected=v["id"]==selected_id;q=v.get("qa") or {};reason=str(q.get("reason") or ("Recommended by structured QA findings." if selected else "Not recommended by structured QA findings.")).strip()
        con.execute("UPDATE production_variants SET status=?,decision_reason=?,allocated_cost_usd=?,updated_at=? WHERE id=?",("selected" if selected else "rejected",reason,allocated,ts(),v["id"]))
    con.commit();chosen=_variant_dict(con.execute("SELECT * FROM production_variants WHERE id=?",(selected_id,)).fetchone());con.close()
    _save_variant_piece("Editor",job_id,edit_run,batch_id,selected_id,"selected","Selected production variant",(chosen.get("optimized_hook") or chosen.get("hook") or "")+"\n\n"+(chosen.get("edited_script") or chosen.get("script") or ""),{"selected":True,"decision_reason":chosen.get("decision_reason")})
    _save_variant_piece("Fact Checker",job_id,fact_run,batch_id,selected_id,"selected_factcheck","Selected variant fact check",json.dumps(chosen.get("fact_check") or {},ensure_ascii=False,indent=2),{"selected":True})
    event(job_id,f"Production Pipeline 2.0: {len(variants)} variants compared; variant {chosen['ordinal']} selected by structured findings");await broadcast({"type":"variants","jobId":job_id,"batchId":batch_id,"selectedVariantId":selected_id});return get_job_variants(job_id)

async def rerun_variant_component(job_id,variant_id,component):
    if component not in VARIANT_COMPONENTS:raise ValueError("Unknown variant component")
    if not FACTORY_LLM_API_KEY:raise RuntimeError("Live LLM provider is required for a paid partial variant rerun")
    con=db();row=con.execute("SELECT * FROM production_variants WHERE id=? AND job_id=?",(variant_id,job_id)).fetchone();con.close();variant=_variant_dict(row)
    if not variant:raise ValueError("Variant not found")
    research=_variant_research_context(job_id);job=get_job(job_id);agent_by_component={"angle":"Angle Strategist","hook":"Hook Generator","script":"Scriptwriter","factcheck":"Fact Checker","optimize":"Hook Optimizer","editor":"Editor","qa":"QA Agent"};agent=agent_by_component[component]
    schemas={"angle":'{"angle":"...","reason":"..."}',"hook":'{"hook":"...","rationale":"..."}',"script":'{"script":"..."}',"factcheck":'{"findings":[{"type":"unsupported_claim|missing_source|fact_conflict","severity":"info|warning|critical","message":"...","evidence":"..."}],"fact_summary":"..."}',"optimize":'{"optimized_hook":"...","change_reason":"..."}',"editor":'{"edited_script":"...","edit_notes":"..."}',"qa":'{"decision":"keep|reject","reason":"...","findings":[{"type":"unsupported_claim|weak_hook|duplicated_angle|missing_source|slow_intro|unclear_cta|excessive_length|unsafe_sensitive_claim|fact_conflict","severity":"info|warning|critical","message":"...","evidence":"..."}]}'}
    obj,run_id,_=await _variant_agent_call(agent,job_id,f"Partial rerun · {component}",f"You are {agent} doing a targeted partial rerun for one production variant. Return JSON only with schema {schemas[component]}. Use only persisted research and current variant context. Never invent evidence.",f"LANGUAGE: {job.get('language','English')}\nRESEARCH:\n{research}\nCURRENT VARIANT:\n{json.dumps(variant,ensure_ascii=False)[:12000]}",1000)
    now=ts();prov=variant.get("provenance") or {};prov.setdefault("partial_reruns",[]).append({"component":component,"run_id":run_id,"at":now});updates={"status":"candidate","decision_reason":f"Downstream outputs invalidated by partial rerun of {component}.","provenance_json":json.dumps(prov,ensure_ascii=False),"updated_at":now}
    if component=="angle":updates.update({"angle":str(obj.get("angle") or "").strip(),"angle_reason":str(obj.get("reason") or "").strip(),"hook":"","hook_rationale":"","script":"","optimized_hook":"","edited_script":"","fact_check_json":"{}","qa_json":"{}"})
    elif component=="hook":updates.update({"hook":str(obj.get("hook") or "").strip(),"hook_rationale":str(obj.get("rationale") or "").strip(),"script":"","optimized_hook":"","edited_script":"","fact_check_json":"{}","qa_json":"{}"})
    elif component=="script":updates.update({"script":str(obj.get("script") or "").strip(),"optimized_hook":"","edited_script":"","fact_check_json":"{}","qa_json":"{}"})
    elif component=="factcheck":obj["findings"]=_normalize_qa_findings(obj.get("findings") or []);updates.update({"fact_check_json":json.dumps(obj,ensure_ascii=False),"optimized_hook":"","edited_script":"","qa_json":"{}"})
    elif component=="optimize":updates.update({"optimized_hook":str(obj.get("optimized_hook") or "").strip(),"edited_script":"","qa_json":"{}"})
    elif component=="editor":updates.update({"edited_script":str(obj.get("edited_script") or "").strip(),"qa_json":"{}"})
    elif component=="qa":
        obj["findings"]=_normalize_qa_findings(obj.get("findings") or []);updates["qa_json"]=json.dumps(obj,ensure_ascii=False)
        if str(obj.get("decision") or "").lower()=="reject":updates["status"]="rejected";updates["decision_reason"]=str(obj.get("reason") or "Rejected by structured QA").strip()
    cols=",".join(f"{k}=?" for k in updates);con=db();con.execute(f"UPDATE production_variants SET {cols} WHERE id=?",(*updates.values(),variant_id));con.commit();con.close();_save_variant_piece(agent,job_id,run_id,variant["batch_id"],variant_id,component,f"Variant {variant['ordinal']} · partial {component}",json.dumps(obj,ensure_ascii=False,indent=2),{"partial_rerun":True});event(job_id,f"Variant {variant['ordinal']}: partial rerun {component}; downstream variant outputs invalidated");await broadcast({"type":"variants","jobId":job_id,"variantId":variant_id,"component":component});return get_job_variants(job_id)

def select_production_variant(job_id,variant_id):
    con=db();row=con.execute("SELECT * FROM production_variants WHERE id=? AND job_id=?",(variant_id,job_id)).fetchone()
    if not row:con.close();raise ValueError("Variant not found")
    chosen=_variant_dict(row)
    if not (chosen.get("edited_script") or chosen.get("script")):con.close();raise ValueError("Variant has no script to select")
    con.execute("UPDATE production_variants SET status='rejected',decision_reason=CASE WHEN id=? THEN decision_reason ELSE 'Not selected in variant comparison.' END,updated_at=? WHERE job_id=? AND batch_id=?",(variant_id,ts(),job_id,chosen["batch_id"]));con.execute("UPDATE production_variants SET status='selected',decision_reason='Selected in Variant Studio.',updated_at=? WHERE id=?",(ts(),variant_id));con.commit();con.close()
    _save_variant_piece("Editor",job_id,None,chosen["batch_id"],variant_id,"selected","Selected production variant",(chosen.get("optimized_hook") or chosen.get("hook") or "")+"\n\n"+(chosen.get("edited_script") or chosen.get("script") or ""),{"selected":True,"manual_selection":True});event(job_id,f"Variant {chosen['ordinal']} selected in Variant Studio");return get_job_variants(job_id)

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
        live_llm=bool(FACTORY_LLM_API_KEY and agent in LLM_LIVE_AGENTS)
        run_model=FACTORY_LLM_MODEL if live_llm else "simulation-v3"
        run_id=start_agent_run(agent,job_id,stage,model=run_model)
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
            mcp_capabilities={}
            for connection in enabled_mcp:
                try:
                    tools=await asyncio.wait_for(asyncio.to_thread(mcp_list_tools,agent,connection,run_id,job_id),timeout=min(25,AGENT_TIMEOUT_SECONDS))
                    mcp_capabilities[connection["name"]]=[x["name"] for x in tools]
                except Exception as exc:
                    mcp_capabilities[connection["name"]]=[f"ERROR: {str(exc)[:120]}"]
            await asyncio.sleep(max(0.05,delay*0.12))

            await push_agent_progress(agent,run_id,job_id,"generate","Producing output",52)
            llm_result=None
            if live_llm:
                usage=get_usage_summary()
                job_cost=get_job_cost(job_id)
                # Reserve the configured maximum output cost before a paid call.
                # This keeps one request from overshooting the daily/job cap.
                max_call_cost=FACTORY_LLM_MAX_OUTPUT_TOKENS * FACTORY_LLM_OUTPUT_USD_PER_1M / 1_000_000
                if usage["today_cost_usd"] + max_call_cost > FACTORY_DAILY_BUDGET_USD:
                    raise RuntimeError("Daily provider budget would be exceeded by the next model call")
                if job_cost + max_call_cost > FACTORY_JOB_BUDGET_USD:
                    raise RuntimeError("Job provider budget would be exceeded by the next model call")
                llm_result=await asyncio.wait_for(
                    asyncio.to_thread(_call_live_llm,agent,job,input_pack),
                    timeout=AGENT_TIMEOUT_SECONDS,
                )
                kind=llm_result["kind"]; title=llm_result["title"]; content=llm_result["content"]; extra=[]
            else:
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
            mode="live_llm" if llm_result else "demo"
            artifact_meta={
                "mode":mode,"stage":stage,"attempt":attempt,
                "enabled_mcp":[x["name"] for x in enabled_mcp],"mcp_capabilities":mcp_capabilities,
            }
            if agent=="QA Agent" and llm_result:
                try:
                    qa_obj=_parse_json_object(content)
                    qa_obj["findings"]=_normalize_qa_findings(qa_obj.get("findings") or [])
                    qa_obj["release_decision"]="pass" if str(qa_obj.get("release_decision","")).lower()=="pass" else "attention"
                    content=json.dumps(qa_obj,ensure_ascii=False,indent=2)
                    artifact_meta["structured_qa"]=qa_obj
                except Exception as exc:
                    artifact_meta["structured_qa_parse_error"]=str(exc)[:240]
            if llm_result:
                artifact_meta.update({
                    "model":llm_result["model"],
                    "provider_request_id":llm_result.get("provider_request_id"),
                })
            save_artifact(agent,kind,title,content,job_id=job_id,run_id=run_id,
                          meta=artifact_meta,**kwargs)
            finish_agent_run(
                run_id,status="completed",
                input_tokens=(llm_result or {}).get("input_tokens",0),
                output_tokens=(llm_result or {}).get("output_tokens",0),
                cost_usd=(llm_result or {}).get("cost_usd",0.0),
                meta={
                    **artifact_meta,
                    "note":(
                        "Live model call completed; MCP capabilities were probed but no MCP tool was invoked automatically."
                        if llm_result else
                        "Demo artifact generated. MCP capabilities were probed; no paid model call was made."
                    ),
                },
            )
            record_run_step(run_id,job_id,agent,"complete","Completed",100,"completed")
            set_agent_progress(agent,100,"Completed",job_id,run_id,"done")
            event(job_id,f"{agent}: completed")
            await broadcast({"type":"agent_progress","agent":agent,"state":"done","progress":agent_progress[agent]})
            return
        except asyncio.TimeoutError:
            last_error=f"Timed out after {AGENT_TIMEOUT_SECONDS}s"
        except Exception as exc:
            last_error=str(exc)

        policy=classify_agent_error(last_error)
        record_run_step(run_id,job_id,agent,"failed",last_error,agent_progress.get(agent,{}).get("progress",0),"failed")
        finish_agent_run(run_id,status="failed",error=last_error,
                         meta={"mode":"live_llm" if live_llm else "demo","attempt":attempt,"error_policy":policy})
        set_agent_progress(agent,agent_progress.get(agent,{}).get("progress",0),f"Failed: {last_error}",job_id,run_id,"failed")
        event(job_id,f"{agent}: attempt {attempt} failed — {last_error}")
        await broadcast({"type":"agent_progress","agent":agent,"state":"failed","progress":agent_progress[agent]})
        if attempt < total_attempts and policy["auto_retry"]:
            event(job_id,f"{agent}: safe automatic retry ({policy['code']})")
            set_agent_progress(agent,5,"Safe retry",job_id,run_id,"working")
            await asyncio.sleep(min(2,attempt))
            continue
        if policy["retryable"] and not policy["auto_retry"]:
            event(job_id,f"{agent}: automatic retry paused ({policy['code']}) — {policy['action']}")
        elif not policy["retryable"]:
            event(job_id,f"{agent}: retry blocked ({policy['code']}) — {policy['action']}")
        raise RuntimeError(f"{agent} failed after {attempt} attempt(s): {last_error}")

def get_job_worker_results(job_id):
    if not job_id:
        return {}
    con=db()
    rows=[dict(x) for x in con.execute(
        """SELECT id,run_id,agent,kind,title,content,url,mime_type,created_at,meta_json
           FROM artifacts WHERE job_id=? ORDER BY created_at DESC""",(job_id,)
    ).fetchall()]
    con.close()
    latest={}
    for row in rows:
        agent=row["agent"]
        if agent in latest:
            continue
        try:
            meta=json.loads(row.pop("meta_json") or "{}")
        except Exception:
            meta={}
        content=(row.get("content") or "").strip()
        latest[agent]={
            "id":row["id"],
            "run_id":row.get("run_id"),
            "agent":agent,
            "kind":row.get("kind"),
            "title":row.get("title"),
            "preview":content[:420],
            "url":row.get("url"),
            "mime_type":row.get("mime_type"),
            "created_at":row.get("created_at"),
            "mode":meta.get("mode"),
            "model":meta.get("model"),
            "variant_id":meta.get("variant_id"),
            "batch_id":meta.get("batch_id"),
            "component":meta.get("component"),
            "selected":bool(meta.get("selected")),
        }
    return latest

def get_job_handoffs(job_id, limit=60):
    if not job_id:
        return []
    con=db()
    rows=[dict(x) for x in con.execute(
        """SELECT ri.run_id,ri.artifact_id,ri.source_agent,ri.created_at,
                  r.agent target_agent,r.stage target_stage,r.status run_status,
                  a.title artifact_title,a.kind artifact_kind
           FROM run_inputs ri
           JOIN agent_runs r ON r.id=ri.run_id
           JOIN artifacts a ON a.id=ri.artifact_id
           WHERE r.job_id=?
           ORDER BY ri.created_at DESC LIMIT ?""",(job_id,limit)
    ).fetchall()]
    con.close()
    return rows

def classify_agent_error(message):
    raw=(message or "").strip()
    low=raw.lower()
    policy={
        "code":"unknown_failure","category":"unknown","severity":"warning",
        "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
        "title":"Unclassified worker failure",
        "action":"Review the failed run before retrying. The provider outcome may be uncertain.",
    }
    if any(x in low for x in ("balance exhausted","insufficient_quota","no credits remaining")):
        policy.update({
            "code":"billing_exhausted","category":"billing","severity":"critical",
            "retryable":True,"auto_retry":False,"requires_confirmation":False,"spend_uncertain":False,
            "title":"Provider balance exhausted","action":"Add provider credits, then retry this worker.",
        })
    elif any(x in low for x in ("authentication failed","factory_llm_api_key is not configured","configured llm model","model/api-mode compatibility","openai rejected the model request","api-mode compatibility")):
        policy.update({
            "code":"provider_configuration","category":"configuration","severity":"critical",
            "retryable":True,"auto_retry":False,"requires_confirmation":False,"spend_uncertain":False,
            "title":"Provider configuration needs attention",
            "action":"Fix the API key, project permission, model or API mode, then retry.",
        })
    elif "budget" in low and any(x in low for x in ("reached","exceeded","would be exceeded")):
        policy.update({
            "code":"budget_guard","category":"budget","severity":"warning",
            "retryable":True,"auto_retry":False,"requires_confirmation":False,"spend_uncertain":False,
            "title":"FactoryOS budget guard stopped the call",
            "action":"Review job/day spend and budget limits before retrying.",
        })
    elif any(x in low for x in ("missing required upstream artifacts","quality gate failed")):
        policy.update({
            "code":"dependency_missing","category":"dependency","severity":"warning",
            "retryable":False,"auto_retry":False,"requires_confirmation":False,"spend_uncertain":False,
            "title":"Upstream dependency is missing",
            "action":"Rebuild the missing upstream worker or artifact before retrying this stage.",
        })
    elif any(x in low for x in ("rate limit","http 429")):
        policy.update({
            "code":"provider_rate_limit","category":"transient","severity":"warning",
            "retryable":True,"auto_retry":True,"requires_confirmation":False,"spend_uncertain":False,
            "title":"Provider rate limit",
            "action":"FactoryOS may safely retry once; if it repeats, wait briefly and retry manually.",
        })
    elif any(x in low for x in ("llm provider http 500","llm provider http 502","llm provider http 503","llm provider http 504")):
        policy.update({
            "code":"provider_5xx","category":"transient","severity":"warning",
            "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
            "title":"Provider service error",
            "action":"Provider outcome may be uncertain. Review the incident before a manual retry.",
        })
    elif any(x in low for x in ("timed out","provider request failed","connection reset","remote end closed","network","temporary failure","name or service not known")):
        policy.update({
            "code":"transport_uncertain","category":"transport","severity":"critical",
            "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
            "title":"Provider outcome is uncertain",
            "action":"Do not auto-retry. Confirm the provider did not complete the request, then retry manually if needed.",
        })
    elif any(x in low for x in ("unsupported response shape","returned empty content")):
        policy.update({
            "code":"provider_response_invalid","category":"provider_response","severity":"warning",
            "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
            "title":"Provider returned an unusable response",
            "action":"The call may already have consumed tokens. Review the incident before retrying.",
        })
    policy["raw"]=raw
    return policy

def get_job_agent_errors(job_id):
    if not job_id:
        return {}
    con=db()
    rows=[dict(x) for x in con.execute(
        """SELECT agent,error,finished_at,id AS run_id,stage,cost_usd
           FROM agent_runs WHERE job_id=? AND status='failed' AND error IS NOT NULL
           ORDER BY finished_at DESC""",(job_id,)
    ).fetchall()]
    con.close()
    latest={}
    for row in rows:
        if row["agent"] not in latest:
            row["policy"]=classify_agent_error(row.get("error"))
            latest[row["agent"]]=row
    return latest

def get_job_error_center(job_id, limit=30):
    empty={"summary":{"open":0,"critical":0,"spend_uncertain":0,"resolved":0},"incidents":[]}
    if not job_id:
        return empty
    con=db()
    failures=[dict(x) for x in con.execute(
        """SELECT id AS run_id,agent,stage,error,started_at,finished_at,cost_usd,model
           FROM agent_runs WHERE job_id=? AND status='failed' AND error IS NOT NULL
           ORDER BY COALESCE(finished_at,started_at) DESC LIMIT ?""",(job_id,limit)
    ).fetchall()]
    completed=[dict(x) for x in con.execute(
        """SELECT agent,MAX(COALESCE(finished_at,started_at)) AS completed_at
           FROM agent_runs WHERE job_id=? AND status='completed' GROUP BY agent""",(job_id,)
    ).fetchall()]
    con.close()
    completed_at={x["agent"]:x.get("completed_at") for x in completed}
    incidents=[]
    for row in failures:
        policy=classify_agent_error(row.get("error"))
        failed_at=row.get("finished_at") or row.get("started_at") or ""
        success_at=completed_at.get(row["agent"]) or ""
        resolved=bool(success_at and failed_at and success_at > failed_at)
        incidents.append({**row,"resolved":resolved,"resolved_at":success_at if resolved else None,"policy":policy})
    unresolved=[x for x in incidents if not x["resolved"]]
    return {
        "summary":{
            "open":len(unresolved),
            "critical":sum(1 for x in unresolved if x["policy"]["severity"]=="critical"),
            "spend_uncertain":sum(1 for x in unresolved if x["policy"]["spend_uncertain"]),
            "resolved":sum(1 for x in incidents if x["resolved"]),
        },
        "incidents":incidents,
    }

def non_retryable_agent_error(message):
    return not classify_agent_error(message)["retryable"]

def safe_auto_retry_agent_error(message):
    return classify_agent_error(message)["auto_retry"]

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
async def verify_builder_bridge():
    if not GITHUB_TOKEN:
        print(json.dumps({"event":"BUILDER_BRIDGE_CHECK","status":"hourly_fallback","reason":"credential_not_configured"}),flush=True)
        return
    try:
        await asyncio.to_thread(github_api,"GET",f"/actions/workflows/{BUILDER_WORKFLOW}")
        print(json.dumps({"event":"BUILDER_BRIDGE_CHECK","status":"ready","workflow":BUILDER_WORKFLOW}),flush=True)
    except Exception as exc:
        print(json.dumps({"event":"BUILDER_BRIDGE_CHECK","status":"error","error":str(exc)[:300]}),flush=True)

async def run_paid_verification_once():
    tag=PAID_VERIFICATION_TAG
    if not tag:
        return
    if not FACTORY_LLM_API_KEY:
        print(json.dumps({"event":"PAID_E2E_VERIFICATION","tag":tag,"status":"skipped","reason":"llm_not_configured"}),flush=True)
        return
    con=db()
    existing=con.execute("SELECT * FROM system_verifications WHERE tag=?",(tag,)).fetchone()
    if existing:
        con.close()
        print(json.dumps({"event":"PAID_E2E_VERIFICATION","tag":tag,"status":"skip_existing","existing_status":existing["status"]}),flush=True)
        return
    started=ts()
    # Persist the fence before any paid provider call. A restart during an
    # uncertain request must never auto-repeat the paid verification.
    con.execute("""INSERT INTO system_verifications(tag,status,started_at,detail)
                   VALUES(?,?,?,?)""",(tag,"started",started,"Explicit user-approved one-shot production verification."))
    con.commit(); con.close()
    job_id=None
    try:
        created=await create_job(JobCreate(
            title="FactoryOS v3.24 controlled live verification",
            brief=(
                "Production verification only. Create concise real artifacts so FactoryOS can prove "
                "live model execution, worker handoffs, token accounting, provider cost, artifact persistence "
                "and the human approval gate. Keep each artifact under 120 words when practical."
            ),
            presenter="Faceless",
            format="Short only",
            language="English",
            outputs=1,
        ))
        job_id=created["id"]
        con=db()
        con.execute("UPDATE system_verifications SET job_id=?,detail=? WHERE tag=?",
                    (job_id,"Paid verification job created; running pipeline to QA approval gate.",tag))
        con.commit(); con.close()
        running_jobs.add(job_id)
        await run_until_review(job_id)
        job=get_job(job_id) or {}
        con=db()
        totals=con.execute("""SELECT COUNT(*) live_runs,
                                     COALESCE(SUM(input_tokens),0) input_tokens,
                                     COALESCE(SUM(output_tokens),0) output_tokens,
                                     COALESCE(SUM(cost_usd),0) cost_usd
                              FROM agent_runs
                              WHERE job_id=? AND status='completed' AND model=?""",
                           (job_id,FACTORY_LLM_MODEL)).fetchone()
        artifact_count=con.execute("SELECT COUNT(*) c FROM artifacts WHERE job_id=?",(job_id,)).fetchone()["c"]
        con.close()
        live_runs=int(totals["live_runs"] or 0)
        input_tokens=int(totals["input_tokens"] or 0)
        output_tokens=int(totals["output_tokens"] or 0)
        cost_usd=float(totals["cost_usd"] or 0)
        passed=(
            job.get("status")=="waiting_approval"
            and live_runs >= 7
            and (input_tokens + output_tokens) > 0
            and cost_usd > 0
            and artifact_count >= 9
        )
        status="passed" if passed else "failed"
        detail=json.dumps({
            "job_status":job.get("status"),
            "artifact_count":artifact_count,
            "approval_gate_reached":job.get("status")=="waiting_approval",
            "expected_min_live_runs":7,
        },ensure_ascii=False)
        con=db()
        con.execute("""UPDATE system_verifications
                       SET status=?,finished_at=?,live_runs=?,input_tokens=?,output_tokens=?,cost_usd=?,detail=?
                       WHERE tag=?""",
                    (status,ts(),live_runs,input_tokens,output_tokens,cost_usd,detail,tag))
        con.commit(); con.close()
        print(json.dumps({
            "event":"PAID_E2E_VERIFICATION","tag":tag,"status":status,"job_id":job_id,
            "job_status":job.get("status"),"artifact_count":artifact_count,"live_runs":live_runs,
            "input_tokens":input_tokens,"output_tokens":output_tokens,"cost_usd":round(cost_usd,6),
            "approval_gate_reached":job.get("status")=="waiting_approval",
        }),flush=True)
    except Exception as exc:
        con=db()
        con.execute("""UPDATE system_verifications SET status='failed',finished_at=?,detail=?,job_id=COALESCE(job_id,?)
                       WHERE tag=?""",(ts(),str(exc)[:1000],job_id,tag))
        con.commit(); con.close()
        print(json.dumps({"event":"PAID_E2E_VERIFICATION","tag":tag,"status":"failed","job_id":job_id,"error":str(exc)[:600]}),flush=True)

@app.on_event("startup")
async def report_llm_readiness():
    print(json.dumps({
        "event":"LLM_PROVIDER_CHECK",
        "configured":bool(FACTORY_LLM_API_KEY),
        "model":FACTORY_LLM_MODEL if FACTORY_LLM_API_KEY else None,
        "api_mode":FACTORY_LLM_API_MODE if FACTORY_LLM_API_KEY else None,
        "base_url":FACTORY_LLM_BASE_URL if FACTORY_LLM_API_KEY else None,
    }),flush=True)
    asyncio.create_task(run_paid_verification_once())

@app.on_event("startup")
async def start_builder_reconciler():
    asyncio.create_task(builder_reconcile_loop())

@app.on_event("startup")
async def start_supervisor():
    backfilled=backfill_legacy_history()
    if backfilled:
        event(None,f"Ledger migration: backfilled {backfilled} historical agent runs")
    asyncio.create_task(supervisor_loop())

@app.on_event("startup")
async def start_content_brain_collector():
    if FACTORY_SIGNAL_FEEDS:
        asyncio.create_task(content_brain_collector_loop())

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
        "factory":"online","version":APP_VERSION,"buildSha":BUILD_SHA,"factoryMcpConfigured":bool(FACTORY_MCP_TOKEN),"jobs":jobs,"selectedJobId":sid,"selectedJob":selected,
        "selectedJobQuality": get_job_quality(sid) if sid else None,
        "selectedJobWorkerResults": get_job_worker_results(sid),
        "selectedJobHandoffs": get_job_handoffs(sid),
        "selectedJobAgentErrors": get_job_agent_errors(sid),
        "selectedJobErrorCenter": get_job_error_center(sid),
        "selectedJobVariants": get_job_variants(sid),
        "events":ev,"connections":CONNECTIONS,"stages":STAGES,
        "agentStates":agent_states(jobs),"agentProgress":{a:get_agent_progress_snapshot(a) for a in AGENTS},"agentMap":AGENT_MAP,
        "agentDependencies":AGENT_DEPENDENCIES,
        "runningJobs":list(running_jobs),"nextAction":next_action(selected),
        "supervisor": report,
        "supervisorState": supervisor_runtime.get("state", "monitoring"),
        "usage": get_usage_summary(),
        "agentMetrics": {a:get_agent_metrics(a) for a in AGENTS},
        "improvementProposals": get_improvement_proposals("proposed",5),
        "contentBrain": get_content_brain(12),
        "buildProgress": get_factory_tasks(),
        "runtimePolicy": {
            "agent_timeout_seconds":AGENT_TIMEOUT_SECONDS,
            "max_retries":AGENT_MAX_RETRIES,
            "daily_budget_usd":FACTORY_DAILY_BUDGET_USD,
            "job_budget_usd":FACTORY_JOB_BUDGET_USD
        }
    }

@app.get("/api/release-readiness")
def release_readiness():
    return get_release_readiness()

@app.get("/api/intelligence")
def factory_intelligence():
    return get_factory_intelligence()


@app.get("/api/content-brain")
def content_brain(limit: int = 50):
    return get_content_brain(max(1,min(200,int(limit))))

@app.post("/api/content-brain/collect")
async def collect_content_brain_signals():
    result=await asyncio.to_thread(collect_configured_signals,20)
    if result["created_count"]:
        event(None,f"Content Brain collected {result['created_count']} new RSS signal(s)")
        await broadcast({"type":"content_brain","action":"signals_collected","count":result["created_count"]})
    return result

@app.post("/api/content-brain/signals")
async def add_content_signal(payload: SignalCreate):
    try:
        result=ingest_source_signal(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    if result["created"]:
        event(None,f"Content Brain signal ingested: {result['signal']['title']}")
        await broadcast({"type":"content_brain","action":"signal_ingested","signalId":result["signal"]["id"]})
    return result

@app.post("/api/content-brain/generate")
async def generate_content_brain(payload: IdeaGenerateRequest):
    try:
        result=await generate_ideas_from_signals(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except RuntimeError as exc:
        raise HTTPException(503,str(exc))
    event(None,f"Content Brain generated {len(result['ideas'])} idea(s)")
    await broadcast({"type":"content_brain","action":"generated","count":len(result["ideas"]),"runId":result["run_id"]})
    return result

@app.post("/api/content-brain/process")
async def process_content_brain(payload: IdeaProcessRequest):
    try:
        result=await process_content_brain_ideas(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    except RuntimeError as exc:
        raise HTTPException(503,str(exc))
    await broadcast({"type":"content_brain","action":"processed","count":result["count"]})
    return result

@app.post("/api/content-brain/ideas")
async def add_content_idea(payload: IdeaCreate):
    try:
        idea=create_content_idea(payload)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    event(None,f"Content Brain idea created: {idea['title']}")
    await broadcast({"type":"content_brain","action":"idea_created","ideaId":idea["id"]})
    return {"created":True,"idea":idea}

@app.post("/api/content-brain/ideas/{idea_id}/status")
async def set_content_idea_status(idea_id: str, payload: IdeaStatus):
    allowed={"generated","shortlisted","selected","rejected","in_production"}
    status=(payload.status or "").strip().lower()
    if status not in allowed:
        raise HTTPException(400,"Unknown idea status")
    con=db()
    row=con.execute("SELECT id,title FROM content_ideas WHERE id=?",(idea_id,)).fetchone()
    if not row:
        con.close(); raise HTTPException(404,"Idea not found")
    con.execute("UPDATE content_ideas SET status=?,updated_at=? WHERE id=?",(status,ts(),idea_id))
    con.commit(); con.close()
    event(None,f"Content Brain idea status: {row['title']} → {status}")
    await broadcast({"type":"content_brain","action":"idea_status","ideaId":idea_id,"status":status})
    return {"ok":True,"idea_id":idea_id,"status":status}

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
    restarted_from_review=False
    if job["status"] == "waiting_approval":
        # "Run Factory" means re-run the production pipeline, not publish.
        # Preserve the human approval gate while allowing an existing reviewed
        # job to be regenerated after provider/configuration changes.
        con=db()
        research_progress=int(STAGES.index("research")/(len(STAGES)-1)*100)
        con.execute(
            "UPDATE jobs SET stage='research',status='idle',progress=?,updated_at=? WHERE id=?",
            (research_progress,ts(),job_id),
        )
        con.commit(); con.close()
        event(job_id,"Factory restart requested from review gate; approval remains required before publish")
        restarted_from_review=True
    usage=get_usage_summary()
    if usage["today_cost_usd"] >= FACTORY_DAILY_BUDGET_USD:
        return {"ok":False,"message":"Daily provider budget reached. Increase the budget only after review."}
    if get_job_cost(job_id) >= FACTORY_JOB_BUDGET_USD:
        return {"ok":False,"message":"This job reached its provider budget. Review its agent ledger before continuing."}
    running_jobs.add(job_id)
    asyncio.create_task(run_until_review(job_id))
    return {
        "ok":True,
        "message":"Factory restarted from Research with the approval gate preserved." if restarted_from_review else "Factory started."
    }

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
            if stage=="script":
                await run_variant_pipeline(job_id,3)
            else:
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
async def rerun_agent(job_id:str,agent_name:str,expected_run_id:str | None=None,confirm_uncertain:bool=False):
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
    center=get_job_error_center(job_id)
    incident=next((x for x in center["incidents"] if x["agent"]==agent_name and not x["resolved"]),None)
    if expected_run_id and (not incident or incident["run_id"]!=expected_run_id):
        return {"ok":False,"message":"This recovery incident is stale or already resolved. Refresh Error Center before retrying."}
    if incident:
        policy=incident["policy"]
        if not policy["retryable"]:
            return {"ok":False,"message":policy["action"],"recovery":policy}
        if policy["requires_confirmation"] and not confirm_uncertain:
            return {
                "ok":False,"requiresConfirmation":True,"failedRunId":incident["run_id"],
                "message":"Provider outcome may be uncertain and a retry could duplicate spend. Confirm the incident before retrying.",
                "recovery":policy,
            }
    live_llm=bool(FACTORY_LLM_API_KEY and agent_name in LLM_LIVE_AGENTS)
    if live_llm:
        usage=get_usage_summary(); job_cost=get_job_cost(job_id)
        max_call_cost=FACTORY_LLM_MAX_OUTPUT_TOKENS * FACTORY_LLM_OUTPUT_USD_PER_1M / 1_000_000
        if usage["today_cost_usd"] + max_call_cost > FACTORY_DAILY_BUDGET_USD:
            return {"ok":False,"message":"Daily provider budget guard blocks this recovery retry."}
        if job_cost + max_call_cost > FACTORY_JOB_BUDGET_USD:
            return {"ok":False,"message":"Job provider budget guard blocks this recovery retry."}
    running_jobs.add(job_id)
    con=db()
    con.execute("UPDATE jobs SET stage=?,status='running',progress=?,updated_at=? WHERE id=?",
                (stage,int(STAGES.index(stage)/(len(STAGES)-1)*100),ts(),job_id))
    con.commit(); con.close()
    recovery_code=(incident or {}).get("policy",{}).get("code","manual_rerun")
    event(job_id,f"Manual recovery requested: {agent_name} ({recovery_code}); downstream outputs will require rebuild")
    asyncio.create_task(rerun_single_agent(job_id,agent_name,stage))
    await broadcast()
    return {"ok":True,"message":f"{agent_name} recovery rerun started","recovery":(incident or {}).get("policy")}

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

@app.get("/api/handoffs/{run_id}/{artifact_id}")
def handoff_trace(run_id:str, artifact_id:str):
    con=db()
    row=con.execute(
        """SELECT ri.run_id,ri.artifact_id,ri.source_agent,ri.created_at handoff_at,
                  r.agent target_agent,r.stage target_stage,r.status target_status,r.started_at target_started_at,r.finished_at target_finished_at,
                  a.job_id,a.kind artifact_kind,a.title artifact_title,a.content artifact_content,a.url artifact_url,a.mime_type,a.created_at artifact_created_at
           FROM run_inputs ri
           JOIN agent_runs r ON r.id=ri.run_id
           JOIN artifacts a ON a.id=ri.artifact_id
           WHERE ri.run_id=? AND ri.artifact_id=?""",(run_id,artifact_id)
    ).fetchone()
    if not row:
        con.close()
        raise HTTPException(404,"Handoff not found")
    data=dict(row)
    source_run=con.execute(
        """SELECT id,stage,status,started_at,finished_at,input_tokens,output_tokens,cost_usd
           FROM agent_runs WHERE id=(SELECT run_id FROM artifacts WHERE id=?)""",(artifact_id,)
    ).fetchone()
    con.close()
    data["source_run"]=dict(source_run) if source_run else None
    return data


@app.get("/api/jobs/{job_id}/variants")
def job_variants(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return get_job_variants(job_id)

async def _manual_variant_build(job_id):
    try:
        await run_variant_pipeline(job_id,3)
        con=db();con.execute("UPDATE jobs SET stage='script',status='idle',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("script")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close();event(job_id,"Manual variant build completed; continue Factory to rebuild downstream stages");await broadcast()
    except Exception as exc:
        con=db();con.execute("UPDATE jobs SET stage='script',status='failed',updated_at=? WHERE id=?",(ts(),job_id));con.commit();con.close();event(job_id,f"Variant build failed: {exc}");await broadcast({"type":"job_failed","jobId":job_id,"error":str(exc)})
    finally:running_jobs.discard(job_id)

@app.post("/api/jobs/{job_id}/variants/generate")
async def generate_job_variants(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    if job_id in running_jobs:return {"ok":False,"message":"Wait for the current job run to finish first"}
    if FACTORY_LLM_API_KEY:
        try:_variant_budget_guard(job_id,1200)
        except RuntimeError as exc:return {"ok":False,"message":str(exc)}
    running_jobs.add(job_id);con=db();con.execute("UPDATE jobs SET stage='script',status='running',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("script")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close();asyncio.create_task(_manual_variant_build(job_id));await broadcast();return {"ok":True,"message":"Production variant build started"}

@app.post("/api/jobs/{job_id}/variants/{variant_id}/rerun/{component}")
async def rerun_job_variant(job_id:str,variant_id:str,component:str):
    if job_id in running_jobs:return {"ok":False,"message":"Wait for the current job run to finish first"}
    try:result=await rerun_variant_component(job_id,variant_id,component)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    return {"ok":True,"variants":result}

@app.post("/api/jobs/{job_id}/variants/{variant_id}/select")
async def select_job_variant(job_id:str,variant_id:str):
    try:result=select_production_variant(job_id,variant_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"variants","jobId":job_id,"variantId":variant_id,"action":"selected"});return {"ok":True,"variants":result}

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
    approved=sorted(set(x.strip() for x in item.allowed_tools if x and x.strip()))
    con.execute("""INSERT INTO agent_mcp_connections(id,agent,name,transport,endpoint,auth_env,enabled,status,created_at,updated_at,allowed_tools_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (connection_id,agent_name,item.name.strip() or "MCP Server",item.transport,endpoint,auth_env,0,"configured",now,now,json.dumps(approved)))
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

@app.get("/api/agents/{agent_name}/mcp/{connection_id}/tools")
async def list_agent_mcp_tools(agent_name:str,connection_id:str):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    connection=next((x for x in get_agent_mcp_connections(agent_name) if x["id"]==connection_id),None)
    if not connection:
        raise HTTPException(404,"MCP connection not found")
    try:
        tools=await asyncio.to_thread(mcp_list_tools,agent_name,connection)
        return {"ok":True,"tools":tools,"allowed_tools":connection.get("allowed_tools",[])}
    except Exception as exc:
        raise HTTPException(502,str(exc))

@app.post("/api/agents/{agent_name}/mcp/{connection_id}/call")
async def call_agent_mcp_tool(agent_name:str,connection_id:str,item:McpToolCall):
    if agent_name not in AGENTS:
        raise HTTPException(404,"Agent not found")
    connection=next((x for x in get_agent_mcp_connections(agent_name) if x["id"]==connection_id),None)
    if not connection:
        raise HTTPException(404,"MCP connection not found")
    if not connection.get("enabled"):
        raise HTTPException(409,"MCP connection is disabled")
    try:
        result=await asyncio.to_thread(mcp_call_tool,agent_name,connection,item.tool_name,item.arguments)
        event(None,f"MCP tool called for {agent_name}: {item.tool_name}")
        await broadcast({"type":"mcp_tool_call","agent":agent_name,"tool":item.tool_name})
        return {"ok":True,"result":result}
    except Exception as exc:
        raise HTTPException(502,str(exc))

@app.get("/api/factory/builder")
def factory_builder_status():
    return {
        "instant_dispatch":bool(GITHUB_TOKEN),
        "repo":GITHUB_REPO,
        "workflow":BUILDER_WORKFLOW,
        "mode":"github_actions_plus_autonomous_builder" if GITHUB_TOKEN else "autonomous_hourly_queue",
        "reconcile_seconds":15,
        "note":"GitHub preflight runs immediately; code implementation is a separate worker phase.",
    }

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
    live_workflow_states={"queued","in_progress","waiting","pending","requested","dispatching"}
    if row["status"]=="in_progress" and (row["workflow_status"] or "") in live_workflow_states:
        con.close()
        return {"ok":True,"message":"Task is already running in Factory Builder","task":factory_task_detail(task_id),"already_queued":True}
    now=ts()
    con.execute("""UPDATE factory_tasks
                   SET status='in_progress',builder_state='queued',requested_at=?,updated_at=?,completed_at=NULL,
                       workflow_run_id=NULL,workflow_url=NULL,workflow_status=NULL,
                       builder_note='Queued from FactoryOS. Immediate GitHub dispatch will be attempted when configured.'
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
    dispatch_state="hourly_queue"
    dispatch_error=None
    if GITHUB_TOKEN:
        try:
            await dispatch_builder_workflow(dict(row))
            dispatch_state="github_dispatched"
            con=db(); con.execute("""UPDATE factory_tasks SET builder_state='queued',workflow_status='dispatching',
                                     builder_note=? WHERE id=?""",
                                  ("GitHub Builder preflight dispatched immediately.",task_id))
            con.commit(); con.close()
            asyncio.create_task(track_builder_dispatch(task_id,now))
        except Exception as exc:
            dispatch_error=str(exc)
            con=db(); con.execute("UPDATE factory_tasks SET workflow_status='dispatch_failed',builder_note=? WHERE id=?",
                                  (f"Immediate dispatch failed; hourly Builder queue remains active. {dispatch_error}",task_id))
            con.commit(); con.close()
    await broadcast({"type":"builder_task_started","taskId":task_id,"dispatch":dispatch_state})
    return {"ok":True,
            "message":"Immediate GitHub Builder started" if dispatch_state=="github_dispatched" else "Task queued for autonomous Factory Builder",
            "dispatch":dispatch_state,"dispatch_error":dispatch_error,
            "task":factory_task_detail(task_id),"already_queued":False}

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
