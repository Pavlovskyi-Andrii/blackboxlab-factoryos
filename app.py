import asyncio
import json
import time
import threading
import sqlite3
import uuid
import os
import hmac
import hashlib
import secrets
import io
import re
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib import request as urlrequest, error as urlerror, parse as urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BASE = Path(__file__).resolve().parent
APP_VERSION = "v4.8.1"
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
FACTORY_REAL_PILOT_TAG = os.environ.get("FACTORY_REAL_PILOT_TAG", "").strip()
FACTORY_REAL_PILOT_SIGNALS_JSON = os.environ.get("FACTORY_REAL_PILOT_SIGNALS_JSON", "").strip()
FACTORY_REAL_PILOT_MAX_USD = max(0.01, float(os.environ.get("FACTORY_REAL_PILOT_MAX_USD", "0.75")))
FACTORY_REAL_PILOT_MAX_IDEAS = max(1, min(2, int(os.environ.get("FACTORY_REAL_PILOT_MAX_IDEAS", "1"))))
FACTORY_REAL_PILOT_LANGUAGE = (os.environ.get("FACTORY_REAL_PILOT_LANGUAGE", "English").strip() or "English")
FACTORY_REAL_PILOT_RESUME_STARTED = os.environ.get("FACTORY_REAL_PILOT_RESUME_STARTED", "").strip().lower() in ("1","true","yes","on")
real_pilot_runtime={"active":False,"tag":None,"started_at":None,"max_usd":FACTORY_REAL_PILOT_MAX_USD}
# Historical production verification evidence remains queryable, but the startup trigger is disabled after the passed v3.24 run.
VERIFICATION_EVIDENCE_TAG = "v3.24-live-e2e-2026-10-19"
PAID_VERIFICATION_TAG = ""
LLM_LIVE_AGENTS = {
    "Scout","Researcher","Tech Verifier","Hook Writer","Angle Strategist","Hook Generator",
    "Scriptwriter","Fact Checker","Hook Optimizer","Editor","Content Packager","Visual Director","QA Agent","Publisher","Analyst",
}

DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factory.db"
MEDIA_UPLOAD_DIR = DATA_DIR / "media_uploads"
MEDIA_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
FACTORY_MEDIA_UPLOAD_MAX_BYTES = max(10 * 1024 * 1024, int(os.environ.get("FACTORY_MEDIA_UPLOAD_MAX_BYTES", str(500 * 1024 * 1024))))
MEDIA_ARCHIVE_DIR = DATA_DIR / "media_archive"
MEDIA_ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
FACTORY_MEDIA_ARCHIVE_MAX_BYTES = max(10 * 1024 * 1024, int(os.environ.get("FACTORY_MEDIA_ARCHIVE_MAX_BYTES", str(600 * 1024 * 1024))))
FACTORY_PUBLIC_BASE_URL = (os.environ.get("FACTORY_PUBLIC_BASE_URL", "https://blackboxlab-factoryos.onrender.com").strip().rstrip("/")
                           or "https://blackboxlab-factoryos.onrender.com")
FACTORY_MEDIA_FINISHER_EPHEMERAL_HOSTS = {
    x.strip().lower() for x in os.environ.get(
        "FACTORY_MEDIA_FINISHER_EPHEMERAL_HOSTS","blackboxlab-media-finisher.onrender.com"
    ).split(",") if x.strip()
}
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
AGENTS = list(dict.fromkeys([a for stage in STAGES for a in AGENT_MAP.get(stage, [])] + ["Hook Writer","Content Packager","AI Media Finisher","Supervisor","Design Partner"]))

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
    "Content Packager": ["Editor","Fact Checker"],
    "AI Media Finisher": ["Content Packager","Render Agent"],
    "Visual Director": ["Content Packager"],
    "Voice Agent": ["Content Packager"],
    "Render Agent": ["Visual Director","Voice Agent"],
    "QA Agent": ["Render Agent","Content Packager","Fact Checker"],
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
    "Content Packager": {"stage":"package","role":"Short-form content packager","goal":"Turn the selected verified variant into one traceable package containing scenes, voice-over, subtitles, publishing metadata, thumbnail concept and media brief."},
    "AI Media Finisher": {"stage":"post-production","role":"Deterministic short-form media finisher","goal":"Turn raw/generated media into a traceable finished short using word timing, cut plans, captions, motion, audio finishing and safe-zone QA without changing approved facts."},
    "Visual Director": {"stage":"visual","role":"Visual director","goal":"Translate the selected Content Package into shots, screen recordings, graphics and image prompts."},
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
FACTORY_MEDIA_ADAPTERS = {
    "tts": os.environ.get("FACTORY_TTS_ADAPTER", "").strip(),
    "image": os.environ.get("FACTORY_IMAGE_ADAPTER", "").strip(),
    "video": os.environ.get("FACTORY_VIDEO_ADAPTER", "").strip(),
    "stock": os.environ.get("FACTORY_STOCK_ADAPTER", "").strip(),
}
FACTORY_PUBLISHER_ADAPTER = (os.environ.get("FACTORY_PUBLISHER_ADAPTER", "manual").strip().lower() or "manual")
FACTORY_PUBLISHER_ENDPOINT = os.environ.get("FACTORY_PUBLISHER_ENDPOINT", "").strip()
FACTORY_PUBLISHER_TOKEN = os.environ.get("FACTORY_PUBLISHER_TOKEN", "").strip()
FACTORY_PUBLISHER_SCHEDULER_ENABLED = os.environ.get("FACTORY_PUBLISHER_SCHEDULER_ENABLED", "0").strip().lower() in ("1","true","yes","on")
FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC = max(15,min(600,int(os.environ.get("FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC","60"))))
FACTORY_ANALYTICS_ADAPTER = (os.environ.get("FACTORY_ANALYTICS_ADAPTER", "manual").strip().lower() or "manual")
FACTORY_ANALYTICS_ENDPOINT = os.environ.get("FACTORY_ANALYTICS_ENDPOINT", "").strip()
FACTORY_ANALYTICS_TOKEN = os.environ.get("FACTORY_ANALYTICS_TOKEN", "").strip()
FACTORY_TRANSCRIPT_ADAPTER = (os.environ.get("FACTORY_TRANSCRIPT_ADAPTER", "manual").strip().lower() or "manual")
FACTORY_TRANSCRIPT_ENDPOINT = os.environ.get("FACTORY_TRANSCRIPT_ENDPOINT", "").strip()
FACTORY_TRANSCRIPT_TOKEN = os.environ.get("FACTORY_TRANSCRIPT_TOKEN", "").strip()
FACTORY_VIDEO_ENDPOINT = os.environ.get("FACTORY_VIDEO_ENDPOINT", "").strip()
FACTORY_VIDEO_TOKEN = os.environ.get("FACTORY_VIDEO_TOKEN", "").strip()
FACTORY_VIDEO_STATUS_ENDPOINT = os.environ.get("FACTORY_VIDEO_STATUS_ENDPOINT", "").strip()
FACTORY_VIDEO_CALLBACK_TOKEN = os.environ.get("FACTORY_VIDEO_CALLBACK_TOKEN", "").strip()
FACTORY_MEDIA_FINISHER_ADAPTER = (os.environ.get("FACTORY_MEDIA_FINISHER_ADAPTER", "webhook").strip().lower() or "webhook")
FACTORY_MEDIA_FINISHER_ENDPOINT = os.environ.get("FACTORY_MEDIA_FINISHER_ENDPOINT", "").strip()
FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT = os.environ.get("FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT", "").strip()
FACTORY_MEDIA_FINISHER_SHARED_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_SHARED_TOKEN", "").strip()
FACTORY_MEDIA_FINISHER_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_TOKEN", "").strip() or FACTORY_MEDIA_FINISHER_SHARED_TOKEN
FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN", "").strip() or FACTORY_MEDIA_FINISHER_SHARED_TOKEN
FACTORY_MEDIA_FINISHER_PILOT_TAG = os.environ.get("FACTORY_MEDIA_FINISHER_PILOT_TAG", "").strip()
FACTORY_MEDIA_FINISHER_PILOT_SOURCE_URL = os.environ.get("FACTORY_MEDIA_FINISHER_PILOT_SOURCE_URL", "").strip()
FACTORY_DISCOVERY_ENDPOINT = os.environ.get("FACTORY_DISCOVERY_ENDPOINT", "").strip()
FACTORY_DISCOVERY_TOKEN = os.environ.get("FACTORY_DISCOVERY_TOKEN", "").strip()
FACTORY_DISCOVERY_TOPICS = [x.strip() for x in os.environ.get("FACTORY_DISCOVERY_TOPICS", "").split(",") if x.strip()]
FACTORY_DISCOVERY_INTERVAL_MINUTES = max(15, int(os.environ.get("FACTORY_DISCOVERY_INTERVAL_MINUTES", "360")))
FACTORY_DISCOVERY_SEED_JSON = os.environ.get("FACTORY_DISCOVERY_SEED_JSON", "").strip()
FACTORY_DISCOVERY_SEED_AUTO_REVIDEO = os.environ.get("FACTORY_DISCOVERY_SEED_AUTO_REVIDEO", "").strip().lower() in ("1","true","yes","on")

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
    public_prefixes = ("/static/", "/.well-known/", "/media-source/", "/media-archive/")
    finisher_callback = re.fullmatch(r"/api/media-finisher/[0-9a-fA-F-]+/callback", request.url.path)
    if (FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN and finisher_callback) or request.url.path.startswith(public_prefixes) or request.url.path in public_paths or request.url.path=="/register":
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
        "real_pilot": get_real_pilot(),
    }

clients: set[WebSocket] = set()
running_jobs: set[str] = set()
package_building: set[str] = set()
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
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    return con

def get_paid_verification(tag=VERIFICATION_EVIDENCE_TAG):
    if not tag:
        return {"status":"disabled","live_runs":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}
    con=db()
    row=con.execute("SELECT * FROM system_verifications WHERE tag=?",(tag,)).fetchone()
    con.close()
    return dict(row) if row else {"tag":tag,"status":"pending","live_runs":0,"input_tokens":0,"output_tokens":0,"cost_usd":0}

def get_real_pilot(tag=None):
    tag=(tag if tag is not None else FACTORY_REAL_PILOT_TAG).strip()
    if not tag:
        return {"tag":"","status":"disabled","cycle_id":None,"job_id":None,"cost_usd":0.0,"approval_gate_reached":False}
    row=get_paid_verification(tag)
    detail=row.get("detail") or ""
    try:meta=json.loads(detail) if detail.strip().startswith("{") else {}
    except Exception:meta={}
    return {
        "tag":tag,"status":row.get("status","pending"),"cycle_id":meta.get("cycle_id"),
        "job_id":row.get("job_id") or meta.get("job_id"),"cost_usd":round(float(row.get("cost_usd") or 0),6),
        "live_runs":int(row.get("live_runs") or 0),
        "total_tokens":int(row.get("input_tokens") or 0)+int(row.get("output_tokens") or 0),
        "approval_gate_reached":bool(meta.get("approval_gate_reached")),
        "idea_title":meta.get("idea_title"),"source_urls":meta.get("source_urls") or [],
        "quote_usd":meta.get("quote_usd"),"max_usd":meta.get("max_usd"),
        "error":meta.get("error"),
    }

def _pilot_spend_since(started_at):
    if not started_at:return 0.0
    con=db()
    row=con.execute("""SELECT COALESCE(SUM(cost_usd),0) cost FROM agent_runs
                       WHERE started_at>=? AND model!='simulation-v3'""",(started_at,)).fetchone()
    con.close()
    return round(float(row["cost"] or 0),6)

def _real_pilot_budget_guard(output_tokens=1200):
    if not real_pilot_runtime.get("active"):return 0.0
    started=real_pilot_runtime.get("started_at")
    max_usd=float(real_pilot_runtime.get("max_usd") or FACTORY_REAL_PILOT_MAX_USD)
    spent=_pilot_spend_since(started)
    # Conservative reserve includes 5k input tokens plus the configured output ceiling.
    reserve=(5000*FACTORY_LLM_INPUT_USD_PER_1M + max(128,int(output_tokens))*FACTORY_LLM_OUTPUT_USD_PER_1M)/1_000_000
    if spent + reserve > max_usd + 1e-9:
        raise RuntimeError(f"Real pilot hard budget would be exceeded: spent USD {spent:.6f} + reserve USD {reserve:.6f} > USD {max_usd:.6f}")
    return reserve

def _verification_update(tag, values, attempts=6):
    last=None
    for n in range(max(1,attempts)):
        con=None
        try:
            con=db()
            cols=",".join(f"{k}=?" for k in values)
            con.execute(f"UPDATE system_verifications SET {cols} WHERE tag=?",(*values.values(),tag))
            con.commit();con.close();return
        except sqlite3.OperationalError as exc:
            last=exc
            if con:
                try:con.close()
                except Exception:pass
            if "locked" not in str(exc).lower():raise
            time.sleep(0.15*(n+1))
    raise last or RuntimeError("verification update failed")

def _parse_real_pilot_signals(raw=None):
    raw=FACTORY_REAL_PILOT_SIGNALS_JSON if raw is None else raw
    if not str(raw or "").strip():
        raise ValueError("FACTORY_REAL_PILOT_SIGNALS_JSON is empty")
    data=json.loads(raw)
    if not isinstance(data,list) or not data:
        raise ValueError("Pilot signals must be a non-empty JSON array")
    out=[]
    for item in data[:6]:
        if not isinstance(item,dict):continue
        title=" ".join(str(item.get("title") or "").split()).strip()
        url=str(item.get("url") or "").strip()
        content=" ".join(str(item.get("content") or "").split()).strip()
        topic=" ".join(str(item.get("topic") or "AI / technology").split()).strip()
        if not title or not url or not content:continue
        out.append({"title":title[:300],"url":url[:2000],"content":content[:7000],"topic":topic[:200]})
    if not out:
        raise ValueError("Pilot signal array contains no usable title/url/content items")
    return out

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
    CREATE TABLE IF NOT EXISTS content_packages(
      id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      variant_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'ready',
      package_json TEXT NOT NULL DEFAULT '{}',
      srt_text TEXT NOT NULL DEFAULT '',
      generation_cost_usd REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_content_packages_job ON content_packages(job_id, created_at DESC);
    CREATE INDEX IF NOT EXISTS idx_content_packages_variant ON content_packages(variant_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS approval_decisions(
      id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      package_id TEXT,
      variant_id TEXT,
      decision TEXT NOT NULL,
      reason TEXT DEFAULT '',
      component TEXT DEFAULT '',
      actor TEXT NOT NULL DEFAULT 'owner',
      created_at TEXT NOT NULL,
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_approval_job ON approval_decisions(job_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS publishing_queue(
      id TEXT PRIMARY KEY,
      job_id TEXT NOT NULL,
      package_id TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'approved',
      target TEXT NOT NULL DEFAULT 'manual',
      platform TEXT NOT NULL DEFAULT 'unspecified',
      scheduled_at TEXT,
      idempotency_key TEXT UNIQUE NOT NULL,
      attempt_count INTEGER NOT NULL DEFAULT 0,
      external_post_id TEXT,
      external_url TEXT,
      last_error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      published_at TEXT,
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_publish_status ON publishing_queue(status, scheduled_at, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_publish_job ON publishing_queue(job_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS performance_snapshots(
      id TEXT PRIMARY KEY,
      publish_id TEXT NOT NULL,
      job_id TEXT NOT NULL,
      platform TEXT NOT NULL DEFAULT 'unspecified',
      captured_at TEXT NOT NULL,
      metrics_json TEXT NOT NULL DEFAULT '{}',
      source TEXT NOT NULL DEFAULT 'manual',
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_perf_publish ON performance_snapshots(publish_id, captured_at DESC);
    CREATE INDEX IF NOT EXISTS idx_perf_job ON performance_snapshots(job_id, captured_at DESC);
    CREATE TABLE IF NOT EXISTS job_idea_links(
      job_id TEXT PRIMARY KEY,
      idea_id TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_job_idea ON job_idea_links(idea_id, created_at DESC);
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
    CREATE TABLE IF NOT EXISTS workflow_versions(
      id TEXT PRIMARY KEY,
      name TEXT NOT NULL,
      proposal_id TEXT,
      parent_id TEXT,
      status TEXT NOT NULL DEFAULT 'draft',
      created_at TEXT NOT NULL,
      config_json TEXT NOT NULL DEFAULT '{}',
      notes TEXT DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_versions_status ON workflow_versions(status, created_at DESC);
    CREATE TABLE IF NOT EXISTS job_workflow_versions(
      job_id TEXT PRIMARY KEY,
      workflow_version_id TEXT NOT NULL,
      experiment_id TEXT,
      arm TEXT,
      assigned_at TEXT NOT NULL,
      locked INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX IF NOT EXISTS idx_job_workflow_experiment ON job_workflow_versions(experiment_id, arm, assigned_at DESC);
    CREATE TABLE IF NOT EXISTS experiments(
      id TEXT PRIMARY KEY,
      proposal_id TEXT NOT NULL,
      title TEXT NOT NULL,
      hypothesis TEXT NOT NULL,
      primary_metric TEXT NOT NULL,
      metric_direction TEXT NOT NULL DEFAULT 'higher',
      min_samples_per_arm INTEGER NOT NULL DEFAULT 2,
      min_effect_pct REAL NOT NULL DEFAULT 5.0,
      platform TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'draft',
      control_version_id TEXT NOT NULL,
      treatment_version_id TEXT NOT NULL,
      baseline_active_version_id TEXT NOT NULL,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      started_at TEXT,
      evaluated_at TEXT,
      decision TEXT,
      decision_reason TEXT DEFAULT '',
      rollout_version_id TEXT,
      evaluation_json TEXT DEFAULT '{}',
      meta_json TEXT DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_experiments_status ON experiments(status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS workflow_rollouts(
      id TEXT PRIMARY KEY,
      experiment_id TEXT NOT NULL,
      action TEXT NOT NULL,
      from_version_id TEXT,
      to_version_id TEXT,
      actor TEXT NOT NULL DEFAULT 'owner',
      reason TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_workflow_rollouts_exp ON workflow_rollouts(experiment_id, created_at DESC);
    CREATE TABLE IF NOT EXISTS factory_cycles(
      id TEXT PRIMARY KEY,
      parent_cycle_id TEXT,
      status TEXT NOT NULL DEFAULT 'ready',
      phase TEXT NOT NULL DEFAULT 'signals',
      source_signal_ids_json TEXT NOT NULL DEFAULT '[]',
      idea_id TEXT,
      job_id TEXT,
      publish_id TEXT,
      workflow_version_id TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      started_at TEXT,
      completed_at TEXT,
      last_error TEXT DEFAULT '',
      learning_json TEXT NOT NULL DEFAULT '{}',
      meta_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_factory_cycles_status ON factory_cycles(status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_factory_cycles_job ON factory_cycles(job_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_factory_cycles_publish ON factory_cycles(publish_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS factory_cycle_events(
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      cycle_id TEXT NOT NULL,
      ts TEXT NOT NULL,
      phase TEXT NOT NULL,
      message TEXT NOT NULL,
      meta_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_factory_cycle_events_cycle ON factory_cycle_events(cycle_id, id DESC);
    CREATE TABLE IF NOT EXISTS discovery_candidates(
      id TEXT PRIMARY KEY,
      fingerprint TEXT NOT NULL UNIQUE,
      platform TEXT NOT NULL DEFAULT 'youtube',
      source_url TEXT NOT NULL,
      external_id TEXT DEFAULT '',
      title TEXT NOT NULL,
      creator TEXT DEFAULT '',
      thumbnail_url TEXT DEFAULT '',
      topic TEXT DEFAULT '',
      language TEXT DEFAULT '',
      content_type TEXT DEFAULT '',
      published_at TEXT DEFAULT '',
      duration_sec REAL,
      views INTEGER,
      vph REAL,
      engagement_rate REAL,
      breakout_score REAL,
      transcript TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'new',
      revideo_project_id TEXT,
      discovered_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      metrics_json TEXT NOT NULL DEFAULT '{}',
      provenance_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_discovery_status ON discovery_candidates(status, discovered_at DESC);
    CREATE INDEX IF NOT EXISTS idx_discovery_breakout ON discovery_candidates(breakout_score DESC, vph DESC);
    CREATE TABLE IF NOT EXISTS revideo_projects(
      id TEXT PRIMARY KEY,
      source_url TEXT NOT NULL,
      source_title TEXT DEFAULT '',
      topic TEXT DEFAULT '',
      language TEXT NOT NULL DEFAULT 'English',
      transcript TEXT DEFAULT '',
      source_notes TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'draft',
      source_signal_id TEXT,
      idea_id TEXT,
      job_id TEXT,
      analysis_json TEXT NOT NULL DEFAULT '{}',
      rewrite_json TEXT NOT NULL DEFAULT '{}',
      originality_json TEXT NOT NULL DEFAULT '{}',
      media_json TEXT NOT NULL DEFAULT '{}',
      provenance_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_revideo_status ON revideo_projects(status, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_revideo_job ON revideo_projects(job_id, updated_at DESC);
    CREATE TABLE IF NOT EXISTS media_jobs(
      id TEXT PRIMARY KEY,
      revideo_project_id TEXT NOT NULL,
      job_id TEXT NOT NULL,
      provider TEXT NOT NULL DEFAULT 'webhook',
      provider_job_id TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'queued',
      media_url TEXT DEFAULT '',
      error TEXT DEFAULT '',
      request_json TEXT NOT NULL DEFAULT '{}',
      response_json TEXT NOT NULL DEFAULT '{}',
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_media_jobs_project ON media_jobs(revideo_project_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_media_jobs_job ON media_jobs(job_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_media_jobs_status ON media_jobs(status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS edit_profiles(
      id TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1,
      name TEXT NOT NULL,
      config_json TEXT NOT NULL DEFAULT '{}',
      active INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL,
      PRIMARY KEY(id,version)
    );
    CREATE TABLE IF NOT EXISTS edit_jobs(
      id TEXT PRIMARY KEY,
      parent_edit_job_id TEXT,
      factory_cycle_id TEXT,
      production_job_id TEXT NOT NULL,
      media_job_id TEXT,
      input_artifact_id TEXT,
      input_url TEXT NOT NULL,
      output_artifact_id TEXT,
      output_url TEXT DEFAULT '',
      profile_id TEXT NOT NULL,
      profile_version INTEGER NOT NULL DEFAULT 1,
      platform TEXT NOT NULL DEFAULT 'reels',
      provider TEXT NOT NULL DEFAULT 'webhook',
      provider_job_id TEXT DEFAULT '',
      status TEXT NOT NULL DEFAULT 'queued',
      rerun_stage TEXT DEFAULT '',
      request_json TEXT NOT NULL DEFAULT '{}',
      response_json TEXT NOT NULL DEFAULT '{}',
      report_json TEXT NOT NULL DEFAULT '{}',
      error TEXT DEFAULT '',
      measured_cost_usd REAL NOT NULL DEFAULT 0,
      measured_duration_sec REAL NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      completed_at TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_edit_jobs_job ON edit_jobs(production_job_id, updated_at DESC);
    CREATE INDEX IF NOT EXISTS idx_edit_jobs_status ON edit_jobs(status, updated_at DESC);
    CREATE TABLE IF NOT EXISTS edit_artifacts(
      id TEXT PRIMARY KEY,
      edit_job_id TEXT NOT NULL,
      kind TEXT NOT NULL,
      content_json TEXT NOT NULL DEFAULT '{}',
      url TEXT DEFAULT '',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_edit_artifacts_job ON edit_artifacts(edit_job_id, created_at);
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
    default_edit_profiles={
      "talking_head_fast":{
        "name":"Talking Head Fast","version":1,
        "config":{
          "target":{"width":1080,"height":1920,"fps":30},
          "speech_cleanup":{"silence_trim":True,"pause_threshold_sec":0.4,"pre_handle_sec":0.1,"post_handle_sec":0.15,"semantic_duplicate_planner":True,"start_on_speech":True},
          "captions":{"enabled":True,"min_words":1,"max_words":3,"burn_in":True,"dark_plate":True,"emphasize_keyword":True,"never_cross_cut":True},
          "motion":{"jump_cut_mask_zoom_min":0.07,"jump_cut_mask_zoom_max":0.10,"push_in_interval_sec":6.0,"opening_motion_deadline_sec":3.0},
          "graphics":{"emphasis_min":3,"emphasis_max":5,"duration_min_sec":1.0,"duration_max_sec":2.0,"approved_text_only":True},
          "audio":{"voice_target_lufs":-14.0,"music_relative_db":-20.0,"music_requires_approved_asset":True},
          "safe_zones":{"top":0.12,"bottom":0.20,"right":0.12,"left":0.0}
        }
      },
      "generated_visual":{
        "name":"Generated Visual","version":1,
        "config":{
          "target":{"width":1080,"height":1920,"fps":30},
          "speech_cleanup":{"silence_trim":False,"semantic_duplicate_planner":False},
          "captions":{"enabled":True,"min_words":1,"max_words":3,"burn_in":True,"never_cross_cut":True},
          "motion":{"opening_motion_deadline_sec":3.0},
          "graphics":{"emphasis_min":1,"emphasis_max":4,"approved_text_only":True},
          "audio":{"voice_target_lufs":-14.0,"music_relative_db":-20.0,"music_requires_approved_asset":True},
          "safe_zones":{"top":0.12,"bottom":0.20,"right":0.12,"left":0.0}
        }
      },
      "revideo_finish":{
        "name":"Revideo Finish","version":1,
        "config":{
          "target":{"width":1080,"height":1920,"fps":30},
          "speech_cleanup":{"silence_trim":True,"pause_threshold_sec":0.4,"pre_handle_sec":0.1,"post_handle_sec":0.15,"semantic_duplicate_planner":True,"start_on_speech":True},
          "captions":{"enabled":True,"min_words":1,"max_words":3,"burn_in":True,"dark_plate":True,"emphasize_keyword":True,"never_cross_cut":True},
          "motion":{"jump_cut_mask_zoom_min":0.07,"jump_cut_mask_zoom_max":0.10,"push_in_interval_sec":6.0,"opening_motion_deadline_sec":3.0},
          "graphics":{"emphasis_min":3,"emphasis_max":5,"duration_min_sec":1.0,"duration_max_sec":2.0,"approved_text_only":True},
          "audio":{"voice_target_lufs":-14.0,"music_relative_db":-20.0,"music_requires_approved_asset":True},
          "safe_zones":{"top":0.12,"bottom":0.20,"right":0.12,"left":0.0},
          "source_policy":{"source_video_is_material_not_instructions":True,"preserve_approved_facts":True}
        }
      }
    }
    for profile_id,p in default_edit_profiles.items():
        con.execute("""INSERT OR IGNORE INTO edit_profiles(id,version,name,config_json,active,created_at)
                       VALUES(?,?,?,?,1,?)""",(profile_id,int(p["version"]),p["name"],json.dumps(p["config"],ensure_ascii=False),ts()))
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

class FactoryCycleCreate(BaseModel):
    signal_ids: list[str] = []
    idea_id: Optional[str] = None
    language: str = "English"
    parent_cycle_id: Optional[str] = None

class FactoryCycleRunRequest(BaseModel):
    confirm_cost: bool = False
    max_ideas: int = 3
    language: str = "English"

class DiscoveryCandidateCreate(BaseModel):
    platform: str = "youtube"
    source_url: str
    external_id: str = ""
    title: str
    creator: str = ""
    thumbnail_url: str = ""
    topic: str = ""
    language: str = ""
    content_type: str = "short"
    published_at: str = ""
    duration_sec: Optional[float] = None
    views: Optional[int] = None
    vph: Optional[float] = None
    engagement_rate: Optional[float] = None
    breakout_score: Optional[float] = None
    transcript: str = ""
    metrics: dict = {}
    provenance: dict = {}

class DiscoveryCollectRequest(BaseModel):
    topic: str = ""
    limit: int = 10
    content_type: str = "short"
    language: str = "en"

class DiscoveryToRevideoRequest(BaseModel):
    language: str = "English"

class RevideoCreateRequest(BaseModel):
    source_url: str
    source_title: str = ""
    topic: str = ""
    transcript: str = ""
    source_notes: str = ""
    language: str = "English"

class RevideoRunRequest(BaseModel):
    confirm_cost: bool = False
    confirm_external_cost: bool = False
    language: str = "English"

class RevideoRenderRequest(BaseModel):
    confirm_external_cost: bool = False

class MediaJobCallbackRequest(BaseModel):
    status: str = "processing"
    url: str = ""
    video_url: str = ""
    output_url: str = ""
    provider_job_id: str = ""
    error: str = ""
    raw: dict = {}

class MediaFinisherStartRequest(BaseModel):
    profile_id: str = "revideo_finish"
    profile_version: int = 1
    platform: str = "reels"
    input_url: str = ""
    media_job_id: str = ""
    edit_full_video: bool = True
    split_shortform: bool = False
    add_captions: bool = True
    add_animation: bool = True
    smart_graphics: bool = True
    max_short_clips: int = 3
    confirm_external_cost: bool = False

class MediaFinisherCallbackRequest(BaseModel):
    status: str = "processing"
    final_url: str = ""
    output_url: str = ""
    provider_job_id: str = ""
    error: str = ""
    report: dict = {}
    artifacts: dict = {}
    measured_cost_usd: float = 0.0
    measured_duration_sec: float = 0.0
    raw: dict = {}

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

def _content_brain_llm(role, system, user, max_output_tokens=900, model=None):
    if not FACTORY_LLM_API_KEY:
        raise RuntimeError("Live LLM provider is not configured")
    model=(model or FACTORY_LLM_MODEL).strip()
    limit=max(128,min(2400,int(max_output_tokens)))
    if FACTORY_LLM_API_MODE=="chat_completions":
        payload={
            "model":model,
            "max_completion_tokens":limit,
            "messages":[{"role":"system","content":system},{"role":"user","content":user}],
        }
    else:
        payload={
            "model":model,"max_output_tokens":limit,
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
    return {"content":content,"model":result.get("model") or model,
            "input_tokens":input_tokens,"output_tokens":output_tokens,"cost_usd":cost_usd,
            "provider_request_id":result.get("id")}

def _content_brain_budget_guard(output_tokens=900):
    _real_pilot_budget_guard(output_tokens)
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
    model=_workflow_model(None)
    system=_apply_workflow_prompt(agent,system,None)
    run_id=start_agent_run(agent,None,"content_brain",model=model)
    try:
        result=await asyncio.wait_for(
            asyncio.to_thread(_content_brain_llm,agent,system,user,max_output_tokens,model),
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
                try:
                    cycle=create_factory_cycle(FactoryCycleCreate(
                        signal_ids=[x["id"] for x in result["created"]],language="English"
                    ),source="rss_collector")
                    cycle_event(cycle["id"],"signals",f"RSS collector attached {result['created_count']} new signal(s) to an autonomous cycle")
                except Exception as exc:
                    print(json.dumps({"event":"FACTORY_CYCLE_CREATE_ERROR","error":str(exc)[:300]}),flush=True)
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
    if isinstance(content,str):
        stored_content=content
    elif content is None:
        stored_content=""
    else:
        stored_content=json.dumps(content,ensure_ascii=False,indent=2,default=str)
    con=db()
    con.execute("""INSERT INTO artifacts(id,run_id,job_id,agent,kind,title,content,url,mime_type,created_at,meta_json)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (artifact_id,run_id,job_id,agent,kind,str(title or ""),stored_content,url,mime_type,ts(),json.dumps(meta or {},ensure_ascii=False,default=str)))
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
        "Content Packager":("json","Content package manifest"),
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
    workflow=_workflow_context(job.get("id"),lock=True)
    model=_workflow_model(job.get("id"))
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
    system=_apply_workflow_prompt(agent,system,job.get("id"))
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
            "model":model,
            "max_completion_tokens":FACTORY_LLM_MAX_OUTPUT_TOKENS,
            "messages":[
                {"role":"system","content":system},
                {"role":"user","content":user},
            ],
        }
    else:
        payload={
            "model":model,
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
        "model":result.get("model") or model,
        "input_tokens":input_tokens,"output_tokens":output_tokens,
        "cost_usd":cost_usd,
        "provider_request_id":result.get("id"),
        "workflow_version_id":workflow["version"]["id"],
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
    checked_at=report.get("checked_at") or ts()
    for text in report.get("improvements",[]):
        suggestions.append({
            "title": text[:110],
            "rationale": text,
            "finding": None,
            "evidence": [{"type":"supervisor_report","checked_at":checked_at,"text":text}],
        })
    for finding in report.get("findings",[]):
        rec=finding.get("recommendation")
        if rec:
            suggestions.append({
                "title": f"Resolve: {finding.get('title','Factory issue')}"[:110],
                "rationale": rec,
                "finding": finding,
                "evidence": [{
                    "type":"supervisor_finding","checked_at":checked_at,
                    "code":finding.get("code"),"severity":finding.get("severity"),
                    "detail":finding.get("detail"),
                }],
            })
    con=db()
    for item in suggestions[:12]:
        action=build_improvement_action(
            item["title"],item["rationale"],item.get("evidence") or [],
            suggested_workflow_patch(item.get("finding"),item["title"],item["rationale"])
        )
        fingerprint=hashlib.sha256((item["title"]+"|"+item["rationale"]).encode("utf-8")).hexdigest()
        now=ts()
        con.execute("""INSERT OR IGNORE INTO improvement_proposals
                       (id,fingerprint,created_at,updated_at,title,rationale,status,source,action_json)
                       VALUES(?,?,?,?,?,?,?,?,?)""",
                    (str(uuid.uuid4()),fingerprint,now,now,item["title"],item["rationale"],"proposed","Supervisor",json.dumps(action,ensure_ascii=False)))
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
        d["hypothesis"]=d["action"].get("hypothesis") or ""
        d["change"]=d["action"].get("change") or {}
        d["evidence"]=d["action"].get("evidence") or []
        d["requires_experiment"]=bool(d["action"].get("requires_experiment",True))
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
    _real_pilot_budget_guard(output_tokens)
    reserve=max(128,int(output_tokens))*FACTORY_LLM_OUTPUT_USD_PER_1M/1_000_000
    usage=get_usage_summary()
    if usage["today_cost_usd"] + reserve > FACTORY_DAILY_BUDGET_USD:raise RuntimeError("Daily provider budget would be exceeded by the next variant call")
    if get_job_cost(job_id) + reserve > FACTORY_JOB_BUDGET_USD:raise RuntimeError("Job provider budget would be exceeded by the next variant call")

async def _variant_agent_call(agent,job_id,label,system,user,max_output_tokens=1100):
    _variant_budget_guard(job_id,max_output_tokens)
    workflow=_workflow_context(job_id,lock=True)
    model=_workflow_model(job_id)
    system=_apply_workflow_prompt(agent,system,job_id)
    run_id=start_agent_run(agent,job_id,"script",model=model)
    set_agent_progress(agent,8,label,job_id,run_id,"working");event(job_id,f"{agent}: {label}")
    await broadcast({"type":"agent","agent":agent,"state":"working"})
    try:
        result=await asyncio.wait_for(asyncio.to_thread(_content_brain_llm,agent,system,user,max_output_tokens,model),timeout=AGENT_TIMEOUT_SECONDS)
        parsed=_parse_json_object(result["content"])
        save_artifact(agent,"analysis",label,result["content"],job_id=job_id,run_id=run_id,meta={"mode":"live_llm","stage":"script","variant_batch":True,"model":result["model"],"provider_request_id":result.get("provider_request_id"),"workflow_version_id":workflow["version"]["id"]})
        finish_agent_run(run_id,status="completed",input_tokens=result["input_tokens"],output_tokens=result["output_tokens"],cost_usd=result["cost_usd"],meta={"mode":"live_llm","variant_batch":True,"workflow_version_id":workflow["version"]["id"]})
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
    workflow=_workflow_context(job_id,lock=True)
    batch_id=str(uuid.uuid4());now=ts()
    templates=[("Explain the hidden mechanism first","You think this is a black box — here is what is actually happening."),("Lead with the surprising limitation","The most interesting part is what this system cannot know."),("Start from a concrete experiment","I tested the claim on one concrete example. Here is what survived verification.")]
    con=db();variants=[]
    for n in range(candidate_count):
        variant_id=str(uuid.uuid4());angle,hook=templates[n%len(templates)]
        script=f"{hook}\n\nContext: {job['title']}.\nDemo variant {n+1}: explain one concrete mechanism, show the evidence boundary, state limitations, then end with a clear CTA."
        fact={"findings":[{"type":"missing_source","severity":"warning","message":"Demo mode has no live external source verification.","evidence":"simulation-v3"}]}
        qa={"decision":"keep" if n==0 else "reject","findings":[{"type":"missing_source","severity":"warning","message":"Demo variant only; live source verification is required.","evidence":"simulation-v3"}]}
        status="selected" if n==0 else "rejected";reason="Demo selection only — no live performance or source evidence." if n==0 else "Demo alternate retained for comparison.";provenance={"mode":"demo","batch_id":batch_id,"workflow_version_id":workflow["version"]["id"]}
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

async def run_variant_pipeline(job_id,candidate_count=None):
    workflow=_workflow_context(job_id,lock=True)
    candidate_count=_workflow_candidate_count(job_id,candidate_count)
    if not FACTORY_LLM_API_KEY:return _demo_variant_pipeline(job_id,candidate_count)
    job=get_job(job_id)
    if not job:raise ValueError("Job not found")
    batch_id=str(uuid.uuid4());research=_variant_research_context(job_id);language=job.get("language","English")
    angle_obj,angle_run,_=await _variant_agent_call("Angle Strategist",job_id,"Generating competing angles","You are Angle Strategist in FactoryOS Production Pipeline 2.0. Create genuinely distinct evidence-grounded narrative angles. Use only supplied research. Return JSON only: {\"angles\":[{\"angle\":\"...\",\"reason\":\"...\",\"audience\":\"...\"}]}. Return exactly "+str(candidate_count)+" angles. Do not invent facts.",f"JOB: {job['title']}\nBRIEF: {job.get('brief','')}\nLANGUAGE: {language}\nRESEARCH:\n{research}",1000)
    angles=[x for x in (angle_obj.get("angles") or []) if isinstance(x,dict) and str(x.get("angle") or "").strip()][:candidate_count]
    if len(angles)<candidate_count:raise RuntimeError(f"Angle Strategist returned {len(angles)} usable angles; expected {candidate_count}")
    con=db();now=ts();variants=[]
    for n,a in enumerate(angles,1):
        vid=str(uuid.uuid4());provenance={"batch_id":batch_id,"run_ids":{"angle":angle_run},"workflow_version_id":workflow["version"]["id"]}
        con.execute("INSERT INTO production_variants(id,batch_id,job_id,ordinal,status,angle,angle_reason,provenance_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(vid,batch_id,job_id,n,"candidate",str(a.get("angle") or "").strip(),str(a.get("reason") or "").strip(),json.dumps(provenance),now,now))
        con.commit()
        variants.append({"id":vid,"ordinal":n,"angle":str(a.get("angle") or "").strip(),"angle_reason":str(a.get("reason") or "").strip()});_save_variant_piece("Angle Strategist",job_id,angle_run,batch_id,vid,"angle",f"Variant {n} · angle",json.dumps(a,ensure_ascii=False,indent=2))
    con.commit();con.close()
    hook_obj,hook_run,_=await _variant_agent_call("Hook Generator",job_id,"Generating hook candidates","You are Hook Generator. Create one specific 1–3 second opening hook for each supplied variant. Hooks must differ in mechanism, not just wording, and must not add unsupported claims. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"hook\":\"...\",\"rationale\":\"...\"}]}.",f"LANGUAGE: {language}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps(variants,ensure_ascii=False)}",1000)
    hooks={str(x.get("variant_id")):x for x in hook_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        h=hooks.get(v["id"]) or {};v["hook"]=str(h.get("hook") or "").strip();v["hook_rationale"]=str(h.get("rationale") or "").strip()
        if not v["hook"]:raise RuntimeError(f"Hook Generator missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["hook"]=hook_run
        con.execute("UPDATE production_variants SET hook=?,hook_rationale=?,provenance_json=?,updated_at=? WHERE id=?",(v["hook"],v["hook_rationale"],json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("Hook Generator",job_id,hook_run,batch_id,v["id"],"hook",f"Variant {v['ordinal']} · hook",json.dumps(h,ensure_ascii=False,indent=2))
    con.commit();con.close()
    script_obj,script_run,_=await _variant_agent_call("Scriptwriter",job_id,"Writing script variants","You are Scriptwriter. Write a distinct concise production script for each supplied variant, keeping its angle and hook. Use only supplied research. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"script\":\"...\"}]}. Each script must contain a concrete payoff and CTA, and explicitly qualify uncertainty.",f"LANGUAGE: {language}\nFORMAT: {job.get('format','')}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps(variants,ensure_ascii=False)}",1200)
    scripts={str(x.get("variant_id")):x for x in script_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=scripts.get(v["id"]) or {};v["script"]=str(x.get("script") or "").strip()
        if not v["script"]:raise RuntimeError(f"Scriptwriter missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["script"]=script_run
        con.execute("UPDATE production_variants SET script=?,provenance_json=?,updated_at=? WHERE id=?",(v["script"],json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("Scriptwriter",job_id,script_run,batch_id,v["id"],"script",f"Variant {v['ordinal']} · script",v["script"])
    con.commit();con.close()
    fact_obj,fact_run,_=await _variant_agent_call("Fact Checker",job_id,"Fact-checking variants","You are Fact Checker. Inspect each script against supplied persisted research only. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"findings\":[{\"type\":\"unsupported_claim|missing_source|fact_conflict\",\"severity\":\"info|warning|critical\",\"message\":\"...\",\"evidence\":\"...\"}],\"fact_summary\":\"...\"}]}. Never claim external verification that is not present in research.",f"RESEARCH:\n{research}\nSCRIPTS:\n{json.dumps([{k:v.get(k) for k in ('id','script')} for v in variants],ensure_ascii=False)}",1100)
    facts={str(x.get("variant_id")):x for x in fact_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=facts.get(v["id"]) or {};x["findings"]=_normalize_qa_findings(x.get("findings") or []);v["fact_check"]=x
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["factcheck"]=fact_run
        con.execute("UPDATE production_variants SET fact_check_json=?,provenance_json=?,updated_at=? WHERE id=?",(json.dumps(x,ensure_ascii=False),json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("Fact Checker",job_id,fact_run,batch_id,v["id"],"factcheck",f"Variant {v['ordinal']} · fact check",json.dumps(x,ensure_ascii=False,indent=2))
    con.commit();con.close()
    opt_obj,opt_run,_=await _variant_agent_call("Hook Optimizer",job_id,"Optimizing hooks","You are Hook Optimizer. Improve each hook after reading fact-check findings. Preserve evidence boundaries; do not introduce new claims. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"optimized_hook\":\"...\",\"change_reason\":\"...\"}]}.",f"LANGUAGE: {language}\nVARIANTS:\n{json.dumps([{**{k:v.get(k) for k in ('id','hook')},'fact_check':v.get('fact_check')} for v in variants],ensure_ascii=False)}",850)
    opts={str(x.get("variant_id")):x for x in opt_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=opts.get(v["id"]) or {};v["optimized_hook"]=str(x.get("optimized_hook") or v.get("hook") or "").strip();prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["optimize"]=opt_run
        con.execute("UPDATE production_variants SET optimized_hook=?,provenance_json=?,updated_at=? WHERE id=?",(v["optimized_hook"],json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("Hook Optimizer",job_id,opt_run,batch_id,v["id"],"optimize",f"Variant {v['ordinal']} · optimized hook",json.dumps(x,ensure_ascii=False,indent=2))
    con.commit();con.close()
    edit_obj,edit_run,_=await _variant_agent_call("Editor",job_id,"Editing production variants","You are Editor. Produce final edited script for each variant using its optimized hook and fact-check findings. Remove or qualify unsupported claims. Keep variants meaningfully distinct. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"edited_script\":\"...\",\"edit_notes\":\"...\"}]}.",f"LANGUAGE: {language}\nVARIANTS:\n{json.dumps([{k:v.get(k) for k in ('id','angle','optimized_hook','script','fact_check')} for v in variants],ensure_ascii=False)}",1200)
    edits={str(x.get("variant_id")):x for x in edit_obj.get("variants") or [] if isinstance(x,dict)};con=db()
    for v in variants:
        x=edits.get(v["id"]) or {};v["edited_script"]=str(x.get("edited_script") or "").strip()
        if not v["edited_script"]:raise RuntimeError(f"Editor missed variant {v['ordinal']}")
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["editor"]=edit_run
        con.execute("UPDATE production_variants SET edited_script=?,provenance_json=?,updated_at=? WHERE id=?",(v["edited_script"],json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("Editor",job_id,edit_run,batch_id,v["id"],"editor",f"Variant {v['ordinal']} · edited script",v["edited_script"])
    con.commit();con.close()
    qa_obj,qa_run,_=await _variant_agent_call("QA Agent",job_id,"Comparing variants with structured QA","You are QA Agent comparing competing content variants before downstream production. Return JSON only: {\"variants\":[{\"variant_id\":\"...\",\"decision\":\"keep|reject\",\"reason\":\"...\",\"findings\":[{\"type\":\"unsupported_claim|weak_hook|duplicated_angle|missing_source|slow_intro|unclear_cta|excessive_length|unsafe_sensitive_claim|fact_conflict\",\"severity\":\"info|warning|critical\",\"message\":\"...\",\"evidence\":\"...\"}]}],\"recommended_variant_id\":\"...\"}. Do not use a made-up quality score. Recommend based on concrete findings only.",f"LANGUAGE: {language}\nRESEARCH:\n{research}\nVARIANTS:\n{json.dumps([{k:v.get(k) for k in ('id','angle','optimized_hook','edited_script','fact_check')} for v in variants],ensure_ascii=False)}",1200)
    qa_map={str(x.get("variant_id")):x for x in qa_obj.get("variants") or [] if isinstance(x,dict)};con=db();hydrated=[]
    for v in variants:
        q=qa_map.get(v["id"]) or {"decision":"keep","reason":"QA returned no variant-specific decision","findings":[]};q["findings"]=_normalize_qa_findings(q.get("findings") or []);v["qa"]=q
        prov=_decode_json(con.execute("SELECT provenance_json p FROM production_variants WHERE id=?",(v["id"],)).fetchone()["p"],{});prov.setdefault("run_ids",{})["qa"]=qa_run
        con.execute("UPDATE production_variants SET qa_json=?,provenance_json=?,updated_at=? WHERE id=?",(json.dumps(q,ensure_ascii=False),json.dumps(prov),ts(),v["id"]));con.commit();_save_variant_piece("QA Agent",job_id,qa_run,batch_id,v["id"],"qa",f"Variant {v['ordinal']} · structured QA",json.dumps(q,ensure_ascii=False,indent=2));hydrated.append({**v,"provenance":prov})
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
    cols=",".join(f"{k}=?" for k in updates);con=db();con.execute(f"UPDATE production_variants SET {cols} WHERE id=?",(*updates.values(),variant_id))
    con.execute("UPDATE jobs SET stage='script',status='idle',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("script")/(len(STAGES)-1)*100),now,job_id))
    con.commit();con.close();_mark_content_package_stale(job_id,f"Variant {variant['ordinal']} changed via partial rerun: {component}.");_save_variant_piece(agent,job_id,run_id,variant["batch_id"],variant_id,component,f"Variant {variant['ordinal']} · partial {component}",json.dumps(obj,ensure_ascii=False,indent=2),{"partial_rerun":True});event(job_id,f"Variant {variant['ordinal']}: partial rerun {component}; downstream stages invalidated from script");await broadcast({"type":"variants","jobId":job_id,"variantId":variant_id,"component":component});return get_job_variants(job_id)

def select_production_variant(job_id,variant_id):
    con=db();row=con.execute("SELECT * FROM production_variants WHERE id=? AND job_id=?",(variant_id,job_id)).fetchone()
    if not row:con.close();raise ValueError("Variant not found")
    chosen=_variant_dict(row)
    if not chosen.get("edited_script"):con.close();raise ValueError("Variant must be edited before selection")
    if not chosen.get("fact_check") or not chosen.get("qa"):con.close();raise ValueError("Variant must complete fact-check and structured QA before selection")
    con.execute("UPDATE production_variants SET status='rejected',decision_reason=CASE WHEN id=? THEN decision_reason ELSE 'Not selected in variant comparison.' END,updated_at=? WHERE job_id=? AND batch_id=?",(variant_id,ts(),job_id,chosen["batch_id"]));con.execute("UPDATE production_variants SET status='selected',decision_reason='Selected in Variant Studio.',updated_at=? WHERE id=?",(ts(),variant_id));con.commit();con.close()
    _save_variant_piece("Editor",job_id,None,chosen["batch_id"],variant_id,"selected","Selected production variant",(chosen.get("optimized_hook") or chosen.get("hook") or "")+"\n\n"+chosen.get("edited_script",""),{"selected":True,"manual_selection":True})
    _save_variant_piece("Fact Checker",job_id,None,chosen["batch_id"],variant_id,"selected_factcheck","Selected variant fact check",json.dumps(chosen.get("fact_check") or {},ensure_ascii=False,indent=2),{"selected":True,"manual_selection":True})
    _mark_content_package_stale(job_id,f"Selected production variant changed to variant {chosen['ordinal']}.")
    con=db();con.execute("UPDATE jobs SET stage='script',status='idle',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("script")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close()
    event(job_id,f"Variant {chosen['ordinal']} selected in Variant Studio; Content Package and downstream media require rebuild");return get_job_variants(job_id)


# v4.4 — Viral Discovery / outlier intake.
# Discovery persists factual public metrics supplied by a connector/webhook; FactoryOS does not invent performance.
def _discovery_dict(row):
    if not row:return None
    d=dict(row)
    d["metrics"]=_decode_json(d.pop("metrics_json","{}"),{})
    d["provenance"]=_decode_json(d.pop("provenance_json","{}"),{})
    return d

def _discovery_fingerprint(platform,source_url,external_id=""):
    raw=f"{(platform or 'unknown').strip().lower()}|{(external_id or '').strip()}|{(source_url or '').strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ingest_discovery_candidate(payload, source="manual"):
    source_url=(payload.source_url or "").strip()
    if not _valid_public_url(source_url):raise ValueError("A valid http/https source URL is required")
    title=" ".join(str(payload.title or "").split()).strip()
    if not title:raise ValueError("Discovery candidate title is required")
    platform=(payload.platform or "unknown").strip().lower()[:40]
    external_id=(payload.external_id or "").strip()[:240]
    fp=_discovery_fingerprint(platform,source_url,external_id)
    now=ts()
    metrics=dict(payload.metrics or {})
    for key,value in {
        "views":payload.views,"vph":payload.vph,"engagement_rate":payload.engagement_rate,
        "breakout_score":payload.breakout_score,"duration_sec":payload.duration_sec,
    }.items():
        if value is not None:metrics[key]=value
    provenance=dict(payload.provenance or {})
    provenance.setdefault("source",source);provenance.setdefault("ingested_at",now)
    con=db();existing=con.execute("SELECT * FROM discovery_candidates WHERE fingerprint=?",(fp,)).fetchone()
    if existing:
        cid=existing["id"]
        con.execute("""UPDATE discovery_candidates SET title=?,creator=?,thumbnail_url=?,topic=?,language=?,content_type=?,
                       published_at=?,duration_sec=?,views=?,vph=?,engagement_rate=?,breakout_score=?,transcript=?,
                       metrics_json=?,provenance_json=?,updated_at=? WHERE id=?""",(
            title,(payload.creator or "")[:300],(payload.thumbnail_url or "")[:2000],(payload.topic or "")[:300],
            (payload.language or "")[:40],(payload.content_type or "")[:40],(payload.published_at or "")[:80],
            payload.duration_sec,payload.views,payload.vph,payload.engagement_rate,payload.breakout_score,
            (payload.transcript or "")[:30000],json.dumps(metrics,ensure_ascii=False),json.dumps(provenance,ensure_ascii=False),now,cid
        ))
        created=False
    else:
        cid=str(uuid.uuid4())
        con.execute("""INSERT INTO discovery_candidates(
          id,fingerprint,platform,source_url,external_id,title,creator,thumbnail_url,topic,language,content_type,published_at,
          duration_sec,views,vph,engagement_rate,breakout_score,transcript,status,revideo_project_id,discovered_at,updated_at,metrics_json,provenance_json
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'new',NULL,?,?,?,?)""",(
          cid,fp,platform,source_url,external_id,title,(payload.creator or "")[:300],(payload.thumbnail_url or "")[:2000],
          (payload.topic or "")[:300],(payload.language or "")[:40],(payload.content_type or "")[:40],(payload.published_at or "")[:80],
          payload.duration_sec,payload.views,payload.vph,payload.engagement_rate,payload.breakout_score,(payload.transcript or "")[:30000],
          now,now,json.dumps(metrics,ensure_ascii=False),json.dumps(provenance,ensure_ascii=False)
        ))
        created=True
    con.commit();row=con.execute("SELECT * FROM discovery_candidates WHERE id=?",(cid,)).fetchone();con.close()
    return {"created":created,"candidate":_discovery_dict(row)}

def get_discovery_candidate(candidate_id):
    con=db();row=con.execute("SELECT * FROM discovery_candidates WHERE id=?",(candidate_id,)).fetchone();con.close()
    return _discovery_dict(row)

def get_discovery_candidates(limit=80,status=None):
    con=db()
    if status:
        rows=con.execute("""SELECT * FROM discovery_candidates WHERE status=?
                            ORDER BY COALESCE(breakout_score,-1) DESC,COALESCE(vph,-1) DESC,discovered_at DESC LIMIT ?""",
                         (status,max(1,min(300,int(limit))))).fetchall()
    else:
        rows=con.execute("""SELECT * FROM discovery_candidates
                            ORDER BY CASE WHEN status='new' THEN 0 ELSE 1 END,
                                     COALESCE(breakout_score,-1) DESC,COALESCE(vph,-1) DESC,discovered_at DESC LIMIT ?""",
                         (max(1,min(300,int(limit))),)).fetchall()
    con.close();items=[_discovery_dict(x) for x in rows];counts={}
    for x in items:counts[x["status"]]=counts.get(x["status"],0)+1
    return {
      "summary":{"candidates":len(items),**counts},"candidates":items,
      "adapter":{"configured":bool(FACTORY_DISCOVERY_ENDPOINT),"mode":"webhook" if FACTORY_DISCOVERY_ENDPOINT else "manual_intake",
                 "topics":FACTORY_DISCOVERY_TOPICS,"interval_minutes":FACTORY_DISCOVERY_INTERVAL_MINUTES},
      "measurement_note":"views, VPH, engagement and breakout score are stored only when supplied by the discovery source; FactoryOS does not synthesize them."
    }

def _normalize_discovery_webhook_item(item,topic=""):
    if not isinstance(item,dict):raise ValueError("Discovery webhook item must be an object")
    url=str(item.get("source_url") or item.get("url") or item.get("video_url") or "").strip()
    title=str(item.get("title") or item.get("videoTitle") or "").strip()
    if not url or not title:raise ValueError("Discovery webhook item needs source_url/url and title")
    return DiscoveryCandidateCreate(
      platform=str(item.get("platform") or "youtube"),
      source_url=url,external_id=str(item.get("external_id") or item.get("videoId") or ""),
      title=title,creator=str(item.get("creator") or item.get("channelTitle") or ""),
      thumbnail_url=str(item.get("thumbnail_url") or item.get("videoThumbnail") or ""),
      topic=str(item.get("topic") or topic or ""),
      language=str(item.get("language") or item.get("videoTitleLanguage") or ""),
      content_type=str(item.get("content_type") or item.get("videoType") or "short"),
      published_at=str(item.get("published_at") or item.get("videoPublishedAt") or ""),
      duration_sec=item.get("duration_sec",item.get("videoDuration")),
      views=item.get("views",item.get("viewCount")),vph=item.get("vph"),
      engagement_rate=item.get("engagement_rate",item.get("engagementRate")),
      breakout_score=item.get("breakout_score",item.get("breakoutScore")),
      transcript=str(item.get("transcript") or ""),
      metrics={k:v for k,v in item.items() if k in ("viewCount","likeCount","commentCount","score","subscriberCount","hasAiLabel")},
      provenance={"provider_payload_keys":sorted(item.keys())[:80]}
    )

def collect_discovery_candidates(topic="",limit=10,content_type="short",language="en"):
    if not FACTORY_DISCOVERY_ENDPOINT:
        return {"created_count":0,"updated_count":0,"candidates":[],"adapter":"manual_intake",
                "message":"Discovery webhook is not configured; use manual intake or an external connector such as vidIQ."}
    payload={"topic":topic,"limit":max(1,min(50,int(limit))),"content_type":content_type,"language":language}
    result=_external_json(FACTORY_DISCOVERY_ENDPOINT,"POST",payload,FACTORY_DISCOVERY_TOKEN)
    raw=result.get("candidates") or result.get("videos") or result.get("items") or []
    if not isinstance(raw,list):raise RuntimeError("Discovery provider response must include candidates/videos/items array")
    created=updated=0;items=[]
    for item in raw[:payload["limit"]]:
        try:
            normalized=_normalize_discovery_webhook_item(item,topic)
            out=ingest_discovery_candidate(normalized,source="discovery_webhook")
            created+=1 if out["created"] else 0;updated+=0 if out["created"] else 1;items.append(out["candidate"])
        except Exception as exc:
            event(None,f"Discovery item skipped: {str(exc)[:180]}")
    return {"created_count":created,"updated_count":updated,"candidates":items,"adapter":"webhook"}

def discovery_candidate_to_revideo(candidate_id,language="English"):
    candidate=get_discovery_candidate(candidate_id)
    if not candidate:raise ValueError("Discovery candidate not found")
    if candidate.get("revideo_project_id"):
        project=get_revideo_project(candidate["revideo_project_id"])
        if project:return {"created":False,"project":project,"candidate":candidate}
    notes="Public performance evidence supplied by discovery source. "
    facts=[]
    if candidate.get("views") is not None:facts.append(f"views={candidate['views']}")
    if candidate.get("vph") is not None:facts.append(f"vph={candidate['vph']}")
    if candidate.get("engagement_rate") is not None:facts.append(f"engagement_rate={candidate['engagement_rate']}")
    if candidate.get("breakout_score") is not None:facts.append(f"breakout_score={candidate['breakout_score']}")
    notes+=(", ".join(facts) if facts else "No performance metrics supplied.")+" Analyze structure only; do not copy source wording, identity, voice or footage."
    project=create_revideo_project(RevideoCreateRequest(
      source_url=candidate["source_url"],source_title=candidate["title"],topic=candidate.get("topic") or "",
      transcript=candidate.get("transcript") or "",source_notes=notes,language=language
    ))
    provenance=dict(project.get("provenance") or {})
    provenance["discovery_candidate_id"]=candidate_id
    provenance["discovery_metrics"]={k:candidate.get(k) for k in ("views","vph","engagement_rate","breakout_score") if candidate.get(k) is not None}
    con=db();con.execute("UPDATE revideo_projects SET provenance_json=?,updated_at=? WHERE id=?",
                         (json.dumps(provenance,ensure_ascii=False),ts(),project["id"]))
    con.execute("UPDATE discovery_candidates SET status='sent_to_revideo',revideo_project_id=?,updated_at=? WHERE id=?",
                (project["id"],ts(),candidate_id));con.commit();con.close()
    return {"created":True,"project":get_revideo_project(project["id"]),"candidate":get_discovery_candidate(candidate_id)}

def import_discovery_seed():
    if not FACTORY_DISCOVERY_SEED_JSON:return {"imported":0,"projects":0}
    try:data=json.loads(FACTORY_DISCOVERY_SEED_JSON)
    except Exception as exc:
        print(json.dumps({"event":"DISCOVERY_SEED","status":"invalid_json","error":str(exc)[:300]}),flush=True);return {"imported":0,"projects":0}
    if isinstance(data,dict):data=[data]
    imported=projects=0
    for item in (data or [])[:20]:
        try:
            payload=_normalize_discovery_webhook_item(item,item.get("topic","") if isinstance(item,dict) else "")
            out=ingest_discovery_candidate(payload,source="startup_seed")
            if out["created"]:imported+=1
            if FACTORY_DISCOVERY_SEED_AUTO_REVIDEO:
                rev=discovery_candidate_to_revideo(out["candidate"]["id"],"English")
                if rev.get("created"):projects+=1
        except Exception as exc:
            print(json.dumps({"event":"DISCOVERY_SEED","status":"item_error","error":str(exc)[:300]}),flush=True)
    print(json.dumps({"event":"DISCOVERY_SEED","status":"done","imported":imported,"revideo_projects":projects}),flush=True)
    return {"imported":imported,"projects":projects}

async def discovery_collector_loop():
    while True:
        for topic in FACTORY_DISCOVERY_TOPICS:
            try:
                result=await asyncio.to_thread(collect_discovery_candidates,topic,10,"short","en")
                if result.get("created_count"):
                    event(None,f"Viral Discovery collected {result['created_count']} new candidate(s) for {topic}")
                    await broadcast({"type":"discovery","action":"collected","topic":topic,"count":result["created_count"]})
            except Exception as exc:
                print(json.dumps({"event":"DISCOVERY_COLLECT_ERROR","topic":topic,"error":str(exc)[:500]}),flush=True)
        await asyncio.sleep(FACTORY_DISCOVERY_INTERVAL_MINUTES*60)

# v4.3 — Revideo MVP / original rewrite pipeline.
# The source is used for analysis and provenance; FactoryOS does not default to downloading/reposting source media.
REVIDEO_REQUIRED_REWRITE_FIELDS=("new_angle","hook_candidates","original_script","originality_note","media_brief","fact_check_notes")

def _revideo_dict(row):
    if not row:return None
    d=dict(row)
    for field,out in (("analysis_json","analysis"),("rewrite_json","rewrite"),("originality_json","originality"),
                      ("media_json","media"),("provenance_json","provenance")):
        d[out]=_decode_json(d.pop(field,"{}"),{})
    return d

def _attach_latest_media_job(project):
    if not project:return project
    con=db();row=con.execute("SELECT * FROM media_jobs WHERE revideo_project_id=? ORDER BY updated_at DESC LIMIT 1",
                             (project["id"],)).fetchone();con.close()
    project["media_job"]=_media_job_dict(row) if row else None
    return project

def get_revideo_project(project_id):
    con=db();row=con.execute("SELECT * FROM revideo_projects WHERE id=?",(project_id,)).fetchone();con.close()
    return _attach_latest_media_job(_revideo_dict(row))

def get_revideo_projects(limit=80):
    con=db();rows=con.execute("SELECT * FROM revideo_projects ORDER BY updated_at DESC LIMIT ?",
                              (max(1,min(200,int(limit))),)).fetchall();con.close()
    items=[_attach_latest_media_job(_revideo_dict(x)) for x in rows];counts={}
    for x in items:counts[x["status"]]=counts.get(x["status"],0)+1
    return {
        "summary":{"projects":len(items),**counts},"projects":items,
        "transcript_adapter":{"selected":FACTORY_TRANSCRIPT_ADAPTER,"configured":bool(FACTORY_TRANSCRIPT_ENDPOINT),
                              "mode":"manual" if not FACTORY_TRANSCRIPT_ENDPOINT else "webhook"},
        "video_adapter":{"selected":FACTORY_MEDIA_ADAPTERS.get("video") or None,
                         "configured":bool(FACTORY_VIDEO_ENDPOINT),"mode":"async_webhook" if FACTORY_VIDEO_ENDPOINT else "not_configured",
                         "status_endpoint_configured":bool(FACTORY_VIDEO_STATUS_ENDPOINT)},
        "safety_note":"Revideo extracts reusable structure and creates an original rewrite. Source media is not copied/re-uploaded by default; human approval remains mandatory."
    }

def _valid_public_url(value):
    try:
        p=urlparse.urlparse(value)
        return p.scheme in ("http","https") and bool(p.netloc)
    except Exception:return False

def create_revideo_project(payload):
    source_url=(payload.source_url or "").strip()
    if not _valid_public_url(source_url):raise ValueError("A valid http/https source URL is required")
    title=" ".join((payload.source_title or "").split()).strip()[:400]
    topic=" ".join((payload.topic or "").split()).strip()[:250]
    transcript=(payload.transcript or "").strip()
    notes=(payload.source_notes or "").strip()
    language=(payload.language or "English").strip() or "English"
    pid=str(uuid.uuid4());now=ts()
    provenance={"created_by":"owner","source_url":source_url,"copyright_mode":"original_rewrite_only",
                "voice_identity_imitation":False,"auto_publish":False}
    con=db();con.execute("""INSERT INTO revideo_projects(
        id,source_url,source_title,topic,language,transcript,source_notes,status,
        analysis_json,rewrite_json,originality_json,media_json,provenance_json,created_at,updated_at
    ) VALUES(?,?,?,?,?,?,?,'draft','{}','{}','{}','{}',?,?,?)""",
    (pid,source_url,title,topic,language,transcript,notes,json.dumps(provenance,ensure_ascii=False),now,now))
    con.commit();con.close()
    return get_revideo_project(pid)

def _fetch_revideo_transcript(project):
    if project.get("transcript"):return project["transcript"]
    if not FACTORY_TRANSCRIPT_ENDPOINT:
        raise RuntimeError("No transcript was supplied and no transcript webhook provider is configured")
    result=_external_json(FACTORY_TRANSCRIPT_ENDPOINT,"POST",
                          {"source_url":project["source_url"],"project_id":project["id"]},FACTORY_TRANSCRIPT_TOKEN)
    transcript=str(result.get("transcript") or result.get("text") or result.get("content") or "").strip()
    if not transcript:raise RuntimeError("Transcript provider returned no transcript text")
    con=db();con.execute("UPDATE revideo_projects SET transcript=?,updated_at=? WHERE id=?",(transcript,ts(),project["id"]));con.commit();con.close()
    return transcript

def _revideo_quote(project):
    # Two bounded LLM calls. Provider calls remain additionally protected by FactoryOS daily/job budget guards.
    if not FACTORY_LLM_API_KEY:return {"estimated_max_usd":0.0,"paid_calls_possible":False,"calls":0}
    calls=2
    per=(6500*FACTORY_LLM_INPUT_USD_PER_1M + 1200*FACTORY_LLM_OUTPUT_USD_PER_1M)/1_000_000
    return {"estimated_max_usd":round(calls*per,6),"paid_calls_possible":True,"calls":calls,
            "note":"Conservative estimate for Structure Analyzer + Rewrite Strategist; actual usage is recorded per run."}

def _word_shingles(text,n=5):
    words=[re.sub(r"[^\w'-]","",x.lower()) for x in re.findall(r"\S+",text or "")]
    words=[x for x in words if x]
    return {" ".join(words[i:i+n]) for i in range(max(0,len(words)-n+1))}

def _originality_check(source,new_script):
    a=_word_shingles(source,5);b=_word_shingles(new_script,5)
    shared=a & b
    overlap=(len(shared)/max(1,len(b))) if b else 0.0
    return {
        "five_word_shingle_overlap":round(overlap,4),
        "shared_phrase_count":len(shared),
        "passed":overlap<0.20,
        "threshold":0.20,
        "note":"This is a mechanical phrase-overlap guard, not a legal copyright determination."
    }

def _demo_revideo(project,transcript):
    analysis={
        "source_summary":(project.get("source_notes") or transcript[:600] or project.get("source_title") or "Source video")[:900],
        "source_hook_pattern":"Open with a concrete tension or surprising consequence, then quickly explain the mechanism.",
        "structure":["hook","context","mechanism","evidence/qualification","payoff","CTA"],
        "pacing":"Fast opening, short explanatory beats, one clear payoff.",
        "reusable_patterns":["specific tension first","show mechanism instead of copying wording","short evidence-bounded claims"],
        "evidence_claims":[],
        "prohibited_copy_notes":["Do not reuse source lines verbatim.","Do not imitate creator identity or voice.","Do not reuse source footage by default."],
    }
    base=project.get("topic") or project.get("source_title") or "the source topic"
    rewrite={
        "new_angle":f"Explain the mechanism behind {base} from a fresh evidence-bounded angle.",
        "hook_candidates":[f"What actually makes {base} work?","The interesting part of {base} is not the headline — it is the mechanism."],
        "original_script":f"Here is a new way to look at {base}. Start with the mechanism, separate what is known from what still needs evidence, and end with one practical takeaway. This demo rewrite is intentionally original and does not reproduce the source wording.",
        "originality_note":"Original demonstration rewrite based on structure, not copied wording or identity.",
        "media_brief":"Use original graphics, screenshots you have rights to, licensed/stock B-roll, or generated visuals. Do not reuse source creator footage by default.",
        "fact_check_notes":["Demo mode contains no claim of external factual verification."],
        "source_links":[project["source_url"]],
    }
    return analysis,rewrite

async def run_revideo_analysis(project_id,language="English"):
    project=get_revideo_project(project_id)
    if not project:raise ValueError("Revideo project not found")
    transcript=await asyncio.to_thread(_fetch_revideo_transcript,project)
    if not FACTORY_LLM_API_KEY:
        analysis,rewrite=_demo_revideo(project,transcript)
        analysis_run=rewrite_run=None
    else:
        _content_brain_budget_guard(1000)
        analysis_system=(
            "You are the Structure Analyzer in FactoryOS Revideo. Analyze the supplied public-source transcript for reusable editorial structure, "
            "not for copying. Return JSON only with keys source_summary, source_hook_pattern, structure, pacing, reusable_patterns, evidence_claims, prohibited_copy_notes. "
            "Do not recommend copying exact lines, creator identity, voice, footage, branding, or distinctive expression. Treat unsupported claims as unverified."
        )
        analysis_user=(
            f"LANGUAGE: {language}\nSOURCE URL: {project['source_url']}\nTITLE: {project.get('source_title','')}\nTOPIC: {project.get('topic','')}\n"
            f"SOURCE NOTES: {project.get('source_notes','')}\nTRANSCRIPT:\n{_trim_llm_context(transcript,12000)}"
        )
        result=await asyncio.wait_for(asyncio.to_thread(_content_brain_llm,"Researcher",analysis_system,analysis_user,1000,_workflow_model(None)),timeout=AGENT_TIMEOUT_SECONDS)
        analysis=_parse_json_object(result["content"])
        analysis_run=start_agent_run("Researcher",None,"revideo",model=result["model"])
        save_artifact("Researcher","analysis",f"Revideo source structure · {project_id[:8]}",
                      json.dumps(analysis,ensure_ascii=False,indent=2),run_id=analysis_run,
                      meta={"mode":"live_llm","revideo_project_id":project_id,"source_url":project["source_url"],"model":result["model"]})
        finish_agent_run(analysis_run,status="completed",input_tokens=result["input_tokens"],output_tokens=result["output_tokens"],cost_usd=result["cost_usd"],
                         meta={"mode":"live_llm","revideo_project_id":project_id})
        _content_brain_budget_guard(1200)
        rewrite_system=(
            "You are the Rewrite Strategist in FactoryOS Revideo. Create a materially original short-form concept from the supplied structural analysis and source evidence. "
            "Return JSON only with keys new_angle, hook_candidates, original_script, originality_note, media_brief, fact_check_notes, source_links. "
            "Do not reproduce distinctive source wording, do not imitate the creator's identity or voice, do not instruct re-uploading source footage, and do not add unsupported factual claims. "
            "Preserve the source URL in source_links. hook_candidates must contain 2-4 concise original hooks."
        )
        rewrite_user=(
            f"LANGUAGE: {language}\nSOURCE URL: {project['source_url']}\nANALYSIS: {json.dumps(analysis,ensure_ascii=False)[:9000]}\n"
            f"SOURCE NOTES: {project.get('source_notes','')}\nCreate an original rewrite inspired only by reusable structure."
        )
        result2=await asyncio.wait_for(asyncio.to_thread(_content_brain_llm,"Editor",rewrite_system,rewrite_user,1200,_workflow_model(None)),timeout=AGENT_TIMEOUT_SECONDS)
        rewrite=_parse_json_object(result2["content"])
        rewrite_run=start_agent_run("Editor",None,"revideo",model=result2["model"])
        save_artifact("Editor","text",f"Revideo original rewrite · {project_id[:8]}",
                      json.dumps(rewrite,ensure_ascii=False,indent=2),run_id=rewrite_run,
                      meta={"mode":"live_llm","revideo_project_id":project_id,"source_url":project["source_url"],"model":result2["model"]})
        finish_agent_run(rewrite_run,status="completed",input_tokens=result2["input_tokens"],output_tokens=result2["output_tokens"],cost_usd=result2["cost_usd"],
                         meta={"mode":"live_llm","revideo_project_id":project_id})
    for key in REVIDEO_REQUIRED_REWRITE_FIELDS:
        if key not in rewrite:raise RuntimeError(f"Rewrite provider output missing required field: {key}")
    rewrite["source_links"]=list(dict.fromkeys([project["source_url"]]+[str(x) for x in rewrite.get("source_links") or [] if str(x).strip()]))
    original=_originality_check(transcript,rewrite.get("original_script") or "")
    status="ready" if original["passed"] else "needs_revision"
    provenance=dict(project.get("provenance") or {})
    provenance.update({"analysis_run_id":analysis_run,"rewrite_run_id":rewrite_run,"analyzed_at":ts(),
                       "source_url":project["source_url"],"human_approval_required":True})
    con=db();con.execute("""UPDATE revideo_projects SET transcript=?,status=?,analysis_json=?,rewrite_json=?,originality_json=?,provenance_json=?,updated_at=? WHERE id=?""",
        (transcript,status,json.dumps(analysis,ensure_ascii=False),json.dumps(rewrite,ensure_ascii=False),
         json.dumps(original,ensure_ascii=False),json.dumps(provenance,ensure_ascii=False),ts(),project_id))
    con.commit();con.close()
    return get_revideo_project(project_id)

def create_revideo_production_job(project_id):
    project=get_revideo_project(project_id)
    if not project:raise ValueError("Revideo project not found")
    if project.get("status")!="ready":raise ValueError("Revideo analysis must be ready and pass the originality guard first")
    if project.get("job_id"):
        return {"created":False,"job":get_job(project["job_id"]),"project":project}
    rewrite=project.get("rewrite") or {};analysis=project.get("analysis") or {}
    signal=ingest_source_signal(SignalCreate(
        title=project.get("source_title") or f"Revideo source {project_id[:8]}",
        url=project["source_url"],content=project.get("transcript") or project.get("source_notes") or analysis.get("source_summary",""),
        source_type="revideo_source",topic=project.get("topic") or "revideo"
    ))["signal"]
    idea=create_content_idea(IdeaCreate(
        title=(rewrite.get("new_angle") or project.get("source_title") or "Original Revideo concept")[:300],
        topic=project.get("topic") or "revideo",
        angle=rewrite.get("new_angle") or "",
        audience="short-form audience",
        why_now="Derived from a current public-source video/topic using an original rewrite workflow.",
        source_signal_ids=[signal["id"]],source_links=[project["source_url"]],
        score=0.75,risk_flags=[] if (project.get("originality") or {}).get("passed") else ["originality_review"],
        complexity="medium"
    ))
    verification={"decision":"shortlist","score":0.75,"risk_flags":[],
                  "verification_notes":"Revideo source provenance and mechanical originality guard recorded. Human approval remains required.",
                  "rejection_reason":""}
    research={"research_summary":analysis.get("source_summary",""),"claims":analysis.get("evidence_claims") or [],
              "source_signal_ids":[signal["id"]],"source_links":[project["source_url"]],
              "missing_evidence":["Any factual claim not supported by the source transcript/notes still requires verification."]}
    provenance=dict(idea.get("provenance") or {});provenance["revideo"]={"project_id":project_id,"source_url":project["source_url"],
        "originality":project.get("originality") or {},"rewrite_created_at":ts()}
    con=db();now=ts();con.execute("""UPDATE content_ideas SET status='selected',verified_at=?,research_json=?,strategy_json=?,verification_json=?,provenance_json=?,updated_at=? WHERE id=?""",
        (now,json.dumps(research,ensure_ascii=False),json.dumps({"rewrite":rewrite},ensure_ascii=False),
         json.dumps(verification,ensure_ascii=False),json.dumps(provenance,ensure_ascii=False),now,idea["id"]));con.commit();con.close()
    bridged=create_job_from_idea(idea["id"],project.get("language") or "English")
    job=bridged["job"]
    brief=(job.get("brief") or "")+"\n\nREVIDEO ORIGINAL SCRIPT DIRECTION:\n"+str(rewrite.get("original_script") or "")+"\n\nSOURCE STRUCTURE (do not copy wording):\n"+json.dumps(analysis,ensure_ascii=False)
    con=db();con.execute("UPDATE jobs SET brief=?,updated_at=? WHERE id=?",(brief[:22000],ts(),job["id"]))
    con.execute("UPDATE revideo_projects SET source_signal_id=?,idea_id=?,job_id=?,status='in_production',updated_at=? WHERE id=?",
                (signal["id"],idea["id"],job["id"],ts(),project_id));con.commit();con.close()
    save_artifact("Researcher","analysis","Revideo source structure",json.dumps(analysis,ensure_ascii=False,indent=2),
                  job_id=job["id"],meta={"revideo_project_id":project_id,"source_url":project["source_url"],"provenance":True})
    save_artifact("Editor","text","Revideo original rewrite",json.dumps(rewrite,ensure_ascii=False,indent=2),
                  job_id=job["id"],meta={"revideo_project_id":project_id,"source_url":project["source_url"],"originality":project.get("originality")})
    event(job["id"],f"Created from Revideo project {project_id}; source wording/identity must not be copied")
    return {"created":True,"job":get_job(job["id"]),"project":get_revideo_project(project_id)}

def _media_job_dict(row):
    if not row:return None
    d=dict(row)
    d["request"]=_decode_json(d.pop("request_json","{}"),{})
    d["response"]=_decode_json(d.pop("response_json","{}"),{})
    return d

def get_media_job(media_job_id):
    con=db();row=con.execute("SELECT * FROM media_jobs WHERE id=?",(media_job_id,)).fetchone();con.close()
    return _media_job_dict(row)

def get_media_jobs(limit=100,project_id=None):
    con=db()
    if project_id:
        rows=con.execute("SELECT * FROM media_jobs WHERE revideo_project_id=? ORDER BY updated_at DESC LIMIT ?",
                         (project_id,max(1,min(300,int(limit))))).fetchall()
    else:
        rows=con.execute("SELECT * FROM media_jobs ORDER BY updated_at DESC LIMIT ?",
                         (max(1,min(300,int(limit))),)).fetchall()
    con.close()
    items=[_media_job_dict(x) for x in rows];counts={}
    for item in items:counts[item["status"]]=counts.get(item["status"],0)+1
    return {"summary":{"total":len(items),**counts},"items":items}

def _normalize_media_status(raw_status,media_url=""):
    value=str(raw_status or "").strip().lower()
    if media_url:return "ready"
    if value in ("done","complete","completed","success","succeeded","ready","finished"):return "ready"
    if value in ("failed","error","cancelled","canceled","rejected"):return "failed"
    if value in ("queued","pending","submitted"):return "submitted"
    return "processing"

def _finalize_media_job(media_job_id,status,media_url="",error="",response=None,provider_job_id=""):
    item=get_media_job(media_job_id)
    if not item:raise ValueError("Media job not found")
    status=_normalize_media_status(status,media_url)
    completed_at=ts() if status in ("ready","failed") else None
    con=db();con.execute("""UPDATE media_jobs SET status=?,media_url=?,error=?,response_json=?,
                            provider_job_id=CASE WHEN ?!='' THEN ? ELSE provider_job_id END,
                            updated_at=?,completed_at=? WHERE id=?""",
        (status,media_url or item.get("media_url",""),error or "",json.dumps(response or {},ensure_ascii=False),
         provider_job_id,provider_job_id,ts(),completed_at,media_job_id))
    con.commit();con.close()
    item=get_media_job(media_job_id)
    if status=="ready" and media_url:
        project=get_revideo_project(item["revideo_project_id"])
        media={"url":media_url,"provider":item["provider"],"provider_id":item.get("provider_job_id"),
               "media_job_id":media_job_id,"created_at":ts(),"raw_status":status}
        con=db();con.execute("UPDATE revideo_projects SET media_json=?,updated_at=? WHERE id=?",
                             (json.dumps(media,ensure_ascii=False),ts(),item["revideo_project_id"]));con.commit();con.close()
        save_artifact("Render Agent","video","Revideo generated video",job_id=item["job_id"],url=media_url,mime_type="video/mp4",
                      meta={"revideo_project_id":item["revideo_project_id"],"provider":item["provider"],
                            "provider_job_id":item.get("provider_job_id"),"media_job_id":media_job_id,
                            "source_media_reused":False})
        event(item["job_id"],f"Media job {media_job_id} completed with a video artifact")
    elif status=="failed":
        event(item["job_id"],f"Media job {media_job_id} failed: {error or 'provider failure'}")
    return get_media_job(media_job_id)

def _edit_profile_dict(row):
    if not row:return None
    item=dict(row)
    item["config"]=_decode_json(item.pop("config_json","{}"),{})
    item["active"]=bool(item.get("active"))
    return item

def get_edit_profiles():
    con=db();rows=[_edit_profile_dict(x) for x in con.execute("SELECT * FROM edit_profiles ORDER BY id,version DESC").fetchall()];con.close()
    return rows

def get_edit_profile(profile_id,version=1):
    con=db();row=con.execute("SELECT * FROM edit_profiles WHERE id=? AND version=?",(profile_id,int(version))).fetchone();con.close()
    return _edit_profile_dict(row)

def _edit_job_dict(row,include_artifacts=True):
    if not row:return None
    item=dict(row)
    item["request"]=_decode_json(item.pop("request_json","{}"),{})
    item["response"]=_decode_json(item.pop("response_json","{}"),{})
    item["report"]=_decode_json(item.pop("report_json","{}"),{})
    if include_artifacts:
        con=db();arts=[dict(x) for x in con.execute("SELECT * FROM edit_artifacts WHERE edit_job_id=? ORDER BY created_at",(item["id"],)).fetchall()];con.close()
        for a in arts:a["content"]=_decode_json(a.pop("content_json","{}"),{})
        item["artifacts"]=arts
    return item

def get_edit_job(edit_job_id):
    con=db();row=con.execute("SELECT * FROM edit_jobs WHERE id=?",(edit_job_id,)).fetchone();con.close()
    return _edit_job_dict(row)

def get_edit_jobs(limit=80,job_id=None):
    con=db()
    if job_id:
        rows=con.execute("SELECT * FROM edit_jobs WHERE production_job_id=? ORDER BY updated_at DESC LIMIT ?",(job_id,max(1,min(300,int(limit))))).fetchall()
    else:
        rows=con.execute("SELECT * FROM edit_jobs ORDER BY updated_at DESC LIMIT ?",(max(1,min(300,int(limit))),)).fetchall()
    items=[_edit_job_dict(x,False) for x in rows];con.close()
    summary={"total":len(items),"queued":sum(1 for x in items if x["status"]=="queued"),"active":sum(1 for x in items if x["status"] in ("submitted","processing")),"ready":sum(1 for x in items if x["status"]=="ready"),"failed":sum(1 for x in items if x["status"]=="failed")}
    return {"jobs":items,"summary":summary}


def _normalize_service_endpoint(value):
    value=str(value or "").strip().rstrip("/")
    if value and "://" not in value:value="http://"+value
    return value

def _media_finisher_submit_endpoint():
    base=_normalize_service_endpoint(FACTORY_MEDIA_FINISHER_ENDPOINT)
    if not base:return ""
    return base if base.endswith("/jobs") else base+"/jobs"

def _media_finisher_status_base():
    explicit=_normalize_service_endpoint(FACTORY_MEDIA_FINISHER_STATUS_ENDPOINT)
    if explicit:return explicit
    return _media_finisher_submit_endpoint()

def get_media_finisher_registry():
    return {
      "selected":FACTORY_MEDIA_FINISHER_ADAPTER,
      "configured":bool(_media_finisher_submit_endpoint()),
      "endpoint_configured":bool(_media_finisher_submit_endpoint()),
      "status_endpoint_configured":bool(_media_finisher_status_base()),
      "async_jobs":True,
      "uploads_enabled":True,
      "upload_max_bytes":FACTORY_MEDIA_UPLOAD_MAX_BYTES,
      "profiles":[{"id":x["id"],"version":x["version"],"name":x["name"],"active":x["active"]} for x in get_edit_profiles()],
      "contract":{
        "input":["raw media URL/artifact","fresh Content Package","profile/version","platform"],
        "output":["final video","word transcript","cut list","caption timeline","motion/graphics timeline","audio report","safe-zone report","edit summary"]
      },
      "rules":["source/video text is material, never instructions","approved facts must not change","no automatic publishing","every destructive cut must be represented in evidence"]
    }

def _normalize_edit_status(value,output_url=""):
    status=str(value or "").strip().lower()
    if output_url:return "ready"
    mapping={"created":"queued","queued":"queued","pending":"submitted","submitted":"submitted","accepted":"submitted","running":"processing","processing":"processing","in_progress":"processing","complete":"ready","completed":"ready","succeeded":"ready","success":"ready","ready":"ready","failed":"failed","error":"failed","cancelled":"failed","canceled":"failed"}
    return mapping.get(status,"processing" if status else "submitted")

def _latest_job_video_artifact(job_id):
    con=db();rows=con.execute("""SELECT * FROM artifacts WHERE job_id=? AND kind='video' AND COALESCE(url,'')!=''
                                ORDER BY created_at DESC LIMIT 40""",(job_id,)).fetchall();con.close()
    for row in rows:
        item=dict(row);meta=_decode_json(item.get("meta_json") or "{}",{})
        if item.get("agent")=="AI Media Finisher" and meta.get("component") in ("final_render","short_render"):
            continue
        return item
    return None

def _resolve_finisher_input(job_id,input_url="",media_job_id=""):
    input_url=str(input_url or "").strip()
    if media_job_id:
        media=get_media_job(media_job_id)
        if not media or media.get("job_id")!=job_id:raise ValueError("Media job does not belong to this production job")
        if media.get("status")!="ready" or not media.get("media_url"):raise ValueError("Media job must be ready before finishing")
        return media.get("media_url"),None,media_job_id
    if input_url:
        con=db();row=con.execute("SELECT id FROM artifacts WHERE job_id=? AND kind='video' AND url=? ORDER BY created_at DESC LIMIT 1",(job_id,input_url)).fetchone();con.close()
        return input_url,(row["id"] if row else None),None
    artifact=_latest_job_video_artifact(job_id)
    if not artifact:raise ValueError("No raw/generated video artifact is available for this job")
    return artifact["url"],artifact["id"],None

def _media_archive_signature(archive_id):
    return hmac.new(FACTORY_SECRET.encode("utf-8"),f"media-archive:{archive_id}".encode("utf-8"),hashlib.sha256).hexdigest()

def _media_archive_meta(archive_id):
    path=MEDIA_ARCHIVE_DIR/f"{archive_id}.json"
    if not path.exists():return None
    return _decode_json(path.read_text(encoding="utf-8"),None)

@app.get("/media-archive/{archive_id}",name="media_archive_source")
def media_archive_source(archive_id:str,token:str=""):
    expected=_media_archive_signature(archive_id)
    if not token or not hmac.compare_digest(token,expected):raise HTTPException(403,"Invalid media archive token")
    meta=_media_archive_meta(archive_id)
    if not meta:raise HTTPException(404,"Archived media not found")
    path=MEDIA_ARCHIVE_DIR/str(meta.get("stored_name") or "")
    if not path.exists():raise HTTPException(404,"Archived media file missing")
    return FileResponse(path,media_type=meta.get("content_type") or "video/mp4",
                        filename=meta.get("filename") or path.name,content_disposition_type="inline")

def _artifact_media_row(artifact_id):
    con=db();row=con.execute("SELECT * FROM artifacts WHERE id=?",(artifact_id,)).fetchone();con.close()
    return dict(row) if row else None

def _artifact_archive_file(artifact):
    meta=_decode_json(artifact.get("meta_json") or "{}",{})
    archive_id=str(meta.get("archive_id") or "").strip()
    if not archive_id:
        raw=str(artifact.get("url") or "")
        match=re.search(r"/media-archive/([^?/#]+)",raw)
        archive_id=match.group(1) if match else ""
    if not archive_id:return None,None
    archive_meta=_media_archive_meta(archive_id)
    if not archive_meta:return None,None
    path=MEDIA_ARCHIVE_DIR/str(archive_meta.get("stored_name") or "")
    if not path.exists():return None,None
    return path,archive_meta

@app.get("/api/artifacts/{artifact_id}/media",name="artifact_media")
def artifact_media(artifact_id:str,download:bool=False):
    artifact=_artifact_media_row(artifact_id)
    if not artifact:raise HTTPException(404,"Artifact not found")
    path,archive_meta=_artifact_archive_file(artifact)
    if not path and artifact.get("kind")=="video" and _is_ephemeral_finisher_url(artifact.get("url")):
        try:
            _archive_media_artifact(artifact_id)
            artifact=_artifact_media_row(artifact_id) or artifact
            path,archive_meta=_artifact_archive_file(artifact)
        except Exception as exc:
            if not str(artifact.get("url") or ""):
                raise HTTPException(410,f"Media is no longer available: {str(exc)[:220]}")
    if path and archive_meta:
        return FileResponse(path,media_type=archive_meta.get("content_type") or artifact.get("mime_type") or "application/octet-stream",
                            filename=archive_meta.get("filename") or path.name,
                            content_disposition_type="attachment" if download else "inline")
    source_url=str(artifact.get("url") or "").strip()
    if not source_url:raise HTTPException(404,"Artifact has no media URL")
    if _is_ephemeral_finisher_url(source_url):
        raise HTTPException(410,"This temporary Media Finisher file expired before durable archival. Rerun the Media Finisher output to restore it.")
    return RedirectResponse(source_url,status_code=307)

def _is_ephemeral_finisher_url(value):
    raw=str(value or "").strip()
    if not raw:return False
    try:
        parsed=urlparse.urlparse(raw)
        host=(parsed.hostname or "").lower()
        path=parsed.path or ""
    except Exception:
        return False
    return bool(host in FACTORY_MEDIA_FINISHER_EPHEMERAL_HOSTS and path.startswith("/files/"))

def _download_media_to_path(source_url,dest):
    req=urlrequest.Request(source_url,headers={"User-Agent":f"FactoryOS/{APP_VERSION} durable-media-archive"})
    total=0;digest=hashlib.sha256();content_type="video/mp4"
    try:
        with urlrequest.urlopen(req,timeout=180) as resp, dest.open("wb") as fh:
            content_type=str(resp.headers.get("Content-Type") or "video/mp4").split(";")[0].strip() or "video/mp4"
            length=str(resp.headers.get("Content-Length") or "").strip()
            if length and int(length)>FACTORY_MEDIA_ARCHIVE_MAX_BYTES:
                raise RuntimeError(f"Finished media exceeds durable archive limit of {FACTORY_MEDIA_ARCHIVE_MAX_BYTES//(1024*1024)} MB")
            while True:
                chunk=resp.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>FACTORY_MEDIA_ARCHIVE_MAX_BYTES:
                    raise RuntimeError(f"Finished media exceeds durable archive limit of {FACTORY_MEDIA_ARCHIVE_MAX_BYTES//(1024*1024)} MB")
                fh.write(chunk);digest.update(chunk)
    except Exception:
        if dest.exists():dest.unlink()
        raise
    if total<1024:
        if dest.exists():dest.unlink()
        raise RuntimeError("Finished media archive download was empty or too small")
    return {"bytes":total,"sha256":digest.hexdigest(),"content_type":content_type}

def _replace_media_url(value,old,new):
    if isinstance(value,dict):return {k:_replace_media_url(v,old,new) for k,v in value.items()}
    if isinstance(value,list):return [_replace_media_url(v,old,new) for v in value]
    if isinstance(value,str) and value==old:return new
    return value

def _archive_media_artifact(artifact_id):
    con=db();row=con.execute("SELECT * FROM artifacts WHERE id=? AND kind='video'",(artifact_id,)).fetchone();con.close()
    if not row:return None
    artifact=dict(row);meta=_decode_json(artifact.get("meta_json") or "{}",{})
    source_url=str(artifact.get("url") or "").strip()
    if not source_url:return None
    if meta.get("durable_media") and "/media-archive/" in source_url:
        return {"artifact_id":artifact_id,"url":source_url,"already_archived":True}
    if not _is_ephemeral_finisher_url(source_url):
        return {"artifact_id":artifact_id,"url":source_url,"archive_required":False}
    archive_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:durable-media:{artifact_id}:{source_url}"))
    ext=Path(urlparse.urlparse(source_url).path).suffix.lower()
    if ext not in {".mp4",".mov",".m4v",".webm",".mpeg",".mpg"}:ext=".mp4"
    stored_name=archive_id+ext;dest=MEDIA_ARCHIVE_DIR/stored_name
    archive_meta=_media_archive_meta(archive_id)
    if not (archive_meta and dest.exists()):
        result=_download_media_to_path(source_url,dest)
        archive_meta={
          "archive_id":archive_id,"artifact_id":artifact_id,"job_id":artifact.get("job_id"),
          "edit_job_id":meta.get("edit_job_id"),"source_url":source_url,"stored_name":stored_name,
          "filename":Path(urlparse.urlparse(source_url).path).name or stored_name,
          "content_type":result["content_type"],"bytes":result["bytes"],"sha256":result["sha256"],
          "created_at":ts()
        }
        (MEDIA_ARCHIVE_DIR/f"{archive_id}.json").write_text(json.dumps(archive_meta,ensure_ascii=False,indent=2),encoding="utf-8")
    token=_media_archive_signature(archive_id)
    durable_url=f"{FACTORY_PUBLIC_BASE_URL}/media-archive/{archive_id}?token={urlparse.quote(token,safe='')}"
    updated_meta={**meta,"durable_media":True,"archive_id":archive_id,"archive_bytes":archive_meta.get("bytes"),
                  "archive_sha256":archive_meta.get("sha256"),"source_url":source_url,"archived_at":ts()}
    edit_job_id=meta.get("edit_job_id")
    con=db()
    con.execute("UPDATE artifacts SET url=?,mime_type=?,meta_json=? WHERE id=?",
                (durable_url,archive_meta.get("content_type") or artifact.get("mime_type") or "video/mp4",
                 json.dumps(updated_meta,ensure_ascii=False,default=str),artifact_id))
    if edit_job_id:
        edit_row=con.execute("SELECT output_url,report_json FROM edit_jobs WHERE id=?",(edit_job_id,)).fetchone()
        if edit_row:
            output_url=durable_url if str(edit_row["output_url"] or "")==source_url else edit_row["output_url"]
            report=_decode_json(edit_row["report_json"] or "{}",{})
            report=_replace_media_url(report,source_url,durable_url)
            con.execute("UPDATE edit_jobs SET output_url=?,report_json=?,updated_at=? WHERE id=?",
                        (output_url,json.dumps(report,ensure_ascii=False,default=str),ts(),edit_job_id))
    con.commit();con.close()
    if artifact.get("job_id"):event(artifact["job_id"],f"Durable media archived: {artifact_id[:8]} · {round(float(archive_meta.get('bytes') or 0)/1024/1024,1)} MB")
    return {"artifact_id":artifact_id,"url":durable_url,"archive_id":archive_id,
            "bytes":archive_meta.get("bytes"),"sha256":archive_meta.get("sha256"),"archive_required":True}

_media_archive_active=set()
_media_archive_lock=threading.Lock()

def _set_media_archive_state(edit_job_id,status,error="",items=None):
    item=get_edit_job(edit_job_id)
    if not item:return None
    response=dict(item.get("response") or {})
    response["durable_media_status"]=status
    response["durable_media_items"]=items or []
    if error:response["durable_media_error"]=str(error)[:700]
    elif "durable_media_error" in response:response.pop("durable_media_error",None)
    con=db();con.execute("UPDATE edit_jobs SET response_json=?,updated_at=? WHERE id=?",
                         (json.dumps(response,ensure_ascii=False,default=str),ts(),edit_job_id));con.commit();con.close()
    return get_edit_job(edit_job_id)

def _edit_media_archive_targets(edit_job_id):
    edit=get_edit_job(edit_job_id)
    if not edit:return []
    con=db();rows=con.execute("""SELECT id,url,meta_json FROM artifacts
                                WHERE job_id=? AND agent='AI Media Finisher' AND kind='video'
                                ORDER BY created_at""",(edit["production_job_id"],)).fetchall();con.close()
    targets=[]
    for row in rows:
        meta=_decode_json(row["meta_json"] or "{}",{})
        if meta.get("edit_job_id")!=edit_job_id:continue
        if meta.get("component") not in ("final_render","short_render"):continue
        if _is_ephemeral_finisher_url(row["url"]):targets.append(row["id"])
    return targets

def _archive_edit_media(edit_job_id):
    edit=get_edit_job(edit_job_id)
    if not edit:return {"status":"missing","items":[]}
    targets=_edit_media_archive_targets(edit_job_id)
    if not targets:
        _set_media_archive_state(edit_job_id,"not_required",items=[])
        return {"status":"not_required","items":[]}
    _set_media_archive_state(edit_job_id,"archiving",items=[])
    items=[]
    try:
        for artifact_id in targets:items.append(_archive_media_artifact(artifact_id))
        _set_media_archive_state(edit_job_id,"ready",items=items)
        event(edit["production_job_id"],f"Durable media ready: {edit_job_id[:8]} · {len(items)} deliverable(s)")
        return {"status":"ready","items":items}
    except Exception as exc:
        _set_media_archive_state(edit_job_id,"failed",error=str(exc),items=items)
        event(edit["production_job_id"],f"Durable media archive failed: {edit_job_id[:8]} · {str(exc)[:180]}")
        return {"status":"failed","items":items,"error":str(exc)}

def _patch_edit_job_response(edit_job_id,patch):
    item=get_edit_job(edit_job_id)
    if not item:return None
    response=dict(item.get("response") or {});response.update(patch or {})
    con=db();con.execute("UPDATE edit_jobs SET response_json=?,updated_at=? WHERE id=?",
                         (json.dumps(response,ensure_ascii=False,default=str),ts(),edit_job_id));con.commit();con.close()
    return get_edit_job(edit_job_id)

def _recoverable_persistent_finisher_input(edit):
    if not edit:return False
    raw=str(edit.get("input_url") or "").strip()
    try:
        source=urlparse.urlparse(raw);public=urlparse.urlparse(FACTORY_PUBLIC_BASE_URL)
    except Exception:
        return False
    if not source.hostname or not public.hostname or source.hostname.lower()!=public.hostname.lower():
        return False
    if not source.path.startswith("/media-source/"):
        return False
    upload_id=source.path.rsplit("/",1)[-1]
    meta=_media_upload_meta(upload_id)
    if not meta:return False
    path=MEDIA_UPLOAD_DIR/str(meta.get("stored_name") or "")
    return bool(path.exists() and path.stat().st_size>=1024)

def _latest_ready_edit_for_job(production_job_id):
    con=db();row=con.execute("""SELECT id FROM edit_jobs
                                WHERE production_job_id=? AND status='ready'
                                ORDER BY COALESCE(completed_at,updated_at) DESC,created_at DESC,id DESC LIMIT 1""",
                             (production_job_id,)).fetchone();con.close()
    return row["id"] if row else ""

def _maybe_repair_lost_ephemeral_media(edit_job_id,result):
    error=str((result or {}).get("error") or "")
    if "404" not in error:return None
    edit=get_edit_job(edit_job_id)
    if not edit or edit.get("status")!="ready":return None
    response=dict(edit.get("response") or {})
    if response.get("lost_media_repair_status") in ("queued","processing","done","skipped","failed"):
        return response.get("lost_media_repair_child_id")
    if _latest_ready_edit_for_job(edit["production_job_id"])!=edit_job_id:
        _patch_edit_job_response(edit_job_id,{"lost_media_repair_status":"skipped",
                                             "lost_media_repair_reason":"superseded_ready_edit",
                                             "lost_media_repair_at":ts()})
        print(json.dumps({"event":"LOST_MEDIA_REPAIR","edit_job_id":edit_job_id,"status":"skipped","reason":"superseded"}),flush=True)
        return None
    if not _recoverable_persistent_finisher_input(edit):
        _patch_edit_job_response(edit_job_id,{"lost_media_repair_status":"failed",
                                             "lost_media_repair_reason":"persistent_raw_source_unavailable",
                                             "lost_media_repair_at":ts()})
        print(json.dumps({"event":"LOST_MEDIA_REPAIR","edit_job_id":edit_job_id,"status":"failed","reason":"raw_source_unavailable"}),flush=True)
        return None
    _patch_edit_job_response(edit_job_id,{"lost_media_repair_status":"processing",
                                         "lost_media_repair_reason":"ephemeral_output_404",
                                         "lost_media_repair_at":ts()})
    try:
        rerun=rerun_media_finisher_stage(edit_job_id,"render")
        child=((rerun or {}).get("edit_job") or {}).get("id") or ""
        _patch_edit_job_response(edit_job_id,{"lost_media_repair_status":"queued",
                                             "lost_media_repair_child_id":child})
        event(edit["production_job_id"],f"Lost temporary Media Finisher output auto-repair queued: {edit_job_id[:8]} → {child[:8]}")
        print(json.dumps({"event":"LOST_MEDIA_REPAIR","edit_job_id":edit_job_id,"status":"queued","child_edit_job_id":child}),flush=True)
        return child
    except Exception as exc:
        _patch_edit_job_response(edit_job_id,{"lost_media_repair_status":"failed",
                                             "lost_media_repair_reason":str(exc)[:500]})
        event(edit["production_job_id"],f"Lost media auto-repair failed to queue: {edit_job_id[:8]} · {str(exc)[:160]}")
        print(json.dumps({"event":"LOST_MEDIA_REPAIR","edit_job_id":edit_job_id,"status":"failed","error":str(exc)[:400]}),flush=True)
        return None

def _archive_edit_media_background(edit_job_id):
    with _media_archive_lock:
        if edit_job_id in _media_archive_active:return
        _media_archive_active.add(edit_job_id)
    try:
        result=_archive_edit_media(edit_job_id)
        print(json.dumps({"event":"DURABLE_MEDIA_ARCHIVE","edit_job_id":edit_job_id,"status":result.get("status"),
                          "items":len(result.get("items") or []),"error":str(result.get("error") or "")[:300]}),flush=True)
        if result.get("status")=="failed":
            _maybe_repair_lost_ephemeral_media(edit_job_id,result)
    finally:
        with _media_archive_lock:_media_archive_active.discard(edit_job_id)

def _queue_durable_media_archive(edit_job_id):
    edit=get_edit_job(edit_job_id)
    if not edit:return False
    targets=_edit_media_archive_targets(edit_job_id)
    if not targets:
        _set_media_archive_state(edit_job_id,"not_required",items=[])
        return False
    _set_media_archive_state(edit_job_id,"queued",items=[])
    threading.Thread(target=_archive_edit_media_background,args=(edit_job_id,),daemon=True,
                     name=f"media-archive-{edit_job_id[:8]}").start()
    return True

def _recover_ready_durable_media():
    con=db();rows=con.execute("""SELECT id FROM edit_jobs WHERE status='ready'
                                ORDER BY updated_at DESC LIMIT 60""").fetchall();con.close()
    queued=0
    for row in rows:
        try:
            if _edit_media_archive_targets(row["id"]):
                if _queue_durable_media_archive(row["id"]):queued+=1
        except Exception as exc:
            print(json.dumps({"event":"DURABLE_MEDIA_RECOVERY_ERROR","edit_job_id":row["id"],"error":str(exc)[:400]}),flush=True)
    if queued:print(json.dumps({"event":"DURABLE_MEDIA_RECOVERY","queued":queued}),flush=True)
    return queued

def _persist_edit_evidence(edit_job_id,job_id,profile_id,profile_version,report,output_url=""):
    report=report if isinstance(report,dict) else {}
    evidence_map={
      "transcript_words":("json","Word-level transcript"),
      "transcript_corrections":("json","Transcript corrections"),
      "cut_list":("json","Edit cut list"),
      "caption_timeline":("json","Caption timeline"),
      "motion_timeline":("json","Motion / zoom timeline"),
      "graphics_timeline":("json","Emphasis graphics timeline"),
      "shorts_manifest":("json","Shorts / Reels cut manifest"),
      "audio_report":("analysis","Audio finishing report"),
      "safe_zone_report":("analysis","Safe-zone / frame QA"),
      "edit_summary":("analysis","Media Finisher edit summary"),
    }
    now=ts();con=db()
    for key,(kind,title) in evidence_map.items():
        if key not in report:continue
        value=report.get(key)
        content=value if isinstance(value,dict) else {"items":value} if isinstance(value,list) else {"value":value}
        eid=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{edit_job_id}:{key}"))
        con.execute("""INSERT OR REPLACE INTO edit_artifacts(id,edit_job_id,kind,content_json,url,created_at)
                       VALUES(?,?,?,?,?,?)""",(eid,edit_job_id,key,json.dumps(content,ensure_ascii=False,default=str),"",now))
        existing=con.execute("SELECT id FROM artifacts WHERE job_id=? AND agent='AI Media Finisher' AND title=? AND meta_json LIKE ?",(job_id,title,f'%"edit_job_id": "{edit_job_id}"%')).fetchone()
        if not existing:
            save_id=str(uuid.uuid4())
            con.execute("""INSERT INTO artifacts(id,run_id,job_id,agent,kind,title,content,url,mime_type,created_at,meta_json)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(save_id,None,job_id,"AI Media Finisher",kind,title,json.dumps(content,ensure_ascii=False,indent=2,default=str),None,"application/json" if kind=="json" else None,now,json.dumps({"edit_job_id":edit_job_id,"profile_id":profile_id,"profile_version":profile_version,"component":key,"mode":"external_finisher"},ensure_ascii=False)))
    con.commit();con.close()
    edit_options=((report.get("edit_summary") or {}).get("options") or {}) if isinstance(report,dict) else {}
    full_video_enabled=bool(edit_options.get("edit_full_video",True))
    if output_url and full_video_enabled:
        con=db();existing=con.execute("SELECT id FROM artifacts WHERE job_id=? AND agent='AI Media Finisher' AND kind='video' AND url=?",(job_id,output_url)).fetchone();con.close()
        if existing:return existing["id"]
        return save_artifact("AI Media Finisher","video","Finished video",job_id=job_id,url=output_url,mime_type="video/mp4",meta={"edit_job_id":edit_job_id,"profile_id":profile_id,"profile_version":profile_version,"component":"final_render","mode":"external_finisher","human_approval_required":True})
    return None

def _persist_short_video_artifacts(edit_job_id,job_id,report):
    manifest=(report or {}).get("shorts_manifest") or {}
    clips=manifest.get("clips") if isinstance(manifest,dict) else []
    saved=[]
    for idx,clip in enumerate(clips or [],1):
        if not isinstance(clip,dict):continue
        url=str(clip.get("url") or "").strip()
        if not url:continue
        con=db();existing=con.execute("SELECT id FROM artifacts WHERE job_id=? AND agent='AI Media Finisher' AND kind='video' AND url=?",(job_id,url)).fetchone();con.close()
        if existing:
            saved.append(existing["id"]);continue
        title=f"Short clip {idx:02d} · Shorts/Reels"
        aid=save_artifact("AI Media Finisher","video",title,job_id=job_id,url=url,mime_type="video/mp4",
                          meta={"edit_job_id":edit_job_id,"component":"short_render","mode":"shorts_reels",
                                "clip_index":idx,"start_sec":clip.get("start_sec"),"end_sec":clip.get("end_sec"),
                                "human_approval_required":True})
        saved.append(aid)
    return saved

def _record_media_finisher_qa_handoff(item,artifact_ids,report):
    artifact_ids=[x for x in (artifact_ids or []) if x]
    if not artifact_ids:return None
    con=db();existing=con.execute("""SELECT id FROM artifacts WHERE job_id=? AND agent='QA Agent'
                                    AND meta_json LIKE ? LIMIT 1""",(item["production_job_id"],f'%"edit_job_id": "{item["id"]}"%')).fetchone()
    if existing:
        con.close();return existing["id"]
    rows=[dict(x) for x in con.execute("SELECT id,agent,title FROM artifacts WHERE id IN ("+",".join("?" for _ in artifact_ids)+")",artifact_ids).fetchall()]
    con.close()
    run_id=start_agent_run("QA Agent",item["production_job_id"],"qa","deterministic-v4.5")
    attach_run_inputs(run_id,rows)
    safe=(report or {}).get("safe_zone_report") or {}
    violations=safe.get("violations") if isinstance(safe,dict) else []
    summary=(report or {}).get("edit_summary") or {}
    qa={
      "decision":"human_review_required",
      "safe_zone_violations":len(violations or []),
      "caption_events":len((report or {}).get("caption_timeline") or []),
      "graphics_events":len((report or {}).get("graphics_timeline") or []),
      "short_clips":len((((report or {}).get("shorts_manifest") or {}).get("clips") or [])),
      "duration_before_sec":summary.get("duration_before_sec"),"duration_after_sec":summary.get("duration_after_sec"),
      "checks":["final media exists","edit evidence persisted","safe-zone report recorded","human approval remains required"]
    }
    aid=save_artifact("QA Agent","analysis","Media Finisher QA gate",json.dumps(qa,ensure_ascii=False,indent=2),
                      job_id=item["production_job_id"],run_id=run_id,
                      meta={"edit_job_id":item["id"],"component":"media_finisher_qa","mode":"deterministic","decision":"human_review_required"})
    finish_agent_run(run_id,"completed",meta={"edit_job_id":item["id"],"decision":"human_review_required"})
    event(item["production_job_id"],f"QA Agent received Media Finisher outputs: {item['id'][:8]} → Approval Studio")
    return aid

def _manual_raw_transcript(report):
    report=report if isinstance(report,dict) else {}
    words=[]
    for item in report.get("transcript_words") or []:
        if isinstance(item,dict):
            token=str(item.get("word") or item.get("text") or "").strip()
            if token:words.append(token)
    if words:return " ".join(words).strip()
    groups=[]
    for item in report.get("caption_timeline") or []:
        if not isinstance(item,dict):continue
        raw=item.get("words")
        if isinstance(raw,list):
            text=" ".join(str(x).strip() for x in raw if str(x).strip())
        else:
            text=str(item.get("text") or "").strip()
        if text:groups.append(text)
    return " ".join(groups).strip()

def _ensure_manual_raw_publish_package(edit_job_id):
    edit=get_edit_job(edit_job_id)
    if not edit:return None
    req=edit.get("request") or {}
    if str(req.get("package_mode") or "")!="manual_raw_upload":return get_content_package(edit["production_job_id"]).get("package_record")
    job_id=edit["production_job_id"];job=get_job(job_id)
    if not job:return None
    existing=get_content_package(job_id).get("package_record")
    selected=_selected_production_variant(job_id)
    if existing and existing.get("status")=="ready" and selected:return existing
    if existing or selected:
        event(job_id,"Manual raw-media auto publish pack skipped because this job already has partial production state")
        return existing
    report=edit.get("report") or {}
    script=_manual_raw_transcript(report)
    if not script:
        script=(job.get("brief") or job.get("title") or "Manual uploaded video").strip()
    words=script.split();hook=" ".join(words[:18]).strip()
    summary=report.get("edit_summary") if isinstance(report.get("edit_summary"),dict) else {}
    duration=float(summary.get("duration_after_sec") or edit.get("measured_duration_sec") or _package_duration_seconds(script) or 6)
    duration=max(1.0,duration)
    title=(job.get("title") or "Manual uploaded video").strip()
    description=(job.get("brief") or "").strip() or (script[:280].strip()+("…" if len(script)>280 else ""))
    batch_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{edit_job_id}:manual-raw-batch"))
    variant_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{edit_job_id}:manual-raw-variant"))
    package_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{edit_job_id}:manual-raw-package"))
    now=ts()
    fact_check={"status":"source_only","findings":[],
                "verification_notes":"Manual uploaded media: spoken claims were not independently verified by FactoryOS."}
    qa={"decision":"human_review_required","findings":[],
        "reason":"Manual raw-media publish pack preserves uploaded content and requires owner review before publishing."}
    provenance={"mode":"manual_raw_upload","edit_job_id":edit_job_id,
                "input_artifact_id":edit.get("input_artifact_id"),"source":"owner_uploaded_media"}
    payload={
      "schema_version":CONTENT_PACKAGE_SCHEMA_VERSION,"package_id":package_id,"job_id":job_id,"variant_id":variant_id,
      "_factoryos_manual_raw":True,"source_mode":"manual_raw_upload",
      "final_script":script,"hook":hook,
      "scenes":[{"scene":1,"start_sec":0.0,"end_sec":round(duration,2),"narration":script,
                 "visual":"Existing uploaded video — preserve the approved edit.","on_screen_text":""}],
      "voice_over":script,"subtitles_srt":_build_srt(script,duration),
      "title":title,"description":description,"cta":"","hashtags":[],
      "thumbnail_concept":{"mode":"owner_review","note":"No automatic thumbnail claim generated for manual raw media."},
      "media_brief":{"mode":"existing_video","edit_job_id":edit_job_id,"do_not_replace_media":True,
                     "platform":edit.get("platform") or "reels"},
      "source_list":[{"type":"uploaded_media","artifact_id":edit.get("input_artifact_id"),"edit_job_id":edit_job_id}],
      "fact_check_report":fact_check,"structured_qa":qa,
      "estimated_duration_sec":round(duration,2),
      "production_cost":{"package_generation_usd":0.0,
                         "media_finisher_usd":round(float(edit.get("measured_cost_usd") or 0),6),
                         "job_total_measured_usd":round(get_job_cost(job_id)+float(edit.get("measured_cost_usd") or 0),6)},
    }
    con=db()
    current=con.execute("SELECT id FROM content_packages WHERE job_id=? AND status='ready' ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone()
    selected_row=con.execute("SELECT id FROM production_variants WHERE job_id=? AND status='selected' ORDER BY updated_at DESC LIMIT 1",(job_id,)).fetchone()
    if current or selected_row:
        row=con.execute("SELECT * FROM content_packages WHERE id=?",(current["id"],)).fetchone() if current else None
        con.close()
        return _content_package_dict(row)
    con.execute("""INSERT OR IGNORE INTO production_variants(
        id,batch_id,job_id,ordinal,status,angle,angle_reason,hook,hook_rationale,script,optimized_hook,edited_script,
        fact_check_json,qa_json,decision_reason,allocated_cost_usd,provenance_json,created_at,updated_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        variant_id,batch_id,job_id,1,"selected","Manual uploaded video","Owner-provided source media",
        hook,"Opening words from the uploaded-media transcript",script,hook,script,
        json.dumps(fact_check,ensure_ascii=False),json.dumps(qa,ensure_ascii=False),
        "Manual raw-media publish pack",0.0,json.dumps(provenance,ensure_ascii=False),now,now
    ))
    con.execute("""INSERT OR IGNORE INTO content_packages(
        id,job_id,variant_id,status,package_json,srt_text,generation_cost_usd,created_at,updated_at
    ) VALUES(?,?,?,'ready',?,?,0,?,?)""",(
        package_id,job_id,variant_id,json.dumps(payload,ensure_ascii=False,default=str),payload["subtitles_srt"],now,now
    ))
    con.commit();row=con.execute("SELECT * FROM content_packages WHERE id=?",(package_id,)).fetchone();con.close()
    if row:
        _save_package_artifacts(job_id,None,package_id,payload)
        event(job_id,f"Manual raw-media publish pack created: {package_id[:8]} · no LLM spend · owner review required")
        return _content_package_dict(row)
    return get_content_package(job_id).get("package_record")

def _finalize_edit_job(edit_job_id,status,output_url="",provider_job_id="",error="",response=None,report=None,measured_cost_usd=0.0,measured_duration_sec=0.0):
    item=get_edit_job(edit_job_id)
    if not item:raise ValueError("Edit job not found")
    output_url=str(output_url or item.get("output_url") or "").strip()
    status=_normalize_edit_status(status,output_url)
    now=ts();report=report if isinstance(report,dict) else item.get("report") or {}
    response=response if isinstance(response,dict) else item.get("response") or {}
    completed=now if status in ("ready","failed") else None
    con=db();con.execute("""UPDATE edit_jobs SET provider_job_id=COALESCE(NULLIF(?,''),provider_job_id),status=?,output_url=?,
                           error=?,response_json=?,report_json=?,measured_cost_usd=?,measured_duration_sec=?,updated_at=?,completed_at=?
                           WHERE id=?""",(provider_job_id,status,output_url,str(error or ""),json.dumps(response,ensure_ascii=False,default=str),json.dumps(report,ensure_ascii=False,default=str),max(0,float(measured_cost_usd or 0)),max(0,float(measured_duration_sec or 0)),now,completed,edit_job_id));con.commit();con.close()
    if status=="ready":
        if not output_url:raise RuntimeError("Ready Media Finisher job requires a final output URL")
        output_artifact_id=_persist_edit_evidence(edit_job_id,item["production_job_id"],item["profile_id"],item["profile_version"],report,output_url)
        short_artifact_ids=_persist_short_video_artifacts(edit_job_id,item["production_job_id"],report)
        _record_media_finisher_qa_handoff(item,[output_artifact_id,*short_artifact_ids],report)
        _ensure_manual_raw_publish_package(edit_job_id)
        con=db();con.execute("UPDATE edit_jobs SET output_artifact_id=? WHERE id=?",(output_artifact_id,edit_job_id))
        job=con.execute("SELECT status FROM jobs WHERE id=?",(item["production_job_id"],)).fetchone()
        if job and job["status"] not in ("approved","publishing","done"):
            con.execute("UPDATE jobs SET stage='qa',status='waiting_approval',progress=75,updated_at=? WHERE id=?",(ts(),item["production_job_id"]))
        con.commit();con.close()
        _queue_durable_media_archive(edit_job_id)
        event(item["production_job_id"],f"AI Media Finisher ready: {edit_job_id[:8]} → durable media check → human review")
    elif status=="failed":
        event(item["production_job_id"],f"AI Media Finisher failed: {edit_job_id[:8]} — {str(error or 'provider failure')[:240]}")
    return get_edit_job(edit_job_id)

MEDIA_FINISHER_SUBMIT_RETRIES=max(1,min(8,int(os.environ.get("FACTORY_MEDIA_FINISHER_SUBMIT_RETRIES","5"))))
_media_finisher_submit_active=set()
_media_finisher_submit_lock=threading.Lock()

def _set_media_finisher_submit_progress(edit_job_id,stage="waking_worker",percent=1,attempt=1,last_error=""):
    item=get_edit_job(edit_job_id)
    if not item:return None
    response=dict(item.get("response") or {})
    response.update({"status":"queued","stage":stage,"percent":max(1,min(9,int(percent))),"submit_attempt":int(attempt)})
    if last_error:response["last_submit_error"]=str(last_error)[:500]
    con=db();con.execute("""UPDATE edit_jobs SET status='queued',error='',response_json=?,updated_at=? WHERE id=?""",
                         (json.dumps(response,ensure_ascii=False,default=str),ts(),edit_job_id));con.commit();con.close()
    return get_edit_job(edit_job_id)

def _submit_media_finisher_background(edit_job_id):
    with _media_finisher_submit_lock:
        if edit_job_id in _media_finisher_submit_active:return
        _media_finisher_submit_active.add(edit_job_id)
    try:
        item=get_edit_job(edit_job_id)
        if not item or item.get("status") in ("ready","failed") or item.get("provider_job_id"):return
        submit_endpoint=_media_finisher_submit_endpoint()
        if not submit_endpoint:
            _finalize_edit_job(edit_job_id,"failed",error="Media Finisher provider is not configured",response={"stage":"submit","percent":1})
            return
        payload=item.get("request") or {}
        retry_delays=[0,3,6,12,20,30,45,60]
        last_error=""
        for attempt in range(1,MEDIA_FINISHER_SUBMIT_RETRIES+1):
            _set_media_finisher_submit_progress(edit_job_id,"waking_worker",min(8,attempt+1),attempt,last_error)
            if attempt>1:time.sleep(retry_delays[min(attempt-1,len(retry_delays)-1)])
            try:
                result=_external_json(submit_endpoint,"POST",payload,FACTORY_MEDIA_FINISHER_TOKEN)
            except Exception as exc:
                last_error=str(exc)
                event(item["production_job_id"],f"AI Media Finisher worker wake/submit retry {attempt}/{MEDIA_FINISHER_SUBMIT_RETRIES}: {last_error[:180]}")
                if attempt<MEDIA_FINISHER_SUBMIT_RETRIES:
                    continue
                _finalize_edit_job(edit_job_id,"failed",error=f"Worker did not become ready after {attempt} attempts: {last_error}",
                                   response={"status":"failed","stage":"submit","percent":1,"submit_attempt":attempt,"exception":last_error})
                return
            output_url=str(result.get("final_url") or result.get("output_url") or result.get("url") or "").strip()
            provider_job_id=str(result.get("id") or result.get("job_id") or result.get("task_id") or edit_job_id).strip()
            status=_normalize_edit_status(result.get("status"),output_url)
            report=result.get("report") if isinstance(result.get("report"),dict) else {}
            done=_finalize_edit_job(edit_job_id,status,output_url,provider_job_id,str(result.get("error") or ""),result,report,
                                    float(result.get("cost_usd") or 0),float(result.get("duration_sec") or 0))
            event(item["production_job_id"],f"AI Media Finisher worker accepted: {edit_job_id[:8]} · status {done['status']}")
            return
    finally:
        with _media_finisher_submit_lock:_media_finisher_submit_active.discard(edit_job_id)

def _spawn_media_finisher_submit(edit_job_id):
    threading.Thread(target=_submit_media_finisher_background,args=(edit_job_id,),daemon=True,name=f"finisher-submit-{edit_job_id[:8]}").start()

def start_media_finisher(job_id,payload,parent_edit_job_id=None,rerun_stage=""):
    job=get_job(job_id)
    if not job:raise ValueError("Job not found")
    if not payload.edit_full_video and not payload.split_shortform:
        raise ValueError("Select full-video editing, Shorts/Reels splitting, or both")
    profile=get_edit_profile(payload.profile_id,payload.profile_version)
    if not profile or not profile.get("active"):raise ValueError("Unknown or inactive Media Finisher profile/version")
    input_url,input_artifact_id,media_job_id=_resolve_finisher_input(job_id,payload.input_url,payload.media_job_id)
    package_record=get_content_package(job_id).get("package_record")
    manual_raw_upload=False
    if input_artifact_id:
        con=db();raw_row=con.execute("SELECT agent,title,meta_json FROM artifacts WHERE id=? AND job_id=?",(input_artifact_id,job_id)).fetchone();con.close()
        raw_meta=_decode_json(raw_row["meta_json"],{}) if raw_row else {}
        manual_raw_upload=bool(raw_row and raw_row["agent"]=="AI Media Finisher" and raw_meta.get("component")=="raw_upload")
    if package_record and package_record.get("status")=="ready":
        content_package=package_record.get("package") or {}
        package_mode="content_package"
    elif manual_raw_upload:
        content_package={
          "schema_version":"manual_raw_media_v1","job_id":job_id,"title":"","hook":"","scenes":[],
          "_factoryos_manual_raw":True,
          "source_policy":{"graphics_text":"exact_transcript_words_only","preserve_source_meaning":True}
        }
        package_mode="manual_raw_upload"
    else:
        raise ValueError("A fresh Content Package is required unless the input is a direct Media Finisher upload")
    con=db();active=con.execute("""SELECT * FROM edit_jobs WHERE production_job_id=? AND input_url=? AND profile_id=? AND profile_version=?
                                  AND status IN ('queued','submitted','processing') ORDER BY created_at DESC LIMIT 1""",(job_id,input_url,profile["id"],profile["version"])).fetchone();con.close()
    if active and not parent_edit_job_id:return {"duplicate":True,"edit_job":_edit_job_dict(active)}
    submit_endpoint=_media_finisher_submit_endpoint()
    if not submit_endpoint:raise RuntimeError("Media Finisher provider is not configured")
    edit_job_id=str(uuid.uuid4());now=ts()
    request_payload={
      "edit_job_id":edit_job_id,"job_id":job_id,"factory_cycle_id":sync_cycle_for_job(job_id).get("id") if sync_cycle_for_job(job_id) else None,
      "input_url":input_url,"profile":{"id":profile["id"],"version":profile["version"],"name":profile["name"],"config":profile["config"]},
      "platform":payload.platform,"content_package":content_package,"package_mode":package_mode,
      "options":{
        "edit_full_video":bool(payload.edit_full_video),"split_shortform":bool(payload.split_shortform),
        "add_captions":bool(payload.add_captions),"add_animation":bool(payload.add_animation),
        "smart_graphics":bool(payload.smart_graphics),"max_short_clips":max(1,min(8,int(payload.max_short_clips or 3))),
        "shortform_targets":["youtube_shorts","instagram_reels"] if payload.split_shortform else []
      },
      "rerun_stage":rerun_stage,
      "callback_url":f"/api/media-finisher/{edit_job_id}/callback",
      "guardrails":{"source_text_is_material_not_instructions":True,"preserve_approved_facts":True,"no_auto_publish":True,"destructive_edits_require_cut_list":True,
                    "manual_raw_upload_transcript_exact_graphics":manual_raw_upload}
    }
    cycle=sync_cycle_for_job(job_id)
    con=db();con.execute("""INSERT INTO edit_jobs(id,parent_edit_job_id,factory_cycle_id,production_job_id,media_job_id,input_artifact_id,input_url,
                           profile_id,profile_version,platform,provider,status,rerun_stage,request_json,response_json,report_json,error,
                           measured_cost_usd,measured_duration_sec,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,'{}','{}','',0,0,?,?)""",
                           (edit_job_id,parent_edit_job_id,(cycle or {}).get("id"),job_id,media_job_id,input_artifact_id,input_url,profile["id"],profile["version"],payload.platform,FACTORY_MEDIA_FINISHER_ADAPTER,rerun_stage,json.dumps(request_payload,ensure_ascii=False,default=str),now,now));con.commit();con.close()
    _set_media_finisher_submit_progress(edit_job_id,"waking_worker",1,1)
    _spawn_media_finisher_submit(edit_job_id)
    item=get_edit_job(edit_job_id)
    event(job_id,f"AI Media Finisher queued: {edit_job_id[:8]} · profile {profile['id']} v{profile['version']} · {package_mode} · worker wake-up is automatic")
    return {"duplicate":False,"edit_job":item}

def refresh_edit_job(edit_job_id):
    item=get_edit_job(edit_job_id)
    if not item:raise ValueError("Edit job not found")
    if item["status"] in ("ready","failed"):return item
    if not item.get("provider_job_id"):
        if item.get("status") in ("queued","submitted","processing"):return item
        raise RuntimeError("Media Finisher provider job id is not available yet")
    status_base=_media_finisher_status_base()
    if not status_base:raise RuntimeError("Media Finisher status endpoint is not configured")
    endpoint=status_base.rstrip("/")+"/"+urlparse.quote(item["provider_job_id"],safe="")
    try:
        result=_external_json(endpoint,"GET",None,FACTORY_MEDIA_FINISHER_TOKEN)
    except urlerror.HTTPError as exc:
        if int(getattr(exc,"code",0) or 0)==404:
            response=dict(item.get("response") or {})
            response.update({"status":"queued","stage":"waking_worker","percent":max(1,int(response.get("percent") or 1)),
                             "recovered_after_worker_restart":True})
            con=db();con.execute("""UPDATE edit_jobs SET provider_job_id='',status='queued',error='',response_json=?,updated_at=? WHERE id=?""",
                                 (json.dumps(response,ensure_ascii=False,default=str),ts(),edit_job_id));con.commit();con.close()
            event(item["production_job_id"],f"AI Media Finisher worker state was lost after restart; auto-resubmitting {edit_job_id[:8]}")
            _spawn_media_finisher_submit(edit_job_id)
            return get_edit_job(edit_job_id)
        raise
    except (TimeoutError,urlerror.URLError):
        return item
    output_url=str(result.get("final_url") or result.get("output_url") or result.get("url") or "").strip()
    report=result.get("report") if isinstance(result.get("report"),dict) else {}
    return _finalize_edit_job(edit_job_id,result.get("status"),output_url,str(result.get("id") or result.get("job_id") or item.get("provider_job_id") or ""),str(result.get("error") or ""),result,report,float(result.get("cost_usd") or item.get("measured_cost_usd") or 0),float(result.get("duration_sec") or item.get("measured_duration_sec") or 0))

def rerun_media_finisher_stage(edit_job_id,stage):
    allowed={"transcript","cleanup","captions","motion","graphics","audio","safe_zone","render"}
    stage=str(stage or "").strip().lower()
    if stage not in allowed:raise ValueError("Unknown Media Finisher stage")
    original=get_edit_job(edit_job_id)
    if not original:raise ValueError("Edit job not found")
    opts=(original.get("request") or {}).get("options") or {}
    payload=MediaFinisherStartRequest(profile_id=original["profile_id"],profile_version=original["profile_version"],platform=original["platform"],input_url=original["input_url"],
                                      edit_full_video=bool(opts.get("edit_full_video",True)),split_shortform=bool(opts.get("split_shortform",False)),
                                      add_captions=bool(opts.get("add_captions",True)),add_animation=bool(opts.get("add_animation",True)),
                                      smart_graphics=bool(opts.get("smart_graphics",True)),max_short_clips=int(opts.get("max_short_clips") or 3),
                                      confirm_external_cost=True)
    return start_media_finisher(original["production_job_id"],payload,parent_edit_job_id=edit_job_id,rerun_stage=stage)

def get_media_finisher_pilot(tag=None):
    tag=(tag if tag is not None else FACTORY_MEDIA_FINISHER_PILOT_TAG).strip()
    if not tag:
        return {"tag":"","status":"disabled","job_id":None,"edit_job_id":None,"output_url":"","approval_gate_reached":False}
    row=get_paid_verification(tag)
    detail=_decode_json(row.get("detail") or "{}",{}) if row else {}
    return {
        "tag":tag,"status":row.get("status","pending"),"job_id":row.get("job_id") or detail.get("job_id"),
        "edit_job_id":detail.get("edit_job_id"),"output_url":detail.get("output_url") or "",
        "approval_gate_reached":bool(detail.get("approval_gate_reached")),
        "evidence_kinds":detail.get("evidence_kinds") or [],
        "duration_before_sec":detail.get("duration_before_sec"),
        "duration_after_sec":detail.get("duration_after_sec"),
        "removed_segments":detail.get("removed_segments"),
        "caption_events":detail.get("caption_events"),
        "error":detail.get("error"),
    }

def _seed_media_finisher_pilot_job(tag,source_url):
    now=ts()
    job_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{tag}:job"))
    variant_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{tag}:variant"))
    batch_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{tag}:batch"))
    package_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:{tag}:package"))
    script="FactoryOS finds the pauses. Then it cuts the dead air, adds captions, and sends the finished video back for human approval."
    con=db()
    existing=con.execute("SELECT id FROM jobs WHERE id=?",(job_id,)).fetchone()
    if not existing:
        con.execute("""INSERT INTO jobs(id,title,brief,stage,presenter,format,language,outputs,status,progress,created_at,updated_at)
                       VALUES(?,?,?,'render','Faceless','Short only','English',1,'idle',65,?,?)""",
                    (job_id,"v4.5 AI Media Finisher real pilot",
                     "Controlled zero-publish runtime proof for FFmpeg + Whisper + Remotion finishing.",now,now))
        con.execute("""INSERT INTO production_variants(
            id,batch_id,job_id,ordinal,status,angle,angle_reason,hook,hook_rationale,script,optimized_hook,edited_script,
            fact_check_json,qa_json,decision_reason,allocated_cost_usd,provenance_json,created_at,updated_at
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
            variant_id,batch_id,job_id,1,"selected","Show the deterministic edit pipeline",
            "Controlled runtime proof","Watch dead air become a finished short.","Original pilot hook",script,
            "Watch dead air become a finished short.",script,
            json.dumps({"findings":[],"fact_summary":"Synthetic FactoryOS pilot contains no external factual claims."}),
            json.dumps({"decision":"keep","reason":"Controlled integration fixture","findings":[]}),
            "Controlled v4.5 integration fixture.",0.0,json.dumps({"mode":"v4.5_real_pilot","tag":tag}),now,now
        ))
        package={
            "schema_version":CONTENT_PACKAGE_SCHEMA_VERSION,"package_id":package_id,"job_id":job_id,"variant_id":variant_id,
            "variant_batch_id":batch_id,"final_script":script,"hook":"Watch dead air become a finished short.",
            "scenes":[
                {"scene":1,"narration":"FactoryOS finds the pauses.","visual":"Raw vertical pilot source.","on_screen_text":"FIND THE PAUSE","duration_sec":3},
                {"scene":2,"narration":"Then it cuts the dead air and adds captions.","visual":"Show the edit transformation.","on_screen_text":"CUT → CAPTION","duration_sec":5},
                {"scene":3,"narration":"And sends the finished video back for human approval.","visual":"Show approval boundary.","on_screen_text":"HUMAN APPROVAL","duration_sec":4}
            ],
            "voice_over":script,"subtitles_srt":"","title":"FactoryOS AI Media Finisher pilot",
            "description":"Controlled integration proof for the v4.5 deterministic editing pipeline.",
            "cta":"Human review before publish.","hashtags":["#FactoryOS","#AIVideo"],
            "thumbnail_concept":{"headline":"AI MEDIA FINISHER","composition":"9:16 safe"},
            "media_brief":{"format":"vertical short-form","aspect_ratio":"9:16","style":"clean deterministic pilot"},
            "source_list":[{"type":"pilot_fixture","value":source_url}],
            "fact_check_report":{"findings":[]},"structured_qa":{"decision":"keep","findings":[]},
            "estimated_duration_sec":12,
            "production_cost":{"package_generation_usd":0.0,"selected_variant_allocated_usd":0.0,"job_total_measured_usd":0.0},
            "provider_adapters":get_media_adapter_registry(),
            "provenance":{"mode":"v4.5_real_pilot","tag":tag,"generated_at":now}
        }
        con.execute("""INSERT INTO content_packages(id,job_id,variant_id,status,package_json,srt_text,generation_cost_usd,created_at,updated_at)
                       VALUES(?,?,?,'ready',?,'',0,?,?)""",(package_id,job_id,variant_id,json.dumps(package,ensure_ascii=False),now,now))
        con.commit();con.close()
        save_artifact("Render Agent","video","v4.5 pilot raw vertical source","",job_id=job_id,url=source_url,mime_type="video/mp4",
                      meta={"mode":"v4.5_real_pilot","tag":tag,"component":"raw_media"})
        _save_package_artifacts(job_id,None,package_id,package)
        event(job_id,"v4.5 Media Finisher real pilot fixture created; no publish action allowed")
    else:
        con.close()
    return job_id

async def run_media_finisher_pilot_once():
    tag=FACTORY_MEDIA_FINISHER_PILOT_TAG
    source_url=FACTORY_MEDIA_FINISHER_PILOT_SOURCE_URL
    if not tag or not source_url or not FACTORY_MEDIA_FINISHER_ENDPOINT:
        return
    con=db();existing=con.execute("SELECT * FROM system_verifications WHERE tag=?",(tag,)).fetchone();con.close()
    if existing and existing["status"] in ("passed","failed"):
        print(json.dumps({"event":"V45_MEDIA_FINISHER_PILOT","tag":tag,"status":"skip_existing","existing_status":existing["status"]}),flush=True)
        return
    started=existing["started_at"] if existing else ts()
    if not existing:
        con=db();con.execute("""INSERT INTO system_verifications(tag,status,started_at,detail)
                               VALUES(?,?,?,?)""",(tag,"started",started,json.dumps({
                                   "phase":"fenced","source_url":source_url,"approval_gate_reached":False
                               })));con.commit();con.close()
    job_id=None;edit_job_id=None
    try:
        job_id=_seed_media_finisher_pilot_job(tag,source_url)
        old=get_paid_verification(tag);detail=_decode_json(old.get("detail") or "{}",{})
        edit_job_id=detail.get("edit_job_id")
        if not edit_job_id:
            result=await asyncio.to_thread(start_media_finisher,job_id,MediaFinisherStartRequest(
                profile_id="talking_head_fast",profile_version=1,platform="reels",
                input_url=source_url,confirm_external_cost=True
            ))
            edit_job_id=result["edit_job"]["id"]
            detail.update({"phase":"processing","job_id":job_id,"edit_job_id":edit_job_id,"source_url":source_url})
            _verification_update(tag,{"job_id":job_id,"detail":json.dumps(detail,ensure_ascii=False)})
            print(json.dumps({"event":"V45_MEDIA_FINISHER_PILOT","tag":tag,"status":"submitted","job_id":job_id,"edit_job_id":edit_job_id}),flush=True)
        deadline=time.monotonic()+1800
        while time.monotonic()<deadline:
            current=get_edit_job(edit_job_id)
            if not current:raise RuntimeError("Pilot edit job disappeared")
            if current["status"] in ("ready","failed"):break
            try:
                current=await asyncio.to_thread(refresh_edit_job,edit_job_id)
            except Exception as exc:
                print(json.dumps({"event":"V45_MEDIA_FINISHER_PILOT","tag":tag,"status":"poll_retry","error":str(exc)[:300]}),flush=True)
            if current.get("status") in ("ready","failed"):break
            await asyncio.sleep(10)
        current=get_edit_job(edit_job_id)
        if not current or current.get("status")!="ready":
            raise RuntimeError("Media Finisher pilot did not reach ready: "+str((current or {}).get("error") or (current or {}).get("status") or "timeout"))
        report=current.get("report") or {};summary=report.get("edit_summary") or {}
        evidence_kinds=sorted({x.get("kind") for x in current.get("artifacts") or [] if x.get("kind")})
        job=get_job(job_id)
        con=db()
        publish_count=int(con.execute("SELECT COUNT(*) c FROM publishing_queue WHERE job_id=?",(job_id,)).fetchone()["c"] or 0)
        fin_art=con.execute("""SELECT id,url FROM artifacts WHERE job_id=? AND agent='AI Media Finisher' AND kind='video'
                              ORDER BY created_at DESC LIMIT 1""",(job_id,)).fetchone()
        con.close()
        required={"transcript_words","cut_list","caption_timeline","audio_report","safe_zone_report","edit_summary"}
        approval_gate=bool(job and job.get("status")=="waiting_approval")
        passed=bool(required.issubset(set(evidence_kinds)) and fin_art and fin_art["url"] and approval_gate and publish_count==0)
        detail={
            "phase":"waiting_approval" if approval_gate else "verification_failed","job_id":job_id,"edit_job_id":edit_job_id,
            "source_url":source_url,"output_url":current.get("output_url") or "","approval_gate_reached":approval_gate,
            "publish_count":publish_count,"evidence_kinds":evidence_kinds,
            "duration_before_sec":summary.get("duration_before_sec"),"duration_after_sec":summary.get("duration_after_sec"),
            "removed_segments":summary.get("removed_segments"),"removed_seconds":summary.get("removed_seconds"),
            "caption_events":len(report.get("caption_timeline") or []),
            "graphics_engine":summary.get("graphics_engine"),"safe_zone_method":(report.get("safe_zone_report") or {}).get("method"),
            "human_visual_review_required":True
        }
        status="passed" if passed else "failed"
        if not passed:detail["error"]="Required evidence, final video, zero-publish boundary or waiting_approval gate missing"
        _verification_update(tag,{"status":status,"job_id":job_id,"finished_at":ts(),"detail":json.dumps(detail,ensure_ascii=False)})
        print(json.dumps({"event":"V45_MEDIA_FINISHER_PILOT","tag":tag,"status":status,**{k:detail.get(k) for k in ("job_id","edit_job_id","output_url","approval_gate_reached","duration_before_sec","duration_after_sec","removed_segments","caption_events","graphics_engine")}},ensure_ascii=False),flush=True)
    except Exception as exc:
        old=get_paid_verification(tag);detail=_decode_json(old.get("detail") or "{}",{})
        detail.update({"phase":"failed","job_id":job_id or detail.get("job_id"),"edit_job_id":edit_job_id or detail.get("edit_job_id"),
                       "approval_gate_reached":False,"error":str(exc)[:1200]})
        _verification_update(tag,{"status":"failed","job_id":job_id or detail.get("job_id"),"finished_at":ts(),"detail":json.dumps(detail,ensure_ascii=False)})
        print(json.dumps({"event":"V45_MEDIA_FINISHER_PILOT","tag":tag,"status":"failed","job_id":job_id,"edit_job_id":edit_job_id,"error":str(exc)[:700]}),flush=True)


def get_revideo_adapter_registry():
    return {
        "transcript":{"selected":FACTORY_TRANSCRIPT_ADAPTER,"configured":bool(FACTORY_TRANSCRIPT_ENDPOINT),
                      "manual_supported":True,"endpoint_configured":bool(FACTORY_TRANSCRIPT_ENDPOINT)},
        "video":{"selected":FACTORY_MEDIA_ADAPTERS.get("video") or None,"configured":bool(FACTORY_VIDEO_ENDPOINT),
                 "endpoint_configured":bool(FACTORY_VIDEO_ENDPOINT),
                 "async_jobs":True,"status_endpoint_configured":bool(FACTORY_VIDEO_STATUS_ENDPOINT)},
        "note":"Provider endpoints/tokens come from environment variables and are never exposed in this response."
    }

def render_revideo_media(project_id):
    project=get_revideo_project(project_id)
    if not project:raise ValueError("Revideo project not found")
    if not project.get("job_id"):raise ValueError("Create a production job first")
    package=get_content_package(project["job_id"]).get("package_record")
    if not package or package.get("status")!="ready":raise ValueError("A fresh Content Package is required before video generation")
    if not FACTORY_VIDEO_ENDPOINT:raise RuntimeError("Video provider is not configured")
    payload={"project_id":project_id,"job_id":project["job_id"],"source_url":project["source_url"],
             "content_package":package.get("package") or {},
             "guardrails":{"do_not_reuse_source_media":True,"do_not_imitate_creator_identity_or_voice":True}}
    media_job_id=str(uuid.uuid4());now=ts();provider=FACTORY_MEDIA_ADAPTERS.get("video") or "webhook"
    con=db();con.execute("""INSERT INTO media_jobs(
        id,revideo_project_id,job_id,provider,provider_job_id,status,media_url,error,
        request_json,response_json,created_at,updated_at,completed_at
    ) VALUES(?,?,?,?,?,'queued','','',?,'{}',?,?,NULL)""",
        (media_job_id,project_id,project["job_id"],provider,"",json.dumps(payload,ensure_ascii=False),now,now))
    con.commit();con.close()
    try:
        result=_external_json(FACTORY_VIDEO_ENDPOINT,"POST",payload,FACTORY_VIDEO_TOKEN)
    except Exception as exc:
        _finalize_media_job(media_job_id,"failed",error=str(exc),response={"exception":str(exc)})
        raise
    media_url=str(result.get("url") or result.get("video_url") or result.get("output_url") or "").strip()
    provider_job_id=str(result.get("id") or result.get("job_id") or result.get("task_id") or "").strip()
    status=_normalize_media_status(result.get("status"),media_url)
    item=_finalize_media_job(media_job_id,status,media_url=media_url,response=result,provider_job_id=provider_job_id)
    if item["status"]=="ready":
        event(project["job_id"],f"Video provider returned a ready media artifact for project {project_id}")
    else:
        event(project["job_id"],f"Video provider accepted media job {media_job_id}; status={item['status']}")
    return {"project":get_revideo_project(project_id),"media_job":item}

def refresh_media_job(media_job_id):
    item=get_media_job(media_job_id)
    if not item:raise ValueError("Media job not found")
    if item["status"] in ("ready","failed"):return item
    if not item.get("provider_job_id"):raise RuntimeError("Provider job id is not available yet")
    if not FACTORY_VIDEO_STATUS_ENDPOINT:raise RuntimeError("Video status endpoint is not configured")
    endpoint=FACTORY_VIDEO_STATUS_ENDPOINT.replace("{provider_job_id}",urlparse.quote(item["provider_job_id"],safe=""))
    result=_external_json(endpoint,"GET",None,FACTORY_VIDEO_TOKEN)
    media_url=str(result.get("url") or result.get("video_url") or result.get("output_url") or "").strip()
    provider_job_id=str(result.get("id") or result.get("job_id") or result.get("task_id") or item["provider_job_id"]).strip()
    status=_normalize_media_status(result.get("status"),media_url)
    return _finalize_media_job(media_job_id,status,media_url=media_url,error=str(result.get("error") or ""),
                               response=result,provider_job_id=provider_job_id)

CONTENT_PACKAGE_SCHEMA_VERSION="1.0"
CONTENT_PACKAGE_REQUIRED_FIELDS=(
    "final_script","hook","scenes","voice_over","subtitles_srt","title","description","cta",
    "hashtags","thumbnail_concept","media_brief","source_list","fact_check_report",
    "estimated_duration_sec","production_cost",
)

def get_media_adapter_registry():
    contracts={
        "tts":{"input":["voice_over","language","delivery_notes"],"output":["audio"],"status":"configured" if FACTORY_MEDIA_ADAPTERS["tts"] else "not_configured"},
        "image":{"input":["scene_prompt","aspect_ratio","style"],"output":["image"],"status":"configured" if FACTORY_MEDIA_ADAPTERS["image"] else "not_configured"},
        "video":{"input":["scene","audio","captions","assets"],"output":["video"],"status":"configured" if (FACTORY_MEDIA_ADAPTERS["video"] and FACTORY_VIDEO_ENDPOINT) else "not_configured"},
        "stock":{"input":["query","duration","orientation"],"output":["stock_asset"],"status":"configured" if FACTORY_MEDIA_ADAPTERS["stock"] else "not_configured"},
        "manual":{"input":["uploaded_media"],"output":["media_asset"],"status":"ready"},
    }
    out=[]
    for kind,spec in contracts.items():
        provider="manual" if kind=="manual" else FACTORY_MEDIA_ADAPTERS.get(kind,"")
        out.append({
            "kind":kind,"provider":provider or None,"configured":spec["status"] in ("configured","ready"),
            "status":spec["status"],"contract":{"input":spec["input"],"output":spec["output"]},
            "execution":("webhook_provider" if kind=="video" and FACTORY_VIDEO_ENDPOINT else "adapter_interface_only") if kind!="manual" else "manual_asset_path",
        })
    return {
        "contract_version":"1.0",
        "adapters":out,
        "note":"Provider names are environment configuration, not hardcoded business logic. Secrets are not exposed by this registry.",
    }

def _selected_production_variant(job_id):
    data=get_job_variants(job_id)
    return next((x for x in data.get("variants",[]) if x.get("status")=="selected"),None)

def _content_package_sources(job_id,variant):
    con=db()
    rows=[dict(x) for x in con.execute(
        """SELECT id,agent,title,content,url,created_at FROM artifacts
           WHERE job_id=? AND agent IN ('Researcher','Tech Verifier')
           ORDER BY created_at DESC LIMIT 8""",(job_id,)
    ).fetchall()]
    con.close()
    urls=[];refs=[];notes=[]
    for row in rows:
        refs.append({"artifact_id":row["id"],"agent":row["agent"],"title":row["title"],"created_at":row["created_at"]})
        candidates=[]
        if row.get("url"):candidates.append(row["url"])
        candidates.extend(re.findall(r"https?://[^\s<>\"']+",row.get("content") or ""))
        for url in candidates:
            clean=url.rstrip(".,;:!?")
            if clean and clean not in urls:urls.append(clean)
    for finding in (variant.get("fact_check") or {}).get("findings") or []:
        evidence=str(finding.get("evidence") or "").strip()
        if evidence and evidence not in notes:notes.append(evidence)
    source_list=[]
    source_list.extend({"type":"url","value":x} for x in urls)
    source_list.extend({"type":"artifact","artifact_id":x["artifact_id"],"agent":x["agent"],"title":x["title"],"created_at":x["created_at"]} for x in refs)
    source_list.extend({"type":"fact_evidence","value":x} for x in notes)
    return source_list

def _package_duration_seconds(text):
    words=len(re.findall(r"\S+",text or ""))
    return max(6,int(round(words/2.55))) if words else 6

def _split_package_sentences(text):
    parts=[x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',text or "") if x.strip()]
    return parts or [str(text or "").strip() or "Narration"]

def _demo_package_scenes(script,duration):
    sentences=_split_package_sentences(script)
    target=min(8,max(3,len(sentences)))
    groups=[[] for _ in range(target)]
    for i,sentence in enumerate(sentences):
        groups[min(target-1,int(i*target/max(1,len(sentences))))].append(sentence)
    groups=[x for x in groups if x]
    per=max(1,duration/len(groups));scenes=[];cursor=0.0
    for i,group in enumerate(groups,1):
        narration=" ".join(group).strip()
        end=duration if i==len(groups) else round(cursor+per,1)
        scenes.append({
            "scene":i,"start_sec":round(cursor,1),"end_sec":round(end,1),
            "narration":narration,
            "visual":"Show concrete on-screen evidence or a visual illustration that directly supports this narration without adding new factual claims.",
            "on_screen_text":" ".join(narration.split()[:7]),
        })
        cursor=end
    return scenes

def _srt_time(seconds):
    ms=max(0,int(round(float(seconds or 0)*1000)))
    h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);sec,msec=divmod(rem,1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{msec:03d}"

def _build_srt(voice_over,duration):
    words=(voice_over or "").split()
    if not words:return ""
    chunks=[" ".join(words[i:i+8]) for i in range(0,len(words),8)]
    total=max(float(duration or 1),float(len(chunks))*0.9)
    lines=[];cursor=0.0
    for i,chunk in enumerate(chunks,1):
        frac=len(chunk.split())/max(1,len(words));span=max(0.9,total*frac)
        end=total if i==len(chunks) else min(total,cursor+span)
        lines.extend([str(i),f"{_srt_time(cursor)} --> {_srt_time(end)}",chunk,""])
        cursor=end
    return "\n".join(lines).strip()+"\n"

def _normalize_package_scenes(raw_scenes,voice_over,duration):
    scenes=[]
    raw=[x for x in (raw_scenes or []) if isinstance(x,dict)]
    if not raw:return _demo_package_scenes(voice_over,duration)
    cursor=0.0
    fallback=max(1,float(duration)/max(1,len(raw)))
    for i,item in enumerate(raw[:10],1):
        narration=str(item.get("narration") or item.get("voice_over") or "").strip()
        visual=str(item.get("visual") or item.get("visual_direction") or "").strip()
        onscreen=str(item.get("on_screen_text") or item.get("text") or "").strip()
        span=float(item.get("duration_sec") or fallback)
        end=float(duration) if i==len(raw[:10]) else min(float(duration),cursor+max(0.8,span))
        scenes.append({"scene":i,"start_sec":round(cursor,1),"end_sec":round(end,1),
                       "narration":narration,"visual":visual,"on_screen_text":onscreen})
        cursor=end
    return scenes

def _package_demo_payload(job,variant):
    script=(variant.get("edited_script") or variant.get("script") or "").strip()
    hook=(variant.get("optimized_hook") or variant.get("hook") or "").strip()
    duration=_package_duration_seconds(script)
    title=(job.get("title") or "Untitled short").strip()
    words=[re.sub(r"[^A-Za-z0-9А-Яа-яІіЇїЄє_-]","",x) for x in title.split()]
    tags=["#"+x for x in words if len(x)>=4][:5] or ["#shorts"]
    return {
        "title":title,
        "description":(script[:280].strip()+("…" if len(script)>280 else "")),
        "cta":"Follow for the next verified breakdown.",
        "hashtags":tags,
        "voice_over":script,
        "scenes":_demo_package_scenes(script,duration),
        "thumbnail_concept":{"headline":hook[:70] or title[:70],"visual_direction":"Use one clear subject plus one proof-oriented visual cue; avoid adding unverified claims.","composition":"9:16-safe focal composition"},
        "media_brief":{"format":"vertical short-form","aspect_ratio":"9:16","style":"clear, evidence-led, fast-paced","visual_rules":["Every factual claim should have matching on-screen proof or an explicit qualification.","Keep captions inside mobile safe areas."],"asset_needs":["proof visuals","simple diagrams","supporting B-roll where relevant"]},
    }

def _content_package_dict(row):
    if not row:return None
    item=dict(row);item["package"]=_decode_json(item.pop("package_json","{}"),{})
    item["package"]["subtitles_srt"]=item.get("srt_text") or item["package"].get("subtitles_srt","")
    return item

def get_content_package(job_id):
    if not job_id:return {"job_id":job_id,"status":"missing","package":None,"adapters":get_media_adapter_registry()}
    con=db();row=con.execute("SELECT * FROM content_packages WHERE job_id=? ORDER BY created_at DESC LIMIT 1",(job_id,)).fetchone();con.close()
    item=_content_package_dict(row)
    return {
        "job_id":job_id,
        "status":item.get("status") if item else "missing",
        "building":job_id in package_building,
        "package_record":item,
        "package":item.get("package") if item else None,
        "adapters":get_media_adapter_registry(),
    }

def _mark_content_package_stale(job_id,reason):
    con=db()
    rows=con.execute("SELECT id,package_json FROM content_packages WHERE job_id=? AND status='ready'",(job_id,)).fetchall()
    for row in rows:
        payload=_decode_json(row["package_json"],{})
        payload["stale_reason"]=reason
        con.execute("UPDATE content_packages SET status='stale',package_json=?,updated_at=? WHERE id=?",
                    (json.dumps(payload,ensure_ascii=False),ts(),row["id"]))
    con.commit();con.close()
    return len(rows)

def _save_package_artifacts(job_id,run_id,package_id,payload):
    common={"content_package":True,"package_id":package_id,"variant_id":payload.get("variant_id"),"schema_version":CONTENT_PACKAGE_SCHEMA_VERSION}
    save_artifact("Content Packager","text","Final short-form script",payload.get("final_script",""),job_id=job_id,run_id=run_id,meta={**common,"component":"final_script"})
    save_artifact("Content Packager","text","Voice-over",payload.get("voice_over",""),job_id=job_id,run_id=run_id,meta={**common,"component":"voice_over"})
    save_artifact("Content Packager","text","Subtitles / SRT",payload.get("subtitles_srt",""),job_id=job_id,run_id=run_id,mime_type="application/x-subrip",meta={**common,"component":"srt"})
    save_artifact("Content Packager","json","Scene breakdown",json.dumps(payload.get("scenes") or [],ensure_ascii=False,indent=2),job_id=job_id,run_id=run_id,meta={**common,"component":"scenes"})
    save_artifact("Content Packager","json","Publishing metadata",json.dumps({k:payload.get(k) for k in ("title","description","cta","hashtags")},ensure_ascii=False,indent=2),job_id=job_id,run_id=run_id,meta={**common,"component":"metadata"})
    save_artifact("Content Packager","json","Thumbnail + media brief",json.dumps({"thumbnail_concept":payload.get("thumbnail_concept"),"media_brief":payload.get("media_brief")},ensure_ascii=False,indent=2),job_id=job_id,run_id=run_id,meta={**common,"component":"media_brief"})
    save_artifact("Content Packager","json","Content package manifest",json.dumps(payload,ensure_ascii=False,indent=2),job_id=job_id,run_id=run_id,meta={**common,"component":"manifest","selected":True})

async def generate_content_package(job_id):
    job=get_job(job_id)
    if not job:raise ValueError("Job not found")
    variant=_selected_production_variant(job_id)
    if not variant:raise ValueError("A selected production variant is required before building a Content Package")
    script=(variant.get("edited_script") or "").strip()
    if not script:raise ValueError("Selected variant must have an edited script")
    source_list=_content_package_sources(job_id,variant)
    live=bool(FACTORY_LLM_API_KEY)
    run_id=start_agent_run("Content Packager",job_id,"package",model=FACTORY_LLM_MODEL if live else "simulation-v3")
    set_agent_progress("Content Packager",8,"Preparing selected variant",job_id,run_id,"working")
    generation_cost=0.0
    try:
        if live:
            _variant_budget_guard(job_id,1800)
            system=(
                "You are Content Packager in FactoryOS. Convert the selected verified short-form variant into a production package. "
                "Do not invent facts, sources, analytics, media files or provider execution. Return JSON only with keys: "
                "title, description, cta, hashtags, voice_over, scenes, thumbnail_concept, media_brief. "
                "hashtags must be an array. scenes must be an array of objects containing narration, visual, on_screen_text and duration_sec. "
                "thumbnail_concept and media_brief must be JSON objects. Keep it production-ready for a vertical short."
            )
            user=(
                f"LANGUAGE: {job.get('language','English')}\nFORMAT: {job.get('format','Short only')}\n"
                f"JOB TITLE: {job.get('title','')}\nHOOK: {variant.get('optimized_hook') or variant.get('hook') or ''}\n"
                f"FINAL SCRIPT:\n{script}\n\nFACT CHECK:\n{json.dumps(variant.get('fact_check') or {},ensure_ascii=False)}\n\n"
                f"STRUCTURED QA:\n{json.dumps(variant.get('qa') or {},ensure_ascii=False)}\n\n"
                f"PERSISTED SOURCE REFERENCES:\n{json.dumps(source_list,ensure_ascii=False)}"
            )
            set_agent_progress("Content Packager",45,"Generating package structure",job_id,run_id,"working")
            result=await asyncio.wait_for(asyncio.to_thread(_content_brain_llm,"Content Packager",system,user,1800),timeout=AGENT_TIMEOUT_SECONDS)
            creative=_parse_json_object(result["content"]);generation_cost=float(result.get("cost_usd") or 0)
            finish_agent_run(run_id,status="completed",input_tokens=result["input_tokens"],output_tokens=result["output_tokens"],cost_usd=generation_cost,meta={"mode":"live_llm","content_package":True,"variant_id":variant["id"]})
        else:
            creative=_package_demo_payload(job,variant)
            finish_agent_run(run_id,status="completed",meta={"mode":"demo","content_package":True,"variant_id":variant["id"]})
        voice_over=str(creative.get("voice_over") or script).strip() or script
        duration=_package_duration_seconds(voice_over)
        scenes=_normalize_package_scenes(creative.get("scenes"),voice_over,duration)
        srt=_build_srt(voice_over,duration)
        hashtags=[str(x).strip() for x in (creative.get("hashtags") or []) if str(x).strip()][:12]
        payload={
            "schema_version":CONTENT_PACKAGE_SCHEMA_VERSION,
            "job_id":job_id,"variant_id":variant["id"],"variant_batch_id":variant.get("batch_id"),
            "final_script":script,
            "hook":str(variant.get("optimized_hook") or variant.get("hook") or "").strip(),
            "scenes":scenes,"voice_over":voice_over,"subtitles_srt":srt,
            "title":str(creative.get("title") or job.get("title") or "").strip(),
            "description":str(creative.get("description") or "").strip(),
            "cta":str(creative.get("cta") or "").strip(),
            "hashtags":hashtags,
            "thumbnail_concept":creative.get("thumbnail_concept") if isinstance(creative.get("thumbnail_concept"),dict) else {"concept":str(creative.get("thumbnail_concept") or "").strip()},
            "media_brief":creative.get("media_brief") if isinstance(creative.get("media_brief"),dict) else {"brief":str(creative.get("media_brief") or "").strip()},
            "source_list":source_list,
            "fact_check_report":variant.get("fact_check") or {},
            "structured_qa":variant.get("qa") or {},
            "estimated_duration_sec":duration,
            "production_cost":{
                "package_generation_usd":round(generation_cost,6),
                "selected_variant_allocated_usd":round(float(variant.get("allocated_cost_usd") or 0),6),
                "job_total_measured_usd":round(get_job_cost(job_id),6),
            },
            "provider_adapters":get_media_adapter_registry(),
            "provenance":{
                "content_packager_run_id":run_id,
                "variant_provenance":variant.get("provenance") or {},
                "generated_at":ts(),
                "mode":"live_llm" if live else "demo",
            },
        }
        missing=[x for x in CONTENT_PACKAGE_REQUIRED_FIELDS if x not in payload]
        if missing:raise RuntimeError("Content Package schema missing: "+", ".join(missing))
        package_id=str(uuid.uuid4());now=ts();payload["package_id"]=package_id
        con=db();con.execute("""INSERT INTO content_packages(id,job_id,variant_id,status,package_json,srt_text,generation_cost_usd,created_at,updated_at)
                               VALUES(?,?,?,'ready',?,?,?,?,?)""",
                            (package_id,job_id,variant["id"],json.dumps(payload,ensure_ascii=False),srt,generation_cost,now,now));con.commit();con.close()
        _save_package_artifacts(job_id,run_id,package_id,payload)
        record_run_step(run_id,job_id,"Content Packager","complete","Content Package ready",100,"completed")
        set_agent_progress("Content Packager",100,"Content Package ready",job_id,run_id,"done")
        event(job_id,f"Content Package ready: {len(scenes)} scene(s), ~{duration}s, package {package_id[:8]}")
        await broadcast({"type":"content_package","jobId":job_id,"packageId":package_id,"status":"ready"})
        return get_content_package(job_id)
    except Exception as exc:
        con=db();row=con.execute("SELECT status FROM agent_runs WHERE id=?",(run_id,)).fetchone();con.close()
        if row and row["status"]=="running":finish_agent_run(run_id,status="failed",error=str(exc),meta={"content_package":True})
        set_agent_progress("Content Packager",20,f"Failed: {str(exc)[:160]}",job_id,run_id,"failed")
        raise

def _package_export_files(record):
    package=record.get("package") or {}
    media=package.get("media_brief") or {}
    thumb=package.get("thumbnail_concept") or {}
    metadata={"title":package.get("title"),"description":package.get("description"),"cta":package.get("cta"),"hashtags":package.get("hashtags")}
    brief_lines=["# Media Brief","",json.dumps(media,ensure_ascii=False,indent=2),"","# Thumbnail Concept","",json.dumps(thumb,ensure_ascii=False,indent=2)]
    return {
        "content-package.json":json.dumps(package,ensure_ascii=False,indent=2)+"\n",
        "final-script.txt":str(package.get("final_script") or "")+"\n",
        "voice-over.txt":str(package.get("voice_over") or "")+"\n",
        "subtitles.srt":str(package.get("subtitles_srt") or record.get("srt_text") or ""),
        "scenes.json":json.dumps(package.get("scenes") or [],ensure_ascii=False,indent=2)+"\n",
        "publishing-metadata.json":json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",
        "sources.json":json.dumps(package.get("source_list") or [],ensure_ascii=False,indent=2)+"\n",
        "fact-check.json":json.dumps(package.get("fact_check_report") or {},ensure_ascii=False,indent=2)+"\n",
        "media-brief.md":"\n".join(brief_lines)+"\n",
    }

def _export_filename(job_id,suffix):
    job=get_job(job_id) or {}
    raw=re.sub(r"[^A-Za-z0-9._-]+","-",str(job.get("title") or "factoryos-package").strip()).strip("-")[:60] or "factoryos-package"
    return f"{raw}-{job_id[:8]}{suffix}"

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
        run_model=_workflow_model(job_id) if live_llm else "simulation-v3"
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
                _real_pilot_budget_guard(FACTORY_LLM_MAX_OUTPUT_TOKENS)
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
                    "workflow_version_id":llm_result.get("workflow_version_id"),
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
           FROM artifacts WHERE job_id=?
           ORDER BY CASE
             WHEN agent='AI Media Finisher' AND meta_json LIKE '%"component": "final_render"%' THEN 0
             WHEN agent='AI Media Finisher' AND meta_json LIKE '%"component": "short_render"%' THEN 2
             ELSE 1
           END, created_at DESC""",(job_id,)
    ).fetchall()]
    counts={x["agent"]:int(x["c"] or 0) for x in con.execute(
        "SELECT agent,COUNT(*) c FROM artifacts WHERE job_id=? GROUP BY agent",(job_id,)
    ).fetchall()}
    latest={}
    for row in rows:
        agent=row["agent"]
        if agent in latest:
            continue
        try:
            meta=json.loads(row.pop("meta_json") or "{}")
        except Exception:
            meta={}
        raw=row.get("content")
        if isinstance(raw,str):
            content=raw.strip()
        elif raw is None:
            content=""
        else:
            content=json.dumps(raw,ensure_ascii=False,indent=2)
        run=None;inputs=[]
        if row.get("run_id"):
            rr=con.execute("""SELECT id,status,stage,started_at,finished_at,duration_ms,input_tokens,output_tokens,cost_usd,model,error,meta_json
                              FROM agent_runs WHERE id=?""",(row["run_id"],)).fetchone()
            if rr:
                run=dict(rr)
                try:run["meta"]=json.loads(run.pop("meta_json") or "{}")
                except Exception:run["meta"]={}
                inputs=[dict(x) for x in con.execute(
                    """SELECT ri.source_agent,a.id artifact_id,a.kind,a.title,a.created_at
                       FROM run_inputs ri JOIN artifacts a ON a.id=ri.artifact_id
                       WHERE ri.run_id=? ORDER BY a.created_at""",(row["run_id"],)
                ).fetchall()]
        latest[agent]={
            "id":row["id"],
            "run_id":row.get("run_id"),
            "agent":agent,
            "kind":row.get("kind"),
            "title":row.get("title"),
            "content":content,
            "preview":content[:900],
            "url":row.get("url"),
            "mime_type":row.get("mime_type"),
            "created_at":row.get("created_at"),
            "mode":meta.get("mode"),
            "model":meta.get("model") or ((run or {}).get("model")),
            "variant_id":meta.get("variant_id"),
            "batch_id":meta.get("batch_id"),
            "component":meta.get("component"),
            "selected":bool(meta.get("selected")),
            "artifact_count":counts.get(agent,0),
            "run":run,
            "inputs":inputs,
            "meta":meta,
        }
    con.close()
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
    import_discovery_seed()
    if FACTORY_DISCOVERY_ENDPOINT and FACTORY_DISCOVERY_TOPICS:
        asyncio.create_task(discovery_collector_loop())

@app.on_event("startup")
async def start_factory_cycle_reconciler():
    asyncio.create_task(factory_cycle_reconcile_loop())
    if FACTORY_PUBLISHER_SCHEDULER_ENABLED:
        asyncio.create_task(publisher_scheduler_loop())
    asyncio.create_task(run_real_world_pilot_once())
    asyncio.create_task(run_media_finisher_pilot_once())

async def broadcast(payload=None):
    dead=[]; msg=json.dumps(payload or {"type":"refresh"})
    for ws in list(clients):
        try: await ws.send_text(msg)
        except Exception: dead.append(ws)
    for ws in dead: clients.discard(ws)


# v3.90 — Self-Improving Factory. Workflow changes are isolated, measured and owner-approved.
FACTORY_ALLOWED_LLM_MODELS=set(
    x.strip() for x in ([FACTORY_LLM_MODEL]+os.environ.get("FACTORY_ALLOWED_LLM_MODELS","").split(","))
    if x and x.strip()
)
WORKFLOW_ALLOWED_KEYS={"candidate_count","prompt_addenda","model","hook_pattern","routing_notes"}
EXPERIMENT_METRICS=set(PERFORMANCE_FIELDS if "PERFORMANCE_FIELDS" in globals() else ()) | {
    "views","retention_pct","completion_rate_pct","likes","comments","shares","saves","follower_delta",
    "production_cost_usd","production_duration_ms","cost_per_1k_views_usd",
}
LOWER_IS_BETTER={"production_cost_usd","production_duration_ms","cost_per_1k_views_usd"}

class ImprovementProposalCreate(BaseModel):
    title: str
    rationale: str
    hypothesis: str = ""
    change: dict = {}
    evidence: list[dict] = []

class ExperimentCreateRequest(BaseModel):
    primary_metric: str = "retention_pct"
    metric_direction: str = ""
    min_samples_per_arm: int = 2
    min_effect_pct: float = 5.0
    platform: str = ""

class ExperimentJobAssignment(BaseModel):
    job_id: str
    arm: str

class ExperimentDecisionRequest(BaseModel):
    confirm: bool = False
    reason: str = ""

def _decode_workflow_row(row):
    if not row:return None
    d=dict(row)
    d["config"]=_decode_json(d.pop("config_json","{}"),{})
    return d

def _workflow_baseline_config():
    return {"candidate_count":3,"prompt_addenda":{},"model":FACTORY_LLM_MODEL,"hook_pattern":"","routing_notes":""}

def _sanitize_workflow_patch(patch):
    if patch is None:return {}
    if not isinstance(patch,dict):raise ValueError("Workflow change must be an object")
    unknown=set(patch)-WORKFLOW_ALLOWED_KEYS
    if unknown:raise ValueError("Unsafe/unsupported workflow keys: "+", ".join(sorted(unknown)))
    out={}
    if "candidate_count" in patch:
        value=int(patch["candidate_count"])
        if value<2 or value>4:raise ValueError("candidate_count must be between 2 and 4")
        out["candidate_count"]=value
    if "prompt_addenda" in patch:
        raw=patch.get("prompt_addenda") or {}
        if not isinstance(raw,dict):raise ValueError("prompt_addenda must be an object")
        clean={}
        for agent,text_value in raw.items():
            if agent not in AGENTS:raise ValueError(f"Unknown workflow agent: {agent}")
            text_value=" ".join(str(text_value or "").split())
            if text_value:
                clean[agent]=text_value[:1200]
        out["prompt_addenda"]=clean
    if "model" in patch:
        model=str(patch.get("model") or "").strip()
        if model not in FACTORY_ALLOWED_LLM_MODELS:
            raise ValueError("Model is not in FACTORY_ALLOWED_LLM_MODELS")
        out["model"]=model
    if "hook_pattern" in patch:
        out["hook_pattern"]=" ".join(str(patch.get("hook_pattern") or "").split())[:800]
    if "routing_notes" in patch:
        out["routing_notes"]=" ".join(str(patch.get("routing_notes") or "").split())[:800]
    return out

def _normalize_workflow_config(patch=None,base=None):
    config=dict(_workflow_baseline_config() if base is None else base)
    clean=_sanitize_workflow_patch(patch or {})
    if "prompt_addenda" in clean:
        merged=dict(config.get("prompt_addenda") or {})
        merged.update(clean["prompt_addenda"])
        clean["prompt_addenda"]=merged
    config.update(clean)
    config["candidate_count"]=max(2,min(4,int(config.get("candidate_count") or 3)))
    if config.get("model") not in FACTORY_ALLOWED_LLM_MODELS:config["model"]=FACTORY_LLM_MODEL
    config["prompt_addenda"]=config.get("prompt_addenda") if isinstance(config.get("prompt_addenda"),dict) else {}
    return config

def _active_workflow_version():
    con=db()
    row=con.execute("SELECT * FROM workflow_versions WHERE status='active' ORDER BY created_at DESC LIMIT 1").fetchone()
    if not row:
        wid=str(uuid.uuid4());now=ts();cfg=_workflow_baseline_config()
        con.execute("""INSERT INTO workflow_versions(id,name,proposal_id,parent_id,status,created_at,config_json,notes)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (wid,"FactoryOS v3.90 baseline",None,None,"active",now,json.dumps(cfg),"Initial immutable runtime baseline for controlled experiments."))
        con.commit();row=con.execute("SELECT * FROM workflow_versions WHERE id=?",(wid,)).fetchone()
    con.close()
    return _decode_workflow_row(row)

def _workflow_version(version_id):
    con=db();row=con.execute("SELECT * FROM workflow_versions WHERE id=?",(version_id,)).fetchone();con.close()
    return _decode_workflow_row(row)

def get_job_workflow_assignment(job_id):
    if not job_id:return None
    con=db();row=con.execute("SELECT * FROM job_workflow_versions WHERE job_id=?",(job_id,)).fetchone();con.close()
    if not row:return None
    d=dict(row);d["locked"]=bool(d.get("locked"));d["version"]=_workflow_version(d["workflow_version_id"])
    return d

def _workflow_context(job_id=None,lock=False):
    assignment=get_job_workflow_assignment(job_id) if job_id else None
    if assignment:
        version=assignment["version"]
    else:
        version=_active_workflow_version()
        if job_id and lock:
            con=db()
            con.execute("""INSERT OR IGNORE INTO job_workflow_versions(job_id,workflow_version_id,experiment_id,arm,assigned_at,locked)
                           VALUES(?,?,?,?,?,1)""",(job_id,version["id"],None,None,ts()))
            con.commit();con.close()
            assignment=get_job_workflow_assignment(job_id)
    return {"version":version,"config":_normalize_workflow_config(version.get("config") or {}),"assignment":assignment}

def _workflow_model(job_id=None):
    return str(_workflow_context(job_id).get("config",{}).get("model") or FACTORY_LLM_MODEL)

def _workflow_candidate_count(job_id,requested=None):
    if requested is not None:return max(2,min(4,int(requested)))
    return int(_workflow_context(job_id).get("config",{}).get("candidate_count") or 3)

def _apply_workflow_prompt(agent,system,job_id=None):
    cfg=_workflow_context(job_id).get("config") or {}
    extra=(cfg.get("prompt_addenda") or {}).get(agent,"").strip()
    hook_pattern=(cfg.get("hook_pattern") or "").strip() if agent=="Hook Generator" else ""
    additions=[]
    if extra:additions.append("Approved workflow instruction: "+extra)
    if hook_pattern:additions.append("Approved hook pattern to test: "+hook_pattern)
    return system + (("\n" + "\n".join(additions)) if additions else "")

def build_improvement_action(title,rationale,evidence=None,change=None,hypothesis=None):
    change=_sanitize_workflow_patch(change or {})
    hypothesis=(hypothesis or f"If we apply the proposed workflow change for '{title}', the selected measured outcome should improve without weakening safety controls.").strip()
    return {
        "type":"workflow_improvement",
        "requires_review":True,
        "requires_experiment":True,
        "hypothesis":hypothesis[:900],
        "change":change,
        "evidence":list(evidence or [])[:20],
    }

def suggested_workflow_patch(finding,title="",rationale=""):
    if not finding:return {}
    code=str(finding.get("code") or "")
    agent=""
    if ":" in str(finding.get("title") or ""):agent=str(finding.get("title")).split(":",1)[1].strip()
    if agent not in AGENTS:return {}
    if code=="low_success_rate":
        return {"prompt_addenda":{agent:"Use a strict input/output contract. If required evidence is missing, report the missing dependency instead of improvising."}}
    if code in ("slow_agent","high_agent_cost"):
        return {"prompt_addenda":{agent:"Return only stage-required content, avoid repeating upstream context, and prefer concise structured output."}}
    return {}

def create_improvement_proposal(payload):
    title=" ".join((payload.title or "").split())[:180]
    rationale=" ".join((payload.rationale or "").split())[:2500]
    if not title or not rationale:raise ValueError("Title and rationale are required")
    action=build_improvement_action(title,rationale,payload.evidence,payload.change,payload.hypothesis or None)
    fingerprint=hashlib.sha256((title+"|"+rationale+"|"+json.dumps(action.get("change") or {},sort_keys=True)).encode("utf-8")).hexdigest()
    con=db();existing=con.execute("SELECT id FROM improvement_proposals WHERE fingerprint=?",(fingerprint,)).fetchone()
    if existing:
        con.close();return next(x for x in get_improvement_proposals(None,100) if x["id"]==existing["id"])
    pid=str(uuid.uuid4());now=ts()
    con.execute("""INSERT INTO improvement_proposals(id,fingerprint,created_at,updated_at,title,rationale,status,source,action_json)
                   VALUES(?,?,?,?,?,?,?,?,?)""",(pid,fingerprint,now,now,title,rationale,"proposed","owner",json.dumps(action,ensure_ascii=False)))
    con.commit();con.close()
    return next(x for x in get_improvement_proposals(None,100) if x["id"]==pid)

def _experiment_row(row):
    if not row:return None
    d=dict(row)
    d["evaluation"]=_decode_json(d.pop("evaluation_json","{}"),{})
    d["meta"]=_decode_json(d.pop("meta_json","{}"),{})
    d["control_version"]=_workflow_version(d["control_version_id"])
    d["treatment_version"]=_workflow_version(d["treatment_version_id"])
    return d

def _get_experiment(experiment_id):
    con=db();row=con.execute("SELECT * FROM experiments WHERE id=?",(experiment_id,)).fetchone();con.close()
    return _experiment_row(row)

def _proposal_by_id(proposal_id):
    return next((x for x in get_improvement_proposals(None,300) if x["id"]==proposal_id),None)

def create_experiment_from_proposal(proposal_id,request=None):
    proposal=_proposal_by_id(proposal_id)
    if not proposal:raise ValueError("Proposal not found")
    change=_sanitize_workflow_patch(proposal.get("change") or {})
    if not change:raise ValueError("Proposal has no concrete workflow change to test")
    req=request or ExperimentCreateRequest()
    metric=(req.primary_metric or "retention_pct").strip()
    if metric not in EXPERIMENT_METRICS:raise ValueError("Unsupported experiment metric")
    direction=(req.metric_direction or ("lower" if metric in LOWER_IS_BETTER else "higher")).strip().lower()
    if direction not in ("higher","lower"):raise ValueError("metric_direction must be higher or lower")
    con=db()
    existing=con.execute("""SELECT * FROM experiments WHERE proposal_id=? AND status NOT IN ('rejected','rolled_back')
                            ORDER BY created_at DESC LIMIT 1""",(proposal_id,)).fetchone()
    con.close()
    if existing:return _experiment_row(existing)
    active=_active_workflow_version()
    treatment_config=_normalize_workflow_config(change,active["config"])
    treatment_id=str(uuid.uuid4());experiment_id=str(uuid.uuid4());now=ts()
    con=db()
    con.execute("""INSERT INTO workflow_versions(id,name,proposal_id,parent_id,status,created_at,config_json,notes)
                   VALUES(?,?,?,?,?,?,?,?)""",(
        treatment_id,f"Treatment · {proposal['title'][:90]}",proposal_id,active["id"],"experiment",now,
        json.dumps(treatment_config,ensure_ascii=False),"Treatment version. Not active until measured experiment + owner rollout approval."
    ))
    con.execute("""INSERT INTO experiments(
        id,proposal_id,title,hypothesis,primary_metric,metric_direction,min_samples_per_arm,min_effect_pct,platform,
        status,control_version_id,treatment_version_id,baseline_active_version_id,created_at,updated_at,evaluation_json,meta_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        experiment_id,proposal_id,proposal["title"],proposal.get("hypothesis") or proposal["rationale"],metric,direction,
        max(1,min(100,int(req.min_samples_per_arm))),max(0.0,float(req.min_effect_pct)),(req.platform or "").strip(),
        "draft",active["id"],treatment_id,active["id"],now,now,"{}",
        json.dumps({"evidence":proposal.get("evidence") or [],"safety":"No workflow version is activated automatically."},ensure_ascii=False)
    ))
    con.execute("UPDATE improvement_proposals SET status='experimenting',updated_at=? WHERE id=?",(now,proposal_id))
    con.commit();con.close()
    return _get_experiment(experiment_id)

def assign_job_to_experiment(experiment_id,job_id,arm):
    exp=_get_experiment(experiment_id)
    if not exp:raise ValueError("Experiment not found")
    if exp["status"] in ("rejected","rolled_out","rolled_back"):raise ValueError("Experiment is closed")
    arm=(arm or "").strip().lower()
    if arm not in ("control","treatment"):raise ValueError("arm must be control or treatment")
    if not get_job(job_id):raise ValueError("Job not found")
    con=db()
    run_count=int(con.execute("SELECT COUNT(*) c FROM agent_runs WHERE job_id=?",(job_id,)).fetchone()["c"] or 0)
    existing=con.execute("SELECT * FROM job_workflow_versions WHERE job_id=?",(job_id,)).fetchone()
    if run_count:
        con.close();raise ValueError("Experiment arm must be assigned before the first worker run")
    if existing and (existing["experiment_id"]!=experiment_id or existing["arm"]!=arm):
        con.close();raise ValueError("Job already has a locked workflow assignment")
    version_id=exp["control_version_id"] if arm=="control" else exp["treatment_version_id"]
    if not existing:
        con.execute("""INSERT INTO job_workflow_versions(job_id,workflow_version_id,experiment_id,arm,assigned_at,locked)
                       VALUES(?,?,?,?,?,1)""",(job_id,version_id,experiment_id,arm,ts()))
    now=ts()
    con.execute("""UPDATE experiments SET status='running',started_at=COALESCE(started_at,?),updated_at=? WHERE id=?""",
                (now,now,experiment_id))
    con.commit();con.close()
    return get_job_workflow_assignment(job_id)

def _metric_for_performance_item(item,metric):
    latest=(item.get("latest") or {}).get("metrics") or {}
    if metric in latest:return latest.get(metric)
    if metric=="production_cost_usd":return float(item.get("attribution",{}).get("production_cost_usd") or 0)
    if metric=="production_duration_ms":
        con=db();row=con.execute("SELECT COALESCE(SUM(duration_ms),0) v FROM agent_runs WHERE job_id=?",(item["publish"]["job_id"],)).fetchone();con.close()
        return float(row["v"] or 0)
    if metric=="cost_per_1k_views_usd":return item.get("cost_per_1k_views_usd")
    return None

def evaluate_experiment(experiment_id):
    exp=_get_experiment(experiment_id)
    if not exp:raise ValueError("Experiment not found")
    con=db();assignments=[dict(x) for x in con.execute(
        "SELECT * FROM job_workflow_versions WHERE experiment_id=? ORDER BY assigned_at",(experiment_id,)
    ).fetchall()];con.close()
    samples={"control":[],"treatment":[]}
    for assignment in assignments:
        con=db();rows=con.execute("""SELECT * FROM publishing_queue WHERE job_id=? AND status='published'
                                     ORDER BY published_at DESC,updated_at DESC""",(assignment["job_id"],)).fetchall();con.close()
        for row in rows:
            pub=_publish_item(row)
            if exp.get("platform") and pub.get("platform")!=exp["platform"]:continue
            item=_performance_item(pub)
            value=_metric_for_performance_item(item,exp["primary_metric"])
            if not isinstance(value,(int,float)):continue
            con=db();dur=con.execute("SELECT COALESCE(SUM(duration_ms),0) v FROM agent_runs WHERE job_id=?",(assignment["job_id"],)).fetchone()["v"];con.close()
            samples[assignment["arm"]].append({
                "job_id":assignment["job_id"],"publish_id":pub["id"],"platform":pub.get("platform"),
                "value":float(value),"production_cost_usd":float(item.get("attribution",{}).get("production_cost_usd") or 0),
                "production_duration_ms":float(dur or 0),"workflow_version_id":assignment["workflow_version_id"],
            })
    def aggregate(items):
        vals=[x["value"] for x in items]
        costs=[x["production_cost_usd"] for x in items]
        durations=[x["production_duration_ms"] for x in items]
        return {"samples":len(vals),"mean":round(sum(vals)/len(vals),6) if vals else None,
                "avg_production_cost_usd":round(sum(costs)/len(costs),6) if costs else None,
                "avg_production_duration_ms":round(sum(durations)/len(durations),2) if durations else None}
    control=aggregate(samples["control"]);treatment=aggregate(samples["treatment"])
    enough=control["samples"]>=exp["min_samples_per_arm"] and treatment["samples"]>=exp["min_samples_per_arm"]
    delta=None;delta_pct=None;improvement_pct=None;recommendation="insufficient_data"
    if control["mean"] is not None and treatment["mean"] is not None:
        delta=treatment["mean"]-control["mean"]
        if control["mean"]!=0:delta_pct=delta/abs(control["mean"])*100
        signed=(delta_pct if exp["metric_direction"]=="higher" else (-delta_pct if delta_pct is not None else None))
        if enough:
            if signed is not None and signed>=float(exp["min_effect_pct"]):recommendation="treatment"
            elif signed is not None and signed<=-float(exp["min_effect_pct"]):recommendation="control"
            else:recommendation="inconclusive"
        improvement_pct=signed
    evaluation={
        "metric":exp["primary_metric"],"direction":exp["metric_direction"],"platform":exp.get("platform") or None,
        "min_samples_per_arm":exp["min_samples_per_arm"],"min_effect_pct":exp["min_effect_pct"],
        "control":control,"treatment":treatment,"delta":round(delta,6) if delta is not None else None,
        "delta_pct":round(delta_pct,2) if delta_pct is not None else None,
        "observed_improvement_pct":round(improvement_pct,2) if improvement_pct is not None else None,
        "recommendation":recommendation,"enough_samples":enough,"samples":samples,
        "note":"This is an observed controlled comparison, not a claim of statistical causality. Rollout always requires owner approval."
    }
    now=ts();new_status="ready_for_decision" if enough else ("running" if exp["status"]!="draft" else "draft")
    con=db();con.execute("UPDATE experiments SET status=?,evaluation_json=?,evaluated_at=?,updated_at=? WHERE id=?",
                         (new_status,json.dumps(evaluation,ensure_ascii=False),now,now,experiment_id));con.commit();con.close()
    return evaluation

def _experiment_config_diff(exp):
    a=(exp.get("control_version") or {}).get("config") or {}
    b=(exp.get("treatment_version") or {}).get("config") or {}
    keys=sorted(set(a)|set(b))
    return [{"key":k,"control":a.get(k),"treatment":b.get(k)} for k in keys if a.get(k)!=b.get(k)]

def get_experiments(limit=100):
    con=db();rows=con.execute("SELECT * FROM experiments ORDER BY updated_at DESC LIMIT ?",(max(1,min(300,int(limit))),)).fetchall();con.close()
    out=[]
    for row in rows:
        exp=_experiment_row(row)
        con=db();assign=[dict(x) for x in con.execute("SELECT job_id,workflow_version_id,arm,assigned_at FROM job_workflow_versions WHERE experiment_id=? ORDER BY assigned_at",(exp["id"],)).fetchall()];con.close()
        exp["assignments"]=assign;exp["config_diff"]=_experiment_config_diff(exp);out.append(exp)
    return out

def rollout_experiment(experiment_id,confirm=False,reason=""):
    exp=_get_experiment(experiment_id)
    if not exp:raise ValueError("Experiment not found")
    if not confirm:return {"ok":False,"requires_confirmation":True,"message":"Owner confirmation is required before production rollout."}
    evaluation=exp.get("evaluation") or evaluate_experiment(experiment_id)
    if evaluation.get("recommendation")!="treatment":raise ValueError("Treatment is not the measured recommendation; rollout is blocked")
    treatment=_workflow_version(exp["treatment_version_id"])
    _normalize_workflow_config(treatment.get("config") or {})
    current=_active_workflow_version();now=ts();con=db()
    con.execute("UPDATE workflow_versions SET status='archived' WHERE status='active'")
    con.execute("UPDATE workflow_versions SET status='active' WHERE id=?",(treatment["id"],))
    con.execute("""UPDATE experiments SET status='rolled_out',decision='accepted',decision_reason=?,rollout_version_id=?,updated_at=?
                   WHERE id=?""",((reason or "Owner approved measured treatment rollout.")[:1200],treatment["id"],now,experiment_id))
    con.execute("UPDATE improvement_proposals SET status='accepted',updated_at=? WHERE id=?",(now,exp["proposal_id"]))
    con.execute("""INSERT INTO workflow_rollouts(id,experiment_id,action,from_version_id,to_version_id,actor,reason,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),experiment_id,"rollout",current["id"],treatment["id"],"owner",(reason or "")[:1200],now))
    con.commit();con.close();event(None,f"Self-Improving Factory: treatment rolled out for experiment {experiment_id}")
    return {"ok":True,"active":_active_workflow_version(),"experiment":_get_experiment(experiment_id)}

def rollback_experiment(experiment_id,confirm=False,reason=""):
    exp=_get_experiment(experiment_id)
    if not exp:raise ValueError("Experiment not found")
    if exp["status"]!="rolled_out":raise ValueError("Only a rolled-out experiment can be rolled back")
    if not confirm:return {"ok":False,"requires_confirmation":True,"message":"Owner confirmation is required before rollback."}
    con=db();last=con.execute("""SELECT * FROM workflow_rollouts WHERE experiment_id=? AND action='rollout'
                                ORDER BY created_at DESC LIMIT 1""",(experiment_id,)).fetchone();con.close()
    restore_id=(last["from_version_id"] if last else exp["baseline_active_version_id"])
    restore=_workflow_version(restore_id)
    if not restore:raise ValueError("Rollback baseline workflow version is unavailable")
    _normalize_workflow_config(restore.get("config") or {})
    current=_active_workflow_version();now=ts();con=db()
    con.execute("UPDATE workflow_versions SET status='archived' WHERE status='active'")
    con.execute("UPDATE workflow_versions SET status='active' WHERE id=?",(restore_id,))
    con.execute("""UPDATE experiments SET status='rolled_back',decision='rollback',decision_reason=?,updated_at=? WHERE id=?""",
                ((reason or "Owner rolled back the treatment.")[:1200],now,experiment_id))
    con.execute("""INSERT INTO workflow_rollouts(id,experiment_id,action,from_version_id,to_version_id,actor,reason,created_at)
                   VALUES(?,?,?,?,?,?,?,?)""",(str(uuid.uuid4()),experiment_id,"rollback",current["id"],restore_id,"owner",(reason or "")[:1200],now))
    con.commit();con.close();event(None,f"Self-Improving Factory: rollback completed for experiment {experiment_id}")
    return {"ok":True,"active":_active_workflow_version(),"experiment":_get_experiment(experiment_id)}

def reject_experiment(experiment_id,reason=""):
    exp=_get_experiment(experiment_id)
    if not exp:raise ValueError("Experiment not found")
    if exp["status"]=="rolled_out":raise ValueError("Rollback the active treatment instead of rejecting it")
    now=ts();con=db()
    con.execute("UPDATE experiments SET status='rejected',decision='rejected',decision_reason=?,updated_at=? WHERE id=?",
                ((reason or "Owner rejected experiment.")[:1200],now,experiment_id))
    con.execute("UPDATE improvement_proposals SET status='rejected',updated_at=? WHERE id=?",(now,exp["proposal_id"]))
    con.execute("UPDATE workflow_versions SET status='rejected' WHERE id=? AND status='experiment'",(exp["treatment_version_id"],))
    con.commit();con.close()
    return _get_experiment(experiment_id)

def get_self_improvement_dashboard():
    experiments=get_experiments(100);active=_active_workflow_version();proposals=get_improvement_proposals(None,100)
    counts={}
    for x in experiments:counts[x["status"]]=counts.get(x["status"],0)+1
    return {
        "summary":{"proposals":len(proposals),"experiments":len(experiments),"running":counts.get("running",0),
                   "ready_for_decision":counts.get("ready_for_decision",0),"rolled_out":counts.get("rolled_out",0)},
        "active_workflow":active,"proposals":proposals,"experiments":experiments,
        "allowed_models":sorted(FACTORY_ALLOWED_LLM_MODELS),"allowed_change_keys":sorted(WORKFLOW_ALLOWED_KEYS),
        "safety_note":"Supervisor proposals never auto-promote. Jobs are pinned to immutable workflow versions; rollout and rollback require owner confirmation."
    }

# v3.60 → v3.80 release train: approval, controlled publishing, real performance feedback.
class ApprovalRejectRequest(BaseModel):
    reason: str = ""

class ApprovalRegenerateRequest(BaseModel):
    component: str
    confirm_cost: bool = False

class PublishScheduleRequest(BaseModel):
    target: str = "manual"
    platform: str = "unspecified"
    scheduled_at: Optional[str] = None

class PublishConfirmRequest(BaseModel):
    external_post_id: str
    external_url: str = ""
    published_at: Optional[str] = None

class PerformanceSnapshotCreate(BaseModel):
    publish_id: str
    captured_at: Optional[str] = None
    views: Optional[int] = None
    reach: Optional[int] = None
    watch_time_sec: Optional[float] = None
    retention_pct: Optional[float] = None
    completion_rate_pct: Optional[float] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    saves: Optional[int] = None
    follower_delta: Optional[int] = None
    content_duration_sec: Optional[float] = None
    source: str = "manual"

PERFORMANCE_FIELDS=(
    "views","reach","watch_time_sec","retention_pct","completion_rate_pct",
    "likes","comments","shares","saves","follower_delta","content_duration_sec",
)

EXPERIMENT_METRICS.update(PERFORMANCE_FIELDS)

def _json_row(row, field="meta_json", output="meta"):
    if not row:return None
    item=dict(row)
    item[output]=_decode_json(item.pop(field,"{}"),{})
    return item

def _record_approval(job_id,decision,reason="",component="",meta=None):
    package=get_content_package(job_id).get("package_record")
    variant=_selected_production_variant(job_id)
    decision_id=str(uuid.uuid4())
    con=db()
    con.execute("""INSERT INTO approval_decisions(
        id,job_id,package_id,variant_id,decision,reason,component,actor,created_at,meta_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?)""",(
        decision_id,job_id,(package or {}).get("id"),(variant or {}).get("id"),
        decision,(reason or "").strip(),(component or "").strip(),"owner",ts(),
        json.dumps(meta or {},ensure_ascii=False)
    ))
    con.commit();con.close()
    return decision_id

def get_approval_history(job_id,limit=80):
    con=db()
    rows=con.execute("SELECT * FROM approval_decisions WHERE job_id=? ORDER BY created_at DESC LIMIT ?",
                     (job_id,max(1,min(300,int(limit))))).fetchall()
    con.close()
    return [_json_row(x) for x in rows]

def _latest_publishable_media(job_id):
    con=db()
    row=con.execute("""SELECT id,agent,kind,title,content,url,mime_type,created_at,meta_json FROM artifacts
                       WHERE job_id=? AND kind='video' AND COALESCE(url,'')!=''
                       ORDER BY CASE
                         WHEN agent='AI Media Finisher' AND meta_json LIKE '%final_render%' THEN 0
                         WHEN agent='AI Media Finisher' THEN 1
                         WHEN agent='Render Agent' THEN 2
                         ELSE 3
                       END, created_at DESC LIMIT 1""",(job_id,)).fetchone()
    con.close()
    if not row:return None
    item=dict(row);item["meta"]=_decode_json(item.pop("meta_json","{}"),{})
    return item

def _artifact_for_edit_job(edit):
    if not edit:return None
    job_id=edit.get("production_job_id")
    edit_job_id=edit.get("id")
    artifact_id=edit.get("output_artifact_id")
    con=db()
    if artifact_id:
        row=con.execute("""SELECT id,agent,kind,title,content,url,mime_type,created_at,meta_json FROM artifacts
                           WHERE id=? AND job_id=? AND kind='video' AND COALESCE(url,'')!=''""",
                        (artifact_id,job_id)).fetchone()
        if row:
            con.close()
            item=dict(row);item["meta"]=_decode_json(item.pop("meta_json","{}"),{})
            return item
    rows=con.execute("""SELECT id,agent,kind,title,content,url,mime_type,created_at,meta_json FROM artifacts
                        WHERE job_id=? AND kind='video' AND agent='AI Media Finisher' AND COALESCE(url,'')!=''
                        ORDER BY created_at DESC LIMIT 100""",(job_id,)).fetchall()
    con.close()
    matches=[]
    for row in rows:
        item=dict(row);item["meta"]=_decode_json(item.pop("meta_json","{}"),{})
        if (item.get("meta") or {}).get("edit_job_id")!=edit_job_id:continue
        component=(item.get("meta") or {}).get("component")
        priority=0 if component=="final_render" else 1 if component=="short_render" else 2
        matches.append((priority,item))
    if not matches:return None
    matches.sort(key=lambda x:x[0])
    return matches[0][1]

def _latest_render_preview(job_id):
    con=db()
    row=con.execute("""SELECT * FROM edit_jobs WHERE production_job_id=?
                       ORDER BY updated_at DESC,created_at DESC,id DESC LIMIT 1""",(job_id,)).fetchone()
    con.close()
    if row:
        exact=_artifact_for_edit_job(_edit_job_dict(row,False))
        if exact:return exact
    return _latest_publishable_media(job_id)

def _media_review_state(job_id):
    con=db()
    row=con.execute("""SELECT * FROM edit_jobs WHERE production_job_id=?
                       ORDER BY updated_at DESC,created_at DESC,id DESC LIMIT 1""",(job_id,)).fetchone()
    con.close()
    if not row:
        return {"required":False,"ready":True,"edit_job":None,"artifact":_latest_publishable_media(job_id),
                "source_binding_ok":True,"binding":{},"reason":""}
    edit=_edit_job_dict(row,False)
    media=_artifact_for_edit_job(edit)
    request=edit.get("request") or {}
    package_mode=str(request.get("package_mode") or "").strip()
    source_package=request.get("content_package") if isinstance(request.get("content_package"),dict) else {}
    source_package_id=source_package.get("package_id")
    source_variant_id=source_package.get("variant_id")
    current_package=get_content_package(job_id).get("package_record")
    current_variant=_selected_production_variant(job_id)
    binding={
        "package_mode":package_mode,
        "source_package_id":source_package_id,
        "source_variant_id":source_variant_id,
        "current_package_id":(current_package or {}).get("id"),
        "current_variant_id":(current_variant or {}).get("id"),
    }
    source_binding_ok=True
    stale_reason=""
    if package_mode=="content_package":
        source_binding_ok=bool(
            current_package and current_package.get("status")=="ready" and current_variant
            and source_package_id and source_variant_id
            and source_package_id==current_package.get("id")
            and source_variant_id==current_variant.get("id")
        )
        if not source_binding_ok:
            stale_reason="Finished media was produced from an older Content Package or selected variant. Rerun Media Finisher before approval."
    status_ready=edit.get("status")=="ready"
    media_ready=bool(media and media.get("url"))
    media_meta=(media or {}).get("meta") or {}
    archive_status=str((edit.get("response") or {}).get("durable_media_status") or "")
    durability_required=bool(media_ready and _is_ephemeral_finisher_url((media or {}).get("url")))
    durability_ready=bool(media_ready and (not durability_required or media_meta.get("durable_media") or "/media-archive/" in str((media or {}).get("url") or "")))
    ready=bool(status_ready and media_ready and durability_ready and source_binding_ok)
    if ready:
        reason=""
    elif not status_ready:
        reason="Latest Media Finisher output is not ready for human approval."
    elif not media_ready:
        reason="Latest Media Finisher run has no publishable video artifact."
    elif not durability_ready and archive_status=="failed":
        reason="Finished media could not be copied to durable FactoryOS storage. Retry Media Finisher or the archive before approval."
    elif not durability_ready:
        reason="Finished media is being copied to durable FactoryOS storage before approval."
    else:
        reason=stale_reason or "Finished media is not bound to the current approved production inputs."
    return {"required":True,"ready":ready,"edit_job":edit,"artifact":media,
            "source_binding_ok":source_binding_ok,"binding":binding,"reason":reason,
            "durability_required":durability_required,"durability_ready":durability_ready,
            "durable_media_status":archive_status}

def get_variant_diff(job_id):
    data=get_job_variants(job_id); variants=data.get("variants") or []
    selected=next((x for x in variants if x.get("status")=="selected"),None)
    if not selected:return {"selected":None,"comparisons":[]}
    comparisons=[]
    for other in variants:
        if other["id"]==selected["id"]:continue
        changes=[]
        for field in ("angle","hook","optimized_hook","edited_script","decision_reason","allocated_cost_usd"):
            if selected.get(field)!=other.get(field):
                changes.append({"field":field,"selected":selected.get(field),"other":other.get(field)})
        comparisons.append({"variant_id":other["id"],"ordinal":other.get("ordinal"),"status":other.get("status"),
                            "changes":changes,"qa":other.get("qa") or {}})
    return {"selected":{"id":selected["id"],"ordinal":selected.get("ordinal"),"qa":selected.get("qa") or {}},
            "comparisons":comparisons}

def _estimated_regeneration_cost(component):
    if component=="voice":
        return {"component":"voice","estimated_model_cost_usd":0.0,"provider_cost_known":False,
                "note":"Voice rerun uses no LLM call here; external TTS pricing may be unknown."}
    caps={"hook":650,"script":1100,"caption":700}
    if component not in caps:raise ValueError("Unsupported regeneration component")
    if not FACTORY_LLM_API_KEY:
        return {"component":component,"estimated_model_cost_usd":0.0,"provider_cost_known":True,
                "note":"Zero-spend deterministic runtime: no live model call is configured."}
    estimate=(5000*FACTORY_LLM_INPUT_USD_PER_1M + caps[component]*FACTORY_LLM_OUTPUT_USD_PER_1M)/1_000_000
    return {"component":component,"estimated_model_cost_usd":round(estimate,6),"provider_cost_known":True,
            "note":"Conservative pre-call estimate; actual provider usage is recorded from the run."}

async def _regenerate_caption(job_id):
    data=get_content_package(job_id);record=data.get("package_record")
    variant=_selected_production_variant(job_id);job=get_job(job_id)
    if not record or record.get("status")!="ready" or not variant:
        raise ValueError("Ready package and selected variant required")
    run_id=None
    if FACTORY_LLM_API_KEY:
        obj,run_id,_=await _variant_agent_call(
            "Content Packager",job_id,"Partial rerun · publishing metadata",
            "Return JSON only with title, description, cta, hashtags. Preserve verified meaning; do not add unsupported claims.",
            json.dumps({"job_title":job.get("title"),"script":variant.get("edited_script"),
                        "hook":variant.get("optimized_hook") or variant.get("hook")},ensure_ascii=False),700
        )
        fresh={k:obj.get(k) for k in ("title","description","cta","hashtags")}
    else:
        demo=_package_demo_payload(job,variant)
        fresh={k:demo.get(k) for k in ("title","description","cta","hashtags")}
    package=record.get("package") or {}
    for key,value in fresh.items():
        if value is not None:package[key]=value
    package.setdefault("production_cost",{})["job_total_measured_usd"]=round(get_job_cost(job_id),6)
    con=db()
    con.execute("UPDATE content_packages SET package_json=?,updated_at=? WHERE id=?",
                (json.dumps(package,ensure_ascii=False),ts(),record["id"]))
    con.commit();con.close()
    _record_approval(job_id,"regenerate","Publishing metadata regenerated","caption",{"run_id":run_id})
    event(job_id,"Approval Studio: publishing metadata regenerated only")
    return get_content_package(job_id)

def link_job_idea(job_id,idea_id):
    con=db()
    if not con.execute("SELECT id FROM jobs WHERE id=?",(job_id,)).fetchone():
        con.close();raise ValueError("Job not found")
    if not con.execute("SELECT id FROM content_ideas WHERE id=?",(idea_id,)).fetchone():
        con.close();raise ValueError("Idea not found")
    con.execute("""INSERT INTO job_idea_links(job_id,idea_id,created_at) VALUES(?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET idea_id=excluded.idea_id,created_at=excluded.created_at""",
                (job_id,idea_id,ts()))
    con.commit();con.close()
    return {"job_id":job_id,"idea_id":idea_id}

def get_publisher_adapter_registry():
    webhook=bool(FACTORY_PUBLISHER_ENDPOINT)
    return {"selected":FACTORY_PUBLISHER_ADAPTER,
            "scheduler_enabled":FACTORY_PUBLISHER_SCHEDULER_ENABLED,
            "scheduler_interval_sec":FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC,
            "adapters":[
                {"kind":"manual","configured":True,"status":"ready","execution":"explicit external confirmation"},
                {"kind":"webhook","configured":webhook,"status":"configured" if webhook else "not_configured","execution":"idempotent POST"},
            ],
            "secrets_exposed":False,
            "note":"Approval never publishes directly. Retries reuse one stable idempotency key bound to the approved package, variant and final media artifact."}

def get_analytics_adapter_registry():
    webhook=bool(FACTORY_ANALYTICS_ENDPOINT)
    return {"selected":FACTORY_ANALYTICS_ADAPTER,
            "adapters":[
                {"kind":"manual","configured":True,"status":"ready"},
                {"kind":"webhook","configured":webhook,"status":"configured" if webhook else "not_configured"},
            ],
            "secrets_exposed":False,
            "note":"Only metrics actually supplied by the platform/owner are persisted."}

def _publish_content_snapshot(package_record):
    package=(package_record or {}).get("package") or {}
    return {
        "title":str(package.get("title") or ""),
        "description":str(package.get("description") or ""),
        "cta":str(package.get("cta") or ""),
        "hashtags":[str(x) for x in (package.get("hashtags") or []) if str(x).strip()],
        "thumbnail_concept":package.get("thumbnail_concept") or "",
    }

def _publish_snapshot_hash(snapshot):
    canonical=json.dumps(snapshot or {},ensure_ascii=False,sort_keys=True,separators=(",",":"),default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def _publish_item(row):
    item=_json_row(row) if row else None
    if not item:return None
    meta=item.get("meta") or {}
    item["media"]={
        "artifact_id":meta.get("media_artifact_id"),"url":meta.get("media_url") or "",
        "title":meta.get("media_title") or "","mime_type":meta.get("media_mime_type") or "",
        "edit_job_id":meta.get("media_edit_job_id")
    } if meta.get("media_artifact_id") or meta.get("media_url") else None
    item["content_snapshot"]=meta.get("content_snapshot") if isinstance(meta.get("content_snapshot"),dict) else None
    item["content_snapshot_hash"]=str(meta.get("content_snapshot_hash") or "")
    item["approval_decision_id"]=meta.get("approval_decision_id")
    item["approved_at"]=meta.get("approved_at")
    return item

def _ensure_publish_item(job_id,approval_decision_id=None):
    package=get_content_package(job_id).get("package_record")
    variant=_selected_production_variant(job_id)
    if not package or package.get("status")!="ready":raise ValueError("A fresh Content Package is required before publishing")
    if not variant:raise ValueError("A selected production variant is required before publishing")
    media_state=_media_review_state(job_id)
    if media_state.get("required") and not media_state.get("ready"):
        raise ValueError(media_state.get("reason") or "Finished media is not ready for approval")
    media=media_state.get("artifact") or {}
    media_meta=media.get("meta") or {}
    media_key=media.get("id") or "no-media"
    content_snapshot=_publish_content_snapshot(package)
    snapshot_hash=_publish_snapshot_hash(content_snapshot)
    idem=hashlib.sha256(f"{job_id}:{package['id']}:{variant['id']}:{media_key}:{snapshot_hash}".encode("utf-8")).hexdigest()
    con=db();existing=con.execute("SELECT * FROM publishing_queue WHERE idempotency_key=?",(idem,)).fetchone()
    if existing:con.close();return _publish_item(existing)
    pid=str(uuid.uuid4());now=ts()
    meta={"variant_id":variant["id"],"approval_required":True,
          "approval_decision_id":approval_decision_id,"approved_at":now,
          "content_snapshot":content_snapshot,"content_snapshot_hash":snapshot_hash,
          "media_artifact_id":media.get("id"),"media_url":media.get("url") or "",
          "media_title":media.get("title") or "","media_mime_type":media.get("mime_type") or "",
          "media_edit_job_id":media_meta.get("edit_job_id")}
    con.execute("""INSERT INTO publishing_queue(
        id,job_id,package_id,status,target,platform,scheduled_at,idempotency_key,attempt_count,
        external_post_id,external_url,last_error,created_at,updated_at,published_at,meta_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        pid,job_id,package["id"],"approved","manual","unspecified",None,idem,0,
        None,None,None,now,now,None,json.dumps(meta,ensure_ascii=False)
    ))
    con.commit();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(pid,)).fetchone();con.close()
    return _publish_item(row)

def get_publishing_queue(limit=100):
    con=db();rows=con.execute("SELECT * FROM publishing_queue ORDER BY updated_at DESC LIMIT ?",
                              (max(1,min(300,int(limit))),)).fetchall();con.close()
    items=[_publish_item(x) for x in rows];counts={}
    for item in items:counts[item["status"]]=counts.get(item["status"],0)+1
    return {"summary":{"total":len(items),**counts},"items":items,"adapter":get_publisher_adapter_registry()}

def _external_json(url,method="GET",payload=None,token=""):
    headers={"Accept":"application/json","User-Agent":"FactoryOS/3.80"};data=None
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8");headers["Content-Type"]="application/json"
    if token:headers["Authorization"]="Bearer "+token
    req=urlrequest.Request(url,data=data,headers=headers,method=method)
    with urlrequest.urlopen(req,timeout=25) as response:
        return json.loads(response.read().decode("utf-8","replace") or "{}")

def _publish_receipt(item,external_post_id,external_url="",published_at=None,source="adapter"):
    published_at=published_at or ts()
    content_snapshot=item.get("content_snapshot") or {}
    con=db();existing=con.execute("""SELECT id FROM artifacts WHERE job_id=? AND agent='Publisher'
                                    AND kind='publish_receipt' AND meta_json LIKE ? LIMIT 1""",
                                  (item["job_id"],f'%"publish_id": "{item["id"]}"%')).fetchone();con.close()
    if not existing:
        save_artifact("Publisher","publish_receipt",f"Published · {item['platform']}",
                      json.dumps({"external_post_id":external_post_id,"external_url":external_url,
                                  "published_at":published_at,"platform":item["platform"],"media":item.get("media"),
                                  "content_snapshot":content_snapshot,
                                  "content_snapshot_hash":item.get("content_snapshot_hash") or ""},ensure_ascii=False,indent=2),
                      job_id=item["job_id"],meta={"publish_id":item["id"],"idempotency_key":item["idempotency_key"],
                                                 "platform":item["platform"],"source":source,
                                                 "approval_decision_id":item.get("approval_decision_id"),
                                                 "content_snapshot_hash":item.get("content_snapshot_hash") or "",
                                                 "media_artifact_id":((item.get("media") or {}).get("artifact_id"))})
    con=db();con.execute("UPDATE jobs SET stage='publish',status='published',progress=90,updated_at=? WHERE id=?",(ts(),item["job_id"]));con.commit();con.close()
    event(item["job_id"],f"Publish confirmed: {item['platform']} · {external_post_id}")
    sync_cycle_for_publish(item["id"])

def _publish_via_adapter(item):
    if FACTORY_PUBLISHER_ADAPTER=="manual" or not FACTORY_PUBLISHER_ENDPOINT:
        return {"manual":True,"status":"publishing"}
    content=item.get("content_snapshot")
    if not isinstance(content,dict):
        con=db();row=con.execute("SELECT * FROM content_packages WHERE id=? AND job_id=?",(item["package_id"],item["job_id"])).fetchone();con.close()
        package_record=_content_package_dict(row) if row else None
        if not package_record:raise RuntimeError("Approved Content Package snapshot is unavailable")
        content=_publish_content_snapshot(package_record)
    media=item.get("media") or {}
    payload={"idempotency_key":item["idempotency_key"],"publish_id":item["id"],"job_id":item["job_id"],
             "package_id":item["package_id"],"approval_decision_id":item.get("approval_decision_id"),
             "content_snapshot_hash":item.get("content_snapshot_hash") or _publish_snapshot_hash(content),
             "target":item["target"],"platform":item["platform"],
             "scheduled_at":item.get("scheduled_at"),"media_url":media.get("url") or "",
             "media_artifact_id":media.get("artifact_id"),"media":media,"content":content}
    result=_external_json(FACTORY_PUBLISHER_ENDPOINT,"POST",payload,FACTORY_PUBLISHER_TOKEN)
    return {"manual":False,"status":str(result.get("status") or "publishing"),
            "external_post_id":result.get("external_post_id") or result.get("id"),
            "external_url":result.get("external_url") or result.get("url"),"raw":result}

# v4.0 — Autonomous Content Factory coordinator.
# It automates handoffs and production up to the human review gate. It never auto-approves or auto-publishes.
FACTORY_CYCLE_MAX_SIGNALS=max(1,min(20,int(os.environ.get("FACTORY_CYCLE_MAX_SIGNALS","8"))))
active_factory_cycles=set()

def cycle_event(cycle_id,phase,message,meta=None):
    con=db();con.execute("""INSERT INTO factory_cycle_events(cycle_id,ts,phase,message,meta_json)
                            VALUES(?,?,?,?,?)""",(cycle_id,ts(),phase,message,json.dumps(meta or {},ensure_ascii=False)))
    con.commit();con.close()

def _cycle_dict(row):
    if not row:return None
    d=dict(row)
    d["source_signal_ids"]=_decode_json(d.pop("source_signal_ids_json","[]"),[])
    d["learning"]=_decode_json(d.pop("learning_json","{}"),{})
    d["meta"]=_decode_json(d.pop("meta_json","{}"),{})
    return d

def get_factory_cycle(cycle_id,hydrate=False):
    con=db();row=con.execute("SELECT * FROM factory_cycles WHERE id=?",(cycle_id,)).fetchone();con.close()
    cycle=_cycle_dict(row)
    if not cycle or not hydrate:return cycle
    con=db()
    signals=[]
    if cycle["source_signal_ids"]:
        placeholders=",".join("?" for _ in cycle["source_signal_ids"])
        rows=con.execute(f"SELECT * FROM source_signals WHERE id IN ({placeholders})",cycle["source_signal_ids"]).fetchall()
        by_id={x["id"]:dict(x) for x in rows};signals=[by_id[x] for x in cycle["source_signal_ids"] if x in by_id]
    idea=_idea_dict(con.execute("SELECT * FROM content_ideas WHERE id=?",(cycle["idea_id"],)).fetchone()) if cycle.get("idea_id") else None
    events=[dict(x) for x in con.execute("SELECT * FROM factory_cycle_events WHERE cycle_id=? ORDER BY id DESC LIMIT 30",(cycle_id,)).fetchall()]
    for e in events:e["meta"]=_decode_json(e.pop("meta_json","{}"),{})
    con.close()
    job=get_job(cycle.get("job_id")) if cycle.get("job_id") else None
    publish=None;performance=None
    if cycle.get("publish_id"):
        con=db();pr=con.execute("SELECT * FROM publishing_queue WHERE id=?",(cycle["publish_id"],)).fetchone();con.close()
        publish=_publish_item(pr)
        if publish and publish.get("status")=="published":performance=_performance_item(publish)
    return {**cycle,"signals":signals,"idea":idea,"job":job,"publish":publish,"performance":performance,"events":events,
            "workflow":_workflow_version(cycle.get("workflow_version_id")) if cycle.get("workflow_version_id") else None}

def get_factory_cycles(limit=80):
    con=db();rows=con.execute("SELECT * FROM factory_cycles ORDER BY updated_at DESC LIMIT ?",
                              (max(1,min(200,int(limit))),)).fetchall();con.close()
    cycles=[get_factory_cycle(x["id"],True) for x in rows]
    counts={}
    for c in cycles:counts[c["status"]]=counts.get(c["status"],0)+1
    return {"summary":{"cycles":len(cycles),"active":sum(1 for x in cycles if x["status"] in ("ready","running","waiting_approval","approved","scheduled","published","measured")),
                       **counts},"cycles":cycles,
            "safety_note":"Autopilot stops at human approval. Publishing remains a separate explicit action and paid model work requires cost confirmation."}

def _new_signal_ids(limit=None):
    con=db();rows=con.execute("""SELECT id FROM source_signals WHERE status='new'
                                 ORDER BY created_at DESC LIMIT ?""",(int(limit or FACTORY_CYCLE_MAX_SIGNALS),)).fetchall();con.close()
    return [x["id"] for x in rows]

def create_factory_cycle(payload,source="owner"):
    signal_ids=list(dict.fromkeys(str(x).strip() for x in (payload.signal_ids or []) if str(x).strip()))
    if not signal_ids and not payload.idea_id:
        signal_ids=_new_signal_ids()
    con=db()
    if signal_ids:
        placeholders=",".join("?" for _ in signal_ids)
        found={x["id"] for x in con.execute(f"SELECT id FROM source_signals WHERE id IN ({placeholders})",signal_ids).fetchall()}
        missing=[x for x in signal_ids if x not in found]
        if missing:con.close();raise ValueError("Unknown source signal id(s): "+", ".join(missing))
    idea_id=(payload.idea_id or "").strip() or None
    if idea_id and not con.execute("SELECT id FROM content_ideas WHERE id=?",(idea_id,)).fetchone():
        con.close();raise ValueError("Idea not found")
    parent=(payload.parent_cycle_id or "").strip() or None
    if parent and not con.execute("SELECT id FROM factory_cycles WHERE id=?",(parent,)).fetchone():
        con.close();raise ValueError("Parent cycle not found")
    cycle_id=str(uuid.uuid4());now=ts();active=_active_workflow_version()
    meta={"created_by":source,"language":(payload.language or "English").strip(),"approval_gate":"required",
          "publisher_execution":"explicit","paid_generation":"confirmation_required"}
    con.execute("""INSERT INTO factory_cycles(
        id,parent_cycle_id,status,phase,source_signal_ids_json,idea_id,job_id,publish_id,workflow_version_id,
        created_at,updated_at,started_at,completed_at,last_error,learning_json,meta_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        cycle_id,parent,"ready","idea" if idea_id else "signals",json.dumps(signal_ids),idea_id,None,None,active["id"],
        now,now,None,None,"","{}",json.dumps(meta,ensure_ascii=False)
    ))
    con.commit();con.close()
    cycle_event(cycle_id,"signals",f"Factory cycle created with {len(signal_ids)} signal(s)"+(" and a preselected idea" if idea_id else ""),
                {"workflow_version_id":active["id"],"source":source})
    return get_factory_cycle(cycle_id,True)

def _cycle_update(cycle_id,**fields):
    allowed={"status","phase","idea_id","job_id","publish_id","workflow_version_id","started_at","completed_at","last_error","learning_json","meta_json","source_signal_ids_json"}
    clean={k:v for k,v in fields.items() if k in allowed}
    if not clean:return get_factory_cycle(cycle_id)
    clean["updated_at"]=ts()
    sets=",".join(f"{k}=?" for k in clean)
    con=db();con.execute(f"UPDATE factory_cycles SET {sets} WHERE id=?",(*clean.values(),cycle_id));con.commit();con.close()
    return get_factory_cycle(cycle_id,True)

def _cycle_for_job(job_id):
    if not job_id:return None
    con=db();row=con.execute("SELECT * FROM factory_cycles WHERE job_id=? ORDER BY updated_at DESC LIMIT 1",(job_id,)).fetchone();con.close()
    return _cycle_dict(row)

def _cycle_for_publish(publish_id):
    if not publish_id:return None
    con=db();row=con.execute("SELECT * FROM factory_cycles WHERE publish_id=? ORDER BY updated_at DESC LIMIT 1",(publish_id,)).fetchone();con.close()
    return _cycle_dict(row)

def _idea_job_brief(idea):
    research=idea.get("research") or {};verification=idea.get("verification") or {}
    source_lines=[str(x) for x in (idea.get("source_links") or []) if str(x).strip()]
    claims=research.get("claims") or []
    return "\n".join([
        f"ANGLE: {idea.get('angle') or ''}",
        f"AUDIENCE: {idea.get('audience') or ''}",
        f"WHY NOW: {idea.get('why_now') or ''}",
        f"RESEARCH SUMMARY: {research.get('research_summary') or ''}",
        "EVIDENCE-BOUND CLAIMS: "+("; ".join(str(x) for x in claims[:8]) if claims else "Use persisted source signals and state uncertainty."),
        "SOURCE LINKS: "+(" | ".join(source_lines[:10]) if source_lines else "See linked source signals in Content Brain."),
        f"VERIFICATION: {verification.get('verification_notes') or ''}",
        "PROVENANCE: Created directly from FactoryOS Content Brain. Preserve source boundaries and human approval before publish.",
    ]).strip()

def create_job_from_idea(idea_id,language="English"):
    con=db();idea=_idea_dict(con.execute("SELECT * FROM content_ideas WHERE id=?",(idea_id,)).fetchone())
    if not idea:con.close();raise ValueError("Idea not found")
    existing=con.execute("""SELECT j.* FROM job_idea_links l JOIN jobs j ON j.id=l.job_id
                            WHERE l.idea_id=? ORDER BY l.created_at DESC LIMIT 1""",(idea_id,)).fetchone()
    if existing:
        con.close();return {"created":False,"job":dict(existing),"idea":idea}
    if idea.get("status")=="rejected":
        con.close();raise ValueError("Rejected idea cannot enter production")
    if idea.get("verified_at") is None and FACTORY_LLM_API_KEY:
        con.close();raise ValueError("Live-mode idea must pass Content Brain verification before production")
    jid=str(uuid.uuid4());now=ts();title=idea.get("title") or "FactoryOS content idea"
    brief=_idea_job_brief(idea)
    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid,title,brief,"inbox","Faceless","Short only",language or "English",1,"idle",0,now,now))
    con.execute("""INSERT INTO job_idea_links(job_id,idea_id,created_at) VALUES(?,?,?)
                   ON CONFLICT(job_id) DO UPDATE SET idea_id=excluded.idea_id,created_at=excluded.created_at""",
                (jid,idea_id,now))
    provenance=dict(idea.get("provenance") or {});provenance["production_job_id"]=jid;provenance["production_started_at"]=now
    con.execute("UPDATE content_ideas SET status='in_production',provenance_json=?,updated_at=? WHERE id=?",
                (json.dumps(provenance,ensure_ascii=False),now,idea_id))
    con.commit();con.close()
    event(jid,f"Created directly from Content Brain idea {idea_id}")
    global selected_job_id;selected_job_id=jid
    return {"created":True,"job":get_job(jid),"idea":{**idea,"status":"in_production","provenance":provenance}}

def estimate_factory_cycle_cost(cycle_id,max_ideas=3):
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:raise ValueError("Factory cycle not found")
    if not FACTORY_LLM_API_KEY:
        return {"estimated_max_usd":0.0,"paid_calls_possible":False,"note":"Demo mode uses deterministic zero-spend workers."}
    # Conservative reserve: Scout + 3 Content Brain workers per idea + production worker set.
    idea_count=max(1,min(3,int(max_ideas or 3)))
    content_calls=0 if cycle.get("idea_id") else 1+(3*idea_count)
    production_calls=0 if cycle.get("job") and cycle["job"].get("status")=="waiting_approval" else max(1,len(LLM_LIVE_AGENTS))
    calls=content_calls+production_calls
    per_call=(5000*FACTORY_LLM_INPUT_USD_PER_1M + FACTORY_LLM_MAX_OUTPUT_TOKENS*FACTORY_LLM_OUTPUT_USD_PER_1M)/1_000_000
    estimate=round(calls*per_call,6)
    return {"estimated_max_usd":estimate,"paid_calls_possible":True,"estimated_calls":calls,
            "note":"Conservative ceiling for confirmation only; real provider usage is recorded per worker and hard daily/job budgets still apply."}

def _select_cycle_idea(candidates):
    usable=[x for x in candidates if x.get("status")=="shortlisted" and not x.get("rejection_reason")]
    if not usable:usable=[x for x in candidates if x.get("status")=="shortlisted"]
    if not usable:return None
    usable.sort(key=lambda x:(float(x.get("score") or 0),x.get("verified_at") or ""),reverse=True)
    return usable[0]

async def _run_factory_cycle_to_review(cycle_id,max_ideas=3,language="English"):
    active_factory_cycles.add(cycle_id)
    try:
        cycle=get_factory_cycle(cycle_id,True)
        if not cycle:raise ValueError("Factory cycle not found")
        if cycle.get("job") and cycle["job"].get("status")=="waiting_approval":
            _cycle_update(cycle_id,status="waiting_approval",phase="approval",last_error="")
            return
        _cycle_update(cycle_id,status="running",started_at=cycle.get("started_at") or ts(),last_error="")
        cycle_event(cycle_id,cycle.get("phase") or "signals","Autopilot run started",{"language":language})

        signal_ids=cycle.get("source_signal_ids") or []
        if not signal_ids and not cycle.get("idea_id"):
            collected=await asyncio.to_thread(collect_configured_signals,FACTORY_CYCLE_MAX_SIGNALS) if FACTORY_SIGNAL_FEEDS else {"created":[]}
            signal_ids=[x["id"] for x in collected.get("created") or []] or _new_signal_ids()
            if not signal_ids:raise RuntimeError("No source signals are available. Add a signal or configure RSS feeds.")
            _cycle_update(cycle_id,source_signal_ids_json=json.dumps(signal_ids),phase="ideas")
            cycle_event(cycle_id,"signals",f"Attached {len(signal_ids)} available signal(s)")

        idea_id=cycle.get("idea_id")
        if not idea_id:
            _cycle_update(cycle_id,phase="ideas")
            generated=await generate_ideas_from_signals(IdeaGenerateRequest(signal_ids=signal_ids,max_ideas=max_ideas,language=language))
            generated_ids=[x["id"] for x in generated.get("ideas") or []]
            if not generated_ids:raise RuntimeError("Content Brain generated no usable ideas")
            cycle_event(cycle_id,"ideas",f"Scout generated {len(generated_ids)} idea candidate(s)",
                        {"run_id":generated.get("run_id"),"cost_usd":generated.get("cost_usd")})
            processed=await process_content_brain_ideas(IdeaProcessRequest(idea_ids=generated_ids,max_ideas=max_ideas,language=language))
            chosen=_select_cycle_idea(processed.get("processed") or [])
            if not chosen:raise RuntimeError("Idea Verifier did not shortlist a production-ready idea")
            idea_id=chosen["id"]
            con=db();con.execute("UPDATE content_ideas SET status='selected',updated_at=? WHERE id=?",(ts(),idea_id));con.commit();con.close()
            _cycle_update(cycle_id,idea_id=idea_id,phase="production")
            cycle_event(cycle_id,"ideas",f"Verified idea selected: {chosen['title']}",{"idea_id":idea_id,"score":chosen.get("score")})
        else:
            con=db();idea=_idea_dict(con.execute("SELECT * FROM content_ideas WHERE id=?",(idea_id,)).fetchone());con.close()
            if not idea:raise RuntimeError("Cycle idea no longer exists")
            if FACTORY_LLM_API_KEY and not idea.get("verified_at"):
                processed=await process_content_brain_ideas(IdeaProcessRequest(idea_ids=[idea_id],max_ideas=1,language=language))
                chosen=_select_cycle_idea(processed.get("processed") or [])
                if not chosen:raise RuntimeError("Preselected idea did not pass verification")
                con=db();con.execute("UPDATE content_ideas SET status='selected',updated_at=? WHERE id=?",(ts(),idea_id));con.commit();con.close()

        bridge=create_job_from_idea(idea_id,language)
        job=bridge["job"];workflow=_workflow_context(job["id"],lock=True)["version"]
        _cycle_update(cycle_id,job_id=job["id"],workflow_version_id=workflow["id"],phase="production")
        cycle_event(cycle_id,"production","Content Brain → production handoff completed",
                    {"job_id":job["id"],"idea_id":idea_id,"workflow_version_id":workflow["id"]})
        running_jobs.add(job["id"])
        await run_until_review(job["id"])
        job=get_job(job["id"])
        if not job or job.get("status")!="waiting_approval":
            raise RuntimeError("Production did not reach the human approval gate")
        _cycle_update(cycle_id,status="waiting_approval",phase="approval",last_error="")
        cycle_event(cycle_id,"approval","Production package is ready; Autopilot stopped at the human approval gate",
                    {"job_id":job["id"]})
        await broadcast({"type":"factory_cycle","action":"waiting_approval","cycleId":cycle_id,"jobId":job["id"]})
    except Exception as exc:
        _cycle_update(cycle_id,status="failed",last_error=str(exc)[:1200])
        cycle_event(cycle_id,"error",f"Autopilot failed: {str(exc)[:500]}")
        await broadcast({"type":"factory_cycle","action":"failed","cycleId":cycle_id,"error":str(exc)[:500]})
    finally:
        active_factory_cycles.discard(cycle_id)

def _cycle_metric_baseline(current_item,metric):
    platform=(current_item.get("publish") or {}).get("platform")
    current_publish=(current_item.get("publish") or {}).get("id")
    values=[]
    for item in get_performance_dashboard(200).get("items") or []:
        if (item.get("publish") or {}).get("id")==current_publish:continue
        if platform and (item.get("publish") or {}).get("platform")!=platform:continue
        value=((item.get("latest") or {}).get("metrics") or {}).get(metric)
        if isinstance(value,(int,float)):values.append(float(value))
    return round(sum(values)/len(values),4) if values else None,len(values)

def derive_cycle_learning(cycle_id):
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:raise ValueError("Factory cycle not found")
    perf=cycle.get("performance")
    if not perf or not perf.get("latest"):
        return {"ready":False,"reason":"No real performance snapshot exists for this cycle yet."}
    metrics=(perf["latest"].get("metrics") or {})
    metric=next((x for x in ("retention_pct","completion_rate_pct","views") if isinstance(metrics.get(x),(int,float))),None)
    current=float(metrics[metric]) if metric else None
    baseline,count=_cycle_metric_baseline(perf,metric) if metric else (None,0)
    delta_pct=None
    if current is not None and baseline not in (None,0):delta_pct=round((current-baseline)/abs(baseline)*100,2)
    selected=_selected_production_variant(cycle["job_id"]) if cycle.get("job_id") else None
    learning={
        "generated_at":ts(),"publish_id":cycle.get("publish_id"),"job_id":cycle.get("job_id"),
        "primary_observed_metric":metric,"current_value":current,"comparable_baseline":baseline,
        "comparable_items":count,"observed_delta_pct":delta_pct,
        "production_cost_usd":perf.get("attribution",{}).get("production_cost_usd"),
        "angle":perf.get("attribution",{}).get("angle"),"hook":perf.get("attribution",{}).get("hook"),
        "workflow_version_id":perf.get("attribution",{}).get("workflow_version_id"),
        "statement":"Observed platform performance is stored as evidence. It is not treated as causal proof; workflow changes still require a controlled experiment."
    }
    recommendation="Collect more comparable real performance before proposing a workflow change."
    proposal_id=None
    if metric in ("retention_pct","completion_rate_pct") and baseline is not None and count>=2 and delta_pct is not None:
        hook=(perf.get("attribution",{}).get("hook") or "").strip()
        if delta_pct>=5 and hook:
            recommendation=f"Observed {metric} is {delta_pct:.1f}% above the comparable baseline. Test this hook structure in a controlled experiment before rollout."
            proposal=create_improvement_proposal(ImprovementProposalCreate(
                title=f"Test measured hook pattern from cycle {cycle_id[:8]}",
                rationale=recommendation,
                hypothesis=f"A hook structure based on the measured cycle may improve {metric} by at least 5% versus the active control workflow.",
                change={"hook_pattern":f"Test a structurally similar opening to this measured hook while preserving evidence boundaries: {hook[:500]}"},
                evidence=[{"type":"performance_snapshot","publish_id":cycle.get("publish_id"),"metric":metric,
                           "current":current,"baseline":baseline,"comparable_items":count,"observed_delta_pct":delta_pct}]
            ))
            con=db();con.execute("UPDATE improvement_proposals SET source='Factory Intelligence' WHERE id=?",(proposal["id"],));con.commit();con.close()
            proposal_id=proposal["id"]
        elif delta_pct<=-5:
            recommendation=f"Observed {metric} is {abs(delta_pct):.1f}% below the comparable baseline. Test a stronger mechanism-first opening rather than promoting the current pattern."
            proposal=create_improvement_proposal(ImprovementProposalCreate(
                title=f"Test hook recovery after cycle {cycle_id[:8]}",
                rationale=recommendation,
                hypothesis=f"A clearer mechanism-first opening should recover at least 5% of {metric} versus the current active workflow.",
                change={"hook_pattern":"Test a concrete mechanism-first opening in the first 1–3 seconds; avoid vague setup and preserve evidence boundaries."},
                evidence=[{"type":"performance_snapshot","publish_id":cycle.get("publish_id"),"metric":metric,
                           "current":current,"baseline":baseline,"comparable_items":count,"observed_delta_pct":delta_pct}]
            ))
            con=db();con.execute("UPDATE improvement_proposals SET source='Factory Intelligence' WHERE id=?",(proposal["id"],));con.commit();con.close()
            proposal_id=proposal["id"]
    learning["recommendation"]=recommendation;learning["improvement_proposal_id"]=proposal_id
    _cycle_update(cycle_id,status="learning_ready",phase="learning",learning_json=json.dumps(learning,ensure_ascii=False),completed_at=ts())
    save_artifact("Analyst","cycle_learning",f"Factory Cycle learning · {cycle_id[:8]}",
                  json.dumps(learning,ensure_ascii=False,indent=2),job_id=cycle.get("job_id"),
                  meta={"cycle_id":cycle_id,"publish_id":cycle.get("publish_id"),"proposal_id":proposal_id})
    cycle_event(cycle_id,"learning",recommendation,{"proposal_id":proposal_id})
    return {"ready":True,"learning":learning}

def sync_factory_cycle(cycle_id,derive_learning_if_possible=True):
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:return None
    job=cycle.get("job")
    publish=cycle.get("publish")
    if cycle.get("job_id") and not publish:
        con=db();row=con.execute("SELECT * FROM publishing_queue WHERE job_id=? ORDER BY updated_at DESC LIMIT 1",(cycle["job_id"],)).fetchone();con.close()
        if row:
            publish=_publish_item(row);_cycle_update(cycle_id,publish_id=publish["id"])
    status=cycle.get("status");phase=cycle.get("phase")
    if job:
        if job.get("status")=="waiting_approval":status,phase="waiting_approval","approval"
        elif job.get("status")=="approved":status,phase="approved","publishing"
        elif job.get("status")=="rejected":status,phase="rejected","approval"
        elif job.get("status")=="failed":status,phase="failed","production"
    if publish:
        pstatus=publish.get("status")
        if pstatus=="scheduled":status,phase="scheduled","publishing"
        elif pstatus=="publishing":status,phase="approved","publishing"
        elif pstatus=="published":status,phase="published","analytics"
        elif pstatus=="failed":status,phase="failed","publishing"
    con=db();snap=None
    if publish:snap=con.execute("SELECT id FROM performance_snapshots WHERE publish_id=? ORDER BY captured_at DESC LIMIT 1",(publish["id"],)).fetchone()
    con.close()
    if snap:status,phase="measured","analytics"
    _cycle_update(cycle_id,status=status,phase=phase,publish_id=(publish or {}).get("id") or cycle.get("publish_id"))
    if snap and derive_learning_if_possible:
        try:derive_cycle_learning(cycle_id)
        except Exception as exc:cycle_event(cycle_id,"learning",f"Learning derivation deferred: {str(exc)[:300]}")
    return get_factory_cycle(cycle_id,True)

def sync_cycle_for_job(job_id):
    cycle=_cycle_for_job(job_id)
    return sync_factory_cycle(cycle["id"]) if cycle else None

def sync_cycle_for_publish(publish_id):
    cycle=_cycle_for_publish(publish_id)
    return sync_factory_cycle(cycle["id"]) if cycle else None

async def factory_cycle_reconcile_loop():
    while True:
        try:
            con=db();rows=con.execute("""SELECT id FROM factory_cycles
                                        WHERE status NOT IN ('failed','rejected','learning_ready','completed')
                                        ORDER BY updated_at DESC LIMIT 100""").fetchall();con.close()
            for row in rows:sync_factory_cycle(row["id"],True)
        except Exception as exc:
            print(json.dumps({"event":"FACTORY_CYCLE_RECONCILE_ERROR","error":str(exc)[:400]}),flush=True)
        await asyncio.sleep(60)


async def run_real_world_pilot_once():
    tag=FACTORY_REAL_PILOT_TAG
    if not tag:return
    if not FACTORY_LLM_API_KEY:
        print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"skipped","reason":"llm_not_configured"}),flush=True);return

    con=db();existing=con.execute("SELECT * FROM system_verifications WHERE tag=?",(tag,)).fetchone();con.close()
    source_rows=[];quote_usd=None;cycle_id=None;job_id=None
    if existing:
        row=dict(existing)
        try:meta=json.loads(row.get("detail") or "{}")
        except Exception:meta={}
        if not (row.get("status")=="started" and FACTORY_REAL_PILOT_RESUME_STARTED and meta.get("cycle_id")):
            print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"skip_existing","existing_status":row.get("status")}),flush=True);return
        started=row.get("started_at");cycle_id=meta.get("cycle_id");quote_usd=meta.get("quote_usd")
        source_urls=meta.get("source_urls") or []
        spent=_pilot_spend_since(started)
        if spent >= FACTORY_REAL_PILOT_MAX_USD:
            _verification_update(tag,{"status":"failed","finished_at":ts(),"cost_usd":spent,
                "detail":json.dumps({**meta,"phase":"failed","error":"Pilot budget exhausted before safe resume","actual_cost_usd":spent},ensure_ascii=False)})
            print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"failed","cycle_id":cycle_id,"actual_cost_usd":spent,"error":"budget exhausted before safe resume"}),flush=True);return
        print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"resuming","cycle_id":cycle_id,
                          "spent_so_far_usd":spent,"max_usd":FACTORY_REAL_PILOT_MAX_USD}),flush=True)
    else:
        started=ts()
        con=db();con.execute("""INSERT INTO system_verifications(tag,status,started_at,detail)
                               VALUES(?,?,?,?)""",(tag,"started",started,json.dumps({
                                   "phase":"fenced","max_usd":FACTORY_REAL_PILOT_MAX_USD,"approval_gate_reached":False
                               })));con.commit();con.close()
        try:
            for signal in _parse_real_pilot_signals():
                result=ingest_source_signal(SignalCreate(
                    title=signal["title"],url=signal["url"],content=signal["content"],
                    source_type="real_pilot_web",topic=signal["topic"]
                ));source_rows.append(result["signal"])
            cycle=create_factory_cycle(FactoryCycleCreate(
                signal_ids=[x["id"] for x in source_rows],language=FACTORY_REAL_PILOT_LANGUAGE
            ),source="v4.1_real_world_pilot")
            cycle_id=cycle["id"];quote=estimate_factory_cycle_cost(cycle_id,FACTORY_REAL_PILOT_MAX_IDEAS)
            quote_usd=float(quote.get("estimated_max_usd") or 0)
            if not quote.get("paid_calls_possible"):raise RuntimeError("Pilot expected live paid LLM work but provider quote reports zero-spend mode")
            if quote_usd > FACTORY_REAL_PILOT_MAX_USD:
                raise RuntimeError(f"Pilot quote USD {quote_usd:.6f} exceeds hard pilot ceiling USD {FACTORY_REAL_PILOT_MAX_USD:.6f}")
            meta={"phase":"running","cycle_id":cycle_id,"source_urls":[x["url"] for x in source_rows],
                  "quote_usd":quote_usd,"max_usd":FACTORY_REAL_PILOT_MAX_USD,"approval_gate_reached":False}
            _verification_update(tag,{"detail":json.dumps(meta,ensure_ascii=False)})
            print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"running","cycle_id":cycle_id,
                              "quote_usd":quote_usd,"max_usd":FACTORY_REAL_PILOT_MAX_USD,
                              "sources":meta["source_urls"]}),flush=True)
        except Exception as exc:
            spent=_pilot_spend_since(started)
            _verification_update(tag,{"status":"failed","finished_at":ts(),"cost_usd":spent,
                "detail":json.dumps({"phase":"failed","cycle_id":cycle_id,"max_usd":FACTORY_REAL_PILOT_MAX_USD,
                                     "approval_gate_reached":False,"actual_cost_usd":spent,"error":str(exc)[:1000]},ensure_ascii=False)})
            print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"failed","cycle_id":cycle_id,
                              "actual_cost_usd":spent,"error":str(exc)[:700]}),flush=True);return

    real_pilot_runtime.update({"active":True,"tag":tag,"started_at":started,"max_usd":FACTORY_REAL_PILOT_MAX_USD})
    try:
        await _run_factory_cycle_to_review(cycle_id,FACTORY_REAL_PILOT_MAX_IDEAS,FACTORY_REAL_PILOT_LANGUAGE)
        cycle=get_factory_cycle(cycle_id,True);job_id=cycle.get("job_id")
        spent=_pilot_spend_since(started)
        con=db();totals=con.execute("""SELECT COUNT(*) live_runs,COALESCE(SUM(input_tokens),0) input_tokens,
                                             COALESCE(SUM(output_tokens),0) output_tokens
                                      FROM agent_runs WHERE started_at>=? AND model!='simulation-v3'""",(started,)).fetchone();con.close()
        approval_reached=bool(cycle.get("status")=="waiting_approval" and cycle.get("job",{}).get("status")=="waiting_approval")
        no_publish=not bool(cycle.get("publish_id"));within_budget=spent<=FACTORY_REAL_PILOT_MAX_USD+1e-9
        passed=approval_reached and no_publish and within_budget and spent>0
        idea=cycle.get("idea") or {};old=get_paid_verification(tag)
        try:old_meta=json.loads(old.get("detail") or "{}")
        except Exception:old_meta={}
        detail={**old_meta,"phase":"waiting_approval" if approval_reached else cycle.get("phase"),
                "cycle_id":cycle_id,"job_id":job_id,"idea_id":cycle.get("idea_id"),"idea_title":idea.get("title"),
                "quote_usd":quote_usd or old_meta.get("quote_usd"),"max_usd":FACTORY_REAL_PILOT_MAX_USD,
                "approval_gate_reached":approval_reached,"publish_created":not no_publish,
                "actual_cost_usd":spent,"cycle_status":cycle.get("status")}
        status="passed" if passed else "failed"
        _verification_update(tag,{"status":status,"job_id":job_id,"finished_at":ts(),
                                  "live_runs":int(totals["live_runs"] or 0),"input_tokens":int(totals["input_tokens"] or 0),
                                  "output_tokens":int(totals["output_tokens"] or 0),"cost_usd":spent,
                                  "detail":json.dumps(detail,ensure_ascii=False)})
        print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":status,"cycle_id":cycle_id,"job_id":job_id,
                          "idea_title":idea.get("title"),"actual_cost_usd":spent,
                          "approval_gate_reached":approval_reached,"publish_created":not no_publish,
                          "live_runs":int(totals["live_runs"] or 0),
                          "total_tokens":int(totals["input_tokens"] or 0)+int(totals["output_tokens"] or 0)}),flush=True)
    except Exception as exc:
        spent=_pilot_spend_since(started);old=get_paid_verification(tag)
        try:old_meta=json.loads(old.get("detail") or "{}")
        except Exception:old_meta={}
        detail={**old_meta,"phase":"failed","cycle_id":cycle_id,"job_id":job_id,"max_usd":FACTORY_REAL_PILOT_MAX_USD,
                "approval_gate_reached":False,"actual_cost_usd":spent,"error":str(exc)[:1000]}
        _verification_update(tag,{"status":"failed","job_id":job_id,"finished_at":ts(),"cost_usd":spent,
                                  "detail":json.dumps(detail,ensure_ascii=False)})
        print(json.dumps({"event":"V41_REAL_PILOT","tag":tag,"status":"failed","cycle_id":cycle_id,"job_id":job_id,
                          "actual_cost_usd":spent,"error":str(exc)[:700]}),flush=True)
    finally:
        real_pilot_runtime["active"]=False

def _approval_summary():
    con=db()
    waiting=int(con.execute("SELECT COUNT(*) c FROM jobs WHERE status='waiting_approval'").fetchone()["c"] or 0)
    decisions=int(con.execute("SELECT COUNT(*) c FROM approval_decisions").fetchone()["c"] or 0)
    con.close();return {"waiting":waiting,"decisions":decisions}

def _publishing_summary():
    con=db();rows=con.execute("SELECT status,COUNT(*) c FROM publishing_queue GROUP BY status").fetchall();con.close()
    return {x["status"]:x["c"] for x in rows}

def _performance_summary():
    con=db()
    snapshots=int(con.execute("SELECT COUNT(*) c FROM performance_snapshots").fetchone()["c"] or 0)
    published=int(con.execute("SELECT COUNT(*) c FROM publishing_queue WHERE status='published'").fetchone()["c"] or 0)
    con.close();return {"snapshots":snapshots,"published_items":published}

def get_approval_queue(limit=60):
    con=db();jobs=[dict(x) for x in con.execute(
        """SELECT * FROM jobs WHERE status IN ('waiting_approval','approved','rejected')
           ORDER BY updated_at DESC LIMIT ?""",(max(1,min(200,int(limit))),)).fetchall()];con.close()
    items=[]
    for job in jobs:
        package=get_content_package(job["id"]);variants=get_job_variants(job["id"])
        con=db();pub=con.execute("SELECT * FROM publishing_queue WHERE job_id=? ORDER BY updated_at DESC LIMIT 1",
                                 (job["id"],)).fetchone();con.close()
        package_record=package.get("package_record")
        variant_count=int((variants.get("summary") or {}).get("variants") or 0)
        media_review=_media_review_state(job["id"])
        review_ready=bool(package_record and package_record.get("status")=="ready" and variant_count>0 and media_review.get("ready"))
        items.append({"job":job,"package":package_record,"package_status":package.get("status"),
                      "variants":variants,"preview":_latest_render_preview(job["id"]),"media_review":media_review,
                      "history":get_approval_history(job["id"],20),"variant_diff":get_variant_diff(job["id"]),
                      "publish":_publish_item(pub),"review_ready":review_ready,
                      "legacy_incomplete":bool(not package_record or variant_count==0)})
    return {"summary":{"items":len(items),
                       "waiting":sum(1 for x in items if x["job"]["status"]=="waiting_approval"),
                       "approved":sum(1 for x in items if x["job"]["status"]=="approved"),
                       "rejected":sum(1 for x in items if x["job"]["status"]=="rejected")},
            "items":items}

def _performance_item(publish):
    con=db()
    rows=con.execute("SELECT * FROM performance_snapshots WHERE publish_id=? ORDER BY captured_at",(publish["id"],)).fetchall()
    idea=con.execute("SELECT idea_id FROM job_idea_links WHERE job_id=?",(publish["job_id"],)).fetchone()
    con.close()
    snapshots=[]
    for row in rows:
        x=dict(row);x["metrics"]=_decode_json(x.pop("metrics_json","{}"),{});x["meta"]=_decode_json(x.pop("meta_json","{}"),{});snapshots.append(x)
    package=get_content_package(publish["job_id"]).get("package_record")
    variant=_selected_production_variant(publish["job_id"])
    latest=snapshots[-1] if snapshots else None;metrics=(latest or {}).get("metrics",{})
    cost=float(((package or {}).get("package") or {}).get("production_cost",{}).get("job_total_measured_usd") or get_job_cost(publish["job_id"]) or 0)
    views=metrics.get("views")
    cpk=round(cost/(float(views)/1000),6) if isinstance(views,(int,float)) and views>0 else None
    workflow=get_job_workflow_assignment(publish["job_id"])
    attribution={"idea_id":idea["idea_id"] if idea else None,"job_id":publish["job_id"],"package_id":publish["package_id"],
                 "variant_id":(variant or {}).get("id"),"variant_provenance":(variant or {}).get("provenance") or {},
                 "angle":(variant or {}).get("angle"),"hook":(variant or {}).get("optimized_hook") or (variant or {}).get("hook"),
                 "sources":((package or {}).get("package") or {}).get("source_list") or [],
                 "production_cost_usd":cost,
                 "workflow_version_id":(workflow or {}).get("workflow_version_id"),
                 "experiment_id":(workflow or {}).get("experiment_id"),"experiment_arm":(workflow or {}).get("arm"),
                 "factory_cycle_id":((_cycle_for_job(publish["job_id"]) or {}).get("id"))}
    return {"publish":publish,"snapshots":snapshots,"latest":latest,"attribution":attribution,"cost_per_1k_views_usd":cpk}

def get_performance_dashboard(limit=100):
    con=db();rows=con.execute("""SELECT * FROM publishing_queue WHERE status='published'
                                 ORDER BY published_at DESC,updated_at DESC LIMIT ?""",
                              (max(1,min(300,int(limit))),)).fetchall();con.close()
    items=[_performance_item(_publish_item(x)) for x in rows];cohorts={}
    for item in items:
        key=(item["attribution"].get("angle") or "unknown").strip()
        metrics=(item.get("latest") or {}).get("metrics",{})
        b=cohorts.setdefault(key,{"angle":key,"items":0,"views":0,"retention":[],"completion":[]})
        b["items"]+=1;b["views"]+=metrics.get("views") or 0
        if isinstance(metrics.get("retention_pct"),(int,float)):b["retention"].append(metrics["retention_pct"])
        if isinstance(metrics.get("completion_rate_pct"),(int,float)):b["completion"].append(metrics["completion_rate_pct"])
    cohort_rows=[]
    for b in cohorts.values():
        cohort_rows.append({"angle":b["angle"],"items":b["items"],"views":b["views"],
                            "avg_retention_pct":round(sum(b["retention"])/len(b["retention"]),2) if b["retention"] else None,
                            "avg_completion_rate_pct":round(sum(b["completion"])/len(b["completion"]),2) if b["completion"] else None})
    return {"summary":{"published_items":len(items),"measured_items":sum(1 for x in items if x.get("latest")),
                       "views":sum(((x.get("latest") or {}).get("metrics",{}).get("views") or 0) for x in items)},
            "items":items,"angle_cohorts":cohort_rows,"adapter":get_analytics_adapter_registry(),
            "measurement_note":"Missing platform metrics remain absent. Derived cost/outcome metrics exist only when their source metric exists."}

def record_performance_snapshot(payload):
    con=db();pub=con.execute("SELECT * FROM publishing_queue WHERE id=?",(payload.publish_id,)).fetchone()
    if not pub:con.close();raise ValueError("Published item not found")
    if pub["status"]!="published":con.close();raise ValueError("Performance can only be attached to a published item")
    metrics={}
    for key in PERFORMANCE_FIELDS:
        value=getattr(payload,key)
        if value is not None:metrics[key]=value
    if not metrics:con.close();raise ValueError("At least one real platform metric is required")
    snapshot_id=str(uuid.uuid4());captured=payload.captured_at or ts()
    con.execute("""INSERT INTO performance_snapshots(
        id,publish_id,job_id,platform,captured_at,metrics_json,source,meta_json
    ) VALUES(?,?,?,?,?,?,?,?)""",(
        snapshot_id,pub["id"],pub["job_id"],pub["platform"],captured,json.dumps(metrics),
        payload.source or "manual","{}"
    ))
    con.commit();con.close()
    save_artifact("Analyst","performance_snapshot",f"Performance snapshot · {pub['platform']}",
                  json.dumps(metrics,ensure_ascii=False,indent=2),job_id=pub["job_id"],
                  meta={"publish_id":pub["id"],"source":payload.source or "manual"})
    event(pub["job_id"],f"Performance snapshot recorded: {pub['platform']} · {', '.join(metrics.keys())}")
    sync_cycle_for_publish(pub["id"])
    return {"id":snapshot_id,"publish_id":pub["id"],"metrics":metrics,"captured_at":captured}

@app.get("/api/factory-cycles")
def factory_cycles(limit:int=80):
    return get_factory_cycles(limit)

@app.get("/api/factory-cycles/{cycle_id}")
def factory_cycle_detail(cycle_id:str):
    cycle=sync_factory_cycle(cycle_id,True)
    if not cycle:raise HTTPException(404,"Factory cycle not found")
    return cycle

@app.post("/api/factory-cycles")
async def new_factory_cycle(payload:FactoryCycleCreate):
    try:cycle=create_factory_cycle(payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"factory_cycle","action":"created","cycleId":cycle["id"]})
    return {"ok":True,"cycle":cycle}

@app.get("/api/factory-cycles/{cycle_id}/quote")
def factory_cycle_quote(cycle_id:str,max_ideas:int=3):
    try:return estimate_factory_cycle_cost(cycle_id,max_ideas)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post("/api/factory-cycles/{cycle_id}/run")
async def run_factory_cycle_api(cycle_id:str,payload:FactoryCycleRunRequest):
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:raise HTTPException(404,"Factory cycle not found")
    if cycle_id in active_factory_cycles:return {"ok":True,"message":"Factory cycle is already running"}
    try:quote=estimate_factory_cycle_cost(cycle_id,payload.max_ideas)
    except ValueError as exc:raise HTTPException(400,str(exc))
    if quote["paid_calls_possible"] and not payload.confirm_cost:
        return {"ok":False,"requiresCostConfirmation":True,"quote":quote,
                "message":"Confirm the conservative paid-work ceiling before Autopilot starts. Daily/job budgets remain hard limits."}
    asyncio.create_task(_run_factory_cycle_to_review(cycle_id,payload.max_ideas,payload.language))
    return {"ok":True,"started":True,"quote":quote,
            "message":"Autopilot started and will stop at the human approval gate."}

@app.post("/api/factory-cycles/{cycle_id}/sync")
async def sync_factory_cycle_api(cycle_id:str):
    cycle=sync_factory_cycle(cycle_id,True)
    if not cycle:raise HTTPException(404,"Factory cycle not found")
    await broadcast({"type":"factory_cycle","action":"synced","cycleId":cycle_id})
    return {"ok":True,"cycle":cycle}

@app.post("/api/factory-cycles/{cycle_id}/learn")
async def learn_factory_cycle(cycle_id:str):
    try:result=derive_cycle_learning(cycle_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"factory_cycle","action":"learning","cycleId":cycle_id})
    return result

@app.post("/api/factory-cycles/{cycle_id}/next")
async def next_factory_cycle(cycle_id:str):
    parent=get_factory_cycle(cycle_id,True)
    if not parent:raise HTTPException(404,"Factory cycle not found")
    child=create_factory_cycle(FactoryCycleCreate(language=(parent.get("meta") or {}).get("language","English"),parent_cycle_id=cycle_id))
    cycle_event(child["id"],"signals","Next cycle created using the currently active, owner-approved workflow",
                {"parent_cycle_id":cycle_id,"workflow_version_id":child.get("workflow_version_id")})
    await broadcast({"type":"factory_cycle","action":"next","cycleId":child["id"],"parentCycleId":cycle_id})
    return {"ok":True,"cycle":child}

@app.get("/api/approval")
def approval_studio(job_id: Optional[str]=None):
    data=get_approval_queue()
    if job_id:
        data["items"]=[x for x in data["items"] if x["job"]["id"]==job_id]
        data["summary"]["items"]=len(data["items"])
    data["regeneration_quotes"]={x:_estimated_regeneration_cost(x) for x in ("hook","script","caption","voice")}
    return data

@app.get("/api/jobs/{job_id}/approval/history")
def approval_history(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return {"history":get_approval_history(job_id),"variant_diff":get_variant_diff(job_id)}

@app.get("/api/jobs/{job_id}/approval/quote/{component}")
def approval_regeneration_quote(job_id:str,component:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    try:return _estimated_regeneration_cost(component)
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.post("/api/jobs/{job_id}/reject")
async def reject_job(job_id:str,payload:ApprovalRejectRequest):
    job=get_job(job_id)
    if not job:raise HTTPException(404,"Job not found")
    if job["status"]!="waiting_approval":return {"ok":False,"message":"Job is not waiting for approval"}
    reason=(payload.reason or "").strip()
    if not reason:return {"ok":False,"message":"Reject reason is required"}
    _record_approval(job_id,"rejected",reason)
    con=db();con.execute("UPDATE jobs SET status='rejected',stage='qa',updated_at=? WHERE id=?",(ts(),job_id));con.commit();con.close()
    event(job_id,f"Approval Studio: rejected — {reason[:180]}")
    sync_cycle_for_job(job_id)
    await broadcast({"type":"approval","jobId":job_id,"decision":"rejected"})
    return {"ok":True,"status":"rejected"}

@app.post("/api/jobs/{job_id}/approval/regenerate")
async def approval_regenerate(job_id:str,payload:ApprovalRegenerateRequest):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    component=(payload.component or "").strip().lower()
    try:quote=_estimated_regeneration_cost(component)
    except ValueError as exc:raise HTTPException(400,str(exc))
    if quote["estimated_model_cost_usd"]>0 and not payload.confirm_cost:
        return {"ok":False,"requiresCostConfirmation":True,"quote":quote}
    if component in ("hook","script"):
        selected=_selected_production_variant(job_id)
        if not selected:raise HTTPException(400,"Select a production variant first")
        try:result=await rerun_variant_component(job_id,selected["id"],component)
        except (ValueError,RuntimeError) as exc:raise HTTPException(503,str(exc))
        _record_approval(job_id,"regenerate",f"{component} targeted rerun",component,{"quote":quote})
        return {"ok":True,"quote":quote,"variants":result}
    if component=="caption":
        try:package=await _regenerate_caption(job_id)
        except (ValueError,RuntimeError) as exc:raise HTTPException(503,str(exc))
        return {"ok":True,"quote":quote,"package":package}
    await execute_agent("Voice Agent","voice",job_id,delay=0.0)
    con=db();con.execute("UPDATE jobs SET stage='render',status='idle',progress=?,updated_at=? WHERE id=?",
                        (int(STAGES.index("render")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close()
    _record_approval(job_id,"regenerate","Voice regenerated; Render and QA require rebuild","voice",{"quote":quote})
    event(job_id,"Approval Studio: voice regenerated; Render → QA invalidated")
    await broadcast({"type":"approval","jobId":job_id,"action":"regenerate_voice"})
    return {"ok":True,"quote":quote}

@app.post("/api/jobs/{job_id}/idea-link/{idea_id}")
async def api_link_job_idea(job_id:str,idea_id:str):
    try:return {"ok":True,**link_job_idea(job_id,idea_id)}
    except ValueError as exc:raise HTTPException(400,str(exc))

@app.get("/api/publisher-adapters")
def publisher_adapters():
    return get_publisher_adapter_registry()

@app.get("/api/publishing")
def publishing_queue(limit:int=100):
    return get_publishing_queue(limit)

@app.post("/api/publishing/{publish_id}/schedule")
async def schedule_publishing(publish_id:str,payload:PublishScheduleRequest):
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone()
    if not row:con.close();raise HTTPException(404,"Publish item not found")
    if row["status"]=="published":con.close();return {"ok":True,"item":_publish_item(row)}
    if row["status"] not in ("approved","scheduled","failed"):
        con.close();return {"ok":False,"message":"Only an approved or retryable publish item can be scheduled"}
    when=(payload.scheduled_at or ts()).strip();target=(payload.target or "manual").strip();platform=(payload.platform or "unspecified").strip()
    try:
        parsed=datetime.fromisoformat(when.replace("Z","+00:00"))
        if parsed.tzinfo is None:raise ValueError("timezone required")
    except Exception:
        con.close();return {"ok":False,"message":"scheduled_at must be an ISO-8601 timestamp with timezone"}
    con.execute("""UPDATE publishing_queue SET status='scheduled',target=?,platform=?,scheduled_at=?,updated_at=?,last_error=NULL
                   WHERE id=?""",(target,platform,when,ts(),publish_id))
    con.commit();updated=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    event(row["job_id"],f"Publishing scheduled: {platform} · {when}")
    sync_cycle_for_publish(publish_id)
    await broadcast({"type":"publishing","publishId":publish_id,"status":"scheduled"})
    return {"ok":True,"item":_publish_item(updated)}

@app.post("/api/publishing/{publish_id}/publish")
async def publish_scheduled_item(publish_id:str,confirm_uncertain:bool=False):
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone()
    if not row:con.close();raise HTTPException(404,"Publish item not found")
    item=_publish_item(row);meta=item.get("meta") or {}
    if item["status"]=="published":con.close();return {"ok":True,"item":item,"idempotent":True}
    if not item.get("scheduled_at") or item["status"] not in ("scheduled","failed"):
        con.close();return {"ok":False,"message":"Explicit scheduling is required before publishing"}
    if meta.get("outcome_uncertain") and not confirm_uncertain:
        con.close();return {"ok":False,"requiresConfirmation":True,
                            "message":"Previous external publish outcome is uncertain. Confirm before retrying the same idempotency key."}
    try:
        scheduled_dt=datetime.fromisoformat(str(item["scheduled_at"]).replace("Z","+00:00"))
        if scheduled_dt.tzinfo is None:raise ValueError("timezone required")
        if scheduled_dt.astimezone(timezone.utc)>datetime.now(timezone.utc):
            con.close();return {"ok":False,"message":"Publish item is scheduled for a future time"}
    except ValueError:
        con.close();return {"ok":False,"message":"Publish item has an invalid scheduled timestamp"}
    if item.get("media") and not (item.get("media") or {}).get("url"):
        con.close();return {"ok":False,"message":"Approved media URL is missing"}
    con.execute("UPDATE publishing_queue SET status='publishing',attempt_count=attempt_count+1,updated_at=?,last_error=NULL WHERE id=?",
                (ts(),publish_id));con.commit();con.close()
    try:
        result=await asyncio.to_thread(_publish_via_adapter,item)
        if result.get("manual"):
            con=db();con.execute("UPDATE publishing_queue SET status='publishing',updated_at=?,meta_json=? WHERE id=?",
                                 (ts(),json.dumps({**meta,"manual_confirmation_required":True}),publish_id));con.commit();con.close()
            return {"ok":True,"requiresManualConfirmation":True,
                    "message":"Manual publisher path: confirm the real platform post ID/URL after publishing."}
        status="published" if result.get("status")=="published" and result.get("external_post_id") else str(result.get("status") or "publishing")
        published_at=ts() if status=="published" else None
        con=db();con.execute("""UPDATE publishing_queue SET status=?,external_post_id=?,external_url=?,published_at=?,updated_at=?,meta_json=?
                               WHERE id=?""",(status,result.get("external_post_id"),result.get("external_url"),published_at,ts(),
                               json.dumps({**meta,"adapter_result":result.get("raw",{})},ensure_ascii=False),publish_id))
        con.commit();updated=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
        item=_publish_item(updated)
        if status=="published":
            _publish_receipt(item,result.get("external_post_id"),result.get("external_url") or "",published_at,"adapter")
        else:
            event(item["job_id"],f"Publishing result: {status} · {item['platform']}")
            sync_cycle_for_publish(publish_id)
        await broadcast({"type":"publishing","publishId":publish_id,"status":status})
        return {"ok":True,"status":status,"item":item}
    except Exception as exc:
        uncertain=isinstance(exc,(TimeoutError,urlerror.URLError))
        con=db();con.execute("UPDATE publishing_queue SET status='failed',last_error=?,updated_at=?,meta_json=? WHERE id=?",
                             (str(exc)[:900],ts(),json.dumps({**meta,"outcome_uncertain":uncertain}),publish_id))
        con.commit();con.close();event(item["job_id"],f"Publishing failed: {str(exc)[:180]}")
        return {"ok":False,"status":"failed","outcomeUncertain":uncertain,"message":str(exc)}

@app.post("/api/publishing/{publish_id}/confirm")
async def confirm_manual_publish(publish_id:str,payload:PublishConfirmRequest):
    external=(payload.external_post_id or "").strip()
    if not external:raise HTTPException(400,"external_post_id is required")
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone()
    if not row:con.close();raise HTTPException(404,"Publish item not found")
    published_at=payload.published_at or ts()
    con.execute("""UPDATE publishing_queue SET status='published',external_post_id=?,external_url=?,published_at=?,updated_at=?,last_error=NULL
                   WHERE id=?""",(external,(payload.external_url or "").strip(),published_at,ts(),publish_id))
    con.commit();updated=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    _publish_receipt(_publish_item(updated),external,(payload.external_url or "").strip(),published_at,"manual")
    await broadcast({"type":"publishing","publishId":publish_id,"status":"published"})
    return {"ok":True,"status":"published","item":_publish_item(updated)}

@app.post("/api/publishing/run-due")
async def run_due_publishing():
    con=db();rows=con.execute("""SELECT id FROM publishing_queue WHERE status='scheduled' AND scheduled_at<=?
                                 ORDER BY scheduled_at LIMIT 20""",(ts(),)).fetchall();con.close()
    results=[]
    for row in rows:results.append(await publish_scheduled_item(row["id"],False))
    return {"ok":True,"processed":len(results),"results":results}

async def publisher_scheduler_loop():
    while True:
        try:
            await run_due_publishing()
        except Exception as exc:
            print(json.dumps({"event":"PUBLISHER_SCHEDULER_ERROR","error":str(exc)[:500]}),flush=True)
        await asyncio.sleep(FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC)

@app.get("/api/analytics-adapters")
def analytics_adapters():
    return get_analytics_adapter_registry()

@app.get("/api/performance")
def performance_dashboard(limit:int=100):
    return get_performance_dashboard(limit)

@app.get("/api/performance/{publish_id}")
def performance_detail(publish_id:str):
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    if not row:raise HTTPException(404,"Published item not found")
    return _performance_item(_publish_item(row))

@app.post("/api/performance/snapshots")
async def add_performance_snapshot(payload:PerformanceSnapshotCreate):
    try:result=record_performance_snapshot(payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"performance","publishId":payload.publish_id})
    return {"ok":True,**result}

@app.post("/api/performance/{publish_id}/sync")
async def sync_performance_snapshot(publish_id:str):
    if not FACTORY_ANALYTICS_ENDPOINT:raise HTTPException(503,"Analytics webhook adapter is not configured")
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    if not row or row["status"]!="published":raise HTTPException(400,"Published item required")
    query=urlparse.urlencode({"external_post_id":row["external_post_id"] or "","platform":row["platform"]})
    sep="&" if "?" in FACTORY_ANALYTICS_ENDPOINT else "?"
    try:data=await asyncio.to_thread(_external_json,FACTORY_ANALYTICS_ENDPOINT+sep+query,"GET",None,FACTORY_ANALYTICS_TOKEN)
    except Exception as exc:raise HTTPException(503,str(exc))
    source=data.get("metrics") if isinstance(data.get("metrics"),dict) else data
    kwargs={"publish_id":publish_id,"source":FACTORY_ANALYTICS_ADAPTER}
    for key in PERFORMANCE_FIELDS:
        if key in source:kwargs[key]=source[key]
    try:result=record_performance_snapshot(PerformanceSnapshotCreate(**kwargs))
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"performance","publishId":publish_id})
    return {"ok":True,**result}


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
        "selectedJobContentPackage": get_content_package(sid),
        "mediaAdapters": get_media_adapter_registry(),
        "packageBuilding": list(package_building),
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
        "approvalSummary": _approval_summary(),
        "publishingSummary": _publishing_summary(),
        "performanceSummary": _performance_summary(),
        "selfImprovementSummary": get_self_improvement_dashboard()["summary"],
        "autonomousCycleSummary": get_factory_cycles(40)["summary"],
        "discoverySummary": get_discovery_candidates(40)["summary"],
        "discoveryAdapter": get_discovery_candidates(1)["adapter"],
        "revideoSummary": get_revideo_projects(40)["summary"],
        "revideoAdapters": get_revideo_adapter_registry(),
        "mediaFinisher": {"adapter":get_media_finisher_registry(),"summary":get_edit_jobs(80)["summary"],"pilot":get_media_finisher_pilot()},
        "activeWorkflow": _active_workflow_version(),
        "publisherAdapters": get_publisher_adapter_registry(),
        "analyticsAdapters": get_analytics_adapter_registry(),
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
                await run_variant_pipeline(job_id,None)
                await generate_content_package(job_id)
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
    package=get_content_package(job_id).get("package_record")
    if not package or package.get("status")!="ready":
        return {"ok":False,"message":"A fresh Content Package is required before approval"}
    media_review=_media_review_state(job_id)
    if media_review.get("required") and not media_review.get("ready"):
        return {"ok":False,"message":media_review.get("reason") or "Finished media is not ready for approval"}
    approval_decision_id=_record_approval(job_id,"approved","Approved in Approval Studio",
                     meta={"media_artifact_id":((media_review.get("artifact") or {}).get("id")),
                           "media_edit_job_id":(((media_review.get("edit_job") or {}).get("id")))})
    try:item=_ensure_publish_item(job_id,approval_decision_id)
    except ValueError as exc:return {"ok":False,"message":str(exc)}
    con=db();con.execute("UPDATE jobs SET status='approved',stage='qa',progress=75,updated_at=? WHERE id=?",(ts(),job_id));con.commit();con.close()
    event(job_id,"Approval Studio: approved; added to publishing queue; no publish action executed")
    sync_cycle_for_job(job_id)
    await broadcast({"type":"approval","jobId":job_id,"decision":"approved","publishId":item["id"]})
    return {"ok":True,"status":"approved","publish":item,
            "message":"Approved and queued. Publishing still requires a separate schedule/publish action."}

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
    jobs=get_jobs()
    selected_job_id=current_selected(jobs)
    selected_result=(get_job_worker_results(selected_job_id).get(agent_name) if selected_job_id else None)
    return {
        "name":agent_name,
        "spec":AGENT_SPECS.get(agent_name,{}),
        "dependencies":AGENT_DEPENDENCIES.get(agent_name,[]),
        "state":agent_states(jobs).get(agent_name,"idle"),
        "metrics":get_agent_metrics(agent_name),
        "progress":get_agent_progress_snapshot(agent_name),
        "mcp":get_agent_mcp_connections(agent_name),
        "steps":steps,
        "runs":runs,
        "artifacts":artifacts,
        "memory":get_agent_memory(agent_name),
        "selected_job_id":selected_job_id,
        "selected_job_result":selected_result,
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



@app.get("/api/discovery")
def discovery_candidates(limit:int=80,status:Optional[str]=None):
    return get_discovery_candidates(limit,status)

@app.post("/api/discovery/candidates")
async def add_discovery_candidate(payload:DiscoveryCandidateCreate):
    try:result=ingest_discovery_candidate(payload,"manual")
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"discovery","action":"candidate","candidateId":result["candidate"]["id"]})
    return result

@app.post("/api/discovery/collect")
async def collect_discovery(payload:DiscoveryCollectRequest):
    try:result=await asyncio.to_thread(collect_discovery_candidates,payload.topic,payload.limit,payload.content_type,payload.language)
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"discovery","action":"collected","count":result.get("created_count",0)})
    return result

@app.post("/api/discovery/{candidate_id}/revideo")
async def discovery_to_revideo(candidate_id:str,payload:DiscoveryToRevideoRequest):
    try:result=discovery_candidate_to_revideo(candidate_id,payload.language)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"discovery","action":"revideo","candidateId":candidate_id,"projectId":result["project"]["id"]})
    return {"ok":True,**result}


def _media_upload_signature(upload_id):
    return hmac.new(FACTORY_SECRET.encode("utf-8"),f"media-source:{upload_id}".encode("utf-8"),hashlib.sha256).hexdigest()

def _media_upload_meta(upload_id):
    path=MEDIA_UPLOAD_DIR/f"{upload_id}.json"
    if not path.exists():return None
    return _decode_json(path.read_text(encoding="utf-8"),None)

@app.get("/media-source/{upload_id}",name="media_finisher_uploaded_source")
def media_finisher_uploaded_source(upload_id:str,token:str=""):
    expected=_media_upload_signature(upload_id)
    if not token or not hmac.compare_digest(token,expected):raise HTTPException(403,"Invalid media source token")
    meta=_media_upload_meta(upload_id)
    if not meta:raise HTTPException(404,"Media source not found")
    path=MEDIA_UPLOAD_DIR/str(meta.get("stored_name") or "")
    if not path.exists():raise HTTPException(404,"Media source file missing")
    return FileResponse(path,media_type=meta.get("content_type") or "application/octet-stream",
                        filename=meta.get("filename") or path.name,content_disposition_type="inline")

@app.post("/api/jobs/{job_id}/media-finisher/upload")
async def media_finisher_upload(job_id:str,request:Request,file:UploadFile=File(...)):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    filename=Path(file.filename or "upload.mp4").name
    ext=Path(filename).suffix.lower()
    allowed_ext={".mp4",".mov",".m4v",".webm",".mpeg",".mpg"}
    content_type=(file.content_type or "").lower()
    if ext not in allowed_ext or (content_type and not content_type.startswith("video/")):
        raise HTTPException(400,"Upload a supported video file")
    upload_id=str(uuid.uuid4())
    stored_name=upload_id+ext
    dest=MEDIA_UPLOAD_DIR/stored_name
    total=0
    try:
        with dest.open("wb") as fh:
            while True:
                chunk=await file.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>FACTORY_MEDIA_UPLOAD_MAX_BYTES:
                    raise HTTPException(413,f"Video exceeds upload limit of {FACTORY_MEDIA_UPLOAD_MAX_BYTES//(1024*1024)} MB")
                fh.write(chunk)
    except Exception:
        if dest.exists():dest.unlink()
        raise
    finally:
        await file.close()
    if total<1024:
        if dest.exists():dest.unlink()
        raise HTTPException(400,"Uploaded video is empty or too small")
    meta={"upload_id":upload_id,"job_id":job_id,"filename":filename,"stored_name":stored_name,
          "content_type":content_type or "video/mp4","bytes":total,"created_at":ts()}
    (MEDIA_UPLOAD_DIR/f"{upload_id}.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    token=_media_upload_signature(upload_id)
    source_url=str(request.url_for("media_finisher_uploaded_source",upload_id=upload_id))+"?token="+urlparse.quote(token,safe="")
    artifact_id=save_artifact("AI Media Finisher","video","Raw video upload","",job_id=job_id,url=source_url,
                              mime_type=meta["content_type"],meta={"component":"raw_upload","upload_id":upload_id,"bytes":total,"filename":filename})
    event(job_id,f"Media Finisher raw video uploaded: {filename} · {round(total/1024/1024,1)} MB")
    return {"ok":True,"upload_id":upload_id,"url":source_url,"artifact_id":artifact_id,"bytes":total,"filename":filename}

ASR_REPAIR_GENERATION="pyav17-whisper-v2"

def _recent_edit_timestamp(value,minutes=120):
    try:
        stamp=datetime.fromisoformat(str(value or "").replace("Z","+00:00"))
        if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
        return stamp.timestamp()>=time.time()-max(1,int(minutes))*60
    except Exception:
        return False

def _is_media_finisher_pilot_request(raw_request):
    request=_decode_json(raw_request or "{}",{}) if not isinstance(raw_request,dict) else raw_request
    input_url=str(request.get("input_url") or "")
    package=request.get("content_package") or {}
    provenance=package.get("provenance") or {}
    return "/pilot/source.mp4" in input_url or provenance.get("mode")=="v4.5_real_pilot" or package.get("_factoryos_pilot") is True

def _retire_legacy_media_finisher_pilots():
    con=db();rows=con.execute("""SELECT id,request_json FROM edit_jobs
                                WHERE status IN ('queued','submitted','processing')
                                ORDER BY created_at DESC LIMIT 100""").fetchall()
    retired=0;now=ts()
    for row in rows:
        if not _is_media_finisher_pilot_request(row["request_json"]):continue
        con.execute("""UPDATE edit_jobs SET status='failed',error='Legacy pilot recovery retired; user media jobs have priority.',
                       updated_at=?,completed_at=? WHERE id=?""",(now,now,row["id"]))
        retired+=1
    con.commit();con.close()
    if retired:print(json.dumps({"event":"MEDIA_FINISHER_PILOT_RECOVERY_RETIRED","count":retired}),flush=True)

def _recover_active_media_finisher_jobs():
    time.sleep(2)
    con=db();rows=con.execute("""SELECT id,updated_at,request_json,provider_job_id,status FROM edit_jobs WHERE status IN ('queued','submitted','processing')
                                ORDER BY created_at DESC LIMIT 30""").fetchall();con.close()
    rows=[row for row in rows if _recent_edit_timestamp(row["updated_at"],360) and not _is_media_finisher_pilot_request(row["request_json"])]
    checked=0
    for row in rows:
        try:
            if not str(row["provider_job_id"] or "").strip():
                _spawn_media_finisher_submit(row["id"])
            else:
                refresh_edit_job(row["id"])
            checked+=1
        except Exception as exc:
            print(json.dumps({"event":"MEDIA_FINISHER_STATUS_RECOVERY_ERROR","edit_job_id":row["id"],"error":str(exc)[:400]}),flush=True)
    if rows:print(json.dumps({"event":"MEDIA_FINISHER_STATUS_RECOVERY","active":len(rows),"checked":checked}),flush=True)

def _media_finisher_watchdog_loop():
    time.sleep(8)
    while True:
        try:
            _recover_active_media_finisher_jobs()
        except Exception as exc:
            print(json.dumps({"event":"MEDIA_FINISHER_WATCHDOG_ERROR","error":str(exc)[:500]}),flush=True)
        time.sleep(15)

REAL_MEDIA_REPAIR_GENERATION="manual-raw-v45-free-worker-2"

def _recover_recent_real_media_failures():
    con=db();rows=con.execute("""SELECT id,production_job_id,updated_at,error,request_json FROM edit_jobs
                                WHERE status='failed' ORDER BY updated_at DESC LIMIT 40""").fetchall();con.close()
    recovered=0;seen_jobs=set()
    for row in rows:
        if row["production_job_id"] in seen_jobs:continue
        request=_decode_json(row["request_json"] or "{}",{})
        if _is_media_finisher_pilot_request(request):continue
        if request.get("package_mode")!="manual_raw_upload":continue
        if not _recent_edit_timestamp(row["updated_at"],120):continue
        seen_jobs.add(row["production_job_id"])
        if request.get("_real_media_repair_generation")==REAL_MEDIA_REPAIR_GENERATION:continue
        request["_real_media_repair_generation"]=REAL_MEDIA_REPAIR_GENERATION
        response={"status":"queued","stage":"waking_worker","percent":1,"real_media_repair":True,
                  "repair_generation":REAL_MEDIA_REPAIR_GENERATION}
        con=db();con.execute("""UPDATE edit_jobs SET provider_job_id='',status='queued',error='',request_json=?,response_json=?,updated_at=?,completed_at=NULL WHERE id=?""",
                             (json.dumps(request,ensure_ascii=False,default=str),json.dumps(response,ensure_ascii=False),ts(),row["id"]));con.commit();con.close()
        _spawn_media_finisher_submit(row["id"]);recovered+=1
    if recovered:print(json.dumps({"event":"MEDIA_FINISHER_REAL_MEDIA_REPAIR","recovered":recovered,"generation":REAL_MEDIA_REPAIR_GENERATION}),flush=True)

def _recover_recent_failed_asr_jobs():
    con=db();rows=con.execute("""SELECT id,updated_at,error,request_json FROM edit_jobs
                                WHERE status='failed' AND (error LIKE '%transcribe_runner%' OR error LIKE 'Whisper subprocess failed%')
                                ORDER BY updated_at DESC LIMIT 20""").fetchall();con.close()
    recovered=0
    for row in rows:
        if not _recent_edit_timestamp(row["updated_at"],360):continue
        request=_decode_json(row["request_json"] or "{}",{})
        if _is_media_finisher_pilot_request(request):continue
        if request.get("_asr_repair_generation")==ASR_REPAIR_GENERATION:continue
        attempts=int(request.get("_auto_asr_retry_count") or 0)+1
        request["_auto_asr_retry_count"]=attempts
        request["_asr_repair_generation"]=ASR_REPAIR_GENERATION
        response={"status":"queued","stage":"waking_worker","percent":1,"auto_asr_retry":True,
                  "auto_asr_retry_attempt":attempts,"asr_repair_generation":ASR_REPAIR_GENERATION}
        con=db();con.execute("""UPDATE edit_jobs SET provider_job_id='',status='queued',error='',request_json=?,response_json=?,updated_at=?,completed_at=NULL WHERE id=?""",
                             (json.dumps(request,ensure_ascii=False,default=str),json.dumps(response,ensure_ascii=False),ts(),row["id"]));con.commit();con.close()
        _spawn_media_finisher_submit(row["id"]);recovered+=1
    if recovered:print(json.dumps({"event":"MEDIA_FINISHER_ASR_AUTO_RETRY","recovered":recovered,"generation":ASR_REPAIR_GENERATION}),flush=True)

@app.on_event("startup")
def recover_pending_media_finisher_submits():
    _retire_legacy_media_finisher_pilots()
    con=db();rows=con.execute("""SELECT id,updated_at,request_json FROM edit_jobs WHERE status IN ('queued','submitted','processing')
                                AND COALESCE(provider_job_id,'')='' ORDER BY created_at DESC LIMIT 30""").fetchall();con.close()
    rows=[row for row in rows if _recent_edit_timestamp(row["updated_at"],120) and not _is_media_finisher_pilot_request(row["request_json"])]
    for row in rows:_spawn_media_finisher_submit(row["id"])
    _recover_recent_real_media_failures()
    _recover_recent_failed_asr_jobs()
    _recover_ready_durable_media()
    threading.Thread(target=_media_finisher_watchdog_loop,daemon=True,name="finisher-watchdog").start()
    if rows:print(json.dumps({"event":"MEDIA_FINISHER_SUBMIT_RECOVERY","queued":len(rows)}),flush=True)

@app.get("/api/media-finisher/profiles")
def media_finisher_profiles():
    return {"profiles":get_edit_profiles(),"adapter":get_media_finisher_registry()}

@app.get("/api/media-finisher")
def media_finisher_jobs(limit:int=80,job_id:Optional[str]=None):
    return get_edit_jobs(limit,job_id)

@app.get("/api/media-finisher/{edit_job_id}")
def media_finisher_detail(edit_job_id:str):
    item=get_edit_job(edit_job_id)
    if not item:raise HTTPException(404,"Edit job not found")
    return item

@app.post("/api/jobs/{job_id}/media-finisher")
async def media_finisher_start(job_id:str,payload:MediaFinisherStartRequest):
    if FACTORY_MEDIA_FINISHER_ENDPOINT and not payload.confirm_external_cost:
        return {"ok":False,"requiresExternalCostConfirmation":True,
                "message":"Media Finisher may use external compute/provider resources. Confirm before starting."}
    try:result=await asyncio.to_thread(start_media_finisher,job_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"media_finisher","action":"submitted","jobId":job_id,"editJobId":result["edit_job"]["id"],"status":result["edit_job"]["status"]})
    return {"ok":True,**result}

@app.post("/api/media-finisher/{edit_job_id}/refresh")
async def media_finisher_refresh(edit_job_id:str):
    try:item=await asyncio.to_thread(refresh_edit_job,edit_job_id)
    except ValueError as exc:raise HTTPException(404,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"media_finisher","action":"updated","editJobId":edit_job_id,"status":item["status"]})
    return {"ok":True,"edit_job":item}

@app.post("/api/media-finisher/{edit_job_id}/archive")
async def media_finisher_archive(edit_job_id:str):
    item=get_edit_job(edit_job_id)
    if not item:raise HTTPException(404,"Edit job not found")
    if item.get("status")!="ready":raise HTTPException(400,"Media Finisher job must be ready before durable archive")
    queued=_queue_durable_media_archive(edit_job_id)
    updated=get_edit_job(edit_job_id)
    await broadcast({"type":"media_finisher","action":"archive","editJobId":edit_job_id,
                     "durableMediaStatus":((updated.get("response") or {}).get("durable_media_status"))})
    return {"ok":True,"queued":queued,"edit_job":updated}

@app.post("/api/media-finisher/{edit_job_id}/callback")
async def media_finisher_callback(edit_job_id:str,payload:MediaFinisherCallbackRequest,request:Request):
    if FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN:
        supplied=(request.headers.get("authorization") or "").replace("Bearer ","",1).strip()
        if not hmac.compare_digest(supplied,FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN):raise HTTPException(401,"Invalid Media Finisher callback token")
    try:
        output_url=(payload.final_url or payload.output_url or "").strip()
        item=_finalize_edit_job(edit_job_id,payload.status,output_url,payload.provider_job_id,payload.error,payload.raw,payload.report,payload.measured_cost_usd,payload.measured_duration_sec)
    except ValueError as exc:raise HTTPException(404,str(exc))
    await broadcast({"type":"media_finisher","action":"callback","editJobId":edit_job_id,"status":item["status"]})
    return {"ok":True,"edit_job":item}

@app.post("/api/media-finisher/{edit_job_id}/rerun/{stage}")
async def media_finisher_rerun(edit_job_id:str,stage:str,payload:MediaFinisherStartRequest):
    if not payload.confirm_external_cost:
        return {"ok":False,"requiresExternalCostConfirmation":True,"message":"Targeted Media Finisher rerun may incur external compute cost. Confirm first."}
    try:result=await asyncio.to_thread(rerun_media_finisher_stage,edit_job_id,stage)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"media_finisher","action":"rerun","editJobId":result["edit_job"]["id"],"stage":stage})
    return {"ok":True,**result}

@app.get("/api/revideo")
def revideo_projects(limit:int=80):
    return get_revideo_projects(limit)

@app.get("/api/revideo/adapters")
def revideo_adapters():
    return get_revideo_adapter_registry()

@app.post("/api/revideo")
async def create_revideo(payload:RevideoCreateRequest):
    try:project=create_revideo_project(payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"revideo","action":"created","projectId":project["id"]})
    return {"ok":True,"project":project}

@app.get("/api/revideo/{project_id}")
def revideo_project(project_id:str):
    project=get_revideo_project(project_id)
    if not project:raise HTTPException(404,"Revideo project not found")
    return project

@app.get("/api/revideo/{project_id}/quote")
def revideo_quote(project_id:str):
    project=get_revideo_project(project_id)
    if not project:raise HTTPException(404,"Revideo project not found")
    return _revideo_quote(project)

@app.post("/api/revideo/{project_id}/analyze")
async def analyze_revideo(project_id:str,payload:RevideoRunRequest):
    project=get_revideo_project(project_id)
    if not project:raise HTTPException(404,"Revideo project not found")
    if not project.get("transcript") and FACTORY_TRANSCRIPT_ENDPOINT and not payload.confirm_external_cost:
        return {"ok":False,"requiresExternalCostConfirmation":True,
                "message":"Transcript webhook may have external provider cost. Confirm before calling it."}
    quote=_revideo_quote(project)
    if quote.get("paid_calls_possible") and not payload.confirm_cost:
        return {"ok":False,"requiresCostConfirmation":True,"quote":quote,
                "message":"Confirm the bounded LLM analysis/rewrite estimate before running Revideo."}
    try:project=await run_revideo_analysis(project_id,payload.language or project.get("language") or "English")
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"revideo","action":"analyzed","projectId":project_id})
    return {"ok":True,"project":project}

@app.post("/api/revideo/{project_id}/create-job")
async def revideo_create_job(project_id:str):
    try:result=create_revideo_production_job(project_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"revideo","action":"job_created","projectId":project_id,"jobId":result["job"]["id"]})
    return {"ok":True,**result}

@app.post("/api/revideo/{project_id}/render")
async def revideo_render(project_id:str,payload:RevideoRenderRequest):
    if not payload.confirm_external_cost:
        return {"ok":False,"requiresExternalCostConfirmation":True,
                "message":"Video generation may incur external provider cost. Confirm before calling the configured provider."}
    try:result=await asyncio.to_thread(render_revideo_media,project_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    media_job=result["media_job"]
    await broadcast({"type":"revideo","action":"media_job","projectId":project_id,
                     "mediaJobId":media_job["id"],"status":media_job["status"]})
    return {"ok":True,**result}

@app.get("/api/media-jobs")
def media_jobs(limit:int=100,project_id:Optional[str]=None):
    return get_media_jobs(limit,project_id)

@app.get("/api/media-jobs/{media_job_id}")
def media_job_detail(media_job_id:str):
    item=get_media_job(media_job_id)
    if not item:raise HTTPException(404,"Media job not found")
    return item

@app.post("/api/media-jobs/{media_job_id}/refresh")
async def media_job_refresh(media_job_id:str):
    try:item=await asyncio.to_thread(refresh_media_job,media_job_id)
    except ValueError as exc:raise HTTPException(404,str(exc))
    except RuntimeError as exc:raise HTTPException(503,str(exc))
    await broadcast({"type":"media_job","action":"updated","mediaJobId":media_job_id,"status":item["status"]})
    return {"ok":True,"media_job":item}

@app.post("/api/media-jobs/{media_job_id}/callback")
async def media_job_callback(media_job_id:str,payload:MediaJobCallbackRequest,request:Request):
    if FACTORY_VIDEO_CALLBACK_TOKEN:
        supplied=(request.headers.get("authorization") or "").replace("Bearer ","",1).strip()
        if not hmac.compare_digest(supplied,FACTORY_VIDEO_CALLBACK_TOKEN):
            raise HTTPException(401,"Invalid media callback token")
    try:
        media_url=(payload.url or payload.video_url or payload.output_url or "").strip()
        item=_finalize_media_job(media_job_id,payload.status,media_url=media_url,error=payload.error,
                                 response=payload.raw or payload.model_dump(),provider_job_id=payload.provider_job_id)
    except ValueError as exc:raise HTTPException(404,str(exc))
    await broadcast({"type":"media_job","action":"callback","mediaJobId":media_job_id,"status":item["status"]})
    return {"ok":True,"media_job":item}

@app.get("/api/media-adapters")
def media_adapters():
    return get_media_adapter_registry()

@app.get("/api/jobs/{job_id}/content-package")
def job_content_package(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return get_content_package(job_id)

async def _manual_package_build(job_id):
    try:
        await generate_content_package(job_id)
        con=db();con.execute("UPDATE jobs SET stage='visual',status='idle',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("visual")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close()
        event(job_id,"Content Package rebuilt; Visual → Voice → Render → QA require rebuild")
        await broadcast()
    except Exception as exc:
        event(job_id,f"Content Package build failed: {exc}")
        await broadcast({"type":"content_package","jobId":job_id,"status":"failed","error":str(exc)})
    finally:
        package_building.discard(job_id)

@app.post("/api/jobs/{job_id}/content-package/generate")
async def generate_job_content_package(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    if job_id in package_building:return {"ok":True,"message":"Content Package is already building"}
    if job_id in running_jobs:return {"ok":False,"message":"Wait for the current Factory run to finish before rebuilding the package"}
    if not _selected_production_variant(job_id):return {"ok":False,"message":"Select a complete production variant first"}
    if FACTORY_LLM_API_KEY:
        try:_variant_budget_guard(job_id,1800)
        except RuntimeError as exc:return {"ok":False,"message":str(exc)}
    package_building.add(job_id);asyncio.create_task(_manual_package_build(job_id))
    await broadcast({"type":"content_package","jobId":job_id,"status":"building"})
    return {"ok":True,"message":"Content Package build started"}

@app.get("/api/jobs/{job_id}/content-package/export.json")
def export_content_package_json(job_id:str):
    data=get_content_package(job_id);record=data.get("package_record")
    if not record:raise HTTPException(404,"Content Package not found")
    body=json.dumps(record.get("package") or {},ensure_ascii=False,indent=2).encode("utf-8")
    return Response(content=body,media_type="application/json; charset=utf-8",
                    headers={"Content-Disposition":f'attachment; filename="{_export_filename(job_id,".json")}"'})

@app.get("/api/jobs/{job_id}/content-package/export.zip")
def export_content_package_zip(job_id:str):
    data=get_content_package(job_id);record=data.get("package_record")
    if not record:raise HTTPException(404,"Content Package not found")
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for name,content in _package_export_files(record).items():
            zf.writestr(name,content)
    return Response(content=buf.getvalue(),media_type="application/zip",
                    headers={"Content-Disposition":f'attachment; filename="{_export_filename(job_id,".zip")}"'})

@app.get("/api/jobs/{job_id}/variants")
def job_variants(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return get_job_variants(job_id)

async def _manual_variant_build(job_id):
    try:
        await run_variant_pipeline(job_id,None)
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

@app.delete("/api/artifacts/{artifact_id}")
async def delete_video_artifact(artifact_id:str):
    con=db();row=con.execute("SELECT * FROM artifacts WHERE id=?",(artifact_id,)).fetchone()
    if not row:
        con.close();raise HTTPException(404,"Artifact not found")
    item=dict(row)
    meta=_decode_json(item.get("meta_json") or "{}",{})
    if item.get("kind")!="video" or meta.get("component")!="raw_upload":
        con.close();raise HTTPException(400,"Only unprocessed raw video uploads can be removed here")
    refs=con.execute("SELECT id,status FROM edit_jobs WHERE input_artifact_id=? LIMIT 5",(artifact_id,)).fetchall()
    if refs:
        con.close();raise HTTPException(409,"This video is already referenced by Media Finisher history and is kept for provenance")
    con.execute("DELETE FROM run_inputs WHERE artifact_id=?",(artifact_id,))
    con.execute("DELETE FROM artifacts WHERE id=?",(artifact_id,))
    con.commit();con.close()
    upload_id=str(meta.get("upload_id") or "")
    if upload_id:
        upload_meta=_media_upload_meta(upload_id) or {}
        stored=MEDIA_UPLOAD_DIR/str(upload_meta.get("stored_name") or "")
        sidecar=MEDIA_UPLOAD_DIR/f"{upload_id}.json"
        try:
            if stored.exists() and stored.is_file():stored.unlink()
            if sidecar.exists():sidecar.unlink()
        except Exception:
            pass
    event(item.get("job_id"),f"Raw Media Finisher upload removed: {meta.get('filename') or artifact_id[:8]}")
    await broadcast({"type":"artifact","action":"deleted","artifactId":artifact_id,"jobId":item.get("job_id")})
    return {"ok":True,"artifact_id":artifact_id}

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
    try:experiment=create_experiment_from_proposal(proposal_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    event(None,f"Supervisor improvement approved for controlled experiment: {experiment['title']}")
    await broadcast({"type":"self_improvement","action":"experiment_created","experimentId":experiment["id"]})
    return {"ok":True,"experiment":experiment,"message":"Proposal moved into a controlled experiment; production is unchanged until measured owner-approved rollout."}

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

@app.post("/api/improvements")
async def create_improvement(payload:ImprovementProposalCreate):
    try:proposal=create_improvement_proposal(payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    event(None,f"Workflow improvement proposed: {proposal['title']}")
    await broadcast({"type":"self_improvement","action":"proposal_created","proposalId":proposal["id"]})
    return {"ok":True,"proposal":proposal}

@app.get("/api/self-improvement")
def self_improvement_dashboard():
    return get_self_improvement_dashboard()

@app.get("/api/workflow/active")
def active_workflow():
    return {"active":_active_workflow_version(),"allowed_models":sorted(FACTORY_ALLOWED_LLM_MODELS)}

@app.get("/api/experiments")
def experiments():
    return {"experiments":get_experiments(100),"active_workflow":_active_workflow_version()}

@app.post("/api/improvements/{proposal_id}/experiment")
async def create_improvement_experiment(proposal_id:str,payload:ExperimentCreateRequest):
    try:experiment=create_experiment_from_proposal(proposal_id,payload)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"self_improvement","action":"experiment_created","experimentId":experiment["id"]})
    return {"ok":True,"experiment":experiment}

@app.post("/api/experiments/{experiment_id}/assign")
async def assign_experiment(experiment_id:str,payload:ExperimentJobAssignment):
    try:assignment=assign_job_to_experiment(experiment_id,payload.job_id,payload.arm)
    except ValueError as exc:raise HTTPException(400,str(exc))
    event(payload.job_id,f"Experiment {experiment_id}: assigned to {payload.arm}")
    await broadcast({"type":"self_improvement","action":"assigned","experimentId":experiment_id,"jobId":payload.job_id,"arm":payload.arm})
    return {"ok":True,"assignment":assignment}

@app.post("/api/experiments/{experiment_id}/evaluate")
async def evaluate_experiment_api(experiment_id:str):
    try:evaluation=evaluate_experiment(experiment_id)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"self_improvement","action":"evaluated","experimentId":experiment_id})
    return {"ok":True,"evaluation":evaluation,"experiment":_get_experiment(experiment_id)}

@app.post("/api/experiments/{experiment_id}/rollout")
async def rollout_experiment_api(experiment_id:str,payload:ExperimentDecisionRequest):
    try:result=rollout_experiment(experiment_id,payload.confirm,payload.reason)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"self_improvement","action":"rollout","experimentId":experiment_id})
    return result

@app.post("/api/experiments/{experiment_id}/rollback")
async def rollback_experiment_api(experiment_id:str,payload:ExperimentDecisionRequest):
    try:result=rollback_experiment(experiment_id,payload.confirm,payload.reason)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"self_improvement","action":"rollback","experimentId":experiment_id})
    return result

@app.post("/api/experiments/{experiment_id}/reject")
async def reject_experiment_api(experiment_id:str,payload:ExperimentDecisionRequest):
    try:experiment=reject_experiment(experiment_id,payload.reason)
    except ValueError as exc:raise HTTPException(400,str(exc))
    await broadcast({"type":"self_improvement","action":"rejected","experimentId":experiment_id})
    return {"ok":True,"experiment":experiment}

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
