import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from urllib import request as urlrequest

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

router = APIRouter()

BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE / "data")))
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB = DATA_DIR / "factory.db"
TELEGRAM_OWNER_FILE = DATA_DIR / "telegram_owner.json"
FACTORY_TELEGRAM_BOT_TOKEN = os.environ.get("FACTORY_TELEGRAM_BOT_TOKEN", "").strip()
FACTORY_PUBLIC_BASE_URL = (
    os.environ.get("FACTORY_PUBLIC_BASE_URL", "https://blackboxlab-factoryos.onrender.com").strip().rstrip("/")
    or "https://blackboxlab-factoryos.onrender.com"
)

STATUSES = ("inbox", "in_progress", "need_you", "done")
STATUS_LABELS = {
    "inbox": "Inbox",
    "in_progress": "In progress",
    "need_you": "Need you",
    "done": "Done",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _db():
    con = sqlite3.connect(DB, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=15000")
    return con


def init_companion_db() -> None:
    con = _db()
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS companion_tasks(
          id TEXT PRIMARY KEY,
          workspace_id TEXT NOT NULL DEFAULT 'default',
          user_id TEXT NOT NULL DEFAULT 'owner',
          source TEXT NOT NULL DEFAULT 'factoryos',
          source_kind TEXT NOT NULL DEFAULT 'text',
          source_ref TEXT NOT NULL DEFAULT '',
          title TEXT NOT NULL,
          body TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'inbox',
          result_text TEXT NOT NULL DEFAULT '',
          meta_json TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          completed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_companion_tasks_status
          ON companion_tasks(workspace_id,user_id,status,updated_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_companion_tasks_source_ref
          ON companion_tasks(workspace_id,source,source_ref)
          WHERE source_ref <> '';
        CREATE TABLE IF NOT EXISTS companion_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          task_id TEXT NOT NULL,
          kind TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL,
          meta_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_companion_events_task
          ON companion_events(task_id,id DESC);
        """
    )
    con.commit()
    con.close()


init_companion_db()


def _row(row):
    if not row:
        return None
    out = dict(row)
    try:
        out["meta"] = json.loads(out.pop("meta_json") or "{}")
    except Exception:
        out["meta"] = {}
        out.pop("meta_json", None)
    return out


def _extract_url(text: str) -> str:
    match = re.search(r"https?://[^\s<>()]+", str(text or ""))
    return match.group(0).rstrip(".,);]") if match else ""


def _title_for(title: str, body: str, source_kind: str, url: str) -> str:
    clean = " ".join(str(title or "").split()).strip()
    if clean:
        return clean[:180]
    if source_kind == "voice":
        return "Voice message"
    if url:
        host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url)).split("/", 1)[0]
        return f"Check: {host}"[:180]
    clean = " ".join(str(body or "").split()).strip()
    return (clean[:177] + "...") if len(clean) > 180 else (clean or "New checkpoint")


def _event(con, task_id: str, kind: str, note: str = "", meta: Optional[dict] = None) -> None:
    con.execute(
        "INSERT INTO companion_events(task_id,kind,note,created_at,meta_json) VALUES(?,?,?,?,?)",
        (task_id, kind, str(note or "")[:4000], _now(), json.dumps(meta or {}, ensure_ascii=False)),
    )


def _telegram_owner() -> dict:
    if not TELEGRAM_OWNER_FILE.exists():
        return {}
    try:
        data = json.loads(TELEGRAM_OWNER_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _telegram_send(chat_id: str, text: str, task_id: str = "") -> bool:
    chat_id = str(chat_id or "").strip()
    if not chat_id or not FACTORY_TELEGRAM_BOT_TOKEN:
        return False
    payload = {"chat_id": chat_id, "text": str(text or "")[:4000]}
    if task_id:
        payload["reply_markup"] = {
            "inline_keyboard": [[
                {"text": "Open task", "url": f"{FACTORY_PUBLIC_BASE_URL}/companion?task={task_id}"}
            ]]
        }
    req = urlrequest.Request(
        f"https://api.telegram.org/bot{FACTORY_TELEGRAM_BOT_TOKEN}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False
    return bool(isinstance(data, dict) and data.get("ok"))


def create_task(
    title: str = "",
    body: str = "",
    url: str = "",
    status: str = "inbox",
    source: str = "factoryos",
    source_kind: str = "text",
    source_ref: str = "",
    workspace_id: str = "default",
    user_id: str = "owner",
    meta: Optional[dict] = None,
    notify: bool = False,
) -> dict:
    status = str(status or "inbox").strip().lower()
    if status not in STATUSES:
        raise ValueError(f"Unsupported Companion status: {status}")
    workspace_id = str(workspace_id or "default").strip()[:120] or "default"
    user_id = str(user_id or "owner").strip()[:120] or "owner"
    source = str(source or "factoryos").strip()[:80] or "factoryos"
    source_kind = str(source_kind or "text").strip()[:80] or "text"
    source_ref = str(source_ref or "").strip()[:300]
    body = str(body or "").strip()[:20000]
    url = str(url or "").strip()[:3000] or _extract_url(body)
    title = _title_for(title, body, source_kind, url)
    meta = meta if isinstance(meta, dict) else {}

    con = _db()
    if source_ref:
        existing = con.execute(
            "SELECT * FROM companion_tasks WHERE workspace_id=? AND source=? AND source_ref=?",
            (workspace_id, source, source_ref),
        ).fetchone()
        if existing:
            con.close()
            return _row(existing)

    task_id = "C-" + uuid.uuid4().hex[:8].upper()
    now = _now()
    completed_at = now if status == "done" else None
    con.execute(
        """INSERT INTO companion_tasks(
             id,workspace_id,user_id,source,source_kind,source_ref,title,body,url,status,
             result_text,meta_json,created_at,updated_at,completed_at
           ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            task_id, workspace_id, user_id, source, source_kind, source_ref, title, body, url, status,
            "", json.dumps(meta, ensure_ascii=False), now, now, completed_at,
        ),
    )
    _event(con, task_id, "created", f"Created from {source}/{source_kind}", meta)
    con.commit()
    row = con.execute("SELECT * FROM companion_tasks WHERE id=?", (task_id,)).fetchone()
    con.close()
    task = _row(row)

    if notify or status == "need_you":
        owner = _telegram_owner()
        chat_id = str(owner.get("chat_id") or "")
        if chat_id:
            prefix = "🙋 Need you" if status == "need_you" else "📌 FactoryOS task"
            _telegram_send(chat_id, f"{prefix}\n{task_id} — {title}", task_id)
    return task


def list_tasks(
    status: str = "all",
    workspace_id: str = "default",
    user_id: str = "owner",
    limit: int = 200,
) -> list[dict]:
    limit = max(1, min(int(limit or 200), 500))
    con = _db()
    if status and status != "all":
        if status not in STATUSES:
            con.close()
            raise ValueError(f"Unsupported Companion status: {status}")
        rows = con.execute(
            """SELECT * FROM companion_tasks
               WHERE workspace_id=? AND user_id=? AND status=?
               ORDER BY updated_at DESC LIMIT ?""",
            (workspace_id, user_id, status, limit),
        ).fetchall()
    else:
        rows = con.execute(
            """SELECT * FROM companion_tasks
               WHERE workspace_id=? AND user_id=?
               ORDER BY CASE status
                 WHEN 'need_you' THEN 0 WHEN 'in_progress' THEN 1
                 WHEN 'inbox' THEN 2 ELSE 3 END,
                 updated_at DESC LIMIT ?""",
            (workspace_id, user_id, limit),
        ).fetchall()
    con.close()
    return [_row(x) for x in rows]


def get_task(task_id: str) -> dict:
    con = _db()
    row = con.execute("SELECT * FROM companion_tasks WHERE id=?", (task_id,)).fetchone()
    if not row:
        con.close()
        raise KeyError(task_id)
    events = con.execute(
        "SELECT id,kind,note,created_at,meta_json FROM companion_events WHERE task_id=? ORDER BY id",
        (task_id,),
    ).fetchall()
    con.close()
    task = _row(row)
    task["events"] = []
    for e in events:
        d = dict(e)
        try:
            d["meta"] = json.loads(d.pop("meta_json") or "{}")
        except Exception:
            d["meta"] = {}
            d.pop("meta_json", None)
        task["events"].append(d)
    return task


def update_task(
    task_id: str,
    status: Optional[str] = None,
    note: str = "",
    result_text: Optional[str] = None,
    notify: bool = False,
) -> dict:
    con = _db()
    current = con.execute("SELECT * FROM companion_tasks WHERE id=?", (task_id,)).fetchone()
    if not current:
        con.close()
        raise KeyError(task_id)

    updates = []
    values = []
    event_kind = "updated"
    if status is not None:
        status = str(status).strip().lower()
        if status not in STATUSES:
            con.close()
            raise ValueError(f"Unsupported Companion status: {status}")
        updates.append("status=?")
        values.append(status)
        event_kind = f"status:{status}"
        updates.append("completed_at=?")
        values.append(_now() if status == "done" else None)
    if result_text is not None:
        updates.append("result_text=?")
        values.append(str(result_text or "")[:20000])
        event_kind = "result"
    updates.append("updated_at=?")
    values.append(_now())
    values.append(task_id)
    con.execute(f"UPDATE companion_tasks SET {','.join(updates)} WHERE id=?", values)
    _event(con, task_id, event_kind, note or (result_text or "")[:1000])
    con.commit()
    row = con.execute("SELECT * FROM companion_tasks WHERE id=?", (task_id,)).fetchone()
    con.close()
    task = _row(row)

    if notify:
        owner = _telegram_owner()
        chat_id = str(owner.get("chat_id") or "")
        if chat_id:
            label = STATUS_LABELS.get(task["status"], task["status"])
            message = f"{'✅' if task['status']=='done' else '📌'} {task_id} — {task['title']}\nStatus: {label}"
            if task.get("result_text"):
                message += "\n\n" + task["result_text"][:3200]
            _telegram_send(chat_id, message, task_id)
    return task


def complete_task(task_id: str, result_text: str = "", notify: bool = True) -> dict:
    return update_task(task_id, status="done", result_text=result_text, note="Completed", notify=notify)


def task_summary(workspace_id: str = "default", user_id: str = "owner") -> dict:
    con = _db()
    rows = con.execute(
        """SELECT status,COUNT(*) c FROM companion_tasks
           WHERE workspace_id=? AND user_id=? GROUP BY status""",
        (workspace_id, user_id),
    ).fetchall()
    con.close()
    counts = {s: 0 for s in STATUSES}
    for row in rows:
        counts[row["status"]] = int(row["c"])
    return {
        "counts": counts,
        "open": counts["inbox"] + counts["in_progress"] + counts["need_you"],
        "total": sum(counts.values()),
    }


def ingest_telegram_message(
    chat_id: str,
    update_id: int,
    message_id: int = 0,
    text: str = "",
    source_kind: str = "text",
    source_file_id: str = "",
    username: str = "",
) -> dict:
    body = str(text or "").strip()
    if source_kind == "voice" and not body:
        body = "Voice message from Telegram"
    meta = {
        "telegram_chat_id": str(chat_id or ""),
        "telegram_update_id": int(update_id or 0),
        "telegram_message_id": int(message_id or 0),
        "telegram_username": str(username or ""),
    }
    if source_file_id:
        meta["telegram_file_id"] = str(source_file_id)
    task = create_task(
        body=body,
        source="telegram",
        source_kind=source_kind,
        source_ref=f"update:{int(update_id or 0)}",
        meta=meta,
        status="inbox",
    )
    _telegram_send(
        str(chat_id or ""),
        f"📥 Saved as {task['id']}\n{task['title']}\n\nI’ll keep the source, result and status in Companion history.",
        task["id"],
    )
    return task


class CompanionTaskCreate(BaseModel):
    title: str = ""
    body: str = ""
    url: str = ""
    status: str = "inbox"
    source: str = "factoryos"
    source_kind: str = "text"
    source_ref: str = ""
    workspace_id: str = "default"
    user_id: str = "owner"
    meta: dict = {}
    notify: bool = False


class CompanionStatusUpdate(BaseModel):
    status: str
    note: str = ""
    notify: bool = False


class CompanionResultUpdate(BaseModel):
    result_text: str = ""
    status: str = "done"
    notify: bool = True


@router.get("/api/companion/tasks")
def api_list_companion_tasks(status: str = "all", limit: int = 200):
    try:
        return {"tasks": list_tasks(status=status, limit=limit), "summary": task_summary()}
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/api/companion/tasks")
def api_create_companion_task(payload: CompanionTaskCreate):
    try:
        return create_task(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/api/companion/tasks/{task_id}")
def api_get_companion_task(task_id: str):
    try:
        return get_task(task_id)
    except KeyError:
        raise HTTPException(404, "Companion task not found")


@router.post("/api/companion/tasks/{task_id}/status")
def api_update_companion_status(task_id: str, payload: CompanionStatusUpdate):
    try:
        return update_task(task_id, status=payload.status, note=payload.note, notify=payload.notify)
    except KeyError:
        raise HTTPException(404, "Companion task not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.post("/api/companion/tasks/{task_id}/result")
def api_update_companion_result(task_id: str, payload: CompanionResultUpdate):
    try:
        return update_task(
            task_id,
            status=payload.status,
            result_text=payload.result_text,
            note="Result saved",
            notify=payload.notify,
        )
    except KeyError:
        raise HTTPException(404, "Companion task not found")
    except ValueError as exc:
        raise HTTPException(422, str(exc))


@router.get("/api/companion/summary")
def api_companion_summary():
    return task_summary()


@router.get("/companion", response_class=HTMLResponse)
def companion_page():
    return HTMLResponse(r"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>FactoryOS Companion</title>
<style>
:root{color-scheme:dark}*{box-sizing:border-box}body{margin:0;background:#07101a;color:#ecf7ff;font:14px Inter,system-ui,Arial}
main{max-width:760px;margin:auto;padding:18px 14px 90px}.top{display:flex;justify-content:space-between;align-items:center;gap:12px}
h1{font-size:22px;margin:0}.sub{color:#7890a5;font-size:12px;margin-top:4px}.badge{background:#10283a;border:1px solid #21465d;border-radius:999px;padding:7px 10px}
.tabs{display:flex;gap:7px;overflow:auto;padding:16px 0 12px;position:sticky;top:0;background:#07101af2;backdrop-filter:blur(12px);z-index:5}
.tabs button{white-space:nowrap;border:1px solid #203f55;background:#0b1b28;color:#8ca4b8;border-radius:10px;padding:9px 11px;font-weight:700}
.tabs button.active{background:#123b54;color:#fff;border-color:#1d6d94}.card{border:1px solid #17374d;background:linear-gradient(180deg,#0d1d2a,#091621);border-radius:14px;padding:13px;margin:9px 0}
.id{font:11px ui-monospace,monospace;color:#5fbce8}.title{font-weight:800;margin:5px 0}.body{color:#9cb0c1;font-size:13px;line-height:1.4;white-space:pre-wrap;max-height:72px;overflow:hidden}
.meta{display:flex;gap:8px;flex-wrap:wrap;margin-top:9px;color:#688298;font-size:11px}.result{margin-top:10px;padding:9px;border-left:2px solid #2ac4ff;background:#0a2130;color:#c8e7f5;white-space:pre-wrap}
.actions{display:flex;gap:7px;margin-top:10px}.actions button{border:1px solid #24485f;background:#0c2230;color:#dceef8;border-radius:9px;padding:7px 9px}
.empty{padding:36px 10px;text-align:center;color:#62798d}.composer{position:fixed;left:0;right:0;bottom:0;background:#07101af2;backdrop-filter:blur(14px);border-top:1px solid #17374d;padding:10px 14px max(10px,env(safe-area-inset-bottom))}
.composeInner{max-width:760px;margin:auto;display:flex;gap:8px}.composeInner input{flex:1;background:#0c1b27;color:#fff;border:1px solid #24485f;border-radius:11px;padding:12px}.composeInner button{border:0;border-radius:11px;padding:0 16px;background:#159ad2;color:#001018;font-weight:900}
</style></head><body><main>
<div class="top"><div><h1>FactoryOS Companion</h1><div class="sub">One inbox for links, voice notes, tasks and results.</div></div><div class="badge" id="openCount">0 open</div></div>
<div class="tabs" id="tabs"></div><div id="list"></div>
</main>
<div class="composer"><div class="composeInner"><input id="newTask" placeholder="Drop a link or write a task…"><button onclick="addTask()">Add</button></div></div>
<script>
const labels={inbox:'Inbox',in_progress:'In progress',need_you:'Need you',done:'Done'};let current='inbox';let data={tasks:[],summary:{counts:{}}};
function esc(s){return String(s||'').replace(/[&<>"']/g,function(c){return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]})}
async function load(){const r=await fetch('/api/companion/tasks?status=all');if(!r.ok)return;data=await r.json();render()}
function render(){const counts=(data.summary&&data.summary.counts)||{};document.getElementById('openCount').textContent=((counts.inbox||0)+(counts.in_progress||0)+(counts.need_you||0))+' open';
document.getElementById('tabs').innerHTML=Object.keys(labels).map(function(s){return '<button class="'+(s===current?'active':'')+'" onclick="current=\''+s+'\';render()">'+labels[s]+' '+(counts[s]||0)+'</button>'}).join('');
const rows=(data.tasks||[]).filter(function(x){return x.status===current});document.getElementById('list').innerHTML=rows.length?rows.map(card).join(''):'<div class="empty">Nothing here.</div>'}
function card(t){let action=t.status==='done'?'':'<div class="actions"><button onclick="setStatus(\''+t.id+'\',\'in_progress\')">Work</button><button onclick="setStatus(\''+t.id+'\',\'need_you\')">Need you</button><button onclick="setStatus(\''+t.id+'\',\'done\')">Done</button></div>';
let result=t.result_text?'<div class="result">'+esc(t.result_text)+'</div>':'';return '<div class="card"><div class="id">'+esc(t.id)+'</div><div class="title">'+esc(t.title)+'</div><div class="body">'+esc(t.body)+'</div>'+result+'<div class="meta"><span>'+esc(t.source)+' / '+esc(t.source_kind)+'</span><span>'+new Date(t.updated_at).toLocaleString()+'</span></div>'+action+'</div>'}
async function setStatus(id,status){await fetch('/api/companion/tasks/'+id+'/status',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status:status})});await load()}
async function addTask(){const el=document.getElementById('newTask'),v=el.value.trim();if(!v)return;await fetch('/api/companion/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({body:v,source:'companion',source_kind:/^https?:\/\//.test(v)?'link':'text'})});el.value='';current='inbox';await load()}
load();setInterval(load,15000);
</script></body></html>""")
