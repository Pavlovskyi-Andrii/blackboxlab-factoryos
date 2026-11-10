"""T-560-F Access vault: owner API routes + dashboard drawer regression.

Runs as a script (CI). Uses a throwaway DATA_DIR and a key generated per run; no network.
"""
import json
import os
from pathlib import Path
import re
import tempfile

TMP = tempfile.mkdtemp(prefix="factoryos-vault-ui-")
os.environ["DATA_DIR"] = TMP
os.environ.setdefault("FACTORY_PASSWORD", "")
os.environ.setdefault("FACTORY_LLM_API_KEY", "")
from browser_runner.vault import generate_key  # noqa: E402

os.environ["FACTORY_VAULT_KEY"] = generate_key()

import asyncio  # noqa: E402

import app  # noqa: E402


class _Resp:
    def __init__(self, status, body):
        self.status_code, self.text = status, body.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)


class Client:
    """Raw ASGI calls (same pattern as test_route_auth_fixes); no httpx dependency."""

    def _call(self, method, path, body=b""):
        headers = [(b"host", b"testserver"), (b"content-type", b"application/json")]
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
                 "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
                 "headers": headers, "server": ("testserver", 80), "client": ("127.0.0.1", 50000), "root_path": ""}
        sent, delivered = [], []

        async def receive():
            if not delivered:
                delivered.append(True)
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.Event().wait()

        async def send(message):
            sent.append(message)

        asyncio.run(app.app(scope, receive, send))
        start = next(m for m in sent if m["type"] == "http.response.start")
        return _Resp(start["status"], b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))

    def get(self, path):
        return self._call("GET", path)

    def post(self, path, json=None):
        import json as _json
        return self._call("POST", path, _json.dumps(json or {}).encode())

PASSWORD = "Route-Secret-Pa55"
COOKIE = "route-cookie-secret-77"
STATE = {"cookies": [{"name": "sid", "value": COOKIE, "domain": ".olx.ua", "path": "/", "expires": 1893456000}],
         "origins": [{"origin": "https://www.olx.ua", "localStorage": [{"name": "t", "value": COOKIE}]}]}


def require(cond, msg):
    if not cond:
        raise SystemExit("FAIL: " + msg)


def no_secret(resp, where):
    text = resp.text
    require(PASSWORD not in text and COOKIE not in text and os.environ["FACTORY_VAULT_KEY"] not in text,
            f"secret leaked in {where}")
    return resp


def routes():
    c = Client()
    post = lambda u, b: no_secret(c.post(u, json=b), u)

    r = post("/api/factory/vault/credentials", {"provider": "olx", "account": "shop",
                                                "username": "seller@example.com", "password": PASSWORD})
    require(r.status_code == 200 and r.json()["fields"] == ["password", "username"], f"save login {r.text}")
    ref = r.json()["ref"]
    r = post("/api/factory/vault/credentials", {"provider": "olx", "account": "shop", "password": PASSWORD + "2"})
    require(r.json()["ref"] == ref, "re-saving the same site/account must replace, not duplicate")

    r = post("/api/factory/vault/sessions", {"provider": "olx", "account": "shop", "storage_state": json.dumps(STATE)})
    require(r.status_code == 200 and r.json()["cookies"] == 1 and r.json()["domains"] == ["olx.ua"], f"save session {r.text}")

    st = no_secret(c.get("/api/factory/vault/status"), "status").json()
    require(st["configured"] and len(st["credentials"]) == 1 and len(st["sessions"]) == 1, f"status {st}")

    r = post("/api/factory/vault/check", {"provider": "olx", "account": "shop"}).json()
    require(r["ok"] and r["fields"] == ["password"], f"login check {r}")
    r = post("/api/factory/vault/check", {"provider": "olx", "account": "shop", "kind": "session"}).json()
    require(r["ok"] and r["cookies"] == 1, f"session check {r}")

    for body, code in (({"provider": "Bad Site!", "password": "x"}, 400),
                       ({"provider": "olx", "account": "a\"b", "password": "x"}, 400),
                       ({"provider": "olx", "account": "x"}, 400),
                       ({"provider": "olx", "otp": "123456"}, 400)):
        require(c.post("/api/factory/vault/credentials", json=body).status_code == code, f"validation {body}")
    require(c.post("/api/factory/vault/sessions", json={"provider": "olx", "storage_state": "{nope"}).status_code == 400,
            "bad session json accepted")
    require(c.post("/api/factory/vault/sessions", json={"provider": "olx", "storage_state": {"cookies": "x"}}).status_code == 400,
            "malformed storage_state accepted")

    require(post("/api/factory/vault/sessions/disconnect", {"provider": "olx", "account": "shop"}).json()["ok"], "disconnect")
    require(not post("/api/factory/vault/check", {"provider": "olx", "account": "shop", "kind": "session"}).json()["ok"],
            "session still usable after disconnect")
    require(post("/api/factory/vault/credentials/delete", {"provider": "olx", "account": "shop"}).json()["ok"], "delete")
    require(not no_secret(c.get("/api/factory/vault/status"), "status").json()["credentials"], "login not deleted")

    disk = b"".join(p.read_bytes() for p in Path(TMP, "vault").rglob("*") if p.is_file())
    require(PASSWORD.encode() not in disk and COOKIE.encode() not in disk, "plaintext on disk")

    # Non-owner is refused before anything is read or written.
    real = app.request_identity
    app.request_identity = lambda request: {"role": "viewer"}
    try:
        for u in ("/api/factory/vault/credentials", "/api/factory/vault/sessions", "/api/factory/vault/check",
                  "/api/factory/vault/credentials/delete", "/api/factory/vault/sessions/disconnect"):
            require(c.post(u, json={"provider": "olx", "password": "x"}).status_code in (401, 403), f"viewer allowed {u}")
        require(c.get("/api/factory/vault/status").status_code in (401, 403), "viewer allowed status")
    finally:
        app.request_identity = real

    # No key: status says why, writes are refused (fail closed).
    key = os.environ.pop("FACTORY_VAULT_KEY")
    try:
        st = c.get("/api/factory/vault/status").json()
        require(not st["configured"] and "FACTORY_VAULT_KEY" in st["reason"], f"unconfigured status {st}")
        r = c.post("/api/factory/vault/credentials", json={"provider": "olx", "password": "x"})
        require(r.status_code == 409 and "vault_not_configured" in r.text, "write without key not refused")
    finally:
        os.environ["FACTORY_VAULT_KEY"] = key
    print("Vault routes passed: save/replace/list/check/delete, session upload/disconnect, validation, owner-only, no key = refused, no secret in any response or on disk")


def dashboard():
    html = Path("static/index.html").read_text(encoding="utf-8")
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    require('id="vaultOpenBtn"' in html and 'onclick="openVault()"' in html, "vault button missing from Connections")
    for fn in ("openVault", "vaultRefresh", "vaultSaveLogin", "vaultSaveSession", "vaultCheck", "vaultRemove"):
        require(f"function {fn}(" in script or f"async function {fn}(" in script, f"{fn} missing")
    keys = set(re.findall(r"tr\('(vault\.[A-Za-z0-9_.]+)'", script)) | set(re.findall(r"'(vault\.limit\d)'", script))
    for lang in ("en", "uk", "ru"):
        line = next(l for l in script.split("\n") if l.startswith(f'Object.assign(I18N.{lang},{{"vault.open"'))
        table = json.loads(line[len(f"Object.assign(I18N.{lang},"):-2])
        missing = keys - set(table)
        require(not missing, f"{lang} missing vault keys {sorted(missing)}")
    require('type="password"' in script and "autocomplete=\"new-password\"" in script, "password field not masked")
    require("$('#vaultLoginPass').value=''" in script, "password not cleared after save")
    require("readOnly?'none':''" in script and "vaultOpenBtn" in script, "vault button not hidden for viewers")
    print(f"Vault drawer passed: button, 6 handlers, {len(keys)} keys x EN/UK/RU, masked password cleared after save, hidden for viewers")


if __name__ == "__main__":
    routes()
    dashboard()
