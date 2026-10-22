#!/usr/bin/env python3
import os, platform, socket, subprocess, sys, time, tempfile, json
from contextlib import ExitStack
from pathlib import Path
import requests
FACTORY_URL=os.environ.get("FACTORYOS_URL","https://blackboxlab-factoryos.onrender.com").rstrip("/")
TOKEN=os.environ.get("FACTORYOS_LOCAL_BOOSTER_TOKEN","").strip()
WORKER_URL=os.environ.get("FACTORYOS_LOCAL_WORKER_URL","http://127.0.0.1:10000").rstrip("/")
POLL=max(1.0,float(os.environ.get("FACTORYOS_LOCAL_BOOSTER_POLL_SEC","2.5")))
NODE_ID=os.environ.get("FACTORYOS_LOCAL_BOOSTER_NODE_ID",socket.gethostname() or "local-pc")
if not TOKEN:
    print("FACTORYOS_LOCAL_BOOSTER_TOKEN is required.");sys.exit(2)
session=requests.Session();session.headers.update({"Authorization":"Bearer "+TOKEN,"User-Agent":"FactoryOS-Local-Booster/1.0"})
def gpu_name():
    try:
        out=subprocess.check_output(["nvidia-smi","--query-gpu=name","--format=csv,noheader"],text=True,timeout=3)
        return out.strip().splitlines()[0][:120] if out.strip() else ""
    except Exception:return ""
def node_payload():
    return {"node_id":NODE_ID,"hostname":socket.gethostname(),"platform":platform.platform(),"cpu_count":os.cpu_count() or 0,"gpu":gpu_name(),"worker_url":WORKER_URL}
def cloud(method,path,**kwargs):
    r=session.request(method,FACTORY_URL+path,timeout=120,**kwargs);r.raise_for_status();return r.json() if r.content else {}
def worker(method,path,**kwargs):
    r=requests.request(method,WORKER_URL+path,timeout=120,**kwargs);r.raise_for_status();return r.json() if r.content else {}
def send_progress(job_id,state):
    cloud("POST",f"/api/local-booster/{job_id}/progress",json={"stage":str(state.get("stage") or state.get("status") or "processing"),"percent":int(state.get("percent") or 1),"status":"failed" if state.get("status")=="failed" else "processing","error":str(state.get("error") or ""),"detail":{"worker_status":state.get("status"),"graphics_engine":state.get("graphics_engine")}})
def download(url,dest):
    with requests.get(url,stream=True,timeout=180) as r:
        r.raise_for_status()
        with open(dest,"wb") as fh:
            for chunk in r.iter_content(1024*1024):
                if chunk:fh.write(chunk)
def upload_result(job_id,state):
    report=state.get("report") or {}
    with tempfile.TemporaryDirectory(prefix="factoryos-booster-") as td:
        td=Path(td);final_path=td/"final.mp4";download(WORKER_URL+f"/files/{job_id}/final.mp4",final_path)
        short_paths=[];clips=(((report.get("shorts_manifest") or {}).get("clips")) or [])
        for i,_ in enumerate(clips,1):
            p=td/f"short-{i:02d}.mp4"
            try:download(WORKER_URL+f"/files/{job_id}/short-{i:02d}.mp4",p);short_paths.append(p)
            except Exception:pass
        with ExitStack() as stack:
            files=[("final_file",(final_path.name,stack.enter_context(open(final_path,"rb")),"video/mp4"))]
            for p in short_paths:files.append(("shorts",(p.name,stack.enter_context(open(p,"rb")),"video/mp4")))
            data={"report_json":json.dumps(report,ensure_ascii=False),"wall_duration_sec":str(float(state.get("wall_duration_sec") or 0))}
            r=session.post(FACTORY_URL+f"/api/local-booster/{job_id}/complete",files=files,data=data,timeout=600);r.raise_for_status()
    print(f"[FactoryOS] {job_id[:8]} uploaded to durable storage")
def submit_local(job):
    job_id=job["id"];payload=dict(job["request"]);payload["callback_url"]="";print(f"[FactoryOS] claimed {job_id[:8]} -> local worker");worker("POST","/jobs",json=payload);last=(-1,"")
    while True:
        state=worker("GET",f"/jobs/{job_id}");marker=(int(state.get("percent") or 0),str(state.get("stage") or ""))
        if marker!=last:
            print(f"[{job_id[:8]}] {state.get('status')} · {marker[1]} · {marker[0]}%");last=marker
            try:send_progress(job_id,state)
            except Exception as exc:print("[warn] progress sync:",exc)
        if state.get("status") in ("ready","failed"):break
        time.sleep(POLL)
    if state.get("status")=="failed":send_progress(job_id,state);raise RuntimeError(state.get("error") or "local worker failed")
    upload_result(job_id,state)
def main():
    print("FactoryOS Local Render Booster");print("Factory:",FACTORY_URL);print("Worker:",WORKER_URL);print("Node:",node_payload())
    while True:
        try:
            cloud("POST","/api/local-booster/heartbeat",json=node_payload());job=(cloud("POST","/api/local-booster/claim",json=node_payload()) or {}).get("job")
            if job:
                try:submit_local(job)
                except Exception as exc:
                    print("[error]",exc)
                    try:cloud("POST",f"/api/local-booster/{job['id']}/progress",json={"stage":"failed","percent":0,"status":"failed","error":str(exc),"detail":{}})
                    except Exception:pass
            else:time.sleep(5)
        except KeyboardInterrupt:print("\nStopped.");return
        except Exception as exc:print("[offline]",exc);time.sleep(8)
if __name__=="__main__":main()
