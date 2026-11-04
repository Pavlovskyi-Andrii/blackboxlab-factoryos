"""T-553 Workspace data tenancy regression.

Deterministic two-workspace fixture (no LLM key, no outbound HTTP, $0.00). Customer `acme` and customer `globex` each
own a job, artifacts, an approval decision, a published + a scheduled publishing queue item, a performance snapshot and
an integration binding. Every request goes through the full ASGI app (auth middleware included) with signed member /
owner session cookies. Checks:
  * members only list their own jobs, events, approvals, publishing queue, analytics/attribution and integrations;
  * every id-addressed read or mutation of the other workspace's job / artifact / publish item / analytics is a 404
    and leaves the database untouched; operator surfaces are 403 for members;
  * server-held publisher credentials (Metricool) never become another customer's connection, and a binding change in
    one workspace never moves the other's;
  * the owner keeps cross-workspace observability (all jobs, all publish items, /api/workspaces counts);
  * background work carries explicit workspace identity: scheduled publishing runs per item under its workspace and the
    credential fence stops non-default workspaces before any outbound call, Local Booster claims and job tasks carry the
    job's workspace, and member websockets only receive bare refreshes;
  * forged/revoked member sessions are rejected.
"""
import asyncio
import json
import os
import tempfile
import uuid
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="factoryos-tenancy-"))
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")

import app as factory
import workspace_tenancy as tenancy

MEMBERS = {"alice@acme.test": "acme", "bob@globex.test": "globex"}
SECRET_TOKEN = "mc-secret-token-t553-never-render"
outbound = []


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def cookie_for(role, email=""):
    if role == "owner":
        return factory.session_token(factory.FACTORY_USER)
    return factory._member_session_token(email, MEMBERS[email])


def call(method, path, cookie=None, body=None, query=""):
    payload = json.dumps(body).encode("utf-8") if body is not None else b""
    headers = [(b"host", b"testserver")]
    if body is not None:
        headers.append((b"content-type", b"application/json"))
    if cookie:
        headers.append((b"cookie", f"{factory.COOKIE_NAME}={cookie}".encode("utf-8")))
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
             "path": path, "raw_path": path.encode("utf-8"), "query_string": query.encode("utf-8"),
             "headers": headers, "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
    sent = []

    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(factory.app(scope, receive, send))
    start = next(m for m in sent if m["type"] == "http.response.start")
    raw = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    try:
        data = json.loads(raw or b"null")
    except ValueError:
        data = raw.decode("utf-8", "replace")
    return start["status"], data


def no_network(*args, **kwargs):
    outbound.append(args[0] if args else kwargs)
    raise AssertionError("T-553 regression must not make outbound provider calls")


def seed_workspace(email):
    cookie = cookie_for("member", email)
    status, created = call("POST", "/api/jobs", cookie, {"title": f"{MEMBERS[email]} launch video", "brief": "private brief"})
    require(status == 200 and created["workspace_key"] == MEMBERS[email], f"member job create: {status} {created}")
    job_id = created["id"]
    artifact = factory.save_artifact("Script Agent", "script", f"{MEMBERS[email]} script", "secret script body",
                                     job_id=job_id, meta={"fixture": "t553"})
    now = factory.ts()
    con = factory.db()
    con.execute("UPDATE jobs SET status='waiting_approval' WHERE id=?", (job_id,))
    con.execute("""INSERT INTO approval_decisions(id,job_id,decision,reason,actor,created_at,meta_json)
                   VALUES(?,?,?,?,?,?,?)""", (str(uuid.uuid4()), job_id, "approved", "fixture", "owner", now, "{}"))
    ids = {}
    for kind, status_value in (("published", "published"), ("scheduled", "scheduled")):
        pid = str(uuid.uuid4())
        meta = {"content_snapshot": {"title": f"{MEMBERS[email]} post", "caption": "c"}, "content_snapshot_hash": "h"}
        con.execute("""INSERT INTO publishing_queue(id,job_id,package_id,status,target,platform,scheduled_at,idempotency_key,
                       attempt_count,external_post_id,created_at,updated_at,published_at,meta_json)
                       VALUES(?,?,?,?,?,?,?,?,0,?,?,?,?,?)""",
                    (pid, job_id, "pkg-" + pid[:8], status_value, "webhook", "youtube_shorts",
                     "2026-01-01T00:00:00+00:00", "idem-" + pid, "ext-" + pid[:8] if kind == "published" else None,
                     now, now, now if kind == "published" else None, json.dumps(meta)))
        ids[kind] = pid
    con.commit()
    con.close()
    status, snap = call("POST", "/api/performance/snapshots", cookie, {"publish_id": ids["published"], "views": 1000})
    require(status == 200, f"own performance snapshot must be accepted: {status} {snap}")
    factory._integration_set("HubSpot", "connected", account_label=f"{MEMBERS[email]} CRM",
                             external_account_id=f"{MEMBERS[email]}-crm-portal", auth_mode="oauth",
                             connected_via="oauth", workspace_key=MEMBERS[email])
    return {"cookie": cookie, "job": job_id, "artifact": artifact, **ids}


def db_snapshot():
    con = factory.db()
    try:
        return {
            "jobs": [tuple(r) for r in con.execute("SELECT id,stage,status,updated_at FROM jobs ORDER BY id")],
            "publishing": [tuple(r) for r in con.execute(
                "SELECT id,status,scheduled_at,external_post_id,attempt_count FROM publishing_queue ORDER BY id")],
            "snapshots": con.execute("SELECT COUNT(*) FROM performance_snapshots").fetchone()[0],
            "artifacts": con.execute("SELECT COUNT(*) FROM artifacts").fetchone()[0],
            "decisions": con.execute("SELECT COUNT(*) FROM approval_decisions").fetchone()[0],
            "bindings": [tuple(r) for r in con.execute(
                "SELECT workspace_key,provider,state,external_account_id FROM integration_accounts ORDER BY 1,2")],
        }
    finally:
        con.close()


def check_isolation(me, other, my_ws, other_ws):
    c = me["cookie"]
    status, state = call("GET", "/api/status", c)
    require(status == 200 and state["workspace"] == my_ws, f"member status: {status}")
    require({j["id"] for j in state["jobs"]} == {me["job"]}, f"{my_ws} must only list its own job")
    require(all(e["job_id"] == me["job"] for e in state["events"]), f"{my_ws} events leak another workspace")
    for operator_key in ("supervisor", "relay", "usage", "buildProgress", "agentMetrics", "builderAutopilot"):
        require(operator_key not in state, f"member status must not expose operator telemetry '{operator_key}'")
    require(state["publishingSummary"] == {"published": 1, "scheduled": 1}, f"scoped publishing summary: {state['publishingSummary']}")
    require(state["performanceSummary"] == {"snapshots": 1, "published_items": 1}, "scoped performance summary")

    status, queue = call("GET", "/api/publishing", c)
    require({x["id"] for x in queue["items"]} == {me["published"], me["scheduled"]}, f"{my_ws} publishing queue leak")
    require(all(x["workspace_key"] == my_ws for x in queue["items"]), "publish items carry workspace identity")
    status, perf = call("GET", "/api/performance", c)
    require([x["publish"]["id"] for x in perf["items"]] == [me["published"]], f"{my_ws} analytics leak")
    require(all(x["attribution"]["job_id"] == me["job"] for x in perf["items"]), "CRM/attribution scoped to workspace")
    status, approval = call("GET", "/api/approval", c)
    require([x["job"]["id"] for x in approval["items"]] == [me["job"]], f"{my_ws} approval queue leak")
    status, own_artifacts = call("GET", f"/api/jobs/{me['job']}/artifacts", c)
    require(status == 200, f"own artifacts readable: {status}")

    status, integrations = call("GET", "/api/integrations", c)
    require(integrations["workspace"] == my_ws, "integration registry is the member's workspace")
    hub = integrations["connections"]["HubSpot"]
    require(hub["external_account_id"] == f"{my_ws}-crm-portal", f"{my_ws} sees its own CRM binding only: {hub}")
    require(other_ws not in json.dumps(integrations), f"{my_ws} integrations mention {other_ws}")
    require(integrations["connections"]["Metricool"]["state"] != "connected",
            "server Metricool credentials must not appear as a customer's connection")
    require(SECRET_TOKEN not in json.dumps(integrations) + json.dumps(state), "credential value leaked")

    before = db_snapshot()
    foreign_reads = [
        ("GET", f"/api/jobs/{other['job']}/artifacts"), ("GET", f"/api/jobs/{other['job']}/content-package"),
        ("GET", f"/api/jobs/{other['job']}/approval/history"), ("GET", f"/api/jobs/{other['job']}/quality"),
        ("GET", f"/api/performance/{other['published']}"), ("GET", f"/api/artifacts/{other['artifact']}/media"),
        ("GET", f"/api/jobs/{other['job']}/content-package/export.json"),
    ]
    foreign_writes = [
        ("POST", f"/api/jobs/{other['job']}/move", {"stage": "publish"}),
        ("POST", f"/api/jobs/{other['job']}/reject", {"reason": "sabotage"}),
        ("POST", f"/api/jobs/{other['job']}/approve", {}),
        ("POST", f"/api/jobs/{other['job']}/select", None),
        ("POST", f"/api/jobs/{other['job']}/run", None),
        ("POST", f"/api/publishing/{other['scheduled']}/schedule", {"scheduled_at": "2026-02-01T00:00:00+00:00"}),
        ("POST", f"/api/publishing/{other['scheduled']}/publish", None),
        ("POST", f"/api/publishing/{other['scheduled']}/dry-run", None),
        ("POST", f"/api/publishing/{other['published']}/confirm", {"external_post_id": "hijack"}),
        ("POST", f"/api/publishing/{other['published']}/refresh", None),
        ("POST", f"/api/performance/{other['published']}/sync", None),
    ]
    for method, path in foreign_reads:
        status, body = call(method, path, c)
        require(status == 404, f"{my_ws} {method} {path} must be 404, got {status}")
        require(other_ws not in json.dumps(body), f"404 body must not echo the other workspace: {body}")
    for method, path, body in foreign_writes:
        status, _ = call(method, path, c, body)
        require(status == 404, f"{my_ws} {method} {path} must be 404, got {status}")
    status, body = call("POST", "/api/performance/snapshots", c, {"publish_id": other["published"], "views": 999999})
    require(status == 400, f"foreign analytics snapshot must be rejected, got {status}")
    status, _ = call("DELETE", f"/api/artifacts/{other['artifact']}", c)
    require(status == 403, f"artifact delete is operator-only for members, got {status}")
    status, _ = call("POST", "/api/jobs", c, {"title": "cross-create", "workspace_key": other_ws})
    require(status == 403, "member cannot create a job in another workspace")
    status, _ = call("POST", "/api/integrations/HubSpot/disconnect", c)
    require(status == 200, "own disconnect works")
    after = db_snapshot()
    require(after["jobs"] == before["jobs"] and after["publishing"] == before["publishing"], f"{my_ws} mutated foreign data")
    require(after["snapshots"] == before["snapshots"] and after["artifacts"] == before["artifacts"]
            and after["decisions"] == before["decisions"], f"{my_ws} wrote foreign analytics/artifacts/approvals")
    changed = [b for b in after["bindings"] if b not in before["bindings"]]
    require(changed and all(b[0] == my_ws for b in changed), f"disconnect must only touch {my_ws}: {changed}")
    factory._integration_set("HubSpot", "connected", account_label=f"{my_ws} CRM", external_account_id=f"{my_ws}-crm-portal",
                             auth_mode="oauth", connected_via="oauth", workspace_key=my_ws)

    for path in ("/api/factory/tasks", "/api/supervisor", "/api/workspaces", "/api/content-brain", "/api/agents",
                 "/api/usage", "/api/viewer-invite", "/api/media-finisher", "/api/factory/worker-overview"):
        status, _ = call("GET", path, c)
        require(status == 403, f"member must not reach operator surface {path}, got {status}")
    status, _ = call("POST", f"/api/jobs/{me['job']}/idea-link/some-idea", c)
    require(status == 403, "member cannot link jobs to shared Content Brain ideas")
    status, connect = call("POST", "/api/integrations/Metricool/connect", c, {})
    require(status == 200 and connect.get("state") == "needs_setup", f"server Metricool secret not reusable: {connect}")


def check_owner(acme, globex):
    owner = cookie_for("owner")
    status, state = call("GET", "/api/status", owner)
    require({acme["job"], globex["job"]} <= {j["id"] for j in state["jobs"]}, "owner observes all workspaces")
    require("supervisor" in state, "owner status keeps operator telemetry")
    status, queue = call("GET", "/api/publishing", owner)
    require({acme["published"], globex["published"]} <= {x["id"] for x in queue["items"]}, "owner sees all publish items")
    status, ws = call("GET", "/api/workspaces", owner)
    by_key = {x["workspace"]: x for x in ws["workspaces"]}
    require(by_key["acme"]["jobs"] == 1 and by_key["globex"]["jobs"] == 1 and by_key["acme"]["members"] == 1,
            f"owner workspace overview: {ws}")
    require("secret script body" not in json.dumps(ws), "workspace overview is counts only")
    status, integrations = call("GET", "/api/integrations", owner)
    require(integrations["workspace"] == "default" and integrations["connections"]["Metricool"]["state"] == "connected",
            "owner's default workspace keeps the server Metricool binding")


def check_background_workers(acme, globex):
    # Default-workspace scheduled item so the fence is shown to be workspace-specific, not a blanket block.
    status, created = call("POST", "/api/jobs", cookie_for("owner"), {"title": "owner default job"})
    require(created["workspace_key"] == "default", "owner job defaults to the default workspace")
    pid = str(uuid.uuid4())
    con = factory.db()
    con.execute("""INSERT INTO publishing_queue(id,job_id,package_id,status,target,platform,scheduled_at,idempotency_key,
                   attempt_count,created_at,updated_at,meta_json) VALUES(?,?,?,?,?,?,?,?,0,?,?,?)""",
                (pid, created["id"], "pkg-default", "scheduled", "webhook", "youtube_shorts", "2026-01-01T00:00:00+00:00",
                 "idem-default", factory.ts(), factory.ts(), json.dumps({"content_snapshot": {"title": "d"}})))
    con.commit()
    con.close()
    sent = []

    def fake_external(url, method="GET", payload=None, token=""):
        sent.append(payload)
        return {"status": "published", "external_post_id": "post-" + payload["publish_id"][:6]}

    with patch.object(factory, "FACTORY_PUBLISHER_ADAPTER", "webhook"), \
            patch.object(factory, "FACTORY_PUBLISHER_ENDPOINT", "https://publisher.invalid/hook"), \
            patch.object(factory, "_external_json", fake_external):
        # A member-triggered run only touches its own workspace.
        status, member_run = call("POST", "/api/publishing/run-due", acme["cookie"])
        require(status == 200 and [r["workspace_key"] for r in member_run["results"]] == ["acme"], f"member run-due: {member_run}")
        require(member_run["results"][0]["status"] == "failed" and not sent,
                "acme publish must stop at the credential fence before any outbound call")
        # The system scheduler (unscoped) runs every due item under that item's own workspace identity.
        result = asyncio.run(factory.run_due_publishing())
    by_ws = {r["workspace_key"]: r for r in result["results"]}
    require(set(by_ws) == {"default", "globex"}, f"scheduler processes remaining due items per workspace: {result}")
    require(by_ws["default"]["status"] == "published", f"default workspace still publishes: {by_ws['default']}")
    require(by_ws["globex"]["status"] == "failed" and "publisher credentials" in by_ws["globex"]["message"], "globex fenced")
    require(len(sent) == 1 and sent[0]["workspace_key"] == "default", f"outbound payload carries workspace: {sent}")
    con = factory.db()
    rows = {r["id"]: r for r in con.execute("SELECT id,status,external_post_id FROM publishing_queue")}
    con.close()
    require(rows[acme["scheduled"]]["external_post_id"] is None and rows[globex["scheduled"]]["external_post_id"] is None,
            "fenced workspaces never receive a fabricated external post id")

    edit_id = str(uuid.uuid4())
    con = factory.db()
    con.execute("""INSERT INTO edit_jobs(id,production_job_id,input_url,profile_id,status,request_json,response_json,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (edit_id, globex["job"], "https://example.com/in.mp4", "talking_head_fast", "queued",
                 json.dumps({"compute_target": "local"}), json.dumps({"stage": "waiting_local_booster"}), "2000-01-01", "2000-01-01"))
    con.commit()
    con.close()
    claim = factory.local_booster_claim(factory.LocalBoosterHeartbeat())
    require(claim["job"]["id"] == edit_id and claim["job"]["workspace_key"] == "globex"
            and claim["job"]["request"]["workspace_key"] == "globex", f"Local Booster claim carries workspace: {claim}")

    seen = []

    async def probe():
        seen.append((tenancy.current(), factory.get_job(acme["job"]) is not None, factory.get_job(globex["job"]) is not None))

    asyncio.run(factory.run_in_job_workspace(acme["job"], probe()))
    require(seen == [("acme", True, False)], f"job task runs under its job's workspace only: {seen}")

    class FakeWS:
        def __init__(self):
            self.messages = []

        async def send_text(self, text):
            self.messages.append(json.loads(text))

    owner_ws, member_ws = FakeWS(), FakeWS()
    factory.clients.update({owner_ws, member_ws})
    factory.member_clients.add(member_ws)
    try:
        asyncio.run(factory.broadcast({"type": "publishing", "publishId": globex["published"], "status": "published"}))
    finally:
        factory.clients.difference_update({owner_ws, member_ws})
        factory.member_clients.discard(member_ws)
    require(owner_ws.messages[0]["publishId"] == globex["published"], "owner websocket keeps detailed events")
    require(member_ws.messages == [{"type": "refresh"}], "member websocket only receives a bare refresh")


def check_sessions():
    forged = factory._member_session_token("alice@acme.test", "globex")
    status, _ = call("GET", "/api/status", forged)
    require(status == 401, "a member token for a workspace the member is not assigned to is rejected")
    tampered = factory._member_session_token("alice@acme.test", "acme").replace("|acme|", "|globex|")
    status, _ = call("GET", "/api/status", tampered)
    require(status == 401, "a tampered member token is rejected")
    revoked = cookie_for("member", "alice@acme.test")
    with patch.object(factory, "FACTORY_WORKSPACE_MEMBERS", {"bob@globex.test": "globex"}):
        status, _ = call("GET", "/api/status", revoked)
    require(status == 401, "a removed member loses access immediately")
    require(factory._google_identity_role("alice@acme.test") == "member", "configured customers sign in as members")
    require(tenancy.parse_members("a@x.io=Acme, bad, c@x.io=../etc, d@x.io=ok_1") == {"a@x.io": "acme", "d@x.io": "ok_1"},
            "member map parsing normalizes keys and drops invalid entries")
    for invalid_ws in ("../", "/", "", "a" * 205):
        try:
            tenancy.normalize_workspace(invalid_ws)
            require(False, f"workspace key '{invalid_ws}' must be rejected")
        except ValueError:
            pass


def main():
    with patch.object(factory, "FACTORY_PASSWORD", "t553-test-password"), \
            patch.object(factory, "FACTORY_WORKSPACE_MEMBERS", dict(MEMBERS)), \
            patch.object(factory, "FACTORY_METRICOOL_TOKEN", SECRET_TOKEN), \
            patch.object(factory, "FACTORY_METRICOOL_USER_ID", "1"), \
            patch.object(factory, "FACTORY_METRICOOL_BLOG_ID", "2"), \
            patch.object(factory.urlrequest, "urlopen", no_network):
        status, _ = call("GET", "/api/status")
        require(status == 401, "anonymous access stays behind auth")
        acme = seed_workspace("alice@acme.test")
        globex = seed_workspace("bob@globex.test")
        check_isolation(acme, globex, "acme", "globex")
        check_isolation(globex, acme, "globex", "acme")
        check_owner(acme, globex)
        check_sessions()
        check_background_workers(acme, globex)
    require(not outbound, f"no outbound calls: {outbound}")
    print("T-553 workspace tenancy regression passed: two-workspace isolation for content, credentials, publishing "
          "queue and analytics; owner observability kept; background workers carry workspace identity")


if __name__ == "__main__":
    main()
