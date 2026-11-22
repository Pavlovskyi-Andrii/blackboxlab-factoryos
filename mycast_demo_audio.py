"""T-665: owner-made Gemini voicing of the MyCast demo city episodes (T-645-H, owner 2026-11-16).

The owner approved voicing the demo cards (Athens, Rome, Delphi, Olympia, Pompeii) with Gemini, within the free Google
quota only. Everything here is owner-triggered and owner-approved:

* Scripts are fixed files in the repo, `static/mycast-share/scripts/<city>.<lang>.json` (two hosts, sources listed).
  Nothing is written by a model at generation time; the server only voices the reviewed text.
* The owner presses "Generate" (one city or all) in the owner console. The server voices with the existing MyCast
  two-host TTS (`mycast.gemini_tts_pcm`; T-711: each city has its own pair of hosts from `demos.json`) and the server key, and keeps the MP3 under DATA_DIR, never in
  the repo. A generated track is not public.
* Idempotent: a track that exists is not voiced again unless the owner asks for "regenerate" explicitly.
* Limits: at most RUN_CAP (5) new generations per run and DAILY_CAP per UTC day; every attempt counts, failed ones too.
* HTTP 429 from Google stops the whole run at once with a plain "quota exhausted, try again tomorrow" message. There is
  no retry loop and no paid fallback.
* Only a track the owner listened to and approved is served publicly (`/mycast/demo/<city>.<lang>.mp3`) and played on
  the shared-episode page. Regenerating a track withdraws its approval.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

BASE = Path(__file__).parent
SCRIPTS_DIR = BASE / "static" / "mycast-share" / "scripts"
MANIFEST = BASE / "static" / "mycast-share" / "demos.json"
LANGS = ("uk", "ru", "en")
CITY_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
RUN_CAP = 5
DAILY_CAP = int(os.environ.get("MYCAST_DEMO_AUDIO_DAILY_CAP", "10") or 10)
DEFAULT_VOICES = ("Charon", "Kore")
PAUSE_SECONDS = 21.0          # between two voicings: stays under the free tier's few requests per minute
MAX_SCRIPT_CHARS = 2600       # one TTS chunk (mycast.CHUNK_CHARS is 2800): one request per city
MAX_LINES = 40
QUOTA_MESSAGE = {
    "ru": "Квота Google исчерпана: Google ответил 429. Генерация остановлена, новых запросов не отправлено. Повторите завтра.",
    "uk": "Квоту Google вичерпано: Google відповів 429. Генерацію зупинено, нових запитів не надіслано. Повторіть завтра.",
    "en": "The Google quota is used up: Google answered 429. Generation stopped and no further requests were sent. Try again tomorrow.",
}


class DemoAudioRefused(ValueError):
    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code, self.status = code, status


def _now_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_script(city: str, lang: str, scripts_dir: Path = SCRIPTS_DIR) -> dict:
    """A validated script, or DemoAudioRefused. Lines become [(host, text)] for mycast.gemini_tts_pcm."""
    if not CITY_RE.match(str(city)) or lang not in LANGS:
        raise DemoAudioRefused("unknown_track", 404)
    path = scripts_dir / f"{city}.{lang}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise DemoAudioRefused("no_script", 404) from None
    if not isinstance(data, dict):
        raise DemoAudioRefused("bad_script", 422)
    lines = data.get("lines")
    if data.get("id") != city or data.get("language") != lang or not isinstance(lines, list) or not 2 <= len(lines) <= MAX_LINES:
        raise DemoAudioRefused("bad_script", 422)
    out = []
    for line in lines:
        if not isinstance(line, dict) or line.get("host") not in ("A", "B") or not isinstance(line.get("text"), str):
            raise DemoAudioRefused("bad_script", 422)
        text = re.sub(r"[\u0000-\u001f]", " ", line["text"]).strip()
        if not text:
            raise DemoAudioRefused("bad_script", 422)
        out.append((line["host"], text))
    if sum(len(t) for _, t in out) > MAX_SCRIPT_CHARS:
        raise DemoAudioRefused("script_too_long", 422)
    sha = hashlib.sha256(json.dumps(out, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    return {"id": city, "language": lang, "lines": out, "sha": sha, "title": str(data.get("title") or city)[:120],
            "sources": [s for s in data.get("sources") or [] if isinstance(s, str)][:12]}


def manifest_cities(manifest: Path = MANIFEST) -> list[dict]:
    try:
        demos = json.loads(manifest.read_text(encoding="utf-8")).get("demos") or []
    except (OSError, ValueError, AttributeError):
        return []
    return [{"id": d["id"], "name": d.get("name") or {}, "voices": city_voices(d)} for d in demos
            if isinstance(d, dict) and CITY_RE.match(str(d.get("id") or ""))][:12]


def city_voices(demo: dict) -> list:
    """T-711: each demo city has its own pair of hosts, so the demos show different MyCast voices. A pair that is not a
    valid two-host pair of the catalogue (first male-by-ear, second female-by-ear) falls back to the default pair."""
    import mycast_voices
    pair = demo.get("voices")
    return list(pair) if mycast_voices.valid_voices("two_hosts", pair) else list(DEFAULT_VOICES)


class DemoAudioStore:
    def __init__(self, root: Path, *, api_key: Callable[[], str], tts: Callable, encode: Callable[[bytes, int], bytes],
                 qc: Optional[Callable] = None, clock: Callable[[], float] = time.time,
                 sleep: Callable[[float], None] = time.sleep, scripts_dir: Path = SCRIPTS_DIR,
                 manifest: Path = MANIFEST, daily_cap: int = DAILY_CAP, run_cap: int = RUN_CAP,
                 pause: float = PAUSE_SECONDS, background: bool = True):
        self.root, self.api_key, self.tts, self.encode, self.qc = Path(root), api_key, tts, encode, qc
        self.clock, self.sleep, self.scripts_dir, self.manifest = clock, sleep, Path(scripts_dir), Path(manifest)
        self.daily_cap, self.run_cap, self.pause, self.background = daily_cap, run_cap, pause, background
        self._lock = threading.Lock()          # state.json and the job record
        self._job: dict[str, Any] = {"state": "idle"}
        self._thread: Optional[threading.Thread] = None

    # ---- persistence ----------------------------------------------------------------------------------------------
    def _state_path(self) -> Path:
        return self.root / "state.json"

    def _load(self) -> dict:
        try:
            data = json.loads(self._state_path().read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path().with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self._state_path())

    def _day(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).strftime("%Y-%m-%d")

    def used_today(self, data: Optional[dict] = None) -> int:
        data = self._load() if data is None else data
        usage = data.get("usage") or {}
        return int(usage.get("count", 0)) if usage.get("day") == self._day() else 0

    def audio_path(self, city: str, lang: str) -> Path:
        if not CITY_RE.match(str(city)) or lang not in LANGS:
            raise DemoAudioRefused("unknown_track", 404)
        return self.root / f"{city}.{lang}.mp3"

    # ---- read side ------------------------------------------------------------------------------------------------
    def status(self) -> dict:
        data = self._load()
        tracks = data.get("tracks") or {}
        cities = []
        for c in manifest_cities(self.manifest):
            row = {"id": c["id"], "name": c["name"], "voices": c["voices"], "tracks": {}}
            for lang in LANGS:
                key = f"{c['id']}.{lang}"
                try:
                    script = load_script(c["id"], lang, self.scripts_dir)
                except DemoAudioRefused as exc:
                    row["tracks"][lang] = {"state": "no_script" if exc.code == "no_script" else "bad_script"}
                    continue
                rec = tracks.get(key) or {}
                exists = self.audio_path(c["id"], lang).is_file()
                state = ("approved" if rec.get("approved") is True else "generated") if exists else "none"
                item = {"state": state, "sources": script["sources"], "chars": sum(len(t) for _, t in script["lines"])}
                if rec.get("last_error"):
                    item["last_error"] = rec["last_error"]
                if exists:
                    item.update({"generated_at": rec.get("generated_at"), "seconds": rec.get("seconds"),
                                 "bytes": rec.get("bytes"), "stale": rec.get("script_sha") != script["sha"],
                                 "voices": rec.get("voices") or list(DEFAULT_VOICES),
                                 "voices_changed": (rec.get("voices") or list(DEFAULT_VOICES)) != c["voices"],
                                 "preview_url": f"/api/factory/mycast/demo-audio/{c['id']}/{lang}.mp3"})
                if state == "approved":
                    item.update({"approved_at": rec.get("approved_at"), "public_url": f"/mycast/demo/{c['id']}.{lang}.mp3"})
                row["tracks"][lang] = item
            cities.append(row)
        with self._lock:
            job = dict(self._job)
        return {"cities": cities, "job": job, "used_today": self.used_today(data), "daily_cap": self.daily_cap,
                "run_cap": self.run_cap, "configured": bool(self.api_key()), "last_quota_error": data.get("last_quota_error")}

    def is_approved(self, city: str, lang: str) -> bool:
        try:
            path = self.audio_path(city, lang)
        except DemoAudioRefused:
            return False
        rec = (self._load().get("tracks") or {}).get(f"{city}.{lang}") or {}
        return rec.get("approved") is True and path.is_file()

    def approved_url(self, city: str, lang: str) -> Optional[str]:
        """The public URL of an approved track: the page language first, then any other approved language."""
        for cand in (lang,) + tuple(x for x in LANGS if x != lang):
            if self.is_approved(city, cand):
                return f"/mycast/demo/{city}.{cand}.mp3"
        return None

    # ---- owner actions --------------------------------------------------------------------------------------------
    def set_approved(self, city: str, lang: str, approved: bool) -> dict:
        path = self.audio_path(city, lang)
        with self._lock:
            if self._job.get("state") == "running" and f"{city}.{lang}" in self._job.get("pending", []):
                raise DemoAudioRefused("generation_running", 409)
            if approved and not path.is_file():
                raise DemoAudioRefused("not_generated", 409)
            data = self._load()
            rec = data.setdefault("tracks", {}).setdefault(f"{city}.{lang}", {})
            rec["approved"] = bool(approved)
            rec["approved_at"] = _now_iso(self.clock()) if approved else None
            self._save(data)
        return {"id": city, "language": lang, "approved": bool(approved)}

    def start(self, cities: Any, lang: Any, *, regenerate: bool = False) -> dict:
        if lang not in LANGS:
            raise DemoAudioRefused("bad_language")
        voices = {c["id"]: c["voices"] for c in manifest_cities(self.manifest)}    # one manifest snapshot for both checks
        known = list(voices)
        if cities == "all":
            cities = known
        if not isinstance(cities, list) or not cities or any(c not in known for c in cities):
            raise DemoAudioRefused("unknown_city", 404)
        cities = list(dict.fromkeys(cities))
        if len(cities) > self.run_cap:
            raise DemoAudioRefused("run_limit")
        scripts = {c: load_script(c, lang, self.scripts_dir) for c in cities}
        for c in cities:
            scripts[c]["voices"] = voices[c]
        if not self.api_key():
            raise DemoAudioRefused("not_configured", 503)
        with self._lock:
            if self._job.get("state") == "running":
                raise DemoAudioRefused("generation_running", 409)
            todo = [c for c in cities if regenerate or not self.audio_path(c, lang).is_file()]
            skipped = [c for c in cities if c not in todo]
            if todo and self.used_today() >= self.daily_cap:
                raise DemoAudioRefused("daily_limit", 429)
            self._job = {"state": "running" if todo else "done", "language": lang, "regenerate": bool(regenerate),
                         "started_at": _now_iso(self.clock()), "pending": [f"{c}.{lang}" for c in todo],
                         "results": [{"id": c, "language": lang, "result": "cached"} for c in skipped], "message": ""}
            job = dict(self._job)
        if todo:
            if self.background:
                self._thread = threading.Thread(target=self._run, args=(todo, lang, scripts), daemon=True)
                self._thread.start()
            else:
                self._run(todo, lang, scripts)
                with self._lock:
                    job = dict(self._job)
        return job

    def _finish_job(self, state: str, message: str = "") -> None:
        with self._lock:
            self._job.update({"state": state, "pending": [], "finished_at": _now_iso(self.clock()), "message": message})

    def _result(self, city: str, lang: str, result: str, **extra) -> None:
        with self._lock:
            self._job["results"].append({"id": city, "language": lang, "result": result, **extra})
            self._job["pending"] = [p for p in self._job["pending"] if p != f"{city}.{lang}"]

    def _run(self, todo: list, lang: str, scripts: dict) -> None:
        import mycast
        for n, city in enumerate(todo):
            with self._lock:                                        # the daily cap is checked and charged per call
                data = self._load()
                used = self.used_today(data)
                if used >= self.daily_cap:
                    stop = True
                else:
                    stop = False
                    data["usage"] = {"day": self._day(), "count": used + 1}
                    self._save(data)
            if stop:
                for rest in todo[n:]:
                    self._result(rest, lang, "skipped_daily_limit")
                self._finish_job("stopped", "daily_limit")
                return
            if n:
                self.sleep(self.pause)
            script = scripts[city]
            try:
                pcm, rate = self.tts(self.api_key(), {"language": lang, "lines": script["lines"], "voices": list(script["voices"])})
                if self.qc:
                    self.qc(pcm, rate, script["lines"])
                mp3 = self.encode(pcm, rate)
                if not mp3:
                    raise RuntimeError("no_audio")
            except Exception as exc:
                category = str(getattr(exc, "category", "") or "")
                if category == "rate_limited":                     # 429: stop the run, no retry, no fallback
                    with self._lock:
                        data = self._load()
                        data["last_quota_error"] = _now_iso(self.clock())
                        self._save(data)
                    self._result(city, lang, "quota_exhausted")
                    for rest in todo[n + 1:]:
                        self._result(rest, lang, "not_started")
                    self._finish_job("stopped", "quota_exhausted")
                    return
                reason = (category or ("qc_failed" if isinstance(exc, mycast.AudioQCError) else "voice_failed"))[:40]
                with self._lock:
                    data = self._load()
                    data.setdefault("tracks", {}).setdefault(f"{city}.{lang}", {})["last_error"] = reason
                    self._save(data)
                self._result(city, lang, "failed", reason=reason)
                if category == "invalid_key":
                    for rest in todo[n + 1:]:
                        self._result(rest, lang, "not_started")
                    self._finish_job("stopped", "invalid_key")
                    return
                continue
            path = self.audio_path(city, lang)
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".part")
            tmp.write_bytes(mp3)
            with self._lock:
                os.replace(tmp, path)
                data = self._load()
                data.setdefault("tracks", {})[f"{city}.{lang}"] = {
                    "generated_at": _now_iso(self.clock()), "seconds": round(len(pcm) / 2 / max(1, rate), 1),
                    "bytes": len(mp3), "script_sha": script["sha"], "voices": list(script["voices"]), "approved": False, "approved_at": None}
                self._save(data)
            self._result(city, lang, "generated")
        self._finish_job("done")


# ---- owner console ------------------------------------------------------------------------------------------------
CONSOLE_COPY = {
    "title": "MyCast · демо-аудио городов",
    "intro": "Сценарии лежат в репозитории (static/mycast-share/scripts). Генерация — через Gemini TTS сервера. "
             "Бесплатность гарантирует только проект ключа без оплаты (Free tier в Google AI Studio): код лишь "
             "ограничивает число запросов и останавливается на 429. Сгенерированное не публикуется: публично играет только то, что вы прослушали "
             "и одобрили.",
}


def console_html() -> str:
    e = html.escape
    quota = json.dumps(QUOTA_MESSAGE["ru"], ensure_ascii=False)
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow"><title>{e(CONSOLE_COPY['title'])}</title>
<style>
body{{margin:0;background:#120e1f;color:#f4ecff;font:15px/1.45 system-ui,sans-serif}}main{{max-width:980px;margin:0 auto;padding:16px}}
h1{{font-size:22px;margin:8px 0}}.mute{{color:#b9add6}}.bar{{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:12px 0}}
button,select{{font:inherit;border-radius:10px;border:1px solid #5b4b8a;background:#2a2147;color:#f4ecff;padding:7px 12px;cursor:pointer}}
button[disabled]{{opacity:.45;cursor:not-allowed}}.ok{{background:#14532d;border-color:#22c55e}}.warn{{background:#5b1d1d;border-color:#ef4444}}
.card{{border:1px solid #3b2f63;border-radius:14px;padding:12px;margin:10px 0;background:#1a1530}}
.row{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}.tag{{font-size:12px;border-radius:99px;padding:2px 8px;background:#3b2f63}}
.tag.approved{{background:#14532d}}.tag.generated{{background:#6b4f12}}audio{{width:100%;max-width:420px;height:36px}}
#msg{{white-space:pre-wrap;padding:10px;border-radius:10px;background:#2a2147;display:none}}#msg.err{{background:#5b1d1d}}
a{{color:#c4b5fd;overflow-wrap:anywhere}}
</style></head><body><main>
<h1>{e(CONSOLE_COPY['title'])}</h1><p class="mute">{e(CONSOLE_COPY['intro'])}</p>
<div class="bar"><label>Язык <select id="lang"><option value="uk">Українська</option><option value="ru">Русский</option><option value="en">English</option></select></label>
<button id="all" type="button">Сгенерировать демо: все города</button>
<span id="quota" class="mute"></span></div>
<div id="msg" role="status"></div><div id="list" aria-live="polite"></div>
</main><script>
const QUOTA={quota};
const MSG={{daily_limit:'Дневной лимит генераций исчерпан. Повторите завтра.',run_limit:'Не больше 5 городов за запуск.',
not_configured:'На сервере нет ключа Gemini (FACTORY_GEMINI_API_KEY).',generation_running:'Уже идёт генерация — дождитесь окончания.',
quota_exhausted:QUOTA,invalid_key:'Google отклонил ключ Gemini (401/403). Генерация остановлена.',not_generated:'Сначала сгенерируйте аудио.',
no_script:'Для этого языка нет сценария.',bad_script:'Сценарий повреждён.',unknown_city:'Неизвестный город.'}};
const RES={{generated:'готово',cached:'уже было — пропущено',failed:'ошибка',quota_exhausted:'429 — квота Google',not_started:'не запускалось',skipped_daily_limit:'дневной лимит'}};
const $=s=>document.querySelector(s);let poll=null;
function esc(s){{return String(s==null?'':s).replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]))}}
function say(t,err){{const m=$('#msg');m.textContent=t;m.className=err?'err':'';m.style.display=t?'block':'none'}}
async function api(path,body){{const r=await fetch(path,body?{{method:'POST',headers:{{'content-type':'application/json'}},body:JSON.stringify(body)}}:{{}});
let j={{}};try{{j=await r.json()}}catch(_){{}};if(!r.ok)throw new Error(MSG[j.detail]||j.detail||('HTTP '+r.status));return j}}
async function gen(cities,regen){{say('');try{{const j=await api('/api/factory/mycast/demo-audio/generate',{{cities,language:$('#lang').value,regenerate:!!regen}});show(j)}}catch(e){{say(e.message,true)}};load()}}
async function approve(id,lang,ok){{try{{await api('/api/factory/mycast/demo-audio/'+id+'/'+lang+'/approve',{{approved:ok}});load()}}catch(e){{say(e.message,true)}}}}
function show(job){{if(!job||job.state==='idle')return;const lines=(job.results||[]).map(r=>r.id+'.'+r.language+': '+(RES[r.result]||r.result)+(r.reason?' ('+r.reason+')':''));
const pend=(job.pending||[]);const head=job.state==='running'?'Идёт генерация… осталось: '+pend.join(', '):(job.state==='stopped'?'Остановлено: '+(MSG[job.message]||job.message):'Готово.');
say(head+(lines.length?'\\n'+lines.join('\\n'):''),job.state==='stopped')}}
async function load(){{let s;try{{s=await api('/api/factory/mycast/demo-audio')}}catch(e){{say(e.message,true);return}}
const lang=$('#lang').value;$('#quota').textContent='Сегодня: '+s.used_today+' из '+s.daily_cap+' генераций'+(s.configured?'':' · ключа Gemini нет');
const running=s.job&&s.job.state==='running';$('#all').disabled=running||!s.configured;
$('#list').innerHTML=s.cities.map(c=>{{const t=c.tracks[lang]||{{state:'no_script'}};const name=(c.name&&(c.name.ru||c.name.uk))||c.id;
let h='<div class="card"><div class="row"><b>'+esc(name)+'</b><span class="tag '+esc(t.state)+'">'+esc({{none:'не сгенерировано',generated:'сгенерировано · ждёт одобрения',approved:'одобрено · играет на сайте',no_script:'нет сценария',bad_script:'сценарий повреждён'}}[t.state]||t.state)+'</span>'+(t.stale?'<span class="tag">сценарий изменился после генерации</span>':'')+(t.voices_changed?'<span class="tag">записано старыми голосами: '+esc((t.voices||[]).join(' + '))+'</span>':'')+'<span class="tag">ведущие: '+esc((c.voices||[]).join(' + '))+'</span>'+'</div>';
if(t.state!=='no_script'&&t.state!=='bad_script'){{h+='<div class="row" style="margin-top:8px">';
if(t.state==='none')h+='<button type="button" data-g="'+esc(c.id)+'"'+(running||!s.configured?' disabled':'')+'>Сгенерировать</button>';
else h+='<button type="button" data-r="'+esc(c.id)+'"'+(running||!s.configured?' disabled':'')+'>Перегенерировать</button>';
if(t.state==='generated')h+='<button type="button" class="ok" data-a="'+esc(c.id)+'">Одобрить</button>';
if(t.state==='approved')h+='<button type="button" class="warn" data-u="'+esc(c.id)+'">Снять одобрение</button>';
h+='</div>';if(t.preview_url)h+='<p><audio controls preload="none" src="'+esc(t.preview_url)+'?v='+esc(t.generated_at||'')+'"></audio> <span class="mute">'+esc(t.seconds||'')+' с</span></p>';
if(t.last_error)h+='<p class="mute">Последняя ошибка: '+esc(t.last_error)+'</p>';
if(t.sources&&t.sources.length)h+='<p class="mute">Источники: '+t.sources.map(u=>'<a href="'+esc(u)+'" target="_blank" rel="noopener noreferrer">'+esc(u.replace(/^https?:\\/\\//,''))+'</a>').join(' · ')+'</p>'}}
return h+'</div>'}}).join('');
document.querySelectorAll('[data-g]').forEach(b=>b.onclick=()=>gen([b.dataset.g],false));
document.querySelectorAll('[data-r]').forEach(b=>b.onclick=()=>{{if(confirm('Перегенерировать? Одобрение будет снято, уйдёт одна генерация из дневного лимита.'))gen([b.dataset.r],true)}});
document.querySelectorAll('[data-a]').forEach(b=>b.onclick=()=>{{if(confirm('Вы прослушали трек целиком? После одобрения он играет на публичной странице.'))approve(b.dataset.a,lang,true)}});
document.querySelectorAll('[data-u]').forEach(b=>b.onclick=()=>approve(b.dataset.u,lang,false));
if(s.job)show(s.job);clearTimeout(poll);if(running)poll=setTimeout(load,4000)}}
$('#all').onclick=()=>gen('all',false);$('#lang').onchange=load;load();
</script></body></html>"""


# ---- routes -------------------------------------------------------------------------------------------------------
def install_mycast_demo_audio_routes(app, store: DemoAudioStore, *, is_owner: Callable[[Request], bool]) -> None:
    def _err(exc: DemoAudioRefused):
        return JSONResponse({"detail": exc.code}, status_code=exc.status)

    def _denied():
        return JSONResponse({"detail": "owner only"}, status_code=403)

    async def _json(request: Request) -> dict:
        if "application/json" not in (request.headers.get("content-type") or ""):
            raise DemoAudioRefused("json_required", 415)            # no cross-site form posts
        try:
            body = await request.json()
        except ValueError:
            raise DemoAudioRefused("bad_json") from None
        return body if isinstance(body, dict) else {}

    @app.get("/factory/mycast-demos", include_in_schema=False)
    def mycast_demo_audio_console(request: Request):
        if not is_owner(request):
            return HTMLResponse("owner only", status_code=403)
        return HTMLResponse(console_html(), headers={"Cache-Control": "no-store", "X-Robots-Tag": "noindex, nofollow"})

    @app.get("/api/factory/mycast/demo-audio")
    def mycast_demo_audio_status(request: Request):
        if not is_owner(request):
            return _denied()
        return store.status()

    @app.post("/api/factory/mycast/demo-audio/generate")
    async def mycast_demo_audio_generate(request: Request):
        if not is_owner(request):
            return _denied()
        try:
            body = await _json(request)
            return store.start(body.get("cities"), body.get("language"), regenerate=body.get("regenerate") is True)
        except DemoAudioRefused as exc:
            return _err(exc)

    @app.post("/api/factory/mycast/demo-audio/{city}/{lang}/approve")
    async def mycast_demo_audio_approve(city: str, lang: str, request: Request):
        if not is_owner(request):
            return _denied()
        try:
            body = await _json(request)
            return store.set_approved(city, lang, body.get("approved") is True)
        except DemoAudioRefused as exc:
            return _err(exc)

    @app.get("/api/factory/mycast/demo-audio/{city}/{lang}.mp3")
    def mycast_demo_audio_preview(city: str, lang: str, request: Request):
        if not is_owner(request):
            return _denied()
        try:
            path = store.audio_path(city, lang)
        except DemoAudioRefused as exc:
            return _err(exc)
        if not path.is_file():
            return JSONResponse({"detail": "not_generated"}, status_code=404)
        return FileResponse(path, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})

    @app.get("/mycast/demo/{name}", include_in_schema=False)
    def mycast_demo_audio_public(name: str):
        """Public, but only an owner-approved track; anything else is a plain 404."""
        m = re.fullmatch(r"([a-z0-9][a-z0-9_-]{0,39})\.(uk|ru|en)\.mp3", name or "")
        if not m or not store.is_approved(m.group(1), m.group(2)):
            return Response(status_code=404, headers={"Cache-Control": "no-store"})
        return FileResponse(store.audio_path(m.group(1), m.group(2)), media_type="audio/mpeg",
                            headers={"Cache-Control": "public, max-age=600", "X-Robots-Tag": "noindex"})
