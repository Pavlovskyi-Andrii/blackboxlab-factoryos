import os
import pathlib
import subprocess
import time
from typing import Any

try:
    from .delegation import build_delegation, report_result, run_delegation, write_evidence
    from .notify import configured as telegram_configured
    from .notify import send, wait_answer
except ImportError:
    from delegation import build_delegation, report_result, run_delegation, write_evidence
    from notify import configured as telegram_configured
    from notify import send, wait_answer

REPO = pathlib.Path(os.environ.get("AUTOPILOT_REPO", "/work/factoryos")).resolve()
STATUS = REPO / ".autopilot" / "status.json"
ANSWERS = REPO / ".autopilot" / "answers.md"
ROADMAP = REPO / "ROADMAP.md"
MAX_FAILS = max(1, min(5, int(os.environ.get("AUTOPILOT_MAX_FAILS", "3"))))
MAX_TURNS = max(10, min(160, int(os.environ.get("AUTOPILOT_MAX_TURNS", "80"))))
TASK_TIMEOUT_SECONDS = max(600, min(7200, int(os.environ.get("AUTOPILOT_TASK_TIMEOUT_SECONDS", "3600"))))
PAUSE_SECONDS = max(5, min(3600, int(os.environ.get("AUTOPILOT_PAUSE_SECONDS", "30"))))
WAIT_FOR_HUMAN = os.environ.get("AUTOPILOT_WAIT_FOR_HUMAN", "0").strip().lower() in {"1", "true", "yes", "on"}
SKIP_PERMISSIONS = os.environ.get("AUTOPILOT_SKIP_PERMISSIONS", "0").strip().lower() in {"1", "true", "yes", "on"}

def run(cmd: list[str], *, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=REPO,
        check=check,
        text=True,
        capture_output=capture,
    )


def current_branch() -> str:
    result = run(["git", "branch", "--show-current"], capture=True)
    return result.stdout.strip()


def assert_safe_branch() -> str:
    branch = current_branch()
    if not branch or branch in {"main", "master"}:
        raise RuntimeError("Autopilot refuses to run on main/master. Checkout a dedicated autopilot branch.")
    return branch


TASK_RE = __import__("re").compile(r"^- \[([ xX])\]\s+(\[HUMAN\]\s+)?(T-[A-Za-z0-9-]+)\s+(.+)$")


def parse_roadmap(path: pathlib.Path = ROADMAP) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    version = ""
    tasks: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            version = line[3:].strip()
            continue
        match = TASK_RE.match(line)
        if not match:
            continue
        tasks.append({
            "id": match.group(3),
            "title": match.group(4).strip(),
            "done": match.group(1).lower() == "x",
            "human": bool(match.group(2)),
            "version": version,
        })
    return tasks


def next_safe_task(path: pathlib.Path = ROADMAP) -> dict[str, Any] | None:
    return next((task for task in parse_roadmap(path) if not task["done"] and not task["human"]), None)


def roadmap_has_safe_work(path: pathlib.Path = ROADMAP) -> bool:
    return next_safe_task(path) is not None


def first_human_blocker(path: pathlib.Path = ROADMAP) -> str:
    task = next((task for task in parse_roadmap(path) if not task["done"] and task["human"]), None)
    return f"{task['id']} · {task['title']}" if task else ""


def done_status_is_consistent(status: dict[str, Any], expected_task: dict[str, Any], path: pathlib.Path = ROADMAP) -> bool:
    task_id = str(status.get("task") or "")
    if not expected_task or task_id != expected_task.get("id"):
        return False
    persisted = next((task for task in parse_roadmap(path) if task["id"] == task_id), None)
    return bool(persisted and persisted["done"] and not persisted["human"])


def run_agent(target: dict[str, Any]) -> dict[str, Any]:
    try:
        spec = build_delegation(
            target,
            REPO,
            max_turns=MAX_TURNS,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            skip_permissions=SKIP_PERMISSIONS,
        )
    except ValueError as exc:
        return {"task": target.get("id"), "status": "failed", "summary": f"delegation refused: {exc}"}
    evidence = run_delegation(spec)
    write_evidence(REPO, evidence)
    report_result(evidence)
    status = dict(evidence["status"])
    status["status"] = evidence["result"]
    if evidence["violations"]:
        status["summary"] = "; ".join(evidence["violations"])
    return status


def append_answer(task: str, answer: str) -> None:
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    with ANSWERS.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {task or 'blocked-task'}\n{answer.strip()}\n")


def sync_branch(branch: str) -> None:
    run(["git", "pull", "--rebase", "origin", branch], check=False)


def push_branch(branch: str) -> None:
    run(["git", "push", "origin", branch])


def main() -> int:
    branch = assert_safe_branch()
    failures = 0

    while roadmap_has_safe_work():
        sync_branch(branch)
        target = next_safe_task()
        if not target:
            break
        status = run_agent(target)
        state = str(status.get("status") or "failed").strip().lower()
        task = str(status.get("task") or "unknown")
        summary = str(status.get("summary") or "").strip()

        if task not in {target["id"], "unknown"}:
            state = "failed"
            summary = f"agent reported unexpected task {task}; expected {target['id']}"

        if state == "done" and not done_status_is_consistent(status, target):
            state = "failed"
            summary = f"{target['id']} reported done but ROADMAP checkbox was not closed"

        if state == "done":
            failures = 0
            push_branch(branch)
            send(f"✅ {task}: {summary}")
            time.sleep(PAUSE_SECONDS)
            continue

        if state == "blocked":
            need = str(status.get("need") or "Owner input required").strip()
            send(f"🙋 {task} ждёт тебя:\n{need}")
            if WAIT_FOR_HUMAN and telegram_configured():
                answer = wait_answer()
                if answer:
                    append_answer(task, answer)
                    time.sleep(PAUSE_SECONDS)
                    continue
            return 2

        failures += 1
        send(f"⚠️ {task}: autonomous attempt failed ({failures}/{MAX_FAILS}). {summary}")
        if failures >= MAX_FAILS:
            send(f"⛔ {MAX_FAILS} failures in a row. Autopilot stopped. Last: {summary}")
            return 3
        time.sleep(PAUSE_SECONDS)

    blocker = first_human_blocker()
    if blocker:
        send(f"🙋 Safe roadmap tasks are complete. HUMAN task remains: {blocker}")
    else:
        send("🏁 FactoryOS roadmap has no remaining safe tasks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
