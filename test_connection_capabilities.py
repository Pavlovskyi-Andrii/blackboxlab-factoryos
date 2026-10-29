"""Offline, zero-spend connections contract regression. Run: python test_connection_capabilities.py."""
from pathlib import Path
from connection_capabilities import (
    ai_provider_catalog, llm_provider_for_endpoint, worker_projection, video_projection
)

def check(condition, reason):
    if not condition:
        raise AssertionError(reason)

def main():
    check(llm_provider_for_endpoint("https://api.openai.com/v1")=="openai","OpenAI host")
    check(llm_provider_for_endpoint("https://api.anthropic.com/v1")=="anthropic","Claude host")
    check(llm_provider_for_endpoint("https://generativelanguage.googleapis.com/v1")=="google","Google host")
    for uri in ["http://api.openai.com/v1","https://api.openai.com.evil.example/v1","https://example.com/v1",""]:
        check(llm_provider_for_endpoint(uri) is None,"Unknown or unsafe host must not be attributed to OpenAI")
    providers=ai_provider_catalog("gpt-test","https://api.openai.com/v1",True)
    check([p["id"] for p in providers]==["openai","anthropic","google","microsoft","deepseek","xai"],"Provider order/catalog")
    check(providers[0]["status"]=="configured_unverified","API key configuration is not a verified model connection")
    check(providers[0]["model"]=="gpt-test","Actual backend model must be displayed")
    check(all(not p["access_verified"] for p in providers),"No live provider claims without a verification")
    check(all(p["status"]=="coming_soon" for p in providers[3:]),"Unsupported providers must be planned")
    no_key=ai_provider_catalog("gpt-test","https://api.openai.com/v1",False)
    check(no_key[0]["status"]=="not_configured","No key => no connection")
    proxy=ai_provider_catalog("gpt-test","https://proxy.example/v1",True)
    check(all(p["status"]!="configured_unverified" for p in proxy),"Proxy must not impersonate first-party provider")
    offline=worker_projection({"online":False,"active_task_id":"T-42","last_seen":1700000000,"node":{"node_id":"existing-ec2","auth_mode":"subscription"}})[0]
    check(offline["status"]=="offline" and not offline["active_task_id"],"Stale worker cannot claim active execution")
    check(not offline["paired"] and offline["host_type"]=="unknown","Unknown host must remain unknown")
    online=worker_projection({"online":True,"active_task_id":"T-42","last_seen":1700000001,"auth_mode":"subscription","node":{"node_id":"existing-ec2","host_type":"remote"}})[0]
    check(online["status"]=="running" and online["active_task_id"]=="T-42","Verified heartbeat and active task")
    check(online["host_type"]=="remote" and online["paired"],"Reported worker host and heartbeat")
    v=video_projection("gemini-omni","gemini-omni-1.1-flash",True)
    check(v["provider"]=="google" and v["capability"]=="video_generation","Model provider/capability")
    check(v["access_state"]=="configured_unverified" and not v["access_verified"],"A key is not a verified video generation")
    check(v["separate_from_chat_subscription"] and v["may_incur_charges"],"Subscription/billing boundaries")
    check(video_projection("gemini-omni","gemini-omni-1.1-flash",False)["access_state"]=="not_configured","Unconfigured video model")
    html=Path("static/index.html").read_text(encoding="utf-8")
    for needle in (
        'id="workerHostChoice"', 'id="workerRuntimeChoice"',
        'onclick="copyClaudePairingToken()"', "/api/factory/claude-code/pair-token",
        "workerHostChanged()", "connections.workerOffline",
        "connections.videoUnverified", "AI Providers", "connectionAction(k,v)"
    ):
        check(needle in html,"Missing Connections UI contract "+needle)
    check("sudo python3 -m autopilot.pair_worker" in html,"Existing EC2 pairing command missing")
    print("Connections catalog, video access, worker status and guided setup: PASS (offline zero-spend)")

if __name__=="__main__":
    main()
