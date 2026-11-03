"""Owner-scoped voice settings and delivery metadata. No network calls during import/tests."""
from __future__ import annotations
import json
import os
import re
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from fastapi import HTTPException, Request
from mycast import gemini_tts_pcm, pcm_to_mp3, GeminiTTSError, DEFAULT_TTS_MODEL

VOICES=frozenset(("Charon","Kore","Puck","Zephyr","Achernar","Achird","Algenib","Algieba",
                  "Alnilam","Aoede","Autonoe","Callirrhoe","Despina","Enceladus","Erinome",
                  "Fenrir","Gacrux","Iapetus","Laomedeia","Leda","Orus","Pulcherrima",
                  "Rasalgethi","Sadachbia","Sadaltager","Schedar","Sulafat","Uma",
                  "Vindemiatrix","Zubenelgenubi"))
MODEL_ALLOWLIST=frozenset((DEFAULT_TTS_MODEL,))

class VoiceSettings:
    def __init__(self,path,default_a="Charon",default_b="Kore",default_model=DEFAULT_TTS_MODEL):
        self.path=Path(path);self.lock=threading.RLock()
        self.defaults={"voice_a":default_a if default_a in VOICES else "Charon",
                       "voice_b":default_b if default_b in VOICES else "Kore",
                       "model":default_model if default_model in MODEL_ALLOWLIST else DEFAULT_TTS_MODEL}
    def read(self):
        with self.lock:
            try:obj=json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError,ValueError):obj={}
            if not isinstance(obj,dict):obj={}
            return {k:(obj.get(k) if obj.get(k) in (VOICES if k.startswith("voice_") else MODEL_ALLOWLIST) else v)
                    for k,v in self.defaults.items()}
    def update(self,body):
        if not isinstance(body,dict) or set(body)-{"voice_a","voice_b","model"}:
            raise ValueError("Unsupported voice setting")
        data={**self.read(),**body}
        if data["voice_a"] not in VOICES or data["voice_b"] not in VOICES or data["model"] not in MODEL_ALLOWLIST:
            raise ValueError("Unknown voice or non-approved model")
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            tmp=self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data,ensure_ascii=False),encoding="utf-8")
            os.replace(tmp,self.path)
        return data

class VoiceHistory:
    def __init__(self,path):
        self.path=Path(path);self.lock=threading.RLock()
    def list(self):
        with self.lock:
            try:rows=json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError,ValueError):rows=[]
            return rows if isinstance(rows,list) else []
    def record(self,episode_id,kind,voice,seconds=0,status="sent"):
        record={"id":str(episode_id)[:100],"kind":kind if kind in ("mycast","brief") else "mycast",
                "voice":str(voice)[:100],"seconds":max(0,int(seconds or 0)),
                "status":status,"sent_at":datetime.now(timezone.utc).isoformat()}
        with self.lock:
            self.path.parent.mkdir(parents=True,exist_ok=True)
            try:rows=json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError,ValueError):rows=[]
            if not isinstance(rows,list):rows=[]
            rows=[r for r in rows if isinstance(r,dict) and r.get("id")!=record["id"]][-364:]+[record]
            tmp=self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(rows,ensure_ascii=False),encoding="utf-8")
            os.replace(tmp,self.path)
        return record

def install_voice_routes(app,settings,history,delivery_log,*,authorize_worker,identity_fn,api_key,paired,
                         send_audio,tts=gemini_tts_pcm,encode=pcm_to_mp3):
    def owner(request):
        if (identity_fn(request) or {}).get("role")!="owner":
            raise HTTPException(403,"Owner access required")
    @app.get("/api/factory/voice/settings")
    def get_settings(request:Request):
        owner(request)
        return {"settings":settings.read(),"available_voices":sorted(VOICES)}
    @app.post("/api/factory/voice/settings")
    async def set_settings(request:Request):
        owner(request)
        try:
            body=await request.json()
            return {"settings":settings.update(body)}
        except ValueError as exc:
            raise HTTPException(400,str(exc))
    @app.get("/api/factory/voice/history")
    def get_history(request:Request):
        owner(request)
        return {"deliveries":history.list()}
    @app.post("/api/factory/voice/worker/brief-deliver")
    async def brief_deliver(request:Request):
        if not authorize_worker(request):
            raise HTTPException(401,"Worker token required")
        try:body=await request.json()
        except Exception:raise HTTPException(400,"JSON required")
        if not isinstance(body,dict):raise HTTPException(400,"Bad request")
        day=str(body.get("date") or "")
        try:
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",day) or date.fromisoformat(day).isoformat()!=day:raise ValueError()
        except ValueError:raise HTTPException(400,"Invalid briefing date")
        text=str(body.get("text") or "").strip()
        # One short TTS request per morning. The full text briefing remains available separately.
        if not 1<=len(text)<=1400:raise HTTPException(413,"Voice briefing excerpt must be 1..1400 characters")
        if not api_key():raise HTTPException(409,"Gemini key not configured")
        if not paired():raise HTTPException(409,"Telegram not paired")
        episode_id="brief-"+day
        if not delivery_log.claim(episode_id):
            return {"sent":False,"duplicate":True,"id":episode_id}
        voices=settings.read()
        episode={"id":episode_id,"title":"MyBrief "+day,"language":"uk","lines":[["A",text]]}
        try:
            pcm,rate=tts(api_key(),episode,model=voices["model"],
                         voices=(voices["voice_a"],voices["voice_b"]))
            audio=encode(pcm,rate)
            send_audio(audio,episode_id+".mp3",episode["title"],"🎙 MyBrief · Gemini voice")
            history.record(episode_id,"brief",voices["voice_a"],seconds=round(len(pcm)/2/rate))
        except Exception as exc:
            delivery_log.release(episode_id)
            if isinstance(exc,GeminiTTSError):raise HTTPException(502,"Gemini TTS: "+exc.category)
            raise HTTPException(502,"Voice briefing delivery failed")
        return {"sent":True,"duplicate":False,"id":episode_id}
