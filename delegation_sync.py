"""Delegation Center sync projection from source-of-truth ROADMAP and existing GitHub cache."""
from datetime import datetime,timezone

DEFERRED_OWNER_TASKS={"T-520","T-521","T-551"}

def delegation_sync_view(board, github, synced_at=None):
    waiting=[]
    deferred=[]
    for task in (board or {}).get("planner_queue") or []:
        if task.get("state")!="human" or task.get("done"):
            continue
        record={"id":str(task.get("id") or ""),"title":str(task.get("title") or "")[:180],
                "state":"waiting_owner","roadmap_line":task.get("roadmap_line"),
                "dependencies_met":bool(task.get("dependencies_met"))}
        if record["id"] in DEFERRED_OWNER_TASKS:
            deferred.append(record)
        else:
            waiting.append(record)
    return {"synced_at":synced_at,"source":"GitHub owner issues + ROADMAP + Relay",
            "github_available":bool((github or {}).get("available")),
            "waiting_owner":waiting,"deferred_owner":deferred,"waiting_owner_count":len(waiting)+len(deferred),
            "note":"Owner tasks are not an AI worker queue. A stale sync never implies a running task."}
