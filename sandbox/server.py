"""Independent, authenticated, static-only MVP ZIP preview on Render. Python stdlib."""
import hashlib
import hmac
import io
import json
import mimetypes
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path, PurePosixPath

TOKEN = os.getenv("SANDBOX_ADMIN_TOKEN", "")
ROOT = Path(tempfile.mkdtemp(prefix="factoryos-sandbox-"))
MAX_ZIP = 8 * 1024 * 1024
MAX_OUT = 32 * 1024 * 1024
MAX_FILES = 250
MAX_SITES = 8
ALLOWED = {".html",".htm",".css",".js",".mjs",".png",".jpg",".jpeg",".gif",".webp",".avif",".ico",".svg",".txt",".json",".woff",".woff2",".ttf",".map"}
SITES = {}
LOCK = threading.Lock()
TTL = 3600


class InvalidArchive(ValueError):
    pass


def extract_zip(raw, folder):
    if len(raw) > MAX_ZIP or not raw.startswith(b"PK"):
        raise InvalidArchive("Expected ZIP (max 8 MiB)")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries = [f for f in z.infolist() if not f.is_dir()]
        if len(entries) > MAX_FILES or sum(f.file_size for f in entries) > MAX_OUT:
            raise InvalidArchive("Extraction exceeds limits")
        parts = []
        for f in entries:
            p = PurePosixPath(f.filename)
            filetype = (f.external_attr >> 16) & 0o170000
            if (p.is_absolute() or ".." in p.parts or "\\" in f.filename or
                    filetype == 0o120000 or p.suffix.lower() not in ALLOWED or
                    (f.compress_size and f.file_size > f.compress_size * 200)):
                raise InvalidArchive("Invalid path, link, file type or compression ratio")
            parts.append(p.parts)
        common_prefix = bool(parts and all(len(p) > 1 and p[0] == parts[0][0] for p in parts))
        names = set()
        for f in entries:
            rel = PurePosixPath(*PurePosixPath(f.filename).parts[(1 if common_prefix else 0):])
            if not rel.parts or rel.as_posix() in names:
                raise InvalidArchive("Empty or duplicate path")
            names.add(rel.as_posix())
            out = folder.joinpath(*rel.parts)
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(f) as source, out.open("wb") as dest:
                shutil.copyfileobj(source, dest, 65536)
        if "index.html" not in names:
            raise InvalidArchive("Expected index.html in archive root")
        return len(names)


def import_zip(raw, name):
    site_id = uuid.uuid4().hex[:14]
    path = ROOT / site_id
    path.mkdir()
    try:
        count = extract_zip(raw, path)
        with LOCK:
            if len(SITES) >= MAX_SITES:
                raise InvalidArchive("Limit reached: max 8 previews per instance")
            info = {"id":site_id, "name":str(name)[:80], "files":count,
                    "sha256":hashlib.sha256(raw).hexdigest(), "created":int(time.time())}
            SITES[site_id] = info
        return info
    except Exception:
        shutil.rmtree(path, ignore_errors=True)
        raise


def sign(site_id, exp):
    return hmac.new(TOKEN.encode(), f"{site_id}:{exp}".encode(), hashlib.sha256).hexdigest()


def link(site_id):
    exp = int(time.time()) + TTL
    return f"/p/{site_id}/index.html?exp={exp}&sig={sign(site_id, exp)}"


def verified(site_id, exp, sig):
    try:
        exp = int(exp)
        return time.time() <= exp <= time.time() + TTL + 60 and hmac.compare_digest(sign(site_id, exp), sig)
    except (ValueError, TypeError):
        return False


PAGE = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>FactoryOS Sandbox</title><style>
body{background:#0c1426;color:#eaf2ff;font:16px system-ui;margin:0}main{max-width:750px;padding:28px;margin:auto}
h1{font-size:2rem}.card{border:1px solid #314260;background:#17233b;border-radius:16px;padding:24px;margin:20px 0}
input,button{border-radius:8px;padding:11px;background:#0d172b;color:white;border:1px solid #627392;max-width:100%;margin:4px}
input[type=password]{width:80%}button{cursor:pointer;background:#2154c1;border:0;font-weight:650}
p,small{color:#aabbd3}a{color:#98d5ff}li{margin:14px 0}#status{min-height:20px}
</style></head><body><main><h1>🧪 FactoryOS Sandbox</h1><p>Private, static-only ZIP previews for every MVP Center project · Free-tier.</p>
<div class="card"><h2>1. Access</h2><p>Enter the sandbox admin token. It is never stored in the browser.</p><input id="key" type="password" autocomplete="off" placeholder="Admin token"><button id="connect">Connect</button></div>
<div class="card"><h2>2. Import ZIP sites</h2><p>Up to 8 sites; 8 MiB each; static index.html required.</p><input id="files" type="file" multiple accept=".zip"><button id="upload">Import ZIP files</button><p>Or public Google Drive ZIP file:</p><input id="drive" placeholder="Google Drive URL / file ID"><button id="import">Import Drive ZIP</button></div>
<div class="card"><h2>3. Preview</h2><button id="refresh">Refresh</button><ul id="sites"></ul></div>
<p id="status">Connect to list private previews.</p><small>Safeguards: no uploaded code execution; previews expire after 1 hour. Render free instances are ephemeral; imports vanish on restart.</small>
<script>
const el=id=>document.getElementById(id);let key='';
function message(msg){el('status').textContent=msg}
async function api(path,opts={}){const r=await fetch(path,{...opts,headers:{Authorization:'Bearer '+key,...opts.headers}});let d=await r.json().catch(()=>({error:'Invalid response'}));if(!r.ok)throw Error(d.error||r.status);return d}
async function refresh(){try{let d=await api('/api/sites');el('sites').replaceChildren();for(let s of d.sites){let li=document.createElement('li'),a=document.createElement('a');a.href=s.preview;a.target='_blank';a.rel='noopener noreferrer';a.textContent=s.name+' — preview ('+s.files+' files)';li.append(a);el('sites').append(li)}message(d.sites.length+' site(s) ready')}catch(e){message('Error: '+e.message)}}
el('connect').onclick=()=>{key=el('key').value.trim();el('key').value='';refresh()};
el('refresh').onclick=refresh;
el('upload').onclick=async()=>{for(let f of el('files').files){try{let d=await api('/api/upload',{method:'POST',headers:{'Content-Type':'application/zip','X-Archive-Name':f.name},body:f});message('Imported '+d.name)}catch(e){message('Error importing '+f.name+': '+e.message)}}await refresh()};
el('import').onclick=async()=>{try{let d=await api('/api/import-drive',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({file:el('drive').value})});message('Imported '+d.name);await refresh()}catch(e){message('Drive error: '+e.message)}};
</script></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "FactoryOS-Sandbox/0.1"

    def response(self, code, data, mime="application/json", headers=None):
        raw = data if isinstance(data, bytes) else json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        for k,v in (headers or {}).items():
            self.send_header(k,v)
        self.end_headers()
        self.wfile.write(raw)

    def auth(self):
        return bool(len(TOKEN) >= 32 and hmac.compare_digest(self.headers.get("Authorization",""),"Bearer "+TOKEN))

    def body(self, limit=MAX_ZIP):
        try:
            n=int(self.headers.get("Content-Length","0"))
        except ValueError:
            n=0
        if n < 1 or n > limit:
            raise InvalidArchive("Request exceeds size limit or is empty")
        return self.rfile.read(n)

    def do_GET(self):
        url=urllib.parse.urlparse(self.path)
        if url.path == "/health":
            return self.response(200, {"ok":True,"service":"factoryos-sandbox","version":"0.1.0","static_only":True,"sites":len(SITES)})
        if url.path == "/":
            return self.response(200,PAGE.encode(),"text/html; charset=utf-8",{"Content-Security-Policy":"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'"})
        if url.path == "/api/sites":
            if not self.auth():
                return self.response(401,{"error":"Unauthorized"})
            with LOCK:
                sites=[dict(s,preview=link(s["id"])) for s in SITES.values()]
            return self.response(200,{"sites":sites,"persistent":False})
        if url.path.startswith("/p/"):
            segments=url.path.split("/",3)
            if len(segments) != 4 or not re.fullmatch("[0-9a-f]{14}",segments[2]):
                return self.response(404,{"error":"Not found"})
            site_id,rel=segments[2],urllib.parse.unquote(segments[3])
            query=urllib.parse.parse_qs(url.query)
            exp=query.get("exp",[""])[0];sig=query.get("sig",[""])[0]
            cookie=self.headers.get("Cookie","")
            matched=re.search(r"(?:^|;\s*)sb_preview=(\d+)\.([0-9a-f]{64})(?:;|$)",cookie)
            ok_query=verified(site_id,exp,sig)
            ok_cookie=bool(matched and verified(site_id,matched.group(1),matched.group(2)))
            if not (ok_query or ok_cookie):
                return self.response(403,{"error":"Preview link invalid or expired"})
            p=PurePosixPath(rel)
            if (site_id not in SITES or p.is_absolute() or ".." in p.parts or
                    "\\" in rel or p.suffix.lower() not in ALLOWED):
                return self.response(404,{"error":"Not found"})
            file=ROOT.joinpath(site_id,*p.parts)
            if not file.is_file():
                return self.response(404,{"error":"Missing file"})
            headers={"Content-Security-Policy":"sandbox allow-same-origin; default-src 'self' data:; script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'none'","X-Robots-Tag":"noindex,nofollow"}
            if ok_query:
                headers["Set-Cookie"]=f"sb_preview={exp}.{sig}; Path=/p/{site_id}/; Max-Age={TTL}; HttpOnly; Secure; SameSite=Lax"
            return self.response(200,file.read_bytes(),mimetypes.guess_type(str(file))[0] or "application/octet-stream",headers)
        return self.response(404,{"error":"Not found"})

    def do_POST(self):
        if not self.auth():
            return self.response(401,{"error":"Unauthorized"})
        try:
            if self.path == "/api/upload":
                name=os.path.basename(self.headers.get("X-Archive-Name","website.zip"))
                if not name.endswith(".zip"):
                    raise InvalidArchive("Only .zip accepted")
                info=import_zip(self.body(),name)
                return self.response(201,dict(info,preview=link(info["id"])))
            if self.path == "/api/import-drive":
                data=json.loads(self.body(2048))
                source=str(data.get("file",""))
                match=re.search(r"/file/d/([A-Za-z0-9_-]{15,})",source) or re.fullmatch(r"[A-Za-z0-9_-]{15,}",source)
                if not match:
                    raise InvalidArchive("Expected Drive file ID or Drive /file/d/ URL")
                file_id=match.group(1) if match.lastindex else match.group(0)
                class SafeRedirect(urllib.request.HTTPRedirectHandler):
                    def redirect_request(self,req,fp,code,msg,headers,newurl):
                        parsed=urllib.parse.urlparse(newurl)
                        if parsed.scheme != "https" or not (parsed.hostname in ("drive.google.com","drive.usercontent.google.com") or (parsed.hostname or "").endswith(".googleusercontent.com")):
                            raise InvalidArchive("Unsafe Google Drive redirect")
                        return super().redirect_request(req,fp,code,msg,headers,newurl)
                opener=urllib.request.build_opener(SafeRedirect)
                url="https://drive.google.com/uc?export=download&id="+file_id
                with opener.open(urllib.request.Request(url,headers={"User-Agent":"FactoryOS-Sandbox/0.1"}),timeout=12) as r:
                    raw=r.read(MAX_ZIP+1)
                info=import_zip(raw,"Drive-"+file_id[:12]+".zip")
                return self.response(201,dict(info,preview=link(info["id"])))
            return self.response(404,{"error":"Not found"})
        except (InvalidArchive,zipfile.BadZipFile,json.JSONDecodeError) as e:
            return self.response(400,{"error":str(e)})
        except Exception:
            return self.response(502,{"error":"Download/import failed; public sharing and valid ZIP are required"})


if __name__ == "__main__":
    if len(TOKEN) < 32:
        raise SystemExit("SANDBOX_ADMIN_TOKEN (>=32 chars) required")
    print("FactoryOS Sandbox startup; static ZIP previews only",flush=True)
    ThreadingHTTPServer(("0.0.0.0",int(os.getenv("PORT","10000"))),Handler).serve_forever()
