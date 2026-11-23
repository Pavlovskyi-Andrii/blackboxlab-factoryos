"""T-729 Coordination guard: one read model that answers "is anybody about to do the same work twice?".

Inputs are facts that already exist; nothing here starts work, claims a task or calls a provider:
- ``ROADMAP.md`` text (task IDs, ``Owner:``, ``Depends:``, done / open);
- open GitHub pull requests with their changed files (``files`` is ``None`` when GitHub did not answer);
- active Relay claims of ROADMAP tasks (lane, run state);
- FactoryOS handoffs between lanes (``to``, ``state``, ``files_scope``).

Findings, worst first:
- ``conflict``: the same ROADMAP task ID is defined twice; two open PRs change the same code file; one task is
  worked on by two lanes (PR + claim, two PRs, claim + handoff to another lane); a PR changes files inside the
  ``files_scope`` of a handoff that belongs to another lane.
- ``warning``: a PR names a task that is already ``[x]`` on main; ``Depends:`` points at an unknown task;
  an open task is claimed by a lane that is not its ``Owner:``.
- ``unknown``: a source could not be read (GitHub down, no read token, a PR's file list unreadable).

The verdict is never "clear" while a source is unknown: unknown is not success (owner rule, Evidence Protocol).
Shared ledger files that every PR edits by design (ROADMAP.md, DECISIONS.md, README, CI workflow, the
versioned smoke test) do not count as code overlap; they are listed separately so a reviewer still sees them.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from fnmatch import fnmatchcase
from typing import Iterable, Optional

TASK_LINE_RE = re.compile(r"^- \[([ xX])\]\s+(\[HUMAN\]\s+)?(T-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*)\s*(.*)$")
TASK_ID_RE = re.compile(r"\bT-(?:[0-9]{3,4}|[A-Z]{3,12})(?:-[A-Z0-9]{1,4})?\b")
META_RE = re.compile(r"^(Owner|Depends):\s*(.*)$")
SHARED_LEDGER = ("ROADMAP.md", "DECISIONS.md", "README.md", "CLAUDE.md", "AGENTS.md", ".autopilot/status.json",
                 ".autopilot/answers.md", ".github/workflows/ci.yml", "smoke_tests.py")
ACTIVE_CLAIM_STATES = ("claimed", "running", "checkpoint", "committed", "pushed", "pr", "ci")
ACTIVE_HANDOFF_STATES = ("queued", "claimed", "review")
SEVERITY_RANK = {"conflict": 0, "unknown": 1, "warning": 2}
MAX_FINDINGS = 60


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_roadmap(text: str) -> list[dict]:
    """Every task line with its line number, done flag, owner lane and dependency IDs (duplicates are kept)."""
    tasks: list[dict] = []
    for line_no, raw in enumerate(str(text or "").splitlines(), 1):
        line = raw.strip()
        match = TASK_LINE_RE.match(line)
        if match:
            tasks.append({"id": match.group(3), "done": match.group(1).lower() == "x", "human": bool(match.group(2)),
                          "title": match.group(4).strip()[:160], "line": line_no, "owner": "", "depends": []})
            continue
        if not tasks or not raw[:1].isspace():
            continue
        meta = META_RE.match(line)
        if not meta:
            continue
        if meta.group(1) == "Owner":
            tasks[-1]["owner"] = (meta.group(2).split() or [""])[0].lower()
        else:
            tasks[-1]["depends"] = sorted(set(TASK_ID_RE.findall(meta.group(2))))
    return tasks


def task_ids_in(*texts: str) -> list[str]:
    """ROADMAP task IDs named in a PR title / branch / body (``t-729`` in a branch name counts too)."""
    found: set = set()
    for text in texts:
        found.update(TASK_ID_RE.findall(str(text or "").replace("t-", "T-")))
    return sorted(found)


def _is_ledger(path: str) -> bool:
    return path in SHARED_LEDGER


def _in_scope(path: str, scope: Iterable[str]) -> bool:
    for s in scope or ():
        s = str(s or "").strip()
        if not s:
            continue
        base = s[:-3] if s.endswith("/**") else s
        if path == s or fnmatchcase(path, s) or path.startswith(base.rstrip("/") + "/"):
            return True
    return False


def _lane_of_pr(pr: dict) -> str:
    """The agent lane a PR belongs to, from its branch prefix (claude/…, chatgpt/…, gemini/…, ccr-… = claude)."""
    ref = str(pr.get("branch") or "").lower()
    for lane in ("claude", "chatgpt", "gemini", "codex"):
        if ref.startswith(lane + "/") or ref.startswith(lane + "-"):
            return lane
    if ref.startswith("ccr-"):
        return "claude"
    return "unknown"


def build_report(roadmap_text: Optional[str], prs: Optional[list], claims: Optional[list],
                 handoffs: Optional[list], *, now: str = "") -> dict:
    """The coordination report. ``None`` for a source means "could not be read", ``[]`` means "read, empty"."""
    findings: list[dict] = []
    sources = {"roadmap": roadmap_text is not None, "github": prs is not None,
               "relay": claims is not None, "handoffs": handoffs is not None}

    def add(severity: str, code: str, **fields) -> None:
        findings.append({"severity": severity, "code": code, **fields})

    tasks = parse_roadmap(roadmap_text or "")
    by_id: dict[str, list[dict]] = {}
    for t in tasks:
        by_id.setdefault(t["id"], []).append(t)
    for tid, rows in sorted(by_id.items()):
        if len(rows) > 1:
            add("conflict", "duplicate_task_id", task_ids=[tid], lines=[r["line"] for r in rows],
                titles=[r["title"] for r in rows])
    known = set(by_id)
    for t in tasks:
        missing = [d for d in t["depends"] if d not in known and d.split("-")[0] + "-" + d.split("-")[1] not in known]
        if missing and not t["done"]:
            add("warning", "unknown_dependency", task_ids=[t["id"]], depends=missing, lines=[t["line"]])
    status_of = {tid: rows[0] for tid, rows in by_id.items()}

    # work items: every open PR, active claim and active handoff, with the task IDs it touches
    work: list[dict] = []
    for pr in prs or []:
        if not isinstance(pr, dict):
            continue
        files = pr.get("files")
        item = {"kind": "pr", "ref": "#" + str(pr.get("number")), "number": pr.get("number"),
                "lane": _lane_of_pr(pr), "branch": str(pr.get("branch") or "")[:120],
                "title": str(pr.get("title") or "")[:200], "url": str(pr.get("url") or ""), "draft": bool(pr.get("draft")),
                "task_ids": task_ids_in(pr.get("title"), pr.get("branch")),
                "files": None if files is None else sorted({str(f) for f in files if isinstance(f, str)})}
        work.append(item)
        if item["files"] is None:
            add("unknown", "pr_files_unreadable", prs=[item["ref"]], detail="GitHub did not return the changed files")
    for c in claims or []:
        if not isinstance(c, dict) or str(c.get("state") or "") not in ACTIVE_CLAIM_STATES:
            continue
        work.append({"kind": "claim", "ref": str(c.get("ticket") or c.get("task_id") or ""), "lane": str(c.get("lane") or "unknown"),
                     "state": str(c.get("state") or ""), "task_ids": [str(c.get("task_id") or "")], "files": None,
                     "title": str(c.get("title") or "")[:200]})
    for h in handoffs or []:
        if not isinstance(h, dict) or str(h.get("state") or "") not in ACTIVE_HANDOFF_STATES:
            continue
        work.append({"kind": "handoff", "ref": str(h.get("handoff_id") or ""), "lane": str(h.get("to") or "unknown"),
                     "state": str(h.get("state") or ""), "task_ids": [str(h.get("task_id") or "")],
                     "scope": [str(s) for s in (h.get("files_scope") or []) if s], "files": None,
                     "title": str(h.get("objective") or "")[:200]})

    # one task in two places
    by_task: dict[str, list[dict]] = {}
    for w in work:
        for tid in w["task_ids"]:
            if tid:
                by_task.setdefault(tid, []).append(w)
    for tid, items in sorted(by_task.items()):
        lanes = sorted({w["lane"] for w in items})
        prs_for = [w for w in items if w["kind"] == "pr"]
        if len(items) > 1 and (len(lanes) > 1 or len(prs_for) > 1):
            add("conflict", "task_in_two_places", task_ids=[tid], refs=[w["kind"] + " " + w["ref"] for w in items], lanes=lanes)
        row = status_of.get(tid)
        if row and row["done"]:
            for w in prs_for:
                add("warning", "pr_names_done_task", task_ids=[tid], prs=[w["ref"]], lines=[row["line"]],
                    titles=[row["title"]])
        for w in items:
            if w["kind"] == "claim" and row and row["owner"] and row["owner"] not in ("any", "auto", w["lane"]) \
                    and not row["owner"].startswith(w["lane"]):
                add("warning", "claimed_by_other_lane", task_ids=[tid], refs=["claim " + w["ref"]],
                    lanes=[w["lane"]], owner=row["owner"])

    # two open PRs changing the same code file; a PR inside another lane's handoff scope
    pr_items = [w for w in work if w["kind"] == "pr" and w["files"] is not None]
    ledger_touch: dict[str, list[str]] = {}
    for i, a in enumerate(pr_items):
        for f in a["files"]:
            if _is_ledger(f):
                ledger_touch.setdefault(f, []).append(a["ref"])
        for b in pr_items[i + 1:]:
            shared = sorted(f for f in set(a["files"]) & set(b["files"]) if not _is_ledger(f))
            if shared:
                add("conflict", "pr_file_overlap", prs=[a["ref"], b["ref"]], files=shared[:20], count=len(shared))
    for h in (w for w in work if w["kind"] == "handoff" and w.get("scope")):
        for p in pr_items:
            if p["lane"] == h["lane"] or set(p["task_ids"]) & set(h["task_ids"]):
                continue
            hits = [f for f in p["files"] if not _is_ledger(f) and _in_scope(f, h["scope"])]
            if hits:
                add("conflict", "pr_in_handoff_scope", prs=[p["ref"]], refs=["handoff " + h["ref"]], lanes=[p["lane"], h["lane"]],
                    files=hits[:20], count=len(hits))

    for name, ok in sources.items():
        if not ok:
            add("unknown", "source_unreadable", source=name)

    findings.sort(key=lambda f: (SEVERITY_RANK.get(f["severity"], 9), f["code"], str(f.get("task_ids") or f.get("prs") or "")))
    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in SEVERITY_RANK}
    verdict = "conflict" if counts["conflict"] else "unknown" if counts["unknown"] else "attention" if counts["warning"] else "clear"
    open_tasks = [t for t in tasks if not t["done"]]
    return {
        "verdict": verdict,
        "generated_at": now or _now(),
        "counts": counts,
        "findings": findings[:MAX_FINDINGS],
        "truncated": len(findings) > MAX_FINDINGS,
        "sources": sources,
        "roadmap": {"tasks": len(tasks), "unique_ids": len(by_id), "open": len(open_tasks),
                    "open_human": sum(1 for t in open_tasks if t["human"]),
                    "max_id": max((int(m.group(1)) for t in tasks for m in [re.match(r"T-(\d+)", t["id"])] if m), default=0)},
        "work": [{k: v for k, v in w.items() if k != "files"} | {"files_count": None if w["files"] is None else len(w["files"])}
                 for w in work],
        "shared_ledger": {f: refs for f, refs in sorted(ledger_touch.items()) if len(refs) > 1},
        # private inputs for agent_check (removed from the public JSON by public_view)
        "_pr_files": {w["ref"]: w["files"] for w in work if w["kind"] == "pr"},
        "_roadmap_text": roadmap_text or "",
    }


def public_view(report: dict) -> dict:
    """The report without the private agent_check inputs (owner page / API)."""
    return {k: v for k, v in report.items() if not k.startswith("_")}


def next_free_id(report: dict, reserved: Iterable[str] = ()) -> str:
    """The next unused T-number after the highest one on ROADMAP and every ID named in open work."""
    top = int((report.get("roadmap") or {}).get("max_id") or 0)
    for w in report.get("work") or []:
        for tid in w.get("task_ids") or []:
            m = re.match(r"T-(\d+)", tid or "")
            if m:
                top = max(top, int(m.group(1)))
    for tid in reserved:
        m = re.match(r"T-(\d+)", tid or "")
        if m:
            top = max(top, int(m.group(1)))
    return "T-" + str(top + 1)


MCP_TOOL = {
    "name": "coordination_check",
    "description": ("T-729: before you take a task or open a branch, ask whether anybody already works on it. Give the ROADMAP "
                    "task_id and/or the files you plan to change. Answers safe_to_start with reasons (same task in an open "
                    "PR, Relay claim or handoff; files changed by an open PR), plus next_free_id for a new ROADMAP task. "
                    "Read-only; unknown sources make the answer 'unknown', never 'safe'."),
    "inputSchema": {"type": "object", "properties": {
        "task_id": {"type": "string", "maxLength": 20},
        "files": {"type": "array", "items": {"type": "string", "maxLength": 300}, "maxItems": 200},
        "lane": {"type": "string", "enum": ["claude", "chatgpt", "gemini"]}},
        "additionalProperties": False},
}
MCP_TOOL_NAMES = ("coordination_check",)


def agent_check(report: dict, task_id: str = "", files: Iterable[str] = (), lane: str = "") -> dict:
    """Pre-start answer for one agent: may it start ``task_id`` / change ``files`` without duplicating work?"""
    task_id = str(task_id or "").strip().upper()
    if task_id and not TASK_ID_RE.fullmatch(task_id):
        raise ValueError("task_id must look like T-123")
    wanted = sorted({str(f).strip().lstrip("./") for f in files or () if str(f).strip()})[:200]
    lane = str(lane or "").strip().lower()
    reasons: list[dict] = []
    for w in report.get("work") or []:
        if task_id and task_id in (w.get("task_ids") or []) and not (lane and w.get("lane") == lane and w.get("kind") != "pr"):
            reasons.append({"code": "task_already_active", "ref": w.get("kind", "") + " " + str(w.get("ref") or ""),
                            "lane": w.get("lane"), "state": w.get("state") or ("draft" if w.get("draft") else "open")})
    for f in report.get("findings") or []:
        if task_id and f.get("code") == "duplicate_task_id" and task_id in (f.get("task_ids") or []):
            reasons.append({"code": "task_id_defined_twice", "lines": f.get("lines")})
    pr_files = report.get("_pr_files") or {}
    unknown_prs = []
    for ref, pfiles in pr_files.items():
        if pfiles is None:
            unknown_prs.append(ref)
            continue
        hits = [x for x in wanted if not _is_ledger(x) and (x in pfiles or any(p.startswith(x.rstrip("/") + "/") for p in pfiles))]
        if hits:
            reasons.append({"code": "files_in_open_pr", "ref": "pr " + ref, "files": hits[:20]})
    for w in report.get("work") or []:
        if w.get("kind") == "handoff" and w.get("scope") and not (lane and w.get("lane") == lane):
            hits = [x for x in wanted if not _is_ledger(x) and _in_scope(x, w["scope"])]
            if hits:
                reasons.append({"code": "files_in_handoff_scope", "ref": "handoff " + str(w.get("ref")), "lane": w.get("lane"),
                                "files": hits[:20]})
    sources_ok = all((report.get("sources") or {}).values())
    if reasons:
        answer = "no"
    elif not sources_ok or (wanted and unknown_prs):
        answer = "unknown"
    else:
        answer = "yes"
    row = None
    if task_id:
        for f in parse_roadmap(report.get("_roadmap_text") or ""):
            if f["id"] == task_id:
                row = {"done": f["done"], "owner": f["owner"], "human": f["human"], "depends": f["depends"]}
                break
    return {"safe_to_start": answer, "task_id": task_id or None, "roadmap": row, "reasons": reasons,
            "unknown_sources": [k for k, v in (report.get("sources") or {}).items() if not v] + [("pr " + r) for r in unknown_prs],
            "next_free_id": next_free_id(report), "verdict": report.get("verdict"), "generated_at": report.get("generated_at"),
            "note": "safe_to_start is advisory and read-only: claim the task through Relay before coding."}
