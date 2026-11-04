"""Gemini coder proxy for the EC2 loop (owner decision 2026-11-04).

The EC2 worker runs the Gemini Issue -> PR loop every 5 minutes; the Gemini key stays in Render.
Worker token only. Text generation with stable Flash models only, so a leaked worker token cannot
reach pro/preview/paid media models. Google error text is never relayed, only its HTTP status.
"""
from __future__ import annotations

import json
import re
from typing import Callable
from urllib import request as urlrequest

from fastapi import HTTPException, Request

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
FLASH_MODEL = re.compile(r"^gemini-(?:[0-9.]+-flash(?:-lite)?|flash-latest|flash-lite-latest)$")
MAX_PROMPT_CHARS = 400_000


def _call(api_key: str, method: str, path: str, payload, opener, timeout: int):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urlrequest.Request(f"{GEMINI_API}/{path}", data=data, method=method,
                             headers={"x-goog-api-key": api_key, "Content-Type": "application/json"})
    try:
        with (opener or urlrequest.urlopen)(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPException:
        raise
    except Exception as exc:
        status = int(getattr(exc, "code", 0) or 0)
        raise HTTPException(status_code=502, detail={"error": "gemini upstream", "upstream_status": status or 504}) from None


def install_gemini_worker_routes(app, *, authorize_worker: Callable[[Request], bool], api_key: Callable[[], str],
                                 opener: Callable | None = None) -> None:
    def _key(request: Request) -> str:
        if not authorize_worker(request):
            raise HTTPException(status_code=401, detail="worker token required")
        key = api_key()
        if not key:
            raise HTTPException(status_code=409, detail="gemini key not configured")
        return key

    @app.get("/api/factory/gemini/worker/models")
    def gemini_worker_models(request: Request):
        key = _key(request)
        listing = _call(key, "GET", "models?pageSize=200", None, opener, 30)
        names = [str(m.get("name", "")).split("/")[-1] for m in listing.get("models") or []
                 if "generateContent" in (m.get("supportedGenerationMethods") or [])]
        return {"models": [n for n in names if FLASH_MODEL.fullmatch(n)]}

    @app.post("/api/factory/gemini/worker/generate")
    async def gemini_worker_generate(request: Request):
        key = _key(request)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="json body required") from None
        model, prompt = str((body or {}).get("model") or ""), str((body or {}).get("prompt") or "")
        if not FLASH_MODEL.fullmatch(model):
            raise HTTPException(status_code=400, detail="only stable Flash text models")
        if not prompt or len(prompt) > MAX_PROMPT_CHARS:
            raise HTTPException(status_code=400, detail="prompt empty or too large")
        import anyio
        payload = {"contents": [{"parts": [{"text": prompt}]}],
                   "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 32768, "temperature": 0.2}}
        data = await anyio.to_thread.run_sync(lambda: _call(key, "POST", f"models/{model}:generateContent", payload, opener, 400))
        text = "".join(str(p.get("text") or "") for p in (((data.get("candidates") or [{}])[0].get("content") or {}).get("parts") or []))
        return {"model": model, "text": text}


# --- #122: owner "Check" button in Connections → free read-only models list, cached 10 minutes ---
GEMINI_KEY_CHECK = {"status": "", "checked_at": None, "models": 0}
_CHECK_TTL = 600


def verify_gemini_key(api_key: str, opener: Callable | None = None) -> dict:
    """verified | invalid_key | not_configured | unreachable. No key, key parts or Google text in the result."""
    import time
    from datetime import datetime, timezone
    if not api_key:
        return {"status": "not_configured", "checked_at": None, "models": 0}
    req = urlrequest.Request(f"{GEMINI_API}/models?pageSize=200", headers={"x-goog-api-key": api_key})
    try:
        with (opener or urlrequest.urlopen)(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
        status, models = "verified", len(data.get("models") or [])
    except Exception as exc:
        status, models = ("invalid_key" if getattr(exc, "code", 0) in (400, 401, 403) else "unreachable"), 0
    return {"status": status, "checked_at": datetime.now(timezone.utc).isoformat(), "models": models, "_at": time.time()}


def install_gemini_verify_route(app, *, request_identity: Callable, api_key: Callable[[], str],
                                opener: Callable | None = None) -> None:
    import time

    @app.post("/api/factory/connections/gemini/verify")
    def gemini_connection_verify(request: Request):
        if (request_identity(request) or {}).get("role") != "owner":
            raise HTTPException(status_code=403, detail="Owner access required")
        key = api_key()
        cached = GEMINI_KEY_CHECK
        if key and cached.get("status") and time.time() - float(cached.get("_at") or 0) < _CHECK_TTL:
            result = cached
        else:
            result = verify_gemini_key(key, opener)
            GEMINI_KEY_CHECK.clear()
            GEMINI_KEY_CHECK.update(result)
        return {k: v for k, v in result.items() if not k.startswith("_")}
