from __future__ import annotations
import json
import os
import pathlib
import subprocess
import time
from typing import Any

try:
    from .delegation import build_delegation, report_result, run_delegation, write_evidence
    from .notify import configured as telegram_configured
    from .notify import send, wait_answer
    from . import control
    from . import relay_tasks
except ImportError:
    from delegation import build_delegation, report_result, run_delegation, write_evidence
    from notify import configured as telegram_configured
    from notify import send, wait_answer
    import control
    import relay_tasks

def _default_repo() -> pathlib.Path:
    """AUTOPILOT_REPO wins; otherwise the container path; otherwise this checkout (EC2/phone runs)."""
    configured = os.environ.get("AUTOPILOT_REPO", "").strip()
    if configured:
        return pathlib.Path(configured).resolve()
    container = pathlib.Path("/work/factoryos")
    if (container / "ROADMAP.md").exists():
        return container.resolve()
    return pathlib.Path(__file__).resolve().parent.parent


REPO = _default_repo()
STATUS = REPO / ".autopilot" / "status.json"
ANSWERS = REPO / ".autopilot" / "answers.md"
ROADMAP = REPO / "ROADMAP.md"
MAX_FAILS = max(1, min(5, int(os.environ.get("AUTOPILOT_MAX_FAILS", "3"))))
MAX_TURNS = max(10, min(160, int(os.environ.get("AUTOPILOT_MAX_TURNS", "80"))))
TASK_TIMEOUT_SECONDS = max(600, min(7200, int(os.environ.get("AUTOPILOT_TASK_TIMEOUT_SECONDS", "3600"))))
PAUSE_SECONDS = max(5, min(3600, int(os.environ.get("AUTOPILOT_PAUSE_SECONDS", "30"))))
WAIT_FOR_HUMAN = os.environ.get("AUTOPILOT_WAIT_FOR_HUMAN", "0").strip().lower() in {"1", "true", "yes", "on"}
SKIP_PERMISSIONS = os.environ.get("AUTOPILOT_SKIP_PERMISSIONS", "0").strip().lower() in {"1", "true", "yes", "on"}
DAEMON_MODE = os.environ.get("AUTOPILOT_DAEMON", "1").strip().lower() in {"1", "true", "yes", "on"}
IDLE_SECONDS = max(15, min(3600, int(os.environ.get("AUTOPILOT_IDLE_SECONDS", "60"))))
# Operator identity of this runner. Roadmap tasks carrying `Owner: <other operator>` are skipped.
OPERATOR = os.environ.get("AUTOPILOT_OPERATOR", "claude").strip().lower() or "claude"
SHARED_OWNERS = {"", "any", "auto"}
RELAY_ONLY = os.environ.get("AUTOPILOT_RELAY_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}

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


# Metadata may share a line with other fields ("Planner: owner; Executor: ... Depends: T-590.").
DEPENDS_META_RE = __import__("re").compile(r"\bDepends:\s*(T-[A-Za-z0-9-]+(?:\s*,\s*[^,;.\s(]+)*)", __import__("re").IGNORECASE)
OWNER_META_RE = __import__("re").compile(r"\bOwner:\s*([A-Za-z0-9_-]*)", __import__("re").IGNORECASE)
TASK_ID_RE = __import__("re").compile(r"^T-[A-Za-z0-9-]+$")


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
            # Indented metadata belongs to the task directly above it.
            if tasks and raw[:1].isspace():
                depends = DEPENDS_META_RE.search(line)
                if depends:
                    ids = [x.strip().rstrip("-") for x in depends.group(1).split(",")]
                    tasks[-1]["depends"] = [x for x in ids if TASK_ID_RE.match(x)]
                owner = OWNER_META_RE.search(line)
                if owner:
                    tasks[-1]["owner"] = owner.group(1).lower()
            continue
        tasks.append({
            "id": match.group(3),
            "title": match.group(4).strip(),
            "done": match.group(1).lower() == "x",
            "human": bool(match.group(2)),
            "version": version,
            "depends": [],
            "owner": "",
        })
    return tasks


def owned_by_operator(task: dict[str, Any], operator: str = "") -> bool:
    owner = str(task.get("owner") or "").lower()
    return owner in SHARED_OWNERS or owner == (operator or OPERATOR)


def unmet_dependencies(task: dict[str, Any], tasks: list[dict[str, Any]]) -> list[str]:
    """A dependency is met only when it exists in the roadmap and is checked. Unknown IDs stay unmet."""
    done = {x["id"] for x in tasks if x["done"]}
    return [dep for dep in task.get("depends") or [] if dep not in done]


def selectable(task: dict[str, Any], tasks: list[dict[str, Any]], operator: str = "") -> bool:
    return (
        not task["done"]
        and not task["human"]
        and owned_by_operator(task, operator)
        and not unmet_dependencies(task, tasks)
    )


def next_safe_task(path: pathlib.Path = ROADMAP, operator: str = "", skip: set[str] | frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """First selectable task, ignoring `skip` (tasks this runner parked as blocked or failed)."""
    tasks = parse_roadmap(path)
    return next((task for task in tasks if task["id"] not in skip and selectable(task, tasks, operator)), None)


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


def push_branch(branch: str) -> bool:
    return run(["git", "push", "origin", branch], check=False).returncode == 0


def commits_ahead(branch: str) -> int:
    result = run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], check=False, capture=True)
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def answers_marker() -> int:
    try:
        return ANSWERS.stat().st_mtime_ns
    except FileNotFoundError:
        return 0


def write_runtime_status(status: str, *, task: str = "", summary: str = "", need: str = "") -> None:
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "task": task,
        "status": status,
        "summary": summary,
        "need": need,
        "checks": [],
        "commit": "",
    }
    tmp = STATUS.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATUS)


def poll_control(paused: bool, held_task: str | set[str], decided: dict[str, tuple[str, str]], *, fetch=None, ack=None) -> dict[str, Any]:
    """Apply owner pause/resume/retry between tasks. Unreachable FactoryOS keeps the last pause level."""
    decision = control.decide((fetch or control.fetch)(), paused=paused, held_task=held_task, decided=decided)
    for command_id, outcome, detail in decision["acks"]:
        decided[command_id] = (outcome, detail)
        (ack or control.ack)(command_id, outcome, detail)
    return decision


def idle_notice(path: pathlib.Path = ROADMAP, parked: set[str] | frozenset[str] = frozenset()) -> str:
    if parked:
        return f"🙋 Remaining safe tasks are parked as blocked/failed and wait for owner input or Retry: {', '.join(sorted(parked))}"
    tasks = parse_roadmap(path)
    waiting = [
        t["id"] for t in tasks
        if not t["done"] and not t["human"] and not selectable(t, tasks)
    ]
    if waiting:
        shown = ", ".join(waiting[:5]) + ("…" if len(waiting) > 5 else "")
        return f"⏳ No task is selectable for {OPERATOR}; waiting on dependencies or another operator: {shown}"
    blocker = first_human_blocker(path)
    if blocker:
        return f"🙋 Safe roadmap tasks are complete. HUMAN task remains: {blocker}"
    return "🏁 FactoryOS roadmap has no remaining safe tasks."


def main() -> int:
    branch = assert_safe_branch()
    failures = 0
    failures_task = ""
    # T-599-A: a blocked or failed task is parked instead of stalling the whole queue.
    # Blocked tasks wake up when answers/HEAD change; failed ones only on an owner Retry.
    blocked: dict[str, int] = {}
    failed_hold: set[str] = set()
    last_idle_notice = ""
    paused = False
    paused_status = ""
    decided: dict[str, tuple[str, str]] = {}

    while True:
        # Owner controls are only read here, between tasks, so a pause never interrupts a running task.
        decision = poll_control(paused, set(blocked) | failed_hold, decided)
        if decision["retry"]:
            send(f"🔁 {decision['retry']}: owner requested a retry from FactoryOS.")
            failures = 0
            blocked.pop(decision["retry"], None)
            failed_hold.discard(decision["retry"])
        if decision["paused"]:
            if not paused:
                paused_status = STATUS.read_text(encoding="utf-8") if STATUS.exists() else ""
                write_runtime_status("paused", summary="Paused by the owner from FactoryOS; no new task starts until Resume.")
                send("⏸ Autopilot paused by the owner. No new task will start until Resume.")
            paused = True
            if not DAEMON_MODE:
                return 5
            time.sleep(IDLE_SECONDS)
            continue
        if paused:
            paused = False
            if paused_status:
                STATUS.write_text(paused_status, encoding="utf-8")
            send("▶️ Autopilot resumed by the owner.")

        sync_branch(branch)

        # Never advance to another task while verified local commits are still
        # waiting to reach the dedicated remote branch.
        if commits_ahead(branch) > 0:
            if push_branch(branch):
                failures = 0
            else:
                failures += 1
                send(f"⚠️ Git push to {branch} failed ({failures}/{MAX_FAILS}); worker will retry.")
                if not DAEMON_MODE and failures >= MAX_FAILS:
                    return 4
                time.sleep(IDLE_SECONDS if DAEMON_MODE else PAUSE_SECONDS)
                continue

        # Relay owner tickets have priority over ordinary roadmap work. This is
        # an actual claim + bounded Claude CLI invocation, not a UI status flip.
        if relay_tasks.run_one(REPO, status_fn=write_runtime_status):
            last_idle_notice = ""
            time.sleep(PAUSE_SECONDS)
            continue

        # Keep the dedicated EC2 Relay executor focused on owner requests.
        # It must not silently consume unrelated ROADMAP tasks while idle.
        if RELAY_ONLY:
            write_runtime_status("idle", summary="Relay worker online, waiting for queued owner tasks")
            if not DAEMON_MODE:
                return 0
            time.sleep(IDLE_SECONDS)
            continue

        # Only new owner input (answers.md) or an explicit Retry wakes a blocked task; our own
        # commits on other tasks must not make it burn another turn.
        marker = answers_marker()
        for task_id in [t for t, m in blocked.items() if m != marker]:
            del blocked[task_id]
        parked = set(blocked) | failed_hold
        target = next_safe_task(ROADMAP, skip=parked)
        if not target:
            notice = idle_notice(ROADMAP, parked=parked & {t["id"] for t in parse_roadmap(ROADMAP) if not t["done"]})
            write_runtime_status("idle", summary=notice)
            if notice != last_idle_notice:
                suffix = f" Polling every {IDLE_SECONDS}s." if DAEMON_MODE else ""
                send(notice + suffix)
                last_idle_notice = notice
            if not DAEMON_MODE:
                return 0
            time.sleep(IDLE_SECONDS)
            continue

        last_idle_notice = ""
        if failures_task != target["id"]:
            failures_task = target["id"]
            failures = 0
        if current_branch() != branch:
            raise RuntimeError(f"Branch changed from {branch} while running; autopilot refuses to continue.")

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
            if not push_branch(branch):
                failures = 1
                send(f"⚠️ {task} is committed locally but push failed; worker will retry without rerunning the task.")
                if not DAEMON_MODE:
                    return 4
                time.sleep(IDLE_SECONDS)
                continue
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
            if DAEMON_MODE:
                blocked[target["id"]] = answers_marker()
                time.sleep(PAUSE_SECONDS)
                continue
            return 2

        failures += 1
        send(f"⚠️ {task}: autonomous attempt failed ({failures}/{MAX_FAILS}). {summary}")
        if failures >= MAX_FAILS:
            if not DAEMON_MODE:
                send(f"⛔ {MAX_FAILS} failures in a row. Autopilot stopped. Last: {summary}")
                return 3
            failed_hold.add(target["id"])
            failures = 0
            send(f"⛔ {MAX_FAILS} failures in a row on {target['id']}. Parked without new attempts; moving to the next safe task. "
                 f"use Retry in FactoryOS Workers to try again. Last: {summary}")
        time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
