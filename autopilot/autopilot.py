from __future__ import annotations
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
from typing import Any

try:
    from .delegation import agent_preflight, build_delegation, limit_reset_epoch, report_result, run_delegation, write_evidence
    from .notify import configured as telegram_configured
    from .notify import send, wait_answer
    from . import control
    from . import relay_tasks
    from . import owner_questions
    from . import browser_tasks, codex_review, main_ci_watch, mycast_daily, mycast_listeners
    from . import mods_runtime
    from . import worker_heartbeat
except ImportError:
    from delegation import agent_preflight, build_delegation, limit_reset_epoch, report_result, run_delegation, write_evidence
    from notify import configured as telegram_configured
    from notify import send, wait_answer
    import mods_runtime
    import worker_heartbeat
    import control
    import relay_tasks
    import owner_questions
    import browser_tasks
    import codex_review
    import main_ci_watch
    import mycast_daily
    import mycast_listeners

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
# T-714: this loop's own heartbeat (read by the root supervisor's watchdog) and the dedicated Surfer worker's.
LOOP_BEAT = worker_heartbeat.path_for(REPO, worker_heartbeat.CLAUDE_LOOP_FILE)
SURFER_BEAT = worker_heartbeat.path_for(REPO, worker_heartbeat.SURFER_FILE)
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
# T-607: which agent CLI runs a task. The Gemini lane runs Gemini CLI on the owner's Google-account login.
AGENT = (os.environ.get("AUTOPILOT_AGENT", "").strip().lower()
         or (OPERATOR if OPERATOR in {"claude", "gemini"} else "claude"))
# A non-Claude lane takes only tasks that name it (`Owner: gemini`), never shared/unowned work (ROADMAP T-607).
EXPLICIT_OWNER_ONLY = os.environ.get("AUTOPILOT_EXPLICIT_OWNER_ONLY", "1" if OPERATOR != "claude" else "0"
                                     ).strip().lower() in {"1", "true", "yes", "on"}
# Owner questions, MyCast, Codex review, browser tasks and Relay owner tickets belong to the Claude runner.
CLAUDE_SIDE_JOBS = OPERATOR == "claude"
# T-599-C: without a server claim no ROADMAP task runs, unless explicitly allowed for offline dev runs.
ALLOW_UNCLAIMED = os.environ.get("AUTOPILOT_ALLOW_UNCLAIMED", "0").strip().lower() in {"1", "true", "yes", "on"}
CLAIM_RETRY_SECONDS = 300
# The worker branch follows main between tasks so new ROADMAP tasks and runner fixes arrive
# without a manual merge. A runner code change restarts the process via claude_pro_worker.
BASE_BRANCH = os.environ.get("AUTOPILOT_BASE_BRANCH", "main").strip() or "main"
EXIT_CODE_UPDATED = 75
RELAY_ONLY = os.environ.get("AUTOPILOT_RELAY_ONLY", "0").strip().lower() in {"1", "true", "yes", "on"}
# T-598: network git (pull/fetch/push) is bounded and never waits on a credential prompt, so an
# unreachable remote is a short failed sync, not an endless "busy" worker.
GIT_NET_TIMEOUT = max(10, min(600, int(os.environ.get("AUTOPILOT_GIT_TIMEOUT_SECONDS", "120"))))
# T-600: a subscription limit is account-wide, so the whole queue waits for the reset. When the CLI
# gives no readable reset time we retry after this back-off; the grace avoids racing the reset.
LIMIT_BACKOFF_SECONDS = max(300, min(21600, int(os.environ.get("AUTOPILOT_LIMIT_BACKOFF_SECONDS", "1800"))))
LIMIT_GRACE_SECONDS = 120
MYCAST_ENABLED = os.environ.get("AUTOPILOT_MYCAST", "1").strip().lower() in {"1", "true", "yes", "on"}


def run(cmd: list[str], *, check: bool = True, capture: bool = False, timeout: float | None = None) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            cmd,
            cwd=REPO,
            check=check,
            text=True,
            capture_output=capture,
            timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.TimeoutExpired:
        if check:
            raise
        return subprocess.CompletedProcess(cmd, 124, "", f"timed out after {timeout}s")


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
    operator = operator or OPERATOR
    if EXPLICIT_OWNER_ONLY and operator == OPERATOR:
        return owner == operator
    return owner in SHARED_OWNERS or owner == operator


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
    # Owner's switched-on mods, this run only. They are Claude Code plugins: the Gemini lane never loads them.
    mods = mods_runtime.prepare(REPO, "roadmap") if AGENT == "claude" else None
    try:
        spec = build_delegation(
            target,
            REPO,
            max_turns=MAX_TURNS,
            timeout_seconds=TASK_TIMEOUT_SECONDS,
            skip_permissions=SKIP_PERMISSIONS,
            agent=AGENT,
            mods=mods,
        )
    except ValueError as exc:
        return {"task": target.get("id"), "status": "failed", "summary": f"delegation refused: {exc}"}
    refused = agent_preflight(spec)
    if refused:
        return {"task": target.get("id"), **refused}
    evidence = run_delegation(spec)
    write_evidence(REPO, evidence)
    if AGENT == "claude":
        report_result(evidence)   # /api/claude-worker/task-result is the Claude lane's own record
        mods_runtime.report_run(spec["mods"], run_id=str(evidence.get("run_id") or ""), task=str(target.get("id") or ""),
                                kind="roadmap", result=str(evidence.get("result") or ""),
                                duration_seconds=evidence.get("duration_seconds") or 0)
    status = dict(evidence["status"])
    status["status"] = evidence["result"]
    if evidence["violations"]:
        status["summary"] = "; ".join(evidence["violations"])
    return status


def append_answer(task: str, answer: str) -> None:
    ANSWERS.parent.mkdir(parents=True, exist_ok=True)
    with ANSWERS.open("a", encoding="utf-8") as handle:
        handle.write(f"\n## {task or 'blocked-task'}\n{answer.strip()}\n")


RUNNER_CODE_DIRS = ("autopilot/", "browser_runner/")


_TASK_HEADER_RE = re.compile(r"^\s*- \[[ xX]\] (?:\[HUMAN\] )?(T-[A-Za-z0-9-]+)")


def merge_roadmap_text(text: str) -> str | None:
    """Resolve conflict blocks in ROADMAP.md: keep both sides' lines (worker notes first, then main's), but a task
    header (`- [ ] T-…`) that both sides changed is taken from main only, so a task never appears twice with two
    checkbox states. Returns None when the markers are malformed."""
    out: list[str] = []
    lines = text.splitlines(keepends=True)
    i = 0
    while i < len(lines):
        if not lines[i].startswith("<<<<<<< "):
            out.append(lines[i])
            i += 1
            continue
        ours: list[str] = []
        theirs: list[str] = []
        section = ours
        i += 1
        while i < len(lines) and not lines[i].startswith(">>>>>>> "):
            line = lines[i]
            if line.startswith("||||||| "):
                section = []                       # diff3 base section: not kept
            elif line.rstrip("\r\n") == "=======":
                section = theirs
            elif line.startswith("<<<<<<< "):
                return None
            else:
                section.append(line)
            i += 1
        if i >= len(lines):
            return None
        i += 1
        main_ids = {m.group(1) for m in map(_TASK_HEADER_RE.match, theirs) if m}
        kept = [line for line in ours if not ((m := _TASK_HEADER_RE.match(line)) and m.group(1) in main_ids)]
        out.extend(line for line in kept if line not in theirs)
        out.extend(theirs)
    return "".join(out)


def resolve_roadmap_only_conflict() -> bool:
    """Owner 2026-11-17: a merge whose only conflict is ROADMAP.md (status notes written on both sides) is resolved
    automatically and committed; any other conflicted file leaves the merge to be aborted as before. 2026-11-16: two
    T-590 notes kept the EC2 worker on day-old code (36 commits behind main) until a human merged by hand."""
    conflicted = run(["git", "diff", "--name-only", "--diff-filter=U"], check=False, capture=True).stdout.split()
    if conflicted != ["ROADMAP.md"]:
        return False
    path = pathlib.Path(REPO) / "ROADMAP.md"
    try:
        merged = merge_roadmap_text(path.read_text(encoding="utf-8"))
    except OSError:
        return False
    if merged is None or any(line.startswith(("<<<<<<< ", ">>>>>>> ")) for line in merged.splitlines()):
        return False
    path.write_text(merged, encoding="utf-8")
    if run(["git", "add", "ROADMAP.md"], check=False).returncode != 0:
        return False
    return run(["git", "commit", "--no-edit", "--no-verify"], check=False, capture=True).returncode == 0


def sync_branch(branch: str) -> str:
    """Pull the worker branch, then bring in main. Returns "", "code_updated", "conflict" or "offline".

    Runner code can arrive through either step (a fix pushed to the worker branch, or main), so the
    comparison starts before the pull; otherwise new runner code sits on disk without being loaded.
    """
    # 2026-11-04: "pull --rebase" replayed main's merge commits one by one, stopped on a conflict that a
    # merge commit had already resolved, and left the checkout mid-rebase; the worker was down for ~7 h.
    # Never rebase: abort a leftover rebase, then fast-forward or merge the remote worker branch.
    git_dir = pathlib.Path(REPO) / ".git"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        run(["git", "rebase", "--abort"], check=False)
    # #236: a restart in the middle of a merge leaves MERGE_HEAD behind; every later merge would then fail and the
    # worker would report "conflict" forever. Abort it (committed work is untouched) and sync again from scratch.
    if (git_dir / "MERGE_HEAD").exists():
        run(["git", "merge", "--abort"], check=False)
    before = git_head()
    if run(["git", "fetch", "origin", branch], check=False, timeout=GIT_NET_TIMEOUT).returncode == 0:
        remote = f"origin/{branch}"
        if run(["git", "merge", "--ff-only", remote], check=False, capture=True).returncode != 0:
            if run(["git", "merge", "--no-edit", remote], check=False, capture=True).returncode != 0:
                if not resolve_roadmap_only_conflict():
                    run(["git", "merge", "--abort"], check=False)
                    return "conflict"
    if run(["git", "fetch", "origin", BASE_BRANCH], check=False, timeout=GIT_NET_TIMEOUT).returncode != 0:
        return "offline"
    target = f"origin/{BASE_BRANCH}"
    if run(["git", "merge", "--ff-only", target], check=False, capture=True).returncode != 0:
        if run(["git", "merge", "--no-edit", target], check=False, capture=True).returncode != 0:
            if not resolve_roadmap_only_conflict():
                run(["git", "merge", "--abort"], check=False)
                return "conflict"
    after = git_head()
    if not before or after == before:
        return ""
    changed = run(["git", "diff", "--name-only", before, after], check=False, capture=True).stdout.split()
    # T-670: the browser worker imports browser_runner/ once per process, so its changes need the same restart.
    return "code_updated" if any(name.startswith(RUNNER_CODE_DIRS) and name.endswith(".py") for name in changed) else ""


def push_branch(branch: str) -> bool:
    return run(["git", "push", "origin", branch], check=False, timeout=GIT_NET_TIMEOUT).returncode == 0


def git_head() -> str:
    result = run(["git", "rev-parse", "HEAD"], check=False, capture=True)
    return result.stdout.strip() if result.returncode == 0 else ""


def commits_ahead(branch: str) -> int:
    result = run(["git", "rev-list", "--count", f"origin/{branch}..HEAD"], check=False, capture=True)
    try:
        return int(result.stdout.strip()) if result.returncode == 0 else 0
    except ValueError:
        return 0


def answers_marker() -> int:
    """Fingerprint of the owner's answers: changes only when their *content* changes.

    2026-11-15: this used the file's mtime. A sync whose merge of main conflicted ran `git merge` +
    `git merge --abort` on every loop pass; both rewrite answers.md (main had changed it), so the mtime moved
    each pass, a blocked task was "woken" every ~2 minutes and Telegram got ~300 identical cards. A content
    hash ignores rewrites, checkouts and touches; only real new owner input wakes a blocked task.
    """
    try:
        data = ANSWERS.read_bytes()
    except OSError:
        return 0
    return int.from_bytes(hashlib.sha256(data).digest()[:7], "big") or 1


def parking_path() -> pathlib.Path:
    # Next to answers.md so it follows the repo (and test fixtures); gitignored.
    return ANSWERS.with_name("parking.json")


def load_parking() -> dict[str, Any]:
    """T-598: parked/failed tasks and the attempt counter survive a worker restart."""
    try:
        value = json.loads(parking_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        value = {}
    value = value if isinstance(value, dict) else {}
    blocked = value.get("blocked") if isinstance(value.get("blocked"), dict) else {}
    failed = value.get("failed") if isinstance(value.get("failed"), list) else []
    try:
        failures = max(0, int(value.get("failures") or 0))
    except (TypeError, ValueError):
        failures = 0
    try:
        limit_until = max(0.0, float(value.get("limit_until") or 0))
    except (TypeError, ValueError):
        limit_until = 0.0
    return {
        "blocked": {str(k): int(v) for k, v in blocked.items() if TASK_ID_RE.match(str(k)) and isinstance(v, int)},
        "failed": {str(x) for x in failed if TASK_ID_RE.match(str(x))},
        "failures_task": str(value.get("failures_task") or ""),
        "failures": failures,
        "limit_until": limit_until,
    }


def save_parking(blocked: dict[str, int], failed: set[str], failures_task: str, failures: int,
                 limit_until: float = 0.0) -> None:
    path = parking_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"blocked": blocked, "failed": sorted(failed), "failures_task": failures_task, "failures": failures,
               "limit_until": limit_until}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def commit_files(sha: str) -> list[str]:
    if not sha:
        return []
    result = run(["git", "show", "--name-only", "--format=", sha], check=False, capture=True)
    return [line for line in result.stdout.splitlines() if line.strip()] if result.returncode == 0 else []


def limit_notice(until: float) -> str:
    import datetime as dt

    moment = dt.datetime.fromtimestamp(until, dt.timezone.utc)
    return (f"⏳ Claude subscription limit reached. Queue paused until {moment:%H:%M} UTC ({_kyiv_label(moment)}); "
            "no task is parked or counted as failed. Resumes automatically.")


def _kyiv_label(moment: Any) -> str:
    try:
        from zoneinfo import ZoneInfo

        return moment.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%H:%M Kyiv")
    except Exception:  # tzdata missing: say so instead of pretending
        return "Kyiv time unavailable"


def milestone_report(task_id: str, stage: str, *, summary: str = "", owner: str = "", branch: str = "",
                     commit: str = "", files: list[str] | None = None, checks: list[Any] | None = None,
                     blocker: str = "", next_task: str = "", now: float | None = None) -> str:
    """Concise owner-visible checkpoint (M6). PR/CI/Render are never claimed by the worker."""
    from datetime import datetime, timezone

    moment = datetime.fromtimestamp(time.time() if now is None else now, timezone.utc)
    files = list(files or [])
    shown_files = ", ".join(files[:5]) + (f" (+{len(files) - 5})" if len(files) > 5 else "") if files else "—"
    shown_checks = "; ".join(str(c)[:80] for c in (checks or [])[:4]) or "none reported"
    lines = [
        f"🧭 {task_id} · {stage}",
        f"🕒 {moment.strftime('%Y-%m-%d %H:%M')} UTC · {_kyiv_label(moment)}",
        f"👤 owner {owner or 'any'} · executor {OPERATOR}",
        f"🌿 {branch or '?'} @ {commit[:10] if commit else 'no commit'}",
        f"📄 files: {shown_files}",
        f"🧪 checks: {shown_checks}",
        "🔎 PR / CI / Render: not verified by the worker",
        f"⛔ blocker: {blocker or '—'}",
        f"➡️ next: {next_task or '—'}",
    ]
    if summary:
        lines.append(summary[:300])
    return "\n".join(lines)


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


def loop_beat(state: str = "idle", *, long_job: bool = False, task: str = "") -> None:
    """T-714: promise the next beat within 15 min (plus the longest deliberate sleep), or within the task timeout
    plus 15 min before a Claude CLI run. A loop that breaks the promise is restarted by the supervisor's watchdog."""
    budget = (max(TASK_TIMEOUT_SECONDS, 3600) if long_job else max(IDLE_SECONDS, PAUSE_SECONDS)) + worker_heartbeat.STALE_AFTER_SECONDS
    worker_heartbeat.beat(LOOP_BEAT, budget_seconds=budget, state=state, task=task)


def run_browser_fallback() -> bool:
    """T-560 in-loop browser task, now only a fallback (T-714): while the dedicated Surfer worker beats, it owns the
    queue and this loop starts no second Chromium. True when a task was run."""
    if worker_heartbeat.alive(SURFER_BEAT):
        return False
    return browser_tasks.run_one() == "done"


def main() -> int:
    branch = assert_safe_branch()
    # T-599-A: a blocked or failed task is parked instead of stalling the whole queue.
    # Blocked tasks wake up when answers/HEAD change; failed ones only on an owner Retry.
    # T-598: this state is persisted, so a restart cannot reset the bounded retries.
    parking = load_parking()
    blocked: dict[str, int] = parking["blocked"]
    failed_hold: set[str] = parking["failed"]
    failures_task = parking["failures_task"]
    failures = parking["failures"]
    limit_until = parking["limit_until"]

    def persist() -> None:
        save_parking(blocked, failed_hold, failures_task, failures, limit_until)

    def hold_for_limit(hint: str) -> str:
        nonlocal limit_until
        reset_at = limit_reset_epoch(hint, time.time())
        limit_until = (reset_at + LIMIT_GRACE_SECONDS) if reset_at else time.time() + LIMIT_BACKOFF_SECONDS
        persist()
        return limit_notice(limit_until)

    # Tasks the server refused to hand us (another lane/run owns them): retry after a pause.
    deferred: dict[str, float] = {}
    last_idle_notice = ""
    paused = False
    paused_status = ""
    decided: dict[str, tuple[str, str]] = {}

    while True:
        loop_beat()
        # Owner controls are only read here, between tasks, so a pause never interrupts a running task.
        # The owner controls queue serves the Claude runner; a Gemini runner must not ack (and so swallow) its commands.
        decision = (poll_control(paused, set(blocked) | failed_hold, decided) if CLAUDE_SIDE_JOBS
                    else {"paused": False, "retry": "", "acks": []})
        if decision["retry"]:
            send(f"🔁 {decision['retry']}: owner requested a retry from FactoryOS.")
            failures = 0
            blocked.pop(decision["retry"], None)
            failed_hold.discard(decision["retry"])
            persist()
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

        sync = sync_branch(branch)
        if sync == "code_updated" and DAEMON_MODE:
            write_runtime_status("idle", summary=f"Runner code updated from {BASE_BRANCH}; restarting with the new code")
            send(f"♻️ Worker picked up new runner code from {BASE_BRANCH}; restarting between tasks.")
            return EXIT_CODE_UPDATED
        if sync == "conflict" and last_idle_notice != "conflict":
            last_idle_notice = "conflict"
            send(f"⚠️ {branch} cannot merge {BASE_BRANCH} cleanly; continuing on the current code. Owner/Claude must resolve the conflict.")

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

        # T-600: while the subscription limit holds, every Claude run would fail the same way.
        # Pushing verified commits (above) still happens; starting Claude does not.
        remaining = limit_until - time.time()
        if remaining > 0:
            write_runtime_status("idle", summary=limit_notice(limit_until))
            if not DAEMON_MODE:
                return 6
            time.sleep(max(1.0, min(float(IDLE_SECONDS), remaining)))
            continue
        if limit_until:
            limit_until = 0.0
            persist()
            send("▶️ Claude subscription limit window has passed; the queue resumes.")

        # T-607: the Gemini runner skips the Claude-only jobs below (they start Claude CLI or claim Claude tickets).
        if CLAUDE_SIDE_JOBS:
            # Owner desk questions, MyCast and Relay tickets can start Claude CLI: promise a long-job deadline.
            loop_beat("side_jobs", long_job=True)
            # Owner desk questions are short and read-only, so they go before any long task.
            owner_questions.maybe_selftest()
            asked, hint = owner_questions.answer_one(REPO)
            if asked == "limit":
                notice = hold_for_limit(hint)
                write_runtime_status("idle", summary=notice)
                send(notice)
                continue
            if asked in ("answered", "failed"):
                continue

            # T-603: the owner's morning MyCast episode, once a day, between tasks.
            if MYCAST_ENABLED:
                cast = mycast_daily.run_daily(ANSWERS.with_name("mycast.json"), repo=REPO)
                if cast == "limit":
                    notice = hold_for_limit("")
                    write_runtime_status("idle", summary=notice)
                    send(notice)
                    continue
                if cast != "idle":
                    continue
                # #317: website listeners' episodes, one per pass, only after the owner's own episode is settled.
                cast = mycast_listeners.run_listeners(ANSWERS.with_name("mycast_listeners.json"))
                if cast == "limit":
                    notice = hold_for_limit("")
                    write_runtime_status("idle", summary=notice)
                    send(notice)
                    continue
                if cast != "idle":
                    continue

            # Owner 2026-11-13: every open PR gets an automatic Codex review (advisory comment). Cheap: no model runs here,
            # Codex answers in its own isolated service; at most one new request per pass.
            codex_review.run_once(ANSWERS.with_name("codex_review.json"))
            # FO-09: one Telegram message when CI on main goes red, one when it is green again (gh read every 10 min).
            try:
                main_ci_watch.run_once(ANSWERS.with_name("main_ci_watch.json"), gh_fn=mycast_daily.gh, send=send)
            except Exception as exc:  # monitoring must never stop the worker loop
                print(f"main-ci-watch: {type(exc).__name__}", flush=True)
            # T-560: the owner's read-only browser tasks (anonymous Chromium, one per pass; idle without Playwright).
            # T-714: only when the dedicated Surfer worker (autopilot.browser_worker) is not alive.
            if run_browser_fallback():
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
        woken = [t for t, m in blocked.items() if m != marker]
        for task_id in woken:
            del blocked[task_id]
        if woken:
            persist()
        now = time.time()
        for task_id in [t for t, until in deferred.items() if until <= now]:
            del deferred[task_id]
        parked = set(blocked) | failed_hold | set(deferred)
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
            persist()
        if current_branch() != branch:
            raise RuntimeError(f"Branch changed from {branch} while running; autopilot refuses to continue.")

        ticket, reason = relay_tasks.claim_roadmap(target, OPERATOR)
        if ticket is None and not (ALLOW_UNCLAIMED and not relay_tasks.configured()):
            # Assignment is not execution: without a verified claim we never touch the code.
            deferred[target["id"]] = time.time() + CLAIM_RETRY_SECONDS
            write_runtime_status("idle", task=target["id"], summary=f"{target['id']} not started: {reason}")
            continue
        report = relay_tasks.RunReporter(ticket) if ticket else (lambda *a, **k: None)
        loop_beat("running", long_job=True, task=target["id"])
        head_before = git_head()
        if ticket:
            report("running", f"{target['id']}: Claude Code CLI started", {"branch": branch})
            with report:
                status = run_agent(target)
        else:
            status = run_agent(target)
        state = str(status.get("status") or "failed").strip().lower()
        task = str(status.get("task") or "unknown")
        summary = str(status.get("summary") or "").strip()

        if task not in {target["id"], "unknown"}:
            state = "failed"
            summary = f"agent reported unexpected task {task}; expected {target['id']}"

        if state == "done" and not done_status_is_consistent(status, target, ROADMAP):
            state = "failed"
            summary = f"{target['id']} reported done but ROADMAP checkbox was not closed"

        head_after = git_head()
        evidence = {"branch": branch}
        if head_after and head_after != head_before:
            evidence["commit"] = head_after
            report("committed", f"{target['id']}: commit {head_after[:10]} on {branch}", evidence)

        if status.get("error_category") == "subscription_limit":
            # Not the task's fault: no attempt counted, nothing parked; the next task would hit the same wall.
            notice = hold_for_limit(str(status.get("limit_resets") or ""))
            report("blocked", f"{target['id']}: not run — {notice}", evidence)
            write_runtime_status("idle", task=target["id"], summary=notice)
            send(notice)
            if not DAEMON_MODE:
                return 6
            time.sleep(PAUSE_SECONDS)
            continue

        if state == "done":
            failures = 0
            if not push_branch(branch):
                failures = 1
                report("blocked", f"{target['id']}: committed locally, push failed; worker retries the push only", evidence)
                send(f"⚠️ {task} is committed locally but push failed; worker will retry without rerunning the task.")
                if not DAEMON_MODE:
                    return 4
                time.sleep(IDLE_SECONDS)
                continue
            persist()
            report("pushed", f"{target['id']}: pushed to {branch}; PR/CI/merge not verified by the worker", {**evidence, "pushed": True})
            checks = ", ".join(str(c) for c in (status.get("checks") or [])[:6])
            report("done", f"{target['id']}: {summary}" + (f" · checks: {checks}" if checks else ""), {**evidence, "pushed": True})
            upcoming = next_safe_task(ROADMAP, skip=set(blocked) | failed_hold | set(deferred))
            send("✅ " + milestone_report(
                task, "done · pushed", summary=summary, owner=str(target.get("owner") or ""), branch=branch,
                commit=evidence.get("commit", ""), files=commit_files(evidence.get("commit", "")),
                checks=list(status.get("checks") or []), next_task=upcoming["id"] if upcoming else "",
            ))
            time.sleep(PAUSE_SECONDS)
            continue

        if state == "blocked":
            need = str(status.get("need") or "Owner input required").strip()
            report("blocked", f"{target['id']}: {need}", evidence)
            send("🙋 " + milestone_report(
                task, "blocked · waiting for owner", owner=str(target.get("owner") or ""), branch=branch,
                commit=evidence.get("commit", ""), blocker=need,
            ))
            if WAIT_FOR_HUMAN and telegram_configured():
                answer = wait_answer()
                if answer:
                    append_answer(task, answer)
                    time.sleep(PAUSE_SECONDS)
                    continue
            if DAEMON_MODE:
                blocked[target["id"]] = answers_marker()
                persist()
                time.sleep(PAUSE_SECONDS)
                continue
            return 2

        failures += 1
        persist()
        report("failed", f"{target['id']}: attempt {failures}/{MAX_FAILS} failed. {summary}", evidence)
        send(f"⚠️ {task}: autonomous attempt failed ({failures}/{MAX_FAILS}). {summary}")
        if failures >= MAX_FAILS:
            if not DAEMON_MODE:
                send(f"⛔ {MAX_FAILS} failures in a row. Autopilot stopped. Last: {summary}")
                return 3
            failed_hold.add(target["id"])
            failures = 0
            persist()
            send(f"⛔ {MAX_FAILS} failures in a row on {target['id']}. Parked without new attempts; moving to the next safe task. "
                 f"use Retry in FactoryOS Workers to try again. Last: {summary}")
        time.sleep(PAUSE_SECONDS)


if __name__ == "__main__":
    raise SystemExit(main())
