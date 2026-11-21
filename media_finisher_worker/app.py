import hashlib
import hmac
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import request as urlrequest, error as urlerror
from urllib.parse import urlparse

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from media_finisher_worker import edit_decisions, qa_checks

APP_VERSION = "v4.6.0-worker"
BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FINISHER_DATA_DIR", "/var/data/media-finisher"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("PORT", "10000"))
_render_external_hostname = os.environ.get("RENDER_EXTERNAL_HOSTNAME", "").strip()
PUBLIC_BASE_URL = (os.environ.get("FINISHER_PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or (f"https://{_render_external_hostname}" if _render_external_hostname else f"http://localhost:{PORT}")).rstrip("/")
SHARED_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_SHARED_TOKEN", "").strip()
API_TOKEN = os.environ.get("FINISHER_API_TOKEN", "").strip() or SHARED_TOKEN
FACTORYOS_CALLBACK_BASE_URL = os.environ.get("FACTORYOS_CALLBACK_BASE_URL", "").rstrip("/")
if FACTORYOS_CALLBACK_BASE_URL and "://" not in FACTORYOS_CALLBACK_BASE_URL:
    FACTORYOS_CALLBACK_BASE_URL = "http://" + FACTORYOS_CALLBACK_BASE_URL
FACTORYOS_CALLBACK_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN", "").strip() or SHARED_TOKEN
WHISPER_MODEL = os.environ.get("FINISHER_WHISPER_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.environ.get("FINISHER_WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.environ.get("FINISHER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
GRAPHICS_ENGINE = os.environ.get("FINISHER_GRAPHICS_ENGINE", "remotion").strip().lower()
REMOTION_BROWSER = os.environ.get("REMOTION_BROWSER_EXECUTABLE", "/usr/bin/chromium").strip()
MAX_DOWNLOAD_BYTES = int(os.environ.get("FINISHER_MAX_DOWNLOAD_BYTES", str(750 * 1024 * 1024)))
ENABLE_PILOT_FIXTURE = os.environ.get("FINISHER_ENABLE_PILOT_FIXTURE", "").strip().lower() in ("1","true","yes","on")
LOW_MEMORY_MODE = os.environ.get("FINISHER_LOW_MEMORY_MODE", "").strip().lower() in ("1","true","yes","on")
_default_threads = 1 if LOW_MEMORY_MODE else max(2,min(8,int(os.cpu_count() or 4)))
CPU_THREADS = max(1,min(16,int(os.environ.get("FINISHER_CPU_THREADS",str(_default_threads)))))
MAX_RECOVERY_ATTEMPTS = max(1, int(os.environ.get("FINISHER_MAX_RECOVERY_ATTEMPTS", "3")))
RECOVER_INTERRUPTED = os.environ.get("FINISHER_RECOVER_INTERRUPTED", "").strip().lower() in ("1","true","yes","on")
if str(DATA_DIR).startswith("/tmp/") and "FINISHER_RECOVER_INTERRUPTED" not in os.environ:
    RECOVER_INTERRUPTED=False

app = FastAPI(title="FactoryOS AI Media Finisher", version=APP_VERSION)
_state_lock = threading.Lock()
_whisper_model = None


class JobRequest(BaseModel):
    edit_job_id: str = ""
    job_id: str
    factory_cycle_id: Optional[str] = None
    input_url: str
    profile: dict[str, Any]
    platform: str = "reels"
    content_package: dict[str, Any] = {}
    options: dict[str, Any] = {}
    rerun_stage: str = ""
    callback_url: str = ""
    guardrails: dict[str, Any] = {}


JOB_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
FILE_URL_TTL_SEC = max(60, int(os.environ.get("FINISHER_FILE_URL_TTL_SEC", str(24 * 3600))))
# Local development only: without an API token nothing can be signed, so files are refused unless this is set.
ALLOW_PUBLIC_FILES = os.environ.get("FINISHER_ALLOW_PUBLIC_FILES", "").strip().lower() in ("1","true","yes","on")


def _bearer_ok(request: Request) -> bool:
    supplied = (request.headers.get("authorization") or "").replace("Bearer ", "", 1).strip()
    return bool(API_TOKEN) and hmac.compare_digest(supplied.encode(), API_TOKEN.encode())


def _auth(request: Request):
    if not API_TOKEN:
        return
    if not _bearer_ok(request):
        raise HTTPException(401, "Invalid Media Finisher API token")


def _file_signature(job_id: str, filename: str, expires: int) -> str:
    """HMAC of one file of one job until one moment: the link opens that file only, and only until it expires."""
    return hmac.new(API_TOKEN.encode(), f"{job_id}/{filename}/{expires}".encode(), hashlib.sha256).hexdigest()[:40]


def _job_dir(job_id: str) -> Path:
    if not JOB_ID_RE.fullmatch(str(job_id or "")):
        raise HTTPException(400, "Bad job id")       # never a path: no dots, no slashes
    path = DATA_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _state_path(job_id: str) -> Path:
    return _job_dir(job_id) / "state.json"


def _read_state(job_id: str) -> dict:
    p = _state_path(job_id)
    if not p.exists():
        raise KeyError(job_id)
    return json.loads(p.read_text(encoding="utf-8"))


def _write_state(job_id: str, patch: Optional[dict] = None, replace: Optional[dict] = None) -> dict:
    with _state_lock:
        state = replace if replace is not None else (_read_state(job_id) if _state_path(job_id).exists() else {})
        if patch:
            state.update(patch)
        state["updated_at"] = time.time()
        tmp = _state_path(job_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_state_path(job_id))
        return state


def _run(cmd: list[str], *, capture: bool = True, cwd: Optional[Path] = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=True,
        timeout=timeout,
    )


def _run_ffmpeg_progress(job_id: str, cmd: list[str], duration: float, start_pct: int, end_pct: int, stage: str, timeout: int = 1800) -> subprocess.CompletedProcess:
    full=[cmd[0],"-hide_banner","-loglevel","error","-nostats","-progress","pipe:1",*cmd[1:]]
    proc=subprocess.Popen(full,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    started=time.time();last_pct=max(0,int(start_pct))
    try:
        assert proc.stdout is not None
        for raw in proc.stdout:
            if time.time()-started>timeout:
                proc.kill();raise subprocess.TimeoutExpired(full,timeout)
            line=raw.strip()
            if not line.startswith("out_time_ms=") or duration<=0:
                continue
            try:elapsed=max(0.0,float(line.split("=",1)[1])/1_000_000.0)
            except Exception:continue
            ratio=max(0.0,min(1.0,elapsed/max(.001,duration)))
            pct=int(round(start_pct+(end_pct-start_pct)*ratio))
            if pct>last_pct:
                last_pct=pct;_stage(job_id,stage,pct,elapsed_sec=round(elapsed,1),duration_sec=round(duration,1))
        stderr=proc.stderr.read() if proc.stderr is not None else ""
        rc=proc.wait(timeout=max(1,int(timeout-(time.time()-started))))
    except Exception:
        proc.kill()
        try:proc.wait(timeout=5)
        except Exception:pass
        raise
    if rc!=0:
        raise subprocess.CalledProcessError(rc,full,output="",stderr=stderr)
    if end_pct>last_pct:_stage(job_id,stage,end_pct,duration_sec=round(duration,1))
    return subprocess.CompletedProcess(full,rc,"",stderr)


def _download(url: str, dest: Path) -> None:
    if url.rstrip("/") == (PUBLIC_BASE_URL + "/pilot/source.mp4").rstrip("/"):
        local=_ensure_pilot_fixture()
        if not local:raise RuntimeError("Pilot fixture is unavailable")
        shutil.copy2(local,dest)
        return
    delays=[0,2,4,8,12,20]
    last=None
    part=dest.with_suffix(dest.suffix+".part")
    for attempt,delay in enumerate(delays,1):
        if delay:time.sleep(delay)
        try:
            if part.exists():part.unlink()
            req=urlrequest.Request(url,headers={"User-Agent":"FactoryOS-MediaFinisher/4.5"})
            total=0
            with urlrequest.urlopen(req,timeout=120) as resp,part.open("wb") as fh:
                while True:
                    chunk=resp.read(1024*1024)
                    if not chunk:break
                    total+=len(chunk)
                    if total>MAX_DOWNLOAD_BYTES:raise RuntimeError("Input media exceeds FINISHER_MAX_DOWNLOAD_BYTES")
                    fh.write(chunk)
            if total<=0:raise RuntimeError("Input media download returned an empty body")
            part.replace(dest)
            return
        except urlerror.HTTPError as exc:
            last=exc
            if int(getattr(exc,"code",0) or 0) not in (408,425,429,500,502,503,504) or attempt>=len(delays):raise
        except (urlerror.URLError,TimeoutError,ConnectionError) as exc:
            last=exc
            if attempt>=len(delays):raise
        print(json.dumps({"event":"MEDIA_FINISHER_DOWNLOAD_RETRY","attempt":attempt,"next_attempt":attempt+1,
                          "error":str(last)[:400]}),flush=True)
    raise RuntimeError(f"Input media download failed after retries: {last}")


def _probe(path: Path) -> dict:
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
    data = json.loads(result.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or audio.get("duration") or 0)
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1",
        "video_codec":str(video.get("codec_name") or ""),
        "audio_codec":str(audio.get("codec_name") or ""),
        "video_duration":_float_or_zero(video.get("duration")),
        "audio_duration":_float_or_zero(audio.get("duration")),
        "audio_channels":int(audio.get("channels") or 0),
    }


def _float_or_zero(value) -> float:
    try:return float(value)
    except (TypeError,ValueError):return 0.0


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding="utf-8")


def _validate_source(src: Path, job_dir: Path, input_url: str) -> dict:
    """Fail closed on a source FFprobe cannot read, and record what was received. The source file is never modified."""
    size=src.stat().st_size
    try:probe=_probe(src)
    except Exception as exc:
        raise RuntimeError("Unsupported source: FFprobe could not read the file") from exc
    problems=qa_checks.source_problems(probe,size)
    if problems:raise RuntimeError("Unsupported source: "+"; ".join(problems))
    digest=hashlib.sha256()
    with src.open("rb") as fh:
        for chunk in iter(lambda:fh.read(1024*1024),b""):digest.update(chunk)
    # Only the host is kept: the input URL can be a signed link.
    reference={"sha256":digest.hexdigest(),"size_bytes":size,"probe":probe,"source_host":urlparse(input_url).hostname or "",
               "original_modified":False}
    _write_json(job_dir/"source-reference.json",reference)
    return reference


def _effective_target(profile: dict) -> dict:
    target=dict(profile.get("target") or {})
    width,height,fps=int(target.get("width") or 1080),int(target.get("height") or 1920),int(target.get("fps") or 30)
    if LOW_MEMORY_MODE and (width>540 or height>960):
        scale=min(540/width,960/height)
        width=max(2,int(width*scale)//2*2);height=max(2,int(height*scale)//2*2)
        fps=min(fps,24)
    return {"width":width,"height":height,"fps":fps}


def _normalize_input(job_id: str, src: Path, dest: Path, profile: dict) -> None:
    # On the constrained Render worker, defer the expensive scale/encode until the cut pass.
    # This avoids encoding the full source twice before overlays.
    if LOW_MEMORY_MODE:
        shutil.copy2(src,dest)
        _stage(job_id,"normalize",20,mode="deferred_scale_fast")
        return
    source=_probe(src);duration=float(source.get("duration") or 0)
    target=_effective_target(profile)
    width,height,fps=target["width"],target["height"],target["fps"]
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    _run_ffmpeg_progress(job_id,[
        "ffmpeg", "-y", "-threads", str(CPU_THREADS), "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-threads", str(CPU_THREADS), "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(dest)
    ],duration,10,21,"normalize")


def _extract_audio(src: Path, wav: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


def _transcribe_words(job_id: str, wav: Path) -> tuple[list[dict], dict]:
    """Run ASR in a child process and stream segment progress back to FactoryOS."""
    output=wav.with_name("transcript-raw.json");duration=float(_probe(wav).get("duration") or 0)
    cmd=[sys.executable,"-m","media_finisher_worker.transcribe_runner",
         str(wav),str(output),WHISPER_MODEL,WHISPER_DEVICE,WHISPER_COMPUTE_TYPE]
    proc=subprocess.Popen(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    started=time.time();last_pct=22
    assert proc.stdout is not None
    for raw in proc.stdout:
        if time.time()-started>1200:
            proc.kill();raise subprocess.TimeoutExpired(cmd,1200)
        line=raw.strip()
        if not line.startswith("PROGRESS ") or duration<=0:continue
        try:elapsed=float(line.split(" ",1)[1])
        except Exception:continue
        pct=int(round(22+18*max(0.0,min(1.0,elapsed/max(.001,duration)))))
        if pct>last_pct:
            last_pct=pct;_stage(job_id,"transcript",pct,transcribed_sec=round(elapsed,1),duration_sec=round(duration,1))
    stderr=proc.stderr.read() if proc.stderr is not None else "";rc=proc.wait()
    if rc!=0:
        detail=(stderr or "").strip()[-1600:]
        raise RuntimeError("Whisper subprocess failed"+(": "+detail if detail else f" with exit code {rc}"))
    _stage(job_id,"transcript",40,duration_sec=round(duration,1))
    data=json.loads(output.read_text(encoding="utf-8"))
    return list(data.get("words") or []),dict(data.get("meta") or {})


def _detect_silences(src: Path, threshold: float, noise_db: float = -35.0) -> list[dict]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"silencedetect=noise={noise_db}dB:d={threshold}", "-f", "null", "-"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", proc.stderr or "")]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", proc.stderr or "")]
    return [{"start": round(s, 3), "end": round(e, 3), "reason": f"silence>{threshold:.2f}s"} for s, e in zip(starts, ends) if e > s]


def build_cut_list(silences: list[dict], words: list[dict], duration: float, profile: dict) -> list[dict]:
    """Source ranges to remove. The decisions behind them (reason, confidence, undo) come from `edit_decisions`."""
    return edit_decisions.plan_edits(silences,words,duration,profile)["cuts"]


def _keep_ranges(duration: float, cuts: list[dict]) -> list[tuple[float,float]]:
    keep: list[tuple[float,float]] = []
    cursor = 0.0
    for cut in cuts:
        start, end = float(cut["start"]), float(cut["end"])
        if start > cursor + 0.02:
            keep.append((cursor, start))
        cursor = max(cursor, end)
    if duration > cursor + 0.02:
        keep.append((cursor, duration))
    return keep or [(0.0, duration)]


def _apply_cuts(job_id: str, src: Path, dest: Path, duration: float, cuts: list[dict], profile: dict) -> None:
    target=_effective_target(profile);width,height,fps=target["width"],target["height"],target["fps"]
    scale_filter=f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    preset="ultrafast" if LOW_MEMORY_MODE else "veryfast";crf="26" if LOW_MEMORY_MODE else "20"
    if not cuts:
        _run_ffmpeg_progress(job_id,["ffmpeg","-y","-threads",str(CPU_THREADS),"-i",str(src),"-vf",scale_filter,
             "-c:v","libx264","-threads",str(CPU_THREADS),"-preset",preset,"-crf",crf,"-c:a","aac","-b:a","128k","-movflags","+faststart",str(dest)],
             duration,42,60,"cleanup")
        return
    keep = _keep_ranges(duration, cuts)
    parts = [];labels = []
    for i, (a,b) in enumerate(keep):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    filt = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(keep)}:v=1:a=1[joinv][outa];[joinv]{scale_filter}[outv]"
    output_duration=max(.1,duration-sum(max(0.0,float(x["end"])-float(x["start"])) for x in cuts))
    _run_ffmpeg_progress(job_id,["ffmpeg","-y","-threads",str(CPU_THREADS),"-i",str(src),"-filter_complex",filt,"-map","[outv]","-map","[outa]",
          "-c:v","libx264","-threads",str(CPU_THREADS),"-preset",preset,"-crf",crf,"-c:a","aac","-b:a","128k","-movflags","+faststart",str(dest)],
          output_duration,42,60,"cleanup")

def _removed_before(t: float, cuts: list[dict]) -> float:
    removed = 0.0
    for cut in cuts:
        start,end=float(cut["start"]),float(cut["end"])
        if t >= end:
            removed += end-start
        elif t > start:
            removed += t-start
            break
        else:
            break
    return removed


def map_words_after_cuts(words: list[dict], cuts: list[dict]) -> list[dict]:
    out=[]
    for word in words:
        mid=(float(word["start"])+float(word["end"]))/2
        if any(float(c["start"]) <= mid <= float(c["end"]) for c in cuts):
            continue
        start=float(word["start"])-_removed_before(float(word["start"]),cuts)
        end=float(word["end"])-_removed_before(float(word["end"]),cuts)
        if end > start:
            out.append({**word,"start":round(max(0,start),3),"end":round(max(0,end),3)})
    return out


def _caption(group: list[dict]) -> dict:
    words=[x["word"] for x in group]
    keyword=max(words,key=lambda x:len(re.sub(r"\W+","",x))) if words else ""
    return {"start":round(float(group[0]["start"]),3),"end":round(float(group[-1]["end"])+0.08,3),"words":words,"text":" ".join(words),"keyword":keyword}


def group_captions(words: list[dict], profile: dict, cut_output_times: Optional[list[float]] = None) -> list[dict]:
    cfg=profile.get("captions") or {}
    max_words=max(1,min(3,int(cfg.get("max_words") or 3)))
    cut_output_times=cut_output_times or []
    result=[];group=[]
    def crosses_cut(a:float,b:float)->bool:
        return any(a < x < b for x in cut_output_times)
    for word in words:
        if group and (len(group)>=max_words or crosses_cut(float(group[-1]["end"]),float(word["start"]))):
            result.append(_caption(group));group=[]
        group.append(word)
        if re.search(r"[.!?…]$",word["word"]):
            result.append(_caption(group));group=[]
    if group:result.append(_caption(group))
    # The 0.08 s tail must not show two groups at once or carry a group over a cut.
    for i,caption in enumerate(result):
        limits=[x for x in cut_output_times if caption["start"]<x<caption["end"]]
        if i+1<len(result):limits.append(float(result[i+1]["start"]))
        if limits and min(limits)<caption["end"]:
            caption["end"]=round(max(float(caption["start"])+.04,min(limits)),3)
    return result


def _cut_output_boundaries(cuts: list[dict]) -> list[float]:
    return [round(float(c["start"])-_removed_before(float(c["start"]),cuts),3) for c in cuts]


def _motion_timeline(output_duration: float, cuts: list[dict], profile: dict) -> list[dict]:
    cfg=profile.get("motion") or {};events=[]
    zmin=float(cfg.get("jump_cut_mask_zoom_min",0.07));zmax=float(cfg.get("jump_cut_mask_zoom_max",0.10))
    # A zoom covers a jump cut only when there is a visible jump: a very short removal barely moves the speaker, and
    # zooms closer together than `jump_cut_min_gap_sec` read as shaking.
    min_removed=float(cfg.get("jump_cut_min_removed_sec",0.25));min_gap=float(cfg.get("jump_cut_min_gap_sec",0.8))
    for i,t in enumerate(_cut_output_boundaries(cuts)):
        removed=float(cuts[i]["end"])-float(cuts[i]["start"])
        if removed<min_removed or (events and t-events[-1]["start"]<min_gap):
            continue
        zoom=1+(zmin+(zmax-zmin)*(i%3)/2)
        events.append({"start":max(0,t-0.06),"end":min(output_duration,t+0.32),"type":"jump_cut_mask_zoom","zoom":round(zoom,3)})
    deadline=float(cfg.get("opening_motion_deadline_sec",3.0))
    if output_duration>1 and not any(x["start"]<=deadline for x in events):
        events.append({"start":0.25,"end":min(2.5,output_duration),"type":"opening_push_in","zoom":1.08})
    interval=max(4.0,float(cfg.get("push_in_interval_sec",6.0)))
    t=interval
    while t < output_duration-1:
        if all(abs(t-x["start"])>2.5 for x in events):
            events.append({"start":round(t,2),"end":round(min(output_duration,t+1.4),2),"type":"subtle_push_in","zoom":1.06})
        t+=interval
    return sorted(events,key=lambda x:x["start"])


def _graphics_timeline(content_package: dict, output_duration: float, profile: dict, transcript_words: Optional[list[dict]] = None) -> list[dict]:
    cfg=profile.get("graphics") or {};limit=max(0,min(6,int(cfg.get("emphasis_max",5))))
    entries=[];source_type="approved_emphasis"
    for scene in content_package.get("scenes") or []:
        text=str((scene or {}).get("on_screen_text") or "").strip()
        if text and all(x["text"]!=text for x in entries):
            entries.append({"text":text,"start":None})
    if not entries:
        title=str(content_package.get("title") or "").strip()
        if title:
            entries.append({"text":title,"start":None})
    if not entries and content_package.get("_factoryos_manual_raw"):
        seen=set();candidates=[]
        for item in transcript_words or []:
            raw=str((item or {}).get("word") or "").strip()
            key=re.sub(r"[^\w]+","",raw.lower(),flags=re.UNICODE)
            if len(key)<4 or key in seen:
                continue
            seen.add(key);candidates.append({"text":raw,"start":float((item or {}).get("start") or 0)})
        if candidates:
            if len(candidates)>limit:
                idx=[round(i*(len(candidates)-1)/max(1,limit-1)) for i in range(limit)]
                candidates=[candidates[i] for i in idx]
            entries=candidates;source_type="transcript_exact_emphasis"
    entries=entries[:limit]
    if not entries:
        return []
    step=max(2.0,output_duration/(len(entries)+1))
    duration=max(1.15,min(2.4,float(cfg.get("duration_max_sec",2.0))+0.25))
    variants=["kinetic_title","lower_third","callout","badge"]
    out=[]
    for i,item in enumerate(entries):
        anchor=item.get("start")
        start=float(anchor) if anchor is not None else (i+1)*step
        start=min(max(.15,start-.18),max(.15,output_duration-.55))
        out.append({"start":round(start,2),"end":round(min(output_duration,start+duration),2),
                    "text":str(item["text"])[:70],"type":source_type,"variant":variants[i%len(variants)]})
    return out

def _write_srt(captions: list[dict], path: Path) -> None:
    def stamp(value:float)->str:
        ms=max(0,int(round(value*1000)));h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);sec,msec=divmod(rem,1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{msec:03d}"
    lines=[]
    for i,caption in enumerate(captions,1):
        lines.extend([str(i),f"{stamp(caption['start'])} --> {stamp(caption['end'])}",caption["text"],""])
    path.write_text("\n".join(lines),encoding="utf-8")


def _ass_stamp(value: float) -> str:
    cs=max(0,int(round(float(value)*100)));h,rem=divmod(cs,360000);m,rem=divmod(rem,6000);s,cs=divmod(rem,100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"

def _ass_text(value: str) -> str:
    return str(value or "").replace("\\","\\\\").replace("{","(").replace("}",")").replace("\n","\\N")

def _write_ass_overlays(captions: list[dict], graphics: list[dict], path: Path, width: int, height: int, zones: Optional[dict] = None) -> None:
    layout=qa_checks.ass_layout(width,height,zones or {})
    cap_size=layout["caption_font"];gfx_size=layout["graphic_font"];side=layout["margin_h"]
    lines=[
      "[Script Info]",f"PlayResX: {width}",f"PlayResY: {height}","WrapStyle: 0","ScaledBorderAndShadow: yes","",
      "[V4+ Styles]",
      "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
      f"Style: Caption,DejaVu Sans,{cap_size},&H00FFFFFF,&H0000FFFF,&H80000000,&H70000000,-1,0,0,0,100,100,0,0,3,2,0,2,{side},{side},{layout['caption_margin_v']},1",
      f"Style: Graphic,DejaVu Sans,{gfx_size},&H00EAFBFF,&H00EAFBFF,&H80306070,&H9005121C,-1,0,0,0,100,100,1,0,3,2,0,8,{side},{side},{layout['graphic_margin_v']},1","",
      "[Events]","Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"
    ]
    for x in captions:
        text=_ass_text(x.get("text") or " ".join(x.get("words") or []))
        lines.append(f"Dialogue: 0,{_ass_stamp(x.get('start',0))},{_ass_stamp(x.get('end',0))},Caption,,0,0,0,,{{\\fad(70,70)}}{text}")
    for x in graphics:
        text=_ass_text(x.get("text") or "")
        lines.append(f"Dialogue: 1,{_ass_stamp(x.get('start',0))},{_ass_stamp(x.get('end',0))},Graphic,,0,0,0,,{{\\fad(140,140)\\fscx88\\fscy88\\t(0,240,\\fscx100\\fscy100)}}{text}")
    path.write_text("\n".join(lines),encoding="utf-8")

def _render_ffmpeg_fast(job_id: str, clean: Path, dest: Path, captions: list[dict], graphics: list[dict], profile: dict, duration: float, job_dir: Path) -> None:
    target=_effective_target(profile);ass=job_dir/"overlays.ass";_write_ass_overlays(captions,graphics,ass,target["width"],target["height"],profile.get("safe_zones") or {})
    _run_ffmpeg_progress(job_id,["ffmpeg","-y","-threads",str(CPU_THREADS),"-i",str(clean),"-vf",f"ass={ass}",
        "-c:v","libx264","-threads",str(CPU_THREADS),"-preset","ultrafast","-crf","26","-c:a","copy","-movflags","+faststart",str(dest)],
        duration,70,83,"render")


def _render_with_remotion(clean: Path, dest: Path, captions: list[dict], motion: list[dict], graphics: list[dict], profile: dict, duration: float, job_dir: Path) -> None:
    remotion_dir=BASE/"remotion";public_jobs=remotion_dir/"public"/"jobs"/job_dir.name
    public_jobs.mkdir(parents=True,exist_ok=True)
    shutil.copy2(clean,public_jobs/"clean.mp4")
    target=_effective_target(profile);fps=target["fps"]
    props={
        "videoPath":f"jobs/{job_dir.name}/clean.mp4","captions":captions,"motion":motion,"graphics":graphics,
        "safeZones":profile.get("safe_zones") or {},"fps":fps,
        "durationInFrames":max(1,int(math.ceil(duration*fps))),
        "width":target["width"],"height":target["height"],
    }
    props_path=job_dir/"remotion-props.json";props_path.write_text(json.dumps(props,ensure_ascii=False),encoding="utf-8")
    concurrency="1" if LOW_MEMORY_MODE else str(max(2,min(4,CPU_THREADS//2 or 1)))
    cmd=["npx","remotion","render","src/index.tsx","MediaFinish",str(dest),"--props",str(props_path),"--codec","h264","--concurrency",concurrency,
         # Standard video levels: bt709, limited range, yuv420p. Remotion's default wrote full-range yuvj420p
         # (seen on a real render, 2026-11-20), which some players and platforms show with washed or crushed colours.
         "--color-space","bt709","--pixel-format","yuv420p"]
    if REMOTION_BROWSER and Path(REMOTION_BROWSER).exists():
        cmd.extend(["--browser-executable",REMOTION_BROWSER])
    try:_run(cmd,cwd=remotion_dir,timeout=3600)
    finally:shutil.rmtree(public_jobs,ignore_errors=True)


def _render_ffmpeg_fallback(clean: Path, dest: Path, captions_srt: Path) -> None:
    style="FontName=DejaVu Sans,FontSize=28,Bold=1,PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=360"
    _run(["ffmpeg","-y","-i",str(clean),"-vf",f"subtitles={captions_srt}:force_style='{style}'","-c:v","libx264","-preset","veryfast","-crf","20","-c:a","copy",str(dest)])


def _audio_finish(src: Path, dest: Path, profile: dict) -> dict:
    target=float((profile.get("audio") or {}).get("voice_target_lufs",-14.0))
    _run(["ffmpeg","-y","-i",str(src),"-af",f"loudnorm=I={target}:TP=-1.5:LRA=11","-c:v","copy","-c:a","aac","-b:a","192k","-movflags","+faststart",str(dest)])
    probe=subprocess.run(["ffmpeg","-hide_banner","-i",str(dest),"-af",f"loudnorm=I={target}:TP=-1.5:LRA=11:print_format=json","-f","null","-"],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    match=re.findall(r"\{\s*\"input_i\".*?\}",probe.stderr or "",flags=re.S)
    measured={}
    if match:
        try:measured=json.loads(match[-1])
        except Exception:measured={}
    # The reported loudness is a measurement of final.mp4 itself (EBU R128 integrated), not loudnorm's own
    # estimate of what a second pass would produce.
    meter=subprocess.run(["ffmpeg","-hide_banner","-nostats","-i",str(dest),"-vn","-af","ebur128=peak=true","-f","null","-"],text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False)
    voice_lufs,true_peak=qa_checks.parse_ebur128(meter.stderr or "")
    return {"target_voice_lufs":target,"voice_lufs":voice_lufs,"true_peak_dbfs":true_peak,"method":"ebur128_on_final_file","loudnorm_estimate":measured.get("output_i") if isinstance(measured,dict) else None,"measured":measured,"music_applied":False,"music_policy":"No approved music asset was supplied; none was added."}


def _frame_sampling_report(final: Path, cuts: list[dict], graphics: list[dict], duration: float, job_dir: Path) -> dict:
    """Persist lightweight visual QA samples around edit boundaries and graphics moments."""
    candidates=[{"time_sec":0.5,"reason":"opening"},{"time_sec":max(0.0,duration-0.5),"reason":"ending"}]
    boundaries=_cut_output_boundaries(cuts)
    if boundaries:
        step=max(1,len(boundaries)//4)
        for t in boundaries[::step][:4]:
            candidates.append({"time_sec":max(0.0,min(duration,float(t)+0.08)),"reason":"post_cut"})
    for item in (graphics or [])[:4]:
        mid=(float(item.get("start",0))+float(item.get("end",0)))/2
        candidates.append({"time_sec":max(0.0,min(duration,mid)),"reason":"graphic"})
    unique=[];seen=set()
    for item in candidates:
        key=round(float(item["time_sec"]),1)
        if key in seen:continue
        seen.add(key);unique.append(item)
        if len(unique)>=10:break
    samples=[]
    for i,item in enumerate(unique,1):
        name=f"qa-frame-{i:02d}.jpg";dest=job_dir/name
        try:
            _run(["ffmpeg","-y","-ss",f"{float(item['time_sec']):.3f}","-i",str(final),"-frames:v","1",
                  "-vf","scale=360:-2","-q:v","4",str(dest)],timeout=120)
            samples.append({"index":i,"time_sec":round(float(item["time_sec"]),3),"reason":item["reason"],
                            "url":_public_file(job_dir.name,name),"status":"captured"})
        except Exception as exc:
            samples.append({"index":i,"time_sec":round(float(item["time_sec"]),3),"reason":item["reason"],
                            "status":"failed","error":str(exc)[:240]})
    return {
        "method":"deterministic_frame_sampling_v1","requested":len(unique),
        "captured":sum(1 for x in samples if x.get("status")=="captured"),
        "samples":samples,"visual_review_required":True
    }


def _safe_zone_report(profile: dict, captions: list[dict], graphics: list[dict], frame_sampling: Optional[dict] = None, engine: str = "") -> dict:
    zones=profile.get("safe_zones") or {}
    frame_sampling=frame_sampling or {"method":"not_run","captured":0,"samples":[],"visual_review_required":True}
    target=_effective_target(profile)
    layout=qa_checks.safe_zone_violations(captions,zones,target["width"],target["height"],engine)
    return {
        "method":layout["method"],
        "top":float(zones.get("top",0.12)),"bottom":float(zones.get("bottom",0.20)),
        "right":float(zones.get("right",0.12)),"left":float(zones.get("left",0.0)),
        "caption_events":len(captions),"graphics_events":len(graphics),"violations":layout["violations"],
        "captions_checked":layout["checked"],"graphics_checked":0,
        "frame_sampling":frame_sampling,"visual_review_required":True,
        "note":"Caption boxes are estimated from the renderer's layout numbers, not read from pixels; emphasis graphics are not estimated. Sampled frames are persisted for human review of readability and face/object obstruction."
    }


def _final_media_checks(final: Path, duration: float) -> dict:
    """Decode every frame and audio sample of the final file and look for black or silent stretches (measured, not metadata)."""
    try:
        proc=subprocess.run(["ffmpeg","-hide_banner","-nostats","-xerror","-i",str(final),"-vf","blackdetect=d=0.5:pix_th=0.10",
                             "-af","silencedetect=noise=-50dB:d=2","-f","null","-"],
                            text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=False,timeout=900)
    except Exception as exc:
        skipped={"status":"not_run","detail":str(exc)[:240]}
        return {"decode":skipped,"black":dict(skipped),"silence":dict(skipped)}
    err=proc.stderr or ""
    if proc.returncode!=0:
        skipped={"status":"not_run","detail":"the file did not decode"}
        return {"decode":{"status":"fail","detail":err.strip()[-300:]},"black":skipped,"silence":dict(skipped)}
    black=[{"start":float(a),"end":float(b)} for a,b in re.findall(r"black_start:\s*([0-9.]+)\s+black_end:\s*([0-9.]+)",err)]
    starts=[float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)",err)]
    ends=[float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)",err)]
    ends+=[round(duration,3)]*(len(starts)-len(ends))
    silent=[{"start":s,"end":e} for s,e in zip(starts,ends)]
    return {"decode":{"status":"pass","detail":"all video frames and audio samples decoded"},
            "black":{"status":"warn" if black else "pass","ranges":black[:20],"rule":"black for 0.5 s or longer"},
            "silence":{"status":"warn" if silent else "pass","ranges":silent[:20],"rule":"below -50 dB for 2 s or longer"}}


def _children_usage() -> dict:
    try:
        import resource
        usage=resource.getrusage(resource.RUSAGE_CHILDREN)
        return {"cpu_sec":round(usage.ru_utime+usage.ru_stime,2),"peak_rss_mb":round(usage.ru_maxrss/1024,1)}
    except Exception:
        return {}


def _cleanup_intermediates(job_dir: Path) -> None:
    """Working copies are removed once the final file is verified; the downloaded source and the artifacts stay."""
    for name in ("normalized.mp4","clean.mp4","composed.mp4","audio.wav","transcript-raw.json","source.bin.part"):
        try:(job_dir/name).unlink()
        except OSError:pass


def _short_clip_windows(words: list[dict], duration: float, max_clips: int = 3) -> list[dict]:
    max_clips=max(1,min(8,int(max_clips or 3)))
    if duration<=0:return []
    target=min(45.0,max(18.0,duration if duration<45 else 35.0))
    if duration<=target+2:
        return [{"start_sec":0.0,"end_sec":round(duration,3),"score":1.0}]
    step=max(10.0,target/2)
    candidates=[];start=0.0
    while start<duration-8:
        end=min(duration,start+target)
        selected=[w for w in words if float(w.get("start",0))>=start and float(w.get("end",0))<=end]
        tokens=[re.sub(r"[^\w']+","",str(w.get("word") or "").lower()) for w in selected]
        tokens=[x for x in tokens if x]
        unique=len(set(tokens));density=len(tokens)/max(1.0,end-start)
        lexical=sum(1 for x in set(tokens) if len(x)>=6)
        score=density*12+unique*.18+lexical*.35
        candidates.append({"start_sec":round(start,3),"end_sec":round(end,3),"score":round(score,3)})
        start+=step
    chosen=[]
    for cand in sorted(candidates,key=lambda x:x["score"],reverse=True):
        center=(cand["start_sec"]+cand["end_sec"])/2
        if any(abs(center-(x["start_sec"]+x["end_sec"])/2)<target*.7 for x in chosen):
            continue
        chosen.append(cand)
        if len(chosen)>=max_clips:break
    return sorted(chosen,key=lambda x:x["start_sec"])


def _render_short_clips(final: Path, job_dir: Path, words: list[dict], duration: float, max_clips: int) -> dict:
    clips=[]
    for i,window in enumerate(_short_clip_windows(words,duration,max_clips),1):
        filename=f"short-{i:02d}.mp4";dest=job_dir/filename
        length=max(.5,float(window["end_sec"])-float(window["start_sec"]))
        _run(["ffmpeg","-y","-ss",f"{float(window['start_sec']):.3f}","-i",str(final),"-t",f"{length:.3f}",
              "-c","copy","-avoid_negative_ts","make_zero",str(dest)],timeout=900)
        clips.append({**window,"index":i,"duration_sec":round(length,3),"url":_public_file(job_dir.name,filename),
                      "targets":["youtube_shorts","instagram_reels"],"selector":"transcript_density_v1"})
    return {"enabled":True,"selector":"transcript_density_v1","clips":clips,"human_review_required":True}


def _public_file(job_id: str, filename: str) -> str:
    """Link to a job file. With an API token it is signed and expires (FINISHER_FILE_URL_TTL_SEC, default 24 h):
    FactoryOS downloads the result with it, and GET /jobs/{id} hands out a fresh one."""
    base = f"{PUBLIC_BASE_URL}/files/{job_id}/{filename}"
    if not API_TOKEN:
        return base
    expires = int(time.time()) + FILE_URL_TTL_SEC
    return f"{base}?exp={expires}&sig={_file_signature(job_id, filename, expires)}"


def _callback(state: dict) -> None:
    callback=str(state.get("callback_url") or "")
    if not callback:
        return
    if callback.startswith("/"):
        if not FACTORYOS_CALLBACK_BASE_URL:
            return
        callback=FACTORYOS_CALLBACK_BASE_URL+callback
    body={
        "status":state["status"],"final_url":state.get("final_url",""),"provider_job_id":state["id"],
        "error":state.get("error",""),"report":state.get("report") or {},
        "measured_cost_usd":0.0,"measured_duration_sec":float(state.get("wall_duration_sec") or 0),
        "raw":{"worker_version":APP_VERSION,"graphics_engine":state.get("graphics_engine"),"failed_stage":state.get("failed_stage","")}
    }
    headers={"Content-Type":"application/json"}
    if FACTORYOS_CALLBACK_TOKEN:headers["Authorization"]="Bearer "+FACTORYOS_CALLBACK_TOKEN
    req=urlrequest.Request(callback,data=json.dumps(body).encode("utf-8"),headers=headers,method="POST")
    try:
        with urlrequest.urlopen(req,timeout=30) as resp:resp.read()
    except Exception:
        pass


def _stage(job_id: str, stage: str, percent: Optional[int] = None, **extra) -> dict:
    patch={"stage":stage}
    if percent is not None:patch["percent"]=max(0,min(100,int(percent)))
    if extra:patch["progress"]=extra
    state=_write_state(job_id,patch)
    print(json.dumps({"event":"MEDIA_FINISHER_STAGE","job_id":job_id,"status":state.get("status"),"stage":stage,"percent":state.get("percent",0),**extra},ensure_ascii=False),flush=True)
    return state


def _process_one(job_id: str) -> None:
    started=time.time();state=_read_state(job_id);payload=state["request"];job_dir=_job_dir(job_id)
    marks=[("download",started)];usage_before=_children_usage()
    def mark(stage: str) -> None:marks.append((stage,time.time()))
    try:
        options=payload.get("options") or {}
        _write_state(job_id,{"status":"processing","stage":"download","percent":3,"error":""})
        print(json.dumps({"event":"MEDIA_FINISHER_STAGE","job_id":job_id,"status":"processing","stage":"download","percent":3}),flush=True)
        src=job_dir/"source.bin"
        if not src.exists() or src.stat().st_size<1024:_download(payload["input_url"],src)
        profile=(payload.get("profile") or {}).get("config") or {}
        mark("validate");_stage(job_id,"validate",8)
        source_reference=_validate_source(src,job_dir,str(payload.get("input_url") or ""))
        mark("normalize");_stage(job_id,"normalize",10)
        normalized=job_dir/"normalized.mp4";_normalize_input(job_id,src,normalized,profile)
        before=_probe(normalized);duration=float(before["duration"])
        mark("transcript");_stage(job_id,"transcript",22)
        wav=job_dir/"audio.wav";_extract_audio(normalized,wav)
        words,asr_meta=_transcribe_words(job_id,wav)
        cleanup=profile.get("speech_cleanup") or {};threshold=float(cleanup.get("pause_threshold_sec",0.4))
        silences=_detect_silences(normalized,threshold)
        plan=edit_decisions.plan_edits(silences,words,duration,profile,options.get("edit_overrides"))
        cuts=plan["cuts"];word_audit=edit_decisions.audit_cuts(words,cuts,plan["decisions"])
        _write_json(job_dir/"transcript.json",{"words":words,"asr":asr_meta,"timeline":"source"})
        _write_json(job_dir/"edit-decisions.json",{**plan,"word_audit":word_audit})
        mark("cleanup");_stage(job_id,"cleanup",42,words=len(words),cuts=len(cuts))
        clean=job_dir/"clean.mp4";_apply_cuts(job_id,normalized,clean,duration,cuts,profile)
        after_clean=_probe(clean);out_duration=float(after_clean["duration"])
        mapped_words=map_words_after_cuts(words,cuts)
        boundaries=_cut_output_boundaries(cuts)
        captions=group_captions(mapped_words,profile,boundaries) if options.get("add_captions",True) else []
        srt=job_dir/"captions.srt";_write_srt(captions,srt)
        motion=_motion_timeline(out_duration,cuts,profile) if options.get("add_animation",True) else []
        graphics=_graphics_timeline(payload.get("content_package") or {},out_duration,profile,mapped_words) if options.get("smart_graphics",True) else []
        mark("graphics");_stage(job_id,"graphics",62,captions=len(captions),motion=len(motion),graphics=len(graphics))
        composed=job_dir/"composed.mp4";engine="ffmpeg_fast" if LOW_MEMORY_MODE else GRAPHICS_ENGINE
        mark("render");_stage(job_id,"render",70)
        if engine=="ffmpeg_fast":
            _render_ffmpeg_fast(job_id,clean,composed,captions,graphics,profile,out_duration,job_dir)
        elif engine=="remotion":
            _render_with_remotion(clean,composed,captions,motion,graphics,profile,out_duration,job_dir)
        elif engine=="ffmpeg":
            if captions:_render_ffmpeg_fallback(clean,composed,srt)
            else:shutil.copy2(clean,composed)
            engine="ffmpeg_captions_only" if captions else "ffmpeg_passthrough"
        else:
            raise RuntimeError("Unsupported FINISHER_GRAPHICS_ENGINE; use remotion or ffmpeg")
        mark("audio");_stage(job_id,"audio",84)
        final=job_dir/"final.mp4";audio_report=_audio_finish(composed,final,profile)
        mark("qa");_stage(job_id,"qa",90)
        final_probe=_probe(final);final_duration=float(final_probe["duration"])
        media_checks=_final_media_checks(final,final_duration)
        if media_checks["decode"]["status"]=="fail":
            final.unlink()
            raise RuntimeError("Final render failed the decode check: "+str(media_checks["decode"].get("detail") or "")[:400])
        frame_sampling=_frame_sampling_report(final,cuts,graphics,final_duration,job_dir)
        safe=_safe_zone_report(profile,captions,graphics,frame_sampling,engine)
        removed_seconds=sum(float(x["end"])-float(x["start"]) for x in cuts)
        length=qa_checks.duration_check(duration,removed_seconds,final_duration)
        caption_issues=qa_checks.caption_timeline_issues(captions,boundaries,final_duration)
        loudness_ok=audio_report.get("voice_lufs") is not None and abs(float(audio_report["voice_lufs"])-float(audio_report["target_voice_lufs"]))<=1.5
        qa=qa_checks.qa_report([
            {"id":"source_valid","status":"pass","detail":"FFprobe read the source; video and audio streams present"},
            {"id":"final_decodes",**media_checks["decode"]},
            {"id":"words_at_cuts","status":"pass" if word_audit["ok"] else "fail",
             "lost_words":word_audit["lost_words"],"clipped_words":word_audit["clipped_words"],"removed_on_purpose":len(word_audit["removed_words"])},
            {"id":"wordless_slivers","status":"warn" if word_audit["wordless_slivers"] else "pass","slivers":word_audit["wordless_slivers"][:20],
             "meaning":"a short kept piece between two cuts with no transcribed word: listen for a leftover fragment"},
            {"id":"long_pauses_kept","status":"warn" if word_audit["long_pauses_kept"] else "pass","pauses":word_audit["long_pauses_kept"][:20],
             "meaning":"a pause of a second or more stayed in the video; restore-or-cut is the reviewer's call"},
            {"id":"captions_timeline","status":"fail" if caption_issues else "pass","issues":caption_issues[:50],"captions":len(captions)},
            {"id":"length_matches_cut_list","status":"pass" if length["ok"] else "fail",**length},
            {"id":"audio_video_streams",**qa_checks.stream_sync_check(final_probe)},
            {"id":"black_frames",**media_checks["black"]},
            {"id":"silent_stretches",**media_checks["silence"]},
            {"id":"voice_loudness","status":"not_run" if audio_report.get("voice_lufs") is None else ("pass" if loudness_ok else "warn"),
             "measured_lufs":audio_report.get("voice_lufs"),"target_lufs":audio_report.get("target_voice_lufs")},
            {"id":"caption_safe_zones","status":"not_run" if safe["method"]=="not_estimated_for_engine" else ("warn" if safe["violations"] else "pass"),
             "method":safe["method"],"violations":len(safe["violations"])},
        ])
        shorts_manifest={"enabled":False,"clips":[]}
        if options.get("split_shortform",False):
            mark("shorts_reels");_stage(job_id,"shorts_reels",92)
            shorts_manifest=_render_short_clips(final,job_dir,mapped_words,final_duration,int(options.get("max_short_clips") or 3))
        finished=time.time();usage_after=_children_usage()
        stage_seconds={name:round((marks[i+1][1] if i+1<len(marks) else finished)-at,3) for i,(name,at) in enumerate(marks)}
        render_metrics={
            "wall_sec":round(finished-started,3),"stage_seconds":stage_seconds,
            "realtime_factor":round((finished-started)/max(.001,duration),3),
            "child_cpu_sec":round(float(usage_after.get("cpu_sec") or 0)-float(usage_before.get("cpu_sec") or 0),2) if usage_after else None,
            "child_peak_rss_mb_since_worker_start":usage_after.get("peak_rss_mb"),
            "source_bytes":source_reference["size_bytes"],"final_bytes":final.stat().st_size,
            "cpu_threads":CPU_THREADS,"low_memory_mode":LOW_MEMORY_MODE,"measured_cost_usd":0.0,
        }
        output_cursor=0.0;keep_map=[]
        for a,b in _keep_ranges(duration,cuts):
            keep_map.append({"source_start":round(a,3),"source_end":round(b,3),"output_start":round(output_cursor,3)})
            output_cursor+=b-a
        _write_json(job_dir/"timeline.json",{"source_duration_sec":round(duration,3),"output_duration_sec":round(final_duration,3),
                                             "keep_ranges":keep_map,"captions":captions,"engine":engine,
                                             "motion":motion if engine=="remotion" else [],"graphics":graphics if engine=="remotion" else []})
        qa={**qa,"word_audit":word_audit}
        _write_json(job_dir/"qa-report.json",qa);_write_json(job_dir/"render-metrics.json",render_metrics)
        report={
            "edit_decisions":{k:plan[k] for k in ("version","pause_threshold","decisions","summary")},
            "qa_report":qa,"render_metrics":render_metrics,"source_reference":source_reference,
            "transcript_words":mapped_words,"transcript_corrections":[],"asr":asr_meta,"cut_list":cuts,
            "caption_timeline":captions,"motion_timeline":motion if engine=="remotion" else [],
            "graphics_timeline":graphics if engine=="remotion" else [],"shorts_manifest":shorts_manifest,
            "audio_report":audio_report,"safe_zone_report":safe,
            "edit_summary":{
                "duration_before_sec":round(duration,3),"duration_after_sec":round(float(final_probe["duration"]),3),
                "removed_segments":len(cuts),"removed_seconds":round(sum(float(x["end"])-float(x["start"]) for x in cuts),3),
                "filler_segments_removed":sum(1 for x in cuts if "filler_word:" in str(x.get("reason") or "")),
                "graphics_engine":engine,"profile_id":(payload.get("profile") or {}).get("id"),
                "profile_version":(payload.get("profile") or {}).get("version"),"platform":payload.get("platform"),
                "rerun_stage":payload.get("rerun_stage") or "full","human_review_required":True,
                "options":options,"output_target":_effective_target(profile),"low_memory_mode":LOW_MEMORY_MODE,
                "visual_checks_required":["face/object obstruction","caption readability","cut naturalness"]
            }
        }
        state=_write_state(job_id,{"status":"ready","stage":"done","percent":100,"final_url":_public_file(job_id,"final.mp4"),"report":report,
                                   "graphics_engine":engine,"wall_duration_sec":round(time.time()-started,3),"error":"","failed_stage":""})
        print(json.dumps({"event":"MEDIA_FINISHER_DONE","job_id":job_id,"status":"ready","wall_duration_sec":state.get("wall_duration_sec"),"final_url":state.get("final_url")},ensure_ascii=False),flush=True)
        _cleanup_intermediates(job_dir)
        _callback(state)
    except Exception as exc:
        state=_write_state(job_id,{"status":"failed","stage":"failed","failed_stage":marks[-1][0],"error":str(exc)[:1500],"wall_duration_sec":round(time.time()-started,3)})
        print(json.dumps({"event":"MEDIA_FINISHER_DONE","job_id":job_id,"status":"failed","failed_stage":marks[-1][0],"error":state.get("error"),"wall_duration_sec":state.get("wall_duration_sec")},ensure_ascii=False),flush=True)
        _callback(state)


_PROCESS_LOCK=threading.Lock()

def _process(job_id: str) -> None:
    queued=False
    if not _PROCESS_LOCK.acquire(blocking=False):
        queued=True
        _write_state(job_id,{"status":"queued","stage":"worker_queue","percent":2,"error":""})
        print(json.dumps({"event":"MEDIA_FINISHER_STAGE","job_id":job_id,"status":"queued","stage":"worker_queue","percent":2,
                          "reason":"single-heavy-job-worker"}),flush=True)
        _PROCESS_LOCK.acquire()
    try:
        if queued:
            print(json.dumps({"event":"MEDIA_FINISHER_QUEUE_RELEASE","job_id":job_id}),flush=True)
        _process_one(job_id)
    finally:
        _PROCESS_LOCK.release()



def _ensure_pilot_fixture() -> Optional[Path]:
    if not ENABLE_PILOT_FIXTURE:
        return None
    pilot_dir = DATA_DIR / "_pilot"
    pilot_dir.mkdir(parents=True, exist_ok=True)
    source = pilot_dir / "source.mp4"
    if source.exists() and source.stat().st_size > 10000:
        return source
    first = pilot_dir / "first.wav"
    second = pilot_dir / "second.wav"
    silence = pilot_dir / "silence.wav"
    speech = pilot_dir / "speech.wav"
    _run(["espeak-ng","-s","155","-v","en-us","-w",str(first),"Factory OS finds the pauses."])
    _run(["espeak-ng","-s","155","-v","en-us","-w",str(second),"Then it cuts the dead air. Adds captions. Adds captions. And sends the final video back for human approval."])
    _run(["ffmpeg","-y","-f","lavfi","-i","anullsrc=r=22050:cl=mono","-t","0.85","-c:a","pcm_s16le",str(silence)])
    _run([
        "ffmpeg","-y","-i",str(first),"-i",str(silence),"-i",str(second),
        "-filter_complex",
        "[0:a]aresample=48000[a0];[1:a]aresample=48000[a1];[2:a]aresample=48000[a2];[a0][a1][a2]concat=n=3:v=0:a=1[out]",
        "-map","[out]","-c:a","pcm_s16le",str(speech)
    ])
    _run([
        "ffmpeg","-y","-f","lavfi","-i","color=c=0x111827:s=1080x1920:r=30",
        "-i",str(speech),"-shortest","-c:v","libx264","-preset","veryfast","-crf","22",
        "-pix_fmt","yuv420p","-c:a","aac","-b:a","160k","-ar","48000","-movflags","+faststart",str(source)
    ])
    return source


@app.on_event("startup")
def startup_pilot_fixture():
    if ENABLE_PILOT_FIXTURE:
        print(json.dumps({"event":"FINISHER_PILOT_FIXTURE","status":"lazy","note":"generated only when /pilot/source.mp4 is requested"}),flush=True)


@app.on_event("startup")
def recover_interrupted_jobs():
    if not RECOVER_INTERRUPTED:
        print(json.dumps({"event":"MEDIA_FINISHER_RECOVERY_DISABLED","data_dir":str(DATA_DIR),"reason":"main FactoryOS owns retry/recovery for ephemeral workers"}),flush=True)
        return
    recovered=0
    for state_path in DATA_DIR.glob("*/state.json"):
        try:
            state=json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if state.get("status") not in ("queued","processing"):
            continue
        job_id=str(state.get("id") or state_path.parent.name)
        recovery_count=int(state.get("recovery_count") or 0)+1
        if recovery_count>MAX_RECOVERY_ATTEMPTS:
            _write_state(job_id,{"status":"failed","stage":"failed","error":"Processing was interrupted repeatedly; manual retry required.","recovery_count":recovery_count})
            print(json.dumps({"event":"MEDIA_FINISHER_RECOVER_GIVEUP","job_id":job_id,"attempts":recovery_count}),flush=True)
            continue
        _write_state(job_id,{"recovery_count":recovery_count})
        recovered+=1
        print(json.dumps({"event":"MEDIA_FINISHER_RECOVER","job_id":job_id,"previous_stage":state.get("stage"),"attempt":recovery_count}),flush=True)
        threading.Thread(target=_process,args=(job_id,),daemon=True,name=f"recover-{job_id[:8]}").start()
    if recovered:
        print(json.dumps({"event":"MEDIA_FINISHER_RECOVERY_SUMMARY","recovered":recovered}),flush=True)


@app.get("/pilot/source.mp4")
def pilot_source():
    if not ENABLE_PILOT_FIXTURE:
        raise HTTPException(404,"Pilot fixture is disabled")
    path=_ensure_pilot_fixture()
    if not path or not path.exists():
        raise HTTPException(503,"Pilot fixture is not ready")
    return FileResponse(path,media_type="video/mp4",filename="factoryos-v45-pilot-source.mp4")


@app.get("/health")
def health():
    return {"ok":True,"version":APP_VERSION,"graphics_engine":GRAPHICS_ENGINE,"whisper_model":WHISPER_MODEL,
            "low_memory_mode":LOW_MEMORY_MODE,"cpu_threads":CPU_THREADS,
            "callback_configured":bool(FACTORYOS_CALLBACK_BASE_URL),"auth_configured":bool(API_TOKEN)}


@app.post("/jobs")
def create_job(payload: JobRequest, background: BackgroundTasks, request: Request):
    _auth(request)
    if not payload.input_url.startswith(("https://","http://")):
        raise HTTPException(400,"input_url must be http(s)")
    guard=payload.guardrails or {}
    if guard.get("no_auto_publish") is not True or guard.get("preserve_approved_facts") is not True:
        raise HTTPException(400,"Required FactoryOS Media Finisher guardrails are missing")
    job_id=(payload.edit_job_id or str(uuid.uuid4())).strip()
    if not JOB_ID_RE.fullmatch(job_id):raise HTTPException(400,"Bad job id")
    if _state_path(job_id).exists():
        return _read_state(job_id)
    state={"id":job_id,"status":"queued","stage":"queued","percent":1,"request":payload.model_dump(),
           "callback_url":payload.callback_url,"created_at":time.time(),"updated_at":time.time(),
           "final_url":"","error":"","report":{}}
    _write_state(job_id,replace=state)
    background.add_task(_process,job_id)
    return _read_state(job_id)


@app.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    _auth(request)
    try:state=_read_state(job_id)
    except KeyError:raise HTTPException(404,"Media Finisher job not found")
    if state.get("final_url"):state={**state,"final_url":_public_file(job_id,"final.mp4")}   # a fresh signed link per read
    return state


@app.get("/files/{job_id}/{filename}")
def file(job_id: str, filename: str, request: Request, exp: int = 0, sig: str = ""):
    # A user's video is private: the API token, or a signed link for exactly this file that has not expired.
    if API_TOKEN:
        signed=bool(sig) and exp>time.time() and JOB_ID_RE.fullmatch(job_id or "") and hmac.compare_digest(sig.encode(),_file_signature(job_id,filename,exp).encode())
        if not (signed or _bearer_ok(request)):raise HTTPException(403,"A signed link or the API token is required")
    elif not ALLOW_PUBLIC_FILES:
        raise HTTPException(403,"File access is closed: set FINISHER_API_TOKEN")
    allowed=filename in {"final.mp4","captions.srt","remotion-props.json"} or bool(re.fullmatch(r"short-\d{2}\.mp4",filename)) or bool(re.fullmatch(r"qa-frame-\d{2}\.jpg",filename))
    if not allowed:raise HTTPException(404,"File not exposed")
    path=_job_dir(job_id)/filename
    if not path.exists():raise HTTPException(404,"File not found")
    media="video/mp4" if filename.endswith(".mp4") else ("image/jpeg" if filename.endswith(".jpg") else "text/plain")
    return FileResponse(path,media_type=media,filename=filename)
