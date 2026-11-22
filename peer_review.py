"""Evidence Tier 2.6 (owner chose option A, 2026-11-11): Gemini reviews Claude's PRs in risky areas.

- Required only when the PR touches a risky area (auth, tokens, secrets, vault, OAuth, payments, budgets,
  publishing/approval, CI workflows) or is large (> BIG_CHANGE changed lines). The server adds the
  ``peer_review`` check to the ticket's required checks then; the agent cannot remove it.
- Runs only after CI is green on the PR head, once per head commit. A new push needs a new review.
- A review is an opinion, not proof: approval alone never closes a ticket (merge + CI are still required),
  and a blocking finding can always be overridden by the owner with a reason (/done R-0001 причина).
- Free Gemini tier only, stable Flash model, at most DAILY_CAP reviews per UTC day. Unavailable or over the
  cap → nothing is recorded as passed; it is retried later.
- What leaves the server: the changed files' patches (secrets redacted, size-capped), the ticket title and its
  "done when" text. Never tokens, env or other files.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

MODEL = "gemini-2.5-flash"
DAILY_CAP = 20
BIG_CHANGE = 300
MAX_PATCH_CHARS = 60_000
RETRY_AFTER = 30 * 60
RISKY = re.compile(r"(auth|token|secret|vault|oauth|password|credential|payment|billing|budget|publish|approval"
                   r"|\.github/workflows/|requirements\.txt$)", re.I)
SECRET_RE = re.compile(r"(?:sk-ant-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9_]{12,}|github_pat_[A-Za-z0-9_]{12,}"
                       r"|AIza[0-9A-Za-z_-]{20,}|\b\d{6,12}:[A-Za-z0-9_-]{30,}\b|Bearer\s+[A-Za-z0-9._~+/=-]{12,})")
SKIP_FILES = re.compile(r"(\.lock$|package-lock\.json$|\.png$|\.jpg$|\.mp3$|\.svg$)", re.I)


def needs_review(files: list) -> tuple[bool, str]:
    """Which PRs must be reviewed: a risky path or a big change. Returns (required, reason)."""
    files = [f for f in files or [] if isinstance(f, dict)]
    risky = sorted({str(f.get("filename") or "") for f in files if RISKY.search(str(f.get("filename") or ""))})
    if risky:
        return True, "risky: " + ", ".join(risky[:5])
    changed = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in files)
    if changed > BIG_CHANGE:
        return True, f"large: {changed} lines"
    return False, ""


def build_prompt(title: str, body: str, files: list) -> str:
    parts, used = [], 0
    for f in files or []:
        name = str(f.get("filename") or "")
        if not name or SKIP_FILES.search(name):
            continue
        patch = SECRET_RE.sub("[REDACTED]", str(f.get("patch") or ""))
        room = MAX_PATCH_CHARS - used
        if room <= 0:
            parts.append(f"--- {name}: (omitted, size cap)")
            continue
        chunk = patch[:room]
        used += len(chunk)
        parts.append(f"--- {name} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})\n{chunk}"
                     + ("\n[truncated]" if len(patch) > len(chunk) else ""))
    criteria = SECRET_RE.sub("[REDACTED]", str(body or ""))[:3000]
    return (
        "You are a strict senior code reviewer. Another AI agent wrote this pull request. Review ONLY the diff.\n"
        "Look for: security holes (auth bypass, secret exposure, missing owner/worker checks), data loss, "
        "behaviour that contradicts the task, broken error handling, tests that do not really test the change.\n"
        "Do not report style or naming. If unsure, do not report it.\n"
        'Answer with JSON only: {"verdict":"approve"|"changes","findings":[{"severity":"blocker"|"minor",'
        '"file":"path","text":"one sentence"}]} (at most 8 findings).\n\n'
        f"Task: {str(title or '')[:200]}\nDone when / task text:\n{criteria}\n\nDiff:\n" + "\n".join(parts))


def parse_verdict(text: str) -> Optional[dict]:
    """Model output → {"verdict", "blockers", "findings"}; anything malformed → None (= not reviewed)."""
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return None
    if not isinstance(data, dict) or data.get("verdict") not in ("approve", "changes"):
        return None
    findings = []
    for f in data.get("findings") or []:
        if not isinstance(f, dict) or not str(f.get("text") or "").strip():
            continue
        sev = "blocker" if f.get("severity") == "blocker" else "minor"
        findings.append({"severity": sev, "file": str(f.get("file") or "")[:160],
                         "text": " ".join(str(f["text"]).split())[:300]})
    findings = findings[:8]
    return {"verdict": data["verdict"], "blockers": sum(f["severity"] == "blocker" for f in findings),
            "findings": findings}


def gemini_review(api_key: str, prompt: str, call: Callable, resolve: Optional[Callable] = None) -> Optional[dict]:
    """One generateContent call on the stable Flash model. Errors → None (never a pass)."""
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"responseMimeType": "application/json", "maxOutputTokens": 4096, "temperature": 0.1}}
    try:
        model = resolve(api_key, MODEL) if resolve else MODEL
        data = call(api_key, "POST", f"models/{model}:generateContent", payload, None, 120)
    except Exception:
        return None
    parts = ((((data or {}).get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    return parse_verdict("".join(str(p.get("text") or "") for p in parts))


class ReviewBudget:
    """At most ``cap`` reviews per UTC day, persisted so a restart does not reset it."""

    def __init__(self, data_dir: Path, cap: int = DAILY_CAP, clock: Callable[[], float] = time.time):
        self.path, self.cap, self.clock = Path(data_dir) / "peer_review_budget.json", cap, clock
        self._lock = threading.Lock()

    def take(self) -> bool:
        day = time.strftime("%Y-%m-%d", time.gmtime(self.clock()))
        with self._lock:
            try:
                state = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = {}
            used = int(state.get(day) or 0)
            if used >= self.cap:
                return False
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({day: used + 1}), encoding="utf-8")
            os.replace(tmp, self.path)
            return True


def notice_text(ticket_id: str, url: str, verdict: dict) -> str:
    if verdict["blockers"]:
        lines = [f"⚠️ Ревью Gemini · {ticket_id}: блокирующих замечаний {verdict['blockers']} — тикет не закроется, "
                 f"пока их не исправят (или закрой вручную: /done {ticket_id} причина)."]
    elif verdict["findings"]:
        lines = [f"🔍 Ревью Gemini · {ticket_id}: блокирующих замечаний нет, мелких {len(verdict['findings'])}."]
    else:
        lines = [f"🔍 Ревью Gemini · {ticket_id}: замечаний нет."]
    for f in verdict["findings"][:5]:
        lines.append(("❗ " if f["severity"] == "blocker" else "• ") + (f["file"] + ": " if f["file"] else "") + f["text"])
    lines.append(url)
    lines.append("Это мнение второй модели, не доказательство: мерж и CI всё равно обязательны.")
    return "\n".join(lines)[:3800]
