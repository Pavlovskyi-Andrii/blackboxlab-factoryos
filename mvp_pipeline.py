"""MVP Builder step 2 (owner 2026-11-11: "чтобы один передавал второму информацию, автономно").

Agents hand their work to the next one through recorded artifacts and registry events with evidence:

  idea ──(autopilot on)──▶ researching ──Researcher (Gemini): research + 3 variants──▶ spec_draft
       ──Spec Writer (Gemini): spec with "готово, коли"──▶ spec_review ──OWNER approves──▶ build_queued
       ──Builder: one Relay ticket (Claude worker, isolated branch → PR → CI)──▶ building
       ──ticket closed on evidence (merged PR + CI)──▶ qa_review   (QA / preview / verdict: next step, owner gates)

Rules
- Autopilot is per project and off until the owner starts it (one Gemini call per stage on the free key; nothing paid).
- Every hand-off is an `advance` event whose evidence is the artifact link (research, spec) or the merged PR; the
  registry refuses agent moves into build, preview, verdict or rejection (`AGENT_FORBIDDEN_TARGETS`).
- Battle: the Researcher proposes three variants with a recommendation; the Spec Writer uses the recommended one; the
  owner can redo the spec on another variant before approving it.
- A failed agent run is not retried in a loop: it waits RETRY_AFTER and records the reason in the agent chat.
- The MVP code goes to `mvps/<project-id>/` in this repository through the normal Relay flow (owner merges).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

RETRY_AFTER = 30 * 60
NAME_RE = re.compile(r"^[a-z0-9_.-]{1,60}$")
REPO_ROOT_DIR = "mvps"


class ArtifactStore:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "mvp_artifacts"
        self._lock = threading.Lock()

    def save(self, project_id: str, name: str, text: str) -> str:
        if not NAME_RE.match(name):
            raise ValueError("bad_name")
        d = self.root / project_id
        with self._lock:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / (name + ".tmp")
            tmp.write_text(str(text)[:60000], encoding="utf-8")
            os.replace(tmp, d / name)
        return f"/api/mvp-factory/{project_id}/artifacts/{name}"

    def read(self, project_id: str, name: str) -> Optional[str]:
        if not NAME_RE.match(name or "") or not re.match(r"^[a-z0-9-]{2,41}$", project_id or ""):
            return None
        p = self.root / project_id / name
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            return None

    def names(self, project_id: str) -> list:
        d = self.root / project_id
        return sorted(p.name for p in d.iterdir() if p.is_file() and not p.name.endswith(".tmp")) if d.exists() else []


def _json(text: str) -> Optional[dict]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`").split("\n", 1)[-1]
    m = re.search(r"\{.*\}", raw, re.S)
    for candidate in (raw, m.group(0) if m else ""):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


def research_prompt(project: dict) -> str:
    return (
        "You are the Researcher agent of MVP Builder (FactoryOS). Work only from the owner's brief below and general "
        "knowledge; do not invent numbers, customers, quotes or sources. Mark assumptions as assumptions.\n"
        f"Project: {project.get('title')}\nOwner's brief:\n{str(project.get('brief') or '—')[:4000]}\n\n"
        "Answer in the language of the brief, as JSON only:\n"
        '{"summary": "...", "audience": "...", "problem": "...", "competitors": ["name — what they do"],'
        ' "variants": [{"id": "A", "name": "...", "pitch": "...", "features": ["..."], "differentiator": "...",'
        ' "risks": ["..."]}, {"id": "B", ...}, {"id": "C", ...}], "recommended": "A", "why": "...",'
        ' "assumptions": ["..."]}\n'
        "Exactly three variants (Battle: they must really differ). Features: 3-6 each, small enough for an MVP.")


def spec_prompt(project: dict, research: dict, variant_id: str, feedback: str = "") -> str:
    variant = next((v for v in research.get("variants") or [] if v.get("id") == variant_id), None) or {}
    return (
        "You are the Spec Writer agent of MVP Builder (FactoryOS). Write a technical spec for a small MVP that the "
        "Builder (Claude Code) will implement in one pull request in the folder "
        f"`{REPO_ROOT_DIR}/{project.get('id')}/` of an existing Python/FastAPI repository.\n"
        f"Project: {project.get('title')}\nOwner's brief:\n{str(project.get('brief') or '—')[:3000]}\n"
        f"Chosen variant ({variant_id}): {json.dumps(variant, ensure_ascii=False)[:2500]}\n"
        f"Audience: {research.get('audience', '')}\nProblem: {research.get('problem', '')}\n"
        + (f"Owner's feedback on the previous spec: {feedback[:1500]}\n" if feedback else "") +
        "Hard rules for the MVP: zero spend (no paid APIs or services), no publishing or sending messages to real "
        "people, no secrets in code, runs locally with tests.\n"
        "Write the spec in the language of the brief, in Markdown, with these sections exactly: "
        "## Мета, ## Для кого, ## Історії користувача, ## Обов'язкові функції, ## Поза межами MVP, "
        "## Технічні рамки, ## Готово, коли (a checklist of 5-10 verifiable items, each checkable by a test or a "
        "screenshot), ## Ризики. Do not invent results or data.")


def research_markdown(project: dict, r: dict) -> str:
    lines = [f"# Дослідження · {project.get('title')}", "", r.get("summary", ""), "",
             f"**Аудиторія:** {r.get('audience', '')}", f"**Проблема:** {r.get('problem', '')}", "", "## Конкуренти"]
    lines += [f"- {c}" for c in r.get("competitors") or []] + ["", "## Варіанти (Battle)"]
    for v in r.get("variants") or []:
        mark = " ⭐ рекомендовано" if v.get("id") == r.get("recommended") else ""
        lines += [f"### {v.get('id')} · {v.get('name')}{mark}", v.get("pitch", ""), "Функції:"]
        lines += [f"- {f}" for f in v.get("features") or []]
        lines += [f"Відмінність: {v.get('differentiator', '')}", "Ризики: " + "; ".join(v.get("risks") or []), ""]
    lines += [f"**Чому {r.get('recommended')}:** {r.get('why', '')}", "", "## Припущення"]
    lines += [f"- {a}" for a in r.get("assumptions") or []]
    lines += ["", "_Згенеровано агентом Researcher (Gemini). Припущення не перевірені._"]
    return "\n".join(str(x) for x in lines)


def build_ticket_body(project: dict, spec_md: str) -> str:
    return (f"MVP Builder · Builder agent · проєкт `{project.get('id')}`.\n\n"
            f"Реалізуй MVP за ТЗ нижче в папці `{REPO_ROOT_DIR}/{project.get('id')}/` (лише там, плюс тести поруч). "
            "Нуль витрат, без публікацій і без розсилок, без секретів у коді. Готово, коли виконано всі пункти "
            "розділу «Готово, коли» і тести проходять.\n\n" + spec_md[:9000])


class Pipeline:
    """One tick moves every autopilot project at most one step. Blocking (Gemini calls): run it off the event loop."""

    def __init__(self, data_dir: Path, *, registry, chat, artifacts: ArtifactStore, gemini: Callable[[str], tuple],
                 create_ticket: Callable[[str, str, str, str], dict], get_ticket: Callable[[str], Optional[dict]],
                 ticket_done: Callable[[dict], bool], clock: Callable[[], float] = time.time):
        self.path = Path(data_dir) / "mvp_pipeline.json"
        self.registry, self.chat, self.artifacts, self.gemini = registry, chat, artifacts, gemini
        self.create_ticket, self.get_ticket, self.ticket_done, self.clock = create_ticket, get_ticket, ticket_done, clock
        self._lock = threading.Lock()

    # --- state ---
    def _load(self) -> dict:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def state(self, project_id: str) -> dict:
        with self._lock:
            return dict(self._load().get(project_id) or {})

    def _update(self, project_id: str, **kw) -> dict:
        with self._lock:
            data = self._load()
            st = {**(data.get(project_id) or {}), **kw}
            data[project_id] = st
            self._save(data)
            return st

    def set_autopilot(self, project_id: str, on: bool) -> dict:
        return self._update(project_id, autopilot=bool(on))

    # --- helpers ---
    def _say(self, project_id: str, agent: str, text: str) -> None:
        try:
            self.chat.add(project_id, agent, "agent", text)
        except ValueError:
            pass

    def _advance(self, project_id: str, evidence: str, note: str, key: str) -> bool:
        from mvp_factory import MvpError
        try:
            self.registry.record(project_id, "advance", actor_role="agent", actor="mvp-pipeline", evidence=[evidence],
                                 note=note, idempotency_key=key)
            return True
        except MvpError:
            return False

    def _failed(self, project_id: str, agent: str, what: str, reason: str) -> None:
        self._update(project_id, last_error={"agent": agent, "reason": reason[:120], "at": self.clock()})
        self._say(project_id, agent, f"⚠️ {what} не вдалося ({reason}). Спробую знову через 30 хв або напиши мені тут.")

    def _cooling(self, project_id: str) -> bool:
        err = self.state(project_id).get("last_error") or {}
        return bool(err) and self.clock() - float(err.get("at") or 0) < RETRY_AFTER

    # --- the agents ---
    def run_research(self, project: dict) -> bool:
        pid = project["id"]
        text, reason = self.gemini(research_prompt(project))
        data = _json(text) if text else None
        variants = (data or {}).get("variants") or []
        if not data or len(variants) < 2:
            self._failed(pid, "researcher", "Дослідження", reason or "відповідь не в потрібному форматі")
            return False
        link = self.artifacts.save(pid, "research.json", json.dumps(data, ensure_ascii=False))
        md = self.artifacts.save(pid, "research.md", research_markdown(project, data))
        rec = str(data.get("recommended") or variants[0].get("id") or "A")
        self._update(pid, variant=rec, last_error=None)
        self._say(pid, "researcher", f"✅ Дослідження готове: {len(variants)} варіанти, рекомендую {rec}. {md}")
        return self._advance(pid, md, f"research done, recommended variant {rec}", f"mvp:{pid}:research") and bool(link)

    def run_spec(self, project: dict, feedback: str = "") -> bool:
        pid = project["id"]
        research = _json(self.artifacts.read(pid, "research.json") or "") or {}
        variant = self.state(pid).get("variant") or research.get("recommended") or "A"
        text, reason = self.gemini(spec_prompt(project, research, variant, feedback))
        if not text or "Готово" not in text:
            self._failed(pid, "spec", "ТЗ", reason or "у ТЗ немає розділу «Готово, коли»")
            return False
        version = int(self.state(pid).get("spec_version") or 0) + 1
        link = self.artifacts.save(pid, f"spec-v{version}.md", text)
        self.artifacts.save(pid, "spec.md", text)
        self._update(pid, spec_version=version, last_error=None)
        self._say(pid, "spec", f"✅ ТЗ v{version} готове (варіант {variant}). Потрібне твоє «так» перед збіркою: {link}")
        if project.get("stage") == "spec_draft":
            return self._advance(pid, link, f"spec v{version} written (variant {variant})", f"mvp:{pid}:spec")
        return True

    def start_build(self, project: dict) -> bool:
        pid = project["id"]
        st = self.state(pid)
        if st.get("build_ticket"):
            return False
        spec_md = self.artifacts.read(pid, "spec.md") or ""
        ticket = self.create_ticket(f"MVP {project.get('title')}: збірка за ТЗ", build_ticket_body(project, spec_md),
                                    f"mvp:{pid}:build:{st.get('spec_version') or 1}", pid)
        self._update(pid, build_ticket=ticket.get("id"))
        self._say(pid, "builder", f"📥 Отримав ТЗ. Створив задачу {ticket.get('id')} для Claude-воркера: окрема гілка, "
                                  f"код у {REPO_ROOT_DIR}/{pid}/, PR, CI. Повідомлю, коли буде PR.")
        return True

    # --- one pass ---
    def tick(self) -> list:
        moved = []
        for project in self.registry.snapshot()["projects"]:
            pid = project["id"]
            st = self.state(pid)
            if not st.get("autopilot") or project.get("blocked") or self._cooling(pid):
                continue
            stage = project.get("stage")
            if stage == "idea":
                if not project.get("brief"):
                    continue
                brief = self.artifacts.save(pid, "brief.md", f"# ТЗ власника · {project.get('title')}\n\n{project['brief']}")
                if self._advance(pid, brief, "autopilot started: Researcher takes the brief", f"mvp:{pid}:start"):
                    self._say(pid, "researcher", "🔎 Взяв ТЗ власника, починаю дослідження.")
                    moved.append((pid, "researching"))
            elif stage == "researching":
                if self.run_research(project):
                    moved.append((pid, "spec_draft"))
            elif stage == "spec_draft":
                if self.run_spec(project):
                    moved.append((pid, "spec_review"))
            elif stage == "build_queued":
                if not st.get("build_ticket"):
                    if self.start_build(project):
                        moved.append((pid, "build_ticket"))
                    continue
                ex = (self.get_ticket(st["build_ticket"]) or {}).get("execution") or {}
                if ex.get("pr_url") and self._advance(pid, ex["pr_url"], f"Builder opened {ex['pr_url']}", f"mvp:{pid}:building"):
                    self._say(pid, "builder", f"🔗 PR відкрито: {ex['pr_url']}. Чекаю CI і твій мерж.")
                    moved.append((pid, "building"))
            elif stage == "building":
                ticket = self.get_ticket(st.get("build_ticket") or "")
                if ticket and self.ticket_done(ticket):
                    pr = (ticket.get("execution") or {}).get("pr_url") or ""
                    if pr and self._advance(pid, pr, "build verified: merged PR + CI", f"mvp:{pid}:built"):
                        self._say(pid, "qa", f"🧪 Збірку підтверджено доказами ({pr}). Далі — перевірка й прев'ю.")
                        moved.append((pid, "qa_review"))
        return moved
