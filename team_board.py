"""Team Build Progress projection: only verified events can imply active work."""
from datetime import datetime, timezone
import re

LANES=("claude","chatgpt","gemini")
COLUMNS={"planned":"queued","in_progress":"in_progress","blocked":"blocked","review":"review","done":"done"}
STAGES={"queued":0,"in_progress":50,"review":80,"blocked":0,"done":100,"waiting_owner":0}

def project_team(board, issues=None, lines=None, repo="Pavlovskyi-Andrii/blackboxlab-factoryos"):
    board=board or {}
    grouped={lane:[] for lane in LANES}
    issues=issues if isinstance(issues,dict) else {}
    lines=lines or {}
    present=set()
    for task in board.get("tasks") or []:
        lane=str(task.get("lane") or "").lower()
        if lane not in LANES:continue
        status="waiting_owner" if task.get("human") else COLUMNS.get(task.get("column"),"queued")
        tid=str(task.get("id") or "")
        if task.get("kind")=="roadmap":
            url=f"https://github.com/{repo}/blob/main/ROADMAP.md"
            if lines.get(tid):url+=f"#L{lines[tid]}"
        else:
            url=""
        grouped[lane].append({"id":tid,"title":str(task.get("title") or "")[:160],"status":status,
                              "progress":STAGES[status],"url":url,"origin":task.get("kind")})
        present.add(tid)
    if issues.get("available") is True:
        for issue in issues.get("issues") or []:
            if not isinstance(issue,dict) or issue.get("pull_request"):continue
            m=re.match(r"^Owner:\s*(Claude|ChatGPT|Gemini)\s*$",str(issue.get("body") or "").split("\n",1)[0],re.I)
            if not m:continue
            lane=m.group(1).lower();number=str(issue.get("number") or "")
            # Issue is already represented by its Relay ticket when matching source number.
            if "#"+number in present or not number:continue
            status="done" if issue.get("state")=="closed" else "queued"
            grouped[lane].append({"id":"#"+number,"title":str(issue.get("title") or "")[:160],
                                  "status":status,"progress":STAGES[status],"url":str(issue.get("url") or ""),
                                  "origin":"GitHub (assigned, not claimed)"})
    lanes={}
    for lane in LANES:
        facts=(board.get("lanes") or {}).get(lane) or {}
        state=str(facts.get("state") or "unknown")
        lanes[lane]={"state":state,"online":state in ("idle","working"),
                     "last_activity":str((facts.get("last_event") or {}).get("at") or "") or None,
                     "heartbeat_age_seconds":facts.get("heartbeat_age_seconds"),
                     "current_task":facts.get("task_id") if state=="working" else None,
                     "tasks":grouped[lane],
                     "counts":{s:sum(t["status"]==s for t in grouped[lane]) for s in STAGES}}
    return {"synced_at":datetime.now(timezone.utc).isoformat(),"source":"ROADMAP + Relay events + owner GitHub Issues",
            "github_available":issues.get("available") is True,"lanes":lanes,
            "counts":{s:sum(t["status"]==s for items in grouped.values() for t in items) for s in STAGES},
            "total":sum(map(len,grouped.values())),
            "progress_note":"Percent reflects stage, not measured implementation completion"}
