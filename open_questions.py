"""Read-only, owner-only projection of structured unresolved FactoryOS items (#321).

Uses existing stores only. Free-form notes and external Notion records are NOT parsed as
open questions: their status cannot be reliably inferred. Does not write or start workers.
"""
from __future__ import annotations

from typing import Any, Callable

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from mvp_factory import TERMINAL, MvpError
from owner_desk import MAX_KEPT_QUESTIONS


OPEN_QUESTION_STATUSES = {"pending", "answering", "failed"}


def collect_open_questions(registry: Any, questions: Any) -> dict[str, Any]:
    """Project all unresolved items with an explicit, existing state; never invent one."""
    items: list[dict[str, Any]] = []
    for project in registry.snapshot()["projects"]:
        pid = str(project.get("id") or "")
        title = str(project.get("title") or pid)
        stage = str(project.get("stage") or "")
        if stage in TERMINAL:
            continue  # validated/rejected: nothing left to decide, even if a block was never lifted
        blocked = project.get("blocked")
        if blocked:
            items.append({
                "id": f"mvp-block:{pid}", "source": "mvp_registry",
                "project_id": pid, "project_title": title,
                "status": "blocked", "kind": "mvp_blocker",
                "title": str(blocked.get("reason") or "MVP blocked"),
                "updated_at": str(blocked.get("at") or project.get("updated_at") or ""),
                "context": stage,
            })
        elif stage in ("spec_review", "preview_ready", "owner_review"):
            # A review gate is unresolved until the project stage changes.
            items.append({
                "id": f"mvp-review:{pid}", "source": "mvp_registry",
                "project_id": pid, "project_title": title,
                "status": "needs_review", "kind": "mvp_review",
                "title": "spec_review" if stage == "spec_review" else "preview_review",
                "updated_at": str(project.get("updated_at") or ""),
                "context": stage,
            })

    # The store's bounded retained history is the complete locally available source,
    # not just its default last 50. Closed/answered and internal probes are excluded.
    for q in questions.list(limit=MAX_KEPT_QUESTIONS):
        status = str(q.get("status") or "")
        if status not in OPEN_QUESTION_STATUSES:
            continue
        items.append({
            "id": str(q.get("id") or ""), "source": "owner_desk",
            "project_id": "owner-desk", "project_title": "Owner Desk",
            "status": status, "kind": "owner_question",
            "title": str(q.get("question") or ""),
            "updated_at": str(q.get("created_at") or ""),
            "context": str(q.get("task_id") or ""),
        })

    items.sort(key=lambda item: (item["updated_at"], item["id"]), reverse=True)
    return {
        "items": items, "total": len(items),
        "sources": {"mvp_registry": True, "owner_desk": True, "notion": False},
        "coverage": "Structured local MVP blockers/review gates and retained Owner Desk questions only. "
                    "Notion, free-form notes, Telegram conversations and other unstructured waits are not synced.",
        "read_only": True,
    }


def install_open_questions_routes(app: Any, registry: Any, questions: Any,
                                  identity_fn: Callable[[Request], Any]) -> None:
    @app.get("/api/factory/open-questions")
    def open_questions(request: Request):
        if (identity_fn(request) or {}).get("role") != "owner":
            raise HTTPException(status_code=403, detail="Owner access required")
        try:
            return collect_open_questions(registry, questions)
        except MvpError as exc:
            return JSONResponse({"detail": exc.code}, status_code=exc.status)
