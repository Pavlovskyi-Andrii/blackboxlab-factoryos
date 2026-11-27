"""MCP ops_health (owner 2026-11-27): python test_ops_health.py — unit snapshot plus the real /mcp route."""
import asyncio
import json
import os
import tempfile
from unittest.mock import patch

import ops_health

NOW = 1_800_000_000.0


def test_snapshot():
    worker = {"online": True, "last_seen": NOW - 42, "active_task_id": "T-742", "task_state": "running",
              "last_error": "git push failed with token ghp_SECRETSECRET1234 in url " + "x" * 400}
    telegram = {"configured": True, "paired": True, "paired_at": "2026-11-01T08:00:00+00:00", "username": "owner_handle",
                "chat_id": 123456}
    deliveries = [{"id": "mycast-2026-11-26", "kind": "mycast", "status": "sent", "seconds": 410, "at": NOW - 90_000},
                  {"id": "mycast-2026-11-27", "kind": "mycast", "status": "sent", "seconds": 433, "at": NOW - 3_600},
                  {"id": "brief-2026-11-27", "kind": "brief", "status": "failed:qc", "seconds": 0, "at": NOW - 600}, "junk"]
    ops = {"enabled": False, "classes": ["read", "restart"], "executor": {"online": False, "last_poll_at": None},
           "requests": [{"output": "secret log"}]}
    snap = ops_health.snapshot("claude", worker=worker, telegram=telegram, deliveries=deliveries, ops=ops,
                               finisher={"endpoint": "media.example:443", "token": ""},
                               known_secrets=lambda: ["ghp_SECRETSECRET1234", ""], now=NOW)
    assert snap["claude_worker"]["online"] and snap["claude_worker"]["last_seen_seconds_ago"] == 42
    assert snap["claude_worker"]["active_task_id"] == "T-742"
    error = snap["claude_worker"]["last_error"]
    assert "ghp_SECRET" not in error and "[redacted]" in error and len(error) == 200
    assert snap["telegram"] == {"bot_configured": True, "owner_paired": True, "paired_at": "2026-11-01T08:00:00+00:00"}
    text = json.dumps(snap)
    assert "owner_handle" not in text and "123456" not in text and "secret log" not in text  # no ids, names, op output
    assert [d["id"] for d in snap["deliveries"]] == ["brief-2026-11-27", "mycast-2026-11-27", "mycast-2026-11-26"]
    assert snap["deliveries"][1] == {"kind": "mycast", "id": "mycast-2026-11-27", "status": "sent", "seconds": 433,
                                     "seconds_ago": 3600}
    assert snap["ops_relay"] == {"enabled": False, "classes": ["read", "restart"], "agent_online": False,
                                 "agent_last_poll_at": None}
    assert snap["media_finisher"] == {"endpoint_configured": True, "token_configured": False, "recent_jobs": []}
    never = ops_health.snapshot("claude", worker={}, telegram={}, deliveries=[], ops={}, finisher={}, now=NOW)
    assert never["claude_worker"]["last_seen_seconds_ago"] is None and never["deliveries"] == []
    for lane in ("chatgpt", "gemini", ""):
        try:
            ops_health.snapshot(lane, worker={}, telegram={}, deliveries=[], ops={}, finisher={}, now=NOW)
            raise AssertionError("only the Claude lane may read ops_health")
        except PermissionError:
            pass


def test_edit_jobs():
    job = {"id": "3f2c9a1e-7b1d-4c55-9a51-0a1b2c3d4e5f", "status": "ready", "provider": "render-media-finisher",
           "platform": "reels", "created_at": "2026-11-27T16:40:00Z", "updated_at": "2026-11-27T16:44:00Z",
           "completed_at": "2026-11-27T16:44:00Z", "output_url": "https://media.example/files/x/final.mp4?exp=1&sig=abc",
           "error": "download failed https://media.example/files/x/final.mp4?exp=1&sig=SIGNED for ghp_SECRETSECRET1234",
           "request": {"options": {"split_shortform": True, "edit_full_video": True}},
           "response": {"stage": "done", "percent": 100},
           "report": {"edit_summary": {"duration_before_sec": 48.21, "duration_after_sec": 41.0, "removed_segments": 4,
                                       "filler_segments_removed": 2, "graphics_engine": "remotion"},
                      "transcript_words": [{"word": "приватне слово"}],
                      "qa_report": {"overall": "warn", "checks": [
                          {"id": "final_decodes", "status": "pass"},
                          {"id": "words_at_cuts", "status": "fail", "lost_words": ["приватне"], "clipped_words": []},
                          {"id": "voice_loudness", "status": "warn", "measured_lufs": -19.2, "target_lufs": -16}]},
                      "shorts_manifest": {"enabled": True, "clips": [{"duration_sec": 20.5, "url": "https://x/short-01.mp4"},
                                                                      {"duration_sec": 18}]},
                      "render_metrics": {"wall_sec": 212.4, "realtime_factor": 4.41}}}
    snap = ops_health.snapshot("claude", worker={}, telegram={}, deliveries=[], ops={}, finisher={"endpoint": "x"},
                               known_secrets=lambda: ["ghp_SECRETSECRET1234"], now=NOW, edit_jobs=[job, "junk"])
    jobs = snap["media_finisher"]["recent_jobs"]
    assert len(jobs) == 1
    one = jobs[0]
    assert one["id"] == "3f2c9a1e-7b1" and one["status"] == "ready" and one["stage"] == "done" and one["percent"] == 100
    assert one["shorts_requested"] and one["shorts"] == {"enabled": True, "clips": 2, "clip_seconds": [20.5, 18.0]}
    assert one["duration_before_sec"] == 48.21 and one["duration_after_sec"] == 41.0 and one["qa_overall"] == "warn"
    assert one["qa_flagged"] == [{"id": "words_at_cuts", "status": "fail", "lost_words": 1, "clipped_words": 0},
                                 {"id": "voice_loudness", "status": "warn", "measured_lufs": -19.2, "target_lufs": -16}]
    assert one["render_wall_sec"] == 212.4 and one["error"].startswith("download failed [link]")
    text = json.dumps(snap, ensure_ascii=False)
    for leak in ("приватне", "https://", "sig=", "ghp_SECRET", "short-01"):
        assert leak not in text, leak                                  # no words, links, signatures or secrets


def test_mcp_route():
    os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-opshealth-"))
    import app as factory

    def mcp(bearer):
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": "ops_health", "arguments": {}}}).encode()
        headers = [(b"host", b"testserver"), (b"content-type", b"application/json"),
                   (b"authorization", ("Bearer " + bearer).encode())]
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST", "scheme": "http",
                 "path": "/mcp", "raw_path": b"/mcp", "query_string": b"", "headers": headers,
                 "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
        sent, delivered = [], []

        async def receive():
            if not delivered:
                delivered.append(True)
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)
        asyncio.run(factory.app(scope, receive, send))
        return json.loads(b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))

    lanes = {"FACTORY_MCP_LANE_TOKEN_CLAUDE": "claude-lane-token-for-tests-0001",
             "FACTORY_MCP_LANE_TOKEN_CHATGPT": "chatgpt-lane-token-for-tests-0001"}
    with patch.dict(os.environ, lanes), patch.object(factory, "FACTORY_MCP_TOKEN", "shared-mcp-token-for-tests-0001"):
        assert "ops_health" in [t["name"] for t in factory.FACTORY_MCP_TOOLS]
        result = mcp("claude-lane-token-for-tests-0001")["result"]
        snap = json.loads(result["content"][0]["text"])
        assert not result.get("isError") and set(snap) == {"checked_at", "claude_worker", "telegram", "deliveries",
                                                           "ops_relay", "media_finisher"}
        for other in ("chatgpt-lane-token-for-tests-0001", "shared-mcp-token-for-tests-0001"):
            refused = mcp(other)["result"]
            assert refused["isError"] and "Claude lane" in refused["content"][0]["text"], refused


if __name__ == "__main__":
    test_snapshot()
    test_edit_jobs()
    test_mcp_route()
    print("ops_health tests passed")
