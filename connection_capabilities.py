"""Connection projections for FactoryOS UI. No provider calls or secret access.

A configured credential is not evidence of entitlement or a successful generation.
Worker runtime presence is not the same as AI subscription or API authentication.
"""
from __future__ import annotations
from urllib.parse import urlsplit

AI_PROVIDER_SPECS = (
    ("openai", "ChatGPT / OpenAI", "available"),
    ("anthropic", "Claude", "available"),
    ("google", "Gemini", "available"),
    ("microsoft", "Copilot", "planned"),
    ("deepseek", "DeepSeek", "planned"),
    ("xai", "Grok", "planned"),
)

def llm_provider_for_endpoint(base_url: str) -> str | None:
    """Only identify known first-party API hosts; custom proxies stay unverified."""
    try:
        uri = urlsplit(base_url.strip())
        host = (uri.hostname or "").lower()
        if uri.scheme != "https":
            return None
    except (ValueError, AttributeError):
        return None
    return {
        "api.openai.com": "openai",
        "api.anthropic.com": "anthropic",
        "generativelanguage.googleapis.com": "google",
    }.get(host)

def ai_provider_catalog(model: str, base_url: str, llm_key_present: bool) -> list[dict]:
    """Catalog identity is not a claim of OAuth connection or successful API request."""
    selected = llm_provider_for_endpoint(base_url)
    out = []
    for code, label, availability in AI_PROVIDER_SPECS:
        configured = availability == "available" and selected == code and bool(llm_key_present)
        out.append({
            "id": code,
            "name": label,
            "availability": availability,
            "status": ("coming_soon" if availability == "planned" else
                       "configured_unverified" if configured else "not_configured"),
            "model": str(model)[:120] if configured else "",
            "access_verified": False,
            "auth_type": "api_key" if configured else None,
            "subscription_is_worker": False,
        })
    return out

def worker_projection(cw: dict) -> list[dict]:
    """Existing Claude Code worker state, with no fabricated host or worker identities."""
    node = cw.get("node") if isinstance(cw.get("node"), dict) else {}
    online = cw.get("online") is True
    host_type = node.get("host_type") if node.get("host_type") in ("local", "remote", "cloud") else "unknown"
    return [{
        "id": str(node.get("node_id") or "claude-code-worker")[:80],
        "name": "Claude Code Worker",
        "runtime": "claude-code",
        "provider": "anthropic",
        "host_type": host_type,
        "online": online,
        "status": "running" if online and cw.get("active_task_id") else "idle" if online else "offline",
        "last_seen": cw.get("last_seen") or None,
        "active_task_id": str(cw.get("active_task_id") or "")[:100] if online else "",
        "auth_mode": str(cw.get("auth_mode") or "")[:80] if online else "",
        "last_error": str(cw.get("last_error") or "")[:200],
        "paired": online,  # a heartbeat proves it was paired; offline is unknown, not disproved
        "hosting_cost_verified": False,
    }]

def video_projection(provider: str, model: str, configured: bool) -> dict:
    """Configured key/endpoint does not assert successful provider access."""
    p = str(provider or "").lower()
    google = p in {"gemini", "gemini-omni", "gemini-omni-flash", "google-gemini", "google-gemini-omni"}
    return {
        "provider": "google" if google else p,
        "model": str(model or "")[:120] if google else "",
        "capability": "video_generation",
        "credential_configured": bool(configured),
        "access_verified": False,
        "access_state": "configured_unverified" if configured else "not_configured",
        "auth_type": "api_key" if google else "provider_credentials",
        "separate_from_chat_subscription": True,
        "may_incur_charges": True,
    }
