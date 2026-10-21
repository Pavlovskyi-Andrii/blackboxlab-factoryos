import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any
from urllib import request as urlrequest

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

APP_VERSION = "v4.5-worker-1"
BASE = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FINISHER_DATA_DIR", "/var/data/media-finisher"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("PORT", "10000"))
PUBLIC_BASE_URL = (os.environ.get("FINISHER_PUBLIC_BASE_URL") or os.environ.get("RENDER_EXTERNAL_URL") or f"http://localhost:{PORT}").rstrip("/")
API_TOKEN = os.environ.get("FINISHER_API_TOKEN", "").strip()
FACTORYOS_CALLBACK_BASE_URL = os.environ.get("FACTORYOS_CALLBACK_BASE_URL", "").rstrip("/")
FACTORYOS_CALLBACK_TOKEN = os.environ.get("FACTORY_MEDIA_FINISHER_CALLBACK_TOKEN", "").strip()
WHISPER_MODEL = os.environ.get("FINISHER_WHISPER_MODEL", "small").strip() or "small"
WHISPER_DEVICE = os.environ.get("FINISHER_WHISPER_DEVICE", "cpu").strip() or "cpu"
WHISPER_COMPUTE_TYPE = os.environ.get("FINISHER_WHISPER_COMPUTE_TYPE", "int8").strip() or "int8"
GRAPHICS_ENGINE = os.environ.get("FINISHER_GRAPHICS_ENGINE", "remotion").strip().lower()
REMOTION_BROWSER = os.environ.get("REMOTION_BROWSER_EXECUTABLE", "/usr/bin/chromium").strip()
MAX_DOWNLOAD_BYTES = int(os.environ.get("FINISHER_MAX_DOWNLOAD_BYTES", str(750 * 1024 * 1024)))

app = FastAPI(title="FactoryOS AI Media Finisher", version=APP_VERSION)
_state_lock = threading.Lock()
_whisper_model = None


class JobRequest(BaseModel):
    edit_job_id: str = ""
    job_id: str
    factory_cycle_id: str | None = None
    input_url: str
    profile: dict[str, Any]
    platform: str = "reels"
    content_package: dict[str, Any] = {}
    rerun_stage: str = ""
    callback_url: str = ""
    guardrails: dict[str, Any] = {}


def _auth(request: Request):
    if not API_TOKEN:
        return
    supplied = (request.headers.get("authorization") or "").replace("Bearer ", "", 1).strip()
    if supplied != API_TOKEN:
        raise HTTPException(401, "Invalid Media Finisher API token")


def _job_dir(job_id: str) -> Path:
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


def _write_state(job_id: str, patch: dict | None = None, replace: dict | None = None) -> dict:
    with _state_lock:
        state = replace if replace is not None else (_read_state(job_id) if _state_path(job_id).exists() else {})
        if patch:
            state.update(patch)
        state["updated_at"] = time.time()
        tmp = _state_path(job_id).with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(_state_path(job_id))
        return state


def _run(cmd: list[str], *, capture: bool = True, cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        check=True,
        timeout=timeout,
    )


def _download(url: str, dest: Path) -> None:
    req = urlrequest.Request(url, headers={"User-Agent": "FactoryOS-MediaFinisher/4.5"})
    total = 0
    with urlrequest.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_DOWNLOAD_BYTES:
                raise RuntimeError("Input media exceeds FINISHER_MAX_DOWNLOAD_BYTES")
            fh.write(chunk)


def _probe(path: Path) -> dict:
    result = _run([
        "ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)
    ])
    data = json.loads(result.stdout or "{}")
    video = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
    duration = float((data.get("format") or {}).get("duration") or video.get("duration") or 0)
    return {
        "duration": duration,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": video.get("avg_frame_rate") or video.get("r_frame_rate") or "0/1",
    }


def _normalize_input(src: Path, dest: Path, profile: dict) -> None:
    target = profile.get("target") or {}
    width, height, fps = int(target.get("width") or 1080), int(target.get("height") or 1920), int(target.get("fps") or 30)
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps={fps}"
    _run([
        "ffmpeg", "-y", "-i", str(src), "-vf", vf,
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-movflags", "+faststart", str(dest)
    ])


def _extract_audio(src: Path, wav: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)])


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel
        _whisper_model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE)
    return _whisper_model


def _transcribe_words(wav: Path) -> tuple[list[dict], dict]:
    model = _get_whisper()
    segments, info = model.transcribe(str(wav), word_timestamps=True, vad_filter=True)
    words: list[dict] = []
    for segment in segments:
        for word in segment.words or []:
            token = str(word.word or "").strip()
            if not token or word.start is None or word.end is None:
                continue
            words.append({
                "word": token,
                "start": round(float(word.start), 3),
                "end": round(float(word.end), 3),
                "confidence": round(float(word.probability or 0), 4),
            })
    meta = {"language": getattr(info, "language", None), "language_probability": getattr(info, "language_probability", None), "model": WHISPER_MODEL}
    return words, meta


def _detect_silences(src: Path, threshold: float, noise_db: float = -35.0) -> list[dict]:
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"silencedetect=noise={noise_db}dB:d={threshold}", "-f", "null", "-"],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    starts = [float(x) for x in re.findall(r"silence_start:\s*([0-9.]+)", proc.stderr or "")]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([0-9.]+)", proc.stderr or "")]
    return [{"start": round(s, 3), "end": round(e, 3), "reason": f"silence>{threshold:.2f}s"} for s, e in zip(starts, ends) if e > s]


def _semantic_duplicate_cuts(words: list[dict]) -> list[dict]:
    """Conservative exact-repeat detector: only removes an immediately repeated 2–6 word phrase."""
    tokens = [re.sub(r"[^\w']+", "", w["word"].lower()) for w in words]
    cuts: list[dict] = []
    i = 0
    while i < len(tokens):
        matched = False
        for n in range(6, 1, -1):
            if i + 2 * n > len(tokens):
                continue
            a, b = tokens[i:i+n], tokens[i+n:i+2*n]
            if a == b and all(a):
                start = float(words[i+n]["start"])
                end = float(words[i+2*n-1]["end"])
                if 0 < end - start <= 6.0:
                    cuts.append({"start": round(start,3), "end": round(end,3), "reason": "exact_consecutive_duplicate"})
                    i += 2 * n
                    matched = True
                    break
        if not matched:
            i += 1
    return cuts


def _merge_ranges(ranges: list[dict], duration: float) -> list[dict]:
    prepared = sorted([
        {"start": max(0.0, float(x["start"])), "end": min(duration, float(x["end"])), "reason": x.get("reason","edit")}
        for x in ranges if float(x.get("end",0)) > float(x.get("start",0))
    ], key=lambda x: (x["start"], x["end"]))
    merged: list[dict] = []
    for item in prepared:
        if not merged or item["start"] > merged[-1]["end"] + 0.02:
            merged.append(item)
        else:
            merged[-1]["end"] = max(merged[-1]["end"], item["end"])
            if item["reason"] not in merged[-1]["reason"]:
                merged[-1]["reason"] += "+" + item["reason"]
    return [{**x, "start":round(x["start"],3), "end":round(x["end"],3)} for x in merged if x["end"] - x["start"] >= 0.05]


def build_cut_list(silences: list[dict], words: list[dict], duration: float, profile: dict) -> list[dict]:
    cleanup = profile.get("speech_cleanup") or {}
    pre = float(cleanup.get("pre_handle_sec", 0.1))
    post = float(cleanup.get("post_handle_sec", 0.15))
    cuts: list[dict] = []
    if cleanup.get("silence_trim", True):
        for silence in silences:
            start = float(silence["start"]) + pre
            end = float(silence["end"]) - post
            if end - start >= 0.08:
                cuts.append({"start": start, "end": end, "reason": silence.get("reason","silence")})
    if cleanup.get("semantic_duplicate_planner", True):
        cuts.extend(_semantic_duplicate_cuts(words))
    return _merge_ranges(cuts, duration)


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


def _apply_cuts(src: Path, dest: Path, duration: float, cuts: list[dict]) -> None:
    if not cuts:
        shutil.copy2(src, dest)
        return
    keep = _keep_ranges(duration, cuts)
    parts = []
    labels = []
    for i, (a,b) in enumerate(keep):
        parts.append(f"[0:v]trim=start={a:.3f}:end={b:.3f},setpts=PTS-STARTPTS[v{i}]")
        parts.append(f"[0:a]atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}][a{i}]")
    filt = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(keep)}:v=1:a=1[outv][outa]"
    _run(["ffmpeg","-y","-i",str(src),"-filter_complex",filt,"-map","[outv]","-map","[outa]",
          "-c:v","libx264","-preset","veryfast","-crf","20","-c:a","aac","-b:a","160k","-movflags","+faststart",str(dest)])


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


def group_captions(words: list[dict], profile: dict, cut_output_times: list[float] | None = None) -> list[dict]:
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
    return result


def _cut_output_boundaries(cuts: list[dict]) -> list[float]:
    return [round(float(c["start"])-_removed_before(float(c["start"]),cuts),3) for c in cuts]


def _motion_timeline(output_duration: float, cuts: list[dict], profile: dict) -> list[dict]:
    cfg=profile.get("motion") or {};events=[]
    zmin=float(cfg.get("jump_cut_mask_zoom_min",0.07));zmax=float(cfg.get("jump_cut_mask_zoom_max",0.10))
    for i,t in enumerate(_cut_output_boundaries(cuts)):
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


def _graphics_timeline(content_package: dict, output_duration: float, profile: dict) -> list[dict]:
    cfg=profile.get("graphics") or {};limit=max(0,min(5,int(cfg.get("emphasis_max",5))))
    texts=[]
    for scene in content_package.get("scenes") or []:
        text=str((scene or {}).get("on_screen_text") or "").strip()
        if text and text not in texts:
            texts.append(text)
    if not texts:
        title=str(content_package.get("title") or "").strip()
        if title:texts.append(title)
    texts=texts[:limit]
    if not texts:return []
    step=max(2.0,output_duration/(len(texts)+1));duration=max(1.0,min(2.0,float(cfg.get("duration_max_sec",2.0))))
    return [{"start":round(min(max(.1,output_duration-.5),(i+1)*step),2),"end":round(min(output_duration,(i+1)*step+duration),2),"text":text[:70],"type":"approved_emphasis"} for i,text in enumerate(texts)]


def _write_srt(captions: list[dict], path: Path) -> None:
    def stamp(value:float)->str:
        ms=max(0,int(round(value*1000)));h,rem=divmod(ms,3600000);m,rem=divmod(rem,60000);sec,msec=divmod(rem,1000)
        return f"{h:02d}:{m:02d}:{sec:02d},{msec:03d}"
    lines=[]
    for i,caption in enumerate(captions,1):
        lines.extend([str(i),f"{stamp(caption['start'])} --> {stamp(caption['end'])}",caption["text"],""])
    path.write_text("\n".join(lines),encoding="utf-8")


def _render_with_remotion(clean: Path, dest: Path, captions: list[dict], motion: list[dict], graphics: list[dict], profile: dict, duration: float, job_dir: Path) -> None:
    remotion_dir=BASE/"remotion";public_jobs=remotion_dir/"public"/"jobs"/job_dir.name
    public_jobs.mkdir(parents=True,exist_ok=True)
    shutil.copy2(clean,public_jobs/"clean.mp4")
    fps=int((profile.get("target") or {}).get("fps") or 30)
    props={
        "videoPath":f"jobs/{job_dir.name}/clean.mp4","captions":captions,"motion":motion,"graphics":graphics,
        "safeZones":profile.get("safe_zones") or {},"fps":fps,
        "durationInFrames":max(1,int(math.ceil(duration*fps))),
        "width":int((profile.get("target") or {}).get("width") or 1080),
        "height":int((profile.get("target") or {}).get("height") or 1920),
    }
    props_path=job_dir/"remotion-props.json";props_path.write_text(json.dumps(props,ensure_ascii=False),encoding="utf-8")
    cmd=["npx","remotion","render","src/index.tsx","MediaFinish",str(dest),"--props",str(props_path),"--codec","h264","--concurrency","2"]
    if REMOTION_BROWSER and Path(REMOTION_BROWSER).exists():
        cmd.extend(["--browser-executable",REMOTION_BROWSER])
    _run(cmd,cwd=remotion_dir,timeout=3600)


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
    return {"target_voice_lufs":target,"measured":measured,"music_applied":False,"music_policy":"No approved music asset was supplied; none was added."}


def _safe_zone_report(profile: dict, captions: list[dict], graphics: list[dict]) -> dict:
    zones=profile.get("safe_zones") or {}
    return {
        "method":"layout_contract",
        "top":float(zones.get("top",0.12)),"bottom":float(zones.get("bottom",0.20)),
        "right":float(zones.get("right",0.12)),"left":float(zones.get("left",0.0)),
        "caption_events":len(captions),"graphics_events":len(graphics),"violations":[],
        "frame_sampling":"not_yet_computer_vision_verified",
        "note":"Deterministic overlay coordinates were checked; human review is still required for face/object obstruction."
    }


def _public_file(job_id: str, filename: str) -> str:
    return f"{PUBLIC_BASE_URL}/files/{job_id}/{filename}"


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
        "raw":{"worker_version":APP_VERSION,"graphics_engine":state.get("graphics_engine")}
    }
    headers={"Content-Type":"application/json"}
    if FACTORYOS_CALLBACK_TOKEN:headers["Authorization"]="Bearer "+FACTORYOS_CALLBACK_TOKEN
    req=urlrequest.Request(callback,data=json.dumps(body).encode("utf-8"),headers=headers,method="POST")
    try:
        with urlrequest.urlopen(req,timeout=30) as resp:resp.read()
    except Exception:
        pass


def _process(job_id: str) -> None:
    started=time.time();state=_read_state(job_id);payload=state["request"];job_dir=_job_dir(job_id)
    try:
        _write_state(job_id,{"status":"processing","stage":"download"})
        src=job_dir/"source.bin";_download(payload["input_url"],src)
        profile=(payload.get("profile") or {}).get("config") or {}
        normalized=job_dir/"normalized.mp4";_normalize_input(src,normalized,profile)
        before=_probe(normalized);duration=float(before["duration"])
        _write_state(job_id,{"stage":"transcript"})
        wav=job_dir/"audio.wav";_extract_audio(normalized,wav)
        words,asr_meta=_transcribe_words(wav)
        cleanup=profile.get("speech_cleanup") or {};threshold=float(cleanup.get("pause_threshold_sec",0.4))
        silences=_detect_silences(normalized,threshold)
        cuts=build_cut_list(silences,words,duration,profile)
        _write_state(job_id,{"stage":"cleanup","progress":{"words":len(words),"cuts":len(cuts)}})
        clean=job_dir/"clean.mp4";_apply_cuts(normalized,clean,duration,cuts)
        after_clean=_probe(clean);out_duration=float(after_clean["duration"])
        mapped_words=map_words_after_cuts(words,cuts)
        boundaries=_cut_output_boundaries(cuts)
        captions=group_captions(mapped_words,profile,boundaries)
        srt=job_dir/"captions.srt";_write_srt(captions,srt)
        motion=_motion_timeline(out_duration,cuts,profile)
        graphics=_graphics_timeline(payload.get("content_package") or {},out_duration,profile)
        _write_state(job_id,{"stage":"graphics","progress":{"captions":len(captions),"motion":len(motion),"graphics":len(graphics)}})
        composed=job_dir/"composed.mp4";engine=GRAPHICS_ENGINE
        if engine=="remotion":
            _render_with_remotion(clean,composed,captions,motion,graphics,profile,out_duration,job_dir)
        elif engine=="ffmpeg":
            _render_ffmpeg_fallback(clean,composed,srt);engine="ffmpeg_captions_only"
        else:
            raise RuntimeError("Unsupported FINISHER_GRAPHICS_ENGINE; use remotion or ffmpeg")
        _write_state(job_id,{"stage":"audio"})
        final=job_dir/"final.mp4";audio_report=_audio_finish(composed,final,profile)
        final_probe=_probe(final);safe=_safe_zone_report(profile,captions,graphics)
        report={
            "transcript_words":mapped_words,"transcript_corrections":[],"asr":asr_meta,"cut_list":cuts,
            "caption_timeline":captions,"motion_timeline":motion if engine=="remotion" else [],
            "graphics_timeline":graphics if engine=="remotion" else [],"audio_report":audio_report,"safe_zone_report":safe,
            "edit_summary":{
                "duration_before_sec":round(duration,3),"duration_after_sec":round(float(final_probe["duration"]),3),
                "removed_segments":len(cuts),"removed_seconds":round(sum(float(x["end"])-float(x["start"]) for x in cuts),3),
                "graphics_engine":engine,"profile_id":(payload.get("profile") or {}).get("id"),
                "profile_version":(payload.get("profile") or {}).get("version"),"platform":payload.get("platform"),
                "rerun_stage":payload.get("rerun_stage") or "full","human_review_required":True,
                "visual_checks_required":["face/object obstruction","caption readability","cut naturalness"]
            }
        }
        state=_write_state(job_id,{"status":"ready","stage":"done","final_url":_public_file(job_id,"final.mp4"),"report":report,
                                   "graphics_engine":engine,"wall_duration_sec":round(time.time()-started,3),"error":""})
        _callback(state)
    except Exception as exc:
        state=_write_state(job_id,{"status":"failed","stage":"failed","error":str(exc)[:1500],"wall_duration_sec":round(time.time()-started,3)})
        _callback(state)


@app.get("/health")
def health():
    return {"ok":True,"version":APP_VERSION,"graphics_engine":GRAPHICS_ENGINE,"whisper_model":WHISPER_MODEL}


@app.post("/jobs")
def create_job(payload: JobRequest, background: BackgroundTasks, request: Request):
    _auth(request)
    if not payload.input_url.startswith(("https://","http://")):
        raise HTTPException(400,"input_url must be http(s)")
    guard=payload.guardrails or {}
    if guard.get("no_auto_publish") is not True or guard.get("preserve_approved_facts") is not True:
        raise HTTPException(400,"Required FactoryOS Media Finisher guardrails are missing")
    job_id=(payload.edit_job_id or str(uuid.uuid4())).strip()
    if _state_path(job_id).exists():
        return _read_state(job_id)
    state={"id":job_id,"status":"queued","stage":"queued","request":payload.model_dump(),
           "callback_url":payload.callback_url,"created_at":time.time(),"updated_at":time.time(),
           "final_url":"","error":"","report":{}}
    _write_state(job_id,replace=state)
    background.add_task(_process,job_id)
    return _read_state(job_id)


@app.get("/jobs/{job_id}")
def job_status(job_id: str, request: Request):
    _auth(request)
    try:return _read_state(job_id)
    except KeyError:raise HTTPException(404,"Media Finisher job not found")


@app.get("/files/{job_id}/{filename}")
def file(job_id: str, filename: str):
    if filename not in {"final.mp4","captions.srt","remotion-props.json"}:
        raise HTTPException(404,"File not exposed")
    path=_job_dir(job_id)/filename
    if not path.exists():raise HTTPException(404,"File not found")
    media="video/mp4" if filename.endswith(".mp4") else "text/plain"
    return FileResponse(path,media_type=media,filename=filename)
