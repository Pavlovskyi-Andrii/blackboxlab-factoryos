import json
import os
import pathlib
import subprocess
import time
from typing import Any

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

PROMPT = (
    "Работай строго по CLAUDE.md. Возьми первую незакрытую задачу ROADMAP.md без [HUMAN], "
    "доведи только её до проверяемого DONE, запиши решения, тесты и .autopilot/status.json, "
    "сделай один commit с ID задачи. Не трогай main и production."
)


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


def roadmap_has_safe_work() -> bool:
    if not ROADMAP.exists():
        return False
    for raw in ROADMAP.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- [ ]") and "[HUMAN]" not in line:
            return True
    return False


def first_human_blocker() -> str:
    if not ROADMAP.exists():
        return ""
    for raw in ROADMAP.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("- [ ]") and "[HUMAN]" in line:
            return line
    return ""


def load_status() -> dict[str, Any]:
    if not STATUS.exists():
        return {"status": "failed", "summary": "agent did not write .autopilot/status.json"}
    try:
        value = json.loads(STATUS.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"status": "failed", "summary": f"invalid status.json: {exc}"}
    if not isinstance(value, dict):
        return {"status": "failed", "summary": "status.json is not an object"}
    return value


def run_agent() -> dict[str, Any]:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.unlink(missing_ok=True)
    cmd = [
        "claude",
        "-p",
        PROMPT,
        "--output-format",
        "json",
        "--max-turns",
        str(MAX_TURNS),
    ]
    if SKIP_PERMISSIONS:
        cmd.append("--dangerously-skip-permissions")
    try:
        subprocess.run(cmd, cwd=REPO, timeout=TASK_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        return {"status": "failed", "summary": f"agent timed out after {TASK_TIMEOUT_SECONDS}s"}
    return load_status()


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
        status = run_agent()
        state = str(status.get("status") or "failed").strip().lower()
        task = str(status.get("task") or "unknown")
        summary = str(status.get("summary") or "").strip()

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
