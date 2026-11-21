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
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Optional
from urllib import request as urlrequest, error as urlerror, parse as urlparse

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Request, Form, UploadFile, File
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from relay_agent_messages import agent_identity, install_agent_message_routes
from relay import RelayStore, install_relay_routes, relay_handle_telegram_update, relay_github_snapshot, relay_auto_intake_issues, relay_github_owner_issues, _telegram_attachment
from voice_transcribe import VoiceTranscriber
from telegram_group import GroupBridge, GROUP_TYPES as TELEGRAM_GROUP_TYPES
from relay_execution import RelayQueue
from lane_board import build_lane_board
from operator_lanes import build_operator_lanes
from team_tasks import TeamTasksCache, queue_readiness, build_team_tasks, compact_github, github_fetcher, read_github, valid_snapshot
from supervisor_routing import AUTO_POLICY as ROUTING_AUTO_POLICY,PRIVILEGES as ROUTING_PRIVILEGES,operator_availability,route_tasks
from worker_observability import build_worker_overview, sanitize_supervisor, sanitize_telemetry
from relay_pairing import create_pairing, valid_pairing, pairing_status
from relay_acceptance import latest_telegram_acceptance
from telegram_web_compare import StaleComparison, TelegramViewLog, compare as telegram_web_compare, confirmation_for, owner_status as telegram_compare_status
from owner_desk import RUNBOOKS as OWNER_RUNBOOKS, QuestionStore, TELEGRAM_TASK, install_owner_desk_routes, roadmap_states
from mvp_factory import MvpRegistry, install_mvp_factory_routes
from mybrief import FeedbackStore as MyBriefFeedback, install_mybrief_routes, load_catalog as mybrief_catalog
from faceless_crm import FacelessCrm, install_faceless_crm_routes, register_crm_mvp_project_once
from open_questions import install_open_questions_routes
from browser_tasks import BrowserTaskStore, install_browser_task_routes
import web_surfer
import agent_workspace
from mvp_pipeline import ArtifactStore as MvpArtifacts, Pipeline as MvpPipeline
from mvp_cycle import AGENTS as MVP_AGENTS, AGENT_IDS as MVP_AGENT_IDS, AgentChat, agent_prompt as mvp_agent_prompt, cycle_view as mvp_cycle_view
from gemini_proxy import GEMINI_KEY_CHECK, install_gemini_verify_route, install_gemini_worker_routes
from mycast import (DeliveryLog, check_mp3, check_pcm as mycast_check_pcm, gemini_tts_pcm, install_mycast_routes, install_mycast_voice_routes, pcm_to_mp3,
                    telegram_send_audio)
from mycast_demo import DemoService, install_mycast_demo_routes, _client_id as _mycast_client_id
from mycast_subtopics import SubtopicService
from mycast_listener_delivery import ListenerDelivery, install_listener_delivery_routes
from mycast_accounts import ListenerStore, install_mycast_account_routes, AccountError as MyCastAccountError
from mycast_accounts import COOKIE as MYCAST_COOKIE, unsign as mycast_unsign
from mycast_calendar import ListenerCalendar, install_calendar_routes
from mycast_voices import VoiceSamples, gemini_single_voice_pcm, install_mycast_voice_audition_routes
from mycast import GeminiTTSError as MycastGeminiTTSError
from mycast_demo_audio import DemoAudioStore, install_mycast_demo_audio_routes
import login_recovery
import evidence as _evidence
from gemini_proxy import _call as _gemini_raw_call, resolve_flash_model
from peer_review import ReviewBudget, build_prompt, gemini_review, needs_review, notice_text as review_notice_text
from morning_brief import MorningBrief, compose_brief, plan_ids as brief_plan_ids, github_brief_snapshot
from voice_settings import (VoiceHistory, VoiceSettingsStore, install_brief_route, install_voice_history_routes,
                            install_voice_settings_routes)
from connection_capabilities import ai_provider_catalog, worker_projection, video_projection
from oauth_framework import OAuthError, OAuthFlow, UnavailableTokenVault
import youtube_publisher
import linkedin_publisher
import social_autopilot
import olx_publisher
import workspace_tenancy as tenancy
from battle_runs import BattleError, BattleStore
from telegram_battles import BattleTelegram
import durable_engine
import durable_media_finisher as durable_finisher

BASE = Path(__file__).resolve().parent
APP_VERSION = "v5.15.0"  # the only version; README changelog + sidebar must match (test_versioning.py)
BUILD_SHA = os.environ.get("RENDER_GIT_COMMIT", "local")
GITHUB_REPO = os.environ.get("FACTORY_GITHUB_REPO", "Pavlovskyi-Andrii/blackboxlab-factoryos")
GITHUB_TOKEN = os.environ.get("FACTORY_GITHUB_TOKEN", "").strip()
# Evidence Protocol: a separate read-only token, so verification never needs (or enables) the Builder's write token.
GITHUB_READ_TOKEN = os.environ.get("FACTORY_GITHUB_READ_TOKEN", "").strip()
def _github_read_token():
    """Every server-side GitHub *read* (intake, team board, /github, PR reconcile) prefers the read-only token;
    the Builder's write paths keep FACTORY_GITHUB_TOKEN. Evaluated at call time."""
    return GITHUB_READ_TOKEN or GITHUB_TOKEN
if GITHUB_READ_TOKEN:
    # Evidence Tier 2.1: only Render's own GitHub read counts as "checked" once the read-only token exists.
    import evidence as _evidence
    _evidence.set_trusted_sources({"github:render","delivery_log","telegram_api","gemini:review"})
# T-599-E / #369: poll no more often than every 120 seconds; this is not a worker-start SLA.
FACTORY_GITHUB_ISSUE_INTAKE_ENABLED = os.environ.get("FACTORY_GITHUB_ISSUE_INTAKE", "1").strip().lower() not in ("0","false","no","off")
FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC = max(120, int(os.environ.get("FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC", "120") or 120))
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


@app.on_event("startup")
def _durable_engine_startup():
    """T-611: keep this the first startup hook. Launching DBOS resumes interrupted workflows from their last finished step
    before any later hook (such as the Media Finisher recovery) inspects or restarts work."""
    durable_engine.launch(DATA_DIR)


@app.on_event("shutdown")
def _durable_engine_shutdown():
    durable_engine.shutdown()


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    """Browsers ask for /favicon.ico before reading the page; serve the Blackbox Lab cube."""
    return FileResponse(BASE / "static" / "favicon-32.png", media_type="image/png", headers={"Cache-Control": "public, max-age=86400"})


@app.get("/mycast", include_in_schema=False)
def mycast_short_link():
    """Short public address for shared MyCast podcasts. The browser keeps the #p=… part across the redirect."""
    return RedirectResponse("/static/mycast-configurator/index.html", status_code=307)

FACTORY_USER = os.environ.get("FACTORY_USER", "blackboxlab")
FACTORY_PASSWORD = os.environ.get("FACTORY_PASSWORD", "")
FACTORY_SECRET = os.environ.get("FACTORY_SECRET", secrets.token_hex(32))
FACTORY_TELEGRAM_BOT_TOKEN = os.environ.get("FACTORY_TELEGRAM_BOT_TOKEN", "").strip()
FACTORY_TELEGRAM_PAIR_TTL_SECONDS = max(120, min(1800, int(os.environ.get("FACTORY_TELEGRAM_PAIR_TTL_SECONDS", "600"))))
TELEGRAM_OWNER_FILE = DATA_DIR / "telegram_owner.json"
RELAY_STORE = RelayStore(DATA_DIR / "relay.json")
RELAY_QUEUE = RelayQueue(RELAY_STORE)
RELAY_WORKER_PAIR_FILE = DATA_DIR / "relay_worker_pair.json"
_telegram_state_lock = threading.Lock()
FACTORY_LOCAL_BOOSTER_TOKEN = (os.environ.get("FACTORY_LOCAL_BOOSTER_TOKEN","").strip()
    or hmac.new(FACTORY_SECRET.encode("utf-8"),b"factoryos-local-render-booster-v1",hashlib.sha256).hexdigest())
FACTORY_CLAUDE_WORKER_TOKEN = (os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN","").strip()
    or hmac.new(FACTORY_SECRET.encode("utf-8"),b"factoryos-claude-code-worker-v1",hashlib.sha256).hexdigest())
# Independent credential for the existing EC2 worker; leaves older phone/owner tokens valid.
FACTORY_CLAUDE_WORKER_TOKEN_EC2 = os.environ.get("FACTORY_CLAUDE_WORKER_TOKEN_EC2", "").strip()
FACTORY_OPERATOR_WORKER_TOKEN = (os.environ.get("FACTORY_OPERATOR_WORKER_TOKEN","").strip()
    or hmac.new(FACTORY_SECRET.encode("utf-8"),b"factoryos-operator-worker-v1",hashlib.sha256).hexdigest())
FACTORY_OPERATOR_WORKER_TTL_SECONDS = max(15,min(300,int(os.environ.get("FACTORY_OPERATOR_WORKER_TTL_SECONDS","45"))))
# T-607: the Gemini worker's own credential (owner-set, >= 32 chars, no derived default). It opens only the Gemini lane:
# ROADMAP claims with lane=gemini, events on Gemini-owned tickets and the gemini operator heartbeat. Nothing else.
FACTORY_GEMINI_WORKER_TOKEN = os.environ.get("FACTORY_GEMINI_WORKER_TOKEN", "").strip()
GEMINI_WORKER_PATHS = ("/api/relay/worker/roadmap-claim", "/api/relay/worker/event", "/api/operator-worker/heartbeat")
operator_worker_runtime={"claude":{"last_seen":0.0},"gemini":{"last_seen":0.0}}
_operator_worker_lock=threading.Lock()
FACTORY_CLAUDE_WORKER_TTL_SECONDS = max(15,min(300,int(os.environ.get("FACTORY_CLAUDE_WORKER_TTL_SECONDS","45"))))
claude_worker_runtime={"last_seen":0.0,"node":{},"active_task_id":"","last_error":"","telemetry":{}}
CLAUDE_WORKER_RESULTS_FILE = DATA_DIR / "claude_worker_results.json"
# T-536-B: last sanitized heartbeat survives restarts; the TTL still decides online/stale.
CLAUDE_WORKER_HEARTBEAT_FILE = DATA_DIR / "claude_worker_heartbeat.json"
_claude_worker_results_lock=threading.Lock()
FACTORY_GOOGLE_CLIENT_ID = os.environ.get("FACTORY_GOOGLE_CLIENT_ID","").strip()
FACTORY_GOOGLE_CLIENT_SECRET = os.environ.get("FACTORY_GOOGLE_CLIENT_SECRET","").strip()   # MyCast calendar OAuth only
FACTORY_MYCAST_CALENDAR_REDIRECT = os.environ.get("FACTORY_MYCAST_CALENDAR_REDIRECT",
                                                  "https://mycast.pro/api/mycast/calendar/callback").strip()
FACTORY_GOOGLE_OWNER_EMAILS = {x.strip().lower() for x in os.environ.get("FACTORY_GOOGLE_OWNER_EMAILS","").split(",") if x.strip()}
FACTORY_GOOGLE_VIEWER_EMAILS = {x.strip().lower() for x in os.environ.get("FACTORY_GOOGLE_VIEWER_EMAILS","").split(",") if x.strip()}
FACTORY_GOOGLE_ALLOWED_EMAILS = ({x.strip().lower() for x in os.environ.get("FACTORY_GOOGLE_ALLOWED_EMAILS","").split(",") if x.strip()} | FACTORY_GOOGLE_OWNER_EMAILS | FACTORY_GOOGLE_VIEWER_EMAILS)
FACTORY_GOOGLE_ALLOWED_DOMAINS = {x.strip().lower().lstrip("@") for x in os.environ.get("FACTORY_GOOGLE_ALLOWED_DOMAINS","").split(",") if x.strip()}
FACTORY_VIEWER_INVITE_TOKEN = os.environ.get("FACTORY_VIEWER_INVITE_TOKEN","").strip()
# T-553: customer users, "email=workspace,..."; they sign in with Google and only see their workspace.
FACTORY_WORKSPACE_MEMBERS = tenancy.parse_members(os.environ.get("FACTORY_WORKSPACE_MEMBERS",""))
FACTORY_LOCAL_BOOSTER_TTL_SECONDS = max(15,min(300,int(os.environ.get("FACTORY_LOCAL_BOOSTER_TTL_SECONDS","45"))))
local_booster_runtime={"last_seen":0.0,"node":{},"active_job_id":"","last_error":""}
_local_booster_claim_lock=threading.Lock()
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
FACTORY_METRICOOL_TOKEN = os.environ.get("FACTORY_METRICOOL_TOKEN", "").strip()
FACTORY_METRICOOL_USER_ID = os.environ.get("FACTORY_METRICOOL_USER_ID", "").strip()
FACTORY_METRICOOL_BLOG_ID = os.environ.get("FACTORY_METRICOOL_BLOG_ID", "").strip()
FACTORY_METRICOOL_TIMEZONE = os.environ.get("FACTORY_METRICOOL_TIMEZONE", "Europe/Kyiv").strip() or "Europe/Kyiv"
FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS = os.environ.get("FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS", "").strip().lower()
FACTORY_METRICOOL_BASE_URL = os.environ.get("FACTORY_METRICOOL_BASE_URL", "https://app.metricool.com").strip().rstrip("/")
FACTORY_METRICOOL_RECONCILE_ENABLED = os.environ.get("FACTORY_METRICOOL_RECONCILE_ENABLED", "1").strip().lower() in ("1","true","yes","on")
FACTORY_METRICOOL_RECONCILE_LIMIT = max(1,min(100,int(os.environ.get("FACTORY_METRICOOL_RECONCILE_LIMIT","30"))))
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
# Native Google Gemini video provider. Keep the API key in the runtime secret store only.
FACTORY_GEMINI_API_KEY = os.environ.get("FACTORY_GEMINI_API_KEY", "").strip()
FACTORY_GEMINI_VIDEO_MODEL = os.environ.get("FACTORY_GEMINI_VIDEO_MODEL", "gemini-omni-1.1-flash").strip() or "gemini-omni-1.1-flash"
FACTORY_GEMINI_VIDEO_ASPECT_RATIO = os.environ.get("FACTORY_GEMINI_VIDEO_ASPECT_RATIO", "9:16").strip() or "9:16"
FACTORY_GEMINI_VIDEO_RESOLUTION = os.environ.get("FACTORY_GEMINI_VIDEO_RESOLUTION", "720p").strip() or "720p"
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

def _role_session_token(role: str, email: str) -> str:
    role=(role or "viewer").strip().lower()
    email=(email or "").strip().lower()
    payload=f"v2|{role}|{email}"
    sig=hmac.new(FACTORY_SECRET.encode("utf-8"),payload.encode("utf-8"),hashlib.sha256).hexdigest()
    return payload+"|"+sig

def _member_session_token(email: str, workspace: str) -> str:
    payload=f"v3|member|{(email or '').strip().lower()}|{tenancy.normalize_workspace(workspace)}"
    sig=hmac.new(FACTORY_SECRET.encode("utf-8"),payload.encode("utf-8"),hashlib.sha256).hexdigest()
    return payload+"|"+sig

def _identity_from_session_token(token: str):
    token=(token or "").strip()
    if not token:
        return None
    if hmac.compare_digest(token,session_token(FACTORY_USER)):
        return {"role":"owner","email":"","provider":"password"}
    parts=token.split("|")
    if len(parts)==5 and parts[0]=="v3" and parts[1]=="member":
        expected=hmac.new(FACTORY_SECRET.encode("utf-8"),"|".join(parts[:4]).encode("utf-8"),hashlib.sha256).hexdigest()
        # A removed or re-assigned member loses the old workspace immediately, even with a valid cookie.
        if not hmac.compare_digest(parts[4],expected) or FACTORY_WORKSPACE_MEMBERS.get(parts[2])!=parts[3]:
            return None
        return {"role":"member","email":parts[2],"provider":"google","workspace":parts[3]}
    if len(parts)!=4 or parts[0]!="v2" or parts[1] not in ("owner","viewer"):
        return None
    payload="|".join(parts[:3])
    expected=hmac.new(FACTORY_SECRET.encode("utf-8"),payload.encode("utf-8"),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(parts[3],expected):
        return None
    return {"role":parts[1],"email":parts[2],"provider":"guest" if parts[2]=="guest" else "google"}

def request_identity(request: Request):
    if not FACTORY_PASSWORD:
        return {"role":"owner","email":"","provider":"open"}
    return _identity_from_session_token(request.cookies.get(COOKIE_NAME,""))

def request_is_authed(request: Request) -> bool:
    return bool(request_identity(request))

def _google_login_enabled() -> bool:
    return bool(FACTORY_GOOGLE_CLIENT_ID and (FACTORY_GOOGLE_ALLOWED_EMAILS or FACTORY_GOOGLE_ALLOWED_DOMAINS or FACTORY_WORKSPACE_MEMBERS))

def _google_identity_role(email: str):
    email=(email or "").strip().lower()
    if not email:
        return None
    if email in FACTORY_GOOGLE_OWNER_EMAILS:
        return "owner"
    if email in FACTORY_WORKSPACE_MEMBERS:
        return "member"
    if email in FACTORY_GOOGLE_VIEWER_EMAILS:
        return "viewer"
    if email in FACTORY_GOOGLE_ALLOWED_EMAILS:
        return "viewer"
    domain=email.rsplit("@",1)[-1] if "@" in email else ""
    return "viewer" if domain and domain in FACTORY_GOOGLE_ALLOWED_DOMAINS else None

def _google_identity_allowed(email: str) -> bool:
    return bool(_google_identity_role(email))

def _auth_cookie_response(target: str, role: str="owner", email: str="") -> RedirectResponse:
    response=RedirectResponse(target,status_code=303)
    token=(_member_session_token(email,FACTORY_WORKSPACE_MEMBERS[email.strip().lower()]) if role=="member"
           else _role_session_token(role,email))
    response.set_cookie(
        COOKIE_NAME,token,httponly=True,
        secure=bool(os.environ.get("RENDER")),samesite="lax",max_age=60*60*24*30,
    )
    return response

def _local_booster_authorized(request: Request) -> bool:
    auth=(request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):return False
    supplied=auth.split(" ",1)[1].strip()
    return bool(supplied and hmac.compare_digest(supplied,FACTORY_LOCAL_BOOSTER_TOKEN))

def _local_booster_online():
    return (time.time()-float(local_booster_runtime.get("last_seen") or 0)) <= FACTORY_LOCAL_BOOSTER_TTL_SECONDS

def _claude_worker_authorized(request: Request) -> bool:
    auth=(request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):return False
    supplied=auth.split(" ",1)[1].strip()
    return bool(supplied and (hmac.compare_digest(supplied,FACTORY_CLAUDE_WORKER_TOKEN)
                 or bool(FACTORY_CLAUDE_WORKER_TOKEN_EC2 and hmac.compare_digest(supplied,FACTORY_CLAUDE_WORKER_TOKEN_EC2))
                 or valid_pairing(RELAY_WORKER_PAIR_FILE, supplied)))

FACTORY_BROWSER_AGENT_TOKEN = os.environ.get("FACTORY_BROWSER_AGENT_TOKEN", "").strip()


def _browser_agent_authorized(request: Request) -> bool:
    """Owner 2026-11-13: a token that opens only the browser agent's read-task queue for Claude (min 32 chars,
    never equal to the worker tokens)."""
    token = FACTORY_BROWSER_AGENT_TOKEN
    if len(token) < 32 or token in (FACTORY_CLAUDE_WORKER_TOKEN, FACTORY_CLAUDE_WORKER_TOKEN_EC2):
        return False
    auth = (request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return False
    return hmac.compare_digest(auth.split(" ", 1)[1].strip(), token)


def _operator_worker_authorized(request: Request) -> bool:
    auth=(request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):return False
    supplied=auth.split(" ",1)[1].strip()
    return bool(supplied and hmac.compare_digest(supplied,FACTORY_OPERATOR_WORKER_TOKEN))

def _gemini_worker_authorized(request: Request) -> bool:
    auth=(request.headers.get("authorization") or "").strip()
    if len(FACTORY_GEMINI_WORKER_TOKEN)<32 or not auth.lower().startswith("bearer "):return False
    supplied=auth.split(" ",1)[1].strip()
    return bool(supplied and hmac.compare_digest(supplied,FACTORY_GEMINI_WORKER_TOKEN))

def _worker_lane(request: Request) -> str:
    """'claude' for the Claude worker credentials, 'gemini' for the Gemini worker token, '' otherwise."""
    if _claude_worker_authorized(request):return "claude"
    return "gemini" if _gemini_worker_authorized(request) else ""

def _operator_runtime_online(item: dict) -> bool:
    return (time.time()-float((item or {}).get("last_seen") or 0)) <= FACTORY_OPERATOR_WORKER_TTL_SECONDS

def get_operator_lanes():
    """Live, secret-free operator telemetry for UI/Telegram. Absence stays offline/unknown."""
    lanes={}
    role_board=get_role_operator_board() if "ROLE_CATALOG" in globals() else {"roles":[]}
    assigned_by_operator={}
    for role in role_board.get("roles") or []:
        op=str(role.get("assigned_operator") or "")
        if op and op!="auto":assigned_by_operator.setdefault(op,[]).append(role.get("id"))
    for op in ("claude","gemini"):
        item=dict(operator_worker_runtime.get(op) or {})
        online=_operator_runtime_online(item)
        tickets=[x for x in (item.get("tickets") or []) if isinstance(x,dict)][:20]
        task_id=str(item.get("task_id") or "")
        if task_id and not any(str(x.get("id") or x.get("task_id") or "")==task_id for x in tickets):
            task=next((x for x in _parse_roadmap_tasks() if x["id"]==task_id),None)
            tickets.insert(0,{"id":task_id,"title":(task or {}).get("title",""),"state":item.get("status") or "running"})
        lanes[op]={
            "operator_id":op,"online":online,
            "state":str(item.get("status") or ("online" if online else "offline")) if online else ("stale" if item.get("last_seen") else "offline"),
            "last_seen":item.get("last_seen") or 0,
            "heartbeat_age_seconds":round(max(0.0,time.time()-float(item.get("last_seen") or 0)),1) if item.get("last_seen") else None,
            "node_id":str(item.get("node_id") or ""),"runtime":str(item.get("runtime") or ""),
            "version":str(item.get("version") or ""),"auth_mode":str(item.get("auth_mode") or ""),
            "branch":str(item.get("branch") or ""),"repo":str(item.get("repo") or ""),
            "active_task_id":task_id if online and str(item.get("status") or "").lower() in ("running", "working", "in_progress", "claimed", "checkpoint") else "",
            "last_task_id":task_id if online else "",
            "task_state":str(item.get("status") or ""),
            "stage":str(item.get("stage") or ""),"queue_depth":max(0,int(item.get("queue_depth") or 0)),
            "tickets":tickets,"last_result":str(item.get("last_result") or "")[:500],
            "last_error":str(item.get("last_error") or "")[:500],
            "assigned_roles":assigned_by_operator.get(op,[]),
        }
    # Preserve the richer legacy Claude heartbeat as a factual fallback until all runners use the generic reporter.
    legacy=get_claude_code_status()
    if not lanes["claude"]["online"] and legacy.get("online"):
        lanes["claude"].update({
            "online":True,"state":"online","last_seen":legacy.get("last_seen") or 0,
            "active_task_id":(legacy.get("active_task_id") or "") if legacy.get("task_state") in ("running", "working", "in_progress", "claimed", "checkpoint") else "",
            "last_task_id":legacy.get("active_task_id") or "",
            "task_state":legacy.get("task_state") or "",
            "last_error":legacy.get("last_error") or "",
            "runtime":"claude-code","auth_mode":legacy.get("auth_mode") or "",
            "node_id":str((legacy.get("node") or {}).get("node_id") or ""),
            "branch":str((legacy.get("node") or {}).get("branch") or ""),
        })
    return lanes

def _claude_worker_online():
    return (time.time()-float(claude_worker_runtime.get("last_seen") or 0)) <= FACTORY_CLAUDE_WORKER_TTL_SECONDS

def get_claude_code_status():
    node=dict(claude_worker_runtime.get("node") or {})
    return {
        "online":_claude_worker_online(),
        "ttl_seconds":FACTORY_CLAUDE_WORKER_TTL_SECONDS,
        "last_seen":claude_worker_runtime.get("last_seen") or 0,
        "node":node,
        "active_task_id":claude_worker_runtime.get("active_task_id") or "",
        "task_state":str(node.get("status") or ""),
        "last_error":claude_worker_runtime.get("last_error") or "",
        "auth_mode":str(node.get("auth_mode") or ""),
        "subscription":str(node.get("subscription") or ""),
        "api_key_required":False,
        "recommended_auth":"Claude account with subscription",
        "recent_results":_load_claude_worker_results()[-5:],
        "telemetry":_live_claude_worker_telemetry(),
    }

def _live_claude_worker_telemetry(now=None):
    """Persisted telemetry with elapsed time advanced to now while a task is running; {} when never reported."""
    telemetry=dict(claude_worker_runtime.get("telemetry") or {})
    started=telemetry.get("task_started_at")
    if telemetry.get("stage")=="running" and isinstance(started,(int,float)) and started>0:
        telemetry["elapsed_seconds"]=round(max(0.0,(now or time.time())-float(started)),1)
    return telemetry

def _persist_claude_worker_heartbeat():
    keep={k:claude_worker_runtime.get(k) for k in ("last_seen","node","active_task_id","last_error","telemetry")}
    try:
        CLAUDE_WORKER_HEARTBEAT_FILE.parent.mkdir(parents=True,exist_ok=True)
        tmp=CLAUDE_WORKER_HEARTBEAT_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(keep,ensure_ascii=False)+"\n",encoding="utf-8")
        os.replace(tmp,CLAUDE_WORKER_HEARTBEAT_FILE)
    except OSError as exc:
        print(json.dumps({"event":"CLAUDE_WORKER_HEARTBEAT_PERSIST_FAILED","error":type(exc).__name__}),flush=True)

def _restore_claude_worker_heartbeat():
    if not CLAUDE_WORKER_HEARTBEAT_FILE.exists():return
    value=_decode_json(CLAUDE_WORKER_HEARTBEAT_FILE.read_text(encoding="utf-8"),{})
    if not isinstance(value,dict):return
    node=value.get("node") if isinstance(value.get("node"),dict) else {}
    node["supervisor"]=sanitize_supervisor(node.get("supervisor"))
    claude_worker_runtime.update({
        "last_seen":float(value.get("last_seen") or 0) if isinstance(value.get("last_seen"),(int,float)) else 0.0,
        "node":node,"active_task_id":str(value.get("active_task_id") or ""),
        "last_error":str(value.get("last_error") or "")[:500],
        "telemetry":sanitize_telemetry(value.get("telemetry")),
    })

def _load_claude_worker_results():
    if not CLAUDE_WORKER_RESULTS_FILE.exists():return []
    value=_decode_json(CLAUDE_WORKER_RESULTS_FILE.read_text(encoding="utf-8"),[])
    return value if isinstance(value,list) else []

def ingest_claude_worker_result(payload: "ClaudeWorkerTaskResult"):
    """Validate a delegated Builder result; never trusts a self-reported done without evidence."""
    data=payload.model_dump()
    task_id=data["task_id"].strip()
    if not re.match(r"^T-[A-Za-z0-9-]+$",task_id):raise HTTPException(422,"Invalid task id")
    if data["pinned_task_id"].strip()!=task_id:raise HTTPException(409,"Result task does not match the pinned delegation task")
    if not data["branch"].strip() or data["branch"].strip() in {"main","master"}:
        raise HTTPException(409,"Delegated work must run on a dedicated non-main branch")
    task=next((x for x in _parse_roadmap_tasks() if x["id"]==task_id),None)
    if not task:raise HTTPException(404,"Unknown roadmap task")
    if task["human"]:raise HTTPException(409,"HUMAN roadmap tasks cannot be delegated")
    result=data["result"].strip().lower()
    if result not in {"done","blocked","failed"}:raise HTTPException(422,"Unsupported result state")
    violations=[str(x)[:300] for x in data["violations"]][:20]
    if data["pushed"]:violations.append("delegated agent pushed during execution")
    if not data["deploy_credentials_scrubbed"]:violations.append("deploy credentials were not scrubbed")
    if result=="done" and (data["commit_count"]!=1 or not re.match(r"^[0-9a-f]{7,40}$",data["commit"] or "")):
        violations.append("done result lacks exactly one captured commit")
    if violations:result="failed"
    received_at=time.time()
    record={**data,"task_id":task_id,"result":result,"violations":violations,"received_at":received_at,
            "started_at":_timeline_ts(data["started_at"],received_at),
            "summary":data["summary"][:500],"need":data["need"][:500],"checks":[str(x)[:300] for x in data["checks"]][:20],
            "files":[str(x)[:300] for x in data["files"]][:100]}
    CLAUDE_WORKER_RESULTS_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=CLAUDE_WORKER_RESULTS_FILE.with_suffix(".tmp")
    with _claude_worker_results_lock:
        results=(_load_claude_worker_results()+[record])[-50:]
        tmp.write_text(json.dumps(results,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,CLAUDE_WORKER_RESULTS_FILE)
    claude_worker_runtime["last_error"]="; ".join(violations) if violations else ("" if result!="failed" else record["summary"])
    return record

def _telegram_webhook_secret() -> str:
    if not FACTORY_TELEGRAM_BOT_TOKEN:
        return ""
    return hmac.new(
        FACTORY_TELEGRAM_BOT_TOKEN.encode("utf-8"),
        b"factoryos-telegram-webhook-v1",
        hashlib.sha256,
    ).hexdigest()


def _telegram_webhook_authorized(request: Request) -> bool:
    expected=_telegram_webhook_secret()
    supplied=(request.headers.get("x-telegram-bot-api-secret-token") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(supplied,expected))


def _telegram_bridge_authorized(request: Request) -> bool:
    """#114 C-4: once FACTORY_TELEGRAM_BRIDGE_TOKEN is set, only it opens the bridge (the MCP connector token, which
    the public /mcp also accepts in a URL, no longer reads the owner's inbox). Unset: the old MCP-token behaviour."""
    token=os.environ.get("FACTORY_TELEGRAM_BRIDGE_TOKEN","").strip() or FACTORY_MCP_TOKEN
    if not token:
        return False
    auth=(request.headers.get("authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return False
    supplied=auth.split(" ",1)[1].strip()
    return bool(supplied and hmac.compare_digest(supplied,token))


def _telegram_load_state() -> dict:
    if not TELEGRAM_OWNER_FILE.exists():
        return {}
    try:
        value=json.loads(TELEGRAM_OWNER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return value if isinstance(value,dict) else {}


def _telegram_save_state(state: dict) -> None:
    TELEGRAM_OWNER_FILE.parent.mkdir(parents=True,exist_ok=True)
    payload=dict(state or {})
    tmp=TELEGRAM_OWNER_FILE.with_suffix(".tmp")
    with _telegram_state_lock:
        tmp.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,TELEGRAM_OWNER_FILE)
        try:
            TELEGRAM_OWNER_FILE.chmod(0o600)
        except OSError:
            pass


def _telegram_pair_code_hash(code: str) -> str:
    return hashlib.sha256(str(code or "").strip().encode("utf-8")).hexdigest()


def _telegram_pair_code_matches(code: str, expected_hash: str) -> bool:
    candidate=_telegram_pair_code_hash(code)
    return bool(expected_hash and hmac.compare_digest(candidate,str(expected_hash)))


def _telegram_api(method: str, payload: Optional[dict]=None) -> dict:
    if not FACTORY_TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Telegram bot token is not configured")
    url=f"https://api.telegram.org/bot{FACTORY_TELEGRAM_BOT_TOKEN}/{method}"
    body=json.dumps(payload or {}).encode("utf-8")
    req=urlrequest.Request(url,data=body,headers={"Content-Type":"application/json"},method="POST")
    try:
        with urlrequest.urlopen(req,timeout=25) as response:
            result=json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Telegram API {method} failed") from exc
    if not isinstance(result,dict) or not result.get("ok"):
        raise RuntimeError(f"Telegram API {method} returned not-ok")
    return result


def _telegram_send_markup(chat_id: str, text: str, reply_markup: Optional[dict]=None):
    """#129: send to any chat the bridge already authorised (the paired group); never raises."""
    try:
        payload={"chat_id":str(chat_id),"text":str(text)[:4000]}
        if reply_markup:payload["reply_markup"]=reply_markup
        _telegram_api("sendMessage",payload)
        return True
    except Exception:
        return False

def _telegram_send_to(chat_id: str, text: str) -> bool:
    target=str(chat_id or "").strip()
    if not target or not FACTORY_TELEGRAM_BOT_TOKEN:
        return False
    _telegram_api("sendMessage",{"chat_id":target,"text":str(text or "")[:4000]})
    return True


def _telegram_send(text: str) -> bool:
    state=_telegram_load_state()
    return _telegram_send_to(str(state.get("chat_id") or ""),text)


def _telegram_public_status() -> dict:
    state=_telegram_load_state()
    pending=state.get("pending") if isinstance(state.get("pending"),dict) else {}
    expires_at=float(pending.get("expires_at") or 0)
    return {
        "configured": bool(FACTORY_TELEGRAM_BOT_TOKEN),
        "paired": bool(state.get("chat_id")),
        "username": str(state.get("username") or ""),
        "bot_username": str(state.get("bot_username") or ""),
        "paired_at": state.get("paired_at"),
        "pairing_pending": bool(pending and expires_at>time.time()),
        "pairing_expires_at": datetime.fromtimestamp(expires_at,timezone.utc).isoformat() if expires_at else None,
        "inbox_count": len(state.get("inbox") or []) if isinstance(state.get("inbox"),list) else 0,
    }


@app.on_event("startup")
async def sync_telegram_relay_webhook():
    if not FACTORY_TELEGRAM_BOT_TOKEN:
        return
    try:
        await asyncio.to_thread(_telegram_api,"setWebhook",{
            "url":f"{FACTORY_PUBLIC_BASE_URL}/api/integrations/telegram/webhook",
            "secret_token":_telegram_webhook_secret(),
            "allowed_updates":["message","callback_query"],
            "drop_pending_updates":False,
        })
        await asyncio.to_thread(_telegram_api,"setMyCommands",{"commands":[
            {"command":"relay","description":"Открыть активные задачи Relay"},
            {"command":"tasks","description":"Задачи Relay и GitHub"},
            {"command":"task","description":"Детали задачи Relay: /task R-0001"},
            {"command":"history","description":"История действий Relay"},
            {"command":"proof","description":"Приёмка задачи по фактам: /proof R-0001"},
            {"command":"github","description":"GitHub PR, коммиты и CI"},
            {"command":"roadmap","description":"Roadmap и открытые задачи"},
            {"command":"new","description":"Создать новую задачу"},
            {"command":"ask","description":"Вопрос Claude: /ask текст"},
            {"command":"group","description":"Привязать группу FactoryOS Team"},
            {"command":"brief","description":"Ранковий брифінг 08:00: on / off / test"},
            {"command":"work","description":"Перевести тикет в работу"},
            {"command":"need","description":"Нужно действие от меня"},
            {"command":"done","description":"Закрыть тикет"},
            {"command":"operators","description":"Claude / Gemini: статус и тикеты"},
            {"command":"workers","description":"Открыть операторские ветки"},
            {"command":"status","description":"Проверить связь с FactoryOS"},
        ]})
        print(json.dumps({"event":"RELAY_TELEGRAM_WEBHOOK","status":"ready"}),flush=True)
    except Exception as exc:
        print(json.dumps({"event":"RELAY_TELEGRAM_WEBHOOK","status":"error","error":str(exc)[:300]}),flush=True)


class TelegramBridgeNotify(BaseModel):
    text: str
    kind: str = "info"
    task_id: Optional[str] = None


# T-592: facts (never text or chat ids) of every ticket view the bot delivered, for the server-side Telegram ↔ website check.
TELEGRAM_VIEWS = TelegramViewLog(DATA_DIR / "telegram_views.json")
install_relay_routes(app, RELAY_STORE, request_identity, queue=RELAY_QUEUE, authorize_worker=_claude_worker_authorized, notify_owner=_telegram_send,
                     authorize_gemini_worker=_gemini_worker_authorized, view_log=TELEGRAM_VIEWS)


def _telegram_web_report(ticket_id: str = "") -> dict:
    """T-592 card: the newest ticket the bot showed in detail (or the T-591 acceptance ticket) vs the website now."""
    tid = str(ticket_id or "").strip().upper()
    if not tid:
        latest = TELEGRAM_VIEWS.latest()
        if latest:
            tid = latest["ticket_id"]
        else:
            acc = latest_telegram_acceptance(RELAY_STORE.list(limit=100000))
            tid = (acc or {}).get("ticket_id") or ""
    ticket = RELAY_STORE.get(tid) if tid else None
    view = RELAY_QUEUE.view(ticket) if ticket else None
    report = telegram_web_compare(TELEGRAM_VIEWS.latest(tid) if tid else None, view)
    report["ticket_id"] = tid or report.get("ticket_id") or ""
    report["ticket_title"] = str((ticket or {}).get("title") or "")[:120]
    report["confirmation"] = confirmation_for(TELEGRAM_VIEWS.latest_confirmation(), report)
    return report


class TelegramWebConfirm(BaseModel):
    ticket_id: str
    verdict: str
    key: str = ""  # report_key of the card the owner saw


@app.get("/api/factory/telegram-web-compare")
def telegram_web_compare_view(request: Request, ticket_id: str = ""):
    if (request_identity(request) or {}).get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    return _telegram_web_report(ticket_id)


@app.post("/api/factory/telegram-web-compare/confirm")
def telegram_web_compare_confirm(payload: TelegramWebConfirm, request: Request):
    """The owner's one action for T-592-H: «Совпадает» / «Не совпадает» next to the server verdict."""
    if (request_identity(request) or {}).get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    report = _telegram_web_report(payload.ticket_id)
    if not report["ticket_id"]:
        raise HTTPException(404, "No Relay ticket to compare")
    try:
        entry = TELEGRAM_VIEWS.confirm(report["ticket_id"], payload.verdict, report, payload.key)
    except StaleComparison as exc:
        raise HTTPException(409, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "confirmation": entry, "report": {**report, "confirmation": entry}}

def _agent_relay_forbidden_tokens():
    """PR #314 review B4: the agent relay tokens must not reuse any broader FactoryOS credential."""
    return (FACTORY_CLAUDE_WORKER_TOKEN, FACTORY_CLAUDE_WORKER_TOKEN_EC2, FACTORY_OPERATOR_WORKER_TOKEN, FACTORY_PASSWORD,
            os.environ.get("FACTORY_TELEGRAM_BRIDGE_TOKEN", ""), FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN, FACTORY_MCP_TOKEN)

AGENT_MESSAGES = install_agent_message_routes(app, RELAY_STORE, _agent_relay_forbidden_tokens)

def _mcp_lane_forbidden_tokens():
    """T-604: a per-lane MCP token must not reuse the shared MCP token or any other FactoryOS credential."""
    return _agent_relay_forbidden_tokens()+(os.environ.get("FACTORY_CLAUDE_RELAY_TOKEN",""),os.environ.get("FACTORY_CODEX_RELAY_TOKEN",""))

AGENT_WORKSPACE = agent_workspace.AgentWorkspace(RELAY_STORE, RELAY_QUEUE, known_secrets=_mcp_lane_forbidden_tokens)
agent_workspace.install_routes(app, AGENT_WORKSPACE, lambda: agent_workspace.lane_status(forbidden=_mcp_lane_forbidden_tokens()))
agent_workspace.install_access_log_redaction()

def _owner_desk_status():
    """Live facts for the owner runbooks; never calls a provider. Lines are keys localized by owner_desk_i18n."""
    out={}
    tg=_telegram_public_status()
    if tg.get("paired"):
        out["T-506"]={"state":"done","detail_key":"tg_paired","args":{"bot":f" (@{tg['bot_username']})" if tg.get("bot_username") else ""}}
    elif tg.get("configured"):
        out["T-506"]={"state":"todo","detail_key":"tg_configured"}
    else:
        out["T-506"]={"state":"todo","detail_key":"tg_no_token"}
    out["T-590-H"]={"state":"info","detail_key":"prod_sha","args":{"sha":BUILD_SHA[:12]}}
    acc=latest_telegram_acceptance(RELAY_STORE.list(limit=100000))
    if acc and acc["status"]=="VERIFIED":
        out["T-591-H"]={"state":"done","detail_key":"accept_verified","args":{"ticket":acc["ticket_id"],"run":acc["run_id"]}}
    elif acc:
        out["T-591-H"]={"state":"todo","detail_key":"accept_partial","args":{"ticket":acc["ticket_id"],"missing":", ".join(acc["missing"]) or (acc["problems"][0][:80] if acc["problems"] else "—")}}
    else:
        out["T-591-H"]={"state":"todo","detail_key":"accept_none"} if tg.get("paired") else {"state":"blocked","detail_key":"waits","args":{"task":"T-506"}}
    confirmation=TELEGRAM_VIEWS.latest_confirmation()
    try:
        current=_telegram_web_report((confirmation or {}).get("ticket_id") or "")
    except Exception:
        current=None
    out["T-592-H"]=telegram_compare_status(confirmation,
                                           out["T-591-H"]["state"]=="done" or roadmap_states().get("T-591-H") is True,current)
    out["T-593-H"]={"state":"todo","detail_key":"t593_live"}
    reg=get_publisher_adapter_registry()
    metricool=next((a for a in reg.get("adapters") or [] if a.get("kind")=="metricool"),{})
    youtube=next((a for a in reg.get("adapters") or [] if a.get("kind")=="youtube"),{})
    if reg.get("selected")=="youtube":
        out["T-520"]=({"state":"done","detail_key":"youtube_ok","args":{"channel":youtube.get("channel_title") or "—"}}
                      if youtube.get("configured") else
                      {"state":"todo","detail_key":"youtube_blocked","args":{"reasons":", ".join(youtube.get("blockers") or [])}})
    elif reg.get("selected")=="metricool" and metricool.get("configured"):
        out["T-520"]={"state":"done","detail_key":"metricool_ok" if metricool.get("youtube_audience_configured") else "metricool_no_audience"}
    elif reg.get("selected")=="metricool":
        out["T-520"]={"state":"todo","detail_key":"metricool_unconfigured"}
    else:
        out["T-520"]={"state":"todo","detail_key":"publisher_selected","args":{"adapter":reg.get("selected") or "manual"}}
    out["T-521"]={"state":"todo","detail_key":"can_start"} if out["T-520"]["state"]=="done" else {"state":"blocked","detail_key":"waits","args":{"task":"T-520"}}
    out["T-551"]={"state":"optional","detail_key":"t551_youtube_in_t520"}
    out["T-598-H1"]={"state":"done","detail_key":"h1_done"}
    out["T-598-H2"]={"state":"optional","detail_key":"h2_optional"}
    out["T-605"]={"state":"done","detail_key":"gemini_key_ok"} if FACTORY_GEMINI_API_KEY else {"state":"todo","detail_key":"gemini_key_missing"}
    out["T-606"]={"state":"todo","detail_key":"jules_pending"}
    return out

def _mycast_send_audio(audio, filename, title, caption):
    telegram_send_audio(FACTORY_TELEGRAM_BOT_TOKEN, str(_telegram_load_state().get("chat_id") or ""), audio,
                        filename=filename, title=title, caption=caption)

MYCAST_DELIVERIES = DeliveryLog(DATA_DIR/"mycast_delivered.json")
GROUP_GEMINI_PROMPT=("Ты Gemini — участник рабочего чата FactoryOS Team вместе с владельцем и Claude. "
                    "Отвечай по-русски, по делу, до 1200 символов, без воды. Если не знаешь фактов о проекте — так и скажи, "
                    "не выдумывай статусы, цифры и результаты. Claude ответит отдельно, не повторяй его.\n\n")


def _group_gemini(prompt):
    """Owner 2026-11-11: Gemini joins /discuss on the owner's free key (stable Flash, picked per key)."""
    return _gemini_text(GROUP_GEMINI_PROMPT+str(prompt)[:6000])


def _gemini_text(full_prompt):
    """One free-key Gemini text answer: (text, "") or (None, reason in Russian). Never raises."""
    if not FACTORY_GEMINI_API_KEY:
        return None,"ключ Gemini не задан"
    try:
        model=resolve_flash_model(FACTORY_GEMINI_API_KEY)
        data=_gemini_raw_call(FACTORY_GEMINI_API_KEY,"POST",f"models/{model}:generateContent",
                              {"contents":[{"parts":[{"text":str(full_prompt)[:8000]}]}],
                               "generationConfig":{"maxOutputTokens":1024,"temperature":0.4}},None,60)
    except Exception as exc:
        status=getattr(exc,"detail",{}) if isinstance(getattr(exc,"detail",None),dict) else {}
        return None,{429:"перегружен, попробуй позже",404:"модель недоступна"}.get(status.get("upstream_status"),"недоступен")
    parts=((((data or {}).get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    text="".join(str(p.get("text") or "") for p in parts).strip()
    return (text[:6000],"") if text else (None,"пустой ответ")


GROUP_BRIDGE = GroupBridge(DATA_DIR, ask=lambda text, source_key="", meta=None: OWNER_QUESTIONS.create(TELEGRAM_TASK,"","",text,source_key=source_key,meta=meta),
                           gemini=_group_gemini)
VOICE_TRANSCRIBER = VoiceTranscriber(DATA_DIR, api_key=lambda: FACTORY_GEMINI_API_KEY, bot_token=lambda: FACTORY_TELEGRAM_BOT_TOKEN)
VOICE_REASONS = {"not_configured":"ключ Gemini не задан","daily_limit":"дневной лимит 30 голосовых исчерпан","too_long":"слишком длинное, больше ~3 минут","rate_limited":"Gemini перегружен, попробуй позже","invalid_key":"ключ Gemini не принят","telegram_file_unavailable":"Telegram не отдал файл","empty_transcript":"пустой результат","model_not_found":"модель Gemini недоступна"}
VOICE_SETTINGS = VoiceSettingsStore(DATA_DIR)
VOICE_HISTORY = VoiceHistory(DATA_DIR)
_mycast_paired = lambda: bool(FACTORY_TELEGRAM_BOT_TOKEN and _telegram_public_status().get("paired"))
install_mycast_routes(app, MYCAST_DELIVERIES, authorize_worker=_claude_worker_authorized,
                      send_audio=_mycast_send_audio, paired=_mycast_paired)
# Natural two-host voice with the owner's Gemini key; the worker falls back to Piper when this returns 409/502.
install_mycast_voice_routes(app, MYCAST_DELIVERIES, authorize_worker=_claude_worker_authorized,
                            send_audio=_mycast_send_audio, paired=_mycast_paired, api_key=lambda: FACTORY_GEMINI_API_KEY,
                            model=os.environ.get("FACTORY_MYCAST_TTS_MODEL", "").strip(),
                            voices=lambda: VOICE_SETTINGS.current_pair(),
                            on_result=lambda row: VOICE_HISTORY.record(kind="mycast", item_id=row["id"], status=row["status"],
                                                                      seconds=row.get("seconds", 0),
                                                                      voice="+".join(VOICE_SETTINGS.current_pair())))
# #140: the owner picks the daily two-host pair; owner-only API, same catalogue and pair rule as the demo.
install_voice_settings_routes(app, VOICE_SETTINGS, is_owner=lambda r: (request_identity(r) or {}).get("role") == "owner")
install_voice_history_routes(app, VOICE_HISTORY, is_owner=lambda r: (request_identity(r) or {}).get("role") == "owner")
# Morning brief in the owner's host-A voice, once per date: the worker route and the #106 08:00 schedule share it.
BRIEF_DELIVER = install_brief_route(app, VOICE_HISTORY, MYCAST_DELIVERIES, VOICE_SETTINGS, authorize_worker=_claude_worker_authorized,
                    api_key=lambda: FACTORY_GEMINI_API_KEY, paired=_mycast_paired,
                    tts_single=lambda key, text, voice: gemini_single_voice_pcm(key, text, voice),
                    encode=pcm_to_mp3, send_audio=_mycast_send_audio, check_audio=lambda audio: check_mp3(audio))

# Gemini coder loop on EC2 calls Google through this proxy, so the key never leaves Render.
install_gemini_worker_routes(app, authorize_worker=_claude_worker_authorized, api_key=lambda: FACTORY_GEMINI_API_KEY)
# MyCast public demo (owner 2026-11-06): Gemini voices, at most 30 new per UTC day, cached, one at a time.
def _subtopics_generate(key,prompt):
    try:
        model=resolve_flash_model(key)
        data=_gemini_raw_call(key,"POST",f"models/{model}:generateContent",
                              {"contents":[{"parts":[{"text":prompt}]}],
                               "generationConfig":{"responseMimeType":"application/json","maxOutputTokens":512,"temperature":0.5}},None,20)
    except Exception:
        return None
    parts=((((data or {}).get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    return "".join(str(p.get("text") or "") for p in parts) or None


MYCAST_SUBTOPICS=SubtopicService(DATA_DIR/"mycast_subtopics",api_key=lambda: FACTORY_GEMINI_API_KEY,generate=_subtopics_generate)


@app.get("/api/mycast/subtopics")
def mycast_subtopics(request: Request, q: str = "", lang: str = "en"):
    """Public beta: AI subtopic suggestions on the free Gemini key; capped, cached, never an error page."""
    return MYCAST_SUBTOPICS.suggest(q,lang,_mycast_client_id(request))


MYCAST_DEMO = DemoService(DATA_DIR / "mycast_demo", api_key=lambda: FACTORY_GEMINI_API_KEY, tts=gemini_tts_pcm,
                          tts_single=lambda key, text, voice: gemini_single_voice_pcm(key, text, voice))
install_mycast_demo_routes(app, MYCAST_DEMO)
# #281 voice audition: real cached Gemini samples per prebuilt voice (owner: about 30 samples), honest unavailable states.
install_mycast_voice_audition_routes(app, VoiceSamples(DATA_DIR / "mycast_voices", api_key=lambda: FACTORY_GEMINI_API_KEY,
                                                       tts=lambda key, text, voice: gemini_single_voice_pcm(key, text, voice)))


def _mycast_demo_tts_no_retry(key, episode):
    """T-665: the MyCast two-host TTS without its 429 wait-and-retry: a 429 stops the owner's run at once."""
    def _stop(_seconds):
        raise MycastGeminiTTSError("rate_limited")
    return gemini_tts_pcm(key, episode, voices=tuple(episode.get("voices") or ("Charon", "Kore")), sleep=_stop)


MYCAST_DEMO_AUDIO = DemoAudioStore(DATA_DIR / "mycast_demo_audio", api_key=lambda: FACTORY_GEMINI_API_KEY,
                                   tts=_mycast_demo_tts_no_retry, encode=lambda pcm, rate: pcm_to_mp3(pcm, rate),
                                   qc=lambda pcm, rate, lines: mycast_check_pcm(pcm, rate, lines))
install_mycast_demo_audio_routes(app, MYCAST_DEMO_AUDIO,
                                 is_owner=lambda r: (request_identity(r) or {}).get("role") == "owner")
import mycast_share_page as _mycast_share_page  # noqa: E402
_mycast_share_page.set_demo_audio_source(MYCAST_DEMO_AUDIO.approved_url)
def _mycast_send_listener_sample(chat_id: str, job_id: str) -> None:
    """#281: one generated demo, as mp3, to the listener's own Telegram chat (delivery opt-in checked by the caller)."""
    import wave
    from mycast import pcm_to_mp3
    try:
        path = MYCAST_DEMO.audio_path(job_id)
    except Exception:
        raise MyCastAccountError("demo_not_ready", 409)
    with wave.open(str(path)) as w:
        pcm, rate = w.readframes(w.getnframes()), w.getframerate()
    telegram_send_audio(FACTORY_TELEGRAM_BOT_TOKEN, str(chat_id), pcm_to_mp3(pcm, rate), filename="mycast-demo.mp3",
                        title="MyCast · демо", caption="Демо MyCast (не справжній випуск). Розсилку можна зупинити на сторінці MyCast.")
def _telegram_fetch_file(file_id: str, limit: int = 20 * 1024 * 1024) -> bytes:
    """#317 history: download a file the bot sent earlier (Bot API getFile, max 20 MB). Nothing is cached on disk."""
    path=str((_telegram_api("getFile",{"file_id":file_id}).get("result") or {}).get("file_path") or "")
    if not path or ".." in path:
        raise RuntimeError("Telegram file not available")
    req=urlrequest.Request(f"https://api.telegram.org/file/bot{FACTORY_TELEGRAM_BOT_TOKEN}/{path}")
    with urlrequest.urlopen(req,timeout=60) as response:
        data=response.read(limit+1)
    if len(data)>limit:
        raise RuntimeError("Telegram file too large")
    return data
_MYCAST_BOT_NAME = {"name": "", "at": 0.0}
def _mycast_bot_username() -> str:
    # The Login Widget needs the bot's public @username; ask Telegram once an hour, never expose the token.
    if time.time() - _MYCAST_BOT_NAME["at"] > 3600:
        _MYCAST_BOT_NAME.update(name=str((_telegram_api("getMe").get("result") or {}).get("username") or ""), at=time.time())
    return _MYCAST_BOT_NAME["name"]
# MyCast listener accounts (owner 2026-11-06: open beta, Telegram + Google). Separate cookie; never a staff session.
MYCAST_LISTENERS = ListenerStore(DATA_DIR / "mycast_listeners.json")


def _mycast_keyring():
    from browser_runner.vault import Keyring
    return Keyring.from_env()


# Owner 2026-11-13: "Підключити Google Календар" — read-only, refresh token encrypted with FACTORY_VAULT_KEY.
MYCAST_CALENDAR = ListenerCalendar(MYCAST_LISTENERS, keyring=_mycast_keyring, client_id=lambda: FACTORY_GOOGLE_CLIENT_ID,
                                   client_secret=lambda: FACTORY_GOOGLE_CLIENT_SECRET, secret=FACTORY_SECRET,
                                   redirect_uri=FACTORY_MYCAST_CALENDAR_REDIRECT)
install_calendar_routes(app, MYCAST_CALENDAR, current_slug=lambda request: mycast_unsign(
    FACTORY_SECRET, request.cookies.get(MYCAST_COOKIE, ""), time.time()))
install_mycast_account_routes(app, MYCAST_LISTENERS, secret=FACTORY_SECRET,
                              bot_token=lambda: FACTORY_TELEGRAM_BOT_TOKEN, bot_username=_mycast_bot_username,
                              google_client_id=lambda: FACTORY_GOOGLE_CLIENT_ID,
                              google_verify=lambda cred: google_id_token.verify_oauth2_token(cred, google_requests.Request(), FACTORY_GOOGLE_CLIENT_ID),
                              secure_cookie=FACTORY_PUBLIC_BASE_URL.startswith("https://"),
                              send_message=lambda chat, text: _telegram_api("sendMessage", {"chat_id": chat, "text": text}),
                              send_sample=_mycast_send_listener_sample, fetch_audio=_telegram_fetch_file,
                              calendar_available=MYCAST_CALENDAR.available,
                              on_delete=MYCAST_CALENDAR.disconnect)
install_gemini_verify_route(app, request_identity=request_identity, api_key=lambda: FACTORY_GEMINI_API_KEY)
# #317: website listeners' daily episodes. The EC2 worker writes the script; the server re-checks every gate,
# voices it with the listener's own voices and sends it only to the listener's own chat.
MYCAST_LISTENER_DELIVERY = ListenerDelivery(MYCAST_LISTENERS, calendar=MYCAST_CALENDAR.today)
install_listener_delivery_routes(
    app, MYCAST_LISTENER_DELIVERY, authorize_worker=_claude_worker_authorized, api_key=lambda: FACTORY_GEMINI_API_KEY,
    tts=gemini_tts_pcm, encode=lambda pcm, rate: pcm_to_mp3(pcm, rate, bitrate=64),  # 30 min ≈ 14 MB < Telegram's 20 MB re-download limit
    check_pcm=mycast_check_pcm, identity=request_identity,
    send_audio=lambda chat, audio, filename, title, caption: telegram_send_audio(
        FACTORY_TELEGRAM_BOT_TOKEN, str(chat), audio, filename=filename, title=title, caption=caption))

# Owner 2026-11-14: brand strategy passport (7-step chain) -> Master Brief; MyCast starts from Claude's draft.
from brand_strategy import StrategyStore, install_strategy_routes
from brand_strategy_seeds import SEEDS as STRATEGY_SEEDS
STRATEGY = StrategyStore(DATA_DIR / "brand_strategy.json", seeds=STRATEGY_SEEDS)


async def _strategy_draft(agent, system, user):
    """One owner-clicked LLM call, inside the daily budget guard and recorded as an agent run."""
    _content_brain_budget_guard(1800)
    model = _workflow_model(None)
    run_id = start_agent_run(agent, None, "brand_strategy", model=model)
    try:
        result = await asyncio.wait_for(asyncio.to_thread(_content_brain_llm, agent, system, user, 1800, model),
                                        timeout=AGENT_TIMEOUT_SECONDS)
    except Exception as exc:
        finish_agent_run(run_id, status="failed", error=str(exc), meta={"brand_strategy": True})
        raise RuntimeError(str(exc)) from exc
    finish_agent_run(run_id, status="completed", input_tokens=result["input_tokens"], output_tokens=result["output_tokens"],
                     cost_usd=result["cost_usd"], meta={"brand_strategy": True})
    return result


async def _strategy_job(title, brief, fmt):
    """Stage 2: a plan row becomes an ordinary inbox job through the normal job route."""
    out = await create_job(JobCreate(title=title[:200], brief=brief, format=(fmt or "Long + Shorts")[:80], language="Russian"))
    return out["id"]


def _strategy_job_exists(job_id):
    con = db()
    try:
        return con.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is not None
    finally:
        con.close()


install_strategy_routes(app, STRATEGY, identity=request_identity, draft=_strategy_draft, create_job=_strategy_job,
                        job_exists=_strategy_job_exists)

# Owner 2026-11-15 (T-MODS): Mods & skills — one-button on/off for skills and features, with usage and before/after.
from mods_registry import ModsStore, install_mods_routes
MODS = ModsStore(DATA_DIR / "mods.json")


def _duel_job_state(job_id):
    job = get_job(job_id)
    return {"status": job.get("status") or "", "title": job.get("title") or ""} if job else None


def _duel_ticket_state(ticket_id):
    t = RELAY_STORE.get(ticket_id)
    if not t:
        return None
    ex = t.get("execution") or {}
    return {"status": t.get("status") or "", "execution": ex.get("state") or "", "note": str(ex.get("note") or "")[:400]}


install_mods_routes(app, MODS, identity=request_identity, worker_auth=_claude_worker_authorized,
                    create_job=_strategy_job, job_state=_duel_job_state, ticket_state=_duel_ticket_state,
                    create_ticket=lambda title, body, key: RELAY_STORE.create(
                        title, body, source={"channel": "mods-duel", "source_key": key, "url": ""},
                        created_by="mods-duel", owner="claude")[0]["id"],
                    media_dir=DATA_DIR / "mods_media")

OWNER_QUESTIONS = QuestionStore(DATA_DIR/"owner_questions.json")
MVP_REGISTRY = MvpRegistry(DATA_DIR / "mvp_factory.json")
FACELESS_CRM = FacelessCrm(DATA_DIR / "faceless_crm.json")  # #359 owner-only internal persona tracker
try:
    register_crm_mvp_project_once(MVP_REGISTRY, DATA_DIR / "faceless_crm_project_intake_v1.marker")
except (OSError, ValueError) as exc:
    # Never take down FactoryOS because of a draft project intake; leave no success marker on failure.
    print("Faceless Models CRM MVP intake blocked:", type(exc).__name__)
MVP_CHAT = AgentChat(DATA_DIR)


def _mvp_project(project_id):
    return next((p for p in MVP_REGISTRY.snapshot()["projects"] if p.get("id")==project_id),None)


def _mvp_connections():
    return {"gemini":bool(FACTORY_GEMINI_API_KEY),"github":bool(GITHUB_READ_TOKEN),"claude_worker":_claude_worker_online(),
            "render":BUILD_SHA!="local","channels":False}


def _mvp_route_answer(item):
    """Claude worker answers for MVP agents go back into the agent's chat (2026-11-11)."""
    meta=item.get("meta") if isinstance(item.get("meta"),dict) else {}
    pid,agent=meta.get("mvp_project"),meta.get("mvp_agent")
    if not pid or agent not in MVP_AGENT_IDS:
        return False
    try:MVP_CHAT.add(pid,agent,"agent",str(item.get("answer") or "")[:1500] or "(порожня відповідь)",ref=str(item.get("id") or ""))
    except ValueError:pass
    return True


MVP_ARTIFACTS=MvpArtifacts(DATA_DIR)


def _mvp_ticket_done(ticket):
    """Build hand-off needs real evidence: the Relay ticket closed on merged PR + CI, not by an owner override."""
    ver=ticket.get("verification") or {}
    return ticket.get("status")=="done" and not ver.get("override") and _evidence.level(ticket) in ("checked","accepted")


MVP_PIPELINE=MvpPipeline(DATA_DIR,registry=MVP_REGISTRY,chat=MVP_CHAT,artifacts=MVP_ARTIFACTS,gemini=lambda prompt:_gemini_text(prompt),
    create_ticket=lambda title,body,key,pid:RELAY_STORE.create(title,body,source={"channel":"mvp","source_key":key,"url":""},
                                                               created_by="mvp-pipeline",owner="claude")[0],
    get_ticket=lambda tid:RELAY_STORE.get(tid) if tid else None,ticket_done=_mvp_ticket_done)


def _mvp_owner(request,members=False):
    role=(request_identity(request) or {}).get("role")
    if role!="owner" and not (members and role=="member"):
        raise HTTPException(403,"owner_only")


@app.get("/api/mvp-factory/{project_id}/artifacts/{name}")
def mvp_artifact(project_id: str, name: str, request: Request):
    if not request_identity(request):
        raise HTTPException(401,"login required")
    text=MVP_ARTIFACTS.read(project_id,name)
    if text is None:
        raise HTTPException(404,"unknown_artifact")
    media="application/json" if name.endswith(".json") else "text/markdown"
    return Response(text,media_type=media+"; charset=utf-8")


@app.post("/api/mvp-factory/{project_id}/autopilot")
async def mvp_autopilot(project_id: str, request: Request):
    """Owner starts or stops the agents' hand-off for one project (free Gemini key; build still needs the owner)."""
    _mvp_owner(request)
    if not _mvp_project(project_id):
        raise HTTPException(404,"unknown_project")
    try:body=await request.json()
    except ValueError:body={}
    on=bool((body or {}).get("on")) if isinstance(body,dict) else False
    return MVP_PIPELINE.set_autopilot(project_id,on)


@app.post("/api/mvp-factory/{project_id}/spec/approve")
def mvp_spec_approve(project_id: str, request: Request):
    """The owner's "так" on the spec: spec_review → build_queued with the spec as evidence. Agents can't do this."""
    _mvp_owner(request)
    project=_mvp_project(project_id)
    if not project or project.get("stage")!="spec_review":
        raise HTTPException(409,"not_in_spec_review")
    version=int(MVP_PIPELINE.state(project_id).get("spec_version") or 0)
    if not version:
        raise HTTPException(409,"no_spec")
    out=MVP_REGISTRY.record(project_id,"advance",actor_role="owner",actor=(request_identity(request) or {}).get("email") or "owner",
                            evidence=[f"/api/mvp-factory/{project_id}/artifacts/spec-v{version}.md"],
                            note=f"owner approved spec v{version}",idempotency_key=f"mvp:{project_id}:approve:{version}")
    MVP_CHAT.add(project_id,"spec","system",f"✅ Власник затвердив ТЗ v{version}. Передаю Builder'у.")
    return out


@app.post("/api/mvp-factory/{project_id}/spec/redo")
async def mvp_spec_redo(project_id: str, request: Request):
    """Battle: redo the spec on another variant and/or with the owner's feedback (before approval)."""
    _mvp_owner(request,members=True)
    project=_mvp_project(project_id)
    if not project or project.get("stage") not in ("spec_draft","spec_review"):
        raise HTTPException(409,"not_in_spec_stage")
    try:body=await request.json()
    except ValueError:body={}
    body=body if isinstance(body,dict) else {}
    variant=str(body.get("variant") or "").strip().upper()[:2]
    if variant:
        MVP_PIPELINE._update(project_id,variant=variant)
    feedback=str(body.get("feedback") or "")[:1500]
    threading.Thread(target=lambda:MVP_PIPELINE.run_spec(project,feedback),daemon=True).start()
    return {"ok":True,"variant":variant or MVP_PIPELINE.state(project_id).get("variant")}


@app.get("/api/mvp-factory/{project_id}/cycle")
def mvp_project_cycle(project_id: str, request: Request):
    """MVP Builder panel: phase, five agents, what they produced, what to connect, their chats. Read-only facts."""
    if not request_identity(request):
        raise HTTPException(401,"login required")
    project=_mvp_project(project_id)
    if not project:
        raise HTTPException(404,"unknown_project")
    view=mvp_cycle_view(project,_mvp_connections(),MVP_CHAT.thread(project_id))
    st=MVP_PIPELINE.state(project_id)
    view["pipeline"]={"autopilot":bool(st.get("autopilot")),"variant":st.get("variant"),"spec_version":st.get("spec_version"),
                      "build_ticket":st.get("build_ticket"),"last_error":st.get("last_error"),
                      "artifacts":[f"/api/mvp-factory/{project_id}/artifacts/{n}" for n in MVP_ARTIFACTS.names(project_id)]}
    return view


@app.post("/api/mvp-factory/{project_id}/agents/{agent}/message")
async def mvp_agent_message(project_id: str, agent: str, request: Request):
    """Owner → agent. Gemini roles answer at once (free key); Claude roles go through the worker question queue."""
    if (request_identity(request) or {}).get("role") not in ("owner","member"):
        raise HTTPException(403,"forbidden")
    project=_mvp_project(project_id)
    spec=next((a for a in MVP_AGENTS if a["id"]==agent),None)
    if not project or not spec:
        raise HTTPException(404,"unknown_project_or_agent")
    try:body=await request.json()
    except ValueError:body={}
    text=str((body or {}).get("text") or "") if isinstance(body,dict) else ""
    try:msg=MVP_CHAT.add(project_id,agent,"owner",text)
    except ValueError as exc:
        raise HTTPException(400,str(exc))
    chat=(MVP_CHAT.thread(project_id).get(agent) or [])
    if spec["engine"]=="claude":
        question=(f"MVP Builder · проєкт «{project.get('title')}» ({project.get('stage')}) · агент {spec['label']} "
                  f"({spec['does']}).\nТЗ (початок): {str(project.get('brief') or '—')[:500]}\n\nВласник: {msg['text'][:700]}")
        try:
            item=OWNER_QUESTIONS.create(TELEGRAM_TASK,"","",question,source_key=f"mvp:{project_id}:{agent}:{msg['at']}",
                                        meta={"mvp_project":project_id,"mvp_agent":agent})
            MVP_CHAT.add(project_id,agent,"system",f"📨 Передано Claude-воркеру ({item.get('id')}). Відповідь з'явиться тут.")
        except Exception:
            MVP_CHAT.add(project_id,agent,"system","⚠️ Черга Claude зараз недоступна, повідомлення збережено.")
        return {"ok":True,"routed":"claude_worker"}
    prompt=mvp_agent_prompt(project,spec,msg["text"],chat)

    def work():
        text_out,reason=_gemini_text(prompt)
        MVP_CHAT.add(project_id,agent,"agent" if text_out else "system",
                     text_out or f"⚠️ Gemini не відповів ({reason}). Повідомлення збережено.")
    threading.Thread(target=work,daemon=True).start()
    return {"ok":True,"routed":"gemini"}
# T-560 wiring: owner's read-only browser tasks, run by the EC2 runner (Playwright never runs on Render).
BROWSER_TASKS = BrowserTaskStore(DATA_DIR)
# T-560-H Surfer for every MCP-connected agent; Google search via Gemini only after the owner opts in (may be billed).
WEB_SEARCH = web_surfer.WebSearch(DATA_DIR, provider=lambda: os.environ.get("FACTORY_WEB_SEARCH_PROVIDER", ""),
                                  gemini_key=lambda: FACTORY_GEMINI_API_KEY, gemini_model=resolve_flash_model)
web_surfer.install_worker_routes(app, store=BROWSER_TASKS, search=WEB_SEARCH, authorize_worker=_claude_worker_authorized)
def _browser_session_domains(provider: str, account: str) -> list:
    parts = _vault_parts(required=False)
    if not parts or not _VAULT_SLUG.match(provider or "") or not _VAULT_ACCOUNT.match(account or ""):
        return []
    info = parts[1].check(workspace_id=tenancy.binding_workspace(), provider=provider, account_binding_id=account)
    return [d.lower() for d in info.get("domains") or []] if info.get("ok") else []


def _browser_session_state(provider: str, account: str):
    parts = _vault_parts(required=False)
    if not parts:
        return None
    sessions, workspace = parts[1], tenancy.binding_workspace()
    ref = sessions._registry.resolve(workspace, provider, account)
    if not ref:
        return None
    return sessions.load(ref, workspace_id=workspace, provider=provider, account_binding_id=account).reveal()


def _surfer_session(raw, url: str) -> dict:
    """T-560-L: MCP web_read may use a saved vault login only if the owner switched "allow agents" on for it and the
    page is on one of its cookie domains. The refusal lists the allowed logins (site/account only, no secrets)."""
    from urllib.parse import urlsplit
    from browser_runner.sessions import VaultError
    if isinstance(raw,dict):provider,account=str(raw.get("provider") or ""),str(raw.get("account") or "")
    else:provider,_,account=str(raw or "").strip().partition("/")
    provider,account=provider.strip().lower(),(account.strip() or "default")
    parts=_vault_parts(required=False)
    workspace=tenancy.binding_workspace()
    allowed=[e for e in (parts[1].entries(workspace) if parts else []) if e.get("agent_use") is True]
    listing=", ".join(f"{e['provider']}/{e['account']} ({', '.join((e.get('domains') or [])[:2])})" for e in allowed[:5]) or "none"
    if not parts or not _VAULT_SLUG.match(provider) or not _VAULT_ACCOUNT.match(account):
        raise HTTPException(403,f"saved login not allowed for agents; allowed: {listing}")
    try:
        ok=parts[1].agent_use(workspace_id=workspace,provider=provider,account_binding_id=account)
    except VaultError:
        ok=False
    if not ok:
        raise HTTPException(403,f"saved login not allowed for agents; allowed: {listing}")
    domains=_browser_session_domains(provider,account)
    host=(urlsplit(url).hostname or "").lower()
    if not domains or not any(host==d or host.endswith("."+d) for d in domains):
        raise HTTPException(400,f"the page is not on a domain of {provider}/{account}: {', '.join(domains[:3]) or 'none'}")
    return {"provider":provider,"account":account}


install_browser_task_routes(app, BROWSER_TASKS, identity=request_identity, authorize_worker=_claude_worker_authorized,
                            authorize_agent=_browser_agent_authorized,
                            session_domains=_browser_session_domains, session_state=_browser_session_state)
install_mvp_factory_routes(app, MVP_REGISTRY, request_identity)  # #186: evidence-gated MVP registry, never dispatches
MYBRIEF_FEEDBACK = MyBriefFeedback(DATA_DIR / "mybrief_feedback.json", mybrief_catalog())
install_mybrief_routes(app, MYBRIEF_FEEDBACK, request_identity)  # T-615 #188 pilot: fixture briefs, opt-in feedback
from mvp_evolution import EvolutionStore, install_mvp_evolution_routes  # noqa: E402
MVP_EVOLUTION = EvolutionStore(DATA_DIR / "mvp_evolution.json", project_exists=lambda pid: _mvp_project(pid) is not None)
_mvp_evolution_ticket = lambda title, body, key, lane: RELAY_STORE.create(  # noqa: E731
    title, body, source={"channel": "mvp-evolution", "source_key": key, "url": ""}, created_by="mvp-evolution", owner=lane)[0]
install_mvp_evolution_routes(  # T-630 #270: consented feedback -> themes -> owner-approved V2 proposal -> one Relay ticket
    app, MVP_EVOLUTION, request_identity, ticket_lookup=RELAY_STORE.get, ticket_verified=_mvp_ticket_done,
    mybrief_entries=MYBRIEF_FEEDBACK.consented_entries, create_ticket=_mvp_evolution_ticket)
from mvp_quiz import QuizService, install_mvp_quiz_routes  # noqa: E402
install_mvp_quiz_routes(  # T-634 #270: optional MyCast quiz -> analyst -> V2 task via Relay; gifts/mail held behind flags
    app, QuizService(DATA_DIR / "mvp_quiz.json", MVP_EVOLUTION, create_ticket=_mvp_evolution_ticket,
                     grant_days=MYCAST_LISTENERS.grant_bonus), request_identity,
    listener_fn=lambda request: mycast_unsign(FACTORY_SECRET, request.cookies.get(MYCAST_COOKIE, ""), time.time()) or "",
    client_fn=_mycast_client_id)
from mvp_experiments import install_mvp_experiment_routes  # noqa: E402
async def _ab_content_job(title, brief, job_id):
    """T-610: an A/B branch becomes an ordinary inbox job (draft only), the same row the normal job route writes.
    Codex review on #376: the id is deterministic per branch and the insert is INSERT OR IGNORE in one transaction with
    its workspace binding, so retries, slow creators and crashes can never make a second job. Nothing runs or publishes."""
    workspace = tenancy.normalize_workspace(tenancy.current() or tenancy.DEFAULT_WORKSPACE)
    con = db()
    try:
        now = ts()
        cur = con.execute("INSERT OR IGNORE INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                          (job_id, title[:200], brief, "inbox", "AI presenter", "Short only", "Russian", 8, "idle", 0, now, now))
        created = cur.rowcount == 1
        if created:
            assign_job_workspace(con, job_id, workspace)
        con.commit()
    finally:
        con.close()
    if created:
        event(job_id, f"Created: {title[:200]}")
        await broadcast()
    return job_id


install_mvp_experiment_routes(app, MVP_REGISTRY, request_identity, create_job=_ab_content_job)  # T-608..T-610 A/B Tester: drafts only, owner-gated
from mvp_launchpad import install_mvp_launchpad_routes  # noqa: E402
install_mvp_launchpad_routes(app, MVP_REGISTRY, request_identity)  # T-704 Launchpad: plans and evidence only, never changes a stage
install_faceless_crm_routes(app, FACELESS_CRM, request_identity)  # #359: private, zero-external-work CRM
from decision_memory import DecisionStore, install_decision_memory_routes, sync_mvp_registry_once  # noqa: E402
install_decision_memory_routes(app, DecisionStore(DATA_DIR / "decision_memory.json", BASE / "DECISIONS.md"), request_identity)  # T-614 #187: owner-only
try:
    sync_mvp_registry_once(MVP_REGISTRY, DATA_DIR / "decision_memory_registry_intake.marker")  # links the existing #187 pilot
except (OSError, ValueError) as exc:
    print("Decision Memory registry intake skipped:", type(exc).__name__)
from learn_center import install_learn_routes  # noqa: E402
import brand_strategy as _brand_strategy_mod  # noqa: E402
install_learn_routes(app, base=BASE, steps_source=lambda: _brand_strategy_mod.STEPS)  # owner 2026-11-14: one Learning section
install_open_questions_routes(app, MVP_REGISTRY, OWNER_QUESTIONS, request_identity)  # #321: read-only owner dashboard
from release_guardian import GitHubReader as _RgReader, ReleaseGuardian as _RgGuardian, install_release_guardian_routes  # noqa: E402
install_release_guardian_routes(app, _RgGuardian(_RgReader(GITHUB_REPO, _github_read_token)), request_identity)  # T-616 #189: owner-only, GET-only PR board
install_owner_desk_routes(app, OWNER_QUESTIONS, request_identity, authorize_worker=_claude_worker_authorized,
                          status_fn=_owner_desk_status,
                          redact_fn=lambda s: _redact_board_value(s,_board_secret_values()),
                          notify_owner=_telegram_send,
                          route_answer=lambda item: _mvp_route_answer(item) or GROUP_BRIDGE.deliver_answer(item,_telegram_send_markup))


# MyCast's own domain (owner bought mycast.pro, 2026-11-13). On it, only MyCast is served: the root opens the MyCast
# page and the FactoryOS dashboard/API stay on the onrender.com address. Comma-separated, lower case.
MYCAST_HOSTS = {h.strip().lower() for h in os.environ.get("FACTORY_MYCAST_HOSTS", "mycast.pro,www.mycast.pro").split(",") if h.strip()}
MYCAST_PAGE = "/static/mycast-configurator/index.html"
MYCAST_HOST_PREFIXES = ("/static/mycast-configurator/", "/static/favicon", "/static/apple-touch-icon", "/api/mycast/",
                        "/mycast/u/", "/mycast/e/", "/mycast/demo/", "/.well-known/")
MYCAST_HOST_PATHS = {"/privacy", "/terms", "/health", "/favicon.ico", "/mycast", "/robots.txt", "/sitemap.xml"}


def _mycast_host_response(request: Request):
    """None when the request may go on; otherwise a redirect that keeps mycast.pro limited to MyCast."""
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if host not in MYCAST_HOSTS:
        return None
    path = request.url.path
    if host.startswith("www."):
        return RedirectResponse("https://" + host[4:] + (path if path != "/" else MYCAST_PAGE), status_code=301)
    if path in MYCAST_HOST_PATHS or path.startswith(MYCAST_HOST_PREFIXES):
        return None
    query = ("?" + request.url.query) if request.url.query and path == "/" else ""
    return RedirectResponse(MYCAST_PAGE + query, status_code=302)


@app.get("/privacy")
def mycast_privacy():
    return FileResponse(BASE/"static"/"mycast-configurator"/"privacy.html")


@app.get("/terms")
def mycast_terms():
    return FileResponse(BASE/"static"/"mycast-configurator"/"terms.html")


# Search Console (owner 2026-11-13): mycast.pro is indexable; the FactoryOS dashboard host is not.
MYCAST_SITEMAP_PATHS = ("/static/mycast-configurator/index.html", "/privacy", "/terms")


@app.get("/robots.txt", include_in_schema=False)
def robots_txt(request: Request):
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if host in MYCAST_HOSTS:
        body = "User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: https://" + host + "/sitemap.xml\n"
    else:
        body = "User-agent: *\nDisallow: /\n"
    return Response(body, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
def sitemap_xml(request: Request):
    host = (request.headers.get("host") or "").split(":")[0].strip().lower()
    if host not in MYCAST_HOSTS:
        return Response(status_code=404)
    urls = "".join(f"<url><loc>https://{host}{p}</loc></url>" for p in MYCAST_SITEMAP_PATHS)
    return Response('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    + urls + "</urlset>", media_type="application/xml")


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    mycast_redirect = _mycast_host_response(request)
    if mycast_redirect is not None:
        return mycast_redirect
    public_paths = {"/api/mycast/quiz", "/login", "/login/recover", "/auth/google", "/guest", "/health", "/mcp", "/favicon.ico", "/mycast", "/privacy", "/terms", "/robots.txt", "/sitemap.xml",
                    "/api/mycast/demo", "/api/mycast/account", "/api/mycast/voices", "/api/mycast/subtopics"}
    # #114 C-7: prefixes end with "/", so a future "/api/mycast/accounts-admin" is not public by accident.
    public_prefixes = ("/static/", "/.well-known/", "/media-source/", "/media-archive/", "/api/mycast/demo/", "/api/mycast/account/", "/api/mycast/voices/", "/mycast/u/", "/mycast/e/", "/mycast/demo/", "/api/mycast/calendar/", "/api/mybrief/public/")  # MyCast public beta: capped demo, listener accounts
    finisher_callback = re.fullmatch(r"/api/media-finisher/[0-9a-fA-F-]+/callback", request.url.path)
    # #114 C-2: the provider callback carries FACTORY_VIDEO_CALLBACK_TOKEN, not a session; the route checks it.
    media_job_callback = FACTORY_VIDEO_CALLBACK_TOKEN and re.fullmatch(r"/api/media-jobs/[0-9a-zA-Z_-]+/callback", request.url.path)
    local_booster_api=request.url.path.startswith("/api/local-booster/") and _local_booster_authorized(request)
    claude_worker_api=request.url.path.startswith("/api/claude-worker/") and _claude_worker_authorized(request)
    gemini_worker_api=request.url.path in GEMINI_WORKER_PATHS and _gemini_worker_authorized(request)
    operator_worker_api=request.url.path.startswith("/api/operator-worker/") and (_operator_worker_authorized(request) or gemini_worker_api)
    telegram_webhook_path=request.url.path=="/api/integrations/telegram/webhook"
    telegram_bridge_api=request.url.path.startswith("/api/factory/telegram/bridge/") and _telegram_bridge_authorized(request)
    relay_worker_api=request.url.path.startswith("/api/relay/worker/") and (_claude_worker_authorized(request) or gemini_worker_api)
    browser_agent_api=request.url.path.startswith("/api/factory/browser/agent/") and _browser_agent_authorized(request)
    relay_agent_api=request.url.path.startswith("/api/relay/agent/") and bool(agent_identity(request, forbidden=_agent_relay_forbidden_tokens()))
    owner_desk_worker_api=(request.url.path.startswith("/api/factory/owner-desk/worker/") or request.url.path.startswith("/api/factory/mycast/worker/") or request.url.path.startswith("/api/factory/voice/worker/") or request.url.path.startswith("/api/factory/gemini/worker/") or request.url.path.startswith("/api/factory/team-tasks/worker/") or request.url.path.startswith("/api/factory/browser/worker/") or request.url.path.startswith("/api/factory/surfer/worker/")) and _claude_worker_authorized(request)
    # #114 C-1: worker POSTs need the worker's own token; an owner browser session must not stand in for a runner.
    if (request.method.upper()=="POST" and request.url.path.startswith(("/api/claude-worker/","/api/operator-worker/","/api/local-booster/"))
            and not (claude_worker_api or operator_worker_api or local_booster_api)):
        return JSONResponse({"detail":"worker token required"},status_code=401)
    if (FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN and finisher_callback) or media_job_callback or local_booster_api or claude_worker_api or operator_worker_api or telegram_webhook_path or telegram_bridge_api or relay_worker_api or relay_agent_api or browser_agent_api or owner_desk_worker_api or request.url.path.startswith(public_prefixes) or request.url.path in public_paths or request.url.path=="/register":
        return await call_next(request)
    identity=request_identity(request)
    if not identity:
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail":"authentication required"},status_code=401)
        seg=request.url.path.strip("/").split("/",1)[0]
        lang=seg if seg in ("en","uk","ru") else "en"
        return RedirectResponse(f"/login?lang={lang}",status_code=303)
    if identity.get("role")=="viewer":
        if request.url.path in ("/api/local-booster/token","/api/local-booster/package.zip","/api/viewer-invite"):
            return JSONResponse({"detail":"viewer access is read-only"},status_code=403)
        if request.method.upper() not in ("GET","HEAD","OPTIONS") and request.url.path!="/logout":
            return JSONResponse({"detail":"viewer access is read-only"},status_code=403)
    scope=tenancy.identity_workspace(identity)
    if scope is not None:
        denied=_workspace_member_denial(request.method,request.url.path,scope)
        if denied:return denied
    token=tenancy.set_scope(scope)
    try:
        return await call_next(request)
    finally:
        tenancy.reset_scope(token)

def _workspace_member_denial(method, path, scope):
    """T-553: members only reach tenant-aware routes, and every id in the path must belong to their workspace."""
    if not tenancy.member_route_allowed(method,path):
        return JSONResponse({"detail":"workspace members cannot access operator surfaces"},status_code=403)
    resources=tenancy.path_resources(path)
    if resources:
        con=db()
        try:owners=[tenancy.resource_workspace(con,kind,rid) for kind,rid in resources]
        finally:con.close()
        # Foreign and missing resources look identical so ids from other workspaces are not confirmed.
        if any(owner!=scope for owner in owners):
            return JSONResponse({"detail":"Not found"},status_code=404)
    return None

@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, lang: str = "en"):
    lang=lang if lang in ("en","uk","ru") else "en"
    if request_is_authed(request):
        return RedirectResponse(f"/{lang}", status_code=303)
    copy={
      "en":{"sub":"Private AI content production control room","user":"Username","password":"Password","enter":"Enter FactoryOS","or":"or"},
      "uk":{"sub":"Приватний центр керування AI-виробництвом контенту","user":"Користувач","password":"Пароль","enter":"Увійти до FactoryOS","or":"або"},
      "ru":{"sub":"Приватный центр управления AI-производством контента","user":"Пользователь","password":"Пароль","enter":"Войти в FactoryOS","or":"или"},
    }[lang]
    google_html=""
    google_script=""
    if _google_login_enabled():
        google_html=f"""<div class='sep'><span>{copy["or"]}</span></div>
        <div id='g_id_onload' data-client_id='{FACTORY_GOOGLE_CLIENT_ID}' data-callback='factoryGoogleCredential'
             data-auto_prompt='false' data-context='signin'></div>
        <div class='g_id_signin' data-type='standard' data-shape='rectangular' data-theme='filled_black'
             data-text='signin_with' data-size='large' data-logo_alignment='left' data-width='354'></div>"""
        google_script=f"""<script src='https://accounts.google.com/gsi/client' async defer></script>
        <script>
        function factoryGoogleCredential(r){{
          var f=document.createElement('form');f.method='post';f.action='/auth/google';
          var c=document.createElement('input');c.type='hidden';c.name='credential';c.value=r.credential||'';f.appendChild(c);
          var l=document.createElement('input');l.type='hidden';l.name='lang';l.value='{lang}';f.appendChild(l);
          document.body.appendChild(f);f.submit();
        }}
        </script>"""
    return HTMLResponse(f"""<!doctype html><html lang='{lang}'><head><meta charset='utf-8'>
    <meta name='viewport' content='width=device-width,initial-scale=1'>
    <link rel='icon' href='/static/favicon.svg' type='image/svg+xml'><link rel='apple-touch-icon' href='/static/apple-touch-icon.png'>
    <title>Blackbox Lab — FactoryOS Login</title>
    <style>
    body{{margin:0;min-height:100vh;display:grid;place-items:center;background:radial-gradient(700px 420px at 50% 0,#163f6255,transparent 65%),#07101b;color:#fff;font:14px Inter,system-ui,Arial}}
    .box{{width:min(410px,90vw);background:linear-gradient(180deg,#0e1d2d,#0a1522);border:1px solid #284963;border-radius:20px;padding:28px;box-shadow:0 24px 80px #000a}}
    h1{{margin:0 0 6px;font-size:24px}}.sub{{color:#8ca0b4;margin-bottom:18px}}
    input{{width:100%;box-sizing:border-box;margin:7px 0;padding:12px;background:#07111d;color:#fff;border:1px solid #28465f;border-radius:10px}}
    button{{width:100%;margin-top:10px;padding:12px;border:0;border-radius:10px;background:linear-gradient(135deg,#1677ff,#0db7f5);color:#fff;font-weight:800;cursor:pointer}}
    .cube{{width:42px;height:42px;border:2px solid #16bdf6;transform:rotate(30deg);border-radius:7px;margin-bottom:18px;box-shadow:0 0 24px #16bdf655}}
    .langs{{display:flex;gap:5px;justify-content:flex-end;margin-bottom:14px}}.langs a{{font-size:10px;color:#8297ac;text-decoration:none;border:1px solid #294761;padding:5px 7px;border-radius:7px}}.langs a.active{{color:#fff;background:#153b63}}
    .sep{{display:flex;align-items:center;gap:10px;color:#6f8599;font-size:11px;margin:16px 0 12px}}.sep:before,.sep:after{{content:'';height:1px;background:#234158;flex:1}}
    .googleWrap{{display:flex;justify-content:center}}
    .forgot{{margin:12px 0 0;text-align:center}}.forgot a{{color:#5cc8ff;font-weight:600}}
    </style>{google_script}</head><body><div class='box'>
    <div class='langs'><a href='/login?lang=en' class='{"active" if lang=="en" else ""}'>EN</a><a href='/login?lang=uk' class='{"active" if lang=="uk" else ""}'>УКР</a><a href='/login?lang=ru' class='{"active" if lang=="ru" else ""}'>RU</a></div>
    <div class='cube'></div><h1>Blackbox Lab — FactoryOS</h1><div class='sub'>{copy["sub"]}</div>
    <form method='post' action='/login'>
      <input type='hidden' name='lang' value='{lang}'>
      <input name='username' placeholder='{copy["user"]}' autocomplete='username' required>
      <input name='password' type='password' placeholder='{copy["password"]}' autocomplete='current-password' required>
      <button type='submit'>{copy["enter"]}</button>
    </form>
    {login_recovery.link_html(lang)}
    <div class='googleWrap'>{google_html}</div>
    </div></body></html>""")

@app.post("/login")
def login(username: str = Form(...), password: str = Form(...), lang: str = Form("en")):
    lang=lang if lang in ("en","uk","ru") else "en"
    if not (hmac.compare_digest(username, FACTORY_USER) and hmac.compare_digest(password, FACTORY_PASSWORD)):
        msg={"en":"Invalid username or password","uk":"Невірний логін або пароль","ru":"Неверный логин или пароль"}[lang]
        retry={"en":"Try again","uk":"Спробувати ще раз","ru":"Попробовать снова"}[lang]
        return HTMLResponse(f"{msg}. <a href='/login?lang={lang}'>{retry}</a>", status_code=401)
    return _auth_cookie_response(f"/{lang}","owner","")

LOGIN_RECOVERY=login_recovery.LoginRecovery(base_url=lambda: FACTORY_PUBLIC_BASE_URL,state_path=DATA_DIR/"login_recovery.json")
login_recovery.install_login_recovery_routes(app,LOGIN_RECOVERY,sign_in=lambda lang: _auth_cookie_response(f"/{lang}","owner",""))

def _login_recovery_reply(message: dict, owner_chat: str) -> bool:
    """T-712: `/login` from the owner's private paired chat gets a one-time sign-in link, sent without a link preview."""
    if not login_recovery.enabled() or not login_recovery.owner_private_command(message,owner_chat):
        return False
    text=LOGIN_RECOVERY.message("ru")
    try:
        _telegram_api("sendMessage",{"chat_id":str(owner_chat),"text":text,"disable_web_page_preview":True})
    except Exception:
        LOGIN_RECOVERY.revoke(text)                      # undelivered: the link must not stay usable
    return True

@app.post("/auth/google")
def google_login(credential: str = Form(...), lang: str = Form("en")):
    lang=lang if lang in ("en","uk","ru") else "en"
    if not _google_login_enabled():
        raise HTTPException(503,"Google sign-in is not configured")
    try:
        claims=google_id_token.verify_oauth2_token(credential,google_requests.Request(),FACTORY_GOOGLE_CLIENT_ID)
    except Exception:
        msg={"en":"Google sign-in failed","uk":"Не вдалося увійти через Google","ru":"Не удалось войти через Google"}[lang]
        return HTMLResponse(f"{msg}. <a href='/login?lang={lang}'>←</a>",status_code=401)
    email=str(claims.get("email") or "").strip().lower()
    role=_google_identity_role(email)
    if not bool(claims.get("email_verified")) or not role:
        msg={"en":"This Google account is not allowed","uk":"Цей Google-акаунт не має доступу","ru":"У этого Google-аккаунта нет доступа"}[lang]
        return HTMLResponse(f"{msg}. <a href='/login?lang={lang}'>←</a>",status_code=403)
    print(json.dumps({"event":"GOOGLE_LOGIN","email":email,"role":role,"status":"success"}),flush=True)
    return _auth_cookie_response(f"/{lang}",role,email)

@app.get("/guest")
def guest_login(token: str="", lang: str="ru"):
    lang=lang if lang in ("en","uk","ru") else "ru"
    if not FACTORY_VIEWER_INVITE_TOKEN or not token or not hmac.compare_digest(token,FACTORY_VIEWER_INVITE_TOKEN):
        return HTMLResponse("Guest link is invalid or expired.",status_code=403)
    return _auth_cookie_response(f"/{lang}","viewer","guest")

@app.get("/api/viewer-invite")
def viewer_invite(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":
        raise HTTPException(403,"Owner access required")
    if not FACTORY_VIEWER_INVITE_TOKEN:
        raise HTTPException(503,"Viewer invite is not configured")
    token=urlparse.quote(FACTORY_VIEWER_INVITE_TOKEN,safe="")
    return {"url":f"{FACTORY_PUBLIC_BASE_URL}/guest?token={token}&lang=ru","role":"viewer","read_only":True}

@app.get("/api/factory/telegram/status")
def telegram_owner_status(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":
        raise HTTPException(403,"Owner access required")
    return _telegram_public_status()


@app.post("/api/factory/telegram/pairing/start")
def telegram_pairing_start(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":
        raise HTTPException(403,"Owner access required")
    if not FACTORY_TELEGRAM_BOT_TOKEN:
        raise HTTPException(503,"Telegram bot token is not configured")
    try:
        bot_result=(_telegram_api("getMe").get("result") or {})
        bot_username=str(bot_result.get("username") or "")
        code=secrets.token_hex(4).upper()
        state=_telegram_load_state()
        state["bot_username"]=bot_username
        state["pending"]={
            "code_hash":_telegram_pair_code_hash(code),
            "expires_at":time.time()+FACTORY_TELEGRAM_PAIR_TTL_SECONDS,
            "created_at":datetime.now(timezone.utc).isoformat(),
        }
        _telegram_save_state(state)
        _telegram_api("setWebhook",{
            "url":f"{FACTORY_PUBLIC_BASE_URL}/api/integrations/telegram/webhook",
            "secret_token":_telegram_webhook_secret(),
            "allowed_updates":["message","callback_query"],
            "drop_pending_updates":False,
        })
    except Exception as exc:
        raise HTTPException(502,"Telegram pairing could not be initialized") from exc
    return {
        **_telegram_public_status(),
        "pair_code":code,
        "command":f"/pair {code}",
        "deep_link":f"https://t.me/{bot_username}?start={code}" if bot_username else "",
        "expires_in_seconds":FACTORY_TELEGRAM_PAIR_TTL_SECONDS,
    }


@app.post("/api/factory/telegram/test")
def telegram_test_notification(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":
        raise HTTPException(403,"Owner access required")
    if not _telegram_public_status().get("paired"):
        raise HTTPException(409,"Telegram owner chat is not paired")
    try:
        _telegram_send("✅ FactoryOS Telegram channel test. Owner interrupt channel is online.")
    except Exception as exc:
        raise HTTPException(502,"Telegram test message failed") from exc
    return {"sent":True}


@app.post("/api/integrations/telegram/webhook")
async def telegram_webhook(request: Request):
    if not _telegram_webhook_authorized(request):
        raise HTTPException(403,"Invalid Telegram webhook secret")
    try:
        update=await request.json()
    except Exception:
        return {"ok":True}
    if not isinstance(update,dict):
        return {"ok":True}
    # #129 FactoryOS Team group: pairing (/group in the private chat), group commands and decision buttons.
    owner_chat=str(_telegram_load_state().get("chat_id") or "")
    g_msg=update.get("message") if isinstance(update.get("message"),dict) else {}
    g_chat=g_msg.get("chat") if isinstance(g_msg.get("chat"),dict) else {}
    g_cb=update.get("callback_query") if isinstance(update.get("callback_query"),dict) else {}
    if g_chat.get("type") in TELEGRAM_GROUP_TYPES or str(g_cb.get("data") or "").startswith("grp:"):
        result=GROUP_BRIDGE.handle_group(update,owner_chat,_telegram_send_markup)
        if g_cb.get("id"):
            try:_telegram_api("answerCallbackQuery",{"callback_query_id":g_cb["id"]})
            except Exception:pass
        return {"ok":True,**result}
    if _login_recovery_reply(g_msg,owner_chat):
        return {"ok":True,"action":"login_link"}
    if g_chat.get("type")=="private" and owner_chat and str(g_chat.get("id") or "")==owner_chat:
        reply=MORNING_BRIEF.handle_private(str(g_msg.get("text") or ""))
        if reply:
            _telegram_send_to(owner_chat,reply)
            return {"ok":True,"action":"morning_brief"}
        reply=GROUP_BRIDGE.handle_private(str(g_msg.get("text") or ""))
        if reply:
            _telegram_send_to(owner_chat,reply)
            return {"ok":True,"action":"group_pairing"}
    # #133: Telegram owner -> existing Claude subscription worker question queue.
    # This precedes the Relay command fallback (which would otherwise treat /ask as unknown).
    ask_msg=update.get("message") if isinstance(update.get("message"),dict) else {}
    ask_chat=ask_msg.get("chat") if isinstance(ask_msg.get("chat"),dict) else {}
    ask_text=str(ask_msg.get("text") or "").strip()
    ask_cmd=ask_text.split(maxsplit=1)[0].split("@",1)[0].lower() if ask_text.startswith("/") else ""
    ask_chat_id=str(ask_chat.get("id") or "").strip()
    if (ask_cmd=="/ask" and ask_chat.get("type")=="private"
            and ask_chat_id and ask_chat_id==str(_telegram_load_state().get("chat_id") or "")):
        question=ask_text.split(maxsplit=1)[1].strip() if len(ask_text.split(maxsplit=1))>1 else ""
        if not question:
            _telegram_send_to(ask_chat_id,"Использование: /ask Вопрос Claude")
            return {"ok":True,"action":"ask_help"}
        update_id=str(update.get("update_id") or "")
        source_key=("telegram-ask:"+update_id) if update_id else (
            "telegram-ask:"+ask_chat_id+":"+str(ask_msg.get("message_id") or ""))
        try:
            item=OWNER_QUESTIONS.create(TELEGRAM_TASK,"","",question,source_key=source_key)
        except OverflowError:
            _telegram_send_to(ask_chat_id,"Очередь вопросов заполнена. Попробуй позже.")
            return {"ok":True,"action":"ask_full"}
        except ValueError:
            _telegram_send_to(ask_chat_id,"Пустой или неподдерживаемый вопрос.")
            return {"ok":True,"action":"ask_invalid"}
        _telegram_send_to(ask_chat_id,"Принял вопрос "+item["id"]+". Claude ответит после того, как его воркер заберёт задачу.")
        return {"ok":True,"action":"ask_queued","question_id":item["id"]}
    # Owner voice → text (owner: «1 вариант», 2026-11-08): Gemini transcribes the paired owner's voice message,
    # the owner sees the text, and the Relay ticket gets that text instead of an empty "Голосовое сообщение".
    voice_msg=update.get("message") if isinstance(update.get("message"),dict) else {}
    voice_chat=voice_msg.get("chat") if isinstance(voice_msg.get("chat"),dict) else {}
    voice_att=_telegram_attachment(voice_msg) if voice_msg else {}
    if (voice_att and voice_att.get("kind") in ("voice","audio") and not str(voice_msg.get("text") or voice_msg.get("caption") or "").strip()
            and voice_chat.get("type")=="private" and str(voice_chat.get("id") or "")==str(_telegram_load_state().get("chat_id") or "")):
        transcript,reason=await asyncio.to_thread(VOICE_TRANSCRIBER,voice_att)
        chat=str(voice_chat.get("id"))
        if transcript:
            voice_msg["text"]=transcript
            _telegram_send_to(chat,"🎙 Распознал голосовое (Gemini):\n«"+transcript[:3500]+"»")
        else:
            # 2026-11-11 (R-0065): an empty voice ticket only made Claude run and answer "BLOCKED, no text".
            # No ticket without text: the owner resends it as text.
            _telegram_send_to(chat,"🎙 Не удалось распознать голосовое ("+VOICE_REASONS.get(reason,reason)+").\n"
                              "Задачу не создаю: без текста исполнителю нечего делать. Отправь её текстом или голосом ещё раз.")
            return {"ok":True,"action":"voice_not_transcribed","reason":reason}
    relay_result=relay_handle_telegram_update(update,RELAY_STORE,_telegram_load_state,_telegram_api,get_operator_lanes,lambda: relay_github_snapshot(GITHUB_REPO,_github_read_token()),RELAY_QUEUE,lane_board_provider=get_telegram_lane_board,operator_lanes_provider=get_telegram_operator_lanes,battle_controls=TELEGRAM_BATTLES,view_log=TELEGRAM_VIEWS)
    if relay_result and relay_result.get("handled"):
        return {"ok":True,**relay_result}
    message=update.get("message") or {}
    chat=message.get("chat") or {}
    if str(chat.get("type") or "")!="private":
        return {"ok":True}
    chat_id=str(chat.get("id") or "").strip()
    text=str(message.get("text") or "").strip()
    if not chat_id or not text:
        return {"ok":True}
    state=_telegram_load_state()
    pending=state.get("pending") if isinstance(state.get("pending"),dict) else {}
    parts=text.split(maxsplit=1)
    if parts and parts[0].lower() in ("/pair","/start"):
        supplied=parts[1].strip() if len(parts)>1 else ""
        expires_at=float(pending.get("expires_at") or 0)
        if not pending or expires_at<=time.time():
            try:
                _telegram_send_to(chat_id,"⏱ Pairing code expired. Start a new pairing session in FactoryOS.")
            except Exception:
                pass
            return {"ok":True,"paired":False}
        if not _telegram_pair_code_matches(supplied,str(pending.get("code_hash") or "")):
            return {"ok":True,"paired":False}
        sender=message.get("from") or {}
        state["chat_id"]=chat_id
        state["username"]=str(sender.get("username") or "")
        state["paired_at"]=datetime.now(timezone.utc).isoformat()
        state.pop("pending",None)
        state.setdefault("inbox",[])
        _telegram_save_state(state)
        try:
            _telegram_send_to(chat_id,"✅ FactoryOS paired. I will send HUMAN blockers and autopilot stop alerts here.")
        except Exception:
            pass
        return {"ok":True,"paired":True}
    if chat_id!=str(state.get("chat_id") or ""):
        return {"ok":True}
    if text.lower()=="/status":
        try:
            _telegram_send_to(chat_id,"🟢 FactoryOS Telegram bridge is online and paired.")
        except Exception:
            pass
        return {"ok":True}
    inbox=state.get("inbox") if isinstance(state.get("inbox"),list) else []
    update_id=int(update.get("update_id") or 0)
    inbox.append({
        "id":update_id,
        "text":text[:4000],
        "received_at":datetime.now(timezone.utc).isoformat(),
    })
    state["inbox"]=inbox[-100:]
    _telegram_save_state(state)
    return {"ok":True}


@app.post("/api/factory/telegram/bridge/notify")
def telegram_bridge_notify(payload: TelegramBridgeNotify, request: Request):
    if not _telegram_bridge_authorized(request):
        raise HTTPException(403,"Invalid bridge token")
    if not _telegram_public_status().get("paired"):
        raise HTTPException(409,"Telegram owner chat is not paired")
    prefix={"warning":"⚠️","blocked":"🙋","stopped":"⛔","done":"✅"}.get((payload.kind or "").strip().lower(),"")
    task=(payload.task_id or "").strip()
    body=" ".join(x for x in (prefix,task) if x).strip()
    body=(body+"\n" if body else "")+payload.text.strip()
    try:
        _telegram_send(body)
    except Exception as exc:
        raise HTTPException(502,"Telegram notification failed") from exc
    state=_telegram_load_state()
    inbox=state.get("inbox") if isinstance(state.get("inbox"),list) else []
    latest=max([int(x.get("id") or 0) for x in inbox if isinstance(x,dict)] or [0])
    return {"sent":True,"inbox_cursor":latest}


@app.get("/api/factory/telegram/bridge/inbox")
def telegram_bridge_inbox(request: Request, after: int=0):
    if not _telegram_bridge_authorized(request):
        raise HTTPException(403,"Invalid bridge token")
    state=_telegram_load_state()
    inbox=state.get("inbox") if isinstance(state.get("inbox"),list) else []
    messages=[x for x in inbox if isinstance(x,dict) and int(x.get("id") or 0)>int(after or 0)]
    latest=max([int(x.get("id") or 0) for x in inbox if isinstance(x,dict)] or [0])
    return {"messages":messages,"latest_id":latest}


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
]+web_surfer.TOOLS+agent_workspace.TOOLS+social_autopilot.MCP_TOOLS

@app.post("/mcp")
async def factory_mcp(request: Request):
    if not FACTORY_MCP_TOKEN:
        return JSONResponse({"jsonrpc":"2.0","id":None,"error":{"code":-32001,"message":"FactoryOS MCP connector is disabled until FACTORY_MCP_TOKEN is configured."}},status_code=503)
    mcp_lane=agent_workspace.lane_identity(request, forbidden=_mcp_lane_forbidden_tokens())
    if not (mcp_lane or _factory_mcp_authorized(request)):
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
            elif name in agent_workspace.TOOL_NAMES:
                data=agent_workspace.call_tool(AGENT_WORKSPACE,name,args,mcp_lane)
                if "error" in data:
                    return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":{"isError":True,**_factory_mcp_text(data["error"])}})
                result=_factory_mcp_text(data)
            elif name in web_surfer.TOOL_NAMES:
                result=_factory_mcp_text(await web_surfer.call_tool(name,args,store=BROWSER_TASKS,search=WEB_SEARCH,sessions=_surfer_session))
            elif name in social_autopilot.MCP_TOOL_NAMES:
                # T-702: agents read the plan and add drafts only; approval and publishing stay owner-only.
                result=_factory_mcp_text(social_autopilot.call_tool(SOCIAL_AUTOPILOT,name,args,mcp_lane or ""))
            elif name=="submit_design_review":
                created=_create_design_task_from_review(args)
                await broadcast({"type":"design_review_task","taskId":created["task_id"]})
                result=_factory_mcp_text(created)
            else:
                return JSONResponse({"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Unknown tool"}},status_code=404)
            return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":result})
        except Exception as exc:
            # #114 D-2: validation messages are meant for the caller; anything else is reported by type only.
            text=str(getattr(exc,"detail",None) or exc)[:300] if isinstance(exc,(ValueError,HTTPException)) else "internal error ("+type(exc).__name__+")"
            return JSONResponse({"jsonrpc":"2.0","id":req_id,"result":{"isError":True,"content":[{"type":"text","text":text}]}})
    return JSONResponse({"jsonrpc":"2.0","id":req_id,"error":{"code":-32601,"message":"Method not found"}},status_code=404)

@app.get("/mcp")
def factory_mcp_info(request: Request):
    if not FACTORY_MCP_TOKEN:
        return JSONResponse({"enabled":False,"detail":"Set FACTORY_MCP_TOKEN in Render to enable the Claude/remote MCP connector."},status_code=503)
    lane=agent_workspace.lane_identity(request, forbidden=_mcp_lane_forbidden_tokens())
    if not (lane or _factory_mcp_authorized(request)):
        return JSONResponse({"enabled":True,"detail":"Authentication required: Bearer token or ?key= token."},status_code=401)
    return {"enabled":True,"server":"Blackbox Lab FactoryOS","version":APP_VERSION,"lane":lane or None,"tools":[x["name"] for x in FACTORY_MCP_TOOLS]}

@app.get("/health")
def health(request: Request):
    """#114 A-1: anyone (Render's health check) gets liveness only; pilot/spend details need a signed-in session."""
    if not request_identity(request):
        return {"ok": True, "service": "factoryos", "version": APP_VERSION}
    return health_details()

def health_details():
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
        "durable_engine": durable_engine.status(),
    }

clients: set[WebSocket] = set()
member_clients: set[WebSocket] = set()
class _LeasedJobSet(set):
    """T-690: the in-process job registry also writes a job lease, so another process (an overlapping deploy) can
    see that this process is executing the job and must not reset it."""
    def add(self, job_id):
        super().add(job_id)
        _write_job_lease(job_id, True)
    def discard(self, job_id):
        super().discard(job_id)
        _write_job_lease(job_id, False)

def _write_job_lease(job_id, held):
    try:
        con=db()
        if held:
            con.execute("INSERT OR REPLACE INTO job_leases(job_id,process_id,created_at) VALUES(?,?,?)",(job_id,PROCESS_ID,ts()))
        else:
            con.execute("DELETE FROM job_leases WHERE job_id=? AND process_id=?",(job_id,PROCESS_ID))
        con.commit();con.close()
    except Exception as exc:
        print(json.dumps({"event":"JOB_LEASE_ERROR","error":str(exc)[:200]}),flush=True)

running_jobs: set[str] = _LeasedJobSet()
package_building: set[str] = set()
# T-690: runs this process started and has not finished yet (content pipeline, variant reruns, Content Packager,
# media QA …). A run of ours is orphaned only when it is not here, whatever registry its caller used.
LIVE_RUNS: set[str] = set()
selected_job_id: Optional[str] = None
selected_job_by_workspace: dict = {}
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

# Connection metadata is intentionally separate from provider secrets. The current
# deployment is one FactoryOS workspace, but bindings are stored with a workspace key so
# provider accounts can be detached/replaced now and full tenant scoping can be added later.
INTEGRATION_WORKSPACE_KEY = "default"
PORTABLE_INTEGRATIONS = {
    "Metricool": {"category":"publishing","auth_mode":"server_credentials","transport":"metricool"},
    "YouTube": {"category":"publishing","auth_mode":"via_metricool","transport":"metricool"},
    "Instagram": {"category":"publishing","auth_mode":"via_metricool","transport":"metricool"},
    "TikTok": {"category":"publishing","auth_mode":"via_metricool","transport":"metricool"},
    "HubSpot": {"category":"crm","auth_mode":"oauth","transport":"direct"},
    "LinkedIn": {"category":"publishing","auth_mode":"oauth","transport":"direct"},
    "OLX": {"category":"marketplace","auth_mode":"oauth","transport":"direct"},
}
CONNECTIONS = {
    "Metricool": {"state":"not_configured","detail":"Publishing workspace not configured"},
    "YouTube": {"state":"not_configured","detail":"Connect a publishing account"},
    "Instagram": {"state":"not_configured","detail":"Connect a publishing account"},
    "TikTok": {"state":"not_configured","detail":"Connect a publishing account"},
    "HubSpot": {"state":"not_configured","detail":"CRM / Growth · direct FactoryOS login not configured"},
    "LinkedIn": {"state":"not_configured","detail":"Text posts via the official LinkedIn API · connect on /static/linkedin/"},
    "OLX": {"state":"not_configured","detail":"Adverts via the official OLX Partner API · connect on /static/olx/index.html"},
    "vidIQ": {"state":"paused","detail":"Paused for now"},
    "LLM": {
        "state":"connected" if FACTORY_LLM_API_KEY else "demo",
        "detail":f"Live model: {FACTORY_LLM_MODEL}" if FACTORY_LLM_API_KEY else "Live adapter ready; set FACTORY_LLM_API_KEY",
    },
    "Voice": {"state":"not_configured","detail":"Provider not selected"},
    "Video": {"state":"not_configured","detail":"Provider not selected"},
}

def _integration_row(provider, workspace_key=None):
    workspace_key=workspace_key or tenancy.binding_workspace()
    con=db()
    row=con.execute("""SELECT * FROM integration_accounts
                       WHERE workspace_key=? AND provider=?""",(workspace_key,provider)).fetchone()
    con.close()
    if not row:return None
    item=dict(row)
    try:item["meta"]=json.loads(item.pop("meta_json") or "{}")
    except Exception:item["meta"]={}
    return item

def _integration_set(provider,state,account_label="",external_account_id="",auth_mode="",connected_via="",meta=None,
                     workspace_key=None):
    if provider not in PORTABLE_INTEGRATIONS:
        raise ValueError("Unsupported portable integration")
    workspace_key=workspace_key or tenancy.binding_workspace()
    now=ts(); existing=_integration_row(provider,workspace_key)
    connected_at=(existing or {}).get("connected_at")
    if state=="connected" and not connected_at:connected_at=now
    disconnected_at=now if state=="disconnected" else None
    con=db()
    con.execute("""INSERT INTO integration_accounts(
        workspace_key,provider,state,account_label,external_account_id,auth_mode,connected_via,
        meta_json,connected_at,disconnected_at,created_at,updated_at
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(workspace_key,provider) DO UPDATE SET
        state=excluded.state,account_label=excluded.account_label,
        external_account_id=excluded.external_account_id,auth_mode=excluded.auth_mode,
        connected_via=excluded.connected_via,meta_json=excluded.meta_json,
        connected_at=excluded.connected_at,disconnected_at=excluded.disconnected_at,
        updated_at=excluded.updated_at""",(
        workspace_key,provider,state,account_label,external_account_id,auth_mode,connected_via,
        json.dumps(meta or {},ensure_ascii=False),connected_at,disconnected_at,
        (existing or {}).get("created_at") or now,now
    ))
    con.commit();con.close()
    return _integration_row(provider,workspace_key)

def _integration_explicitly_disconnected(provider,workspace_key=None):
    row=_integration_row(provider,workspace_key)
    return bool(row and row.get("state")=="disconnected")

def _metricool_credentials_present():
    # T-553: the server Metricool secret is the default workspace's account, never another customer's.
    if tenancy.binding_workspace()!=tenancy.DEFAULT_WORKSPACE:return False
    return bool(FACTORY_METRICOOL_TOKEN and FACTORY_METRICOOL_USER_ID and FACTORY_METRICOOL_BLOG_ID)

def _portable_connection(provider):
    spec=PORTABLE_INTEGRATIONS[provider]
    row=_integration_row(provider)
    disconnected=bool(row and row.get("state")=="disconnected")
    if provider=="Metricool":
        ready=_metricool_credentials_present() and not disconnected
        state="connected" if ready else ("disconnected" if disconnected else "not_configured")
        detail=(row or {}).get("account_label") or ("Publisher credentials ready" if ready else
               ("Disconnected · content history kept" if disconnected else "Add workspace publisher credentials"))
    elif provider in ("YouTube","Instagram","TikTok"):
        ready=_metricool_credentials_present() and not _integration_explicitly_disconnected("Metricool") and not disconnected
        state="connected" if ready else ("disconnected" if disconnected else "not_configured")
        detail=(row or {}).get("account_label") or (f"Available via Metricool · replaceable" if ready else
               ("Disconnected · content history kept" if disconnected else "Connect a publishing account"))
    else:  # HubSpot direct runtime auth is intentionally not borrowed from ChatGPT.
        ready=bool(row and row.get("state")=="connected" and row.get("auth_mode")=="oauth")
        state="connected" if ready else ("disconnected" if disconnected else "not_configured")
        detail=(row or {}).get("account_label") or ("Disconnected · CRM history kept" if disconnected else
               "CRM / Growth · per-workspace OAuth slot ready")
    return {
        "state":state,"detail":detail,"portable":True,
        "category":spec["category"],"auth_mode":spec["auth_mode"],"transport":spec["transport"],
        "account_label":(row or {}).get("account_label") or "",
        "external_account_id":(row or {}).get("external_account_id") or "",
        "can_disconnect":state=="connected","can_switch":True,
        "secrets_exposed":False,
    }

def get_connection_registry():
    registry={k:dict(v) for k,v in CONNECTIONS.items()}
    for provider in PORTABLE_INTEGRATIONS:
        registry[provider]=_portable_connection(provider)
    tg=_telegram_public_status()
    registry["Telegram"]={
        "state":"connected" if tg.get("paired") else "not_configured",
        "detail":(
            ("Paired"+(f" · @{tg.get('username')}" if tg.get("username") else ""))
            if tg.get("paired") else
            ("Bot ready · pair owner chat" if tg.get("configured") else "Add bot token in Render")
        ),
        "configured":bool(tg.get("configured")),"paired":bool(tg.get("paired")),
        "bot_username":tg.get("bot_username") or "","username":tg.get("username") or "",
    }
    cw=get_claude_code_status()
    registry["AI Providers"]={
        "providers":[{**p,"gemini_key_configured":bool(FACTORY_GEMINI_API_KEY),
                      "gemini_check":{k:v for k,v in GEMINI_KEY_CHECK.items() if not k.startswith("_")} if FACTORY_GEMINI_API_KEY else {"status":"not_configured"}}
                     if p.get("id")=="google" else p
                     for p in ai_provider_catalog(FACTORY_LLM_MODEL,FACTORY_LLM_BASE_URL,bool(FACTORY_LLM_API_KEY))],
        "secrets_exposed":False,
    }
    registry["Workers"]={"items":worker_projection(cw),"secrets_exposed":False}
    registry["Claude Code Pro"]={
        "state":"connected" if cw.get("online") else "not_configured",
        "detail":(
            f"{cw.get('subscription') or 'Subscription'} runner online · {cw.get('auth_mode') or 'subscription'}"
            if cw.get("online") else
            "Connect a Claude Code runner authenticated with your Pro subscription"
        ),
        "online":bool(cw.get("online")),"auth_mode":cw.get("auth_mode") or "",
        "subscription":cw.get("subscription") or "Pro",
    }
    video_provider=_video_adapter_name()
    video_ready=_video_provider_configured(video_provider)
    video_cap=video_projection(video_provider,FACTORY_GEMINI_VIDEO_MODEL,video_ready)
    if _is_gemini_video_provider(video_provider):
        registry["Video"]={
            "state":"configured" if video_ready else "not_configured",
            "detail":(
                f"Google Gemini Omni · {FACTORY_GEMINI_VIDEO_MODEL} · credentials configured; video access not verified"
                if video_ready else
                "Google Gemini Omni · video generation · add FACTORY_GEMINI_API_KEY in the runtime secret store"
            ),
            "provider":video_provider,"model":FACTORY_GEMINI_VIDEO_MODEL,
            "aspect_ratio":FACTORY_GEMINI_VIDEO_ASPECT_RATIO,"resolution":FACTORY_GEMINI_VIDEO_RESOLUTION,
            "secrets_exposed":False,**video_cap,
        }
    elif video_provider:
        registry["Video"]={
            "state":"configured" if video_ready else "not_configured",
            "detail":f"{video_provider} · "+("credentials configured; access not verified" if video_ready else "provider endpoint not configured"),
            "provider":video_provider,"secrets_exposed":False,**video_cap,
        }
    return registry

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
    CREATE TABLE IF NOT EXISTS integration_accounts(
      workspace_key TEXT NOT NULL DEFAULT 'default',
      provider TEXT NOT NULL,
      state TEXT NOT NULL DEFAULT 'disconnected',
      account_label TEXT DEFAULT '',
      external_account_id TEXT DEFAULT '',
      auth_mode TEXT DEFAULT '',
      connected_via TEXT DEFAULT '',
      meta_json TEXT DEFAULT '{}',
      connected_at TEXT,
      disconnected_at TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      PRIMARY KEY(workspace_key, provider)
    );
    CREATE INDEX IF NOT EXISTS idx_integration_accounts_workspace
      ON integration_accounts(workspace_key, provider);
    CREATE TABLE IF NOT EXISTS job_workspaces(
      job_id TEXT PRIMARY KEY,
      workspace_key TEXT NOT NULL DEFAULT 'default',
      created_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_job_workspaces_workspace ON job_workspaces(workspace_key, job_id);
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
    CREATE TABLE IF NOT EXISTS agent_run_leases(
      run_id TEXT PRIMARY KEY,
      process_id TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS job_leases(
      job_id TEXT PRIMARY KEY,
      process_id TEXT NOT NULL,
      created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS process_heartbeats(
      process_id TEXT PRIMARY KEY,
      heartbeat_at TEXT NOT NULL
    );
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
BATTLE_STORE=BattleStore(db)
BATTLE_STORE.ensure_schema()

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
        # Owner 2026-11-14 (Actions budget): recover only a dispatch that was lost before GitHub saw it. A preflight that
        # already ran and failed or finished is left for a manual Start build; re-dispatching it on every Render restart
        # (= every deploy) burned 22 runs in two days.
        if (task.get("workflow_status") or "") or task.get("workflow_run_id"):
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
    workspace_key: Optional[str] = None  # owner/admin only; members always create in their own workspace

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
    target: Optional[dict] = None   # T-646: what the cycle aims at {brand, topic, platform, audience}

class FactoryCycleTarget(BaseModel):
    brand: str = ""
    topic: str = ""
    platform: str = ""
    audience: str = ""

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
    compute_target: str = "auto"
    confirm_external_cost: bool = False

class LocalBoosterHeartbeat(BaseModel):
    node_id: str = "local-pc"
    hostname: str = ""
    platform: str = ""
    cpu_count: int = 0
    gpu: str = ""
    worker_url: str = "http://127.0.0.1:10000"

class ClaudeWorkerHeartbeat(BaseModel):
    node_id: str = "claude-pro-runner"
    hostname: str = ""
    platform: str = ""
    claude_version: str = ""
    auth_mode: str = "subscription"
    subscription: str = "Pro"
    branch: str = ""
    repo: str = ""
    status: str = "idle"
    task_id: str = ""
    last_error: str = ""
    run_id: str = ""
    run_started_at: str = ""
    # T-596: secret-free systemd/OAuth report of the local runner supervisor (whitelisted on receipt).
    supervisor: dict = {}
    # T-536-B: stage/elapsed/branch/head/queue/CPU/memory; whitelisted by sanitize_telemetry on receipt.
    telemetry: dict = {}

class OperatorWorkerHeartbeat(BaseModel):
    operator_id: str
    node_id: str = "factoryos-worker"
    hostname: str = ""
    runtime: str = ""
    version: str = ""
    auth_mode: str = ""
    branch: str = ""
    repo: str = ""
    status: str = "idle"
    task_id: str = ""
    stage: str = ""
    queue_depth: int = 0
    tickets: list[dict] = []
    last_result: str = ""
    last_error: str = ""

class ClaudeWorkerTaskResult(BaseModel):
    task_id: str
    pinned_task_id: str
    result: str
    branch: str
    summary: str = ""
    need: str = ""
    checks: list[str] = []
    commit: str = ""
    commit_count: int = 0
    files: list[str] = []
    exit_code: Optional[int] = None
    timed_out: bool = False
    duration_seconds: float = 0
    started_at: Optional[float] = None
    max_turns: int = 0
    timeout_seconds: int = 0
    violations: list[str] = []
    pushed: bool = False
    deploy_credentials_scrubbed: bool = True

class LocalBoosterProgress(BaseModel):
    stage: str = "processing"
    percent: int = 1
    status: str = "processing"
    error: str = ""
    detail: dict = {}

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

_JOB_COLUMNS_SQL=f"jobs.*,{tenancy.JOB_WORKSPACE_SQL.format(col='jobs.id')} AS workspace_key"

def get_jobs():
    where,params=tenancy.sql_filter("jobs.id")
    con=db(); rows=con.execute(f"SELECT {_JOB_COLUMNS_SQL} FROM jobs WHERE 1=1{where} ORDER BY created_at DESC",params).fetchall(); con.close()
    return [dict(x) for x in rows]

def get_job(job_id):
    """Job in the active workspace scope; jobs of other workspaces look missing."""
    where,params=tenancy.sql_filter("jobs.id")
    con=db(); row=con.execute(f"SELECT {_JOB_COLUMNS_SQL} FROM jobs WHERE id=?{where}",[job_id,*params]).fetchone(); con.close()
    return dict(row) if row else None

async def run_in_job_workspace(job_id, coro):
    """Background job work runs under the job's own workspace identity, not the caller's."""
    with tenancy.workspace_scope(job_workspace_key(job_id)):
        return await coro

def assign_job_workspace(con, job_id, workspace_key=None):
    """Bind a new job to the explicit workspace, else the active scope (default for admin/system work)."""
    key=tenancy.normalize_workspace(workspace_key or tenancy.binding_workspace())
    con.execute("INSERT OR IGNORE INTO job_workspaces(job_id,workspace_key,created_at) VALUES(?,?,?)",(job_id,key,ts()))
    return key

def job_workspace_key(job_id):
    con=db()
    try:return tenancy.job_workspace(con,job_id)
    finally:con.close()


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
    now=ts()
    con.execute("""INSERT INTO agent_runs(id,job_id,agent,stage,status,started_at,model)
                   VALUES(?,?,?,?,?,?,?)""",
                (run_id,job_id,agent,stage,"running",now,model))
    # T-690: the run belongs to this process; another process may close it only after our heartbeat lease expires.
    con.execute("INSERT OR REPLACE INTO agent_run_leases(run_id,process_id,created_at) VALUES(?,?,?)",(run_id,PROCESS_ID,now))
    con.commit(); con.close()
    LIVE_RUNS.add(run_id)
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
    LIVE_RUNS.discard(run_id)
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

DISCOVERY_RANK_FIELDS=("breakout_score","vph","engagement_rate","views")

def _discovery_metric_value(item,key):
    value=item.get(key)
    if value is None:return (0,0.0)
    try:return (1,float(value))
    except (TypeError,ValueError):return (0,0.0)

def _discovery_rank_key(item):
    # This is deliberately a factual lexicographic priority, not a synthetic quality score.
    # A supplied metric always outranks a missing value for that metric; missing values are never imputed.
    parts=[1 if item.get("status")=="new" else 0]
    for key in DISCOVERY_RANK_FIELDS:
        present,value=_discovery_metric_value(item,key);parts.extend((present,value))
    parts.extend((str(item.get("discovered_at") or ""),str(item.get("id") or "")))
    return tuple(parts)

def _discovery_ranking_evidence(item):
    evidence={}
    for key in DISCOVERY_RANK_FIELDS:
        if item.get(key) is not None:evidence[key]=item.get(key)
    return {
        "metrics":evidence,
        "metric_count":len(evidence),
        "method":"factual_lexicographic",
        "priority":["status:new","breakout_score","vph","engagement_rate","views","discovered_at","id"],
        "missing_metrics":[key for key in DISCOVERY_RANK_FIELDS if item.get(key) is None],
    }

def get_discovery_candidates(limit=80,status=None):
    cap=max(1,min(300,int(limit)))
    con=db()
    if status:
        rows=con.execute("SELECT * FROM discovery_candidates WHERE status=? LIMIT 300",(status,)).fetchall()
    else:
        rows=con.execute("SELECT * FROM discovery_candidates LIMIT 300").fetchall()
    con.close()
    items=[_discovery_dict(x) for x in rows]
    items.sort(key=_discovery_rank_key,reverse=True)
    items=items[:cap]
    for rank,item in enumerate(items,1):
        item["rank_position"]=rank
        item["ranking_evidence"]=_discovery_ranking_evidence(item)
    counts={}
    for x in items:counts[x["status"]]=counts.get(x["status"],0)+1
    return {
      "summary":{"candidates":len(items),**counts},"candidates":items,
      "adapter":{"configured":bool(FACTORY_DISCOVERY_ENDPOINT),"mode":"webhook" if FACTORY_DISCOVERY_ENDPOINT else "manual_intake",
                 "topics":FACTORY_DISCOVERY_TOPICS,"interval_minutes":FACTORY_DISCOVERY_INTERVAL_MINUTES},
      "ranking":{"method":"factual_lexicographic","fields":list(DISCOVERY_RANK_FIELDS),
                 "note":"Provider-supplied breakout score is primary, then measured VPH, engagement and views. Missing metrics are never imputed; timestamp and ID only break factual ties."},
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
    # T-540: a repeated create-job call after handoff (status in_production) returns the existing job, not an error.
    if project.get("job_id"):
        return {"created":False,"job":get_job(project["job_id"]),"project":project}
    if project.get("status")!="ready":raise ValueError("Revideo analysis must be ready and pass the originality guard first")
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
      "configured":bool(_media_finisher_submit_endpoint()) or _local_booster_online(),
      "endpoint_configured":bool(_media_finisher_submit_endpoint()),
      "local_booster":{"online":_local_booster_online(),"ttl_seconds":FACTORY_LOCAL_BOOSTER_TTL_SECONDS,
                       "node":local_booster_runtime.get("node") or {},"active_job_id":local_booster_runtime.get("active_job_id") or ""},
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
def artifact_media(artifact_id:str,request:Request=None,download:bool=False):
    artifact=_artifact_media_row(artifact_id)
    if not artifact:raise HTTPException(404,"Artifact not found")
    path,archive_meta=_artifact_archive_file(artifact)
    # #114 B-2: only the owner's request may download and rewrite the artifact; viewers and members only read.
    may_archive=request is None or (request_identity(request) or {}).get("role")=="owner"
    if may_archive and not path and artifact.get("kind")=="video" and _is_ephemeral_finisher_url(artifact.get("url")):
        try:
            _archive_media_artifact(artifact_id)
            artifact=_artifact_media_row(artifact_id) or artifact
            path,archive_meta=_artifact_archive_file(artifact)
        except Exception as exc:
            if not str(artifact.get("url") or ""):
                raise HTTPException(410,"Media is no longer available ("+type(exc).__name__+")")  # #114 D-2
    if path and archive_meta:
        response=FileResponse(path,media_type=archive_meta.get("content_type") or artifact.get("mime_type") or "application/octet-stream",
                              filename=archive_meta.get("filename") or path.name,
                              content_disposition_type="attachment" if download else "inline")
        response.headers["X-Content-Type-Options"]="nosniff"
        return response
    source_url=str(artifact.get("url") or "").strip()
    if not source_url:
        # T-535: text/JSON/subtitle artifacts live in the DB; serve them through the same authenticated route.
        if artifact.get("kind") not in ARTIFACT_BINARY_KINDS and str(artifact.get("content") or ""):
            return _artifact_text_response(artifact,download)
        raise HTTPException(404,"Artifact has no media URL")
    if _is_ephemeral_finisher_url(source_url):
        raise HTTPException(410,"This temporary Media Finisher file expired before durable archival. Rerun the Media Finisher output to restore it.")
    if not _artifact_redirect_allowed(source_url):
        raise HTTPException(422,"Artifact media URL is not an http(s) or same-origin location")
    return RedirectResponse(source_url,status_code=307)

ARTIFACT_BINARY_KINDS={"video","audio","image"}
# Stored mime → (download extension, inline type). Inline subtitles/markdown/csv render as text/plain so the browser
# shows them instead of downloading; anything outside this table (text/html, SVG, …) is never served as active content.
ARTIFACT_TEXT_TYPES={
    "application/json":(".json","application/json"),
    "application/x-subrip":(".srt","text/plain"),
    "text/vtt":(".vtt","text/plain"),
    "text/markdown":(".md","text/plain"),
    "text/csv":(".csv","text/plain"),
    "text/plain":(".txt","text/plain"),
}

def _artifact_text_type(artifact):
    content=str(artifact.get("content") or "")
    mime=str(artifact.get("mime_type") or "").split(";")[0].strip().lower()
    meta=_decode_json(artifact.get("meta_json") or "{}",{})
    if mime not in ARTIFACT_TEXT_TYPES:
        if artifact.get("kind")=="json":mime="application/json"
        elif content.lstrip().startswith("WEBVTT"):mime="text/vtt"
        elif (meta or {}).get("component")=="srt" or artifact.get("kind")=="subtitle":mime="application/x-subrip"
        else:mime="text/plain"
    if mime=="application/json":
        try:json.loads(content)
        except ValueError:mime="text/plain"
    return mime

def _artifact_text_response(artifact,download=False):
    mime=_artifact_text_type(artifact)
    ext,inline_type=ARTIFACT_TEXT_TYPES[mime]
    stem=re.sub(r"[^A-Za-z0-9._-]+","-",str(artifact.get("title") or "artifact")).strip("-.")[:80] or "artifact"
    filename=stem+ext
    disposition=("attachment" if download else "inline")+f"; filename=\"{filename}\"; filename*=UTF-8''{urlparse.quote(filename)}"
    return Response(str(artifact.get("content") or "").encode("utf-8"),
                    media_type=f"{mime if download else inline_type}; charset=utf-8",
                    headers={"Content-Disposition":disposition,"X-Content-Type-Options":"nosniff",
                             "Content-Security-Policy":"default-src 'none'; sandbox","Cache-Control":"private, no-store"})

def _artifact_redirect_allowed(url):
    """Only real media locations: absolute http(s) or a same-origin path (not scheme-relative //host)."""
    if url.startswith("/"):return not url.startswith("//") and "\\" not in url
    try:parsed=urlparse.urlparse(url)
    except ValueError:return False
    return parsed.scheme in ("http","https") and bool(parsed.netloc)

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

def _durable_media_inventory(limit=200):
    con=db();rows=con.execute("""SELECT id,url,meta_json FROM artifacts
                                WHERE kind='video' AND (url LIKE '%/media-archive/%' OR meta_json LIKE '%"durable_media": true%')
                                ORDER BY created_at DESC LIMIT ?""",(int(limit),)).fetchall();con.close()
    checked=present=missing=0;bytes_total=0;archive_ids=[]
    for row in rows:
        item=dict(row);meta=_decode_json(item.get("meta_json") or "{}",{})
        archive_id=str(meta.get("archive_id") or "").strip()
        if not archive_id:
            match=re.search(r"/media-archive/([^?/#]+)",str(item.get("url") or ""))
            archive_id=match.group(1) if match else ""
        if not archive_id:continue
        checked+=1
        archive_meta=_media_archive_meta(archive_id)
        path=(MEDIA_ARCHIVE_DIR/str((archive_meta or {}).get("stored_name") or "")) if archive_meta else None
        expected=int((archive_meta or {}).get("bytes") or meta.get("archive_bytes") or 0)
        actual=int(path.stat().st_size) if path and path.exists() else 0
        ok=bool(archive_meta and path and path.exists() and actual>=1024 and (not expected or actual==expected))
        if ok:
            present+=1;bytes_total+=actual
        else:
            missing+=1
        if len(archive_ids)<5:archive_ids.append(archive_id[:12])
    return {"checked":checked,"present":present,"missing":missing,"bytes":bytes_total,"archive_ids":archive_ids}

MEDIA_FINISHER_EVIDENCE={
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
  "edit_decisions":("json","Edit decisions (reasons, confidence, undo)"),
  "qa_report":("analysis","Measured QA report"),
  "render_metrics":("analysis","Render time and resource use"),
}

def _persist_edit_evidence(edit_job_id,job_id,profile_id,profile_version,report,output_url=""):
    report=report if isinstance(report,dict) else {}
    now=ts();con=db()
    for key,(kind,title) in MEDIA_FINISHER_EVIDENCE.items():
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
    worker_qa=(report or {}).get("qa_report") or {}
    qa={
      "decision":"human_review_required",
      "worker_qa_overall":worker_qa.get("overall") if isinstance(worker_qa,dict) else None,
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
    # T-612: once the durable engine is launched, one DBOS workflow owns submit → wait for callback → poll for this
    # edit job, and a repeated call while it runs is a no-op. Engine off or unavailable → the legacy thread below.
    if durable_engine.launched():
        try:
            workflow_id,created=durable_finisher.start(edit_job_id)
        except Exception as exc:
            workflow_id,created=None,False
            print(json.dumps({"event":"DBOS_MEDIA_FINISHER_START_ERROR","edit_job_id":edit_job_id,"error":str(exc)[:300]}),flush=True)
        if workflow_id:
            if created:
                item=get_edit_job(edit_job_id)
                if item:event(item["production_job_id"],f"AI Media Finisher durable workflow started: {edit_job_id[:8]} · survives restarts and deploys")
            return
    threading.Thread(target=_submit_media_finisher_background,args=(edit_job_id,),daemon=True,name=f"finisher-submit-{edit_job_id[:8]}").start()

def _durable_finisher_state(edit_job_id,needs_submit=False):
    item=get_edit_job(edit_job_id)
    if not item:return {"status":"missing","provider_job_id":"","needs_submit":False}
    status=str(item.get("status") or "")
    return {"status":status,"provider_job_id":str(item.get("provider_job_id") or ""),
            "needs_submit":bool(needs_submit) and status not in ("ready","failed")}

def _durable_finisher_submit(edit_job_id):
    """DBOS step body (T-612): the legacy submit routine, safe to repeat after a crash. It returns early once
    provider_job_id is recorded, and the worker treats edit_job_id as its idempotency key (POST /jobs)."""
    _submit_media_finisher_background(edit_job_id)
    return _durable_finisher_state(edit_job_id)

def _durable_finisher_poll(edit_job_id):
    """DBOS step body (T-612): read the outcome a callback may already have written, otherwise ask the worker.
    needs_submit=True when the worker has no job for us (its state was lost → 404, or the submit never landed)."""
    item=get_edit_job(edit_job_id)
    if not item or item.get("status") in ("ready","failed"):return _durable_finisher_state(edit_job_id)
    if not str(item.get("provider_job_id") or "").strip():
        return _durable_finisher_state(edit_job_id,needs_submit=edit_job_id not in _media_finisher_submit_active)
    refreshed=refresh_edit_job(edit_job_id,resubmit=False)
    return _durable_finisher_state(edit_job_id,needs_submit=not str(refreshed.get("provider_job_id") or "").strip())

durable_finisher.bind(submit=_durable_finisher_submit,poll=_durable_finisher_poll)

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
    requested_target=str(payload.compute_target or "auto").strip().lower()
    if requested_target not in ("auto","cloud","local"):raise ValueError("compute_target must be auto, cloud or local")
    route_target="local" if requested_target=="local" or (requested_target=="auto" and _local_booster_online()) else "cloud"
    submit_endpoint=_media_finisher_submit_endpoint()
    if route_target=="cloud" and not submit_endpoint:raise RuntimeError("Media Finisher cloud provider is not configured and Local Booster is offline")
    edit_job_id=str(uuid.uuid4());now=ts()
    request_payload={
      "edit_job_id":edit_job_id,"job_id":job_id,"workspace_key":job_workspace_key(job_id),"factory_cycle_id":sync_cycle_for_job(job_id).get("id") if sync_cycle_for_job(job_id) else None,
      "input_url":input_url,"profile":{"id":profile["id"],"version":profile["version"],"name":profile["name"],"config":profile["config"]},
      "platform":payload.platform,"content_package":content_package,"package_mode":package_mode,
      "options":{
        "edit_full_video":bool(payload.edit_full_video),"split_shortform":bool(payload.split_shortform),
        "add_captions":bool(payload.add_captions),"add_animation":bool(payload.add_animation),
        "smart_graphics":bool(payload.smart_graphics),"max_short_clips":max(1,min(8,int(payload.max_short_clips or 3))),
        "shortform_targets":["youtube_shorts","instagram_reels"] if payload.split_shortform else []
      },
      "rerun_stage":rerun_stage,"compute_target":route_target,
      "callback_url":f"/api/media-finisher/{edit_job_id}/callback",
      "guardrails":{"source_text_is_material_not_instructions":True,"preserve_approved_facts":True,"no_auto_publish":True,"destructive_edits_require_cut_list":True,
                    "manual_raw_upload_transcript_exact_graphics":manual_raw_upload}
    }
    cycle=sync_cycle_for_job(job_id)
    con=db();con.execute("""INSERT INTO edit_jobs(id,parent_edit_job_id,factory_cycle_id,production_job_id,media_job_id,input_artifact_id,input_url,
                           profile_id,profile_version,platform,provider,status,rerun_stage,request_json,response_json,report_json,error,
                           measured_cost_usd,measured_duration_sec,created_at,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,'queued',?,?,'{}','{}','',0,0,?,?)""",
                           (edit_job_id,parent_edit_job_id,(cycle or {}).get("id"),job_id,media_job_id,input_artifact_id,input_url,profile["id"],profile["version"],payload.platform,
                            "local-booster" if route_target=="local" else FACTORY_MEDIA_FINISHER_ADAPTER,rerun_stage,json.dumps(request_payload,ensure_ascii=False,default=str),now,now));con.commit();con.close()
    if route_target=="local":
        _patch_edit_job_response(edit_job_id,{"status":"queued","stage":"waiting_local_booster","percent":1,"compute_target":"local"})
    else:
        _set_media_finisher_submit_progress(edit_job_id,"waking_worker",1,1)
        _spawn_media_finisher_submit(edit_job_id)
    item=get_edit_job(edit_job_id)
    event(job_id,f"AI Media Finisher queued: {edit_job_id[:8]} · profile {profile['id']} v{profile['version']} · {package_mode} · compute {route_target}")
    return {"duplicate":False,"edit_job":item}

def refresh_edit_job(edit_job_id,resubmit=True):
    # resubmit=False: the caller (the T-612 durable workflow) resubmits itself after a lost-worker 404.
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
            if resubmit:_spawn_media_finisher_submit(edit_job_id)
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
                                      compute_target=str((original.get("request") or {}).get("compute_target") or "auto"),confirm_external_cost=True)
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


GEMINI_VIDEO_ADAPTERS={"gemini","gemini-omni","gemini-omni-flash","google-gemini","google-gemini-omni"}

def _video_adapter_name():
    return str(FACTORY_MEDIA_ADAPTERS.get("video") or "").strip().lower()

def _is_gemini_video_provider(provider=None):
    return str(provider if provider is not None else _video_adapter_name()).strip().lower() in GEMINI_VIDEO_ADAPTERS

def _video_provider_configured(provider=None):
    provider=str(provider if provider is not None else _video_adapter_name()).strip().lower()
    if _is_gemini_video_provider(provider):
        return bool(FACTORY_GEMINI_API_KEY)
    return bool(provider and FACTORY_VIDEO_ENDPOINT)

def _gemini_api_json(path,method="GET",payload=None,timeout=300):
    if not FACTORY_GEMINI_API_KEY:
        raise RuntimeError("Gemini API key is not configured")
    path=str(path or "").strip()
    if not path.startswith("/"):path="/"+path
    url="https://generativelanguage.googleapis.com/v1beta"+path
    headers={"Accept":"application/json","User-Agent":f"FactoryOS/{APP_VERSION}","x-goog-api-key":FACTORY_GEMINI_API_KEY}
    data=None
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8");headers["Content-Type"]="application/json"
    req=urlrequest.Request(url,data=data,headers=headers,method=method)
    try:
        with urlrequest.urlopen(req,timeout=timeout) as response:
            raw=response.read().decode("utf-8","replace")
            return json.loads(raw or "{}")
    except urlerror.HTTPError as exc:
        try:detail=exc.read().decode("utf-8","replace")
        except Exception:detail=str(exc)
        raise RuntimeError(f"Gemini API HTTP {getattr(exc,'code','error')}: {detail[:700]}") from exc
    except urlerror.URLError as exc:
        raise RuntimeError(f"Gemini API network error: {exc}") from exc

def _gemini_video_uri(result):
    if not isinstance(result,dict):return ""
    direct=result.get("output_video") or result.get("outputVideo")
    if isinstance(direct,dict) and str(direct.get("uri") or "").strip():
        return str(direct.get("uri")).strip()
    stack=[result.get("steps") or []]
    while stack:
        current=stack.pop(0)
        if isinstance(current,dict):
            if str(current.get("type") or "").lower()=="video" and str(current.get("uri") or "").strip():
                return str(current.get("uri")).strip()
            stack.extend(current.values())
        elif isinstance(current,list):
            stack.extend(current)
    return ""

def _gemini_video_file_id(value):
    raw=str(value or "").strip()
    match=re.search(r"/files/([^/:?]+)",raw)
    if match:return match.group(1)
    raw=raw.replace("files/","").split(":",1)[0].split("?",1)[0].strip("/")
    return raw if re.fullmatch(r"[A-Za-z0-9._-]+",raw or "") else ""

def _gemini_video_prompt(package):
    package=package if isinstance(package,dict) else {}
    title=str(package.get("title") or "").strip()
    hook=str(package.get("hook") or "").strip()
    script=str(package.get("final_script") or package.get("voice_over") or "").strip()
    brief=package.get("media_brief")
    brief=json.dumps(brief,ensure_ascii=False) if isinstance(brief,(dict,list)) else str(brief or "").strip()
    scene_lines=[]
    for index,scene in enumerate((package.get("scenes") or [])[:8],1):
        if isinstance(scene,dict):
            visual=str(scene.get("visual") or scene.get("visual_prompt") or scene.get("description") or "").strip()
            narration=str(scene.get("narration") or "").strip()
            line=" · ".join(x for x in (visual,narration) if x)
        else:
            line=str(scene or "").strip()
        if line:scene_lines.append(f"{index}. {line[:700]}")
    parts=[
        "Create one original short-form social video asset for FactoryOS.",
        f"Format: {FACTORY_GEMINI_VIDEO_ASPECT_RATIO} portrait, {FACTORY_GEMINI_VIDEO_RESOLUTION}.",
        "Use cinematic, coherent motion and clear visual storytelling. Do not copy or reuse source footage, creator identity, likeness, voice, logos, or watermarks.",
        "No spoken dialogue and no baked-in subtitles unless the visual itself requires a small natural sign; FactoryOS adds narration and captions later.",
    ]
    if title:parts.append("Working title: "+title[:500])
    if hook:parts.append("Hook intent: "+hook[:700])
    if brief:parts.append("Visual brief: "+brief[:2400])
    if scene_lines:parts.append("Scene guidance:\n"+"\n".join(scene_lines))
    if script:parts.append("Narrative context (visualize, do not render as captions): "+script[:2800])
    return "\n\n".join(parts)[:12000]

def _gemini_submit_video(package):
    aspect=FACTORY_GEMINI_VIDEO_ASPECT_RATIO if FACTORY_GEMINI_VIDEO_ASPECT_RATIO in ("9:16","16:9") else "9:16"
    resolution=FACTORY_GEMINI_VIDEO_RESOLUTION if FACTORY_GEMINI_VIDEO_RESOLUTION in ("360p","720p","1080p","4k") else "720p"
    request_payload={
        "model":FACTORY_GEMINI_VIDEO_MODEL,
        "input":_gemini_video_prompt(package),
        "response_format":{"type":"video","delivery":"uri","aspect_ratio":aspect,"resolution":resolution},
    }
    result=_gemini_api_json("/interactions","POST",request_payload,timeout=300)
    uri=_gemini_video_uri(result)
    file_id=_gemini_video_file_id(uri)
    if not uri or not file_id:
        raise RuntimeError("Gemini returned no downloadable video URI")
    return {
        "id":file_id,"job_id":file_id,"status":"submitted",
        "interaction_id":str(result.get("id") or ""),"file_uri":uri,
        "model":FACTORY_GEMINI_VIDEO_MODEL,"aspect_ratio":aspect,"resolution":resolution,
        "provider_response":result,
    }

def _gemini_archive_video(media_job_id,file_id,file_info=None):
    archive_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:gemini-video:{media_job_id}:{file_id}"))
    stored_name=archive_id+".mp4";dest=MEDIA_ARCHIVE_DIR/stored_name
    existing=_media_archive_meta(archive_id)
    if not (existing and dest.exists()):
        url=f"https://generativelanguage.googleapis.com/v1beta/files/{urlparse.quote(file_id,safe='')}:download?alt=media"
        req=urlrequest.Request(url,headers={
            "Accept":"video/mp4","User-Agent":f"FactoryOS/{APP_VERSION}","x-goog-api-key":FACTORY_GEMINI_API_KEY
        },method="GET")
        total=0;digest=hashlib.sha256();content_type="video/mp4"
        try:
            with urlrequest.urlopen(req,timeout=300) as response,dest.open("wb") as fh:
                content_type=str(response.headers.get("Content-Type") or "video/mp4").split(";")[0].strip() or "video/mp4"
                length=str(response.headers.get("Content-Length") or "").strip()
                if length and int(length)>FACTORY_MEDIA_ARCHIVE_MAX_BYTES:
                    raise RuntimeError(f"Gemini video exceeds archive limit of {FACTORY_MEDIA_ARCHIVE_MAX_BYTES//(1024*1024)} MB")
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>FACTORY_MEDIA_ARCHIVE_MAX_BYTES:
                        raise RuntimeError(f"Gemini video exceeds archive limit of {FACTORY_MEDIA_ARCHIVE_MAX_BYTES//(1024*1024)} MB")
                    fh.write(chunk);digest.update(chunk)
        except Exception:
            if dest.exists():dest.unlink()
            raise
        if total<1024:
            if dest.exists():dest.unlink()
            raise RuntimeError("Gemini video download was empty or too small")
        existing={
            "archive_id":archive_id,"media_job_id":media_job_id,"provider":"gemini-omni",
            "google_file_id":file_id,"stored_name":stored_name,"filename":f"gemini-{media_job_id[:8]}.mp4",
            "content_type":content_type,"bytes":total,"sha256":digest.hexdigest(),
            "model":FACTORY_GEMINI_VIDEO_MODEL,"created_at":ts(),
            "file_state":str((file_info or {}).get("state") or "ACTIVE"),
        }
        (MEDIA_ARCHIVE_DIR/f"{archive_id}.json").write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding="utf-8")
    token=_media_archive_signature(archive_id)
    return f"{FACTORY_PUBLIC_BASE_URL}/media-archive/{archive_id}?token={urlparse.quote(token,safe='')}"

def _refresh_gemini_media_job(item):
    file_id=_gemini_video_file_id(item.get("provider_job_id"))
    if not file_id:raise RuntimeError("Gemini file id is not available yet")
    info=_gemini_api_json(f"/files/{urlparse.quote(file_id,safe='')}","GET",None,timeout=60)
    state=str(info.get("state") or "").strip().upper()
    if state=="FAILED":
        detail=info.get("error") or info.get("status") or "Gemini generation failed"
        return _finalize_media_job(item["id"],"failed",error=str(detail)[:900],response=info,provider_job_id=file_id)
    if state!="ACTIVE":
        return _finalize_media_job(item["id"],"processing",response=info,provider_job_id=file_id)
    media_url=_gemini_archive_video(item["id"],file_id,info)
    return _finalize_media_job(item["id"],"ready",media_url=media_url,response=info,provider_job_id=file_id)

def get_revideo_adapter_registry():
    provider=_video_adapter_name()
    gemini=_is_gemini_video_provider(provider)
    return {
        "transcript":{"selected":FACTORY_TRANSCRIPT_ADAPTER,"configured":bool(FACTORY_TRANSCRIPT_ENDPOINT),
                      "manual_supported":True,"endpoint_configured":bool(FACTORY_TRANSCRIPT_ENDPOINT)},
        "video":{"selected":provider or None,"configured":_video_provider_configured(provider),
                 "endpoint_configured":bool(FACTORY_VIDEO_ENDPOINT) if not gemini else False,
                 "api_key_configured":bool(FACTORY_GEMINI_API_KEY) if gemini else None,
                 "model":FACTORY_GEMINI_VIDEO_MODEL if gemini else None,
                 "aspect_ratio":FACTORY_GEMINI_VIDEO_ASPECT_RATIO if gemini else None,
                 "resolution":FACTORY_GEMINI_VIDEO_RESOLUTION if gemini else None,
                 "execution":"gemini_interactions_uri" if gemini else "webhook_provider",
                 "async_jobs":True,
                 "status_endpoint_configured":True if gemini and FACTORY_GEMINI_API_KEY else bool(FACTORY_VIDEO_STATUS_ENDPOINT)},
        "note":"Provider credentials come from environment/runtime secrets and are never exposed in this response."
    }

def render_revideo_media(project_id):
    project=get_revideo_project(project_id)
    if not project:raise ValueError("Revideo project not found")
    if not project.get("job_id"):raise ValueError("Create a production job first")
    package=get_content_package(project["job_id"]).get("package_record")
    if not package or package.get("status")!="ready":raise ValueError("A fresh Content Package is required before video generation")
    provider=_video_adapter_name()
    if not _video_provider_configured(provider):raise RuntimeError("Video provider is not configured")
    payload={"project_id":project_id,"job_id":project["job_id"],"source_url":project["source_url"],
             "content_package":package.get("package") or {},
             "guardrails":{"do_not_reuse_source_media":True,"do_not_imitate_creator_identity_or_voice":True}}
    media_job_id=str(uuid.uuid4());now=ts();provider=provider or "webhook"
    con=db();con.execute("""INSERT INTO media_jobs(
        id,revideo_project_id,job_id,provider,provider_job_id,status,media_url,error,
        request_json,response_json,created_at,updated_at,completed_at
    ) VALUES(?,?,?,?,?,'queued','','',?,'{}',?,?,NULL)""",
        (media_job_id,project_id,project["job_id"],provider,"",json.dumps(payload,ensure_ascii=False),now,now))
    con.commit();con.close()
    try:
        if _is_gemini_video_provider(provider):
            result=_gemini_submit_video(package.get("package") or {})
        else:
            result=_external_json(FACTORY_VIDEO_ENDPOINT,"POST",payload,FACTORY_VIDEO_TOKEN)
    except Exception as exc:
        _finalize_media_job(media_job_id,"failed",error=str(exc),response={"exception":str(exc),"provider":provider})
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
    if _is_gemini_video_provider(item.get("provider")):
        return _refresh_gemini_media_job(item)
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
        "video":{"input":["scene","audio","captions","assets"],"output":["video"],"status":"configured" if _video_provider_configured() else "not_configured"},
        "stock":{"input":["query","duration","orientation"],"output":["stock_asset"],"status":"configured" if FACTORY_MEDIA_ADAPTERS["stock"] else "not_configured"},
        "manual":{"input":["uploaded_media"],"output":["media_asset"],"status":"ready"},
    }
    out=[]
    for kind,spec in contracts.items():
        provider="manual" if kind=="manual" else FACTORY_MEDIA_ADAPTERS.get(kind,"")
        out.append({
            "kind":kind,"provider":provider or None,"configured":spec["status"] in ("configured","ready"),
            "status":spec["status"],"contract":{"input":spec["input"],"output":spec["output"]},
            "execution":(("gemini_interactions_uri" if _is_gemini_video_provider(provider) else "webhook_provider") if kind=="video" and _video_provider_configured(provider) else "adapter_interface_only") if kind!="manual" else "manual_asset_path",
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
        """SELECT id,agent,title,content,url,created_at,meta_json FROM artifacts
           WHERE job_id=? AND agent IN ('Researcher','Tech Verifier')
           ORDER BY created_at DESC LIMIT 8""",(job_id,)
    ).fetchall()]
    con.close()
    urls=[];refs=[];notes=[]
    for row in rows:
        refs.append({"artifact_id":row["id"],"agent":row["agent"],"title":row["title"],"created_at":row["created_at"]})
        candidates=[]
        if row.get("url"):candidates.append(row["url"])
        # T-540: Revideo source-structure artifacts keep the public source URL in meta, not in the JSON body.
        meta_source=str(_decode_json(row.get("meta_json") or "{}",{}).get("source_url") or "").strip()
        if _valid_public_url(meta_source):candidates.append(meta_source)
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

WORKER_REPORT_ARTIFACT_LIMIT=5
# Run modes whose persisted zero token/cost values are factual (no paid call, or a measured live call).
WORKER_REPORT_MEASURED_MODES={"demo","live_llm","rules-engine","deterministic"}

def _worker_report(row,content,run,inputs,meta,artifact_count,artifact_items):
    """Answer input / action / status / output / artifacts / duration / tokens / cost for one worker.

    None means "unavailable": never substitute a default (e.g. the 0 DB default) for an unmeasured value.
    """
    run=run or None
    run_meta=(run or {}).get("meta") or {}
    finished=bool(run and run.get("finished_at"))
    mode=run_meta.get("mode") or meta.get("mode")
    tokens_in=int((run or {}).get("input_tokens") or 0);tokens_out=int((run or {}).get("output_tokens") or 0)
    cost=float((run or {}).get("cost_usd") or 0)
    measured=finished and run.get("status")=="completed" and mode in WORKER_REPORT_MEASURED_MODES
    report={
        "input":({"count":len(inputs),"sources":[{"agent":x.get("source_agent"),"artifact_id":x.get("artifact_id"),"kind":x.get("kind"),"title":x.get("title")} for x in inputs]} if run else None),
        "action":({"stage":run.get("stage"),"mode":mode,"model":run.get("model") or meta.get("model"),"note":run_meta.get("note")} if run else None),
        "status":(run.get("status") if run else "artifact_only"),
        "error":(run.get("error") if run else None),
        "output":{"kind":row.get("kind"),"title":row.get("title"),"preview":content[:240],"url":row.get("url"),"mime_type":row.get("mime_type")},
        "artifacts":{"count":int(artifact_count or 0),"items":list(artifact_items or [])},
        "duration_ms":(int(run.get("duration_ms") or 0) if finished else None),
        "tokens":({"input":tokens_in,"output":tokens_out,"total":tokens_in+tokens_out} if finished and (tokens_in or tokens_out or measured) else None),
        "cost_usd":(round(cost,6) if finished and (cost>0 or measured) else None),
    }
    report["unavailable"]=[k for k in ("input","action","duration_ms","tokens","cost_usd") if report[k] is None]
    return report

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
    latest={};items={}
    for row in rows:
        if len(items.setdefault(row["agent"],[]))<WORKER_REPORT_ARTIFACT_LIMIT:
            items[row["agent"]].append({k:row.get(k) for k in ("id","kind","title","url","mime_type","created_at")})
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
            "report":_worker_report(row,content,run,inputs,meta,counts.get(agent,0),items.get(agent,[])),
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

# T-560-E — Browser Runner observability. Runs are recorded in trusted server code only
# (no HTTP ingest), as redacted views built by browser_runner.observability.
BROWSER_RUNNER_AGENT="Browser Runner"
BROWSER_RUN_KIND="browser_run"

def record_browser_run(job_id, plan, result, checkpoint=None, started_at=None, finished_at=None):
    from browser_runner.observability import build_run_view, run_view_title
    view=build_run_view(plan,result,checkpoint,started_at=started_at,finished_at=finished_at)
    meta={"component":BROWSER_RUN_KIND,"mode":"deterministic" if view["executor"]=="mock" else view["executor"],
          "plan_id":view["plan"]["plan_id"],"status":view["status"]}
    artifact_id=save_artifact(BROWSER_RUNNER_AGENT,BROWSER_RUN_KIND,run_view_title(view),view,
                              job_id=job_id,mime_type="application/json",meta=meta)
    return {"id":artifact_id,"view":view}

def _browser_run_row(row):
    from browser_runner.core import redact
    view=_decode_json(row.get("content") or "",None)
    if not isinstance(view,dict) or "plan" not in view:
        return None
    return {"id":row["id"],"job_id":row.get("job_id"),"created_at":row.get("created_at"),"view":redact(view)}

def get_job_browser_runs(job_id, limit=10):
    if not job_id:
        return []
    con=db()
    rows=[dict(x) for x in con.execute(
        "SELECT id,job_id,content,created_at FROM artifacts WHERE job_id=? AND agent=? AND kind=? ORDER BY created_at DESC LIMIT ?",
        (job_id,BROWSER_RUNNER_AGENT,BROWSER_RUN_KIND,max(1,min(int(limit),50)))).fetchall()]
    con.close()
    return [x for x in map(_browser_run_row,rows) if x]

def get_browser_run(artifact_id):
    con=db()
    row=con.execute("SELECT id,job_id,content,created_at FROM artifacts WHERE id=? AND agent=? AND kind=?",
                    (artifact_id,BROWSER_RUNNER_AGENT,BROWSER_RUN_KIND)).fetchone()
    con.close()
    return _browser_run_row(dict(row)) if row else None

# T-532 — live pipeline handoff trace. Ordered read model of persisted runs only:
# source artifact -> worker run -> output artifacts -> downstream worker runs.
FLOW_BLOCKED_CATEGORIES={"dependency","budget"}

def _flow_run_state(status, error):
    raw=(status or "").lower()
    if raw=="running":
        return "running"
    if raw=="completed":
        return "done"
    if raw=="failed":
        # A gate (missing upstream / quality gate / budget guard) stopped the run: blocked, not a worker failure.
        return "blocked" if classify_agent_error(error)["category"] in FLOW_BLOCKED_CATEGORIES else "failed"
    return "queued" if raw=="queued" else "unknown"

def get_job_flow(job_id, limit=40):
    empty={"job_id":job_id,"hops":[],"edges":[],"sources":[],"counts":{"running":0,"done":0,"blocked":0,"failed":0,"queued":0,"unknown":0},"live":False,"truncated":False}
    if not job_id:
        return empty
    con=db()
    runs=[dict(x) for x in con.execute(
        """SELECT id,agent,stage,status,started_at,finished_at,error,duration_ms,cost_usd,model FROM agent_runs
           WHERE job_id=? ORDER BY started_at DESC, rowid DESC LIMIT ?""",(job_id,limit+1)
    ).fetchall()]
    # T-691: a failure is resolved once the same agent later completes (same rule as the Error Center).
    completed_at={x["agent"]:x["at"] or "" for x in con.execute(
        """SELECT agent,MAX(COALESCE(finished_at,started_at)) AS at FROM agent_runs
           WHERE job_id=? AND status='completed' GROUP BY agent""",(job_id,)).fetchall()}
    truncated=len(runs)>limit
    runs=list(reversed(runs[:limit]))
    if not runs:
        con.close()
        return empty
    ids=[r["id"] for r in runs]
    marks=",".join("?"*len(ids))
    outputs=[dict(x) for x in con.execute(
        f"""SELECT id,run_id,agent,kind,title FROM artifacts WHERE run_id IN ({marks})
            ORDER BY created_at, rowid""",ids
    ).fetchall()]
    inputs=[dict(x) for x in con.execute(
        f"""SELECT ri.run_id,ri.artifact_id,ri.source_agent,a.run_id source_run_id,a.title,a.kind
            FROM run_inputs ri JOIN artifacts a ON a.id=ri.artifact_id
            WHERE ri.run_id IN ({marks}) ORDER BY ri.created_at, ri.rowid""",ids
    ).fetchall()]
    con.close()
    hops={}
    for i,r in enumerate(runs):
        state=_flow_run_state(r["status"],r.get("error"))
        stopped=state in ("failed","blocked")
        hops[r["id"]]={"order":i+1,"run_id":r["id"],"agent":r["agent"],"stage":r.get("stage") or "","status":r["status"],"state":state,
                       "started_at":r["started_at"],"finished_at":r.get("finished_at"),
                       "duration_ms":r.get("duration_ms"),"cost_usd":r.get("cost_usd"),"model":r.get("model") or "",
                       "error":(r.get("error") or "")[:600] if stopped else "",
                       "inputs":[],"outputs":[],"downstream":[]}
        if stopped:
            p=classify_agent_error(r.get("error"))
            failed_at=r.get("finished_at") or r.get("started_at") or ""
            hops[r["id"]]["policy"]={k:p[k] for k in ("code","category","severity","title","action","retryable","requires_confirmation","spend_uncertain")}
            hops[r["id"]]["resolved"]=bool(completed_at.get(r["agent"]) and failed_at and completed_at[r["agent"]]>failed_at)
    for a in outputs:
        hops[a["run_id"]]["outputs"].append({"artifact_id":a["id"],"title":a["title"],"kind":a["kind"]})
    edges=[];sources={}
    for x in inputs:
        target=hops[x["run_id"]]
        upstream=hops.get(x["source_run_id"]) if x.get("source_run_id") else None
        item={"artifact_id":x["artifact_id"],"title":x["title"],"kind":x["kind"],"source_agent":x["source_agent"],
              "source_run_id":upstream["run_id"] if upstream else None,
              # "source" = seed/manual artifact with no run record; "earlier" = produced by a run outside this window.
              "origin":"run" if upstream else ("earlier" if x.get("source_run_id") else "source")}
        target["inputs"].append(item)
        if upstream:
            upstream["downstream"].append({"run_id":target["run_id"],"agent":target["agent"],"state":target["state"],"artifact_id":x["artifact_id"]})
        else:
            sources.setdefault(x["artifact_id"],{"artifact_id":x["artifact_id"],"title":x["title"],"kind":x["kind"],"agent":x["source_agent"],"origin":item["origin"]})
        edges.append({"from_run":item["source_run_id"],"from_agent":x["source_agent"],"artifact_id":x["artifact_id"],"artifact_title":x["title"],
                      "to_run":target["run_id"],"to_agent":target["agent"],"state":target["state"],"origin":item["origin"]})
    ordered=sorted(hops.values(),key=lambda h:h["order"])
    counts=dict(empty["counts"])
    for h in ordered:
        counts[h["state"]]+=1
    return {"job_id":job_id,"hops":ordered,"edges":edges,"sources":list(sources.values()),"counts":counts,
            "live":counts["running"]>0,"truncated":truncated}

RUN_INTERRUPTED_ERROR=("Run interrupted: the FactoryOS server restarted or the worker task stopped before this agent "
                       "finished; no result was recorded.")

# T-690: each FastAPI process owns the runs it starts and renews a heartbeat. During an overlapping Render deploy the
# old instance keeps executing while the new one starts, so "not in my running_jobs" is not proof that a run is dead.
PROCESS_ID=str(uuid.uuid4())
RUN_LEASE_SECONDS=int(os.environ.get("FACTORY_RUN_LEASE_SECONDS","90"))
RUN_HEARTBEAT_SECONDS=max(5,min(30,RUN_LEASE_SECONDS//3))
# Runs written before leases existed (or by an older build still draining) are closed only after the longest a single
# agent can take: every attempt at the provider timeout, plus a margin.
LEGACY_RUN_GRACE_SECONDS=AGENT_TIMEOUT_SECONDS*max(1,AGENT_MAX_RETRIES+1)+300

def beat_process_heartbeat(process_id=None):
    con=db()
    con.execute("INSERT OR REPLACE INTO process_heartbeats(process_id,heartbeat_at) VALUES(?,?)",(process_id or PROCESS_ID,ts()))
    con.commit();con.close()

def _heartbeat_loop():
    while True:
        try:beat_process_heartbeat()
        except Exception as exc:print(json.dumps({"event":"PROCESS_HEARTBEAT_ERROR","error":str(exc)[:200]}),flush=True)
        time.sleep(RUN_HEARTBEAT_SECONDS)

def _lease_cutoff(seconds):
    return (datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat()

def job_owned_by_live_process(job_id, lease_seconds=None):
    """True when another process holds a fresh lease on the job (it is executing it right now)."""
    cutoff=_lease_cutoff(RUN_LEASE_SECONDS if lease_seconds is None else lease_seconds)
    con=db()
    row=con.execute("""SELECT 1 FROM job_leases j JOIN process_heartbeats h ON h.process_id=j.process_id
                       WHERE j.job_id=? AND j.process_id<>? AND h.heartbeat_at>?""",(job_id,PROCESS_ID,cutoff)).fetchone()
    con.close()
    return bool(row)

def _run_is_orphaned(row, now_dt, lease_seconds, legacy_grace_seconds):
    owner=row.get("process_id")
    if owner==PROCESS_ID:
        return row["id"] not in LIVE_RUNS  # our own run whose task is gone (no finish was recorded)
    if owner:
        beat=row.get("heartbeat_at")
        return not beat or (now_dt-_parse_dt(beat)).total_seconds()>lease_seconds
    started=row.get("started_at")
    return bool(started) and (now_dt-_parse_dt(started)).total_seconds()>legacy_grace_seconds

def close_interrupted_agent_runs(job_id=None, lease_seconds=None, legacy_grace_seconds=None):
    """T-690: content-job runs live in a FastAPI process. After a deploy/restart (or a dead task) their agent_runs
    row stayed 'running' forever, so the trace showed a phantom live worker and the owner could not see where the job
    stopped. Close such rows as failed with an explicit, classified reason, but only when no live process owns them:
    our own run whose job we no longer execute, a run whose owner's heartbeat lease expired, or a lease-less legacy
    run older than any agent attempt can last."""
    lease=RUN_LEASE_SECONDS if lease_seconds is None else lease_seconds
    grace=LEGACY_RUN_GRACE_SECONDS if legacy_grace_seconds is None else legacy_grace_seconds
    con=db()
    sql="""SELECT r.id,r.job_id,r.agent,r.stage,r.started_at,l.process_id,h.heartbeat_at FROM agent_runs r
           LEFT JOIN agent_run_leases l ON l.run_id=r.id LEFT JOIN process_heartbeats h ON h.process_id=l.process_id
           WHERE r.status='running' AND r.job_id IS NOT NULL"""
    params=[]
    if job_id:
        sql+=" AND r.job_id=?";params.append(job_id)
    now_dt=datetime.now(timezone.utc)
    rows=[dict(x) for x in con.execute(sql,params).fetchall()]
    rows=[r for r in rows if _run_is_orphaned(r,now_dt,lease,grace)]
    now=ts();closed=[]
    lease_cut=_lease_cutoff(lease);legacy_cut=_lease_cutoff(grace)
    for r in rows:
        if r.get("process_id")==PROCESS_ID and r["id"] in LIVE_RUNS:
            continue
        # The ownership test is repeated inside the UPDATE, so a heartbeat renewed after the SELECT still protects the
        # run: a foreign owner must be stale *now*, and a lease-less run must still be older than the grace window.
        cur=con.execute("""UPDATE agent_runs SET status='failed',finished_at=?,error=? WHERE id=? AND status='running'
                AND NOT EXISTS (SELECT 1 FROM agent_run_leases l JOIN process_heartbeats h ON h.process_id=l.process_id
                                WHERE l.run_id=agent_runs.id AND l.process_id<>? AND h.heartbeat_at>?)
                AND (EXISTS (SELECT 1 FROM agent_run_leases l WHERE l.run_id=agent_runs.id) OR agent_runs.started_at<?)""",
                (now,RUN_INTERRUPTED_ERROR,r["id"],PROCESS_ID,lease_cut,legacy_cut))
        if cur.rowcount:closed.append(r)
    con.commit();con.close()
    rows=closed
    for r in rows:
        event(r["job_id"],f"Run interrupted: {r['agent']} ({r['stage'] or 'stage unknown'}) did not finish; marked failed so it can be retried")
    return len(rows)

def get_jobs_attention(job_ids):
    """T-690: per-job open incidents for the job list (same 'resolved' rule as get_job_error_center)."""
    ids=[x for x in job_ids if x]
    if not ids:
        return {}
    marks=",".join("?"*len(ids))
    con=db()
    rows=[dict(x) for x in con.execute(
        f"""SELECT r.job_id,r.agent,r.stage,r.error,r.id AS run_id FROM agent_runs r
            WHERE r.job_id IN ({marks}) AND r.status='failed' AND r.error IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM agent_runs c WHERE c.job_id=r.job_id AND c.agent=r.agent AND c.status='completed'
                              AND COALESCE(c.finished_at,c.started_at)>COALESCE(r.finished_at,r.started_at))
            ORDER BY COALESCE(r.finished_at,r.started_at) DESC""",ids).fetchall()]
    con.close()
    out={}
    for r in rows:
        item=out.setdefault(r["job_id"],{"open":0,"agent":r["agent"],"stage":r["stage"] or "","run_id":r["run_id"],
                                         "code":classify_agent_error(r["error"])["code"]})
        item["open"]+=1
    return out

def classify_agent_error(message):
    raw=(message or "").strip()
    low=raw.lower()
    policy={
        "code":"unknown_failure","category":"unknown","severity":"warning",
        "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
        "title":"Unclassified worker failure",
        "action":"Review the failed run before retrying. The provider outcome may be uncertain.",
    }
    if low.startswith("run interrupted"):
        # T-690: the in-process task died (deploy/restart) mid-run. Nothing was recorded, but a live
        # provider call may already have been billed, so a retry stays behind the confirmation gate.
        policy.update({
            "code":"run_interrupted","category":"interrupted","severity":"warning",
            "retryable":True,"auto_retry":False,"requires_confirmation":True,"spend_uncertain":True,
            "title":"Run interrupted by a server restart",
            "action":"No result was saved. Confirm, then retry this worker or press Run to continue from this stage.",
        })
    elif any(x in low for x in ("balance exhausted","insufficient_quota","no credits remaining")):
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
    scope=tenancy.current()
    if scope is not None:  # T-553: a member's selection never moves the owner's or another workspace's
        chosen=selected_job_by_workspace.get(scope)
        if not (chosen and any(j["id"]==chosen for j in jobs)):
            chosen=jobs[0]["id"] if jobs else None;selected_job_by_workspace[scope]=chosen
        return chosen
    if selected_job_id and any(j["id"]==selected_job_id for j in jobs): return selected_job_id
    selected_job_id = jobs[0]["id"] if jobs else None
    return selected_job_id

def _set_selected_job(job_id):
    global selected_job_id
    scope=tenancy.current()
    if scope is None:selected_job_id=job_id
    else:selected_job_by_workspace[scope]=job_id

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

        if j["status"] == "running" and j["id"] not in running_jobs and not job_owned_by_live_process(j["id"]):
            add("critical", "orphan_job", f"Orphaned running job: {j['title']}",
                "The database says the job is running, but no worker task owns it.",
                "Reset it to ready and restart from the current stage.")
            if auto_heal:
                con = db()
                con.execute("UPDATE jobs SET status='idle',updated_at=? WHERE id=?", (ts(), j["id"]))
                con.commit(); con.close()
                close_interrupted_agent_runs(j["id"])
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

    if auto_heal:
        interrupted=close_interrupted_agent_runs()
        if interrupted:
            healed.append(f"Closed {interrupted} agent run(s) whose process stopped before they finished.")

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
def close_runs_interrupted_by_restart():
    # T-690: renew this process's lease, then close only runs no live process owns (an overlapping old instance keeps
    # its runs until its heartbeat expires; the Supervisor cycle closes them after that).
    beat_process_heartbeat()
    threading.Thread(target=_heartbeat_loop,daemon=True,name="run-heartbeat").start()
    closed=close_interrupted_agent_runs()
    if closed:print(json.dumps({"event":"AGENT_RUNS_INTERRUPTED","closed":closed}),flush=True)

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
async def restore_claude_worker_heartbeat():
    _restore_claude_worker_heartbeat()

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
    publisher_state={
        "event":"PUBLISHER_RUNTIME",
        "version":APP_VERSION,
        "adapter":FACTORY_PUBLISHER_ADAPTER,
        "scheduler_enabled":FACTORY_PUBLISHER_SCHEDULER_ENABLED,
        "scheduler_interval_sec":FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC,
        "metricool_configured":_metricool_configured(),
        "metricool_reconcile_enabled":FACTORY_METRICOOL_RECONCILE_ENABLED,
        "analytics_adapter":FACTORY_ANALYTICS_ADAPTER,
        "analytics_webhook_configured":bool(FACTORY_ANALYTICS_ENDPOINT),
        "publishing_queue":_publishing_summary(),
        "approval_queue":_approval_summary(),
    }
    print(json.dumps(publisher_state),flush=True)
    asyncio.create_task(factory_cycle_reconcile_loop())
    if FACTORY_GITHUB_ISSUE_INTAKE_ENABLED:
        asyncio.create_task(github_issue_intake_loop())
    if FACTORY_PUBLISHER_SCHEDULER_ENABLED:
        asyncio.create_task(publisher_scheduler_loop())
    asyncio.create_task(morning_brief_loop())
    asyncio.create_task(mvp_pipeline_loop())
    asyncio.create_task(run_real_world_pilot_once())
    asyncio.create_task(run_media_finisher_pilot_once())

async def broadcast(payload=None):
    dead=[]; msg=json.dumps(payload or {"type":"refresh"}); scoped_msg=json.dumps({"type":"refresh"})
    for ws in list(clients):
        # T-553: workspace members get a bare refresh so ids/states of other workspaces never reach them.
        try: await ws.send_text(scoped_msg if ws in member_clients else msg)
        except Exception: dead.append(ws)
    for ws in dead: clients.discard(ws); member_clients.discard(ws)


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
    # Stage 3 (owner 2026-11-14): jobs from a brand plan (or linked to a brand) carry that brand's Master Brief.
    try:
        from brand_strategy import agent_context, brand_for_job
        # T-MODS: the "brand-strategy" mod switch decides whether the Master Brief enters agent prompts.
        if MODS.enabled("brand-strategy"):
            passport,item=brand_for_job(STRATEGY,job_id)
            brief=agent_context(passport,agent,item) if passport else ""
            if brief:
                additions.append(brief)
                MODS.use("brand-strategy")
    except Exception as exc:
        print(f"brand brief not added for {agent}: {type(exc).__name__}",file=__import__("sys").stderr)
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
    ctr_pct: Optional[float] = None
    conversions: Optional[int] = None
    source: str = "manual"

PERFORMANCE_FIELDS=(
    "views","reach","watch_time_sec","retention_pct","completion_rate_pct",
    "likes","comments","shares","saves","follower_delta","content_duration_sec",
    "ctr_pct","conversions",
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

# T-541: evidence groups shown to the operator before approval. Every finisher artifact is optional; an absent one is
# reported as not produced instead of being hidden, so the reviewer can tell "missing" from "not looked at".
MEDIA_FINISHER_PREVIEW_GROUPS=(
  ("cuts",("cut_list","edit_decisions","shorts_manifest")),
  ("captions",("caption_timeline","transcript_words","transcript_corrections")),
  ("audio",("audio_report",)),
  ("graphics",("graphics_timeline","motion_timeline")),
  ("qa",("safe_zone_report","qa_report","render_metrics","edit_summary")),
)

def _preview_media_item(item):
    if not item:return None
    return {"id":item.get("id"),"agent":item.get("agent"),"kind":item.get("kind"),"title":item.get("title"),
            "url":item.get("url") or "","mime_type":item.get("mime_type"),"created_at":item.get("created_at"),
            "component":(item.get("meta") or {}).get("component")}

def _media_finisher_operator_preview(job_id,media_review=None):
    media_review=media_review or _media_review_state(job_id)
    edit=media_review.get("edit_job")
    gate={"required":bool(media_review.get("required")),"ready":bool(media_review.get("ready")),
          "reason":media_review.get("reason") or "","human_approval_required":True,"auto_publish":False}
    if not edit:
        return {"available":False,"edit_job":None,"source":None,"final":_preview_media_item(media_review.get("artifact")),
                "shorts":[],"groups":[],"approval_gate":gate}
    edit_job_id=edit["id"]
    con=db()
    rows=[dict(x) for x in con.execute("""SELECT id,agent,kind,title,url,mime_type,created_at,meta_json FROM artifacts
                                          WHERE job_id=? AND agent IN ('AI Media Finisher','QA Agent') AND meta_json LIKE ?
                                          ORDER BY created_at""",(job_id,f'%"edit_job_id": "{edit_job_id}"%')).fetchall()]
    source_row=None
    if edit.get("input_artifact_id"):
        source_row=con.execute("""SELECT id,agent,kind,title,url,mime_type,created_at,meta_json FROM artifacts
                                  WHERE id=? AND job_id=?""",(edit["input_artifact_id"],job_id)).fetchone()
    if not source_row and edit.get("input_url"):
        source_row=con.execute("""SELECT id,agent,kind,title,url,mime_type,created_at,meta_json FROM artifacts
                                  WHERE job_id=? AND kind='video' AND url=? ORDER BY created_at DESC LIMIT 1""",
                               (job_id,edit["input_url"])).fetchone()
    con.close()
    for row in rows:row["meta"]=_decode_json(row.pop("meta_json","{}"),{})
    rows=[x for x in rows if x["meta"].get("edit_job_id")==edit_job_id]
    if source_row:
        source=dict(source_row);source["meta"]=_decode_json(source.pop("meta_json","{}"),{})
        source=_preview_media_item(source)
    elif re.match(r"^https?://",str(edit.get("input_url") or "")):
        source={"id":None,"agent":"","kind":"video","title":"Source video","url":edit["input_url"],"mime_type":"video/mp4",
                "created_at":edit.get("created_at"),"component":"source"}
    else:
        source=None
    by_component={}
    for row in rows:
        component=row["meta"].get("component")
        if row["agent"]=="AI Media Finisher" and component in MEDIA_FINISHER_EVIDENCE:by_component[component]=row
    groups=[]
    for group,components in MEDIA_FINISHER_PREVIEW_GROUPS:
        items=[]
        for component in components:
            row=by_component.get(component)
            items.append({"component":component,"title":MEDIA_FINISHER_EVIDENCE[component][1],"available":bool(row),
                          "artifact_id":row["id"] if row else None,"kind":row["kind"] if row else MEDIA_FINISHER_EVIDENCE[component][0]})
        groups.append({"group":group,"items":items,"available":sum(1 for x in items if x["available"]),"total":len(items)})
    shorts=[_preview_media_item(x) for x in rows if x["agent"]=="AI Media Finisher" and x["kind"]=="video"
            and x["meta"].get("component")=="short_render" and x.get("url")]
    shorts.sort(key=lambda x:str(x.get("title") or ""))
    qa=next((x for x in rows if x["agent"]=="QA Agent"),None)
    return {"available":True,
            "edit_job":{k:edit.get(k) for k in ("id","status","profile_id","profile_version","platform","rerun_stage","created_at","updated_at","error")},
            "source":source,"final":_preview_media_item(media_review.get("artifact")),"shorts":shorts,"groups":groups,
            "qa_gate_artifact_id":qa["id"] if qa else None,"approval_gate":gate}

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

def _metricool_configured():
    return bool(_metricool_credentials_present() and not _integration_explicitly_disconnected("Metricool"))

def _youtube_publisher_state(workspace=None):
    """Direct YouTube publisher readiness from facts only: OAuth client, stored channel token, upload settings.
    Scoped to one workspace (default: the caller's), so no workspace sees another's channel."""
    workspace=workspace or tenancy.binding_workspace()
    from oauth_framework import get_provider
    spec=get_provider("youtube")
    blockers=[b for b in OAUTH_FLOW.blockers(spec)]
    tokens=None
    if "vault_unavailable" not in blockers:
        try:tokens=OAUTH_FLOW.vault.get(workspace,"youtube")
        except Exception:blockers.append("vault_unreadable")
    if not tokens and not blockers:blockers.append("youtube_not_connected")
    if _integration_explicitly_disconnected("YouTube",workspace):blockers.append("youtube_disconnected")
    settings=youtube_publisher.upload_settings()
    blockers+=settings["blockers"]
    return {"configured":not blockers,"blockers":blockers,"channel_id":(tokens.account_id if tokens else ""),
            "channel_title":(tokens.account_label if tokens else ""),"privacy":settings["privacy"],
            "audience_configured":settings["made_for_kids"] is not None}

def get_publisher_adapter_registry():
    webhook=bool(FACTORY_PUBLISHER_ENDPOINT)
    metricool=_metricool_configured()
    youtube=_youtube_publisher_state()
    return {"selected":FACTORY_PUBLISHER_ADAPTER,
            "scheduler_enabled":FACTORY_PUBLISHER_SCHEDULER_ENABLED,
            "scheduler_interval_sec":FACTORY_PUBLISHER_SCHEDULER_INTERVAL_SEC,
            "metricool_reconcile_enabled":FACTORY_METRICOOL_RECONCILE_ENABLED,
            "adapters":[
                {"kind":"manual","configured":True,"status":"ready","execution":"explicit external confirmation"},
                {"kind":"webhook","configured":webhook,"status":"configured" if webhook else "not_configured","execution":"idempotent POST"},
                {"kind":"metricool","configured":metricool,"status":"configured" if metricool else "not_configured",
                 "execution":"server-side Metricool scheduler",
                 "supported_platforms":["instagram_reels","tiktok","youtube_shorts"],
                 "youtube_audience_configured":FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS in ("true","false","1","0","yes","no")},
                {"kind":"youtube","configured":youtube["configured"],
                 "status":"configured" if youtube["configured"] else "not_configured",
                 "execution":"direct YouTube Data API upload (official, free quota)",
                 "supported_platforms":["youtube_shorts"],"blockers":youtube["blockers"],
                 "channel_title":youtube["channel_title"],"privacy":youtube["privacy"],
                 "youtube_audience_configured":youtube["audience_configured"]},
            ],
            "secrets_exposed":False,
            "note":"Approval never publishes directly. Metricool receives only the exact immutable approved snapshot and durable media URL after explicit scheduling. A Metricool scheduler ID is never treated as a real platform post receipt."}

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
        "edit_job_id":meta.get("media_edit_job_id"),"sha256":meta.get("media_sha256") or ""
    } if meta.get("media_artifact_id") or meta.get("media_url") else None
    item["content_snapshot"]=meta.get("content_snapshot") if isinstance(meta.get("content_snapshot"),dict) else None
    item["content_snapshot_hash"]=str(meta.get("content_snapshot_hash") or "")
    item["approval_decision_id"]=meta.get("approval_decision_id")
    item["approved_at"]=meta.get("approved_at")
    item["workspace_key"]=job_workspace_key(item.get("job_id"))
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
          "media_edit_job_id":media_meta.get("edit_job_id"),
          # T-552-YT: digest of the exact durable file the owner approved; byte-uploading publishers verify it.
          "media_sha256":media_meta.get("archive_sha256") or ""}
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
    where,params=tenancy.sql_filter("publishing_queue.job_id")
    con=db();rows=con.execute(f"SELECT * FROM publishing_queue WHERE 1=1{where} ORDER BY updated_at DESC LIMIT ?",
                              (*params,max(1,min(300,int(limit))))).fetchall();con.close()
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

def _metricool_json(url,method="GET",payload=None):
    if not _metricool_configured():
        raise RuntimeError("Metricool publisher is not configured")
    headers={"Accept":"application/json","User-Agent":f"FactoryOS/{APP_VERSION}",
             "X-Mc-Auth":FACTORY_METRICOOL_TOKEN}
    data=None
    if payload is not None:
        data=json.dumps(payload,ensure_ascii=False).encode("utf-8")
        headers["Content-Type"]="application/json"
    req=urlrequest.Request(url,data=data,headers=headers,method=method)
    with urlrequest.urlopen(req,timeout=45) as response:
        raw=response.read().decode("utf-8","replace")
        try:return json.loads(raw or "{}")
        except json.JSONDecodeError:return {"raw_text":raw[:4000],"http_status":getattr(response,"status",None)}

def _metricool_normalize_media_url(media_url):
    """Copy approved media to Metricool-owned hosting before scheduler submission.

    Metricool's normalize endpoint intentionally returns plain text for media URLs,
    so it must not use _metricool_json (which advertises JSON). The durable
    FactoryOS URL remains the provenance source; the normalized URL is only the
    transport copy handed to the social scheduler.
    """
    media_url=str(media_url or "").strip()
    if not media_url:
        raise RuntimeError("Metricool media normalization requires a public media URL")
    query=urlparse.urlencode({
        "url":media_url,"folder":"PLANNER",
        "userId":FACTORY_METRICOOL_USER_ID,"blogId":FACTORY_METRICOOL_BLOG_ID,
    })
    req=urlrequest.Request(
        f"{FACTORY_METRICOOL_BASE_URL}/api/actions/normalize/image/url?{query}",
        headers={"Accept":"*/*","X-Mc-Auth":FACTORY_METRICOOL_TOKEN,
                 "User-Agent":f"FactoryOS/{APP_VERSION}"},
        method="GET",
    )
    with urlrequest.urlopen(req,timeout=300) as response:
        raw=response.read().decode("utf-8","replace").strip()
    normalized=raw.strip().strip('"')
    if raw[:1] in ("{","["):
        try:
            parsed=json.loads(raw)
            stack=[parsed]
            while stack:
                current=stack.pop(0)
                if isinstance(current,dict):
                    for key in ("url","mediaUrl","media_url","normalizedUrl","normalized_url"):
                        value=current.get(key)
                        if isinstance(value,str) and value.startswith(("http://","https://")):
                            normalized=value.strip();stack=[];break
                    else:
                        stack.extend(current.values())
                elif isinstance(current,list):
                    stack.extend(current)
        except Exception:
            pass
    if not normalized.startswith(("http://","https://")):
        raise RuntimeError(f"Metricool media normalization returned no public URL: {normalized[:240]}")
    return normalized

def _metricool_network(platform):
    key=str(platform or "").strip().lower()
    mapping={
        "instagram":"instagram","instagram_reel":"instagram","instagram_reels":"instagram","reels":"instagram",
        "tiktok":"tiktok","tik_tok":"tiktok",
        "youtube":"youtube","youtube_short":"youtube","youtube_shorts":"youtube","shorts":"youtube",
    }
    network=mapping.get(key)
    if not network:
        raise RuntimeError(f"Metricool adapter does not support platform '{platform}'")
    return network

def _metricool_bool_setting(raw,name):
    value=str(raw or "").strip().lower()
    if value in ("1","true","yes","on"):return True
    if value in ("0","false","no","off"):return False
    raise RuntimeError(f"{name} must be explicitly configured as true or false")

def _metricool_publication_time(scheduled_at):
    try:
        requested=datetime.fromisoformat(str(scheduled_at or "").replace("Z","+00:00"))
        if requested.tzinfo is None:raise ValueError("timezone required")
    except Exception as exc:
        raise RuntimeError("Metricool requires a valid scheduled_at timestamp with timezone") from exc
    minimum=datetime.now(timezone.utc)+timedelta(minutes=2)
    target=max(requested.astimezone(timezone.utc),minimum)
    try:zone=ZoneInfo(FACTORY_METRICOOL_TIMEZONE)
    except Exception as exc:raise RuntimeError("Invalid FACTORY_METRICOOL_TIMEZONE") from exc
    local=target.astimezone(zone)
    return {"dateTime":local.strftime("%Y-%m-%dT%H:%M:%S"),"timezone":FACTORY_METRICOOL_TIMEZONE,
            "_utc":target.isoformat()}

def _metricool_post_text(content):
    content=content if isinstance(content,dict) else {}
    parts=[]
    description=str(content.get("description") or "").strip()
    cta=str(content.get("cta") or "").strip()
    hashtags=["#"+str(x).strip().lstrip("#") for x in (content.get("hashtags") or []) if str(x).strip()]
    if description:parts.append(description)
    if cta:parts.append(cta)
    if hashtags:parts.append(" ".join(hashtags))
    return "\n\n".join(parts).strip()

def _metricool_scheduler_payload(item,content,media,normalize=True):
    network=_metricool_network(item.get("platform"))
    media_url=str((media or {}).get("url") or "").strip()
    if not media_url:
        raise RuntimeError("Metricool video publishing requires the exact approved media URL")
    title=str((content or {}).get("title") or "").strip()
    if not title:title="FactoryOS approved video"
    publication=_metricool_publication_time(item.get("scheduled_at"))
    # Dry-run (T-542) skips the normalize call: it is an outbound upload to Metricool hosting.
    normalized_media_url=_metricool_normalize_media_url(media_url) if normalize else media_url
    payload={
        "publicationDate":{"dateTime":publication["dateTime"],"timezone":publication["timezone"]},
        "text":_metricool_post_text(content),
        "providers":[{"network":network}],
        "autoPublish":True,"draft":False,"shortener":False,
        "saveExternalMediaFiles":True,
        "media":[normalized_media_url],
    }
    if network=="instagram":
        payload["instagramData"]={"type":"REEL","collaborators":[],"showReelOnFeed":True,"isAiGenerated":True}
    elif network=="tiktok":
        payload["tiktokData"]={"disableComment":False,"disableDuet":False,"disableStitch":False,
                               "privacyOption":"PUBLIC_TO_EVERYONE","commercialContentThirdParty":False,
                               "commercialContentOwnBrand":False,"title":title,"autoAddMusic":False,
                               "photoCoverIndex":0,"isAigc":True}
    elif network=="youtube":
        made_for_kids=_metricool_bool_setting(FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS,
                                               "FACTORY_METRICOOL_YOUTUBE_MADE_FOR_KIDS")
        payload["youtubeData"]={"title":title,"type":"short","privacy":"public",
                               "tags":[str(x).strip().lstrip("#") for x in ((content or {}).get("hashtags") or []) if str(x).strip()],
                               "madeForKids":made_for_kids,"isAiGeneratedContent":True}
    return payload,publication["_utc"],network

def _publish_via_metricool(item,content,media):
    if not _metricool_configured():
        raise RuntimeError("Metricool publisher requires FACTORY_METRICOOL_TOKEN, FACTORY_METRICOOL_USER_ID and FACTORY_METRICOOL_BLOG_ID")
    payload,scheduled_utc,network=_metricool_scheduler_payload(item,content,media)
    provider_name={"youtube":"YouTube","instagram":"Instagram","tiktok":"TikTok"}[network]
    if _integration_explicitly_disconnected(provider_name):
        raise RuntimeError(f"{provider_name} is disconnected from this FactoryOS workspace")
    query=urlparse.urlencode({"blogId":FACTORY_METRICOOL_BLOG_ID,"userId":FACTORY_METRICOOL_USER_ID})
    result=_metricool_json(f"{FACTORY_METRICOOL_BASE_URL}/api/v2/scheduler/posts?{query}","POST",payload)
    data=result.get("data") if isinstance(result.get("data"),dict) else result
    scheduler_id=(data or {}).get("id") or (data or {}).get("postId") or (data or {}).get("uuid")
    planner_url=(data or {}).get("plannerUrl") or (data or {}).get("planner_url") or ""
    raw={"provider":"metricool","network":network,"scheduled_at_utc":scheduled_utc,
         "metricool_schedule_id":scheduler_id,"planner_url":planner_url,"response":result}
    raw["normalized_media_url"]=(payload.get("media") or [""])[0]
    return {"manual":False,"status":"publishing","external_post_id":None,"external_url":None,"raw":raw}

def _metricool_calendar_posts(item):
    meta=item.get("meta") or {}
    adapter=meta.get("adapter_result") if isinstance(meta.get("adapter_result"),dict) else {}
    scheduled_raw=str(adapter.get("scheduled_at_utc") or item.get("scheduled_at") or "").strip()
    try:
        scheduled=datetime.fromisoformat(scheduled_raw.replace("Z","+00:00"))
        if scheduled.tzinfo is None:scheduled=scheduled.replace(tzinfo=timezone.utc)
    except Exception:
        scheduled=datetime.now(timezone.utc)
    start=(scheduled.astimezone(timezone.utc)-timedelta(days=2)).strftime("%Y-%m-%dT%H:%M:%S")
    end=(scheduled.astimezone(timezone.utc)+timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%S")
    query=urlparse.urlencode({
        "blogId":FACTORY_METRICOOL_BLOG_ID,"userId":FACTORY_METRICOOL_USER_ID,
        "start":start,"end":end,"timezone":FACTORY_METRICOOL_TIMEZONE,"extendedRange":"true",
    })
    result=_metricool_json(f"{FACTORY_METRICOOL_BASE_URL}/api/v2/scheduler/posts?{query}","GET")
    if isinstance(result,list):return result
    if isinstance(result,dict):
        for key in ("data","posts","items","content"):
            value=result.get(key)
            if isinstance(value,list):return value
            if isinstance(value,dict):
                for nested in ("data","posts","items","content"):
                    if isinstance(value.get(nested),list):return value[nested]
    return []

def _metricool_post_identity(post):
    if not isinstance(post,dict):return set()
    values=set()
    for key in ("id","uuid","postId","post_id","schedulerId","scheduler_id"):
        value=post.get(key)
        if value not in (None,""):values.add(str(value))
    return values

def _metricool_match_post(posts,scheduler_id):
    target=str(scheduler_id or "").strip()
    if not target:return None
    for post in posts or []:
        if target in _metricool_post_identity(post):return post
    return None

def _metricool_provider_snapshot(post,network):
    post=post if isinstance(post,dict) else {}
    providers=post.get("providers") if isinstance(post.get("providers"),list) else []
    provider=None
    for candidate in providers:
        if not isinstance(candidate,dict):continue
        name=str(candidate.get("network") or candidate.get("provider") or candidate.get("name") or "").strip().lower()
        if name==network:
            provider=candidate;break
    if provider is None and len(providers)==1 and isinstance(providers[0],dict):provider=providers[0]
    provider=provider or {}
    status=str(provider.get("status") or post.get("status") or "").strip().upper()
    detail=str(provider.get("detailedStatus") or provider.get("detailed_status") or post.get("detailedStatus") or "").strip()
    public_url=str(provider.get("publicUrl") or provider.get("public_url") or provider.get("externalUrl") or
                   post.get("publicUrl") or post.get("public_url") or post.get("externalUrl") or "").strip()
    external_id=""
    for source in (provider,post):
        for key in ("externalPostId","external_post_id","socialMediaId","social_media_id","postId","post_id"):
            value=source.get(key) if isinstance(source,dict) else None
            if value not in (None,""):
                external_id=str(value);break
        if external_id:break
    return {"status":status,"detail":detail,"public_url":public_url,"external_id":external_id,
            "provider":provider,"post":post}

def reconcile_metricool_publish(publish_id):
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    if not row:return {"changed":False,"status":"missing","publish_id":publish_id}
    item=_publish_item(row);meta=item.get("meta") or {}
    adapter=meta.get("adapter_result") if isinstance(meta.get("adapter_result"),dict) else {}
    if item.get("status")!="publishing" or str(adapter.get("provider") or "").lower()!="metricool":
        return {"changed":False,"status":item.get("status"),"publish_id":publish_id}
    scheduler_id=adapter.get("metricool_schedule_id")
    if not scheduler_id:
        return {"changed":False,"status":"publishing","publish_id":publish_id,"reason":"missing_metricool_schedule_id"}
    try:
        network=str(adapter.get("network") or _metricool_network(item.get("platform"))).lower()
        posts=_metricool_calendar_posts(item)
        post=_metricool_match_post(posts,scheduler_id)
        now=ts()
        reconcile_meta={"checked_at":now,"scheduler_id":str(scheduler_id),"network":network,
                        "calendar_items":len(posts),"found":bool(post)}
        if not post:
            con=db();con.execute("UPDATE publishing_queue SET meta_json=?,updated_at=? WHERE id=?",
                (json.dumps({**meta,"metricool_reconcile":{**reconcile_meta,"status":"not_found"}},ensure_ascii=False),now,publish_id))
            con.commit();con.close()
            return {"changed":False,"status":"publishing","publish_id":publish_id,"reason":"not_found"}
        snap=_metricool_provider_snapshot(post,network)
        status=snap["status"];public_url=snap["public_url"];detail=snap["detail"]
        reconcile_meta.update({"status":status or "UNKNOWN","detailed_status":detail,"public_url":public_url})
        published=status in ("PUBLISHED","PUBLISHED_WITH_ERRORS","DONE","SUCCESS") or (status=="ERROR" and bool(public_url))
        if published:
            external_id=snap["external_id"] or f"metricool:{scheduler_id}"
            published_at=now
            next_meta={**meta,"metricool_reconcile":{**reconcile_meta,
                       "external_id_kind":"platform" if snap["external_id"] else "metricool_schedule_fallback"}}
            con=db();con.execute("""UPDATE publishing_queue SET status='published',external_post_id=?,external_url=?,
                                   published_at=?,updated_at=?,last_error=NULL,meta_json=? WHERE id=?""",
                (external_id,public_url,published_at,now,json.dumps(next_meta,ensure_ascii=False,default=str),publish_id))
            con.commit();updated=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
            published_item=_publish_item(updated)
            _publish_receipt(published_item,external_id,public_url,published_at,"metricool-reconcile")
            return {"changed":True,"status":"published","publish_id":publish_id,
                    "external_post_id":external_id,"external_url":public_url}
        if status in ("ERROR","FAILED","REJECTED","CANCELLED","CANCELED"):
            message=detail or f"Metricool provider status {status}"
            con=db();con.execute("UPDATE publishing_queue SET status='failed',last_error=?,updated_at=?,meta_json=? WHERE id=?",
                (message[:900],now,json.dumps({**meta,"metricool_reconcile":reconcile_meta},ensure_ascii=False,default=str),publish_id))
            con.commit();con.close()
            event(item["job_id"],f"Metricool publish failed: {network} · {message[:180]}")
            sync_cycle_for_publish(publish_id)
            return {"changed":True,"status":"failed","publish_id":publish_id,"message":message}
        con=db();con.execute("UPDATE publishing_queue SET meta_json=?,updated_at=? WHERE id=?",
            (json.dumps({**meta,"metricool_reconcile":reconcile_meta},ensure_ascii=False,default=str),now,publish_id))
        con.commit();con.close()
        return {"changed":False,"status":"publishing","publish_id":publish_id,"provider_status":status or "UNKNOWN"}
    except Exception as exc:
        now=ts()
        reconcile_meta={"checked_at":now,"scheduler_id":str(scheduler_id),"status":"reconcile_error","error":str(exc)[:700]}
        con=db();con.execute("UPDATE publishing_queue SET meta_json=?,updated_at=? WHERE id=?",
            (json.dumps({**meta,"metricool_reconcile":reconcile_meta},ensure_ascii=False,default=str),now,publish_id))
        con.commit();con.close()
        return {"changed":False,"status":"publishing","publish_id":publish_id,"error":str(exc)}

def reconcile_metricool_publishing(limit=None):
    if not (FACTORY_METRICOOL_RECONCILE_ENABLED and _metricool_configured()):
        return {"processed":0,"changed":0,"results":[]}
    # Metricool runs on the default workspace's server credentials, so only default-workspace items reconcile.
    con=db();rows=con.execute(f"""SELECT id FROM publishing_queue WHERE status='publishing'
                                 AND {tenancy.JOB_WORKSPACE_SQL.format(col='publishing_queue.job_id')}=?
                                 ORDER BY updated_at LIMIT ?""",(tenancy.DEFAULT_WORKSPACE,int(limit or FACTORY_METRICOOL_RECONCILE_LIMIT))).fetchall();con.close()
    results=[reconcile_metricool_publish(row["id"]) for row in rows]
    return {"processed":len(results),"changed":sum(1 for x in results if x.get("changed")),"results":results}

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

def _publish_via_youtube(item,content,media,workspace):
    """T-552-YT: upload the exact approved durable media to the connected channel. Never retried blindly."""
    if item.get("platform")!="youtube_shorts":
        raise RuntimeError(f"YouTube publisher only handles youtube_shorts, not {item.get('platform')}")
    state=_youtube_publisher_state(workspace)
    if not state["configured"]:
        raise RuntimeError("YouTube publisher is not ready: "+", ".join(state["blockers"]))
    artifact=_artifact_media_row((media or {}).get("artifact_id"))
    if not artifact or artifact.get("job_id")!=item.get("job_id") or (artifact.get("url") or "")!=(media or {}).get("url"):
        raise RuntimeError("Approved media artifact does not match the approved snapshot")
    path,archive_meta=_artifact_archive_file(artifact)
    if not path or not Path(path).is_file():
        raise RuntimeError("Approved media is not in the durable FactoryOS archive; YouTube needs the exact file")
    # The bytes must be the ones approved: only the digest captured in the approval snapshot counts (never the
    # artifact's current metadata, which a re-archive could rewrite together with the file). upload_video re-checks
    # it on the same file handle it uploads from.
    expected=str((media or {}).get("sha256") or "").lower()
    if not expected:
        raise RuntimeError("Approved media has no digest in the approval snapshot; re-approve it before publishing")
    if expected!=str((archive_meta or {}).get("sha256") or "").lower():
        raise RuntimeError("Archived media bytes do not match the approved media digest")
    from oauth_framework import get_provider
    spec=get_provider("youtube");adapter=OAUTH_FLOW.adapters["youtube"]
    try:
        tokens=adapter.refresh(spec,OAUTH_FLOW.vault.get(workspace,"youtube"))
        OAUTH_FLOW.vault.put(workspace,"youtube",tokens)
    except OAuthError as exc:
        raise RuntimeError(f"YouTube token refresh failed ({exc.code}); reconnect YouTube") from None
    settings=youtube_publisher.upload_settings()
    metadata=youtube_publisher.video_metadata(content,settings)
    try:
        result=youtube_publisher.upload_video(adapter.http,tokens.access_token,Path(path),
                                              (archive_meta or {}).get("content_type") or media.get("mime_type") or "video/mp4",metadata,
                                              expected)
    except youtube_publisher.YouTubeError as exc:
        if exc.code in ("youtube_media_digest_mismatch","youtube_media_digest_missing"):
            raise RuntimeError("Archived media bytes do not match the approved media digest") from None
        # Uncertain outcomes surface as TimeoutError so the publish item demands explicit confirmation before a retry.
        if exc.uncertain:raise TimeoutError(exc.code) from None
        raise RuntimeError(exc.code) from None
    raw={"provider":"youtube","channel_id":tokens.account_id,"channel_title":tokens.account_label,
         "video_id":result["video_id"],"privacy":result["privacy"],"upload_status":result["upload_status"],
         "made_for_kids":settings["made_for_kids"],"contains_synthetic_media":True}
    return {"manual":False,"status":"published","external_post_id":result["video_id"],"external_url":result["url"],"raw":raw}

def _publish_via_adapter(item):
    if FACTORY_PUBLISHER_ADAPTER=="manual":
        return {"manual":True,"status":"publishing"}
    workspace=item.get("workspace_key") or job_workspace_key(item.get("job_id"))
    if workspace!=tenancy.DEFAULT_WORKSPACE:
        # T-553: server publisher credentials belong to the default workspace; customer workspaces need their own (T-552).
        raise RuntimeError(f"Workspace '{workspace}' has no publisher credentials of its own; server credentials are not shared across workspaces")
    content=item.get("content_snapshot")
    if not isinstance(content,dict):
        con=db();row=con.execute("SELECT * FROM content_packages WHERE id=? AND job_id=?",(item["package_id"],item["job_id"])).fetchone();con.close()
        package_record=_content_package_dict(row) if row else None
        if not package_record:raise RuntimeError("Approved Content Package snapshot is unavailable")
        content=_publish_content_snapshot(package_record)
    media=item.get("media") or {}
    if FACTORY_PUBLISHER_ADAPTER=="metricool":
        return _publish_via_metricool(item,content,media)
    if FACTORY_PUBLISHER_ADAPTER=="youtube":
        return _publish_via_youtube(item,content,media,workspace)
    if not FACTORY_PUBLISHER_ENDPOINT:
        raise RuntimeError(f"Publisher adapter '{FACTORY_PUBLISHER_ADAPTER}' is not configured")
    payload={"idempotency_key":item["idempotency_key"],"publish_id":item["id"],"job_id":item["job_id"],"workspace_key":workspace,
             "package_id":item["package_id"],"approval_decision_id":item.get("approval_decision_id"),
             "content_snapshot_hash":item.get("content_snapshot_hash") or _publish_snapshot_hash(content),
             "target":item["target"],"platform":item["platform"],
             "scheduled_at":item.get("scheduled_at"),"media_url":media.get("url") or "",
             "media_artifact_id":media.get("artifact_id"),"media":media,"content":content}
    result=_external_json(FACTORY_PUBLISHER_ENDPOINT,"POST",payload,FACTORY_PUBLISHER_TOKEN)
    return {"manual":False,"status":str(result.get("status") or "publishing"),
            "external_post_id":result.get("external_post_id") or result.get("id"),
            "external_url":result.get("external_url") or result.get("url"),"raw":result}

# T-542 — Publishing dry-run evidence. Builds the exact per-platform publisher plan for an approved
# publish item without any outbound call, status change or external post ID.
PUBLISH_DRY_RUN_PLATFORMS=("youtube_shorts","tiktok","instagram_reels")

def _publish_dry_run_binding(item):
    """Verify the publish item still carries the immutable approved snapshot and its exact media."""
    problems=[]
    content=item.get("content_snapshot")
    stored_hash=item.get("content_snapshot_hash") or ""
    recomputed=_publish_snapshot_hash(content) if isinstance(content,dict) else ""
    if not isinstance(content,dict):problems.append("approved content snapshot is missing")
    elif not stored_hash or recomputed!=stored_hash:problems.append("content snapshot hash does not match the approved snapshot")
    if not item.get("approved_at"):problems.append("publish item has no human approval record")
    media=item.get("media") or {}
    media_ok=False
    if not media.get("artifact_id") or not media.get("url"):
        problems.append("approved media artifact or URL is missing")
    else:
        con=db();row=con.execute("SELECT id,url,job_id FROM artifacts WHERE id=?",(media["artifact_id"],)).fetchone();con.close()
        if not row:problems.append("approved media artifact no longer exists")
        elif (row["url"] or "")!=media["url"] or row["job_id"]!=item["job_id"]:
            problems.append("approved media artifact does not match the approved media URL/job")
        else:media_ok=True
    return {"ok":not problems,"problems":problems,"content_snapshot_hash":stored_hash,
            "recomputed_hash":recomputed,"media_artifact_id":media.get("artifact_id"),
            "media_url":media.get("url") or "","media_verified":media_ok,
            "approval_decision_id":item.get("approval_decision_id"),"approved_at":item.get("approved_at")}

def build_publish_dry_run(publish_id):
    con=db();row=con.execute("SELECT * FROM publishing_queue WHERE id=?",(publish_id,)).fetchone();con.close()
    if not row:raise LookupError("Publish item not found")
    item=_publish_item(row)
    if item["status"] not in ("approved","scheduled","failed"):
        raise ValueError(f"Dry-run is only available for approved, unpublished items (status={item['status']})")
    binding=_publish_dry_run_binding(item)
    content=item.get("content_snapshot") or {}
    media=item.get("media") or {}
    plans=[]
    for platform in PUBLISH_DRY_RUN_PLATFORMS:
        entry={"platform":platform,"ready":False,"blockers":[],"payload":None,"network":None}
        if not binding["ok"]:
            entry["blockers"]=list(binding["problems"])
        else:
            try:
                payload,scheduled_utc,network=_metricool_scheduler_payload(
                    {**item,"platform":platform,"scheduled_at":item.get("scheduled_at") or ts()},content,media,normalize=False)
                entry.update({"ready":True,"network":network,"payload":payload,"scheduled_at_utc":scheduled_utc,
                              "media_binding":"exact approved media URL (Metricool normalization skipped in dry-run)"})
            except RuntimeError as exc:
                entry["blockers"].append(str(exc))
        plans.append(entry)
    registry=get_publisher_adapter_registry()
    metricool=next((a for a in registry["adapters"] if a["kind"]=="metricool"),{})
    real_blockers=[]
    selected=next((a for a in registry["adapters"] if a["kind"]==FACTORY_PUBLISHER_ADAPTER),{})
    if FACTORY_PUBLISHER_ADAPTER=="manual" or not selected.get("configured"):
        real_blockers.append("T-520: no configured real publisher adapter")
    supported=selected.get("supported_platforms")
    if FACTORY_PUBLISHER_ADAPTER!="manual" and supported is not None:
        for plan in plans:plan["real_publisher_supported"]=plan["platform"] in supported
        if item.get("platform") and item["platform"]!="unspecified" and item["platform"] not in supported:
            real_blockers.append(f"T-520: publisher '{FACTORY_PUBLISHER_ADAPTER}' does not support {item['platform']}")
    real_blockers.append("T-521: explicit owner approval of this exact snapshot for a real post")
    # The plan hash excludes publication times so re-running the same snapshot is idempotent.
    stable=[{k:v for k,v in p.items() if k!="scheduled_at_utc"} for p in plans]
    for p in stable:
        if p.get("payload"):p["payload"]={k:v for k,v in p["payload"].items() if k!="publicationDate"}
    plan_hash=_publish_snapshot_hash({"publish_id":item["id"],"idempotency_key":item["idempotency_key"],
                                      "binding":{k:binding[k] for k in ("content_snapshot_hash","media_artifact_id","media_url")},
                                      "plans":stable})
    receipt_preview={"dry_run":True,"status":"not_published","external_post_id":None,"external_url":None,
                     "publish_id":item["id"],"job_id":item["job_id"],"idempotency_key":item["idempotency_key"],
                     "approval_decision_id":item.get("approval_decision_id"),
                     "content_snapshot_hash":binding["content_snapshot_hash"],
                     "media_artifact_id":binding["media_artifact_id"],"plan_hash":plan_hash,
                     "platforms":[p["platform"] for p in plans if p["ready"]]}
    result={"dry_run":True,"publish_id":item["id"],"job_id":item["job_id"],"plan_hash":plan_hash,
            "binding":binding,"content_snapshot":content,"media":media,"plans":plans,
            "receipt_preview":receipt_preview,
            "real_publish":{"allowed":False,"blockers":real_blockers,"adapter":FACTORY_PUBLISHER_ADAPTER,
                            "adapter_configured":bool(metricool.get("configured"))},
            "spend_usd":0.0,"outbound_calls":0,"generated_at":ts()}
    con=db();existing=con.execute("""SELECT id FROM artifacts WHERE job_id=? AND agent='Publisher'
                                    AND kind='publish_dry_run' AND meta_json LIKE ? LIMIT 1""",
                                  (item["job_id"],f'%"plan_hash": "{plan_hash}"%')).fetchone();con.close()
    if existing:
        result["artifact_id"]=existing["id"];result["idempotent"]=True
        return result
    result["artifact_id"]=save_artifact("Publisher","publish_dry_run",f"Publishing dry-run · {len(receipt_preview['platforms'])}/{len(plans)} platforms",
        json.dumps(result,ensure_ascii=False,indent=2,default=str),job_id=item["job_id"],mime_type="application/json",
        meta={"publish_id":item["id"],"plan_hash":plan_hash,"dry_run":True,"idempotency_key":item["idempotency_key"],
              "content_snapshot_hash":binding["content_snapshot_hash"],"media_artifact_id":binding["media_artifact_id"],
              "binding_ok":binding["ok"]})
    result["idempotent"]=False
    event(item["job_id"],f"Publishing dry-run: {len(receipt_preview['platforms'])}/{len(plans)} platform plan(s) · no external post")
    return result

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

# T-646: the owner can say what a cycle aims at. All four fields are optional and only steer existing steps:
# topic narrows which new signals are attached, brand links the production job to that brand's Master Brief,
# platform/audience are written into the production brief. None of them publishes or spends anything.
FACTORY_CYCLE_TARGET_PLATFORMS=("",)+PUBLISH_DRY_RUN_PLATFORMS
CYCLE_TARGET_EDITABLE=("ready","stopped","failed")

# T-647: stable codes for cycle error/status messages, so the dashboard can show them in EN/UK/RU.
# The English text stays the source of truth (logs, API clients); the code and params only drive translation.
CYCLE_MESSAGE_CODES=(
    (r"^Factory cycle not found","not_found"),
    (r"^Unknown target platform: (?P<value>.*)$","bad_platform"),
    (r"^Unknown brand: (?P<value>.*)$","bad_brand"),
    (r"^(?:One or more source signal ids are unknown|Unknown source signal id\(s\): (?P<value>.*))$","bad_signals"),
    (r"^(?:Idea not found|Cycle idea no longer exists)","idea_missing"),
    (r"^Parent cycle not found","parent_missing"),
    (r"^The target can change only before production","target_locked"),
    (r"^Only a ready, running or failed cycle can be stopped","not_stoppable"),
    (r"^Only a stopped cycle can be resumed","not_resumable"),
    (r"^This cycle is stopped","stopped_resume_first"),
    (r"^This idea already has production job (?P<job>\S+) made for a different target \((?P<have>.*)\)\.","job_other_target"),
    (r"^Rejected idea cannot enter production","idea_rejected"),
    (r"^Live-mode idea must pass Content Brain verification","idea_not_verified"),
    (r"^No source signals","no_signals"),
    (r"^Content Brain generated no usable ideas","no_ideas"),
    (r"^Idea Verifier did not shortlist","no_shortlist"),
    (r"^Preselected idea did not pass verification","idea_failed_verification"),
    (r"^Production did not reach the human approval gate","production_not_at_gate"),
    (r"^Live LLM provider is not configured","llm_not_configured"),
    (r"^Daily provider budget would be exceeded","daily_budget"),
    (r"^No real performance snapshot","no_metrics"),
    (r"^Factory cycle is already running","already_running"),
    (r"^Confirm the conservative paid-work ceiling","confirm_cost"),
    (r"^Autopilot started and will stop","started"),
)

def cycle_message_info(message):
    """(code, params) for a known cycle message; ('unknown', {'text': message}) otherwise."""
    text=str(message or "").strip()
    for pattern,code in CYCLE_MESSAGE_CODES:
        m=re.match(pattern,text)
        if m:return code,{k:v for k,v in m.groupdict().items() if v is not None}
    if len(text)>500:return "unknown",{"text":text[:500]+"…","truncated":True}
    return "unknown",{"text":text}

def cycle_http_error(status,exc):
    code,params=cycle_message_info(str(exc))
    return HTTPException(status,{"message":str(exc),"code":code,"params":params})

def _cycle_target(raw):
    raw=dict(raw or {})
    target={k:re.sub(r"\s+"," ",str(raw.get(k) or "")).strip()[:120] for k in ("brand","topic","platform","audience")}
    if target["platform"] not in FACTORY_CYCLE_TARGET_PLATFORMS:
        raise ValueError("Unknown target platform: "+target["platform"])
    if target["brand"]:
        known={b["brand"] for b in STRATEGY.brands()}
        if target["brand"] not in known:raise ValueError("Unknown brand: "+target["brand"])
    return target

def _signal_ids_for_topic(signal_ids,topic):
    """Keep only signals whose topic or title mentions the target topic. Returns (ids, matched)."""
    topic=(topic or "").strip().lower()
    if not topic or not signal_ids:return signal_ids,None
    placeholders=",".join("?" for _ in signal_ids)
    con=db();rows=con.execute(f"SELECT id,title,topic FROM source_signals WHERE id IN ({placeholders})",signal_ids).fetchall();con.close()
    keep={x["id"] for x in rows if topic in (x["topic"] or "").lower() or topic in (x["title"] or "").lower()}
    picked=[x for x in signal_ids if x in keep]
    return (picked,True) if picked else (signal_ids,False)

def _new_signal_ids_for_topic(topic):
    """Newest *new* signals that mention the topic, searched across all new signals before the limit is applied.
    Returns (ids, matched); with no topic or no match it falls back to the newest new signals."""
    topic=(topic or "").strip().lower()
    if not topic:return _new_signal_ids(),None
    # Matched in Python (SQLite lower() only folds ASCII; topics are often Cyrillic). Bounded scan of new signals.
    con=db();rows=con.execute("""SELECT id,title,topic FROM source_signals WHERE status='new'
                                 ORDER BY created_at DESC LIMIT 2000""").fetchall();con.close()
    rows=[x for x in rows if topic in (x["topic"] or "").lower() or topic in (x["title"] or "").lower()][:FACTORY_CYCLE_MAX_SIGNALS]
    ids=[x["id"] for x in rows]
    return (ids,True) if ids else (_new_signal_ids(),False)

def create_factory_cycle(payload,source="owner"):
    target=_cycle_target(payload.target)
    signal_ids=list(dict.fromkeys(str(x).strip() for x in (payload.signal_ids or []) if str(x).strip()))
    topic_matched=None
    if not signal_ids and not payload.idea_id:
        signal_ids,topic_matched=_new_signal_ids_for_topic(target["topic"])
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
          "publisher_execution":"explicit","paid_generation":"confirmation_required","target":target}
    if topic_matched is not None:meta["target_topic_matched"]=topic_matched
    if not payload.signal_ids and not idea_id:meta["signals_auto"]=True
    con.execute("""INSERT INTO factory_cycles(
        id,parent_cycle_id,status,phase,source_signal_ids_json,idea_id,job_id,publish_id,workflow_version_id,
        created_at,updated_at,started_at,completed_at,last_error,learning_json,meta_json
    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(
        cycle_id,parent,"ready","idea" if idea_id else "signals",json.dumps(signal_ids),idea_id,None,None,active["id"],
        now,now,None,None,"","{}",json.dumps(meta,ensure_ascii=False)
    ))
    con.commit();con.close()
    cycle_event(cycle_id,"signals",f"Factory cycle created with {len(signal_ids)} signal(s)"+(" and a preselected idea" if idea_id else ""),
                {"workflow_version_id":active["id"],"source":source,"target":target})
    if topic_matched is False:
        cycle_event(cycle_id,"signals",f"No new signal mentions the target topic '{target['topic']}'; all new signals were attached")
    return get_factory_cycle(cycle_id,True)

def set_factory_cycle_target(cycle_id,raw):
    cycle=get_factory_cycle(cycle_id)
    if not cycle:raise LookupError("Factory cycle not found")
    if cycle["status"] not in CYCLE_TARGET_EDITABLE or cycle.get("job_id") or cycle_id in active_factory_cycles:
        raise PermissionError("The target can change only before production starts (ready, stopped or failed, no job yet)")
    target=_cycle_target(raw)
    meta=dict(cycle.get("meta") or {});old_topic=(meta.get("target") or {}).get("topic","")
    meta["target"]=target;meta.pop("target_topic_matched",None)
    fields={}
    # Signals the cycle picked by itself follow the new topic; signals or an idea chosen by the owner stay as chosen.
    if meta.get("signals_auto") and not cycle.get("idea_id") and target["topic"]!=old_topic:
        ids,matched=_new_signal_ids_for_topic(target["topic"])
        if matched is not True:   # no new signal matches: keep any already attached signal that does
            kept,kept_match=_signal_ids_for_topic(cycle.get("source_signal_ids") or [],target["topic"])
            if kept_match:ids,matched=kept,True
        if matched is not None:meta["target_topic_matched"]=matched
        fields["source_signal_ids_json"]=json.dumps(ids)
    _cycle_update(cycle_id,meta_json=json.dumps(meta,ensure_ascii=False),**fields)
    cycle_event(cycle_id,cycle.get("phase") or "signals","Cycle target changed by the owner",{"target":target})
    if fields:
        cycle_event(cycle_id,"signals",f"Signals re-selected for the new topic: {len(json.loads(fields['source_signal_ids_json']))}")
    if meta.get("target_topic_matched") is False:
        cycle_event(cycle_id,"signals",f"No signal mentions the target topic '{target['topic']}'; all available signals are kept")
    return get_factory_cycle(cycle_id,True)

# T-646: stop/resume. A stop is a flag the coordinator reads between handoffs; it never cancels a provider call
# mid-flight and never touches the approval gate. Resume returns the cycle to `ready` and re-syncs from its job.
CYCLE_STOPPABLE=("ready","running","failed")

class _CycleStopped(Exception):
    pass

def _cycle_stop_requested(cycle_id):
    cycle=get_factory_cycle(cycle_id)
    return bool(cycle and (cycle.get("meta") or {}).get("stop_requested"))

def _cycle_checkpoint(cycle_id,step):
    if _cycle_stop_requested(cycle_id):raise _CycleStopped(step)

def stop_factory_cycle(cycle_id):
    cycle=get_factory_cycle(cycle_id)
    if not cycle:raise LookupError("Factory cycle not found")
    if cycle["status"]=="stopped":return {"cycle":get_factory_cycle(cycle_id,True),"pending":False}
    if cycle["status"] not in CYCLE_STOPPABLE:
        raise PermissionError("Only a ready, running or failed cycle can be stopped. Later steps already wait for you.")
    meta=dict(cycle.get("meta") or {});meta["stop_requested"]=True
    pending=cycle_id in active_factory_cycles
    if pending:
        _cycle_update(cycle_id,meta_json=json.dumps(meta,ensure_ascii=False))
        cycle_event(cycle_id,cycle.get("phase") or "signals","Stop requested; Autopilot stops at the next handoff")
    else:
        _cycle_update(cycle_id,status="stopped",meta_json=json.dumps(meta,ensure_ascii=False))
        cycle_event(cycle_id,cycle.get("phase") or "signals","Cycle stopped by the owner")
    return {"cycle":get_factory_cycle(cycle_id,True),"pending":pending}

def resume_factory_cycle(cycle_id):
    cycle=get_factory_cycle(cycle_id)
    if not cycle:raise LookupError("Factory cycle not found")
    if cycle["status"]!="stopped":raise PermissionError("Only a stopped cycle can be resumed")
    meta=dict(cycle.get("meta") or {});meta.pop("stop_requested",None)
    _cycle_update(cycle_id,status="ready",meta_json=json.dumps(meta,ensure_ascii=False),last_error="")
    cycle_event(cycle_id,cycle.get("phase") or "signals","Cycle resumed by the owner")
    return sync_factory_cycle(cycle_id,True)

CYCLE_TARGET_MARK="CYCLE TARGET (owner): "

def _cycle_target_line(target):
    target=target or {}
    lines=[f"{label}: {target[key]}" for key,label in (("brand","BRAND"),("topic","TOPIC"),("platform","TARGET PLATFORM"),("audience","TARGET AUDIENCE")) if target.get(key)]
    return "; ".join(lines)

def _job_target_line(brief):
    for line in reversed((brief or "").splitlines()):
        if line.startswith(CYCLE_TARGET_MARK):return line[len(CYCLE_TARGET_MARK):]
    return ""

def _check_existing_job_target(cycle_id,idea_id):
    """An idea has at most one production job. Reusing it is only honest when it was made for the same target."""
    con=db();row=con.execute("""SELECT j.id,j.brief FROM job_idea_links l JOIN jobs j ON j.id=l.job_id
                                WHERE l.idea_id=? ORDER BY l.created_at DESC LIMIT 1""",(idea_id,)).fetchone();con.close()
    if not row:return
    want=_cycle_target_line(((get_factory_cycle(cycle_id) or {}).get("meta") or {}).get("target"))
    have=_job_target_line(row["brief"])
    if want!=have:
        raise RuntimeError(f"This idea already has production job {row['id'][:8]} made for a different target "
                           f"({have or 'no target'}). Start the cycle from another idea, or set the same target.")

def _apply_cycle_target_to_job(cycle_id,job_id,created):
    """Write the cycle target into a freshly created production job and link the brand (Master Brief)."""
    target=((get_factory_cycle(cycle_id) or {}).get("meta") or {}).get("target") or {}
    if not created or not any(target.values()):return
    con=db();row=con.execute("SELECT brief FROM jobs WHERE id=?",(job_id,)).fetchone()
    if row:
        con.execute("UPDATE jobs SET brief=?,updated_at=? WHERE id=?",
                    ((row["brief"] or "")+"\n"+CYCLE_TARGET_MARK+_cycle_target_line(target),ts(),job_id));con.commit()
    con.close()
    if target.get("brand"):
        try:
            STRATEGY.link_job(target["brand"],job_id)
            cycle_event(cycle_id,"production",f"Production job linked to brand {target['brand']}; agents get its Master Brief")
        except Exception as exc:
            reason=str(getattr(exc,'detail',exc))[:200]
            cur=get_factory_cycle(cycle_id) or {};meta=dict(cur.get("meta") or {});meta["brand_link_error"]=reason
            _cycle_update(cycle_id,meta_json=json.dumps(meta,ensure_ascii=False))
            cycle_event(cycle_id,"production",f"WARNING: brand {target['brand']} was NOT linked, agents do not get its Master Brief: {reason}",
                        {"code":"brand_not_linked","params":{"brand":target["brand"],"reason":reason}})

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
    assign_job_workspace(con,jid)
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

def _cycle_record_error(cycle_id,status,exc):
    code,params=cycle_message_info(str(exc))
    meta=dict((get_factory_cycle(cycle_id) or {}).get("meta") or {})
    meta["last_error_code"]=code;meta["last_error_params"]=params
    _cycle_update(cycle_id,status=status,last_error=str(exc)[:1200],meta_json=json.dumps(meta,ensure_ascii=False))
    return code,params

async def _run_factory_cycle_to_review(cycle_id,max_ideas=3,language="English"):
    active_factory_cycles.add(cycle_id)
    try:
        cycle=get_factory_cycle(cycle_id,True)
        if not cycle:raise ValueError("Factory cycle not found")
        if cycle.get("job") and cycle["job"].get("status")=="waiting_approval":
            _cycle_update(cycle_id,status="waiting_approval",phase="approval",last_error="")
            return
        meta=dict(cycle.get("meta") or {});meta.pop("last_error_code",None);meta.pop("last_error_params",None)
        _cycle_update(cycle_id,status="running",started_at=cycle.get("started_at") or ts(),last_error="",
                      meta_json=json.dumps(meta,ensure_ascii=False))
        cycle_event(cycle_id,cycle.get("phase") or "signals","Autopilot run started",{"language":language})
        _cycle_checkpoint(cycle_id,"signals")

        signal_ids=cycle.get("source_signal_ids") or []
        if not signal_ids and not cycle.get("idea_id"):
            collected=await asyncio.to_thread(collect_configured_signals,FACTORY_CYCLE_MAX_SIGNALS) if FACTORY_SIGNAL_FEEDS else {"created":[]}
            signal_ids=[x["id"] for x in collected.get("created") or []] or _new_signal_ids()
            run_topic=((cycle.get("meta") or {}).get("target") or {}).get("topic")
            signal_ids,matched=_signal_ids_for_topic(signal_ids,run_topic)
            if matched is not None:
                meta=dict((get_factory_cycle(cycle_id) or {}).get("meta") or {});meta["target_topic_matched"]=matched
                _cycle_update(cycle_id,meta_json=json.dumps(meta,ensure_ascii=False))
            if matched is False:
                cycle_event(cycle_id,"signals",f"No collected signal mentions the target topic '{run_topic}'; all collected signals were used")
            if not signal_ids:raise RuntimeError("No source signals are available. Add a signal or configure RSS feeds.")
            _cycle_update(cycle_id,source_signal_ids_json=json.dumps(signal_ids),phase="ideas")
            cycle_event(cycle_id,"signals",f"Attached {len(signal_ids)} available signal(s)")

        idea_id=cycle.get("idea_id")
        _cycle_checkpoint(cycle_id,"ideas")
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

        _cycle_checkpoint(cycle_id,"production")
        _check_existing_job_target(cycle_id,idea_id)
        bridge=create_job_from_idea(idea_id,language)
        _apply_cycle_target_to_job(cycle_id,bridge["job"]["id"],bridge.get("created"))
        job=bridge["job"];workflow=_workflow_context(job["id"],lock=True)["version"]
        _cycle_update(cycle_id,job_id=job["id"],workflow_version_id=workflow["id"],phase="production")
        cycle_event(cycle_id,"production","Content Brain → production handoff completed",
                    {"job_id":job["id"],"idea_id":idea_id,"workflow_version_id":workflow["id"]})
        running_jobs.add(job["id"])
        await run_until_review(job["id"])
        job=get_job(job["id"])
        if not job or job.get("status")!="waiting_approval":
            raise RuntimeError("Production did not reach the human approval gate")
        if _cycle_stop_requested(cycle_id):
            _cycle_update(cycle_id,status="stopped",phase="approval",last_error="")
            cycle_event(cycle_id,"approval","Stopped as requested after production; the package waits at the approval gate, nothing was published",
                        {"job_id":job["id"]})
            await broadcast({"type":"factory_cycle","action":"stopped","cycleId":cycle_id})
            return
        _cycle_update(cycle_id,status="waiting_approval",phase="approval",last_error="")
        cycle_event(cycle_id,"approval","Production package is ready; Autopilot stopped at the human approval gate",
                    {"job_id":job["id"]})
        await broadcast({"type":"factory_cycle","action":"waiting_approval","cycleId":cycle_id,"jobId":job["id"]})
    except _CycleStopped as stop:
        _cycle_update(cycle_id,status="stopped",last_error="")
        cycle_event(cycle_id,str(stop) or "signals","Autopilot stopped by the owner before this step; nothing was skipped or published")
        await broadcast({"type":"factory_cycle","action":"stopped","cycleId":cycle_id})
    except Exception as exc:
        if _cycle_stop_requested(cycle_id):
            # The owner asked to stop while this step was running: honour the stop, keep the error visible.
            _cycle_record_error(cycle_id,"stopped",exc)
            cycle_event(cycle_id,"error",f"Step failed after a stop was requested; the cycle stays stopped: {str(exc)[:500]}",
                        {"code":"stopped_then_failed","params":{},"cause":{"code":cycle_message_info(str(exc))[0],
                         "params":cycle_message_info(str(exc))[1],"text":str(exc)[:1200]}})
            await broadcast({"type":"factory_cycle","action":"stopped","cycleId":cycle_id})
            return
        code,params=_cycle_record_error(cycle_id,"failed",exc)
        cycle_event(cycle_id,"error",f"Autopilot failed: {str(exc)[:500]}",{"code":code,"params":params})
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
    if status=="stopped":
        _cycle_update(cycle_id,publish_id=(publish or {}).get("id") or cycle.get("publish_id"))
        return get_factory_cycle(cycle_id,True)
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

INTAKE_SNAPSHOT_MAX_AGE=900  # the EC2 pusher runs every 3 minutes

INTAKE_SNAPSHOT_CLOCK_SKEW=60  # a snapshot "from the future" beyond this is not trusted as fresh

def _intake_issues_from_ec2_snapshot():
    """#41/#258: owner Issues from the EC2 worker's snapshot (owner gh login) when Render's own read fails.
    Returns (data, reason): data is None unless the snapshot is present, well-formed and fresh; reason is one of
    "fresh", "missing", "stale", "malformed". Unknown is never imported as fresh."""
    snap=_load_team_snapshot()
    if snap is None:return None,"missing"
    if not isinstance(snap,dict):return None,"malformed"
    try:received=float(snap.get("received"))
    except (TypeError,ValueError):return None,"malformed"
    age=time.time()-received
    if age>INTAKE_SNAPSHOT_MAX_AGE or age<-INTAKE_SNAPSHOT_CLOCK_SKEW:return None,"stale"
    github=snap.get("github")
    if not isinstance(github,dict) or not isinstance(github.get("issues"),list):return None,"malformed"
    issues=[{"number":i.get("number"),"title":str(i.get("title") or ""),"body":str(i.get("body") or ""),
             "url":str(i.get("html_url") or ""),"state":str(i.get("state") or ""),"author":str(i.get("author") or ""),
             "pull_request":bool(i.get("pull_request"))} for i in github["issues"] if isinstance(i,dict)]
    return {"issues":issues,"github":{**github,"pulls":github.get("pulls") if isinstance(github.get("pulls"),list) else []}},"fresh"

def github_issue_intake_once(fetch=None):
    """T-599-E / #41: one owner-Issue intake pass; logs counts/IDs and safe reason codes only, never bodies or tokens.

    Source: Render's own GitHub read, else the fresh EC2 snapshot. Claude issues that Queue Keeper (#231) sees as
    blocked (open Depends, owner gate, another agent's PR) are deferred, so the worker never starts them early."""
    direct=relay_github_owner_issues(GITHUB_REPO,_github_read_token(),fetch=fetch)
    source,render_error,gate_github="render","",None
    if direct.get("available"):
        issues,owner=direct["issues"],direct["owner"]
        gate_github={"available":True,"pulls":[],"issues":[{"number":i.get("number"),"title":i.get("title"),"body":i.get("body"),
                     "state":i.get("state"),"html_url":i.get("url"),"labels":[]} for i in issues if isinstance(i,dict)]}
    else:
        render_error=f"{direct.get('error','')} ({direct.get('reason','unknown')})"
        ec2,snapshot_state=_intake_issues_from_ec2_snapshot()
        if ec2 is None:
            print(json.dumps({"event":"GITHUB_ISSUE_INTAKE","ok":False,"error":direct.get("error",""),"reason":direct.get("reason",""),
                              "ec2_snapshot":snapshot_state,"imported":[],"linked":[],"existing":0,"ignored":0}),flush=True)
            return {"ok":False,"error":direct.get("error") or "GitHub unavailable","ec2_snapshot":snapshot_state,
                    "imported":[],"existing":[],"linked":[],"ignored":0}
        issues,owner,source,gate_github=ec2["issues"],GITHUB_REPO.split("/",1)[0],"ec2",ec2["github"]
    readiness=queue_readiness({**gate_github,"available":True},roadmap=_parse_roadmap_tasks(),agent="claude")
    blocked={t["number"]:t["reasons"] for t in readiness.get("blocked") or []}
    deferred=[{"issue":n,"reasons":r} for n,r in sorted(blocked.items())]
    ready=[i for i in issues if not (isinstance(i,dict) and _safe_int(i.get("number")) in blocked)]
    result={"ok":True,**RELAY_QUEUE.auto_intake_owner_issues(ready,GITHUB_REPO,owner)}
    print(json.dumps({"event":"GITHUB_ISSUE_INTAKE","ok":True,"source":source,"render_error":render_error,
                      "imported":[x["issue"] for x in result["imported"]],"linked":[x["issue"] for x in result["linked"]],
                      "existing":len(result["existing"]),"ignored":result["ignored"],"deferred":[d["issue"] for d in deferred]}),flush=True)
    for row in result["imported"]:
        try:_telegram_send(f"📥 Relay {row['ticket']}: GitHub #{row['issue']} (Owner: {row['lane']})\nВ очереди, выполнение ещё не началось.")
        except Exception:pass
    result.update(source=source,deferred=deferred,render_error=render_error)
    return result

def _safe_int(value):
    try:return int(value)
    except (TypeError,ValueError):return 0


PEER_REVIEW_BUDGET=ReviewBudget(DATA_DIR)


def relay_peer_review_once(pulls,ci,reader,gemini_call=None,limit=2):
    """Evidence T2.6 (owner option A): Gemini reviews Claude's PRs that touch risky areas or are large, once
    per head commit after CI is green. Free tier, stable Flash, DAILY_CAP per day; unavailable = retried later."""
    notices=[]
    for c in RELAY_QUEUE.review_candidates(pulls,ci,time.time())[:limit]:
        files=None
        if not c["scope_known"]:
            try:files=reader(f"/pulls/{c['number']}/files?per_page=100")
            except Exception:files=None
            if not isinstance(files,list):
                # Unknown diff: be conservative, so a risky PR cannot close unreviewed while GitHub is flaky.
                RELAY_QUEUE.record_review_scope(c["ticket"],c["head"],True,"diff unreadable")
                continue
            required,reason=needs_review(files)
            RELAY_QUEUE.record_review_scope(c["ticket"],c["head"],required,reason)
            if not required:
                continue
        if not FACTORY_GEMINI_API_KEY or not PEER_REVIEW_BUDGET.take():
            RELAY_QUEUE.record_review(c["ticket"],c["head"],None,time.time())
            continue
        if files is None:
            try:files=reader(f"/pulls/{c['number']}/files?per_page=100")
            except Exception:files=None
        if not isinstance(files,list):
            RELAY_QUEUE.record_review(c["ticket"],c["head"],None,time.time())
            continue
        verdict=gemini_review(FACTORY_GEMINI_API_KEY,build_prompt(c["title"],c["body"],files),gemini_call or _gemini_raw_call,
                              None if gemini_call else resolve_flash_model)
        RELAY_QUEUE.record_review(c["ticket"],c["head"],verdict,time.time())
        print(json.dumps({"event":"PEER_REVIEW","ticket":c["ticket"],"status":"unavailable" if verdict is None else verdict["verdict"],
                          "blockers":0 if verdict is None else verdict["blockers"]}),flush=True)
        if verdict is not None:
            notices.append({"ticket":c["ticket"],"action":"peer_review","text":review_notice_text(c["ticket"],c["url"],verdict)})
    return notices


def relay_pr_reconcile_once(fetch=None):
    """#289 round trip: follow Relay tickets' PRs (CI passed/failed, merged, closed) and tell the owner once per
    transition. Evidence Tier 2.1: with FACTORY_GITHUB_READ_TOKEN the facts come from Render's own GitHub read
    (source github:render, the only source that counts as checked); otherwise, or if that read fails, from the fresh
    EC2 snapshot, which the worker itself uploads (source github:ec2-snapshot). Unknown stays unknown."""
    github,source,snapshot_state=None,"github:ec2-snapshot",""
    if GITHUB_READ_TOKEN or fetch is not None:
        own=read_github(fetch or github_fetcher(GITHUB_REPO,GITHUB_READ_TOKEN))
        if own.get("available"):
            github,source,snapshot_state=own,"github:render","render"
    if github is None:
        ec2,snapshot_state=_intake_issues_from_ec2_snapshot()
        if ec2 is None:
            return {"ok":False,"snapshot":snapshot_state,"notices":0}
        github=ec2["github"]
    ci=github.get("ci") if isinstance(github.get("ci"),dict) else {}
    notices=[]
    if source=="github:render":
        notices+=relay_peer_review_once(github.get("pulls") or [],ci,fetch or github_fetcher(GITHUB_REPO,GITHUB_READ_TOKEN))
    notices+=RELAY_QUEUE.reconcile_pull_requests(github.get("pulls") or [],ci,source=source)
    if source=="github:render":
        # Evidence T2.2: is a ticket's merge commit inside the build Render runs now? Only from our own read.
        reader=fetch or github_fetcher(GITHUB_REPO,GITHUB_READ_TOKEN)

        def contains(merge_sha):
            try:
                data=reader(f"/compare/{merge_sha}...{BUILD_SHA}")
            except Exception:
                return None
            status=str((data or {}).get("status") or "") if isinstance(data,dict) else ""
            return True if status in ("ahead","identical") else False if status in ("behind","diverged") else None
        notices+=RELAY_QUEUE.reconcile_deploys(BUILD_SHA,contains)
    owner_chat=str((_telegram_load_state() or {}).get("chat_id") or "")
    for n in notices:
        try:
            if n.get("markup") and owner_chat:_telegram_send_markup(owner_chat,n["text"],n["markup"])
            else:_telegram_send(n["text"])
        except Exception:pass
    if notices:
        print(json.dumps({"event":"RELAY_PR_RECONCILE","source":source,"notices":[{"ticket":n["ticket"],"action":n["action"]} for n in notices]}),flush=True)
    return {"ok":True,"snapshot":snapshot_state,"source":source,"notices":len(notices)}

def _morning_brief_github(now=None):
    """Fresh main commit facts with an honest, logged fallback on GitHub read failure."""
    return github_brief_snapshot(
        token=GITHUB_READ_TOKEN, repo=GITHUB_REPO, now=time.time() if now is None else now,
        fetcher=github_fetcher, read_snapshot=read_github,
        fallback=_intake_issues_from_ec2_snapshot,
        log_error=lambda event: print(json.dumps(event), flush=True))


def _morning_brief_compose(date,now,yesterday_plan=None):
    tickets=RELAY_STORE.list(limit=500)
    return compose_brief(date,now,github=_morning_brief_github(now),tickets=tickets,
                         questions_open=int(OWNER_QUESTIONS.queue_stats().get("open") or 0),
                         evidence_metrics=_evidence.metrics(tickets,now),yesterday_plan=yesterday_plan)


MORNING_BRIEF=MorningBrief(DATA_DIR,deliver=lambda date,text:BRIEF_DELIVER(date,text),send_text=_telegram_send,
                           compose=_morning_brief_compose,plan_source=lambda:brief_plan_ids(RELAY_STORE.list(limit=500)))


async def mvp_pipeline_loop():
    """MVP Builder step 2: move autopilot projects one hand-off per minute (see mvp_pipeline.py)."""
    await asyncio.sleep(45)
    while True:
        try:
            moved=await asyncio.to_thread(MVP_PIPELINE.tick)
            if moved:print(json.dumps({"event":"MVP_PIPELINE","moved":moved}),flush=True)
        except Exception as exc:
            print(json.dumps({"event":"MVP_PIPELINE_ERROR","error":type(exc).__name__}),flush=True)
        await asyncio.sleep(60)


async def morning_brief_loop():
    """#106: owner opt-in (/brief on), 08:00 Europe/Kyiv, one brief per date; see morning_brief.py."""
    await asyncio.sleep(30)
    while True:
        try:await asyncio.to_thread(MORNING_BRIEF.tick)
        except Exception as exc:
            print(json.dumps({"event":"MORNING_BRIEF_ERROR","error":type(exc).__name__}),flush=True)
        await asyncio.sleep(60)


async def github_issue_intake_loop():
    await asyncio.sleep(60)
    while True:
        try:await asyncio.to_thread(github_issue_intake_once)
        except Exception as exc:
            print(json.dumps({"event":"GITHUB_ISSUE_INTAKE_ERROR","error":type(exc).__name__}),flush=True)
        try:await asyncio.to_thread(relay_pr_reconcile_once)
        except Exception as exc:
            print(json.dumps({"event":"RELAY_PR_RECONCILE_ERROR","error":type(exc).__name__}),flush=True)
        await asyncio.sleep(FACTORY_GITHUB_ISSUE_INTAKE_INTERVAL_SEC)


async def factory_cycle_reconcile_loop():
    while True:
        try:
            con=db();rows=con.execute("""SELECT id FROM factory_cycles
                                        WHERE status NOT IN ('failed','rejected','learning_ready','completed','stopped')
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
    jw,jp=tenancy.sql_filter("jobs.id");dw,dp=tenancy.sql_filter("approval_decisions.job_id")
    con=db()
    waiting=int(con.execute(f"SELECT COUNT(*) c FROM jobs WHERE status='waiting_approval'{jw}",jp).fetchone()["c"] or 0)
    decisions=int(con.execute(f"SELECT COUNT(*) c FROM approval_decisions WHERE 1=1{dw}",dp).fetchone()["c"] or 0)
    con.close();return {"waiting":waiting,"decisions":decisions}

def _publishing_summary():
    where,params=tenancy.sql_filter("publishing_queue.job_id")
    con=db();rows=con.execute(f"SELECT status,COUNT(*) c FROM publishing_queue WHERE 1=1{where} GROUP BY status",params).fetchall();con.close()
    return {x["status"]:x["c"] for x in rows}

def _performance_summary():
    sw,sp=tenancy.sql_filter("performance_snapshots.job_id");pw,pp=tenancy.sql_filter("publishing_queue.job_id")
    con=db()
    snapshots=int(con.execute(f"SELECT COUNT(*) c FROM performance_snapshots WHERE 1=1{sw}",sp).fetchone()["c"] or 0)
    published=int(con.execute(f"SELECT COUNT(*) c FROM publishing_queue WHERE status='published'{pw}",pp).fetchone()["c"] or 0)
    con.close();return {"snapshots":snapshots,"published_items":published}

def get_approval_queue(limit=60):
    where,params=tenancy.sql_filter("jobs.id")
    con=db();jobs=[dict(x) for x in con.execute(
        f"""SELECT {_JOB_COLUMNS_SQL} FROM jobs WHERE status IN ('waiting_approval','approved','rejected'){where}
           ORDER BY updated_at DESC LIMIT ?""",(*params,max(1,min(200,int(limit))))).fetchall()];con.close()
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
                      "finisher_preview":_media_finisher_operator_preview(job["id"],media_review),
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
    where,params=tenancy.sql_filter("publishing_queue.job_id")
    con=db();rows=con.execute(f"""SELECT * FROM publishing_queue WHERE status='published'{where}
                                 ORDER BY published_at DESC,updated_at DESC LIMIT ?""",
                              (*params,max(1,min(300,int(limit))))).fetchall();con.close()
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
    if not pub or not tenancy.visible(tenancy.job_workspace(con,pub["job_id"])):con.close();raise ValueError("Published item not found")
    if pub["status"]!="published":con.close();raise ValueError("Performance can only be attached to a published item")
    metrics={}
    for key in PERFORMANCE_FIELDS:
        value=getattr(payload,key)
        if value is not None:metrics[key]=value
    if not metrics:con.close();raise ValueError("At least one real platform metric is required")
    publish=_publish_item(pub)
    publish_meta=(publish or {}).get("meta") or {}
    workflow=get_job_workflow_assignment(pub["job_id"]) or {}
    snapshot_meta={
        "publish_id":pub["id"],
        "external_post_id":str(pub["external_post_id"] or ""),
        "external_url":str(pub["external_url"] or ""),
        "media_artifact_id":publish_meta.get("media_artifact_id"),
        "media_edit_job_id":publish_meta.get("media_edit_job_id"),
        "content_snapshot_hash":publish_meta.get("content_snapshot_hash"),
        "approval_decision_id":publish_meta.get("approval_decision_id"),
        "workflow_version_id":workflow.get("workflow_version_id"),
        "experiment_id":workflow.get("experiment_id"),
        "experiment_arm":workflow.get("arm"),
        "source":payload.source or "manual",
    }
    snapshot_id=str(uuid.uuid4());captured=payload.captured_at or ts()
    con.execute("""INSERT INTO performance_snapshots(
        id,publish_id,job_id,platform,captured_at,metrics_json,source,meta_json
    ) VALUES(?,?,?,?,?,?,?,?)""",(
        snapshot_id,pub["id"],pub["job_id"],pub["platform"],captured,json.dumps(metrics),
        payload.source or "manual",json.dumps(snapshot_meta,ensure_ascii=False,default=str)
    ))
    con.commit();con.close()
    save_artifact("Analyst","performance_snapshot",f"Performance snapshot · {pub['platform']}",
                  json.dumps(metrics,ensure_ascii=False,indent=2),job_id=pub["job_id"],
                  meta=snapshot_meta)
    event(pub["job_id"],f"Performance snapshot recorded: {pub['platform']} · {', '.join(metrics.keys())}")
    sync_cycle_for_publish(pub["id"])
    return {"id":snapshot_id,"publish_id":pub["id"],"metrics":metrics,"captured_at":captured,"meta":snapshot_meta}

def factory_cycle_readiness():
    """T-646: what a beginner needs before the first cycle — real counts only, nothing estimated."""
    con=db()
    new_signals=con.execute("SELECT COUNT(*) n FROM source_signals WHERE status='new'").fetchone()["n"]
    # Ideas a cycle can start from: not rejected and not yet in production (live mode verifies them first).
    ideas=[dict(x) for x in con.execute("""SELECT id,title,score,status,verified_at FROM content_ideas
                                          WHERE status IN ('selected','shortlisted','generated')
                                          ORDER BY CASE status WHEN 'selected' THEN 0 WHEN 'shortlisted' THEN 1 ELSE 2 END,
                                                   updated_at DESC LIMIT 20""").fetchall()]
    con.close()
    try:brands=[{"brand":b["brand"],"name":b.get("name") or b["brand"]} for b in STRATEGY.brands()]
    except Exception:brands=[]
    return {"new_signals":int(new_signals),"feeds_configured":bool(FACTORY_SIGNAL_FEEDS),
            "paid_calls_possible":bool(FACTORY_LLM_API_KEY),"ideas":ideas,"brands":brands,
            "platforms":[x for x in FACTORY_CYCLE_TARGET_PLATFORMS if x]}

@app.get("/api/factory-cycles")
def factory_cycles(limit:int=80):
    data=get_factory_cycles(limit)
    data["readiness"]=factory_cycle_readiness()
    return data

@app.get("/api/factory-cycles/{cycle_id}")
def factory_cycle_detail(cycle_id:str):
    # #114 B-1: a GET (viewers included) only reads; reconciliation and learning run through POST /sync and /learn.
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:raise cycle_http_error(404,"Factory cycle not found")
    return cycle

@app.post("/api/factory-cycles")
async def new_factory_cycle(payload:FactoryCycleCreate):
    try:cycle=create_factory_cycle(payload)
    except ValueError as exc:raise cycle_http_error(400,exc)
    await broadcast({"type":"factory_cycle","action":"created","cycleId":cycle["id"]})
    return {"ok":True,"cycle":cycle}

@app.get("/api/factory-cycles/{cycle_id}/quote")
def factory_cycle_quote(cycle_id:str,max_ideas:int=3):
    try:return estimate_factory_cycle_cost(cycle_id,max_ideas)
    except ValueError as exc:raise cycle_http_error(400,exc)

@app.post("/api/factory-cycles/{cycle_id}/run")
async def run_factory_cycle_api(cycle_id:str,payload:FactoryCycleRunRequest):
    cycle=get_factory_cycle(cycle_id,True)
    if not cycle:raise cycle_http_error(404,"Factory cycle not found")
    if cycle["status"]=="stopped":raise cycle_http_error(409,"This cycle is stopped. Resume it first.")
    if cycle_id in active_factory_cycles:return {"ok":True,"message":"Factory cycle is already running","message_code":"already_running"}
    try:quote=estimate_factory_cycle_cost(cycle_id,payload.max_ideas)
    except ValueError as exc:raise cycle_http_error(400,exc)
    if quote["paid_calls_possible"] and not payload.confirm_cost:
        return {"ok":False,"requiresCostConfirmation":True,"quote":quote,
                "message":"Confirm the conservative paid-work ceiling before Autopilot starts. Daily/job budgets remain hard limits.",
                "message_code":"confirm_cost"}
    meta=dict(cycle.get("meta") or {})
    if meta.pop("stop_requested",None):   # a stop flag left by a run that already ended is stale
        _cycle_update(cycle_id,meta_json=json.dumps(meta,ensure_ascii=False))
    asyncio.create_task(_run_factory_cycle_to_review(cycle_id,payload.max_ideas,payload.language))
    return {"ok":True,"started":True,"quote":quote,
            "message":"Autopilot started and will stop at the human approval gate.","message_code":"started"}

@app.post("/api/factory-cycles/{cycle_id}/sync")
async def sync_factory_cycle_api(cycle_id:str):
    cycle=sync_factory_cycle(cycle_id,True)
    if not cycle:raise cycle_http_error(404,"Factory cycle not found")
    await broadcast({"type":"factory_cycle","action":"synced","cycleId":cycle_id})
    return {"ok":True,"cycle":cycle}

@app.post("/api/factory-cycles/{cycle_id}/learn")
async def learn_factory_cycle(cycle_id:str):
    try:result=derive_cycle_learning(cycle_id)
    except ValueError as exc:raise cycle_http_error(400,exc)
    if not result.get("ready"):result["reason_code"]=cycle_message_info(result.get("reason"))[0]
    await broadcast({"type":"factory_cycle","action":"learning","cycleId":cycle_id})
    return result

@app.post("/api/factory-cycles/{cycle_id}/target")
async def factory_cycle_target_api(cycle_id:str,payload:FactoryCycleTarget):
    try:cycle=set_factory_cycle_target(cycle_id,payload.model_dump())
    except LookupError as exc:raise cycle_http_error(404,exc)
    except PermissionError as exc:raise cycle_http_error(409,exc)
    except ValueError as exc:raise cycle_http_error(400,exc)
    await broadcast({"type":"factory_cycle","action":"target","cycleId":cycle_id})
    return {"ok":True,"cycle":cycle}

@app.post("/api/factory-cycles/{cycle_id}/stop")
async def factory_cycle_stop_api(cycle_id:str):
    try:result=stop_factory_cycle(cycle_id)
    except LookupError as exc:raise cycle_http_error(404,exc)
    except PermissionError as exc:raise cycle_http_error(409,exc)
    await broadcast({"type":"factory_cycle","action":"stop","cycleId":cycle_id})
    return {"ok":True,**result}

@app.post("/api/factory-cycles/{cycle_id}/resume")
async def factory_cycle_resume_api(cycle_id:str):
    try:cycle=resume_factory_cycle(cycle_id)
    except LookupError as exc:raise cycle_http_error(404,exc)
    except PermissionError as exc:raise cycle_http_error(409,exc)
    await broadcast({"type":"factory_cycle","action":"resume","cycleId":cycle_id})
    return {"ok":True,"cycle":cycle}

@app.post("/api/factory-cycles/{cycle_id}/next")
async def next_factory_cycle(cycle_id:str):
    parent=get_factory_cycle(cycle_id,True)
    if not parent:raise cycle_http_error(404,"Factory cycle not found")
    try:child=create_factory_cycle(FactoryCycleCreate(language=(parent.get("meta") or {}).get("language","English"),parent_cycle_id=cycle_id,
                                                      target=(parent.get("meta") or {}).get("target")))
    except ValueError as exc:raise cycle_http_error(400,exc)
    cycle_event(child["id"],"signals","Next cycle created using the currently active, owner-approved workflow",
                {"parent_cycle_id":cycle_id,"workflow_version_id":child.get("workflow_version_id")})
    await broadcast({"type":"factory_cycle","action":"next","cycleId":child["id"],"parentCycleId":cycle_id})
    return {"ok":True,"cycle":child}

@app.get("/api/approval")
def approval_studio(job_id: Optional[str]=None):
    data=get_approval_queue()
    data["filter"]={"job_id":None,"applied":False,"total_items":len(data["items"])}
    if job_id:
        matched=[x for x in data["items"] if x["job"]["id"]==job_id]
        if matched:
            data["items"]=matched
            data["summary"]["items"]=len(matched)
            data["filter"].update(job_id=job_id,applied=True)
        else:
            # The job selected elsewhere (e.g. "Ready to run") is not in review yet. Filtering to it would show an
            # empty studio next to a non-zero "waiting" counter; show the whole queue and say where that job is.
            job=get_job(job_id)
            data["filter"]["job_id"]=job_id
            if job:
                data["filter"]["selected_job"]={"id":job["id"],"title":job.get("title") or "",
                                                "status":job.get("status") or "","stage":job.get("stage") or ""}
    data["regeneration_quotes"]={x:_estimated_regeneration_cost(x) for x in ("hook","script","caption","voice")}
    return data

@app.get("/api/jobs/{job_id}/approval/history")
def approval_history(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return {"history":get_approval_history(job_id),"variant_diff":get_variant_diff(job_id)}

@app.get("/api/jobs/{job_id}/media-finisher/preview")
def media_finisher_operator_preview(job_id:str):
    if not get_job(job_id):raise HTTPException(404,"Job not found")
    return _media_finisher_operator_preview(job_id)

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

def _publish_approval_gate(item):
    """#238: the last check before any publisher adapter runs. Returns "" when the item carries the current owner
    approval of its own job; otherwise a reason, and nothing is published. Fails closed on missing data."""
    decision_id=str(item.get("approval_decision_id") or "")
    if not decision_id:return "No owner approval is recorded for this publish item"
    con=db()
    try:
        row=con.execute("SELECT job_id,decision FROM approval_decisions WHERE id=?",(decision_id,)).fetchone()
        if not row:return "The owner approval for this publish item was not found"
        if row["job_id"]!=item.get("job_id"):return "The approval belongs to a different job"
        if row["decision"]!="approved":return "The linked owner decision is not an approval"
        latest=con.execute("SELECT id FROM approval_decisions WHERE job_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1",
                           (item.get("job_id"),)).fetchone()
        if not latest or latest["id"]!=decision_id:
            return "The approval is stale: the owner made a newer decision for this job; approve again to publish"
        return ""
    finally:con.close()

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
    con.close()
    refusal=_publish_approval_gate(item)
    if refusal:
        event(item["job_id"],f"Publishing refused: {refusal}")
        return {"ok":False,"approvalRequired":True,"message":refusal}
    con=db()
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

@app.post("/api/publishing/{publish_id}/dry-run")
async def publishing_dry_run(publish_id:str):
    try:return {"ok":True,**await asyncio.to_thread(build_publish_dry_run,publish_id)}
    except LookupError as exc:raise HTTPException(404,str(exc))
    except ValueError as exc:return {"ok":False,"message":str(exc)}

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

@app.post("/api/publishing/{publish_id}/refresh")
async def refresh_publishing_status(publish_id:str):
    result=await asyncio.to_thread(reconcile_metricool_publish,publish_id)
    if result.get("status")=="missing":raise HTTPException(404,"Publish item not found")
    await broadcast({"type":"publishing","publishId":publish_id,"status":result.get("status"),"refresh":True})
    return {"ok":True,**result}

@app.post("/api/publishing/run-due")
async def run_due_publishing():
    where,params=tenancy.sql_filter("publishing_queue.job_id")
    con=db();rows=con.execute(f"""SELECT id,{tenancy.JOB_WORKSPACE_SQL.format(col='publishing_queue.job_id')} AS workspace_key
                                 FROM publishing_queue WHERE status='scheduled' AND scheduled_at<=?{where}
                                 ORDER BY scheduled_at LIMIT 20""",(ts(),*params)).fetchall();con.close()
    results=[]
    for row in rows:
        # T-553: each item publishes under its own workspace identity (bindings + credential fence).
        with tenancy.workspace_scope(row["workspace_key"]):
            results.append({"workspace_key":row["workspace_key"],**(await publish_scheduled_item(row["id"],False))})
    return {"ok":True,"processed":len(results),"results":results}

async def publisher_scheduler_loop():
    while True:
        try:
            await run_due_publishing()
            reconciled=await asyncio.to_thread(reconcile_metricool_publishing)
            if reconciled.get("changed"):
                await broadcast({"type":"publishing","action":"metricool_reconciled",
                                 "changed":reconciled.get("changed"),"processed":reconciled.get("processed")})
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
    if tenancy.binding_workspace()!=tenancy.DEFAULT_WORKSPACE:
        raise HTTPException(503,"Analytics webhook adapter is not configured for this workspace")
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

class IntegrationConnectRequest(BaseModel):
    account_label: Optional[str] = None
    external_account_id: Optional[str] = None

def _integration_public_payload(provider):
    return {"provider":provider,**_portable_connection(provider)}

@app.get("/api/integrations")
def list_integrations():
    return {
        "workspace":tenancy.binding_workspace(),
        "connections":{k:_integration_public_payload(k) for k in PORTABLE_INTEGRATIONS},
        "history_policy":"Disconnecting an account never deletes FactoryOS jobs, artifacts, approvals or analytics.",
        "tenant_scope":"Provider bindings, jobs, artifacts, approvals, publishing queue and analytics are scoped per workspace; server credentials belong to the default workspace only.",
    }

@app.post("/api/integrations/{provider}/disconnect")
async def disconnect_integration(provider: str):
    if provider not in PORTABLE_INTEGRATIONS:raise HTTPException(404,"Unknown integration")
    affected=[provider]
    if provider=="Metricool":
        affected=["Metricool","YouTube","Instagram","TikTok"]
    for name in affected:
        _integration_set(name,"disconnected",auth_mode=PORTABLE_INTEGRATIONS[name]["auth_mode"],
                         connected_via=PORTABLE_INTEGRATIONS[name]["transport"],
                         meta={"reason":"owner_disconnect"})
    event(None,f"Integration disconnected: {provider}" + (" + publishing channels" if provider=="Metricool" else ""))
    await broadcast({"type":"integration","provider":provider,"state":"disconnected"})
    return {"ok":True,"affected":affected,"connection":_integration_public_payload(provider)}

@app.post("/api/integrations/{provider}/connect")
async def connect_integration(provider: str, payload: IntegrationConnectRequest=IntegrationConnectRequest()):
    if provider not in PORTABLE_INTEGRATIONS:raise HTTPException(404,"Unknown integration")
    label=(payload.account_label or "").strip()[:180]
    external_id=(payload.external_account_id or "").strip()[:180]
    if provider=="YouTube" and os.environ.get("FACTORY_OAUTH_GOOGLE_CLIENT_ID","").strip():
        # T-552-YT: a configured Google OAuth client means the channel is connected by OAuth, not via Metricool.
        return {"ok":False,"state":"oauth_redirect","provider":provider,"oauth_provider":"youtube",
                "message":"Continue in Google to connect your YouTube channel."}
    if provider in ("Metricool","YouTube","Instagram","TikTok"):
        if not _metricool_credentials_present():
            return {"ok":False,"state":"needs_setup","provider":provider,
                    "message":"No reusable Metricool workspace credentials are configured. Use Connect another account after OAuth/credential setup."}
        if provider!="Metricool" and _integration_explicitly_disconnected("Metricool"):
            return {"ok":False,"state":"needs_setup","provider":provider,
                    "message":"Metricool transport is disconnected. Reconnect Metricool before enabling social channels."}
        row=_integration_set(provider,"connected",account_label=label or "Current publisher workspace",
                             external_account_id=external_id,auth_mode=PORTABLE_INTEGRATIONS[provider]["auth_mode"],
                             connected_via="metricool",meta={"credential_source":"server_secret"})
        event(None,f"Integration enabled: {provider}")
        await broadcast({"type":"integration","provider":provider,"state":"connected"})
        return {"ok":True,"connection":_integration_public_payload(provider),"binding":bool(row)}
    # HubSpot: ChatGPT's OAuth grant is deliberately not copied into the standalone product.
    return {"ok":False,"state":"needs_oauth","provider":"HubSpot",
            "message":"HubSpot direct login is not configured in FactoryOS yet. The connector slot is ready, but each customer needs a separate OAuth authorization flow."}

@app.post("/api/integrations/disconnect-all")
async def disconnect_all_integrations():
    affected=list(PORTABLE_INTEGRATIONS)
    for name in affected:
        _integration_set(name,"disconnected",auth_mode=PORTABLE_INTEGRATIONS[name]["auth_mode"],
                         connected_via=PORTABLE_INTEGRATIONS[name]["transport"],
                         meta={"reason":"owner_disconnect_all"})
    event(None,"All portable integrations disconnected")
    await broadcast({"type":"integration","provider":"all","state":"disconnected"})
    return {"ok":True,"affected":affected,"history_preserved":True}

@app.post("/api/integrations/{provider}/switch")
async def switch_integration(provider: str):
    if provider not in PORTABLE_INTEGRATIONS:raise HTTPException(404,"Unknown integration")
    await disconnect_integration(provider)
    return {
        "ok":True,"provider":provider,"state":"disconnected","ready_for_new_account":True,
        "next_step":(
            "Authorize a new customer account through provider OAuth."
            if provider=="HubSpot" else
            "Authorize/replace the publisher workspace credentials for the new customer, then press Connect."
        ),
        "history_preserved":True,
    }

# T-551-A: provider OAuth scaffold. No real adapters yet (T-552), so authorize still refuses
# with blockers in production; tests inject mock adapters + memory vault.
# T-560-F: tokens go to the AES-256-GCM vault when FACTORY_VAULT_KEY is configured. Missing or
# malformed key -> UnavailableTokenVault (fail closed); the app still boots.
def _oauth_token_vault():
    from browser_runner.vault import Keyring, VaultConfigError, make_token_vault, vault_paths
    try:
        keyring=Keyring.from_env()
    except VaultConfigError:
        return UnavailableTokenVault()
    if keyring is None:
        return UnavailableTokenVault()
    return make_token_vault(vault_paths(DATA_DIR)["oauth_token"],keyring)

OAUTH_FLOW = OAuthFlow(
    redirect_base=FACTORY_PUBLIC_BASE_URL,
    client_id_lookup=lambda spec: os.environ.get(spec.client_id_env,""),
    vault=_oauth_token_vault(),
    # T-552-YT: real Google transport for YouTube; other providers stay blocked until their adapters exist.
    adapters={"youtube":youtube_publisher.GoogleOAuthAdapter(),"linkedin":linkedin_publisher.LinkedInOAuthAdapter(),
              "olx":olx_publisher.OlxOAuthAdapter()},
)
# T-700: LinkedIn text posts (owner-only draft → approve → publish), off until FACTORY_LINKEDIN_ENABLED=1.
linkedin_publisher.install_routes(app,store=linkedin_publisher.PostStore(DATA_DIR),flow=OAUTH_FLOW,
                                  identity=request_identity,workspace=tenancy.binding_workspace)
# T-701: OLX adverts (owner-only draft → approve → publish), off until FACTORY_OLX_ENABLED=1.
olx_publisher.install_routes(app,store=olx_publisher.AdvertStore(DATA_DIR),flow=OAUTH_FLOW,
                             identity=request_identity,workspace=tenancy.binding_workspace)

# T-702: social autopilot — weekly plan, owner approval (plan / rules opt-in / each), exactly-once scheduled publishing
# to the Telegram channel and LinkedIn. Scheduler does nothing until FACTORY_SOCIAL_AUTOPILOT_ENABLED=1; «Стоп» pauses it.
SOCIAL_TELEGRAM=social_autopilot.TelegramChannelAdapter(
    token=lambda: FACTORY_TELEGRAM_BOT_TOKEN,
    channel=lambda: os.environ.get("FACTORY_TELEGRAM_CHANNEL_ID","").strip())
SOCIAL_AUTOPILOT=social_autopilot.Autopilot(
    social_autopilot.Store(DATA_DIR),
    {"telegram":SOCIAL_TELEGRAM,
     "linkedin":social_autopilot.LinkedInAdapter(OAUTH_FLOW,tenancy.binding_workspace)},
    notify=lambda text: _telegram_send(text),
    ideas=lambda: get_content_brain(limit=200)["ideas"])
social_autopilot.install_routes(app,pilot=SOCIAL_AUTOPILOT,identity=request_identity,telegram=SOCIAL_TELEGRAM)

async def social_autopilot_loop():
    while True:
        try:
            result=await asyncio.to_thread(SOCIAL_AUTOPILOT.tick)
            if any(result.get(k) for k in ("sent","failed","uncertain","missed")):
                print(json.dumps({"event":"SOCIAL_AUTOPILOT_TICK",**{k:len(result.get(k) or []) for k in ("sent","failed","uncertain","missed")}}),flush=True)
            await asyncio.to_thread(SOCIAL_AUTOPILOT.maybe_send_summary)
        except Exception as exc:
            print(json.dumps({"event":"SOCIAL_AUTOPILOT_TICK","status":"error","error":type(exc).__name__}),flush=True)
        await asyncio.sleep(60)

@app.on_event("startup")
async def start_social_autopilot():
    # A claim that never finished before the restart may have been sent: it becomes «uncertain», never resent.
    SOCIAL_AUTOPILOT.store.recover_interrupted()
    asyncio.create_task(social_autopilot_loop())

@app.get("/api/factory/vault/status")
def factory_vault_status(request: Request):
    if (request_identity(request) or {}).get("role")!="owner":
        raise HTTPException(403,"owner_only")
    # Owner-visible: configured or not, algorithm, key ids and record counts. Never key material.
    from browser_runner.vault import vault_status
    out={**vault_status(DATA_DIR),"oauth_vault":OAUTH_FLOW.vault.kind,"secrets_exposed":False,
         "credentials":[],"sessions":[],"workspace":tenancy.binding_workspace()}
    parts=_vault_parts(required=False)
    if parts:
        creds,sessions=parts
        out["credentials"]=list(creds.entries(out["workspace"]))
        out["sessions"]=list(sessions.entries(out["workspace"]))
    return out

# T-560-F UI: owner-only vault management. Secrets go in, never come back out: responses carry
# refs, field kinds, cookie counts and domains only. Workspace comes from the server binding.
_VAULT_SLUG=re.compile(r"^[a-z0-9][a-z0-9_.-]{0,39}$")
_VAULT_ACCOUNT=re.compile(r"^[\w.@+ -]{1,80}$")

def _vault_parts(required=True):
    from browser_runner.sessions import SessionRegistry
    from browser_runner.vault import (EncryptedCredentialVault,EncryptedSessionStore,Keyring,
                                      VaultConfigError,vault_paths)
    try:
        keyring=Keyring.from_env()
    except VaultConfigError:
        keyring=None
    if keyring is None:
        if required:raise HTTPException(409,"vault_not_configured")
        return None
    paths=vault_paths(DATA_DIR)
    return (EncryptedCredentialVault(paths["credential"],keyring),
            EncryptedSessionStore(paths["session"],keyring,SessionRegistry(paths["session_registry"])))

def _vault_owner(request: Request):
    if (request_identity(request) or {}).get("role")!="owner":
        raise HTTPException(403,"owner_only")

def _vault_binding(body: dict):
    provider=str(body.get("provider") or "").strip().lower()
    account=str(body.get("account") or "default").strip()
    if not _VAULT_SLUG.match(provider):raise HTTPException(400,"invalid_provider")
    if not _VAULT_ACCOUNT.match(account):raise HTTPException(400,"invalid_account")
    return tenancy.binding_workspace(),provider,account

@app.post("/api/factory/vault/credentials")
async def factory_vault_save_credential(request: Request):
    _vault_owner(request)
    from browser_runner.sessions import VaultError
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    values={k:str(body.get(k) or "") for k in ("username","password") if body.get(k)}
    creds,_=_vault_parts()
    ref=creds.find_ref(workspace_id=workspace,provider=provider,account_binding_id=account) or f"vault://{secrets.token_hex(16)}"
    try:
        creds.put(ref,workspace_id=workspace,provider=provider,account_binding_id=account,values=values)
    except VaultError as e:
        raise HTTPException(400,str(e))
    event(None,f"Vault: login saved for {provider}/{account}")
    return {"ok":True,"ref":ref,"provider":provider,"account":account,"fields":sorted(values),"secrets_exposed":False}

@app.post("/api/factory/vault/credentials/delete")
async def factory_vault_delete_credential(request: Request):
    _vault_owner(request)
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    creds,_=_vault_parts()
    ref=creds.find_ref(workspace_id=workspace,provider=provider,account_binding_id=account)
    deleted=bool(ref and creds.delete(ref,workspace_id=workspace,provider=provider,account_binding_id=account))
    if deleted:event(None,f"Vault: login deleted for {provider}/{account}")
    return {"ok":deleted,"provider":provider,"account":account}

@app.post("/api/factory/vault/sessions")
async def factory_vault_save_session(request: Request):
    _vault_owner(request)
    from browser_runner.sessions import SessionIsolationError, VaultError
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    state=body.get("storage_state")
    if isinstance(state,str):
        try:state=json.loads(state)
        except ValueError:raise HTTPException(400,"storage_state_not_json")
    if isinstance(state,list):   # a Cookie-Editor / EditThisCookie export from the owner's own Chrome
        from browser_runner.vault import from_cookie_export
        try:state=from_cookie_export(state)
        except Exception as e:raise HTTPException(400,str(e)[:120])
    _,sessions=_vault_parts()
    try:
        sessions.capture(workspace_id=workspace,provider=provider,account_binding_id=account,storage_state=state)
    except (VaultError,SessionIsolationError,ValueError) as e:
        raise HTTPException(400,str(e))
    event(None,f"Vault: browser session saved for {provider}/{account}")
    return {"ok":True,"provider":provider,"account":account,
            **sessions.check(workspace_id=workspace,provider=provider,account_binding_id=account),
            "secrets_exposed":False}

@app.post("/api/factory/vault/sessions/disconnect")
async def factory_vault_disconnect_session(request: Request):
    _vault_owner(request)
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    _,sessions=_vault_parts()
    deleted=sessions.disconnect(workspace_id=workspace,provider=provider,account_binding_id=account)
    if deleted:event(None,f"Vault: browser session removed for {provider}/{account}")
    return {"ok":deleted,"provider":provider,"account":account}

@app.post("/api/factory/vault/sessions/agent-use")
async def factory_vault_session_agent_use(request: Request):
    # T-560-L: owner lets (or stops) MCP agents (ChatGPT, Claude, Gemini via the Surfer) open pages with this login.
    _vault_owner(request)
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    _,sessions=_vault_parts()
    allowed=body.get("allowed") is True
    if not sessions.set_agent_use(workspace_id=workspace,provider=provider,account_binding_id=account,allowed=allowed):
        raise HTTPException(404,"no_session")
    event(None,f"Vault: agents {'may' if allowed else 'may not'} use the browser session {provider}/{account}")
    return {"ok":True,"provider":provider,"account":account,"agent_use":allowed}

@app.post("/api/factory/vault/check")
async def factory_vault_check(request: Request):
    # Proves the stored record decrypts with the current key, without returning any value.
    _vault_owner(request)
    body=await request.json()
    workspace,provider,account=_vault_binding(body)
    creds,sessions=_vault_parts()
    if body.get("kind")=="session":
        return {"kind":"session","provider":provider,"account":account,
                **sessions.check(workspace_id=workspace,provider=provider,account_binding_id=account)}
    ref=creds.find_ref(workspace_id=workspace,provider=provider,account_binding_id=account)
    if not ref:return {"kind":"login","provider":provider,"account":account,"ok":False,"reason":"no_login"}
    return {"kind":"login","provider":provider,"account":account,
            **creds.check(ref,workspace_id=workspace,provider=provider,account_binding_id=account)}

def _oauth_subject(request: Request) -> str:
    identity=request_identity(request) or {}
    return f"{identity.get('role','')}|{identity.get('email','')}|{identity.get('provider','')}"

@app.get("/api/oauth/providers")
def oauth_providers():
    return {"workspace":tenancy.binding_workspace(),"providers":OAUTH_FLOW.public_registry(),"secrets_exposed":False}

@app.post("/api/oauth/{provider}/authorize")
def oauth_authorize(provider: str, request: Request):
    try:
        return {"ok":True,**OAUTH_FLOW.start(provider,tenancy.binding_workspace(),_oauth_subject(request))}
    except OAuthError as e:
        if e.code=="unknown_provider":raise HTTPException(404,"Unknown OAuth provider")
        return JSONResponse({"ok":False,"provider":provider,"state":"not_ready","reason":e.code},status_code=409)

@app.get("/api/oauth/{provider}/callback")
def oauth_callback(provider: str, request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":
        return JSONResponse({"detail":"owner session required"},status_code=403)
    try:
        result=OAUTH_FLOW.complete(provider,dict(request.query_params),_oauth_subject(request))
    except OAuthError as e:
        if e.code=="unknown_provider":raise HTTPException(404,"Unknown OAuth provider")
        event(None,f"OAuth callback rejected: {provider} ({e.code})")
        return RedirectResponse(f"/?{urlparse.urlencode({'oauth':provider,'result':'error','reason':e.code})}",status_code=303)
    _integration_set(result["integration"],"connected",account_label=result["account_label"],
                     external_account_id=result["account_id"],auth_mode="oauth",connected_via="oauth",
                     meta={"oauth_provider":result["provider"],"scopes":result["scopes"],
                           "token_storage":result["token_storage"]["vault"]},
                     workspace_key=result["workspace"])
    event(None,f"OAuth connected: {provider}")
    return RedirectResponse(f"/?{urlparse.urlencode({'oauth':provider,'result':'connected'})}",status_code=303)

@app.post("/api/oauth/{provider}/disconnect")
async def oauth_disconnect(provider: str):
    try:
        result=OAUTH_FLOW.disconnect(provider,tenancy.binding_workspace())
    except OAuthError:
        raise HTTPException(404,"Unknown OAuth provider")
    name=result["integration"]
    _integration_set(name,"disconnected",auth_mode=PORTABLE_INTEGRATIONS[name]["auth_mode"],
                     connected_via="oauth",meta={"reason":"owner_oauth_disconnect","revoke":result["revoke"]})
    event(None,f"OAuth disconnected: {provider} (revoke: {result['revoke']})")
    await broadcast({"type":"integration","provider":name,"state":"disconnected"})
    return {**result,"connection":_integration_public_payload(name)}

@app.get("/api/status")
def status(request: Request=None):
    identity=(request_identity(request) if request is not None else None) or {"role":"owner","email":"","provider":"open"}
    if tenancy.current() is not None:
        return _workspace_status(identity)
    jobs=get_jobs(); sid=current_selected(jobs); selected=next((j for j in jobs if j["id"]==sid),None)
    attention=get_jobs_attention([j["id"] for j in jobs])
    for j in jobs:j["attention"]=attention.get(j["id"])
    con=db(); ev=[dict(x) for x in con.execute("SELECT * FROM events ORDER BY id DESC LIMIT 60").fetchall()]; con.close()
    report = supervisor_runtime.get("last_report") or supervisor_audit(auto_heal=False, persist=False)
    return {
        "factory":"online","version":APP_VERSION,"buildSha":BUILD_SHA,"factoryMcpConfigured":bool(FACTORY_MCP_TOKEN),
        "relay":RELAY_STORE.summary(),
        "auth":{"role":identity.get("role","owner"),"email":identity.get("email",""),"provider":identity.get("provider",""),"readOnly":identity.get("role")=="viewer"},
        "jobs":jobs,"selectedJobId":sid,"selectedJob":selected,
        "selectedJobQuality": get_job_quality(sid) if sid else None,
        "selectedJobWorkerResults": get_job_worker_results(sid),
        "selectedJobHandoffs": get_job_handoffs(sid),
        "selectedJobBrowserRuns": get_job_browser_runs(sid),
        "selectedJobFlow": get_job_flow(sid),
        "selectedJobAgentErrors": get_job_agent_errors(sid),
        "selectedJobErrorCenter": get_job_error_center(sid),
        "selectedJobVariants": get_job_variants(sid),
        "selectedJobContentPackage": get_content_package(sid),
        "mediaAdapters": get_media_adapter_registry(),
        "packageBuilding": list(package_building),
        "events":ev,"connections":get_connection_registry(),"stages":STAGES,
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
        "builderAutopilot": get_repository_autopilot_state(),
        "runtimePolicy": {
            "agent_timeout_seconds":AGENT_TIMEOUT_SECONDS,
            "max_retries":AGENT_MAX_RETRIES,
            "daily_budget_usd":FACTORY_DAILY_BUDGET_USD,
            "job_budget_usd":FACTORY_JOB_BUDGET_USD
        }
    }

def _workspace_status(identity):
    """T-553: member dashboard state — only this workspace's jobs/events/summaries, no operator telemetry."""
    workspace=tenancy.current()
    jobs=get_jobs(); sid=current_selected(jobs); selected=next((j for j in jobs if j["id"]==sid),None)
    where,params=tenancy.sql_filter("events.job_id")
    con=db(); ev=[dict(x) for x in con.execute(f"SELECT * FROM events WHERE job_id IS NOT NULL{where} ORDER BY id DESC LIMIT 60",params).fetchall()]; con.close()
    return {
        "factory":"online","version":APP_VERSION,"workspace":workspace,
        "auth":{"role":identity.get("role"),"email":identity.get("email",""),"provider":identity.get("provider",""),
                "workspace":workspace,"readOnly":False},
        "jobs":jobs,"selectedJobId":sid,"selectedJob":selected,
        "selectedJobQuality": get_job_quality(sid) if sid else None,
        "selectedJobVariants": get_job_variants(sid),
        "selectedJobContentPackage": get_content_package(sid),
        "events":ev,"stages":STAGES,"nextAction":next_action(selected),
        "connections":{k:_integration_public_payload(k) for k in PORTABLE_INTEGRATIONS},
        "approvalSummary": _approval_summary(),
        "publishingSummary": _publishing_summary(),
        "performanceSummary": _performance_summary(),
        "runningJobs":[j["id"] for j in jobs if j["id"] in running_jobs],
    }

@app.get("/api/workspace")
def current_workspace(request: Request):
    identity=request_identity(request) or {}
    scope=tenancy.current()
    return {"workspace":scope or tenancy.DEFAULT_WORKSPACE,"scoped":scope is not None,
            "role":identity.get("role"),"all_workspaces_visible":scope is None}

@app.get("/api/workspaces")
def list_workspaces():
    """Owner/admin observability across tenants: counts only, no content."""
    con=db()
    jobs=con.execute(f"SELECT {tenancy.JOB_WORKSPACE_SQL.format(col='jobs.id')} AS w,COUNT(*) c FROM jobs GROUP BY w").fetchall()
    pubs=con.execute(f"SELECT {tenancy.JOB_WORKSPACE_SQL.format(col='publishing_queue.job_id')} AS w,COUNT(*) c FROM publishing_queue GROUP BY w").fetchall()
    bindings=con.execute("SELECT workspace_key w,COUNT(*) c FROM integration_accounts WHERE state='connected' GROUP BY w").fetchall()
    con.close()
    out={}
    for key,rows in (("jobs",jobs),("publish_items",pubs),("connected_integrations",bindings)):
        for row in rows:out.setdefault(row["w"],{"workspace":row["w"],"jobs":0,"publish_items":0,"connected_integrations":0})[key]=row["c"]
    members={}
    for email,workspace in FACTORY_WORKSPACE_MEMBERS.items():members[workspace]=members.get(workspace,0)+1
    for workspace,count in members.items():
        out.setdefault(workspace,{"workspace":workspace,"jobs":0,"publish_items":0,"connected_integrations":0})["members"]=count
    return {"workspaces":sorted(out.values(),key=lambda x:x["workspace"]),"default":tenancy.DEFAULT_WORKSPACE}

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
    scope=tenancy.current()
    try:workspace=tenancy.normalize_workspace(j.workspace_key or scope or tenancy.DEFAULT_WORKSPACE)
    except ValueError as exc:raise HTTPException(400,str(exc))
    if scope is not None and workspace!=scope:raise HTTPException(403,"Jobs can only be created in your own workspace")
    jid=str(uuid.uuid4()); con=db()
    con.execute("INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (jid,j.title,j.brief,"inbox",j.presenter,j.format,j.language,j.outputs,"idle",0,ts(),ts()))
    assign_job_workspace(con,jid,workspace)
    con.commit(); con.close(); event(jid,f"Created: {j.title}")
    _set_selected_job(jid)
    await broadcast(); return {"id":jid,"workspace_key":workspace}

@app.post("/api/jobs/{job_id}/select")
async def select_job(job_id:str):
    if not any(j["id"]==job_id for j in get_jobs()): raise HTTPException(404,"Job not found")
    _set_selected_job(job_id); await broadcast(); return {"ok":True}

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
    asyncio.create_task(run_in_job_workspace(job_id,run_until_review(job_id)))
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
async def rerun_agent(job_id:str,agent_name:str,expected_run_id:Optional[str]=None,confirm_uncertain:bool=False):
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
    asyncio.create_task(run_in_job_workspace(job_id,rerun_single_agent(job_id,agent_name,stage)))
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

@app.get("/api/browser-runs")
def browser_runs(job_id:str, limit:int=10):
    return {"job_id":job_id,"runs":get_job_browser_runs(job_id,limit)}

@app.get("/api/browser-runs/{artifact_id}")
def browser_run_trace(artifact_id:str):
    run=get_browser_run(artifact_id)
    if not run:
        raise HTTPException(404,"Browser run not found")
    return run



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
    rows=[row for row in rows if _recent_edit_timestamp(row["updated_at"],360) and not _is_media_finisher_pilot_request(row["request_json"])
          and str((_decode_json(row["request_json"] or "{}",{})).get("compute_target") or "")!="local"]
    checked=durable=0
    for row in rows:
        try:
            if durable_finisher.active(row["id"]):
                durable+=1;continue  # T-612: its DBOS workflow waits for the callback and polls; never double-poll.
            if not str(row["provider_job_id"] or "").strip():
                _spawn_media_finisher_submit(row["id"])
            else:
                refresh_edit_job(row["id"])
            checked+=1
        except Exception as exc:
            print(json.dumps({"event":"MEDIA_FINISHER_STATUS_RECOVERY_ERROR","edit_job_id":row["id"],"error":str(exc)[:400]}),flush=True)
    if rows:print(json.dumps({"event":"MEDIA_FINISHER_STATUS_RECOVERY","active":len(rows),"checked":checked,"durable":durable}),flush=True)

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
        if request.get("compute_target")=="local":continue
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
        if request.get("compute_target")=="local":continue
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
    rows=[row for row in rows if _recent_edit_timestamp(row["updated_at"],120) and not _is_media_finisher_pilot_request(row["request_json"])
          and str((_decode_json(row["request_json"] or "{}",{})).get("compute_target") or "")!="local"]
    for row in rows:_spawn_media_finisher_submit(row["id"])
    _recover_recent_real_media_failures()
    _recover_recent_failed_asr_jobs()
    _recover_ready_durable_media()
    inventory=_durable_media_inventory()
    inventory_status="ready" if inventory["checked"] and inventory["missing"]==0 else ("empty" if not inventory["checked"] else "degraded")
    print(json.dumps({"event":"DURABLE_MEDIA_INVENTORY","status":inventory_status,**inventory}),flush=True)
    threading.Thread(target=_media_finisher_watchdog_loop,daemon=True,name="finisher-watchdog").start()
    if rows:print(json.dumps({"event":"MEDIA_FINISHER_SUBMIT_RECOVERY","queued":len(rows)}),flush=True)


@app.get("/api/factory/claude-code/status")
def claude_code_owner_status(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_claude_code_status()

@app.get("/api/factory/claude-code/worker-token")
def claude_code_worker_token(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return {"token":FACTORY_CLAUDE_WORKER_TOKEN,"factory_url":FACTORY_PUBLIC_BASE_URL,
            "note":"Use only on the trusted machine running Claude Code. Do not commit this token."}

@app.post("/api/factory/claude-code/pair-token")
def claude_code_pair_token(request: Request):
    identity = request_identity(request) or {}
    if identity.get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    # Secret is returned ONCE through the authenticated HTTPS response.
    # Do not print, log, email or include it in history/status endpoints.
    return {**create_pairing(RELAY_WORKER_PAIR_FILE),
            "environment_key": "FACTORY_CLAUDE_WORKER_TOKEN",
            "note": "Copy this token into /etc/factoryos/claude-worker.env on the existing EC2. Do not paste it into a chat."}


@app.get("/api/factory/claude-code/pair-token/status")
def claude_code_pair_token_status(request: Request):
    identity = request_identity(request) or {}
    if identity.get("role") != "owner":
        raise HTTPException(403, "Owner access required")
    return pairing_status(RELAY_WORKER_PAIR_FILE)


@app.post("/api/claude-worker/heartbeat")
def claude_worker_heartbeat(payload: ClaudeWorkerHeartbeat):
    claude_worker_runtime["last_seen"]=time.time()
    node=payload.model_dump()
    node["supervisor"]=sanitize_supervisor(node.get("supervisor"))
    claude_worker_runtime["telemetry"]=sanitize_telemetry(node.pop("telemetry",None))
    claude_worker_runtime["node"]=node
    claude_worker_runtime["active_task_id"]=payload.task_id or ""
    claude_worker_runtime["last_error"]=payload.last_error or ""
    _persist_claude_worker_heartbeat()
    return {"ok":True,**get_claude_code_status()}

@app.post("/api/claude-worker/task-result")
def claude_worker_task_result(payload: ClaudeWorkerTaskResult):
    return {"ok":True,"result":ingest_claude_worker_result(payload)}

@app.post("/api/operator-worker/heartbeat")
def operator_worker_heartbeat(payload: OperatorWorkerHeartbeat, request: Request = None):
    op=(payload.operator_id or "").strip().lower()
    if op not in ("claude","gemini"):raise HTTPException(422,"Unsupported operator")
    # The middleware already admitted either the operator token or the Gemini token; the latter reports only gemini.
    if request is not None and not _operator_worker_authorized(request) and op!="gemini":
        raise HTTPException(403,"The Gemini worker token reports only the gemini lane")
    data=payload.model_dump()
    data["operator_id"]=op
    data["last_seen"]=time.time()
    data["tickets"]=[x for x in (data.get("tickets") or []) if isinstance(x,dict)][:20]
    with _operator_worker_lock:
        operator_worker_runtime[op]=data
    return {"ok":True,"lane":get_operator_lanes()[op]}

@app.get("/api/factory/operators/runtime")
def factory_operator_runtime(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return {"operators":get_operator_lanes()}

@app.get("/api/local-booster/status")
def local_booster_status():
    return {"online":_local_booster_online(),"ttl_seconds":FACTORY_LOCAL_BOOSTER_TTL_SECONDS,
            "last_seen":local_booster_runtime.get("last_seen") or 0,"node":local_booster_runtime.get("node") or {},
            "active_job_id":local_booster_runtime.get("active_job_id") or "","last_error":local_booster_runtime.get("last_error") or ""}

@app.get("/api/local-booster/token")
def local_booster_pairing_token():
    return {"token":FACTORY_LOCAL_BOOSTER_TOKEN,"factory_url":FACTORY_PUBLIC_BASE_URL}

@app.get("/api/local-booster/package.zip")
def local_booster_package():
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as zf:
        for folder_name in ("media_finisher_worker","local_booster"):
            root=BASE/folder_name
            if not root.exists():
                continue
            for path in root.rglob("*"):
                if not path.is_file() or "__pycache__" in path.parts or path.suffix in (".pyc",".pyo"):
                    continue
                zf.write(path,path.relative_to(BASE).as_posix())
    payload=buf.getvalue()
    return Response(payload,media_type="application/zip",headers={
        "Content-Disposition":'attachment; filename="factoryos-local-booster-v1.zip"',
        "Cache-Control":"no-store"
    })

@app.post("/api/local-booster/heartbeat")
def local_booster_heartbeat(payload:LocalBoosterHeartbeat):
    local_booster_runtime["last_seen"]=time.time()
    local_booster_runtime["node"]=payload.model_dump()
    return {"ok":True,**local_booster_status()}

@app.post("/api/local-booster/claim")
def local_booster_claim(payload:LocalBoosterHeartbeat):
    local_booster_runtime["last_seen"]=time.time();local_booster_runtime["node"]=payload.model_dump()
    with _local_booster_claim_lock:
        con=db();rows=con.execute("""SELECT * FROM edit_jobs WHERE status='queued' AND COALESCE(provider_job_id,'')=''
                                    ORDER BY created_at ASC LIMIT 30""").fetchall();con.close()
        chosen=None
        for row in rows:
            item=_edit_job_dict(row,False);req=item.get("request") or {};resp=item.get("response") or {}
            if str(req.get("compute_target") or "")=="local" and str(resp.get("stage") or "")=="waiting_local_booster":
                chosen=item;break
        if not chosen:return {"ok":True,"job":None}
        response=dict(chosen.get("response") or {})
        response.update({"status":"processing","stage":"local_claimed","percent":2,"compute_target":"local",
                         "local_node":payload.model_dump(),"claimed_at":ts()})
        con=db();con.execute("""UPDATE edit_jobs SET status='processing',provider='local-booster',response_json=?,updated_at=?
                               WHERE id=? AND status='queued'""",(json.dumps(response,ensure_ascii=False),ts(),chosen["id"]));con.commit();con.close()
        local_booster_runtime["active_job_id"]=chosen["id"]
        req=dict(chosen.get("request") or {});req["callback_url"]=""
        event(chosen["production_job_id"],f"Local Render Booster claimed Media Finisher job {chosen['id'][:8]}")
        req["workspace_key"]=job_workspace_key(chosen["production_job_id"])
        return {"ok":True,"job":{"id":chosen["id"],"production_job_id":chosen["production_job_id"],
                                 "workspace_key":req["workspace_key"],"request":req}}

@app.post("/api/local-booster/{edit_job_id}/progress")
async def local_booster_progress(edit_job_id:str,payload:LocalBoosterProgress):
    item=get_edit_job(edit_job_id)
    if not item:raise HTTPException(404,"Edit job not found")
    local_booster_runtime["last_seen"]=time.time();local_booster_runtime["active_job_id"]=edit_job_id
    response=dict(item.get("response") or {})
    response.update({"status":payload.status,"stage":payload.stage,"percent":max(0,min(100,int(payload.percent))),
                     "compute_target":"local","local_detail":payload.detail or {}})
    con=db();con.execute("UPDATE edit_jobs SET status=?,error=?,response_json=?,updated_at=? WHERE id=?",
                         ("failed" if payload.status=="failed" else "processing",str(payload.error or ""),
                          json.dumps(response,ensure_ascii=False,default=str),ts(),edit_job_id));con.commit();con.close()
    if payload.status=="failed":
        local_booster_runtime["last_error"]=str(payload.error or "")[:500];local_booster_runtime["active_job_id"]=""
    await broadcast({"type":"media_finisher","action":"local_progress","editJobId":edit_job_id,"status":payload.status})
    return {"ok":True}

async def _store_local_booster_media(edit_job_id:str,upload:UploadFile,component:str,index:int=0):
    filename=Path(upload.filename or ("final.mp4" if component=="final_render" else f"short-{index:02d}.mp4")).name
    ext=Path(filename).suffix.lower()
    if ext not in {".mp4",".mov",".m4v",".webm"}:ext=".mp4"
    archive_id=str(uuid.uuid5(uuid.NAMESPACE_URL,f"factoryos:local-booster:{edit_job_id}:{component}:{index}"))
    stored_name=archive_id+ext;dest=MEDIA_ARCHIVE_DIR/stored_name;total=0;digest=hashlib.sha256()
    try:
        with dest.open("wb") as fh:
            while True:
                chunk=await upload.read(1024*1024)
                if not chunk:break
                total+=len(chunk)
                if total>FACTORY_MEDIA_ARCHIVE_MAX_BYTES:raise HTTPException(413,"Local Booster output exceeds durable archive limit")
                fh.write(chunk);digest.update(chunk)
    finally:
        await upload.close()
    if total<1024:
        if dest.exists():dest.unlink()
        raise HTTPException(400,"Local Booster output is empty")
    meta={"archive_id":archive_id,"edit_job_id":edit_job_id,"component":component,"clip_index":index,
          "stored_name":stored_name,"filename":filename,"content_type":"video/mp4","bytes":total,
          "sha256":digest.hexdigest(),"created_at":ts(),"source":"local_render_booster"}
    (MEDIA_ARCHIVE_DIR/f"{archive_id}.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    token=_media_archive_signature(archive_id)
    return f"{FACTORY_PUBLIC_BASE_URL}/media-archive/{archive_id}?token={urlparse.quote(token,safe='')}"

@app.post("/api/local-booster/{edit_job_id}/complete")
async def local_booster_complete(edit_job_id:str,final_file:UploadFile=File(...),report_json:str=Form("{}"),
                                 wall_duration_sec:float=Form(0),shorts:list[UploadFile]=File(default=[])):
    item=get_edit_job(edit_job_id)
    if not item:raise HTTPException(404,"Edit job not found")
    try:report=json.loads(report_json or "{}")
    except Exception:raise HTTPException(400,"Invalid report_json")
    final_url=await _store_local_booster_media(edit_job_id,final_file,"final_render",0)
    clips=(((report or {}).get("shorts_manifest") or {}).get("clips") or [])
    for i,upload in enumerate(shorts or [],1):
        url=await _store_local_booster_media(edit_job_id,upload,"short_render",i)
        if i<=len(clips) and isinstance(clips[i-1],dict):clips[i-1]["url"]=url
        else:clips.append({"index":i,"url":url,"targets":["youtube_shorts","instagram_reels"]})
    if clips:
        report.setdefault("shorts_manifest",{})["clips"]=clips
        report["shorts_manifest"]["enabled"]=True
    response={"status":"ready","stage":"done","percent":100,"compute_target":"local",
              "local_node":local_booster_runtime.get("node") or {}}
    result=_finalize_edit_job(edit_job_id,"ready",final_url,f"local:{(local_booster_runtime.get('node') or {}).get('node_id','pc')}",
                              "",response,report,0.0,float(wall_duration_sec or 0))
    _set_media_archive_state(edit_job_id,"ready",items=[{"url":final_url,"source":"local_booster"}])
    local_booster_runtime["active_job_id"]="";local_booster_runtime["last_seen"]=time.time();local_booster_runtime["last_error"]=""
    await broadcast({"type":"media_finisher","action":"local_complete","editJobId":edit_job_id,"status":"ready"})
    return {"ok":True,"edit_job":result}

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
    # T-612: wake the durable workflow now instead of at its next poll; a no-op when no workflow owns this job. The result is
    # already saved, so a wake-up failure must not fail the worker's callback: the workflow's next poll reads the result.
    try:await asyncio.to_thread(durable_finisher.notify,edit_job_id,{"status":item["status"]})
    except Exception as exc:
        print(json.dumps({"event":"DBOS_MEDIA_FINISHER_NOTIFY_ERROR","edit_job_id":edit_job_id,"error":str(exc)[:300]}),flush=True)
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
    package_building.add(job_id);asyncio.create_task(run_in_job_workspace(job_id,_manual_package_build(job_id)))
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
    running_jobs.add(job_id);con=db();con.execute("UPDATE jobs SET stage='script',status='running',progress=?,updated_at=? WHERE id=?",(int(STAGES.index("script")/(len(STAGES)-1)*100),ts(),job_id));con.commit();con.close();asyncio.create_task(run_in_job_workspace(job_id,_manual_variant_build(job_id)));await broadcast();return {"ok":True,"message":"Production variant build started"}

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

_ROADMAP_META_KEYS={"planner":"planner","parent":"parent","depends":"depends","goal":"goal","done":"done_criteria",
                    "need":"need","progress":"progress","owner":"owner"}
_ROADMAP_TEXT_KEYS=("goal","done_criteria","need","progress")

def _parse_roadmap_tasks(text=None):
    roadmap_path=BASE/"ROADMAP.md"
    tasks=[]
    current_version=""
    last_key=""
    if text is None and roadmap_path.exists():text=roadmap_path.read_text(encoding="utf-8")
    if text:
        for line_no,raw in enumerate(text.splitlines(),1):
            line=raw.strip()
            if line.startswith("## "):
                current_version=line[3:].strip();last_key=""
                continue
            match=re.match(r"- \[([ xX])\]\s+(\[HUMAN\]\s+)?(T-[A-Za-z0-9-]+)\s+(.+)",line)
            if not match:
                if not (tasks and line and raw[:1].isspace()):
                    last_key=""
                    continue
                meta=re.match(r"(Planner|Parent|Depends|Goal|DONE|Need|Progress|Owner):\s*(.*)",line)
                if meta:
                    key,value=_ROADMAP_META_KEYS[meta.group(1).lower()],meta.group(2).strip()
                    if key=="depends":tasks[-1]["depends"]=[x.strip() for x in value.split(",") if re.match(r"^T-[A-Za-z0-9-]+$",x.strip())]
                    elif key=="owner":tasks[-1]["owner"]=(value.split()[0].lower() if value else "")
                    else:tasks[-1][key]=value
                    last_key=key
                elif last_key in _ROADMAP_TEXT_KEYS:
                    tasks[-1][last_key]=(tasks[-1][last_key]+" "+line).strip()
                continue
            last_key=""
            tasks.append({
                "id":match.group(3),
                "title":match.group(4).strip(),
                "done":match.group(1).lower()=="x",
                "human":bool(match.group(2)),
                "version":current_version,
                "planner":"",
                "parent":"",
                "depends":[],
                "goal":"",
                "done_criteria":"",
                "need":"",
                "progress":"",
                "owner":"",
                "roadmap_line":line_no,
            })
    for task in tasks:
        task["source"]=task["planner"] or "roadmap"
        task["provenance"]="planner" if task["planner"] else "legacy"
    return tasks

def _roadmap_task_tree(queue):
    """Nest ROADMAP tasks under their declared Parent; unknown parents and cycles fall back to roots."""
    by_id={x["id"]:x for x in queue}
    children={}
    for task in queue:
        if task["parent"] in by_id and task["parent"]!=task["id"]:children.setdefault(task["parent"],[]).append(task["id"])
    placed=set()
    def node(task_id,depth,trail):
        placed.add(task_id)
        task=by_id[task_id]
        kids=[node(c,depth+1,trail|{c}) for c in children.get(task_id,[]) if c not in trail and c not in placed]
        return {"id":task_id,"title":task["title"],"state":task["state"],"source":task["source"],"provenance":task["provenance"],
                "planner":task["planner"],"parent":task["parent"],"depends":task["depends"],"goal":task["goal"],
                "done_criteria":task["done_criteria"],"queue_position":task["queue_position"],"depth":depth,
                "children_done":sum(1 for k in kids if k["state"]=="done"),"children_total":len(kids),"children":kids}
    roots=[]
    for task in queue:
        if task["id"] in placed:continue
        if task["parent"] in by_id and task["parent"]!=task["id"] and not _roadmap_parent_cycle(task["id"],by_id):continue
        roots.append(node(task["id"],0,{task["id"]}))
    for task in queue:
        if task["id"] not in placed:roots.append(node(task["id"],0,{task["id"]}))
    return roots

def _roadmap_parent_cycle(task_id,by_id):
    seen={task_id};current=by_id[task_id]["parent"]
    while current in by_id:
        if current in seen:return True
        seen.add(current);current=by_id[current]["parent"]
    return False

def _redact_board_value(value, secret_values):
    if isinstance(value,dict):return {k:_redact_board_value(v,secret_values) for k,v in value.items()}
    if isinstance(value,list):return [_redact_board_value(v,secret_values) for v in value]
    if not isinstance(value,str):return value
    value=re.sub(r"(?i)\b(https?://)[^/\s:@]+(?::[^/\s@]*)?@",r"\1",value)
    for secret in secret_values:value=value.replace(secret,"[redacted]")
    return value

_DELEGATION_NODE_FIELDS=("node_id","hostname","platform","claude_version","auth_mode","subscription","branch","repo","status","supervisor")
_DELEGATION_RESULT_FIELDS=("task_id","result","branch","summary","need","checks","commit","commit_count","files","exit_code",
                           "timed_out","duration_seconds","violations","received_at","started_at","pushed")
_TIMELINE_AFTER_PICK=("checks","commit","push","outcome")

def _timeline_ts(value, upper):
    """Accept only a plausible epoch timestamp observed no later than `upper` (+60 s clock skew)."""
    if isinstance(value,bool) or not isinstance(value,(int,float)) or value!=value or value<=0 or value==float("inf"):return None
    return float(value) if value<=float(upper)+60 else None

def _timeline_event(kind, status, source=None, at=None, **detail):
    return {"kind":kind,"status":status,"source":source,"at":at,**detail}

def _commit_url(sha):
    if not re.match(r"^[0-9a-f]{7,40}$",sha or "") or not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",GITHUB_REPO or ""):return None
    return f"https://github.com/{GITHUB_REPO}/commit/{sha}"

def build_delegation_timeline(task, attempts, telemetry=None, now=None):
    """Factual lifecycle of one board task: queued -> picked -> running -> checks -> commit -> push -> outcome.

    Only reported evidence becomes an `observed` event. Everything else is `unavailable` (expected but never
    reported), `pending` (not reached yet) or `skipped` (the run ended blocked/failed first). Nothing is inferred.
    """
    now=time.time() if now is None else now
    telemetry=telemetry or {}
    latest=attempts[-1] if attempts else None
    events=[_timeline_event("queued","observed","roadmap",roadmap_line=task.get("roadmap_line"))]
    if task.get("state")=="running":
        phase="running"
        started=_timeline_ts(telemetry.get("task_started_at"),now) if telemetry.get("stage")=="running" else None
        events+=[_timeline_event("picked","observed","heartbeat",started),
                 _timeline_event("running","observed","heartbeat",started,stage=telemetry.get("stage"),
                                 elapsed_seconds=telemetry.get("elapsed_seconds") if started else None)]
        events+=[_timeline_event(k,"pending") for k in _TIMELINE_AFTER_PICK]
    elif latest:
        phase="result"
        result=str(latest.get("result") or "failed")
        ended=result in {"blocked","failed"}
        received=_timeline_ts(latest.get("received_at"),now)
        started=_timeline_ts(latest.get("started_at"),received or now)
        events+=[_timeline_event("picked","observed","worker_result",started),
                 _timeline_event("running","observed","worker_result",started,duration_seconds=latest.get("duration_seconds"),
                                 exit_code=latest.get("exit_code"),timed_out=bool(latest.get("timed_out")))]
        checks=[str(x) for x in (latest.get("checks") or [])]
        # Workers report the commands they ran, not a per-command verdict, so per-check pass/fail stays None.
        events.append(_timeline_event("checks","observed","worker_result",items=[{"command":c,"passed":None} for c in checks])
                      if checks else _timeline_event("checks","skipped" if ended else "unavailable"))
        sha=str(latest.get("commit") or "")
        if re.match(r"^[0-9a-f]{7,40}$",sha):
            files=[str(x) for x in (latest.get("files") or [])]
            events.append(_timeline_event("commit","observed","worker_result",sha=sha,url=_commit_url(sha),
                                          commit_count=latest.get("commit_count"),files=files,file_count=len(files)))
        else:
            events.append(_timeline_event("commit","skipped" if ended else "unavailable"))
        if latest.get("pushed"):
            events.append(_timeline_event("push","observed","worker_result",violation=True))
        else:
            # The runner pushes after reporting; FactoryOS never observes that push, so it is not claimed.
            events.append(_timeline_event("push","skipped" if ended and not re.match(r"^[0-9a-f]{7,40}$",sha) else "unavailable"))
        events.append(_timeline_event("outcome","observed","worker_result",received,result=result,summary=latest.get("summary") or "",
                                      need=latest.get("need") or "",violations=list(latest.get("violations") or [])))
    elif task.get("done"):
        phase="roadmap"
        events+=[_timeline_event(k,"unavailable") for k in ("picked","running","checks","commit","push")]
        events.append(_timeline_event("outcome","observed","roadmap",result="done"))
    else:
        phase="queued"
        events+=[_timeline_event(k,"pending") for k in ("picked","running")+_TIMELINE_AFTER_PICK]
    return {"task_id":task["id"],"phase":phase,"attempts":len(attempts),"events":events}

def get_delegation_operator_lanes(worker,results,queue):
    """T-585: Claude / Gemini / ChatGPT lanes from observed heartbeats, verified results and Relay runs only."""
    roles=get_role_operator_board()
    assigned={}
    for role in roles["roles"]:
        if role["assigned_operator"]!="auto":assigned.setdefault(role["assigned_operator"],[]).append(role["id"])
    with _operator_worker_lock:
        runners={k:dict(v) for k,v in operator_worker_runtime.items() if isinstance(v,dict)}
    return build_operator_lanes(runners=runners,runner_ttl=FACTORY_OPERATOR_WORKER_TTL_SECONDS,claude_worker=worker,
                                claude_results=results,lane_board=get_lane_board(),
                                provider_status={o["id"]:o["status"] for o in roles["operators"]},
                                task_titles={x["id"]:x["title"] for x in queue},assigned_roles=assigned)

def get_delegation_board():
    """Owner-safe read model: ROADMAP queue + Claude worker state + verified results. Never returns tokens."""
    tasks=_parse_roadmap_tasks()
    worker=get_claude_code_status()
    online=bool(worker["online"])
    last_seen=float(worker["last_seen"] or 0)
    active_task_id=str(worker["active_task_id"] or "")
    results=[{k:r.get(k) for k in _DELEGATION_RESULT_FIELDS} for r in _load_claude_worker_results() if isinstance(r,dict)]
    latest_result={}
    for r in results:latest_result[str(r.get("task_id") or "")]=r
    done_ids={x["id"] for x in tasks if x["done"]}
    queue=[];position=0
    for task in tasks:
        latest=latest_result.get(task["id"])
        latest_state=str((latest or {}).get("result") or "")
        if task["done"]:state,source="done","roadmap"
        elif latest_state=="done":state,source="done","worker_result"
        elif task["human"]:state,source="human","roadmap"
        elif online and active_task_id==task["id"]:state,source="running","heartbeat"
        elif latest_state in {"blocked","failed"}:state,source="blocked","worker_result"
        else:state,source="queued","roadmap"
        if state=="queued":position+=1
        queue.append({**task,"state":state,"state_source":source,"queue_position":position if state=="queued" else None,
                      "dependencies_met":all(d in done_ids for d in task["depends"]),
                      "unmet_dependencies":[d for d in task["depends"] if d not in done_ids],"latest_result":latest})
    counts={key:sum(1 for x in queue if x["state"]==key) for key in ("done","running","queued","blocked","human")}
    counts["total"]=len(queue)
    counts["safe_remaining"]=counts["running"]+counts["queued"]+counts["blocked"]
    connection="online" if online else ("stale" if last_seen else "offline")
    board={
        "planner_queue":queue,
        "hierarchy":[{"parent":p,"parent_is_task":p in {x["id"] for x in tasks},
                      "children":[c["id"] for c in queue if c["parent"]==p],
                      "done":sum(1 for c in queue if c["parent"]==p and c["state"]=="done"),
                      "total":sum(1 for c in queue if c["parent"]==p)}
                     for p in dict.fromkeys(x["parent"] for x in tasks if x["parent"])],
        "tree":_roadmap_task_tree(queue),
        "provenance":{key:sum(1 for x in tasks if x["source"]==key) for key in dict.fromkeys(x["source"] for x in tasks)},
        "timelines":{x["id"]:build_delegation_timeline(x,[r for r in results if r.get("task_id")==x["id"]],worker.get("telemetry"))
                     for x in queue if x["state"]!="human"},
        "worker":{
            "connection":connection,
            "online":online,
            "ttl_seconds":worker["ttl_seconds"],
            "last_seen":last_seen or None,
            "heartbeat_age_seconds":round(max(0.0,time.time()-last_seen),1) if last_seen else None,
            "active_task_id":active_task_id or None,
            "last_error":worker["last_error"] or "",
            "node":{k:worker["node"].get(k) for k in _DELEGATION_NODE_FIELDS if k in worker["node"]},
            "telemetry":worker.get("telemetry") or None,
        },
        "active_task":next((x for x in queue if x["id"]==active_task_id),None) if active_task_id else None,
        "next_task":next((x for x in queue if x["state"]=="queued"),None),
        "recent_results":results[-10:],
        "counts":counts,
        "controls":get_delegation_control_view(queue,{"online":online,"active_task_id":active_task_id}),
        "safety":{"secrets_returned":False,"main_push_forbidden":True,"production_direct_deploy_forbidden":True,
                  "human_publish_approval_required":True},
    }
    board["operator_lanes"]=get_delegation_operator_lanes(board["worker"],results,queue)
    secret_values=[s for s in (FACTORY_CLAUDE_WORKER_TOKEN,FACTORY_CLAUDE_WORKER_TOKEN_EC2,FACTORY_OPERATOR_WORKER_TOKEN,FACTORY_TELEGRAM_BOT_TOKEN,GITHUB_TOKEN,GITHUB_READ_TOKEN,FACTORY_MCP_TOKEN,FACTORY_LLM_API_KEY,
                               FACTORY_SECRET,FACTORY_PASSWORD,FACTORY_LOCAL_BOOSTER_TOKEN,FACTORY_PUBLISHER_TOKEN,FACTORY_METRICOOL_TOKEN,
                               FACTORY_ANALYTICS_TOKEN,FACTORY_MEDIA_FINISHER_TOKEN,FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN,
                               FACTORY_VIEWER_INVITE_TOKEN) if s and len(s)>=8]
    return _redact_board_value(board,sorted(secret_values,key=len,reverse=True))

def get_repository_autopilot_state():
    roadmap_path=BASE/"ROADMAP.md"
    status_path=BASE/".autopilot"/"status.json"
    decisions_path=BASE/"DECISIONS.md"
    tasks=_parse_roadmap_tasks()
    pending=[x for x in tasks if not x["done"]]
    safe_pending=[x for x in pending if not x["human"]]
    human_pending=[x for x in pending if x["human"]]
    runtime={"status":"idle","task":"","summary":"","need":"","checks":[],"commit":""}
    if status_path.exists():
        runtime=_decode_json(status_path.read_text(encoding="utf-8"),runtime)
        if not isinstance(runtime,dict):
            runtime={"status":"invalid","task":"","summary":"Autopilot status is not a JSON object","need":"","checks":[],"commit":""}
    decisions=[]
    if decisions_path.exists():
        block=[]
        for raw in decisions_path.read_text(encoding="utf-8").splitlines():
            if raw.startswith("## "):
                if block:decisions.append("\n".join(block).strip())
                block=[raw[3:].strip()]
            elif block:
                block.append(raw)
        if block:decisions.append("\n".join(block).strip())
    return {
        "enabled":roadmap_path.exists() and (BASE/"CLAUDE.md").exists(),
        "runner_present":(BASE/"autopilot"/"autopilot.py").exists(),
        "roadmap_present":roadmap_path.exists(),
        "total":len(tasks),
        "done":sum(1 for x in tasks if x["done"]),
        "pending":len(pending),
        "safe_pending":len(safe_pending),
        "human_pending":len(human_pending),
        "progress":round((sum(1 for x in tasks if x["done"])/len(tasks))*100,1) if tasks else 0,
        "next_task":safe_pending[0] if safe_pending else None,
        "next_human":human_pending[0] if human_pending else None,
        "runtime":runtime,
        "recent_decisions":decisions[-5:],
        "safety":{
            "main_push_forbidden":True,
            "production_direct_deploy_forbidden":True,
            "human_publish_approval_required":True,
            "paid_calls_auto_enabled":False,
        },
    }

@app.get("/api/factory/autopilot")
def factory_autopilot_status():
    return get_repository_autopilot_state()

@app.get("/api/factory/delegation-board")
def factory_delegation_board(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_delegation_board()

def get_lane_board():
    """T-599-F: per-lane state and Build Progress columns from Relay events + heartbeats only."""
    lanes=get_operator_lanes()
    beats={k:{"last_seen":v.get("last_seen") or None,"online":v.get("online") is True} for k,v in lanes.items()}
    # GitHub activity from the cached Team tasks board (never a GitHub read here): the Gemini loop works through
    # GitHub issues/PRs, not Relay, so its lane would otherwise look empty.
    team=_TEAM_TASKS_CACHE.peek() if "_TEAM_TASKS_CACHE" in globals() else None
    activity={k:{"done_7d":a.get("done_7d"),"last_activity_at":a.get("last_activity_at")}
              for k,a in ((team or {}).get("agents") or {}).items() if k in ("claude","chatgpt","gemini")}
    return build_lane_board(_parse_roadmap_tasks(),RELAY_STORE.list(limit=500),beats,stale_seconds=RELAY_QUEUE.stale_seconds,
                            github_activity=activity)

@app.get("/api/factory/lane-board")
def factory_lane_board(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_lane_board()

def _board_secret_values():
    return sorted([s for s in (FACTORY_CLAUDE_WORKER_TOKEN,FACTORY_CLAUDE_WORKER_TOKEN_EC2,FACTORY_OPERATOR_WORKER_TOKEN,FACTORY_TELEGRAM_BOT_TOKEN,
                               GITHUB_TOKEN,GITHUB_READ_TOKEN,FACTORY_MCP_TOKEN,FACTORY_LLM_API_KEY,FACTORY_SECRET,FACTORY_PASSWORD,FACTORY_LOCAL_BOOSTER_TOKEN,
                               FACTORY_PUBLISHER_TOKEN,FACTORY_METRICOOL_TOKEN,FACTORY_ANALYTICS_TOKEN,FACTORY_MEDIA_FINISHER_TOKEN,
                               FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN,FACTORY_VIEWER_INVITE_TOKEN) if s and len(s)>=8],key=len,reverse=True)

def get_worker_overview(board=None):
    """T-596: per-source Claude worker observability (host, EC2 API, systemd, OAuth, heartbeat, claim, task)."""
    board=board if board is not None else get_lane_board()
    answers=BASE/".autopilot"/"answers.md"
    try:
        con=db();row=con.execute("SELECT COUNT(*) AS total,SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) AS done FROM factory_tasks").fetchone();con.close()
        factory={"total":int(row["total"] or 0),"done":int(row["done"] or 0)}
    except Exception:factory=None
    overview=build_worker_overview(get_claude_code_status(),board,results=_load_claude_worker_results(),
                                   tickets=RELAY_STORE.list(limit=500),roadmap_tasks=_parse_roadmap_tasks(),
                                   factory_tasks=factory,
                                   answers_text=answers.read_text(encoding="utf-8") if answers.exists() else "",
                                   repo=GITHUB_REPO)
    return _redact_board_value(overview,_board_secret_values())

def get_telegram_lane_board():
    """Lane board plus the worker overview built from the same snapshot (Telegram /status)."""
    board=get_lane_board()
    try:board={**board,"worker_overview":get_worker_overview(board)}
    except Exception:pass
    return board

def get_telegram_operator_lanes():
    """T-586: the T-585 delegation lanes (already secret-redacted) for the Telegram Claude/Gemini buttons.
    2026-11-07: each lane also carries its GitHub facts from the cached Team tasks board (never a GitHub read here),
    so the Gemini lane, which works through GitHub PRs and has no Relay runner, is not shown as merely "not configured"."""
    lanes=get_delegation_board().get("operator_lanes") or []
    team=_TEAM_TASKS_CACHE.peek() if "_TEAM_TASKS_CACHE" in globals() else None
    agents=(team or {}).get("agents") or {}
    out=[]
    for lane in lanes:
        a=agents.get(str((lane or {}).get("operator_id") or "")) if isinstance(lane,dict) else None
        if isinstance(a,dict):
            c=a.get("counts") or {}
            lane={**lane,"github":{"open_prs":int(c.get("review") or 0)+int(c.get("in_progress") or 0)+int(c.get("ci_failed") or 0),
                                   "done_7d":a.get("done_7d") or 0,"last_activity_at":a.get("last_activity_at") or ""}}
        out.append(lane)
    return out

def _owner_decision_cards(roadmap):
    """Owner-desk cards that are open decisions and not already ROADMAP [HUMAN] tasks (those are listed anyway)."""
    known={str(t.get("id")) for t in roadmap or []}
    status=_owner_desk_status()
    return [{"id":r["id"],"title":r["title"],"covers":r.get("covers") or []} for r in OWNER_RUNBOOKS
            if r["id"] not in known and (status.get(r["id"]) or {}).get("state")=="todo"]

_TEAM_TASKS_CACHE=TeamTasksCache()

def github_read_check(fetch=None):
    """Evidence Protocol: can the read-only token read what verification needs? Codes only, never the token."""
    if fetch is None:
        if not GITHUB_READ_TOKEN:
            return {"configured":False,"reads":{}}
        fetch=github_fetcher(GITHUB_REPO,GITHUB_READ_TOKEN)
    reads={}
    for name,path in (("issues","/issues?per_page=1"),("pulls","/pulls?state=all&per_page=1"),
                      ("checks","/commits/main/check-runs?per_page=1"),("actions","/actions/runs?per_page=1")):
        try:
            data=fetch(path)
            reads[name]="ok" if isinstance(data,(list,dict)) else "unexpected"
        except Exception as exc:
            code=getattr(exc,"code",None)
            reads[name]=f"http_{code}" if code else "unreachable"
    # Fine-grained tokens have no Checks permission; CI is then read from Actions runs, which is enough.
    ci_via="checks" if reads.get("checks")=="ok" else "actions" if reads.get("actions")=="ok" else ""
    return {"configured":True,"reads":reads,"ci_via":ci_via,
            "all_ok":reads.get("issues")=="ok" and reads.get("pulls")=="ok" and bool(ci_via)}


@app.get("/api/factory/evidence/github-read-check")
def evidence_github_read_check(request: Request):
    if (request_identity(request) or {}).get("role")!="owner":
        raise HTTPException(403,"owner_only")
    return github_read_check()


@app.get("/api/factory/evidence/overview")
def evidence_overview(request: Request):
    """Evidence T2.4: the Agent Office panel. Owner only; facts from the Relay tickets, no secrets."""
    if (request_identity(request) or {}).get("role")!="owner":
        raise HTTPException(403,"owner_only")
    out=_evidence.overview(RELAY_STORE.list(limit=500),time.time())
    out["source"]="render" if GITHUB_READ_TOKEN else "ec2_snapshot"
    return out


def get_team_tasks(refresh=False):
    """Owner tasks page: Issues/PRs/CI per executor + ROADMAP [HUMAN] tasks + lane heartbeats."""
    def read():
        github=read_github(github_fetcher(GITHUB_REPO,_github_read_token()),owner=GITHUB_REPO.split("/",1)[0])
        if not github.get("available"):
            # Render's token cannot read the repo (seen 2026-11-04: HTTP 403); use the EC2 worker's snapshot (owner's gh login).
            snap=_load_team_snapshot()
            if snap and time.time()-float(snap.get("received",0))<3600:
                github={**snap["github"],"source":"ec2","fetched_at":snap["fetched_at"],"render_error":github.get("error")}
        try:lanes=(get_lane_board() or {}).get("lanes") or {}
        except Exception:lanes={}
        roadmap=_parse_roadmap_tasks()
        return build_team_tasks(github,roadmap=roadmap,lanes=lanes,repo=GITHUB_REPO,owner_cards=_owner_decision_cards(roadmap))
    return _TEAM_TASKS_CACHE.get(read,refresh=refresh)

_TEAM_SNAPSHOT_PATH=DATA_DIR/"team_tasks_github.json"

def _load_team_snapshot():
    try:return json.loads(_TEAM_SNAPSHOT_PATH.read_text())
    except Exception:return None

@app.post("/api/factory/team-tasks/worker/snapshot")
async def factory_team_tasks_snapshot(request: Request):
    if not _claude_worker_authorized(request):
        raise HTTPException(401,"worker token required")
    raw=await request.body()
    if len(raw)>3_000_000:raise HTTPException(413,"snapshot too large")
    try:data=compact_github(json.loads(raw))
    except Exception:raise HTTPException(400,"invalid json") from None
    data["available"]=True
    if not valid_snapshot(data):raise HTTPException(400,"invalid snapshot")
    now=time.time()
    tmp=_TEAM_SNAPSHOT_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps({"received":now,"fetched_at":datetime.fromtimestamp(now,timezone.utc).isoformat(),"github":data}))
    tmp.replace(_TEAM_SNAPSHOT_PATH)
    _TEAM_TASKS_CACHE.invalidate()
    return {"ok":True,"issues":len(data["issues"]),"pulls":len(data["pulls"])}

@app.get("/api/factory/team-tasks")
def factory_team_tasks(request: Request, refresh: int = 0):
    if (request_identity(request) or {}).get("role")!="owner":
        raise HTTPException(403,"Owner access required")
    return get_team_tasks(bool(refresh))

@app.get("/api/factory/worker-overview")
def factory_worker_overview(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_worker_overview()

# --- T-580 Role / Operator separation.
# A role is what a canonical worker does; an operator is the model/runtime assigned to it. Canonical worker
# names (AGENTS / AGENT_MAP) are untouched. Assignment is recorded owner intent only: it does not reroute the
# existing pipeline (T-588 owns routing) and never grants a provider publish/production privileges.
OPERATOR_IDS=("chatgpt","claude","gemini","auto")
ROLE_CATALOG=(
    {"id":"scout","label":"Scout","group":"content","workers":["Scout"],"operators":["chatgpt","claude","gemini","auto"]},
    {"id":"researcher","label":"Researcher","group":"content","workers":["Researcher","Tech Verifier"],"operators":["chatgpt","claude","gemini","auto"]},
    {"id":"scriptwriter","label":"Scriptwriter","group":"content","workers":["Angle Strategist","Hook Generator","Scriptwriter","Hook Optimizer","Editor"],"operators":["chatgpt","claude","gemini","auto"]},
    {"id":"reviewer","label":"Reviewer","group":"content","workers":["Fact Checker"],"operators":["chatgpt","claude","gemini","auto"]},
    {"id":"qa","label":"QA","group":"content","workers":["QA Agent"],"operators":["chatgpt","claude","gemini","auto"]},
    {"id":"engineer","label":"Engineer","group":"engineering","workers":[],"operators":["claude","gemini","auto"]},
    {"id":"supervisor","label":"Supervisor","group":"engineering","workers":["Supervisor"],"operators":["chatgpt","claude","gemini","auto"]},
)
ROLE_ASSIGNMENTS_FILE = DATA_DIR / "role_operator_assignments.json"
_role_assignments_lock=threading.Lock()

def _load_role_assignments():
    if not ROLE_ASSIGNMENTS_FILE.exists():return {}
    value=_decode_json(ROLE_ASSIGNMENTS_FILE.read_text(encoding="utf-8"),{})
    roles={r["id"]:r for r in ROLE_CATALOG}
    return {k:v for k,v in (value.items() if isinstance(value,dict) else [])
            if k in roles and v in roles[k]["operators"]}

def get_operator_status():
    """Operator readiness without secrets; unknown stays unknown instead of being reported as ready."""
    claude=get_claude_code_status()
    return [
        {"id":"chatgpt","label":"ChatGPT","kind":"api","model":FACTORY_LLM_MODEL,
         "online":bool(FACTORY_LLM_API_KEY),"auth":"ready" if FACTORY_LLM_API_KEY else "pending",
         "status":"configured" if FACTORY_LLM_API_KEY else "auth_pending"},
        {"id":"claude","label":"Claude","kind":"runner","model":"",
         "online":bool(claude["online"]),"auth":"ready" if claude["online"] and claude["auth_mode"] else ("unknown" if claude["online"] else "pending"),
         "status":"online" if claude["online"] else "offline"},
        {"id":"gemini","label":"Gemini","kind":"api","model":FACTORY_GEMINI_VIDEO_MODEL if FACTORY_GEMINI_API_KEY else "",
         "online":None if FACTORY_GEMINI_API_KEY else False,"auth":"ready" if FACTORY_GEMINI_API_KEY else "pending",
         "status":"configured_unverified" if FACTORY_GEMINI_API_KEY else "auth_pending"},
        {"id":"auto","label":"Auto","kind":"policy","model":"","online":True,"auth":"not_required","status":"policy"},
    ]

def get_role_operator_board():
    assigned=_load_role_assignments()
    operators=get_operator_status()
    status={o["id"]:o for o in operators}
    roles=[]
    for r in ROLE_CATALOG:
        choice=assigned.get(r["id"],"auto")
        live=[w for w in r["workers"] if w in LLM_LIVE_AGENTS]
        roles.append({**r,"workers":list(r["workers"]),"operators":list(r["operators"]),
            "assigned_operator":choice,"explicit":r["id"] in assigned,
            "operator_status":status[choice]["status"],
            # what the unchanged pipeline really uses today; assignment does not reroute it yet
            "runtime_operator":"chatgpt" if live else "",
            "enforced":False})
    return {"roles":roles,"operators":operators,"assignments":assigned,
            "note":"Assignments record owner intent; existing pipelines still run on their configured provider."}

class RoleAssignmentRequest(BaseModel):
    model_config={"extra":"forbid"}
    role: str
    operator: str

@app.get("/api/factory/roles")
def factory_roles(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_role_operator_board()

@app.post("/api/factory/roles/assignment")
def factory_role_assignment(item:RoleAssignmentRequest,request:Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    role=next((r for r in ROLE_CATALOG if r["id"]==item.role),None)
    if not role:raise HTTPException(404,"Unknown role")
    if item.operator not in OPERATOR_IDS:raise HTTPException(422,"Unknown operator")
    if item.operator not in role["operators"]:raise HTTPException(409,"Operator is not eligible for this role")
    with _role_assignments_lock:
        state=_load_role_assignments()
        if item.operator=="auto":state.pop(role["id"],None)
        else:state[role["id"]]=item.operator
        ROLE_ASSIGNMENTS_FILE.parent.mkdir(parents=True,exist_ok=True)
        tmp=ROLE_ASSIGNMENTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        os.replace(tmp,ROLE_ASSIGNMENTS_FILE)
    return {"ok":True,**get_role_operator_board()}

# --- T-588 Supervisor routing policy: a read-only decision per open roadmap task (explicit owner assignment >
# bounded Auto; offline skipped; HUMAN blocked). Executes nothing and grants no publish/production privilege.
def get_supervisor_routing(lanes=None):
    board=get_role_operator_board()
    if lanes is None:lanes=get_delegation_board().get("operator_lanes") or []
    availability=operator_availability(lanes,board["operators"])
    engineer=next(r for r in ROLE_CATALOG if r["id"]=="engineer")
    open_tasks=[t for t in _parse_roadmap_tasks() if not t["done"]]
    return {"routes":route_tasks(open_tasks,role="engineer",role_assignments=board["assignments"],
                                 availability=availability,eligible=engineer["operators"]),
            "availability":availability,"auto_policy":{k:list(v) for k,v in ROUTING_AUTO_POLICY.items()},
            "privileges":dict(ROUTING_PRIVILEGES),"executes":False}

@app.get("/api/factory/routing")
def factory_routing(request: Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return get_supervisor_routing()

# --- T-582 Battle Run experiment model: one brief, two or more competing role->operator chains, exact per-step
# provenance. Owner-only operator surface (not a member route). Never runs a provider and never publishes.
def _battle_owner(request:Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return str(identity.get("email") or identity.get("role") or "owner")

def _battle_call(fn,*args):
    try:return fn(*args)
    except BattleError as exc:raise HTTPException(exc.status_code,exc.detail)

@app.get("/api/battles")
def battle_list(request:Request):
    _battle_owner(request)
    return {"battles":BATTLE_STORE.list()}

@app.post("/api/battles")
async def battle_create(request:Request):
    who=_battle_owner(request)
    body=await request.json()
    battle,created=_battle_call(BATTLE_STORE.create,body,get_role_operator_board(),who)
    if created:event(None,f"Battle Run {battle['battle_id']} planned with {len(battle['chains'])} chains")
    return {"ok":True,"created":created,"battle":battle}

@app.get("/api/battles/{battle_id}")
def battle_get(battle_id:str,request:Request):
    _battle_owner(request)
    return {"battle":_battle_call(BATTLE_STORE.get,battle_id)}

@app.post("/api/battles/{battle_id}/results")
async def battle_record_result(battle_id:str,request:Request):
    who=_battle_owner(request)
    body=await request.json()
    return {"ok":True,"battle":_battle_call(BATTLE_STORE.record_step_result,battle_id,body,who)}

# --- T-583 Outcome attribution + leaderboard: credit an already-published item to the completed chain that made it,
# then compare chains on real performance snapshots only. Missing metrics stay null; nothing publishes here.
def _battle_publish_lookup(publish_id):
    con=db()
    try:
        row=con.execute("SELECT id,job_id,platform,status FROM publishing_queue WHERE id=?",(publish_id,)).fetchone()
        return dict(row) if row and tenancy.visible(tenancy.job_workspace(con,row["job_id"])) else None
    finally:con.close()

def _battle_latest_snapshot(publish_id):
    con=db()
    try:row=con.execute("""SELECT id,platform,captured_at,source,metrics_json FROM performance_snapshots
                           WHERE publish_id=? ORDER BY captured_at DESC,rowid DESC LIMIT 1""",(publish_id,)).fetchone()
    finally:con.close()
    if not row:return None
    return {"id":row["id"],"platform":row["platform"],"captured_at":row["captured_at"],"source":row["source"],
            "metrics":_decode_json(row["metrics_json"],{})}

@app.post("/api/battles/{battle_id}/outcomes")
async def battle_link_outcome(battle_id:str,request:Request):
    who=_battle_owner(request)
    body=await request.json()
    link,created=_battle_call(BATTLE_STORE.link_outcome,battle_id,body,_battle_publish_lookup,who)
    if created:event(link["job_id"] or None,f"Battle outcome: publish {link['publish_id']} attributed to {link['chain_id']}")
    return {"ok":True,"created":created,"link":link}

@app.get("/api/battles/{battle_id}/leaderboard")
def battle_leaderboard(battle_id:str,request:Request,metric:str="views"):
    _battle_owner(request)
    return _battle_call(BATTLE_STORE.leaderboard,battle_id,_battle_latest_snapshot,metric)

# --- T-584 Reviewer / Judge mode: a separate reviewer-role operator scores completed chains' final outputs on explicit
# criteria and selects one. Append-only; candidates are pinned by evidence hash and never rewritten; nothing publishes.
@app.get("/api/battles/{battle_id}/reviews")
def battle_reviews(battle_id:str,request:Request):
    _battle_owner(request)
    return {"battle_id":battle_id,"candidates":_battle_call(BATTLE_STORE.candidates,battle_id),
            "reviews":_battle_call(BATTLE_STORE.reviews,battle_id)}

@app.post("/api/battles/{battle_id}/reviews")
async def battle_record_review(battle_id:str,request:Request):
    who=_battle_owner(request)
    body=await request.json()
    review,created=_battle_call(BATTLE_STORE.record_review,battle_id,body,get_role_operator_board(),who)
    if created:event(None,f"Battle review: {review['judge']['operator']} selected {review['selected_chain_id']} in {review['battle_id']}")
    return {"ok":True,"created":created,"review":review}

# --- T-587 Telegram Battle controls: the paired owner chat views battles, candidate chains and factual metrics and
# records only approve/reject owner decisions. Nothing here publishes or runs a provider.
TELEGRAM_BATTLES=BattleTelegram(BATTLE_STORE,_battle_latest_snapshot)

# --- T-536-F safe operator controls: owner -> FactoryOS -> Claude runner command channel.
# Only these three actions exist. Nothing here can push, switch branches, deploy, publish or touch secrets;
# commands carry only {action, task_id} and the runner applies them between tasks.
DELEGATION_CONTROL_ACTIONS=("pause","resume","retry")
DELEGATION_CONTROL_FILE = DATA_DIR / "claude_worker_control.json"
_delegation_control_lock=threading.Lock()
_DELEGATION_CONTROL_TERMINAL=("applied","rejected","superseded")

class DelegationControlRequest(BaseModel):
    model_config={"extra":"forbid"}
    action: str
    request_id: str
    task_id: str = ""

class DelegationControlAck(BaseModel):
    model_config={"extra":"forbid"}
    command_id: str
    outcome: str
    detail: str = ""

def _load_delegation_control():
    empty={"paused":False,"commands":[],"audit":[]}
    if not DELEGATION_CONTROL_FILE.exists():return empty
    value=_decode_json(DELEGATION_CONTROL_FILE.read_text(encoding="utf-8"),empty)
    if not isinstance(value,dict):return empty
    return {"paused":value.get("paused") is True,
            "commands":[x for x in value.get("commands") or [] if isinstance(x,dict)],
            "audit":[x for x in value.get("audit") or [] if isinstance(x,dict)]}

def _save_delegation_control(state):
    pending=[x for x in state["commands"] if x.get("status")=="pending"]
    done=[x for x in state["commands"] if x.get("status")!="pending"][-100:]
    state["commands"]=sorted(pending+done,key=lambda x:x.get("seq",0))
    state["audit"]=state["audit"][-200:]
    DELEGATION_CONTROL_FILE.parent.mkdir(parents=True,exist_ok=True)
    tmp=DELEGATION_CONTROL_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    os.replace(tmp,DELEGATION_CONTROL_FILE)

def _delegation_audit(state,actor,action,outcome,*,task_id="",request_id="",command_id="",detail=""):
    state["audit"].append({"at":time.time(),"actor":actor,"action":str(action)[:40],"task_id":task_id,"request_id":request_id,
                           "command_id":command_id,"outcome":outcome,"detail":str(detail)[:300]})

def _delegation_actor(identity):
    identity=identity or {}
    return ":".join(x for x in (str(identity.get("role") or "unknown"),str(identity.get("email") or "")) if x)

def _delegation_retry_refusal(task_id,queue,worker):
    """Why `task_id` may not be retried, or "" when it is a blocked/failed safe ROADMAP task."""
    task=next((x for x in queue if x["id"]==task_id),None)
    if not task:return "unknown roadmap task"
    if task.get("human"):return "HUMAN roadmap tasks cannot be retried by the runner"
    if task.get("done") or task.get("state")=="done":return "task is already done"
    if worker.get("online") and str(worker.get("active_task_id") or "")==task_id:return "task is running now"
    if task.get("state")!="blocked":return "only blocked or failed tasks can be retried"
    return ""

def submit_delegation_control(item:DelegationControlRequest,identity,*,queue=None,worker=None):
    """Record one owner command. Idempotent per request_id; repeated intents never queue twice."""
    actor=_delegation_actor(identity)
    action=item.action.strip().lower()
    task_id=item.task_id.strip()
    request_id=item.request_id.strip()
    with _delegation_control_lock:
        state=_load_delegation_control()
        if not re.match(r"^[A-Za-z0-9_-]{8,64}$",request_id):
            _delegation_audit(state,actor,action,"rejected",task_id=task_id[:40],detail="invalid request_id")
            _save_delegation_control(state)
            raise HTTPException(422,"request_id must be 8-64 characters of [A-Za-z0-9_-]")
        replay=next((x for x in state["commands"] if x.get("request_id")==request_id),None)
        if replay:
            if replay["action"]!=action or replay["task_id"]!=task_id:
                raise HTTPException(409,"request_id was already used for a different command")
            return {"ok":True,"duplicate":True,"changed":False,"command":replay,"paused":state["paused"]}
        noop=next((x for x in state["audit"] if x.get("request_id")==request_id and x.get("outcome")=="noop"),None)
        if noop:
            if noop["action"]!=action or noop["task_id"]!=task_id:
                raise HTTPException(409,"request_id was already used for a different command")
            return {"ok":True,"duplicate":True,"changed":False,"command":None,"paused":state["paused"]}
        refusal=""
        if action not in DELEGATION_CONTROL_ACTIONS:
            refusal=f"unsupported action; allowed: {', '.join(DELEGATION_CONTROL_ACTIONS)}"
        elif action=="retry":
            if not re.match(r"^T-[A-Za-z0-9-]+$",task_id):refusal="retry requires a ROADMAP task id"
            else:
                if queue is None or worker is None:
                    board=get_delegation_board()
                    queue,worker=board["planner_queue"],board["worker"]
                refusal=_delegation_retry_refusal(task_id,queue,worker)
        elif task_id:
            refusal=f"{action} does not take a task id"
        if refusal:
            _delegation_audit(state,actor,action,"rejected",task_id=task_id[:40],request_id=request_id,detail=refusal)
            _save_delegation_control(state)
            raise HTTPException(409 if action in DELEGATION_CONTROL_ACTIONS else 400,refusal)
        pending=[x for x in state["commands"] if x.get("status")=="pending"]
        same=next((x for x in pending if x["action"]==action and x["task_id"]==task_id),None)
        if action in ("pause","resume") and state["paused"]==(action=="pause"):
            _delegation_audit(state,actor,action,"noop",request_id=request_id,command_id=(same or {}).get("id",""),
                              detail="already paused" if action=="pause" else "already running")
            _save_delegation_control(state)
            return {"ok":True,"duplicate":False,"changed":False,"command":same,"paused":state["paused"]}
        if same:
            _delegation_audit(state,actor,action,"noop",task_id=task_id,request_id=request_id,command_id=same["id"],detail="already pending")
            _save_delegation_control(state)
            return {"ok":True,"duplicate":False,"changed":False,"command":same,"paused":state["paused"]}
        now=time.time()
        if action in ("pause","resume"):
            opposite="resume" if action=="pause" else "pause"
            for cmd in pending:
                if cmd["action"]==opposite:
                    cmd.update(status="superseded",updated_at=now,detail=f"superseded by {action}")
                    _delegation_audit(state,actor,opposite,"superseded",command_id=cmd["id"],request_id=cmd["request_id"])
            state["paused"]=action=="pause"
        seq=max([int(x.get("seq") or 0) for x in state["commands"]]+[0])+1
        command={"id":uuid.uuid4().hex,"seq":seq,"request_id":request_id,"action":action,"task_id":task_id,"status":"pending",
                 "actor":actor,"created_at":now,"updated_at":now,"detail":""}
        state["commands"].append(command)
        _delegation_audit(state,actor,action,"accepted",task_id=task_id,request_id=request_id,command_id=command["id"])
        _save_delegation_control(state)
        return {"ok":True,"duplicate":False,"changed":True,"command":command,"paused":state["paused"]}

def get_worker_delegation_control():
    """What the runner may see: the pause level and pending commands as {id, action, task_id} only."""
    state=_load_delegation_control()
    return {"paused":state["paused"],
            "commands":[{"id":x["id"],"action":x["action"],"task_id":x["task_id"]}
                        for x in state["commands"] if x.get("status")=="pending" and x.get("action") in DELEGATION_CONTROL_ACTIONS]}

def ack_delegation_control(item:DelegationControlAck):
    outcome=item.outcome.strip().lower()
    if outcome not in ("applied","rejected"):raise HTTPException(422,"outcome must be applied or rejected")
    with _delegation_control_lock:
        state=_load_delegation_control()
        command=next((x for x in state["commands"] if x.get("id")==item.command_id.strip()),None)
        if not command:raise HTTPException(404,"Unknown command")
        if command["status"] in _DELEGATION_CONTROL_TERMINAL:
            return {"ok":True,"duplicate":True,"command":command}
        command.update(status=outcome,updated_at=time.time(),detail=item.detail.strip()[:300])
        _delegation_audit(state,"worker",command["action"],outcome,task_id=command["task_id"],request_id=command["request_id"],
                          command_id=command["id"],detail=command["detail"])
        _save_delegation_control(state)
        return {"ok":True,"duplicate":False,"command":command}

def get_delegation_control_view(queue,worker):
    """Owner-facing control state for the delegation board."""
    state=_load_delegation_control()
    pending=[x for x in state["commands"] if x.get("status")=="pending"]
    pending_retry={x["task_id"] for x in pending if x["action"]=="retry"}
    pause_cmd=next((x for x in reversed(pending) if x["action"]=="pause"),None)
    mode="pause_requested" if pause_cmd else ("paused" if state["paused"] else "running")
    return {"paused":state["paused"],"mode":mode,
            "available":["resume"] if state["paused"] else ["pause"],
            "retryable":[x["id"] for x in queue if x["id"] not in pending_retry and not _delegation_retry_refusal(x["id"],queue,worker)],
            "pending":[{k:x.get(k) for k in ("id","action","task_id","created_at")} for x in pending],
            "recent_audit":[{k:x.get(k) for k in ("at","action","task_id","outcome","detail")} for x in state["audit"][-10:]],
            "allowed_actions":list(DELEGATION_CONTROL_ACTIONS)}

@app.post("/api/factory/delegation-control")
def factory_delegation_control(item:DelegationControlRequest,request:Request):
    identity=request_identity(request) or {}
    if identity.get("role")!="owner":raise HTTPException(403,"Owner access required")
    return submit_delegation_control(item,identity)

@app.get("/api/claude-worker/control")
def claude_worker_control(request:Request):
    # Worker token only: an owner session must not be able to impersonate the runner.
    if not _claude_worker_authorized(request):raise HTTPException(401,"Claude worker token required")
    return get_worker_delegation_control()

@app.post("/api/claude-worker/control/ack")
def claude_worker_control_ack(item:DelegationControlAck,request:Request):
    if not _claude_worker_authorized(request):raise HTTPException(401,"Claude worker token required")
    return ack_delegation_control(item)

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
    identity=_identity_from_session_token(ws.cookies.get(COOKIE_NAME,"")) if FACTORY_PASSWORD else {"role":"owner"}
    if not identity:
        await ws.close(code=4401)
        return
    await ws.accept(); clients.add(ws)
    if tenancy.identity_workspace(identity) is not None: member_clients.add(ws)
    try:
        while True: await ws.receive_text()
    except WebSocketDisconnect: clients.discard(ws); member_clients.discard(ws)
